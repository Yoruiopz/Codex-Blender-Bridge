"""Scene-domain projection of the frozen native all-Main admission profile.

The shared reader remains unchanged. Only identities explicitly controlled by
the seven Scene handlers are projected out, and the domain reader separately
proves their literal fields, consumers and exact native constructor outcomes.
This is bounded admission, not a sandbox for third-party host Python.
"""

from __future__ import annotations

from typing import Any

from ..errors import BridgeError, ErrorCode
from . import _rigid_evaluation_scope as native
from . import _scene_mutation as proof


class Scope:
    def __init__(self, bpy: Any, scene: Any, method: str, *, world_getter: Any = None,
                 new_world: bool = False, edit_world: bool = False, collection_identity: Any = None):
        self.bpy, self.scene, self.method = bpy, proof.token(scene), method
        self.world_getter = world_getter if method == "world.configure" else None
        self.new_world, self.edit_world = method == "world.configure" and new_world, method == "world.configure" and edit_world
        self.collection_identity = collection_identity if method in {"collection.create", "collection.rename", "collection.delete"} else None

    def __call__(self) -> tuple[Any, ...]:
        try:
            main_ids, owners, trees, _totals = native.snapshot(self.bpy)
        except BridgeError as error:
            if error.code != ErrorCode.NOT_IMPLEMENTED:
                raise
            raise proof.unsupported("Scene mutation requires the bounded static all-Main native dependency profile; animated, linked, overridden or unreviewed dependencies are unsupported.",
                                    evaluation_scope_complete=False) from error
        collection = None if self.collection_identity is None else self.collection_identity()
        world = None if self.world_getter is None else self.world_getter()
        world_identity = None if world is None else proof.token(world)
        # These tokens originate only from the explicit preflight target or the
        # synchronous native constructor result, before any later providers.
        excluded = {identity for identity in (collection, world_identity if self.new_world else None) if identity is not None}
        main = tuple(record for record in main_ids if record[0] not in excluded)
        projected_owners, owned_trees = [], set()
        for identity, bindings in owners:
            target_world = identity[0] == world_identity and (self.edit_world or self.new_world)
            if target_world:
                owned_trees.update(token for field, token in bindings if field == "node_tree" and token[0] is not None)
            if self.new_world and identity[0] == world_identity:
                continue
            projected = tuple((field, token) for field, token in bindings
                              if not (self.method == "world.configure" and identity[0] == self.scene and field == "world")
                              and not (target_world and field == "node_tree"))
            projected_owners.append((identity, projected))
        projected_trees = tuple(record for record in trees if record[0][0] not in owned_trees)
        totals = tuple(sum(len(record[index]) for record in projected_trees) for index in (1, 2, 3))
        return main, tuple(projected_owners), projected_trees, totals


def require_plain_object(bpy: Any, obj: Any) -> None:
    """Refuse geometric/evaluated transform sources beyond a literal Object."""
    proof.descriptors(bpy, obj)
    if (obj.animation_data is not None or obj.parent is not None or len(obj.constraints) or len(obj.modifiers)
            or obj.rigid_body is not None or obj.rigid_body_constraint is not None or obj.instance_type != "NONE"):
        raise proof.unsupported("Camera, Light and focus Objects require plain unanimated, unparented, unconstrained, non-instanced native sources without modifiers or rigid-body effects.")


def require_no_physics(bpy: Any) -> None:
    """Gravity/units affect physics beyond the literal Scene settings."""
    # Called only after Scope has admitted every native Main Object and Scene.
    for scene in proof.bounded(bpy.data.scenes, native.MAX_SCENES, "physics Scenes"):
        if scene.rigidbody_world is not None:
            raise proof.unsupported("Gravity and unit changes in existing rigid-body worlds need a broader physics preservation contract.")
    for obj in proof.bounded(bpy.data.objects, native.MAX_MAIN_IDS, "physics Objects"):
        proof.descriptors(bpy, obj)
        field, collision = obj.field, obj.collision
        if (obj.rigid_body is not None or obj.rigid_body_constraint is not None or len(obj.particle_systems)
                or (field is not None and field.type != "NONE") or (collision is not None and collision.use)):
            raise proof.unsupported("Gravity and unit changes with existing physics require a broader preservation contract.")
        for modifier in proof.bounded(obj.modifiers, 128, "physics modifiers"):
            if modifier.type in {"CLOTH", "COLLISION", "DYNAMIC_PAINT", "EXPLODE", "FLUID", "PARTICLE_INSTANCE", "PARTICLE_SYSTEM", "SOFT_BODY"}:
                raise proof.unsupported("Gravity and unit changes with existing physics modifiers require a broader preservation contract.")
