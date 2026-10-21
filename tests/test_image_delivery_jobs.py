from __future__ import annotations

import asyncio
import importlib
import math
from array import array
from pathlib import Path
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError
from test_image_paint import Image, paint_tools  # noqa: F401
from test_paint_jobs import finish, jobs  # noqa: F401
from test_pixel_codecs import exr_pixels, png_pixels

from mcp_server.tools.image_paint import ImagePaintTools


@pytest.fixture
def delivery(request, monkeypatch, tmp_path):
    env = request.getfixturevalue("jobs")
    env.delivery = importlib.import_module(env.module.__package__ + ".tools.image_delivery")
    env.verification = importlib.import_module(env.module.__package__ + ".texture_verification")
    monkeypatch.setattr(env.delivery, "require_blender", lambda: env.bpy)
    monkeypatch.setattr(env.delivery.images, "_root", lambda: str(tmp_path))
    env.delivery.register_tools(env.context().registry)
    env.folder = tmp_path
    env.bpy.types.ColorManagedInputColorspaceSettings.bl_rna.properties["name"].enum_items.append(NS(identifier="sRGB"))

    class NativePixels:
        def __init__(self, image, values, depth):
            self.image, self.values, self.depth = image, array("f", values), depth

        def __len__(self):
            return len(self.values)

        def foreach_get(self, output):
            values = array("f", self.values)
            if self.depth == 16 and self.image.colorspace_settings.name == "sRGB":
                for start in range(0, len(values), 4):
                    for channel in range(3):
                        value = values[start+channel]
                        values[start+channel] = (value/12.92 if value <= .04045 else ((value+.055)/1.055)**2.4)*values[start+3]
            output[:] = values

    def load(filepath, *, check_existing):
        assert check_existing is False
        path = Path(filepath)
        data = path.read_bytes()
        if path.suffix == ".png":
            depth, rows = png_pixels(data)
            width, height = len(rows[0])//4, len(rows)
            scale = 255 if depth == 8 else 65535
            values = [v/scale for row in reversed(rows) for v in row]
        else:
            rows, _attributes = exr_pixels(data)
            width, height, depth = len(rows[0])//4, len(rows), 32
            values = [v for row in reversed(rows) for v in row]
        image = Image(path.stem, width, height)
        image.source, image.type, image.filepath = "FILE", "IMAGE", filepath
        image.is_float = depth != 8
        image.bl_rna = NS(properties={"alpha_mode": NS(type="ENUM", is_readonly=False,
            is_array=False, is_enum_flag=False, enum_items=[NS(identifier=v) for v in ("STRAIGHT", "PREMUL", "CHANNEL_PACKED", "NONE")])})
        image.pixels = NativePixels(image, values, depth)
        env.images.append(image)
        return image
    monkeypatch.setattr(env.images, "load", load, raising=False)
    return env


def start_export(env, *, format="EXR32_RAW", name="Reimported", context=None, **values):
    path = env.folder / ("texture.png" if format.startswith("PNG") else "texture.exr")
    env.path = path
    return env.context().registry.dispatch("image.export_job_start", {"image_name": "Original", "new_name": name,
        "filepath": str(path), "format": format, **values}, context or env.context())


@pytest.mark.parametrize("format", ["PNG8", "PNG16", "EXR32", "EXR32_RAW"])
@pytest.mark.parametrize("role", ["COLOR", "DATA"])
def test_typed_export_reimport_full_channels_source_preservation_and_terminal_history(delivery, format, role):
    env = delivery
    source = env.images[0]
    source.colorspace_settings.name = "Non-Color" if role == "DATA" else "Linear Rec.709"
    source.alpha_mode = "CHANNEL_PACKED"
    source.pixels.values[3] = 0.
    before = env.paint.brush.digest(source.pixels.values)
    accepted = start_export(env, format=format)
    assert accepted["accepted"] and not accepted["export_completed"] and not env.path.exists() and not env.marks
    terminal = finish(env)
    assert terminal["state"] == "SUCCEEDED", terminal
    result = terminal["result"]
    assert result["source_pixels_unchanged"] and env.paint.brush.digest(source.pixels.values) == before
    assert result["pixel_verification"]["all_channels_compared"] == 64
    assert result["pixel_verification"]["pixel_roundtrip_verified"]
    assert env.images.get("Reimported") is not None and env.path.is_file()
    assert terminal["undo_boundary_finalized"] and len(env.marks) == 2
    evidence = terminal["external_effects"]
    assert evidence["file_published"] and evidence["published_file_hash_verified"]
    assert evidence["native_decode_verified"] and evidence["pixel_roundtrip_verified"]
    assert evidence["staging_cleanup"] == "removed" and evidence["retained_staging_path"] is None
    assert not evidence["native_undo_removes_external_file"] and not result["project_saved"] and not result["bound_to_nodes"]
    history = env.context().state.history(1)[0]
    assert history["tool"] == "image.export_job_start" and history["job_evidence"]["external_effects"]["file_sha256"]
    assert env.manager.history[0].driver is None and not env.manager.history[0].prepared


def test_no_export_io_before_acknowledged_handoff_and_one_shared_active_limit(delivery):
    env = delivery
    lease = importlib.import_module(env.module.RequestLifetime.__module__)
    lifetime = lease.RequestLifetime(lease.ConnectionLifetime(), float("inf"))
    context = env.context()
    context.request_lifecycle = lifetime
    start_export(env, context=context)
    assert env.manager.tick() and env.manager.active.work is None and not list(env.folder.iterdir())
    with pytest.raises(env.module.BridgeError, match="already active"):
        env.manager.start(env.context(), {}, 30.)
    lifetime.acknowledge(False)
    terminal = finish(env)
    assert terminal["state"] == "CANCELLED" and not list(env.folder.iterdir()) and not env.marks
    assert not lifetime.connection.background_active.is_set()


@pytest.mark.parametrize("permission", ["EDIT_MATERIALS", "ACCESS_EXTERNAL_FILES", "SAVE_PROJECT"])
def test_each_authoritative_grant_required_before_export_source_or_path_work(delivery, permission):
    delivery.grants[permission] = False
    with pytest.raises(delivery.module.BridgeError) as error:
        start_export(delivery)
    assert error.value.code == "PERMISSION_DENIED" and delivery.manager.active is None
    assert not list(delivery.folder.iterdir())


@pytest.mark.parametrize("change", ["pixels", "metadata", "identity", "mode", "name", "root", "animation"])
def test_stale_source_or_scope_never_publishes_a_file(delivery, monkeypatch, change):
    env = delivery
    start_export(env)
    if change == "pixels":
        env.images[0].pixels.values[0] = .8
    elif change == "metadata":
        env.images[0].alpha_mode = "PREMUL"
    elif change == "identity":
        env.images[0] = Image("Original")
    elif change == "mode":
        env.bpy.context.mode = "EDIT_MESH"
    elif change == "name":
        env.images.append(Image("Reimported"))
    elif change == "root":
        monkeypatch.setattr(env.delivery.images, "_root", lambda: "")
    else:
        env.images[0].animation_data = NS(action=object())
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and not env.path.exists() and not env.marks
    assert not terminal["external_effects"]["file_published"]


@pytest.mark.parametrize("stage", ["before_publish", "after_publish", "after_native"])
def test_cancellation_never_erases_file_effects_or_a_finalized_native_image(delivery, monkeypatch, stage):
    env = delivery
    if stage != "after_native":
        original = env.delivery.TextureStaging.publish
        def publish(resource):
            if stage == "before_publish":
                env.manager.cancel(env.manager.active.job_id)
            result = original(resource)
            if stage == "after_publish":
                env.manager.cancel(env.manager.active.job_id)
            return result
        monkeypatch.setattr(env.delivery.TextureStaging, "publish", publish)
    else:
        original = env.verification.compare_steps
        def compare(*args, **kwargs):
            env.manager.cancel(env.manager.active.job_id)
            yield from original(*args, **kwargs)
        monkeypatch.setattr(env.verification, "compare_steps", compare)
    start_export(env)
    terminal = finish(env)
    assert terminal["state"] == "CANCELLED" and terminal["result"] is None
    assert env.path.exists() is (stage != "before_publish")
    assert terminal["external_effects"]["file_published"] is (stage != "before_publish")
    assert (env.images.get("Reimported") is not None) is (stage == "after_native")
    assert terminal["undo_boundary_finalized"] is (stage == "after_native")
    if stage != "before_publish":
        assert terminal["error"]["context"]["possible_mutation"]
        assert not terminal["error"]["context"]["rollback_verified"]
    if stage == "after_native":
        assert terminal["external_effects"]["post_commit_image_cleanup"] == "explicit_recovery_required"


def test_revoked_file_consent_retains_exact_staging_and_audit_path(delivery, monkeypatch):
    env = delivery
    original = env.delivery.TextureStaging._append
    def write(resource, data):
        original(resource, data)
        env.grants["ACCESS_EXTERNAL_FILES"] = False
    monkeypatch.setattr(env.delivery.TextureStaging, "_append", write)
    start_export(env)
    terminal = finish(env)
    evidence = terminal["external_effects"]
    assert terminal["state"] == "FAILED" and not env.path.exists()
    assert evidence["staging_cleanup"] == "retained_permission_denied"
    assert Path(evidence["retained_staging_path"]).exists()
    assert terminal["error"]["context"]["possible_mutation"]
    assert env.context().state.history(1)[0]["job_evidence"]["external_effects"] == evidence


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_failed_native_checkpoint_retains_published_file_and_never_reports_success(delivery, boundary):
    env = delivery
    setattr(env.checkpoints, boundary+"_modification", lambda _name: False)
    start_export(env)
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and terminal["result"] is None and env.path.exists()
    assert (env.images.get("Reimported") is not None) is (boundary == "after")
    assert terminal["external_effects"]["file_published"] and not terminal["undo_boundary_finalized"]


def test_interleaved_output_edit_is_not_silently_deleted_on_verification_failure(delivery, monkeypatch):
    env = delivery
    original = env.verification.compare_steps
    def compare(*args, **kwargs):
        result = yield from original(*args, **kwargs)
        env.images.get("Reimported").pixels.values[0] = .95
        return result
    monkeypatch.setattr(env.verification, "compare_steps", compare)
    start_export(env)
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and env.path.exists()
    assert env.images.get("Reimported").pixels.values[0] == pytest.approx(.95)
    assert terminal["external_effects"]["post_commit_image_cleanup"] == "explicit_recovery_required"


@pytest.mark.parametrize("target", ["file", "name"])
def test_existing_targets_are_never_overwritten_or_renamed(delivery, target):
    env = delivery
    if target == "file":
        (env.folder/"texture.exr").write_bytes(b"Keep this")
    else:
        env.images.append(Image("Reimported"))
    with pytest.raises(env.module.BridgeError, match="already exists"):
        start_export(env)
    assert env.manager.active is None
    if target == "file":
        assert (env.folder/"texture.exr").read_bytes() == b"Keep this"


@pytest.mark.parametrize("value", [True, 0, 301, math.inf, "120"])
def test_export_deadline_schema_is_bounded_without_coercion(value):
    schema = get_type_hints(ImagePaintTools.image_export_job_start, include_extras=True)["time_limit_seconds"]
    with pytest.raises(ValidationError):
        TypeAdapter(schema).validate_python(value)


def test_export_mcp_wrapper_forwards_only_typed_parameters():
    class Registry:
        async def call(self, method, params):
            return method, params
    wrapper = ImagePaintTools()
    wrapper.registry = Registry()
    method, params = asyncio.run(wrapper.image_export_job_start("Source", "Reopened", "C:/approved/exact.exr", "EXR32_RAW", 240.))
    assert method == "image.export_job_start" and params == {"image_name": "Source", "new_name": "Reopened", "filepath": "C:/approved/exact.exr", "format": "EXR32_RAW", "time_limit_seconds": 240.}


def test_cleanup_exception_cannot_erase_published_file_from_terminal_history(delivery, monkeypatch):
    env = delivery
    resources = []
    def fail(resource):
        resources.append(resource)
        raise RuntimeError("injected cleanup fault")
    monkeypatch.setattr(env.delivery.TextureStaging, "cleanup", fail)
    start_export(env)
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and terminal["result"] is None and env.path.exists()
    assert terminal["external_effects"]["file_published"] and terminal["external_effects"]["file_sha256"]
    assert terminal["error"]["context"]["cleanup_outcome_unknown"] and terminal["error"]["context"]["possible_mutation"]
    assert env.context().state.history(1)[0]["job_evidence"]["external_effects"]["filepath"] == str(env.path)
    assert resources and resources[0].closed and resources[0].stream is None and not resources[0].pins.handles


def test_native_decode_stop_with_delete_denied_preserves_both_file_and_last_image_name(delivery, monkeypatch):
    env = delivery
    original = env.images.load
    def load(*args, **kwargs):
        image = original(*args, **kwargs)
        env.grants["SAVE_PROJECT"] = env.grants["DELETE_OBJECTS"] = False
        return image
    monkeypatch.setattr(env.images, "load", load)
    start_export(env)
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and env.path.exists() and terminal["undo_boundary_finalized"]
    assert terminal["error"]["context"]["cleanup_permission_denied"]
    name = terminal["external_effects"]["last_observed_reimport_image_name"]
    assert name and env.images.get(name) is not None and name != "Reimported"


@pytest.mark.parametrize("failure", ["pause", "deadline", "disconnect", "toolset", "emergency"])
def test_export_lifecycle_stops_before_handoff_or_file_effects(delivery, failure):
    env = delivery
    lease = importlib.import_module(env.module.RequestLifetime.__module__)
    lifetime = lease.RequestLifetime(lease.ConnectionLifetime(), float("inf"))
    context = env.context()
    context.request_lifecycle = lifetime
    start_export(env, context=context)
    if failure == "pause":
        env.context().state.set_paused(True)
        assert env.manager.tick() and env.manager.active.state == "PAUSED" and not env.manager.active.work
        env.manager.active.deadline = 0
    elif failure == "deadline":
        env.manager.active.deadline = 0
    elif failure == "disconnect":
        lifetime.connection.disconnected.set()
    elif failure == "toolset":
        lifetime.acknowledge(True)
        env.context().registry.disable_toolset("materials")
    else:
        env.context().state.set_emergency_stopped(True)
    terminal = finish(env)
    assert terminal["state"] == ("FAILED" if failure == "toolset" else "CANCELLED")
    assert not list(env.folder.iterdir()) and not env.marks


def test_export_registry_is_nonbatchable_and_control_status_does_not_leak_file_evidence(delivery):
    env = delivery
    spec = env.context().registry.get("image.export_job_start")
    assert spec.modifies and not spec.automatic_checkpoint and not spec.batchable
    assert {p.value for p in spec.permissions} == {"EDIT_MATERIALS", "ACCESS_EXTERNAL_FILES", "SAVE_PROJECT"}
    start_export(env)
    assert "external_effects" not in env.manager.status()["active"]
    env.manager.cancel_all("test cleanup")
    assert "external_effects" not in env.manager.status()["last_terminal"]


def test_associated_color_normalization_is_explicit_and_not_raw_input_identity(delivery):
    env = delivery
    source = env.images[0]
    source.alpha_mode = "PREMUL"
    source.pixels.values = array("f", [.05,.1,.15,.25])*16
    before = env.paint.brush.digest(source.pixels.values)
    start_export(env)
    terminal = finish(env)
    assert terminal["state"] == "SUCCEEDED", terminal
    result = terminal["result"]
    assert result["source_associated_converted_to_straight"] and not result["raw_input_float32_recovery_verified"]
    assert result["source_pixels_sha256_float32_le"] == before != result["encoded_source_pixels_sha256_float32_le"]
    assert list(env.images.get("Reimported").pixels.values[:4]) == pytest.approx([.2,.4,.6,.25])
    assert result["pixel_verification"]["native_pixels_sha256_float32_le"] == result["encoded_source_pixels_sha256_float32_le"]
    assert env.paint.brush.digest(source.pixels.values) == before


def test_export_acceptance_history_is_not_completion_and_polling_does_not_evict_it(delivery):
    env = delivery
    executor_module = importlib.import_module(env.module.__package__+".executor")
    queue_module = importlib.import_module(env.module.__package__+".command_queue")
    context = env.context()
    executor = executor_module.MainThreadExecutor(command_queue=queue_module.CommandQueue(), registry=context.registry,
        state=context.state, permissions=context.permissions, checkpoints=context.checkpoints, jobs=env.manager)
    accepted = executor.dispatch("image.export_job_start", {"image_name": "Original", "new_name": "Reimported",
        "filepath": str(env.folder/"history.exr"), "format": "EXR32_RAW"})
    assert "not yet completed" in context.state.history(1)[0]["description"] and not env.marks
    for _ in range(60):
        executor.dispatch("jobs.inspect", {"job_id": accepted["job_id"]})
    assert len(context.state.history(50)) == 1
    terminal = finish(env)
    records = context.state.history(50)
    assert terminal["state"] == "SUCCEEDED" and len(records) == 2
    assert records[0]["job_evidence"]["external_effects"]["file_published"]


def test_uncertain_link_effect_is_retained_even_when_publication_raises(delivery, monkeypatch):
    env = delivery
    resource_module = importlib.import_module(env.module.__package__+".texture_staging")
    original = resource_module.os.link
    def link(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("injected exception after actual link")
    monkeypatch.setattr(resource_module.os, "link", link)
    start_export(env)
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and env.path.is_file()
    effects = terminal["external_effects"]
    assert effects["publication_attempted"] and effects["publication_outcome_unknown"] and not effects["file_published"]
    assert effects["requested_output_path"] == str(env.path) and effects["file_sha256"]
    assert terminal["error"]["context"]["possible_mutation"] and not terminal["error"]["context"]["rollback_verified"]


def test_source_change_after_publication_never_rewrites_input_or_hides_published_file(delivery, monkeypatch):
    env = delivery
    original = env.delivery.TextureStaging.publish
    def publish(resource):
        result = original(resource)
        env.images[0].pixels.values[0] = .9
        return result
    monkeypatch.setattr(env.delivery.TextureStaging, "publish", publish)
    start_export(env)
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and terminal["error"]["context"]["stale_source"]
    assert env.path.is_file() and not env.images.get("Reimported") and not terminal["execution_started"]
    assert terminal["external_effects"]["file_published"] and terminal["error"]["context"]["possible_mutation"]
    assert env.images[0].pixels.values[0] == pytest.approx(.9)


def test_recovery_history_redacts_job_file_details_without_inspection_and_retains_local_audit(delivery):
    import json
    env = delivery
    core = importlib.import_module(env.module.__package__+".tools.core")
    env.checkpoints.list = lambda _limit: []
    env.checkpoints.recovery_status = lambda **_kwargs: {}
    start_export(env)
    terminal = finish(env)
    assert terminal["state"] == "SUCCEEDED"
    env.grants["INSPECT_SCENE"] = False
    redacted = core.checkpoint_list(env.context(), {"limit": 10})
    assert terminal["external_effects"]["file_sha256"] not in json.dumps(redacted)
    assert redacted["operation_history"][0]["job_evidence"] is None
    assert redacted["operation_history"][0]["job_evidence_redacted"] is True
    assert redacted["operation_history"][0]["job_evidence"] is None
    env.grants["INSPECT_SCENE"] = True
    complete = core.checkpoint_list(env.context(), {"limit": 10})
    assert complete["operation_history"][0]["job_evidence"]["external_effects"]["filepath"] == str(env.path)
