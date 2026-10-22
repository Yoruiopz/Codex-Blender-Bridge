"""Exact weak ParticleEdit roles written by the reviewed native undo poll.

``particle_undosys_poll -> PE_get_current`` assigns particle.scene/object even
in Object Mode. Only a trusted, completed checkpoint push advances this plan.
No getter result or undo-window position can authorize that transition.
"""

from __future__ import annotations

from typing import Any

from . import _scene_mutation as proof
from . import _scene_evaluation_scope as evaluation


def _pointer(bpy: Any, owner: Any, name: str, fixed_type: str) -> Any:
    properties = proof.descriptors(bpy, owner)
    prop = next((item for item in properties if item.identifier == name), None)
    if (prop is None or prop.is_runtime or not prop.is_readonly or prop.type != "POINTER"
            or getattr(prop, "is_registered", False)
            or getattr(getattr(prop, "fixed_type", None), "identifier", None) != fixed_type):
        raise proof.unsupported("Checkpoint weak-role pointer has an unreviewed native descriptor.", property=name)
    return getattr(owner, name)


class Plan:
    def __init__(self, bpy: Any, scene: Any):
        self.bpy, self.scene = bpy, scene
        owners, self_count, particle_object = self._read()
        self.active = owners[-1]
        if self.active == proof.token(None):
            raise proof.unsupported("Checkpoint weak-role admission requires a non-null frozen active Object.")
        if (self_count, particle_object) not in ((0, proof.token(None)), (1, self.active)):
            raise proof.unsupported("Checkpoint ParticleEdit roles are outside their exact reviewed initial state.")
        self.owners = owners
        self.expected = self_count, particle_object

    def _read(self) -> tuple[Any, int, Any]:
        bpy, scene = self.bpy, self.scene
        settings = _pointer(bpy, scene, "tool_settings", "ToolSettings")
        particle = _pointer(bpy, settings, "particle_edit", "ParticleEdit")
        # The Scene weak role is not exposed by RNA on either reviewed build.
        # Reading is_editable/is_hair would itself call PE_get_current.
        if any(prop.identifier == "scene" for prop in proof.descriptors(bpy, particle)):
            raise proof.unsupported("An exposed ParticleEdit Scene role requires a separate source review.")
        particle_object = _pointer(bpy, particle, "object", "Object")
        original = _pointer(bpy, scene, "original", "ID")
        active = bpy.context.view_layer.objects.active
        if active is not None:
            evaluation.require_plain_object(bpy, active)
            if len(active.particle_systems) or _pointer(bpy, active, "soft_body", "SoftBodySettings") is not None:
                raise proof.unsupported("Checkpoint weak-role admission refuses active particle or soft-body cache sources.")
        owners = (proof.token(scene), proof.key(settings), proof.key(particle),
                  proof.token(original), proof.token(active))
        return owners, int(scene.user_of_id(scene)), proof.token(particle_object)

    def check_after_read(self) -> None:
        owners, self_count, particle_object = self._read()
        if owners != self.owners or (self_count, particle_object) != self.expected:
            raise proof.unsupported("Checkpoint ParticleEdit roles or their frozen native owners changed.",
                                    checkpoint_roles_valid=False)

    def after_native_push(self) -> None:
        # Trusted notification only; the caller must immediately run the
        # mandatory readonly CAS. Never derive expectations from live values.
        self.expected = 1, self.active

    def references(self) -> Any:
        """Project only the exact source-proven, separately checked self role."""
        self.check_after_read()
        records = proof.references(self.bpy, (self.scene,))
        identity, users, fake_user, direct = records[0]
        own = tuple(record for record in direct if record[0] == identity)
        expected = () if self.expected[0] == 0 else ((identity, "Scene", self.scene.name, 1),)
        if own != expected:
            raise proof.unsupported("Checkpoint Scene self consumers exceed the exact ParticleEdit role.",
                                    checkpoint_roles_valid=False)
        return ((identity, users, fake_user, tuple(record for record in direct if record[0] != identity)),)
