"""What a value is, how good it is, and how often it is read."""
from dataclasses import dataclass
from enum import Enum, IntEnum


class Quality(Enum):
    """How far a value can be trusted."""

    GOOD = "good"
    """A value the unit answered."""
    NO_DATA = "no_data"
    """The unit answered a number no state names."""
    STALE = "stale"
    """The last read failed; the value and timestamp are the last good read's."""
    OFFLINE = "offline"
    """The unit has not answered since the client connected."""
    MISSING = "missing"
    """The unit says it does not have this value."""


class PollRate(IntEnum):
    """How often a subscribed point is read, in seconds; `STATIC` is read once, when connecting."""

    FAST = 10
    MEDIUM = 30
    SLOW = 60
    RARE = 900
    STATIC = 0


class Certainty(Enum):
    """How certain it is that a point is right."""

    VERIFIED = "verified"
    """Read on a Duka One."""
    REPORTED = "reported"
    """Taken from the manufacturer's documents; not read on a Duka One."""


class Status(Enum):
    """Whether the unit answers."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True, slots=True)
class DataValue[T]:
    """A point's value, its quality, when it was read, and the bytes the unit answered."""

    value: T | None
    quality: Quality
    timestamp: float | None
    raw: bytes | None


@dataclass(frozen=True, slots=True)
class Key[T]:
    """A point's name, typed by the value reading it gives."""

    name: str
    type: type[T]

    def __str__(self) -> str:
        return self.name


class ClientError(Exception):
    """Something the client could not do."""


class CannotConnectError(ClientError):
    """The unit did not answer. Its address, device id or password may be wrong."""


class UnsupportedDeviceError(ClientError):
    """The unit answered, but is not a Duka One."""

    def __init__(self, message: str, unit_type: int | None) -> None:
        """Keep the unit type the unit reported."""
        super().__init__(message)
        self.unit_type = unit_type


class NotConnectedError(ClientError):
    """The client is not connected."""


class ReadOnlyError(ClientError):
    """The point cannot be written."""


class InvalidValueError(ClientError):
    """The value is outside what the point takes."""


class WriteError(ClientError):
    """The unit did not take a write."""
