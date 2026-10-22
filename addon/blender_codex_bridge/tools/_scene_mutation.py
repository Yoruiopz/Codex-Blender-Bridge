"""Typed Scene-domain snapshots and measured, per-write mutation boundaries.

Only internal literal native fields are read. Runtime properties are screened
before getters; the host process is not a sandbox for third-party Python.
"""

from __future__ import annotations

import logging
import math
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode
from ..permissions import Permission
from ..tool_registry import check_final_mutation
from ._object_safety import require_local_editable_id

LOGGER = logging.getLogger(__name__)
MAX_ITEMS = 1024
PRIMITIVES = frozenset({"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"})
HANDLERS = ("depsgraph_update_pre", "depsgraph_update_post", "frame_change_pre", "frame_change_post")
RUNTIME = {
    "Scene": {"cycles": "POINTER", "cycles_curves": "POINTER"},
    "Object": {"cycles": "POINTER", "selection_sets": "COLLECTION", "active_selection_set": "INT"},
    "Camera": {"cycles_custom": "POINTER"},
    "PointLight": {"cycles": "POINTER"}, "SpotLight": {"cycles": "POINTER"},
    "AreaLight": {"cycles": "POINTER"}, "SunLight": {"cycles": "POINTER"},
    "World": {"cycles": "POINTER", "cycles_visibility": "POINTER"},
}
RUNTIME_FIXED = {
    ("Scene", "cycles"): "CyclesRenderSettings", ("Scene", "cycles_curves"): "CyclesCurveRenderSettings",
    ("Object", "cycles"): "CyclesObjectSettings", ("Object", "selection_sets"): "SelectionSet",
    ("Camera", "cycles_custom"): "CyclesCustomCameraSettings",
    **{(kind, "cycles"): "CyclesLightSettings" for kind in ("PointLight", "SpotLight", "AreaLight", "SunLight")},
    ("World", "cycles"): "CyclesWorldSettings", ("World", "cycles_visibility"): "CyclesVisibilitySettings",
}
CLASSES = ("Scene", "Object", "Camera", "CameraDOFSettings", "PointLight", "SpotLight", "AreaLight", "SunLight",
           "World", "UnitSettings", "Collection", "ShaderNodeTree", "ShaderNodeBackground", "ShaderNodeOutputWorld",
           "NodeSocketColor", "NodeSocketFloat", "NodeSocketShader", "ShaderNodeEmission", "ShaderNodeOutputLight")


def unsupported(message: str, **details: Any) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, message, {"scope_complete": False, **details})


def preservation_scope() -> dict[str, Any]:
    """Successful literal verification never claims unread runtime preservation."""
    return {"complete": False, "literal_fields_verified": True,
            "unread_bundled_runtime_settings": True}


def bounded(values: Any, maximum: int, label: str) -> tuple[Any, ...]:
    result = tuple(islice(values, maximum + 1))
    if len(result) > maximum:
        raise unsupported(f"Scene mutation {label} exceeds {maximum} items.")
    return result


def key(owner: Any) -> int | None:
    return None if owner is None else int(owner.as_pointer())


def token(owner: Any) -> tuple[int | None, int | None]:
    return key(owner), None if owner is None else getattr(owner, "session_uid", None)


def value(raw: Any, *, depth: int = 0, budget: list[int] | None = None,
          custom_scalars: bool = False) -> Any:
    if budget is None:
        budget = [4096]
    budget[0] -= 1
    if budget[0] < 0 or depth > 8:
        raise unsupported("Scene mutation property evidence exceeds its bounded budget.")
    if raw is None or isinstance(raw, (bool, int)):
        return (type(raw).__name__, raw) if custom_scalars else raw
    if isinstance(raw, str):
        if len(raw) > 4096:
            raise unsupported("Scene mutation strings exceed 4096 characters.")
        return ("str", raw) if custom_scalars else raw
    if isinstance(raw, float):
        if not math.isfinite(raw):
            raise unsupported("Scene mutation evidence requires finite values.")
        return ("float", raw.hex()) if custom_scalars else raw
    if hasattr(raw, "as_pointer"):
        return ("RNA", *token(raw))
    if hasattr(raw, "keys"):
        return tuple((str(name), value(raw[name], depth=depth + 1, budget=budget, custom_scalars=custom_scalars))
                     for name in sorted(bounded(raw.keys(), 128, "custom-property keys")))
    items = sorted(raw) if isinstance(raw, set) else bounded(raw, 256, "array values")
    return tuple(value(item, depth=depth + 1, budget=budget, custom_scalars=custom_scalars) for item in items)


def custom(owner: Any) -> Any:
    try:
        names = sorted(bounded(owner.keys(), 128, "custom-property keys"))
    except TypeError as error:
        if "doesn't support IDProperties" in str(error):
            return ()
        raise
    budget = [4096]
    # IDProperty scalar types may change while comparing equal in Python.
    # Preserve each exposed type and finite float spelling, including -0.0;
    # native fixed-RNA fields keep their separate setter prediction format.
    return tuple((name, value(owner[name], budget=budget, custom_scalars=True)) for name in names)


def descriptors(bpy: Any, owner: Any) -> Any:
    rna = owner.bl_rna
    identifier = rna.identifier
    canonical = getattr(bpy.types, identifier, None)
    if canonical is None or type(owner) is not canonical or key(rna) != key(canonical.bl_rna):
        raise unsupported("Scene mutation requires an exact reviewed native RNA owner.", owner_type=identifier)
    properties = bounded(rna.properties, 512, "RNA descriptors")
    allowed = RUNTIME.get(identifier, {})
    for prop in properties:
        if prop.is_runtime:
            kind = allowed.get(prop.identifier)
            readonly = prop.identifier != "active_selection_set"
            if kind != prop.type or bool(prop.is_readonly) != readonly or prop.is_registered:
                raise unsupported("Unreviewed runtime RNA properties are refused before their getters.", owner_type=identifier, property=prop.identifier)
            if prop.identifier == "active_selection_set" and (prop.array_length or prop.default != 0):
                raise unsupported("Object UI selection descriptor differs from its reviewed native signature.")
            if prop.type in {"POINTER", "COLLECTION"} and getattr(getattr(prop, "fixed_type", None), "identifier", None) != RUNTIME_FIXED.get((identifier, prop.identifier)):
                raise unsupported("Bundled runtime descriptor differs from its reviewed native fixed type.")
    if identifier == "Object" and "active_selection_set" in bounded(owner.keys(), 128, "Object custom keys"):
        raise unsupported("Stored runtime Object UI selection requires a broader preservation contract.")
    return properties


def preflight_types(bpy: Any) -> None:
    """Screen unknown runtime registrations before legacy argument getters."""
    for identifier in CLASSES:
        canonical = getattr(getattr(bpy, "types", None), identifier, None)
        if canonical is None:
            raise unsupported("A required native Scene-domain RNA type is unavailable.", owner_type=identifier)
        for prop in bounded(canonical.bl_rna.properties, 512, "RNA descriptors"):
            if not prop.is_runtime:
                continue
            kind = RUNTIME.get(identifier, {}).get(prop.identifier)
            readonly = prop.identifier != "active_selection_set"
            if kind != prop.type or bool(prop.is_readonly) != readonly or prop.is_registered:
                raise unsupported("Unreviewed runtime RNA properties are refused before their getters.", owner_type=identifier, property=prop.identifier)
            if prop.identifier == "active_selection_set" and (prop.array_length or prop.default != 0):
                raise unsupported("Object UI selection descriptor differs from its reviewed native signature.")
            if prop.type in {"POINTER", "COLLECTION"} and getattr(getattr(prop, "fixed_type", None), "identifier", None) != RUNTIME_FIXED.get((identifier, prop.identifier)):
                raise unsupported("Bundled runtime descriptor differs from its reviewed native fixed type.")


def primitive(bpy: Any, owner: Any, *, exclude: frozenset[str] = frozenset()) -> tuple[Any, ...]:
    props = descriptors(bpy, owner)
    result = []
    for prop in props:
        if prop.is_runtime or prop.is_readonly or prop.identifier in exclude:
            continue
        if prop.type in PRIMITIVES | {"POINTER"}:
            result.append((prop.identifier, value(getattr(owner, prop.identifier))))
    return tuple(result), custom(owner)


def session(bpy: Any) -> Any:
    ctx = bpy.context
    return (token(ctx.scene), key(ctx.view_layer), key(ctx.window), bpy.data.filepath, ctx.mode,
            tuple(token(obj) for obj in bounded(ctx.selected_objects, 256, "selection")), token(ctx.view_layer.objects.active),
            token(ctx.window.scene), key(ctx.window.view_layer))


def runtime(bpy: Any) -> Any:
    result = tuple((name, tuple(id(fn) for fn in bounded(getattr(bpy.app.handlers, name), 128, "handlers"))) for name in HANDLERS)
    if any(functions for _name, functions in result):
        raise unsupported("Scene mutation refuses frame/dependency-graph handlers with unreviewed effects.")
    return result


def current_scene(bpy: Any, scene: Any) -> None:
    descriptors(bpy, scene)
    require_local_editable_id(scene, operation="Scene mutation")
    if (bpy.context.mode != "OBJECT" or bpy.context.scene != scene or bpy.context.window.scene != scene
            or bpy.context.window.view_layer != bpy.context.view_layer or bpy.data.scenes.get(scene.name) != scene):
        raise unsupported("Scene mutation requires the actual current Scene and view layer in Object Mode.")
    if scene.animation_data is not None:
        raise unsupported("Animated Scene settings require a separately reviewed mutation scope.")


def references(bpy: Any, owners: tuple[Any, ...]) -> tuple[Any, ...]:
    user_map = bpy.data.user_map(subset=set(owners))
    result = []
    for owner in owners:
        direct = bounded(user_map.get(owner, ()), 128, "direct consumers")
        result.append((token(owner), int(owner.users), bool(owner.use_fake_user),
                       tuple(sorted((token(user), user.bl_rna.identifier, str(user.name), int(user.user_of_id(owner))) for user in direct))))
    return tuple(result)


def canonical(prop: Any, raw: Any) -> Any:
    if prop.type == "FLOAT":
        def f32(number: Any) -> float:
            return struct.unpack("f", struct.pack("f", float(number)))[0]
        return tuple(f32(item) for item in raw) if prop.array_length else f32(raw)
    return value(raw)


@dataclass(frozen=True, slots=True)
class Field:
    owner: Callable[[], Any]
    name: str

    def raw(self, bpy: Any) -> Any:
        target = self.owner()
        if target is None:
            return None
        descriptors(bpy, target)
        prop = target.bl_rna.properties.get(self.name)
        if prop is None or prop.is_runtime or prop.is_readonly or prop.type not in PRIMITIVES | {"POINTER"}:
            raise unsupported("A literal Scene mutation field has no reviewed native descriptor.", property=self.name)
        raw = getattr(target, self.name)
        if prop.type in {"BOOLEAN", "INT", "FLOAT"} and prop.array_length:
            return tuple(raw)
        return set(raw) if isinstance(raw, set) else raw

    def read(self, bpy: Any) -> Any:
        return value(self.raw(bpy))


class Boundary:
    """Keep provider effects outside the frozen comparison and owned writes."""

    def __init__(self, bpy: Any, context: Any, method: str, fields: Mapping[str, Field], profile: Callable[[], Any]):
        self.bpy, self.context, self.method = bpy, context, method
        self.fields = dict(fields)
        self.profile = profile
        self.expected_profile = profile()
        self.expected = self.read()
        self.original = dict(self.expected)
        self.attempted: list[tuple[str, Any, Any, Any]] = []
        self.stopped: BridgeError | None = None
        self.retained_effects: list[dict[str, Any]] = []
        self.owned_started = False
        self.native_attempts = 0

    def mark_native(self) -> None:
        self.owned_started = True
        self.native_attempts += 1

    def evidence(self, restored: bool) -> dict[str, Any]:
        return {"kind": "scene_mutation", "owned_write_attempts": len(self.attempted) + self.native_attempts,
                "restoration_verified": restored, "retained_effects": list(self.retained_effects)}

    def read(self) -> dict[str, Any]:
        return {name: field.read(self.bpy) for name, field in self.fields.items()}

    def authority(self, *, delete: bool = False) -> None:
        if self.stopped is not None:
            raise self.stopped
        try:
            callback = getattr(self.context, "check_cancelled", None)
            if callback is not None:
                callback()
            permissions = (Permission.EDIT_SCENE, Permission.DELETE_OBJECTS) if delete or self.method == "collection.delete" else (Permission.EDIT_SCENE,)
            registry = getattr(self.context, "registry", None)
            if registry is not None:
                registry.prepare(self.method, self.context)
            # Cleanup can need an additional deletion grant beyond ToolSpec.
            # Resolve the complete set coherently after every other provider.
            self.context.require(*permissions)
        except BridgeError as error:
            self.stopped = error
            raise

    def final(self) -> None:
        if self.stopped is not None:
            raise self.stopped
        try:
            check_final_mutation(self.context, self.method)
        except BridgeError as error:
            self.stopped = error
            raise

    def check(self, *, delete: bool = False) -> None:
        self.authority(delete=delete)
        self.check_after_read()

    def check_after_read(self) -> None:
        """Prove retained authored expectations without calling providers."""
        if self.profile() != self.expected_profile or self.read() != self.expected:
            raise unsupported("Scene mutation context, identity, consumers or authored content changed; further writes and compensation are refused.")
        self.final()

    def write(self, name: str, raw: Any, *, after_native: Callable[[], None] | None = None) -> None:
        self.check()
        field = self.fields[name]
        owner = field.owner()
        prop = owner.bl_rna.properties[field.name]
        before, after = self.expected[name], canonical(prop, raw)
        before_raw = field.raw(self.bpy)
        candidate = {**self.expected, name: after}
        self.attempted.append((name, before, after, before_raw))
        self.final()
        try:
            setattr(owner, field.name, raw)
            if after_native is not None:
                after_native()
                candidate = {**self.expected, name: after}
        except Exception:
            # Only exact before/after output can authorize later compensation.
            try:
                if self.profile() == self.expected_profile and self.read() == candidate:
                    self.expected = candidate
            except Exception:
                LOGGER.exception("Scene setter failure output could not be observed")
            raise
        if self.profile() != self.expected_profile or self.read() != candidate:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Native Scene setter output did not match its exact prediction.")
        self.expected = candidate

    def restore(self) -> bool:
        self.check()
        for name, before, _after, before_raw in reversed(self.attempted):
            if self.expected[name] == before:
                continue
            self.check()
            field = self.fields[name]
            self.final()
            setattr(field.owner(), field.name, before_raw)
            candidate = {**self.expected, name: before}
            if self.profile() != self.expected_profile or self.read() != candidate:
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Scene compensation could not be measured exactly.")
            self.expected = candidate
        self.check()
        return self.expected == self.original and not self.retained_effects

    def failure(self, error: Exception, *, affected: tuple[str, ...] = (), restoration_verified: bool | None = None) -> BridgeError:
        restored = bool(restoration_verified)
        if restoration_verified is None and self.attempted:
            try:
                restored = self.restore()
            except Exception:
                LOGGER.exception("Scene compensation refused or failed; retained state requires inspection")
        started = bool(self.attempted) or self.owned_started
        details = {"execution_started": started, "possible_mutation": started and not restored,
                   "rollback_verified": restored, "affected_objects": list(affected), "verification_required": True,
                   "recovery_evidence": self.evidence(restored)}
        return BridgeError(error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED,
                           "Scene mutation did not complete; inspect retained state and recovery evidence.", details)
