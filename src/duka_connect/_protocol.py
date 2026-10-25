"""The Duka One's UDP protocol: building requests and reading responses."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum

PORT = 4000
"""The UDP port the unit listens on."""

SEARCH_DEVICE_ID = "DEFAULT_DEVICEID"
"""The device id every unit answers to, used by discovery."""

_HEADER = b"\xfd\xfd"
_PROTOCOL_TYPE = 0x02
_CHANGE_FUNCTION = 0xFC
_UNSUPPORTED = 0xFD
_VALUE_SIZE = 0xFE
_PAGE = 0xFF
_MAX_TEXT = 0xFF


class Function(IntEnum):
    """What a packet asks the unit to do, or that it is the unit's answer."""

    READ = 0x01
    WRITE = 0x02
    WRITE_READ = 0x03
    INCREMENT_READ = 0x04
    DECREMENT_READ = 0x05
    RESPONSE = 0x06


class ProtocolError(Exception):
    """A packet that is not a valid Duka One packet."""


@dataclass(frozen=True, slots=True)
class Response:
    """A response from the unit.

    `values` maps each parameter number to the bytes the unit answered, least significant byte
    first, or to `None` where the unit said it does not have the parameter.
    """

    device_id: str
    password: str
    values: Mapping[int, bytes | None]


def checksum(data: bytes) -> bytes:
    """Return the checksum of a packet without its checksum: the sum of its bytes after the header."""
    total = sum(data[len(_HEADER):]) & 0xFFFF
    return total.to_bytes(2, "little")


def _text(value: str, what: str) -> bytes:
    encoded = value.encode("ascii")
    if len(encoded) > _MAX_TEXT:
        raise ValueError(f"The {what} is longer than {_MAX_TEXT} characters")
    return bytes([len(encoded)]) + encoded


def encode_request(
    device_id: str,
    password: str,
    function: Function,
    parameters: Sequence[tuple[int, bytes | None]],
) -> bytes:
    """Build a request.

    Args:
        parameters: each parameter number, up to 0xFFFF, with the bytes to write, least
            significant first, or `None` to only name it, as a read does.

    Raises:
        ValueError: a parameter number or value the protocol cannot carry.
    """
    body = bytearray(_HEADER)
    body.append(_PROTOCOL_TYPE)
    body += _text(device_id, "device id")
    body += _text(password, "password")
    body.append(function)
    page = 0
    for number, value in parameters:
        if not 0 <= number <= 0xFFFF:
            raise ValueError(f"Parameter 0x{number:X} is not a parameter number")
        # The page is sticky: it holds for every parameter after it until the next one.
        if number >> 8 != page:
            page = number >> 8
            body += bytes([_PAGE, page])
        if value is not None and len(value) != 1:
            if not 0 < len(value) <= 0xFF:
                raise ValueError(f"Parameter 0x{number:X} has a value of {len(value)} bytes")
            body += bytes([_VALUE_SIZE, len(value)])
        body.append(number & 0xFF)
        if value is not None:
            body += value
    return bytes(body) + checksum(bytes(body))


def decode_response(packet: bytes, sizes: Mapping[int, int] | None = None) -> Response:
    """Read a response.

    Args:
        sizes: the size in bytes of parameters the unit may send without saying their size;
            any other parameter without a size is one byte.

    Raises:
        ProtocolError: the packet is not a valid response.
    """
    sizes = sizes or {}
    if len(packet) < 8 or not packet.startswith(_HEADER):
        raise ProtocolError("Not a Duka One packet")
    if checksum(packet[:-2]) != packet[-2:]:
        raise ProtocolError("Wrong checksum")
    end = len(packet) - 2
    try:
        if packet[2] != _PROTOCOL_TYPE:
            raise ProtocolError(f"Unknown protocol type 0x{packet[2]:02X}")
        pos = 3
        device_id, pos = _read_text(packet, pos, end)
        password, pos = _read_text(packet, pos, end)
        if pos >= end or packet[pos] != Function.RESPONSE:
            raise ProtocolError("Not a response")
        pos += 1
        values: dict[int, bytes | None] = {}
        page = 0
        while pos < end:
            marker = packet[pos]
            if marker == _CHANGE_FUNCTION:
                pos += 2
                continue
            if marker == _PAGE:
                page = packet[pos + 1]
                pos += 2
                continue
            if marker == _UNSUPPORTED:
                values[page << 8 | packet[pos + 1]] = None
                pos += 2
                continue
            if marker == _VALUE_SIZE:
                size = packet[pos + 1]
                pos += 2
                number = page << 8 | packet[pos]
            else:
                number = page << 8 | marker
                size = sizes.get(number, 1)
            pos += 1
            if pos + size > end:
                raise ProtocolError(f"Parameter 0x{number:X} runs past the end of the packet")
            values[number] = packet[pos:pos + size]
            pos += size
    except IndexError as error:
        raise ProtocolError("The packet ends in the middle of a parameter") from error
    return Response(device_id, password, values)


def _read_text(packet: bytes, pos: int, end: int) -> tuple[str, int]:
    size = packet[pos]
    start = pos + 1
    if start + size > end:
        raise ProtocolError("A text runs past the end of the packet")
    try:
        return packet[start:start + size].decode("ascii"), start + size
    except UnicodeDecodeError as error:
        raise ProtocolError("A text is not ASCII") from error


def encode_response(
    device_id: str,
    password: str,
    values: Sequence[tuple[int, bytes | None]],
) -> bytes:
    """Build a response, as the unit does: a value of more than one byte carries its size.

    Args:
        values: each parameter number with its bytes, or `None` for one the unit does not have.
    """
    body = bytearray(_HEADER)
    body.append(_PROTOCOL_TYPE)
    body += _text(device_id, "device id")
    body += _text(password, "password")
    body.append(Function.RESPONSE)
    page = 0
    for number, value in values:
        if number >> 8 != page:
            page = number >> 8
            body += bytes([_PAGE, page])
        if value is None:
            body += bytes([_UNSUPPORTED, number & 0xFF])
            continue
        if len(value) != 1:
            body += bytes([_VALUE_SIZE, len(value)])
        body.append(number & 0xFF)
        body += value
    return bytes(body) + checksum(bytes(body))


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
    if len(packet) < 8 or not packet.startswith(_HEADER):
        raise ProtocolError("Not a Duka One packet")
    if checksum(packet[:-2]) != packet[-2:]:
        raise ProtocolError("Wrong checksum")
    end = len(packet) - 2
    try:
        if packet[2] != _PROTOCOL_TYPE:
            raise ProtocolError(f"Unknown protocol type 0x{packet[2]:02X}")
        device_id, pos = _read_text(packet, 3, end)
        password, pos = _read_text(packet, pos, end)
        try:
            function = Function(packet[pos])
        except ValueError as error:
            raise ProtocolError(f"Unknown function 0x{packet[pos]:02X}") from error
        pos += 1
        carries_values = function is not Function.READ
        parameters: list[tuple[int, bytes | None]] = []
        page = 0
        while pos < end:
            marker = packet[pos]
            if marker == _PAGE:
                page = packet[pos + 1]
                pos += 2
                continue
            size: int | None = None
            if marker == _VALUE_SIZE:
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
