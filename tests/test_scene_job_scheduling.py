"""Scene context failures and sequencing use real canonical composition."""

import pytest
from test_scene_jobs import scene_jobs as scene_jobs


@pytest.mark.parametrize("after_before", [False, True])
@pytest.mark.parametrize("typed", [False, True])
def test_context_factory_failure_retires_scene_with_truthful_checkpoint_receipt(scene_jobs, after_before, typed):
    env = scene_jobs
    accepted = env.start()
    if after_before:
        assert env.manager.tick()
    before = len(env.stack.frames), dict(env.stack.scene), list(env.advances)
    facts = env.checkpoints.pending_status(accepted.job.pending)
    primary = env.errors.BridgeError("TIMEOUT", "Fixture context unavailable.") if typed else RuntimeError("Fixture context unavailable.")

    def unavailable():
        raise primary

    env.manager.context_factory = unavailable
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert terminal["state"] == "FAILED"  # Separate terminal history capture also failed.
    assert terminal["error"]["code"] == ("TIMEOUT" if typed else "OPERATION_FAILED")
    assert terminal["error"]["context"]["operation_history_unknown"] is True
    assert terminal["checkpoint"]["native_snapshots_completed"] == facts["native_snapshots_completed"]
    assert terminal["checkpoint"]["marker_writes_completed"] == facts["marker_writes_completed"]
    assert terminal["error"]["context"]["possible_mutation"] is after_before
    assert terminal["effects"]["native_cleanup_attempted"] is False
    assert (len(env.stack.frames), dict(env.stack.scene), env.advances) == before
    assert env.manager.recovery_ledger[accepted.job.job_id]["checkpoint"] == terminal["checkpoint"]
    assert env.manager.active is None and env.manager.reservations.owner is None
    assert not accepted.job.in_tick and not accepted.owner.connection.background_active.is_set()


@pytest.mark.parametrize("phase", ["fixture_step_0", "checkpoint_after"])
def test_mutated_phase_cannot_skip_owned_before_or_complete_unfinished_driver(scene_jobs, phase):
    env = scene_jobs
    accepted = env.start()
    accepted.job.phase = phase
    before = len(env.stack.frames), dict(env.stack.scene)
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert terminal["state"] == "FAILED" and terminal["result"] is None
    assert terminal["error"]["context"]["reason"] == "SCENE_PHASE_SEQUENCE_CHANGED"
    assert env.advances == [] and (len(env.stack.frames), dict(env.stack.scene)) == before


@pytest.mark.parametrize("field", ["progress", "result"])
@pytest.mark.parametrize("invalid", ["native", "cyclic", "oversize", "nonfinite"])
def test_invalid_driver_evidence_cannot_report_success_after_scene_work(scene_jobs, field, invalid):
    env = scene_jobs
    accepted = env.start(steps=1)
    original = accepted.job.driver.advance

    class Native:
        @property
        def name(self):
            pytest.fail("Evidence validation must not read native getters")

        def __repr__(self):
            pytest.fail("Evidence validation must not call repr")

    values = {"native": Native(), "cyclic": [], "oversize": "x"*65537, "nonfinite": float("inf")}
    values["cyclic"].append(values["cyclic"])

    def advance(context):
        report = original(context)
        if field == "result":
            accepted.job.driver.result = {"invalid": values[invalid]}
            return report
        return {**report, "invalid": values[invalid]}

    accepted.job.driver.advance = advance
    for _ in range(8):
        if not env.manager.tick():
            break
    terminal = accepted.job.summary()
    assert terminal["state"] == "FAILED" and terminal["result"] is None
    assert terminal["error"]["context"]["reason"] == "SCENE_JOB_EVIDENCE_INVALID"
    assert terminal["error"]["context"]["possible_mutation"] is True
    assert terminal["checkpoint"]["native_snapshots_completed"] == 1
    assert not terminal["checkpoint"]["after_verified"] and env.advances == [(1, 1)]


def test_report_and_summary_are_detached_from_driver_and_inspector_mutation(scene_jobs):
    env = scene_jobs
    accepted = env.start(steps=1)
    original = accepted.job.driver.advance
    reports = []

    def advance(context):
        result = original(context)
        result["detail"] = {"value": 1}
        accepted.job.driver.result = {"nested": {"value": 1}}
        reports.append(result)
        return result

    accepted.job.driver.advance = advance
    assert env.manager.tick()  # BEFORE
    assert env.manager.tick()  # Domain report/result freeze.
    reports[0]["detail"]["value"] = 99
    accepted.job.driver.result["nested"]["value"] = 99
    first = env.manager.inspect(accepted.job.job_id)
    assert first["progress"]["detail"]["value"] == 1 and first["result"]["nested"]["value"] == 1
    first["progress"]["detail"]["value"] = 55
    first["result"]["nested"]["value"] = 55
    second = env.manager.inspect(accepted.job.job_id)
    assert second["progress"]["detail"]["value"] == 1 and second["result"]["nested"]["value"] == 1
    assert not env.manager.tick()
    assert accepted.job.summary()["result"]["nested"]["value"] == 1


@pytest.mark.parametrize("failure", ["ledger", "history", "retire_before", "retire_after"])
def test_terminal_retry_retains_first_intent_without_domain_or_duplicate_history(scene_jobs, monkeypatch, failure):
    env = scene_jobs
    accepted = env.start()
    assert env.manager.tick()  # Actual native BEFORE.
    env.manager.cancel(accepted.job.job_id)
    before = len(env.stack.frames), dict(env.stack.scene), list(env.advances)
    history_calls = []
    original_record = env.state.record_operation

    def record(**kwargs):
        history_calls.append(kwargs)
        if failure == "history" and len(history_calls) == 1:
            raise MemoryError("Fixture history allocation failed once")
        return original_record(**kwargs)

    monkeypatch.setattr(env.state, "record_operation", record)
    if failure == "ledger":
        class Ledger(dict):
            failed = False

            def __setitem__(self, key, value):
                if not self.failed:
                    self.failed = True
                    raise MemoryError("Fixture ledger allocation failed once")
                super().__setitem__(key, value)
        env.manager.recovery_ledger = Ledger()
    if failure.startswith("retire"):
        original_retire = env.manager._retire
        attempts = []

        def retire(job):
            attempts.append(True)
            if len(attempts) == 1:
                if failure == "retire_after":
                    original_retire(job)
                raise MemoryError("Fixture retirement failed once")
            original_retire(job)

        monkeypatch.setattr(env.manager, "_retire", retire)
    if failure == "history":
        assert not env.manager.tick()
    else:
        with pytest.raises(MemoryError):
            env.manager.tick()
        assert env.manager.active is accepted.job and env.manager.reservations.owner is not None
        assert accepted.job.terminal_state == "CANCELLED"
        # Retry must not recapture a context or run another history callback.
        env.manager.context_factory = lambda: pytest.fail("Terminal retry must not recapture context")
        assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert terminal["state"] == ("FAILED" if failure == "history" else "CANCELLED")
    assert terminal["error"]["code"] == "TIMEOUT" and len(history_calls) == 1
    assert terminal["checkpoint"]["native_snapshots_completed"] == 1
    assert terminal["checkpoint"]["marker_writes_completed"] == 3
    assert (len(env.stack.frames), dict(env.stack.scene), env.advances) == before
    assert sum(item is accepted.job for item in env.manager.history) == 1
    assert env.manager.active is None and env.manager.reservations.owner is None
    assert not accepted.job.in_tick and accepted.job.driver is None


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("failure", ["memory", "timeout", "runtime"])
def test_native_finished_count_precedes_fallible_window_bookkeeping(scene_jobs, monkeypatch, phase, failure):
    env = scene_jobs
    accepted = env.start(steps=1)
    if phase == "after":
        assert env.manager.tick() and env.manager.tick()
    before = len(env.stack.frames)
    primary = {"memory": MemoryError("Fixture window failure"),
               "timeout": env.errors.BridgeError("TIMEOUT", "Original native bookkeeping timeout."),
               "runtime": RuntimeError("Fixture window failure")}[failure]

    def unavailable(_limit):
        raise primary

    monkeypatch.setattr(env.checkpoints._window, "pushed", unavailable)
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert terminal["state"] == ("CANCELLED" if failure == "timeout" else "FAILED")
    assert terminal["checkpoint"]["native_snapshots_completed"] == (2 if phase == "after" else 1)
    assert len(env.stack.frames) == before+1
    assert terminal["error"]["context"]["possible_mutation"] is True
    assert not terminal["checkpoint"]["after_verified"]
    if failure == "timeout":
        assert terminal["error"]["code"] == "TIMEOUT"
        assert terminal["error"]["message"] == "Original native bookkeeping timeout."
    # Failed window bookkeeping does not authenticate a domain role advance.
    assert env.events.count("authenticated_push") == (1 if phase == "after" else 0)


def test_terminal_error_copy_allocation_failure_keeps_exact_primary_until_retry(scene_jobs, monkeypatch):
    env = scene_jobs
    accepted = env.start()
    assert env.manager.tick()
    env.manager.cancel(accepted.job.job_id)
    original = env.domain.plain
    copies = []

    def allocation(value, **kwargs):
        if kwargs.get("field") == "error":
            copies.append(value)
            if len(copies) == 1:
                raise MemoryError("Fixture error receipt allocation failed once")
        return original(value, **kwargs)

    monkeypatch.setattr(env.domain, "plain", allocation)
    before = len(env.stack.frames), dict(env.stack.scene), list(env.advances)
    with pytest.raises(MemoryError):
        env.manager.tick()
    assert accepted.job.terminal_primary.code == "TIMEOUT" and accepted.job.error is None
    assert not accepted.job.terminal_error_captured and not accepted.job.terminal_history_attempted
    assert env.manager.active is accepted.job and env.manager.reservations.owner is not None
    assert not env.manager.tick()
    terminal = accepted.job.summary()
    assert terminal["state"] == "CANCELLED" and terminal["error"]["code"] == "TIMEOUT"
    assert copies[0] == copies[1] and copies[1]["code"] == "TIMEOUT"
    assert terminal["checkpoint"]["native_snapshots_completed"] == 1
    assert (len(env.stack.frames), dict(env.stack.scene), env.advances) == before
    assert accepted.job.terminal_primary is None and accepted.job.terminal_error_captured
