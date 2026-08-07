"""Small dependency-free schemas for the newline-delimited JSON protocol."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeAlias

from .errors import BridgeProtocolError

PROTOCOL_VERSION = "1.0"
MAX_REQUEST_ID_LENGTH = 256
MAX_METHOD_LENGTH = 128
MAX_TIMESTAMP_LENGTH = 128
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def utc_timestamp() -> str:
    """Return an RFC 3339-compatible UTC timestamp."""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def validate_json_value(value: Any, *, path: str = "$", depth: int = 0) -> JsonValue:
    """Validate/copy a value before it reaches ``json.dumps``.

    Rejecting NaN, infinity, non-string keys and arbitrarily deep containers makes
    the wire format deterministic and avoids implementation-specific JSON output.
    """

    if depth > 64:
        raise ValueError(f"{path} exceeds the maximum JSON nesting depth")
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain NaN or infinity")
        return value
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            result[key] = validate_json_value(
                item, path=f"{path}.{key}", depth=depth + 1
            )
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return [
            validate_json_value(item, path=f"{path}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    raise ValueError(f"{path} contains unsupported value type {type(value).__name__}")


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BridgeProtocolError(f"'{key}' must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class ErrorPayload:
    code: str
    message: str
    context: dict[str, JsonValue] = field(default_factory=dict)
    retryable: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ErrorPayload:
        if not isinstance(data, Mapping):
            raise BridgeProtocolError("Response 'error' must be an object")
        code = _required_string(data, "code")
        message = _required_string(data, "message")
        raw_context = data.get("context", {})
        if not isinstance(raw_context, Mapping):
            raise BridgeProtocolError("Response error 'context' must be an object")
        try:
            context = validate_json_value(raw_context, path="$.error.context")
        except ValueError as exc:
            raise BridgeProtocolError(str(exc)) from exc
        assert isinstance(context, dict)
        retryable = data.get("retryable", False)
        if not isinstance(retryable, bool):
            raise BridgeProtocolError("Response error 'retryable' must be a boolean")
        return cls(code=code, message=message, context=context, retryable=retryable)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class BridgeRequest:
    id: str
    method: str
    params: dict[str, JsonValue] = field(default_factory=dict)
    timestamp: str | None = None
    timeout_ms: int | None = None
    protocol_version: str = PROTOCOL_VERSION

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        method: str,
        params: Mapping[str, Any] | None = None,
        include_timestamp: bool = True,
        timeout_ms: int | None = None,
    ) -> BridgeRequest:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        if len(request_id) > MAX_REQUEST_ID_LENGTH:
            raise ValueError(
                f"request_id cannot exceed {MAX_REQUEST_ID_LENGTH} characters"
            )
        if not isinstance(method, str) or not method.strip():
            raise ValueError("method must be a non-empty string")
        if len(method) > MAX_METHOD_LENGTH:
            raise ValueError(f"method cannot exceed {MAX_METHOD_LENGTH} characters")
        if params is None:
            clean_params: dict[str, JsonValue] = {}
        elif not isinstance(params, Mapping):
            raise ValueError("params must be an object")
        else:
            clean = validate_json_value(params, path="$.params")
            assert isinstance(clean, dict)
            clean_params = clean
        if timeout_ms is not None and (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or timeout_ms <= 0
        ):
            raise ValueError("timeout_ms must be a positive integer")
        return cls(
            id=request_id,
            method=method,
            params=clean_params,
            timestamp=utc_timestamp() if include_timestamp else None,
            timeout_ms=timeout_ms,
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> BridgeRequest:
        if not isinstance(data, Mapping):
            raise BridgeProtocolError("Request must be a JSON object")
        request_id = _required_string(data, "id")
        method = _required_string(data, "method")
        if len(request_id) > MAX_REQUEST_ID_LENGTH:
            raise BridgeProtocolError(
                f"Request 'id' cannot exceed {MAX_REQUEST_ID_LENGTH} characters"
            )
        if len(method) > MAX_METHOD_LENGTH:
            raise BridgeProtocolError(
                f"Request 'method' cannot exceed {MAX_METHOD_LENGTH} characters",
                request_id=request_id,
            )
        version = data.get("protocol_version")
        if version != PROTOCOL_VERSION:
            raise BridgeProtocolError(
                f"Unsupported protocol version {version!r}",
                context={"supported": [PROTOCOL_VERSION]},
                request_id=request_id,
            )
        params = data.get("params", {})
        if not isinstance(params, Mapping):
            raise BridgeProtocolError("Request 'params' must be an object")
        try:
            clean = validate_json_value(params, path="$.params")
        except ValueError as exc:
            raise BridgeProtocolError(str(exc), request_id=request_id) from exc
        assert isinstance(clean, dict)
        timestamp = data.get("timestamp")
        if timestamp is not None and not isinstance(timestamp, str):
            raise BridgeProtocolError("Request 'timestamp' must be a string")
        if timestamp is not None and len(timestamp) > MAX_TIMESTAMP_LENGTH:
            raise BridgeProtocolError(
                f"Request 'timestamp' cannot exceed {MAX_TIMESTAMP_LENGTH} characters",
                request_id=request_id,
            )
        timeout_ms = data.get("timeout_ms")
        if timeout_ms is not None and (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or timeout_ms <= 0
        ):
            raise BridgeProtocolError(
                "Request 'timeout_ms' must be a positive integer",
                request_id=request_id,
            )
        return cls(
            id=request_id,
            method=method,
            params=clean,
            timestamp=timestamp,
            timeout_ms=timeout_ms,
            protocol_version=version,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {
            "id": self.id,
            "method": self.method,
            "params": self.params,
            "protocol_version": self.protocol_version,
        }
        if self.timestamp is not None:
            result["timestamp"] = self.timestamp
        if self.timeout_ms is not None:
            result["timeout_ms"] = self.timeout_ms
        return result


@dataclass(frozen=True, slots=True)
class BridgeResponse:
    id: str
    ok: bool
    result: JsonValue = None
    error: ErrorPayload | None = None
    timestamp: str = field(default_factory=utc_timestamp)
    protocol_version: str = PROTOCOL_VERSION

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> BridgeResponse:
        if not isinstance(data, Mapping):
            raise BridgeProtocolError("Response must be a JSON object")
        request_id = _required_string(data, "id")
        version = data.get("protocol_version")
        if version != PROTOCOL_VERSION:
            raise BridgeProtocolError(
                f"Unsupported response protocol version {version!r}",
                context={"supported": [PROTOCOL_VERSION]},
                request_id=request_id,
            )
        timestamp = data.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise BridgeProtocolError(
                "Response 'timestamp' must be a non-empty string",
                request_id=request_id,
            )
        if len(timestamp) > MAX_TIMESTAMP_LENGTH:
            raise BridgeProtocolError(
                f"Response 'timestamp' cannot exceed {MAX_TIMESTAMP_LENGTH} characters",
                request_id=request_id,
            )
        ok = data.get("ok")
        if not isinstance(ok, bool):
            raise BridgeProtocolError(
                "Response 'ok' must be a boolean", request_id=request_id
            )
        if ok:
            if "result" not in data:
                raise BridgeProtocolError(
                    "Successful response is missing 'result'", request_id=request_id
                )
            if "error" in data and data["error"] is not None:
                raise BridgeProtocolError(
                    "Successful response must not contain an error",
                    request_id=request_id,
                )
            try:
                result = validate_json_value(data["result"], path="$.result")
            except ValueError as exc:
                raise BridgeProtocolError(str(exc), request_id=request_id) from exc
            return cls(
                id=request_id,
                ok=True,
                result=result,
                timestamp=timestamp,
                protocol_version=version,
            )
        if "error" not in data:
            raise BridgeProtocolError(
                "Failed response is missing 'error'", request_id=request_id
            )
        error = ErrorPayload.from_mapping(data["error"])
        return cls(
            id=request_id,
            ok=False,
            error=error,
            timestamp=timestamp,
            protocol_version=version,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        if self.ok:
            return {
                "id": self.id,
                "ok": True,
                "result": self.result,
                "timestamp": self.timestamp,
                "protocol_version": self.protocol_version,
            }
        if self.error is None:
            raise ValueError("Failed response requires an error payload")
        return {
            "id": self.id,
            "ok": False,
            "error": self.error.to_dict(),
            "timestamp": self.timestamp,
            "protocol_version": self.protocol_version,
        }


@dataclass(frozen=True, slots=True)
class ToolsetState:
    name: str
    enabled: bool
    loaded: bool
    tools: tuple[str, ...]
    description: str = ""
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "loaded": self.loaded,
            "tools": list(self.tools),
            "description": self.description,
            "aliases": list(self.aliases),
        }
