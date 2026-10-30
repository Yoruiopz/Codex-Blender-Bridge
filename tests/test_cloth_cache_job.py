"""Native-shaped cloth intervals retain partial effects and stop between calls."""
from __future__ import annotations

import importlib
import math
import struct
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def cloth(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools._cloth_cache_job")
    effects = importlib.import_module(f"{addon_package}.scene_job_effects")
    env = NS(module=module, effects=effects, events=[], stopped=False, deny=False, hook=None,
             provider_hook=None, gravity=-9.81, source_vertex_offset=0., map_old=100, map_new=100,
             float_override=None, final_override=None, snapshot_reads=0, context_slot=1,
             native_bake_active=False, callback_context=(None,), negative_frames_allowed=False,
             preference_pointer=10, edit_pointer=11)
    def native(name):
        env.events.append(name)
        if env.hook:
            env.hook(name)
    class Cache:
        def __init__(self):
            self.frame_start, self.frame_end, self.frame_step, self.is_baked = 1, 3, 1, False
        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)
            if name.startswith("frame_") and getattr(env, "recording", False):
                native(name)
    env.cache = Cache()
    class Scene:
        def __setattr__(self, name, value):
            if name == "frame_float":
                value = struct.unpack("=f", struct.pack("=f", value))[0]
                if value < 0 and not env.negative_frames_allowed:
                    value = 0.
                integer = int(value)
                object.__setattr__(self, "frame_current", integer)
                object.__setattr__(self, "frame_subframe", struct.unpack("=f", struct.pack("=f", value-integer))[0])
                if getattr(env, "recording", False):
                    native("scene_frame_float_set")
                return
            if name == "frame_current" and value < 0 and not env.negative_frames_allowed:
                value = 0
            object.__setattr__(self, name, value)
            if name in {"frame_current", "frame_subframe"} and getattr(env, "recording", False):
                native("scene_" + name + "_set")
    env.scene = Scene()
    env.scene.frame_current, env.scene.frame_subframe, env.scene.name = 7, .25, "Target"
    def frame_set(frame, *, subframe):
        # Native frame_set passes double(frame)+double(subframe) to the float
        # BKE_scene_frame_set, then modf splits it. It cannot preserve every pair.
        combined = struct.unpack("=f", struct.pack("=f", float(frame) + subframe))[0]
        fraction, integer = math.modf(combined)
        object.__setattr__(env.scene, "frame_current", int(integer))
        object.__setattr__(env.scene, "frame_subframe", fraction)
        native("frame_set")
    env.scene.frame_set = frame_set
    env.obj = NS(name="Cloth", data=NS(vertices=[NS(co=(0., 0., 1.)), NS(co=(1., 0., 1.))],
        edges=[NS(vertices=(0, 1))], polygons=[NS(vertices=(0, 1))],
        loops=[NS(vertex_index=0, edge_index=0), NS(vertex_index=1, edge_index=0)]))
    def evaluated_get(_graph):
        native("evaluated_get")
        clock = module.scope.working_clock((env.scene.frame_current, env.scene.frame_subframe),
                                           module.scope.TimeInputs(env.map_old, env.map_new))
        z = env.gravity * float.fromhex(clock["frame_current_final"]) + env.source_vertex_offset
        return NS(data=NS(vertices=[NS(co=(0., 0., z)), NS(co=(1., 0., z))],
            edges=[NS(vertices=(0, 1))], polygons=[NS(vertices=(0, 1))],
            loops=[NS(vertex_index=0, edge_index=0), NS(vertex_index=1, edge_index=0)]))
    env.obj.evaluated_get = evaluated_get
    env.prepared, env.modifier = NS(scene=env.scene, obj=env.obj), object()
    def capture(_context, _bpy, _request):
        env.snapshot_reads += 1
        timing = module.scope.TimeInputs(env.map_old, env.map_new)
        clock = module.scope.working_clock((env.scene.frame_current, env.scene.frame_subframe), timing)
        if env.float_override is not None:
            clock["frame_float"] = env.float_override.hex()
        if env.final_override is not None:
            clock["frame_current_final"] = env.final_override.hex()
        assert not env.native_bake_active, "No clock snapshot is allowed inside synchronous native EXEC"
        snapshot = {"data": (env.gravity, env.source_vertex_offset, timing), "time_inputs": timing, "cloth": "settings", "layout": "layout",
             "clock_callback_context": env.callback_context if _request["action"] == "BAKE" else None,
             "negative_frame_policy": (env.preference_pointer, env.edit_pointer, env.negative_frames_allowed) if _request["action"] == "BAKE" else None,
             "context": (env.context_slot, 2, 3, 4, 5, 6, env.scene.frame_current, env.scene.frame_subframe.hex()),
             "owned": {"range": (env.cache.frame_start, env.cache.frame_end), "step": 1,
                       "baked": env.cache.is_baked, "frame": (env.scene.frame_current, env.scene.frame_subframe),
                       "clock": clock}}
        return (env.prepared, env.modifier, env.cache, snapshot,
                module.scope.digest({"scope": snapshot, "proposal": _request}))
    monkeypatch.setattr(module.scope, "capture", capture)
    def final(*_args):
        if env.stopped:
            raise module.BridgeError(module.ErrorCode.TIMEOUT, "Stopped fixture caller")
    monkeypatch.setattr(module, "check_final_mutation", final)
    def require(*_permissions):
        if env.provider_hook:
            hook, env.provider_hook = env.provider_hook, None
            hook()
        if env.deny:
            raise module.BridgeError(module.ErrorCode.PERMISSION_DENIED, "Revoked fixture grant")
    env.context = NS(require=require)
    class Operator:
        def __init__(self, action):
            self.action = action
        def poll(self):
            native("poll")
            return True
        def __call__(self, execution, **params):
            assert execution == "EXEC_DEFAULT"
            assert params == ({"bake": True} if self.action == "BAKE" else {})
            env.cache.is_baked = self.action == "BAKE"
            env.native_bake_active = self.action == "BAKE"
            try:
                native(self.action)
                return {"FINISHED"}
            finally:
                env.native_bake_active = False
    def graph():
        native("depsgraph_get")
        return object()
    env.bpy = NS(app=NS(build_hash=b"d13f752e3b9c", version=(5, 2, 2)),
        context=NS(temp_override=lambda **_: nullcontext(), evaluated_depsgraph_get=graph,
        view_layer=NS(update=lambda: native("view_layer_update"))),
        ops=NS(ptcache=NS(bake=Operator("BAKE"), free_bake=Operator("FREE"))))
    def driver(action="BAKE", start=1, end=3):
        params = {"object_name": "Cloth", "scene_name": "Target", "frame_start": start,
                  "frame_end": end, "action": action}
        params["expected_fingerprint"] = module.scope.preview(env.context, env.bpy, params)[-1]
        result = module.ClothCacheDriver(env.bpy, env.context, params)
        geometry = result._geometry
        def capture_geometry(evaluated):
            value = geometry(evaluated)
            native("geometry_capture")
            return value
        result._geometry = capture_geometry
        env.recording = True
        return result
    env.driver = driver
    return env


def run(cloth, driver):
    for _ in range(100):
        driver.advance(cloth.context)
        if driver.done:
            return driver.result
    pytest.fail("Bounded driver did not complete")


def test_bake_records_complete_geometry_at_shuffled_frames_and_restores_fractional_caller_time(cloth):
    driver = cloth.driver()
    result = run(cloth, driver)
    assert result["sample_frame_order"] == [3, 1, 2]
    assert result["frames_sampled"] == 3 and result["vertices_per_frame"] == 2
    assert result["caller_time_restored"] and (cloth.scene.frame_current, cloth.scene.frame_subframe) == (7, .25)
    assert all(len(sample["coordinates"]) == 2 and len(sample["loops"]) == 2 for sample in driver.samples)
    assert cloth.events[:5] == ["frame_start", "frame_end", "frame_step", "poll", "BAKE"]
    assert cloth.events[-3:] == ["scene_frame_current_set", "scene_frame_subframe_set", "view_layer_update"]
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["last_verified"]["operation"] == "view_layer_update"
    assert evidence["counts_by_operation"]["geometry_capture"] == {"entered": 3, "returned": 3}


@pytest.mark.parametrize("action", ["FREE", "INVALIDATE"])
def test_free_and_invalidate_do_not_evaluate_or_restore_time_and_make_no_memory_deletion_claim(cloth, action):
    cloth.cache.is_baked = True
    driver = cloth.driver(action)
    result = run(cloth, driver)
    assert result["native_memory_empty"] == result["cache_freshness"] == "NOT_ASSESSED"
    assert not result["all_requested_integer_frames_sampled"]
    assert (cloth.scene.frame_current, cloth.scene.frame_subframe) == (7, .25)
    assert cloth.events == (["poll", "FREE"] if action == "FREE" else ["frame_step"])
    assert cloth.cache.is_baked is (action == "INVALIDATE")


@pytest.mark.parametrize("boundary", range(23))
def test_stopped_caller_after_each_native_return_prevents_every_later_call_including_cleanup(cloth, boundary):
    driver = cloth.driver()
    def stop(_name):
        if len(cloth.events) == boundary+1:
            cloth.stopped = True
    cloth.hook = stop
    with pytest.raises(cloth.module.BridgeError) as caught:
        run(cloth, driver)
    assert caught.value.code == "TIMEOUT"
    retained = deepcopy(cloth.events)
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert sum(row["returned"] for row in evidence["counts_by_operation"].values()) >= 1
    with pytest.raises(cloth.module.BridgeError):
        driver.advance(cloth.context)
    assert cloth.events == retained and not driver.done


def test_permission_provider_drift_cannot_become_a_new_baseline(cloth):
    driver = cloth.driver()
    cloth.provider_hook = lambda: setattr(cloth, "gravity", 0.)
    with pytest.raises(cloth.module.BridgeError) as caught:
        driver.advance(cloth.context)
    assert caught.value.context["reason"] == "CLOTH_JOB_SCOPE_OR_CALLER_TIME_CHANGED"
    assert cloth.events == []


@pytest.mark.parametrize("when", ["poll", "BAKE", "frame_set", "depsgraph_get", "evaluated_get"])
def test_revocation_after_native_return_retains_call_and_prevents_next_native_boundary(cloth, when):
    driver = cloth.driver()
    cloth.hook = lambda name: setattr(cloth, "deny", True) if name == when else None
    with pytest.raises(cloth.module.BridgeError) as caught:
        run(cloth, driver)
    assert caught.value.code == "PERMISSION_DENIED"
    assert cloth.events[-1] == when


def test_unknown_native_outcome_keeps_entry_without_return_and_never_compensates(cloth):
    driver = cloth.driver()
    def fail(name):
        if name == "BAKE":
            raise RuntimeError("Native call changed data then failed")
    cloth.hook = fail
    with pytest.raises(RuntimeError):
        run(cloth, driver)
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["counts_by_operation"]["ptcache_bake_exec"] == {"entered": 1, "returned": 0}
    assert cloth.cache.is_baked and cloth.events[-1] == "BAKE"


def test_newer_manual_time_is_retained_without_automatic_caller_restore(cloth):
    driver = cloth.driver()
    for _ in range(7):
        driver.advance(cloth.context)
    cloth.scene.frame_current, cloth.scene.frame_subframe = 91, .5
    before = list(cloth.events)
    with pytest.raises(cloth.module.BridgeError):
        driver.advance(cloth.context)
    assert cloth.events == before and (cloth.scene.frame_current, cloth.scene.frame_subframe) == (91, .5)


def test_same_count_geometry_edit_changes_complete_sample_digest(cloth):
    first = run(cloth, cloth.driver())["complete_geometry_samples_sha256"]
    cloth.cache.is_baked = False
    cloth.source_vertex_offset = .125
    second = run(cloth, cloth.driver())["complete_geometry_samples_sha256"]
    assert first != second


def test_complete_evaluated_topology_must_match_source_even_when_counts_match(cloth):
    original = cloth.obj.evaluated_get
    def changed(graph):
        evaluated = original(graph)
        evaluated.data.polygons[0].vertices = (1, 0)
        return evaluated
    cloth.obj.evaluated_get = changed
    driver = cloth.driver()
    with pytest.raises(cloth.module.BridgeError, match="topology"):
        run(cloth, driver)
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["counts_by_operation"]["geometry_capture"] == {"entered": 1, "returned": 0}


def test_context_preparation_rejects_cloth_settings_drift_before_next_native_boundary(cloth, monkeypatch):
    module = cloth.module
    driver = object.__new__(module.ContextPreparationDriver)
    home, target, window, workspace, screen = object(), NS(frame_current=1, frame_subframe=0.), object(), object(), object()
    driver.bpy = NS(context=NS(window=window, mode="OBJECT", workspace=workspace, screen=screen, scene=home))
    driver.window, driver.scene, driver.home, driver.obj = window, target, home, object()
    driver.target_time_inputs = module.scope.TimeInputs(100, 100)
    driver.target_time = module.scope.working_clock((1, 0.), driver.target_time_inputs)
    monkeypatch.setattr(module.scope, "time_inputs", lambda *_: driver.target_time_inputs)
    monkeypatch.setattr(module.scope, "scene_clock", lambda *_: driver.target_time)
    driver.queued_workspace = False
    driver.expected_workspace, driver.expected_screen, driver.expected_scene = workspace, screen, home
    driver.initial_layout = (1, 2, 3, 4, 5, 6, 7)
    driver._data_with_expected_active = lambda: "frozen"
    driver.expected_cloth = module.scope.digest(("original", {"baked": False}))
    monkeypatch.setattr(module.scope, "layout", lambda _: driver.initial_layout)
    monkeypatch.setattr(module.scope, "static_data", lambda *_: "frozen")
    monkeypatch.setattr(module.scope, "cloth_state", lambda *_: (None, None, "changed", {"baked": False}))
    with pytest.raises(module.BridgeError) as caught:
        driver.check_after_read(cloth.context)
    assert caught.value.context["reason"] == "CLOTH_PREPARATION_SETTINGS_OR_CACHE_CHANGED"
    assert cloth.events == []


def test_private_cloth_prerequisites_preserve_existing_public_registration(addon_package):
    module = importlib.import_module(f"{addon_package}.tools.simulation")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry()
    module.register_tools(registry)
    # This integration carries private safety prerequisites. The donor's public
    # cloth job registration requires its own qualified caller and is not added.
    assert set(registry._tools) == {
        "simulation.inspect", "simulation.cloth_add", "simulation.configure", "simulation.cache",
    }
    preview = registry.get("simulation.inspect")
    assert not preview.modifies and {p.value for p in preview.permissions} == {"INSPECT_SCENE"}
    for name in ("simulation.cloth_add", "simulation.configure", "simulation.cache"):
        spec = registry.get(name)
        expected = {"EDIT_MESH", "EDIT_SCENE"}
        if name == "simulation.cache":
            expected.add("EDIT_ANIMATION")
        assert spec.modifies and {p.value for p in spec.permissions} == expected
    for name in ("simulation.cache_preview", "simulation.cache_context_prepare", "simulation.cache_job_start"):
        with pytest.raises(registry_module.BridgeError) as caught:
            registry.get(name)
        assert caught.value.code == "METHOD_NOT_FOUND"


def preparation_at_workspace_request(cloth):
    module = cloth.module
    driver = object.__new__(module.ContextPreparationDriver)
    source, destination, screen, home = object(), object(), object(), object()
    class Window:
        requested = None
        workspace = source
        def __setattr__(self, key, value):
            if key == "workspace":
                self.requested = value
                cloth.events.append("workspace_request")
            else:
                object.__setattr__(self, key, value)
    driver.window, driver.workspace = Window(), destination
    driver.home, driver.destination_screens = home, (screen,)
    driver.bpy = NS(context=NS(workspace=source, screen=object(), scene=home))
    driver.expected_workspace, driver.expected_screen, driver.expected_scene = source, driver.bpy.context.screen, home
    driver.queued_workspace, driver.index, driver.phase, driver.done = False, 3, "workspace_request", False
    driver.check_after_read = lambda _context: None
    driver.native_effects = cloth.effects.SceneNativeEffects(tuple(
        module._phase("phase_" + str(index), "window_workspace_set" if index == 3 else "workspace_completion_observe",
                      deferred=index == 3) for index in range(8)), profile=cloth.effects.CLOTH_PROFILE)
    return driver, destination, screen, home


def test_queued_workspace_request_is_not_completion_and_stop_retains_unknown_effect_without_inverse(cloth):
    driver, destination, _screen, _home = preparation_at_workspace_request(cloth)
    driver.advance(cloth.context)
    assert driver.window.requested is destination and driver.bpy.context.workspace is not destination
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["deferred_native_effects"]["completion_unknown"] == 1
    cloth.stopped = True
    with pytest.raises(cloth.module.BridgeError):
        driver.advance(cloth.context)
    assert cloth.events == ["workspace_request"]
    assert cloth.effects.snapshot_native_effects(driver.native_effects)["deferred_native_effects"]["completion_unknown"] == 1


def test_workspace_completion_requires_a_later_turn_and_exact_screen_scene_window(cloth):
    driver, destination, screen, home = preparation_at_workspace_request(cloth)
    driver.advance(cloth.context)
    pending = driver.advance(cloth.context)
    assert pending["completed"] == 4 and driver.index == 4
    driver.bpy.context.workspace, driver.bpy.context.screen = destination, screen
    object.__setattr__(driver.window, "workspace", destination)
    driver.window.screen = screen
    driver.advance(cloth.context)
    assert driver.bpy.context.scene is home and driver.index == 5
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["deferred_native_effects"]["completion_verified"] == 1
    assert evidence["deferred_native_effects"]["completion_unknown"] == 0
    assert cloth.events == ["workspace_request"]


@pytest.mark.parametrize('mapping',[(100,200),(200,100),(899,7)])
def test_mapped_clock_advancement_samples_expected_playback_and_restores_exact_clock(cloth,mapping):
    cloth.map_old,cloth.map_new=mapping
    driver=cloth.driver()
    expected=cloth.module.scope.working_clock((7,.25),cloth.module.scope.TimeInputs(*mapping))
    result=run(cloth,driver)
    assert result['initial_caller_clock']==result['verified_final_clock']==expected
    assert result['immutable_scene_time_inputs']=={'frame_map_old':mapping[0],'frame_map_new':mapping[1]}
    assert result['clock_comparison']=='EXACT_SOURCE_FLOAT32_NO_TOLERANCE'
    assert result['native_bake_temporarily_forces_frame_length_one'] is True
    assert len(result['sample_clock_values'])==3
    for geometry,record in zip(driver.samples,result['sample_clock_values'],strict=True):
        clock=cloth.module.scope.working_clock((geometry['frame'],0.),cloth.module.scope.TimeInputs(*mapping))
        assert record=={'requested_frame':geometry['frame'],'clock':clock}
        assert geometry['coordinates'][0][2]==cloth.gravity*float.fromhex(clock['frame_current_final'])


def test_changed_mapping_makes_actual_start_preview_stale_before_any_native_write(cloth):
    module=cloth.module
    params={'object_name':'Cloth','scene_name':'Target','frame_start':1,'frame_end':3,'action':'BAKE'}
    fingerprint=module.scope.preview(cloth.context,cloth.bpy,params)[-1]
    cloth.map_new=200
    with pytest.raises(module.BridgeError,match='stale'):
        module.ClothCacheDriver(cloth.bpy,cloth.context,{**params,'expected_fingerprint':fingerprint})
    assert cloth.events==[]


@pytest.mark.parametrize('change',['mapping','raw_time','raw_float','final','context','mixed'])
def test_manual_clock_or_immutable_input_drift_before_write_never_becomes_a_baseline(cloth,change):
    driver=cloth.driver()
    if change in {'mapping','mixed'}:
        cloth.map_new=200
    if change in {'raw_time','mixed'}:
        object.__setattr__(cloth.scene, 'frame_current', 91)
        object.__setattr__(cloth.scene, 'frame_subframe', .5)
    if change=='raw_float':
        cloth.float_override=7.250000476837158
    if change=='final':
        cloth.final_override=7.250000476837158
    if change in {'context','mixed'}:
        cloth.context_slot=99
    with pytest.raises(cloth.module.BridgeError):
        driver.advance(cloth.context)
    assert cloth.events==[] and not driver.done


@pytest.mark.parametrize('boundary',['BAKE','frame_set','view_layer_update','depsgraph_get','evaluated_get'])
def test_manual_mapping_drift_after_native_return_stops_without_later_calls_or_restore(cloth,boundary):
    driver=cloth.driver()
    cloth.hook=lambda name:setattr(cloth,'map_new',200) if name==boundary else None
    with pytest.raises(cloth.module.BridgeError):
        run(cloth,driver)
    events=list(cloth.events)
    assert events[-1]==boundary and cloth.map_new==200
    with pytest.raises(cloth.module.BridgeError):
        driver.advance(cloth.context)
    assert cloth.events==events


@pytest.mark.parametrize('authority',['stop','permission'])
def test_authority_failure_with_mixed_clock_changes_never_peeks_at_native_clock_after_stop(cloth,authority):
    driver=cloth.driver()
    before=cloth.snapshot_reads
    cloth.map_new,cloth.context_slot,cloth.final_override=200,99,123.
    setattr(cloth,'stopped' if authority=='stop' else 'deny',True)
    with pytest.raises(cloth.module.BridgeError) as failure:
        driver.advance(cloth.context)
    assert failure.value.code==('TIMEOUT' if authority=='stop' else 'PERMISSION_DENIED')
    assert cloth.snapshot_reads==before and cloth.events==[]


def test_synchronous_bake_clock_is_not_sampled_until_native_return(cloth):
    cloth.map_new=200
    driver=cloth.driver()
    observations=[]
    cloth.hook=lambda name:observations.append(cloth.native_bake_active) if name=='BAKE' else None
    result=run(cloth,driver)
    assert observations==[True]
    assert result['verified_final_clock']==result['initial_caller_clock']


@pytest.mark.parametrize("frame,subframe", [
    (7, struct.unpack("=f", struct.pack("=f", .1))[0]),
    (1048574, .0312500037252903), (-100, .375), (0, -0.), (7, 1.),
    (-1048574, .0312500037252903), (1048574, 1.),
])
def test_raw_rna_restore_preserves_the_independent_float32_pair(cloth, frame, subframe):
    object.__setattr__(cloth.scene, "frame_current", frame)
    object.__setattr__(cloth.scene, "frame_subframe", subframe)
    original = (frame, subframe.hex())
    driver = cloth.driver()
    result = run(cloth, driver)
    assert (cloth.scene.frame_current, cloth.scene.frame_subframe.hex()) == original
    assert result["initial_caller_clock"] == result["verified_final_clock"]
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    frames = 4 if frame < 0 else 3
    raw_integer = 0 if frame < 0 else 1
    assert evidence["counts_by_operation"]["frame_set"] == {"entered": frames, "returned": frames}
    assert evidence["counts_by_operation"]["scene_frame_current_set"] == {"entered": raw_integer, "returned": raw_integer}
    assert evidence["counts_by_operation"]["scene_frame_subframe_set"] == {"entered": 1, "returned": 1}
    assert cloth.events[-3:] == ["frame_set" if frame < 0 else "scene_frame_current_set",
                                "scene_frame_subframe_set", "view_layer_update"]


def test_source_shaped_frame_set_cannot_restore_a_large_fractional_pair(cloth):
    pair = (1048574, .0312500037252903)
    cloth.scene.frame_set(pair[0], subframe=pair[1])
    assert (cloth.scene.frame_current, cloth.scene.frame_subframe) != pair
    assert cloth.scene.frame_subframe == .0625


@pytest.mark.parametrize("boundary", ["scene_frame_current_set", "scene_frame_subframe_set"])
@pytest.mark.parametrize("authority", ["stop", "permission"])
def test_raw_restore_stop_keeps_exact_returned_prefix_without_native_reinspection(cloth, boundary, authority):
    driver = cloth.driver()
    reads_after_callback = []
    def change(name):
        if name == boundary:
            cloth.map_new, cloth.callback_context = 200, (99, "VIEW_3D")
            setattr(cloth, "stopped" if authority == "stop" else "deny", True)
            reads_after_callback.append(cloth.snapshot_reads)
    cloth.hook = change
    with pytest.raises(cloth.module.BridgeError) as caught:
        run(cloth, driver)
    assert caught.value.code == ("TIMEOUT" if authority == "stop" else "PERMISSION_DENIED")
    assert cloth.events[-1] == boundary and cloth.snapshot_reads == reads_after_callback[0]
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["last_entered"]["operation"] == evidence["last_returned"]["operation"] == boundary
    assert evidence["last_verified"]["operation"] == (
        "geometry_capture" if boundary == "scene_frame_current_set" else "scene_frame_current_set")
    retained = list(cloth.events)
    with pytest.raises(cloth.module.BridgeError):
        driver.advance(cloth.context)
    assert cloth.events == retained and cloth.snapshot_reads == reads_after_callback[0]


@pytest.mark.parametrize("boundary", ["scene_frame_current_set", "scene_frame_subframe_set"])
@pytest.mark.parametrize("change", ["mapping", "manual_time", "callback_context", "context"])
def test_raw_restore_drift_is_never_adopted_after_the_selected_setter(cloth, boundary, change):
    driver = cloth.driver()
    def alter(name):
        if name != boundary:
            return
        if change == "mapping":
            cloth.map_new = 200
        elif change == "manual_time":
            object.__setattr__(cloth.scene, "frame_current", 91)
            object.__setattr__(cloth.scene, "frame_subframe", .5)
        elif change == "callback_context":
            cloth.callback_context = (99, "VIEW_3D")
        else:
            cloth.context_slot = 99
    cloth.hook = alter
    with pytest.raises(cloth.module.BridgeError):
        run(cloth, driver)
    retained = list(cloth.events)
    assert retained[-1] == boundary
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["last_returned"]["operation"] == boundary
    assert evidence["last_verified"]["operation"] == (
        "geometry_capture" if boundary == "scene_frame_current_set" else "scene_frame_current_set")
    with pytest.raises(cloth.module.BridgeError):
        driver.advance(cloth.context)
    assert cloth.events == retained
    if change == "manual_time":
        assert (cloth.scene.frame_current, cloth.scene.frame_subframe) == (91, .5)


@pytest.mark.parametrize("boundary", ["scene_frame_current_set", "scene_frame_subframe_set"])
def test_failed_raw_setter_retains_entered_but_unreturned_effect(cloth, boundary):
    driver = cloth.driver()
    def fail(name):
        if name == boundary:
            raise RuntimeError("Raw Scene setter updated its field before failing")
    cloth.hook = fail
    with pytest.raises(RuntimeError):
        run(cloth, driver)
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["counts_by_operation"][boundary] == {"entered": 1, "returned": 0}
    assert evidence["last_entered"]["operation"] == boundary
    assert evidence["last_returned"]["operation"] == (
        "geometry_capture" if boundary == "scene_frame_current_set" else "scene_frame_current_set")
    assert cloth.events[-1] == boundary and not driver.done


@pytest.mark.parametrize("drift", ["mapping", "manual_time", "callback_context"])
def test_permission_callback_drift_before_raw_restore_cannot_authorize_its_first_setter(cloth, drift):
    driver = cloth.driver()
    while driver.phase != "restore_caller_frame":
        driver.advance(cloth.context)
    prefix = list(cloth.events)
    def change():
        if drift == "mapping":
            cloth.map_new = 200
        elif drift == "manual_time":
            object.__setattr__(cloth.scene, "frame_current", 91)
        else:
            cloth.callback_context = (99, "VIEW_3D")
    cloth.provider_hook = change
    with pytest.raises(cloth.module.BridgeError):
        driver.advance(cloth.context)
    assert cloth.events == prefix
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["counts_by_operation"]["scene_frame_current_set"] == {"entered": 0, "returned": 0}
    assert evidence["last_verified"]["operation"] == "geometry_capture"


def test_negative_integer_restore_bypasses_preference_clamp_and_retains_signed_zero_stop_prefix(cloth):
    assert cloth.negative_frames_allowed is False
    object.__setattr__(cloth.scene, "frame_current", -100)
    object.__setattr__(cloth.scene, "frame_subframe", .375)
    driver = cloth.driver()
    while driver.phase != "restore_caller_frame":
        driver.advance(cloth.context)
    cloth.hook = lambda _name: setattr(cloth, "stopped", True)
    with pytest.raises(cloth.module.BridgeError):
        driver.advance(cloth.context)
    assert cloth.scene.frame_current == -100 and cloth.scene.frame_subframe.hex() == (-0.).hex()
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["last_returned"]["operation"] == "frame_set"
    assert evidence["last_returned"]["target"] == [-100, -0.]
    assert evidence["last_verified"]["operation"] == "geometry_capture"
    assert evidence["counts_by_operation"]["scene_frame_subframe_set"] == {"entered": 0, "returned": 0}


@pytest.mark.parametrize("allowed,frame,subframe,operation", [
    (True, -2, -.625, "scene_frame_float_set"),
    (False, -2, -.625, "frame_set"),
    (True, 0, -float.fromhex("0x1p-149"), "scene_frame_float_set"),
    (True, -1048573, -.9375, "scene_frame_float_set"),
])
def test_negative_native_clock_restoration_matches_the_exact_original_pair(cloth, allowed, frame, subframe, operation):
    cloth.negative_frames_allowed = allowed
    object.__setattr__(cloth.scene, "frame_current", frame)
    object.__setattr__(cloth.scene, "frame_subframe", subframe)
    driver = cloth.driver()
    result = run(cloth, driver)
    assert (cloth.scene.frame_current, cloth.scene.frame_subframe.hex()) == (frame, subframe.hex())
    assert result["initial_caller_clock"] == result["verified_final_clock"]
    assert result["caller_time_restoration_operations"] == (operation,)
    assert cloth.events[-2:] == [operation, "view_layer_update"]
    assert result["negative_frame_policy"] == (10, 11, allowed)


def test_tiny_negative_clock_with_clamping_policy_refuses_before_any_cache_write(cloth):
    object.__setattr__(cloth.scene, "frame_current", 0)
    object.__setattr__(cloth.scene, "frame_subframe", -float.fromhex("0x1p-149"))
    with pytest.raises(cloth.module.BridgeError):
        cloth.driver()
    assert cloth.events == []


@pytest.mark.parametrize("change", ["bit", "preferences_pointer", "edit_pointer", "stop", "permission"])
def test_negative_float_restore_never_adopts_a_changed_policy_or_authority_after_return(cloth, change):
    cloth.negative_frames_allowed = True
    object.__setattr__(cloth.scene, "frame_current", -2)
    object.__setattr__(cloth.scene, "frame_subframe", -.625)
    driver = cloth.driver()
    def alter(name):
        if name != "scene_frame_float_set":
            return
        if change == "bit":
            cloth.negative_frames_allowed = False
        elif change == "preferences_pointer":
            cloth.preference_pointer = 99
        elif change == "edit_pointer":
            cloth.edit_pointer = 99
        else:
            setattr(cloth, "stopped" if change == "stop" else "deny", True)
    cloth.hook = alter
    with pytest.raises(cloth.module.BridgeError):
        run(cloth, driver)
    prefix = list(cloth.events)
    assert prefix[-1] == "scene_frame_float_set"
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["last_returned"]["operation"] == "scene_frame_float_set"
    assert evidence["last_verified"]["operation"] == "geometry_capture"
    with pytest.raises(cloth.module.BridgeError):
        driver.advance(cloth.context)
    assert cloth.events == prefix


def test_negative_float_setter_failure_keeps_entered_unknown_effect_and_no_later_update(cloth):
    cloth.negative_frames_allowed = True
    object.__setattr__(cloth.scene, "frame_current", -2)
    object.__setattr__(cloth.scene, "frame_subframe", -.625)
    driver = cloth.driver()
    def fail(name):
        if name == "scene_frame_float_set":
            raise RuntimeError("Combined clock changed before a failed return")
    cloth.hook = fail
    with pytest.raises(RuntimeError):
        run(cloth, driver)
    evidence = cloth.effects.snapshot_native_effects(driver.native_effects)
    assert evidence["counts_by_operation"]["scene_frame_float_set"] == {"entered": 1, "returned": 0}
    assert evidence["last_entered"]["operation"] == "scene_frame_float_set"
    assert evidence["last_returned"]["operation"] == "geometry_capture"
    assert cloth.events[-1] == "scene_frame_float_set"
