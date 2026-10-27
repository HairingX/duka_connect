"""The installed package."""
import duka_connect


def test_the_version_is_the_installed_packages() -> None:
    assert duka_connect.__version__


def test_everything_exported_exists() -> None:
    for name in duka_connect.__all__:
        assert hasattr(duka_connect, name), name


def test_every_point_has_its_own_key() -> None:
    names = [str(point.key) for point in duka_connect.DUKA_ONE]
    assert len(names) == len(set(names))


def test_the_timer_modes_are_named_by_what_they_do() -> None:
    assert [mode.name for mode in duka_connect.TimerMode] == ["OFF", "REDUCED", "BOOST"]
    assert {str(duka_connect.PointKey.REDUCED_DURATION), str(duka_connect.PointKey.BOOST_DURATION)} == {
        "reduced_duration", "boost_duration"}
