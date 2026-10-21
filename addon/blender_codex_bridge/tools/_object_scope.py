"""Conservative scene/container and incoming-reference scope for object edits."""

from __future__ import annotations

from itertools import islice
from typing import Any

from ..errors import BridgeError, ErrorCode
from ..permissions import Permission
from ._object_safety import require_local_editable_id, require_local_object

MAX_COLLECTION_SCAN = 4096
MAX_DIRECT_USERS = 1024
MAX_VIEW_LAYERS = 256


def datablock_identity(value: Any) -> int:
    """RNA may return a new Python wrapper for the same native datablock."""
    return int(value.as_pointer()) if hasattr(value, "as_pointer") else id(value)


class MutationGuard:
    """Revalidate live consent and frozen session identity at actual write boundaries."""

    def __init__(self, bpy: Any, context: Any, method: str):
        self.bpy, self.context, self.method = bpy, context, method
        self.scene = datablock_identity(bpy.context.scene)
        self.layer = datablock_identity(bpy.context.view_layer)
        self.filepath = getattr(bpy.data, "filepath", None)
        self.identities: list[tuple[Any, int, Any, Any]] = []

    def remember(self, value: Any, storage: Any = None) -> None:
        self.identities.append((value, datablock_identity(value), getattr(value, "session_uid", None), storage))

    def forget(self, value: Any) -> None:
        self.identities = [item for item in self.identities if item[0] is not value]

    def check(self, objects: tuple[Any, ...] | list[Any] = (), collections: tuple[Any, ...] | list[Any] = (), *, dependencies: bool = True, delete: bool = False) -> None:
        cancelled = getattr(self.context, "check_cancelled", None)
        if callable(cancelled):
            cancelled()
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.prepare(self.method, self.context)
        if delete:
            permissions = getattr(self.context, "permissions", None)
            if permissions is None:
                raise BridgeError(ErrorCode.PERMISSION_DENIED, "Allocation cleanup requires explicit deletion permission.")
            permissions.require((Permission.DELETE_OBJECTS,))
        try:
            stable = self.bpy.context.mode == "OBJECT" and self.scene == datablock_identity(self.bpy.context.scene) and self.layer == datablock_identity(self.bpy.context.view_layer) and self.filepath == getattr(self.bpy.data, "filepath", None)
            stable = stable and all(datablock_identity(value) == identity and getattr(value, "session_uid", None) == session and (storage is None or storage.get(value.name) == value) for value, identity, session, storage in self.identities)
        except (ReferenceError, AttributeError):
            stable = False
        if not stable:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Scene, view layer, project or target identity changed after preflight; no further writes are allowed.", {"scope_complete": False})
        for obj in objects:
            require_object_scope(self.bpy, obj, operation=self.method)
        for collection in collections:
            require_collection_scope(self.bpy, collection, operation=self.method)
        if objects and dependencies:
            require_no_external_consumers(self.bpy, list(objects), operation=self.method)


def require_collection_scope(bpy: Any, collection: Any, *, operation: str) -> None:
    """Prove that a collection and its ancestors belong only to the current scene."""
    scene = bpy.context.scene
    require_local_editable_id(scene, operation=operation)
    root = scene.collection
    pending = [(root, ())]
    scanned: set[int] = set()
    path = None
    while pending:
        current, ancestors = pending.pop()
        identity = datablock_identity(current)
        if identity in scanned:
            continue
        if len(scanned) >= MAX_COLLECTION_SCAN:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Collection scope exceeds the reviewed inspection budget.", {"collection": collection.name, "scope_complete": False})
        scanned.add(identity)
        if current == collection:
            path = (*ancestors, current)
            break
        pending.extend((child, (*ancestors, current)) for child in current.children)
    if path is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object tools only edit collections in the current scene.", {"collection": collection.name, "scene": scene.name})
    for container in path:
        require_local_editable_id(container, operation=operation)
        users = int(container.users) - int(bool(container.use_fake_user))
        if users != 1 and not (container == root and users == 0):
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Shared or instanced collection ancestry requires an explicit wider scope; no containers are changed implicitly.", {"collection": container.name, "effective_users": users})


def require_object_scope(bpy: Any, obj: Any, *, operation: str) -> None:
    require_local_object(obj, operation=operation)
    if bpy.context.mode != "OBJECT" or obj.mode != "OBJECT":
        raise BridgeError(ErrorCode.INVALID_MODE, f"{operation} requires Object Mode without changing selection or mode.", {"object": obj.name})
    if bpy.context.view_layer.objects.get(obj.name) != obj:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object target must belong to the current view layer.", {"object": obj.name})
    scenes = tuple(obj.users_scene)
    if len(scenes) != 1 or scenes[0] != bpy.context.scene:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Objects shared between scenes or outside the current scene require an explicit wider scope.", {"object": obj.name, "scene_count": len(scenes)})
    for collection in obj.users_collection:
        require_collection_scope(bpy, collection, operation=operation)


def require_no_external_consumers(bpy: Any, objects: list[Any], *, operation: str) -> None:
    """Reject consumers outside owning collections; do not infer transitive effects."""
    try:
        user_map = bpy.data.user_map(subset=set(objects))
    except Exception as exc:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cannot prove object dependency scope before mutation.", {"scope_complete": False}) from exc
    for obj in objects:
        users = list(islice(user_map.get(obj, ()), MAX_DIRECT_USERS + 1))
        if len(users) > MAX_DIRECT_USERS:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Object dependency scope exceeds the reviewed budget.", {"object": obj.name, "scope_complete": False})
        containers = {datablock_identity(collection) for collection in obj.users_collection}
        try:
            ordinary_links = all(collection.user_of_id(obj) == 1 for collection in obj.users_collection)
        except Exception as exc:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Cannot prove collection reference scope before mutation.", {"object": obj.name, "scope_complete": False}) from exc
        if not ordinary_links:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Owning collections contain references beyond ordinary object membership.", {"object": obj.name})
        external = [user for user in users if datablock_identity(user) not in containers and not _ordinary_scene_membership(bpy.context.scene, user, obj)]
        if external:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, f"{operation} has incoming consumers outside its owning collections; dependency effects are not changed implicitly.", {"object": obj.name, "direct_consumers": [getattr(user, "name", None) for user in external[:20]], "consumer_count": len(external), "consumers_truncated": len(external) > 20})


def _ordinary_scene_membership(scene: Any, user: Any, obj: Any) -> bool:
    """Scene owns view-layer bases and its embedded root's links, not arbitrary users."""
    if datablock_identity(user) != datablock_identity(scene):
        return False
    try:
        layers = list(islice(scene.view_layers, MAX_VIEW_LAYERS + 1))
        if len(layers) > MAX_VIEW_LAYERS:
            return False
        root_links = int(scene.collection.objects.get(obj.name) == obj)
        base_links = sum(layer.objects.get(obj.name) == obj for layer in layers)
        expected = root_links + base_links
        return expected > 0 and scene.collection.user_of_id(obj) == root_links and scene.user_of_id(obj) == expected
    except Exception:
        return False
