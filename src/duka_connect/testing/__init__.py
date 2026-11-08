"""A simulated Duka One and a clock that moves only when told, for testing code that uses this
library without a unit; and measurements of a real unit's timing."""
from event_connect.testing import FakeClock, Latency, Settling, recommended_refresh

from .._measure import measure_fan_settling, measure_latency
from ._simulator import DEFAULT_VALUES, FILTER_DAYS, SimulatedDuka

__all__ = [
    "DEFAULT_VALUES",
    "FILTER_DAYS",
    "FakeClock",
    "Latency",
    "Settling",
    "SimulatedDuka",
    "measure_fan_settling",
    "measure_latency",
    "recommended_refresh",
]
