from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


def drain(steps):
    progress = []
    while True:
        try:
            progress.append(next(steps))
        except StopIteration as stopped:
            return stopped.value, progress


def receipt():
    return {"kind": "current_pixels_lifecycle", "schema_version": 1,
            "method": "image.pack_current_pixels_job_start", "mode": "CURRENT_PIXELS_PACK",
            "profile": "FILE_F32_EXR_DATA_CURRENT_PIXELS_V1", "stage": "BACKUPS_DURABLE",
            "identity_mode": "SAME_SESSION_NATIVE_IDS", "external_write_attempted": True,
            "helper_record_write_attempted": False, "image_write_attempted": False,
            "state_known": True, "possible_mutation": True, "verification_required": True,
            "recovery_authorized": False, "project_saved": False, "source_file_read": False,
            "automatic_inverse_attempted": False, "durable_backups_verified": True}


@pytest.fixture
def files(addon_package, tmp_path):
    module = importlib.import_module(f"{addon_package}.current_pixels_files")
    contract = importlib.import_module(f"{addon_package}.current_pixels_contract")
    live = {"allowed": True, "root": str(tmp_path), "calls": 0}

    def check():
        live["calls"] += 1
        if not live["allowed"] or live["root"] != str(tmp_path):
            raise module.BridgeError("PERMISSION_DENIED", "Current local authority lost.")

    def plan(prefix="asset", journal=True):
        return module.freeze_backup_plan(str(tmp_path), prefix, str(tmp_path), journal, check)

    def make(prefix="asset", journal=True):
        return module.BackupFiles(plan(prefix, journal))

    def publish(item, kind, data):
        return drain(item.publish_steps(kind, (data,), len(data), hashlib.sha256(data).hexdigest(), check))[0]

    old, current = b"qualified frozen old packed bytes", b"qualified complete current EXR bytes"

    def manifest(prefix="asset", **updates):
        rows = [{"kind": kind, "name": name, "content_sha256": "a" * 64}
                for kind, name in (("Image", "Original"), ("Image", "Snapshot"), ("Material", "Material"))]
        value = {"kind": "current_pixels_manifest", "schema_version": 1, "profile": contract.PROFILE,
                 "record_uuid": "1" * 32, "runtime_nonce": "2" * 32,
                 "image_name": "Original", "snapshot_name": "Snapshot", "width": 2, "height": 2,
                 "affected_materials": ["Material"], "backup_prefix": prefix,
                 "current_pixels_sha256_float32_le": "b" * 64,
                 "previous_packed_sha256": hashlib.sha256(old).hexdigest(),
                 "previous_decoded_pixels_sha256": "c" * 64,
                 "native_graph_sha256": "d" * 64, "portable_graph_sha256": "e" * 64,
                 "original_identity": {"pointer": "1", "session_uid": "1"},
                 "snapshot_identity": {"pointer": "2", "session_uid": "2"},
                 "roles": {"source": "FILE", "file_format": "OPEN_EXR", "colorspace": "Non-Color",
                           "alpha_mode": "CHANNEL_PACKED", "is_float": True},
                 "native_identity_rows": [{**row, "pointer": str(index), "session_uid": str(index)}
                                          for index, row in enumerate(rows, 1)],
                 "portable_identity_rows": rows,
                 "backups": {kind: {"filename": prefix + module.SUFFIXES[kind], "bytes": len(data),
                                    "sha256": hashlib.sha256(data).hexdigest()}
                             for kind, data in (("oldpacked", old), ("current", current))}}
        value.update(updates)
        return contract.canonical_manifest(value)

    def complete(item=None):
        item = item or make()
        publish(item, "oldpacked", old)
        publish(item, "current", current)
        publish(item, "manifest", manifest(item.plan.prefix))
        return item

    return NS(module=module, contract=contract, root=tmp_path, live=live, check=check,
              make=make, plan=plan, publish=publish, complete=complete, manifest=manifest,
              old=old, current=current)


def test_three_create_only_backups_have_full_independent_receipts(files, monkeypatch):
    module, real_sync = files.module, os.fsync
    syncs = []

    def fsync(descriptor):
        value = os.fstat(descriptor)
        syncs.append((value.st_ino, value.st_size))
        return real_sync(descriptor)

    monkeypatch.setattr(module.os, "fsync", fsync)
    item = files.complete()
    records, progress = drain(item.verify_steps(files.check))
    assert len(records) == 3 and len(syncs) == 12  # file; create/link/retirement directory barriers.
    assert {step["phase"] for step in progress} == {"verifying_oldpacked", "verifying_current", "verifying_manifest"}
    for record in records:
        path = Path(record.path)
        assert path.stat().st_nlink == 1 and path.stat().st_ino == record.identity[1]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record.sha256
    assert item.stage is None and not list(files.root.glob("*.staging"))
    effects = item.evidence()
    assert effects["published_bytes_verified"] and len(effects["artifacts"]) == 3
    assert effects["staging_cleanup"] == "successful_stage_retired"
    assert not effects["publication_outcome_unknown"] and not effects["crash_durability_verified"]
    assert not effects["native_undo_removes_external_file"]


def test_descriptors_are_closed_at_every_cooperative_yield(files, monkeypatch):
    opened = set()
    real_open, real_close = os.open, os.close

    def tracked_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        opened.add(descriptor)
        return descriptor

    def tracked_close(descriptor):
        opened.discard(descriptor)
        return real_close(descriptor)

    monkeypatch.setattr(files.module.os, "open", tracked_open)
    monkeypatch.setattr(files.module.os, "close", tracked_close)
    item = files.make()
    steps = item.publish_steps("oldpacked", (files.old[:5], files.old[5:]), len(files.old),
                               hashlib.sha256(files.old).hexdigest(), files.check)
    for _ in steps:
        assert opened == set()
    assert opened == set()


@pytest.mark.parametrize("kind", ["oldpacked", "current", "manifest", "journal"])
@pytest.mark.parametrize("shape", ["file", "directory", "broken_link"])
def test_every_fixed_destination_must_be_absent_before_staging(files, kind, shape):
    path = files.root / ("asset" + files.module.SUFFIXES[kind])
    if shape == "file":
        path.write_bytes(b"protected")
    elif shape == "directory":
        path.mkdir()
    else:
        path.symlink_to(files.root / "missing")
    with pytest.raises(files.module.BridgeError, match="already exists"):
        files.make()
    assert not list(files.root.glob("*.staging"))
    if shape == "file":
        assert path.read_bytes() == b"protected"


@pytest.mark.parametrize("prefix", ["../escape", "x.y", "x/y", "", "x" * 49, "é", "x\n"])
def test_prefix_is_fixed_bounded_ascii(files, prefix):
    with pytest.raises(files.module.BridgeError):
        files.plan(prefix)
    assert list(files.root.iterdir()) == []


def test_denied_authority_precedes_every_initial_path_probe(files, monkeypatch):
    files.live["allowed"] = False
    monkeypatch.setattr(files.module, "approved_output", lambda *_: pytest.fail("unauthorized probe"))
    with pytest.raises(files.module.BridgeError, match="authority"):
        files.plan()
    assert list(files.root.iterdir()) == []


def test_existing_output_policy_sees_only_current_exr(files, monkeypatch):
    real_output, seen = files.module.approved_output, []

    def output(raw, root, extension):
        seen.append((raw, extension))
        return real_output(raw, root, extension)

    monkeypatch.setattr(files.module, "approved_output", output)
    files.complete()
    assert seen and all(raw.endswith(".current.exr") and extension == ".exr" for raw, extension in seen)


def test_approved_root_change_stops_before_any_new_effect(files):
    item = files.make()
    files.live["root"] = str(files.root.parent)
    with pytest.raises(files.module.BridgeError, match="authority"):
        files.publish(item, "oldpacked", files.old)
    assert not list(files.root.iterdir()) and not item.attempted


def test_parent_replacement_is_not_adopted(files):
    child = files.root / "child"
    child.mkdir()
    plan = files.module.freeze_backup_plan(str(child), "asset", str(files.root), False, files.check)
    child.rename(files.root / "retained")
    child.mkdir()
    item = files.module.BackupFiles(plan)
    with pytest.raises(files.module.BridgeError, match="could not be verified"):
        files.publish(item, "oldpacked", files.old)
    assert list(child.iterdir()) == [] and not item.attempted


def test_manifest_is_last_and_cannot_misdescribe_published_bytes(files):
    item = files.make()
    with pytest.raises(files.module.BridgeError):
        files.publish(item, "manifest", files.manifest())
    assert not item.attempted
    files.publish(item, "oldpacked", files.old)
    files.publish(item, "current", files.current + b"changed")
    with pytest.raises(files.module.BridgeError, match="could not be verified"):
        files.publish(item, "manifest", files.manifest())
    assert not item.plan.path("manifest").exists()
    assert item.stage and item.stage.exists() and item.failed
    assert item.plan.path("current").read_bytes() == files.current + b"changed"


@pytest.mark.parametrize("failure", ["short_write", "file_fsync", "directory_fsync", "wrong_hash", "too_large_block"])
def test_incomplete_staging_is_retained_and_never_retried(files, monkeypatch, failure):
    item, module = files.make(), files.module
    real_write, real_fsync = os.write, os.fsync
    if failure == "short_write":
        monkeypatch.setattr(module.os, "write", lambda descriptor, data: real_write(descriptor, data[:-1]))
    elif failure in {"file_fsync", "directory_fsync"}:
        def fsync(descriptor):
            import stat
            directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
            if directory == (failure == "directory_fsync"):
                raise OSError("unsupported durability barrier")
            return real_fsync(descriptor)
        monkeypatch.setattr(module.os, "fsync", fsync)
    data = b"x" * (module.BLOCK_BYTES + 1) if failure == "too_large_block" else files.old
    expected = "0" * 64 if failure == "wrong_hash" else hashlib.sha256(data).hexdigest()
    with pytest.raises((module.BridgeError, OSError)):
        drain(item.publish_steps("oldpacked", (data,), len(data), expected, files.check))
    assert item.stage and item.stage.exists() and item.failed
    assert not item.plan.path("oldpacked").exists()
    retained = item.stage.read_bytes()
    with pytest.raises(module.BridgeError):
        files.publish(item, "oldpacked", files.old)
    item.close()
    assert item.stage.read_bytes() == retained


def test_atomic_competitor_never_gets_clobbered_or_adopted(files, monkeypatch):
    item, real_link = files.make(), os.link

    def compete(source, destination, **kwargs):
        Path(destination).write_bytes(b"protected competitor")
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(files.module.os, "link", compete)
    with pytest.raises(FileExistsError):
        files.publish(item, "oldpacked", files.old)
    assert item.plan.path("oldpacked").read_bytes() == b"protected competitor"
    assert item.stage.read_bytes() == files.old
    assert item.evidence()["publication_outcome_unknown"]
    assert item.evidence()["artifacts"][0]["file_sha256"] is None


def test_failed_initial_stage_stat_retains_path_and_closes_descriptor(files, monkeypatch):
    item, real_stat, seen = files.make(), os.fstat, []

    def fstat(descriptor):
        seen.append(descriptor)
        raise OSError("initial stage identity unavailable")

    # Fault only this module's I/O; pytest/capture may stat its own descriptors.
    local_os = NS(**vars(files.module.os))
    local_os.fstat = fstat
    monkeypatch.setattr(files.module, "os", local_os)
    with pytest.raises(OSError):
        files.publish(item, "oldpacked", files.old)
    assert len(seen) == 1 and item.failed and item.stage.exists()
    assert item.evidence()["staging_cleanup"] == "retained_unverified"
    assert item.evidence()["retained_staging_path"] == str(item.stage)
    with pytest.raises(OSError):
        real_stat(seen[0])
    item.close()
    assert item.stage.exists()


@pytest.mark.parametrize("boundary", ["after_write", "after_link", "before_stage_retirement"])
def test_revocation_retains_effects_and_never_automatically_unlinks(files, monkeypatch, boundary):
    item, module = files.make(), files.module
    real_write, real_link, real_read = os.write, os.link, item._read
    if boundary == "after_write":
        def write(descriptor, data):
            count = real_write(descriptor, data)
            files.live["allowed"] = False
            return count
        monkeypatch.setattr(module.os, "write", write)
    elif boundary == "after_link":
        def link(*args, **kwargs):
            real_link(*args, **kwargs)
            files.live["allowed"] = False
        monkeypatch.setattr(module.os, "link", link)
    else:
        def read(*args, **kwargs):
            value = yield from real_read(*args, **kwargs)
            if args[0] == item.plan.path("oldpacked"):
                files.live["allowed"] = False
            return value
        monkeypatch.setattr(item, "_read", read)
    with pytest.raises(module.BridgeError, match="authority"):
        files.publish(item, "oldpacked", files.old)
    assert item.stage and item.stage.read_bytes() == files.old
    assert item.plan.path("oldpacked").exists() is (boundary != "after_write")
    retained = sorted(path.name for path in files.root.iterdir())
    item.close()
    assert sorted(path.name for path in files.root.iterdir()) == retained


def test_readback_corruption_blocks_stage_retirement(files, monkeypatch):
    item, real_link = files.make(), os.link

    def corrupt(source, destination, **kwargs):
        real_link(source, destination, **kwargs)
        with open(destination, "r+b") as stream:
            stream.write(b"!")

    monkeypatch.setattr(files.module.os, "link", corrupt)
    with pytest.raises(files.module.BridgeError):
        files.publish(item, "oldpacked", files.old)
    assert item.stage and item.stage.exists() and item.plan.path("oldpacked").exists()
    assert item.failed and item.evidence()["artifacts_incomplete"]


@pytest.mark.parametrize("boundary", ["unlink", "post_retirement_parent_fsync"])
def test_stage_retirement_failure_retains_uncertain_publication_without_retry(files, monkeypatch, boundary):
    item = files.make()
    if boundary == "unlink":
        def unlink(_path):
            raise OSError("owned staging retirement failed")
        monkeypatch.setattr(files.module.os, "unlink", unlink)
    else:
        real_sync, barriers = item._sync_parent, []

        def sync(check):
            barriers.append(True)
            if len(barriers) == 3:
                raise OSError("post-retirement durability unavailable")
            return real_sync(check)
        monkeypatch.setattr(item, "_sync_parent", sync)
    with pytest.raises(OSError):
        files.publish(item, "oldpacked", files.old)
    assert item.plan.path("oldpacked").read_bytes() == files.old and item.failed
    assert (item.stage is not None) is (boundary == "unlink")
    facts = item.evidence()
    assert facts["publication_outcome_unknown"] and facts["artifacts"][0]["file_sha256"] is None
    retained = sorted(path.name for path in files.root.iterdir())
    item.close()
    assert sorted(path.name for path in files.root.iterdir()) == retained


def test_complete_verification_reopens_all_files_and_detects_later_corruption(files):
    item = files.complete()
    path = item.plan.path("current")
    with path.open("r+b") as stream:
        stream.write(b"!")
    with pytest.raises(files.module.BridgeError):
        drain(item.verify_steps(files.check))
    assert len(list(files.root.iterdir())) == 3
    assert item.failed and not item.evidence()["durable_backups_verified"]
    assert item.evidence()["artifacts"][1]["file_sha256"] is None


def test_read_only_recovery_cannot_publish_even_with_mutated_cached_records(files):
    files.complete()
    plan = files.module.freeze_recovery_plan(str(files.root / "asset.manifest.json"), str(files.root), files.check)
    item = files.module.BackupFiles(plan)
    item.records.clear()
    with pytest.raises(files.module.BridgeError):
        files.publish(item, "oldpacked", files.old)
    with pytest.raises(files.module.BridgeError):
        drain(item.read_steps("oldpacked", len(files.old), hashlib.sha256(files.old).hexdigest(), files.check))
    (manifest, record), _ = drain(item.read_manifest_steps(files.check))
    assert manifest["backup_prefix"] == "asset" and record.path.endswith(".manifest.json")
    (data, record), _ = drain(item.read_steps("oldpacked", len(files.old), hashlib.sha256(files.old).hexdigest(), files.check, capture=True))
    assert data == files.old and record.sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("raw", [b'{"kind":"current_pixels_manifest","kind":"other"}', b'{"schema_version":2}', b"x" * (64 * 1024 + 1)])
def test_manifest_bootstrap_refuses_before_any_named_payload_read(files, monkeypatch, raw):
    path = files.root / "asset.manifest.json"
    path.write_bytes(raw)
    plan = files.module.freeze_recovery_plan(str(path), str(files.root), files.check)
    item = files.module.BackupFiles(plan)
    real_open, seen = os.open, []

    def opened(path, *args, **kwargs):
        seen.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(files.module.os, "open", opened)
    with pytest.raises(files.module.BridgeError):
        drain(item.read_manifest_steps(files.check))
    assert all(value.endswith("asset.manifest.json") for value in seen)


def test_capture_uses_declared_payload_cap_beyond_old_twenty_mib_default(files):
    payload = b"z" * (20 * 1024 * 1024 + 1)
    path = files.root / "asset.oldpacked.bin"
    path.write_bytes(payload)
    metadata = json.loads(files.manifest())
    metadata["backups"]["oldpacked"].update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    metadata["previous_packed_sha256"] = hashlib.sha256(payload).hexdigest()
    (files.root / "asset.manifest.json").write_bytes(files.contract.canonical_manifest(metadata))
    plan = files.module.freeze_recovery_plan(str(files.root / "asset.manifest.json"), str(files.root), files.check)
    item = files.module.BackupFiles(plan)
    drain(item.read_manifest_steps(files.check))
    (data, record), progress = drain(item.read_steps("oldpacked", len(payload), hashlib.sha256(payload).hexdigest(), files.check, capture=True))
    assert data == payload and record.identity[2] == len(payload)
    payload_progress = [row for row in progress if row["phase"] == "verifying_oldpacked"]
    assert len(payload_progress) == 21 and all(0 < row["completed"] <= len(payload) for row in payload_progress)


def test_journal_prefix_is_bounded_exact_and_cached_evidence_has_four_artifacts(files, monkeypatch):
    item = files.complete()
    first, _ = drain(item.append_event_steps(receipt(), files.check))
    event = {**receipt(), "stage": "HELPER_RECORD_ATTEMPT", "helper_record_write_attempted": True}
    second, _ = drain(item.append_event_steps(event, files.check))
    data = item.plan.path("journal").read_bytes()
    assert first.identity[:2] == second.identity[:2] and item.journal_events == 2
    assert [json.loads(line) for line in data.splitlines()] == [receipt(), event]
    assert hashlib.sha256(data).hexdigest() == second.sha256
    assert len(item.evidence()["artifacts"]) == 4
    monkeypatch.setattr(Path, "lstat", lambda *_: pytest.fail("cached evidence must not probe"))
    facts = item.evidence()
    facts["artifacts"][0]["file_sha256"] = "changed caller copy"
    assert item.evidence()["artifacts"][0]["file_sha256"] != "changed caller copy"
    item.close()


@pytest.mark.parametrize("problem", ["malformed_receipt", "corrupt_prefix", "revoked"])
def test_journal_failures_never_overwrite_or_append_after_lost_authority(files, problem):
    item = files.complete()
    drain(item.append_event_steps(receipt(), files.check))
    journal = item.plan.path("journal")
    event = receipt()
    if problem == "malformed_receipt":
        event["recovery_authorized"] = True
    elif problem == "corrupt_prefix":
        journal.write_bytes(b"foreign")
    else:
        files.live["allowed"] = False
    before = journal.read_bytes()
    with pytest.raises(files.module.BridgeError):
        drain(item.append_event_steps(event, files.check))
    assert journal.read_bytes() == before
    assert all(item.plan.path(kind).exists() for kind in ("oldpacked", "current", "manifest"))
    if problem == "corrupt_prefix":
        assert item.failed and item.evidence()["publication_outcome_unknown"]
        assert item.evidence()["artifacts"][-1]["file_sha256"] is None
        with pytest.raises(files.module.BridgeError):
            drain(item.append_event_steps(receipt(), files.check))


def test_journal_refuses_sixty_fifth_real_event_without_changing_file(files):
    item = files.complete()
    for _ in range(64):
        drain(item.append_event_steps(receipt(), files.check))
    journal = item.plan.path("journal")
    before = journal.read_bytes()
    assert len(before.splitlines()) == 64 and len(before) < files.module.MAX_JOURNAL_BYTES
    with pytest.raises(files.module.BridgeError):
        drain(item.append_event_steps(receipt(), files.check))
    assert journal.read_bytes() == before and item.journal_events == 64


def test_journal_byte_budget_refuses_full_receipt_before_event_limit(files):
    item = files.complete()
    event = {**receipt(), "image_name": "a" * 63, "snapshot_name": "b" * 63,
             "record_uuid": "a" * 32, "runtime_nonce": "b" * 32,
             "same_session_original_pointer": "a" * 16, "same_session_original_uid": "1" * 20,
             "owned_write_attempts": 1, "packed_bytes": 269484032,
             "expected_target_fingerprint": "a" * 64, "manifest_sha256": "b" * 64,
             "expected_prefix_sha256": "c" * 64, "observed_prefix_sha256": "c" * 64,
             "observed_prefix": "BACKUPS_DURABLE", "current_pixels_sha256_float32_le": "d" * 64,
             "previous_packed_sha256": "e" * 64, "current_packed_sha256": "f" * 64,
             "consumer_graph_sha256": "1" * 64, "previous_decoded_pixels_sha256": "2" * 64}
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    expected_count = files.module.MAX_JOURNAL_BYTES // len(encoded)
    assert expected_count < 64
    for _ in range(expected_count):
        drain(item.append_event_steps(event, files.check))
    before = item.plan.path("journal").read_bytes()
    with pytest.raises(files.module.BridgeError):
        drain(item.append_event_steps(event, files.check))
    assert item.plan.path("journal").read_bytes() == before and item.journal_events == expected_count


def test_returned_manifest_mutation_cannot_change_retained_recovery_byte_contract(files):
    files.complete()
    plan = files.module.freeze_recovery_plan(str(files.root / "asset.manifest.json"), str(files.root), files.check)
    item = files.module.BackupFiles(plan)
    (manifest, _record), _ = drain(item.read_manifest_steps(files.check))
    manifest["backups"]["oldpacked"].update(bytes=3, sha256=hashlib.sha256(b"bad").hexdigest())
    with pytest.raises(files.module.BridgeError):
        drain(item.read_steps("oldpacked", 3, hashlib.sha256(b"bad").hexdigest(), files.check, capture=True))
    (data, _record), _ = drain(item.read_steps("oldpacked", len(files.old), hashlib.sha256(files.old).hexdigest(), files.check, capture=True))
    assert data == files.old


def test_changed_recovery_manifest_is_never_adopted_as_a_new_baseline(files):
    files.complete()
    plan = files.module.freeze_recovery_plan(str(files.root / "asset.manifest.json"), str(files.root), files.check)
    item = files.module.BackupFiles(plan)
    drain(item.read_manifest_steps(files.check))
    metadata = json.loads(files.manifest())
    metadata["runtime_nonce"] = "f" * 32
    item.plan.path("manifest").write_bytes(files.contract.canonical_manifest(metadata))
    with pytest.raises(files.module.BridgeError):
        drain(item.read_manifest_steps(files.check))
    with pytest.raises(files.module.BridgeError):
        drain(item.read_steps("oldpacked", len(files.old), hashlib.sha256(files.old).hexdigest(), files.check))


def test_partial_journal_append_retains_unknown_file_and_blocks_further_writes(files, monkeypatch):
    item = files.complete()
    drain(item.append_event_steps(receipt(), files.check))
    old = item.plan.path("journal").read_bytes()
    real_write = os.write
    monkeypatch.setattr(files.module.os, "write", lambda descriptor, data: real_write(descriptor, data[:5]))
    with pytest.raises(files.module.BridgeError):
        drain(item.append_event_steps(receipt(), files.check))
    assert item.failed and item.plan.path("journal").read_bytes().startswith(old)
    assert item.evidence()["artifacts"][-1]["file_sha256"] is None
    assert item.evidence()["publication_outcome_unknown"]
    with pytest.raises(files.module.BridgeError):
        drain(item.append_event_steps(receipt(), files.check))
