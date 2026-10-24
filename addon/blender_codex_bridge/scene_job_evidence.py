"""Strict, detached Scene-job receipts; no RNA getters or repr fallbacks."""

from __future__ import annotations

import json
import math

from .errors import BridgeError, ErrorCode


def plain(value, *, field="evidence", byte_limit=65536, item_limit=4096, depth_limit=8):
    remaining = [item_limit, byte_limit]
    seen = set()

    def visit(item, depth=0):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > depth_limit:
            raise ValueError
        kind = type(item)
        if item is None or kind is bool:
            return item
        if kind is int:
            if item.bit_length() > 4096:
                raise ValueError
            remaining[1] -= 2+item.bit_length()//3
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError
            remaining[1] -= 32
        elif kind is str:
            if len(item) > 4096:
                raise ValueError
            remaining[1] -= len(item.encode("utf-8"))
        elif kind in {dict, list, tuple}:
            if id(item) in seen or len(item) > remaining[0]:
                raise ValueError
            seen.add(id(item))
            if kind is dict:
                if any(type(key) is not str for key in item):
                    raise ValueError
                return {visit(key, depth+1): visit(value, depth+1) for key, value in item.items()}
            return [visit(value, depth+1) for value in item]
        else:
            raise ValueError
        if remaining[1] < 0:
            raise ValueError
        return item

    try:
        result = visit(value)
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > byte_limit:
            raise ValueError
        return result
    except (ValueError, UnicodeError, OverflowError) as cause:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Scene-job report is not bounded plain evidence.",
                          {"reason": "SCENE_JOB_EVIDENCE_INVALID", "field": field,
                           "verification_required": True}) from cause


def progress(value):
    result = plain(value, field="progress", byte_limit=8192, item_limit=512)
    if (type(result) is not dict or type(result.get("phase")) is not str or not result["phase"]
            or len(result["phase"]) > 128 or type(result.get("completed")) is not int
            or type(result.get("total")) is not int or not 0 <= result["completed"] <= result["total"]):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Scene-job progress has no bounded phase/count report.",
                          {"reason": "SCENE_JOB_EVIDENCE_INVALID", "field": "progress"})
    return result


def phase(value):
    if type(value) is not str or not value or len(value) > 128:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Scene-job phase has no bounded literal name.",
                          {"reason": "SCENE_JOB_EVIDENCE_INVALID", "field": "phase"})
    return value
