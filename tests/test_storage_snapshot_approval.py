"""Local-approval countermodels, not acceptance of native preference RNA.

Substitution happens before source capture. Official registered-class and
native-collection getter qualification is a separate isolated-runner gate.
"""
from __future__ import annotations

import importlib
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def approval(addon_package, monkeypatch):
    module = importlib.import_module(addon_package + ".storage_snapshot_approval")
    runtime = module.runtime.BridgeRuntime()
    runtime.state.set_paused(False)
    runtime.state.set_emergency_stopped(False)
    runtime._registered = True
    monkeypatch.setattr(module.runtime, "_RUNTIME", runtime)
    fields = {name: True for name in (
        "allow_inspect_scene", "allow_save_project", "allow_external_files")}
    prefs = SimpleNamespace(**fields)
    def provider_preferences():
        calls.append("provider")
        if hooks[0] is not None:
            hooks[0]()
        return prefs
    monkeypatch.setattr(module.runtime, "_preferences", provider_preferences)
    monkeypatch.setattr(module.runtime, "_PREFERENCES_FUNCTION", provider_preferences)
    monkeypatch.setattr(module.runtime, "_PREFERENCES_CODE", provider_preferences.__code__)
    bpy = ModuleType("bpy")
    bpy.types = ModuleType("bpy.types")
    monkeypatch.setattr(module.runtime, "bpy", bpy)
    monkeypatch.setattr(module.preferences, "bpy", bpy)
    monkeypatch.setattr(module.graph, "_deferred_type", lambda _bpy: None)
    marker = object()
    def declaration(_bpy):
        return marker
    def unchanged(_bpy, actual):
        assert actual is marker
    monkeypatch.setattr(module, "_declaration", declaration)
    monkeypatch.setattr(module, "_declaration_unchanged", unchanged)
    calls, hooks, root, changed_route = [], [None], ["/approved/project"], [False]
    def native_get(_owner, field):
        assert field == "project_directory"
        calls.append("root_getter")
        return root[0]
    route = (*tuple(object() for _ in range(10)), 21, 22, native_get)
    def route_model(_bpy, _declaration):
        calls.append("route")
        return (*route[:6], object(), *route[7:]) if changed_route[0] else route
    monkeypatch.setattr(module, "_route", route_model)
    runtime.registry.register("fixture.root_approval", lambda *_: None,
        modifies=True, permissions=module.REQUIRED)
    context = runtime.executor.context
    context.checkpoint_method = "fixture.root_approval"
    return SimpleNamespace(module=module, runtime=runtime, context=context, calls=calls,
        hooks=hooks, root=root, changed_route=changed_route, prefs=prefs, route=route)


def test_authorize_then_separate_value_reads_keep_providers_separate(approval):
    env = approval
    value = env.module.LocalRootApproval.capture(env.context)
    assert env.calls == ["route"]
    value = value.authorize()
    assert value.approved_root == "/approved/project"
    assert env.calls == ["route", "provider", "route", "root_getter"]
    env.calls.clear()
    value.check_source()
    assert env.calls == []
    assert value.read_current() == "/approved/project"
    assert env.calls == ["route", "root_getter"]


def test_read_before_first_provider_never_reaches_route_or_root(approval):
    env = approval
    value = env.module.LocalRootApproval.capture(env.context)
    env.calls.clear()
    with pytest.raises(env.module.BridgeError, match="approval") as failure:
        value.read_current()
    assert failure.value.context["reason"] == "ROOT_APPROVAL_INITIAL_PERMISSION_REQUIRED"
    assert env.calls == []


@pytest.mark.parametrize("name", ["allow_inspect_scene", "allow_save_project", "allow_external_files"])
def test_denial_has_no_postprovider_route_or_root_read(approval, name):
    env = approval
    value = env.module.LocalRootApproval.capture(env.context)
    setattr(env.prefs, name, False)
    env.calls.clear()
    with pytest.raises(env.module.BridgeError) as failure:
        value.authorize()
    assert failure.value.code == env.module.ErrorCode.PERMISSION_DENIED
    assert env.calls == ["provider"]


@pytest.mark.parametrize("flag", ["paused", "emergency_stopped"])
def test_stop_after_provider_precedes_every_native_getter(approval, flag):
    env = approval
    value = env.module.LocalRootApproval.capture(env.context)
    env.hooks[0] = lambda: setattr(env.context.state, flag, True)
    env.calls.clear()
    with pytest.raises(env.module.BridgeError) as failure:
        value.authorize()
    assert failure.value.code in (env.module.ErrorCode.AGENT_PAUSED, env.module.ErrorCode.EMERGENCY_STOPPED)
    assert env.calls == ["provider"]


@pytest.mark.parametrize("target", ["service", "alias", "executor", "context", "provider", "getter"])
def test_provider_drift_refuses_before_native_route(approval, monkeypatch, target):
    env = approval
    value = env.module.LocalRootApproval.capture(env.context)
    def drift():
        if target == "service":
            env.runtime.storage_snapshots = object()
        elif target == "alias":
            env.runtime._storage_snapshot_origin = object()
        elif target == "executor":
            env.runtime.executor.storage_snapshots = object()
        elif target == "context":
            env.context.storage_snapshots = object()
        elif target == "provider":
            env.runtime.permissions._source = lambda: {}
        else:
            monkeypatch.setattr(env.module.preferences, "get_preferences", lambda: None)
    env.hooks[0] = drift
    env.calls.clear()
    with pytest.raises(env.module.BridgeError):
        value.authorize()
    assert env.calls == ["provider"]


def test_changed_approval_after_provider_cannot_be_adopted(approval):
    env = approval
    value = env.module.LocalRootApproval.capture(env.context)
    value = value.authorize()
    assert value.approved_root == env.root[0]
    env.hooks[0] = lambda: env.root.__setitem__(0, "/other/project")
    with pytest.raises(env.module.BridgeError) as failure:
        value.authorize()
    assert failure.value.context["reason"] == "ROOT_APPROVAL_VALUE_CHANGED"
    assert tuple.__getitem__(value, 7) == "/approved/project"


def test_changed_native_route_refuses_before_root_getter(approval):
    env = approval
    value = env.module.LocalRootApproval.capture(env.context)
    value = value.authorize()
    env.changed_route[0] = True
    env.calls.clear()
    with pytest.raises(env.module.BridgeError) as failure:
        value.read_current()
    assert failure.value.context["reason"] == "ROOT_APPROVAL_NATIVE_ROUTE_CHANGED"
    assert env.calls == ["route"]


def test_approval_cannot_escape_its_original_call_activation(approval):
    env = approval
    def capture():
        return env.module.LocalRootApproval.capture(env.context)
    value = capture()
    env.calls.clear()
    with pytest.raises(env.module.BridgeError):
        value.authorize()
    assert env.calls == []


@pytest.mark.parametrize("raw", [None, 1, "", "/", "relative", "//host/path", "/a/../b", "/a/./b", "/a/", "/a//b", "/a\\b", "/a\x00b", "/a\x7fb", "/a\ud800b"])
def test_approval_path_shape_never_normalizes_or_adopts(raw, approval):
    with pytest.raises(approval.module.BridgeError):
        approval.module._root(raw)


def test_native_route_identity_comparison_never_calls_foreign_equality(approval):
    class Foreign:
        def __eq__(self, _other):
            pytest.fail("foreign equality")
    assert not approval.module._same_route((Foreign(),), (1,))
    assert not approval.module._same_route((1,), (Foreign(),))
    assert not approval.module._same_route((True,), (1,))


def test_module_and_existing_registered_tools_unchanged(approval):
    assert approval.module.__name__.endswith("storage_snapshot_approval")
    assert not any("cache_storage" in row["name"] for row in approval.context.registry.describe()["tools"])


@pytest.mark.parametrize("target", ["route", "getter", "verifier"])
def test_successful_control_boundary_requires_fresh_source_before_getter(approval, monkeypatch, target):
    import sys
    env = approval
    module = env.module
    value = module.LocalRootApproval.capture(env.context).authorize()
    env.calls.clear()
    code = type(env.context.state).snapshot.__code__
    fired = []
    def profile(frame, event, _argument):
        if event == "return" and frame.f_code is code and not fired:
            fired.append(True)
            if target == "route":
                monkeypatch.setattr(module, "_route", lambda *_: pytest.fail("changed route called"))
            elif target == "getter":
                monkeypatch.setattr(module.preferences, "get_preferences", lambda: pytest.fail("changed getter called"))
            else:
                monkeypatch.setattr(module.LocalRootApproval, "check_source", lambda *_: pytest.fail("changed verifier called"))
    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        with pytest.raises(module.BridgeError):
            value.read_current()
    finally:
        sys.setprofile(previous)
    assert fired == [True] and env.calls == []


def test_settled_approval_and_initial_grant_are_immutable(approval):
    env = approval
    pending = env.module.LocalRootApproval.capture(env.context)
    value = pending.authorize()
    assert pending is not value and tuple.__getitem__(pending, 7) is None
    assert tuple.__getitem__(value, 7) == "/approved/project"
    with pytest.raises(TypeError):
        value[7] = "/other/project"
    with pytest.raises(TypeError):
        pending[7] = "/other/project"
    env.calls.clear()
    with pytest.raises(env.module.BridgeError):
        pending.read_current()
    assert env.calls == []


def test_unknown_context_is_rejected_without_attribute_callbacks(addon_package):
    module = importlib.import_module(addon_package + ".storage_snapshot_approval")
    class Foreign:
        def __getattribute__(self, _name):
            pytest.fail("foreign context read")
    with pytest.raises(module.BridgeError):
        module.LocalRootApproval.capture(Foreign())


@pytest.mark.parametrize("callback", [None, "get", "set", "update", "foreign_key", "foreign_value",
    "missing_attr", "wrong_attr", "foreign_attr", "extra_key"])
def test_registered_declaration_allows_only_original_callback_free_keywords(addon_package, monkeypatch, callback):
    import os
    module = importlib.import_module(addon_package + ".storage_snapshot_approval")
    class Marker:
        __slots__ = ("function", "keywords")
    class Prefs:
        pass
    marker = Marker()
    marker.function, marker.keywords = os.getcwd, dict(module._DECLARATION)
    Prefs.__annotations__ = {"project_directory": marker}
    props, bpy = ModuleType("owned.props"), ModuleType("owned.bpy")
    props.StringProperty, props._PropertyDeferred, bpy.props = os.getcwd, Marker, props
    origins = (bpy, props, Marker, (), None, (Marker.function, Marker.keywords))
    monkeypatch.setattr(module.graph, "_deferred_type", lambda _bpy: (Marker, origins))
    monkeypatch.setattr(module.preferences, "BlenderCodexBridgePreferences", Prefs)
    if callback in {"get", "set", "update"}:
        marker.keywords[callback] = lambda: pytest.fail("declaration callback invoked")
    elif callback == "foreign_key":
        marker.keywords[1] = "foreign"
    elif callback == "foreign_value":
        marker.keywords["name"] = object()
    elif callback == "missing_attr":
        del marker.keywords["attr"]
    elif callback == "wrong_attr":
        marker.keywords["attr"] = "texture_directory"
    elif callback == "foreign_attr":
        class Foreign:
            def __eq__(self, _other):
                pytest.fail("foreign attr equality")
        marker.keywords["attr"] = Foreign()
    elif callback == "extra_key":
        marker.keywords["unexpected"] = "literal"
    if callback is None:
        fact = module._declaration(bpy)
        module._declaration_unchanged(bpy, fact)
        marker.keywords["name"] = "Changed"
        with pytest.raises(module.BridgeError):
            module._declaration_unchanged(bpy, fact)
    else:
        with pytest.raises(module.BridgeError):
            module._declaration(bpy)


@pytest.fixture
def native_route_model(addon_package, monkeypatch):
    """Model only native constructors; exercise the original route body."""
    module = importlib.import_module(addon_package + ".storage_snapshot_approval")
    classes = {name: type(name, (), {}) for name in ("Context", "Preferences", "Addon", "Struct", "Property",
               "PointerProperty", "CollectionProperty", "StringProperty", "BlenderCodexBridgePreferences")}
    bpy = ModuleType("owned.bpy")
    bpy.types = SimpleNamespace(**classes)
    context, prefs, addon, owner = (classes[name]() for name in
        ("Context", "Preferences", "Addon", "BlenderCodexBridgePreferences"))
    bpy.context = context
    context.preferences, prefs.addons, addon.preferences = prefs, {module.__package__: addon}, owner
    owner.project_directory = "/approved/project"
    calls = []
    def metadata(name, category, *, readonly=True, registered=False, target=None):
        prop = classes[category + "Property"]()
        prop.identifier, prop.type = name, category.upper()
        prop.is_readonly, prop.is_runtime, prop.is_registered = readonly, registered, registered
        prop.fixed_type, prop.subtype = SimpleNamespace(identifier=target), "DIR_PATH"
        return prop
    rnas = {name: SimpleNamespace(properties={}) for name in classes}
    rnas["Context"].properties["preferences"] = metadata("preferences", "Pointer", target="Preferences")
    rnas["Preferences"].properties["addons"] = metadata("addons", "Collection", target="Addon")
    rnas["Addon"].properties["preferences"] = metadata("preferences", "Pointer", target="AddonPreferences")
    rnas["BlenderCodexBridgePreferences"].properties["project_directory"] = metadata(
        "project_directory", "String", readonly=False, registered=True)
    def pointer(value):
        return id(value)
    def native_get(value, name):
        calls.append((type(value).__name__, name))
        return object.__getattribute__(value, name)
    def constructor(_bpy, name, resolved=None):
        cls = classes[name]
        assert resolved is None or resolved is cls
        return cls, rnas[name], native_get, pointer, ()
    monkeypatch.setattr(module.graph, "_constructor_proof", constructor)
    monkeypatch.setattr(module.preferences, "get_preferences", lambda: owner)
    return SimpleNamespace(module=module, classes=classes, bpy=bpy, calls=calls,
        declaration=(classes["BlenderCodexBridgePreferences"],), rnas=rnas)


def test_actual_route_body_checks_exact_metadata_and_original_collection(native_route_model):
    env = native_route_model
    value = env.module._route(env.bpy, env.declaration)
    assert value[7].project_directory == "/approved/project"
    assert len(env.calls) == 3


@pytest.mark.parametrize("kind,field", [("StringProperty", "subtype"), ("StringProperty", "is_registered"),
    ("PointerProperty", "fixed_type"), ("CollectionProperty", "fixed_type"), ("Context", "preferences")])
def test_actual_route_rejects_metadata_shadow_before_callback(native_route_model, kind, field):
    env = native_route_model
    def forbidden(_self):
        pytest.fail("unqualified metadata shadow executed")
    setattr(env.classes[kind], field, property(forbidden))
    with pytest.raises(env.module.graph.BridgeError):
        env.module._route(env.bpy, env.declaration)


def test_actual_route_rejects_foreign_metadata_type_before_field_getter(native_route_model):
    env = native_route_model
    class Foreign:
        def __getattribute__(self, _name):
            pytest.fail("foreign metadata getter")
    env.rnas["BlenderCodexBridgePreferences"].properties["project_directory"] = Foreign()
    with pytest.raises(env.module.BridgeError):
        env.module._route(env.bpy, env.declaration)


@pytest.mark.parametrize("diagnostic_failure", [False, True])
def test_declaration_clause_diagnostic_retains_additional_keyword_difference(addon_package, monkeypatch, diagnostic_failure):
    import os
    module = importlib.import_module(addon_package + ".storage_snapshot_approval")
    class Marker:
        __slots__ = ("function", "keywords")
    class Prefs:
        pass
    marker = Marker()
    marker.function, marker.keywords = os.getcwd, {**dict(module._DECLARATION), "unexpected": "literal"}
    Prefs.__annotations__ = {"project_directory": marker}
    props, bpy = ModuleType("owned.props"), ModuleType("owned.bpy")
    props.StringProperty, props._PropertyDeferred, bpy.props = os.getcwd, Marker, props
    slots = (Marker.function, Marker.keywords)
    origins = (bpy, props, Marker, (), None, slots)
    monkeypatch.setattr(module.graph, "_deferred_type", lambda _bpy: (Marker, origins))
    monkeypatch.setattr(module.preferences, "BlenderCodexBridgePreferences", Prefs)
    if diagnostic_failure:
        def unavailable(*_args):
            raise MemoryError("diagnostic allocation model")
        monkeypatch.setattr(module, "_declaration_clause_facts", unavailable)
    with pytest.raises(module.BridgeError) as failure:
        module._declaration(bpy)
    assert failure.value.code == module.ErrorCode.NOT_IMPLEMENTED
    assert failure.value.context["reason"] == "ROOT_APPROVAL_CALLBACK_OR_DECLARATION_CHANGED"
    if diagnostic_failure:
        assert "declaration_clause" not in failure.value.context
        return
    facts = failure.value.context["declaration_clause"]
    assert facts["function_is_builtin"] and facts["function_matches_original"]
    assert facts["keywords_exact_dict"] and facts["keyword_count"] == 6
    assert facts["expected_keyword_names"] == [key for key, _ in module._DECLARATION]
    assert facts["keywords"][-1] == {"name": "unexpected", "name_kind": "str", "name_truncated": False,
        "value": "literal", "value_kind": "str", "value_truncated": False}


def test_declaration_clause_diagnostic_never_formats_or_traverses_foreign_objects(addon_package):
    module = importlib.import_module(addon_package + ".storage_snapshot_approval")
    class Foreign:
        def __repr__(self):
            pytest.fail("foreign repr")
        def __str__(self):
            pytest.fail("foreign str")
        def __getattribute__(self, _name):
            pytest.fail("foreign attribute")
        def __eq__(self, _other):
            pytest.fail("foreign equality")
    foreign = Foreign()
    facts = module._declaration_clause_facts(foreign, object(), {"get": foreign})
    assert facts["function_kind"] == "Foreign"
    assert facts["function_is_builtin"] is False and facts["function_matches_original"] is False
    assert facts["keywords"][0]["value"] is None and facts["keywords"][0]["value_kind"] == "Foreign"
    class ForeignDict(dict):
        def items(self):
            pytest.fail("foreign items")
        def __len__(self):
            pytest.fail("foreign len")
    facts = module._declaration_clause_facts(foreign, foreign, ForeignDict())
    assert facts["keywords_exact_dict"] is False and facts["keyword_count"] is None and facts["keywords"] == []


def test_declaration_clause_diagnostic_bounds_literal_rows_and_text(addon_package):
    import json
    module = importlib.import_module(addon_package + ".storage_snapshot_approval")
    facts = module._declaration_clause_facts(None, object(), {str(i) * 100: "v" * 10000 for i in range(30)})
    assert facts["keyword_count"] == 30 and facts["rows_truncated"] is True
    assert len(facts["keywords"]) == 16
    assert all(len(row["name"]) <= 64 and len(row["value"]) <= 512 for row in facts["keywords"])
    assert all(row["name_truncated"] and row["value_truncated"] for row in facts["keywords"])
    assert len(json.dumps(facts)) < 16000
    facts = module._declaration_clause_facts(None, None, {"bad": "\ud800", "large": 1 << 10000})
    assert facts["keywords"][0]["value"] is None and facts["keywords"][0]["value_truncated"] is True
    assert facts["keywords"][1]["value"] is None


@pytest.mark.parametrize("drift", ["attr", "get", "set", "update"])
def test_registered_declaration_never_adopts_later_attr_or_callback_drift(addon_package, monkeypatch, drift):
    import os
    module = importlib.import_module(addon_package + ".storage_snapshot_approval")
    class Marker:
        __slots__ = ("function", "keywords")
    class Prefs:
        pass
    marker = Marker()
    marker.function, marker.keywords = os.getcwd, dict(module._DECLARATION)
    Prefs.__annotations__ = {"project_directory": marker}
    props, bpy = ModuleType("owned.props"), ModuleType("owned.bpy")
    props.StringProperty, props._PropertyDeferred, bpy.props = os.getcwd, Marker, props
    origins = (bpy, props, Marker, (), None, (Marker.function, Marker.keywords))
    monkeypatch.setattr(module.graph, "_deferred_type", lambda _bpy: (Marker, origins))
    monkeypatch.setattr(module.preferences, "BlenderCodexBridgePreferences", Prefs)
    fact = module._declaration(bpy)
    assert tuple(marker.keywords) == ("name", "description", "subtype", "default", "attr")
    marker.keywords[drift] = "texture_directory" if drift == "attr" else lambda: pytest.fail("callback invoked")
    with pytest.raises(module.BridgeError) as failure:
        module._declaration_unchanged(bpy, fact)
    assert failure.value.context["reason"] == "ROOT_APPROVAL_DECLARATION_CHANGED"
