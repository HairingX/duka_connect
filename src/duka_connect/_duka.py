"""Reaching Duka One units: a client for one, and finding them on the local network."""
import asyncio
import logging
import socket
from dataclasses import dataclass
from typing import cast

from event_connect import CircuitBreaker, Clock, Fixed, Retry, SystemClock

from ._client import Client
from ._duka_one import DUKA_ONE, PointKey
from ._protocol import (
    DEVICE_ID_PARAMETER,
    PORT,
    SEARCH_DEVICE_ID,
    Function,
    ProtocolError,
    decode_response,
    encode_request,
)
from ._transport import UdpLink

_LOGGER = logging.getLogger(__name__)

_TIMEOUT_MARGIN = 1.0  # guess
"""Seconds a request waits beyond the model's `answers_within`, for the network."""

_ATTEMPTS = 3  # guess
"""How many times a request is sent before the unit counts as not answering it."""

_BREAKER = CircuitBreaker(after=2, retry=Retry(Fixed(10.0), None))  # guess
"""After two requests in a row left unanswered, each already sent `_ATTEMPTS` times, the unit is
not asked for 10 s, then probed with one request, and so on for as long as it stays silent: a pass
over a silent unit fails at once rather than waiting out every request, and an answer is found
within 10 s of the next poll."""

_OFFLINE_AFTER_INTERVALS = 3  # guess
"""Reads of the fastest poll rate the unit may miss before it counts as not answering, so that
one lost answer does not make it unavailable."""

_DISCOVERY_WAIT = 2.0  # guess
"""Seconds discovery waits for answers."""

_BROADCAST = "255.255.255.255"

_UNIT_TYPE = next(point for point in DUKA_ONE.points if point.key == PointKey.UNIT_TYPE)
_SIZES = {DEVICE_ID_PARAMETER: 16, _UNIT_TYPE.parameter: _UNIT_TYPE.size}


def create_client(*, host: str, device_id: str, password: str, port: int = PORT, read_only: bool = False,
                  clock: Clock | None = None) -> Client:
    """A client of the Duka One at `host`, which answers to `device_id` and `password`; nothing is
    sent until it is connected.

    Args:
        password: the unit's password: `DEFAULT_PASSWORD` unless it was changed in Duka's app.
        read_only: refuse every write.
        clock: the clocks values are read and stamped by; the system's when None.
    """
    return build_client(host, port, device_id=device_id, password=password,
                        timeout=DUKA_ONE.answers_within + _TIMEOUT_MARGIN, attempts=_ATTEMPTS,
                        read_only=read_only, clock=clock or SystemClock())


def build_client(host: str, port: int, *, device_id: str, password: str, timeout: float, attempts: int,
                 read_only: bool, clock: Clock) -> Client:
    """A client of the Duka One at `host`, waiting `timeout` seconds for each of `attempts` sends
    of a request, and otherwise as `create_client` makes it."""
    link = UdpLink(host, port, timeout=timeout, attempts=attempts, breaker=_BREAKER, clock=clock)
    return Client(link, device_id=device_id, password=password, model=DUKA_ONE,
                  offline_after_intervals=_OFFLINE_AFTER_INTERVALS, read_only=read_only, clock=clock)


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    """A unit that answered discovery."""

    host: str
    """The address it answered from."""
    port: int
    """The port it answered from."""
    device_id: str
    """The id a client reaches it by."""
    unit_type: int | None
    """The kind of unit it says it is; None if it did not say."""


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.found: dict[str, DiscoveredDevice] = {}

    def datagram_received(self, data: bytes, addr: tuple[str | object, int]) -> None:
        try:
            response = decode_response(data, _SIZES)
        except ProtocolError:
            return
        raw_id = response.values.get(DEVICE_ID_PARAMETER)
        if raw_id is None:
            return
        try:
            device_id = raw_id.decode("ascii")
        except UnicodeDecodeError:
            return
        raw_type = response.values.get(_UNIT_TYPE.parameter)
        unit_type = None if raw_type is None else cast(int, _UNIT_TYPE.to_value(raw_type))
        self.found[device_id] = DiscoveredDevice(str(addr[0]), int(addr[1]), device_id, unit_type)


async def discover(*, target: str | None = None, port: int = PORT) -> list[DiscoveredDevice]:
    """Ask the unit at `target`, or every unit on the local network when it is None, who it is.

    Returns:
        The units that answered, each once.
    """
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _Protocol, local_addr=("0.0.0.0", 0), family=socket.AF_INET, allow_broadcast=True
    )
    address = _BROADCAST if target is None else target
    try:
        packet = encode_request(
            SEARCH_DEVICE_ID, "", Function.READ, [(DEVICE_ID_PARAMETER, None), (_UNIT_TYPE.parameter, None)]
        )
        transport.sendto(packet, (address, port))
        await asyncio.sleep(_DISCOVERY_WAIT)
    finally:
        transport.close()
    _LOGGER.debug("Discovery at %s found %d units", address, len(protocol.found))
    return list(protocol.found.values())
