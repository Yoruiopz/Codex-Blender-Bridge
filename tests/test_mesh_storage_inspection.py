"""Pure domain models; canonical scheduling and native RNA need separate gates."""
import importlib
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def inspection_model(addon_package, monkeypatch):
    domain = importlib.import_module(addon_package + ".tools._mesh_storage_inspection")
    source, primitive, contract = domain.source, domain.primitive, domain.contract
    errors = importlib.import_module(addon_package + ".errors")
    env = NS(events=[], stopped=None, changed_source=False, scope_hook=None, bind_hook=None, role_error=None,
             protected={"pixels": "a" * 64, "binding": ["Material", True]}, reads=0, binds=0)
    env.context = NS(registry=object(), state=object(), request_lifecycle=None)
    env.fresh_context = lambda: NS(registry=env.context.registry, state=env.context.state, request_lifecycle=None)
    env.store = NS(evidence_epoch=1)
    env.native_context = {"mode": "OBJECT", "selection": ["Object"]}
    obj, mesh = object(), object()
    header = primitive.AttributeHeader("UV", "CORNER", "FLOAT2", "Float2Attribute", "Float2AttributeValue",
                                       "SINGLE", 4, "a" * 64, "b" * 64)
    env.metadata = primitive._Metadata(obj, mesh, ("Object", "1"), ("Mesh", "2"), "3", (4, 0, 4, 1), (), (header,))
    env.plan = primitive.PreparationPlan(env.metadata, (primitive.Target("UV", header, "MATERIALIZE_SINGLE"),),
                                        "c" * 64, (("required_available_memory_bytes", source.BASE_MEMORY),))

    class Seal:
        def verify(self):
            if env.changed_source:
                raise contract.refused("MODELED_SOURCE_CHANGED")
        def fingerprint(self):
            return "d" * 64

    class Gate:
        def __init__(self, context, seal, method):
            self.context, self.seal, self.method = context, seal, method
            self.floor = source.BASE_MEMORY
        def pure(self):
            self.seal.verify()
            env.events.append("guard")
            if env.stopped is not None:
                raise env.stopped
        def authorize(self):
            self.pure()
            env.events.append("permission")
            self.pure()

    class Roles:
        def __init__(self, _bpy, metadata, gate):
            self.gate, self.obj, self.mesh = gate, metadata.obj, metadata.mesh
            self.phase, self.native_push_completed = 0, False
            self.initial_roles, self.identities = (0, None), (("Scene", "1"),)
            self.origin = self.memberships = self.before_readback = self.last_readback = self.after_readback = None
            self.bound_digest = None
            env.events.append("roles")
        def check_identity(self, origin=None):
            if origin is not self.origin:
                raise contract.refused("MODELED_ROLE_ORIGIN_CHANGED")
        def check_after_read(self):
            self.gate.pure()
            if env.role_error is not None:
                raise env.role_error
            env.events.append("role_read")
        def bind_protected(self, facts):
            self.gate.pure()
            env.binds += 1
            self.bound_digest, self.origin = contract.digest(facts), object()
            if env.bind_hook is not None:
                env.bind_hook()
        def report(self):
            return {"native_push_completed": False}

    def plan(*_args):
        env.events.append("plan")
        return replace(env.plan, metadata=env.metadata)

    def protected(_bpy, _metadata, gate, _bindings, _excluded, *, checkpoint_roles):
        gate.pure()
        env.events.append("protected")
        env.reads += 1
        checkpoint_roles.memberships = 1
        checkpoint_roles.last_readback = {"refs": 1, "weak": False}
        if checkpoint_roles.before_readback is None:
            checkpoint_roles.before_readback = checkpoint_roles.last_readback
        if env.scope_hook is not None:
            env.scope_hook()
        gate.pure()
        return {**env.protected}

    class Access:
        def __init__(self, _bpy, pure):
            self.pure = pure
        def snapshot(self, _object_name, _mesh_name):
            self.pure()
            result = env.metadata
            self.pure()
            return result

    monkeypatch.setattr(source, "verify_seal", lambda seal: seal.verify())
    monkeypatch.setattr(source, "get_task_plans", lambda _state: env.store)
    monkeypatch.setattr(source, "Gate", Gate)
    monkeypatch.setattr(source, "build_plan", plan)
    monkeypatch.setattr(source, "CheckpointRoles", Roles)
    monkeypatch.setattr(source, "protected_facts", protected)
    monkeypatch.setattr(domain, "_context_stamp", lambda *_args: domain._encoded(env.native_context))
    monkeypatch.setattr(primitive.CaptureOrigin, "capture", lambda pure, **kwargs: NS(pure=pure))
    monkeypatch.setattr(primitive, "_guards", lambda origin: (origin.pure, None, None))
    monkeypatch.setattr(primitive, "qualify_collection_bindings", lambda *args, **kwargs: object())
    monkeypatch.setattr(primitive, "_Access", Access)
    env.parameters = {"object_name": "Object", "mesh_name": "Mesh", "attribute_names": ["UV"]}
    env.bpy = NS(app=NS(build_hash=b"test"), types=object())
    env.domain, env.errors = domain, errors
    env.driver = domain.MeshStorageInspectionDriver(env.context, env.parameters, env.bpy, source_seal=Seal())
    return env


def test_construction_and_pure_admission_do_not_read_native_facts(inspection_model):
    e = inspection_model
    assert e.events == []
    e.driver.check_after_read(e.fresh_context())
    assert e.events == [] and e.reads == e.binds == 0
    assert e.driver.result is None and e.driver.done is False


def test_three_distinct_read_phases_require_complete_final_comparison(inspection_model):
    e = inspection_model
    for completed in (1, 2):
        progress = e.driver.advance(e.context)
        assert progress["completed"] == completed
        assert e.driver.result is None and e.driver.done is False
        assert e.binds == 0
    assert e.reads == 1
    e.driver.advance(e.fresh_context())
    result = e.driver.result
    assert e.reads == 2 and e.binds == 1
    assert result["write_authorized"] is False
    assert len(result["inspection_fingerprint"]) == 64
    assert "expected_preparation_fingerprint" not in result
    assert result["undo_boundary_created"] is False and result["project_saved"] is False
    assert result["transient_intervening_edits_detectable"] is False
    assert result["edits_before_first_observation_detectable"] is False
    assert result["writer_handoff_supported"] is False
    assert result["native_functional_qualified"] is False


@pytest.mark.parametrize("phase", (0, 1, 2))
@pytest.mark.parametrize("code", ("CANCELLED", "TIMEOUT", "PERMISSION_DENIED"))
def test_original_stop_failure_is_preserved_without_ready_or_late_read(inspection_model, phase, code):
    e = inspection_model
    for _ in range(phase):
        e.driver.advance(e.context)
    before = e.reads
    e.stopped = e.errors.BridgeError(code, "Modeled original control stop.")
    with pytest.raises(e.errors.BridgeError) as failure:
        e.driver.advance(e.context)
    assert failure.value is e.stopped
    assert e.reads == before and e.binds == 0
    assert e.driver.result is None and e.driver.done is False


@pytest.mark.parametrize("field", ("pixels", "binding"))
def test_observed_final_scope_drift_refuses_without_rebasing(inspection_model, field):
    e = inspection_model
    e.driver.advance(e.context)
    e.driver.advance(e.context)
    original = e.driver.protected_bytes
    e.protected[field] = "changed"
    with pytest.raises(e.errors.BridgeError) as failure:
        e.driver.advance(e.context)
    assert failure.value.context["inspection_status"] == "STALE"
    assert e.driver.protected_bytes is original and e.driver.result is None and e.binds == 0


def test_metadata_drift_is_stale_without_protected_read(inspection_model):
    e = inspection_model
    e.driver.advance(e.context)
    e.metadata = replace(e.metadata, counts=(8, 0, 4, 1))
    with pytest.raises(e.errors.BridgeError) as failure:
        e.driver.advance(e.context)
    assert failure.value.context["inspection_status"] == "STALE" and e.reads == 0


@pytest.mark.parametrize("phase", (1, 2))
def test_native_context_drift_is_stale_before_next_protected_read(inspection_model, phase):
    e = inspection_model
    for _ in range(phase):
        e.driver.advance(e.context)
    e.native_context["selection"] = ["Foreign"]
    before = e.reads
    with pytest.raises(e.errors.BridgeError) as failure:
        e.driver.advance(e.context)
    assert failure.value.context["reason"] == "INSPECTION_CONTEXT_STALE"
    assert failure.value.context["inspection_status"] == "STALE" and e.reads == before and e.driver.result is None


@pytest.mark.parametrize("tamper", ("parameter", "plan", "readback", "floor", "source"))
def test_cached_state_tamper_refuses_before_next_native_read(inspection_model, tamper):
    e = inspection_model
    e.driver.advance(e.context)
    e.driver.advance(e.context)
    if tamper == "parameter":
        object.__setattr__(e.driver.parameters, "mesh_name", "Foreign")
    elif tamper == "plan":
        object.__setattr__(e.driver.initial.metadata, "counts", (9, 0, 4, 1))
    elif tamper == "readback":
        e.driver.checkpoint_roles.last_readback["weak"] = 0  # Exact bool/int distinction.
    elif tamper == "floor":
        e.driver.gate.floor = 1
    else:
        e.changed_source = True
    before = e.reads
    with pytest.raises(e.errors.BridgeError):
        e.driver.check_after_read(e.fresh_context())
    assert e.reads == before and e.binds == 0 and e.driver.result is None


def test_foreign_fact_never_runs_conversion_or_equality_callbacks(inspection_model):
    e = inspection_model
    class Foreign:
        def __eq__(self, other):
            pytest.fail("foreign equality")
        def __repr__(self):
            pytest.fail("foreign repr")
        def __bool__(self):
            pytest.fail("foreign bool")
        def __iter__(self):
            pytest.fail("foreign iteration")
    with pytest.raises(e.errors.BridgeError):
        e.domain._encoded({"foreign": Foreign()})


def test_final_guard_stop_does_not_publish_ready(inspection_model, monkeypatch):
    e = inspection_model
    e.driver.advance(e.context)
    e.driver.advance(e.context)
    original = e.domain.source.CheckpointRoles.bind_protected
    error = e.errors.BridgeError("TIMEOUT", "Modeled final control stop.")
    def bind(roles, facts):
        original(roles, facts)
        e.stopped = error
    monkeypatch.setattr(e.domain.source.CheckpointRoles, "bind_protected", bind)
    with pytest.raises(e.errors.BridgeError) as failure:
        e.driver.advance(e.context)
    assert failure.value is error and e.driver.result is None and e.driver.done is False


@pytest.mark.parametrize("name", ("_inspection_function", "_InspectionAdmission"))
def test_private_admission_proves_registration_source_before_core_helper(addon_package, monkeypatch, name):
    tools = importlib.import_module(addon_package + ".tools.mesh_storage")
    core = importlib.import_module(addon_package + ".scene_jobs")
    registry_module = importlib.import_module(addon_package + ".tool_registry")
    registry = registry_module.ToolRegistry()
    tools.register_private(registry)
    spec = registry.get(tools.contract.INSPECTION_START)
    calls = []
    def foreign(*args, **kwargs):
        calls.append(True)
        pytest.fail("source-replaced admission helper was called")
    monkeypatch.setattr(core, name, foreign)
    with pytest.raises(tools.contract.BridgeError):
        spec.checkpoint_admission_factory(object(), {})
    assert calls == []


def test_private_starter_declares_readonly_no_checkpoint_metadata(addon_package):
    tools = importlib.import_module(addon_package + ".tools.mesh_storage")
    registry_module = importlib.import_module(addon_package + ".tool_registry")
    registry = registry_module.ToolRegistry()
    tools.register_private(registry)
    spec = registry.get(tools.contract.INSPECTION_START)
    assert spec.modifies is False and spec.automatic_checkpoint is False
    assert spec.record_history is False and spec.checkpoint_owns_finalization is False
    assert spec.permissions == frozenset(tools.contract.PERMISSIONS)


def test_private_admission_pins_glb_stage_defining_module_before_start(addon_package, monkeypatch):
    tools = importlib.import_module(addon_package + ".tools.mesh_storage")
    helper = importlib.import_module(addon_package + ".glb_stage_runtime")
    registry_module = importlib.import_module(addon_package + ".tool_registry")
    registry = registry_module.ToolRegistry()
    tools.register_private(registry)
    spec = registry.get(tools.contract.INSPECTION_START)
    calls = []
    def foreign(*_args, **_kwargs):
        calls.append(True)
        pytest.fail("defining-module source was adopted after registration")
    monkeypatch.setattr(helper.GLBStageService, "check_context_factory", foreign)
    with pytest.raises(tools.contract.BridgeError):
        spec.checkpoint_admission_factory(object(), {})
    assert calls == []


@pytest.mark.parametrize("field", ("action", "name", "header_count", "header_schema"))
def test_nested_plan_leaf_types_refuse_before_foreign_hash_or_equality(inspection_model, field):
    e = inspection_model
    e.driver.advance(e.context)
    calls = []
    class Foreign:
        def __hash__(self):
            calls.append("hash")
            return 0
        def __eq__(self, _other):
            calls.append("eq")
            return False
    target = e.driver.initial.targets[0]
    if field in ("action", "name"):
        object.__setattr__(target, field, Foreign())
    else:
        object.__setattr__(target.header, "count" if field == "header_count" else "schema_sha256", Foreign())
    with pytest.raises(e.errors.BridgeError):
        e.driver.check_after_read(e.context)
    assert calls == [] and e.reads == 0


@pytest.mark.parametrize("stage", ("capture_read", "seal_read", "seal_bind"))
@pytest.mark.parametrize("field,value", (("storage", "ARRAY"), ("schema_sha256", "e" * 64), ("count", 8)))
def test_selected_metadata_changed_by_final_native_return_is_stale(inspection_model, stage, field, value):
    e = inspection_model
    e.driver.advance(e.context)
    if stage != "capture_read":
        e.driver.advance(e.context)
    def change():
        e.metadata = replace(e.metadata, attributes=(replace(e.metadata.attributes[0], **{field: value}),))
    if stage == "seal_bind":
        e.bind_hook = change
    else:
        e.scope_hook = change
    with pytest.raises(e.errors.BridgeError) as failure:
        e.driver.advance(e.context)
    assert failure.value.context["inspection_status"] == "STALE"
    assert e.driver.result is None and e.driver.done is False


@pytest.mark.parametrize("reason", ("STORAGE_CHECKPOINT_MAIN_OWNER_CHANGED", "STORAGE_CHECKPOINT_NATIVE_ROLES_CHANGED",
    "STORAGE_CHECKPOINT_ACTIVE_OWNER_CHANGED", "STORAGE_CHECKPOINT_STRUCTURAL_MEMBERSHIPS_CHANGED",
    "SCENE_OBJECT_REFERENCE_ROLES_CHANGED", "STORAGE_CHECKPOINT_SCENE_SELF_CONSUMERS_CHANGED"))
def test_observed_native_role_drift_is_typed_stale_without_replacing_primary(inspection_model, reason):
    e = inspection_model
    e.driver.advance(e.context)
    e.role_error = e.domain.contract.refused(reason)
    with pytest.raises(e.errors.BridgeError) as failure:
        e.driver.advance(e.context)
    assert failure.value is e.role_error and failure.value.context["inspection_status"] == "STALE"
    assert e.reads == 0 and e.driver.result is None


@pytest.mark.parametrize("field", ("registry", "state", "connection", "epoch"))
def test_inspection_session_binding_rejects_other_original_scope(inspection_model, field):
    e = inspection_model
    context = e.fresh_context()
    if field in ("registry", "state"):
        setattr(context, field, object())
    elif field == "connection":
        context.request_lifecycle = NS(connection=object())
    else:
        e.store.evidence_epoch += 1
    with pytest.raises(e.errors.BridgeError) as failure:
        e.driver.check_after_read(context)
    assert failure.value.context["reason"] == "INSPECTION_SESSION_CHANGED" and e.reads == 0
