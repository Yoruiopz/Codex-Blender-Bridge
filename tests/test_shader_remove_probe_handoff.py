"""Portable event-order checks; these do not qualify Blender's native context."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import traceback
from itertools import islice
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def probe():
    source = Path(__file__).resolve().parents[1] / "scripts/blender_shader_remove_probe_smoke.py"
    names = {"digest", "assert_same", "persistent_core_projection", "condition_loaded_fixture", "reader", "advance_phase"}
    definitions = ast.parse(source.read_text())
    definitions.body = [node for node in definitions.body if isinstance(node, ast.FunctionDef) and node.name in names]
    callbacks, events, finished = [], [], []
    context = SimpleNamespace(window=object(), screen=object())

    def open_mainfile(**_kwargs):
        events.append("load")
        context.window = context.screen = None
        return {"FINISHED"}

    timers = SimpleNamespace(register=lambda callback, **_kwargs: callbacks.append(callback))
    wm = SimpleNamespace(open_mainfile=open_mainfile, quit_blender=lambda: events.append("quit"))
    bpy = SimpleNamespace(context=context, app=SimpleNamespace(timers=timers, version_string="modeled"),
        ops=SimpleNamespace(wm=wm))
    namespace = {"copy": copy, "hashlib": hashlib, "json": json, "traceback": traceback,
        "islice": islice, "bpy": bpy, "JOURNAL": {"cases": []}}
    exec(compile(definitions, str(source), "exec"), namespace)
    return SimpleNamespace(functions=namespace, callbacks=callbacks, events=events, finished=finished, context=context)


def seed(probe, tmp_path, *, fail_snapshot=False, changed_selection=False):
    before = {"graphs": {"tree": {"properties": {"is_runtime_data": True}}},
        "owner_properties": {}, "runtime_flags": {"tree": True}, "context": {"selected": ["Cube"], "active": "Cube"}}
    expected, _ = probe.functions["persistent_core_projection"](before)
    calls = []

    def snapshot(_refs):
        calls.append("snapshot")
        if "load" in probe.events:
            assert probe.context.window is not None
            if fail_snapshot:
                raise ValueError("injected exact post-load comparison failure")
            if changed_selection:
                altered = copy.deepcopy(expected)
                altered["context"]["selected"] = ["Other"]
                return altered, {}
            return expected, {}
        return before, {}

    def inventory(_refs):
        return {"tree": {"is_runtime_data": "load" not in probe.events, "embedded": True,
            "runtime_status_readonly": True, "evaluated": False, "linked": False, "override": False}}

    probe.functions.update(snapshot=snapshot, runtime_inventory=inventory,
        serialize_owned_fixture=lambda *_args: probe.events.append("serialize") or {"fixture_native_save": True})

    def phase():
        yield from probe.functions["condition_loaded_fixture"](None, [{"kind": "GROUP", "name": "Leaf"}], tmp_path)
        probe.events.append("measurement")
        return {"verified": True}

    return phase(), calls


def resume(probe):
    probe.context.window, probe.context.screen = object(), object()
    probe.callbacks.pop(0)()


def test_owned_seed_reload_returns_to_event_loop_before_snapshot_or_measurement(probe, tmp_path):
    phase, reads = seed(probe, tmp_path)
    probe.functions["advance_phase"](phase, probe.finished.append)
    assert probe.events == ["serialize", "load"]
    assert len(reads) == 2 and probe.finished == [] and len(probe.callbacks) == 1
    resume(probe)
    assert len(reads) == 3 and probe.events == ["serialize", "load", "measurement"]
    assert probe.finished == [{"verified": True}]
    assert probe.functions["JOURNAL"]["fixture_origin"]["post_load_snapshot_on_separate_timer_turn"] is True
    assert len(probe.callbacks) == 1  # Only the terminal quit remains.


@pytest.mark.parametrize("failure", ["snapshot", "missing_window", "selection"])
def test_failed_post_load_context_never_retries_or_emits_success(probe, tmp_path, failure, capsys):
    phase, reads = seed(probe, tmp_path, fail_snapshot=failure == "snapshot", changed_selection=failure == "selection")
    probe.functions["advance_phase"](phase, probe.finished.append)
    if failure != "missing_window":
        resume(probe)
    else:
        probe.callbacks.pop(0)()
    assert "measurement" not in probe.events and probe.finished == []
    assert len(reads) == (2 if failure == "missing_window" else 3)
    assert len(probe.callbacks) == 1
    probe.callbacks.pop(0)()
    assert probe.events[-1] == "quit" and probe.callbacks == []
    assert "Traceback" in capsys.readouterr().err


@pytest.mark.parametrize("changed_selection", [False, True])
def test_reader_uses_fresh_context_then_compares_complete_core(probe, tmp_path, changed_selection, capsys):
    core = {"context": {"selected": ["Cube"], "active": "Cube"}, "runtime_flags": {"tree": False}}
    (tmp_path / "expected.json").write_text(json.dumps({"loaded_fixture": True, "core": core, "ui": {},
        "references": [], "leaf": "Leaf", "cases": [{"identifier": "removed"}]}))
    observed = copy.deepcopy(core)
    if changed_selection:
        observed["context"]["selected"] = ["Other"]
    probe.functions.update(snapshot=lambda _refs: (observed, {}),
        runtime_inventory=lambda _refs: {"tree": {"is_runtime_data": False}})
    probe.functions["bpy"].data = SimpleNamespace(node_groups={"Leaf": SimpleNamespace(interface=SimpleNamespace(items_tree=[]))})
    phase = probe.functions["reader"](None, tmp_path, loaded_fixture=True)
    probe.functions["advance_phase"](phase, probe.finished.append)
    assert probe.events == ["load"] and probe.finished == []
    resume(probe)
    if changed_selection:
        assert probe.finished == []
        assert "Fresh process shader state differs" in capsys.readouterr().err
        return
    assert probe.finished[0]["post_load_snapshot_on_separate_timer_turn"] is True
    assert probe.finished[0]["fresh_process_removed_identifiers_and_all_surviving_shader_state_verified"] is True


@pytest.mark.parametrize("stage,repeat", [("UNKNOWN", False), ("OWNED_FILE_LOADED", True)])
def test_unexpected_or_repeated_handoff_fails_instead_of_waiting_for_context(probe, stage, repeat, capsys):
    def phase():
        yield stage
        if repeat:
            yield stage
        return {"unexpected_success": True}

    probe.functions["advance_phase"](phase(), probe.finished.append)
    if repeat:
        resume(probe)
    assert probe.finished == [] and len(probe.callbacks) == 1
    probe.callbacks.pop(0)()
    assert probe.events == ["quit"] and probe.callbacks == []
    assert "Unexpected or repeated post-load handoff" in capsys.readouterr().err


def test_phase_without_reload_finishes_without_an_extra_context_turn(probe):
    def phase():
        if False:
            yield
        return {"origin": "FRESH_CREATED_OWNED_FIXTURE"}

    probe.functions["advance_phase"](phase(), probe.finished.append)
    assert probe.finished == [{"origin": "FRESH_CREATED_OWNED_FIXTURE"}]
    assert len(probe.callbacks) == 1 and probe.events == []
