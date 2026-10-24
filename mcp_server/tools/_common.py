"""Shared helpers for explicit MCP tool wrappers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import Field, StrictFloat

RotationQuaternion = Annotated[
    list[Annotated[StrictFloat, Field(allow_inf_nan=False)]],
    Field(min_length=4, max_length=4, strict=True),
]


def params(**values: Any) -> dict[str, Any]:
    """Omit optional values so Blender-side defaults remain authoritative."""

    return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class MCPToolBinding:
    name: str
    handler: Callable[..., Any]
    description: str
