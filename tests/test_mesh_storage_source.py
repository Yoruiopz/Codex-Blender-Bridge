"""Source replacement and predicted-storage CAS; no native qualification claim."""
import importlib
import warnings
from dataclasses import replace
from types import FunctionType, ModuleType
from types import SimpleNamespace as NS

import pytest
from test_scene_checkpoint_roles import roles  # noqa: F401 - native-shaped RNA only
from test_scene_jobs import scene_jobs  # noqa: F401 - canonical scheduler fixture
from test_scene_mutation_boundaries import RNA, NativeOwner, Properties, prop


@pytest.fixture
def source(addon_package):
    return importlib.import_module(addon_package + ".mesh_storage_source")


@pytest.fixture
def checkpoint_case(source, roles, monkeypatch):  # noqa: F811
    """Assume native constructor metadata; retain real Plan/count/CAS logic."""
    case = roles
    brush_type = type("ParticleBrush", (NativeOwner,), {"bl_rna": RNA("ParticleBrush", Properties([
        prop("curve", "POINTER", is_readonly=True, fixed_type=NS(identifier="CurveMapping")),
        prop("strength", "FLOAT")]))})
    mesh_type = type("Mesh", (NativeOwner,), {"bl_rna": RNA("Mesh", Properties([]))})
    case.bpy.types.ParticleBrush, case.bpy.types.Mesh, case.bpy.types.Struct = brush_type, mesh_type, RNA
    brush = brush_type({"curve": None, "strength": 0.5})
    case.particle.bl_rna.properties.append(prop("brush", "POINTER", is_readonly=True,
                                              fixed_type=NS(identifier="ParticleBrush")))
    case.particle._values["brush"] = brush
    mesh = mesh_type({"name": "Mesh", "session_uid": 103})
    case.active._values.update(name="Target", session_uid=102, type="MESH", data=mesh)
    case.scene._values.update(session_uid=101)
    case.bpy.context.scene = case.scene
    case.bpy.data.scenes = {"Scene": case.scene}
    case.bpy.data.objects = {"Target": case.active}
    case.bpy.data.meshes = {"Mesh": mesh}
    case.counts.update(memberships=2, extra=0)
    def references(owner):
        if owner is case.scene:
            return case.counts["self"]
        if owner is case.active:
            return case.counts["memberships"] + int(case.particle.object is case.active) + case.counts["extra"]
        return 0
    case.scene.user_of_id = references
    class Reader:
        def __init__(self, bpy, check):
            self.bpy, self.check = bpy, check
        def local_id(self, owner, kind):
            return {"kind": kind, "name": owner.name, "pointer": format(owner.as_pointer(), "x"),
                    "session_uid": str(owner.session_uid)}
    monkeypatch.setattr(source.graph, "_Reader", Reader)
    monkeypatch.setattr(source.graph, "_query_context", lambda reader: (id(reader.bpy.context.scene),))
    # Only C factory/descriptor bindings are modeled. Production guarded call,
    # raw, descriptor scanning, iteration and Plan readers remain unchanged.
    original_find = source.graph._class_find
    case.native_events, case.native_after_stop = [], []
    case.live = {"stopped": False}
    case.native_hook = None
    def note(event):
        case.native_events.append(event)
        if case.live["stopped"]:
            case.native_after_stop.append(event)
    def native_get(owner, name):
        note(("get", id(owner), name))
        result = getattr(owner, name)
        return result if case.native_hook is None else case.native_hook(owner, name, result)
    def native_pointer(owner):
        note(("pointer", id(owner)))
        return owner.as_pointer()
    def class_find(cls, name):
        if name == "__getattribute__":
            return native_get
        if name == "__getattr__":
            return None
        if name == "as_pointer":
            return native_pointer
        return original_find(cls, name)
    def access_init(self, bpy, check):
        self.bpy, self.check = bpy, check
        self.types, self.base, self.struct_type, self.array_type = bpy.types, NativeOwner, RNA, tuple
        self.getter, self.pointer = native_get, native_pointer
        self.collection_type, self.collection_getter = NS, object.__getattribute__
        self._origin = tuple((name, getattr(self, name)) for name in self.__slots__ if name != "_origin")
    def lookup(self, collection, name):
        def get():
            note(("Main.get", name))
            return collection.get(name)
        return self.call(get)
    def native_method(self, owner, name):
        assert name == "keys"
        def keys():
            note(("keys", id(owner)))
            return NativeOwner.keys(owner)
        return keys
    def active(self, layer):
        return self.raw(self.raw(layer, "objects"), "active")
    monkeypatch.setattr(source.graph, "_class_find", class_find)
    monkeypatch.setattr(source._CheckpointRoleAccess, "__init__", access_init)
    monkeypatch.setattr(source._CheckpointRoleAccess, "lookup", lookup)
    monkeypatch.setattr(source._CheckpointRoleAccess, "method", native_method)
    monkeypatch.setattr(source._CheckpointRoleAccess, "active", active)
    case.source, case.mesh, case.brush = source, mesh, brush
    case.gate = NS(pure=lambda: None)
    case.reader = Reader(case.bpy, case.gate.pure)
    def capture():
        role = source.CheckpointRoles(case.bpy, NS(obj=case.active, mesh=mesh), case.gate)
        role.check_scene_object_count(case.reader, case.scene, case.active, case.counts["memberships"])
        facts = {"complete_original_B2_scope": {"ARRAY": "signed-zero", "image": "all-pixels",
                                                "material": "original"}, "checkpoint_roles": role.authored()}
        role.bind_protected(facts)
        return role, facts
    case.capture = capture
    return case


def complete_b2_push(case, role, facts, addon_package, monkeypatch, *, effect=None):
    """Actual canonical manager/event; only native undo side effects modeled."""
    from test_checkpoint_snapshots import NativeStack
    source = case.source
    checkpoints = importlib.import_module(addon_package + ".checkpoints")
    completion = importlib.import_module(addon_package + ".checkpoint_completion")
    tools = importlib.import_module(addon_package + ".tool_registry")
    permissions = importlib.import_module(addon_package + ".permissions")
    state = importlib.import_module(addon_package + ".state")
    stack, manager, registry = NativeStack(), checkpoints.CheckpointManager(), tools.ToolRegistry()
    context = tools.ToolContext(state.BridgeState(), permissions.PermissionManager(lambda: {}), registry, manager)
    method, params = "fixture.b2_roles", {}
    class Guard:
        def __call__(self):
            self.check_after_read()
        def check_after_read(self):
            role.check_scene_object_count(case.reader, case.scene, case.active, case.counts["memberships"])
            current = {**facts, "checkpoint_roles": role.authored()}
            if source.contract.digest(current) != role.bound_digest:
                raise source.contract.refused("MODELED_FULL_PROTECTION_CHANGED")
            role.verified(source.contract.digest(current))
        def native_push_delegates(self):
            role.check_identity(role.origin)
            return (role.plan,)
        def after_native_push(self):
            completion.claim_native_push_completion(context, method, self)
            role.after_native_push(role.origin)
    guard = Guard()
    spec = registry.register(method, lambda *_: None, modifies=True, checkpoint_admission_factory=lambda *_: guard)
    native = stack.bpy.ops.ed.undo_push
    def push(**kwargs):
        result = native(**kwargs)
        if "FINISHED" in result:
            (case.push if effect is None else effect)()
        return result
    with monkeypatch.context() as patches:
        patches.setattr(checkpoints, "require_blender", lambda: stack.bpy)
        patches.setattr(stack.bpy.ops.ed, "undo_push", push)
        with (registry.mutation_entry(spec, params, context) as permit,
              registry.checkpoint_admission(spec, params, context) as binding,
              registry.native_push_completion(permit, binding, manager,
                  final_check=lambda: binding.check_identity(method)) as consumer):
            assert manager.before_modification(method, before_write=binding,
                after_read=binding.check_after_read, after_native_push=consumer)
    return NS(stack=stack, manager=manager, guard=guard)


@pytest.mark.parametrize("initialized", [False, True])
def test_b2_exact_weak_role_transition_preserves_frozen_scope_and_repeated_count(
    checkpoint_case, addon_package, monkeypatch, initialized,
):
    c = checkpoint_case
    if initialized:
        c.push()
    role, facts = c.capture()
    fingerprint = c.source.contract.digest(facts)
    before = role.before_readback
    complete_b2_push(c, role, facts, addon_package, monkeypatch)
    assert role.report()["after_readback_measured"] is True
    assert role.after_readback["scene_self_references"] == 1
    assert role.after_readback["scene_object_references"] == 3
    assert role.after_readback["particle_object"] == c.module.proof.token(c.active)
    assert role.bound_digest == fingerprint and role.before_readback is before
    complete_b2_push(c, role, facts, addon_package, monkeypatch)
    assert role.after_readback["scene_object_references"] == 3
    assert c.source.contract.digest({**facts, "checkpoint_roles": role.authored()}) == fingerprint


@pytest.mark.parametrize("initialized", [False, True])
def test_b2_checked_reader_matches_original_plan_admitted_state(checkpoint_case, initialized):
    c = checkpoint_case
    if initialized:
        c.push()
    role, _ = c.capture()
    original = c.module.Plan(c.bpy, c.scene, active_validator=role.validator, include_brush=True)
    assert role.plan._read() == original._read()
    assert role.plan.references() == original.references()
    assert role.plan.authored() == original.authored()


@pytest.mark.parametrize("change", ["main_owner", "uid", "original", "particle", "extra_reference", "settings", "protected"])
def test_b2_foreign_change_after_genuine_push_refuses_with_truthful_partial_bookkeeping(
    checkpoint_case, addon_package, monkeypatch, change,
):
    c = checkpoint_case
    role, facts = c.capture()
    def effect():
        c.push()
        if change == "main_owner":
            c.bpy.data.objects["Target"] = c.other
        elif change == "uid":
            c.active.session_uid += 1
        elif change == "original":
            c.scene._values["original"] = c.other
        elif change == "particle":
            c.particle._values["object"] = c.other
        elif change == "extra_reference":
            c.counts["extra"] += 1
        elif change == "settings":
            c.brush._values["strength"] = 0.25
        else:
            facts["complete_original_B2_scope"]["material"] = "foreign"
    with pytest.raises(c.source.contract.BridgeError) as caught:
        complete_b2_push(c, role, facts, addon_package, monkeypatch, effect=effect)
    assert caught.value.context["checkpoint_bookkeeping"]["native_snapshots_completed"] == 1
    assert caught.value.context["checkpoint_bookkeeping"]["next_write_rejected"] == "after_native_undo_push"
    assert role.report()["native_push_completed"] is True
    assert role.report()["after_readback_measured"] is False


@pytest.mark.parametrize("field", ["active_validator", "previous_witness", "_read", "check_after_read"])
def test_b2_plan_instance_replacement_refuses_before_foreign_callback(checkpoint_case, field):
    c = checkpoint_case
    role, _ = c.capture()
    calls = []
    setattr(role.plan, field, lambda *_: calls.append("foreign"))
    with pytest.raises(c.source.contract.BridgeError):
        role.check_after_read()
    assert calls == []


@pytest.mark.parametrize("phase", [0, 1])
def test_b2_replaced_expected_never_dispatches_foreign_equality(checkpoint_case, phase):
    c = checkpoint_case
    role, _ = c.capture()
    calls = []
    class Foreign:
        def __eq__(self, _other):
            calls.append("equality")
            return True
    role.phase = phase
    role.plan.expected = Foreign()
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.check_after_read()
    assert caught.value.context["reason"] == "STORAGE_CHECKPOINT_ROLE_PHASE_CHANGED"
    assert calls == []


@pytest.mark.parametrize("change", ["unannounced", "phase_only", "expected_only", "direct_completion"])
def test_b2_weak_looking_values_without_canonical_completion_do_not_authorize_readback(checkpoint_case, change):
    c = checkpoint_case
    role, _ = c.capture()
    c.push()
    if change == "phase_only":
        role.phase = 1
    elif change == "expected_only":
        role.plan.expected = (1, role.plan.active)
    with pytest.raises(c.source.contract.BridgeError):
        if change == "direct_completion":
            role.after_native_push(role.origin)
        else:
            role.check_after_read()
    assert role.native_push_completed is False
    assert role.after_readback is None


@pytest.mark.parametrize("boundary", ["field", "iterator", "pointer", "settings", "user_map", "user_of_id"])
@pytest.mark.parametrize("fault", ["stop", "source_change"])
def test_b2_role_native_boundary_stops_before_any_later_native_access(
    checkpoint_case, monkeypatch, boundary, fault,
):
    c = checkpoint_case
    held_seal = [None]
    def check():
        if held_seal[0] is not None:
            c.source.verify_seal(held_seal[0])
        if c.live["stopped"]:
            raise c.source.contract.BridgeError("TIMEOUT", "Modeled stop inside native role access")
    c.gate.pure = check
    role, _ = c.capture()
    held_seal[0] = c.source.SourceSeal.capture()
    events = []
    def trigger(value):
        events.append("fault")
        c.live["stopped"] = True
        if fault == "source_change":
            monkeypatch.setitem(c.source.checkpoint_proof.RUNTIME["Scene"], "cycles", "STRING")
        return value
    if boundary == "field":
        c.scene.getter_hooks["tool_settings"] = lambda: trigger(c.settings)
    elif boundary == "iterator":
        original = c.scene.bl_rna.properties
        class StopIterator:
            def __iter__(self):
                return self
            def __next__(self):
                if events:
                    pytest.fail("A second native iterator step ran after stop")
                return trigger(original[0])
        c.scene.bl_rna.properties = StopIterator()
    elif boundary == "pointer":
        c.scene.as_pointer = lambda: trigger(id(c.scene))
    elif boundary == "settings":
        c.brush.getter_hooks["strength"] = lambda: trigger(0.5)
    elif boundary == "user_map":
        original = c.bpy.data.user_map
        c.bpy.data.user_map = lambda **kwargs: trigger(original(**kwargs))
    else:
        original = c.scene.user_of_id
        c.scene.user_of_id = lambda owner: trigger(original(owner))
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.authored() if boundary in {"settings", "user_map"} else role.check_after_read()
    assert events == ["fault"]
    assert c.native_after_stop == []
    assert role.native_push_completed is False and role.after_readback is None
    if fault == "source_change":
        assert caught.value.context["reason"] == "STORAGE_SOURCE_CHANGED"
    else:
        assert caught.value.code == "TIMEOUT"


@pytest.mark.parametrize("field", ["identifier", "type"])
@pytest.mark.parametrize("when", ["before", "native_return"])
@pytest.mark.parametrize("shadow", ["property", "callable", "descriptor"])
def test_b2_static_metadata_shadows_refuse_without_dispatch(checkpoint_case, monkeypatch, field, when, shadow):
    c = checkpoint_case
    role, _ = c.capture()
    calls = []
    class StaticMetadata(NS):
        pass
    metadata = StaticMetadata(**vars(prop("static_field")))
    c.active.bl_rna.properties.append(metadata)
    def foreign(*_args):
        calls.append("foreign metadata")
        return "FLOAT"
    class Descriptor:
        def __get__(self, *_args):
            return foreign()
    replacement = {"property": property(foreign), "callable": foreign, "descriptor": Descriptor()}[shadow]
    def install():
        monkeypatch.setattr(StaticMetadata, field, replacement, raising=False)
    if when == "before":
        install()
    else:
        def hook(owner, name, value):
            if owner is metadata and name == "is_runtime":
                install()
            return value
        c.native_hook = hook
    c.native_events.clear()
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.access.descriptors(c.active)
    assert caught.value.context["reason"] == "NATIVE_FIELD_PYTHON_SHADOW:" + field
    assert calls == []
    reads = [event[2] for event in c.native_events if event[0] == "get" and event[1] == id(metadata)]
    assert reads == ([] if when == "before" else ["is_runtime"])
    assert c.native_after_stop == []


def test_b2_static_catalog_audit_reads_only_runtime_flags_and_returns_original_items(checkpoint_case):
    c = checkpoint_case
    role, _ = c.capture()
    properties = tuple(c.active.bl_rna.properties)
    assert properties and all(item.is_runtime is False for item in properties)
    c.native_events.clear()
    result = role.access.descriptors(c.active)
    assert len(result) == len(properties)
    assert all(current is original for current, original in zip(result, properties, strict=True))
    for metadata in properties:
        reads = [event[2] for event in c.native_events if event[0] == "get" and event[1] == id(metadata)]
        assert reads == ["is_runtime"]


@pytest.mark.parametrize("kind", ["falsey_foreign", "truthy_foreign", "zero", "one", "none"])
def test_b2_runtime_flag_requires_exact_native_bool_without_foreign_dispatch(checkpoint_case, kind):
    c = checkpoint_case
    role, _ = c.capture()
    calls = []
    class Foreign:
        def __bool__(self):
            calls.append("bool")
            return kind == "truthy_foreign"
        def __repr__(self):
            calls.append("repr")
            return "foreign"
        def __str__(self):
            calls.append("str")
            return "foreign"
    flag = {"zero": 0, "one": 1, "none": None}.get(kind, Foreign())
    metadata = prop("unreviewed", is_runtime=flag)
    c.active.bl_rna.properties.append(metadata)
    c.native_events.clear()
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.access.descriptors(c.active)
    assert caught.value.context["reason"] == "STORAGE_CHECKPOINT_RUNTIME_DESCRIPTOR_CHANGED"
    facts = caught.value.context["checkpoint_descriptor"]
    assert facts["owner_identifier"] == "Object"
    if kind.endswith("foreign"):
        assert "is_runtime" not in facts
    else:
        assert facts["is_runtime"] is flag
    assert calls == []
    assert [event[2] for event in c.native_events if event[0] == "get" and event[1] == id(metadata)] == ["is_runtime"]


@pytest.mark.parametrize("fault", ["stop", "source", "access_binding", "origin", "memory"])
def test_b2_runtime_flag_failure_keeps_primary_and_prevents_next_native_read(checkpoint_case, monkeypatch, fault):
    c = checkpoint_case
    held_seal = [None]
    primary = c.source.contract.BridgeError("TIMEOUT", "Original runtime flag stop")
    def check():
        if held_seal[0] is not None:
            c.source.verify_seal(held_seal[0])
        if c.live["stopped"]:
            raise primary
    c.gate.pure = check
    role, _ = c.capture()
    held_seal[0] = c.source.SourceSeal.capture()
    metadata = prop("last_static")
    c.active.bl_rna.properties.append(metadata)
    memory = MemoryError("runtime flag allocation")
    calls = []
    def hook(owner, name, value):
        if owner is metadata and name == "is_runtime":
            if fault == "stop":
                c.live["stopped"] = True
            elif fault == "source":
                monkeypatch.setitem(c.source.checkpoint_proof.RUNTIME["Scene"], "cycles", "STRING")
            elif fault == "access_binding":
                role.access.getter = lambda *_: calls.append("foreign")
            elif fault == "origin":
                role.access._origin = ()
            else:
                raise memory
        return value
    c.native_hook = hook
    c.native_events.clear()
    with pytest.raises((c.source.contract.BridgeError, MemoryError)) as caught:
        role.access.descriptors(c.active)
    reads = [event[2] for event in c.native_events if event[0] == "get" and event[1] == id(metadata)]
    assert reads == ["is_runtime"]
    assert c.native_events[-1] == ("get", id(metadata), "is_runtime")
    assert calls == [] and c.native_after_stop == []
    if fault == "stop":
        assert caught.value is primary
    elif fault == "memory":
        assert caught.value is memory
    else:
        expected = "STORAGE_SOURCE_CHANGED" if fault == "source" else "STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED"
        assert caught.value.context["reason"] == expected


@pytest.mark.parametrize("change", ["replace", "code"])
def test_b2_runtime_first_screen_is_pinned_before_next_native_inspection(checkpoint_case, monkeypatch, change):
    c = checkpoint_case
    _role, _ = c.capture()
    seal = c.source.SourceSeal.capture()
    cls = c.source._CheckpointRoleAccess
    calls = []
    if change == "replace":
        monkeypatch.setattr(cls, "screen_static_metadata", lambda *_: calls.append("foreign"))
    else:
        fn = cls.screen_static_metadata
        monkeypatch.setattr(fn, "__code__", fn.__code__.replace(co_name="foreign"))
    c.native_events.clear()
    with pytest.raises(c.source.contract.BridgeError) as caught:
        c.source.verify_seal(seal)
    assert caught.value.context["reason"] == "STORAGE_SOURCE_CHANGED"
    assert calls == [] and c.native_events == []


@pytest.mark.parametrize("kind", ["Scene", "Object"])
def test_b2_runtime_marker_declaration_is_screened_without_reading_its_payload(checkpoint_case, monkeypatch, kind):
    c = checkpoint_case
    owner = c.scene if kind == "Scene" else c.active
    fixed = c.source.checkpoint_proof.RUNTIME_FIXED[(kind, "cycles")]
    owner.bl_rna.properties.append(prop("cycles", "POINTER", is_runtime=True, is_readonly=True,
                                        fixed_type=NS(identifier=fixed)))
    calls = []
    def marker(_owner):
        calls.append("runtime payload")
        raise AssertionError("An unread runtime declaration must not invoke its getter")
    monkeypatch.setattr(type(owner), "cycles", property(marker), raising=False)
    role, _ = c.capture()
    original = c.module.Plan(c.bpy, c.scene, active_validator=role.validator, include_brush=True)
    assert role.plan.authored() == original.authored()
    assert calls == []
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.access.raw(owner, "cycles")
    assert caught.value.context["reason"] == "NATIVE_FIELD_PYTHON_SHADOW:cycles"
    assert calls == []


@pytest.mark.parametrize("kind", ["Scene", "Object"])
@pytest.mark.parametrize("change", ["unknown", "kind", "readonly", "registered", "fixed_type"])
def test_b2_runtime_marker_signature_drift_refuses_before_its_getter(checkpoint_case, monkeypatch, kind, change):
    c = checkpoint_case
    owner = c.scene if kind == "Scene" else c.active
    name = "unreviewed" if change == "unknown" else "cycles"
    fixed = c.source.checkpoint_proof.RUNTIME_FIXED[(kind, "cycles")]
    metadata = prop(name, "STRING" if change == "kind" else "POINTER", is_runtime=True,
                    is_readonly=change != "readonly", is_registered=change == "registered",
                    fixed_type=NS(identifier="ForeignSettings" if change == "fixed_type" else fixed))
    owner.bl_rna.properties.append(metadata)
    calls = []
    monkeypatch.setattr(type(owner), name, property(lambda _owner: calls.append("foreign")), raising=False)
    with pytest.raises(c.source.contract.BridgeError) as caught:
        c.capture()
    assert caught.value.context["reason"] == "STORAGE_CHECKPOINT_RUNTIME_DESCRIPTOR_CHANGED"
    assert calls == []


@pytest.mark.parametrize("change", ["unknown", "kind", "readonly", "registered", "fixed_type", "array_length", "default"])
def test_b2_runtime_descriptor_failure_reports_only_original_read_prefix(checkpoint_case, change):
    c = checkpoint_case
    role, _ = c.capture()
    name = "unreviewed" if change == "unknown" else "active_selection_set" if change in {"array_length", "default"} else "cycles"
    is_scalar = name == "active_selection_set"
    fixed = NS(identifier="ForeignSettings" if change == "fixed_type" else "CyclesObjectSettings")
    metadata = prop(name, "STRING" if change == "kind" else "INT" if is_scalar else "POINTER",
                    is_runtime=True, is_readonly=not (is_scalar or change == "readonly"),
                    is_registered=change == "registered", fixed_type=fixed,
                    array_length=1 if change == "array_length" else 0, default=1 if change == "default" else 0)
    c.active.bl_rna.properties.append(metadata)
    c.native_events.clear()
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.access.descriptors(c.active)
    error = caught.value
    assert error.context["reason"] == "STORAGE_CHECKPOINT_RUNTIME_DESCRIPTOR_CHANGED"
    facts = error.context["checkpoint_descriptor"]
    assert facts["owner_identifier"] == "Object" and facts["property"] == name
    assert facts["observed_kind"] == metadata.type and facts["is_runtime"] is True
    expected_reads = ["is_runtime", "identifier", "type"]
    if change not in {"unknown", "kind"}:
        expected_reads.append("is_readonly")
        assert facts["readonly"] is metadata.is_readonly
        if change != "readonly":
            expected_reads.append("is_registered")
            assert facts["registered"] is metadata.is_registered
    if change in {"array_length", "default"}:
        expected_reads.append("array_length")
        assert facts["array_length"] == metadata.array_length
        if change == "default":
            expected_reads.append("default")
            assert facts["default"] == 1
        else:
            assert "default" not in facts
    if change == "fixed_type":
        expected_reads.append("fixed_type")
        assert facts["fixed_identifier"] == "ForeignSettings"
        assert facts["expected_fixed_identifier"] == "CyclesObjectSettings"
    assert [event[2] for event in c.native_events if event[0] == "get" and event[1] == id(metadata)] == expected_reads
    assert c.native_after_stop == []


@pytest.mark.parametrize("fault", ["exception", "stop"])
def test_b2_descriptor_diagnostic_never_replaces_primary_native_failure(checkpoint_case, fault):
    c = checkpoint_case
    primary = c.source.contract.BridgeError("TIMEOUT", "Original native metadata failure")
    def check():
        if c.live["stopped"]:
            raise primary
    c.gate.pure = check
    role, _ = c.capture()
    metadata = prop("cycles", "POINTER", is_runtime=True, is_readonly=False,
                    fixed_type=NS(identifier="CyclesObjectSettings"))
    c.active.bl_rna.properties.append(metadata)
    def hook(owner, name, value):
        if owner is metadata and name == "is_readonly":
            if fault == "exception":
                raise primary
            c.live["stopped"] = True
        return value
    c.native_hook = hook
    c.native_events.clear()
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.access.descriptors(c.active)
    assert caught.value is primary
    assert "checkpoint_descriptor" not in primary.context
    reads = [event[2] for event in c.native_events if event[0] == "get" and event[1] == id(metadata)]
    assert reads == ["is_runtime", "identifier", "type", "is_readonly"]
    assert c.native_after_stop == []


def test_b2_descriptor_diagnostic_omits_foreign_values_without_dispatch(source):
    calls = []
    class Foreign:
        def __str__(self):
            calls.append("string")
            return "foreign"
        def __bool__(self):
            calls.append("truthiness")
            return True
        def __repr__(self):
            calls.append("repr")
            return "foreign"
    error = source._checkpoint_descriptor_error({"owner_identifier": "Scene", "property": "cycles", "readonly": Foreign()})
    assert error.context["checkpoint_descriptor"] == {"owner_identifier": "Scene", "property": "cycles"}
    assert calls == []



def test_b2_mesh_identity_does_not_read_unrelated_cycles_declaration(checkpoint_case, monkeypatch):
    c = checkpoint_case
    c.mesh.bl_rna.properties.append(prop("cycles", "POINTER", is_runtime=True, is_readonly=True,
                                        fixed_type=NS(identifier="CyclesMeshSettings")))
    calls = []
    def foreign(_owner):
        calls.append("cycles payload")
        raise AssertionError("Identity must not inspect unrelated runtime payloads")
    monkeypatch.setattr(type(c.mesh), "cycles", property(foreign), raising=False)
    role, _ = c.capture()
    assert role.access.identity(c.mesh, "Mesh") == role.identities[2]
    role.check_after_read()
    assert calls == []
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.access.descriptors(c.mesh)
    assert caught.value.context["reason"] == "STORAGE_CHECKPOINT_RUNTIME_DESCRIPTOR_CHANGED"
    assert caught.value.context["checkpoint_descriptor"]["property"] == "cycles"
    assert calls == []
    with pytest.raises(c.source.contract.BridgeError) as shadow:
        role.access.raw(c.mesh, "cycles")
    assert shadow.value.context["reason"] == "NATIVE_FIELD_PYTHON_SHADOW:cycles"
    assert calls == []


@pytest.mark.parametrize("change", ["wrong_class", "schema_name", "schema_pointer", "schema_kind", "uid", "Main", "stale_alias"])
def test_b2_minimal_identity_refuses_foreign_or_changed_native_owners(checkpoint_case, monkeypatch, change):
    c = checkpoint_case
    role, _ = c.capture()
    if change == "wrong_class":
        with pytest.raises(c.source.contract.BridgeError) as caught:
            role.access.identity(c.active, "Mesh")
        assert caught.value.context["reason"] == "STORAGE_CHECKPOINT_NATIVE_OWNER_CHANGED"
        return
    if change == "schema_name":
        rna = c.mesh.bl_rna
        c.native_hook = lambda owner, name, value: "Object" if owner is rna and name == "identifier" else value
    elif change == "schema_pointer":
        alternate = RNA("Mesh", Properties([]))
        c.native_hook = lambda owner, name, value: alternate if owner is c.mesh and name == "bl_rna" else value
    elif change == "schema_kind":
        c.native_hook = lambda owner, name, value: object() if owner is c.mesh and name == "bl_rna" else value
    elif change == "uid":
        c.mesh.session_uid += 1
    elif change == "Main":
        c.bpy.data.meshes["Mesh"] = c.other
    else:
        monkeypatch.setattr(c.bpy.types, "Mesh", type("ForeignMesh", (NativeOwner,), {"bl_rna": c.mesh.bl_rna}))
    with pytest.raises(c.source.contract.BridgeError):
        role.check_after_read()
    assert role.after_readback is None
    assert role.native_push_completed is False


@pytest.mark.parametrize("uid", [0, -1, True, None])
def test_b2_minimal_identity_requires_real_positive_native_uid(checkpoint_case, uid):
    c = checkpoint_case
    role, _ = c.capture()
    c.mesh.session_uid = uid
    with pytest.raises(c.source.contract.BridgeError):
        role.check_after_read()
    assert role.after_readback is None


@pytest.mark.parametrize("fault", ["stop", "source_change"])
def test_b2_minimal_identity_stops_at_first_schema_getter(checkpoint_case, monkeypatch, fault):
    c = checkpoint_case
    seal = [None]
    primary = c.source.contract.BridgeError("TIMEOUT", "Stopped native identity getter")
    def check():
        if seal[0] is not None:
            c.source.verify_seal(seal[0])
        if c.live["stopped"]:
            raise primary
    c.gate.pure = check
    role, _ = c.capture()
    seal[0] = c.source.SourceSeal.capture()
    def hook(owner, name, value):
        if owner is c.mesh and name == "bl_rna":
            c.live["stopped"] = True
            if fault == "source_change":
                monkeypatch.setitem(c.source.checkpoint_proof.RUNTIME["Scene"], "cycles", "STRING")
        return value
    c.native_hook = hook
    c.native_events.clear()
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.access.identity(c.mesh, "Mesh")
    assert c.native_after_stop == []
    assert [event[2] for event in c.native_events if event[0] == "get" and event[1] == id(c.mesh)] == ["bl_rna"]
    if fault == "stop":
        assert caught.value is primary
    else:
        assert caught.value.context["reason"] == "STORAGE_SOURCE_CHANGED"


def test_b2_role_shadow_property_refuses_before_python_getter(checkpoint_case, monkeypatch):
    c = checkpoint_case
    role, _ = c.capture()
    calls = []
    def foreign(owner):
        calls.append("foreign property")
        return owner._values["object"]
    monkeypatch.setattr(type(c.particle), "object", property(foreign), raising=False)
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.check_after_read()
    assert caught.value.context["reason"] == "NATIVE_FIELD_PYTHON_SHADOW:object"
    assert calls == []


@pytest.mark.parametrize("field", ["check", "getter", "pointer", "bpy", "types", "collection_getter"])
def test_b2_access_binding_replacement_refuses_before_foreign_dispatch(checkpoint_case, field):
    c = checkpoint_case
    role, _ = c.capture()
    calls = []
    setattr(role.access, field, lambda *_: calls.append("foreign"))
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.check_after_read()
    assert caught.value.context["reason"] == "STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED"
    assert calls == []


@pytest.mark.parametrize("field", ["check", "getter", "types", "_origin"])
def test_b2_native_return_cannot_replace_next_access_or_guard(checkpoint_case, field):
    c = checkpoint_case
    role, _ = c.capture()
    calls = []
    def effect():
        setattr(role.access, field, lambda *_: calls.append("foreign"))
        return c.settings
    c.scene.getter_hooks["tool_settings"] = effect
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.check_after_read()
    assert caught.value.context["reason"] == "STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED"
    assert calls == []


def test_b2_checked_reader_keeps_original_stored_ui_selection_refusal(checkpoint_case):
    c = checkpoint_case
    role, _ = c.capture()
    c.active.custom_values["active_selection_set"] = 0
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.check_after_read()
    assert caught.value.context["reason"] == "STORAGE_CHECKPOINT_STORED_UI_SELECTION_UNQUALIFIED"


def test_b2_unknown_settings_container_refuses_before_foreign_iteration(checkpoint_case):
    c = checkpoint_case
    role, _ = c.capture()
    calls = []
    class Foreign:
        def __iter__(self):
            calls.append("foreign iteration")
            return iter(())
    c.brush.getter_hooks["strength"] = Foreign
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.authored()
    assert caught.value.context["reason"] == "STORAGE_CHECKPOINT_VALUE_KIND_UNQUALIFIED"
    assert calls == []


def test_b2_mutable_struct_alias_cannot_admit_python_shadow(checkpoint_case, monkeypatch):
    c = checkpoint_case
    role, _ = c.capture()
    calls = []
    def foreign(_owner):
        calls.append("foreign")
        return c.scene.bl_rna
    monkeypatch.setattr(c.bpy.types, "Struct", property)
    monkeypatch.setattr(type(c.scene), "bl_rna", property(foreign))
    with pytest.raises(c.source.contract.BridgeError):
        role.check_after_read()
    assert calls == []


def test_b2_replaced_membership_never_dispatches_foreign_equality(checkpoint_case):
    c = checkpoint_case
    role, _ = c.capture()
    calls = []
    class Foreign:
        def __eq__(self, _other):
            calls.append("equality")
            return True
    role.memberships = Foreign()
    with pytest.raises(c.source.contract.BridgeError):
        role.check_after_read()
    assert calls == []


@pytest.mark.parametrize("self_count,target", [(0, "active"), (1, "none"), (1, "other"), (2, "active"), (-1, "none")])
def test_b2_initial_roles_refuse_unwitnessed_or_extra_native_owners(checkpoint_case, self_count, target):
    c = checkpoint_case
    c.counts["self"] = self_count
    c.particle._values["object"] = {"active": c.active, "none": None, "other": c.other}[target]
    with pytest.raises(c.source.contract.BridgeError):
        c.capture()


@pytest.mark.parametrize("policy", ["nested_leaf", "nested_table", "flat_leaf"])
def test_checkpoint_descriptor_policy_in_place_change_is_source_refusal(source, monkeypatch, policy):
    seal = source.SourceSeal.capture()
    proof = source.checkpoint_proof
    if policy == "nested_leaf":
        monkeypatch.setitem(proof.RUNTIME["Scene"], "cycles", "STRING")
    elif policy == "nested_table":
        monkeypatch.setitem(proof.RUNTIME, "Scene", dict(proof.RUNTIME["Scene"]))
    else:
        monkeypatch.setitem(proof.RUNTIME_FIXED, ("Scene", "cycles"), "ForeignSettings")
    with pytest.raises(source.contract.BridgeError) as caught:
        source.verify_seal(seal)
    assert caught.value.context["reason"] == "STORAGE_SOURCE_CHANGED"


def test_source_verifier_refuses_replaced_any_before_foreign_builtin_dispatch(source):
    seal = source.SourceSeal.capture()
    table = source.SourceSeal.verify.__builtins__
    original = table["any"]
    calls = []
    def foreign(*_args):
        calls.append(True)
        raise AssertionError("Foreign builtin executed")
    table["any"] = foreign
    try:
        with pytest.raises(source.contract.BridgeError):
            source.SourceSeal.verify(seal)
    finally:
        table["any"] = original
    assert calls == []


@pytest.mark.parametrize("change", ["module_function", "function_code", "class_method", "foreign_key", "module_class"])
def test_source_seal_refuses_before_foreign_callback(source, monkeypatch, change):
    seal = source.SourceSeal.capture()
    seal.verify()
    calls = []
    def foreign(*args, **kwargs):
        calls.append(True)
        raise AssertionError("foreign source executed")
    class Key:
        def __hash__(self):
            return 8191
        def __eq__(self, other):
            calls.append("equality")
            return False
    if change == "module_function":
        monkeypatch.setattr(source, "metadata_matches", foreign)
    elif change == "function_code":
        monkeypatch.setattr(source.metadata_matches, "__code__", source.metadata_matches.__code__.replace(co_name="changed"))
    elif change == "class_method":
        monkeypatch.setattr(source.Gate, "pure", foreign)
    elif change == "foreign_key":
        monkeypatch.setitem(vars(source), Key(), None)
    else:
        class Altered(ModuleType):
            @property
            def __dict__(self):
                calls.append("dictionary")
                return {}
        monkeypatch.setattr(source, "__class__", Altered)
    with pytest.raises(source.contract.BridgeError):
        seal.verify()
    assert calls == []


@pytest.mark.parametrize("inspection", [False, True])
def test_source_capture_deduplicates_fact_rows_but_retains_every_alias(source, monkeypatch, inspection):
    before = source.SourceSeal.capture(inspection=inspection)
    function_ids = {id(row[0]) for row in before[2]}
    class_ids = {id(row[0]) for row in before[1]}
    function, owner, method = source.metadata_matches, source.Gate, source.Gate.pure
    monkeypatch.setattr(source, "_capture_function_alias", function, raising=False)
    monkeypatch.setattr(source.contract, "_capture_imported_function_alias", function, raising=False)
    monkeypatch.setattr(source, "_capture_class_alias", owner, raising=False)
    monkeypatch.setattr(source.contract, "_capture_imported_class_alias", owner, raising=False)
    method_aliases = {
        "_capture_method_alias": method,
        "_capture_static_alias": staticmethod(method),
        "_capture_classmethod_alias": classmethod(method),
        "_capture_property_alias": property(method),
    }
    for name, value in method_aliases.items():
        monkeypatch.setattr(owner, name, value, raising=False)

    seal = source.SourceSeal.capture(inspection=inspection)
    source.verify_seal(seal)
    assert len(seal[2]) == len({id(row[0]) for row in seal[2]})
    assert len(seal[1]) == len({id(row[0]) for row in seal[1]})
    assert {id(row[0]) for row in seal[2]} == function_ids
    assert {id(row[0]) for row in seal[1]} == class_ids
    assert {id(row[0]) for row in seal[0]} == {id(row[0]) for row in before[0]}
    for module, fields in seal[0]:
        namespace = vars(module)
        assert len(fields) == len(namespace)
        assert all(namespace[name] is value for name, value in fields)
    source_fields = dict(next(fields for module, fields in seal[0] if module is source))
    imported_fields = dict(next(fields for module, fields in seal[0] if module is source.contract))
    assert source_fields["_capture_function_alias"] is function
    assert source_fields["_capture_class_alias"] is owner
    assert imported_fields["_capture_imported_function_alias"] is function
    assert imported_fields["_capture_imported_class_alias"] is owner
    owner_fields = dict(next(fields for kind, _mro, fields in seal[1] if kind is owner))
    assert all(owner_fields[name] is value for name, value in method_aliases.items())


def _source_capture_alias_probe(source, monkeypatch):
    marker, default, keyword_default = object(), object(), object()
    def template(value=default, *, keyword=keyword_default):
        return marker, value, keyword, importlib
    function = FunctionType(template.__code__, vars(source), "_capture_probe",
                            template.__defaults__, template.__closure__)
    function.__kwdefaults__ = dict(template.__kwdefaults__)
    monkeypatch.setattr(source, "_capture_probe", function, raising=False)
    monkeypatch.setattr(source.contract, "_capture_probe_alias", function, raising=False)
    base = type("CaptureBase", (), {"__module__": source.__name__})
    other_base = type("CaptureOtherBase", (), {"__module__": source.__name__})
    owner = type("CaptureOwner", (base,), {"__module__": source.__name__, "method": function})
    monkeypatch.setattr(source, "_capture_probe_owner", owner, raising=False)
    monkeypatch.setattr(source, "_capture_probe_owner_alias", owner, raising=False)
    return function, owner, other_base


@pytest.mark.parametrize("change", [
    "module_alias", "imported_alias", "function_code", "function_defaults", "keyword_binding",
    "keyword_value", "closure_value", "empty_closure", "globals_binding", "class_alias",
    "class_namespace", "class_mro",
])
def test_source_deduplicated_facts_keep_alias_and_metadata_drift_refusals(source, monkeypatch, change):
    function, owner, other_base = _source_capture_alias_probe(source, monkeypatch)
    seal = source.SourceSeal.capture()
    source.verify_seal(seal)
    function_rows = [row for row in seal[2] if row[0] is function]
    owner_rows = [row for row in seal[1] if row[0] is owner]
    assert len(function_rows) == len(owner_rows) == 1
    assert function_rows[0][2] is vars(source)
    calls = []
    def foreign(*_args, **_kwargs):
        calls.append("call")
        raise AssertionError("Foreign alias or metadata executed")
    if change == "module_alias":
        monkeypatch.setattr(source, "_capture_probe", foreign)
    elif change == "imported_alias":
        monkeypatch.setattr(source.contract, "_capture_probe_alias", foreign)
    elif change == "function_code":
        monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="changed"))
    elif change == "function_defaults":
        monkeypatch.setattr(function, "__defaults__", (foreign,))
    elif change == "keyword_binding":
        monkeypatch.setattr(function, "__kwdefaults__", dict(function.__kwdefaults__))
    elif change == "keyword_value":
        monkeypatch.setitem(function.__kwdefaults__, "keyword", foreign)
    elif change == "closure_value":
        monkeypatch.setattr(function.__closure__[0], "cell_contents", foreign)
    elif change == "empty_closure":
        monkeypatch.delattr(function.__closure__[0], "cell_contents")
    elif change == "globals_binding":
        monkeypatch.setattr(source, "importlib", foreign)
    elif change == "class_alias":
        monkeypatch.setattr(source, "_capture_probe_owner_alias", object())
    elif change == "class_namespace":
        monkeypatch.setattr(owner, "method", property(foreign))
    else:
        original_bases = owner.__bases__
        owner.__bases__ = (other_base,)
    try:
        with pytest.raises(source.contract.BridgeError) as caught:
            source.verify_seal(seal)
        assert caught.value.context["reason"] == "STORAGE_SOURCE_CHANGED"
        assert calls == []
    finally:
        if change == "class_mro":
            owner.__bases__ = original_bases


def test_source_capture_keeps_distinct_functions_with_shared_code(source, monkeypatch):
    function, _owner, _base = _source_capture_alias_probe(source, monkeypatch)
    clone = FunctionType(function.__code__, function.__globals__, "_capture_clone",
                         function.__defaults__, function.__closure__)
    clone.__kwdefaults__ = dict(function.__kwdefaults__)
    monkeypatch.setattr(source, "_capture_probe_clone", clone, raising=False)
    seal = source.SourceSeal.capture()
    source.verify_seal(seal)
    rows = [row for row in seal[2] if row[0] is function or row[0] is clone]
    assert len(rows) == 2
    assert {id(row[0]) for row in rows} == {id(function), id(clone)}
    assert rows[0][1] is rows[1][1]
    assert rows[0][2] is rows[1][2]
    monkeypatch.setattr(clone, "__kwdefaults__", {"keyword": object()})
    with pytest.raises(source.contract.BridgeError) as caught:
        source.verify_seal(seal)
    assert caught.value.context["reason"] == "STORAGE_SOURCE_CHANGED"


def test_source_fingerprint_binds_code_even_when_function_identity_is_retained(source, monkeypatch):
    before = source.SourceSeal.capture().fingerprint()
    fn = source.metadata_matches
    monkeypatch.setattr(fn, "__code__", fn.__code__.replace(co_name="changed"))
    after = source.SourceSeal.capture().fingerprint()
    assert before != after


@pytest.mark.parametrize("owner_name", ["graph", "source"])
def test_standard_warning_cache_updates_keep_complete_source_seal_valid(source, owner_name):
    owner = source.graph if owner_name == "graph" else source
    registry = owner.__warningregistry__
    assert type(registry) is dict
    saved = dict(registry)
    registry.clear()
    try:
        seal = source.SourceSeal.capture()
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("default", DeprecationWarning)
            for _ in range(2):
                warnings.warn_explicit("Owned standard warning-cache model", DeprecationWarning,
                                       owner.__file__, 571, module=owner.__name__, registry=registry)
                source.verify_seal(seal)
        assert len(observed) == 1 and observed[0].category is DeprecationWarning
        assert owner.__warningregistry__ is registry and type(registry["version"]) is int
    finally:
        registry.clear()
        registry.update(saved)


def test_forward_cas_permits_only_precomputed_selected_array_transition(source):
    p = source.primitive
    obj, mesh = object(), object()
    a = p.AttributeHeader("UV", "CORNER", "FLOAT2", "Float2Attribute", "Float2AttributeValue", "SINGLE", 3, "a", "b")
    b = replace(a, name="Other")
    initial = p._Metadata(obj, mesh, (("uid", "1"),), (("uid", "2"),), "main", (), (-1, ()), (a, b))
    actual = replace(initial, attributes=(replace(a, storage="ARRAY"), b))
    source.metadata_matches(actual, initial, {"UV"})
    with pytest.raises(source.contract.BridgeError):
        source.metadata_matches(actual, initial, set())
    with pytest.raises(source.contract.BridgeError):
        source.metadata_matches(replace(actual, attributes=(actual.attributes[0], replace(b, count=4))), initial, {"UV"})
    with pytest.raises(source.contract.BridgeError):
        source.metadata_matches(replace(actual, mesh=object()), initial, {"UV"})
    assert initial.attributes == (a, b) and a.storage == "SINGLE"


@pytest.fixture
def protected_gate(source, scene_jobs, monkeypatch, addon_package):  # noqa: F811
    """Genuine policy/store/gate; Blender reads remain explicit model effects."""
    env = scene_jobs
    artist = importlib.import_module(addon_package + ".tools.artist_loop")
    animation = importlib.import_module(addon_package + ".tools._animation_scope")
    errors = importlib.import_module(addon_package + ".errors")
    monkeypatch.setattr(source, "available_memory_facts", lambda: {"available_memory_bytes": 2 * 1024**3})
    env.registry.register(source.contract.PREVIEW, lambda *_args: {},
                          permissions=source.contract.PERMISSIONS, toolset="geometry")
    env.registry.enable_toolset("geometry")
    context = env.executor.context
    store = source.get_task_plans(context.state)
    store.plan = {"plan_id": "protected-plan", "protected_objects": ["Protected"]}
    store.scope = (17, (("Protected", 23),))
    store.protection = {"plan_id": "protected-plan", "scope": store.scope}
    protected = NS(name="Protected", session_uid=23, as_pointer=lambda: 23)
    untouched = NS(name="Untouched", session_uid=31, as_pointer=lambda: 31)
    bpy = NS(context=NS(scene=NS(session_uid=17, objects=[protected], as_pointer=lambda: 17),
                        view_layer=NS(objects={"Protected": protected})))
    return NS(env=env, artist=artist, animation=animation, errors=errors, context=context,
              store=store, protected=protected, untouched=untouched, bpy=bpy,
              gate=source.Gate(context, source.SourceSeal.capture(), source.contract.PREVIEW))


@pytest.mark.parametrize("scene_job_manager", ("scene", "native_save"))
@pytest.mark.parametrize("owner_name", ("graph", "source"))
@pytest.mark.parametrize("change", ("replace", "delete", "foreign"))
def test_warning_cache_binding_change_refuses_before_provider_or_native(
    source, protected_gate, monkeypatch, scene_job_manager, owner_name, change,
):
    s, calls = protected_gate, []
    owner = source.graph if owner_name == "graph" else source

    class Foreign:
        def __getattribute__(self, name):
            calls.append("foreign attribute")
            raise AssertionError("Foreign warning cache was inspected")
        def __iter__(self):
            calls.append("foreign iteration")
            raise AssertionError("Foreign warning cache was iterated")
        def __getitem__(self, key):
            calls.append("foreign indexing")
            raise AssertionError("Foreign warning cache was indexed")

    def forbidden_provider():
        calls.append("permission provider")
        raise AssertionError("Provider ran before source refusal")

    def native_reader():
        calls.append("native reader")
        raise AssertionError("Native read preceded source refusal")

    if change == "delete":
        monkeypatch.delattr(owner, "__warningregistry__")
    else:
        monkeypatch.setattr(owner, "__warningregistry__", {} if change == "replace" else Foreign())
    s.env.provider_hook = forbidden_provider
    before = s.env.provider_calls
    with pytest.raises(source.contract.BridgeError) as failure:
        s.gate.authorize()
        native_reader()
    assert failure.value.context["reason"] == "STORAGE_SOURCE_CHANGED"
    assert s.env.provider_calls == before and calls == []
    assert scene_job_manager in {"scene", "native_save"}


def test_affected_scope_dependency_modules_are_held_before_providers(source, addon_package):
    seal = source.SourceSeal.capture()
    names = {module.__name__ for module, _rows in tuple.__getitem__(seal, 0)}
    assert {addon_package + suffix for suffix in (".tools.artist_loop", ".tools._animation_scope", ".errors")} <= names
    source.verify_seal(seal)


@pytest.mark.parametrize("scene_job_manager", ("scene", "native_save"))
@pytest.mark.parametrize("native_uid", (True, False))
def test_genuine_affected_scope_remains_functional_after_authorization(protected_gate, scene_job_manager, native_uid):
    s = protected_gate
    if not native_uid:
        s.bpy.context.scene.session_uid = s.protected.session_uid = s.untouched.session_uid = None
    s.gate.authorize()
    stamp = s.artist.policy_stamp(s.context)
    s.artist.check_affected(s.context, s.bpy, (s.untouched,), stamp=stamp)
    with pytest.raises(s.errors.BridgeError) as failure:
        s.artist.check_affected(s.context, s.bpy, (s.protected,), stamp=stamp)
    assert failure.value.context["protected_scope_violation"] is True
    assert failure.value.context["affected_protected_objects"] == ["Protected"]
    assert s.store.protection["scope"] == s.store.scope
    assert s.env.provider_calls > 0 and scene_job_manager in {"scene", "native_save"}


@pytest.mark.parametrize("scene_job_manager", ("scene", "native_save"))
@pytest.mark.parametrize("change", (
    "scene_scope", "objects", "scope_alias", "bounded", "key", "islice",
    "policy_stamp", "get_task_plans", "error_factory_global", "error_class_alias",
    "helper_code", "helper_defaults", "affected_kwdefaults", "artist_module_class",
    "animation_module_class", "artist_foreign_key", "animation_foreign_key",
))
def test_permission_provider_cannot_replace_affected_scope_closure_before_native_read(
    source, protected_gate, monkeypatch, scene_job_manager, change,
):
    s, calls = protected_gate, []

    def foreign(*_args, **_kwargs):
        calls.append("foreign callback")
        raise AssertionError("Unverified affected-scope callback ran")

    class UnreadNative:
        def __getattribute__(self, _name):
            calls.append("native reader")
            raise AssertionError("Native read preceded source refusal")

    class ForeignKey:
        def __hash__(self):
            return 8191
        def __eq__(self, _other):
            calls.append("foreign equality")
            return False

    def inject():
        if change in {"scene_scope", "objects", "policy_stamp", "get_task_plans"}:
            name = {"scene_scope": "_scene_scope", "objects": "_objects"}.get(change, change)
            monkeypatch.setattr(s.artist, name, foreign)
        elif change == "scope_alias":
            monkeypatch.setattr(s.artist, "scope", NS(bounded=foreign, key=foreign))
        elif change in {"bounded", "key", "islice"}:
            monkeypatch.setattr(s.animation, change, foreign)
        elif change == "error_factory_global":
            monkeypatch.setattr(s.errors, "BridgeError", foreign)
        elif change == "error_class_alias":
            monkeypatch.setattr(s.animation, "BridgeError", foreign)
        elif change == "helper_code":
            fn = s.artist._scene_scope
            monkeypatch.setattr(fn, "__code__", fn.__code__.replace(co_name="changed"))
        elif change == "helper_defaults":
            monkeypatch.setattr(s.animation.bounded, "__defaults__", (foreign,))
        elif change == "affected_kwdefaults":
            monkeypatch.setitem(s.artist.check_affected.__kwdefaults__, "stamp", foreign)
        elif change.endswith("module_class"):
            class Altered(ModuleType):
                @property
                def __dict__(self):
                    calls.append("foreign module dictionary")
                    return {}
            monkeypatch.setattr(s.artist if change.startswith("artist") else s.animation, "__class__", Altered)
        else:
            monkeypatch.setitem(vars(s.artist if change.startswith("artist") else s.animation), ForeignKey(), None)

    s.env.provider_hook = inject
    before = s.env.provider_calls
    with pytest.raises(source.contract.BridgeError) as failure:
        s.gate.authorize()
        # This is the same held pre-provider authorization ordering used before
        # the concrete protected resolver reaches check_affected. The stamp
        # mismatch also exercises its direct error-factory dependency.
        s.artist.check_affected(s.context, UnreadNative(), (s.untouched,), stamp=("wrong", -1))
    assert failure.value.context["reason"] == "STORAGE_SOURCE_CHANGED"
    assert s.env.provider_calls > before
    assert calls == [] and scene_job_manager in {"scene", "native_save"}


def _b2_owned_keys_case(case, monkeypatch, *, native_error=None, guard_phase=None, guard_error=None, guard_effect=None):
    """Model only C keys/error bindings; exercise real call/helper/settings."""
    import sys

    source, events, armed = case.source, [], [False]
    original_method = source._CheckpointRoleAccess.method

    def owned_keys():
        events.append("native_keys")
        if armed[0] and native_error is not None:
            raise native_error
        return ()

    def method(self, owner, name):
        if owner is case.brush and name == "keys":
            return owned_keys
        return original_method(self, owner, name)

    def check():
        if not armed[0]:
            return
        caller = sys._getframe(1)
        values = caller.f_locals
        args = values.get("args")
        if (caller.f_code is source._CheckpointRoleAccess.call.__code__
                and values.get("function") is source._checkpoint_native_keys
                and type(args) is tuple and len(args) == 1 and args[0] is owned_keys):
            phase = "pre" if values["stage"] == 0 else "post"
        elif caller.f_code is source._CheckpointRoleAccess.settings.__code__ and "native_keys" in events:
            phase = "extra"
        else:
            return
        events.append(phase)
        if guard_effect is not None:
            guard_effect(phase)
        if guard_phase == phase:
            raise guard_error

    monkeypatch.setattr(source._CheckpointRoleAccess, "method", method)
    case.gate.pure = check
    role, _ = case.capture()
    events.clear()
    armed[0] = True
    return role, events


def test_b2_native_keys_exact_unsupported_typeerror_keeps_original_three_checks(checkpoint_case, monkeypatch):
    primary = TypeError("bpy_struct.keys(): this type doesn't support IDProperties")
    role, events = _b2_owned_keys_case(checkpoint_case, monkeypatch, native_error=primary)
    assert role.access.settings(checkpoint_case.brush) == ((("strength", 0.5),), ())
    assert events == ["pre", "native_keys", "post", "extra"]


def test_b2_native_keys_success_keeps_two_checks(checkpoint_case, monkeypatch):
    role, events = _b2_owned_keys_case(checkpoint_case, monkeypatch)
    assert role.access.settings(checkpoint_case.brush) == ((("strength", 0.5),), ())
    assert events == ["pre", "native_keys", "post"]


def test_b2_native_keys_foreign_typeerror_never_formats_or_reads_foreign_args(checkpoint_case, monkeypatch):
    calls = []

    class ForeignTypeError(TypeError):
        def __str__(self):
            calls.append("str")
            return "doesn't support IDProperties"

        def __repr__(self):
            calls.append("repr")
            return "foreign"

        def __getattribute__(self, name):
            if name == "args":
                calls.append("args")
            return super().__getattribute__(name)

    primary = ForeignTypeError("doesn't support IDProperties")
    role, events = _b2_owned_keys_case(checkpoint_case, monkeypatch, native_error=primary)
    with pytest.raises(TypeError) as caught:
        role.access.settings(checkpoint_case.brush)
    assert caught.value is primary
    assert calls == []
    assert events[:3] == ["pre", "native_keys", "post"]
    assert events.count("native_keys") == 1


@pytest.mark.parametrize("shape", ["empty", "multiple", "foreign_value", "string_subclass", "unrelated_message"])
def test_b2_native_keys_malformed_error_rethrows_original_without_payload_dispatch(checkpoint_case, monkeypatch, shape):
    calls = []

    class Foreign:
        def __str__(self):
            calls.append("str")
            return "doesn't support IDProperties"

        def __repr__(self):
            calls.append("repr")
            return "foreign"

        def __bool__(self):
            calls.append("bool")
            return True

    class ForeignString(str):
        def __str__(self):
            calls.append("str-subclass")
            return "doesn't support IDProperties"

        def __contains__(self, _needle):
            calls.append("contains-subclass")
            return True

    args = {
        "empty": (),
        "multiple": ("doesn't support IDProperties", "extra"),
        "foreign_value": (Foreign(),),
        "string_subclass": (ForeignString("doesn't support IDProperties"),),
        "unrelated_message": ("unrelated native error",),
    }[shape]
    primary = TypeError(*args)
    role, events = _b2_owned_keys_case(checkpoint_case, monkeypatch, native_error=primary)
    with pytest.raises(TypeError) as caught:
        role.access.settings(checkpoint_case.brush)
    assert caught.value is primary and calls == []
    assert events[:3] == ["pre", "native_keys", "post"]
    assert events.count("native_keys") == 1


@pytest.mark.parametrize("phase,native_unsupported", [("pre", False), ("pre", True), ("post", False), ("post", True), ("extra", True)])
def test_b2_matching_guard_typeerror_never_becomes_native_keys_admission(checkpoint_case, monkeypatch, phase, native_unsupported):
    message = "bpy_struct.keys(): this type doesn't support IDProperties"
    primary = TypeError(message)
    native_error = TypeError(message) if native_unsupported else None
    role, events = _b2_owned_keys_case(checkpoint_case, monkeypatch,
        native_error=native_error, guard_phase=phase, guard_error=primary)
    with pytest.raises(TypeError) as caught:
        role.access.settings(checkpoint_case.brush)
    assert caught.value is primary
    expected = {"pre": ["pre"], "post": ["pre", "native_keys", "post"],
                "extra": ["pre", "native_keys", "post", "extra"]}
    assert events == expected[phase]
    assert events.count("native_keys") == (0 if phase == "pre" else 1)


def test_b2_native_keys_non_typeerror_preserves_primary_without_later_guard(checkpoint_case, monkeypatch):
    primary = RuntimeError("native keys fault")
    role, events = _b2_owned_keys_case(checkpoint_case, monkeypatch, native_error=primary)
    with pytest.raises(RuntimeError) as caught:
        role.access.settings(checkpoint_case.brush)
    assert caught.value is primary
    assert events == ["pre", "native_keys"]


@pytest.mark.parametrize("field", ["getter", "check", "_origin"])
def test_b2_third_native_error_check_keeps_held_accessor_origin_fence(checkpoint_case, monkeypatch, field):
    """Private guard-boundary parity; ordinary Gate.pure is provider-free."""
    c, held, calls = checkpoint_case, [None], []
    primary = TypeError("bpy_struct.keys(): this type doesn't support IDProperties")
    def foreign(*_args):
        calls.append("foreign")
        return None
    def effect(phase):
        if phase == "extra":
            setattr(held[0].access, field, foreign)
    role, events = _b2_owned_keys_case(c, monkeypatch, native_error=primary, guard_effect=effect)
    held[0] = role
    with pytest.raises(c.source.contract.BridgeError) as caught:
        role.access.settings(c.brush)
    assert caught.value.context["reason"] == "STORAGE_CHECKPOINT_ROLE_ACCESS_CHANGED"
    assert events == ["pre", "native_keys", "post", "extra"]
    assert calls == []
