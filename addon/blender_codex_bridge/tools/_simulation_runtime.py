"""Noncreating runtime-storage prerequisites for the private cloth replay.

This module grants no mutation authority and is not a complete settings reader.
Stored runtime settings require a separate complete value/preservation contract.
In particular, it never resolves a bundled runtime pointer to test its absence.
"""
from __future__ import annotations

from inspect import getattr_static
from types import MethodDescriptorType
from typing import Any

from ..errors import BridgeError, ErrorCode

BUILDS = {
    b"62c1db4208e8": ((4, 5, 14), "USER"),
    b"d13f752e3b9c": ((5, 2, 2), "SYSTEM"),
}
# These are bundled declarations, not arbitrary runtime-extension admission.
DECLARATIONS = {
    "Scene": (("cycles", "POINTER", "CyclesRenderSettings"),
              ("cycles_curves", "POINTER", "CyclesCurveRenderSettings")),
    "ViewLayer": (("cycles", "POINTER", "CyclesRenderLayerSettings"),),
    "Mesh": (("cycles", "POINTER", "CyclesMeshSettings"),),
    "Object": (("cycles", "POINTER", "CyclesObjectSettings"),
               ("selection_sets", "COLLECTION", "SelectionSet"),
               ("active_selection_set", "INT", None)),
}
MAX_PROPERTIES = 512


def refused(reason: str, **facts: Any) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED,
                       "Cloth runtime-storage prerequisite is not satisfied.",
                       {"reason": reason, "runtime_getter_invoked": False,
                        "stored_runtime_preservation_qualified": False, **facts})


def profile(bpy: Any) -> tuple[Any, ...]:
    build = bpy.app.build_hash
    row = BUILDS.get(build) if type(build) is bytes else None
    if row is None or tuple(bpy.app.version) != row[0]:
        raise refused("UNREVIEWED_BUILD")
    return build.decode("ascii"), row[0], row[1]


def _bounded(items: Any, maximum: int) -> tuple[Any, ...]:
    # Native RNA collections provide len before iteration; never eagerly copy
    # an oversized collection simply to discover that it exceeds the budget.
    size = len(items)
    if type(size) is not int or not 0 <= size <= maximum:
        raise refused("DESCRIPTOR_BUDGET")
    result = tuple(items)
    if len(result) != size:
        raise refused("DESCRIPTOR_COLLECTION_CHANGED")
    return result


def _signature(prop: Any) -> tuple[Any, ...]:
    kind = prop.type
    if kind not in {"BOOLEAN", "INT", "FLOAT", "ENUM", "STRING", "POINTER", "COLLECTION"}:
        raise refused("UNKNOWN_PROPERTY_KIND")
    array = prop.array_length if kind in {"BOOLEAN", "INT", "FLOAT"} else None
    if array is not None and (type(array) is not int or not 0 <= array <= 65536):
        raise refused("ARRAY_METADATA_BUDGET")
    fixed = prop.fixed_type.identifier if kind in {"POINTER", "COLLECTION"} else None
    pointer = prop.as_pointer()
    if type(pointer) is not int or pointer <= 0:
        raise refused("INVALID_DESCRIPTOR_IDENTITY")
    return (prop.identifier, kind, prop.is_runtime, prop.is_readonly,
            prop.is_registered, array, fixed, pointer)


def _presence_descriptor(bpy: Any, canonical: Any) -> Any:
    base = bpy.types.bpy_struct
    if type(base) is not type or not issubclass(canonical, base):
        raise refused("NONCANONICAL_METHOD_BASE")
    method = vars(base).get("is_property_set")
    if (type(method) is not MethodDescriptorType or method.__objclass__ is not base
            or getattr_static(canonical, "is_property_set", None) is not method):
        raise refused("REPLACED_PRESENCE_METHOD")
    return method


def absent_runtime(bpy: Any, owner: Any) -> tuple[Any, ...]:
    """Return a stable metadata/presence receipt, or refuse before getters.

    ghost=False is important: ghost/default storage also counts as present.
    Exact reviewed C implementations perform a noncreating USER (4.5) or SYSTEM
    (5.2) lookup. This does not admit malformed/present storage or read its value.
    """
    build = profile(bpy)
    rna = owner.bl_rna
    name = rna.identifier
    allowed = DECLARATIONS.get(name)
    canonical = getattr(bpy.types, name, None)
    if (allowed is None or canonical is None or type(owner) is not canonical
            or canonical.bl_rna.as_pointer() != rna.as_pointer()):
        raise refused("NONCANONICAL_OWNER")
    method = _presence_descriptor(bpy, canonical)
    props = _bounded(rna.properties, MAX_PROPERTIES)
    before = tuple(_signature(prop) for prop in props)
    if len({row[0] for row in before}) != len(before):
        raise refused("DUPLICATE_PROPERTY_IDENTIFIER")
    declarations = {key: (kind, fixed) for key, kind, fixed in allowed}
    runtime = []
    for prop, row in zip(props, before, strict=True):
        if row[2] is not True:
            continue
        expected = declarations.get(row[0])
        if (expected is None or (row[1], row[6]) != expected
                or row[3] is not (row[0] != "active_selection_set")
                or row[4] is not False or row[5] not in (None, 0)):
            raise refused("UNKNOWN_RUNTIME_DECLARATION", owner_type=name, property=row[0])
        runtime.append(prop.identifier)
    if set(runtime) != set(declarations):
        raise refused("MISSING_BUNDLED_DECLARATION", owner_type=name)
    presence = []
    for key in runtime:
        present = method(owner, key, ghost=False)
        if type(present) is not bool or present:
            raise refused("STORED_RUNTIME_REQUIRES_VALUE_READER", owner_type=name, property=key)
        presence.append((key, False))
    if (_presence_descriptor(bpy, canonical) is not method
            or tuple(_signature(prop) for prop in _bounded(rna.properties, MAX_PROPERTIES)) != before
            or profile(bpy) != build):
        raise refused("METADATA_CHANGED_DURING_PRESENCE_READ")
    return build, rna.as_pointer(), before, tuple(presence)
