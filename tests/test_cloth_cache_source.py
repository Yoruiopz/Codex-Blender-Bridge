"""Fixed cloth source proof rejects drift before callback/native dispatch."""
from __future__ import annotations

import importlib
import operator
import subprocess
import sys
import time
from pathlib import Path
from types import FunctionType, SimpleNamespace

import pytest


@pytest.fixture
def boundary(addon_package):
    source = importlib.import_module(addon_package + ".tools._cloth_cache_source")
    registry = importlib.import_module(addon_package + ".tool_registry")
    state = importlib.import_module(addon_package + ".state")
    permissions = importlib.import_module(addon_package + ".permissions")
    calls = []

    def provider():
        calls.append("provider")
        return {item.value: True for item in permissions.Permission}

    context = registry.ToolContext(state.BridgeState(), permissions.PermissionManager(provider),
                                   registry.ToolRegistry(), None)
    return SimpleNamespace(source=source, context=context, calls=calls, package=addon_package,
                           module=lambda name: importlib.import_module(addon_package + "." + name))


def snapshot(boundary):
    return boundary.source.capture_cloth_sources(boundary.context)


def closure(value):
    return (lambda: value).__closure__[0]


def queued_context(boundary):
    queue, protocol, executor = (boundary.module(name) for name in ("command_queue", "protocol", "executor"))
    life = boundary.module("request_lifecycle").RequestLifetime.local()
    request = protocol.Request(id="cloth-source", method="simulation.cache_preview", params={}, _lifecycle=life)
    owner = queue.QueuedRequest(request, deadline=time.monotonic() + 60)
    code, = [code for code in executor.MainThreadExecutor._invoke_owned.__code__.co_consts
             if getattr(code, "co_freevars", None) == ("queued_owner",)]
    boundary.context.request_lifecycle, boundary.context.request_id = life, request.id
    boundary.context.check_cancelled = owner.check_active
    boundary.context.check_final_request = FunctionType(code, vars(executor), closure=(closure(owner),))
    return owner


def scene_context(boundary):
    # Genuine constructor wiring, without registering Blender, running a timer,
    # invoking a context factory or calling its preferences/permission provider.
    runtime = boundary.module("runtime").BridgeRuntime()
    boundary.context = runtime.executor.context
    return runtime.jobs, runtime, runtime.executor


def test_capture_and_recheck_never_call_provider_or_hooks(boundary):
    witness = snapshot(boundary)
    assert type(witness) is boundary.source.ClothSourceWitness
    for _ in range(3):
        assert witness.verify(boundary.context) is None
    assert boundary.calls == []
    with pytest.raises(AttributeError):
        witness.foreign = 1
    assert type(tuple.__getitem__(witness, 5)[1]) is tuple


def test_strict_python_function_qualification_still_refuses_native_accessors(boundary):
    with pytest.raises(boundary.source.BridgeError) as error:
        boundary.source._function(operator.attrgetter("_drv"))
    assert error.value.context["reason"] == "CLOTH_SOURCE_FUNCTION_UNQUALIFIED"
    assert boundary.calls == []


def test_native_purepath_accessor_boundaries_in_isolated_controlled_model():
    """Bootstrap substitutions stay in a child; real bundled proof is separate."""
    code = r'''
import operator,pathlib,sys
sys.path.insert(0,'addon')
from blender_codex_bridge.tools import _cloth_cache_source as source
from blender_codex_bridge.tool_registry import ToolContext,ToolRegistry
from blender_codex_bridge.state import BridgeState
from blender_codex_bridge.permissions import PermissionManager
calls=[]
def provider(): calls.append('provider');return {}
context=ToolContext(BridgeState(),PermissionManager(provider),ToolRegistry(),None)
source.capture_cloth_sources(context)  # Load fixed modules before model setup.
original=tuple((name,vars(pathlib.PurePath)[name]) for name in ('drive','root'))
old_rows=source._PATH_PROPERTIES
old_bindings=source._PATH_PROPERTY_BINDINGS
def install(drive='_drv',root='_root',setter=None):
    drive=property(operator.attrgetter(drive),setter)
    root=property(operator.attrgetter(root))
    pathlib.PurePath.drive,pathlib.PurePath.root=drive,root
    source._PATH_PROPERTIES=(('drive',drive,'_drv'),('root',root,'_root'))
    source._PATH_PROPERTY_BINDINGS=tuple((prop,tuple((slot,slot.__get__(prop,property)) for slot in source._PATH_PROPERTY_SLOTS)) for prop in (drive,root))
try:
    install()
    for _,prop,_ in source._PATH_PROPERTIES:
        source._native_path_accessor(pathlib,pathlib.PurePath,prop.fget)
    witness=source.capture_cloth_sources(context)
    witness.verify(context)
    prop=pathlib.PurePath.drive
    saved=(prop.fget,prop.fset,prop.fdel)
    for index in range(3):
        replacement=list(saved)
        replacement[index]=lambda *args:calls.append('foreign property accessor')
        property.__init__(prop,*replacement)
        try:
            try:witness.verify(context)
            except source.BridgeError:pass
            else:raise AssertionError('in-place property accessor replacement accepted')
            try:source.capture_cloth_sources(context)
            except source.BridgeError:pass
            else:raise AssertionError('in-place property accessor replacement recaptured')
        finally:property.__init__(prop,*saved)
    witness.verify(context)
    old=pathlib.PurePath.drive
    pathlib.PurePath.drive=property(lambda value:calls.append('foreign drive'))
    try: witness.verify(context)
    except source.BridgeError: pass
    else: raise AssertionError('property replacement accepted')
    pathlib.PurePath.drive=old
    old_factory=operator.attrgetter
    operator.attrgetter=lambda *args:calls.append('foreign factory')
    try:
        try: witness.verify(context)
        except source.BridgeError: pass
        else: raise AssertionError('factory replacement accepted')
        try: source._native_path_accessor(pathlib,pathlib.PurePath,old.fget)
        except source.BridgeError: pass
        else: raise AssertionError('foreign factory origin accepted')
    finally: operator.attrgetter=old_factory
    class TrapText(str):
        def __eq__(self,other): calls.append('eq');raise AssertionError('foreign equality')
        def __getitem__(self,key): calls.append('getitem');raise AssertionError('foreign slicing')
        def __repr__(self): calls.append('repr');raise AssertionError('foreign repr')
    for argument in ('_foreign',TrapText('_drv')):
        install(argument)
        try: source._native_path_accessor(pathlib,pathlib.PurePath,pathlib.PurePath.drive.fget)
        except source.BridgeError: pass
        else: raise AssertionError('unqualified native argument accepted')
    install(setter=lambda *args:calls.append('foreign setter'))
    try: source._native_path_accessor(pathlib,pathlib.PurePath,pathlib.PurePath.drive.fget)
    except source.BridgeError: pass
    else: raise AssertionError('setter-bearing property accepted')
    install()
    for module,owner,getter in ((object(),pathlib.PurePath,pathlib.PurePath.drive.fget),
                                (pathlib,object(),pathlib.PurePath.drive.fget),
                                (pathlib,pathlib.PurePath,operator.attrgetter('_drv'))):
        try: source._native_path_accessor(module,owner,getter)
        except source.BridgeError: pass
        else: raise AssertionError('unbound accessor accepted')
    class Foreign:
        def __getattribute__(self,name): calls.append(name);raise AssertionError('foreign callable')
    for getter in (Foreign(),lambda *args:calls.append('foreign function')):
        try: source._native_path_accessor(pathlib,pathlib.PurePath,getter)
        except source.BridgeError: pass
        else: raise AssertionError('foreign callable accepted')
finally:
    for name,value in original: setattr(pathlib.PurePath,name,value)
    source._PATH_PROPERTIES=old_rows
    source._PATH_PROPERTY_BINDINGS=old_bindings
assert calls==[],calls
print('isolated native-accessor countermodels passed; no Blender qualification')
'''
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert "countermodels passed" in result.stdout


@pytest.mark.parametrize("module,name", [
    ("storage_snapshot", "SnapshotOperation"), ("storage_snapshot_effects", "SnapshotJournal"),
    ("tools._cloth_cache_scope", "bounded"), ("tools._cloth_cache_job", "ClothCacheDriver"),
    ("tools._simulation_runtime", "profile"), ("tool_registry", "check_final_mutation"),
])
def test_module_binding_replacement_refuses_without_dispatch(boundary, monkeypatch, module, name):
    witness = snapshot(boundary)
    touched = []
    with monkeypatch.context() as patch:
        patch.setattr(boundary.module(module), name, lambda *_: touched.append("foreign"))
        with pytest.raises(boundary.source.BridgeError, match="retained cloth source"):
            witness.verify(boundary.context)
    assert touched == [] and boundary.calls == []


@pytest.mark.parametrize("attribute", ["__code__", "__defaults__", "__kwdefaults__"])
def test_inplace_function_fact_drift_is_not_rebased(boundary, monkeypatch, attribute):
    function = boundary.module("tools._cloth_cache_scope").bounded
    witness = snapshot(boundary)
    replacement = ((lambda *_: None).__code__ if attribute == "__code__" else
                   (object(),) if attribute == "__defaults__" else {"foreign": object()})
    with monkeypatch.context() as patch:
        patch.setattr(function, attribute, replacement)
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert boundary.calls == []


def test_keyword_dictionary_content_drift_and_nested_source_table_drift_refuse(boundary, monkeypatch):
    function = boundary.module("tools._cloth_cache_scope").bounded
    witness = snapshot(boundary)
    with monkeypatch.context() as patch:
        patch.setitem(function.__kwdefaults__, "field", "foreign")
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    table = boundary.module("tools._cloth_cache_scope").ATTRIBUTE_VALUES
    with monkeypatch.context() as patch:
        patch.setitem(table, "BOOLEAN", ("Foreign", "ForeignValue"))
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)


@pytest.mark.parametrize("name", ["state", "registry", "permissions", "checkpoints", "jobs", "request_id",
                                  "check_final_request", "check_final_job", "check_cancelled"])
def test_context_slot_rebinding_refuses_without_foreign_getters(boundary, monkeypatch, name):
    witness = snapshot(boundary)
    touched = []

    class Trap:
        def __getattribute__(self, name):
            touched.append(name)
            raise AssertionError(name)

    with monkeypatch.context() as patch:
        patch.setattr(boundary.context, name, Trap())
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert touched == []


@pytest.mark.parametrize("name", ["check_final_request", "check_final_job", "check_cancelled"])
def test_arbitrary_caller_callbacks_are_not_source_qualified(boundary, name):
    calls = []
    setattr(boundary.context, name, lambda: calls.append("foreign"))
    with pytest.raises(boundary.source.BridgeError):
        snapshot(boundary)
    assert calls == []


def test_class_slot_and_state_endpoint_replacement_refuse_before_getters(boundary, monkeypatch):
    witness = snapshot(boundary)
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(type(boundary.context), "state", property(lambda *_: calls.append("foreign")))
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    with monkeypatch.context() as patch:
        patch.setattr(boundary.context.state, "snapshot", lambda: calls.append("foreign"))
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert calls == []


def test_provider_source_mutation_is_detected_before_next_native_phase(boundary, monkeypatch):
    witness = snapshot(boundary)
    with monkeypatch.context() as patch:
        patch.setattr(boundary.context.permissions, "_source", lambda: {})
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert boundary.calls == []


def test_canonical_queue_endpoints_are_held_without_invoking_them(boundary, monkeypatch):
    owner = queued_context(boundary)
    witness = snapshot(boundary)
    owner._stop_requested = True
    boundary.context.request_lifecycle.rejected.set()
    assert witness.verify(boundary.context) is None
    with monkeypatch.context() as patch:
        patch.setattr(owner, "_lock", object())
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert boundary.calls == []


def test_final_queue_closure_rebinding_refuses_before_hook(boundary):
    queued_context(boundary)
    witness = snapshot(boundary)
    cell = boundary.context.check_final_request.__closure__[0]
    original = cell.cell_contents
    try:
        cell.cell_contents = object()
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    finally:
        cell.cell_contents = original


def test_scene_context_factory_is_native_shaped_and_never_executed(boundary, monkeypatch):
    jobs, runtime, executor = scene_context(boundary)
    witness = snapshot(boundary)
    assert witness.verify(boundary.context) is None
    with monkeypatch.context() as patch:
        patch.setattr(jobs.context_factory, "__code__", (lambda item: lambda: item)(None).__code__)
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    with monkeypatch.context() as patch:
        patch.setattr(runtime, "executor", object())
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert executor.jobs is jobs and boundary.calls == []


def test_wrong_context_class_and_instance_shadow_refuse_before_capture(boundary):
    calls = []
    with pytest.raises(boundary.source.BridgeError):
        boundary.source.capture_cloth_sources(SimpleNamespace())
    boundary.context.registry.get = lambda *_: calls.append("foreign")
    with pytest.raises(boundary.source.BridgeError):
        snapshot(boundary)
    assert calls == []


def test_held_verifier_bootstrap_detects_changed_class_entry_without_dispatch(boundary, monkeypatch):
    witness = snapshot(boundary)
    fact = tuple.__getitem__(witness, 7)
    function, code, namespace = fact[:3]
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(boundary.source.ClothSourceWitness, "verify", lambda *_: calls.append("foreign"))
        assert function.__code__ is code and function.__globals__ is namespace
        with pytest.raises(boundary.source.BridgeError):
            function(witness, boundary.context)
    assert calls == []


def test_inplace_module_globals_and_native_helper_bindings_refuse_without_calls(boundary, monkeypatch):
    witness = snapshot(boundary)
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(boundary.source.os, "open", lambda *_args, **_kwargs: calls.append("os.open"))
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    with monkeypatch.context() as patch:
        patch.setitem(vars(boundary.module("tools._cloth_cache_scope")), "new_source_binding", object())
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert calls == []


def test_foreign_namespace_key_refuses_before_custom_equality(boundary):
    witness = snapshot(boundary)
    calls = []

    class Foreign(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            calls.append("equality")
            raise AssertionError("foreign equality")

    namespace = vars(boundary.module("tools._cloth_cache_scope"))
    key = Foreign("new_foreign_binding")
    try:
        namespace[key] = object()
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    finally:
        namespace.pop(key)
    assert calls == []


@pytest.mark.parametrize("which", ["event", "queued"])
def test_stop_flag_replacement_refuses_before_truthiness(boundary, which):
    owner = queued_context(boundary)
    witness = snapshot(boundary)
    calls = []

    class Foreign:
        def __bool__(self):
            calls.append("truth")
            raise AssertionError("foreign truth")

    target, field = ((boundary.context.request_lifecycle.rejected, "_flag") if which == "event"
                     else (owner, "_stop_requested"))
    original = getattr(target, field)
    try:
        setattr(target, field, Foreign())
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    finally:
        setattr(target, field, original)
    assert calls == []


def test_actual_permission_provider_can_run_but_is_not_run_by_source_verifier(boundary):
    witness = snapshot(boundary)
    boundary.context.require(boundary.module("permissions").Permission.INSPECT_SCENE)
    assert boundary.calls == ["provider"]
    witness.verify(boundary.context)
    assert boundary.calls == ["provider"]


@pytest.mark.parametrize("module,name", [("io", "open"), ("contextlib", "contextmanager")])
def test_stdlib_entry_replacement_is_seen_before_use(boundary, monkeypatch, module, name):
    target = importlib.import_module(module)
    witness = snapshot(boundary)
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(target, name, lambda *_args, **_kwargs: calls.append("foreign"))
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert calls == []


def test_source_failure_does_not_claim_enclosing_operation_never_started(boundary, monkeypatch):
    witness = snapshot(boundary)
    with monkeypatch.context() as patch:
        patch.setitem(vars(boundary.module("tools._cloth_cache_scope")), "after_native_change", object())
        with pytest.raises(boundary.source.BridgeError) as caught:
            witness.verify(boundary.context)
    assert "execution_started" not in caught.value.context
    assert caught.value.context["source_verifier_invoked_blender"] is False


def test_scene_permission_view_holds_actual_service_endpoints(boundary, monkeypatch):
    authority = boundary.module("scene_job_authority")
    reservations = boundary.module("scene_job_reservations").SceneJobReservations(boundary.context.registry)
    boundary.context.permissions = authority.SceneJobPermissions(boundary.context.permissions, reservations)
    witness = snapshot(boundary)
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(reservations, "permission_turn", lambda: calls.append("foreign"))
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert calls == []


def test_registration_class_classification_never_reads_foreign_dunder_class(boundary, monkeypatch):
    calls = []

    class Foreign:
        @property
        def __class__(self):
            calls.append("foreign.__class__")
            raise AssertionError("unsafe isinstance classification")

    with monkeypatch.context() as patch:
        patch.setitem(vars(boundary.module("tools._cloth_cache_scope")), "unused_foreign_binding", Foreign())
        witness = snapshot(boundary)
        witness.verify(boundary.context)
    assert calls == []


@pytest.mark.parametrize("field", ["_tools", "_enabled_toolsets", "_scene_reservations"])
def test_registry_storage_rebinding_refuses_before_custom_dispatch(boundary, monkeypatch, field):
    witness = snapshot(boundary)
    calls = []

    class Foreign:
        def __getitem__(self, key):
            calls.append("getitem")
            raise AssertionError(key)

        def __iter__(self):
            calls.append("iter")
            raise AssertionError("iter")

    with monkeypatch.context() as patch:
        patch.setattr(boundary.context.registry, field, Foreign())
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert calls == []


@pytest.mark.parametrize("field", ["paused", "emergency_stopped", "connected_clients"])
def test_live_state_values_are_typed_before_control_truthiness(boundary, monkeypatch, field):
    witness = snapshot(boundary)
    calls = []

    class Foreign:
        def __bool__(self):
            calls.append("truth")
            raise AssertionError("truth")

    with monkeypatch.context() as patch:
        patch.setattr(boundary.context.state, field, Foreign())
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    assert calls == []


def test_real_pause_and_enabled_toolset_changes_remain_live_authority(boundary):
    witness = snapshot(boundary)
    boundary.context.state.paused = True
    boundary.context.registry._enabled_toolsets.clear()
    witness.verify(boundary.context)
    assert boundary.context.state.paused is True
    assert boundary.context.registry.enabled_toolsets == ()


def test_registered_metadata_slot_changes_do_not_become_new_intent(boundary):
    spec = boundary.context.registry.register("simulation.test", lambda *_: None, toolset="simulation")
    witness = snapshot(boundary)
    previous = spec.modifies
    try:
        object.__setattr__(spec, "modifies", True)
        with pytest.raises(boundary.source.BridgeError):
            witness.verify(boundary.context)
    finally:
        object.__setattr__(spec, "modifies", previous)


@pytest.mark.parametrize("field", ["app", "types", "types_getattr"])
def test_native_runtime_module_rebinding_refuses_before_following_values(boundary, monkeypatch, field):
    from types import ModuleType

    runtime = boundary.module("runtime")
    native = ModuleType("bpy")
    native.types = ModuleType("bpy.types")
    native.app = object()
    calls = []

    class Foreign:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError(name)

    with monkeypatch.context() as native_patch:
        native_patch.setattr(runtime, "bpy", native)
        witness = snapshot(boundary)
        with monkeypatch.context() as patch:
            if field == "types_getattr":
                patch.setattr(native.types, "__getattr__", lambda *_: calls.append("types_getattr"), raising=False)
            else:
                patch.setattr(native, field, Foreign())
            with pytest.raises(boundary.source.BridgeError):
                witness.verify(boundary.context)
    assert calls == []


def test_unknown_native_types_owner_refuses_without_getattr(boundary, monkeypatch):
    from types import ModuleType

    runtime = boundary.module("runtime")
    native = ModuleType("bpy")
    calls = []

    class Foreign:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError(name)

    native.types = Foreign()
    with monkeypatch.context() as patch:
        patch.setattr(runtime, "bpy", native)
        with pytest.raises(boundary.source.BridgeError):
            snapshot(boundary)
    assert calls == []


@pytest.mark.parametrize("where,field", [
    ("runtime", "executor"), ("runtime", "jobs"), ("executor", "glb_stage"),
    ("service", "runtime"), ("service", "state"), ("service", "store"),
])
def test_checked_factory_custom_data_descriptor_refuses_before_foreign_get(boundary, monkeypatch, where, field):
    _jobs, runtime, executor = scene_context(boundary)
    service = runtime.glb_stage
    owner = {"runtime": runtime, "executor": executor, "service": service}[where]
    calls = []
    class Foreign:
        def __get__(self, *_args):
            calls.append("get")
            raise AssertionError("foreign data descriptor")
        def __set__(self, *_args):
            calls.append("set")
    monkeypatch.setattr(type(owner), field, Foreign(), raising=False)
    with pytest.raises(boundary.source.BridgeError):
        snapshot(boundary)
    assert calls == [] and boundary.calls == []


@pytest.mark.parametrize("where,field", [
    ("runtime", "executor"), ("runtime", "_glb_stage_origin"), ("executor", "jobs"),
    ("executor", "permissions"), ("service", "runtime"), ("service", "state"),
    ("service", "registry"), ("service", "checkpoints"), ("service", "jobs"),
    ("service", "_executor_origin"), ("service", "_origins"),
])
def test_checked_factory_component_drift_is_not_recaptured(boundary, monkeypatch, where, field):
    _jobs, runtime, executor = scene_context(boundary)
    owner = {"runtime": runtime, "executor": executor, "service": runtime.glb_stage}[where]
    monkeypatch.setattr(owner, field, object())
    with pytest.raises(boundary.source.BridgeError):
        snapshot(boundary)
    assert boundary.calls == []


@pytest.mark.parametrize("change", ["helper", "helper_code", "factory_method", "dependency_code", "observer_method", "context_property"])
def test_checked_factory_preexisting_source_drift_refuses_before_foreign_dispatch(boundary, monkeypatch, change):
    _jobs, _runtime, executor = scene_context(boundary)
    glb = boundary.module("glb_stage_runtime")
    calls = []
    def foreign(*_args):
        calls.append("foreign")
        raise AssertionError("foreign checked factory")
    if change == "helper":
        monkeypatch.setattr(glb, "checked_executor_context", foreign)
    elif change == "helper_code":
        monkeypatch.setattr(glb.checked_executor_context, "__code__", (lambda *_args: None).__code__)
    elif change == "factory_method":
        monkeypatch.setattr(glb.GLBStageService, "check_context_factory", foreign)
    elif change == "dependency_code":
        monkeypatch.setattr(glb._check_protected_dependencies, "__code__", (lambda *_args: None).__code__)
    elif change == "observer_method":
        monkeypatch.setattr(boundary.module("glb_stage_protected_mesh").ProtectedMeshObserver, "capture_mesh", foreign)
    else:
        monkeypatch.setattr(type(executor), "context", property(foreign))
    with pytest.raises(boundary.source.BridgeError):
        snapshot(boundary)
    assert calls == [] and boundary.calls == []


@pytest.mark.parametrize("change", ["globals", "owner", "foreign_code", "defaults"])
def test_checked_factory_requires_exact_constructor_code_and_owner(boundary, change):
    jobs, runtime, _executor = scene_context(boundary)
    old = jobs.context_factory
    if change == "globals":
        jobs.context_factory = FunctionType(old.__code__, dict(old.__globals__), closure=old.__closure__)
    elif change == "owner":
        other = boundary.module("runtime").BridgeRuntime()
        jobs.context_factory = FunctionType(old.__code__, old.__globals__, closure=(closure(other),))
    elif change == "foreign_code":
        jobs.context_factory = lambda: runtime.executor.context
    else:
        jobs.context_factory = FunctionType(old.__code__, old.__globals__, argdefs=(None,), closure=old.__closure__)
    with pytest.raises(boundary.source.BridgeError):
        snapshot(boundary)
    assert boundary.calls == []


@pytest.mark.parametrize("kind,field", [("base", "_source"), ("wrapper", "base"), ("wrapper", "service")])
def test_permission_data_descriptors_refuse_before_provider_dispatch(boundary, monkeypatch, kind, field):
    manager = boundary.context.permissions
    if kind == "wrapper":
        service = boundary.module("scene_job_reservations").SceneJobReservations(boundary.context.registry)
        manager = boundary.module("scene_job_authority").SceneJobPermissions(manager, service)
        boundary.context.permissions = manager
    calls = []
    class Foreign:
        def __get__(self, *_args):
            calls.append("get")
            raise AssertionError("foreign permission data descriptor")
        def __set__(self, *_args):
            calls.append("set")
    monkeypatch.setattr(type(manager), field, Foreign(), raising=False)
    with pytest.raises(boundary.source.BridgeError):
        snapshot(boundary)
    assert calls == [] and boundary.calls == []


@pytest.mark.parametrize("field", ["BridgeRuntime", "_CANONICAL_RUNTIME_CLASS", "_RUNTIME_CONSTRUCTOR_CODE"])
def test_checked_factory_canonical_runtime_aliases_cannot_be_recaptured(boundary, monkeypatch, field):
    scene_context(boundary)
    runtime = boundary.module("runtime")
    monkeypatch.setattr(runtime, field, object())
    with pytest.raises(boundary.source.BridgeError):
        snapshot(boundary)
    assert boundary.calls == []


@pytest.mark.parametrize("change", ["helper_code", "helper_binding", "helper_defaults", "dependency_code", "context_property_inplace"])
def test_checked_factory_drift_before_first_source_import_is_not_adopted(change):
    code = r'''
import sys
sys.path.insert(0,"addon")
from blender_codex_bridge import jobs,glb_stage_runtime as glb
from blender_codex_bridge.errors import BridgeError
calls=[]
def foreign(*args):calls.append("foreign");raise AssertionError("foreign helper executed")
change=sys.argv[1]
if change=="helper_code":glb.checked_executor_context.__code__=foreign.__code__
elif change=="helper_binding":glb.checked_executor_context=foreign
elif change=="helper_defaults":glb.checked_executor_context.__defaults__=(None,)
elif change=="dependency_code":glb._check_protected_dependencies.__code__=foreign.__code__
else:property.__init__(glb._EXECUTOR_CONTEXT_PROPERTY,foreign)
try:
    from blender_codex_bridge.tools import _cloth_cache_source
except BridgeError as error:
    assert error.context["reason"]=="CLOTH_SOURCE_CHECKED_FACTORY_ORIGIN_CHANGED"
else:raise AssertionError("preexisting checked-helper mutation became original")
assert calls==[],calls
print("pre-import original checked-helper guard passed")
'''
    result = subprocess.run([sys.executable, "-B", "-c", code, change], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert "original checked-helper guard passed" in result.stdout
