from __future__ import annotations

import importlib
import threading
import time
from types import SimpleNamespace as NS

import pytest
from test_image_paint import paint_tools  # noqa: F401
from test_paint_jobs import finish, jobs, start  # noqa: F401


@pytest.fixture
def controller(addon_package, monkeypatch):
    engine = importlib.import_module(f"{addon_package}.job_controller")
    errors = importlib.import_module(f"{addon_package}.errors")
    lifetime = importlib.import_module(f"{addon_package}.request_lifecycle")
    clock = NS(value=0.)
    monkeypatch.setattr(time, "perf_counter", lambda: clock.value)

    class Record:
        def __init__(self, identifier, values, owner):
            self.job_id, self.values, self.lifetime = identifier, tuple(values), owner
            self.method, self.deadline = "fixture.compute", float("inf")
            self.state, self.revision = "QUEUED", 1
            self.progress = {"phase": "awaiting_start_delivery", "completed": 0, "total": 1}
            self.work = self.result = self.error = None
            self.cancel_reason, self.in_tick, self.in_commit = "", False, False
            self.resources = {"private_input": object()}

        def summary(self):
            return {"job_id": self.job_id, "kind": "fixture.compute", "state": self.state,
                    "terminal": self.state in {"SUCCEEDED", "FAILED", "CANCELLED"},
                    "revision": self.revision, "progress": dict(self.progress), "result": self.result,
                    "error": self.error}

    class Domain(engine.CooperativeJobController):
        def __init__(self):
            self.flags = {"paused": False, "emergency_stopped": False}
            self.prepared_calls, self.work_calls, self.completion_calls = [], [], []
            self.finish_calls, self.closed_work, self.retired_resources = [], [], []
            self.sequence, self.fault, self.on_step = 0, None, None
            self.finalizer_failures = 0
            self.context_value = NS(
                state=NS(snapshot=lambda: dict(self.flags)),
                registry=NS(prepare=lambda method, context: self.prepared_calls.append(method)),
            )
            super().__init__(lambda: self.context_value, budget_ms=lambda: 1.)

        def add(self, values=(2, 4, 6), *, delivered=True):
            assert self.active is None
            owner = lifetime.RequestLifetime(lifetime.ConnectionLifetime(), float("inf"))
            if delivered:
                owner.acknowledge(True)
            self.sequence += 1
            job = Record(f"toy_{self.sequence}", values, owner)
            self.active = job
            return job

        def _context(self, job):
            return self.context_factory()

        def _check(self, job, context):
            job.lifetime.check()
            if job.cancel_reason or time.monotonic() >= job.deadline:
                raise errors.BridgeError(errors.ErrorCode.TIMEOUT, "Fixture owner stopped.")

        def _make_work(self, job, context):
            self.work_calls.append(job.job_id)
            if self.fault == "construct":
                raise ValueError("Fixture work construction failed")

            def calculate():
                try:
                    for index, _value in enumerate(job.values):
                        if self.on_step is not None:
                            self.on_step(job)
                        if self.fault == "iterate":
                            raise ValueError("Fixture cooperative calculation failed")
                        if self.fault == "denied":
                            raise errors.BridgeError(errors.ErrorCode.PERMISSION_DENIED, "Fixture denied.")
                        # One cooperative step exceeds the configured slice, so
                        # another step must wait for a later controller tick.
                        clock.value += .002
                        yield {"phase": "calculating", "completed": index+1, "total": len(job.values)}
                    return sum(job.values)
                finally:
                    self.closed_work.append(job.job_id)

            return calculate()

        def _complete_work(self, job, context, value):
            self.completion_calls.append((job.job_id, value))
            if self.fault == "complete":
                raise ValueError("Fixture native completion failed")
            job.result = value
            self._finish(job, "SUCCEEDED")

        def _finish(self, job, state, error=None):
            self.finish_calls.append((job.job_id, state))
            if self.finalizer_failures:
                self.finalizer_failures -= 1
                raise RuntimeError("Fixture domain finalization failed")
            if job.state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                return
            if job.work is not None:
                work, job.work = job.work, None
                work.close()
            job.resources.clear()
            job.state, job.error = state, error.to_dict() if error is not None else None
            if state != "SUCCEEDED":
                job.result = None
            job.progress = {**job.progress, "phase": state.lower()}
            job.revision += 1
            self.retired_resources.append((job.job_id, dict(job.resources), job.work))
            self._retire(job)

    return NS(engine=engine, errors=errors, lifetime=lifetime, clock=clock, manager=Domain())


def drain(manager):
    for _ in range(20):
        if not manager.tick():
            return manager.history[0]
    pytest.fail("Fixture controller did not finish within its bounded steps")


def test_nonimage_work_waits_for_ack_and_uses_its_separate_owner_deadline(controller):
    manager = controller.manager
    job = manager.add(delivered=False)
    assert manager.tick() and job.work is None
    assert manager.work_calls == manager.completion_calls == manager.finish_calls == []
    assert manager.prepared_calls == [] and job.resources
    job.lifetime.acknowledge(True)
    job.lifetime.deadline = 0  # Delivered start RPC expiry does not expire this job.
    terminal = drain(manager)
    assert terminal is job and job.state == "SUCCEEDED" and job.result == 12
    assert manager.work_calls == [job.job_id] and manager.completion_calls == [(job.job_id, 12)]
    assert manager.retired_resources == [(job.job_id, {}, None)]
    assert manager.active is None and not job.in_tick


def test_budget_yields_between_steps_and_preserves_revisioned_progress(controller):
    manager = controller.manager
    job = manager.add()
    revisions = []
    for expected in (1, 2, 3):
        assert manager.tick()
        assert job.progress == {"phase": "calculating", "completed": expected, "total": 3}
        assert not job.in_tick and job.resources and not manager.history
        revisions.append(job.revision)
    assert revisions == sorted(set(revisions))
    assert not manager.tick()
    assert job.state == "SUCCEEDED" and manager.closed_work == [job.job_id]


def test_pause_resumes_existing_work_without_restarting_it(controller):
    manager = controller.manager
    job = manager.add()
    assert manager.tick() and job.progress["completed"] == 1
    work = job.work
    manager.flags["paused"] = True
    revision = job.revision
    assert manager.tick() and job.state == "PAUSED" and job.work is work
    assert job.revision > revision and job.progress["completed"] == 1
    revision = job.revision
    assert manager.tick() and job.revision == revision and job.work is work
    manager.flags["paused"] = False
    assert drain(manager).state == "SUCCEEDED"
    assert manager.work_calls == [job.job_id]


@pytest.mark.parametrize("stop", ["deadline", "cancel", "disconnect", "reject", "handoff", "emergency"])
def test_undelivered_or_paused_owner_stops_before_constructing_work(controller, stop):
    manager = controller.manager
    job = manager.add(delivered=False)
    manager.flags["paused"] = stop in {"deadline", "cancel"}
    if manager.flags["paused"]:
        assert manager.tick() and job.state == "PAUSED"
    if stop == "deadline":
        job.deadline = 0
    elif stop == "cancel":
        assert manager.cancel(job.job_id)["cancel_requested"]
    elif stop == "disconnect":
        job.lifetime.connection.disconnected.set()
    elif stop == "reject":
        job.lifetime.acknowledge(False)
    elif stop == "handoff":
        job.lifetime.deadline = 0
    else:
        manager.flags["emergency_stopped"] = True
    terminal = drain(manager)
    assert terminal.state == "CANCELLED" and terminal.result is None
    assert manager.work_calls == manager.completion_calls == []
    assert not job.resources and not job.in_tick and manager.active is None


def test_foreign_thread_cannot_execute_or_control_the_owner(controller):
    manager = controller.manager
    job = manager.add()
    failures = []

    def foreign_thread():
        actions = (manager.tick, lambda: manager.inspect(job.job_id), manager.list, manager.status,
                   lambda: manager.cancel(job.job_id), lambda: manager.cancel_all("foreign thread"))
        for action in actions:
            try:
                action()
            except controller.errors.BridgeError as error:
                failures.append(error.code)

    worker = threading.Thread(target=foreign_thread)
    worker.start()
    worker.join(2)
    assert not worker.is_alive() and failures == ["BLENDER_CONTEXT_ERROR"]*6
    assert manager.active is job and job.state == "QUEUED" and not job.cancel_reason
    assert not manager.work_calls and not manager.history


def test_terminal_history_is_bounded_and_status_keeps_only_control_fields(controller):
    manager = controller.manager
    first = None
    for _ in range(34):
        job = manager.add(values=())
        first = first or job
        assert not manager.tick()
    listing = manager.list(2)
    assert len(manager.history) == listing["total"] == 32 and listing["truncated"]
    assert listing["max_active"] == 1 and listing["terminal_history_limit"] == 32
    assert manager.inspect(job.job_id)["result"] == 0
    assert "result" not in manager.status()["last_terminal"]
    assert not manager.cancel(job.job_id)["cancel_requested"]
    with pytest.raises(controller.errors.BridgeError):
        manager.inspect(first.job_id)


def test_cancel_during_native_completion_defers_release_until_a_safe_tick(controller):
    manager = controller.manager
    job = manager.add()
    job.in_commit = True
    manager.cancel_all("native callback cancellation")
    assert manager.active is job and job.resources and not manager.finish_calls
    assert job.cancel_reason == "native callback cancellation"
    job.in_commit = False
    assert drain(manager).state == "CANCELLED"
    assert manager.finish_calls == [(job.job_id, "CANCELLED")]


def test_reentrant_generator_cancel_never_closes_executing_work(controller):
    manager = controller.manager
    job = manager.add()
    observed = []

    def cancel_while_running(current):
        manager.cancel_all("cooperative callback cancellation")
        observed.append((manager.active is current, bool(current.resources), current.in_tick))
        assert current.work is not None and not manager.closed_work and not manager.finish_calls

    manager.on_step = cancel_while_running
    assert manager.tick() and observed == [(True, True, True)]
    assert drain(manager).state == "CANCELLED"
    assert manager.closed_work == [job.job_id] and len(manager.history) == 1
    assert manager.finish_calls == [(job.job_id, "CANCELLED")]


@pytest.mark.parametrize("fault", ["construct", "iterate", "complete", "denied"])
def test_work_and_domain_completion_failures_use_one_truthful_terminal_record(controller, fault):
    manager = controller.manager
    manager.fault = fault
    job = manager.add()
    terminal = drain(manager)
    assert terminal is job and job.state == "FAILED" and job.result is None
    assert job.error["code"] == ("PERMISSION_DENIED" if fault == "denied" else "OPERATION_FAILED")
    assert manager.finish_calls == [(job.job_id, "FAILED")]
    assert manager.retired_resources == [(job.job_id, {}, None)]
    assert not job.in_tick and manager.active is None and len(manager.history) == 1


def test_first_finalizer_failure_is_retried_as_failed_before_retirement(controller):
    manager = controller.manager
    manager.finalizer_failures = 1
    job = manager.add(values=())
    assert not manager.tick()
    assert manager.finish_calls == [(job.job_id, "SUCCEEDED"), (job.job_id, "FAILED")]
    assert job.state == "FAILED" and job.result is None and job.error["code"] == "OPERATION_FAILED"
    assert manager.retired_resources == [(job.job_id, {}, None)] and len(manager.history) == 1
    assert manager.active is None and not job.in_tick


def test_repeated_finalizer_failure_retains_active_owner_without_false_history(controller):
    manager = controller.manager
    manager.finalizer_failures = 2
    job = manager.add(values=())
    with pytest.raises(RuntimeError, match="domain finalization failed"):
        manager.tick()
    assert manager.finish_calls == [(job.job_id, "SUCCEEDED"), (job.job_id, "FAILED")]
    assert manager.active is job and job.resources and job.work is not None
    assert job.state not in {"SUCCEEDED", "FAILED", "CANCELLED"} and not job.in_tick
    assert not manager.history and not manager.retired_resources


def test_existing_image_adapter_uses_shared_tick_for_handoff_and_native_publication(request, monkeypatch):
    env = request.getfixturevalue("jobs")
    engine = importlib.import_module(env.module.__package__ + ".job_controller")
    original_tick = engine.CooperativeJobController.tick
    original_work = type(env.manager)._make_work
    ticks, image_work = [], []

    def shared_tick(manager):
        ticks.append(manager.active.job_id if manager.active else None)
        return original_tick(manager)

    def make_image_work(manager, job, context):
        image_work.append(job.job_id)
        return original_work(manager, job, context)

    monkeypatch.setattr(engine.CooperativeJobController, "tick", shared_tick)
    monkeypatch.setattr(type(env.manager), "_make_work", make_image_work)
    lifetime_module = importlib.import_module(env.module.RequestLifetime.__module__)
    owner = lifetime_module.RequestLifetime(lifetime_module.ConnectionLifetime(), float("inf"))
    context = env.context()
    context.request_lifecycle = owner
    accepted = start(env, context=context)
    assert env.manager.tick() and ticks == [accepted["job_id"]]
    assert not image_work and not env.marks and env.images.get("Painted") is None
    owner.acknowledge(True)
    terminal = finish(env)
    assert terminal["state"] == "SUCCEEDED" and terminal["undo_boundary_finalized"]
    assert image_work == [accepted["job_id"]] and len(ticks) >= 2
    assert env.images.get("Painted") is not None and len(env.marks) == 2
    assert not owner.connection.background_active.is_set()
