"""Measuring a real Duka One's timing: how long it takes to answer, and how long its fans take to
reach a new speed."""
import asyncio
from collections.abc import Awaitable, Callable

from ._client import Client
from ._duka_one import PointKey
from ._event_connect import CannotConnectError, Clock, Quality, SystemClock
from ._event_connect.testing import Latency, Settling
from ._states import Speed

_AGREEING = 3
"""Readings in a row within the tolerance that end a measurement of settling."""


async def measure_latency(client: Client, *, requests: int = 20, clock: Clock | None = None) -> Latency:
    """Read one point `requests` times, one after another, and time each answer.

    A request the unit does not answer takes the client's timeout for each of its attempts.
    """
    timer = clock or SystemClock()
    answers: list[float | None] = []
    for _ in range(requests):
        started = timer.monotonic()
        await client.refresh([PointKey.POWER])
        power = client.value(PointKey.POWER)
        answered = power is not None and power.quality is not Quality.STALE
        answers.append(timer.monotonic() - started if answered else None)
    return Latency(tuple(answers))


async def measure_fan_settling(
    client: Client,
    *,
    speeds: tuple[Speed, Speed] = (Speed.LOW, Speed.HIGH),
    every: float = 0.5,
    limit: float = 60.0,
    tolerance: float = 20.0,
    clock: Clock | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[Settling, ...]:
    """Change the speed from the first of `speeds` to the second and back, and read the fan's speed
    every `every` seconds after each change until it settles, for at most `limit` seconds.

    The unit runs at the first speed before it is measured, and at the speed it had before once it
    has been, whatever happens.

    Raises:
        ValueError: the unit is off, so its fans do not turn.
        CannotConnectError: the unit did not take a speed.
    """
    power = client.value(PointKey.POWER)
    if power is None or power.value is not True:
        raise ValueError("Turn the unit on: its fans do not turn while it is off")
    timer = clock or SystemClock()
    original = client.value(PointKey.SPEED)
    first, second = speeds
    try:
        await _settle(client, first, every, limit, tolerance, timer, sleep)
        return (
            await _settle(client, second, every, limit, tolerance, timer, sleep, f"{first.name} to {second.name}"),
            await _settle(client, first, every, limit, tolerance, timer, sleep, f"{second.name} to {first.name}"),
        )
    finally:
        if original is not None and original.value is not None:
            await client.write(PointKey.SPEED, original.value)


async def _settle(
    client: Client, speed: Speed, every: float, limit: float, tolerance: float, timer: Clock,
    sleep: Callable[[float], Awaitable[None]], change: str = "",
) -> Settling:
    if not await client.write(PointKey.SPEED, speed):
        raise CannotConnectError(f"The unit did not take the speed {speed.name}")
    started = timer.monotonic()
    readings: list[tuple[float, float]] = []
    while timer.monotonic() - started < limit:
        await sleep(every)
        await client.refresh([PointKey.FAN_RPM])
        rpm = client.value(PointKey.FAN_RPM)
        if rpm is not None and rpm.is_good and rpm.value is not None:
            readings.append((timer.monotonic() - started, float(rpm.value)))
        recent = [value for _, value in readings[-_AGREEING:]]
        if len(recent) == _AGREEING and max(recent) - min(recent) <= tolerance:
            break
    return Settling(change, tuple(readings), tolerance)

