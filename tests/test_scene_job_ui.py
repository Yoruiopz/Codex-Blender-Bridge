"""The real cached job renderer accepts mixed image and Scene receipts."""

import importlib


class Layout:
    def __init__(self):
        self.labels, self.operators = [], []

    def label(self, *, text, icon=None):
        self.labels.append((text, icon))

    def operator(self, name, *, icon=None):
        self.operators.append((name, icon))


def test_job_renderer_preserves_image_fields_and_displays_evicted_scene_receipt(addon_package):
    ui = importlib.import_module(f"{addon_package}.ui")
    image = {"kind": "image.paint_version", "new_image": "Paint result", "state": "SUCCEEDED",
             "workload": {"image_size": [64, 32], "candidate_pixel_tests": 4096,
                          "private_pixel_buffers_peak_estimate_bytes": 1048576},
             "progress": {"phase": "succeeded", "completed": 1, "total": 1}, "terminal": True,
             "error": None, "external_effects": {"file_published": True},
             "recovery_evidence": {"snapshot_retained": True}}
    scene = {"kind": "fixture.rigid_scene_evaluation", "label": "Owned Scene evaluation", "state": "RUNNING",
             "progress": {"phase": "frame_2_set", "completed": 3, "total": 12}, "terminal": False, "error": None}
    retained = {**scene, "state": "CANCELLED", "terminal": True, "terminal_history_evicted": True,
                "recovery_receipt_retained": True,
                "error": {"code": "TIMEOUT", "context": {"possible_mutation": True}}}
    layout = Layout()
    for record in (image, scene, retained):
        ui._draw_job(layout, record)
    labels = [text for text, _ in layout.labels]
    assert "SUCCEEDED: Paint result" in labels
    assert "64 x 32 pixels" in labels and "4096 brush candidates" in labels
    assert "Private pixel estimate: 1.0 MiB" in labels
    assert "File may persist after cancel/undo; inspect" in labels
    assert "Snapshot retained at completion; verify before saving" in labels
    assert "RUNNING: Owned Scene evaluation" in labels
    assert "CANCELLED: Owned Scene evaluation" in labels
    assert "Possible effects; inspect/recover" in labels
    assert layout.operators == [("blender_codex_bridge.cancel_job", "CANCEL")]
