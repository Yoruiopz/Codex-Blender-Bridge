from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


class Tracks(list):
    def get(self, name):
        return next((t for t in self if t.name == name), None)


@pytest.fixture
def fixture(addon_package, monkeypatch):
    mod = importlib.import_module(f"{addon_package}.tools.animation_layers")
    track = NS(name="Motion", lock=False, strips=[])
    other = NS(name="Protected", lock=False, strips=[])
    tracks = Tracks([track, other])
    obj = NS(name="Actor", animation_data=NS(nla_tracks=tracks))
    monkeypatch.setattr(mod, "_object", lambda *args: obj)
    monkeypatch.setattr(mod, "inspect", lambda *args: {"tracks": [t.name for t in tracks]})
    return mod, track, tracks


def test_empty_track_removal_preserves_other_tracks(fixture):
    mod, _, tracks = fixture
    result = mod.nla_edit_track(None, {"track_name": "Motion", "remove": True})
    assert result["removed"] and result["tracks"] == ["Protected"]
    assert len(tracks) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"remove": "yes"},
        {"remove": True, "settings": {}},
        {"settings": {"name": "Protected"}},
        {"settings": {"name": "界" * 22}},
        {"settings": {}},
        {"settings": {"name": ""}},
    ],
)
def test_invalid_track_edits_fail_before_mutation(fixture, params):
    mod, track, tracks = fixture
    with pytest.raises(Exception) as caught:
        mod.nla_edit_track(None, {"track_name": "Motion", **params})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert track.name == "Motion" and len(tracks) == 2


def test_track_deletion_does_not_implicitly_remove_strips(fixture):
    mod, track, tracks = fixture
    track.strips.append(NS(name="Walk"))
    with pytest.raises(Exception) as caught:
        mod.nla_edit_track(None, {"track_name": "Motion", "remove": True})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert len(track.strips) == 1 and len(tracks) == 2


@pytest.mark.parametrize(
    "params",
    [
        {"remove": True},
        {"settings": {"mute": True}},
        {"settings": {"lock": False, "name": "Changed"}},
    ],
)
def test_locked_tracks_require_separate_unlock(fixture, params):
    mod, track, tracks = fixture
    track.lock = True
    with pytest.raises(Exception) as caught:
        mod.nla_edit_track(None, {"track_name": "Motion", **params})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert track.lock and len(tracks) == 2
