from __future__ import annotations

import asyncio
import importlib
import json
import socket
import threading
import time
from contextlib import suppress
from typing import Any

import pytest

from mcp_server.blender_client import BlenderClient, SyncBlenderClient
from mcp_server.errors import BridgeError, BridgeTimeoutError


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    return port


def _modules(addon_package: str) -> dict[str, Any]:
    return {
        name: importlib.import_module(f"{addon_package}.{name}")
        for name in ("command_queue", "errors", "protocol", "server", "state")
    }


def test_pipelined_timeout_never_executes_late_pending_mutation(
    addon_package: str,
) -> None:
    modules = _modules(addon_package)
    command_queue = modules["command_queue"].CommandQueue(maximum_size=8)
    response_type = modules["protocol"].Response
    bridge_server = modules["server"].LocalBridgeServer(
        submit=command_queue.submit,
        state=modules["state"].BridgeState(),
    )
    port = _free_port()
    bridge_server.start("127.0.0.1", port, request_timeout=0.5)
    mutations: list[str] = []

    def dispatch_serially() -> None:
        deadline = time.monotonic() + 3.0
        first = None
        while first is None and time.monotonic() < deadline:
            first = command_queue.pop_nowait()
            time.sleep(0.005)
        assert first is not None and first.request.method == "slow"
        assert first.try_start() is True
        time.sleep(0.35)
        first.resolve(response_type.success(first.request.id, {"finished": "slow"}))
        command_queue.task_done()

        second = None
        while second is None and time.monotonic() < deadline:
            second = command_queue.pop_nowait()
            time.sleep(0.005)
        assert second is not None and second.request.method == "mutate"
        if second.try_start():
            mutations.append(second.request.method)
            second.resolve(response_type.success(second.request.id, {"mutated": True}))
        command_queue.task_done()

    dispatcher = threading.Thread(target=dispatch_serially, daemon=True)
    dispatcher.start()

    async def scenario() -> list[object]:
        client = BlenderClient(port=port, timeout=0.1, connect_timeout=1.0)
        try:
            slow = asyncio.create_task(client.request("slow", timeout=0.1))
            await asyncio.sleep(0.02)
            mutate = asyncio.create_task(client.request("mutate", timeout=0.1))
            return await asyncio.gather(slow, mutate, return_exceptions=True)
        finally:
            await client.close()

    try:
        results = asyncio.run(scenario())
        dispatcher.join(timeout=3.0)
    finally:
        bridge_server.stop()

    assert all(isinstance(result, BridgeTimeoutError) for result in results)
    assert mutations == []
    assert not dispatcher.is_alive()


def test_sub_100ms_timeout_cannot_start_after_caller_deadline(
    addon_package: str,
) -> None:
    modules = _modules(addon_package)
    queued_type = modules["command_queue"].QueuedRequest
    submitted: list[Any] = []

    def submit(request: Any, *, timeout: float):
        queued = queued_type(request, deadline=time.monotonic() + timeout)
        submitted.append(queued)
        return queued

    bridge_server = modules["server"].LocalBridgeServer(
        submit=submit,
        state=modules["state"].BridgeState(),
    )
    port = _free_port()
    bridge_server.start("127.0.0.1", port, request_timeout=1.0)

    async def scenario() -> BridgeTimeoutError:
        client = BlenderClient(port=port, timeout=1.0, connect_timeout=1.0)
        try:
            with pytest.raises(BridgeTimeoutError) as caught:
                await client.request("mutate", timeout=0.02)
            await asyncio.sleep(0.03)
            return caught.value
        finally:
            await client.close()

    try:
        error = asyncio.run(scenario())
    finally:
        bridge_server.stop()

    assert submitted
    assert time.monotonic() >= submitted[0].deadline
    assert submitted[0].try_start() is False
    assert error.retryable is False


def test_caller_cancellation_drops_connection_and_cancels_pending(
    addon_package: str,
) -> None:
    modules = _modules(addon_package)
    queued_type = modules["command_queue"].QueuedRequest
    submitted: list[Any] = []

    def submit(request: Any, *, timeout: float):
        queued = queued_type(request, deadline=time.monotonic() + timeout)
        submitted.append(queued)
        return queued

    bridge_server = modules["server"].LocalBridgeServer(
        submit=submit,
        state=modules["state"].BridgeState(),
    )
    port = _free_port()
    bridge_server.start("127.0.0.1", port, request_timeout=2.0)

    async def scenario() -> bool:
        client = BlenderClient(port=port, timeout=2.0, connect_timeout=1.0)
        try:
            call = asyncio.create_task(client.request("mutate", timeout=2.0))
            deadline = time.monotonic() + 2.0
            while not submitted and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert submitted
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            return client.connected
        finally:
            await client.close()

    try:
        connected_after_cancel = asyncio.run(scenario())
    finally:
        bridge_server.stop()

    assert connected_after_cancel is False
    assert submitted[0].try_start() is False


def test_cancel_teardown_cannot_fail_a_new_connection_generation(
    addon_package: str,
) -> None:
    modules = _modules(addon_package)
    queued_type = modules["command_queue"].QueuedRequest
    response_type = modules["protocol"].Response
    submitted: list[Any] = []

    def submit(request: Any, *, timeout: float):
        queued = queued_type(request, deadline=time.monotonic() + timeout)
        submitted.append(queued)
        return queued

    bridge_server = modules["server"].LocalBridgeServer(
        submit=submit,
        state=modules["state"].BridgeState(),
    )
    port = _free_port()
    bridge_server.start("127.0.0.1", port, request_timeout=2.0)

    async def scenario() -> Any:
        client = BlenderClient(port=port, timeout=2.0, connect_timeout=1.0)
        close_entered = asyncio.Event()
        release_close = asyncio.Event()

        class GatedWriter:
            def __init__(self, wrapped: Any) -> None:
                self.wrapped = wrapped

            def is_closing(self) -> bool:
                return self.wrapped.is_closing()

            def write(self, payload: bytes) -> None:
                self.wrapped.write(payload)

            async def drain(self) -> None:
                await self.wrapped.drain()

            def close(self) -> None:
                self.wrapped.close()

            async def wait_closed(self) -> None:
                close_entered.set()
                await release_close.wait()
                await self.wrapped.wait_closed()

        try:
            abandoned = asyncio.create_task(
                client.request("abandoned_mutation", timeout=2.0)
            )
            deadline = time.monotonic() + 2.0
            while not submitted and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert submitted
            assert client._writer is not None
            client._writer = GatedWriter(client._writer)  # type: ignore[assignment]
            abandoned.cancel()
            await asyncio.wait_for(close_entered.wait(), timeout=1.0)

            replacement = asyncio.create_task(
                client.request("replacement_mutation", timeout=2.0)
            )
            await asyncio.sleep(0.05)
            release_close.set()
            with pytest.raises(asyncio.CancelledError):
                await abandoned

            deadline = time.monotonic() + 2.0
            while (
                not any(
                    queued.request.method == "replacement_mutation"
                    for queued in submitted
                )
                and time.monotonic() < deadline
            ):
                await asyncio.sleep(0.01)
            replacement_work = next(
                queued
                for queued in submitted
                if queued.request.method == "replacement_mutation"
            )
            assert replacement_work.try_start() is True
            replacement_work.resolve(
                response_type.success(
                    replacement_work.request.id,
                    {"generation": "replacement"},
                )
            )
            return await replacement
        finally:
            release_close.set()
            await client.close()

    try:
        result = asyncio.run(scenario())
    finally:
        bridge_server.stop()

    assert result == {"generation": "replacement"}
    abandoned_work = next(
        queued for queued in submitted if queued.request.method == "abandoned_mutation"
    )
    assert abandoned_work.try_start() is False


def test_oversized_result_becomes_correlated_protocol_error(addon_package: str) -> None:
    modules = _modules(addon_package)
    queued_type = modules["command_queue"].QueuedRequest
    response_type = modules["protocol"].Response

    def submit(request: Any, *, timeout: float):
        queued = queued_type(request, deadline=time.monotonic() + timeout)
        assert queued.try_start()
        queued.resolve(response_type.success(request.id, {"blob": "x" * (4 * 1024 * 1024)}))
        return queued

    bridge_server = modules["server"].LocalBridgeServer(
        submit=submit,
        state=modules["state"].BridgeState(),
    )
    port = _free_port()
    bridge_server.start("127.0.0.1", port, request_timeout=1.0)
    try:
        with SyncBlenderClient(port=port, timeout=2.0) as client, pytest.raises(
            BridgeError
        ) as caught:
            client.request("scene.inspect")
    finally:
        bridge_server.stop()

    assert caught.value.code == "MESSAGE_TOO_LARGE"
    assert caught.value.request_id is not None


def test_duplicate_active_id_is_rejected_without_second_submission(
    addon_package: str,
) -> None:
    modules = _modules(addon_package)
    queued_type = modules["command_queue"].QueuedRequest
    response_type = modules["protocol"].Response
    submitted: list[Any] = []

    def submit(request: Any, *, timeout: float):
        queued = queued_type(request, deadline=time.monotonic() + timeout)
        submitted.append(queued)
        return queued

    bridge_server = modules["server"].LocalBridgeServer(
        submit=submit,
        state=modules["state"].BridgeState(),
    )
    port = _free_port()
    bridge_server.start("127.0.0.1", port, request_timeout=1.0)
    request = {
        "id": "req_duplicate",
        "method": "bridge.status",
        "params": {},
        "protocol_version": "1.0",
        "timeout_ms": 1_000,
    }
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2.0) as connection:
            connection.sendall(
                json.dumps(request).encode("utf-8")
                + b"\n"
                + json.dumps(request).encode("utf-8")
                + b"\n"
            )
            deadline = time.monotonic() + 1.0
            while not submitted and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(submitted) == 1
            assert submitted[0].try_start()
            submitted[0].resolve(
                response_type.success("req_duplicate", {"accepted": True})
            )
            reader = connection.makefile("rb")
            responses = [json.loads(reader.readline()), json.loads(reader.readline())]
    finally:
        bridge_server.stop()

    assert responses[0]["id"] == "req_duplicate"
    assert responses[0]["ok"] is True
    assert responses[1]["id"] is None
    assert responses[1]["error"]["code"] == "INVALID_REQUEST"
    assert responses[1]["error"]["context"]["duplicate_id"] == "req_duplicate"


def test_oversized_frame_closes_without_parsing_its_tail(addon_package: str) -> None:
    modules = _modules(addon_package)
    submitted: list[Any] = []

    def submit(request: Any, *, timeout: float):
        submitted.append((request, timeout))
        raise AssertionError("oversized connection must close before submission")

    bridge_server = modules["server"].LocalBridgeServer(
        submit=submit,
        state=modules["state"].BridgeState(),
    )
    port = _free_port()
    bridge_server.start("127.0.0.1", port, request_timeout=1.0)
    valid = json.dumps(
        {
            "id": "must_not_run",
            "method": "bridge.status",
            "params": {},
            "protocol_version": "1.0",
        }
    ).encode("utf-8")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3.0) as connection:
            connection.sendall(b"x" * (4 * 1024 * 1024 + 4) + b"\n" + valid + b"\n")
            connection.shutdown(socket.SHUT_WR)
            assert connection.recv(1) == b""
    finally:
        bridge_server.stop()

    assert submitted == []


def test_stop_closes_accepted_connection_and_rejects_post_stop_frames(
    addon_package: str,
) -> None:
    modules = _modules(addon_package)
    queued_type = modules["command_queue"].QueuedRequest
    response_type = modules["protocol"].Response
    submitted: list[str] = []

    def submit(request: Any, *, timeout: float):
        submitted.append(request.method)
        queued = queued_type(request, deadline=time.monotonic() + timeout)
        assert queued.try_start()
        queued.resolve(response_type.success(request.id, {"method": request.method}))
        return queued

    bridge_server = modules["server"].LocalBridgeServer(
        submit=submit,
        state=modules["state"].BridgeState(),
    )
    port = _free_port()
    bridge_server.start("127.0.0.1", port, request_timeout=1.0)
    connection = socket.create_connection(("127.0.0.1", port), timeout=2.0)
    reader = connection.makefile("rb")
    request = {
        "id": "before_stop",
        "method": "before",
        "params": {},
        "protocol_version": "1.0",
    }
    connection.sendall(json.dumps(request).encode("utf-8") + b"\n")
    assert json.loads(reader.readline())["ok"] is True

    bridge_server.stop()
    after = {**request, "id": "after_stop", "method": "after"}
    with suppress(OSError):
        connection.sendall(json.dumps(after).encode("utf-8") + b"\n")
    with suppress(OSError):
        assert reader.readline() == b""
    connection.close()

    assert submitted == ["before"]


def test_stop_gate_is_atomic_with_queue_submission(addon_package: str) -> None:
    modules = _modules(addon_package)
    command_queue = modules["command_queue"].CommandQueue(maximum_size=4)
    entered_submit = threading.Event()
    release_submit = threading.Event()
    submitted: list[Any] = []

    def submit(request: Any, *, timeout: float):
        entered_submit.set()
        assert release_submit.wait(timeout=2.0)
        queued = command_queue.submit(request, timeout=timeout)
        submitted.append(queued)
        return queued

    bridge_server = modules["server"].LocalBridgeServer(
        submit=submit,
        state=modules["state"].BridgeState(),
    )
    port = _free_port()
    bridge_server.start("127.0.0.1", port, request_timeout=1.0)
    connection = socket.create_connection(("127.0.0.1", port), timeout=2.0)
    request = {
        "id": "racing_stop",
        "method": "mutate",
        "params": {},
        "protocol_version": "1.0",
    }
    connection.sendall(json.dumps(request).encode("utf-8") + b"\n")
    assert entered_submit.wait(timeout=2.0)

    stopper = threading.Thread(target=bridge_server.stop, daemon=True)
    stopper.start()
    time.sleep(0.05)
    assert stopper.is_alive(), "deactivate bypassed an in-progress queue insertion"
    release_submit.set()
    stopper.join(timeout=2.0)
    assert not stopper.is_alive()
    command_queue.cancel_all(
        modules["errors"].BridgeError(
            modules["errors"].ErrorCode.SERVER_ERROR,
            "runtime lifecycle reset",
            {"executed": False},
        )
    )
    connection.close()

    assert submitted
    assert submitted[0].try_start() is False
