"""Scene-scoped settings must not silently edit another consumer's data."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest


def _camera(*, users: int = 1) -> Any:
    return SimpleNamespace(
        name="Camera Data", users=users, type="PERSP", lens=35.0, sensor_width=36.0,
        clip_start=0.1, clip_end=1000.0, ortho_scale=6.0,
        dof=SimpleNamespace(use_dof=False, focus_object=None, aperture_fstop=2.8),
    )


def _light(*, users: int = 1) -> Any:
    return SimpleNamespace(
        name="Light Data", users=users, type="POINT", energy=1000.0,
        color=(1.0, 1.0, 1.0), shadow_soft_size=0.25, spot_size=0.75, spot_blend=0.15,
    )


@pytest.mark.parametrize("kind,attribute,value", [("camera", "lens", 85.0), ("light", "energy", 25.0)])
def test_shared_camera_or_light_rejected_before_target_or_protected_changes(
    addon_package: str, monkeypatch: pytest.MonkeyPatch, kind: str, attribute: str, value: float,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    data = _camera(users=2) if kind == "camera" else _light(users=2)
    target = SimpleNamespace(name="Target", type=kind.upper(), data=data)
    protected = SimpleNamespace(name="Protected", data=data)
    scene = SimpleNamespace(name="Scene", objects={target.name: target}, camera=None)
    monkeypatch.setattr(module, "get_object", lambda *_args, **_kwargs: target)
    monkeypatch.setattr(module, "_scene", lambda _name: scene)
    params = {"object_name": target.name, attribute: value}
    if kind == "camera":
        params.update(set_active_for_scene=True, scene_name=scene.name)
    before = getattr(protected.data, attribute)

    with pytest.raises(module.BridgeError) as caught:
        getattr(module, f"configure_{kind}")(object(), params)

    assert caught.value.code == "NOT_IMPLEMENTED"
    assert getattr(target.data, attribute) == getattr(protected.data, attribute) == before
    assert scene.camera is None


@pytest.mark.parametrize("kind", ["camera", "light"])
@pytest.mark.parametrize("owner", ["object", "data"])
@pytest.mark.parametrize("field,value", [("library", object()), ("override_library", object()), ("is_editable", False)])
def test_nonlocal_camera_and_light_fail_before_configuration(
    addon_package: str, monkeypatch: pytest.MonkeyPatch, kind: str, owner: str, field: str, value: Any,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    data = _camera() if kind == "camera" else _light()
    target = SimpleNamespace(name="Target", type=kind.upper(), data=data)
    setattr(target if owner == "object" else data, field, value)
    monkeypatch.setattr(module, "get_object", lambda *_args, **_kwargs: target)
    attribute = "lens" if kind == "camera" else "energy"
    before = getattr(data, attribute)

    with pytest.raises(module.BridgeError) as caught:
        getattr(module, f"configure_{kind}")(object(), {"object_name": target.name, attribute: 10.0})

    assert caught.value.code == "NOT_IMPLEMENTED"
    assert getattr(data, attribute) == before


def test_shared_camera_can_be_assigned_without_editing_its_data(
    addon_package: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    data = _camera(users=2)
    target = SimpleNamespace(name="Target", type="CAMERA", data=data)
    scene = SimpleNamespace(name="Scene", objects={target.name: target}, camera=None)
    monkeypatch.setattr(module, "get_object", lambda *_args, **_kwargs: target)
    monkeypatch.setattr(module, "_scene", lambda _name: scene)

    module.configure_camera(object(), {"object_name": target.name, "set_active_for_scene": True, "scene_name": scene.name})

    assert scene.camera is target
    assert data.lens == 35.0


def _world_fixture(module: Any, monkeypatch: pytest.MonkeyPatch, *, users: int = 1) -> tuple[Any, Any]:
    world = SimpleNamespace(name="World", users=users, use_nodes=False, color=(0.1, 0.2, 0.3), node_tree=None)
    scene = SimpleNamespace(name="Scene", world=world)
    bpy = SimpleNamespace(data=SimpleNamespace(worlds=SimpleNamespace(get=lambda _name: world)))
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_scene", lambda _name: scene)
    return scene, world


@pytest.mark.parametrize("already_assigned", [False, True])
def test_world_edit_rejects_other_scene_users_before_assignment_or_pixel_changes(
    addon_package: str, monkeypatch: pytest.MonkeyPatch, already_assigned: bool,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    scene, world = _world_fixture(module, monkeypatch, users=2 if already_assigned else 1)
    protected = SimpleNamespace(name="Protected Scene", world=world)
    if not already_assigned:
        scene.world = None
    before = scene.world

    with pytest.raises(module.BridgeError) as caught:
        module.configure_world(object(), {"scene_name": scene.name, "world_name": world.name, "color": [0.8, 0.7, 0.6]})

    assert caught.value.code == "NOT_IMPLEMENTED"
    assert scene.world is before
    assert protected.world.color == (0.1, 0.2, 0.3)


@pytest.mark.parametrize("owner", ["scene", "world", "tree"])
@pytest.mark.parametrize("field,value", [("library", object()), ("override_library", object()), ("is_editable", False)])
def test_nonlocal_world_configuration_rejected_before_effects(
    addon_package: str, monkeypatch: pytest.MonkeyPatch, owner: str, field: str, value: Any,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    scene, world = _world_fixture(module, monkeypatch)
    world.node_tree = SimpleNamespace(name="World Nodes", nodes=[])
    setattr({"scene": scene, "world": world, "tree": world.node_tree}[owner], field, value)

    with pytest.raises(module.BridgeError) as caught:
        module.configure_world(object(), {"scene_name": scene.name, "color": [0.8, 0.7, 0.6]})

    assert caught.value.code == "NOT_IMPLEMENTED"
    assert scene.world is world
    assert world.color == (0.1, 0.2, 0.3)
    assert world.node_tree.nodes == []


def test_world_fake_user_does_not_count_as_protected_scene(
    addon_package: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    scene, world = _world_fixture(module, monkeypatch, users=2)
    world.use_fake_user = True

    result = module.configure_world(object(), {"scene_name": scene.name, "color": [0.8, 0.7, 0.6]})

    assert result["configured"] is True
    assert world.color == (0.8, 0.7, 0.6)


def test_shared_world_explicit_assignment_without_edits_is_allowed(
    addon_package: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    scene, world = _world_fixture(module, monkeypatch, users=2)
    scene.world = None

    module.configure_world(object(), {"scene_name": scene.name, "world_name": world.name})

    assert scene.world is world
    assert world.color == (0.1, 0.2, 0.3)
