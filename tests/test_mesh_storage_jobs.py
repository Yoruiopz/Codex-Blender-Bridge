"""Real Scene scheduler plus the unchanged, native-shaped preparation helper.

Only native metadata/RNA bindings, logical dependency reads and OS resources are
modeled. This executes production authorization, Scene turns, journals, helper
conversion/readback, forward CAS, history, cancellation and recovery routing.
"""
import importlib
from types import SimpleNamespace as NS

import pytest
from test_mesh_storage_prepare import environment
from test_scene_jobs import drain, scene_jobs  # noqa: F401

pytestmark = [pytest.mark.usefixtures("scene_job_manager"),
              pytest.mark.parametrize("scene_job_manager", ("scene", "native_save"))]


@pytest.fixture
def storage_job(scene_jobs, addon_package, monkeypatch):  # noqa: F811 - imported pytest fixture
    env = scene_jobs
    primitive = importlib.import_module(addon_package + ".mesh_storage_prepare")
    source = importlib.import_module(addon_package + ".mesh_storage_source")
    tools = importlib.import_module(addon_package + ".tools.mesh_storage")
    native = environment(primitive, monkeypatch)
    bpy = NS(types=object(), app=NS(build_hash=primitive.BUILD, version=primitive.VERSION))
    native.protected = {"complete_pixels": "a" * 64, "material_binding": "source"}
    native.memory = {"available_memory_bytes": 2 * 1024**3}
    native.foreign_verifier_calls = []
    native.scope = {"deny": False}
    native.scope_calls = []
    monkeypatch.setattr(source, "_foreign_verifier_calls", native.foreign_verifier_calls, raising=False)

    def protected(_bpy, _metadata, gate, _bindings, excluded, *, checkpoint_roles=None):
        gate.pure()
        return {**native.protected, "original_ARRAY_payloads": {
            name: tuple(value.values) for name, value in native.attrs.items()
            if value.storage == "ARRAY" and name not in excluded}}

    def affected(_context, _bpy, objects):
        native.scope_calls.append(objects)
        assert objects == (native.object_ref,)
        if native.scope["deny"]:
            raise tools.contract.refused("MODELED_PROTECTED_TARGET")

    monkeypatch.setattr(source, "protected_facts", protected)
    class ModeledRoles:
        """Model native roles only; actual canonical completion remains real."""
        def __init__(self, _bpy, _metadata, gate):
            self.gate, self.origin, self.bound_digest, self.completed = gate, None, None, False
        def bind_protected(self, facts):
            self.bound_digest = source.contract.digest(facts)
            self.origin = (self, self)
        def check_identity(self, origin=None):
            if origin is not None and origin is not self.origin:
                raise source.contract.refused("MODELED_ROLE_ORIGIN_CHANGED")
        def check_after_read(self):
            self.gate.pure()
        def after_native_push(self, origin):
            self.check_identity(origin)
            completion = importlib.import_module(addon_package + ".checkpoint_completion")
            completion.claim_native_push_delegate(self)
            self.completed = True
        def verified(self, digest):
            assert digest == self.bound_digest
        def report(self):
            return {"modeled_native_roles": True, "native_push_completed": self.completed}
    ModeledRoles.__module__ = source.__name__
    monkeypatch.setattr(source, "CheckpointRoles", ModeledRoles)
    monkeypatch.setattr(source, "available_memory_facts", lambda: dict(native.memory))
    monkeypatch.setattr(primitive, "qualify_collection_bindings", lambda *args, **kwargs: native.bindings)
    monkeypatch.setattr(tools, "require_blender", lambda: bpy)
    monkeypatch.setattr(tools, "check_affected", affected)
    tools.register_private(env.registry)
    env.registry.enable_toolset("geometry")
    connection = env.lifecycle.ConnectionLifetime()
    counter = [0]

    def call(method, params, *, delivered=True):
        counter[0] += 1
        owner = env.lifecycle.RequestLifetime(connection, float("inf"))
        if delivered:
            owner.acknowledge(True)
        request = env.protocol.Request(f"storage-{counter[0]}", method, params, _lifecycle=owner)
        return env.executor.execute_request(request), owner

    parameters = {"object_name": "Object", "mesh_name": "Mesh", "attribute_names": list(native.attrs)}

    def preview():
        response, _ = call(tools.contract.PREVIEW, dict(parameters))
        assert response.ok, response.error
        return response.result

    def start(proof=None, *, delivered=True):
        proof = preview() if proof is None else proof
        response, owner = call(tools.contract.START, {**parameters,
            "expected_preparation_fingerprint": proof["expected_preparation_fingerprint"],
            "confirm_materialize_storage": True, "confirm_retained_partial_preparation": True}, delivered=delivered)
        return NS(response=response, owner=owner, job=env.manager.active)

    return NS(env=env, native=native, tools=tools, source=source, primitive=primitive,
              parameters=parameters, preview=preview, start=start, call=call, connection=connection)


def one_materialization(storage):
    for _ in range(10):
        storage.env.manager.tick()
        if storage.native.writes:
            return
    pytest.fail("No materialization in bounded scheduler turns")


def test_two_attributes_materialize_in_distinct_real_scene_turns(storage_job):
    s = storage_job
    accepted = s.start()
    assert accepted.response.ok, accepted.response.error
    assert s.native.writes == 0
    prior = 0
    for _ in range(10):
        active = s.env.manager.tick()
        assert 0 <= s.native.writes - prior <= 1
        prior = s.native.writes
        if not active:
            break
    assert s.env.manager.active is None
    terminal = s.env.manager.history[0].summary()
    assert terminal["state"] == "SUCCEEDED", terminal
    assert s.native.writes == 2 and s.native.entered_names == list(s.native.attrs)
    assert all(row.storage == "ARRAY" for row in s.native.attrs.values())
    assert terminal["result"]["completed_attributes"] == 2
    assert terminal["result"]["protected_logical_state_verified"] is True
    assert terminal["result"]["independent_SINGLE_pre_value_hash"] is False


def test_storage_owner_waits_for_delivery_then_cancels_without_native_entry(storage_job):
    s = storage_job
    accepted = s.start(delivered=False)
    assert accepted.response.ok, accepted.response.error
    for _ in range(3):
        assert s.env.manager.tick()
    assert s.native.writes == 0
    s.env.manager.cancel(accepted.job.job_id)
    assert drain(s.env)["state"] == "CANCELLED"
    assert s.native.writes == 0


def test_stale_preview_cannot_be_rebased_by_start(storage_job):
    s = storage_job
    proof = s.preview()
    s.native.attrs["UV"].count += 1
    result = s.start(proof)
    assert not result.response.ok and result.job is None
    assert s.native.writes == 0


@pytest.mark.parametrize("drift", ["completed_pixels", "protected_material", "mesh_topology"])
def test_late_manual_changes_stop_without_second_conversion(storage_job, drift):
    s = storage_job
    assert s.start().response.ok
    one_materialization(s)
    if drift == "completed_pixels":
        s.native.attrs["UV"].values = ((.25, .5),) * s.native.attrs["UV"].count
    elif drift == "protected_material":
        s.native.protected["material_binding"] = "manually replaced"
    else:
        s.native.attrs[".uv_select_face"].count = 2
    terminal = drain(s.env)
    assert terminal["state"] == "FAILED"
    assert s.native.writes == 1 and s.native.attrs[".uv_select_face"].storage == "SINGLE"


def test_live_permission_revoke_retains_first_conversion_and_stops(storage_job):
    s = storage_job
    assert s.start().response.ok
    one_materialization(s)
    s.env.grants["EDIT_MESH"] = False
    terminal = drain(s.env)
    assert terminal["state"] == "FAILED"
    assert s.native.writes == 1


def test_native_exception_after_transition_retains_unknown_partial_journal(storage_job):
    s = storage_job
    assert s.start().response.ok
    s.native.fail = "after_materialization"
    terminal = drain(s.env)
    assert terminal["state"] == "FAILED"
    assert s.native.writes == 1 and s.native.attrs["UV"].storage == "ARRAY"
    rows = terminal["storage_effects"]["rows"]
    assert rows[0]["materialize_entered"] is True
    assert rows[0]["materialize_returned"] is False


def test_pause_has_no_new_preparation_and_resume_preserves_same_owner(storage_job):
    s = storage_job
    accepted = s.start()
    assert accepted.response.ok
    one_materialization(s)
    s.env.state.paused = True
    for _ in range(3):
        assert s.env.manager.tick()
    assert s.native.writes == 1 and s.env.manager.active is accepted.job
    s.env.state.paused = False
    assert drain(s.env)["state"] == "SUCCEEDED"
    assert s.native.writes == 2


@pytest.mark.parametrize("change", ["verify_binding", "verify_code", "pure_binding", "pure_code", "gate_lookup"])
def test_preview_provider_cannot_bootstrap_a_replaced_verifier(storage_job, monkeypatch, change):
    s = storage_job
    calls = s.native.foreign_verifier_calls
    namespace = {}
    exec('def foreign(self):\n _foreign_verifier_calls.append("foreign")\n raise AssertionError("foreign verifier")', namespace)
    foreign = namespace["foreign"]
    baseline = s.env.provider_calls

    def alter():
        if s.env.provider_calls - baseline < 2:
            s.env.provider_hook = alter
            return
        if change == "verify_binding":
            monkeypatch.setattr(s.source.SourceSeal, "verify", foreign)
        elif change == "verify_code":
            monkeypatch.setattr(s.source.SourceSeal.verify, "__code__", foreign.__code__)
        elif change == "pure_binding":
            monkeypatch.setattr(s.source.Gate, "pure", foreign)
        elif change == "pure_code":
            monkeypatch.setattr(s.source.Gate.pure, "__code__", foreign.__code__)
        else:
            monkeypatch.setattr(s.source.Gate, "__getattribute__", foreign)
    s.env.provider_hook = alter
    response, _ = s.call(s.tools.contract.PREVIEW, dict(s.parameters))
    assert not response.ok and response.error["context"]["reason"] == "STORAGE_SOURCE_CHANGED"
    assert calls == [] and s.native.snapshot_reads == s.native.writes == 0


def test_live_memory_pressure_stops_before_another_native_read(storage_job):
    s = storage_job
    assert s.start().response.ok
    one_materialization(s)
    before = s.native.snapshot_reads
    s.native.memory["available_memory_bytes"] = 0
    terminal = drain(s.env)
    assert terminal["state"] == "FAILED"
    assert s.native.writes == 1 and s.native.snapshot_reads == before


def test_disconnect_retains_partial_rows_without_provider_or_native_reentry(storage_job):
    s = storage_job
    accepted = s.start()
    assert accepted.response.ok
    one_materialization(s)
    before = s.native.snapshot_reads, s.env.provider_calls
    s.connection.disconnected.set()
    assert drain(s.env)["state"] == "CANCELLED"
    assert s.native.writes == 1
    assert (s.native.snapshot_reads, s.env.provider_calls) == before


@pytest.mark.parametrize("module_name", ["graph", "primitive"])
def test_initial_permission_provider_cannot_be_adopted_as_new_helper_source(storage_job, monkeypatch, module_name):
    s = storage_job
    calls = []
    def foreign(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Altered helper source ran")
    module, field = (s.primitive.graph, "_constructor_proof") if module_name == "graph" else (s.primitive, "build_plan")
    s.env.provider_hook = lambda: monkeypatch.setattr(module, field, foreign)
    response, _ = s.call(s.tools.contract.PREVIEW, dict(s.parameters))
    assert not response.ok and response.error["context"]["reason"] == "STORAGE_SOURCE_CHANGED"
    assert calls == [] and s.native.snapshot_reads == s.native.writes == 0


@pytest.mark.parametrize("hook", ("check_final_request", "check_final_job"))
def test_initial_preview_provider_cannot_invoke_replaced_final_hook(storage_job, hook):
    s = storage_job
    context = s.env.executor.context
    calls = []

    def foreign():
        calls.append("foreign final hook")
        raise AssertionError("A replaced final hook ran before admission refusal")

    s.env.provider_hook = lambda: setattr(context, hook, foreign)
    with pytest.raises(s.tools.contract.BridgeError) as failure:
        s.env.registry.dispatch(s.tools.contract.PREVIEW, dict(s.parameters), context)
    assert failure.value.context["reason"] == "STORAGE_CONTEXT_CHANGED"
    assert calls == [] and s.native.snapshot_reads == s.native.writes == 0


@pytest.mark.parametrize("change", ("guard_binding", "guard_code", "guard_cell", "empty_guard_cell"))
def test_initial_preview_provider_cannot_replace_held_entry_guard(storage_job, monkeypatch, change):
    s = storage_job
    context = s.env.executor.context
    calls = []

    def foreign():
        calls.append("foreign entry guard")
        raise AssertionError("A replaced preview guard ran")

    def alter():
        callback = context.checkpoint_admission.callback
        guard = callback.entry_guard
        if change == "guard_binding":
            object.__setattr__(callback, "entry_guard", foreign)
        elif change == "guard_code":
            monkeypatch.setattr(guard, "__code__", guard.__code__.replace(co_name="altered"))
        else:
            cell = next(cell for name, cell in zip(guard.__code__.co_freevars, guard.__closure__, strict=True)
                        if name == "proof")
            if change == "empty_guard_cell":
                del cell.cell_contents
            else:
                held = cell.cell_contents
                monkeypatch.setattr(cell, "cell_contents", (held,))

    s.env.provider_hook = alter
    with pytest.raises(s.tools.contract.BridgeError) as failure:
        s.env.registry.dispatch(s.tools.contract.PREVIEW, dict(s.parameters), context)
    assert failure.value.context["reason"] == "STORAGE_CONTEXT_CHANGED"
    assert calls == [] and s.native.snapshot_reads == s.native.writes == 0


def test_preview_cancellation_callback_cannot_rebaseline_entry_guard(storage_job):
    s = storage_job
    context = s.env.executor.context
    calls = []

    def foreign():
        calls.append("foreign entry guard")
        raise AssertionError("A cancellation callback substituted the entry guard")

    def inject():
        object.__setattr__(context.checkpoint_admission.callback, "entry_guard", foreign)

    request = s.env.protocol.Request("guard-cancel", s.tools.contract.PREVIEW, dict(s.parameters))
    spec = s.env.registry.get(request.method)
    with (s.env.registry.mutation_entry(spec, request.params, context) as permit,
          pytest.raises(s.tools.contract.BridgeError) as failure):
        s.env.executor._invoke_owned(request, allow_recovery=False, check_cancelled=inject,
            _context=context, _permit=permit, preserve_execution=False)
    assert failure.value.context["reason"] == "STORAGE_CONTEXT_CHANGED"
    assert calls == [] and s.native.snapshot_reads == s.native.writes == 0


def test_preview_cancellation_callback_cannot_replace_bind_time_trust_record(storage_job):
    s = storage_job
    context = s.env.executor.context
    calls = []

    def foreign():
        calls.append("foreign entry guard")

    def inject():
        function = foreign
        context.checkpoint_admission.callback.entry_proof = (
            function, function.__code__, function.__globals__, function.__defaults__,
            function.__kwdefaults__, function.__closure__, ())

    request = s.env.protocol.Request("guard-trust-record", s.tools.contract.PREVIEW, dict(s.parameters))
    spec = s.env.registry.get(request.method)
    with (s.env.registry.mutation_entry(spec, request.params, context) as permit,
          pytest.raises(s.tools.contract.BridgeError)):
        s.env.executor._invoke_owned(request, allow_recovery=False, check_cancelled=inject,
            _context=context, _permit=permit, preserve_execution=False)
    assert calls == [] and s.native.snapshot_reads == s.native.writes == 0


def test_exact_b2_starter_and_turns_resolve_enforced_protected_scope(storage_job):
    s = storage_job
    store = s.source.get_task_plans(s.env.state)
    store.protection = {"fixture_protection": True}
    accepted = s.start()
    assert accepted.response.ok, accepted.response.error
    terminal = drain(s.env)
    assert terminal["state"] == "SUCCEEDED", terminal
    assert len(s.native.scope_calls) >= 3  # Starter plus actual checkpoint/native turns.
    assert s.native.writes == 2


def test_protected_scope_denial_before_start_has_no_native_preparation(storage_job):
    s = storage_job
    s.source.get_task_plans(s.env.state).protection = {"fixture_protection": True}
    s.native.scope["deny"] = True
    result = s.start()
    assert not result.response.ok
    assert s.env.manager.active is None and s.native.writes == 0


def test_already_array_selection_is_noop_and_keeps_original_value_baseline(storage_job):
    s = storage_job
    s.native.attrs["UV"].storage = "ARRAY"
    before = s.native.attrs["UV"].values
    assert s.start().response.ok
    terminal = drain(s.env)
    assert terminal["state"] == "SUCCEEDED", terminal
    assert s.native.writes == 1 and s.native.entered_names == [".uv_select_face"]
    assert s.native.attrs["UV"].values == before


def test_preexisting_array_edit_is_not_adopted_by_a_later_noop(storage_job):
    s = storage_job
    s.native.attrs["UV"].storage = "ARRAY"
    accepted = s.start()
    assert accepted.response.ok
    s.native.attrs["UV"].values = ((.25, .5),) * s.native.attrs["UV"].count
    terminal = drain(s.env)
    assert terminal["state"] == "FAILED"
    assert s.native.writes == 0
