"""Selected face shading/material attributes with bounded, measured restoration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..selection import validate_selection_reference
from ..utils import bool_param, int_param, reject_unknown_params
from . import mesh
from ._mesh_safety import require_local_single_user_mesh
from .interaction import _active_edit_mesh

LOGGER = logging.getLogger(__name__)
MAX_FACES = 20_000


def set_face_attributes(context: Any, params: Mapping[str, Any]) -> dict:
    reject_unknown_params(params, {"object_name", "selection_id", "smooth", "material_index"})
    name = mesh._id_name(params.get("object_name"), "object_name")
    reference_id = params.get("selection_id")
    if not isinstance(reference_id, str) or not reference_id:
        raise invalid_argument("A fresh non-empty face selection_id is required.")
    smooth = bool_param(params, "smooth", False) if "smooth" in params else None
    material = int_param(params, "material_index", 0, minimum=0, maximum=255) if "material_index" in params else None
    if smooth is None and material is None:
        raise invalid_argument("Supply smooth and/or material_index; no arbitrary face properties are exposed.")
    required = (Permission.EDIT_MESH, Permission.EDIT_MATERIALS) if material is not None else (Permission.EDIT_MESH,)
    context.require(*required)
    _bpy, obj, bm, _sequences = _active_edit_mesh(name)
    require_local_single_user_mesh(obj)
    reference = validate_selection_reference(reference_id, obj, bm)
    faces = mesh._operation_elements(bm.faces, "faces", reference)
    if not 1 <= len(faces) <= MAX_FACES or any(face.hide for face in faces):
        raise BridgeError(ErrorCode.INVALID_SELECTION, "Face attributes require 1-20,000 non-hidden referenced faces.")
    if material is not None and (material >= len(obj.material_slots) or obj.material_slots[material].material is None):
        raise invalid_argument("material_index must identify a non-empty existing object material slot.")
    before = [(face, bool(face.smooth), int(face.material_index), bool(face.select)) for face in faces]
    check = getattr(context, "check_cancelled", None)
    if check:
        check()
    context.require(*required)
    try:
        for index, (face, _, _, _) in enumerate(before):
            if check and index % 128 == 0:
                check()
            if smooth is not None:
                face.smooth = smooth
            if material is not None:
                face.material_index = material
        mesh.bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        if check:
            check()
        context.require(*required)
        if any((smooth is not None and face.smooth != smooth)
               or (material is not None and face.material_index != material)
               or bool(face.select) != selected for face, _, _, selected in before):
            raise RuntimeError("Face-attribute readback or selection preservation failed")
    except Exception as exc:
        LOGGER.exception("Face-attribute revision failed; attempting measured local restoration")
        restored = False
        try:
            for face, old_smooth, old_material, _ in before:
                face.smooth, face.material_index = old_smooth, old_material
            mesh.bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            restored = all(face.smooth == old_smooth and face.material_index == old_material
                           and bool(face.select) == selected for face, old_smooth, old_material, selected in before)
        except Exception:
            LOGGER.exception("Could not verify face-attribute restoration")
        raise BridgeError(exc.code if isinstance(exc, BridgeError) else ErrorCode.OPERATION_FAILED,
                          "Face-attribute revision failed; inspect measured restoration before continuing.",
                          {"execution_started": True, "affected_object": name, "rollback_verified": restored,
                           "possible_mutation": not restored, "verification_required": True}) from exc
    return {"object": name, "affected_objects": [name], "target_faces": len(faces),
            "smooth": smooth, "material_index": material, "topology_changed": False,
            "selection_changed": False, "attributes_verified": True,
            "faces": [face.index for face in faces[:64]], "faces_truncated": len(faces) > 64,
            "verification_required": True, "user_goal_verified": False}


def register_tools(registry: Any) -> None:
    registry.register("mesh.set_face_attributes", set_face_attributes, toolset="mesh", modifies=True,
                      permissions=(Permission.EDIT_MESH,),
                      description="Set smooth shading and/or an existing material-slot index on bounded referenced faces; material changes also require EDIT_MATERIALS.")
