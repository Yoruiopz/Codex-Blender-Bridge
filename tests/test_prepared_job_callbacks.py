"""Counter models for the concrete internal protocol, not image qualification.

The absent future domain is represented explicitly by two inert model modules.
Runtime, NativeSaveJobs, executor, registry, permission provider and checkpoint
manager are genuine. Blender data/undo and driver writes remain modeled.
"""
from __future__ import annotations

import importlib
import sys
from types import FunctionType, ModuleType
from types import SimpleNamespace as NS

import pytest
from test_checkpoint_snapshots import NativeStack
from test_image_paint import Image

SOURCE_MODEL = '''
class CurrentPixelsOrigin:
    def __init__(self):
        self.valid = True
    def check_job_callbacks(self):
        if not self.valid:
            raise BridgeError("OPERATION_FAILED", "Modeled retained origin changed")
'''

DOMAIN_MODEL = '''
def prepare_current_pixels(context, params):
    counts["prepare"] += 1
    return {"source": image, "source_name": image.name, "name": "Snapshot",
            "requires_external_files": True, "method": method,
            "kind": "current_pixels_lifecycle", "driver_type": flags.get("driver_type", CurrentPixelsDriver),
            "workload": {"modeled_pixels": 1}}

class CurrentPixelsDriver:
    def __init__(self, prepared):
        counts["construct"] += 1
        self.prepared = prepared
        self.effects = {"publication_attempted": False, "file_published": False}
        self.recovery = {"mode": "LOADED_BUFFER", "possible_mutation": False}
    def steps(self, context, job, commit):
        counts["steps"] += 1
        yield {"phase": "prepared", "completed": 0, "total": 1}
        counts["steps"] += 1
        job.execution_started = True
        def write():
            counts["writes"] += 1
            self.effects.update(publication_attempted=True, file_published=True)
            self.recovery["possible_mutation"] = True
            return {"modeled": True}
        commit(write)
        yield {"phase": "written", "completed": 1, "total": 1}
        counts["steps"] += 1
        return {"modeled": True}
    def cleanup(self, context, job, *, success):
        counts["cleanup"] += 1
        assert context is None or flags.get("legacy")
        flags["phase"] = "final"
        flags["final_grants"] = 0
        if flags.get("cleanup_reentry"):
            manager._finish(job, "FAILED", BridgeError("TIMEOUT", "Reentry"))
        if flags.get("cleanup_error"):
            raise BridgeError("OPERATION_FAILED", "Modeled release failed")
        return dict(self.effects)
    def evidence(self):
        counts["evidence"] += 1
        return dict(self.effects)
    def recovery_evidence(self):
        counts["recovery"] += 1
        if flags.get("phase") == "final":
            hook = flags.get("observer")
            if hook is not None:
                hook()
            if flags.get("observation_error"):
                raise BridgeError("OPERATION_FAILED", "Modeled observation failed")
            if "malformed" in flags:
                return flags["malformed"]
        return dict(self.recovery)
'''

_prepared_foreign_context_probe = None  # Rebound only in the attacked function's globals.


@pytest.fixture
def prepared(addon_package, monkeypatch):
    runtime_module = importlib.import_module(addon_package + ".runtime")
    jobs = importlib.import_module(addon_package + ".jobs")
    state_module = importlib.import_module(addon_package + ".state")
    permissions = importlib.import_module(addon_package + ".permissions")
    lifecycle = importlib.import_module(addon_package + ".request_lifecycle")
    utils = importlib.import_module(addon_package + ".utils")
    monkeypatch.setattr(state_module, "_STATE", state_module.BridgeState())
    counts = dict.fromkeys(("prepare", "construct", "steps", "writes", "cleanup", "evidence", "recovery", "foreign", "grants"), 0)
    flags = {"phase": "admit", "final_grants": 0}

    class Preferences:
        def __getattribute__(self, name):
            if name == "allow_inspect_scene":
                counts["grants"] += 1
                if flags["phase"] == "final":
                    flags["final_grants"] += 1
                    hook = flags.get("grant")
                    if hook is not None:
                        hook(flags["final_grants"])
            return object.__getattribute__(self, name)

    prefs = Preferences()
    for name in permissions.PREFERENCE_PROPERTIES.values():
        setattr(prefs, name, True)
    stack = NativeStack()
    stack.bpy.context.preferences.addons = {addon_package: NS(preferences=prefs)}
    monkeypatch.setitem(sys.modules, "bpy", stack.bpy)
    monkeypatch.setattr(utils, "bpy", stack.bpy)
    runtime = runtime_module.BridgeRuntime()
    runtime._registered = True
    monkeypatch.setattr(runtime_module, "_RUNTIME", runtime)
    runtime.registry.enable_toolset("materials")
    required = tuple(getattr(permissions.Permission, name) for name in
                     ("INSPECT_SCENE", "EDIT_MATERIALS", "ACCESS_EXTERNAL_FILES", "SAVE_PROJECT"))
    method = "image.pack_current_pixels_job_start"
    runtime.registry.register(method, lambda *_: None, toolset="materials", modifies=True,
                              automatic_checkpoint=False, permissions=required)
    source = ModuleType(addon_package + ".current_pixels_source")
    source.BridgeError = jobs.BridgeError
    exec(SOURCE_MODEL, vars(source))
    domain = ModuleType(addon_package + ".tools.image_current_pixels")
    domain.__dict__.update(counts=counts, flags=flags, image=Image("Original"),
                           method=method, manager=runtime.jobs, BridgeError=jobs.BridgeError)
    exec(DOMAIN_MODEL, vars(domain))
    monkeypatch.setitem(sys.modules, source.__name__, source)
    monkeypatch.setitem(sys.modules, domain.__name__, domain)
    return NS(jobs=jobs, runtime=runtime, manager=runtime.jobs, source=source, domain=domain,
              counts=counts, flags=flags, required=required, lifecycle=lifecycle, prefs=prefs,
              stack=stack, state_module=state_module)


def start(env, *, delivered=True, legacy=False):
    context = env.runtime.executor.context
    context.request_id = "prepared-model-start"
    lifetime = env.lifecycle.RequestLifetime(env.lifecycle.ConnectionLifetime())
    context.request_lifecycle = lifetime
    origin = env.source.CurrentPixelsOrigin()
    control = env.jobs.PreparedJobCallbacks.capture(context, origin=origin)
    provider = env.runtime.permissions._source
    accepted = env.manager.start_prepared_driver(context, {}, 60., prepare=env.domain.prepare_current_pixels,
                required_permissions=env.required, **({} if legacy else {"callback_control": control}))
    assert env.runtime.permissions._source is provider
    if delivered:
        lifetime.acknowledge(True)
    return accepted, control, lifetime


def finish(env):
    for _ in range(20):
        if not env.manager.tick():
            return env.manager.history[0].summary()
    pytest.fail("Modeled guarded job did not terminate")


def trap(env):
    def foreign(*_args, **_kwargs):
        env.counts["foreign"] += 1
        raise AssertionError("Foreign callback invoked")
    return foreign


def change_checked_context_origin(env, monkeypatch, kind):
    """Each replacement has an observable callback if the guard dereferences it."""
    module = env.jobs._prepared_context_module
    runtime_module = sys.modules[type(env.runtime).__module__]
    helper = env.jobs._PREPARED_CONTEXT_HELPER
    foreign = trap(env)
    if kind == "runtime_alias":
        monkeypatch.setattr(runtime_module, "checked_executor_context", foreign)
    elif kind in {"runtime_module_access", "executor_module_access"}:
        class ForeignModule(ModuleType):
            __getattribute__ = foreign
        target = runtime_module if kind == "runtime_module_access" else env.jobs._PREPARED_EXECUTOR_MODULE
        monkeypatch.setattr(target, "__class__", ForeignModule)
    elif kind == "module_alias":
        monkeypatch.setattr(module, "checked_executor_context", foreign)
    elif kind == "helper_globals":
        namespace = dict(helper.__globals__)
        namespace["type"] = foreign
        replacement = FunctionType(helper.__code__, namespace)
        monkeypatch.setattr(runtime_module, "checked_executor_context", replacement)
        monkeypatch.setattr(module, "checked_executor_context", replacement)
    elif kind == "helper_closure":
        def replacement(executor):
            return foreign(executor)
        monkeypatch.setattr(runtime_module, "checked_executor_context", replacement)
        monkeypatch.setattr(module, "checked_executor_context", replacement)
    elif kind in {"helper_code", "guard_code"}:
        def replacement(*args):
            return _prepared_foreign_context_probe(*args)
        target = helper if kind == "helper_code" else vars(env.jobs._PREPARED_CONTEXT_SERVICE)["check_context_factory"]
        monkeypatch.setitem(target.__globals__, "_prepared_foreign_context_probe", foreign)
        monkeypatch.setattr(target, "__code__", replacement.__code__)
    elif kind == "helper_defaults":
        monkeypatch.setattr(helper, "__defaults__", (foreign,))
    elif kind == "helper_kwdefaults":
        monkeypatch.setattr(helper, "__kwdefaults__", {"hidden": foreign})
    elif kind in {"type_shadow", "vars_shadow"}:
        monkeypatch.setitem(vars(module), kind.split("_", 1)[0], foreign)
    elif kind == "executor_alias":
        monkeypatch.setattr(module, "_Executor", foreign)
    elif kind == "service_alias":
        monkeypatch.setattr(module, "GLBStageService", NS(check_context_factory=foreign))
    elif kind == "guard_alias":
        monkeypatch.setattr(module, "_PROTECTED_DEPENDENCY_GUARD_ORIGIN", foreign)
    elif kind in {"geometry_alias", "scene_alias"}:
        class ForeignClass:
            __eq__ = foreign
        suffix, name = ("geometry_preview_jobs", "GeometryPreviewJobs") if kind == "geometry_alias" else ("scene_jobs", "SceneJobs")
        monkeypatch.setattr(sys.modules[env.jobs.__package__+"."+suffix], name, ForeignClass())
    elif kind == "origin_iterable":
        class ForeignOrigins:
            __iter__ = foreign
        monkeypatch.setattr(module, "_SERVICE_METHOD_ORIGINS", ForeignOrigins())
    elif kind == "service_method":
        monkeypatch.setattr(env.jobs._PREPARED_CONTEXT_SERVICE, "check_context_factory", foreign)
    elif kind == "service_shadow":
        monkeypatch.setattr(env.runtime.glb_stage, "check_context_factory", foreign)
    elif kind == "executor_access":
        monkeypatch.setattr(type(env.runtime.executor), "__getattribute__", foreign)
    elif kind == "runtime_access":
        monkeypatch.setattr(type(env.runtime), "__getattribute__", foreign)
    elif kind == "manager_mro":
        manager_type = type(env.manager)
        class ForeignManagerBase(manager_type.__bases__[0]):
            context_factory = property(foreign)
        original = manager_type.__bases__
        manager_type.__bases__ = (ForeignManagerBase,)
        return lambda: setattr(manager_type, "__bases__", original)
    elif kind == "executor_mro":
        executor = env.runtime.executor
        class ForeignExecutor(type(executor)):
            glb_stage = property(foreign)
        monkeypatch.setattr(executor, "__class__", ForeignExecutor)
    elif kind == "runtime_mro":
        runtime = env.runtime
        class ForeignRuntime(type(runtime)):
            jobs = property(foreign)
        monkeypatch.setattr(runtime, "__class__", ForeignRuntime)
    else:
        assert kind == "service_mro"
        service = env.runtime.glb_stage
        class ForeignService(type(service)):
            runtime = property(foreign)
        monkeypatch.setattr(service, "__class__", ForeignService)


@pytest.mark.parametrize("when", ["admission", "first_tick", "following_tick"])
@pytest.mark.parametrize("kind", ["runtime_alias", "runtime_module_access", "executor_module_access", "module_alias", "helper_globals", "helper_closure", "helper_code",
    "helper_defaults", "helper_kwdefaults", "type_shadow", "vars_shadow", "executor_alias", "service_alias", "guard_alias",
    "origin_iterable", "guard_code", "geometry_alias", "scene_alias", "service_method", "service_shadow", "executor_access", "runtime_access",
    "manager_mro", "executor_mro", "runtime_mro", "service_mro"])
def test_checked_factory_helper_is_proven_before_foreign_access(prepared, monkeypatch, when, kind):
    env = prepared
    if when == "admission":
        context = env.runtime.executor.context
        origin = env.source.CurrentPixelsOrigin()
    else:
        start(env)
        if when == "following_tick":
            assert env.manager.tick() and env.counts["steps"] == 1
    before = dict(env.counts)
    restore = change_checked_context_origin(env, monkeypatch, kind)
    try:
        if when == "admission":
            with pytest.raises(env.jobs.BridgeError):
                env.jobs.PreparedJobCallbacks.capture(context, origin=origin)
        else:
            row = finish(env)
            assert row["state"] == "FAILED" and row["error"]["context"]["verification_required"]
        assert env.counts == before
        assert env.counts["foreign"] == env.counts["writes"] == 0
    finally:
        if restore is not None:
            restore()


@pytest.mark.parametrize("kind", ["defaults", "kwdefaults", "empty_closure", "wrong_closure", "copied_globals"])
def test_new_canonical_factory_still_refuses_unowned_literal_shapes_at_admission(prepared, monkeypatch, kind):
    env = prepared
    context = env.runtime.executor.context
    factory = env.manager.context_factory
    if kind == "defaults":
        monkeypatch.setattr(factory, "__defaults__", (trap(env),))
    elif kind == "kwdefaults":
        monkeypatch.setattr(factory, "__kwdefaults__", {"hidden": trap(env)})
    elif kind in {"empty_closure", "wrong_closure"}:
        cell = factory.__closure__[0]
        original = cell.cell_contents
        if kind == "empty_closure":
            del cell.cell_contents
        else:
            cell.cell_contents = NS(executor=NS(context=trap(env)))
    else:
        monkeypatch.setattr(env.manager, "context_factory", FunctionType(factory.__code__, dict(factory.__globals__),
            closure=factory.__closure__))
    before = dict(env.counts)
    try:
        with pytest.raises(env.jobs.BridgeError):
            env.jobs.PreparedJobCallbacks.capture(context, origin=env.source.CurrentPixelsOrigin())
    finally:
        if kind in {"empty_closure", "wrong_closure"}:
            cell.cell_contents = original
    assert env.counts == before and env.counts["foreign"] == 0


def test_actual_runtime_inheritance_delivery_native_checkpoint_and_captured_history(prepared):
    env = prepared
    accepted, control, lifetime = start(env, delivered=False)
    runtime_module = importlib.import_module(type(env.runtime).__module__)
    assert type(env.manager) is runtime_module.NativeSaveJobs
    assert runtime_module.native_save_permission_provider_intact()
    assert type(env.manager.active) is env.jobs.GuardedPreparedPaintJob
    assert accepted["accepted"] and lifetime.connection.background_active.is_set()
    assert env.manager.tick() and env.counts["steps"] == env.counts["writes"] == 0
    lifetime.acknowledge(True)
    result = finish(env)
    assert result["state"] == "SUCCEEDED", result
    assert env.counts["writes"] == 1 and env.counts["cleanup"] == 1
    assert result["undo_boundary_created"] and result["undo_boundary_finalized"]
    assert len(env.stack.frames) == 3
    assert result["external_effects"]["file_published"]
    assert env.runtime.state.history(1)[0]["operation_id"] == result["operation_id"]
    assert control.history_attempted and control.retired and control.driver is None
    assert not env.manager._prepared_controls and env.manager._prepared_active is None
    assert not lifetime.connection.background_active.is_set()


@pytest.mark.parametrize("between_ticks", [False, True])
def test_changed_factory_is_never_called_before_first_or_following_tick(prepared, between_ticks):
    env = prepared
    start(env)
    if between_ticks:
        assert env.manager.tick() and env.counts["steps"] == 1
    baseline = env.counts["steps"], env.counts["writes"], env.counts["evidence"], env.counts["recovery"]
    env.manager.context_factory = trap(env)
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == 0
    assert (env.counts["steps"], env.counts["writes"], env.counts["evidence"], env.counts["recovery"]) == baseline
    assert row["error"]["context"]["cleanup_outcome_unknown"]
    assert row["error"]["context"]["operation_history_unknown"]


@pytest.mark.parametrize("provider", [1, 2])
def test_actual_final_permission_and_registry_prepare_grants_cannot_replace_factory(prepared, provider):
    env = prepared
    start(env)
    seen = []
    def change(index):
        if index == provider:
            env.manager.context_factory = trap(env)
            seen.append(index)
    env.flags["grant"] = change
    row = finish(env)
    assert seen == [provider] and row["state"] == "FAILED", row
    assert env.counts["foreign"] == 0 and env.counts["writes"] == 1
    assert row["external_effects"]["file_published"]
    assert row["result"] is None and row["error"]["context"]["possible_mutation"]


@pytest.mark.parametrize("change", ["code", "closure"])
def test_factory_same_identity_code_or_closure_drift_refuses_before_invocation(prepared, monkeypatch, change):
    env = prepared
    _, control, _ = start(env)
    if change == "code":
        foreign = trap(env)
        def replacement():
            return foreign()
        monkeypatch.setattr(control.factory, "__code__", replacement.__code__)
    else:
        cell = control.factory.__closure__[0]
        original = cell.cell_contents
        cell.cell_contents = NS(executor=NS(context=trap(env)))
    try:
        row = finish(env)
    finally:
        if change == "closure":
            cell.cell_contents = original
    assert row["state"] == "FAILED" and env.counts["foreign"] == 0
    assert env.counts["steps"] == env.counts["writes"] == 0


@pytest.mark.parametrize("raises", [False, True])
def test_final_observer_factory_change_has_no_late_factory_provider_or_driver_calls(prepared, raises):
    env = prepared
    start(env)
    at_observer = []
    def change():
        env.manager.context_factory = trap(env)
        at_observer.append(dict(env.counts))
        if raises:
            raise env.jobs.BridgeError("OPERATION_FAILED", "Observer interrupted after drift")
    env.flags["observer"] = change
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == 0
    assert len(at_observer) == 1
    assert env.counts == at_observer[0]
    assert row["external_effects"]["file_published"] and row["result"] is None


def test_foreign_recorder_is_skipped_while_captured_effects_and_original_error_remain(prepared):
    env = prepared
    start(env)
    def replace():
        env.runtime.state.record_operation = trap(env)
        raise env.jobs.BridgeError("OPERATION_FAILED", "Primary observer refusal", {"primary": True})
    env.flags["observer"] = replace
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == 0
    assert row["error"]["message"] == "Primary observer refusal"
    assert row["error"]["context"]["primary"]
    assert row["error"]["context"]["operation_history_unknown"]
    assert row["external_effects"]["file_published"] and row["operation_id"] is None


@pytest.mark.parametrize("real_generator", [False, True])
def test_replaced_work_never_dispatches_foreign_next_or_close(prepared, real_generator):
    env = prepared
    start(env)
    assert env.manager.tick()
    job = env.manager.active
    if real_generator:
        def foreign():
            try:
                yield {}
                env.counts["foreign"] += 1
            finally:
                env.counts["foreign"] += 1
        replacement = foreign()
        next(replacement)
    else:
        class Foreign:
            __next__ = close = trap(env)
        replacement = Foreign()
    job.work = replacement
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == 0
    assert env.counts["writes"] == 0
    assert env.manager._prepared_unresolved is not None
    if real_generator:
        replacement.close()  # Test-owned disposal is outside product execution.


def test_foreign_driver_attribute_access_and_polling_never_run_callbacks(prepared):
    env = prepared
    start(env)
    job = env.manager.active
    class Foreign:
        def __getattribute__(self, _name):
            env.counts["foreign"] += 1
            raise AssertionError("Foreign driver attribute observed")
    job.driver = Foreign()
    env.manager.context_factory = trap(env)
    before = dict(env.counts)
    env.manager.inspect(job.job_id)
    env.manager.list()
    env.manager.status()
    assert env.counts == before
    row = finish(env)
    before = dict(env.counts)
    env.manager.inspect(job.job_id)
    env.manager.list()
    env.manager.status()
    assert env.counts == before and env.counts["foreign"] == 0
    assert row["state"] == "FAILED"


@pytest.mark.parametrize("method", ["steps", "cleanup", "evidence", "recovery_evidence"])
def test_rebound_driver_callback_is_rejected_without_invocation(prepared, method):
    env = prepared
    start(env)
    setattr(env.manager.active.driver, method, trap(env))
    before = dict(env.counts)
    env.manager.list()
    assert env.counts == before
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == 0
    assert env.counts["writes"] == env.counts["steps"] == 0


@pytest.mark.parametrize("damage", ["missing", "map", "control", "token", "pair"])
def test_control_damage_stays_guarded_retains_unknown_and_blocks_next_guarded_start(prepared, damage):
    env = prepared
    _, control, _ = start(env)
    job = env.manager.active
    if damage == "missing":
        env.manager._prepared_controls.clear()
    elif damage == "map":
        env.manager._prepared_controls = {}
    elif damage == "control":
        env.manager._prepared_controls[id(job)] = (job, object(), control.token)
    elif damage == "token":
        job._callback_token = object()
    else:
        env.manager._prepared_controls[id(job)] = (object(), control, control.token)
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == 0
    assert env.counts["steps"] == env.counts["writes"] == env.counts["cleanup"] == 0
    assert row["error"]["context"]["cleanup_outcome_unknown"]
    with pytest.raises(env.jobs.BridgeError, match="callback ownership changed"):
        start(env)


def test_guarded_budget_is_fixed_and_each_tick_advances_only_one_step(prepared):
    env = prepared
    start(env)
    env.manager.budget_ms = trap(env)
    assert env.manager.tick() and env.counts["steps"] == 1 and env.counts["writes"] == 0
    assert env.manager.tick() and env.counts["steps"] == 2 and env.counts["writes"] == 1
    assert finish(env)["state"] == "SUCCEEDED" and env.counts["foreign"] == 0


@pytest.mark.parametrize("failure", ["cleanup_error", "observation_error"])
def test_terminal_failure_retains_already_observed_files_and_no_automatic_inverse(prepared, failure):
    env = prepared
    _, control, _ = start(env)
    env.flags[failure] = True
    row = finish(env)
    assert row["state"] == "FAILED" and row["result"] is None
    assert env.counts["writes"] == env.counts["cleanup"] == 1
    assert row["external_effects"]["file_published"]
    assert env.runtime.state.history(1)[0]["job_evidence"]["external_effects"]["file_published"]
    assert bool(env.manager._prepared_unresolved) is (failure == "cleanup_error")
    assert control.retired


@pytest.mark.parametrize("stop", ["cancel_all", "cancel", "disconnect", "reject", "deadline", "permission"])
def test_actual_lifetime_and_permission_loss_prevent_undelivered_work(prepared, stop):
    env = prepared
    _, _, lifetime = start(env, delivered=False)
    if stop == "cancel_all":
        env.manager.cancel_all("lifecycle stop")
    elif stop == "cancel":
        env.manager.cancel(env.manager.active.job_id)
    elif stop == "disconnect":
        lifetime.connection.disconnected.set()
    elif stop == "reject":
        lifetime.acknowledge(False)
    elif stop == "deadline":
        env.manager.active.deadline = 0
    else:
        env.prefs.allow_edit_materials = False
    row = finish(env)
    assert row["state"] in {"FAILED", "CANCELLED"}
    assert env.counts["steps"] == env.counts["writes"] == env.counts["foreign"] == 0
    assert not lifetime.connection.background_active.is_set()


@pytest.mark.parametrize("receipt", [None, {}, {"kind": "current_pixels_lifecycle", "mode": "LOADED_BUFFER"}, {"mode": "invented"}])
def test_malformed_final_observation_never_becomes_empty_success(prepared, receipt):
    env = prepared
    start(env)
    env.flags["malformed"] = receipt
    row = finish(env)
    assert row["state"] == "FAILED" and row["result"] is None
    assert "recovery_evidence" in row["evidence_observation_unknown"]
    assert row["external_effects"]["file_published"]


def test_canonical_recorder_exception_is_not_retried_and_retains_primary_failure(prepared, monkeypatch):
    env = prepared
    _, control, _ = start(env)
    assert env.manager.tick() and env.manager.tick()
    calls = []
    def failed_uuid():
        calls.append(True)
        raise MemoryError("Injected trusted primitive allocation failure")
    # A fault in a trusted primitive exercises an actual canonical recorder raise;
    # this is not a production arbitrary-interpreter substitution guarantee.
    monkeypatch.setattr(env.state_module.uuid, "uuid4", failed_uuid)
    env.flags["observation_error"] = True
    row = finish(env)
    assert calls == [True] and control.history_attempted
    assert row["error"]["message"] == "Modeled observation failed"
    assert row["error"]["context"]["operation_history_unknown"]
    assert row["external_effects"]["file_published"] and env.manager.active is None


def test_reentrant_terminalization_records_once_and_releases_one_owner(prepared):
    env = prepared
    _, control, _ = start(env)
    with pytest.raises(env.jobs.BridgeError, match="already active"):
        start(env)
    env.flags["cleanup_reentry"] = True
    row = finish(env)
    assert row["state"] == "SUCCEEDED" and env.counts["cleanup"] == 1
    assert len(env.runtime.state.history(10)) == len(env.manager.history) == 1
    assert control.retired and not env.manager._prepared_controls
    env.manager._finish(control.job, "FAILED", env.jobs.BridgeError("TIMEOUT", "Too late"))
    assert len(env.manager.history) == 1


def test_legacy_prepared_route_keeps_original_record_live_polling_and_budget(prepared):
    env = prepared
    env.flags["legacy"] = True
    accepted, _, _ = start(env, legacy=True)
    assert type(env.manager.active) is env.jobs.PaintJob
    assert accepted["accepted"] and env.manager._prepared_active is None
    before = env.counts["evidence"]
    env.manager.list()
    assert env.counts["evidence"] > before
    calls = []
    env.manager.budget_ms = lambda: calls.append(True) or 4.
    row = finish(env)
    assert row["state"] == "SUCCEEDED" and calls
    assert env.manager.history.maxlen == 32


@pytest.mark.parametrize("changed", ["prepare", "source", "constructor", "permissions", "returned_type"])
def test_preparation_and_constructor_origins_are_checked_before_invocation(prepared, monkeypatch, changed):
    env = prepared
    context = env.runtime.executor.context
    control = env.jobs.PreparedJobCallbacks.capture(context, origin=env.source.CurrentPixelsOrigin())
    if changed == "prepare":
        monkeypatch.setattr(env.domain, "prepare_current_pixels", trap(env))
    elif changed == "source":
        monkeypatch.setattr(env.source.CurrentPixelsOrigin, "check_job_callbacks", trap(env))
    elif changed == "constructor":
        monkeypatch.setattr(env.domain.CurrentPixelsDriver, "__init__", trap(env))
    elif changed == "returned_type":
        class Foreign:
            __init__ = trap(env)
        env.flags["driver_type"] = Foreign
    with pytest.raises(env.jobs.BridgeError):
        env.manager.start_prepared_driver(context, {}, 60., prepare=control.prepare,
                required_permissions=() if changed == "permissions" else env.required,
                callback_control=control)
    assert env.counts["foreign"] == env.counts["construct"] == env.counts["writes"] == 0
    assert env.counts["prepare"] == (1 if changed == "returned_type" else 0)


@pytest.mark.parametrize("callback", ["steps", "cleanup", "evidence", "recovery_evidence"])
def test_real_final_grant_rebinding_never_invokes_the_foreign_driver_callback(prepared, callback):
    env = prepared
    start(env)
    def change(index):
        if index == 1:
            setattr(env.manager.active.driver, callback, trap(env))
    env.flags["grant"] = change
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == 0
    assert env.counts["writes"] == 1 and row["external_effects"]["file_published"]


@pytest.mark.parametrize("changed", ["getter", "runtime", "service"])
def test_changed_canonical_context_origin_is_rejected_without_a_foreign_call(prepared, monkeypatch, changed):
    env = prepared
    _, control, _ = start(env)
    if changed == "getter":
        monkeypatch.setattr(type(env.runtime.executor), "context", property(trap(env)))
    elif changed == "runtime":
        monkeypatch.setattr(control.runtime_module, "_RUNTIME", NS())
    else:
        env.runtime.executor.jobs = object()
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == env.counts["writes"] == 0


@pytest.mark.parametrize("changed", ["method", "dependency"])
def test_canonical_history_origin_change_is_skipped_without_foreign_callbacks(prepared, monkeypatch, changed):
    env = prepared
    start(env)
    def change():
        if changed == "method":
            monkeypatch.setattr(env.state_module.BridgeState, "record_operation", trap(env))
        else:
            monkeypatch.setattr(env.state_module, "_now", trap(env))
    env.flags["observer"] = change
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == 0
    assert row["error"]["context"]["operation_history_unknown"]
    assert row["external_effects"]["file_published"]


def test_native_checkpoint_callback_drift_blocks_domain_write_and_retains_measured_boundary(prepared):
    env = prepared
    start(env)
    original = env.stack.bpy.ops.ed.undo_push
    calls = []
    def native_push(**kwargs):
        result = original(**kwargs)
        calls.append(True)
        env.manager.context_factory = trap(env)
        return result
    env.stack.bpy.ops.ed.undo_push = native_push
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == env.counts["writes"] == 0
    assert calls == [True] and len(env.stack.frames) == 2
    assert row["error"]["context"]["possible_mutation"]
    assert row["error"]["context"]["checkpoint_bookkeeping"]["native_snapshots_completed"] == 1


def test_guarded_control_retirement_keeps_existing_terminal_limit_without_buffer_history(prepared):
    env = prepared
    controls = []
    for _ in range(34):
        env.flags["phase"] = "admit"
        _, control, _ = start(env)
        controls.append(control)
        assert finish(env)["state"] == "SUCCEEDED"
    assert len(env.manager.history) == env.manager.history.maxlen == 32
    assert all(control.driver is control.prepared is control.work is None for control in controls)
    assert all(job.driver is job.work is None and job.prepared == {} for job in env.manager.history)
    assert env.manager._prepared_unresolved is None and not env.manager._prepared_controls


@pytest.mark.parametrize("field", ["external_effects", "recovery_evidence"])
def test_substituted_evidence_container_never_runs_iteration_and_keeps_last_cache(prepared, field):
    env = prepared
    start(env)
    assert env.manager.tick() and env.manager.tick()
    job = env.manager.active
    class Foreign:
        def __iter__(self):
            env.counts["foreign"] += 1
            raise AssertionError("Foreign evidence iterated")
    setattr(job, field, Foreign())
    before = dict(env.counts)
    assert env.manager.inspect(job.job_id)["external_effects"]["file_published"]
    env.manager.list()
    env.manager.status()
    assert env.counts == before
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts["foreign"] == 0
    assert row["external_effects"]["file_published"]
    assert row["error"]["context"]["possible_mutation"]


@pytest.mark.parametrize("callback", ["context_constructor", "context_require", "permission_require", "permission_source",
                                       "registry_get", "registry_prepare", "state_snapshot", "checkpoint_before", "checkpoint_after"])
def test_known_context_and_service_dependencies_refuse_before_any_foreign_dispatch(prepared, monkeypatch, callback):
    env = prepared
    _, control, _ = start(env)
    foreign = trap(env)
    if callback == "context_constructor":
        monkeypatch.setitem(control.context_getter.__globals__, "ToolContext", foreign)
    elif callback == "context_require":
        monkeypatch.setattr(type(control.context), "require", foreign)
    elif callback == "permission_require":
        monkeypatch.setattr(env.runtime.permissions, "require", foreign)
    elif callback == "permission_source":
        monkeypatch.setattr(env.runtime.permissions, "_source", foreign)
    elif callback == "registry_get":
        monkeypatch.setattr(env.runtime.registry, "get", foreign)
    elif callback == "registry_prepare":
        monkeypatch.setattr(env.runtime.registry, "prepare", foreign)
    elif callback == "state_snapshot":
        monkeypatch.setattr(env.runtime.state, "snapshot", foreign)
    else:
        name = "before_modification" if callback == "checkpoint_before" else "after_modification"
        monkeypatch.setattr(env.runtime.checkpoints, name, foreign)
    before = dict(env.counts)
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts == before
    assert env.counts["foreign"] == env.counts["writes"] == 0


class ForeignDescriptor:
    def __init__(self, counts):
        self.counts = counts

    def __get__(self, _instance, _owner):
        self.counts["foreign"] += 1
        raise AssertionError("Foreign tracked-slot descriptor invoked")


@pytest.mark.parametrize("slot", ["executor_context", "runtime_constructor", "context_constructor"])
def test_tracked_context_descriptor_changes_never_run_get_before_refusal(prepared, monkeypatch, slot):
    env = prepared
    _, control, _ = start(env)
    descriptor = ForeignDescriptor(env.counts)
    if slot == "executor_context":
        monkeypatch.setattr(type(env.runtime.executor), "context", descriptor)
    elif slot == "runtime_constructor":
        monkeypatch.setattr(type(env.runtime), "__init__", descriptor)
    else:
        monkeypatch.setattr(type(control.context), "__init__", descriptor)
    before = dict(env.counts)
    row = finish(env)
    assert row["state"] == "FAILED" and env.counts == before
    assert env.counts["foreign"] == 0


@pytest.mark.parametrize("when", ["capture", "after_observer"])
def test_tracked_history_descriptor_is_never_called_during_capture_or_terminal_tail(prepared, monkeypatch, when):
    env = prepared
    def change():
        monkeypatch.setattr(env.state_module.BridgeState, "record_operation", ForeignDescriptor(env.counts))
    if when == "capture":
        change()
        before = dict(env.counts)
        with pytest.raises(env.jobs.BridgeError):
            start(env)
        assert env.counts == before
    else:
        start(env)
        env.flags["observer"] = change
        row = finish(env)
        assert row["state"] == "FAILED" and row["error"]["context"]["operation_history_unknown"]
        assert row["external_effects"]["file_published"] and row["result"] is None
    assert env.counts["foreign"] == 0


def test_deleted_tracked_recorder_slot_fails_history_without_stranding_owner(prepared, monkeypatch):
    env = prepared
    _, control, lifetime = start(env)
    def remove():
        monkeypatch.delattr(env.state_module.BridgeState, "record_operation")
    env.flags["observer"] = remove
    row = finish(env)
    assert row["state"] == "FAILED" and row["result"] is None
    assert row["error"]["context"]["operation_history_unknown"]
    assert row["external_effects"]["file_published"] and env.counts["writes"] == 1
    assert env.counts["foreign"] == 0 and env.manager.active is None
    assert not lifetime.connection.background_active.is_set()
    assert control.retired and not control.history_attempted and len(env.manager.history) == 1


@pytest.mark.parametrize("changed", ["map", "active", "token"])
def test_final_observer_control_loss_skips_recorder_and_retires_retained_effects(prepared, changed):
    env = prepared
    _, control, _ = start(env)
    def remove():
        if changed == "map":
            env.manager._prepared_controls.clear()
        elif changed == "active":
            env.manager._prepared_active = None
        else:
            env.manager.active._callback_token = object()
    env.flags["observer"] = remove
    row = finish(env)
    assert row["state"] == "FAILED" and row["result"] is None
    assert row["error"]["context"]["operation_history_unknown"]
    assert not control.history_attempted and env.runtime.state.history(1) == []
    assert env.manager.active is None and len(env.manager.history) == 1
    assert row["external_effects"]["file_published"] and env.counts["foreign"] == 0
