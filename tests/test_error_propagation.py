from __future__ import annotations

import json

from mcp_server.errors import (
    BridgeConnectionError,
    BridgeError,
    BridgeTimeoutError,
    ToolsetDisabledError,
)


def test_bridge_error_preserves_structured_payload() -> None:
    error = BridgeError.from_payload(
        {
            "code": "PERMISSION_DENIED",
            "message": "Permission is disabled.",
            "context": {"missing_permissions": ["DELETE_OBJECTS"]},
            "retryable": False,
        },
        request_id="req_permission",
    )

    assert error.code == "PERMISSION_DENIED"
    assert error.request_id == "req_permission"
    assert error.context["missing_permissions"] == ["DELETE_OBJECTS"]
    assert json.loads(str(error))["code"] == "PERMISSION_DENIED"


def test_transport_retryability_requires_known_pre_send_failure() -> None:
    assert BridgeConnectionError("offline").retryable is False
    assert BridgeTimeoutError("late").retryable is False
    assert BridgeConnectionError(
        "not connected",
        context={"executed": False},
        retryable=True,
    ).retryable is True


def test_disabled_toolset_error_is_actionable() -> None:
    error = ToolsetDisabledError("mesh.inspect", "mesh")

    assert error.code == "TOOLSET_DISABLED"
    assert error.context["toolset"] == "mesh"
    assert "toolsets.enable" in error.context["hint"]
