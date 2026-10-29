"""Native-shaped Stage A models. No model is a native qualification claim."""
from __future__ import annotations

import builtins
import dataclasses
import hashlib
import importlib
import json
from array import array
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def prepare_module(addon_package):
    return importlib.import_module(f"{addon_package}.mesh_storage_prepare")


def environment(module, monkeypatch, *, count=3, include_second=True):
    """Assume only native RNA/descriptor qualification; run production protocol.

    FakeAccess models source-qualified passive native metadata and fresh native
    owners. Production plans, gates, buffers, conversion/readback, forward CAS,
    source seals, journals and failure bookkeeping execute unchanged.
    """
    state = NS(attrs={}, generation=0, events=[], providers=0, pure_calls=0,
               stop=False, provider_hook=None, native_hook=None, fail=None,
               view_after_provider=0, snapshot_reads=0, writes=0, buffers=0,
               object_uid="10", mesh_uid="20", object_ref=object(), mesh_ref=object(),
               journal=None, stop_when_returned=False, metadata_change=None,
               absent_getters=0, entered_names=[])
    state.database_identity, state.expected_buffers = "300", 0
    state.uv_roles = (0, (("UV", True, True),))
    state.attrs["UV"] = NS(kind="FLOAT2", domain="CORNER", storage="SINGLE", count=count,
                           values=((-0., 0.5),) * count)
    if include_second:
        state.attrs[".uv_select_face"] = NS(kind="BOOLEAN", domain="FACE", storage="SINGLE", count=1,
                                             values=(False,))

    def header(name, data):
        native, leaf = module._VALUE_CLASSES[data.kind]
        return module.AttributeHeader(name, data.domain, data.kind, native, leaf, data.storage,
                                      data.count, "a" * 64, "b" * 64)

    class NativeAttribute:
        def __init__(self, name):
            self.name, self.generation = name, state.generation

    class NativeCollection:
        def __init__(self, owner):
            self.owner = owner

        def foreach_get(self, field, buffer):
            assert not state.stop, "Native entry after observed stop"
            owner = self.owner
            assert owner.generation == state.generation, "Owner retained across provider/data entry"
            data = state.attrs[owner.name]
            assert field == ("vector" if data.kind == "FLOAT2" else "value")
            converting = data.storage == "SINGLE"
            state.events.append(("foreach", owner.name, converting, len(buffer)))
            if converting:
                state.entered_names.append(owner.name)
                assert state.buffers >= state.expected_buffers, \
                    "All outputs/readback buffers must precede the first conversion"
                data.storage = "ARRAY"  # Argument discovery already materializes.
                state.writes += 1
                state.generation += 1
                if state.fail == "after_materialization":
                    raise MemoryError("Modeled wrapper failure after physical transition")
            values = [component for pair in data.values for component in pair] if data.kind == "FLOAT2" else list(data.values)
            if state.fail == "nonrepeated" and converting and len(values) >= 4:
                values[-1] = 1.
            for index, value in enumerate(values):
                buffer[index] = value
            if state.native_hook:
                state.native_hook(owner.name, converting)

        def __getitem__(self, key):
            assert not state.stop
            assert type(key) is slice and key.start is key.stop is key.step is None
            owner = self.owner
            assert owner.generation == state.generation
            data = state.attrs[owner.name]
            assert data.count == 0 and data.storage == "SINGLE"
            state.events.append(("full_slice", owner.name))
            state.entered_names.append(owner.name)
            state.writes += 1
            data.storage = "ARRAY"
            state.generation += 1
            return []

    class FakeAccess:
        def __init__(self, _bpy, pure):
            self.pure = pure
            pure()

        def database(self):
            self.pure()
            assert not state.stop
            return state.database_identity

        def snapshot(self, _object_name, _mesh_name):
            self.pure()
            assert not state.stop, "Original metadata read after stop"
            state.snapshot_reads += 1
            state.events.append(("metadata", state.generation))
            result = module._Metadata(state.object_ref, state.mesh_ref,
                (("name", "Object"), ("pointer", "100"), ("session_uid", state.object_uid)),
                (("name", "Mesh"), ("pointer", "200"), ("session_uid", state.mesh_uid)),
                state.database_identity,
                (("vertices", 3), ("edges", 3), ("polygons", 1), ("loops", count)),
                state.uv_roles, tuple(header(name, item) for name, item in state.attrs.items()))
            self.pure()
            return result

        def attribute(self, _mesh, selected):
            self.pure()
            assert not state.stop
            state.events.append(("owner", selected.name, state.generation))
            return NativeAttribute(selected.name)

        def field(self, owner, _kind, name):
            self.pure()
            assert name == "data" and not state.stop
            if owner.generation != state.generation:
                state.view_after_provider += 1
                pytest.fail("Borrowed owner crossed a provider")
            result = NativeCollection(owner)
            state.events.append(("data_wrapper", owner.name))
            self.pure()
            return result

    # Model source-defined native-access adapter; production never admits a
    # Python collection as a qualified canonical C binding.
    FakeAccess.__module__ = module.__name__
    monkeypatch.setattr(module, "_Access", FakeAccess)

    def binding_assumption(self):
        assert self.collection_class is NativeCollection

    monkeypatch.setattr(module.CollectionBindings, "verify", binding_assumption)
    bindings = module.CollectionBindings(None, NativeCollection,
        (("foreach_get", NativeCollection.foreach_get), ("__getitem__", NativeCollection.__getitem__)),
        "0" * 64, True)
    real_buffers = module._buffers

    def tracked_buffers(selected):
        state.buffers += 1
        return real_buffers(selected)

    monkeypatch.setattr(module, "_buffers", tracked_buffers)

    def pure():
        state.pure_calls += 1
        if state.stop_when_returned and state.journal and state.journal.rows[0]["materialize_returned"]:
            state.stop = True
        if state.stop:
            raise module.BridgeError(module.ErrorCode.EMERGENCY_STOPPED, "Modeled stop.")

    def authorize():
        assert not state.stop, "Provider after observed stop"
        state.providers += 1
        state.events.append(("provider", state.providers))
        state.generation += 1  # Providers can invalidate old Attribute records.
        if state.provider_hook:
            state.provider_hook()

    origin = module.CaptureOrigin.capture(pure, authorize=authorize)
    state.pure_check, state.authorize = pure, authorize
    names = tuple(state.attrs)
    bpy = object()

    def plan(selected=None, memory=2 * 1024**3):
        return module.build_plan(bpy, "Object", "Mesh", names if selected is None else selected,
            origin=origin, available_memory_bytes=memory)

    def run(preview=None, *, memory=2 * 1024**3, token=None):
        preview = plan() if preview is None else preview
        state.expected_buffers = sum(row.action == "MATERIALIZE_SINGLE" for row in preview.targets)
        state.journal = module.PreparationJournal.for_plan(preview)
        return module.prepare(bpy, preview, bindings=bindings if token is None else token, origin=origin,
                              available_memory_bytes=memory, journal=state.journal)

    state.plan, state.run, state.origin, state.bindings = plan, run, origin, bindings
    state.fake_access = FakeAccess
    return state


def test_complete_boolean_float2_materialization_repeated_signed_zero_and_readback(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    preview = e.plan()
    assert e.writes == 0 and not any(row[0] in {"foreach", "data_wrapper", "full_slice"} for row in e.events)
    assert preview.summary()["SINGLE_pre_value_hash_available"] is False
    result = e.run(preview)
    assert result.values["UV"] == (("00000080", "0000003f"),) * 3
    assert result.values[".uv_select_face"] == (False,)
    assert e.writes == 2 and e.entered_names == ["UV", ".uv_select_face"]
    assert e.view_after_provider == 0
    receipt = result.receipt()
    assert receipt["status"] == "COMPLETE_PREPARED" and receipt["source_equivalent_before_after"]
    assert not receipt["independently_measured_SINGLE_pre_value_hash"]
    assert receipt["requires_fresh_image_preview"] and not receipt["inverse_attempted"]
    assert receipt["resource_facts"]["available_memory_measurement_scope"] == "INITIAL_CALL_ARGUMENT_SNAPSHOT"
    assert all(row["verified"] and row["readback_entries"] == row["readback_returns"] for row in receipt["rows"])
    assert json.dumps(receipt)
    with pytest.raises(TypeError):
        result.values["fake"] = ()
    with pytest.raises(TypeError):
        e.journal.rows[0]["materialize_entered"] = False


def metadata_environment(module, monkeypatch, active, roles):
    """Assume native binding qualification; run the real metadata snapshot.

    No fake storage conversion or UV role normalization is provided. Any UV
    buffer/selection getter fails, so admission can only observe role metadata.
    """
    events = []

    class Layer:
        def __init__(self, row):
            self.row = row

        @property
        def name(self):
            events.append(("role", "name"))
            return self.row[0]

        @property
        def active_render(self):
            events.append(("role", "active_render"))
            return self.row[1]

        @property
        def active_clone(self):
            events.append(("role", "active_clone"))
            return self.row[2]

        def __getattr__(self, name):
            pytest.fail("Unexpected UV getter: " + name)

    class Layers(list):
        @property
        def active_index(self):
            events.append(("role", "active_index"))
            return active

    layers = Layers(Layer(row) for row in roles)
    mesh = NS(name="Mesh", is_editmode=False, shape_keys=None, users=1, is_evaluated=False,
              vertices=[None] * 3, edges=[None] * 3, polygons=[None], loops=[None] * 3,
              has_custom_normals=False, color_attributes=[], uv_layers=layers)
    obj = NS(name="Object", data=mesh, type="MESH", mode="OBJECT", is_evaluated=False)

    class Reader:
        def __init__(self):
            self.catalogs = {}

        def catalog(self, owner, kind):
            events.append(("catalog", kind))

        def class_catalog(self, kind):
            events.append(("class_catalog", kind))

        def local_id(self, owner, kind):
            return {"name": owner.name, "kind": kind, "pointer": "100", "session_uid": "10"}

    class Access(module._Access):
        def __init__(self):
            self.reader = Reader()
            self.bpy = NS(app=NS(build_hash=module.BUILD, version=module.VERSION),
                          data=NS(objects={obj.name: obj}, meshes={mesh.name: mesh}))
            self.pure = lambda: events.append(("gate",))

        def database(self):
            return "300"

    def inventory(reader, actual, counts, names):
        assert actual is mesh and names == tuple(row[0] for row in roles)
        events.append(("inventory",))
        return (), {}, {}, ()

    monkeypatch.setattr(module.graph, "_attribute_inventory", inventory)
    return NS(access=Access(), events=events, mesh=mesh, layers=layers)


@pytest.mark.parametrize("active,roles", [
    (-1, ()),
    (-1, (("UV", False, False),)),
    (0, (("UV", False, False),)),
    (0, (("UV", True, False),)),
    (-1, (("UV", False, True),)),
    (1, (("UV0", False, True), ("UV1", True, False))),
])
def test_metadata_snapshot_preserves_absent_and_independent_uv_roles(prepare_module, monkeypatch, active, roles):
    e = metadata_environment(prepare_module, monkeypatch, active, roles)
    result = e.access.snapshot("Object", "Mesh")
    assert result.uv_roles == (active, roles)
    assert result.plain()["uv_roles"] == (active, roles)
    assert e.mesh.uv_layers is e.layers and tuple(layer.row for layer in e.layers) == roles
    assert e.events[-1] == ("gate",) and e.events.count(("inventory",)) == 1


@pytest.mark.parametrize("active,roles,reason", [
    (True, (("UV", False, False),), "UV_ROLE_SCHEMA"),
    (0., (("UV", False, False),), "UV_ROLE_SCHEMA"),
    (-2, (("UV", False, False),), "UV_ROLE_SCHEMA"),
    (1, (("UV", False, False),), "UV_ROLE_SCHEMA"),
    (0, (), "UV_ROLE_SCHEMA"),
    (0, (("UV0", True, False), ("UV1", True, False)), "UV_ROLE_SCHEMA"),
    (0, (("UV0", False, True), ("UV1", False, True)), "UV_ROLE_SCHEMA"),
    (0, (("UV", False, False), ("UV", False, False)), "DUPLICATE_UV_NAMES"),
    (0, (("UV", 1, False),), "BOOLEAN_SHAPE"),
    (0, (("UV", False, None),), "BOOLEAN_SHAPE"),
    (0, (("UV0", False, False), ("UV1", False, False), ("UV2", False, False)), "COLLECTION_BUDGET"),
])
def test_metadata_invalid_uv_roles_refuse_before_attribute_inventory(prepare_module, monkeypatch, active, roles, reason):
    e = metadata_environment(prepare_module, monkeypatch, active, roles)
    with pytest.raises(prepare_module.BridgeError) as failure:
        e.access.snapshot("Object", "Mesh")
    assert failure.value.context["reason"] == reason
    assert ("inventory",) not in e.events


@pytest.mark.parametrize("active,render,clone", [(-1, False, False), (0, False, False), (-1, True, False)])
def test_preparation_preserves_missing_roles_in_plan_and_forward_state(prepare_module, monkeypatch, active, render, clone):
    e = environment(prepare_module, monkeypatch)
    e.uv_roles = (active, (("UV", render, clone),))
    preview = e.plan()
    result = e.run(preview)
    assert preview.summary()["metadata"]["uv_roles"] == e.uv_roles
    assert result.receipt()["status"] == "COMPLETE_PREPARED"
    assert e.uv_roles == (active, (("UV", render, clone),))
    assert e.writes == 2 and e.view_after_provider == 0


@pytest.mark.parametrize("changed", [(0, (("UV", False, False),)),
                                    (-1, (("UV", True, False),)),
                                    (-1, (("UV", False, True),))])
def test_missing_uv_role_manual_edits_invalidate_plan_before_conversion(prepare_module, monkeypatch, changed):
    e = environment(prepare_module, monkeypatch)
    e.uv_roles = (-1, (("UV", False, False),))
    preview = e.plan()
    e.uv_roles = changed
    with pytest.raises(prepare_module.BridgeError) as failure:
        e.run(preview)
    assert failure.value.context["reason"] == "PREPARATION_FORWARD_METADATA_CAS_CHANGED"
    assert e.writes == 0 and e.entered_names == []


def test_missing_uv_role_provider_edit_keeps_verified_transition_and_stops_next_attribute(prepare_module, monkeypatch):
    e = environment(prepare_module, monkeypatch)
    e.uv_roles = (-1, (("UV", False, False),))
    preview = e.plan()
    edited = (-1, (("UV", False, True),))

    def edit_after_verified():
        if e.journal and e.journal.rows[0]["verified"]:
            e.uv_roles = edited

    e.provider_hook = edit_after_verified
    with pytest.raises(prepare_module.BridgeError) as failure:
        e.run(preview)
    assert failure.value.context["reason"] == "PREPARATION_FORWARD_METADATA_CAS_CHANGED"
    assert e.uv_roles == edited and e.entered_names == ["UV"]
    assert e.attrs["UV"].storage == "ARRAY" and e.attrs[".uv_select_face"].storage == "SINGLE"
    assert e.journal.rows[0]["verified"] and not e.journal.rows[1]["materialize_entered"]
    assert not failure.value.context["mesh_storage_prepare"]["inverse_attempted"]


@pytest.mark.parametrize("field", ["active_index", "active_render", "active_clone"])
def test_foreign_uv_role_scalars_refuse_without_scalar_callbacks(prepare_module, monkeypatch, field):
    class Foreign:
        def __bool__(self):
            pytest.fail("Foreign UV role Boolean conversion ran")

        def __lt__(self, _other):
            pytest.fail("Foreign UV role index comparison ran")

        def __le__(self, _other):
            pytest.fail("Foreign UV role index comparison ran")

        def __gt__(self, _other):
            pytest.fail("Foreign UV role index comparison ran")

        def __ge__(self, _other):
            pytest.fail("Foreign UV role index comparison ran")

    active, render, clone = -1, False, False
    if field == "active_index":
        active = Foreign()
    elif field == "active_render":
        render = Foreign()
    else:
        clone = Foreign()
    e = metadata_environment(prepare_module, monkeypatch, active, (("UV", render, clone),))
    with pytest.raises(prepare_module.BridgeError) as failure:
        e.access.snapshot("Object", "Mesh")
    assert failure.value.context["reason"] == ("UV_ROLE_SCHEMA" if field == "active_index" else "BOOLEAN_SHAPE")
    assert ("inventory",) not in e.events


def test_array_selection_is_metadata_noop_without_data_lookup(prepare_module, monkeypatch):
    e = environment(prepare_module, monkeypatch, include_second=False)
    e.attrs["UV"].storage = "ARRAY"
    result = e.run()
    assert e.writes == 0 and not any(row[0] in {"data_wrapper", "foreach"} for row in e.events)
    assert result.receipt()["status"] == "NOOP_COMPLETE"
    assert not result.receipt()["complete_post_ARRAY_values_verified"]
    assert not result.rows[0]["materialize_entered"]


def test_absent_requested_row_refuses_whole_batch_before_buffers_or_data(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    plan = e.plan(("UV", ".uv_select_edge"))
    assert not plan.summary()["start_admitted"]
    with pytest.raises(m.BridgeError) as failure:
        e.run(plan)
    assert failure.value.context["reason"] == "SELECTED_ABSENT_OR_UNSUPPORTED_ATTRIBUTE"
    assert e.writes == e.buffers == 0
    assert not any(row[0] == "data_wrapper" for row in e.events)


def test_resource_refusal_precedes_conversion_and_reports_known_estimate(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    with pytest.raises(m.BridgeError) as failure:
        e.plan(memory=64 * 1024**2)
    facts = failure.value.context["resource_facts"]
    assert facts["known_array_payload_bytes"] == 25
    assert facts["available_memory_measurement_scope"] == "INITIAL_CALL_ARGUMENT_SNAPSHOT"
    assert not facts["admitted"] and facts["native_OOM_survival"] == "UNPROVEN"
    assert not facts["hard_total_memory_bound"] and not facts["resources_reserved"]
    assert e.writes == 0


def test_stop_after_first_real_return_precedes_provider_metadata_and_next_attribute(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    plan = e.plan()
    e.stop_when_returned = True
    with pytest.raises(m.BridgeError) as failure:
        e.run(plan)
    assert failure.value.code == "EMERGENCY_STOPPED"
    rows = failure.value.context["mesh_storage_prepare"]["rows"]
    assert rows[0]["materialize_entered"] and rows[0]["materialize_returned"]
    assert rows[0]["after_storage"] is None and not rows[0]["verified"]
    assert not rows[1]["materialize_entered"]
    assert e.events[-1] == ("foreach", "UV", True, 6)
    assert e.attrs["UV"].storage == "ARRAY" and e.attrs[".uv_select_face"].storage == "SINGLE"


def test_failure_after_argument_phase_conversion_is_not_reported_as_no_mutation(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    e.fail = "after_materialization"
    with pytest.raises(m.BridgeError) as failure:
        e.run()
    row = failure.value.context["mesh_storage_prepare"]["rows"][0]
    assert row["materialize_entered"] and not row["materialize_returned"] and row["after_storage"] is None
    assert row["retained_physical_transition"] == "ENTERED_OUTCOME_UNKNOWN"
    assert e.writes == 1 and e.attrs["UV"].storage == "ARRAY"
    assert not failure.value.context["mesh_storage_prepare"]["inverse_attempted"]


@pytest.mark.parametrize("change", ["owner_uid", "owner_ref", "database", "storage", "count", "name", "domain", "schema"])
def test_forward_metadata_or_original_owner_drift_refuses_before_entry(prepare_module, monkeypatch, change):
    m = prepare_module
    e = environment(m, monkeypatch)
    plan = e.plan()
    if change == "owner_uid":
        e.mesh_uid = "999"
    elif change == "owner_ref":
        e.mesh_ref = object()
    elif change == "database":
        e.database_identity = "999"
    elif change == "storage":
        e.attrs["UV"].storage = "ARRAY"
    elif change == "count":
        e.attrs["UV"].count = 1
    elif change == "name":
        e.attrs["Renamed"] = e.attrs.pop("UV")
    elif change == "domain":
        e.attrs["UV"].domain = "POINT"
    elif change == "schema":
        e.attrs["UV"].kind = "INT"
    with pytest.raises(m.BridgeError) as failure:
        e.run(plan)
    assert failure.value.context["reason"] == ("PREPARATION_DATABASE_CHANGED" if change == "database" else
                                               "PREPARATION_FORWARD_METADATA_CAS_CHANGED")
    assert e.writes == 0


def test_single_scalar_change_before_first_copy_is_not_claimed_as_value_cas(prepare_module, monkeypatch):
    e = environment(prepare_module, monkeypatch, include_second=False)
    plan = e.plan()
    e.attrs["UV"].values = ((1., -0.),) * 3
    result = e.run(plan)
    assert result.values["UV"] == (("0000803f", "00000080"),) * 3
    assert not result.receipt()["independently_measured_SINGLE_pre_value_hash"]


def test_completed_array_value_change_is_rejected_before_next_materialization(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    def change_after_verified():
        if e.journal and e.journal.rows[0]["verified"]:
            e.attrs["UV"].values = ((1., 1.),) * 3
    e.provider_hook = change_after_verified
    with pytest.raises(m.BridgeError) as failure:
        e.run()
    assert failure.value.context["reason"] == "PREPARED_ARRAY_LOGICAL_BASELINE_CHANGED"
    assert e.entered_names == ["UV"]
    assert e.journal.rows[0]["baseline_conflict"]
    assert not e.journal.rows[1]["materialize_entered"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_nonfinite_first_observation_refuses_after_honest_physical_transition(prepare_module, monkeypatch, bad):
    m = prepare_module
    e = environment(m, monkeypatch)
    e.attrs["UV"].values = ((bad, 0.),) * 3
    with pytest.raises(m.BridgeError) as failure:
        e.run()
    assert failure.value.context["reason"] == "FLOAT2_BUFFER_SHAPE_OR_FINITE"
    assert e.journal.rows[0]["materialize_returned"] and not e.journal.rows[0]["verified"]
    assert e.attrs["UV"].storage == "ARRAY" and not e.journal.rows[1]["materialize_entered"]


def test_nonrepeated_single_expansion_is_rejected(prepare_module, monkeypatch):
    e = environment(prepare_module, monkeypatch)
    e.fail = "nonrepeated"
    with pytest.raises(prepare_module.BridgeError) as failure:
        e.run()
    assert failure.value.context["reason"] == "SINGLE_EXPANSION_NOT_REPEATED_BITS"


def test_zero_domain_uses_qualified_full_slice_and_verifies_empty_array(prepare_module, monkeypatch):
    e = environment(prepare_module, monkeypatch, count=0, include_second=False)
    result = e.run()
    assert e.writes == 1 and ("full_slice", "UV") in e.events
    assert not any(row[0] == "foreach" and row[2] for row in e.events)
    assert result.values["UV"] == ()
    assert result.rows[0]["entry_kind"] == "FULL_SLICE_ZERO_DOMAIN"
    assert result.rows[0]["verified"]


def test_zero_domain_requires_its_descriptor_qualification(prepare_module, monkeypatch):
    e = environment(prepare_module, monkeypatch, count=0, include_second=False)
    token = dataclasses.replace(e.bindings, zero_slice_qualified=False)
    with pytest.raises(prepare_module.BridgeError) as failure:
        e.run(token=token)
    assert failure.value.context["reason"] == "EMPTY_FULL_SLICE_NOT_QUALIFIED"
    assert e.writes == 0


def test_zero_slice_allocation_failure_precedes_data_and_materialize_entry(prepare_module, monkeypatch):
    m = prepare_module
    state = [None]
    def allocation_failure(*_arguments):
        assert state[0].journal is not None
        raise MemoryError("Modeled full-slice argument allocation failure")
    # The model allocator is sealed before capture, rather than replacing a
    # source binding after the origin witness has been established.
    monkeypatch.setattr(m, "slice", allocation_failure, raising=False)
    e = environment(m, monkeypatch, count=0, include_second=False)
    state[0] = e
    with pytest.raises(m.BridgeError):
        e.run()
    assert e.writes == 0 and e.attrs["UV"].storage == "SINGLE"
    assert not e.journal.rows[0]["data_lookup_entered"]
    assert not e.journal.rows[0]["materialize_entered"]
    assert not e.journal.rows[0]["materialize_returned"]


@pytest.mark.parametrize("mutation", ["global_dispatch", "class_dispatch", "foreign_key", "literal_table"])
def test_provider_source_additions_fail_before_foreign_dispatch_or_metadata(prepare_module, monkeypatch, mutation):
    m = prepare_module
    e = environment(m, monkeypatch)
    plan = e.plan()
    native_reads = e.snapshot_reads
    foreign_calls = []
    def foreign(*_args, **_kwargs):
        foreign_calls.append(True)
        pytest.fail("Foreign source dispatch ran")
    class ForeignKey:
        def __hash__(self):
            return 8191
        def __eq__(self, _other):
            foreign()
    def alter():
        if mutation == "global_dispatch":
            # Preserve key count: raw verification must not use newly shadowed
            # builtin dispatch before checking exact namespace membership.
            monkeypatch.delattr(m, "MAX_SELECTED")
            monkeypatch.setattr(m, "any", foreign, raising=False)
        elif mutation == "class_dispatch":
            monkeypatch.setattr(m._Access, "__getattribute__", foreign, raising=False)
        elif mutation == "foreign_key":
            monkeypatch.setitem(m.__dict__, ForeignKey(), object())
        else:
            # Source tables are now recursively immutable tuple rows. Replace
            # the binding rather than raising TypeError inside the provider.
            monkeypatch.setattr(m.graph, "_STATIC_CATALOG_HASHES",
                                (*m.graph._STATIC_CATALOG_HASHES, (b"unqualified", ())))
    e.provider_hook = alter
    with pytest.raises(m.BridgeError) as failure:
        e.run(plan)
    assert failure.value.context["reason"] == "PREPARATION_SOURCE_OR_GATE_CHANGED"
    assert foreign_calls == [] and e.snapshot_reads == native_reads and e.writes == 0


def test_callback_defaults_or_closure_origin_change_before_first_gate_is_refused(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    plan = e.plan()
    e.pure_check.__defaults__ = ("changed",)
    with pytest.raises(m.BridgeError):
        e.run(plan)
    assert e.writes == 0


@pytest.mark.parametrize("when", ["before_entry", "provider"])
def test_guard_dispatcher_code_is_authenticated_before_invocation(prepare_module, monkeypatch, when):
    m = prepare_module
    e = environment(m, monkeypatch)
    plan = e.plan()
    old_code = m._run_guard.__code__
    def no_op(_mode, _seal, _native):
        pytest.fail("Foreign guard dispatcher executed")
    def replace():
        m._run_guard.__code__ = no_op.__code__
    if when == "before_entry":
        replace()
    else:
        e.provider_hook = replace
    try:
        with pytest.raises(m.BridgeError) as failure:
            e.run(plan)
        assert failure.value.context["reason"] == "PREPARATION_SOURCE_OR_GATE_CHANGED"
        assert e.writes == 0
    finally:
        m._run_guard.__code__ = old_code


@pytest.mark.parametrize("entry", ["plan", "prepare"])
@pytest.mark.parametrize("mutation", ["code", "defaults"])
def test_api_entry_never_invokes_changed_guard_bootstrap(prepare_module, monkeypatch, entry, mutation):
    m = prepare_module
    e = environment(m, monkeypatch)
    plan = e.plan()
    before = e.pure_calls, e.providers, e.snapshot_reads
    foreign_calls = []
    bootstrap = m._guards
    old_code, old_defaults = bootstrap.__code__, bootstrap.__defaults__
    def foreign_type(_value):
        foreign_calls.append(True)
        return m.CaptureOrigin
    def foreign_bootstrap(_origin, *_args, **_kwargs):
        raise AssertionError("Foreign guard bootstrap executed")
    if mutation == "code":
        bootstrap.__code__ = foreign_bootstrap.__code__
    else:
        bootstrap.__defaults__ = (old_defaults[0], foreign_type, *old_defaults[2:])
    try:
        with pytest.raises(m.BridgeError) as failure:
            e.plan() if entry == "plan" else e.run(plan)
        assert failure.value.context["reason"] == "PREPARATION_SOURCE_OR_GATE_CHANGED"
        assert foreign_calls == [] and e.writes == 0
        assert (e.pure_calls, e.providers, e.snapshot_reads) == before
    finally:
        bootstrap.__code__, bootstrap.__defaults__ = old_code, old_defaults


def test_origin_dispatch_slots_are_immutable(prepare_module, monkeypatch):
    e = environment(prepare_module, monkeypatch)
    for name in ("_pure", "_verify", "_full"):
        with pytest.raises(AttributeError):
            object.__setattr__(e.origin, name, lambda: pytest.fail("Substituted origin dispatch"))


def test_actual_builtin_dispatch_change_is_caught_before_foreign_call(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    plan = e.plan()
    real_dict = builtins.dict
    foreign_calls = []
    def foreign_dict(*_args, **_kwargs):
        foreign_calls.append(True)
        raise AssertionError("Foreign builtin dict executed")
    def replace():
        builtins.dict = foreign_dict
    e.provider_hook = replace
    try:
        with pytest.raises(m.BridgeError) as failure:
            e.run(plan)
    finally:
        builtins.dict = real_dict
    assert failure.value.context["reason"] == "PREPARATION_SOURCE_OR_GATE_CHANGED"
    assert foreign_calls == [] and e.writes == 0


@pytest.mark.parametrize("when", ["capture", "before_entry"])
@pytest.mark.parametrize("kind", ["subclass", "foreign_key"])
def test_keyword_default_dict_shape_is_checked_without_foreign_methods(prepare_module, monkeypatch, when, kind):
    m = prepare_module
    e = environment(m, monkeypatch)
    plan = e.plan()
    foreign_calls = []
    class ForeignDict(dict):
        def __bool__(self):
            foreign_calls.append("bool")
            raise AssertionError("Foreign kwdefaults bool")
        def items(self):
            foreign_calls.append("items")
            raise AssertionError("Foreign kwdefaults items")
    class ForeignKey:
        def __hash__(self):
            return 382
        def __eq__(self, _other):
            foreign_calls.append("eq")
            raise AssertionError("Foreign kwdefaults key")
    e.pure_check.__kwdefaults__ = ForeignDict() if kind == "subclass" else {ForeignKey(): None}
    with pytest.raises(m.BridgeError):
        if when == "capture":
            m.CaptureOrigin.capture(e.pure_check, authorize=e.authorize)
        else:
            e.run(plan)
    assert foreign_calls == [] and e.writes == 0


@pytest.mark.parametrize("container", ["context", "exception_fields"])
def test_foreign_exception_keys_never_run_during_stopped_failure_bookkeeping(prepare_module, monkeypatch, container):
    m = prepare_module
    e = environment(m, monkeypatch)
    plan = e.plan()
    foreign_calls = []
    class ForeignKey:
        def __hash__(self):
            return hash("mesh_storage_prepare" if container == "context" else "context")
        def __eq__(self, _other):
            foreign_calls.append(True)
            raise AssertionError("Foreign exception key equality ran after stop")
    error = m.BridgeError(m.ErrorCode.EMERGENCY_STOPPED, "Stopped.")
    if container == "context":
        error.context[ForeignKey()] = "foreign"
    else:
        # Remove the real colliding key before inserting the model key.
        del error.__dict__["context"]
        error.__dict__[ForeignKey()] = "foreign"
    def stop():
        e.stop = True
        raise error
    e.provider_hook = stop
    with pytest.raises(m.BridgeError) as failure:
        e.run(plan)
    assert failure.value.context["foreign_exception_context_refused"]
    assert foreign_calls == [] and e.writes == 0
    assert not failure.value.context["mesh_storage_prepare"]["inverse_attempted"]


@pytest.mark.parametrize("which", ["object", "mesh", "attribute"])
@pytest.mark.parametrize("bad", ["é" * 32, "x\x00y", "\ud800"])
def test_native_names_refuse_before_any_authority_or_metadata(prepare_module, monkeypatch, which, bad):
    m = prepare_module
    e = environment(m, monkeypatch)
    arguments = {"object_name": "Object", "mesh_name": "Mesh", "attribute_names": ("UV",)}
    arguments[{"object": "object_name", "mesh": "mesh_name", "attribute": "attribute_names"}[which]] = (bad,) if which == "attribute" else bad
    with pytest.raises(m.BridgeError) as failure:
        m.build_plan(object(), **arguments, origin=e.origin, available_memory_bytes=2 * 1024**3)
    assert failure.value.context["reason"] == "EXACT_NATIVE_NAME_REQUIRED"
    assert e.providers == e.snapshot_reads == e.pure_calls == 0


def test_string_subclass_names_are_not_coerced_or_dispatched(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    class ForeignString(str):
        def encode(self, *_args, **_kwargs):
            pytest.fail("Foreign string encoder dispatched")
    with pytest.raises(m.BridgeError):
        e.plan((ForeignString("UV"),))
    assert e.providers == e.snapshot_reads == 0


def test_partial_later_failure_keeps_previously_verified_forward_state(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    def fail_second(name, converting):
        if name == "UV" and converting:
            e.fail = "after_materialization"
    e.native_hook = fail_second
    with pytest.raises(m.BridgeError) as failure:
        e.run()
    first, second = failure.value.context["mesh_storage_prepare"]["rows"]
    assert first["verified"] and first["after_storage"] == "ARRAY"
    assert second["materialize_entered"] and not second["materialize_returned"]
    assert e.entered_names == ["UV", ".uv_select_face"]


def test_unselected_single_stays_single_and_true_boolean_materializes(prepare_module, monkeypatch):
    e = environment(prepare_module, monkeypatch)
    e.attrs[".uv_select_face"].values = (True,)
    result = e.run(e.plan((".uv_select_face",)))
    assert result.values[".uv_select_face"] == (True,)
    assert e.attrs["UV"].storage == "SINGLE" and e.entered_names == [".uv_select_face"]


def test_typed_buffers_preallocated_and_standalone_format_shape(prepare_module):
    m = prepare_module
    boolean = m.AttributeHeader("flag", "POINT", "BOOLEAN", "BoolAttribute", "BoolAttributeValue", "SINGLE", 3, "a", "b")
    float2 = m.AttributeHeader("uv", "CORNER", "FLOAT2", "Float2Attribute", "Float2AttributeValue", "SINGLE", 3, "a", "b")
    output, readback = m._buffers(boolean)
    assert output.format == readback.format == "?" and not output.readonly and len(output) == 3
    output, readback = m._buffers(float2)
    assert type(output) is array and output.typecode == readback.typecode == "f" and len(output) == 6


def test_native_collection_pin_matches_reviewed_non_aslr_metadata_only(prepare_module):
    m = prepare_module
    # Independent static row from Root's official 5.2.2 metadata-only census.
    # No pointer, instance, factory, functional result or current-process hash.
    row = {
        "schema": "mesh_storage_collection_binding_census_v1", "metadata_only": True, "native_entries": 0,
        "class": {"name": "bpy_prop_collection", "module": "builtins", "flags": 5376,
                  "mro": ["bpy_prop_collection", "bpy_prop", "object"]},
        "bindings": {name: {"name": name, "owner": "bpy_prop_collection", "type": kind} for name, kind in (
            ("__getitem__", "wrapper_descriptor"), ("__iter__", "wrapper_descriptor"),
            ("__len__", "wrapper_descriptor"), ("foreach_get", "method_descriptor"), ("get", "method_descriptor"))},
        "foreach_get_coverage": True, "full_slice_coverage": True,
    }
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    assert hashlib.sha256(encoded).hexdigest() == "01d76c36244d35a22287f12826e7a1d726d9c90951520f58adf29754ccc5b00c"
    expected = {b"d13f752e3b9c": hashlib.sha256(encoded).hexdigest()}
    assert expected == m.COLLECTION_BINDING_PINS
    assert m._COLLECTION_BINDING_PINS is m.COLLECTION_BINDING_PINS


@pytest.mark.parametrize("expected", [None, "", "0" * 64,
    "01D76C36244D35A22287F12826E7A1D726D9C90951520F58ADF29754CCC5B00C", b"0" * 64, True])
def test_unknown_or_wrong_collection_pin_refuses_before_census(prepare_module, monkeypatch, expected):
    m = prepare_module
    monkeypatch.setattr(m, "collection_binding_census", lambda *_: pytest.fail("Unreviewed pin reached metadata"))
    with pytest.raises(m.BridgeError) as failure:
        m.qualify_collection_bindings(None, build_hash=m.BUILD, expected_sha256=expected)
    assert failure.value.context["reason"] == "COLLECTION_BINDING_PIN_NOT_QUALIFIED"


@pytest.mark.parametrize("build", [b"62c1db4208e8", b"d13f752e3b9d", b"", "d13f752e3b9c", None])
def test_unreviewed_collection_build_refuses_before_census(prepare_module, monkeypatch, build):
    m = prepare_module
    monkeypatch.setattr(m, "collection_binding_census", lambda *_: pytest.fail("Unreviewed build reached metadata"))
    with pytest.raises(m.BridgeError) as failure:
        m.qualify_collection_bindings(None, build_hash=build, expected_sha256=m.COLLECTION_BINDING_PINS[m.BUILD])
    assert failure.value.context["reason"] == "EXACT_5_2_BUILD_REQUIRED"


def test_reviewed_pin_still_requires_matching_current_census(prepare_module, monkeypatch):
    m = prepare_module
    calls = []
    def changed_census(types):
        calls.append(types)
        return {"sha256": "f" * 64}
    monkeypatch.setattr(m, "collection_binding_census", changed_census)
    with pytest.raises(m.BridgeError) as failure:
        m.qualify_collection_bindings(None, build_hash=m.BUILD, expected_sha256=m.COLLECTION_BINDING_PINS[m.BUILD])
    assert failure.value.context["reason"] == "COLLECTION_BINDING_CENSUS_CHANGED" and calls == [None]


def test_collection_pin_drift_invalidates_captured_source_before_provider_or_metadata(prepare_module, monkeypatch):
    m = prepare_module
    e = environment(m, monkeypatch)
    before = e.providers, e.snapshot_reads, e.writes, e.buffers
    monkeypatch.setitem(m.COLLECTION_BINDING_PINS, m.BUILD, "f" * 64)
    with pytest.raises(m.BridgeError) as failure:
        e.plan()
    assert failure.value.context["reason"] == "PREPARATION_SOURCE_OR_GATE_CHANGED"
    assert (e.providers, e.snapshot_reads, e.writes, e.buffers) == before


def test_census_is_metadata_only_and_does_not_construct_original_or_factory(prepare_module):
    with pytest.raises(prepare_module.BridgeError) as failure:
        prepare_module.collection_binding_census(object())
    assert failure.value.context["reason"] == "COLLECTION_TYPES_MODULE_REQUIRED"


def test_no_registration_inverse_bmesh_or_evaluation_in_primitive(prepare_module):
    import inspect
    source = inspect.getsource(prepare_module)
    for forbidden in ("bpy.ops", "bmesh.new", "from_mesh(", "frame_set(", "evaluated_get(", "to_mesh(",
                      "attributes.new(", "attributes.remove(", "undo(", "register_tools("):
        assert forbidden not in source
