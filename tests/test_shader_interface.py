from __future__ import annotations

import asyncio
import copy
import importlib
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.shader_interface import ShaderInterfaceTools, load_definitions


@pytest.fixture
def domain(addon_package):
    return importlib.import_module(addon_package+".tools.shader_interface")


def item(identifier="a", name="First", kind="NodeSocketFloat", default=.25, direction="INPUT"):
    return NS(identifier=identifier, name=name, socket_type=kind, default_value=default,
        in_out=direction, item_type="SOCKET", bl_rna=NS(properties={"default_value": NS(hard_min=-1e6, hard_max=1e6)}))


def tree():
    return NS(interface=NS(items_tree=[item(), item("b", "Second"), item("s", "Shader", "NodeSocketShader", None, "OUTPUT")]))


def test_metadata_native_and_mcp_match(domain, addon_package):
    registry = importlib.import_module(addon_package+".tool_registry").ToolRegistry()
    domain.register_tools(registry)
    for definition in load_definitions():
        spec = registry.get(definition.name)
        assert spec.modifies == definition.modifying
        assert {p.value for p in spec.permissions} == set(definition.required_permissions)
        assert spec.toolset == "nodes"
    assert not registry.get("shader_group.interface_edit").batchable
    assert registry.get("shader_group.interface_edit").automatic_checkpoint


@pytest.mark.parametrize("field,value", [("operation", "CONVERT"), ("to_index", True),
    ("to_index", 128), ("new_name", ""), ("expected_fingerprint", "guessed"),
    ("allow_shared", 1), ("value", [0, 1]), ("value", [True, 0, 1])])
def test_wrapper_strict_types(field, value):
    annotation = get_type_hints(ShaderInterfaceTools.shader_group_interface_edit, include_extras=True)[field]
    with pytest.raises(ValidationError):
        TypeAdapter(annotation).validate_python(value)


def test_wrapper_forwards_operation_and_exact_cas():
    calls = []

    async def call(name, params):
        calls.append((name, params))
        return {}

    tools = ShaderInterfaceTools(NS(call=call))
    asyncio.run(tools.shader_group_interface_preview("Leaf", "a", "MOVE", to_index=1))
    asyncio.run(tools.shader_group_interface_edit("Leaf", "a", "SET_DEFAULT", "f"*64, value=.75, allow_shared=True))
    assert calls == [("shader_group.interface_preview", {"group_name": "Leaf", "socket_identifier": "a", "operation": "MOVE", "to_index": 1}),
        ("shader_group.interface_edit", {"group_name": "Leaf", "socket_identifier": "a", "operation": "SET_DEFAULT",
            "expected_fingerprint": "f"*64, "value": .75, "allow_shared": True})]


@pytest.mark.parametrize("operation,extra", [("CONVERT", {}), ([], {}),
    ("RENAME", {"new_name": "Second"}), ("MOVE", {"to_index": True}), ("MOVE", {"to_index": 2}),
    ("SET_DEFAULT", {"value": True}), ("SET_DEFAULT", {"value": float("nan")}),
    ("SET_DEFAULT", {"value": 10**1000})])
def test_plan_rejects_conversion_ambiguity_and_unbounded_values(domain, operation, extra):
    with pytest.raises(domain.BridgeError):
        domain._plan(tree(), {"operation": operation, "socket_identifier": "a", **extra})


@pytest.mark.parametrize("kind,value", [("NodeSocketBool", 1), ("NodeSocketInt", True),
    ("NodeSocketInt", 2**31), ("NodeSocketVector", [0, 1]), ("NodeSocketColor", [0, 1, 0, True]),
    ("NodeSocketShader", 0)])
def test_native_default_types_remain_strict(domain, kind, value):
    target = tree()
    target.interface.items_tree[0].socket_type = kind
    with pytest.raises(domain.BridgeError):
        domain._plan(target, {"operation": "SET_DEFAULT", "socket_identifier": "a", "value": value})


def test_native_default_range_checked_before_assignment(domain):
    target = tree()
    target.interface.items_tree[0].bl_rna.properties["default_value"].hard_max = 1
    with pytest.raises(Exception, match="native component range"):
        domain._plan(target, {"operation": "SET_DEFAULT", "socket_identifier": "a", "value": 2})


def state():
    interface = [{"identifier": ident, "in_out": "INPUT", "type": "NodeSocketFloat", "properties": {"name": name, "default_value": default}}
        for ident, name, default in (("a", "First", .25), ("b", "Second", .6))]

    def socket(ident, name, default):
        return {"identifier": ident, "type": "NodeSocketFloat", "properties": {"name": name, "default_value": default}, "linked": False}

    return {"target": [1, 7], "context": {"mode": "OBJECT"}, "owners": {9: {"identity": [9, 8]}},
        "graphs": {1: {"identity": [1, 7], "interface": interface,
            "nodes": [{"type": "NodeGroupInput", "group": None, "inputs": [],
                "outputs": [socket("a", "First", 0.), socket("b", "Second", 0.)]}]},
            2: {"identity": [2, 8], "interface": [], "nodes": [{"type": "ShaderNodeGroup", "group": 1,
                "inputs": [socket("a", "First", .9), socket("b", "Second", .3)], "outputs": []}]}}}


def test_default_projection_never_masks_existing_instance_or_group_input_defaults(domain):
    before = state()
    plan = {"operation": "SET_DEFAULT", "socket_identifier": "a", "value": .75}
    after = domain._project(before, 1, plan)
    assert after["graphs"][1]["interface"][0]["properties"]["default_value"] == .75
    assert after["graphs"][1]["nodes"] == before["graphs"][1]["nodes"]
    assert after["graphs"][2] == before["graphs"][2]
    assert before == state()


def test_reorder_projection_tracks_actual_identifiers_and_defaults(domain):
    before = state()
    before["graphs"][1].update(active_interface_identifier="a", interface_properties={"active_index": 0})
    after = domain._project(before, 1, {"operation": "MOVE", "socket_identifier": "a", "value": 1})
    assert [v["identifier"] for v in after["graphs"][1]["interface"]] == ["b", "a"]
    assert [v["identifier"] for v in after["graphs"][1]["nodes"][0]["outputs"]] == ["b", "a"]
    assert [v["properties"]["default_value"] for v in after["graphs"][2]["nodes"][0]["inputs"]] == [.3, .9]
    assert after["owners"] == before["owners"]
    assert after["graphs"][1]["active_interface_identifier"] == "a"
    assert after["graphs"][1]["interface_properties"]["active_index"] == 1


def test_fingerprint_binds_entire_scope_and_operation(domain):
    baseline = {"state": state(), "plan": {"operation": "MOVE", "value": 1}}
    fingerprint = domain._digest(baseline)
    changed = copy.deepcopy(baseline)
    changed["state"]["graphs"][2]["nodes"][0]["inputs"][1]["properties"]["default_value"] = .4
    assert domain._digest(changed) != fingerprint
    changed = copy.deepcopy(baseline)
    changed["plan"]["value"] = 0
    assert domain._digest(changed) != fingerprint


@pytest.fixture
def transaction(domain, monkeypatch):
    current = state()
    flags, writes, hooks = {}, [], []
    target = NS(session_uid=7)
    scope = {"requires_shared_consent": True, "affected_objects": ["Shared A", "Shared B"]}
    registry = importlib.import_module(domain.__name__.rsplit(".tools.", 1)[0]+".tool_registry").ToolRegistry(enabled_toolsets=("nodes",))
    domain.register_tools(registry)
    context = NS(require=lambda *p: [hook() for hook in hooks], state=NS(snapshot=lambda: flags.copy()),
        registry=registry, check_cancelled=None, request_lifecycle=None)
    plan = {"operation": "SET_DEFAULT", "socket_identifier": "a", "in_out": "INPUT", "before": .25, "value": .75}
    bpy = NS()
    original = copy.deepcopy(current)
    monkeypatch.setattr(domain, "datablock_identity", lambda obj: 1)
    monkeypatch.setattr(domain, "require_blender", lambda: bpy)
    monkeypatch.setattr(domain.shader_scope, "group_exact", lambda *a: target)
    monkeypatch.setattr(domain, "_capture", lambda *a: (copy.deepcopy(current), copy.deepcopy(scope)))
    monkeypatch.setattr(domain, "_plan", lambda *a: plan.copy())

    def write(tree, p, *, inverse=False):
        writes.append("inverse" if inverse else "forward")
        current["graphs"][1]["interface"][0]["properties"]["default_value"] = p["before"] if inverse else p["value"]

    monkeypatch.setattr(domain, "_write", write)
    params = {"group_name": "Leaf", "socket_identifier": "a", "operation": "SET_DEFAULT", "value": .75, "allow_shared": True,
        "expected_fingerprint": domain._digest({"state": original, "plan": plan})}
    return NS(module=domain, context=context, params=params, current=current, flags=flags, writes=writes,
        hooks=hooks, original=original, scope=scope, target=target, write=write)


def test_success_compares_exact_post_state(transaction):
    t = transaction
    assert t.module.edit(t.context, t.params)["protected_graph_state_preserved"]
    assert t.writes == ["forward"]


def test_cancel_before_write_has_no_mutation(transaction):
    t = transaction
    t.context.check_cancelled = lambda: (_ for _ in ()).throw(RuntimeError("Canceled caller"))
    with pytest.raises(RuntimeError, match="Canceled caller"):
        t.module.edit(t.context, t.params)
    assert not t.writes and t.current == t.original


def test_cancel_after_owned_write_refuses_new_recovery_writes(transaction, monkeypatch):
    t = transaction

    def write_and_cancel(tree, plan, *, inverse=False):
        t.write(tree, plan, inverse=inverse)
        t.context.check_cancelled = lambda: (_ for _ in ()).throw(RuntimeError("Caller disconnected/canceled"))

    monkeypatch.setattr(t.module, "_write", write_and_cancel)
    with pytest.raises(t.module.BridgeError) as caught:
        t.module.edit(t.context, t.params)
    assert not caught.value.context["rollback_verified"] and caught.value.context["possible_mutation"]
    assert t.writes == ["forward"]
    assert t.current["graphs"][1]["interface"][0]["properties"]["default_value"] == .75


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("signal", ["toolset", "queued_cancel", "queued_expiry", "disconnect", "handoff_rejected"])
def test_last_grant_provider_cannot_restore_or_write_after_authority_loss(transaction, monkeypatch, addon_package, recovery, signal):
    t = transaction
    permissions = importlib.import_module(addon_package+".permissions")
    queue = importlib.import_module(addon_package+".command_queue")
    protocol = importlib.import_module(addon_package+".protocol")
    lifetimes = importlib.import_module(addon_package+".request_lifecycle")
    lifetime = lifetimes.RequestLifetime(lifetimes.ConnectionLifetime())
    queued = queue.QueuedRequest(protocol.Request(id="shader-canonical", method="shader_group.interface_edit", params=t.params))
    assert queued.try_start()
    t.context.check_cancelled, t.context.request_lifecycle = queued.check_active, lifetime
    boundary = {"prepared": False, "written": False, "poisoned": False}
    capture = t.module._capture

    def captured(*args):
        result = capture(*args)
        boundary["prepared"] = True
        return result

    def provider():
        if not boundary["poisoned"] and (boundary["written"] if recovery else boundary["prepared"]):
            boundary["poisoned"] = True
            if signal == "toolset":
                t.context.registry.disable_toolset("nodes")
            elif signal == "queued_cancel":
                queued.cancel_pending(t.module.BridgeError("TIMEOUT", "Canonical caller canceled"))
            elif signal == "queued_expiry":
                queued.deadline = 0
            elif signal == "disconnect":
                lifetime.connection.disconnected.set()
            else:
                lifetime.acknowledge(False)
        return {"INSPECT_SCENE": True, "EDIT_MATERIALS": True}

    manager = permissions.PermissionManager(provider)
    t.context.require = lambda *p: manager.require(p)

    def failed_native_write(tree, plan, *, inverse=False):
        t.write(tree, plan, inverse=inverse)
        boundary["written"] = True
        raise RuntimeError("Injected after complete native assignment; compensation authority must be fresh")

    monkeypatch.setattr(t.module, "_capture", captured)
    if recovery:
        monkeypatch.setattr(t.module, "_write", failed_native_write)
    with pytest.raises(t.module.BridgeError) as caught:
        t.module.edit(t.context, t.params)
    assert boundary["poisoned"]
    assert t.writes == (["forward"] if recovery else [])
    assert caught.value.context["possible_mutation"] == recovery
    assert caught.value.context["rollback_verified"] != recovery
    assert t.current["graphs"][1]["interface"][0]["properties"]["default_value"] == (.75 if recovery else .25)


@pytest.mark.parametrize("extra", [{"to_index": 0}, {"new_name": "Unrelated"}, {"allow_shared": "yes"}])
def test_irrelevant_parameters_and_shared_consent_rejected_before_write(transaction, extra):
    t = transaction
    with pytest.raises(t.module.BridgeError):
        t.module.edit(t.context, {**t.params, **extra})
    assert not t.writes


@pytest.mark.parametrize("signal", ["paused", "emergency_stopped", "mode", "protected", "owners", "identity"])
def test_granting_provider_changes_live_state_before_write_fail_closed(transaction, signal):
    t = transaction
    calls = [0]

    def provider():
        calls[0] += 1
        if calls[0] != 2:
            return
        if signal in {"paused", "emergency_stopped"}:
            t.flags[signal] = True
        elif signal == "mode":
            t.current["context"]["mode"] = "EDIT_MESH"
        elif signal == "protected":
            t.current["graphs"][2]["nodes"][0]["inputs"][1]["properties"]["default_value"] = .4
        elif signal == "owners":
            t.scope["affected_objects"].append("Acquired Consumer")
        else:
            t.target.session_uid = 99

    t.hooks.append(provider)
    with pytest.raises(t.module.BridgeError):
        t.module.edit(t.context, t.params)
    assert not t.writes
    assert t.current["graphs"][1]["interface"][0]["properties"]["default_value"] == .25


def test_failure_after_owned_output_compensates_and_measures(transaction, monkeypatch):
    t = transaction
    calls = [0]
    capture = t.module._capture

    def fail_once(*args):
        calls[0] += 1
        if calls[0] == 3:
            raise RuntimeError("Injected verification failure after native write")
        return capture(*args)

    monkeypatch.setattr(t.module, "_capture", fail_once)
    with pytest.raises(Exception) as caught:
        t.module.edit(t.context, t.params)
    assert caught.value.context["rollback_verified"]
    assert t.writes == ["forward", "inverse"] and t.current == t.original


@pytest.mark.parametrize("signal", ["paused", "emergency_stopped", "mode", "protected", "identity", "permission"])
def test_compensation_refuses_lost_consent_context_and_unknown_changes(transaction, monkeypatch, signal):
    t = transaction

    def corrupt_after_write(tree, plan, *, inverse=False):
        t.write(tree, plan, inverse=inverse)
        if signal in {"paused", "emergency_stopped"}:
            t.flags[signal] = True
        elif signal == "mode":
            t.current["context"]["mode"] = "EDIT_MESH"
        elif signal == "protected":
            t.current["graphs"][2]["nodes"][0]["inputs"][1]["properties"]["default_value"] = .4
        elif signal == "identity":
            t.target.session_uid = 99
        else:
            t.context.require = lambda *p: (_ for _ in ()).throw(RuntimeError("Permission withdrawn"))

    monkeypatch.setattr(t.module, "_write", corrupt_after_write)
    with pytest.raises(Exception) as caught:
        t.module.edit(t.context, t.params)
    assert caught.value.context["possible_mutation"] and not caught.value.context["rollback_verified"]
    assert t.writes == ["forward"]


@pytest.mark.parametrize("flag", ["paused", "emergency_stopped"])
def test_read_only_gate_remains_available_with_stop_flags(domain, flag):
    domain._gate(NS(require=lambda *p: None, check_cancelled=None, request_lifecycle=None,
        registry=NS(enabled_toolsets=("nodes",)), state=NS(snapshot=lambda: {flag: True})))


def test_proof_rejects_custom_native_pointer_before_keys(domain):
    with pytest.raises(Exception, match="native references"):
        domain._Proof().value(NS(as_pointer=lambda: 1, keys=lambda: []))


def test_animation_rejected_even_empty_native_container(domain):
    with pytest.raises(Exception, match="unanimated"):
        domain._unanimated(NS(animation_data=NS(action=None)))


@pytest.mark.parametrize("changes", [{"library": object()}, {"override_library": object()}, {"is_editable": False}])
def test_local_scope_rejects_linked_override_and_read_only_owners(domain, changes):
    owner = NS(library=None, override_library=None, is_editable=True, animation_data=None)
    owner.__dict__.update(changes)
    with pytest.raises(domain.BridgeError, match="local editable"):
        domain._local(owner)


@pytest.mark.parametrize("value", ["x"*4097, list(range(65)), dict.fromkeys(map(str, range(129)), 0)])
def test_proof_rejects_unsupported_or_unbounded_native_values(domain, value):
    with pytest.raises(domain.BridgeError):
        domain._Proof().value(value)
