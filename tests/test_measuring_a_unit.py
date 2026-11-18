"""Measuring a unit's timing, against the simulated unit."""
import pytest

from duka_connect import Client, PointKey, Speed
from duka_connect.testing import FakeClock, SimulatedDuka, measure_latency
from measure import measure_fan_settling


async def test_every_answered_request_is_timed(client: Client) -> None:
    latency = await measure_latency(client, requests=3, clock=FakeClock())
    assert latency.answers == (0.0, 0.0, 0.0)


async def test_an_unanswered_request_is_counted_as_such(client: Client, unit: SimulatedDuka) -> None:
    unit.answering = False
    assert (await measure_latency(client, requests=2, clock=FakeClock())).unanswered == 2


class _TurningFans(FakeClock):
    """A clock on which the unit's fan turns halfway to its speed's rate during every sleep."""

    TARGETS = {Speed.LOW: 800, Speed.MEDIUM: 1250, Speed.HIGH: 2200}

    def __init__(self, unit: SimulatedDuka) -> None:
        super().__init__(autojump=True)
        self.unit = unit

    async def sleep(self, seconds: float) -> None:
        await super().sleep(seconds)
        rpm = int.from_bytes(self.unit.values[0x4A], "little")
        target = self.TARGETS[Speed(self.unit.values[0x02][0])]
        self.unit.values[0x4A] = (rpm + (target - rpm) // 2).to_bytes(2, "little")


async def test_the_fans_are_followed_until_they_settle_both_ways(client: Client, unit: SimulatedDuka) -> None:
    settlings = await measure_fan_settling(client, speeds=(Speed.LOW, Speed.HIGH), every=0.5, limit=60.0,
                                           tolerance=20.0, clock=_TurningFans(unit))
    assert [s.change for s in settlings] == ["LOW to HIGH", "HIGH to LOW"]
    assert all(s.settled_after is not None and s.settled_after > 1.0 for s in settlings)


async def test_the_unit_runs_at_its_own_speed_again_after_a_measurement(client: Client, unit: SimulatedDuka) -> None:
    await measure_fan_settling(client, speeds=(Speed.LOW, Speed.HIGH), every=0.5, limit=60.0, tolerance=20.0,
                               clock=FakeClock(autojump=True))
    assert unit.values[0x02] == bytes([Speed.MEDIUM])


async def test_a_unit_that_is_off_is_not_measured(client: Client, clock: FakeClock) -> None:
    await client.write(PointKey.POWER, False)
    with pytest.raises(ValueError):
        await measure_fan_settling(client, speeds=(Speed.LOW, Speed.HIGH), every=0.5, limit=60.0, tolerance=20.0,
                                   clock=clock)
