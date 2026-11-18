"""The client as every client of a device is used: event_connect's DeviceClient."""
import asyncio
import logging
from collections.abc import Callable

import pytest

import duka_connect._client
from conftest import make_client
from duka_connect import (
    DUKA_ONE,
    CannotConnectError,
    Client,
    DeviceClient,
    Labels,
    NotConnectedError,
    PointKey,
    Status,
    create_client,
)
from duka_connect.testing import FakeClock, SimulatedDuka


def test_a_client_is_a_device_client(unit: SimulatedDuka, clock: FakeClock) -> None:
    client: DeviceClient = make_client(unit, clock)
    assert isinstance(client, DeviceClient)


async def test_create_client_waits_two_seconds_for_each_of_three_sends(unit: SimulatedDuka) -> None:
    client = create_client(host="127.0.0.1", device_id=unit.device_id, password=unit.password, port=unit.port)
    assert (client._link._timeout, client._link._attempts) == (2.0, 3)
    await client.connect()
    assert client.status(Status.CONNECTED).value is True
    await client.disconnect()


# ========================================================================= the unit and model


async def test_the_model_is_a_duka_one_by_duka(client: Client) -> None:
    assert (client.model.name, client.model.manufacturer) == ("Duka One", "Duka")
    assert client.model is DUKA_ONE


async def test_the_unit_has_every_point_of_its_model(client: Client) -> None:
    assert set(client.points) == {str(point.key) for point in DUKA_ONE.points}
    assert client.has(PointKey.HUMIDITY) and not client.has("nothing")
    assert client.unavailable_reasons == {}
    assert client.instances("zone") == ()


async def test_a_command_can_be_written_and_not_read(client: Client) -> None:
    assert client.can_write(PointKey.RESET_ALARMS) and not client.can_read(PointKey.RESET_ALARMS)
    assert client.can_read(PointKey.HUMIDITY) and not client.can_write(PointKey.HUMIDITY)
    assert not client.can_read("nothing") and not client.can_write("nothing")


async def test_points_are_selected_by_key_or_label(client: Client) -> None:
    assert [point.key for point in client.select([PointKey.HUMIDITY, PointKey.RESET_ALARMS])] == [
        PointKey.HUMIDITY, PointKey.RESET_ALARMS]
    assert client.select(Labels(zone=1)) == ()
    with pytest.raises(KeyError, match="'nothing'"):
        client.select(["nothing"])


async def test_the_values_read_are_a_property(client: Client) -> None:
    humidity = client.values[PointKey.HUMIDITY]
    assert humidity.value == 45 and PointKey.RESET_ALARMS not in client.values


async def test_a_duka_ones_points_never_change(client: Client) -> None:
    told: list[object] = []
    unsubscribe = client.subscribe_points(lambda gained, lost: told.append((gained, lost)))
    await client.refresh()
    unsubscribe()
    assert told == []


async def test_failed_reads_of_a_point_are_counted_until_one_succeeds(client: Client, unit: SimulatedDuka) -> None:
    unit.answering = False
    await client.refresh([PointKey.HUMIDITY])
    assert client.consecutive_failures(PointKey.HUMIDITY) == 1
    unit.answering = True
    await client.refresh([PointKey.HUMIDITY])
    assert client.consecutive_failures(PointKey.HUMIDITY) == 0


async def test_the_diagnostics_say_how_long_the_unit_has_been_silent(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    unit.answering = False
    await client.refresh([PointKey.HUMIDITY])
    clock.advance(4)
    assert client.diagnostics()["silent_for"] == 4.0


# ============================================================================ before connecting


UNKNOWN_BEFORE_CONNECTING: list[Callable[[Client], object]] = [
    lambda client: client.points,
    lambda client: client.model,
    lambda client: client.seconds_until_next_poll(),
    lambda client: client.select([PointKey.HUMIDITY]),
]


@pytest.mark.parametrize("ask", UNKNOWN_BEFORE_CONNECTING)
def test_what_the_unit_has_is_not_known_before_connecting(
    unit: SimulatedDuka, clock: FakeClock, ask: Callable[[Client], object]
) -> None:
    with pytest.raises(NotConnectedError):
        ask(make_client(unit, clock))


def test_before_connecting_the_unit_has_nothing_and_reports_nothing(unit: SimulatedDuka, clock: FakeClock) -> None:
    client = make_client(unit, clock)
    assert not client.has(PointKey.HUMIDITY) and not client.can_read(PointKey.HUMIDITY)
    assert client.identity == {"unit_type": None}
    assert client.values == {} and client.value(PointKey.HUMIDITY) is None


# =========================================================================== after disconnecting


async def test_a_disconnected_client_is_not_connected(unit: SimulatedDuka, clock: FakeClock) -> None:
    client = make_client(unit, clock)
    await client.connect()
    await client.disconnect()
    assert client.status(Status.CONNECTED).value is False


async def test_a_disconnected_client_reads_and_writes_nothing_until_connected_again(
    unit: SimulatedDuka, clock: FakeClock
) -> None:
    client = make_client(unit, clock)
    await client.connect()
    await client.disconnect()
    unit.requests.clear()
    with pytest.raises(NotConnectedError):
        await client.poll()
    with pytest.raises(NotConnectedError):
        await client.refresh()
    with pytest.raises(NotConnectedError):
        await client.write(PointKey.POWER, False)
    assert unit.requests == []
    assert client.model is DUKA_ONE and client.seconds_until_next_poll() is not None
    await client.connect()
    assert client.status(Status.CONNECTED).value is True
    await client.refresh([PointKey.HUMIDITY])
    await client.disconnect()


async def test_a_failed_connect_after_a_disconnect_leaves_the_client_not_connected(
    unit: SimulatedDuka, clock: FakeClock
) -> None:
    client = make_client(unit, clock)
    await client.connect()
    await client.disconnect()
    unit.answering = False
    with pytest.raises(CannotConnectError):
        await client.connect()
    assert client.status(Status.CONNECTED).value is False


# ===================================================================================== running


async def _until(condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not condition():
            await asyncio.sleep(0.01)


async def test_running_reads_what_is_due(client: Client, unit: SimulatedDuka, clock: FakeClock) -> None:
    client.subscribe(PointKey.HUMIDITY, lambda _key, _old, _new: None)
    unit.values[0x25] = bytes([60])
    clock.advance(30)
    running = asyncio.create_task(client.run())
    try:
        await _until(lambda: client.values[PointKey.HUMIDITY].value == 60)
    finally:
        running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running


async def test_running_wakes_when_something_becomes_due(
    client: Client, unit: SimulatedDuka, clock: FakeClock
) -> None:
    client.set_scheduled_polling(False)
    running = asyncio.create_task(client.run())
    await asyncio.sleep(0.05)
    unit.requests.clear()
    clock.advance(30)
    client.set_scheduled_polling(True)
    try:
        await _until(lambda: bool(unit.requests))
    finally:
        running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running


async def test_running_before_connecting_raises(unit: SimulatedDuka, clock: FakeClock) -> None:
    with pytest.raises(NotConnectedError):
        await make_client(unit, clock).run()


async def test_running_ends_when_the_client_is_disconnected(unit: SimulatedDuka, clock: FakeClock) -> None:
    client = make_client(unit, clock)
    await client.connect()
    client.set_scheduled_polling(False)
    running = asyncio.create_task(client.run())
    await asyncio.sleep(0.05)
    await client.disconnect()
    with pytest.raises(NotConnectedError):
        async with asyncio.timeout(2):
            await running


async def test_a_poll_that_raises_is_logged_and_running_goes_on(
    client: Client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    polls = 0

    async def raising() -> None:
        nonlocal polls
        polls += 1
        raise RuntimeError("poll")

    monkeypatch.setattr(duka_connect._client, "_PAUSE_AFTER_FAILURE", 0.01)
    monkeypatch.setattr(client, "poll", raising)
    with caplog.at_level(logging.ERROR):
        running = asyncio.create_task(client.run())
        try:
            await _until(lambda: polls >= 2)
        finally:
            running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    assert "The Duka One could not be polled" in caplog.text
