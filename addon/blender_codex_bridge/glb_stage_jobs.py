"""GLB adapters for canonical SceneJobs, with no scheduler or cleanup of their own."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from .glb_stage_profile import refused
from .glb_stage_runtime import PUBLISH, WRITE
from .permissions import Permission


@dataclass(slots=True)
class _Counts:
    entered: int = 0
    returned: int = 0


class RuntimeNativeGate:
    """Pure stop checks at native boundaries; never a wire-supplied capability.

    No provider or native content read occurs in check(). Providers and the
    complete content CAS run at each phase first. Transient canonical context
    is released at the end of every admission/turn, including exceptions.
    Native read attempts are counted by bounded label cells; native writes have
    separate individual monotonic attempt cells in NativeOperations.
    """

    def __init__(self, service, connection, generation):
        from .glb_stage_runtime import GLBStageService
        if type(service) is not GLBStageService:
            raise refused("GLB_CANONICAL_SERVICE_REQUIRED")
        self.service, self.connection, self.generation = service, connection, generation
        self.context = None
        self.revoked = False
        self._counts: dict[str, _Counts] = {}

    def revoke(self):
        self.revoked = True
        self.context = None

    def bind(self, context):
        if self.context is not None and self.context is not context:
            raise refused("GLB_NATIVE_TURN_REENTRANCY")
        self.context = context
        self.check()

    def unbind(self):
        self.context = None

    @contextmanager
    def scope(self, context):
        previous = self.context
        self.bind(context)
        try:
            yield
        finally:
            self.context = previous

    def check(self):
        if type(self) is not RuntimeNativeGate or any(
                vars(RuntimeNativeGate).get(name) is not fn or fn.__code__ is not code
                for name, fn, code in _GATE_METHOD_ORIGINS):
            raise refused("GLB_CANONICAL_NATIVE_GATE_CODE_CHANGED")
        if self.revoked or self.context is None:
            raise refused("GLB_NATIVE_GATE_NOT_IN_CURRENT_TURN")
        self.service.check_context(self.context, self.connection, self.generation)

    def enter(self, label):
        self.check()
        if type(label) is not str or not 0 < len(label) <= 128:
            raise refused("GLB_NATIVE_ACCESS_LABEL_INVALID")
        cell = self._counts.get(label)
        if cell is None:
            if len(self._counts) >= 1024:
                raise refused("GLB_NATIVE_ACCESS_LABEL_CAPACITY")
            cell = self._counts[label] = _Counts()
        if cell.entered >= 2**63-1:
            raise refused("GLB_NATIVE_ACCESS_COUNTER_CAPACITY")
        cell.entered += 1
        return cell

    def returned(self, cell):
        # Pure first-return fact before the stop check. Exceptions retain an
        # attempted-without-return count; no false successful return is added.
        cell.returned += 1

    def snapshot(self):
        return {label: {"entered": cell.entered, "returned": cell.returned}
                for label, cell in sorted(self._counts.items())}


class GLBStageDriver:
    kind = "asset.glb_stage_create"
    label = "Construct unlinked new-owned GLB stage"
    required_permissions: tuple[Permission, ...] = WRITE

    def __init__(self, context, params, *, publication=False):
        service = context.glb_stage
        self.service, self.params = service, dict(params)
        self.publication = publication
        if publication:
            self.kind, self.label, self.required_permissions = (
                "asset.glb_stage_publish", "Publish one new-owned GLB collection", PUBLISH)
            self.stage_id = params.get("stage_id")
            self.retained = service.retained(self.stage_id)
        else:
            self.stage_id, self.retained = service.by_preview(params.get("preview_id"))
        self.gate = self.retained.gate
        self.steps = None
        self.index, self.done, self.result = 0, False, None
        self.phase = "publish_collection" if publication else "construct_begin"
        self._context = None
        self._factory_preflight(context)

    def _factory_preflight(self, context):
        # The canonical factory runs before its generic provider callback.
        # Perform our declared grants before any source/native read here.
        context.glb_method = "asset.glb_stage_publish_start" if self.publication else "asset.glb_stage_create_start"
        self.service._entry(context, context.glb_method, self.required_permissions)
        with self.gate.scope(context):
            self.service.check_retained(context, self.stage_id, source=not self.publication)
            record = self.service.store.lookup(self.stage_id)
            if self.publication:
                intent = record.publication_intent
                if (intent is None or intent.preview_id != self.params.get("publish_preview_id")
                        or intent.fingerprint != self.params.get("expected_fingerprint")
                        or self.params.get("overwrite_policy", "REFUSE") != "REFUSE"
                        or self.service.publication_witness(self.stage_id, intent.destination_scene_name) != intent.destination_fingerprint):
                    raise refused("GLB_PUBLICATION_PREVIEW_CHANGED")
                self.retained.controller.verify_retained(self.stage_id)
            else:
                from .asset_glb_import_plan import require_loss_acceptance
                if record.phase != "PREPARED" or record.intent.fingerprint != self.params.get("expected_fingerprint"):
                    raise refused("GLB_STAGE_PREVIEW_CHANGED")
                accepted_losses: Any = self.params.get("accepted_losses")
                require_loss_acceptance(record.intent.plan, accepted_losses)
                self.service._names(self.retained.operations, dict(record.intent.allocation_names), self.gate)
            self.service.protected_check(self.stage_id)
            self.gate.check()

    def check_after_read(self, context):
        with self.gate.scope(context):
            self.service.check_retained(context, self.stage_id)
            self.service.protected_check(self.stage_id)
            controller = self.retained.controller
            if controller is not None:
                stage = controller._stages.get(self.stage_id)
                if stage is not None and not stage.failed:
                    controller._verify(stage)
            self.gate.check()

    def native_push_delegates(self):
        return (self.retained.roles,)

    def after_native_push(self):
        # A pure, canonical checkpoint completion capability; no live baseline
        # is adopted. check_after_read must immediately prove exact old content.
        self.retained.roles.after_native_push()

    def _boundary(self):
        context = self._context
        if context is None:
            raise refused("GLB_NO_CURRENT_SCENE_TURN")
        self.gate.check()
        context.require(*self.required_permissions)
        self.gate.check()
        self.service.check_retained(context, self.stage_id)
        if not self.publication and self.service._source_root() != self.retained.root:
            raise refused("GLB_APPROVED_SOURCE_ROOT_CHANGED")
        self.service.protected_check(self.stage_id)
        self.gate.check()

    def advance(self, context):
        self._context = context
        try:
            with self.gate.scope(context):
                self._boundary()
                if self.publication:
                    self._publish()
                else:
                    self._construct()
                self.gate.check()
                self.index += 1
                return {"phase": self.phase, "completed": self.index,
                        "total": self.index if self.done else self.index+1}
        finally:
            # No context, turn token, provider or borrowed native view crosses
            # a timer yield. Only true returned ID refs/immutable plans persist.
            self._context = None

    def _construct(self):
        if self.steps is None:
            from .glb_stage_driver import PrivateGLBController

            service, stage_id = self.service, self.stage_id

            def boundary():
                service.owned_boundary(stage_id)

            controller = PrivateGLBController(self.service.store, self.retained.operations, boundary)
            self.retained.controller = controller
            self.steps = controller.construct_steps(self.params.get("preview_id"),
                self.params.get("expected_fingerprint"), self.params.get("accepted_losses"))
        try:
            completed = next(self.steps)
        except StopIteration:
            self.done, self.phase = True, "constructed"
            record = self.service.store.lookup(self.stage_id)
            self.result = {"stage_id": self.stage_id, "collection_name": record.intent.collection_name,
                "phase": record.phase, "source_sha256": record.intent.source.sha256,
                "required_accepted_losses": list(record.intent.plan.required_accepted_losses),
                "mathematical_world_oracle": "AUTHORED_PARENT_CHAIN_AND_MATRIX_BASIS",
                "evaluated_world_verified": False, "publication_observed": False,
                "public_import_qualified": False, "project_saved": False, "native_cleanup_performed": False}
        else:
            self.phase = completed["operation"].lower()+"_"+completed["role"].replace(":", "_")
            self.retained.phase_history.append({"index": self.index, **completed})

    def _publish(self):
        intent = self.service.store.lookup(self.stage_id).publication_intent
        if intent is None:
            raise refused("GLB_PUBLICATION_INTENT_REQUIRED")
        if self.service.publication_witness(self.stage_id, intent.destination_scene_name) != intent.destination_fingerprint:
            raise refused("GLB_PUBLICATION_DESTINATION_CHANGED")
        self.retained.controller.verify_retained(self.stage_id)
        self.gate.check()
        self.service.store.begin_publication(self.stage_id, self.params.get("publish_preview_id"),
            self.params.get("expected_fingerprint"), overwrite_policy=self.params.get("overwrite_policy", "REFUSE"))
        prefix = self.retained.controller.publish(self.stage_id, self.retained.context_scene)
        self.service.verify_publication_edge(self.stage_id)
        self.service.store.finish_publication(self.stage_id, prefix)
        self.service.protected_check(self.stage_id)
        self.done, self.phase = True, "published"
        self.result = {"stage_id": self.stage_id, "phase": "PUBLISHED", "publication_observed": True,
            "collection_name": self.service.store.lookup(self.stage_id).intent.collection_name,
            "destination_scene_name": intent.destination_scene_name, "scene_root_edges_added": 1,
            "project_saved": False, "public_import_qualified": False, "native_cleanup_performed": False}
        self.retained.phase_history.append({"index": self.index, "operation": "PUBLISH_COLLECTION", "role": "collection"})


def create_driver(context, params):
    return GLBStageDriver(context, params)


def publish_driver(context, params):
    return GLBStageDriver(context, params, publication=True)


from types import FunctionType as _FunctionType  # noqa: E402

_GATE_METHOD_ORIGINS = tuple((name, fn, fn.__code__) for name, fn in vars(RuntimeNativeGate).items()
                             if type(fn) is _FunctionType)
