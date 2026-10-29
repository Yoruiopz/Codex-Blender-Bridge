"""Private Scene driver: one explicit attribute materialization per turn."""
from __future__ import annotations

import time

from .. import mesh_storage_contract as contract
from .. import mesh_storage_prepare as primitive
from .. import mesh_storage_source as source
from ..mesh_storage_effects import MeshStorageJournal


class MeshStorageDriver:
    kind = "mesh.attribute_storage_preparation"
    required_permissions = contract.PERMISSIONS

    def __init__(self, context, params, bpy, *, source_seal=None):
        self.parameters = contract.parse(params, starting=True)
        self.source_seal = source.SourceSeal.capture() if source_seal is None else source_seal
        self.source_seal.verify()
        self.gate = source.Gate(context, self.source_seal)
        self.origin = primitive.CaptureOrigin.capture(self.gate.pure, authorize=self.gate.authorize)
        self.bpy = bpy
        self.initial = source.build_plan(bpy, self.parameters, self.gate, self.origin)
        self.bindings = primitive.qualify_collection_bindings(bpy.types, build_hash=bpy.app.build_hash,
            expected_sha256=primitive.COLLECTION_BINDING_PINS.get(bpy.app.build_hash))
        self.excluded = frozenset(row.name for row in self.initial.targets if row.action == "MATERIALIZE_SINGLE")
        self.checkpoint_roles = source.CheckpointRoles(bpy, self.initial.metadata, self.gate)
        self.protected = source.protected_facts(bpy, self.initial.metadata, self.gate, self.bindings, self.excluded,
                                                 checkpoint_roles=self.checkpoint_roles)
        self.protected_digest = contract.digest(self.protected)
        source.CheckpointRoles.bind_protected(self.checkpoint_roles, self.protected)
        self.checkpoint_origin = self.checkpoint_roles.origin
        self.fingerprint = source.preview_fingerprint(context, self.parameters, self.initial, self.protected, self.source_seal)
        if self.fingerprint != self.parameters.expected_preparation_fingerprint:
            raise contract.refused("STORAGE_PREVIEW_STALE")
        self.storage_effects = MeshStorageJournal(self.parameters.attribute_names)
        self.label = "Prepare mesh attribute storage " + self.parameters.mesh_name
        self.index, self.done, self.result = 0, False, None
        self.phase = "mesh_storage_attribute_0"
        self.completed = set()
        self.value_hashes = {}
        self.preparation_elapsed_seconds = 0.

    def check_after_read(self, context):
        self.source_seal.verify()
        if context.check_final_job is not None:
            turn = context.registry._scene_reservations.current(context)
            if turn.check_only:
                return  # Canonical provider-ordered paused/handoff check; no native inspection.
        self.gate.context = context
        self.gate.pure()
        source.CheckpointRoles.check_identity(self.checkpoint_roles, self.checkpoint_origin)
        source.CheckpointRoles.check_after_read(self.checkpoint_roles)
        current = source.build_plan(self.bpy, self.parameters, self.gate, self.origin)
        source.metadata_matches(current.metadata, self.initial.metadata, self.completed)
        facts = source.protected_facts(self.bpy, current.metadata, self.gate, self.bindings, self.excluded,
                                       checkpoint_roles=self.checkpoint_roles)
        if contract.digest(facts) != self.protected_digest:
            raise contract.refused("STORAGE_PROTECTED_LOGICAL_STATE_CHANGED")
        for name, expected in self.value_hashes.items():
            header = next(row for row in current.metadata.attributes if row.name == name)
            if source.array_hash(self.bpy, current, header, self.bindings, self.gate.pure) != expected:
                raise contract.refused("STORAGE_COMPLETED_ARRAY_VALUES_CHANGED")
        self.gate.pure()
        source.CheckpointRoles.verified(self.checkpoint_roles, self.protected_digest)

    def native_push_delegates(self):
        source.CheckpointRoles.check_identity(self.checkpoint_roles, self.checkpoint_origin)
        return (self.checkpoint_origin[1],)

    def after_native_push(self):
        source.CheckpointRoles.after_native_push(self.checkpoint_roles, self.checkpoint_origin)

    def advance(self, context):
        if self.done:
            raise contract.refused("STORAGE_JOB_ALREADY_COMPLETE")
        self.gate.context = context
        self.gate.authorize()
        self.check_after_read(context)
        name = self.parameters.attribute_names[self.index]
        plan = source.build_plan(self.bpy, self.parameters, self.gate, self.origin, selected=(name,))
        source.metadata_matches(plan.metadata, self.initial.metadata, self.completed)
        journal = primitive.PreparationJournal.for_plan(plan)
        self.storage_effects.attach(self.index, journal)
        self.gate.pure()
        began = time.monotonic()
        try:
            result = primitive.prepare(self.bpy, plan, bindings=self.bindings, origin=self.origin,
                available_memory_bytes=self.gate.last_available, journal=journal)
        finally:
            # Literal timing only: no stopped driver/provider/native cleanup.
            self.preparation_elapsed_seconds += time.monotonic() - began
        self.gate.pure()
        row = result.rows[0]
        self.completed.add(name)  # Predicted authorized transition, not a metadata rebase.
        if row["materialize_entered"]:
            if row["verified"] is not True or type(row["logical_values_sha256"]) is not str:
                raise contract.refused("STORAGE_MATERIALIZED_ROW_NOT_VERIFIED")
            self.value_hashes[name] = row["logical_values_sha256"]
        self.check_after_read(context)
        self.index += 1
        self.done = self.index == len(self.parameters.attribute_names)
        self.phase = "mesh_storage_complete" if self.done else f"mesh_storage_attribute_{self.index}"
        if self.done:
            self.result = {"schema": "mesh_storage_owned_job_v1", "object_name": self.parameters.object_name,
                "mesh_name": self.parameters.mesh_name, "attributes": list(self.parameters.attribute_names),
                "preparation_fingerprint": self.fingerprint, "completed_attributes": self.index,
                "verified_materialized_value_hashes": dict(self.value_hashes),
                "source_equivalent_before_after": True, "independent_SINGLE_pre_value_hash": False,
                "protected_logical_state_verified": True, "requires_fresh_image_preview": True,
                "native_calls_preemptible": False, "preparation_elapsed_seconds": self.preparation_elapsed_seconds,
                "native_C_blocking_measured": False,
                "checkpoint_roles": source.CheckpointRoles.report(self.checkpoint_roles),
                "inverse_attempted": False, "project_saved": False,
                "physical_read_effects": {"ARRAY_COW_or_tagging_possible": True,
                                          "image_buffer_cache_changes_possible": True},
                "native_functional_qualified": False, "publicly_registered": False}
        return {"phase": self.phase, "completed": self.index, "total": len(self.parameters.attribute_names)}
