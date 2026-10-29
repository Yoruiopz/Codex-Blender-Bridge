"""Unregistered private new-ID constructor, with modeled prefix conformance.

Native entry binds actual stock Blender in the reviewed owned-process fixture.
No Runtime, grants, automatic undo/save,
artist destination link or cleanup authority is supplied by this module.
"""
from __future__ import annotations

import inspect
import math
import struct
import time
from contextlib import suppress
from dataclasses import dataclass, field
from types import FunctionType
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument
from .glb_stage_profile import (
    NativeBinding,
    canonical,
    compile_profile,
    compose_channels,
    digest,
    f32,
    mesh_body,
    mesh_normal_body,
    mesh_uv_body,
    object_authored,
    plain,
    recipe_data,
    refused,
    validate_new_row,
)
from .glb_stage_state import GLBStageStore, StageIntent

_ENV_FAMILIES = ("collections", "meshes", "materials", "objects", "node_groups", "scenes", "worlds")
_CHANNELS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
             "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale")

_MESH_RETURN_OPERATIONS = frozenset({"BUILD_MESH", "NEW_UV_LAYER", "WRITE_NORMALS"})
_NEW_ID_OPERATIONS = frozenset({"NEW_COLLECTION", "NEW_MESH", "NEW_MATERIAL", "NEW_OBJECT"})
_F32_EPSILON = 2. ** -23
NORMAL_COMPONENT_BOUND = 5e-4  # Source short-angle quantization envelope; native evidence still required.


def _decode(bits):
    return struct.unpack("<f", bytes.fromhex(bits))[0]


def _matrix_projection(channels):
    return [f32(value) for row in compose_channels(channels["location"],
            channels["rotation_quaternion"], channels["scale"]) for value in row]


def _authored_projection(rows):
    """Only the native-computed basis is numerical evidence, never CAS authority.

    Every assigned channel, parent, inverse and complete custom-data component
    remains in the exact comparison. Excluding a derived matrix cannot authorize
    an edit to even one raw assigned Float32 channel.
    """
    result = plain(rows)
    for row in result.values():
        if row["kind"] == "object":
            del row["body"]["matrix"]
    return result


def _verify_basis(row):
    body = row["body"]
    if row["kind"] != "object":
        return
    wanted = compose_channels(body["channels"]["location"],
                              body["channels"]["rotation_quaternion"], body["channels"]["scale"])
    actual = body["matrix"]
    if type(actual) is not list or len(actual) != 16:
        raise refused("PRIVATE_BASIS_SHAPE")
    for index, expected in enumerate(value for values in wanted for value in values):
        # Independent comparison with the native matrix_basis C getter. This
        # source-derived Float32 operation envelope is a qualification target,
        # not a tolerance used to accept an authored channel drift.
        column = index % 4
        magnitude = max(abs(_decode(body["channels"]["scale"][column])), 1e-30) if column < 3 else max(abs(expected), 1e-30)
        bound = 32 * _F32_EPSILON * magnitude + 2. ** -148
        if abs(_decode(actual[index]) - expected) > bound:
            raise refused("PRIVATE_BASIS_CONFORMANCE_FAILED")


@dataclass(frozen=True, slots=True)
class _MeshReturnReceipt:
    """Immediate native-return evidence on a newly owned mesh, not authority.

    The private prototype captures before its next generic callback. It does
    not qualify queued cancellation during a native call; that integration needs
    a canonical pure lifetime/stop check before any further native read.
    """
    operation: str
    role: str
    stage_id: str
    before_sha256: str
    body: dict
    body_sha256: str


def _validate_mesh_custom_data(body):
    """Complete finite attribute inventory, with topology correspondences."""
    attributes = body["custom_data"]
    if type(attributes) is not dict or len(attributes) > 12:
        raise refused("PRIVATE_CUSTOM_DATA_INVENTORY")
    schema = {"position": ("POINT", "FLOAT_VECTOR", len(body["vertices"])),
              ".edge_verts": ("EDGE", "INT32_2D", len(body["edges"])),
              ".corner_vert": ("CORNER", "INT", len(body["loops"])),
              ".corner_edge": ("CORNER", "INT", len(body["loops"])),
              ".select_vert": ("POINT", "BOOLEAN", len(body["vertices"])),
              ".select_edge": ("EDGE", "BOOLEAN", len(body["edges"])),
              ".select_poly": ("FACE", "BOOLEAN", len(body["polygons"])),
              "sharp_face": ("FACE", "BOOLEAN", len(body["polygons"])),
              "sharp_edge": ("EDGE", "BOOLEAN", len(body["edges"])),
              "custom_normal": ("CORNER", "INT16_2D", len(body["loops"])),
              "material_index": ("FACE", "INT", len(body["polygons"])),
              "UVMap": ("CORNER", "FLOAT2", len(body["loops"]))}
    for name, item in attributes.items():
        if (name not in schema or type(item) is not dict or set(item) != {"domain", "type", "values"}
                or type(item["values"]) is not list
                or (item["domain"], item["type"], len(item["values"])) != schema[name]):
            raise refused("PRIVATE_CUSTOM_DATA_SCHEMA")
    for name, count in ((".select_vert", len(body["vertices"])), (".select_edge", len(body["edges"])),
                        (".select_poly", len(body["polygons"]))):
        selection = attributes.get(name)
        if count and selection is None:
            raise refused("PRIVATE_SELECTION_ATTRIBUTE_MISSING")
        if selection is not None and any(type(value) is not bool for value in selection["values"]):
            raise refused("PRIVATE_SELECTION_STORAGE_INVALID")
    if body["vertices"] and attributes.get("position", {}).get("values") != body["vertices"]:
        raise refused("PRIVATE_POSITION_ATTRIBUTE_CHANGED")
    if body["loops"] and attributes.get(".corner_vert", {}).get("values") != body["loops"]:
        raise refused("PRIVATE_CORNER_ATTRIBUTE_CHANGED")
    if body["edges"] and ".edge_verts" not in attributes:
        raise refused("PRIVATE_EDGE_ATTRIBUTE_MISSING")
    if body["loops"] and ".corner_edge" not in attributes:
        raise refused("PRIVATE_CORNER_EDGE_ATTRIBUTE_MISSING")
    if ".edge_verts" in attributes and sorted(sorted(edge) for edge in attributes[".edge_verts"]["values"]) != body["edges"]:
        raise refused("PRIVATE_EDGE_ATTRIBUTE_CHANGED")
    if ".corner_edge" in attributes:
        edges = attributes.get(".edge_verts", {}).get("values", [])
        for start, count in body["face_ranges"]:
            for offset in range(count):
                index = start + offset
                edge = attributes[".corner_edge"]["values"][index]
                if (type(edge) is not int or not 0 <= edge < len(edges)
                        or sorted(edges[edge]) != sorted((body["loops"][index], body["loops"][start + (offset + 1) % count]))):
                    raise refused("PRIVATE_CORNER_EDGE_CHANGED")
    if "sharp_face" in attributes and attributes["sharp_face"]["values"] != [not face[2] for face in body["polygons"]]:
        raise refused("PRIVATE_SHARP_FACE_CHANGED")
    if "material_index" in attributes and attributes["material_index"]["values"] != [face[1] for face in body["polygons"]]:
        raise refused("PRIVATE_MATERIAL_ATTRIBUTE_CHANGED")
    if body["normals"] is not None and not {"custom_normal", "sharp_edge"} <= attributes.keys():
        raise refused("PRIVATE_NORMAL_STORAGE_INCOMPLETE")
    if "custom_normal" in attributes and (body["normals"] is None or any(type(item) is not list
            or len(item) != 2 or any(type(value) is not int or not -32767 <= value <= 32767 for value in item)
            for item in attributes["custom_normal"]["values"])):
        raise refused("PRIVATE_NORMAL_STORAGE_INVALID")
    if body["uv"] is None:
        if "UVMap" in attributes:
            raise refused("PRIVATE_UNDECLARED_UV_ATTRIBUTE")
    elif attributes.get("UVMap", {}).get("values") != body["uv"]["vectors"]:
        raise refused("PRIVATE_UV_ATTRIBUTE_CHANGED")


def _validate_normal_conformance(body, mesh):
    normals = body["normals"]
    if type(normals) is not dict or set(normals) != {"decoded"} or len(normals["decoded"]) != len(body["loops"]):
        raise refused("PRIVATE_NORMAL_RETURN_SHAPE")
    logical = mesh_normal_body(mesh)
    if logical is None:
        raise refused("PRIVATE_UNDECLARED_NORMAL_RETURN")
    expected = logical["source"]
    for index, (values, present) in enumerate(zip(normals["decoded"], logical["present"], strict=True)):
        if type(values) is not list or len(values) != 3:
            raise refused("PRIVATE_NORMAL_RETURN_SHAPE")
        wanted = [_decode(value) for value in expected[index]]
        if not present:
            triangle = mesh.triangles[index // 3]
            a, b, c = (mesh.vertices[vertex] for vertex in triangle)
            first, second = [b[axis] - a[axis] for axis in range(3)], [c[axis] - a[axis] for axis in range(3)]
            wanted = [first[1] * second[2] - first[2] * second[1],
                      first[2] * second[0] - first[0] * second[2], first[0] * second[1] - first[1] * second[0]]
        length = math.hypot(*wanted)
        wanted = [value / length if length else 0. for value in wanted]
        if any(abs(_decode(value) - target) > NORMAL_COMPONENT_BOUND for value, target in zip(values, wanted, strict=True)):
            raise refused("PRIVATE_NORMAL_CONFORMANCE_FAILED")


class _Calls:
    """Pin trusted private/model implementations without invoking descriptors."""

    def __init__(self, operations):
        self.operations, self.cls = operations, type(operations)
        self.operations_origin = operations
        self.methods = {}
        names = ("version", "environment", "perform", "row", "_bind_stage", "take_footprint")
        if issubclass(self.cls, NativeOperations):
            if self.cls is not NativeOperations:
                raise refused("NATIVE_OPERATIONS_SUBCLASS_UNQUALIFIED")
            names += ("_blender", "_identity", "report")
            if any(inspect.getattr_static(self.cls, name, None) is not fn or fn.__code__ is not code
                   for name, fn, code in _NATIVE_METHOD_ORIGINS):
                raise refused("NATIVE_OPERATIONS_ORIGIN_CHANGED")
        for name in names:
            fn = inspect.getattr_static(self.cls, name, None)
            if type(fn) is not FunctionType:
                raise refused("PRIVATE_OPERATIONS_REQUIRE_PLAIN_METHODS")
            self.methods[name] = (fn, fn.__code__)

    def check(self):
        if self.operations is not self.operations_origin or type(self.operations) is not self.cls:
            raise refused("PRIVATE_OPERATIONS_CLASS_CHANGED")
        for name, (fn, code) in self.methods.items():
            if inspect.getattr_static(self.cls, name, None) is not fn or fn.__code__ is not code:
                raise refused("PRIVATE_OPERATIONS_METHOD_CHANGED")

    def call(self, name, *args):
        self.check()
        return self.methods[name][0](self.operations, *args)


@dataclass(slots=True)
class _Reference:
    value: Any
    uid: int | None = None
    pointer: int | None = None
    name: str | None = None
    admitted_return: bool = False


@dataclass(slots=True)
class _Stage:
    intent: StageIntent
    recipe: Any
    version: str
    references: dict[str, _Reference] = field(default_factory=dict)
    expected: dict[str, dict] = field(default_factory=dict)
    timings: list[dict] = field(default_factory=list)
    operation_started: bool = False
    failed: bool = False
    reference_origin: Any = field(init=False)
    reference_facts: tuple = ()
    expected_digest: str = field(default_factory=lambda: digest({}))
    conformance: dict = field(default_factory=dict)

    def __post_init__(self):
        self.reference_origin = self.references


class PrivateGLBController:
    """Trusted fixture/model engine; not a public permission or native adapter.

    The validation signal has no permission meaning. A fake operations object
    proves only model behavior; actual NativeOperations remains independently
    closed. Returned references are never recovered by name or integer lookup.
    """

    def __init__(self, store: GLBStageStore, operations, check):
        if type(store) is not GLBStageStore or type(check) is not FunctionType:
            raise refused("PRIVATE_CONTROLLER_INPUT")
        self._store, self._calls, self._check = store, _Calls(operations), check
        self._calls_origin = self._calls
        self._check_origin, self._check_code = check, check.__code__
        self._stages: dict[str, _Stage] = {}
        self._stages_origin = self._stages
        self._store_origin = store

    def _values(self, stage):
        return {role: ref.value for role, ref in stage.references.items()}

    def _bound(self, stage):
        if (self._store is not self._store_origin or self._calls is not self._calls_origin
                or self._check is not self._check_origin
                or self._check.__code__ is not self._check_code
                or self._stages is not self._stages_origin
                or self._stages.get(stage.intent.stage_id) is not stage
                or stage.references is not stage.reference_origin
                or self._reference_facts(stage) != stage.reference_facts
                or digest(stage.expected) != stage.expected_digest
                or self._store.lookup(stage.intent.stage_id).intent is not stage.intent
                or digest(recipe_data(stage.recipe)) != stage.recipe.recipe_sha256):
            raise refused("PRIVATE_STAGE_BINDING_CHANGED")
        self._calls.check()
        if self._calls.call("version") != stage.version:
            raise refused("PRIVATE_NATIVE_VERSION_CHANGED")

    def _reference_facts(self, stage):
        return tuple((key, id(ref), id(ref.value), ref.uid, ref.pointer, ref.name, ref.admitted_return)
                     for key, ref in stage.references.items())

    def _environment(self, stage):
        return plain(self._calls.call("environment", self._values(stage)))

    def _read(self, stage):
        return {role: plain(self._calls.call("row", role, ref.value, self._values(stage)))
                for role, ref in stage.references.items()}

    def _verify(self, stage):
        self._bound(stage)
        record = self._store.lookup(stage.intent.stage_id)
        if record.phase not in {"CONSTRUCTED", "PUBLISHED"}:
            GLBStageStore._writing(self._store, stage.intent.stage_id)
        if digest(self._environment(stage)) != stage.intent.destination_fingerprint:
            raise refused("PRIVATE_ENVIRONMENT_CHANGED")
        current = self._read(stage)
        if canonical(_authored_projection(current)) != canonical(_authored_projection(stage.expected)):
            raise refused("PRIVATE_OWNED_PREFIX_CHANGED")
        for row in current.values():
            _verify_basis(row)
            if row["kind"] == "mesh":
                _validate_mesh_custom_data(row["body"])
        if digest(self._environment(stage)) != stage.intent.destination_fingerprint:
            raise refused("PRIVATE_ENVIRONMENT_CHANGED_DURING_READ")
        self._bound(stage)

    def _boundary(self, stage):
        self._bound(stage)
        self._check_origin()
        self._verify(stage)

    def _observe_returns(self, stage, allocations, before_ids):
        if type(allocations) is not dict:
            raise refused("PRIVATE_ALLOCATION_RESULT")
        known = dict(stage.intent.allocation_names)
        for role, value in allocations.items():
            if type(role) is not str or role not in known:
                raise refused("UNEXPECTED_PRIVATE_ALLOCATION_ROLE")
            # Retain the genuine returned reference before any metadata read can
            # fail. This entry is explicitly unverified until all checks pass.
            ref = stage.references.get(role)
            if ref is None:
                stage.references[role] = _Reference(value)
            elif ref.value is not value or ref.admitted_return:
                raise refused("UNEXPECTED_PRIVATE_ALLOCATION_ROLE")
        new_rows = {}
        # Expected genuinely returned references were retained unadmitted by
        # _step before validating the complete result shape or reading metadata.
        for role in allocations:
            ref = stage.references[role]
            row = plain(self._calls.call("row", role, ref.value, self._values(stage)))
            if (type(row.get("uid")) is not int or type(row.get("pointer")) is not int
                    or row["uid"] in before_ids
                    or any(other.admitted_return and
                           (other.uid == row["uid"] or other.pointer == row["pointer"])
                           for other in stage.references.values() if other is not ref)):
                raise refused("RETURNED_ID_NOT_FRESH")
            index = role.split(":")[-1]
            tree = f"node_tree:{index}" if f"node_tree:{index}" in stage.references else None
            obj = next((o for o in stage.recipe.objects if role == f"object:{o.source_index}"), None)
            data_role = None if obj is None or obj.mesh_index is None else f"mesh:{obj.mesh_index}"
            # Embedded tree names are fixed by the pinned stock constructor.
            # Equal names do not confer ownership; fresh UID/pointer and role do.
            row = validate_new_row(role, known[role], row, material_tree=tree, data_role=data_role)
            ref.uid, ref.pointer, ref.name = row["uid"], row["pointer"], row["name"]
            ref.admitted_return = True
            new_rows[role] = row
        return new_rows

    def _mesh_return(self, stage, operation, role, data, prior):
        receipt = self._calls.call("take_footprint", operation, role)
        if (type(receipt) is not _MeshReturnReceipt or receipt.operation != operation or receipt.role != role
                or receipt.stage_id != stage.intent.stage_id or receipt.before_sha256 != digest(prior)
                or receipt.body_sha256 != digest(receipt.body)):
            raise refused("PRIVATE_MESH_RETURN_PROVENANCE")
        actual = plain(receipt.body)
        expected = mesh_body(data) if operation == "BUILD_MESH" else plain(prior)
        if operation == "BUILD_MESH":
            # The pinned native add/update sequence creates these selection
            # layers on newly owned storage. Their full observed bool values
            # must match the independently declared initial effect before any
            # return receipt can seed the exact future prefix/CAS projection.
            _validate_mesh_custom_data(actual)
            for name in (".select_vert", ".select_edge", ".select_poly"):
                if any(value is not True for value in actual["custom_data"][name]["values"]):
                    raise refused("PRIVATE_MESH_INITIAL_SELECTION_CHANGED")
            for face in expected["polygons"]:
                face[1] = 0
        elif operation == "NEW_UV_LAYER":
            expected["uv"] = {**mesh_uv_body(data), "vectors": [[f32(0.), f32(0.)] for _ in data.corner_uvs]}
            expected["uv"].update(clone_bound=stage.version == "4.5", stencil_bound=stage.version == "4.5")
        else:
            _validate_normal_conformance(actual, data)
            expected["normals"] = actual["normals"]
        # Only this immediate native-return receipt admits the declared new
        # mesh's derived storage; other fields keep their predicted prefix.
        expected["custom_data"] = actual["custom_data"]
        if canonical(actual) != canonical(expected):
            raise refused("PRIVATE_MESH_RETURN_FOOTPRINT_CHANGED")
        _validate_mesh_custom_data(actual)
        if operation != "BUILD_MESH":
            allowed = {"UVMap"} if operation == "NEW_UV_LAYER" else {"custom_normal", "sharp_edge"}
            if {name for name in actual["custom_data"] if name not in allowed} != set(prior["custom_data"]) - allowed:
                raise refused("PRIVATE_MESH_RETURN_UNDECLARED_ATTRIBUTES")
            if any(canonical(actual["custom_data"][name]) != canonical(value)
                   for name, value in prior["custom_data"].items() if name not in allowed):
                raise refused("PRIVATE_MESH_RETURN_PROTECTED_ATTRIBUTE_CHANGED")
        return actual

    def _advance(self, stage, operation, role, data, new_rows):
        desired = plain(stage.expected)
        desired.update(new_rows)
        if operation in _MESH_RETURN_OPERATIONS:
            desired[role]["body"] = self._mesh_return(stage, operation, role, data, stage.expected[role]["body"])
        elif operation == "WRITE_UV":
            target = mesh_uv_body(data)
            desired[role]["body"]["uv"] = target
            desired[role]["body"]["custom_data"]["UVMap"]["values"] = target["vectors"]
        elif operation == "UV_ROLE":
            desired[role]["body"]["uv"]["clone_bound" if data == "uv_layer_clone" else "stencil_bound"] = True
        elif operation == "INIT_MATERIAL":
            desired[role]["body"].update(use_nodes=True, tree="node_tree:" + role.split(":")[1])
        elif operation == "WRITE_PBR":
            desired[role]["body"].update(diffuse=list(data.color), backface=data.backface_culling)
            tree = "node_tree:" + str(data.index)
            desired[tree]["body"]["pbr"] = {"Base Color": list(data.color),
                "Metallic": [data.metallic], "Roughness": [data.roughness], "Alpha": [f32(1.)]}
        elif operation == "BIND_MATERIALS":
            names = [f"material:{i}" for i in data.material_indices]
            desired[role]["body"]["materials"] = names
            for face, slot in zip(desired[role]["body"]["polygons"], data.polygon_slots, strict=True):
                face[1] = slot
            desired[role]["body"]["custom_data"]["material_index"] = {
                "domain": "FACE", "type": "INT", "values": list(data.polygon_slots)}
            for name in names:
                desired[name]["users"] += 1
        elif operation == "NEW_OBJECT" and data is not None:
            desired[data]["users"] += 1
        elif operation == "LINK_OBJECT":
            desired[role]["body"]["objects"] = sorted([*desired[role]["body"]["objects"], data])
            desired[data]["body"]["collections"] = [role]
            desired[data]["users"] += 1
        elif operation == "OBJECT_FIELD":
            name, value = data
            body = desired[role]["body"]
            if name in {"location", "rotation_quaternion", "scale"}:
                body["channels"][name] = list(value)
                body["matrix"] = _matrix_projection(body["channels"])
            elif name == "parent":
                body["parent"] = value
                body["parent_inverse"] = [f32(float(i % 5 == 0)) for i in range(16)]
                desired[value]["body"]["children"] = sorted([*desired[value]["body"]["children"], role])
            elif name == "rotation_mode":
                body["rotation_mode"] = value
            elif name == "matrix_parent_inverse":
                body["parent_inverse"] = list(value)
            else:
                raise refused("PRIVATE_OBJECT_FIELD_UNQUALIFIED")
        return desired

    def _step(self, stage, operation, role, data):
        self._boundary(stage)
        # A second validation signal followed by a complete CAS makes a signal
        # mutation detectable; signals themselves are never mutation authority.
        self._boundary(stage)
        environment = self._environment(stage)
        before_ids = {row[1] for row in environment["ids"]}
        before_ids.update(ref.uid for ref in stage.references.values() if ref.uid is not None)
        stage.operation_started = True
        started = time.perf_counter()
        try:
            allocations = self._calls.call("perform", operation, role, data, self._values(stage),
                                          dict(stage.intent.allocation_names))
        finally:
            if type(self._calls.operations_origin) is NativeOperations:
                delivered = _NATIVE_DRAIN(self._calls.operations_origin, stage, operation, role)
                for key, value in delivered.items():
                    if key not in stage.references:
                        stage.references[key] = _Reference(value)
            stage.timings.append({"operation": operation, "role": role,
                                  "seconds": time.perf_counter() - started,
                                  "compound_step_interruptible": False})
        expected_allocations = {role} if operation in _NEW_ID_OPERATIONS else set()
        if operation == "NEW_MATERIAL" and stage.version == "5.2":
            expected_allocations.add("node_tree:" + role.split(":")[1])
        if operation == "INIT_MATERIAL" and stage.version == "4.5":
            expected_allocations = {"node_tree:" + role.split(":")[1]}
        plain_keys = (type(allocations) is dict and len(allocations) <= 2
                      and all(type(key) is str for key in allocations))
        if type(allocations) is dict:
            # Streaming exact-dict entries invokes no foreign key equality or
            # serializer. Retention is bounded by the <=2 expected roles even
            # when the complete returned result has the wrong cardinality.
            for key, value in allocations.items():
                if type(key) is str and key in expected_allocations and key not in stage.references:
                    stage.references[key] = _Reference(value)
        if not plain_keys or set(allocations) != expected_allocations:
            raise refused("PRIVATE_ALLOCATION_SET_CHANGED")
        new_rows = self._observe_returns(stage, allocations, before_ids)
        desired = self._advance(stage, operation, role, data, new_rows)
        # Never adopt a post-setter source/prefix. Constructor receipts belong
        # only to newly returned IDs and were validated above without callbacks.
        current = self._read(stage)
        if canonical(_authored_projection(current)) != canonical(_authored_projection(desired)):
            raise refused("PRIVATE_NATIVE_READBACK_MISMATCH")
        for row in current.values():
            _verify_basis(row)
        stage.expected = desired
        for key, ref in stage.references.items():
            ref.name = desired[key]["name"]
        stage.reference_facts = self._reference_facts(stage)
        stage.expected_digest = digest(desired)
        self._verify(stage)
        for key, ref in stage.references.items():
            row = stage.expected[key]
            if ref.admitted_return and row["name"] == dict(stage.intent.allocation_names)[key]:
                observed = self._store.lookup(stage.intent.stage_id).allocations
                if not any(a.role == key for a in observed):
                    GLBStageStore.note_allocation(self._store, stage.intent.stage_id, key,
                                                  row["name"], ref.uid, ref.pointer)
        GLBStageStore.note_prefix(self._store, stage.intent.stage_id, digest(stage.expected))

    def construct(self, preview_id, expected_fingerprint, accepted_losses):
        """Compatibility drain for the isolated private fixture, never an RPC."""
        steps = self.construct_steps(preview_id, expected_fingerprint, accepted_losses)
        while True:
            try:
                next(steps)
            except StopIteration as completed:
                return completed.value

    def construct_steps(self, preview_id, expected_fingerprint, accepted_losses):
        # Resolve only a sealed existing lookup; no name/ad-hoc object lookup.
        if type(preview_id) is not str or preview_id not in self._store._previews:
            raise invalid_argument("Private construction requires a retained preview.")
        record = self._store.lookup(self._store._previews[preview_id])
        recipe = compile_profile(record.intent.plan)  # Unsupported cases stop before operations.
        version = self._calls.call("version")
        if version not in ("4.5", "5.2"):
            raise refused("PRIVATE_NATIVE_VERSION_UNQUALIFIED")
        environment = plain(self._calls.call("environment", {}))
        if environment.get("mode") != "OBJECT" or environment.get("active_type") == "VOLUME":
            raise refused("PRIVATE_SURFACE_CONTEXT_REQUIRED")
        if digest(environment) != record.intent.destination_fingerprint:
            raise refused("PRIVATE_DESTINATION_WITNESS_CHANGED")
        self._check_origin()
        if digest(self._calls.call("environment", {})) != record.intent.destination_fingerprint:
            raise refused("PRIVATE_DESTINATION_WITNESS_CHANGED_AFTER_SIGNAL")
        record = GLBStageStore.begin(self._store, preview_id, expected_fingerprint, accepted_losses)
        stage = _Stage(record.intent, recipe, version)
        self._stages[record.intent.stage_id] = stage
        try:
            self._calls.call("_bind_stage", stage)
            self._step(stage, "NEW_COLLECTION", "collection", None)
            yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
            for mesh in recipe.meshes:
                role = f"mesh:{mesh.source_index}"
                self._step(stage, "NEW_MESH", role, None)
                yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
                self._step(stage, "BUILD_MESH", role, mesh)
                yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
                if mesh.corner_uvs is not None:
                    self._step(stage, "NEW_UV_LAYER", role, mesh)
                    yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
                    for name, flag in (("uv_layer_clone", "clone_bound"), ("uv_layer_stencil", "stencil_bound")):
                        if not stage.expected[role]["body"]["uv"][flag]:
                            self._step(stage, "UV_ROLE", role, name)
                            yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
                    self._step(stage, "WRITE_UV", role, mesh)
                    yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
                if mesh.corner_normals is not None:
                    self._step(stage, "WRITE_NORMALS", role, mesh)
                    yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
            for material in recipe.materials:
                role = f"material:{material.index}"
                self._step(stage, "NEW_MATERIAL", role, None)
                yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
                self._step(stage, "INIT_MATERIAL", role, None)
                yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
                self._step(stage, "WRITE_PBR", role, material)
                yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
            for mesh in recipe.meshes:
                self._step(stage, "BIND_MATERIALS", f"mesh:{mesh.source_index}", mesh)
                yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
            for obj in recipe.objects:
                role = f"object:{obj.source_index}"
                self._step(stage, "NEW_OBJECT", role, None if obj.mesh_index is None else f"mesh:{obj.mesh_index}")
                yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
                self._step(stage, "LINK_OBJECT", "collection", role)
                yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
            for obj in recipe.objects:
                role = f"object:{obj.source_index}"
                authored = object_authored(obj)
                for name in ("rotation_mode", "location", "rotation_quaternion", "scale", "matrix_parent_inverse"):
                    body = stage.expected[role]["body"]
                    current = body["channels"].get(name) if name in body["channels"] else body.get(
                        "parent_inverse" if name == "matrix_parent_inverse" else name)
                    if current != authored[name]:
                        self._step(stage, "OBJECT_FIELD", role, (name, authored[name]))
                        yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
            for obj in recipe.objects:
                if obj.parent_index is not None:
                    self._step(stage, "OBJECT_FIELD", f"object:{obj.source_index}", ("parent", f"object:{obj.parent_index}"))
                    yield {"operation": stage.timings[-1]["operation"], "role": stage.timings[-1]["role"]}
            self._verify_worlds(stage)
            self._boundary(stage)
            GLBStageStore.finish(self._store, stage.intent.stage_id, published=False)
            return self.retained(stage.intent.stage_id)
        except Exception as cause:
            stage.failed = True
            # A reset may already have retained an explicitly stale record.
            with suppress(BridgeError):
                GLBStageStore.fail(self._store, stage.intent.stage_id, "PRIVATE_CONSTRUCTION_FAILED",
                                   outcome_unknown=stage.operation_started)
            raise BridgeError(cause.code if isinstance(cause, BridgeError) else ErrorCode.OPERATION_FAILED,
                "Private GLB construction did not complete; retained effects require inspection.",
                {**self.retained(stage.intent.stage_id), "possible_mutation": stage.operation_started,
                 "cause": cause.to_dict() if isinstance(cause, BridgeError) else {"code": "OPERATION_FAILED"}}) from cause


    def _verify_worlds(self, stage):
        self._boundary(stage)
        rows, worlds, errors = self._read(stage), {}, {}
        objects = {obj.source_index: obj for obj in stage.recipe.objects}
        def calculate(index):
            if index in worlds:
                return worlds[index], errors[index]
            obj = objects[index]
            body = rows[f"object:{index}"]["body"]
            _verify_basis(rows[f"object:{index}"])
            local = tuple(tuple(_decode(value) for value in body["matrix"][4 * row:4 * row + 4]) for row in range(4))
            local_error = tuple(tuple(64 * _F32_EPSILON * max(abs(obj.local_matrix[row][column]),
                abs(_decode(obj.scale[column])) if column < 3 else 1e-30) + 2. ** -148
                for column in range(4)) for row in range(4))
            if obj.parent_index is None:
                world, error = local, local_error
            else:
                parent, parent_error = calculate(obj.parent_index)
                world = tuple(tuple(sum(parent[row][k] * local[k][column] for k in range(4))
                                    for column in range(4)) for row in range(4))
                error = tuple(tuple(sum(abs(parent[row][k]) * local_error[k][column]
                    + parent_error[row][k] * abs(local[k][column]) + parent_error[row][k] * local_error[k][column]
                    for k in range(4)) for column in range(4)) for row in range(4))
            if any(abs(world[row][column] - obj.world_matrix[row][column]) > error[row][column]
                   for row in range(4) for column in range(4)):
                raise refused("PRIVATE_WORLD_CONFORMANCE_FAILED")
            worlds[index], errors[index] = world, error
            return world, error
        max_error, checked = 0., 0
        mesh_map = {mesh.source_index: mesh for mesh in stage.recipe.meshes}
        for obj in stage.recipe.objects:
            world, error = calculate(obj.source_index)
            max_error = max(max_error, *(abs(world[r][c] - obj.world_matrix[r][c]) for r in range(4) for c in range(4)))
            if obj.mesh_index is not None:
                for vertex in mesh_map[obj.mesh_index].vertices:
                    vector = (*vertex, 1.)
                    for row in range(3):
                        actual = sum(world[row][k] * vector[k] for k in range(4))
                        target = sum(obj.world_matrix[row][k] * vector[k] for k in range(4))
                        if abs(actual - target) > sum(error[row][k] * abs(vector[k]) for k in range(4)) + 1e-12 * max(1., abs(target)):
                            raise refused("PRIVATE_WORLD_GEOMETRY_CONFORMANCE_FAILED")
                    checked += 1
        stage.conformance = {"authored_channels_exact": True, "all_nodes": len(objects),
            "all_instance_vertices": checked, "world_matrix_max_absolute_error": max_error,
            "comparison": "native matrix_basis plus authored parent chain against Float64 plan",
            "depsgraph_evaluated_world_qualified": False, "queued_stop_during_native_return_capture_qualified": False}

    def verify_retained(self, stage_id):
        """Exact new-owned CAS under the current canonical Runtime turn gate."""
        stage = self._stages.get(stage_id)
        if stage is None:
            raise refused("GLB_CONSTRUCTED_REFERENCE_UNAVAILABLE")
        self._boundary(stage)
        self._verify_worlds(stage)

    def publish(self, stage_id, scene):
        stage = self._stages.get(stage_id)
        if stage is None or self._store.lookup(stage_id).phase != "PUBLISHING":
            raise refused("GLB_PUBLICATION_BINDING_REQUIRED")
        self._boundary(stage)
        desired = plain(stage.expected)
        desired["collection"]["users"] += 1
        stage.operation_started = True
        operations = self._calls.operations
        if type(operations) is not NativeOperations:
            raise refused("GLB_PUBLICATION_REQUIRES_GENUINE_NATIVE_OPERATIONS")
        operations.publish_collection(scene, stage.references["collection"].value)
        # The expected one-user delta is declared before readback. It never
        # derives from a post-link baseline; all other complete rows stay exact.
        current = self._read(stage)
        if canonical(_authored_projection(current)) != canonical(_authored_projection(desired)):
            raise refused("GLB_PUBLICATION_OWNED_DELTA_CHANGED")
        stage.expected = desired
        stage.expected_digest = digest(desired)
        stage.reference_facts = self._reference_facts(stage)
        self._verify(stage)
        return digest(desired)

    def retained(self, stage_id):
        stage = self._stages.get(stage_id)
        if stage is None:
            raise invalid_argument("Unknown private stage; no native name lookup is performed.")
        return {"stage_id": stage_id, "state": self._store.inspect(stage_id), "structural_conformance": plain(stage.conformance),
                "known_returned_references": [{"role": role, "uid": ref.uid, "pointer": ref.pointer,
                    "last_observed_name": ref.name, "admitted_constructor_return": ref.admitted_return}
                    for role, ref in stage.references.items()],
                "timings": plain(stage.timings), "last_prefix_sha256": digest(stage.expected),
                "live_native_reinspection_performed": False, "native_qualified": False,
                "artist_destination_preservation_qualified": False, "destination_linked": False,
                "project_saved": False, "durable_recovery_verified": False,
                "native_cleanup_performed": False}


_NO_RETURN = object()


@dataclass(slots=True)
class _ReturnEscrow:
    """Genuine delivered references only; no native getter on retention/drain."""
    stage: Any
    operation: str
    role: str
    expected: tuple[str, ...]
    references: dict = field(default_factory=dict)
    drained: bool = False

    def __post_init__(self):
        if (type(self.expected) is not tuple or len(self.expected) > 2
                or any(type(role) is not str for role in self.expected)
                or len(set(self.expected)) != len(self.expected)):
            raise refused("NATIVE_RETURN_ESCROW_SHAPE")
        # Allocate keys before native entry. Recording a delivered pointer only
        # replaces an existing value; diagnostics can fail without losing it.
        self.references = dict.fromkeys(self.expected, _NO_RETURN)

    def remember(self, role, value):
        if (self.drained or type(role) is not str or role not in self.expected
                or self.references[role] is not _NO_RETURN):
            raise refused("NATIVE_RETURN_ESCROW_SHAPE")
        self.references[role] = value

    def drain(self, stage, operation, role):
        if self.stage is not stage or operation != self.operation or role != self.role or self.drained:
            raise refused("NATIVE_RETURN_ESCROW_BINDING")
        result = {role: value for role, value in self.references.items() if value is not _NO_RETURN}
        self.drained = True
        return result


class NativeOperations:
    """Actual stock-bpy adapter; internal binding confers no public authority."""

    __slots__ = (
        "_binding",
        "_binding_origin",
        "_defaults",
        "_entries",
        "_footprint_history",
        "_footprints",
        "_operation",
        "_pending",
        "_returns",
        "_role",
        "_runtime_gate",
        "_stage",
        "_stage_origins",
    )

    def __init__(self, *, runtime_gate=None):
        if runtime_gate is not None:
            from .glb_stage_jobs import RuntimeNativeGate
            if type(runtime_gate) is not RuntimeNativeGate:
                raise refused("GLB_CANONICAL_NATIVE_GATE_REQUIRED")
        self._runtime_gate = runtime_gate
        self._binding = NativeBinding(runtime_gate=runtime_gate)
        self._binding_origin = self._binding
        self._stage, self._pending = None, None
        self._stage_origins = []
        self._returns, self._entries, self._defaults = [], [], {}
        self._footprints = {}
        self._footprint_history = []
        self._operation, self._role = "BOOTSTRAP", ""

    def _blender(self):
        if self._binding is not self._binding_origin:
            raise refused("NATIVE_ADAPTER_BINDING_CHANGED")
        if self._runtime_gate is not None:
            self._runtime_gate.check()
        self._binding.check()
        return self._binding.bpy

    def _bind_stage(self, stage):
        self._blender()
        if type(stage) is not _Stage or (self._pending is not None and not self._pending.drained):
            raise refused("NATIVE_STAGE_BINDING")
        if not any(previous is stage for previous in self._stage_origins):
            if len(self._stage_origins) >= 16:
                raise refused("NATIVE_STAGE_RETENTION_CAPACITY")
            self._stage_origins.append(stage)
        self._stage = stage

    def _entry(self, label, function, *args, capture_role=None, **kwargs):
        self._blender()
        if len(self._entries) >= 2048:
            raise refused("NATIVE_ENTRY_REPORT_BUDGET")
        gate = self._runtime_gate
        if gate is not None:
            gate.check()
        # Reserve the attempt before C, including none-returning writes and
        # exceptional returns. This cell never disappears after an entry.
        row = {"index": len(self._entries), "operation": self._operation,
               "role": self._role, "entry": label, "entered": True,
               "returned": False, "post_return_stop_checked": False,
               "seconds": 0., "interruptible": False,
               "started_monotonic": time.monotonic(), "returned_monotonic": None}
        self._entries.append(row)
        started = time.perf_counter()
        try:
            result = function(*args, **kwargs)
            # The genuine constructor ref is escrowed before ANY fallible
            # metadata, diagnostics, permission provider or stop check.
            if capture_role is not None:
                self._pending.remember(capture_role, result)
            row["returned"] = True
            row["returned_monotonic"] = time.monotonic()
            if gate is not None:
                gate.check()
                row["post_return_stop_checked"] = True
            return result
        finally:
            row["seconds"] = time.perf_counter() - started

    def version(self):
        self._blender()
        return ".".join(str(v) for v in self._binding.version_tuple[:2])

    def _identity(self, value):
        self._blender()
        binding = self._binding
        if binding.base not in type(value).__mro__ or binding.classes["ID"] not in type(value).__mro__:
            raise refused("NATIVE_ID_REQUIRED")
        uid, pointer = binding.get(value, "session_uid"), binding._pointer(value)
        if type(uid) is not int or type(pointer) is not int or not 0 < uid < 2**64 or not 0 < pointer < 2**64:
            raise refused("NATIVE_IDENTITY_REQUIRED")
        return uid, pointer

    def _items(self, owner, name, limit):
        collection = self._binding.get(owner, name)
        if type(collection) is not self._binding.collection_type or self._binding.length(collection) > limit:
            raise refused("NATIVE_COLLECTION_BUDGET")
        return self._binding.items(collection)

    def environment(self, owned):
        self._blender()
        b = self._binding
        omitted = {self._identity(value)[0] for value in owned.values()}
        ids = []
        for family in _ENV_FAMILIES:
            values = self._items(b.main, family, 4096)
            if len(ids) + len(values) > 4096:
                raise refused("PRIVATE_ID_INVENTORY_BUDGET")
            for value in values:
                uid, pointer = self._identity(value)
                if uid not in omitted:
                    ids.append((family, uid, pointer))
        layer, scene = b.get(b.context, "view_layer"), b.get(b.context, "scene")
        active = b.get(b.get(layer, "objects"), "active")
        return {"main": b.main_pointer, "filepath": b.get(b.main, "filepath"), "scene": self._identity(scene)[0],
            "mode": b.get(b.context, "mode"), "active": None if active is None else self._identity(active)[0],
            "active_type": None if active is None else b.get(active, "type"),
            "selection": sorted(self._identity(obj)[0] for obj in b.selected()),
            "frame": b.get(scene, "frame_current"), "subframe": f32(b.get(scene, "frame_subframe")),
            "ids": sorted(ids)}

    def _remember(self, role, value):
        # First Python action after the actual constructor return. No descriptor,
        # UID, version, node_tree or other dependent getter precedes retention.
        self._pending.remember(role, value)
        return value

    def _drain_returns(self, stage, operation, role):
        # Deliberately pure: called even after binding/context/getter failure.
        pending = self._pending
        if pending is None or pending.drained:
            return {}
        result = pending.drain(stage, operation, role)
        self._returns.append(pending)
        return result

    def take_footprint(self, operation, role):
        # Pure handoff; never re-read after a callback, stop or failed capture.
        return self._footprints.pop((operation, role), None)

    def _capture_mesh_return(self, operation, role, before, owned):
        # RNA attribute-data reads may materialize native storage, including
        # 5.2 SINGLE values. This is an owned constructor effect captured here,
        # never a read-only artist-inspection or representation-passivity claim.
        body = self._entry("mesh_return.complete_read_attempt", self.row, role, owned[role], owned)["body"]
        _validate_mesh_custom_data(body)
        receipt = _MeshReturnReceipt(operation, role,
            self._stage.intent.stage_id, before, plain(body), digest(body))
        if len(self._footprint_history) >= 2048:
            raise refused("NATIVE_RETURN_RECEIPT_CAPACITY")
        self._footprints[(operation, role)] = receipt
        self._footprint_history.append({"stage_id": receipt.stage_id, "operation": operation,
            "role": role, "before_sha256": before, "body_sha256": receipt.body_sha256,
            "capture_returned": True, "captured_before_generic_callback": True,
            "queued_stop_during_capture_qualified": False})

    def _new(self, family, role, name, *args):
        b = self._binding
        # Collection Python wrappers need not retain object identity. Reacquire
        # only through the held Main and screened native property path.
        owner = b.get(b.main, family)
        current = b.callable(owner, "BlendData" + family.capitalize(), "new")
        if type(current) is not b.function_type:
            raise refused("NATIVE_CONSTRUCTOR_BINDING_CHANGED")
        return self._entry(family + ".new", current, name, *args, capture_role=role)

    def _method(self, owner, class_name, method, *args, **kwargs):
        fn = self._binding.callable(owner, class_name, method)
        return self._entry(class_name + "." + method, fn, *args, **kwargs)

    def _bulk(self, mesh, field, attribute, values):
        if type(values) is not tuple or len(values) > 131072:
            raise refused("NATIVE_BULK_ARGUMENT_BUDGET")
        cls = self._binding.classes["MeshVertex" if field == "vertices" else "MeshPolygon"]
        kind, width = {"co": ("FLOAT", 3), "loop_start": ("INT", 0), "vertices": ("INT", "*"),
                       "use_smooth": ("BOOLEAN", 0), "material_index": ("INT", 0)}[attribute]
        self._binding.field(cls, attribute, kind, width, writing=True)
        collection = self._binding.get(mesh, field)
        if type(collection) is not self._binding.collection_type:
            raise refused("NATIVE_BULK_OWNER_REQUIRED")
        return self._entry(field + ".foreach_set:" + attribute, self._binding.foreach,
                           collection, attribute, values)

    def _set(self, owner, field, value):
        self._binding.prepare_set(owner, field)
        return self._entry(type(owner).__name__ + "." + field, self._binding.setter, owner, field, value)

    def perform(self, operation, role, data, owned, names):
        self._blender()
        stage = self._stage
        if (stage is None or names != dict(stage.intent.allocation_names)
                or (self._pending is not None and not self._pending.drained)):
            raise refused("NATIVE_OPERATION_STAGE_CHANGED")
        self._operation, self._role = operation, role
        expected = (role,) if operation in _NEW_ID_OPERATIONS else ()
        tree = "node_tree:" + role.split(":")[-1]
        family = self.version()
        if operation == "NEW_MATERIAL" and family == "5.2":
            expected += (tree,)
        if operation == "INIT_MATERIAL" and family == "4.5":
            expected = (tree,)
        self._pending = _ReturnEscrow(stage, operation, role, expected)
        b, result = self._binding, {}
        before_mesh = digest(stage.expected[role]["body"]) if operation in _MESH_RETURN_OPERATIONS else None
        if operation == "NEW_COLLECTION":
            result[role] = self._new("collections", role, names[role])
        elif operation == "NEW_MESH":
            result[role] = self._new("meshes", role, names[role])
        elif operation == "BUILD_MESH":
            mesh = owned[role]
            for field, cls, count in (("vertices", "MeshVertices", len(data.vertices)),
                    ("loops", "MeshLoops", 3 * len(data.triangles)),
                    ("polygons", "MeshPolygons", len(data.triangles))):
                self._method(b.get(mesh, field), cls, "add", count)
            self._bulk(mesh, "vertices", "co", tuple(v for vertex in data.vertices for v in vertex))
            self._bulk(mesh, "polygons", "loop_start", tuple(3 * i for i in range(len(data.triangles))))
            self._bulk(mesh, "polygons", "vertices", tuple(v for face in data.triangles for v in face))
            self._bulk(mesh, "polygons", "use_smooth", (False,) * len(data.triangles))
            self._method(mesh, "Mesh", "update", calc_edges=True)
        elif operation == "NEW_UV_LAYER":
            mesh = owned[role]
            layer = self._method(b.get(mesh, "uv_layers"), "UVLoopLayers", "new", name="UVMap", do_init=False)
            if type(layer) is not b.classes["MeshUVLoopLayer"]:
                raise refused("NATIVE_NEW_UV_LAYER_CLASS")
        elif operation == "WRITE_UV":
            mesh = owned[role]
            layers = self._items(mesh, "uv_layers", 1)
            if len(layers) != 1 or b.get(layers[0], "name") != "UVMap":
                raise refused("NATIVE_UV_LAYER_CHANGED")
            b.field(b.classes["Float2AttributeValue"], "vector", "FLOAT", 2, writing=True)
            collection = b.get(layers[0], "uv")
            if type(collection) is not b.collection_type or b.length(collection) != len(data.corner_uvs):
                raise refused("NATIVE_UV_SHAPE_CHANGED")
            self._entry("uv.foreach_set:vector", b.foreach, collection, "vector", tuple(value for pair in data.corner_uvs for value in pair))
        elif operation == "UV_ROLE":
            if data not in {"uv_layer_clone", "uv_layer_stencil"}:
                raise refused("NATIVE_UV_ROLE_UNQUALIFIED")
            layers = self._items(owned[role], "uv_layers", 1)
            if len(layers) != 1 or type(layers[0]) is not b.classes["MeshUVLoopLayer"]:
                raise refused("NATIVE_UV_LAYER_CHANGED")
            self._set(owned[role], data, layers[0])
        elif operation == "WRITE_NORMALS":
            if data.corner_normals is None or len(data.corner_normals) != 3 * len(data.triangles):
                raise refused("NATIVE_NORMAL_INPUT_SHAPE")
            self._method(owned[role], "Mesh", "normals_split_custom_set", tuple(data.corner_normals))
        elif operation == "NEW_MATERIAL":
            result[role] = self._new("materials", role, names[role])
            if family == "5.2":
                result[tree] = self._shader_tree_return(b.get(result[role], "node_tree", escrow=self._pending, capture_role=tree))
        elif operation == "INIT_MATERIAL":
            if family == "4.5":
                self._set(owned[role], "use_nodes", True)
                result[tree] = self._shader_tree_return(b.get(owned[role], "node_tree", escrow=self._pending, capture_role=tree))
        elif operation == "WRITE_PBR":
            material = owned[role]
            self._set(material, "diffuse_color", tuple(struct.unpack("<f", bytes.fromhex(v))[0] for v in data.color))
            self._set(material, "use_backface_culling", data.backface_culling)
            node = next(n for n in self._items(owned["node_tree:" + str(data.index)], "nodes", 2)
                        if type(n) is b.classes["ShaderNodeBsdfPrincipled"])
            values = {"Base Color": data.color, "Metallic": (data.metallic,),
                      "Roughness": (data.roughness,), "Alpha": (f32(1.),)}
            for identifier, bits in values.items():
                socket = next(s for s in self._items(node, "inputs", 128) if b.get(s, "identifier") == identifier)
                decoded = tuple(struct.unpack("<f", bytes.fromhex(v))[0] for v in bits)
                self._set(socket, "default_value", decoded if len(decoded) > 1 else decoded[0])
        elif operation == "BIND_MATERIALS":
            for index in data.material_indices:
                self._method(b.get(owned[role], "materials"), "IDMaterials", "append", owned[f"material:{index}"])
            self._bulk(owned[role], "polygons", "material_index", data.polygon_slots)
        elif operation == "NEW_OBJECT":
            result[role] = self._new("objects", role, names[role], None if data is None else owned[data])
        elif operation == "LINK_OBJECT":
            self._method(b.get(owned[role], "objects"), "CollectionObjects", "link", owned[data])
        elif operation == "OBJECT_FIELD":
            name, value = data
            if name == "parent":
                value = owned[value]
            elif name in {"location", "rotation_quaternion", "scale", "matrix_parent_inverse"}:
                value = tuple(_decode(bits) for bits in value)
                if name == "matrix_parent_inverse":
                    value = tuple(value[4 * row:4 * row + 4] for row in range(4))
            elif name != "rotation_mode":
                raise refused("NATIVE_OBJECT_FIELD_UNQUALIFIED")
            self._set(owned[role], name, value)
        else:
            raise refused("UNKNOWN_PRIVATE_OPERATION")
        if operation in _MESH_RETURN_OPERATIONS:
            # No generic permission/provider/check callback or event-loop yield
            # occurs between the returned C operation and this exact receipt.
            # Cancellation during this private compound return is unqualified.
            self._capture_mesh_return(operation, role, before_mesh, owned)
        return result

    def _shader_tree_return(self, value):
        # The actual returned embedded tree has already entered genuine escrow
        # and passed the FIRST pure post-return stop check. No socket/graph read
        # precedes this exact class and readonly SHADER discriminator.
        b = self._binding
        if type(value) is not b.classes["ShaderNodeTree"] or b.get(value, "type") != "SHADER":
            raise refused("NATIVE_RETURNED_SHADER_TREE_REQUIRED")
        return value

    def publish_collection(self, scene, collection):
        self._blender()
        if self._runtime_gate is None:
            raise refused("GLB_PUBLICATION_CANONICAL_GATE_REQUIRED")
        b = self._binding
        if type(scene) is not b.classes["Scene"] or type(collection) is not b.classes["Collection"]:
            raise refused("GLB_PUBLICATION_NATIVE_TYPES_REQUIRED")
        self._operation, self._role = "PUBLISH_COLLECTION", "collection"
        root = b.get(scene, "collection")
        children = b.get(root, "children")
        link = b.callable(children, "CollectionChildren", "link")
        self._entry("CollectionChildren.link", link, collection)

    def _boolean_input(self, socket):
        # Stock 5.2 Principled adds Thin Wall. Preserve its boolean storage as a
        # boolean; numeric equality/coercion must not hide a type or value drift.
        self._binding.field(type(socket), "default_value", "BOOLEAN", 0)
        value = self._binding.get(socket, "default_value")
        if type(value) is not bool:
            raise refused("NATIVE_BOOLEAN_SOCKET_REQUIRED")
        return [value]

    def _collections_using(self, obj, owner_role):
        # Object.users_collection is a Python helper in both official modules.
        # Its sourced algorithm is implemented with screened native fields here,
        # including embedded Scene masters, without executing that property.
        b = self._binding
        collections = list(self._items(b.main, "collections", 4096))
        collections.extend(b.get(scene, "collection") for scene in self._items(b.main, "scenes", 32))
        target, result, count = self._identity(obj), [], 0
        for collection in collections:
            objects = self._items(collection, "objects", 4096)
            count += len(objects)
            if count > 16384:
                raise refused("NATIVE_COLLECTION_CONSUMER_BUDGET")
            if any(self._identity(item) == target for item in objects):
                result.append(owner_role(collection))
        return sorted(result)

    def _attributes(self, mesh):
        b = self._binding
        kinds = {"FLOAT_VECTOR": ("FloatVectorAttribute", "FloatVectorAttributeValue", "vector", "FLOAT", 3),
                 "FLOAT2": ("Float2Attribute", "Float2AttributeValue", "vector", "FLOAT", 2),
                 "INT": ("IntAttribute", "IntAttributeValue", "value", "INT", 0),
                 "INT32_2D": ("Int2Attribute", "Int2AttributeValue", "value", "INT", 2),
                 "INT16_2D": ("Short2Attribute", "Short2AttributeValue", "value", "INT", 2),
                 "BOOLEAN": ("BoolAttribute", "BoolAttributeValue", "value", "BOOLEAN", 0)}
        result = {}
        for attribute in self._items(mesh, "attributes", 12):
            name, kind, domain = (b.get(attribute, field) for field in ("name", "data_type", "domain"))
            if type(name) is not str or name in result or kind not in kinds:
                raise refused("NATIVE_CUSTOM_ATTRIBUTE_UNQUALIFIED")
            attr_class, element_class, field, numeric_kind, width = kinds[kind]
            if type(attribute) is not b.classes[attr_class]:
                raise refused("NATIVE_CUSTOM_ATTRIBUTE_CLASS")
            collection = b.get(attribute, "data")
            if type(collection) is not b.collection_type:
                raise refused("NATIVE_ATTRIBUTE_DATA_CLASS")
            values = b.bulk_read(collection, element_class, field, numeric_kind, width, b.length(collection))
            if numeric_kind == "FLOAT":
                values = tuple(f32(value) for value in values)
            if width:
                values = [list(values[index:index + width]) for index in range(0, len(values), width)]
            else:
                values = list(values)
            result[name] = {"domain": domain, "type": kind, "values": values}
        return result

    def _mesh_uv(self, mesh, attributes):
        b = self._binding
        layers = self._items(mesh, "uv_layers", 1)
        if not layers:
            return None
        if (len(layers) != 1 or type(layers[0]) is not b.classes["MeshUVLoopLayer"]
                or b.get(layers[0], "name") != "UVMap" or b.get(layers[0], "active") is not True
                or b.get(layers[0], "active_render") is not True or "UVMap" not in attributes):
            raise refused("NATIVE_UV_ROLE_CHANGED")
        roles = {}
        for name in ("clone", "stencil"):
            selected = b.get(mesh, "uv_layer_" + name)
            if selected is not None and (type(selected) is not b.classes["MeshUVLoopLayer"]
                    or b._pointer(selected) != b._pointer(layers[0])):
                raise refused("NATIVE_UV_ROLE_POINTER_CHANGED")
            roles[name + "_bound"] = selected is not None
        if b.get(layers[0], "active_clone") is not roles["clone_bound"]:
            raise refused("NATIVE_UV_CLONE_ROLE_CHANGED")
        return {"name": "UVMap", "vectors": attributes["UVMap"]["values"], "active": 0, "render": 0,
                "clone": b.get(mesh, "uv_layer_clone_index"), "stencil": b.get(mesh, "uv_layer_stencil_index"), **roles}

    def _mesh_normals(self, mesh):
        b = self._binding
        if not b.get(mesh, "has_custom_normals"):
            return None
        collection = b.get(mesh, "corner_normals")
        values = b.bulk_read(collection, "MeshNormalValue", "vector", "FLOAT", 3, b.length(collection))
        return {"decoded": [[f32(value) for value in values[index:index + 3]] for index in range(0, len(values), 3)]}

    def _children_using(self, parent, owner_role):
        b, result = self._binding, []
        for obj in self._items(b.main, "objects", 4096):
            candidate = b.get(obj, "parent")
            if candidate is not None and b._pointer(candidate) == b._pointer(parent):
                result.append(owner_role(obj))
        return sorted(result)

    def row(self, role, value, owned):
        self._blender()
        b, kind = self._binding, role.split(":")[0]
        expected_class = {"collection": "Collection", "mesh": "Mesh", "material": "Material",
                          "object": "Object", "node_tree": "ShaderNodeTree"}.get(kind)
        if expected_class is None or type(value) is not b.classes[expected_class]:
            raise refused("NATIVE_RETURN_CLASS_CHANGED")
        uid, pointer = self._identity(value)
        def owner_role(target):
            if target is None:
                return None
            target_uid = self._identity(target)[0]
            matches = [key for key, item in owned.items() if self._identity(item)[0] == target_uid]
            if len(matches) != 1:
                raise refused("FOREIGN_PRIVATE_CONSUMER")
            return matches[0]
        if b.get(value, "library") is not None or b.get(value, "override_library") is not None:
            raise refused("PRIVATE_RETURN_LINKED_OR_OVERRIDE")
        get = b.get
        if kind == "collection":
            body = {"objects": sorted(owner_role(o) for o in self._items(value, "objects", 32)),
                    "children": sorted(owner_role(c) for c in self._items(value, "children", 0))}
        elif kind == "mesh":
            vertices = self._items(value, "vertices", 8192)
            loops = self._items(value, "loops", 24576)
            polygons = self._items(value, "polygons", 8192)
            faces = []
            for polygon in polygons:
                corners = get(polygon, "vertices")
                if type(corners) is not b.array_type or b.length(corners) != 3:
                    raise refused("NATIVE_TRIANGLE_CORNERS_REQUIRED")
                faces.append([list(b.copy(corners)), get(polygon, "material_index"), get(polygon, "use_smooth")])
            attributes = self._attributes(value)
            body = {"vertices": [[f32(v) for v in b.vector(vertex, "co", 3)] for vertex in vertices],
                    "loops": [get(loop, "vertex_index") for loop in loops],
                    "face_ranges": [[get(p, "loop_start"), get(p, "loop_total")] for p in polygons],
                    "polygons": faces,
                    "edges": sorted([sorted(b.copy(get(edge, "vertices"))) for edge in self._items(value, "edges", 24576)]),
                    "materials": [owner_role(m) for m in self._items(value, "materials", 16)],
                    "custom_data": attributes, "uv": self._mesh_uv(value, attributes), "normals": self._mesh_normals(value)}
        elif kind == "material":
            body = {"diffuse": [f32(v) for v in b.vector(value, "diffuse_color", 4)],
                    "use_nodes": get(value, "use_nodes"), "tree": owner_role(get(value, "node_tree")),
                    "backface": get(value, "use_backface_culling")}
        elif kind == "object":
            matrix = get(value, "matrix_basis")
            if type(matrix) is not b.matrix_type or b.length(matrix) != 4:
                raise refused("NATIVE_MATRIX_REQUIRED")
            body = {"data": owner_role(get(value, "data")), "parent": owner_role(get(value, "parent")),
                    "matrix": [f32(v) for row in b.copy(matrix) for v in b.copy(row)],
                    "rotation_mode": get(value, "rotation_mode"), "parent_type": get(value, "parent_type"),
                    "parent_inverse": [f32(v) for row in b.copy(get(value, "matrix_parent_inverse")) for v in b.copy(row)],
                    "channels": {field: [f32(v) for v in b.vector(value, field, 4 if field in {
                        "rotation_quaternion", "rotation_axis_angle", "delta_rotation_quaternion"} else 3)] for field in _CHANNELS},
                    "collections": self._collections_using(value, owner_role), "children": self._children_using(value, owner_role)}
        else:
            self._shader_tree_return(value)
            layout, other, pbr, outputs = [], [], {}, []
            def node_kind(node):
                for name in ("ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial"):
                    if type(node) is b.classes[name]:
                        return name
                raise refused("NATIVE_DEFAULT_NODE_REQUIRED")
            for node in self._items(value, "nodes", 2):
                node_name = node_kind(node)
                layout.append([node_name, get(node, "name"), [f32(v) for v in b.vector(node, "location", 2)],
                               f32(get(node, "width")), get(node, "mute")])
                if node_name == "ShaderNodeOutputMaterial":
                    outputs.append(node)
                for socket in self._items(node, "inputs", 128):
                    socket_kind, identifier = get(socket, "type"), get(socket, "identifier")
                    if socket_kind == "SHADER":
                        bits = None
                    elif socket_kind == "BOOLEAN":
                        bits = self._boolean_input(socket)
                    elif socket_kind == "VALUE":
                        b.field(type(socket), "default_value", "FLOAT", 0)
                        bits = [f32(get(socket, "default_value"))]
                    elif socket_kind in {"RGBA", "VECTOR"}:
                        bits = [f32(v) for v in b.vector(socket, "default_value", 4 if socket_kind == "RGBA" else 3)]
                    else:
                        raise refused("UNQUALIFIED_SHADER_SOCKET")
                    if node_name == "ShaderNodeBsdfPrincipled" and identifier in {"Base Color", "Metallic", "Roughness", "Alpha"}:
                        if identifier in pbr:
                            raise refused("DUPLICATE_PBR_SOCKET")
                        pbr[identifier] = bits
                    else:
                        other.append([node_name, identifier, socket_kind, bits])
            if len(outputs) != 1:
                raise refused("SURFACE_DEFAULT_GRAPH_REQUIRED")
            body = {"layout": sorted(layout), "other_inputs": sorted(other), "pbr": pbr,
                    "active_output": get(outputs[0], "is_active_output"), "output_target": get(outputs[0], "target"),
                    "links": sorted([node_kind(get(link, "from_node")), get(get(link, "from_socket"), "identifier"),
                                     node_kind(get(link, "to_node")), get(get(link, "to_socket"), "identifier")]
                                    for link in self._items(value, "links", 1))}
        row = {"name": get(value, "name"), "kind": kind, "uid": uid, "pointer": pointer,
               "users": get(value, "users"), "fake_user": get(value, "use_fake_user"), "body": body}
        key = (self._stage.intent.stage_id if self._stage is not None else "", role)
        if key not in self._defaults:
            self._defaults[key] = plain(row)
        return row

    def report(self):
        return {"build": {"version": list(self._binding.version_tuple), "build_hash": self._binding.build_hash.decode("ascii")},
                "binding": self._binding.report(), "native_entries": plain(self._entries),
                "mesh_return_receipts": plain(self._footprint_history),
                "native_storage_effects": {
                    "scope": "NEW_OWNED_PRIVATE_CONSTRUCTOR_STORAGE",
                    "implicit_selection_layers": [".select_vert", ".select_edge", ".select_poly"],
                    "attribute_data_reads_may_materialize_storage": True,
                    "blender_5_2_SINGLE_materialization_in_scope": self._binding.version_tuple[:2] == (5, 2),
                    "single_materialization_observed": False,
                    "artist_read_only_inspection_qualified": False,
                    "representation_level_passivity_qualified": False},
                "publication_physical_effects": {
                    "declared_native_link_effects": ["MAIN_WIDE_COLLECTION_LAYER_BASE_SYNC", "LOCAL_VIEW_COLLECTION_SYNC"],
                    "main_wide_sync_may_have_run": any(row["entry"] == "CollectionChildren.link" and row["entered"] for row in self._entries),
                    "hidden_layout_or_cache_passivity_qualified": False},
                "return_capture_lifetime_check_qualified": False,
                "canonical_per_entry_stop_gate_bound": self._runtime_gate is not None,
                "native_access_counts": ({} if self._runtime_gate is None else self._runtime_gate.snapshot()),
                "constructor_defaults": [{"stage_id": stage, "role": role, "row": plain(row)}
                                         for (stage, role), row in self._defaults.items()],
                "pending_returns": [{"stage_id": escrow.stage.intent.stage_id, "operation": escrow.operation,
                    "role": escrow.role, "returned_roles": [role for role, value in escrow.references.items() if value is not _NO_RETURN], "drained": escrow.drained}
                    for escrow in (*self._returns, *((self._pending,) if self._pending is not None and not any(escrow is self._pending for escrow in self._returns) else ()))],
                "native_acceptance_established": False}


_NATIVE_METHOD_ORIGINS = tuple((name, fn, fn.__code__) for name, fn in vars(NativeOperations).items()
                             if type(fn) is FunctionType)
_NATIVE_DRAIN = NativeOperations._drain_returns
