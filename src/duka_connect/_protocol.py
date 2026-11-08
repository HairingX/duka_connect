"""The Duka One's UDP protocol: building requests and reading responses."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum

PORT = 4000
"""The UDP port the unit listens on."""

SEARCH_DEVICE_ID = "DEFAULT_DEVICEID"
"""The device id every unit answers to, used by discovery."""

DEVICE_ID_PARAMETER = 0x7C
"""The parameter that holds the unit's device id, which discovery reads."""

_HEADER = b"\xfd\xfd"
_PROTOCOL_TYPE = 0x02
_MAX_TEXT = 0xFF

FUNCTION_MARKER = 0xFC
"""In an answer, before a function: the function changes to it."""

UNSUPPORTED_MARKER = 0xFD
"""In an answer, before a parameter's low byte: the unit does not have the parameter."""

SIZE_MARKER = 0xFE
"""Before a size: the next parameter's value has that many bytes."""

PAGE_MARKER = 0xFF
"""Before a page: the parameters after it are on that page, until the next page marker."""


class Function(IntEnum):
    """What a packet asks the unit to do, or that it is the unit's answer."""

    READ = 0x01
    WRITE = 0x02
    WRITE_READ = 0x03
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


def start_packet(device_id: str, password: str, function: Function) -> bytearray:
    """Return a packet's start, up to and including its function, for its parameters to follow.

    Raises:
        ValueError: a device id or password longer than the protocol can carry.
    """
    body = bytearray(_HEADER)
    body.append(_PROTOCOL_TYPE)
    body += _text(device_id, "device id")
    body += _text(password, "password")
    body.append(function)
    return body


def end_packet(body: bytearray) -> bytes:
    """Return the packet `body` with its checksum after it."""
    return bytes(body) + checksum(bytes(body))


def open_packet(packet: bytes) -> tuple[str, str, int, int]:
    """Check a packet's frame, and read the device id and password it carries.

    Returns:
        The device id, the password, the position of the function, and the end of the
        parameters, where the checksum starts.

    Raises:
        ProtocolError: the packet is not a valid Duka One packet.
    """
    if len(packet) < 8 or not packet.startswith(_HEADER):
        raise ProtocolError("Not a Duka One packet")
    if checksum(packet[:-2]) != packet[-2:]:
        raise ProtocolError("Wrong checksum")
    if packet[2] != _PROTOCOL_TYPE:
        raise ProtocolError(f"Unknown protocol type 0x{packet[2]:02X}")
    end = len(packet) - 2
    device_id, pos = _read_text(packet, 3, end)
    password, pos = _read_text(packet, pos, end)
    if pos >= end:
        raise ProtocolError("The packet has no function")
    return device_id, password, pos, end


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
    body = start_packet(device_id, password, function)
    page = 0
    for number, value in parameters:
        if not 0 <= number <= 0xFFFF:
            raise ValueError(f"Parameter 0x{number:X} is not a parameter number")
        # The page is sticky: it holds for every parameter after it until the next one.
        if number >> 8 != page:
            page = number >> 8
            body += bytes([PAGE_MARKER, page])
        if value is not None and len(value) != 1:
            if not 0 < len(value) <= 0xFF:
                raise ValueError(f"Parameter 0x{number:X} has a value of {len(value)} bytes")
            body += bytes([SIZE_MARKER, len(value)])
        body.append(number & 0xFF)
        if value is not None:
            body += value
    return end_packet(body)


def decode_response(packet: bytes, sizes: Mapping[int, int] | None = None) -> Response:
    """Read a response.

    Args:
        sizes: the size in bytes of parameters the unit may send without saying their size;
            any other parameter without a size is one byte.

    Raises:
        ProtocolError: the packet is not a valid response.
    """
    sizes = sizes or {}
    device_id, password, pos, end = open_packet(packet)
    if packet[pos] != Function.RESPONSE:
        raise ProtocolError("Not a response")
    pos += 1
    try:
        values: dict[int, bytes | None] = {}
        page = 0
        while pos < end:
            marker = packet[pos]
            if marker == FUNCTION_MARKER:
                pos += 2
                continue
            if marker == PAGE_MARKER:
                page = packet[pos + 1]
                pos += 2
                continue
            if marker == UNSUPPORTED_MARKER:
                values[page << 8 | packet[pos + 1]] = None
                pos += 2
                continue
            if marker == SIZE_MARKER:
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
