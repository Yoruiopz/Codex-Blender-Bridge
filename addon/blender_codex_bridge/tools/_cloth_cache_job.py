"""Explicit context preparation and guarded cloth phases on the Scene scheduler.

Every selected native interval has preallocated entry/return facts. Stopping
retains them and performs no inverse, native cleanup or late context restoration.
The synchronous EXEC bake is non-preemptible once entered.
"""
from __future__ import annotations

import math
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..scene_job_effects import CLOTH_PROFILE, NativeCallPlan, NativePhasePlan, SceneNativeEffects
from ..scene_job_reservations import TURN_METHOD
from ..task_plans import get_task_plans
from ..tool_registry import check_final_mutation
from ..utils import reject_unknown_params
from . import _cloth_cache_scope as scope
from . import _cloth_scene_consumers as roles

PREPARE_PERMISSIONS = (Permission.EDIT_SCENE, Permission.EDIT_ANIMATION, Permission.INSPECT_SCENE)
CACHE_PERMISSIONS = (Permission.EDIT_MESH, *PREPARE_PERMISSIONS)


def _phase(name: str, operation: str, target: Any = None, *, deferred: bool = False) -> NativePhasePlan:
    return NativePhasePlan(name, (NativeCallPlan(operation, target=target, completion_deferred=deferred),))


class _Driver:
    def _final(self, context):
        check_final_mutation(context, TURN_METHOD)

    def _check(self, context):
        self._final(context)
        context.require(*self.required_permissions)
        self._final(context)
        self.check_after_read(context)
        self._final(context)

    def _call(self, context, bits, callback):
        self._check(context)
        bits.entered = True
        result = callback()
        bits.returned = True
        self._final(context)
        context.require(*self.required_permissions)
        self._final(context)
        return result

    @staticmethod
    def _verified(row, index=0):
        # SceneNativeEffects validates this exact typed cell without a driver.
        row.last_verified.call_index = index
        row.verified = True

    def native_push_delegates(self):
        return ()

    def after_native_push(self):
        # Explicit same-value authentication establishes roles independently.
        # A checkpoint push cannot adopt an observed reference baseline.
        return None


class ContextPreparationDriver(_Driver):
    kind = "simulation.cloth_context_preparation"
    required_permissions = PREPARE_PERMISSIONS

    def __init__(self, bpy, context, params):
        reject_unknown_params(params, scope.PREPARE_FIELDS)
        scope.time_limit(params)
        self.bpy = bpy
        names = {field: scope.name(params.get(field), field) for field in
                 ("object_name", "scene_name", "home_scene_name", "workspace_name", "home_empty_name", "target_empty_name")}
        for field in ("expected_home_active_object_name", "expected_target_active_object_name"):
            if field not in params:
                raise invalid_argument(field + " is required, including explicit null intent.")
            names[field] = scope.name(params[field], field, nullable=True)
        self.scene, self.home = bpy.data.scenes.get(names["scene_name"]), bpy.data.scenes.get(names["home_scene_name"])
        self.obj = bpy.data.objects.get(names["object_name"])
        self.home_empty, self.empty = bpy.data.objects.get(names["home_empty_name"]), bpy.data.objects.get(names["target_empty_name"])
        self.workspace = bpy.data.workspaces.get(names["workspace_name"])
        if any(value is None for value in (self.scene, self.home, self.obj, self.home_empty, self.empty, self.workspace)):
            raise invalid_argument("Every preparation Scene, workspace, Object and Empty must already exist.")
        if self.scene is self.home or self.home_empty is self.empty:
            raise invalid_argument("Preparation requires distinct target/home Scenes and existing plain Empties.")
        self.label = "Prepare cloth context " + self.scene.name
        self.source_workspace, self.window = bpy.context.workspace, bpy.context.window
        self.source_screen = bpy.context.screen
        self.destination_screens = scope.bounded(self.workspace.screens, 1)
        if len(self.destination_screens) != 1 or self.workspace is self.source_workspace:
            raise scope.refuse("CLOTH_DISTINCT_SINGLE_LAYOUT_WORKSPACE_REQUIRED")
        if (bpy.context.scene is not self.home or self.window.scene is not self.home or bpy.context.mode != "OBJECT"
                or self.source_workspace.object_mode != "OBJECT" or self.workspace.object_mode != "OBJECT"):
            raise scope.refuse("CLOTH_PREPARATION_HOME_CONTEXT_REQUIRED")
        for scene, empty in ((self.home, self.home_empty), (self.scene, self.empty)):
            if empty not in scope.bounded(scene.objects, scope.MAX_OBJECTS) or scope.read(bpy, empty, "type", "ENUM") != "EMPTY":
                raise scope.refuse("CLOTH_EXISTING_PLAIN_EMPTY_REQUIRED")
            scope.object_state(bpy, empty)
        self.home_layer, self.target_layer = self.home.view_layers[0], self.scene.view_layers[0]
        self.original_home_active, self.original_target_active = self.home_layer.objects.active, self.target_layer.objects.active
        for field, actual in (("expected_home_active_object_name", self.original_home_active),
                              ("expected_target_active_object_name", self.original_target_active)):
            if (None if actual is None else actual.name) != names[field]:
                raise invalid_argument("Preparation active-Object compare-and-swap intent is stale.")
        _modifier, _cache, cloth_authored, cloth_owned = scope.cloth_state(bpy, self.obj)
        self.expected_cloth = scope.digest((cloth_authored, cloth_owned))
        self.expected_data = scope.static_data(bpy, self.scene, self.home, self.obj)
        self.target_time_inputs = scope.time_inputs(bpy, self.scene)
        self.target_time = scope.scene_clock(bpy, self.scene, self.target_time_inputs)
        if set(scope.bounded(self.scene.objects, 2)) != {self.empty, self.obj}:
            raise scope.refuse("CLOTH_TARGET_SCENE_OBJECTS_UNSUPPORTED")
        self.initial_layout = scope.layout(bpy)
        self.expected_home_active, self.expected_target_active = self.original_home_active, self.original_target_active
        self.expected_workspace, self.expected_screen, self.expected_scene = self.source_workspace, self.source_screen, self.home
        self.queued_workspace = False
        self.authenticated = {}
        self.particle_values = {}
        for scene in (self.home, self.scene):
            particle = roles._particle_settings(bpy, scene)[1]
            self.particle_values[scene.name] = scope.read(bpy, particle, "show_particles", "BOOLEAN")
        plans = (
            _phase("home_active_empty", "active_object_set", scope.token(self.home_empty)),
            _phase("home_particle_role", "particle_role_authenticate", scope.token(self.home)),
            _phase("home_active_restore", "active_object_set", scope.token(self.original_home_active)),
            _phase("workspace_request", "window_workspace_set", scope.token(self.workspace), deferred=True),
            _phase("workspace_completion", "workspace_completion_observe", scope.token(self.workspace)),
            _phase("target_scene", "window_scene_set", scope.token(self.scene)),
            _phase("target_active_empty", "active_object_set", scope.token(self.empty)),
            _phase("target_particle_role", "particle_role_authenticate", scope.token(self.scene)),
        )
        self.native_effects = SceneNativeEffects(plans, profile=CLOTH_PROFILE)
        self.index, self.done, self.result = 0, False, None
        self.phase = plans[0].phase

    def _data_with_expected_active(self):
        # Active slots are explicit context intent; all other projected authored
        # data and selection stay exactly frozen, including both Scene times.
        rows = list(self.expected_data)
        for index, active in ((2, self.expected_home_active), (3, self.expected_target_active)):
            row = list(rows[index])
            row[-2] = scope.token(active)
            rows[index] = tuple(row)
        return tuple(rows)

    def check_after_read(self, context):
        bpy = self.bpy
        if bpy.context.window is not self.window or bpy.context.mode != "OBJECT":
            raise scope.refuse("CLOTH_PREPARATION_CONTEXT_CHANGED")
        if (scope.time_inputs(bpy, self.scene) != self.target_time_inputs
                or scope.digest(scope.scene_clock(bpy, self.scene, self.target_time_inputs)) != scope.digest(self.target_time)):
            raise scope.refuse("CLOTH_PREPARATION_TARGET_TIME_CHANGED")
        current = (bpy.context.workspace, bpy.context.screen, bpy.context.scene)
        expected = (self.expected_workspace, self.expected_screen, self.expected_scene)
        if self.queued_workspace:
            allowed = (expected, (self.workspace, self.destination_screens[0], self.home))
            if current not in allowed:
                raise scope.refuse("CLOTH_WORKSPACE_COMPLETION_CONTEXT_CHANGED")
        elif current != expected:
            raise scope.refuse("CLOTH_PREPARATION_CONTEXT_CHANGED")
        layout = scope.layout(bpy)
        if layout[:4] != self.initial_layout[:4] or layout[6:] != self.initial_layout[6:]:
            raise scope.refuse("CLOTH_PREPARATION_LAYOUT_CHANGED")
        if scope.digest(scope.static_data(bpy, self.scene, self.home, self.obj)) != scope.digest(self._data_with_expected_active()):
            raise scope.refuse("CLOTH_PREPARATION_AUTHORED_OR_SELECTION_CHANGED")
        _modifier, _cache, authored, owned = scope.cloth_state(bpy, self.obj)
        if scope.digest((authored, owned)) != self.expected_cloth:
            raise scope.refuse("CLOTH_PREPARATION_SETTINGS_OR_CACHE_CHANGED")
        for scene, empty in self.authenticated.values():
            particle = roles._particle_settings(bpy, scene)[1]
            if (scope.read(bpy, particle, "object", "POINTER") is not empty
                    or scope.read(bpy, particle, "show_particles", "BOOLEAN") is not self.particle_values[scene.name]):
                raise scope.refuse("CLOTH_PREPARATION_PARTICLE_ROLE_CHANGED")

    def _authenticate(self, context, scene, empty, bits):
        particle = roles._particle_settings(self.bpy, scene)[1]
        roles._particle_field(self.bpy, particle, "ParticleEdit", "show_particles", "BOOLEAN", readonly=False)
        before = self.particle_values[scene.name]
        if self.bpy.context.scene is not scene or self.bpy.context.view_layer.objects.active is not empty:
            raise scope.refuse("CLOTH_PARTICLE_AUTHENTICATION_CONTEXT_CHANGED")
        self._call(context, bits, lambda: setattr(particle, "show_particles", before))
        # Source-inferred hidden Scene assignment, independently visible Object
        # pointer and Boolean readback. Never infer the Scene role from counts.
        self.authenticated[scene.name] = (scene, empty)
        if scope.read(self.bpy, particle, "object", "POINTER") is not empty:
            raise scope.refuse("CLOTH_PARTICLE_AUTHENTICATION_UNVERIFIED")

    def _complete(self, context):
        self._check(context)
        bpy = self.bpy
        declarations = [roles.Role(scope.token(bpy.context.window_manager), "window.scene", scope.token(self.scene)),
            roles.Role(scope.token(bpy.context.window_manager), "window.unpinned_scene", scope.token(self.home)),
            roles.Role(scope.token(self.home), "particle.scene", scope.token(self.home)),
            roles.Role(scope.token(self.scene), "particle.scene", scope.token(self.scene))]
        if roles.profile(bpy)[1][:2] == (5, 2):
            for workspace in scope.bounded(bpy.data.workspaces, 16):
                selected = scope.read(bpy, workspace, "sequencer_scene", "POINTER")
                if selected is not None:
                    if selected not in (self.home, self.scene):
                        raise scope.refuse("CLOTH_WORKSPACE_SCENE_DEPENDENCY_UNSUPPORTED")
                    declarations.append(roles.Role(scope.token(workspace), "workspace.sequencer_scene", scope.token(selected)))
        plan = roles.DeclaredRoles(roles.profile(bpy), (scope.token(self.home), scope.token(self.scene)), tuple(declarations),
            ((scope.token(self.home), 1), (scope.token(self.scene), 1)), roles.context(bpy))
        roles.verify(bpy, plan, (self.home, self.scene))
        self._final(context)
        store = get_task_plans(context.state)
        prepared = scope.PreparedContext(context.state, store, store.evidence_epoch,
            context.jobs.active, self.scene, self.home, self.obj, self.empty, self.home_empty, plan, scope.layout(bpy))
        scope.consumers(bpy, prepared)
        scope.retain_prepared(prepared)
        self.result = {**scope.observation_limits(bpy),
            "scene": self.scene.name, "home_scene": self.home.name, "object": self.obj.name,
            "workspace": self.workspace.name, "target_active_object": self.empty.name,
            "home_active_selection_and_projected_authored_state_preserved": True,
            "target_context_intentionally_retained": True, "same_value_particle_role_updates": 2,
            "previous_latent_particle_scene_unobserved": True,
            "workspace_change_completion_verified": True, "frame_set_calls": 0,
            "native_notifications_may_remain": True, "project_saved": False, "profile": scope.PROFILE}
        self.done, self.phase = True, "complete"

    def advance(self, context):
        if self.index == len(self.native_effects.plans):
            self._complete(context)
        else:
            row = self.native_effects.rows[self.index]
            bits = row.calls[0]
            self._check(context)
            if self.index in (0, 2, 6):
                layer = self.target_layer if self.index == 6 else self.home_layer
                wanted = self.empty if self.index == 6 else self.home_empty if self.index == 0 else self.original_home_active
                self._call(context, bits, lambda: setattr(layer.objects, "active", wanted))
                if self.index == 6:
                    self.expected_target_active = wanted
                else:
                    self.expected_home_active = wanted
            elif self.index in (1, 7):
                scene, empty = (self.home, self.home_empty) if self.index == 1 else (self.scene, self.empty)
                self._authenticate(context, scene, empty, bits)
            elif self.index == 3:
                self._call(context, bits, lambda: setattr(self.window, "workspace", self.workspace))
                self.queued_workspace = True
            elif self.index == 4:
                # A later timer turn proves the queued notifier actually ran.
                if self.bpy.context.workspace is not self.workspace:
                    return {"phase": self.phase, "completed": self.index, "total": 9}
                bits.entered = True
                if (self.bpy.context.screen is not self.destination_screens[0] or self.bpy.context.scene is not self.home
                        or self.window.workspace is not self.workspace or self.window.screen is not self.destination_screens[0]):
                    raise scope.refuse("CLOTH_WORKSPACE_COMPLETION_UNVERIFIED")
                bits.returned = True
                self.native_effects.rows[3].calls[0].completion_verified = True
                self.expected_workspace, self.expected_screen = self.workspace, self.destination_screens[0]
                self.queued_workspace = False
            elif self.index == 5:
                self._call(context, bits, lambda: setattr(self.window, "scene", self.scene))
                self.expected_scene = self.scene
            self.check_after_read(context)
            self._final(context)
            self._verified(row)
            self.index += 1
            self.phase = "verify_context_preparation" if self.index == len(self.native_effects.plans) else self.native_effects.plans[self.index].phase
        return {"phase": self.phase, "completed": self.index+int(self.done), "total": 9}


class ClothCacheDriver(_Driver):
    kind = "simulation.cloth_cache"
    required_permissions = CACHE_PERMISSIONS

    def __init__(self, bpy, context, params):
        self.bpy = bpy
        (self.request, self.prepared, self.modifier, self.cache,
         self.expected, self.fingerprint) = scope.preview(context, bpy, params, starting=True)
        self.label = self.request["action"] + " cloth memory " + self.request["object_name"]
        self.original_time = self.expected["owned"]["frame"]
        self.time_inputs = self.expected["time_inputs"]
        self.original_clock = dict(self.expected["owned"]["clock"])
        self.samples, self.sample_clocks = [], []
        start, end = self.request["frame_start"], self.request["frame_end"]
        action = self.request["action"]
        plans = []
        self.restore_outputs, self.restoration_operations = {}, ()
        if action == "BAKE":
            first, last = self.expected["owned"]["range"]
            fields = (("frame_end", end), ("frame_start", start)) if start > last else (("frame_start", start), ("frame_end", end))
            for field, value in fields:
                first, last = (value, last) if field == "frame_start" else (first, value)
                plans.append(_phase("set_" + field, "cache_" + field + "_set", (first, last)))
        if action in {"BAKE", "INVALIDATE"}:
            plans.append(_phase("invalidate_memory", "cache_frame_step_invalidate", 1))
        if action in {"BAKE", "FREE"}:
            plans.extend((_phase("cache_operator_poll", "ptcache_poll", action),
                _phase("cache_operator_exec", "ptcache_bake_exec" if action == "BAKE" else "ptcache_free_exec", action)))
        if action == "BAKE":
            self.frame_order = tuple(range(end, start-1, -2)) + tuple(range(end-1, start-1, -2))
            for frame in self.frame_order:
                plans.extend((_phase(f"frame_{frame}_set", "frame_set", (frame, 0.)),
                    _phase(f"frame_{frame}_update", "view_layer_update", (frame, 0.)),
                    NativePhasePlan(f"frame_{frame}_geometry", (
                        NativeCallPlan("depsgraph_get", target=(frame, 0.)),
                        NativeCallPlan("evaluated_get", body_name=self.request["object_name"], target=(frame, 0.)),
                        NativeCallPlan("geometry_capture", body_name=self.request["object_name"], target=(frame, 0.))))))
            # Every restoration route and exact native output was proved during
            # preview. Keep requested call arguments distinct from raw readback:
            # negative fractional frame_set arguments normalize through modf.
            steps = scope.restoration_steps(self.original_time, self.time_inputs,
                                             self.expected["negative_frame_policy"][2])
            self.restoration_operations = tuple(step[0] for step in steps)
            for index, (operation, target, output) in enumerate(steps):
                phase = "restore_caller_frame" if index == 0 else "restore_caller_subframe"
                plans.append(_phase(phase, operation, target))
                self.restore_outputs[phase] = output
            plans.append(_phase("restore_caller_update", "view_layer_update", self.original_time))
        self.native_effects = SceneNativeEffects(tuple(plans), profile=CLOTH_PROFILE)
        self.index, self.done, self.result = 0, False, None
        self.phase = plans[0].phase

    def check_after_read(self, context):
        _prepared, modifier, cache, actual, _fingerprint = scope.capture(context, self.bpy, self.request)
        if modifier is not self.modifier or cache is not self.cache or scope.digest(actual) != scope.digest(self.expected):
            raise scope.refuse("CLOTH_JOB_SCOPE_OR_CALLER_TIME_CHANGED")

    def _accept(self, context, row, owned, *, last=0):
        self._final(context)
        _prepared, modifier, cache, actual, _fingerprint = scope.capture(context, self.bpy, self.request)
        expected = {**self.expected, "owned": owned}
        # The context's frame fields are the same declared owned time.
        current = list(expected["context"])
        current[6], current[7] = owned["frame"][0], float(owned["frame"][1]).hex()
        expected["context"] = tuple(current)
        if modifier is not self.modifier or cache is not self.cache or scope.digest(actual) != scope.digest(expected):
            raise scope.refuse("CLOTH_NATIVE_RETURN_UNVERIFIED")
        self.expected = expected
        self._final(context)
        self._verified(row, last)

    def _operator(self, poll=False):
        operator = self.bpy.ops.ptcache.bake if self.request["action"] == "BAKE" else self.bpy.ops.ptcache.free_bake
        with self.bpy.context.temp_override(scene=self.prepared.scene, object=self.prepared.obj,
                active_object=self.prepared.obj, point_cache=self.cache):
            return operator.poll() if poll else operator("EXEC_DEFAULT", **({"bake": True} if self.request["action"] == "BAKE" else {}))

    def _geometry(self, evaluated):
        mesh = evaluated.data
        vertices = scope.bounded(mesh.vertices, scope.MAX_VERTICES)
        coordinates = tuple(tuple(float(value) for value in vertex.co) for vertex in vertices)
        if (len(coordinates) != len(self.prepared.obj.data.vertices) or any(len(co) != 3 for co in coordinates)
                or not all(math.isfinite(value) for co in coordinates for value in co)):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Cloth returned incomplete or nonfinite evaluated geometry.")
        geometry = {"coordinates": coordinates,
            "edges": tuple(tuple(edge.vertices) for edge in scope.bounded(mesh.edges, 1024)),
            "faces": tuple(tuple(face.vertices) for face in scope.bounded(mesh.polygons, 1024)),
            "loops": tuple((loop.vertex_index, loop.edge_index) for loop in scope.bounded(mesh.loops, 2048))}
        source = self.prepared.obj.data
        source_topology = {
            "edges": tuple(tuple(edge.vertices) for edge in scope.bounded(source.edges, 1024)),
            "faces": tuple(tuple(face.vertices) for face in scope.bounded(source.polygons, 1024)),
            "loops": tuple((loop.vertex_index, loop.edge_index) for loop in scope.bounded(source.loops, 2048))}
        if any(geometry[field] != topology for field, topology in source_topology.items()):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Cloth evaluated topology differs from the complete frozen source mesh.")
        return geometry

    def _sample(self, context, plan, row):
        graph = self._call(context, row.calls[0], self.bpy.context.evaluated_depsgraph_get)
        evaluated = self._call(context, row.calls[1], lambda graph=graph: self.prepared.obj.evaluated_get(graph))
        geometry = self._call(context, row.calls[2], lambda evaluated=evaluated: self._geometry(evaluated))
        del graph, evaluated
        self._accept(context, row, dict(self.expected["owned"]), last=2)
        self.samples.append({"frame": plan.calls[0].target[0], **geometry})
        self.sample_clocks.append({"requested_frame": plan.calls[0].target[0],
                                   "clock": dict(self.expected["owned"]["clock"])})
        row.sample_recorded = True

    def _complete(self, context):
        self._check(context)
        action = self.request["action"]
        if action == "BAKE" and (set(item["frame"] for item in self.samples) != set(self.frame_order)
                or len(self.samples) != len(self.frame_order) or self.expected["owned"]["frame"] != self.original_time):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Cloth did not verify every requested frame and caller time.")
        self.result = {**self.request, **scope.observation_limits(self.bpy), "expected_fingerprint": self.fingerprint,
            "baked": self.expected["owned"]["baked"], "frames_sampled": len(self.samples),
            "vertices_per_frame": len(self.prepared.obj.data.vertices),
            "complete_geometry_samples_sha256": scope.digest(self.samples) if self.samples else None,
            "sample_frame_order": [item["frame"] for item in self.samples],
            "immutable_scene_time_inputs": dict(zip(scope.TimeInputs._fields, self.time_inputs, strict=True)),
            "initial_caller_clock": self.original_clock, "verified_final_clock": dict(self.expected["owned"]["clock"]),
            "sample_clock_values": self.sample_clocks,
            "clock_comparison": "EXACT_SOURCE_FLOAT32_NO_TOLERANCE",
            "native_bake_temporarily_forces_frame_length_one": action == "BAKE",
            "native_bake_frame_length_restoration": "SOURCE_NATIVE_RETURN_AND_MAPPED_CLOCK_VERIFIED" if action == "BAKE" else "NOT_APPLICABLE",
            "caller_time_restoration_operations": self.restoration_operations,
            "negative_frame_policy": self.expected["negative_frame_policy"],
            "frame_change_tags_and_notifications_may_remain": action == "BAKE",
            "all_requested_integer_frames_sampled": action == "BAKE", "caller_time_restored": action == "BAKE",
            "cache_coverage": "ALL_REQUESTED_FRAMES_GEOMETRY_SAMPLED_BAKED_FLAG_OBSERVED" if action == "BAKE" else "NOT_ASSESSED",
            "cache_storage_coverage": "NOT_INSPECTED",
            "cache_freshness": "INPUT_FINGERPRINT_MATCHED_BEFORE_BAKE_AND_EVERY_SAMPLE" if action == "BAKE" else "NOT_ASSESSED",
            "native_memory_empty": "NOT_ASSESSED", "free_semantics": "BAKED_FLAG_ONLY_STORAGE_AND_FRESHNESS_UNKNOWN",
            "same_value_frame_step_update_requested": action in {"BAKE", "INVALIDATE"},
            "native_calls_preemptible": False, "automatic_cleanup_performed": False,
            "physical_correctness": "NOT_ASSESSED", "visual_review": "NOT_PERFORMED", "project_saved": False,
            "durable_backup_created": False, "full_solver_and_ordinary_large_artist_target": "OPEN"}
        self.done, self.phase = True, "complete"

    def advance(self, context):
        if self.index == len(self.native_effects.plans):
            self._complete(context)
        else:
            plan, row = self.native_effects.plans[self.index], self.native_effects.rows[self.index]
            operation, target = plan.calls[0].operation, plan.calls[0].target
            owned = dict(self.expected["owned"])
            if operation.startswith("cache_frame_") and operation.endswith("_set"):
                field = "frame_start" if operation == "cache_frame_start_set" else "frame_end"
                value = target[0] if field == "frame_start" else target[1]
                self._call(context, row.calls[0], lambda: setattr(self.cache, field, value))
                owned["range"] = target
            elif operation == "cache_frame_step_invalidate":
                self._call(context, row.calls[0], lambda: setattr(self.cache, "frame_step", 1))
                # The update requests invalidation, but may retain baked data;
                # no changed baked-flag value is inferred from the setter.
            elif operation == "ptcache_poll":
                if self._call(context, row.calls[0], lambda: self._operator(poll=True)) is not True:
                    raise invalid_argument("Point-cache operator is unavailable in the exact cloth context.")
            elif operation in {"ptcache_bake_exec", "ptcache_free_exec"}:
                result = self._call(context, row.calls[0], self._operator)
                if type(result) is not set or result != {"FINISHED"}:
                    raise BridgeError(ErrorCode.OPERATION_FAILED, "Native point-cache EXEC did not finish.")
                owned["baked"] = operation == "ptcache_bake_exec"
            elif operation == "frame_set":
                self._call(context, row.calls[0], lambda: self.prepared.scene.frame_set(target[0], subframe=target[1]))
                frame = self.restore_outputs.get(plan.phase, target)
                owned["frame"], owned["clock"] = frame, scope.working_clock(frame, self.time_inputs)
            elif operation in {"scene_frame_current_set", "scene_frame_subframe_set", "scene_frame_float_set"}:
                field = {"scene_frame_current_set": "frame_current", "scene_frame_subframe_set": "frame_subframe",
                         "scene_frame_float_set": "frame_float"}[operation]
                self._call(context, row.calls[0], lambda: setattr(self.prepared.scene, field, target))
                frame = self.restore_outputs[plan.phase]
                if frame is None:
                    frame = (target, owned["frame"][1])
                owned["frame"], owned["clock"] = frame, scope.working_clock(frame, self.time_inputs)
            elif operation == "view_layer_update":
                self._call(context, row.calls[0], self.bpy.context.view_layer.update)
            else:
                self._sample(context, plan, row)
            if not row.verified:
                self._accept(context, row, owned)
            self.index += 1
            self.phase = "verify_cloth_cache" if self.index == len(self.native_effects.plans) else self.native_effects.plans[self.index].phase
        return {"phase": self.phase, "completed": self.index+int(self.done), "total": len(self.native_effects.plans)+1}
