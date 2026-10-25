from __future__ import annotations

import importlib
import subprocess
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def process_module(addon_package):
    return importlib.import_module(f"{addon_package}.geometry_preview_process")


def dto(module):
    return module.canonical(module.validate_dto({"bad": 1}))


def triangle(addon_package):
    module = importlib.import_module(f"{addon_package}.geometry_preview_dto")
    return module.canonical(
        module.make_dto(
            "Target", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1), (1, 2), (2, 0)], [(0, 1, 2)]
        )
    )


def test_fixed_launcher_uses_owned_paths_thin_environment_and_no_shell(
    process_module, addon_package, tmp_path, monkeypatch
):
    binary = tmp_path / "Blender With Spaces"
    binary.write_bytes(b"qualified binary model")
    process = process_module.PreviewProcess(str(binary), triangle(addon_package), "build")
    monkeypatch.setenv("GITHUB_TOKEN", "never-inherit")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    calls = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        assert command[0] == str(binary) and command[-2] == "--token"
        assert command.index("--python-expr") < command.index("--python")
        assert (
            command[command.index("--python-expr") + 1]
            == "import sys; sys.dont_write_bytecode = True"
        )
        assert kwargs["shell"] is False and kwargs["stdout"] is subprocess.DEVNULL
        assert "GITHUB_TOKEN" not in kwargs["env"] and "PYTHONPATH" not in kwargs["env"]
        assert kwargs["env"]["BLENDER_USER_SCRIPTS"] != "/untrusted"
        return NS(pid=23, returncode=0, poll=lambda: 0)

    monkeypatch.setattr(process_module.subprocess, "Popen", popen)
    list(process.fingerprint_steps(lambda: None))
    process.launch(lambda: None)
    assert calls and process.folder.stat().st_mode & 0o777 == 0o700
    assert process.close()["staging_cleanup"] == "complete"
    assert process.close()["staging_cleanup"] == "complete"


def test_cancel_escalates_and_reaps_owned_child(process_module, addon_package, tmp_path):
    binary = tmp_path / "blender"
    binary.write_bytes(b"binary")
    process = process_module.PreviewProcess(str(binary), triangle(addon_package), "build")
    calls = []
    state = NS(alive=True)

    def wait(timeout):
        calls.append(("wait", timeout))
        if len(calls) == 2:
            raise subprocess.TimeoutExpired("owned", timeout)
        state.alive = False
        process.process.returncode = -9

    object.__setattr__(
        process,
        "process",
        NS(
            pid=42,
            returncode=None,
            poll=lambda: None if state.alive else -9,
            terminate=lambda: calls.append("terminate"),
            kill=lambda: calls.append("kill"),
            wait=wait,
        ),
    )
    evidence = process.close()
    assert calls == ["terminate", ("wait", 0.1), "kill", ("wait", 0.2)]
    assert evidence["worker_reaped"] and evidence["staging_cleanup"] == "complete"


def test_bounded_read_refuses_links_and_oversize(process_module, tmp_path):
    path = tmp_path / "receipt"
    path.write_bytes(b"1234")
    with pytest.raises(type(process_module.refused("MODEL"))):
        process_module.bounded_read(path, 3)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(type(process_module.refused("MODEL"))):
        process_module.bounded_read(link, 4)


def success_files(process_module, addon_package, tmp_path):
    import hashlib
    import json

    from test_geometry_preview import png

    module = importlib.import_module(f"{addon_package}.geometry_preview_dto")
    binary = tmp_path / "blender"
    binary.write_bytes(b"binary model")
    process = process_module.PreviewProcess(
        str(binary), triangle(addon_package), "build", "4.5.14 LTS"
    )
    folder = tmp_path / "bundle"
    folder.mkdir(mode=0o700)
    object.__setattr__(process, "folder", folder)
    stat = folder.stat()
    object.__setattr__(process, "directory_id", (stat.st_dev, stat.st_ino))
    object.__setattr__(process, "cleanup_status", "pending")
    object.__setattr__(process, "process", NS(pid=42, returncode=0, poll=lambda: 0))
    raw = png()
    value = json.loads(process.raw)
    fit = module.camera_fit(value)
    row = {
        "schema": "geometry_preview_worker_v1",
        "status": "succeeded",
        "token": process.token,
        "dto_sha256": process.input_sha,
        "input_sha256": process.input_sha,
        "blender_version": "4.5.14 LTS",
        "build_hash": "build",
        "process_id": 42,
        "geometry_reconstructed": True,
        "raw_channels_reconstructed": True,
        "raw_channel_scope": [
            "location",
            "rotation_mode",
            "rotation_euler",
            "scale",
            *module.DEFAULT_DELTAS,
        ],
        "inactive_rotation_channels_copied": False,
        "edge_identity_scope": "Complete undirected edge set, not native edge allocation/order",
        "world_bounds": module.world_bounds(value),
        "camera_fit": fit,
        "projected_bounds": module.projected_bounds(value, fit),
        "png": module.validate_png(raw),
        "render_engine": "CYCLES",
        "device": "CPU",
        "samples": 8,
        "threads": 1,
        "source_process_contacted": False,
        "source_restore_writes": 0,
        "user_properties_or_ID_references_copied": False,
        "original_material_appearance_copied": False,
        "project_saved": False,
        "timings": {
            "worker_elapsed_seconds": 0.2,
            "render_and_validation_seconds": 0.1,
            "clock": "time.monotonic",
            "scope": "worker_process",
        },
        "peak_memory": {
            "available": True,
            "metric": "ru_maxrss",
            "scope": "RUSAGE_SELF",
            "value": 1234,
            "unit": "KiB",
            "platform": "linux",
        },
    }
    (folder / "preview.png").write_bytes(raw)
    (folder / "preview.png").chmod(0o600)

    def write():
        (folder / "worker.json").write_text(json.dumps(row))
        (folder / "worker.json").chmod(0o600)

    write()
    assert hashlib.sha256(raw).hexdigest() == row["png"]["sha256"]
    return process, row, write


def test_parent_independently_validates_complete_receipt_and_png(
    process_module, addon_package, tmp_path
):
    process, row, _write = success_files(process_module, addon_package, tmp_path)
    raw, evidence = process.result(lambda: None)
    assert evidence["worker"]["peak_memory"]["value"] == 1234
    assert evidence["parent_validated_png"]["sha256"] == row["png"]["sha256"]
    assert raw.startswith(b"\x89PNG") and evidence["OS_launch_memory_measured"] is False
    assert process.close()["staging_cleanup"] == "complete"


@pytest.mark.parametrize(
    "fault",
    [
        "samples_float",
        "threads_bool",
        "png_shape",
        "png_bool",
        "camera_bool",
        "projection",
        "version",
        "timing",
        "memory",
        "source_flag",
        "unknown",
    ],
)
def test_parent_refuses_malformed_worker_semantics_before_publication(
    process_module, addon_package, tmp_path, fault
):
    process, row, write = success_files(process_module, addon_package, tmp_path)
    if fault == "samples_float":
        row["samples"] = 8.0
    elif fault == "threads_bool":
        row["threads"] = True
    elif fault == "png_shape":
        row["png"] = []
    elif fault == "png_bool":
        row["png"]["visual_review_performed"] = 0
    elif fault == "camera_bool":
        row["camera_fit"]["right"][2] = False
    elif fault == "projection":
        row["projected_bounds"]["min"][0] += 0.1
    elif fault == "version":
        row["blender_version"] = "different"
    elif fault == "timing":
        row["timings"]["worker_elapsed_seconds"] = float("nan")
    elif fault == "memory":
        row["peak_memory"]["value"] = True
    elif fault == "source_flag":
        row["source_process_contacted"] = True
    else:
        row["unreviewed"] = True
    write()
    with pytest.raises(type(process_module.refused("MODEL"))):
        process.result(lambda: None)
    assert process.receipt is None
    process.close()


def test_authenticated_failed_worker_metrics_survive_reap_cleanup(
    process_module, addon_package, tmp_path
):
    import json

    process, old, _write = success_files(process_module, addon_package, tmp_path)
    row = {
        key: old[key]
        for key in (
            "schema",
            "token",
            "dto_sha256",
            "blender_version",
            "build_hash",
            "process_id",
            "timings",
            "peak_memory",
        )
    }
    row.update(
        status="failed", error={"code": "GEOMETRY_PREVIEW_WORKER_FAILED", "type": "RuntimeError"}
    )
    (process.folder / "worker.json").write_text(json.dumps(row))
    process.process.returncode = 1
    with pytest.raises(type(process_module.refused("MODEL"))) as caught:
        process.result(lambda: None)
    assert caught.value.context["worker_evidence"]["peak_memory"]["value"] == 1234
    assert process.close()["worker_receipt"] == row


def test_private_output_hardlinks_are_never_read(process_module, tmp_path):
    import os

    path = tmp_path / "output"
    path.write_bytes(b"owned")
    path.chmod(0o600)
    os.link(path, tmp_path / "extra_link")
    with pytest.raises(type(process_module.refused("MODEL"))):
        process_module.bounded_read(path, 100, private=True)


def test_owned_process_facts_are_sealed_after_construction(process_module, addon_package, tmp_path):
    binary = tmp_path / "blender"
    binary.write_bytes(b"binary")
    process = process_module.PreviewProcess(str(binary), triangle(addon_package), "build")
    for name, value in (
        ("raw", b"other"),
        ("folder", tmp_path),
        ("token", "x" * 32),
        ("process", object()),
        ("cleanup_status", "complete"),
    ):
        with pytest.raises(type(process_module.refused("MODEL"))):
            setattr(process, name, value)
    with pytest.raises(TypeError):
        process.program["geometry_preview_worker.py"] = "forged"


def test_edge_identity_scope_is_a_fixed_typed_contract(process_module, addon_package, tmp_path):
    process, row, write = success_files(process_module, addon_package, tmp_path)
    row["edge_identity_scope"] = {"all_edges": True}
    write()
    with pytest.raises(type(process_module.refused("MODEL"))):
        process.result(lambda: None)
    process.close()


def test_failed_worker_cannot_claim_render_timing_without_validated_input(
    process_module, addon_package, tmp_path
):
    process, row, _write = success_files(process_module, addon_package, tmp_path)
    failed = {
        key: row[key]
        for key in (
            "schema",
            "token",
            "blender_version",
            "build_hash",
            "process_id",
            "timings",
            "peak_memory",
        )
    }
    failed.update(
        status="failed",
        dto_sha256=None,
        error={"code": "GEOMETRY_PREVIEW_WORKER_FAILED", "type": "PreviewRefused"},
    )
    with pytest.raises(type(process_module.refused("MODEL"))):
        process._failed_receipt(failed)
    failed["timings"]["render_and_validation_seconds"] = None
    process._failed_receipt(failed)
    process.close()
