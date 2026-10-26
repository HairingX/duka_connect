"""Support for testing what is built on these points: a clock that moves only when told, and a
point without a protocol."""
from ._clock import FakeClock
from ._point import FakePoint

__all__ = ["FakeClock", "FakePoint"]
