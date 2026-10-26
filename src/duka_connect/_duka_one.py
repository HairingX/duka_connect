"""The Duka One's points."""
from datetime import date, time
from typing import Any

from ._event_connect import Key, Limits, PollRate, Refresh, Unit, WriteKind
from ._points import (
    Point,
    command_encoder,
    decode_bool,
    decode_clock_date,
    decode_clock_time,
    decode_firmware_date,
    decode_firmware_version,
    decode_int,
    decode_ipv4,
    decode_minutes_hours,
    decode_minutes_hours_days,
    decode_operating_minutes,
    decode_seconds_minutes_hours,
    encode_bool,
    encode_clock_date,
    encode_clock_time,
    encode_minutes_hours,
    encode_state,
    int_encoder,
    state_decoder,
)
from ._states import AlarmLevel, Speed, TimerMode, VentilationMode


class PointKey:
    """The keys of the Duka One's points."""

    POWER = Key("power", bool)
    SPEED = Key("speed", Speed)
    MANUAL_SPEED = Key("manual_speed", int)
    VENTILATION_MODE = Key("ventilation_mode", VentilationMode)
    BOOST = Key("boost", bool)
    TIMER_MODE = Key("timer_mode", TimerMode)
    TIMER_COUNTDOWN = Key("timer_countdown", int)
    HUMIDITY_SENSOR_ENABLED = Key("humidity_sensor_enabled", bool)
    HUMIDITY_THRESHOLD = Key("humidity_threshold", int)
    HUMIDITY = Key("humidity", int)
    FAN_RPM = Key("fan_rpm", int)
    BOOST_OFF_DELAY = Key("boost_off_delay", int)
    FILTER_TIMER = Key("filter_timer", int)
    FILTER_REPLACE = Key("filter_replace", bool)
    ALARM = Key("alarm", AlarmLevel)
    RTC_BATTERY_VOLTAGE = Key("rtc_battery_voltage", int)
    OPERATING_TIME = Key("operating_time", int)
    FIRMWARE_VERSION = Key("firmware_version", str)
    FIRMWARE_DATE = Key("firmware_date", date)
    UNIT_TYPE = Key("unit_type", int)
    RESET_FILTER_TIMER = Key("reset_filter_timer", bool)
    RESET_ALARMS = Key("reset_alarms", bool)
    RELAY_SENSOR_ENABLED = Key("relay_sensor_enabled", bool)
    RELAY_SENSOR_ACTIVE = Key("relay_sensor_active", bool)
    ANALOG_SENSOR_ENABLED = Key("analog_sensor_enabled", bool)
    ANALOG_SENSOR_LEVEL = Key("analog_sensor_level", int)
    ANALOG_SENSOR_THRESHOLD = Key("analog_sensor_threshold", int)
    ANALOG_SENSOR_OVER_THRESHOLD = Key("analog_sensor_over_threshold", bool)
    HUMIDITY_OVER_THRESHOLD = Key("humidity_over_threshold", bool)
    SUPPLY_SPEED_1 = Key("supply_speed_1", int)
    EXHAUST_SPEED_1 = Key("exhaust_speed_1", int)
    SUPPLY_SPEED_2 = Key("supply_speed_2", int)
    EXHAUST_SPEED_2 = Key("exhaust_speed_2", int)
    SUPPLY_SPEED_3 = Key("supply_speed_3", int)
    EXHAUST_SPEED_3 = Key("exhaust_speed_3", int)
    FAN2_RPM = Key("fan2_rpm", int)
    FILTER_INTERVAL = Key("filter_interval", int)
    CLOCK_TIME = Key("clock_time", time)
    CLOCK_DATE = Key("clock_date", date)
    WEEKLY_SCHEDULE = Key("weekly_schedule", bool)
    CLOUD_ENABLED = Key("cloud_enabled", bool)
    IP_ADDRESS = Key("ip_address", str)
    NIGHT_TIMER = Key("night_timer", int)
    PARTY_TIMER = Key("party_timer", int)
    RESTORE_FAN_SPEEDS = Key("restore_fan_speeds", bool)


_FANS = (PointKey.FAN_RPM, PointKey.FAN2_RPM)

_FANS_SETTLE = Refresh(_FANS, after=3.0, until_stable=30.0)
"""The fans' speeds, read until they settle: a fan takes some seconds to reach a new speed."""

_COMMAND_TAKEN = 1.0
"""Seconds before what a command changed is read: the unit does not answer a command, so nothing
says when it has carried it out."""


def _whole(minimum: int, maximum: int) -> Limits:
    return Limits(minimum, maximum, step=1)


DUKA_ONE: tuple[Point[Any], ...] = (
    Point(
        PointKey.POWER, 0x01, 1, decode_bool, encode_bool, poll_rate=PollRate.FAST,
        on_change=Refresh((*_FANS, PointKey.BOOST), after=3.0, until_stable=30.0),
    ),
    Point(
        PointKey.SPEED, 0x02, 1, state_decoder(Speed), encode_state, poll_rate=PollRate.FAST,
        on_change=_FANS_SETTLE,
    ),
    Point(
        PointKey.BOOST, 0x06, 1, decode_bool, poll_rate=PollRate.FAST,
        on_change=Refresh(
            (*_FANS, PointKey.HUMIDITY, PointKey.HUMIDITY_OVER_THRESHOLD), after=3.0, until_stable=30.0,
        ),
    ),
    Point(
        PointKey.TIMER_MODE, 0x07, 1, state_decoder(TimerMode), encode_state, poll_rate=PollRate.FAST,
        on_change=Refresh((PointKey.TIMER_COUNTDOWN, *_FANS), after=3.0, until_stable=30.0),
    ),
    Point(PointKey.TIMER_COUNTDOWN, 0x0B, 3, decode_seconds_minutes_hours, unit=Unit.SECONDS),
    Point(
        PointKey.HUMIDITY_SENSOR_ENABLED, 0x0F, 1, decode_bool, encode_bool, poll_rate=PollRate.SLOW,
        on_change=Refresh((PointKey.HUMIDITY_OVER_THRESHOLD, PointKey.BOOST), after=1.0),
    ),
    Point(
        PointKey.HUMIDITY_THRESHOLD, 0x19, 1, decode_int, int_encoder(1), poll_rate=PollRate.SLOW,
        unit=Unit.PERCENT, limits=_whole(40, 80),
        on_change=Refresh((PointKey.HUMIDITY_OVER_THRESHOLD, PointKey.BOOST), after=1.0),
    ),
    Point(
        PointKey.RTC_BATTERY_VOLTAGE, 0x24, 2, decode_int, poll_rate=PollRate.RARE, unit=Unit.MILLIVOLT,
    ),
    Point(
        PointKey.HUMIDITY, 0x25, 1, decode_int, unit=Unit.PERCENT,
        on_change=Refresh((PointKey.HUMIDITY_OVER_THRESHOLD, PointKey.BOOST)),
    ),
    Point(
        PointKey.MANUAL_SPEED, 0x44, 1, decode_int, int_encoder(1), poll_rate=PollRate.FAST,
        limits=_whole(0, 255), on_change=_FANS_SETTLE,
    ),
    Point(PointKey.FAN_RPM, 0x4A, 2, decode_int, poll_rate=PollRate.FAST, unit=Unit.RPM),
    Point(
        PointKey.FILTER_TIMER, 0x64, 3, decode_minutes_hours_days, poll_rate=PollRate.RARE,
        unit=Unit.MINUTES,
    ),
    Point(
        PointKey.RESET_FILTER_TIMER, 0x65, 1, None, command_encoder(b"\x00"),
        write_kind=WriteKind.COMMAND, read_back_after=_COMMAND_TAKEN,
        on_write=Refresh((PointKey.FILTER_TIMER, PointKey.FILTER_REPLACE, PointKey.ALARM)),
    ),
    Point(
        PointKey.BOOST_OFF_DELAY, 0x66, 1, decode_int, int_encoder(1), poll_rate=PollRate.SLOW,
        unit=Unit.MINUTES, limits=_whole(0, 60),
    ),
    Point(
        PointKey.OPERATING_TIME, 0x7E, 4, decode_operating_minutes, poll_rate=PollRate.RARE,
        unit=Unit.MINUTES,
    ),
    Point(
        PointKey.RESET_ALARMS, 0x80, 1, None, command_encoder(b"\x00"),
        write_kind=WriteKind.COMMAND, read_back_after=_COMMAND_TAKEN,
        on_write=Refresh((PointKey.ALARM, PointKey.FILTER_REPLACE)),
    ),
    Point(
        PointKey.ALARM, 0x83, 1, state_decoder(AlarmLevel), poll_rate=PollRate.SLOW,
        on_change=Refresh(
            (PointKey.RTC_BATTERY_VOLTAGE, PointKey.FILTER_REPLACE, PointKey.FILTER_TIMER),
            after=10.0, until_stable=120.0,
        ),
    ),
    Point(PointKey.FIRMWARE_VERSION, 0x86, 6, decode_firmware_version, poll_rate=PollRate.STATIC),
    Point(PointKey.FIRMWARE_DATE, 0x86, 6, decode_firmware_date, poll_rate=PollRate.STATIC),
    Point(
        PointKey.FILTER_REPLACE, 0x88, 1, decode_bool, poll_rate=PollRate.SLOW,
        on_change=Refresh((PointKey.FILTER_TIMER, PointKey.ALARM)),
    ),
    Point(
        PointKey.VENTILATION_MODE, 0xB7, 1, state_decoder(VentilationMode), encode_state,
        poll_rate=PollRate.FAST,
    ),
    Point(PointKey.UNIT_TYPE, 0xB9, 2, decode_int, poll_rate=PollRate.STATIC),
    Point(PointKey.RELAY_SENSOR_ENABLED, 0x14, 1, decode_bool, encode_bool, poll_rate=PollRate.SLOW),
    Point(PointKey.ANALOG_SENSOR_ENABLED, 0x16, 1, decode_bool, encode_bool, poll_rate=PollRate.SLOW),
    Point(
        PointKey.ANALOG_SENSOR_LEVEL, 0x2D, 1, decode_int, unit=Unit.PERCENT,
        on_change=Refresh((PointKey.ANALOG_SENSOR_OVER_THRESHOLD,)),
    ),
    Point(PointKey.RELAY_SENSOR_ACTIVE, 0x32, 1, decode_bool),
    *(
        Point(
            key, parameter, 1, decode_int, int_encoder(1), poll_rate=PollRate.SLOW,
            limits=_whole(10, 255),
        )
        for key, parameter in (
            (PointKey.SUPPLY_SPEED_1, 0x3A),
            (PointKey.EXHAUST_SPEED_1, 0x3B),
            (PointKey.SUPPLY_SPEED_2, 0x3C),
            (PointKey.EXHAUST_SPEED_2, 0x3D),
            (PointKey.SUPPLY_SPEED_3, 0x3E),
            (PointKey.EXHAUST_SPEED_3, 0x3F),
        )
    ),
    Point(PointKey.FAN2_RPM, 0x4B, 2, decode_int, poll_rate=PollRate.FAST, unit=Unit.RPM),
    Point(
        PointKey.FILTER_INTERVAL, 0x63, 2, decode_int, int_encoder(2), poll_rate=PollRate.RARE,
        unit=Unit.DAYS, limits=_whole(70, 365),
        on_change=Refresh((PointKey.FILTER_TIMER, PointKey.FILTER_REPLACE), after=1.0),
    ),
    Point(PointKey.CLOCK_TIME, 0x6F, 3, decode_clock_time, encode_clock_time, poll_rate=PollRate.RARE),
    Point(PointKey.CLOCK_DATE, 0x70, 4, decode_clock_date, encode_clock_date, poll_rate=PollRate.RARE),
    Point(PointKey.WEEKLY_SCHEDULE, 0x72, 1, decode_bool, encode_bool, poll_rate=PollRate.SLOW),
    Point(PointKey.CLOUD_ENABLED, 0x85, 1, decode_bool, encode_bool, poll_rate=PollRate.RARE),
    Point(PointKey.IP_ADDRESS, 0xA3, 4, decode_ipv4, poll_rate=PollRate.RARE),
    Point(
        PointKey.ANALOG_SENSOR_THRESHOLD, 0xB8, 1, decode_int, int_encoder(1), poll_rate=PollRate.SLOW,
        unit=Unit.PERCENT, limits=_whole(5, 100),
        on_change=Refresh((PointKey.ANALOG_SENSOR_OVER_THRESHOLD,), after=1.0),
    ),
    Point(
        PointKey.RESTORE_FAN_SPEEDS, 0x012A, 1, None, command_encoder(b"\x01"),
        write_kind=WriteKind.COMMAND, read_back_after=_COMMAND_TAKEN,
        on_write=Refresh((
            PointKey.SUPPLY_SPEED_1, PointKey.EXHAUST_SPEED_1,
            PointKey.SUPPLY_SPEED_2, PointKey.EXHAUST_SPEED_2,
            PointKey.SUPPLY_SPEED_3, PointKey.EXHAUST_SPEED_3,
        )),
    ),
    *(
        Point(
            key, parameter, 2, decode_minutes_hours, encode_minutes_hours, poll_rate=PollRate.SLOW,
            unit=Unit.MINUTES, limits=_whole(0, 23 * 60 + 59),
        )
        for key, parameter in ((PointKey.NIGHT_TIMER, 0x0302), (PointKey.PARTY_TIMER, 0x0303))
    ),
    Point(PointKey.HUMIDITY_OVER_THRESHOLD, 0x0304, 1, decode_bool),
    Point(PointKey.ANALOG_SENSOR_OVER_THRESHOLD, 0x0305, 1, decode_bool),
)
"""Every point a Duka One has."""
