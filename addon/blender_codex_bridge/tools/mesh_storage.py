"""Fixture-local typed B2 handlers. Never imported by the public registry."""
from __future__ import annotations

from dataclasses import dataclass

from .. import mesh_storage_contract as contract
from .. import mesh_storage_prepare as primitive
from .. import mesh_storage_source as source
from ..scene_jobs import _StartAdmission, _TurnAdmission, start_admission
from ..utils import require_blender
from ._mesh_storage_job import MeshStorageDriver
from .artist_loop import check_affected


@dataclass(frozen=True, slots=True, eq=False)
class _PreviewAdmission:
    """Bind preview context before the registry's first permission provider."""
    context: object
    seal: object
    entry_guard: object = None
    entry_proof: object = None

    def bind_checkpoint(self, _binding):
        context, seal = self.context, self.seal
        proof = source.capture_context(context, seal)

        def checked():
            # No mutable module helper is dispatched before the held verifier
            # has proved its own code and the complete registration closure.
            raw = ().__class__.__getitem__
            fact, native = raw(seal, 7), raw(seal, 4)
            function, code, namespace, defaults, keywords, closure = fact
            kind, failure = raw(native, 0), raw(native, 8)
            if (kind(function) is not raw(native, 4) or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__defaults__ is not defaults
                    or function.__kwdefaults__ is not keywords or function.__closure__ is not closure):
                raise failure
            function(seal)
            if type(self) is not _PreviewAdmission or self.entry_guard is not checked:
                raise contract.refused("STORAGE_CONTEXT_CHANGED")
            source.verify_context(context, proof)

        object.__setattr__(self, "entry_guard", checked)
        # Executor cancellation callbacks may run between bind and prepare.
        # Retain this original closure rather than adopting a later callback.
        object.__setattr__(self, "entry_proof", (checked, checked.__code__, checked.__globals__, checked.__defaults__,
                            checked.__kwdefaults__, checked.__closure__,
                            tuple((cell, cell.cell_contents) for cell in checked.__closure__ or ())))

    def __call__(self):
        self.check_after_read()

    def check_after_read(self):
        self.entry_guard()


def preview(context, params, *, source_seal=None):
    parameters = contract.parse(params)
    seal = source.SourceSeal.capture() if source_seal is None else source_seal
    gate = source.Gate(context, seal, contract.PREVIEW)
    gate.authorize()
    bpy = require_blender()
    origin = primitive.CaptureOrigin.capture(gate.pure, authorize=gate.authorize)
    plan = source.build_plan(bpy, parameters, gate, origin)
    bindings = primitive.qualify_collection_bindings(bpy.types, build_hash=bpy.app.build_hash,
        expected_sha256=primitive.COLLECTION_BINDING_PINS.get(bpy.app.build_hash))
    excluded = frozenset(row.name for row in plan.targets if row.action == "MATERIALIZE_SINGLE")
    facts = source.protected_facts(bpy, plan.metadata, gate, bindings, excluded)
    return {"policy": contract.POLICY, **parameters.plain(), "plan": plan.summary(),
            "expected_preparation_fingerprint": source.preview_fingerprint(context, parameters, plan, facts, seal),
            "maximum_active_jobs": 1, "one_attribute_per_turn": True,
            "protected_logical_scope_sha256": contract.digest(facts),
            "SINGLE_pre_value_hash_available": False, "native_calls_preemptible": False,
            "physical_read_effects": {"ARRAY_COW_or_tagging_possible": True, "image_cache_changes_possible": True},
            "inverse_available": False, "project_saved": False, "native_functional_qualified": False,
            "publicly_registered": False}


def driver_factory(context, params, *, source_seal=None):
    return MeshStorageDriver(context, params, require_blender(), source_seal=source_seal)


def start(context, params):
    parameters = contract.parse(params, starting=True)
    return context.jobs.start_scene(context, params, time_limit=parameters.time_limit_seconds)


def protected_scope(context, params):
    contract.parse(params, starting=True)
    binding = context.checkpoint_admission
    callback = None if binding is None else binding.callback
    if type(callback) is _StartAdmission:
        driver = callback.driver
    elif type(callback) is _TurnAdmission:
        driver = callback.job.driver
    else:
        raise contract.refused("STORAGE_PROTECTED_ADMISSION_REQUIRED")
    if type(driver) is not MeshStorageDriver:
        raise contract.refused("STORAGE_EXACT_DRIVER_REQUIRED")
    driver.check_after_read(context)
    check_affected(context, driver.bpy, (driver.initial.metadata.obj,))
    return {"scope_complete": True, "affected_objects": [driver.parameters.object_name]}


def register_private(registry):
    """Explicit in-process fixture registration, not an RPC capability."""
    # Source closure is frozen before the FIRST request permission provider;
    # constructing a fresh closure after it would adopt a replacement helper.
    seal = source.SourceSeal.capture()
    verify = source.SourceSeal.__dict__["verify"]
    proof = (verify, verify.__code__, verify.__globals__, verify.__defaults__, verify.__kwdefaults__, verify.__closure__)
    failure = contract.refused("STORAGE_REGISTRATION_SOURCE_CHANGED")

    def checked_preview(context, params):
        function, code, namespace, defaults, keywords, closure = proof
        if (function.__code__ is not code or function.__globals__ is not namespace
                or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords
                or function.__closure__ is not closure):
            raise failure
        function(seal)
        return preview(context, params, source_seal=seal)

    def checked_factory(context, params):
        function, code, namespace, defaults, keywords, closure = proof
        if (function.__code__ is not code or function.__globals__ is not namespace
                or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords
                or function.__closure__ is not closure):
            raise failure
        function(seal)
        return driver_factory(context, params, source_seal=seal)

    def checked_preview_admission(context, params):
        function, code, namespace, defaults, keywords, closure = proof
        if (function.__code__ is not code or function.__globals__ is not namespace
                or function.__defaults__ is not defaults or function.__kwdefaults__ is not keywords
                or function.__closure__ is not closure):
            raise failure
        function(seal)
        contract.parse(params)
        return _PreviewAdmission(context, seal)

    registry.register(contract.PREVIEW, checked_preview, permissions=contract.PERMISSIONS, toolset="geometry",
                      batchable=False, checkpoint_admission_factory=checked_preview_admission,
                      description="Inspect exact metadata and bounded storage-preparation intent.")
    registry.register(contract.START, start, permissions=contract.PERMISSIONS, toolset="geometry",
                      modifies=True, automatic_checkpoint=False, checkpoint_owns_finalization=True,
                      exclusive_mutation=True, batchable=False, checkpoint_admission_factory=start_admission(checked_factory),
                      protected_scope_resolver=protected_scope,
                      description="Prepare one selected attribute per owned Scene turn; retain partial preparation.")
