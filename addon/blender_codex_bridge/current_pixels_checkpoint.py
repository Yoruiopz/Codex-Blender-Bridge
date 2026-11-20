"""Readonly checkpoint prechecks for the private current-pixel record phase.

A legacy push notification proves no authority and advances no expected native
state. This finite witness refuses any changed ParticleEdit role, including
stock undo-poll changes. The checkpoint manager owns its exact marker deltas;
this witness compares markers across every provider and outside manager calls.
It does not prove pixels, backup files, render/compositor dependencies or an
arbitrary host-Python sandbox. The owning job must supply those separate proofs
and a source-qualified, provider-free final lifetime/stop check.
"""
from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Any, TypeVar

from .checkpoints import MARKER_KEY, TOKEN_PATTERN, CheckpointManager, UndoStep
from .errors import BridgeError, ErrorCode
from .tool_registry import ToolContext
from .tools import _scene_mutation as proof
from .tools._scene_checkpoint_roles import _pointer, _settings
from .tools._scene_evaluation_scope import require_plain_object
from .utils import require_blender

BUILDS = ((b"62c1db4208e8", (4, 5, 14)), (b"d13f752e3b9c", (5, 2, 2)))
MAX_OBJECTS = 16
_Result = TypeVar("_Result")


def _refused(reason: str) -> BridgeError:
    return BridgeError(ErrorCode.OPERATION_FAILED, "Current-pixel checkpoint precheck changed; reinspect before a native write.",
                       {"reason": reason, "checkpoint_precheck_valid": False, "verification_required": True})


def _unsupported(reason: str) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, "Current-pixel checkpoint context is outside the readonly native profile.",
                       {"reason": reason, "checkpoint_precheck_valid": False, "verification_required": True})


def _read_state(bpy: Any, scene: Any, check: Callable[[], None]) -> Any:
    """Finite Scene fields/custom data and ParticleEdit/brush role/settings CAS.

    No writable render/compositor child is projected by this helper. The actual
    job must refuse unreviewed evaluated dependencies independently before undo.
    Runtime Scene pointers are classified by the existing Scene descriptor guard
    but their Python getters are not read. Selection convenience getters are not
    needed in a UI timer context.
    """
    check()
    if not any(bpy.app.build_hash == build and tuple(bpy.app.version) == version for build, version in BUILDS):
        raise _unsupported("OFFICIAL_BUILD_REQUIRED")
    scenes = proof.bounded(bpy.data.scenes, 2, "current-pixel checkpoint Scenes")
    scene_token = proof.token(scene)
    if len(scenes) != 1 or proof.token(scenes[0]) != scene_token:
        raise _unsupported("SINGLE_CURRENT_SCENE_REQUIRED")
    proof.descriptors(bpy, scene)
    if (scene.library is not None or scene.override_library is not None or scene.is_editable is not True
            or scene.animation_data is not None):
        raise _unsupported("LOCAL_UNANIMATED_SCENE_REQUIRED")
    context = bpy.context
    if context.mode != "OBJECT" or proof.token(context.scene) != scene_token:
        raise _unsupported("CURRENT_OBJECT_MODE_REQUIRED")
    layer, window = context.view_layer, context.window
    if window is not None and (proof.token(window.scene) != scene_token or proof.key(window.view_layer) != proof.key(layer)):
        raise _unsupported("CURRENT_WINDOW_LAYER_REQUIRED")
    active = layer.objects.active
    if active is not None:
        require_plain_object(bpy, active)
        if len(active.particle_systems) or _pointer(bpy, active, "soft_body", "SoftBodySettings") is not None:
            raise _unsupported("PLAIN_ACTIVE_OBJECT_REQUIRED")
    settings = _pointer(bpy, scene, "tool_settings", "ToolSettings")
    particle = _pointer(bpy, settings, "particle_edit", "ParticleEdit")
    if any(prop.identifier == "scene" for prop in proof.descriptors(bpy, particle)):
        raise _unsupported("EXPOSED_PARTICLE_SCENE_ROLE")
    particle_object = _pointer(bpy, particle, "object", "Object")
    original = _pointer(bpy, scene, "original", "ID")
    brush = _pointer(bpy, particle, "brush", "ParticleBrush")
    brush_state = None
    if brush is not None:
        if _pointer(bpy, brush, "curve", "CurveMapping") is not None:
            raise _unsupported("PARTICLE_BRUSH_CURVE_UNQUALIFIED")
        brush_state = proof.key(brush), _settings(bpy, brush)
    scalar_fields, custom = proof.primitive(bpy, scene)
    custom = tuple(row for row in custom if row[0] != MARKER_KEY)
    objects = proof.bounded(bpy.data.objects, MAX_OBJECTS, "current-pixel checkpoint Objects")
    counts = []
    for owner in objects:
        proof.descriptors(bpy, owner)
        counts.append((proof.token(owner), int(scene.user_of_id(owner))))
    handlers = proof.runtime(bpy)
    result = (
        proof.token(scene), proof.key(layer), proof.key(window),
        None if window is None else (proof.token(window.scene), proof.key(window.view_layer)),
        context.mode, proof.token(active), scalar_fields, custom,
        proof.key(settings), proof.key(particle), proof.token(original), proof.token(particle_object),
        int(scene.user_of_id(scene)), tuple(sorted(counts)), _settings(bpy, particle), brush_state, handlers,
    )
    check()
    return result


def _pending_facts(step: Any) -> tuple[Any, ...] | None:
    if step is None:
        return None
    if type(step) is not UndoStep:
        raise _refused("PENDING_RECORD_TYPE_CHANGED")
    fields = step.label, step.before_marker, step.sequence, step.kind, step.attempts
    if (type(fields[0]) is not str or len(fields[0]) > 512
            or type(fields[1]) is not str or len(fields[1]) > 128
            or type(fields[2]) is not int or type(fields[3]) is not str or type(fields[4]) is not int):
        raise _refused("PENDING_RECORD_FIELDS_CHANGED")
    return fields


class CheckpointPrecheck:
    """Job-owned readonly facts; phase methods confer no write/push authority."""

    def __init__(self, context: ToolContext, check: Callable[[], None]):
        if type(context) is not ToolContext or not callable(check):
            raise _refused("CONCRETE_CONTEXT_REQUIRED")
        if threading.current_thread() is not threading.main_thread():
            raise _refused("MAIN_THREAD_REQUIRED")
        self.context, self.check = context, check
        self.manager = context.checkpoints
        if type(self.manager) is not CheckpointManager:
            raise _refused("CONCRETE_CHECKPOINT_MANAGER_REQUIRED")
        self.bpy = require_blender()
        self.scene = self.bpy.context.scene
        values = vars(self.manager)
        self.containers = tuple((name, values.get(name)) for name in (
            "_checkpoints", "_window", "_native_push_pending", "_owned_pending"))
        if (any(type(values.get(name)) is not deque for name in ("_checkpoints", "_undo_steps"))
                or any(type(values.get(name)) is not dict for name in ("_native_push_pending", "_owned_pending"))):
            raise _refused("CHECKPOINT_STORAGE_CHANGED")
        self.undo_maxlen = values["_undo_steps"].maxlen
        self.sequence, self.prefix = values.get("_sequence"), values.get("_prefix")
        if type(self.sequence) is not int or self.sequence < 0 or type(self.prefix) is not str:
            raise _refused("CHECKPOINT_IDENTITY_CHANGED")
        self.phase = "CAPTURED"
        self.pending = self.pending_facts = None
        self._services()
        self._idle()
        self.markers = self.manager.capture_job_markers()
        self.expected = _read_state(self.bpy, self.scene, self.check)
        self.check_before_capture_end()

    def check_before_capture_end(self) -> None:
        self._services()
        self._idle()
        self.manager.check_job_markers(self.markers)
        self.check()

    def _services(self) -> None:
        if (threading.current_thread() is not threading.main_thread()
                or self.context.checkpoints is not self.manager or type(self.manager) is not CheckpointManager
                or require_blender() is not self.bpy):
            raise _refused("CHECKPOINT_SERVICE_CHANGED")
        values = vars(self.manager)
        if (any(values.get(name) is not retained for name, retained in self.containers)
                or type(values.get("_prefix")) is not str or values["_prefix"] != self.prefix):
            raise _refused("CHECKPOINT_STORAGE_CHANGED")
        steps = values.get("_undo_steps")
        if type(steps) is not deque or steps.maxlen != self.undo_maxlen or len(steps) > 200:
            raise _refused("CHECKPOINT_UNDO_STORAGE_CHANGED")
        if (values.get("_editor_session") is not None or values.get("_owned_claim") is not None
                or values.get("_owned_pending") or values.get("_native_push_pending")
                or values.get("recovery_in_progress") is not False):
            raise _refused("CHECKPOINT_BUSY")

    def _idle(self) -> None:
        if vars(self.manager).get("_pending") is not None:
            raise _refused("CHECKPOINT_PENDING_CONFLICT")

    def _pending(self) -> None:
        current = vars(self.manager).get("_pending")
        sequence = vars(self.manager).get("_sequence")
        if type(sequence) is not int:
            raise _refused("CHECKPOINT_SEQUENCE_CHANGED")
        if self.phase == "CAPTURED":
            if current is not None or sequence != self.sequence:
                raise _refused("CHECKPOINT_PENDING_CONFLICT")
        elif self.phase == "BEFORE":
            if current is None:
                if sequence != self.sequence:
                    raise _refused("CHECKPOINT_SEQUENCE_CHANGED")
            elif (_pending_facts(current)[2:] != (self.sequence + 1, "operation", 1)
                  or sequence != self.sequence + 1):
                raise _refused("CHECKPOINT_PENDING_CHANGED")
        elif self.phase in {"PENDING", "FINALIZING"}:
            # after_modification clears only after its final read/push guards.
            if current is not self.pending or _pending_facts(current) != self.pending_facts or sequence != self.sequence + 1:
                raise _refused("CHECKPOINT_PENDING_CHANGED")
        elif self.phase == "FINALIZED":
            if current is not None or sequence != self.sequence + 1:
                raise _refused("CHECKPOINT_FINALIZED_STATE_CHANGED")
        else:
            raise _refused("CHECKPOINT_PHASE_CHANGED")

    def check_after_read(self) -> None:
        self._services()
        self._pending()
        if self.phase in {"CAPTURED", "PENDING", "FINALIZED"}:
            self.manager.check_job_markers(self.markers)
        if _read_state(self.bpy, self.scene, self.check) != self.expected:
            raise _refused("SCENE_OR_PARTICLE_STATE_CHANGED")
        self._services()
        self._pending()
        if self.phase in {"CAPTURED", "PENDING", "FINALIZED"}:
            self.manager.check_job_markers(self.markers)
        self.check()

    def check_before_checkpoint(self) -> None:
        if self.phase != "CAPTURED":
            raise _refused("CHECKPOINT_PHASE_CHANGED")
        self.check_after_read()
        self.phase = "BEFORE"

    def with_provider(self, callback: Callable[[], _Result]) -> _Result:
        self.check_after_read()
        pending = vars(self.manager).get("_pending")
        facts = _pending_facts(pending)
        markers = self.manager._marker_evidence(self.bpy)
        undo_steps = vars(self.manager)["_undo_steps"]
        undo_facts = tuple(_pending_facts(step) for step in undo_steps)
        self.check()
        result = callback()
        self._services()
        if vars(self.manager).get("_pending") is not pending or _pending_facts(pending) != facts:
            raise _refused("PROVIDER_CHANGED_PENDING")
        if (vars(self.manager)["_undo_steps"] is not undo_steps
                or tuple(_pending_facts(step) for step in undo_steps) != undo_facts):
            raise _refused("PROVIDER_CHANGED_UNDO_HISTORY")
        self.manager.check_job_markers(markers)
        self.check_after_read()
        return result

    def check_after_push(self) -> None:
        """Legacy observation only: never accept a native role/Scene delta."""
        self.check_after_read()

    def bind_before_pending(self, label: str) -> None:
        if self.phase != "BEFORE":
            raise _refused("CHECKPOINT_PHASE_CHANGED")
        self.check_after_read()
        pending = vars(self.manager).get("_pending")
        facts = _pending_facts(pending)
        if (facts is None or facts[0] != label or facts[2:] != (self.sequence + 1, "operation", 1)
                or type(facts[1]) is not str or TOKEN_PATTERN.fullmatch(facts[1]) is None
                or not facts[1].startswith(self.prefix)):
            raise _refused("CHECKPOINT_PENDING_NOT_OWNED")
        markers = self.manager._marker_evidence(self.bpy)
        self.check()
        self.pending, self.pending_facts, self.markers = pending, facts, markers
        self.phase = "PENDING"

    def before_finalization(self) -> None:
        if self.phase != "PENDING":
            raise _refused("CHECKPOINT_PHASE_CHANGED")
        self.check_after_read()
        self.phase = "FINALIZING"

    def check_finalized(self) -> None:
        if self.phase != "FINALIZING":
            raise _refused("CHECKPOINT_PHASE_CHANGED")
        self._services()
        if (vars(self.manager).get("_pending") is not None
                or vars(self.manager).get("_sequence") != self.sequence + 1
                or not self.manager._undo_steps
                or _pending_facts(self.manager._undo_steps[0]) != self.pending_facts):
            raise _refused("CHECKPOINT_FINALIZED_STATE_CHANGED")
        if _read_state(self.bpy, self.scene, self.check) != self.expected:
            raise _refused("SCENE_OR_PARTICLE_STATE_CHANGED")
        markers = self.manager._marker_evidence(self.bpy)
        self.check()
        self.markers, self.phase = markers, "FINALIZED"


def capture(context: ToolContext, *, check: Callable[[], None]) -> CheckpointPrecheck:
    """Capture before providers; no checkpoint, marker, native write or grant."""
    return CheckpointPrecheck(context, check)
