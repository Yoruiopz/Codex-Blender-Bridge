from __future__ import annotations

import copy
import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def binding(addon_package):
    return importlib.import_module(f"{addon_package}.tools._rig_binding")


@pytest.fixture
def states():
    matrix = tuple(tuple(float(row == column) for column in range(4)) for row in range(4))
    before = {"groups": ((101, "Upper", 0, False), (102, "Protected", 1, True)),
              "weights": (((0, .2), (1, .123)), ((0, .7), (1, .123))),
              "modifiers": ((201, (("object", 11),), ()),), "parent": None, "world": matrix}
    after = copy.deepcopy(before)
    after.update(groups=(*before["groups"], (103, "Lower", 2, False)), parent=11,
                 weights=(((0, .4), (1, .123), (2, .6)), ((0, .1), (1, .123), (2, .9))))
    return before, after


def test_native_allocation_preserves_preexisting_exact_group_and_modifier_ids(binding, states):
    before, after = states
    binding._allocation_shape(before, after, ("Upper", "Lower"), 11, parent=True)
    coverage = binding._weight_shape(before, after, ("Upper", "Lower"), automatic=True)
    assert coverage["positive_deform_coverage"]
    assert not coverage["normalization_certified"]


@pytest.mark.parametrize("change", ["group_id", "group_name", "group_lock", "group_reorder", "extra_group", "modifier_id", "modifier_rna", "extra_modifiers", "parent", "world"])
def test_native_output_cannot_claim_unknown_allocations_or_protected_state(binding, states, change):
    before, after = states
    groups = list(after["groups"])
    if change == "group_id":
        groups[0] = (999, *groups[0][1:])
    elif change == "group_name":
        groups[0] = (groups[0][0], "Foreign", *groups[0][2:])
    elif change == "group_lock":
        groups[0] = (*groups[0][:3], True)
    elif change == "group_reorder":
        groups[0], groups[1] = groups[1], groups[0]
    elif change == "extra_group":
        groups.append((104, "Foreign", 3, False))
    elif change == "modifier_id":
        after["modifiers"] = ((999, *after["modifiers"][0][1:]),)
    elif change == "modifier_rna":
        after["modifiers"] = ((201, (("object", 12),), ()),)
    elif change == "extra_modifiers":
        after["modifiers"] *= 3
    elif change == "parent":
        after["parent"] = 12
    else:
        after["world"] = tuple((2., *row[1:]) if index == 0 else row for index, row in enumerate(after["world"]))
    after["groups"] = tuple(groups)
    with pytest.raises(binding.BridgeError):
        binding._allocation_shape(before, after, ("Upper", "Lower"), 11, parent=True)


@pytest.mark.parametrize("automatic", [True, False])
def test_protected_locked_unrelated_memberships_are_exact(binding, states, automatic):
    before, after = states
    after["weights"] = (((0, .4), (1, .124), (2, .6)), after["weights"][1])
    with pytest.raises(binding.BridgeError, match="protected unrelated"):
        binding._weight_shape(before, after, ("Upper", "Lower"), automatic=automatic)


def test_empty_groups_cannot_rewrite_existing_deform_weights(binding, states):
    before, after = states
    with pytest.raises(binding.BridgeError, match="Empty-group"):
        binding._weight_shape(before, after, ("Upper", "Lower"), automatic=False)


@pytest.mark.parametrize("total", [0., 1e-9])
def test_finished_native_solver_without_positive_deform_coverage_fails(binding, states, total):
    before, after = states
    after["weights"] = (((0, total), (1, .123)), after["weights"][1])
    with pytest.raises(binding.BridgeError, match="incomplete deform coverage"):
        binding._weight_shape(before, after, ("Upper", "Lower"), automatic=True)


def test_observed_native_heat_total_need_not_be_one(binding, states):
    before, after = states
    after["weights"] = (((0, .3), (1, .123), (2, .688)), after["weights"][1])
    result = binding._weight_shape(before, after, ("Upper", "Lower"), automatic=True)
    assert result["deform_weight_total_min"] == pytest.approx(.988)
    assert not result["normalization_certified"]


@pytest.fixture
def boundary(binding):
    flags, grants = {}, {"EDIT_ANIMATION": True, "TRANSFORM_OBJECTS": True, "EDIT_MESH": True}
    def require(*permissions):
        if any(not grants[item.value] for item in permissions):
            raise binding.BridgeError("PERMISSION_DENIED", "Denied")
    context = NS(require=require, registry=None, check_cancelled=None, state=NS(snapshot=lambda: dict(flags)))
    bpy = NS(context=NS(scene=object(), view_layer=object(), mode="OBJECT"), data=NS(filepath=""))
    current = {"context": ("original",), "scope": ("exact roots",), "protected": ("stored geometry",),
               "binding": {"weights": ("old",), "groups": ("original identity",)}}
    tx = object.__new__(binding.Binding)
    tx.bpy, tx.context = bpy, context
    tx.guard = binding.scope.Guard(bpy, context, "rig.bind_mesh")
    tx.expected = copy.deepcopy(current)
    tx.original = copy.deepcopy(current)
    tx.changed, tx.owned_output, tx.blocked = False, True, None
    tx.read = lambda: copy.deepcopy(current)
    return NS(tx=tx, current=current, grants=grants, flags=flags, context=context, bpy=bpy, module=binding)


@pytest.mark.parametrize("stop", ["paused", "emergency_stopped", "EDIT_MESH", "TRANSFORM_OBJECTS", "EDIT_ANIMATION", "cancel", "mode", "project", "scene", "view_layer", "manual_weight", "protected", "scope"])
def test_last_live_boundary_blocks_writes_and_recovery(boundary, stop):
    env = boundary
    if stop in env.grants:
        env.grants[stop] = False
    elif stop in {"paused", "emergency_stopped"}:
        env.flags[stop] = True
    elif stop == "cancel":
        env.context.check_cancelled = lambda: (_ for _ in ()).throw(env.module.BridgeError("TIMEOUT", "Canceled/disconnected"))
    elif stop == "mode":
        env.bpy.context.mode = "POSE"
    elif stop == "project":
        env.bpy.data.filepath = "/manual/project.blend"
    elif stop in {"scene", "view_layer"}:
        setattr(env.bpy.context, stop, object())
    elif stop == "manual_weight":
        env.current["binding"]["weights"] = ("manual",)
    else:
        env.current[stop] = ("manual",)
    writes = []
    with pytest.raises(env.module.BridgeError):
        env.tx.write(lambda: writes.append("write"), {"weights"})
    with pytest.raises(env.module.BridgeError):
        env.tx.recover()
    assert not writes and not env.tx.changed


def test_final_permission_provider_session_change_is_detected(boundary):
    env = boundary
    env.context.registry = NS(prepare=lambda *_: setattr(env.bpy.context, "mode", "POSE"),
                              get=lambda _: NS(toolset="rigging"), enabled_toolsets=("rigging",))
    writes = []
    with pytest.raises(env.module.BridgeError):
        env.tx.write(lambda: writes.append("write"), {"weights"})
    assert not writes


def test_observed_known_write_receipt_is_frozen_before_following_callbacks(boundary):
    env = boundary
    env.tx.write(lambda: env.current["binding"].update(weights=("native",)), {"weights"})
    assert env.tx.expected["binding"]["weights"] == ("native",)
    env.context.check_cancelled = lambda: env.current["binding"].update(weights=("manual",))
    with pytest.raises(env.module.BridgeError):
        env.tx.gate()
    assert env.current["binding"]["weights"] == ("manual",)
    assert env.tx.expected["binding"]["weights"] == ("native",)


@pytest.mark.parametrize("unknown", ["groups", "protected", "context"])
def test_unexpected_write_effect_is_not_adopted_for_compensation(boundary, unknown):
    env = boundary
    def write():
        env.current["binding"]["weights"] = ("native",)
        if unknown == "groups":
            env.current["binding"]["groups"] = ("foreign identity",)
        else:
            env.current[unknown] = ("manual",)
    with pytest.raises(env.module.BridgeError):
        env.tx.write(write, {"weights"})
    assert env.tx.expected == env.tx.original
    with pytest.raises(env.module.BridgeError):
        env.tx.recover()
    assert env.current["binding"]["weights"] == ("native",)


def test_unknown_native_output_has_no_recovery_ownership(boundary):
    boundary.tx.owned_output = False
    assert boundary.tx.recover() is False


@pytest.mark.parametrize("stop", ["paused", "emergency_stopped", "EDIT_MESH", "cancel"])
def test_transient_authority_interruption_stays_latched_after_preferences_recover(boundary, stop):
    env = boundary
    if stop in env.grants:
        env.grants[stop] = False
    elif stop == "cancel":
        env.context.check_cancelled = lambda: (_ for _ in ()).throw(env.module.BridgeError("TIMEOUT", "Canceled"))
    else:
        env.flags[stop] = True
    with pytest.raises(env.module.BridgeError):
        env.tx.gate()
    env.grants.update({name: True for name in env.grants})
    env.flags.clear()
    env.context.check_cancelled = None
    writes = []
    with pytest.raises(env.module.BridgeError):
        env.tx.write(lambda: writes.append(True), {"weights"})
    assert not writes


@pytest.mark.parametrize("references", [((1, 2, 1),), ((1, 3, 1), (3, 2, 1)), ((1, 3, 1), (3, 4, 1), (4, 2, 1))])
def test_binding_rejects_direct_and_nested_dependency_cycles_before_mutation(binding, references):
    with pytest.raises(binding.BridgeError, match="dependency cycle"):
        binding._no_cycle(((), references), 1, 2)


def test_existing_mesh_dependency_on_rig_is_the_expected_forward_edge(binding):
    binding._no_cycle(((), ((2, 1, 2),)), 1, 2)


@pytest.fixture
def multi_scope(binding, monkeypatch):
    class Object:
        def __init__(self, name):
            self.name, self.session_uid, self.data, self.users_collection = name, 1, None, []
            self.bl_rna = NS(identifier="Object")
        def user_of_id(self, target):
            return counts.get((target, self), 0)
    rig, mesh, prop = (Object(name) for name in ("Rig", "Skin", "Prop"))
    owners, counts = {rig: [mesh]}, {(rig, mesh): 2}
    bpy = NS(context=NS(scene=NS(objects=[rig, mesh, prop])), data=NS(user_map=lambda *, subset: {obj: owners.get(obj, []) for obj in subset}))
    monkeypatch.setattr(binding.scope, "object_scope", lambda *_: None)
    monkeypatch.setattr(binding.scope, "_ordinary_scene_membership", lambda *_: False)
    return NS(module=binding, bpy=bpy, rig=rig, mesh=mesh, prop=prop, owners=owners, counts=counts)


def test_explicit_second_root_allows_only_its_exact_native_consumer_references(multi_scope):
    env = multi_scope
    result = env.module.scope.affected_scope(env.bpy, env.rig, [], additional_roots=(env.mesh,))
    assert len(result[0]) == 2
    assert result[1] == ((id(env.rig), id(env.mesh), 2),)


def test_single_root_api_keeps_old_no_implicit_consumer_contract(multi_scope):
    env = multi_scope
    with pytest.raises(env.module.BridgeError):
        env.module.scope.affected_scope(env.bpy, env.rig, [])


@pytest.mark.parametrize("names", [["Rig"], ["Skin"], ["Prop"]])
def test_two_root_scope_rejects_root_aliases_and_unused_affected_names(multi_scope, names):
    env = multi_scope
    with pytest.raises(env.module.BridgeError):
        env.module.scope.affected_scope(env.bpy, env.rig, names, additional_roots=(env.mesh,))


def test_two_root_scope_still_requires_every_transitive_dependent(multi_scope):
    env = multi_scope
    env.owners[env.mesh] = [env.prop]
    env.counts[(env.mesh, env.prop)] = 1
    with pytest.raises(env.module.BridgeError):
        env.module.scope.affected_scope(env.bpy, env.rig, [], additional_roots=(env.mesh,))
    result = env.module.scope.affected_scope(env.bpy, env.rig, ["Prop"], additional_roots=(env.mesh,))
    assert len(result[0]) == 3 and len(result[1]) == 2


def test_two_root_scope_rejects_duplicate_roots(multi_scope):
    env = multi_scope
    with pytest.raises(env.module.BridgeError):
        env.module.scope.affected_scope(env.bpy, env.rig, [], additional_roots=(env.rig,))


def test_last_permission_provider_cannot_disable_toolset_and_allow_a_write(boundary):
    env = boundary
    registry = NS(get=lambda _: NS(toolset="rigging"), enabled_toolsets=("rigging",))
    registry.prepare = lambda *_: setattr(registry, "enabled_toolsets", ())
    env.context.registry = registry
    writes = []
    with pytest.raises(env.module.BridgeError) as error:
        env.tx.write(lambda: writes.append(True), {"weights"})
    assert error.value.code == "TOOLSET_DISABLED" and not writes
    registry.enabled_toolsets = ("rigging",)
    registry.prepare = lambda *_: None
    with pytest.raises(env.module.BridgeError):
        env.tx.recover()


def test_cancel_or_disconnect_inside_final_permission_provider_blocks_first_write(boundary):
    env = boundary
    lifetime = NS(canceled=False)
    env.context.registry = NS(prepare=lambda *_: setattr(lifetime, "canceled", True),
                              get=lambda _: NS(toolset="rigging"), enabled_toolsets=("rigging",))
    def check():
        if lifetime.canceled:
            raise env.module.BridgeError("TIMEOUT", "Queued caller disconnected during authorization")
    env.context.check_cancelled = check
    writes = []
    with pytest.raises(env.module.BridgeError) as error:
        env.tx.write(lambda: writes.append(True), {"weights"})
    assert error.value.code == "TIMEOUT" and not writes


def test_scheduler_deadline_after_complete_cas_read_blocks_write_and_latches(boundary):
    env = boundary
    lifetime = NS(expired=False)
    original_read = env.tx.read
    def read():
        result = original_read()
        lifetime.expired = True
        return result
    def final():
        if lifetime.expired:
            raise env.module.BridgeError("TIMEOUT", "Expired while measuring scope")
    env.tx.read = read
    env.context.check_final_job = final
    writes = []
    with pytest.raises(env.module.BridgeError):
        env.tx.write(lambda: writes.append(True), {"weights"})
    env.context.check_final_job = None
    with pytest.raises(env.module.BridgeError):
        env.tx.recover()
    assert not writes


def test_custom_split_normals_refused_before_temporary_bmesh_allocation(binding, monkeypatch):
    mesh_surface = importlib.import_module(binding.__package__ + ".mesh_surface")
    allocations = []
    monkeypatch.setattr(mesh_surface, "bmesh", NS(new=lambda: allocations.append(True)))
    with pytest.raises(binding.BridgeError, match="split-normal preservation"):
        binding._geometry(NS(data=NS(has_custom_normals=True)))
    assert not allocations
