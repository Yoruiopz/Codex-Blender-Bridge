"""Source-pinned external WindowManager Scene roles, not full Scene admission.

This reader is not wired to a public mutator. In particular, its returned raw
Scene self-reference count is NOT an accepted or normalized ownership role.
"""

from __future__ import annotations

import math
from typing import Any

from ..errors import BridgeError, ErrorCode
from . import _rigid_evaluation_scope as native
from . import _rigid_snapshot_scope as descriptors

PROFILES = {
    "62c1db4208e8": ((4, 5, 14), "62c1db4208e862312bc36db5bc15d4a6dbcfa3e3",
                     "7532f8fd4f4f703c205eba61c53b37470ae2d595",
                     "7b4f78ddf864eb9654dfbfa06a13b9f187ec5141",
                     "4dba33d968142e29c7c15cea91722158f3e04765",
                     "c70fb689dc92bcbd89f1c310ce2b3b6f8377f8ed",
                     "99871ed881396d87f9ea9c49720acccf30063996"),
    "d13f752e3b9c": ((5, 2, 2), "d13f752e3b9c4f8c261cda552b1021f8bcc0382c",
                     "a39a8dbc3f56700b7904f3885fa284a06eb15272",
                     "98a4ebbff67de34b1923fc6b1a0152863b5a592c",
                     "9cca9653c152f5098d563c064be4658ed37d10f9",
                     "30b07a0edf126d07d568bda2e713becc0e8227b2",
                     "83bae4846df4c54491a10898120ea2f37e0e3524"),
}
MAX_RAW_VALUES, MAX_RAW_TEXT = 2048, 8192


def _refuse(message: str) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, message, {"scene_consumer_scope_complete": False})


def _id(bpy: Any, owner: Any, kind: str) -> tuple[Any, ...]:
    # This reader projects only named native role/identity fields. Unrelated UI
    # runtime fields are never resolved, unlike a generic authored-RNA reader.
    rna = native._native(bpy, owner, frozenset({kind}))
    descriptors._fields(rna, (("name", "STRING"), ("session_uid", "INT"),
        ("library", "POINTER"), ("override_library", "POINTER"), ("is_editable", "BOOLEAN")))
    if owner.library is not None or owner.override_library is not None or not owner.is_editable:
        raise _refuse("Native Scene roles require local editable IDs without library overrides.")
    return owner.as_pointer(), owner.session_uid, owner.name


def _raw(bpy: Any, owner: Any, budget: list[int]) -> tuple[Any, ...]:
    """Inspect raw UI IDProperties, refusing aliases without invoking RNA getters."""
    def value(item: Any, depth: int = 0) -> Any:
        if depth > 8:
            raise _refuse("Raw UI properties exceed the bounded native Scene role profile.")
        budget[0] += 1
        if budget[0] > MAX_RAW_VALUES:
            raise _refuse("Raw UI properties exceed the aggregate value budget.")
        if isinstance(item, bpy.types.ID):
            raise _refuse("Raw UI ID aliases prevent native Scene role attribution.")
        if item is None or type(item) in {bool, int}:
            return type(item).__name__, item
        if type(item) is float:
            if not math.isfinite(item):
                raise _refuse("Nonfinite raw UI properties cannot be compared exactly.")
            return "float", item.hex()
        if type(item) is str:
            budget[1] += len(item)
            if budget[1] > MAX_RAW_TEXT:
                raise _refuse("Raw UI properties exceed the aggregate text budget.")
            return "str", item
        if type(item).__name__ == "IDPropertyGroup":
            keys = native._bounded(item.keys(), 128, "raw UI property group")
            if any(type(key) is not str for key in keys):
                raise _refuse("Raw UI property keys have an unreviewed native representation.")
            return tuple((value(key, depth + 1), value(item[key], depth + 1)) for key in sorted(keys))
        if type(item) in {tuple, list} or type(item).__name__ == "IDPropertyArray":
            return tuple(value(child, depth + 1) for child in native._bounded(item, 256, "raw UI array"))
        raise _refuse("Raw UI properties contain an unreviewed native value kind.")

    try:
        keys = native._bounded(owner.keys(), 128, "raw UI properties")
    except TypeError as error:
        if "doesn't support IDProperties" not in str(error):
            raise _refuse("UI raw properties have no reviewed native reader.") from error
        return ()
    if any(type(key) is not str for key in keys):
        raise _refuse("Raw UI property keys have an unreviewed native representation.")
    return tuple((value(key), value(owner[key])) for key in sorted(keys))


def external_scene_roles(bpy: Any, scene: Any) -> tuple[Any, ...]:
    """Return exact external roles; the complete Scene self/dependency scope stays unqualified.

    Exact upstream query entry points use IDWALK_NOP (user_map) and
    IDWALK_READONLY (user_of_id). Neither includes UI or deprecated pointers.
    The pinned WM visitor's only native Scene slots are win.scene USER_ONE and
    win.unpinned_scene NOP. Their observed counts remain in the result.
    """
    build = bpy.app.build_hash.decode("ascii")
    profile = PROFILES.get(build)
    if profile is None or tuple(bpy.app.version) != profile[0]:
        raise _refuse("External native Scene roles require an exact reviewed Blender build.")
    context = bpy.context
    context_rna = native._native(bpy, context, frozenset({"Context"}))
    descriptors._fields(context_rna, tuple((field, "POINTER") for field in
        ("scene", "window_manager", "window", "workspace", "view_layer")))
    main_rna = native._native(bpy, bpy.data, frozenset({"BlendData"}))
    descriptors._fields(main_rna, (("scenes", "COLLECTION"),))
    scene_rna = native._native(bpy, scene, frozenset({"Scene"}))
    descriptors._fields(scene_rna, (("users", "INT"), ("use_fake_user", "BOOLEAN")))
    scene_id = _id(bpy, scene, "Scene")
    if context.scene != scene or native._bounded(bpy.data.scenes, 1, "ordinary Main Scenes") != [scene]:
        raise _refuse("The ordinary native role profile requires exactly the actual current Main Scene.")
    wm, window, workspace = context.window_manager, context.window, context.workspace
    if window is None or workspace is None or wm is None:
        raise _refuse("The ordinary native role profile requires an actual window and workspace.")
    wm_id = _id(bpy, wm, "WindowManager")
    workspace_id = _id(bpy, workspace, "WorkSpace")
    wm_rna = native._native(bpy, wm, frozenset({"WindowManager"}))
    window_rna = native._native(bpy, window, frozenset({"Window"}))
    workspace_rna = native._native(bpy, workspace, frozenset({"WorkSpace"}))
    descriptors._fields(wm_rna, (("windows", "COLLECTION"),))
    descriptors._fields(window_rna, (("scene", "POINTER"), ("view_layer", "POINTER"), ("workspace", "POINTER")))
    descriptors._fields(workspace_rna, (("use_pin_scene", "BOOLEAN"),))
    # Screen every optional direct role reader before reading any of them.
    sequencer = workspace_rna.properties.get("sequencer_scene")
    if sequencer is not None:
        descriptors._fields(workspace_rna, (("sequencer_scene", "POINTER"),))
    if (native._bounded(wm.windows, 1, "ordinary native windows") != [window]
            or window.scene != scene or window.view_layer != context.view_layer
            or window.workspace != workspace or workspace.use_pin_scene):
        raise _refuse("Native Scene roles require one actual current window and an unpinned workspace.")
    if sequencer is not None and workspace.sequencer_scene is not None:
        raise _refuse("Workspace sequencer Scene bindings require a separate native consumer role.")
    budget = [0, 0]
    raw = tuple((label, _raw(bpy, owner, budget)) for label, owner in
                (("window_manager", wm), ("window", window), ("workspace", workspace)))
    incoming = native._bounded(bpy.data.user_map(subset={scene}).get(scene, ()), 64, "Scene consumers")
    external = [owner for owner in incoming if owner != scene]
    if external != [wm] or int(scene.users) - int(bool(scene.use_fake_user)) != 1:
        raise _refuse("The Scene has consumers or native users outside the reviewed ordinary WindowManager role.")
    count = int(wm.user_of_id(scene))
    if count == 1:
        roles = (("win.scene", "IDWALK_CB_USER_ONE"),)
    elif count == 2:
        roles = (("win.scene", "IDWALK_CB_USER_ONE"), ("win.unpinned_scene", "IDWALK_CB_NOP"))
    else:
        raise _refuse("The native WindowManager Scene count has no exact source role.")
    return (("scope", "EXTERNAL_WINDOW_MANAGER_ONLY"), ("scene_id", scene_id), ("wm_id", wm_id),
            ("window_pointer", window.as_pointer()), ("workspace_id", workspace_id),
            ("source_profile", (build, *profile[1:], "IDWALK_NOP", "IDWALK_READONLY")),
            ("native_roles", roles), ("raw_wm_scene_reference_count", count),
            ("raw_scene_users", int(scene.users)), ("raw_scene_fake_user", bool(scene.use_fake_user)),
            ("raw_scene_self_reference_count", int(scene.user_of_id(scene))),
            ("scene_self_scope_qualified", False), ("raw_ui_properties", raw))
