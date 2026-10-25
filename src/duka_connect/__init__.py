"""Duka One ventilation units on the local network, over their UDP protocol.

Everything a user needs is here: the client and its values, the points, the errors, and
discovery. A simulated unit for tests is in `duka_connect.testing`.
"""
from importlib.metadata import version as _installed_version

from ._client import DEFAULT_PASSWORD, Client, StatusCallback, ValueCallback
from ._discovery import DiscoveredDevice, discover
from ._duka_one import DUKA_ONE, PointKey
from ._points import Point
from ._protocol import PORT, ProtocolError
from ._states import AlarmLevel, Speed, TimerMode, VentilationMode
from ._values import (
    CannotConnectError,
    Certainty,
    ClientError,
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

__version__ = _installed_version("duka_connect")
__all__ = [
    "DEFAULT_PASSWORD",
    "DUKA_ONE",
    "PORT",
    "AlarmLevel",
    "CannotConnectError",
    "Certainty",
    "Client",
    "ClientError",
    "DataValue",
    "DiscoveredDevice",
    "InvalidValueError",
    "Key",
    "NotConnectedError",
    "Point",
    "PointKey",
    "PollRate",
    "ProtocolError",
    "Quality",
    "ReadOnlyError",
    "Speed",
    "Status",
    "StatusCallback",
    "TimerMode",
    "UnsupportedDeviceError",
    "ValueCallback",
    "VentilationMode",
    "WriteError",
    "discover",
]
