"""The client: connecting to a unit, reading what is due, and writing."""
import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any, NoReturn, cast

from event_connect import (
    CannotConnectError,
    Clock,
    DataValue,
    Identity,
    Key,
    NotConnectedError,
    Passes,
    PointsCallback,
    PollRate,
    Quality,
    ReadOnlyError,
    Reachability,
    Refresh,
    Selector,
    Status,
    StatusBoard,
    StatusCallback,
    Subscriptions,
    UnsupportedDeviceError,
    ValueCallback,
    Write,
    WriteKind,
    changed,
    select,
    selector,
    should_poll,
    stale,
    tell,
)
from ._duka_one import PointKey
from ._model import DukaModel
from ._points import Point, Undecodable
from ._protocol import Function, encode_request
from ._transport import UdpLink

_LOGGER = logging.getLogger(__name__)

DEFAULT_PASSWORD = "1111"
"""The password a Duka One has until it is changed in Duka's app."""

_MAX_PARAMETERS_PER_REQUEST = 32

_PAUSE_AFTER_FAILURE = 1.0  # guess
"""Seconds `run()` waits after a poll that raised, so that a failure that repeats is not retried
without a pause."""


class Client:
    """A Duka One on the local network.

    The client never reads on its own: `poll()` reads what is due - the subscribed points on their
    poll rates, and what a write or a change has asked to be read again - and does nothing when
    nothing is; `run()` polls whenever something is due.

    `poll`, `refresh` and `write` raise `NotConnectedError` until `connect()`, and again from
    `disconnect()` until the next `connect()`; `points`, `model` and `seconds_until_next_poll`
    raise it until the first `connect()`.
    """

    def __init__(self, link: UdpLink, *, device_id: str, password: str, model: DukaModel,
                 offline_after_intervals: int, read_only: bool, clock: Clock) -> None:
        """Set up a client of the unit `link` reaches; nothing is sent until `connect()`.

        Args:
            offline_after_intervals: how many reads of the model's fastest poll rate the unit may
                miss before it counts as not answering.
            read_only: refuse every write.
        """
        self.device_id = device_id
        self._password = password
        self._link = link
        self._model = model
        self._clock = clock
        self._read_only = read_only
        self._offline_after_intervals = offline_after_intervals
        self._timing = model.timing
        self._points: dict[str, Point[Any]] = {point.key: point for point in model.points}
        self._readable = tuple(point for point in model.points if point.readable)
        self._sizes = {point.parameter: point.size for point in model.points}
        self._values: dict[str, DataValue[Any]] = {}
        self._subscriptions = Subscriptions()
        self._polled_keys: set[str] = set()
        self._scheduled_keys = frozenset(point.key for point in self._readable)
        self._reachability = self._new_reachability()
        self._scheduler = self._timing.scheduler(self._clock)
        self._scheduler.set_points(self._readable)
        self._wake = asyncio.Event()
        for point in self._readable:
            self._update_polling(point.key)
        self._statuses = StatusBoard(self._clock)
        self._passes = Passes()
        self._connected = False
        self._ever_connected = False

    def _new_reachability(self) -> Reachability:
        return Reachability(self._clock, offline_after_intervals=self._offline_after_intervals,
                            fastest_interval=self._timing.fastest_interval, name=f"The {self._model.name}")

    # ============================================================================== the unit

    @property
    def host(self) -> str:
        """The unit's address."""
        return self._link.host

    @property
    def model(self) -> DukaModel:
        """The unit's model."""
        self._require_connected_once()
        return self._model

    @property
    def identity(self) -> Identity:
        """What the unit reports about itself: its `unit_type`, None until it has."""
        value = self._values.get(PointKey.UNIT_TYPE)
        return {"unit_type": None if value is None else cast(int | None, value.value)}

    @property
    def points(self) -> Mapping[Key[Any], Point[Any]]:
        """Every point the unit has, by its key."""
        self._require_connected_once()
        return cast(Mapping[Key[Any], Point[Any]], self._points)

    def has(self, key: str) -> bool:
        """Whether the unit has `key`; False until the first `connect()`."""
        return self._ever_connected and key in self._points

    def can_read(self, key: str) -> bool:
        """Whether the unit has `key`, and it can be read."""
        return self.has(key) and self._points[key].readable

    def can_write(self, key: str) -> bool:
        """Whether the unit has `key`, and it can be written."""
        return self.has(key) and self._points[key].writable

    def select(self, targets: Selector | Sequence[str]) -> tuple[Point[Any], ...]:
        """The points `targets` selects.

        Raises:
            NotConnectedError: the client has never been connected.
            KeyError: naming every key the unit does not have.
        """
        self._require_connected_once()
        return select(self._model.points, selector(targets))

    def instances(self, label: str) -> tuple[int, ...]:
        """No numbers: a Duka One has no instances of anything."""
        return ()

    @property
    def unavailable_reasons(self) -> Mapping[Key[Any], str]:
        """None: a Duka One has every point of its model."""
        return {}

    async def connect(self) -> None:
        """Read every point once.

        Raises:
            CannotConnectError: the unit did not answer; the address, device id or password
                may be wrong, as a unit does not answer a wrong password.
            UnsupportedDeviceError: the unit answered, but not as a Duka One does.
        """
        self._link.reset()
        if not await self._read(self._readable):
            raise CannotConnectError(
                f"No answer from {self.host}; check its address, device id and password"
            )
        unit_type = self._values.get(PointKey.UNIT_TYPE)
        if unit_type is None or not unit_type.is_good:
            raise UnsupportedDeviceError(f"{self.host} did not report a unit type", {"unit_type": None})
        self._connected = True
        self._ever_connected = True
        self._wake.set()
        _LOGGER.debug("Connected to %s, unit type %s", self.host, unit_type.value)

    async def disconnect(self) -> None:
        """Close the connection: `Status.CONNECTED` turns False, and the values stay as they are."""
        self._connected = False
        await self._link.close()
        self._reachability = self._new_reachability()
        self._statuses.set(Status.CONNECTED, False)
        self._wake.set()

    async def run(self) -> NoReturn:
        """Poll whenever something is due, until cancelled.

        A poll that raises anything but `NotConnectedError` is logged, and polling goes on.

        Raises:
            NotConnectedError: the client is not connected, or is disconnected while it runs.
        """
        while True:
            try:
                await self.poll()
            except NotConnectedError:
                raise
            except Exception:
                _LOGGER.exception("%s could not be polled", self._reachability.name)
                wait = _PAUSE_AFTER_FAILURE
            else:
                wait = self.seconds_until_next_poll()
            # Cleared only now: whatever the poll changed is in the wait just worked out.
            self._wake.clear()
            try:
                async with asyncio.timeout(wait):
                    await self._wake.wait()
            except TimeoutError:
                pass

    # ================================================================================ values

    def value[T](self, key: Key[T]) -> DataValue[T] | None:
        """A point's current value, or None while it has none.

        Raises:
            TypeError: the point's value is of another type than `key` says.
        """
        point = self._points.get(key)
        if point is not None:
            self._check_type(point, key)
        return cast(DataValue[T] | None, self._values.get(key))

    @property
    def values(self) -> Mapping[Key[Any], DataValue[Any]]:
        """Every value read so far, by key."""
        return {self._points[key].key: value for key, value in self._values.items()}

    def status(self, status: Status) -> DataValue[bool]:
        """What the client knows of `status` now.

        `Status.CONNECTED` turns False once the unit has missed the model's fastest poll rate's
        reads `offline_after_intervals` times, or the client is disconnected; `silent_for` says how
        long the unit has been silent so far.
        """
        return self._statuses.value(status)

    @property
    def silent(self) -> bool:
        """Whether the unit left the latest request unanswered."""
        return self._reachability.silent

    @property
    def silent_for(self) -> float:
        """Seconds since the unit first left a request unanswered since its last answer; 0 while
        it answers."""
        return self._reachability.silent_for

    def consecutive_failures(self, key: str) -> int:
        """How many reads of `key` in a row have failed.

        Raises:
            KeyError: the unit has no point `key` that can be read.
        """
        return self._scheduler.consecutive_failures(key)

    def diagnostics(self) -> Mapping[str, object]:
        """Counters for a bug report; never the address, device id or password."""
        return {**self._link.diagnostics(), "silent_for": self._reachability.silent_for}

    # ============================================================================== interest

    def subscribe[T](self, key: Key[T], callback: ValueCallback[T], *, poll: bool = True) -> Callable[[], None]:
        """Call `callback` on every change of `key`'s value or quality, starting with the current
        value. With `poll`, the point is also read on its schedule. Returns the unsubscriber.

        Raises:
            KeyError: a Duka One has no such point.
            TypeError: the point's value is of another type than `key` says, or it is a command,
                which has no value.
        """
        point = self._point(key)
        if not point.readable:
            raise TypeError(f"{key} is a command, and has no value")
        subscriber = self._subscriptions.add(key, cast(ValueCallback[Any], callback), polls=poll)
        self._update_polling(key)
        current = self._values.get(key)
        if current is not None:
            tell(subscriber, None, current)

        def unsubscribe() -> None:
            self._subscriptions.remove(key, subscriber)
            self._update_polling(key)

        return unsubscribe

    def subscribe_status(self, status: Status, callback: StatusCallback) -> Callable[[], None]:
        """Call `callback` on every change of `status`, starting with its current value.

        Returns the unsubscriber.
        """
        return self._statuses.subscribe(status, callback)

    def subscribe_points(self, callback: PointsCallback) -> Callable[[], None]:
        """Call `callback` whenever the points the unit has change; as a Duka One's never do, it is
        never called. Returns the unsubscriber."""
        return lambda: None

    def set_polling(self, key: str, enabled: bool = True) -> None:
        """Poll `key` on its schedule even without a subscriber; False stops that."""
        if enabled:
            self._polled_keys.add(key)
        else:
            self._polled_keys.discard(key)
        self._update_polling(key)

    def set_scheduled_polling(self, enabled: bool) -> None:
        """Whether `poll()` reads on the schedule. Off, it reads only what `refresh()` and writes
        ask for."""
        self._scheduler.set_scheduled(enabled)
        self._wake.set()

    def _update_polling(self, key: str) -> None:
        if key in self._scheduled_keys:
            self._scheduler.set_polled(key, should_poll(self._points[key], self._subscriptions, self._polled_keys))
            self._wake.set()

    # =============================================================================== reading

    async def poll(self) -> None:
        """Read whatever is due. A call made during a pass waits for it, then makes a pass of its own
        only if something is still due.

        A unit that does not answer makes `Status.CONNECTED` false and the points read stale;
        nothing is raised.
        """
        self._require_connected()
        try:
            await self._passes.run(self._pass, due=lambda: bool(self._scheduler.due()))
        finally:
            self._wake.set()

    async def _pass(self) -> None:
        due = self._scheduler.due()
        if due:
            await self._read([self._points[key] for key in due])

    def seconds_until_next_poll(self) -> float | None:
        """Seconds until `poll()` has something to do, 0 if it has now; None if it never will."""
        self._require_connected_once()
        due = self._scheduler.next_due()
        return None if due is None else max(0.0, due - self._clock.monotonic())

    async def refresh(self, targets: PollRate | Selector | Sequence[str] | None = None, *,
                      after: float = 0.0) -> None:
        """Read a poll rate's points, a selection, or everything - now, or `after` seconds from now.

        A command in a selection is left out, as it has no value. A unit that does not answer makes
        `Status.CONNECTED` false and the points read stale; nothing is raised for that.

        Raises:
            KeyError: naming every key of `targets` a Duka One does not have.
        """
        self._require_connected()
        if targets is None:
            points = self._readable
        elif isinstance(targets, PollRate):
            points = tuple(point for point in self._readable if point.poll_rate is targets)
        else:
            points = self._readable_of(selector(targets))
        try:
            if after > 0:
                self._scheduler.refresh([point.key for point in points], after=after, force=True)
                return
            await self._read(points)
        finally:
            self._wake.set()

    async def _read(self, points: Sequence[Point[Any]]) -> bool:
        """Read `points`, and return whether the unit answered every request."""
        parameters = list(dict.fromkeys(point.parameter for point in points))
        answered = True
        for start in range(0, len(parameters), _MAX_PARAMETERS_PER_REQUEST):
            chunk = set(parameters[start:start + _MAX_PARAMETERS_PER_REQUEST])
            chunk_points = [point for point in points if point.parameter in chunk]
            packet = encode_request(
                self.device_id, self._password, Function.READ, [(number, None) for number in sorted(chunk)]
            )
            values = await self._request(packet)
            if values is None:
                answered = False
                for point in chunk_points:
                    previous = self._values.get(point.key)
                    self._store(point, stale(previous, self._clock.now()), previous, success=False)
                continue
            for point in chunk_points:
                if point.parameter in values:
                    previous = self._values.get(point.key)
                    self._store(point, self._decoded(point, values[point.parameter]), previous, success=True)
        return answered

    def _decoded(self, point: Point[Any], data: bytes | None) -> DataValue[Any]:
        now = self._clock.now()
        if data is None:
            return DataValue(None, Quality.MISSING, now)
        try:
            return DataValue(point.to_value(data), Quality.GOOD, now, tuple(data))
        except Undecodable:
            return DataValue(None, Quality.NO_DATA, now, tuple(data))

    def _store(self, point: Point[Any], data: DataValue[Any], previous: DataValue[Any] | None, *,
               success: bool) -> None:
        self._values[point.key] = data
        self._subscriptions.report(point, data)
        trigger = point.on_change
        if trigger is not None and previous is not None and changed(previous, data, trigger.when):
            self._schedule(trigger, trigger.after or 0.0)
        self._scheduler.record(point.key, data, success=success)

    def _readable_of(self, targets: Selector) -> tuple[Point[Any], ...]:
        """The readable points of those `targets` names; a command has no value to read.

        Raises:
            KeyError: naming every key a Duka One does not have.
        """
        return tuple(point for point in select(self._model.points, targets) if point.readable)

    def _schedule(self, refresh: Refresh, after: float) -> None:
        keys = [point.key for point in self._readable_of(refresh.targets)]
        if keys:
            self._scheduler.refresh(keys, after=after, until_stable=refresh.until_stable)

    # =============================================================================== writing

    async def write[T](self, key: Key[T], value: T) -> bool:
        """Write `value` to `key`, and return whether the unit took it. A command is sent with True.

        A setting is answered with the value the unit then has; a command is not answered, so
        it counts as taken once sent.

        Raises:
            ReadOnlyError: the client is read-only.
            NotConnectedError: the client is not connected.
            KeyError: a Duka One has no such point.
            ValueError: the point cannot be written.
            InvalidValueError: the point does not take the value.
            TypeError: the point's value is of another type than `key` says.
        """
        return await self.write_sequence([Write(key, value)])

    async def write_sequence(self, writes: Sequence[Write[Any]]) -> bool:
        """Write several values as one operation, and return whether the unit took all of them.

        Every value is checked before anything is sent. The settings go in one request, in order,
        then the commands.
        """
        self._require_connected()
        settings: list[tuple[Point[Any], bytes]] = []
        commands: list[tuple[Point[Any], bytes]] = []
        for write in writes:
            point = self._writable_point(write.key)
            encoded = point.to_bytes(write.value)
            (commands if point.write_kind is WriteKind.COMMAND else settings).append((point, encoded))
        with self._statuses.holding(Status.WRITE_PENDING):
            try:
                taken = True
                if settings:
                    taken = await self._write_settings(settings)
                if commands and taken:
                    packet = encode_request(
                        self.device_id, self._password, Function.WRITE,
                        [(point.parameter, data) for point, data in commands],
                    )
                    await self._link.send(packet)
                    for point, _ in commands:
                        self._written(point)
                return taken
            finally:
                self._wake.set()

    async def _write_settings(self, settings: list[tuple[Point[Any], bytes]]) -> bool:
        packet = encode_request(
            self.device_id, self._password, Function.WRITE_READ,
            [(point.parameter, data) for point, data in settings],
        )
        values = await self._request(packet)
        if values is None:
            return False
        taken = True
        for point, data in settings:
            answered = values.get(point.parameter)
            if answered != data:
                taken = False
                _LOGGER.debug("%s did not take %s: sent %s, it has %s", self.host, point.key, data.hex(),
                              "none" if answered is None else answered.hex())
            if point.parameter in values and point.readable:
                previous = self._values.get(point.key)
                self._store(point, self._decoded(point, values[point.parameter]), previous, success=True)
            if answered == data:
                self._written(point)
        return taken

    def _written(self, point: Point[Any]) -> None:
        """Schedule what the point's write disturbs."""
        effect = point.on_write
        if effect is None:
            return
        self._schedule(effect, self._timing.on_write_delay(point))

    def _writable_point(self, key: Key[Any]) -> Point[Any]:
        if self._read_only:
            raise ReadOnlyError(f"refused to write '{key}': the client is read-only")
        point = self._point(key)
        if not point.writable:
            raise ValueError(f"'{key}' cannot be written")
        return point

    # ============================================================================= internals

    async def _request(self, packet: bytes) -> Mapping[int, bytes | None] | None:
        """Send a request, and return the unit's answer, or None if it gave none or the breaker
        is open."""
        response = await self._link.request(packet, self.device_id, self._sizes)
        if response is None:
            self._reachability.unanswered()
            self._statuses.set(Status.CONNECTED, self._reachability.reachable)
            return None
        self._reachability.answered(self._scheduler)
        self._statuses.set(Status.CONNECTED, self._reachability.reachable)
        return response.values

    def _point(self, key: Key[Any]) -> Point[Any]:
        point = self._points.get(key)
        if point is None:
            raise KeyError(f"A Duka One has no point {key!r}")
        self._check_type(point, key)
        return point

    @staticmethod
    def _check_type(point: Point[Any], key: Key[Any]) -> None:
        if point.key.type is not key.type:
            raise TypeError(f"{key} is a {point.key.type.__name__}, not a {key.type.__name__}")

    def _require_connected(self) -> None:
        if not self._connected:
            raise NotConnectedError("The client is not connected")

    def _require_connected_once(self) -> None:
        if not self._ever_connected:
            raise NotConnectedError("The client has never been connected; call connect() first")
