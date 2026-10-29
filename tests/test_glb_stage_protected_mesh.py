"""Detached header/array flow models; no Blender or Native qualification."""
from __future__ import annotations

import copy
import importlib
import struct
from types import SimpleNamespace as NS
from typing import Any

import pytest


@pytest.fixture
def module(addon_package):
    return importlib.import_module(addon_package + ".glb_stage_protected_mesh")


def bits(value):
    return struct.pack("<f", value).hex()


class Model:
    """Independent tiny triangle and physical header relocation model."""

    def __init__(self, module, *, version=(4, 5, 14), pin=False):
        self.module = module
        self.binding = NS(version_tuple=version)
        self.mesh = object()
        self.events = []
        self.generation = 0
        self.relocate = True
        self.drift = None
        self.values_by_name: dict[str, Any] = {
            "position": [["00000080", "00000000", "00000000"], ["0000803f", "00000000", "00000000"],
                         ["00000000", "0000803f", "00000000"]],
            ".edge_verts": [[0, 1], [1, 2], [2, 0]], ".corner_vert": [0, 1, 2], ".corner_edge": [0, 1, 2],
            "UVMap": [["00000000", "00000000"], ["0000803f", "00000000"], ["00000000", "0000803f"]],
            "custom_normal": [[-32768, 17], [0, -23], [32767, 0]], ".select_vert": [True, False, True],
            "sharp_edge": [False, True, False], "material_index": [0], "sharp_face": [True]}
        schemas = {"position": ("POINT", "FLOAT_VECTOR"), ".edge_verts": ("EDGE", "INT32_2D"),
                   ".corner_vert": ("CORNER", "INT"), ".corner_edge": ("CORNER", "INT"),
                   "UVMap": ("CORNER", "FLOAT2"), "custom_normal": ("CORNER", "INT16_2D"),
                   ".select_vert": ("POINT", "BOOLEAN"), "sharp_edge": ("EDGE", "BOOLEAN"),
                   "material_index": ("FACE", "INT"), "sharp_face": ("FACE", "BOOLEAN")}
        if pin:
            schemas[".pn.UVMap"] = "CORNER", "BOOLEAN"
            self.values_by_name[".pn.UVMap"] = [False, True, False]
        storage = "LEGACY_ARRAY" if version[:2] == (4, 5) else "ARRAY"
        self.headers: dict[str, Any] = {"identity": {"uid": 11, "pointer": 22, "name": "Protected"},
            "counts": {"vertices": 3, "edges": 3, "loops": 3, "polygons": 1},
            "uv_roles": {"active_index": 0, "clone_index": 0, "stencil_index": 0,
                "layers": [{"name": "UVMap", "active": True, "active_render": True, "active_clone": True}]},
            "materials": [{"uid": 33, "pointer": 44, "name": "Protected Material"}],
            "attributes": [{"name": name, "domain": domain, "data_type": kind,
                "native_class": module.LAYOUTS[kind].attribute_class, "value_class": module.LAYOUTS[kind].value_class,
                "storage": storage, "count": len(self.values_by_name[name]), "schema_sha256": "a" * 64,
                "supported": True} for name, (domain, kind) in sorted(schemas.items())],
            "uv_auxiliary_presence": [[".pn.UVMap", pin], [".vs.UVMap", False], [".es.UVMap", False]],
            "shape_keys_ref": None}
        self.vertices = [NS(index=i, co=co, select=[True, False, True][i], hide=False, groups=[])
            for i, co in enumerate([[-0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])]
        self.edges = [NS(index=i, vertices=pair, select=False, hide=False, use_seam=False,
                         use_edge_sharp=[False, True, False][i]) for i, pair in enumerate([(0, 1), (1, 2), (2, 0)])]
        self.loops = [NS(index=i, vertex_index=i, edge_index=i) for i in range(3)]
        self.polygons = [NS(index=0, vertices=(0, 1, 2), loop_start=0, loop_total=3,
                            material_index=0, use_smooth=False, select=False, hide=False)]

    def check(self):
        self.events.append("pure")

    def header_copy(self, _mesh):
        self.events.append("headers")
        return copy.deepcopy(self.headers)

    def get(self, owner, name):
        return getattr(owner, name)

    def items(self, owner, field, _maximum):
        if owner is self.mesh:
            self.events.append("geometry:" + field)
            return tuple(getattr(self, field))
        if field == "groups":
            self.events.append("groups")
            if self.relocate:
                self.generation += 1
                self.relocate = False
                if self.drift:
                    self.drift(self)
            return tuple(owner.groups)
        raise AssertionError("unexpected model field")

    def vector(self, owner, name, width):
        values = getattr(owner, name)
        assert len(values) == width
        return [bits(value) for value in values]

    def integers(self, owner, name, width, _maximum):
        values = list(getattr(owner, name))
        assert len(values) == width
        return values

    def attribute(self, _mesh, header):
        self.events.append("by_name:" + header["name"])
        return NS(name=header["name"], generation=self.generation)

    def values(self, attribute, _header):
        self.events.append("data:" + attribute.name)
        assert attribute.generation == self.generation, "stale borrowed Attribute used"
        return copy.deepcopy(self.values_by_name[attribute.name])


def capture(module, model, monkeypatch, journal=None):
    monkeypatch.setattr(module, "_headers", lambda access, mesh: access.header_copy(mesh))
    return module._capture(model, model.mesh, module._Journal() if journal is None else journal)


def test_public_adapter_does_not_accept_model_or_boolean_authority(module):
    for value in (None, True, object(), NS(_runtime_gate=True)):
        with pytest.raises(module.BridgeError):
            module.ProtectedMeshObserver(value)


def test_detached_capture_survives_dvert_header_relocation_and_keeps_full_bits(module, monkeypatch):
    model = Model(module, pin=True)
    journal = module._Journal()
    result = capture(module, model, monkeypatch, journal)
    assert model.generation == 1
    assert result["attribute_values"]["custom_normal"] == [[-32768, 17], [0, -23], [32767, 0]]
    assert result["geometry"]["vertices"][0]["co"][0] == "00000080"
    assert result["uv_layers"][0]["data"] == [
        {"uv": ["00000000", "00000000"], "pin_uv": False},
        {"uv": ["0000803f", "00000000"], "pin_uv": True},
        {"uv": ["00000000", "0000803f"], "pin_uv": False}]
    assert result["uv_layers"][0]["auxiliary"]["pin"] == ".pn.UVMap"
    assert all(model.events.index("groups") < model.events.index("data:" + name) for name in model.values_by_name)
    cells = journal.report()
    groups = next(row for row in cells if row["kind"] == "VERTEX_GROUP_READ")
    assert groups["attempts_entered"] == groups["attempts_returned"] == 3
    assert "EMPTY_CD_MDEFORMVERT_CREATION_AND_LAYER_DESCRIPTOR_REALLOCATION" in groups["allowed_effects"]
    assert all(row["logical_values_written"] is False for row in cells)


@pytest.mark.parametrize("kind", ["BOOLEAN", "FLOAT2", "INT", "FLOAT_VECTOR", "INT16_2D", "FLOAT"])
def test_any_single_refuses_before_geometry_groups_or_data(module, monkeypatch, kind):
    model = Model(module, version=(5, 2, 2))
    row = model.headers["attributes"][0]
    row["data_type"], row["storage"] = kind, "SINGLE"
    journal = module._Journal()
    with pytest.raises(module.BridgeError) as failure:
        capture(module, model, monkeypatch, journal)
    assert failure.value.context["reason"] == "PROTECTED_MESH_SINGLE_REQUIRES_SEPARATE_PREPARATION"
    assert model.events == ["headers"]
    assert journal.report() == []


def test_unknown_kind_refuses_before_geometry(module, monkeypatch):
    model = Model(module)
    model.headers["attributes"][0]["supported"] = False
    model.headers["attributes"][0]["data_type"] = "STRING"
    with pytest.raises(module.BridgeError):
        capture(module, model, monkeypatch)
    assert model.events == ["headers"]


@pytest.mark.parametrize("drift", ["drop", "append", "schema", "storage", "owner", "uv_role"])
def test_after_group_storage_drift_refuses_before_any_attribute_data(module, monkeypatch, drift):
    model = Model(module, version=(5, 2, 2))
    def change(target):
        if drift == "drop":
            target.headers["attributes"].pop()
        elif drift == "append":
            target.headers["attributes"].append({**target.headers["attributes"][0], "name": "new"})
        elif drift == "schema":
            target.headers["attributes"][0]["schema_sha256"] = "b" * 64
        elif drift == "storage":
            target.headers["attributes"][0]["storage"] = "SINGLE"
        elif drift == "owner":
            target.headers["identity"]["uid"] += 1
        else:
            target.headers["uv_roles"]["active_index"] = -1
    model.drift = change
    with pytest.raises(module.BridgeError):
        capture(module, model, monkeypatch)
    assert not any(event.startswith("data:") for event in model.events)


def test_each_attribute_read_requires_a_fresh_inventory_and_lookup(module, monkeypatch):
    model = Model(module)
    original = model.values
    reads = []
    def values(attribute, header):
        reads.append(attribute.name)
        result = original(attribute, header)
        if len(reads) == 1:
            model.headers["attributes"][-1]["storage"] = "SINGLE"
        return result
    monkeypatch.setattr(model, "values", values)
    with pytest.raises(module.BridgeError):
        capture(module, model, monkeypatch)
    assert len(reads) == 1


def test_logical_hash_preserves_schema_presence_roles_and_every_component_bit(module, monkeypatch):
    model = Model(module)
    baseline = capture(module, model, monkeypatch)
    changed = copy.deepcopy(baseline)
    for row in changed["attributes"]:
        row["storage"] = "ARRAY"
    assert module._digest(module.logical_projection(changed)) == baseline["authored_sha256"]
    for mutate in (
        lambda value: value["attribute_values"]["position"][0].__setitem__(0, "00000000"),
        lambda value: value["attribute_values"]["custom_normal"][0].__setitem__(0, -32767),
        lambda value: value["uv_roles"].__setitem__("active_index", -1),
        lambda value: value["uv_auxiliary_presence"][0].__setitem__(1, True),
        lambda value: value["attributes"].pop(),
    ):
        changed = copy.deepcopy(baseline)
        mutate(changed)
        assert module._digest(module.logical_projection(changed)) != baseline["authored_sha256"]


def test_read_effect_cells_accumulate_without_per_vertex_unbounded_history(module, monkeypatch):
    model = Model(module)
    journal = module._Journal()
    capture(module, model, monkeypatch, journal)
    first = journal.report()
    capture(module, model, monkeypatch, journal)
    second = journal.report()
    assert len(first) == len(second) == len(model.headers["attributes"]) + 5
    assert all(row["attempts_entered"] == 2 * old["attempts_entered"] for row, old in zip(second, first, strict=True))
    second[0]["allowed_effects"].append("foreign")
    assert "foreign" not in journal.report()[0]["allowed_effects"]


@pytest.mark.parametrize("value", [True, 1, 0, None, "true"])
def test_boolean_components_are_never_coerced(module, value):
    if type(value) is bool:
        assert module._boolean(value) is value
    else:
        with pytest.raises(module.BridgeError):
            module._boolean(value)


def test_five_two_array_capture_declares_group_cow_and_empty_dvert_effect(module, monkeypatch):
    model = Model(module, version=(5, 2, 2))
    journal = module._Journal()
    capture(module, model, monkeypatch, journal)
    row = next(item for item in journal.report() if item["kind"] == "VERTEX_GROUP_READ")
    assert row["build"] == [5, 2, 2]
    assert row["attempts_entered"] == row["attempts_returned"] == 3
    assert "EMPTY_CD_MDEFORMVERT_CREATION_AND_LAYER_DESCRIPTOR_REALLOCATION" in row["allowed_effects"]
    assert row["logical_values_written"] is False


def test_global_header_rejection_precedes_geometry_on_any_mesh(module, monkeypatch):
    first, second = Model(module, version=(5, 2, 2)), Model(module, version=(5, 2, 2))
    second.headers["attributes"][-1]["storage"] = "SINGLE"
    censuses = [first.header_copy(first.mesh), second.header_copy(second.mesh)]
    with pytest.raises(module.BridgeError):
        for headers in censuses:
            module.validate_header_profile(headers)
        capture(module, first, monkeypatch)
        capture(module, second, monkeypatch)
    assert first.events == second.events == ["headers"]


@pytest.mark.parametrize("storage", [None, True, 1, "UNKNOWN", "single"])
def test_header_profile_never_admits_unknown_storage(module, storage):
    model = Model(module)
    model.headers["attributes"][0]["storage"] = storage
    with pytest.raises(module.BridgeError):
        module.validate_header_profile(model.headers)


def test_empty_domains_never_enter_geometry_or_data_fallbacks(module, monkeypatch):
    model = Model(module)
    model.headers.update(counts={name: 0 for name in module.COUNTS}, attributes=[],
        uv_roles={"active_index": 0, "clone_index": 0, "stencil_index": 0, "layers": []},
        uv_auxiliary_presence=[])
    model.vertices = model.edges = model.loops = model.polygons = []
    journal = module._Journal()
    result = capture(module, model, monkeypatch, journal)
    assert result["geometry"] == {"vertices": [], "edges": [], "loops": [], "polygons": []}
    assert journal.report() == []
    assert not any(event.startswith(("geometry:", "data:")) for event in model.events)


@pytest.mark.parametrize("value", [True, 1, float("nan"), float("inf"), .1])
def test_float_component_profile_requires_exact_finite_native_float32(module, value):
    with pytest.raises(module.BridgeError):
        module._float_bits(value)


def test_float_components_keep_signed_zero_and_no_tolerance(module):
    assert module._float_bits(-0.) == "00000080"
    assert module._float_bits(0.) == "00000000"
    assert module._float_bits(1.) == "0000803f"


def observer_without_native_work(module):
    """A real binding identity with no native gate; never native acceptance."""
    binding = object.__new__(module.NativeBinding)
    binding._runtime_gate = None
    return module.ProtectedMeshObserver(binding)


@pytest.mark.parametrize("layout_name", ["FLOAT", "FLOAT_VECTOR", "FLOAT2", "INT", "INT32_2D", "INT16_2D", "BOOLEAN"])
@pytest.mark.parametrize("field", ["attribute_class", "value_class", "field", "kind", "width", "minimum", "maximum"])
def test_every_layout_field_is_rechecked_on_existing_observer(module, layout_name, field):
    observer = observer_without_native_work(module)
    layout = module.LAYOUTS[layout_name]
    original = object.__getattribute__(layout, field)
    changed = original + " changed" if type(original) is str else original + 1
    try:
        object.__setattr__(layout, field, changed)
        with pytest.raises(module.BridgeError) as failure:
            observer._check()
        assert failure.value.context["reason"] == "PROTECTED_MESH_OBSERVER_SOURCE_CHANGED"
    finally:
        object.__setattr__(layout, field, original)
    observer._check()


@pytest.mark.parametrize("field", ["attribute_class", "value_class", "field", "kind", "width", "minimum", "maximum"])
@pytest.mark.parametrize("subclass", [False, True])
def test_layout_values_refuse_foreign_protocols_before_copy_or_comparison(module, field, subclass):
    observer = observer_without_native_work(module)
    layout = module.LAYOUTS["FLOAT"]
    original = object.__getattribute__(layout, field)
    calls = []
    class Foreign:
        def __deepcopy__(self, _memo):
            calls.append("deepcopy")
            raise AssertionError("Foreign layout copied")
        def __eq__(self, _other):
            calls.append("eq")
            raise AssertionError("Foreign layout compared")
    class ForeignString(str, Foreign):
        __eq__ = Foreign.__eq__
        __deepcopy__ = Foreign.__deepcopy__
    class ForeignInteger(int, Foreign):
        __eq__ = Foreign.__eq__
        __deepcopy__ = Foreign.__deepcopy__
    value = (ForeignString(original) if type(original) is str else ForeignInteger(original)) if subclass else Foreign()
    try:
        object.__setattr__(layout, field, value)
        with pytest.raises(module.BridgeError) as failure:
            observer._check()
        assert failure.value.context["reason"] == "PROTECTED_MESH_OBSERVER_SOURCE_CHANGED"
        assert calls == []
    finally:
        object.__setattr__(layout, field, original)


@pytest.mark.parametrize("field", ["width", "minimum", "maximum"])
def test_layout_numeric_fields_do_not_accept_booleans(module, field):
    observer = observer_without_native_work(module)
    layout = module.LAYOUTS["FLOAT"]
    original = object.__getattribute__(layout, field)
    try:
        object.__setattr__(layout, field, False)
        with pytest.raises(module.BridgeError):
            observer._check()
    finally:
        object.__setattr__(layout, field, original)


@pytest.mark.parametrize("field", ["attribute_class", "value_class", "field", "kind", "width", "minimum", "maximum"])
def test_layout_descriptor_replacement_refuses_before_getter(module, monkeypatch, field):
    observer = observer_without_native_work(module)
    calls = []
    def forbidden(_self):
        calls.append("getter")
        raise AssertionError("Replacement layout descriptor invoked")
    monkeypatch.setattr(module._Layout, field, property(forbidden))
    with pytest.raises(module.BridgeError):
        observer._check()
    assert calls == []


def test_layout_attribute_dispatch_replacement_refuses_before_callback(module, monkeypatch):
    observer = observer_without_native_work(module)
    calls = []
    def forbidden(_self, _name):
        calls.append("getattribute")
        raise AssertionError("Replacement layout dispatch invoked")
    monkeypatch.setattr(module._Layout, "__getattribute__", forbidden)
    with pytest.raises(module.BridgeError):
        observer._check()
    assert calls == []


def test_layout_verification_no_longer_invokes_runtime_dataclass_copy(module, monkeypatch):
    observer = observer_without_native_work(module)
    monkeypatch.setattr(module, "asdict", lambda *_args: pytest.fail("Runtime dataclass copy invoked"))
    observer._check()
    observer._check()


def test_unchanged_layout_checks_preserve_each_native_gate_boundary(module, addon_package):
    observer = observer_without_native_work(module)
    gates = importlib.import_module(addon_package + ".glb_stage_jobs")
    gate = object.__new__(gates.RuntimeNativeGate)
    calls = []
    gate.service = NS(check_context=lambda *args: calls.append(args))
    gate.context, gate.connection, gate.generation, gate.revoked = object(), object(), 4, False
    observer.binding._runtime_gate = gate
    for index in range(3):
        observer._check()
        assert len(calls) == index + 1
    assert all(args == (gate.context, gate.connection, gate.generation) for args in calls)


def test_layout_guard_projection_covers_complete_declared_dataclass_schema(module):
    from dataclasses import asdict, fields
    assert tuple(field.name for field in fields(module._Layout)) == (
        "attribute_class", "value_class", "field", "kind", "width", "minimum", "maximum")
    assert len(module._LAYOUT_FACTS) == len(module.LAYOUTS) == 7
    assert {id(layout) for layout, _facts in module._LAYOUT_FACTS} == {id(layout) for layout in module.LAYOUTS.values()}
    for layout, facts in module._LAYOUT_FACTS:
        assert facts == tuple(asdict(layout).values())
