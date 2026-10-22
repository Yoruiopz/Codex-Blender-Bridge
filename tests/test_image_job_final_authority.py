from __future__ import annotations

import pytest
from test_image_delivery_jobs import delivery, start_export  # noqa: F401
from test_image_paint import Image, paint_tools  # noqa: F401
from test_image_surface_paint import parameters, setup_fake, surface  # noqa: F401
from test_paint_jobs import finish, jobs, start  # noqa: F401


def arm_provider(context, gate, mutate, *, arm=lambda: True, repetitions=1):
    """Inject after the final grant without assuming provider batching."""
    manager, measured = context.permissions, []
    source = manager._source
    def measure():
        measured.append(True)
        return source()
    manager._source = measure
    try:
        gate()
    finally:
        manager._source = source
    calls, injected = [], []
    def provider():
        grants = source()
        if arm():
            calls.append(True)
            if len(calls) == len(measured)*repetitions:
                mutate()
                injected.append(True)
        return grants
    manager._source = provider
    return injected, lambda: setattr(manager, "_source", source)


def mutation(env, fault):
    if fault == "cancel":
        env.manager.active.cancel_reason = "Provider-triggered cancellation"
    else:
        env.context().registry.disable_toolset("materials")


def assert_stopped(value, fault):
    assert value["state"] == ("CANCELLED" if fault == "cancel" else "FAILED"), value
    assert value["error"]["code"] == ("TIMEOUT" if fault == "cancel" else "TOOLSET_DISABLED"), value


@pytest.mark.parametrize("fault", ["cancel", "toolset"])
def test_paint_last_grant_blocks_next_allocated_output_write(request, monkeypatch, fault):
    env = request.getfixturevalue("jobs")
    env.grants["DELETE_OBJECTS"] = False
    start(env)
    original_new, probes = env.paint._new, []
    def new(context, *args, **kwargs):
        injected, restore = arm_provider(context, lambda: env.paint._require(context, modifying=True),
            lambda: mutation(env, fault), arm=lambda: env.images.get("Painted") is not None)
        probes.append(injected)
        try:
            return original_new(context, *args, **kwargs)
        finally:
            restore()
    monkeypatch.setattr(env.paint, "_new", new)
    result = finish(env)
    assert_stopped(result, fault)
    assert probes == [[True]]
    output = env.images.get("Painted")
    assert output is not None and output.alpha_mode == "STRAIGHT" and not output.is_dirty
    assert list(output.pixels.values) == pytest.approx([.2, .4, .6, 1.]*16)


@pytest.mark.parametrize("fault", ["cancel", "toolset"])
def test_surface_authority_last_grant_blocks_next_allocated_output_write(request, monkeypatch, fault):
    env = request.getfixturevalue("jobs")
    domain = request.getfixturevalue("surface")
    setup_fake(domain, env.bpy, monkeypatch)
    domain.register_tools(env.context().registry)
    env.grants["DELETE_OBJECTS"] = False
    env.manager.start_surface_paint(env.context(), parameters(), 60.)
    original_guard, probes, restores = domain._owned_output_guard, [], []
    def build_guard(context, prepared, job=None):
        guard = original_guard(context, prepared, job)
        def checked(image):
            if not probes:
                injected, restore = arm_provider(context, lambda: domain._authority(context, job),
                    lambda: mutation(env, fault))
                probes.append(injected)
                restores.append(restore)
            return guard(image)
        return checked
    monkeypatch.setattr(domain, "_owned_output_guard", build_guard)
    try:
        result = finish(env)
    finally:
        for restore in restores:
            restore()
    assert_stopped(result, fault)
    assert probes == [[True]]
    output = env.images.get("Projected")
    assert output is not None and output.alpha_mode == "STRAIGHT" and not output.is_dirty
    assert list(output.pixels.values) == pytest.approx([.2, .4, .6, 1.]*16)


@pytest.mark.parametrize("fault", ["cancel", "toolset"])
@pytest.mark.parametrize("boundary", ["driver_check", "staging_publication"])
def test_export_final_grant_blocks_actual_file_publication(request, monkeypatch, boundary, fault):
    env = request.getfixturevalue("delivery")
    start_export(env)
    job, probes, restores = env.manager.active, [], []
    driver = job.driver
    if boundary == "driver_check":
        original = driver._check
        def check(context):
            if driver.staging is not None and driver.staging.sealed and not probes:
                injected, restore = arm_provider(context, lambda: original(context), lambda: mutation(env, fault))
                probes.append(injected)
                restores.append(restore)
            return original(context)
        monkeypatch.setattr(driver, "_check", check)
    else:
        cls = env.delivery.TextureStaging
        original = cls.publish
        def publish(resource):
            injected, restore = arm_provider(resource.context, resource._authorize,
                lambda: mutation(env, fault), repetitions=2)
            probes.append(injected)
            try:
                return original(resource)
            finally:
                restore()
        monkeypatch.setattr(cls, "publish", publish)
    try:
        result = finish(env)
    finally:
        for restore in restores:
            restore()
    assert_stopped(result, fault)
    assert probes == [[True]] and not env.path.exists()
    assert result["external_effects"]["file_published"] is False
    assert result["external_effects"]["publication_attempted"] is False
    assert env.images.get("Reimported") is None
