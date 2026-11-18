"""Duka One ventilation units on the local network, over their UDP protocol.

Everything a user needs is here: the client and its values, the points, the errors, and
discovery. A simulated unit for tests is in `duka_connect.testing`.
"""
from importlib.metadata import version as _installed_version

from event_connect import (
    AuthenticationError,
    CannotConnectError,
    Certainty,
    Change,
    ClientError,
    Clock,
    DataValue,
    DeviceClient,
    Identity,
    InvalidValueError,
    Key,
    Labels,
    Limits,
    ModelError,
    NotConnectedError,
    PointsCallback,
    PollRate,
    Quality,
    ReadOnlyError,
    Selector,
    Status,
    StatusCallback,
    Unit,
    UnsupportedDeviceError,
    ValueCallback,
    Write,
    WriteKind,
    WriteRange,
)

from ._client import DEFAULT_PASSWORD, Client
from ._duka import DiscoveredDevice, create_client, discover
from ._duka_one import DUKA_ONE, PointKey
from ._model import DukaModel
from ._points import Point
from ._protocol import PORT
from ._states import AlarmLevel, Speed, TimerMode, VentilationMode

__version__ = _installed_version("duka_connect")
__all__ = [
    "DEFAULT_PASSWORD",
    "DUKA_ONE",
    "PORT",
    "AlarmLevel",
    "AuthenticationError",
    "CannotConnectError",
    "Certainty",
    "Change",
    "Client",
    "ClientError",
    "Clock",
    "DataValue",
    "DeviceClient",
    "DiscoveredDevice",
    "DukaModel",
    "Identity",
    "InvalidValueError",
    "Key",
    "Labels",
    "Limits",
    "ModelError",
    "NotConnectedError",
    "Point",
    "PointKey",
    "PointsCallback",
    "PollRate",
    "Quality",
    "ReadOnlyError",
    "Selector",
    "Speed",
    "Status",
    "StatusCallback",
    "TimerMode",
    "Unit",
    "UnsupportedDeviceError",
    "ValueCallback",
    "VentilationMode",
    "Write",
    "WriteKind",
    "WriteRange",
    "create_client",
    "discover",
]
