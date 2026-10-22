"""Live render authority/CAS, private publication and encoded-PNG adversaries."""

from __future__ import annotations

import hashlib
import importlib
import struct
import zlib
from array import array
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


def png(*, width=16, height=16, depth=8, color=2, row_filter=0, metadata=None, raw_data=None):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    components = {0: 1, 2: 3, 4: 2, 6: 4}.get(color, 3)
    rows = (bytes([row_filter]) + bytes([37]) * width * components * (depth // 8)) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, 0))
        + (b"" if metadata is None else chunk(*metadata))
        + chunk(b"IDAT", zlib.compress(rows) if raw_data is None else raw_data)
        + chunk(b"IEND", b"")
    )


def test_native_png_accepts_opaque_metadata_without_decoding(addon_package, tmp_path):
    module = importlib.import_module(f"{addon_package}.render_png")
    path = tmp_path / "native.png"
    # Deliberately not a TIFF payload: render metadata is opaque, never fed to
    # an EXIF decoder or relaxed image-import admission.
    payload = png(metadata=(b"eXIf", b"opaque native producer metadata"))
    path.write_bytes(payload)
    calls = []
    result = module.verify(path, lambda: calls.append(True))
    assert result["file_sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["encoded_png_verified"] and result["decoded_scanline_bytes"] == 16 * 49
    assert calls and result["opaque_metadata_bytes"] == 31


@pytest.mark.parametrize(
    "payload",
    [
        b"bad",
        png()[:-1],
        png() + b"trailing",
        png(row_filter=9),
        png(width=0),
        png(width=1025, height=1024),
        png(depth=1),
        png(color=3),
        png(raw_data=b"not-deflate"),
        png(raw_data=zlib.compress(b"excess" * 1000)),
        png(raw_data=zlib.compress(b"\0" * (16 * 49)) + b"after-deflate"),
        png(metadata=(b"acTL", b"animation")),
        png(metadata=(b"ABCD", b"critical")),
        png(metadata=(b"iCCP", b"x" * (256 * 1024 + 1))),
    ],
)
def test_native_png_rejects_malformed_or_unbounded_data(addon_package, tmp_path, payload):
    module = importlib.import_module(f"{addon_package}.render_png")
    path = tmp_path / "native.png"
    path.write_bytes(payload)
    with pytest.raises(module.invalid_argument("").__class__):
        module.verify(path, lambda: None)


def test_native_png_rejects_crc_corruption(addon_package, tmp_path):
    module = importlib.import_module(f"{addon_package}.render_png")
    data = bytearray(png())
    data[-1] ^= 1
    path = tmp_path / "native.png"
    path.write_bytes(data)
    with pytest.raises(module.invalid_argument("").__class__, match="checksum"):
        module.verify(path, lambda: None)


def test_native_png_cancellation_propagates_before_read(addon_package, tmp_path):
    module = importlib.import_module(f"{addon_package}.render_png")
    errors = importlib.import_module(f"{addon_package}.errors")

    def stop():
        raise errors.BridgeError(errors.ErrorCode.TIMEOUT, "owner lost")

    with pytest.raises(errors.BridgeError, match="owner lost"):
        module.verify(tmp_path / "absent.png", stop)


def test_native_png_checks_cancellation_within_one_large_decoded_chunk(addon_package, tmp_path):
    module = importlib.import_module(f"{addon_package}.render_png")
    errors = importlib.import_module(f"{addon_package}.errors")
    path = tmp_path / "tall.png"
    path.write_bytes(png(width=1, height=8192))
    calls = []

    def cancel_during_rows():
        calls.append(True)
        if len(calls) == 8:
            raise errors.BridgeError("TIMEOUT", "cancel during decoded scanline validation")

    with pytest.raises(errors.BridgeError, match="decoded scanline"):
        module.verify(path, cancel_during_rows)
    assert len(calls) == 8


class Props(list):
    def get(self, name):
        return next((p for p in self if p.identifier == name), None)


def prop(name, kind="INT", *, runtime=False, readonly=False, fixed=None, default=0):
    p = NS(
        identifier=name,
        type=kind,
        is_runtime=runtime,
        is_readonly=readonly,
        fixed_type=NS(identifier=fixed),
        default=default,
    )
    p.as_pointer = lambda: id(p)
    return p


@pytest.mark.parametrize(
    "build,identifier,accepted",
    [
        (b"62c1db4208e8", "BLENDER_EEVEE_NEXT", True),
        (b"62c1db4208e8", "BLENDER_EEVEE", False),
        (b"d13f752e3b9c", "BLENDER_EEVEE", True),
        (b"d13f752e3b9c", "BLENDER_EEVEE_NEXT", False),
        (b"unknown", "BLENDER_EEVEE", False),
        (b"62c1db4208e8", "CYCLES", False),
    ],
)
def test_native_engine_requires_exact_build_specific_identifier(
    addon_package, build, identifier, accepted
):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")
    bpy = NS(app=NS(build_hash=build))
    if accepted:
        module.native_engine(bpy, identifier)
    else:
        with pytest.raises(module.BridgeError, match="exact reviewed build"):
            module.native_engine(bpy, identifier)


@pytest.mark.parametrize(
    "build,method,socket,expected",
    [
        ("62c1db4208e8", "BURLEY", "Subsurface IOR", False),
        ("62c1db4208e8", "RANDOM_WALK", "Subsurface IOR", False),
        ("62c1db4208e8", "RANDOM_WALK_SKIN", "Subsurface IOR", True),
        ("62c1db4208e8", "BURLEY", "Subsurface Anisotropy", False),
        ("62c1db4208e8", "RANDOM_WALK", "Subsurface Anisotropy", True),
        ("d13f752e3b9c", "RANDOM_WALK_LEGACY", "Subsurface IOR", False),
        ("d13f752e3b9c", "RANDOM_WALK_SKIN", "Subsurface IOR", True),
        ("d13f752e3b9c", "BURLEY", "Subsurface Anisotropy", None),
        ("d13f752e3b9c", "RANDOM_WALK", "Roughness", None),
    ],
)
def test_exact_source_version_specific_availability_prediction(
    addon_package, build, method, socket, expected
):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")
    node_rna = NS(
        identifier="ShaderNodeBsdfPrincipled", properties=Props([prop("subsurface_method", "ENUM")])
    )
    socket_rna = NS(
        identifier="NodeSocketFloat",
        properties=Props([prop("identifier", "STRING", readonly=True), prop("enabled", "BOOLEAN")]),
    )
    node = NS(bl_rna=node_rna, subsurface_method=method)
    native_socket = NS(bl_rna=socket_rna, identifier=socket)
    bpy = NS(
        app=NS(build_hash=build.encode()),
        types=NS(
            ShaderNodeBsdfPrincipled=NS(bl_rna=node_rna), NodeSocketFloat=NS(bl_rna=socket_rna)
        ),
    )
    reader = module.Reader(bpy, None, predict_native_availability=True)
    assert reader.availability(node, "inputs", native_socket) == (
        None if expected is None else {"enabled": expected}
    )
    assert module.Reader(bpy, None).availability(node, "inputs", native_socket) is None
    assert reader.availability(node, "outputs", native_socket) is None


@pytest.mark.parametrize(
    "kind",
    [
        "Object",
        "Mesh",
        "Collection",
        "World",
        "Material",
        "ShaderNodeBsdfPrincipled",
        "NodeSocketFloat",
        "RenderSettings",
        "ImageFormatSettings",
        "SceneEEVEE",
        "RaytraceEEVEE",
        "ViewLayerEEVEE",
        "MaterialSlot",
        "ObjectLightLinking",
        "UVLoopLayers",
        "UnitSettings",
    ],
)
def test_render_descriptor_admission_never_reads_unknown_runtime_getter(addon_package, kind):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")
    called = []

    class NativeOwner:
        def as_pointer(self):
            return id(self)

        @property
        def dangerous(self):
            called.append(True)
            return 1

        def keys(self):
            return []

    owner = NativeOwner()
    owner.bl_rna = NS(identifier=kind, properties=Props([prop("dangerous", runtime=True)]))
    bpy = NS(types=NS(**{kind: NS(bl_rna=owner.bl_rna)}))
    with pytest.raises(module.BridgeError, match="runtime RNA"):
        module.Reader(bpy, None).primitive(owner)
    assert called == []


def test_reviewed_selection_ui_descriptor_is_not_read(addon_package):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")

    class NativeOwner:
        def as_pointer(self):
            return id(self)

        def keys(self):
            return []

        @property
        def active_selection_set(self):
            raise AssertionError("ignored bundled UI getter must not execute")

    owner = NativeOwner()
    owner.bl_rna = NS(
        identifier="Object", properties=Props([prop("active_selection_set", runtime=True)])
    )
    bpy = NS(types=NS(Object=NS(bl_rna=owner.bl_rna)))
    result = module.Reader(bpy, None).primitive(owner)
    assert result[2] == ()


@pytest.mark.parametrize("kind,fixed", [("Scene", "CyclesRenderSettings"), ("ViewLayer", "CyclesRenderLayerSettings")])
def test_system_runtime_storage_refuses_before_getter_or_raw_keys(addon_package, kind, fixed):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")

    class NativeOwner:
        @property
        def cycles(self):
            raise AssertionError("SYSTEM pointer getter must not execute")

        def keys(self):
            raise AssertionError("ordinary keys cannot prove SYSTEM storage")

    owner = NativeOwner()
    owner.bl_rna = NS(identifier=kind, properties=Props([prop("cycles", "POINTER", runtime=True, readonly=True, fixed=fixed)]))
    bpy = NS(app=NS(build_hash=b"d13f752e3b9c"), types=NS(**{kind: NS(bl_rna=owner.bl_rna)}))
    with pytest.raises(module.BridgeError, match="SYSTEM storage") as caught:
        module.Reader(bpy, None).primitive(owner)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context["runtime_getter_fallback_used"] is False


def test_system_storage_refusal_does_not_depend_on_visible_runtime_descriptors(addon_package):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")

    class NativeBuild:
        app = NS(build_hash=b"d13f752e3b9c")

        @property
        def context(self):
            raise AssertionError("Unsupported SYSTEM build must refuse before RNA or context reads")

    with pytest.raises(module.BridgeError, match="SYSTEM storage") as caught:
        module.snapshot(NativeBuild(), object())
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context["runtime_getter_fallback_used"] is False


@pytest.mark.parametrize("before,after", [(False, 0), (0, 0.0), (0.0, -0.0), ({"nested": [False]}, {"nested": [0]}), ({"nested": [0.0]}, {"nested": [-0.0]}), (array("f", [1.0]), array("d", [1.0])), ({}, array("i"))])
def test_provider_custom_scalar_type_or_signed_zero_drift_stops_before_owned_write(
    addon_package, monkeypatch, before, after
):
    module = importlib.import_module(f"{addon_package}.tools._render_boundary")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    states = importlib.import_module(f"{addon_package}.state")

    class Native(dict):
        a = 0

        def as_pointer(self):
            return id(self)

    owner = Native(protected=before)
    owner.bl_rna = NS(identifier="RenderSettings", properties=Props([prop("a")]))
    bpy = NS(types=NS(RenderSettings=NS(bl_rna=owner.bl_rna)))
    scene = object()
    registry = registry_module.ToolRegistry(enabled_toolsets=["render"])
    registry.register("render.configure", lambda *_: None, toolset="render", modifies=True,
                      permissions=(permissions.Permission.EDIT_RENDER,))
    calls = []

    def provider():
        calls.append(True)
        owner["protected"] = after
        return {permission.value: True for permission in permissions.Permission}

    context = registry_module.ToolContext(states.BridgeState(), permissions.PermissionManager(provider), registry, None)
    monkeypatch.setattr(module.profile, "snapshot", lambda *_args, **_kwargs: module.profile.Reader(bpy, scene).custom(owner))
    boundary = module.Boundary(context, bpy, scene, "render.configure", [(owner, "a", 1)], initial_check=False)
    # These changes collided in the previous untagged recursive projection.
    assert module.profile.value(before) == module.profile.value(after)
    with pytest.raises(module.BridgeError, match="owned settings changed"):
        boundary.apply()
    assert calls and owner.a == 0 and boundary.published == []
    assert module.profile.value(owner["protected"], custom_scalars=True) == module.profile.value(after, custom_scalars=True)
    assert module.profile.value(before, custom_scalars=True) != module.profile.value(after, custom_scalars=True)


@pytest.mark.parametrize("code", [None, "", "q", b"f", 1, "float32"])
def test_custom_native_array_requires_reviewed_typecode_before_iteration(addon_package, monkeypatch, code):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")
    iterations = []

    class NativeArray:
        typecode = code

        def __iter__(self):
            iterations.append(True)
            yield 1.0

    monkeypatch.setattr(module, "IDPropertyArray", NativeArray)
    with pytest.raises(module.BridgeError, match="typecode"):
        module.value(NativeArray(), custom_scalars=True)
    assert iterations == []


def test_custom_native_array_missing_typecode_never_becomes_python_sequence(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")

    class NativeArray:
        def __iter__(self):
            raise AssertionError("Missing native array metadata must refuse before iteration")

    monkeypatch.setattr(module, "IDPropertyArray", NativeArray)
    with pytest.raises(module.BridgeError, match="typecode is unavailable"):
        module.value(NativeArray(), custom_scalars=True)


def test_custom_sequence_kinds_and_native_arrays_remain_distinct(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")

    class NativeArray:
        typecode = "f"

        def __iter__(self):
            return iter([1.0])

    monkeypatch.setattr(module, "IDPropertyArray", NativeArray)
    projections = [module.value(raw, custom_scalars=True) for raw in ([1.0], (1.0,), array("f", [1.0]), NativeArray())]
    assert len(set(projections)) == 4
    assert module.value([1.0]) == module.value((1.0,)) == module.value(array("f", [1.0]))


def test_unreviewed_custom_iterable_refuses_before_python_metadata_or_iteration(addon_package):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")

    class Unreviewed:
        @property
        def typecode(self):
            raise AssertionError("Unreviewed Python metadata must not execute")

        def __iter__(self):
            raise AssertionError("Unreviewed Python iterator must not execute")

    with pytest.raises(module.BridgeError, match="explicit reader"):
        module.value(Unreviewed(), custom_scalars=True)


def test_unreviewed_custom_metaclass_cannot_run_during_type_classification(addon_package):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")
    calls = []

    class HostileMeta(type):
        def __eq__(cls, _other):
            calls.append("class equality")
            raise AssertionError("Unknown class equality must not run")

        def __getattribute__(cls, name):
            if name == "__name__":
                calls.append("class name")
                raise AssertionError("Unknown class metadata must not run")
            return type.__getattribute__(cls, name)

    class Unreviewed(metaclass=HostileMeta):
        pass

    raw = object.__new__(Unreviewed)
    with pytest.raises(module.BridgeError, match="explicit reader"):
        module.value(raw, custom_scalars=True)
    assert calls == []


@pytest.mark.parametrize("native_role,authored", [(1, "original"), (2, "original"), (1, "new authored value")])
def test_checkpoint_notification_uses_frozen_prediction_and_readonly_cas(
    live_boundary, monkeypatch, native_role, authored
):
    f = live_boundary
    module = importlib.import_module(f"{f.module.__package__}._render_checkpoint")
    f.context.checkpoints = NS(_prefix="BCB1:" + "a" * 32 + ":")
    f.scene.role = 0

    def snapshot(*_args, **kwargs):
        return (1 if kwargs.get("predict_checkpoint_roles") else f.scene.role, f.scene.protected)

    monkeypatch.setattr(module.profile, "snapshot", snapshot)
    boundary = f.module.Boundary(
        f.context, object(), f.scene, "render.configure", [(f.owner, "a", 10)],
        checkpoint_prefix=f.context.checkpoints._prefix, initial_check=False,
    )
    admission = module.Admission(
        f.context, object(), f.scene, "render.configure", external=False, boundary=boundary,
    )
    assert f.calls == []
    f.scene.role, f.scene.protected = native_role, authored
    if (native_role, authored) == (1, "original"):
        admission.after_native_push()
        admission.check_after_read()
        assert boundary.protected == (1, "original")
    else:
        with pytest.raises(f.errors.BridgeError) as caught:
            admission.after_native_push()
        f.scene.role, f.scene.protected = 1, "original"
        with pytest.raises(f.errors.BridgeError) as repeated:
            admission.check_after_read()
        assert repeated.value is caught.value
    assert f.calls == [] and f.owner.a == 0


def test_predicted_native_role_cannot_be_admitted_before_notification(live_boundary, monkeypatch):
    f = live_boundary
    module = importlib.import_module(f"{f.module.__package__}._render_checkpoint")
    f.context.checkpoints = NS(_prefix="BCB1:" + "a" * 32 + ":")
    f.scene.role = 0
    monkeypatch.setattr(module.profile, "snapshot", lambda *_args, **kw: (1 if kw.get("predict_checkpoint_roles") else f.scene.role,))
    admission = module.Admission(f.context, object(), f.scene, "render.configure", external=False)
    f.scene.role = 1
    with pytest.raises(f.errors.BridgeError):
        admission.check_after_read()
    with pytest.raises(f.errors.BridgeError):
        admission.after_native_push()
    assert f.calls == []


def test_native_particle_roles_preserve_original_and_require_active_object(addon_package):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")

    class Native:
        def __init__(self, kind, properties=()):
            self.bl_rna = NS(identifier=kind, properties=Props(properties))

        def as_pointer(self):
            return id(self)

    active = Native("Object")
    scene = Native("Scene", [prop("tool_settings", "POINTER", readonly=True, fixed="ToolSettings"), prop("original", "POINTER", readonly=True, fixed="ID")])
    settings = Native("ToolSettings", [prop("particle_edit", "POINTER", readonly=True, fixed="ParticleEdit")])
    particle = Native("ParticleEdit", [prop("object", "POINTER", readonly=True, fixed="Object")])
    scene.tool_settings, scene.original, scene.self_count = settings, scene, 0
    scene.user_of_id = lambda _owner: scene.self_count
    settings.particle_edit, particle.object = particle, None
    bpy = NS(types=NS(**{owner.bl_rna.identifier: NS(bl_rna=owner.bl_rna) for owner in (scene, settings, particle, active)}), context=NS(view_layer=NS(objects=NS(active=active))))
    reader = module.Reader(bpy, scene)
    baseline = reader.checkpoint_roles()
    predicted = reader.checkpoint_roles(predicted=True)
    assert baseline[-1] == (0, None) and predicted[-1] == (1, module.key(active))
    scene.self_count, particle.object = 1, active
    assert reader.checkpoint_roles() == predicted
    scene.original = active
    assert reader.checkpoint_roles() != predicted
    bpy.context.view_layer.objects.active = None
    with pytest.raises(module.BridgeError, match="non-null active"):
        reader.checkpoint_roles(predicted=True)


def test_raw_custom_id_alias_is_refused_before_identity_getter(addon_package):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")

    class Alias:
        def as_pointer(self):
            raise AssertionError("custom native alias identity must not be read")

    with pytest.raises(module.BridgeError, match="ID-property references"):
        module.value({"scene_alias": Alias()}, allow_ids=False)


class Owner:
    def __init__(self, **values):
        self.__dict__.update(values)
        self.hook = None

    def as_pointer(self):
        return id(self)

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)
        if key != "hook" and getattr(self, "hook", None):
            self.hook(key, value)


@pytest.fixture
def live_boundary(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools._render_boundary")
    registry_mod = importlib.import_module(f"{addon_package}.tool_registry")
    pm = importlib.import_module(f"{addon_package}.permissions")
    states = importlib.import_module(f"{addon_package}.state")
    errors = importlib.import_module(f"{addon_package}.errors")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    queues = importlib.import_module(f"{addon_package}.command_queue")
    reg = registry_mod.ToolRegistry(enabled_toolsets=["render"])
    reg.register(
        "render.configure",
        lambda *_: None,
        permissions=(pm.Permission.EDIT_RENDER,),
        toolset="render",
        modifies=True,
    )
    state = states.BridgeState()
    grants = {p.value: True for p in pm.Permission}
    calls = []
    provider_hook = [None]

    def provider():
        calls.append(True)
        if provider_hook[0]:
            provider_hook[0]()
        return grants

    owner, scene = Owner(a=0, b=0), NS(protected="original")
    request = protocol.Request(id="boundary", method="render.configure")
    queue = queues.QueuedRequest(request)
    assert queue.try_start()
    ctx = registry_mod.ToolContext(
        state,
        pm.PermissionManager(provider),
        reg,
        None,
        check_cancelled=queue.check_active,
        check_final_request=lambda: queues.QueuedRequest.check_active(queue),
    )

    class Reader:
        def __init__(self, *_args):
            pass

        def field(self, target, name):
            return getattr(target, name)

    monkeypatch.setattr(module.profile, "Reader", Reader)
    monkeypatch.setattr(module.profile, "snapshot", lambda *_, **_kwargs: (scene.protected,))
    return NS(
        module=module,
        context=ctx,
        owner=owner,
        scene=scene,
        registry=reg,
        grants=grants,
        state=state,
        calls=calls,
        provider_hook=provider_hook,
        queue=queue,
        errors=errors,
        create=lambda: module.Boundary(
            ctx, object(), scene, "render.configure", [(owner, "a", 1), (owner, "b", 2)]
        ),
    )


def test_provider_cannot_adopt_new_owned_setting_as_baseline(live_boundary):
    f = live_boundary

    def change():
        f.owner.a = 77
        f.provider_hook[0] = None

    f.provider_hook[0] = change
    with pytest.raises(f.errors.BridgeError, match="owned settings changed"):
        f.create()
    assert (f.owner.a, f.owner.b) == (77, 0)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("cancel", "TIMEOUT"),
        ("deadline", "TIMEOUT"),
        ("pause", "AGENT_PAUSED"),
        ("stop", "EMERGENCY_STOPPED"),
        ("permission", "PERMISSION_DENIED"),
        ("toolset", "TOOLSET_DISABLED"),
    ],
)
def test_lost_authority_after_first_native_setting_stops_next_write_and_recovery(
    live_boundary, fault, code
):
    f = live_boundary
    boundary = f.create()
    writes = []

    def hook(name, value):
        writes.append((name, value))
        if name == "a" and value == 1:
            if fault == "cancel":
                f.queue.cancel_pending(f.errors.BridgeError("TIMEOUT", "test caller lost"))
            elif fault == "deadline":
                f.queue.deadline = 0
            elif fault == "pause":
                f.state.set_paused(True)
            elif fault == "stop":
                f.state.set_emergency_stopped(True)
            elif fault == "permission":
                f.grants["EDIT_RENDER"] = False
            else:
                f.registry.disable_toolset("render")

    f.owner.hook = hook
    with pytest.raises(f.errors.BridgeError) as caught:
        boundary.apply()
    assert caught.value.code == code
    assert (f.owner.a, f.owner.b) == (1, 0)
    assert not boundary.restore()["restored"]
    assert writes == [("a", 1)]


def test_newer_manual_setting_is_not_overwritten_by_compensation(live_boundary):
    f = live_boundary
    boundary = f.create()

    def hook(name, value):
        if name == "a" and value == 1:
            f.owner.__dict__["a"] = 99

    f.owner.hook = hook
    with pytest.raises(f.errors.BridgeError):
        boundary.apply()
    assert not boundary.restore()["restored"] and (f.owner.a, f.owner.b) == (99, 0)


def test_partial_failed_native_setting_has_measured_exact_recovery(live_boundary):
    f = live_boundary
    boundary = f.create()

    def hook(name, value):
        if name == "a" and value == 1:
            raise RuntimeError("native setter wrote then failed")

    f.owner.hook = hook
    with pytest.raises(RuntimeError, match="wrote then failed"):
        boundary.apply()
    assert boundary.restore()["restored"] and (f.owner.a, f.owner.b) == (0, 0)


@pytest.mark.parametrize("unreadable", [False, True])
def test_failed_setter_keeps_primary_error_when_readback_is_unknown(
    live_boundary, monkeypatch, unreadable
):
    f = live_boundary
    boundary = f.create()
    primary = f.errors.BridgeError("PERMISSION_DENIED", "native setter primary refusal")

    def hook(name, value):
        if name == "a" and value == 1:
            f.owner.__dict__["a"] = 77
            raise primary

    f.owner.hook = hook
    original_read = boundary.read

    def read(owner, name):
        if unreadable and name == "a" and owner.a == 77:
            raise RuntimeError("secondary unavailable readback")
        return original_read(owner, name)

    monkeypatch.setattr(boundary, "read", read)
    with pytest.raises(f.errors.BridgeError) as caught:
        boundary.apply()
    assert caught.value is primary
    recovery = boundary.restore()
    annotated = boundary.annotate(primary, recovery)
    assert annotated.code == "PERMISSION_DENIED" and "primary refusal" in annotated.message
    assert annotated.context["failed_setter_observation"]["readback"] == (
        "unavailable" if unreadable else "unreviewed_value"
    )
    assert not recovery["restored"] and (f.owner.a, f.owner.b) == (77, 0)


def test_protected_change_during_setter_blocks_compensation(live_boundary):
    f = live_boundary
    boundary = f.create()

    def hook(name, value):
        if name == "a" and value == 1:
            f.scene.protected = "manual new protected data"

    f.owner.hook = hook
    with pytest.raises(f.errors.BridgeError):
        boundary.apply()
    assert not boundary.restore()["restored"] and f.scene.protected == "manual new protected data"
    assert (f.owner.a, f.owner.b) == (1, 0)


@pytest.mark.parametrize("outcome", ["raw native flag true", "predicted native flag false"])
def test_native_prediction_is_frozen_before_providers_and_only_used_after_finished(
    live_boundary, monkeypatch, outcome
):
    f = live_boundary
    f.registry.register(
        "render.execute",
        lambda *_: None,
        permissions=f.registry.get("render.configure").permissions,
        toolset="render",
        modifies=True,
    )
    f.scene.protected = "raw native flag true"

    def snapshot(*_args, **kwargs):
        return (
            "predicted native flag false"
            if kwargs.get("predict_native_availability")
            else f.scene.protected,
        )

    monkeypatch.setattr(f.module.profile, "snapshot", snapshot)
    boundary = f.module.Boundary(
        f.context, object(), f.scene, "render.execute", [(f.owner, "a", 1)]
    )
    f.scene.protected = "predicted native flag false"
    with pytest.raises(f.errors.BridgeError):
        boundary.check()
    boundary.native_started = True
    with pytest.raises(f.errors.BridgeError):
        boundary.check()
    boundary.native_completed = True
    with pytest.raises(f.errors.BridgeError):
        boundary.check()
    f.scene.protected = outcome
    boundary.seal_native_outcome()
    boundary.check()
    f.scene.protected = (
        "raw native flag true"
        if outcome == "predicted native flag false"
        else "predicted native flag false"
    )
    with pytest.raises(f.errors.BridgeError):
        boundary.check()
    f.scene.protected = "unrelated manual drift"
    with pytest.raises(f.errors.BridgeError):
        boundary.check()


@pytest.fixture
def stage(addon_package, monkeypatch, tmp_path):
    module = importlib.import_module(f"{addon_package}.render_staging")
    stopped = [False]
    checks = []

    class Boundary:
        native_completed = True
        native_started = True
        filesystem_checks = checks

        def check(self):
            self.final()
            for callback in self.filesystem_checks:
                callback()

        def final(self):
            if stopped[0]:
                raise module.BridgeError("TIMEOUT", "owner lost")

    monkeypatch.setattr(module, "_read_root", lambda: (str(tmp_path), ("reviewed_fixture",)))
    resource = module.Staging(Boundary(), str(tmp_path / "result.png"))
    resource.open()
    resource.payload.write_bytes(png(metadata=(b"eXIf", b"opaque")))
    resource.capture()
    return NS(module=module, resource=resource, stopped=stopped, root=tmp_path)


def test_publish_is_atomic_no_clobber_even_after_last_absence_check(stage, monkeypatch):
    f = stage
    link = f.module.os.link

    def race(source, target):
        Path(target).write_bytes(b"newer foreign file")
        return link(source, target)

    monkeypatch.setattr(f.module.os, "link", race)
    with pytest.raises(f.module.BridgeError, match="appeared after preflight"):
        f.resource.publish()
    f.resource.cleanup()
    assert (f.root / "result.png").read_bytes() == b"newer foreign file"
    assert (
        f.resource.evidence()["publication_attempted"]
        and not f.resource.evidence()["file_published"]
    )
    assert f.resource.evidence()["staging_cleanup"] == "complete"


def test_authority_loss_retains_private_bytes_and_prevents_publication_or_cleanup(stage):
    f = stage
    original = f.resource.payload.read_bytes()
    f.stopped[0] = True
    with pytest.raises(f.module.BridgeError, match="owner lost"):
        f.resource.publish()
    f.resource.cleanup()
    assert not f.resource.path.exists() and f.resource.payload.read_bytes() == original
    assert f.resource.evidence()["staging_cleanup"] == "retained_TIMEOUT"


def test_newer_private_bytes_are_never_adopted_or_deleted(stage):
    f = stage
    f.resource.payload.write_bytes(b"newer manual private bytes")
    with pytest.raises(f.module.BridgeError):
        f.resource.publish()
    f.resource.cleanup()
    assert (
        not f.resource.path.exists()
        and f.resource.payload.read_bytes() == b"newer manual private bytes"
    )
    assert f.resource.evidence()["staging_cleanup"].startswith("retained_")


def test_success_retains_exact_published_bytes_and_removes_only_private_resource(stage):
    f = stage
    data = f.resource.payload.read_bytes()
    f.resource.publish()
    f.resource.cleanup()
    assert f.resource.path.read_bytes() == data and not f.resource.payload.exists()
    assert (
        f.resource.evidence()["published_bytes_verified"]
        and f.resource.evidence()["staging_cleanup"] == "complete"
    )


def test_filesystem_error_after_link_reports_unknown_publication_and_preserves_target(
    stage, monkeypatch
):
    f = stage
    link = f.module.os.link
    original = f.resource.payload.read_bytes()

    def unknown(source, target):
        link(source, target)
        raise OSError("injected filesystem completion error")

    monkeypatch.setattr(f.module.os, "link", unknown)
    with pytest.raises(OSError, match="completion error"):
        f.resource.publish()
    f.resource.cleanup()
    assert f.resource.path.read_bytes() == original
    assert f.resource.evidence()["file_published"] is None
    assert f.resource.evidence()["publication_outcome_unknown"]
    assert not f.resource.evidence()["published_bytes_verified"]


def test_overwrite_existing_is_refused_before_private_resource_creation(
    addon_package, monkeypatch, tmp_path
):
    module = importlib.import_module(f"{addon_package}.render_staging")
    path = tmp_path / "result.png"
    path.write_bytes(b"protected existing file")
    monkeypatch.setattr(module, "_read_root", lambda: (str(tmp_path), ("reviewed_fixture",)))
    boundary = NS(check=lambda: None, filesystem_checks=[])
    with pytest.raises(module.BridgeError) as caught:
        module.Staging(boundary, str(path), overwrite=True)
    assert (
        caught.value.code == "NOT_IMPLEMENTED" and path.read_bytes() == b"protected existing file"
    )
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "started,completed,result", [(False, False, False), (True, False, None), (True, True, True)]
)
def test_native_exception_never_asserts_render_result_was_unchanged(
    addon_package, started, completed, result
):
    module = importlib.import_module(f"{addon_package}.render_staging")
    effects = module.native_render_effects(NS(native_started=started, native_completed=completed))
    assert effects["render_result_replaced"] is result
    assert effects["render_result_replacement_possible"] is started


def test_checkpoint_static_projection_validates_values_but_preserves_only_owned_marker_slot(
    addon_package,
):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")
    prefix = "BCB1:" + "a" * 32 + ":"

    class NativeOwner(dict):
        name = "Scene"
        authored = 1.0

        def as_pointer(self):
            return id(self)

    owner = NativeOwner(protected_custom="original")
    owner.bl_rna = NS(
        identifier="Scene", properties=Props([prop("name", "STRING"), prop("authored", "FLOAT")])
    )
    bpy = NS(types=NS(Scene=NS(bl_rna=owner.bl_rna)))
    reader = module.Reader(bpy, None, checkpoint_prefix=prefix)
    before = reader.primitive(owner)
    owner["_codex_bridge_undo_marker"] = prefix + "b" * 32
    owner.authored = 2.0
    assert reader.primitive(owner) == before
    owner["protected_custom"] = "newer manual custom value"
    assert reader.primitive(owner) != before
    owner["protected_custom"] = "original"
    owner.authored = float("inf")
    with pytest.raises(module.BridgeError, match="finite"):
        reader.primitive(owner)
    owner.authored = 2.0
    owner["_codex_bridge_undo_marker"] = "BCB1:" + "c" * 32 + ":" + "d" * 32
    with pytest.raises(module.BridgeError, match="not owned"):
        reader.primitive(owner)


@pytest.mark.parametrize(
    "fault",
    [
        "provider_source_drift",
        "checkpoint_manager",
        "checkpoint_namespace",
        "external_permission",
        "terminal_cancel",
    ],
)
def test_checkpoint_admission_freezes_before_providers_and_stops_before_checkpoint_write(
    live_boundary, monkeypatch, fault
):
    f = live_boundary
    module = importlib.import_module(f"{f.module.__package__}._render_checkpoint")
    f.context.checkpoints = NS(_prefix="BCB1:" + "a" * 32 + ":")

    def snapshot(*_args, **_kwargs):
        result = (f.scene.protected,)
        if armed[0] and fault == "terminal_cancel":
            f.queue.cancel_pending(
                f.errors.BridgeError("TIMEOUT", "cancel after static checkpoint CAS")
            )
        return result

    armed = [False]
    monkeypatch.setattr(module.profile, "snapshot", snapshot)
    admission = module.Admission(f.context, object(), f.scene, "render.configure", external=True)
    assert f.calls == []

    def interfere():
        f.provider_hook[0] = None
        if fault == "provider_source_drift":
            f.scene.protected = "new source from provider"
        elif fault == "checkpoint_manager":
            f.context.checkpoints = NS(_prefix=f.context.checkpoints._prefix)
        elif fault == "checkpoint_namespace":
            f.context.checkpoints._prefix = "BCB1:" + "c" * 32 + ":"
        elif fault == "external_permission":
            f.grants["ACCESS_EXTERNAL_FILES"] = False

    f.provider_hook[0] = interfere
    armed[0] = True
    expected = (
        "TIMEOUT"
        if fault == "terminal_cancel"
        else "PERMISSION_DENIED"
        if fault == "external_permission"
        else "OPERATION_FAILED"
    )
    with pytest.raises(f.errors.BridgeError) as caught:
        admission()
    assert caught.value.code == expected
    f.scene.protected = "original"
    f.grants["ACCESS_EXTERNAL_FILES"] = True
    with pytest.raises(f.errors.BridgeError) as repeated:
        admission()
    assert repeated.value is caught.value
    assert (f.owner.a, f.owner.b) == (0, 0)


def test_checkpoint_after_read_guard_never_calls_providers_and_latches_unexpected_failure(
    live_boundary, monkeypatch
):
    f = live_boundary
    module = importlib.import_module(f"{f.module.__package__}._render_checkpoint")
    f.context.checkpoints = NS(_prefix="BCB1:" + "a" * 32 + ":")
    monkeypatch.setattr(module.profile, "snapshot", lambda *_args, **_kwargs: ("static",))
    admission = module.Admission(f.context, object(), f.scene, "render.configure", external=False)

    def forbidden():
        raise AssertionError("provider called after checkpoint marker CAS")

    f.provider_hook[0] = forbidden
    admission.check_after_read()
    assert f.calls == []

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("native metadata is unavailable")

    monkeypatch.setattr(module.profile, "snapshot", unavailable)
    with pytest.raises(f.errors.BridgeError) as caught:
        admission.check_after_read()
    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["exception_type"] == "RuntimeError"
    with pytest.raises(f.errors.BridgeError) as repeated:
        admission()
    assert repeated.value is caught.value and f.calls == []


def test_approved_render_root_uses_native_raw_storage_never_runtime_getter(
    addon_package, monkeypatch, tmp_path
):
    module = importlib.import_module(f"{addon_package}.render_staging")
    preferences = importlib.import_module(f"{addon_package}.preferences")
    calls = []

    class NativePrefs(dict):
        def as_pointer(self):
            return id(self)

        @property
        def asset_directory(self):
            calls.append(True)
            raise AssertionError("runtime directory getter must not run after grants")

    descriptor = prop("asset_directory", "STRING", runtime=True, default="")
    descriptor.subtype = "DIR_PATH"
    rna = NS(properties=Props([descriptor]), as_pointer=lambda: 123)
    NativePrefs.bl_rna = rna
    owner = NativePrefs(asset_directory=str(tmp_path))
    monkeypatch.setattr(preferences, "BlenderCodexBridgePreferences", NativePrefs, raising=False)
    monkeypatch.setattr(module, "get_preferences", lambda: owner)
    monkeypatch.setattr(
        module, "require_blender", lambda: NS(types=NS(bpy_struct=NS(get=dict.get)))
    )
    first = module._read_root()
    assert first[0] == str(tmp_path) and calls == []
    del owner["asset_directory"]
    assert module._read_root()[0] == "" and calls == []
    owner["asset_directory"] = 17
    with pytest.raises(module.BridgeError, match="raw storage"):
        module._read_root()
    owner["asset_directory"] = str(tmp_path)
    descriptor.is_readonly = True
    with pytest.raises(module.BridgeError, match="reviewed bridge descriptor"):
        module._read_root()
    assert calls == []


@pytest.mark.parametrize("change", ["folder", "descriptor"])
def test_changed_approved_root_after_prior_reads_blocks_publication_and_cleanup(
    stage, monkeypatch, change
):
    f = stage
    original = f.resource.payload.read_bytes()
    changed = (
        (str(f.root.parent), ("reviewed_fixture",))
        if change == "folder"
        else (str(f.root), ("new_descriptor",))
    )
    monkeypatch.setattr(f.module, "_read_root", lambda: changed)
    with pytest.raises(f.module.BridgeError, match="Approved render path"):
        f.resource.publish()
    f.resource.cleanup()
    assert not f.resource.path.exists() and f.resource.payload.read_bytes() == original
    assert f.resource.evidence()["staging_cleanup"].startswith("retained_")


def test_checkpoint_mesh_array_identity_preserves_authored_values_and_structural_roles(
    addon_package,
):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")
    prefix = "BCB1:" + "a" * 32 + ":"

    class Native(dict):
        pointer = 101
        co = (1.0, 2.0, 3.0)

        def as_pointer(self):
            return self.pointer

    mesh, vertex = Native(), Native()
    mesh.pointer = 200
    mesh.bl_rna = NS(identifier="Mesh", properties=Props([]))
    descriptor = prop("co", "FLOAT")
    vertex.bl_rna = NS(identifier="MeshVertex", properties=Props([descriptor]))
    bpy = NS(
        app=NS(build_hash=b"62c1db4208e8"),
        types=NS(MeshVertex=NS(bl_rna=vertex.bl_rna)),
    )
    reader = module.Reader(bpy, None, checkpoint_prefix=prefix, checkpoint_static=False)
    before = reader.mesh_array(mesh, "vertices", 0, vertex)
    vertex.pointer = 999  # Native undo shares arrays; next RNA iteration detaches storage.
    assert reader.mesh_array(mesh, "vertices", 0, vertex) == before
    assert reader.mesh_array(mesh, "vertices", 1, vertex) != before
    mesh.pointer += 1
    assert reader.mesh_array(mesh, "vertices", 0, vertex) != before
    mesh.pointer -= 1
    vertex.co = (4.0, 2.0, 3.0)
    assert reader.mesh_array(mesh, "vertices", 0, vertex) != before
    vertex.co = (1.0, 2.0, 3.0)
    descriptor.as_pointer = lambda: 10003
    assert reader.mesh_array(mesh, "vertices", 0, vertex) != before
    with pytest.raises(module.BridgeError, match="measured native element role"):
        reader.mesh_array(mesh, "unreviewed_role", 0, vertex)
    bpy.app.build_hash = b"unmeasured"
    with pytest.raises(module.BridgeError, match="measured native element role"):
        reader.mesh_array(mesh, "vertices", 0, vertex)


def test_full_checkpoint_projection_never_omits_authored_scalars(addon_package):
    module = importlib.import_module(f"{addon_package}.render_scope_profile")

    class Native(dict):
        authored = 1.0

        def as_pointer(self):
            return id(self)

    scene = Native()
    scene.bl_rna = NS(identifier="Scene", properties=Props([prop("authored", "FLOAT")]))
    bpy = NS(types=NS(Scene=NS(bl_rna=scene.bl_rna)))
    reader = module.Reader(
        bpy, scene, checkpoint_prefix="BCB1:" + "a" * 32 + ":", checkpoint_static=False
    )
    original = reader.primitive(scene)
    scene["_codex_bridge_undo_marker"] = "BCB1:" + "a" * 32 + ":" + "b" * 32
    assert reader.primitive(scene) == original
    scene.authored = 2.0
    assert reader.primitive(scene) != original


@pytest.mark.parametrize("stage", ["entry_provider", "before_checkpoint", "after_handler"])
@pytest.mark.parametrize("target", ["owned", "protected"])
def test_reused_authored_ledger_rejects_manual_drift_through_final_checkpoint(
    live_boundary, stage, target
):
    f = live_boundary
    module = importlib.import_module(f"{f.module.__package__}._render_checkpoint")
    f.context.checkpoints = NS(_prefix="BCB1:" + "a" * 32 + ":")
    boundary = f.module.Boundary(
        f.context,
        object(),
        f.scene,
        "render.configure",
        [(f.owner, "a", 10), (f.owner, "b", 20)],
        checkpoint_prefix=f.context.checkpoints._prefix,
        initial_check=False,
    )
    admission = module.Admission(
        f.context,
        object(),
        f.scene,
        "render.configure",
        external=False,
        boundary=boundary,
    )
    assert f.calls == []

    def manual_change():
        if target == "owned":
            f.owner.a = 999
        else:
            f.scene.protected = "new manual source"
        f.provider_hook[0] = None

    if stage == "entry_provider":
        f.provider_hook[0] = manual_change
        with pytest.raises(f.errors.BridgeError):
            admission()
    else:
        admission()
        if stage == "after_handler":
            boundary.apply()
            assert boundary.expected == {
                (f.owner.as_pointer(), "a"): 10,
                (f.owner.as_pointer(), "b"): 20,
            }
        manual_change()
        calls = len(f.calls)
        with pytest.raises(f.errors.BridgeError) as caught:
            admission.check_after_read()
        assert len(f.calls) == calls
        with pytest.raises(f.errors.BridgeError) as repeated:
            admission()
        assert repeated.value is caught.value
    assert f.owner.a == (999 if target == "owned" else 10 if stage == "after_handler" else 0)
