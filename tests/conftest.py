"""Fixtures: a simulated Duka One, and a client connected to it."""
from collections.abc import AsyncIterator

import pytest

from duka_connect import Client
from duka_connect.testing import SimulatedDuka


class FakeClock:
    """A monotonic clock the test moves."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
async def unit() -> AsyncIterator[SimulatedDuka]:
    simulated = SimulatedDuka()
    await simulated.start()
    yield simulated
    simulated.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_client(unit: SimulatedDuka, clock: FakeClock, password: str | None = None) -> Client:
    return Client(
        "127.0.0.1", unit.device_id, unit.password if password is None else password,
        port=unit.port, timeout=0.2, attempts=1, command_delay=0.0, clock=clock,
    )


@pytest.fixture
async def client(unit: SimulatedDuka, clock: FakeClock) -> AsyncIterator[Client]:
    connected = make_client(unit, clock)
    await connected.connect()
    yield connected
    await connected.disconnect()
