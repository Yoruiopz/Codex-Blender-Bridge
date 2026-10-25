"""Typed isolated authored-geometry preview, never current viewport capture."""

from __future__ import annotations

import re

from ..geometry_preview_source import (
    FETCH,
    REQUIRED,
    SERVICES,
    START,
    GeometryPreviewOrigin,
    refused,
    require_main_thread,
    stop_gate,
)
from ..tool_registry import _checkpoint_parameters
from ..utils import reject_unknown_params


def admission(context, params):
    return GeometryPreviewOrigin(context, params, start)


def resolver(context, params):
    binding = context.checkpoint_admission
    origin = None if binding is None else binding.callback
    if (
        type(origin) is not GeometryPreviewOrigin
        or origin.params is not params
        or origin.context is not context
    ):
        raise refused("ADMISSION_REQUIRED")
    origin._static(
        context, admission=True
    )  # Pure policy/identity proof; native CAS belongs to admission.
    return {
        "scope_complete": True,
        "affected_objects": [],
        "original_Main_write_set": [],
        "managed_process_and_files": True,
    }


def start(context, params):
    binding = context.checkpoint_admission
    origin = None if binding is None else binding.callback
    if type(origin) is not GeometryPreviewOrigin or origin.params is not params:
        raise refused("ADMISSION_REQUIRED")
    return context.jobs.start_geometry(context, origin)


class ImageAdmission:
    __slots__ = (
        "_sealed",
        "binding",
        "binding_facts",
        "context",
        "facts",
        "final_request",
        "lifetime",
        "params",
        "services",
        "spec",
    )

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise refused("FETCH_ORIGIN_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        raise refused("FETCH_ORIGIN_IMMUTABLE")

    def __init__(self, context, params):
        require_main_thread()
        self.context, self.params = context, params
        self.facts = _checkpoint_parameters(params)
        self.spec = context.registry.get(FETCH)
        if (
            self.spec.handler is not image
            or self.spec.modifies
            or self.spec.toolset != "core"
            or not self.spec.remote
            or self.spec.permissions != frozenset(REQUIRED)
            or self.spec.batchable
            or self.spec.checkpoint_admission_factory is not ImageAdmission
        ):
            raise refused("FETCH_SPEC_CHANGED")
        self.services = tuple(getattr(context, key) for key in SERVICES)
        self.final_request, self.lifetime = context.check_final_request, context.request_lifecycle
        self.binding, self.binding_facts = None, None
        object.__setattr__(self, "_sealed", True)

    def bind_checkpoint(self, binding):
        if self.binding is not None or binding.callback is not self:
            raise refused("FETCH_BINDING_CHANGED")
        object.__setattr__(self, "binding", binding)
        object.__setattr__(
            self, "binding_facts", (binding.call_id, binding.readonly_callback, binding.callback)
        )

    def check_after_read(self):
        context = self.context
        if (
            self.binding is None
            or self.binding.call_id is not self.binding_facts[0]
            or self.binding.readonly_callback is not self.binding_facts[1]
            or self.binding.callback is not self.binding_facts[2]
            or not self.binding.matches(self.spec, self.params, context)
            or context.registry.get(FETCH) is not self.spec
            or context.check_final_request is not self.final_request
            or context.request_lifecycle is not self.lifetime
            or _checkpoint_parameters(self.params) != self.facts
            or any(
                getattr(context, key) is not value
                for key, value in zip(SERVICES, self.services, strict=True)
            )
        ):
            raise refused("FETCH_AUTHORITY_CHANGED")
        stop_gate(context, self.lifetime)

    def __call__(self):
        self.check_after_read()
        self.context.require(*REQUIRED)
        self.check_after_read()


def image(context, params):
    binding = context.checkpoint_admission
    origin = None if binding is None else binding.callback
    if type(origin) is not ImageAdmission:
        raise refused("FETCH_ADMISSION_REQUIRED")
    origin()
    reject_unknown_params(params, {"preview_id"})
    value = params.get("preview_id")
    if type(value) is not str or re.fullmatch(r"geometry_preview_[a-f0-9]{32}", value) is None:
        raise refused("PREVIEW_ID_INVALID")
    result = context.jobs.geometry_image(context, value)
    origin.check_after_read()
    return result


def register_tools(registry):
    registry.register(
        START,
        start,
        modifies=True,
        automatic_checkpoint=False,
        checkpoint_owns_finalization=True,
        exclusive_mutation=True,
        batchable=False,
        permissions=REQUIRED,
        checkpoint_admission_factory=admission,
        protected_scope_resolver=resolver,
        description="Start one bounded authored-geometry preview in an isolated official Blender worker; source Main is unchanged, original appearance is excluded.",
    )
    registry.register(
        FETCH,
        image,
        permissions=REQUIRED,
        batchable=False,
        checkpoint_admission_factory=ImageAdmission,
        description="Retrieve a fresh session-local geometry-preview PNG; refuses stale/expired source or lost consent.",
    )
