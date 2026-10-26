"""How a library plans the reads of its devices: one profile, set by the library, that a client
can be given another of."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ._clock import Clock
from ._point import DEFAULT_INTERVALS, Point, PollRate
from ._scheduler import Scheduler


@dataclass(frozen=True)
class Timing:
    """When a device's points are read, and how long its writes take to show.

    A library sets one for its devices, as measured on them; a client may be given another.
    """
    poll_intervals: Mapping[PollRate, float | None] = field(default_factory=lambda: DEFAULT_INTERVALS)
    """Seconds between reads per poll rate; a rate left out keeps its default."""
    min_poll_interval: float = 0.0
    """The shortest interval any point may be read at, however it is overridden."""
    read_back_after: float = 1.0
    """Seconds from a write until a read shows it, unless a point says otherwise."""
    coalesce_window: float = 2.0
    """Seconds ahead a read is brought forward to share a request with one due now.

    Wide enough to gather what falls due close together, so that a slow device is not asked
    twice in quick succession; narrow against the shortest interval, so that nothing is read much
    early.
    """

    def __post_init__(self) -> None:
        object.__setattr__(self, "poll_intervals", MappingProxyType(dict(self.poll_intervals)))
        for name in ("min_poll_interval", "read_back_after", "coalesce_window"):
            seconds: float = getattr(self, name)
            if not (math.isfinite(seconds) and seconds >= 0):
                raise ValueError(f"{name} must be a finite number >= 0, got {seconds}")
        shortest = min((s for s in self.poll_intervals.values() if s is not None), default=None)
        if shortest is not None and self.coalesce_window >= shortest:
            raise ValueError(f"coalesce_window {self.coalesce_window}s must be shorter than the "
                             f"shortest poll interval, {shortest}s, or every read is brought forward")

    def scheduler(self, clock: Clock) -> Scheduler:
        """A scheduler that plans by this timing."""
        return Scheduler(clock, self.poll_intervals, min_poll_interval=self.min_poll_interval,
                         coalesce_window=self.coalesce_window)

    def read_back_delay(self, point: Point[Any]) -> float:
        """Seconds after writing `point` before what its write disturbs is read."""
        if point.on_write is not None and point.on_write.after is not None:
            return point.on_write.after
        return point.read_back_after if point.read_back_after is not None else self.read_back_after


DEFAULT_TIMING = Timing()
"""A timing for a device nothing has been measured on: the default poll intervals, a second for a
write to show, and reads within two seconds of each other gathered into one request."""
