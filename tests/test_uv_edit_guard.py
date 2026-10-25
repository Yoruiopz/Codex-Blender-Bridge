"""Portable UV call-state models; no native BMesh/getter/undo qualification.

The fake checks ordinary witnesses before copying any UV payload. Expected
coordinates and recovery values come from fixed source data plus struct, never
from the guard's planned/expected output. Registry bindings are issued normally;
no native checkpoint completion or provider reproduction is fabricated here.
"""

from __future__ import annotations

import copy
import importlib
import struct
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace as NS
from typing import Any

import pytest

KEYS = ((0, 0, 0, 0), (0, 1, 1, 1), (0, 2, 2, 2), (0, 3, 3, 3))
METHODS = ("uv.coordinates_set", "uv.transform", "uv.pin")


def f32_pair(values: Any) -> tuple[float, float]:
    return struct.unpack("<ff", struct.pack("<ff", *values))


def pair_bits(values: Any) -> tuple[str, str]:
    return tuple(struct.pack("<f", value).hex() for value in values)


def original_maps() -> dict[str, list[dict[str, Any]]]:
    coordinates = {
        "Primary": [(0.0, -0.0), (0.25, 0.5), (-0.5, 0.75), (1.0, -1.0)],
        "Protected": [(0.125, 0.25), (0.375, 0.5), (0.625, 0.75), (0.875, 1.0)],
    }
    return {
        name: [
            {
                "face": key[0],
                "corner": key[1],
                "vertex": key[2],
                "edge": key[3],
                "uv": list(uv),
                "pin_uv": name == "Primary" and index == 1,
            }
            for index, (key, uv) in enumerate(zip(KEYS, values, strict=True))
        ]
        for name, values in coordinates.items()
    }


def model_digest(reader: Any) -> tuple[Any, ...]:
    return tuple(
        (
            name,
            tuple(
                (
                    tuple(row[field] for field in ("face", "corner", "vertex", "edge")),
                    pair_bits(row["uv"]),
                    row["pin_uv"],
                )
                for row in rows
            ),
        )
        for name, rows in reader.maps.items()
    )


class FieldTarget:
    """Ephemeral setter target; setters round exactly as native Float32 storage."""

    def __init__(self, reader: Any, key: tuple[int, ...]):
        self.reader, self.key = reader, key

    @property
    def uv(self) -> tuple[float, float]:
        self.reader.uv_reads += 1
        return tuple(self.reader.row(self.key)["uv"])

    @uv.setter
    def uv(self, values: Any) -> None:
        self.reader.assign(self.key, "uv", list(f32_pair(values)))

    @property
    def pin_uv(self) -> bool:
        self.reader.uv_reads += 1
        return self.reader.row(self.key)["pin_uv"]

    @pin_uv.setter
    def pin_uv(self, value: bool) -> None:
        assert type(value) is bool
        self.reader.assign(self.key, "pin_uv", value)


class FakeReader:
    def __init__(self, case: Any):
        self.case = case
        self.maps = original_maps()
        self.preservation = (
            ("context", ("Scene", "Layer", "EDIT", "Working", True)),
            ("topology", KEYS),
            ("material_binding", (101, 202)),
            ("protected_geometry", ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))),
        )
        self.identities = {"object": (11, 101), "mesh": (12, 102)}
        self.scope_keys, self.object_name, self.uv_layer = KEYS, "Working", "Primary"
        self.scalar_count = 2 * len(KEYS) * 3
        self.witness_valid = self.identity_valid = True
        self.witness_checks = self.uv_reads = self.snapshots = self.resolves = self.updates = 0
        self.writes: list[tuple[Any, ...]] = []
        self.native_events: list[tuple[Any, ...]] = []
        self.on_assign: Callable[[Any, str, Any], None] | None = None
        self.on_resolve: Callable[[], None] | None = None
        self.on_update: Callable[[], None] | None = None
        self.on_snapshot: Callable[[], None] | None = None
        self.proof_hooks = ()

    def row(self, key: tuple[int, ...]) -> dict[str, Any]:
        return next(
            row
            for row in self.maps[self.uv_layer]
            if tuple(row[field] for field in ("face", "corner", "vertex", "edge")) == key
        )

    def snapshot(self) -> Any:
        self.native_events.append(("snapshot",))
        self.snapshots += 1
        self.witness_checks += 1
        if not self.identity_valid:
            raise self.case.errors.BridgeError(
                "NOT_IMPLEMENTED",
                "Native model identity changed; UV payload must not be read",
                {"uv_identity_valid": False},
            )
        if not self.witness_valid:
            raise self.case.errors.BridgeError(
                "NOT_IMPLEMENTED",
                "Ordinary model witness invalid; UV payload must not be read",
                {"uv_witness_valid": False},
            )
        if self.on_snapshot is not None:
            self.on_snapshot()
        self.uv_reads += sum(len(rows) * 3 for rows in self.maps.values())
        return self.case.guard.NativeState(
            self.preservation, self.case.intent.freeze_snapshot(copy.deepcopy(self.maps))
        )

    def resolve(self, key: tuple[int, ...], field: str, expected: Any) -> FieldTarget:
        assert field in {"uv", "pin_uv"}
        self.resolves += 1
        assert self.identity_valid and self.witness_valid, (
            "Invalid ordinary witness reached a field resolver"
        )
        if self.on_resolve is not None:
            self.on_resolve()
        if not self.identity_valid or not self.witness_valid:
            kind = "identity" if not self.identity_valid else "witness"
            raise self.case.errors.BridgeError(
                "NOT_IMPLEMENTED",
                "Resolver lost its ordinary witness before the leaf copy",
                {"uv_" + kind + "_valid": False},
            )
        self.uv_reads += 1
        actual = self.row(key)[field]
        matched = (
            pair_bits(actual) == expected.uv_bits if field == "uv" else actual is expected.pin_uv
        )
        if expected.key != key or not matched:
            raise self.case.errors.BridgeError(
                "NOT_IMPLEMENTED", "Fresh leaf field differs from its retained prefix"
            )
        self.native_events.append(("resolve", key, field))
        return FieldTarget(self, key)

    def assign(self, key: tuple[int, ...], field: str, value: Any) -> None:
        self.native_events.append(("assign", key, field))
        self.writes.append((key, field, copy.deepcopy(value)))
        self.row(key)[field] = value
        if self.on_assign is not None:
            self.on_assign(key, field, value)

    def update(self) -> None:
        self.native_events.append(("update",))
        self.updates += 1
        if self.on_update is not None:
            self.on_update()


def coordinate_request() -> dict[str, Any]:
    return {
        "object_name": "Working",
        "uv_layer": "Primary",
        "selection_id": "faces-current",
        "updates": [
            {"face_index": 0, "corner_index": 0, "uv": [-0.0, 0.0]},
            {"face_index": 0, "corner_index": 2, "uv": [0.1, -0.2]},
        ],
    }


@pytest.fixture
def model(addon_package: str, monkeypatch: Any) -> Any:
    guard = importlib.import_module(f"{addon_package}.uv_edit_guard")
    intent = importlib.import_module(f"{addon_package}.uv_edit_intent")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permission_module = importlib.import_module(f"{addon_package}.permissions")
    state_module = importlib.import_module(f"{addon_package}.state")
    errors = importlib.import_module(f"{addon_package}.errors")
    grants = {
        permission.value: permission is permission_module.Permission.EDIT_MESH
        for permission in permission_module.Permission
    }
    case = NS(
        guard=guard,
        intent=intent,
        errors=errors,
        registry_module=registry_module,
        permissions=permission_module,
        grants=grants,
        provider=None,
        cancel=None,
        readers=[],
    )

    def permission_values() -> dict[str, bool]:
        if hasattr(case, "reader"):
            case.reader.native_events.append(("permission_provider",))
        if case.provider is not None:
            response = case.provider()
            if response is not None:
                return dict(response)
        return dict(grants)

    state = state_module.BridgeState()
    registry = registry_module.ToolRegistry(enabled_toolsets=("uv",))
    context = registry_module.ToolContext(
        state, permission_module.PermissionManager(permission_values), registry, NS()
    )

    def cancelled() -> None:
        if case.cancel is not None:
            raise errors.BridgeError(case.cancel, "Model request stopped")

    context.check_cancelled = cancelled
    case.state, case.registry, case.context = state, registry, context
    case.reader = FakeReader(case)

    def reader_factory(*_args: Any, **_kwargs: Any) -> FakeReader:
        case.readers.append(case.reader)
        return case.reader

    monkeypatch.setattr(guard, "_NativeReader", reader_factory)
    for method in METHODS:
        registry.register(
            method,
            lambda *_: None,
            toolset="uv",
            permissions=(permission_module.Permission.EDIT_MESH,),
            modifies=True,
            checkpoint_admission_factory=lambda context, params, method=method: guard.factory(
                method, context, params
            ),
        )

    @contextmanager
    def admitted(method: str = "uv.coordinates_set", params: dict[str, Any] | None = None):
        params = coordinate_request() if params is None else params
        with registry.checkpoint_admission(registry.get(method), params, context):
            yield guard.current(context, method, params), params

    case.admitted = admitted
    return case


def test_coordinates_round_decimals_and_write_zero_signs_without_touching_pins_or_other_map(model):
    expected = original_maps()
    expected["Primary"][0]["uv"] = [-0.0, 0.0]
    expected["Primary"][2]["uv"] = list(f32_pair((0.1, -0.2)))
    with model.admitted() as (guard, params):
        original_plan = guard.plan
        assert model.guard.current(model.context, "uv.coordinates_set", params) is guard
        result = guard.execute()
        assert guard.plan is original_plan
    assert model_digest(model.reader) == model_digest(NS(maps=expected))
    assert pair_bits(model.reader.maps["Primary"][0]["uv"]) == ("00000080", "00000000")
    assert pair_bits(model.reader.maps["Primary"][2]["uv"]) == ("cdcccc3d", "cdcc4cbe")
    assert result["coordinate_changes"] == 2 and result["pin_changes"] == 0 and result["changed"]
    assert [field for _key, field, _value in model.reader.writes] == ["uv", "uv"]
    assert model.reader.updates == 1 and len(model.readers) == 1
    assert model.context.checkpoint_admission is None


def test_transform_preserves_pinned_corner_with_independent_pivot_scale_offset_results(model):
    params = {
        "object_name": "Working",
        "uv_layer": "Primary",
        "offset": [0.5, 0.25],
        "scale": [2.0, -1.0],
        "pivot": [0.125, -0.25],
        "rotation": 0.0,
    }
    expected = original_maps()
    for index, value in ((0, (0.375, -0.25)), (2, (-0.625, -1.0)), (3, (2.375, 0.75))):
        expected["Primary"][index]["uv"] = list(value)
    with model.admitted("uv.transform", params) as (guard, _params):
        result = guard.execute()
    assert model_digest(model.reader) == model_digest(NS(maps=expected))
    assert result["coordinate_changes"] == 3 and result["pin_changes"] == 0
    assert result["skipped_pinned_corners"] == 1
    assert all(field == "uv" for _key, field, _value in model.reader.writes)


def test_pin_changes_only_requested_flags_and_preserves_all_coordinate_bits(model):
    params = {
        "object_name": "Working",
        "uv_layer": "Primary",
        "selection_id": "faces-current",
        "corners": [{"face_index": 0, "corner_index": 0}, {"face_index": 0, "corner_index": 2}],
        "pinned": True,
    }
    expected = original_maps()
    expected["Primary"][0]["pin_uv"] = expected["Primary"][2]["pin_uv"] = True
    with model.admitted("uv.pin", params) as (guard, _params):
        result = guard.execute()
    assert model_digest(model.reader) == model_digest(NS(maps=expected))
    assert result["pin_changes"] == 2 and result["coordinate_changes"] == 0
    assert all(field == "pin_uv" for _key, field, _value in model.reader.writes)


def test_bit_exact_noop_does_not_resolve_set_or_update(model):
    params = coordinate_request()
    params["updates"] = [{"face_index": 0, "corner_index": 0, "uv": [0.0, -0.0]}]
    before = model_digest(model.reader)
    with model.admitted(params=params) as (guard, _params):
        result = guard.execute()
    assert result["changed"] is False and result["coordinate_changes"] == result["pin_changes"] == 0
    assert model_digest(model.reader) == before
    assert model.reader.resolves == model.reader.updates == 0 and model.reader.writes == []


@pytest.mark.parametrize(
    "stop,code",
    [
        ("permission", "PERMISSION_DENIED"),
        ("paused", "AGENT_PAUSED"),
        ("emergency_stopped", "EMERGENCY_STOPPED"),
        ("cancel", "TIMEOUT"),
    ],
)
def test_explicit_registry_preflight_denial_never_constructs_reader_or_observes_uv(
    model, stop, code
):
    if stop == "permission":
        model.grants["EDIT_MESH"] = False
    elif stop == "cancel":
        model.cancel = "TIMEOUT"
    else:
        getattr(model.state, "set_" + stop)(True)
    with pytest.raises(model.errors.BridgeError) as caught:
        if stop == "cancel":
            model.context.check_final_request = model.context.check_cancelled
            model.registry.check_admission_entry(
                model.registry.get("uv.coordinates_set"), model.context
            )
        else:
            model.registry.prepare("uv.coordinates_set", model.context)
    assert caught.value.code == code
    assert model.readers == [] and model.reader.uv_reads == 0
    assert not model.reader.writes and model.reader.updates == 0


@pytest.mark.parametrize(
    "stop,code",
    [
        ("permission", "PERMISSION_DENIED"),
        ("paused", "AGENT_PAUSED"),
        ("emergency_stopped", "EMERGENCY_STOPPED"),
        ("cancel", "TIMEOUT"),
    ],
)
def test_late_authority_loss_keeps_first_requested_bits_and_stops_later_writes_and_restoration(
    model, stop, code
):
    def stop_after_first(_key, _field, _value):
        if len(model.reader.writes) != 1:
            return
        if stop == "permission":
            model.grants["EDIT_MESH"] = False
        elif stop == "cancel":
            model.cancel = "TIMEOUT"
        else:
            getattr(model.state, "set_" + stop)(True)

    model.reader.on_assign = stop_after_first
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert caught.value.code == code and caught.value.context["possible_mutation"] is True
    assert caught.value.context["rollback_verified"] is False
    expected = original_maps()
    expected["Primary"][0]["uv"] = [-0.0, 0.0]
    assert model_digest(model.reader) == model_digest(NS(maps=expected))
    assert len(model.reader.writes) == 1 and model.reader.updates == 0


@pytest.mark.parametrize("phase", ["before_first_write", "after_first_write"])
@pytest.mark.parametrize("kind", ["witness", "identity"])
def test_invalid_identity_or_ordinary_witness_is_checked_before_any_new_uv_payload_read(
    model, phase, kind
):
    stopped_reads = []
    with model.admitted() as (guard, _params):
        if phase == "before_first_write":
            setattr(model.reader, kind + "_valid", False)
            stopped_reads.append(model.reader.uv_reads)
        else:

            def invalidate(_key, _field, _value):
                setattr(model.reader, kind + "_valid", False)
                stopped_reads.append(model.reader.uv_reads)

            model.reader.on_assign = invalidate
        with pytest.raises(model.errors.BridgeError) as caught:
            guard.execute()
    assert caught.value.context["uv_" + kind + "_valid"] is False
    assert stopped_reads and model.reader.uv_reads == stopped_reads[0]
    assert len(model.reader.writes) == (0 if phase == "before_first_write" else 1)
    assert model.reader.updates == 0


def test_resolver_invalidation_is_measured_before_uv_read_or_assignment(model):
    invalidated_reads = []

    def invalidate():
        model.reader.witness_valid = False
        invalidated_reads.append(model.reader.uv_reads)

    model.reader.on_resolve = invalidate
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert caught.value.context["uv_witness_valid"] is False
    assert invalidated_reads == [model.reader.uv_reads]
    assert model.reader.writes == [] and model.reader.updates == 0


@pytest.mark.parametrize("change", ["owned", "unrelated_corner", "protected_map", "preservation"])
def test_newer_authored_or_protected_state_after_first_field_is_never_adopted_or_overwritten(
    model, change
):
    endpoint = []

    def manual_change(_key, _field, _value):
        if len(model.reader.writes) != 1:
            return
        if change == "owned":
            model.reader.maps["Primary"][0]["uv"] = [0.875, 0.625]
        elif change == "unrelated_corner":
            model.reader.maps["Primary"][3]["uv"] = [0.875, 0.625]
        elif change == "protected_map":
            model.reader.maps["Protected"][0]["uv"] = [0.875, 0.625]
        else:
            model.reader.preservation = (*model.reader.preservation, ("newer_manual_edit", 1))
        endpoint.append((model_digest(model.reader), model.reader.preservation))

    model.reader.on_assign = manual_change
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert endpoint == [(model_digest(model.reader), model.reader.preservation)]
    assert (
        caught.value.context["possible_mutation"] is True
        and caught.value.context["rollback_verified"] is False
    )
    assert len(model.reader.writes) == 1 and model.reader.updates == 0


def test_post_assignment_failure_can_restore_only_its_owned_field_with_exact_zero_bits(model):
    before = model_digest(model.reader)

    def fail_once(_key, _field, _value):
        if len(model.reader.writes) == 1:
            raise RuntimeError("Model setter failed after its actual requested assignment")

    model.reader.on_assign = fail_once
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert model_digest(model.reader) == before
    assert pair_bits(model.reader.maps["Primary"][0]["uv"]) == ("00000000", "00000080")
    assert [row[:2] for row in model.reader.writes] == [(KEYS[0], "uv"), (KEYS[0], "uv")]
    assert (
        caught.value.context["rollback_verified"] is True
        and caught.value.context["possible_mutation"] is True
    )


def test_unknown_setter_outcome_is_retained_without_guessing_or_compensating(model):
    endpoint = []

    def unknown(_key, _field, _value):
        model.reader.maps["Primary"][0]["uv"] = [0.875, 0.625]
        endpoint.append(model_digest(model.reader))
        raise RuntimeError("Model setter outcome differs from before and requested Float32 values")

    model.reader.on_assign = unknown
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert endpoint == [model_digest(model.reader)] and len(model.reader.writes) == 1
    assert (
        caught.value.context["rollback_verified"] is False
        and caught.value.context["possible_mutation"] is True
    )


def test_update_exception_retains_known_requested_payload_but_never_claims_unknown_native_cache_recovery(
    model,
):
    expected = original_maps()
    expected["Primary"][0]["uv"] = [-0.0, 0.0]
    expected["Primary"][2]["uv"] = list(f32_pair((0.1, -0.2)))

    def fail_once():
        if model.reader.updates == 1:
            raise RuntimeError("Model update failed without a foreign delta")

    model.reader.on_update = fail_once
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert model_digest(model.reader) == model_digest(NS(maps=expected))
    assert all(
        field == "uv" and key in {KEYS[0], KEYS[2]} for key, field, _value in model.reader.writes
    )
    assert len(model.reader.writes) == 2 and model.reader.updates == 1
    assert (
        caught.value.context["rollback_verified"] is False
        and caught.value.context["possible_mutation"] is True
    )
    assert caught.value.context["recovery_evidence"]["state_known"] is False


def test_update_that_changes_protected_data_never_enters_compensation(model):
    endpoint = []

    def coupled_update():
        model.reader.maps["Protected"][0]["uv"] = [0.875, 0.625]
        endpoint.append(model_digest(model.reader))
        raise RuntimeError("Model native update acquired a foreign delta")

    model.reader.on_update = coupled_update
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert (
        endpoint == [model_digest(model.reader)]
        and len(model.reader.writes) == 2
        and model.reader.updates == 1
    )
    assert (
        caught.value.context["rollback_verified"] is False
        and caught.value.context["possible_mutation"] is True
    )


@pytest.mark.parametrize(
    "flag,context_key",
    [
        ("disconnect", "connection_disconnected"),
        ("reject", "start_delivery_failed"),
        ("expire", "start_handoff_expired"),
    ],
)
def test_actual_lifetime_flags_after_first_assignment_prevent_followup_or_restore(
    model, addon_package, flag, context_key
):
    lifecycle = importlib.import_module(f"{addon_package}.request_lifecycle")
    owner = lifecycle.ConnectionLifetime()
    lifetime = lifecycle.RequestLifetime(connection=owner)
    model.context.request_lifecycle = lifetime

    def stop(_key, _field, _value):
        if flag == "disconnect":
            owner.disconnected.set()
        elif flag == "reject":
            lifetime.rejected.set()
        else:
            lifetime.deadline = -1.0

    model.reader.on_assign = stop
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert caught.value.code == "TIMEOUT" and caught.value.context[context_key] is True
    assert (
        caught.value.context["possible_mutation"] is True
        and caught.value.context["rollback_verified"] is False
    )
    assert len(model.reader.writes) == 1 and model.reader.updates == 0


def test_changed_native_state_before_first_assignment_is_not_recaptured_as_a_new_plan(model):
    with model.admitted() as (guard, _params):
        model.reader.maps["Protected"][0]["uv"] = [0.875, 0.625]
        endpoint = model_digest(model.reader)
        with pytest.raises(model.errors.BridgeError) as caught:
            guard.execute()
    assert endpoint == model_digest(model.reader)
    assert model.reader.writes == [] and model.reader.updates == 0 and len(model.readers) == 1
    assert caught.value.context["execution_started"] is False


def test_restoration_with_an_unknown_second_setter_outcome_cannot_claim_success(model):
    def failed_restore(_key, _field, _value):
        if len(model.reader.writes) == 2:
            model.reader.maps["Primary"][0]["uv"] = [0.875, 0.625]
        raise RuntimeError("First assignment and then compensation both failed")

    model.reader.on_assign = failed_restore
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert len(model.reader.writes) == 2
    assert model.reader.maps["Primary"][0]["uv"] == [0.875, 0.625]
    assert (
        caught.value.context["rollback_verified"] is False
        and caught.value.context["possible_mutation"] is True
    )


@pytest.mark.parametrize("phase", ["before_restore", "after_restore_setter"])
def test_foreign_state_introduced_during_restoration_is_not_erased_or_reported_recovered(
    model, phase
):
    endpoint = []

    def change_protected():
        if endpoint:
            return
        model.reader.maps["Protected"][0]["uv"] = [0.875, 0.625]
        endpoint.append(model_digest(model.reader))

    def fail_and_interleave(_key, _field, _value):
        if len(model.reader.writes) == 1:
            if phase == "before_restore":
                model.provider = change_protected
            raise RuntimeError("A measured first-field failure")
        if phase == "after_restore_setter":
            change_protected()

    model.reader.on_assign = fail_and_interleave
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert endpoint == [model_digest(model.reader)]
    assert len(model.reader.writes) == (1 if phase == "before_restore" else 2)
    assert model.reader.updates == 0
    assert (
        caught.value.context["rollback_verified"] is False
        and caught.value.context["possible_mutation"] is True
    )


def test_plan_is_deeply_frozen_and_equal_value_replacement_is_not_a_new_origin(model):
    with model.admitted() as (guard, params):
        with pytest.raises(FrozenInstanceError):
            guard.plan.expected = guard.plan.before
        original = guard.plan
        replacement = replace(original)
        assert replacement == original and replacement is not original
        guard.plan = replacement
        reads = model.reader.uv_reads
        with pytest.raises(model.errors.BridgeError):
            model.guard.current(model.context, "uv.coordinates_set", params).execute()
        assert model.reader.uv_reads == reads and model.reader.writes == []


@pytest.mark.parametrize(
    "fault", ["sign_parameters", "equal_parameter_mapping", "binding", "call_id", "method", "slots"]
)
def test_replaced_canonical_params_or_binding_are_denied_before_uv_read_and_write(model, fault):
    with model.admitted() as (_guard, params):
        reads = model.reader.uv_reads
        if fault == "sign_parameters":
            params["updates"][0]["uv"][0] = 0.0
        elif fault == "equal_parameter_mapping":
            model.context.checkpoint_params = copy.deepcopy(params)
        elif fault == "binding":
            model.context.checkpoint_admission = None
        elif fault == "call_id":
            model.context.checkpoint_call_id = object()
        elif fault == "method":
            model.context.checkpoint_method = "uv.pin"
        else:
            model.context.checkpoint_admission = model.context.checkpoint_call_id = None
            model.context.checkpoint_method = model.context.checkpoint_params = None
        with pytest.raises(model.errors.BridgeError):
            model.guard.current(model.context, "uv.coordinates_set", params).execute()
        assert model.reader.uv_reads == reads and model.reader.writes == []
        assert model.reader.updates == 0


@pytest.mark.parametrize(
    "fault",
    [
        "callback",
        "readonly",
        "marker",
        "reader",
        "reader_layer",
        "reader_name",
        "reader_identities",
        "reader_scope",
        "snapshot",
        "resolve",
        "update",
        "spec",
        "service",
    ],
)
def test_original_reader_proof_hooks_services_and_spec_cannot_be_replaced(model, fault):
    with model.admitted() as (guard, params):
        reads = model.reader.uv_reads
        if fault == "callback":
            model.context.checkpoint_admission.callback = lambda: None
        elif fault == "readonly":
            model.context.checkpoint_admission.readonly_callback = lambda: None
        elif fault == "marker":
            model.context.checkpoint_admission.marker_write_callback = lambda _event: None
        elif fault == "reader":
            guard.reader = FakeReader(model)
        elif fault == "reader_layer":
            model.reader.uv_layer = "Protected"
        elif fault == "reader_name":
            model.reader.object_name = "Other"
        elif fault == "reader_identities":
            model.reader.identities["object"] = (999, 101)
        elif fault == "reader_scope":
            model.reader.scope_keys = tuple(reversed(KEYS))
        elif fault in {"snapshot", "resolve", "update"}:
            setattr(model.reader, fault, lambda *_args: None)
        elif fault == "spec":
            original = model.registry.get("uv.coordinates_set")
            replacement = replace(original)
            assert replacement == original and replacement is not original
            model.registry._tools["uv.coordinates_set"] = replacement
        else:
            model.context.check_final_request = lambda: None
        with pytest.raises(model.errors.BridgeError):
            model.guard.current(model.context, "uv.coordinates_set", params).execute()
        assert (
            model.reader.uv_reads == reads
            and model.reader.writes == []
            and model.reader.updates == 0
        )


@pytest.mark.parametrize("method", METHODS)
def test_resolved_leaf_is_immediately_assigned_without_snapshot_or_provider_in_between(
    model, method
):
    params = (
        coordinate_request()
        if method == "uv.coordinates_set"
        else {
            "object_name": "Working",
            "uv_layer": "Primary",
            **({"offset": [0.125, -0.25]} if method == "uv.transform" else {"pinned": True}),
        }
    )
    with model.admitted(method, params) as (guard, _params):
        guard.execute()
    events = model.reader.native_events
    resolved = [(index, event) for index, event in enumerate(events) if event[0] == "resolve"]
    assert resolved
    for index, event in resolved:
        assert events[index + 1] == ("assign", *event[1:])


def test_successful_guard_is_one_use_and_released_binding_never_recaptures(model):
    with model.admitted() as (guard, params):
        guard.execute()
        endpoint = model_digest(model.reader)
        reads, writes = model.reader.uv_reads, len(model.reader.writes)
        with pytest.raises(model.errors.BridgeError):
            guard.execute()
        assert (
            model_digest(model.reader) == endpoint
            and len(model.reader.writes) == writes
            and model.reader.uv_reads == reads
        )
    with pytest.raises(model.errors.BridgeError):
        model.guard.current(model.context, "uv.coordinates_set", params)
    assert len(model.readers) == 1


@pytest.mark.parametrize("phase", ["before_write", "after_first_assignment"])
def test_comparison_budget_exhaustion_stops_before_new_payload_reads_and_never_guesses_recovery(
    model, monkeypatch, phase
):
    stopped_counters = []

    def exhaust():
        stopped_counters.append((model.reader.snapshots, model.reader.uv_reads))
        monkeypatch.setattr(model.guard, "MAX_COMPARE_VALUES", 0)

    with model.admitted() as (guard, _params):
        if phase == "before_write":
            exhaust()
        else:
            model.reader.on_assign = lambda *_args: exhaust()
        with pytest.raises(model.errors.BridgeError) as caught:
            guard.execute()
    assert stopped_counters == [(model.reader.snapshots, model.reader.uv_reads)]
    assert (
        len(model.reader.writes) == (0 if phase == "before_write" else 1)
        and model.reader.updates == 0
    )
    assert caught.value.context["execution_started"] is (phase != "before_write")
    assert caught.value.context["rollback_verified"] is False
    assert caught.value.context["recovery_evidence"]["state_known"] is False


@pytest.mark.parametrize(
    "fault", ["foreign_expected", "equal_expected", "unowned_journal", "equal_journal"]
)
def test_expected_prefix_and_verified_journal_origins_cannot_be_replaced_after_first_field(
    model, fault
):
    injected = []
    with model.admitted() as (guard, _params):

        def substitute_once():
            if injected or not guard._journal:
                return
            assert len(model.reader.writes) == guard.verified == len(guard._journal) == 1
            if fault.endswith("expected"):
                original = guard._expected
                replacement = (
                    replace(original, preservation=(*original.preservation, ("foreign_origin", 1)))
                    if fault == "foreign_expected"
                    else replace(original)
                )
                assert replacement is not original
                if fault == "equal_expected":
                    assert replacement == original
                guard._expected = replacement
            else:
                original = guard._journal
                assert type(original) is tuple and original
                replacement = (
                    ((KEYS[3], "uv", guard.before.uv.maps[0].corners[3]),)
                    if fault == "unowned_journal"
                    else tuple(list(original))
                )
                assert replacement is not original
                if fault == "equal_journal":
                    assert replacement == original
                guard._journal = replacement
            injected.append(
                (
                    model.reader.snapshots,
                    model.reader.uv_reads,
                    model.reader.resolves,
                    len(model.reader.writes),
                    model.reader.updates,
                )
            )

        model.provider = substitute_once
        with pytest.raises(model.errors.BridgeError) as caught:
            guard.execute()
    assert injected == [
        (
            model.reader.snapshots,
            model.reader.uv_reads,
            model.reader.resolves,
            len(model.reader.writes),
            model.reader.updates,
        )
    ]
    assert len(model.reader.writes) == 1 and model.reader.updates == 0
    expected = original_maps()
    expected["Primary"][0]["uv"] = [-0.0, 0.0]
    assert model_digest(model.reader) == model_digest(NS(maps=expected))
    evidence = caught.value.context["recovery_evidence"]
    assert (
        caught.value.context["possible_mutation"] is True
        and caught.value.context["rollback_verified"] is False
    )
    assert (
        evidence["restoration_attempts"] == 0
        and evidence["restoration_refused"] == "AUTHORITY_LOST"
    )


@pytest.mark.parametrize(
    "fault", ["equal_source", "unplanned_key", "unplanned_field", "unverified_restore"]
)
def test_field_routing_requires_original_owned_corner_and_a_verified_restore_entry_before_native_reads(
    model, fault
):
    with model.admitted() as (guard, _params):
        key, field, restoring = KEYS[0], "uv", False
        source = guard.plan.expected.maps[0].corners[0]
        if fault == "equal_source":
            original = source
            source = replace(source)
            assert source == original and source is not original
        elif fault == "unplanned_key":
            key, source = KEYS[3], guard.plan.expected.maps[0].corners[3]
        elif fault == "unplanned_field":
            field = "pin_uv"
        else:
            source, restoring = guard.before.uv.maps[0].corners[0], True
        counts = (model.reader.snapshots, model.reader.uv_reads, model.reader.resolves)
        before = model_digest(model.reader)
        with pytest.raises(model.errors.BridgeError):
            guard._write(key, field, source, restoring=restoring)
        assert counts == (model.reader.snapshots, model.reader.uv_reads, model.reader.resolves)
        assert (
            model_digest(model.reader) == before
            and model.reader.writes == []
            and model.reader.updates == 0
        )


def test_one_shot_permission_denial_remains_latched_when_live_grants_are_already_true_again(model):
    def deny_once():
        if len(model.reader.writes) != 1:
            return None
        model.provider = None
        return {"EDIT_MESH": False}

    model.provider = deny_once
    with model.admitted() as (guard, _params), pytest.raises(model.errors.BridgeError) as caught:
        guard.execute()
    assert model.grants["EDIT_MESH"] is True and model.provider is None
    assert (
        caught.value.code == "PERMISSION_DENIED"
        and caught.value.context["rollback_verified"] is False
    )
    assert len(model.reader.writes) == 1
    guard._recover()  # A later private cleanup attempt must keep the same stop.
    assert len(model.reader.writes) == 1 and pair_bits(model.reader.maps["Primary"][0]["uv"]) == (
        "00000080",
        "00000000",
    )


@pytest.mark.parametrize("invalid_index", range(5))
def test_actual_reader_refuses_invalid_ordinary_witness_before_native_session_or_uv_getters(
    addon_package, invalid_index
):
    module = importlib.import_module(f"{addon_package}.uv_edit_guard")
    errors = importlib.import_module(f"{addon_package}.errors")
    payload_accesses = []

    class Witness:
        def __init__(self, valid):
            self.valid = valid

        @property
        def is_valid(self):
            return self.valid

        def __getattr__(self, name):
            payload_accesses.append(name)
            raise AssertionError("Invalid descendant/native payload accessed")

    class NativeBomb:
        def __getattr__(self, name):
            payload_accesses.append(name)
            raise AssertionError("A native session/UV getter ran after an invalid ordinary witness")

    ordinary = [Witness(index != invalid_index) for index in range(5)]
    reader = module._NativeReader.__new__(module._NativeReader)
    reader.bm = ordinary[0]
    reader.verts, reader.edges, reader.faces, reader.loops = [(item,) for item in ordinary[1:]]
    reader._witness_types = tuple((type(item), type(item).is_valid) for item in ordinary)
    reader.bpy = reader.bmesh = reader.mesh = reader.obj = NativeBomb()
    with pytest.raises(errors.BridgeError) as caught:
        reader.snapshot()
    assert (
        caught.value.code == "NOT_IMPLEMENTED" and caught.value.context["uv_witness_valid"] is False
    )
    assert payload_accesses == []


def test_ordinary_registered_denial_does_not_enter_a_setter_after_readonly_capture(model):
    model.grants["EDIT_MESH"] = False
    with pytest.raises(model.errors.BridgeError) as caught:
        model.registry.dispatch("uv.coordinates_set", coordinate_request(), model.context)
    assert caught.value.code == "PERMISSION_DENIED"
    assert (
        len(model.readers) == 1
    )  # Original capture precedes live permission providers by contract.
    assert model.reader.resolves == model.reader.updates == 0 and model.reader.writes == []
