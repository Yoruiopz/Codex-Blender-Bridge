"""Retained authored admission for the bounded artist transform profile.

Unarmed ordinary transforms retain their existing broad behavior. Their guard
only preserves entry policy/lifetime; it makes no authored checkpoint claim.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from weakref import ref

from ..errors import invalid_argument
from ..task_plans import get_task_plans
from ..tool_registry import check_final_mutation
from ..utils import require_blender

_CAPTURES: dict[int, list[Any]] = {}


def _remember(admission: Admission) -> Admission:
    """Keep only weak factory receipts, independently of mutable context slots."""
    identity = id(admission.context)
    def discarded(_reference):
        remaining = [item for item in _CAPTURES.get(identity, ()) if item() is not None]
        if remaining:
            _CAPTURES[identity] = remaining
        else:
            _CAPTURES.pop(identity, None)
    _CAPTURES.setdefault(identity, []).append(ref(admission, discarded))
    return admission


class Admission:
    def __init__(self, context: Any, method: str, *, boundary: Any = None,
                 preview: Any = None, params: Any = None, parent: Any = None):
        from . import artist_loop
        self.context, self.method, self.boundary = context, method, boundary
        self._boundary_identity = boundary
        self._roles_view = None
        self._advance_roles = None
        self._role_delegate = None
        if boundary is not None:
            if parent is None:
                self._role_delegate = boundary.checkpoint_roles
                self._roles_view, self._advance_roles = boundary.checkpoint_roles.retained()
                boundary.checkpoint_roles = self._roles_view
            else:
                self._roles_view, self._advance_roles = parent._roles_view, parent._advance_roles
                self._role_delegate = parent._role_delegate
        self.store = get_task_plans(context.state)
        self.stamp = artist_loop.policy_stamp(context)
        self.preview, self.params, self.parent = preview, params, parent
        self._parent_identity = parent
        self.consumed = False
        self.binding = None
        self.preview_origin = None if preview is None else preview["checkpoint_roles"]
        self.revision = self.store.require_plan()["revision"] if preview is not None else None
        self.preview_values = None if preview is None else {
            name: deepcopy(preview[name]) for name in ("params", "profile", "reference_id", "policy_stamp", "plan_id", "step_association")}
        self.transform_spec = context.registry.get("transform.set") if preview is not None else None

    @property
    def roles(self) -> Any:
        return self._roles_view

    def bind_checkpoint(self, binding: Any) -> Any:
        if (self.binding is not None or binding.context is not self.context or binding.callback is not self
                or binding.method != self.method):
            raise invalid_argument("Artist checkpoint binding does not belong to its original factory guard.")
        self.binding = binding
        identity = id(self.context)
        def release() -> None:
            captures = _CAPTURES.get(identity)
            if captures is not None:
                captures[:] = [item for item in captures if item() is not self]
                if not captures:
                    _CAPTURES.pop(identity, None)
        return release

    def __call__(self) -> None:
        self.context.registry.prepare(self.method, self.context)
        self.check_after_read()

    def check_write_identity(self) -> None:
        from . import artist_loop
        context = self.context
        if current(context, strict=True) is not self:
            raise invalid_argument("Artist checkpoint proof belongs to a different factory guard.")
        if get_task_plans(context.state) is not self.store or artist_loop.policy_stamp(context) != self.stamp:
            raise invalid_argument("Artist checkpoint policy or runtime ownership changed; no new checkpoint write is authorized.")
        if (self.boundary is not self._boundary_identity
                or (self.boundary is not None and self.boundary.checkpoint_roles is not self._roles_view)):
            raise invalid_argument("The original artist boundary or role proof was replaced.")
        # The enclosing binding separately checks its exact identity after
        # this child proof. Both guards share the original owned Boundary.
        if (self.parent is not self._parent_identity
                or (self.parent is not None and (self.parent.boundary is not self.boundary or not self.parent.consumed))):
            raise invalid_argument("The nested transform lost its retained artist boundary.")
        if self.parent is not None:
            self.parent._check_preview_owner()
        self._check_preview_owner()

    def _check_preview_owner(self) -> None:
        context = self.context
        if self.preview is not None:
            from ..artist_step_evidence import check_apply
            if (self.store.require_plan()["revision"] != self.revision
                    or self.preview["checkpoint_roles"] is not self.preview_origin
                    or any(self.preview[name] != value for name, value in self.preview_values.items())
                    or context.registry.get("transform.set") is not self.transform_spec):
                raise invalid_argument("The retained artist preview changed before checkpoint or write.")
            check_apply(context, self.params["preview_id"], self.preview, self.params)
            identifier = self.params["preview_id"]
            if ((not self.consumed and self.store.previews.get(identifier) is not self.preview)
                    or (self.consumed and (identifier in self.store.previews
                        or (self.store.applying_preview is not None and self.store.applying_preview is not self.preview)))):
                raise invalid_argument("The retained artist preview lost its consumption ownership.")

    def check_after_read(self) -> None:
        from . import artist_loop
        context = self.context
        self.check_write_identity()
        if self.boundary is None:
            if artist_loop.needs_review(context):
                raise invalid_argument("An unarmed transform cannot adopt a newly enabled artist policy.")
        else:
            self.boundary.check_after_read(final=False)
        check_final_mutation(context, self.method)

    def after_native_push(self) -> None:
        from ..checkpoint_completion import claim_native_push_completion
        claim_native_push_completion(self.context, self.method, self)
        if self._advance_roles is not None:
            self._advance_roles()

    def native_push_delegates(self) -> tuple[Any, ...]:
        return () if self._role_delegate is None else (self._role_delegate,)


def current(context: Any, *, strict: bool = False) -> Admission | None:
    binding = getattr(context, "checkpoint_admission", None)
    captures = [item() for item in _CAPTURES.get(id(context), ()) if item() is not None]
    active = [guard for guard in captures if guard.context is context]
    if binding is None:
        if active:
            raise invalid_argument("The retained artist checkpoint binding was lost; recapture is forbidden.")
        return None
    guard = binding.callback
    if not isinstance(guard, Admission):
        if strict or active:
            raise invalid_argument("The retained artist checkpoint guard was replaced.")
        return None
    if (not any(guard is item for item in active)
            or getattr(binding.readonly_callback, "__self__", None) is not guard
            or getattr(binding.readonly_callback, "__func__", None) is not Admission.check_after_read
            or getattr(binding.native_push_callback, "__self__", None) is not guard
            or getattr(binding.native_push_callback, "__func__", None) is not Admission.after_native_push
            or guard.context is not context or guard.method != binding.method
            or (guard.binding is not None and guard.binding is not binding)):
        raise invalid_argument("The original artist checkpoint guard or its proof hooks changed.")
    if guard.binding is not binding:
        raise invalid_argument("The artist checkpoint guard has no canonical factory binding receipt.")
    binding.check_identity(binding.method)
    return guard


def cached(context: Any, method: str, obj: Any) -> Any:
    from ._animation_scope import action_token
    admission = current(context, strict=True)
    if admission is None or admission.boundary is None:
        return None
    if (admission.method != method or admission.boundary.method != method
            or action_token(admission.boundary.obj) != action_token(obj)):
        raise invalid_argument("Transform commit does not match its retained artist boundary.")
    return admission.boundary


def consumed(context: Any, preview: Mapping[str, Any]) -> None:
    admission = current(context, strict=True)
    if admission is not None:
        if admission.method != "task.plan.apply_preview" or admission.preview is not preview or admission.consumed:
            raise invalid_argument("Preview consumption does not belong to this retained artist call.")
        admission.consumed = True


def factory(method: str, context: Any, params: Mapping[str, Any]) -> Admission:
    from . import artist_loop
    from ._object_rna_mutation import Boundary
    enclosing = current(context)
    if enclosing is not None and enclosing.boundary is not None:
        preview = enclosing.preview
        if (enclosing.method != "task.plan.apply_preview" or method != "transform.set"
                or preview is None or not enclosing.consumed or enclosing.store.applying_preview is not preview
                or dict(params) != enclosing.preview_values["params"]):
            raise invalid_argument("Nested artist transform is not the exact retained preview application.")
        enclosing.check_after_read()
        return _remember(Admission(context, method, boundary=enclosing.boundary, parent=enclosing))
    if method == "task.plan.apply_preview":
        store = get_task_plans(context.state)
        identifier = params.get("preview_id")
        preview = store.previews.get(identifier) if type(identifier) is str else None
        if preview is None:
            raise invalid_argument("Preview is missing, consumed or evicted; preview again.")
        boundary = artist_loop.preview_boundary(context, params)
        return _remember(Admission(context, method, boundary=boundary, preview=preview, params=params))
    if not artist_loop.needs_review(context):
        return _remember(Admission(context, method))
    bpy = require_blender()
    name = params.get("object_name")
    if not isinstance(name, str):
        raise invalid_argument("A reviewed transform requires an exact object_name.")
    obj = artist_loop._objects(bpy, [name])[0]
    boundary = Boundary(bpy, context, method, obj, transform=True, artist_profile=True)
    return _remember(Admission(context, method, boundary=boundary))
