"""A simulated Duka One, and a clock that moves only when told, for testing code that uses this
library without a unit."""
import asyncio
from collections.abc import Iterable, Mapping

from ._duka_one import DUKA_ONE
from ._event_connect.testing import FakeClock
from ._protocol import (
    SEARCH_DEVICE_ID,
    Function,
    ProtocolError,
    decode_request,
    encode_response,
)

_SEARCH = 0x7C
_RESET_FILTER_TIMER = 0x65
_RESET_ALARMS = 0x80
_FILTER_TIMER = 0x64
_FILTER_REPLACE = 0x88
_ALARM = 0x83
_RESTORE_FAN_SPEEDS = 0x012A
_FAN_SPEEDS = range(0x3A, 0x40)
_SIZES = {point.parameter: point.size for point in DUKA_ONE}

DEFAULT_VALUES: Mapping[int, bytes] = {
    0x01: b"\x01",
    0x02: b"\x02",
    0x06: b"\x00",
    0x07: b"\x00",
    0x0B: b"\x00\x00\x00",
    0x0F: b"\x00",
    0x19: bytes([60]),
    0x24: (3010).to_bytes(2, "little"),
    0x25: bytes([45]),
    0x44: bytes([128]),
    0x4A: (1250).to_bytes(2, "little"),
    0x64: bytes([30, 12, 75]),
    0x66: bytes([5]),
    0x7E: bytes([10, 4]) + (400).to_bytes(2, "little"),
    0x83: b"\x00",
    0x86: bytes([1, 5, 17, 5]) + (2023).to_bytes(2, "little"),
    0x88: b"\x00",
    0xB7: b"\x01",
    0xB9: (3).to_bytes(2, "little"),
    0x14: b"\x00",
    0x16: b"\x00",
    0x2D: bytes([0]),
    0x32: b"\x00",
    **dict(zip(range(0x3A, 0x40), (bytes([speed]) for speed in (80, 80, 160, 160, 255, 255)))),
    0x4B: (1240).to_bytes(2, "little"),
    0x63: (90).to_bytes(2, "little"),
    0x6F: bytes([15, 30, 12]),
    0x70: bytes([26, 1, 10, 26]),
    0x72: b"\x00",
    0x85: b"\x01",
    0xA3: bytes([192, 0, 2, 10]),
    0xB8: bytes([50]),
    0x0302: bytes([0, 8]),
    0x0303: bytes([0, 4]),
    0x0304: b"\x00",
    0x0305: b"\x00",
}
"""What a simulated unit starts with, by parameter number: a running unit with no alarm, its
clock at 12:30:15 on Monday 26 October 2026, and the documentation address 192.0.2.10."""

FILTER_DAYS = 90
"""The days a filter timer is reset to."""


class SimulatedDuka(asyncio.DatagramProtocol):
    """A Duka One answering on a local UDP port.

    `values` is the unit's state by parameter number, and can be changed between requests.
    A wrong password, a parameter the unit does not have, and `answering = False` behave as a
    unit does: no answer, an "unsupported" marker, and silence.
    """

    def __init__(
        self,
        device_id: str = "DUKA0000TEST0001",
        password: str = "1111",
        values: Mapping[int, bytes] | None = None,
        unsupported: Iterable[int] = (),
    ) -> None:
        """Set up a unit; it answers once `start()` has bound it."""
        self.device_id = device_id
        self.password = password
        self.values: dict[int, bytes] = dict(DEFAULT_VALUES if values is None else values)
        self.unsupported = set(unsupported)
        self.answering = True
        self.requests: list[tuple[Function, list[int]]] = []
        self.port = 0
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> int:
        """Bind the unit, and return the port it answers on, also kept as `port`."""
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(lambda: self, local_addr=(host, port))
        self._transport = transport
        self.port = int(transport.get_extra_info("sockname")[1])
        return self.port

    def close(self) -> None:
        """Stop answering and release the port."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Keep the transport answers are sent on."""
        assert isinstance(transport, asyncio.DatagramTransport)
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str | object, int]) -> None:
        """Answer a request as a Duka One does."""
        try:
            request = decode_request(data, _SIZES)
        except ProtocolError:
            return
        self.requests.append((request.function, [number for number, _ in request.parameters]))
        if not self.answering or self._transport is None:
            return
        if request.device_id == SEARCH_DEVICE_ID:
            if request.function is Function.READ:
                answer = [(_SEARCH, self.device_id.encode("ascii"))] + [
                    (number, self._get(number))
                    for number, _ in request.parameters if number != _SEARCH
                ]
                self._transport.sendto(encode_response(self.device_id, "", answer), addr)
            return
        if request.device_id != self.device_id or request.password != self.password:
            return
        if request.function in (Function.WRITE, Function.WRITE_READ):
            for number, value in request.parameters:
                if value is not None and number not in self.unsupported:
                    self._set(number, value)
        if request.function is Function.WRITE:
            return
        answer = [(number, self._get(number)) for number, _ in request.parameters]
        self._transport.sendto(encode_response(self.device_id, self.password, answer), addr)

    def _get(self, number: int) -> bytes | None:
        if number in self.unsupported:
            return None
        return self.values.get(number)

    def _set(self, number: int, value: bytes) -> None:
        if number == _RESET_FILTER_TIMER:
            self.values[_FILTER_TIMER] = bytes([0, 0, FILTER_DAYS])
            self.values[_FILTER_REPLACE] = b"\x00"
        elif number == _RESET_ALARMS:
            self.values[_ALARM] = b"\x00"
        elif number == _RESTORE_FAN_SPEEDS:
            for speed in _FAN_SPEEDS:
                self.values[speed] = DEFAULT_VALUES[speed]
        elif number in self.values:
            self.values[number] = value


__all__ = ["DEFAULT_VALUES", "FILTER_DAYS", "FakeClock", "SimulatedDuka"]
