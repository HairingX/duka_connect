"""Discovery against a simulated Duka One."""
import pytest

import duka_connect._duka
from duka_connect import DiscoveredDevice, discover
from duka_connect.testing import SimulatedDuka


@pytest.fixture(autouse=True)
def short_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(duka_connect._duka, "_DISCOVERY_WAIT", 0.2)


async def test_a_unit_answers_discovery_with_its_address_port_id_and_unit_type(unit: SimulatedDuka) -> None:
    assert await discover(target="127.0.0.1", port=unit.port) == [
        DiscoveredDevice("127.0.0.1", unit.port, unit.device_id, 3)
    ]


async def test_nothing_answering_finds_nothing(unit: SimulatedDuka) -> None:
    unit.answering = False
    assert await discover(target="127.0.0.1", port=unit.port) == []

