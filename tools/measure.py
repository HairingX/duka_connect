"""Measuring a real Duka One's timing, changing its speed while it runs: never run in CI.

Set DUKA_HOST, DUKA_DEVICE_ID and, if it is not the default, DUKA_PASSWORD, turn the unit on, and
run `python tools/measure.py`. It prints how long the unit takes to answer, how long its fans take
to reach a new speed, and an `after` and `until_stable` that would follow them.
"""
import asyncio
import os

from event_connect import SystemClock

from duka_connect import DEFAULT_PASSWORD, CannotConnectError, Client, Clock, PointKey, Speed, create_client
from duka_connect.testing import Settling, measure_latency, recommended_refresh

_AGREEING = 3
"""Readings in a row within the tolerance that end a measurement of settling."""


async def measure_fan_settling(
    client: Client,
    *,
    speeds: tuple[Speed, Speed],
    every: float,
    limit: float,
    tolerance: float,
    clock: Clock,
) -> tuple[Settling, ...]:
    """Change the speed from the first of `speeds` to the second and back, and read the fan's speed
    every `every` seconds of `clock` after each change until it settles, for at most `limit`
    seconds.

    The unit runs at the first speed before it is measured, and at the speed it had before once it
    has been, whatever happens.

    Raises:
        ValueError: the unit is off, so its fans do not turn.
        CannotConnectError: the unit did not take a speed.
    """
    power = client.value(PointKey.POWER)
    if power is None or power.value is not True:
        raise ValueError("Turn the unit on: its fans do not turn while it is off")
    original = client.value(PointKey.SPEED)
    first, second = speeds
    try:
        await _settle(client, first, every, limit, tolerance, clock)
        return (
            await _settle(client, second, every, limit, tolerance, clock, f"{first.name} to {second.name}"),
            await _settle(client, first, every, limit, tolerance, clock, f"{second.name} to {first.name}"),
        )
    finally:
        if original is not None and original.value is not None:
            await client.write(PointKey.SPEED, original.value)


async def _settle(
    client: Client, speed: Speed, every: float, limit: float, tolerance: float, clock: Clock,
    change: str = "",
) -> Settling:
    if not await client.write(PointKey.SPEED, speed):
        raise CannotConnectError(f"The unit did not take the speed {speed.name}")
    started = clock.monotonic()
    readings: list[tuple[float, float]] = []
    while clock.monotonic() - started < limit:
        await clock.sleep(every)
        await client.refresh([PointKey.FAN_RPM])
        rpm = client.value(PointKey.FAN_RPM)
        if rpm is not None and rpm.is_good and rpm.value is not None:
            readings.append((clock.monotonic() - started, float(rpm.value)))
        recent = [value for _, value in readings[-_AGREEING:]]
        if len(recent) == _AGREEING and max(recent) - min(recent) <= tolerance:
            break
    return Settling(change, tuple(readings), tolerance)


async def main() -> None:
    """Measure the unit the environment names, and print what was found."""
    clock = SystemClock()
    client = create_client(
        host=os.environ["DUKA_HOST"], device_id=os.environ["DUKA_DEVICE_ID"],
        password=os.environ.get("DUKA_PASSWORD", DEFAULT_PASSWORD), clock=clock,
    )
    await client.connect()
    try:
        print(await measure_latency(client, requests=20, clock=clock))
        every = 0.5
        settlings = await measure_fan_settling(
            client, speeds=(Speed.LOW, Speed.HIGH), every=every, limit=60.0, tolerance=20.0, clock=clock,
        )
        for settling in settlings:
            print(settling)
        print(recommended_refresh(settlings, every, margin=2))
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
