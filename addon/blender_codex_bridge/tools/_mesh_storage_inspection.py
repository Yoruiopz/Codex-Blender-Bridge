"""Private read-only inspection phases; their evidence cannot authorize a writer.

Every native operation retains the original B2 access guards. The last phase
repeats the complete protected comparison without yielding. Cooperative yields
therefore shorten the initial request, not that final indivisible comparison.
"""
from __future__ import annotations

import json
import math

from .. import mesh_storage_contract as contract
from .. import mesh_storage_prepare as primitive
from .. import mesh_storage_source as source
from ..errors import BridgeError


def _literal(value, *, depth=0, budget=None):
    """Copy only builtin facts, without foreign equality/encoding callbacks."""
    if budget is None:
        budget = [131072]
    budget[0] -= 1
    if depth > 32 or budget[0] < 0:
        raise contract.inspection_refused("INSPECTION_FACT_BUDGET", status="INCOMPLETE")
    kind = type(value)
    if value is None or kind is bool or kind is int or kind is str:
        return value
    if kind is float and math.isfinite(value):
        return value
    if kind is tuple or kind is list:
        return [_literal(item, depth=depth + 1, budget=budget) for item in value]
    if kind is dict and all(type(key) is str for key in value):
        return {key: _literal(item, depth=depth + 1, budget=budget) for key, item in value.items()}
    raise contract.inspection_refused("INSPECTION_FACT_TYPE_CHANGED")


def _encoded(value):
    return json.dumps(_literal(value), sort_keys=True, ensure_ascii=True,
                      allow_nan=False, separators=(",", ":")).encode("ascii")


def _parameter_stamp(parameters):
    if (type(parameters) is not contract.Parameters or type(parameters.object_name) is not str
            or type(parameters.mesh_name) is not str or type(parameters.attribute_names) is not tuple
            or any(type(name) is not str for name in parameters.attribute_names)
            or type(parameters.time_limit_seconds) is not float
            or not math.isfinite(parameters.time_limit_seconds)
            or parameters.expected_preparation_fingerprint is not None):
        raise contract.inspection_refused("INSPECTION_PARAMETERS_CHANGED")
    return _encoded(parameters.plain())


def _roles_stamp(roles):
    source.CheckpointRoles.check_identity(roles, roles.origin)
    if roles.phase != 0 or roles.native_push_completed is not False:
        raise contract.inspection_refused("INSPECTION_ROLE_PHASE_CHANGED")
    return _encoded({"initial": roles.initial_roles, "identities": roles.identities,
                     "memberships": roles.memberships, "before": roles.before_readback,
                     "last": roles.last_readback, "after": roles.after_readback,
                     "bound": roles.bound_digest})


def _plan_stamp(plan):
    if (type(plan) is not primitive.PreparationPlan or type(plan.metadata) is not primitive._Metadata
            or type(plan.targets) is not tuple or type(plan.metadata.attributes) is not tuple
            or type(plan.resources) is not tuple
            or any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str for row in plan.resources)
            or any(type(row) is not primitive.AttributeHeader for row in plan.metadata.attributes)
            or any(type(row) is not primitive.Target or (row.header is not None
                       and type(row.header) is not primitive.AttributeHeader) for row in plan.targets)):
        raise contract.inspection_refused("INSPECTION_PLAN_TYPE_CHANGED")
    for target in plan.targets:
        if type(target.name) is not str or type(target.action) is not str:
            raise contract.inspection_refused("INSPECTION_PLAN_TYPE_CHANGED")
    for header in (*plan.metadata.attributes, *(row.header for row in plan.targets if row.header is not None)):
        if (type(header.count) is not int or any(type(getattr(header, name)) is not str for name in
                ("name", "domain", "data_type", "native_class", "value_class", "storage",
                 "schema_sha256", "value_schema_sha256"))):
            raise contract.inspection_refused("INSPECTION_PLAN_TYPE_CHANGED")
    _literal(plan.resources)
    _literal(plan.metadata.plain())
    return _encoded(plan.summary())


def _context_stamp(bpy, roles):
    """Anchor the native context through the original guarded role reader."""
    read = roles.access
    context = read.call(getattr, bpy, "context")
    mode = source.graph._text(read.raw(context, "mode"))
    scene = read.raw(context, "scene")
    layer = read.raw(context, "view_layer")
    active = read.active(layer)
    selected = read.bounded(read.raw(context, "selected_objects"), 512, "inspection selection")
    selection = [read.identity(owner, "Object") for owner in selected]
    return _encoded({"mode": mode, "scene": read.identity(scene, "Scene"),
                     "active": None if active is None else read.identity(active, "Object"),
                     "selection": sorted(selection, key=_encoded)})


class MeshStorageInspectionDriver:
    """Three owned read turns with immutable inter-turn evidence anchors."""

    kind = "mesh.attribute_storage_inspection"
    required_permissions = contract.PERMISSIONS

    def __init__(self, context, params, bpy, *, source_seal=None):
        # Admission constructs this before permission providers. No RNA access,
        # checkpoint, native undo, storage materialization or image read here.
        self.parameters = contract.parse(params)
        self.parameter_stamp = _parameter_stamp(self.parameters)
        self.source_seal = source.SourceSeal.capture(inspection=True) if source_seal is None else source_seal
        source.verify_seal(self.source_seal)
        lifetime = context.request_lifecycle
        connection = None if lifetime is None else lifetime.connection
        store = source.get_task_plans(context.state)
        self.session_scope = (context.registry, context.state, connection, store, store.evidence_epoch)
        self.session_stamp = _encoded({"registry": id(context.registry), "state": id(context.state),
                                       "connection": None if connection is None else id(connection),
                                       "plan_epoch": store.evidence_epoch})
        self.bpy = bpy
        self.label = "Inspect mesh attribute storage " + self.parameters.mesh_name
        self.phase, self.done, self.result = "inspection_plan", False, None
        self.gate = self.origin = self.initial = self.bindings = self.excluded = None
        self.checkpoint_roles = self.role_stamp = self.metadata_stamp = self.protected_bytes = None
        self.plan_stamp = self.minimum_floor = None
        self.context_stamp = None

    def check_after_read(self, context):
        """Pure cached-state checks, including before fresh context adoption."""
        source.verify_seal(self.source_seal)
        registry, state, connection, store, epoch = self.session_scope
        lifetime = context.request_lifecycle
        current_connection = None if lifetime is None else lifetime.connection
        if (context.registry is not registry or context.state is not state or current_connection is not connection
                or source.get_task_plans(state) is not store or type(store.evidence_epoch) is not int
                or store.evidence_epoch != epoch):
            raise contract.inspection_refused("INSPECTION_SESSION_CHANGED")
        if type(self.parameter_stamp) is not bytes or _parameter_stamp(self.parameters) != self.parameter_stamp:
            raise contract.inspection_refused("INSPECTION_PARAMETERS_CHANGED")
        if (type(self.phase) is not str or type(self.done) is not bool
                or self.phase not in ("inspection_plan", "inspection_capture", "inspection_seal", "inspection_complete")):
            raise contract.inspection_refused("INSPECTION_PHASE_CHANGED")
        if self.initial is not None:
            if (_plan_stamp(self.initial) != self.plan_stamp
                    or _encoded(self.initial.metadata.plain()) != self.metadata_stamp
                    or self.initial.metadata.obj is not self.checkpoint_roles.obj
                    or self.initial.metadata.mesh is not self.checkpoint_roles.mesh):
                raise contract.inspection_refused("INSPECTION_METADATA_ANCHOR_CHANGED")
            if (type(self.minimum_floor) is not int or type(self.gate.floor) is not int
                    or self.gate.floor < self.minimum_floor):
                raise contract.inspection_refused("INSPECTION_MEMORY_FLOOR_CHANGED")
            if _roles_stamp(self.checkpoint_roles) != self.role_stamp:
                raise contract.inspection_refused("INSPECTION_ROLE_CACHE_CHANGED")

    def _current(self, gate):
        current = source.build_plan(self.bpy, self.parameters, gate, self.origin)
        try:
            source.metadata_matches(current.metadata, self.initial.metadata, set())
            source.CheckpointRoles.check_after_read(self.checkpoint_roles)
        except BridgeError as error:
            # Preserve native/control failures. Metadata mismatch is a known
            # observation of drift; no new baseline is adopted on refusal.
            if error.context.get("reason") == "STORAGE_FORWARD_METADATA_CHANGED":
                raise contract.inspection_refused("INSPECTION_METADATA_STALE") from error
            raise
        return current

    def _metadata_after_read(self, gate):
        # build_plan would call the original authorization provider again.
        # Reuse its exact checked metadata reader without a late provider.
        gate.pure()
        pure = primitive._guards(self.origin)[0]
        pure()
        current = primitive._Access(self.bpy, pure).snapshot(
            self.parameters.object_name, self.parameters.mesh_name)
        try:
            source.metadata_matches(current, self.initial.metadata, set())
        except BridgeError as error:
            if error.context.get("reason") == "STORAGE_FORWARD_METADATA_CHANGED":
                raise contract.inspection_refused("INSPECTION_METADATA_STALE") from error
            raise
        pure()

    def advance(self, context):
        try:
            return self._advance(context)
        except BridgeError as error:
            reason = error.context.get("reason") if type(error.context) is dict else None
            if type(reason) is str and reason in (
                    "STORAGE_CHECKPOINT_MAIN_OWNER_CHANGED", "STORAGE_CHECKPOINT_NATIVE_ROLES_CHANGED",
                    "STORAGE_CHECKPOINT_ACTIVE_OWNER_CHANGED", "STORAGE_CHECKPOINT_STRUCTURAL_MEMBERSHIPS_CHANGED",
                    "SCENE_OBJECT_REFERENCE_ROLES_CHANGED", "STORAGE_CHECKPOINT_SCENE_SELF_CONSUMERS_CHANGED"):
                error.context.update(inspection_status="STALE", write_authorized=False)
            raise

    def _advance(self, context):
        self.check_after_read(context)
        if self.done:
            raise contract.inspection_refused("INSPECTION_ALREADY_COMPLETE")
        if self.phase == "inspection_plan":
            gate = source.Gate(context, self.source_seal, contract.INSPECTION_START)
            gate.authorize()
            origin = primitive.CaptureOrigin.capture(gate.pure, authorize=gate.authorize)
            initial = source.build_plan(self.bpy, self.parameters, gate, origin)
            plan_stamp = _plan_stamp(initial)
            gate.pure()
            app = gate_call(gate, getattr, self.bpy, "app")
            build_hash = gate_call(gate, getattr, app, "build_hash")
            types = gate_call(gate, getattr, self.bpy, "types")
            bindings = primitive.qualify_collection_bindings(types, build_hash=build_hash,
                expected_sha256=primitive.COLLECTION_BINDING_PINS.get(build_hash))
            gate.pure()
            excluded = frozenset(row.name for row in initial.targets if row.action == "MATERIALIZE_SINGLE")
            roles = source.CheckpointRoles(self.bpy, initial.metadata, gate)
            role_stamp, metadata_stamp = _roles_stamp(roles), _encoded(initial.metadata.plain())
            minimum_floor = gate.floor
            context_stamp = _context_stamp(self.bpy, roles)
            gate.pure()
            # Commit only after the final guard; the core holds every previous
            # driver-field identity during native reads and permission calls.
            self.gate, self.origin, self.initial = gate, origin, initial
            self.bindings, self.excluded, self.checkpoint_roles = bindings, excluded, roles
            self.role_stamp, self.metadata_stamp, self.phase = role_stamp, metadata_stamp, "inspection_capture"
            self.plan_stamp, self.minimum_floor = plan_stamp, minimum_floor
            self.context_stamp = context_stamp
            return {"phase": self.phase, "completed": 1, "total": 3}

        gate = self.gate
        gate.context = context  # Exact canonical inspection admission proof.
        gate.authorize()
        self.check_after_read(context)
        current = self._current(gate)
        if _context_stamp(self.bpy, self.checkpoint_roles) != self.context_stamp:
            raise contract.inspection_refused("INSPECTION_CONTEXT_STALE")
        facts = source.protected_facts(self.bpy, current.metadata, gate, self.bindings, self.excluded,
                                       checkpoint_roles=self.checkpoint_roles)
        encoded = _encoded(facts)
        if _context_stamp(self.bpy, self.checkpoint_roles) != self.context_stamp:
            raise contract.inspection_refused("INSPECTION_CONTEXT_STALE")
        if self.phase == "inspection_capture":
            self._metadata_after_read(gate)
            role_stamp = _roles_stamp(self.checkpoint_roles)
            gate.pure()
            self.protected_bytes, self.role_stamp, self.phase = encoded, role_stamp, "inspection_seal"
            return {"phase": self.phase, "completed": 2, "total": 3}

        # No yield, provider, context adoption or rebasing between this complete
        # scope comparison and the original checkpoint-role binding.
        if encoded != self.protected_bytes:
            raise contract.inspection_refused("INSPECTION_PROTECTED_SCOPE_STALE")
        source.CheckpointRoles.bind_protected(self.checkpoint_roles, facts)
        self._metadata_after_read(gate)
        role_stamp = _roles_stamp(self.checkpoint_roles)
        result = {"schema": "mesh_storage_inspection_v1", "policy": contract.INSPECTION_POLICY,
                  **self.parameters.plain(), "plan": self.initial.summary(), "inspection_status": "COHERENT",
                  "inspection_fingerprint": contract.digest({"policy": contract.INSPECTION_POLICY,
                      "parameters": self.parameters.plain(), "metadata": self.metadata_stamp.hex(),
                      "protected": contract.digest(facts), "source": self.source_seal.fingerprint(),
                      "session": self.session_stamp.hex()}),
                  "protected_logical_scope_sha256": contract.digest(facts),
                  "checkpoint_roles": source.CheckpointRoles.report(self.checkpoint_roles),
                  "write_authorized": False, "native_calls_preemptible": False,
                  "transient_intervening_edits_detectable": False,
                  "edits_before_first_observation_detectable": False,
                  "writer_handoff_supported": False,
                  "physical_read_effects": {"ARRAY_COW_or_tagging_possible": True,
                                            "image_buffer_cache_changes_possible": True},
                  "undo_boundary_created": False, "project_saved": False,
                  "native_functional_qualified": False, "publicly_registered": False}
        gate.pure()
        self.role_stamp, self.result, self.done, self.phase = role_stamp, result, True, "inspection_complete"
        return {"phase": self.phase, "completed": 3, "total": 3}


def gate_call(gate, function, *args):
    """Only for build metadata; complete native readers retain original guards."""
    gate.pure()
    result = function(*args)
    gate.pure()
    return result
