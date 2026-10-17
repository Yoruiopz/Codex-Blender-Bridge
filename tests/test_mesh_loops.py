from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest

from mcp_server.tools.catalog import load_mesh_definitions
from mcp_server.tools.mesh import MeshTools


class Geometry:
    def __init__(self, index, **kwargs):
        self.index, self.hide = index, False
        self.__dict__.update(kwargs)


def cube():
    vertices = [Geometry(i) for i in range(8)]
    edges, lookup, faces = [], {}, []
    for corners in ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)):
        face = Geometry(len(faces), verts=[vertices[i] for i in corners], edges=[])
        for first, second in zip(corners, corners[1:] + corners[:1], strict=True):
            key = tuple(sorted((first, second)))
            if key not in lookup:
                edge = Geometry(len(edges), verts=[vertices[first], vertices[second]], link_faces=[])
                lookup[key] = edge
                edges.append(edge)
            lookup[key].link_faces.append(face)
            face.edges.append(lookup[key])
        faces.append(face)
    return SimpleNamespace(verts=vertices, edges=edges, faces=faces, normal_update=lambda: None)


@pytest.fixture
def loops(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.mesh_loops")
    bm = cube()
    obj = SimpleNamespace(name="Box", data=SimpleNamespace(users=1, shape_keys=None, materials=[]))
    monkeypatch.setattr(module, "_active_edit_mesh", lambda _: (None, obj, bm, {}))
    monkeypatch.setattr(module, "validate_selection_reference", lambda *args: {"edges": [0]})
    monkeypatch.setattr(module, "_result", lambda obj, bm, before, **kw: {"mesh_counts_after": module._mesh_counts(bm)})
    calls = []

    def subdivide(mesh, **kwargs):
        calls.append(kwargs)
        ring = module._ring(mesh, mesh.edges[0], SimpleNamespace(check_cancelled=None))
        expected = module._cut_counts(module._mesh_counts(mesh), ring, kwargs["cuts"])
        for label in ("verts", "edges", "faces"):
            sequence = getattr(mesh, label)
            count = expected["vertices" if label == "verts" else label]
            sequence.extend(Geometry(i) for i in range(len(sequence), count))

    monkeypatch.setattr(module, "bmesh", SimpleNamespace(ops=SimpleNamespace(subdivide_edges=subdivide)))
    return module, obj, bm, calls, SimpleNamespace(check_cancelled=None)


def test_closed_ring_walk_and_expected_cut_counts(loops):
    module, _, bm, _, context = loops
    ring = module._ring(bm, bm.edges[0], context)
    assert ring.closed and len(ring.edges) == len(ring.faces) == 4
    assert module._cut_counts(module._mesh_counts(bm), ring, 2) == {"vertices": 16, "edges": 28, "faces": 14}


@pytest.mark.parametrize("restriction", ["hidden", "triangle", "nonmanifold", "budget", "wire"])
def test_ring_rejects_unsafe_or_unsupported_traversal(loops, monkeypatch, restriction):
    module, _, bm, calls, context = loops
    if restriction == "hidden":
        bm.edges[2].hide = True
    elif restriction == "triangle":
        bm.faces[0].verts.pop()
    elif restriction == "nonmanifold":
        bm.edges[0].link_faces.append(bm.faces[1])
    elif restriction == "budget":
        monkeypatch.setattr(module, "MAX_RING_EDGES", 2)
    else:
        bm.edges[0].link_faces.clear()
    with pytest.raises(Exception) as error:
        module._ring(bm, bm.edges[0], context)
    assert error.value.code in {"INVALID_ARGUMENT", "INVALID_SELECTION", "NOT_IMPLEMENTED"}
    assert not calls


@pytest.mark.parametrize("extra", [{"cuts": True}, {"cuts": 33}, {"seed_edge_index": True},
    {"seed_edge_index": 99}, {"selection_id": None}, {"unknown": 1}])
def test_loop_cut_validates_before_native_mutation(loops, extra):
    module, _, _, calls, context = loops
    with pytest.raises(Exception) as error:
        module.loop_cut(context, {"object_name": "Box", "seed_edge_index": 0, "selection_id": "ref", **extra})
    assert error.value.code == "INVALID_ARGUMENT" and not calls


def test_loop_cut_uses_complete_ring_and_checks_native_counts(loops):
    module, _, _, calls, context = loops
    result = module.loop_cut(context, {"object_name": "Box", "seed_edge_index": 0, "selection_id": "ref", "cuts": 2})
    assert len(calls[0]["edges"]) == 4 and calls[0]["use_only_quads"]
    assert result["mesh_counts_after"] == {"vertices": 16, "edges": 28, "faces": 14}


def test_wrong_native_cut_counts_are_not_success(loops, monkeypatch):
    module, _, _, _, context = loops
    monkeypatch.setattr(module.bmesh.ops, "subdivide_edges", lambda *a, **kw: {})
    with pytest.raises(Exception) as error:
        module.loop_cut(context, {"object_name": "Box", "seed_edge_index": 0, "selection_id": "ref"})
    assert error.value.code == "OPERATION_FAILED" and error.value.context["verification_required"]


@pytest.mark.parametrize("restriction", ["shared", "shape_keys", "reference", "budget"])
def test_cut_ownership_reference_and_output_budget(loops, monkeypatch, restriction):
    module, obj, _, calls, context = loops
    if restriction == "shared":
        obj.data.users = 2
    elif restriction == "shape_keys":
        obj.data.shape_keys = object()
    elif restriction == "reference":
        monkeypatch.setattr(module, "validate_selection_reference", lambda *a: {"edges": [1]})
    else:
        monkeypatch.setattr(module, "MAX_MESH_ELEMENTS", 30)
    with pytest.raises(Exception) as error:
        module.loop_cut(context, {"object_name": "Box", "seed_edge_index": 0, "selection_id": "ref"})
    assert error.value.code in {"NOT_IMPLEMENTED", "INVALID_ARGUMENT", "INVALID_SELECTION"} and not calls


def wire_loops(sizes):
    result = []
    for size in sizes:
        vertices = [Geometry(i) for i in range(size)]
        result.extend(Geometry(len(result) + i, verts=[vertices[i], vertices[(i + 1) % size]], is_boundary=False,
                               is_wire=True, link_faces=[]) for i in range(size))
    return result


@pytest.mark.parametrize("sizes", [(4, 4), (3, 7)])
def test_bridge_closed_loop_detection(loops, sizes):
    module, _, _, _, _ = loops
    result = module._closed_loops(wire_loops(sizes))
    assert [len(loop) for loop in result] == list(sizes)


@pytest.mark.parametrize("restriction", ["open", "interior", "one", "three", "oversize"])
def test_bridge_rejects_bad_loops(loops, monkeypatch, restriction):
    module, _, _, _, _ = loops
    edges = wire_loops((4, 4))
    if restriction == "open":
        edges.pop()
    elif restriction == "interior":
        edges[0].is_wire = False
    elif restriction == "one":
        edges = edges[:4]
    elif restriction == "three":
        edges = wire_loops((3, 3, 3))
    else:
        monkeypatch.setattr(module, "MAX_LOOP_EDGES", 3)
    with pytest.raises(Exception) as error:
        module._closed_loops(edges)
    assert error.value.code in {"INVALID_ARGUMENT", "INVALID_SELECTION"}


@pytest.mark.parametrize("extra", [{"twist_offset": True}, {"twist_offset": 4}, {"material_index": True},
    {"material_index": 1}, {"selection_id": None}, {"unexpected": 1}])
def test_bridge_parameters_are_validated_before_native_work(loops, monkeypatch, extra):
    module, obj, bm, calls, context = loops
    edges = wire_loops((4, 4))
    monkeypatch.setattr(module, "_scope", lambda *a: (obj, bm, edges))
    with pytest.raises(Exception) as error:
        module.bridge_loops(context, {"object_name": "Box", "selection_id": "ref", **extra})
    assert error.value.code == "INVALID_ARGUMENT" and not calls


@pytest.mark.parametrize("sizes,area", [((4, 4), 1.), ((3, 5), 1.), ((4, 4), 0.)])
def test_native_bridge_counts_and_zero_area_faces(loops, monkeypatch, sizes, area):
    module, obj, bm, _, context = loops
    edges = wire_loops(sizes)
    bm.edges, bm.faces = edges[:], []
    bm.verts = list({vertex for edge in edges for vertex in edge.verts})
    monkeypatch.setattr(module, "_scope", lambda *a: (obj, bm, edges))

    def bridge(mesh, **kwargs):
        assert not kwargs["use_merge"]
        count = sizes[0] if sizes[0] == sizes[1] else sum(sizes)
        created = [Geometry(i, loops=[], calc_area=lambda: area) for i in range(count)]
        mesh.faces.extend(created)
        mesh.edges.extend(Geometry(i) for i in range(count))
        return {"faces": created}

    monkeypatch.setattr(module.bmesh.ops, "bridge_loops", bridge, raising=False)
    if area == 0:
        with pytest.raises(Exception) as error:
            module.bridge_loops(context, {"object_name": "Box", "selection_id": "ref"})
        assert error.value.code == "OPERATION_FAILED" and error.value.context["invalid_created_faces"] == 4
    else:
        result = module.bridge_loops(context, {"object_name": "Box", "selection_id": "ref"})
        assert result["created_faces"] == (sizes[0] if sizes[0] == sizes[1] else sum(sizes))
        assert result["invalid_created_faces"] == 0


def test_unequal_twist_is_not_claimed_when_native_blender_ignores_it(loops, monkeypatch):
    module, obj, bm, calls, context = loops
    monkeypatch.setattr(module, "_scope", lambda *a: (obj, bm, wire_loops((3, 5))))
    with pytest.raises(Exception) as error:
        module.bridge_loops(context, {"object_name": "Box", "selection_id": "ref", "twist_offset": 1})
    assert error.value.code == "NOT_IMPLEMENTED" and not calls


def test_new_loop_tools_registry_and_wrappers(addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools.mesh_loops").register_tools(registry)
    definitions = {item.name: item for item in load_mesh_definitions()}
    calls = []

    class Registry:
        async def call(self, method, arguments):
            calls.append((method, arguments))
            return {}

    tools = MeshTools(Registry())
    for name, kwargs in {"edge_ring_inspect": {"seed_edge_index": 0},
                         "loop_cut": {"seed_edge_index": 0, "selection_id": "ref"},
                         "bridge_loops": {"selection_id": "ref"}}.items():
        spec = registry.get(f"mesh.{name}")
        modifying = name != "edge_ring_inspect"
        assert spec.modifies is modifying and spec.automatic_checkpoint
        assert definitions[spec.name].modifying is modifying
        assert {p.value for p in spec.permissions} == set(definitions[spec.name].required_permissions)
        asyncio.run(getattr(tools, f"mesh_{name}")("Box", **kwargs))
        assert calls[-1][0] == spec.name and calls[-1][1]["object_name"] == "Box"
