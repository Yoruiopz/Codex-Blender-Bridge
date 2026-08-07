"""Viewport capture with temporary UI/render state restoration."""

from __future__ import annotations

import struct
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument
from .utils import bool_param, get_object, require_blender

_VIEWS = {"current", "front", "back", "left", "right", "top", "bottom", "camera"}
_SHADING = {
    "solid": "SOLID",
    "wireframe": "WIREFRAME",
    "material": "MATERIAL",
    "rendered": "RENDERED",
}
_CAPTURE_SAMPLE_LIMIT = 16


def _resolution(value: Any) -> tuple[int, int]:
    if value is None:
        return (768, 768)
    if isinstance(value, Mapping):
        value = (value.get("x"), value.get("y"))
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise invalid_argument("'resolution' must be [width, height] using integers.")
    width, height = int(value[0]), int(value[1])
    if not 64 <= width <= 4096 or not 64 <= height <= 4096:
        raise invalid_argument("Viewport resolution must be between 64 and 4096 pixels per side.")
    return width, height


def _view3d_context(bpy: Any) -> tuple[Any, Any, Any, Any] | None:
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return None
    for window in window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((item for item in area.regions if item.type == "WINDOW"), None)
            if region is not None:
                return window, screen, area, region
    return None


def _managed_capture_path() -> Path:
    directory = Path(tempfile.gettempdir()).resolve() / "blender_codex_bridge" / "captures"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"viewport_{uuid.uuid4().hex}.png"


def _cleanup_managed_captures(directory: Path, *, keep: int = 32) -> None:
    """Bound bridge-owned temporary captures without touching user files."""

    try:
        captures = sorted(
            directory.glob("viewport_*.png"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in captures[keep:]:
            stale.unlink(missing_ok=True)
    except OSError:
        # Cleanup failure must not discard a successfully generated capture.
        pass


def _save_render_settings(scene: Any) -> dict[str, Any]:
    render = scene.render
    image = render.image_settings
    settings = {
        "filepath": render.filepath,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "use_border": render.use_border,
        "use_crop_to_border": render.use_crop_to_border,
        "border_min_x": render.border_min_x,
        "border_max_x": render.border_max_x,
        "border_min_y": render.border_min_y,
        "border_max_y": render.border_max_y,
        "file_format": image.file_format,
        "color_mode": image.color_mode,
    }
    eevee = getattr(scene, "eevee", None)
    cycles = getattr(scene, "cycles", None)
    for name in ("taa_samples", "taa_render_samples"):
        if eevee is not None and hasattr(eevee, name):
            settings[f"eevee_{name}"] = getattr(eevee, name)
    for name in ("samples", "preview_samples"):
        if cycles is not None and hasattr(cycles, name):
            settings[f"cycles_{name}"] = getattr(cycles, name)
    return settings


def _restore_render_settings(scene: Any, settings: Mapping[str, Any]) -> None:
    render = scene.render
    render.filepath = settings["filepath"]
    render.resolution_x = settings["resolution_x"]
    render.resolution_y = settings["resolution_y"]
    render.resolution_percentage = settings["resolution_percentage"]
    render.use_border = settings["use_border"]
    render.use_crop_to_border = settings["use_crop_to_border"]
    render.border_min_x = settings["border_min_x"]
    render.border_max_x = settings["border_max_x"]
    render.border_min_y = settings["border_min_y"]
    render.border_max_y = settings["border_max_y"]
    render.image_settings.file_format = settings["file_format"]
    render.image_settings.color_mode = settings["color_mode"]
    eevee = getattr(scene, "eevee", None)
    cycles = getattr(scene, "cycles", None)
    for name in ("taa_samples", "taa_render_samples"):
        key = f"eevee_{name}"
        if eevee is not None and key in settings:
            setattr(eevee, name, settings[key])
    for name in ("samples", "preview_samples"):
        key = f"cycles_{name}"
        if cycles is not None and key in settings:
            setattr(cycles, name, settings[key])


def _configure_output(
    scene: Any,
    filepath: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    scene.render.filepath = str(filepath)
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    # A user's render-region crop must not silently shrink a bridge capture.
    scene.render.use_border = False
    scene.render.use_crop_to_border = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    sampling: dict[str, Any] = {
        "engine": scene.render.engine,
        "maximum_samples": _CAPTURE_SAMPLE_LIMIT,
    }
    eevee = getattr(scene, "eevee", None)
    cycles = getattr(scene, "cycles", None)
    for name in ("taa_samples", "taa_render_samples"):
        if eevee is not None and hasattr(eevee, name):
            value = min(int(getattr(eevee, name)), _CAPTURE_SAMPLE_LIMIT)
            setattr(eevee, name, value)
            sampling[f"eevee_{name}"] = value
    for name in ("samples", "preview_samples"):
        if cycles is not None and hasattr(cycles, name):
            value = min(int(getattr(cycles, name)), _CAPTURE_SAMPLE_LIMIT)
            setattr(cycles, name, value)
            sampling[f"cycles_{name}"] = value
    return sampling


def _isolate_object(scene: Any, isolated_object: Any) -> list[tuple[Any, bool, bool]]:
    """Apply temporary isolation atomically and return restoration state."""

    visibility: list[tuple[Any, bool, bool]] = []
    try:
        for obj in scene.objects:
            try:
                hidden = bool(obj.hide_get())
            except (RuntimeError, TypeError):
                hidden = bool(obj.hide_viewport)
            visibility.append((obj, hidden, bool(obj.hide_render)))
            if obj != isolated_object:
                obj.hide_set(True)
                obj.hide_render = True
            else:
                obj.hide_set(False)
                obj.hide_render = False
    except Exception:
        for obj, hidden, hidden_render in visibility:
            try:
                obj.hide_set(hidden)
                obj.hide_render = hidden_render
            except (ReferenceError, RuntimeError):
                pass
        raise
    return visibility


def _capture_camera_render(
    bpy: Any,
    filepath: Path,
    width: int,
    height: int,
) -> tuple[str, dict[str, Any]]:
    scene = bpy.context.scene
    if scene.camera is None:
        raise BridgeError(
            ErrorCode.BLENDER_CONTEXT_ERROR,
            "No 3D viewport is available and the scene has no active camera fallback.",
        )
    settings = _save_render_settings(scene)
    try:
        sampling = _configure_output(scene, filepath, width, height)
        result = bpy.ops.render.render(write_still=True)
        if "FINISHED" not in result:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Camera render capture did not finish.")
    finally:
        _restore_render_settings(scene, settings)
    return "camera_render", sampling


def _png_dimensions(filepath: Path) -> tuple[int, int]:
    try:
        with filepath.open("rb") as stream:
            header = stream.read(24)
    except OSError as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender created a capture that could not be inspected.",
            {"detail": str(exc)},
        ) from exc
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender capture output is not a valid PNG header.",
        )
    return struct.unpack(">II", header[16:24])


def capture_viewport(params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Capture a viewport PNG while restoring temporary view/render settings.

    Blender's render operators replace the session's Render Result buffer. The
    caller opts into that explicit side effect through CAPTURE_VIEWPORT.
    """

    bpy = require_blender()
    params = params or {}
    view = params.get("view", "current")
    shading = params.get("shading", "solid")
    if not isinstance(view, str) or view.lower() not in _VIEWS:
        raise invalid_argument("Unsupported viewport view.", allowed=sorted(_VIEWS))
    if not isinstance(shading, str) or shading.lower() not in _SHADING:
        raise invalid_argument("Unsupported viewport shading.", allowed=sorted(_SHADING))
    view = view.lower()
    shading = shading.lower()
    include_overlays = bool_param(params, "include_overlays", True)
    width, height = _resolution(params.get("resolution"))
    object_name = params.get("object_name")
    if object_name is not None and not isinstance(object_name, str):
        raise invalid_argument("'object_name' must be a string.")
    isolated_object = get_object(object_name) if object_name else None
    filepath = _managed_capture_path()
    scene = bpy.context.scene
    if isolated_object is not None and (
        isolated_object.name not in scene.objects
        or isolated_object.name not in bpy.context.view_layer.objects
    ):
        raise invalid_argument(
            "The isolated object must belong to the current scene and view layer.",
            object_name=isolated_object.name,
            scene=scene.name,
            view_layer=bpy.context.view_layer.name,
        )
    # Background startup files can still expose screen/area RNA, but no OpenGL
    # context exists. Treat that as headless so only the truthful camera-render
    # fallback is offered.
    viewport_context = None if bpy.app.background else _view3d_context(bpy)

    object_visibility = _isolate_object(scene, isolated_object) if isolated_object else []

    try:
        if viewport_context is None:
            if view != "camera" or shading != "rendered":
                raise BridgeError(
                    ErrorCode.BLENDER_CONTEXT_ERROR,
                    "A desktop 3D viewport is required for this view or shading mode.",
                    {
                        "requested_view": view,
                        "requested_shading": shading,
                        "headless_supported": {"view": "camera", "shading": "rendered"},
                    },
                )
            source, capture_sampling = _capture_camera_render(
                bpy,
                filepath,
                width,
                height,
            )
            effective_view = "camera"
            effective_shading = "rendered"
            effective_overlays = False
        else:
            window, screen, area, region = viewport_context
            space = area.spaces.active
            region_3d = space.region_3d
            render_settings = _save_render_settings(scene)
            original_shading = space.shading.type
            original_overlays = space.overlay.show_overlays
            view_state = {
                "view_distance": region_3d.view_distance,
                "view_location": region_3d.view_location.copy(),
                "view_rotation": region_3d.view_rotation.copy(),
                "view_perspective": region_3d.view_perspective,
                "view_camera_offset": tuple(region_3d.view_camera_offset),
                "view_camera_zoom": region_3d.view_camera_zoom,
            }
            try:
                capture_sampling = _configure_output(scene, filepath, width, height)
                space.shading.type = _SHADING[shading]
                space.overlay.show_overlays = include_overlays
                with bpy.context.temp_override(
                    window=window,
                    screen=screen,
                    area=area,
                    region=region,
                    scene=scene,
                ):
                    if view == "camera":
                        result = bpy.ops.view3d.view_camera()
                        if "FINISHED" not in result:
                            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Could not enter camera view.")
                    elif view != "current":
                        result = bpy.ops.view3d.view_axis(type=view.upper(), align_active=False)
                        if "FINISHED" not in result:
                            raise BridgeError(
                                ErrorCode.BLENDER_CONTEXT_ERROR,
                                f"Could not set viewport to {view} view.",
                            )
                    result = bpy.ops.render.opengl(write_still=True, view_context=True)
                    if "FINISHED" not in result:
                        raise BridgeError(ErrorCode.OPERATION_FAILED, "Viewport capture did not finish.")
                source = "viewport_opengl"
                effective_view = view
                effective_shading = shading
                effective_overlays = include_overlays
            finally:
                _restore_render_settings(scene, render_settings)
                space.shading.type = original_shading
                space.overlay.show_overlays = original_overlays
                region_3d.view_distance = view_state["view_distance"]
                region_3d.view_location = view_state["view_location"]
                region_3d.view_rotation = view_state["view_rotation"]
                region_3d.view_perspective = view_state["view_perspective"]
                region_3d.view_camera_offset = view_state["view_camera_offset"]
                region_3d.view_camera_zoom = view_state["view_camera_zoom"]
    except BridgeError:
        raise
    except RuntimeError as exc:
        raise BridgeError(
            ErrorCode.BLENDER_CONTEXT_ERROR,
            "Blender failed to capture the viewport in the current context.",
            {"detail": str(exc)},
        ) from exc
    finally:
        for obj, hidden, hidden_render in object_visibility:
            try:
                obj.hide_set(hidden)
                obj.hide_render = hidden_render
            except (ReferenceError, RuntimeError):
                pass

    if not filepath.is_file():
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender reported a completed capture but no PNG was created.",
        )
    actual_width, actual_height = _png_dimensions(filepath)
    _cleanup_managed_captures(filepath.parent)
    return {
        "path": str(filepath),
        "mime_type": "image/png",
        "width": actual_width,
        "height": actual_height,
        "requested_resolution": [width, height],
        "resolution_matches_request": (actual_width, actual_height) == (width, height),
        "view": view,
        "shading": shading,
        "effective_view": effective_view,
        "effective_shading": effective_shading,
        "include_overlays": include_overlays,
        "effective_include_overlays": effective_overlays,
        "isolated_object": isolated_object.name if isolated_object else None,
        "source": source,
        "sampling": capture_sampling,
        "side_effects": ["render_result_replaced"],
        "file_size_bytes": filepath.stat().st_size,
        "temporary": True,
    }
