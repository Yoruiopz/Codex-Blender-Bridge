"""Blender-free native-identity/permission NLA fixtures; native RNA remains separately tested."""

from __future__ import annotations

from types import SimpleNamespace as NS


class ID(NS):
    __eq__ = object.__eq__
    __hash__ = object.__hash__

    def __init__(self, name, **values):
        super().__init__(name=name, library=None, override_library=None, is_editable=True, **values)

    def keys(self):
        return ()


class Items(list):
    active = None

    def get(self, name):
        return next((item for item in self if item.name == name), None)


class Strips(Items):
    def new(self, name, start, action):
        first, last = action.frame_range
        strip = NS(name=name, type="CLIP", action=action, action_slot=None,
                   action_frame_start=first, action_frame_end=last, frame_start=float(start),
                   frame_end=start+last-first, scale=1., repeat=1., influence=0.,
                   blend_type="REPLACE", extrapolation="HOLD", mute=False, select=True,
                   active=False, use_auto_blend=False, use_animated_influence=False,
                   blend_in=0., blend_out=0., fcurves=[], modifiers=[], strips=[])
        self.append(strip)
        self.sort(key=lambda item: item.frame_start)
        return strip


class Tracks(Items):
    fail_strip = False

    def new(self, **_kwargs):
        track = NS(name="NlaTrack", lock=False, mute=False, is_solo=False, select=True, strips=Strips())
        if self.fail_strip:
            def fail(*_args):
                raise RuntimeError("injected strip creation failure")
            track.strips.new = fail
        self.append(track)
        self.active = track
        return track

    def remove(self, item):
        super().remove(item)
        if self.active is item:
            self.active = None


def make_env(module, monkeypatch, permission_module, *, data=None, tracks=None):
    tracks = Tracks() if tracks is None else tracks
    if data is None:
        data = NS(action=None, action_slot=None, use_tweak_mode=False, use_nla=True, drivers=[],
                  nla_tracks=tracks, action_blend_type="REPLACE", action_extrapolation="HOLD", action_influence=1.)
    else:
        data.nla_tracks = tracks
        data.use_tweak_mode = False
    obj = ID("Actor", type="EMPTY", data=None, animation_data=data, mode="OBJECT", rotation_mode="XYZ")
    obj.bl_rna = NS(identifier="Object")
    obj.select_get = lambda: True
    objects = Items([obj])
    objects.active = obj
    obj.user_of_id = lambda action: int(obj.animation_data.action is action) + sum(
        int(strip.action is action) for track in tracks for strip in track.strips)
    scene = ID("Scene", objects=objects, frame_current=1, frame_subframe=0.)
    obj.users_scene, obj.users_collection = [scene], []
    actions = Items()
    def action(name="Walk"):
        result = ID(name, is_action_layered=False, is_action_legacy=True, slots=[], layers=[],
                    fcurves=[], groups=[], pose_markers=[], asset_data=None, use_fake_user=False,
                    frame_range=(1., 11.))
        # A property descriptor supplies live users, not a captured integer.
        result.__class__ = type("Action", (ID,), {"users": property(lambda self: obj.user_of_id(self))})
        actions.append(result)
        return result
    def users(*, subset):
        return {item: {obj} if item in actions and obj.user_of_id(item) else set() for item in subset}
    bpy = NS(data=NS(objects=objects, actions=actions, user_map=users, filepath=""),
             context=NS(scene=scene, mode="OBJECT", view_layer=NS(objects=objects), selected_objects=[obj]))
    flags = {"paused": False, "emergency_stopped": False}
    grants = {permission.value: True for permission in permission_module.Permission}
    manager = permission_module.PermissionManager(lambda: grants)
    context = NS(state=NS(snapshot=lambda: dict(flags)), require=lambda *required: manager.require(required),
                 permissions=manager, registry=None, check_cancelled=lambda: None)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_object", lambda *_args: obj)
    if hasattr(module, "inspect"):
        monkeypatch.setattr(module, "inspect", lambda *_args: {"tracks": [track.name for track in tracks]})
    return NS(bpy=bpy, obj=obj, data=data, tracks=tracks, flags=flags, grants=grants,
              context=context, actions=actions, action=action)
