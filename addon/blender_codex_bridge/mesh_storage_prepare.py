# SPDX-License-Identifier: GPL-3.0-or-later
"""Unregistered 5.2 Mesh storage preparation, not a readonly getter fallback.

Stage A supplies a typed metadata plan and synchronous conversion primitive.
The source-qualified caller owns checkpoint/history, explicit preparation intent,
current INSPECT_SCENE+EDIT_MESH authority, protected dependencies, request slot,
database identity and resource measurements. No JSON callback is accepted.
The collection declaration pin records separately reviewed metadata only.
Owned functional/checkpoint qualification remains a separate Root gate.

The caller's source-qualified pure gate must check stop/slot first, then current
measured memory against its numeric floor before and after every native read or
conversion. The initial metadata pass needs a conservative base floor; before
preparation the caller adopts the plan's count-derived required-available floor.
The available_memory_bytes argument and receipt are initial call snapshots only;
the helper does not resample memory or reserve resources.

SINGLE values are first observed by the authorized materializing call. Normal
conversion is source-equivalent; an independently measured pre-value hash does
not exist. Allocation survival, total allocator cost and native latency are not
guaranteed. Partial physical transitions are retained without an inverse.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
import threading
from array import array
from dataclasses import dataclass
from functools import partial
from types import (
    FunctionType,
    MappingProxyType,
    MethodDescriptorType,
    MethodType,
    ModuleType,
    WrapperDescriptorType,
)
from typing import Any

from . import current_pixels_graph as graph
from .errors import BridgeError, ErrorCode

BUILD = b"d13f752e3b9c"
VERSION = (5, 2, 2)
# Official 5.2.2 metadata census: names, native descriptor kinds/owners and
# non-ASLR class declarations only; no instance or functional result is pinned.
COLLECTION_BINDING_PINS: dict[bytes, str] = {
    b"d13f752e3b9c": "01d76c36244d35a22287f12826e7a1d726d9c90951520f58adf29754ccc5b00c",
}
_COLLECTION_BINDING_PINS = COLLECTION_BINDING_PINS
COLLECTION_FIELDS = ("foreach_get", "__getitem__", "__len__", "__iter__", "get")
MAX_SELECTED = 32
MAX_ATTRIBUTES = 64
_COUNTS = (("vertices", 32_768), ("edges", 65_536), ("polygons", 32_768), ("loops", 131_072))
_VALUE_CLASSES = {"BOOLEAN": ("BoolAttribute", "BoolAttributeValue"),
                  "FLOAT2": ("Float2Attribute", "Float2AttributeValue"),
                  "FLOAT_VECTOR": ("FloatVectorAttribute", "FloatVectorAttributeValue"),
                  "INT32_2D": ("Int2Attribute", "Int2AttributeValue"),
                  "INT": ("IntAttribute", "IntAttributeValue")}
_ROW_BITS = ("data_lookup_entered", "data_lookup_returned", "materialize_entered", "materialize_returned",
             "after_storage_observed", "verified", "baseline_conflict")


def refused(reason: str) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, "Mesh storage preparation refused.",
                       {"reason": reason, "requires_fresh_image_preview": True})


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")


def _class_namespace(cls: type) -> Any:
    return type.__dict__["__dict__"].__get__(cls)


def _class_mro(cls: type) -> tuple:
    return type.__dict__["__mro__"].__get__(cls)


def _class_field(cls: type, name: str) -> Any:
    for base in _class_mro(cls):
        fields = _class_namespace(base)
        if name in fields:
            return fields[name]
    raise refused("COLLECTION_DESCRIPTOR_MISSING")


def _literal(value: Any, depth: int = 0) -> Any:
    """Bounded exact builtin facts; refuse foreign keys before any lookup."""
    kind = type(value)
    if value is None or kind in {str, int, bool, bytes, float}:
        return ("identity", value)
    if depth > 12:
        raise refused("SOURCE_LITERAL_BUDGET")
    if kind in {tuple, list, set, frozenset}:
        if len(value) > 8192:
            raise refused("SOURCE_LITERAL_BUDGET")
        rows = tuple(_literal(item, depth + 1) for item in value)
        return (kind, rows)
    if kind is dict:
        if len(value) > 8192 or any(type(key) not in {str, bytes, tuple} for key in value):
            raise refused("SOURCE_LITERAL_FOREIGN_KEY")
        for key in value:
            if type(key) is tuple and any(type(part) is not str for part in key):
                raise refused("SOURCE_LITERAL_FOREIGN_KEY")
        return (dict, tuple((key, _literal(item, depth + 1)) for key, item in value.items()))
    raise TypeError("nonliteral source value")


def _function_fact(function: Any) -> tuple:
    keywords = function.__kwdefaults__
    if keywords is not None and (type(keywords) is not dict or any(type(key) is not str for key in keywords)):
        raise refused("SOURCE_FUNCTION_KEYWORD_DEFAULTS")
    if function.__defaults__ is not None and type(function.__defaults__) is not tuple:
        raise refused("SOURCE_FUNCTION_DEFAULTS")
    return (function, function.__code__, function.__globals__, function.__defaults__,
            () if keywords is None else tuple(dict.items(keywords)),
            tuple((cell, cell.cell_contents) for cell in function.__closure__ or ()))


def _descriptor_functions(value: Any) -> tuple:
    if type(value) is FunctionType:
        return (value,)
    if type(value) in {classmethod, staticmethod}:
        return (value.__func__,)
    if type(value) is property:
        return tuple(fn for fn in (value.fget, value.fset, value.fdel) if fn is not None)
    return ()


def _literal_matches(value, fact, native):
    type_of, length, _tuples, _items, _module, _classes, _mro, all_of, any_of, zip_items = native[:10]
    str_type, bytes_type, tuple_type, dict_type, set_type, frozen_set_type = native[10:16]
    kind, saved = fact
    if kind == "identity":
        return value is saved
    if type_of(value) is not kind or length(value) != length(saved):
        return False
    if kind is dict_type:
        if any_of(type_of(key) not in (str_type, bytes_type, tuple_type) for key in value):
            return False
        for key in value:
            if type_of(key) is tuple_type and any_of(type_of(part) is not str_type for part in key):
                return False
        return all_of(key in value and _literal_matches(value[key], row, native) for key, row in saved)
    if kind in (set_type, frozen_set_type):
        return all_of(any_of(_literal_matches(item, row, native) for row in saved) for item in value)
    return all_of(_literal_matches(item, row, native) for item, row in zip_items(value, saved, strict=True))


def _run_guard(mode, seal, native):
    """Parameter-only dispatch: no generated mutable verifier or global builtin.

    The executing frame holds immutable seal/native tuples across a callback.
    Recheck this dispatcher's own code before any next helper dispatch too.
    """
    type_of, length, tuples, items, module_dict, class_dict, class_mro, _all_of, any_of, zip_items = native[:10]
    str_type, _bytes_type, _tuple_type, dict_type = native[10:14]
    function_type, exception_type, failure, literal_match = native[16:20]
    module_facts, class_facts, functions, literals, builtin_tables, callbacks = seal
    pending = None
    phase = 0
    while True:
        # Validate builtin tables before any unheld Python/global dispatch.
        for table, saved in builtin_tables:
            if (type_of(table) is not dict_type or length(table) != length(saved)
                    or any_of(type_of(key) is not str_type for key in table)
                    or any_of(name not in table or table[name] is not value for name, value in saved)):
                raise failure
        for module, saved in module_facts:
            fields = module_dict(module, "__dict__")
            if (length(fields) != length(saved) or any_of(type_of(key) is not str_type for key in fields)
                    or any_of(name not in fields or fields[name] is not value for name, value in saved)):
                raise failure
        for owner, mro, saved in class_facts:
            fields = class_dict(owner)
            if (class_mro(owner) is not mro or length(fields) != length(saved)
                    or any_of(type_of(key) is not str_type for key in fields)
                    or any_of(name not in fields or fields[name] is not value for name, value in saved)):
                raise failure
        for function, code, namespace, defaults, kwdefaults, closure in functions:
            if (type_of(function) is not function_type or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__defaults__ is not defaults):
                raise failure
            keywords = function.__kwdefaults__
            if keywords is None:
                current = ()
            elif type_of(keywords) is dict_type and not any_of(type_of(key) is not str_type for key in keywords):
                current = tuples(items(keywords))
            else:
                raise failure
            if (length(current) != length(kwdefaults)
                    or any_of(left[0] != right[0] or left[1] is not right[1]
                              for left, right in zip_items(current, kwdefaults, strict=True))):
                raise failure
            current = function.__closure__
            if current is None:
                current = ()
            if (length(current) != length(closure)
                    or any_of(cell is not old or cell.cell_contents is not value
                              for cell, (old, value) in zip_items(current, closure, strict=True))):
                raise failure
        for module, name, fact in literals:
            if not literal_match(module_dict(module, "__dict__")[name], fact, native):
                raise failure
        if pending is not None:
            raise pending
        if mode == "VERIFY" or (mode == "PURE" and phase == 1) or (mode == "FULL" and phase == 3):
            return
        callback = callbacks[1] if mode == "FULL" and phase == 1 else callbacks[0]
        phase += 1
        if callback is not None:
            try:
                callback()
            except exception_type as error:
                pending = error


class CaptureOrigin(tuple):
    """Immutable held provenance; caller source-qualifies gate semantics.

    Native tuple slots cannot be replaced by origin._pure/_verify assignment.
    Gates use a captured dispatcher and immutable facts, not generated verifier
    closures. This is source consistency, not an arbitrary Python sandbox.
    The pure callback owns stop-first current measured-resource admission at
    every native boundary, including provider-free metadata passes.
    """
    __slots__ = ()

    @classmethod
    def capture(cls, pure_check: Any, *, authorize: Any = None) -> CaptureOrigin:
        if cls is not CaptureOrigin:
            raise refused("CAPTURE_ORIGIN_REQUIRED")
        functions, modules, classes = [], [], []
        own_module = sys.modules[__name__]
        for callback in (pure_check,) if authorize is None else (pure_check, authorize):
            if type(callback) is FunctionType:
                function, owner = callback, None
            elif type(callback) is MethodType and type(callback.__func__) is FunctionType:
                function, owner = callback.__func__, callback.__self__
            else:
                raise refused("SOURCE_QUALIFIED_GATE_FUNCTION_REQUIRED")
            functions.append(_function_fact(function))
            module = sys.modules.get(function.__module__)
            if type(module) is ModuleType and module not in modules:
                modules.append(module)
            if owner is not None:
                classes.extend(_class_mro(type(owner)))
        for module in (own_module, graph, sys.modules[BridgeError.__module__]):
            if module not in modules:
                modules.append(module)
        module_facts, class_facts, literals = [], [], []
        for module in modules:
            fields = ModuleType.__getattribute__(module, "__dict__")
            if len(fields) > 4096 or any(type(key) is not str for key in fields):
                raise refused("SOURCE_MODULE_NAMESPACE")
            module_facts.append((module, tuple(dict.items(fields))))
            for name, value in tuple(dict.items(fields)):
                functions.extend(_function_fact(fn) for fn in _descriptor_functions(value))
                if type(value) is type and type.__getattribute__(value, "__module__") == fields.get("__name__"):
                    classes.extend(_class_mro(value))
                if module in (own_module, graph) and (name.isupper() or name.startswith("_")):
                    try:
                        literals.append((module, name, _literal(value)))
                    except TypeError:
                        continue
        unique = []
        for owner in classes:
            if owner in unique:
                continue
            if type(owner) is not type:
                raise refused("SOURCE_CLASS_ORIGIN")
            unique.append(owner)
            fields, mro = _class_namespace(owner), _class_mro(owner)
            if len(fields) > 512 or len(mro) > 32 or any(type(key) is not str for key in fields):
                raise refused("SOURCE_CLASS_NAMESPACE")
            class_facts.append((owner, mro, tuple(fields.items())))
            for value in fields.values():
                functions.extend(_function_fact(fn) for fn in _descriptor_functions(value))
        builtin_tables = []
        for fact in functions:
            table = fact[0].__builtins__
            if type(table) is not dict or any(type(key) is not str for key in table):
                raise refused("SOURCE_BUILTIN_TABLE")
            if not any(table is old for old, _saved in builtin_tables):
                builtin_tables.append((table, tuple(dict.items(table))))
        failure = refused("PREPARATION_SOURCE_OR_GATE_CHANGED")
        native = (type, len, tuple, dict.items, ModuleType.__getattribute__,
                  type.__dict__["__dict__"].__get__, type.__dict__["__mro__"].__get__,
                  all, any, zip, str, bytes, tuple, dict, set, frozenset,
                  FunctionType, BaseException, failure, _literal_matches)
        seal = (tuple(module_facts), tuple(class_facts), tuple(functions), tuple(literals),
                tuple(builtin_tables), (pure_check, authorize))
        result = tuple.__new__(cls, (seal, native, _run_guard))
        _guards(result)[2]()
        return result


def _guards(origin: Any, kind=CaptureOrigin, type_of=type, get=tuple.__getitem__,
            bind=partial) -> tuple:
    if type_of(origin) is not kind:
        raise refused("CAPTURE_ORIGIN_REQUIRED")
    seal, native, dispatch = get(origin, 0), get(origin, 1), get(origin, 2)
    # Authenticate the actual dispatcher before invoking it at API entry. Its
    # own executing frame repeats the complete seal after each callback.
    found = False
    for fact in get(seal, 2):
        if fact[0] is dispatch:
            if dispatch.__code__ is not fact[1] or dispatch.__defaults__ is not fact[3]:
                raise get(native, 18)
            found = True
    if not found:
        raise get(native, 18)
    return (bind(dispatch, "PURE", seal, native), bind(dispatch, "FULL", seal, native),
            bind(dispatch, "VERIFY", seal, native))


def _native_collection_class(bpy_types: Any) -> tuple[Any, Any]:
    if type(bpy_types) is not ModuleType:
        raise refused("COLLECTION_TYPES_MODULE_REQUIRED")
    fields = ModuleType.__getattribute__(bpy_types, "__dict__")
    bpy_module = sys.modules.get("bpy")
    if (type(bpy_module) is not ModuleType
            or ModuleType.__getattribute__(bpy_module, "__dict__").get("types") is not bpy_types):
        raise refused("COLLECTION_TYPES_MODULE_ORIGIN")
    cls = fields.get("bpy_prop_collection")
    if (type(cls) is not type or type.__getattribute__(cls, "__name__") != "bpy_prop_collection"
            or type.__getattribute__(cls, "__flags__") & (1 << 9)):
        raise refused("COLLECTION_NATIVE_CLASS_REQUIRED")
    for base in _class_mro(cls):
        if type(base) is not type or type.__getattribute__(base, "__flags__") & (1 << 9):
            raise refused("COLLECTION_NATIVE_MRO_REQUIRED")
    return fields, cls


def collection_binding_census(bpy_types: Any) -> dict:
    """Metadata only: no original, instance, provider, factory or native entry."""
    _fields, cls = _native_collection_class(bpy_types)
    descriptors = {}
    for name in COLLECTION_FIELDS:
        descriptor = _class_field(cls, name)
        if type(descriptor) not in {MethodDescriptorType, WrapperDescriptorType}:
            raise refused("COLLECTION_NATIVE_DESCRIPTOR_REQUIRED")
        descriptors[name] = {"type": type(descriptor).__name__, "name": descriptor.__name__,
                             "owner": type.__getattribute__(descriptor.__objclass__, "__name__")}
    result = {"schema": "mesh_storage_collection_binding_census_v1", "metadata_only": True,
              "native_entries": 0, "class": {"name": type.__getattribute__(cls, "__name__"),
              "module": type.__getattribute__(cls, "__module__"),
              "flags": type.__getattribute__(cls, "__flags__") & ~(1 << 19),
              "mro": [type.__getattribute__(base, "__name__") for base in _class_mro(cls)]},
              "bindings": descriptors, "foreach_get_coverage": True, "full_slice_coverage": True}
    result["sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


@dataclass(frozen=True)
class CollectionBindings:
    types_module: Any
    collection_class: Any
    descriptors: tuple[tuple[str, Any], ...]
    sha256: str
    zero_slice_qualified: bool

    def verify(self) -> None:
        _fields, cls = _native_collection_class(self.types_module)
        if cls is not self.collection_class or any(_class_field(cls, name) is not value for name, value in self.descriptors):
            raise refused("COLLECTION_BINDING_CHANGED")


def qualify_collection_bindings(bpy_types: Any, *, build_hash: bytes,
                                expected_sha256: str | None) -> CollectionBindings:
    if type(build_hash) is not bytes or build_hash != BUILD:
        raise refused("EXACT_5_2_BUILD_REQUIRED")
    if (type(expected_sha256) is not str or len(expected_sha256) != 64
            or expected_sha256 != COLLECTION_BINDING_PINS.get(BUILD)):
        raise refused("COLLECTION_BINDING_PIN_NOT_QUALIFIED")
    census = collection_binding_census(bpy_types)
    if census["sha256"] != expected_sha256:
        raise refused("COLLECTION_BINDING_CENSUS_CHANGED")
    _fields, cls = _native_collection_class(bpy_types)
    return CollectionBindings(bpy_types, cls, tuple((name, _class_field(cls, name)) for name in COLLECTION_FIELDS),
                              expected_sha256, True)


@dataclass(frozen=True)
class AttributeHeader:
    name: str
    domain: str
    data_type: str
    native_class: str
    value_class: str
    storage: str
    count: int
    schema_sha256: str
    value_schema_sha256: str


@dataclass(frozen=True)
class Target:
    name: str
    header: AttributeHeader | None
    action: str


@dataclass(frozen=True)
class _Metadata:
    obj: Any
    mesh: Any
    object_identity: tuple
    mesh_identity: tuple
    database_identity: str
    counts: tuple
    uv_roles: tuple
    attributes: tuple[AttributeHeader, ...]

    def plain(self) -> dict:
        return {"object": self.object_identity, "mesh": self.mesh_identity, "database_identity": self.database_identity,
                "counts": self.counts,
                "uv_roles": self.uv_roles, "attributes": [_header(row) for row in self.attributes]}


def _header(row: AttributeHeader) -> tuple:
    return (row.name, row.domain, row.data_type, row.native_class, row.value_class, row.storage,
            row.count, row.schema_sha256, row.value_schema_sha256)


def _resource_facts(targets: tuple[Target, ...], available: int, reserved: int) -> dict:
    if (type(available) is not int or type(reserved) is not int or not 0 <= available <= 2**63 - 1
            or not 0 <= reserved <= 2**63 - 1):
        raise refused("MEASURED_MEMORY_FACTS_REQUIRED")
    payload = sum(row.header.count * (8 if row.header.data_type == "FLOAT2" else 1)
                  for row in targets if row.action == "MATERIALIZE_SINGLE")
    values = sum(row.header.count for row in targets if row.action == "MATERIALIZE_SINGLE")
    required = 64 * 1024**2 + 3 * payload + 512 * values
    result = {"known_array_payload_bytes": payload, "required_available_memory_bytes": required + reserved,
              "required_preparation_memory_bytes": required, "available_memory_bytes": available,
              "available_memory_measurement_scope": "INITIAL_CALL_ARGUMENT_SNAPSHOT",
              "reserved_for_other_work_bytes": reserved, "admitted": available >= required + reserved,
              "resources_reserved": False, "hard_total_memory_bound": False,
              "native_OOM_survival": "UNPROVEN", "native_calls_preemptible": False}
    if not result["admitted"]:
        error = refused("STORAGE_PREPARATION_RESOURCE_REFUSED")
        error.context["resource_facts"] = result
        raise error
    return result


@dataclass(frozen=True)
class PreparationPlan:
    metadata: _Metadata
    targets: tuple[Target, ...]
    fingerprint: str
    resources: tuple

    def summary(self) -> dict:
        return {"schema": "mesh_storage_preparation_plan_v1", "build_hash": BUILD.decode(),
                "fingerprint": self.fingerprint, "metadata": self.metadata.plain(),
                "targets": [{"name": row.name, "action": row.action,
                             "header": None if row.header is None else _header(row.header)} for row in self.targets],
                "start_admitted": all(row.action in {"MATERIALIZE_SINGLE", "NOOP_ALREADY_ARRAY"} for row in self.targets),
                "resource_facts": dict(self.resources), "SINGLE_pre_value_hash_available": False,
                "native_entries": 0, "stage_B_registered": False,
                "dependency_protection_checkpoint_authority": "CALLER_SOURCE_QUALIFIED_GATE_REQUIRED"}


class _Access:
    def __init__(self, bpy: Any, pure: Any):
        self.bpy, self.pure = bpy, pure
        pure()
        self.reader = graph._Reader(bpy, pure)
        pure()

    def call(self, function: Any, *args: Any) -> Any:
        self.pure()
        value = function(*args)
        self.pure()
        return value

    def field(self, owner: Any, kind: str, name: str) -> Any:
        self.call(self.reader.catalog, owner, kind)
        return self.call(getattr, owner, name)

    def database(self) -> str:
        database = self.call(lambda: self.bpy.data)
        self.call(self.reader.catalog, database, "BlendData")
        base = self.call(lambda: self.bpy.types.bpy_struct)
        descriptor = _class_field(type(database), "as_pointer")
        if (type(descriptor) is not MethodDescriptorType or descriptor.__objclass__ is not base
                or _class_field(base, "as_pointer") is not descriptor):
            raise refused("BLEND_DATA_POINTER_BINDING_CHANGED")
        pointer = self.call(descriptor, database)
        return format(graph._int(pointer, 2**64 - 1, minimum=1), "x")

    def snapshot(self, object_name: str, mesh_name: str) -> _Metadata:
        if (self.call(lambda: self.bpy.app.build_hash) != BUILD
                or tuple(self.call(lambda: self.bpy.app.version)) != VERSION):
            raise refused("EXACT_5_2_BUILD_REQUIRED")
        database_identity = self.database()
        obj = self.call(lambda: self.bpy.data.objects.get(object_name))
        mesh = self.call(lambda: self.bpy.data.meshes.get(mesh_name))
        if obj is None or mesh is None:
            raise refused("EXACT_ORIGINAL_OBJECT_AND_MESH_REQUIRED")
        object_identity = tuple(self.call(self.reader.local_id, obj, "Object").items())
        mesh_identity = tuple(self.call(self.reader.local_id, mesh, "Mesh").items())
        if (self.field(obj, "Object", "data") is not mesh or self.field(obj, "Object", "type") != "MESH"
                or self.field(obj, "Object", "mode") != "OBJECT" or self.field(mesh, "Mesh", "is_editmode") is not False
                or self.field(mesh, "Mesh", "shape_keys") is not None or self.field(mesh, "Mesh", "users") != 1
                or self.field(obj, "Object", "is_evaluated") is not False
                or self.field(mesh, "Mesh", "is_evaluated") is not False):
            raise refused("ORIGINAL_SINGLE_USER_OBJECT_MESH_SCOPE_REQUIRED")
        counts = {}
        for name, maximum in _COUNTS:
            count = self.call(len, self.field(mesh, "Mesh", name))
            if type(count) is not int or not 0 <= count <= maximum:
                raise refused("STORAGE_GEOMETRY_COUNT_BUDGET")
            counts[name] = count
        if (self.field(mesh, "Mesh", "has_custom_normals") is not False
                or self.call(len, self.field(mesh, "Mesh", "color_attributes"))):
            raise refused("UNSUPPORTED_NORMAL_OR_COLOR_LAYOUT")
        layers = self.call(graph._bounded, self.field(mesh, "Mesh", "uv_layers"), 2)
        roles = tuple((graph._text(self.field(layer, "MeshUVLoopLayer", "name")),
                       graph._bool(self.field(layer, "MeshUVLoopLayer", "active_render")),
                       graph._bool(self.field(layer, "MeshUVLoopLayer", "active_clone"))) for layer in layers)
        uv_names = tuple(row[0] for row in roles)
        if len(set(uv_names)) != len(uv_names):
            raise refused("DUPLICATE_UV_NAMES")
        self.call(self.reader.class_catalog, "UVLoopLayers")
        active = self.call(getattr, self.field(mesh, "Mesh", "uv_layers"), "active_index")
        # Stock 5.2 stores active/default/clone UV names independently. An absent
        # active name reads as -1; absent default/clone names select no layer.
        # Preserve those values in the metadata/CAS rather than assigning roles.
        if (type(active) is not int or not -1 <= active < len(roles)
                or sum(row[1] for row in roles) > 1 or sum(row[2] for row in roles) > 1):
            raise refused("UV_ROLE_SCHEMA")
        _headers, views, _auxiliary, physical = self.call(graph._attribute_inventory, self.reader, mesh, counts, uv_names)
        del views, layers
        headers = []
        for name, domain, data_type, storage, count in physical:
            native, leaf = _VALUE_CLASSES[data_type]
            self.call(self.reader.class_catalog, native)
            self.call(self.reader.class_catalog, leaf)
            headers.append(AttributeHeader(name, domain, data_type, native, leaf, storage, count,
                                           self.reader.catalogs[native], self.reader.catalogs[leaf]))
        return _Metadata(obj, mesh, object_identity, mesh_identity, database_identity,
                         tuple(counts.items()), (active, roles), tuple(headers))

    def attribute(self, mesh: Any, target: AttributeHeader) -> Any:
        attributes = self.call(graph._bounded, self.field(mesh, "Mesh", "attributes"), MAX_ATTRIBUTES)
        selected = None
        for attribute in attributes:
            self.call(self.reader.catalog, attribute, target.native_class if type(attribute) is
                      getattr(self.bpy.types, target.native_class) else type(attribute).__name__)
            if self.call(getattr, attribute, "name") == target.name:
                if selected is not None:
                    raise refused("DUPLICATE_ATTRIBUTE")
                selected = attribute
        if selected is None:
            raise refused("ATTRIBUTE_DISAPPEARED")
        self.call(self.reader.catalog, selected, target.native_class)
        return selected


def _names(object_name: str, mesh_name: str, attribute_names: tuple[str, ...]) -> None:
    if type(attribute_names) is not tuple or not 1 <= len(attribute_names) <= MAX_SELECTED:
        raise refused("EXACT_SELECTED_ATTRIBUTE_NAMES_REQUIRED")
    for name in (object_name, mesh_name, *attribute_names):
        if type(name) is not str or not name or "\x00" in name:
            raise refused("EXACT_NATIVE_NAME_REQUIRED")
        try:
            size = len(name.encode("utf-8"))
        except UnicodeError:
            raise refused("EXACT_NATIVE_NAME_REQUIRED") from None
        if size > 63:
            raise refused("EXACT_NATIVE_NAME_REQUIRED")
    if len(set(attribute_names)) != len(attribute_names):
        raise refused("DUPLICATE_SELECTED_ATTRIBUTE")


def build_plan(bpy: Any, object_name: str, mesh_name: str, attribute_names: tuple[str, ...], *,
               origin: CaptureOrigin, available_memory_bytes: int, reserved_memory_bytes: int = 0) -> PreparationPlan:
    """Metadata plan; caller pure gate enforces a live base resource floor.

    available_memory_bytes is the initial scalar snapshot for this call's
    count-derived admission receipt, not a per-native-entry memory measurement.
    """
    # Bootstrap inline from immutable builtin tuple descriptors. A Python
    # helper/default must not execute before its own captured source is checked.
    raw_get, raw_type = ().__class__.__getitem__, ().__class__.__class__
    seal, native, dispatch = raw_get(origin, 0), raw_get(origin, 1), raw_get(origin, 2)
    if raw_type(origin) is not CaptureOrigin or raw_type(dispatch) is not raw_get(native, 16):
        raise raw_get(native, 18)
    found = False
    for fact in raw_get(seal, 2):
        if raw_get(fact, 0) is dispatch:
            if (dispatch.__code__ is not raw_get(fact, 1) or dispatch.__globals__ is not raw_get(fact, 2)
                    or dispatch.__defaults__ is not raw_get(fact, 3) or dispatch.__kwdefaults__ is not None
                    or dispatch.__closure__ is not None):
                raise raw_get(native, 18)
            found = True
    if not found:
        raise raw_get(native, 18)
    dispatch("VERIFY", seal, native)
    pure, full = partial(dispatch, "PURE", seal, native), partial(dispatch, "FULL", seal, native)
    _names(object_name, mesh_name, attribute_names)
    pure()
    if threading.current_thread() is not threading.main_thread():
        raise refused("BLENDER_MAIN_THREAD_REQUIRED")
    full()
    access = _Access(bpy, pure)
    metadata = access.snapshot(object_name, mesh_name)
    present = {row.name: row for row in metadata.attributes}
    targets = []
    for name in attribute_names:
        header = present.get(name)
        if header is None:
            action = "ABSENT_REFUSED"
        elif header.data_type not in {"BOOLEAN", "FLOAT2"}:
            action = "UNSUPPORTED_TYPE_REFUSED"
        else:
            action = "MATERIALIZE_SINGLE" if header.storage == "SINGLE" else "NOOP_ALREADY_ARRAY"
        targets.append(Target(name, header, action))
    targets = tuple(targets)
    resources = _resource_facts(targets, available_memory_bytes, reserved_memory_bytes)
    fingerprint = hashlib.sha256(_canonical([metadata.plain(), [(row.name, row.action) for row in targets]])).hexdigest()
    pure()
    return PreparationPlan(metadata, targets, fingerprint, tuple(resources.items()))


class PreparationJournal:
    @classmethod
    def for_plan(cls, plan: PreparationPlan) -> PreparationJournal:
        if type(plan) is not PreparationPlan:
            raise refused("PREPARATION_PLAN_REQUIRED")
        result = object.__new__(cls)
        cells = []
        for target in plan.targets:
            cell = dict.fromkeys(_ROW_BITS, False)
            cell.update(name=target.name, action=target.action, entry_kind=("FULL_SLICE_ZERO_DOMAIN" if target.header
                and target.header.count == 0 and target.action == "MATERIALIZE_SINGLE" else
                "FOREACH_GET" if target.action == "MATERIALIZE_SINGLE" else target.action),
                before_storage=None if target.header is None else target.header.storage,
                after_storage=None, readback_entries=0, readback_returns=0,
                logical_values_sha256=None, retained_physical_transition="NOT_ENTERED")
            cells.append(cell)
        result._cells = tuple(cells)
        result._views = tuple(MappingProxyType(cell) for cell in cells)
        result._plan = plan
        return result

    @property
    def rows(self) -> tuple:
        return self._views

    def receipt(self) -> dict:
        return {"rows": [dict(row) for row in self._cells], "inverse_attempted": False,
                "requires_fresh_image_preview": True, "project_saved": False}


@dataclass(frozen=True)
class PreparationResult:
    fingerprint: str
    rows: tuple
    resources: tuple
    values: Any

    def receipt(self) -> dict:
        converted = tuple(row for row in self.rows if row["materialize_entered"])
        return {"schema": "mesh_storage_preparation_result_v1",
                "status": "COMPLETE_PREPARED" if converted else "NOOP_COMPLETE",
                "preparation_fingerprint": self.fingerprint, "rows": [dict(row) for row in self.rows],
                "resource_facts": dict(self.resources), "source_equivalent_before_after": True,
                "independently_measured_SINGLE_pre_value_hash": False,
                "complete_post_ARRAY_values_verified": bool(converted) and all(row["verified"] for row in converted),
                "requires_fresh_image_preview": True,
                "post_value_verification_applies_to_materialized_rows_only": True,
                "untouched_ARRAY_selection_values_read": False,
                "project_saved": False, "inverse_attempted": False, "new_Main_IDs": False,
                "native_functional_qualified": False, "stage_B_registered": False}


def _bits(buffer: Any, header: AttributeHeader) -> tuple:
    if header.data_type == "BOOLEAN":
        values = tuple(buffer)
        if len(values) != header.count or any(type(value) is not bool for value in values):
            raise refused("BOOLEAN_BUFFER_SHAPE_OR_TYPE")
        return values
    values = tuple(buffer)
    if len(values) != 2 * header.count or any(type(value) is not float or not math.isfinite(value) for value in values):
        raise refused("FLOAT2_BUFFER_SHAPE_OR_FINITE")
    return tuple(tuple(struct.pack("<f", values[index + offset]).hex() for offset in (0, 1))
                 for index in range(0, len(values), 2))


def _buffers(header: AttributeHeader) -> tuple:
    if header.data_type == "BOOLEAN":
        output = memoryview(bytearray(header.count)).cast("?")
        readback = memoryview(bytearray(header.count)).cast("?")
        if output.format != "?" or output.itemsize != 1 or output.readonly:
            raise refused("BOOLEAN_BUFFER_FORMAT")
    else:
        output, readback = array("f", [0.]) * (2 * header.count), array("f", [0.]) * (2 * header.count)
        if output.itemsize != 4 or memoryview(output).format != "f":
            raise refused("FLOAT2_BUFFER_FORMAT")
    return output, readback


def prepare(bpy: Any, plan: PreparationPlan, *, bindings: CollectionBindings, origin: CaptureOrigin,
            available_memory_bytes: int, reserved_memory_bytes: int = 0,
            journal: PreparationJournal | None = None,
            _raw_get=object.__getattribute__) -> PreparationResult:
    """Prepare under caller pure-gate live resource checks at every boundary.

    Before entry the caller sets its numeric floor from the plan's required
    available memory. The scalar available_memory_bytes remains an initial
    argument snapshot; callback sampling is separate caller-owned evidence.
    """
    # This duplicates build_plan's deliberately inline entry bootstrap: calling
    # a mutable Python helper to check that helper would execute it too early.
    raw_get, raw_type = ().__class__.__getitem__, ().__class__.__class__
    seal, native, dispatch = raw_get(origin, 0), raw_get(origin, 1), raw_get(origin, 2)
    if raw_type(origin) is not CaptureOrigin or raw_type(dispatch) is not raw_get(native, 16):
        raise raw_get(native, 18)
    found = False
    for fact in raw_get(seal, 2):
        if raw_get(fact, 0) is dispatch:
            if (dispatch.__code__ is not raw_get(fact, 1) or dispatch.__globals__ is not raw_get(fact, 2)
                    or dispatch.__defaults__ is not raw_get(fact, 3) or dispatch.__kwdefaults__ is not None
                    or dispatch.__closure__ is not None):
                raise raw_get(native, 18)
            found = True
    if not found:
        raise raw_get(native, 18)
    dispatch("VERIFY", seal, native)
    pure, full = partial(dispatch, "PURE", seal, native), partial(dispatch, "FULL", seal, native)
    # The full ledger precedes clocks, native/factory entry and output buffers.
    if type(plan) is not PreparationPlan or type(bindings) is not CollectionBindings:
        raise refused("QUALIFIED_PREPARATION_INPUTS_REQUIRED")
    if journal is None:
        journal = PreparationJournal.for_plan(plan)
    if type(journal) is not PreparationJournal or _raw_get(journal, "_plan") is not plan:
        raise refused("PLAN_JOURNAL_MISMATCH")
    cells = _raw_get(journal, "_cells")
    fallback = BridgeError(ErrorCode.OPERATION_FAILED, "Mesh storage preparation did not complete.", {})
    fallback_context = fallback.context
    exception_dict = BaseException.__dict__["__dict__"].__get__
    clear_traceback = BaseException.__dict__["__traceback__"].__set__
    canonical_error, raw_type, raw_dict = BridgeError, type, dict
    exception_type = BaseException
    raw_keys, raw_getitem, raw_setitem = dict.keys, dict.get, dict.__setitem__
    raw_all, raw_str = all, str
    fallback_fields = exception_dict(fallback)
    # Allocate the clean fallback context and row aliases BEFORE buffers/native
    # calls. If error conversion itself exhausts memory, the caller's journal
    # still owns these exact monotonic plain cells. No foreign keys are copied.
    receipt = {"schema": "mesh_storage_preparation_partial_v1", "rows": list(cells),
               "requires_fresh_image_preview": True, "inverse_attempted": False,
               "project_saved": False, "physical_state_requires_reinspection": True,
               "verification_bits_record_past_observations": True,
               "after_storage_is_last_observed": True}
    fallback_context.update(reason="PREPARATION_NATIVE_OR_VERIFICATION_FAILURE",
                            mesh_storage_prepare=receipt, foreign_exception_context_refused=False)

    outputs, baselines, values = {}, {}, {}
    _attribute = data = None
    try:
        pure()
        if threading.current_thread() is not threading.main_thread():
            raise refused("BLENDER_MAIN_THREAD_REQUIRED")
        if any(row.action not in {"MATERIALIZE_SINGLE", "NOOP_ALREADY_ARRAY"} for row in plan.targets):
            raise refused("SELECTED_ABSENT_OR_UNSUPPORTED_ATTRIBUTE")
        resources = _resource_facts(plan.targets, available_memory_bytes, reserved_memory_bytes)
        full()
        bindings.verify()
        descriptors = dict(bindings.descriptors)
        foreach, full_slice = descriptors["foreach_get"], descriptors["__getitem__"]
        needs_full_slice = any(row.header.count == 0 and row.action == "MATERIALIZE_SINGLE" for row in plan.targets)
        if needs_full_slice and not bindings.zero_slice_qualified:
            raise refused("EMPTY_FULL_SLICE_NOT_QUALIFIED")
        # Argument construction must finish before the native entered fence.
        held_full_slice = slice(None, None, None) if needs_full_slice else None
        for index, target in enumerate(plan.targets):
            if target.action == "MATERIALIZE_SINGLE":
                outputs[index] = _buffers(target.header)
        expected = plan.metadata
        object_name, mesh_name = dict(expected.object_identity)["name"], dict(expected.mesh_identity)["name"]

        def snapshot(access):
            if access.database() != expected.database_identity:
                raise refused("PREPARATION_DATABASE_CHANGED")
            current = access.snapshot(object_name, mesh_name)
            if (current.obj is not expected.obj or current.mesh is not expected.mesh
                    or current.plain() != expected.plain()):
                raise refused("PREPARATION_FORWARD_METADATA_CAS_CHANGED")
            return current

        def collection(access, header):
            owner = access.attribute(expected.mesh, header)
            result = access.field(owner, header.native_class, "data")
            if type(result) is not bindings.collection_class:
                raise refused("COLLECTION_INSTANCE_CLASS_CHANGED")
            return owner, result

        def verify_baselines(access):
            # No permission/provider callback within this synchronous pass.
            # Fresh owners follow every other attribute's data access.
            snapshot(access)
            for completed, baseline in baselines.items():
                header = expected.attributes[next(i for i, row in enumerate(expected.attributes)
                    if row.name == plan.targets[completed].name)]
                owner, source = collection(access, header)
                buffer = outputs[completed][1]
                pure()
                bindings.verify()
                cells[completed]["readback_entries"] += 1
                foreach(source, "vector" if header.data_type == "FLOAT2" else "value", buffer)
                cells[completed]["readback_returns"] += 1
                pure()
                del source, owner
                if _bits(buffer, header) != baseline:
                    cells[completed]["baseline_conflict"] = True
                    raise refused("PREPARED_ARRAY_LOGICAL_BASELINE_CHANGED")
            snapshot(access)

        for index, target in enumerate(plan.targets):
            full()
            access = _Access(bpy, pure)
            verify_baselines(access)
            if target.action == "NOOP_ALREADY_ARRAY":
                cells[index]["after_storage_observed"] = True
                cells[index]["after_storage"] = "ARRAY"
                cells[index]["verified"] = True
                cells[index]["retained_physical_transition"] = "NOOP_ALREADY_ARRAY"
                continue
            header = target.header
            # Compute the only permitted metadata delta before entry.
            advanced = tuple(AttributeHeader(row.name, row.domain, row.data_type, row.native_class, row.value_class,
                "ARRAY" if row.name == header.name else row.storage, row.count, row.schema_sha256, row.value_schema_sha256)
                for row in expected.attributes)
            forward = _Metadata(expected.obj, expected.mesh, expected.object_identity, expected.mesh_identity,
                                expected.database_identity, expected.counts, expected.uv_roles, advanced)
            cells[index]["data_lookup_entered"] = True
            _attribute, data = collection(access, header)
            cells[index]["data_lookup_returned"] = True
            pure()
            bindings.verify()
            output = outputs[index][0]
            cells[index]["materialize_entered"] = True
            cells[index]["retained_physical_transition"] = "ENTERED_OUTCOME_UNKNOWN"
            if header.count == 0:
                empty = full_slice(data, held_full_slice)
                cells[index]["materialize_returned"] = True
                pure()
                if type(empty) is not list or empty:
                    raise refused("EMPTY_FULL_SLICE_RESULT")
                del empty
            else:
                foreach(data, "vector" if header.data_type == "FLOAT2" else "value", output)
                cells[index]["materialize_returned"] = True
                pure()
            _attribute = data = None
            expected = forward  # Precomputed advance, never an observed rebase.
            baseline = _bits(output, header)
            if baseline and any(value != baseline[0] for value in baseline):
                raise refused("SINGLE_EXPANSION_NOT_REPEATED_BITS")
            baselines[index] = baseline
            full()
            access = _Access(bpy, pure)
            verify_baselines(access)
            cells[index]["after_storage_observed"] = True
            cells[index]["after_storage"] = "ARRAY"
            cells[index]["logical_values_sha256"] = hashlib.sha256(_canonical(baseline)).hexdigest()
            cells[index]["verified"] = True
            cells[index]["retained_physical_transition"] = "OBSERVED_SINGLE_TO_ARRAY"
            values[header.name] = baseline
        full()
        access = _Access(bpy, pure)
        verify_baselines(access)
        pure()
        return PreparationResult(plan.fingerprint, tuple(MappingProxyType(dict(row)) for row in cells),
                                 tuple(resources.items()), MappingProxyType(values))
    except exception_type as error:
        _attribute = data = None
        if raw_type(error) is canonical_error:
            fields = exception_dict(error)
            if raw_type(fields) is raw_dict and raw_all(raw_type(key) is raw_str for key in raw_keys(fields)):
                code = raw_getitem(fields, "code")
                if raw_type(code) is raw_str:
                    raw_setitem(fallback_fields, "code", code)
                context = raw_getitem(fields, "context")
                if raw_type(context) is raw_dict and raw_all(raw_type(key) is raw_str for key in raw_keys(context)):
                    reason = raw_getitem(context, "reason")
                    if raw_type(reason) is raw_str:
                        raw_setitem(fallback_context, "reason", reason)
                else:
                    raw_setitem(fallback_context, "foreign_exception_context_refused", True)
            else:
                raw_setitem(fallback_context, "foreign_exception_context_refused", True)
        clear_traceback(error, None)
        raise fallback from None
