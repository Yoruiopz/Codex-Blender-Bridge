from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def boundary(addon_package, monkeypatch):
    proof = importlib.import_module(f"{addon_package}.tools._rigging_edit")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state_module = importlib.import_module(f"{addon_package}.state")
    owner = SimpleNamespace(name="Rig", data=SimpleNamespace(name="Data"), session_uid=1)
    bone = SimpleNamespace(name="Bone", location=(0., 0., 0.), scale=(1., 1., 1.))
    scene = SimpleNamespace(frame_current=1, frame_subframe=0.)
    layer = SimpleNamespace(objects=SimpleNamespace(active=owner))
    bpy = SimpleNamespace(context=SimpleNamespace(scene=scene, view_layer=layer, mode="OBJECT", selected_objects=[owner]),
                          data=SimpleNamespace(filepath="", objects={owner.name: owner}))
    grants = {permission.value: True for permission in permissions.Permission}
    provider = [lambda: grants]
    manager = permissions.PermissionManager(lambda: provider[0]())
    registry = registry_module.ToolRegistry(enabled_toolsets=("rigging",))
    registry.register("rig.pose_transform", lambda *_: None, toolset="rigging", modifies=True,
                      permissions=(permissions.Permission.EDIT_ANIMATION, permissions.Permission.TRANSFORM_OBJECTS))
    context = registry_module.ToolContext(state_module.BridgeState(), manager, registry, None)
    obj = proof.Boundary.__new__(proof.Boundary)
    obj.bpy, obj.context, obj.method, obj.rig = bpy, context, "rig.pose_transform", owner
    obj.kind, obj.bone_name, obj.names = "pose", bone.name, []
    obj.permissions = (permissions.Permission.TRANSFORM_OBJECTS,)
    obj.session = proof._session(bpy)
    obj.original_session = obj.session
    obj.references = ("exact reviewed closure",)
    obj.objects = (owner,)
    obj.identities = ((owner, proof.scope.action_token(owner), proof.scope.action_token(owner.data), owner.name),)
    obj.steps, obj.sources = 0, []
    protected = ["rest, skin, Action and sibling pose"]
    obj._protected = lambda: tuple(protected)
    obj._owned = lambda: (("location", tuple(bone.location)), ("scale", tuple(bone.scale)))
    obj.protected, obj.expected = obj._protected(), obj._owned()
    monkeypatch.setattr(proof.scope, "affected_scope", lambda *_args: ("exact reviewed closure",))
    return SimpleNamespace(proof=proof, boundary=obj, bone=bone, owner=owner, bpy=bpy, context=context,
                           grants=grants, provider=provider, protected=protected, permissions=permissions.Permission)


@pytest.mark.parametrize("stop", ["permission", "pause", "emergency", "cancel", "toolset"])
def test_live_stop_after_first_channel_retains_measured_partial_operation(boundary, stop):
    case = boundary
    case.boundary.write(case.bone, "location", (1., 2., 3.))
    if stop == "permission":
        case.grants[case.permissions.EDIT_ANIMATION.value] = False
    elif stop == "pause":
        case.context.state.set_paused(True)
    elif stop == "emergency":
        case.context.state.set_emergency_stopped(True)
    elif stop == "toolset":
        case.context.registry.disable_toolset("rigging")
    else:
        def cancelled():
            raise case.proof.BridgeError("TIMEOUT", "Caller disconnected or canceled")
        case.context.check_cancelled = cancelled
    with pytest.raises(case.proof.BridgeError) as error:
        case.boundary.write(case.bone, "scale", (2., 2., 2.))
    assert case.bone.location == (1., 2., 3.) and case.bone.scale == (1., 1., 1.)
    assert error.value.context["possible_mutation"]
    assert error.value.context["completed_writes"] == 1
    assert not error.value.context["rollback_verified"]


@pytest.mark.parametrize("change", ["scene", "view_layer", "mode", "filepath", "frame", "active", "selection", "id", "protected", "consumer", "toolset"])
def test_final_permission_provider_cannot_change_reviewed_scope_before_write(boundary, monkeypatch, change):
    case = boundary
    fired = []
    def provider():
        # Registry.prepare consults permissions after the explicit require.
        if len(fired) == 1:
            if change == "scene":
                case.bpy.context.scene = SimpleNamespace(frame_current=1, frame_subframe=0.)
            elif change == "view_layer":
                case.bpy.context.view_layer = SimpleNamespace(objects=SimpleNamespace(active=case.owner))
            elif change == "mode":
                case.bpy.context.mode = "POSE"
            elif change == "filepath":
                case.bpy.data.filepath = "/another.blend"
            elif change == "frame":
                case.bpy.context.scene.frame_current = 2
            elif change == "active":
                case.bpy.context.view_layer.objects.active = None
            elif change == "selection":
                case.bpy.context.selected_objects = []
            elif change == "id":
                case.bpy.data.objects["Rig"] = SimpleNamespace(name="Rig")
            elif change == "protected":
                case.protected[0] = "manual protected edit"
            elif change == "consumer":
                monkeypatch.setattr(case.proof.scope, "affected_scope", lambda *_: ("new external consumer",))
            else:
                case.context.registry.disable_toolset("rigging")
        fired.append(True)
        return case.grants
    case.provider[0] = provider
    with pytest.raises(case.proof.BridgeError):
        case.boundary.write(case.bone, "location", (1., 2., 3.))
    assert len(fired) == 2 and case.bone.location == (0., 0., 0.)


def test_owned_channel_interleaving_is_preserved_and_not_adopted(boundary):
    case = boundary
    case.boundary.write(case.bone, "location", (1., 2., 3.))
    case.bone.location = (8., 9., 10.)
    with pytest.raises(case.proof.BridgeError):
        case.boundary.write(case.bone, "scale", (2., 2., 2.))
    assert case.bone.location == (8., 9., 10.) and case.bone.scale == (1., 1., 1.)


def test_noop_still_requires_live_permission(boundary):
    case = boundary
    case.grants[case.permissions.EDIT_ANIMATION.value] = False
    with pytest.raises(case.proof.BridgeError):
        case.boundary.write(case.bone, "location", (0., 0., 0.))
    assert case.boundary.steps == 0


def test_scheduler_deadline_is_checked_after_content_read_before_write(boundary):
    case = boundary
    events = []
    protected = case.boundary._protected
    def capture():
        events.append("content")
        return protected()
    case.boundary._protected = capture
    def final_job():
        assert events == ["content"]
        raise case.proof.BridgeError("TIMEOUT", "Deadline expired while reading protected skin")
    case.context.check_final_job = final_job
    with pytest.raises(case.proof.BridgeError) as error:
        case.boundary.write(case.bone, "location", (1., 2., 3.))
    assert error.value.code == "TIMEOUT" and not error.value.context["possible_mutation"]
    assert case.bone.location == (0., 0., 0.)


def test_context_write_cannot_adopt_callback_frame_change(boundary, monkeypatch):
    case = boundary
    monkeypatch.setattr(case.proof, "_common_geometry", lambda _: ())
    monkeypatch.setattr(case.proof, "_rest", lambda *_: ())
    monkeypatch.setattr(case.proof, "_pose", lambda _: ())
    def setter():
        case.bpy.context.selected_objects = []
        case.bpy.context.scene.frame_current = 99
    with pytest.raises(case.proof.BridgeError, match="Context transition"):
        case.boundary.contextual(setter, change=(5, ()))
    assert case.bpy.context.scene.frame_current == 99
    assert case.boundary.session[6] == 1


@pytest.mark.parametrize("affected,animated", [(["Skin"], False), ([], True)])
def test_native_rename_and_removal_propagation_is_rejected_before_context(addon_package, affected, animated):
    proof = importlib.import_module(f"{addon_package}.tools._rigging_edit")
    rig = SimpleNamespace(animation_data=object() if animated else None, data=SimpleNamespace(animation_data=None), pose=SimpleNamespace(bones=[]))
    with pytest.raises(proof.BridgeError, match="propagation transaction"):
        proof.require_independent_rest(rig, affected, "Renaming")


def test_creation_failure_reports_exact_retained_ids_without_deletion(addon_package):
    proof = importlib.import_module(f"{addon_package}.tools._rigging_edit")
    creation = proof.Creation.__new__(proof.Creation)
    creation.created = [SimpleNamespace(name="New Rig", session_uid=41, bl_rna=SimpleNamespace(identifier="Object"))]
    error = creation.failure(proof.BridgeError("PERMISSION_DENIED", "Revoked"))
    assert error.code == "PERMISSION_DENIED"
    assert error.context["retained_ids"][0]["name"] == "New Rig"
    assert error.context["retained_ids"][0]["identity"][1] == 41
    assert not error.context["automatic_id_deletion"]
