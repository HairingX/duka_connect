"""Discovery against a simulated Duka One."""
from duka_connect import discover
from duka_connect.testing import SimulatedDuka


async def test_a_unit_answers_discovery_with_its_id_and_unit_type(unit: SimulatedDuka) -> None:
    found = await discover("127.0.0.1", port=unit.port, timeout=0.2)
    assert [(device.host, device.device_id, device.unit_type) for device in found] == [
        ("127.0.0.1", unit.device_id, 3)
    ]


async def test_nothing_answering_finds_nothing(unit: SimulatedDuka) -> None:
    unit.answering = False
    assert await discover("127.0.0.1", port=unit.port, timeout=0.2) == []
