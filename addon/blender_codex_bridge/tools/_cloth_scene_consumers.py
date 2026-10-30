"""Exact declared Scene-role comparison for the private cloth prerequisite.

Role declarations are data, not permission or evidence that preparation ran.
The caller must establish hidden slots through the reviewed native transition
and independently retain its completion. No observed count initializes a plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from inspect import getattr_static
from types import (
    BuiltinFunctionType,
    GetSetDescriptorType,
    MemberDescriptorType,
    WrapperDescriptorType,
)
from typing import Any

from ..permissions import Permission
from ._simulation_runtime import BUILDS, profile, refused

MAX_SCENES, MAX_ROLES, MAX_CONSUMERS = 2, 64, 64
SLOTS = frozenset({"window.scene", "window.unpinned_scene", "workspace.pin_scene",
                   "workspace.sequencer_scene", "particle.scene"})


def _valid_identity(value: Any) -> bool:
    return (type(value) is tuple and len(value) == 2
            and all(type(item) is int and 0 < item < 2**64 for item in value))


@dataclass(frozen=True, slots=True)
class Role:
    owner: tuple[int, int]
    slot: str
    target: tuple[int, int]

    def __post_init__(self) -> None:
        if self.slot not in SLOTS:
            raise refused("UNREVIEWED_SCENE_SLOT", slot=self.slot)
        for identity in (self.owner, self.target):
            if not _valid_identity(identity):
                raise refused("INVALID_NATIVE_IDENTITY")


@dataclass(frozen=True, slots=True)
class DeclaredRoles:
    build: tuple[Any, ...]
    scenes: tuple[tuple[int, int], ...]
    roles: tuple[Role, ...]
    real_users: tuple[tuple[tuple[int, int], int], ...]
    context: tuple[Any, ...]

    def __post_init__(self) -> None:
        profiles = tuple((key.decode(), row[0], row[1]) for key, row in BUILDS.items())
        if (type(self.build) is not tuple or len(self.build) != 3
                or type(self.build[0]) is not str or type(self.build[2]) is not str
                or type(self.build[1]) is not tuple or len(self.build[1]) != 3
                or any(type(item) is not int for item in self.build[1]) or self.build not in profiles):
            raise refused("INVALID_DECLARED_BUILD")
        if (type(self.scenes) is not tuple or not 1 <= len(self.scenes) <= MAX_SCENES
                or type(self.roles) is not tuple or len(self.roles) > MAX_ROLES
                or not all(_valid_identity(row) for row in self.scenes)
                or len(set(self.scenes)) != len(self.scenes)
                or any(type(role) is not Role or role.target not in self.scenes for role in self.roles)):
            raise refused("INVALID_DECLARED_SCENE_PLAN")
        slots = tuple((role.owner, role.slot) for role in self.roles)
        if len(set(slots)) != len(slots):
            raise refused("DUPLICATE_DECLARED_SCENE_SLOT")
        if (type(self.real_users) is not tuple or len(self.real_users) != len(self.scenes)
                or any(type(row) is not tuple or len(row) != 2 or not _valid_identity(row[0])
                       for row in self.real_users)
                or {row[0] for row in self.real_users} != set(self.scenes)
                or any(type(row[1]) is not int or row[1] < 0 for row in self.real_users)
                or type(self.context) is not tuple or len(self.context) != 8):
            raise refused("INVALID_DECLARED_REAL_USERS")
        if self.build[1][:2] == (4, 5) and any(role.slot == "workspace.sequencer_scene" for role in self.roles):
            raise refused("UNAVAILABLE_BUILD_SLOT")

    def expected(self, scene: tuple[int, int]) -> tuple[tuple[tuple[int, int], int], ...]:
        counts: dict[tuple[int, int], int] = {}
        for role in self.roles:
            if role.target == scene:
                counts[role.owner] = counts.get(role.owner, 0) + 1
        return tuple(sorted(counts.items()))


def identity(owner: Any) -> tuple[int, int]:
    pointer, uid = owner.as_pointer(), owner.session_uid
    if any(type(value) is not int or value <= 0 for value in (pointer, uid)):
        raise refused("INVALID_NATIVE_IDENTITY")
    return pointer, uid


def context(bpy: Any) -> tuple[Any, ...]:
    """Declared layout/sync footprint; not a complete UI/data snapshot."""
    c = bpy.context
    return (bpy.data.as_pointer(), c.window.as_pointer(),
            identity(c.window.workspace), identity(c.window.screen), identity(c.scene),
            c.view_layer.as_pointer(), c.scene.frame_current, c.scene.frame_subframe.hex())


def verify(bpy: Any, plan: DeclaredRoles, owners: tuple[Any, ...]) -> tuple[Any, ...]:
    """Compare literal query output against source-declared multiplicities.

    Scene.original is deliberately absent: both source-reviewed query flags omit
    orig_id. user_map returns membership sets; user_of_id supplies multiplicity.
    Neither membership nor aggregate counts determine the expected role list.
    Native traversal may synchronize view layers; no read-passivity claim.
    """
    if type(plan) is not DeclaredRoles or profile(bpy) != plan.build:
        raise refused("SCENE_ROLE_BUILD_CHANGED")
    if context(bpy) != plan.context:
        raise refused("SCENE_ROLE_CONTEXT_CHANGED")
    if type(owners) is not tuple or tuple(identity(owner) for owner in owners) != plan.scenes:
        raise refused("SCENE_ROLE_IDENTITIES_CHANGED")
    mapping = bpy.data.user_map(subset=set(owners))
    if context(bpy) != plan.context:
        raise refused("SCENE_QUERY_LAYOUT_OR_CONTEXT_CHANGED")
    if set(mapping) != set(owners):
        raise refused("SCENE_ROLE_QUERY_SHAPE")
    user_plan = dict(plan.real_users)
    result = []
    for scene in owners:
        token = identity(scene)
        incoming = mapping[scene]
        if len(incoming) > MAX_CONSUMERS:
            raise refused("SCENE_CONSUMER_BUDGET")
        measured = []
        for owner in incoming:
            count = owner.user_of_id(scene)
            if context(bpy) != plan.context:
                raise refused("SCENE_QUERY_LAYOUT_OR_CONTEXT_CHANGED")
            if type(count) is not int or count <= 0:
                raise refused("INVALID_SCENE_REFERENCE_COUNT")
            measured.append((identity(owner), count))
        measured = tuple(sorted(measured))
        if measured != plan.expected(token):
            failure = refused("SCENE_CONSUMER_ROLES_CHANGED")
            failure.context.update(scene=token, expected=plan.expected(token), observed=measured)
            raise failure
        users, fake = scene.users, scene.use_fake_user
        if (type(users) is not int or type(fake) is not bool
                or users - int(fake) != user_plan[token]):
            raise refused("SCENE_NATIVE_USERS_CHANGED")
        result.append((token, measured, users, fake))
    return tuple(result)


def completed_unpinned_exit(roles: DeclaredRoles, *, window_manager: tuple[int, int],
                            scene: tuple[int, int], source_workspace: tuple[int, int],
                            source_unpinned: bool, completed: bool) -> DeclaredRoles:
    """Predict workspace_exit's one hidden assignment after actual completion.

    The external completion check must match exact source/destination workspace,
    screen, Window and Scene. A queued Window.workspace setter is NOT completion.
    This pure reducer never calls Blender, polls events or blesses a late edit.
    """
    if completed is not True or scene not in roles.scenes or source_unpinned is not True:
        raise refused("WORKSPACE_EXIT_NOT_COMPLETED")
    if not _valid_identity(source_workspace):
        raise refused("INVALID_SOURCE_WORKSPACE")
    retained = tuple(role for role in roles.roles
                     if (role.owner, role.slot) != (window_manager, "window.unpinned_scene"))
    return DeclaredRoles(roles.build, roles.scenes,
                         (*retained, Role(window_manager, "window.unpinned_scene", scene)),
                         roles.real_users, roles.context)


def _particle_class(bpy: Any, kind: str) -> Any:
    cls, base = getattr(bpy.types, kind), bpy.types.bpy_struct
    meta = type(cls)
    if (getattr_static(meta, "__getattribute__", None) is not type.__dict__["__getattribute__"]
            or getattr_static(meta, "__call__", None) is not type.__dict__["__call__"]
            or getattr_static(meta, "__getattr__", None) is not None):
        raise refused("PARTICLE_PREPARATION_METACLASS_CHANGED")
    for slot in ("__getattribute__", "__setattr__", "__init__"):
        native = getattr_static(base, slot, None)
        if type(native) is not WrapperDescriptorType or getattr_static(cls, slot, None) is not native:
            raise refused("PARTICLE_PREPARATION_NATIVE_SLOT_CHANGED")
    constructor = getattr_static(base, "__new__", None)
    if (type(constructor) is not BuiltinFunctionType or getattr_static(cls, "__new__", None) is not constructor
            or getattr_static(cls, "__getattr__", None) is not None
            or getattr_static(cls, "__del__", None) is not None):
        raise refused("PARTICLE_PREPARATION_CONSTRUCTOR_CHANGED")
    return cls


def _particle_field(bpy: Any, owner: Any, kind: str, name: str, category: str,
                    *, target: str | None = None, readonly: bool) -> None:
    """Narrow native declarations for the explicit owned fixture preparation."""
    cls = _particle_class(bpy, kind)
    if type(owner) is not cls or owner.bl_rna.as_pointer() != cls.bl_rna.as_pointer():
        raise refused("PARTICLE_PREPARATION_OWNER_CHANGED")
    descriptor = getattr_static(cls, name, None)
    if descriptor is not None and type(descriptor) not in {GetSetDescriptorType, MemberDescriptorType}:
        raise refused("PARTICLE_PREPARATION_PYTHON_SHADOW")
    prop = cls.bl_rna.properties.get(name)
    if (prop is None or prop.identifier != name or prop.type != category
            or prop.is_runtime is not False or prop.is_registered is not False or prop.is_readonly is not readonly
            or (category == "BOOLEAN" and prop.array_length != 0)
            or (target is not None and prop.fixed_type.identifier != target)):
        raise refused("PARTICLE_PREPARATION_FIELD_UNQUALIFIED")


def _particle_settings(bpy: Any, scene: Any) -> tuple[Any, Any]:
    _particle_class(bpy, "ToolSettings")
    _particle_class(bpy, "ParticleEdit")
    _particle_class(bpy, "Object")
    _particle_field(bpy, scene, "Scene", "tool_settings", "POINTER", target="ToolSettings", readonly=True)
    tools = scene.tool_settings
    _particle_field(bpy, tools, "ToolSettings", "particle_edit", "POINTER", target="ParticleEdit", readonly=True)
    return tools, tools.particle_edit


def authenticate_particle_role(bpy: Any, tool_context: Any, scene: Any, empty: Any,
                               check: Any, effects: list[dict[str, Any]]) -> Role:
    """Explicit same-value native Boolean update establishes a known Scene slot.

    The reviewed synchronous RNA update invokes PE_get_current with the actual
    current Scene and active owned Empty. It assigns the latent editor Scene and
    Object references. This is a declared preparation effect, not a passive read,
    an observed-count baseline, an undo checkpoint or a public mutation tool.
    """
    profile(bpy)
    check()
    tool_context.require(Permission.EDIT_SCENE, Permission.EDIT_ANIMATION)
    before = context(bpy)
    if type(empty) is not _particle_class(bpy, "Object"):
        raise refused("PARTICLE_PREPARATION_OWNED_EMPTY_REQUIRED")
    for name in ("type", "data", "modifiers", "particle_systems", "soft_body", "library", "override_library", "is_editable"):
        descriptor = getattr_static(type(empty), name, None)
        if descriptor is not None and type(descriptor) not in {GetSetDescriptorType, MemberDescriptorType}:
            raise refused("PARTICLE_PREPARATION_PYTHON_SHADOW")
    if (bpy.context.scene is not scene or bpy.context.view_layer.objects.active is not empty
            or empty.type != "EMPTY" or empty.data is not None or len(empty.modifiers)
            or len(empty.particle_systems) or empty.soft_body is not None
            or empty.library is not None or empty.override_library is not None
            or empty.is_editable is not True or bpy.context.mode != "OBJECT"):
        raise refused("PARTICLE_PREPARATION_OWNED_EMPTY_REQUIRED")
    tools, particle = _particle_settings(bpy, scene)
    tools_pointer, particle_pointer = tools.as_pointer(), particle.as_pointer()
    _particle_field(bpy, particle, "ParticleEdit", "show_particles", "BOOLEAN", readonly=False)
    _particle_field(bpy, particle, "ParticleEdit", "object", "POINTER", target="Object", readonly=True)
    value = particle.show_particles
    if type(value) is not bool:
        raise refused("PARTICLE_PREPARATION_BOOLEAN_REQUIRED")
    entry = {"operation": "same_value_show_particles_native_update", "entered": False, "returned": False,
             "native_callback_completed_verified": False, "scene": identity(scene), "object": identity(empty),
             "boolean_before": value, "latent_scene_object_references_assigned_verified": False,
             "previous_latent_scene_unobserved": True, "native_depsgraph_and_notifier_effects_possible": True,
             "deferred_generic_RNA_notifications_may_remain": True,
             "particle_scene_role_proof": "source-inferred synchronous callback; hidden pointer not read",
             "particle_object_readonly_pointer_verified": False,
             "hidden_Main_passivity_qualified": False}
    effects.append(entry)  # Allocation must succeed before native entry.
    check()
    tool_context.require(Permission.EDIT_SCENE, Permission.EDIT_ANIMATION)
    current_tools, current_particle = _particle_settings(bpy, scene)
    _particle_field(bpy, current_particle, "ParticleEdit", "show_particles", "BOOLEAN", readonly=False)
    if (context(bpy) != before or bpy.context.view_layer.objects.active is not empty
            or current_tools.as_pointer() != tools_pointer or current_particle.as_pointer() != particle_pointer
            or empty.soft_body is not None or len(empty.modifiers) or len(empty.particle_systems)
            or current_particle.show_particles is not value):
        raise refused("PARTICLE_PREPARATION_PREFIX_CHANGED")
    particle = current_particle
    _particle_field(bpy, particle, "ParticleEdit", "show_particles", "BOOLEAN", readonly=False)
    entry["entered"] = True
    particle.show_particles = value
    entry["returned"] = True  # Retain the actual assignment return before providers.
    check()
    tool_context.require(Permission.EDIT_SCENE, Permission.EDIT_ANIMATION)
    if context(bpy) != before or bpy.context.view_layer.objects.active is not empty:
        raise refused("PARTICLE_PREPARATION_CONTEXT_CHANGED")
    current_tools, particle = _particle_settings(bpy, scene)
    if current_tools.as_pointer() != tools_pointer or particle.as_pointer() != particle_pointer:
        raise refused("PARTICLE_PREPARATION_PREFIX_CHANGED")
    _particle_field(bpy, particle, "ParticleEdit", "object", "POINTER", target="Object", readonly=True)
    _particle_field(bpy, particle, "ParticleEdit", "show_particles", "BOOLEAN", readonly=False)
    if particle.show_particles is not value or particle.object is not empty:
        raise refused("PARTICLE_PREPARATION_NATIVE_RETURN_UNVERIFIED")
    entry["native_callback_completed_verified"] = True
    entry["latent_scene_object_references_assigned_verified"] = True
    entry["particle_object_readonly_pointer_verified"] = True
    return Role(identity(scene), "particle.scene", identity(scene))
