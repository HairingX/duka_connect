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
