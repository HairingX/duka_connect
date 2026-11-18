"""What a model of a unit on the Duka One's protocol says: its points, and how it behaves."""
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from event_connect import PollRate, Timing

from ._points import Point


@dataclass(frozen=True, kw_only=True, eq=False)
class DukaModel:
    """A model of a unit reached over the Duka One's protocol, checked when it is made.

    Raises:
        ValueError: naming every problem: a key used twice, a poll rate a readable point uses
            without an interval, an interval no readable point uses, and an interval or a wait
            that is not a finite number in its range.
    """

    name: str
    """The model's name, as its manufacturer writes it."""
    manufacturer: str
    """Who makes it."""
    points: tuple[Point[Any], ...]
    """Every point the model has."""
    poll_intervals: Mapping[PollRate, float]
    """Seconds between reads for each poll rate its readable points use, but `PollRate.STATIC`,
    which is never read on a timer."""
    read_back_after: float
    """Seconds from a write until a read shows it."""
    answers_within: float
    """Seconds within which the unit answers a request."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "poll_intervals", MappingProxyType(dict(self.poll_intervals)))
        keys = [str(point.key) for point in self.points]
        problems = [f"the key '{key}' is used twice" for key in dict.fromkeys(keys) if keys.count(key) > 1]
        used = {point.poll_rate for point in self.points if point.readable}
        for rate in PollRate:
            if rate is PollRate.STATIC:
                if rate in self.poll_intervals:
                    problems.append("STATIC is never read on a timer, and takes no interval")
            elif rate in used and rate not in self.poll_intervals:
                problems.append(f"{rate.name} is used by a point but has no interval")
            elif rate in self.poll_intervals and rate not in used:
                problems.append(f"{rate.name} has an interval but no point is read at it")
        problems += [f"the interval of {rate.name} must be a finite number above 0, got {seconds}"
                     for rate, seconds in self.poll_intervals.items() if not _positive(seconds)]
        if not (math.isfinite(self.read_back_after) and self.read_back_after >= 0):
            problems.append(f"read_back_after must be a finite number of at least 0, got {self.read_back_after}")
        if not _positive(self.answers_within):
            problems.append(f"answers_within must be a finite number above 0, got {self.answers_within}")
        if problems:
            raise ValueError(f"The {self.name} model: " + "; ".join(problems))

    @property
    def timing(self) -> Timing:
        """When the model's points are read, and how long its writes take to show."""
        return Timing(poll_intervals=self.poll_intervals, read_back_after=self.read_back_after)


def _positive(seconds: float) -> bool:
    return math.isfinite(seconds) and seconds > 0
