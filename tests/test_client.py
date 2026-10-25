"""The client against a simulated Duka One."""
from datetime import date
from typing import Any

import pytest

from conftest import FakeClock, make_client
from duka_connect import (
    AlarmLevel,
    CannotConnectError,
    Client,
    DataValue,
    InvalidValueError,
    Key,
    NotConnectedError,
    PointKey,
    Quality,
    ReadOnlyError,
    Speed,
    Status,
    UnsupportedDeviceError,
    VentilationMode,
    WriteError,
)
from duka_connect.testing import FILTER_DAYS, SimulatedDuka


def values_of(client: Client, key: Key[Any]) -> object:
    value = client.value(key)
    assert value is not None
    return value.value


async def test_connecting_reads_every_point(client: Client) -> None:
    assert values_of(client, PointKey.POWER) is True
    assert values_of(client, PointKey.SPEED) is Speed.MEDIUM
    assert values_of(client, PointKey.VENTILATION_MODE) is VentilationMode.HEAT_RECOVERY
    assert values_of(client, PointKey.HUMIDITY) == 45
    assert values_of(client, PointKey.FAN_RPM) == 1250
    assert values_of(client, PointKey.RTC_BATTERY_VOLTAGE) == 3010
    assert values_of(client, PointKey.FILTER_TIMER) == 75 * 24 * 60 + 12 * 60 + 30
    assert values_of(client, PointKey.OPERATING_TIME) == 400 * 24 * 60 + 4 * 60 + 10
    assert values_of(client, PointKey.FIRMWARE_VERSION) == "1.5"
    assert values_of(client, PointKey.FIRMWARE_DATE) == date(2023, 5, 17)
    assert values_of(client, PointKey.ALARM) is AlarmLevel.NONE
    assert client.unit_type == 3
    assert client.status is Status.CONNECTED


async def test_a_unit_that_does_not_answer_cannot_be_connected(unit: SimulatedDuka, clock: FakeClock) -> None:
    unit.answering = False
    with pytest.raises(CannotConnectError):
        await make_client(unit, clock).connect()


async def test_a_wrong_password_is_not_answered(unit: SimulatedDuka, clock: FakeClock) -> None:
    with pytest.raises(CannotConnectError):
        await make_client(unit, clock, password="wrong").connect()


async def test_a_unit_without_a_unit_type_is_not_supported(unit: SimulatedDuka, clock: FakeClock) -> None:
    unit.unsupported.add(0xB9)
    with pytest.raises(UnsupportedDeviceError):
        await make_client(unit, clock).connect()


async def test_a_point_the_unit_does_not_have_is_missing(unit: SimulatedDuka, clock: FakeClock) -> None:
    unit.unsupported.add(0x24)
    client = make_client(unit, clock)
    await client.connect()
    value = client.value(PointKey.RTC_BATTERY_VOLTAGE)
    assert value is not None and value.quality is Quality.MISSING
    assert values_of(client, PointKey.HUMIDITY) == 45


async def test_a_number_no_state_names_is_no_data(unit: SimulatedDuka, clock: FakeClock) -> None:
    unit.values[0x83] = b"\x07"
    client = make_client(unit, clock)
    await client.connect()
    value = client.value(PointKey.ALARM)
    assert value is not None and value.quality is Quality.NO_DATA and value.raw == b"\x07"


async def test_a_subscriber_is_told_the_current_value_and_every_change(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    seen: list[tuple[int | None, int | None]] = []

    def on_change(key: Key[int], old: DataValue[int] | None, new: DataValue[int]) -> None:
        seen.append((None if old is None else old.value, new.value))

    client.subscribe(PointKey.HUMIDITY, on_change)
    unit.values[0x25] = bytes([60])
    clock.advance(30)
    await client.poll()
    assert seen == [(None, 45), (45, 60)]


async def test_a_poll_reads_only_what_is_due(client: Client, unit: SimulatedDuka, clock: FakeClock) -> None:
    client.subscribe(PointKey.POWER, lambda key, old, new: None)
    client.subscribe(PointKey.HUMIDITY, lambda key, old, new: None)
    unit.requests.clear()
    await client.poll()
    assert unit.requests == [] or unit.requests[0][1] in ([0x01, 0x25], [0x25, 0x01])
    unit.requests.clear()
    clock.advance(10)
    await client.poll()
    assert unit.requests[0][1] == [0x01]
    unit.requests.clear()
    await client.poll()
    assert unit.requests == []


async def test_a_static_point_is_not_polled(client: Client, unit: SimulatedDuka, clock: FakeClock) -> None:
    client.subscribe(PointKey.FIRMWARE_VERSION, lambda key, old, new: None)
    unit.requests.clear()
    clock.advance(10_000)
    await client.poll()
    assert unit.requests == []
    assert client.seconds_until_next_poll() is None


async def test_a_unit_that_stops_answering_makes_values_stale_and_status_disconnected(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    statuses: list[Status] = []
    client.subscribe_status(statuses.append)
    client.subscribe(PointKey.HUMIDITY, lambda key, old, new: None)
    unit.answering = False
    clock.advance(30)
    await client.poll()
    value = client.value(PointKey.HUMIDITY)
    assert value is not None and value.quality is Quality.STALE and value.value == 45
    assert statuses == [Status.CONNECTED, Status.DISCONNECTED]
    unit.answering = True
    clock.advance(30)
    await client.poll()
    assert statuses[-1] is Status.CONNECTED
    value = client.value(PointKey.HUMIDITY)
    assert value is not None and value.quality is Quality.GOOD


async def test_a_written_setting_is_read_back(client: Client, unit: SimulatedDuka) -> None:
    await client.write(PointKey.VENTILATION_MODE, VentilationMode.SUPPLY)
    assert unit.values[0xB7] == b"\x02"
    assert values_of(client, PointKey.VENTILATION_MODE) is VentilationMode.SUPPLY


async def test_manual_speed_is_written_with_the_manual_preset_in_one_request(
    client: Client, unit: SimulatedDuka
) -> None:
    unit.requests.clear()
    await client.write_many([(PointKey.SPEED, Speed.MANUAL), (PointKey.MANUAL_SPEED, 77)])
    assert len(unit.requests) == 1
    assert values_of(client, PointKey.SPEED) is Speed.MANUAL
    assert values_of(client, PointKey.MANUAL_SPEED) == 77


async def test_a_setting_the_unit_does_not_take_raises(client: Client, unit: SimulatedDuka) -> None:
    unit.unsupported.add(0xB7)
    with pytest.raises(WriteError):
        await client.write(PointKey.VENTILATION_MODE, VentilationMode.SUPPLY)


async def test_a_value_outside_the_limits_is_refused_before_it_is_sent(
    client: Client, unit: SimulatedDuka
) -> None:
    unit.requests.clear()
    with pytest.raises(InvalidValueError):
        await client.write(PointKey.HUMIDITY_THRESHOLD, 95)
    assert unit.requests == []


async def test_a_read_only_point_cannot_be_written(client: Client) -> None:
    with pytest.raises(ReadOnlyError):
        await client.write(PointKey.HUMIDITY, 50)


async def test_resetting_the_filter_timer_reads_back_the_filter(client: Client, unit: SimulatedDuka) -> None:
    unit.values[0x88] = b"\x01"
    unit.values[0x64] = bytes([0, 0, 0])
    await client.refresh([PointKey.FILTER_REPLACE])
    assert values_of(client, PointKey.FILTER_REPLACE) is True
    await client.write(PointKey.RESET_FILTER_TIMER, None)
    assert values_of(client, PointKey.FILTER_REPLACE) is False
    assert values_of(client, PointKey.FILTER_TIMER) == FILTER_DAYS * 24 * 60


async def test_resetting_the_alarms_reads_back_the_alarm(client: Client, unit: SimulatedDuka) -> None:
    unit.values[0x83] = b"\x02"
    await client.refresh([PointKey.ALARM])
    assert values_of(client, PointKey.ALARM) is AlarmLevel.WARNING
    await client.write(PointKey.RESET_ALARMS, None)
    assert values_of(client, PointKey.ALARM) is AlarmLevel.NONE


async def test_a_key_of_the_wrong_type_raises(client: Client) -> None:
    with pytest.raises(TypeError):
        client.value(Key("humidity", str))


async def test_polling_before_connecting_raises(unit: SimulatedDuka, clock: FakeClock) -> None:
    with pytest.raises(NotConnectedError):
        await make_client(unit, clock).poll()


async def test_a_raising_callback_does_not_stop_the_others(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    seen: list[int | None] = []

    def raising(key: Key[int], old: DataValue[int] | None, new: DataValue[int]) -> None:
        raise RuntimeError("callback")

    client.subscribe(PointKey.HUMIDITY, raising)
    client.subscribe(PointKey.HUMIDITY, lambda key, old, new: seen.append(new.value))
    unit.values[0x25] = bytes([50])
    clock.advance(30)
    await client.poll()
    assert seen == [45, 50]
