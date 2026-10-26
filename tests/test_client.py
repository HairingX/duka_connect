"""The client against a simulated Duka One."""
from datetime import date, time
from time import monotonic
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
from duka_connect._duka_one import DUKA_ONE
from duka_connect._protocol import Function
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
    assert sorted(unit.requests[0][1]) == [0x02, 0x44]
    assert all(function is Function.READ for function, _ in unit.requests[1:])
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


async def test_connecting_reads_the_sensors_clock_and_settings(client: Client) -> None:
    assert values_of(client, PointKey.FAN2_RPM) == 1240
    assert values_of(client, PointKey.CLOCK_TIME) == time(12, 30, 15)
    assert values_of(client, PointKey.CLOCK_DATE) == date(2026, 10, 26)
    assert values_of(client, PointKey.IP_ADDRESS) == "192.0.2.10"
    assert values_of(client, PointKey.NIGHT_TIMER) == 8 * 60
    assert values_of(client, PointKey.PARTY_TIMER) == 4 * 60
    assert values_of(client, PointKey.FILTER_INTERVAL) == 90
    assert values_of(client, PointKey.SUPPLY_SPEED_3) == 255
    assert values_of(client, PointKey.CLOUD_ENABLED) is True
    assert values_of(client, PointKey.HUMIDITY_OVER_THRESHOLD) is False


async def test_the_clock_is_set_in_one_request(client: Client, unit: SimulatedDuka) -> None:
    unit.requests.clear()
    await client.write_many(
        [(PointKey.CLOCK_TIME, time(7, 5, 9)), (PointKey.CLOCK_DATE, date(2027, 1, 3))]
    )
    assert len(unit.requests) == 1
    assert unit.values[0x6F] == bytes([9, 5, 7])
    assert unit.values[0x70] == bytes([3, 7, 1, 27])
    assert values_of(client, PointKey.CLOCK_DATE) == date(2027, 1, 3)


async def test_a_year_the_unit_cannot_hold_is_refused(client: Client) -> None:
    with pytest.raises(InvalidValueError):
        await client.write(PointKey.CLOCK_DATE, date(2100, 1, 1))


async def test_a_timer_on_page_3_is_written_as_minutes_and_hours(
    client: Client, unit: SimulatedDuka
) -> None:
    await client.write(PointKey.NIGHT_TIMER, 9 * 60 + 45)
    assert unit.values[0x0302] == bytes([45, 9])
    assert values_of(client, PointKey.NIGHT_TIMER) == 9 * 60 + 45


async def test_a_filter_interval_outside_70_to_365_days_is_refused(client: Client) -> None:
    with pytest.raises(InvalidValueError):
        await client.write(PointKey.FILTER_INTERVAL, 30)


async def test_restoring_the_fan_speeds_reads_them_back(client: Client, unit: SimulatedDuka) -> None:
    await client.write(PointKey.SUPPLY_SPEED_1, 120)
    assert values_of(client, PointKey.SUPPLY_SPEED_1) == 120
    await client.write(PointKey.RESTORE_FAN_SPEEDS, None)
    assert values_of(client, PointKey.SUPPLY_SPEED_1) == 80


async def test_a_cleared_alarm_reads_the_battery_and_filter_at_once(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    client.subscribe(PointKey.ALARM, lambda key, old, new: None)
    unit.values[0x83] = bytes([AlarmLevel.WARNING])
    clock.advance(60)
    await client.poll()
    unit.values[0x83] = bytes([AlarmLevel.NONE])
    unit.values[0x24] = (3100).to_bytes(2, "little")
    unit.requests.clear()
    clock.advance(60)
    await client.poll()
    assert values_of(client, PointKey.RTC_BATTERY_VOLTAGE) == 3100
    assert [parameters for _, parameters in unit.requests][0] == [0x83]


async def test_an_unchanged_value_reads_nothing_more(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    client.subscribe(PointKey.ALARM, lambda key, old, new: None)
    unit.requests.clear()
    clock.advance(60)
    await client.poll()
    assert [parameters for _, parameters in unit.requests] == [[0x83]]


async def test_a_change_read_in_turn_reads_on_without_reading_a_point_twice(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    client.subscribe(PointKey.ALARM, lambda key, old, new: None)
    unit.values[0x83] = bytes([AlarmLevel.WARNING])
    unit.values[0x88] = b"\x01"
    unit.requests.clear()
    clock.advance(60)
    await client.poll()
    read = [number for _, parameters in unit.requests for number in parameters]
    assert values_of(client, PointKey.FILTER_REPLACE) is True
    assert len(read) == len(set(read))


async def test_turning_the_unit_off_reads_the_fans_at_once(client: Client, unit: SimulatedDuka) -> None:
    unit.requests.clear()
    await client.write(PointKey.POWER, False)
    read = {number for _, parameters in unit.requests[1:] for number in parameters}
    assert {0x4A, 0x4B, 0x06} <= read


def test_a_point_reads_in_turn_only_other_points_with_a_value() -> None:
    names = {point.key.name: point for point in DUKA_ONE}
    for point in DUKA_ONE:
        for key in point.then_read:
            assert key.name != point.key.name, point.key
            assert not names[key.name].command, (point.key, key)


async def test_a_command_is_read_back_only_after_the_unit_has_had_time_to_carry_it_out(
    unit: SimulatedDuka, clock: FakeClock
) -> None:
    client = Client(
        "127.0.0.1", unit.device_id, unit.password,
        port=unit.port, timeout=0.2, attempts=1, command_delay=0.3, clock=clock,
    )
    await client.connect()
    started = monotonic()
    await client.write(PointKey.RESET_ALARMS, None)
    assert monotonic() - started >= 0.3
    await client.disconnect()


async def test_a_setting_is_answered_so_it_is_not_waited_for(unit: SimulatedDuka, clock: FakeClock) -> None:
    client = Client(
        "127.0.0.1", unit.device_id, unit.password,
        port=unit.port, timeout=0.2, attempts=1, command_delay=5.0, clock=clock,
    )
    await client.connect()
    started = monotonic()
    await client.write(PointKey.POWER, False)
    assert monotonic() - started < 1.0
    await client.disconnect()
