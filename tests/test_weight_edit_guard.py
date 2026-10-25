"""Portable registered-call models, never native group/window qualification."""

from __future__ import annotations

import builtins
import importlib
import struct
from contextlib import contextmanager
from dataclasses import replace
from types import FunctionType, ModuleType
from types import SimpleNamespace as NS

import pytest


def bits(value):
    return struct.pack("<f", value).hex()


class Reader:
    def __init__(self, case):
        self.case = case

    def snapshot(self):
        c = self.case
        c.events.append("snapshot")
        if not c.valid:
            raise c.errors.BridgeError("NOT_IMPLEMENTED", "Native identity invalid before payload")
        if c.on_snapshot is not None:
            c.on_snapshot()
        return c.native

    def resolve(self, vertex, group, expected, value):
        c = self.case
        c.events.append("resolve")
        if c.on_resolve is not None:
            c.on_resolve()
        if not c.valid or c.native != expected or group not in c.native.memberships.groups:
            raise c.errors.BridgeError("NOT_IMPLEMENTED", "Closed leaf lost complete expected prefix")

        def native_model():
            c.events.append("write")
            c.writes.append((vertex, group.index, value))
            count = len(c.writes)
            if c.failure == (count, "before"):
                raise RuntimeError("model native setter failed before store")
            c.native = replace(c.native, memberships=c.intent.replace_member(
                c.native.memberships, vertex, group.index, value))
            if c.on_write is not None:
                c.on_write(count)
            if c.failure == (count, "after"):
                raise RuntimeError("model native setter failed after store")
        return native_model


@pytest.fixture
def model(addon_package, monkeypatch):
    guard = importlib.import_module(f"{addon_package}.weight_edit_guard")
    intent = importlib.import_module(f"{addon_package}.weight_edit_plan")
    tools = importlib.import_module(f"{addon_package}.tools.weights")
    registry_mod = importlib.import_module(f"{addon_package}.tool_registry")
    permission_mod = importlib.import_module(f"{addon_package}.permissions")
    state_mod = importlib.import_module(f"{addon_package}.state")
    errors = importlib.import_module(f"{addon_package}.errors")
    case = NS(guard=guard, intent=intent, tools=tools, errors=errors, registry_mod=registry_mod,
              state_mod=state_mod, permission_mod=permission_mod, provider=None, cancel=None,
              on_write=None, on_resolve=None, on_snapshot=None, writes=[], events=[], valid=True,
              failure=None, reader_count=0)
    case.grants = {p.value: p is permission_mod.Permission.EDIT_MESH for p in permission_mod.Permission}
    snapshot = intent.MembershipSnapshot(
        (intent.GroupState(0, "A", 101, False), intent.GroupState(1, "B", 102, False),
         intent.GroupState(2, "Locked", 103, True)),
        (((0, bits(.25)), (1, bits(.25)), (2, bits(.125))),
         ((0, bits(.5)), (1, bits(0.)), (2, bits(-0.))),
         ((1, bits(.75)), (2, bits(.125)))))
    case.native = guard.NativeState(("native-model", (11, 201), (12, 202),
                                    ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)), "OBJECT"), snapshot)
    case.original = case.native
    case.reader = Reader(case)

    def native_reader(*_args):
        case.reader_count += 1
        return case.reader
    monkeypatch.setattr(guard, "_NativeReader", native_reader)

    def permissions():
        case.events.append("permission")
        if case.provider is not None:
            case.provider()
        return dict(case.grants)

    state = state_mod.BridgeState()
    registry = registry_mod.ToolRegistry(enabled_toolsets=("weights", "batch"))
    context = registry_mod.ToolContext(state, permission_mod.PermissionManager(permissions), registry, NS())

    def cancel():
        if case.cancel:
            raise errors.BridgeError(case.cancel, "Model caller stopped")
    context.check_cancelled = cancel
    tools.register_tools(registry)
    case.state, case.registry, case.context = state, registry, context
    case.params = {"object_name": "Mesh", "group_name": "A", "vertex_indices": [0, 1], "weight": .75}
    case.call = lambda method="weights.assign", params=None: registry.dispatch(
        method, case.params if params is None else params, context)

    @contextmanager
    def admitted():
        spec = registry.get("weights.assign")
        with (registry.mutation_entry(spec, case.params, context),
              registry.checkpoint_admission(spec, case.params, context)):
            yield guard.current(context, spec.name, case.params)
    case.admitted = admitted
    return case


def test_assignment_has_exact_complete_membership_readback_and_history(model):
    result = model.call()
    expected = model.intent.replace_member(model.original.memberships, 0, 0, bits(.75))
    expected = model.intent.replace_member(expected, 1, 0, bits(.75))
    assert model.native == replace(model.original, memberships=expected)
    assert result["updated_memberships"] == 2
    assert result["complete_membership_readback_verified"]
    receipt = result["recovery_evidence"]
    assert receipt["owned_membership_verified"] == 2 and receipt["native_update_attempts"] == 0
    assert model.state_mod.bounded_recovery_evidence(receipt) == receipt
    record = model.state.record_operation(tool="weights.assign", description="Direct weights", success=True,
                                          duration_ms=1., recovery_evidence=receipt)
    assert record.recovery_evidence == receipt
    assert model.reader_count == 1 and model.context.checkpoint_admission is None


def test_normalization_preserves_all_unselected_groups_and_zero_presence(model):
    result = model.call("weights.normalize", {"object_name": "Mesh", "group_names": ["A", "B"],
                                               "vertex_indices": [0, 1]})
    rows = model.native.memberships.memberships
    assert rows[0] == ((0, bits(.4375)), (1, bits(.4375)), (2, bits(.125)))
    assert rows[1] == ((0, bits(1.)), (1, bits(0.)), (2, bits(-0.)))
    assert rows[2] == model.original.memberships.memberships[2]
    assert result["recovery_evidence"]["owned_membership_verified"] == 3


@pytest.mark.parametrize("value", [None, 0., -0.])
def test_absent_zero_and_signed_zero_assignment_are_distinct(model, value):
    params = {**model.params, "vertex_indices": [2], "weight": value}
    model.call(params=params)
    members = dict(model.native.memberships.memberships[2])
    assert (members.get(0) is None) if value is None else members[0] == bits(value)
    assert len(model.writes) == (0 if value is None else 1)


def test_noop_uses_no_membership_setter_or_explicit_update(model):
    result = model.call(params={**model.params, "vertex_indices": [0], "weight": .25})
    assert not result["changed"] and model.writes == []
    assert model.native == model.original
    assert result["recovery_evidence"]["native_update_attempts"] == 0


@pytest.mark.parametrize("field", ["weight", "object_name", "vertex_indices"])
def test_first_provider_cannot_replace_original_request(model, field):
    def provider():
        model.params[field] = {"weight": .5, "object_name": "Other", "vertex_indices": [2]}[field]
    model.provider = provider
    with pytest.raises(model.errors.BridgeError):
        model.call()
    assert model.writes == [] and model.reader_count == 1


def test_first_provider_cannot_adopt_a_new_membership_baseline(model):
    def provider():
        model.native = replace(model.native, memberships=model.intent.replace_member(
            model.native.memberships, 2, 1, bits(.9)))
    model.provider = provider
    with pytest.raises(model.errors.BridgeError):
        model.call()
    assert model.writes == [] and model.native != model.original


@pytest.mark.parametrize("when", ["before", "after"])
def test_native_exception_restores_only_independently_verified_owned_fields(model, when):
    model.failure = (2, when)
    with pytest.raises(model.errors.BridgeError) as caught:
        model.call(params={**model.params, "vertex_indices": [0, 1, 2]})
    assert model.native == model.original
    assert not any(vertex == 2 for vertex, _group, _value in model.writes)
    receipt = caught.value.context["recovery_evidence"]
    assert receipt["rollback_verified"] and receipt["observed_sha256"] == receipt["before_sha256"]
    assert receipt["restoration_attempts"] == (1 if when == "before" else 2)
    assert model.state_mod.bounded_recovery_evidence(receipt) == receipt


@pytest.mark.parametrize("stop", ["PERMISSION_DENIED", "AGENT_PAUSED", "EMERGENCY_STOPPED", "REQUEST_CANCELLED", "TIMEOUT"])
def test_revocation_after_first_write_forbids_compensation_and_late_writes(model, stop):
    def written(count):
        if count != 1:
            return
        if stop == "PERMISSION_DENIED":
            model.grants["EDIT_MESH"] = False
        elif stop == "AGENT_PAUSED":
            model.state.set_paused(True)
        elif stop == "EMERGENCY_STOPPED":
            model.state.set_emergency_stopped(True)
        else:
            model.cancel = stop
    model.on_write = written
    with pytest.raises(model.errors.BridgeError) as caught:
        model.call()
    assert len(model.writes) == 1
    receipt = caught.value.context["recovery_evidence"]
    assert receipt["restoration_refused"] == "AUTHORITY_LOST"
    assert receipt["restoration_attempts"] == 0 and not receipt["rollback_verified"]


def test_foreign_unwritten_membership_change_stops_without_overwriting_it(model):
    def written(count):
        if count == 1:
            model.native = replace(model.native, memberships=model.intent.replace_member(
                model.native.memberships, 2, 1, bits(.9)))
    model.on_write = written
    with pytest.raises(model.errors.BridgeError) as caught:
        model.call()
    assert len(model.writes) == 1
    assert dict(model.native.memberships.memberships[2])[1] == bits(.9)
    receipt = caught.value.context["recovery_evidence"]
    assert receipt["restoration_refused"] == "UNKNOWN_WRITE_RESULT" and receipt["observed_sha256"] is None


def test_group_recreation_pointer_change_is_refused_before_leaf(model):
    def provider():
        groups = model.native.memberships.groups
        model.native = replace(model.native, memberships=replace(model.native.memberships,
            groups=(replace(groups[0], pointer=301), *groups[1:])))
    model.provider = provider
    with pytest.raises(model.errors.BridgeError):
        model.call()
    assert not model.writes


def test_closed_leaf_rejects_drift_after_broad_snapshot(model):
    model.on_resolve = lambda: setattr(model, "valid", False)
    with pytest.raises(model.errors.BridgeError) as caught:
        model.call()
    assert not model.writes
    assert caught.value.context["recovery_evidence"]["restoration_refused"] == "INVALID_NATIVE_SCOPE"


def test_sticky_unknown_cannot_be_reopened_by_restoring_original_values(model):
    with model.admitted() as guard:
        model.native = replace(model.native, preservation=("foreign",))
        with pytest.raises(model.errors.BridgeError):
            guard.execute()
        assert guard.refusal == "STATE_CHANGED"
        model.native = model.original
        with pytest.raises(model.errors.BridgeError):
            guard.execute()
    assert model.writes == []


def test_original_factory_cannot_be_recaptured_or_substituted(model):
    with pytest.raises(model.errors.BridgeError, match="original registered factory"):
        model.tools.assign(model.context, model.params)
    with model.admitted() as guard:
        guard.plan = replace(guard.plan, object_name="Foreign")
        with pytest.raises(model.errors.BridgeError):
            guard.execute()
    assert model.writes == []


def test_factory_refuses_invalid_request_before_reader_payload(model):
    with pytest.raises(model.errors.BridgeError):
        model.call(params={**model.params, "unknown": 1})
    assert model.reader_count == 0 and "snapshot" not in model.events


def test_two_methods_alone_add_factory_and_exclusive_metadata(model):
    for name in ("assign", "normalize"):
        spec = model.registry.get("weights." + name)
        assert spec.automatic_checkpoint and spec.exclusive_mutation
        assert spec.checkpoint_admission_factory is not None
        assert not spec.checkpoint_batch_reviewed and spec.protected_scope_resolver is None
    for name in ("group_create", "smooth", "transfer"):
        spec = model.registry.get("weights." + name)
        assert spec.checkpoint_admission_factory is None and not spec.exclusive_mutation


def test_unknown_native_window_still_refuses_before_any_blender_access(addon_package):
    guard = importlib.import_module(f"{addon_package}.weight_edit_guard")
    with pytest.raises(guard.BridgeError) as caught:
        guard._NativeReader(None, None)
    assert caught.value.context["native_profile_qualified"] is False


@pytest.fixture
def ordinary_origin(addon_package, monkeypatch):
    """Construct real services, but never import Blender or invoke a provider."""
    guard = importlib.import_module(f"{addon_package}.weight_edit_guard")
    runtime = guard._runtime
    active = runtime.BridgeRuntime()
    monkeypatch.setattr(runtime, "_RUNTIME", active)
    reader = object.__new__(guard._NativeReader)
    reader.context = active.executor.context
    return NS(guard=guard, runtime=runtime, active=active, reader=reader)


def test_ordinary_origin_uses_canonical_services_without_calling_provider(ordinary_origin, monkeypatch):
    case = ordinary_origin
    before = case.active.permissions._source
    evidence = case.reader._ordinary_origin()
    assert evidence[0] is case.active and evidence[1] is before
    case.reader._origin = evidence
    case.reader._check_origin()
    monkeypatch.setattr(case.active.executor, "state", case.runtime.BridgeState())
    with pytest.raises(case.guard.BridgeError):
        case.reader._check_origin()


@pytest.mark.parametrize("change", ["provider", "preferences", "final", "cancel", "job"])
def test_unknown_ordinary_hook_origin_refuses_before_blender(ordinary_origin, monkeypatch, change):
    case, context = ordinary_origin, ordinary_origin.reader.context
    if change == "provider":
        monkeypatch.setattr(context.permissions, "_source", lambda: {})
    elif change == "preferences":
        monkeypatch.setattr(case.runtime, "_preferences", lambda: None)
    elif change == "final":
        context.check_final_request = lambda: None
    elif change == "cancel":
        context.check_cancelled = lambda: None
    else:
        context.check_final_job = lambda: None
    with pytest.raises(case.guard.BridgeError):
        case.reader._ordinary_origin()


def _callback_poison(calls):
    namespace = {"calls": calls}
    exec("def poison(*args, **kwargs):\n calls.append('callback')\n raise AssertionError('Unexpected callback')", namespace)
    return namespace["poison"]


@pytest.mark.parametrize("change", [
    "wrapper", "wrapper_code", "wrapper_defaults", "wrapper_foreign_globals",
    "base", "base_code", "base_globals", "base_defaults", "base_map",
    "proof", "proof_code", "proof_globals", "proof_retained_code", "proof_helpers",
    "constructor_code", "preferences_code", "preferences_defaults", "source_defaults", "source_closure",
    "grant_class", "statement_class", "statement_init", "grant_helper", "grant_helper_code",
    "grant_helper_globals", "grant_helper_kwdefaults", "grant_helper_closure", "generation_property", "generation_code",
    "grant_attribute", "runtime_attribute", "enum_iterator", "enum_value", "enum_map", "enum_member",
    "jobs_export", "jobs_subclass", "jobs_grant", "foreign_grant", "foreign_authority", "foreign_generation",
    "grant_origin", "grant_thread", "registered_type", "time_helper", "thread_helper", "builtins_alias",
    "runtime_module", "policy_module", "permissions_module", "math_module", "import_hook",
    "enum_descriptor_fget", "enum_descriptor_get",
])
def test_h01_dependency_poison_refuses_before_provider_or_blender(ordinary_origin, monkeypatch, addon_package, change):
    case, calls = ordinary_origin, []
    runtime, guard = case.runtime, case.guard
    policy, permissions = guard._save_policy, guard._permissions
    poison = _callback_poison(calls)
    utils = importlib.import_module(f"{addon_package}.utils")
    with monkeypatch.context() as patch:
        patch.setattr(utils, "require_blender", poison)
        if change.endswith("_module"):
            class ForeignModule(ModuleType):
                def __getattribute__(self, name):
                    return poison()
            module = {"runtime_module": runtime, "policy_module": policy,
                      "permissions_module": permissions, "math_module": policy.math}[change]
            patch.setattr(module, "__class__", ForeignModule)
        elif change == "builtins_alias":
            patch.setitem(vars(runtime), "__builtins__", {"__import__": poison})
        elif change == "import_hook":
            patch.setitem(vars(runtime), "__builtins__", {**runtime._preferences.__builtins__, "__import__": poison})
            foreign = FunctionType(runtime._preferences.__code__, vars(runtime))
            patch.setattr(runtime, "_preferences", foreign)
            patch.setattr(runtime, "_PREFERENCES_FUNCTION", foreign)
        elif change == "enum_descriptor_fget":
            patch.setattr(guard._ENUM_VALUE_PROPERTY, "fget", poison)
        elif change == "enum_descriptor_get":
            patch.setattr(type(guard._ENUM_VALUE_PROPERTY).__get__, "__code__", poison.__code__)
        elif change in {"wrapper", "base", "proof"}:
            module, name = {"wrapper": (runtime, "permission_snapshot"),
                            "base": (runtime, "_base_permission_snapshot"),
                            "proof": (runtime, "native_save_permission_provider_intact")}[change]
            patch.setattr(module, name, poison)
        elif change in {"wrapper_code", "base_code", "proof_code", "constructor_code", "preferences_code",
                        "grant_helper_code", "generation_code", "enum_iterator", "enum_value"}:
            function = {"wrapper_code": runtime.permission_snapshot, "base_code": permissions.permission_snapshot,
                        "proof_code": runtime.native_save_permission_provider_intact,
                        "constructor_code": runtime.BridgeRuntime.__init__, "preferences_code": runtime._preferences,
                        "grant_helper_code": policy.NativeSaveGrant._now,
                        "generation_code": policy.NativeSaveGrant.generation.fget,
                        "enum_iterator": type(permissions.Permission).__iter__,
                        "enum_value": vars(guard.Enum)["value"].fget}[change]
            patch.setattr(function, "__code__", poison.__code__)
        elif change == "wrapper_foreign_globals":
            function = runtime.permission_snapshot
            patch.setattr(runtime, "permission_snapshot", FunctionType(function.__code__, {**vars(runtime),
                "_base_permission_snapshot": poison}))
        elif change in {"wrapper_defaults", "base_defaults", "preferences_defaults", "source_defaults"}:
            function = {"wrapper_defaults": runtime.permission_snapshot, "base_defaults": permissions.permission_snapshot,
                        "preferences_defaults": runtime._preferences, "source_defaults": case.active.permissions._source}[change]
            patch.setattr(function, "__defaults__", (poison,))
        elif change == "base_globals":
            patch.setitem(vars(permissions), "getattr", poison)
        elif change == "base_map":
            patch.setitem(permissions.PREFERENCE_PROPERTIES, permissions.Permission.EDIT_MESH, "allow_delete_objects")
        elif change in {"proof_globals", "proof_retained_code", "proof_helpers"}:
            patch.setattr(runtime, {"proof_globals": "FunctionType", "proof_retained_code": "_BASE_PERMISSION_SNAPSHOT_CODE",
                                   "proof_helpers": "_GRANT_HELPERS"}[change], poison)
        elif change in {"grant_class", "statement_class"}:
            patch.setattr(policy, "NativeSaveGrant" if change == "grant_class" else "GrantStatement", poison)
        elif change == "statement_init":
            patch.setattr(policy.GrantStatement, "__init__", poison)
        elif change == "grant_helper":
            patch.setattr(policy.NativeSaveGrant, "active", poison)
        elif change == "grant_helper_globals":
            patch.setattr(policy, "time", NS(monotonic=poison))
        elif change == "grant_helper_kwdefaults":
            patch.setitem(policy.NativeSaveGrant.active.__kwdefaults__, "now", poison)
        elif change in {"source_closure", "grant_helper_closure"}:
            def make_foreign(callback):
                return lambda *args, **kwargs: callback()
            if change == "source_closure":
                patch.setattr(case.active.permissions, "_source", make_foreign(poison))
            else:
                patch.setattr(policy.NativeSaveGrant, "active", make_foreign(poison))
        elif change == "generation_property":
            patch.setattr(policy.NativeSaveGrant, "generation", property(poison))
        elif change in {"grant_attribute", "runtime_attribute"}:
            patch.setattr(policy.NativeSaveGrant if change == "grant_attribute" else runtime.BridgeRuntime,
                          "__getattribute__", poison, raising=False)
        elif change == "enum_map":
            patch.setitem(permissions.Permission._member_map_, "EDIT_MESH", permissions.Permission.DELETE_OBJECTS)
        elif change == "enum_member":
            patch.setattr(permissions.Permission.EDIT_MESH, "_value_", "DELETE_OBJECTS")
        elif change == "jobs_export":
            patch.setattr(runtime, "NativeSaveJobs", poison)
        elif change == "jobs_subclass":
            class ForeignJobs(guard._NATIVE_SAVE_JOBS):
                @property
                def active(self):
                    return poison()
            foreign = object.__new__(ForeignJobs)
            patch.setattr(case.active, "jobs", foreign)
            patch.setattr(case.reader.context, "jobs", foreign)
            patch.setattr(case.active.executor, "jobs", foreign)
        elif change in {"jobs_grant", "foreign_grant"}:
            grant = policy.NativeSaveGrant(case.active._native_save_generation, case.active._native_save_local_authority)
            if change == "jobs_grant":
                patch.setattr(case.active.jobs, "native_save_policy", grant)
            else:
                patch.setattr(case.active, "native_save_policy", grant)
                patch.setattr(case.active.jobs, "native_save_policy", grant)
        elif change == "foreign_authority":
            patch.setattr(case.active, "_native_save_local_authority", object())
        elif change == "foreign_generation":
            patch.setattr(case.active, "_native_save_generation", "foreign-generation")
        elif change == "grant_origin":
            patch.setattr(case.active, "_native_save_policy_origin", object())
        elif change == "grant_thread":
            grant = policy.NativeSaveGrant(case.active._native_save_generation, case.active._native_save_local_authority)
            object.__setattr__(grant, "_thread", grant._thread + 1)
            patch.setattr(case.active, "native_save_policy", grant)
            patch.setattr(case.active, "_native_save_policy_origin", grant)
            patch.setattr(case.active.jobs, "native_save_policy", grant)
        elif change == "registered_type":
            patch.setattr(case.active, "_registered", poison)
        elif change == "time_helper":
            patch.setattr(policy.time, "monotonic", poison)
        else:
            patch.setattr(policy.threading, "current_thread", poison)
        with pytest.raises(guard.BridgeError):
            guard._NativeReader(case.reader.context, {"object_name": "Mesh"})
    assert calls == []


def test_native_grant_lifecycle_never_becomes_ordinary_weight_authority(ordinary_origin):
    case = ordinary_origin
    original = case.reader._ordinary_origin()
    case.reader._origin = original
    grant = case.active.native_save_policy
    grant.arm(case.active._native_save_local_authority, 1, now=0.)  # Already expired on real monotonic time.
    case.reader._check_origin()
    grant.revoke()
    case.reader._check_origin()
    assert all(first is second for first, second in zip(original, case.reader._ordinary_origin(), strict=True))


def test_only_native_flag_changes_with_registered_grant_lifecycle(ordinary_origin):
    case = ordinary_origin
    case.active._registered = True
    case.reader._origin = case.reader._ordinary_origin()
    preferences = NS(allow_edit_mesh=True)
    base = case.guard._permissions.permission_snapshot(preferences)
    snapshots = [case.runtime.permission_snapshot(preferences)]
    case.active.native_save_policy.arm(case.active._native_save_local_authority, 60)
    case.reader._check_origin()
    snapshots.append(case.runtime.permission_snapshot(preferences))
    case.active.native_save_policy.revoke()
    case.reader._check_origin()
    snapshots.append(case.runtime.permission_snapshot(preferences))
    assert [row["NATIVE_SAVE_EFFECTS"] for row in snapshots] == [False, True, False]
    assert all({key: value for key, value in row.items() if key != "NATIVE_SAVE_EFFECTS"}
               == {key: value for key, value in base.items() if key != "NATIVE_SAVE_EFFECTS"} for row in snapshots)


def test_h01_dependency_change_after_origin_cannot_pass_final_fence(ordinary_origin, monkeypatch):
    case = ordinary_origin
    case.reader._origin = case.reader._ordinary_origin()
    poison = _callback_poison([])
    monkeypatch.setattr(case.runtime, "_GRANT_HELPERS", (poison,))
    with pytest.raises(case.guard.BridgeError):
        case.reader._check_origin()


@pytest.mark.parametrize("name", ["_h01_origin", "_function_intact", "_mapping_intact", "_error"])
@pytest.mark.parametrize("change", ["replacement", "code", "defaults", "foreign_globals"])
def test_local_origin_comparators_are_authenticated_before_call(ordinary_origin, monkeypatch, name, change):
    case, calls = ordinary_origin, []
    guard = case.guard
    original = getattr(guard, name)
    poison = _callback_poison(calls)
    if change == "replacement":
        monkeypatch.setattr(guard, name, poison)
    elif change == "code":
        monkeypatch.setattr(original, "__code__", poison.__code__)
    elif change == "defaults":
        monkeypatch.setattr(original, "__defaults__", (poison,))
    else:
        monkeypatch.setattr(guard, name, FunctionType(original.__code__, {**vars(guard), "_PURE_TYPE": poison}))
    with pytest.raises(guard.BridgeError):
        case.reader._ordinary_origin()
    assert calls == []


def test_enum_metaclass_attribute_hook_cannot_run_during_raw_namespace_proof(ordinary_origin, monkeypatch):
    case, calls = ordinary_origin, []
    meta = type(case.guard._permissions.Permission)
    with monkeypatch.context() as patch:
        patch.setattr(meta, "__getattribute__", _callback_poison(calls), raising=False)
        with pytest.raises(case.guard.BridgeError):
            case.reader._ordinary_origin()
    assert calls == []


@pytest.mark.parametrize("name", ["type", "any", "all", "vars", "len"])
def test_actual_builtin_poison_refuses_without_calling_it(ordinary_origin, name):
    case, calls = ordinary_origin, []
    original = getattr(builtins, name)
    poison = _callback_poison(calls)
    # Restore before pytest handles/asserts anything: its own machinery uses the
    # same real builtin map. Only the closed entry runs while it is poisoned.
    caught = None
    setattr(builtins, name, poison)
    try:
        try:
            case.reader._ordinary_origin()
        except case.guard.BridgeError as error:
            caught = error
    finally:
        setattr(builtins, name, original)
    assert caught is not None and calls == []


@pytest.mark.parametrize("name", ["_PURE_NAMESPACE", "_PURE_BUILTINS", "_PURE_ALIASES",
                                  "_PURE_BUILTIN_FACTS", "_LOCAL_FACTS"])
def test_origin_root_shapes_are_checked_before_container_callbacks(ordinary_origin, monkeypatch, name):
    case, calls = ordinary_origin, []

    class ForeignContainer:
        def __iter__(self):
            calls.append("iter")
            raise AssertionError("Root iterator must not run")

        def __getitem__(self, _key):
            calls.append("item")
            raise AssertionError("Root item callback must not run")

        def get(self, *_args):
            calls.append("get")
            raise AssertionError("Root get callback must not run")

    monkeypatch.setattr(case.guard, name, ForeignContainer())
    with pytest.raises(case.guard.BridgeError):
        case.reader._ordinary_origin()
    assert calls == []


def test_origin_rejects_foreign_native_namespace_identity(ordinary_origin, monkeypatch):
    case = ordinary_origin
    monkeypatch.setattr(case.guard, "_PURE_NAMESPACE", dict(vars(case.guard)))
    with pytest.raises(case.guard.BridgeError):
        case.reader._ordinary_origin()


@pytest.mark.parametrize("raises", [False, True])
def test_native_leaf_prebuilt_arguments_and_method_release(addon_package, raises):
    guard = importlib.import_module(f"{addon_package}.weight_edit_guard")
    arguments = ((1,), .5, "REPLACE")
    leaf = guard._NativeLeaf(arguments)
    seen = []

    def method(*values):
        seen.append(values)
        if raises:
            raise RuntimeError("model native call")
        return "done"

    leaf.method = method
    if raises:
        with pytest.raises(RuntimeError):
            leaf()
    else:
        assert leaf() == "done"
    assert seen == [arguments] and leaf.arguments is arguments and leaf.method is None


@pytest.fixture
def mesh_runtime_model(addon_package, monkeypatch):
    """Descriptor/presence models only; no claim of genuine native admission."""
    guard = importlib.import_module(f"{addon_package}.weight_edit_guard")
    presence_calls = []
    case = NS(guard=guard, stored=False, presence_calls=presence_calls)

    def prop(name, kind, readonly, pointer, **extra):
        return NS(identifier=name, type=kind, is_readonly=readonly, is_runtime=False,
                  is_registered=False, fixed_type=NS(identifier="Struct"),
                  as_pointer=lambda: pointer, **extra)

    base = NS(as_pointer=lambda: 700, properties=[prop("rna_type", "POINTER", True, 701),
                                               prop("name", "STRING", False, 702)])
    fixed = NS(identifier="CyclesMeshSettings", as_pointer=lambda: 710, base=base,
               properties=[prop("rna_type", "POINTER", True, 711),
                           prop("name", "STRING", False, 712)])
    cycles = prop("cycles", "POINTER", True, 720)
    cycles.is_runtime, cycles.fixed_type = True, fixed

    class MethodModel:
        def __init__(self, name):
            self.name = name

        def __call__(self, owner, *args, **kwargs):
            if self.name == "keys":
                return ()
            assert args == ("cycles",) and kwargs == {"ghost": False}
            presence_calls.append((args, kwargs))
            return case.stored

    class BaseModel:
        is_property_set = MethodModel("is_property_set")
        keys = MethodModel("keys")

    for name in ("is_property_set", "keys"):
        vars(BaseModel)[name].__objclass__ = BaseModel

    class OwnerModel:
        bl_rna = NS(identifier="Mesh")

        @property
        def cycles(self):
            raise AssertionError("The runtime payload getter must never be used")

    monkeypatch.setattr(guard, "MethodDescriptorType", MethodModel)
    reader = object.__new__(guard._NativeReader)
    reader._base = lambda _cls: BaseModel
    reader.bpy = NS(app=NS(build_hash=b"62c1db4208e8"),
                    types=NS(PropertyGroup=NS(bl_rna=base)))
    case.reader, case.owner, case.prop = reader, OwnerModel(), cycles
    case.base, case.fixed = base, fixed
    return case


@pytest.mark.parametrize("build", [b"62c1db4208e8", b"d13f752e3b9c"])
def test_mesh_empty_bundled_runtime_accepts_only_noncreating_absence(mesh_runtime_model, build):
    case = mesh_runtime_model
    case.reader.bpy.app.build_hash = build
    schema = case.reader._stored_runtime(case.owner, (case.prop,))
    assert schema[0][0] == "cycles" and schema[0][3][0] == build.decode()
    assert schema[0][3][1] == "NATIVE_ABSENCE_ONLY" and len(case.presence_calls) == 1


@pytest.mark.parametrize("stored", [True, 1, None])
def test_mesh_stored_or_untyped_presence_never_adopts_runtime_payload(mesh_runtime_model, stored):
    case = mesh_runtime_model
    case.stored = stored
    with pytest.raises(case.guard.BridgeError) as caught:
        case.reader._stored_runtime(case.owner, (case.prop,))
    assert caught.value.context["owner_type"] == "Mesh"
    assert caught.value.context["property"] == "cycles"
    assert caught.value.context["runtime_getter_fallback_used"] is False


@pytest.mark.parametrize("change", ["build", "fixed_type", "extra_group", "group_runtime", "group_readonly",
                                      "registered", "readonly", "unknown", "missing"])
def test_mesh_runtime_schema_refuses_before_presence_or_payload(mesh_runtime_model, change):
    case, props = mesh_runtime_model, (mesh_runtime_model.prop,)
    if change == "build":
        case.reader.bpy.app.build_hash = b"unknown"
    elif change == "fixed_type":
        case.fixed.identifier = "CyclesGeometrySettings"
    elif change == "extra_group":
        case.fixed.properties.append(NS(identifier="extra"))
    elif change == "group_runtime":
        case.fixed.properties[0].is_runtime = True
    elif change == "group_readonly":
        case.fixed.properties[1].is_readonly = True
    elif change == "registered":
        case.prop.is_registered = True
    elif change == "readonly":
        case.prop.is_readonly = False
    elif change == "unknown":
        case.prop.identifier = "cycles_extra"
    else:
        props = ()
    with pytest.raises(case.guard.BridgeError) as caught:
        case.reader._stored_runtime(case.owner, props)
    assert caught.value.context["owner_type"] == "Mesh"
    assert "property" in caught.value.context and not case.presence_calls


@pytest.mark.parametrize("phase", ["before_checkpoint", "after_checkpoint"])
def test_checkpoint_model_callback_cannot_rebase_original_memberships(model, phase):
    """Exercise real admission callbacks, without fabricating a native event."""
    with model.admitted() as guard:
        binding = model.context.checkpoint_admission
        if phase == "before_checkpoint":
            model.native = replace(model.native, preservation=("foreign pre-checkpoint",))
        else:
            binding.check_after_read()
            model.native = replace(model.native, memberships=model.intent.replace_member(
                model.native.memberships, 2, 1, bits(.9)))
        with pytest.raises(model.errors.BridgeError):
            binding.check_after_read()
        assert guard.before == model.original
        with pytest.raises(model.errors.BridgeError):
            guard.execute()
    assert not model.writes


def test_guarded_children_refuse_batch_before_providers_or_reader(model, addon_package):
    batch = importlib.import_module(f"{addon_package}.tools.batch")
    batch.register_tools(model.registry)
    with pytest.raises(model.errors.BridgeError):
        model.registry.dispatch("batch.execute", {"steps": [
            {"method": "weights.assign", "params": model.params}]}, model.context)
    assert not model.writes and model.reader_count == 0


def test_exclusive_owner_denies_nested_writer_before_reader(model):
    seen = []

    def provider():
        if seen:
            return
        seen.append("attempted")
        with pytest.raises(model.errors.BridgeError):
            model.call(params={**model.params, "weight": .5})

    model.provider = provider
    model.call()
    assert seen == ["attempted"] and model.reader_count == 1


def test_authority_denial_before_first_write_has_no_native_calls(model):
    model.grants["EDIT_MESH"] = False
    with pytest.raises(model.errors.BridgeError) as caught:
        model.call()
    assert caught.value.code == "PERMISSION_DENIED" and not model.writes


def test_wrong_or_unqualified_history_method_cannot_relabel_a_receipt(model):
    receipt = model.call()["recovery_evidence"]
    assert model.state_mod.bounded_recovery_evidence({**receipt, "method": "weights.smooth"}) is None
    assert model.state_mod.bounded_recovery_evidence({**receipt, "owned_membership_verified": 4097}) is None


@pytest.mark.parametrize("method", ["weights.assign", "weights.normalize"])
def test_typed_direct_history_is_copied_and_permission_redacted(model, addon_package, method):
    params = model.params if method == "weights.assign" else {
        "object_name": "Mesh", "group_names": ["A", "B"], "vertex_indices": [0, 1]}
    receipt = model.call(method, params)["recovery_evidence"]
    model.state.record_operation(tool=method, description="Private direct weight details", success=True,
                                 duration_ms=1., recovery_evidence=receipt)
    original_hash = receipt["expected_sha256"]
    receipt["expected_sha256"] = "0" * 64
    assert model.state.history(1)[0]["recovery_evidence"]["expected_sha256"] == original_hash
    model.context.checkpoints.list = lambda _limit: []
    model.context.checkpoints.recovery_status = lambda **_kwargs: {}
    core = importlib.import_module(f"{addon_package}.tools.core")
    hidden = core.checkpoint_list(model.context, {"limit": 1})["operation_history"][0]
    assert hidden["recovery_evidence"] is None and hidden["recovery_evidence_redacted"]
    model.grants["INSPECT_SCENE"] = True
    shown = core.checkpoint_list(model.context, {"limit": 1})["operation_history"][0]
    assert shown["recovery_evidence"]["expected_sha256"] == original_hash


@pytest.mark.parametrize("field,bad", [("owned_membership_attempts", 257),
    ("restoration_attempts", 257), ("native_update_attempts", 1), ("stage", "UPDATE")])
def test_direct_receipt_limits_cannot_adopt_brush_update_or_field_capacity(model, field, bad):
    receipt = model.call()["recovery_evidence"]
    assert model.state_mod.bounded_recovery_evidence({**receipt, field: bad}) is None
