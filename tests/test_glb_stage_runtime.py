"""Source service/lifetime countermodels, never Blender/native acceptance."""
from __future__ import annotations

import importlib
import time
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def runtime_case(addon_package, monkeypatch):
    module = importlib.import_module(addon_package + ".runtime")
    lifecycle = importlib.import_module(addon_package + ".request_lifecycle")
    states = importlib.import_module(addon_package + ".state")
    # Other test runtimes may deliberately shadow the shared singleton's
    # methods. This positive model needs a fresh canonical state instance.
    monkeypatch.setattr(module, "get_state", states.BridgeState)
    owner = module.BridgeRuntime()
    monkeypatch.setattr(module, "_RUNTIME", owner)
    owner._registered = True
    owner.registry.enable_toolset("asset_delivery")
    context = owner.executor.context
    context.request_lifecycle = lifecycle.RequestLifetime(connection=lifecycle.ConnectionLifetime())
    context.glb_method = "asset.glb_stage_preview"
    return module, owner, context


def test_runtime_wires_single_owned_service_into_every_context(runtime_case):
    _module, owner, context = runtime_case
    assert context.glb_stage is owner.glb_stage is owner._glb_stage_origin
    assert owner.executor.context.glb_stage is owner.glb_stage
    assert owner.glb_stage.jobs is owner.jobs
    assert owner.glb_stage.checkpoints is owner.checkpoints


@pytest.mark.parametrize("fault", ["other_service", "other_registry", "other_jobs", "other_checkpoints",
                                    "other_connection", "local_connection", "disconnected", "generation",
                                    "unregistered", "owner_origin", "runtime_replaced"])
def test_service_rejects_foreign_or_expired_authority_without_native_access(runtime_case, fault, monkeypatch):
    module, owner, context = runtime_case
    service = owner.glb_stage
    connection = context.request_lifecycle.connection
    generation = service._generation
    if fault == "other_service":
        context.glb_stage = object()
    elif fault == "other_registry":
        context.registry = object()
    elif fault == "other_jobs":
        context.jobs = object()
    elif fault == "other_checkpoints":
        context.checkpoints = object()
    elif fault == "other_connection":
        connection = object()
    elif fault == "local_connection":
        context.request_lifecycle.connection = None
    elif fault == "disconnected":
        connection.disconnected.set()
    elif fault == "generation":
        generation = "old"
    elif fault == "unregistered":
        owner._registered = False
    elif fault == "owner_origin":
        owner._glb_stage_origin = object()
    else:
        monkeypatch.setattr(module, "_RUNTIME", object())
    with pytest.raises(module.BridgeError):
        service.check_context(context, connection, generation)
    assert not service._records and not service.store._records


def test_source_preference_is_not_a_wire_approved_root(runtime_case, monkeypatch):
    module, owner, _context = runtime_case
    monkeypatch.setattr(module, "_preferences", lambda: NS(asset_source_directory=""))
    with pytest.raises(module.BridgeError, match="Approve a nonempty"):
        owner.glb_stage._source_root()
    monkeypatch.setattr(module, "_preferences", lambda: NS(asset_source_directory="/approved-by-Blender"))
    assert owner.glb_stage._source_root() == "/approved-by-Blender"


def test_invalidation_revokes_before_native_context_can_be_reused(runtime_case):
    _module, owner, context = runtime_case
    jobs = importlib.import_module(owner.glb_stage.__module__.rsplit(".", 1)[0] + ".glb_stage_jobs")
    gate = jobs.RuntimeNativeGate(owner.glb_stage, context.request_lifecycle.connection, owner.glb_stage._generation)
    gate.bind(context)
    gate.check()
    generation = owner.glb_stage._generation
    owner.glb_stage._records["model"] = NS(gate=gate)
    owner.glb_stage.invalidate()
    assert owner.glb_stage._generation != generation
    assert gate.revoked and gate.context is None
    with pytest.raises(Exception, match="Outside"):
        gate.check()


@pytest.mark.parametrize("method,reason", [
    ("register", "runtime registered"), ("unregister", "runtime unregistered"),
    ("stop_server", "bridge stopped"), ("emergency_stop", "emergency stop"),
    ("prepare_for_file_load", "project file replacement"), ("undo", "native undo/redo"),
])
def test_failed_glb_invalidation_revokes_authority_and_stops_existing_and_new_writes(
    runtime_case, monkeypatch, method, reason
):
    """Real grant/controller; an injected allocation failure is not native OOM proof."""
    module, owner, _context = runtime_case
    package = module.__package__
    painting = importlib.import_module(package + ".jobs")
    lifecycle = importlib.import_module(package + ".request_lifecycle")
    stage = importlib.import_module(package + ".glb_stage_runtime")
    writes = []
    method_name = "fixture.lifecycle_write"
    owner.registry.enable_toolset("core")
    owner.registry.register(method_name, lambda *_: writes.append("new handler"),
                            modifies=True, automatic_checkpoint=False)

    def work():
        while True:
            writes.append("existing step")
            yield {"phase": "model_write_boundary", "completed": 0, "total": 1}

    job = painting.PaintJob("job_lifecycle_model", "request_lifecycle_model", "source", "output",
        lifecycle.RequestLifetime.local(), time.monotonic() + 60, {}, (), {}, False,
        method=method_name, required_permissions=())
    job.work = work()
    owner.jobs.active = job
    assert owner.jobs.tick() is True and writes
    writes.clear()
    owner.arm_native_save_effects()
    original_grant = owner.native_save_policy.statement()
    # Model a lifecycle callback re-entering an existing scheduler turn. Its
    # cancellation must be retained before the next write boundary is visited.
    job.in_tick = True
    if method == "register":
        owner._registered = False
    failure = MemoryError("injected GLB invalidation token allocation")
    observed = []

    def fail_token_allocation(_size):
        observed.append((owner.native_save_policy.active(), owner.state.paused,
                         owner.state.emergency_stopped, job.cancel_reason))
        raise failure

    with monkeypatch.context() as fault:
        fault.setattr(stage.secrets, "token_hex", fail_token_allocation)
        with pytest.raises(MemoryError) as caught:
            if method == "undo":
                module._before_external_undo_redo(None)
            else:
                getattr(owner, method)()
    assert caught.value is failure
    assert observed == [(False, True, method == "emergency_stop", reason)]
    assert not owner.native_save_policy.active()
    with pytest.raises(ValueError):
        owner.native_save_policy.check(original_grant)
    assert job.cancel_reason == reason
    # Restore the actual allocation helper before checking writability, so a
    # damaged service origin cannot accidentally stand in for the stop policy.
    with pytest.raises(module.BridgeError) as refused:
        owner.executor.dispatch(method_name)
    expected = module.ErrorCode.EMERGENCY_STOPPED if method == "emergency_stop" else module.ErrorCode.AGENT_PAUSED
    assert refused.value.code == expected.value and writes == []
    job.in_tick = False
    assert owner.jobs.tick() is False
    assert job.state == "CANCELLED" and job.error["code"] == module.ErrorCode.TIMEOUT.value
    assert job.error["context"]["job_cancel_requested"] is True
    assert job.error["context"]["reason"] == reason and writes == []


@pytest.mark.parametrize("paused,stopped", [(False, False), (True, False), (True, True)])
def test_successful_native_history_invalidation_preserves_prior_stop_intent(runtime_case, paused, stopped):
    module, owner, _context = runtime_case
    owner.arm_native_save_effects()
    owner.state.set_emergency_stopped(stopped)
    owner.state.set_paused(paused)
    module._before_external_undo_redo(None)
    assert owner.state.paused is paused and owner.state.emergency_stopped is stopped
    assert not owner.native_save_policy.active()


def test_protected_legacy_uv_reader_refuses_before_getter_or_iteration(addon_package):
    module = importlib.import_module(addon_package + ".glb_stage_runtime")

    class ProtectedUV:
        def __getattribute__(self, name):
            pytest.fail("protected legacy UV getter was reached: " + name)

    view = object.__new__(module._ProtectedView)
    view.binding = NS(classes={"MeshUVLoopLayer": ProtectedUV, "Mesh": object, "Object": object})
    with pytest.raises(module.invalid_argument("x").__class__) as failure:
        view.field(ProtectedUV(), "data")
    assert failure.value.context["reason"] == "GLB_PROTECTED_NATIVE_LEGACY_UV_DATA_FORBIDDEN"
    assert failure.value.context["native_allocation_started"] is False


@pytest.mark.parametrize("name", ["vertices", "edges", "loops", "polygons"])
def test_protected_mesh_collection_views_require_current_fresh_observation(addon_package, name):
    module = importlib.import_module(addon_package + ".glb_stage_runtime")

    class ProtectedMesh:
        def __getattribute__(self, field):
            pytest.fail("protected Mesh getter reached: " + field)

    view = object.__new__(module._ProtectedView)
    view.binding = NS(classes={"Mesh": ProtectedMesh, "MeshUVLoopLayer": object})
    view._observing = False
    with pytest.raises(module.invalid_argument("x").__class__) as failure:
        view.field(ProtectedMesh(), name)
    assert failure.value.context["reason"] == "GLB_PROTECTED_MESH_OUTSIDE_CURRENT_OBSERVATION"


@pytest.mark.parametrize("fault", ["context_manager", "executor_manager", "executor", "wrapper_service"])
def test_forged_context_or_executor_grants_cannot_replace_canonical_provider(runtime_case, fault):
    module, owner, context = runtime_case
    permissions = importlib.import_module(module.__package__ + ".permissions")
    authority = importlib.import_module(module.__package__ + ".scene_job_authority")
    callbacks = []
    def granting_provider():
        callbacks.append("FORGED_PROVIDER")
        return {permission.value: True for permission in permissions.Permission}

    forged = permissions.PermissionManager(granting_provider)
    if fault == "context_manager":
        context.permissions = forged
    elif fault == "executor_manager":
        owner.executor.permissions = forged
        context = owner.executor.context
        context.request_lifecycle = importlib.import_module(module.__package__ + ".request_lifecycle").RequestLifetime(
            connection=importlib.import_module(module.__package__ + ".request_lifecycle").ConnectionLifetime())
    elif fault == "executor":
        owner.executor = NS(permissions=owner.permissions, glb_stage=owner.glb_stage)
    else:
        context.permissions = authority.SceneJobPermissions(owner.permissions, object())
    with pytest.raises(module.BridgeError):
        owner.glb_stage._entry(context, "asset.glb_stage_preview", (permissions.Permission.INSPECT_SCENE,))
    assert callbacks == []
    assert not owner.glb_stage.store._records


def test_runtime_component_origin_checks_do_not_invoke_foreign_equality(runtime_case):
    module, owner, context = runtime_case
    callbacks = []

    class Counterfeit:
        def __eq__(self, _other):
            callbacks.append("FOREIGN_EQUALITY")
            return True

    owner.jobs = Counterfeit()
    with pytest.raises(module.BridgeError):
        owner.glb_stage.check_context(context, context.request_lifecycle.connection, owner.glb_stage._generation)
    assert callbacks == []
    assert not owner.glb_stage.store._records


def test_canonical_scene_permission_wrapper_keeps_original_manager(runtime_case):
    module, owner, context = runtime_case
    authority = importlib.import_module(module.__package__ + ".scene_job_authority")
    context.permissions = authority.SceneJobPermissions(owner.permissions, owner.registry._scene_reservations)
    owner.glb_stage.check_context(context, context.request_lifecycle.connection, owner.glb_stage._generation)


@pytest.mark.parametrize("owner_kind", ["manager", "scene_view"])
@pytest.mark.parametrize("method", ["require", "snapshot", "is_allowed"])
def test_canonical_permission_objects_reject_instance_method_shadows(runtime_case, owner_kind, method):
    module, owner, context = runtime_case
    permissions = importlib.import_module(module.__package__ + ".permissions")
    authority = importlib.import_module(module.__package__ + ".scene_job_authority")
    target = owner.permissions
    if owner_kind == "scene_view":
        target = context.permissions = authority.SceneJobPermissions(owner.permissions, owner.registry._scene_reservations)
    callbacks = []
    setattr(target, method, lambda *_args: callbacks.append("SHADOWED_ENFORCEMENT"))
    with pytest.raises(module.BridgeError):
        owner.glb_stage._entry(context, "asset.glb_stage_preview", (permissions.Permission.INSPECT_SCENE,))
    assert callbacks == []
    assert not owner.glb_stage.store._records


@pytest.mark.parametrize("owner_kind", ["manager", "scene_view"])
def test_permission_class_enforcement_code_is_pinned_before_grant_callbacks(runtime_case, owner_kind, monkeypatch):
    module, owner, context = runtime_case
    permissions = importlib.import_module(module.__package__ + ".permissions")
    authority = importlib.import_module(module.__package__ + ".scene_job_authority")
    target = permissions.PermissionManager
    if owner_kind == "scene_view":
        context.permissions = authority.SceneJobPermissions(owner.permissions, owner.registry._scene_reservations)
        target = authority.SceneJobPermissions
    callbacks = []
    monkeypatch.setattr(target, "require", lambda *_args: callbacks.append("REPLACED_ENFORCEMENT"))
    with pytest.raises(module.BridgeError):
        owner.glb_stage._entry(context, "asset.glb_stage_preview", (permissions.Permission.INSPECT_SCENE,))
    assert callbacks == []


def test_foreign_context_is_refused_before_any_attribute_callback(runtime_case):
    module, owner, _context = runtime_case
    callbacks = []

    class ForeignContext:
        def __getattribute__(self, name):
            callbacks.append(("get", name))
            raise AssertionError("foreign context read")

        def __setattr__(self, name, _value):
            callbacks.append(("set", name))
            raise AssertionError("foreign context write")

    with pytest.raises(module.BridgeError):
        owner.glb_stage._entry(ForeignContext(), "asset.glb_stage_preview", ())
    assert callbacks == []


def test_executor_state_fork_cannot_hide_original_runtime_emergency_stop(runtime_case, monkeypatch):
    module, owner, context = runtime_case
    states = importlib.import_module(module.__package__ + ".state")
    owner.registry.register("fixture.glb_state_gate", lambda *_args: None, modifies=True)
    context.glb_method = "fixture.glb_state_gate"
    monkeypatch.setattr(owner.state, "emergency_stopped", True)
    with pytest.raises(module.BridgeError) as baseline:
        owner.glb_stage.check_context(context, context.request_lifecycle.connection, owner.glb_stage._generation)
    assert baseline.value.code == module.ErrorCode.EMERGENCY_STOPPED.value
    owner.executor.state = states.BridgeState()
    forked = owner.executor.context
    forked.request_lifecycle = context.request_lifecycle
    forked.glb_method = context.glb_method
    with pytest.raises(module.BridgeError) as changed:
        owner.glb_stage.check_context(forked, forked.request_lifecycle.connection, owner.glb_stage._generation)
    assert changed.value.context["reason"] == "GLB_CANONICAL_CONTEXT_COMPONENT_CHANGED"


@pytest.mark.parametrize("method", ["snapshot", "set_emergency_stopped"])
def test_state_enforcement_instance_shadows_do_not_run(runtime_case, method):
    module, owner, context = runtime_case
    callbacks = []
    setattr(owner.state, method, lambda *_args: callbacks.append("STATE_SHADOW"))
    try:
        with pytest.raises(module.BridgeError):
            owner.glb_stage.check_context(context, context.request_lifecycle.connection, owner.glb_stage._generation)
        assert callbacks == []
    finally:
        delattr(owner.state, method)


def test_all_protected_mesh_headers_are_admitted_before_first_geometry_read(addon_package):
    module = importlib.import_module(addon_package + ".glb_stage_runtime")
    meshes = (object(), object())
    events = []

    class Observer:
        def capture_headers(self, mesh):
            events.append(("header", meshes.index(mesh)))
            return {"attributes": [{"name": "position", "storage": "ARRAY" if mesh is meshes[0] else "SINGLE",
                "supported": True, "data_type": "FLOAT_VECTOR", "count": 3}]}

        def capture_mesh(self, _mesh):
            events.append(("geometry", None))
            pytest.fail("geometry reached before all-Mesh SINGLE admission")

    view = object.__new__(module._ProtectedView)
    view._observing = False
    view.mesh_observer = Observer()
    with pytest.raises(module.invalid_argument("x").__class__) as failure:
        view.observe({"meshes": {0: meshes[0], 1: meshes[1]}, "objects": {}}, lambda: None)
    assert failure.value.context["reason"] == "PROTECTED_MESH_SINGLE_REQUIRES_SEPARATE_PREPARATION"
    assert events == [("header", 0), ("header", 1)]
    assert view._observing is False and view._meshes == view._groups == {}


def test_detached_legacy_shapes_copy_full_values_without_native_legacy_reads(addon_package):
    module = importlib.import_module(addon_package + ".glb_stage_runtime")
    projection = {
        "geometry": {"vertices": [{"index": 0, "co": ["0000803f", "00000080", "00000040"],
                                    "groups": [[2, "0000003f"]]}]},
        "uv_roles": {"active_index": 0},
        "uv_layers": [{"name": "UVMap", "active": True, "active_render": True, "active_clone": False,
                       "data": [{"uv": ["0000803e", "0000403f"], "pin_uv": True}]}],
    }
    view = object.__new__(module._ProtectedView)
    view.mesh_snapshot = lambda _mesh: projection
    vertex = view.mesh_field(object(), "vertices")[0]
    assert vertex.index == 0 and vertex.co == (1., -0., 2.)
    assert vertex.groups[0].group == 2 and vertex.groups[0].weight == .5
    layers = view.mesh_field(object(), "uv_layers")
    assert layers.active_index == 0 and layers[0].name == "UVMap" and layers[0].active_render is True
    assert layers[0].data[0].uv == [.25, .75] and layers[0].data[0].pin_uv is True
    import struct
    assert struct.pack("<f", vertex.co[1]).hex() == "00000080"


@pytest.mark.parametrize("fault", ["constructor", "constructor_code", "validator", "validator_code",
    "detached_rows", "detached_rows_code", "detached_bits", "detached_bits_code", "guard", "guard_code", "module_class"])
@pytest.mark.parametrize("route", ["view_constructor", "canonical_context", "detached_read"])
def test_protected_reader_dependencies_reject_changes_before_foreign_call(addon_package, monkeypatch, fault, route):
    module = importlib.import_module(addon_package + ".glb_stage_runtime")
    runtime = importlib.import_module(addon_package + ".runtime")
    owner = runtime.BridgeRuntime()
    callbacks = []

    def foreign(*_args, **_kwargs):
        callbacks.append("FOREIGN_DEPENDENCY")
        pytest.fail("A changed dependency was called before source validation")

    if fault == "module_class":
        from types import ModuleType
        class ForeignModule(ModuleType):
            def __getattribute__(self, name):
                callbacks.append(name)
                raise AssertionError("Foreign module lookup preceded source validation")
        monkeypatch.setattr(module._protected_mesh, "__class__", ForeignModule)
    elif fault.endswith("_code"):
        def changed_code(*_args, **_kwargs):
            raise AssertionError("Changed dependency code was entered")
        function = {"constructor_code": module._PROTECTED_MESH_OBSERVER_ORIGIN.__init__,
            "validator_code": module._PROTECTED_HEADER_VALIDATOR_ORIGIN,
            "detached_rows_code": module._plain_rows, "detached_bits_code": module._bits_float,
            "guard_code": module._PROTECTED_DEPENDENCY_GUARD_ORIGIN}[fault]
        monkeypatch.setattr(function, "__code__", changed_code.__code__)
    elif fault == "constructor":
        monkeypatch.setattr(module._protected_mesh, "ProtectedMeshObserver", foreign)
    elif fault == "validator":
        monkeypatch.setattr(module._protected_mesh, "validate_header_profile", foreign)
    else:
        name = {"detached_rows": "_plain_rows", "detached_bits": "_bits_float", "guard": "_check_protected_dependencies"}[fault]
        monkeypatch.setattr(module, name, foreign)
    with pytest.raises(module.invalid_argument("x").__class__) as failure:
        if route == "view_constructor":
            module._ProtectedView(NS(_binding=object()))
        elif route == "canonical_context":
            owner.glb_stage.check_context_factory(owner.executor)
        else:
            view = object.__new__(module._ProtectedView)
            view.mesh_snapshot = foreign
            view.mesh_field(object(), "vertices")
    assert failure.value.context["reason"] == "GLB_PROTECTED_DEPENDENCY_ORIGIN_CHANGED"
    assert callbacks == []
