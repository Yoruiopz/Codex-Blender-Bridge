"""Pure intent/observation models; no native ownership or preservation proof."""
from __future__ import annotations

import importlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from test_asset_glb_import_plan import glb, triangle


@pytest.fixture
def model(addon_package, tmp_path):
    module = importlib.import_module(addon_package + ".glb_stage_state")
    source_module = importlib.import_module(addon_package + ".glb_stage_source")
    root = tmp_path / "approved"
    root.mkdir()
    path = root / "asset.glb"
    manifest, binary = triangle()
    path.write_bytes(glb(manifest, binary))
    source = source_module.read_glb_source(str(path), str(root))
    return module, module.GLBStageStore(), source


@pytest.mark.parametrize("field", ["uv", "normals", "local_matrix", "world_matrix", "parent"])
def test_structural_plan_fields_are_bound_before_any_creation(addon_package, tmp_path, field):
    module = importlib.import_module(addon_package + ".glb_stage_state")
    source_module = importlib.import_module(addon_package + ".glb_stage_source")
    manifest, binary = triangle(normals=True, uv=True)
    manifest["nodes"] = [{"children": [1], "translation": [2., 3., 4.]}, {"mesh": 0}]
    path = tmp_path / "structured.glb"
    path.write_bytes(glb(manifest, binary))
    source = source_module.read_glb_source(str(path), str(tmp_path))
    store = module.GLBStageStore()
    record = store.prepare(source, "Structured", "a" * 64, overwrite_policy="REFUSE")
    assert len(record.intent.allocation_names) == 6
    assert record.intent.plan.required_accepted_losses[-2:] == ("UV_ORIGIN_CONVERSION", "NORMAL_STORAGE_QUANTIZATION")
    if field in {"uv", "normals"}:
        primitive = record.intent.plan.meshes[0].primitives[0]
        object.__setattr__(primitive, "texcoords" if field == "uv" else "normals", None)
    else:
        node = record.intent.plan.nodes[1]
        if field == "parent":
            object.__setattr__(node, "parent_index", None)
        else:
            object.__setattr__(node, field, tuple(tuple(float(r == c) * 2 for c in range(4)) for r in range(4)))
    with pytest.raises(module.invalid_argument("x").__class__):
        store.begin(record.intent.preview_id, record.intent.fingerprint,
                    list(record.intent.plan.required_accepted_losses))
    assert store.lookup(record.intent.stage_id).phase == "PREPARED"
    assert not store.lookup(record.intent.stage_id).allocations


def prepare(model, name="Imported Asset"):
    _module, store, source = model
    return store.prepare(source, name, "a" * 64, overwrite_policy="REFUSE")


def begin(model):
    _, store, _ = model
    record = prepare(model)
    return store.begin(record.intent.preview_id, record.intent.fingerprint,
                       list(record.intent.plan.required_accepted_losses))


def record_expected(model, record):
    _, store, _ = model
    for index, (role, name) in enumerate(record.intent.allocation_names):
        store.note_allocation(record.intent.stage_id, role, name, index + 1, index + 1000)


def test_prepare_seals_stage_lookup_before_any_allocation(model, monkeypatch):
    _module, store, source = model
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: pytest.fail("state opened a path"))
    record = prepare(model)
    assert store.lookup(record.intent.stage_id) is record
    assert record.phase == "PREPARED" and not record.allocations
    assert record.intent.source is source
    assert record.intent.plan.source_sha256 == source.sha256
    assert store.retained_bytes == record.intent.accounted_bytes
    assert tuple(role for role, _ in record.intent.allocation_names) == (
        "collection", "mesh:0", "material:0", "node_tree:0", "object:0")
    assert record.intent.allocation_names[0] == ("collection", "Imported Asset")
    assert dict(record.intent.allocation_names)["node_tree:0"] == "Shader Nodetree"
    with pytest.raises(FrozenInstanceError):
        record.intent.collection_name = "different"
    with pytest.raises(FrozenInstanceError):
        record.phase = "PUBLISHED"
    assert all(store.inspect(record.intent.stage_id)[key] is False for key in (
        "native_ownership_verified", "native_allocation_inventory_verified",
        "live_request_or_permission_verified", "durable_recovery_verified", "project_saved"))


@pytest.mark.parametrize("value", [True, "", " ", "x" * 41, "é" * 21, "bad\0name", "bad\x7fname", "\ud800"])
def test_name_refusals_do_not_create_lookup_entries(model, value):
    module, store, source = model
    with pytest.raises((module.invalid_argument("x").__class__, UnicodeError)):
        store.prepare(source, value, "a" * 64, overwrite_policy="REFUSE")
    assert not store._records and store.retained_bytes == 0


@pytest.mark.parametrize("name", ["Imported Asset.N0", "Other", "shader Nodetree"])
def test_embedded_observation_requires_exact_stock_constructor_name(model, name):
    module, store, _ = model
    record = begin(model)
    with pytest.raises(module.invalid_argument("x").__class__):
        store.note_allocation(record.intent.stage_id, "node_tree:0", name, 10, 1000)
    assert store.lookup(record.intent.stage_id).allocations == ()
    store.note_allocation(record.intent.stage_id, "node_tree:0", "Shader Nodetree", 10, 1000)
    assert store.inspect(record.intent.stage_id)["observed_allocations"] == [
        {"role": "node_tree:0", "name": "Shader Nodetree", "native_uid": 10, "pointer": 1000}]


@pytest.mark.parametrize("value", [None, True, "", "A" * 64, "a" * 63, "z" * 64])
def test_destination_fingerprint_is_strict_plain_data(model, value):
    module, store, source = model
    with pytest.raises(module.invalid_argument("x").__class__):
        store.prepare(source, "Asset", value, overwrite_policy="REFUSE")
    assert not store._records


@pytest.mark.parametrize("value", [None, True, "REPLACE", "refuse"])
def test_overwrite_policy_never_infers_replace_permission(model, value):
    module, store, source = model
    with pytest.raises(module.invalid_argument("x").__class__):
        store.prepare(source, "Asset", "a" * 64, overwrite_policy=value)
    assert not store._records


@pytest.mark.parametrize("kind", ["unparsed", "unknown_loss", "source_callback_drift"])
def test_independent_planning_cannot_adopt_unsupported_or_rebased_intent(model, monkeypatch, kind):
    module, store, source = model
    if kind == "unparsed":
        object.__setattr__(source, "payload", b"x" * len(source.payload))
    elif kind == "unknown_loss":
        planner = module.plan_glb
        def unknown_loss(payload, check):
            return replace(planner(payload, check), required_accepted_losses=("UNQUALIFIED",))
        monkeypatch.setattr(module, "plan_glb", unknown_loss)

    def check():
        if kind == "source_callback_drift":
            object.__setattr__(source, "approved_root", "/a different root")

    with pytest.raises(module.invalid_argument("x").__class__):
        store.prepare(source, "Asset", "a" * 64, overwrite_policy="REFUSE", check=check)
    assert not store._records


def test_prepared_and_consumed_records_have_separate_lifetime_semantics(model):
    module, store, _ = model
    prepared = prepare(model)
    active = store.begin(prepared.intent.preview_id, prepared.intent.fingerprint,
                         list(prepared.intent.plan.required_accepted_losses))
    assert active.possible_mutation and active.phase == "ALLOCATING"
    assert prepared.phase == "PREPARED"  # An earlier immutable observation stays historical.
    with pytest.raises(module.invalid_argument("x").__class__):
        store.begin(prepared.intent.preview_id, prepared.intent.fingerprint,
                    list(prepared.intent.plan.required_accepted_losses))


@pytest.mark.parametrize("kind", ["wrong_handle", "wrong_digest", "wrong_loss", "loss_order", "tuple", "expired", "invalidated"])
def test_begin_refuses_stale_or_inexact_acceptance_without_allocating(model, monkeypatch, kind):
    module, store, _ = model
    r = prepare(model)
    identifier, fingerprint = r.intent.preview_id, r.intent.fingerprint
    losses = list(r.intent.plan.required_accepted_losses)
    if kind == "wrong_handle":
        identifier = "glb_preview_" + "0" * 32
    elif kind == "wrong_digest":
        fingerprint = "0" * 64
    elif kind == "wrong_loss":
        losses.append("UNQUALIFIED_LOSS")
    elif kind == "loss_order":
        losses.reverse()
    elif kind == "tuple":
        losses = tuple(losses)
    elif kind == "expired":
        monkeypatch.setattr(module.time, "monotonic", lambda: r.intent.expires_at)
    else:
        store.invalidate()
    with pytest.raises(module.invalid_argument("x").__class__):
        store.begin(identifier, fingerprint, losses)
    assert not store.lookup(r.intent.stage_id).allocations


@pytest.mark.parametrize("kind", ["plan", "source", "name", "names", "destination"])
def test_retained_frozen_intent_is_rechecked_before_consumption(model, kind):
    module, store, _ = model
    r = prepare(model)
    if kind == "plan":
        object.__setattr__(r.intent.plan, "coordinate_unit", "UNQUALIFIED")
    elif kind == "source":
        object.__setattr__(r.intent.source, "sha256", "a" * 64)
    elif kind == "name":
        object.__setattr__(r.intent, "collection_name", "adopted")
    elif kind == "names":
        object.__setattr__(r.intent, "allocation_names", ())
    else:
        object.__setattr__(r.intent, "destination_fingerprint", "c" * 64)
    with pytest.raises(module.invalid_argument("x").__class__):
        store.begin(r.intent.preview_id, r.intent.fingerprint, list(r.intent.plan.required_accepted_losses))
    assert store.lookup(r.intent.stage_id).phase == "PREPARED"


@pytest.mark.parametrize("kind", ["role", "name", "bool_uid", "zero_pointer", "duplicate_role", "duplicate_uid", "duplicate_pointer", "huge_uid", "huge_pointer"])
def test_allocation_observations_require_exact_unused_intent_facts(model, kind):
    module, store, _ = model
    r = begin(model)
    role, name = r.intent.allocation_names[0]
    uid, pointer = 1, 100
    if kind.startswith("duplicate"):
        store.note_allocation(r.intent.stage_id, role, name, uid, pointer)
        if kind != "duplicate_role":
            role, name = r.intent.allocation_names[1]
            if kind == "duplicate_uid":
                pointer += 1
            else:
                uid += 1
    elif kind == "role":
        role = "mesh:99"
    elif kind == "name":
        name = "same-name replacement"
    elif kind == "bool_uid":
        uid = True
    elif kind == "huge_uid":
        uid = 2**4096
    elif kind == "huge_pointer":
        pointer = 2**4096
    else:
        pointer = 0
    previous = store.lookup(r.intent.stage_id)
    with pytest.raises(module.invalid_argument("x").__class__):
        store.note_allocation(r.intent.stage_id, role, name, uid, pointer)
    assert store.lookup(r.intent.stage_id) is previous


def test_prefix_must_be_recorded_after_final_allocation_observation(model):
    module, store, _ = model
    r = begin(model)
    store.note_prefix(r.intent.stage_id, "c" * 64)
    record_expected(model, r)
    with pytest.raises(module.invalid_argument("x").__class__):
        store.finish(r.intent.stage_id, published=True)
    store.note_prefix(r.intent.stage_id, "d" * 64)
    final = store.finish(r.intent.stage_id, published=True)
    assert final.phase == "PUBLISHED" and final.publication_observed
    report = store.inspect(r.intent.stage_id)
    assert report["expected_id_observations_complete"] is True
    assert report["native_ownership_verified"] is False  # Modeled integers are never native proof.
    json.dumps(report, allow_nan=False)
    with pytest.raises(module.invalid_argument("x").__class__):
        store.finish(r.intent.stage_id, published=True)


@pytest.mark.parametrize("before_return", [True, False])
def test_unknown_throw_after_constructor_keeps_preissued_lookup_and_partial_observations(model, before_return):
    module, store, _ = model
    r = begin(model)
    if not before_return:
        role, name = r.intent.allocation_names[0]
        store.note_allocation(r.intent.stage_id, role, name, 1, 100)
    final = store.fail(r.intent.stage_id, "CONSTRUCTOR_OUTCOME_UNKNOWN", outcome_unknown=True)
    assert final.phase == "UNKNOWN" and final.possible_mutation and final.outcome_unknown
    assert len(final.allocations) == (0 if before_return else 1)
    assert store.lookup(r.intent.stage_id) is final
    before = store.retained_bytes
    store.invalidate()
    stale = store.lookup(r.intent.stage_id)
    assert stale.allocations == final.allocations and stale.reason == final.reason
    assert stale.prior_phase == "UNKNOWN" and stale.phase == "STALE"
    assert store.retained_bytes == before
    assert store.inspect(r.intent.stage_id)["session_valid"] is False
    with pytest.raises(module.invalid_argument("x").__class__):
        store.note_prefix(r.intent.stage_id, "a" * 64)


def test_capacity_never_evicts_unknown_or_pending_stages(model, monkeypatch):
    module, store, _ = model
    r = begin(model)
    store.fail(r.intent.stage_id, "FAILED_ALLOCATION", outcome_unknown=True)
    monkeypatch.setattr(module, "MAX_RECORDS", 2)
    other = prepare(model, "Second")
    with pytest.raises(module.invalid_argument("x").__class__):
        prepare(model, "Third")
    assert store.lookup(r.intent.stage_id).phase == "UNKNOWN"
    assert store.lookup(other.intent.stage_id) is other


def test_complete_source_plus_canonical_plan_counts_against_byte_capacity(model, monkeypatch):
    module, store, _ = model
    first = prepare(model)
    monkeypatch.setattr(module, "MAX_RETAINED_BYTES", 2 * first.intent.accounted_bytes - 1)
    with pytest.raises(module.invalid_argument("x").__class__):
        prepare(model, "Second")
    assert store.retained_bytes == first.intent.accounted_bytes


def test_only_one_active_creation_and_terminal_failures_cannot_resume(model):
    module, store, _ = model
    a, b = prepare(model, "First"), prepare(model, "Second")
    store.begin(a.intent.preview_id, a.intent.fingerprint, list(a.intent.plan.required_accepted_losses))
    with pytest.raises(module.invalid_argument("x").__class__):
        store.begin(b.intent.preview_id, b.intent.fingerprint, list(b.intent.plan.required_accepted_losses))
    store.fail(a.intent.stage_id, "CANCELLED", outcome_unknown=False)
    assert store.begin(b.intent.preview_id, b.intent.fingerprint,
                       list(b.intent.plan.required_accepted_losses)).phase == "ALLOCATING"


def test_token_collision_refuses_without_overwriting_records(model, monkeypatch):
    module, store, _ = model
    monkeypatch.setattr(module.secrets, "token_hex", lambda n: "a" * (2 * n))
    first = prepare(model)
    with pytest.raises(module.invalid_argument("x").__class__):
        prepare(model)
    assert store.lookup(first.intent.stage_id) is first


def test_reentrant_planner_check_cannot_overfill_record_capacity(model):
    module, store, source = model
    entered = []

    def check():
        if not entered:
            entered.append(True)
            for index in range(module.MAX_RECORDS):
                store.prepare(source, f"Nested {index}", "a" * 64, overwrite_policy="REFUSE")

    with pytest.raises(module.invalid_argument("x").__class__):
        store.prepare(source, "Outer", "a" * 64, overwrite_policy="REFUSE", check=check)
    assert len(store._records) == module.MAX_RECORDS
    assert all(record.intent.collection_name != "Outer" for record in store._records.values())


@pytest.mark.parametrize("kind", ["generation", "records", "previews"])
def test_session_or_store_drift_during_planning_is_not_a_new_baseline(model, kind):
    module, store, source = model
    original = store.generation
    entered = []

    def check():
        if not entered:
            entered.append(True)
            if kind == "generation":
                store.invalidate()
            elif kind == "records":
                store._records = dict(store._records)
            else:
                store._previews = dict(store._previews)

    with pytest.raises(module.invalid_argument("x").__class__):
        store.prepare(source, "Outer", "a" * 64, overwrite_policy="REFUSE", check=check)
    assert not store._records and store.retained_bytes == 0
    if kind == "generation":
        assert store.generation != original
    assert prepare(model).phase == "PREPARED"


def test_largest_plan_identity_observations_have_a_finite_inspection_receipt(model, monkeypatch):
    module, store, source = model
    source_module = importlib.import_module(module.__package__ + ".glb_stage_source")
    manifest, binary = triangle()
    primitive = manifest["meshes"][0]["primitives"][0]
    manifest["materials"] = [{} for _ in range(16)]
    manifest["meshes"] = [{"primitives": [{**primitive, "material": i}]} for i in range(16)]
    manifest["nodes"] = [{"mesh": i % 16} for i in range(32)]
    manifest["scenes"][0]["nodes"] = list(range(32))
    Path(source.path).write_bytes(glb(manifest, binary))
    source = source_module.read_glb_source(source.path, source.approved_root)
    r = store.prepare(source, "é" * 20, "a" * 64, overwrite_policy="REFUSE")
    assert r.intent.accounted_bytes == source.accounted_bytes + len(r.intent.plan.canonical_bytes())
    store.begin(r.intent.preview_id, r.intent.fingerprint, list(r.intent.plan.required_accepted_losses))
    assert len(r.intent.allocation_names) == module.MAX_ALLOCATIONS == 81
    for index, (role, name) in enumerate(r.intent.allocation_names):
        store.note_allocation(r.intent.stage_id, role, name, module.MAX_NATIVE_IDENTITY - index,
                              module.MAX_NATIVE_IDENTITY - index - 100)
    report = store.inspect(r.intent.stage_id)
    assert len(json.dumps(report).encode()) < module.MAX_INSPECTION_BYTES
    monkeypatch.setattr(module, "MAX_INSPECTION_BYTES", 1)
    with pytest.raises(module.invalid_argument("x").__class__):
        store.inspect(r.intent.stage_id)


@pytest.mark.parametrize("normal_mode", ["none", "authored", "mixed", "separate"])
@pytest.mark.parametrize("uv", [False, True])
def test_normal_conversion_counts_and_exact_losses_are_sealed_into_stage_intent(addon_package, tmp_path, normal_mode, uv):
    from test_asset_glb_import_plan import conversion_asset

    module = importlib.import_module(addon_package + ".glb_stage_state")
    sources = importlib.import_module(addon_package + ".glb_stage_source")
    manifest, binary = conversion_asset(normal_mode, uv=uv)
    path = tmp_path / "source.glb"
    path.write_bytes(glb(manifest, binary))
    source = sources.read_glb_source(str(path), str(tmp_path))
    store = module.GLBStageStore()
    record = store.prepare(source, "Normals", "a" * 64, overwrite_policy="REFUSE")
    assert record.phase == "PREPARED" and record.allocations == ()
    summary = record.intent.plan.summary()
    assert summary["normal_conversion"]["authored_normal_corners"] == (0 if normal_mode == "none" else 3)
    assert summary["normal_conversion"]["geometric_auto_corners"] == (3 if normal_mode == "mixed" else 0)
    assert store.begin(record.intent.preview_id, record.intent.fingerprint,
                       list(record.intent.plan.required_accepted_losses)).phase == "ALLOCATING"


@pytest.mark.parametrize("fault", ["old_list", "auto_without_normal", "duplicate", "count", "bool_count"])
def test_rehashed_planner_forgery_never_creates_a_stage_record(addon_package, tmp_path, monkeypatch, fault):
    import hashlib

    from test_asset_glb_import_plan import conversion_asset

    module = importlib.import_module(addon_package + ".glb_stage_state")
    sources = importlib.import_module(addon_package + ".glb_stage_source")
    manifest, binary = conversion_asset("mixed", uv=True)
    path = tmp_path / "source.glb"
    path.write_bytes(glb(manifest, binary))
    source = sources.read_glb_source(str(path), str(tmp_path))
    plan = module.plan_glb(source.payload)
    losses = list(plan.required_accepted_losses)
    conversion = plan.conversion_requirements
    if fault == "old_list":
        losses = losses[:4]
    elif fault == "auto_without_normal":
        losses.remove("NORMAL_STORAGE_QUANTIZATION")
    elif fault == "duplicate":
        losses.append(losses[-1])
    else:
        conversion = replace(conversion, geometric_auto_corners=0 if fault == "count" else True)
    forged = replace(plan, conversion_requirements=conversion, required_accepted_losses=tuple(losses))
    forged = replace(forged, normalized_sha256=hashlib.sha256(forged.canonical_bytes()).hexdigest())
    monkeypatch.setattr(module, "plan_glb", lambda *_args: forged)
    store = module.GLBStageStore()
    with pytest.raises(module.invalid_argument("x").__class__):
        store.prepare(source, "Normals", "a" * 64, overwrite_policy="REFUSE")
    assert store._records == {} and store.retained_bytes == 0


@pytest.mark.parametrize("fault", ["normal_count", "auto_count", "losses"])
def test_conversion_forgery_after_preview_cannot_begin_allocation(addon_package, tmp_path, fault):
    from test_asset_glb_import_plan import conversion_asset

    module = importlib.import_module(addon_package + ".glb_stage_state")
    sources = importlib.import_module(addon_package + ".glb_stage_source")
    manifest, binary = conversion_asset("mixed", uv=True)
    path = tmp_path / "source.glb"
    path.write_bytes(glb(manifest, binary))
    source = sources.read_glb_source(str(path), str(tmp_path))
    store = module.GLBStageStore()
    record = store.prepare(source, "Normals", "a" * 64, overwrite_policy="REFUSE")
    if fault == "losses":
        object.__setattr__(record.intent.plan, "required_accepted_losses", record.intent.plan.required_accepted_losses[:4])
    else:
        field = "authored_normal_corners" if fault == "normal_count" else "geometric_auto_corners"
        object.__setattr__(record.intent.plan.conversion_requirements, field, 0)
    with pytest.raises(module.invalid_argument("x").__class__):
        store.begin(record.intent.preview_id, record.intent.fingerprint,
                    list(record.intent.plan.required_accepted_losses))
    assert store.lookup(record.intent.stage_id).phase == "PREPARED"
    assert store.lookup(record.intent.stage_id).allocations == ()


def constructed(model):
    _, store, _ = model
    record = begin(model)
    record_expected(model, record)
    store.note_prefix(record.intent.stage_id, "b" * 64)
    return store.finish(record.intent.stage_id, published=False)


def test_publication_intent_is_explicit_sealed_and_consumed_once(model):
    module, store, _ = model
    record = constructed(model)
    stage_id = record.intent.stage_id
    intent = store.prepare_publication(stage_id, "Scene", "c" * 64, overwrite_policy="REFUSE")
    assert intent.constructed_prefix == "b" * 64
    assert intent.stage_id == stage_id and intent.generation == store.generation
    assert store.lookup(stage_id).phase == "CONSTRUCTED"
    store.begin_publication(stage_id, intent.preview_id, intent.fingerprint, overwrite_policy="REFUSE")
    assert store.lookup(stage_id).phase == "PUBLISHING"
    store.finish_publication(stage_id, "d" * 64)
    assert store.inspect(stage_id)["phase"] == "PUBLISHED"
    assert store.inspect(stage_id)["publication_observed"] is True
    with pytest.raises(module.invalid_argument("x").__class__):
        store.begin_publication(stage_id, intent.preview_id, intent.fingerprint, overwrite_policy="REFUSE")
    assert len(store.lookup(stage_id).allocations) == len(record.intent.allocation_names)


@pytest.mark.parametrize("fault", ["preview", "fingerprint", "policy", "generation", "expiry", "prefix", "intent"])
def test_publication_forgery_never_enters_publishing(model, fault, monkeypatch):
    module, store, _ = model
    record = constructed(model)
    stage_id = record.intent.stage_id
    intent = store.prepare_publication(stage_id, "Scene", "c" * 64, overwrite_policy="REFUSE")
    preview, fingerprint, policy = intent.preview_id, intent.fingerprint, "REFUSE"
    if fault == "preview":
        preview = "glb_publish_" + "0" * 32
    elif fault == "fingerprint":
        fingerprint = "0" * 64
    elif fault == "policy":
        policy = "REPLACE"
    elif fault == "generation":
        store.invalidate()
    elif fault == "expiry":
        monkeypatch.setattr(module, "_clock", lambda: intent.expires_at)
    elif fault == "prefix":
        store._records[stage_id] = replace(store.lookup(stage_id), prefix_digest="e" * 64)
    else:
        object.__setattr__(intent, "destination_scene_name", "Other")
    with pytest.raises(module.invalid_argument("x").__class__):
        store.begin_publication(stage_id, preview, fingerprint, overwrite_policy=policy)
    assert store.lookup(stage_id).phase != "PUBLISHING"
    assert len(store.lookup(stage_id).allocations) == len(record.intent.allocation_names)


def test_publication_failure_and_trailing_checkpoint_failure_retain_unknown(model):
    _, store, _ = model
    record = constructed(model)
    stage_id = record.intent.stage_id
    intent = store.prepare_publication(stage_id, "Scene", "c" * 64, overwrite_policy="REFUSE")
    store.begin_publication(stage_id, intent.preview_id, intent.fingerprint, overwrite_policy="REFUSE")
    store.finish_publication(stage_id, "d" * 64)
    store.mark_unknown(stage_id, "RUNTIME_CHECKPOINT_AFTER_FAILED")
    result = store.inspect(stage_id)
    assert result["phase"] == "UNKNOWN" and result["prior_phase"] == "PUBLISHED"
    assert result["publication_observed"] and result["possible_mutation"] and result["outcome_unknown"]
    assert len(result["observed_allocations"]) == len(record.intent.allocation_names)
    store.invalidate()
    store.mark_unknown(stage_id, "LATER_CALLBACK")
    assert store.inspect(stage_id)["phase"] == "STALE"


def test_optional_checkpoint_witness_preserves_legacy_intent_and_destination(model, monkeypatch):
    module, store, source = model
    payloads, dumps = [], module.json.dumps

    def capture(value, *args, **kwargs):
        if type(value) is dict and "destination_fingerprint" in value and "plan_sha256" in value:
            payloads.append(dict(value))
        return dumps(value, *args, **kwargs)

    monkeypatch.setattr(module.json, "dumps", capture)
    record = store.prepare(source, "Asset", "a" * 64, overwrite_policy="REFUSE")
    intent = record.intent
    # Old positional construction remains valid, with the optional witness absent.
    legacy = module.StageIntent(intent.preview_id, intent.stage_id, intent.generation,
        intent.source, intent.plan, intent.collection_name, intent.destination_fingerprint,
        intent.allocation_names, intent.expires_at, intent.accounted_bytes, intent.fingerprint)
    assert legacy.checkpoint_fingerprint is None
    assert module._fingerprint(legacy) == intent.fingerprint
    assert payloads and all("checkpoint_fingerprint" not in value for value in payloads)
    assert intent.destination_fingerprint == "a" * 64
    assert intent.accounted_bytes == source.accounted_bytes + len(intent.plan.canonical_bytes())


def test_checkpoint_witness_is_sealed_separately_from_destination(model):
    module, store, source = model
    record = store.prepare(source, "Asset", "a" * 64, overwrite_policy="REFUSE",
                           checkpoint_fingerprint="b" * 64)
    intent = record.intent
    assert intent.checkpoint_fingerprint == "b" * 64
    assert intent.destination_fingerprint == "a" * 64
    assert intent.accounted_bytes == source.accounted_bytes + len(intent.plan.canonical_bytes()) + 64
    assert store.retained_bytes == intent.accounted_bytes
    changed = replace(intent, checkpoint_fingerprint="c" * 64)
    assert module._fingerprint(changed) != intent.fingerprint
    assert changed.destination_fingerprint == intent.destination_fingerprint
    object.__setattr__(intent, "checkpoint_fingerprint", "c" * 64)
    with pytest.raises(module.invalid_argument("x").__class__):
        store.begin(intent.preview_id, intent.fingerprint, list(intent.plan.required_accepted_losses))
    assert store.lookup(intent.stage_id).phase == "PREPARED" and store._active is None


@pytest.mark.parametrize("value", [True, False, 1, b"b" * 64, "", "B" * 64, "b" * 63, "z" * 64, [], {}])
def test_checkpoint_fingerprint_rejects_nonliteral_or_malformed_values_before_planning(model, value):
    module, store, source = model
    callbacks = []
    with pytest.raises(module.invalid_argument("x").__class__):
        store.prepare(source, "Asset", "a" * 64, overwrite_policy="REFUSE",
                      checkpoint_fingerprint=value, check=lambda: callbacks.append("planner"))
    assert callbacks == [] and not store._records and store.retained_bytes == 0


@pytest.mark.parametrize("string_subclass", [False, True])
def test_checkpoint_fingerprint_rejects_foreign_protocol_callbacks_without_invoking_them(model, string_subclass):
    module, store, source = model
    callbacks = []

    class Foreign(str if string_subclass else object):
        def __eq__(self, other):
            callbacks.append("eq")
            raise AssertionError("foreign equality")

        def __hash__(self):
            callbacks.append("hash")
            raise AssertionError("foreign hash")

        def __str__(self):
            callbacks.append("str")
            raise AssertionError("foreign string conversion")

    value = Foreign("b" * 64) if string_subclass else Foreign()
    with pytest.raises(module.invalid_argument("x").__class__):
        store.prepare(source, "Asset", "a" * 64, overwrite_policy="REFUSE", checkpoint_fingerprint=value)
    assert callbacks == [] and not store._records


def test_checkpoint_witness_respects_existing_retained_byte_limit(model, monkeypatch):
    module, _store, source = model
    record = prepare(model)
    maximum = record.intent.accounted_bytes + 63
    monkeypatch.setattr(module, "MAX_RETAINED_BYTES", maximum)
    other = module.GLBStageStore()
    with pytest.raises(module.invalid_argument("x").__class__):
        other.prepare(source, "Asset", "a" * 64, overwrite_policy="REFUSE", checkpoint_fingerprint="b" * 64)
    assert not other._records and other.retained_bytes == 0


def test_active_intent_cannot_drop_checkpoint_witness(model):
    module, store, source = model
    record = store.prepare(source, "Asset", "a" * 64, overwrite_policy="REFUSE", checkpoint_fingerprint="b" * 64)
    intent = record.intent
    store.begin(intent.preview_id, intent.fingerprint, list(intent.plan.required_accepted_losses))
    object.__setattr__(intent, "checkpoint_fingerprint", None)
    with pytest.raises(module.invalid_argument("x").__class__):
        store.note_allocation(intent.stage_id, "collection", "Asset", 1, 1000)
    assert store.lookup(intent.stage_id).allocations == ()
