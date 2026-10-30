"""Private cloth caller models; live preparation/native acceptance is separate."""
from __future__ import annotations

import importlib

import pytest


def test_runtime_service_initialization_never_accesses_filesystem(addon_package, monkeypatch):
    runtime_module = importlib.import_module(addon_package + ".runtime")
    service_module = importlib.import_module(addon_package + ".storage_snapshot_service")
    def forbidden(*_args, **_kwargs):
        pytest.fail("Runtime/service constructor accessed the filesystem")
    for name in ("open", "mkdir", "lstat", "stat", "unlink", "rmdir", "listdir"):
        monkeypatch.setattr(service_module.os, name, forbidden)
    runtime = runtime_module.BridgeRuntime()
    assert runtime.storage_snapshots.receipts(runtime) == ()


def test_runtime_retains_one_service_and_supplies_it_to_fresh_contexts(addon_package):
    runtime_module = importlib.import_module(addon_package + ".runtime")
    runtime = runtime_module.BridgeRuntime()
    service = runtime.storage_snapshots
    first, second = runtime.executor.context, runtime.executor.context
    assert first is not second
    assert first.storage_snapshots is second.storage_snapshots is service
    assert runtime.executor.storage_snapshots is runtime._storage_snapshot_origin is service
    assert service._owner is runtime and service.receipts(runtime) == ()
    assert first.jobs is runtime.jobs and first.registry is runtime.registry
    assert first.permissions is runtime.permissions and first.glb_stage is runtime.glb_stage


def test_executor_optional_service_defaults_to_none(addon_package):
    runtime_module = importlib.import_module(addon_package + ".runtime")
    executor_module = importlib.import_module(addon_package + ".executor")
    runtime = runtime_module.BridgeRuntime()
    executor = executor_module.MainThreadExecutor(command_queue=runtime.command_queue,
        registry=runtime.registry, state=runtime.state, permissions=runtime.permissions,
        checkpoints=runtime.checkpoints)
    assert executor.storage_snapshots is None and executor.context.storage_snapshots is None
    registry_module = importlib.import_module(addon_package + ".tool_registry")
    assert tuple(registry_module.ToolContext.__dataclass_fields__)[-1] == "storage_snapshots"


def test_runtime_jobs_factory_keeps_original_checked_executor_lambda(addon_package):
    runtime_module = importlib.import_module(addon_package + ".runtime")
    runtime = runtime_module.BridgeRuntime()
    factory = runtime.jobs.context_factory
    assert factory.__code__.co_names == ("checked_executor_context", "executor")
    assert factory.__code__.co_freevars == ("self",)
    assert factory.__globals__ is vars(runtime_module)
    assert factory.__closure__[0].cell_contents is runtime
