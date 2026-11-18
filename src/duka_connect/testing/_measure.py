"""Measuring how long a real Duka One takes to answer, without changing anything on it."""
from event_connect import Clock, Quality
from event_connect.testing import Latency

from .._client import Client
from .._duka_one import PointKey


async def measure_latency(client: Client, *, requests: int, clock: Clock) -> Latency:
    """Read one point `requests` times, one after another, and time each answer by `clock`.

    A request the unit does not answer takes the client's wait for each of its sends.
    """
    answers: list[float | None] = []
    for _ in range(requests):
        started = clock.monotonic()
        await client.refresh([PointKey.POWER])
        power = client.value(PointKey.POWER)
        answered = power is not None and power.quality is not Quality.STALE
        answers.append(clock.monotonic() - started if answered else None)
    return Latency(tuple(answers))
