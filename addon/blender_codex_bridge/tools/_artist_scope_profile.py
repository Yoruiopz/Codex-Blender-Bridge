"""Fail-closed host profile for the first protected Object-channel workflow.

This is a gate for bridge-owned writes, not a sandbox for arbitrary installed
Python. Message-bus subscriptions, timers, monkeypatches and other processes are
not enumerable here. Native ``user_map`` remains a non-preemptive Blender scan;
these limits bound our inventory and inherited collection traversal, not its
internal allocation or blocking time. No permission/cancellation provider runs
after the optional initial ``check`` callback in ``require_profile``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode

MAX_OBJECTS = 256
MAX_COLLECTIONS = 256
MAX_SCENES = 16
MAX_IDS = 1024
MAX_ID_FAMILIES = 96
MAX_RNA_PROPERTIES = 256
MAX_COLLECTION_LINKS = 512
MAX_OWNING_COLLECTIONS = 32
MAX_COMPONENTS = 100
MAX_AFFECTED_OBJECTS = 32
MAX_GEOMETRY_ELEMENTS = 32768
HANDLER_LISTS = ("depsgraph_update_pre", "depsgraph_update_post", "frame_change_pre", "frame_change_post")
IMPLICIT_MODIFIERS = frozenset({
    "COLLISION", "CLOTH", "SOFT_BODY", "FLUID", "DYNAMIC_PAINT", "PARTICLE_SYSTEM",
    "PARTICLE_INSTANCE", "EXPLODE", "OCEAN", "NODES",
})
# Blender's bundled bone-selection-set operator registers this writable UI
# index in clean factory startup. It is never read by this static prop profile
# or its Object snapshot, including if another host script replaces its getter.
IGNORED_OBJECT_RUNTIME = frozenset({"active_selection_set"})


def _refuse(message: str, **details: Any) -> None:
    raise BridgeError(ErrorCode.NOT_IMPLEMENTED, message, {"artist_scope_profile_complete": False, **details})


def _bounded(values: Iterable[Any], maximum: int, label: str) -> list[Any]:
    result = list(islice(values, maximum + 1))
    if len(result) > maximum:
        _refuse("Protected transform profile exceeds its bounded inventory.", inventory=label, maximum=maximum)
    return result


def _rna(owner: Any, *, reads: frozenset[str] | None = None) -> frozenset[str]:
    """Inspect descriptors before reading values; runtime getters are untrusted."""
    rna = getattr(owner, "bl_rna", None)
    if rna is None:
        _refuse("Protected transform profile requires native RNA descriptors.")
    properties = _bounded(rna.properties, MAX_RNA_PROPERTIES, "RNA properties")
    for prop in properties:
        if getattr(rna, "identifier", None) == "Object" and prop.identifier in IGNORED_OBJECT_RUNTIME:
            continue
        read = (not getattr(prop, "is_readonly", False)) if reads is None else prop.identifier in reads
        if getattr(prop, "is_runtime", False) and read:
            _refuse("Runtime RNA properties require a separate protected-workflow review.", property=prop.identifier,
                    owner_type=getattr(rna, "identifier", None))
    ignored = IGNORED_OBJECT_RUNTIME if getattr(rna, "identifier", None) == "Object" else frozenset()
    return frozenset(prop.identifier for prop in properties if prop.identifier not in ignored)


def _key(owner: Any) -> int:
    pointer = getattr(owner, "as_pointer", None)
    return int(pointer()) if pointer is not None else id(owner)


def _field(owner: Any, fields: frozenset[str], name: str, default: Any = None) -> Any:
    return getattr(owner, name) if name in fields else default


def _inventory(bpy: Any) -> tuple[list[Any], list[Any], list[Any]]:
    data = bpy.data
    _rna(data)
    families = [prop for prop in _bounded(data.bl_rna.properties, MAX_RNA_PROPERTIES, "BlendData RNA properties")
                if getattr(prop, "type", None) == "COLLECTION"]
    if len(families) > MAX_ID_FAMILIES:
        _refuse("Protected transform profile exceeds its ID-family budget.")
    identifiers: dict[int, Any] = {}
    by_family: dict[str, list[Any]] = {}
    for prop in families:
        maximum = {"objects": MAX_OBJECTS, "collections": MAX_COLLECTIONS, "scenes": MAX_SCENES}.get(prop.identifier, MAX_IDS)
        values = _bounded(getattr(data, prop.identifier), min(maximum, MAX_IDS-len(identifiers)), prop.identifier)
        by_family[prop.identifier] = values
        for owner in values:
            identifiers[_key(owner)] = owner
    if not {"objects", "collections", "scenes"}.issubset(by_family):
        _refuse("Protected transform profile cannot inspect required native ID families.")
    pending = list(identifiers.values())
    scanned: set[int] = set()
    while pending:
        owner = pending.pop()
        token = _key(owner)
        if token in scanned:
            continue
        if len(scanned) >= MAX_IDS:
            _refuse("Protected transform profile exceeds its total ID budget.", maximum=MAX_IDS)
        scanned.add(token)
        fields = _rna(owner, reads=frozenset({"animation_data", "node_tree", "shape_keys", "collection", "data", "users_scene", "users_collection"}))
        animation = _field(owner, fields, "animation_data")
        if animation is not None:
            animation_fields = _rna(animation)
            # This first profile intentionally refuses all drivers, including
            # native aggregations. Opaque expressions and custom RNA paths cannot
            # hide dependencies outside the Object-reference closure.
            if _bounded(_field(animation, animation_fields, "drivers", ()), 0, "drivers"):
                _refuse("Drivers require a separately reviewed protected transform profile.")
        for name in ("node_tree", "shape_keys", "collection", "data"):
            embedded = _field(owner, fields, name)
            if embedded is not None:
                pending.append(embedded)
                if len(pending)+len(scanned) > MAX_IDS*5:
                    _refuse("Protected transform profile exceeds its embedded-ID traversal budget.")
    return by_family["objects"], by_family["collections"], by_family["scenes"]


def pre_closure(bpy: Any) -> None:
    """Bound global ownership inputs before calling the inherited Object closure."""
    for name in HANDLER_LISTS:
        if _bounded(getattr(bpy.app.handlers, name, ()), 0, name):
            _refuse("Installed dependency/frame handlers require a separate protected-workflow review.", handler_list=name)
    objects, collections, scenes = _inventory(bpy)
    scene_keys = {_key(scene) for scene in scenes}
    roots = [scene.collection for scene in scenes]
    all_collections = {_key(collection): collection for collection in (*collections, *roots)}
    links = 0
    for collection in all_collections.values():
        _rna(collection, reads=frozenset({"children", "users", "use_fake_user", "library", "override_library", "is_editable"}))
        children = _bounded(collection.children, MAX_COLLECTIONS, "collection children")
        links += len(children)
        if links > MAX_COLLECTION_LINKS or any(_key(child) not in all_collections for child in children):
            _refuse("Collection links exceed the reviewed protected transform scope.", maximum=MAX_COLLECTION_LINKS)
    for obj in objects:
        users_scene = _bounded(obj.users_scene, MAX_SCENES, "object scene owners")
        users_collection = _bounded(obj.users_collection, MAX_OWNING_COLLECTIONS, "object collection owners")
        if any(_key(scene) not in scene_keys for scene in users_scene) or any(_key(collection) not in all_collections for collection in users_collection):
            _refuse("Object owners fall outside the bounded project inventory.")


def _geometry_descriptors(data: Any, fields: frozenset[str]) -> None:
    """Native geometry collections are homogeneous RNA element types.

    Inspect their descriptors without reading arbitrary per-element properties.
    The later mutation snapshot remains responsible for actual content evidence.
    """
    remaining = MAX_GEOMETRY_ELEMENTS
    for name in ("vertices", "edges", "loops", "polygons"):
        values = _field(data, fields, name, ())
        count = len(values)
        remaining -= count
        if remaining < 0:
            _refuse("Affected geometry exceeds the protected transform profile budget.")
        if count:
            _rna(values[0])
    for attribute in _bounded(_field(data, fields, "attributes", ()), 128, "geometry attributes"):
        attribute_fields = _rna(attribute)
        values = _field(attribute, attribute_fields, "data", ())
        count = len(values)
        remaining -= count
        if remaining < 0:
            _refuse("Affected attribute data exceeds the protected transform profile budget.")
        if count:
            _rna(values[0])


def require_profile(bpy: Any, affected_objects: Iterable[Any], check: Callable[[], None] | None = None) -> None:
    """Require a bounded static authored-data profile at the final safe point.

    Call this again after live authority providers and before each owned write or
    compensation. The optional callback runs once, before any terminal reads.
    Existing animation on unrelated protected characters is not edited or
    certified; affected animated/rigged/shape-key objects remain unsupported.
    """
    if check is not None:
        check()
    pre_closure(bpy)
    for obj in _bounded(affected_objects, MAX_AFFECTED_OBJECTS, "affected objects"):
        fields = _rna(obj)
        if _field(obj, fields, "animation_data") is not None or _field(obj, fields, "type") == "ARMATURE":
            _refuse("Affected animation and rigs need a separate protected transform profile.")
        if _field(obj, fields, "instance_type", "NONE") != "NONE" or _field(obj, fields, "instance_collection") is not None:
            _refuse("Object instances need a separate protected transform profile.")
        for name in ("rigid_body", "rigid_body_constraint", "soft_body"):
            if _field(obj, fields, name) is not None:
                _refuse("Implicit physics effects need a separate protected transform profile.", role=name)
        if _bounded(_field(obj, fields, "particle_systems", ()), 0, "particle systems"):
            _refuse("Particles need a separate protected transform profile.")
        field = _field(obj, fields, "field")
        if field is not None:
            field_fields = _rna(field)
            if _field(field, field_fields, "type", "NONE") != "NONE":
                _refuse("Force fields need a separate protected transform profile.")
        for kind in ("modifiers", "constraints"):
            for component in _bounded(_field(obj, fields, kind, ()), MAX_COMPONENTS, kind):
                component_fields = _rna(component)
                if kind == "modifiers" and _field(component, component_fields, "type") in IMPLICIT_MODIFIERS:
                    _refuse("Simulation, collision and procedural modifiers need a separate protected transform profile.")
        data = _field(obj, fields, "data")
        if data is not None:
            data_fields = _rna(data)
            if _field(data, data_fields, "animation_data") is not None or _field(data, data_fields, "shape_keys") is not None:
                _refuse("Affected data animation and shape keys need a separate protected transform profile.")
            if _field(obj, fields, "type") == "MESH":
                _geometry_descriptors(data, data_fields)
