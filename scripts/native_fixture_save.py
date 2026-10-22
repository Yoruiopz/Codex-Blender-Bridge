"""Owned native fixture serialization; never a public bridge save backend.

Native Save has unbounded catalog/runtime side effects. Factory-startup test
processes use this helper only to prepare their disposable fresh-process input.
A successful fixture save is not safe project delivery or a tool capability.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import bpy


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def serialize_owned_fixture(runtime: Any, filepath: Path) -> dict[str, bool]:
    """First prove public refusal; then prepare this runner-owned test artifact."""
    from blender_codex_bridge.errors import BridgeError

    assert threading.current_thread() is threading.main_thread(), "Fixture saving belongs on Blender's main thread"
    assert os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"), "Use the official native runner"
    index = sys.argv.index("--bridge-bundle")
    bundle = Path(sys.argv[index + 1]).resolve(strict=True)
    target = filepath.resolve()
    assert target.is_relative_to(bundle) and target.suffix == ".blend" and not target.exists()
    try:
        runtime.dispatch("project.save", {"filepath": str(target)})
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED", error.to_dict()
        assert error.context["native_save_invoked"] is False and error.context["execution_started"] is False
        assert error.context["bridge_file_writes"] is False
    else:
        raise AssertionError("Unsafe public project saving unexpectedly succeeded")
    assert not target.exists()
    # This raw operation is intentional fixture setup, outside the bridge tool
    # contract. It is not a supported fallback and does not prove side effects
    # confined to this path. Isolation keeps it out of a user's open project.
    result = bpy.ops.wm.save_as_mainfile(filepath=str(target), check_existing=False, copy=False)
    assert result == {"FINISHED"} and target.is_file()
    frozen = _digest(target)
    # The same public refusal applies with a saved current file, including an
    # explicit path equal to that file. This is still a tool denial test.
    for params in ({}, {"filepath": str(target)}):
        try:
            runtime.dispatch("project.save", params)
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED", error.to_dict()
            assert error.context["native_save_invoked"] is False
        else:
            raise AssertionError("Current-file public save unexpectedly succeeded")
    assert _digest(target) == frozen
    evidence = {"fixture_native_save": True, "bridge_safe_project_save_verified": False,
                "public_project_save_refusal_verified": True, "public_current_file_save_refusal_verified": True}
    print("BRIDGE_FIXTURE_NATIVE_SAVE " + json.dumps(evidence), flush=True)
    return evidence
