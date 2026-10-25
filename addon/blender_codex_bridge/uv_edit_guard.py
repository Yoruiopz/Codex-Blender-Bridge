"""Retained, bounded Edit Mode UV ownership and field-only recovery.

The private plan is data, not authority. Native wrappers never enter it. The
reader holds ordinary lifetime witnesses and reacquires UV payloads only after
those witnesses pass. This is a deliberately partial, material-free profile.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import threading
from dataclasses import dataclass, replace
from inspect import getattr_static
from types import GetSetDescriptorType, MemberDescriptorType, MethodDescriptorType, MethodType
from typing import Any
from weakref import ref

from .errors import BridgeError, ErrorCode
from .permissions import Permission
from .tool_registry import _checkpoint_parameters, check_final_mutation
from .uv_edit_intent import (
    CornerKey,
    UVCorner,
    UVMap,
    UVPlan,
    UVSnapshot,
    freeze_snapshot,
    plan_edit,
)

MAX_NATIVE_VALUES = 65_536
MAX_COMPARE_VALUES = 8_388_608
_CAPTURES: dict[int, list[Any]] = {}
_FIELDS = {"coordinates_set": {"updates"},
           "transform": {"corners", "offset", "scale", "pivot", "rotation", "respect_pins"},
           "pin": {"corners", "pinned"}}
_CYCLES_STORAGE = {b"62c1db4208e8": "RAW_IDPROPERTIES", b"d13f752e3b9c": "SYSTEM_ABSENT"}
_TEXSPACE_VECTORS = ("texspace_location", "texspace_size")


def _error(message: str, **context: Any) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, message, context)


def _native_method_descriptor(base: Any, owner_type: Any, name: str = "is_property_set") -> Any:
    """Return a canonical inherited C method, without instance attribute lookup."""
    if type(base) is not type or not issubclass(owner_type, base):
        raise _error("Mesh storage presence requires the canonical native method base.")
    method = vars(base).get(name)
    if (type(method) is not MethodDescriptorType or method.__objclass__ is not base
            or getattr_static(owner_type, name, None) is not method):
        raise _error("Mesh storage presence method was replaced; no substitute is called.")
    return method


def _property_shape(prop: Any) -> tuple[str, int | None]:
    """RNA exposes array metadata only on its three numeric property classes."""
    if prop.type in {"BOOLEAN", "INT", "FLOAT"}:
        try:
            size = prop.array_length
        except AttributeError as error:
            raise _error("Numeric Mesh property array metadata is unavailable.", property=prop.identifier) from error
        if type(size) is not int or not 0 <= size <= MAX_NATIVE_VALUES:
            raise _error("Numeric Mesh property array metadata is unqualified.", property=prop.identifier)
        return "NUMERIC_ARRAY", size
    if prop.type in {"STRING", "ENUM", "POINTER", "COLLECTION"}:
        # Source-defined nonnumeric classes do not declare array_length. This
        # is not a guessed zero or evidence about native payload buffers.
        return "NON_ARRAY", None
    raise _error("Mesh property metadata type is unreviewed.", property=prop.identifier)


def _property_signature(prop: Any) -> tuple[Any, ...]:
    fixed = prop.fixed_type if prop.type in {"POINTER", "COLLECTION"} else None
    return (prop.identifier, prop.type, prop.is_readonly, prop.is_runtime, prop.is_registered,
            _property_shape(prop), None if fixed is None else fixed.identifier, int(prop.as_pointer()))


def _texspace_policy(mesh: Any, props: tuple[Any, ...]) -> tuple[Any, ...]:
    """Read only the passive SDNA flag before choosing a vector projection."""
    descriptors = {prop.identifier: prop for prop in props}
    for name, kind, size in (("use_auto_texspace", "BOOLEAN", 0),
                             ("texspace_location", "FLOAT", 3), ("texspace_size", "FLOAT", 3)):
        prop = descriptors.get(name)
        if (prop is None or prop.type != kind or _property_shape(prop) != ("NUMERIC_ARRAY", size)
                or prop.is_runtime is not False or prop.is_registered is not False or prop.is_readonly is not False):
            raise _error("Mesh texture-space projection requires the reviewed native descriptors.", property=name)
    auto = mesh.use_auto_texspace
    if type(auto) is not bool:
        raise _error("Mesh texture-space mode requires an exact native Boolean.")
    return (auto, "AUTO_CACHE_EXCLUDED" if auto else "MANUAL_PUBLIC_VECTORS", _TEXSPACE_VECTORS if auto else ())


def _manual_texspace_vector(mesh: Any, name: str) -> tuple[float, ...]:
    # The exact source's ensure returns before calc when AUTO is false. Never
    # inspect an AUTO vector to discover its value or establish a baseline.
    if name not in _TEXSPACE_VECTORS or mesh.use_auto_texspace is not False:
        raise _error("Mesh texture-space mode changed before a manual vector read.")
    try:
        values = tuple(getattr(mesh, name))
    except (TypeError, ValueError) as error:
        raise _error("Manual Mesh texture-space vector storage is unavailable.") from error
    if len(values) != 3 or any(type(value) is not float or not math.isfinite(value) for value in values):
        raise _error("Manual Mesh texture-space vectors require three finite native floats.")
    try:
        rounded = struct.unpack("<3f", struct.pack("<3f", *values))
    except (OverflowError, struct.error) as error:
        raise _error("Manual Mesh texture-space storage is outside native Float32.") from error
    if (any(first.hex() != second.hex() for first, second in zip(values, rounded, strict=True))
            or mesh.use_auto_texspace is not False):
        raise _error("Manual Mesh texture-space source or mode changed during its read.")
    return values


def _mesh_properties(bpy: Any, mesh: Any) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """Screen Mesh.cycles metadata; never obtain the runtime pointer value.

    The two reviewed distributions declare an empty CyclesMeshSettings group.
    4.5 exposes stored groups through ordinary raw IDProperties. 5.2 SYSTEM
    values have no reviewed public raw reader: only proven absence is admitted.
    """
    from .tools import _scene_mutation as scene

    canonical = bpy.types.Mesh
    if (type(mesh) is not canonical or mesh.bl_rna.identifier != "Mesh"
            or scene.key(mesh.bl_rna) != scene.key(canonical.bl_rna)):
        raise _error("UV Mesh metadata requires the exact canonical native owner.")
    props = scene.bounded(mesh.bl_rna.properties, 512, "Mesh RNA descriptors")
    if len({prop.identifier for prop in props}) != len(props):
        raise _error("Mesh RNA property identifiers must form a unique complete inventory.")
    schema = tuple(_property_signature(prop) for prop in props)
    cycles = None
    for prop in props:
        if not prop.is_runtime:
            continue
        if (prop.identifier != "cycles" or prop.type != "POINTER" or prop.is_runtime is not True
                or prop.is_readonly is not True or prop.is_registered is not False
                or _property_shape(prop) != ("NON_ARRAY", None)
                or prop.fixed_type.identifier != "CyclesMeshSettings"):
            raise _error("Unreviewed Mesh runtime descriptors are refused before their getters.",
                         owner_type="Mesh", property=prop.identifier)
        cycles = prop
    if cycles is None:
        raise _error("UV Mesh storage requires the reviewed bundled cycles declaration.")
    fixed, base = cycles.fixed_type, bpy.types.PropertyGroup.bl_rna
    group_props = scene.bounded(fixed.properties, 16, "Cycles Mesh group descriptors")
    base_props = scene.bounded(base.properties, 16, "PropertyGroup base descriptors")
    if (fixed.base is None or scene.key(fixed.base) != scene.key(base)
            or len(group_props) != 2 or {prop.identifier for prop in group_props} != {"rna_type", "name"}
            or len(base_props) != 2 or {prop.identifier for prop in base_props} != {"rna_type", "name"}):
        raise _error("Cycles Mesh settings require the reviewed empty native group schema.")
    group_schema = tuple(_property_signature(prop) for prop in group_props)
    inherited = {prop.identifier: _property_signature(prop) for prop in base_props}
    expected_fields = {"rna_type": ("POINTER", True), "name": ("STRING", False)}
    for signature in group_schema:
        # Native pointers are retained independently; inherited field semantics
        # must match the canonical base and contain no Python runtime fields.
        if (signature[:-1] != inherited[signature[0]][:-1]
                or signature[1:3] != expected_fields[signature[0]] or signature[5] != ("NON_ARRAY", None)
                or signature[3] is not False or signature[4] is not False):
            raise _error("Cycles Mesh group has an unreviewed property declaration.")
    build = bpy.app.build_hash
    storage = _CYCLES_STORAGE.get(build) if type(build) is bytes else None
    if storage is None:
        raise _error("Cycles Mesh storage is qualified only for the two source-reviewed build identities.")
    texspace = _texspace_policy(mesh, props)
    native_base = bpy.types.bpy_struct
    if type(native_base) is not type or native_base.__name__ != "bpy_struct":
        raise _error("Mesh presence requires Blender's native bpy_struct base.")
    method = _native_method_descriptor(native_base, canonical)
    # ghost=False includes every stored group, including ghost/default storage.
    # The reviewed C method performs a noncreating lookup, not pointer_get,
    # rna_idproperty_check, type repair, or an instance/runtime getter.
    present = method(mesh, "cycles", ghost=False)
    if type(present) is not bool:
        raise _error("Mesh native storage presence returned an unqualified value.")
    if storage == "SYSTEM_ABSENT" and present:
        raise _error("Stored Cycles Mesh SYSTEM settings have no reviewed raw reader.",
                     mesh_cycles_storage_readable=False, runtime_getter_fallback_used=False)
    authored = method(mesh, "cycles", ghost=True) if storage == "RAW_IDPROPERTIES" else False
    if type(authored) is not bool or (authored and not present):
        raise _error("Mesh native storage presence facts are inconsistent.")
    metadata = (build.decode("ascii"), storage, scene.key(mesh.bl_rna),
                schema, scene.key(fixed), group_schema,
                scene.key(base), tuple(_property_signature(prop) for prop in base_props),
                texspace, id(method), present, authored)
    return props, metadata


def _plain(value: Any, budget: list[int] | None = None) -> Any:
    """Immutable exact-type evidence, including signed zero and finite floats."""
    if budget is None:
        budget = [MAX_NATIVE_VALUES]
    budget[0] -= 1
    if budget[0] < 0:
        raise _error("UV native evidence exceeds its scalar budget.")
    kind = type(value)
    if kind is float:
        if not math.isfinite(value):
            raise _error("UV preservation evidence requires finite native values.")
        return ("float", value.hex())
    if kind in (type(None), bool, int, str):
        if kind is str and len(value.encode("utf-8")) > 4096:
            raise _error("UV preservation strings exceed their budget.")
        return (kind.__name__, value)
    if kind in (tuple, list):
        return tuple(_plain(item, budget) for item in value)
    raise _error("UV preservation evidence contains an unsupported value.")


def _count(value: Any) -> int:
    return 1 + sum(_count(item) for item in value) if type(value) is tuple else 1


def _immutable(value: Any, depth: int = 0) -> bool:
    if depth > 32:
        return False
    return type(value) in (type(None), bool, int, float, str) or (
        type(value) is tuple and len(value) <= MAX_NATIVE_VALUES
        and all(_immutable(item, depth + 1) for item in value))


@dataclass(frozen=True, slots=True)
class NativeState:
    preservation: tuple[Any, ...]
    uv: UVSnapshot
    checkpoint_markers: tuple[Any, ...] | None = None

    def __post_init__(self) -> None:
        if type(self.preservation) is not tuple or not _immutable(self.preservation) or type(self.uv) is not UVSnapshot:
            raise _error("UV state requires immutable preservation and typed UV values.")
        _plain(self.preservation)
        if self.checkpoint_markers is not None:
            if type(self.checkpoint_markers) is not tuple or not _immutable(self.checkpoint_markers):
                raise _error("UV checkpoint inventory requires immutable predicted values.")
            _plain(self.checkpoint_markers)
        if _state_cost(self) > MAX_NATIVE_VALUES:
            raise _error("UV complete native state exceeds its bounded scalar profile.")


def _state_cost(state: NativeState) -> int:
    return (_count(state.preservation) + sum(len(layer.corners) * 3 for layer in state.uv.maps)
            + _count(state.checkpoint_markers))


def _digest(state: NativeState) -> str:
    values = (state.preservation, tuple((layer.name, tuple((row.key, row.uv_bits, row.pin_uv)
                for row in layer.corners)) for layer in state.uv.maps))
    return hashlib.sha256(json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _hook(value: Any) -> Any:
    # Never inspect a substituted callable adapter in a provider-free gate.
    return (value.__self__, value.__func__) if type(value) is MethodType else (None, value)


def _same_hooks(first: tuple[Any, ...], second: tuple[Any, ...]) -> bool:
    return len(first) == len(second) and all(a[0] is b[0] and a[1] is b[1] for a, b in zip(first, second, strict=True))


def _identities(value: Any) -> bool:
    return (type(value) is dict and len(value) == 2 and all(type(key) is str for key in value)
            and set(value) == {"object", "mesh"}
            and all(type(row) is tuple and len(row) == 2
                    and all(type(item) is int and 0 < item < 2**64 for item in row) for row in value.values()))


def _next(state: NativeState, layer_name: str, key: CornerKey, source: UVCorner) -> NativeState:
    layers = tuple(UVMap(layer.name, tuple(source if row.key == key else row for row in layer.corners))
                   if layer.name == layer_name else layer for layer in state.uv.maps)
    return NativeState(state.preservation, UVSnapshot(layers), state.checkpoint_markers)


def _corner(state: NativeState, layer_name: str, key: CornerKey) -> UVCorner:
    return next(row for layer in state.uv.maps if layer.name == layer_name for row in layer.corners if row.key == key)


class UVEditGuard:
    """One original factory, request, native snapshot and independent plan."""

    def __init__(self, method: str, context: Any, params: Any):
        self.context, self.method, self.params = context, method, params
        self._parameters = _checkpoint_parameters(params)
        if type(params) is not dict or method.removeprefix("uv.") not in _FIELDS:
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, "UV editing requires a supported plain request.")
        operation = method.removeprefix("uv.")
        if set(params) - (_FIELDS[operation] | {"object_name", "uv_layer", "selection_id"}):
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, "UV request contains unknown parameters.")
        for name in ("object_name", "uv_layer"):
            text = params.get(name)
            try:
                encoded_size = len(text.encode("utf-8")) if type(text) is str else 0
            except UnicodeError as error:
                raise BridgeError(ErrorCode.INVALID_ARGUMENT, f"'{name}' requires valid UTF-8.") from error
            if (type(text) is not str or not text or encoded_size > 63
                    or any(ord(char) < 32 or ord(char) == 127 for char in text)):
                raise BridgeError(ErrorCode.INVALID_ARGUMENT, f"'{name}' requires a bounded native name.")
        reference = params.get("selection_id")
        if reference is not None and (type(reference) is not str or not reference):
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, "selection_id must be a nonempty string.")
        if (operation == "coordinates_set" or params.get("corners") is not None) and not reference:
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, "Explicit UV indices require a fresh face selection_id.")
        self.registry = context.registry
        self.spec = self.registry.get(method)
        self.services = tuple((name, getattr(context, name, None)) for name in (
            "state", "permissions", "checkpoints", "request_lifecycle", "check_final_request", "check_final_job", "check_cancelled"))
        self.reader = _NativeReader(context, params)
        self._reader = self.reader
        self._reader_type = type(self.reader)
        self._proof_descriptor = vars(self._reader_type).get("proof_hooks")
        if (type(self.reader.proof_hooks) is not tuple or len(self.reader.proof_hooks) > 32
                or not _identities(self.reader.identities)):
            raise _error("UV reader requires closed hook and native identity metadata.")
        self.hooks = tuple(_hook(getattr(self.reader, name)) for name in ("snapshot", "resolve", "update"))
        self._hooks = self.hooks
        self._proof_hooks = tuple(_hook(hook) for hook in self.reader.proof_hooks)
        self.before = self.reader.snapshot()
        self._before = self.before
        domain = {name: value for name, value in params.items() if name in _FIELDS[operation]}
        self.plan = plan_edit(self.before.uv, operation, params["uv_layer"], domain, self.reader.scope_keys)
        self._plan: UVPlan = self.plan
        self._expected = self.before
        self._expected_identity = self._expected
        scalar_count = _state_cost(self.before)
        # Every setter can be measured and compensated once, with update/final
        # snapshots. This budget includes preservation, not merely UV payloads.
        markers = 0 if self.before.checkpoint_markers is None else len(self.before.checkpoint_markers[1])
        compare_count = 6 * len(self.plan.writes) + 24 + 2 * markers
        # One full maximum-size read remains reserved even if a provider has
        # changed an otherwise bounded custom-data shape. Normal forward and
        # measured compensation reads have the original retained shape.
        if scalar_count * compare_count + MAX_NATIVE_VALUES > MAX_COMPARE_VALUES:
            raise _error("UV joint native verification and recovery budget is exceeded.")
        self._comparison_work = scalar_count
        self._snapshot_cost = scalar_count
        self.binding = None
        self._binding = None
        self.stopped: BridgeError | None = None
        self.refusal: str | None = None
        self.consumed = False
        self.stage = "PREPARED"
        self.started = self.possible = self.rollback = self.retained = False
        self.known = True
        self.observed: NativeState | None = self.before
        self.attempts = self.verified = self.restore_attempts = self.restored = 0
        self.update_attempts = self.update_verified = 0
        self._journal: tuple[tuple[CornerKey, str, UVCorner], ...] = ()
        self._journal_identity = self._journal
        self._identities = (self.reader.identities["object"], self.reader.identities["mesh"])
        self._name, self._layer = self.reader.object_name, self.reader.uv_layer
        self._before_digest = _digest(self.before)
        self._expected_digest = _digest(NativeState(self.before.preservation, self.plan.expected))
        self._mesh_texspace_profile = getattr(self.reader, "mesh_texspace_profile", None)

    def bind_checkpoint(self, binding: Any) -> Any:
        if (self.binding is not None or binding.context is not self.context
                or binding.callback is not self or binding.method != self.method or binding.params is not self.params):
            raise _error("UV factory proof cannot bind a different call.")
        self.binding = binding
        self._binding = binding
        def release() -> None:
            references = _CAPTURES.get(id(self.context), [])
            references[:] = [item for item in references if item() is not self and item() is not None]
            if not references:
                _CAPTURES.pop(id(self.context), None)
        return release

    def _stop(self, error: Exception, reason: str) -> BridgeError:
        if self.stopped is None:
            self.stopped = error if isinstance(error, BridgeError) else BridgeError(
                ErrorCode.OPERATION_FAILED, "UV scope or authority could not be verified.")
            self.refusal = reason
        return self.stopped

    def _identity(self) -> None:
        if self.stopped is not None:
            raise self.stopped
        if (self.context.registry is not self.registry or self.registry.get(self.method) is not self.spec
                or any(getattr(self.context, name, None) is not original for name, original in self.services)
                or self.plan is not self._plan or self.before is not self._before or self.reader is not self._reader
                or self._expected is not self._expected_identity or self._journal is not self._journal_identity
                or self.binding is not self._binding or type(self.reader) is not self._reader_type
                or vars(self._reader_type).get("proof_hooks") is not self._proof_descriptor
                or type(self.reader.object_name) is not str or type(self.reader.uv_layer) is not str
                or self.reader.object_name != self._name or self.reader.uv_layer != self._layer
                or not _identities(self.reader.identities)
                or (self.reader.identities["object"], self.reader.identities["mesh"]) != self._identities
                or type(self.reader.scope_keys) is not tuple
                or not 1 <= len(self.reader.scope_keys) <= 512
                or any(type(key) is not tuple or len(key) != 4 or any(type(item) is not int for item in key)
                       for key in self.reader.scope_keys)
                or self.reader.scope_keys != self._plan.scope_keys
                or self.params is not self.binding.params or _checkpoint_parameters(self.params) != self._parameters
                or self.context.checkpoint_admission is not self.binding
                or self.binding.callback is not self
                or not _same_hooks((_hook(self.binding.readonly_callback),), ((self, UVEditGuard.check_after_read),))
                or not _same_hooks((_hook(self.binding.marker_write_callback),), ((self, UVEditGuard.after_marker_write),))
                or self.hooks is not self._hooks
                or not _same_hooks(self._hooks, tuple(_hook(getattr(self.reader, name)) for name in ("snapshot", "resolve", "update")))
                or type(self.reader.proof_hooks) is not tuple
                or len(self.reader.proof_hooks) > 32
                or not _same_hooks(self._proof_hooks, tuple(_hook(hook) for hook in self.reader.proof_hooks))):
            raise self._stop(_error("The original UV call, plan, reader or lifecycle service changed."), "AUTHORITY_LOST")
        self.binding.check_identity(self.method)

    def _final(self) -> None:
        try:
            self._identity()
            check_final_mutation(self.context, self.method, expected_spec=self.spec)
        except Exception as error:
            raise self._stop(error, "AUTHORITY_LOST") from error

    def _live(self) -> None:
        try:
            self._identity()
            self.context.require(Permission.EDIT_MESH)
            if self.context.check_cancelled is not None:
                self.context.check_cancelled()
            self.context.require(Permission.EDIT_MESH)
            self._final()
        except Exception as error:
            self.known, self.observed = False, None
            raise self._stop(error, "AUTHORITY_LOST") from error

    def _read(self) -> NativeState:
        try:
            if self._comparison_work + MAX_NATIVE_VALUES > MAX_COMPARE_VALUES:
                raise _error("UV native comparison work budget is exhausted.")
            state = self.reader.snapshot()
            if type(state) is not NativeState:
                raise _error("UV reader returned an unqualified state.")
            self._comparison_work += _state_cost(state)
            return state
        except Exception as error:
            self.known, self.observed = False, None
            raise self._stop(error, "SESSION_INVALIDATED") from error

    def _compare(self) -> None:
        state = self._read()
        self.observed, self.known = state, True
        if state != self._expected:
            raise self._stop(_error("UV native state changed outside this retained edit."), "STATE_CHANGED")
        self._final()

    def __call__(self) -> None:
        self._live()
        self._compare()

    def check_after_read(self) -> None:
        """Core checkpoint read-only proof: witnesses, native CAS, pure gate."""
        self._identity()
        self._compare()

    def after_marker_write(self, event: Any) -> None:
        """Consume only the canonical actual bookkeeping write, never a getter."""
        from .checkpoint_completion import claim_marker_write_completion
        predicted = claim_marker_write_completion(self.context, self.method, self, event)
        self._identity()
        if self._expected.checkpoint_markers is None or type(predicted) is not tuple:
            raise self._stop(_error("UV checkpoint marker proof has no original native inventory."), "AUTHORITY_LOST")
        self._expected = replace(self._expected, checkpoint_markers=predicted)
        self._expected_identity = self._expected

    def _prepare(self) -> None:
        self.known, self.observed = False, None
        self._live()
        self._compare()
        self._final()

    def _measure_write(self, old: NativeState, expected: NativeState) -> bool:
        state = self._read()
        self.observed, self.known = state, True
        if state == expected:
            self._expected = expected
            self._expected_identity = self._expected
            return True
        if state == old:
            return False
        raise self._stop(_error("UV setter left an unknown or unowned state."), "UNKNOWN_WRITE_RESULT")

    def _write(self, key: CornerKey, field: str, source: UVCorner, *, restoring: bool = False) -> None:
        self._identity()
        allowed = next((write for write in self._plan.writes if write.key == key
                        and ("uv" if write.uv is not None else "pin_uv") == field), None)
        origin = self.before if restoring else NativeState(self.before.preservation, self._plan.expected)
        intended = _corner(origin, self._layer, key) if allowed is not None else None
        if (allowed is None or type(source) is not UVCorner or source is not intended
                or (restoring and not any(row[0] == key and row[1] == field for row in self._journal))):
            # NativeState/UVSnapshot retain the exact frozen UVCorner values;
            # neither callback-substituted plans nor journals grant ownership.
            raise self._stop(_error("UV field routing lost its original planned ownership."), "AUTHORITY_LOST")
        self._prepare()
        if not restoring:
            remaining = len(self._plan.writes) - self.attempts
            needed = 3 * remaining + 3 * (len(self._journal) + remaining) + 12
            if self._comparison_work + self._snapshot_cost * needed + MAX_NATIVE_VALUES > MAX_COMPARE_VALUES:
                # No field has been attempted here. Existing known owned
                # fields may still use their reserved measured compensation.
                raise _error("UV forward work would consume its retained compensation reserve.")
        old = self._expected
        previous = _corner(old, self._layer, key)
        # Predict only the owned field. In particular, compensation never
        # restores pins from a coordinate write or coordinates from pinning.
        replacement = (UVCorner(key, source.uv, source.uv_bits, previous.pin_uv) if field == "uv"
                       else UVCorner(key, previous.uv, previous.uv_bits, source.pin_uv))
        expected = _next(old, self._layer, key, replacement)
        try:
            # A closed leaf is charged conservatively as another complete
            # comparison. It performs only a subset of snapshot work.
            if self._comparison_work + self._snapshot_cost + MAX_NATIVE_VALUES > MAX_COMPARE_VALUES:
                raise _error("UV native leaf comparison work budget is exhausted.")
            self._comparison_work += self._snapshot_cost
            # Every broad native getter is finished before this closed leaf.
            # A refused/unknown leaf is sticky; recovery cannot adopt a later
            # provider's return to the old state as fresh authority.
            target = self.reader.resolve(key, field, previous)
        except Exception as error:
            self.known, self.observed = False, None
            raise self._stop(error, "INVALID_NATIVE_SCOPE") from error
        failure = None
        try:
            self._final()
            self.stage = "RESTORE" if restoring else "FIELD_WRITE"
            self.started = self.possible = True
            if restoring:
                self.restore_attempts += 1
            else:
                self.attempts += 1
            try:
                setattr(target, field, replacement.uv if field == "uv" else replacement.pin_uv)
            except Exception as error:
                failure = error
        finally:
            # A setter traceback must not retain a native UV target during
            # post-write observation, providers or any compensation attempt.
            target = None
        matched = self._measure_write(old, expected)
        if matched:
            if restoring:
                self.restored += 1
            else:
                self.verified += 1
                self._journal = (*self._journal, (key, field, previous))
                self._journal_identity = self._journal
        if failure is not None:
            raise failure
        if not matched:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "UV setter did not store its exact predicted field.")

    def _update(self) -> None:
        self._prepare()
        self.stage = "UPDATE"
        self.started = self.possible = True
        self.update_attempts += 1
        try:
            self.reader.update()
        except Exception as error:
            self.known, self.observed = False, None
            raise self._stop(error, "UNKNOWN_WRITE_RESULT") from error
        self._compare()
        self.update_verified += 1

    def _recover(self) -> None:
        if self.stopped is not None or not self.known:
            return
        try:
            self._identity()
            for key, field, original in reversed(self._journal):
                self._write(key, field, original, restoring=True)
            if self._journal:
                self._update()
            self._compare()
            # Marker-only core checkpoint bookkeeping is not an authored UV
            # field to undo. Its current value was advanced only by receipts.
            self.rollback = self._expected == replace(self.before, checkpoint_markers=self._expected.checkpoint_markers)
        except Exception:
            if self.refusal is None:
                self.refusal = "UNKNOWN_WRITE_RESULT"
            self.rollback = False

    def evidence(self) -> dict[str, Any]:
        obj, mesh = self._identities
        return {"kind": "uv_mutation", "method": self.method, "object_name": self._name, "uv_layer": self._layer,
                "object_pointer": obj[0], "object_session_uid": obj[1],
                "mesh_pointer": mesh[0], "mesh_session_uid": mesh[1], "stage": self.stage,
                "execution_started": self.started, "possible_mutation": self.possible,
                "rollback_verified": self.rollback, "verification_required": True, "state_known": self.known,
                "retained_partial": self.retained, "owned_field_attempts": self.attempts,
                "owned_field_verified": self.verified, "restoration_attempts": self.restore_attempts,
                "restored_fields": self.restored, "native_update_attempts": self.update_attempts,
                "native_update_verified": self.update_verified, "before_sha256": self._before_digest,
                "expected_sha256": self._expected_digest,
                "observed_sha256": _digest(self.observed) if self.known and self.observed is not None else None,
                "restoration_refused": self.refusal}

    def execute(self) -> dict[str, Any]:
        if self.consumed:
            raise _error("A UV guard cannot execute twice.")
        self.consumed = True
        try:
            self._prepare()
            for write in self.plan.writes:
                self._write(write.key, "uv" if write.uv is not None else "pin_uv",
                            _corner(NativeState(self.before.preservation, self.plan.expected), self._layer, write.key))
            if self.plan.writes:
                self._update()
            self._prepare()
            self.stage = "COMPLETE"
            return self._result()
        except Exception as error:
            self._recover()
            self.stage = "FAILED"
            self.retained = self.possible and not self.rollback
            code = error.code if isinstance(error, BridgeError) else ErrorCode.OPERATION_FAILED
            details = dict(error.context) if isinstance(error, BridgeError) else {}
            details.update(object=self._name, affected_objects=[self._name], uv_layer=self._layer,
                           execution_started=self.started, possible_mutation=self.possible,
                           rollback_verified=self.rollback, verification_required=True,
                           recovery_evidence=self.evidence(),
                           mesh_texture_space={"initial_profile": self._mesh_texspace_profile,
                                               "automatic_cache_verified": False, "hidden_state_verified": False})
            raise BridgeError(code, "UV edit failed; inspect its measured recovery evidence before retrying.", details) from error

    def _result(self) -> dict[str, Any]:
        plan = self._plan
        layer = next(layer for layer in plan.expected.maps if layer.name == self._layer)
        domain = {name: value for name, value in self.params.items() if name in _FIELDS[plan.operation]}
        if plan.operation == "coordinates_set":
            keys = [(row["face_index"], row["corner_index"]) for row in domain["updates"]]
        elif domain.get("corners") is not None:
            keys = [(row["face_index"], row["corner_index"]) for row in domain["corners"]]
        else:
            keys = [key[:2] for key in plan.scope_keys]
        lookup = {row.key[:2]: row for row in layer.corners}
        rows = [lookup[key] for key in keys]
        if plan.operation == "transform" and domain.get("respect_pins", True):
            rows = [row for row in rows if not row.pin_uv]
        result = {"object": self._name, "affected_objects": [self._name], "uv_layer": self._layer,
                  "changed": bool(plan.writes), "coordinate_changes": plan.coordinate_changes,
                  "pin_changes": plan.pin_changes, "target_corners": plan.target_corners,
                  "pinned_corners_after": sum(row.pin_uv for row in rows), "bounds_scope": "target_corners",
                  "bounds_after": {"min": [min(row.uv[i] for row in rows) for i in range(2)],
                                   "max": [max(row.uv[i] for row in rows) for i in range(2)]} if rows else None,
                  "corners": [{"face_index": row.key[0], "corner_index": row.key[1]} for row in rows[:64]],
                  "corners_truncated": len(rows) > 64, "selection_changed": False, "topology_changed": False,
                  "active_layer_changed": False, "verification_required": True, "warnings": [],
                  "recovery_evidence": self.evidence(), "native_undo_boundary_verified": False,
                  "durable_backup_verified": False, "user_goal_verified": False,
                  "preservation_scope": "bounded authored UV/maps, selection, topology, context and literal consumers",
                  "mesh_texture_space": {"initial_profile": self._mesh_texspace_profile,
                                         "automatic_cache_verified": False, "hidden_state_verified": False}}
        if plan.operation == "transform":
            result.update(skipped_pinned_corners=plan.skipped_pinned_corners,
                          transform_order="pivot-relative scale, counterclockwise rotation (radians), then offset")
        return result


def factory(method: str, context: Any, params: Any) -> UVEditGuard:
    guard = UVEditGuard(method, context, params)
    _CAPTURES.setdefault(id(context), []).append(ref(guard))
    return guard


def current(context: Any, method: str, params: Any) -> UVEditGuard:
    captures = [item() for item in _CAPTURES.get(id(context), ()) if item() is not None]
    binding = getattr(context, "checkpoint_admission", None)
    guard = getattr(binding, "callback", None)
    if (type(guard) is not UVEditGuard or not any(guard is item for item in captures)
            or guard.context is not context or guard.method != method or guard.params is not params
            or guard.binding is not binding):
        raise _error("UV mutation requires its original registered factory binding; recapture is forbidden.")
    guard._identity()
    return guard


class _NativeReader:
    """Closed native profile. See uv-edit-safety.md for explicit exclusions."""

    def __init__(self, context: Any, params: dict[str, Any]):
        import bmesh  # type: ignore

        from .selection import validate_selection_reference
        from .tools import _scene_mutation as scene
        from .utils import require_blender

        self.bpy, self.bmesh = require_blender(), bmesh
        if threading.current_thread() is not threading.main_thread():
            raise _error("UV native admission requires Blender's main thread.")
        self.object_name, self.uv_layer = params["object_name"], params["uv_layer"]
        self.obj = self.bpy.data.objects.get(self.object_name)
        if self.obj is None or type(self.obj) is not self.bpy.types.Object or self.obj.type != "MESH":
            raise BridgeError(ErrorCode.INVALID_ARGUMENT, "UV editing requires an existing native mesh Object.")
        self.mesh = self.obj.data
        if type(self.mesh) is not self.bpy.types.Mesh:
            raise _error("UV editing requires an exact native Mesh.")
        scene.descriptors(self.bpy, self.obj)
        self._mesh_descriptors()
        self._from, self._update = bmesh.from_edit_mesh, bmesh.update_edit_mesh
        if (self.bpy.context.mode != "EDIT_MESH" or self.obj.mode != "EDIT"
                or self.bpy.context.edit_object is not self.obj or not self.mesh.is_editmode):
            raise _error("UV admission requires the active live Edit Mode mesh.")
        self.bm = self._from(self.mesh)
        if len(self.bm.verts) > 512 or len(self.bm.edges) > 1024 or len(self.bm.faces) > 512:
            raise _error("UV native topology exceeds its bounded profile.")
        self.verts, self.edges, self.faces = tuple(self.bm.verts), tuple(self.bm.edges), tuple(self.bm.faces)
        self.loops = tuple(loop for face in self.faces for loop in face.loops)
        if (not 1 <= len(self.loops) <= 512 or len(self.verts) > 512 or len(self.edges) > 1024
                or len(self.faces) > 512):
            raise _error("UV native admission supports at most 512 corners/vertices/faces and 1024 edges.")
        if any(tuple(item.index for item in values) != tuple(range(len(values)))
               for values in (self.verts, self.edges, self.faces)):
            raise _error("UV admission requires current consecutive native indices; inspect again.")
        self.keys = tuple((face.index, index, loop.vert.index, loop.edge.index)
                          for face in self.faces for index, loop in enumerate(face.loops))
        self._lookup = dict(zip(self.keys, self.loops, strict=True))
        reference = params.get("selection_id")
        scoped = validate_selection_reference(reference, self.obj, self.bm) if reference else None
        selected_faces = tuple(face for face in self.faces if face.index in scoped["faces"]) if scoped else tuple(
            face for face in self.faces if face.select)
        if not selected_faces or any(face.hide or any(loop.vert.hide or loop.edge.hide for loop in face.loops)
                                     for face in selected_faces):
            raise BridgeError(ErrorCode.INVALID_SELECTION, "UV scope requires visible selected/referenced faces.")
        face_indices = {face.index for face in selected_faces}
        self.scope_keys = tuple(key for key in self.keys if key[0] in face_indices)
        self.identities = {"object": self._token(self.obj), "mesh": self._token(self.mesh)}
        self._scene, self._view_layer = self.bpy.context.scene, self.bpy.context.view_layer
        self._checkpoints = context.checkpoints
        self._marker_reader = self._checkpoints._marker_evidence
        self._checkpoint_prefix = self._checkpoints._prefix
        self._identity = (self._token(self.obj), self._token(self.mesh), self._token(self._scene),
                          int(self._view_layer.as_pointer()))
        self.scalar_count = 0
        self._witness_types = tuple((type(item), getattr(type(item), "is_valid", None))
                                    for item in (self.bm, *self.verts, *self.edges, *self.faces, *self.loops))
        self._layer_access = tuple((type(sequence.layers), tuple((name, descriptor)
                for name, descriptor in vars(type(sequence.layers)).items()
                if not name.startswith("_") and type(descriptor) in (GetSetDescriptorType, MemberDescriptorType)))
                for sequence in (self.bm.verts, self.bm.edges, self.bm.faces, self.bm.loops))
        self._uv_type = bmesh.types.BMLoopUV
        self._uv_descriptors = tuple((name, vars(self._uv_type).get(name))
                                     for name in (("uv", "pin_uv") if hasattr(type(self.bm), "uv_select_sync_valid")
                                                  else ("uv", "pin_uv", "select", "select_edge")))
        if any(type(descriptor) is not GetSetDescriptorType for _name, descriptor in self._uv_descriptors):
            raise _error("UV payload requires canonical native storage descriptors.")

    @property
    def proof_hooks(self) -> tuple[Any, ...]:
        return (self.snapshot, self.resolve, self.update, self._ordinary_witnesses, self._leaf_witness, self._witnesses,
                self._profile, self._layers, self._copy_corner, self._mesh_descriptors, self._mesh_primitive,
                self._token, self._marker_reader)

    def _mesh_descriptors(self) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
        return _mesh_properties(self.bpy, self.mesh)

    def _mesh_primitive(self) -> tuple[Any, ...]:
        from .tools import _scene_mutation as scene
        props, metadata = self._mesh_descriptors()
        texspace = metadata[-4]
        auto = texspace[0]
        self.mesh_texspace_profile = texspace[1]
        values = []
        for prop in props:
            if prop.is_runtime or prop.is_readonly or prop.type not in scene.PRIMITIVES | {"POINTER"}:
                continue
            if prop.identifier in _TEXSPACE_VECTORS:
                if auto:
                    continue
                value = _manual_texspace_vector(self.mesh, prop.identifier)
            else:
                value = scene.value(getattr(self.mesh, prop.identifier))
            values.append((prop.identifier, value))
        if self.mesh.use_auto_texspace is not auto:
            raise _error("Mesh texture-space mode changed during its primitive projection.")
        raw = scene.custom(self.mesh)
        if metadata[1] == "RAW_IDPROPERTIES":
            cycles = next((value for name, value in raw if name == "cycles"), None)
            if (cycles is not None) != metadata[-2] or (cycles is not None and cycles[0] != "group"):
                raise _error("Raw Cycles Mesh storage does not match its native group presence.")
        return tuple(values), raw, metadata

    @staticmethod
    def _token(owner: Any) -> tuple[int, int]:
        pointer, uid = owner.as_pointer(), owner.session_uid
        if type(pointer) is not int or type(uid) is not int or not 0 < pointer < 2**64 or not 0 < uid < 2**64:
            raise _error("UV admission requires native pointer and session UID identities.")
        return pointer, uid

    def _ordinary_witnesses(self) -> None:
        objects = (self.bm, *self.verts, *self.edges, *self.faces, *self.loops)
        if any(type(item) is not kind or getattr(kind, "is_valid", None) is not descriptor
               for item, (kind, descriptor) in zip(objects, self._witness_types, strict=True)):
            raise _error("UV ordinary native witness descriptors changed.", uv_witness_valid=False)
        # Never touch a descendant payload after an invalid ordinary witness.
        if any(item.is_valid is not True for item in objects):
            raise _error("UV ordinary native witnesses were invalidated.", uv_witness_valid=False)
        if (self.bmesh.types.BMLoopUV is not self._uv_type
                or any(vars(self._uv_type).get(name) is not descriptor for name, descriptor in self._uv_descriptors)):
            raise _error("UV native storage descriptors changed.", uv_witness_valid=False)

    def _witnesses(self) -> None:
        self._ordinary_witnesses()
        if (self.bmesh.from_edit_mesh is not self._from or self.bmesh.update_edit_mesh is not self._update
                or not _same_hooks((_hook(self._checkpoints._marker_evidence),), (_hook(self._marker_reader),))
                or self._checkpoints._prefix != self._checkpoint_prefix
                or self._from(self.mesh) is not self.bm):
            raise _error("UV edit-session BMesh identity changed.", uv_witness_valid=False)

    def _leaf_witness(self, loop: Any) -> None:
        # Direct ordinary validity getters do not access CustomData payloads.
        # Full inventory/descriptor checks already ran before this leaf copy.
        if self.bm.is_valid is not True or loop.is_valid is not True:
            raise _error("UV ordinary leaf witnesses were invalidated.", uv_witness_valid=False)

    def _profile(self) -> None:
        from .tools import _scene_mutation as scene
        bpy, obj, mesh, ctx = self.bpy, self.obj, self.mesh, self.bpy.context
        # RNA descriptor screening precedes value getters on every observation.
        for owner in (obj, mesh, self._scene, ctx.scene.tool_settings):
            self._mesh_descriptors() if owner is mesh else scene.descriptors(bpy, owner)
        if (bpy.data.objects.get(self.object_name) is not obj or obj.data is not mesh
                or (self._token(obj), self._token(mesh), self._token(ctx.scene), int(ctx.view_layer.as_pointer())) != self._identity
                or ctx.mode != "EDIT_MESH" or obj.mode != "EDIT" or not mesh.is_editmode
                or ctx.edit_object is not obj or ctx.view_layer.objects.active is not obj
                or tuple(ctx.objects_in_mode_unique_data) != (obj,)):
            raise _error("UV editing requires the original single active Edit Mode session.")
        if any(owner.library is not None or owner.override_library is not None or not owner.is_editable
               for owner in (obj, mesh, self._scene)) or mesh.users != 1:
            raise _error("UV editing requires local editable single-user Object and Mesh data.")
        if (obj.parent is not None or obj.animation_data is not None or mesh.animation_data is not None
                or len(obj.children) or len(obj.modifiers) or len(obj.constraints) or len(obj.vertex_groups)
                or len(mesh.materials) or mesh.shape_keys is not None or len(mesh.color_attributes)
                or obj.instance_type != "NONE"):
            raise _error("Initial UV guard profile excludes materials, rigs, modifiers, hierarchy and animation.")
        if (tuple(obj.users_scene) != (self._scene,) or not 1 <= len(obj.users_collection) <= 8
                or len(self._scene.objects) > 256 or len(self.bpy.data.scenes) > 200):
            raise _error("UV Object ownership requires one current Scene and at most eight Collections.")
        if not ctx.preferences.edit.use_global_undo or ctx.preferences.edit.undo_steps == 0:
            raise _error("UV admission requires existing global undo settings; preferences are not changed.")
        scene.runtime(bpy)
        if (ctx.scene.tool_settings.use_uv_select_sync
                or (hasattr(type(self.bm), "uv_select_sync_valid") and self.bm.uv_select_sync_valid is not False)):
            raise _error("Initial UV guard requires unsynchronized native UV selection storage.")
        marker = self._scene.get("_codex_bridge_undo_marker")
        from .checkpoints import TOKEN_PATTERN
        if marker is not None and (type(marker) is not str or TOKEN_PATTERN.fullmatch(marker) is None):
            raise _error("Reserved checkpoint marker contains unrelated data.")

    def _layers(self) -> tuple[str, ...]:
        from .tools import _scene_mutation as scene
        names = tuple(self.bm.loops.layers.uv.keys())
        if not 1 <= len(names) <= 8 or self.uv_layer not in names or len(set(names)) != len(names):
            raise _error("UV editing requires one to eight complete existing UV maps.")
        # No other BMesh custom-data payload has a preservation reader in this
        # first profile. Modern global selection layers are captured separately.
        modern = hasattr(type(self.bm), "uv_select_sync_valid")
        flags = {prefix + name for name in names for prefix in ((".pn.",) if modern else (".pn.", ".vs.", ".es."))}
        if set(self.bm.loops.layers.bool.keys()) != flags:
            raise _error("Complete physical UV pin/selection storage is required; missing storage is unqualified.")
        sequences = ((self.bm.verts, {}), (self.bm.edges, {}), (self.bm.faces, {}),
                     (self.bm.loops, {"uv": set(names), "bool": flags}))
        for (sequence, allowed), (kind, descriptors) in zip(sequences, self._layer_access, strict=True):
            access = sequence.layers
            fresh = tuple((name, descriptor) for name, descriptor in vars(type(access)).items()
                          if not name.startswith("_") and type(descriptor) in (GetSetDescriptorType, MemberDescriptorType))
            if type(access) is not kind or fresh != descriptors:
                raise _error("UV native custom-data access descriptors changed.")
            # Enumerate every exposed native family, including skin/mask and
            # future native families. Any nonempty unreviewed family refuses.
            for family, _descriptor in descriptors:
                layers = getattr(access, family)
                if not callable(getattr(layers, "keys", None)):
                    raise _error("UV custom-data family has an unsupported native shape.")
                observed = set(layers.keys())
                if observed - allowed.get(family, set()):
                    raise _error("UV guard refuses unreviewed BMesh custom-data layers.", custom_data_family=family)
        if len(self.mesh.attributes) > 128:
            raise _error("UV attribute schema exceeds its bounded profile.")
        for attribute in self.mesh.attributes:
            scene.descriptors(self.bpy, attribute)
            expected = ("CORNER", "FLOAT2") if attribute.name in names else ("CORNER", "BOOLEAN") if attribute.name in flags else None
            if expected is None or (attribute.domain, attribute.data_type) != expected:
                raise _error("UV guard refuses unsupported Mesh attribute metadata.")
        return names

    def snapshot(self) -> NativeState:
        from .tools import _scene_mutation as scene
        self._witnesses()
        self._profile()
        names = self._layers()
        bm, mesh, obj, ctx = self.bm, self.mesh, self.obj, self.bpy.context
        if (tuple(bm.verts) != self.verts or tuple(bm.edges) != self.edges or tuple(bm.faces) != self.faces
                or tuple(loop for face in self.faces for loop in face.loops) != self.loops):
            raise _error("UV native topology/witness inventory changed.")
        geometry = (tuple((vert.index, tuple(vert.co), tuple(vert.normal), vert.select, vert.hide, vert.tag)
                          for vert in self.verts),
                    tuple((edge.index, tuple(vert.index for vert in edge.verts), edge.select, edge.hide, edge.tag,
                           edge.seam, edge.smooth) for edge in self.edges),
                    tuple((face.index, tuple((loop.vert.index, loop.edge.index) for loop in face.loops),
                           face.select, face.hide, face.tag, face.smooth, face.material_index, tuple(face.normal))
                          for face in self.faces))
        consumers = self.bpy.data.user_map(subset={obj, mesh})
        if len(consumers.get(obj, ())) > 16 or len(consumers.get(mesh, ())) > 1:
            raise _error("UV target native consumer inventory exceeds its bounded profile.")
        ownership = []
        permitted = {self._token(self._scene), *(self._token(owner) for owner in obj.users_collection)}
        for target in (obj, mesh):
            rows = []
            for owner in consumers.get(target, set()):
                scene.descriptors(self.bpy, owner)
                identity = self._token(owner)
                if (target is obj and identity not in permitted) or (target is mesh and owner is not obj):
                    raise _error("UV target has an unsupported native consumer.")
                rows.append((owner.bl_rna.identifier, owner.name_full, identity, owner.user_of_id(target)))
            ownership.append((self._token(target), tuple(sorted(rows))))
        object_values = scene.primitive(self.bpy, obj)
        mesh_values = self._mesh_primitive()
        collection_values = []
        for collection in obj.users_collection:
            scene.descriptors(self.bpy, collection)
            if (collection.library is not None or collection.override_library is not None or not collection.is_editable
                    or len(collection.children) or len(collection.objects) > 256
                    or (collection is not self._scene.collection and collection not in tuple(self._scene.collection.children))):
                raise _error("UV owning Collections require local direct Scene membership without nested children.")
            collection_values.append((self._token(collection), scene.primitive(self.bpy, collection),
                                      tuple(self._token(owner) for owner in collection.objects)))
        custom_budget = [4096]
        scene_custom = tuple((name, scene.custom_value(self._scene[name], budget=custom_budget))
                             for name in sorted(scene.bounded(self._scene.keys(), 128, "custom keys"))
                             if name != "_codex_bridge_undo_marker")
        role = (tuple((layer.name, bool(layer.active_render), bool(layer.active_clone)) for layer in mesh.uv_layers),
                mesh.uv_layers.active_index, None if bm.loops.layers.uv.active is None else bm.loops.layers.uv.active.name,
                tuple((attribute.name, attribute.domain, attribute.data_type) for attribute in mesh.attributes))
        modern = hasattr(type(bm), "uv_select_sync_valid")
        selection = (("MESH_GLOBAL", bm.uv_select_sync_valid,
                      tuple((face.index, face.uv_select) for face in self.faces),
                      tuple((key, loop.uv_select_vert, loop.uv_select_edge) for key, loop in zip(self.keys, self.loops, strict=True)))
                     if modern else ("PER_LAYER",))
        maps = {}
        legacy = []
        for name in names:
            rows = []
            flags = []
            for key, loop in zip(self.keys, self.loops, strict=True):
                # A fresh named layer/item/vector is confined to this copy.
                uv, pin, selected = self._copy_corner(loop, name, modern)
                rows.append(dict(zip(("face", "corner", "vertex", "edge"), key, strict=True), uv=list(uv), pin_uv=pin))
                if not modern:
                    flags.append((key, *selected))
            maps[name] = rows
            if not modern:
                legacy.append((name, tuple(flags)))
        settings = ctx.scene.tool_settings
        select_mode = tuple(sorted(bm.select_mode))
        if not select_mode or any(type(value) is not str or value not in {"VERT", "EDGE", "FACE"} for value in select_mode):
            raise _error("UV BMesh selection mode has an unsupported native shape.")
        context = (self._identity, ctx.mode, tuple(self._token(item) for item in ctx.selected_objects),
                   tuple(None if owner is None else int(owner.as_pointer()) for owner in (ctx.window, ctx.area, ctx.region)),
                   tuple(settings.mesh_select_mode), settings.use_uv_select_sync, settings.uv_select_mode,
                   ctx.scene.frame_current, ctx.scene.frame_subframe, self.bpy.data.filepath,
                   select_mode,
                   tuple((type(item).__name__, item.index) for item in bm.select_history),
                   None if bm.faces.active is None else bm.faces.active.index)
        preserved = _plain((geometry, ownership, object_values, mesh_values, tuple(collection_values), scene_custom, role, selection,
                            tuple(legacy), context))
        self.scalar_count = _count(preserved) + len(self.loops) * len(names) * 3
        return NativeState(preserved, freeze_snapshot(maps), self._marker_reader(self.bpy))

    def _copy_corner(self, loop: Any, name: str, modern: bool) -> Any:
        layer = data = None
        try:
            self._leaf_witness(loop)
            layer = self.bm.loops.layers.uv.get(name)
            self._leaf_witness(loop)
            data = loop[layer]
            self._leaf_witness(loop)
            if type(data) is not self._uv_type:
                raise _error("UV payload owner differs from the canonical native type.")
            uv, pin = tuple(data.uv), data.pin_uv
            if type(pin) is not bool:
                raise _error("UV pin storage is unavailable; absent values are not false.")
            selected = () if modern else (data.select, data.select_edge)
            self._leaf_witness(loop)
            return uv, pin, selected
        finally:
            data = layer = None

    def resolve(self, key: CornerKey, field: str, expected: UVCorner) -> Any:
        self._witnesses()
        self._layers()
        if (field not in {"uv", "pin_uv"} or key not in self._lookup
                or type(expected) is not UVCorner or expected.key != key):
            raise _error("UV setter target differs from the frozen corner inventory.")
        loop = self._lookup[key]
        if loop is not self.loops[self.keys.index(key)]:
            raise _error("UV setter loop differs from its held ordinary witness.")
        layer = target = None
        try:
            layer = self.bm.loops.layers.uv.get(self.uv_layer)
            if layer is None:
                raise _error("The original named UV layer disappeared.")
            self._leaf_witness(loop)
            target = loop[layer]
            layer = None
            self._leaf_witness(loop)
            if type(target) is not self._uv_type:
                raise _error("UV setter payload differs from the canonical native type.")
            if field == "uv":
                values = tuple(target.uv)
                matched = tuple(struct.pack("<f", value).hex() for value in values) == expected.uv_bits
            else:
                pin = target.pin_uv
                matched = type(pin) is bool and pin is expected.pin_uv
            self._ordinary_witnesses()
            if not matched:
                raise _error("UV leaf field no longer matches its exact retained prefix.")
            return target
        except Exception:
            target = layer = None
            raise

    def update(self) -> None:
        self._update(self.mesh, loop_triangles=False, destructive=False)
