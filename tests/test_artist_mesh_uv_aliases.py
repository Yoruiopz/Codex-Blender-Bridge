"""Mesh UV selectors are exact same-Mesh aliases, never outbound exemptions."""

from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
from checkpoint_completion_support import complete_plan_push
from test_artist_loop import loop, rna_env  # noqa: F401
from test_artist_role_witness import mesh, native, witness_case  # noqa: F401
from test_object_rna_mutation import Items, prop
from test_scene_checkpoint_roles import roles as roles

ALIASES = ("uv_layer_clone", "uv_layer_stencil")


@pytest.fixture
def original_plan_type(addon_package):
    # Retain the real class before loop's unrelated descriptor-free role adapter.
    return importlib.import_module(f"{addon_package}.tools._scene_checkpoint_roles").Plan


@pytest.fixture
def uv_case(original_plan_type, witness_case):  # noqa: F811
    case = witness_case
    mesh(case)
    fields = (prop("name", "STRING"), prop("active", "BOOLEAN"),
              prop("active_clone", "BOOLEAN"), prop("active_render", "BOOLEAN"))
    first = native("MeshUVLoopLayer", fields=fields, name="UVMap", active=True, active_clone=True, active_render=True)
    second = native("MeshUVLoopLayer", fields=fields, name="Details", active=False, active_clone=False, active_render=False)
    second.bl_rna = first.bl_rna
    case.bpy.types = NS(MeshUVLoopLayer=NS(bl_rna=first.bl_rna))
    case.mesh.uv_layers = Items([first, second])
    case.mesh.uv_layers.active_index = 0
    for name in (*ALIASES, "uv_layers"):
        descriptor = prop(name, "COLLECTION" if name == "uv_layers" else "POINTER", readonly=name == "uv_layers")
        descriptor.is_runtime = descriptor.is_registered = descriptor.is_registered_optional = False
        descriptor.fixed_type = first.bl_rna
        case.mesh.bl_rna.properties[name] = descriptor
    case.mesh.uv_layer_clone, case.mesh.uv_layer_stencil = first, second
    case.first_uv, case.second_uv, case.real_plan_type = first, second, original_plan_type
    case.aliases = lambda: case.witness_module._mesh_uv_aliases(case.bpy, case.mesh)
    return case


@pytest.mark.parametrize("selected", ["none", "first", "second"])
def test_exact_present_aliases_accept_null_or_same_mesh_members_readonly(uv_case, selected):
    case = uv_case
    layer = {"none": None, "first": case.first_uv, "second": case.second_uv}[selected]
    for name in ALIASES:
        setattr(case.mesh, name, layer)
    for owner in (case.old, case.mesh, case.first_uv, case.second_uv):
        owner._writes.clear()
    expected = None if layer is None else (case.mesh.uv_layers.index(layer), layer.as_pointer(), layer.name)
    assert case.aliases() == tuple((name, expected) for name in ALIASES)
    witness = case.capture()
    witness.check(case.role_plan)
    assert all(owner._writes == [] for owner in (case.old, case.mesh, case.first_uv, case.second_uv))


@pytest.mark.parametrize("remaining", [(), ("uv_layer_clone",), ("uv_layer_stencil",)])
def test_absent_optional_alias_descriptors_have_explicit_evidence(uv_case, remaining):
    case = uv_case
    for name in ALIASES:
        if name not in remaining:
            del case.mesh.bl_rna.properties[name]
    receipt = case.aliases()
    assert tuple(name for name, _value in receipt) == remaining
    case.capture().check(case.role_plan)


@pytest.mark.parametrize("name", ALIASES)
@pytest.mark.parametrize("when", ["capture", "recheck"])
def test_same_named_foreign_layers_are_never_accepted_as_aliases(uv_case, name, when):
    case = uv_case
    witness = case.capture() if when == "recheck" else None
    original = getattr(case.mesh, name)
    foreign = native("MeshUVLoopLayer", name=original.name)
    foreign.bl_rna = original.bl_rna
    setattr(case.mesh, name, foreign)
    with pytest.raises(case.module.BridgeError) as caught:
        case.capture() if witness is None else witness.check(case.role_plan)
    assert caught.value.context["previous_owner_witness_complete"] is False
    assert getattr(case.mesh, name) is foreign


@pytest.mark.parametrize("name", ALIASES)
def test_an_ambiguous_duplicate_member_cannot_authorize_a_selector(uv_case, name):
    case = uv_case
    case.mesh.uv_layers.append(getattr(case.mesh, name))
    with pytest.raises(case.module.BridgeError, match="unique same-Mesh"):
        case.aliases()


@pytest.mark.parametrize("name", ALIASES)
@pytest.mark.parametrize("change", ["none", "switch", "rename", "reorder", "replacement", "descriptor_removal"])
def test_alias_receipts_detect_role_inventory_name_and_identity_drift(uv_case, name, change):
    case = uv_case
    before = case.aliases()
    witness = case.capture()
    selected = getattr(case.mesh, name)
    if change == "none":
        setattr(case.mesh, name, None)
    elif change == "switch":
        setattr(case.mesh, name, case.second_uv if selected is case.first_uv else case.first_uv)
    elif change == "rename":
        selected.name = "Renamed manually"
    elif change == "reorder":
        case.mesh.uv_layers.reverse()
    elif change == "replacement":
        replacement = native("MeshUVLoopLayer", name=selected.name, active=selected.active,
            active_clone=selected.active_clone, active_render=selected.active_render)
        replacement.bl_rna = selected.bl_rna
        case.mesh.uv_layers[case.mesh.uv_layers.index(selected)] = replacement
        setattr(case.mesh, name, replacement)
    else:
        del case.mesh.bl_rna.properties[name]
    assert case.aliases() != before
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)


@pytest.mark.parametrize("name", ALIASES)
def test_null_to_member_transition_is_not_a_new_retained_baseline(uv_case, name):
    case = uv_case
    setattr(case.mesh, name, None)
    witness = case.capture()
    setattr(case.mesh, name, case.first_uv)
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)


def test_clone_and_stencil_are_independent_roles(uv_case):
    case = uv_case
    before = case.aliases()
    witness = case.capture()
    case.mesh.uv_layer_clone, case.mesh.uv_layer_stencil = case.mesh.uv_layer_stencil, case.mesh.uv_layer_clone
    after = case.aliases()
    assert after[0][1] == before[1][1] and after[1][1] == before[0][1]
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)


@pytest.mark.parametrize("name", (*ALIASES, "uv_layers"))
@pytest.mark.parametrize("fault", ["runtime", "registered", "optional_registered", "wrong_kind", "wrong_fixed_type"])
def test_all_selector_descriptors_are_screened_before_any_getter(uv_case, name, fault):
    case = uv_case
    descriptor = case.mesh.bl_rna.properties[name]
    if fault == "runtime":
        descriptor.is_runtime = True
    elif fault == "registered":
        descriptor.is_registered = True
    elif fault == "optional_registered":
        descriptor.is_registered_optional = True
    elif fault == "wrong_kind":
        descriptor.type = "POINTER" if name == "uv_layers" else "COLLECTION"
    else:
        descriptor.fixed_type = NS(identifier="MeshUVLoopLayer")
    for field in (*ALIASES, "uv_layers"):
        case.mesh._getters[field] = lambda: pytest.fail("An unchecked UV selector or inventory getter ran")
    with pytest.raises(case.module.BridgeError):
        case.capture()
    assert case.mesh._reads == []


@pytest.mark.parametrize("name", ALIASES)
def test_readonly_selector_descriptor_is_not_the_reviewed_writable_alias(uv_case, name):
    case = uv_case
    case.mesh.bl_rna.properties[name].is_readonly = True
    case.mesh._getters[name] = lambda: pytest.fail("An unreviewed readonly alias getter ran")
    with pytest.raises(case.module.BridgeError):
        case.capture()
    assert case.mesh._reads == []


@pytest.mark.parametrize("fault", ["wrong_layer_rna", "missing_name", "runtime_name"])
def test_inventory_members_require_the_exact_native_name_schema_before_read(uv_case, fault):
    case = uv_case
    if fault == "wrong_layer_rna":
        case.first_uv.bl_rna = NS(identifier="MeshUVLoopLayer", properties=case.first_uv.bl_rna.properties)
    elif fault == "missing_name":
        del case.first_uv.bl_rna.properties["name"]
    else:
        case.first_uv.bl_rna.properties["name"].is_runtime = True
    case.first_uv._getters["name"] = lambda: pytest.fail("An unreviewed layer name getter ran")
    with pytest.raises(case.module.BridgeError):
        case.capture()
    assert case.first_uv._reads == []


@pytest.mark.parametrize("size", [128, 129])
def test_same_mesh_layer_inventory_is_bounded_before_selector_reads(uv_case, size):
    case = uv_case
    for name in ALIASES:
        setattr(case.mesh, name, None)
    case.mesh.uv_layers[:] = [case.first_uv] * size
    if size == 128:
        assert case.aliases() == tuple((name, None) for name in ALIASES)
    else:
        for name in ALIASES:
            case.mesh._getters[name] = lambda: pytest.fail("Selector ran after oversized inventory")
        with pytest.raises(case.module.BridgeError, match="128"):
            case.aliases()
        assert case.mesh._reads == []


@pytest.mark.parametrize("field", ["texture_mesh", "texco_mesh", "unknown_outbound"])
def test_uv_alias_admission_does_not_admit_other_nonnull_mesh_pointers(uv_case, field):
    case = uv_case
    case.mesh.bl_rna.properties[field] = prop(field, "POINTER")
    setattr(case.mesh, field, case.mesh)
    with pytest.raises(case.module.BridgeError) as caught:
        case.capture()
    assert caught.value.context["previous_owner_witness_complete"] is False
    assert getattr(case.mesh, field) is case.mesh


@pytest.mark.parametrize("change", ["role", "vertex", "attribute", "custom"])
def test_admitted_aliases_preserve_existing_metadata_and_geometry_checks(uv_case, change):
    case = uv_case
    witness = case.capture()
    if change == "role":
        case.first_uv.active_render = False
    elif change == "vertex":
        case.vertex.co = (9., 0., 0.)
    elif change == "attribute":
        case.attribute_value.value = .75
    else:
        case.mesh._custom["artist_manual_value"] = {"nested": .75}
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)


@pytest.mark.parametrize("phase", ["before", "after"])
def test_actual_previous_witness_keeps_uv_aliases_through_authenticated_push(
    uv_case, roles, addon_package, monkeypatch, phase,
):
    case = uv_case
    role_case = roles
    role_case.bpy.data = case.bpy.data
    role_case.bpy.data.objects.append(role_case.active)
    role_case.scene.objects = role_case.bpy.data.objects
    role_case.bpy.context.scene = role_case.scene
    role_case.bpy.context.view_layer.objects = role_case.bpy.data.objects
    role_case.bpy.context.view_layer.objects.active = role_case.active
    role_case.bpy.types.MeshUVLoopLayer = case.bpy.types.MeshUVLoopLayer
    role_case.counts["self"] = 1
    role_case.particle._values["object"] = case.old
    plan = case.real_plan_type(role_case.bpy, role_case.scene, active_validator=lambda *_: None,
                              previous_owner_factory=case.witness_module.capture)
    retained = plan.previous_witness
    if phase == "after":
        complete_plan_push(addon_package, monkeypatch, plan, effect=role_case.push)
        assert plan.expected == (1, role_case.module.proof.token(role_case.active))
        assert plan.previous_witness is retained
    else:
        assert plan.expected == (1, role_case.module.proof.token(case.old))
    plan.check_after_read()
    case.mesh.uv_layer_clone = case.second_uv
    effects = []
    with pytest.raises(case.module.BridgeError):
        complete_plan_push(addon_package, monkeypatch, plan, effect=lambda: effects.append("must not run"))
    assert effects == [] and plan.previous_witness is retained
