"""Private numeric conformance only, never native constructor qualification."""
from __future__ import annotations

import copy
import importlib
import math
import struct
from dataclasses import FrozenInstanceError, replace

import pytest
from test_asset_glb_import_plan import append_accessor, glb, triangle


@pytest.fixture
def modules(addon_package):
    return (importlib.import_module(addon_package + ".glb_stage_profile"),
            importlib.import_module(addon_package + ".asset_glb_import_plan"))


def test_identity_recipe_has_exact_signed_float32_geometry_and_default_material(modules):
    profile, planner = modules
    manifest, binary = triangle()
    binary = struct.pack("<f", -0.) + binary[4:]
    plan = planner.plan_glb(glb(manifest, binary))
    recipe = profile.compile_profile(plan)
    assert recipe.profile == "GLB_PRIVATE_STAGE_V1"
    assert recipe.source_sha256 == plan.source_sha256
    assert recipe.plan_sha256 == plan.normalized_sha256
    assert profile.mesh_body(recipe.meshes[0])["vertices"][0] == ["00000080", "00000080", "00000000"]
    assert recipe.materials[0].color == ("0000803f",) * 4
    assert recipe.materials[0].metallic == recipe.materials[0].roughness == "0000803f"
    assert profile.digest(profile.recipe_data(recipe)) == recipe.recipe_sha256
    with pytest.raises(FrozenInstanceError):
        recipe.profile = "qualified"


def test_multiple_primitives_keep_offsets_material_slots_and_mesh_instances(modules):
    profile, planner = modules
    manifest, binary = triangle()
    original = manifest["meshes"][0]["primitives"][0]
    manifest["materials"] = [{"name": "Red"}, {"name": "Green"}]
    manifest["meshes"][0]["primitives"] = [{**original, "material": i} for i in (1, 0)]
    manifest["nodes"] = [{"mesh": 0}, {"mesh": 0}]
    manifest["scenes"][0]["nodes"] = [0, 1]
    plan = planner.plan_glb(glb(manifest, binary))
    recipe = profile.compile_profile(plan)
    mesh = recipe.meshes[0]
    assert len(mesh.vertices) == 6 and mesh.triangles == ((0, 1, 2), (3, 4, 5))
    assert mesh.material_indices == (1, 0) and mesh.polygon_slots == (0, 1)
    assert [o.mesh_index for o in recipe.objects] == [0, 0]
    assert profile.mesh_body(mesh)["loops"] == [0, 1, 2, 3, 4, 5]


@pytest.mark.parametrize("kind", ["mask", "blend"])
def test_valid_broader_plans_refuse_without_dropping_content(modules, kind):
    profile, planner = modules
    manifest, binary = triangle(normals=kind == "normal", uv=kind == "uv")
    if kind == "translation":
        manifest["nodes"][0]["translation"] = [1, 0, 0]
    elif kind == "hierarchy":
        manifest["nodes"] = [{"children": [1]}, {"mesh": 0}]
    elif kind in {"mask", "blend"}:
        manifest["materials"] = [{"alphaMode": kind.upper()}]
        manifest["meshes"][0]["primitives"][0]["material"] = 0
    plan = planner.plan_glb(glb(manifest, binary))
    with pytest.raises(profile.BridgeError) as error:
        profile.compile_profile(plan)
    assert error.value.code == "NOT_IMPLEMENTED"
    assert error.value.context["native_allocation_started"] is False
    assert plan.normalized_sha256 == planner.plan_glb(glb(manifest, binary)).normalized_sha256


def test_explicit_uvs_and_normals_follow_corner_indices_without_losing_source_basis(modules):
    profile, planner = modules
    manifest, binary = triangle(uv=True)
    normal, binary = append_accessor(manifest, binary, ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), "VEC3")
    primitive = manifest["meshes"][0]["primitives"][0]
    primitive["attributes"]["NORMAL"] = normal
    accessor = manifest["accessors"][primitive["indices"]]
    offset = manifest["bufferViews"][accessor["bufferView"]]["byteOffset"]
    binary = binary[:offset] + struct.pack("<3H", 2, 0, 1) + binary[offset + 6:]
    plan = planner.plan_glb(glb(manifest, binary))
    mesh = profile.compile_profile(plan).meshes[0]
    assert mesh.corner_uvs == ((0., 0.), (0., 1.), (1., .75))
    assert mesh.corner_normals == ((0., -1., 0.), (1., -0., 0.), (0., -0., 1.))
    assert mesh.corner_uv_present == mesh.corner_normal_present == (True,) * 3
    assert profile.mesh_uv_body(mesh) == {"name": "UVMap", "vectors": [
        [profile.f32(value) for value in uv] for uv in mesh.corner_uvs],
        "active": 0, "render": 0, "clone": 0, "stencil": 0, "clone_bound": True, "stencil_bound": True}
    assert profile.mesh_normal_body(mesh)["present"] == [True] * 3
    # The native write sequence creates attributes after topology. Its exact
    # expected prefixes must not pretend these inputs were already installed.
    assert profile.mesh_body(mesh)["uv"] is profile.mesh_body(mesh)["normals"] is None


def test_mixed_primitives_keep_explicit_attribute_presence_and_default_inputs(modules):
    profile, planner = modules
    manifest, binary = triangle(normals=True, uv=True)
    first = manifest["meshes"][0]["primitives"][0]
    manifest["meshes"][0]["primitives"].append({**first, "attributes": {"POSITION": first["attributes"]["POSITION"]}})
    recipe = profile.compile_profile(planner.plan_glb(glb(manifest, binary)))
    mesh = recipe.meshes[0]
    assert mesh.corner_uv_present == mesh.corner_normal_present == (True,) * 3 + (False,) * 3
    assert mesh.corner_uvs[3:] == ((0., 0.),) * 3
    assert mesh.corner_normals[3:] == ((0., 0., 0.),) * 3
    assert mesh.triangles == ((0, 1, 2), (3, 4, 5))
    assert mesh.polygon_slots == (0, 0)
    assert profile.mesh_normal_body(mesh)["present"] == [True] * 3 + [False] * 3


def test_transformed_hierarchy_and_shared_meshes_keep_raw_authored_channels_separate_from_conformance(modules):
    profile, planner = modules
    manifest, binary = triangle()
    angle = math.pi / 8.
    manifest["nodes"] = [
        {"children": [1, 2], "translation": [3., -4., 5.],
         "rotation": [0., 0., math.sin(angle), math.cos(angle)], "scale": [2., 3., 4.]},
        {"mesh": 0, "translation": [-2., 1., .5], "scale": [-1., 2., 3.]},
        {"mesh": 0, "translation": [2., -1., -.5], "rotation": [1., 0., 0., 0.]},
    ]
    plan = planner.plan_glb(glb(manifest, binary))
    recipe = profile.compile_profile(plan)
    assert [obj.parent_index for obj in recipe.objects] == [None, 0, 0]
    assert [obj.mesh_index for obj in recipe.objects] == [None, 0, 0]
    assert len(recipe.meshes) == 1
    worlds = profile.expected_worlds(recipe)
    for obj, node in zip(recipe.objects, plan.nodes, strict=True):
        authored = profile.object_authored(obj)
        assert authored["rotation_mode"] == "QUATERNION"
        assert authored["matrix_parent_inverse"] == list(profile.IDENTITY_BITS)
        assert authored["location"] == [profile.f32(node.local_matrix[i][3]) for i in range(3)]
        for row in range(4):
            for column in range(4):
                assert worlds[node.source_index][row][column] == pytest.approx(node.world_matrix[row][column], abs=2e-6, rel=2e-6)
    assert profile.digest(profile.recipe_data(recipe)) == recipe.recipe_sha256


@pytest.mark.parametrize("scale", [
    [0., 0., 0.], [0., 0., 2.], [0., 3., 0.], [2., 0., 0.],
    [0., 3., -2.], [-2., 0., 4.], [2., -3., 0.], [-2., -3., -4.],
    [1e-20, 2e20, -3e-10],
])
def test_matrix_decomposition_handles_zero_nonuniform_and_reflected_axes(modules, scale):
    profile, planner = modules
    manifest, binary = triangle()
    manifest["nodes"][0].update(scale=scale, rotation=[0., .6, 0., .8], translation=[-0., 1., -2.])
    if max(map(abs, scale)) > 1e9:
        # The public input scalar bound stays unchanged; the same numerical
        # case within that bound still tests a very different axis scale.
        manifest["nodes"][0]["scale"] = [1e-20, 2e8, -3e-10]
    plan = planner.plan_glb(glb(manifest, binary))
    obj = profile.compile_profile(plan).objects[0]
    observed = profile.compose_channels(obj.location, obj.rotation_quaternion, obj.scale)
    for column in range(4):
        magnitude = max(abs(plan.nodes[0].local_matrix[row][column]) for row in range(4))
        for row in range(4):
            assert abs(observed[row][column] - plan.nodes[0].local_matrix[row][column]) <= 8 * 2 ** -23 * magnitude + 2 ** -148


def test_small_shear_that_planner_tolerates_is_not_silently_discarded_by_trs_compiler(modules):
    profile, planner = modules
    manifest, binary = triangle()
    manifest["nodes"][0]["matrix"] = [1., 0., 0., 0., 4e-6, 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
    plan = planner.plan_glb(glb(manifest, binary))
    with pytest.raises(profile.BridgeError) as error:
        profile.compile_profile(plan)
    assert error.value.context["reason"] == "TRANSFORM_NOT_REPRESENTABLE_BY_FLOAT32_TRS"
    assert error.value.context["native_allocation_started"] is False


def test_world_projection_resolves_parent_source_order_and_refuses_corrupted_hierarchy(modules):
    profile, planner = modules
    manifest, binary = triangle()
    manifest["nodes"] = [{"mesh": 0, "translation": [1., 2., 3.]},
                         {"children": [0], "translation": [-1., 3., 2.]}]
    manifest["scenes"][0]["nodes"] = [1]
    plan = planner.plan_glb(glb(manifest, binary))
    recipe = profile.compile_profile(plan)
    assert recipe.objects[0].parent_index == 1
    worlds = profile.expected_worlds(recipe)
    assert worlds[0] == plan.nodes[0].world_matrix
    duplicate = replace(recipe, objects=(recipe.objects[0], recipe.objects[0]))
    cycle = replace(recipe, objects=(recipe.objects[0], replace(recipe.objects[1], parent_index=0)))
    missing = replace(recipe, objects=(replace(recipe.objects[0], parent_index=7), recipe.objects[1]))
    for broken in (duplicate, cycle, missing):
        with pytest.raises(profile.BridgeError):
            profile.expected_worlds(broken)


@pytest.mark.parametrize("field", ["location", "rotation_quaternion", "scale", "parent_inverse"])
def test_authored_channels_have_exact_digest_authority_independent_of_small_matrix_error(modules, field):
    profile, planner = modules
    manifest, binary = triangle()
    recipe = profile.compile_profile(planner.plan_glb(glb(manifest, binary)))
    obj = recipe.objects[0]
    original = getattr(obj, field)
    first = struct.unpack("<f", bytes.fromhex(original[0]))[0]
    values = (profile.f32(first + max(1., abs(first)) * 2 ** -23), *original[1:])
    changed = replace(recipe, objects=(replace(obj, **{field: values}),))
    # A matrix numerical tolerance must never adopt a newly observed authored
    # channel, even when its visual/numerical effect would be tiny.
    assert profile.object_authored(obj) != profile.object_authored(changed.objects[0])
    assert profile.digest(profile.recipe_data(recipe)) != profile.digest(profile.recipe_data(changed))


def test_tampered_plan_is_not_new_intent_and_foreign_serializer_never_runs(modules):
    profile, planner = modules
    manifest, binary = triangle()
    plan = planner.plan_glb(glb(manifest, binary))
    object.__setattr__(plan, "coordinate_unit", "OTHER")
    with pytest.raises(profile.BridgeError):
        profile.compile_profile(plan)
    calls = []

    class Foreign:
        def __deepcopy__(self, _memo):
            calls.append(True)
            raise AssertionError("foreign serialization")

    object.__setattr__(plan, "meshes", (Foreign(),))
    with pytest.raises(profile.BridgeError):
        profile.compile_profile(plan)
    assert not calls


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), 2**4096, object()])
def test_float32_streams_are_bounded_ordinary_scalars(modules, value):
    profile, _ = modules
    with pytest.raises(profile.BridgeError):
        profile.f32(value)


def test_canonical_comparison_keeps_boolean_integer_and_zero_sign_distinct(modules):
    profile, _ = modules
    assert profile.canonical({"value": True}) != profile.canonical({"value": 1})
    assert profile.f32(-0.) != profile.f32(0.)


def test_constructor_snapshot_rejects_non_surface_or_extra_nodes(modules):
    profile, _ = modules
    tree = {"name": "Default Tree", "kind": "node_tree", "uid": 1, "pointer": 10,
            "users": 1, "fake_user": False,
            "body": {"layout": [["ShaderNodeBsdfPrincipled", "P", [], "", False],
                                ["ShaderNodeOutputMaterial", "O", [], "", False]],
                     "other_inputs": [], "pbr": {k: [] for k in ("Base Color", "Metallic", "Roughness", "Alpha")},
                     "active_output": True, "output_target": "ALL",
                     "links": [["ShaderNodeBsdfPrincipled", "BSDF", "ShaderNodeOutputMaterial", "Surface"]]}}
    assert profile.validate_new_row("node_tree:0", "Default Tree", tree) == tree
    for invalid in ("ShaderNodeVolumePrincipled", "UnknownNode"):
        changed = copy.deepcopy(tree)
        changed["body"]["layout"][0][0] = invalid
        with pytest.raises(profile.BridgeError):
            profile.validate_new_row("node_tree:0", "Default Tree", changed)


def test_unknown_planner_profile_does_not_inherit_native_constructor_admission(modules):
    import hashlib
    from dataclasses import replace

    profile, planner = modules
    manifest, binary = triangle()
    plan = replace(planner.plan_glb(glb(manifest, binary)), profile="FUTURE_UNREVIEWED")
    plan = replace(plan, normalized_sha256=hashlib.sha256(plan.canonical_bytes()).hexdigest())
    with pytest.raises(profile.BridgeError) as error:
        profile.compile_profile(plan)
    assert error.value.code == "NOT_IMPLEMENTED"


def test_projection_cumulative_text_and_encoding_are_bounded_before_large_allocation(modules, monkeypatch):
    profile, _ = modules
    monkeypatch.setattr(profile, "MAX_PROJECTION_BYTES", 256)
    shared = "x" * 128
    with pytest.raises(profile.BridgeError):
        profile.canonical([shared] * 1000)
    # Numbers fit the text budget but their encoded representation must also
    # stop incrementally; no giant json.dumps string is first materialized.
    with pytest.raises(profile.BridgeError):
        profile.canonical([2**63] * 1000)
    with pytest.raises(profile.BridgeError):
        profile.canonical({"x" * 128: "y" * 128, "second": ""})



def metadata_property(name="co", kind="FLOAT", width=3, **changes):
    from types import SimpleNamespace

    fields = dict(identifier=name, type=kind, is_runtime=False, is_registered=False,
                  is_readonly=False, fixed_type=None, as_pointer=lambda: 17,
                  is_output=False, is_required=True)
    if kind in {"BOOLEAN", "INT", "FLOAT"}:
        fields["array_length"] = width
    fields.update(changes)
    return SimpleNamespace(**fields)


def test_nonnumeric_metadata_has_no_fabricated_array_length(modules):
    profile, _ = modules
    prop = metadata_property("name", "STRING")
    assert not hasattr(prop, "array_length")
    signature = profile.require_native_property(prop, "name", "STRING")
    assert signature[2] is None
    dynamic = metadata_property("vertices", "INT", 0)
    assert profile.require_native_property(dynamic, "vertices", "INT", "*")[2] == 0


@pytest.mark.parametrize("fault", ["runtime", "readonly", "width", "int_flag", "pointer", "kind"])
def test_used_metadata_rejects_invalid_write_before_a_setter(modules, fault):
    profile, _ = modules
    changes = {"runtime": {"is_runtime": True}, "readonly": {"is_readonly": True},
               "width": {"array_length": 4}, "int_flag": {"is_registered": 0},
               "pointer": {"as_pointer": lambda: 0}, "kind": {"type": "INT"}}[fault]
    prop = metadata_property(**changes)
    with pytest.raises(profile.BridgeError):
        profile.require_native_property(prop, "co", "FLOAT", 3, writing=True)


@pytest.mark.parametrize("fault", ["output", "required", "array", "target", "extra", "registered"])
def test_function_contract_checks_actual_direction_required_shape_and_fixed_target(modules, fault):
    from types import SimpleNamespace

    profile, _ = modules
    name = metadata_property("name", "STRING")
    output = metadata_property("mesh", "POINTER", fixed_type=SimpleNamespace(identifier="Mesh"),
                               is_output=True, is_required=False)
    function = SimpleNamespace(parameters=[name, output], is_registered=False,
                               is_registered_optional=False, as_pointer=lambda: 19)
    schema = profile.NATIVE_FUNCTIONS["BlendDataMeshes"]["new"]
    assert profile.native_function_signature(function, schema, "new")[0] == 19
    if fault == "output":
        output.is_output = False
    elif fault == "required":
        name.is_required = False
    elif fault == "array":
        function.parameters = [metadata_property("count", "INT", 3)]
        schema = profile.NATIVE_FUNCTIONS["MeshVertices"]["add"]
    elif fault == "target":
        output.fixed_type.identifier = "Object"
    elif fault == "extra":
        function.parameters.append(metadata_property("hidden", "INT", 0))
    else:
        function.is_registered = True
    with pytest.raises(profile.BridgeError):
        profile.native_function_signature(function, schema, "add" if fault == "array" else "new")


@pytest.mark.parametrize("fault", [None, "required_name", "required_init", "target", "output"])
def test_uv_constructor_keeps_optional_parameters_and_exact_return_target(modules, fault):
    from types import SimpleNamespace

    profile, _ = modules
    name = metadata_property("name", "STRING", is_required=False)
    initialize = metadata_property("do_init", "BOOLEAN", 0, is_required=False)
    output = metadata_property("layer", "POINTER", fixed_type=SimpleNamespace(identifier="MeshUVLoopLayer"),
                               is_output=True, is_required=False)
    function = SimpleNamespace(parameters=[name, initialize, output], is_registered=False,
                               is_registered_optional=False, as_pointer=lambda: 19)
    schema = profile.NATIVE_FUNCTIONS["UVLoopLayers"]["new"]
    if fault == "required_name":
        name.is_required = True
    elif fault == "required_init":
        initialize.is_required = True
    elif fault == "target":
        output.fixed_type.identifier = "MeshLoopColorLayer"
    elif fault == "output":
        output.is_output = False
    if fault is None:
        assert profile.native_function_signature(function, schema, "new", class_name="UVLoopLayers")[0] == 19
    else:
        with pytest.raises(profile.BridgeError):
            profile.native_function_signature(function, schema, "new", class_name="UVLoopLayers")


def test_dynamic_normal_input_is_narrowly_allowed_without_general_numeric_array_relaxation(modules):
    from types import SimpleNamespace

    profile, _ = modules
    normals = metadata_property("normals", "FLOAT", 3)
    function = SimpleNamespace(parameters=[normals], is_registered=False,
                               is_registered_optional=False, as_pointer=lambda: 19)
    schema = profile.NATIVE_FUNCTIONS["Mesh"]["normals_split_custom_set"]
    signature = profile.native_function_signature(function, schema, "normals_split_custom_set", class_name="Mesh")
    assert signature[1][0][0][2] == 3
    for class_name, method in (("Object", "normals_split_custom_set"), ("Mesh", "unknown_dynamic")):
        with pytest.raises(profile.BridgeError):
            profile.native_function_signature(function, schema, method, class_name=class_name)


def test_fresh_object_rows_require_default_rotation_parent_inverse_and_no_children(modules):
    profile, _ = modules
    row = {"name": "Fresh", "kind": "object", "uid": 1, "pointer": 2, "users": 0, "fake_user": False,
           "body": {"data": None, "parent": None, "matrix": list(profile.IDENTITY_BITS),
                    "channels": {"rotation_euler": [profile.f32(0.)] * 3,
                                 "rotation_quaternion": [profile.f32(1.), *([profile.f32(0.)] * 3)]},
                    "collections": [], "rotation_mode": "XYZ", "parent_type": "OBJECT",
                    "parent_inverse": list(profile.IDENTITY_BITS), "children": []}}
    assert profile.validate_new_row("object:0", "Fresh", row) == row
    for field, value in (("rotation_mode", "QUATERNION"), ("parent_type", "BONE"),
                         ("children", ["object:1"]), ("parent_inverse", [profile.f32(0.)] * 16)):
        changed = copy.deepcopy(row)
        changed["body"][field] = value
        with pytest.raises(profile.BridgeError):
            profile.validate_new_row("object:0", "Fresh", changed)
    for field in ("rotation_euler", "rotation_quaternion"):
        changed = copy.deepcopy(row)
        changed["body"]["channels"][field][1] = profile.f32(.25)
        with pytest.raises(profile.BridgeError):
            profile.validate_new_row("object:0", "Fresh", changed)


def test_empty_mesh_constructor_does_not_adopt_foreign_attributes_or_uv_storage(modules):
    profile, _ = modules
    row = {"name": "Fresh mesh", "kind": "mesh", "uid": 1, "pointer": 2, "users": 0, "fake_user": False,
           "body": {**{name: [] for name in ("vertices", "loops", "face_ranges", "polygons", "edges", "materials")},
                    "uv": None, "normals": None, "custom_data": {}}}
    assert profile.validate_new_row("mesh:0", "Fresh mesh", row) == row
    for field, value in (("custom_data", {"unexpected": []}), ("uv", {"name": "Unexpected"}),
                         ("normals", {"source": []})):
        changed = copy.deepcopy(row)
        changed["body"][field] = value
        with pytest.raises(profile.BridgeError):
            profile.validate_new_row("mesh:0", "Fresh mesh", changed)


@pytest.mark.parametrize("fault", ["foreign_collection", "subclass", "bool_count", "oversize", "shape", "numeric_width"])
def test_bulk_reader_refuses_invalid_collection_or_shape_before_field_or_payload_hooks(modules, fault):
    from types import SimpleNamespace

    profile, _ = modules
    events = []
    binding = SimpleNamespace(collection_type=list, field=lambda *_args: events.append("field"))
    collection, width, count = [0], 3, 1
    if fault == "foreign_collection":
        collection = object()
    elif fault == "subclass":
        class Foreign(list):
            def __len__(self):
                events.append("foreign length")
                raise AssertionError("Foreign collection length invoked")
        collection = Foreign([0])
    elif fault == "bool_count":
        count = True
    elif fault == "oversize":
        count = 131073
    elif fault == "shape":
        count = 2
    else:
        width = 65537
    with pytest.raises(profile.BridgeError):
        profile.NativeBinding.bulk_read(binding, collection, "FloatVectorAttributeValue", "vector", "FLOAT", width, count)
    assert not events


def test_python_shadow_is_refused_without_invoking_getter(modules):
    from types import SimpleNamespace

    profile, _ = modules
    events = []

    class UsedOwner:
        @property
        def co(self):
            events.append("foreign getter")
            raise AssertionError("shadow invoked")

    # Test only the pure descriptor screen, with no actual binding or Blender
    # adapter instantiated. This model cannot provide native admission.
    cache = SimpleNamespace(class_namespaces={}, getter=object.__getattribute__, setter=object.__setattr__)
    with pytest.raises(profile.BridgeError) as error:
        profile.NativeBinding._screen(cache, UsedOwner, "co")
    assert error.value.context["reason"] == "NATIVE_FIELD_PYTHON_SHADOW" and not events


@pytest.mark.parametrize("normal_mode", ["none", "authored", "mixed", "separate"])
@pytest.mark.parametrize("uv", [False, True])
def test_profile_compiles_exact_conditional_normal_consent_without_native_work(modules, normal_mode, uv):
    from test_asset_glb_import_plan import conversion_asset

    profile, planner = modules
    manifest, binary = conversion_asset(normal_mode, uv=uv)
    plan = planner.plan_glb(glb(manifest, binary))
    recipe = profile.compile_profile(plan)
    assert recipe.plan_sha256 == plan.normalized_sha256
    assert sum(sum(mesh.corner_normal_present) for mesh in recipe.meshes) == plan.conversion_requirements.authored_normal_corners
    assert sum(len(mesh.corner_normals or ()) - sum(mesh.corner_normal_present) for mesh in recipe.meshes) == plan.conversion_requirements.geometric_auto_corners


@pytest.mark.parametrize("fault", ["old_list", "missing_auto", "extra_auto", "order", "duplicate", "normal_count", "auto_count", "bool_count", "uv_count"])
def test_rehashed_conversion_forgery_refuses_before_recipe_or_native_allocation(modules, monkeypatch, fault):
    import hashlib

    from test_asset_glb_import_plan import conversion_asset

    profile, planner = modules
    manifest, binary = conversion_asset("mixed", uv=True, mixed_uv=True)
    plan = planner.plan_glb(glb(manifest, binary))
    losses = list(plan.required_accepted_losses)
    conversion = plan.conversion_requirements
    if fault == "old_list":
        losses = [*planner.CORE_LOSSES, planner.UV_LOSS]
    elif fault == "missing_auto":
        losses.remove(planner.AUTO_NORMAL_LOSS)
    elif fault == "extra_auto":
        losses.append(planner.AUTO_NORMAL_LOSS)
    elif fault == "order":
        losses[-1], losses[-2] = losses[-2], losses[-1]
    elif fault == "duplicate":
        losses.append(planner.NORMAL_LOSS)
    else:
        field = {"normal_count": "authored_normal_corners", "auto_count": "geometric_auto_corners",
                 "bool_count": "custom_normal_meshes", "uv_count": "missing_uv_zero_fill_corners"}[fault]
        conversion = replace(conversion, **{field: True if fault == "bool_count" else 0})
    changed = replace(plan, conversion_requirements=conversion, required_accepted_losses=tuple(losses))
    changed = replace(changed, normalized_sha256=hashlib.sha256(changed.canonical_bytes()).hexdigest())
    entered = []
    monkeypatch.setattr(profile, "transform_recipe", lambda *_args: entered.append(True))
    with pytest.raises(profile.BridgeError):
        profile.compile_profile(changed)
    assert entered == []
