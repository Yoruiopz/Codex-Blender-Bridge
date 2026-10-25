"""Portable control-flow models; these do not qualify Blender RNA behavior."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def mod(addon_package):
    return importlib.import_module(f"{addon_package}.tools._curve_point_native")


def test_unknown_runtime_refuses_before_blender_acquisition(mod, monkeypatch):
    monkeypatch.setattr(mod, "require_blender", lambda: pytest.fail("Unknown call reached native acquisition"))
    with pytest.raises(mod.BridgeError, match="canonical ordinary"):
        mod.Reader(NS(), {"object_name": "Actor"})


def test_canonical_runtime_direct_origin_is_admitted_without_blender_getters(mod, monkeypatch):
    runtime = mod._runtime.BridgeRuntime()
    monkeypatch.setattr(mod._runtime, "_RUNTIME", runtime)
    reader = mod.Reader.__new__(mod.Reader)
    reader.context = runtime.executor.context
    origin = reader._ordinary_origin()
    assert origin[0] is runtime and origin[5] is runtime.permissions
    runtime.permissions._source = lambda: pytest.fail("Unknown provider was invoked")
    with pytest.raises(mod.BridgeError, match="Unreviewed point permission providers"):
        reader._ordinary_origin()


def test_canonical_executor_queued_origin_retains_request_hooks(mod, monkeypatch):
    queue = importlib.import_module(mod.__package__.rsplit(".", 1)[0] + ".command_queue")
    protocol = importlib.import_module(mod.__package__.rsplit(".", 1)[0] + ".protocol")
    runtime = mod._runtime.BridgeRuntime()
    monkeypatch.setattr(mod._runtime, "_RUNTIME", runtime)
    retained = []
    def handler(context, _params):
        reader = mod.Reader.__new__(mod.Reader)
        reader.context = context
        retained.append(reader._ordinary_origin())
        return {"canonical_origin": True}
    runtime.registry.register("point.origin", handler, description="Portable origin model")
    request = protocol.Request(id="point_origin", method="point.origin", params={})
    queued = queue.QueuedRequest(request)
    assert queued.try_start()
    response = runtime.executor.execute_request(request, check_cancelled=queued.check_active)
    assert response.ok, response.error
    assert response.result == {"canonical_origin": True}
    assert retained[0][14].__self__ is queued and retained[0][15].__closure__[0].cell_contents is queued


@pytest.mark.parametrize("service", ["state", "registry", "checkpoints", "jobs", "snapshot"])
def test_replaced_services_or_final_snapshot_refuse_before_native_getters(mod, monkeypatch, service):
    runtime = mod._runtime.BridgeRuntime()
    monkeypatch.setattr(mod._runtime, "_RUNTIME", runtime)
    if service == "snapshot":
        monkeypatch.setattr(runtime.state, "snapshot", lambda: pytest.fail("Unknown final snapshot invoked"))
    else:
        fake = NS()
        setattr(runtime, service, fake)
        setattr(runtime.executor, service, fake)
    reader = mod.Reader.__new__(mod.Reader)
    reader.context = runtime.executor.context
    with pytest.raises(mod.BridgeError, match="canonical ordinary"):
        reader._ordinary_origin()


def test_native_slot_discovery_has_no_python_setattr_fallback(mod):
    class Point:
        pass
    bpy = NS(types=NS(FCurve=Point, Keyframe=Point))
    with pytest.raises(mod.BridgeError, match="genuine shared native RNA slot"):
        mod.native_slots(bpy)


@pytest.mark.parametrize("fail", [False, True])
def test_leaf_one_literal_native_call_and_explicit_release(mod, fail):
    owner, pair, calls = object(), (1., -0.), []
    def native_setter(actual, field, value):
        calls.append((actual, field, value))
        if fail:
            raise RuntimeError("modeled native failure")
    leaf = mod.Leaf(owner, native_setter, "co", pair)
    try:
        if fail:
            with pytest.raises(RuntimeError):
                leaf()
        else:
            leaf()
    finally:
        leaf.clear()
    assert len(calls) == 1 and calls[0][0] is owner and calls[0][2] is pair
    assert leaf.owner is None and leaf.setter is None


@pytest.mark.parametrize("address,uid", [(0, 1), (1, 0), (True, 1), (1, True), (-1, 2)])
def test_owner_identity_requires_native_positive_exact_integers(mod, address, uid):
    with pytest.raises(mod.BridgeError):
        mod.identity(NS(as_pointer=lambda: address, session_uid=uid))


def test_schema_requires_exact_class_and_declared_array_length(mod):
    prop = NS(type="FLOAT", is_runtime=False, is_registered=False, array_length=2)
    rna = NS(identifier="Keyframe", properties={"co": prop})
    class Keyframe:
        bl_rna = rna
    reader = mod.Reader.__new__(mod.Reader)
    reader.bpy = NS(types=NS(Keyframe=Keyframe))
    reader.schema(Keyframe(), {"co": ("FLOAT", 2)})
    prop.array_length = 3
    with pytest.raises(mod.BridgeError, match="descriptor changed"):
        reader.schema(Keyframe(), {"co": ("FLOAT", 2)})
    class Wrapped(Keyframe):
        pass
    with pytest.raises(mod.BridgeError, match="canonical native"):
        reader.schema(Wrapped(), {"co": ("FLOAT", 2)})


def test_literal_selected_resolution_never_acquires_context(mod, monkeypatch):
    animation = importlib.import_module(mod.__package__ + ".animation_curves")
    first, second = NS(co=(1., 0.), as_pointer=lambda: 301), NS(co=(11., 10.), as_pointer=lambda: 302)
    curve = NS(data_path="location", array_index=0, keyframe_points=[first, second], as_pointer=lambda: 300)
    action = NS(is_action_layered=False, fcurves=[curve])
    obj = NS(animation_data=NS(action=action), name="Actor")
    reader = mod.Reader.__new__(mod.Reader)
    reader.name, reader.params = "Actor", {"data_path": "location", "keyframes": [{"frame": 11, "co": [11, 12]}]}
    reader.bpy = NS(data=NS(objects=NS(get=lambda name: obj if name == "Actor" else None)))
    monkeypatch.setattr(animation, "_prepare_curve_edit", lambda *_: pytest.fail("Legacy resolver acquired"))
    result = reader.selected()
    assert result["curve"] is curve and result["prepared"] == ((11., {"co": (11., 12.)}),)


@pytest.mark.parametrize("drift", ["preservation", "content"])
def test_final_leaf_cas_refuses_before_retaining_point_or_setting(mod, monkeypatch, drift):
    reader = mod.Reader.__new__(mod.Reader)
    curve = NS(as_pointer=lambda: 300)
    reader.resolve = lambda: (None, None, curve)
    reader.preservation = lambda _: ("changed" if drift == "preservation" else "before",)
    reader.selected = lambda: {"action": object(), "curve": curve}
    reader.action_content = lambda _: ("changed" if drift == "content" else "before",)
    reader.schema = lambda *_: pytest.fail("Refused prefix retained a point")
    monkeypatch.setattr(mod, "native_slots", lambda _: pytest.fail("Refused prefix reached native setter slots"))
    with pytest.raises(mod.BridgeError):
        reader.leaf(curve, "co", 11., (11., 12.), expected=("before",), preservation=("before",), roles=None)


@pytest.mark.parametrize("value", [[11., 12.], (11., True), (11., float("inf")), (11.,), (11., 12., 13.)])
def test_native_leaf_refuses_nonliteral_arguments_before_resolve(mod, value):
    reader = mod.Reader.__new__(mod.Reader)
    reader.resolve = lambda: pytest.fail("Invalid argument reached native ownership")
    with pytest.raises(mod.BridgeError):
        reader.leaf(None, "co", 11., value, expected=(), preservation=(), roles=None)


def test_preservation_projection_contains_only_independent_immutable_facts(mod, monkeypatch):
    animation = importlib.import_module(mod.__package__ + ".animation_curves")
    obj = NS(name="Actor", as_pointer=lambda: 1001, session_uid=101)
    action = NS(name="Action")
    reader = mod.Reader.__new__(mod.Reader)
    reader.bpy = NS(data=NS(actions=[action]))
    reader.check_origin = lambda: None
    reader.resolve = lambda: (obj, action, None)
    reader.literal = lambda: ("literal",)
    reader.target_consumers = lambda _: ("consumers",)
    monkeypatch.setattr(mod.scope, "binding", lambda _: ("binding",))
    monkeypatch.setattr(mod.scope, "animation_context", lambda _: ("animation",))
    monkeypatch.setattr(animation, "_curve_structure", lambda _: ("structure",))
    users = {"users": 1, "fake_user": False, "references": ((1001, 101, "Actor", "Object", 1, True),),
             "real_users": 1, "direct_users_complete": True}
    monkeypatch.setattr(mod.scope, "action_users", lambda *_: users)
    facts = reader.preservation(NS(authored=lambda: ("roles",)))
    assert mod.intent.same(facts, facts)
    assert facts[3] == (1, False, users["references"], 1, True)


def test_final_leaf_acquires_point_only_after_full_prefix_comparison(mod, monkeypatch):
    events = []
    class Point:
        bl_rna = NS(properties={"co": NS(is_readonly=False, hard_min=-1e6, hard_max=1e6)})
        as_pointer = staticmethod(lambda: 301)
        @property
        def co(self):
            events.append("point_co")
            return (11., 10.)
    owner = Point()
    curve = NS(as_pointer=lambda: 300, keyframe_points=[owner])
    reader = mod.Reader.__new__(mod.Reader)
    reader.bpy = object()
    reader.resolve = lambda: (events.append("resolve"), None, curve)
    reader.preservation = lambda _: (events.append("preservation") or "before",)
    reader.selected = lambda: events.append("selected") or {"action": object(), "curve": curve}
    reader.action_content = lambda _: (events.append("action_content") or "before",)
    reader.schema = lambda *_: events.append("schema")
    def setter(actual, field, pair):
        events.append(("setter", actual, field, pair))
    reader._slots = (object(), setter)
    monkeypatch.setattr(mod, "native_slots", lambda _: events.append("slots") or reader._slots)
    leaf = reader.leaf(curve, "co", 11., (11., 12.), expected=("before",), preservation=("before",), roles=None)
    assert events == ["resolve", "preservation", "selected", "action_content", "point_co", "schema", "slots"]
    try:
        leaf()
    finally:
        leaf.clear()
    assert events[-1] == ("setter", owner, "co", (11., 12.))
    assert leaf.owner is None and leaf.setter is None


@pytest.mark.parametrize("extra", [
    {"object_name": "\ud800"}, {"slot_identifier": "\ud800"}, {"slot_identifier": 2},
    {"index": True}, {"keyframes": [{"frame": True, "co": [11., 12.]}]},
    {"keyframes": [{"frame": 11., "co": [11., True]}]}, {1: "untyped parameter"},
])
def test_point_request_refuses_untyped_or_invalid_text_before_native_acquisition(mod, extra):
    animation = importlib.import_module(mod.__package__ + ".animation_curves")
    params = {"object_name": "Actor", "data_path": "location", "keyframes": [{"frame": 11., "co": [11., 12.]}], **extra}
    with pytest.raises(mod.BridgeError) as caught:
        animation._point_request(params)
    assert caught.value.code == "INVALID_ARGUMENT"
