"""Trusted plain models exercise private scheduling, never native acceptance."""
from __future__ import annotations

import copy
import importlib
import math
import struct
from dataclasses import dataclass

import pytest
from test_asset_glb_import_plan import glb, triangle


@dataclass
class ModelID:
    name: str
    kind: str
    uid: int
    pointer: int
    users: int
    body: dict


class ModelOperations:
    def __init__(self, version):
        self._version = version
        self.ids = {}
        self.counter = 10
        self.events = []
        self.ambient_revision = 0
        self.active_type = "MESH"
        self.fail_before = None
        self.fail_after = None
        self.corrupt = None
        self.foreign_return = False
        self.volume_graph = False
        self.result_fault = None
        self.footprints = {}

    def _bind_stage(self, stage):
        self.stage = stage

    def take_footprint(self, operation, role):
        return self.footprints.pop((operation, role), None)

    def _capture_footprint(self, operation, role, body):
        prior = self.stage.expected[role]["body"]
        self.footprints[(operation, role)] = self.driver._MeshReturnReceipt(operation, role,
            self.stage.intent.stage_id, self.driver.digest(prior), copy.deepcopy(body), self.driver.digest(body))

    @staticmethod
    def _basis(channels):
        def decode(values):
            return [struct.unpack("<f", bytes.fromhex(value))[0] for value in values]
        location, (w, x, y, z), scale = (decode(channels[name]) for name in ("location", "rotation_quaternion", "scale"))
        length = math.sqrt(w*w + x*x + y*y + z*z)
        w, x, y, z = (value / length for value in (w, x, y, z))
        rotation = [[1-2*y*y-2*z*z, 2*x*y-2*z*w, 2*x*z+2*y*w],
                    [2*x*y+2*z*w, 1-2*x*x-2*z*z, 2*y*z-2*x*w],
                    [2*x*z-2*y*w, 2*y*z+2*x*w, 1-2*x*x-2*y*y]]
        matrix = [[rotation[row][column] * scale[column] for column in range(3)] + [location[row]] for row in range(3)]
        matrix.append([0., 0., 0., 1.])
        return [struct.pack("<f", value).hex() for row in matrix for value in row]

    @staticmethod
    def _topology_attributes(body):
        edges = body["edges"]
        corner_edges = []
        for start, count in body["face_ranges"]:
            for offset in range(count):
                pair = sorted((body["loops"][start + offset], body["loops"][start + (offset + 1) % count]))
                corner_edges.append(edges.index(pair))
        return {"position": {"domain": "POINT", "type": "FLOAT_VECTOR", "values": copy.deepcopy(body["vertices"])},
                ".edge_verts": {"domain": "EDGE", "type": "INT32_2D", "values": copy.deepcopy(edges)},
                ".corner_vert": {"domain": "CORNER", "type": "INT", "values": list(body["loops"])},
                ".corner_edge": {"domain": "CORNER", "type": "INT", "values": corner_edges},
                "sharp_face": {"domain": "FACE", "type": "BOOLEAN", "values": [not face[2] for face in body["polygons"]]},
                ".select_vert": {"domain": "POINT", "type": "BOOLEAN", "values": [True] * len(body["vertices"])},
                ".select_edge": {"domain": "EDGE", "type": "BOOLEAN", "values": [True] * len(body["edges"])},
                ".select_poly": {"domain": "FACE", "type": "BOOLEAN", "values": [True] * len(body["polygons"])}}

    def version(self):
        return self._version

    def environment(self, owned):
        omitted = {v.uid for v in owned.values()}
        return {"mode": "OBJECT", "active_type": self.active_type,
                "ambient_revision": self.ambient_revision,
                "ids": sorted((v.kind, v.uid, v.pointer) for v in self.ids.values() if v.uid not in omitted)}

    def _new(self, role, name, body):
        self.counter += 1
        value = ModelID(name, role.split(":")[0], self.counter, 1000 + self.counter, 0, body)
        self.ids[value.uid] = value
        return value

    def _tree(self, role):
        if self.result_fault == "aliased_tree":
            existing = next((value for value in self.ids.values() if value.kind == "node_tree"), None)
            if existing is not None:
                return existing
        kind = "ShaderNodeVolumePrincipled" if self.volume_graph else "ShaderNodeBsdfPrincipled"
        name = "unexpected" if self.result_fault == "wrong_tree_name" else "Shader Nodetree"
        row = self._new(role, name, {
            "layout": [[kind, "Principled", [], "00000000", False],
                       ["ShaderNodeOutputMaterial", "Output", [], "00000000", False]],
            "other_inputs": [["ShaderNodeBsdfPrincipled", "IOR", "VALUE", ["0000c03f"]]],
            "active_output": True, "output_target": "ALL",
            "pbr": {"Base Color": ["0000803f"] * 4, "Metallic": ["00000000"],
                    "Roughness": ["0000003f"], "Alpha": ["0000803f"]},
            "links": [[kind, "BSDF", "ShaderNodeOutputMaterial", "Surface"]]})
        if self._version == "5.2":
            row.body["other_inputs"].append(["ShaderNodeBsdfPrincipled", "Thin Wall", "BOOLEAN", [False]])
        return row

    def row(self, role, value, owned):
        return {"name": value.name, "kind": value.kind, "uid": value.uid,
                "pointer": value.pointer, "users": value.users, "fake_user": False,
                "body": copy.deepcopy(value.body)}

    def perform(self, operation, role, data, owned, names):
        from struct import pack

        if self.fail_before == operation:
            raise RuntimeError("injected before operation")
        self.events.append(operation)
        result = {}
        if operation == "NEW_COLLECTION":
            result[role] = self._new(role, names[role], {"objects": [], "children": []})
        elif operation == "NEW_MESH":
            if self.foreign_return:
                result[role] = next(iter(self.ids.values()))
            else:
                result[role] = self._new(role, names[role], {**{k: [] for k in (
                    "vertices", "loops", "face_ranges", "polygons", "edges", "materials")},
                    "uv": None, "normals": None, "custom_data": {}})
        elif operation == "BUILD_MESH":
            edges = set()
            for a, b, c in data.triangles:
                edges.update((tuple(sorted((a, b))), tuple(sorted((b, c))), tuple(sorted((a, c)))))
            owned[role].body = {
                "vertices": [[pack("<f", c).hex() for c in v] for v in data.vertices],
                "loops": [v for face in data.triangles for v in face],
                "face_ranges": [[3 * i, 3] for i in range(len(data.triangles))],
                "polygons": [[list(face), 0, False] for face in data.triangles],
                "edges": [list(edge) for edge in sorted(edges)], "materials": [],
                "uv": None, "normals": None, "custom_data": {}}
            if self.corrupt == operation:
                owned[role].body["vertices"][-1][-1] = "00000000"
            elif self.corrupt == "face_ranges":
                owned[role].body["face_ranges"][-1] = [0, 0]
            owned[role].body["custom_data"] = self._topology_attributes(owned[role].body)
        elif operation == "NEW_UV_LAYER":
            vectors = [[pack("<f", 0.).hex()] * 2 for _ in data.corner_uvs]
            owned[role].body["uv"] = {"name": "UVMap", "vectors": vectors, "active": 0, "render": 0, "clone": 0, "stencil": 0,
                "clone_bound": self._version == "4.5", "stencil_bound": self._version == "4.5"}
            owned[role].body["custom_data"]["UVMap"] = {"domain": "CORNER", "type": "FLOAT2", "values": copy.deepcopy(vectors)}
        elif operation == "WRITE_UV":
            vectors = [[pack("<f", value).hex() for value in pair] for pair in data.corner_uvs]
            owned[role].body["uv"]["vectors"] = vectors
            owned[role].body["custom_data"]["UVMap"]["values"] = copy.deepcopy(vectors)
        elif operation == "UV_ROLE":
            owned[role].body["uv"]["clone_bound" if data == "uv_layer_clone" else "stencil_bound"] = True
        elif operation == "WRITE_NORMALS":
            values = []
            for index, normal in enumerate(data.corner_normals):
                if not data.corner_normal_present[index]:
                    a, b, c = (data.vertices[vertex] for vertex in data.triangles[index // 3])
                    u, v = [b[k] - a[k] for k in range(3)], [c[k] - a[k] for k in range(3)]
                    normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
                length = math.sqrt(sum(value*value for value in normal))
                values.append([pack("<f", value / length if length else 0.).hex() for value in normal])
            owned[role].body["normals"] = {"decoded": values}
            owned[role].body["custom_data"]["custom_normal"] = {"domain": "CORNER", "type": "INT16_2D", "values": [[0, 1] for _ in values]}
            owned[role].body["custom_data"]["sharp_edge"] = {"domain": "EDGE", "type": "BOOLEAN", "values": [False] * len(owned[role].body["edges"])}
        elif operation == "NEW_MATERIAL":
            tree = "node_tree:" + role.split(":")[1]
            result[role] = self._new(role, names[role], {"diffuse": ["0000803f"] * 4,
                "backface": False, "use_nodes": self._version == "5.2",
                "tree": tree if self._version == "5.2" else None})
            if self._version == "5.2":
                result[tree] = self._tree(tree)
        elif operation == "INIT_MATERIAL":
            if self._version == "4.5":
                tree = "node_tree:" + role.split(":")[1]
                result[tree] = self._tree(tree)
                owned[role].body.update(use_nodes=True, tree=tree)
        elif operation == "WRITE_PBR":
            owned[role].body.update(diffuse=list(data.color), backface=data.backface_culling)
            owned[f"node_tree:{data.index}"].body["pbr"] = {
                "Base Color": list(data.color), "Metallic": [data.metallic],
                "Roughness": [data.roughness], "Alpha": ["0000803f"]}
        elif operation == "BIND_MATERIALS":
            roles = [f"material:{i}" for i in data.material_indices]
            owned[role].body["materials"] = roles
            for value in roles:
                owned[value].users += 1
            for face, slot in zip(owned[role].body["polygons"], data.polygon_slots, strict=True):
                face[1] = slot
            owned[role].body["custom_data"]["material_index"] = {"domain": "FACE", "type": "INT", "values": list(data.polygon_slots)}
        elif operation == "NEW_OBJECT":
            result[role] = self._new(role, names[role], {"data": data, "parent": None,
                "matrix": ["0000803f" if i % 5 == 0 else "00000000" for i in range(16)],
                "channels": {**{key: [pack("<f", 0.).hex()] * 3 for key in ("location", "rotation_euler", "delta_location", "delta_rotation_euler")},
                    **{key: [pack("<f", 1.).hex()] * 3 for key in ("scale", "delta_scale")},
                    **{key: [pack("<f", value).hex() for value in (1., 0., 0., 0.)] for key in ("rotation_quaternion", "delta_rotation_quaternion")},
                    "rotation_axis_angle": [pack("<f", value).hex() for value in (0., 0., 1., 0.)]},
                "rotation_mode": "XYZ", "parent_type": "OBJECT", "parent_inverse": [pack("<f", float(i % 5 == 0)).hex() for i in range(16)],
                "children": [], "collections": []})
            if data is not None:
                owned[data].users += 1
        elif operation == "LINK_OBJECT":
            owned[role].body["objects"] = sorted([*owned[role].body["objects"], data])
            owned[data].body["collections"] = [role]
            owned[data].users += 1
        elif operation == "OBJECT_FIELD":
            name, value = data
            body = owned[role].body
            if name in {"location", "rotation_quaternion", "scale"}:
                body["channels"][name] = list(value)
                body["matrix"] = self._basis(body["channels"])
            elif name == "parent":
                body["parent"] = value
                owned[value].body["children"] = sorted([*owned[value].body["children"], role])
            elif name == "matrix_parent_inverse":
                body["parent_inverse"] = list(value)
            else:
                body[name] = value
        else:
            raise AssertionError(operation)
        if operation in {"BUILD_MESH", "NEW_UV_LAYER", "WRITE_NORMALS"}:
            self._capture_footprint(operation, role, owned[role].body)
        if self.fail_after == operation:
            raise RuntimeError("injected after possible native effects")
        if self.result_fault == "missing_tree" and operation == "NEW_MATERIAL":
            return {role: result[role]}
        if self.result_fault == "extra_key" and operation == "NEW_MESH":
            return {**result, "unexpected": object()}
        if self.result_fault == "extra_two_keys" and operation == "NEW_MESH":
            return {**result, "unexpected": object(), "another": object()}
        return result


@pytest.fixture
def modules(addon_package):
    return tuple(importlib.import_module(addon_package + "." + name) for name in (
        "glb_stage_profile", "glb_stage_driver", "glb_stage_source", "glb_stage_state"))


def prepared(modules, tmp_path, version="4.5", *, manifest=None, binary=None):
    profile, driver, source, state = modules
    if manifest is None:
        manifest, binary = triangle()
    path = tmp_path / "source.glb"
    path.write_bytes(glb(manifest, binary))
    snapshot = source.read_glb_source(str(path), str(tmp_path))
    ops, store = ModelOperations(version), state.GLBStageStore()
    ops.driver = driver
    record = store.prepare(snapshot, "Private Asset", profile.digest(ops.environment({})), overwrite_policy="REFUSE")
    controller = driver.PrivateGLBController(store, ops, lambda: None)
    return controller, ops, store, record


def construct(context):
    controller, _ops, _store, record = context
    return controller.construct(record.intent.preview_id, record.intent.fingerprint,
                                list(record.intent.plan.required_accepted_losses))


@pytest.mark.parametrize("version", ["4.5", "5.2"])
def test_private_model_completes_unlinked_stage_with_distinct_tree_prefixes(modules, tmp_path, version):
    context = prepared(modules, tmp_path, version)
    controller, ops, store, record = context
    result = construct(context)
    assert store.lookup(record.intent.stage_id).phase == "CONSTRUCTED"
    assert len(result["known_returned_references"]) == 5
    assert all(r["admitted_constructor_return"] for r in result["known_returned_references"])
    assert not result["native_qualified"] and not result["destination_linked"]
    assert not result["artist_destination_preservation_qualified"]
    assert not result["native_cleanup_performed"] and not result["durable_recovery_verified"]
    tree = next(r for r in result["known_returned_references"] if r["role"] == "node_tree:0")
    assert tree["last_observed_name"] == "Shader Nodetree"
    trace = controller._stages[record.intent.stage_id]
    assert trace.expected["mesh:0"]["users"] == 1
    assert trace.expected["material:0"]["users"] == 1
    assert trace.expected["object:0"]["body"]["collections"] == ["collection"]
    expected_other = [["ShaderNodeBsdfPrincipled", "IOR", "VALUE", ["0000c03f"]]]
    if version == "5.2":
        expected_other.append(["ShaderNodeBsdfPrincipled", "Thin Wall", "BOOLEAN", [False]])
    assert trace.expected["node_tree:0"]["body"]["other_inputs"] == expected_other
    assert ops.events.index("NEW_MATERIAL") < ops.events.index("INIT_MATERIAL") < ops.events.index("WRITE_PBR")
    assert "NAME_TREE" not in ops.events
    assert ops.ambient_revision == 0


@pytest.mark.parametrize("version", ["4.5", "5.2"])
def test_multi_primitive_material_binding_and_shared_mesh_users(modules, tmp_path, version):
    manifest, binary = triangle()
    primitive = manifest["meshes"][0]["primitives"][0]
    manifest["materials"] = [{}, {}]
    manifest["meshes"][0]["primitives"] = [{**primitive, "material": i} for i in (1, 0)]
    manifest["nodes"] = [{"mesh": 0}, {"mesh": 0}]
    manifest["scenes"][0]["nodes"] = [0, 1]
    context = prepared(modules, tmp_path, version, manifest=manifest, binary=binary)
    result = construct(context)
    controller, _, _, record = context
    rows = controller._stages[record.intent.stage_id].expected
    assert rows["mesh:0"]["users"] == 2
    assert rows["mesh:0"]["body"]["materials"] == ["material:1", "material:0"]
    assert [p[1] for p in rows["mesh:0"]["body"]["polygons"]] == [0, 1]
    assert result["state"]["expected_id_observations_complete"]
    trees = [row for row in result["known_returned_references"] if row["role"].startswith("node_tree:")]
    assert [row["last_observed_name"] for row in trees] == ["Shader Nodetree"] * 2
    assert len({row["uid"] for row in trees}) == len({row["pointer"] for row in trees}) == 2


@pytest.mark.parametrize("version", ["4.5", "5.2"])
@pytest.mark.parametrize("fault", ["wrong_tree_name", "aliased_tree"])
def test_embedded_constructor_name_and_distinct_return_identity_are_required(modules, tmp_path, version, fault):
    manifest, binary = triangle()
    manifest["materials"] = [{}, {}]
    primitive = manifest["meshes"][0]["primitives"][0]
    manifest["meshes"][0]["primitives"] = [{**primitive, "material": i} for i in (0, 1)]
    context = prepared(modules, tmp_path, version, manifest=manifest, binary=binary)
    controller, ops, _store, record = context
    ops.result_fault = fault
    with pytest.raises(modules[0].BridgeError):
        construct(context)
    assert controller.retained(record.intent.stage_id)["state"]["phase"] == "UNKNOWN"
    assert "NAME_TREE" not in ops.events


@pytest.mark.parametrize("drift", [True, 0])
def test_boolean_default_drift_is_detected_without_numeric_coercion(modules, tmp_path, drift):
    context = prepared(modules, tmp_path, "5.2")
    _, ops, store, record = context

    def check():
        tree = next((value for value in ops.ids.values() if value.kind == "node_tree"), None)
        if tree is not None:
            next(row for row in tree.body["other_inputs"] if row[1] == "Thin Wall")[3][0] = drift

    controller = modules[1].PrivateGLBController(store, ops, check)
    with pytest.raises(modules[0].BridgeError) as failure:
        construct((controller, ops, store, record))
    assert failure.value.context["cause"]["context"]["reason"] == "PRIVATE_OWNED_PREFIX_CHANGED"
    assert ops.events == ["NEW_COLLECTION", "NEW_MESH", "BUILD_MESH", "NEW_MATERIAL"]


@pytest.mark.parametrize("value", [False, True, 0, 1, None])
def test_native_boolean_read_requires_exact_schema_and_builtin_bool(modules, value):
    from types import SimpleNamespace

    calls = []
    socket = object()
    operations = object.__new__(modules[1].NativeOperations)
    operations._binding = SimpleNamespace(
        field=lambda *args: calls.append(("field", args)),
        get=lambda *args: calls.append(("get", args)) or value)
    if type(value) is bool:
        assert operations._boolean_input(socket) == [value]
    else:
        with pytest.raises(modules[0].BridgeError):
            operations._boolean_input(socket)
    assert calls == [("field", (object, "default_value", "BOOLEAN", 0)),
                     ("get", (socket, "default_value"))]


OPERATIONS = ["NEW_COLLECTION", "NEW_MESH", "BUILD_MESH", "NEW_MATERIAL", "INIT_MATERIAL",
              "WRITE_PBR", "BIND_MATERIALS", "NEW_OBJECT", "LINK_OBJECT"]


def structural_asset():
    manifest, binary = triangle(normals=True, uv=True)
    manifest["nodes"] = [
        {"children": [1, 2], "translation": [3., 5., 7.],
         "rotation": [0., 0., math.sqrt(.5), math.sqrt(.5)], "scale": [2., 3., 4.]},
        {"mesh": 0, "translation": [1., 0., 0.], "scale": [-1., 2., .5]},
        {"mesh": 0, "translation": [-2., 1., 3.], "scale": [1., 0., 2.]},
    ]
    return manifest, binary


@pytest.mark.parametrize("version", ["4.5", "5.2"])
def test_structural_model_preserves_full_uv_normals_hierarchy_and_shared_instances(modules, tmp_path, version):
    manifest, binary = structural_asset()
    context = prepared(modules, tmp_path, version, manifest=manifest, binary=binary)
    controller, ops, _store, record = context
    result = construct(context)
    rows = controller._stages[record.intent.stage_id].expected
    def pack(value):
        return struct.pack("<f", value).hex()
    assert rows["mesh:0"]["users"] == 2
    assert rows["object:0"]["users"] == 1  # Parent references are weak, not counted users.
    assert rows["object:0"]["body"]["children"] == ["object:1", "object:2"]
    assert rows["object:0"]["body"]["channels"]["location"] == [pack(3.), pack(-7.), pack(5.)]
    for child in (1, 2):
        assert rows[f"object:{child}"]["body"]["parent"] == "object:0"
        assert rows[f"object:{child}"]["body"]["data"] == "mesh:0"
    mesh = rows["mesh:0"]["body"]
    assert mesh["uv"] == {"name": "UVMap", "vectors": [[pack(0.), pack(1.)],
        [pack(1.), pack(.75)], [pack(0.), pack(0.)]], "active": 0, "render": 0, "clone": 0, "stencil": 0,
        "clone_bound": True, "stencil_bound": True}
    assert mesh["normals"]["decoded"] == [[pack(0.), pack(-1.), pack(0.)]] * 3
    assert {"custom_normal", "sharp_edge", "UVMap", "material_index"} <= mesh["custom_data"].keys()
    assert result["structural_conformance"]["all_nodes"] == 3
    assert result["structural_conformance"]["all_instance_vertices"] == 6
    assert result["structural_conformance"]["depsgraph_evaluated_world_qualified"] is False
    assert result["structural_conformance"]["queued_stop_during_native_return_capture_qualified"] is False
    parent_event = next(index for index, value in enumerate(ops.events) if value == "OBJECT_FIELD")
    assert parent_event > max(index for index, value in enumerate(ops.events) if value == "NEW_OBJECT")


@pytest.mark.parametrize("operation", ["NEW_UV_LAYER", "WRITE_UV", "WRITE_NORMALS", "OBJECT_FIELD"])
@pytest.mark.parametrize("when", ["before", "after"])
def test_structural_native_step_models_retain_partial_effects_without_cleanup(modules, tmp_path, operation, when):
    manifest, binary = structural_asset()
    context = prepared(modules, tmp_path, manifest=manifest, binary=binary)
    controller, ops, store, record = context
    setattr(ops, "fail_" + when, operation)
    with pytest.raises(modules[0].BridgeError):
        construct(context)
    assert store.lookup(record.intent.stage_id).phase == "UNKNOWN"
    events = list(ops.events)
    retained = controller.retained(record.intent.stage_id)
    assert retained["state"]["possible_mutation"] and retained["native_cleanup_performed"] is False
    assert retained["known_returned_references"]
    assert ops.events == events


def test_manual_normal_storage_drift_after_return_receipt_is_exactly_refused(modules, tmp_path):
    manifest, binary = structural_asset()
    _controller, ops, store, record = prepared(modules, tmp_path, manifest=manifest, binary=binary)
    changed = False
    def check():
        nonlocal changed
        if not changed and "WRITE_NORMALS" in ops.events:
            changed = True
            mesh = next(value for value in ops.ids.values() if value.kind == "mesh")
            # The decoded projection still conforms. The exact stored short
            # changed after the qualified return, so a tolerance cannot adopt it.
            mesh.body["custom_data"]["custom_normal"]["values"][0][0] += 1
    controller = modules[1].PrivateGLBController(store, ops, check)
    with pytest.raises(modules[0].BridgeError) as failure:
        construct((controller, ops, store, record))
    assert changed and failure.value.context["cause"]["context"]["reason"] == "PRIVATE_OWNED_PREFIX_CHANGED"
    assert ops.events[-1] == "WRITE_NORMALS" and "NEW_MATERIAL" not in ops.events


def test_one_ulp_manual_authored_transform_edit_cannot_pass_matrix_tolerance(modules, tmp_path):
    manifest, binary = structural_asset()
    _controller, ops, store, record = prepared(modules, tmp_path, manifest=manifest, binary=binary)
    changed = False
    def check():
        nonlocal changed
        if changed:
            return
        objects = [value for value in ops.ids.values() if value.kind == "object"]
        for obj in objects:
            bits = obj.body["channels"]["location"][0]
            if bits == struct.pack("<f", 3.).hex():
                changed = True
                raw = struct.unpack("<I", bytes.fromhex(bits))[0] + 1
                obj.body["channels"]["location"][0] = struct.pack("<I", raw).hex()
                obj.body["matrix"] = ops._basis(obj.body["channels"])
                return
    controller = modules[1].PrivateGLBController(store, ops, check)
    with pytest.raises(modules[0].BridgeError) as failure:
        construct((controller, ops, store, record))
    assert changed and failure.value.context["cause"]["context"]["reason"] == "PRIVATE_OWNED_PREFIX_CHANGED"


def test_direct_parent_consumer_model_rejects_foreign_child_without_python_children_helper(modules):
    from types import SimpleNamespace

    parent, child = object(), object()
    calls = []
    binding = SimpleNamespace(main=object(), get=lambda value, field: parent if value is child and field == "parent" else None,
                              _pointer=lambda value: id(value))
    model = SimpleNamespace(_binding=binding, _items=lambda *_args: (child,))
    def owner_role(value):
        calls.append(value)
        raise modules[0].refused("FOREIGN_PRIVATE_CONSUMER")
    with pytest.raises(modules[0].BridgeError):
        modules[1].NativeOperations._children_using(model, parent, owner_role)
    assert calls == [child]


def test_unbinding_uv_clone_with_unchanged_fallback_index_is_not_adopted(modules, tmp_path):
    manifest, binary = structural_asset()
    _controller, ops, store, record = prepared(modules, tmp_path, "5.2", manifest=manifest, binary=binary)
    changed = False
    def check():
        nonlocal changed
        if changed or "UV_ROLE" not in ops.events:
            return
        mesh = next(value for value in ops.ids.values() if value.kind == "mesh")
        if mesh.body["uv"]["clone_bound"] and mesh.body["uv"]["stencil_bound"]:
            changed = True
            mesh.body["uv"]["clone_bound"] = False
            assert mesh.body["uv"]["clone"] == 0
    controller = modules[1].PrivateGLBController(store, ops, check)
    with pytest.raises(modules[0].BridgeError) as failure:
        construct((controller, ops, store, record))
    assert changed and failure.value.context["cause"]["context"]["reason"] == "PRIVATE_OWNED_PREFIX_CHANGED"
    assert "WRITE_UV" not in ops.events


def test_mesh_return_receipt_cannot_be_forged_by_mutating_its_body(modules, tmp_path, monkeypatch):
    context = prepared(modules, tmp_path)
    _controller, ops, _store, _record = context
    original = ModelOperations.take_footprint
    def corrupt(self, operation, role):
        receipt = original(self, operation, role)
        if receipt is not None:
            receipt.body["vertices"][0][0] = "0000803f"
        return receipt
    monkeypatch.setattr(ModelOperations, "take_footprint", corrupt)
    controller = modules[1].PrivateGLBController(context[2], ops, lambda: None)
    with pytest.raises(modules[0].BridgeError) as failure:
        construct((controller, ops, *context[2:]))
    assert failure.value.context["cause"]["context"]["reason"] == "PRIVATE_MESH_RETURN_PROVENANCE"
    assert ops.events[-1] == "BUILD_MESH"


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("when", ["before", "after"])
def test_injected_failure_retains_exact_known_subset_and_never_cleans_or_resumes(modules, tmp_path, operation, when):
    profile, *_ = modules
    context = prepared(modules, tmp_path)
    controller, ops, store, record = context
    setattr(ops, "fail_" + when, operation)
    with pytest.raises(profile.BridgeError) as failure:
        construct(context)
    assert failure.value.context["possible_mutation"]
    retained = controller.retained(record.intent.stage_id)
    assert retained["state"]["phase"] == "UNKNOWN"
    assert not retained["native_cleanup_performed"]
    assert len(ops.ids) >= len(retained["known_returned_references"])
    events = list(ops.events)
    with pytest.raises(profile.BridgeError):
        construct(context)
    assert ops.events == events
    assert store.inspect(record.intent.stage_id)["outcome_unknown"]


@pytest.mark.parametrize("kind", ["source_context", "owned_payload", "baseline_rebase", "version", "reference_map",
                                  "operations_object", "operations_binding"])
def test_callback_changes_stop_before_the_next_write_without_rebase(modules, tmp_path, kind):
    profile, driver, *_ = modules
    context = prepared(modules, tmp_path)
    original, ops, store, record = context

    def check():
        if len(ops.events) < 3:
            return
        if kind == "source_context":
            ops.ambient_revision += 1
        elif kind == "version":
            ops._version = "5.2"
        elif kind == "owned_payload":
            next(v for v in ops.ids.values() if v.kind == "mesh").body["vertices"][-1][-1] = "00000000"
        elif kind == "operations_object":
            controller._calls.operations = ModelOperations("4.5")
        elif kind == "operations_binding":
            controller._calls = driver._Calls(ModelOperations("4.5"))
        else:
            stage = controller._stages[record.intent.stage_id]
            if kind == "reference_map":
                stage.references = dict(stage.references)
            else:
                stage.expected["mesh:0"]["body"]["vertices"][-1][-1] = "00000000"
                next(v for v in ops.ids.values() if v.kind == "mesh").body["vertices"][-1][-1] = "00000000"

    controller = driver.PrivateGLBController(store, ops, check)
    with pytest.raises(profile.BridgeError):
        construct((controller, ops, store, record))
    assert ops.events == ["NEW_COLLECTION", "NEW_MESH", "BUILD_MESH"]
    assert not original._stages


def test_unknown_method_descriptor_is_rejected_without_invocation(modules, tmp_path, monkeypatch):
    profile, driver, *_ = modules
    context = prepared(modules, tmp_path)
    _, ops, store, record = context
    called = []

    def check():
        if ops.events:
            monkeypatch.setattr(ModelOperations, "row", property(lambda _: called.append(True)))

    controller = driver.PrivateGLBController(store, ops, check)
    with pytest.raises(profile.BridgeError):
        construct((controller, ops, store, record))
    assert ops.events == ["NEW_COLLECTION"] and not called


@pytest.mark.parametrize("kind", ["readback", "foreign", "volume_context", "volume_default", "face_ranges"])
def test_bad_readback_and_constructor_shape_are_not_adopted(modules, tmp_path, kind):
    profile, *_ = modules
    context = prepared(modules, tmp_path)
    controller, ops, store, record = context
    if kind == "readback":
        ops.corrupt = "BUILD_MESH"
    elif kind == "face_ranges":
        ops.corrupt = "face_ranges"
    elif kind == "foreign":
        ops.foreign_return = True
    elif kind == "volume_context":
        ops.active_type = "VOLUME"
    else:
        ops.volume_graph = True
    with pytest.raises(profile.BridgeError):
        construct(context)
    if kind == "volume_context":
        assert not ops.events and not controller._stages
    else:
        assert store.lookup(record.intent.stage_id).phase == "UNKNOWN"
        assert not controller.retained(record.intent.stage_id)["native_cleanup_performed"]


def test_native_operations_requires_real_blender_and_public_adapter_requires_runtime(modules, addon_package):
    from types import SimpleNamespace
    profile, driver, *_ = modules
    with pytest.raises(profile.BridgeError) as failure:
        driver.NativeOperations()
    assert failure.value.context["reason"] == "NATIVE_BLENDER_REQUIRED"
    adapter = importlib.import_module(addon_package + ".tools.glb_stage")
    for function in (adapter.preview, adapter.create_start, adapter.inspect_stage,
                     adapter.publish_preview, adapter.publish_start):
        with pytest.raises(profile.BridgeError, match="Canonical Runtime"):
            function(SimpleNamespace(glb_stage=None), {})
    assert hasattr(adapter, "register")
    assert not hasattr(adapter, "create")


@pytest.mark.parametrize("kind,role", [("missing_tree", "material:0"), ("extra_key", "mesh:0"),
                                       ("extra_two_keys", "mesh:0")])
def test_malformed_result_retains_expected_return_before_any_metadata_or_admission(modules, tmp_path, kind, role):
    profile, *_ = modules
    context = prepared(modules, tmp_path, "5.2")
    controller, ops, _store, record = context
    ops.result_fault = kind
    with pytest.raises(profile.BridgeError):
        construct(context)
    retained = controller.retained(record.intent.stage_id)
    result = next(value for value in retained["known_returned_references"] if value["role"] == role)
    assert not result["admitted_constructor_return"] and result["uid"] is None
    assert retained["state"]["outcome_unknown"] and not retained["native_cleanup_performed"]
    assert "NAME_TREE" not in ops.events


@pytest.mark.parametrize("kind", ["build", "hash", "release", "fake_registry", "fake_module"])
def test_native_bootstrap_cannot_be_unlocked_by_fake_version_or_caller_certificate(modules, monkeypatch, kind):
    import sys
    from types import ModuleType, SimpleNamespace

    profile, driver, *_ = modules
    module = ModuleType("bpy")
    module.app = SimpleNamespace(version=(4, 5, 14), build_hash=b"62c1db4208e8", build_type=b"Release")
    module.types = SimpleNamespace()
    events = []
    module.data = SimpleNamespace(collections=SimpleNamespace(new=lambda *_: events.append("allocation")))
    if kind == "build":
        module.app.version = (4, 5, 15)
    elif kind == "hash":
        module.app.build_hash = b"unreviewed"
    elif kind == "release":
        module.app.build_type = b"Debug"
    elif kind == "fake_registry":
        module.types.__getattr__ = lambda name: events.append(name)
    else:
        module = SimpleNamespace(app=module.app, types=module.types)
    monkeypatch.setitem(sys.modules, "bpy", module)
    with pytest.raises(profile.BridgeError) as failure:
        driver.NativeOperations()
    assert failure.value.context["native_allocation_started"] is False
    assert not events
    with pytest.raises(TypeError):
        driver.NativeOperations(bpy=module, certificate={"approved": True})
    assert not events


def test_native_escrow_retains_actual_delivered_reference_without_a_getter(modules):
    profile, driver, *_ = modules
    events = []

    class Poison:
        def __getattribute__(self, name):
            events.append(name)
            raise AssertionError("metadata before escrow retention")

    stage, material, tree = object(), Poison(), Poison()
    escrow = driver._ReturnEscrow(stage, "NEW_MATERIAL", "material:0", ("material:0", "node_tree:0"))
    assert set(escrow.references) == {"material:0", "node_tree:0"}  # Keys preallocated before native entry.
    escrow.remember("material:0", material)
    # A dependent tree getter throws here: only the genuinely delivered Material
    # is drained. No tree reference/UID is invented and no descriptor is invoked.
    with pytest.raises(profile.BridgeError):
        escrow.drain(object(), "NEW_MATERIAL", "material:0")
    result = escrow.drain(stage, "NEW_MATERIAL", "material:0")
    assert result.keys() == {"material:0"} and result["material:0"] is material
    assert escrow.references["material:0"] is material
    with pytest.raises(profile.BridgeError):
        escrow.remember("node_tree:0", tree)
    assert not events


@pytest.mark.parametrize("fault", ["operation", "role", "duplicate", "unexpected", "too_many"])
def test_escrow_operation_binding_and_finite_roles_do_not_adopt_extras(modules, fault):
    profile, driver, *_ = modules
    stage, value = object(), object()
    if fault == "too_many":
        with pytest.raises(profile.BridgeError):
            driver._ReturnEscrow(stage, "NEW_MATERIAL", "m", ("a", "b", "c"))
        return
    escrow = driver._ReturnEscrow(stage, "NEW_MESH", "mesh:0", ("mesh:0",))
    escrow.remember("mesh:0", value)
    with pytest.raises(profile.BridgeError):
        if fault == "operation":
            escrow.drain(stage, "NEW_OBJECT", "mesh:0")
        elif fault == "role":
            escrow.drain(stage, "NEW_MESH", "mesh:1")
        else:
            escrow.remember("mesh:0" if fault == "duplicate" else "unexpected", object())
    assert escrow.drain(stage, "NEW_MESH", "mesh:0")["mesh:0"] is value


def test_consumer_model_includes_unlinked_collections_and_embedded_scene_masters(modules):
    from types import SimpleNamespace

    profile, driver, *_ = modules
    obj, collection, master, scene = object(), object(), object(), object()
    owners = {"collections": (collection,), "scenes": (scene,),
              (collection, "objects"): (), (master, "objects"): (obj,)}
    main = object()
    model = SimpleNamespace(_binding=SimpleNamespace(main=main, get=lambda owner, field: master),
                            _identity=lambda value: id(value),
                            _items=lambda owner, field, _limit: owners[field if owner is main else (owner, field)])
    # Exercise the sourced algorithm with plain identities, never a native
    # adapter/provider. A foreign embedded Scene master must be observed.
    def refuse_foreign(_owner):
        raise profile.refused("MODEL_FOREIGN_CONSUMER")
    with pytest.raises(profile.BridgeError) as error:
        driver.NativeOperations._collections_using(model, obj, refuse_foreign)
    assert error.value.context["reason"] == "MODEL_FOREIGN_CONSUMER"
    owners[(master, "objects")], owners[(collection, "objects")] = (), (obj,)
    assert driver.NativeOperations._collections_using(model, obj, lambda _: "collection") == ["collection"]


@pytest.mark.parametrize("version", ["4.5", "5.2"])
def test_complete_structural_selection_storage_has_exact_twelve_fields(modules, tmp_path, version):
    manifest, binary = structural_asset()
    context = prepared(modules, tmp_path, version, manifest=manifest, binary=binary)
    construct(context)
    controller, _ops, _store, record = context
    body = controller._stages[record.intent.stage_id].expected["mesh:0"]["body"]
    assert len(body["custom_data"]) == 12
    for name, domain, count in ((".select_vert", "POINT", 3), (".select_edge", "EDGE", 3), (".select_poly", "FACE", 1)):
        assert body["custom_data"][name] == {"domain": domain, "type": "BOOLEAN", "values": [True] * count}
    modules[1]._validate_mesh_custom_data(body)


@pytest.mark.parametrize("name", [".select_vert", ".select_edge", ".select_poly"])
@pytest.mark.parametrize("fault", ["missing", "domain", "type", "short", "long", "integer", "tuple"])
def test_selection_storage_schema_refuses_missing_wrong_shape_and_nonbool(modules, tmp_path, name, fault):
    context = prepared(modules, tmp_path)
    construct(context)
    controller, _ops, _store, record = context
    body = copy.deepcopy(controller._stages[record.intent.stage_id].expected["mesh:0"]["body"])
    item = body["custom_data"][name]
    if fault == "missing":
        body["custom_data"].pop(name)
    elif fault == "domain":
        item["domain"] = "CORNER"
    elif fault == "type":
        item["type"] = "INT"
    elif fault == "short":
        item["values"].pop()
    elif fault == "long":
        item["values"].append(True)
    elif fault == "integer":
        item["values"][0] = 1
    else:
        item["values"] = tuple(item["values"])
    with pytest.raises(modules[0].BridgeError) as failure:
        modules[1]._validate_mesh_custom_data(body)
    assert failure.value.context["reason"] in {"PRIVATE_CUSTOM_DATA_SCHEMA", "PRIVATE_SELECTION_ATTRIBUTE_MISSING", "PRIVATE_SELECTION_STORAGE_INVALID"}


@pytest.mark.parametrize("name", [".select_vert", ".select_edge", ".select_poly"])
def test_initial_selection_values_cannot_be_adopted_from_a_changed_return(modules, tmp_path, name):
    context = prepared(modules, tmp_path)
    _controller, ops, _store, _record = context
    capture = ops._capture_footprint
    def changed(operation, role, body):
        if operation == "BUILD_MESH":
            body["custom_data"][name]["values"][0] = False
        capture(operation, role, body)
    ops._capture_footprint = changed
    with pytest.raises(modules[0].BridgeError) as failure:
        construct(context)
    assert failure.value.context["cause"]["context"]["reason"] == "PRIVATE_MESH_INITIAL_SELECTION_CHANGED"
    assert ops.events[-1] == "BUILD_MESH" and "NEW_MATERIAL" not in ops.events


@pytest.mark.parametrize("name", [".select_vert", ".select_edge", ".select_poly"])
@pytest.mark.parametrize("phase", ["BUILD_MESH", "WRITE_NORMALS"])
@pytest.mark.parametrize("fault", ["bit", "integer", "domain", "type", "missing", "unknown"])
def test_every_later_selection_component_or_schema_edit_stops_before_next_native_entry(
    modules, tmp_path, name, phase, fault,
):
    manifest, binary = structural_asset()
    _controller, ops, store, record = prepared(modules, tmp_path, manifest=manifest, binary=binary)
    changed = []
    def check():
        if changed or not ops.events or ops.events[-1] != phase:
            return
        changed.append(True)
        mesh = next(value for value in ops.ids.values() if value.kind == "mesh")
        attributes = mesh.body["custom_data"]
        if fault == "bit":
            attributes[name]["values"][-1] = False
        elif fault == "integer":
            attributes[name]["values"][-1] = 1
        elif fault == "domain":
            attributes[name]["domain"] = "CORNER"
        elif fault == "type":
            attributes[name]["type"] = "INT"
        elif fault == "missing":
            attributes.pop(name)
        else:
            attributes[name + "_unqualified"] = attributes.pop(name)
    controller = modules[1].PrivateGLBController(store, ops, check)
    with pytest.raises(modules[0].BridgeError) as failure:
        construct((controller, ops, store, record))
    assert changed and failure.value.context["cause"]["context"]["reason"] == "PRIVATE_OWNED_PREFIX_CHANGED"
    assert ops.events[-1] == phase and "NEW_MATERIAL" not in ops.events
    assert store.inspect(record.intent.stage_id)["phase"] == "UNKNOWN"


def test_resumable_construction_does_not_start_before_first_next(modules, tmp_path):
    manifest, binary = triangle(normals=True, uv=True)
    context = prepared(modules, tmp_path, "5.2", manifest=manifest, binary=binary)
    controller, operations, store, record = context
    steps = controller.construct_steps(record.intent.preview_id, record.intent.fingerprint,
                                       list(record.intent.plan.required_accepted_losses))
    assert store.lookup(record.intent.stage_id).phase == "PREPARED"
    assert operations.events == [] and not controller._stages
    first = next(steps)
    assert first == {"operation": "NEW_COLLECTION", "role": "collection"}
    assert store.lookup(record.intent.stage_id).phase == "ALLOCATING"
    assert list(controller._stages[record.intent.stage_id].references) == ["collection"]
    completed = [first]
    while True:
        try:
            completed.append(next(steps))
        except StopIteration as result:
            assert result.value["state"]["phase"] == "CONSTRUCTED"
            break
    assert any(row["operation"] == "WRITE_UV" for row in completed)
    assert any(row["operation"] == "WRITE_NORMALS" for row in completed)
    assert len(completed) == len(controller._stages[record.intent.stage_id].timings)


def test_constructed_verification_rejects_exact_owned_drift_without_new_write(modules, tmp_path):
    context = prepared(modules, tmp_path, "5.2")
    controller, operations, store, record = context
    construct(context)
    before = list(operations.events)
    controller.verify_retained(record.intent.stage_id)
    assert operations.events == before
    mesh = controller._stages[record.intent.stage_id].references["mesh:0"].value
    mesh.body["custom_data"][".select_vert"]["values"][0] = False
    with pytest.raises(modules[0].BridgeError):
        controller.verify_retained(record.intent.stage_id)
    assert operations.events == before
    assert store.lookup(record.intent.stage_id).phase == "CONSTRUCTED"


def test_filepath_only_destination_drift_changes_exact_native_environment_witness(modules):
    from types import SimpleNamespace as NS
    profile, driver, *_ = modules
    scene = NS()
    layer = NS(objects=NS(active=None))
    main = NS(filepath="first.blend")
    context = NS(view_layer=layer, scene=scene, mode="OBJECT")
    scene.frame_current, scene.frame_subframe = 1, 0.
    binding = NS(main=main, main_pointer=12, context=context, get=getattr, selected=lambda: ())
    operations = NS(_blender=lambda: None, _binding=binding, _items=lambda *_args: (),
                    _identity=lambda _value: (34, 56))
    first = driver.NativeOperations.environment(operations, {})
    main.filepath = "second.blend"
    second = driver.NativeOperations.environment(operations, {})
    assert first["filepath"] == "first.blend" and second["filepath"] == "second.blend"
    assert profile.digest(first) != profile.digest(second)
    assert {key: value for key, value in first.items() if key != "filepath"} == {
        key: value for key, value in second.items() if key != "filepath"}


def stock_tree_model(profile, base_module="bpy_types"):
    root = type("NodeTree", (object,), {"__module__": base_module, "__slots__": ()})
    classes = {name: type(name, (root,), {"__module__": "bpy.types", "__slots__": ()})
               for name in profile._STOCK_TREE_NAMES}
    return root, classes


@pytest.mark.parametrize("base_module", ["bpy_types", "_bpy_types"])
def test_stock_tree_family_accepts_only_complete_shipped_namespace_model(modules, base_module):
    profile, *_ = modules
    root, classes = stock_tree_model(profile, base_module)
    assert profile.stock_tree_family(root, classes, id_base=object, base_module=base_module) == tuple(
        (name, id(classes[name])) for name in profile._STOCK_TREE_NAMES)


@pytest.mark.parametrize("fault", ["alias_idname", "nested_subclass", "callback", "base_callback", "module", "slots", "incomplete",
    "base_module", "base_id", "base_getter", "subclass_getter"])
def test_stock_tree_family_refuses_unproven_registry_descendants_before_constructors(modules, fault):
    profile, *_ = modules
    root, classes = stock_tree_model(profile)
    retained = None
    callbacks = []
    if fault == "alias_idname":
        retained = type("MyTree", (root,), {"bl_idname": "ShaderNodeTree", "update": lambda _self: callbacks.append("FOREIGN")})
        assert classes["ShaderNodeTree"].__name__ == "ShaderNodeTree"
    elif fault == "nested_subclass":
        retained = type("Nested", (classes["ShaderNodeTree"],), {"__slots__": ()})
    elif fault == "callback":
        classes["ShaderNodeTree"].update = lambda _self: callbacks.append("FOREIGN")
    elif fault == "base_callback":
        root.poll = lambda *_args: callbacks.append("FOREIGN")
    elif fault == "module":
        classes["ShaderNodeTree"].__module__ = "ordinary_addon"
    elif fault == "slots":
        classes["ShaderNodeTree"].__slots__ = ("unqualified",)
    elif fault == "base_module":
        root.__module__ = "ordinary_addon"
    elif fault == "base_id":
        class ForeignID:
            pass
        root = type("NodeTree", (ForeignID,), {"__module__": "bpy_types", "__slots__": ()})
        classes = {name: type(name, (root,), {"__module__": "bpy.types", "__slots__": ()})
                   for name in profile._STOCK_TREE_NAMES}
    elif fault in {"base_getter", "subclass_getter"}:
        target = root if fault == "base_getter" else classes["ShaderNodeTree"]
        target.__getattribute__ = lambda *_args: callbacks.append("FOREIGN")
    else:
        classes.pop("TextureNodeTree")
    with pytest.raises(profile.BridgeError) as failure:
        profile.stock_tree_family(root, classes, id_base=object, base_module="bpy_types")
    assert failure.value.context["native_allocation_started"] is False
    assert callbacks == []
    assert retained is None or isinstance(retained, type)


def test_stock_tree_family_does_not_invoke_foreign_metaclass_getters(modules):
    profile, *_ = modules
    callbacks = []

    class HostileMeta(type):
        def __getattribute__(cls, name):
            callbacks.append(name)
            raise AssertionError("foreign metaclass getter")

    root = HostileMeta("NodeTree", (object,), {"__module__": "bpy_types", "__slots__": ()})
    classes = {name: HostileMeta(name, (root,), {"__module__": "bpy.types", "__slots__": ()})
               for name in profile._STOCK_TREE_NAMES}
    profile.stock_tree_family(root, classes, id_base=object, base_module="bpy_types")
    assert callbacks == []


@pytest.mark.parametrize("kind", ["SHADER", "CUSTOM", "wrong_class"])
def test_actual_tree_discriminator_is_checked_after_escrow_before_graph_reads(modules, kind):
    from types import SimpleNamespace as NS
    profile, driver, *_ = modules
    tree_class = type("ShaderTree", (), {})
    value = tree_class() if kind != "wrong_class" else object()
    calls = []

    def get(_value, name):
        calls.append(name)
        return kind

    operations = NS(_binding=NS(classes={"ShaderNodeTree": tree_class}, get=get))
    if kind == "SHADER":
        assert driver.NativeOperations._shader_tree_return(operations, value) is value
    else:
        with pytest.raises(profile.BridgeError):
            driver.NativeOperations._shader_tree_return(operations, value)
    assert calls == ([] if kind == "wrong_class" else ["type"])
