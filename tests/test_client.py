"""The client against a simulated Duka One."""
import asyncio
import logging
from datetime import date, time
from typing import Any

import pytest

from conftest import make_client
from duka_connect import (
    DUKA_ONE,
    DUKA_ONE_TIMING,
    AlarmLevel,
    CannotConnectError,
    Client,
    DataValue,
    InvalidValueError,
    Key,
    NotConnectedError,
    PointKey,
    PollRate,
    Quality,
    ReadOnlyError,
    Speed,
    Status,
    Timing,
    UnsupportedDeviceError,
    VentilationMode,
    Write,
    WriteKind,
)
from duka_connect.testing import FakeClock
from duka_connect._protocol import Function
from duka_connect.testing import FILTER_DAYS, SimulatedDuka


def values_of(client: Client, key: Key[Any]) -> object:
    value = client.value(key)
    assert value is not None
    return value.value


def watch(client: Client, *keys: Key[Any]) -> None:
    for key in keys:
        client.subscribe(key, lambda _key, _old, _new: None)


def read(unit: SimulatedDuka) -> list[int]:
    return [number for function, numbers in unit.requests if function is Function.READ for number in numbers]


def triggers(*rates: PollRate) -> list[int]:
    """The parameters of the points at these poll rates whose change sets off a refresh: they are
    polled with no subscriber, as only a read sees their change."""
    return [point.parameter for point in DUKA_ONE if point.on_change is not None and point.poll_rate in rates]


# ============================================================================== connecting


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
    assert client.status(Status.CONNECTED).value is True


async def test_connecting_reads_the_sensors_clock_and_settings(client: Client) -> None:
    assert values_of(client, PointKey.FAN2_RPM) == 1240
    assert values_of(client, PointKey.CLOCK_TIME) == time(12, 30, 15)
    assert values_of(client, PointKey.CLOCK_DATE) == date(2026, 10, 26)
    assert values_of(client, PointKey.IP_ADDRESS) == "192.0.2.10"
    assert values_of(client, PointKey.REDUCED_DURATION) == 8 * 60
    assert values_of(client, PointKey.BOOST_DURATION) == 4 * 60
    assert values_of(client, PointKey.FILTER_INTERVAL) == 90
    assert values_of(client, PointKey.SUPPLY_SPEED_3) == 255
    assert values_of(client, PointKey.CLOUD_ENABLED) is True
    assert values_of(client, PointKey.HUMIDITY_OVER_THRESHOLD) is False


async def test_a_value_carries_the_time_it_was_read_and_the_bytes_answered(client: Client, clock: FakeClock) -> None:
    value = client.value(PointKey.HUMIDITY)
    assert value is not None and value.timestamp == clock.now() and value.raw == (45,)


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
    assert value is not None and value.quality is Quality.NO_DATA and value.raw == (7,)


async def test_polling_before_connecting_raises(unit: SimulatedDuka, clock: FakeClock) -> None:
    with pytest.raises(NotConnectedError):
        await make_client(unit, clock).poll()


async def test_a_key_of_the_wrong_type_raises(client: Client) -> None:
    with pytest.raises(TypeError):
        client.value(Key("humidity", str))


async def test_a_key_a_duka_one_does_not_have_raises(client: Client) -> None:
    with pytest.raises(KeyError):
        client.value(Key("nothing", int))


async def test_a_command_has_no_value_to_subscribe_to(client: Client) -> None:
    with pytest.raises(TypeError):
        client.subscribe(PointKey.RESET_ALARMS, lambda _key, _old, _new: None)


# ================================================================================= polling


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
    watch(client, PointKey.VENTILATION_MODE, PointKey.WEEKLY_SCHEDULE)
    unit.requests.clear()
    await client.poll()
    assert unit.requests == []
    clock.advance(10)
    await client.poll()
    assert read(unit) == sorted([*triggers(PollRate.FAST), 0xB7])
    unit.requests.clear()
    await client.poll()
    assert unit.requests == []


async def test_a_static_point_is_not_polled(client: Client, unit: SimulatedDuka, clock: FakeClock) -> None:
    watch(client, PointKey.FIRMWARE_VERSION)
    firmware = next(point.parameter for point in DUKA_ONE if point.key == PointKey.FIRMWARE_VERSION)
    unit.requests.clear()
    for _ in range(3):
        clock.advance(10_000)
        await client.poll()
    assert read(unit) and firmware not in read(unit)


async def test_a_poll_interval_can_be_set_for_a_key(client: Client, unit: SimulatedDuka, clock: FakeClock) -> None:
    watch(client, PointKey.RTC_BATTERY_VOLTAGE)
    assert client.set_poll_interval(PointKey.RTC_BATTERY_VOLTAGE, 60) == 60
    unit.requests.clear()
    clock.advance(60)
    await client.poll()
    assert read(unit) == sorted([*triggers(PollRate.FAST, PollRate.MEDIUM, PollRate.SLOW), 0x24])


async def test_a_point_without_a_subscriber_is_read_only_when_asked(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    unit.requests.clear()
    clock.advance(10_000)
    await client.poll()
    assert 0x24 not in read(unit)
    unit.requests.clear()
    client.set_polling(PointKey.RTC_BATTERY_VOLTAGE)
    await client.poll()
    assert read(unit) == [0x24]


async def test_a_refresh_reads_a_poll_rate_or_keys_now(client: Client, unit: SimulatedDuka) -> None:
    unit.requests.clear()
    await client.refresh([PointKey.HUMIDITY])
    assert read(unit) == [0x25]
    unit.requests.clear()
    await client.refresh(PollRate.STATIC)
    assert sorted(set(read(unit))) == [0x86, 0xB9]


async def test_a_unit_that_stays_silent_makes_values_stale_and_then_counts_as_not_answering(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    connected: list[bool | None] = []
    client.subscribe_status(Status.CONNECTED, lambda _status, _old, new: connected.append(new.value))
    watch(client, PointKey.HUMIDITY)
    unit.answering = False
    clock.advance(30)
    await client.poll()
    value = client.value(PointKey.HUMIDITY)
    assert value is not None and value.quality is Quality.STALE and value.value == 45
    assert connected == [True]
    for _ in range(5):
        clock.advance(10)
        await client.poll()
    assert connected == [True, False]
    unit.answering = True
    clock.advance(30)
    await client.poll()
    assert connected == [True, False, True]
    value = client.value(PointKey.HUMIDITY)
    assert value is not None and value.quality is Quality.GOOD


async def test_a_single_lost_answer_does_not_count_as_not_answering(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    connected: list[bool | None] = []
    client.subscribe_status(Status.CONNECTED, lambda _status, _old, new: connected.append(new.value))
    watch(client, PointKey.HUMIDITY)
    unit.answering = False
    clock.advance(30)
    await client.poll()
    unit.answering = True
    clock.advance(30)
    await client.poll()
    assert connected == [True]
    value = client.value(PointKey.HUMIDITY)
    assert value is not None and value.quality is Quality.GOOD


async def test_a_failed_read_waits_for_its_next_regular_read_while_the_unit_is_silent(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.RTC_BATTERY_VOLTAGE)
    unit.answering = False
    clock.advance(900)
    await client.poll()
    unit.requests.clear()
    clock.advance(1)
    await client.poll()
    assert read(unit) == []


async def test_what_failed_while_the_unit_was_silent_is_read_as_soon_as_it_answers_again(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.HUMIDITY, PointKey.RTC_BATTERY_VOLTAGE)
    unit.answering = False
    clock.advance(900)
    await client.poll()
    unit.answering = True
    clock.advance(client.seconds_until_next_poll() or 0.0)
    await client.poll()
    unit.requests.clear()
    assert client.seconds_until_next_poll() == 0.0
    await client.poll()
    assert 0x24 in read(unit)


async def test_after_two_unanswered_requests_the_unit_is_not_asked_for_ten_seconds(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    unit.answering = False
    await client.refresh([PointKey.HUMIDITY])
    await client.refresh([PointKey.HUMIDITY])
    sent = len(unit.requests)
    clock.advance(9)
    await client.refresh([PointKey.HUMIDITY])
    assert len(unit.requests) == sent, "the unit was asked while the breaker was open"
    unit.answering = True
    clock.advance(1)
    await client.refresh([PointKey.HUMIDITY])
    value = client.value(PointKey.HUMIDITY)
    assert value is not None and value.quality is Quality.GOOD


async def test_after_an_outage_every_polled_point_is_read_once_the_unit_answers(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.HUMIDITY, PointKey.RTC_BATTERY_VOLTAGE)
    unit.answering = False
    for _ in range(4):
        clock.advance(30)
        await client.poll()
    assert client.status(Status.CONNECTED).value is False
    unit.answering = True
    clock.advance(30)
    await client.poll()
    unit.requests.clear()
    await client.poll()
    assert client.status(Status.CONNECTED).value is True
    assert 0x24 in read(unit), "the battery, not read during the outage, was not read after it"


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


# ================================================================================= writing


async def test_a_written_setting_holds_what_the_unit_answered(client: Client, unit: SimulatedDuka) -> None:
    assert await client.write(PointKey.VENTILATION_MODE, VentilationMode.SUPPLY)
    assert unit.values[0xB7] == b"\x02"
    assert values_of(client, PointKey.VENTILATION_MODE) is VentilationMode.SUPPLY


async def test_manual_speed_is_written_with_the_manual_preset_in_one_request(
    client: Client, unit: SimulatedDuka
) -> None:
    unit.requests.clear()
    assert await client.write_sequence([Write(PointKey.SPEED, Speed.MANUAL), Write(PointKey.MANUAL_SPEED, 77)])
    assert [numbers for _, numbers in unit.requests] == [[0x02, 0x44]]
    assert values_of(client, PointKey.SPEED) is Speed.MANUAL
    assert values_of(client, PointKey.MANUAL_SPEED) == 77


async def test_a_setting_the_unit_does_not_take_is_not_taken(client: Client, unit: SimulatedDuka) -> None:
    unit.unsupported.add(0xB7)
    assert not await client.write(PointKey.VENTILATION_MODE, VentilationMode.SUPPLY)


async def test_a_write_the_unit_does_not_answer_is_not_taken(client: Client, unit: SimulatedDuka) -> None:
    unit.answering = False
    assert not await client.write(PointKey.POWER, False)
    assert client.status(Status.CONNECTED).value is True


async def test_the_client_says_how_long_the_unit_has_been_silent(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    unit.answering = False
    await client.refresh([PointKey.HUMIDITY])
    clock.advance(5)
    assert client.silent and client.silent_for == 5.0
    unit.answering = True
    await client.refresh([PointKey.HUMIDITY])
    assert not client.silent and client.silent_for == 0.0


async def test_a_value_outside_the_limits_is_refused_before_it_is_sent(
    client: Client, unit: SimulatedDuka
) -> None:
    unit.requests.clear()
    with pytest.raises(InvalidValueError):
        await client.write(PointKey.HUMIDITY_THRESHOLD, 95)
    assert unit.requests == []


async def test_a_value_of_another_type_is_refused(client: Client) -> None:
    with pytest.raises(InvalidValueError):
        await client.write(PointKey.HUMIDITY_THRESHOLD, "50")  # pyright: ignore[reportArgumentType]


async def test_a_point_that_is_only_read_cannot_be_written(client: Client) -> None:
    with pytest.raises(ValueError):
        await client.write(PointKey.HUMIDITY, 50)


async def test_a_read_only_client_writes_nothing(unit: SimulatedDuka, clock: FakeClock) -> None:
    client = Client("127.0.0.1", unit.device_id, unit.password, port=unit.port, timeout=0.2, attempts=1,
                    clock=clock, read_only=True)
    await client.connect()
    with pytest.raises(ReadOnlyError):
        await client.write(PointKey.POWER, False)
    await client.disconnect()


async def test_a_command_is_sent_with_true_only(client: Client) -> None:
    with pytest.raises(InvalidValueError):
        await client.write(PointKey.RESET_ALARMS, False)


async def test_a_write_is_pending_while_it_is_sent(client: Client) -> None:
    pending: list[bool | None] = []
    client.subscribe_status(Status.WRITE_PENDING, lambda _status, _old, new: pending.append(new.value))
    await client.write(PointKey.POWER, False)
    assert pending == [False, True, False]


async def test_the_clock_is_set_in_one_request(client: Client, unit: SimulatedDuka) -> None:
    unit.requests.clear()
    await client.write_sequence(
        [Write(PointKey.CLOCK_TIME, time(7, 5, 9)), Write(PointKey.CLOCK_DATE, date(2027, 1, 3))]
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
    await client.write(PointKey.REDUCED_DURATION, 9 * 60 + 45)
    assert unit.values[0x0302] == bytes([45, 9])
    assert values_of(client, PointKey.REDUCED_DURATION) == 9 * 60 + 45


async def test_a_filter_interval_outside_70_to_365_days_is_refused(client: Client) -> None:
    with pytest.raises(InvalidValueError):
        await client.write(PointKey.FILTER_INTERVAL, 30)


# ===================================================================== what is read again


async def test_a_command_is_read_back_once_the_unit_has_had_time_to_carry_it_out(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.ALARM, PointKey.FILTER_REPLACE)
    unit.values[0x83] = b"\x02"
    await client.refresh([PointKey.ALARM])
    assert await client.write(PointKey.RESET_ALARMS, True)
    unit.requests.clear()
    await client.poll()
    assert unit.requests == []
    clock.advance(1)
    await client.poll()
    assert values_of(client, PointKey.ALARM) is AlarmLevel.NONE


async def test_resetting_the_filter_timer_reads_back_the_filter(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.FILTER_REPLACE, PointKey.FILTER_TIMER, PointKey.ALARM)
    unit.values[0x88] = b"\x01"
    unit.values[0x64] = bytes([0, 0, 0])
    await client.refresh([PointKey.FILTER_REPLACE, PointKey.FILTER_TIMER])
    assert values_of(client, PointKey.FILTER_REPLACE) is True
    await client.write(PointKey.RESET_FILTER_TIMER, True)
    clock.advance(1)
    await client.poll()
    assert values_of(client, PointKey.FILTER_REPLACE) is False
    assert values_of(client, PointKey.FILTER_TIMER) == FILTER_DAYS * 24 * 60


async def test_restoring_the_fan_speeds_reads_them_back(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.SUPPLY_SPEED_1)
    await client.write(PointKey.SUPPLY_SPEED_1, 120)
    assert values_of(client, PointKey.SUPPLY_SPEED_1) == 120
    await client.write(PointKey.RESTORE_FAN_SPEEDS, True)
    clock.advance(1)
    await client.poll()
    assert values_of(client, PointKey.SUPPLY_SPEED_1) == 80


async def test_a_new_speed_reads_the_fans_once_they_have_had_time_to_change(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.FAN_RPM, PointKey.FAN2_RPM)
    await client.write(PointKey.SPEED, Speed.HIGH)
    unit.values[0x4A] = (2200).to_bytes(2, "little")
    unit.requests.clear()
    await client.poll()
    assert unit.requests == []
    clock.advance(3)
    await client.poll()
    assert values_of(client, PointKey.FAN_RPM) == 2200


async def test_the_fans_are_read_until_their_speed_settles(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.FAN_RPM, PointKey.FAN2_RPM)
    await client.write(PointKey.SPEED, Speed.HIGH)
    for rpm in (1800, 2200, 2200):
        unit.values[0x4A] = rpm.to_bytes(2, "little")
        clock.advance(3)
        await client.poll()
    clock.advance(1)
    await client.poll()
    unit.requests.clear()
    for _ in range(9):
        clock.advance(1)
        await client.poll()
    assert values_of(client, PointKey.FAN_RPM) == 2200
    assert 0x4A not in read(unit)


async def _warning(unit: SimulatedDuka, clock: FakeClock) -> Client:
    """A client connected to a unit whose alarm shows a warning, watching the alarm and battery."""
    unit.values[0x83] = bytes([AlarmLevel.WARNING])
    client = make_client(unit, clock)
    await client.connect()
    watch(client, PointKey.ALARM, PointKey.RTC_BATTERY_VOLTAGE, PointKey.FILTER_REPLACE)
    return client


async def test_a_cleared_alarm_reads_the_battery_and_filter_soon_after(
    unit: SimulatedDuka, clock: FakeClock
) -> None:
    client = await _warning(unit, clock)
    unit.values[0x83] = bytes([AlarmLevel.NONE])
    unit.values[0x24] = (3100).to_bytes(2, "little")
    clock.advance(60)
    await client.poll()
    unit.requests.clear()
    clock.advance(10)
    await client.poll()
    assert values_of(client, PointKey.RTC_BATTERY_VOLTAGE) == 3100
    assert {0x24, 0x88} <= set(read(unit))
    await client.disconnect()


async def test_a_battery_read_too_soon_is_read_again_until_it_settles(
    unit: SimulatedDuka, clock: FakeClock
) -> None:
    client = await _warning(unit, clock)
    unit.values[0x83] = bytes([AlarmLevel.NONE])
    clock.advance(60)
    await client.poll()
    clock.advance(10)
    await client.poll()
    unit.values[0x24] = (3100).to_bytes(2, "little")
    clock.advance(10)
    await client.poll()
    assert values_of(client, PointKey.RTC_BATTERY_VOLTAGE) == 3100
    await client.disconnect()


async def test_a_settled_battery_is_read_on_its_own_rate_again(unit: SimulatedDuka, clock: FakeClock) -> None:
    client = await _warning(unit, clock)
    unit.values[0x83] = bytes([AlarmLevel.NONE])
    clock.advance(60)
    await client.poll()
    for _ in range(2):
        clock.advance(10)
        await client.poll()
    unit.requests.clear()
    clock.advance(10)
    await client.poll()
    assert 0x24 not in read(unit)
    await client.disconnect()


async def test_an_unchanged_value_reads_nothing_more(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.ALARM, PointKey.RTC_BATTERY_VOLTAGE)
    unit.requests.clear()
    clock.advance(60)
    await client.poll()
    clock.advance(10)
    await client.poll()
    assert read(unit) == [*sorted(triggers(PollRate.FAST, PollRate.MEDIUM, PollRate.SLOW)), *triggers(PollRate.FAST)]


async def test_only_what_is_watched_is_read_again(client: Client, unit: SimulatedDuka, clock: FakeClock) -> None:
    """Of the alarm's targets, only filter_replace (0x88) is read again: it is itself a trigger."""
    watch(client, PointKey.ALARM)
    unit.values[0x83] = bytes([AlarmLevel.WARNING])
    clock.advance(60)
    await client.poll()
    unit.requests.clear()
    clock.advance(10)
    await client.poll()
    assert read(unit) == sorted([*triggers(PollRate.FAST), 0x88])


def test_every_point_read_again_is_a_point_with_a_value() -> None:
    points: dict[str, Any] = {point.key: point for point in DUKA_ONE}
    for point in DUKA_ONE:
        for refresh in (point.on_write, point.on_change):
            if refresh is None:
                continue
            assert isinstance(refresh.targets, tuple)
            for key in refresh.targets:
                assert key != point.key, point.key
                assert points[key].readable, (point.key, key)


def test_every_command_waits_before_what_it_changed_is_read() -> None:
    for point in DUKA_ONE:
        if point.write_kind is WriteKind.COMMAND:
            assert point.on_write is not None and DUKA_ONE_TIMING.read_back_delay(point) > 0, point.key


async def test_a_client_can_be_given_its_own_timing(unit: SimulatedDuka, clock: FakeClock) -> None:
    client = Client("127.0.0.1", unit.device_id, unit.password, port=unit.port, timeout=0.2, attempts=1,
                    clock=clock, timing=Timing(poll_intervals={PollRate.FAST: 5.0}))
    await client.connect()
    watch(client, PointKey.POWER)
    unit.requests.clear()
    clock.advance(5)
    await client.poll()
    assert read(unit) == triggers(PollRate.FAST)
    await client.disconnect()


async def test_after_an_outage_of_15_s_a_value_read_every_10_s_is_back_20_s_after_it_began(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.HUMIDITY)
    client.set_poll_interval(PointKey.HUMIDITY, 10.0)
    clock.advance(10)
    await client.poll()
    unit.answering = False
    good_again: int | None = None
    for second in range(1, 41):
        clock.advance(1)
        if second == 15:
            unit.answering = True
        await client.poll()
        value = client.value(PointKey.HUMIDITY)
        if second >= 15 and good_again is None and value is not None and value.quality is Quality.GOOD:
            good_again = second
    assert good_again == 20


async def test_a_cancelled_probe_lets_the_next_one_through(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    unit.answering = False
    await client.refresh([PointKey.HUMIDITY])
    await client.refresh([PointKey.HUMIDITY])
    clock.advance(10)
    probe = asyncio.ensure_future(client.refresh([PointKey.HUMIDITY]))
    await asyncio.sleep(0.05)
    probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await probe
    unit.answering = True
    await client.refresh([PointKey.HUMIDITY])
    value = client.value(PointKey.HUMIDITY)
    assert value is not None and value.quality is Quality.GOOD


async def test_an_outage_and_its_end_are_logged_once_each(
    client: Client, unit: SimulatedDuka, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    watch(client, PointKey.HUMIDITY)
    unit.answering = False
    with caplog.at_level(logging.INFO):
        for _ in range(4):
            clock.advance(30)
            await client.poll()
        unit.answering = True
        clock.advance(30)
        await client.poll()
    said = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO and "answer" in r.getMessage()]
    assert said == ["The Duka One stopped answering 30 s ago", "The Duka One answers again, after 120 s"]


async def test_diagnostics_count_requests_and_the_breaker_without_naming_the_unit(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    unit.answering = False
    await client.refresh([PointKey.HUMIDITY])
    await client.refresh([PointKey.HUMIDITY])
    await client.refresh([PointKey.HUMIDITY])
    diagnostics = client.diagnostics()
    assert diagnostics["unanswered"] == 2 and diagnostics["refused_while_backing_off"] == 1
    assert diagnostics["backing_off_for"] == 10.0 and diagnostics["backoffs"] == 1
    text = repr(diagnostics)
    assert unit.device_id not in text and unit.password not in text and "127.0.0.1" not in text


async def test_polls_made_together_read_once(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    watch(client, PointKey.HUMIDITY)
    clock.advance(30)
    unit.requests.clear()
    await asyncio.gather(client.poll(), client.poll(), client.poll())
    assert read(unit).count(0x25) == 1


async def test_a_trigger_is_polled_with_no_subscriber(client: Client, unit: SimulatedDuka, clock: FakeClock) -> None:
    unit.requests.clear()
    clock.advance(10)
    await client.poll()
    assert triggers(PollRate.FAST) and read(unit) == triggers(PollRate.FAST)


async def test_overlapping_writes_keep_write_pending_until_the_last_has_finished(client: Client) -> None:
    seen: list[bool | None] = []
    client.subscribe_status(Status.WRITE_PENDING, lambda _status, _old, new: seen.append(new.value))
    in_flight = 0
    pending_while_in_flight: list[bool | None] = []

    async def write(value: int) -> None:
        nonlocal in_flight
        in_flight += 1
        await client.write(PointKey.HUMIDITY_THRESHOLD, value)
        in_flight -= 1
        if in_flight:
            pending_while_in_flight.append(client.status(Status.WRITE_PENDING).value)

    await asyncio.gather(write(50), write(60))
    assert pending_while_in_flight == [True] and seen == [False, True, False]
