"""A model of a unit on the Duka One's protocol, and the Duka One's."""
import math
from typing import Any, cast

import pytest

from duka_connect import DUKA_ONE, Certainty, DukaModel, Key, Point, PointKey, PollRate
from duka_connect._points import decode_bool, decode_int


def model(points: tuple[Point[Any], ...], poll_intervals: dict[PollRate, float], *,
          read_back_after: float = 1.0, answers_within: float = 1.0) -> DukaModel:
    return DukaModel(name="Test", manufacturer="Maker", points=points, poll_intervals=poll_intervals,
                     read_back_after=read_back_after, answers_within=answers_within)


ON = Point(Key("on", bool), 0x01, 1, decode_bool, poll_rate=PollRate.FAST)
LEVEL = Point(Key("level", int), 0x02, 1, decode_int, poll_rate=PollRate.STATIC)


def test_the_duka_one_has_an_interval_for_exactly_the_rates_its_points_are_read_at() -> None:
    assert dict(DUKA_ONE.poll_intervals) == {
        PollRate.FAST: 10.0, PollRate.MEDIUM: 30.0, PollRate.SLOW: 60.0, PollRate.RARE: 900.0}


def test_the_duka_one_reads_a_command_back_a_second_after_it_and_answers_within_a_second() -> None:
    assert (DUKA_ONE.read_back_after, DUKA_ONE.answers_within) == (1.0, 1.0)
    assert DUKA_ONE.timing.read_back_after == 1.0 and DUKA_ONE.timing.fastest_interval == 10.0


READ_ON_A_DUKA_ONE = {
    PointKey.ALARM, PointKey.ANALOG_SENSOR_ENABLED, PointKey.ANALOG_SENSOR_LEVEL,
    PointKey.ANALOG_SENSOR_OVER_THRESHOLD, PointKey.ANALOG_SENSOR_THRESHOLD, PointKey.BOOST,
    PointKey.BOOST_DURATION, PointKey.BOOST_OFF_DELAY, PointKey.CLOCK_DATE, PointKey.CLOCK_TIME,
    PointKey.CLOUD_ENABLED, PointKey.FAN_RPM, PointKey.FILTER_REPLACE, PointKey.FILTER_TIMER,
    PointKey.FIRMWARE_DATE, PointKey.FIRMWARE_VERSION, PointKey.HUMIDITY, PointKey.HUMIDITY_OVER_THRESHOLD,
    PointKey.HUMIDITY_SENSOR_ENABLED, PointKey.HUMIDITY_THRESHOLD, PointKey.IP_ADDRESS, PointKey.MANUAL_SPEED,
    PointKey.OPERATING_TIME, PointKey.POWER, PointKey.REDUCED_DURATION, PointKey.RELAY_SENSOR_ACTIVE,
    PointKey.RELAY_SENSOR_ENABLED, PointKey.RTC_BATTERY_VOLTAGE, PointKey.SPEED, PointKey.TIMER_COUNTDOWN,
    PointKey.TIMER_MODE, PointKey.UNIT_TYPE, PointKey.VENTILATION_MODE, PointKey.WEEKLY_SCHEDULE,
}


def test_exactly_the_points_read_on_a_duka_one_are_verified_and_every_other_is_reported() -> None:
    """`fan2_rpm` was read too, but what it measures on a Duka One is not known."""
    certainties = {point.key: point.certainty for point in DUKA_ONE.points}
    assert {key for key, certainty in certainties.items() if certainty is Certainty.VERIFIED} == READ_ON_A_DUKA_ONE
    assert all(certainty is Certainty.REPORTED
               for key, certainty in certainties.items() if key not in READ_ON_A_DUKA_ONE)


def test_a_model_with_its_rates_is_made() -> None:
    made = model((ON, LEVEL), {PollRate.FAST: 5.0})
    assert made.timing.poll_intervals == {PollRate.FAST: 5.0}


def test_a_rate_a_point_is_read_at_needs_an_interval() -> None:
    with pytest.raises(ValueError, match="FAST is used by a point but has no interval"):
        model((ON,), {})


def test_an_interval_no_point_is_read_at_is_refused() -> None:
    with pytest.raises(ValueError, match="SLOW has an interval but no point is read at it"):
        model((ON,), {PollRate.FAST: 5.0, PollRate.SLOW: 60.0})


def test_a_key_used_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="'on' is used twice"):
        model((ON, ON), {PollRate.FAST: 5.0})


def test_every_problem_is_named_at_once() -> None:
    with pytest.raises(ValueError) as raised:
        model((ON,), {PollRate.FAST: -1.0}, read_back_after=math.nan, answers_within=0.0)
    message = str(raised.value)
    assert "interval of FAST" in message and "read_back_after" in message and "answers_within" in message


def test_the_intervals_cannot_be_changed_once_the_model_is_made() -> None:
    intervals = {PollRate.FAST: 5.0}
    made = model((ON,), intervals)
    intervals[PollRate.FAST] = 1.0
    assert made.poll_intervals[PollRate.FAST] == 5.0
    with pytest.raises(TypeError):
        cast(dict[PollRate, float], made.poll_intervals)[PollRate.FAST] = 1.0


def test_an_interval_for_static_is_refused() -> None:
    with pytest.raises(ValueError, match="STATIC is never read on a timer"):
        model((ON, LEVEL), {PollRate.FAST: 5.0, PollRate.STATIC: 5.0})
