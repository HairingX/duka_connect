"""The client: connecting to a unit, reading what is subscribed to, and writing."""
import logging
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, cast

from ._duka_one import DUKA_ONE, PointKey
from ._points import Point, Undecodable
from ._protocol import PORT, Function, encode_request
from ._transport import UdpLink
from ._values import (
    CannotConnectError,
    DataValue,
    InvalidValueError,
    Key,
    NotConnectedError,
    PollRate,
    Quality,
    ReadOnlyError,
    Status,
    UnsupportedDeviceError,
    WriteError,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_PASSWORD = "1111"
"""The password a Duka One has until it is changed in Duka's app."""

type ValueCallback[T] = Callable[[Key[T], DataValue[T] | None, DataValue[T]], None]
"""Told a point's key, its previous value, or `None` the first time, and its new value."""

type StatusCallback = Callable[[Status], None]
"""Told the client's new status."""

_MAX_PARAMETERS_PER_REQUEST = 32


class _Subscription:
    __slots__ = ("callback", "poll")

    def __init__(self, callback: ValueCallback[Any], poll: bool) -> None:
        self.callback = callback
        self.poll = poll


class Client:
    """A Duka One on the local network.

    The client never reads on its own: `poll()` reads the subscribed points that are due, and
    does nothing when none is.
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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Set up a client; nothing is sent until `connect()`.

        Args:
            timeout: seconds to wait for each answer.
            attempts: how many times a request is sent before the unit counts as not answering.
            clock: the monotonic clock polling is planned by.
        """
        self.device_id = device_id
        self._password = password
        self._link = UdpLink(host, port)
        self._timeout = timeout
        self._attempts = attempts
        self._clock = clock
        self._points: dict[str, Point[Any]] = {point.key.name: point for point in DUKA_ONE}
        self._sizes = {point.parameter: point.size for point in DUKA_ONE}
        self._values: dict[str, DataValue[Any]] = {}
        self._read_at: dict[str, float] = {}
        self._intervals: dict[str, float] = {}
        self._subscriptions: dict[str, list[_Subscription]] = {}
        self._status_callbacks: list[StatusCallback] = []
        self._status = Status.DISCONNECTED
        self._connected = False

    @property
    def host(self) -> str:
        """The unit's address."""
        return self._link.host

    @property
    def points(self) -> Mapping[str, Point[Any]]:
        """Every point, by its key's name."""
        return self._points

    @property
    def status(self) -> Status:
        """Whether the unit answered the last request."""
        return self._status

    @property
    def unit_type(self) -> int | None:
        """The unit type the unit reported when connecting."""
        value = self._values.get(PointKey.UNIT_TYPE.name)
        return None if value is None else cast(int | None, value.value)

    async def connect(self) -> None:
        """Read every point once.

        Raises:
            CannotConnectError: the unit did not answer; the address, device id or password
                may be wrong, as a unit does not answer a wrong password.
            UnsupportedDeviceError: the unit answered, but not as a Duka One does.
        """
        readable = [point for point in self._points.values() if not point.command]
        try:
            await self._read(readable)
        except TimeoutError as error:
            raise CannotConnectError(
                f"No answer from {self.host}; check its address, device id and password"
            ) from error
        unit_type = self._values.get(PointKey.UNIT_TYPE.name)
        if unit_type is None or unit_type.quality is not Quality.GOOD:
            raise UnsupportedDeviceError(f"{self.host} did not report a unit type", None)
        self._connected = True
        _LOGGER.debug("Connected to %s, unit type %s", self.host, unit_type.value)

    async def disconnect(self) -> None:
        """Close the connection; the values stay as they are."""
        self._connected = False
        await self._link.close()

    def value[T](self, key: Key[T]) -> DataValue[T] | None:
        """Return a point's current value, or `None` before it is read."""
        self._point(key)
        return cast(DataValue[T] | None, self._values.get(key.name))

    def subscribe[T](
        self, key: Key[T], callback: ValueCallback[T], *, poll: bool = True
    ) -> Callable[[], None]:
        """Call `callback` with the current value, if there is one, and on every change.

        Args:
            poll: whether the point is read on its poll rate for this subscription.

        Returns:
            A function that ends the subscription.
        """
        point = self._point(key)
        if point.command:
            raise TypeError(f"{key} is a command, and has no value")
        subscription = _Subscription(cast(ValueCallback[Any], callback), poll)
        self._subscriptions.setdefault(key.name, []).append(subscription)
        current = self._values.get(key.name)
        if current is not None:
            self._call(subscription, key, None, current)

        def unsubscribe() -> None:
            subscriptions = self._subscriptions.get(key.name, [])
            if subscription in subscriptions:
                subscriptions.remove(subscription)

        return unsubscribe

    def subscribe_status(self, callback: StatusCallback) -> Callable[[], None]:
        """Call `callback` with the status now and on every change.

        Returns:
            A function that ends the subscription.
        """
        self._status_callbacks.append(callback)
        callback(self._status)

        def unsubscribe() -> None:
            if callback in self._status_callbacks:
                self._status_callbacks.remove(callback)

        return unsubscribe

    def set_poll_interval(self, key: Key[Any], seconds: float | None) -> None:
        """Read a point every `seconds`, or on its poll rate again with `None`."""
        self._point(key)
        if seconds is None:
            self._intervals.pop(key.name, None)
        elif seconds <= 0:
            raise ValueError("An interval is longer than 0 seconds")
        else:
            self._intervals[key.name] = seconds

    def _interval(self, point: Point[Any]) -> float | None:
        if point.key.name in self._intervals:
            return self._intervals[point.key.name]
        if point.poll_rate is PollRate.STATIC:
            return None
        return float(point.poll_rate)

    def _due(self, now: float) -> list[Point[Any]]:
        due: list[Point[Any]] = []
        for name, subscriptions in self._subscriptions.items():
            if not any(subscription.poll for subscription in subscriptions):
                continue
            point = self._points[name]
            interval = self._interval(point)
            if interval is None:
                continue
            read_at = self._read_at.get(name)
            if read_at is None or now - read_at >= interval:
                due.append(point)
        return due

    def seconds_until_next_poll(self) -> float | None:
        """Return how long until a subscribed point is due, or `None` when none will be."""
        now = self._clock()
        waits: list[float] = []
        for name, subscriptions in self._subscriptions.items():
            if not any(subscription.poll for subscription in subscriptions):
                continue
            interval = self._interval(self._points[name])
            if interval is None:
                continue
            read_at = self._read_at.get(name)
            waits.append(0.0 if read_at is None else max(0.0, read_at + interval - now))
        return min(waits, default=None)

    async def poll(self) -> None:
        """Read the subscribed points that are due.

        A unit that does not answer makes the status `DISCONNECTED` and the points read stale;
        nothing is raised.
        """
        self._require_connected()
        due = self._due(self._clock())
        if not due:
            return
        try:
            await self._read(due)
        except TimeoutError:
            _LOGGER.debug("%s did not answer a poll", self.host)

    async def refresh(self, keys: Iterable[Key[Any]] | None = None) -> None:
        """Read points now: those given, or every point.

        Raises:
            CannotConnectError: the unit did not answer.
        """
        self._require_connected()
        if keys is None:
            points = [point for point in self._points.values() if not point.command]
        else:
            points = [self._point(key) for key in keys]
        try:
            await self._read([point for point in points if not point.command])
        except TimeoutError as error:
            raise CannotConnectError(f"No answer from {self.host}") from error

    async def write[T](self, key: Key[T], value: T) -> None:
        """Write a value, or run a command with the value `None`.

        Raises:
            ReadOnlyError: the point cannot be written.
            InvalidValueError: the value is outside the point's limits.
            WriteError: the unit did not take the value.
            CannotConnectError: the unit did not answer.
        """
        await self.write_many([(key, value)])

    async def write_many(self, writes: Sequence[tuple[Key[Any], Any]]) -> None:
        """Write several values in one request, in order.

        Raises:
            ReadOnlyError: a point cannot be written.
            InvalidValueError: a value is outside its point's limits.
            WriteError: the unit did not take a value.
            CannotConnectError: the unit did not answer.
        """
        self._require_connected()
        settings: list[tuple[Point[Any], bytes]] = []
        commands: list[tuple[Point[Any], bytes]] = []
        for key, value in writes:
            point = self._point(key)
            if not point.writable:
                raise ReadOnlyError(f"{key} cannot be written")
            if value is not None and not isinstance(value, point.key.type):
                raise InvalidValueError(f"{key} takes a {point.key.type.__name__}, not {value!r}")
            encoded = point.to_bytes(value)
            (commands if point.command else settings).append((point, encoded))
        try:
            if settings:
                await self._write_settings(settings)
            if commands:
                # The unit does not answer a command; what it did is read back.
                packet = encode_request(
                    self.device_id, self._password, Function.WRITE,
                    [(point.parameter, data) for point, data in commands],
                )
                await self._link.send(packet)
                await self._read_following([point for point, _ in commands], frozenset())
        except TimeoutError as error:
            raise CannotConnectError(f"No answer from {self.host}") from error

    async def _write_settings(self, settings: list[tuple[Point[Any], bytes]]) -> None:
        packet = encode_request(
            self.device_id, self._password, Function.WRITE_READ,
            [(point.parameter, data) for point, data in settings],
        )
        response = await self._request(packet)
        refused: list[str] = []
        for point, data in settings:
            answered = response.get(point.parameter)
            if answered != data:
                refused.append(f"{point.key} (sent {data.hex()}, unit has {answered.hex() if answered else 'none'})")
        written = [point for point, _ in settings]
        changed = self._store(response, written)
        await self._read_following(changed, frozenset(point.key.name for point in written))
        if refused:
            raise WriteError("The unit did not take " + ", ".join(refused))

    async def _request(self, packet: bytes) -> Mapping[int, bytes | None]:
        try:
            response = await self._link.request(
                packet, self.device_id, self._sizes, self._timeout, self._attempts
            )
        except TimeoutError:
            self._set_status(Status.DISCONNECTED)
            raise
        self._set_status(Status.CONNECTED)
        return response.values

    async def _read(self, points: Sequence[Point[Any]], done: frozenset[str] = frozenset()) -> None:
        """Read points, then read on from those whose value changed."""
        changed: list[Point[Any]] = []
        parameters = list(dict.fromkeys(point.parameter for point in points))
        for start in range(0, len(parameters), _MAX_PARAMETERS_PER_REQUEST):
            chunk = parameters[start:start + _MAX_PARAMETERS_PER_REQUEST]
            chunk_points = [point for point in points if point.parameter in chunk]
            packet = encode_request(
                self.device_id, self._password, Function.READ, [(number, None) for number in chunk]
            )
            try:
                values = await self._request(packet)
            except TimeoutError:
                self._mark_failed(chunk_points)
                raise
            changed += self._store(values, chunk_points)
        await self._read_following(changed, done | {point.key.name for point in points})

    async def _read_following(self, points: Sequence[Point[Any]], done: frozenset[str]) -> None:
        """Read the points that `points` are followed by, except those in `done`."""
        following = {
            key.name: self._points[key.name]
            for point in points for key in point.then_read
            if key.name in self._points and key.name not in done
        }
        if following:
            await self._read(list(following.values()), done)

    def _store(self, values: Mapping[int, bytes | None], points: Sequence[Point[Any]]) -> list[Point[Any]]:
        """Store the values read, and return the points whose value changed from a good one."""
        changed: list[Point[Any]] = []
        now = self._clock()
        stamp = time.time()
        for point in points:
            self._read_at[point.key.name] = now
            if point.parameter not in values:
                continue
            data = values[point.parameter]
            if data is None:
                new: DataValue[Any] = DataValue(None, Quality.MISSING, stamp, None)
            else:
                try:
                    new = DataValue(point.decode(data), Quality.GOOD, stamp, data)
                except (Undecodable, IndexError):
                    new = DataValue(None, Quality.NO_DATA, stamp, data)
            old = self._values.get(point.key.name)
            if old is not None and old.quality is Quality.GOOD and old.value != new.value:
                changed.append(point)
            self._update(point.key, new)
        return changed

    def _mark_failed(self, points: Sequence[Point[Any]]) -> None:
        now = self._clock()
        for point in points:
            self._read_at[point.key.name] = now
            old = self._values.get(point.key.name)
            if old is None or old.quality is Quality.OFFLINE:
                new: DataValue[Any] = DataValue(None, Quality.OFFLINE, None, None)
            elif old.quality is Quality.GOOD:
                new = DataValue(old.value, Quality.STALE, old.timestamp, old.raw)
            else:
                continue
            self._update(point.key, new)

    def _update(self, key: Key[Any], new: DataValue[Any]) -> None:
        old = self._values.get(key.name)
        self._values[key.name] = new
        if old is not None and (old.value, old.quality) == (new.value, new.quality):
            return
        for subscription in list(self._subscriptions.get(key.name, ())):
            self._call(subscription, key, old, new)

    @staticmethod
    def _call(
        subscription: _Subscription, key: Key[Any], old: DataValue[Any] | None, new: DataValue[Any]
    ) -> None:
        try:
            subscription.callback(key, old, new)
        except Exception:
            _LOGGER.exception("A callback for %s raised", key)

    def _set_status(self, status: Status) -> None:
        if status is self._status:
            return
        self._status = status
        for callback in list(self._status_callbacks):
            try:
                callback(status)
            except Exception:
                _LOGGER.exception("A status callback raised")

    def _point(self, key: Key[Any]) -> Point[Any]:
        point = self._points.get(key.name)
        if point is None:
            raise KeyError(f"A Duka One has no point {key}")
        if point.key.type is not key.type:
            raise TypeError(f"{key} is a {point.key.type.__name__}, not a {key.type.__name__}")
        return point

    def _require_connected(self) -> None:
        if not self._connected:
            raise NotConnectedError("The client is not connected")
