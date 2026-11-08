"""The installed package."""
import event_connect

import duka_connect
import duka_connect.testing


def test_the_version_is_the_installed_packages() -> None:
    assert duka_connect.__version__


def test_everything_exported_exists() -> None:
    for name in duka_connect.__all__:
        assert hasattr(duka_connect, name), name
    for name in duka_connect.testing.__all__:
        assert hasattr(duka_connect.testing, name), name


def test_every_point_has_its_own_key() -> None:
    names = [str(point.key) for point in duka_connect.DUKA_ONE]
    assert len(names) == len(set(names))


def test_the_timer_modes_are_named_by_what_they_do() -> None:
    assert [mode.name for mode in duka_connect.TimerMode] == ["OFF", "REDUCED", "BOOST"]
    assert {str(duka_connect.PointKey.REDUCED_DURATION), str(duka_connect.PointKey.BOOST_DURATION)} == {
        "reduced_duration", "boost_duration"}


def test_the_clock_battery_voltage_has_been_read_on_a_duka_one() -> None:
    points = {point.key: point for point in duka_connect.DUKA_ONE}
    assert points[duka_connect.PointKey.RTC_BATTERY_VOLTAGE].certainty is duka_connect.Certainty.VERIFIED


def test_a_points_certainty_is_the_one_every_point_has() -> None:
    assert duka_connect.Point.__dataclass_fields__["certainty"] is event_connect.Point.__dataclass_fields__["certainty"]


def test_every_number_that_can_be_written_says_its_range_and_its_encoding_carries_it() -> None:
    for point in duka_connect.DUKA_ONE:
        if not point.writable or point.key.type is not int:
            continue
        write_range = point.write_range()
        assert write_range is not None and write_range.step == 1, point.key
        for value in (int(write_range.min), int(write_range.max)):
            assert point.to_value(point.to_bytes(value)) == value, (point.key, value)
