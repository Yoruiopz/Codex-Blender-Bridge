"""Fixed, guarded native phases for the initial rigid evaluation job profile."""

from __future__ import annotations

import math

from ..entry_effects import mark_view_layer_sync_possible
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..scene_job_effects import NativeCallPlan, NativePhasePlan, SceneNativeEffects
from ..scene_job_reservations import TURN_METHOD
from ..tool_registry import check_final_mutation
from . import _animation_scope as evidence
from . import _rigid_body_scope as scope
from .rigid_body_jobs import PERMISSIONS


class RigidEvaluationDriver:
    kind = "rigid_body.evaluation"
    required_permissions = PERMISSIONS

    def __init__(self, bpy, prepared):
        self.bpy = bpy
        (self.scene, self.params, self.expected, self.roles, self.authored_roles,
         self.proposal, self.fingerprint) = prepared
        self.label = "Evaluate rigid world " + self.scene.name
        self.authored_roles_sha256 = evidence.digest(self.authored_roles)
        self.protected_sha256 = evidence.digest({key: self.expected[key] for key in
                                               ("protected", "body_names", "constraint_names", "base_vertices")})
        self.world, self.cache = self.scene.rigidbody_world, self.scene.rigidbody_world.point_cache
        self.original_frame = self.expected["owned"]["frame"]
        self.body_names = self.expected["body_names"]
        self.bodies = tuple(bpy.data.objects[name] for name in self.body_names)
        self.samples = []
        start, end = self.proposal["frame_start"], self.proposal["frame_end"]
        first, last = self.expected["owned"]["range"]
        fields = (("frame_end", end), ("frame_start", start)) if start > last else (("frame_start", start), ("frame_end", end))
        plans = []
        for field, value in fields:
            first, last = (value, last) if field == "frame_start" else (first, value)
            plans.append(NativePhasePlan("set_"+field, (NativeCallPlan("cache_"+field+"_set", target=(first, last)),)))
        plans.append(NativePhasePlan("reset_world", (NativeCallPlan("world_reset", target=self.expected["owned"]["time_scale"]),)))
        for frame in range(start, end+1):
            plans.extend((
                NativePhasePlan(f"frame_{frame}_set", (NativeCallPlan("frame_set", target=(frame, 0.)),)),
                NativePhasePlan(f"frame_{frame}_update", (NativeCallPlan("view_layer_update", target=(frame, 0.)),)),
                NativePhasePlan(f"frame_{frame}_sample", (
                    NativeCallPlan("depsgraph_get", target=(frame, 0.)),
                    *(call for name in self.body_names for call in (
                        NativeCallPlan("evaluated_get", body_name=name, target=(frame, 0.)),
                        NativeCallPlan("matrix_capture", body_name=name, target=(frame, 0.)))),
                )),
            ))
        plans.extend((
            NativePhasePlan("restore_caller_frame", (NativeCallPlan("frame_set", target=self.original_frame),)),
            NativePhasePlan("restore_caller_update", (NativeCallPlan("view_layer_update", target=self.original_frame),)),
        ))
        self.native_effects = SceneNativeEffects(tuple(plans))
        self.index, self.done, self.result = 0, False, None
        self.phase = plans[0].phase

    def check_after_read(self, context):
        self.roles.check_after_read()
        if evidence.digest(self.roles.authored()) != self.authored_roles_sha256:
            raise invalid_argument("Checkpoint authored settings changed; partial evaluation is retained.", scope_complete=False)
        scene = scope.current_scene(self.bpy, self.params["scene_name"])
        mark_view_layer_sync_possible()
        actual = scope.snapshot(self.bpy, scene, self.params)
        if scene != self.scene or evidence.digest(actual) != evidence.digest(self.expected) or self.cache.is_baked:
            raise invalid_argument("Rigid identities, authored inputs, cache or caller context changed; partial evaluation is retained.",
                                   scope_complete=False)

    def native_push_delegates(self):
        return (self.roles,)

    def after_native_push(self):
        self.roles.after_native_push()

    def _final(self, context):
        check_final_mutation(context, TURN_METHOD)

    def _check(self, context):
        self._final(context)
        context.require(*PERMISSIONS)
        self._final(context)
        self.check_after_read(context)
        self._final(context)

    def _call(self, context, bits, callback, *, preflight=True):
        if preflight:
            self._check(context)
        else:
            self._final(context)
        # These literal stores straddle the selected native interval itself.
        # A normal return is recorded before any fallible later bookkeeping.
        bits.entered = True
        value = callback()
        bits.returned = True
        self._final(context)
        return value

    def _accept(self, context, owned, row):
        self._final(context)
        mark_view_layer_sync_possible()
        actual = scope.snapshot(self.bpy, self.scene, self.params)
        protected = ("protected", "body_names", "constraint_names", "base_vertices")
        if (evidence.digest({key: actual[key] for key in protected}) != self.protected_sha256
                or evidence.digest(actual["owned"]) != evidence.digest(owned)
                or self.cache.is_baked):
            raise invalid_argument("Native evaluation changed protected or unexpected state; partial effects are retained.", scope_complete=False)
        self.roles.check_after_read()
        if evidence.digest(self.roles.authored()) != self.authored_roles_sha256:
            raise invalid_argument("Native evaluation changed protected checkpoint settings.", scope_complete=False)
        self._final(context)
        self.expected = {**self.expected, "owned": dict(owned), "cache_status": actual["cache_status"]}
        row.verified = True

    def _sample(self, context, plan, row):
        getter = self.bpy.context.evaluated_depsgraph_get
        graph = self._call(context, row.calls[0], getter)
        matrices = {}
        for index, (name, obj) in enumerate(zip(self.body_names, self.bodies, strict=True)):
            self._final(context)
            evaluate = obj.evaluated_get
            evaluated = self._call(context, row.calls[1+2*index],
                                   lambda evaluate=evaluate, graph=graph: evaluate(graph), preflight=False)

            def capture(evaluated=evaluated):
                return tuple(float(value) for line in evaluated.matrix_world for value in line)

            # The declared capture interval includes its complete scalar copy;
            # partial copy/allocation failure is entered without normal return.
            values = self._call(context, row.calls[2+2*index], capture, preflight=False)
            if len(values) != 16 or not all(math.isfinite(value) for value in values):
                raise BridgeError(ErrorCode.OPERATION_FAILED, "Rigid evaluation returned an incomplete or nonfinite matrix.")
            matrices[name] = values
            del evaluated, capture
        del graph
        self._final(context)
        self._accept(context, self.expected["owned"], row)
        self.samples.append({"frame": plan.calls[0].target[0], "matrices": matrices})
        row.sample_recorded = True

    def _verify(self, context):
        self._check(context)
        start, end = self.proposal["frame_start"], self.proposal["frame_end"]
        if (evidence.digest(tuple(item["frame"] for item in self.samples)) != evidence.digest(tuple(range(start, end+1)))
                or evidence.digest(self.expected["owned"]["frame"]) != evidence.digest(self.original_frame)
                or evidence.digest(self.expected["owned"]["range"]) != evidence.digest((start, end))):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Rigid evaluation did not verify every requested frame and caller time.")
        endpoints = []
        for name in self.body_names:
            first, last = self.samples[0]["matrices"][name], self.samples[-1]["matrices"][name]
            endpoints.append({"body_name": name, "first_matrix": list(first), "last_matrix": list(last),
                              "displacement_xyz": tuple(last[index]-first[index] for index in (3, 7, 11))})
        self.result = {"scene": self.scene.name, "body_names": list(self.body_names),
            "frame_start": start, "frame_end": end, "frames_sampled": len(self.samples),
            "matrices_sampled": len(self.samples)*len(self.body_names),
            "matrix_samples_sha256": evidence.digest(self.samples),
            "sample_digest_format": "SORTED_JSON_FRAME_ORDER_BODY_NAMES_FLOAT64_VALUES_V1",
            "endpoints": endpoints, "all_requested_integer_frames_sampled": True,
            "caller_time_restored": True, "active_selection_mode_preserved": True,
            "proposed_cache_range_retained": True, "baked": False, "bake_completed": False,
            "cache_coverage": "NOT_ASSESSED", "cache_freshness": "NOT_ASSESSED",
            "physical_correctness": "NOT_ASSESSED", "visual_review": "NOT_PERFORMED",
            "durability": "NOT_ASSESSED", "project_saved": False, "durable_backup_created": False}
        self._final(context)

    def advance(self, context):
        self._final(context)
        if self.index == len(self.native_effects.plans):
            self._verify(context)
            self.done, self.phase = True, "complete"
        else:
            plan = self.native_effects.plans[self.index]
            row = self.native_effects.rows[self.index]
            operation, target = plan.calls[0].operation, plan.calls[0].target
            expected = dict(self.expected["owned"])
            if operation in {"cache_frame_start_set", "cache_frame_end_set"}:
                field = "frame_start" if operation == "cache_frame_start_set" else "frame_end"
                value = target[0] if field == "frame_start" else target[1]
                cache = self.cache
                self._call(context, row.calls[0], lambda: setattr(cache, field, value))
                expected["range"] = target
                self._accept(context, expected, row)
            elif operation == "world_reset":
                world = self.world
                self._call(context, row.calls[0], lambda: setattr(world, "time_scale", target))
                self._accept(context, expected, row)
            elif operation == "frame_set":
                setter = self.scene.frame_set
                self._call(context, row.calls[0], lambda: setter(target[0], subframe=target[1]))
                expected["frame"] = target
                self._accept(context, expected, row)
            elif operation == "view_layer_update":
                update = self.bpy.context.view_layer.update
                self._call(context, row.calls[0], update)
                self._accept(context, expected, row)
            else:
                self._sample(context, plan, row)
            self.index += 1
            self.phase = "verify_complete" if self.index == len(self.native_effects.plans) else self.native_effects.plans[self.index].phase
        return {"phase": self.phase, "completed": self.index+int(self.done), "total": len(self.native_effects.plans)+1}
