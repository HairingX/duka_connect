"""The packet format, checked byte by byte."""
import pytest

from duka_connect._protocol import (
    Function,
    ProtocolError,
    checksum,
    decode_request,
    decode_response,
    encode_request,
    encode_response,
)

ID = "ABCDEFGHIJKLMNOP"


def test_a_read_request_is_header_ids_function_parameters_and_checksum() -> None:
    packet = encode_request(ID, "1111", Function.READ, [(0x01, None), (0x25, None)])
    body = b"\xfd\xfd\x02\x10" + ID.encode() + b"\x041111\x01\x01\x25"
    assert packet == body + checksum(body)


def test_the_checksum_is_the_sum_after_the_header_least_significant_byte_first() -> None:
    assert checksum(b"\xfd\xfd\x02\xff\x01") == (0x02 + 0xFF + 0x01).to_bytes(2, "little")


def test_a_value_of_more_than_one_byte_carries_its_size() -> None:
    packet = encode_request(ID, "1", Function.WRITE_READ, [(0x63, b"\x5a\x00")])
    assert b"\xfe\x02\x63\x5a\x00" in packet


def test_a_parameter_above_0xff_is_sent_after_its_page() -> None:
    packet = encode_request(ID, "1", Function.READ, [(0x0302, None), (0x0303, None), (0x01, None)])
    assert packet[-2 - 7:-2] == b"\xff\x03\x02\x03\xff\x00\x01"


def test_a_response_is_read_with_the_sizes_it_carries() -> None:
    packet = encode_response(ID, "1111", [(0x01, b"\x01"), (0x4A, b"\xd2\x04"), (0x24, None)])
    response = decode_response(packet)
    assert response.device_id == ID
    assert response.values == {0x01: b"\x01", 0x4A: b"\xd2\x04", 0x24: None}


def test_a_response_without_a_size_uses_the_known_size() -> None:
    body = b"\xfd\xfd\x02\x01A\x00\x06\x4a\xd2\x04\x25\x2d"
    response = decode_response(body + checksum(body), {0x4A: 2})
    assert response.values == {0x4A: b"\xd2\x04", 0x25: b"\x2d"}


def test_a_page_in_a_response_holds_until_the_next() -> None:
    body = b"\xfd\xfd\x02\x01A\x00\x06\xff\x03\x02\x07\x03\x08\xff\x00\x01\x01"
    response = decode_response(body + checksum(body))
    assert response.values == {0x0302: b"\x07", 0x0303: b"\x08", 0x01: b"\x01"}


def test_a_changed_function_in_a_response_is_skipped() -> None:
    body = b"\xfd\xfd\x02\x01A\x00\x06\xfc\x03\x01\x01"
    assert decode_response(body + checksum(body)).values == {0x01: b"\x01"}


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"\xfd\xfc\x02\x01A\x00\x06\x01\x01\x00\x00",
        encode_response(ID, "", [(0x01, b"\x01")])[:-1] + b"\x00",
        encode_request(ID, "", Function.READ, [(0x01, None)]),
    ],
    ids=["empty", "wrong header", "wrong checksum", "not a response"],
)
def test_a_packet_that_is_not_a_response_is_refused(packet: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode_response(packet)


def test_a_value_running_past_the_end_is_refused() -> None:
    body = b"\xfd\xfd\x02\x01A\x00\x06\xfe\x05\x01\x01"
    with pytest.raises(ProtocolError):
        decode_response(body + checksum(body))


def test_a_request_reads_back_as_it_was_built() -> None:
    parameters: list[tuple[int, bytes | None]] = [(0x01, b"\x01"), (0x63, b"\x5a\x00"), (0x0302, b"\x01")]
    request = decode_request(encode_request(ID, "pw", Function.WRITE_READ, parameters), {})
    assert (request.device_id, request.password, request.function) == (ID, "pw", Function.WRITE_READ)
    assert list(request.parameters) == parameters


def test_a_parameter_number_above_0xffff_is_refused() -> None:
    with pytest.raises(ValueError):
        encode_request(ID, "", Function.READ, [(0x10000, None)])


GUIDE_ID = "\x00" * 16
"""The controller id the connection guide's examples use: sixteen zero bytes."""


def test_the_guides_read_request_is_built_byte_for_byte() -> None:
    packet = encode_request(GUIDE_ID, "1111", Function.READ, [(0x01, None), (0x02, None)])
    assert packet == bytes(
        [0xFD, 0xFD, 0x02, 0x10, *[0x00] * 16, 0x04, 0x31, 0x31, 0x31, 0x31, 0x01, 0x01, 0x02, 0xDE, 0x00]
    )


def test_the_guides_response_is_read() -> None:
    packet = bytes(
        [0xFD, 0xFD, 0x02, 0x10, *[0x00] * 16, 0x04, 0x31, 0x31, 0x31, 0x31, 0x06, 0x01, 0x00, 0x02, 0x03, 0xE6, 0x00]
    )
    assert decode_response(packet).values == {0x01: b"\x00", 0x02: b"\x03"}


def test_the_guides_write_with_a_size_is_built_as_it_shows() -> None:
    packet = encode_request(
        GUIDE_ID, "", Function.WRITE_READ,
        [(0x9B, b"\x02"), (0x70, bytes([0x04, 0x85, 0x37, 0x42])), (0x07, b"\x01")],
    )
    assert packet[-2 - 11:-2] == bytes([0x9B, 0x02, 0xFE, 0x04, 0x70, 0x04, 0x85, 0x37, 0x42, 0x07, 0x01])


def test_the_guides_paged_read_is_built_as_it_shows() -> None:
    packet = encode_request(GUIDE_ID, "", Function.READ, [(0x0101, None), (0x0104, None), (0x0240, None)])
    assert packet[-2 - 7:-2] == bytes([0xFF, 0x01, 0x01, 0x04, 0xFF, 0x02, 0x40])


def test_the_guides_paged_response_with_an_unsupported_parameter_is_read() -> None:
    body = bytes([0xFD, 0xFD, 0x02, 0x10, *[0x00] * 16, 0x00, 0x06]) + bytes(
        [0xFF, 0x01, 0xFD, 0x01, 0x04, 0x05, 0xFF, 0x02, 0xFE, 0x02, 0x40, 0x51, 0x68]
    )
    assert decode_response(body + checksum(body)).values == {
        0x0101: None, 0x0104: b"\x05", 0x0240: b"\x51\x68"
    }
