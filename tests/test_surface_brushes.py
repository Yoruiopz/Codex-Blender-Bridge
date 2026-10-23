from __future__ import annotations

import asyncio
import importlib
import math
import time
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
    writes = 0

    def foreach_set(self, name, values):
        assert name == "color"
        self.writes += 1
        for index, item in enumerate(self):
            item.color = tuple(values[index * 4:index * 4 + 4])


class Attributes(list):
    active_color_index, render_color_index = -1, -1

    def __init__(self, mesh):
        self.mesh = mesh
        self.allocations = self.removals = 0
        super().__init__()

    def get(self, name):
        return next((attribute for attribute in self if attribute.name == name), None)

    def new(self, *, name, type, domain):
        count = len(self.mesh.vertices) if domain == "POINT" else len(self.mesh.loops)
        attribute = NS(name=name, domain=domain, data_type=type, data=Colors(NS(color=(1., 1., 1., 1.)) for _ in range(count)))
        self.append(attribute)
        self.allocations += 1
        if self.active_color_index < 0:
            self.active_color_index = self.render_color_index = 0
        return attribute

    def remove(self, attribute):
        super().remove(attribute)
        self.removals += 1


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


def publication_provider(surface, monkeypatch, action, *, publication_number=1):
    """Trigger the provider after preliminary target reads, before final proof."""
    phase = NS(active=False, number=0, target_reads=0, fired=False)
    original_publication = surface.module._publication
    original_target_read = surface.module._target_read
    original_require = surface.context.require

    def publication(*args, **kwargs):
        phase.number += 1
        phase.active, phase.target_reads = True, 0
        try:
            return original_publication(*args, **kwargs)
        finally:
            phase.active = False

    def target_read(*args, **kwargs):
        result = original_target_read(*args, **kwargs)
        if phase.active:
            phase.target_reads += 1
        return result

    def require(*permissions):
        if phase.active and phase.number == publication_number and phase.target_reads and not phase.fired:
            phase.fired = True
            action()
        return original_require(*permissions)

    monkeypatch.setattr(surface.module, "_publication", publication)
    monkeypatch.setattr(surface.module, "_target_read", target_read)
    surface.context.require = require
    return phase


def surface_operation(surface, operation):
    if operation == "sculpt":
        return lambda: sculpt(surface)
    if operation == "create":
        return lambda: create(surface)
    create(surface)
    if operation == "paint":
        return lambda: paint(surface)
    if operation == "rename":
        return lambda: surface.module.color_rename(surface.context, {
            "object_name": "Sculpt", "attribute_name": "Paint", "new_name": "Reviewed",
            "acknowledge_named_consumers": True})
    return lambda: surface.module.color_remove(surface.context, {
        "object_name": "Sculpt", "attribute_name": "Paint", "confirm_remove": True,
        "acknowledge_named_consumers": True})


def publication_counts(surface):
    return (surface.mesh.vertices.writes, surface.mesh.color_attributes.allocations,
            surface.mesh.color_attributes.removals,
            [(attr.name, attr.data.writes) for attr in surface.mesh.color_attributes])


@pytest.mark.parametrize("operation", ["sculpt", "create", "paint", "rename", "remove"])
@pytest.mark.parametrize("change,code", [
    ("pause", "AGENT_PAUSED"), ("stop", "EMERGENCY_STOPPED"),
    ("permission", "PERMISSION_DENIED"), ("coordinates", "OPERATION_FAILED"),
    ("sharing", "NOT_IMPLEMENTED"), ("context", "OPERATION_FAILED"),
])
def test_final_provider_changes_refuse_all_surface_mutators_without_writes(surface, monkeypatch, operation, change, code):
    call = surface_operation(surface, operation)
    before = publication_counts(surface)

    def provider_change():
        if change == "pause":
            surface.flags["paused"] = True
        elif change == "stop":
            surface.flags["emergency_stopped"] = True
        elif change == "permission":
            surface.grants["EDIT_MESH"] = False
        elif change == "coordinates":
            surface.mesh.vertices[1].co = (9., 8., 7.)
        elif change == "sharing":
            surface.mesh.users = 2
        else:
            surface.bpy.context.view_layer.objects.active = None

    phase = publication_provider(surface, monkeypatch, provider_change)
    with pytest.raises(surface.module.BridgeError) as caught:
        call()
    assert phase.fired and caught.value.code == code
    assert publication_counts(surface) == before
    if change == "coordinates":
        assert surface.mesh.vertices[1].co == (9., 8., 7.)
    if change == "sharing":
        assert surface.mesh.users == 2
    if change == "context":
        assert surface.bpy.context.view_layer.objects.active is None


@pytest.mark.parametrize("operation", ["create", "rename"])
def test_final_provider_generic_attribute_collision_preserves_destination(surface, monkeypatch, operation):
    call = surface_operation(surface, operation)
    attrs, generic = surface.mesh.color_attributes, {}
    surface.mesh.attributes = NS(get=lambda name: generic.get(name) or attrs.get(name))
    destination = "Paint" if operation == "create" else "Reviewed"
    inserted = NS(name=destination, domain="POINT", data_type="FLOAT", values=[.25, .5, .75, 1.])
    before = publication_counts(surface)
    phase = publication_provider(surface, monkeypatch, lambda: generic.update({destination: inserted}))
    with pytest.raises(surface.module.BridgeError) as caught:
        call()
    assert phase.fired and caught.value.code == "INVALID_ARGUMENT"
    assert generic[destination] is inserted and inserted.values == [.25, .5, .75, 1.]
    assert publication_counts(surface) == before


@pytest.mark.parametrize("operation", ["paint", "rename", "remove"])
def test_final_provider_target_color_changes_are_retained(surface, monkeypatch, operation):
    call = surface_operation(surface, operation)
    attr = surface.mesh.color_attributes.get("Paint")
    before = publication_counts(surface)
    changed = (.5, .25, .125, 1.)
    phase = publication_provider(surface, monkeypatch, lambda: setattr(attr.data[0], "color", changed))
    with pytest.raises(surface.module.BridgeError, match="attribute identity"):
        call()
    assert phase.fired and attr.data[0].color == changed
    assert surface.mesh.color_attributes.get("Paint") is attr
    assert publication_counts(surface) == before


@pytest.mark.parametrize("change", ["cancel", "deadline", "disconnect"])
def test_final_provider_caller_loss_is_checked_without_another_callback(surface, monkeypatch, change):
    queue_module = importlib.import_module(surface.module.__package__.rsplit(".", 1)[0] + ".command_queue")
    protocol = importlib.import_module(surface.module.__package__.rsplit(".", 1)[0] + ".protocol")
    lifecycle = importlib.import_module(surface.module.__package__.rsplit(".", 1)[0] + ".request_lifecycle")
    queued = queue_module.QueuedRequest(protocol.Request("surface-owner", "mesh.sculpt_brush", {}), deadline=float("inf"))
    assert queued.try_start()
    surface.context.check_final_request = queued.check_active
    connection = lifecycle.ConnectionLifetime()
    surface.context.request_lifecycle = lifecycle.RequestLifetime(connection=connection)

    def lose_owner():
        if change == "cancel":
            assert not queued.cancel_pending(surface.module.BridgeError("TIMEOUT", "Fixture cancellation"))
        elif change == "deadline":
            queued.deadline = time.monotonic() - 1.
        else:
            connection.disconnected.set()

    phase = publication_provider(surface, monkeypatch, lose_owner)
    with pytest.raises(surface.module.BridgeError) as caught:
        sculpt(surface)
    assert phase.fired and caught.value.code == "TIMEOUT" and surface.mesh.vertices.writes == 0


@pytest.mark.parametrize("operation", ["paint", "rename", "remove"])
def test_deadline_during_final_attribute_read_prevents_the_write(surface, monkeypatch, operation):
    call = surface_operation(surface, operation)
    before = publication_counts(surface)
    expired = [False]
    original = surface.module._frozen_attribute

    def frozen(*args, **kwargs):
        result = original(*args, **kwargs)
        expired[0] = True
        return result

    def check_final_request():
        if expired[0]:
            raise surface.module.BridgeError("TIMEOUT", "Fixture deadline after attribute validation")

    surface.context.check_final_request = check_final_request
    monkeypatch.setattr(surface.module, "_frozen_attribute", frozen)
    with pytest.raises(surface.module.BridgeError) as caught:
        call()
    assert expired[0] and caught.value.code == "TIMEOUT" and publication_counts(surface) == before


def test_known_post_initialization_failure_can_clean_exact_verified_owned_attribute(surface, monkeypatch):
    failure = RuntimeError("Known update failure after verified pixels")

    def fail_update():
        raise failure

    monkeypatch.setattr(surface.mesh, "update", fail_update)
    with pytest.raises(surface.module.BridgeError) as caught:
        create(surface)
    assert caught.value.__cause__ is failure
    assert surface.mesh.color_attributes.removals == 1 and not surface.mesh.color_attributes
    assert caught.value.context["retained_attribute"] is None


def test_cleanup_final_provider_pixel_edit_is_retained_with_primary_failure(surface, monkeypatch):
    failure = RuntimeError("Known update failure")

    def fail_update():
        raise failure

    monkeypatch.setattr(surface.mesh, "update", fail_update)
    changed = (.5, .25, .125, 1.)
    phase = publication_provider(surface, monkeypatch,
                                 lambda: setattr(surface.mesh.color_attributes.get("Paint").data[0], "color", changed),
                                 publication_number=2)
    with pytest.raises(surface.module.BridgeError) as caught:
        create(surface)
    assert phase.fired and caught.value.__cause__ is failure
    assert surface.mesh.color_attributes.get("Paint").data[0].color == changed
    assert surface.mesh.color_attributes.removals == 0
    assert caught.value.context["retained_attribute"] == "Paint"
    assert caught.value.context["cleanup_blocked_code"] == "OPERATION_FAILED"


def test_partial_initialization_does_not_adopt_unknown_pixels_for_cleanup(surface, monkeypatch):
    original_new = surface.mesh.color_attributes.new
    failure = RuntimeError("Partial initialization")

    def new(**kwargs):
        attr = original_new(**kwargs)

        def partial(*_):
            attr.data[0].color = (1., 0., 0., 1.)
            raise failure

        attr.data.foreach_set = partial
        return attr

    monkeypatch.setattr(surface.mesh.color_attributes, "new", new)
    with pytest.raises(surface.module.BridgeError) as caught:
        create(surface)
    attr = surface.mesh.color_attributes.get("Paint")
    assert caught.value.__cause__ is failure and surface.mesh.color_attributes.removals == 0
    assert attr.data[0].color == (1., 0., 0., 1.) and attr.data[1].color == (1., 1., 1., 1.)
    assert caught.value.context["retained_attribute"] == "Paint" and caught.value.context["possible_mutation"]


def test_primary_permission_loss_latches_cleanup_even_after_regrant(surface, monkeypatch):
    original_gate = surface.module._gate
    fired = [False]

    def gate(*args, **kwargs):
        result = original_gate(*args, **kwargs)
        attr = surface.mesh.color_attributes.get("Paint")
        if attr is not None and not fired[0]:
            fired[0] = True
            surface.grants["EDIT_MESH"] = False
            try:
                original_gate(*args, **kwargs)
            except surface.module.BridgeError:
                surface.grants["EDIT_MESH"] = True
                raise
        return result

    monkeypatch.setattr(surface.module, "_gate", gate)
    with pytest.raises(surface.module.BridgeError) as caught:
        create(surface)
    assert fired[0] and caught.value.code == "PERMISSION_DENIED" and surface.grants["EDIT_MESH"]
    assert surface.mesh.color_attributes.removals == 0 and surface.mesh.color_attributes.get("Paint") is not None
    assert caught.value.context["cleanup_authority_loss_latched"]
    assert caught.value.context["cleanup_blocked_code"] == "PERMISSION_DENIED"


def test_final_provider_signed_zero_coordinate_edit_is_not_overwritten(surface, monkeypatch):
    phase = publication_provider(surface, monkeypatch,
                                 lambda: setattr(surface.mesh.vertices[1], "co", (1., -0., 0.)))
    with pytest.raises(surface.module.BridgeError) as caught:
        sculpt(surface)
    assert phase.fired and caught.value.code == "OPERATION_FAILED" and surface.mesh.vertices.writes == 0
    assert math.copysign(1., surface.mesh.vertices[1].co[1]) == -1.


@pytest.mark.parametrize("operation", ["paint", "rename", "remove"])
def test_final_provider_signed_zero_color_edit_is_retained(surface, monkeypatch, operation):
    call = surface_operation(surface, operation)
    attr = surface.mesh.color_attributes.get("Paint")
    before = publication_counts(surface)
    phase = publication_provider(surface, monkeypatch, lambda: setattr(attr.data[0], "color", (-0., 0., 0., 1.)))
    with pytest.raises(surface.module.BridgeError, match="attribute identity"):
        call()
    assert phase.fired and publication_counts(surface) == before
    assert surface.mesh.color_attributes.get("Paint") is attr and math.copysign(1., attr.data[0].color[0]) == -1.


def test_cleanup_signed_zero_color_edit_is_retained(surface, monkeypatch):
    failure = RuntimeError("Known update failure")

    def fail_update():
        raise failure

    monkeypatch.setattr(surface.mesh, "update", fail_update)
    phase = publication_provider(surface, monkeypatch,
                                 lambda: setattr(surface.mesh.color_attributes.get("Paint").data[0], "color", (-0., 0., 0., 1.)),
                                 publication_number=2)
    with pytest.raises(surface.module.BridgeError) as caught:
        create(surface)
    attr = surface.mesh.color_attributes.get("Paint")
    assert phase.fired and caught.value.__cause__ is failure and surface.mesh.color_attributes.removals == 0
    assert attr is not None and math.copysign(1., attr.data[0].color[0]) == -1.


def test_final_provider_color_role_revision_is_preserved_before_allocation(surface, monkeypatch):
    create(surface, name="Protected A")
    create(surface, name="Protected B")
    attrs = surface.mesh.color_attributes
    before = publication_counts(surface)

    def select_roles():
        attrs.active_color_index = attrs.render_color_index = 1

    phase = publication_provider(surface, monkeypatch, select_roles)
    with pytest.raises(surface.module.BridgeError) as caught:
        create(surface)
    assert phase.fired and caught.value.code == "OPERATION_FAILED" and publication_counts(surface) == before
    assert (attrs.active_color_index, attrs.render_color_index) == (1, 1)


def test_cleanup_provider_color_role_revision_retains_owned_attribute(surface, monkeypatch):
    create(surface, name="Protected A")
    create(surface, name="Protected B")
    attrs = surface.mesh.color_attributes
    failure = RuntimeError("Known update failure")

    def fail_update():
        raise failure

    def select_roles():
        attrs.active_color_index = attrs.render_color_index = 2

    monkeypatch.setattr(surface.mesh, "update", fail_update)
    phase = publication_provider(surface, monkeypatch, select_roles, publication_number=2)
    with pytest.raises(surface.module.BridgeError) as caught:
        create(surface)
    assert phase.fired and caught.value.__cause__ is failure and attrs.removals == 0
    assert attrs.get("Paint") is not None and (attrs.active_color_index, attrs.render_color_index) == (2, 2)
    assert caught.value.context["cleanup_blocked_code"] == "OPERATION_FAILED"


@pytest.mark.parametrize("flag", ["paused", "emergency_stopped"])
def test_color_inspection_remains_available_while_mutations_are_stopped(surface, flag):
    create(surface)
    surface.flags[flag] = True
    result = surface.module.color_inspect(surface.context, {"object_name": "Sculpt", "attribute_name": "Paint"})
    assert result["entry_count"] == 4 and len(result["entries"]) == 4 and not result["truncated"]


def test_deadline_during_final_coordinate_read_prevents_publication(surface, monkeypatch):
    expired = [False]
    phase = publication_provider(surface, monkeypatch, lambda: None)
    original = surface.module._positions

    def positions(*args, **kwargs):
        result = original(*args, **kwargs)
        if phase.active and phase.fired:
            expired[0] = True
        return result

    def check_final_request():
        if expired[0]:
            raise surface.module.BridgeError("TIMEOUT", "Fixture deadline during coordinate proof")

    surface.context.check_final_request = check_final_request
    monkeypatch.setattr(surface.module, "_positions", positions)
    with pytest.raises(surface.module.BridgeError) as caught:
        sculpt(surface)
    assert phase.fired and expired[0] and caught.value.code == "TIMEOUT" and surface.mesh.vertices.writes == 0
