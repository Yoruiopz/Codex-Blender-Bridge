from __future__ import annotations

import asyncio
import copy
import importlib
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.scene_variants import SceneVariantTools, load_definitions


@pytest.fixture
def schema(addon_package):
    return importlib.import_module(addon_package+".cinematic_variants")


def control(module, kind="CAMERA", name="Camera"):
    if kind == "CAMERA":
        settings = dict(zip(module.CAMERA_FIELDS, ("PERSP", 50., "MILLIMETERS", "AUTO", 36., 24., 0., 0., .1, 100., 6.), strict=True))
        settings.update(dict(zip(("dof."+field for field in module.DOF_FIELDS), (False, 10., 2.8, 0, 0., 1.), strict=True)))
        settings["dof.focus_object"] = None
    else:
        settings = {field: 1. for field in (*module.LIGHT_COMMON, *module.LIGHT_SHAPE["POINT"])}
        settings.update(type="POINT", color=[1., 1., 1.], use_shadow=True, normalize=True, use_custom_distance=False, use_nodes=False)
    return {"object_name": name, "data_name": name+" Data", "object_type": kind,
        "data_type": "PERSP" if kind == "CAMERA" else "POINT", "location": [0., 0., 0.],
        "rotation_mode": "XYZ", "rotation": [0., 0., 0.], "scale": [1., 1., 1.], "settings": settings}


def library(module):
    return {"schema_version": 1, "revision": 1, "variants": [{"variant_id": "v_"+"1"*32,
        "label": "Warm close-up", "camera": control(module), "lights": [control(module, "LIGHT", "Key")],
        "protected_objects": ["Prop", "Shared Consumer"], "profile_sha256": "2"*64}]}


def test_inert_library_roundtrip_has_no_runtime_authority(schema):
    value = library(schema)
    raw = schema.encode_library(value)
    assert schema.read_library(raw) == value
    assert schema.fingerprint(None) != schema.fingerprint(schema.encode_library(schema.read_library(None)))
    assert schema.read_library(None) == {"schema_version": 1, "revision": 0, "variants": []}


@pytest.mark.parametrize("raw", ['{"schema_version":1,"revision":0,"revision":1,"variants":[]}',
    '{"schema_version":1,"revision":NaN,"variants":[]}', '{"schema_version":1,"revision":true,"variants":[]}',
    '{"schema_version":1,"revision":0,"variants":[],"permissions":["EDIT_SCENE"]}', '[[]]', 'null', '"text"', '{'])
def test_reject_malformed_or_authority_fields(schema, raw):
    with pytest.raises(Exception, match=r"cinematic|Cinematic|JSON"):
        schema.read_library(raw)


@pytest.mark.parametrize("mutation", [
    lambda v: v["variants"][0].update(filepath="/tmp/inject"),
    lambda v: v["variants"][0]["camera"]["settings"].update(unknown_rna=1.),
    lambda v: v["variants"][0]["camera"]["location"].__setitem__(0, float("nan")),
    lambda v: v["variants"][0]["camera"]["location"].__setitem__(0, True),
    lambda v: v["variants"][0]["camera"]["location"].__setitem__(0, 10**1000),
    lambda v: v["variants"][0]["camera"]["settings"].update({"dof.focus_object": "Guessed Focus"}),
    lambda v: v["variants"][0]["lights"][0]["settings"].update(use_nodes="true"),
    lambda v: v["variants"][0].update(protected_objects=["Prop", "Prop"]),
    lambda v: v["variants"][0].update(protected_objects=["Camera"]),
    lambda v: v.update(variants=v["variants"]*9),
    lambda v: v.update(revision=True),
])
def test_reject_unbounded_ambiguous_or_unsupported_controls(schema, mutation):
    value = library(schema)
    mutation(value)
    with pytest.raises(Exception, match=r"cinematic|Cinematic|JSON|Location|protected|A variant|Unsupported"):
        schema.encode_library(value)


def test_library_cas_rejects_same_revision_external_json_edit(addon_package, schema):
    module = importlib.import_module(addon_package+".tools.scene_variants")
    raw = schema.encode_library(library(schema))
    scene = {schema.PROPERTY: raw}
    params = {"expected_library_revision": 1, "expected_library_fingerprint": schema.fingerprint(raw)}
    module._library(scene, params)
    scene[schema.PROPERTY] = " "+raw
    with pytest.raises(Exception, match="current inspected"):
        module._library(scene, params)


def test_preview_metadata_requires_all_native_permissions():
    definitions = {item.name: item for item in load_definitions()}
    preview = definitions["scene.variant.preview"]
    assert preview.modifying
    assert set(preview.required_permissions) == {"INSPECT_SCENE", "EDIT_SCENE", "TRANSFORM_OBJECTS", "CAPTURE_VIEWPORT"}
    assert not definitions["scene.variant.inspect"].modifying


@pytest.mark.parametrize("method,field,value", [
    ("scene_variant_capture", "light_objects", []),
    ("scene_variant_capture", "protected_objects", ["M"]*33),
    ("scene_variant_capture", "expected_library_revision", True),
    ("scene_variant_apply", "expected_fingerprint", "guessed"),
    ("scene_variant_preview", "variant_id", "Camera"),
])
def test_wrapper_strict_types(method, field, value):
    annotation = get_type_hints(getattr(SceneVariantTools, method), include_extras=True)[field]
    with pytest.raises(ValidationError):
        TypeAdapter(annotation).validate_python(value)


def test_wrappers_forward_exact_cas_and_token():
    calls = []

    async def call(method, params=None):
        calls.append((method, params))
        return {}

    tools = SceneVariantTools(NS(call=call))
    asyncio.run(tools.scene_variant_apply("v_"+"a"*32, 2, "b"*64, "c"*64))
    assert calls == [("scene.variant.apply", {"variant_id": "v_"+"a"*32,
        "expected_library_revision": 2, "expected_library_fingerprint": "b"*64, "expected_fingerprint": "c"*64})]


class Native(NS):
    def __eq__(self, other):
        return self is other


@pytest.fixture
def transaction(addon_package, monkeypatch):
    module = importlib.import_module(addon_package+".tools.scene_variants")
    records = importlib.import_module(addon_package+".cinematic_variants")
    before, desired = control(records), control(records)
    desired["location"] = [1., 2., 3.]
    desired["settings"]["lens"] = 65.
    data = Native(dof=Native(), lens=50.)
    obj = Native(name="Camera", type="CAMERA", data=data, rotation_mode="XYZ", location=[0., 0., 0.])
    callbacks = []
    registry = importlib.import_module(addon_package+".tool_registry").ToolRegistry(enabled_toolsets=("scene_edit",))
    module.register_tools(registry)
    context = NS(require=lambda *args: None, state=NS(snapshot=lambda: {}), registry=registry,
        check_cancelled=lambda: [cb() for cb in callbacks], request_lifecycle=None)
    bpy = NS(context=NS(scene={}, view_layer=NS(update=lambda: None)))
    current = copy.deepcopy(before)

    def read(_obj):
        return {**copy.deepcopy(current), "location": list(obj.location),
            "settings": {**current["settings"], "lens": data.lens}}

    monkeypatch.setattr(module, "_controls", lambda *args: [obj])
    monkeypatch.setattr(module, "_control", read)
    monkeypatch.setattr(module, "_profile", lambda *args: {"protected": 1})
    monkeypatch.setattr(module, "_runtime", lambda *args: {"scene": 1})
    record = {"protected_objects": ["Prop"], "variant_id": "v_"+"f"*32}
    prepared = (bpy, None, record, [obj], [before], [desired], {"protected": 1}, {"scene": 1}, "fingerprint")
    tx = module._Transaction(context, prepared, module.APPLY)
    return module, tx, obj, callbacks


def test_transaction_exact_readback_and_compensation(transaction):
    _module, tx, obj, _callbacks = transaction
    tx.run()
    assert obj.location == [1., 2., 3.] and obj.data.lens == 65.
    tx.restore()
    assert obj.location == [0., 0., 0.] and obj.data.lens == 50.


def test_changed_unowned_control_refuses_compensation(transaction):
    module, tx, obj, _callbacks = transaction
    tx.run()
    obj.location = [7., 8., 9.]
    failure = module._failure(tx, RuntimeError("injected"))
    assert failure.context["possible_mutation"] and not failure.context["rollback_verified"]
    assert obj.location == [7., 8., 9.]


def test_revoked_permission_refuses_recovery(transaction):
    module, tx, obj, _callbacks = transaction
    tx.run()

    def denied(*_args):
        raise RuntimeError("consent revoked")

    tx.context.require = denied
    failure = module._failure(tx, RuntimeError("injected"))
    assert not failure.context["rollback_verified"] and obj.data.lens == 65.


def test_gate_callback_mutation_cannot_become_expected_state(transaction):
    _module, tx, obj, callbacks = transaction
    calls = [0]

    def mutate():
        calls[0] += 1
        if calls[0] == 2:
            obj.data.lens = 99.

    callbacks.append(mutate)
    with pytest.raises(Exception, match="protected data or control output changed"):
        tx.run()
    assert obj.data.lens == 99.


def test_native_struct_without_idproperty_storage_is_explicitly_supported(addon_package):
    module = importlib.import_module(addon_package+".tools.scene_variants")

    class Socket:
        bl_rna = NS(properties=())

        def keys(self):
            raise TypeError("bpy_struct.keys(): this type doesn't support IDProperties")

    assert module._primitive(Socket()) == {}


def test_native_property_failure_is_not_silently_omitted(addon_package):
    module = importlib.import_module(addon_package+".tools.scene_variants")

    class Owner:
        bl_rna = NS(properties=())

        def keys(self):
            raise RuntimeError("native owner invalid")

    with pytest.raises(RuntimeError, match="native owner invalid"):
        module._primitive(Owner())


def prepared_from_transaction(tx):
    return (tx.bpy, tx.raw, tx.record, tx.controls, tx.before, tx.desired,
        tx.profile, tx.runtime, tx.fingerprint)


def test_apply_token_is_single_use(transaction, monkeypatch):
    module, tx, obj, _callbacks = transaction
    monkeypatch.setattr(module, "_prepare", lambda *_args: prepared_from_transaction(tx))
    module._PREVIEWS.clear()
    module._PREVIEWS["token"] = tx.fingerprint
    result = module.apply(tx.context, {"expected_fingerprint": "token"})
    assert result["changed"] and obj.data.lens == 65.
    with pytest.raises(Exception, match="fresh current preview"):
        module.apply(tx.context, {"expected_fingerprint": "token"})
    assert "token" not in module._PREVIEWS


def test_stale_native_state_never_receives_preview_authority(transaction, monkeypatch):
    module, tx, obj, _callbacks = transaction
    monkeypatch.setattr(module, "_prepare", lambda *_args: prepared_from_transaction(tx))
    module._PREVIEWS.clear()
    module._PREVIEWS["token"] = "different native state"
    with pytest.raises(Exception, match="fresh current preview"):
        module.apply(tx.context, {"expected_fingerprint": "token"})
    assert obj.location == [0., 0., 0.] and obj.data.lens == 50.


@pytest.mark.parametrize("flags,code", [({"paused": True}, "AGENT_PAUSED"),
    ({"emergency_stopped": True}, "EMERGENCY_STOPPED")])
def test_recovery_still_obeys_visible_pause_and_emergency_stop(transaction, flags, code):
    module, tx, obj, _callbacks = transaction
    tx.run()
    tx.context.state.snapshot = lambda: flags
    with pytest.raises(Exception) as failure:
        tx.restore()
    assert failure.value.code == code
    assert obj.data.lens == 65.
    wrapped = module._failure(tx, RuntimeError("injected"))
    assert wrapped.context["possible_mutation"] and not wrapped.context["rollback_verified"]


@pytest.fixture
def compatibility_camera(addon_package):
    module = importlib.import_module(addon_package+".tools.scene_variants")
    fields = ("fisheye_fov", "fisheye_lens", "fisheye_polynomial_k0", "fisheye_polynomial_k1",
        "fisheye_polynomial_k2", "fisheye_polynomial_k3", "fisheye_polynomial_k4",
        "latitude_min", "latitude_max", "longitude_min", "longitude_max")
    values = {name: .125*(index+1) for index, name in enumerate(fields)}
    owner = NS(**values, panorama_type="FISHEYE_EQUISOLID", bl_rna=NS(identifier="Camera", properties={
        "panorama_type": NS(enum_items=NS(get=lambda _name: NS(value=2))) }))
    return module, owner, {**values, "panorama_type": 2}


def test_only_exact_redundant_native_camera_compatibility_is_canonical(compatibility_camera):
    module, owner, values = compatibility_camera
    assert module._redundant_camera_compatibility(owner, values)
    owner.bl_rna.identifier = "Object"
    assert not module._redundant_camera_compatibility(owner, values)


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(another_custom_setting=1.),
    lambda value: value.pop("fisheye_fov"),
    lambda value: value.update(fisheye_lens=5.),
    lambda value: value.update(panorama_type=3),
    lambda value: value.update(fisheye_fov=float("nan")),
])
def test_custom_cycles_payloads_remain_protected(compatibility_camera, mutate):
    module, owner, values = compatibility_camera
    mutate(values)
    assert not module._redundant_camera_compatibility(owner, values)


def test_failed_apply_consumes_preview_and_measures_owned_compensation(transaction, monkeypatch):
    module, tx, obj, callbacks = transaction
    monkeypatch.setattr(module, "_prepare", lambda *_args: prepared_from_transaction(tx))
    module._PREVIEWS.clear()
    module._PREVIEWS["token"] = tx.fingerprint
    calls = [0]

    def fail_after_native_write():
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError("injected cancellation after one write")

    callbacks.append(fail_after_native_write)
    with pytest.raises(Exception) as failure:
        module.apply(tx.context, {"expected_fingerprint": "token"})
    assert failure.value.context["execution_started"]
    assert failure.value.context["rollback_verified"]
    assert obj.location == [0., 0., 0.] and obj.data.lens == 50.
    assert "token" not in module._PREVIEWS


def test_protected_custom_id_reference_is_rejected_instead_of_reduced_to_properties(addon_package):
    module = importlib.import_module(addon_package+".tools.scene_variants")

    class ReferencedObject:
        bl_rna = NS(identifier="Object")
        def as_pointer(self):
            return 12345

        def keys(self):
            return ()

    class Owner(dict):
        bl_rna = NS(properties=())

    with pytest.raises(Exception, match="native references"):
        module._primitive(Owner(unreviewed_target=ReferencedObject()))


def test_boolean_and_integer_aliases_are_not_native_compatibility_evidence(compatibility_camera):
    module, owner, values = compatibility_camera
    values["latitude_min"] = True  # Native value is exactly float 1.0.
    assert not module._redundant_camera_compatibility(owner, values)


@pytest.mark.parametrize("dependency", ["background_set", "rigidbody_world", "camera_backgrounds",
    "aovs", "lightgroups", "freestyle", "rigid_body", "force_field"])
def test_unreviewed_static_scene_dependencies_fail_closed(addon_package, dependency):
    module = importlib.import_module(addon_package+".tools.scene_variants")
    scene = NS(objects=[], view_layers=[], render=NS(use_freestyle=False))
    if dependency in {"background_set", "rigidbody_world"}:
        setattr(scene, dependency, NS())
    elif dependency == "camera_backgrounds":
        scene.objects.append(NS(type="CAMERA", data=NS(background_images=[NS()])))
    elif dependency in {"aovs", "lightgroups"}:
        scene.view_layers.append(NS(**{dependency: [NS()]}))
    elif dependency == "freestyle":
        scene.render.use_freestyle = True
    elif dependency == "rigid_body":
        scene.objects.append(NS(type="MESH", rigid_body=NS()))
    else:
        scene.objects.append(NS(type="EMPTY", field=NS(type="FORCE")))
    with pytest.raises(Exception, match=r"unreviewed|static|Cinematic"):
        module._static_dependencies(scene)


def test_empty_inactive_static_dependency_slots_are_supported(addon_package):
    module = importlib.import_module(addon_package+".tools.scene_variants")
    module._static_dependencies(NS(background_set=None, rigidbody_world=None,
        objects=[NS(type="CAMERA", data=NS(background_images=[]), field=NS(type="NONE"))],
        view_layers=[NS(aovs=[], lightgroups=[])], render=NS(use_freestyle=False)))


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("flag,code", [("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")])
def test_permission_provider_stop_before_last_write_boundary(transaction, addon_package, monkeypatch, recovery, flag, code):
    module, tx, obj, _callbacks = transaction
    permissions = importlib.import_module(addon_package+".permissions")
    if recovery:
        tx.run()
    expected_location, expected_lens = list(obj.location), obj.data.lens
    flags, calls, writes = {}, [0], []
    # Recovery validates the complete current publication once before its
    # per-field gate. Poison the final provider pass at that actual write gate.
    # Each require reads one coherent grant set. Forward writes have two
    # provider passes; recovery also validates the publication before its gate.
    poison_at = 4 if recovery else 2

    def provider():
        calls[0] += 1
        if calls[0] == poison_at:
            flags[flag] = True
        return {permission.value: True for permission in permissions.Permission}

    manager = permissions.PermissionManager(provider)
    tx.context.require = lambda *required: manager.require(required)
    tx.context.state.snapshot = lambda: dict(flags)
    native_setattr = Native.__setattr__

    def tracked_setattr(owner, name, value):
        if (owner is obj and name == "location") or (owner is obj.data and name == "lens"):
            writes.append({"field": name, "stopped": bool(flags.get(flag))})
        native_setattr(owner, name, value)

    monkeypatch.setattr(Native, "__setattr__", tracked_setattr)
    with pytest.raises(module.BridgeError) as failure:
        (tx.restore if recovery else tx.run)()
    assert failure.value.code == code
    assert calls[0] >= poison_at
    assert writes == []
    assert obj.location == expected_location and obj.data.lens == expected_lens


@pytest.mark.parametrize("recovery", [False, True])
def test_permission_provider_mode_switch_has_post_provider_scope_cas(transaction, addon_package, monkeypatch, recovery):
    module, tx, obj, _callbacks = transaction
    permissions = importlib.import_module(addon_package+".permissions")
    tx.bpy.context.mode = "OBJECT"
    tx.runtime = {"scene": 1, "mode": "OBJECT"}
    monkeypatch.setattr(module, "_runtime", lambda bpy: {"scene": 1, "mode": bpy.context.mode})
    if recovery:
        tx.run()
    expected_location, expected_lens = list(obj.location), obj.data.lens
    calls = [0]
    poison_at = 4 if recovery else 2

    def provider():
        calls[0] += 1
        if calls[0] == poison_at:
            tx.bpy.context.mode = "EDIT_MESH"
        return {permission.value: True for permission in permissions.Permission}

    manager = permissions.PermissionManager(provider)
    tx.context.require = lambda *required: manager.require(required)
    with pytest.raises(module.BridgeError, match="protected data or control output changed"):
        (tx.restore if recovery else tx.run)()
    assert calls[0] >= poison_at
    assert obj.location == expected_location and obj.data.lens == expected_lens


@pytest.mark.parametrize("flag", ["paused", "emergency_stopped"])
def test_readonly_variant_inspection_remains_available_under_stop_state(addon_package, monkeypatch, flag):
    module = importlib.import_module(addon_package+".tools.scene_variants")
    permissions = importlib.import_module(addon_package+".permissions")
    flags = {flag: True}
    manager = permissions.PermissionManager(lambda: {permission.value: True for permission in permissions.Permission})
    context = NS(require=lambda *required: manager.require(required), state=NS(snapshot=lambda: dict(flags)), check_cancelled=None)
    monkeypatch.setattr(module, "require_blender", lambda: NS(context=NS(scene={})))
    result = module.inspect(context, {})
    assert result["variants"] == [] and not result["authority_loaded"]
    assert flags == {flag: True}


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("signal", ["toolset", "queued_cancel", "queued_expiry", "disconnect", "handoff_rejected"])
def test_canonical_request_authority_loss_prevents_controls_and_compensation(transaction, addon_package, monkeypatch, recovery, signal):
    module, tx, obj, _callbacks = transaction
    if recovery:
        tx.run()
    expected_location, expected_lens = list(obj.location), obj.data.lens
    queue = importlib.import_module(addon_package+".command_queue")
    protocol = importlib.import_module(addon_package+".protocol")
    lifetimes = importlib.import_module(addon_package+".request_lifecycle")
    permissions = importlib.import_module(addon_package+".permissions")
    lifetime = lifetimes.RequestLifetime(lifetimes.ConnectionLifetime())
    queued = queue.QueuedRequest(protocol.Request(id="cinematic-canonical", method="scene.variant.apply"))
    assert queued.try_start()
    tx.context.check_cancelled, tx.context.request_lifecycle = queued.check_active, lifetime
    poisoned, writes = [False], []

    def provider():
        if not poisoned[0]:
            poisoned[0] = True
            if signal == "toolset":
                tx.context.registry.disable_toolset("scene_edit")
            elif signal == "queued_cancel":
                queued.cancel_pending(module.BridgeError("TIMEOUT", "Canonical caller canceled"))
            elif signal == "queued_expiry":
                queued.deadline = 0
            elif signal == "disconnect":
                lifetime.connection.disconnected.set()
            else:
                lifetime.acknowledge(False)
        return {permission.value: True for permission in permissions.Permission}

    manager = permissions.PermissionManager(provider)
    tx.context.require = lambda *required: manager.require(required)
    native_setattr = Native.__setattr__

    def tracked_setattr(owner, name, value):
        if (owner is obj and name == "location") or (owner is obj.data and name == "lens"):
            writes.append(name)
        native_setattr(owner, name, value)

    monkeypatch.setattr(Native, "__setattr__", tracked_setattr)
    with pytest.raises(module.BridgeError) as caught:
        (tx.restore if recovery else tx.run)()
    assert poisoned[0] and not writes
    assert caught.value.code == ("TOOLSET_DISABLED" if signal == "toolset" else "TIMEOUT")
    assert obj.location == expected_location and obj.data.lens == expected_lens
    failure = module._failure(tx, caught.value)
    assert not writes and not failure.context["rollback_verified"]
    assert failure.context["possible_mutation"] == recovery
