from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


class Scenes(list):
    def get(self, name):
        return next((scene for scene in self if scene.name == name), None)


class Scene:
    def __init__(self):
        self.name, self.library, self.override_library, self.is_editable = "Timeline", None, None, True
        self.session_uid = 1
        self.frame_current, self.frame_subframe = 1, 0.
        self.frame_start, self.frame_end = 1, 250
        self.use_preview_range = False
        self.frame_preview_start, self.frame_preview_end = 1, 250
        self.on_write, self.writes, self.armed = None, [], True

    @property
    def frame_current_final(self):
        return self.frame_current + self.frame_subframe

    def __setattr__(self, name, value):
        if getattr(self, "armed", False):
            # Reviewed native RNA semantics from rna_scene.cc, independently
            # retained by the real 4.5/5.2 fixture's preview sentinel probe.
            if name == "frame_start" and value > self.frame_end:
                object.__setattr__(self, "frame_end", value)
            elif name == "frame_end" and value < self.frame_start:
                object.__setattr__(self, "frame_start", value)
            elif name == "use_preview_range" and value and self.frame_preview_start == self.frame_preview_end == 0:
                object.__setattr__(self, "frame_preview_start", self.frame_start)
                object.__setattr__(self, "frame_preview_end", self.frame_end)
            elif name == "frame_preview_start":
                if not self.use_preview_range:
                    object.__setattr__(self, "frame_preview_end", self.frame_end)
                if value > self.frame_preview_end:
                    object.__setattr__(self, "frame_preview_end", value)
            elif name == "frame_preview_end":
                if not self.use_preview_range:
                    object.__setattr__(self, "frame_preview_start", self.frame_start)
                if value < self.frame_preview_start:
                    object.__setattr__(self, "frame_preview_start", value)
        object.__setattr__(self, name, value)
        if getattr(self, "armed", False) and name in {"frame_start", "frame_end", "frame_preview_start", "frame_preview_end", "use_preview_range"}:
            self.writes.append((name, value))
            if self.on_write is not None:
                self.on_write(self, name, value)

    def frame_set(self, frame, *, subframe=0.):
        self.frame_current, self.frame_subframe = frame, subframe


@pytest.fixture
def timeline(addon_package, monkeypatch):
    mutation = importlib.import_module(f"{addon_package}.tools._animation_mutation")
    animation = importlib.import_module(f"{addon_package}.tools.animation")
    scene = Scene()
    flags = {"paused": False, "emergency_stopped": False}
    grants = {"EDIT_ANIMATION": True}

    def require(*permissions):
        if any(not grants.get(permission.value, False) for permission in permissions):
            raise mutation.BridgeError(mutation.ErrorCode.PERMISSION_DENIED, "Denied")

    context = NS(check_cancelled=None, state=NS(snapshot=lambda: dict(flags)), require=require, registry=None)
    bpy = NS(context=NS(scene=scene, view_layer=object(), mode="OBJECT"), data=NS(filepath="", scenes=Scenes([scene])))
    monkeypatch.setattr(animation, "require_blender", lambda: bpy)
    return NS(mutation=mutation, animation=animation, bpy=bpy, context=context, scene=scene, flags=flags, grants=grants)


@pytest.mark.parametrize("stop", ["paused", "emergency_stopped", "permission", "cancel"])
def test_timeline_live_gate_prevents_first_write(timeline, stop):
    boundary = timeline.mutation.Timeline(timeline.bpy, timeline.context, "animation.set_range")
    if stop == "permission":
        timeline.grants["EDIT_ANIMATION"] = False
    elif stop == "cancel":
        timeline.context.check_cancelled = lambda: (_ for _ in ()).throw(timeline.mutation.BridgeError("OPERATION_FAILED", "Canceled"))
    else:
        timeline.flags[stop] = True
    with pytest.raises(timeline.mutation.BridgeError):
        boundary.write("frame_start", 10)
    assert not timeline.scene.writes and not boundary.started


@pytest.mark.parametrize("change", ["scene", "scene_uid", "view_layer", "project", "mode", "range"])
def test_timeline_refuses_stale_context_or_manual_range_changes(timeline, change):
    boundary = timeline.mutation.Timeline(timeline.bpy, timeline.context, "animation.set_range")
    if change == "scene":
        timeline.bpy.context.scene = Scene()
    elif change == "scene_uid":
        timeline.scene.session_uid = 2
    elif change == "view_layer":
        timeline.bpy.context.view_layer = object()
    elif change == "project":
        timeline.bpy.data.filepath = "/manual/reopened.blend"
    elif change == "mode":
        timeline.bpy.context.mode = "POSE"
    else:
        timeline.scene.frame_end = 700
    before = list(timeline.scene.writes)
    with pytest.raises(timeline.mutation.BridgeError):
        boundary.write("frame_start", 10)
    assert timeline.scene.writes == before


@pytest.mark.parametrize("stop", ["paused", "emergency_stopped", "permission", "cancel"])
def test_partial_range_stop_retains_measured_state_without_late_compensation(timeline, stop):
    def callback():
        if timeline.scene.frame_start != 10:
            return
        if stop == "permission":
            timeline.grants["EDIT_ANIMATION"] = False
        elif stop == "cancel":
            raise timeline.mutation.BridgeError("OPERATION_FAILED", "Canceled/disconnected")
        else:
            timeline.flags[stop] = True

    timeline.context.check_cancelled = callback
    with pytest.raises(timeline.mutation.BridgeError) as error:
        timeline.animation.set_range(timeline.context, {"start": 10, "end": 100})
    assert (timeline.scene.frame_start, timeline.scene.frame_end) == (10, 250)
    assert timeline.scene.writes == [("frame_start", 10)]
    assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]


def test_one_shot_range_failure_has_measured_compensation(timeline):
    fired = False

    def callback():
        nonlocal fired
        if timeline.scene.frame_start == 10 and not fired:
            fired = True
            raise RuntimeError("One-shot injected fault")

    timeline.context.check_cancelled = callback
    with pytest.raises(timeline.mutation.BridgeError) as error:
        timeline.animation.set_range(timeline.context, {"start": 10, "end": 100})
    assert fired and (timeline.scene.frame_start, timeline.scene.frame_end) == (1, 250)
    assert error.value.context["rollback_verified"] and not error.value.context["possible_mutation"]


def test_manual_coupled_range_edit_is_not_adopted_or_overwritten(timeline):
    fired = False

    def on_write(scene, name, value):
        nonlocal fired
        if name == "frame_start" and value == 10 and not fired:
            fired = True
            object.__setattr__(scene, "frame_end", 777)

    timeline.scene.on_write = on_write
    with pytest.raises(timeline.mutation.BridgeError) as error:
        timeline.animation.set_range(timeline.context, {"start": 10, "end": 100})
    assert fired and timeline.scene.frame_end == 777
    assert timeline.scene.writes == [("frame_start", 10)]
    assert not error.value.context["rollback_verified"]


def test_frame_late_denial_reports_the_actual_previous_timeline(timeline):
    def callback():
        if timeline.scene.frame_current_final == 12.25:
            timeline.grants["EDIT_ANIMATION"] = False

    timeline.context.check_cancelled = callback
    with pytest.raises(timeline.mutation.BridgeError) as error:
        timeline.animation.set_frame(timeline.context, {"frame": 12.25})
    assert timeline.scene.frame_current_final == 12.25
    assert error.value.context["previous_timeline"]["frame_current"] == 1
    assert error.value.context["previous_timeline"]["frame_subframe"] == 0.
    assert error.value.context["observed_timeline"]["frame_current"] == 12
    assert error.value.context["possible_mutation"] and not error.value.context["automatic_frame_replay_attempted"]


def test_unset_preview_initialization_and_explicit_subrange_are_predicted(timeline):
    object.__setattr__(timeline.scene, "frame_preview_start", 0)
    object.__setattr__(timeline.scene, "frame_preview_end", 0)
    result = timeline.animation.set_range(timeline.context, {"start": 1, "end": 40, "use_preview": True,
                                                           "preview_start": 2, "preview_end": 30})
    assert result["use_preview_range"] and (result["preview_start"], result["preview_end"]) == (2, 30)


def test_enabled_zero_preview_is_preserved_without_redundant_native_toggle(timeline):
    object.__setattr__(timeline.scene, "frame_preview_start", 0)
    object.__setattr__(timeline.scene, "frame_preview_end", 0)
    result = timeline.animation.set_range(timeline.context, {"start": 0, "end": 10, "use_preview": True,
                                                           "preview_start": 0, "preview_end": 0})
    assert result["use_preview_range"] and (result["preview_start"], result["preview_end"]) == (0, 0)
