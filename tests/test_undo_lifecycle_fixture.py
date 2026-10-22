"""Run the native fixture's actual authority cases without launching Blender."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_checkpoint_snapshots import NativeStack, Scene


class NativeScene(Scene):
    def as_pointer(self):
        return id(self)


class NativeScenes(list):
    def new(self, name):
        scene = NativeScene()
        scene.name = name
        self.append(scene)
        return scene

    def remove(self, scene):
        for index, item in enumerate(self):
            if item is scene:
                del self[index]
                return
        raise ValueError("Fixture Scene is not in the native collection")


class SceneVector:
    """Keep the Cube's fake location inside the existing native undo stack."""

    def __init__(self, scene):
        self.scene = scene
        self.scene["cube_x"] = 0.0

    @property
    def x(self):
        return self.scene["cube_x"]

    @x.setter
    def x(self, value):
        self.scene["cube_x"] = value

    def __iter__(self):
        return iter((self.x, 0.0, 0.0))


@pytest.fixture
def native_authority_fixture(addon_package, monkeypatch):
    checkpoint = importlib.import_module(f"{addon_package}.checkpoints")
    stack = NativeStack()
    stack.scene = NativeScene(stack.scene)
    stack.scene.name = "Scene"
    stack.bpy.context.scene = stack.scene
    stack.bpy.data.scenes = NativeScenes([stack.scene])
    stack.bpy.data.objects = {"Cube": SimpleNamespace(location=SceneVector(stack.scene))}
    monkeypatch.setattr(checkpoint, "require_blender", lambda: stack.bpy)
    namespace = {"bpy": stack.bpy, "NS": SimpleNamespace, "MARKER_KEY": checkpoint.MARKER_KEY,
                 "CheckpointManager": checkpoint.CheckpointManager}
    services = {
        "command_queue": ("CommandQueue", "QueuedRequest"),
        "errors": ("BridgeError",),
        "executor": ("MainThreadExecutor",),
        "permissions": ("Permission", "PermissionManager"),
        "protocol": ("Request",),
        "request_lifecycle": ("ConnectionLifetime", "RequestLifetime"),
        "state": ("BridgeState",),
        "task_plans": ("get_task_plans",),
        "tool_registry": ("ToolContext", "ToolRegistry", "check_final_mutation"),
    }
    for module_name, names in services.items():
        module = importlib.import_module(f"{addon_package}.{module_name}")
        namespace.update({name: getattr(module, name) for name in names})
    namespace["batch"] = importlib.import_module(f"{addon_package}.tools.batch")
    path = Path(__file__).resolve().parents[1] / "scripts" / "blender_undo_lifecycle_smoke.py"
    source = ast.parse(path.read_text(), filename=str(path))
    functions = {"_checkpoint_preflight_case", "_checkpoint_internal_case", "_handler_entry_case"}
    cases = ast.Module(body=[node for node in source.body
                             if isinstance(node, ast.FunctionDef) and node.name in functions],
                       type_ignores=[])
    assert len(cases.body) == len(functions)
    exec(compile(cases, str(path), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("entry", ("executor", "batch"))
@pytest.mark.parametrize("stop", ("queued", "queued_deadline", "disconnect", "lifetime_deadline",
                                  "toolset", "pause", "emergency", "provider_queued"))
def test_native_fixture_preflight_preserves_original_authority_assertions(native_authority_fixture, entry, stop):
    native_authority_fixture["_checkpoint_preflight_case"](entry, stop)


@pytest.mark.parametrize("route", ("direct", "post_checkpoint", "batch_second"))
def test_native_fixture_handler_entry_preserves_original_recovery_assertions(native_authority_fixture, route):
    native_authority_fixture["_handler_entry_case"](route)


@pytest.mark.parametrize("route", ("before", "create"))
@pytest.mark.parametrize("where", ("marker_read", "after_delete", "preference_read"))
@pytest.mark.parametrize("kind", ("cancel", "expiry"))
def test_native_fixture_internal_readers_preserve_original_cas_assertions(native_authority_fixture, route, where, kind):
    native_authority_fixture["_checkpoint_internal_case"](route, where, kind)
