from __future__ import annotations

import importlib
import json
import socket
import time
from types import SimpleNamespace as NS

import pytest


def test_wire_cannot_forge_trusted_job_owner_or_delivery(addon_package):
    protocol = importlib.import_module(f"{addon_package}.protocol")
    value = {"id": "req", "method": "jobs.list", "params": {}, "protocol_version": "1.0",
             "_lifecycle": {"delivered": True, "connection": None}}
    assert protocol.decode_request(json.dumps(value).encode())._lifecycle is None


@pytest.mark.parametrize("oversized", [False, True])
def test_start_lease_tracks_actual_flush_and_survives_retired_request_until_owner_disconnect(addon_package, oversized):
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    server_module = importlib.import_module(f"{addon_package}.server")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    work_queue = queue_module.CommandQueue()
    server = server_module.LocalBridgeServer(submit=work_queue.submit, state=state)
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server.start("127.0.0.1", port)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.sendall(b'{"id":"start","method":"fixture.start","params":{},"protocol_version":"1.0"}\n')
            deadline = time.monotonic() + 2
            queued = None
            while queued is None and time.monotonic() < deadline:
                queued = work_queue.pop_nowait()
                time.sleep(.001)
            assert queued is not None and queued.try_start()
            lease = queued.request._lifecycle
            assert lease is not None and not lease.delivered.is_set()
            assert not lease.connection.disconnected.is_set()
            queued.resolve(protocol.Response.success("start", "x" * (5 * 1024 * 1024) if oversized else {"accepted": True}))
            work_queue.task_done()
            with connection.makefile("rb") as stream:
                response = json.loads(stream.readline())
            assert response["id"] == "start" and response["ok"] is not oversized
            assert (lease.rejected if oversized else lease.delivered).wait(1)
            assert lease.delivered.is_set() is not oversized
        assert lease.connection.disconnected.wait(2)
    finally:
        server.stop()


def test_writer_failure_rejects_delivery_and_owner_before_retiring_request(addon_package):
    server_module = importlib.import_module(f"{addon_package}.server")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    import queue
    import threading
    lease = lifecycle.RequestLifetime(lifecycle.ConnectionLifetime())
    work = queue_module.QueuedRequest(protocol.Request("start", "fixture.start", _lifecycle=lease), deadline=time.monotonic()+1)
    assert work.try_start()
    work.resolve(protocol.Response.success("start", {"accepted": True}))
    handler = object.__new__(server_module._RequestHandler)
    handler._outbound, handler._lifetime = queue.Queue(), lease.connection
    handler._inflight, handler._active_ids, handler._inflight_lock = [work], {"start"}, threading.Lock()
    def failed_write(_value):
        raise BrokenPipeError("injected")
    handler.wfile = NS(write=failed_write)
    handler.request = NS(shutdown=lambda _how: None)
    handler.server = NS(running_grace=1)
    handler._outbound.put(work)
    handler._write_responses()
    assert lease.rejected.is_set() and not lease.delivered.is_set() and lease.connection.disconnected.is_set()
    assert not handler._inflight and not handler._active_ids


def test_active_job_connection_survives_repeated_idle_timeouts_and_partial_frame(addon_package):
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    server_module = importlib.import_module(f"{addon_package}.server")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    leases = []
    def submit(request, *, timeout):
        leases.append(request._lifecycle)
        request._lifecycle.connection.background_active.set()
        work = queue_module.QueuedRequest(request, deadline=time.monotonic()+timeout)
        assert work.try_start()
        work.resolve(protocol.Response.success(request.id, {"received": True}))
        return work
    server = server_module._LocalTCPServer(("127.0.0.1", 0), submit=submit, state=state, request_timeout=1)
    server.socket_read_timeout = .02
    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=2) as connection:
            first = b'{"id":"a","method":"fixture.start","params":{},"protocol_version":"1.0"}\n'
            connection.sendall(first)
            with connection.makefile("rb") as reader:
                assert json.loads(reader.readline())["id"] == "a"
                assert leases[0].delivered.wait(1)
                connection.sendall(first.replace(b'"a"', b'"b"')[:15])
                time.sleep(.09)  # Multiple actual socket timeouts with partial bytes.
                assert not leases[0].connection.disconnected.is_set()
                connection.sendall(first.replace(b'"a"', b'"b"')[15:])
                assert json.loads(reader.readline())["id"] == "b"
                leases[0].connection.background_active.clear()
                assert leases[0].connection.disconnected.wait(2)
    finally:
        server.deactivate()
        server.shutdown()
        server.server_close()
        thread.join(2)
