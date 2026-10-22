"""Opt-in4K public snapshot/recovery jobs; one isolated process at a time."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_image_recovery_jobs_smoke import run

run(large=True)
