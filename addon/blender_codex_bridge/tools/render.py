"""Structured render configuration, inspection, and explicit image output."""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, int_param, require_blender, similar_names
from ..viewport import _png_dimensions

_MANAGED_KEEP = 16
_FILE_EXTENSIONS = {
    "BMP": ".bmp",
    "JPEG": ".jpg",
    "OPEN_EXR": ".exr",
    "PNG": ".png",
    "TIFF": ".tif",
    "TARGA": ".tga",
}
_SUPPORTED_OUTPUT_FORMATS = frozenset(_FILE_EXTENSIONS)
_COLOR_FORMATS_WITHOUT_ALPHA = frozenset({"CINEON", "FFMPEG", "HDR", "JPEG"})


@dataclass(frozen=True, slots=True)
class _PreparedRender:
    scene: Any
    engine: str | None
    width: int
    height: int
    percentage: int
    fps: tuple[int, float] | None
    film_transparent: bool | None
    use_file_extension: bool | None
    file_format: str | None
    color_mode: str | None
    sample_target: tuple[Any, str, int] | None
    output_filepath: Path | None


def _required_name(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise invalid_argument(
            f"'{key}' must be a non-empty string of at most 256 characters.",
            parameter=key,
        )
    return value.strip()


def _scene(name: str) -> Any:
    bpy = require_blender()
    scene = bpy.data.scenes.get(name)
    if scene is None:
        raise invalid_argument(
            f"Scene '{name}' does not exist.",
            available_similar_scenes=similar_names(name, bpy.data.scenes.keys()),
        )
    return scene


def _enum_values(owner: Any, property_name: str) -> set[str]:
    try:
        prop = owner.bl_rna.properties[property_name]
        return {item.identifier for item in prop.enum_items}
    except (AttributeError, KeyError, TypeError):
        return set()


def _resolution(params: Mapping[str, Any], scene: Any) -> tuple[int, int, int]:
    render = scene.render
    width = int_param(params, "width", int(render.resolution_x), minimum=16, maximum=16_384)
    height = int_param(params, "height", int(render.resolution_y), minimum=16, maximum=16_384)
    percentage = int_param(
        params,
        "resolution_percentage",
        int(render.resolution_percentage),
        minimum=1,
        maximum=100,
    )
    return width, height, percentage


def _samples(scene: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    cycles = getattr(scene, "cycles", None)
    eevee = getattr(scene, "eevee", None)
    for owner_name, owner, names in (
        ("cycles", cycles, ("samples", "preview_samples")),
        ("eevee", eevee, ("taa_samples", "taa_render_samples")),
    ):
        if owner is None:
            continue
        for name in names:
            if hasattr(owner, name):
                result[f"{owner_name}_{name}"] = int(getattr(owner, name))
    return result


def _render_state(scene: Any) -> dict[str, Any]:
    render = scene.render
    image = render.image_settings
    return {
        "scene": scene.name,
        "engine": render.engine,
        "camera": scene.camera.name if scene.camera else None,
        "resolution": {
            "width": int(render.resolution_x),
            "height": int(render.resolution_y),
            "percentage": int(render.resolution_percentage),
            "effective_width": int(render.resolution_x * render.resolution_percentage / 100),
            "effective_height": int(render.resolution_y * render.resolution_percentage / 100),
        },
        "fps": float(render.fps) / float(render.fps_base),
        "filepath": render.filepath,
        "file_format": image.file_format,
        "color_mode": image.color_mode,
        "film_transparent": bool(render.film_transparent),
        "use_file_extension": bool(render.use_file_extension),
        "samples": _samples(scene),
        "render_result_side_effect": "render.execute replaces Blender's Render Result buffer",
    }


def inspect_render(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del context
    return _render_state(_scene(_required_name(params, "scene_name")))


def _validate_external_path(raw: str, file_format: str) -> Path:
    if not raw or any(ord(character) < 32 for character in raw):
        raise invalid_argument("Render output path must be a non-empty path without control characters.")
    if raw.startswith(("\\\\", "//")):
        raise invalid_argument("Network and UNC render paths are not supported.")
    candidate = Path(raw)
    if not candidate.is_absolute() or ".." in candidate.parts or candidate.is_reserved():
        raise invalid_argument("Render output must be an absolute local path without traversal.")
    try:
        path = candidate.resolve()
    except OSError as exc:
        raise invalid_argument("Render output path could not be resolved.", detail=str(exc)) from exc
    if os.name != "nt" and len(path.parts) > 1 and path.parts[1] in {"dev", "proc", "sys"}:
        raise invalid_argument("System device and process paths cannot be used for renders.")
    expected = _FILE_EXTENSIONS[file_format]
    accepted = {expected}
    if file_format == "JPEG":
        accepted.add(".jpeg")
    if file_format == "TIFF":
        accepted.add(".tiff")
    if path.suffix.lower() not in accepted:
        raise invalid_argument(
            f"Render format {file_format} requires one of these extensions: {sorted(accepted)}."
        )
    if not path.parent.is_dir():
        raise invalid_argument("Render output directory does not exist.", directory=str(path.parent))
    return path


def _managed_path(file_format: str) -> Path:
    directory = Path(tempfile.gettempdir()).resolve() / "blender_codex_bridge" / "renders"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"render_{uuid.uuid4().hex}{_FILE_EXTENSIONS[file_format]}"


def _cleanup_managed(directory: Path) -> None:
    try:
        outputs = sorted(
            (path for path in directory.iterdir() if path.name.startswith("render_")),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in outputs[_MANAGED_KEEP:]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass


def _prepare_render(context: ToolContext, params: Mapping[str, Any]) -> _PreparedRender:
    scene = _scene(_required_name(params, "scene_name"))
    render = scene.render
    image = render.image_settings

    engine_value = None
    planned_engine = render.engine
    if "engine" in params:
        engine = params.get("engine")
        available = _enum_values(render, "engine")
        if (
            not isinstance(engine, str)
            or not engine
            or (available and engine not in available)
        ):
            raise invalid_argument("Unsupported render engine.", supported=sorted(available))
        engine_value = engine
        planned_engine = engine

    width, height, percentage = _resolution(params, scene)

    fps_value = None
    if "fps" in params:
        fps = float_param(params, "fps", float(render.fps), minimum=1.0, maximum=240.0)
        rounded_fps = max(1, round(fps))
        fps_value = (rounded_fps, float(rounded_fps) / fps)

    film_transparent = (
        bool_param(
            params,
            "film_transparent",
            bool(render.film_transparent),
        )
        if "film_transparent" in params
        else None
    )
    use_file_extension = (
        bool_param(
            params,
            "use_file_extension",
            bool(render.use_file_extension),
        )
        if "use_file_extension" in params
        else None
    )

    file_format_value = None
    planned_file_format = image.file_format
    if "file_format" in params:
        file_format = params.get("file_format")
        available = _enum_values(image, "file_format")
        if (
            not isinstance(file_format, str)
            or not file_format
            or (available and file_format not in available)
        ):
            raise invalid_argument("Unsupported image file format.", supported=sorted(available))
        file_format_value = file_format
        planned_file_format = file_format

    color_mode_value = None
    if "color_mode" in params:
        color_mode = params.get("color_mode")
        available = _enum_values(image, "color_mode")
        if (
            not isinstance(color_mode, str)
            or not color_mode
            or (available and color_mode not in available)
        ):
            raise invalid_argument("Unsupported render color mode.", supported=sorted(available))
        if color_mode == "RGBA" and planned_file_format in _COLOR_FORMATS_WITHOUT_ALPHA:
            raise invalid_argument(
                f"Render format {planned_file_format} does not support RGBA output.",
                file_format=planned_file_format,
                supported_color_modes=["BW", "RGB"],
            )
        color_mode_value = color_mode

    sample_target = None
    if "samples" in params:
        value = int_param(params, "samples", 64, minimum=1, maximum=1_000_000)
        cycles = getattr(scene, "cycles", None)
        eevee = getattr(scene, "eevee", None)
        if planned_engine == "CYCLES" and cycles is not None and hasattr(cycles, "samples"):
            sample_target = (cycles, "samples", value)
        elif eevee is not None:
            target = next(
                (name for name in ("taa_render_samples", "taa_samples") if hasattr(eevee, name)),
                None,
            )
            if target is None:
                raise invalid_argument("The active render engine does not expose a writable sample count.")
            sample_target = (eevee, target, value)
        else:
            raise invalid_argument("The active render engine does not expose a writable sample count.")

    output_filepath = None
    if "output_filepath" in params:
        raw_path = params.get("output_filepath")
        if not isinstance(raw_path, str):
            raise invalid_argument("'output_filepath' must be a string.")
        if planned_file_format not in _SUPPORTED_OUTPUT_FORMATS:
            raise invalid_argument(
                "Set a still-image 'file_format' before configuring an output file.",
                supported=sorted(_SUPPORTED_OUTPUT_FORMATS),
            )
        context.require(Permission.ACCESS_EXTERNAL_FILES)
        output_filepath = _validate_external_path(raw_path, planned_file_format)

    return _PreparedRender(
        scene=scene,
        engine=engine_value,
        width=width,
        height=height,
        percentage=percentage,
        fps=fps_value,
        film_transparent=film_transparent,
        use_file_extension=use_file_extension,
        file_format=file_format_value,
        color_mode=color_mode_value,
        sample_target=sample_target,
        output_filepath=output_filepath,
    )


def _apply_render(prepared: _PreparedRender) -> dict[str, Any]:
    scene = prepared.scene
    render = scene.render
    image = render.image_settings
    saved = {
        "engine": render.engine,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "fps": render.fps,
        "fps_base": render.fps_base,
        "film_transparent": render.film_transparent,
        "use_file_extension": render.use_file_extension,
        "filepath": render.filepath,
        "file_format": image.file_format,
        "color_mode": image.color_mode,
    }
    saved_sample = None
    if prepared.sample_target is not None:
        owner, name, _value = prepared.sample_target
        saved_sample = (owner, name, getattr(owner, name))
    try:
        if prepared.engine is not None:
            render.engine = prepared.engine
        render.resolution_x = prepared.width
        render.resolution_y = prepared.height
        render.resolution_percentage = prepared.percentage
        if prepared.fps is not None:
            render.fps, render.fps_base = prepared.fps
        if prepared.film_transparent is not None:
            render.film_transparent = prepared.film_transparent
        if prepared.use_file_extension is not None:
            render.use_file_extension = prepared.use_file_extension
        if prepared.file_format is not None:
            image.file_format = prepared.file_format
        if prepared.color_mode is not None:
            image.color_mode = prepared.color_mode
        if prepared.sample_target is not None:
            owner, name, value = prepared.sample_target
            setattr(owner, name, value)
        if prepared.output_filepath is not None:
            render.filepath = str(prepared.output_filepath)
        return {"configured": True, **_render_state(scene)}
    except Exception:
        render.engine = saved["engine"]
        render.resolution_x = saved["resolution_x"]
        render.resolution_y = saved["resolution_y"]
        render.resolution_percentage = saved["resolution_percentage"]
        render.fps = saved["fps"]
        render.fps_base = saved["fps_base"]
        render.film_transparent = saved["film_transparent"]
        render.use_file_extension = saved["use_file_extension"]
        render.filepath = saved["filepath"]
        image.file_format = saved["file_format"]
        image.color_mode = saved["color_mode"]
        if saved_sample is not None:
            owner, name, value = saved_sample
            setattr(owner, name, value)
        raise


def configure_render(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    return _apply_render(_prepare_render(context, params))


def execute_render(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    scene = _scene(_required_name(params, "scene_name"))
    if scene.camera is None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "The requested scene has no active camera.")
    raw_format = params.get("file_format", "PNG")
    if not isinstance(raw_format, str) or raw_format.upper() not in _SUPPORTED_OUTPUT_FORMATS:
        raise invalid_argument(
            "Unsupported explicit render output format.",
            supported=sorted(_SUPPORTED_OUTPUT_FORMATS),
        )
    file_format = raw_format.upper()
    raw_path = params.get("filepath")
    temporary = raw_path is None
    if raw_path is not None:
        if not isinstance(raw_path, str):
            raise invalid_argument("'filepath' must be a string.")
        context.require(Permission.ACCESS_EXTERNAL_FILES)
        path = _validate_external_path(raw_path, file_format)
        overwrite = bool_param(params, "overwrite", False)
        if path.exists() and not overwrite:
            raise invalid_argument(
                "Render output already exists; set 'overwrite' to true to replace it.",
                filepath=str(path),
            )
    else:
        path = _managed_path(file_format)
    width, height, percentage = _resolution(params, scene)
    render = scene.render
    image = render.image_settings
    saved = {
        "filepath": render.filepath,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "use_border": render.use_border,
        "use_crop_to_border": render.use_crop_to_border,
        "file_format": image.file_format,
    }
    try:
        render.filepath = str(path)
        render.resolution_x = width
        render.resolution_y = height
        render.resolution_percentage = percentage
        render.use_border = False
        render.use_crop_to_border = False
        image.file_format = file_format
        result = bpy.ops.render.render(scene=scene.name, write_still=True)
        if "FINISHED" not in result:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Blender render did not finish.")
    except RuntimeError as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender failed to render the requested scene.",
            {"scene": scene.name, "detail": str(exc)[:400]},
        ) from exc
    finally:
        render.filepath = saved["filepath"]
        render.resolution_x = saved["resolution_x"]
        render.resolution_y = saved["resolution_y"]
        render.resolution_percentage = saved["resolution_percentage"]
        render.use_border = saved["use_border"]
        render.use_crop_to_border = saved["use_crop_to_border"]
        image.file_format = saved["file_format"]
    if not path.is_file():
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender reported success but no render file was produced.",
            {"filepath": str(path)},
        )
    actual_width = int(width * percentage / 100)
    actual_height = int(height * percentage / 100)
    if file_format == "PNG":
        actual_width, actual_height = _png_dimensions(path)
    if temporary:
        _cleanup_managed(path.parent)
    return {
        "rendered": True,
        "scene": scene.name,
        "camera": scene.camera.name,
        "filepath": str(path),
        "temporary": temporary,
        "file_format": file_format,
        "width": actual_width,
        "height": actual_height,
        "engine": scene.render.engine,
        "samples": _samples(scene),
        "render_result_replaced": True,
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "render.inspect",
        inspect_render,
        permissions=(Permission.INSPECT_SCENE,),
        toolset="render",
        description="Inspect an explicit scene's bounded render configuration.",
    )
    registry.register(
        "render.configure",
        configure_render,
        permissions=(Permission.EDIT_RENDER,),
        toolset="render",
        modifies=True,
        description="Configure engine, resolution, samples, image settings, and approved output path.",
    )
    registry.register(
        "render.execute",
        execute_render,
        permissions=(Permission.EDIT_RENDER, Permission.CAPTURE_VIEWPORT),
        toolset="render",
        modifies=True,
        automatic_checkpoint=False,
        description="Render an explicit scene to a managed or approved local file and replace Render Result.",
    )


__all__ = ["register_tools"]
