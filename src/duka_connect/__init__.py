"""Duka One ventilation units on the local network, over their UDP protocol.

Everything a user needs is here: the client and its values, the points, the errors, and
discovery. A simulated unit for tests is in `duka_connect.testing`.
"""
from importlib.metadata import version as _installed_version

from ._client import DEFAULT_PASSWORD, Client
from ._discovery import DiscoveredDevice, discover
from ._duka_one import DUKA_ONE, DUKA_ONE_BREAKER, DUKA_ONE_TIMING, PointKey
from event_connect import (
    NO_RETRY,
    CircuitBreaker,
    CannotConnectError,
    Certainty,
    Change,
    ClientError,
    Clock,
    DataValue,
    Fixed,
    InvalidValueError,
    Key,
    Labels,
    Limits,
    NotConnectedError,
    PollRate,
    Quality,
    ReadOnlyError,
    Refresh,
    Retry,
    Status,
    StatusCallback,
    SystemClock,
    Timing,
    Unit,
    UnsupportedDeviceError,
    ValueCallback,
    Write,
    WriteKind,
    WriteRange,
)
from ._points import Point
from ._protocol import PORT, ProtocolError
from ._states import AlarmLevel, Speed, TimerMode, VentilationMode

__version__ = _installed_version("duka_connect")
__all__ = [
    "DEFAULT_PASSWORD",
    "DUKA_ONE",
    "DUKA_ONE_BREAKER",
    "DUKA_ONE_TIMING",
    "NO_RETRY",
    "PORT",
    "AlarmLevel",
    "CannotConnectError",
    "Certainty",
    "Change",
    "CircuitBreaker",
    "Client",
    "ClientError",
    "Clock",
    "DataValue",
    "DiscoveredDevice",
    "Fixed",
    "InvalidValueError",
    "Key",
    "Labels",
    "Limits",
    "NotConnectedError",
    "Point",
    "PointKey",
    "PollRate",
    "ProtocolError",
    "Quality",
    "ReadOnlyError",
    "Refresh",
    "Retry",
    "Speed",
    "Status",
    "StatusCallback",
    "SystemClock",
    "TimerMode",
    "Timing",
    "Unit",
    "UnsupportedDeviceError",
    "ValueCallback",
    "VentilationMode",
    "Write",
    "WriteKind",
    "WriteRange",
    "discover",
]
