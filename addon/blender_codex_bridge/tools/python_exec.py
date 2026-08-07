"""Explicitly armed Blender-Python escape hatch for unsupported structured work.

This is deliberately a last-resort tool.  It runs on Blender's main thread, is
disabled by its toolset and four explicit high-risk permissions at startup, and
applies a small accident-prevention policy.  The policy is not advertised as a
security sandbox; enabling Python means trusting the caller with Blender and the
permissions granted to the process.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib
import math
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..serialization import to_jsonable
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, float_param, require_blender

_MAX_CODE_BYTES = 64 * 1024
_MAX_AST_NODES = 8_000
_MAX_OUTPUT_BYTES = 64 * 1024
_MAX_RESULT_BYTES = 256 * 1024
_MAX_RESULT_ITEMS = 4_000
_MAX_RESULT_DEPTH = 8
_MAX_RESULT_INTEGER_DIGITS = 4_000
_MAX_INPUT_ITEMS = 1_000
_ALLOWED_IMPORT_ROOTS = frozenset(
    {
        "bmesh",
        "bpy",
        "math",
        "mathutils",
    }
)
_DENIED_NAMES = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "exit",
        "help",
        "input",
        "open",
        "quit",
    }
)
_DENIED_ATTRIBUTES = frozenset(
    {
        "as_module",
        "builtins",
        "ctypes",
        "execfile",
        "importlib",
        "modules",
        "open",
        "os",
        "path_open",
        "pathlib",
        "popen",
        "python_file_run",
        "shutil",
        "socket",
        "subprocess",
        "sys",
        "system",
        "url_open",
    }
)


class _ExecutionDeadline(BaseException):
    """Raised by the trace hook so ordinary ``except Exception`` cannot hide it."""


class _ResultBudgetExceeded(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _BoundedTextBuffer:
    def __init__(self, limit: int = _MAX_OUTPUT_BYTES) -> None:
        self._limit = limit
        self._parts: list[str] = []
        self._size = 0
        self.truncated = False

    def write(self, value: object) -> int:
        text = str(value)
        encoded = text.encode("utf-8", errors="replace")
        remaining = self._limit - self._size
        if remaining <= 0:
            self.truncated = self.truncated or bool(encoded)
            return len(text)
        kept = encoded[:remaining]
        self._parts.append(kept.decode("utf-8", errors="ignore"))
        self._size += len(kept)
        self.truncated = self.truncated or len(encoded) > len(kept)
        return len(text)

    def flush(self) -> None:
        return None

    def getvalue(self) -> str:
        return "".join(self._parts)


class _ScriptPolicy(ast.NodeVisitor):
    """Reject obvious filesystem, process, network, and introspection escapes."""

    def __init__(self) -> None:
        self.node_count = 0

    def generic_visit(self, node: ast.AST) -> None:
        self.node_count += 1
        if self.node_count > _MAX_AST_NODES:
            raise invalid_argument(
                "Python script is too complex.",
                maximum_ast_nodes=_MAX_AST_NODES,
            )
        super().generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            _validate_import_name(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            raise invalid_argument("Relative imports are not allowed in Blender Python.")
        _validate_import_name(node.module or "")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _DENIED_NAMES or node.id.startswith("__"):
            raise invalid_argument(
                f"Python name '{node.id}' is not allowed by the bridge policy.",
                denied_name=node.id,
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_") or node.attr in _DENIED_ATTRIBUTES:
            raise invalid_argument(
                "Private, process, network, and interpreter attribute access is not allowed "
                "by the bridge policy.",
                denied_attribute=node.attr,
            )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        value = node.value
        if isinstance(value, float) and not math.isfinite(value):
            raise invalid_argument("Python numeric constants must be finite.")
        if isinstance(value, str) and value.startswith("__") and value.endswith("__"):
            raise invalid_argument(
                "Double-underscore introspection strings are not allowed by the bridge policy."
            )
        self.generic_visit(node)

    def _visit_try(self, node: Any) -> None:
        # CPython disables a trace hook after the hook raises.  A bare handler or
        # user-authored finally block could therefore swallow the cooperative
        # deadline and continue forever on Blender's main thread without tracing.
        if node.finalbody:
            raise invalid_argument(
                "Python try/finally cleanup is not allowed by the bridge deadline policy."
            )
        for handler in node.handlers:
            if handler.type is None:
                raise invalid_argument(
                    "Bare 'except:' handlers are not allowed by the bridge deadline policy."
                )
            caught_names = {
                item.id
                for item in ast.walk(handler.type)
                if isinstance(item, ast.Name)
            }
            if "BaseException" in caught_names:
                raise invalid_argument(
                    "Catching BaseException is not allowed by the bridge deadline policy."
                )
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_try(node)

    def visit_TryStar(self, node: Any) -> None:
        self._visit_try(node)


def _validate_import_name(name: str) -> None:
    root = name.partition(".")[0]
    if root not in _ALLOWED_IMPORT_ROOTS:
        raise invalid_argument(
            f"Python import '{name}' is not allowed.",
            allowed_import_roots=sorted(_ALLOWED_IMPORT_ROOTS),
        )


def _validate_script(code: str) -> Any:
    try:
        tree = ast.parse(code, filename="<blender-codex-bridge>", mode="exec")
    except SyntaxError as exc:
        raise invalid_argument(
            "Python script has invalid syntax.",
            line=exc.lineno,
            offset=exc.offset,
            detail=(exc.msg or "syntax error")[:200],
        ) from exc
    _ScriptPolicy().visit(tree)
    return compile(tree, "<blender-codex-bridge>", "exec", dont_inherit=True)


def _safe_import(
    name: str,
    globals_: Mapping[str, Any] | None = None,
    locals_: Mapping[str, Any] | None = None,
    fromlist: tuple[str, ...] | list[str] = (),
    level: int = 0,
) -> Any:
    del globals_, locals_
    if level:
        raise ImportError("Relative imports are disabled")
    _validate_import_name(name)
    module = importlib.import_module(name)
    if fromlist:
        return module
    return importlib.import_module(name.partition(".")[0])


def _safe_builtins(output: _BoundedTextBuffer) -> dict[str, Any]:
    def safe_print(*values: object, sep: str = " ", end: str = "\n") -> None:
        if not isinstance(sep, str) or not isinstance(end, str):
            raise TypeError("print sep and end must be strings")
        output.write(sep.join(str(value) for value in values) + end)

    return {
        "__import__": _safe_import,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "Exception": Exception,
        "float": float,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "print": safe_print,
        "range": range,
        "reversed": reversed,
        "round": round,
        "RuntimeError": RuntimeError,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "ValueError": ValueError,
        "zip": zip,
    }


def _data_snapshot(bpy: Any) -> tuple[dict[str, int], set[str]]:
    data = bpy.data
    counts = {
        name: len(getattr(data, name, ()))
        for name in (
            "actions",
            "armatures",
            "collections",
            "images",
            "materials",
            "meshes",
            "node_groups",
            "objects",
        )
    }
    objects = getattr(data, "objects", ())
    return counts, {str(getattr(item, "name", "")) for item in objects}


def _bounded_names(values: set[str], *, limit: int = 100) -> dict[str, Any]:
    ordered = sorted(value for value in values if value)
    return {
        "items": ordered[:limit],
        "count": len(ordered),
        "truncated": len(ordered) > limit,
    }


def _execution_evidence(
    *,
    before_counts: Mapping[str, int],
    before_objects: set[str],
    after_counts: Mapping[str, int],
    after_objects: set[str],
) -> dict[str, Any]:
    return {
        "data_counts_before": dict(before_counts),
        "data_counts_after": dict(after_counts),
        "objects_added": _bounded_names(after_objects - before_objects),
        "objects_removed": _bounded_names(before_objects - after_objects),
    }


def _json_string_size(value: str, *, limit: int | None = None) -> int:
    size = 2  # surrounding quotes
    for character in value:
        codepoint = ord(character)
        if character in {'"', "\\"} or character in {"\b", "\f", "\n", "\r", "\t"}:
            size += 2
        elif codepoint < 0x20:
            size += 6
        else:
            size += len(character.encode("utf-8"))
        if limit is not None and size > limit:
            return size
    return size


def _bounded_json_size(value: Any, *, limit: int) -> int:
    """Return exact compact-JSON bytes, stopping as soon as ``limit`` is exceeded."""

    if value is None:
        return 4
    if value is True:
        return 4
    if value is False:
        return 5
    if isinstance(value, int):
        return len(str(value))
    if isinstance(value, float):
        return len(repr(value))
    if isinstance(value, str):
        return _json_string_size(value, limit=limit)
    if isinstance(value, Mapping):
        size = 2
        for index, (key, item) in enumerate(value.items()):
            if index:
                size += 1
            size += _json_string_size(str(key), limit=max(0, limit - size)) + 1
            if size > limit:
                return size
            size += _bounded_json_size(item, limit=max(0, limit - size))
            if size > limit:
                return size
        return size
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        size = 2
        for index, item in enumerate(value):
            if index:
                size += 1
            size += _bounded_json_size(item, limit=max(0, limit - size))
            if size > limit:
                return size
        return size
    # ``to_jsonable`` should already have removed every other value type.
    return _json_string_size(repr(value))


class _ResultConverter:
    """Convert script results without expanding shared or cyclic object graphs."""

    def __init__(self) -> None:
        self.item_count = 0
        self.scalar_bytes = 0
        self.seen_containers: set[int] = set()

    def _claim_item(self) -> None:
        self.item_count += 1
        if self.item_count > _MAX_RESULT_ITEMS:
            raise _ResultBudgetExceeded("global_item_budget")

    def _string(self, value: str) -> str:
        remaining = _MAX_RESULT_BYTES - self.scalar_bytes
        size = _json_string_size(value, limit=max(0, remaining))
        self._claim_scalar_bytes(size)
        return value

    def _claim_scalar_bytes(self, size: int) -> None:
        self.scalar_bytes += size
        if self.scalar_bytes > _MAX_RESULT_BYTES:
            raise _ResultBudgetExceeded("serialized_byte_budget")

    def _integer_text(self, value: int) -> str:
        estimated_digits = max(1, int(value.bit_length() * math.log10(2)) + 1)
        if estimated_digits > _MAX_RESULT_INTEGER_DIGITS:
            raise _ResultBudgetExceeded("integer_digit_budget")
        try:
            return str(value)
        except (ValueError, OverflowError) as exc:
            raise _ResultBudgetExceeded("integer_digit_budget") from exc

    def _enter_container(self, value: Any) -> None:
        identity = id(value)
        if identity in self.seen_containers:
            raise _ResultBudgetExceeded("cyclic_or_shared_reference")
        self.seen_containers.add(identity)

    def _mapping_key(self, value: Any) -> str:
        if value is None:
            return self._string("None")
        if isinstance(value, bool):
            return self._string("True" if value else "False")
        if isinstance(value, str):
            return self._string(value)
        if isinstance(value, int):
            return self._string(self._integer_text(value))
        if isinstance(value, float) and math.isfinite(value):
            return self._string(str(value))
        raise _ResultBudgetExceeded("unsupported_mapping_key")

    def convert(self, value: Any, *, depth: int = 0) -> Any:
        self._claim_item()
        if depth > _MAX_RESULT_DEPTH:
            raise _ResultBudgetExceeded("maximum_depth")
        if value is None:
            self._claim_scalar_bytes(4)
            return value
        if isinstance(value, bool):
            self._claim_scalar_bytes(4 if value else 5)
            return value
        if isinstance(value, int):
            text = self._integer_text(value)
            self._claim_scalar_bytes(len(text))
            return value
        if isinstance(value, float):
            self._claim_scalar_bytes(4 if not math.isfinite(value) else len(repr(value)))
            return value if math.isfinite(value) else None
        if isinstance(value, str):
            return self._string(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            if len(value) > _MAX_RESULT_BYTES:
                raise _ResultBudgetExceeded("serialized_byte_budget")
            return self._string(bytes(value).decode("utf-8", errors="replace"))
        if isinstance(value, Enum):
            return self.convert(value.value, depth=depth + 1)
        if isinstance(value, (datetime, date, Path)):
            return self._string(str(value) if isinstance(value, Path) else value.isoformat())

        type_name = type(value).__name__
        if type_name == "Matrix":
            try:
                matrix = [[float(component) for component in row] for row in value]
            except (TypeError, ValueError) as exc:
                raise _ResultBudgetExceeded("unsupported_result_type") from exc
            return self.convert(matrix, depth=depth + 1)
        if type_name in {"Vector", "Euler", "Quaternion", "Color"}:
            try:
                components = [float(component) for component in value]
            except (TypeError, ValueError) as exc:
                raise _ResultBudgetExceeded("unsupported_result_type") from exc
            return self.convert(components, depth=depth + 1)

        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            self._enter_container(value)
            return {
                self._string(field.name): self.convert(
                    getattr(value, field.name), depth=depth + 1
                )
                for field in dataclasses.fields(value)
            }
        if isinstance(value, Mapping):
            self._enter_container(value)
            result: dict[str, Any] = {}
            for key, item in value.items():
                self._claim_item()
                clean_key = self._mapping_key(key)
                if clean_key in result:
                    raise _ResultBudgetExceeded("duplicate_stringified_mapping_key")
                result[clean_key] = self.convert(item, depth=depth + 1)
            return result
        if isinstance(value, (set, frozenset)):
            self._enter_container(value)
            return [self.convert(item, depth=depth + 1) for item in value]
        if isinstance(value, Sequence):
            self._enter_container(value)
            return [self.convert(item, depth=depth + 1) for item in value]

        name = getattr(value, "name", None)
        if isinstance(name, str):
            return self._string(name)
        raise _ResultBudgetExceeded("unsupported_result_type")


def _bounded_result(value: Any) -> tuple[Any, bool, int | None]:
    def placeholder(reason: str) -> tuple[Any, bool, int | None]:
        return (
            {
                "__truncated__": True,
                "reason": reason,
                "original_type": type(value).__name__,
                "maximum_bytes": _MAX_RESULT_BYTES,
                "maximum_items": _MAX_RESULT_ITEMS,
            },
            True,
            None,
        )

    try:
        converted = _ResultConverter().convert(value)
    except _ResultBudgetExceeded as exc:
        return placeholder(exc.reason)
    except BaseException:
        return placeholder("result_conversion_failed")
    try:
        size = _bounded_json_size(converted, limit=_MAX_RESULT_BYTES)
    except BaseException:
        return placeholder("result_size_check_failed")
    if size <= _MAX_RESULT_BYTES:
        return converted, False, size
    return (
        {
            "__truncated__": True,
            "reason": "Python result exceeded the dedicated response budget.",
            "original_type": type(converted).__name__,
            "maximum_bytes": _MAX_RESULT_BYTES,
            "maximum_items": _MAX_RESULT_ITEMS,
        },
        True,
        None,
    )


def python_execute(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    """Run one explicitly acknowledged, bounded Blender-Python script."""

    del context
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise invalid_argument("A non-empty Python 'code' string is required.", parameter="code")
    code_bytes = code.encode("utf-8")
    if len(code_bytes) > _MAX_CODE_BYTES:
        raise invalid_argument(
            "Python script exceeds the bridge size limit.",
            maximum_bytes=_MAX_CODE_BYTES,
            actual_bytes=len(code_bytes),
        )
    expected_effect = params.get("expected_effect")
    if not isinstance(expected_effect, str) or not expected_effect.strip():
        raise invalid_argument(
            "A non-empty 'expected_effect' is required for the audit history.",
            parameter="expected_effect",
        )
    if len(expected_effect) > 500:
        raise invalid_argument("'expected_effect' must be at most 500 characters.")
    if not bool_param(params, "confirm_dangerous", False):
        raise invalid_argument(
            "Set 'confirm_dangerous' to true to acknowledge full Blender-Python access."
        )
    time_limit = float_param(
        params,
        "time_limit_seconds",
        5.0,
        minimum=0.1,
        maximum=30.0,
    )
    inputs = params.get("inputs", {})
    if not isinstance(inputs, Mapping):
        raise invalid_argument("'inputs' must be a JSON object.", parameter="inputs")
    if len(inputs) > _MAX_INPUT_ITEMS:
        raise invalid_argument(
            "'inputs' contains too many entries.",
            maximum_items=_MAX_INPUT_ITEMS,
        )

    compiled = _validate_script(code)
    bpy = require_blender()
    before_counts, before_objects = _data_snapshot(bpy)
    output = _BoundedTextBuffer()
    namespace: dict[str, Any] = {
        "__builtins__": _safe_builtins(output),
        "__name__": "blender_codex_bridge_script",
        "bpy": bpy,
        "inputs": to_jsonable(dict(inputs), max_depth=8, max_items=_MAX_INPUT_ITEMS),
        "result": None,
    }
    deadline = time.monotonic() + time_limit

    def trace(frame: Any, event: str, arg: Any) -> Any:
        del frame, arg
        if event in {"call", "line"} and time.monotonic() >= deadline:
            raise _ExecutionDeadline()
        return trace

    previous_trace = sys.gettrace()
    started = time.monotonic()
    failure: tuple[ErrorCode, str, dict[str, Any]] | None = None
    try:
        sys.settrace(trace)
        try:
            exec(compiled, namespace, namespace)
        except _ExecutionDeadline:
            failure = (
                ErrorCode.TIMEOUT,
                "Blender Python exceeded its cooperative execution deadline.",
                {
                    "time_limit_seconds": time_limit,
                    "note": "Long-running Blender C operations cannot always be preempted.",
                },
            )
        except BaseException as exc:
            failure = (
                ErrorCode.OPERATION_FAILED,
                "Blender Python script failed.",
                {"exception_type": type(exc).__name__, "detail": str(exc)[:400]},
            )
    finally:
        sys.settrace(previous_trace)

    elapsed_ms = (time.monotonic() - started) * 1000.0
    after_counts, after_objects = _data_snapshot(bpy)
    evidence = _execution_evidence(
        before_counts=before_counts,
        before_objects=before_objects,
        after_counts=after_counts,
        after_objects=after_objects,
    )
    script_digest = hashlib.sha256(code_bytes).hexdigest()[:16]
    if failure is not None:
        code_value, message, detail = failure
        raise BridgeError(
            code_value,
            message,
            {
                **detail,
                **evidence,
                "execution_started": True,
                "script_digest": script_digest,
                "expected_effect": expected_effect.strip(),
                "duration_ms": round(elapsed_ms, 3),
                "stdout": output.getvalue(),
                "stdout_truncated": output.truncated,
                "mutation_outcome_unknown": True,
                "verification_required": True,
            },
        )
    bounded_result, result_truncated, result_bytes = _bounded_result(
        namespace.get("result")
    )
    return {
        "executed": True,
        "script_digest": script_digest,
        "expected_effect": expected_effect.strip(),
        "duration_ms": round(elapsed_ms, 3),
        "result": bounded_result,
        "result_truncated": result_truncated,
        "result_bytes": result_bytes,
        "result_limit_bytes": _MAX_RESULT_BYTES,
        "stdout": output.getvalue(),
        "stdout_truncated": output.truncated,
        **evidence,
        "verification_required": True,
        "policy": {
            "allowed_import_roots": sorted(_ALLOWED_IMPORT_ROOTS),
            "cooperative_deadline_seconds": time_limit,
            "not_a_security_sandbox": True,
        },
    }


def register_tools(registry: ToolRegistry) -> None:
    registry.register(
        "python.execute",
        python_execute,
        permissions=(
            Permission.EXECUTE_PYTHON,
            Permission.DELETE_OBJECTS,
            Permission.ACCESS_EXTERNAL_FILES,
            Permission.SAVE_PROJECT,
        ),
        toolset="python",
        modifies=True,
        description=(
            "Run explicitly acknowledged Blender Python as a last resort; dangerous, "
            "disabled by default, audited, requires all high-risk permissions, and "
            "always requires verification."
        ),
    )


__all__ = ["python_execute", "register_tools"]
