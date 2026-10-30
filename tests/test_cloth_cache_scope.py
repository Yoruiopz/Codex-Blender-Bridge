"""Cloth admission rejects stored settings, unknown schema and stale scope."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def scope(addon_package):
    return importlib.import_module(f"{addon_package}.tools._cloth_cache_scope")


def request(**changes):
    return {"object_name": "Cloth", "scene_name": "Target", "frame_start": 1, "frame_end": 3, **changes}


@pytest.mark.parametrize("change", [
    {"action": "bake"}, {"action": 1}, {"frame_start": True}, {"frame_end": 1.5},
    {"frame_start": 4}, {"frame_end": 17}, {"frame_start": 0}, {"frame_end": 1048575},
    {"object_name": "é" * 32}, {"scene_name": "bad\x00name"}, {"scene_name": "\ud800"},
    {"unexpected_authority": True},
])
def test_preview_rejects_invalid_or_unbounded_inputs_before_native_access(scope, change):
    with pytest.raises(scope.BridgeError):
        scope.proposal(request(**change))


@pytest.mark.parametrize("value", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, None, 1])
def test_start_requires_exact_lowercase_fingerprint(scope, value):
    with pytest.raises(scope.BridgeError):
        scope.proposal(request(expected_fingerprint=value), starting=True)


@pytest.mark.parametrize("value", [False, 0., 300.1, float("inf"), float("nan"), "60"])
def test_deadline_is_finite_bounded_and_never_bool(scope, value):
    with pytest.raises(scope.BridgeError):
        scope.time_limit({"time_limit_seconds": value})


def test_proposal_and_fingerprint_bind_action_and_range_but_not_job_deadline(scope):
    a = scope.proposal(request())
    b = scope.proposal(request(action="FREE"))
    assert scope.digest(a) != scope.digest(b)
    assert scope.digest(a) != scope.digest(scope.proposal(request(frame_end=4)))
    assert a == scope.proposal(request(time_limit_seconds=1., expected_fingerprint="a" * 64), starting=True)


def test_large_artist_collection_refuses_before_iteration(scope):
    class Oversized:
        def __len__(self):
            return scope.MAX_OBJECTS + 1
        def __iter__(self):
            pytest.fail("Oversized artist collection must not be copied")
    with pytest.raises(scope.BridgeError):
        scope.bounded(Oversized(), scope.MAX_OBJECTS)


def test_collection_budget_identifies_field_and_counts_without_iteration(scope):
    calls = []

    class Oversized:
        def __len__(self):
            calls.append("length")
            return 33

        def __iter__(self):
            pytest.fail("An oversized collection was iterated for diagnostics")

        def __repr__(self):
            pytest.fail("A collection representation was requested for diagnostics")

    with pytest.raises(scope.BridgeError) as caught:
        scope.bounded(Oversized(), 32, field="MeshVertex.groups")
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context == {"reason": "CLOTH_COLLECTION_BUDGET", "scope_complete": False,
        "verification_required": True, "observed_count": 33, "maximum_count": 32, "field": "MeshVertex.groups"}
    assert calls == ["length"]


@pytest.mark.parametrize("actual", [1, 3])
def test_changed_collection_keeps_classification_and_reports_both_counts(scope, actual):
    calls = []

    class Changed:
        def __len__(self):
            calls.append("length")
            return 2

        def __iter__(self):
            calls.append("iteration")
            return iter(range(actual))

    with pytest.raises(scope.BridgeError) as caught:
        scope.bounded(Changed(), 2, field="Scene.objects")
    assert caught.value.context["reason"] == "CLOTH_COLLECTION_CHANGED"
    assert caught.value.context["expected_count"] == 2
    assert caught.value.context["observed_count"] == actual
    assert caught.value.context["maximum_count"] == 2
    assert caught.value.context["field"] == "Scene.objects"
    assert calls.count("iteration") == 1 and calls.count("length") == 2


def test_in_budget_collection_returns_same_detached_tuple(scope):
    first, second = object(), object()
    assert scope.bounded([first, second], 2, field="Scene.objects") == (first, second)
    assert scope.bounded([], 0, field="Scene.objects") == ()


@pytest.mark.parametrize("which,label", [
    ("field", None), ("field", ""), ("field", "x" * 129), ("field", "bad\x00label"), ("field", False), ("field", 1),
    ("owner_type", ""), ("owner_type", "x" * 129), ("owner_type", "bad\x00label"), ("owner_type", False), ("owner_type", 1),
])
def test_unqualified_diagnostic_labels_refuse_before_collection_hooks(scope, which, label):
    class Unread:
        def __len__(self):
            pytest.fail("An unqualified diagnostic label caused a collection read")

        def __iter__(self):
            pytest.fail("An unqualified diagnostic label caused collection iteration")

    params = {"field": "RNA.class.properties", which: label}
    with pytest.raises(scope.BridgeError) as caught:
        scope.bounded(Unread(), 1, **params)
    assert caught.value.context["reason"] == "CLOTH_DIAGNOSTIC_LABEL_INVALID"


@pytest.mark.parametrize("which", ["field", "owner_type"])
def test_foreign_diagnostic_strings_refuse_without_conversion_or_collection_callbacks(scope, which):
    class Foreign(str):
        def __str__(self):
            pytest.fail("A foreign label was converted")

        def __bool__(self):
            pytest.fail("A foreign label Boolean callback ran")

        def __len__(self):
            pytest.fail("A foreign label length callback ran")

        def __repr__(self):
            pytest.fail("A foreign label representation ran")

    class Unread:
        def __len__(self):
            pytest.fail("A foreign label reached collection reads")

    params = {"field": "RNA.class.properties", which: Foreign("Object")}
    with pytest.raises(scope.BridgeError) as caught:
        scope.bounded(Unread(), 1, **params)
    assert caught.value.context["reason"] == "CLOTH_DIAGNOSTIC_LABEL_INVALID"


def test_internal_collection_diagnostics_all_have_source_literal_field_labels(scope):
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(scope))
    sites = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "bounded"]
    assert sites
    for site in sites:
        field = next((keyword.value for keyword in site.keywords if keyword.arg == "field"), None)
        if isinstance(field, ast.Constant):
            assert type(field.value) is str and field.value
        else:
            # The two loops pair native field names with separate literal labels.
            assert isinstance(field, ast.Name) and field.id == "label"
            owner = next(node for node in ast.walk(tree) if isinstance(node, ast.For)
                         and node.lineno <= site.lineno <= node.end_lineno
                         and isinstance(node.target, ast.Tuple)
                         and any(isinstance(item, ast.Name) and item.id == "label" for item in node.target.elts))
            assert isinstance(owner.iter, ast.Tuple)
            assert all(isinstance(pair, ast.Tuple) and len(pair.elts) == 2
                       and all(isinstance(item, ast.Constant) and type(item.value) is str for item in pair.elts)
                       for pair in owner.iter.elts)


class Prop(NS):
    def as_pointer(self):
        return id(self)

    def __getattribute__(self, key):
        if key == "default":
            raise AssertionError("A property default probe is forbidden")
        return super().__getattribute__(key)


@pytest.fixture
def schema_case(scope, monkeypatch):
    class Object:
        def __getattribute__(self, key):
            if key in {"cycles", "selection_sets", "active_selection_set", "field"}:
                raise AssertionError("Runtime/native pointer getter must remain uninvoked")
            return super().__getattribute__(key)
    props = [Prop(identifier=field, type=kind, is_runtime=True, is_readonly=field != "active_selection_set",
                  is_registered=False, array_length=0, fixed_type=NS(identifier=fixed))
             for field, kind, fixed in scope.runtime.DECLARATIONS["Object"]]
    rna = NS(identifier="Object", properties=props, as_pointer=lambda: 42)
    Object.bl_rna = rna
    bpy = NS(types=NS(Object=Object), app=NS(build_hash=b"62c1db4208e8", version=(4, 5, 14)))
    owner, calls, stored = Object(), [], set()
    def presence(actual, field, *, ghost):
        assert actual is owner and ghost is False
        calls.append(field)
        return field in stored
    monkeypatch.setattr(scope.roles, "_particle_class", lambda _bpy, kind: Object)
    monkeypatch.setattr(scope.runtime, "_presence_descriptor", lambda *_: presence)
    return NS(scope=scope, bpy=bpy, owner=owner, props=props, calls=calls, stored=stored)


def test_finite_runtime_absence_does_not_probe_defaults_or_resolve_values(schema_case):
    c = schema_case
    assert c.scope.schema(c.bpy, c.owner) == tuple(c.props)
    assert set(c.calls) == {"cycles", "selection_sets", "active_selection_set"}


def test_rna_property_budget_reports_existing_plain_class_name_before_property_iteration(schema_case):
    c = schema_case

    class OversizedProperties:
        def __len__(self):
            return c.scope.runtime.MAX_PROPERTIES + 1

        def __iter__(self):
            pytest.fail("Oversized RNA properties were iterated")

    c.owner.bl_rna.properties = OversizedProperties()
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.schema(c.bpy, c.owner)
    assert caught.value.context["reason"] == "CLOTH_COLLECTION_BUDGET"
    assert caught.value.context["observed_count"] == c.scope.runtime.MAX_PROPERTIES + 1
    assert caught.value.context["maximum_count"] == c.scope.runtime.MAX_PROPERTIES
    assert caught.value.context["field"] == "RNA.class.properties"
    assert caught.value.context["owner_type"] == "Object" and c.calls == []


@pytest.mark.parametrize("field", ["cycles", "selection_sets", "active_selection_set"])
def test_stored_runtime_even_default_or_ghost_requires_a_value_contract(schema_case, field):
    c = schema_case
    c.stored.add(field)
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.schema(c.bpy, c.owner)
    assert caught.value.context["reason"] == "CLOTH_STORED_RUNTIME_SETTINGS"


def test_late_unknown_runtime_descriptor_refuses_before_any_presence_method(schema_case):
    c = schema_case
    c.props.append(Prop(identifier="late", type="FLOAT", is_runtime=True, is_readonly=False,
                        is_registered=False, array_length=0))
    with pytest.raises(c.scope.BridgeError):
        c.scope.schema(c.bpy, c.owner)
    assert c.calls == []


def test_nonruntime_python_shadow_refuses_before_resolving_field(schema_case, monkeypatch):
    c = schema_case
    c.props.append(Prop(identifier="field", type="POINTER", is_runtime=False, is_readonly=True,
                        is_registered=False, fixed_type=NS(identifier="FieldSettings")))
    monkeypatch.setattr(type(c.owner), "field", property(lambda _: pytest.fail("shadow invoked")), raising=False)
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.schema(c.bpy, c.owner)
    assert caught.value.context["reason"] == "CLOTH_PYTHON_PROPERTY_SHADOW"


@pytest.mark.parametrize("forge_allowed_type", [False, True])
def test_shadow_type_refuses_without_foreign_metaclass_hash_or_equality(schema_case, monkeypatch, forge_allowed_type):
    c, callbacks = schema_case, []

    class ForeignMeta(type):
        def __hash__(cls):
            callbacks.append("hash")
            return hash(c.scope.GetSetDescriptorType)

        def __eq__(cls, _other):
            callbacks.append("equality")
            return forge_allowed_type

    class ForeignDescriptor(metaclass=ForeignMeta):
        def __get__(self, *_args):
            pytest.fail("Unqualified descriptor getter ran")

    c.props.append(Prop(identifier="field", type="POINTER", is_runtime=False, is_readonly=True,
                        is_registered=False, fixed_type=NS(identifier="FieldSettings")))
    monkeypatch.setattr(type(c.owner), "field", ForeignDescriptor(), raising=False)
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.schema(c.bpy, c.owner)
    assert caught.value.context["reason"] == "CLOTH_PYTHON_PROPERTY_SHADOW"
    assert callbacks == [] and c.calls == []


def test_schema_change_during_noncreating_lookup_refuses(schema_case, monkeypatch):
    c = schema_case
    def presence(*_args, **_kwargs):
        c.props[0].as_pointer = lambda: 99
        return False
    monkeypatch.setattr(c.scope.runtime, "_presence_descriptor", lambda *_: presence)
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.schema(c.bpy, c.owner)
    assert caught.value.context["reason"] == "CLOTH_DESCRIPTOR_CHANGED"


def test_preview_cannot_invoke_evaluation_or_prepare_when_receipt_is_absent(scope, monkeypatch):
    monkeypatch.setattr(scope, "_prepared", None)
    class Trap:
        def __getattribute__(self, key):
            pytest.fail("Preview should refuse before Blender access: " + key)
    with pytest.raises(scope.BridgeError) as caught:
        scope.preview(NS(), Trap(), request())
    assert caught.value.context["reason"] == "CLOTH_CONTEXT_PREPARATION_REQUIRED"


def test_uncompleted_preparation_cannot_authorize_a_preview(scope):
    receipt = scope.PreparedContext(NS(), NS(), 0, NS(state="FAILED"), None, None, None, None, None, None, ())
    with pytest.raises(scope.BridgeError) as caught:
        receipt.check(NS(state=NS()), NS())
    assert caught.value.context["reason"] == "CLOTH_CONTEXT_PREPARATION_NOT_COMPLETED"


def test_replacing_runtime_store_cannot_revive_an_old_preparation(scope):
    old, new = NS(evidence_epoch=0), NS(evidence_epoch=0)
    state = NS(_artist_task_plans=new)
    receipt = scope.PreparedContext(state, old, 0, NS(state="SUCCEEDED"), None, None, None, None, None, None, ())
    with pytest.raises(scope.BridgeError) as caught:
        receipt.check(NS(state=state), NS())
    assert caught.value.context["reason"] == "CLOTH_CONTEXT_PREPARATION_NOT_COMPLETED"


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), object()])
def test_geometry_numbers_must_be_finite_and_typed(scope, raw):
    with pytest.raises(scope.BridgeError):
        scope.scalar(raw, "FLOAT")


def test_matrix_projection_preserves_signed_zero_and_all_sixteen_values(scope):
    matrix = ((-0., 1., 2., 3.), (4., 5., 6., 7.), (8., 9., 10., 11.), (12., 13., 14., 15.))
    values = scope.scalar(matrix, "FLOAT", 16)
    assert len(values) == 16 and values[0] == "-0x0.0p+0" and values[-1] == float(15).hex()
    with pytest.raises(scope.BridgeError):
        scope.scalar((*matrix[:3], matrix[3][:3]), "FLOAT", 16)


def native_prop(field, category, *, readonly=False, fixed=None):
    return NS(identifier=field, type=category, is_runtime=False, is_registered=False,
              is_readonly=readonly, array_length=0, fixed_type=NS(identifier=fixed),
              as_pointer=lambda: abs(hash((field, category, fixed))) + 1)


@pytest.fixture
def mesh_model(scope, monkeypatch):
    """Native qualification is assumed; production read/projection/digest run."""
    def owner(kind, props, **values):
        return NS(bl_rna=NS(identifier=kind, properties=tuple(props)), **values)
    monkeypatch.setattr(scope, "schema", lambda _bpy, item, kind=None: item.bl_rna.properties)
    monkeypatch.setattr(scope, "local", lambda *_: None)
    group = owner("VertexGroupElement", [native_prop("group", "INT", readonly=True), native_prop("weight", "FLOAT")],
                  group=0, weight=1.)
    vertex = owner("MeshVertex", [native_prop("co", "FLOAT"), native_prop("groups", "COLLECTION", readonly=True)],
                   co=(0., 0., 0.), groups=[group])
    vertex.bl_rna.properties[0].array_length = 3
    fields = (("shape_keys", "POINTER"), ("vertices", "COLLECTION"), ("edges", "COLLECTION"),
              ("loops", "COLLECTION"), ("polygons", "COLLECTION"), ("attributes", "COLLECTION"), ("materials", "COLLECTION"))
    mesh = owner("Mesh", [native_prop(field, kind, readonly=True) for field, kind in fields], shape_keys=None,
                 vertices=[vertex], edges=[], loops=[], polygons=[], attributes=[], materials=[],
                 as_pointer=lambda: 100, session_uid=10)
    bpy = NS(app=NS(build_hash=b"d13f752e3b9c", version=(5, 2, 2)))
    return NS(scope=scope, bpy=bpy, mesh=mesh, group=group, vertex=vertex, owner=owner)


def test_same_weight_membership_move_changes_complete_mesh_fingerprint(mesh_model):
    c = mesh_model
    before = c.scope.mesh_state(c.bpy, c.mesh)
    c.group.group = 1
    after = c.scope.mesh_state(c.bpy, c.mesh)
    assert c.scope.digest(before) != c.scope.digest(after)


@pytest.mark.parametrize("field,value", [
    ("group", True), ("group", -1), ("group", 32), ("group", 1.),
    ("weight", 1), ("weight", True), ("weight", -.1), ("weight", 1.1),
    ("weight", float("nan")), ("weight", float("inf")),
])
def test_membership_projection_requires_bounded_index_and_finite_float_weight(mesh_model, field, value):
    c = mesh_model
    setattr(c.group, field, value)
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.mesh_state(c.bpy, c.mesh)
    assert caught.value.context["reason"] == "CLOTH_VERTEX_MEMBERSHIP_UNQUALIFIED"


@pytest.mark.parametrize("field,value", [
    ("type", "FLOAT"), ("is_readonly", False), ("is_runtime", True),
    ("is_registered", True), ("array_length", 1),
])
def test_readonly_group_index_requires_exact_native_scalar_metadata(mesh_model, field, value):
    c = mesh_model
    setattr(c.group.bl_rna.properties[0], field, value)
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.vertex_memberships(c.bpy, c.vertex)
    assert caught.value.context["reason"] == "CLOTH_VERTEX_MEMBERSHIP_SCHEMA_CHANGED"


def test_membership_cap_and_duplicate_indices_refuse_before_projection(mesh_model):
    c = mesh_model
    c.vertex.groups = [c.group] * 33
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.vertex_memberships(c.bpy, c.vertex)
    assert caught.value.context["reason"] == "CLOTH_COLLECTION_BUDGET"
    c.vertex.groups = [c.group, c.group]
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.vertex_memberships(c.bpy, c.vertex)
    assert caught.value.context["reason"] == "CLOTH_VERTEX_MEMBERSHIP_UNQUALIFIED"


def attribute_model(c, *, storage="ARRAY", storage_field=True):
    events = []
    class Attribute:
        def __init__(self):
            props = [native_prop("name", "STRING"), native_prop("domain", "ENUM", readonly=True),
                native_prop("data_type", "ENUM", readonly=True),
                native_prop("data", "COLLECTION", readonly=True, fixed="BoolAttributeValue")]
            if storage_field:
                props.append(native_prop("storage_type", "ENUM", readonly=True))
            self.bl_rna = NS(identifier="BoolAttribute", properties=props)
            self.name, self.domain, self.data_type, self._storage = "Selection", "POINT", "BOOLEAN", storage
        @property
        def storage_type(self):
            events.append("storage_type_get")
            assert storage_field, "4.5 absent storage getter must never run"
            return self._storage
        @property
        def data(self):
            events.append("data_get")
            attribute = self
            class Data:
                def __len__(self):
                    return 1
                def __iter__(self):
                    events.append("data_iter")
                    if attribute._storage == "SINGLE":
                        attribute._storage = "ARRAY"
                        events.append("SINGLE_TO_ARRAY")
                    return iter([c.owner("BoolAttributeValue", [native_prop("value", "BOOLEAN")], value=False)])
            return Data()
    return Attribute(), events


@pytest.mark.parametrize("storage", ["SINGLE", "UNKNOWN", "", None, True])
def test_52_single_or_unknown_storage_refuses_before_data_getter_or_iterator(mesh_model, storage):
    c = mesh_model
    attribute, events = attribute_model(c, storage=storage)
    c.mesh.attributes = [attribute]
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.mesh_state(c.bpy, c.mesh)
    assert caught.value.context["reason"] == "CLOTH_ATTRIBUTE_STORAGE_UNSUPPORTED"
    assert events == ["storage_type_get"] and attribute._storage is storage


def test_late_single_attribute_refuses_before_any_earlier_attribute_data_getter(mesh_model):
    c = mesh_model
    first, earlier = attribute_model(c)
    second, later = attribute_model(c, storage="SINGLE")
    c.mesh.attributes = [first, second]
    with pytest.raises(c.scope.BridgeError):
        c.scope.mesh_state(c.bpy, c.mesh)
    assert earlier == later == ["storage_type_get"]
    assert second._storage == "SINGLE"


@pytest.mark.parametrize("field", ["vertices", "edges", "loops", "polygons"])
def test_single_storage_refuses_before_geometry_getters_can_materialize_it(mesh_model, monkeypatch, field):
    c = mesh_model
    attribute, events = attribute_model(c, storage="SINGLE")
    c.mesh.attributes = [attribute]
    read = c.scope.read
    def checked(bpy, owner, key, category, **kwargs):
        if owner is c.mesh and key == field:
            pytest.fail("Geometry getter ran before SINGLE storage refusal")
        return read(bpy, owner, key, category, **kwargs)
    monkeypatch.setattr(c.scope, "read", checked)
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.mesh_state(c.bpy, c.mesh)
    assert caught.value.context["reason"] == "CLOTH_ATTRIBUTE_STORAGE_UNSUPPORTED"
    assert events == ["storage_type_get"]


def test_52_array_storage_is_rechecked_and_copied_without_materialization(mesh_model):
    c = mesh_model
    attribute, events = attribute_model(c)
    c.mesh.attributes = [attribute]
    value = c.scope.mesh_state(c.bpy, c.mesh)
    assert value[3][0][3] == "ARRAY"
    assert events == ["storage_type_get", "storage_type_get", "storage_type_get", "data_get", "data_iter", "storage_type_get"]


@pytest.mark.parametrize("field,value", [
    ("type", "STRING"), ("is_readonly", False), ("is_runtime", True), ("is_registered", True),
])
def test_52_storage_metadata_must_be_exact_before_resolving_value(mesh_model, field, value):
    c = mesh_model
    attribute, events = attribute_model(c)
    setattr(attribute.bl_rna.properties[-1], field, value)
    c.mesh.attributes = [attribute]
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.mesh_state(c.bpy, c.mesh)
    assert caught.value.context["reason"] == "CLOTH_ATTRIBUTE_STORAGE_SCHEMA_CHANGED"
    assert events == []


def test_52_missing_storage_descriptor_refuses_before_any_attribute_value(mesh_model):
    c = mesh_model
    attribute, events = attribute_model(c, storage_field=False)
    c.mesh.attributes = [attribute]
    with pytest.raises(c.scope.BridgeError):
        c.scope.mesh_state(c.bpy, c.mesh)
    assert events == []


def test_45_requires_storage_field_absence_and_does_not_resolve_absent_field(mesh_model):
    c = mesh_model
    c.bpy.app.build_hash, c.bpy.app.version = b"62c1db4208e8", (4, 5, 14)
    attribute, events = attribute_model(c, storage_field=False)
    c.mesh.attributes = [attribute]
    value = c.scope.mesh_state(c.bpy, c.mesh)
    assert value[3][0][3] == "LEGACY_ARRAY_4_5" and events == ["data_get", "data_iter"]
    unexpected, events = attribute_model(c)
    c.mesh.attributes = [unexpected]
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.mesh_state(c.bpy, c.mesh)
    assert caught.value.context["reason"] == "CLOTH_ATTRIBUTE_STORAGE_SCHEMA_CHANGED"
    assert events == []


def generational_mesh(c, *, geometry_drift=None, data_generation_change=False):
    """Model POINT record movement; canonical native qualification assumed."""
    c.bpy.app.build_hash, c.bpy.app.version = b"62c1db4208e8", (4, 5, 14)
    state = NS(generation=0, legacy=False, data_reads=[], created=[], stale_reads=[],
        records=[{"name": "point_value", "domain": "POINT", "category": "FLOAT", "value": .25},
                 {"name": "point_flag", "domain": "POINT", "category": "BOOLEAN", "value": True}])
    class Attribute:
        def __init__(self, record):
            self.record, self.generation = record, state.generation
            kind, value_kind = c.scope.ATTRIBUTE_VALUES[record["category"]]
            props = [native_prop("name", "STRING"), native_prop("domain", "ENUM", readonly=True),
                native_prop("data_type", "ENUM", readonly=True),
                native_prop("data", "COLLECTION", readonly=True, fixed=value_kind)]
            if record.get("schema_drift"):
                props[0].is_readonly = True
            if record.get("storage_field"):
                props.append(native_prop("storage_type", "ENUM", readonly=True))
            self.bl_rna = NS(identifier=kind, properties=tuple(props))
            self.value_kind = value_kind
            state.created.append((record["name"], self.generation))
        def checked(self, field):
            if self.generation != state.generation:
                state.stale_reads.append((field, self.generation, state.generation))
                pytest.fail("Attribute owner crossed a POINT layer-record generation change")
            return self.record[field]
        @property
        def name(self):
            return self.checked("name")
        @property
        def domain(self):
            return self.checked("domain")
        @property
        def data_type(self):
            return self.checked("category")
        @property
        def data(self):
            name, value, category = self.name, self.checked("value"), self.data_type
            state.data_reads.append((name, self.generation))
            if data_generation_change and len(state.data_reads) == 1:
                state.generation += 1
            return [c.owner(self.value_kind, [native_prop("value", category)], value=value)]
    class Attributes:
        def __len__(self):
            return len(state.records)
        def __iter__(self):
            return iter([Attribute(record) for record in state.records])
    class Groups:
        def __len__(self):
            return 0
        def __iter__(self):
            if not state.legacy:
                state.legacy = True
                state.generation += 1
                if geometry_drift is not None:
                    geometry_drift(state)
            return iter(())
    c.mesh.attributes, c.vertex.groups = Attributes(), Groups()
    return state


def test_45_empty_groups_record_insertion_does_not_reuse_admitted_attribute_owners(mesh_model):
    c = mesh_model
    state = generational_mesh(c)
    value = c.scope.mesh_state(c.bpy, c.mesh)
    assert state.legacy and state.generation == 1 and state.stale_reads == []
    assert state.data_reads == [("point_value", 1), ("point_flag", 1)]
    assert ("point_value", 0) in state.created  # Preflight used the older generation.
    assert [attribute[0] for attribute in value[3]] == ["point_value", "point_flag"]
    assert value[2][0][0][1] == ()  # Logical vertex memberships remain empty.


def test_attribute_plan_contains_only_detached_literals_and_survives_owner_invalidation(mesh_model):
    c = mesh_model
    state = generational_mesh(c)
    plan = c.scope.attribute_inventory(c.bpy, c.mesh)
    def literal(value):
        if isinstance(value, tuple):
            return all(literal(item) for item in value)
        return type(value) in {str, bool, int, float, type(None)}
    assert literal(plan)
    tuple(c.vertex.groups)
    assert state.generation == 1 and c.scope.attribute_inventory(c.bpy, c.mesh) == plan
    fresh = c.scope.fresh_attribute(c.bpy, c.mesh, plan, plan[0])
    assert fresh.generation == 1 and state.stale_reads == []


@pytest.mark.parametrize("field,value", [
    ("name", "renamed"), ("domain", "CORNER"), ("category", "INT"),
    ("schema_drift", True), ("storage_field", True),
])
def test_metadata_drift_during_geometry_refuses_before_any_attribute_values(mesh_model, field, value):
    c = mesh_model
    state = generational_mesh(c, geometry_drift=lambda state: state.records[0].__setitem__(field, value))
    with pytest.raises(c.scope.BridgeError):
        c.scope.mesh_state(c.bpy, c.mesh)
    assert state.data_reads == [] and state.stale_reads == []


@pytest.mark.parametrize("change", ["reorder", "remove", "add"])
def test_changed_attribute_inventory_after_geometry_is_not_adopted(mesh_model, change):
    c = mesh_model
    def drift(state):
        if change == "reorder":
            state.records.reverse()
        elif change == "remove":
            state.records.pop()
        else:
            state.records.append({"name": "extra", "domain": "POINT", "category": "BOOLEAN", "value": False})
    state = generational_mesh(c, geometry_drift=drift)
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.mesh_state(c.bpy, c.mesh)
    assert caught.value.context["reason"] == "CLOTH_ATTRIBUTE_INVENTORY_CHANGED"
    assert state.data_reads == [] and state.stale_reads == []


def test_duplicate_attribute_names_refuse_before_geometry_or_values(mesh_model):
    c = mesh_model
    state = generational_mesh(c)
    state.records[1]["name"] = state.records[0]["name"]
    with pytest.raises(c.scope.BridgeError) as caught:
        c.scope.mesh_state(c.bpy, c.mesh)
    assert caught.value.context["reason"] == "CLOTH_ATTRIBUTE_NAMES_AMBIGUOUS"
    assert not state.legacy and state.data_reads == []


def test_next_attribute_owner_is_fresh_after_previous_data_iteration(mesh_model):
    c = mesh_model
    state = generational_mesh(c, data_generation_change=True)
    c.scope.mesh_state(c.bpy, c.mesh)
    assert state.data_reads == [("point_value", 1), ("point_flag", 2)]
    assert state.stale_reads == [] and state.generation == 2


# Exact stock declarations on both source-pinned builds. Their instance values
# are omitted, not admitted as pure callbacks or learned from a factory owner.
RUNTIME_CLASS_FACTS = {
    "Scene": (("cycles", "POINTER", "CyclesRenderSettings"),
              ("cycles_curves", "POINTER", "CyclesCurveRenderSettings")),
    "ViewLayer": (("cycles", "POINTER", "CyclesRenderLayerSettings"),),
    "Mesh": (("cycles", "POINTER", "CyclesMeshSettings"),),
    "Object": (("cycles", "POINTER", "CyclesObjectSettings"),
               ("selection_sets", "COLLECTION", "SelectionSet"),
               ("active_selection_set", "INT", None)),
}


def runtime_declaration_case(scope, monkeypatch, kind, build, descriptor="deferred"):
    """Native class/presence qualification assumed; real schema is exercised."""
    facts = RUNTIME_CLASS_FACTS[kind]
    names = tuple(row[0] for row in facts)
    def instance_getter(self, field):
        if field in names:
            pytest.fail("An omitted runtime instance value was resolved")
        return object.__getattribute__(self, field)
    owner_type = type(kind, (), {"__getattribute__": instance_getter})
    props = [Prop(identifier=field, type=category, is_runtime=True,
                  is_readonly=field != "active_selection_set", is_registered=False,
                  array_length=0, fixed_type=NS(identifier=fixed)) for field, category, fixed in facts]
    rna = NS(identifier=kind, properties=props, as_pointer=lambda: 42)
    owner_type.bl_rna = rna
    class OpaqueRegistration:
        def __getattribute__(self, field):
            pytest.fail("Opaque registration attribute was inspected: " + field)
        def __get__(self, *_args):
            pytest.fail("Opaque registration descriptor was invoked")
        def __repr__(self):
            pytest.fail("Opaque registration representation was requested")
    retained = {}
    for field in names:
        value = (property(lambda _owner: pytest.fail("Foreign callback was called"))
                 if descriptor == "property" else OpaqueRegistration())
        setattr(owner_type, field, value)
        retained[field] = value
    build_hash, version = ((b"62c1db4208e8", (4, 5, 14)) if build == "4.5" else
                           (b"d13f752e3b9c", (5, 2, 2)))
    bpy = NS(types=NS(**{kind: owner_type}), app=NS(build_hash=build_hash, version=version))
    owner, calls, stored = owner_type(), [], set()
    def presence(actual, field, *, ghost):
        assert actual is owner and ghost is False
        calls.append(field)
        return field in stored
    monkeypatch.setattr(scope.roles, "_particle_class", lambda _bpy, _kind: owner_type)
    monkeypatch.setattr(scope.runtime, "_presence_descriptor", lambda *_: presence)
    return NS(scope=scope, bpy=bpy, owner=owner, owner_type=owner_type, props=props,
              calls=calls, stored=stored, retained=retained)


@pytest.mark.parametrize("kind", tuple(RUNTIME_CLASS_FACTS))
@pytest.mark.parametrize("build", ["4.5", "5.2"])
@pytest.mark.parametrize("descriptor", ["deferred", "property"])
def test_omitted_stock_runtime_declarations_do_not_resolve_or_trust_class_objects(scope, monkeypatch, kind, build, descriptor):
    c = runtime_declaration_case(scope, monkeypatch, kind, build, descriptor)
    assert scope.runtime.DECLARATIONS[kind] == RUNTIME_CLASS_FACTS[kind]
    metadata = tuple(scope.runtime._signature(prop) for prop in c.props)
    assert scope.schema(c.bpy, c.owner) == tuple(c.props)
    assert scope.primitives(c.bpy, c.owner) == ()
    assert set(c.calls) == set(c.retained)
    assert tuple(scope.runtime._signature(prop) for prop in c.props) == metadata
    assert all(vars(c.owner_type)[name] is value for name, value in c.retained.items())


@pytest.mark.parametrize("field", ["cycles", "selection_sets", "active_selection_set"])
def test_omitted_runtime_field_cannot_later_be_read_as_native(scope, monkeypatch, field):
    c = runtime_declaration_case(scope, monkeypatch, "Object", "5.2")
    category = next(prop.type for prop in c.props if prop.identifier == field)
    with pytest.raises(scope.BridgeError) as caught:
        scope.read(c.bpy, c.owner, field, category)
    assert caught.value.context["reason"] == "CLOTH_FIELD_SCHEMA_CHANGED"


@pytest.mark.parametrize("field", ["name", "location", "type", "field", "matrix_world"])
@pytest.mark.parametrize("runtime_flag", [False, True, 1, None])
def test_native_field_shadow_or_forged_runtime_flag_refuses_before_getter_and_presence(scope, monkeypatch, field, runtime_flag):
    c = runtime_declaration_case(scope, monkeypatch, "Object", "4.5")
    prop = Prop(identifier=field, type="STRING", is_runtime=runtime_flag, is_readonly=False,
                is_registered=False, array_length=0, fixed_type=NS(identifier=None))
    c.props.append(prop)
    setattr(c.owner_type, field, property(lambda _owner: pytest.fail("Native shadow callback was invoked")))
    with pytest.raises(scope.BridgeError) as caught:
        scope.schema(c.bpy, c.owner)
    expected = ("CLOTH_PYTHON_PROPERTY_SHADOW" if runtime_flag is False else
                "CLOTH_UNKNOWN_RUNTIME_DECLARATION" if runtime_flag is True else "CLOTH_FIELD_SCHEMA_CHANGED")
    assert caught.value.context["reason"] == expected
    assert c.calls == []


@pytest.mark.parametrize("field", ["cycles", "selection_sets", "active_selection_set"])
def test_declared_name_forged_nonruntime_keeps_native_shadow_guard(scope, monkeypatch, field):
    c = runtime_declaration_case(scope, monkeypatch, "Object", "5.2")
    next(prop for prop in c.props if prop.identifier == field).is_runtime = False
    with pytest.raises(scope.BridgeError) as caught:
        scope.schema(c.bpy, c.owner)
    assert caught.value.context["reason"] == "CLOTH_PYTHON_PROPERTY_SHADOW"
    assert c.calls == []


@pytest.mark.parametrize("mutation", ["category", "fixed_type", "readonly", "registered", "array", "missing", "unknown"])
def test_runtime_metadata_exclusion_requires_complete_exact_declarations_before_presence(scope, monkeypatch, mutation):
    c = runtime_declaration_case(scope, monkeypatch, "Object", "4.5")
    if mutation == "category":
        c.props[0].type = "STRING"
    elif mutation == "fixed_type":
        c.props[1].fixed_type.identifier = "ForeignSelectionSet"
    elif mutation == "readonly":
        c.props[1].is_readonly = False
    elif mutation == "registered":
        c.props[1].is_registered = True
    elif mutation == "array":
        c.props[2].array_length = 1
    elif mutation == "missing":
        c.props.pop()
    else:
        c.props.append(Prop(identifier="foreign", type="INT", is_runtime=True, is_readonly=False,
                            is_registered=False, array_length=0, fixed_type=NS(identifier=None)))
    with pytest.raises(scope.BridgeError):
        scope.schema(c.bpy, c.owner)
    assert c.calls == []


@pytest.mark.parametrize("field", ["cycles", "selection_sets", "active_selection_set"])
def test_opaque_runtime_registration_does_not_admit_present_storage_even_ghost_or_default(scope, monkeypatch, field):
    c = runtime_declaration_case(scope, monkeypatch, "Object", "5.2")
    c.stored.add(field)
    with pytest.raises(scope.BridgeError) as caught:
        scope.schema(c.bpy, c.owner)
    assert caught.value.context["reason"] == "CLOTH_STORED_RUNTIME_SETTINGS"
    assert all(vars(c.owner_type)[name] is value for name, value in c.retained.items())


def test_omitted_runtime_metadata_is_rechecked_after_native_absence_read(scope, monkeypatch):
    c = runtime_declaration_case(scope, monkeypatch, "Object", "4.5")
    def changing_presence(_owner, _field, *, ghost):
        assert ghost is False
        c.props[1].is_registered = True
        return False
    monkeypatch.setattr(scope.runtime, "_presence_descriptor", lambda *_: changing_presence)
    with pytest.raises(scope.BridgeError) as caught:
        scope.schema(c.bpy, c.owner)
    assert caught.value.context["reason"] == "CLOTH_DESCRIPTOR_CHANGED"


@pytest.fixture
def clock_case(scope, monkeypatch):
    """Canonical native identity assumed; real schema/read/clock/projection run."""
    import struct
    classes, getters = {}, []
    def f32(value):
        return struct.unpack('=f', struct.pack('=f', value))[0]
    def make(kind, descriptors, **values):
        if kind not in classes:
            class Owner:
                def __getattribute__(self, field):
                    fields = object.__getattribute__(self, '_values')
                    if field in fields:
                        getters.append((kind, field))
                        value = fields[field]
                        return value() if callable(value) else value
                    return object.__getattribute__(self, field)
                def __setattr__(self, field, value):
                    try:
                        values = object.__getattribute__(self, '_values')
                    except AttributeError:
                        values = {}
                    if field in values:
                        values[field] = value
                    else:
                        object.__setattr__(self, field, value)
                def as_pointer(self):
                    return id(self)
            Owner.__name__ = kind
            props = [native_prop(name, category, readonly=readonly, fixed=fixed)
                     for name, category, readonly, fixed in descriptors]
            for name, category, fixed in scope.runtime.DECLARATIONS.get(kind, ()):
                props.append(Prop(identifier=name, type=category, is_runtime=True,
                    is_readonly=name != 'active_selection_set', is_registered=False,
                    array_length=0, fixed_type=NS(identifier=fixed)))
            Owner.bl_rna = NS(identifier=kind, properties=props, as_pointer=lambda: id(Owner))
            classes[kind] = Owner
        result = classes[kind]()
        result._values, result.session_uid = values, id(result)
        return result
    render = make('RenderSettings', [('frame_map_old','INT',False,None),('frame_map_new','INT',False,None)],
                  frame_map_old=100, frame_map_new=100)
    particle = make('ParticleEdit', [])
    unit = make('UnitSettings', [])
    layer = make('ViewLayer', [], objects=NS(active=None))
    scene = make('Scene', [
        ('frame_current','INT',False,None),('frame_subframe','FLOAT',False,None),
        ('frame_float','FLOAT',False,None),('frame_current_final','FLOAT',True,None),
        ('render','POINTER',True,'RenderSettings'),('unit_settings','POINTER',True,'UnitSettings'),
        ('rigidbody_world','POINTER',True,'RigidBodyWorld'),('view_layers','COLLECTION',True,'ViewLayer'),
        ('objects','COLLECTION',True,'Object')], frame_current=7, frame_subframe=.375,
        render=render,unit_settings=unit,rigidbody_world=None,view_layers=[layer],objects=[])
    def raw():
        values = scene._values
        return f32(f32(float(values['frame_current']))+values['frame_subframe'])
    def final():
        values = render._values
        return f32(raw()*f32(float(values['frame_map_old'])/float(values['frame_map_new'])))
    scene._values.update(frame_float=raw,frame_current_final=final)
    bpy = NS(types=NS(**classes), app=NS(build_hash=b'd13f752e3b9c',version=(5,2,2)))
    monkeypatch.setattr(scope.roles,'_particle_class',lambda _bpy,kind:classes[kind])
    monkeypatch.setattr(scope.roles,'_particle_settings',lambda *_:(None,particle))
    monkeypatch.setattr(scope.runtime,'_presence_descriptor',lambda *_:lambda _owner,_field,*,ghost:False)
    monkeypatch.setattr(scope,'local',lambda *_:None)
    return NS(scope=scope,bpy=bpy,scene=scene,render=render,classes=classes,getters=getters,
              raw=raw,final=final,layer=layer,make=make)


def test_frame_mapping_changes_real_scene_projection_and_fingerprint_without_raw_time_change(clock_case):
    c = clock_case
    first = c.scope.scene_state(c.bpy,c.scene,None,target_scene=True)
    first_clock = c.scope.scene_clock(c.bpy,c.scene,c.scope.time_inputs(c.bpy,c.scene))
    c.render._values['frame_map_new'] = 200
    second = c.scope.scene_state(c.bpy,c.scene,None,target_scene=True)
    second_clock = c.scope.scene_clock(c.bpy,c.scene,c.scope.time_inputs(c.bpy,c.scene))
    assert c.scope.digest(first) != c.scope.digest(second)
    assert first_clock['frame'] == second_clock['frame'] == (7,.375)
    assert first_clock['frame_current_final'] == (7.375).hex()
    assert second_clock['frame_current_final'] == (3.6875).hex()
    assert {field for kind,field in c.getters if kind=='RenderSettings'} == {'frame_map_old','frame_map_new'}


def test_authorized_clock_advancement_does_not_change_target_immutable_projection(clock_case):
    c = clock_case
    first = c.scope.scene_state(c.bpy,c.scene,None,target_scene=True)
    home = c.scope.scene_state(c.bpy,c.scene,None,target_scene=False)
    c.scene._values.update(frame_current=16,frame_subframe=0.)
    second = c.scope.scene_state(c.bpy,c.scene,None,target_scene=True)
    assert c.scope.digest(first) == c.scope.digest(second)
    assert c.scope.digest(home) != c.scope.digest(c.scope.scene_state(c.bpy,c.scene,None,target_scene=False))
    assert c.scope.scene_clock(c.bpy,c.scene,c.scope.time_inputs(c.bpy,c.scene)) == c.scope.working_clock((16,0.),c.scope.TimeInputs(100,100))
    assert second[-2] is None and second[-1] == c.layer.as_pointer()


@pytest.mark.parametrize('field', ['render','frame_current','frame_subframe','frame_float','frame_current_final'])
def test_clock_native_shadow_refuses_before_any_time_or_render_getter(clock_case,monkeypatch,field):
    c = clock_case
    monkeypatch.setattr(c.classes['Scene'],field,property(lambda _:pytest.fail('foreign clock callback')),raising=False)
    with pytest.raises(c.scope.BridgeError) as failure:
        inputs = c.scope.time_inputs(c.bpy,c.scene)
        c.scope.scene_clock(c.bpy,c.scene,inputs)
    assert failure.value.context['reason']=='CLOTH_PYTHON_PROPERTY_SHADOW'
    assert c.getters==[]


@pytest.mark.parametrize('field', ['frame_map_old','frame_map_new'])
@pytest.mark.parametrize('change', ['shadow','runtime','category','array','registered','readonly'])
def test_timing_fields_require_exact_native_projection_before_getter(clock_case,monkeypatch,field,change):
    c = clock_case
    prop = next(row for row in c.classes['RenderSettings'].bl_rna.properties if row.identifier==field)
    if change=='shadow':
        monkeypatch.setattr(c.classes['RenderSettings'],field,property(lambda _:pytest.fail('foreign map callback')),raising=False)
    elif change=='runtime':
        prop.is_runtime=True
    elif change=='category':
        prop.type='FLOAT'
    elif change=='array':
        prop.array_length=1
    elif change=='registered':
        prop.is_registered=True
    else:
        prop.is_readonly=True
    with pytest.raises(c.scope.BridgeError):
        c.scope.time_inputs(c.bpy,c.scene)
    assert not any(kind=='RenderSettings' for kind,_name in c.getters)


@pytest.mark.parametrize('field', ['frame_float','frame_current_final'])
def test_one_float32_ulp_of_clock_drift_refuses_without_tolerance(clock_case,field):
    import struct
    c = clock_case
    expected = c.raw() if field=='frame_float' else c.final()
    bits = struct.unpack('=I',struct.pack('=f',expected))[0]
    c.scene._values[field]=struct.unpack('=f',struct.pack('=I',bits+1))[0]
    with pytest.raises(c.scope.BridgeError) as failure:
        c.scope.scene_clock(c.bpy,c.scene,c.scope.time_inputs(c.bpy,c.scene))
    assert failure.value.context['reason']=='CLOTH_EFFECTIVE_CLOCK_INCONSISTENT'


@pytest.mark.parametrize('frame', [(0,-0.),(-100,.375),(1048574,0.0312500037252903),(7,.375)])
@pytest.mark.parametrize('mapping', [(100,100),(100,200),(899,7),(1,900)])
def test_clock_model_matches_explicit_source_float32_stages(scope,frame,mapping):
    import struct
    def f32(value):
        return struct.unpack('=f',struct.pack('=f',value))[0]
    raw = f32(f32(float(frame[0]))+frame[1])
    scale = f32(float(mapping[0])/float(mapping[1]))
    result = scope.working_clock(frame,scope.TimeInputs(*mapping))
    assert result=={'frame':frame,'frame_float':raw.hex(),'frame_current_final':f32(raw*scale).hex()}


def test_failed_preparation_receipt_refuses_before_retained_clock_or_context_getters(scope,monkeypatch):
    store=NS(evidence_epoch=0)
    state=NS(_artist_task_plans=store)
    receipt=scope.PreparedContext(state,store,0,NS(state='FAILED'),None,None,None,None,None,None,())
    monkeypatch.setattr(scope,'_prepared',receipt)
    class NoNative:
        def __getattribute__(self,field):
            pytest.fail('Stale receipt reached native clock/context: '+field)
    with pytest.raises(scope.BridgeError) as failure:
        scope.capture(NS(state=state),NoNative(),scope.proposal(request()))
    assert failure.value.context['reason']=='CLOTH_CONTEXT_PREPARATION_NOT_COMPLETED'


def test_invalid_window_context_refuses_before_any_retained_scene_clock_getter(scope,monkeypatch):
    store=NS(evidence_epoch=0)
    state=NS(_artist_task_plans=store)
    receipt=scope.PreparedContext(state,store,0,NS(state='SUCCEEDED'),object(),None,None,None,None,None,())
    monkeypatch.setattr(scope,'_prepared',receipt)
    monkeypatch.setattr(scope,'time_inputs',lambda *_:pytest.fail('Invalid context reached clock input getter'))
    monkeypatch.setattr(scope, '_clock_read', lambda _bpy, owner, _kind, field: getattr(owner, field))
    bpy=NS(context=NS(mode='OBJECT',window=NS(scene=object())))
    with pytest.raises(scope.BridgeError) as failure:
        scope.capture(NS(state=state),bpy,scope.proposal(request()))
    assert failure.value.context['reason']=='CLOTH_OBJECT_MODE_REQUIRED'


@pytest.mark.parametrize('field',['frame_current','frame_subframe','frame_float','frame_current_final'])
@pytest.mark.parametrize('mutation',['readonly','registered','runtime','array'])
def test_complete_clock_metadata_preflight_precedes_all_clock_getters(clock_case,field,mutation):
    c=clock_case
    prop=next(row for row in c.classes['Scene'].bl_rna.properties if row.identifier==field)
    if mutation=='readonly':
        prop.is_readonly=not prop.is_readonly
    elif mutation=='registered':
        prop.is_registered=True
    elif mutation=='runtime':
        prop.is_runtime=True
    else:
        prop.array_length=1
    with pytest.raises(c.scope.BridgeError):
        c.scope.scene_clock(c.bpy,c.scene,c.scope.TimeInputs(100,100))
    assert c.getters==[]


def test_scene_render_fixed_type_is_qualified_before_pointer_getter(clock_case):
    c=clock_case
    prop=next(row for row in c.classes['Scene'].bl_rna.properties if row.identifier=='render')
    prop.fixed_type.identifier='ForeignSettings'
    with pytest.raises(c.scope.BridgeError):
        c.scope.time_inputs(c.bpy,c.scene)
    assert c.getters==[]


@pytest.fixture
def clock_callback_case(clock_case):
    c = clock_case
    c.manager = object()
    c.screen = c.make("Screen", [("is_animation_playing", "BOOLEAN", True, None)],
                      is_animation_playing=False)
    class AreaTrap:
        def __getattribute__(self, field):
            pytest.fail("An Area getter cannot establish its actual C spacetype: " + field)
    c.area = AreaTrap()
    c.bpy.data = c.make("BlendData", [("window_managers", "COLLECTION", True, "WindowManager")],
                        window_managers=[c.manager])
    c.window = c.make("Window", [("scene", "POINTER", False, "Scene")], scene=c.scene)
    c.edit = c.make("PreferencesEdit", [("use_negative_frames", "BOOLEAN", False, None)], use_negative_frames=False)
    c.preferences = c.make("Preferences", [("edit", "POINTER", True, "PreferencesEdit")], edit=c.edit)
    c.bpy.context = c.make("Context", [
        ("window_manager", "POINTER", True, "WindowManager"), ("screen", "POINTER", True, "Screen"),
        ("area", "POINTER", True, "Area"), ("window", "POINTER", True, "Window"),
        ("mode", "ENUM", True, None), ("preferences", "POINTER", True, "Preferences")],
        window_manager=c.manager, screen=c.screen, area=None, window=c.window, mode="OBJECT", preferences=c.preferences)
    for kind, native in c.classes.items():
        setattr(c.bpy.types, kind, native)
    return c


def test_52_callback_footprint_qualifies_no_playback_and_no_context_area(clock_callback_case):
    c = clock_callback_case
    assert c.scope.clock_callback_context(c.bpy) == (None,)
    assert c.getters == [("BlendData", "window_managers"), ("Context", "window_manager"),
        ("Context", "screen"), ("Screen", "is_animation_playing"), ("Context", "area")]


@pytest.mark.parametrize("failure", ["other_manager", "two_managers", "playback", "area_present"])
def test_52_callback_conditions_refuse_before_any_scene_setter(clock_callback_case, failure):
    c = clock_callback_case
    if failure == "other_manager":
        c.bpy.context.window_manager = object()
    elif failure == "two_managers":
        c.bpy.data._values["window_managers"].append(object())
    elif failure == "playback":
        c.screen._values["is_animation_playing"] = True
    else:
        c.bpy.context.area = c.area
    with pytest.raises(c.scope.BridgeError):
        c.scope.clock_callback_context(c.bpy)
    assert not any(kind == "Scene" for kind, _field in c.getters)


@pytest.mark.parametrize("kind,field", [
    ("BlendData", "window_managers"), ("Screen", "is_animation_playing"),
    ("Context", "window_manager"), ("Context", "screen"), ("Context", "area"),
    ("Context", "window"), ("Context", "mode"),
])
@pytest.mark.parametrize("change", ["shadow", "literal_none", "runtime", "registered", "readonly", "category"])
def test_callback_native_field_qualification_precedes_its_getter(clock_callback_case, monkeypatch, kind, field, change):
    c = clock_callback_case
    native = c.classes[kind]
    prop = next(row for row in native.bl_rna.properties if row.identifier == field)
    if change == "shadow":
        monkeypatch.setattr(native, field, property(lambda _: pytest.fail("Callback field shadow ran")), raising=False)
    elif change == "literal_none":
        monkeypatch.setattr(native, field, None, raising=False)
    elif change == "runtime":
        prop.is_runtime = True
    elif change == "registered":
        prop.is_registered = True
    elif change == "readonly":
        prop.is_readonly = not prop.is_readonly
    else:
        prop.type = "STRING"
    with pytest.raises(c.scope.BridgeError):
        c.scope.clock_callback_context(c.bpy)
    assert (kind, field) not in c.getters
    if kind == "Context":
        assert not any(owner == "Context" for owner, _field in c.getters)


def test_45_raw_frame_setter_has_no_52_context_update_getters(clock_callback_case):
    c = clock_callback_case
    c.bpy.app.build_hash, c.bpy.app.version = b"62c1db4208e8", (4, 5, 14)
    assert c.scope.clock_callback_context(c.bpy) is None
    assert c.getters == []


@pytest.fixture
def capture_clock_case(clock_callback_case, monkeypatch):
    """Run production capture/preview and clock guards around a modeled data read."""
    c = clock_callback_case
    monkeypatch.setattr(c.scope, "_clock_pointer", lambda _bpy, owner: owner.as_pointer())
    store = NS(evidence_epoch=0)
    state = NS(_artist_task_plans=store)
    c.context = NS(state=state)
    c.obj = NS(name="Cloth", hide_get=lambda: False, visible_get=lambda: True)
    c.scene._values["name"] = "Target"
    c.bpy.context.mode = "OBJECT"
    c.bpy.context.window = c.window
    c.bpy.context.view_layer = NS(objects=NS(get=lambda _name: c.obj))
    c.prepared = c.scope.PreparedContext(state, store, 0, NS(state="SUCCEEDED"),
        c.scene, object(), c.obj, object(), object(), None, ())
    c.scene._values["objects"] = [c.prepared.empty, c.obj]
    monkeypatch.setattr(c.scope, "_prepared", c.prepared)
    monkeypatch.setattr(c.scope.PreparedContext, "check", lambda *_: None)
    read = c.scope.read
    monkeypatch.setattr(c.scope, "read", lambda bpy, owner, field, category, **kwargs:
        owner.name if field == "name" else read(bpy, owner, field, category, **kwargs))
    monkeypatch.setattr(c.scope.roles, "context", lambda _bpy:
        (1, 2, 3, 4, 5, 6, c.scene.frame_current, c.scene.frame_subframe.hex()))
    monkeypatch.setattr(c.scope, "cloth_state", lambda *_:
        (None, None, (), {"range": (1, 3), "step": 1, "baked": False}))
    monkeypatch.setattr(c.scope, "consumers", lambda *_: None)
    c.after_static = lambda: None
    def static_data(*_args):
        timing = c.scope.time_inputs(c.bpy, c.scene)
        c.after_static()
        return (None, None, None, (None, None, timing))
    monkeypatch.setattr(c.scope, "static_data", static_data)
    return c


def test_real_preview_binds_immutable_mapping_and_callback_admission(capture_clock_case):
    c = capture_clock_case
    first = c.scope.preview(c.context, c.bpy, request())[-1]
    c.render._values["frame_map_new"] = 200
    second = c.scope.preview(c.context, c.bpy, request())[-1]
    assert first != second
    c.bpy.context.area = c.area
    with pytest.raises(c.scope.BridgeError) as failure:
        c.scope.preview(c.context, c.bpy, request())
    assert failure.value.context["reason"] == "CLOTH_CLOCK_VSE_CONTEXT_UNSUPPORTED"


@pytest.mark.parametrize("field", ["mode", "window", "window_manager", "screen", "area", "preferences"])
@pytest.mark.parametrize("literal_none", [False, True])
def test_context_shadow_refuses_before_capture_clock_context_or_mode_getters(capture_clock_case, monkeypatch, field, literal_none):
    c = capture_clock_case
    monkeypatch.setattr(c.classes["Context"], field,
        None if literal_none else property(lambda _: pytest.fail("A Context shadow was invoked")), raising=False)
    with pytest.raises(c.scope.BridgeError) as failure:
        c.scope.preview(c.context, c.bpy, request())
    assert failure.value.context["reason"] == "CLOTH_PYTHON_PROPERTY_SHADOW"
    assert c.getters == []


@pytest.mark.parametrize("change", ["shadow", "runtime", "registered", "readonly", "fixed_type"])
def test_window_scene_origin_is_qualified_before_its_getter_and_scene_clock(capture_clock_case, monkeypatch, change):
    c = capture_clock_case
    prop = c.classes["Window"].bl_rna.properties[0]
    if change == "shadow":
        monkeypatch.setattr(c.classes["Window"], "scene",
            property(lambda _: pytest.fail("A Window Scene shadow was invoked")), raising=False)
    elif change == "runtime":
        prop.is_runtime = True
    elif change == "registered":
        prop.is_registered = True
    elif change == "readonly":
        prop.is_readonly = True
    else:
        prop.fixed_type.identifier = "Object"
    with pytest.raises(c.scope.BridgeError):
        c.scope.preview(c.context, c.bpy, request())
    assert ("Window", "scene") not in c.getters
    assert not any(owner == "Scene" for owner, _field in c.getters)


@pytest.mark.parametrize("drift", ["area", "playback", "manager", "mapping", "raw_time"])
def test_real_capture_refuses_clock_or_callback_drift_inside_the_data_getter_window(capture_clock_case, drift):
    c = capture_clock_case
    def alter():
        if drift == "area":
            c.bpy.context.area = c.area
        elif drift == "playback":
            c.screen._values["is_animation_playing"] = True
        elif drift == "manager":
            c.bpy.context.window_manager = object()
        elif drift == "mapping":
            c.render._values["frame_map_new"] = 200
        else:
            c.scene._values["frame_subframe"] = .5
    c.after_static = alter
    with pytest.raises(c.scope.BridgeError):
        c.scope.capture(c.context, c.bpy, c.scope.proposal(request()))


@pytest.mark.parametrize("action", ["FREE", "INVALIDATE"])
def test_non_bake_capture_does_not_introduce_raw_setter_ui_restrictions(capture_clock_case, action):
    c = capture_clock_case
    c.bpy.context.area = c.area
    c.screen._values["is_animation_playing"] = True
    snapshot = c.scope.capture(c.context, c.bpy, c.scope.proposal(request(action=action)))[3]
    assert snapshot["clock_callback_context"] is None
    assert not any(kind == "Screen" for kind, _field in c.getters)


def test_unrepresentable_negative_subframe_under_clamping_policy_refuses_before_the_job_data_read(capture_clock_case, monkeypatch):
    c = capture_clock_case
    c.scene._values.update(frame_current=0, frame_subframe=-float.fromhex("0x1p-149"))
    monkeypatch.setattr(c.scope, "static_data", lambda *_:
        pytest.fail("A negative subframe cannot reach the job data/native plan"))
    with pytest.raises(c.scope.BridgeError) as failure:
        c.scope.preview(c.context, c.bpy, request())
    assert failure.value.context["reason"] == "CLOTH_CALLER_CLOCK_RESTORATION_UNQUALIFIED"


@pytest.mark.parametrize("kind,field", [
    ("Context", "preferences"), ("Preferences", "edit"), ("PreferencesEdit", "use_negative_frames"),
])
@pytest.mark.parametrize("change", ["shadow", "literal_none", "registered", "runtime", "readonly", "category"])
def test_negative_policy_getters_require_exact_native_origin_before_access(capture_clock_case, monkeypatch, kind, field, change):
    c = capture_clock_case
    native = c.classes[kind]
    prop = next(row for row in native.bl_rna.properties if row.identifier == field)
    if change in {"shadow", "literal_none"}:
        monkeypatch.setattr(native, field, None if change == "literal_none" else
            property(lambda _: pytest.fail("A preference shadow ran")), raising=False)
    elif change == "registered":
        prop.is_registered = True
    elif change == "runtime":
        prop.is_runtime = True
    elif change == "readonly":
        prop.is_readonly = not prop.is_readonly
    else:
        prop.type = "FLOAT"
    with pytest.raises(c.scope.BridgeError):
        c.scope.negative_frame_policy(c.bpy)
    assert (kind, field) not in c.getters


@pytest.mark.parametrize("drift", ["bit", "preferences_pointer", "edit_pointer"])
def test_preference_bit_and_native_pointers_are_bound_across_the_capture_window(capture_clock_case, drift):
    c = capture_clock_case
    if drift == "bit":
        c.after_static = lambda: setattr(c.edit, "use_negative_frames", True)
    else:
        target = c.preferences if drift == "preferences_pointer" else c.edit
        monkey_id = target.as_pointer() + 1
        c.after_static = lambda: setattr(target, "as_pointer", lambda: monkey_id)
    with pytest.raises(c.scope.BridgeError) as failure:
        c.scope.preview(c.context, c.bpy, request())
    assert failure.value.context["reason"] == "CLOTH_CAPTURE_NEGATIVE_FRAME_POLICY_CHANGED"


def test_native_pointer_method_shadow_is_rejected_without_invocation(clock_callback_case):
    c = clock_callback_case
    c.bpy.types.bpy_struct = NS(as_pointer=lambda _: pytest.fail("A pointer provider shadow ran"))
    with pytest.raises(c.scope.BridgeError) as failure:
        c.scope._clock_pointer(c.bpy, c.preferences)
    assert failure.value.context["reason"] == "CLOTH_CLOCK_POINTER_ORIGIN_UNQUALIFIED"


def test_real_preview_fingerprint_changes_with_selected_negative_policy(capture_clock_case):
    c = capture_clock_case
    first = c.scope.preview(c.context, c.bpy, request())[-1]
    c.edit.use_negative_frames = True
    second = c.scope.preview(c.context, c.bpy, request())[-1]
    assert first != second
    assert c.scene.frame_current == 7 and c.scene.frame_subframe == .375


@pytest.mark.parametrize("frame", [(-1048574, -.0625), (-2, -1.), (2, -.625)])
def test_non_native_negative_pair_has_no_restoration_route_before_job_data_read(capture_clock_case, monkeypatch, frame):
    c = capture_clock_case
    c.edit.use_negative_frames = True
    c.scene._values.update(frame_current=frame[0], frame_subframe=frame[1])
    monkeypatch.setattr(c.scope, "static_data", lambda *_: pytest.fail("No unsupported-clock cache intent is admitted"))
    with pytest.raises(c.scope.BridgeError) as failure:
        c.scope.preview(c.context, c.bpy, request())
    assert failure.value.context["reason"] == "CLOTH_CALLER_CLOCK_RESTORATION_UNQUALIFIED"


@pytest.fixture
def dynamic_polygon_mesh(mesh_model):
    """Pinned RNA uses nominal length three for each dynamic face vertex array."""
    c = mesh_model
    def build(indices, *, count=None, vertices=8, loops=None):
        c.mesh.vertices = [c.vertex] * vertices
        loop_size = len(indices) if loops is None else loops
        c.mesh.loops = [c.owner("MeshLoop", [
            native_prop("vertex_index", "INT", readonly=True),
            native_prop("edge_index", "INT", readonly=True)], vertex_index=0, edge_index=0)
            for _ in range(loop_size)]
        calls = []
        class Polygon(NS):
            @property
            def vertices(self):
                calls.append("vertices")
                return indices
        array = native_prop("vertices", "INT")
        array.array_length = 3
        c.mesh.polygons = [Polygon(bl_rna=NS(identifier="MeshPolygon", properties=(
            array, native_prop("loop_total", "INT", readonly=True), native_prop("material_index", "INT"))),
            loop_total=len(indices) if count is None else count, material_index=0)]
        return calls
    c.polygon = build
    return c


@pytest.mark.parametrize("indices", [(0, 1, 2), (0, 1, 2, 3), (0, 1, 2, 3, 4), tuple(range(256))])
def test_dynamic_polygon_records_complete_topology_once_not_nominal_rna_length(dynamic_polygon_mesh, indices):
    c = dynamic_polygon_mesh
    calls = c.polygon(indices, vertices=max(indices) + 1)
    state = c.scope.mesh_state(c.bpy, c.mesh)
    assert state[2][3] == (((("material_index", 0),), indices),)
    assert calls == ["vertices"]
    assert c.mesh.polygons[0].bl_rna.properties[0].array_length == 3


def test_dynamic_polygon_last_corner_and_order_changes_alter_structural_fingerprint(dynamic_polygon_mesh):
    c = dynamic_polygon_mesh
    fingerprints = []
    for indices in ((0, 1, 2, 3), (0, 1, 2, 4), (0, 2, 1, 3)):
        c.polygon(indices)
        fingerprints.append(c.scope.digest(c.scope.mesh_state(c.bpy, c.mesh)))
    assert len(set(fingerprints)) == 3


@pytest.mark.parametrize("count", [True, 4., "4", 0, 2, -1, 5])
def test_dynamic_polygon_invalid_loop_total_refuses_before_vertices_getter(dynamic_polygon_mesh, count):
    c = dynamic_polygon_mesh
    calls = c.polygon((0, 1, 2, 3), count=count)
    with pytest.raises(c.scope.BridgeError) as failure:
        c.scope.mesh_state(c.bpy, c.mesh)
    assert failure.value.context["reason"] == "CLOTH_POLYGON_TOPOLOGY_UNQUALIFIED"
    assert calls == []


@pytest.mark.parametrize("indices,count", [
    ((0, 1, 2), 4), ((0, 1, 2, 3), 3), ((0, 1, 2, True), 4),
    ((0, 1, 2, 3.), 4), ((0, 1, 2, -1), 4), ((0, 1, 2, 8), 4),
])
def test_dynamic_polygon_shape_and_indices_remain_exact_typed_and_in_bounds(dynamic_polygon_mesh, indices, count):
    c = dynamic_polygon_mesh
    calls = c.polygon(indices, count=count, loops=4)
    with pytest.raises(c.scope.BridgeError) as failure:
        c.scope.mesh_state(c.bpy, c.mesh)
    assert failure.value.context["reason"] in {"CLOTH_POLYGON_TOPOLOGY_UNQUALIFIED", "CLOTH_COLLECTION_BUDGET"}
    assert calls == ["vertices"]


def test_dynamic_polygon_retains_existing_256_array_bound(dynamic_polygon_mesh):
    c = dynamic_polygon_mesh
    calls = c.polygon(tuple(range(257)), vertices=256)
    with pytest.raises(c.scope.BridgeError) as failure:
        c.scope.mesh_state(c.bpy, c.mesh)
    assert failure.value.context == {"reason": "CLOTH_COLLECTION_BUDGET", "scope_complete": False,
        "verification_required": True, "field": "MeshPolygon.vertices", "observed_count": 257,
        "maximum_count": 256}
    assert calls == ["vertices"]


def test_other_rna_arrays_keep_their_exact_declared_length(scope):
    with pytest.raises(scope.BridgeError) as failure:
        scope.scalar((0., 1., 2., 3.), "FLOAT", 3)
    assert failure.value.context["maximum_count"] == 3
