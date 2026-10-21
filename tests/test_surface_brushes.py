from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.surface_brushes import ColorStroke, SculptStroke, SurfaceBrushTools


class Vertices(list):
    fail = False
    writes = 0

    def foreach_set(self, name, values):
        assert name == "co"
        self.writes += 1
        for index, vertex in enumerate(self):
            vertex.co = tuple(values[index * 3:index * 3 + 3])
            if self.fail:
                raise RuntimeError("Injected partial coordinate publication")


class Colors(list):
    def foreach_set(self, name, values):
        assert name == "color"
        for index, item in enumerate(self):
            item.color = tuple(values[index * 4:index * 4 + 4])


class Attributes(list):
    active_color_index, render_color_index = -1, -1

    def __init__(self, mesh):
        self.mesh = mesh
        super().__init__()

    def get(self, name):
        return next((attribute for attribute in self if attribute.name == name), None)

    def new(self, *, name, type, domain):
        count = len(self.mesh.vertices) if domain == "POINT" else len(self.mesh.loops)
        attribute = NS(name=name, domain=domain, data_type=type, data=Colors(NS(color=(0., 0., 0., 0.)) for _ in range(count)))
        self.append(attribute)
        if self.active_color_index < 0:
            self.active_color_index = self.render_color_index = 0
        return attribute


class UVLayers(list):
    active_index = -1


@pytest.fixture
def surface(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.surface_brushes")
    vertices = Vertices(NS(index=index, co=position, select=False, hide=False) for index, position in
                        enumerate(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (2., 0., 0.))))
    edges = [NS(vertices=(0, 1), select=False, hide=False), NS(vertices=(0, 2), select=False, hide=False),
             NS(vertices=(1, 3), select=False, hide=False)]
    mesh = NS(name="Mesh", users=1, library=None, override_library=None, is_editable=True, shape_keys=None,
              vertices=vertices, edges=edges, loops=[NS(vertex_index=value) for value in (0, 1, 2, 0, 2, 3)],
              polygons=[NS(loop_start=0, loop_total=3, material_index=0, use_smooth=False, select=False, hide=False),
                        NS(loop_start=3, loop_total=3, material_index=0, use_smooth=False, select=False, hide=False)],
              uv_layers=UVLayers(), update=lambda: None)
    mesh.color_attributes = mesh.attributes = Attributes(mesh)
    obj = NS(name="Sculpt", type="MESH", data=mesh, mode="OBJECT", library=None, override_library=None,
             is_editable=True, modifiers=[], hide_viewport=False, material_slots=[],
             matrix_world=((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.)))
    bpy = NS(data=NS(objects=[obj]), context=NS(mode="OBJECT", selected_objects=[obj],
             view_layer=NS(objects=NS(active=obj))))
    grants = {"EDIT_MESH": True, "INSPECT_SCENE": True, "DELETE_OBJECTS": True}
    flags = {"paused": False, "emergency_stopped": False}
    def require(*permissions):
        if any(not grants.get(permission.value, False) for permission in permissions):
            raise module.BridgeError("PERMISSION_DENIED", "Denied")
    context = NS(require=require, check_cancelled=None, state=NS(snapshot=lambda: dict(flags)))
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    return NS(module=module, bpy=bpy, obj=obj, mesh=mesh, context=context, grants=grants, flags=flags)


def push(**values):
    return {"center": [0., 0., 0.], "radius": 1., "direction": [0., 0., 1.], "strength": .5, **values}


def sculpt(surface, **values):
    return surface.module.sculpt_brush(surface.context, {"object_name": "Sculpt", "vertex_indices": [0], "strokes": [push()], **values})


def create(surface, name="Paint", **values):
    return surface.module.color_create(surface.context, {"object_name": "Sculpt", "attribute_name": name, **values})


def paint(surface, **values):
    return surface.module.color_paint(surface.context, {"object_name": "Sculpt", "attribute_name": "Paint", "vertex_indices": [0],
        "strokes": [{"center": [0., 0., 0.], "radius": 1., "color": [1., 0., 0., 1.], "falloff": "CONSTANT"}], **values})


def test_push_real_coordinates_without_mode_entry_or_unrelated_changes(surface):
    before = surface.module._preservation(surface.bpy, surface.obj)
    result = sculpt(surface)
    assert surface.mesh.vertices[0].co == (0., 0., .5)
    assert [vertex.co for vertex in surface.mesh.vertices[1:]] == [(1., 0., 0.), (0., 1., 0.), (2., 0., 0.)]
    assert result["changed_vertices"] == 1 and result["protected_vertices_verified"]
    assert surface.module._preservation(surface.bpy, surface.obj) == before


def test_zero_mask_and_outside_radius_vertices_remain_exactly_protected(surface):
    result = sculpt(surface, vertex_indices=[0, 1, 3], mask_weights=[0., 1., 1.], strokes=[push(radius=.5)])
    assert result["changed_vertices"] == 0
    assert [vertex.co for vertex in surface.mesh.vertices] == [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (2., 0., 0.)]


def test_smoothing_is_frozen_and_independent_of_component_order(surface):
    module = surface.module
    positions, edges = [(0., 0., 0.), (1., 0., 0.), (4., 0., 0.)], [(0, 1), (1, 2)]
    strokes = module._strokes([{"center": [0., 0., 0.], "radius": 10., "operation": "SMOOTH", "strength": 1., "falloff": "CONSTANT"}])
    forward = module.sculpt_values(positions, edges, [0, 1, 2], [1.] * 3, strokes)
    reverse = module.sculpt_values(positions, edges, [2, 1, 0], [1.] * 3, strokes)
    assert forward == reverse == [(1., 0., 0.), (2., 0., 0.), (1., 0., 0.)]
    assert positions == [(0., 0., 0.), (1., 0., 0.), (4., 0., 0.)]


@pytest.mark.parametrize("falloff,expected", [("SMOOTH", .5), ("LINEAR", .5), ("CONSTANT", 1.)])
def test_falloff_and_normalized_push_direction(surface, falloff, expected):
    strokes = surface.module._strokes([push(center=[.5, 0., 0.], radius=1., direction=[0., 0., 9.], strength=1., falloff=falloff)])
    result = surface.module.sculpt_values([(0., 0., 0.)], [], [0], [1.], strokes)
    assert result[0][2] == expected


@pytest.mark.parametrize("change", [{"radius": 0.}, {"radius": True}, {"strength": float("nan")}, {"direction": [0., 0., 0.]},
                                    {"center": [True, 0., 0.]}, {"operation": "INFLATE"}, {"falloff": "AUTO"},
                                    {"operation": "SMOOTH", "strength": 2.}, {"script": "bpy.ops.mesh.delete()"}])
def test_invalid_stroke_has_no_publication(surface, change):
    with pytest.raises(surface.module.BridgeError):
        sculpt(surface, strokes=[push(**change)])
    assert surface.mesh.vertices.writes == 0


@pytest.mark.parametrize("values", [{"vertex_indices": [0, 0]}, {"vertex_indices": [True]}, {"vertex_indices": [4]},
                                    {"mask_weights": [1., 0.]}, {"mask_weights": [2.]}, {"space": "VIEW"}])
def test_invalid_component_mask_is_refused_before_write(surface, values):
    with pytest.raises(surface.module.BridgeError):
        sculpt(surface, **values)
    assert surface.mesh.vertices.writes == 0


@pytest.mark.parametrize("change", ["shared", "linked", "override", "readonly", "shape_keys", "modifier", "edit", "hidden"])
def test_unsupported_mesh_scope_is_refused_before_write(surface, change):
    if change == "shared":
        surface.mesh.users = 2
    elif change == "linked":
        surface.mesh.library = object()
    elif change == "override":
        surface.obj.override_library = object()
    elif change == "readonly":
        surface.obj.is_editable = False
    elif change == "shape_keys":
        surface.mesh.shape_keys = object()
    elif change == "modifier":
        surface.obj.modifiers = [object()]
    elif change == "edit":
        surface.obj.mode = "EDIT"
    else:
        surface.mesh.vertices[0].hide = True
    with pytest.raises(surface.module.BridgeError):
        sculpt(surface)
    assert surface.mesh.vertices.writes == 0


def test_permission_denial_precedes_blender_read(surface, monkeypatch):
    surface.grants["EDIT_MESH"] = False
    monkeypatch.setattr(surface.module, "require_blender", lambda: pytest.fail("Denied Blender read"))
    with pytest.raises(surface.module.BridgeError, match="Denied"):
        sculpt(surface)


@pytest.mark.parametrize("flag,code", [("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")])
def test_pause_and_stop_prevent_surface_publication(surface, flag, code):
    surface.flags[flag] = True
    with pytest.raises(surface.module.BridgeError) as caught:
        sculpt(surface)
    assert caught.value.code == code and surface.mesh.vertices.writes == 0


def test_partial_native_write_never_fabricates_rollback(surface):
    surface.mesh.vertices.fail = True
    with pytest.raises(surface.module.BridgeError) as caught:
        sculpt(surface)
    assert caught.value.context["execution_started"] and caught.value.context["possible_mutation"]
    assert not caught.value.context["rollback_verified"]
    assert surface.mesh.vertices[0].co == (0., 0., .5)


def test_late_permission_revocation_reports_possible_mutation(surface):
    def revoke():
        if surface.mesh.vertices.writes:
            surface.grants["EDIT_MESH"] = False
    surface.context.check_cancelled = revoke
    with pytest.raises(surface.module.BridgeError) as caught:
        sculpt(surface)
    assert caught.value.code == "PERMISSION_DENIED" and caught.value.context["possible_mutation"]
    assert surface.mesh.vertices[0].co == (0., 0., .5)


def test_point_color_lifecycle_and_paint_keeps_geometry_and_other_colors(surface):
    create(surface, initial_color=[.25, .5, .75, 1.])
    create(surface, name="Protected", initial_color=[.1, .2, .3, 1.])
    before = surface.module._preservation(surface.bpy, surface.obj, exclude_color="Paint")
    result = paint(surface)
    assert result["changed_entries"] == 1
    assert surface.mesh.color_attributes.get("Paint").data[0].color == (1., 0., 0., 1.)
    assert surface.module._preservation(surface.bpy, surface.obj, exclude_color="Paint") == before
    inspected = surface.module.color_inspect(surface.context, {"object_name": "Sculpt", "attribute_name": "Paint", "max_entries": 2})
    assert inspected["truncated"] and inspected["next_offset"] == 2 and len(inspected["complete_colors_sha256_float32_le"]) == 64


def test_corner_paint_changes_all_scoped_vertex_corners_only(surface):
    create(surface, domain="CORNER", initial_color=[0., 0., 1., 1.])
    result = paint(surface)
    colors = [item.color for item in surface.mesh.color_attributes[0].data]
    assert result["changed_entries"] == 2 and colors[0] == colors[3] == (1., 0., 0., 1.)
    assert all(color == (0., 0., 1., 1.) for index, color in enumerate(colors) if index not in (0, 3))


def test_color_kernel_preserves_corner_variants_and_zero_mask(surface):
    strokes = surface.module._strokes([{"center": [0., 0., 0.], "radius": 2., "color": [1., 0., 0., 1.], "opacity": .5, "falloff": "CONSTANT"}], color=True)
    colors = [(0., 0., 1., 1.), (0., 1., 0., 1.), (.5, .5, .5, 1.)]
    actual = surface.module.paint_values(colors, [0, 0, 1], [(0., 0., 0.), (1., 0., 0.)], [0, 1], [1., 0.], strokes)
    assert actual == [(.5, 0., .5, 1.), (.5, .5, 0., 1.), colors[2]]
    assert colors[0] == (0., 0., 1., 1.)


def test_color_rename_remove_fail_closed_without_named_consumer_acknowledgment(surface):
    create(surface)
    with pytest.raises(surface.module.BridgeError, match="acknowledge_named_consumers"):
        surface.module.color_rename(surface.context, {"object_name": "Sculpt", "attribute_name": "Paint", "new_name": "Reviewed"})
    renamed = surface.module.color_rename(surface.context, {"object_name": "Sculpt", "attribute_name": "Paint", "new_name": "Reviewed", "acknowledge_named_consumers": True})
    assert not renamed["named_consumers_rewritten"] and surface.mesh.color_attributes.get("Reviewed") is not None
    with pytest.raises(surface.module.BridgeError, match="confirm_remove"):
        surface.module.color_remove(surface.context, {"object_name": "Sculpt", "attribute_name": "Reviewed"})
    surface.grants["DELETE_OBJECTS"] = False
    with pytest.raises(surface.module.BridgeError, match="Denied"):
        surface.module.color_remove(surface.context, {"object_name": "Sculpt", "attribute_name": "Reviewed", "confirm_remove": True, "acknowledge_named_consumers": True})
    assert surface.mesh.color_attributes.get("Reviewed") is not None
    surface.grants["DELETE_OBJECTS"] = True
    result = surface.module.color_remove(surface.context, {"object_name": "Sculpt", "attribute_name": "Reviewed", "confirm_remove": True, "acknowledge_named_consumers": True})
    assert result["removed_attribute"] == "Reviewed" and not surface.mesh.color_attributes


def test_mcp_strict_strokes_validate_operations_and_forward_typed_inputs():
    with pytest.raises(ValidationError):
        SculptStroke(center=[0., 0., 0.], direction=[0., 0., 0.])
    with pytest.raises(ValidationError):
        SculptStroke(center=[0., 0., 0.], operation="SMOOTH", strength=-.1)
    with pytest.raises(ValidationError):
        ColorStroke(center=[0., 0., 0.], color=[2., 0., 0., 1.])
    hints = get_type_hints(SurfaceBrushTools.mesh_sculpt_brush, include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(hints["vertex_indices"]).validate_python([True])
    calls = []
    class Registry:
        async def call(self, name, values):
            calls.append((name, values))
            return {}
    stroke = SculptStroke(center=[0., 0., 0.], direction=[0., 0., 1.])
    tools = SurfaceBrushTools(Registry())
    asyncio.run(tools.mesh_sculpt_brush("Sculpt", [0], [stroke], mask_weights=[0.]))
    assert calls[0][0] == "mesh.sculpt_brush" and calls[0][1]["mask_weights"] == [0.]
    assert calls[0][1]["strokes"][0]["operation"] == "PUSH"


def test_candidate_budget_rejects_before_kernel_iteration(surface, monkeypatch):
    monkeypatch.setattr(surface.module, "MAX_TESTS", 1)
    strokes = surface.module._strokes([push()])
    with pytest.raises(surface.module.BridgeError, match="candidate tests"):
        surface.module.sculpt_values([], [], [0, 1], [1., 1.], strokes)


def test_final_delete_callback_cannot_expand_to_shared_mesh(surface):
    create(surface)
    original_require = surface.context.require
    deletion_checks = [0]
    def require(*permissions):
        if any(permission.value == "DELETE_OBJECTS" for permission in permissions):
            deletion_checks[0] += 1
        original_require(*permissions)
    surface.context.require = require
    def share_at_publication():
        if deletion_checks[0] >= 3:
            surface.mesh.users = 2
    surface.context.check_cancelled = share_at_publication
    with pytest.raises(surface.module.BridgeError):
        surface.module.color_remove(surface.context, {"object_name": "Sculpt", "attribute_name": "Paint", "confirm_remove": True,
                                                       "acknowledge_named_consumers": True})
    assert surface.mesh.color_attributes.get("Paint") is not None


def test_create_cleanup_refuses_new_shared_scope(surface, monkeypatch):
    original_new = surface.mesh.color_attributes.new
    def failing_attribute(**kwargs):
        attribute = original_new(**kwargs)
        def fail(*_):
            raise RuntimeError("Injected attribute initialization failure")
        attribute.data.foreach_set = fail
        return attribute
    monkeypatch.setattr(surface.mesh.color_attributes, "new", failing_attribute)
    original_require = surface.context.require
    deleting = [False]
    def require(*permissions):
        if any(permission.value == "DELETE_OBJECTS" for permission in permissions):
            deleting[0] = True
        original_require(*permissions)
    surface.context.require = require
    def share_during_cleanup():
        if deleting[0]:
            surface.mesh.users = 2
    surface.context.check_cancelled = share_during_cleanup
    with pytest.raises(surface.module.BridgeError) as caught:
        create(surface)
    assert caught.value.context["retained_attribute"] == "Paint"
    assert not caught.value.context["cleanup_permission_denied"]
    assert caught.value.context["cleanup_blocked_code"] == "NOT_IMPLEMENTED"
    assert surface.mesh.color_attributes.get("Paint") is not None


def test_cleanup_denial_reports_actual_renamed_owned_attribute(surface, monkeypatch):
    original_new = surface.mesh.color_attributes.new
    def failing_attribute(**kwargs):
        attribute = original_new(**kwargs)
        def fail(*_):
            raise RuntimeError("Injected attribute initialization failure")
        attribute.data.foreach_set = fail
        return attribute
    monkeypatch.setattr(surface.mesh.color_attributes, "new", failing_attribute)
    original_require = surface.context.require
    deleting = [False]
    def require(*permissions):
        if any(permission.value == "DELETE_OBJECTS" for permission in permissions):
            deleting[0] = True
        original_require(*permissions)
    surface.context.require = require
    def rename_then_revoke_cleanup():
        if deleting[0]:
            attribute = surface.mesh.color_attributes.get("Paint")
            if attribute is not None:
                attribute.name = "Retained Actual"
            surface.grants["DELETE_OBJECTS"] = False
    surface.context.check_cancelled = rename_then_revoke_cleanup
    with pytest.raises(surface.module.BridgeError) as caught:
        create(surface)
    assert caught.value.context["retained_attribute"] == "Retained Actual"
    assert caught.value.context["cleanup_permission_denied"] and caught.value.context["retained_name_is_last_observed"]
    assert surface.mesh.color_attributes.get("Retained Actual") is not None


def test_inspection_rejects_mixed_stale_name_and_old_color_evidence(surface):
    create(surface)
    checks = [0]
    def rename_after_capture():
        checks[0] += 1
        if checks[0] == 2:
            surface.mesh.color_attributes[0].name = "Changed During Inspect"
    surface.context.check_cancelled = rename_after_capture
    with pytest.raises(surface.module.BridgeError) as caught:
        surface.module.color_inspect(surface.context, {"object_name": "Sculpt", "attribute_name": "Paint"})
    assert caught.value.code == "OPERATION_FAILED" and caught.value.context["stale_evidence"]


@pytest.mark.parametrize("change", ["colors", "replacement"])
def test_final_delete_callback_cannot_delete_changed_attribute_input(surface, change):
    create(surface)
    original_require = surface.context.require
    deletion_checks, changed = [0], [False]
    def require(*permissions):
        if any(permission.value == "DELETE_OBJECTS" for permission in permissions):
            deletion_checks[0] += 1
        original_require(*permissions)
    surface.context.require = require
    def replace_at_final_gate():
        if deletion_checks[0] >= 3 and not changed[0]:
            changed[0] = True
            attribute = surface.mesh.color_attributes.get("Paint")
            if change == "colors":
                attribute.data[0].color = (1., 0., 0., 1.)
            else:
                surface.mesh.color_attributes.remove(attribute)
                surface.mesh.color_attributes.new(name="Paint", type="FLOAT_COLOR", domain="POINT")
    surface.context.check_cancelled = replace_at_final_gate
    with pytest.raises(surface.module.BridgeError, match="attribute identity"):
        surface.module.color_remove(surface.context, {"object_name": "Sculpt", "attribute_name": "Paint", "confirm_remove": True,
                                                       "acknowledge_named_consumers": True})
    assert surface.mesh.color_attributes.get("Paint") is not None


def test_rename_refuses_changed_target_values_before_name_mutation(surface):
    create(surface)
    checks = [0]
    def change_after_capture():
        checks[0] += 1
        if checks[0] == 2:
            surface.mesh.color_attributes[0].data[0].color = (1., 0., 0., 1.)
    surface.context.check_cancelled = change_after_capture
    with pytest.raises(surface.module.BridgeError, match="attribute identity"):
        surface.module.color_rename(surface.context, {"object_name": "Sculpt", "attribute_name": "Paint", "new_name": "Reviewed",
                                                       "acknowledge_named_consumers": True})
    assert surface.mesh.color_attributes.get("Paint") is not None and surface.mesh.color_attributes.get("Reviewed") is None


class NativeProxy:
    def __init__(self, wrapped):
        object.__setattr__(self, "_wrapped", wrapped)
        object.__setattr__(self, "_alive", True)

    def __getattr__(self, name):
        if not self._alive:
            raise ReferenceError("Native RNA ID removed")
        return getattr(self._wrapped, name)

    def __setattr__(self, name, value):
        if name in {"_wrapped", "_alive"}:
            object.__setattr__(self, name, value)
        else:
            if not self._alive:
                raise ReferenceError("Native RNA ID removed")
            setattr(self._wrapped, name, value)


def test_removed_native_object_after_write_keeps_structured_mutation_evidence(surface):
    proxy = NativeProxy(surface.obj)
    surface.bpy.data.objects[:] = [proxy]
    surface.bpy.context.selected_objects = [proxy]
    surface.bpy.context.view_layer.objects.active = proxy
    def remove_after_publication():
        if surface.mesh.vertices.writes:
            proxy._alive = False
    surface.context.check_cancelled = remove_after_publication
    with pytest.raises(surface.module.BridgeError) as caught:
        sculpt(surface)
    assert caught.value.context["affected_object"] == "Sculpt" and caught.value.context["possible_mutation"]


def test_removed_native_attribute_after_write_keeps_stable_name_evidence(surface, monkeypatch):
    create(surface)
    proxy = NativeProxy(surface.mesh.color_attributes[0])
    surface.mesh.color_attributes[0] = proxy
    wrote = [False]
    original_write = proxy.data.foreach_set
    def write(*args):
        original_write(*args)
        wrote[0] = True
    monkeypatch.setattr(proxy.data, "foreach_set", write)
    def remove_after_publication():
        if wrote[0]:
            proxy._alive = False
    surface.context.check_cancelled = remove_after_publication
    with pytest.raises(surface.module.BridgeError) as caught:
        paint(surface)
    assert caught.value.context["attribute_name"] == "Paint" and caught.value.context["possible_mutation"]
