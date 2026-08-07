from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


class _NamedCollection(list[SimpleNamespace]):
    pass


def _fake_bpy() -> SimpleNamespace:
    return SimpleNamespace(
        data=SimpleNamespace(
            actions=_NamedCollection(),
            armatures=_NamedCollection(),
            collections=_NamedCollection(),
            images=_NamedCollection(),
            materials=_NamedCollection(),
            meshes=_NamedCollection(),
            node_groups=_NamedCollection(),
            objects=_NamedCollection([SimpleNamespace(name="Cube")]),
        )
    )


def test_python_requires_explicit_acknowledgement(addon_package: str) -> None:
    module = importlib.import_module(f"{addon_package}.tools.python_exec")
    errors = importlib.import_module(f"{addon_package}.errors")

    with pytest.raises(errors.BridgeError) as caught:
        module.python_execute(
            SimpleNamespace(),
            {"code": "result = 1", "expected_effect": "Compute a value"},
        )

    assert caught.value.code == errors.ErrorCode.INVALID_ARGUMENT.value
    assert "confirm_dangerous" in caught.value.message


def test_python_policy_rejects_process_and_introspection_imports(
    addon_package: str,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.python_exec")
    errors = importlib.import_module(f"{addon_package}.errors")

    for code in (
        "import os",
        "import subprocess",
        "import random\nresult = random._os.system('echo unsafe')",
        "import bpy\nresult = bpy.path.os.system('echo unsafe')",
        "result = (1).__class__",
    ):
        with pytest.raises(errors.BridgeError) as caught:
            module._validate_script(code)
        assert caught.value.code == errors.ErrorCode.INVALID_ARGUMENT.value


@pytest.mark.parametrize(
    "code",
    (
        "try:\n    result = 1\nexcept:\n    result = 2",
        "try:\n    result = 1\nexcept BaseException:\n    result = 2",
        "try:\n    result = 1\nfinally:\n    result = 2",
    ),
)
def test_python_policy_rejects_deadline_escape_constructs(
    addon_package: str,
    code: str,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.python_exec")
    errors = importlib.import_module(f"{addon_package}.errors")

    with pytest.raises(errors.BridgeError) as caught:
        module._validate_script(code)

    assert caught.value.code == errors.ErrorCode.INVALID_ARGUMENT.value
    assert "deadline policy" in caught.value.message


def test_python_exec_returns_bounded_result_and_audit_delta(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.python_exec")
    fake = _fake_bpy()
    monkeypatch.setattr(module, "require_blender", lambda: fake)

    response = module.python_execute(
        SimpleNamespace(),
        {
            "code": "print('working')\nresult = {'sum': sum(inputs['values'])}",
            "expected_effect": "Compute a test value without changing Blender",
            "confirm_dangerous": True,
            "inputs": {"values": [2, 3, 5]},
            "time_limit_seconds": 1.0,
        },
    )

    assert response["executed"] is True
    assert response["stdout"] == "working\n"
    assert response["result"] == {"sum": 10}
    assert response["result_truncated"] is False
    assert response["objects_added"] == {"items": [], "count": 0, "truncated": False}
    assert response["verification_required"] is True


def test_python_exec_omits_oversized_result_before_transport_encoding(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.python_exec")
    serialization = importlib.import_module(f"{addon_package}.serialization")
    fake = _fake_bpy()
    monkeypatch.setattr(module, "require_blender", lambda: fake)

    response = module.python_execute(
        SimpleNamespace(),
        {
            "code": "result = 'x' * int(inputs['size'])",
            "expected_effect": "Return an intentionally oversized test value",
            "confirm_dangerous": True,
            "inputs": {"size": 3_000_000},
            "time_limit_seconds": 1.0,
        },
    )

    assert response["result_truncated"] is True
    assert response["result"]["__truncated__"] is True
    assert response["result_bytes"] is None
    assert len(serialization.dumps(response).encode("utf-8")) < 512 * 1024


@pytest.mark.parametrize(
    ("code", "reason"),
    (
        (
            "leaf = [0] * 2000\nmid = [leaf] * 2000\nresult = [mid] * 2000",
            "cyclic_or_shared_reference",
        ),
        ("result = []\nresult.append(result)", "cyclic_or_shared_reference"),
    ),
)
def test_python_result_budget_rejects_shared_and_cyclic_expansion(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    reason: str,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.python_exec")
    fake = _fake_bpy()
    monkeypatch.setattr(module, "require_blender", lambda: fake)

    response = module.python_execute(
        SimpleNamespace(),
        {
            "code": code,
            "expected_effect": "Exercise the result graph budget",
            "confirm_dangerous": True,
            "time_limit_seconds": 1.0,
        },
    )

    assert response["result_truncated"] is True
    assert response["result"]["reason"] == reason
    assert response["result"]["maximum_items"] == 4_000


def test_python_result_budget_rejects_huge_integer_without_stringifying_it(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.python_exec")
    fake = _fake_bpy()
    monkeypatch.setattr(module, "require_blender", lambda: fake)

    response = module.python_execute(
        SimpleNamespace(),
        {
            "code": "result = 10 ** int(inputs['power'])",
            "expected_effect": "Exercise the integer result budget",
            "confirm_dangerous": True,
            "inputs": {"power": 100_000},
            "time_limit_seconds": 1.0,
        },
    )

    assert response["result_truncated"] is True
    assert response["result"]["reason"] == "integer_digit_budget"


def test_python_import_allowlist_supports_math(addon_package: str) -> None:
    module = importlib.import_module(f"{addon_package}.tools.python_exec")

    compiled = module._validate_script("import math\nresult = math.sqrt(9)")

    assert compiled is not None


def test_failed_python_reports_audit_and_mutation_evidence(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.python_exec")
    errors = importlib.import_module(f"{addon_package}.errors")
    fake = _fake_bpy()
    monkeypatch.setattr(module, "require_blender", lambda: fake)

    with pytest.raises(errors.BridgeError) as caught:
        module.python_execute(
            SimpleNamespace(),
            {
                "code": "bpy.data.objects.append(inputs)\nraise ValueError('boom')",
                "expected_effect": "Append a test value before a deliberate failure",
                "confirm_dangerous": True,
                "inputs": {"name": "partial"},
                "time_limit_seconds": 1.0,
            },
        )

    context = caught.value.context
    assert context["execution_started"] is True
    assert context["mutation_outcome_unknown"] is True
    assert context["verification_required"] is True
    assert context["expected_effect"].startswith("Append a test value")
    assert len(context["script_digest"]) == 16
    assert context["data_counts_before"]["objects"] == 1
    assert context["data_counts_after"]["objects"] == 2


def test_python_registry_requires_every_high_risk_permission(addon_package: str) -> None:
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    tools_module = importlib.import_module(f"{addon_package}.tools")
    registry = registry_module.ToolRegistry()
    tools_module.register_all(registry)

    permissions = {item.value for item in registry.get("python.execute").permissions}

    assert permissions == {
        "EXECUTE_PYTHON",
        "DELETE_OBJECTS",
        "ACCESS_EXTERNAL_FILES",
        "SAVE_PROJECT",
    }


def test_executor_tracks_failed_python_as_a_possible_mutation(
    addon_package: str,
) -> None:
    executor_module = importlib.import_module(f"{addon_package}.executor")
    errors = importlib.import_module(f"{addon_package}.errors")
    state_module = importlib.import_module(f"{addon_package}.state")

    class Checkpoints:
        def __init__(self) -> None:
            self.labels: list[str] = []

        def before_modification(self, tool_name: str) -> bool:
            assert tool_name == "python.execute"
            return True

        def after_modification(self, tool_name: str) -> None:
            self.labels.append(tool_name)

    def fail_handler(context: object, params: object) -> None:
        del context, params
        raise errors.BridgeError(
            errors.ErrorCode.OPERATION_FAILED,
            "Script failed after execution began.",
            {
                "execution_started": True,
                "script_digest": "0123456789abcdef",
                "objects_added": {
                    "items": ["PartialObject"],
                    "count": 1,
                    "truncated": False,
                },
            },
        )

    registry = SimpleNamespace(
        prepare=lambda *args, **kwargs: SimpleNamespace(
            modifies=True,
            automatic_checkpoint=True,
            handler=fail_handler,
        )
    )
    checkpoints = Checkpoints()
    state = state_module.BridgeState()
    executor = executor_module.MainThreadExecutor(
        command_queue=SimpleNamespace(),
        registry=registry,
        state=state,
        permissions=SimpleNamespace(),
        checkpoints=checkpoints,
    )

    with pytest.raises(errors.BridgeError):
        executor.dispatch(
            "python.execute",
            {
                "expected_effect": "Create one object",
                "code": "result = None",
            },
        )

    assert checkpoints.labels == ["python.execute (failed; verify state)"]
    record = state.history(1)[0]
    assert record["description"] == (
        "Python failed; verify state [0123456789abcdef]: Create one object"
    )
    assert record["affected_objects"] == ["PartialObject"]
