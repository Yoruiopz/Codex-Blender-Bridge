"""Actual registry leases and native-save job ownership with modeled native IO."""
from __future__ import annotations

import importlib
import sys
import time
from dataclasses import replace
from types import FunctionType, MethodType
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def save_env(addon_package, monkeypatch, tmp_path):
    source = importlib.import_module(f"{addon_package}.native_save_source")
    module = importlib.import_module(f"{addon_package}.native_save_jobs")
    tools = importlib.import_module(f"{addon_package}.tools.native_save")
    registry_type = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    grant_type = importlib.import_module(f"{addon_package}.native_save_policy").NativeSaveGrant
    projection = importlib.import_module(f"{addon_package}.native_save_profile").Projection
    authority = object()
    grant = grant_type("modeled-session", authority)
    grant.arm(authority, 900)
    registry = registry_type.ToolRegistry()
    tools.register_tools(registry)
    values = {permission.value: True for permission in permissions.Permission}
    policy = permissions.PermissionManager(lambda: values)
    checkpoints = NS()
    native = NS(raw=b'{"schema":"stock_native_project_v1"}', identities=(("objects", "AnyName", 1, 1),),
                driven_raw=(), filepath="", calls=[], reader_gate=None, native_hook=None, reader_reaped=True)

    def context():
        return registry_type.ToolContext(state, policy, registry, checkpoints, jobs=manager)

    manager = module.NativeSaveJobs(context, registry=registry, native_save_policy=grant)
    runtime_module = importlib.import_module(f"{addon_package}.runtime")
    runtime = runtime_module.BridgeRuntime.__new__(runtime_module.BridgeRuntime)
    runtime.registry, runtime.state, runtime._registered = registry, state, True
    monkeypatch.setattr(runtime_module, "_RUNTIME", runtime)
    monkeypatch.setattr(source, "qualify_provider", lambda _context: None)  # Pure model; separate canonical-runtime poison tests exist.
    monkeypatch.setattr(source, "snapshot", lambda _resource_directory=None: projection(native.raw, native.identities, native.driven_raw))
    monkeypatch.setattr(source, "options", lambda: (str(tmp_path), 0, "NONE", False))

    class Data:
        @property
        def filepath(self):
            return native.filepath

    def save_as(filepath, copy, **_kwargs):
        from pathlib import Path
        native.calls.append("native")
        assert registry.active_exclusive_mutation
        if native.native_hook:
            native.native_hook()
        Path(filepath).write_bytes(b"MODEL_BLENDER_NATIVE_FILE")
        if not copy:
            native.filepath = filepath
        return {"FINISHED"}

    bpy = NS(data=Data(), app=NS(version=(4, 5, 14), build_hash=b"62c1db4208e8",
                               version_string="4.5.14 LTS", binary_path="/modeled/blender"),
             ops=NS(wm=NS(save_as_mainfile=save_as, save_mainfile=lambda: save_as(native.filepath, False))))
    monkeypatch.setattr(source, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)

    class Reader:
        def __init__(self, *_args):
            native.calls.append("reader_prepare")

        def fingerprint_steps(self, gate):
            gate()
            yield {"phase": "verifying_reader"}

        def launch(self, gate):
            gate()
            native.calls.append("reader_launch")

        def poll(self):
            return 0

        def result(self, gate):
            if native.reader_gate:
                native.reader_gate()
            gate()
            return {"declared_projection_reopened": True}

        def close(self, **_kwargs):
            native.calls.append("reader_close")
            return self.evidence()

        def evidence(self):
            return {"worker_reaped": native.reader_reaped, "staging_cleanup": "complete"}

    monkeypatch.setattr(module, "SaveReaderProcess", Reader)
    return NS(source=source, jobs=module, tools=tools, registry=registry, state=state, context=context,
              manager=manager, native=native, values=values, grant=grant, authority=authority,
              folder=tmp_path)


def preview(env, mode="COPY_NEW", filename="new project.blend", context=None):
    policy = "NO_CLOBBER" if mode == "COPY_NEW" else "NATIVE_NEW_EXPECTED"
    return env.registry.dispatch("project.native_save_preview", {"mode": mode,
        "filepath": str(env.folder / filename), "overwrite_policy": policy}, context or env.context())


def start(env, value, context=None):
    return env.registry.dispatch("project.native_save_start", {
        "mode": value["mode"], "filepath": value["filepath"], "overwrite_policy": value["overwrite_policy"],
        "preview_id": value["preview_id"], "expected_fingerprint": value["fingerprint"],
        "accepted_losses": value["required_accepted_losses"]}, context or env.context())


def finish(env):
    for _ in range(100):
        if not env.manager.tick():
            return env.manager.history[0].summary()
    pytest.fail("Modeled save failed to terminate")


@pytest.fixture
def queued_save(save_env):
    """Real queue/request/executor hooks; only the existing native IO model is used."""
    env = save_env
    package = env.source.__package__
    executor_module = importlib.import_module(package + ".executor")
    queue_module = importlib.import_module(package + ".command_queue")
    protocol = importlib.import_module(package + ".protocol")
    lifecycle = importlib.import_module(package + ".request_lifecycle")
    base = env.context()
    executor = executor_module.MainThreadExecutor(command_queue=queue_module.CommandQueue(),
        registry=env.registry, state=env.state, permissions=base.permissions,
        checkpoints=base.checkpoints, jobs=env.manager)
    return NS(env=env, executor=executor, queue=queue_module, protocol=protocol, lifecycle=lifecycle,
              connection=lifecycle.ConnectionLifetime(), sequence=0)


def queued_request(case, method, params, *, timeout=30.):
    case.sequence += 1
    lifetime = case.lifecycle.RequestLifetime(case.connection, time.monotonic() + timeout)
    request = case.protocol.Request(id="real-queue-" + str(case.sequence), method=method,
                                    params=params, _lifecycle=lifetime)
    queued = case.executor.submit(request, timeout=timeout)
    assert case.executor.command_queue.pop_nowait() is queued
    assert queued.try_start()
    return queued


def execute_queued(case, queued, *, acknowledge=True):
    response = case.executor.execute_request(queued.request, check_cancelled=queued.check_active)
    queued.resolve(response)
    case.executor.command_queue.task_done()
    if acknowledge:
        queued.request._lifecycle.acknowledge(response.ok)
    return response


def queued_preview(case):
    env = case.env
    queued = queued_request(case, "project.native_save_preview", {"mode": "COPY_NEW",
        "filepath": str(env.folder / "real queued project.blend"), "overwrite_policy": "NO_CLOBBER"})
    response = execute_queued(case, queued)
    assert response.ok, response.error
    return queued, response.result


def queued_start(case, value, *, acknowledge=True, request_timeout=30., job_limit=None):
    params = {"mode": value["mode"],
        "filepath": value["filepath"], "overwrite_policy": value["overwrite_policy"],
        "preview_id": value["preview_id"], "expected_fingerprint": value["fingerprint"],
        "accepted_losses": value["required_accepted_losses"]}
    if job_limit is not None:
        params["time_limit_seconds"] = job_limit
    queued = queued_request(case, "project.native_save_start", params, timeout=request_timeout)
    return queued, execute_queued(case, queued, acknowledge=acknowledge)


def test_native_save_start_reuses_preview_resource_ancestry_without_rebinding(queued_save):
    case, env = queued_save, queued_save.env
    _preview_request, value = queued_preview(case)
    previous = env.manager.native_save_previews[value["preview_id"]].origin
    expected = previous.resource_directory
    _request, response = queued_start(case, value)
    assert response.ok, response.error
    job = env.manager.active
    assert job.origin.resource_directory is expected
    assert job.origin.resource_directory.ancestry == previous.resource_directory.ancestry
    assert finish(env)["state"] == "SUCCEEDED"


def test_resource_directory_refusal_is_structured_before_snapshot_or_native_calls(save_env, monkeypatch):
    env = save_env

    def refuse(_path):
        raise env.source.ProfileRefused("RESOURCE_DIRECTORY_UNAVAILABLE")
    monkeypatch.setattr(env.source, "bind_resource_directory", refuse)
    monkeypatch.setattr(env.source, "snapshot", lambda *_a: pytest.fail("Snapshot after directory refusal"))
    with pytest.raises(env.source.BridgeError) as failure:
        preview(env)
    assert failure.value.code == "NOT_IMPLEMENTED"
    assert failure.value.context["reason"] == "RESOURCE_DIRECTORY_UNAVAILABLE"
    assert not env.native.calls and not list(env.folder.iterdir())


def captured_queued_hooks(case):
    contexts = []
    case.env.registry.register("fixture.capture_queue_hooks",
        lambda context, _params: (contexts.append(context) or {"captured": True}))
    queued = queued_request(case, "fixture.capture_queue_hooks", {})
    response = execute_queued(case, queued)
    assert response.ok and len(contexts) == 1
    return queued, contexts[0]


def test_real_queued_preview_a_start_b_same_connection_and_worker_context_succeed(queued_save):
    case, env = queued_save, queued_save.env
    request_a, value = queued_preview(case)
    preview_origin = env.manager.native_save_previews[value["preview_id"]].origin
    request_b, response = queued_start(case, value)
    assert response.ok, response.error
    job = env.manager.active
    assert request_a is not request_b and request_a.request.id != request_b.request.id
    assert preview_origin.context.check_cancelled.__self__ is request_a
    assert job.origin.context.check_cancelled.__self__ is request_b
    assert preview_origin.context.check_final_request is not job.origin.context.check_final_request
    assert preview_origin.lifetime is not job.origin.lifetime
    assert preview_origin.lifetime.connection is job.origin.lifetime.connection is case.connection
    assert job.origin.fingerprint(env.manager._record(job).preview.plan) == value["fingerprint"]
    assert not env.native.calls
    worker = env.manager._context(job)
    assert worker.check_final_request is None and worker.check_cancelled is not job.origin.context.check_cancelled
    assert env.manager.context_valid(worker, job.origin)
    row = finish(env)
    assert row["state"] == "SUCCEEDED", row
    assert (env.folder / "real queued project.blend").read_bytes() == b"MODEL_BLENDER_NATIVE_FILE"


def test_acknowledged_preview_a_expired_old_queue_deadline_does_not_stale_start_b(queued_save):
    case = queued_save
    request_a, value = queued_preview(case)
    request_a.deadline = time.monotonic() - 1.
    assert request_a.request._lifecycle.delivered.is_set()
    request_a.request._lifecycle.check()
    _request_b, response = queued_start(case, value)
    assert response.ok, response.error
    assert finish(case.env)["state"] == "SUCCEEDED"


def test_delivered_start_request_deadline_does_not_replace_background_job_deadline(queued_save):
    case = queued_save
    _request_a, value = queued_preview(case)
    request_b, response = queued_start(case, value, request_timeout=1.)
    assert response.ok, response.error
    time.sleep(1.05)
    with pytest.raises(case.env.source.BridgeError) as expired:
        request_b.check_active()
    assert expired.value.code == "TIMEOUT"
    request_b.request._lifecycle.check()  # Delivered start now uses connection/job authority.
    assert finish(case.env)["state"] == "SUCCEEDED"


@pytest.mark.parametrize("control", ["cancelled", "queue_expired", "lifetime_expired"])
def test_current_queued_request_cancellation_or_expiry_refuses_before_source_or_files(queued_save, monkeypatch, control):
    case, env = queued_save, queued_save.env
    queued = queued_request(case, "project.native_save_preview", {"mode": "COPY_NEW",
        "filepath": str(env.folder / "denied.blend"), "overwrite_policy": "NO_CLOBBER"})
    reads = []
    monkeypatch.setattr(env.source, "snapshot", lambda _resource_directory=None: reads.append("source"))
    monkeypatch.setattr(env.source, "options", lambda: reads.append("options"))
    if control == "cancelled":
        assert queued.cancel_pending(env.source.BridgeError("TIMEOUT", "Owner cancelled")) is False
    elif control == "queue_expired":
        queued.deadline = time.monotonic() - 1.
    else:
        queued.request._lifecycle.deadline = time.monotonic() - 1.
    response = execute_queued(case, queued)
    assert not response.ok and response.error["code"] == "TIMEOUT"
    assert reads == [] and env.native.calls == [] and not list(env.folder.iterdir())


@pytest.mark.parametrize("control", ["disconnect", "rejected_delivery"])
def test_queued_handoff_owner_loss_stops_worker_before_native_or_file_actions(queued_save, control):
    case, env = queued_save, queued_save.env
    _request_a, value = queued_preview(case)
    request_b, response = queued_start(case, value, acknowledge=False)
    assert response.ok, response.error
    assert env.manager.tick() and not env.native.calls  # No acknowledged start, no work.
    if control == "disconnect":
        request_b.request._lifecycle.acknowledge(True)
        case.connection.disconnected.set()
    else:
        request_b.request._lifecycle.acknowledge(False)
    row = finish(env)
    assert row["state"] == "CANCELLED", row
    assert not env.native.calls and not list(env.folder.iterdir())


def test_queued_native_job_keeps_its_own_deadline_after_delivery(queued_save):
    case, env = queued_save, queued_save.env
    _request_a, value = queued_preview(case)
    _request_b, response = queued_start(case, value, job_limit=1)
    assert response.ok, response.error
    time.sleep(1.05)
    row = finish(env)
    assert row["state"] == "CANCELLED" and row["error"]["code"] == "TIMEOUT"
    assert not env.native.calls and not list(env.folder.iterdir())


def test_queued_native_save_reaches_unsupported_context_without_touching_source(queued_save, monkeypatch):
    case, env = queued_save, queued_save.env
    reads = []

    def unsupported(_resource_directory=None):
        reads.append("declared context profile")
        raise env.source.BridgeError("NOT_IMPLEMENTED", "Modeled unsupported Edit Mode")

    monkeypatch.setattr(env.source, "snapshot", unsupported)
    queued = queued_request(case, "project.native_save_preview", {"mode": "COPY_NEW",
        "filepath": str(env.folder / "unsupported.blend"), "overwrite_policy": "NO_CLOBBER"})
    response = execute_queued(case, queued)
    assert not response.ok and response.error["code"] == "NOT_IMPLEMENTED"
    assert reads == ["declared context profile"] and not env.native.calls and not list(env.folder.iterdir())


@pytest.mark.parametrize("change", ["foreign_method", "fake_owner", "subclass_owner", "wrong_final_code",
                                    "wrong_final_owner", "wrong_request_id", "wrong_lifecycle", "foreign_lock"])
def test_unknown_queued_hook_shapes_refuse_without_invoking_callbacks(queued_save, change):
    case, source = queued_save, queued_save.env.source
    queued, context = captured_queued_hooks(case)
    calls = []

    def poison(_self=None):
        calls.append("untrusted hook")

    if change == "foreign_method":
        context.check_cancelled = MethodType(poison, queued)
    elif change == "fake_owner":
        context.check_cancelled = MethodType(case.queue.QueuedRequest.check_active, NS())
    elif change == "subclass_owner":
        class Subclass(case.queue.QueuedRequest):
            pass
        context.check_cancelled = Subclass(queued.request).check_active
    elif change == "wrong_final_code":
        context.check_final_request = poison
    elif change == "wrong_final_owner":
        other = case.queue.QueuedRequest(queued.request)
        cell = (lambda: other).__closure__[0]
        original = context.check_final_request
        context.check_final_request = FunctionType(original.__code__, original.__globals__, closure=(cell,))
    elif change == "wrong_request_id":
        context.request_id = "other-owner"
    elif change == "wrong_lifecycle":
        context.request_lifecycle = case.lifecycle.RequestLifetime(case.connection)
    else:
        class ForeignLock:
            def __enter__(self):
                calls.append("foreign lock")
            def __exit__(self, *_args):
                return False
        queued._lock = ForeignLock()
    with pytest.raises(source.BridgeError):
        source.hook_facts(context)
    assert calls == [] and not case.env.native.calls


@pytest.mark.parametrize("dependency", ["method_binding", "method_code", "queue_class", "queue_clock",
                                         "queue_error", "executor_queue", "executor_code"])
def test_changed_queued_hook_dependencies_refuse_before_callbacks(queued_save, monkeypatch, dependency):
    case, source = queued_save, queued_save.env.source
    _queued, context = captured_queued_hooks(case)
    calls = []

    def poison(_self=None):
        calls.append("replaced dependency")

    def poison_code(*_args, **_kwargs):
        raise AssertionError("A substituted implementation must not run")

    if dependency == "method_binding":
        monkeypatch.setattr(case.queue.QueuedRequest, "check_active", poison)
    elif dependency == "method_code":
        monkeypatch.setattr(case.queue.QueuedRequest.check_active, "__code__", poison_code.__code__)
    elif dependency == "queue_class":
        monkeypatch.setattr(case.queue, "QueuedRequest", object())
    elif dependency == "queue_clock":
        monkeypatch.setattr(case.queue, "time", NS(monotonic=poison))
    elif dependency == "queue_error":
        monkeypatch.setattr(case.queue, "BridgeError", poison)
    elif dependency == "executor_queue":
        monkeypatch.setattr(source._executor_module, "QueuedRequest", object())
    else:
        monkeypatch.setattr(source._EXECUTOR_INVOKE, "__code__", poison_code.__code__)
    with pytest.raises(source.BridgeError):
        source.hook_facts(context)
    assert calls == [] and not case.env.native.calls


def test_canonical_clock_function_substitution_refuses_without_calling_it(queued_save, monkeypatch):
    case, source = queued_save, queued_save.env.source
    _queued, context = captured_queued_hooks(case)
    calls = []

    def poison():
        calls.append("clock")
        return 0.

    error = None
    with monkeypatch.context() as patch:
        patch.setattr(source._QUEUE_TIME, "monotonic", poison)
        try:
            source.hook_facts(context)
        except source.BridgeError as cause:
            error = cause
    assert error is not None and calls == [] and not case.env.native.calls


def test_retained_queued_hook_deadline_changes_do_not_match(queued_save):
    case, source = queued_save, queued_save.env.source
    queued, context = captured_queued_hooks(case)
    original = source.hook_facts(context)
    assert source.hooks_match(context, original)
    queued.deadline += 1.
    assert source.hooks_match(context, original) is False
    assert not case.env.native.calls


@pytest.mark.parametrize("changed", ["method", "params"])
def test_queue_hook_owner_must_match_the_actual_executed_request_intent(queued_save, monkeypatch, changed):
    case, env = queued_save, queued_save.env
    queued = queued_request(case, "project.native_save_preview", {"mode": "COPY_NEW",
        "filepath": str(env.folder / "wrong-owner.blend"), "overwrite_policy": "NO_CLOBBER"})
    executed = queued.request
    queued.request = replace(executed, **({"method": "different.request"} if changed == "method"
                                         else {"params": dict(executed.params)}))
    reads = []
    monkeypatch.setattr(env.source, "snapshot", lambda _resource_directory=None: reads.append("source"))
    monkeypatch.setattr(env.source, "options", lambda: reads.append("options"))
    response = case.executor.execute_request(executed, check_cancelled=queued.check_active)
    assert not response.ok and response.error["context"]["reason"] == "QUEUED_REQUEST_INTENT_CHANGED"
    assert reads == [] and not env.native.calls and not list(env.folder.iterdir())


@pytest.mark.parametrize("mode", ["COPY_NEW", "SAVE_AS"])
def test_registered_save_uses_real_phase_lease_and_keeps_saved_files(save_env, mode):
    env = save_env
    value = preview(env, mode)
    accepted = start(env, value)
    assert accepted["accepted"] and not env.native.calls
    row = finish(env)
    assert row["state"] == "SUCCEEDED", row
    assert (env.folder / "new project.blend").read_bytes() == b"MODEL_BLENDER_NATIVE_FILE"
    assert row["external_effects"]["native_save"]["native_save_completed"] is True
    assert row["external_effects"]["native_save"]["native_effect_inventory_complete"] is False
    assert not env.registry.active_exclusive_mutation and env.manager.active is None


def test_nested_mutator_is_blocked_inside_native_save_callback(save_env):
    env = save_env
    calls = []
    env.registry.register("fixture.edit", lambda *_: calls.append(True), modifies=True,
                          automatic_checkpoint=False)

    def hook():
        with pytest.raises(env.source.BridgeError) as failure:
            env.registry.dispatch("fixture.edit", {}, env.context())
        assert failure.value.context["reason"] == "REENTRANT_MUTATION_BLOCKED"

    env.native.native_hook = hook
    start(env, preview(env))
    assert finish(env)["state"] == "SUCCEEDED" and calls == []


def test_manual_authored_change_during_reader_keeps_edit_and_rejects_publication(save_env):
    env = save_env
    start(env, preview(env))
    env.native.reader_gate = lambda: setattr(env.native, "raw", b'{"edited":1}')
    row = finish(env)
    assert row["state"] == "FAILED" and row["result"] is None
    assert env.native.raw == b'{"edited":1}' and not (env.folder / "new project.blend").exists()
    assert row["external_effects"]["native_save"]["possible_native_effects"] is True


def test_undelivered_or_rejected_handoff_does_not_prepare_private_files(save_env):
    env = save_env
    lifecycle = importlib.import_module(env.source.RequestLifetime.__module__)
    connection = lifecycle.ConnectionLifetime()
    preview_context = env.context()
    preview_context.request_lifecycle = lifecycle.RequestLifetime(connection)
    preview_context.request_lifecycle.acknowledge(True)
    value = preview(env, context=preview_context)
    lifetime = lifecycle.RequestLifetime(connection)
    context = env.context()
    context.request_lifecycle = lifetime
    start(env, value, context)
    assert env.manager.tick() and env.native.calls == []
    assert not env.manager._save_contexts
    lifetime.acknowledge(False)
    row = finish(env)
    assert row["state"] == "CANCELLED" and env.native.calls == []


def test_permission_revoked_inside_native_callback_preserves_possible_effects(save_env):
    env = save_env
    start(env, preview(env))
    env.native.native_hook = env.grant.revoke
    row = finish(env)
    assert row["state"] == "CANCELLED" and row["result"] is None
    assert row["external_effects"]["native_save"]["native_save_completed"] is True
    assert row["external_effects"]["native_save"]["possible_native_effects"] is True
    assert not (env.folder / "new project.blend").exists()


def test_provider_cannot_replace_a_final_hook_after_source_cas(save_env):
    env = save_env
    original = env.context().permissions._source
    context = env.context()
    changed = []

    def provider():
        context.check_final_request = lambda: changed.append(True)
        return original()

    context.permissions._source = provider
    with pytest.raises(env.source.BridgeError):
        preview(env, context=context)
    assert not changed and not env.native.calls


@pytest.mark.parametrize("permission", ["INSPECT_SCENE", "SAVE_PROJECT", "ACCESS_EXTERNAL_FILES", "NATIVE_SAVE_EFFECTS"])
def test_admission_denied_permission_precedes_any_blender_or_files_read(save_env, monkeypatch, permission):
    env = save_env
    env.values[permission] = False
    calls = []

    def poison():
        calls.append(True)
        pytest.fail("Denied admission must not inspect Blender")

    monkeypatch.setattr(env.source, "require_blender", poison)
    with pytest.raises(env.source.BridgeError) as failure:
        preview(env)
    assert failure.value.code == "PERMISSION_DENIED" and not calls and not env.native.calls


def test_late_history_failure_keeps_copy_file_and_nulls_success(save_env, monkeypatch):
    env = save_env
    start(env, preview(env))
    monkeypatch.setattr(env.state, "record_operation", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("history")))
    row = finish(env)
    assert row["state"] == "FAILED" and row["result"] is None
    assert row["progress"]["phase"] == "failed"
    assert (env.folder / "new project.blend").is_file()
    assert row["external_effects"]["file_published"] is True
    assert not env.manager._save_contexts and not env.registry.active_exclusive_mutation


@pytest.mark.parametrize("method", ["project.native_save_preview", "project.native_save_start"])
@pytest.mark.parametrize("entry", ["registry", "executor"])
def test_protected_entry_refuses_before_canonical_provider_or_native_factory(save_env, monkeypatch, method, entry):
    env = save_env
    runtime_module = importlib.import_module(env.source._runtime.__name__)
    env.context().permissions._source = FunctionType(runtime_module._PERMISSION_PROVIDER_CODE, vars(runtime_module))
    store = env.source.get_task_plans(env.state)
    protection = store.protection = {"fixture_model": True}
    calls = []

    def poison(*_args, **_kwargs):
        calls.append("unsafe")
        pytest.fail("Initial protected denial must precede admission, provider, Blender and files")

    monkeypatch.setattr(env.source, "qualify_provider", poison)
    monkeypatch.setattr(env.source, "require_blender", poison)
    monkeypatch.setattr(env.jobs, "freeze_plan", poison)
    if entry == "executor":
        executor = importlib.import_module(f"{runtime_module.__package__}.executor").MainThreadExecutor(
            command_queue=importlib.import_module(f"{runtime_module.__package__}.command_queue").CommandQueue(),
            registry=env.registry, state=env.state, permissions=env.context().permissions,
            checkpoints=env.context().checkpoints, jobs=env.manager)
        invoke = executor.dispatch
    else:
        def invoke(name, params):
            return env.registry.dispatch(name, params, env.context())
    previous_trace = sys.gettrace()

    def trace(frame, event, _arg):
        if event == "call" and frame.f_code is runtime_module._PERMISSION_PROVIDER_CODE:
            poison()
        return trace

    try:
        sys.settrace(trace)
        with pytest.raises(env.source.BridgeError) as failure:
            invoke(method, {"mode": "COPY_NEW", "filepath": str(env.folder / "denied.blend"),
                            "overwrite_policy": "NO_CLOBBER"})
    finally:
        sys.settrace(previous_trace)
    assert failure.value.code == "NOT_IMPLEMENTED"
    assert failure.value.context["initial_policy_classification"] is True
    assert store.protection is protection and not calls and not env.native.calls
    assert not (env.folder / "denied.blend").exists()


def test_later_accepted_start_reaps_worker_but_preserves_native_recovery_stage_and_receipt(save_env):
    env = save_env
    start(env, preview(env))
    env.native.reader_gate = lambda: setattr(env.native, "raw", b'{"edited":1}')
    row = finish(env)
    retained = env.manager._save_retained[row["job_id"]]
    stage = retained.files.folder
    assert stage.is_dir() and row["state"] == "FAILED"
    env.native.reader_gate = None
    start(env, preview(env, filename="next project.blend"))
    assert stage.is_dir() and retained.files.native_path.read_bytes() == b"MODEL_BLENDER_NATIVE_FILE"
    assert env.manager._save_retained[row["job_id"]] is retained
    assert retained.job.state == "FAILED" and retained.job.result is None
    assert finish(env)["state"] == "SUCCEEDED"
    assert not env.manager._save_contexts and not env.registry.active_exclusive_mutation


def test_unknown_retained_reader_blocks_new_worker_after_approved_folder_change(save_env, monkeypatch):
    env = save_env
    start(env, preview(env))
    env.native.reader_gate = lambda: setattr(env.native, "raw", b'{"edited":1}')
    env.native.reader_reaped = False
    row = finish(env)
    retained = env.manager._save_retained[row["job_id"]]
    other = env.folder / "other approved folder"
    other.mkdir()
    monkeypatch.setattr(env.source, "options", lambda: (str(other), 0, "NONE", False))
    env.native.reader_gate = None
    env.folder = other
    calls_before = list(env.native.calls)
    with pytest.raises(env.source.BridgeError) as failure:
        start(env, preview(env))
    assert failure.value.context["reason"] == "READER_REAP_PENDING"
    assert env.native.calls == [*calls_before, "reader_close"]
    assert retained.files.native_path.is_file() and env.manager.active is None


def test_retained_cap_never_deletes_native_project_bytes_to_make_room(save_env, monkeypatch):
    env = save_env
    stages = []
    for index in range(4):
        start(env, preview(env, filename=f"failed {index}.blend"))
        env.native.reader_gate = lambda index=index: setattr(env.native, "raw", f'{{"edited":{index}}}'.encode())
        row = finish(env)
        retained = env.manager._save_retained[row["job_id"]]
        stages.append(retained.files.native_path)
        original_close = retained.files.close

        def preserve_only(*, remove_files=True, original=original_close):
            assert remove_files is False, "A later grant must not delete retained recovery artifacts"
            return original(remove_files=False)

        monkeypatch.setattr(retained.files, "close", preserve_only)
    env.native.reader_gate = None
    with pytest.raises(env.source.BridgeError) as failure:
        start(env, preview(env, filename="over capacity.blend"))
    assert failure.value.context["reason"] == "RETAINED_RESOURCE_LIMIT"
    assert len(env.manager._save_retained) == 4 and env.manager.active is None
    assert all(path.read_bytes() == b"MODEL_BLENDER_NATIVE_FILE" for path in stages)


def test_native_save_as_revoke_records_actual_changed_filepath(save_env):
    env = save_env
    value = preview(env, "SAVE_AS")
    start(env, value)
    env.native.native_hook = env.grant.revoke
    row = finish(env)
    assert row["state"] == "CANCELLED"
    assert row["external_effects"]["native_save"]["source_filepath_after"] == value["filepath"]
    assert (env.folder / "new project.blend").is_file()
