"""Provider effects never overwrite reserved metadata or move its ownership."""

from __future__ import annotations

import pytest
from test_checkpoint_authority import authority  # noqa: F401
from test_checkpoint_snapshots import Scene


@pytest.mark.parametrize("stage,calls,writes,snapshots", [
    ("delete", 1, 0, 0), ("set", 2, 1, 0), ("native_push", 3, 2, 0),
    ("post_push_delete", 4, 2, 1),
])
def test_late_marker_note_is_preserved_before_every_checkpoint_write(authority, stage, calls, writes, snapshots):
    env = authority
    providers = []
    note = "Unrelated newer note at " + stage
    before_frames, before_position = len(env.stack.frames), env.manager._window.position
    old_checkpoints, old_steps = env.manager.list(), list(env.manager._undo_steps)

    def provider():
        providers.append(True)
        if len(providers) == calls:
            env.stack.scene[env.module.MARKER_KEY] = note
        env.guard()

    with pytest.raises(env.module.BridgeError) as caught:
        env.manager.before_modification("fixture.edit", before_write=provider, after_read=env.guard)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context["checkpoint_marker_unchanged"] is False
    evidence = caught.value.context["checkpoint_bookkeeping"]
    assert evidence["marker_writes_completed"] == writes
    assert evidence["native_snapshots_completed"] == snapshots
    assert not evidence["compensation_performed"]
    assert env.stack.scene[env.module.MARKER_KEY] == note
    assert len(providers) == calls
    assert len(env.stack.frames) == before_frames + snapshots
    assert env.manager._window.position == before_position + snapshots
    assert env.manager.list() == old_checkpoints and list(env.manager._undo_steps) == old_steps


@pytest.mark.parametrize("change", ["context", "ownership", "other_scene_note"])
def test_late_scene_ownership_and_other_reserved_values_are_never_adopted(authority, change):
    env = authority
    scene = env.stack.scene
    other = Scene({env.module.MARKER_KEY: "Preserved foreign note"})
    env.stack.bpy.data.scenes.append(other)
    before_frames, before_marker = len(env.stack.frames), scene[env.module.MARKER_KEY]

    def provider():
        if change == "context":
            env.stack.bpy.context.scene = other
        elif change == "ownership":
            scene.is_editable = False
        else:
            other[env.module.MARKER_KEY] = "New manual foreign note"

    with pytest.raises(env.module.BridgeError) as caught:
        env.manager.before_modification("fixture.edit", before_write=provider, after_read=env.guard)
    assert caught.value.context["checkpoint_marker_unchanged"] is False
    assert caught.value.context["checkpoint_bookkeeping"]["marker_writes_completed"] == 0
    assert scene[env.module.MARKER_KEY] == before_marker and len(env.stack.frames) == before_frames
    if change == "other_scene_note":
        assert other[env.module.MARKER_KEY] == "New manual foreign note"
