from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from scripts.native_character_evidence import digest, max_difference, plain


def test_semantic_pointer_evidence_drops_process_specific_identity():
    first = NS(name="Character Rig", bl_rna=NS(identifier="Object"), as_pointer=lambda: 101, session_uid=5)
    reopened = NS(name="Character Rig", bl_rna=NS(identifier="Object"), as_pointer=lambda: 202, session_uid=7)
    assert plain(first) == plain(reopened) == {"name": "Character Rig", "type": "Object"}
    assert digest(plain(first)) == digest(plain(reopened))


def test_complete_deformation_comparison_detects_last_vertex_and_shape_changes():
    before = {"bones": {"Root": [[1., 0.], [0., 1.]]}, "vertices": [[0., 0., 0.], [1., 2., 3.]]}
    changed = {"bones": {"Root": [[1., 0.], [0., 1.]]}, "vertices": [[0., 0., 0.], [1., 2., 3.25]]}
    assert max_difference(before, changed) == .25
    with pytest.raises(AssertionError):
        max_difference(before, {**before, "vertices": before["vertices"][:1]})
    with pytest.raises(AssertionError):
        max_difference(before, {**before, "omitted_bone": True})


def test_nonfinite_numeric_evidence_never_produces_a_valid_digest_or_comparison():
    with pytest.raises(ValueError):
        digest([float("nan")])
    with pytest.raises(AssertionError):
        max_difference([float("inf")], [float("inf")])
    with pytest.raises(ValueError):
        plain(float("nan"))


def test_semantic_boolean_settings_cannot_be_replaced_by_equal_numeric_values():
    with pytest.raises(AssertionError):
        max_difference({"mute": False}, {"mute": 0})
    with pytest.raises(AssertionError):
        max_difference({"use_nla": True}, {"use_nla": 1})
