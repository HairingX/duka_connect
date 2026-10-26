"""Reading a real Duka One: only reads, and skips itself unless a unit is configured.

Set DUKA_HOST, DUKA_DEVICE_ID and, if it is not the default, DUKA_PASSWORD, then run
`pytest -m live -s` to see what the unit answers for every point.
"""
import os

import pytest

from duka_connect import DEFAULT_PASSWORD, Client, Quality

pytestmark = pytest.mark.live

HOST = os.environ.get("DUKA_HOST")
DEVICE_ID = os.environ.get("DUKA_DEVICE_ID")


@pytest.mark.skipif(not HOST or not DEVICE_ID, reason="DUKA_HOST and DUKA_DEVICE_ID are not set")
async def test_every_point_of_a_real_unit_is_read() -> None:
    assert HOST and DEVICE_ID
    client = Client(HOST, DEVICE_ID, os.environ.get("DUKA_PASSWORD", DEFAULT_PASSWORD))
    await client.connect()
    try:
        print(f"\nUnit type: {client.unit_type}")
        for name, point in client.points.items():
            if not point.readable:
                continue
            value = client.value(point.key)
            assert value is not None, name
            raw = bytes(value.raw).hex() or "-"
            print(f"{name:26} {value.quality.name:8} {value.value!s:22} raw {raw}")
            assert value.quality in (Quality.GOOD, Quality.MISSING, Quality.NO_DATA), name
    finally:
        await client.disconnect()
