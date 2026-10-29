"""Canonical session-local GLB intent service; cached reports confer no authority.

No deletion, same-name adoption, cleanup or persistence. Native stages remain
explicitly unqualified until the matching Runtime TCP/installed acceptance.
"""
from __future__ import annotations

import operator
import secrets
import struct
from dataclasses import dataclass, field
from typing import Any

from . import glb_stage_protected_mesh as _protected_mesh
from .asset_glb_import_plan import plan_glb
from .errors import invalid_argument
from .glb_stage_profile import compile_profile, digest, plain, refused
from .glb_stage_source import read_glb_source
from .glb_stage_state import GLBStageStore, _name, _names
from .permissions import Permission
from .request_lifecycle import RequestLifetime
from .tool_registry import check_final_mutation

READ = (Permission.INSPECT_SCENE, Permission.ACCESS_EXTERNAL_FILES)
WRITE = (*READ, Permission.EDIT_SCENE, Permission.TRANSFORM_OBJECTS,
         Permission.EDIT_MESH, Permission.EDIT_MATERIALS)
PUBLISH = tuple(item for item in WRITE if item is not Permission.ACCESS_EXTERNAL_FILES)


@dataclass(slots=True)
class RuntimeStage:
    connection: Any
    generation: str
    root: str
    operations: Any
    gate: Any
    bpy: Any
    protected_ids: dict
    protected: dict
    roles: Any
    roles_sha256: str
    context_scene: Any
    protected_view: Any
    controller: Any = None
    job_id: str | None = None
    job: Any = None
    publication: Any = None
    source_verified: bool = False
    phase_history: list[dict] = field(default_factory=list)


class GLBStageService:
    """Owned only by BridgeRuntime; wire tokens select records, never authority."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.state = runtime.state
        self.registry = runtime.registry
        self.checkpoints = runtime.checkpoints
        self.jobs = runtime.jobs
        self.store = GLBStageStore()
        self._records: dict[str, RuntimeStage] = {}
        self._generation = secrets.token_hex(32)
        self._executor_origin = None
        self._origins = (runtime, runtime.state, runtime.registry, runtime.checkpoints, runtime.jobs, self.store, self._records)

    def invalidate(self) -> None:
        # Revoke BEFORE cancellation/load/undo; never dereference native refs.
        self._generation = secrets.token_hex(32)
        self.store.invalidate()
        for retained in self._records.values():
            retained.gate.revoke()

    def check_context_factory(self, executor) -> None:
        """Pure source/component validation BEFORE any context getter executes."""
        if _PROTECTED_DEPENDENCY_GUARD_ORIGIN.__code__ is not _PROTECTED_DEPENDENCY_GUARD_CODE:
            raise refused("GLB_PROTECTED_DEPENDENCY_ORIGIN_CHANGED")
        _PROTECTED_DEPENDENCY_GUARD_ORIGIN()
        if (type(self) is not GLBStageService or type(executor) is not _Executor
                or vars(_Executor).get("context") is not _EXECUTOR_CONTEXT_PROPERTY
                or _EXECUTOR_CONTEXT_GETTER.__code__ is not _EXECUTOR_CONTEXT_GETTER_CODE):
            raise refused("GLB_CANONICAL_CONTEXT_FACTORY_CHANGED")
        if any(vars(cls).get(name) is not fn or fn.__code__ is not code
               for cls, name, fn, code in _SERVICE_METHOD_ORIGINS):
            raise refused("GLB_CANONICAL_SERVICE_CODE_ORIGIN_CHANGED")
        for cls, expected in _AUTHORITY_CLASS_NAMESPACES:
            namespace = vars(cls)
            if len(namespace) != len(expected) or any(namespace.get(name) is not value for name, value in expected):
                raise refused("GLB_AUTHORITY_CLASS_NAMESPACE_CHANGED")
        for cls, name, raw, function, code in _AUTHORITY_METHOD_ORIGINS:
            if vars(cls).get(name) is not raw or function.__code__ is not code:
                raise refused("GLB_PERMISSION_ENFORCEMENT_CODE_CHANGED")
        for cls in _AUTHORITY_CLASSES:
            if (vars(cls).get("__getattribute__", object.__getattribute__) is not object.__getattribute__
                    or vars(cls).get("__setattr__", object.__setattr__) is not object.__setattr__):
                raise refused("GLB_PERMISSION_ENFORCEMENT_ACCESS_CHANGED")
        owner = self.runtime
        if (executor is not self._executor_origin or owner.executor is not executor
                or executor.glb_stage is not self or executor.state is not self.state
                or owner.state is not self.state or executor.permissions is not owner.permissions
                or executor.registry is not self.registry or executor.jobs is not self.jobs
                or executor.checkpoints is not self.checkpoints):
            raise refused("GLB_CANONICAL_CONTEXT_COMPONENT_CHANGED")
        namespace = vars(self.state)
        if any(type(name) is not str or name in _STATE_METHOD_NAMES for name in namespace):
            raise refused("GLB_STATE_ENFORCEMENT_INSTANCE_SHADOW")

    def check_context(self, context, connection, generation) -> None:
        if type(context) is not _ToolContext:
            raise refused("GLB_CANONICAL_TOOL_CONTEXT_REQUIRED")
        self.check_context_factory(self._executor_origin)
        from . import runtime as module
        if (module.native_save_permission_provider_intact is not module._PERMISSION_PROVIDER_GUARD
                or module.native_save_permission_provider_intact.__code__ is not module._PERMISSION_PROVIDER_GUARD_CODE
                or not module.native_save_permission_provider_intact()):
            raise refused("GLB_CANONICAL_PERMISSION_PROVIDER_CHANGED")
        owner = self.runtime
        from .scene_job_authority import SceneJobPermissions
        manager = context.permissions
        if not _exact_instance_keys(owner.permissions, ("_source",)):
            raise refused("GLB_PERMISSION_MANAGER_INSTANCE_SHADOW")
        if type(manager) is SceneJobPermissions:
            if not _exact_instance_keys(manager, ("base", "service")):
                raise refused("GLB_PERMISSION_VIEW_INSTANCE_SHADOW")
            if manager.service is not self.registry._scene_reservations:
                raise refused("GLB_CONTEXT_PERMISSION_WRAPPER_CHANGED")
            manager = manager.base
        executor = self._executor_origin
        if (executor is None or owner.executor is not executor
                or executor.glb_stage is not self or executor.permissions is not owner.permissions
                or manager is not owner.permissions):
            raise refused("GLB_CONTEXT_PERMISSION_MANAGER_OR_EXECUTOR_CHANGED")
        if (module._RUNTIME is not owner or type(owner) is not module._CANONICAL_RUNTIME_CLASS
                or not owner._registered or getattr(owner, "_glb_stage_origin", None) is not self
                or owner.glb_stage is not self or context.glb_stage is not self
                or context.registry is not self.registry or context.jobs is not self.jobs
                or context.checkpoints is not self.checkpoints or context.state is not self.state
                or any(left is not right for left, right in zip(self._origins,
                    (owner, owner.state, owner.registry, owner.checkpoints, owner.jobs, self.store, self._records), strict=True))
                or generation != self._generation):
            raise refused("GLB_RUNTIME_SERVICE_OR_SESSION_CHANGED")
        lifetime = context.request_lifecycle
        if (type(lifetime) is not RequestLifetime or connection is None
                or lifetime.connection is not connection):
            raise refused("GLB_ORIGINAL_TCP_CONNECTION_REQUIRED")
        lifetime.check()
        check_final_mutation(context, context.checkpoint_method or context.glb_method,
                             expected_spec=self.registry.get(context.checkpoint_method or context.glb_method))

    def _entry(self, context, method, required):
        if type(context) is not _ToolContext:
            raise refused("GLB_CANONICAL_TOOL_CONTEXT_REQUIRED")
        self.check_context_factory(self._executor_origin)
        context.glb_method = method
        lifetime = context.request_lifecycle
        connection = None if lifetime is None else lifetime.connection
        self.check_context(context, connection, self._generation)
        context.require(*required)
        self.check_context(context, connection, self._generation)
        return connection

    def _source_root(self):
        # Only the canonical Runtime preferences provider supplies this root.
        from .runtime import _preferences
        value = getattr(_preferences(), "asset_source_directory", "")
        if type(value) is not str or not value:
            raise invalid_argument("Approve a nonempty asset source directory in Blender preferences.")
        return value

    def preview(self, context, params):
        from .glb_stage_driver import NativeOperations
        from .glb_stage_jobs import RuntimeNativeGate
        from .tools import asset_import as protected_reader
        connection = self._entry(context, "asset.glb_stage_preview", READ)
        if params.get("overwrite_policy", "REFUSE") != "REFUSE":
            raise invalid_argument("Only explicit REFUSE overwrite policy is supported.")
        gate = RuntimeNativeGate(self, connection, self._generation)
        gate.bind(context)
        try:
            root = self._source_root()
            gate.check()
            source = read_glb_source(params.get("filepath"), root, gate.check)
            plan = plan_glb(source.payload, gate.check)
            compile_profile(plan)  # Complete unsupported-feature refusal before IDs.
            if plan.conversion_requirements.missing_uv_zero_fill_corners:
                raise refused("GLB_MIXED_UV_ZERO_FILL_PUBLIC_GATE_OPEN", allocation_started=False)
            operations = NativeOperations(runtime_gate=gate)
            bpy = operations._binding.bpy
            gate.check()
            scene = bpy.context.scene
            if (bpy.context.mode != "OBJECT" or scene.unit_settings.scale_length != 1.
                    or scene.library is not None or scene.override_library is not None
                    or scene.collection.library is not None or scene.collection.override_library is not None):
                raise refused("GLB_LOCAL_OBJECT_MODE_METRE_DESTINATION_REQUIRED", allocation_started=False)
            roles = GLBCheckpointRoles(operations, scene)
            role_hash = digest(roles.authored())
            view = _ProtectedView(operations)
            protected_ids = protected_reader._inventory(view.bpy)
            protected = view.observe(protected_ids, gate.check)
            environment = operations.environment({})
            names = dict(_names(plan, _name(params.get("collection_name"))))
            self._names(operations, names, gate)
            record = self.store.prepare(source, params.get("collection_name"), digest(environment),
                                        overwrite_policy="REFUSE", check=gate.check)
            if names != dict(record.intent.allocation_names):
                raise refused("GLB_ALLOCATION_PLAN_CHANGED_DURING_PREVIEW")
            retained = RuntimeStage(connection, self._generation, root, operations, gate, bpy,
                protected_ids, protected, roles, role_hash, scene, view)
            self._records[record.intent.stage_id] = retained
            gate.check()
            return {"preview_id": record.intent.preview_id, "stage_id": record.intent.stage_id,
                "expected_fingerprint": record.intent.fingerprint,
                "required_accepted_losses": list(record.intent.plan.required_accepted_losses),
                "summary": record.intent.plan.summary(), "collection_name": record.intent.collection_name,
                "allocation_names": [list(item) for item in record.intent.allocation_names],
                "overwrite_policy": "REFUSE", "units_policy": "SOURCE_METRES_REQUIRES_SCENE_SCALE_LENGTH_1",
                "native_allocation_started": False, "destination_linked": False,
                "protected_mesh_read_effects": view.read_effects(),
                "public_import_qualified": False, "project_saved": False}
        finally:
            gate.unbind()

    @staticmethod
    def _names(operations, names, gate):
        b = operations._binding
        families = {"collection": "collections", "mesh": "meshes", "material": "materials", "object": "objects"}
        for role, name in names.items():
            family = families.get(role.split(":")[0])
            if family is None:
                continue  # Stock duplicate embedded tree names are never owners.
            for item in operations._items(b.main, family, 4096):
                gate.check()
                if b.get(item, "name") == name:
                    raise refused("GLB_EXACT_ALLOCATION_NAME_COLLISION", allocation_started=False)

    def retained(self, stage_id):
        self.store.lookup(stage_id)
        if stage_id not in self._records:
            raise refused("GLB_RETAINED_NATIVE_BINDING_UNAVAILABLE")
        return self._records[stage_id]

    def by_preview(self, preview_id):
        if type(preview_id) is not str or preview_id not in self.store._previews:
            raise invalid_argument("An exact current stage preview is required.")
        stage_id = self.store._previews[preview_id]
        return stage_id, self.retained(stage_id)

    def check_retained(self, context, stage_id, *, source=False):
        row = self.retained(stage_id)
        self.check_context(context, row.connection, row.generation)
        record = self.store.lookup(stage_id)
        if record.intent.generation != self.store.generation or record.phase in {"UNKNOWN", "FAILED", "STALE"}:
            raise refused("GLB_STAGE_NOT_WRITABLE")
        if source:
            root = self._source_root()
            if root != row.root:
                raise refused("GLB_APPROVED_SOURCE_ROOT_CHANGED")
            record.intent.source.verify(root, row.gate.check)
            row.source_verified = True
        return row

    def owned_boundary(self, stage_id):
        """Fresh current-turn authority; never retain the old creator driver."""
        row = self.retained(stage_id)
        row.gate.check()
        context = row.gate.context
        phase = self.store.lookup(stage_id).phase
        required = PUBLISH if phase in {"CONSTRUCTED", "PUBLISHING", "PUBLISHED"} else WRITE
        context.require(*required)
        row.gate.check()
        self.check_retained(context, stage_id)
        if phase in {"PREPARED", "ALLOCATING"} and self._source_root() != row.root:
            raise refused("GLB_APPROVED_SOURCE_ROOT_CHANGED")
        self.protected_check(stage_id)
        row.gate.check()

    def protected_check(self, stage_id):
        from .tools import asset_import as protected_reader
        row = self.retained(stage_id)
        row.gate.check()
        row.roles.check_after_read()
        if digest(row.roles.authored()) != row.roles_sha256:
            raise refused("GLB_PROTECTED_CHECKPOINT_SETTINGS_CHANGED")
        ignored: frozenset[int] = frozenset()
        if self.store.lookup(stage_id).publication_observed and row.controller is not None:
            stage = row.controller._stages[stage_id]
            ignored = frozenset({stage.references["collection"].pointer})
        current = row.protected_view.observe(row.protected_ids, row.gate.check, ignored_collections=ignored)
        if protected_reader._hash(current) != protected_reader._hash(row.protected):
            raise refused("GLB_PROTECTED_EXISTING_STATE_CHANGED")
        row.gate.check()

    def inspect(self, context, stage_id):
        # Inspect can cross connections, but it never dereferences native refs.
        self._entry(context, "asset.glb_stage_inspect", (Permission.INSPECT_SCENE,))
        row = self.retained(stage_id)
        record = self.store.lookup(stage_id)
        job = row.job
        if (job is not None and job.state in {"FAILED", "CANCELLED", "TIMED_OUT"}
                and record.phase not in {"UNKNOWN", "STALE", "FAILED"}):
            if record.possible_mutation:
                self.store.mark_unknown(stage_id, "RUNTIME_JOB_STOPPED")
            else:
                self.store.fail(stage_id, "RUNTIME_JOB_STOPPED", outcome_unknown=False)
        report = row.operations.report()  # Pure cached fields, never RNA.
        return {**self.store.inspect(stage_id), "job_id": row.job_id,
                "native_evidence": {"native_entries": report["native_entries"],
                    "native_access_counts": report["native_access_counts"],
                    "protected_mesh_read_effects": row.protected_view.read_effects(),
                    "mesh_return_receipts": report["mesh_return_receipts"],
                    "native_storage_effects": report["native_storage_effects"],
                    "publication_physical_effects": report["publication_physical_effects"],
                    "pending_returns": report["pending_returns"],
                    "constructor_defaults": report["constructor_defaults"],
                    "owned_rows": ({} if row.controller is None or stage_id not in row.controller._stages else
                                   plain(row.controller._stages[stage_id].expected)),
                    "owned_reference_roles": ([] if row.controller is None else
                        sorted(row.controller._stages[stage_id].references) if stage_id in row.controller._stages else []),
                    "footprint_complete": self.store.lookup(stage_id).phase in {"CONSTRUCTED", "PUBLISHED"}},
                "phase_history": plain(row.phase_history),
                "public_import_qualified": False, "native_cleanup_performed": False}

    def publication_witness(self, stage_id, destination_scene_name):
        row = self.retained(stage_id)
        row.gate.check()
        b, scene = row.operations._binding, row.context_scene
        if (b.get(b.context, "scene") is not scene or type(destination_scene_name) is not str
                or b.get(scene, "name") != destination_scene_name):
            raise refused("GLB_EXPLICIT_CURRENT_DESTINATION_SCENE_REQUIRED")
        units = b.get(scene, "unit_settings")
        if b.get(units, "scale_length") != 1.:
            raise refused("GLB_DESTINATION_METRE_UNITS_CHANGED")
        root = b.get(scene, "collection")
        children = row.operations._items(root, "children", 4096)
        witness = {"scene": list(row.operations._identity(scene)), "scene_name": destination_scene_name,
                   "root": list(row.operations._identity(root)),
                   "children": sorted([*row.operations._identity(child), b.get(child, "name")] for child in children),
                   "context": row.operations.environment(row.controller._values(row.controller._stages[stage_id]))}
        row.gate.check()
        row.publication = witness
        return digest(witness)

    def publish_preview(self, context, params):
        self._entry(context, "asset.glb_stage_publish_preview", (Permission.INSPECT_SCENE,))
        stage_id = params.get("stage_id")
        row = self.retained(stage_id)
        with row.gate.scope(context):
            self.check_retained(context, stage_id)
            if self.store.lookup(stage_id).phase != "CONSTRUCTED" or row.controller is None:
                raise refused("GLB_CONSTRUCTED_STAGE_REQUIRED_FOR_PUBLICATION")
            # This readonly preview reads only Scene/ID edges. It NEVER invokes
            # the owned Mesh attribute reader; full fresh write-authority CAS
            # belongs to publish_start, before the sole native edge write.
            destination = params.get("destination_scene_name")
            witness = self.publication_witness(stage_id, destination)
            intent = self.store.prepare_publication(stage_id, destination, witness,
                overwrite_policy=params.get("overwrite_policy", "REFUSE"))
            return {"stage_id": stage_id, "publish_preview_id": intent.preview_id,
                "expected_fingerprint": intent.fingerprint, "destination_scene_name": destination,
                "constructed_prefix_sha256": intent.constructed_prefix,
                "overwrite_policy": "REFUSE", "proposed_scene_root_edges_added": 1,
                "owned_mesh_reinspection_performed": False, "native_ownership_verified": False,
                "publication_observed": False, "public_import_qualified": False, "project_saved": False}

    def verify_publication_edge(self, stage_id):
        row = self.retained(stage_id)
        before = row.publication
        if type(before) is not dict:
            raise refused("GLB_PUBLICATION_EDGE_WITNESS_REQUIRED")
        # Freeze the old exact witness before computing a new measurement.
        prior = plain(before)
        self.publication_witness(stage_id, prior["scene_name"])
        after = row.publication
        stage = row.controller._stages[stage_id]
        ref = stage.references["collection"]
        expected = {**prior, "children": sorted([*prior["children"],
                     [ref.uid, ref.pointer, ref.name]])}
        if digest(after) != digest(expected):
            raise refused("GLB_PUBLICATION_SCENE_EDGE_DELTA_CHANGED")
        row.gate.check()

    def attach_job(self, stage_id, result):
        row = self.retained(stage_id)
        job = self.jobs.active
        if job is None or job.job_id != result.get("job_id"):
            raise refused("GLB_CANONICAL_ACCEPTED_JOB_MISSING")
        row.job, row.job_id = job, job.job_id
        return {**result, "stage_id": stage_id, "public_import_qualified": False}


class _ProtectedView:
    """Guard each primitive access made by the existing bounded observer.

    This read adapter exposes no constructors, setters, updates or data paths.
    It never wraps new-owned Meshes into the protected set. Each borrowed
    collection/array wrapper lives only for its current bounded observation.
    This closes stop granularity; it is not a hidden-state/passivity verdict.
    """

    def __init__(self, operations):
        from types import SimpleNamespace

        if _PROTECTED_DEPENDENCY_GUARD_ORIGIN.__code__ is not _PROTECTED_DEPENDENCY_GUARD_CODE:
            raise refused("GLB_PROTECTED_DEPENDENCY_ORIGIN_CHANGED")
        _PROTECTED_DEPENDENCY_GUARD_ORIGIN()
        self.operations, self.binding = operations, operations._binding
        self.mesh_observer = _PROTECTED_MESH_OBSERVER_ORIGIN(self.binding)
        self.native_ids = {}
        self._meshes, self._groups = {}, {}
        self._observing = False
        self.bpy = SimpleNamespace(data=self.wrap(self.binding.main),
                                   context=self.wrap(self.binding.context), types=self.binding.types)

    def observe(self, ids, check, *, ignored_collections=frozenset()):
        """One provider-free bounded pass; discard all detached arrays at exit."""
        if _PROTECTED_DEPENDENCY_GUARD_ORIGIN.__code__ is not _PROTECTED_DEPENDENCY_GUARD_CODE:
            raise refused("GLB_PROTECTED_DEPENDENCY_ORIGIN_CHANGED")
        _PROTECTED_DEPENDENCY_GUARD_ORIGIN()
        from .tools import asset_import as reader
        if self._observing:
            raise refused("GLB_PROTECTED_OBSERVATION_REENTRANCY")
        self._observing = True
        self._meshes, self._groups = {}, {}
        try:
            # Header/storage admission precedes any Mesh geometry/groups/data
            # access, including unused protected Main meshes. This never uses
            # native legacy UV .data; the legacy-shaped views below are pure.
            mesh_refs = tuple(self.unwrap(mesh) for mesh in ids.get("meshes", {}).values())
            headers = tuple(self.mesh_observer.capture_headers(mesh) for mesh in mesh_refs)
            for header in headers:
                _PROTECTED_HEADER_VALIDATOR_ORIGIN(header)  # Reject-only; confers no authority.
            for mesh in mesh_refs:
                self.mesh_snapshot(mesh)  # Independently reacquires actual headers.
            for obj in ids.get("objects", {}).values():
                raw = self.unwrap(obj)
                if self.binding.get(raw, "type") == "MESH":
                    self.object_groups(raw)
            result = reader._guard(self.bpy, ids, check, ignored_collections=ignored_collections)
            result["protected_mesh_authored_sha256"] = {
                str(row["identity"]["uid"]): row["authored_sha256"] for row in self._meshes.values()}
            result["protected_object_groups"] = {
                str(row["object_identity"]["uid"]): row for row in self._groups.values()}
            check()
            return result
        finally:
            # Pure releases only. Never improve a stopped report with another
            # native read or permission provider; the observer journal is cached.
            self._meshes.clear()
            self._groups.clear()
            self._observing = False

    def mesh_snapshot(self, mesh):
        if not self._observing:
            raise refused("GLB_PROTECTED_MESH_OUTSIDE_CURRENT_OBSERVATION")
        pointer = self.binding._pointer(mesh)
        if pointer not in self._meshes:
            self._meshes[pointer] = self.mesh_observer.capture_mesh(mesh)
        return self._meshes[pointer]

    def object_groups(self, obj):
        if not self._observing:
            raise refused("GLB_PROTECTED_GROUPS_OUTSIDE_CURRENT_OBSERVATION")
        pointer = self.binding._pointer(obj)
        if pointer not in self._groups:
            mesh = self.binding.get(obj, "data")
            self._groups[pointer] = self.mesh_observer.capture_object_groups(obj, self.mesh_snapshot(mesh))
        return self._groups[pointer]

    def mesh_field(self, mesh, name):
        if _PROTECTED_DEPENDENCY_GUARD_ORIGIN.__code__ is not _PROTECTED_DEPENDENCY_GUARD_CODE:
            raise refused("GLB_PROTECTED_DEPENDENCY_ORIGIN_CHANGED")
        _PROTECTED_DEPENDENCY_GUARD_ORIGIN()
        row = self.mesh_snapshot(mesh)
        if name == "uv_layers":
            layers = []
            for layer in row["uv_layers"]:
                data = _DetachedCollection(_plain_rows([
                    {"uv": [_bits_float(value) for value in corner["uv"]], "pin_uv": corner["pin_uv"]}
                    for corner in layer["data"]]))
                layers.extend(_plain_rows([{**{key: layer[key] for key in
                    ("name", "active", "active_render", "active_clone")}, "data": data}]))
            return _DetachedCollection(layers, active_index=row["uv_roles"]["active_index"])
        rows = []
        for item in row["geometry"][name]:
            value = dict(item)
            if name == "vertices":
                value["co"] = tuple(_bits_float(bit) for bit in value["co"])
                value["groups"] = _DetachedCollection(_plain_rows([
                    {"group": index, "weight": _bits_float(weight)} for index, weight in value["groups"]]))
            rows.append(value)
        return _DetachedCollection(_plain_rows(rows))

    def read_effects(self):
        return self.mesh_observer.report()  # Cached pure journal, including stops.

    def wrap(self, value):
        b = self.binding
        if value is None or type(value) in {bool, int, float, str, bytes}:
            return value
        if type(value) in {tuple, list}:
            return tuple(self.wrap(item) for item in value)
        cls = type(value)
        if b.base in cls.__mro__:
            if b.classes["ID"] in cls.__mro__:
                key = (cls, b._pointer(value))
                if key not in self.native_ids:
                    if len(self.native_ids) >= 4096:
                        raise refused("GLB_PROTECTED_ID_VIEW_CAPACITY")
                    self.native_ids[key] = _ProtectedValue(self, value)
                return self.native_ids[key]
            return _ProtectedValue(self, value)
        if cls in (b.collection_type, b.array_type, b.matrix_type, *b.vector_types):
            return _ProtectedValue(self, value)
        raise refused("GLB_PROTECTED_NATIVE_VIEW_TYPE_UNQUALIFIED")

    @staticmethod
    def unwrap(value):
        return value._value if type(value) is _ProtectedValue else value

    def field(self, value, name):
        if _PROTECTED_DEPENDENCY_GUARD_ORIGIN.__code__ is not _PROTECTED_DEPENDENCY_GUARD_CODE:
            raise refused("GLB_PROTECTED_DEPENDENCY_ORIGIN_CHANGED")
        _PROTECTED_DEPENDENCY_GUARD_ORIGIN()
        b = self.binding
        if type(value) is b.classes["Mesh"] and name in {"vertices", "edges", "loops", "polygons", "uv_layers"}:
            return self.mesh_field(value, name)
        if type(value) is b.classes["Object"] and name == "vertex_groups":
            return _DetachedCollection(_plain_rows(self.object_groups(value)["groups"]))
        if type(value) is b.classes["MeshUVLoopLayer"] and name == "data":
            # Native legacy UV access can create optional storage. Pure
            # detached compatibility views use generic-attribute values instead;
            # the existing native getter remains outside this reader contract.
            raise refused("GLB_PROTECTED_NATIVE_LEGACY_UV_DATA_FORBIDDEN", allocation_started=False)
        if name == "as_pointer":
            return lambda: b._pointer(value)
        if name == "bl_rna" and b.base in type(value).__mro__:
            return self.wrap(b._rna(type(value)))
        if value is b.context and name == "selected_objects":
            return self.wrap(b.selected())
        if type(value) is b.classes["Object"] and name == "users_collection":
            # Exact source-reviewed stock helper, without invoking its Python
            # property or retaining a borrowed collection view across turns.
            candidates = list(self.operations._items(b.main, "collections", 4096))
            candidates.extend(b.get(scene, "collection") for scene in self.operations._items(b.main, "scenes", 32))
            target, result = b._pointer(value), []
            for collection in candidates:
                if any(b._pointer(obj) == target for obj in self.operations._items(collection, "objects", 4096)):
                    result.append(self.wrap(collection))
            return tuple(result)
        if type(value) is b.collection_type and name == "get":
            slot = vars(b.collection_type).get("get")
            from types import MethodDescriptorType
            if type(slot) is not MethodDescriptorType or slot.__objclass__ is not b.collection_type:
                raise refused("GLB_PROTECTED_COLLECTION_LOOKUP_SLOT_CHANGED")
            return lambda key, default=None: self.wrap(b._access("protected_collection_get", slot, value, key, default))
        if b.base not in type(value).__mro__:
            raise AttributeError(name)
        # Missing optional properties are reported without invoking a guessed
        # Python attribute. All present fields pass the stock slot/schema gate.
        prop = b._access("protected_property_lookup", b._raw(b._rna(type(value)), "properties").get, name)
        if prop is None:
            raise AttributeError(name)
        return self.wrap(b.get(value, name))


def _bits_float(value):
    if type(value) is not str or len(value) != 8:
        raise refused("GLB_DETACHED_FLOAT32_COMPONENT_INVALID")
    try:
        return struct.unpack("<f", bytes.fromhex(value))[0]
    except (ValueError, struct.error) as cause:
        raise refused("GLB_DETACHED_FLOAT32_COMPONENT_INVALID") from cause


def _plain_rows(rows):
    from types import SimpleNamespace
    return tuple(SimpleNamespace(**row) for row in rows)


def _check_protected_dependencies():
    """Pure origin checks before a new protected-reader dependency is called."""
    if (_check_protected_dependencies is not _PROTECTED_DEPENDENCY_GUARD_ORIGIN
            or _check_protected_dependencies.__code__ is not _PROTECTED_DEPENDENCY_GUARD_CODE
            or _protected_mesh is not _PROTECTED_MESH_MODULE_ORIGIN
            or type(_protected_mesh) is not _PROTECTED_MESH_MODULE_TYPE):
        raise refused("GLB_PROTECTED_DEPENDENCY_ORIGIN_CHANGED")
    namespace = vars(_protected_mesh)
    if (namespace.get("ProtectedMeshObserver") is not _PROTECTED_MESH_OBSERVER_ORIGIN
            or any(namespace.get(name) is not function or function.__code__ is not code
                   for name, function, code in _PROTECTED_MODULE_FUNCTION_ORIGINS)
            or len(vars(_PROTECTED_MESH_OBSERVER_ORIGIN)) != len(_PROTECTED_OBSERVER_NAMESPACE)
            or any(vars(_PROTECTED_MESH_OBSERVER_ORIGIN).get(name) is not value
                   for name, value in _PROTECTED_OBSERVER_NAMESPACE)
            or any(function.__code__ is not code for function, code in _PROTECTED_OBSERVER_METHOD_CODES)
            or any(globals().get(name) is not function or function.__code__ is not code
                   for name, function, code in _DETACHED_FUNCTION_ORIGINS)):
        raise refused("GLB_PROTECTED_DEPENDENCY_ORIGIN_CHANGED")


class _DetachedCollection:
    """Pure detached compatibility shape, never an RNA/Attribute wrapper."""
    __slots__ = ("active_index", "values")

    def __init__(self, values, *, active_index=0):
        self.values, self.active_index = tuple(values), active_index

    def __len__(self):
        return len(self.values)

    def __iter__(self):
        return iter(self.values)

    def __getitem__(self, key):
        return self.values[key]


class _ProtectedValue:
    __slots__ = ("_value", "_view")

    def __init__(self, view, value):
        self._view, self._value = view, value

    def __getattr__(self, name):
        return self._view.field(self._value, name)

    def __len__(self):
        return self._view.binding.length(self._value)

    def __iter__(self):
        b = self._view.binding
        iterator = b._access("protected_iter", iter, self._value)
        while True:
            try:
                value = b._access("protected_next", next, iterator)
            except StopIteration:
                return
            yield self._view.wrap(value)

    def __getitem__(self, key):
        value = self._view.binding._access("protected_getitem", operator.getitem, self._value, key)
        return self._view.wrap(value)

    def __bool__(self):
        return self._view.binding._access("protected_bool", bool, self._value)


class GLBCheckpointRoles:
    """Exact existing native undo ParticleEdit weak-role effects, gated per read.

    Mirrors the reviewed Scene checkpoint role contract for a plain active
    Empty. No RNA getter that calls PE_get_current is used. The scene self-use
    count and readonly object pointer are read through qualified native entries.
    Only canonical native-push completion changes the expected role phase.
    """

    def __init__(self, operations, scene):
        self.operations, self.binding, self.scene = operations, operations._binding, scene
        self.owners, self.expected, self.active = self._read()
        if self.active is None or self.expected not in ((0, None), (1, self.active)):
            raise refused("GLB_CHECKPOINT_WEAK_ROLE_INITIAL_STATE_UNQUALIFIED")

    def _read(self):
        b, scene = self.binding, self.scene
        if b.get(b.context, "scene") is not scene:
            raise refused("GLB_CHECKPOINT_SCENE_CHANGED")
        settings = b.get(scene, "tool_settings")
        particle = b.get(settings, "particle_edit")
        props = b._raw(b._rna(type(particle)), "properties")
        if b._access("particle_scene_descriptor_lookup", props.get, "scene") is not None:
            raise refused("GLB_EXPOSED_PARTICLE_SCENE_ROLE_UNQUALIFIED")
        active = b.get(b.get(b.get(b.context, "view_layer"), "objects"), "active")
        if active is None or b.get(active, "type") != "EMPTY":
            raise refused("GLB_CHECKPOINT_REQUIRES_PLAIN_ACTIVE_EMPTY")
        for name in ("modifiers", "constraints", "particle_systems"):
            if b.length(b.get(active, name)):
                raise refused("GLB_CHECKPOINT_ACTIVE_EMPTY_HAS_DEPENDENCIES")
        if b.get(active, "soft_body") is not None or b.get(active, "animation_data") is not None:
            raise refused("GLB_CHECKPOINT_ACTIVE_EMPTY_HAS_EVALUATION_DEPENDENCIES")
        pointer = b._pointer(active)
        original, particle_object = b.get(scene, "original"), b.get(particle, "object")
        count = b._access("ID.user_of_id", b.callable(scene, "ID", "user_of_id"), scene)
        if type(count) is not int or count not in (0, 1):
            raise refused("GLB_CHECKPOINT_SCENE_SELF_USE_UNQUALIFIED")
        owners = (b._pointer(scene), b._pointer(settings), b._pointer(particle),
                  None if original is None else b._pointer(original), pointer)
        return owners, (count, None if particle_object is None else b._pointer(particle_object)), pointer

    def check_after_read(self):
        owners, expected, active = self._read()
        if owners != self.owners or expected != self.expected or active != self.active:
            raise refused("GLB_CHECKPOINT_WEAK_ROLE_OR_OWNER_CHANGED")

    def authored(self):
        b = self.binding
        self.check_after_read()
        particle = b.get(b.get(self.scene, "tool_settings"), "particle_edit")
        props = b.items(b._raw(b._rna(type(particle)), "properties"))
        if len(props) > 512:
            raise refused("GLB_CHECKPOINT_SETTINGS_DESCRIPTOR_BUDGET")
        rows = []
        for prop in props:
            readonly = b._raw(prop, "is_readonly")
            runtime = b._raw(prop, "is_runtime")
            if type(readonly) is not bool or type(runtime) is not bool:
                raise refused("GLB_CHECKPOINT_SETTINGS_FLAGS_UNQUALIFIED")
            if readonly:
                continue  # In particular do not invoke is_hair/is_editable.
            if runtime or b._raw(prop, "is_registered"):
                raise refused("GLB_CHECKPOINT_RUNTIME_SETTINGS_UNQUALIFIED")
            name, kind = b._raw(prop, "identifier"), b._raw(prop, "type")
            if kind not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER"}:
                raise refused("GLB_CHECKPOINT_WRITABLE_SETTINGS_KIND_UNQUALIFIED")
            value = b.get(particle, name)
            if kind == "POINTER":
                value = None if value is None else b._pointer(value)
            elif type(value) not in {bool, int, float, str}:
                value = b.copy(value)
            rows.append([name, kind, value])
        return [list(self.owners), rows]

    def after_native_push(self):
        from .checkpoint_completion import claim_native_push_delegate
        claim_native_push_delegate(self)
        self.expected = 1, self.active


from types import FunctionType as _FunctionType  # noqa: E402

_PROTECTED_MESH_MODULE_ORIGIN = _protected_mesh
_PROTECTED_MESH_MODULE_TYPE = type(_protected_mesh)
_PROTECTED_MESH_OBSERVER_ORIGIN = _protected_mesh.ProtectedMeshObserver
_PROTECTED_HEADER_VALIDATOR_ORIGIN = _protected_mesh.validate_header_profile
_PROTECTED_OBSERVER_NAMESPACE = tuple(vars(_PROTECTED_MESH_OBSERVER_ORIGIN).items())
_PROTECTED_OBSERVER_METHOD_CODES = tuple((function, function.__code__)
    for _name, function in _PROTECTED_OBSERVER_NAMESPACE if type(function) is _FunctionType)
_PROTECTED_MODULE_FUNCTION_ORIGINS = tuple((name, function, function.__code__)
    for name, function in vars(_protected_mesh).items() if type(function) is _FunctionType)
_DETACHED_FUNCTION_ORIGINS = tuple((name, function, function.__code__)
    for name, function in (("_bits_float", _bits_float), ("_plain_rows", _plain_rows)))
_PROTECTED_DEPENDENCY_GUARD_ORIGIN = _check_protected_dependencies
_PROTECTED_DEPENDENCY_GUARD_CODE = _check_protected_dependencies.__code__

_SERVICE_METHOD_ORIGINS = tuple((cls, name, fn, fn.__code__)
    for cls in (GLBStageService, _ProtectedView, _ProtectedValue, _DetachedCollection, GLBCheckpointRoles)
    for name, fn in vars(cls).items() if type(fn) is _FunctionType)


def _exact_instance_keys(value, expected):
    namespace = vars(value)
    keys = tuple(namespace)
    return (all(type(name) is str for name in keys)
            and len(keys) == len(expected) and all(name in expected for name in keys))


from .executor import MainThreadExecutor as _Executor  # noqa: E402
from .permissions import PermissionManager as _PermissionManager  # noqa: E402
from .scene_job_authority import SceneJobPermissions as _SceneJobPermissions  # noqa: E402
from .state import BridgeState as _BridgeState  # noqa: E402
from .tool_registry import ToolContext as _ToolContext  # noqa: E402

_EXECUTOR_CONTEXT_PROPERTY: Any = vars(_Executor)["context"]
_EXECUTOR_CONTEXT_GETTER: Any = _EXECUTOR_CONTEXT_PROPERTY.fget
_EXECUTOR_CONTEXT_GETTER_CODE = _EXECUTOR_CONTEXT_GETTER.__code__
_STATE_METHOD_NAMES = frozenset(name for name, value in vars(_BridgeState).items() if type(value) is _FunctionType)
_AUTHORITY_CLASSES = (_PermissionManager, _SceneJobPermissions, _ToolContext, _BridgeState)
_AUTHORITY_CLASS_NAMESPACES = tuple((cls, tuple(vars(cls).items())) for cls in _AUTHORITY_CLASSES)
_AUTHORITY_METHOD_ORIGINS = tuple(
    (cls, name, raw, raw.__func__ if type(raw) is staticmethod else raw,
     (raw.__func__ if type(raw) is staticmethod else raw).__code__)
    for cls in _AUTHORITY_CLASSES for name, raw in vars(cls).items()
    if type(raw) is _FunctionType or (type(raw) is staticmethod and type(raw.__func__) is _FunctionType))


def checked_executor_context(executor):
    """Trusted wiring helper: validate before resolving a dynamic property."""
    if type(executor) is not _Executor:
        raise refused("GLB_CANONICAL_EXECUTOR_REQUIRED")
    service = executor.glb_stage
    if type(service) is not GLBStageService:
        raise refused("GLB_CANONICAL_SERVICE_REQUIRED")
    GLBStageService.check_context_factory(service, executor)
    return _EXECUTOR_CONTEXT_PROPERTY.fget(executor)
