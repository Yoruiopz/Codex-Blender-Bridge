from __future__ import annotations

import asyncio
import copy
import importlib
import math
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


class CustomOwner(dict):
    """Model an owner that actually supports user IDProperties, without bpy."""

    bl_rna = NS(properties=())


@pytest.mark.parametrize("payload", [False, 17, .375, "artist-owned", [1., 2.], {"revision": 2, "label": "keep"}])
def test_marker_named_custom_property_is_ordinary_preserved_data(domain, payload):
    owner = CustomOwner(_codex_bridge_undo_marker=payload, unrelated="retained")
    proof = domain._Proof().properties(owner)
    assert proof["custom_properties"] == owner
    changed = CustomOwner(owner)
    changed["_codex_bridge_undo_marker"] = "new artist payload"
    assert domain._digest(domain._Proof().properties(changed)) != domain._digest(proof)


@pytest.mark.parametrize("payload", [float("nan"), float("inf"), NS(as_pointer=lambda: 1)])
def test_marker_named_property_cannot_hide_unsupported_native_values(domain, payload):
    with pytest.raises(domain.BridgeError):
        domain._Proof().properties(CustomOwner(_codex_bridge_undo_marker=payload))


def marker_record(captured, owner_kind):
    if owner_kind == "material":
        return captured["owners"][9].setdefault("properties", {})
    if owner_kind == "tree":
        return captured["graphs"][1].setdefault("properties", {})
    if owner_kind == "node":
        return captured["graphs"][2]["nodes"][0].setdefault("properties", {})
    return captured["graphs"][2]["nodes"][0]["inputs"][1]["properties"]


@pytest.mark.parametrize("owner_kind", ["material", "tree", "node", "socket"])
def test_successful_interface_edit_preserves_marker_named_payload(transaction, monkeypatch, owner_kind):
    t = transaction
    owner = CustomOwner(_codex_bridge_undo_marker={"revision": 1, "weights": [.125, .25]})
    capture = t.module._capture

    def captured(*args):
        result, scope = capture(*args)
        marker_record(result, owner_kind).update(t.module._Proof().properties(owner))
        return result, scope

    monkeypatch.setattr(t.module, "_capture", captured)
    original, _scope = captured()
    plan = t.module._plan(None, None)
    params = {**t.params, "expected_fingerprint": t.module._digest({"state": original, "plan": plan})}
    result = t.module.edit(t.context, params)
    assert result["protected_graph_state_preserved"] and t.writes == ["forward"]
    assert captured()[0] == t.module._project(original, 1, plan)
    assert owner["_codex_bridge_undo_marker"] == {"revision": 1, "weights": [.125, .25]}


@pytest.mark.parametrize("owner_kind", ["material", "tree", "node", "socket"])
@pytest.mark.parametrize("after_write", [False, True])
def test_grant_provider_marker_drift_blocks_writes_and_inverse_compensation(transaction, monkeypatch, owner_kind, after_write):
    t = transaction
    permissions = importlib.import_module(t.module.__name__.rsplit(".tools.", 1)[0]+".permissions")
    marker = "_codex_bridge_undo_marker"
    owner = CustomOwner({marker: {"revision": 1, "label": "artist-owned"}})
    boundary = {"prepared": False, "written": False, "poisoned": False}
    capture = t.module._capture

    def captured(*args):
        result, scope = capture(*args)
        marker_record(result, owner_kind).update(t.module._Proof().properties(owner))
        boundary["prepared"] = True
        return result, scope

    monkeypatch.setattr(t.module, "_capture", captured)
    original, _scope = captured()
    params = {**t.params, "expected_fingerprint": t.module._digest({"state": original, "plan": t.module._plan(None, None)})}
    boundary["prepared"] = False
    primary = t.module.BridgeError("OPERATION_FAILED", "Original failure after completed interface assignment")

    def provider():
        if not boundary["poisoned"] and (boundary["written"] if after_write else boundary["prepared"]):
            boundary["poisoned"] = True
            owner[marker] = {"revision": 2, "label": "manual protected edit"}
        return {"INSPECT_SCENE": True, "EDIT_MATERIALS": True}

    manager = permissions.PermissionManager(provider)
    t.context.require = lambda *required: manager.require(required)

    def written_then_failed(tree, plan, *, inverse=False):
        t.write(tree, plan, inverse=inverse)
        boundary["written"] = True
        raise primary

    if after_write:
        monkeypatch.setattr(t.module, "_write", written_then_failed)
    with pytest.raises(t.module.BridgeError) as caught:
        t.module.edit(t.context, params)
    error = caught.value
    assert boundary["poisoned"]
    assert t.writes == (["forward"] if after_write else [])
    assert error.context["possible_mutation"] is after_write
    assert error.context["rollback_verified"] is not after_write
    assert owner[marker] == {"revision": 2, "label": "manual protected edit"}
    assert t.current["graphs"][1]["interface"][0]["properties"]["default_value"] == (.75 if after_write else .25)
    if after_write:
        assert error.code == primary.code and error.__cause__ is primary
    else:
        assert error.code == "INVALID_ARGUMENT"


@pytest.fixture
def canonical_transaction(transaction):
    t = transaction
    package = t.module.__name__.rsplit(".tools.", 1)[0]
    registry_module = importlib.import_module(package+".tool_registry")
    permissions = importlib.import_module(package+".permissions")
    state_module = importlib.import_module(package+".state")
    t.context = registry_module.ToolContext(state_module.BridgeState(),
        permissions.PermissionManager(lambda: {"INSPECT_SCENE": True, "EDIT_MATERIALS": True}),
        t.context.registry, NS())
    return t


@pytest.mark.parametrize("initial,replacement", [(True, 1), (1, 1.), (0., -0.),
    ({"values": [True]}, {"values": [1]})])
@pytest.mark.parametrize("phase", ["before", "verification", "compensation"])
def test_canonical_provider_typed_drift_cannot_pass_cas_or_compensation(canonical_transaction, monkeypatch, initial, replacement, phase):
    t = canonical_transaction
    after_write = phase != "before"
    permissions = importlib.import_module(t.module.__name__.rsplit(".tools.", 1)[0]+".permissions")
    marker = "_codex_bridge_undo_marker"
    owner = CustomOwner({marker: copy.deepcopy(initial)})
    capture = t.module._capture
    boundary = {"prepared": False, "written": False, "poisoned": False}
    assert initial == replacement and t.module._digest(initial) != t.module._digest(replacement)

    def captured(*args):
        result, scope = capture(*args)
        marker_record(result, "node").update(t.module._Proof().properties(owner))
        boundary["prepared"] = True
        return result, scope

    monkeypatch.setattr(t.module, "_capture", captured)
    original, _scope = captured()
    params = {**t.params, "expected_fingerprint": t.module._digest({"state": original, "plan": t.module._plan(None, None)})}
    boundary["prepared"] = False
    primary = t.module.BridgeError("OPERATION_FAILED", "Original failure before typed drift in compensation")

    def provider():
        if not boundary["poisoned"] and (boundary["written"] if after_write else boundary["prepared"]):
            owner[marker] = copy.deepcopy(replacement)
            boundary["poisoned"] = True
        return {"INSPECT_SCENE": True, "EDIT_MATERIALS": True}

    t.context.permissions = permissions.PermissionManager(provider)

    def owned_write(tree, plan, *, inverse=False):
        t.write(tree, plan, inverse=inverse)
        boundary["written"] = True
        if not inverse and phase == "compensation":
            raise primary

    if after_write:
        monkeypatch.setattr(t.module, "_write", owned_write)
    with pytest.raises(t.module.BridgeError) as caught:
        t.context.registry.dispatch("shader_group.interface_edit", params, t.context)
    assert boundary["poisoned"]
    assert t.writes == (["forward"] if after_write else [])
    assert caught.value.context["possible_mutation"] is after_write
    assert caught.value.context["rollback_verified"] is not after_write
    assert t.module._digest(owner[marker]) == t.module._digest(replacement)
    assert t.current["graphs"][1]["interface"][0]["properties"]["default_value"] == (.75 if after_write else .25)
    if phase == "compensation":
        assert caught.value.code == primary.code and caught.value.__cause__ is primary
    elif phase == "before":
        assert caught.value.code == "INVALID_ARGUMENT"
    else:
        assert caught.value.code == "OPERATION_FAILED"
        assert "propagation changed protected state" in caught.value.__cause__.message


@pytest.mark.parametrize("initial,desired", [(0., -0.), (-0., 0.)])
def test_default_plan_retains_requested_zero_sign(domain, initial, desired):
    target = tree()
    target.interface.items_tree[0].default_value = initial
    plan = domain._plan(target, {"operation": "SET_DEFAULT", "socket_identifier": "a", "value": desired})
    assert math.copysign(1., plan["before"]) == math.copysign(1., initial)
    assert math.copysign(1., plan["value"]) == math.copysign(1., desired)


@pytest.mark.parametrize("initial,desired,changed", [(0., -0., True), (-0., 0., True),
    (0., 0., False), (-0., -0., False)])
def test_zero_sign_edit_and_exact_noop_read_back_actual_state(canonical_transaction, monkeypatch, initial, desired, changed):
    t = canonical_transaction
    t.current["graphs"][1]["interface"][0]["properties"]["default_value"] = initial
    plan = {"operation": "SET_DEFAULT", "socket_identifier": "a", "in_out": "INPUT", "before": initial, "value": desired}
    monkeypatch.setattr(t.module, "_plan", lambda *_args: plan.copy())
    before = copy.deepcopy(t.current)
    params = {**t.params, "value": desired, "expected_fingerprint": t.module._digest({"state": before, "plan": plan})}
    result = t.context.registry.dispatch("shader_group.interface_edit", params, t.context)
    assert result["changed"] is changed
    assert t.writes == (["forward"] if changed else [])
    actual = t.current["graphs"][1]["interface"][0]["properties"]["default_value"]
    assert math.copysign(1., actual) == math.copysign(1., desired)
    assert t.module._digest(t.current) == t.module._digest(t.module._project(before, 1, plan))


@pytest.mark.parametrize("inverse_preserves_sign", [False, True])
def test_zero_sign_rollback_requires_exact_actual_readback(canonical_transaction, monkeypatch, inverse_preserves_sign):
    t = canonical_transaction
    t.current["graphs"][1]["interface"][0]["properties"]["default_value"] = -0.
    plan = {"operation": "SET_DEFAULT", "socket_identifier": "a", "in_out": "INPUT", "before": -0., "value": 0.}
    monkeypatch.setattr(t.module, "_plan", lambda *_args: plan.copy())
    before = copy.deepcopy(t.current)
    params = {**t.params, "value": 0., "expected_fingerprint": t.module._digest({"state": before, "plan": plan})}
    primary = t.module.BridgeError("OPERATION_FAILED", "Original zero-sign native assignment failure")

    def owned_write(tree, operation, *, inverse=False):
        t.write(tree, operation, inverse=inverse)
        if not inverse:
            raise primary
        if not inverse_preserves_sign:
            t.current["graphs"][1]["interface"][0]["properties"]["default_value"] = 0.

    monkeypatch.setattr(t.module, "_write", owned_write)
    with pytest.raises(t.module.BridgeError) as caught:
        t.context.registry.dispatch("shader_group.interface_edit", params, t.context)
    assert t.writes == ["forward", "inverse"]
    assert caught.value.__cause__ is primary
    assert caught.value.context["rollback_verified"] is inverse_preserves_sign
    assert caught.value.context["possible_mutation"] is not inverse_preserves_sign
    assert (t.module._digest(t.current) == t.module._digest(before)) is inverse_preserves_sign


@pytest.mark.parametrize("initial,desired", [(0., -0.), (-0., 0.)])
def test_zero_sign_native_normalization_cannot_report_success(canonical_transaction, monkeypatch, initial, desired):
    t = canonical_transaction
    t.current["graphs"][1]["interface"][0]["properties"]["default_value"] = initial
    plan = {"operation": "SET_DEFAULT", "socket_identifier": "a", "in_out": "INPUT", "before": initial, "value": desired}
    monkeypatch.setattr(t.module, "_plan", lambda *_args: plan.copy())
    before = copy.deepcopy(t.current)
    params = {**t.params, "value": desired, "expected_fingerprint": t.module._digest({"state": before, "plan": plan})}

    def normalize_sign(tree, operation, *, inverse=False):
        t.write(tree, operation, inverse=inverse)
        t.current["graphs"][1]["interface"][0]["properties"]["default_value"] = initial

    monkeypatch.setattr(t.module, "_write", normalize_sign)
    with pytest.raises(t.module.BridgeError) as caught:
        t.context.registry.dispatch("shader_group.interface_edit", params, t.context)
    assert t.writes == ["forward"]
    assert caught.value.context["rollback_verified"] is True
    assert caught.value.context["possible_mutation"] is False
    assert t.module._digest(t.current) == t.module._digest(before)


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
