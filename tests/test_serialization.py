from __future__ import annotations

import importlib
import math
from dataclasses import dataclass

import pytest


def test_json_serialization_is_bounded_and_deterministic(addon_package: str) -> None:
    serialization = importlib.import_module(f"{addon_package}.serialization")

    value = {"z": [1, 2, 3], "a": math.inf}
    encoded = serialization.dumps(value)

    assert encoded == '{"a":null,"z":[1,2,3]}'
    assert serialization.loads(encoded) == {"a": None, "z": [1, 2, 3]}


def test_json_conversion_supports_dataclasses_and_paths(
    addon_package: str, tmp_path
) -> None:
    serialization = importlib.import_module(f"{addon_package}.serialization")

    @dataclass
    class Example:
        path: object
        enabled: bool

    result = serialization.to_jsonable(Example(path=tmp_path, enabled=True))

    assert result == {"path": str(tmp_path), "enabled": True}


def test_json_conversion_marks_truncated_sequences(addon_package: str) -> None:
    serialization = importlib.import_module(f"{addon_package}.serialization")

    result = serialization.to_jsonable([1, 2, 3], max_items=2)

    assert result == [1, 2, {"__truncated__": True, "total": 3}]


def test_json_exponent_overflow_is_rejected(addon_package: str) -> None:
    serialization = importlib.import_module(f"{addon_package}.serialization")

    with pytest.raises(ValueError, match="Non-finite"):
        serialization.loads('{"scale":1e309}')
