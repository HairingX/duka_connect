"""Finding Duka One units on the local network."""
import asyncio
import logging
import socket
from dataclasses import dataclass

from ._protocol import PORT, SEARCH_DEVICE_ID, Function, ProtocolError, decode_response, encode_request

_LOGGER = logging.getLogger(__name__)

_SEARCH = 0x7C
_UNIT_TYPE = 0xB9
_SIZES = {_SEARCH: 16, _UNIT_TYPE: 2}


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    """A unit that answered discovery."""

    host: str
    device_id: str
    unit_type: int | None


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.found: dict[str, DiscoveredDevice] = {}

    def datagram_received(self, data: bytes, addr: tuple[str | object, int]) -> None:
        try:
            response = decode_response(data, _SIZES)
        except ProtocolError:
            return
        raw_id = response.values.get(_SEARCH)
        if raw_id is None:
            return
        try:
            device_id = raw_id.decode("ascii")
        except UnicodeDecodeError:
            return
        raw_type = response.values.get(_UNIT_TYPE)
        unit_type = None if raw_type is None else int.from_bytes(raw_type, "little")
        self.found[device_id] = DiscoveredDevice(str(addr[0]), device_id, unit_type)


async def discover(
    target: str = "255.255.255.255", *, port: int = PORT, timeout: float = 2.0
) -> list[DiscoveredDevice]:
    """Ask every unit at `target` - the broadcast address, or one unit's address - who it is.

    Returns:
        The units that answered within `timeout` seconds, each once.
    """
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _Protocol, local_addr=("0.0.0.0", 0), family=socket.AF_INET, allow_broadcast=True
    )
    try:
        packet = encode_request(
            SEARCH_DEVICE_ID, "", Function.READ, [(_SEARCH, None), (_UNIT_TYPE, None)]
        )
        transport.sendto(packet, (target, port))
        await asyncio.sleep(timeout)
    finally:
        transport.close()
    _LOGGER.debug("Discovery at %s found %d units", target, len(protocol.found))
    return list(protocol.found.values())
