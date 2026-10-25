"""The Duka One's points."""
from datetime import date
from typing import Any

from ._points import (
    Point,
    decode_bool,
    decode_firmware_date,
    decode_firmware_version,
    decode_int,
    decode_minutes_hours_days,
    decode_nothing,
    decode_operating_minutes,
    decode_seconds_minutes_hours,
    encode_bool,
    encode_nothing,
    encode_state,
    int_encoder,
    state_decoder,
)
from ._states import AlarmLevel, Speed, TimerMode, VentilationMode
from ._values import Key, PollRate


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
    RESET_FILTER_TIMER = Key("reset_filter_timer", type(None))
    RESET_ALARMS = Key("reset_alarms", type(None))


DUKA_ONE: tuple[Point[Any], ...] = (
    Point(PointKey.POWER, 0x01, 1, decode_bool, encode_bool, PollRate.FAST),
    Point(PointKey.SPEED, 0x02, 1, state_decoder(Speed), encode_state, PollRate.FAST),
    Point(PointKey.BOOST, 0x06, 1, decode_bool, poll_rate=PollRate.FAST),
    Point(PointKey.TIMER_MODE, 0x07, 1, state_decoder(TimerMode), encode_state, PollRate.FAST),
    Point(PointKey.TIMER_COUNTDOWN, 0x0B, 3, decode_seconds_minutes_hours, unit="s"),
    Point(PointKey.HUMIDITY_SENSOR_ENABLED, 0x0F, 1, decode_bool, encode_bool, PollRate.SLOW),
    Point(
        PointKey.HUMIDITY_THRESHOLD, 0x19, 1, decode_int, int_encoder(1), PollRate.SLOW,
        unit="%", minimum=40, maximum=80,
    ),
    Point(PointKey.RTC_BATTERY_VOLTAGE, 0x24, 2, decode_int, poll_rate=PollRate.RARE, unit="mV"),
    Point(PointKey.HUMIDITY, 0x25, 1, decode_int, unit="%"),
    Point(
        PointKey.MANUAL_SPEED, 0x44, 1, decode_int, int_encoder(1), PollRate.FAST,
        minimum=0, maximum=255,
    ),
    Point(PointKey.FAN_RPM, 0x4A, 2, decode_int, poll_rate=PollRate.FAST, unit="rpm"),
    Point(PointKey.FILTER_TIMER, 0x64, 3, decode_minutes_hours_days, poll_rate=PollRate.RARE, unit="min"),
    Point(PointKey.RESET_FILTER_TIMER, 0x65, 1, decode_nothing, encode_nothing, command=True),
    Point(
        PointKey.BOOST_OFF_DELAY, 0x66, 1, decode_int, int_encoder(1), PollRate.SLOW,
        unit="min", minimum=0, maximum=60,
    ),
    Point(PointKey.OPERATING_TIME, 0x7E, 4, decode_operating_minutes, poll_rate=PollRate.RARE, unit="min"),
    Point(PointKey.RESET_ALARMS, 0x80, 1, decode_nothing, encode_nothing, command=True),
    Point(PointKey.ALARM, 0x83, 1, state_decoder(AlarmLevel), poll_rate=PollRate.SLOW),
    Point(PointKey.FIRMWARE_VERSION, 0x86, 6, decode_firmware_version, poll_rate=PollRate.STATIC),
    Point(PointKey.FIRMWARE_DATE, 0x86, 6, decode_firmware_date, poll_rate=PollRate.STATIC),
    Point(PointKey.FILTER_REPLACE, 0x88, 1, decode_bool, poll_rate=PollRate.SLOW),
    Point(
        PointKey.VENTILATION_MODE, 0xB7, 1, state_decoder(VentilationMode), encode_state,
        PollRate.FAST,
    ),
    Point(PointKey.UNIT_TYPE, 0xB9, 2, decode_int, poll_rate=PollRate.STATIC),
)
"""Every point a Duka One has."""
