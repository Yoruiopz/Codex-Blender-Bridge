from __future__ import annotations

import asyncio
import importlib
from copy import deepcopy
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.shader_settings import RampStop, ShaderSettingsTools


def prop(kind, *identifiers, length=0, minimum=0, maximum=1_000_000):
    return NS(type=kind, is_readonly=False, is_enum_flag=False, array_length=length,
              hard_min=minimum, hard_max=maximum, enum_items=[NS(identifier=i) for i in identifiers])


class Items(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)


class Elements(list):
    fail_times = 0

    def new(self, position):
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("injected allocation failure")
        element = NS(position=position, color=[0., 0., 0., 1.])
        self.append(element)
        self.sort(key=lambda item: item.position)
        return element


def make_ramp():
    properties = {"interpolation": prop("ENUM", "LINEAR", "CONSTANT", "EASE"),
                  "color_mode": prop("ENUM", "RGB", "HSV", "HSL"),
                  "hue_interpolation": prop("ENUM", "NEAR", "FAR", "CW", "CCW")}
    element_rna = NS(properties={"color": prop("FLOAT", length=4),
                                "position": prop("FLOAT", maximum=1)})
    elements = Elements([NS(position=0., color=[0., 0., 0., 1.], bl_rna=element_rna),
                         NS(position=1., color=[1., 1., 1., 1.], bl_rna=element_rna)])
    return NS(elements=elements, interpolation="LINEAR", color_mode="RGB", hue_interpolation="NEAR",
              bl_rna=NS(properties=properties), evaluate=lambda position: [position, 0., 0., 1.])


def make_node(name, kind):
    socket = NS(identifier="Value", bl_idname="NodeSocketFloat", default_value=.5)
    socket.as_pointer = lambda: id(socket)
    node = NS(name=name, bl_idname=kind, inputs=[socket], outputs=[], mute=False,
              bl_rna=NS(properties={"operation": prop("ENUM", "ADD", "MULTIPLY"),
                                   "use_clamp": prop("BOOLEAN")}), operation="ADD", use_clamp=False)
    if kind == "ShaderNodeValToRGB":
        node.color_ramp = make_ramp()
    return node


@pytest.fixture
def shader_settings(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.shader_settings")
    math, ramp = make_node("Math", "ShaderNodeMath"), make_node("Ramp", "ShaderNodeValToRGB")
    tree = NS(name="Tree", nodes=Items([math, ramp]), links=[], animation_data=None)
    material = NS(name="Material", node_tree=tree, animation_data=None, use_nodes=True, library=None)
    bpy = NS(context=NS(mode="OBJECT"))
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module.nodes, "_target_graph", lambda *args, **kwargs: (material, tree))
    monkeypatch.setattr(module.nodes, "_post_state", lambda _m, _t, n: {"node": module.node_state(n)})
    context = NS(check_cancelled=None)
    return module, context, material, tree, math, ramp, bpy


def params(node="Ramp", **extra):
    return {"material_name": "Material", "node_name": node, **extra}


STOPS = [{"position": 0., "color": [2., .5, 0., 1.]},
         {"position": .5, "color": [0., 1., .5, 1.]},
         {"position": .5, "color": [.5, 0., 1., 1.]}]


def test_complete_ramp_revision_preserves_ordered_ties_hdr_and_defaults(shader_settings):
    module, context, _, _, _, ramp, _ = shader_settings
    result = module.set_color_ramp(context, params(stops=STOPS, color_mode="HSV", hue_interpolation="FAR"))
    state = result["node"]["color_ramp"]
    assert [item["position"] for item in state["elements"]] == [0., .5, .5]
    assert [item["color"] for item in state["elements"]] == [stop["color"] for stop in STOPS]
    assert state["color_mode"] == "HSV" and state["hue_interpolation"] == "FAR"
    assert state["effective_interpolation"] == "LINEAR" and not state["interpolation_active"]
    assert state["hue_interpolation_active"]
    assert ramp.inputs[0].default_value == .5 and result["links_and_socket_defaults_preserved"]
    module.set_color_ramp(context, params(stops=STOPS[:1]))
    assert len(ramp.color_ramp.elements) == 1


@pytest.mark.parametrize("extra", [
    {"stops": []}, {"stops": STOPS * 11}, {"stops": [True]},
    {"stops": [{"position": True, "color": [0, 0, 0, 1]}]},
    {"stops": [{"position": -.1, "color": [0, 0, 0, 1]}]},
    {"stops": [{"position": 0, "color": [float("nan"), 0, 0, 1]}]},
    {"stops": [{"position": 0, "color": [-1, 0, 0, 1]}]},
    {"stops": [{"position": 0, "color": [1e7, 0, 0, 1]}]},
    {"stops": [{"position": 0, "color": [False, 0, 0, 1]}]},
    {"stops": [{"position": 0, "color": [0, 0, 0]}]},
    {"stops": [{"position": 0, "color": [0, 0, 0, 1], "extra": 1}]},
    {"stops": list(reversed(STOPS))},
    {"stops": STOPS, "interpolation": "NOT_NATIVE"},
    {"stops": STOPS, "settings": {"image": "Forbidden"}},
])
def test_ramp_invalid_arguments_do_not_touch_existing_state(shader_settings, extra):
    module, context, _, _, _, ramp, _ = shader_settings
    before = module.ramp_state(ramp.color_ramp)
    with pytest.raises(module.BridgeError) as caught:
        module.set_color_ramp(context, params(**extra))
    assert caught.value.code == "INVALID_ARGUMENT"
    assert module.ramp_state(ramp.color_ramp) == before


@pytest.mark.parametrize("fail_times,verified", [(1, True), (10, False)])
def test_partial_ramp_failures_measure_restoration_instead_of_claiming_it(shader_settings, fail_times, verified):
    module, context, _, _, _, ramp, _ = shader_settings
    before = module.ramp_state(ramp.color_ramp)
    ramp.color_ramp.elements.fail_times = fail_times
    with pytest.raises(module.BridgeError) as caught:
        module.set_color_ramp(context, params(stops=STOPS))
    assert caught.value.context["rollback_verified"] is verified
    assert caught.value.context["possible_mutation"] is not verified
    assert caught.value.context["before_color_ramp"] == before
    if verified:
        assert module.ramp_state(ramp.color_ramp) == before


def test_properties_are_prevalidated_and_native_settings_are_inspectable(shader_settings):
    module, context, _, _, math, _, _ = shader_settings
    with pytest.raises(module.BridgeError):
        module.set_properties(context, params("Math", settings={"operation": "MULTIPLY", "use_clamp": "yes"}))
    assert math.operation == "ADD"
    result = module.set_properties(context, params("Math", settings={"operation": "MULTIPLY", "use_clamp": True}))
    assert result["node"]["settings"] == {"operation": "MULTIPLY", "use_clamp": True}
    inspected = module.inspect_properties(context, params("Math"))
    assert inspected["editable_settings"]["operation"]["identifiers"] == ["ADD", "MULTIPLY"]


@pytest.mark.parametrize("settings", [{}, {"image": "Forbidden"}, {"filepath": "D:/secret"},
                                      {"operation": "UNKNOWN"}, {"operation.value": 1},
                                      {"use_clamp": 1}, {"operation": None}])
def test_unreviewed_or_malformed_properties_never_mutate(shader_settings, settings):
    module, context, _, _, math, _, _ = shader_settings
    with pytest.raises(module.BridgeError):
        module.set_properties(context, params("Math", settings=settings))
    assert math.operation == "ADD" and math.use_clamp is False


def test_runtime_socket_side_effects_are_not_hidden_by_property_rollback(shader_settings, monkeypatch):
    module, context, _, _, math, _, _ = shader_settings
    original = module.apply_assignments
    attempts = 0

    def side_effect(owner, assignments):
        nonlocal attempts
        attempts += 1
        original(owner, assignments)
        if attempts == 1:
            math.inputs[0].default_value = .75

    monkeypatch.setattr(module, "apply_assignments", side_effect)
    with pytest.raises(module.BridgeError) as caught:
        module.set_properties(context, params("Math", settings={"operation": "MULTIPLY"}))
    assert math.operation == "ADD" and math.inputs[0].default_value == .75
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert not caught.value.context["rollback_verified"] and caught.value.context["possible_mutation"]


@pytest.mark.parametrize("owner_index", [2, 3])
def test_animated_owners_are_explicitly_unsupported(shader_settings, owner_index):
    module, context, *_ = shader_settings
    shader_settings[owner_index].animation_data = NS(action=object(), drivers=[], nla_tracks=[])
    with pytest.raises(module.BridgeError) as caught:
        module.set_color_ramp(context, params(stops=STOPS))
    assert caught.value.code == "NOT_IMPLEMENTED"


def test_samples_and_mode_gates_are_bounded(shader_settings):
    module, context, _, _, _, ramp, bpy = shader_settings
    result = module.inspect_properties(context, params(sample_positions=[0, .5, 1]))
    assert [item["color"][0] for item in result["samples"]] == [0, .5, 1]
    for samples in ([0] * 33, [float("inf")], [True]):
        with pytest.raises(module.BridgeError):
            module.inspect_properties(context, params(sample_positions=samples))
    bpy.context.mode = "EDIT_MESH"
    before = module.ramp_state(ramp.color_ramp)
    with pytest.raises(module.BridgeError) as caught:
        module.set_color_ramp(context, params(stops=STOPS))
    assert caught.value.code == "NOT_IMPLEMENTED" and module.ramp_state(ramp.color_ramp) == before


def test_pre_cancelled_revision_never_changes_the_ramp(shader_settings):
    module, context, _, _, _, ramp, _ = shader_settings
    before = module.ramp_state(ramp.color_ramp)
    def stop():
        raise module.BridgeError("TIMEOUT", "fixture cancellation")
    context.check_cancelled = stop
    with pytest.raises(module.BridgeError) as caught:
        module.set_color_ramp(context, params(stops=STOPS))
    assert caught.value.code == "TIMEOUT" and module.ramp_state(ramp.color_ramp) == before


def test_invalid_native_sampling_is_not_returned_as_complete_numeric_evidence(shader_settings):
    module, context, _, _, _, ramp, _ = shader_settings
    ramp.color_ramp.evaluate = lambda position: [float("nan"), 0, 0, 1]
    with pytest.raises(module.BridgeError) as caught:
        module.inspect_properties(context, params(sample_positions=[.5]))
    assert caught.value.code == "OPERATION_FAILED"


def test_nonfinite_socket_defaults_prevent_an_unverifiable_revision(shader_settings):
    module, context, _, _, math, _, _ = shader_settings
    math.inputs[0].default_value = float("nan")
    with pytest.raises(module.BridgeError) as caught:
        module.set_properties(context, params("Math", settings={"operation": "MULTIPLY"}))
    assert caught.value.code == "NOT_IMPLEMENTED" and math.operation == "ADD"


def test_scene_evidence_detects_same_count_ramp_and_property_changes(shader_settings, addon_package):
    _, _, material, _, math, ramp, _ = shader_settings
    evidence = importlib.import_module(f"{addon_package}.scene_evidence")
    def digest():
        return evidence._digest(evidence._shader_records(material), evidence.Budget(1000, None))
    before = digest()
    ramp.color_ramp.elements[0].color[0] = .25
    assert digest()["sha256"] != before["sha256"]
    before = digest()
    math.operation = "MULTIPLY"
    assert digest()["sha256"] != before["sha256"]


def test_strict_schema_and_forwarding():
    hints = get_type_hints(ShaderSettingsTools.nodes_set_color_ramp, include_extras=True)
    adapter = TypeAdapter(hints["stops"])
    for raw in ([], STOPS * 11, [{"position": True, "color": [0, 0, 0, 1]}],
                [{"position": 0, "color": [0, 0, 0, 1], "extra": 1}]):
        with pytest.raises(ValidationError):
            adapter.validate_python(raw)
    calls = []
    async def call(method, parameters):
        calls.append((method, parameters))
    tools = ShaderSettingsTools(NS(call=call))
    asyncio.run(tools.nodes_set_color_ramp("Material", "Ramp", [RampStop(**item) for item in STOPS],
                                         group_path=["Outer", "Inner"], allow_shared=True))
    method, data = calls[0]
    assert method == "nodes.set_color_ramp" and data["stops"] == STOPS
    assert data["group_path"] == ["Outer", "Inner"] and data["allow_shared"] is True
    assert not any(key in data for key in ("interpolation", "color_mode", "hue_interpolation"))


def test_complete_ramp_replacement_has_a_destructive_mcp_hint():
    from mcp_server.tools.catalog import DESTRUCTIVE_TOOL_NAMES

    assert "nodes.set_color_ramp" in DESTRUCTIVE_TOOL_NAMES


def test_ramp_inspection_and_graph_truncation_are_explicit(shader_settings, addon_package):
    module, _, _, _, _, ramp, _ = shader_settings
    for _ in range(31):
        ramp.color_ramp.elements.append(deepcopy(ramp.color_ramp.elements[0]))
    assert module.ramp_state(ramp.color_ramp)["truncated"]
    evidence = importlib.import_module(f"{addon_package}.scene_evidence")
    with pytest.raises(evidence.EvidenceLimit):
        list(evidence._shader_records(shader_settings[2]))
