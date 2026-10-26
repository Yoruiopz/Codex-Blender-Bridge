from __future__ import annotations

import importlib.util
import json
import socket
import threading
import time
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest


@pytest.fixture
def transport():
    path = Path(__file__).parents[1] / "scripts/installed_fixture_transport.py"
    spec = importlib.util.spec_from_file_location("installed_fixture_transport_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def peer(handler):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    observations = {"errors": [], "accepted": 0, "requests": [], "thread": None}

    def run():
        observations["thread"] = threading.get_ident()
        try:
            with listener:
                connection, _address = listener.accept()
                observations["accepted"] += 1
                with connection:
                    connection.settimeout(2)
                    handler(connection, observations)
        except Exception as error:
            observations["errors"].append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        yield listener.getsockname()[1], observations
    finally:
        worker.join(timeout=3)
        listener.close()
        assert not worker.is_alive(), "Test peer did not terminate"
        assert not observations["errors"], observations["errors"]


def request(stream, observations):
    row = json.loads(stream.readline())
    observations["requests"].append(row)
    return row


def successful(row, result=None):
    return {"id": row["id"], "protocol_version": "1.0", "ok": True, "result": result}


def wait_response(client, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.poll()
        if result is not None:
            return result
        time.sleep(0.001)
    raise AssertionError("Fixture client did not return a response")


def test_two_requests_use_one_connection_and_freeze_caller_input(transport):
    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            for _ in range(2):
                row = request(stream, observations)
                connection.sendall(json.dumps(successful(row, row["params"])).encode() + b"\r\n")
            assert connection.recv(1) == b""

    with peer(handler) as (port, seen):
        client = transport.PersistentTCP(port, "native_save")
        try:
            params = {"nested": [1, 2]}
            submitted = client.submit("bridge.status", params)
            params["nested"].append(3)
            submitted["params"]["nested"].append(4)
            first = wait_response(client)
            assert first["request"]["params"] == first["response"]["result"] == {"nested": [1, 2]}
            assert first["request"]["id"] == "native_save-1"
            client.submit("jobs.inspect", {"job_id": "owned"})
            second = wait_response(client)
            assert second["request"]["id"] == "native_save-2"
            assert client.connected and client.worker_ident != threading.get_ident()
        finally:
            client.close()
        assert client.closed
    assert seen["accepted"] == 1 and len(seen["requests"]) == 2


def test_delayed_response_does_not_block_caller_and_pending_request_cannot_be_replaced(transport):
    received, release = threading.Event(), threading.Event()

    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            row = request(stream, observations)
            received.set()
            assert release.wait(2)
            connection.sendall(json.dumps(successful(row, "done")).encode() + b"\n")

    with peer(handler) as (port, _seen):
        client = transport.PersistentTCP(port, "weights")
        try:
            client.submit("weights.assign", {"weight": 0.5})
            assert received.wait(2)
            started = time.monotonic()
            assert client.poll() is None
            assert time.monotonic() - started < 0.05
            with pytest.raises(RuntimeError, match="one fixture request"):
                client.submit("jobs.inspect", {})
            release.set()
            assert wait_response(client)["response"]["result"] == "done"
        finally:
            release.set()
            client.close()


@pytest.mark.parametrize("reply", [
    b"not json\n", b"\xff\n", b"[]\n",
    b'{"id":"curve-1","protocol_version":"1.0","ok":true,"result":NaN}\n',
    b'{"id":"curve-1","id":"curve-1","protocol_version":"1.0","ok":true,"result":null}\n',
    b'{"id":"other","protocol_version":"1.0","ok":true,"result":null}\n',
    b'{"id":"curve-1","protocol_version":"2.0","ok":true,"result":null}\n',
    b'{"id":"curve-1","protocol_version":"1.0","ok":1,"result":null}\n',
    b'{"id":"curve-1","protocol_version":"1.0","ok":true}\n',
    b'{"id":"curve-1","protocol_version":"1.0","ok":true,"result":null,"error":{}}\n',
    b'{"id":"curve-1","protocol_version":"1.0","ok":false,"result":null,"error":{}}\n',
    b'{"id":"curve-1","protocol_version":"1.0","ok":false,"error":null}\n',
])
def test_invalid_terminal_response_fails_without_retry(transport, reply):
    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            request(stream, observations)
            connection.sendall(reply)
            assert connection.recv(1) == b""

    with peer(handler) as (port, seen):
        client = transport.PersistentTCP(port, "curve")
        try:
            client.submit("animation.curve_edit", {})
            with pytest.raises(transport.FixtureTransportError):
                wait_response(client)
            with pytest.raises(transport.FixtureTransportError):
                client.submit("bridge.status", {})
        finally:
            client.close()
    assert len(seen["requests"]) == 1


def test_fragmented_response_and_structured_failure_are_valid(transport):
    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            row = request(stream, observations)
            payload = json.dumps({"id": row["id"], "protocol_version": "1.0", "ok": False,
                                  "error": {"code": "PERMISSION_DENIED"}}).encode() + b"\n"
            for part in (payload[:1], payload[1:13], payload[13:]):
                connection.sendall(part)

    with peer(handler) as (port, _seen):
        client = transport.PersistentTCP(port, "native_save")
        try:
            client.submit("project.native_save_preview", {})
            assert wait_response(client)["response"]["error"]["code"] == "PERMISSION_DENIED"
        finally:
            client.close()


@pytest.mark.parametrize("newline", [b"", b"\n"])
def test_oversized_frame_is_bounded_and_terminal(transport, newline):
    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            request(stream, observations)
            with suppress(BrokenPipeError, ConnectionResetError):
                connection.sendall(b"x" * (transport.MAX_FRAME_BYTES + 2) + newline)

    with peer(handler) as (port, _seen):
        client = transport.PersistentTCP(port, "curve")
        try:
            client.submit("bridge.status", {})
            with pytest.raises(transport.FixtureTransportError, match="4 MiB"):
                wait_response(client)
        finally:
            client.close()


def test_disconnect_before_response_is_not_a_success(transport):
    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            request(stream, observations)

    with peer(handler) as (port, _seen):
        client = transport.PersistentTCP(port, "native_save")
        try:
            client.submit("jobs.inspect", {})
            with pytest.raises(transport.FixtureTransportError, match="disconnected"):
                wait_response(client)
        finally:
            client.close()


def test_exact_payload_limit_excludes_crlf_delimiter(transport):
    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            request(stream, observations)
            prefix = b'{"id":"curve-1","protocol_version":"1.0","ok":true,"result":"'
            suffix = b'"}'
            length = transport.MAX_FRAME_BYTES - len(prefix) - len(suffix)
            connection.sendall(prefix + b"x" * length + suffix + b"\r\n")

    with peer(handler) as (port, _seen):
        client = transport.PersistentTCP(port, "curve")
        try:
            client.submit("bridge.status", {})
            receipt = wait_response(client)
            assert len(receipt["response"]["result"]) > transport.MAX_FRAME_BYTES - 100
        finally:
            client.close()


def test_invalid_request_leaves_connection_and_sequence_available(transport):
    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            row = request(stream, observations)
            connection.sendall(json.dumps(successful(row)).encode() + b"\n")

    with peer(handler) as (port, seen):
        client = transport.PersistentTCP(port, "curve")
        try:
            for method, params in (("not dotted", {}), ("bridge.status", []),
                                   ("bridge.status", {"bad": float("nan")}),
                                   ("bridge.status", {"oversize": "x" * transport.MAX_FRAME_BYTES})):
                with pytest.raises(ValueError):
                    client.submit(method, params)
            row = client.submit("bridge.status", {})
            assert row["id"] == "curve-1"
            assert wait_response(client)["response"]["ok"]
        finally:
            client.close()
    assert len(seen["requests"]) == 1


def test_foreign_thread_cannot_submit_or_poll(transport):
    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            row = request(stream, observations)
            connection.sendall(json.dumps(successful(row)).encode() + b"\n")

    with peer(handler) as (port, _seen):
        client = transport.PersistentTCP(port, "curve")
        failures = []

        def foreign():
            for operation in (lambda: client.submit("bridge.status", {}), client.poll):
                try:
                    operation()
                except RuntimeError as error:
                    failures.append(str(error))

        try:
            other = threading.Thread(target=foreign)
            other.start()
            other.join(timeout=1)
            assert not other.is_alive() and len(failures) == 2
            assert all("creating fixture thread" in failure for failure in failures)
            client.submit("bridge.status", {})
            assert wait_response(client)["response"]["ok"]
        finally:
            client.close()


def test_deadline_preserves_one_send_and_closes_connection(transport):
    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            request(stream, observations)
            assert connection.recv(1) == b""

    with peer(handler) as (port, seen):
        client = transport.PersistentTCP(port, "native_save", request_timeout=0.1)
        try:
            client.submit("project.native_save_start", {})
            with pytest.raises(transport.FixtureTransportError, match="deadline"):
                wait_response(client)
        finally:
            client.close()
    assert len(seen["requests"]) == 1


def test_close_returns_promptly_when_peer_has_not_responded(transport):
    received = threading.Event()

    def handler(connection, observations):
        with connection.makefile("rb") as stream:
            request(stream, observations)
            received.set()
            assert connection.recv(1) == b""

    with peer(handler) as (port, _seen):
        client = transport.PersistentTCP(port, "native_save")
        client.submit("jobs.inspect", {})
        assert received.wait(2)
        started = time.monotonic()
        client.close()
        assert time.monotonic() - started < 0.3
        assert client.closed
        with pytest.raises(transport.FixtureTransportError, match="closed"):
            client.submit("bridge.status", {})


@pytest.mark.parametrize("port,phase,timeout", [
    (True, "curve", 1), (0, "curve", 1), (65536, "curve", 1),
    (1, "", 1), (1, "bad phase", 1), (1, "x" * 49, 1),
    (1, "curve", True), (1, "curve", float("nan")), (1, "curve", float("inf")),
    (1, "curve", 0), (1, "curve", 301),
])
def test_invalid_configuration_is_rejected_before_network(transport, port, phase, timeout):
    with pytest.raises(ValueError):
        transport.PersistentTCP(port, phase, timeout)
