"""Canonical queued inspection models; native RNA qualification remains separate.

The actual Runtime, constructor context factory, executor queue, registry,
SourceSeal, Gate and job controller run unchanged. Only native data access,
checkpoint-role facts and OS resource observations are modeled before sealing.
"""
from __future__ import annotations

import importlib
import sys
import time
from types import SimpleNamespace as NS

import pytest
from test_mesh_storage_prepare import environment


@pytest.fixture
def inspection_runtime(addon_package, monkeypatch, request):
    runtime = importlib.import_module(addon_package + ".runtime")
    states = importlib.import_module(addon_package + ".state")
    source = importlib.import_module(addon_package + ".mesh_storage_source")
    primitive = importlib.import_module(addon_package + ".mesh_storage_prepare")
    tools = importlib.import_module(addon_package + ".tools.mesh_storage")
    lifecycle = importlib.import_module(addon_package + ".request_lifecycle")
    protocol = importlib.import_module(addon_package + ".protocol")
    utils = importlib.import_module(addon_package + ".utils")
    reservations = importlib.import_module(addon_package + ".scene_job_reservations")
    native = environment(primitive, monkeypatch)
    env = NS(provider_calls=0, provider_hook=None, scope_reads=0, scope_hook=None,
             binds=0, protected={"pixels": "a" * 64, "material": "original"}, source_walks=0)
    if getattr(request, "param", None) == "count_source_walks":
        original_verify = source.SourceSeal.verify
        def counted_verify(seal):
            env.source_walks += 1
            return original_verify(seal)
        monkeypatch.setattr(source.SourceSeal, "verify", counted_verify)
    if getattr(request, "param", None) == "controlled_clock":
        env.clock = [time.monotonic()]
        monkeypatch.setattr(reservations, "time", NS(monotonic=lambda: env.clock[0]))

    class Preferences:
        def __getattribute__(self, name):
            if name == "allow_inspect_scene":
                env.provider_calls += 1
                hook, env.provider_hook = env.provider_hook, None
                if hook is not None:
                    hook()
            if name.startswith("allow_"):
                return object.__getattribute__(self, "grants").get(name, True)
            return object.__getattribute__(self, name)

    preferences = Preferences()
    preferences.grants = {}
    timers = NS(is_registered=lambda _callback: False, register=lambda *_args, **_kwargs: None)
    scene = object()
    bpy = NS(types=object(), app=NS(build_hash=primitive.BUILD, version=primitive.VERSION,
                 timers=timers, handlers=NS(load_pre=[], undo_pre=[], redo_pre=[])),
             context=NS(screen=None, mode="OBJECT", scene=scene,
                 view_layer=NS(objects=NS(active=native.object_ref)), selected_objects=[native.object_ref],
                 preferences=NS(addons={addon_package: NS(preferences=preferences)})))
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setattr(utils, "bpy", bpy)
    monkeypatch.setattr(runtime, "bpy", bpy)
    monkeypatch.setattr(runtime, "get_state", states.BridgeState)

    class Read:
        def __init__(self, gate):
            self.gate = gate

        def call(self, function, *args):
            self.gate.pure()
            result = function(*args)
            self.gate.pure()
            return result

        def raw(self, owner, name):
            return self.call(getattr, owner, name)

        def active(self, layer):
            return self.raw(layer.objects, "active")

        def bounded(self, values, maximum, _label):
            result = self.call(tuple, values)
            assert len(result) <= maximum
            return result

        def identity(self, owner, kind):
            self.gate.pure()
            return kind, str(id(owner))

    Read.__module__ = source.__name__
    monkeypatch.setattr(source, "_ModeledInspectionRead", Read, raising=False)

    class Roles:
        def __init__(self, _bpy, metadata, gate):
            self.gate, self.obj, self.mesh = gate, metadata.obj, metadata.mesh
            self.access = Read(gate)
            self.phase, self.native_push_completed = 0, False
            self.initial_roles, self.identities = (0, None), (("Scene", "1"),)
            self.origin = self.memberships = self.before_readback = self.last_readback = self.after_readback = None
            self.bound_digest = None

        def check_identity(self, origin=None):
            if origin is not self.origin:
                raise source.contract.refused("MODELED_ROLE_ORIGIN_CHANGED")

        def check_after_read(self):
            self.gate.pure()

        def bind_protected(self, facts):
            self.gate.pure()
            env.binds += 1
            self.bound_digest, self.origin = source.contract.digest(facts), object()

        def report(self):
            return {"modeled_native_roles": True, "native_push_completed": False}

    Roles.__module__ = source.__name__

    def protected(_bpy, _metadata, gate, _bindings, _excluded, *, checkpoint_roles):
        gate.pure()
        env.scope_reads += 1
        checkpoint_roles.memberships = 1
        checkpoint_roles.last_readback = {"refs": 1, "weak": False}
        if checkpoint_roles.before_readback is None:
            checkpoint_roles.before_readback = checkpoint_roles.last_readback
        if env.scope_hook is not None:
            env.scope_hook()
        gate.pure()
        return dict(env.protected)

    monkeypatch.setattr(source, "CheckpointRoles", Roles)
    monkeypatch.setattr(source, "protected_facts", protected)
    monkeypatch.setattr(source, "available_memory_facts", lambda: {"available_memory_bytes": 2 * 1024**3})
    monkeypatch.setattr(primitive, "qualify_collection_bindings", lambda *_args, **_kwargs: native.bindings)
    owner = runtime.BridgeRuntime()
    monkeypatch.setattr(runtime, "_RUNTIME", owner)
    owner.register()
    tools.register_private(owner.registry)
    owner.registry.enable_toolset("geometry")
    connection = lifecycle.ConnectionLifetime()
    parameters = {"object_name": "Object", "mesh_name": "Mesh", "attribute_names": list(native.attrs)}
    counter = [0]

    def call(method=None, params=None, *, delivered=True):
        counter[0] += 1
        lifetime = lifecycle.RequestLifetime(connection, float("inf"))
        request = protocol.Request("inspection-" + str(counter[0]),
            tools.contract.INSPECTION_START if method is None else method,
            dict(parameters) if params is None else params, _lifecycle=lifetime)
        queued = owner.executor.submit(request, timeout=60.)
        owner.executor._drain_timer()
        assert queued.completed.is_set() and queued.response is not None
        if delivered:
            lifetime.acknowledge(queued.response.ok)
        return NS(response=queued.response, lifetime=lifetime, job=owner.jobs.active)

    def drain():
        for _ in range(8):
            if not owner.jobs.tick():
                return owner.jobs.history[0].summary()
        pytest.fail("Inspection did not terminate in a finite number of turns")

    env.runtime, env.owner, env.tools, env.source = runtime, owner, tools, source
    env.native, env.preferences, env.connection, env.bpy = native, preferences, connection, bpy
    env.call, env.drain = call, drain
    yield env
    owner.jobs.cancel_all("inspection model teardown")


def test_queued_start_defers_all_native_work_until_delivery(inspection_runtime):
    e = inspection_runtime
    accepted = e.call(delivered=False)
    assert accepted.response.ok, accepted.response.error
    assert accepted.response.result["inspection_only"] is True
    assert accepted.response.result["ready"] is False
    assert accepted.response.result["result"] is None
    for _ in range(2):
        assert e.owner.jobs.tick()
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0
    accepted.lifetime.acknowledge(True)
    terminal = e.drain()
    assert terminal["state"] == "SUCCEEDED", terminal
    assert terminal["ready"] is True and terminal["result"]["write_authorized"] is False
    assert e.scope_reads == 2 and e.binds == 1 and e.native.writes == 0
    assert all(row.storage == "SINGLE" for row in e.native.attrs.values())
    assert not e.owner.checkpoints._undo_steps
    assert e.owner.registry.executing_mutators == 0


def test_one_native_inspection_phase_per_real_controller_tick(inspection_runtime):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    phases = []
    for _ in range(4):
        active = e.owner.jobs.tick()
        phases.append(e.owner.jobs.inspect(accepted.job.job_id)["phase"])
        if not active:
            break
    assert phases[:3] == ["inspection_capture", "inspection_seal", "inspection_complete"]
    assert e.native.writes == 0


@pytest.mark.parametrize("control", ["cancel", "disconnect", "deadline", "emergency", "permission"])
def test_stopped_owner_never_enters_next_native_phase(inspection_runtime, control):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    if control == "cancel":
        e.owner.jobs.cancel(accepted.job.job_id)
    elif control == "disconnect":
        e.connection.disconnected.set()
    elif control == "deadline":
        accepted.job.deadline = 0.
    elif control == "emergency":
        e.owner.state.set_emergency_stopped(True)
    else:
        e.preferences.grants["allow_edit_mesh"] = False
    terminal = e.drain()
    assert terminal["state"] in {"FAILED", "CANCELLED"}
    assert terminal["ready"] is False and terminal["result"] is None
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0


def test_pause_preserves_owner_without_reading_then_resumes(inspection_runtime):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    e.owner.state.set_paused(True)
    assert e.owner.jobs.tick()
    assert accepted.job.state == "PAUSED"
    assert e.native.snapshot_reads == e.scope_reads == 0
    e.owner.state.set_paused(False)
    assert e.drain()["state"] == "SUCCEEDED"


def test_final_full_scope_drift_never_rebases_ready_evidence(inspection_runtime):
    e = inspection_runtime
    assert e.call().response.ok
    assert e.owner.jobs.tick() and e.owner.jobs.tick()
    e.protected["pixels"] = "manually changed"
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert terminal["result"] is None and e.scope_reads == 2 and e.binds == 0


def test_context_factory_substitution_is_refused_before_callback(inspection_runtime):
    e = inspection_runtime
    assert e.call().response.ok
    calls = []
    e.owner.jobs.context_factory = lambda: calls.append("foreign factory")
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and calls == []
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0


def test_provider_cannot_replace_driver_phase_before_native_entry(inspection_runtime):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    e.provider_hook = lambda: setattr(accepted.job.driver, "phase", "inspection_seal")
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0


def test_wire_cannot_invoke_private_inspection_turn(inspection_runtime):
    e = inspection_runtime
    accepted = e.call(delivered=False)
    assert accepted.response.ok, accepted.response.error
    attempted = e.call("jobs._inspection_turn", {})
    assert not attempted.response.ok
    assert e.owner.jobs.active is accepted.job
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0


@pytest.mark.parametrize("name", ["_inspection_function", "_InspectionAdmission"])
def test_registration_seal_precedes_mutable_core_helper_dispatch(inspection_runtime, monkeypatch, name):
    e = inspection_runtime
    core = importlib.import_module(e.runtime.__package__ + ".scene_jobs")
    calls = []
    monkeypatch.setattr(core, name, lambda *_args, **_kwargs: calls.append(name))
    result = e.call()
    assert not result.response.ok and result.job is None
    assert calls == []
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0


def test_permission_provider_cannot_dispatch_replaced_entry_guard(inspection_runtime):
    e = inspection_runtime
    calls = []

    def replace_guard():
        entry = e.owner.registry._mutation_interlock._entries[-1]
        callback = entry.context.checkpoint_admission.callback
        object.__setattr__(callback, "entry_guard", lambda: calls.append("foreign guard"))

    e.provider_hook = replace_guard
    result = e.call()
    assert not result.response.ok and result.job is None
    assert calls == []
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0


def test_native_read_cannot_replace_driver_top_level_fields(inspection_runtime):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    assert e.owner.jobs.tick()
    e.scope_hook = lambda: setattr(accepted.job.driver, "protected_bytes", b"foreign")
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert terminal["result"] is None and e.binds == e.native.writes == 0


@pytest.mark.parametrize("field", ["mode", "scene", "active", "selection"])
def test_original_native_context_drift_is_stale_before_scope_read(inspection_runtime, field):
    e = inspection_runtime
    assert e.call().response.ok
    assert e.owner.jobs.tick()
    if field == "mode":
        e.bpy.context.mode = "EDIT_MESH"
    elif field == "scene":
        e.bpy.context.scene = object()
    elif field == "active":
        e.bpy.context.view_layer.objects.active = None
    else:
        e.bpy.context.selected_objects.clear()
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert terminal["error"]["context"]["inspection_status"] == "STALE"
    assert terminal["result"] is None and e.scope_reads == e.binds == e.native.writes == 0


def test_inspection_turn_is_one_use_and_never_a_scene_writer(inspection_runtime):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    jobs, service, registry = e.owner.jobs, e.owner.jobs.reservations, e.owner.registry
    with service.scheduler_scope(accepted.job.reservation) as origin:
        context = jobs._context(accepted.job)
        token = service.issue_inspection_turn(accepted.job.reservation, accepted.job.phase,
            accepted.job.revision, origin=origin, check_only=True)
        try:
            with pytest.raises(e.runtime.BridgeError):
                registry.invoke_scene_turn(token, {}, context, e.owner.checkpoints, check_only=True)
            assert registry.invoke_inspection_turn(token, {}, context, check_only=True) is None
            with pytest.raises(e.runtime.BridgeError):
                registry.invoke_inspection_turn(token, {}, context, check_only=True)
        finally:
            service.close_inspection_turn(token)
    assert e.native.snapshot_reads == e.scope_reads == e.binds == e.native.writes == 0
    assert not e.owner.checkpoints._undo_steps


def test_reservation_receipt_alone_cannot_issue_inspection_turn(inspection_runtime):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    job, service = accepted.job, e.owner.jobs.reservations
    with pytest.raises(e.runtime.BridgeError) as failure:
        service.issue_inspection_turn(job.reservation, job.phase, job.revision)
    assert failure.value.context["reason"] == "INVALID_SCENE_SCHEDULER_ORIGIN"
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0


@pytest.mark.parametrize("field", ["authority", "driver", "state_origin", "params", "allowlist"])
def test_permission_provider_cannot_replace_admission_owned_fields(inspection_runtime, field):
    e = inspection_runtime
    calls = []

    class Foreign:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError("Foreign admission field was dispatched")

        def __iter__(self):
            calls.append("iteration")
            raise AssertionError("Foreign admission field was iterated")

    foreign = Foreign()

    def replace_field():
        entry = e.owner.registry._mutation_interlock._entries[-1]
        object.__setattr__(entry.context.checkpoint_admission.callback, field, foreign)

    e.provider_hook = replace_field
    result = e.call()
    assert not result.response.ok and result.job is None
    assert calls == []
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0


def test_native_callback_cannot_dispatch_replaced_turn_entry_guard(inspection_runtime):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    assert e.owner.jobs.tick()
    calls = []

    def replace_guard():
        entry = e.owner.registry._mutation_interlock._entries[-1]
        callback = entry.context.checkpoint_admission.callback
        object.__setattr__(callback, "entry_guard", lambda: calls.append("foreign turn guard"))

    e.scope_hook = replace_guard
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert calls == [] and e.binds == e.native.writes == 0


def test_native_callback_cannot_transplant_foreign_turn_entry_proof(inspection_runtime):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    assert e.owner.jobs.tick()
    calls = []

    def replace_proof():
        service = e.owner.jobs.reservations
        row = next(iter(service._inspection_turns.values()))

        def function():
            calls.append("foreign turn proof")

        row.inspection_entry_proof = (function, function.__code__, function.__globals__, function.__defaults__,
            function.__kwdefaults__, function.__closure__,
            tuple((cell, cell.cell_contents) for cell in function.__closure__ or ()))

    e.scope_hook = replace_proof
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert calls == [] and e.binds == e.native.writes == 0


@pytest.mark.parametrize("field", ["handler", "checkpoint_admission_factory", "permissions", "modifies",
                                    "automatic_checkpoint", "toolset"])
def test_accepted_start_spec_replacement_denies_before_next_phase(inspection_runtime, field):
    e = inspection_runtime
    assert e.call().response.ok
    calls = []
    values = {"handler": lambda *_args: calls.append("foreign handler"),
              "checkpoint_admission_factory": lambda *_args: calls.append("foreign admission"),
              "permissions": frozenset(), "modifies": True, "automatic_checkpoint": True, "toolset": "core"}
    spec = e.owner.registry.get(e.tools.contract.INSPECTION_START)
    object.__setattr__(spec, field, values[field])
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert calls == []
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0


def test_permission_source_replacement_denies_before_dispatch(inspection_runtime):
    e = inspection_runtime
    assert e.call().response.ok
    calls = []
    e.owner.permissions._source = lambda: calls.append("foreign source")
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert calls == []
    assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0


def test_requested_absolute_deadline_is_frozen_at_acceptance(inspection_runtime):
    e = inspection_runtime
    parameters = {"object_name": "Object", "mesh_name": "Mesh", "attribute_names": list(e.native.attrs),
                  "time_limit_seconds": 17.}
    before = time.monotonic()
    accepted = e.call(params=parameters)
    after = time.monotonic()
    assert accepted.response.ok, accepted.response.error
    deadline = accepted.job.deadline
    assert before + 17. <= deadline <= after + 17.
    assert e.owner.jobs.tick()
    assert accepted.job.deadline is deadline


@pytest.mark.parametrize("inspection_runtime", ["controlled_clock"], indirect=True)
@pytest.mark.parametrize("boundary", ["provider", "native_read"])
def test_each_inspection_turn_keeps_original_sixty_second_limit(inspection_runtime, boundary):
    e = inspection_runtime
    parameters = {"object_name": "Object", "mesh_name": "Mesh", "attribute_names": list(e.native.attrs),
                  "time_limit_seconds": 300.}
    accepted = e.call(params=parameters)
    assert accepted.response.ok, accepted.response.error

    def exceed_turn_limit():
        e.clock[0] += 61.

    if boundary == "provider":
        e.provider_hook = exceed_turn_limit
    else:
        assert e.owner.jobs.tick()
        e.scope_hook = exceed_turn_limit
    terminal = e.drain()
    assert terminal["state"] in {"FAILED", "CANCELLED"} and terminal["ready"] is False
    assert terminal["error"]["context"]["inspection_status"] == "INCOMPLETE"
    assert terminal["result"] is None and e.binds == e.native.writes == 0
    assert e.scope_reads == (1 if boundary == "native_read" else 0)


def test_private_turn_does_not_change_ordinary_runtime_metadata(inspection_runtime):
    e = inspection_runtime
    assert "jobs._inspection_turn" not in e.owner.registry._tools
    assert e.owner.jobs._inspection_spec is None
    assert e.call().response.ok
    assert e.owner.registry.get("jobs._inspection_turn").remote is False


def test_inspection_start_and_turn_never_acquire_native_push_consumer(inspection_runtime):
    e = inspection_runtime
    completion = importlib.import_module(e.runtime.__package__ + ".checkpoint_completion")
    observed = []
    e.provider_hook = lambda: observed.append(len(completion._consumers))
    assert e.call().response.ok
    e.scope_hook = lambda: observed.append(len(completion._consumers))
    assert e.drain()["ready"] is True
    assert observed and observed == [0] * len(observed)


def test_foreign_permission_source_is_not_adopted_at_first_start(inspection_runtime):
    e = inspection_runtime
    calls = []
    e.owner.permissions._source = lambda: calls.append("foreign provider")
    accepted = e.call()
    assert accepted.response.ok is False
    assert calls == [] and e.native.snapshot_reads == e.scope_reads == 0


@pytest.mark.parametrize("drift", ["disconnect", "epoch", "provider", "spec", "source", "runtime_stop"])
def test_cached_ready_proof_invalidates_without_live_callbacks(inspection_runtime, monkeypatch, drift):
    e = inspection_runtime
    accepted = e.call()
    terminal = e.drain()
    assert terminal["ready"] is True
    result = terminal["result"]
    assert result["cached_at_completion"] is True
    assert result["native_state_revalidated"] is result["permission_values_revalidated"] is False
    assert result["write_authorized"] is result["writer_handoff_supported"] is False
    before = e.provider_calls, e.scope_reads, e.native.snapshot_reads, e.native.writes
    calls = []
    if drift == "disconnect":
        e.connection.disconnected.set()
    elif drift == "epoch":
        accepted.job.state_origin[1].evidence_epoch += 1
    elif drift == "provider":
        e.owner.permissions._source = lambda: calls.append("foreign provider")
    elif drift == "spec":
        spec = e.owner.registry.get(e.tools.contract.INSPECTION_START)
        object.__setattr__(spec, "handler", lambda *_args: calls.append("foreign handler"))
    elif drift == "source":
        monkeypatch.setattr(e.source, "build_plan", lambda *_args: calls.append("foreign source"))
    else:
        e.owner.jobs.cancel_all("native undo/redo")
    report = e.owner.jobs.inspect(accepted.job.job_id)
    assert report["ready"] is False and report["result"] is None
    assert report["invalidated_reason"]
    assert e.owner.jobs.list()["jobs"][0]["ready"] is False
    assert (e.provider_calls, e.scope_reads, e.native.snapshot_reads, e.native.writes) == before
    assert calls == []


@pytest.mark.parametrize("target", ["object", "deque", "condition"])
def test_stopped_terminal_uses_no_replaceable_callback(inspection_runtime, monkeypatch, target):
    e = inspection_runtime
    assert e.call().response.ok
    assert e.owner.jobs.tick()
    calls = []
    scene_jobs = importlib.import_module(e.runtime.__package__ + ".scene_jobs")

    class ForeignCondition:
        def __enter__(self):
            calls.append("foreign condition")

        def __exit__(self, *_args):
            calls.append("foreign condition exit")

    def poison():
        if target == "condition":
            e.connection.background_active._cond = ForeignCondition()
        elif target == "object":
            monkeypatch.setattr(scene_jobs, "object", NS(__getattribute__=lambda *_args: calls.append("foreign object")), raising=False)
        else:
            monkeypatch.setattr(scene_jobs, "deque", NS(appendleft=lambda *_args: calls.append("foreign deque")))

    e.scope_hook = poison
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert calls == [] and e.owner.jobs.active is None


def test_terminal_error_copy_rejects_foreign_metaclass_without_hash(inspection_runtime):
    e = inspection_runtime
    errors = importlib.import_module(e.runtime.__package__ + ".errors")
    assert e.call().response.ok
    assert e.owner.jobs.tick()
    calls = []

    class ForeignMeta(type):
        def __hash__(cls):
            calls.append("foreign class hash")
            return 1

    class Foreign(metaclass=ForeignMeta):
        pass

    def stop():
        raise errors.BridgeError("OPERATION_FAILED", "Original stop", {"foreign": Foreign()})

    e.scope_hook = stop
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["error"]["code"] == "OPERATION_FAILED"
    assert terminal["error"]["context"]["original_error_context_invalid"] is True
    assert calls == []


@pytest.mark.parametrize("boundary", ["provider", "native"])
@pytest.mark.parametrize("owner", ["state", "permissions", "permission_view"])
def test_owned_service_method_shadow_denies_before_foreign_dispatch(inspection_runtime, boundary, owner):
    e = inspection_runtime
    assert e.call().response.ok
    calls = []

    def poison():
        if owner == "state":
            e.owner.state.snapshot = lambda: calls.append("foreign state")
        elif owner == "permissions":
            e.owner.permissions.snapshot = lambda: calls.append("foreign permissions")
        else:
            row = next(iter(e.owner.jobs.reservations._inspection_turns.values()))
            row.context.permissions.require = lambda *_args: calls.append("foreign permission view")

    if boundary == "provider":
        e.provider_hook = poison
    else:
        assert e.owner.jobs.tick()
        e.scope_hook = poison
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert calls == [] and e.native.writes == 0


@pytest.mark.parametrize("target", ["turn_table", "proof_table", "row"])
def test_native_table_or_row_substitution_calls_no_foreign_accessor(inspection_runtime, target):
    e = inspection_runtime
    assert e.call().response.ok
    assert e.owner.jobs.tick()
    calls = []

    class Foreign:
        def get(self, *_args):
            calls.append("foreign get")

        def values(self):
            calls.append("foreign values")
            return ()

        @property
        def context(self):
            calls.append("foreign row context")

        @property
        def token(self):
            calls.append("foreign row token")

    def poison():
        service = e.owner.jobs.reservations
        if target == "turn_table":
            service._inspection_turns = Foreign()
        elif target == "proof_table":
            service._inspection_proofs = Foreign()
        else:
            key = next(iter(service._inspection_turns))
            service._inspection_turns[key] = Foreign()

    e.scope_hook = poison
    terminal = e.drain()
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert calls == [] and e.scope_reads == 1 and e.binds == e.native.writes == 0


@pytest.mark.parametrize("inspection_runtime", ["count_source_walks"], indirect=True)
@pytest.mark.parametrize("boundary", ["start", "turn", "record"])
def test_inspection_guard_consolidates_only_its_own_complete_source_walk(inspection_runtime, boundary):
    e, counts = inspection_runtime, []

    def count_entry():
        entry = e.owner.registry._mutation_interlock._entries[-1]
        callback = entry.context.checkpoint_admission.callback
        before = e.source_walks
        callback.entry_guard()
        counts.append(e.source_walks - before)

    if boundary == "start":
        e.provider_hook = count_entry
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    if boundary == "turn":
        e.provider_hook = count_entry
        assert e.owner.jobs.tick()
    elif boundary == "record":
        before = e.source_walks
        record = e.owner.jobs._inspection_record(accepted.job)
        counts.append(e.source_walks - before)
        assert record[0] is accepted.job
    assert counts == [1]
    assert e.native.writes == 0 and e.scope_reads == 0


@pytest.mark.parametrize("target", ["turn", "owner"])
def test_checked_turn_rejects_owner_class_drift_before_foreign_access(inspection_runtime, target):
    e = inspection_runtime
    assert e.call().response.ok
    assert e.owner.jobs.tick()
    calls, failures = [], []

    def poison():
        row = next(iter(e.owner.jobs.reservations._inspection_turns.values()))
        callback = row.context.checkpoint_admission.callback
        value = row if target == "turn" else row.owner
        original = type(value)
        class Foreign(original):
            __slots__ = ()

            def __getattribute__(self, name):
                calls.append(name)
                raise AssertionError("Foreign turn owner was accessed")

            def __hash__(self):
                calls.append("hash")
                raise AssertionError("Foreign turn owner was hashed")

            def __eq__(self, _other):
                calls.append("equality")
                raise AssertionError("Foreign turn owner was compared")

        object.__setattr__(value, "__class__", Foreign)
        try:
            with pytest.raises(e.runtime.BridgeError) as caught:
                callback.entry_guard()
            failures.append(caught.value)
            assert calls == []
        finally:
            object.__setattr__(value, "__class__", original)
        raise failures[-1]

    e.scope_hook = poison
    terminal = e.drain()
    assert len(failures) == 1 and calls == []
    assert terminal["state"] == "FAILED" and terminal["ready"] is False
    assert e.scope_reads == 1 and e.binds == e.native.writes == 0


@pytest.mark.parametrize("target", ["registry", "jobs", "glb_stage"])
def test_standalone_record_refuses_owned_method_shadow_before_dispatch(inspection_runtime, target):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    jobs, calls = e.owner.jobs, []
    record = type(jobs)._inspection_record
    owner, name = {
        "registry": (e.owner.registry, "get"),
        "jobs": (jobs, "_inspection_record"),
        "glb_stage": (e.owner.glb_stage, "check_context_factory"),
    }[target]
    setattr(owner, name, lambda *_args, **_kwargs: calls.append("foreign method"))
    try:
        with pytest.raises(e.runtime.BridgeError):
            record(jobs, accepted.job)
        assert calls == []
        assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0
    finally:
        delattr(owner, name)


@pytest.mark.parametrize("leaf", ["context", "driver", "factory", "record"])
@pytest.mark.parametrize("change", ["identity", "code"])
@pytest.mark.parametrize("boundary", ["provider", "native"])
def test_held_inspection_leaf_drift_refuses_before_dispatch(inspection_runtime, monkeypatch, leaf, change, boundary):
    e, calls = inspection_runtime, []
    core = importlib.import_module(e.runtime.__package__ + ".scene_jobs")
    module, name = {
        "context": (e.source, "_verify_context_fields"),
        "driver": (core, "_inspection_driver_fields"),
        "factory": (core, "_inspection_context_factory_fields"),
        "record": (core.SceneJobs, "_inspection_record_fields"),
    }[leaf]
    original = getattr(module, name)

    def foreign(*_args, **_kwargs):
        calls.append("foreign leaf")
        raise AssertionError("Foreign inspection leaf executed")

    def poison():
        if change == "identity":
            monkeypatch.setattr(module, name, foreign)
        else:
            monkeypatch.setattr(original, "__code__", original.__code__.replace(co_name="changed"))

    if boundary == "provider":
        e.provider_hook = poison
        result = e.call()
        assert not result.response.ok and result.job is None
        assert e.native.snapshot_reads == e.scope_reads == 0
    else:
        assert e.call().response.ok
        assert e.owner.jobs.tick()
        e.scope_hook = poison
        terminal = e.drain()
        assert terminal["state"] == "FAILED" and terminal["ready"] is False
        assert e.scope_reads == 1 and e.binds == 0
    assert calls == [] and e.native.writes == 0


def test_standalone_record_rejects_service_class_before_foreign_access(inspection_runtime):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    jobs, calls = e.owner.jobs, []
    original = type(jobs)
    record = original._inspection_record
    class Foreign(original):
        __slots__ = ()

        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError("Foreign job service was accessed")

        def __hash__(self):
            calls.append("hash")
            raise AssertionError("Foreign job service was hashed")

        def __eq__(self, _other):
            calls.append("equality")
            raise AssertionError("Foreign job service was compared")

    object.__setattr__(jobs, "__class__", Foreign)
    try:
        with pytest.raises(e.runtime.BridgeError):
            record(jobs, accepted.job)
        assert calls == []
        assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0
    finally:
        object.__setattr__(jobs, "__class__", original)


@pytest.mark.parametrize("target", ["records", "tools"])
def test_standalone_record_rejects_foreign_table_key_before_collision(inspection_runtime, target):
    e = inspection_runtime
    accepted = e.call()
    assert accepted.response.ok, accepted.response.error
    jobs, calls = e.owner.jobs, []
    record = type(jobs)._inspection_record
    core = importlib.import_module(e.runtime.__package__ + ".scene_jobs")
    table, key = ((jobs._inspection_records, id(accepted.job)) if target == "records"
                  else (e.owner.registry._tools, core.INSPECTION_TURN_METHOD))
    original = dict(table)
    value = table.pop(key)
    collision_hash = hash(key)
    class ForeignKey:
        def __hash__(self):
            calls.append("hash")
            return collision_hash

        def __eq__(self, _other):
            calls.append("equality")
            raise AssertionError("Foreign lookup key was compared")

    table[ForeignKey()] = value
    calls.clear()  # Dictionary construction hashes the intentionally bad key.
    try:
        with pytest.raises(e.runtime.BridgeError):
            record(jobs, accepted.job)
        assert calls == []
        assert e.native.snapshot_reads == e.scope_reads == e.native.writes == 0
    finally:
        table.clear()
        table.update(original)
