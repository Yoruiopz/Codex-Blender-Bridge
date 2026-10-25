# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed opt-in native saves; legacy project.save remains quarantined."""
from __future__ import annotations

from ..errors import BridgeError
from ..native_save_source import PREVIEW, REQUIRED, START, SaveOrigin, initial_dependencies, refused


def _origin(context):
    binding = context.checkpoint_admission
    if binding is None or type(binding.callback) is not SaveOrigin:
        raise refused("RETAINED_SAVE_ADMISSION_REQUIRED")
    return binding.callback


def preview(context, params):
    return context.jobs.preview_save(context, _origin(context))


def start(context, params):
    return context.jobs.start_native_save(context, _origin(context))


def preview_admission(context, params):
    return _admission(context, params, PREVIEW, preview)


def start_admission(context, params):
    return _admission(context, params, START, start)


def _admission(context, params, method, handler):
    try:
        return SaveOrigin(context, params, method, handler)
    except BridgeError as error:
        error.context.update(execution_started=False, native_save_invoked=False, bridge_file_writes=False)
        raise


def scope(context, params):
    return {"scope_complete": False, "reason": "NATIVE_SAVE_PROTECTED_SCOPE_UNSUPPORTED"}


def register_tools(registry):
    for name, handler, admission, description in (
        (PREVIEW, preview, preview_admission, "Preview a bounded declared native-save project/path under explicit native-effects session permission."),
        (START, start, start_admission, "Accept an exact previewed native Copy/Save/SaveAs job; poll files/reopen effects, never infer rollback."),
    ):
        registry.register(name, handler, permissions=REQUIRED, modifies=True, automatic_checkpoint=False,
                          checkpoint_owns_finalization=True, checkpoint_admission_factory=admission,
                          checkpoint_parameter_dependencies=initial_dependencies,
                          protected_scope_resolver=scope, exclusive_mutation=True, batchable=False,
                          description=description)
