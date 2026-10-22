"""Bounded Mesh projections for the initial rigid authored-data profile.

The caller supplies its independently proven Mesh/consumer inventory. This
module neither discovers every consumer nor proves complete Main preservation.
Admission of the entire inventory precedes generic RNA value reads. Only ID
identities enter comparisons; geometry, attributes and UV children are structural.
These comparison records are not recovery backups.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..errors import BridgeError, ErrorCode
from . import _rigid_evaluation_scope as native
from . import _rigid_snapshot_scope as descriptors

MAX_MESHES, MAX_CONSUMERS = 64, 256
MAX_STRUCTURE, MAX_ATTRIBUTE_COMPONENTS = 131072, 262144
MAX_COMPONENTS, MAX_CUSTOM_COMPONENTS = 2097152, 4096
MAX_STRING, MAX_UV_LAYERS, MAX_ENUM_FLAGS = 1024, 8, 128
SCALARS = frozenset({"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"})
WIDTHS = {"FLOAT": 1, "INT": 1, "FLOAT_VECTOR": 3, "FLOAT_COLOR": 4,
          "BYTE_COLOR": 4, "STRING": MAX_STRING, "BOOLEAN": 1, "INT8": 1,
          "FLOAT2": 2, "INT32_2D": 2, "INT16_2D": 2}
UV_BUFFERS = {"data": "MeshUVLoop", "uv": "Float2AttributeValue",
              "pin": "BoolAttributeValue", "vertex_selection": "BoolAttributeValue",
              "edge_selection": "BoolAttributeValue"}


def _unsupported(message: str) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, message, {"mesh_authored_scope_complete": False})


@dataclass
class _Budget:
    counts: dict[str, int] = field(default_factory=lambda: {
        "structure": 0, "attribute_components": 0, "payload_components": 0,
        "custom_components": 0, "memberships": 0, "uv_records": 0})

    def add(self, kind: str, count: int, maximum: int) -> None:
        self.counts[kind] += count
        if self.counts[kind] > maximum:
            raise _unsupported(f"Aggregate rigid Mesh {kind} exceeds {maximum} components.")

    def payload(self, count: int) -> None:
        self.add("payload_components", count, MAX_COMPONENTS)


def _token(bpy: Any, owner: Any, classes: frozenset[str] | None = None) -> tuple[int, int]:
    rna = owner.bl_rna
    native._native(bpy, owner, classes or frozenset({rna.identifier}))
    descriptors._fields(rna, (("session_uid", "INT"),))
    # Requiring the native ID descriptor excludes transient RNA-array elements.
    base = rna
    for _ in range(16):
        if base.identifier == "ID":
            break
        base = base.base
        if base is None:
            raise _unsupported("Rigid Mesh bindings require native ID data blocks.")
    else:
        raise _unsupported("Rigid Mesh ID inheritance is outside the reviewed bound.")
    return int(owner.as_pointer()), int(native._read(owner, rna, "session_uid", "INT"))


def _plain(raw: Any, depth: int = 0) -> Any:
    if depth > 8:
        raise _unsupported("Rigid Mesh property arrays exceed eight levels.")
    if raw is None or type(raw) in {bool, int}:
        if type(raw) is int and raw.bit_length() > 4096:
            raise _unsupported("Rigid Mesh integer evidence exceeds 4096 bits.")
        return raw
    if type(raw) is float:
        if not math.isfinite(raw):
            raise _unsupported("Rigid Mesh evidence contains a nonfinite value.")
        return raw
    if type(raw) in {str, bytes}:
        if len(raw) > MAX_STRING:
            raise _unsupported("Rigid Mesh string evidence exceeds 1024 components.")
        return ("BYTES", tuple(raw)) if type(raw) is bytes else raw
    if hasattr(raw, "as_pointer"):
        raise _unsupported("Unexpected native child pointer in a structural Mesh payload.")
    return tuple(_plain(item, depth + 1) for item in native._bounded(raw, 256, "Mesh scalar array"))


def _custom(owner: Any, budget: _Budget) -> Any:
    def key(name: Any) -> str:
        if type(name) is not str:
            raise _unsupported("Mesh raw custom-property keys must be bounded strings.")
        _plain(name)
        budget.add("custom_components", len(name), MAX_CUSTOM_COMPONENTS)
        budget.payload(len(name))
        return name

    def read(raw: Any, depth: int = 0) -> Any:
        if depth > 4:
            raise _unsupported("Rigid Mesh raw custom properties exceed four levels.")
        width = len(raw) if type(raw) in {str, bytes} else 1
        budget.add("custom_components", width, MAX_CUSTOM_COMPONENTS)
        budget.payload(width)
        if raw is None or type(raw) in {bool, int, float, str, bytes}:
            checked = _plain(raw)
            # Python equality conflates False/0/0.0 and signed zero. Keep the
            # exposed custom scalar type and the exact finite float spelling.
            return type(raw).__name__, raw.hex() if type(raw) is float else checked
        if hasattr(raw, "as_pointer"):
            raise _unsupported("Native ID aliases in Mesh custom properties need a separate consumer proof.")
        if type(raw) in {set, frozenset}:
            raise _unsupported("Mesh raw custom-property sets have no native IDProperty representation.")
        if hasattr(raw, "keys"):
            names = native._bounded(raw.keys(), 128, "Mesh custom fields")
            return tuple((key(name), read(raw[name], depth + 1)) for name in sorted(names))
        return tuple(read(item, depth + 1) for item in native._bounded(raw, 256, "Mesh custom array"))

    names = native._bounded(owner.keys(), 128, "Mesh raw custom properties")
    return tuple((key(name), read(owner[name])) for name in sorted(names))


@dataclass
class _Field:
    name: str
    kind: str
    width: int
    enum_flags: bool


@dataclass
class _Plan:
    owner: Any
    rna: Any
    fields: tuple[_Field, ...]
    pointers: tuple[tuple[str, Any], ...]


def _structural_index(value: Any, items: Any) -> int | None:
    if value is None:
        return None
    indices = [index for index, owner in enumerate(items) if owner == value]
    if len(indices) != 1:
        raise _unsupported("A structural Mesh selector is outside its admitted child inventory.")
    return indices[0]


def _plan(bpy: Any, owner: Any, classes: frozenset[str], budget: _Budget,
          *, exclude: frozenset[str] = frozenset(), rna: Any = None,
          structural: dict[str, Any] | None = None) -> _Plan:
    rna = descriptors._checked(bpy, owner, classes) if rna is None else rna
    fields, pointers = [], []
    for prop in native._bounded(rna.properties, 256, "Mesh authored descriptors"):
        if prop.is_readonly or prop.identifier in exclude:
            continue
        if prop.is_runtime or prop.type not in SCALARS | {"POINTER"}:
            raise _unsupported("Rigid Mesh projection contains an unreviewed writable RNA field.")
        if prop.type == "POINTER":
            value = native._read(owner, rna, prop.identifier, "POINTER")
            projected = (("STRUCTURAL_INDEX", _structural_index(value, structural[prop.identifier]))
                         if structural is not None and prop.identifier in structural
                         else None if value is None else _token(bpy, value))
            pointers.append((prop.identifier, projected))
            budget.payload(2)
            continue
        enum_flags = prop.type == "ENUM" and bool(getattr(prop, "is_enum_flag", False))
        # Only native numeric descriptor subclasses expose array metadata.
        # StringProperty and EnumProperty are scalars without is_array.
        is_array = prop.type in {"BOOLEAN", "INT", "FLOAT"} and prop.is_array
        width = prop.array_length if is_array else 0
        if is_array and not 0 < width <= 256:
            raise _unsupported("Rigid Mesh writable arrays need a fixed reviewed component count.")
        if width and prop.type not in {"BOOLEAN", "INT", "FLOAT"}:
            raise _unsupported("Mesh authored arrays require reviewed native numeric scalar types.")
        reserved = width or 1
        if enum_flags:
            reserved = MAX_ENUM_FLAGS * MAX_STRING
        elif prop.type in {"STRING", "ENUM"}:
            reserved = MAX_STRING
        budget.payload(reserved)
        fields.append(_Field(prop.identifier, prop.type, width, enum_flags))
    return _Plan(owner, rna, tuple(fields), tuple(pointers))


def _project(plan: _Plan) -> Any:
    def scalar(raw: Any, kind: str) -> Any:
        expected = {"BOOLEAN": {bool}, "INT": {int}, "FLOAT": {int, float},
                    "STRING": {str, bytes}, "ENUM": {str}}[kind]
        if type(raw) not in expected:
            raise _unsupported("A Mesh scalar value disagrees with its admitted native descriptor.")
        return _plain(raw)

    def read(field_: _Field) -> Any:
        raw = getattr(plan.owner, field_.name)
        if field_.enum_flags:
            if type(raw) not in {set, frozenset} or len(raw) > MAX_ENUM_FLAGS:
                raise _unsupported("Mesh enum-flag values exceed their admitted set representation.")
            return tuple(sorted(scalar(item, "ENUM") for item in raw))
        if field_.width:
            values = native._bounded(raw, field_.width, "fixed Mesh scalar array")
            if len(values) != field_.width:
                raise _unsupported("Mesh array length disagrees with its reserved descriptor component count.")
            return tuple(scalar(item, field_.kind) for item in values)
        return scalar(raw, field_.kind)

    return (tuple((field_.name, read(field_)) for field_ in plan.fields), plan.pointers)


def _items(owner: Any, rna: Any, name: str, maximum: int) -> list[Any]:
    return native._bounded(native._read(owner, rna, name, "COLLECTION"), maximum, "Mesh " + name)


def _wrapper(bpy: Any, mesh_rna: Any, name: str, kind: str) -> Any:
    prop = mesh_rna.properties.get(name)
    wrapper = getattr(bpy.types, kind, None)
    if (prop is None or prop.type != "COLLECTION" or prop.is_runtime or wrapper is None
            or getattr(prop, "srna", None) != wrapper.bl_rna):
        raise _unsupported(f"Mesh {name} has no proven canonical {kind} wrapper metadata.")
    return wrapper.bl_rna


def _attribute_selectors(bpy: Any, mesh: Any, rna: Any, attributes: Any, budget: _Budget) -> Any:
    records = []
    for name in ("attributes", "color_attributes"):
        wrapper_rna = _wrapper(bpy, rna, name, "AttributeGroupMesh")
        container = native._read(mesh, rna, name, "COLLECTION")
        members = _items(mesh, rna, name, 128)
        indices = tuple(_structural_index(item, attributes) for item in members)
        roles = []
        for field_ in ("active", "active_color"):
            descriptors._fields(wrapper_rna, ((field_, "POINTER"),))
            roles.append((field_, _structural_index(native._read(container, wrapper_rna, field_, "POINTER"), attributes)))
        plan = _plan(bpy, container, frozenset(), budget, rna=wrapper_rna,
                     exclude=frozenset({"active", "active_color"}))
        budget.payload(len(indices) + len(roles))
        records.append((name, indices, tuple(roles), plan))
    return tuple(records)


def _uv(bpy: Any, mesh: Any, mesh_rna: Any, budget: _Budget) -> Any:
    wrapper_rna = _wrapper(bpy, mesh_rna, "uv_layers", "UVLoopLayers")
    layers = _items(mesh, mesh_rna, "uv_layers", MAX_UV_LAYERS)
    container = native._read(mesh, mesh_rna, "uv_layers", "COLLECTION")
    descriptors._fields(wrapper_rna, (("active", "POINTER"), ("active_index", "INT")))
    budget.payload(2)
    # The wrapper has no owner.bl_rna. Its canonical schema comes from the
    # already canonical Mesh property's srna, not the entry fixed_type.
    selectors = _plan(bpy, container, frozenset(), budget, rna=wrapper_rna,
                      exclude=frozenset({"active"}), structural={"active_render": layers})
    records = []
    for layer in layers:
        rna = descriptors._checked(bpy, layer, frozenset({"MeshUVLoopLayer"}))
        descriptors._fields(rna, (("name", "STRING"), ("active", "BOOLEAN"),
                                 ("active_render", "BOOLEAN"), ("active_clone", "BOOLEAN")))
        budget.payload(MAX_STRING + 3)
        plan = _plan(bpy, layer, frozenset({"MeshUVLoopLayer"}), budget)
        buffers = []
        for field_ in native._bounded(rna.properties, 256, "UV layer descriptors"):
            if field_.type != "COLLECTION":
                continue
            kind = UV_BUFFERS.get(field_.identifier)
            canonical = getattr(bpy.types, kind, None) if kind else None
            if (canonical is None or field_.is_runtime
                    or field_.fixed_type != canonical.bl_rna):
                raise _unsupported("UV storage needs reviewed native value metadata.")
            values = _items(layer, rna, field_.identifier, MAX_STRUCTURE - budget.counts["uv_records"])
            budget.add("uv_records", len(values), MAX_STRUCTURE)
            buffers.append((field_.identifier, tuple(_plan(bpy, item, frozenset({kind}), budget) for item in values)))
        records.append((layer, plan, tuple(buffers)))
    return container, wrapper_rna, selectors, tuple(records)


def _mesh(bpy: Any, mesh: Any, budget: _Budget) -> Any:
    rna = descriptors._checked(bpy, mesh, frozenset({"Mesh"}))
    descriptors._fields(rna, (("has_custom_normals", "BOOLEAN"), ("shape_keys", "POINTER")))
    if native._read(mesh, rna, "has_custom_normals", "BOOLEAN"):
        raise _unsupported("Custom split normals require a separately proven preservation projection.")
    if native._read(mesh, rna, "shape_keys", "POINTER") is not None:
        raise _unsupported("Shape keys are outside the initial rigid Mesh authored profile.")
    uv = _uv(bpy, mesh, rna, budget)
    uv_layers = tuple(owner for owner, _, _ in uv[3])
    plan = _plan(bpy, mesh, frozenset({"Mesh"}), budget,
                 structural={"uv_layer_clone": uv_layers, "uv_layer_stencil": uv_layers})
    materials = tuple(None if material is None else _token(bpy, material, frozenset({"Material"}))
                      for material in _items(mesh, rna, "materials", 128))
    budget.payload(2 * len(materials))
    geometry = []
    for field_, kind in (("vertices", "MeshVertex"), ("edges", "MeshEdge"),
                         ("loops", "MeshLoop"), ("polygons", "MeshPolygon")):
        records = _items(mesh, rna, field_, MAX_STRUCTURE - budget.counts["structure"])
        budget.add("structure", len(records), MAX_STRUCTURE)
        prepared = []
        for record in records:
            # MeshPolygon.vertices is a native dynamic array whose descriptor
            # array_length is the default triangle width, even for quads/ngons.
            # Its bounded measured topology is captured in direct below.
            child = _plan(bpy, record, frozenset({kind}), budget,
                          exclude=frozenset({"vertices"}) if field_ == "polygons" else frozenset())
            direct, groups = (), ()
            if field_ == "vertices":
                memberships = _items(record, child.rna, "groups", MAX_STRUCTURE - budget.counts["memberships"])
                budget.add("memberships", len(memberships), MAX_STRUCTURE)
                groups = tuple(_plan(bpy, item, frozenset({"VertexGroupElement"}), budget) for item in memberships)
                for group in groups:
                    descriptors._fields(group.rna, (("group", "INT"), ("weight", "FLOAT")))
                    budget.payload(2)
            else:
                fields = (("vertex_index", "INT"), ("edge_index", "INT")) if field_ == "loops" else (("vertices", "INT"),)
                if field_ == "polygons":
                    fields += (("loop_start", "INT"), ("loop_total", "INT"))
                descriptors._fields(child.rna, fields)
                direct = tuple((name, _plain(native._read(record, child.rna, name, kind_))) for name, kind_ in fields)
                budget.payload(sum(len(value) if isinstance(value, tuple) else 1 for _, value in direct))
            prepared.append((child, direct, groups))
        geometry.append((field_, tuple(prepared)))
    attributes = []
    attribute_owners = _items(mesh, rna, "attributes", 128)
    attribute_selectors = _attribute_selectors(bpy, mesh, rna, attribute_owners, budget)
    for attribute in attribute_owners:
        attr_rna = descriptors._checked(bpy, attribute, descriptors.ATTRIBUTE_CLASSES)
        data_type = native._read(attribute, attr_rna, "data_type", "ENUM")
        expected = descriptors.ATTRIBUTES.get(data_type)
        if expected is None or attr_rna.identifier != expected[0]:
            raise _unsupported("Mesh attribute type has no reviewed native value class.")
        remaining = (MAX_ATTRIBUTE_COMPONENTS - budget.counts["attribute_components"]) // WIDTHS[data_type]
        values = _items(attribute, attr_rna, "data", remaining)
        budget.add("attribute_components", len(values) * WIDTHS[data_type], MAX_ATTRIBUTE_COMPONENTS)
        metadata = tuple((name, _plain(native._read(attribute, attr_rna, name, kind)))
                         for name, kind in (("name", "STRING"), ("domain", "ENUM"), ("data_type", "ENUM")))
        budget.payload(sum(len(value) for _, value in metadata))
        attributes.append((metadata, _plan(bpy, attribute, descriptors.ATTRIBUTE_CLASSES, budget),
                           tuple(_plan(bpy, item, frozenset({expected[1]}), budget) for item in values)))
    return plan, _custom(mesh, budget), tuple(geometry), tuple(attributes), uv, materials, attribute_selectors


def _mesh_state(prepared: Any) -> Any:
    plan, custom, geometry, attributes, uv, materials, attribute_selectors = prepared
    container, wrapper_rna, selectors, layers = uv
    active = native._read(container, wrapper_rna, "active", "POINTER")
    indices = [index for index, (owner, _, _) in enumerate(layers) if owner == active]
    if active is not None and len(indices) != 1:
        raise _unsupported("Active UV layer is outside the admitted structural layer inventory.")
    active_index = native._read(container, wrapper_rna, "active_index", "INT")
    if (active is not None and active_index != indices[0]) or (active is None and layers):
        raise _unsupported("UV active pointer and structural selector index disagree.")
    uv_state = (_project(selectors), None if active is None else indices[0],
                tuple((tuple((name, _plain(native._read(owner, layer.rna, name, kind)))
                             for name, kind in (("name", "STRING"), ("active", "BOOLEAN"),
                                                ("active_render", "BOOLEAN"), ("active_clone", "BOOLEAN"))),
                       _project(layer), tuple((name, tuple(_project(item) for item in values))
                     for name, values in buffers)) for owner, layer, buffers in layers))
    return (("rna", _project(plan)), ("custom", custom), ("custom_normals", False),
            ("geometry", tuple((name, tuple((_project(item), direct,
                tuple((_project(group), native._read(group.owner, group.rna, "group", "INT"),
                       native._read(group.owner, group.rna, "weight", "FLOAT")) for group in groups))
                for item, direct, groups in records)) for name, records in geometry)),
            ("attributes", tuple((metadata, _project(attr), tuple(_project(item) for item in values))
                                 for metadata, attr, values in attributes)),
            ("attribute_selectors", tuple((name, indices, roles, _project(plan_))
                                          for name, indices, roles, plan_ in attribute_selectors)),
            ("material_bindings", materials), ("uv", uv_state))


def snapshot_meshes(bpy: Any, meshes: tuple[Any, ...], consumers: tuple[Any, ...]) -> tuple[Any, ...]:
    """Capture supplied Meshes once and bind every supplied consumer by ID.

    Shared and unused Mesh IDs are admitted. Foreign consumer data is refused.
    Input closure, non-Mesh dependencies, permissions and recovery belong to the
    caller. Every invocation repeats full admission; no preflight ticket survives
    a checkpoint or external callback.
    """
    budget, prepared, bindings = _Budget(), {}, {}
    for mesh in native._bounded(meshes, MAX_MESHES, "admitted Mesh IDs"):
        token = _token(bpy, mesh, frozenset({"Mesh"}))
        if token not in prepared:
            budget.payload(2)
            prepared[token] = _mesh(bpy, mesh, budget)
    for obj in native._bounded(consumers, MAX_CONSUMERS, "Mesh consumers"):
        rna = descriptors._checked(bpy, obj, frozenset({"Object"}))
        descriptors._fields(rna, (("type", "ENUM"), ("data", "POINTER")))
        if native._read(obj, rna, "type", "ENUM") != "MESH":
            raise _unsupported("The Mesh authored inventory accepts only Mesh Object consumers.")
        token = _token(bpy, obj, frozenset({"Object"}))
        data = native._read(obj, rna, "data", "POINTER")
        data_token = _token(bpy, data, frozenset({"Mesh"})) if data is not None else None
        if data_token not in prepared:
            raise _unsupported("A Mesh consumer refers to data outside the admitted Mesh inventory.")
        if token not in bindings:
            budget.payload(4)
            bindings[token] = data_token
    # Generic reads start only after every Mesh, nested record and consumer has
    # passed descriptor admission and the aggregate budget has been reserved.
    return (("mesh_states", tuple((token, _mesh_state(value)) for token, value in sorted(prepared.items()))),
            ("consumer_bindings", tuple(sorted(bindings.items()))),
            ("aggregate_counts", tuple(sorted({**budget.counts, "meshes": len(prepared), "consumers": len(bindings)}.items()))))
