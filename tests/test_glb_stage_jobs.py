"""Pure native-boundary models; actual Runtime TCP/native proof is separate."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def modules(addon_package):
    return tuple(importlib.import_module(addon_package + "." + name)
                 for name in ("glb_stage_jobs", "glb_stage_driver", "glb_stage_profile"))


def test_constructor_ref_escrow_precedes_stop_and_any_dependent_read(modules):
    _jobs, driver, profile = modules
    events, stage, returned = [], object(), object()
    escrow = driver._ReturnEscrow(stage, "NEW_MESH", "mesh:0", ("mesh:0",))
    stop = [False]

    class Gate:
        def check(self):
            events.append("pure stop")
            if stop[0]:
                assert escrow.references["mesh:0"] is returned
                raise profile.refused("MODEL_STOP_AFTER_REAL_RETURN")

    operations = NS(_blender=lambda: None, _entries=[], _runtime_gate=Gate(), _pending=escrow,
                    _operation="NEW_MESH", _role="mesh:0")

    def constructor():
        events.append("C model")
        stop[0] = True
        return returned

    with pytest.raises(profile.BridgeError):
        driver.NativeOperations._entry(operations, "meshes.new", constructor, capture_role="mesh:0")
    assert events == ["pure stop", "C model", "pure stop"]
    assert escrow.drain(stage, "NEW_MESH", "mesh:0") == {"mesh:0": returned}
    assert operations._entries[0]["entered"] is True
    assert operations._entries[0]["returned"] is True
    assert operations._entries[0]["post_return_stop_checked"] is False


@pytest.mark.parametrize("returned", [True, False])
def test_none_return_writes_and_raising_entries_keep_monotonic_attempt_cells(modules, returned):
    _jobs, driver, profile = modules
    events = []
    gate = NS(check=lambda: events.append("pure"))
    operations = NS(_blender=lambda: None, _entries=[], _runtime_gate=gate,
                    _operation="OBJECT_FIELD", _role="object:0")

    def setter():
        events.append("write")
        if not returned:
            raise profile.refused("MODEL_NATIVE_EXCEPTION")
        return None

    if returned:
        assert driver.NativeOperations._entry(operations, "location", setter) is None
    else:
        with pytest.raises(profile.BridgeError):
            driver.NativeOperations._entry(operations, "location", setter)
    cell = operations._entries[0]
    assert cell["index"] == 0 and cell["entered"] is True
    assert cell["returned"] is returned and cell["post_return_stop_checked"] is returned
    assert events == (["pure", "write", "pure"] if returned else ["pure", "write"])


def test_stopped_entry_does_not_invoke_native_function(modules):
    _jobs, driver, profile = modules
    entries: list[dict] = []
    calls: list[bool] = []

    def stopped():
        raise profile.refused("MODEL_STOPPED")

    operations = NS(_blender=lambda: None, _entries=entries, _runtime_gate=NS(check=stopped))
    with pytest.raises(profile.BridgeError):
        driver.NativeOperations._entry(operations, "must not enter", lambda: calls.append(True))
    assert entries == calls == []


def test_embedded_tree_getter_keeps_genuine_return_before_stop(modules):
    _jobs, driver, profile = modules
    stage, tree = object(), object()
    escrow = driver._ReturnEscrow(stage, "NEW_MATERIAL", "material:0", ("node_tree:0",))
    calls = []

    class Gate:
        def check(self):
            calls.append("pure")
            if len(calls) == 2:
                assert escrow.references["node_tree:0"] is tree
                raise profile.refused("MODEL_EMBEDDED_STOP")

        def enter(self, _label): return object()
        def returned(self, _cell): pass

    binding = object.__new__(profile.NativeBinding)
    binding._runtime_gate = Gate()
    with pytest.raises(profile.BridgeError):
        profile.NativeBinding._access(binding, "get:node_tree", lambda: tree,
                                      escrow=escrow, capture_role="node_tree:0")
    assert escrow.references["node_tree:0"] is tree


def test_guarded_existing_observer_stops_before_next_native_component(modules):
    import importlib
    _jobs, _driver, profile = modules
    runtime = importlib.import_module(profile.__package__ + ".glb_stage_runtime")
    events = []

    def access(label, function, *args):
        events.append(label)
        if label == "protected_next" and events.count(label) > 1:
            raise profile.refused("MODEL_STOP_DURING_PROTECTED_COPY")
        return function(*args)

    view = NS(binding=NS(_access=access), wrap=lambda value: value)
    borrowed = runtime._ProtectedValue(view, (1, 2, 3))
    values = iter(borrowed)
    assert next(values) == 1
    with pytest.raises(profile.BridgeError):
        next(values)
    assert events == ["protected_iter", "protected_next", "protected_next"]


@pytest.mark.parametrize("phase,access_source", [("ALLOCATING", True), ("CONSTRUCTED", False), ("PUBLISHING", False)])
def test_retained_controller_uses_fresh_current_turn_grants_not_creator_context(modules, phase, access_source):
    import importlib
    _jobs, _driver, profile = modules
    runtime = importlib.import_module(profile.__package__ + ".glb_stage_runtime")
    events: list[object] = []
    context = NS(require=lambda *permissions: events.append(tuple(p.value for p in permissions)))
    row = NS(gate=NS(context=context, check=lambda: events.append("pure")), root="approved")
    def source_root():
        events.append("source preference")
        return "approved"

    service = NS(retained=lambda _stage: row, store=NS(lookup=lambda _stage: NS(phase=phase)),
                 check_retained=lambda *_args: events.append("current authority"),
                 protected_check=lambda _stage: events.append("protected CAS"),
                 _source_root=source_root)
    runtime.GLBStageService.owned_boundary(service, "stage-model")
    grants = next(item for item in events if type(item) is tuple)
    assert isinstance(grants, tuple)
    assert ("ACCESS_EXTERNAL_FILES" in grants) is access_source
    assert events.index("current authority") < events.index("protected CAS") < len(events)-1
    assert ("source preference" in events) is access_source


def test_guard_precedes_borrowed_native_getitem_method_resolution(modules):
    import importlib
    _jobs, _driver, profile = modules
    runtime = importlib.import_module(profile.__package__ + ".glb_stage_runtime")
    events = []

    class BorrowedView:
        def __getattribute__(self, name):
            if name == "__getitem__":
                events.append("borrowed method lookup")
            return object.__getattribute__(self, name)

        def __getitem__(self, key):
            events.append("native item read")
            return key

    def stopped(*_args):
        events.append("pure stop")
        raise profile.refused("MODEL_STOP_BEFORE_BORROWED_ACCESS")

    proxy = runtime._ProtectedValue(NS(binding=NS(_access=stopped)), BorrowedView())
    with pytest.raises(profile.BridgeError):
        proxy[0]
    assert events == ["pure stop"]
