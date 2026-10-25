"""Sending a request to the unit over UDP and waiting for its answer."""
import asyncio
import logging
from collections.abc import Mapping

from ._protocol import ProtocolError, Response, decode_response

_LOGGER = logging.getLogger(__name__)


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.answers: asyncio.Queue[bytes] = asyncio.Queue()

    def datagram_received(self, data: bytes, addr: tuple[str | object, int]) -> None:
        self.answers.put_nowait(data)


class UdpLink:
    """A UDP link to one unit, sending one request at a time."""

    def __init__(self, host: str, port: int) -> None:
        """Remember where the unit is; nothing is opened until the first request."""
        self.host = host
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _Protocol | None = None
        self._lock = asyncio.Lock()

    async def _open(self) -> _Protocol:
        if self._transport is None or self._transport.is_closing() or self._protocol is None:
            loop = asyncio.get_running_loop()
            transport, protocol = await loop.create_datagram_endpoint(
                _Protocol, remote_addr=(self.host, self.port)
            )
            self._transport = transport
            self._protocol = protocol
        return self._protocol

    async def send(self, packet: bytes) -> None:
        """Send a packet that is not answered."""
        async with self._lock:
            await self._open()
            assert self._transport is not None
            self._transport.sendto(packet)

    async def request(
        self,
        packet: bytes,
        device_id: str,
        sizes: Mapping[int, int],
        timeout: float,
        attempts: int,
    ) -> Response:
        """Send a request and return the unit's response.

        A datagram that is not a response from `device_id` is ignored.

        Raises:
            TimeoutError: no response in `attempts` tries of `timeout` seconds each.
        """
        async with self._lock:
            for attempt in range(attempts):
                try:
                    protocol = await self._open()
                except OSError as error:
                    _LOGGER.debug("Cannot open a socket to %s: %s", self.host, error)
                    self._close()
                    continue
                while not protocol.answers.empty():
                    protocol.answers.get_nowait()
                assert self._transport is not None
                self._transport.sendto(packet)
                try:
                    return await asyncio.wait_for(
                        self._answer(protocol, device_id, sizes), timeout
                    )
                except TimeoutError:
                    _LOGGER.debug("No answer from %s, attempt %d of %d", self.host, attempt + 1, attempts)
            raise TimeoutError(f"No answer from {self.host}:{self.port}")

    @staticmethod
    async def _answer(protocol: _Protocol, device_id: str, sizes: Mapping[int, int]) -> Response:
        while True:
            data = await protocol.answers.get()
            try:
                response = decode_response(data, sizes)
            except ProtocolError as error:
                _LOGGER.debug("Ignored a packet that is not a response: %s", error)
                continue
            # A unit answers with its own id, also to a request sent to the search id.
            if not device_id or response.device_id.upper() == device_id.upper():
                return response

    def _close(self) -> None:
        if self._transport is not None:
            self._transport.close()
        self._transport = None
        self._protocol = None

    async def close(self) -> None:
        """Close the socket; a later request opens a new one."""
        async with self._lock:
            self._close()
