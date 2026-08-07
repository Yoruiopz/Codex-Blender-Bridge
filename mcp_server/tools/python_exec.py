"""Last-resort, explicitly consent-gated Blender Python wrapper."""

from __future__ import annotations

from typing import Any

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

PYTHON_TOOL_NAMES = ("python.execute",)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return (
        remote_tool(
            "python.execute",
            toolset="python",
            description=(
                "Run acknowledged Blender Python as a super-permission last resort."
            ),
            modifying=True,
            required_permissions=(
                "EXECUTE_PYTHON",
                "DELETE_OBJECTS",
                "ACCESS_EXTERNAL_FILES",
                "SAVE_PROJECT",
            ),
        ),
    )


class PythonTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def python_execute(
        self,
        code: str,
        expected_effect: str,
        confirm_dangerous: bool = False,
        inputs: dict[str, Any] | None = None,
        time_limit_seconds: float = 5.0,
    ) -> Any:
        """Run Blender Python after acknowledgement and every high-risk permission gate."""

        return await self.registry.call(
            "python.execute",
            params(
                code=code,
                expected_effect=expected_effect,
                confirm_dangerous=confirm_dangerous,
                inputs=inputs,
                time_limit_seconds=time_limit_seconds,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return (
            MCPToolBinding(
                "python.execute",
                self.python_execute,
                self.python_execute.__doc__ or "",
            ),
        )


__all__ = ["PYTHON_TOOL_NAMES", "PythonTools", "load_definitions"]
