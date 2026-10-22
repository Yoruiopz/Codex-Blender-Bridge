from __future__ import annotations

import asyncio
import importlib
import json
from array import array
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError
from test_image_portability import Image, _last_provider_fault, fixture, packed  # noqa: F401

from mcp_server.tools.image_recovery_jobs import ImageRecoveryJobTools


@pytest.fixture
def env(request, addon_package, monkeypatch):
    base = request.getfixturevalue("fixture")
    domain = importlib.import_module(f"{addon_package}.tools.image_recovery_jobs")
    module = importlib.import_module(f"{addon_package}.jobs")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    base.grants["INSPECT_SCENE"] = True
    manager_class = importlib.import_module(f"{addon_package}.permissions").PermissionManager
    permissions = manager_class(lambda: base.grants)
    registry = registry_module.ToolRegistry(enabled_toolsets=("materials",))
    domain.register_tools(registry)
    importlib.import_module(f"{addon_package}.tools.paint_jobs").register_tools(registry)
    marks = []
    checkpoints = NS(before_modification=lambda label: marks.append(("before", label)) or True,
                     after_modification=lambda label: marks.append(("after", label)) or True)
    def context():
        return registry_module.ToolContext(state, permissions, registry, checkpoints, jobs=manager)
    manager = module.PaintJobs(context, budget_ms=lambda: 1.)
    for target in (domain, domain.image_recovery, module):
        monkeypatch.setattr(target, "require_blender", lambda: base.bpy)
    return NS(base=base, domain=domain, module=module, state=state, permissions=permissions,
              registry=registry, context=context, manager=manager, marks=marks, checkpoints=checkpoints,
              images=base.images, bpy=base.bpy, grants=base.grants)


def snapshot(env, name="Snapshot", context=None):
    return env.domain.snapshot_job_start(context or env.context(), {"image_name": "Original", "new_name": name})


def preview(env, **extra):
    return env.domain.recovery_job_preview(env.context(), {"image_name": "Original", "snapshot_name": "Snapshot", **extra})


def restoration(env, inspected=None, context=None, **extra):
    inspected = inspected or preview(env)
    return env.domain.restore_snapshot_job_start(context or env.context(), {"image_name": "Original", "snapshot_name": "Snapshot",
        "expected_target_fingerprint": inspected["expected_target_fingerprint"], **extra})


def finish(env):
    for _ in range(2000):
        if not env.manager.tick():
            return env.manager.history[0].summary()
    pytest.fail("Recovery job never terminated")


def test_snapshot_job_waits_for_delivery_then_publishes_complete_raw_version(env):
    lease = importlib.import_module(env.module.RequestLifetime.__module__)
    lifetime = lease.RequestLifetime(lease.ConnectionLifetime(), float("inf"))
    context = env.context()
    context.request_lifecycle, context.request_id = lifetime, "snapshot-start"
    result = snapshot(env, context=context)
    assert result["accepted"] and not result["job_completed"]
    assert result["kind"] == "image.current_pixels_snapshot" and not result["recovery_evidence"]["snapshot_retained"]
    assert env.manager.tick() and env.manager.active.work is None and not env.marks
    assert env.images.get("Snapshot") is None
    lifetime.acknowledge(True)
    terminal = finish(env)
    assert terminal["state"] == "SUCCEEDED" and terminal["undo_boundary_finalized"]
    assert terminal["result"]["current_pixels_verified"] and terminal["recovery_evidence"]["snapshot_retained"]
    assert env.images.get("Snapshot")[env.domain.storage.OWNER_KEY] is env.base.target
    assert terminal["external_effects"] == {} and env.manager.history[0].prepared == {}
    assert env.state.history()[0]["recovery_evidence"]["complete_pixels_verified"]


def test_loaded_recovery_job_preserves_original_identity_packed_bytes_and_snapshot(env):
    packed(env.base)
    env.base.target.pixels.values[:] = array("f", [1.]) * 8
    inspected = preview(env)
    assert inspected["mode"] == "LOADED_BUFFER" and not inspected["snapshot_pixels_verified"]
    assert not inspected["requires_confirm_replace_packed_bytes"]
    result = restoration(env, inspected)
    assert result["accepted"] and not result["execution_started"]
    terminal = finish(env)
    assert terminal["state"] == "SUCCEEDED", terminal
    assert terminal["result"]["image_identity_preserved"] and terminal["result"]["complete_pixels_verified"]
    assert not terminal["result"]["packed_payload_replaced"]
    assert env.base.target.pixels.values.tobytes() == env.base.values.tobytes()
    assert env.base.target.packed_file is None and env.images.get("Snapshot") is not None


@pytest.mark.parametrize("kind", ["snapshot", "restore"])
@pytest.mark.parametrize("failure", ["disconnect", "rejected", "handoff", "deadline", "cancel", "stop"])
def test_recovery_cancellation_before_publication_never_creates_or_writes_image(env, kind, failure):
    if kind == "restore":
        packed(env.base)
        env.base.target.pixels.values[:] = array("f", [1.]) * 8
        before = env.base.target.pixels.values.tobytes()
    lease = importlib.import_module(env.module.RequestLifetime.__module__)
    lifetime = lease.RequestLifetime(lease.ConnectionLifetime(), float("inf"))
    context = env.context()
    context.request_lifecycle = lifetime
    (snapshot if kind == "snapshot" else restoration)(env, context=context)
    if failure == "disconnect":
        lifetime.connection.disconnected.set()
    elif failure == "rejected":
        lifetime.acknowledge(False)
    elif failure == "handoff":
        lifetime.deadline = 0
    elif failure == "deadline":
        env.manager.active.deadline = 0
    elif failure == "cancel":
        env.manager.cancel(env.manager.active.job_id)
    else:
        env.state.set_emergency_stopped(True)
    terminal = finish(env)
    assert terminal["state"] == "CANCELLED" and not terminal["execution_started"]
    assert terminal["error"]["context"]["possible_mutation"] is False and not env.marks
    if kind == "snapshot":
        assert env.images.get("Snapshot") is None and not terminal["recovery_evidence"]["snapshot_retained"]
    else:
        assert env.base.target.pixels.values.tobytes() == before and env.base.target.pixels.writes == 0
        assert terminal["recovery_evidence"]["snapshot_retained"]
    assert env.manager.history[0].prepared == {}


def test_pause_holds_private_recovery_and_deadline_continues(env):
    snapshot(env)
    env.state.set_paused(True)
    assert env.manager.tick() and env.manager.active.state == "PAUSED"
    assert env.manager.active.work is None and env.images.get("Snapshot") is None
    env.manager.active.deadline = 0
    assert finish(env)["state"] == "CANCELLED"


@pytest.mark.parametrize("change", ["pixels", "metadata", "identity", "mode", "name", "permission", "toolset"])
def test_snapshot_commit_preserves_newer_input_and_rejects_stale_scope(env, change):
    snapshot(env)
    if change == "pixels":
        env.base.target.pixels.values[0] = .75
    elif change == "metadata":
        env.base.target.alpha_mode = "STRAIGHT"
    elif change == "identity":
        env.images[0] = Image("Original", env.base.values, env.base.module, users=1)
    elif change == "mode":
        env.bpy.context.mode = "EDIT_MESH"
    elif change == "name":
        env.images.append(Image("Snapshot", env.base.values, env.base.module))
    elif change == "permission":
        env.grants["EDIT_MATERIALS"] = False
    else:
        env.registry.disable_toolset("materials")
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and not terminal["execution_started"]
    assert env.images.get("Snapshot") is None or change == "name"


def test_recovery_preview_requires_only_inspection_and_freezes_target_hash(env):
    packed(env.base)
    env.grants["EDIT_MATERIALS"] = False
    result = preview(env)
    assert len(result["expected_target_fingerprint"]) == 64 and not result["mutation_performed"]
    assert env.base.target.pixels.writes == 0 and not env.marks


def test_stale_recovery_preview_rejected_before_acceptance(env):
    packed(env.base)
    inspected = preview(env)
    env.base.target.pixels.values[0] = .75
    with pytest.raises(env.domain.BridgeError, match="fingerprint"):
        restoration(env, inspected)
    assert env.manager.active is None and env.base.target.pixels.writes == 0


@pytest.mark.parametrize("change", ["target_pixels", "snapshot_bytes", "snapshot_owner", "target_role", "same_name"])
def test_restore_job_detects_input_changes_after_acceptance_without_target_write(env, change):
    packed(env.base)
    restoration(env)
    if change == "target_pixels":
        env.base.target.pixels.values[0] = .75
    elif change == "snapshot_bytes":
        env.images.get("Snapshot").packed_file.data = b"changed"
    elif change == "snapshot_owner":
        dict.__setitem__(env.images.get("Snapshot"), env.base.module.OWNER_KEY, None)
    elif change == "target_role":
        env.base.target.alpha_mode = "STRAIGHT"
    else:
        env.images[0] = Image("Original", env.base.values, env.base.module, users=1)
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and not terminal["execution_started"]
    assert env.base.target.pixels.writes == 0


def test_newly_acquired_snapshot_receives_no_later_writes_and_is_reported_as_partial(env, monkeypatch):
    snapshot(env)
    before = env.base.target.pixels.values.tobytes()
    original_new = env.images.new
    def acquired(*args, **kwargs):
        image = original_new(*args, **kwargs)
        image.users = 1
        return image
    monkeypatch.setattr(env.images, "new", acquired)
    terminal = finish(env)
    image = env.images.get("Snapshot")
    assert terminal["state"] == "FAILED" and terminal["execution_started"] and image is not None
    assert image.source == "GENERATED" and image.packed_file is None
    assert env.base.module.METADATA_KEY not in image and not image.use_fake_user
    assert not terminal["recovery_evidence"]["snapshot_retained"]
    assert terminal["recovery_evidence"]["retained_image_name"] == "Snapshot"
    assert env.base.target.pixels.values.tobytes() == before


def test_checkpoint_interleaving_original_pixels_is_rechecked_before_any_restoration(env):
    packed(env.base)
    restoration(env)
    def checkpoint(label):
        env.marks.append(("before", label))
        env.base.target.pixels.values[0] = .75
        return True
    env.checkpoints.before_modification = checkpoint
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and not terminal["execution_started"]
    assert env.base.target.pixels.values[0] == .75 and env.base.target.pixels.writes == 0


def test_late_permission_denial_retains_restored_pixels_and_original_snapshot(env, monkeypatch):
    packed(env.base)
    env.base.target.pixels.values[:] = array("f", [1.]) * 8
    restoration(env)
    update = env.base.target.update
    def revoked():
        update()
        env.grants["EDIT_MATERIALS"] = False
    monkeypatch.setattr(env.base.target, "update", revoked)
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and terminal["execution_started"]
    assert terminal["error"]["code"] == "PERMISSION_DENIED"
    assert terminal["recovery_evidence"]["possible_mutation"] and terminal["recovery_evidence"]["snapshot_retained"]
    assert not terminal["recovery_evidence"]["complete_pixels_verified"]
    assert env.base.target.pixels.values.tobytes() == env.base.values.tobytes()
    assert terminal["external_effects"] == {} and env.manager.history[0].prepared == {}


def test_oversized_snapshot_refused_without_accessing_packed_data(env):
    packed(env.base)
    class TooLarge:
        size = env.domain.MAX_BYTES+1
        @property
        def data(self):
            pytest.fail("Oversized packed data read")
    env.images.get("Snapshot").packed_file = TooLarge()
    with pytest.raises(env.domain.BridgeError):
        preview(env)
    assert env.manager.active is None


@pytest.mark.parametrize("bad", ["bad_layout", "raw_digest", "nonfinite"])
def test_private_snapshot_decode_failure_never_mutates_original(env, bad):
    packed(env.base)
    snapshot_image = env.images.get("Snapshot")
    metadata = json.loads(snapshot_image[env.base.module.METADATA_KEY])
    if bad == "bad_layout":
        snapshot_image.packed_file.data = b"bad" + snapshot_image.packed_file.data[3:]
    elif bad == "raw_digest":
        metadata["pixels_sha256_float32_le"] = "0"*64
    else:
        values = array("f", env.base.values)
        values[0] = float("nan")
        payload = bytearray(snapshot_image.packed_file.data)
        header = env.domain.pixel_codecs.exr_header(2, 1, "EXR32_RAW", "DATA")
        import struct
        struct.pack_into("<f", payload, len(header)+8+8+3*2*4, float("nan"))
        snapshot_image.packed_file.data = bytes(payload)
    metadata["packed_sha256"] = env.domain.hashlib.sha256(snapshot_image.packed_file.data).hexdigest()
    snapshot_image[env.base.module.METADATA_KEY] = json.dumps(metadata)
    restoration(env)
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and not terminal["execution_started"]
    assert env.base.target.pixels.writes == 0


def test_job_mcp_forwards_strict_confirmation_fingerprint_and_deadline():
    calls = []
    class Registry:
        async def call(self, name, params):
            calls.append((name, params))
            return {"forwarded": True}
    tools = ImageRecoveryJobTools(Registry())
    asyncio.run(tools.image_restore_snapshot_job_start("Original", "Snapshot", "a"*64, True, False, 123.))
    assert calls[0] == ("image.restore_snapshot_job_start", {"image_name": "Original", "snapshot_name": "Snapshot",
        "expected_target_fingerprint": "a"*64, "confirm_replace_packed_bytes": True, "allow_shared": False, "time_limit_seconds": 123.})
    hints = get_type_hints(tools.image_restore_snapshot_job_start, include_extras=True)
    for bad in (True, 0., 301., float("inf"), "60"):
        with pytest.raises(ValidationError):
            TypeAdapter(hints["time_limit_seconds"]).validate_python(bad)
    for bad in (True, "bad", "A"*64):
        with pytest.raises(ValidationError):
            TypeAdapter(hints["expected_target_fingerprint"]).validate_python(bad)


@pytest.mark.parametrize("field_name", ["recovery_evidence", "evidence"])
def test_failed_evidence_observation_retains_last_facts_and_unconditionally_releases_owner(env, monkeypatch, field_name):
    lease = importlib.import_module(env.module.RequestLifetime.__module__)
    lifetime = lease.RequestLifetime(lease.ConnectionLifetime(), float("inf"))
    context = env.context()
    context.request_lifecycle = lifetime
    accepted = snapshot(env, context=context)
    job = env.manager.active
    assert lifetime.connection.background_active.is_set()
    prior = dict(job.recovery_evidence)
    def failure():
        raise ReferenceError("Native image was removed during evidence observation")
    monkeypatch.setattr(job.driver, field_name, failure)
    summary = env.manager.inspect(accepted["job_id"])
    key = "external_effects" if field_name == "evidence" else field_name
    assert summary["evidence_observation_unknown"] == [key]
    assert summary["recovery_evidence"] == prior
    env.manager.cancel_all("fixture cancellation")
    assert env.manager.active is None and job.prepared == {} and job.work is None
    assert job.driver is None and not lifetime.connection.background_active.is_set()
    summary = env.manager.inspect(accepted["job_id"])
    assert summary["terminal"] and summary["evidence_observation_unknown"] == [key]
    assert summary["error"]["context"]["evidence_observation_unknown"] == [key]
    assert summary["recovery_evidence"]["snapshot_retained"] is False
    assert env.state.history()[0]["job_evidence"]["evidence_observation_unknown"] == [key]


def test_failed_operation_recording_releases_job_with_truthful_terminal_error(env, monkeypatch):
    snapshot(env)
    job = env.manager.active
    def failure(**kwargs):
        raise RuntimeError("Fixture unavailable history")
    monkeypatch.setattr(env.state, "record_operation", failure)
    terminal = finish(env)
    assert terminal["state"] == "FAILED" and terminal["result"] is None
    assert terminal["progress"]["phase"] == "failed"
    assert terminal["error"]["context"]["operation_history_unknown"]
    assert terminal["recovery_evidence"]["snapshot_retained"]
    assert env.manager.active is None and job.prepared == {} and job.driver is None


def test_actual_terminal_snapshot_name_and_hash_are_redacted_without_inspect(env, monkeypatch):
    accepted = snapshot(env, "Private Recovery Texture")
    terminal = finish(env)
    assert terminal["state"] == "SUCCEEDED"
    native_hash = terminal["recovery_evidence"]["packed_sha256"]
    core = importlib.import_module(env.module.__package__ + ".tools.core")
    monkeypatch.setattr(env.checkpoints, "list", lambda limit: [], raising=False)
    monkeypatch.setattr(env.checkpoints, "recovery_status", lambda limit: {}, raising=False)
    env.grants["INSPECT_SCENE"] = False
    hidden = core.checkpoint_list(env.context(), {"limit": 20})
    assert "Private Recovery Texture" not in json.dumps(hidden)
    assert native_hash not in json.dumps(hidden)
    record = hidden["operation_history"][0]
    assert record["description_redacted"] and record["recovery_evidence_redacted"] and record["job_evidence_redacted"]
    local = env.state.history()[0]
    assert "Private Recovery Texture" in local["description"]
    assert local["recovery_evidence"]["packed_sha256"] == native_hash
    assert env.manager.inspect(accepted["job_id"])["recovery_evidence"]["snapshot_retained"]


@pytest.mark.parametrize("operation", ["snapshot_allocate", "snapshot_metadata", "restore_loaded", "restore_unloaded"])
@pytest.mark.parametrize("fault", ["cancel", "disconnect", "deadline", "toolset"])
def test_last_provider_job_events_block_next_native_image_write(env, operation, fault):
    lease = importlib.import_module(env.module.RequestLifetime.__module__)
    lifetime = lease.RequestLifetime(lease.ConnectionLifetime(), float("inf"))
    lifetime.acknowledge(True)
    context = env.context()
    context.request_lifecycle = lifetime
    if operation.startswith("restore"):
        if operation == "restore_unloaded":
            env.base.target.source, env.base.target.type = "FILE", "IMAGE"
            env.base.target.filepath = "/missing/source.exr"
        packed(env.base)
        env.base.target.pixels.values[:] = array("f", [1.]) * 8
        if operation == "restore_unloaded":
            env.base.target.has_data = False
        restoration(env, context=context, confirm_replace_packed_bytes=True)
    else:
        snapshot(env, context=context)
    job = env.manager.active
    worker = env.manager._context(job)
    assert worker.request_lifecycle is lifetime and worker.check_final_job is not None
    # The assignable facade injects after the real worker gate's last provider.
    ctx = NS(require=worker.require, permissions=worker.permissions, registry=worker.registry,
        state=worker.state, request_lifecycle=worker.request_lifecycle)
    ctx.check_cancelled = lambda: env.manager._check(job, ctx)
    ctx.check_final_job = lambda: env.manager._lifetime_check(job, ctx)
    driver = job.driver
    before = env.base.target.pixels.values.tobytes()
    def mutate():
        if fault == "cancel":
            job.cancel_reason = "Provider-triggered cancellation"
        elif fault == "disconnect":
            lifetime.connection.disconnected.set()
        elif fault == "deadline":
            job.deadline = 0
        else:
            env.registry.disable_toolset("materials")
    injected = _last_provider_fault(ctx, lambda: env.domain._gate(ctx, env.base.target),
        lambda: operation != "snapshot_metadata" or driver.output is not None, mutate)
    payload = b"".join(step.data for step in env.domain.pixel_codecs.encode_steps(env.base.values, 2, 1, "EXR32_RAW", "DATA"))
    with pytest.raises(env.domain.BridgeError) as caught:
        if operation.startswith("snapshot"):
            driver._publish(ctx, job, payload, env.domain.brush.digest(env.base.values))
        else:
            driver._publish(ctx, job, env.base.values, payload)
    assert injected == [True]
    assert caught.value.code == ("TOOLSET_DISABLED" if fault == "toolset" else "TIMEOUT")
    assert env.base.target.pixels.values.tobytes() == before and env.base.target.pixels.writes == 0
    assert env.base.target.packed_file is None
    if operation == "snapshot_metadata":
        output = env.images.get("Snapshot")
        assert output is not None and output.source == "GENERATED" and output.filepath == ""
        assert output.packed_file is None and not output and not output.use_fake_user
    elif operation == "snapshot_allocate":
        assert env.images.get("Snapshot") is None
