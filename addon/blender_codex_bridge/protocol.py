"""Newline-delimited JSON request/response protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .errors import BridgeError, ErrorCode
from .serialization import dumps, loads, to_jsonable

PROTOCOL_VERSION = "1.0"
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
MAX_REQUEST_ID_LENGTH = 256
MAX_METHOD_LENGTH = 128
MAX_TIMESTAMP_LENGTH = 128


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True, slots=True)
class Request:
    """Validated Blender-side request."""

    id: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    timestamp: str | None = None
    protocol_version: str = PROTOCOL_VERSION
    timeout_ms: int | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Request:
        if not isinstance(value, Mapping):
            raise BridgeError(ErrorCode.INVALID_REQUEST, "Request must be a JSON object.")
        protocol_version = value.get("protocol_version")
        if protocol_version != PROTOCOL_VERSION:
            raise BridgeError(
                ErrorCode.UNSUPPORTED_PROTOCOL_VERSION,
                f"Unsupported protocol version {protocol_version!r}.",
                {"supported": [PROTOCOL_VERSION]},
            )
        if "id" not in value:
            raise BridgeError(ErrorCode.INVALID_REQUEST, "Request is missing required field 'id'.")
        request_id = value.get("id")
        if not isinstance(request_id, str):
            raise BridgeError(
                ErrorCode.INVALID_REQUEST,
                "Request 'id' must be a string.",
            )
        if not request_id.strip():
            raise BridgeError(ErrorCode.INVALID_REQUEST, "Request 'id' cannot be empty.")
        if len(request_id) > MAX_REQUEST_ID_LENGTH:
            raise BridgeError(
                ErrorCode.INVALID_REQUEST,
                f"Request 'id' cannot exceed {MAX_REQUEST_ID_LENGTH} characters.",
            )
        method = value.get("method")
        if not isinstance(method, str) or not method.strip():
            raise BridgeError(
                ErrorCode.INVALID_REQUEST,
                "Request 'method' must be a non-empty string.",
            )
        if len(method) > MAX_METHOD_LENGTH:
            raise BridgeError(
                ErrorCode.INVALID_REQUEST,
                f"Request 'method' cannot exceed {MAX_METHOD_LENGTH} characters.",
            )
        if "params" not in value:
            raise BridgeError(ErrorCode.INVALID_REQUEST, "Request is missing required field 'params'.")
        params = value.get("params")
        if not isinstance(params, Mapping):
            raise BridgeError(ErrorCode.INVALID_REQUEST, "Request 'params' must be an object.")
        timestamp = value.get("timestamp")
        if timestamp is not None and not isinstance(timestamp, str):
            raise BridgeError(ErrorCode.INVALID_REQUEST, "Request 'timestamp' must be a string.")
        if timestamp is not None and len(timestamp) > MAX_TIMESTAMP_LENGTH:
            raise BridgeError(
                ErrorCode.INVALID_REQUEST,
                f"Request 'timestamp' cannot exceed {MAX_TIMESTAMP_LENGTH} characters.",
            )
        timeout_ms = value.get("timeout_ms")
        if timeout_ms is not None and (
            isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0
        ):
            raise BridgeError(
                ErrorCode.INVALID_REQUEST,
                "Request 'timeout_ms' must be a positive integer.",
            )
        return cls(
            request_id,
            method.strip(),
            dict(params),
            timestamp,
            protocol_version,
            timeout_ms,
        )


@dataclass(frozen=True, slots=True)
class Response:
    """A successful or failed protocol response."""

    id: str | None
    ok: bool
    result: Any = None
    error: Mapping[str, Any] | None = None
    timestamp: str = field(default_factory=utc_timestamp)

    @classmethod
    def success(cls, request_id: str, result: Any) -> Response:
        return cls(id=request_id, ok=True, result=to_jsonable(result))

    @classmethod
    def failure(
        cls,
        request_id: str | None,
        error: BridgeError | Mapping[str, Any],
    ) -> Response:
        payload = error.to_dict() if isinstance(error, BridgeError) else dict(error)
        return cls(id=request_id, ok=False, error=to_jsonable(payload))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "ok": self.ok,
            "timestamp": self.timestamp,
            "protocol_version": PROTOCOL_VERSION,
        }
        if self.ok:
            payload["result"] = self.result
        else:
            payload["error"] = dict(self.error or {})
        return payload


def decode_request(line: bytes | str, *, max_bytes: int = MAX_MESSAGE_BYTES) -> Request:
    """Decode and validate one JSON line."""

    raw = line.encode("utf-8") if isinstance(line, str) else line
    if len(raw) > max_bytes:
        raise BridgeError(
            ErrorCode.MESSAGE_TOO_LARGE,
            "Request exceeds the configured message size limit.",
            {"maximum_bytes": max_bytes, "received_bytes": len(raw)},
        )
    try:
        value = loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise BridgeError(ErrorCode.MALFORMED_JSON, "Request is not valid UTF-8 JSON.") from exc
    return Request.from_mapping(value)


def encode_response(response: Response, *, max_bytes: int = MAX_MESSAGE_BYTES) -> bytes:
    """Encode one response with a newline delimiter."""

    payload = dumps(response.to_dict()).encode("utf-8")
    if len(payload) > max_bytes:
        raise BridgeError(
            ErrorCode.MESSAGE_TOO_LARGE,
            "Response exceeds the configured message size limit.",
            {"maximum_bytes": max_bytes, "response_bytes": len(payload)},
        )
    return payload + b"\n"
