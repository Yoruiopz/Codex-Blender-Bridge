"""Canonical final safe points never rerun providers after a content proof."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
import test_object_rna_mutation as object_tests
import test_rigging_edit_boundaries as rig_tests

STOPS = ("queued", "disconnect", "deadline", "rejected", "job", "toolset", "pause", "emergency")


@pytest.fixture
def object_env(addon_package, monkeypatch):
    return object_tests.env.__wrapped__(addon_package, monkeypatch)


@pytest.fixture
def rig_env(addon_package, monkeypatch):
    return rig_tests.boundary.__wrapped__(addon_package, monkeypatch)


def owner_flags(addon_package, context, method):
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    queue = importlib.import_module(f"{addon_package}.command_queue")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    registry = importlib.import_module(f"{addon_package}.tool_registry")
    life = lifecycle.RequestLifetime(lifecycle.ConnectionLifetime())
    queued = queue.QueuedRequest(protocol.Request(id="final-write-owner", method=method, params={}))
    queued.deadline = float("inf")
    context.request_lifecycle = life
    context.check_final_request = queued.check_active
    job = [False]

    def job_check():
        if job[0]:
            raise registry.BridgeError("TIMEOUT", "Scheduler deadline expired during content read")

    context.check_final_job = job_check

    def stop(kind):
        if kind == "queued":
            queued.cancel_pending(registry.BridgeError("TIMEOUT", "Caller canceled"))
        elif kind == "disconnect":
            life.connection.disconnected.set()
        elif kind == "deadline":
            life.deadline = 0.
        elif kind == "rejected":
            life.rejected.set()
        elif kind == "job":
            job[0] = True
        elif kind == "toolset":
            context.registry.disable_toolset(context.registry.get(method).toolset)
        elif kind == "pause":
            if hasattr(context.state, "set_paused"):
                context.state.set_paused(True)
            else:
                context.state.snapshot = lambda: {"paused": True, "emergency_stopped": False}
        else:
            if hasattr(context.state, "set_emergency_stopped"):
                context.state.set_emergency_stopped(True)
            else:
                context.state.snapshot = lambda: {"paused": False, "emergency_stopped": True}

    return NS(stop=stop, life=life, queued=queued, job=job, module=registry)


@pytest.mark.parametrize("stop", STOPS)
@pytest.mark.parametrize("where", ("last_provider", "content", "prediction"))
def test_object_final_authority_blocks_next_write_and_latches(object_env, addon_package, monkeypatch, stop, where):
    case = object_env
    owned = case.obj.modifiers.new()
    guard = object_tests.boundary(case)
    flags = owner_flags(addon_package, case.context, guard.method)
    fired = []

    def inject():
        if not fired:
            fired.append(True)
            flags.stop(stop)

    if where == "last_provider":
        calls = []

        def provider():
            calls.append(True)
            if len(calls) == 2:
                inject()

        case.provider[0] = provider
    elif where == "content":
        original = guard._protected

        def capture():
            value = original()
            inject()
            return value

        monkeypatch.setattr(guard, "_protected", capture)
    else:
        original = guard._predict

        def predict(*args):
            value = original(*args)
            inject()
            return value

        monkeypatch.setattr(guard, "_predict", predict)
    with pytest.raises(flags.module.BridgeError):
        guard.write(owned, "width", 2.)
    assert fired and owned.width == 1. and not guard.started
    assert guard.stopped is not None
    # Even renewed authority cannot restart this already-stopped operation or
    # authorize its attempted automatic compensation.
    flags.life.connection.disconnected.clear()
    flags.life.rejected.clear()
    flags.life.deadline = float("inf")
    flags.queued._stop_requested = False
    flags.job[0] = False
    monkeypatch.setattr(case.context, "check_final_job", None)
    case.context.registry.enable_toolset("objects")
    with pytest.raises(flags.module.BridgeError):
        guard.write(owned, "width", 3.)
    assert owned.width == 1.


@pytest.mark.parametrize("stop", STOPS)
@pytest.mark.parametrize("where", ("last_provider", "content", "last_read"))
def test_rig_final_authority_blocks_next_write(rig_env, addon_package, monkeypatch, stop, where):
    case = rig_env
    guard = case.boundary
    flags = owner_flags(addon_package, case.context, guard.method)
    fired = []

    def inject():
        if not fired:
            fired.append(True)
            flags.stop(stop)

    if where == "last_provider":
        calls = []

        def provider():
            calls.append(True)
            if len(calls) == 2:
                inject()
            return case.grants

        case.provider[0] = provider
    else:
        original = guard._protected
        reads = []

        def capture():
            result = original()
            reads.append(True)
            if len(reads) == (1 if where == "content" else 2):
                inject()
            return result

        monkeypatch.setattr(guard, "_protected", capture)
    with pytest.raises(flags.module.BridgeError) as caught:
        guard.write(case.bone, "location", (1., 2., 3.))
    assert fired and case.bone.location == (0., 0., 0.) and guard.steps == 0
    assert not caught.value.context["possible_mutation"]


def test_final_helper_does_not_call_permissions_or_arbitrary_cancellation(addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry")

    def forbidden(*_args):
        raise AssertionError("Final mutation check invoked a callback-capable provider")

    tools = registry.ToolRegistry(enabled_toolsets=("fixture",))
    tools.register("fixture.edit", lambda *_: None, toolset="fixture", modifies=True)
    context = registry.ToolContext(NS(snapshot=lambda: {}), NS(require=forbidden), tools, None,
                                   check_cancelled=forbidden)
    registry.check_final_mutation(context, "fixture.edit")


@pytest.mark.parametrize("callback_kind", ("canonical", "arbitrary", "lookalike", "override"))
def test_executor_installs_only_canonical_queue_hook(addon_package, callback_kind):
    registry = importlib.import_module(f"{addon_package}.tool_registry")
    queue = importlib.import_module(f"{addon_package}.command_queue")
    executor_module = importlib.import_module(f"{addon_package}.executor")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state")
    protocol = importlib.import_module(f"{addon_package}.protocol")
    seen = []
    tools = registry.ToolRegistry()

    def handler(context, _params):
        seen.append(context.check_final_request)

    tools.register("fixture.inspect", handler)
    executor = executor_module.MainThreadExecutor(command_queue=queue.CommandQueue(), registry=tools,
        state=state.BridgeState(), permissions=permissions.PermissionManager(lambda: {}), checkpoints=None)
    request = protocol.Request(id="hook-kind", method="fixture.inspect", params={})
    owner = queue.QueuedRequest(request, deadline=float("inf"))
    if callback_kind == "canonical":
        callback = owner.check_active
    elif callback_kind == "arbitrary":
        def callback():
            pass
    elif callback_kind == "lookalike":
        class Lookalike:
            def check_active(self):
                pass
        callback = Lookalike().check_active
    else:
        class Override(queue.QueuedRequest):
            def check_active(self):
                pass
        callback = Override(request, deadline=float("inf")).check_active
    assert executor.execute_request(request, check_cancelled=callback).ok
    assert len(seen) == 1
    if callback_kind == "canonical":
        assert callable(seen[0])
        owner.cancel_pending(registry.BridgeError("TIMEOUT", "Canceled after handler"))
        with pytest.raises(registry.BridgeError, match="cooperative"):
            seen[0]()
    else:
        assert seen[0] is None


def test_context_final_gate_runs_after_rest_and_pose_reads(rig_env, addon_package, monkeypatch):
    case = rig_env
    flags = owner_flags(addon_package, case.context, case.boundary.method)
    monkeypatch.setattr(case.proof, "_common_geometry", lambda _: ())
    monkeypatch.setattr(case.proof, "_rest", lambda *_: ())

    def pose(_rig):
        flags.stop("deadline")
        return ()

    monkeypatch.setattr(case.proof, "_pose", pose)
    writes = []
    with pytest.raises(flags.module.BridgeError):
        case.boundary.contextual(lambda: writes.append(True), change=(5, ()))
    assert not writes and case.boundary.steps == 0


@pytest.mark.parametrize("operation", ("allocate", "assign", "link"))
def test_creation_final_gate_after_last_owned_read(addon_package, monkeypatch, operation):
    proof = importlib.import_module(f"{addon_package}.tools._rigging_edit")
    registry = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state")
    tools = registry.ToolRegistry(enabled_toolsets=("rigging",))
    tools.register("rig.create", lambda *_: None, toolset="rigging", modifies=True)
    context = registry.ToolContext(state.BridgeState(), permissions.PermissionManager(lambda: {}), tools, None)
    flags = owner_flags(addon_package, context, "rig.create")
    creation = proof.Creation.__new__(proof.Creation)
    creation.context = context
    creation.check = lambda: None
    owner = NS(name="New Rig", location=(0., 0., 0.))
    creation.content = {proof.scope.action_token(owner): {"channels": (("location", (0., 0., 0.)),), "rna": (), "collections": ()}}
    writes = []
    creation.collection = NS(objects=NS(link=lambda _: writes.append(True)))
    original_copy = proof.deepcopy

    def copy(value):
        result = original_copy(value)
        flags.stop("deadline")
        return result

    if operation == "allocate":
        flags.stop("deadline")
        def call():
            return creation.allocate(lambda: writes.append(True))
    else:
        monkeypatch.setattr(proof, "deepcopy", copy)
        def call():
            return creation.assign(owner, "location", (1., 2., 3.)) if operation == "assign" else creation.link(owner)
    with pytest.raises(registry.BridgeError):
        call()
    assert not writes and owner.location == (0., 0., 0.)
