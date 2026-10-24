"""Readonly authored evidence for an artist checkpoint's previous weak owner.

Only the particle poll's Scene/Object bookkeeping moves. The previous Object is
never added to the transform's write set. Unsupported outbound dependencies are
refused instead of treating an ID binding as complete content evidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import _animation_scope as scope
from . import _artist_scope_profile as profile
from . import _object_rna_mutation as objects
from . import _scene_mutation as proof
from ._object_safety import require_local_editable_id

MAX_MATERIALS = 16
MAX_GRAPH_NODES = 8
MAX_BYTES = 1_048_576
MAX_WITNESS_BYTES = 8_388_608
NODES = frozenset({"ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial"})
UV_ALIASES = frozenset({"uv_layer_clone", "uv_layer_stencil"})


def _screen(owner: Any, *, pointers: frozenset[str] = frozenset()) -> None:
    """Screen descriptors before reading writable fields or custom contents."""
    profile._rna(owner)
    for prop in owner.bl_rna.properties:
        if prop.is_readonly or prop.identifier in pointers or prop.type != "POINTER":
            continue
        if getattr(owner, prop.identifier) is not None:
            raise proof.unsupported("Previous checkpoint owner has an unsupported outbound dependency.",
                                    property=prop.identifier, previous_owner_witness_complete=False)


def _custom(owner: Any) -> Any:
    # Unlike the inherited Object snapshot, this strict serializer rejects
    # native IDs inside nested custom containers before they become mere tokens.
    try:
        names = proof.bounded(owner.keys(), 128, "previous-owner custom keys")
    except AttributeError:
        return ()
    except TypeError as error:
        if "doesn't support IDProperties" in str(error):
            return ()
        raise
    budget = [4096]
    return tuple((name, proof.custom_value(owner[name], budget=budget)) for name in sorted(names))


def _plain_child(owner: Any, name: str) -> Any:
    """Explicit native settings children; no generic readonly-pointer walk."""
    fields = profile._rna(owner, reads=frozenset({name}))
    if name not in fields:
        return None
    child = getattr(owner, name)
    if child is None:
        return None
    _screen(child)
    return scope.key(child), scope.rna_state(child), _custom(child)


def _asset(owner: Any) -> None:
    fields = profile._rna(owner, reads=frozenset({"asset_data"}))
    if "asset_data" in fields and owner.asset_data is not None:
        raise proof.unsupported("Previous checkpoint asset metadata requires a broader readonly witness.")


def _mesh_uv_aliases(bpy: Any, mesh: Any) -> Any:
    """Prove only the native clone/stencil selectors into this Mesh's UVs.

    Both reviewed RNA implementations return members of uv_layers. Blender 4.5
    uses CustomData clone/stencil indices; 5.2 uses nullable UV attribute names.
    Neither selector is an outbound ID dependency or a new authored baseline.
    """
    profile._rna(mesh, reads=UV_ALIASES | {"uv_layers"})
    properties = {prop.identifier: prop for prop in mesh.bl_rna.properties}
    present = tuple(name for name in sorted(UV_ALIASES) if name in properties)
    if not present:
        return ()
    canonical = getattr(getattr(bpy, "types", None), "MeshUVLoopLayer", None)
    fixed = getattr(canonical, "bl_rna", None)
    for name in (*present, "uv_layers"):
        prop = properties.get(name)
        kind = "COLLECTION" if name == "uv_layers" else "POINTER"
        if (fixed is None or prop is None or prop.type != kind or getattr(prop, "is_runtime", False)
                or getattr(prop, "is_registered", False) or getattr(prop, "is_registered_optional", False)
                or scope.key(getattr(prop, "fixed_type", None)) != scope.key(fixed)
                or (name != "uv_layers" and prop.is_readonly)):
            raise proof.unsupported("Previous checkpoint UV selector has an unreviewed native descriptor.",
                                    property=name, previous_owner_witness_complete=False)
    layers = proof.bounded(mesh.uv_layers, 128, "previous-owner UV selector inventory")
    for layer in layers:
        if scope.key(getattr(layer, "bl_rna", None)) != scope.key(fixed):
            raise proof.unsupported("Previous checkpoint UV selectors require the admitted native layer type.")
        profile._rna(layer, reads=frozenset({"name"}))
        name = next((prop for prop in layer.bl_rna.properties if prop.identifier == "name"), None)
        if (name is None or name.type != "STRING" or getattr(name, "is_runtime", False)
                or getattr(name, "is_registered", False) or getattr(name, "is_registered_optional", False)):
            raise proof.unsupported("Previous checkpoint UV layers need their native name evidence.")
    result = []
    for name in present:
        selected = getattr(mesh, name)
        if selected is None:
            result.append((name, None))
            continue
        matches = [index for index, layer in enumerate(layers) if selected == layer]
        if len(matches) != 1:
            raise proof.unsupported("Previous checkpoint UV selector is outside its unique same-Mesh layer inventory.",
                                    property=name, previous_owner_witness_complete=False)
        index = matches[0]
        layer = layers[index]
        result.append((name, (index, scope.key(layer), str(layer.name))))
    return tuple(result)


def _material(bpy: Any, material: Any) -> tuple[Any, tuple[Any, ...]]:
    from .shader_interface import _Proof

    require_local_editable_id(material, operation="Previous checkpoint owner witness")
    _asset(material)
    _screen(material, pointers=frozenset({"node_tree"}))
    profile._rna(material, reads=frozenset({"animation_data", "grease_pencil", "node_tree"}))
    customs = [("material", _custom(material))]
    if material.animation_data is not None or getattr(material, "grease_pencil", None) is not None:
        raise proof.unsupported("Previous checkpoint material animation or grease-pencil data needs a broader witness.")
    tree = material.node_tree
    children = tuple((name, _plain_child(material, name)) for name in ("lineart",))
    reader = _Proof()
    state: Any = reader.properties(material), children, tuple(customs), None
    identifiers = (material,)
    if tree is not None:
        require_local_editable_id(tree, operation="Previous checkpoint material witness")
        _asset(tree)
        _screen(tree)
        profile._rna(tree, reads=frozenset({"animation_data", "interface", "nodes", "links"}))
        customs.append(("tree", _custom(tree)))
        if tree.animation_data is not None:
            raise proof.unsupported("Animated previous checkpoint node trees need a broader witness.")
        nodes = proof.bounded(tree.nodes, MAX_GRAPH_NODES, "previous-owner material nodes")
        proof.bounded(tree.links, 64, "previous-owner material links")
        _screen(tree.interface)
        profile._rna(tree.interface, reads=frozenset({"items_tree", "active"}))
        customs.append(("interface", _custom(tree.interface)))
        proof.bounded(tree.interface.items_tree, 0, "previous-owner material interface")
        for node in nodes:
            # These two native node kinds have no image/group/object data
            # dependencies. Broader graphs need their own transitive reader.
            if node.bl_idname not in NODES:
                raise proof.unsupported("Previous checkpoint materials require bounded native Principled/output graphs.",
                                        node_type=node.bl_idname)
            _screen(node)
            profile._rna(node, reads=frozenset({"texture_mapping", "color_mapping", "image_user", "color_ramp", "node_tree", "object", "image"}))
            customs.append((node.name, _custom(node)))
            for direction in ("inputs", "outputs"):
                for socket in proof.bounded(getattr(node, direction), 64, "previous-owner node sockets"):
                    _screen(socket)
                    profile._rna(socket, reads=frozenset({"identifier", "is_linked"}))
                    customs.append(((node.name, direction, socket.identifier), _custom(socket)))
        state = reader.properties(material), children, tuple(customs), reader.graph(tree)
        identifiers = material, tree
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > MAX_BYTES:
        raise proof.unsupported("Previous checkpoint material evidence exceeds one MiB.")
    return encoded, identifiers


def _dependencies(bpy: Any, obj: Any) -> Any:
    """Measure the bounded static Mesh/Empty dependency profile literally."""
    _screen(obj, pointers=frozenset({"data", "active_material"}))
    _asset(obj)
    customs = [("object", _custom(obj))]
    if obj.type not in {"EMPTY", "MESH"}:
        raise proof.unsupported("Previous checkpoint owners currently require static Empty or Mesh evidence.")
    children = tuple((name, _plain_child(obj, name)) for name in ("field", "display", "collision", "lineart", "light_linking"))
    fields = profile._rna(obj, reads=frozenset({"animation_visualization"}))
    visualization = obj.animation_visualization if "animation_visualization" in fields else None
    if visualization is not None:
        _screen(visualization)
        children += (("animation_visualization", (scope.rna_state(visualization), _custom(visualization),
                                                   _plain_child(visualization, "motion_path"))),)
    for kind in ("modifiers", "constraints"):
        for component in proof.bounded(getattr(obj, kind), 100, "previous-owner components"):
            _screen(component)
            customs.append(((kind, scope.key(component)), _custom(component)))
    data = obj.data
    identifiers, materials = [], []
    mesh_roles = None
    if data is not None:
        if obj.type != "MESH":
            raise proof.unsupported("Previous Empty data bindings need a separate witness.")
        require_local_editable_id(data, operation="Previous checkpoint geometry witness")
        _asset(data)
        # Validate all selector descriptors and same-Mesh membership before
        # permitting the inherited generic Mesh snapshot to read these aliases.
        uv_aliases = _mesh_uv_aliases(bpy, data)
        _screen(data, pointers=UV_ALIASES)
        customs.append(("data", _custom(data)))
        fields = profile._rna(data, reads=frozenset({"uv_layers", "vertex_colors", "color_attributes", "skin_vertices"}))
        if "skin_vertices" in fields:
            proof.bounded(data.skin_vertices, 0, "previous-owner skin layers")
        layers = []
        for name in ("uv_layers", "vertex_colors"):
            values = getattr(data, name, ()) if name in fields else ()
            records = []
            for layer in proof.bounded(values, 128, "previous-owner geometry layers"):
                read = profile._rna(layer, reads=frozenset({"name", "active", "active_clone", "active_render"}))
                records.append(tuple((field, scope.value(getattr(layer, field))) for field in
                                     ("name", "active", "active_clone", "active_render") if field in read))
            layers.append((name, getattr(values, "active_index", None), tuple(records)))
        colors = data.color_attributes if "color_attributes" in fields else None
        mesh_roles = (tuple(layers), (getattr(colors, "active_color_index", None), getattr(colors, "render_color_index", None)),
                      uv_aliases)
        identifiers.append(data)
        materials.extend(proof.bounded(data.materials, MAX_MATERIALS, "previous-owner geometry materials"))
    materials.extend(slot.material for slot in proof.bounded(obj.material_slots, MAX_MATERIALS, "previous-owner material slots"))
    unique = {scope.action_token(material): material for material in materials if material is not None}
    if len(unique) > MAX_MATERIALS:
        raise proof.unsupported("Previous checkpoint owner exceeds sixteen distinct materials.")
    states = []
    for identity, material in sorted(unique.items()):
        state, nested = _material(bpy, material)
        states.append((identity, state))
        identifiers.extend(nested)
    identifiers = list({scope.action_token(owner): owner for owner in identifiers}.values())
    groups = getattr(getattr(obj, "vertex_groups", None), "active_index", None)
    return (tuple(customs), children, mesh_roles, groups, tuple(states),
            proof.references(bpy, tuple(identifiers)) if identifiers else ())


@dataclass(frozen=True, slots=True)
class Witness:
    bpy: Any
    name: str
    identity: Any
    authored: Any
    dependencies: Any
    consumers: Any

    def _object(self) -> Any:
        obj = self.bpy.data.objects.get(self.name)
        if (obj is None or scope.action_token(obj) != self.identity
                or self.bpy.context.scene.objects.get(self.name) != obj
                or self.bpy.context.view_layer.objects.get(self.name) != obj):
            raise proof.unsupported("Previous checkpoint Object identity or scene membership changed.",
                                    previous_object=self.name, previous_owner_witness_complete=False)
        return obj

    def check(self, plan: Any) -> None:
        try:
            obj = self._object()
            from . import artist_loop
            artist_loop.require_profile(self.bpy, (obj,))
            _, references = objects._closure(self.bpy, obj)
            stable = (_dependencies(self.bpy, obj) == self.dependencies
                      and objects._object_state(obj, artist_profile=True) == self.authored
                      and plan.object_references(references) == self.consumers)
        except (AttributeError, ReferenceError, TypeError, RuntimeError):
            stable = False
        if not stable:
            raise proof.unsupported("Previous checkpoint Object authored data, dependencies or consumers changed.",
                                    previous_object=self.name, previous_owner_witness_complete=False)


def capture(bpy: Any, obj: Any, plan: Any) -> Witness:
    """Called only by artist admission, before live authority providers."""
    from . import artist_loop
    objects.require_object_scope(bpy, obj, operation="Previous checkpoint Object witness")
    artist_loop.require_profile(bpy, (obj,))
    _, references = objects._closure(bpy, obj)
    dependencies = _dependencies(bpy, obj)
    result = Witness(bpy, str(obj.name), scope.action_token(obj),
                     objects._object_state(obj, artist_profile=True), dependencies,
                     plan.object_references(references))
    encoded = json.dumps((result.authored, result.dependencies, result.consumers),
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > MAX_WITNESS_BYTES:
        raise proof.unsupported("Previous checkpoint owner witness exceeds eight MiB.")
    result.check(plan)
    return result
