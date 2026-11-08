"""The unit's side of the protocol: reading requests and building responses, as a Duka One does."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .._protocol import (
    PAGE_MARKER,
    SIZE_MARKER,
    UNSUPPORTED_MARKER,
    Function,
    ProtocolError,
    end_packet,
    open_packet,
    start_packet,
)


@dataclass(frozen=True, slots=True)
class Request:
    """A request, as the unit reads it."""

    device_id: str
    password: str
    function: Function
    parameters: Sequence[tuple[int, bytes | None]]


def decode_request(packet: bytes, sizes: Mapping[int, int]) -> Request:
    """Read a request.

    Args:
        sizes: the size in bytes of each parameter a write may carry without saying its size;
            any other is one byte.

    Raises:
        ProtocolError: the packet is not a valid request.
    """
    device_id, password, pos, end = open_packet(packet)
    try:
        function = Function(packet[pos])
    except ValueError as error:
        raise ProtocolError(f"Unknown function 0x{packet[pos]:02X}") from error
    pos += 1
    carries_values = function is not Function.READ
    parameters: list[tuple[int, bytes | None]] = []
    page = 0
    try:
        while pos < end:
            marker = packet[pos]
            if marker == PAGE_MARKER:
                page = packet[pos + 1]
                pos += 2
                continue
            size: int | None = None
            if marker == SIZE_MARKER:
                size = packet[pos + 1]
                pos += 2
            number = page << 8 | packet[pos]
            pos += 1
            if not carries_values:
                parameters.append((number, None))
                continue
            size = size if size is not None else sizes.get(number, 1)
            if pos + size > end:
                raise ProtocolError(f"Parameter 0x{number:X} runs past the end of the packet")
            parameters.append((number, packet[pos:pos + size]))
            pos += size
    except IndexError as error:
        raise ProtocolError("The packet ends in the middle of a parameter") from error
    return Request(device_id, password, function, parameters)


def encode_response(
    device_id: str,
    password: str,
    values: Sequence[tuple[int, bytes | None]],
) -> bytes:
    """Build a response, as the unit does: a value of more than one byte carries its size.

    Args:
        values: each parameter number with its bytes, or `None` for one the unit does not have.
    """
    body = start_packet(device_id, password, Function.RESPONSE)
    page = 0
    for number, value in values:
        if number >> 8 != page:
            page = number >> 8
            body += bytes([PAGE_MARKER, page])
        if value is None:
            body += bytes([UNSUPPORTED_MARKER, number & 0xFF])
            continue
        if len(value) != 1:
            body += bytes([SIZE_MARKER, len(value)])
        body.append(number & 0xFF)
        body += value
    return end_packet(body)
