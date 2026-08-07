from __future__ import annotations

import importlib

import pytest


def test_queue_resolves_response(addon_package: str) -> None:
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    command_queue = queue_module.CommandQueue(maximum_size=2)
    queued = command_queue.submit(
        protocol.Request("req_queue", "bridge.status"), timeout=1.0
    )

    assert command_queue.pending_count == 1
    assert command_queue.pop_nowait() is queued
    queued.resolve(protocol.Response.success("req_queue", {"connected": True}))
    command_queue.task_done()

    assert queued.wait(0.01).result == {"connected": True}


def test_queue_wait_timeout_is_structured(addon_package: str) -> None:
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    command_queue = queue_module.CommandQueue(maximum_size=1)
    queued = command_queue.submit(
        protocol.Request("req_timeout", "slow.operation"), timeout=1.0
    )

    with pytest.raises(errors.BridgeError) as caught:
        queued.wait(0.001)

    assert caught.value.code == errors.ErrorCode.TIMEOUT.value


def test_queue_cancels_all_pending_requests(addon_package: str) -> None:
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    errors = importlib.import_module(f"{addon_package}.errors")
    command_queue = queue_module.CommandQueue(maximum_size=2)
    first = command_queue.submit(
        protocol.Request("req_1", "scene.inspect"), timeout=1.0
    )
    second = command_queue.submit(
        protocol.Request("req_2", "scene.summary"), timeout=1.0
    )

    count = command_queue.cancel_all(
        errors.BridgeError(errors.ErrorCode.SERVER_ERROR, "Stopping")
    )

    assert count == 2
    assert first.wait(0.01).ok is False
    assert second.wait(0.01).error["code"] == "SERVER_ERROR"


def test_expired_request_cannot_cross_execution_boundary(addon_package: str) -> None:
    queue_module = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    queued = queue_module.QueuedRequest(
        protocol.Request("req_expired", "object.delete"), deadline=0.0
    )

    assert queued.try_start() is False
    response = queued.wait(0.01)
    assert response.ok is False
    assert response.error["code"] == "TIMEOUT"
    assert response.error["context"]["executed"] is False
