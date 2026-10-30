"""Source-pinned, bounded static cloth memory scope.

No generic RNA snapshot, property-default probe, runtime value getter, frame
evaluation or context preparation is used here. The two source-reviewed Object
field getters wrap ob->pd; RNA_pointer_create_with_parent returns null for null
data, and FieldSettings has no refine callback. A non-null field is refused.
This statement applies only to BUILDS, not to arbitrary Blender versions.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass, replace
from inspect import getattr_static
from types import GetSetDescriptorType, MemberDescriptorType, MethodDescriptorType
from typing import Any, NamedTuple

from ..checkpoints import MARKER_KEY
from ..entry_effects import mark_view_layer_sync_possible
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..utils import int_param, reject_unknown_params
from . import _cloth_scene_consumers as roles
from . import _rigid_evaluation_scope as dependencies
from . import _simulation_runtime as runtime

PROFILE = "STATIC_CLOTH_MEMORY_V1"
MAX_VERTICES, MAX_FRAMES, MAX_OBJECTS = 256, 16, 16
MAX_VERTEX_GROUPS = 32
PERMITTED_ACTIONS = frozenset({"BAKE", "INVALIDATE", "FREE"})
FIELDS = frozenset({"object_name", "scene_name", "frame_start", "frame_end", "action"})
PREPARE_FIELDS = frozenset({"object_name", "scene_name", "home_scene_name", "workspace_name",
    "home_empty_name", "target_empty_name", "expected_home_active_object_name",
    "expected_target_active_object_name", "time_limit_seconds"})
PRIMITIVES = frozenset({"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"})
ATTRIBUTE_VALUES = {
    "FLOAT": ("FloatAttribute", "FloatAttributeValue"), "INT": ("IntAttribute", "IntAttributeValue"),
    "FLOAT_VECTOR": ("FloatVectorAttribute", "FloatVectorAttributeValue"),
    "FLOAT_COLOR": ("FloatColorAttribute", "FloatColorAttributeValue"),
    "BYTE_COLOR": ("ByteColorAttribute", "ByteColorAttributeValue"),
    "STRING": ("StringAttribute", "StringAttributeValue"), "BOOLEAN": ("BoolAttribute", "BoolAttributeValue"),
    "INT8": ("ByteIntAttribute", "ByteIntAttributeValue"), "FLOAT2": ("Float2Attribute", "Float2AttributeValue"),
    "INT32_2D": ("Int2Attribute", "Int2AttributeValue"), "INT16_2D": ("Short2Attribute", "Short2AttributeValue"),
}


def refuse(reason: str, **facts: Any) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, "The bounded cloth memory profile is not satisfied.",
                       {"reason": reason, "scope_complete": False, "verification_required": True, **facts})


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def observation_limits(bpy: Any) -> dict:
    build = runtime.profile(bpy)
    return {"mesh_observation_scope": "LOGICAL_AUTHORED_VALUES_GROUP_MEMBERSHIPS_GENERIC_ATTRIBUTE_INVENTORY",
        "native_legacy_deform_layer_creation": "KNOWN_POSSIBLE_ON_4_5_EMPTY_GROUPS_READ" if build[1] == (4, 5, 14) else "NOT_ASSESSED",
        "native_legacy_deform_layout_preservation": "NOT_ASSESSED",
        "native_layer_record_pointer_preservation": "NOT_ASSESSED", "hidden_main_passivity": "NOT_ASSESSED"}


def bounded(items: Any, maximum: int, *, field: str = "collection", owner_type: str | None = None) -> tuple:
    for label in ((field,) if owner_type is None else (field, owner_type)):
        if type(label) is not str or not label or len(label) > 128 or "\x00" in label:
            raise refuse("CLOTH_DIAGNOSTIC_LABEL_INVALID")
    size = len(items)
    if type(size) is not int or not 0 <= size <= maximum:
        raise refuse("CLOTH_COLLECTION_BUDGET", field=field, observed_count=size, maximum_count=maximum,
                     **({"owner_type": owner_type} if owner_type is not None else {}))
    result = tuple(items)
    observed = len(result)
    if observed != size:
        raise refuse("CLOTH_COLLECTION_CHANGED", field=field, expected_count=size, observed_count=observed,
                     maximum_count=maximum, **({"owner_type": owner_type} if owner_type is not None else {}))
    return result


def name(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or not value or "\x00" in value:
        raise invalid_argument(field + " must name one existing native data block.")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError as cause:
        raise invalid_argument(field + " must be valid UTF-8.") from cause
    if length > 63:
        raise invalid_argument(field + " exceeds the 63-byte native name limit.")
    return value


def time_limit(params: Any) -> float:
    value = params.get("time_limit_seconds", 60.)
    if type(value) not in {float, int} or not math.isfinite(value) or not 1. <= value <= 300.:
        raise invalid_argument("time_limit_seconds must be between 1 and 300 seconds.")
    return float(value)


def proposal(params: Any, *, starting: bool = False) -> dict:
    reject_unknown_params(params, FIELDS | ({"expected_fingerprint", "time_limit_seconds"} if starting else set()))
    object_name, scene_name = name(params.get("object_name"), "object_name"), name(params.get("scene_name"), "scene_name")
    start = int_param(params, "frame_start", 0, minimum=1, maximum=1048574)
    end = int_param(params, "frame_end", 0, minimum=1, maximum=1048574)
    action = params.get("action", "BAKE")
    if type(action) is not str or action not in PERMITTED_ACTIONS:
        raise invalid_argument("action must be BAKE, INVALIDATE or FREE.")
    if not 1 <= end-start+1 <= MAX_FRAMES:
        raise invalid_argument("Cloth jobs require an ordered range of at most 16 integer frames.")
    if starting:
        time_limit(params)
        fingerprint = params.get("expected_fingerprint")
        if type(fingerprint) is not str or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
            raise invalid_argument("expected_fingerprint must be the exact 64-character lowercase preview hash.")
    return {"profile": PROFILE, "object_name": object_name, "scene_name": scene_name,
            "frame_start": start, "frame_end": end, "action": action}


def schema(bpy: Any, owner: Any, kind: str | None = None) -> tuple:
    """Finite metadata/absence admission before the first projected getter.

    In particular active_selection_set.default is never resolved. The reviewed
    is_property_set(ghost=False) implementation performs a noncreating lookup,
    including ghost/default storage. Present bundled storage remains unsupported.
    """
    runtime.profile(bpy)
    identifier = owner.bl_rna.identifier if kind is None else kind
    canonical = roles._particle_class(bpy, identifier)
    if type(owner) is not canonical or owner.bl_rna.as_pointer() != canonical.bl_rna.as_pointer():
        raise refuse("CLOTH_NONCANONICAL_RNA_OWNER", owner_type=identifier)
    diagnostic_owner = identifier if type(identifier) is str else None
    props = bounded(canonical.bl_rna.properties, runtime.MAX_PROPERTIES,
                    field="RNA.class.properties", owner_type=diagnostic_owner)
    signatures = tuple(runtime._signature(prop) for prop in props)
    if len({row[0] for row in signatures}) != len(signatures):
        raise refuse("CLOTH_DUPLICATE_PROPERTY")
    declarations = {field: (category, fixed) for field, category, fixed in runtime.DECLARATIONS.get(identifier, ())}
    present = set()
    method = runtime._presence_descriptor(bpy, canonical) if declarations else None
    missing = object()
    for row in signatures:
        if row[2] is True:
            if (declarations.get(row[0]) != (row[1], row[6]) or row[3] is not (row[0] != "active_selection_set")
                    or row[4] is not False or row[5] not in (None, 0)):
                raise refuse("CLOTH_UNKNOWN_RUNTIME_DECLARATION", owner_type=identifier, property=row[0])
            # Stock runtime registration retains a deferred object in the Python
            # class dictionary. These exact declarations are never projected or
            # resolved: only native noncreating storage absence is checked below.
            # Their opaque class attributes need no purity/provenance exemption.
            present.add(row[0])
            continue
        if row[2] is not False:
            raise refuse("CLOTH_FIELD_SCHEMA_CHANGED", property=row[0])
        descriptor = getattr_static(canonical, row[0], missing)
        if (descriptor is not missing and type(descriptor) is not GetSetDescriptorType
                and type(descriptor) is not MemberDescriptorType):
            raise refuse("CLOTH_PYTHON_PROPERTY_SHADOW", owner_type=identifier, property=row[0])
    if present != set(declarations):
        raise refuse("CLOTH_RUNTIME_SCHEMA_CHANGED", owner_type=identifier)
    for field in sorted(present):
        if method(owner, field, ghost=False) is not False:
            raise refuse("CLOTH_STORED_RUNTIME_SETTINGS", owner_type=identifier, property=field)
    if tuple(runtime._signature(prop) for prop in bounded(canonical.bl_rna.properties, runtime.MAX_PROPERTIES,
            field="RNA.class.properties", owner_type=diagnostic_owner)) != signatures:
        raise refuse("CLOTH_DESCRIPTOR_CHANGED")
    return props


def read(bpy: Any, owner: Any, field: str, category: str, *, fixed: str | None = None) -> Any:
    prop = next((prop for prop in schema(bpy, owner) if prop.identifier == field), None)
    if (prop is None or prop.is_runtime or prop.type != category
            or (fixed is not None and prop.fixed_type.identifier != fixed)):
        raise refuse("CLOTH_FIELD_SCHEMA_CHANGED", property=field)
    return getattr(owner, field)


def scalar(raw: Any, category: str, count: int = 0) -> Any:
    if count:
        values = bounded(raw, min(count, 256), field="RNA.primitive.array")
        if category == "FLOAT" and count == 16 and len(values) == 4:
            rows = tuple(bounded(row, 4, field="RNA.matrix.row") for row in values)
            if any(len(row) != 4 for row in rows):
                raise refuse("CLOTH_ARRAY_SHAPE")
            return tuple(scalar(value, category) for row in rows for value in row)
        if len(values) != count:
            raise refuse("CLOTH_ARRAY_SHAPE")
        return tuple(scalar(value, category) for value in values)
    if category == "BOOLEAN" and type(raw) is bool:
        return raw
    if category == "INT" and type(raw) is int and raw.bit_length() <= 64:
        return raw
    if category == "FLOAT" and type(raw) in {int, float} and math.isfinite(raw):
        return float(raw).hex()
    if category in {"STRING", "ENUM"} and type(raw) is str and len(raw.encode("utf-8")) <= 4096:
        return raw
    if category == "ENUM" and type(raw) is set and all(type(value) is str and len(value) <= 128 for value in raw):
        return tuple(sorted(raw))
    raise refuse("CLOTH_NONFINITE_OR_UNTYPED_VALUE")


def primitives(bpy: Any, owner: Any, *, exclude: frozenset = frozenset()) -> tuple:
    props = schema(bpy, owner)  # Complete descriptor pass precedes every value.
    if owner.bl_rna.identifier == "Object":
        exclude = exclude | {"dimensions"}  # Derived bounding-box getter is unnecessary here.
    elif owner.bl_rna.identifier == "MeshPolygon":
        # Both pinned builds declare a nominal array_length of three while
        # PROP_DYNAMIC resolves the complete face size. mesh_state records this
        # field once below, using loop_total rather than the nominal length.
        exclude = exclude | {"vertices"}
    result = []
    for prop in props:
        if not prop.is_runtime and not prop.is_readonly and prop.type in PRIMITIVES and prop.identifier not in exclude:
            count = prop.array_length if prop.type in {"BOOLEAN", "INT", "FLOAT"} else 0
            result.append((prop.identifier, scalar(getattr(owner, prop.identifier), prop.type, count)))
    return tuple(result)


def token(owner: Any) -> tuple | None:
    return None if owner is None else roles.identity(owner)


def local(bpy: Any, owner: Any) -> None:
    schema(bpy, owner)
    for field in ("library", "override_library", "animation_data"):
        if read(bpy, owner, field, "POINTER") is not None:
            raise refuse("CLOTH_NONLOCAL_OR_ANIMATED_ID")
    if read(bpy, owner, "is_editable", "BOOLEAN") is not True:
        raise refuse("CLOTH_NONEDITABLE_ID")
    keys = bounded(owner.keys(), 32, field="ID.custom_properties")
    if any(key != MARKER_KEY or owner.bl_rna.identifier != "Scene" for key in keys):
        raise refuse("CLOTH_UNOBSERVED_CUSTOM_SETTINGS")


def vertex_memberships(bpy: Any, vertex: Any) -> tuple:
    """Project the essential readonly group index and its authored weight.

    VertexGroupElement.group is readonly RNA, but selects which cloth pin or
    stiffness group owns the weight. Generic readonly getters stay excluded.
    """
    result, indices = [], set()
    for member in bounded(read(bpy, vertex, "groups", "COLLECTION"), MAX_VERTEX_GROUPS, field="MeshVertex.groups"):
        props = {prop.identifier: prop for prop in schema(bpy, member, "VertexGroupElement")}
        for field, category, readonly in (("group", "INT", True), ("weight", "FLOAT", False)):
            prop = props.get(field)
            if (prop is None or prop.type != category or prop.is_runtime is not False
                    or prop.is_registered is not False or prop.is_readonly is not readonly
                    or prop.array_length != 0):
                raise refuse("CLOTH_VERTEX_MEMBERSHIP_SCHEMA_CHANGED", property=field)
        group, weight = member.group, member.weight
        if (type(group) is not int or not 0 <= group < MAX_VERTEX_GROUPS or group in indices
                or type(weight) is not float or not math.isfinite(weight) or not 0. <= weight <= 1.):
            raise refuse("CLOTH_VERTEX_MEMBERSHIP_UNQUALIFIED")
        indices.add(group)
        result.append((group, weight.hex()))
    return tuple(result)


def attribute_storage(bpy: Any, attribute: Any, value_class: str) -> str:
    """Refuse unreviewed physical storage before resolving Attribute.data.

    5.2's SINGLE data iterator assigns ARRAY storage. The source-reviewed native
    readonly storage getter does not perform that conversion. 4.5 has no such
    property: prove descriptor absence without resolving an absent field.
    """
    build = runtime.profile(bpy)
    props = {prop.identifier: prop for prop in schema(bpy, attribute)}
    data = props.get("data")
    if (data is None or data.type != "COLLECTION" or data.is_runtime is not False
            or data.is_registered is not False or data.is_readonly is not True
            or data.fixed_type.identifier != value_class):
        raise refuse("CLOTH_ATTRIBUTE_DATA_SCHEMA_CHANGED")
    storage = props.get("storage_type")
    if build[1] == (4, 5, 14):
        if storage is not None:
            raise refuse("CLOTH_ATTRIBUTE_STORAGE_SCHEMA_CHANGED")
        return "LEGACY_ARRAY_4_5"
    if (build[1] != (5, 2, 2) or storage is None or storage.type != "ENUM"
            or storage.is_runtime is not False or storage.is_registered is not False
            or storage.is_readonly is not True):
        raise refuse("CLOTH_ATTRIBUTE_STORAGE_SCHEMA_CHANGED")
    value = attribute.storage_type
    if type(value) is not str or value != "ARRAY":
        raise refuse("CLOTH_ATTRIBUTE_STORAGE_UNSUPPORTED", attribute_storage="SINGLE" if type(value) is str and value == "SINGLE" else "UNKNOWN",
                     single_storage_support="OPEN_TEMPORARY_ALPHA_GAP")
    return value


class AttributePlan(NamedTuple):
    """Detached logical facts; no Attribute owner or CustomDataLayer pointer."""
    name: str
    domain: str
    category: str
    native_class: str
    value_class: str
    schema: tuple
    storage: str


def attribute_plan(bpy: Any, attribute: Any) -> AttributePlan:
    category = read(bpy, attribute, "data_type", "ENUM")
    classes = ATTRIBUTE_VALUES.get(category)
    if classes is None:
        raise refuse("CLOTH_ATTRIBUTE_TYPE_UNSUPPORTED")
    props = schema(bpy, attribute, classes[0])
    storage = attribute_storage(bpy, attribute, classes[1])
    name = scalar(read(bpy, attribute, "name", "STRING"), "STRING")
    domain = scalar(read(bpy, attribute, "domain", "ENUM"), "ENUM")
    if not name or "\x00" in name or type(domain) is not str:
        raise refuse("CLOTH_ATTRIBUTE_NAME_OR_DOMAIN_UNQUALIFIED")
    # These are canonical PropertyRNA descriptor facts, not attribute-record or
    # buffer addresses. Every scalar/tuple is detached before geometry access.
    signature = tuple(runtime._signature(prop) for prop in props)
    return AttributePlan(name, domain, category, classes[0], classes[1], signature, storage)


def attribute_inventory(bpy: Any, mesh: Any) -> tuple[AttributePlan, ...]:
    result = tuple(attribute_plan(bpy, attribute)
                   for attribute in bounded(read(bpy, mesh, "attributes", "COLLECTION"), 64, field="Mesh.attributes"))
    if len({plan.name for plan in result}) != len(result):
        raise refuse("CLOTH_ATTRIBUTE_NAMES_AMBIGUOUS")
    return result


def fresh_attribute(bpy: Any, mesh: Any, expected: tuple[AttributePlan, ...], target: AttributePlan) -> Any:
    """Resolve a current owner only after proving the whole inventory unchanged.

    4.5 geometry/group getters may insert legacy CustomData records and move the
    records behind earlier Attribute wrappers. No admitted owner is reused.
    Data iteration from a previous attribute may also not supply the next owner.
    """
    plans, selected = [], None
    for attribute in bounded(read(bpy, mesh, "attributes", "COLLECTION"), 64, field="Mesh.attributes"):
        plan = attribute_plan(bpy, attribute)
        plans.append(plan)
        if plan.name == target.name:
            if selected is not None or plan != target:
                raise refuse("CLOTH_ATTRIBUTE_INVENTORY_CHANGED")
            selected = attribute
    if tuple(plans) != expected or selected is None:
        raise refuse("CLOTH_ATTRIBUTE_INVENTORY_CHANGED")
    return selected


def mesh_state(bpy: Any, mesh: Any) -> tuple:
    local(bpy, mesh)
    if read(bpy, mesh, "shape_keys", "POINTER") is not None:
        raise refuse("CLOTH_SHAPE_KEYS_UNSUPPORTED")
    attributes, total = [], 0
    # Geometry accessors also request mutable native attribute buffers. Qualify
    # every attribute before even resolving vertices/edges/loops/polygons, so
    # SINGLE position storage cannot convert before its storage is checked.
    admitted = attribute_inventory(bpy, mesh)
    vertices = bounded(read(bpy, mesh, "vertices", "COLLECTION"), MAX_VERTICES, field="Mesh.vertices")
    edges = bounded(read(bpy, mesh, "edges", "COLLECTION"), 1024, field="Mesh.edges")
    loops = bounded(read(bpy, mesh, "loops", "COLLECTION"), 2048, field="Mesh.loops")
    polygons = bounded(read(bpy, mesh, "polygons", "COLLECTION"), 1024, field="Mesh.polygons")
    geometry = []
    for records, kind in ((vertices, "MeshVertex"), (edges, "MeshEdge"), (loops, "MeshLoop"), (polygons, "MeshPolygon")):
        rows = []
        for record in records:
            schema(bpy, record, kind)
            row = primitives(bpy, record)
            if kind == "MeshVertex":
                row = (row, vertex_memberships(bpy, record))
            if kind == "MeshPolygon":
                count = read(bpy, record, "loop_total", "INT")
                if type(count) is not int or not 3 <= count <= len(loops):
                    raise refuse("CLOTH_POLYGON_TOPOLOGY_UNQUALIFIED")
                indices = bounded(read(bpy, record, "vertices", "INT"), min(count, 256),
                                  field="MeshPolygon.vertices")
                if (len(indices) != count or any(type(index) is not int or not 0 <= index < len(vertices)
                                                 for index in indices)):
                    raise refuse("CLOTH_POLYGON_TOPOLOGY_UNQUALIFIED")
                row = (row, indices)
            elif kind == "MeshEdge":
                row = (row, tuple(read(bpy, record, "vertices", "INT")))
            elif kind == "MeshLoop":
                row = (row, read(bpy, record, "vertex_index", "INT"), read(bpy, record, "edge_index", "INT"))
            rows.append(row)
        geometry.append(tuple(rows))
    if attribute_inventory(bpy, mesh) != admitted:
        raise refuse("CLOTH_ATTRIBUTE_INVENTORY_CHANGED")
    for plan in admitted:
        attribute = fresh_attribute(bpy, mesh, admitted, plan)
        records = bounded(read(bpy, attribute, "data", "COLLECTION"), 8192-total, field="Attribute.data")
        total += len(records)
        values = tuple(primitives(bpy, item) for item in records)
        del attribute, records
        attributes.append((plan.name, plan.domain, plan.category, plan.storage, values,
                           plan.native_class, plan.value_class, plan.schema))
    if attribute_inventory(bpy, mesh) != admitted:
        raise refuse("CLOTH_ATTRIBUTE_INVENTORY_CHANGED")
    return (token(mesh), primitives(bpy, mesh), tuple(geometry), tuple(attributes),
            tuple(token(item) for item in bounded(read(bpy, mesh, "materials", "COLLECTION"), 16, field="Mesh.materials")))


def object_state(bpy: Any, obj: Any, *, cloth: bool = False) -> tuple:
    local(bpy, obj)
    kind = read(bpy, obj, "type", "ENUM")
    if read(bpy, obj, "mode", "ENUM") != "OBJECT":
        raise refuse("CLOTH_OBJECT_MODE_REQUIRED")
    if kind not in {"MESH", "EMPTY", "CAMERA", "LIGHT"}:
        raise refuse("CLOTH_OBJECT_TYPE_UNSUPPORTED")
    for field in ("parent", "rigid_body", "rigid_body_constraint", "soft_body"):
        if read(bpy, obj, field, "POINTER") is not None:
            raise refuse("CLOTH_OBJECT_DEPENDENCY_UNSUPPORTED", property=field)
    for field, label in (("constraints", "Object.constraints"), ("particle_systems", "Object.particle_systems")):
        if bounded(read(bpy, obj, field, "COLLECTION"), 16, field=label):
            raise refuse("CLOTH_OBJECT_DEPENDENCY_UNSUPPORTED", property=field)
    # Source-reviewed native getter only; it does not manufacture missing pd.
    if read(bpy, obj, "field", "POINTER", fixed="FieldSettings") is not None:
        raise refuse("CLOTH_FORCE_FIELD_STORAGE_UNSUPPORTED")
    if read(bpy, obj, "instance_type", "ENUM") != "NONE":
        raise refuse("CLOTH_INSTANCE_UNSUPPORTED")
    modifiers = bounded(read(bpy, obj, "modifiers", "COLLECTION"), 2, field="Object.modifiers")
    if (cloth and (len(modifiers) != 1 or read(bpy, modifiers[0], "type", "ENUM") != "CLOTH")) or (not cloth and modifiers):
        raise refuse("CLOTH_MODIFIER_STACK_UNSUPPORTED")
    data = read(bpy, obj, "data", "POINTER")
    if kind == "EMPTY" and data is not None:
        raise refuse("CLOTH_PLAIN_EMPTY_REQUIRED")
    if kind == "MESH":
        if read(bpy, data, "users", "INT") != 1:
            raise refuse("CLOTH_SHARED_MESH_UNSUPPORTED")
        data_state = mesh_state(bpy, data)
    elif data is not None:
        local(bpy, data)
        data_state = token(data), primitives(bpy, data)
    else:
        data_state = None
    return (token(obj), primitives(bpy, obj), data_state,
            tuple(primitives(bpy, group) for group in bounded(read(bpy, obj, "vertex_groups", "COLLECTION"), MAX_VERTEX_GROUPS,
                                                            field="Object.vertex_groups")),
            tuple((read(bpy, slot, "link", "ENUM"), token(read(bpy, slot, "material", "POINTER")))
                  for slot in bounded(read(bpy, obj, "material_slots", "COLLECTION"), 16, field="Object.material_slots")))


# These are temporal outputs, not immutable Scene authoring. Native frame_set
# updates frame_float too; mapped current_final is readonly but solver-relevant.
CLOCK_FIELDS = frozenset({"frame_current", "frame_subframe", "frame_float", "frame_current_final"})


class TimeInputs(NamedTuple):
    frame_map_old: int
    frame_map_new: int


_CLOCK_NATIVE = {
    "Scene": (("render", "POINTER", True, "RenderSettings"),
        ("frame_current", "INT", False, None), ("frame_subframe", "FLOAT", False, None),
        ("frame_float", "FLOAT", False, None), ("frame_current_final", "FLOAT", True, None)),
    "RenderSettings": (("frame_map_old", "INT", False, None), ("frame_map_new", "INT", False, None)),
    "Screen": (("is_animation_playing", "BOOLEAN", True, None),),
    "BlendData": (("window_managers", "COLLECTION", True, "WindowManager"),),
    "Context": (("window_manager", "POINTER", True, "WindowManager"),
        ("screen", "POINTER", True, "Screen"), ("area", "POINTER", True, "Area"),
        ("window", "POINTER", True, "Window"), ("mode", "ENUM", True, None),
        ("preferences", "POINTER", True, "Preferences")),
    "Window": (("scene", "POINTER", False, "Scene"),),
    "Preferences": (("edit", "POINTER", True, "PreferencesEdit"),),
    "PreferencesEdit": (("use_negative_frames", "BOOLEAN", False, None),),
}


def _clock_read(bpy: Any, owner: Any, kind: str, field: str) -> Any:
    family = _CLOCK_NATIVE.get(kind)
    if family is None or field not in {row[0] for row in family}:
        raise refuse("CLOTH_CLOCK_FIELD_UNQUALIFIED", property=field)
    props = {prop.identifier: prop for prop in schema(bpy, owner, kind)}
    # The complete selected family is qualified before its first getter; never
    # let an altered runtime/readonly/registered/array declaration become a read.
    for name, category, readonly, fixed in family:
        prop = props.get(name)
        if (prop is None or prop.type != category or prop.is_runtime is not False
                or prop.is_registered is not False or prop.is_readonly is not readonly
                or (category in {"BOOLEAN", "INT", "FLOAT"} and (type(prop.array_length) is not int or prop.array_length != 0))
                or (fixed is not None and prop.fixed_type.identifier != fixed)):
            raise refuse("CLOTH_CLOCK_FIELD_UNQUALIFIED", property=name)
    return getattr(owner, field)


def time_inputs(bpy: Any, scene: Any) -> TimeInputs:
    # RNA's readonly render pointer wraps the Scene's embedded RenderData. Only
    # the two proven timing fields are read; no generic render/settings walk.
    render = _clock_read(bpy, scene, "Scene", "render")
    schema(bpy, render, "RenderSettings")
    values = tuple(_clock_read(bpy, render, "RenderSettings", field) for field in ("frame_map_old", "frame_map_new"))
    if any(type(value) is not int or not 1 <= value <= 900 for value in values):
        raise refuse("CLOTH_FRAME_MAPPING_UNQUALIFIED")
    return TimeInputs(*values)


def float32(value: float) -> float:
    # Match each source C float operation, not an approximate/tolerance CAS.
    try:
        result = struct.unpack("=f", struct.pack("=f", value))[0]
    except (OverflowError, struct.error) as error:
        raise refuse("CLOTH_CLOCK_UNREPRESENTABLE") from error
    if not math.isfinite(result):
        raise refuse("CLOTH_CLOCK_UNREPRESENTABLE")
    return result


def working_clock(frame: tuple[int, float], inputs: TimeInputs) -> dict:
    if (type(inputs) is not TimeInputs or any(type(value) is not int or not 1 <= value <= 900 for value in inputs)
            or type(frame) is not tuple or len(frame) != 2 or type(frame[0]) is not int
            or not -1048574 <= frame[0] <= 1048574 or type(frame[1]) is not float
            or not math.isfinite(frame[1]) or not -1. <= frame[1] <= 1.
            or float32(frame[1]).hex() != frame[1].hex()):
        raise refuse("CLOTH_CLOCK_UNQUALIFIED")
    # RNA frame_map_old is DNA framapto; new is images. The callback stores
    # float(framapto)/float(images). ctime adds subframe, then multiplies by it.
    raw_float = float32(float32(float(frame[0])) + frame[1])
    scale = float32(float(inputs.frame_map_old) / float(inputs.frame_map_new))
    return {"frame": frame, "frame_float": raw_float.hex(),
            "frame_current_final": float32(raw_float * scale).hex()}


def scene_clock(bpy: Any, scene: Any, inputs: TimeInputs) -> dict:
    # _clock_read qualifies the canonical class and field shadow before every
    # getter, including both readonly and writable derived clock properties.
    frame = (_clock_read(bpy, scene, "Scene", "frame_current"), _clock_read(bpy, scene, "Scene", "frame_subframe"))
    actual = {"frame": frame,
        "frame_float": scalar(_clock_read(bpy, scene, "Scene", "frame_float"), "FLOAT"),
        "frame_current_final": scalar(_clock_read(bpy, scene, "Scene", "frame_current_final"), "FLOAT")}
    if digest(actual) != digest(working_clock(frame, inputs)):
        raise refuse("CLOTH_EFFECTIVE_CLOCK_INCONSISTENT")
    return actual


def _clock_pointer(bpy: Any, owner: Any) -> int:
    base = bpy.types.bpy_struct
    method = getattr_static(base, "as_pointer", None)
    if (type(method) is not MethodDescriptorType or method.__objclass__ is not base
            or getattr_static(type(owner), "as_pointer", None) is not method):
        raise refuse("CLOTH_CLOCK_POINTER_ORIGIN_UNQUALIFIED")
    pointer = method(owner)
    if type(pointer) is not int or not 0 < pointer < 2**64:
        raise refuse("CLOTH_CLOCK_POINTER_UNQUALIFIED")
    return pointer


def negative_frame_policy(bpy: Any) -> tuple[int, int, bool]:
    preferences = _clock_read(bpy, bpy.context, "Context", "preferences")
    edit = _clock_read(bpy, preferences, "Preferences", "edit")
    allowed = _clock_read(bpy, edit, "PreferencesEdit", "use_negative_frames")
    if type(allowed) is not bool:
        raise refuse("CLOTH_NEGATIVE_FRAME_POLICY_UNQUALIFIED")
    return (_clock_pointer(bpy, preferences), _clock_pointer(bpy, edit), allowed)


def restoration_steps(frame: tuple[int, float], inputs: TimeInputs, allowed: bool) -> tuple:
    """Precompute actual call arguments and exact outputs before any cache write."""
    working_clock(frame, inputs)
    if type(allowed) is not bool:
        raise refuse("CLOTH_NEGATIVE_FRAME_POLICY_UNQUALIFIED")
    integer, fraction = frame
    if fraction >= 0.:
        first = ("frame_set", (integer, -0.), (integer, -0.)) if integer < 0 else (
            "scene_frame_current_set", integer, None)
        return (first, ("scene_frame_subframe_set", fraction, frame))
    combined = float32(float32(float(integer)) + fraction)
    whole = int(combined)
    native_pair = (whole, float32(combined - float32(float(whole))))
    if (not -1048574. <= combined <= 1048574. or digest(native_pair) != digest(frame)):
        raise refuse("CLOTH_CALLER_CLOCK_RESTORATION_UNQUALIFIED")
    if allowed:
        return (("scene_frame_float_set", combined, native_pair),)
    base = math.floor(combined)
    subargument = float32(combined - float(base))
    rounded = float32(float(base) + subargument)
    subframe, integer_part = math.modf(rounded)
    output = (int(integer_part), subframe)
    if (not -1048574 <= base <= 1048574 or not 0. <= subargument <= 1.
            or digest(output) != digest(frame)):
        raise refuse("CLOTH_CALLER_CLOCK_RESTORATION_UNQUALIFIED")
    return (("frame_set", (base, subargument), output),)


def clock_callback_context(bpy: Any) -> tuple | None:
    """Exclude 5.2's context-sensitive VSE update before a raw time setter.

    The Screen getter queries G_MAIN's first WindowManager. Require that exact
    sole manager to be the current one. With no playback and no context Area,
    neither VSE space predicate can activate Scene/time synchronization. Area.type
    is insufficient: its getter can expose a pending, rather than actual type.
    Frame-change dependency tags and notifiers still occur and are not passive.
    """
    if runtime.profile(bpy)[1][:2] != (5, 2):
        return None
    c = bpy.context
    managers = bounded(_clock_read(bpy, bpy.data, "BlendData", "window_managers"), 1, field="BlendData.window_managers")
    if len(managers) != 1 or managers[0] is not _clock_read(bpy, c, "Context", "window_manager"):
        raise refuse("CLOTH_CLOCK_WINDOW_MANAGER_UNQUALIFIED")
    screen = _clock_read(bpy, c, "Context", "screen")
    if screen is None or _clock_read(bpy, screen, "Screen", "is_animation_playing") is not False:
        raise refuse("CLOTH_CLOCK_PLAYBACK_UNSUPPORTED")
    if _clock_read(bpy, c, "Context", "area") is not None:
        raise refuse("CLOTH_CLOCK_VSE_CONTEXT_UNSUPPORTED")
    return (None,)


def scene_state(bpy: Any, scene: Any, target: Any, *, target_scene: bool) -> tuple:
    local(bpy, scene)
    if read(bpy, scene, "rigidbody_world", "POINTER") is not None:
        raise refuse("CLOTH_RIGID_WORLD_UNSUPPORTED")
    layers = bounded(read(bpy, scene, "view_layers", "COLLECTION"), 1, field="Scene.view_layers")
    if len(layers) != 1:
        raise refuse("CLOTH_ONE_VIEW_LAYER_REQUIRED")
    layer = layers[0]
    schema(bpy, layer, "ViewLayer")
    objects = bounded(read(bpy, scene, "objects", "COLLECTION"), MAX_OBJECTS, field="Scene.objects")
    authored = tuple(object_state(bpy, obj, cloth=obj is target) for obj in objects)
    particle = roles._particle_settings(bpy, scene)[1]
    timing = time_inputs(bpy, scene)
    return (token(scene), primitives(bpy, scene, exclude=CLOCK_FIELDS), timing,
            None if target_scene else scene_clock(bpy, scene, timing),
            primitives(bpy, read(bpy, scene, "unit_settings", "POINTER")),
            primitives(bpy, particle), authored,
            tuple((token(obj), bool(obj.select_get(view_layer=layer))) for obj in objects),
            token(layer.objects.active), layer.as_pointer())


def static_data(bpy: Any, scene: Any, home: Any, obj: Any) -> tuple:
    runtime.profile(bpy)
    if set(bounded(bpy.data.scenes, 2, field="BlendData.scenes")) != {scene, home} or scene is home:
        raise refuse("CLOTH_EXACT_TWO_SCENES_REQUIRED")
    if len(bounded(bpy.data.objects, MAX_OBJECTS, field="BlendData.objects")) > MAX_OBJECTS:
        raise refuse("CLOTH_OBJECT_BUDGET")
    for handler, label in (("frame_change_pre", "bpy.app.handlers.frame_change_pre"),
                           ("frame_change_post", "bpy.app.handlers.frame_change_post"),
                           ("depsgraph_update_pre", "bpy.app.handlers.depsgraph_update_pre"),
                           ("depsgraph_update_post", "bpy.app.handlers.depsgraph_update_post")):
        if bounded(getattr(bpy.app.handlers, handler), 32, field=label):
            raise refuse("CLOTH_UNKNOWN_EVALUATION_HANDLER", handler=handler)
    mark_view_layer_sync_possible()
    graph = dependencies.snapshot(bpy)  # Native static dependency metadata; no evaluation.
    return (runtime.profile(bpy), graph, scene_state(bpy, home, obj, target_scene=False),
            scene_state(bpy, scene, obj, target_scene=True))


def cloth_state(bpy: Any, obj: Any) -> tuple[Any, Any, tuple, dict]:
    object_state(bpy, obj, cloth=True)
    modifier = obj.modifiers[0]
    settings = read(bpy, modifier, "settings", "POINTER")
    collisions = read(bpy, modifier, "collision_settings", "POINTER")
    cache = read(bpy, modifier, "point_cache", "POINTER")
    if (read(bpy, settings, "quality", "INT") > 3 or read(bpy, cache, "frame_step", "INT") != 1
            or read(bpy, cache, "use_disk_cache", "BOOLEAN") or read(bpy, cache, "use_external", "BOOLEAN")
            or read(bpy, cache, "is_baking", "BOOLEAN")
            or read(bpy, collisions, "use_collision", "BOOLEAN") or read(bpy, collisions, "use_self_collision", "BOOLEAN")):
        raise refuse("CLOTH_MEMORY_SOLVER_PROFILE_UNSUPPORTED")
    for owner, field in ((settings, "rest_shape_key"), (collisions, "collection")):
        if read(bpy, owner, field, "POINTER") is not None:
            raise refuse("CLOTH_SETTINGS_DEPENDENCY_UNSUPPORTED", property=field)
    weights = read(bpy, settings, "effector_weights", "POINTER")
    if read(bpy, weights, "collection", "POINTER") is not None:
        raise refuse("CLOTH_EFFECTOR_COLLECTION_UNSUPPORTED")
    caches = bounded(read(bpy, cache, "point_caches", "COLLECTION"), 1, field="PointCache.point_caches")
    if len(caches) != 1 or caches[0].as_pointer() != cache.as_pointer():
        raise refuse("CLOTH_SINGLE_POINT_CACHE_REQUIRED")
    authored = (modifier.as_pointer(), primitives(bpy, modifier), settings.as_pointer(), primitives(bpy, settings),
        collisions.as_pointer(), primitives(bpy, collisions), weights.as_pointer(), primitives(bpy, weights),
        cache.as_pointer(), primitives(bpy, cache, exclude=frozenset({"frame_start", "frame_end", "frame_step"})))
    owned = {"range": (cache.frame_start, cache.frame_end), "step": cache.frame_step,
             "baked": cache.is_baked}
    return modifier, cache, authored, owned


@dataclass(frozen=True, slots=True)
class PreparedContext:
    state: Any
    store: Any
    epoch: int
    job: Any
    scene: Any
    home: Any
    obj: Any
    empty: Any
    home_empty: Any
    roles: roles.DeclaredRoles
    layout: tuple

    def check_state(self, context: Any) -> None:
        if (context.state is not self.state or getattr(context.state, "_artist_task_plans", None) is not self.store
                or self.store.evidence_epoch != self.epoch
                or self.job.state != "SUCCEEDED"):
            raise refuse("CLOTH_CONTEXT_PREPARATION_NOT_COMPLETED")

    def check(self, context: Any, bpy: Any) -> None:
        self.check_state(context)
        if layout(bpy) != self.layout or bpy.context.scene is not self.scene or bpy.context.view_layer.objects.active is not self.empty:
            raise refuse("CLOTH_PREPARED_CONTEXT_CHANGED")
        current = replace(self.roles, context=roles.context(bpy))
        for scene, empty in ((self.home, self.home_empty), (self.scene, self.empty)):
            particle = roles._particle_settings(bpy, scene)[1]
            if read(bpy, particle, "object", "POINTER", fixed="Object") is not empty:
                raise refuse("CLOTH_PARTICLE_OBJECT_ROLE_CHANGED")
        mark_view_layer_sync_possible()
        roles.verify(bpy, current, (self.home, self.scene))


_prepared: PreparedContext | None = None


def retain_prepared(value: PreparedContext) -> None:
    global _prepared
    if type(value) is not PreparedContext:
        raise refuse("CLOTH_PREPARATION_RECEIPT_INVALID")
    _prepared = value


def layout(bpy: Any) -> tuple:
    c = bpy.context
    workspaces = bounded(bpy.data.workspaces, 16, field="BlendData.workspaces")
    if any(workspace.use_pin_scene for workspace in workspaces):
        raise refuse("CLOTH_PINNED_WORKSPACE_UNSUPPORTED")
    return (bpy.data.as_pointer(), bpy.data.filepath, c.window.as_pointer(), token(c.window_manager),
            token(c.workspace), token(c.screen), c.mode,
            tuple((token(workspace), workspace.object_mode,
                   tuple(token(screen) for screen in bounded(workspace.screens, 16, field="WorkSpace.screens")))
                  for workspace in workspaces))


def capture(context: Any, bpy: Any, request: dict) -> tuple:
    prepared = _prepared
    if type(prepared) is not PreparedContext:
        raise refuse("CLOTH_CONTEXT_PREPARATION_REQUIRED")
    prepared.check_state(context)  # Reject stale authority before touching retained RNA.
    scene, home, obj = prepared.scene, prepared.home, prepared.obj
    if _clock_read(bpy, bpy.context, "Context", "mode") != "OBJECT":
        raise refuse("CLOTH_OBJECT_MODE_REQUIRED")
    window = _clock_read(bpy, bpy.context, "Context", "window")
    if window is None or _clock_read(bpy, window, "Window", "scene") is not scene:
        raise refuse("CLOTH_OBJECT_MODE_REQUIRED")
    # Qualify the clock fields before role/context helpers resolve raw time.
    timing = time_inputs(bpy, scene)
    clock_before = scene_clock(bpy, scene, timing)
    callback_context = clock_callback_context(bpy) if request["action"] == "BAKE" else None
    policy = negative_frame_policy(bpy) if request["action"] == "BAKE" else None
    if policy is not None:
        restoration_steps(clock_before["frame"], timing, policy[2])
    prepared.check(context, bpy)
    if request["scene_name"] != read(bpy, scene, "name", "STRING") or request["object_name"] != read(bpy, obj, "name", "STRING"):
        raise refuse("CLOTH_PREPARED_TARGET_CHANGED")
    mark_view_layer_sync_possible()
    before = roles.context(bpy)
    modifier, cache, authored, owned = cloth_state(bpy, obj)
    data = static_data(bpy, scene, home, obj)
    if tuple(scene.objects) != (prepared.empty, obj) and set(scene.objects) != {prepared.empty, obj}:
        raise refuse("CLOTH_TARGET_SCENE_OBJECTS_UNSUPPORTED")
    consumers(bpy, prepared)
    if (obj.hide_get() or not obj.visible_get() or bpy.context.view_layer.objects.get(obj.name) is not obj
            or before != roles.context(bpy)):
        raise refuse("CLOTH_CAPTURE_CONTEXT_CHANGED")
    clock_after = scene_clock(bpy, scene, timing)
    if (data[3][2] != timing or time_inputs(bpy, scene) != timing
            or digest(clock_after) != digest(clock_before)
            or clock_after["frame"][0] != before[6] or clock_after["frame"][1].hex() != before[7]):
        raise refuse("CLOTH_CAPTURE_CLOCK_OR_INPUTS_CHANGED")
    if request["action"] == "BAKE" and clock_callback_context(bpy) != callback_context:
        raise refuse("CLOTH_CAPTURE_CLOCK_CALLBACK_CONTEXT_CHANGED")
    if request["action"] == "BAKE" and negative_frame_policy(bpy) != policy:
        raise refuse("CLOTH_CAPTURE_NEGATIVE_FRAME_POLICY_CHANGED")
    prepared.check(context, bpy)
    owned["frame"], owned["clock"] = clock_after["frame"], clock_after
    snapshot = {"data": data, "cloth": authored, "owned": owned, "time_inputs": timing,
                "clock_callback_context": callback_context, "negative_frame_policy": policy,
                "context": before, "layout": prepared.layout}
    fingerprint = digest({"scope": snapshot, "proposal": request})
    return prepared, modifier, cache, snapshot, fingerprint


def consumers(bpy: Any, prepared: PreparedContext) -> None:
    """Declare root membership + one native Base; no observed-count baseline."""
    scene, obj, empty = prepared.scene, prepared.obj, prepared.empty
    root = read(bpy, scene, "collection", "POINTER")
    schema(bpy, root, "Collection")
    if bounded(read(bpy, root, "children", "COLLECTION"), 16, field="Scene.collection.children"):
        raise refuse("CLOTH_NESTED_COLLECTION_UNSUPPORTED")
    if set(bounded(read(bpy, root, "objects", "COLLECTION"), 2, field="Scene.collection.objects")) != {obj, empty}:
        raise refuse("CLOTH_ROOT_MEMBERSHIP_CHANGED")
    for target in (obj, empty):
        if read(bpy, target, "users", "INT") != 1:
            raise refuse("CLOTH_SHARED_OBJECT_UNSUPPORTED")
    mesh = read(bpy, obj, "data", "POINTER")
    mapping = bpy.data.user_map(subset={obj, empty, mesh})
    declarations = ((obj, scene, 2), (empty, scene, 3), (mesh, obj, 1))
    for target, owner, count in declarations:
        if set(mapping.get(target, ())) != {owner} or owner.user_of_id(target) != count:
            raise refuse("CLOTH_OBJECT_OR_MESH_CONSUMERS_CHANGED")


def preview(context: Any, bpy: Any, params: Any, *, starting: bool = False) -> tuple:
    request = proposal(params, starting=starting)
    prepared, modifier, cache, snapshot, fingerprint = capture(context, bpy, request)
    if request["action"] == "BAKE" and snapshot["owned"]["baked"]:
        raise invalid_argument("FREE the baked cache and obtain a new preview before BAKE.")
    if starting and params["expected_fingerprint"] != fingerprint:
        raise invalid_argument("The cloth preview fingerprint is stale; preview the exact scope again.")
    return request, prepared, modifier, cache, snapshot, fingerprint
