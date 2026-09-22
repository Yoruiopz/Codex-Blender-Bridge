"""Explicit, bounded object context and mesh-component selection controls."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import (
    clear_selection_references,
    inspect_selection,
    validate_selection_reference,
)
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, get_object, int_param, reject_unknown_params, require_blender

try:
    import bmesh  # type: ignore
except ImportError:  # pragma: no cover
    bmesh = None  # type: ignore

MAX_OBJECTS = 200
MAX_COMPONENT_INDICES = 20_000
MAX_MESH_ELEMENTS = 200_000
_OPERATIONS = {"REPLACE", "ADD", "REMOVE"}
_MESH_MODES = {"EDIT", "SCULPT", "VERTEX_PAINT", "WEIGHT_PAINT", "TEXTURE_PAINT"}


def _enum(value: Any, name: str, choices: set[str]) -> str:
    if not isinstance(value, str) or value.upper() not in choices:
        raise invalid_argument(f"'{name}' must be one of {', '.join(sorted(choices))}.")
    return value.upper()


def _name(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise invalid_argument(f"'{name}' must be a non-empty string of at most 256 characters.")
    return value


def _names(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_OBJECTS:
        raise invalid_argument(f"'object_names' must be an array of at most {MAX_OBJECTS} names.")
    names = [_name(item, "object_names item") for item in value]
    if len(set(names)) != len(names):
        raise invalid_argument("'object_names' must not contain duplicate names.")
    return names


def _indices(value: Any) -> list[int]:
    if not isinstance(value, list) or len(value) > MAX_COMPONENT_INDICES:
        raise invalid_argument(
            f"'indices' must be an array of at most {MAX_COMPONENT_INDICES} indices."
        )
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value):
        raise invalid_argument("'indices' must contain non-negative integers, not booleans.")
    if len(set(value)) != len(value):
        raise invalid_argument("'indices' must not contain duplicates.")
    return list(value)


def _in_view_layer(bpy: Any, name: str) -> Any:
    obj = get_object(name, allow_active=False)
    if bpy.context.view_layer.objects.get(name) != obj:
        raise BridgeError(
            ErrorCode.BLENDER_CONTEXT_ERROR,
            f"Object '{name}' is not in the current view layer.",
            {"object": name, "view_layer": bpy.context.view_layer.name},
        )
    return obj


def _selectable(obj: Any) -> None:
    if obj.hide_select or not obj.visible_get():
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            f"Object '{obj.name}' is hidden or selection-locked; visibility is not changed implicitly.",
            {"object": obj.name},
        )


def _selected(bpy: Any) -> list[Any]:
    selected = list(bpy.context.selected_objects)
    if len(selected) > MAX_OBJECTS:
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            "Current object selection exceeds the bounded interaction limit.",
            {"selected_object_count": len(selected), "maximum_objects": MAX_OBJECTS},
        )
    return selected


def _restore_context(bpy: Any, selected: list[Any], active: Any, mode: str) -> bool:
    """Best-effort failure recovery; callers report whether it was successful."""
    try:
        current = bpy.context.view_layer.objects.active
        if (
            current is not None
            and current.mode != "OBJECT"
            and "FINISHED" not in bpy.ops.object.mode_set(mode="OBJECT")
        ):
            return False
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active
        if (
            active is not None
            and mode != "OBJECT"
            and "FINISHED" not in bpy.ops.object.mode_set(mode=mode)
        ):
            return False
        return (
            set(bpy.context.selected_objects) == set(selected)
            and bpy.context.view_layer.objects.active == active
            and (active is None or active.mode == mode)
        )
    except (RuntimeError, ReferenceError):
        return False


def set_selection(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Intentionally change Object Mode selection without changing mode or visibility."""
    reject_unknown_params(params, {"object_names", "operation", "active_object"})
    del context
    names = _names(params.get("object_names"))
    operation = _enum(params.get("operation", "REPLACE"), "operation", _OPERATIONS)
    active_name = params.get("active_object")
    if active_name is not None:
        active_name = _name(active_name, "active_object")
    bpy = require_blender()
    if bpy.context.mode != "OBJECT":
        raise BridgeError(
            ErrorCode.INVALID_MODE,
            "selection.set requires Object Mode; use context.set_mode explicitly first.",
        )
    selected = _selected(bpy)
    objects = [_in_view_layer(bpy, name) for name in names]
    old_active = bpy.context.view_layer.objects.active
    old_by_name = {obj.name: obj for obj in selected}
    desired = dict(old_by_name) if operation != "REPLACE" else {}
    for obj in objects:
        if operation == "REMOVE":
            desired.pop(obj.name, None)
        else:
            _selectable(obj)
            desired[obj.name] = obj
    if len(desired) > MAX_OBJECTS:
        raise invalid_argument(f"Resulting selection exceeds {MAX_OBJECTS} objects.")
    if active_name is not None and active_name not in desired:
        raise invalid_argument("'active_object' must belong to the resulting selection.")
    new_active = (
        desired.get(active_name)
        if active_name is not None
        else (old_active if old_active is not None and old_active.name in desired else None)
    )
    if new_active is not None:
        _selectable(new_active)
    before = inspect_selection({"create_selection_id": False})
    try:
        for obj in selected:
            if obj.name not in desired:
                obj.select_set(False)
        for obj in desired.values():
            obj.select_set(True)
        bpy.context.view_layer.objects.active = new_active
        if {obj.name for obj in bpy.context.selected_objects} != set(desired):
            raise RuntimeError("Object selection verification failed")
        if bpy.context.view_layer.objects.active != new_active:
            raise RuntimeError("Active object verification failed")
    except (RuntimeError, ReferenceError) as exc:
        restored = _restore_context(bpy, selected, old_active, "OBJECT")
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender could not set the requested object selection.",
            {
                "execution_started": True,
                "context_restored": restored,
                "verification_required": not restored,
            },
        ) from exc
    return {
        "changed": set(old_by_name) != set(desired) or old_active != new_active,
        "operation_type": operation,
        "affected_objects": sorted(set(old_by_name) | set(desired)),
        "before": before,
        "selection": inspect_selection({"create_selection_id": False}),
    }


def set_mode(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Enter one named object's mode; non-Object modes isolate its object selection."""
    reject_unknown_params(params, {"object_name", "mode"})
    name = _name(params.get("object_name"), "object_name")
    mode = _enum(params.get("mode"), "mode", {"OBJECT", "POSE", *_MESH_MODES})
    bpy = require_blender()
    obj = _in_view_layer(bpy, name)
    old_active = bpy.context.view_layer.objects.active
    old_mode = old_active.mode if old_active is not None else "OBJECT"
    selected = _selected(bpy)
    if old_mode != "OBJECT" and old_active != obj:
        raise BridgeError(
            ErrorCode.INVALID_MODE,
            "Exit the current active object's mode before targeting another object.",
        )
    if len(list(getattr(bpy.context, "objects_in_mode", ()))) > 1:
        raise BridgeError(
            ErrorCode.INVALID_MODE,
            "Multi-object modes are not changed implicitly; isolate the target first.",
        )
    if mode != "OBJECT":
        _selectable(obj)
        if not obj.is_editable or (obj.data is not None and not obj.data.is_editable):
            raise BridgeError(
                ErrorCode.INVALID_ARGUMENT, "The target object and its data must be editable."
            )
        if obj.type == "MESH" and mode in _MESH_MODES:
            context.require(Permission.EDIT_MESH)
        elif obj.type == "ARMATURE" and mode in {"EDIT", "POSE"}:
            context.require(Permission.EDIT_ANIMATION)
        else:
            raise invalid_argument(
                "This target does not support the requested structured mode.",
                object_type=obj.type,
                requested_mode=mode,
            )
    before = inspect_selection({"create_selection_id": False})
    if old_active == obj and old_mode == mode:
        return {
            "changed": False,
            "object": obj.name,
            "affected_objects": [],
            "before": before,
            "selection": inspect_selection(),
        }
    try:
        if mode == "OBJECT":
            if obj.mode != "OBJECT" and "FINISHED" not in bpy.ops.object.mode_set(mode="OBJECT"):
                raise RuntimeError("Object Mode transition did not finish")
        else:
            if old_mode != "OBJECT" and "FINISHED" not in bpy.ops.object.mode_set(mode="OBJECT"):
                raise RuntimeError("Mode exit did not finish")
            for item in selected:
                item.select_set(False)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            if not bpy.ops.object.mode_set.poll():
                raise RuntimeError("Mode operator is unavailable in this context")
            if "FINISHED" not in bpy.ops.object.mode_set(mode=mode):
                raise RuntimeError("Mode transition did not finish")
        if obj.mode != mode:
            raise RuntimeError("Mode verification failed")
    except (RuntimeError, ReferenceError) as exc:
        restored = _restore_context(bpy, selected, old_active, old_mode)
        clear_selection_references()
        raise BridgeError(
            ErrorCode.BLENDER_CONTEXT_ERROR,
            "Blender could not enter the requested mode in the current context.",
            {
                "object": obj.name,
                "requested_mode": mode,
                "execution_started": True,
                "context_restored": restored,
                "verification_required": not restored,
            },
        ) from exc
    clear_selection_references()
    return {
        "changed": old_mode != mode or (mode != "OBJECT" and old_active != obj),
        "object": obj.name,
        "affected_objects": sorted({obj.name, *(item.name for item in selected)}),
        "selection_isolated": mode != "OBJECT",
        "before": before,
        "selection": inspect_selection(),
    }


def _active_edit_mesh(name: str) -> tuple[Any, Any, Any, dict[str, Any]]:
    bpy = require_blender()
    obj = _in_view_layer(bpy, name)
    if obj.type != "MESH" or obj.mode != "EDIT" or bpy.context.view_layer.objects.active != obj:
        raise BridgeError(
            ErrorCode.INVALID_MODE, "The named mesh must be the active object in Edit Mode."
        )
    if len(list(bpy.context.objects_in_mode)) != 1:
        raise BridgeError(
            ErrorCode.INVALID_MODE, "Component selection requires single-object Edit Mode."
        )
    if bmesh is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "bmesh is unavailable.")
    bm = bmesh.from_edit_mesh(obj.data)
    sequences = {"VERT": bm.verts, "EDGE": bm.edges, "FACE": bm.faces}
    if sum(len(items) for items in sequences.values()) > MAX_MESH_ELEMENTS:
        raise invalid_argument(
            "Mesh exceeds the bounded component-selection limit.",
            maximum_elements=MAX_MESH_ELEMENTS,
        )
    for items in sequences.values():
        items.ensure_lookup_table()
        items.index_update()
    return bpy, obj, bm, sequences


def inspect_components(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Read paginated, measured component geometry without changing the selection."""
    del context
    name = _name(params.get("object_name"), "object_name")
    element_type = _enum(params.get("element_type"), "element_type", {"VERT", "EDGE", "FACE"})
    offset = int_param(params, "offset", 0, minimum=0, maximum=MAX_MESH_ELEMENTS)
    max_items = int_param(params, "max_items", 100, minimum=1, maximum=256)
    selected_only = bool_param(params, "selected_only", False)
    _bpy, obj, _bm, sequences = _active_edit_mesh(name)
    sequence = sequences[element_type]
    matching = [item for item in sequence if not selected_only or item.select]
    items: list[dict[str, Any]] = []
    for element in matching[offset : offset + max_items]:
        detail: dict[str, Any] = {
            "index": element.index,
            "selected": bool(element.select),
            "hidden": bool(element.hide),
        }
        if element_type == "VERT":
            center = element.co
            detail["normal_local"] = list(element.normal)
        elif element_type == "EDGE":
            center = (element.verts[0].co + element.verts[1].co) * 0.5
            detail["vertex_indices"] = [vertex.index for vertex in element.verts]
            detail["length_world"] = float(
                (
                    (obj.matrix_world @ element.verts[1].co)
                    - (obj.matrix_world @ element.verts[0].co)
                ).length
            )
        else:
            center = element.calc_center_median()
            detail["vertex_indices"] = [
                element.verts[index].index for index in range(min(len(element.verts), 64))
            ]
            detail["vertex_count"] = len(element.verts)
            detail["vertex_indices_truncated"] = len(element.verts) > 64
            detail["normal_local"] = list(element.normal)
            detail["material_index"] = element.material_index
        detail["center_local"] = [float(value) for value in center]
        detail["center_world"] = [float(value) for value in obj.matrix_world @ center]
        items.append(detail)
    next_offset = offset + len(items)
    more = next_offset < len(matching)
    return {
        "object": obj.name,
        "element_type": element_type,
        "component_count": len(sequence),
        "matching_component_count": len(matching),
        "selected_only": selected_only,
        "offset": offset,
        "items": items,
        "truncated": more,
        "next_offset": next_offset if more else None,
        "mesh_counts": {kind: len(values) for kind, values in sequences.items()},
        "index_validity": "Session-local indices; reinspect after topology edits, mode changes, undo, or file reload. Pass the returned selection_id when selecting these indices to reject stale topology/context.",
        "selection": inspect_selection(),
    }


def select_components(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Select exact component indices, with dependent components flushed consistently."""
    reject_unknown_params(params, {"object_name", "element_type", "indices", "operation", "selection_id"})
    del context
    name = _name(params.get("object_name"), "object_name")
    indices = _indices(params.get("indices"))
    element_type = _enum(params.get("element_type"), "element_type", {"VERT", "EDGE", "FACE"})
    operation = _enum(params.get("operation", "REPLACE"), "operation", _OPERATIONS)
    selection_id = params.get("selection_id")
    if selection_id is not None:
        selection_id = _name(selection_id, "selection_id")
    bpy, obj, bm, sequences = _active_edit_mesh(name)
    if selection_id is not None:
        validate_selection_reference(selection_id, obj, bm)
    sequence = sequences[element_type]
    if any(index >= len(sequence) for index in indices):
        raise invalid_argument("A component index is out of range.", element_count=len(sequence))
    existing = {item.index for item in sequence if item.select}
    requested = set(indices)
    desired = (
        requested
        if operation == "REPLACE"
        else (existing | requested if operation == "ADD" else existing - requested)
    )
    if any(sequence[index].hide for index in desired):
        raise BridgeError(
            ErrorCode.INVALID_SELECTION,
            "Hidden components cannot be selected; visibility is not changed implicitly.",
        )
    if len(desired) > MAX_COMPONENT_INDICES:
        raise invalid_argument("Resulting component selection exceeds the bounded index limit.")
    before = inspect_selection({"create_selection_id": False})
    try:
        # Selection changes are intentional, but mesh topology and coordinates are untouched.
        for items in sequences.values():
            for item in items:
                item.select = False
        bm.select_mode = {element_type}
        bpy.context.tool_settings.mesh_select_mode = tuple(
            kind == element_type for kind in ("VERT", "EDGE", "FACE")
        )
        bm.select_history.clear()
        for index in sorted(desired):
            sequence[index].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        actual = {item.index for item in sequence if item.select}
        if actual != desired:
            raise RuntimeError("Component selection verification failed")
    except Exception as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender could not set the requested component selection; reinspect or recover the tracked checkpoint.",
            {"execution_started": True, "verification_required": True, "object": obj.name},
        ) from exc
    return {
        "changed": existing != desired
        or before["mesh_selection"]["selection_modes"] != [element_type],
        "object": obj.name,
        "affected_objects": [obj.name],
        "element_type": element_type,
        "operation_type": operation,
        "selected_indices": sorted(actual)[:256],
        "selected_index_count": len(actual),
        "selected_indices_truncated": len(actual) > 256,
        "before": before,
        "selection": inspect_selection(),
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "mesh.components_inspect",
        inspect_components,
        toolset="interaction",
        permissions=(Permission.INSPECT_SCENE,),
        description="Inspect paginated component indices and measured centers on the active single Edit Mode mesh without changing selection.",
    )
    registry.register(
        "selection.set",
        set_selection,
        toolset="interaction",
        modifies=True,
        permissions=(Permission.TRANSFORM_OBJECTS,),
        description="Set exact Object Mode selection and active object without changing visibility.",
    )
    registry.register(
        "context.set_mode",
        set_mode,
        toolset="interaction",
        modifies=True,
        permissions=(Permission.TRANSFORM_OBJECTS,),
        description="Set one named object's mode; entering editing also requires its domain permission and isolates selection.",
    )
    registry.register(
        "mesh.select_components",
        select_components,
        toolset="interaction",
        modifies=True,
        permissions=(Permission.EDIT_MESH,),
        description="Select bounded explicit indices in the active single Edit Mode mesh and return refreshed selection evidence.",
    )
