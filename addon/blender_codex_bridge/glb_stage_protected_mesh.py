"""Detached protected Mesh observation with declared logical read effects.

This internal adapter supplies no Runtime, permission or process-ownership grant.
An exact NativeBinding carries the caller's current native-entry gate. A binding
without that gate is only the raw owned-fixture path; its report remains explicitly
unqualified. No caller headers, callbacks, storage flags or repair switches are
accepted. No legacy MeshUVLoopLayer.data getter or preparation operation is used.

Pinned native array readers can unshare/COW existing arrays, tag caches, and on
both builds create an empty CD_MDEFORMVERT through vertex.groups. These source-proven
physical effects are not authored-value changes. They are journaled separately;
physical pointer identity is not a logical compare-and-swap invariant. All 5.2
SINGLE storage refuses before geometry/data iteration. Native acceptance remains
Root-owned and is never inferred from this module's model tests.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import asdict, dataclass
from types import FunctionType, MappingProxyType, MethodDescriptorType, WrapperDescriptorType

from .errors import BridgeError, ErrorCode
from .glb_stage_profile import NativeBinding

MAX_ATTRIBUTES = 64
MAX_UV_MAPS = 8
MAX_MATERIALS = 256
MAX_GROUPS = 256
MAX_MEMBERSHIPS = 262144
MAX_SCALARS = 1_000_000
MAX_BYTES = 8 * 1024**2
COUNTS = MappingProxyType({"vertices": 32768, "edges": 65536, "loops": 131072, "polygons": 32768})
DOMAINS = MappingProxyType({"POINT": "vertices", "EDGE": "edges", "CORNER": "loops", "FACE": "polygons"})


@dataclass(frozen=True, slots=True)
class _Layout:
    attribute_class: str
    value_class: str
    field: str
    kind: str
    width: int
    minimum: int = -(2**31)
    maximum: int = 2**31 - 1


LAYOUTS = MappingProxyType({
    "FLOAT": _Layout("FloatAttribute", "FloatAttributeValue", "value", "FLOAT", 0),
    "FLOAT_VECTOR": _Layout("FloatVectorAttribute", "FloatVectorAttributeValue", "vector", "FLOAT", 3),
    "FLOAT2": _Layout("Float2Attribute", "Float2AttributeValue", "vector", "FLOAT", 2),
    "INT": _Layout("IntAttribute", "IntAttributeValue", "value", "INT", 0),
    "INT32_2D": _Layout("Int2Attribute", "Int2AttributeValue", "value", "INT", 2),
    "INT16_2D": _Layout("Short2Attribute", "Short2AttributeValue", "value", "INT", 2, -(2**15), 2**15 - 1),
    "BOOLEAN": _Layout("BoolAttribute", "BoolAttributeValue", "value", "BOOLEAN", 0),
})
CORE_ATTRIBUTES = MappingProxyType({"position": ("POINT", "FLOAT_VECTOR"),
    ".edge_verts": ("EDGE", "INT32_2D"), ".corner_vert": ("CORNER", "INT"),
    ".corner_edge": ("CORNER", "INT")})


def refused(reason: str, **facts) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, "Protected Mesh observation is outside its qualified profile.",
                       {"reason": reason, "scope_complete": False, "native_qualified": False, **facts})


def _integer(value, maximum, *, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise refused("PROTECTED_MESH_INTEGER_SHAPE")
    return value


def _boolean(value):
    if type(value) is not bool:
        raise refused("PROTECTED_MESH_BOOLEAN_SHAPE")
    return value


def _text(value, *, maximum=63, blank=False):
    if (type(value) is not str or (not blank and not value) or len(value.encode("utf8")) > maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise refused("PROTECTED_MESH_TEXT_SHAPE")
    return value


def _float_bits(value):
    if type(value) is not float or not math.isfinite(value):
        raise refused("PROTECTED_MESH_FLOAT_SHAPE")
    bits = struct.pack("<f", value)
    if struct.unpack("<f", bits)[0] != value:
        raise refused("PROTECTED_MESH_NON_FLOAT32_VALUE")
    return bits.hex()


def _canonical(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > MAX_BYTES:
        raise refused("PROTECTED_MESH_PROJECTION_BUDGET")
    return data


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def logical_projection(projection):
    """Discard only declared read effects/storage representation, not schema.

    Physical presence/name/domain/type/count, strict full component bits and UV
    roles remain literal. Headers contain no borrowed pointers. Current ARRAY vs
    LEGACY_ARRAY is representation evidence, never permission to convert SINGLE.
    """
    result = {key: value for key, value in projection.items()
              if key not in {"read_effects", "authored_sha256", "runtime_gate_bound", "native_qualified"}}
    result["attributes"] = [{key: value for key, value in row.items() if key != "storage"}
                            for row in projection["attributes"]]
    return result


@dataclass(frozen=True, slots=True)
class AttributeHeader:
    name: str
    domain: str
    data_type: str
    native_class: str
    value_class: str | None
    storage: str
    count: int
    schema_sha256: str
    supported: bool


class _Access:
    """One synchronous pass, with only immutable schema cache and native IDs.

    Static compiled RNA metadata is qualified once within this callback-free
    pass. Every later getter still checks its raw Python descriptor/slots and
    goes through NativeBinding._access's pure pre/post native gates. No schema
    cache or borrowed collection/leaf crosses a provider or timer yield.
    """

    def __init__(self, observer):
        self.observer, self.binding = observer, observer.binding
        self.cache = {}
        self.slots = {}
        cls = self.binding.collection_type
        for name in ("__getattribute__", "__len__", "__iter__", "__getitem__", "get", "foreach_get"):
            descriptor = vars(cls).get(name)
            if (type(descriptor) not in {MethodDescriptorType, WrapperDescriptorType}
                    or descriptor.__objclass__ is not cls or descriptor.__name__ != name):
                raise refused("PROTECTED_MESH_NATIVE_COLLECTION_SLOT", slot=name)
            self.slots[name] = descriptor
        self.binding.check()

    def check(self):
        self.observer._check()
        if any(vars(self.binding.collection_type).get(name) is not descriptor
               for name, descriptor in self.slots.items()):
            raise refused("PROTECTED_MESH_COLLECTION_SLOT_CHANGED")

    def cls(self, name):
        self.check()
        return self.binding.classes.get(name) or self.binding.resolve(name)

    def schema(self, cls, name, kind=None, width=None):
        self.check()
        b = self.binding
        key = cls, name
        if key not in self.cache:
            props = b._raw(b._rna(cls), "properties")
            prop = b._access("protected_schema_lookup", props.get, name)
            if prop is None:
                raise refused("PROTECTED_MESH_PROPERTY_MISSING", property=name)
            actual_kind = b._raw(prop, "type")
            actual_width = b._raw(prop, "array_length") if actual_kind in {"FLOAT", "INT", "BOOLEAN"} else None
            b.field(cls, name, actual_kind, actual_width)
            signature = b.properties[key][1]
            if signature[3] is not False or signature[4] is not False:
                raise refused("PROTECTED_MESH_RUNTIME_PROPERTY", property=name)
            self.cache[key] = (prop, signature)
        prop, signature = self.cache[key]
        b._screen(cls, name)
        if (kind is not None and signature[1] != kind) or (width is not None and signature[2] != width):
            raise refused("PROTECTED_MESH_PROPERTY_SCHEMA", property=name)
        return prop, signature

    def get(self, owner, name):
        _prop, signature = self.schema(type(owner), name)
        value = self.binding._raw(owner, name)
        if signature[2] in (0, None):
            expected = {"INT": int, "FLOAT": float, "BOOLEAN": bool, "ENUM": str, "STRING": str}.get(signature[1])
            if expected is not None and type(value) is not expected:
                raise refused("PROTECTED_MESH_SCALAR_TYPE", property=name)
        return value

    def items(self, owner, name, maximum):
        collection = self.get(owner, name)
        return self.copy(collection, maximum)

    def copy(self, collection, maximum):
        b = self.binding
        self.check()
        if type(collection) is not b.collection_type or b.length(collection) > maximum:
            raise refused("PROTECTED_MESH_COLLECTION_BUDGET")
        return b.items(collection)

    def count(self, owner, name, maximum):
        b = self.binding
        collection = self.get(owner, name)
        if type(collection) is not b.collection_type:
            raise refused("PROTECTED_MESH_COLLECTION_REQUIRED")
        return _integer(b.length(collection), maximum)

    def vector(self, owner, name, width):
        self.schema(type(owner), name, "FLOAT", width)
        value = self.binding.copy(self.get(owner, name))
        if len(value) != width:
            raise refused("PROTECTED_MESH_VECTOR_SHAPE")
        return [_float_bits(component) for component in value]

    def integers(self, owner, name, width, maximum):
        dynamic = name == "vertices" and type(owner) is self.cls("MeshPolygon")
        self.schema(type(owner), name, "INT", None if dynamic else width)
        values = self.binding.copy(self.get(owner, name))
        if len(values) != width:
            raise refused("PROTECTED_MESH_INDEX_SHAPE")
        return [_integer(value, maximum) for value in values]

    def identity(self, owner):
        if owner is None:
            return None
        b = self.binding
        uid = _integer(self.get(owner, "session_uid"), 2**64 - 1, minimum=1)
        pointer = _integer(b._pointer(owner), 2**64 - 1, minimum=1)
        return {"uid": uid, "pointer": pointer, "name": _text(self.get(owner, "name"), maximum=1024)}

    def collection_field(self, collection, cls, name):
        b = self.binding
        self.schema(self.cls(cls), name)
        if type(collection) is not b.collection_type:
            raise refused("PROTECTED_MESH_COLLECTION_REQUIRED")
        return b._access("protected_collection_field:" + name, b.collection_type.__getattribute__, collection, name)

    def attribute(self, mesh, expected):
        b = self.binding
        collection = self.get(mesh, "attributes")
        slot = vars(b.collection_type).get("get")
        if type(slot) is not MethodDescriptorType or slot.__objclass__ is not b.collection_type:
            raise refused("PROTECTED_MESH_LOOKUP_SLOT_CHANGED")
        attribute = b._access("protected_attribute_by_name", slot, collection, expected["name"])
        if attribute is None or _attribute_header(self, attribute, expected["count"]) != expected:
            raise refused("PROTECTED_MESH_ATTRIBUTE_REACQUISITION_CHANGED")
        return attribute

    def values(self, attribute, header):
        b = self.binding
        layout = LAYOUTS[header["data_type"]]
        self.schema(type(attribute), "data", "COLLECTION")
        if self.cache[(type(attribute), "data")][1][6] != layout.value_class:
            raise refused("PROTECTED_MESH_ATTRIBUTE_FIXED_TYPE")
        data = self.get(attribute, "data")
        count = header["count"]
        if type(data) is not b.collection_type or b.length(data) != count:
            raise refused("PROTECTED_MESH_ATTRIBUTE_DATA_LENGTH")
        leaf = self.cls(layout.value_class)
        self.schema(leaf, layout.field, layout.kind, layout.width)
        scalars = count * (layout.width or 1)
        if scalars <= 131072:
            raw = b.bulk_read(data, layout.value_class, layout.field, layout.kind, layout.width, count)
            rows = ([list(raw[index:index + layout.width]) for index in range(0, len(raw), layout.width)]
                    if layout.width else list(raw))
        else:
            rows = []
            for item in self.copy(data, count):
                if type(item) is not leaf:
                    raise refused("PROTECTED_MESH_ATTRIBUTE_LEAF_CLASS")
                value = self.get(item, layout.field)
                rows.append(list(b.copy(value)) if layout.width else value)
        def scalar(value):
            if layout.kind == "FLOAT":
                return _float_bits(value)
            if layout.kind == "BOOLEAN":
                return _boolean(value)
            return _integer(value, layout.maximum, minimum=layout.minimum)
        return [[scalar(value) for value in row] for row in rows] if layout.width else [scalar(value) for value in rows]


def _attribute_header(access, attribute, count):
    name = _text(access.get(attribute, "name"))
    domain, data_type = access.get(attribute, "domain"), access.get(attribute, "data_type")
    if type(domain) is not str or domain not in DOMAINS or type(data_type) is not str:
        raise refused("PROTECTED_MESH_ATTRIBUTE_DOMAIN_OR_TYPE")
    cls = type(attribute)
    native_class = access.binding._raw(access.binding._rna(cls), "identifier")
    native_class = _text(native_class, maximum=128)
    b = access.binding
    prop = b._access("protected_storage_descriptor", b._raw(b._rna(cls), "properties").get, "storage_type")
    if b.version_tuple[:2] == (5, 2):
        if prop is None:
            raise refused("PROTECTED_MESH_STORAGE_TYPE_REQUIRED")
        _prop, signature = access.schema(cls, "storage_type", "ENUM")
        if signature[5] is not True:
            raise refused("PROTECTED_MESH_STORAGE_TYPE_READONLY_REQUIRED")
        storage = access.get(attribute, "storage_type")
        if type(storage) is not str or storage not in {"ARRAY", "SINGLE"}:
            raise refused("PROTECTED_MESH_STORAGE_TYPE_UNKNOWN")
    else:
        if prop is not None:
            raise refused("PROTECTED_MESH_LEGACY_STORAGE_SCHEMA_CHANGED")
        storage = "LEGACY_ARRAY"
    layout = LAYOUTS.get(data_type)
    supported = layout is not None
    if supported and (cls is not access.cls(layout.attribute_class) or native_class != layout.attribute_class):
        raise refused("PROTECTED_MESH_ATTRIBUTE_CLASS")
    facts = []
    for field in ("name", "domain", "data_type", *(("storage_type",) if prop is not None else ())):
        _prop, signature = access.schema(cls, field)
        facts.append([field, list(signature[:-1])])
    if supported:
        _prop, signature = access.schema(cls, "data", "COLLECTION")
        if signature[6] != layout.value_class:
            raise refused("PROTECTED_MESH_ATTRIBUTE_FIXED_TYPE")
        facts.append(["data", list(signature[:-1])])
        leaf = access.cls(layout.value_class)
        _prop, signature = access.schema(leaf, layout.field, layout.kind, layout.width)
        facts.append([layout.value_class + "." + layout.field, list(signature[:-1])])
    return asdict(AttributeHeader(name, domain, data_type, native_class,
        None if layout is None else layout.value_class, storage, count, _digest(facts), supported))


def _headers(access, mesh):
    b = access.binding
    access.check()
    if type(mesh) is not access.cls("Mesh") or access.get(mesh, "is_editmode") is not False:
        raise refused("PROTECTED_ORIGINAL_OBJECT_MODE_MESH_REQUIRED")
    if access.get(mesh, "is_evaluated") is not False:
        raise refused("PROTECTED_EVALUATED_MESH_REFUSED")
    identity = access.identity(mesh)
    counts = {name: access.count(mesh, name, maximum) for name, maximum in COUNTS.items()}
    layers = access.items(mesh, "uv_layers", MAX_UV_MAPS)
    roles = []
    for layer in layers:
        if type(layer) is not access.cls("MeshUVLoopLayer"):
            raise refused("PROTECTED_MESH_UV_LAYER_CLASS")
        roles.append({"name": _text(access.get(layer, "name")),
                      **{field: _boolean(access.get(layer, field)) for field in ("active", "active_render", "active_clone")}})
    if len({row["name"] for row in roles}) != len(roles):
        raise refused("PROTECTED_MESH_DUPLICATE_UV_NAMES")
    uv_layers = access.get(mesh, "uv_layers")
    active = access.collection_field(uv_layers, "UVLoopLayers", "active_index")
    active = _integer(active, max(0, len(roles) - 1), minimum=-1)
    uv_roles = {"active_index": active, "clone_index": access.get(mesh, "uv_layer_clone_index"),
                "stencil_index": access.get(mesh, "uv_layer_stencil_index"), "layers": roles}
    for key in ("clone_index", "stencil_index"):
        _integer(uv_roles[key], max(0, len(roles) - 1), minimum=-1)
    rows = []
    for attribute in access.items(mesh, "attributes", MAX_ATTRIBUTES):
        domain = access.get(attribute, "domain")
        if type(domain) is not str or domain not in DOMAINS:
            raise refused("PROTECTED_MESH_ATTRIBUTE_DOMAIN_OR_TYPE")
        header = _attribute_header(access, attribute, counts[DOMAINS[domain]])
        if header["count"] != counts[DOMAINS[header["domain"]]]:
            raise refused("PROTECTED_MESH_ATTRIBUTE_DOMAIN_CHANGED")
        rows.append(header)
    rows.sort(key=lambda row: row["name"])
    if len({row["name"] for row in rows}) != len(rows):
        raise refused("PROTECTED_MESH_DUPLICATE_ATTRIBUTE")
    observed = {row["name"]: row for row in rows}
    for name, (domain, data_type) in CORE_ATTRIBUTES.items():
        if counts[DOMAINS[domain]] and (name not in observed or
                (observed[name]["domain"], observed[name]["data_type"]) != (domain, data_type)):
            raise refused("PROTECTED_MESH_PHYSICAL_CORE_STORAGE_REQUIRED")
    for layer in roles:
        row = observed.get(layer["name"])
        if row is None or (row["domain"], row["data_type"]) != ("CORNER", "FLOAT2"):
            raise refused("PROTECTED_MESH_PHYSICAL_UV_STORAGE_REQUIRED")
    schemas = {"material_index": ("FACE", "INT"), "custom_normal": ("CORNER", "INT16_2D")}
    for name, domain in ((".select_vert", "POINT"), (".hide_vert", "POINT"), (".select_edge", "EDGE"),
                         (".hide_edge", "EDGE"), ("uv_seam", "EDGE"), ("sharp_edge", "EDGE"),
                         (".select_poly", "FACE"), (".hide_poly", "FACE"), ("sharp_face", "FACE")):
        schemas[name] = domain, "BOOLEAN"
    for layer in roles:
        for prefix in ((".pn.", ".vs.", ".es.") if b.version_tuple[:2] == (4, 5) else (".pn.",)):
            schemas[prefix + layer["name"]] = "CORNER", "BOOLEAN"
    if b.version_tuple[:2] == (5, 2):
        schemas.update({".uv_select_vert": ("CORNER", "BOOLEAN"), ".uv_select_edge": ("CORNER", "BOOLEAN"),
                        ".uv_select_face": ("FACE", "BOOLEAN")})
    for name, schema in schemas.items():
        row = observed.get(name)
        if row is not None and (row["domain"], row["data_type"]) != schema:
            raise refused("PROTECTED_MESH_SEMANTIC_ATTRIBUTE_SCHEMA", attribute=name)
    auxiliary = []
    for layer in roles:
        for prefix in ((".pn.", ".vs.", ".es.") if b.version_tuple[:2] == (4, 5) else (".pn.",)):
            auxiliary.append([prefix + layer["name"], prefix + layer["name"] in observed])
    if roles and b.version_tuple[:2] == (5, 2):
        auxiliary.extend([name, name in observed] for name in (".uv_select_vert", ".uv_select_edge", ".uv_select_face"))
    return {"identity": identity, "counts": counts, "uv_roles": uv_roles,
            "materials": [access.identity(material) for material in access.items(mesh, "materials", MAX_MATERIALS)],
            "attributes": rows, "uv_auxiliary_presence": sorted(auxiliary),
            "shape_keys_ref": access.identity(access.get(mesh, "shape_keys"))}


def _fresh(access, mesh, expected):
    current = _headers(access, mesh)
    if current != expected:
        raise refused("PROTECTED_MESH_HEADERS_OR_OWNER_CHANGED")
    return current


def _safe_storage(headers):
    scalars = 0
    for row in headers["attributes"]:
        if row["storage"] == "SINGLE":
            raise refused("PROTECTED_MESH_SINGLE_REQUIRES_SEPARATE_PREPARATION", attribute=row["name"])
        if type(row["storage"]) is not str or row["storage"] not in {"ARRAY", "LEGACY_ARRAY"}:
            raise refused("PROTECTED_MESH_STORAGE_TYPE_UNKNOWN")
        if row["supported"] is not True or row["data_type"] not in LAYOUTS:
            raise refused("PROTECTED_MESH_ATTRIBUTE_KIND_UNQUALIFIED", attribute=row["name"], data_type=row["data_type"])
        layout = LAYOUTS[row["data_type"]]
        scalars += _integer(row["count"], max(COUNTS.values())) * (layout.width or 1)
    if scalars > MAX_SCALARS:
        raise refused("PROTECTED_MESH_COMPONENT_BUDGET")


def validate_header_profile(headers):
    """Pure reject-only admission for a detached complete header census.

    This cannot qualify or authorize native reads. capture_mesh independently
    reacquires and validates actual native headers immediately before use.
    A caller may census every protected Mesh and reject any SINGLE/unsupported
    storage before beginning geometry on the first Mesh.
    """
    if type(headers) is not dict or type(headers.get("attributes")) is not list:
        raise refused("PROTECTED_MESH_DETACHED_HEADER_SHAPE")
    for row in headers["attributes"]:
        if type(row) is not dict or any(type(name) is not str for name in row):
            raise refused("PROTECTED_MESH_DETACHED_HEADER_SHAPE")
    _safe_storage(headers)


class _Journal:
    """Bounded named cells count every declared read attempt and return."""

    def __init__(self):
        self.cells = {}

    def effect(self, kind, **facts):
        key = (kind, facts.get("mesh_uid"), facts.get("field"), facts.get("name"))
        cell = self.cells.get(key)
        if cell is None:
            if len(self.cells) >= 4096:
                raise refused("PROTECTED_MESH_READ_EFFECT_BUDGET")
            cell = {"index": len(self.cells), "kind": kind, "attempts_entered": 0, "attempts_returned": 0,
                    "last_attempt_returned": False, "logical_values_written": False,
                    "physical_pointer_stability_required": False, **facts}
            self.cells[key] = cell
        elif any(cell[name] != value for name, value in facts.items()):
            raise refused("PROTECTED_MESH_READ_EFFECT_DESCRIPTOR_CHANGED")
        return cell

    @staticmethod
    def enter(cell):
        cell["attempts_entered"] += 1
        cell["last_attempt_returned"] = False

    @staticmethod
    def returned(cell):
        cell["attempts_returned"] += 1
        cell["last_attempt_returned"] = True

    def counts(self):
        return {key: (cell["attempts_entered"], cell["attempts_returned"]) for key, cell in self.cells.items()}

    def report(self, before=None):
        rows = []
        for key, cell in self.cells.items():
            prior = (0, 0) if before is None else before.get(key, (0, 0))
            delta = cell["attempts_entered"]-prior[0], cell["attempts_returned"]-prior[1]
            if before is None or delta != (0, 0):
                rows.append({**cell, "entered_in_capture": delta[0], "returned_in_capture": delta[1]})
        # Detached ordinary JSON, including nested allowed-effect labels.
        return json.loads(_canonical(rows))



def _geometry(access, mesh, headers, journal):
    counts = headers["counts"]
    result = {}
    memberships = 0
    for field in ("vertices", "edges", "loops", "polygons"):
        _fresh(access, mesh, headers)
        if not counts[field]:
            # Do not invoke zero-domain for_write fallbacks merely to learn
            # an already observed zero count; absent core buffers stay absent.
            result[field] = []
            continue
        cell = journal.effect("EXISTING_ARRAY_GEOMETRY_READ", mesh_uid=headers["identity"]["uid"], field=field,
            allowed_effects=["BIT_PRESERVING_ARRAY_COW_UNSHARE", "NATIVE_CACHE_TAGGING"], count=counts[field])
        journal.enter(cell)
        elements = access.items(mesh, field, COUNTS[field])
        journal.returned(cell)
        if len(elements) != counts[field]:
            raise refused("PROTECTED_MESH_GEOMETRY_COUNT_CHANGED")
        rows = []
        group_cell = journal.effect("VERTEX_GROUP_READ", mesh_uid=headers["identity"]["uid"], count=counts["vertices"],
            allowed_effects=["BIT_PRESERVING_GROUP_BUFFER_COW_UNSHARE",
                "EMPTY_CD_MDEFORMVERT_CREATION_AND_LAYER_DESCRIPTOR_REALLOCATION"],
            build=list(access.binding.version_tuple)) if field == "vertices" else None
        for index, element in enumerate(elements):
            access.check()
            if _integer(access.get(element, "index"), max(0, counts[field] - 1)) != index:
                raise refused("PROTECTED_MESH_ELEMENT_INDEX")
            if field == "vertices":
                row = {"index": index, "co": access.vector(element, "co", 3),
                       "select": _boolean(access.get(element, "select")), "hide": _boolean(access.get(element, "hide"))}
                # No Attribute wrapper from the header pass remains alive here.
                journal.enter(group_cell)
                groups = access.items(element, "groups", MAX_GROUPS)
                journal.returned(group_cell)
                pairs = [[_integer(access.get(group, "group"), 2**31 - 1),
                          _float_bits(access.get(group, "weight"))] for group in groups]
                if len({pair[0] for pair in pairs}) != len(pairs):
                    raise refused("PROTECTED_MESH_DUPLICATE_WEIGHT_MEMBERSHIP")
                memberships += len(pairs)
                if memberships > MAX_MEMBERSHIPS:
                    raise refused("PROTECTED_MESH_WEIGHT_MEMBERSHIP_BUDGET")
                row["groups"] = pairs
            elif field == "edges":
                row = {"index": index, "vertices": access.integers(element, "vertices", 2, max(0, counts["vertices"] - 1)),
                       **{name: _boolean(access.get(element, name)) for name in
                          ("select", "hide", "use_seam", "use_edge_sharp")}}
            elif field == "loops":
                row = {"index": index, "vertex_index": _integer(access.get(element, "vertex_index"), max(0, counts["vertices"] - 1)),
                       "edge_index": _integer(access.get(element, "edge_index"), max(0, counts["edges"] - 1))}
            else:
                total = _integer(access.get(element, "loop_total"), counts["loops"], minimum=3)
                start = _integer(access.get(element, "loop_start"), counts["loops"])
                if start + total > counts["loops"]:
                    raise refused("PROTECTED_MESH_FACE_RANGE")
                row = {"index": index, "vertices": access.integers(element, "vertices", total, max(0, counts["vertices"] - 1)),
                       "loop_start": start, "loop_total": total,
                       "material_index": _integer(access.get(element, "material_index"), 32767),
                       **{name: _boolean(access.get(element, name)) for name in ("use_smooth", "select", "hide")}}
            rows.append(row)
        result[field] = rows
        _fresh(access, mesh, headers)
    return result


def _capture(access, mesh, journal):
    headers = _headers(access, mesh)
    _safe_storage(headers)  # Before the FIRST geometry/groups/data begin.
    geometry = _geometry(access, mesh, headers, journal)
    _fresh(access, mesh, headers)  # Empty DVERT may have moved native headers.
    values = {}
    for row in headers["attributes"]:
        _fresh(access, mesh, headers)
        if not row["count"]:
            values[row["name"]] = []
            continue
        attribute = access.attribute(mesh, row)  # Fresh by name/schema/storage.
        cell = journal.effect("EXISTING_ARRAY_ATTRIBUTE_READ", mesh_uid=headers["identity"]["uid"], name=row["name"], storage=row["storage"],
                       count=row["count"], allowed_effects=["BIT_PRESERVING_ARRAY_COW_UNSHARE"])
        journal.enter(cell)
        data = access.values(attribute, row)
        journal.returned(cell)
        values[row["name"]] = data
        del attribute
        _fresh(access, mesh, headers)
    # Independent native interfaces must agree on the complete core topology.
    if values.get("position", []) != [row["co"] for row in geometry["vertices"]]:
        raise refused("PROTECTED_MESH_POSITION_INTERFACE_DISAGREEMENT")
    if values.get(".edge_verts", []) != [row["vertices"] for row in geometry["edges"]]:
        raise refused("PROTECTED_MESH_EDGE_INTERFACE_DISAGREEMENT")
    if values.get(".corner_vert", []) != [row["vertex_index"] for row in geometry["loops"]]:
        raise refused("PROTECTED_MESH_CORNER_INTERFACE_DISAGREEMENT")
    if values.get(".corner_edge", []) != [row["edge_index"] for row in geometry["loops"]]:
        raise refused("PROTECTED_MESH_CORNER_EDGE_INTERFACE_DISAGREEMENT")
    layers = []
    present = {row["name"] for row in headers["attributes"]}
    for role in headers["uv_roles"]["layers"]:
        name = role["name"]
        four_five = access.binding.version_tuple[:2] == (4, 5)
        names = {"pin": ".pn." + name,
                 "vertex_select": ".vs." + name if four_five else ".uv_select_vert",
                 "edge_select": ".es." + name if four_five else ".uv_select_edge",
                 "face_select": None if four_five else ".uv_select_face"}
        auxiliary = {key: value if value in present else None for key, value in names.items()}
        pin_name = auxiliary["pin"]
        pins = [False] * headers["counts"]["loops"] if pin_name is None else values[pin_name]
        if len(pins) != headers["counts"]["loops"] or any(type(value) is not bool for value in pins):
            raise refused("PROTECTED_MESH_UV_PIN_SCHEMA")
        layers.append({**role, "auxiliary": auxiliary,
                       "data": [{"uv": uv, "pin_uv": pin} for uv, pin in zip(values[name], pins, strict=True)]})
    result = {**headers, "geometry": geometry, "attribute_values": values, "uv_layers": layers}
    result["authored_sha256"] = _digest(logical_projection(result))
    return result


class ProtectedMeshObserver:
    """Retain only detached observations/read-effects between synchronous calls."""

    def __init__(self, binding):
        if type(binding) is not NativeBinding:
            raise refused("PROTECTED_MESH_GENUINE_NATIVE_BINDING_REQUIRED")
        self.binding = binding
        self._binding_origin = binding
        self._journal = _Journal()
        self._check()

    def _check(self):
        if type(self) is not ProtectedMeshObserver or self.binding is not self._binding_origin or type(self.binding) is not NativeBinding:
            raise refused("PROTECTED_MESH_NATIVE_BINDING_CHANGED")
        if any(len(vars(cls)) != len(fields) or any(vars(cls).get(name) is not value for name, value in fields)
               for cls, fields in _CLASS_NAMESPACES):
            raise _SOURCE_CHANGED_FAILURE
        if (any(globals().get(name) is not function or function.__code__ is not code
                for name, function, code in _FUNCTION_ORIGINS)
                or any(vars(cls).get(name) is not raw or function.__code__ is not code
                       for cls, name, raw, function, code in _CLASS_METHOD_ORIGINS)
                or LAYOUTS is not _LAYOUTS_ORIGIN or COUNTS is not _COUNTS_ORIGIN
                or DOMAINS is not _DOMAINS_ORIGIN or CORE_ATTRIBUTES is not _CORE_ORIGIN):
            raise _SOURCE_CHANGED_FAILURE
        # The class/slot and method checks above precede these direct reads.
        # Compare every frozen layout field without dataclasses.asdict, whose
        # recursive deepcopy could enter a foreign value before rejecting it.
        for layout, facts in _LAYOUT_FACTS:
            if type(layout) is not _Layout:
                raise _SOURCE_CHANGED_FAILURE
            values = (layout.attribute_class, layout.value_class, layout.field, layout.kind,
                      layout.width, layout.minimum, layout.maximum)
            if (any(type(value) is not str for value in values[:4])
                    or any(type(value) is not int for value in values[4:])
                    or values != facts):
                raise _SOURCE_CHANGED_FAILURE
        gate = self.binding._runtime_gate
        if gate is not None:
            from .glb_stage_jobs import RuntimeNativeGate
            if type(gate) is not RuntimeNativeGate:
                raise refused("PROTECTED_MESH_CANONICAL_GATE_REQUIRED")
            gate.check()

    def capture_headers(self, mesh):
        access = _Access(self)
        result = _headers(access, mesh)
        access.check()
        self.binding.check()
        return result

    def capture_mesh(self, mesh):
        access = _Access(self)
        start = self._journal.counts()
        try:
            result = _capture(access, mesh, self._journal)
            access.check()
            self.binding.check()
            return {**result, "read_effects": self._journal.report(start),
                    "runtime_gate_bound": self.binding._runtime_gate is not None, "native_qualified": False}
        except Exception as cause:
            if isinstance(cause, BridgeError):
                raise
            raise refused("PROTECTED_MESH_OBSERVATION_FAILED", possible_read_effects=True) from cause

    def capture_object_groups(self, obj, mesh_projection):
        access = _Access(self)
        if type(obj) is not access.cls("Object") or access.get(obj, "type") != "MESH":
            raise refused("PROTECTED_MESH_OBJECT_REQUIRED")
        mesh = access.get(obj, "data")
        current = self.capture_mesh(mesh)
        if (current["identity"] != mesh_projection.get("identity")
                or current["authored_sha256"] != mesh_projection.get("authored_sha256")):
            raise refused("PROTECTED_MESH_GROUP_CAPTURE_BASELINE_CHANGED")
        definitions = []
        for index, group in enumerate(access.items(obj, "vertex_groups", MAX_GROUPS)):
            if access.get(group, "index") != index:
                raise refused("PROTECTED_MESH_GROUP_DEFINITION_INDEX")
            definitions.append({"index": index, "name": _text(access.get(group, "name")),
                                "lock_weight": _boolean(access.get(group, "lock_weight"))})
        _fresh(access, mesh, {key: current[key] for key in
            ("identity", "counts", "uv_roles", "materials", "attributes", "uv_auxiliary_presence", "shape_keys_ref")})
        result = {"object_identity": access.identity(obj), "mesh_identity": current["identity"],
                  "mesh_authored_sha256": current["authored_sha256"], "groups": definitions,
                  "memberships": [row["groups"] for row in current["geometry"]["vertices"]]}
        access.check()
        return result

    def report(self):
        # No native access, providers, schema getters or live wrappers here.
        return {"scope": "LOGICAL_AUTHORED_MESH_VALUES_WITH_DECLARED_PHYSICAL_READ_EFFECTS",
                "runtime_gate_bound": self.binding._runtime_gate is not None,
                "read_effects": self._journal.report(),
                "hidden_layout_or_cache_passivity_qualified": False,
                "copy_evidence": "SOURCE_EQUIVALENT_TYPED_LOGICAL_COPY_AND_COMPLETE_POSTREADBACK",
                "empirical_pre_COW_value_hash_observed": False,
                "arbitrary_NaN_or_padding_bit_preservation_qualified": False,
                "SINGLE_conversion_authorized": False, "native_qualified": False}


def capture_headers(binding, mesh):
    return ProtectedMeshObserver(binding).capture_headers(mesh)


def capture_mesh(binding, mesh):
    return ProtectedMeshObserver(binding).capture_mesh(mesh)


def capture_object_groups(binding, obj, mesh_projection):
    return ProtectedMeshObserver(binding).capture_object_groups(obj, mesh_projection)


_SOURCE_CHANGED_FAILURE = refused("PROTECTED_MESH_OBSERVER_SOURCE_CHANGED")
_LAYOUTS_ORIGIN, _COUNTS_ORIGIN, _DOMAINS_ORIGIN, _CORE_ORIGIN = LAYOUTS, COUNTS, DOMAINS, CORE_ATTRIBUTES
_LAYOUT_FACTS = tuple((layout, tuple(asdict(layout).values())) for layout in LAYOUTS.values())
_FUNCTION_ORIGINS = tuple((name, function, function.__code__) for name, function in tuple(globals().items())
                          if type(function) is FunctionType and function.__module__ == __name__)
_SOURCE_CLASSES = (_Layout, AttributeHeader, _Access, _Journal, ProtectedMeshObserver)
_CLASS_NAMESPACES = tuple((cls, tuple(vars(cls).items())) for cls in _SOURCE_CLASSES)
_CLASS_METHOD_ORIGINS = tuple((cls, name, raw, raw.__func__ if type(raw) is staticmethod else raw,
    (raw.__func__ if type(raw) is staticmethod else raw).__code__)
    for cls in _SOURCE_CLASSES for name, raw in vars(cls).items()
    if type(raw) is FunctionType or (type(raw) is staticmethod and type(raw.__func__) is FunctionType))
