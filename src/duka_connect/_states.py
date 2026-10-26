"""The states a Duka One's points take."""
from enum import IntEnum


class Speed(IntEnum):
    """The fan speed: one of three preset speeds, or the manual speed."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    MANUAL = 255


class VentilationMode(IntEnum):
    """Which way the air moves."""

    VENTILATION = 0
    """One way, all the time: in or out, as the unit's DIP switch sets it."""
    HEAT_RECOVERY = 1
    """Alternating in and out through the heat exchanger, 70 seconds each way."""
    SUPPLY = 2
    """Supply only: outdoor air is brought into the room."""


class TimerMode(IntEnum):
    """Which timed mode runs."""

    OFF = 0
    NIGHT = 1
    PARTY = 2


class AlarmLevel(IntEnum):
    """What the unit's alarm indicator shows."""

    NONE = 0
    ALARM = 1
    WARNING = 2
