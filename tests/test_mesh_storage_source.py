"""Source replacement and predicted-storage CAS; no native qualification claim."""
import importlib
from dataclasses import replace
from types import ModuleType
from types import SimpleNamespace as NS

import pytest
from test_scene_jobs import scene_jobs  # noqa: F401 - canonical scheduler fixture


@pytest.fixture
def source(addon_package):
    return importlib.import_module(addon_package + ".mesh_storage_source")


@pytest.mark.parametrize("change", ["module_function", "function_code", "class_method", "foreign_key", "module_class"])
def test_source_seal_refuses_before_foreign_callback(source, monkeypatch, change):
    seal = source.SourceSeal.capture()
    seal.verify()
    calls = []
    def foreign(*args, **kwargs):
        calls.append(True)
        raise AssertionError("foreign source executed")
    class Key:
        def __hash__(self):
            return 8191
        def __eq__(self, other):
            calls.append("equality")
            return False
    if change == "module_function":
        monkeypatch.setattr(source, "metadata_matches", foreign)
    elif change == "function_code":
        monkeypatch.setattr(source.metadata_matches, "__code__", source.metadata_matches.__code__.replace(co_name="changed"))
    elif change == "class_method":
        monkeypatch.setattr(source.Gate, "pure", foreign)
    elif change == "foreign_key":
        monkeypatch.setitem(vars(source), Key(), None)
    else:
        class Altered(ModuleType):
            @property
            def __dict__(self):
                calls.append("dictionary")
                return {}
        monkeypatch.setattr(source, "__class__", Altered)
    with pytest.raises(source.contract.BridgeError):
        seal.verify()
    assert calls == []


def test_source_fingerprint_binds_code_even_when_function_identity_is_retained(source, monkeypatch):
    before = source.SourceSeal.capture().fingerprint()
    fn = source.metadata_matches
    monkeypatch.setattr(fn, "__code__", fn.__code__.replace(co_name="changed"))
    after = source.SourceSeal.capture().fingerprint()
    assert before != after


def test_forward_cas_permits_only_precomputed_selected_array_transition(source):
    p = source.primitive
    obj, mesh = object(), object()
    a = p.AttributeHeader("UV", "CORNER", "FLOAT2", "Float2Attribute", "Float2AttributeValue", "SINGLE", 3, "a", "b")
    b = replace(a, name="Other")
    initial = p._Metadata(obj, mesh, (("uid", "1"),), (("uid", "2"),), "main", (), (-1, ()), (a, b))
    actual = replace(initial, attributes=(replace(a, storage="ARRAY"), b))
    source.metadata_matches(actual, initial, {"UV"})
    with pytest.raises(source.contract.BridgeError):
        source.metadata_matches(actual, initial, set())
    with pytest.raises(source.contract.BridgeError):
        source.metadata_matches(replace(actual, attributes=(actual.attributes[0], replace(b, count=4))), initial, {"UV"})
    with pytest.raises(source.contract.BridgeError):
        source.metadata_matches(replace(actual, mesh=object()), initial, {"UV"})
    assert initial.attributes == (a, b) and a.storage == "SINGLE"


@pytest.fixture
def protected_gate(source, scene_jobs, monkeypatch, addon_package):  # noqa: F811
    """Genuine policy/store/gate; Blender reads remain explicit model effects."""
    env = scene_jobs
    artist = importlib.import_module(addon_package + ".tools.artist_loop")
    animation = importlib.import_module(addon_package + ".tools._animation_scope")
    errors = importlib.import_module(addon_package + ".errors")
    monkeypatch.setattr(source, "available_memory_facts", lambda: {"available_memory_bytes": 2 * 1024**3})
    env.registry.register(source.contract.PREVIEW, lambda *_args: {},
                          permissions=source.contract.PERMISSIONS, toolset="geometry")
    env.registry.enable_toolset("geometry")
    context = env.executor.context
    store = source.get_task_plans(context.state)
    store.plan = {"plan_id": "protected-plan", "protected_objects": ["Protected"]}
    store.scope = (17, (("Protected", 23),))
    store.protection = {"plan_id": "protected-plan", "scope": store.scope}
    protected = NS(name="Protected", session_uid=23, as_pointer=lambda: 23)
    untouched = NS(name="Untouched", session_uid=31, as_pointer=lambda: 31)
    bpy = NS(context=NS(scene=NS(session_uid=17, objects=[protected], as_pointer=lambda: 17),
                        view_layer=NS(objects={"Protected": protected})))
    return NS(env=env, artist=artist, animation=animation, errors=errors, context=context,
              store=store, protected=protected, untouched=untouched, bpy=bpy,
              gate=source.Gate(context, source.SourceSeal.capture(), source.contract.PREVIEW))


def test_affected_scope_dependency_modules_are_held_before_providers(source, addon_package):
    seal = source.SourceSeal.capture()
    names = {module.__name__ for module, _rows in tuple.__getitem__(seal, 0)}
    assert {addon_package + suffix for suffix in (".tools.artist_loop", ".tools._animation_scope", ".errors")} <= names
    source.verify_seal(seal)


@pytest.mark.parametrize("scene_job_manager", ("scene", "native_save"))
@pytest.mark.parametrize("native_uid", (True, False))
def test_genuine_affected_scope_remains_functional_after_authorization(protected_gate, scene_job_manager, native_uid):
    s = protected_gate
    if not native_uid:
        s.bpy.context.scene.session_uid = s.protected.session_uid = s.untouched.session_uid = None
    s.gate.authorize()
    stamp = s.artist.policy_stamp(s.context)
    s.artist.check_affected(s.context, s.bpy, (s.untouched,), stamp=stamp)
    with pytest.raises(s.errors.BridgeError) as failure:
        s.artist.check_affected(s.context, s.bpy, (s.protected,), stamp=stamp)
    assert failure.value.context["protected_scope_violation"] is True
    assert failure.value.context["affected_protected_objects"] == ["Protected"]
    assert s.store.protection["scope"] == s.store.scope
    assert s.env.provider_calls > 0 and scene_job_manager in {"scene", "native_save"}


@pytest.mark.parametrize("scene_job_manager", ("scene", "native_save"))
@pytest.mark.parametrize("change", (
    "scene_scope", "objects", "scope_alias", "bounded", "key", "islice",
    "policy_stamp", "get_task_plans", "error_factory_global", "error_class_alias",
    "helper_code", "helper_defaults", "affected_kwdefaults", "artist_module_class",
    "animation_module_class", "artist_foreign_key", "animation_foreign_key",
))
def test_permission_provider_cannot_replace_affected_scope_closure_before_native_read(
    source, protected_gate, monkeypatch, scene_job_manager, change,
):
    s, calls = protected_gate, []

    def foreign(*_args, **_kwargs):
        calls.append("foreign callback")
        raise AssertionError("Unverified affected-scope callback ran")

    class UnreadNative:
        def __getattribute__(self, _name):
            calls.append("native reader")
            raise AssertionError("Native read preceded source refusal")

    class ForeignKey:
        def __hash__(self):
            return 8191
        def __eq__(self, _other):
            calls.append("foreign equality")
            return False

    def inject():
        if change in {"scene_scope", "objects", "policy_stamp", "get_task_plans"}:
            name = {"scene_scope": "_scene_scope", "objects": "_objects"}.get(change, change)
            monkeypatch.setattr(s.artist, name, foreign)
        elif change == "scope_alias":
            monkeypatch.setattr(s.artist, "scope", NS(bounded=foreign, key=foreign))
        elif change in {"bounded", "key", "islice"}:
            monkeypatch.setattr(s.animation, change, foreign)
        elif change == "error_factory_global":
            monkeypatch.setattr(s.errors, "BridgeError", foreign)
        elif change == "error_class_alias":
            monkeypatch.setattr(s.animation, "BridgeError", foreign)
        elif change == "helper_code":
            fn = s.artist._scene_scope
            monkeypatch.setattr(fn, "__code__", fn.__code__.replace(co_name="changed"))
        elif change == "helper_defaults":
            monkeypatch.setattr(s.animation.bounded, "__defaults__", (foreign,))
        elif change == "affected_kwdefaults":
            monkeypatch.setitem(s.artist.check_affected.__kwdefaults__, "stamp", foreign)
        elif change.endswith("module_class"):
            class Altered(ModuleType):
                @property
                def __dict__(self):
                    calls.append("foreign module dictionary")
                    return {}
            monkeypatch.setattr(s.artist if change.startswith("artist") else s.animation, "__class__", Altered)
        else:
            monkeypatch.setitem(vars(s.artist if change.startswith("artist") else s.animation), ForeignKey(), None)

    s.env.provider_hook = inject
    before = s.env.provider_calls
    with pytest.raises(source.contract.BridgeError) as failure:
        s.gate.authorize()
        # This is the same held pre-provider authorization ordering used before
        # the concrete protected resolver reaches check_affected. The stamp
        # mismatch also exercises its direct error-factory dependency.
        s.artist.check_affected(s.context, UnreadNative(), (s.untouched,), stamp=("wrong", -1))
    assert failure.value.context["reason"] == "STORAGE_SOURCE_CHANGED"
    assert s.env.provider_calls > before
    assert calls == [] and scene_job_manager in {"scene", "native_save"}
