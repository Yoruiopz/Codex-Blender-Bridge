from __future__ import annotations

import importlib
import io
import socket

import pytest


def test_transport_accepts_only_literal_ipv4_loopback(addon_package: str) -> None:
    transport = importlib.import_module(f"{addon_package}.transport")
    errors = importlib.import_module(f"{addon_package}.errors")

    assert transport.normalize_loopback_host("localhost") == "127.0.0.1"
    assert transport.normalize_loopback_host("127.0.0.1") == "127.0.0.1"
    for unsafe in ("0.0.0.0", "127.0.0.2", "::1", "192.0.2.1"):
        with pytest.raises(errors.BridgeError):
            transport.normalize_loopback_host(unsafe)


def test_frame_reader_accepts_lf_and_crlf(addon_package: str) -> None:
    transport = importlib.import_module(f"{addon_package}.transport")

    assert transport.read_frame(io.BytesIO(b'{"id":"lf"}\n')) == b'{"id":"lf"}'
    assert transport.read_frame(io.BytesIO(b'{"id":"crlf"}\r\n')) == b'{"id":"crlf"}'


def test_frame_reader_applies_limit_to_payload_not_delimiter(addon_package: str) -> None:
    transport = importlib.import_module(f"{addon_package}.transport")

    payload = b"12345678"
    assert transport.read_frame(io.BytesIO(payload + b"\r\n"), maximum_bytes=8) == payload


def test_frame_reader_rejects_unterminated_and_oversized_frames(
    addon_package: str,
) -> None:
    transport = importlib.import_module(f"{addon_package}.transport")
    errors = importlib.import_module(f"{addon_package}.errors")

    with pytest.raises(errors.BridgeError):
        transport.read_frame(io.BytesIO(b"{}"), maximum_bytes=8)
    with pytest.raises(errors.BridgeError):
        transport.read_frame(io.BytesIO(b"123456789\n"), maximum_bytes=8)


def test_socket_reader_keeps_pipelined_frames_and_partial_bytes_across_timeout(addon_package):
    transport = importlib.import_module(f"{addon_package}.transport")
    left, right = socket.socketpair()
    try:
        left.settimeout(.02)
        reader = transport.SocketLineReader(left)
        right.sendall(b'one\r\ntwo\npartial')
        assert transport.read_frame(reader) == b"one"
        assert transport.read_frame(reader) == b"two"
        with pytest.raises(TimeoutError):
            transport.read_frame(reader)
        right.sendall(b' end\n')
        assert transport.read_frame(reader) == b"partial end"
        right.close()
        assert transport.read_frame(reader) is None
    finally:
        left.close()
        right.close()


def test_socket_reader_bounds_buffering_and_rejects_unterminated_eof(addon_package):
    transport = importlib.import_module(f"{addon_package}.transport")
    errors = importlib.import_module(f"{addon_package}.errors")
    left, right = socket.socketpair()
    try:
        reader = transport.SocketLineReader(left)
        right.sendall(b"1234567890123456")
        with pytest.raises(errors.BridgeError) as caught:
            transport.read_frame(reader, maximum_bytes=8)
        assert caught.value.code == "MESSAGE_TOO_LARGE"
        assert len(reader._buffer) <= 11
        reader = transport.SocketLineReader(left)
        right.close()
        with pytest.raises(errors.BridgeError) as caught:
            transport.read_frame(reader)
        assert caught.value.code == "INVALID_REQUEST"
        with pytest.raises(ValueError):
            reader.readline(-1)
    finally:
        left.close()
        right.close()
