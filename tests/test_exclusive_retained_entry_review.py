"""Fault injection: diagnostic-slot loss must not release a retained scope."""

from __future__ import annotations

import pytest
from test_exclusive_mutation import exclusive, invoke_outer  # noqa: F401


@pytest.mark.parametrize("entry", ["executor", "registry", "invoke"])
def test_retained_exclusive_scope_blocks_foreign_writer_after_both_slots_are_cleared(
    exclusive, entry  # noqa: F811
):
    case = exclusive
    nested_errors = []

    def callback():
        interlock = case.registry._mutation_interlock
        assert len(interlock._entries) == 1
        assert interlock._entries[0].lease is case.context.exclusive_mutation_lease
        interlock.owner = None
        interlock.invocation = None
        events_before = list(case.events)
        try:
            if entry == "executor":
                case.executor.dispatch("fixture.child", {})
            elif entry == "registry":
                case.registry.dispatch("fixture.child", {}, case.context)
            else:
                case.registry.invoke(case.child, {}, case.context)
        except case.errors.BridgeError as error:
            nested_errors.append(error)
        assert case.events == events_before

    case.hooks["native"] = callback
    with pytest.raises(case.errors.BridgeError) as caught:
        invoke_outer(case)
    assert caught.value.context["reason"] == "EXCLUSIVE_MUTATION_LEASE_LOST"
    assert case.writes == [], (
        "Foreign mutation completed inside the retained exclusive scope before "
        f"the outer gate detected slot loss: writes={case.writes!r}; events={case.events!r}"
    )
    assert len(nested_errors) == 1
    assert nested_errors[0].context["reason"] == "REENTRANT_MUTATION_BLOCKED"


def test_foreign_final_mutation_gate_does_not_treat_diagnostic_slot_loss_as_no_owner(
    exclusive,  # noqa: F811
):
    case, params = exclusive, {}
    rejected = []
    with (
        pytest.raises(case.errors.BridgeError) as outer,
        case.registry.mutation_entry(case.outer, params, case.context),
    ):
        case.registry._mutation_interlock.owner = None
        case.registry._mutation_interlock.invocation = None
        try:
            case.registry_module.check_final_mutation(
                case.context, case.child.name, expected_spec=case.child
            )
        except case.errors.BridgeError as error:
            rejected.append(error)
    assert outer.value.context["reason"] == "EXCLUSIVE_MUTATION_LEASE_LOST"
    assert len(rejected) == 1, "Foreign pure final gate passed despite retained exclusive entry."
    assert rejected[0].context["reason"] == "EXCLUSIVE_MUTATION_LEASE_LOST"


def test_readonly_call_preserves_outer_display_until_retained_scope_unwinds(
    exclusive,  # noqa: F811
):
    case = exclusive
    observed = []

    def callback():
        case.registry._mutation_interlock.owner = None
        case.registry._mutation_interlock.invocation = None
        assert case.registry.active_exclusive_mutation is True
        before = case.state.snapshot()
        result = case.executor.dispatch("fixture.inspect", {})
        assert result["current_method"] == "fixture.exclusive"
        after = case.state.snapshot()
        assert after["current_method"] == before["current_method"]
        assert after["current_task"] == before["current_task"]
        assert after["is_executing"] is True
        observed.append(result)

    case.hooks["native"] = callback
    with pytest.raises(case.errors.BridgeError) as caught:
        invoke_outer(case)
    assert caught.value.context["reason"] == "EXCLUSIVE_MUTATION_LEASE_LOST"
    assert len(observed) == 1 and case.writes == []
    assert case.registry.active_exclusive_mutation is False
    case.executor.dispatch("fixture.child", {})
    assert case.writes == ["child"]
