"""Exercise retained role delegates through an actual authenticated checkpoint."""

from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

from test_checkpoint_snapshots import NativeStack


def complete_plan_push(addon_package, monkeypatch, plan, *, effect=None):
    """Deliver only the completion earned by a real manager's FINISHED push.

    ``effect`` models a native operator's narrowly expected state change. It runs
    inside that operator, after the manager's pre-push admission checks.
    """
    checkpoints = importlib.import_module(f"{addon_package}.checkpoints")
    completion = importlib.import_module(f"{addon_package}.checkpoint_completion")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state_module = importlib.import_module(f"{addon_package}.state")
    stack = NativeStack()
    manager = checkpoints.CheckpointManager()
    registry = registry_module.ToolRegistry()
    context = registry_module.ToolContext(
        state_module.BridgeState(), permissions.PermissionManager(lambda: {}), registry, manager,
    )
    method, params = "fixture.retained_roles", {}

    class FactoryGuard:
        def __call__(self):
            self.check_after_read()

        def check_after_read(self):
            plan.check_after_read()

        def native_push_delegates(self):
            return (plan,)

        def after_native_push(self):
            completion.claim_native_push_completion(context, method, self)
            plan.after_native_push()

    guard = FactoryGuard()
    spec = registry.register(method, lambda *_: None, modifies=True,
                             checkpoint_admission_factory=lambda *_: guard)
    push = stack.bpy.ops.ed.undo_push

    def actual_push(**kwargs):
        result = push(**kwargs)
        if "FINISHED" in result and effect is not None:
            effect()
        return result

    with monkeypatch.context() as patches:
        patches.setattr(checkpoints, "require_blender", lambda: stack.bpy)
        patches.setattr(stack.bpy.ops.ed, "undo_push", actual_push)
        with (registry.mutation_entry(spec, params, context) as permit,
              registry.checkpoint_admission(spec, params, context) as binding,
              registry.native_push_completion(
                  permit, binding, manager, final_check=lambda: binding.check_identity(method),
              ) as consumer):
            assert manager.before_modification(method, before_write=binding,
                after_read=binding.check_after_read, after_native_push=consumer)
    return NS(stack=stack, manager=manager, guard=guard, context=context, registry=registry)
