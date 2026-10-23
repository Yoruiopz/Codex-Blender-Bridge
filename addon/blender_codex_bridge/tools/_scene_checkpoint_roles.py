"""Exact weak ParticleEdit roles written by the reviewed native undo poll.

``particle_undosys_poll -> PE_get_current`` assigns particle.scene/object even
in Object Mode. Only a trusted, completed checkpoint push advances this plan.
No getter result or undo-window position can authorize that transition.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import _scene_evaluation_scope as evaluation
from . import _scene_mutation as proof


def _pointer(bpy: Any, owner: Any, name: str, fixed_type: str) -> Any:
    properties = proof.descriptors(bpy, owner)
    prop = next((item for item in properties if item.identifier == name), None)
    if (prop is None or prop.is_runtime or not prop.is_readonly or prop.type != "POINTER"
            or getattr(prop, "is_registered", False)
            or getattr(getattr(prop, "fixed_type", None), "identifier", None) != fixed_type):
        raise proof.unsupported("Checkpoint weak-role pointer has an unreviewed native descriptor.", property=name)
    return getattr(owner, name)


def _settings(bpy: Any, owner: Any) -> Any:
    for prop in proof.descriptors(bpy, owner):
        if not prop.is_readonly and not prop.is_runtime and prop.type not in proof.PRIMITIVES | {"POINTER"}:
            raise proof.unsupported("Particle settings contain an unreviewed writable property kind.", property=prop.identifier)
    return proof.primitive(bpy, owner)


@dataclass(frozen=True, slots=True)
class Origin:
    bpy: Any
    scene: Any
    active_validator: Any
    include_brush: bool
    active: Any
    owners: Any
    expected: Any
    previous_witness: Any = None

    def fork(self) -> Plan:
        result = object.__new__(Plan)
        result.bpy, result.scene = self.bpy, self.scene
        result.active_validator, result.include_brush = self.active_validator, self.include_brush
        result.active, result.owners, result.expected = self.active, self.owners, self.expected
        result.previous_witness = self.previous_witness
        result.check_after_read()
        return result


@dataclass(frozen=True, slots=True)
class Readonly:
    _plan: Any

    def check_after_read(self) -> None:
        self._plan.check_after_read()

    def authored(self) -> Any:
        return self._plan.authored()

    def object_references(self, references: Any) -> Any:
        return self._plan.object_references(references)


class Plan:
    def __init__(self, bpy: Any, scene: Any, *, active_validator: Callable[[Any, Any], None] | None = None,
                 include_brush: bool = False,
                 previous_owner_factory: Callable[[Any, Any, Any], Any] | None = None):
        self.bpy, self.scene = bpy, scene
        self.active_validator = active_validator or evaluation.require_plain_object
        self.include_brush = include_brush
        self.previous_witness = None
        owners, self_count, particle_object = self._read()
        self.active = owners[-1]
        if self.active == proof.token(None):
            raise proof.unsupported("Checkpoint weak-role admission requires a non-null frozen active Object.")
        self.owners = owners
        self.expected = self_count, particle_object
        if self.expected not in ((0, proof.token(None)), (1, self.active)):
            if self_count != 1 or particle_object == proof.token(None) or previous_owner_factory is None:
                raise proof.unsupported("Checkpoint ParticleEdit roles are outside their exact reviewed initial state.")
            settings = _pointer(bpy, scene, "tool_settings", "ToolSettings")
            particle = _pointer(bpy, settings, "particle_edit", "ParticleEdit")
            previous = _pointer(bpy, particle, "object", "Object")
            if proof.token(previous) != particle_object:
                raise proof.unsupported("Checkpoint previous weak Object changed before witness capture.")
            witness = previous_owner_factory(bpy, previous, self)
            if witness is None or not callable(getattr(witness, "check", None)):
                raise proof.unsupported("Checkpoint previous weak Object requires a retained readonly witness.")
            self.previous_witness = witness
        self.check_after_read()

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
            self.active_validator(bpy, active)
            if len(active.particle_systems) or _pointer(bpy, active, "soft_body", "SoftBodySettings") is not None:
                raise proof.unsupported("Checkpoint weak-role admission refuses active particle or soft-body cache sources.")
        owners = (proof.token(scene), proof.key(settings), proof.key(particle),
                  proof.token(original), proof.token(active))
        return owners, int(scene.user_of_id(scene)), proof.token(particle_object)

    def _check_roles(self) -> None:
        owners, self_count, particle_object = self._read()
        if owners != self.owners or (self_count, particle_object) != self.expected:
            raise proof.unsupported("Checkpoint ParticleEdit roles or their frozen native owners changed.",
                                    checkpoint_roles_valid=False)

    def check_after_read(self) -> None:
        self._check_roles()
        if self.previous_witness is not None:
            self.previous_witness.check(self)

    def after_native_push(self) -> None:
        from ..checkpoint_completion import claim_native_push_delegate
        claim_native_push_delegate(self)
        # Trusted notification only; the caller must immediately run the
        # mandatory readonly CAS. Never derive expectations from live values.
        self.expected = 1, self.active

    def fork(self) -> Plan:
        """Retain an origin's exact phase; never adopt a newer native readback."""
        return self.origin().fork()

    def origin(self) -> Origin:
        return Origin(self.bpy, self.scene, self.active_validator, self.include_brush,
                      self.active, self.owners, self.expected, self.previous_witness)

    def retained(self) -> tuple[Readonly, Callable[[], None]]:
        """Public read-only proof plus a private completion writer capability."""
        return Readonly(self), self.after_native_push

    def authored(self) -> Any:
        """Always measure writable particle settings, including before binding."""
        self.check_after_read()
        settings = _pointer(self.bpy, self.scene, "tool_settings", "ToolSettings")
        particle = _pointer(self.bpy, settings, "particle_edit", "ParticleEdit")
        if not self.include_brush:
            return self.owners, self.references(), _settings(self.bpy, particle)
        brush = _pointer(self.bpy, particle, "brush", "ParticleBrush")
        if brush is None:
            raise proof.unsupported("Artist checkpoint requires the reviewed native particle brush.")
        # On the reviewed runtimes this getter returns null. A non-null native
        # curve needs a separate bounded content reader, never omission.
        curve = _pointer(self.bpy, brush, "curve", "CurveMapping")
        if curve is not None:
            raise proof.unsupported("A non-null particle brush curve requires a broader artist checkpoint reader.")
        authored = self.owners, self.references(), _settings(self.bpy, particle)
        return (*authored, proof.key(brush), _settings(self.bpy, brush), proof.token(curve))

    def object_references(self, references: Any) -> Any:
        """Subtract only the separately proven native weak Object role.

        Ordinary Scene membership and camera use keep their exact count. All
        other consumers remain literal, and writable particle settings live in
        authored() on both sides of a native push.
        """
        # A witness itself projects both old/new Object closures. Recheck only
        # the exact role phase here, never recursively enter that witness.
        self._check_roles()
        scene = proof.token(self.scene)
        result = []
        for target, owner, count, role in references:
            if owner != scene:
                result.append((target, owner, count, role))
                continue
            weak = int(self.expected[0] == 1 and self.expected[1] == target)
            if role == ("MEMBERSHIP",):
                if weak:
                    raise proof.unsupported("Checkpoint weak Object role is missing from its Scene consumer.")
                canonical = role
            elif (len(role) == 4 and role[0] == "SCENE_REFERENCES"
                    and role[1] in (0, 1) and role[2] == weak):
                canonical = ("SCENE_REFERENCES", 1, 0, None) if role[1] else ("MEMBERSHIP",)
            else:
                raise proof.unsupported("Checkpoint Scene Object consumers exceed the exact native weak role.")
            if type(count) is not int or count <= weak:
                raise proof.unsupported("Checkpoint weak Object role has an invalid native reference count.")
            result.append((target, owner, count - weak, canonical))
        return tuple(result)

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
