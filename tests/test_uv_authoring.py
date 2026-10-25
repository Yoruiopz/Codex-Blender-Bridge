from __future__ import annotations

import asyncio
import importlib
import math
import struct
from types import SimpleNamespace
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.uv import UVCoordinateUpdate, UVCorner, UVTools, load_definitions


class Loop:
    def __init__(self, index):
        self.data = SimpleNamespace(uv=(float(index), 0.25), pin_uv=False)
        self.vert = self.edge = SimpleNamespace(index=index, hide=False)

    def __getitem__(self, layer):
        return self.data


@pytest.fixture
def edit(addon_package, monkeypatch):
    """Algorithm model with genuine admission bindings, not native-profile proof."""
    module = importlib.import_module(f"{addon_package}.tools.uv_edit")
    guard = importlib.import_module(f"{addon_package}.uv_edit_guard")
    intent = importlib.import_module(f"{addon_package}.uv_edit_intent")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    layer = SimpleNamespace(name="UV")
    faces = [
        SimpleNamespace(index=i, select=i == 0, hide=False, loops=[Loop(j) for j in range(4)])
        for i in range(2)
    ]
    bm = SimpleNamespace(
        faces=faces, loops=SimpleNamespace(layers=SimpleNamespace(uv={"UV": layer}))
    )
    obj = SimpleNamespace(name="Mesh", data=SimpleNamespace(users=1))
    monkeypatch.setattr(module, "_active_edit_mesh", lambda _: (None, obj, bm, {}))
    monkeypatch.setattr(module, "validate_selection_reference", lambda *args: {"faces": [0]})
    calls = []
    monkeypatch.setattr(
        module, "bmesh", SimpleNamespace(update_edit_mesh=lambda *a, **kw: calls.append(kw))
    )

    class Reader:
        proof_hooks = ()

        def __init__(self, _context, params):
            _obj, _bm, _layer, scoped = module._scope(
                params, require_reference=("updates" in params or params.get("corners") is not None)
            )
            self.scope_keys = tuple(
                (face.index, index, loop.vert.index, loop.edge.index)
                for face in scoped
                for index, loop in enumerate(face.loops)
            )
            self.object_name, self.uv_layer = obj.name, layer.name
            self.identities = {"object": (id(obj), 1), "mesh": (id(obj.data), 2)}
            self.scalar_count = sum(len(face.loops) for face in faces) * 3

        def snapshot(self):
            rows = [
                {
                    "face": face.index,
                    "corner": index,
                    "vertex": loop.vert.index,
                    "edge": loop.edge.index,
                    "uv": tuple(loop.data.uv),
                    "pin_uv": loop.data.pin_uv,
                }
                for face in faces
                for index, loop in enumerate(face.loops)
            ]
            preserved = (
                obj.data.users,
                tuple(
                    (
                        face.index,
                        face.select,
                        face.hide,
                        tuple((loop.vert.hide, loop.edge.hide) for loop in face.loops),
                    )
                    for face in faces
                ),
            )
            return guard.NativeState(preserved, intent.freeze_snapshot({"UV": rows}))

        def resolve(self, key, field, expected):
            assert field in {"uv", "pin_uv"}
            target = faces[key[0]].loops[key[1]].data
            matched = (tuple(struct.pack("<f", value).hex() for value in target.uv) == expected.uv_bits
                       if field == "uv" else target.pin_uv is expected.pin_uv)
            if expected.key != key or not matched:
                raise guard.BridgeError("NOT_IMPLEMENTED", "The model leaf differs from the original prefix")
            return target

        def update(self):
            module.bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)

    monkeypatch.setattr(guard, "_NativeReader", Reader)
    registry = registry_module.ToolRegistry(enabled_toolsets=("uv",))
    manager = permissions.PermissionManager(lambda: {"EDIT_MESH": True})
    context = registry_module.ToolContext(state, manager, registry, SimpleNamespace())
    module.register_tools(registry)  # Retain the actual original guarded handlers.

    def dispatch(name):
        return lambda ctx, params: registry.dispatch("uv." + name, params, ctx)

    for name in ("coordinates_set", "transform", "pin"):
        monkeypatch.setattr(module, name, dispatch(name))
    return module, obj, bm, calls, context


def arguments(**kwargs):
    return {"object_name": "Mesh", "uv_layer": "UV", **kwargs}


@pytest.mark.parametrize("updates", [None, [], "wrong", [{}],
    [{"face_index": True, "corner_index": 0, "uv": [0, 0]}],
    [{"face_index": 0, "corner_index": -1, "uv": [0, 0]}],
    [{"face_index": 0, "corner_index": 0, "uv": [float("nan"), 0]}],
    [{"face_index": 0, "corner_index": 0, "uv": [True, 0]}],
    [{"face_index": 0, "corner_index": 0, "uv": [1e7, 0]}],
    [{"face_index": 0, "corner_index": 0, "uv": [0]}],
    [{"face_index": 0, "corner_index": 0, "uv": [0, 0], "extra": 1}],
    [{"face_index": 0, "corner_index": 0, "uv": [0, 0]}] * 2,
])
def test_coordinate_updates_are_fully_typed_and_bounded(edit, updates):
    module, _, bm, calls, context = edit
    with pytest.raises(Exception) as error:
        module.coordinates_set(context, arguments(selection_id="ref", updates=updates))
    assert error.value.code == "INVALID_ARGUMENT"
    assert bm.faces[0].loops[0].data.uv == (0, .25) and not calls


@pytest.mark.parametrize("face,corner", [(1, 0), (0, 4)])
def test_late_invalid_coordinate_does_not_apply_earlier_update(edit, face, corner):
    module, _, bm, calls, context = edit
    with pytest.raises(Exception) as error:
        module.coordinates_set(context, arguments(selection_id="ref", updates=[
            {"face_index": 0, "corner_index": 0, "uv": [7, 8]},
            {"face_index": face, "corner_index": corner, "uv": [9, 10]},
        ]))
    assert error.value.code == "INVALID_SELECTION"
    assert bm.faces[0].loops[0].data.uv == (0, .25) and not calls


def test_coordinates_require_reference_and_preserve_pins_and_other_faces(edit):
    module, _, bm, calls, context = edit
    update = {"face_index": 0, "corner_index": 0, "uv": [.1, .2]}
    with pytest.raises(Exception) as error:
        module.coordinates_set(context, arguments(updates=[update]))
    assert error.value.code == "INVALID_ARGUMENT" and not calls
    bm.faces[0].loops[0].data.pin_uv = True
    result = module.coordinates_set(context, arguments(selection_id="ref", updates=[update]))
    assert bm.faces[0].loops[0].data.uv == pytest.approx((.1, .2))
    assert bm.faces[0].loops[0].data.pin_uv and bm.faces[1].loops[0].data.uv == (0, .25)
    assert result["coordinate_changes"] == 1 and not result["pin_changes"]
    assert calls == [{"loop_triangles": False, "destructive": False}]


def test_transform_order_pin_scope_and_selection_preservation(edit):
    module, _, bm, _, context = edit
    bm.faces[0].loops[0].data.pin_uv = True
    result = module.transform(context, arguments(offset=[2, 3], scale=[2, 1], pivot=[1, 1], rotation=math.pi / 2))
    assert result["skipped_pinned_corners"] == 1
    assert bm.faces[0].loops[0].data.uv == (0, .25)
    assert bm.faces[0].loops[1].data.uv == pytest.approx((3.75, 4))
    assert bm.faces[1].loops[1].data.uv == (1, .25)
    assert bm.faces[0].select and not bm.faces[1].select
    moved = module.transform(context, arguments(offset=[1, 0], respect_pins=False))
    assert moved["skipped_pinned_corners"] == 0 and bm.faces[0].loops[0].data.uv == (1, .25)


def test_transform_prevalidates_every_result_and_rejects_overflow(edit):
    module, _, bm, calls, context = edit
    with pytest.raises(Exception) as error:
        module.transform(context, arguments(scale=[1e6, 1]))
    assert error.value.code == "NOT_IMPLEMENTED" and not calls
    assert bm.faces[0].loops[0].data.uv == (0, 0.25)


def test_all_pinned_and_repeated_pin_are_noops(edit):
    module, _, bm, calls, context = edit
    pinned = module.pin(context, arguments())
    assert pinned["pin_changes"] == 4 and pinned["coordinate_changes"] == 0
    calls.clear()
    assert not module.pin(context, arguments())["changed"]
    result = module.transform(context, arguments(offset=[1, 1]))
    assert not result["changed"] and result["target_corners"] == 0
    assert result["bounds_after"] is None and result["skipped_pinned_corners"] == 4 and not calls
    assert all(loop.data.pin_uv for loop in bm.faces[0].loops)


def test_individual_pin_anchors_and_corner_transform(edit):
    module, _, bm, _, context = edit
    corners = [{"face_index": 0, "corner_index": 1}]
    result = module.pin(context, arguments(selection_id="ref", corners=corners))
    assert result["target_corners"] == result["pin_changes"] == 1
    assert [loop.data.pin_uv for loop in bm.faces[0].loops] == [False, True, False, False]
    module.transform(context, arguments(selection_id="ref", corners=corners, offset=[1, 2], respect_pins=False))
    assert bm.faces[0].loops[1].data.uv == (2, 2.25)
    assert bm.faces[0].loops[0].data.uv == (0, .25)


@pytest.mark.parametrize("tool", ["pin", "transform"])
@pytest.mark.parametrize("corners", [[], "bad", [{}], [{"face_index": 1, "corner_index": 0}],
    [{"face_index": 0, "corner_index": 9}], [{"face_index": 0, "corner_index": 0}] * 2])
def test_exact_corners_are_validated_before_writing(edit, tool, corners):
    module, _, bm, calls, context = edit
    with pytest.raises(Exception) as error:
        getattr(module, tool)(context, arguments(selection_id="ref", corners=corners))
    assert error.value.code in {"INVALID_ARGUMENT", "INVALID_SELECTION"} and not calls
    assert bm.faces[0].loops[0].data.uv == (0, .25) and not bm.faces[0].loops[0].data.pin_uv


def test_indexed_pin_needs_reference(edit):
    module, _, _, calls, context = edit
    with pytest.raises(Exception) as error:
        module.pin(context, arguments(corners=[{"face_index": 0, "corner_index": 0}]))
    assert error.value.code == "INVALID_ARGUMENT" and not calls


@pytest.mark.parametrize("restriction", ["hidden", "shared", "missing_layer", "empty", "budget"])
def test_retained_legacy_scope_for_uv_refine_rejects_unsupported_model_context(
    edit, monkeypatch, restriction
):
    module, obj, bm, calls, _context = edit
    extra = {}
    if restriction == "hidden":
        bm.faces[0].hide = True
    elif restriction == "shared":
        obj.data.users = 2
    elif restriction == "missing_layer":
        extra["uv_layer"] = "Missing"
    elif restriction == "empty":
        bm.faces[0].select = False
    elif restriction == "budget":
        monkeypatch.setattr(module, "MAX_CORNERS", 2)
    with pytest.raises(Exception) as error:
        module._scope(arguments(**extra))
    assert error.value.code in {"INVALID_ARGUMENT", "INVALID_SELECTION", "NOT_IMPLEMENTED"}
    assert not calls


@pytest.mark.parametrize("tool", ["transform", "pin"])
def test_guarded_boolean_parameters_remain_strict(edit, tool):
    module, _, _, calls, context = edit
    with pytest.raises(Exception) as error:
        getattr(module, tool)(
            context, arguments(**{"pinned" if tool == "pin" else "respect_pins": 1})
        )
    assert error.value.code == "INVALID_ARGUMENT" and not calls


def test_uv_update_failure_retains_requested_payload_without_unknown_native_compensation(
    edit, monkeypatch
):
    module, _, bm, _, context = edit
    updates = []

    def fail(*args, **kwargs):
        updates.append(True)
        raise RuntimeError("injected update failure")

    monkeypatch.setattr(module.bmesh, "update_edit_mesh", fail)
    with pytest.raises(Exception) as error:
        module.transform(context, arguments(offset=[1, 1]))
    assert error.value.code == "OPERATION_FAILED"
    assert error.value.context["rollback_verified"] is False
    assert error.value.context["possible_mutation"] is True
    assert error.value.context["verification_required"]
    assert updates == [True] and bm.faces[0].loops[0].data.uv == (1, 1.25)


def test_cancellation_after_write_retains_partial_and_preserves_error_code(edit, addon_package):
    module, _, bm, _, context = edit
    errors = importlib.import_module(f"{addon_package}.errors")
    checks = []

    def cancel():
        checks.append(True)
        if bm.faces[0].loops[0].data.uv == (1, 1.25):
            raise errors.BridgeError(errors.ErrorCode.TIMEOUT, "expired")

    context.check_cancelled = cancel
    with pytest.raises(Exception) as error:
        module.transform(context, arguments(offset=[1, 1]))
    assert error.value.code == "TIMEOUT" and not error.value.context["rollback_verified"]
    assert error.value.context["possible_mutation"] is True
    assert checks and bm.faces[0].loops[0].data.uv == (1, 1.25)
    assert bm.faces[0].loops[1].data.uv == (1, 0.25)


def test_uv_authoring_registry_and_thin_wrappers(addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    for domain in ("uv_edit", "uv_layers"):
        importlib.import_module(f"{addon_package}.tools.{domain}").register_tools(registry)
    definitions = {item.name: item for item in load_definitions()}
    methods = {
        "coordinates_set": {"selection_id": "ref", "updates": [{"face_index": 0, "corner_index": 0, "uv": [0., 0.]}]},
        "transform": {}, "pin": {}, "layer_create": {"new_name": "New"},
        "layer_rename": {"new_name": "New"}, "layer_activate": {}, "layer_remove": {"confirm_remove": True},
    }
    calls = []

    class Registry:
        async def call(self, method, params):
            calls.append((method, params))
            return {}

    tools = UVTools(Registry())
    for method, extra in methods.items():
        name = f"uv.{method}"
        spec = registry.get(name)
        assert spec.modifies and spec.automatic_checkpoint and spec.toolset == "uv"
        assert {p.value for p in spec.permissions} == {"EDIT_MESH"}
        assert definitions[name].required_permissions == ("EDIT_MESH",)
        params = {"object_name": "Mesh", **({} if method == "layer_create" else {"uv_layer": "UV"}), **extra}
        asyncio.run(getattr(tools, f"uv_{method}")(**params))
        assert calls[-1][0] == name
        assert all(calls[-1][1][key] == value for key, value in params.items())
        assert name in {binding.name for binding in tools.bindings()}


@pytest.mark.parametrize("record", [
    {"face_index": True, "corner_index": 0, "uv": [0, 0]},
    {"face_index": "0", "corner_index": 0, "uv": [0, 0]},
    {"face_index": 0, "corner_index": 0, "uv": [True, 0]},
    {"face_index": 0, "corner_index": 0, "uv": [0, 0], "unexpected": 1},
])
def test_mcp_corner_records_reject_coercion_and_extra_fields(record):
    with pytest.raises(ValidationError):
        TypeAdapter(UVCoordinateUpdate).validate_python(record)


def test_mcp_record_schema_is_strict_but_accepts_integer_uv_numbers():
    assert TypeAdapter(UVCoordinateUpdate).validate_python({"face_index": 0, "corner_index": 0, "uv": [0, 1]})["uv"] == [0., 1.]
    for record in (UVCorner, UVCoordinateUpdate):
        assert TypeAdapter(record).json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("method,parameter,value", [
    ("uv_transform", "rotation", True), ("uv_transform", "offset", [False, 1]),
    ("uv_transform", "respect_pins", "false"), ("uv_pin", "pinned", 1),
    ("uv_layer_activate", "for_render", "true"), ("uv_layer_remove", "confirm_remove", "true"),
])
def test_new_mcp_authoring_parameters_reject_coercion(method, parameter, value):
    annotation = get_type_hints(getattr(UVTools, method), include_extras=True)[parameter]
    with pytest.raises(ValidationError):
        TypeAdapter(annotation).validate_python(value)
