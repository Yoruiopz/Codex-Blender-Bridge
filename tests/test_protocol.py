from __future__ import annotations

import math

import pytest

from mcp_server.errors import BridgeProtocolError
from mcp_server.schemas import (
    PROTOCOL_VERSION,
    BridgeRequest,
    BridgeResponse,
    ErrorPayload,
    validate_json_value,
)


def test_request_round_trip_preserves_id_method_and_params() -> None:
    request = BridgeRequest.create(
        request_id="req_test_001",
        method="scene.inspect",
        params={"include_hidden": False, "max_objects": 25},
        timeout_ms=12_500,
    )

    decoded = BridgeRequest.from_mapping(request.to_dict())

    assert decoded.id == "req_test_001"
    assert decoded.method == "scene.inspect"
    assert decoded.params == {"include_hidden": False, "max_objects": 25}
    assert decoded.protocol_version == PROTOCOL_VERSION
    assert decoded.timestamp is not None
    assert decoded.timeout_ms == 12_500


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"id": "req", "method": "scene.inspect", "protocol_version": PROTOCOL_VERSION, "params": []},
        {"id": "req", "method": "", "protocol_version": PROTOCOL_VERSION, "params": {}},
        {"id": "req", "method": "scene.inspect", "protocol_version": "99", "params": {}},
        {
            "id": "req",
            "method": "scene.inspect",
            "protocol_version": PROTOCOL_VERSION,
            "params": {},
            "timeout_ms": 0,
        },
    ],
)
def test_malformed_requests_are_rejected(message: dict[str, object]) -> None:
    with pytest.raises(BridgeProtocolError):
        BridgeRequest.from_mapping(message)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_json_numbers_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="NaN or infinity"):
        validate_json_value({"value": value})


def test_success_response_round_trip() -> None:
    response = BridgeResponse.from_mapping(
        {
            "id": "req_ok",
            "ok": True,
            "result": {"scene": "Scene", "objects": []},
            "timestamp": "2026-08-08T00:00:00Z",
            "protocol_version": "1.0",
        }
    )

    assert response.ok is True
    assert response.result == {"scene": "Scene", "objects": []}
    assert response.to_dict()["id"] == "req_ok"


def test_error_response_round_trip() -> None:
    payload = ErrorPayload(
        code="OBJECT_NOT_FOUND",
        message="Object 'Missing' does not exist.",
        context={"available_similar_objects": ["Mesh"]},
    )
    response = BridgeResponse(id="req_error", ok=False, error=payload)

    decoded = BridgeResponse.from_mapping(response.to_dict())

    assert decoded.ok is False
    assert decoded.error is not None
    assert decoded.error.code == "OBJECT_NOT_FOUND"
    assert decoded.error.context["available_similar_objects"] == ["Mesh"]


def test_success_response_cannot_also_contain_error() -> None:
    with pytest.raises(BridgeProtocolError):
        BridgeResponse.from_mapping(
            {
                "id": "req_both",
                "ok": True,
                "result": {},
                "error": {"code": "NOPE", "message": "invalid"},
                "timestamp": "2026-08-08T00:00:00Z",
                "protocol_version": "1.0",
            }
        )


@pytest.mark.parametrize("version", [None, "2.0"])
def test_response_requires_supported_protocol_version(version: object) -> None:
    with pytest.raises(BridgeProtocolError):
        BridgeResponse.from_mapping(
            {
                "id": "req_version",
                "ok": True,
                "result": {},
                "timestamp": "2026-08-08T00:00:00Z",
                "protocol_version": version,
            }
        )
