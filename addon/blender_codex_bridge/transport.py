"""Socket framing and loopback endpoint validation (no Blender imports)."""

from __future__ import annotations

import ipaddress
from typing import BinaryIO

from .errors import BridgeError, ErrorCode
from .protocol import MAX_MESSAGE_BYTES


def normalize_loopback_host(host: str) -> str:
    """Return a normalized IPv4 loopback host or reject it."""

    if not isinstance(host, str) or not host.strip():
        raise BridgeError(ErrorCode.INVALID_ARGUMENT, "Bridge host must be a loopback address.")
    normalized = host.strip().lower()
    if normalized == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError as exc:
        raise BridgeError(
            ErrorCode.INVALID_ARGUMENT,
            "Bridge host must be a numeric loopback address or 'localhost'.",
            {"host": host},
        ) from exc
    if address.version != 4 or str(address) != "127.0.0.1":
        raise BridgeError(
            ErrorCode.PERMISSION_DENIED,
            "The Blender listener is restricted to IPv4 loopback addresses.",
            {"host": host, "allowed": ["127.0.0.1", "localhost"]},
        )
    return str(address)


def validate_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise BridgeError(ErrorCode.INVALID_ARGUMENT, "Bridge port must be between 1 and 65535.")
    return port


def read_frame(stream: BinaryIO, *, maximum_bytes: int = MAX_MESSAGE_BYTES) -> bytes | None:
    """Read one bounded newline-delimited frame."""

    line = stream.readline(maximum_bytes + 3)
    if not line:
        return None
    if not line.endswith(b"\n"):
        if len(line) <= maximum_bytes:
            raise BridgeError(ErrorCode.INVALID_REQUEST, "Request frame must end with a newline.")
        raise BridgeError(
            ErrorCode.MESSAGE_TOO_LARGE,
            "Request exceeds the maximum NDJSON frame size.",
            {"maximum_bytes": maximum_bytes},
        )
    payload = line[:-1]
    if payload.endswith(b"\r"):
        payload = payload[:-1]
    if len(payload) > maximum_bytes:
        raise BridgeError(
            ErrorCode.MESSAGE_TOO_LARGE,
            "Request exceeds the maximum NDJSON frame size.",
            {"maximum_bytes": maximum_bytes},
        )
    return payload
