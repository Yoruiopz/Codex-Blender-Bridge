"""Portable control-flow models; these do not qualify Blender RNA behavior."""
from __future__ import annotations

import importlib
import sys
from types import FunctionType
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


@pytest.fixture
def origin_model(mod, monkeypatch):
    runtime = mod._runtime.BridgeRuntime()
    monkeypatch.setattr(mod._runtime, "_RUNTIME", runtime)
    reader = mod.Reader.__new__(mod.Reader)
    reader.context = runtime.executor.context
    monkeypatch.setattr(mod, "require_blender", lambda: pytest.fail("Poisoned graph reached Blender"))
    return NS(runtime=runtime, reader=reader, mod=mod, calls=[])


def test_permission_dependency_proof_executes_no_provider_or_grant_helpers(origin_model):
    env, calls = origin_model, []
    functions = (env.mod._PERMISSIONS, env.mod._PREFERENCES,
                 env.mod._runtime.native_save_permission_provider_intact,
                 env.mod._permission_module.permission_snapshot,
                 env.mod._GRANT_CLASS.active, env.mod._GENERATION.fget)
    watched = {function.__code__ for function in functions}
    def profile(frame, event, _arg):
        if event == "call" and frame.f_code in watched:
            calls.append(frame.f_code.co_name)
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        origin = env.reader._ordinary_origin()
    finally:
        sys.setprofile(previous)
    assert calls == [] and type(origin[2]) is env.mod._runtime.NativeSaveJobs
    assert origin[17] is env.runtime.native_save_policy


@pytest.mark.parametrize("change", [
    "wrapper", "base", "proof", "helper", "helper_code", "helper_globals", "wrapper_code",
    "wrapper_defaults", "helper_keywords", "statement_closure", "generation_property",
    "grant_class", "statement_class", "retained_base", "retained_proof", "retained_helpers",
    "preference_map", "enum_member", "policy_version", "math", "time", "threading",
    "global_shadow", "jobs_export", "grant_getattribute",
])
def test_changed_permission_dependency_graph_refuses_before_any_callback(origin_model, monkeypatch, change):
    env, mod = origin_model, origin_model.mod
    def poison(*_args, **_kwargs):
        env.calls.append(change)
        raise AssertionError("An unqualified dependency was executed")
    runtime, policy = mod._runtime, mod._POLICY_MODULE
    if change in {"wrapper", "base", "proof"}:
        name = {"wrapper": "permission_snapshot", "base": "_base_permission_snapshot",
                "proof": "native_save_permission_provider_intact"}[change]
        monkeypatch.setattr(runtime, name, poison)
    elif change == "helper":
        monkeypatch.setattr(mod._GRANT_CLASS, "active", poison)
    elif change in {"helper_code", "wrapper_code"}:
        function = mod._GRANT_CLASS.active if change == "helper_code" else mod._PERMISSIONS
        def body(*_args, **_kwargs):
            raise AssertionError("An altered code object was executed")
        monkeypatch.setattr(function, "__code__", body.__code__)
    elif change == "helper_globals":
        function = mod._GRANT_CLASS.active
        monkeypatch.setattr(mod._GRANT_CLASS, "active", FunctionType(function.__code__, {"type": poison}))
    elif change == "wrapper_defaults":
        monkeypatch.setattr(mod._PERMISSIONS, "__defaults__", (poison,))
    elif change == "helper_keywords":
        monkeypatch.setitem(mod._GRANT_CLASS.active.__kwdefaults__, "now", poison)
    elif change == "statement_closure":
        monkeypatch.setattr(mod._STATEMENT_CLASS.__init__.__closure__[0], "cell_contents", poison)
    elif change == "generation_property":
        monkeypatch.setattr(mod._GRANT_CLASS, "generation", property(poison))
    elif change in {"grant_class", "statement_class"}:
        name = "NativeSaveGrant" if change == "grant_class" else "GrantStatement"
        monkeypatch.setattr(runtime, name, type("PoisonedGrantClass", (), {"active": poison}))
    elif change in {"retained_base", "retained_proof", "retained_helpers"}:
        name = {"retained_base": "_BASE_PERMISSION_SNAPSHOT", "retained_proof": "_PERMISSION_PROVIDER_GUARD",
                "retained_helpers": "_GRANT_HELPERS"}[change]
        monkeypatch.setattr(runtime, name, poison)
    elif change == "preference_map":
        monkeypatch.setitem(mod._PREFERENCE_MAP, mod._PERMISSION_CLASS.EDIT_ANIMATION, poison)
    elif change == "enum_member":
        monkeypatch.setitem(vars(mod._PERMISSION_CLASS.EDIT_ANIMATION), "_value_", poison)
    elif change == "policy_version":
        monkeypatch.setattr(policy, "POLICY_VERSION", "unreviewed")
    elif change in {"math", "time", "threading"}:
        monkeypatch.setattr(policy, change, NS(isfinite=poison, monotonic=poison, current_thread=poison))
    elif change == "global_shadow":
        monkeypatch.setitem(vars(runtime), "all", poison)
    elif change == "jobs_export":
        monkeypatch.setattr(runtime, "NativeSaveJobs", type("UnqualifiedJobs", (), {}))
    else:
        monkeypatch.setattr(mod._GRANT_CLASS, "__getattribute__", poison)
    with pytest.raises(mod.BridgeError, match="dependency graph"):
        env.reader._ordinary_origin()
    assert env.calls == []


@pytest.mark.parametrize("field", ["authority", "generation", "origin", "job_grant", "thread"])
def test_changed_grant_owner_refuses_before_native_getters(origin_model, field):
    env, grant = origin_model, origin_model.runtime.native_save_policy
    if field == "authority":
        object.__setattr__(grant, "_authority", object())
    elif field == "generation":
        object.__setattr__(grant, "_generation", "different-session")
    elif field == "origin":
        env.runtime._native_save_policy_origin = object()
    elif field == "job_grant":
        env.runtime.jobs.native_save_policy = object()
    else:
        object.__setattr__(grant, "_thread", -1)
    with pytest.raises(env.mod.BridgeError, match="grant"):
        env.reader._ordinary_origin()


def test_native_grant_changes_only_native_flag_and_not_ordinary_origin(origin_model):
    env, mod = origin_model, origin_model.mod
    env.runtime._registered = True
    grant, authority = env.runtime.native_save_policy, env.runtime._native_save_local_authority
    prefs = NS(allow_edit_animation=True, allow_edit_mesh=True)
    before = env.reader._ordinary_origin()
    ordinary = mod._permission_module.permission_snapshot(prefs)
    def check(expected_native):
        result = mod._runtime.permission_snapshot(prefs)
        assert result.pop("NATIVE_SAVE_EFFECTS") is expected_native
        assert result == {key: value for key, value in ordinary.items() if key != "NATIVE_SAVE_EFFECTS"}
        now = env.reader._ordinary_origin()
        assert len(now) == len(before) and all(a is b for a, b in zip(now, before, strict=True))
    check(False)
    grant.arm(authority, 60)
    check(True)
    grant.revoke()
    check(False)
    grant.arm(authority, 1, now=0.)
    check(False)


@pytest.mark.parametrize("name", ["bool", "all", "type", "any", "vars", "len", "__import__"])
def test_resolved_builtin_poison_is_refused_without_calling_it(origin_model, name):
    env, calls = origin_model, []
    builtins = env.mod._PERMISSIONS.__builtins__
    original = builtins[name]
    def poison(*_args, **_kwargs):
        calls.append(name)
        raise AssertionError("An altered provider builtin was executed")
    captured = None
    try:
        builtins[name] = poison
        try:
            env.reader._ordinary_origin()
        except env.mod.BridgeError as error:
            captured = error
    finally:
        builtins[name] = original
    assert captured is not None and "dependency" in captured.message and calls == []


@pytest.mark.parametrize("target", ["inherited_active", "enum_value", "enum_iterator", "enum_fget", "enum_get_code",
                                    "enum_metaclass"])
def test_changed_inherited_descriptor_is_refused_without_getter_callback(origin_model, monkeypatch, target):
    env, mod = origin_model, origin_model.mod
    def poison(*_args, **_kwargs):
        env.calls.append(target)
        raise AssertionError("An altered inherited descriptor was executed")
    if target == "inherited_active":
        monkeypatch.setattr(mod._JOBS_MRO[2], "active", property(poison), raising=False)
    elif target == "enum_value":
        original = vars(mod.Enum)["value"]
        try:
            mod.Enum.value = property(poison)
            with pytest.raises(mod.BridgeError, match="dependency graph"):
                env.reader._ordinary_origin()
        finally:
            mod.Enum.value = original
        assert env.calls == []
        return
    elif target == "enum_fget":
        monkeypatch.setitem(vars(mod._ENUM_VALUE), "fget", poison)
    elif target == "enum_get_code":
        def body(*_args, **_kwargs):
            raise AssertionError("An altered enum descriptor body was executed")
        monkeypatch.setattr(vars(type(mod._ENUM_VALUE))["__get__"], "__code__", body.__code__)
    elif target == "enum_metaclass":
        original = vars(mod._ENUM_META).get("__getattribute__")
        captured = None
        try:
            mod._ENUM_META.__getattribute__ = poison
            try:
                env.reader._ordinary_origin()
            except mod.BridgeError as error:
                captured = error
        finally:
            if original is None:
                del mod._ENUM_META.__getattribute__
            else:
                mod._ENUM_META.__getattribute__ = original
        assert captured is not None and env.calls == []
        return
    else:
        monkeypatch.setattr(mod._ENUM_META, "__iter__", poison)
    with pytest.raises(mod.BridgeError, match="dependency graph"):
        env.reader._ordinary_origin()
    assert env.calls == []


@pytest.mark.parametrize("name", ["_permission_dependencies", "_function_intact", "_same_items", "_class_items",
                                  "_grant_origin", "refused"])
@pytest.mark.parametrize("change", ["replacement", "code"])
def test_local_proof_helpers_are_authenticated_before_first_call(origin_model, monkeypatch, name, change):
    env, mod = origin_model, origin_model.mod
    def poison(*_args, **_kwargs):
        env.calls.append(name)
        return True
    if change == "replacement":
        monkeypatch.setattr(mod, name, poison)
    else:
        def body(*_args, **_kwargs):
            raise AssertionError("An altered local proof body was executed")
        monkeypatch.setattr(getattr(mod, name), "__code__", body.__code__)
    with pytest.raises(mod.BridgeError, match="local point dependency proof"):
        env.reader._ordinary_origin()
    assert env.calls == []


@pytest.mark.parametrize("target", ["_LOCAL_BUILTINS", "_LOCAL_HELPER_PINS", "_LOCAL_NAMESPACE", "row", "pin"])
def test_local_proof_root_shapes_refuse_before_container_callbacks(origin_model, monkeypatch, target):
    env, calls = origin_model, []
    class ForeignContainer:
        def __iter__(self):
            calls.append("iter")
            raise AssertionError("A foreign proof root was iterated")

        def __getitem__(self, _key):
            calls.append("item")
            raise AssertionError("A foreign proof root was indexed")

        def get(self, *_args):
            calls.append("get")
            raise AssertionError("A foreign proof namespace was read")

    foreign = ForeignContainer()
    if target == "row":
        monkeypatch.setattr(env.mod, "_LOCAL_HELPER_PINS", (foreign, *env.mod._LOCAL_HELPER_PINS[1:]))
    elif target == "pin":
        name, _pin = env.mod._LOCAL_HELPER_PINS[0]
        monkeypatch.setattr(env.mod, "_LOCAL_HELPER_PINS", ((name, foreign), *env.mod._LOCAL_HELPER_PINS[1:]))
    else:
        monkeypatch.setattr(env.mod, target, foreign)
    with pytest.raises(env.mod.BridgeError, match="local point dependency"):
        env.reader._ordinary_origin()
    assert calls == []


def test_local_proof_rejects_foreign_native_namespace_before_lookup(origin_model, monkeypatch):
    env = origin_model
    monkeypatch.setattr(env.mod, "_LOCAL_NAMESPACE", dict(vars(env.mod)))
    with pytest.raises(env.mod.BridgeError, match="local point dependency pin contents"):
        env.reader._ordinary_origin()


def test_permission_graph_is_rechecked_at_existing_perwrite_origin_fence(origin_model, monkeypatch):
    env, mod = origin_model, origin_model.mod
    reader = env.reader
    reader.origin, reader._hooks = reader._ordinary_origin(), reader.hooks()
    store = mod.get_task_plans(reader.context.state)
    reader.plan_origin = (store, store.plan, store.baseline, store.protection,
                          store.protection_generation, store.evidence_epoch)
    registry_module = importlib.import_module(mod._runtime.__package__ + ".tool_registry")
    reader.plan_semantic = registry_module._checkpoint_parameters((store.plan, store.scope,
        store.baseline, store.protection, store.protection_generation, store.evidence_epoch))
    reader.check_origin()
    def poison(*_args, **_kwargs):
        env.calls.append("late dependency")
        raise AssertionError("A late dependency callback was executed")
    monkeypatch.setattr(mod._runtime, "_PERMISSION_PROVIDER_GUARD", poison)
    with pytest.raises(mod.BridgeError, match="dependency graph"):
        reader.check_origin()
    assert env.calls == []


@pytest.mark.parametrize("attribute", ["__defaults__", "__kwdefaults__", "__globals__", "__closure__"])
def test_provider_metadata_remains_closed(origin_model, monkeypatch, attribute):
    env, source = origin_model, origin_model.runtime.permissions._source
    if attribute == "__globals__":
        env.runtime.permissions._source = FunctionType(source.__code__, {})
    elif attribute == "__closure__":
        captured = object()
        def replacement():
            return captured
        env.runtime.permissions._source = replacement
    else:
        monkeypatch.setattr(source, attribute, (object(),) if attribute == "__defaults__" else {"extra": object()})
    with pytest.raises(env.mod.BridgeError, match="Unreviewed point permission providers"):
        env.reader._ordinary_origin()


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
