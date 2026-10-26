"""What a point is: a parameter of the unit, and how its bytes become a value."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, time
from enum import IntEnum

from ._values import Certainty, InvalidValueError, Key, PollRate


class Undecodable(Exception):
    """Bytes that name no value of the point."""


@dataclass(frozen=True, slots=True)
class Point[T]:
    """One value the unit has.

    A point with `encode` can be written; a `command` point is written to make the unit do
    something, and has no value to read.
    """

    key: Key[T]
    parameter: int
    size: int
    decode: Callable[[bytes], T]
    encode: Callable[[T], bytes] | None = None
    poll_rate: PollRate = PollRate.MEDIUM
    unit: str | None = None
    minimum: int | None = None
    maximum: int | None = None
    command: bool = False
    certainty: Certainty = Certainty.REPORTED

    @property
    def writable(self) -> bool:
        """Whether the point can be written."""
        return self.encode is not None

    def to_bytes(self, value: T) -> bytes:
        """Encode a value to write.

        Raises:
            InvalidValueError: the value is outside the point's limits.
        """
        if self.encode is None:
            raise TypeError(f"{self.key} cannot be written")
        if isinstance(value, int) and not isinstance(value, (bool, IntEnum)):
            if self.minimum is not None and value < self.minimum:
                raise InvalidValueError(f"{self.key} is at least {self.minimum}, not {value}")
            if self.maximum is not None and value > self.maximum:
                raise InvalidValueError(f"{self.key} is at most {self.maximum}, not {value}")
        return self.encode(value)


def decode_bool(data: bytes) -> bool:
    """Read a flag: 0 is off, anything else on."""
    return data[0] != 0


def encode_bool(value: bool) -> bytes:
    """Write a flag."""
    return b"\x01" if value else b"\x00"


def decode_int(data: bytes) -> int:
    """Read an unsigned number, least significant byte first."""
    return int.from_bytes(data, "little")


def int_encoder(size: int) -> Callable[[int], bytes]:
    """Return an encoder of an unsigned number of `size` bytes, least significant first."""

    def encode(value: int) -> bytes:
        try:
            return value.to_bytes(size, "little")
        except OverflowError as error:
            raise InvalidValueError(f"{value} does not fit in {size} bytes") from error

    return encode


def state_decoder[E: IntEnum](states: type[E]) -> Callable[[bytes], E]:
    """Return a decoder of a one-byte state."""

    def decode(data: bytes) -> E:
        try:
            return states(data[0])
        except ValueError as error:
            raise Undecodable(f"{data[0]} is not a {states.__name__}") from error

    return decode


def encode_state(value: IntEnum) -> bytes:
    """Write a one-byte state."""
    return bytes([int(value)])


def decode_minutes_hours_days(data: bytes) -> int:
    """Read a duration sent as minutes, hours and days, in minutes."""
    return data[0] + data[1] * 60 + data[2] * 24 * 60


def decode_seconds_minutes_hours(data: bytes) -> int:
    """Read a duration sent as seconds, minutes and hours, in seconds."""
    return data[0] + data[1] * 60 + data[2] * 3600


def decode_operating_minutes(data: bytes) -> int:
    """Read the time the unit has run, sent as minutes, hours and days in two bytes, in minutes."""
    return data[0] + data[1] * 60 + int.from_bytes(data[2:4], "little") * 24 * 60


def decode_firmware_version(data: bytes) -> str:
    """Read the firmware's version, as `major.minor`."""
    return f"{data[0]}.{data[1]}"


def decode_firmware_date(data: bytes) -> date:
    """Read the firmware's date, sent after its version as day, month and a two-byte year."""
    try:
        return date(int.from_bytes(data[4:6], "little"), data[3], data[2])
    except ValueError as error:
        raise Undecodable(f"{data.hex()} is not a date") from error


def decode_nothing(data: bytes) -> None:
    """Read a command point, which has no value."""
    return None


def encode_nothing(value: None) -> bytes:
    """Write a command point: the unit ignores the byte sent."""
    return b"\x00"


def decode_clock_time(data: bytes) -> time:
    """Read the unit's clock, sent as seconds, minutes and hours."""
    try:
        return time(data[2], data[1], data[0])
    except ValueError as error:
        raise Undecodable(f"{data.hex()} is not a time of day") from error


def encode_clock_time(value: time) -> bytes:
    """Write the unit's clock as seconds, minutes and hours."""
    return bytes([value.second, value.minute, value.hour])


def decode_clock_date(data: bytes) -> date:
    """Read the unit's calendar, sent as day, weekday, month and the year in the century."""
    try:
        return date(2000 + data[3], data[2], data[0])
    except ValueError as error:
        raise Undecodable(f"{data.hex()} is not a date") from error


def encode_clock_date(value: date) -> bytes:
    """Write the unit's calendar as day, weekday (1 Monday to 7 Sunday), month and year in the century.

    Raises:
        InvalidValueError: the year is outside 2000 to 2099, which the unit cannot hold.
    """
    if not 2000 <= value.year <= 2099:
        raise InvalidValueError(f"The unit holds years 2000 to 2099, not {value.year}")
    return bytes([value.day, value.isoweekday(), value.month, value.year - 2000])


def decode_minutes_hours(data: bytes) -> int:
    """Read a duration sent as minutes and hours, in minutes."""
    return data[0] + data[1] * 60


def encode_minutes_hours(value: int) -> bytes:
    """Write a duration in minutes as minutes and hours."""
    return bytes([value % 60, value // 60])


def decode_ipv4(data: bytes) -> str:
    """Read an IPv4 address, sent as its four numbers in the order they are written."""
    return ".".join(str(byte) for byte in data[:4])


def encode_execute(value: None) -> bytes:
    """Write a command that is run by the value 1."""
    return b"\x01"
