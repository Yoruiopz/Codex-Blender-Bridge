"""Optional exception diagnostics preserve the original start failure."""

import pytest
from test_scene_jobs import scene_jobs as scene_jobs


class LegacyError(RuntimeError):
    # Exercise the Python 3.10 API shape on newer test interpreters too.
    add_note = None


class BrokenNoteError(RuntimeError):
    def add_note(self, _note):
        raise RuntimeError("Fixture diagnostic failed")


@pytest.mark.parametrize("error_type", [RuntimeError, LegacyError, BrokenNoteError])
def test_secondary_abort_diagnostic_keeps_original_exception(scene_jobs, monkeypatch, error_type):
    env = scene_jobs
    primary = error_type("Original start failed.")

    def failed_claim(*_args, **_kwargs):
        raise primary

    def failed_abort(*_args, **_kwargs):
        raise ValueError("Secondary metadata abort failed.")

    monkeypatch.setattr(env.checkpoints, "claim_pending", failed_claim)
    monkeypatch.setattr(env.checkpoints, "discard_unstarted_pending", failed_abort)
    with pytest.raises(error_type) as caught:
        env.registry.dispatch(env.start_spec.name, {}, env.executor.context)
    assert caught.value is primary and str(primary) == "Original start failed."
    assert env.manager.active is None and env.manager.reservations.owner is not None
    assert len(env.stack.frames) == 1 and env.advances == []
    if error_type is LegacyError or (error_type is RuntimeError and not hasattr(primary, "add_note")):
        assert primary.scene_start_abort_unknown == "ValueError"
    elif error_type is RuntimeError:
        assert primary.__notes__ == ["Scene start metadata abort could not be verified: ValueError"]
