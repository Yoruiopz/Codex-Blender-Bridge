"""Blender Codex Bridge add-on registration entry point."""

from __future__ import annotations

import logging
from contextlib import suppress

from .constants import ADDON_VERSION

bl_info = {
    "name": "Blender Codex Bridge",
    "author": "Blender Codex Bridge contributors",
    "version": ADDON_VERSION,
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Codex Bridge",
    "description": "Local, permissioned structured bridge between Codex and Blender",
    "category": "Development",
    "doc_url": "https://github.com/Yoruiopz/Codex-Blender-Bridge",
}

LOGGER = logging.getLogger(__name__)

try:
    import bpy  # type: ignore
except ImportError:  # pragma: no cover - package remains importable in normal Python
    bpy = None  # type: ignore


def register() -> None:
    """Register preferences/UI, then start the main-thread executor."""

    if bpy is None:
        raise RuntimeError("Blender Codex Bridge can only be registered inside Blender.")
    from . import preferences, ui
    from .runtime import get_runtime

    registered: list[type] = []
    try:
        for cls in (*preferences.CLASSES, *ui.CLASSES):
            bpy.utils.register_class(cls)
            registered.append(cls)
        runtime = get_runtime()
        runtime.register()
        addon_preferences = preferences.get_preferences()
        if addon_preferences and addon_preferences.auto_start:
            try:
                runtime.start_server(
                    addon_preferences.host,
                    addon_preferences.port,
                    request_timeout=addon_preferences.request_timeout,
                )
            except Exception:
                # Auto-start errors should not make the add-on impossible to enable.
                LOGGER.exception("Blender Codex Bridge auto-start failed")
    except Exception:
        for cls in reversed(registered):
            with suppress(RuntimeError):
                bpy.utils.unregister_class(cls)
        raise


def unregister() -> None:
    """Stop sockets/timers before removing all registered Blender classes."""

    if bpy is None:
        return
    from . import preferences, ui
    from .runtime import get_runtime

    try:
        get_runtime().unregister()
    finally:
        for cls in reversed((*preferences.CLASSES, *ui.CLASSES)):
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                LOGGER.warning("Blender class %s was not registered", cls.__name__)


__all__ = ["bl_info", "register", "unregister"]
