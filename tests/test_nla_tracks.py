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
    track = NS(name="Motion", lock=False, strips=[], is_solo=False, mute=False)
    other = NS(name="Protected", lock=False, strips=[], is_solo=False, mute=False)
    tracks = Tracks([track, other])
    obj = NS(name="Actor", animation_data=NS(nla_tracks=tracks, use_nla=True))
    monkeypatch.setattr(mod, "_object", lambda *args: obj)
    monkeypatch.setattr(mod, "inspect", lambda *args: {"tracks": [t.name for t in tracks]})
    return mod, track, tracks


def test_empty_track_removal_preserves_other_tracks(fixture):
    mod, _, tracks = fixture
    result = mod.nla_edit_track(None, {"track_name": "Motion", "remove": True})
    assert result["removed"] and result["tracks"] == ["Protected"]
    assert len(tracks) == 1


def test_solo_replacement_requires_acknowledgement(fixture):
    mod, track, tracks = fixture
    tracks[1].is_solo = True
    with pytest.raises(Exception) as caught:
        mod.nla_solo_track(None, {"track_name": "Motion", "enabled": True})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert tracks[1].is_solo and not track.is_solo
    result = mod.nla_solo_track(
        None, {"track_name": "Motion", "enabled": True, "replace_existing": True}
    )
    assert result["solo_before"] == ["Protected"] and result["solo_after"] == ["Motion"]
    assert set(result["changed_tracks"]) == {"Protected", "Motion"}
    result = mod.nla_solo_track(None, {"track_name": "Motion", "enabled": False})
    assert result["solo_after"] == []


@pytest.mark.parametrize(
    "params", [{"enabled": 1}, {"enabled": True, "replace_existing": "yes"}, {}]
)
def test_solo_rejects_non_boolean_flags(fixture, params):
    mod, track, _ = fixture
    with pytest.raises(Exception) as caught:
        mod.nla_solo_track(None, {"track_name": "Motion", **params})
    assert caught.value.code == "INVALID_ARGUMENT" and not track.is_solo


def test_solo_preserves_other_solo_when_disabling_non_solo_track(fixture):
    mod, _, tracks = fixture
    tracks[1].is_solo = True
    result = mod.nla_solo_track(None, {"track_name": "Motion", "enabled": False})
    assert result["changed_tracks"] == [] and tracks[1].is_solo


def test_solo_respects_other_track_lock(fixture):
    mod, track, tracks = fixture
    tracks[1].is_solo = tracks[1].lock = True
    with pytest.raises(Exception) as caught:
        mod.nla_solo_track(
            None, {"track_name": "Motion", "enabled": True, "replace_existing": True}
        )
    assert caught.value.code == "INVALID_ARGUMENT" and not track.is_solo
    assert tracks[1].is_solo


@pytest.mark.parametrize("condition", ["muted", "disabled", "locked"])
def test_solo_does_not_implicitly_enable_or_unlock(fixture, condition):
    mod, track, _ = fixture
    if condition == "muted":
        track.mute = True
    elif condition == "locked":
        track.lock = True
    else:
        mod._object({}).animation_data.use_nla = False
    with pytest.raises(Exception) as caught:
        mod.nla_solo_track(None, {"track_name": "Motion", "enabled": True})
    assert caught.value.code == "INVALID_ARGUMENT" and not track.is_solo


def test_solo_failure_restores_previous_solo(fixture):
    mod, _, tracks = fixture

    class FailingTrack:
        name = "Motion"
        lock = mute = False
        _solo = False

        @property
        def is_solo(self):
            return self._solo

        @is_solo.setter
        def is_solo(self, value):
            if value:
                raise RuntimeError("injected failure")
            self._solo = value

    tracks[0] = FailingTrack()
    tracks[1].is_solo = True
    with pytest.raises(Exception) as caught:
        mod.nla_solo_track(
            None, {"track_name": "Motion", "enabled": True, "replace_existing": True}
        )
    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["rollback_performed"]
    assert tracks[1].is_solo and not tracks[0].is_solo


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
