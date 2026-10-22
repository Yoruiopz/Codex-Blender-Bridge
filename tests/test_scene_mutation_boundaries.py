"""Adversarial authorizations and measured recovery for Scene write boundaries."""

from __future__ import annotations

import importlib
import struct
from collections.abc import Callable
from types import SimpleNamespace as NS
from typing import Any

import pytest


def f32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


class Properties(list):
    def get(self, name: str) -> Any:
        return next((prop for prop in self if prop.identifier == name), None)

    def __getitem__(self, key: Any) -> Any:
        return self.get(key) if isinstance(key, str) else super().__getitem__(key)


def prop(name: str, kind: str = "FLOAT", **kwargs: Any) -> Any:
    values = dict(identifier=name, type=kind, is_runtime=False, is_readonly=False,
                  is_registered=False, array_length=0, default=0)
    return NS(**{**values, **kwargs})


class RNA:
    def __init__(self, identifier: str, properties: Properties):
        self.identifier, self.properties = identifier, properties

    def as_pointer(self) -> int:
        return id(self)


class NativeOwner:
    bl_rna: Any

    def __init__(self, values: dict[str, Any] | None = None):
        object.__setattr__(self, "_values", dict(values or {}))
        object.__setattr__(self, "custom_values", {})
        object.__setattr__(self, "getter_calls", [])
        object.__setattr__(self, "setter_calls", [])
        object.__setattr__(self, "mutations", [])
        object.__setattr__(self, "getter_hooks", {})
        object.__setattr__(self, "setter_hooks", {})
        object.__setattr__(self, "session_uid", id(self))

    def __getattr__(self, name: str) -> Any:
        if name in self.getter_hooks:
            self.getter_calls.append(name)
            return self.getter_hooks[name]()
        if name in self._values:
            return self._values[name]
        raise AttributeError(name)

    def __setattr__(self, name: str, raw: Any) -> None:
        descriptor = self.bl_rna.properties.get(name)
        if descriptor is None:
            object.__setattr__(self, name, raw)
            return
        self.setter_calls.append((name, raw))
        normalized = raw
        if descriptor.type == "FLOAT":
            normalized = tuple(f32(float(item)) for item in raw) if descriptor.array_length else f32(float(raw))
        hook = self.setter_hooks.get(name)
        if hook is not None:
            hook(self, name, normalized)
            return
        self.publish(name, normalized)

    def publish(self, name: str, value: Any) -> None:
        self._values[name] = value
        self.mutations.append((name, value))

    def as_pointer(self) -> int:
        return id(self)

    def keys(self) -> Any:
        return self.custom_values.keys()

    def __getitem__(self, name: str) -> Any:
        return self.custom_values[name]


@pytest.fixture
def env(addon_package: str) -> Any:
    proof = importlib.import_module(f"{addon_package}.tools._scene_mutation")
    permission_module = importlib.import_module(f"{addon_package}.permissions")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    state_module = importlib.import_module(f"{addon_package}.state")
    errors = importlib.import_module(f"{addon_package}.errors")
    props = Properties([prop("a"), prop("b"), prop("vector", array_length=3), prop("target", "POINTER")])
    native_type = type("NativeSettings", (NativeOwner,), {"bl_rna": RNA("NativeSettings", props)})
    bpy = NS(types=NS(NativeSettings=native_type))
    owner = native_type({"a": 1.0, "b": 2.0, "vector": (1.0, 2.0, 3.0), "target": None})
    grants = {item.value: True for item in permission_module.Permission}
    provider_calls: list[dict[str, bool]] = []
    provider_hook: list[Callable[[], None] | None] = [None]

    def provider() -> Any:
        if provider_hook[0] is not None:
            provider_hook[0]()
        provider_calls.append(dict(grants))
        return dict(grants)

    permissions = permission_module.PermissionManager(provider)
    state = state_module.BridgeState()
    registry = registry_module.ToolRegistry(enabled_toolsets=("scene_edit",))
    for method in ("scene.configure", "collection.create", "collection.delete"):
        required = (permission_module.Permission.EDIT_SCENE,)
        if method == "collection.delete":
            required = (*required, permission_module.Permission.DELETE_OBJECTS)
        registry.register(method, lambda _context, _params: None, permissions=required, toolset="scene_edit", modifies=True)
    context = registry_module.ToolContext(state, permissions, registry, NS())
    protected = {"session": "same", "consumer": "same"}
    fields = {name: proof.Field(lambda: owner, name) for name in ("a", "b", "vector", "target")}

    def make(method: str = "scene.configure") -> Any:
        return proof.Boundary(bpy, context, method, fields, lambda: tuple(sorted(protected.items())))

    return NS(proof=proof, permissions=permission_module, registry_module=registry_module, errors=errors,
              bpy=bpy, owner=owner, props=props, grants=grants, provider_calls=provider_calls,
              provider_hook=provider_hook, context=context, protected=protected, fields=fields, make=make)


def failure(case: Any, boundary: Any, operation: Callable[[], Any]) -> Any:
    with pytest.raises(case.errors.BridgeError) as caught:
        operation()
    return boundary.failure(caught.value)


def test_success_uses_native_float32_prediction_and_raw_pointer_identity(env: Any) -> None:
    case = env
    boundary = case.make()
    pointer = case.bpy.types.NativeSettings({"a": 12.0})
    boundary.write("a", 43.1)
    boundary.write("vector", (.1, .2, .3))
    boundary.write("target", pointer)
    assert case.owner.a == f32(43.1)
    assert case.owner.vector == tuple(f32(item) for item in (.1, .2, .3))
    assert case.fields["target"].raw(case.bpy) is pointer
    assert boundary.expected["target"] == ("RNA", pointer.as_pointer(), pointer.session_uid)
    assert boundary.restore() is True
    assert case.owner.target is None
    assert (case.owner.a, case.owner.vector) == (1.0, (1.0, 2.0, 3.0))


def test_compensation_restores_original_native_pointer_not_an_encoded_tuple(env: Any) -> None:
    case = env
    original = case.bpy.types.NativeSettings({"a": 12.0})
    replacement = case.bpy.types.NativeSettings({"a": 13.0})
    case.owner._values["target"] = original
    boundary = case.make()
    boundary.write("target", replacement)
    assert boundary.restore() is True
    assert case.owner.target is original
    assert case.owner.setter_calls == [("target", replacement), ("target", original)]


def test_missing_grant_before_first_write_does_not_mutate_or_attempt_recovery(env: Any) -> None:
    case = env
    boundary = case.make()
    case.grants["EDIT_SCENE"] = False
    error = failure(case, boundary, lambda: boundary.write("a", 9.0))
    assert error.code == "PERMISSION_DENIED"
    assert case.owner.setter_calls == []
    assert error.context["execution_started"] is False
    assert error.context["possible_mutation"] is False


def test_revocation_after_one_write_retains_that_effect_without_compensation(env: Any) -> None:
    case = env
    boundary = case.make()
    boundary.write("a", 9.0)
    case.grants["EDIT_SCENE"] = False
    error = failure(case, boundary, lambda: boundary.write("b", 10.0))
    assert error.code == "PERMISSION_DENIED"
    assert case.owner.setter_calls == [("a", 9.0)]
    assert (case.owner.a, case.owner.b) == (9.0, 2.0)
    assert error.context["possible_mutation"] is True
    assert error.context["recovery_evidence"]["restoration_verified"] is False


def test_cleanup_resolves_complete_grants_after_the_narrower_registry_provider(env: Any) -> None:
    case = env
    boundary = case.make("collection.create")
    reads = []

    def revoke_in_second_provider() -> None:
        reads.append(True)
        if len(reads) == 2:
            case.grants["DELETE_OBJECTS"] = False

    case.provider_hook[0] = revoke_in_second_provider
    with pytest.raises(case.errors.BridgeError) as caught:
        boundary.check(delete=True)
    assert caught.value.code == "PERMISSION_DENIED"
    assert caught.value.context["missing_permissions"] == ["DELETE_OBJECTS"]
    assert len(reads) == 2
    assert case.owner.setter_calls == []


@pytest.mark.parametrize("target", ("owned", "protected"))
def test_provider_edits_are_not_adopted_as_a_new_snapshot(env: Any, target: str) -> None:
    case = env
    boundary = case.make()
    fired = []

    def manual_edit() -> None:
        if not fired:
            fired.append(True)
            if target == "owned":
                case.owner._values["a"] = 77.0
            else:
                case.protected["consumer"] = "new manual consumer"

    case.provider_hook[0] = manual_edit
    error = failure(case, boundary, lambda: boundary.write("a", 9.0))
    assert error.code == "NOT_IMPLEMENTED"
    assert case.owner.setter_calls == []
    assert boundary.expected["a"] == 1.0
    assert case.owner.a == (77.0 if target == "owned" else 1.0)
    assert case.protected["consumer"] == ("new manual consumer" if target == "protected" else "same")


def owner_flags(addon_package: str, case: Any) -> Any:
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    queue = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    life = lifecycle.RequestLifetime(lifecycle.ConnectionLifetime())
    queued = queue.QueuedRequest(protocol.Request(id="scene-final-owner", method="scene.configure", params={}))
    queued.deadline = float("inf")
    case.context.request_lifecycle = life
    case.context.check_final_request = queued.check_active
    job = [False]

    def job_check() -> None:
        if job[0]:
            raise case.errors.BridgeError("TIMEOUT", "Scheduler deadline expired")

    case.context.check_final_job = job_check

    def stop(kind: str) -> None:
        if kind == "queued_cancel":
            queued.cancel_pending(case.errors.BridgeError("TIMEOUT", "Caller canceled"))
        elif kind == "queued_deadline":
            queued.deadline = 0.0
        elif kind == "disconnect":
            life.connection.disconnected.set()
        elif kind == "handoff_deadline":
            life.deadline = 0.0
        elif kind == "rejected":
            life.rejected.set()
        elif kind == "job":
            job[0] = True
        elif kind == "pause":
            case.context.state.set_paused(True)
        elif kind == "emergency":
            case.context.state.set_emergency_stopped(True)
        else:
            case.context.registry.disable_toolset("scene_edit")

    def renew() -> None:
        queued._stop_requested = False
        queued.deadline = float("inf")
        life.connection.disconnected.clear()
        life.rejected.clear()
        life.deadline = float("inf")
        job[0] = False
        case.context.state.set_paused(False)
        case.context.state.set_emergency_stopped(False)
        case.context.registry.enable_toolset("scene_edit")

    return NS(stop=stop, renew=renew)


STOPS = ("queued_cancel", "queued_deadline", "disconnect", "handoff_deadline", "rejected", "job", "pause", "emergency", "toolset")


@pytest.mark.parametrize("kind", STOPS)
@pytest.mark.parametrize("where", ("profile", "last_owned_read", "last_raw_read"))
def test_final_owner_loss_after_content_reads_prevents_next_write_and_latches(
    env: Any, addon_package: str, monkeypatch: pytest.MonkeyPatch, kind: str, where: str,
) -> None:
    case = env
    boundary = case.make()
    flags = owner_flags(addon_package, case)
    fired = []

    def inject() -> None:
        if not fired:
            fired.append(True)
            flags.stop(kind)

    if where == "profile":
        original = boundary.profile

        def profile() -> Any:
            result = original()
            inject()
            return result

        monkeypatch.setattr(boundary, "profile", profile)
    elif where == "last_owned_read":
        original = boundary.read

        def read() -> Any:
            result = original()
            inject()
            return result

        monkeypatch.setattr(boundary, "read", read)
    else:
        original = case.proof.Field.raw
        calls = []

        def raw(field: Any, bpy: Any) -> Any:
            result = original(field, bpy)
            if field is case.fields["a"]:
                calls.append(True)
                if len(calls) == 2:
                    inject()
            return result

        monkeypatch.setattr(case.proof.Field, "raw", raw)
    with pytest.raises(case.errors.BridgeError):
        boundary.write("a", 9.0)
    assert fired and boundary.stopped is not None
    assert case.owner.setter_calls == []
    flags.renew()
    with pytest.raises(case.errors.BridgeError):
        boundary.write("a", 10.0)
    assert case.owner.setter_calls == []


@pytest.mark.parametrize("outcome", ("before", "after"))
def test_exact_setter_failure_outputs_allow_measured_prior_write_recovery(env: Any, outcome: str) -> None:
    case = env
    boundary = case.make()
    boundary.write("a", 9.0)
    tripped = []

    def fail_once(owner: NativeOwner, name: str, raw: Any) -> None:
        if not tripped:
            tripped.append(True)
            if outcome == "after":
                owner.publish(name, raw)
            raise RuntimeError("native setter failed")
        owner.publish(name, raw)

    case.owner.setter_hooks["b"] = fail_once
    with pytest.raises(RuntimeError) as caught:
        boundary.write("b", 10.0)
    error = boundary.failure(caught.value, affected=("Camera",))
    assert (case.owner.a, case.owner.b) == (1.0, 2.0)
    assert error.code == "OPERATION_FAILED"
    assert error.context["rollback_verified"] is True
    assert error.context["possible_mutation"] is False
    assert error.context["affected_objects"] == ["Camera"]
    assert error.context["recovery_evidence"]["owned_write_attempts"] == 2


def test_unknown_partial_vector_output_refuses_all_compensation(env: Any) -> None:
    case = env
    boundary = case.make()
    boundary.write("a", 9.0)

    def partial(owner: NativeOwner, name: str, _raw: Any) -> None:
        owner.publish(name, (4.0, 2.0, 3.0))
        raise RuntimeError("partial native vector write")

    case.owner.setter_hooks["vector"] = partial
    with pytest.raises(RuntimeError) as caught:
        boundary.write("vector", (4.0, 5.0, 6.0))
    before_recovery = list(case.owner.setter_calls)
    error = boundary.failure(caught.value)
    assert case.owner.setter_calls == before_recovery
    assert case.owner.a == 9.0 and case.owner.vector == (4.0, 2.0, 3.0)
    assert error.context["rollback_verified"] is False
    assert error.context["possible_mutation"] is True


@pytest.mark.parametrize("manual_target", ("owned", "protected"))
def test_new_manual_edit_after_setter_failure_is_preserved(env: Any, manual_target: str) -> None:
    case = env
    boundary = case.make()
    boundary.write("a", 9.0)

    def failed(owner: NativeOwner, _name: str, _raw: Any) -> None:
        if manual_target == "owned":
            owner._values["a"] = 77.0
        else:
            case.protected["session"] = "new manual Scene"
        raise RuntimeError("failed after interleaved manual edit")

    case.owner.setter_hooks["b"] = failed
    with pytest.raises(RuntimeError) as caught:
        boundary.write("b", 10.0)
    before_recovery = list(case.owner.setter_calls)
    error = boundary.failure(caught.value)
    assert case.owner.setter_calls == before_recovery
    assert case.owner.a == (77.0 if manual_target == "owned" else 9.0)
    assert error.context["possible_mutation"] is True


def test_lost_owner_during_failed_setter_blocks_recovery_even_after_reconnection(env: Any, addon_package: str) -> None:
    case = env
    boundary = case.make()
    flags = owner_flags(addon_package, case)
    boundary.write("a", 9.0)

    def failed(_owner: NativeOwner, _name: str, _raw: Any) -> None:
        flags.stop("disconnect")
        raise case.errors.BridgeError("TIMEOUT", "Owner disconnected during native setter")

    case.owner.setter_hooks["b"] = failed
    with pytest.raises(case.errors.BridgeError) as caught:
        boundary.write("b", 10.0)
    before_recovery = list(case.owner.setter_calls)
    error = boundary.failure(caught.value)
    assert case.owner.setter_calls == before_recovery
    assert error.code == "TIMEOUT" and error.context["possible_mutation"] is True
    assert boundary.stopped is not None
    flags.renew()
    with pytest.raises(case.errors.BridgeError):
        boundary.restore()
    assert case.owner.setter_calls == before_recovery


@pytest.mark.parametrize("readonly", (False, True))
def test_unknown_runtime_getters_are_rejected_before_generic_reads(env: Any, readonly: bool) -> None:
    case = env
    runtime = prop("custom_callback")
    runtime.is_runtime, runtime.is_readonly = True, readonly
    case.props.append(runtime)
    case.owner.getter_hooks["custom_callback"] = lambda: 42.0
    with pytest.raises(case.errors.BridgeError) as caught:
        case.proof.primitive(case.bpy, case.owner)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert case.owner.getter_calls == []


def object_ui_owner(case: Any, **changes: Any) -> Any:
    runtime = prop("active_selection_set", "INT")
    runtime.is_runtime = True
    for name, raw in changes.items():
        setattr(runtime, name, raw)
    native_type = type("Object", (NativeOwner,), {"bl_rna": RNA("Object", Properties([runtime]))})
    case.bpy.types.Object = native_type
    owner = native_type()
    owner.getter_hooks["active_selection_set"] = lambda: 0
    return owner


def test_reviewed_ui_descriptor_is_skipped_without_calling_its_getter(env: Any) -> None:
    case = env
    owner = object_ui_owner(case)
    assert case.proof.primitive(case.bpy, owner) == ((), ())
    assert owner.getter_calls == []


@pytest.mark.parametrize("changes", ({"type": "FLOAT"}, {"is_readonly": True}, {"is_registered": True},
                                     {"array_length": 1}, {"default": 1}))
def test_inexact_ui_descriptor_is_refused_without_calling_its_getter(env: Any, changes: Any) -> None:
    case = env
    owner = object_ui_owner(case, **changes)
    with pytest.raises(case.errors.BridgeError):
        case.proof.primitive(case.bpy, owner)
    assert owner.getter_calls == []


def test_stored_ui_property_is_not_silently_ignored(env: Any) -> None:
    case = env
    owner = object_ui_owner(case)
    owner.custom_values["active_selection_set"] = 0
    with pytest.raises(case.errors.BridgeError):
        case.proof.primitive(case.bpy, owner)
    assert owner.getter_calls == []


@pytest.mark.parametrize("change", ("readonly", "runtime", "kind", "missing"))
def test_literal_field_requires_reviewed_writable_native_descriptor(env: Any, change: str) -> None:
    case = env
    descriptor = case.props.get("a")
    if change == "readonly":
        descriptor.is_readonly = True
    elif change == "runtime":
        descriptor.is_runtime = True
    elif change == "kind":
        descriptor.type = "COLLECTION"
    else:
        case.props.remove(descriptor)
    case.owner.getter_hooks["a"] = lambda: 42.0
    with pytest.raises(case.errors.BridgeError):
        case.fields["a"].raw(case.bpy)
    assert case.owner.getter_calls == []


def test_wrong_native_class_is_refused_before_any_getters(env: Any) -> None:
    case = env
    subclass = type("ForeignSettings", (type(case.owner),), {})
    impostor = subclass({"a": 1.0})
    impostor.getter_hooks["a"] = lambda: 42.0
    with pytest.raises(case.errors.BridgeError):
        case.proof.primitive(case.bpy, impostor)
    assert impostor.getter_calls == []


def test_retained_native_allocation_prevents_a_false_full_recovery_claim(env: Any) -> None:
    case = env
    boundary = case.make()
    boundary.write("a", 9.0)
    boundary.owned_started = True
    boundary.retained_effects.append({"kind": "native_graph", "name": "Retained World Tree"})
    error = boundary.failure(RuntimeError("native graph allocation cannot be undone locally"))
    assert case.owner.a == 1.0
    assert error.context["rollback_verified"] is False
    assert error.context["possible_mutation"] is True
    assert error.context["recovery_evidence"]["retained_effects"] == boundary.retained_effects


def test_native_allocation_failure_without_a_field_write_still_reports_possible_effects(env: Any) -> None:
    case = env
    boundary = case.make("collection.create")
    boundary.owned_started = True
    boundary.retained_effects.append({"kind": "collection_allocation_attempt", "name": "Owned"})
    error = boundary.failure(RuntimeError("constructor failed after possibly allocating"))
    assert case.owner.setter_calls == []
    assert error.context["execution_started"] is True
    assert error.context["possible_mutation"] is True
    assert error.context["rollback_verified"] is False
    assert error.context["recovery_evidence"]["owned_write_attempts"] == 0


# Independent native contract measured on both supported development runtimes.
# Keep these expected names explicit instead of reading RUNTIME_FIXED back into
# assertions: a misspelled or widened product allowlist must fail these cases.
BUNDLED_RUNTIME = (
    ("Scene", "cycles", "POINTER", "CyclesRenderSettings"),
    ("Scene", "cycles_curves", "POINTER", "CyclesCurveRenderSettings"),
    ("Object", "cycles", "POINTER", "CyclesObjectSettings"),
    ("Object", "selection_sets", "COLLECTION", "SelectionSet"),
    ("Camera", "cycles_custom", "POINTER", "CyclesCustomCameraSettings"),
    ("PointLight", "cycles", "POINTER", "CyclesLightSettings"),
    ("SpotLight", "cycles", "POINTER", "CyclesLightSettings"),
    ("AreaLight", "cycles", "POINTER", "CyclesLightSettings"),
    ("SunLight", "cycles", "POINTER", "CyclesLightSettings"),
    ("World", "cycles", "POINTER", "CyclesWorldSettings"),
    ("World", "cycles_visibility", "POINTER", "CyclesVisibilitySettings"),
)


def bundled_runtime_owner(case: Any, owner_kind: str, name: str, kind: str, fixed: str) -> Any:
    for identifier in case.proof.CLASSES:
        native_type = type(identifier, (NativeOwner,), {"bl_rna": RNA(identifier, Properties())})
        setattr(case.bpy.types, identifier, native_type)
    descriptor = prop(name, kind, is_runtime=True, is_readonly=True, fixed_type=NS(identifier=fixed))
    native_type = getattr(case.bpy.types, owner_kind)
    native_type.bl_rna.properties.append(descriptor)
    owner = native_type()
    owner.getter_hooks[name] = lambda: pytest.fail("Runtime pointer/collection getter was invoked")
    return NS(owner=owner, descriptor=descriptor)


@pytest.mark.parametrize("owner_kind,name,kind,fixed", BUNDLED_RUNTIME)
def test_reviewed_bundled_fixed_types_are_admitted_without_resolving_runtime_values(
    env: Any, owner_kind: str, name: str, kind: str, fixed: str,
) -> None:
    case = env
    fixture = bundled_runtime_owner(case, owner_kind, name, kind, fixed)
    assert case.proof.descriptors(case.bpy, fixture.owner) == (fixture.descriptor,)
    case.proof.preflight_types(case.bpy)
    assert case.proof.primitive(case.bpy, fixture.owner) == ((), ())
    assert fixture.owner.getter_calls == []


@pytest.mark.parametrize("owner_kind,name,kind,fixed", BUNDLED_RUNTIME)
@pytest.mark.parametrize("signature", ("wrong", "missing_fixed_type", "missing_identifier"))
@pytest.mark.parametrize("entry", ("owner", "preflight"))
def test_wrong_or_missing_bundled_fixed_types_are_refused_before_runtime_getters(
    env: Any, owner_kind: str, name: str, kind: str, fixed: str, signature: str, entry: str,
) -> None:
    case = env
    fixture = bundled_runtime_owner(case, owner_kind, name, kind, fixed)
    if signature == "wrong":
        fixture.descriptor.fixed_type = NS(identifier="UnreviewedRuntimeSettings")
    elif signature == "missing_fixed_type":
        del fixture.descriptor.fixed_type
    else:
        fixture.descriptor.fixed_type = NS()
    with pytest.raises(case.errors.BridgeError) as caught:
        if entry == "owner":
            case.proof.descriptors(case.bpy, fixture.owner)
        else:
            case.proof.preflight_types(case.bpy)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert fixture.owner.getter_calls == []
