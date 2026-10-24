"""Descriptor-only preflight for the rigid scope's generic RNA projections.

The shared object/animation snapshot readers intentionally support other domains.
Before calling them here, close their complete static Mesh traversal and refuse
runtime properties without evaluating their getters. This is not a host sandbox.
"""

from __future__ import annotations

from typing import Any

from ..errors import BridgeError, ErrorCode
from . import _rigid_evaluation_scope as native

MAX_STRUCTURE = 131072
MAX_ATTRIBUTE_VALUES = 262144
ATTRIBUTES = {
    "FLOAT": ("FloatAttribute", "FloatAttributeValue"),
    "INT": ("IntAttribute", "IntAttributeValue"),
    "FLOAT_VECTOR": ("FloatVectorAttribute", "FloatVectorAttributeValue"),
    "FLOAT_COLOR": ("FloatColorAttribute", "FloatColorAttributeValue"),
    "BYTE_COLOR": ("ByteColorAttribute", "ByteColorAttributeValue"),
    "STRING": ("StringAttribute", "StringAttributeValue"),
    "BOOLEAN": ("BoolAttribute", "BoolAttributeValue"),
    "INT8": ("ByteIntAttribute", "ByteIntAttributeValue"),
    "FLOAT2": ("Float2Attribute", "Float2AttributeValue"),
    "INT32_2D": ("Int2Attribute", "Int2AttributeValue"),
    "INT16_2D": ("Short2Attribute", "Short2AttributeValue"),
}
ATTRIBUTE_CLASSES = frozenset(pair[0] for pair in ATTRIBUTES.values())
# Bundled bone-selection-set UI state is irrelevant to independent Mesh bodies.
# The field is excluded from the later generic Object reader, never resolved.
IGNORED_OBJECT_RUNTIME = frozenset({"active_selection_set"})


def _unsupported(message: str) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, message, {"evaluation_scope_complete": False})


def _checked(bpy: Any, owner: Any, classes: frozenset[str]) -> Any:
    """Inspect every descriptor before any generic reader can resolve a field."""
    rna = native._native(bpy, owner, classes)
    for prop in native._bounded(rna.properties, 256, "snapshot RNA descriptors"):
        if not prop.is_readonly and prop.is_runtime:
            if (rna.identifier == "Object" and prop.identifier in IGNORED_OBJECT_RUNTIME
                    and prop.type == "INT" and not prop.is_array and not prop.is_registered
                    and not prop.is_registered_optional and prop.default == 0
                    and prop.identifier not in native._bounded(owner.keys(), 128, "raw Object properties")):
                continue
            raise _unsupported(
                f"Rigid-body snapshot refuses writable runtime RNA property '{rna.identifier}.{prop.identifier}' before invoking its getter."
            )
    return rna


def _items(owner: Any, rna: Any, field: str, maximum: int) -> list[Any]:
    return native._bounded(native._read(owner, rna, field, "COLLECTION"), maximum, "snapshot " + field)


def _fields(rna: Any, fields: tuple[tuple[str, str], ...]) -> None:
    """Also close explicit readonly/direct reads outside generic rna_state."""
    for name, kind in fields:
        prop = rna.properties.get(name)
        if prop is None or prop.type != kind or prop.is_runtime:
            raise _unsupported(f"Direct snapshot field '{rna.identifier}.{name}' has no reviewed native descriptor.")


def _mesh(bpy: Any, mesh: Any) -> None:
    rna = _checked(bpy, mesh, frozenset({"Mesh"}))
    _fields(rna, (("session_uid", "INT"), ("users", "INT"), ("library", "POINTER"),
                  ("override_library", "POINTER"), ("is_editable", "BOOLEAN")))
    if native._read(mesh, rna, "shape_keys", "POINTER") is not None:
        raise _unsupported("Rigid-body snapshots require Mesh data without shape keys.")
    count = 0
    for field, kind in (("vertices", "MeshVertex"), ("edges", "MeshEdge"),
                        ("loops", "MeshLoop"), ("polygons", "MeshPolygon")):
        records = _items(mesh, rna, field, MAX_STRUCTURE - count)
        count += len(records)
        for record in records:
            record_rna = _checked(bpy, record, frozenset({kind}))
            if field == "vertices":
                for membership in _items(record, record_rna, "groups", 256):
                    member_rna = _checked(bpy, membership, frozenset({"VertexGroupElement"}))
                    for name, expected in (("group", "INT"), ("weight", "FLOAT")):
                        native._read(membership, member_rna, name, expected)
            elif field in {"edges", "polygons"}:
                native._read(record, record_rna, "vertices", "INT")
            elif field == "loops":
                native._read(record, record_rna, "vertex_index", "INT")
                native._read(record, record_rna, "edge_index", "INT")
    total = 0
    for attribute in _items(mesh, rna, "attributes", 128):
        attribute_rna = _checked(bpy, attribute, ATTRIBUTE_CLASSES)
        data_type = native._read(attribute, attribute_rna, "data_type", "ENUM")
        expected = ATTRIBUTES.get(data_type)
        if expected is None or attribute_rna.identifier != expected[0]:
            raise _unsupported("Rigid-body attribute data has no reviewed native value class.")
        native._read(attribute, attribute_rna, "name", "STRING")
        native._read(attribute, attribute_rna, "domain", "ENUM")
        records = _items(attribute, attribute_rna, "data", MAX_ATTRIBUTE_VALUES-total)
        total += len(records)
        for record in records:
            _checked(bpy, record, frozenset({expected[1]}))
    # The generic reader records Material identities only. Validate the native
    # binding collection itself without resolving any Material custom properties.
    _items(mesh, rna, "materials", 128)


def preflight(bpy: Any, scene: Any, bodies: tuple[Any, ...]) -> None:
    """Close every generic rna_state/object_state owner before the first read.

    All traversal properties are native, descriptor checked and independently
    bounded. The generic projection is called only after this entire pass, so a
    runtime getter on a late nested record cannot mutate an earlier comparison.
    This pass repeats on every scope capture, including after live providers.
    """
    scene_rna = native._native(bpy, scene, frozenset({"Scene"}))
    world = native._read(scene, scene_rna, "rigidbody_world", "POINTER")
    world_rna = _checked(bpy, world, frozenset({"RigidBodyWorld"}))
    units = native._read(scene, scene_rna, "unit_settings", "POINTER")
    _checked(bpy, units, frozenset({"UnitSettings"}))
    weights = native._read(world, world_rna, "effector_weights", "POINTER")
    _checked(bpy, weights, frozenset({"EffectorWeights"}))
    for field in ("collection", "constraints"):
        collection = native._read(world, world_rna, field, "POINTER")
        if collection is None:
            raise _unsupported("Rigid-body snapshot requires explicit native body and constraint collections.")
        _checked(bpy, collection, frozenset({"Collection"}))
    for obj in bodies:
        rna = _checked(bpy, obj, frozenset({"Object"}))
        _fields(rna, (("name", "STRING"), ("session_uid", "INT"),
            ("location", "FLOAT"), ("rotation_mode", "ENUM"), ("rotation_euler", "FLOAT"),
            ("rotation_quaternion", "FLOAT"), ("rotation_axis_angle", "FLOAT"), ("scale", "FLOAT"),
            ("delta_location", "FLOAT"), ("delta_rotation_euler", "FLOAT"),
            ("delta_rotation_quaternion", "FLOAT"), ("delta_scale", "FLOAT"),
            ("matrix_parent_inverse", "FLOAT")))
        if native._read(obj, rna, "type", "ENUM") != "MESH":
            raise _unsupported("Rigid-body generic snapshots require native Mesh objects.")
        if (native._read(obj, rna, "animation_data", "POINTER") is not None
                or native._read(obj, rna, "pose", "POINTER") is not None
                or _items(obj, rna, "modifiers", 100) or _items(obj, rna, "constraints", 100)):
            raise _unsupported("Rigid-body snapshots require static objects without pose, animation, modifiers or constraints.")
        body = native._read(obj, rna, "rigid_body", "POINTER")
        _checked(bpy, body, frozenset({"RigidBodyObject"}))
        _mesh(bpy, native._read(obj, rna, "data", "POINTER"))
        for group in _items(obj, rna, "vertex_groups", 256):
            _checked(bpy, group, frozenset({"VertexGroup"}))
        for slot in _items(obj, rna, "material_slots", 128):
            slot_rna = _checked(bpy, slot, frozenset({"MaterialSlot"}))
            native._read(slot, slot_rna, "link", "ENUM")
            native._read(slot, slot_rna, "material", "POINTER")
