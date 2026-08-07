from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture(scope="session")
def addon_package() -> str:
    """Load Blender-free add-on modules without executing the bpy entry point."""

    package_name = "_blender_codex_bridge_test"
    package = ModuleType(package_name)
    package.__path__ = [
        str(Path(__file__).resolve().parents[1] / "addon" / "blender_codex_bridge")
    ]
    package.__package__ = package_name
    sys.modules[package_name] = package
    try:
        yield package_name
    finally:
        for module_name in list(sys.modules):
            if module_name == package_name or module_name.startswith(f"{package_name}."):
                sys.modules.pop(module_name, None)
