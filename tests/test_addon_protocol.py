from __future__ import annotations

import importlib
import json

import pytest


def test_addon_decodes_mcp_request_envelope(addon_package: str) -> None:
    protocol = importlib.import_module(f"{addon_package}.protocol")
    payload = {
        "id": "req_addon",
        "method": "scene.inspect",
        "params": {"include_hidden": False},
        "timestamp": "2026-08-07T12:00:00Z",
        "protocol_version": "1.0",
        "timeout_ms": 30_000,
    }

    request = protocol.decode_request(json.dumps(payload).encode())

    assert request.id == "req_addon"
    assert request.method == "scene.inspect"
    assert request.params == {"include_hidden": False}
    assert request.timeout_ms == 30_000


def test_addon_rejects_malformed_json(addon_package: str) -> None:
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")

    with pytest.raises(errors.BridgeError) as caught:
        protocol.decode_request(b"{not-json")

    assert caught.value.code == errors.ErrorCode.MALFORMED_JSON.value


@pytest.mark.parametrize(
    "change",
    [
        {"id": 42},
        {"params": None},
        {"remove_params": True},
    ],
)
def test_addon_requires_string_id_and_object_params(
    addon_package: str, change: dict[str, object]
) -> None:
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    payload: dict[str, object] = {
        "id": "req",
        "method": "bridge.status",
        "params": {},
        "protocol_version": "1.0",
    }
    if change.pop("remove_params", False):
        payload.pop("params")
    else:
        payload.update(change)

    with pytest.raises(errors.BridgeError) as caught:
        protocol.Request.from_mapping(payload)

    assert caught.value.code == errors.ErrorCode.INVALID_REQUEST.value


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_addon_rejects_non_finite_json_numbers(
    addon_package: str, constant: str
) -> None:
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    payload = (
        '{"id":"req","method":"transform.set","params":{"scale":['
        + constant
        + ',1,1]},"protocol_version":"1.0"}'
    )

    with pytest.raises(errors.BridgeError) as caught:
        protocol.decode_request(payload)

    assert caught.value.code == errors.ErrorCode.MALFORMED_JSON.value


def test_addon_rejects_json_exponent_overflow(addon_package: str) -> None:
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")

    with pytest.raises(errors.BridgeError) as caught:
        protocol.decode_request(
            b'{"id":"req_overflow","method":"transform.scale","params":{"factor":1e309},"protocol_version":"1.0"}'
        )

    assert caught.value.code == errors.ErrorCode.MALFORMED_JSON.value


def test_addon_rejects_oversized_message(addon_package: str) -> None:
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")

    with pytest.raises(errors.BridgeError) as caught:
        protocol.decode_request(b"{}", max_bytes=1)

    assert caught.value.code == errors.ErrorCode.MESSAGE_TOO_LARGE.value


def test_addon_rejects_unbounded_envelope_strings(addon_package: str) -> None:
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    base = {
        "id": "req",
        "method": "scene.inspect",
        "params": {},
        "protocol_version": "1.0",
    }

    for field, value in (
        ("id", "x" * 257),
        ("method", "x" * 129),
        ("timestamp", "x" * 129),
    ):
        with pytest.raises(errors.BridgeError) as caught:
            protocol.Request.from_mapping({**base, field: value})
        assert caught.value.code == errors.ErrorCode.INVALID_REQUEST.value


def test_addon_rejects_oversized_response(addon_package: str) -> None:
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    response = protocol.Response.success("req_large", {"blob": "x" * 100})

    with pytest.raises(errors.BridgeError) as caught:
        protocol.encode_response(response, max_bytes=32)

    assert caught.value.code == errors.ErrorCode.MESSAGE_TOO_LARGE.value


def test_addon_error_response_is_structured(addon_package: str) -> None:
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    response = protocol.Response.failure(
        "req_denied",
        errors.BridgeError(
            errors.ErrorCode.PERMISSION_DENIED,
            "Permission denied.",
            {
                "required": ["DELETE_OBJECTS"],
                "missing_permissions": ["DELETE_OBJECTS"],
            },
        ),
    )

    decoded = json.loads(protocol.encode_response(response))

    assert decoded["id"] == "req_denied"
    assert decoded["ok"] is False
    assert decoded["error"]["code"] == "PERMISSION_DENIED"
    assert decoded["protocol_version"] == "1.0"
