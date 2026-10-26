"""The client: connecting to a unit, reading what is due, and writing."""
import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from ._duka_one import DUKA_ONE, DUKA_ONE_TIMING, PointKey
from ._event_connect import (
    CannotConnectError,
    Clock,
    DataValue,
    Key,
    NotConnectedError,
    PollRate,
    Quality,
    ReadOnlyError,
    Reachability,
    Refresh,
    Selector,
    Status,
    StatusCallback,
    Subscriptions,
    SystemClock,
    Timing,
    UnsupportedDeviceError,
    ValueCallback,
    Write,
    WriteKind,
    changed,
    select,
    selector,
    stale,
    tell,
)
from ._points import Point, Undecodable
from ._protocol import PORT, Function, encode_request
from ._transport import UdpLink

_LOGGER = logging.getLogger(__name__)

DEFAULT_PASSWORD = "1111"
"""The password a Duka One has until it is changed in Duka's app."""

_MAX_PARAMETERS_PER_REQUEST = 32


class Client:
    """A Duka One on the local network.

    The client never reads on its own: `poll()` reads what is due - the subscribed points on their
    poll rates, and what a write or a change has asked to be read again - and does nothing when
    nothing is.
    """

    def __init__(
        self,
        host: str,
        device_id: str,
        password: str = DEFAULT_PASSWORD,
        *,
        port: int = PORT,
        timeout: float = 2.0,
        attempts: int = 3,
        clock: Clock | None = None,
        read_only: bool = False,
        timing: Timing = DUKA_ONE_TIMING,
    ) -> None:
        """Set up a client; nothing is sent until `connect()`.

        Args:
            timeout: seconds to wait for each answer.
            attempts: how many times a request is sent before the unit counts as not answering.
            read_only: refuse every write.
            timing: when points are read, and how long a write takes to show.
        """
        self.device_id = device_id
        self._password = password
        self._link = UdpLink(host, port)
        self._timeout = timeout
        self._attempts = attempts
        self._clock: Clock = clock or SystemClock()
        self._read_only = read_only
        self._points: dict[str, Point[Any]] = {point.key: point for point in DUKA_ONE}
        self._readable = tuple(point for point in DUKA_ONE if point.readable)
        self._sizes = {point.parameter: point.size for point in DUKA_ONE}
        self._values: dict[str, DataValue[Any]] = {}
        self._subscriptions = Subscriptions()
        self._polled_keys: set[str] = set()
        self._scheduled_keys = frozenset(point.key for point in self._readable)
        self._timing = timing
        self._reachability = Reachability(self._clock, timing.offline_after)
        self._scheduler = timing.scheduler(self._clock)
        self._scheduler.set_points(self._readable)
        self._status: dict[Status, DataValue[bool]] = {
            status: DataValue(False, Quality.GOOD, self._clock.now()) for status in Status
        }
        self._status_callbacks: dict[Status, list[StatusCallback]] = {status: [] for status in Status}
        self._poll_lock = asyncio.Lock()
        self._connected = False

    # ============================================================================== the unit

    @property
    def host(self) -> str:
        """The unit's address."""
        return self._link.host

    @property
    def points(self) -> Mapping[Key[Any], Point[Any]]:
        """Every point, by its key."""
        return cast(Mapping[Key[Any], Point[Any]], self._points)

    @property
    def unit_type(self) -> int | None:
        """The unit type the unit reported when connecting."""
        value = self._values.get(PointKey.UNIT_TYPE)
        return None if value is None else cast(int | None, value.value)

    async def connect(self) -> None:
        """Read every point once.

        Raises:
            CannotConnectError: the unit did not answer; the address, device id or password
                may be wrong, as a unit does not answer a wrong password.
            UnsupportedDeviceError: the unit answered, but not as a Duka One does.
        """
        if not await self._read(self._readable):
            raise CannotConnectError(
                f"No answer from {self.host}; check its address, device id and password"
            )
        unit_type = self._values.get(PointKey.UNIT_TYPE)
        if unit_type is None or not unit_type.is_good:
            raise UnsupportedDeviceError(f"{self.host} did not report a unit type", {"unit_type": None})
        self._connected = True
        _LOGGER.debug("Connected to %s, unit type %s", self.host, unit_type.value)

    async def disconnect(self) -> None:
        """Close the connection; the values stay as they are."""
        self._connected = False
        await self._link.close()

    # ================================================================================ values

    def value[T](self, key: Key[T]) -> DataValue[T] | None:
        """A point's current value, or None before it is read.

        Raises:
            KeyError: a Duka One has no such point.
            TypeError: the point's value is of another type than `key` says.
        """
        self._point(key)
        return cast(DataValue[T] | None, self._values.get(key))

    def values(self) -> Mapping[Key[Any], DataValue[Any]]:
        """Every value read so far, by key."""
        return {self._points[key].key: value for key, value in self._values.items()}

    def status(self, status: Status) -> DataValue[bool]:
        """What the client knows of `status` now.

        `Status.CONNECTED` turns false only once the unit has been silent for the timing's
        `offline_after`; `silent_for` says how long it has been so far.
        """
        return self._status[status]

    @property
    def silent(self) -> bool:
        """Whether the unit left the latest request unanswered."""
        return self._reachability.silent

    @property
    def silent_for(self) -> float:
        """Seconds since the unit first left a request unanswered since its last answer; 0 while
        it answers."""
        return self._reachability.silent_for

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
        callbacks = self._status_callbacks[status]
        callbacks.append(callback)
        _tell_status(callback, status, None, self._status[status])

        def unsubscribe() -> None:
            if callback in callbacks:
                callbacks.remove(callback)

        return unsubscribe

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

    def set_poll_interval(self, target: PollRate | str, seconds: float | None) -> float | None:
        """Override how often a poll rate or a key is read; None restores its own interval.

        Returns the interval in effect.
        """
        return self._scheduler.set_poll_interval(target, seconds)

    def _update_polling(self, key: str) -> None:
        if key in self._scheduled_keys:
            self._scheduler.set_polled(key, key in self._polled_keys or self._subscriptions.polled(key))

    # =============================================================================== reading

    async def poll(self) -> None:
        """Read whatever is due. A call made during a pass waits for it instead of starting another.

        A unit that does not answer makes `Status.CONNECTED` false and the points read stale;
        nothing is raised.
        """
        self._require_connected()
        if self._poll_lock.locked():
            async with self._poll_lock:
                return
        async with self._poll_lock:
            due = self._scheduler.due()
            if due:
                await self._read([self._points[key] for key in due])

    def seconds_until_next_poll(self) -> float | None:
        """Seconds until `poll()` has something to do, 0 if it has now; None if it never will."""
        due = self._scheduler.next_due()
        return None if due is None else max(0.0, due - self._clock.monotonic())

    async def refresh(self, targets: PollRate | Selector | Sequence[str] | None = None, *,
                      after: float = 0.0) -> None:
        """Read a poll rate's points, a selection, or everything - now, or `after` seconds from now.

        A unit that does not answer makes `Status.CONNECTED` false and the points read stale;
        nothing is raised.
        """
        self._require_connected()
        if targets is None:
            points = self._readable
        elif isinstance(targets, PollRate):
            points = tuple(point for point in self._readable if point.poll_rate is targets)
        else:
            points = select(self._readable, selector(targets))
        if after > 0:
            self._scheduler.refresh([point.key for point in points], after=after, force=True)
            return
        await self._read(points)

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

    def _schedule(self, refresh: Refresh, after: float) -> None:
        keys = [point.key for point in select(self._readable, refresh.targets)]
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
        self._set_status(Status.WRITE_PENDING, True)
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
            self._set_status(Status.WRITE_PENDING, False)

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
        self._schedule(effect, self._timing.read_back_delay(point))

    def _writable_point(self, key: Key[Any]) -> Point[Any]:
        if self._read_only:
            raise ReadOnlyError(f"refused to write '{key}': the client is read-only")
        point = self._point(key)
        if not point.writable:
            raise ValueError(f"'{key}' cannot be written")
        return point

    # ============================================================================= internals

    async def _request(self, packet: bytes) -> Mapping[int, bytes | None] | None:
        """Send a request, and return the unit's answer, or None if it gave none."""
        try:
            response = await self._link.request(
                packet, self.device_id, self._sizes, self._timeout, self._attempts
            )
        except TimeoutError:
            reachable = self._reachability.unanswered()
            _LOGGER.debug("%s did not answer, silent for %.1f s", self.host, self._reachability.silent_for)
            self._set_status(Status.CONNECTED, reachable)
            return None
        self._set_status(Status.CONNECTED, self._reachability.answered())
        return response.values

    def _set_status(self, status: Status, value: bool) -> None:
        old = self._status[status]
        if old.value is value:
            return
        new = DataValue(value, Quality.GOOD, self._clock.now())
        self._status[status] = new
        for callback in list(self._status_callbacks[status]):
            _tell_status(callback, status, old, new)

    def _point(self, key: Key[Any]) -> Point[Any]:
        point = self._points.get(key)
        if point is None:
            raise KeyError(f"A Duka One has no point {key!r}")
        if point.key.type is not key.type:
            raise TypeError(f"{key} is a {point.key.type.__name__}, not a {key.type.__name__}")
        return point

    def _require_connected(self) -> None:
        if not self._connected:
            raise NotConnectedError("The client is not connected")


def _tell_status(callback: StatusCallback, status: Status, old: DataValue[bool] | None,
                 new: DataValue[bool]) -> None:
    """Call one status subscriber; its error is logged and kept from the others."""
    try:
        callback(status, old, new)
    except Exception:
        _LOGGER.exception("a subscriber to %s raised", status)

