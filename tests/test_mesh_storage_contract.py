"""Typed opt-in intent rejects malformed inputs before any native boundary."""
import importlib

import pytest


@pytest.fixture
def contract(addon_package):
    return importlib.import_module(addon_package + ".mesh_storage_contract")


def params():
    return {"object_name": "Target", "mesh_name": "Target Mesh", "attribute_names": ["UVMap", ".select_poly"]}


def test_preview_and_start_share_exact_normalized_intent(contract):
    before = contract.parse(params())
    start = {**params(), "expected_preparation_fingerprint": "a" * 64,
             "confirm_materialize_storage": True, "confirm_retained_partial_preparation": True}
    after = contract.parse(start, starting=True)
    assert before.plain() == after.plain()
    assert before.attribute_names == ("UVMap", ".select_poly")


@pytest.mark.parametrize("field,value", [
    ("object_name", None), ("mesh_name", ""), ("mesh_name", "x\x00y"), ("object_name", "é" * 32),
    ("attribute_names", []), ("attribute_names", ("UVMap",)), ("attribute_names", ["UVMap", "UVMap"]),
    ("attribute_names", [True]), ("attribute_names", [str(i) for i in range(33)]),
    ("time_limit_seconds", True), ("time_limit_seconds", 0), ("time_limit_seconds", 301),
    ("time_limit_seconds", float("inf")), ("time_limit_seconds", float("nan")), ("extra", 1),
])
def test_malformed_intent_refuses_before_source_or_blender(contract, field, value):
    with pytest.raises(contract.BridgeError):
        contract.parse({**params(), field: value})


@pytest.mark.parametrize("field,value", [("confirm_materialize_storage", False),
    ("confirm_retained_partial_preparation", None), ("confirm_materialize_storage", 1),
    ("expected_preparation_fingerprint", "A" * 64), ("expected_preparation_fingerprint", "a" * 63)])
def test_start_requires_both_explicit_consents_and_exact_preview(contract, field, value):
    start = {**params(), "expected_preparation_fingerprint": "a" * 64,
             "confirm_materialize_storage": True, "confirm_retained_partial_preparation": True}
    with pytest.raises(contract.BridgeError):
        contract.parse({**start, field: value}, starting=True)


def test_foreign_type_metaclass_cannot_run_in_deadline_classification(contract):
    calls = []
    class Meta(type):
        def __eq__(self, other):
            calls.append(other)
            return False
    class Foreign(metaclass=Meta):
        pass
    with pytest.raises(contract.BridgeError):
        contract.parse({**params(), "time_limit_seconds": Foreign()})
    assert calls == []
