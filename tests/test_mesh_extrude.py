from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace as NS


def test_face_region_extrusion_includes_each_region_edge_for_native_base_cleanup(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.mesh")
    class Element:
        select = False
    class Vertex(Element):
        pass
    edges = [Element() for _ in range(5)]
    faces = [NS(edges=edges[:3], select=True), NS(edges=edges[2:], select=True)]
    bm = NS(verts=[Vertex()], edges=edges, faces=faces)
    new = Vertex()
    cap = Element()
    calls = []
    def extrude(mesh, *, geom, use_keep_orig):
        assert mesh is bm and use_keep_orig is False
        assert geom[:2] == faces and geom[2:] == edges
        calls.append("extrude")
        return {"geom": [new, cap]}
    def translate(mesh, *, verts, vec):
        assert mesh is bm and verts == [new] and vec == [0., 0., .25]
        calls.append("translate")
    monkeypatch.setattr(module, "bmesh", NS(ops=NS(extrude_face_region=extrude, translate=translate), types=NS(BMVert=Vertex)))
    monkeypatch.setitem(sys.modules, "mathutils", NS(Vector=lambda value: list(value)))
    monkeypatch.setattr(module, "_edit_bmesh", lambda _: (NS(name="Shell"), bm, None))
    monkeypatch.setattr(module, "_operation_elements", lambda *_: faces)
    monkeypatch.setattr(module, "_mesh_counts", lambda _: {"faces": 2})
    monkeypatch.setattr(module, "_finish", lambda *_a, **_k: {})
    result = module.extrude_selected(None, {"offset": [0., 0., .25]})
    assert calls == ["extrude", "translate"]
    assert result["source_faces"] == 2 and result["new_vertices"] == 1
    assert new.select and cap.select and not any(face.select for face in faces)
