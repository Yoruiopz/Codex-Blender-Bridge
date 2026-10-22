"""The optional trusted hook follows actual native completion and retains failure."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from test_checkpoint_authority import authority  # noqa: F401


@pytest.mark.parametrize("route", ("before", "create", "after", "editor"))
def test_completion_hook_runs_after_actual_push_before_following_providers(authority, route):
    case = authority
    if route in {"after", "editor"}:
        assert case.manager.before_modification("owned existing writer")
    if route == "editor":
        case.stack.scene.session_uid = 11
        case.stack.bpy.context.active_object = NS(name="Mesh", session_uid=22)
        case.manager._editor_session = case.module.MeshEditSession(case.manager._pending, "group", 11, 22, "Mesh")
        case.manager._pending = None
    frames, position = len(case.stack.frames), case.manager._window.position
    events = []
    def before():
        events.append("provider")
        case.guard()
    def complete():
        assert len(case.stack.frames) == frames + 1
        assert case.manager._window.position == position + 1
        events.append("completed")
    kwargs = dict(before_write=before, after_read=case.guard, after_native_push=complete)
    if route == "before":
        assert case.manager.before_modification("fixture.edit", **kwargs)
    elif route == "create":
        case.manager.create("owned named checkpoint", **kwargs)
    elif route == "after":
        assert case.manager.after_modification("fixture.edit", **kwargs)
    else:
        assert case.manager.finish_editor_session(**kwargs)["state"] == "finalized"
    assert events.count("completed") == 1
    assert events[:3] == ["provider"] * 3
    assert events[3] == "completed"


def test_hook_failure_retains_native_count_marker_and_exact_denial_without_retry(authority):
    case = authority
    frames, position, listed = len(case.stack.frames), case.manager._window.position, case.manager.list()
    denial = case.module.BridgeError("NOT_IMPLEMENTED", "Exact completion CAS denied")
    calls = []
    def complete():
        calls.append(True)
        raise denial
    with pytest.raises(case.module.BridgeError) as caught:
        case.manager.before_modification("fixture.edit", before_write=case.guard,
                                        after_read=case.guard, after_native_push=complete)
    assert caught.value is denial and calls == [True]
    assert denial.context["checkpoint_bookkeeping"] == {
        "marker_writes_completed": 2, "native_snapshots_completed": 1,
        "next_write_rejected": "after_native_undo_push", "compensation_performed": False}
    assert denial.context["execution_started"] and denial.context["possible_mutation"]
    assert len(case.stack.frames) == frames + 1 and case.manager._window.position == position + 1
    assert case.stack.scene[case.module.MARKER_KEY] == case.stack.frames[-1][case.module.MARKER_KEY]
    assert case.manager.list() == listed


def test_cancelled_native_push_never_notifies_completion(authority, monkeypatch):
    case = authority
    calls = []
    monkeypatch.setattr(case.stack.bpy.ops.ed, "undo_push", lambda **_kwargs: {"CANCELLED"})
    assert case.manager.before_modification("fixture.edit", before_write=case.guard,
        after_read=case.guard, after_native_push=lambda: calls.append(True)) is False
    assert calls == []
