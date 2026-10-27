"""Measuring a unit's timing, against the simulated unit."""
import pytest

from duka_connect import Client, PointKey, Speed
from duka_connect.testing import FakeClock, SimulatedDuka, measure_fan_settling, measure_latency


async def test_every_answered_request_is_timed(client: Client) -> None:
    latency = await measure_latency(client, requests=3, clock=FakeClock())
    assert latency.answers == (0.0, 0.0, 0.0)


async def test_an_unanswered_request_is_counted_as_such(client: Client, unit: SimulatedDuka) -> None:
    unit.answering = False
    assert (await measure_latency(client, requests=2)).unanswered == 2


async def test_the_fans_are_followed_until_they_settle_both_ways(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    targets = {Speed.LOW: 800, Speed.MEDIUM: 1250, Speed.HIGH: 2200}

    async def sleep(seconds: float) -> None:
        clock.advance(seconds)
        rpm = int.from_bytes(unit.values[0x4A], "little")
        target = targets[Speed(unit.values[0x02][0])]
        unit.values[0x4A] = (rpm + (target - rpm) // 2).to_bytes(2, "little")

    settlings = await measure_fan_settling(client, every=0.5, clock=clock, sleep=sleep)
    assert [s.change for s in settlings] == ["LOW to HIGH", "HIGH to LOW"]
    assert all(s.settled_after is not None and s.settled_after > 1.0 for s in settlings)


async def test_the_unit_runs_at_its_own_speed_again_after_a_measurement(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    async def sleep(seconds: float) -> None:
        clock.advance(seconds)

    await measure_fan_settling(client, every=0.5, clock=clock, sleep=sleep)
    assert unit.values[0x02] == bytes([Speed.MEDIUM])


async def test_a_unit_that_is_off_is_not_measured(client: Client) -> None:
    await client.write(PointKey.POWER, False)
    with pytest.raises(ValueError):
        await measure_fan_settling(client)
