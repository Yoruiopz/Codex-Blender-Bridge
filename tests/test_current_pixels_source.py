"""Actual runtime/request origins with explicitly modeled native graph reads.

No model result qualifies a native getter, complete graph or public lifecycle.
The permission provider is the unchanged Runtime provider over modeled prefs.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import time
from array import array
from types import ModuleType
from types import SimpleNamespace as NS

import pytest
from test_current_pixels_graph import make_identity_model
from test_image_paint import Image

DOMAIN = '''
def pack_preview(context, params):
    origin = context.checkpoint_admission.callback.enter()
    flags["handler"] += 1
    return origin.cache_preview(origin.capture, origin.file_plan, {"model": True})
def pack_start(context, params):
    origin = context.checkpoint_admission.callback.enter()
    flags["handler"] += 1
    flags["start_data"] = origin.preview_data()
    flags["origin"] = origin
    if flags.get("job_model"):
        return context.jobs.start_prepared_driver(context, params, params.get("time_limit_seconds", 60.), prepare=prepare_current_pixels,
            required_permissions=REQUIRED,
            callback_control=origin.callbacks)
    return {"accepted": False, "model_source_only": True}
def recovery_preview(context, params):
    return pack_preview(context, params)
def restore_start(context, params):
    return pack_start(context, params)
def prepare_current_pixels(context, params):
    return {"source": image, "source_name": image.name, "name": "Snapshot", "requires_external_files": True,
        "method": METHODS[1], "kind": "current_pixels_lifecycle", "driver_type": CurrentPixelsDriver,
        "origin": context.checkpoint_admission.callback, "workload": {"source_model_only": True}}
class CurrentPixelsDriver:
    def __init__(self, prepared):
        self.origin = prepared["origin"]
    def steps(self, context, job, commit):
        self.origin.authorize(context)
        self.origin.refresh_capture(context)
        flags["worker_context"] = context
        flags["steps"] = flags.get("steps", 0) + 1
        yield {"phase": "source_model_only", "completed": 0, "total": 1}
        return {"source_model_only": True}
    def cleanup(self, context, job, *, success):
        assert context is None
        flags["cleanup"] = flags.get("cleanup", 0) + 1
        return {"publication_attempted": False, "file_published": False}
    def evidence(self):
        return {"publication_attempted": False, "file_published": False}
    def recovery_evidence(self):
        return {"mode": "LOADED_BUFFER", "possible_mutation": False}
'''


@pytest.fixture
def source_env(addon_package, monkeypatch, tmp_path):
    source = importlib.import_module(addon_package + ".current_pixels_source")
    graph = importlib.import_module(addon_package + ".current_pixels_graph")
    runtime_module = importlib.import_module(addon_package + ".runtime")
    state_module = importlib.import_module(addon_package + ".state")
    permissions = importlib.import_module(addon_package + ".permissions")
    utils = importlib.import_module(addon_package + ".utils")
    preference_module = importlib.import_module(addon_package + ".preferences")
    native = make_identity_model(graph, monkeypatch, addon_package)
    native.original.marker = 0
    flags = {"handler": 0, "grants": 0, "captures": 0, "writes": 0, "foreign": 0, "hook": None}

    class Preferences:
        def __getattribute__(self, name):
            if name == "allow_inspect_scene":
                flags["grants"] += 1
                hook = flags["hook"]
                if hook is not None:
                    hook()
            return object.__getattribute__(self, name)

    prefs = Preferences()
    for name in permissions.PREFERENCE_PROPERTIES.values():
        setattr(prefs, name, True)
    prefs.texture_directory = str(tmp_path)
    native.bpy.context = NS(mode="OBJECT", preferences=NS(addons={addon_package: NS(preferences=prefs)}))
    monkeypatch.setitem(sys.modules, "bpy", native.bpy)
    monkeypatch.setattr(utils, "bpy", native.bpy)
    monkeypatch.setattr(preference_module, "bpy", native.bpy)
    monkeypatch.setattr(state_module, "_STATE", state_module.BridgeState())
    runtime = runtime_module.BridgeRuntime()
    runtime._registered = True
    monkeypatch.setattr(runtime_module, "_RUNTIME", runtime)
    runtime.registry.enable_toolset("materials")
    # The native graph reader is modeled here; catalog/getter tests are separate.
    # There is no production constructor flag or RPC bypass for this substitution.
    def capture(_bpy, image_name, snapshot_name, affected_materials, *, check,
                available_memory_bytes, available_disk_bytes, lifecycle_record=None):
        check()
        if flags.get("capture_hook") is not None:
            flags["capture_hook"]()
            check()
        graph.validate_resource_facts(2, 2, available_memory_bytes, available_disk_bytes)
        flags["captures"] += 1
        digest = hashlib.sha256(str(native.original.marker).encode()).hexdigest()
        payload = graph.PayloadCapture(array("f", [1.] * 16), b"old", b"current", digest, "b" * 64, "c" * 64, "d" * 64)
        return graph.GraphCapture(native.original, native.helper, (native.material,), (), "a" * 64,
            "e" * 64, digest, digest, ({"kind": "Image", "name": "Original", "pointer": "a", "session_uid": "10", "content_sha256": "f" * 64},),
            {"name": "Original", "has_data": True}, {"name": "Snapshot", "has_data": True},
            {"vertices": 0}, {"available_memory_bytes": available_memory_bytes}, (), 100, payload)
    monkeypatch.setattr(graph, "capture_graph", capture)
    original_identity_witness = graph.identity_witness
    def checked_identity_witness(_bpy, image_name, snapshot_name, affected_materials, *, check=None):
        assert check is not None, "The source must provide a real gate for native identity queries"
        check()
        if flags.get("identity_hook") is not None:
            flags["identity_hook"]()
            check()
        return original_identity_witness(_bpy, image_name, snapshot_name, affected_materials, check=check)
    monkeypatch.setattr(graph, "identity_witness", checked_identity_witness)
    domain = ModuleType(addon_package + ".tools.image_current_pixels")
    domain.flags = flags
    domain.image, domain.REQUIRED, domain.METHODS = Image("ModeledJobSource"), source.REQUIRED, source.METHODS
    exec(DOMAIN, vars(domain))
    monkeypatch.setitem(sys.modules, domain.__name__, domain)
    for method in source.METHODS:
        start = method in source.current_pixels_contract.METHOD_MODES
        runtime.registry.register(method, vars(domain)[source.HANDLERS[method]], toolset="materials", modifies=start,
            permissions=source.REQUIRED, automatic_checkpoint=False, batchable=False, record_history=True,
            checkpoint_owns_finalization=start, protected_scope_resolver=source.protected_scope,
            checkpoint_admission_factory=source.admission_factory(method), checkpoint_parameter_dependencies=source.initial_dependencies)
    original_registration = source._REGISTRATION
    source.bind_registry(runtime.registry)
    yield NS(source=source, graph=graph, runtime=runtime, runtime_module=runtime_module, native=native,
             prefs=prefs, flags=flags, domain=domain, folder=tmp_path)
    source._PLANS.clear()
    source._REGISTRATION = original_registration


def params(env, prefix="texture"):
    return {"image_name": "Original", "snapshot_name": "Snapshot", "affected_materials": ["Material"],
            "backup_directory": str(env.folder), "backup_prefix": prefix}


def preview(env, prefix="texture"):
    return env.runtime.dispatch(env.source.METHODS[0], params(env, prefix))


def start(env, proof, *, prefix="texture"):
    return env.runtime.dispatch(env.source.METHODS[1], {**params(env, prefix),
        "expected_target_fingerprint": proof["fingerprint"], "confirm_replace_packed_bytes": True,
        "confirm_discard_current_buffer": True})


def test_pure_classifier_has_no_provider_native_or_store_initialization(source_env):
    env = source_env
    assert "_artist_task_plans" not in vars(env.runtime.state)
    before, native = dict(env.flags), list(env.native.calls)
    assert env.source.initial_dependencies(env.runtime.registry, {}) == env.source._REGISTRATION.specs
    assert env.flags == before and env.native.calls == native
    assert "_artist_task_plans" not in vars(env.runtime.state)


def test_enforced_scope_refuses_all_four_before_factory_provider_or_native(source_env):
    env = source_env
    store = env.source.get_task_plans(env.runtime.state)
    protected = {"user": "retained scope"}
    store.protection = protected
    before, native = dict(env.flags), list(env.native.calls)
    for method in env.source.METHODS:
        with pytest.raises(env.source.BridgeError) as failure:
            env.runtime.registry.get(method).checkpoint_parameter_dependencies(env.runtime.registry, {})
        assert failure.value.code == "NOT_IMPLEMENTED" and failure.value.context["protected_scope_enforced"]
    assert store.protection is protected and env.flags == before and env.native.calls == native


def test_authorized_initial_preview_is_plain_after_grants_and_start_binds_same_full_baseline(source_env):
    env = source_env
    provider = env.runtime.permissions._source
    proof = preview(env)
    assert proof["baseline_established_after_authorization"] is True
    assert proof["first_authorization_pixel_only_change_detection"] is False
    assert not proof["preview_mutation_performed"] and env.flags["captures"] > 0
    entry = env.source._PLANS[proof["fingerprint"]]
    data = json.loads(entry.raw)
    assert "resource_facts" not in data["graph"] and "payloads" not in data["graph"]
    assert len(entry.raw) <= 65536 and env.runtime.permissions._source is provider
    assert start(env, proof)["model_source_only"]
    assert env.flags["writes"] == 0 and list(env.folder.iterdir()) == []


@pytest.mark.parametrize("permission", ["allow_inspect_scene", "allow_edit_materials", "allow_external_files", "allow_save_project"])
def test_each_actual_permission_denial_prevents_full_capture_and_file_effects(source_env, permission):
    env = source_env
    setattr(env.prefs, permission, False)
    with pytest.raises(env.source.BridgeError) as failure:
        preview(env)
    assert failure.value.code == "PERMISSION_DENIED"
    assert env.flags["captures"] == env.flags["handler"] == env.flags["writes"] == 0
    assert list(env.folder.iterdir()) == [] and not env.source._PLANS


@pytest.mark.parametrize("change", ["pixel", "identity", "context", "root", "generation"])
def test_start_never_adopts_changed_preview_source_or_scope(source_env, change):
    env = source_env
    proof = preview(env)
    if change == "pixel":
        env.native.original.marker = 7
    elif change == "identity":
        env.native.original.session_uid += 1
    elif change == "context":
        env.native.bpy.context.mode = "EDIT_MESH"
    elif change == "root":
        env.prefs.texture_directory = str(env.folder / "different")
    else:
        env.source.get_task_plans(env.runtime.state).invalidate_handles()
    before = env.flags["handler"]
    with pytest.raises(env.source.BridgeError):
        start(env, proof)
    assert env.flags["handler"] == before and env.flags["writes"] == 0
    assert list(env.folder.iterdir()) == []


def test_initial_preview_explicitly_allows_pixel_only_change_before_first_full_baseline(source_env):
    env = source_env
    def change():
        if env.flags["captures"] == 0:
            env.native.original.marker = 12
    env.flags["hook"] = change
    proof = preview(env)
    observed = json.loads(env.source._PLANS[proof["fingerprint"]].raw)["graph"]["full_native_prefix_sha256"]
    assert observed == hashlib.sha256(b"12").hexdigest()
    assert proof["first_authorization_pixel_only_change_detection"] is False


def test_pixel_change_after_established_preview_capture_is_refused_without_rebase(source_env):
    env = source_env
    def change():
        if env.flags["captures"]:
            env.native.original.marker = 31
    env.flags["hook"] = change
    with pytest.raises(env.source.BridgeError) as failure:
        preview(env)
    assert failure.value.context["reason"] == "FULL_SOURCE_REBASE_REFUSED"
    assert env.flags["writes"] == 0


@pytest.mark.parametrize("change", ["identity", "mode", "store", "factory"])
def test_first_provider_identity_context_and_service_drift_cannot_become_baseline(source_env, change):
    env = source_env
    def mutate():
        env.flags["hook"] = None
        if change == "identity":
            env.native.original.session_uid += 1
        elif change == "mode":
            env.native.bpy.context.mode = "EDIT_MESH"
        elif change == "store":
            env.source.get_task_plans(env.runtime.state)
        else:
            def foreign():
                env.flags["foreign"] += 1
                raise AssertionError("Foreign context factory")
            env.runtime.jobs.context_factory = foreign
    env.flags["hook"] = mutate
    with pytest.raises(env.source.BridgeError):
        preview(env)
    assert env.flags["captures"] == env.flags["writes"] == env.flags["foreign"] == 0


def queued(env, method, parameters, connection, identifier, *, queue_seconds=60.):
    life = env.source.RequestLifetime(connection, deadline=time.monotonic() + 60.)
    request = env.source.protocol.Request(identifier, method, parameters, _lifecycle=life)
    item = env.source.command_queue.QueuedRequest(request, deadline=time.monotonic() + queue_seconds)
    assert item.try_start()
    response = env.runtime.executor.execute_request(request, check_cancelled=item.check_active)
    item.resolve(response)
    life.acknowledge(response.ok)
    return response, item, life


def queued_preview(env, connection, identifier="preview-A", *, queue_seconds=60.):
    response, item, life = queued(env, env.source.METHODS[0], params(env), connection, identifier, queue_seconds=queue_seconds)
    assert response.ok, response.error
    return response.result, item, life


def start_parameters(env, proof):
    return {**params(env), "expected_target_fingerprint": proof["fingerprint"],
            "confirm_replace_packed_bytes": True, "confirm_discard_current_buffer": True}


def finish_model(env):
    for _ in range(8):
        if not env.runtime.jobs.tick():
            break
    assert env.runtime.jobs.active is None
    return env.runtime.jobs.history[0]


@pytest.mark.timeout(30)
def test_genuine_queued_preview_a_start_b_and_worker_retain_connection_not_old_rpc_deadline(source_env):
    env = source_env
    owner = env.source.ConnectionLifetime()
    proof, first, _first_life = queued_preview(env, owner, queue_seconds=10.)
    env.flags["job_model"] = True
    response, second, life = queued(env, env.source.METHODS[1], start_parameters(env, proof), owner, "start-B", queue_seconds=10.)
    assert response.ok, response.error
    assert response.result["accepted"] and first is not second
    assert first.request is not second.request and env.runtime.jobs.active.lifetime is life
    # Start delivery transfers authority to the genuine job lifetime. A later
    # reader/worker must not call the completed request's expired check_active.
    env.source.threading.Event().wait(max(0., max(first.deadline, second.deadline) - time.monotonic()) + .01)
    assert time.monotonic() >= max(first.deadline, second.deadline)
    record = finish_model(env)
    assert record.state == "SUCCEEDED", json.dumps(record.error, sort_keys=True)
    assert env.flags["steps"] == 1 and env.flags["cleanup"] == 1
    assert not owner.background_active.is_set() and env.flags["writes"] == 0
    assert list(env.folder.iterdir()) == [] and env.flags["worker_context"].check_final_request is None


@pytest.mark.parametrize("reason", ["foreign_connection", "disconnect", "eviction", "expiry"])
def test_queued_preview_ownership_and_retention_fail_before_new_capture(source_env, reason):
    env = source_env
    owner = env.source.ConnectionLifetime()
    proof, _request, _life = queued_preview(env, owner)
    if reason == "foreign_connection":
        owner = env.source.ConnectionLifetime()
    elif reason == "disconnect":
        owner.disconnected.set()
    elif reason == "eviction":
        env.source._PLANS.clear()
    else:
        entry = env.source._PLANS[proof["fingerprint"]]
        object.__setattr__(entry, "expires", time.monotonic() - 1.)
    before = env.flags["grants"], env.flags["handler"], env.flags["captures"]
    response, _request, _life = queued(env, env.source.METHODS[1], start_parameters(env, proof), owner, "start-refused")
    assert not response.ok and env.flags["handler"] == before[1] and env.flags["captures"] == before[2]
    # The registry deliberately resolves the canonical provider once even when
    # admission has already failed, preserving permission-denial precedence.
    assert env.flags["grants"] <= before[0] + 1
    assert env.flags["writes"] == 0 and list(env.folder.iterdir()) == []


@pytest.mark.parametrize("reason", ["cancel", "disconnect", "revoke", "pause"])
def test_accepted_real_worker_stops_without_file_effects_at_next_safe_point(source_env, reason):
    env = source_env
    owner = env.source.ConnectionLifetime()
    proof, _request, _life = queued_preview(env, owner)
    env.flags["job_model"] = True
    response, _request, _life = queued(env, env.source.METHODS[1], start_parameters(env, proof), owner, "start-worker")
    assert response.ok, response.error
    if reason == "cancel":
        env.runtime.jobs.cancel_all("model reader cancellation")
    elif reason == "disconnect":
        owner.disconnected.set()
    elif reason == "revoke":
        env.prefs.allow_save_project = False
    else:
        env.runtime.state.paused = True
    if reason == "pause":
        assert env.runtime.jobs.tick() and env.flags.get("steps", 0) == 0
        env.runtime.state.paused = False
        env.runtime.jobs.cancel_all("stop after pause proof")
    record = finish_model(env)
    assert record.state in {"FAILED", "CANCELLED"} and env.flags.get("steps", 0) == 0
    assert env.flags["writes"] == 0 and list(env.folder.iterdir()) == []


@pytest.mark.parametrize("slot", ["graph", "driver_descriptor", "schema", "source_check"])
def test_current_provider_cannot_replace_tracked_source_before_first_full_read(source_env, monkeypatch, slot):
    env = source_env
    class Foreign:
        def __get__(self, _instance, _owner):
            env.flags["foreign"] += 1
            raise AssertionError("Foreign descriptor lookup")

    def replace():
        env.flags["hook"] = None
        if slot == "graph":
            def foreign(*_args, **_kwargs):
                env.flags["foreign"] += 1
                raise AssertionError("Foreign graph read")
            monkeypatch.setattr(env.graph, "capture_graph", foreign)
        elif slot == "driver_descriptor":
            monkeypatch.setattr(env.domain.CurrentPixelsDriver, "evidence", Foreign())
        elif slot == "source_check":
            def foreign_check(_origin):
                env.flags["foreign"] += 1
                raise AssertionError("Foreign source check")
            monkeypatch.setattr(env.source.CurrentPixelsOrigin, "check_job_callbacks", foreign_check)
        else:
            monkeypatch.setattr(env.source.current_pixels_contract, "MAX_PAYLOAD_BYTES", 2)
    env.flags["hook"] = replace
    with pytest.raises(env.source.BridgeError):
        preview(env)
    assert env.flags["captures"] == env.flags["foreign"] == env.flags["writes"] == 0


def test_start_native_identity_is_bound_before_providers_even_if_modeled_full_reader_is_unchanged(source_env):
    env = source_env
    proof = preview(env)
    env.native.original.session_uid += 1
    before = env.flags["grants"], env.flags["captures"], env.flags["handler"]
    with pytest.raises(env.source.BridgeError) as failure:
        start(env, proof)
    assert failure.value.context["reason"] == "CACHED_NATIVE_IDENTITY_WITNESS_CHANGED"
    assert (env.flags["captures"], env.flags["handler"]) == before[1:]
    assert env.flags["grants"] == before[0] + 1  # Existing deferred-denial precedence.


def test_existing_backup_artifact_refuses_before_full_capture_and_never_overwrites(source_env):
    env = source_env
    old = env.folder / ("texture" + env.source.current_pixels_files.SUFFIXES["current"])
    old.write_bytes(b"retained preexisting file")
    with pytest.raises(env.source.BridgeError):
        preview(env)
    assert env.flags["captures"] == env.flags["writes"] == 0
    assert old.read_bytes() == b"retained preexisting file" and list(env.folder.iterdir()) == [old]


def test_cached_preview_data_is_detached_plain_and_retains_no_pixel_array_or_native_graph(source_env):
    env = source_env
    proof = preview(env)
    entry = env.source._PLANS[proof["fingerprint"]]
    assert type(entry.raw) is bytes and entry.owner is None
    data = json.loads(entry.raw)
    assert "identity_witness" in data and "current_pixels" not in data["graph"]
    data["graph"]["native_identity_rows"][0]["session_uid"] = "999"
    assert json.loads(entry.raw)["graph"]["native_identity_rows"][0]["session_uid"] == "10"


def test_retained_completed_request_origin_cannot_renew_authority(source_env):
    env = source_env
    proof = preview(env)
    start(env, proof)
    origin = env.flags["origin"]
    before = env.flags["grants"], env.flags["captures"]
    with pytest.raises(env.source.BridgeError) as failure:
        origin.authorize()
    assert failure.value.context["reason"] == "REQUEST_ADMISSION_NO_LONGER_ACTIVE"
    assert (env.flags["grants"], env.flags["captures"]) == before


@pytest.mark.timeout(30)
def test_real_worker_cancellation_during_complete_read_stops_at_provider_free_safe_point(source_env):
    env = source_env
    owner = env.source.ConnectionLifetime()
    proof, _request, _life = queued_preview(env, owner)
    env.flags["job_model"] = True
    response, _request, _life = queued(env, env.source.METHODS[1], start_parameters(env, proof), owner, "cancel-during-read")
    assert response.ok, response.error
    def cancel():
        env.runtime.jobs.active.cancel_reason = "cancel during modeled full graph read"
    env.flags["capture_hook"] = cancel
    record = finish_model(env)
    assert record.state == "CANCELLED" and env.flags.get("steps", 0) == 0
    assert env.flags["writes"] == 0 and list(env.folder.iterdir()) == []


@pytest.mark.parametrize("reason", ["cancel", pytest.param("deadline", marks=pytest.mark.timeout(20))])
def test_current_worker_identity_query_gate_checks_cancel_and_real_elapsed_deadline(source_env, reason, record_property):
    env = source_env
    owner = env.source.ConnectionLifetime()
    proof, _request, _life = queued_preview(env, owner)
    env.flags["job_model"] = True
    values = start_parameters(env, proof)
    if reason == "deadline":
        # Exercise an elapsed deadline at the identity safe point, rather than
        # impose an unpromised three-second admission performance guarantee.
        values["time_limit_seconds"] = 10
    response, _request, _life = queued(env, env.source.METHODS[1], values, owner, "identity-safe-point")
    assert response.ok, response.error
    job = env.runtime.jobs.active
    origin = job.driver.origin
    retained_deadline, retained_origin_deadline = job.deadline, origin.deadline
    record_property("accepted_job_deadline_headroom_seconds", retained_deadline - time.monotonic())
    record_property("accepted_start_origin_deadline_headroom_seconds", retained_origin_deadline - time.monotonic())

    def interrupt():
        env.flags["identity_hook"] = None
        env.flags["identity_interrupt_fired"] = True
        env.flags["native_calls_at_identity_interrupt"] = list(env.native.calls)
        record_property("identity_interrupt_origin_headroom_seconds", retained_origin_deadline - time.monotonic())
        record_property("identity_interrupt_job_headroom_seconds", retained_deadline - time.monotonic())
        if reason == "cancel":
            job.cancel_reason = "cancel between modeled native identity queries"
        else:
            earliest = min(retained_origin_deadline, retained_deadline)
            env.source.threading.Event().wait(max(0., earliest - time.monotonic()) + .01)
            elapsed_at = time.monotonic()
            assert elapsed_at >= earliest
            record_property("identity_interrupt_elapsed_past_earliest_seconds", elapsed_at - earliest)
    env.flags["identity_hook"] = interrupt
    record = finish_model(env)
    assert env.flags.get("identity_interrupt_fired") is True
    assert env.native.calls == env.flags["native_calls_at_identity_interrupt"]
    assert record.state == "CANCELLED" and record.error["code"] == "TIMEOUT"
    assert job.deadline is retained_deadline and origin.deadline is retained_origin_deadline
    assert env.flags.get("steps", 0) == 0
    assert env.flags["writes"] == 0 and list(env.folder.iterdir()) == []


def test_real_three_second_start_deadline_denial_stops_after_provider_before_handler_or_native_effects(source_env, record_property):
    env = source_env
    owner = env.source.ConnectionLifetime()
    proof, _request, _life = queued_preview(env, owner)
    env.flags["job_model"] = True
    before_handler, before_captures = env.flags["handler"], env.flags["captures"]

    def expire_during_provider():
        env.flags["hook"] = None
        env.flags["deadline_provider_hook_fired"] = True
        # The initial bounded identity witness precedes this provider. Capture
        # its actual calls here; do not claim those legitimate reads were zero.
        env.flags["native_calls_at_deadline_provider"] = list(env.native.calls)
        started = time.monotonic()
        env.source.threading.Event().wait(3.02)
        elapsed = time.monotonic() - started
        assert elapsed >= 3.
        record_property("deadline_provider_actual_wait_seconds", elapsed)
    env.flags["hook"] = expire_during_provider
    values = start_parameters(env, proof)
    values["time_limit_seconds"] = 3
    response, _request, _life = queued(env, env.source.METHODS[1], values, owner, "three-second-denial")
    assert env.flags.get("deadline_provider_hook_fired") is True
    assert not response.ok and response.error["code"] == "TIMEOUT"
    assert env.native.calls == env.flags["native_calls_at_deadline_provider"]
    assert env.flags["handler"] == before_handler and env.flags["captures"] == before_captures
    assert env.runtime.jobs.active is None and not env.runtime.jobs.history
    assert env.flags.get("steps", 0) == 0 and env.flags["writes"] == 0
    assert list(env.folder.iterdir()) == []


@pytest.mark.parametrize("length", [129, 256])
def test_genuine_queued_preview_and_start_preserve_existing_valid_protocol_id_limit(source_env, length):
    env = source_env
    owner = env.source.ConnectionLifetime()
    proof, item, _life = queued_preview(env, owner, identifier="A" * length)
    assert item.response.id == "A" * length
    response, item, _life = queued(env, env.source.METHODS[1], start_parameters(env, proof), owner, "B" * length)
    assert response.ok, response.error
    assert response.id == item.request.id == "B" * length and response.result["model_source_only"]


def test_protocol_parser_retains_existing_257_character_id_refusal(source_env):
    env = source_env
    before = dict(env.flags)
    with pytest.raises(env.source.BridgeError) as failure:
        env.source.protocol.Request.from_mapping({"id": "A" * 257, "method": env.source.METHODS[0],
            "params": params(env), "protocol_version": env.source.protocol.PROTOCOL_VERSION})
    assert failure.value.code == "INVALID_REQUEST" and env.flags == before


@pytest.mark.parametrize("changed", ["function", "descriptor", "code"])
def test_identity_safe_point_rejects_changed_shared_verifier_before_any_foreign_call(source_env, monkeypatch, changed):
    env = source_env
    verifier_type = env.source.jobs.PreparedJobCallbacks
    original = verifier_type.verify
    def foreign(*_args, **_kwargs):
        env.flags["foreign"] += 1
        raise AssertionError("Foreign shared verifier")
    namespace = {}
    exec('def foreign_code(*args, **kwargs):\n    _CODE_FOREIGN_COUNTER["foreign"] += 1\n    raise AssertionError("Foreign verifier code")\n', namespace)
    monkeypatch.setattr(env.source.jobs, "_CODE_FOREIGN_COUNTER", env.flags, raising=False)
    class Foreign:
        def __get__(self, _instance, _owner):
            return foreign()
    def replace():
        env.flags["identity_hook"] = None
        if changed == "code":
            monkeypatch.setattr(original, "__code__", namespace["foreign_code"].__code__)
        else:
            monkeypatch.setattr(verifier_type, "verify", foreign if changed == "function" else Foreign())
    env.flags["identity_hook"] = replace
    with pytest.raises(env.source.BridgeError) as failure:
        preview(env)
    # Existing deferred admission can surface its later pure dependency check
    # instead of the original shared-slot refusal. Both precede foreign code.
    assert failure.value.context["reason"] in {"SHARED_VERIFIER_CHANGED", "DOMAIN_CALLBACK_SOURCE_CHANGED"}
    assert env.flags["foreign"] == env.flags["captures"] == env.flags["writes"] == 0


@pytest.mark.parametrize("key,value", [("work", False), ("work", 0), ("callbacks", False), ("callbacks", 0),
    ("context", False), ("job", 0)])
def test_current_grant_cannot_mutate_shared_verifier_keyword_contents_in_place(source_env, monkeypatch, key, value):
    env = source_env
    keywords = env.source.jobs.PreparedJobCallbacks.verify.__kwdefaults__
    def replace():
        env.flags["hook"] = None
        monkeypatch.setitem(keywords, key, value)
    env.flags["hook"] = replace
    with pytest.raises(env.source.BridgeError) as failure:
        preview(env)
    assert failure.value.context["reason"] == "SHARED_VERIFIER_KEYWORDS_CHANGED"
    assert env.source.jobs.PreparedJobCallbacks.verify.__kwdefaults__ is keywords
    assert env.flags["foreign"] == env.flags["captures"] == env.flags["writes"] == 0


@pytest.mark.parametrize("value", [False, 0])
def test_in_place_work_default_change_cannot_advance_foreign_owned_work(source_env, monkeypatch, value):
    env = source_env
    owner = env.source.ConnectionLifetime()
    proof, _request, _life = queued_preview(env, owner)
    env.flags["job_model"] = True
    response, _request, _life = queued(env, env.source.METHODS[1], start_parameters(env, proof), owner, "work-default-drift")
    assert response.ok, response.error
    job = env.runtime.jobs.active
    control = env.runtime.jobs._prepared_controls[id(job)][1]
    class ForeignWork:
        def __next__(self):
            env.flags["foreign"] += 1
            raise AssertionError("Foreign work advanced")
        def close(self):
            env.flags["foreign"] += 1
            raise AssertionError("Foreign work closed")
    control.work = job.work = ForeignWork()
    keywords = env.source.jobs.PreparedJobCallbacks.verify.__kwdefaults__
    monkeypatch.setitem(keywords, "work", value)
    record = finish_model(env)
    assert record.state == "FAILED" and env.flags["foreign"] == env.flags["writes"] == 0
    assert record.error["context"]["reason"] == "SHARED_VERIFIER_KEYWORDS_CHANGED"
    assert env.source.jobs.PreparedJobCallbacks.verify.__kwdefaults__ is keywords
    assert list(env.folder.iterdir()) == []


def test_all_four_graph_literal_tables_are_mandatory_with_separate_fact_budget(source_env):
    env = source_env
    required = {"_CATALOG_HASHES", "_STATIC_CATALOG_HASHES", "_FIXED_TARGETS", "_RUNTIME_MARKER_ROWS"}
    actual = {name for owner, name, _facts, _refs in env.source._REGISTRATION.constants if owner is env.graph}
    assert required <= actual
    facts = env.source._literal_facts(env.graph._FIXED_TARGETS)
    assert len(json.dumps(facts, separators=(",", ":")).encode()) <= env.source.MAX_PLAN_BYTES
    assert env.source._literal_matches(env.graph._FIXED_TARGETS, facts)
    # Expanded source-fact wrappers remain invalid as client request/plan data.
    with pytest.raises(env.source.BridgeError):
        env.source._plain(facts)
    assert all(type(key) is tuple and len(key) == 2 and all(type(part) is str for part in key)
               for key in env.graph._RUNTIME_MARKER_ROWS)


@pytest.mark.parametrize("table", ["_FIXED_TARGETS", "_RUNTIME_MARKER_ROWS"])
def test_current_provider_cannot_mutate_captured_graph_table_in_place(source_env, monkeypatch, table):
    env = source_env
    def mutate():
        env.flags["hook"] = None
        if table == "_FIXED_TARGETS":
            values = env.graph._FIXED_TARGETS[env.native.bpy.app.build_hash]["Material"]
            monkeypatch.setitem(values, "node_tree", "Object")
        else:
            key = ("Scene", "cycles")
            values = env.graph._RUNTIME_MARKER_ROWS[key]
            monkeypatch.setitem(env.graph._RUNTIME_MARKER_ROWS, key, ("INT", *values[1:]))
    env.flags["hook"] = mutate
    with pytest.raises(env.source.BridgeError) as failure:
        preview(env)
    assert failure.value.context["reason"] == "DOMAIN_CONSTANT_CHANGED"
    assert env.flags["captures"] == env.flags["foreign"] == env.flags["writes"] == 0


@pytest.mark.parametrize("table", ["_CATALOG_HASHES", "_STATIC_CATALOG_HASHES", "_FIXED_TARGETS", "_RUNTIME_MARKER_ROWS"])
def test_registration_refuses_missing_required_graph_table_without_native_or_provider(source_env, monkeypatch, table):
    env = source_env
    before, native = dict(env.flags), list(env.native.calls)
    monkeypatch.delattr(env.graph, table)
    with pytest.raises(env.source.BridgeError) as failure:
        env.source.bind_registry(env.runtime.registry)
    assert failure.value.context["reason"] == "MANDATORY_GRAPH_TABLE_NOT_CAPTURED"
    assert env.flags == before and env.native.calls == native


def test_literal_comparison_refuses_foreign_dict_key_before_hash_or_equality(source_env):
    env = source_env
    class Foreign:
        def __hash__(self):
            if env.flags.get("key_armed"):
                env.flags["foreign"] += 1
                raise AssertionError("Foreign key hashed during verification")
            return 17
        def __eq__(self, _other):
            env.flags["foreign"] += 1
            raise AssertionError("Foreign key compared during verification")
    values = {Foreign(): "unchanged"}
    env.flags["key_armed"] = True
    assert not env.source._literal_matches(values, env.source._literal_facts({"expected": "unchanged"}))
    assert env.flags["foreign"] == 0


@pytest.mark.parametrize("value", [{("three", "part", "key"): 1}, {("owner", 2): 1}, "x" * 4097, 1 << 4096])
def test_literal_capture_keeps_original_input_bounds_and_exact_owner_field_keys(source_env, value):
    with pytest.raises(source_env.source.BridgeError):
        source_env.source._literal_facts(value)


@pytest.mark.parametrize("changed", ["none", "function", "code", "globals", "defaults", "kwdefaults", "cell", "cell_value", "empty_cell"])
def test_direct_function_matching_preserves_every_captured_identity(addon_package, changed):
    source = importlib.import_module(addon_package + ".current_pixels_source")
    value = object()
    def factory(retained):
        def candidate(argument=None, *, enabled=True):
            return retained, argument, enabled
        return candidate
    candidate = factory(value)
    facts = source._function_facts(candidate)
    if changed == "function":
        candidate = factory(value)
    elif changed == "code":
        candidate.__code__ = candidate.__code__.replace(co_name="different_code_identity")
    elif changed == "globals":
        facts = (*facts[:2], dict(candidate.__globals__), *facts[3:])
    elif changed == "defaults":
        candidate.__defaults__ = (object(),)
    elif changed == "kwdefaults":
        candidate.__kwdefaults__ = {"enabled": True}
    elif changed == "cell":
        cell = factory(value).__closure__[0]
        facts = (*facts[:5], ((cell, value),))
    elif changed == "cell_value":
        candidate.__closure__[0].cell_contents = object()
    elif changed == "empty_cell":
        del candidate.__closure__[0].cell_contents
    assert source._function_matches(candidate, facts) is (changed == "none")


def test_static_class_path_matches_raw_inspector_without_descriptor_invocation(addon_package):
    source = importlib.import_module(addon_package + ".current_pixels_source")
    calls = []
    class Foreign:
        def __get__(self, *_args):
            calls.append("foreign")
            raise AssertionError("Static class lookup invoked descriptor")
    class Base:
        inherited = object()
        descriptor = Foreign()
        @property
        def prop(self):
            raise AssertionError("Static lookup invoked property")
        @staticmethod
        def static():
            raise AssertionError("Static lookup invoked method")
        @classmethod
        def klass(cls):
            raise AssertionError("Static lookup invoked classmethod")
    class Owner(Base):
        own = object()
    for name in ("own", "inherited", "descriptor", "prop", "static", "klass", "missing", "__dict__", "__mro__", "__call__", "__new__"):
        assert source._static(Owner, name) is source.inspect.getattr_static(Owner, name, source._MISSING)
    Owner.inherited = object()
    assert source._static(Owner, "inherited") is vars(Owner)["inherited"]
    del Owner.inherited
    assert source._static(Owner, "inherited") is vars(Base)["inherited"]
    assert calls == []


def test_static_lookup_preserves_missing_sentinel_value_instead_of_falling_through(addon_package):
    source = importlib.import_module(addon_package + ".current_pixels_source")
    class Owner:
        __call__ = source._MISSING
    assert source._static(Owner, "__call__") is source._MISSING
    assert source._static(Owner, "__call__") is source.inspect.getattr_static(Owner, "__call__", source._MISSING)


def test_static_fastpath_checks_current_entire_mro_and_keeps_instance_fallback(addon_package, monkeypatch):
    source = importlib.import_module(addon_package + ".current_pixels_source")
    original, calls, foreign = source.inspect.getattr_static, [], []
    def counted(owner, name, default):
        calls.append((owner, name))
        return original(owner, name, default)
    class Plain:
        pass
    class Owner(Plain):
        own = object()
    class Meta(type):
        @property
        def __dict__(cls):
            foreign.append("metaclass dictionary")
            raise AssertionError("Static lookup executed metaclass descriptor")
    class Shadow(metaclass=Meta):
        inherited = object()
    monkeypatch.setattr(source.inspect, "getattr_static", counted)
    assert source._static(Owner, "own") is vars(Owner)["own"] and calls == []
    instance = Owner()
    assert source._static(instance, "own") is vars(Owner)["own"] and calls == [(instance, "own")]
    calls.clear()
    Owner.__bases__ = (Shadow,)
    assert type(Owner) is type and type(Shadow) is Meta
    assert source._static(Owner, "inherited") is original(Owner, "inherited", source._MISSING) is source._MISSING
    assert calls == [(Owner, "inherited")] and foreign == []


def test_immutable_literal_identity_uses_strong_fact_and_value_then_structural_fallback(addon_package, monkeypatch):
    source = importlib.import_module(addon_package + ".current_pixels_source")
    value = ("literal", (1, -0.), frozenset({"one", "two"}))
    facts = source._literal_facts(value)
    references = source._immutable_literal_refs(value, facts)
    assert type(references) is source.MappingProxyType
    assert references[id(facts)][0] is facts and references[id(facts)][1] is value
    with pytest.raises(TypeError):
        references[id(facts)] = (facts, ())
    original, calls = source._literal_matches, []
    def counted(actual, captured, immutable=None):
        calls.append(actual)
        return original(actual, captured, immutable)
    monkeypatch.setattr(source, "_literal_matches", counted)
    assert source._literal_matches(value, facts, references) and len(calls) == 1
    replacement = tuple([*value])
    assert replacement is not value
    calls.clear()
    assert source._literal_matches(replacement, facts, references) and len(calls) > 1
    assert not source._literal_matches((value[0], (1, +0.), value[2]), facts, references)
    assert not source._literal_matches((value[0], (True, -0.), value[2]), facts, references)


@pytest.mark.parametrize("kind", ["list", "dict", "set"])
def test_retained_tuple_with_mutable_descendant_never_shortcuts_in_place_change(addon_package, kind):
    source = importlib.import_module(addon_package + ".current_pixels_source")
    child = [1] if kind == "list" else {"entry": 1} if kind == "dict" else {1}
    value = ("stable", child)
    facts = source._literal_facts(value)
    references = source._immutable_literal_refs(value, facts)
    assert id(facts) not in references and not source._deeply_immutable_literal(value)
    assert source._literal_matches(value, facts, references)
    if kind == "list":
        child[0] = 2
    elif kind == "dict":
        child["entry"] = 2
    else:
        child.remove(1)
        child.add(2)
    assert not source._literal_matches(value, facts, references)


def test_immutable_reference_map_does_not_treat_missing_fact_as_missing_source_value(addon_package):
    source = importlib.import_module(addon_package + ".current_pixels_source")
    facts = source._literal_facts("retained")
    empty = source.MappingProxyType({})
    assert not source._literal_matches(source._MISSING, facts, empty)
    assert not source._literal_matches("changed", facts, empty)


def test_registration_tracks_readonly_literal_map_identity_before_full_reader(source_env):
    env = source_env
    binding = env.source._REGISTRATION
    index = next(index for index, (owner, name, _facts, _references) in enumerate(binding.constants)
                 if owner is env.graph and name == "_FIXED_TARGETS")
    original = binding.constants[index]
    def replace():
        env.flags["hook"] = None
        binding.constants[index] = (*original[:3], env.source.MappingProxyType({}))
    env.flags["hook"] = replace
    with pytest.raises(env.source.BridgeError) as failure:
        preview(env)
    assert failure.value.context["reason"] == "IMMUTABLE_LITERAL_MAP_CHANGED"
    assert env.flags["foreign"] == env.flags["captures"] == env.flags["writes"] == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_immutable_literal_optimization_does_not_admit_nonfinite_capture(addon_package, value):
    source = importlib.import_module(addon_package + ".current_pixels_source")
    with pytest.raises(source.BridgeError):
        source._literal_facts((value,))


def test_immutable_literal_capture_refuses_subclasses_without_iteration(addon_package):
    source = importlib.import_module(addon_package + ".current_pixels_source")
    class Foreign(tuple):
        def __iter__(self):
            pytest.fail("Foreign tuple subclass iterated")
    with pytest.raises(source.BridgeError):
        source._literal_facts(Foreign(("value",)))


@pytest.mark.parametrize("member,changed", [
    ("getter", "code"), ("setter", "code"), ("deleter", "code"),
    ("static", "code"), ("class", "code"), ("getter", "defaults"),
    ("getter", "kwdefaults"), ("getter", "cell_value"), ("getter", "empty_cell"),
])
def test_registration_inline_descriptor_facts_keep_every_identity_and_empty_cell_refusal(source_env, monkeypatch, member, changed):
    env = source_env
    exec('''
def _captured_factory(retained):
    class Captured:
        @property
        def value(self, argument=None, *, enabled=True):
            return retained, argument, enabled
        @value.setter
        def value(self, new):
            return retained, new
        @value.deleter
        def value(self):
            return retained
        @staticmethod
        def static():
            return retained
        @classmethod
        def klass(cls):
            return retained, cls
    return Captured
Captured = _captured_factory(object())
''', vars(env.domain))
    env.source.bind_registry(env.runtime.registry)
    binding = env.source._REGISTRATION
    descriptor = vars(env.domain.Captured)["value"]
    function = {"getter": descriptor.fget, "setter": descriptor.fset, "deleter": descriptor.fdel,
                "static": vars(env.domain.Captured)["static"].__func__,
                "class": vars(env.domain.Captured)["klass"].__func__}[member]
    before, native = dict(env.flags), list(env.native.calls)
    if changed == "code":
        monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="changed"))
    elif changed == "defaults":
        monkeypatch.setattr(function, "__defaults__", (object(),))
    elif changed == "kwdefaults":
        monkeypatch.setattr(function, "__kwdefaults__", {"enabled": True})
    elif changed == "cell_value":
        function.__closure__[0].cell_contents = object()
    else:
        del function.__closure__[0].cell_contents
    with pytest.raises(env.source.BridgeError) as failure:
        binding.verify()
    assert failure.value.context["reason"] == "DOMAIN_CALLBACK_SOURCE_CHANGED"
    assert env.flags == before and env.native.calls == native


@pytest.mark.parametrize("kind", ["callback", "binding", "constant"])
def test_registration_current_module_rows_refuse_changed_or_deleted_member_before_effects(source_env, monkeypatch, kind):
    env = source_env
    binding = env.source._REGISTRATION
    before, native = dict(env.flags), list(env.native.calls)
    if kind == "callback":
        owner, name, _value, _facts = next(row for row in reversed(binding.functions)
                                         if type(row[0]) is ModuleType)
        reason = "DOMAIN_CALLBACK_SOURCE_CHANGED"
    elif kind == "binding":
        owner, name, _value = next(row for row in reversed(binding.bindings)
                                  if type(row[0]) is ModuleType)
        reason = "DOMAIN_BINDING_CHANGED"
    else:
        owner, name, _facts, _immutable = next(row for row in reversed(binding.constants)
                                             if type(row[0]) is ModuleType)
        reason = "DOMAIN_CONSTANT_CHANGED"
    monkeypatch.delattr(owner, name)
    with pytest.raises(env.source.BridgeError) as failure:
        binding.verify()
    assert failure.value.context["reason"] == reason
    assert env.flags == before and env.native.calls == native
