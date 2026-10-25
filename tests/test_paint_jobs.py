from __future__ import annotations

import importlib
import threading
from array import array
from types import SimpleNamespace as NS

import pytest
from test_image_paint import Image, paint_tools, stroke  # noqa: F401

pytestmark = pytest.mark.parametrize("jobs", ("paint", "native_save"), indirect=True)


@pytest.fixture
def jobs(request, addon_package, monkeypatch):
    paint, _, images, bpy, grants = request.getfixturevalue("paint_tools")
    module = importlib.import_module(f"{addon_package}.jobs")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions").PermissionManager(lambda: grants)
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    registry = registry_module.ToolRegistry(enabled_toolsets=("materials",))
    importlib.import_module(f"{addon_package}.tools.paint_jobs").register_tools(registry)
    marks = []
    checkpoints = NS(before_modification=lambda name: marks.append(("before", name)) or True,
                     after_modification=lambda name: marks.append(("after", name)) or True)
    def context():
        return registry_module.ToolContext(state, permissions, registry, checkpoints, jobs=manager)
    if getattr(request, "param", "paint") == "native_save":
        runtime = importlib.import_module(f"{addon_package}.runtime")
        policy_module = importlib.import_module(f"{addon_package}.native_save_policy")
        grant = policy_module.NativeSaveGrant("inherited-paint-fixture", object())
        assert not grant.active() and grant.status()["armed"] is False
        manager = runtime.NativeSaveJobs(
            context, budget_ms=lambda: 1., registry=registry, native_save_policy=grant,
        )
    else:
        manager = module.PaintJobs(context, budget_ms=lambda: 1.)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    return NS(module=module, manager=manager, context=context, images=images, bpy=bpy,
              grants=grants, marks=marks, checkpoints=checkpoints, paint=paint)


def start(env, name="Painted", context=None):
    return env.manager.start(context or env.context(),
        {"image_name": "Original", "new_name": name, "strokes": [stroke()]}, 60.)


def finish(env):
    for _ in range(2000):
        if not env.manager.tick():
            return env.manager.history[0].summary()
    pytest.fail("job never terminated")


def test_no_brush_work_or_checkpoint_before_start_delivery_and_lease_survives_rpc_deadline(jobs, monkeypatch):
    env = jobs
    connection = env.module.RequestLifetime.__module__
    lifetime_module = importlib.import_module(connection)
    lifetime = lifetime_module.RequestLifetime(lifetime_module.ConnectionLifetime(), float("inf"))
    context = env.context()
    context.request_lifecycle, context.request_id = lifetime, "start-1"
    accepted = start(env, context=context)
    assert accepted["accepted"] and not accepted["painting_completed"]
    assert accepted["request_id"] == "start-1" and lifetime.connection.background_active.is_set()
    assert env.manager.tick() and env.manager.active.work is None and not env.marks
    lifetime.acknowledge(True)
    lifetime.deadline = 0  # The completed RPC is not the job's own deadline.
    result = finish(env)
    assert result["state"] == "SUCCEEDED" and result["undo_boundary_finalized"]
    assert env.images.get("Painted") is not None and len(env.marks) == 2
    assert not lifetime.connection.background_active.is_set()
    assert env.manager.history[0].prepared == {} and env.manager.history[0].work is None


@pytest.mark.parametrize("failure", ["disconnect", "reject", "handoff", "deadline", "cancel", "emergency"])
def test_stopped_precommit_jobs_release_private_work_without_any_scene_image(jobs, failure):
    env = jobs
    lease = importlib.import_module(env.module.RequestLifetime.__module__)
    lifetime = lease.RequestLifetime(lease.ConnectionLifetime(), float("inf"))
    context = env.context()
    context.request_lifecycle = lifetime
    start(env, context=context)
    if failure == "disconnect":
        lifetime.connection.disconnected.set()
    elif failure == "reject":
        lifetime.acknowledge(False)
    elif failure == "handoff":
        lifetime.deadline = 0
    elif failure == "deadline":
        env.manager.active.deadline = 0
    elif failure == "cancel":
        env.manager.cancel(env.manager.active.job_id)
    else:
        env.context().state.set_emergency_stopped(True)
    result = finish(env)
    assert result["state"] == "CANCELLED" and not result["execution_started"]
    assert result["error"]["context"]["possible_mutation"] is False
    assert len(env.images) == 1 and not env.marks


def test_pause_holds_work_without_losing_owner_and_explicit_cancel_is_available(jobs):
    env = jobs
    start(env)
    env.context().state.set_paused(True)
    assert env.manager.tick() and env.manager.active.state == "PAUSED"
    assert not env.marks and env.manager.active.work is None
    env.manager.cancel(env.manager.active.job_id)
    result = finish(env)
    assert result["state"] == "CANCELLED" and len(env.images) == 1


def test_pause_can_resume_and_deadline_keeps_running_while_paused(jobs):
    env = jobs
    start(env)
    env.context().state.set_paused(True)
    env.manager.tick()
    env.context().state.set_paused(False)
    assert finish(env)["state"] == "SUCCEEDED"
    start(env, "Expired")
    env.context().state.set_paused(True)
    env.manager.active.deadline = 0
    assert finish(env)["state"] == "CANCELLED"
    assert env.images.get("Expired") is None


@pytest.mark.parametrize("change", ["pixels", "metadata", "identity", "mode", "name", "permission", "toolset", "animation"])
def test_final_commit_rejects_changed_source_context_or_live_authority(jobs, change):
    env = jobs
    start(env)
    if change == "pixels":
        env.images[0].pixels.values[0] = .9
    elif change == "metadata":
        env.images[0].alpha_mode = "PREMUL"
    elif change == "identity":
        env.images[0] = Image("Original")
    elif change == "mode":
        env.bpy.context.mode = "EDIT_MESH"
    elif change == "name":
        env.images.append(Image("Painted"))
    elif change == "permission":
        env.grants["EDIT_MATERIALS"] = False
    elif change == "animation":
        env.images[0].animation_data = NS(action=object(), drivers=[], nla_tracks=[])
    else:
        env.context().registry.disable_toolset("materials")
    result = finish(env)
    assert result["state"] == "FAILED" and not result["execution_started"] and not env.marks
    assert len(env.images) == (2 if change == "name" else 1)


def test_checkpoint_is_at_commit_after_interleaved_edits_and_revalidation(jobs):
    env = jobs
    start(env)
    assert not env.marks
    # If checkpoint setup changes the source, no publication is allowed afterward.
    def checkpoint(name):
        env.marks.append(("before", name))
        env.images[0].pixels.values[0] = .8
        return True
    env.checkpoints.before_modification = checkpoint
    result = finish(env)
    assert result["state"] == "FAILED" and not result["execution_started"]
    assert result["undo_boundary_finalized"] and len(env.images) == 1


@pytest.mark.parametrize("stage", ["before", "after"])
def test_missing_native_boundary_or_finalization_never_claims_success(jobs, stage):
    env = jobs
    setattr(env.checkpoints, stage + "_modification", lambda _label: False)
    start(env)
    result = finish(env)
    assert result["state"] == "FAILED" and result["result"] is None
    assert bool(env.images.get("Painted")) is (stage == "after")
    assert result["error"]["context"]["possible_mutation"] is (stage == "after")


def test_late_cancel_and_denied_cleanup_retain_truthful_mutation_and_recovery(jobs, monkeypatch):
    env = jobs
    start(env)
    original = Image.update
    def update(image):
        original(image)
        if image.name == "Painted":
            env.grants["DELETE_OBJECTS"] = False
            env.manager.cancel_all("stop during native publication")
    monkeypatch.setattr(Image, "update", update)
    result = finish(env)
    evidence = result["error"]["context"]
    assert result["state"] == "CANCELLED" and result["execution_started"]
    assert result["undo_boundary_finalized"] and evidence["cleanup_permission_denied"]
    assert evidence["possible_mutation"] and not evidence["rollback_verified"]
    assert env.images.get("Painted") is not None and env.manager.active is None
    assert len(env.manager.history) == 1


def test_pause_during_native_publication_is_observed_before_further_mutation_or_success(jobs, monkeypatch):
    env = jobs
    start(env)
    original = Image.update
    def update(image):
        original(image)
        if image.name == "Painted":
            env.grants["DELETE_OBJECTS"] = False
            env.context().state.set_paused(True)
    monkeypatch.setattr(Image, "update", update)
    result = finish(env)
    assert result["state"] == "FAILED" and result["result"] is None
    assert result["error"]["code"] == "AGENT_PAUSED"
    assert result["error"]["context"]["possible_mutation"]
    assert result["undo_boundary_finalized"] and env.images.get("Painted") is not None


def test_single_active_limit_bounded_retention_and_main_thread_control(jobs):
    env = jobs
    start(env)
    with pytest.raises(env.module.BridgeError, match="already active"):
        start(env, "Another")
    errors = []
    def foreign_thread():
        try:
            env.manager.tick()
        except env.module.BridgeError as error:
            errors.append(error.code)
    worker = threading.Thread(target=foreign_thread)
    worker.start()
    worker.join()
    assert errors == ["BLENDER_CONTEXT_ERROR"]
    env.manager.cancel_all("test cleanup")
    for _ in range(34):
        start(env)
        env.manager.cancel_all("test cancellation")
    assert len(env.manager.history) == 32 and env.manager.list(2)["truncated"]
    assert all(not job.prepared and job.work is None for job in env.manager.history)


def test_reentrant_lifecycle_cancel_during_generator_releases_only_after_unwind(jobs, monkeypatch):
    env = jobs
    original = env.paint.brush.paint_steps
    def reentrant(*args, **kwargs):
        env.manager.cancel_all("reentrant CPU safe-point stop")
        assert env.manager.active is not None and env.manager.active.prepared
        yield from original(*args, **kwargs)
    monkeypatch.setattr(env.paint.brush, "paint_steps", reentrant)
    start(env)
    result = finish(env)
    assert result["state"] == "CANCELLED" and len(env.manager.history) == 1
    assert not env.manager.active and not env.manager.history[0].prepared and len(env.images) == 1


def test_unguarded_control_status_never_exposes_private_result_pixels_or_file_evidence(jobs):
    env = jobs
    accepted = start(env)
    assert "result" not in env.manager.status()["active"]
    result = finish(env)
    assert result["result"] is not None
    assert "result" not in env.manager.status()["last_terminal"]
    cancelled = env.manager.cancel(accepted["job_id"])
    assert "job" not in cancelled and "result" not in cancelled and not cancelled["cancel_requested"]


def test_cooperative_generator_has_identical_pixels_to_sync_kernel_and_yields_bounded_progress(jobs):
    kernel = jobs.paint.brush
    values = array("f", [0.2, 0.4, 0.6, 1.]) * (64 * 64)
    strokes, _ = kernel.prepare([stroke(radius_pixels=32.)], 64, 64, "COLOR")
    expected = kernel.paint(values, 64, 64, strokes, "COLOR")
    generator = kernel.paint_steps(values, 64, 64, strokes, "COLOR")
    progress = []
    while True:
        try:
            progress.append(next(generator))
        except StopIteration as result:
            assert result.value == expected
            break
    assert len(progress) > 20 and all(0 <= item["completed"] <= item["total"] for item in progress)


@pytest.mark.parametrize("limit", [True, 0, 301, float("nan"), "60", 10**400])
def test_job_deadline_is_typed_and_bounded_before_image_read(jobs, limit):
    with pytest.raises(jobs.module.BridgeError):
        jobs.manager.start(jobs.context(), {}, limit)


def test_frozen_strokes_and_separate_inspection_consent(jobs):
    env = jobs
    env.grants["INSPECT_SCENE"] = False
    strokes = [stroke()]
    expected = env.paint.brush.paint(env.images[0].pixels.values, 4, 4,
        env.paint.brush.prepare(strokes, 4, 4, "COLOR")[0], "COLOR")[0]
    accepted = env.manager.start(env.context(), {"image_name": "Original", "new_name": "Painted", "strokes": strokes}, 60.)
    strokes[0]["color"][0] = 0.
    strokes[0]["points"][0][0] = 0.
    with pytest.raises(env.module.BridgeError, match="permission"):
        env.context().registry.dispatch("jobs.inspect", {"job_id": accepted["job_id"]}, env.context())
    assert finish(env)["state"] == "SUCCEEDED"
    assert env.images.get("Painted").pixels.values == expected


def test_polling_does_not_evict_operation_history_and_async_jobs_cannot_nest_in_batches(jobs):
    env = jobs
    executor_module = importlib.import_module(env.module.__package__ + ".executor")
    queue_module = importlib.import_module(env.module.__package__ + ".command_queue")
    batch = importlib.import_module(env.module.__package__ + ".tools.batch")
    context = env.context()
    executor = executor_module.MainThreadExecutor(command_queue=queue_module.CommandQueue(), registry=context.registry,
        state=context.state, permissions=context.permissions, checkpoints=context.checkpoints, jobs=env.manager)
    accepted = executor.dispatch("image.paint_job_start", {"image_name": "Original", "new_name": "Painted", "strokes": [stroke()]})
    assert "not yet committed" in context.state.history(1)[0]["description"]
    for _ in range(60):
        executor.dispatch("jobs.inspect", {"job_id": accepted["job_id"]})
        executor.dispatch("jobs.list", {"limit": 2})
    assert len(context.state.history(50)) == 1 and not env.marks
    assert not batch.is_batch_supported(context.registry.get("image.paint_job_start"))
    with pytest.raises(env.module.BridgeError, match="batch-supported"):
        batch.batch_plan(context, {"steps": [{"method": "image.paint_job_start", "params": {}}]})


@pytest.mark.parametrize("stage", ["output", "coverage"])
def test_controlled_private_allocation_failure_does_not_allocate_scene_image(jobs, monkeypatch, stage):
    env = jobs
    start(env)
    original = env.paint.brush.array
    def allocate(kind, *args):
        if kind == ("f" if stage == "output" else "d"):
            raise MemoryError("controlled owned-buffer allocation fault, not host pressure")
        return original(kind, *args)
    monkeypatch.setattr(env.paint.brush, "array", allocate)
    result = finish(env)
    assert result["state"] == "FAILED" and result["error"]["code"] == "OPERATION_FAILED"
    assert not result["execution_started"] and result["error"]["context"]["possible_mutation"] is False
    assert len(env.images) == 1 and not env.manager.history[0].prepared and env.manager.history[0].work is None


def test_surface_job_routes_large_profile_and_releases_source_after_precommit_cancel(jobs, monkeypatch):
    from test_image_surface_paint import parameters, setup_fake

    env = jobs
    surface = importlib.import_module(env.module.__package__ + ".tools.image_surface_paint")
    setup_fake(surface, env.bpy, monkeypatch)
    surface.register_tools(env.context().registry)
    env.images[0].size = [1025, 1024]
    env.images[0].pixels.values = array("f", [.2, .4, .6, 1.])*(1025*1024)
    accepted = env.manager.start_surface_paint(env.context(), parameters(), 300.)
    assert accepted["workload"]["image_size"] == [1025, 1024]
    assert accepted["workload"]["large_image_requires_job"]
    assert accepted["workload"]["maximum_source_or_stencil_pixels"] == 16_777_216
    assert accepted["workload"]["maximum_candidate_pixel_tests"] == 33_554_432
    assert accepted["workload"]["baseline_copy_bytes"] == 0
    assert not accepted["projection_work_started"] and not env.marks
    env.manager.cancel(accepted["job_id"])
    done = finish(env)
    assert done["state"] == "CANCELLED" and not done["execution_started"]
    assert env.manager.history[0].prepared == {} and env.manager.history[0].driver is None
    assert env.images.get("Projected") is None


@pytest.mark.parametrize("stage", ["output", "owners"])
def test_surface_private_allocation_failure_keeps_scene_and_terminal_evidence_truthful(jobs, monkeypatch, stage):
    from test_image_surface_paint import parameters, setup_fake

    env = jobs
    surface = importlib.import_module(env.module.__package__ + ".tools.image_surface_paint")
    setup_fake(surface, env.bpy, monkeypatch)
    surface.register_tools(env.context().registry)
    env.manager.start_surface_paint(env.context(), parameters(), 60.)
    module, kind = (env.paint.brush, "f") if stage == "output" else (surface, "i")
    original = module.array

    def allocate(code, *args):
        if code == kind:
            raise MemoryError("controlled private surface buffer failure; no host pressure")
        return original(code, *args)

    monkeypatch.setattr(module, "array", allocate)
    done = finish(env)
    assert done["state"] == "FAILED" and done["error"]["code"] == "OPERATION_FAILED"
    assert not done["execution_started"] and not done["error"]["context"]["possible_mutation"]
    assert env.images.get("Projected") is None and not env.marks
    assert not env.manager.history[0].prepared and env.manager.history[0].driver is None


@pytest.mark.parametrize("loss", ["cancel", "emergency", "pause"])
def test_surface_late_publication_loss_retains_image_and_finalized_boundary(jobs, monkeypatch, loss):
    from test_image_surface_paint import parameters, setup_fake

    env = jobs
    surface = importlib.import_module(env.module.__package__ + ".tools.image_surface_paint")
    setup_fake(surface, env.bpy, monkeypatch)
    surface.register_tools(env.context().registry)
    env.grants["DELETE_OBJECTS"] = False
    update = Image.update

    def lose_after_update(image):
        update(image)
        if image.name != "Projected":
            return
        if loss == "cancel":
            env.manager.cancel_all("owned late surface cancellation")
        elif loss == "emergency":
            env.context().state.set_emergency_stopped(True)
        else:
            env.context().state.set_paused(True)

    monkeypatch.setattr(Image, "update", lose_after_update)
    env.manager.start_surface_paint(env.context(), parameters(), 60.)
    done = finish(env)
    assert done["state"] == ("FAILED" if loss == "pause" else "CANCELLED")
    assert done["execution_started"] and done["undo_boundary_finalized"]
    assert done["error"]["context"]["possible_mutation"] and done["result"] is None
    assert env.images.get("Projected") is not None and env.manager.history[0].prepared == {}
