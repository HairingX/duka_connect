"""Sending a request to the unit over UDP and waiting for its answer."""
import asyncio
import logging
from collections.abc import Mapping

from event_connect import Breaker, CircuitBreaker, Clock

from ._protocol import ProtocolError, Response, decode_response

_LOGGER = logging.getLogger(__name__)


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.answers: asyncio.Queue[bytes] = asyncio.Queue()

    def datagram_received(self, data: bytes, addr: tuple[str | object, int]) -> None:
        self.answers.put_nowait(data)


class UdpLink:
    """A UDP link to one unit, sending one request at a time, and none while its breaker is open."""

    def __init__(self, host: str, port: int, *, timeout: float, attempts: int, breaker: CircuitBreaker,
                 clock: Clock) -> None:
        """Remember where the unit is; nothing is opened until the first request.

        Args:
            timeout: seconds to wait for each answer.
            attempts: how many times a request is sent before it counts as unanswered.
            breaker: after how many unanswered requests the unit is no longer asked, and for how
                long; requests meanwhile are refused at once.
        """
        self.host = host
        self.port = port
        self._timeout = timeout
        self._attempts = attempts
        self._breaker_settings = breaker
        self._breaker: Breaker = breaker.breaker()
        self._clock = clock
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _Protocol | None = None
        self._lock = asyncio.Lock()
        self._requests = 0
        self._unanswered = 0
        self._refused = 0
        self._latency_total = 0.0

    def reset(self) -> None:
        """Close the breaker, so that the next request is sent whatever went unanswered before."""
        self._breaker = self._breaker_settings.breaker()

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

    async def request(self, packet: bytes, device_id: str, sizes: Mapping[int, int]) -> Response | None:
        """Send a request, and return the unit's response; None when it gave none, or the breaker
        refused to send it.

        A datagram that is not a response from `device_id` is ignored.
        """
        attempt = self._breaker.attempt(self._clock.monotonic())
        if attempt is None:
            self._refused += 1
            return None
        with attempt:
            started = self._clock.monotonic()
            self._requests += 1
            try:
                response = await self._exchange(packet, device_id, sizes)
            except TimeoutError:
                self._unanswered += 1
                attempt.unanswered(self._clock.monotonic())
                _LOGGER.debug("%s did not answer", self.host)
                return None
            self._latency_total += self._clock.monotonic() - started
            attempt.answered()
        return response

    async def _exchange(self, packet: bytes, device_id: str, sizes: Mapping[int, int]) -> Response:
        """Send a request and return the unit's response.

        Raises:
            TimeoutError: no response in `attempts` tries of `timeout` seconds each.
        """
        async with self._lock:
            for attempt in range(self._attempts):
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
                    return await asyncio.wait_for(self._answer(protocol, device_id, sizes), self._timeout)
                except TimeoutError:
                    _LOGGER.debug("No answer from %s, attempt %d of %d", self.host, attempt + 1, self._attempts)
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

    def diagnostics(self) -> dict[str, object]:
        """Counters of the requests and the breaker; never the address."""
        open_for = self._breaker.open_for(self._clock.monotonic())
        answered = self._requests - self._unanswered
        return {
            "requests": self._requests,
            "unanswered": self._unanswered,
            "refused_while_open": self._refused,
            "average_latency": self._latency_total / answered if answered else None,
            "consecutive_unanswered": self._breaker.unanswered_in_a_row,
            "open": open_for > 0,
            "open_for": open_for,
            "openings": self._breaker.openings,
            "gave_up": self._breaker.gave_up,
        }

    def _close(self) -> None:
        if self._transport is not None:
            self._transport.close()
        self._transport = None
        self._protocol = None

    async def close(self) -> None:
        """Close the socket; a later request opens a new one."""
        async with self._lock:
            self._close()
