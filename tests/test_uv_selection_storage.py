"""Exercise native per-layer versus mesh-global UV context preservation."""

from __future__ import annotations

import importlib
from contextlib import nullcontext
from types import SimpleNamespace

import pytest


class Loop:
    def __init__(self, index, modern):
        self.data = SimpleNamespace(uv=(index, .25), pin_uv=index % 2 == 0)
        if modern:
            self.uv_select_vert = index % 3 == 0
            self.uv_select_edge = index % 2 == 0
        else:
            self.data.select = index % 3 == 0
            self.data.select_edge = index % 2 == 0

    def __getitem__(self, handle):
        return self.data


class Face:
    def __init__(self, loops, selected, modern):
        self.loops, self.select = loops, selected
        if modern:
            self.uv_select = not selected

    def select_set(self, value):
        self.select = value


@pytest.fixture(params=["legacy", "global"])
def scope(request, addon_package):
    module = importlib.import_module(f"{addon_package}.tools._uv_selection")
    modern = request.param == "global"
    layer = SimpleNamespace(name="UV")
    loops = [Loop(index, modern) for index in range(6)]
    bm = SimpleNamespace(verts=[SimpleNamespace(select=True), SimpleNamespace(select=False)],
        edges=[SimpleNamespace(select=False)], faces=[Face(loops[:3], True, modern), Face(loops[3:], False, modern)])
    if modern:
        bm.uv_select_sync_valid = False
    return module, bm, layer, loops, modern


def state(bm, layer, loops, modern):
    return ([item.select for seq in (bm.verts, bm.edges, bm.faces) for item in seq],
        [(loop.data.uv, loop.data.pin_uv) for loop in loops],
        [(loop.uv_select_vert, loop.uv_select_edge) if modern else (loop[layer].select, loop[layer].select_edge) for loop in loops],
        [face.uv_select for face in bm.faces] if modern else None,
        bm.uv_select_sync_valid if modern else None)


@pytest.mark.parametrize("failure", [False, True])
def test_native_uv_scope_restores_complete_flags_and_sync(scope, failure):
    module, bm, layer, loops, modern = scope
    before = state(bm, layer, loops, modern)
    error = RuntimeError("operator failed")
    try:
        with module.scoped_uv_selection(bm, layer, [bm.faces[1]]):
            assert not bm.faces[0].select and bm.faces[1].select
            if modern:
                assert [(loop.uv_select_vert, loop.uv_select_edge) for loop in loops] == [(False, False)]*3+[(True, True)]*3
                assert [face.uv_select for face in bm.faces] == [False, True]
                assert bm.uv_select_sync_valid is True
            else:
                assert [(loop[layer].select, loop[layer].select_edge) for loop in loops] == [(False, False)]*3+[(True, True)]*3
            if failure:
                raise error
    except RuntimeError as caught:
        assert failure and caught is error
    assert state(bm, layer, loops, modern) == before


def test_unknown_storage_rejects_before_any_mesh_selection(scope):
    module, bm, layer, loops, modern = scope
    if modern:
        del loops[0].uv_select_edge
    else:
        del loops[0].data.select_edge
    before = [item.select for seq in (bm.verts, bm.edges, bm.faces) for item in seq]
    with pytest.raises(module.BridgeError, match="storage is unsupported"), module.scoped_uv_selection(bm, layer, [bm.faces[1]]):
        pytest.fail("unreachable")
    assert [item.select for seq in (bm.verts, bm.edges, bm.faces) for item in seq] == before


@pytest.mark.parametrize("limit", ["MAX_LOOPS", "MAX_SELECTION_ELEMENTS"])
def test_complete_selection_budgets_reject_before_writes(scope, monkeypatch, limit):
    module, bm, layer, loops, modern = scope
    monkeypatch.setattr(module, limit, 4)
    before = state(bm, layer, loops, modern)
    with pytest.raises(module.BridgeError), module.scoped_uv_selection(bm, layer, [bm.faces[1]]):
        pytest.fail("unreachable")
    assert state(bm, layer, loops, modern) == before


def test_topology_change_refuses_restoration(scope):
    module, bm, layer, _loops, _modern = scope
    with pytest.raises(module.BridgeError) as caught, module.scoped_uv_selection(bm, layer, [bm.faces[1]]):
        bm.verts.append(SimpleNamespace(select=True))
    assert caught.value.context["selection_restored"] is False
    assert caught.value.context["possible_mutation"]
    assert not bm.faces[0].select and bm.faces[1].select


def test_recovery_error_enriches_primary_bridge_error(scope):
    module, bm, layer, _loops, _modern = scope
    primary = module.BridgeError("TIMEOUT", "original deadline")
    with pytest.raises(module.BridgeError) as caught, module.scoped_uv_selection(bm, layer, [bm.faces[1]]):
        bm.verts.append(SimpleNamespace(select=True))
        raise primary
    assert caught.value is primary and caught.value.code == "TIMEOUT"
    assert caught.value.context["selection_restored"] is False


def test_inspection_uses_actual_global_or_per_layer_flag(scope):
    module, _bm, layer, loops, _modern = scope
    assert [module.corner_selection(loop, layer) for loop in loops] == [index % 3 == 0 for index in range(6)]


@pytest.mark.parametrize("primary_kind", ["bridge", "runtime", "value", "success"])
def test_final_mesh_update_preserves_primary_error(addon_package, monkeypatch, primary_kind):
    module = importlib.import_module(f"{addon_package}.tools.uv")
    monkeypatch.setattr(module, "_scoped_uv_selection", lambda *_: nullcontext())
    calls = []
    def update(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise OSError("final update failed")
    monkeypatch.setattr(module, "bmesh", SimpleNamespace(update_edit_mesh=update))
    primary = module.BridgeError("TIMEOUT", "original timeout") if primary_kind == "bridge" else RuntimeError("native operator") if primary_kind == "runtime" else ValueError("bad native value")
    def operator():
        if primary_kind != "success":
            raise primary
        return {"FINISHED"}
    with pytest.raises(module.BridgeError) as caught:
        module._run_uv_operator(SimpleNamespace(name="Mesh", data=object()), None, SimpleNamespace(name="UV"), [], operator, {}, created_layer=False)
    assert caught.value.context["final_mesh_update_failed"]
    assert caught.value.context["update_error_type"] == "OSError"
    if primary_kind == "bridge":
        assert caught.value is primary and caught.value.code == "TIMEOUT"
    else:
        assert caught.value.code == "OPERATION_FAILED"
        if primary_kind != "success":
            assert caught.value.__cause__ is primary


def test_created_layer_cleanup_never_reads_removed_native_handle(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.uv")
    monkeypatch.setattr(module, "_scoped_uv_selection", lambda *_: nullcontext())
    monkeypatch.setattr(module, "bmesh", SimpleNamespace(update_edit_mesh=lambda *a, **k: None))
    class Layer:
        removed = False
        @property
        def name(self):
            if self.removed:
                raise ReferenceError("native layer removed")
            return "CreatedUV"
    layer = Layer()
    def remove(handle):
        assert handle is layer
        handle.removed = True
    bm = SimpleNamespace(loops=SimpleNamespace(layers=SimpleNamespace(uv=SimpleNamespace(remove=remove))))
    def operator():
        raise RuntimeError("original operator")
    with pytest.raises(module.BridgeError) as caught:
        module._run_uv_operator(SimpleNamespace(name="Mesh", data=object()), bm, layer, [], operator, {}, created_layer=True)
    assert caught.value.context["uv_layer"] == "CreatedUV"
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert layer.removed
