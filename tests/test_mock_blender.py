from __future__ import annotations

import json
import socket
import socketserver
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from mcp_server.blender_client import SyncBlenderClient
from mcp_server.errors import (
    BridgeConnectionError,
    BridgeError,
    BridgeTimeoutError,
)

ResponseFactory = Callable[[dict[str, Any]], dict[str, Any] | bytes | None]


class _ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, factory: ResponseFactory) -> None:
        self.factory = factory
        self.requests: list[dict[str, Any]] = []
        self.requests_lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), _FakeBlenderHandler)


class _FakeBlenderHandler(socketserver.StreamRequestHandler):
    server: _ThreadedTCPServer

    def handle(self) -> None:
        for line in self.rfile:
            request = json.loads(line)
            with self.server.requests_lock:
                self.server.requests.append(request)
            response = self.server.factory(request)
            if response is None:
                continue
            if isinstance(response, bytes):
                payload = response
            else:
                response = {
                    "protocol_version": "1.0",
                    "timestamp": "2026-08-08T00:00:00Z",
                    **response,
                }
                payload = json.dumps(response).encode()
            self.wfile.write(payload + (b"" if payload.endswith(b"\n") else b"\n"))
            self.wfile.flush()


class FakeBlenderServer:
    def __init__(self, factory: ResponseFactory) -> None:
        self._server = _ThreadedTCPServer(factory)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def requests(self) -> list[dict[str, Any]]:
        with self._server.requests_lock:
            return list(self._server.requests)

    def __enter__(self) -> FakeBlenderServer:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


def test_fake_scene_response_and_request_id_round_trip() -> None:
    def respond(request: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": request["id"],
            "ok": True,
            "result": {"scene": "Test Scene", "objects": [{"name": "Cube"}]},
        }

    with FakeBlenderServer(respond) as server, SyncBlenderClient(
        port=server.port, timeout=1
    ) as client:
        result = client.request(
            "scene.inspect", {"include_hidden": False}, request_id="req_scene"
        )

        assert client.connected is True

    assert result == {"scene": "Test Scene", "objects": [{"name": "Cube"}]}
    assert server.requests[0]["id"] == "req_scene"
    assert server.requests[0]["method"] == "scene.inspect"
    assert server.requests[0]["protocol_version"] == "1.0"
    assert server.requests[0]["timeout_ms"] == 1000


def test_multiple_requests_reuse_connection_and_have_distinct_ids() -> None:
    def respond(request: dict[str, Any]) -> dict[str, Any]:
        return {"id": request["id"], "ok": True, "result": request["method"]}

    with FakeBlenderServer(respond) as server, SyncBlenderClient(
        port=server.port, timeout=1
    ) as client:
        assert client.request("bridge.status") == "bridge.status"
        assert client.request("project.info") == "project.info"

    request_ids = [request["id"] for request in server.requests]
    assert len(request_ids) == 2
    assert len(set(request_ids)) == 2
    assert all(request_id.startswith("req_") for request_id in request_ids)


def test_structured_blender_error_is_propagated() -> None:
    def deny(request: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": request["id"],
            "ok": False,
            "error": {
                "code": "PERMISSION_DENIED",
                "message": "Delete Objects is disabled.",
                "context": {
                    "required": ["DELETE_OBJECTS"],
                    "missing_permissions": ["DELETE_OBJECTS"],
                },
            },
        }

    with FakeBlenderServer(deny) as server, SyncBlenderClient(
        port=server.port, timeout=1
    ) as client, pytest.raises(BridgeError) as caught:
        client.request("object.delete", {"name": "Cube"})

    assert caught.value.code == "PERMISSION_DENIED"
    assert caught.value.context == {
        "required": ["DELETE_OBJECTS"],
        "missing_permissions": ["DELETE_OBJECTS"],
    }
    assert caught.value.request_id is not None


def test_timeout_does_not_poison_the_next_request() -> None:
    def respond(request: dict[str, Any]) -> dict[str, Any]:
        if request["method"] == "slow":
            time.sleep(0.15)
        return {"id": request["id"], "ok": True, "result": request["method"]}

    with FakeBlenderServer(respond) as server, SyncBlenderClient(
        port=server.port, timeout=1
    ) as client:
        with pytest.raises(BridgeTimeoutError) as caught:
            client.request("slow", timeout=0.03, request_id="req_slow")
        assert caught.value.retryable is False
        assert caught.value.context["outcome_unknown"] is True
        assert client.request("bridge.status", timeout=1, request_id="req_after") == "bridge.status"


def test_malformed_response_disconnects_cleanly() -> None:
    with FakeBlenderServer(lambda _: b"not-json") as server, SyncBlenderClient(
        port=server.port, timeout=1
    ) as client, pytest.raises(BridgeError) as caught:
        client.request("bridge.status")

    assert caught.value.code == "PROTOCOL_ERROR"


def _padded_response(request: dict[str, Any], size: int) -> bytes:
    template = {
        "id": request["id"],
        "ok": True,
        "result": "",
        "protocol_version": "1.0",
        "timestamp": "2026-08-08T00:00:00Z",
    }
    overhead = len(json.dumps(template, separators=(",", ":")).encode("utf-8"))
    payload = {**template, "result": "x" * (size - overhead)}
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    assert len(encoded) == size
    return encoded


def test_response_limit_applies_to_json_payload_not_newline() -> None:
    with (
        FakeBlenderServer(lambda request: _padded_response(request, 1024)) as server,
        SyncBlenderClient(
            port=server.port, timeout=1, max_message_bytes=1024
        ) as client,
    ):
        result = client.request("bridge.status")

    assert isinstance(result, str)
    assert result


def test_oversized_response_is_rejected() -> None:
    with (
        FakeBlenderServer(lambda request: _padded_response(request, 1025)) as server,
        SyncBlenderClient(
            port=server.port, timeout=1, max_message_bytes=1024
        ) as client,
        pytest.raises(BridgeError) as caught,
    ):
        client.request("bridge.status")

    assert caught.value.code == "PROTOCOL_ERROR"


def test_non_loopback_target_is_rejected_before_connect() -> None:
    for unsafe in ("192.0.2.1", "127.0.0.2", "::1"):
        with pytest.raises(ValueError, match=r"only 127\.0\.0\.1"):
            SyncBlenderClient(host=unsafe)


def test_unavailable_target_is_structured() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    unused_port = int(probe.getsockname()[1])
    probe.close()

    client = SyncBlenderClient(port=unused_port, timeout=0.2, connect_timeout=0.2)
    try:
        with pytest.raises((BridgeConnectionError, BridgeTimeoutError)) as caught:
            client.request("bridge.status")
    finally:
        client.close()

    assert caught.value.code in {"CONNECTION_ERROR", "TIMEOUT"}
    assert caught.value.retryable is True
    assert caught.value.context["executed"] is False
