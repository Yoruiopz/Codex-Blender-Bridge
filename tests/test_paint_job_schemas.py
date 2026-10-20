from __future__ import annotations

import asyncio
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.core import CoreTools
from mcp_server.tools.image_paint import BrushStroke, ImagePaintTools


@pytest.mark.parametrize("value", [True, 0, 301, float("inf"), "60"])
def test_mcp_deadline_schema_rejects_unbounded_or_coerced_values(value):
    schema = get_type_hints(ImagePaintTools.image_paint_job_start, include_extras=True)["time_limit_seconds"]
    with pytest.raises(ValidationError):
        TypeAdapter(schema).validate_python(value)


@pytest.mark.parametrize("function,key,invalid", [(CoreTools.jobs_list, "limit", True),
    (CoreTools.jobs_list, "limit", 33), (CoreTools.jobs_inspect, "job_id", "missing"),
    (CoreTools.jobs_cancel, "job_id", "job_" + "x" * 32)])
def test_mcp_control_schemas_are_typed_and_bounded(function, key, invalid):
    with pytest.raises(ValidationError):
        TypeAdapter(get_type_hints(function, include_extras=True)[key]).validate_python(invalid)


def test_wrappers_forward_only_structured_job_parameters():
    class Registry:
        async def call(self, method, params):
            return {"method": method, "params": params}
    async def run():
        registry = Registry()
        brush = BrushStroke(points=[[.5, .5]], radius_pixels=2., color=[1., 0., 0., 1.])
        paint = ImagePaintTools()
        paint.registry = registry
        result = await paint.image_paint_job_start("Source", "Version", [brush], 45.)
        assert result == {"method": "image.paint_job_start", "params": {"image_name": "Source", "new_name": "Version",
                           "strokes": [brush.model_dump()], "time_limit_seconds": 45.}}
        core = CoreTools(registry)
        job_id = "job_" + "a" * 32
        assert (await core.jobs_inspect(job_id))["params"] == {"job_id": job_id}
        assert (await core.jobs_cancel(job_id))["params"] == {"job_id": job_id}
        assert (await core.jobs_list(3))["params"] == {"limit": 3}
    asyncio.run(run())
