"""Literal named geometry capture and retained source/permission origin."""

from __future__ import annotations

import hashlib
import sys
import threading
import time
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument
from .geometry_preview_dto import (
    DEFAULT_DELTAS,
    MAX_CORNERS,
    MAX_EDGES,
    MAX_POLYGONS,
    MAX_SCALE,
    MAX_VERTICES,
    PreviewRefused,
    _bits,
    _name,
    _require,
    canonical,
    make_dto,
)
from .permissions import Permission
from .request_lifecycle import RequestLifetime
from .task_plans import get_task_plans
from .tool_registry import _checkpoint_parameters, check_final_mutation
from .utils import require_blender

START = "preview.geometry_start"
FETCH = "preview.geometry_image"
REQUIRED = (Permission.INSPECT_SCENE, Permission.CAPTURE_VIEWPORT, Permission.ACCESS_EXTERNAL_FILES)
BUILDS = {(4, 5, 14): "62c1db4208e8", (5, 2, 2): "d13f752e3b9c"}
SERVICES = ("state", "registry", "permissions", "checkpoints", "jobs")


def refused(
    reason: str, message: str = "Geometry preview authority or source changed."
) -> BridgeError:
    return BridgeError(
        ErrorCode.OPERATION_FAILED,
        message,
        {
            "reason": reason,
            "scene_changed": False,
            "project_saved": False,
            "preview_published": False,
        },
    )


def require_main_thread():
    if threading.current_thread() is not threading.main_thread():
        raise BridgeError(
            ErrorCode.BLENDER_CONTEXT_ERROR, "Geometry preview requires Blender's main thread."
        )


def stop_gate(
    context: Any, lifetime: RequestLifetime | None = None, deadline: float = float("inf")
) -> None:
    if lifetime is not None:
        RequestLifetime.check(lifetime)
    if time.monotonic() >= deadline:
        raise BridgeError(ErrorCode.TIMEOUT, "Geometry preview deadline expired.")
    flags = context.state.snapshot()
    if flags["emergency_stopped"] or flags["paused"]:
        raise BridgeError(
            ErrorCode.EMERGENCY_STOPPED if flags["emergency_stopped"] else ErrorCode.AGENT_PAUSED,
            "Geometry preview stopped; status and cancellation remain available.",
        )
    callback = context.check_final_request
    if callback is not None:
        callback()


def semantic(store: Any) -> Any:
    # Exact plain runtime metadata only, never native protected/context readers.
    return _checkpoint_parameters(
        {
            "runtime_id": store.runtime_id,
            "plan": store.plan,
            "scope": store.scope,
            "baseline": store.baseline,
            "protection": store.protection,
            "protection_generation": store.protection_generation,
            "evidence_epoch": store.evidence_epoch,
        }
    )


def identity(owner: Any) -> tuple[int, int]:
    pointer, uid = owner.as_pointer(), owner.session_uid
    if type(pointer) is not int or type(uid) is not int or pointer <= 0 or uid <= 0:
        raise refused("SOURCE_IDENTITY_UNAVAILABLE")
    return pointer, uid


def _schema(bpy: Any, owner: Any, family: str, fields: dict[str, tuple[str, int | None]]) -> None:
    _require(type(owner) is getattr(bpy.types, family), "Exact native RNA class required")
    rna = type(owner).bl_rna
    _require(rna.identifier == family, "Native RNA class identity changed")
    for name, (kind, length) in fields.items():
        p = rna.properties.get(name)
        _require(
            p is not None and p.identifier == name and p.is_runtime is False and p.type == kind,
            "Unsupported or runtime RNA descriptor",
        )
        if kind in {"FLOAT", "INT", "BOOLEAN"}:
            _require(
                type(p.array_length) is int and p.array_length == length,
                "Native numeric shape changed",
            )


def capture(bpy: Any, object_name: str) -> dict[str, Any]:
    """Literal named data only; intentionally contains no context/evaluated getter."""
    _name(object_name)
    obj = bpy.data.objects.get(object_name)
    _require(obj is not None, "Named Object missing")
    object_fields = {
        "name": ("STRING", None),
        "type": ("ENUM", None),
        "mode": ("ENUM", None),
        "data": ("POINTER", None),
        "library": ("POINTER", None),
        "override_library": ("POINTER", None),
        "parent": ("POINTER", None),
        "modifiers": ("COLLECTION", None),
        "constraints": ("COLLECTION", None),
        "animation_data": ("POINTER", None),
        "rotation_mode": ("ENUM", None),
        "location": ("FLOAT", 3),
        "rotation_euler": ("FLOAT", 3),
        "scale": ("FLOAT", 3),
        **{k: ("FLOAT", len(v)) for k, v in DEFAULT_DELTAS.items()},
    }
    _schema(bpy, obj, "Object", object_fields)
    _require(
        obj.name == object_name
        and obj.type == "MESH"
        and obj.mode == "OBJECT"
        and obj.library is None
        and obj.override_library is None
        and obj.parent is None
        and len(obj.modifiers) == len(obj.constraints) == 0
        and obj.animation_data is None
        and obj.rotation_mode == "XYZ",
        "Unsupported source Object profile",
    )
    for key, expected in DEFAULT_DELTAS.items():
        actual = tuple(getattr(obj, key))
        _require(
            [_bits(v, MAX_SCALE) for v in actual] == [_bits(v, MAX_SCALE) for v in expected],
            "Nondefault delta transform",
        )
    mesh = obj.data
    _schema(
        bpy,
        mesh,
        "Mesh",
        {
            "library": ("POINTER", None),
            "override_library": ("POINTER", None),
            "animation_data": ("POINTER", None),
            "shape_keys": ("POINTER", None),
            "is_editmode": ("BOOLEAN", 0),
            "users": ("INT", 0),
            "vertices": ("COLLECTION", None),
            "edges": ("COLLECTION", None),
            "polygons": ("COLLECTION", None),
        },
    )
    _require(
        mesh.library is None
        and mesh.override_library is None
        and mesh.animation_data is None
        and mesh.shape_keys is None
        and mesh.is_editmode is False
        and mesh.users == 1,
        "Edit/shared/animated Mesh buffers are unsupported",
    )
    _require(
        3 <= len(mesh.vertices) <= MAX_VERTICES
        and 3 <= len(mesh.edges) <= MAX_EDGES
        and 1 <= len(mesh.polygons) <= MAX_POLYGONS,
        "Geometry outside capture budget",
    )
    # Screen every bounded element descriptor before any geometry payload getter.
    # Dynamic face vertices have static RNA reflection length 3 in both pinned
    # sources; each actual polygon's dynamic length is independently bounded below.
    for collection, family, fields in (
        (mesh.vertices, "MeshVertex", {"co": ("FLOAT", 3)}),
        (mesh.edges, "MeshEdge", {"vertices": ("INT", 2)}),
        (mesh.polygons, "MeshPolygon", {"vertices": ("INT", 3)}),
    ):
        for owner in collection:
            _schema(bpy, owner, family, fields)
    vertices, edges, polygons = [], [], []
    for v in mesh.vertices:
        vertices.append(tuple(v.co))
    for e in mesh.edges:
        edges.append(tuple(e.vertices))
    corners = 0
    for p in mesh.polygons:
        corners += len(p.vertices)
        _require(corners <= MAX_CORNERS and len(p.vertices) <= 64, "Corner budget exceeded")
        polygons.append(tuple(p.vertices))
    return make_dto(
        object_name,
        vertices,
        edges,
        polygons,
        location=tuple(obj.location),
        rotation=tuple(obj.rotation_euler),
        scale=tuple(obj.scale),
    )


def frozen_source(name: str) -> tuple[bytes, tuple, float]:
    require_main_thread()
    bpy = require_blender()
    started = time.perf_counter()
    try:
        dto = capture(bpy, name)
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise refused("STALE_SOURCE")
        identities = identity(obj), identity(obj.data)
        raw = canonical(dto)
    except PreviewRefused as cause:
        raise BridgeError(
            ErrorCode.NOT_IMPLEMENTED,
            str(cause),
            {"profile": "stock_geometry_preview_v1", "scene_changed": False},
        ) from cause
    return raw, identities, (time.perf_counter() - started) * 1000


class GeometryPreviewOrigin:
    """Pre-provider source snapshot; no late source/policy baseline adoption."""

    __slots__ = (
        "_sealed",
        "baseline",
        "binary",
        "binding",
        "binding_facts",
        "build",
        "capture_ms",
        "connection_events",
        "context",
        "context_factory",
        "deadline",
        "digest",
        "final_request",
        "identities",
        "in_gate",
        "invocation",
        "lifetime",
        "lifetime_facts",
        "limit",
        "name",
        "params",
        "protection",
        "provider",
        "raw",
        "registry",
        "request_facts",
        "revision",
        "semantic_origin",
        "services",
        "spec",
        "started",
        "store",
        "used",
        "version",
    )

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise refused("ORIGIN_FACTS_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        raise refused("ORIGIN_FACTS_IMMUTABLE")

    def __init__(self, context: Any, params: Any, handler: Any):
        require_main_thread()
        if type(params) is not dict or set(params) - {"object_name", "time_limit_seconds"}:
            raise invalid_argument(
                "Geometry preview accepts only object_name and time_limit_seconds."
            )
        name = params.get("object_name")
        try:
            _name(name)
        except PreviewRefused as cause:
            raise invalid_argument(str(cause)) from cause
        limit = params.get("time_limit_seconds", 60)
        if type(limit) is not int or not 1 <= limit <= 120:
            raise invalid_argument("time_limit_seconds must be an integer from 1 through 120.")
        self.context, self.params, self.name, self.limit = context, params, name, limit
        self.started, self.deadline = time.monotonic(), time.monotonic() + limit
        self.registry, self.spec = context.registry, context.registry.get(START)
        from .tools.geometry_preview import admission, resolver

        if (
            self.spec.handler is not handler
            or self.spec.toolset != "core"
            or not self.spec.remote
            or self.spec.checkpoint_admission_factory is not admission
            or self.spec.protected_scope_resolver is not resolver
            or not self.spec.modifies
            or self.spec.automatic_checkpoint
            or not self.spec.checkpoint_owns_finalization
            or not self.spec.exclusive_mutation
            or self.spec.batchable
            or self.spec.permissions != frozenset(REQUIRED)
        ):
            raise refused("START_SPEC_CHANGED")
        self.services = tuple(getattr(context, key) for key in SERVICES)
        self.provider = context.permissions._source
        self.context_factory = context.jobs.context_factory
        self.lifetime = context.request_lifecycle or RequestLifetime.local()
        self.lifetime_facts = (
            self.lifetime.connection,
            self.lifetime.delivered,
            self.lifetime.rejected,
            self.lifetime.deadline,
        )
        self.connection_events = (
            None
            if self.lifetime.connection is None
            else (self.lifetime.connection.disconnected, self.lifetime.connection.background_active)
        )
        self.final_request = context.check_final_request
        self.store = get_task_plans(context.state)
        if context.jobs is None or context.jobs.active is not None:
            raise refused("JOB_BUSY")
        if self.registry.executing_mutators or self.store.executing_mutators:
            raise refused("NESTED_START")
        entries = self.registry._mutation_interlock._entries
        if (
            len(entries) != 1
            or entries[-1].context is not context
            or entries[-1].spec is not self.spec
            or entries[-1].params is not params
        ):
            raise refused("CANONICAL_START_REQUIRED")
        self.invocation = entries[-1]
        self.request_facts = _checkpoint_parameters(params)
        self.semantic_origin = semantic(self.store)
        self.baseline, self.protection = self.store.baseline, self.store.protection
        self.revision = self.store.evidence_revision
        self.binding, self.binding_facts, self.used, self.in_gate = None, None, False, False
        stop_gate(context, self.lifetime, self.deadline)
        bpy = require_blender()
        if (
            tuple(bpy.app.version) not in BUILDS
            or bpy.app.build_hash.decode() != BUILDS[tuple(bpy.app.version)]
        ):
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED,
                "Geometry preview requires a qualified official Linux Blender build.",
            )
        if sys.platform != "linux":
            raise BridgeError(
                ErrorCode.NOT_IMPLEMENTED,
                "Geometry preview is currently qualified only on Linux; Windows remains deferred.",
            )
        self.binary, self.build = bpy.app.binary_path, bpy.app.build_hash.decode()
        self.version = bpy.app.version_string
        self.raw, self.identities, self.capture_ms = frozen_source(name)
        self.digest = hashlib.sha256(self.raw).hexdigest()
        object.__setattr__(self, "_sealed", True)

    def bind_checkpoint(self, binding: Any) -> Any:
        if (
            self.binding is not None
            or binding.callback is not self
            or binding.context is not self.context
        ):
            raise refused("ADMISSION_BINDING_CHANGED")
        object.__setattr__(self, "binding", binding)
        object.__setattr__(
            self, "binding_facts", (binding.call_id, binding.readonly_callback, binding.callback)
        )

        # Canonical scope cleanup is caller-local, not a context/wire grant.
        def completed_start():
            manager = self.services[-1]
            job = manager.active
            if job is None or getattr(job, "origin", None) is not self:
                return
            if sys.exc_info()[1] is not None or not self.used:
                manager.cancel_all("geometry start did not complete")
            else:
                job.handoff_ready = True

        return completed_start

    def release_buffer(self):
        object.__setattr__(self, "raw", b"")

    def _static(self, context: Any, *, admission: bool = False) -> None:
        if (
            self.lifetime.connection is not self.lifetime_facts[0]
            or self.lifetime.delivered is not self.lifetime_facts[1]
            or self.lifetime.rejected is not self.lifetime_facts[2]
            or self.lifetime.deadline != self.lifetime_facts[3]
            or (
                self.connection_events is not None
                and (
                    self.lifetime.connection.disconnected is not self.connection_events[0]
                    or self.lifetime.connection.background_active is not self.connection_events[1]
                )
            )
        ):
            raise refused("LIFETIME_CHANGED")
        if (
            any(
                getattr(context, key) is not value
                for key, value in zip(SERVICES, self.services, strict=True)
            )
            or context.permissions._source is not self.provider
            or context.jobs.context_factory is not self.context_factory
            or context.registry.get(START) is not self.spec
            or self.spec.toolset not in context.registry.enabled_toolsets
            or getattr(context.state, "_artist_task_plans", None) is not self.store
            or self.store.baseline is not self.baseline
            or self.store.protection is not self.protection
            or semantic(self.store) != self.semantic_origin
        ):
            raise refused("AUTHORITY_CHANGED")
        if admission:
            if (
                context is not self.context
                or context.check_final_request is not self.final_request
                or _checkpoint_parameters(self.params) != self.request_facts
                or self.binding is None
                or context.checkpoint_admission is not self.binding
                or not self.binding.matches(self.spec, self.params, context)
                or not self.binding.active
                or self.binding.callback is not self
                or self.binding.call_id is not self.binding_facts[0]
                or self.binding.readonly_callback is not self.binding_facts[1]
                or not any(
                    entry is self.invocation for entry in self.registry._mutation_interlock._entries
                )
            ):
                raise refused("ADMISSION_CHANGED")
            counters = self.registry.executing_mutators, self.store.executing_mutators
            if counters == (0, 0):
                expected = self.revision
            elif (
                counters == (1, 1)
                and self.invocation.continuation_id in self.registry._mutation_interlock._consumed
            ):
                expected = self.revision + 1
            else:
                raise refused("FRAMEWORK_COUNTER_CHANGED")
            if self.store.evidence_revision != expected:
                raise refused("FRAMEWORK_COUNTER_CHANGED")
        elif context.check_final_request is not None:
            raise refused("JOB_SAFE_POINT_CHANGED")
        elif (
            self.registry.active_exclusive_mutation
            or self.registry.executing_mutators
            or self.store.executing_mutators
        ):
            raise refused("NESTED_MUTATOR")
        stop_gate(context, self.lifetime, self.deadline)

    def check_after_read(self) -> None:
        self._static(self.context, admission=True)
        try:
            raw, ids, _elapsed = frozen_source(self.name)
        except BridgeError as cause:
            raise refused("STALE_SOURCE") from cause
        if raw != self.raw or ids != self.identities:
            raise refused("STALE_SOURCE")
        self._static(self.context, admission=True)
        check_final_mutation(self.context, START, expected_spec=self.spec)

    def __call__(self) -> None:
        if self.in_gate:
            raise refused("ADMISSION_REENTRY")
        object.__setattr__(self, "in_gate", True)
        try:
            self._static(self.context, admission=True)
            self.context.require(*REQUIRED)
            self.check_after_read()
        finally:
            object.__setattr__(self, "in_gate", False)

    def enter(self) -> None:
        self.check_after_read()
        if (
            self.used
            or self.in_gate
            or self.invocation.continuation_id not in self.registry._mutation_interlock._consumed
        ):
            raise refused("CONTINUATION_LOST")
        object.__setattr__(self, "used", True)
        self.context.checkpoint_finalization_owner = self.context.checkpoint_call_id

    def check_job(self, context: Any, *, source: bool = False, grants: bool = True) -> None:
        self._static(context)
        if grants:
            context.require(*REQUIRED)
            self._static(context)
        if source:
            try:
                raw, ids, _elapsed = frozen_source(self.name)
            except BridgeError as cause:
                raise refused("STALE_SOURCE") from cause
            if hashlib.sha256(raw).hexdigest() != self.digest or ids != self.identities:
                raise refused("STALE_SOURCE")
        self._static(context)
