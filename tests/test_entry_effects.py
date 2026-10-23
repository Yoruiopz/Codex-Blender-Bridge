"""Entry effects are bounded diagnostics, never authority for native writes."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from contextvars import copy_context
from threading import Barrier, Thread

import pytest


@pytest.fixture
def effects(addon_package):
    module = importlib.import_module(addon_package + ".entry_effects")
    assert module.current_entry_audit() is None
    yield module
    assert module.current_entry_audit() is None


@pytest.fixture
def errors(addon_package):
    return importlib.import_module(addon_package + ".errors")


def expected(*, handler=False):
    return {
        "view_layer_sync_possible": True,
        "context_change_measured": False,
        "handler_entered": handler,
        "reinspection_required": True,
    }


def denial(errors, **details):
    return errors.BridgeError(errors.ErrorCode.PERMISSION_DENIED, "Original denial", details)


def test_outside_entry_markers_do_not_create_or_reopen_audit(effects):
    effects.mark_view_layer_sync_possible()
    effects.mark_handler_entered()
    assert effects.current_entry_audit() is None
    assert effects.snapshot_entry_effects(None) is None
    with effects.entry_audit() as audit:
        assert effects.current_entry_audit() is audit
        assert effects.snapshot_entry_effects(audit) is None
    effects.mark_view_layer_sync_possible()
    assert effects.snapshot_entry_effects(audit) is None
    with effects.entry_audit() as fresh:
        assert fresh is not audit
        assert effects.snapshot_entry_effects(fresh) is None


def test_live_snapshot_is_conservative_detached_and_closed_on_exit(effects):
    with effects.entry_audit() as audit:
        effects.mark_handler_entered()
        assert effects.snapshot_entry_effects(audit) is None
        effects.mark_view_layer_sync_possible()
        first = effects.snapshot_entry_effects(audit)
        assert first == expected(handler=True)
        assert all(type(value) is bool for value in first.values())
        first["context_change_measured"] = True
        first["extra"] = True
        assert effects.snapshot_entry_effects(audit) == expected(handler=True)
    assert effects.current_entry_audit() is None
    assert effects.snapshot_entry_effects(audit) is None


def test_binding_live_carrier_routes_marks_without_closing_or_folding_handler(effects):
    with effects.entry_audit() as retained:
        with effects.entry_audit() as physical:
            with effects.bind_entry_audit(retained):
                assert effects.current_entry_audit() is retained
                effects.mark_view_layer_sync_possible()
                effects.mark_handler_entered()
                assert effects.snapshot_entry_effects(retained) == expected(handler=True)
            assert retained.live is True
            assert effects.current_entry_audit() is physical
            assert effects.snapshot_entry_effects(physical) == expected()
        assert effects.current_entry_audit() is retained
        assert effects.snapshot_entry_effects(retained) == expected(handler=True)
    assert retained.live is False


def test_nested_duplicate_bindings_restore_each_physical_caller(effects):
    with effects.entry_audit() as retained:
        with effects.bind_entry_audit(retained):
            assert effects.current_entry_audit() is retained
        assert retained.live is True
        with effects.entry_audit() as physical:
            with effects.bind_entry_audit(retained):
                with effects.entry_audit() as child:
                    with effects.bind_entry_audit(retained):
                        effects.mark_view_layer_sync_possible()
                        effects.mark_handler_entered()
                    assert effects.current_entry_audit() is child
                    assert retained.live is True
                    assert effects.snapshot_entry_effects(child) == expected()
                assert effects.current_entry_audit() is retained
                assert child.live is False
            assert effects.current_entry_audit() is physical
            assert effects.snapshot_entry_effects(physical) == expected()
        assert effects.current_entry_audit() is retained
        assert effects.snapshot_entry_effects(retained) == expected(handler=True)
    assert effects.current_entry_audit() is None


def test_binding_exception_restores_caller_and_keeps_carrier_live(effects, errors):
    primary = denial(errors)
    with effects.entry_audit() as retained, effects.entry_audit() as physical:
        with pytest.raises(errors.BridgeError) as caught, effects.bind_entry_audit(retained):
            effects.mark_view_layer_sync_possible()
            effects.mark_handler_entered()
            raise primary
        assert caught.value is primary
        assert effects.current_entry_audit() is physical
        assert retained.live is True
        assert effects.snapshot_entry_effects(physical) == expected()
        assert effects.snapshot_entry_effects(retained) == expected(handler=True)


def test_binding_absent_or_closed_carrier_does_not_reopen_it(effects):
    with effects.entry_audit() as closed:
        pass
    with effects.entry_audit() as physical:
        for carrier in (None, closed):
            with effects.bind_entry_audit(carrier):
                assert effects.current_entry_audit() is physical
            assert effects.current_entry_audit() is physical
            assert closed.live is False
            assert effects.snapshot_entry_effects(physical) is None


def test_marker_precedes_getter_failure_and_preserves_primary_error(effects, errors):
    primary = denial(errors, execution_started=False, possible_mutation=False)

    class Getter:
        @property
        def active(self):
            assert effects.snapshot_entry_effects(effects.current_entry_audit()) == expected()
            raise primary

    with effects.entry_audit() as audit:
        with pytest.raises(errors.BridgeError) as caught:
            effects.mark_view_layer_sync_possible()
            _ = Getter().active
        assert caught.value is primary
        assert effects.annotate_entry_error(primary, audit) == expected()
        assert primary.context["entry_effects"] == expected()
        assert primary.context["execution_started"] is False
        assert primary.context["possible_mutation"] is False


@pytest.mark.parametrize("fail_child", [False, True])
def test_child_effect_folds_on_success_or_failure_but_handler_does_not(effects, errors, fail_child):
    primary = denial(errors)
    with effects.entry_audit() as parent:
        try:
            with effects.entry_audit() as child:
                assert child is not parent
                effects.mark_handler_entered()
                effects.mark_view_layer_sync_possible()
                assert effects.snapshot_entry_effects(child) == expected(handler=True)
                if fail_child:
                    raise primary
        except errors.BridgeError as caught:
            assert fail_child and caught is primary
        assert effects.current_entry_audit() is parent
        assert effects.snapshot_entry_effects(child) is None
        assert effects.snapshot_entry_effects(parent) == expected()
        outer_error = denial(errors, requested_edit_started=False)
        assert effects.annotate_entry_error(outer_error, parent) == expected()
        assert outer_error.context["requested_edit_started"] is False


def test_marked_parent_does_not_label_unmarked_child_or_sibling(effects, errors):
    with effects.entry_audit() as parent:
        effects.mark_view_layer_sync_possible()
        effects.mark_handler_entered()
        for _ in range(2):
            with effects.entry_audit() as child:
                assert effects.snapshot_entry_effects(child) is None
                primary = denial(errors, entry_effects=expected(handler=True))
                assert effects.annotate_entry_error(primary, child) is None
                assert "entry_effects" not in primary.context
                effects.mark_handler_entered()
                assert effects.snapshot_entry_effects(child) is None
            assert effects.snapshot_entry_effects(parent) == expected(handler=True)


def test_multiple_nested_levels_fold_only_context_effect(effects):
    with effects.entry_audit() as root:
        with effects.entry_audit() as middle:
            with effects.entry_audit() as leaf:
                effects.mark_view_layer_sync_possible()
                effects.mark_handler_entered()
                assert effects.snapshot_entry_effects(leaf) == expected(handler=True)
            assert effects.snapshot_entry_effects(middle) == expected()
        assert effects.snapshot_entry_effects(root) == expected()
        with effects.entry_audit() as sibling:
            assert effects.snapshot_entry_effects(sibling) is None
        assert effects.snapshot_entry_effects(root) == expected()


def test_copied_context_child_folds_into_physical_parent(effects):
    copied = copy_context()
    with effects.entry_audit() as parent:

        def child_call():
            assert effects.current_entry_audit() is parent
            with effects.entry_audit() as child:
                assert child is not parent
                assert effects.current_entry_audit() is child
                effects.mark_view_layer_sync_possible()
                effects.mark_handler_entered()
                return child, effects.snapshot_entry_effects(child)

        child, child_effects = copied.run(child_call)
        assert child_effects == expected(handler=True)
        assert effects.snapshot_entry_effects(child) is None
        assert effects.current_entry_audit() is parent
        assert effects.snapshot_entry_effects(parent) == expected()


def test_old_copied_context_uses_new_physical_entry_and_cannot_revive_old(effects):
    with effects.entry_audit() as old:
        copied = copy_context()
        effects.mark_view_layer_sync_possible()
    assert effects.snapshot_entry_effects(old) is None
    copied.run(effects.mark_view_layer_sync_possible)
    assert effects.current_entry_audit() is None
    with effects.entry_audit() as current:
        assert effects.snapshot_entry_effects(current) is None

        def new_call():
            assert effects.current_entry_audit() is current
            with effects.entry_audit() as child:
                assert child is not old and child is not current
                effects.mark_view_layer_sync_possible()
                return child

        child = copied.run(new_call)
        assert effects.snapshot_entry_effects(child) is None
        assert effects.snapshot_entry_effects(old) is None
        assert effects.snapshot_entry_effects(current) == expected()


def test_physical_threads_do_not_share_entry_or_effects_even_with_copied_context(effects):
    barrier = Barrier(2, timeout=3)
    failures, observations = [], []
    with effects.entry_audit() as parent:
        effects.mark_handler_entered()
        copied = copy_context()

        def worker():
            try:
                assert effects.current_entry_audit() is None
                with effects.entry_audit() as audit:
                    effects.mark_view_layer_sync_possible()
                    observations.append(effects.snapshot_entry_effects(audit))
                    barrier.wait()
                    barrier.wait()
                    assert effects.snapshot_entry_effects(audit) == expected()
                assert effects.current_entry_audit() is None
            except BaseException as error:
                failures.append(error)
                barrier.abort()

        thread = Thread(target=lambda: copied.run(worker))
        thread.start()
        try:
            barrier.wait()
            assert effects.current_entry_audit() is parent
            assert effects.snapshot_entry_effects(parent) is None
            effects.mark_view_layer_sync_possible()
            assert effects.snapshot_entry_effects(parent) == expected(handler=True)
            barrier.wait()
        finally:
            thread.join(timeout=4)
        assert not thread.is_alive()
        assert failures == []
        assert observations == [expected()]


def test_annotation_preserves_primary_identity_and_legacy_execution_evidence(effects, errors):
    cause = RuntimeError("original cause")
    primary = denial(
        errors,
        required=["TRANSFORM_OBJECTS"],
        missing_permissions=["TRANSFORM_OBJECTS"],
        execution_started=False,
        requested_edit_started=False,
        possible_mutation=False,
        rollback_verified=True,
    )
    primary.__cause__ = cause
    original = primary.to_dict()
    original_context = dict(primary.context)
    with effects.entry_audit() as audit:
        effects.mark_view_layer_sync_possible()
        assert effects.annotate_entry_error(primary, audit) == expected()
    assert primary.code == original["code"]
    assert primary.message == original["message"]
    assert primary.args == (original["message"],)
    assert primary.__cause__ is cause
    assert {key: primary.context[key] for key in original_context} == original_context
    assert primary.context["entry_effects"] == expected()
    assert primary.context["verification_required"] is True
    assert set(primary.context) == set(original_context) | {
        "entry_effects",
        "verification_required",
    }


def test_reused_error_gets_current_entry_effects_instead_of_stale_fields(effects, errors):
    primary = denial(errors)
    with effects.entry_audit() as first:
        effects.mark_view_layer_sync_possible()
        effects.mark_handler_entered()
        assert effects.annotate_entry_error(primary, first) == expected(handler=True)
    assert effects.annotate_entry_error(primary, first) is None
    assert "entry_effects" not in primary.context
    with effects.entry_audit() as fresh:
        primary.context["entry_effects"] = expected(handler=True)
        assert effects.annotate_entry_error(primary, fresh) is None
        assert "entry_effects" not in primary.context
        effects.mark_view_layer_sync_possible()
        assert effects.annotate_entry_error(primary, fresh) == expected()
    assert effects.annotate_entry_error(primary, None) is None
    assert "entry_effects" not in primary.context
    assert primary.context["verification_required"] is True


@pytest.mark.parametrize("handler", [False, True])
def test_bounded_effects_accepts_only_canonical_detached_metadata(effects, handler):
    source = expected(handler=handler)
    bounded = effects.bounded_entry_effects(source)
    assert bounded == source and bounded is not source
    source["handler_entered"] = not handler
    assert bounded == expected(handler=handler)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        1,
        "view_layer_sync_possible",
        [],
        {},
        {"view_layer_sync_possible": True},
        {**expected(), "extra": True},
        {**expected(), "view_layer_sync_possible": False},
        {**expected(), "context_change_measured": True},
        {**expected(), "reinspection_required": False},
        {**expected(), "handler_entered": 1},
        {**expected(), "handler_entered": "false"},
        {**expected(), "handler_entered": None},
        {**expected(), "view_layer_sync_possible": 1},
        {**expected(), "context_change_measured": 0},
        {**expected(), "reinspection_required": 1},
    ],
)
def test_bounded_effects_rejects_forged_or_coerced_metadata(effects, value):
    assert effects.bounded_entry_effects(value) is None


def test_bounded_effects_does_not_invoke_mapping_or_dict_subclass_hooks(effects):
    class UnknownMapping(Mapping):
        def __len__(self):
            raise AssertionError("Unreviewed mapping length was read")

        def __iter__(self):
            raise AssertionError("Unreviewed mapping was traversed")

        def __getitem__(self, key):
            raise AssertionError("Unreviewed mapping value was read")

    class UnknownDict(dict):
        def keys(self):
            raise AssertionError("Unreviewed dict keys were read")

        def items(self):
            raise AssertionError("Unreviewed dict items were read")

        def get(self, key, default=None):
            raise AssertionError("Unreviewed dict getter was called")

    assert effects.bounded_entry_effects(UnknownMapping()) is None
    assert effects.bounded_entry_effects(UnknownDict(expected())) is None


@pytest.mark.parametrize("failure", [MemoryError, RuntimeError])
def test_annotation_allocation_failure_never_replaces_primary(
    effects, errors, monkeypatch, failure
):
    primary = denial(errors, execution_started=False, possible_mutation=False)
    before = primary.to_dict()

    def unavailable(_audit):
        raise failure("Diagnostic allocation failed")

    with effects.entry_audit() as audit:
        effects.mark_view_layer_sync_possible()
        monkeypatch.setattr(effects, "snapshot_entry_effects", unavailable)
        assert effects.annotate_entry_error(primary, audit) is None
    assert primary.to_dict() == before
    assert primary.code == errors.ErrorCode.PERMISSION_DENIED.value


def test_annotation_context_write_failure_never_replaces_primary(effects, errors):
    class UnwritableContext(dict):
        def __setitem__(self, key, value):
            raise MemoryError("Diagnostic context write failed")

    primary = denial(errors, execution_started=False)
    primary.context = UnwritableContext(primary.context)
    with effects.entry_audit() as audit:
        effects.mark_view_layer_sync_possible()
        assert effects.annotate_entry_error(primary, audit) is None
    assert primary.code == errors.ErrorCode.PERMISSION_DENIED.value
    assert primary.message == "Original denial"
    assert primary.context == {"execution_started": False}
