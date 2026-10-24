"""Structured render configuration, inspection, and explicit image output."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import render_scope_profile as profile
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, int_param, require_blender, similar_names
from ..viewport import _png_dimensions
from ._render_boundary import Boundary
from ._render_checkpoint import Admission

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


@dataclass(frozen=True, slots=True)
class _PreparedExecute:
    scene: Any
    filepath: str | None
    overwrite: bool
    width: int
    height: int
    percentage: int
    expected_size: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _FrozenPlan:
    prepared: _PreparedRender | _PreparedExecute
    boundary: Boundary
    root_snapshot: tuple | None


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
    # The admitted EEVEE path never reads bundled Cycles runtime getters.
    result = {}
    eevee = getattr(scene, "eevee", None)
    if eevee is not None:
        for name in ("taa_samples", "taa_render_samples"):
            if hasattr(eevee, name):
                result[f"eevee_{name}"] = int(getattr(eevee, name))
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


def _validate_external_path(raw: str, file_format: str, *, probe: bool = True) -> Path:
    if not raw or any(ord(character) < 32 for character in raw):
        raise invalid_argument(
            "Render output path must be a non-empty path without control characters."
        )
    if raw.startswith(("\\\\", "//")):
        raise invalid_argument("Network and UNC render paths are not supported.")
    candidate = Path(raw)
    if not candidate.is_absolute() or ".." in candidate.parts or candidate.is_reserved():
        raise invalid_argument("Render output must be an absolute local path without traversal.")
    try:
        path = candidate.resolve() if probe else candidate
    except OSError as exc:
        raise invalid_argument(
            "Render output path could not be resolved.", detail=str(exc)
        ) from exc
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
    if probe and not path.parent.is_dir():
        raise invalid_argument(
            "Render output directory does not exist.", directory=str(path.parent)
        )
    return path


def _validate_native_prepare(scene: Any) -> None:
    bpy = require_blender()
    profile.require_raw_storage_reader(bpy)
    reader = profile.Reader(bpy, scene)
    reader.props(scene)
    render = reader.field(scene, "render")
    reader.props(render)
    reader.props(reader.field(render, "image_settings"))
    eevee = reader.field(scene, "eevee")
    if eevee is not None:
        reader.props(eevee)


def _prepare_render(context: ToolContext, params: Mapping[str, Any]) -> _PreparedRender:
    scene = _scene(_required_name(params, "scene_name"))
    _validate_native_prepare(scene)
    render = scene.render
    image = render.image_settings

    engine_value = None
    planned_engine = render.engine
    if "engine" in params:
        engine = params.get("engine")
        available = _enum_values(render, "engine")
        if not isinstance(engine, str) or not engine or (available and engine not in available):
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
        eevee = getattr(scene, "eevee", None)
        if planned_engine == "CYCLES":
            # Preserve pure parameter validation without reading a runtime
            # Cycles getter. The supported-scope gate refuses it before writes.
            sample_target = None
        elif eevee is not None:
            target = next(
                (name for name in ("taa_render_samples", "taa_samples") if hasattr(eevee, name)),
                None,
            )
            if target is None:
                raise invalid_argument(
                    "The active render engine does not expose a writable sample count."
                )
            sample_target = (eevee, target, value)
        else:
            raise invalid_argument(
                "The active render engine does not expose a writable sample count."
            )

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
        output_filepath = _validate_external_path(raw_path, planned_file_format, probe=False)

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


def _supported(prepared: _PreparedRender) -> None:
    if prepared.file_format not in {None, "PNG"}:
        profile.refuse(
            "Additional render formats require separate native output/compensation proof."
        )
    profile.native_engine(require_blender(), prepared.engine or prepared.scene.render.engine)
    if prepared.width * prepared.height > 16_384 * 16_384:
        profile.refuse("Render configuration exceeds its typed resolution bounds.")


def _configured_writes(prepared: _PreparedRender) -> list[tuple[Any, str, Any]]:
    scene, writes = prepared.scene, []
    render, image = scene.render, scene.render.image_settings
    if prepared.engine is not None:
        writes.append((render, "engine", prepared.engine))
    writes.extend(
        (render, name, value)
        for name, value in (
            ("resolution_x", prepared.width),
            ("resolution_y", prepared.height),
            ("resolution_percentage", prepared.percentage),
        )
    )
    if prepared.fps is not None:
        writes.extend(((render, "fps", prepared.fps[0]), (render, "fps_base", prepared.fps[1])))
    for name, value in (
        ("film_transparent", prepared.film_transparent),
        ("use_file_extension", prepared.use_file_extension),
    ):
        if value is not None:
            writes.append((render, name, value))
    for name, value in (("file_format", prepared.file_format), ("color_mode", prepared.color_mode)):
        if value is not None:
            writes.append((image, name, value))
    if prepared.sample_target is not None:
        writes.append(prepared.sample_target)
    if prepared.output_filepath is not None:
        writes.append((render, "filepath", str(prepared.output_filepath)))
    return writes


def _prepare_execute(params: Mapping[str, Any]) -> _PreparedExecute:
    scene = _scene(_required_name(params, "scene_name"))
    _validate_native_prepare(scene)
    if scene.camera is None:
        raise BridgeError(
            ErrorCode.BLENDER_CONTEXT_ERROR, "The requested scene has no active camera."
        )
    raw_format = params.get("file_format", "PNG")
    if not isinstance(raw_format, str) or raw_format.upper() not in _SUPPORTED_OUTPUT_FORMATS:
        raise invalid_argument(
            "Unsupported explicit render output format.",
            supported=sorted(_SUPPORTED_OUTPUT_FORMATS),
        )
    if raw_format.upper() != "PNG":
        profile.refuse("The demonstrated native render publication currently admits PNG only.")
    raw_path = params.get("filepath")
    if raw_path is not None:
        if not isinstance(raw_path, str):
            raise invalid_argument("'filepath' must be a string.")
        _validate_external_path(raw_path, "PNG", probe=False)
    overwrite = bool_param(params, "overwrite", False)
    width, height, percentage = _resolution(params, scene)
    expected_size = max(1, int(width * percentage / 100)), max(1, int(height * percentage / 100))
    if expected_size[0] * expected_size[1] > 1_048_576:
        profile.refuse("Native render output is currently bounded to 1,048,576 pixels.")
    image = scene.render.image_settings
    if image.file_format != "PNG":
        profile.refuse(
            "The measured render tail requires an existing PNG image format; configure it explicitly first."
        )
    return _PreparedExecute(scene, raw_path, overwrite, width, height, percentage, expected_size)


def _freeze_plan(
    context: ToolContext, params: Mapping[str, Any], method: str, *, prefix: str | None = None
) -> _FrozenPlan:
    from ..render_staging import _read_root

    if method == "render.configure":
        prepared = _prepare_render(context, params)
        _supported(prepared)
        writes = _configured_writes(prepared)
        external = prepared.output_filepath is not None
    elif method == "render.execute":
        prepared = _prepare_execute(params)
        render = prepared.scene.render
        writes = [
            (render, "filepath", ""),
            (render, "resolution_x", prepared.width),
            (render, "resolution_y", prepared.height),
            (render, "resolution_percentage", prepared.percentage),
            (render, "use_border", False),
            (render, "use_crop_to_border", False),
        ]
        external = prepared.filepath is not None
    else:
        raise ValueError("Unreviewed internal render method")
    # These are descriptor/raw-storage reads only. No caller path is probed and
    # no callback-backed authority reader runs before this entire plan freezes.
    root_snapshot = _read_root() if external else None
    boundary = Boundary(
        context,
        require_blender(),
        prepared.scene,
        method,
        writes,
        external=external,
        checkpoint_prefix=prefix,
        initial_check=False,
    )
    if root_snapshot is not None:

        def check_root() -> None:
            if _read_root() != root_snapshot:
                raise invalid_argument("Approved render path storage or descriptor changed.")

        boundary.filesystem_checks.append(check_root)
    return _FrozenPlan(prepared, boundary, root_snapshot)


def checkpoint_admission_factory(
    method: str, context: ToolContext, params: Mapping[str, Any]
) -> Admission:
    """Freeze the complete authored ledger before entry/checkpoint providers.

    The shared registry retains this plan through handler and finalization.
    """
    manager = context.checkpoints
    prefix = getattr(manager, "_prefix", None)
    if not isinstance(prefix, str):
        profile.refuse("Native render checkpoint admission requires its manager-owned namespace.")
    plan = _freeze_plan(context, params, method, prefix=prefix)
    admission = Admission(
        context,
        plan.boundary.bpy,
        plan.prepared.scene,
        method,
        external=plan.root_snapshot is not None,
        boundary=plan.boundary,
    )
    admission.plan = plan
    return admission


def _request_plan(context: ToolContext, params: Mapping[str, Any], method: str) -> _FrozenPlan:
    binding = getattr(context, "checkpoint_admission", None)
    if binding is None:
        # Raw handlers have no automatic checkpoint. Registered opt-in calls
        # must retain their factory-created plan rather than rebaseline here.
        return _freeze_plan(context, params, method)
    admission = binding.callback
    if (
        not isinstance(admission, Admission)
        or admission.method != method
        or not binding.matches(context.registry.get(method), params, context)
        or not isinstance(getattr(admission, "plan", None), _FrozenPlan)
    ):
        profile.refuse("Render has no matching request-owned authored checkpoint ledger.")
    admission.check_after_read()
    return admission.plan


def configure_render(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    from ..render_staging import _approved, _read_root

    plan = _request_plan(context, params, "render.configure")
    prepared, boundary = plan.prepared, plan.boundary
    if not isinstance(prepared, _PreparedRender):
        raise ValueError("Internal render configuration plan has the wrong type")
    try:
        boundary.check()
        if prepared.output_filepath is not None:
            raw = str(prepared.output_filepath)
            root, root_descriptor = plan.root_snapshot
            expected = _approved(raw, root)

            def validate_output() -> None:
                if _read_root() != (root, root_descriptor) or _approved(raw, root) != expected:
                    raise invalid_argument("Configured render output or approved folder changed.")

            boundary.filesystem_checks.append(validate_output)
        boundary.apply()
        return {
            "configured": True,
            "verified": True,
            "render_scope_complete": True,
            **_render_state(prepared.scene),
        }
    except Exception as error:
        raise boundary.annotate(error, boundary.restore()) from error


def execute_render(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    import time

    from ..render_staging import Staging, native_render_effects

    plan = _request_plan(context, params, "render.execute")
    prepared, boundary = plan.prepared, plan.boundary
    if not isinstance(prepared, _PreparedExecute):
        raise ValueError("Internal render execution plan has the wrong type")
    bpy, scene = boundary.bpy, prepared.scene
    raw_path, overwrite = prepared.filepath, prepared.overwrite
    expected_size = prepared.expected_size
    render = scene.render
    staging, recovery, error, native_seconds = None, None, None, None
    try:
        staging = Staging(boundary, raw_path, overwrite=overwrite)
        staging.open()
        boundary.planned[0] = (render, "filepath", str(staging.payload))
        boundary.apply()
        if not bpy.ops.render.render.poll():
            raise BridgeError(
                ErrorCode.BLENDER_CONTEXT_ERROR,
                "Native render is unavailable in the current context.",
            )
        boundary.check()
        boundary.final()
        boundary.native_started = True
        started = time.monotonic()
        try:
            result = bpy.ops.render.render(scene=scene.name, write_still=True)
        finally:
            native_seconds = time.monotonic() - started
            boundary.native_blocking_seconds = native_seconds
        if "FINISHED" not in result:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "Native render did not finish; output and Render Result require inspection.",
            )
        boundary.native_completed = True
        boundary.seal_native_outcome()
        staging.capture()
        actual_size = _png_dimensions(staging.payload)
        if actual_size != expected_size:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "Native PNG dimensions differ from the requested effective resolution.",
            )
        boundary.check()
        recovery = boundary.restore()
        if not recovery["restored"]:
            raise BridgeError(
                ErrorCode.OPERATION_FAILED,
                "Render completed but its original settings could not be restored.",
            )
        staging.publish()
    except Exception as failure:
        error = failure
        if recovery is None:
            recovery = boundary.restore()
    finally:
        if staging is not None:
            staging.cleanup()
    effects = staging.evidence() if staging is not None else native_render_effects(boundary)
    if error is not None:
        raise boundary.annotate(error, recovery, effects) from error
    try:
        boundary.check()
    except Exception as failure:
        raise boundary.annotate(failure, recovery, effects) from failure
    return {
        "rendered": True,
        "scene": scene.name,
        "camera": scene.camera.name,
        "filepath": str(staging.path),
        "temporary": raw_path is None,
        "file_format": "PNG",
        "width": expected_size[0],
        "height": expected_size[1],
        "engine": scene.render.engine,
        "samples": _samples(scene),
        "render_result_replaced": True,
        "native_call_interruptible": False,
        "native_blocking_seconds": native_seconds,
        "render_settings_recovery": recovery,
        "native_dependency_evidence": boundary.native_evidence(),
        "external_effects": effects,
        "verified": True,
        "project_saved": False,
        "project_dirty": bool(bpy.data.is_dirty),
        "render_scope_complete": True,
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
        checkpoint_admission_factory=lambda context, params: checkpoint_admission_factory(
            "render.configure", context, params
        ),
        description="Configure engine, resolution, samples, image settings, and approved output path.",
    )
    registry.register(
        "render.execute",
        execute_render,
        permissions=(Permission.EDIT_RENDER, Permission.CAPTURE_VIEWPORT),
        toolset="render",
        modifies=True,
        automatic_checkpoint=False,
        checkpoint_admission_factory=lambda context, params: checkpoint_admission_factory(
            "render.execute", context, params
        ),
        description="Render an explicit scene to a managed or approved local file and replace Render Result.",
    )


__all__ = ["register_tools"]
