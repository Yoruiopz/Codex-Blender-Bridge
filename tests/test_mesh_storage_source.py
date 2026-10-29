"""Source replacement and predicted-storage CAS; no native qualification claim."""
import importlib
from dataclasses import replace
from types import ModuleType

import pytest


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
