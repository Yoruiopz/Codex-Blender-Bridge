from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools.scene_edit import SceneEditTools


class RecordingRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, values))
        return values


def _install_field_boundary(module, monkeypatch):
    """Keep fake-setter ordering tests over the real CAS/authorization engine.

    These legacy Python objects cannot prove native ownership. Native Scene
    profiles are covered by the isolated Blender boundary fixture instead.
    """
    from dataclasses import fields
    proof = module.proof
    package = module.__package__.rsplit(".", 1)[0]
    registry = importlib.import_module(f"{package}.tool_registry")
    permissions = importlib.import_module(f"{package}.permissions")
    state = importlib.import_module(f"{package}.state")
    context = registry.ToolContext(state.BridgeState(), permissions.PermissionManager(
        lambda: {p.value: True for p in permissions.Permission}), None, None)

    def identity(owner):
        if owner is not None and hasattr(owner, "__dict__") and not hasattr(owner, "as_pointer"):
            owner.as_pointer = lambda: id(owner)
            owner.session_uid = id(owner)
        return owner

    class Proxy:
        def __init__(self, target, name):
            object.__setattr__(self, "target", target)
            object.__setattr__(self, "bl_rna", SimpleNamespace(properties={name: SimpleNamespace(type="POINTER", array_length=0)}))

        def __setattr__(self, name, value):
            setattr(self.target, name, value)

    class Field:
        def __init__(self, getter, name):
            self.getter, self.name = getter, name

        def owner(self):
            return Proxy(self.getter(), self.name)

        def raw(self, _bpy):
            owner = self.getter()
            raw = None if owner is None else getattr(owner, self.name)
            identity(raw)
            return tuple(raw) if isinstance(raw, list) else raw

        def read(self, bpy):
            return proof.value(self.raw(bpy))

    def settings(_context, method, prepared):
        for field in fields(prepared):
            identity(getattr(prepared, field.name))
        if method == "scene.configure":
            scene = prepared.scene
            watched = {name: Field(lambda: scene, name) for name in ("camera", "use_gravity", "gravity")}
            watched.update({"units." + name: Field(lambda: scene.unit_settings, name) for name in ("system", "scale_length")})
        elif method == "camera.configure":
            camera = prepared.camera
            watched = {name: Field(lambda: camera, name) for name in module.profile.CAMERA_FIELDS}
            watched.update({"dof." + name: Field(lambda: camera.dof, name) for name in module.profile.DOF_FIELDS})
            if prepared.active_scene is not None:
                watched["active_camera"] = Field(lambda: prepared.active_scene, "camera")
        else:
            light = prepared.light
            watched = {name: Field(lambda: light, name) for name in module.profile.LIGHT_FIELDS if hasattr(light, name)}
        return proof.Boundary(None, context, method, watched, lambda: ())

    def world(_context, prepared, holder):
        scene = prepared.scene
        identity(holder[0])
        def socket(name):
            node = module.profile.background(holder[0])
            return None if node is None else node.inputs.get(name)
        watched = {"scene_world": Field(lambda: scene, "world"), "world_nodes": Field(lambda: holder[0], "use_nodes"),
                   "world_color": Field(lambda: holder[0], "color"), "background_color": Field(lambda: socket("Color"), "default_value"),
                   "background_strength": Field(lambda: socket("Strength"), "default_value")}
        return proof.Boundary(None, context, "world.configure", watched, lambda: ())

    monkeypatch.setattr(module, "_settings_boundary", settings)
    monkeypatch.setattr(module, "_world_boundary", world)
    monkeypatch.setattr(module.profile, "background", lambda owner: next((node for node in owner.node_tree.nodes if node.type == "BACKGROUND"), None)
                        if owner is not None and owner.node_tree is not None else None)


def test_scene_edit_registration_is_permissioned(addon_package: str) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry()

    module.register_tools(registry)

    assert registry.get("camera.configure").permissions == {
        permissions.Permission.EDIT_SCENE
    }
    assert registry.get("collection.delete").permissions == {
        permissions.Permission.EDIT_SCENE,
        permissions.Permission.DELETE_OBJECTS,
    }
    assert all(registry.get(name).modifies for name in registry.list_tools())


def test_scene_color_rejects_non_finite_values(addon_package: str) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    errors = importlib.import_module(f"{addon_package}.errors")

    with pytest.raises(errors.BridgeError):
        module._color([1.0, float("inf"), 0.0], "color")


def test_scene_edit_wrapper_forwards_only_json_parameters() -> None:
    registry = RecordingRegistry()
    tools = SceneEditTools(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        tools.camera_configure(
            "Camera",
            lens=50.0,
            dof_enabled=True,
            clear_focus_object=True,
        )
    )

    assert result == {
        "object_name": "Camera",
        "lens": 50.0,
        "dof_enabled": True,
        "clear_focus_object": True,
    }
    assert registry.calls == [("camera.configure", result)]


def test_scene_configure_rejects_late_gravity_without_partial_mutation(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    old_camera = SimpleNamespace(name="Old Camera", type="CAMERA")
    new_camera = SimpleNamespace(name="New Camera", type="CAMERA")
    scene = SimpleNamespace(
        name="Scene",
        camera=old_camera,
        objects={new_camera.name: new_camera},
        unit_settings=SimpleNamespace(system="NONE", scale_length=1.0),
        use_gravity=True,
        gravity=(0.0, 0.0, -9.81),
    )
    before = (
        scene.camera,
        scene.unit_settings.system,
        scene.unit_settings.scale_length,
        scene.use_gravity,
        tuple(scene.gravity),
    )
    monkeypatch.setattr(module, "_scene", lambda _: scene)
    monkeypatch.setattr(module, "get_object", lambda *_args, **_kwargs: new_camera)

    with pytest.raises(Exception) as caught:
        module.configure_scene(
            object(),
            {
                "scene_name": "Scene",
                "camera_object": "New Camera",
                "unit_system": "METRIC",
                "unit_scale_length": 0.01,
                "use_gravity": False,
                "gravity": [0.0, float("inf"), -9.81],
            },
        )

    assert caught.value.code == "INVALID_ARGUMENT"
    assert (
        scene.camera,
        scene.unit_settings.system,
        scene.unit_settings.scale_length,
        scene.use_gravity,
        tuple(scene.gravity),
    ) == before


def test_camera_configure_rejects_late_scene_target_without_partial_mutation(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    old_focus = SimpleNamespace(name="Old Focus")
    new_focus = SimpleNamespace(name="New Focus")
    camera = SimpleNamespace(
        name="Camera Data",
        type="PERSP",
        lens=35.0,
        sensor_width=36.0,
        clip_start=0.1,
        clip_end=1000.0,
        ortho_scale=6.0,
        dof=SimpleNamespace(
            use_dof=False,
            focus_object=old_focus,
            focus_distance=10.0,
            aperture_fstop=2.8,
        ),
    )
    obj = SimpleNamespace(name="Camera", type="CAMERA", data=camera)
    other_scene = SimpleNamespace(name="Other Scene", objects={}, camera=None)
    before = (
        camera.type,
        camera.lens,
        camera.sensor_width,
        camera.clip_start,
        camera.clip_end,
        camera.ortho_scale,
        camera.dof.use_dof,
        camera.dof.focus_object,
        camera.dof.aperture_fstop,
        other_scene.camera,
    )

    def fake_object(name: str, **_kwargs: Any) -> Any:
        return obj if name == "Camera" else new_focus

    monkeypatch.setattr(module, "get_object", fake_object)
    monkeypatch.setattr(module, "_scene", lambda _: other_scene)

    with pytest.raises(Exception) as caught:
        module.configure_camera(
            object(),
            {
                "object_name": "Camera",
                "camera_type": "ORTHO",
                "lens": 85.0,
                "sensor_width": 50.0,
                "clip_start": 1.0,
                "clip_end": 2000.0,
                "ortho_scale": 12.0,
                "dof_enabled": True,
                "focus_object": "New Focus",
                "aperture_fstop": 1.4,
                "set_active_for_scene": True,
                "scene_name": "Other Scene",
            },
        )

    assert caught.value.code == "INVALID_ARGUMENT"
    assert (
        camera.type,
        camera.lens,
        camera.sensor_width,
        camera.clip_start,
        camera.clip_end,
        camera.ortho_scale,
        camera.dof.use_dof,
        camera.dof.focus_object,
        camera.dof.aperture_fstop,
        other_scene.camera,
    ) == before


def test_light_configure_rejects_late_shape_value_without_partial_mutation(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    light = SimpleNamespace(
        name="Key Data",
        type="POINT",
        energy=1000.0,
        color=(1.0, 1.0, 1.0),
        shadow_soft_size=0.25,
        spot_size=0.75,
        spot_blend=0.15,
    )
    obj = SimpleNamespace(name="Key", type="LIGHT", data=light)
    before = (
        light.type,
        light.energy,
        tuple(light.color),
        light.shadow_soft_size,
        light.spot_size,
        light.spot_blend,
    )
    monkeypatch.setattr(module, "get_object", lambda *_args, **_kwargs: obj)

    with pytest.raises(Exception) as caught:
        module.configure_light(
            object(),
            {
                "object_name": "Key",
                "light_type": "SPOT",
                "energy": 2500.0,
                "color": [0.2, 0.3, 0.4],
                "shadow_soft_size": 1.0,
                "spot_size": 1.25,
                "spot_blend": 2.0,
            },
        )

    assert caught.value.code == "INVALID_ARGUMENT"
    assert (
        light.type,
        light.energy,
        tuple(light.color),
        light.shadow_soft_size,
        light.spot_size,
        light.spot_blend,
    ) == before


def test_world_configure_validates_strength_before_creating_or_assigning_world(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    previous_world = SimpleNamespace(name="Previous World")
    scene = SimpleNamespace(name="Scene", world=previous_world)

    class Worlds:
        new_calls = 0

        @staticmethod
        def get(_name: str) -> None:
            return None

        def new(self, name: str) -> Any:
            self.new_calls += 1
            return SimpleNamespace(name=name)

    worlds = Worlds()
    bpy = SimpleNamespace(data=SimpleNamespace(worlds=worlds))
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_scene", lambda _: scene)

    with pytest.raises(Exception) as caught:
        module.configure_world(
            object(),
            {
                "scene_name": "Scene",
                "world_name": "New World",
                "create": True,
                "use_nodes": True,
                "color": [0.1, 0.2, 0.3],
                "strength": -1.0,
            },
        )

    assert caught.value.code == "INVALID_ARGUMENT"
    assert worlds.new_calls == 0
    assert scene.world is previous_world


def test_collection_create_rejects_parent_outside_requested_scene_before_creation(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    requested_root = SimpleNamespace(name="Requested Root", children_recursive=[])
    requested_scene = SimpleNamespace(name="Requested Scene", collection=requested_root)
    other_parent = SimpleNamespace(name="Other Parent")

    class Collections:
        new_calls = 0

        @staticmethod
        def get(_name: str) -> None:
            return None

        def new(self, name: str) -> Any:
            self.new_calls += 1
            return SimpleNamespace(name=name)

    collections = Collections()
    bpy = SimpleNamespace(data=SimpleNamespace(collections=collections))
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_scene", lambda _: requested_scene)
    monkeypatch.setattr(module, "_collection", lambda _: other_parent)

    with pytest.raises(Exception) as caught:
        module.create_collection(
            object(),
            {
                "scene_name": "Requested Scene",
                "name": "Should Not Exist",
                "parent_collection": "Other Parent",
            },
        )

    assert caught.value.code == "INVALID_ARGUMENT"
    assert collections.new_calls == 0


def test_scene_configure_rolls_back_when_late_rna_setter_fails(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    _install_field_boundary(module, monkeypatch)
    old_camera = SimpleNamespace(name="Old Camera", type="CAMERA")
    new_camera = SimpleNamespace(name="New Camera", type="CAMERA")

    class FailingScene:
        def __init__(self) -> None:
            self.name = "Scene"
            self.camera = old_camera
            self.objects = {new_camera.name: new_camera}
            self.unit_settings = SimpleNamespace(system="NONE", scale_length=1.0)
            self.use_gravity = True
            self._gravity = (0.0, 0.0, -9.81)

        @property
        def gravity(self) -> tuple[float, float, float]:
            return self._gravity

        @gravity.setter
        def gravity(self, value: Any) -> None:
            converted = tuple(value)
            if converted == (1.0, 2.0, 3.0):
                raise RuntimeError("linked gravity is read-only")
            self._gravity = converted

    scene = FailingScene()
    before = (
        scene.camera,
        scene.unit_settings.system,
        scene.unit_settings.scale_length,
        scene.use_gravity,
        scene.gravity,
    )
    monkeypatch.setattr(module, "_scene", lambda _: scene)
    monkeypatch.setattr(module, "get_object", lambda *_args, **_kwargs: new_camera)

    with pytest.raises(module.BridgeError) as caught:
        module.configure_scene(
            object(),
            {
                "scene_name": "Scene",
                "camera_object": "New Camera",
                "unit_system": "METRIC",
                "unit_scale_length": 0.01,
                "use_gravity": False,
                "gravity": [1.0, 2.0, 3.0],
            },
        )

    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["rollback_verified"] is True

    assert (
        scene.camera,
        scene.unit_settings.system,
        scene.unit_settings.scale_length,
        scene.use_gravity,
        scene.gravity,
    ) == before


def test_camera_configure_rolls_back_when_dof_setter_fails(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    _install_field_boundary(module, monkeypatch)
    old_focus = SimpleNamespace(name="Old Focus")
    new_focus = SimpleNamespace(name="New Focus")

    class FailingDof:
        def __init__(self) -> None:
            self.use_dof = False
            self.focus_object = old_focus
            self.focus_distance = 10.0
            self._aperture_fstop = 2.8

        @property
        def aperture_fstop(self) -> float:
            return self._aperture_fstop

        @aperture_fstop.setter
        def aperture_fstop(self, value: float) -> None:
            if value == 1.4:
                raise RuntimeError("aperture setter failed")
            self._aperture_fstop = value

    camera = SimpleNamespace(
        name="Camera Data",
        type="PERSP",
        lens=35.0,
        sensor_width=36.0,
        clip_start=0.1,
        clip_end=1000.0,
        ortho_scale=6.0,
        dof=FailingDof(),
    )
    obj = SimpleNamespace(name="Camera", type="CAMERA", data=camera)
    before = (
        camera.type,
        camera.lens,
        camera.sensor_width,
        camera.dof.use_dof,
        camera.dof.focus_object,
        camera.dof.aperture_fstop,
    )

    def fake_object(name: str, **_kwargs: Any) -> Any:
        return obj if name == "Camera" else new_focus

    monkeypatch.setattr(module, "get_object", fake_object)

    with pytest.raises(module.BridgeError) as caught:
        module.configure_camera(
            object(),
            {
                "object_name": "Camera",
                "camera_type": "ORTHO",
                "lens": 85.0,
                "sensor_width": 50.0,
                "dof_enabled": True,
                "focus_object": "New Focus",
                "aperture_fstop": 1.4,
            },
        )

    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["rollback_verified"] is True

    assert (
        camera.type,
        camera.lens,
        camera.sensor_width,
        camera.dof.use_dof,
        camera.dof.focus_object,
        camera.dof.aperture_fstop,
    ) == before


def test_light_configure_rolls_back_when_shape_setter_fails(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    _install_field_boundary(module, monkeypatch)

    class FailingLight:
        def __init__(self) -> None:
            self.name = "Key Data"
            self.type = "SPOT"
            self.energy = 1000.0
            self.color = (1.0, 1.0, 1.0)
            self.shadow_soft_size = 0.25
            self.spot_size = 0.75
            self._spot_blend = 0.15

        @property
        def spot_blend(self) -> float:
            return self._spot_blend

        @spot_blend.setter
        def spot_blend(self, value: float) -> None:
            if value == 0.75:
                raise RuntimeError("spot blend setter failed")
            self._spot_blend = value

    light = FailingLight()
    obj = SimpleNamespace(name="Key", type="LIGHT", data=light)
    before = (
        light.type,
        light.energy,
        tuple(light.color),
        light.shadow_soft_size,
        light.spot_size,
        light.spot_blend,
    )
    monkeypatch.setattr(module, "get_object", lambda *_args, **_kwargs: obj)

    with pytest.raises(module.BridgeError) as caught:
        module.configure_light(
            object(),
            {
                "object_name": "Key",
                "energy": 2500.0,
                "color": [0.2, 0.3, 0.4],
                "shadow_soft_size": 1.0,
                "spot_size": 1.25,
                "spot_blend": 0.75,
            },
        )

    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["rollback_verified"] is True

    assert (
        light.type,
        light.energy,
        tuple(light.color),
        light.shadow_soft_size,
        light.spot_size,
        light.spot_blend,
    ) == before


class _FakeSocket:
    def __init__(self, value: Any, *, reject: Any = None) -> None:
        self._value = value
        self.reject = reject

    @property
    def default_value(self) -> Any:
        return self._value

    @default_value.setter
    def default_value(self, value: Any) -> None:
        comparable = tuple(value) if isinstance(value, (list, tuple)) else value
        if comparable == self.reject:
            raise RuntimeError("background socket setter failed")
        self._value = comparable


class _FakeNode:
    def __init__(self, node_type: str, *, reject_strength: float | None = None) -> None:
        self.type = node_type
        self.inputs = (
            {
                "Color": _FakeSocket((0.05, 0.06, 0.07, 1.0)),
                "Strength": _FakeSocket(0.5, reject=reject_strength),
            }
            if node_type == "BACKGROUND"
            else {}
        )


class _FakeNodes:
    def __init__(self, nodes: list[_FakeNode], *, reject_new_strength: float | None = None) -> None:
        self.items = nodes
        self.reject_new_strength = reject_new_strength

    def __iter__(self) -> Any:
        return iter(self.items)

    def new(self, _node_type: str) -> _FakeNode:
        node = _FakeNode("BACKGROUND", reject_strength=self.reject_new_strength)
        self.items.append(node)
        return node

    def remove(self, node: _FakeNode) -> None:
        self.items.remove(node)


def _fake_world(name: str, nodes: _FakeNodes, *, use_nodes: bool = True) -> Any:
    return SimpleNamespace(
        name=name,
        users=1, use_fake_user=False,
        use_nodes=use_nodes,
        color=(0.01, 0.02, 0.03),
        node_tree=SimpleNamespace(nodes=nodes),
    )


def test_world_configure_restores_existing_properties_and_background_sockets(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    _install_field_boundary(module, monkeypatch)
    background = _FakeNode("BACKGROUND", reject_strength=2.0)
    nodes = _FakeNodes([background])
    world = _fake_world("World", nodes)
    scene = SimpleNamespace(name="Scene", world=world)
    bpy = SimpleNamespace(data=SimpleNamespace(worlds=SimpleNamespace()))
    before = (
        scene.world,
        world.use_nodes,
        tuple(world.color),
        tuple(background.inputs["Color"].default_value),
        background.inputs["Strength"].default_value,
        tuple(nodes.items),
    )
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_scene", lambda _: scene)

    with pytest.raises(module.BridgeError) as caught:
        module.configure_world(
            object(),
            {
                "scene_name": "Scene",
                "use_nodes": True,
                "color": [0.2, 0.3, 0.4],
                "strength": 2.0,
            },
        )

    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["rollback_verified"] is True

    assert (
        scene.world,
        world.use_nodes,
        tuple(world.color),
        tuple(background.inputs["Color"].default_value),
        background.inputs["Strength"].default_value,
        tuple(nodes.items),
    ) == before


def test_world_configure_refuses_unreviewed_node_profile_before_allocation(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    output = _FakeNode("OUTPUT_WORLD")
    nodes = _FakeNodes([output], reject_new_strength=2.0)
    world = _fake_world("World", nodes, use_nodes=False)
    scene = SimpleNamespace(name="Scene", world=world)
    bpy = SimpleNamespace(data=SimpleNamespace(worlds=SimpleNamespace()))
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_scene", lambda _: scene)

    with pytest.raises(module.BridgeError) as caught:
        module.configure_world(
            object(),
            {
                "scene_name": "Scene",
                "use_nodes": True,
                "color": [0.2, 0.3, 0.4],
                "strength": 2.0,
            },
        )

    assert caught.value.code == "NOT_IMPLEMENTED"

    assert scene.world is world
    assert world.use_nodes is False
    assert tuple(world.color) == (0.01, 0.02, 0.03)
    assert nodes.items == [output]


def test_world_configure_requires_native_allocation_profile_before_creation(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.scene_edit")
    previous_world = SimpleNamespace(name="Previous World")
    scene = SimpleNamespace(name="Scene", world=previous_world)

    class Worlds:
        def __init__(self) -> None:
            self.created: Any = None
            self.removed: Any = None

        @staticmethod
        def get(_name: str) -> None:
            return None

        def new(self, name: str) -> Any:
            nodes = _FakeNodes([_FakeNode("BACKGROUND", reject_strength=2.0)])
            self.created = _fake_world(name, nodes, use_nodes=False)
            return self.created

        def remove(self, world: Any, *, do_unlink: bool) -> None:
            assert do_unlink is True
            self.removed = world

    worlds = Worlds()
    bpy = SimpleNamespace(data=SimpleNamespace(worlds=worlds))
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_scene", lambda _: scene)

    with pytest.raises(module.BridgeError) as caught:
        module.configure_world(
            object(),
            {
                "scene_name": "Scene",
                "world_name": "New World",
                "create": True,
                "use_nodes": True,
                "color": [0.2, 0.3, 0.4],
                "strength": 2.0,
            },
        )

    assert caught.value.code == "NOT_IMPLEMENTED"

    assert scene.world is previous_world
    assert worlds.created is None
    assert worlds.removed is None
