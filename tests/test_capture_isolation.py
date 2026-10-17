from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


class Object:
    def __init__(self, selected=True, hidden=False, render=False, fail=False):
        self.selected, self.hidden, self.hide_render = selected, hidden, render
        self.fail = fail

    def hide_get(self):
        return self.hidden

    def hide_set(self, value):
        if self.fail and value:
            raise RuntimeError("cannot hide")
        self.hidden = value
        if value:
            self.selected = False  # Blender's real hide_set side effect.

    def select_get(self):
        return self.selected

    def select_set(self, value):
        self.selected = value


def test_capture_isolation_restores_visibility_and_selected_hidden_peers(addon_package):
    module = importlib.import_module(f"{addon_package}.viewport")
    target, selected_peer, hidden_peer = Object(), Object(), Object(False, True, True)
    scene = SimpleNamespace(objects=[target, selected_peer, hidden_peer])
    state = module._isolate_object(scene, target)
    assert not selected_peer.selected and selected_peer.hidden and selected_peer.hide_render
    assert module._restore_isolation(state)
    assert target.selected and selected_peer.selected and not hidden_peer.selected
    assert not selected_peer.hidden and not selected_peer.hide_render
    assert hidden_peer.hidden and hidden_peer.hide_render


def test_partial_isolation_failure_restores_selection_too(addon_package):
    module = importlib.import_module(f"{addon_package}.viewport")
    target, selected_peer, failing_peer = Object(), Object(), Object(fail=True)
    with pytest.raises(RuntimeError, match="cannot hide"):
        module._isolate_object(SimpleNamespace(objects=[target, selected_peer, failing_peer]), target)
    assert selected_peer.selected and not selected_peer.hidden and not selected_peer.hide_render
    assert failing_peer.selected and not target.hidden


def test_capture_restore_failure_is_not_silently_successful(addon_package, caplog):
    module = importlib.import_module(f"{addon_package}.viewport")
    assert not module._restore_isolation([(Object(fail=True), True, False, True)])
    assert "Could not restore capture visibility" in caplog.text
