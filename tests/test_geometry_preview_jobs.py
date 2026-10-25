from __future__ import annotations

import hashlib
import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def env(addon_package, monkeypatch, tmp_path):
    source = importlib.import_module(f"{addon_package}.geometry_preview_source")
    jobs = importlib.import_module(f"{addon_package}.geometry_preview_jobs")
    tools = importlib.import_module(f"{addon_package}.tools.geometry_preview")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    registry = registry_module.ToolRegistry()
    tools.register_tools(registry)
    grants = {p.value: True for p in permissions.Permission}
    policy = permissions.PermissionManager(lambda: grants)
    checkpoints = NS()

    def context():
        return registry_module.ToolContext(state, policy, registry, checkpoints, jobs=manager)

    manager = jobs.GeometryPreviewJobs(context, registry=registry)
    native = NS(raw=b'{"frozen":1}', ids=((1, 1), (2, 2)))
    monkeypatch.setattr(source, "frozen_source", lambda _name: (native.raw, native.ids, 0.1))
    monkeypatch.setattr(
        source,
        "require_blender",
        lambda: NS(
            app=NS(
                version=(4, 5, 14),
                build_hash=b"62c1db4208e8",
                version_string="4.5.14 LTS",
                binary_path=str(tmp_path / "blender"),
            )
        ),
    )
    calls = []

    class Process:
        def __init__(self, *_args):
            calls.append("prepare")

        def fingerprint_steps(self, gate):
            gate()
            yield {"phase": "verifying_runtime"}

        def launch(self, gate):
            gate()
            calls.append("launch")

        def poll(self):
            return 0

        def result(self, gate):
            gate()
            return b"MODEL_PNG_BYTES", {
                "parent_validated_png": {"sha256": hashlib.sha256(b"MODEL_PNG_BYTES").hexdigest()}
            }

        def close(self):
            calls.append("close")
            return {"staging_cleanup": "complete", "worker_reaped": True}

    monkeypatch.setattr(jobs, "PreviewProcess", Process)
    return NS(
        source=source,
        jobs=jobs,
        tools=tools,
        registry=registry,
        context=context,
        manager=manager,
        native=native,
        grants=grants,
        state=state,
        calls=calls,
    )


def start(env, context=None):
    return env.registry.dispatch(
        "preview.geometry_start", {"object_name": "Target"}, context or env.context()
    )


def finish(env):
    for _ in range(20):
        if not env.manager.tick():
            return env.manager.history[0].summary()
    pytest.fail("Geometry model did not terminate")


def test_registered_start_uses_one_slot_and_no_native_checkpoint(env):
    result = start(env)
    assert result["accepted"] and result["framework_evidence_revision_at_admission"] == 1
    assert env.manager.active.work is None
    with pytest.raises(env.source.BridgeError):
        start(env)
    row = finish(env)
    assert row["state"] == "SUCCEEDED" and not row["undo_boundary_created"]
    assert env.calls == ["prepare", "launch", "close", "close"]
    assert env.manager.history[0].origin.raw == b""
    image = env.registry.dispatch(
        "preview.geometry_image", {"preview_id": row["result"]["preview_id"]}, env.context()
    )
    assert image["png_base64"] == "TU9ERUxfUE5HX0JZVEVT" and image["scene_changed"] is False


def test_undelivered_start_never_constructs_private_process(env):
    lifetime_module = (
        importlib.import_module(env.jobs.RequestLifetime.__module__)
        if hasattr(env.jobs, "RequestLifetime")
        else importlib.import_module(env.source.RequestLifetime.__module__)
    )
    lifetime = lifetime_module.RequestLifetime(lifetime_module.ConnectionLifetime())
    context = env.context()
    context.request_lifecycle = lifetime
    start(env, context)
    assert env.manager.tick() and env.calls == []
    lifetime.acknowledge(False)
    row = finish(env)
    assert row["state"] == "CANCELLED" and env.calls == []


@pytest.mark.parametrize(
    "fault",
    ["source", "identity", "permission", "pause", "emergency", "cancel", "disconnect", "plan"],
)
def test_stale_stopped_or_unauthorized_jobs_never_publish(env, fault):
    context = env.context()
    life = env.source.RequestLifetime.local()
    connection = importlib.import_module(env.source.RequestLifetime.__module__).ConnectionLifetime()
    life.connection = connection
    context.request_lifecycle = life
    accepted = start(env, context)
    if fault == "source":
        env.native.raw = b'{"frozen":2}'
    elif fault == "identity":
        env.native.ids = ((1, 9), (2, 2))
    elif fault == "permission":
        env.grants["CAPTURE_VIEWPORT"] = False
    elif fault == "pause":
        env.state.set_paused(True)
    elif fault == "emergency":
        env.state.set_emergency_stopped(True)
    elif fault == "cancel":
        env.manager.cancel(accepted["job_id"])
    elif fault == "disconnect":
        connection.disconnected.set()
    else:
        env.manager.active.origin.store.protection_generation += 1
    row = finish(env)
    assert row["state"] in {"CANCELLED", "FAILED"} and row["result"] is None
    assert env.manager.geometry_previews == {} and "launch" not in env.calls


def test_source_change_after_child_work_prevents_cache_publication(env):
    start(env)
    assert env.manager.tick()
    assert env.manager.tick()
    assert "launch" in env.calls
    env.native.raw = b'{"frozen":3}'
    row = finish(env)
    assert row["state"] == "FAILED" and row["result"] is None
    assert env.manager.geometry_previews == {} and "close" in env.calls


def test_reset_clears_completed_cache_and_stale_fetch_refuses(env):
    start(env)
    row = finish(env)
    handle = row["result"]["preview_id"]
    env.native.raw = b'{"frozen":4}'
    with pytest.raises(env.source.BridgeError):
        env.registry.dispatch("preview.geometry_image", {"preview_id": handle}, env.context())
    env.manager.cancel_all("project replacement")
    assert not env.manager.geometry_previews


def test_provider_mutation_of_source_is_not_adopted(env):
    old = env.context().permissions._source

    def provider():
        env.native.raw = b'{"frozen":99}'
        return old()

    env.context().permissions._source = provider
    with pytest.raises(env.source.BridgeError):
        start(env)
    assert env.calls == [] and env.manager.active is None


def test_executor_owned_finalization_never_pushes_native_undo_or_finishes_editor(
    env, addon_package
):
    executor_module = importlib.import_module(f"{addon_package}.executor")
    queue = importlib.import_module(f"{addon_package}.command_queue").CommandQueue()
    protocol = importlib.import_module(f"{addon_package}.protocol")
    checkpoints = NS(editor_session_status=lambda: None)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Geometry start reached native checkpoint/editor finalization")

    checkpoints.before_modification = checkpoints.after_modification = (
        checkpoints.finish_editor_session
    ) = forbidden
    executor = executor_module.MainThreadExecutor(
        command_queue=queue,
        registry=env.registry,
        state=env.state,
        permissions=env.context().permissions,
        checkpoints=checkpoints,
        jobs=env.manager,
    )
    env.manager.context_factory = lambda: executor.context
    response = executor.execute_request(
        protocol.Request(
            id="geometry-executor",
            method="preview.geometry_start",
            params={"object_name": "Target"},
        )
    )
    assert response.ok, response.error
    assert response.result["operation"]["undo_boundary_created"] is False
    assert response.result["operation"]["undo_boundary_finalized"] is False
    assert env.manager.active.origin.store.evidence_revision == 2
    assert (
        env.registry.executing_mutators == env.manager.active.origin.store.executing_mutators == 0
    )
    assert finish(env)["state"] == "SUCCEEDED"


def test_nested_fetch_during_exclusive_provider_is_refused_before_source_read(env):
    start(env)
    row = finish(env)
    handle = row["result"]["preview_id"]
    errors = []

    def outer(context, params):
        try:
            env.registry.dispatch("preview.geometry_image", {"preview_id": handle}, env.context())
        except env.source.BridgeError as error:
            errors.append(error.context.get("reason"))
        return {}

    env.registry.register(
        "fixture.outer", outer, modifies=True, automatic_checkpoint=False, exclusive_mutation=True
    )
    env.registry.dispatch("fixture.outer", {}, env.context())
    assert errors == ["NESTED_MUTATOR"]


def test_origin_facts_and_bound_checkpoint_token_cannot_be_rebased(env):
    start(env)
    origin = env.manager.active.origin
    for key, value in (
        ("raw", b"replacement"),
        ("digest", "0" * 64),
        ("name", "other"),
        ("semantic_origin", ()),
    ):
        with pytest.raises(env.source.BridgeError, match="changed"):
            setattr(origin, key, value)
    env.manager.cancel_all("finish model")
    assert env.calls == []


def test_failed_executor_start_handoff_never_runs_private_work(env, addon_package, monkeypatch):
    executor_module = importlib.import_module(f"{addon_package}.executor")
    queue = importlib.import_module(f"{addon_package}.command_queue").CommandQueue()
    protocol = importlib.import_module(f"{addon_package}.protocol")
    checkpoints = NS(editor_session_status=lambda: None)

    def fail_history(**_kwargs):
        raise RuntimeError("modeled history failure after handler")

    monkeypatch.setattr(env.state, "record_operation", fail_history)
    executor = executor_module.MainThreadExecutor(
        command_queue=queue,
        registry=env.registry,
        state=env.state,
        permissions=env.context().permissions,
        checkpoints=checkpoints,
        jobs=env.manager,
    )
    env.manager.context_factory = lambda: executor.context
    response = executor.execute_request(
        protocol.Request(
            id="failed-handoff", method="preview.geometry_start", params={"object_name": "Target"}
        )
    )
    assert response.ok is False and response.error["code"] == "OPERATION_FAILED"
    assert env.manager.active is None
    assert env.calls == [] and not env.manager.geometry_previews


def test_fetch_does_not_return_a_handle_invalidated_by_its_permission_provider(env):
    start(env)
    row = finish(env)
    handle = row["result"]["preview_id"]
    policy = env.context().permissions
    old = policy._source

    def provider():
        env.manager.geometry_previews.clear()
        return old()

    policy._source = provider
    with pytest.raises(env.source.BridgeError):
        env.registry.dispatch("preview.geometry_image", {"preview_id": handle}, env.context())


def test_lifetime_record_drift_still_retires_and_clears_original_background_owner(env):
    lifecycle = importlib.import_module(env.source.RequestLifetime.__module__)
    connection = lifecycle.ConnectionLifetime()
    lifetime = env.source.RequestLifetime(connection)
    lifetime.acknowledge(True)
    context = env.context()
    context.request_lifecycle = lifetime
    start(env, context)
    assert connection.background_active.is_set()
    env.manager.active.lifetime = None
    row = finish(env)
    assert row["state"] == "FAILED" and env.manager.active is None
    assert not connection.background_active.is_set() and env.calls == []
    assert env.manager.history[0].origin.raw == b""


def test_late_lifetime_clear_failure_revokes_completed_publication(env, monkeypatch):
    lifecycle = importlib.import_module(env.source.RequestLifetime.__module__)
    connection = lifecycle.ConnectionLifetime()
    lifetime = env.source.RequestLifetime(connection)
    lifetime.acknowledge(True)
    context = env.context()
    context.request_lifecycle = lifetime
    published = []

    def fail_clear():
        published.extend(env.manager.geometry_previews)
        raise RuntimeError("modeled terminal background ownership cleanup failure")

    monkeypatch.setattr(connection.background_active, "clear", fail_clear)
    start(env, context)
    row = finish(env)
    assert len(published) == 1  # Exercise cleanup after a successful worker publication.
    assert row["state"] == "FAILED" and row["result"] is None
    assert row["progress"] == {"phase": "failed"}
    assert row["error"]["context"]["reason"] == "LIFETIME_CLEANUP_UNKNOWN"
    assert row["error"]["context"]["lifetime_cleanup_unknown"] is True
    assert row["external_effects"]["lifetime_cleanup_unknown"] is True
    assert row["operation_id"] is not None  # Successful history must not restore publication.
    assert env.manager.active is None and not env.manager.geometry_previews
    assert env.manager.history[0].origin.raw == b""
    with pytest.raises(env.source.BridgeError):
        env.registry.dispatch(
            "preview.geometry_image", {"preview_id": published[0]}, env.context()
        )


def test_substituted_process_handle_is_never_used_for_cleanup(env):
    start(env)
    assert env.manager.tick()
    assert env.manager.active.process is not None
    env.manager.active.process = NS(
        close=lambda: pytest.fail("Unowned process cleanup was invoked")
    )
    row = finish(env)
    assert row["state"] == "FAILED" and "close" in env.calls
    assert env.manager.active is None and not env.manager.geometry_previews


def test_substituted_work_is_never_called_or_closed(env):
    start(env)
    assert env.manager.tick()
    env.manager.active.work = NS(close=lambda: pytest.fail("Unowned work close was invoked"))
    row = finish(env)
    assert row["state"] == "FAILED" and env.manager.active is None
    assert "launch" not in env.calls and "close" in env.calls
