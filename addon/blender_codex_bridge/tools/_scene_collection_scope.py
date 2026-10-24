"""Read-only, bounded native collection scope for scene-edit write boundaries.

This is an admission/projection helper, not authorization or recovery. Callers
must run live grants first and a pure terminal request check after comparing its
result. The helper never refreshes/evaluates a view layer to manufacture scope.
"""

from __future__ import annotations

import math
from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode
from ._scene_mutation import custom_value

MAX_COLLECTIONS = 4096
MAX_LAYERS = 256
MAX_DIRECT_USERS = 1024
MAX_DEPTH = 64
MAX_PROPERTIES = 512
MAX_OBJECTS = 4096
PRIMITIVES = frozenset({"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"})
UNREAD_RUNTIME = {
    ("Scene", "cycles"): "CyclesRenderSettings",
    ("Scene", "cycles_curves"): "CyclesCurveRenderSettings",
    ("ViewLayer", "cycles"): "CyclesRenderLayerSettings",
}


def _unsupported(message: str) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, message, {"scope_complete": False})


def _bounded(items: Any, maximum: int, label: str) -> list[Any]:
    values = list(islice(items, maximum + 1))
    if len(values) > maximum:
        raise _unsupported(f"Collection {label} exceeds {maximum} entries.")
    return values


def _identity(owner: Any) -> int:
    return int(owner.as_pointer())


def _token(owner: Any) -> tuple[int, Any]:
    return _identity(owner), owner.session_uid


def _class(bpy: Any, owner: Any, kind: str) -> Any:
    canonical = getattr(bpy.types, kind, None)
    if canonical is None or type(owner) is not canonical:
        raise _unsupported(f"Collection scope requires the canonical native {kind} class.")
    rna = owner.bl_rna
    if rna.identifier != kind or rna != canonical.bl_rna:
        raise _unsupported(f"Collection scope has an unreviewed {kind} RNA descriptor.")
    props = _bounded(rna.properties, MAX_PROPERTIES, f"{kind} RNA fields")
    for prop in props:
        if prop.is_runtime:
            # Bundled scene settings are intentionally not resolved. Their
            # native read-only pointer descriptors cannot replace our fields.
            expected = UNREAD_RUNTIME.get((kind, prop.identifier))
            if (expected is not None
                    and prop.type == "POINTER" and prop.is_readonly
                    and not prop.is_registered and not getattr(prop, "array_length", 0)
                    and getattr(getattr(prop, "fixed_type", None), "identifier", None) == expected):
                continue
            raise _unsupported(f"Collection scope refuses runtime {kind} RNA properties before getters.")
    return rna.properties


def _field(props: Any, name: str, kind: str) -> None:
    prop = props.get(name)
    if prop is None or prop.identifier != name or prop.is_runtime or prop.type != kind:
        raise _unsupported(f"Collection native field '{name}' has an unreviewed descriptor.")


def _id_class(bpy: Any, owner: Any, kind: str) -> Any:
    props = _class(bpy, owner, kind)
    for field, value_kind in (("name", "STRING"), ("session_uid", "INT"),
                               ("library", "POINTER"), ("override_library", "POINTER"),
                               ("is_editable", "BOOLEAN"), ("users", "INT"),
                               ("use_fake_user", "BOOLEAN")):
        _field(props, field, value_kind)
    if owner.library is not None or owner.override_library is not None or not owner.is_editable:
        raise _unsupported("Collection edits require local, editable, non-override ancestry.")
    return props


def _primitive(raw: Any, remaining: list[int], depth: int = 0, *, custom_scalars: bool = False) -> Any:
    if custom_scalars:
        return custom_value(raw, depth=depth, budget=remaining, max_depth=4, max_string=1024)
    remaining[0] -= 1
    if remaining[0] < 0 or depth > 4:
        raise _unsupported("Collection custom properties exceed 4096 values or depth four.")
    if raw is None or type(raw) in (bool, int):
        return raw
    if type(raw) is str:
        if len(raw) > 1024:
            raise _unsupported("Collection strings exceed 1024 characters.")
        return raw
    if type(raw) is float:
        if not math.isfinite(raw):
            raise _unsupported("Collection evidence requires finite values.")
        return raw
    native = type(raw).__module__ == "idprop.types"
    if type(raw) is dict or (native and type(raw).__name__ == "IDPropertyGroup"):
        keys = _bounded(raw.keys(), 128, "custom keys")
        if any(type(key) is not str for key in keys):
            raise _unsupported("Collection custom keys must be strings.")
        return tuple((key, _primitive(raw[key], remaining, depth + 1)) for key in sorted(keys))
    if type(raw) in (tuple, list) or (native and type(raw).__name__ == "IDPropertyArray"):
        return tuple(_primitive(value, remaining, depth + 1) for value in _bounded(raw, 256, "array values"))
    raise _unsupported("Collection custom properties contain unreviewed values or native references.")


def _custom(owner: Any) -> tuple[Any, ...]:
    keys = _bounded(owner.keys(), 128, "custom keys")
    if any(type(key) is not str for key in keys):
        raise _unsupported("Collection custom keys must be strings.")
    remaining = [4096]
    return tuple((key, _primitive(owner[key], remaining, custom_scalars=True)) for key in sorted(keys))


def _collection(bpy: Any, owner: Any, *, ignore_name: bool = False) -> tuple[Any, ...]:
    props = _id_class(bpy, owner, "Collection")
    for field in ("children", "objects"):
        _field(props, field, "COLLECTION")
    values = []
    for prop in props:
        if prop.is_readonly or prop.type not in PRIMITIVES or (ignore_name and prop.identifier == "name"):
            continue
        raw = getattr(owner, prop.identifier)
        if type(raw) is set:
            raw = tuple(sorted(raw))
        if getattr(prop, "array_length", 0):
            raw = tuple(raw)
        values.append((prop.identifier, _primitive(raw, [4096])))
    return tuple(values), _custom(owner)


def _tree(bpy: Any, root: Any) -> tuple[dict[int, Any], dict[int, tuple[int, ...]]]:
    owners: dict[int, Any] = {}
    parents: dict[int, list[int]] = {}
    pending = [(root, (), 0)]
    while pending:
        owner, path, depth = pending.pop()
        if depth > MAX_DEPTH:
            raise _unsupported("Collection ancestry exceeds depth 64.")
        _class(bpy, owner, "Collection")
        identity = _identity(owner)
        if identity in path:
            raise _unsupported("Collection ancestry contains a cycle.")
        if identity in owners:
            continue
        if len(owners) >= MAX_COLLECTIONS:
            raise _unsupported("Collection ancestry exceeds 4096 collections.")
        owners[identity] = owner
        _field(owner.bl_rna.properties, "children", "COLLECTION")
        children = _bounded(owner.children, MAX_COLLECTIONS, "children")
        child_ids = []
        for child in children:
            _class(bpy, child, "Collection")
            child_id = _identity(child)
            if child_id in child_ids:
                raise _unsupported("Collection membership repeats a native child.")
            child_ids.append(child_id)
            parents.setdefault(child_id, []).append(identity)
            pending.append((child, (*path, identity), depth + 1))
    return owners, {key: tuple(value) for key, value in parents.items()}


def _layer_occurrences(bpy: Any, scene: Any) -> tuple[dict[int, int], tuple[Any, ...]]:
    _field(scene.bl_rna.properties, "view_layers", "COLLECTION")
    layers = _bounded(scene.view_layers, MAX_LAYERS, "view layers")
    counts: dict[int, int] = {}
    records = []
    total = 0
    for layer in layers:
        props = _class(bpy, layer, "ViewLayer")
        _field(props, "layer_collection", "POINTER")
        pending = [(layer.layer_collection, (), 0)]
        seen: set[int] = set()
        while pending:
            item, path, depth = pending.pop()
            if depth > MAX_DEPTH:
                raise _unsupported("LayerCollection ancestry exceeds depth 64.")
            props = _class(bpy, item, "LayerCollection")
            for field, kind in (("collection", "POINTER"), ("children", "COLLECTION")):
                _field(props, field, kind)
            identity = _identity(item)
            if identity in seen:
                raise _unsupported("LayerCollection hierarchy repeats a native item.")
            seen.add(identity)
            total += 1
            if total > MAX_COLLECTIONS * MAX_LAYERS:
                raise _unsupported("LayerCollection scope exceeds its aggregate budget.")
            collection = item.collection
            _class(bpy, collection, "Collection")
            collection_id = _identity(collection)
            counts[collection_id] = counts.get(collection_id, 0) + 1
            records.append((_identity(layer), path, collection_id))
            pending.extend((child, (*path, collection_id), depth + 1)
                           for child in _bounded(item.children, MAX_COLLECTIONS, "layer children"))
    return counts, tuple(sorted(records))


def snapshot(
    bpy: Any, scene: Any, collection: Any, *, operation: str,
    allow_unlinked: bool = False, expected_name: str | None = None,
) -> tuple[Any, ...]:
    """Freeze supported ownership, ancestry and authored collection content.

    ``expected_name`` is internal rename state: verify the exact live name and
    storage binding while excluding that owned name from the returned content.
    Memberships use native IDs, so a rename does not adopt unrelated changes.
    ``allow_unlinked`` admits only a new, empty, zero-user allocation without a
    fake user. Deletion still requires separate live DELETE_OBJECTS authority.
    """
    del operation  # Authorization belongs to the calling write boundary.
    scene_props = _id_class(bpy, scene, "Scene")
    _field(scene_props, "collection", "POINTER")
    if bpy.context.scene != scene or bpy.data.scenes.get(scene.name) != scene:
        raise _unsupported("Collection mutations require the actual current Scene.")
    root = scene.collection
    owners, parents = _tree(bpy, root)
    _id_class(bpy, collection, "Collection")
    target_id, root_id = _identity(collection), _identity(root)
    actual_name = collection.name
    if expected_name is not None and actual_name != expected_name:
        raise _unsupported("Collection rename output changed before the next write.")
    if target_id != root_id and bpy.data.collections.get(actual_name) != collection:
        raise _unsupported("Collection native storage binding changed.")
    layer_counts, layer_records = _layer_occurrences(bpy, scene)
    path = []
    if target_id in owners:
        current = target_id
        while True:
            path.append(current)
            if current == root_id:
                break
            incoming = parents.get(current, ())
            if len(incoming) != 1:
                raise _unsupported("Collection ancestry is shared or has multiple parent links.")
            current = incoming[0]
            if len(path) > MAX_DEPTH + 1:
                raise _unsupported("Collection ancestry exceeds depth 64.")
        path.reverse()
    elif allow_unlinked:
        if collection.users or collection.use_fake_user or len(collection.children) or len(collection.objects):
            raise _unsupported("Owned unlinked cleanup requires an empty zero-user allocation.")
        if layer_counts.get(target_id, 0):
            raise _unsupported("Unlinked collection acquired a view-layer consumer.")
        owners[target_id] = collection
        path = [target_id]
    else:
        raise _unsupported("Collection belongs outside the actual current Scene.")

    user_map = bpy.data.user_map(subset={owners[key] for key in path})
    records = []
    for index, identity in enumerate(path):
        owner = owners[identity]
        _id_class(bpy, owner, "Collection")
        is_root = identity == root_id
        effective_users = int(owner.users) - int(bool(owner.use_fake_user))
        expected_users = 0 if is_root or (allow_unlinked and target_id not in parents and target_id != root_id) else 1
        if effective_users != expected_users:
            raise _unsupported("Collection has shared, instanced or unexplained native users.")
        expected: dict[int, int] = {}
        scene_refs = (1 if is_root or (index > 0 and path[index - 1] == root_id) else 0) + layer_counts.get(identity, 0)
        actual_scene_refs = int(scene.user_of_id(owner))
        if actual_scene_refs != scene_refs:
            raise _unsupported("Collection Scene references do not match actual native memberships.")
        if not is_root and scene_refs:
            expected[_identity(scene)] = scene_refs
        if index > 0 and path[index - 1] != root_id:
            parent = owners[path[index - 1]]
            if int(parent.user_of_id(owner)) != 1:
                raise _unsupported("Collection parent has references beyond ordinary child membership.")
            expected[_identity(parent)] = 1
        direct = _bounded(user_map.get(owner, ()), MAX_DIRECT_USERS, "direct users")
        actual = {_identity(user): int(user.user_of_id(owner)) for user in direct}
        if len(actual) != len(direct) or actual != expected:
            raise _unsupported("Collection has external, instanced or unexplained direct consumers.")
        records.append((_token(owner), _collection(bpy, owner, ignore_name=expected_name is not None and identity == target_id),
                        effective_users, tuple(sorted(actual.items())), actual_scene_refs))

    children = tuple(sorted(_token(child) for child in _bounded(collection.children, MAX_COLLECTIONS, "target children")))
    objects = _bounded(collection.objects, MAX_OBJECTS, "target objects")
    object_ids = []
    for obj in objects:
        # Objects are membership identities, never generic settings/geometry
        # readers. Validate the one native ID field without resolving unrelated
        # runtime properties on member Objects (including bundled UI settings).
        canonical = getattr(bpy.types, "Object", None)
        if canonical is None or type(obj) is not canonical or obj.bl_rna != canonical.bl_rna:
            raise _unsupported("Collection membership contains an unreviewed Object class.")
        props = obj.bl_rna.properties
        _field(props, "session_uid", "INT")
        object_ids.append(_token(obj))
    relevant_layers = tuple(record for record in layer_records if record[2] in path)
    return (("scene", _token(scene)), ("target", _token(collection)), ("ancestry", tuple(records)),
            ("children", children), ("objects", tuple(sorted(object_ids))), ("layers", relevant_layers))


def without_owned_child(profile: tuple[Any, ...], child: tuple[int, Any]) -> tuple[Any, ...]:
    """Project exactly one already-proven new child from a parent's readback.

    The caller must separately prove this exact allocation's complete expected
    state before using the projection. This normalizes no ancestry, settings,
    existing membership or consumer change and never refreshes native data.
    """
    fields = dict(profile)
    if (set(fields) != {"scene", "target", "ancestry", "children", "objects", "layers"}
            or fields["target"] == child or fields["children"].count(child) != 1):
        raise _unsupported("Owned collection publication has no unique new child identity.")
    return tuple((key, tuple(value for value in values if value != child) if key == "children" else values)
                 for key, values in profile)
