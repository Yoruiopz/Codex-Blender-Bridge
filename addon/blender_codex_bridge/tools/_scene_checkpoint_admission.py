"""Cached Scene authored admission before every checkpoint/native undo write.

Factories freeze native plans before providers. The exact reserved marker slot
belongs to manager CAS; only a trusted native-push notification advances the
source-proven weak ParticleEdit role, followed by mandatory readonly proof.
"""

from __future__ import annotations

from typing import Any

from ..errors import BridgeError, ErrorCode
from ..permissions import Permission
from ..task_plans import get_task_plans
from ..tool_registry import check_final_mutation
from ..utils import require_blender
from . import _scene_checkpoint_roles as roles
from . import _scene_evaluation_scope as evaluation
from . import _scene_mutation as proof


class Admission:
    def __init__(self, context: Any, bpy: Any, scene: Any, method: str, *, objects: tuple[Any, ...] = (),
                 physics_sensitive: bool = False, world: Any = None, new_world: bool = False,
                 edit_world: bool = False, collection: Any = None, prepared: Any = None,
                 boundary: Any = None, holder: Any = None, checkpoint_roles: Any = None):
        self.context, self.bpy, self.scene, self.method = context, bpy, scene, method
        self.objects, self.physics_sensitive = objects, physics_sensitive
        self.world, self.new_world = world, new_world
        self.prepared, self.boundary, self.holder = prepared, boundary, holder
        self.roles = checkpoint_roles
        self.collection = None if collection is None else proof.token(collection)
        self.scope = evaluation.Scope(bpy, scene, method, world_getter=lambda: self.world,
                                      new_world=new_world, edit_world=edit_world, collection_identity=lambda: self.collection)
        self.expected = self.snapshot()

    def snapshot(self) -> Any:
        bpy = self.bpy
        proof.preflight_types(bpy)
        static = self.scope()
        proof.current_scene(bpy, self.scene)
        runtime = proof.runtime(bpy)
        for obj in self.objects:
            evaluation.require_plain_object(bpy, obj)
        if self.physics_sensitive:
            evaluation.require_no_physics(bpy)
        return static, proof.session(bpy), runtime, id(get_task_plans(self.context.state).protection)

    def __call__(self) -> None:
        context = self.context
        # Providers all finish before comparing the frozen static closure.
        context.registry.prepare(self.method, context)
        permissions = (Permission.EDIT_SCENE, Permission.DELETE_OBJECTS) if self.method == "collection.delete" else (Permission.EDIT_SCENE,)
        context.require(*permissions)
        self.check_after_read()

    def check_after_read(self) -> None:
        if self.roles is not None:
            self.roles.check_after_read()
        if self.snapshot() != self.expected:
            raise proof.unsupported("Static Scene checkpoint admission changed; no further markers, undo pushes or automatic finalization are authorized.",
                                    checkpoint_admission_valid=False)
        if self.boundary is not None:
            self.boundary.check_after_read()
        check_final_mutation(self.context, self.method)

    def after_native_push(self) -> None:
        from ..checkpoint_completion import claim_native_push_completion
        claim_native_push_completion(self.context, self.method, self)
        if self.roles is not None:
            self.roles.after_native_push()

    def native_push_delegates(self) -> tuple[Any, ...]:
        return () if self.roles is None else (self.roles,)

    def allocated(self, kind: str, owner: Any) -> None:
        """Called only for a constructor validated by the domain boundary."""
        if kind == "world" and self.method == "world.configure" and self.new_world:
            self.world = owner
        elif kind == "collection" and self.method == "collection.create":
            self.collection = None if owner is None else proof.token(owner)
        else:
            raise proof.unsupported("A native allocation does not belong to this Scene checkpoint admission.")


def note_allocation(context: Any, method: str, kind: str, owner: Any) -> None:
    binding = getattr(context, "checkpoint_admission", None)
    if binding is None:
        return  # Raw handler tests have no checkpoint; registry paths bind it.
    if binding.method != method or not isinstance(binding.callback, Admission):
        raise proof.unsupported("Scene allocation has no matching request-owned checkpoint admission.")
    if not binding.matches(context.registry.get(method), binding.params, context):
        raise proof.unsupported("Scene allocation checkpoint admission belongs to another call.")
    binding.callback.allocated(kind, owner)


def cached(context: Any, method: str) -> Admission | None:
    """Use the exact readonly factory plan; raw unit handlers have no binding."""
    binding = getattr(context, "checkpoint_admission", None)
    if binding is None:
        return None
    binding.check_identity(method)
    if binding.method != method or not isinstance(binding.callback, Admission):
        raise proof.unsupported("Scene mutation has no matching request-owned authored plan.")
    return binding.callback


def factory(method: str, context: Any, params: Any) -> Admission:
    from . import scene_edit as domain

    bpy = require_blender()
    proof.preflight_types(bpy)
    # This descriptor-first pass precedes every generic domain RNA reader.
    evaluation.Scope(bpy, bpy.context.scene, method)()
    checkpoint_roles = roles.Plan(bpy, bpy.context.scene)
    if method in {"scene.configure", "camera.configure", "light.configure"}:
        prepare = {"scene.configure": domain._prepare_scene, "camera.configure": domain._prepare_camera,
                   "light.configure": domain._prepare_light}[method]
        prepared = prepare(params)
        boundary = domain._settings_boundary(context, method, prepared, checkpoint_authored=True,
                                              checkpoint_roles=checkpoint_roles)
        scope = boundary.profile
        return Admission(context, bpy, scope.scene, method, objects=scope.objects, physics_sensitive=scope.physics_sensitive,
                         prepared=prepared, boundary=boundary, checkpoint_roles=checkpoint_roles)
    if method == "world.configure":
        prepared = domain._prepare_world(params)
        domain._validate_world_prepared(prepared)
        holder = [prepared.world]
        boundary = domain._world_boundary(context, prepared, holder, checkpoint_authored=True,
                                           checkpoint_roles=checkpoint_roles)
        return Admission(context, bpy, prepared.scene, method, world=prepared.world, new_world=prepared.world is None,
                         edit_world=boundary.profile.edit_world, prepared=prepared, boundary=boundary, holder=holder,
                         checkpoint_roles=checkpoint_roles)
    if method in {"collection.create", "collection.rename", "collection.delete"}:
        prepare = {"collection.create": domain._prepare_collection_create, "collection.rename": domain._prepare_collection_rename,
                   "collection.delete": domain._prepare_collection_delete}[method]
        plan = prepare(context, params, checkpoint_roles=checkpoint_roles)
        return Admission(context, bpy, plan.scene, method, collection=plan.collection, prepared=plan, boundary=plan.boundary,
                         checkpoint_roles=checkpoint_roles)
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "No reviewed Scene checkpoint admission factory is registered.")
