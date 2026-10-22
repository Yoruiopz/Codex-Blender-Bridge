"""Descriptor-first, bounded static EEVEE preservation evidence.

No operators, permission providers, external reads or arbitrary RNA paths. This is
an explicit native-data contract, not a sandbox for the Blender host process.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from array import array
from itertools import islice
from typing import Any

from .errors import BridgeError, ErrorCode

try:
    from idprop.types import IDPropertyArray, IDPropertyGroup
except ImportError:  # Standalone schema/unit tests have no Blender C extension.
    IDPropertyArray = IDPropertyGroup = None

MAX_IDS, MAX_OBJECTS, MAX_ELEMENTS = 256, 64, 32768
MAX_BYTES = 2 * 1024 * 1024
UI = frozenset({"screens", "workspaces", "window_managers"})
FAMILIES = UI | frozenset(
    {
        "objects",
        "meshes",
        "cameras",
        "lights",
        "materials",
        "worlds",
        "collections",
        "scenes",
        "images",
        "palettes",
        "linestyles",
    }
)
NODES = frozenset(
    {
        "ShaderNodeOutputMaterial",
        "ShaderNodeBsdfPrincipled",
        "ShaderNodeTexChecker",
        "ShaderNodeUVMap",
        "ShaderNodeTexCoord",
        "ShaderNodeRGB",
        "ShaderNodeValue",
        "ShaderNodeBackground",
        "ShaderNodeOutputWorld",
        "ShaderNodeEmission",
        "ShaderNodeOutputLight",
        "NodeFrame",
        "ShaderNodeBsdfDiffuse",
    }
)
SOCKETS = frozenset(
    {
        "NodeSocketShader",
        "NodeSocketFloat",
        "NodeSocketFloatFactor",
        "NodeSocketFloatDistance",
        "NodeSocketFloatAngle",
        "NodeSocketFloatUnsigned",
        "NodeSocketFloatWavelength",
        "NodeSocketVector",
        "NodeSocketVectorXYZ",
        "NodeSocketColor",
        "NodeSocketInt",
        "NodeSocketBool",
    }
)
TYPES = (
    NODES
    | SOCKETS
    | frozenset(
        {
            "Scene",
            "Object",
            "Mesh",
            "Camera",
            "CameraDOFSettings",
            "PointLight",
            "AreaLight",
            "SunLight",
            "SpotLight",
            "Material",
            "World",
            "Collection",
            "CollectionObject",
            "CollectionChild",
            "CollectionLightLinking",
            "ShaderNodeTree",
            "RenderSettings",
            "ImageFormatSettings",
            "ColorManagedViewSettings",
            "ColorManagedDisplaySettings",
            "ColorManagedSequencerColorspaceSettings",
            "SceneEEVEE",
            "SceneDisplay",
            "RaytraceEEVEE",
            "ViewLayerEEVEE",
            "WorldLighting",
            "WorldMistSettings",
            "MaterialGPencilStyle",
            "MaterialLineArt",
            "MaterialSlot",
            "ObjectLightLinking",
            "UnitSettings",
            "ToolSettings",
            "ParticleEdit",
            "UVLoopLayers",
            "ViewLayer",
            "LayerCollection",
            "SequenceEditor",
            "FreestyleSettings",
            "FreestyleLineSet",
            "FreestyleLineStyle",
            "Palette",
            "PaletteColor",
            "Image",
            "MeshVertex",
            "MeshEdge",
            "MeshLoop",
            "MeshPolygon",
            "VertexGroup",
            "VertexGroupElement",
            "FloatVectorAttribute",
            "FloatVectorAttributeValue",
            "FloatColorAttribute",
            "FloatColorAttributeValue",
            "ByteColorAttribute",
            "ByteColorAttributeValue",
            "IntAttribute",
            "IntAttributeValue",
            "Int2Attribute",
            "Int2AttributeValue",
            "Float2Attribute",
            "Float2AttributeValue",
            "BoolAttribute",
            "BoolAttributeValue",
            "FloatAttribute",
            "FloatAttributeValue",
            "StringAttribute",
            "StringAttributeValue",
            "Int8Attribute",
            "Int8AttributeValue",
            "MeshUVLoopLayer",
            "MeshUVLoop",
            "FieldSettings",
            "NodeLink",
            "LineStyleGeometryModifier_Sampling",
        }
    )
)
# Reviewed bundled fields are never read. The exact 4.5 build uses ordinary
# raw IDProperty storage; 5.2 SYSTEM storage has no reviewed safe reader.
RUNTIME = {
    "Scene": {
        "cycles": ("POINTER", True, "CyclesRenderSettings"),
        "cycles_curves": ("POINTER", True, "CyclesCurveRenderSettings"),
    },
    "Object": {
        "selection_sets": ("COLLECTION", True, "SelectionSet"),
        "active_selection_set": ("INT", False, None),
        "cycles": ("POINTER", True, "CyclesObjectSettings"),
    },
    "Mesh": {"cycles": ("POINTER", True, "CyclesMeshSettings")},
    "Camera": {"cycles_custom": ("POINTER", True, "CyclesCustomCameraSettings")},
    "Material": {"cycles": ("POINTER", True, "CyclesMaterialSettings")},
    "World": {
        "cycles": ("POINTER", True, "CyclesWorldSettings"),
        "cycles_visibility": ("POINTER", True, "CyclesVisibilitySettings"),
    },
    "PointLight": {"cycles": ("POINTER", True, "CyclesLightSettings")},
    "AreaLight": {"cycles": ("POINTER", True, "CyclesLightSettings")},
    "SunLight": {"cycles": ("POINTER", True, "CyclesLightSettings")},
    "SpotLight": {"cycles": ("POINTER", True, "CyclesLightSettings")},
    "ViewLayer": {"cycles": ("POINTER", True, "CyclesRenderLayerSettings")},
}
OBJECT_DERIVED = frozenset({"dimensions", "matrix_world", "matrix_local", "matrix_basis"})


def refuse(message: str, **details: Any) -> None:
    raise BridgeError(
        ErrorCode.NOT_IMPLEMENTED, message, {"render_scope_complete": False, **details}
    )


def require_raw_storage_reader(bpy: Any) -> None:
    # Unregistering runtime descriptors does not prove that their authored
    # SYSTEM storage disappeared. Refuse the exact build independently of
    # which bundled declarations are currently visible.
    if getattr(getattr(bpy, "app", None), "build_hash", b"") == b"d13f752e3b9c":
        refuse(
            "This Blender build uses SYSTEM storage without a reviewed raw render reader.",
            runtime_getter_fallback_used=False,
        )


def bounded(values: Any, maximum: int, label: str) -> list[Any]:
    items = list(islice(values, maximum + 1))
    if len(items) > maximum:
        refuse(
            "Render preservation evidence exceeds its reviewed bound.",
            inventory=label,
            maximum=maximum,
        )
    return items


def native_engine(bpy: Any, identifier: str) -> None:
    # Native registration protects an existing built-in ID, but the other
    # version's spelling is available for Python engine registration. Accept
    # only the exact native ID proved for this build, never both spellings.
    expected = {b"62c1db4208e8": "BLENDER_EEVEE_NEXT", b"d13f752e3b9c": "BLENDER_EEVEE"}.get(
        getattr(getattr(bpy, "app", None), "build_hash", b"")
    )
    if expected is None or identifier != expected:
        refuse(
            "Native rendering requires the exact reviewed build and its native EEVEE identifier.",
            engine=identifier,
        )


def key(owner: Any) -> tuple | None:
    if owner is None:
        return None
    prop = owner.bl_rna.properties.get("session_uid")
    if prop is not None and (prop.is_runtime or prop.type != "INT" or not prop.is_readonly):
        refuse("Native identity metadata cannot use a runtime getter.")
    return int(owner.as_pointer()), None if prop is None else owner.session_uid


def value(
    raw: Any, depth: int = 0, *, allow_ids: bool = True, custom_scalars: bool = False
) -> Any:
    if custom_scalars:
        return _custom_value(raw, depth)
    if depth > 8:
        refuse("Render value nesting exceeds eight levels.")
    if raw is None or isinstance(raw, (bool, int, str)):
        if isinstance(raw, str) and len(raw) > 65536:
            refuse("Render evidence string exceeds 64 KiB.")
        return raw
    if isinstance(raw, float):
        if not math.isfinite(raw):
            refuse("Render preservation requires finite authored values.")
        return raw
    if hasattr(raw, "as_pointer"):
        if not allow_ids:
            refuse("Custom ID-property references need an explicit render-consumer contract.")
        return key(raw)
    if hasattr(raw, "keys"):
        return tuple(
            (str(k), value(raw[k], depth + 1, allow_ids=allow_ids))
            for k in bounded(raw.keys(), 128, "custom properties")
        )
    if isinstance(raw, set):
        return tuple(sorted(raw))
    return tuple(
        value(v, depth + 1, allow_ids=allow_ids)
        for v in bounded(raw, 256, "property array")
    )


def _custom_array_code(raw: Any) -> str:
    # Exact native C getset reads the stored subtype, has no setter/callback,
    # and returns only f/d/i/b. Absence/corruption is never a sequence default.
    try:
        code = raw.typecode
    except (AttributeError, TypeError, RuntimeError) as error:
        refuse("Custom array storage typecode is unavailable.", exception_type=type(error).__name__)
    if type(code) is not str or code not in {"f", "d", "i", "b"}:
        refuse("Custom array storage typecode is outside the reviewed native forms.")
    return code


def _custom_value(raw: Any, depth: int) -> Any:
    """Only reviewed exposed custom values; never a generic iterable reader."""
    if depth > 8:
        refuse("Render value nesting exceeds eight levels.")
    kind = type(raw)
    if raw is None or kind is bool or kind is int or kind is str:
        if kind is str and len(raw) > 65536:
            refuse("Render evidence string exceeds 64 KiB.")
        return kind.__name__, raw
    if kind is float:
        if not math.isfinite(raw):
            refuse("Render preservation requires finite authored values.")
        return "float", raw.hex()
    if kind is bytes or kind is bytearray:
        bounded(raw, 256, "custom byte string")
        return kind.__name__, raw.hex()
    if kind is IDPropertyGroup or kind is dict:
        names = bounded(raw.keys(), 128, "custom properties")
        if any(type(name) is not str for name in names):
            refuse("Custom property names require plain strings.")
        return (
            "native_group" if kind is IDPropertyGroup else "python_dict",
            tuple((name, _custom_value(raw[name], depth + 1)) for name in names),
        )
    if kind is IDPropertyArray or kind is array:
        code = _custom_array_code(raw)
        return (
            "native_array" if kind is IDPropertyArray else "python_array",
            code,
            tuple(_custom_value(item, depth + 1) for item in bounded(raw, 256, "custom array")),
        )
    if kind is list or kind is tuple:
        return (
            "python_sequence",
            kind.__name__,
            tuple(_custom_value(item, depth + 1) for item in bounded(raw, 256, "custom sequence")),
        )
    refuse("Custom property representation requires a reviewed explicit reader.")


class Reader:
    def __init__(
        self,
        bpy: Any,
        scene: Any,
        owned: frozenset[tuple[int, str]] = frozenset(),
        *,
        predict_native_availability: bool = False,
        checkpoint_prefix: str | None = None,
        checkpoint_static: bool = True,
    ):
        self.bpy, self.scene, self.owned = bpy, scene, owned
        self.nodes = self.links = self.elements = 0
        self.predict_native_availability = predict_native_availability
        if (
            checkpoint_prefix is not None
            and re.fullmatch(r"BCB1:[0-9a-f]{32}:", checkpoint_prefix) is None
        ):
            refuse("Checkpoint admission requires its exact manager-owned native marker namespace.")
        self.checkpoint_prefix = checkpoint_prefix
        self.checkpoint_static = checkpoint_static

    def props(self, owner: Any) -> tuple[Any, ...]:
        rna = getattr(owner, "bl_rna", None)
        kind = getattr(rna, "identifier", "")
        canonical = getattr(self.bpy.types, kind, None)
        if kind not in TYPES or canonical is None or rna != canonical.bl_rna:
            refuse(
                "Render evidence requires reviewed canonical native RNA classes.", owner_type=kind
            )
        props = bounded(rna.properties, 512, "RNA properties")
        allowed = RUNTIME.get(kind, {})
        for prop in props:
            if not prop.is_runtime:
                continue
            expected = allowed.get(prop.identifier)
            fixed = prop.fixed_type.identifier if prop.type in {"POINTER", "COLLECTION"} else None
            if expected is None or (prop.type, bool(prop.is_readonly), fixed) != expected:
                refuse(
                    "Unreviewed runtime RNA is refused before its getter is read.",
                    owner_type=kind,
                    property=prop.identifier,
                )
            if getattr(getattr(self.bpy, "app", None), "build_hash", b"") == b"d13f752e3b9c":
                refuse(
                    "Bundled runtime settings use SYSTEM storage without a reviewed raw render reader on this Blender build.",
                    owner_type=kind,
                    property=prop.identifier,
                    runtime_getter_fallback_used=False,
                )
            if kind == "Object" and prop.identifier == "active_selection_set" and prop.default != 0:
                refuse("Bundled selection UI descriptor changed.")
        return tuple(props)

    def field(self, owner: Any, name: str, default: Any = None) -> Any:
        props = {p.identifier: p for p in self.props(owner)}
        prop = props.get(name)
        if prop is None:
            return default
        if prop.is_runtime:
            refuse("A render dependency cannot use a runtime getter.", property=name)
        return getattr(owner, name)

    def native_pointer(self, owner: Any, name: str, fixed_type: str) -> Any:
        prop = next((p for p in self.props(owner) if p.identifier == name), None)
        if (
            prop is None
            or prop.is_runtime
            or not prop.is_readonly
            or prop.type != "POINTER"
            or getattr(prop, "is_registered", False)
            or prop.fixed_type.identifier != fixed_type
        ):
            refuse("Render checkpoint role requires its exact native pointer descriptor.", property=name)
        return getattr(owner, name)

    def checkpoint_roles(self, *, predicted: bool = False) -> tuple:
        settings = self.native_pointer(self.scene, "tool_settings", "ToolSettings")
        particle = self.native_pointer(settings, "particle_edit", "ParticleEdit")
        # ParticleEdit.is_editable/is_hair call PE_get_current and write these
        # roles. Never inspect them; the hidden Scene slot is proved by its
        # exact self consumer count and the source-pinned paired Object slot.
        if any(p.identifier == "scene" for p in self.props(particle)):
            refuse("An exposed ParticleEdit Scene role needs separate native review.")
        obj = self.native_pointer(particle, "object", "Object")
        original = self.native_pointer(self.scene, "original", "ID")
        active = self.bpy.context.view_layer.objects.active
        if active is None:
            refuse("Render checkpoint polling requires the frozen non-null active Object.")
        pair = int(self.scene.user_of_id(self.scene)), key(obj)
        if pair not in ((0, key(None)), (1, key(active))):
            refuse("Render ParticleEdit roles exceed their exact reviewed native states.")
        owners = key(settings), key(particle), key(original), key(active)
        return owners, ((1, key(active)) if predicted else pair)

    def header(self, owner: Any) -> None:
        self.props(owner)
        if (
            self.field(owner, "library") is not None
            or self.field(owner, "override_library") is not None
            or not self.field(owner, "is_editable", True)
        ):
            refuse("Render scope requires local editable non-override data.", owner=owner.name)
        if self.field(owner, "animation_data") is not None:
            refuse(
                "Animated inputs and drivers need a broader measured render dependency contract.",
                owner=owner.name,
            )

    def custom(self, owner: Any) -> tuple:
        try:
            names = bounded(owner.keys(), 128, "ID properties")
        except TypeError as error:
            if "doesn't support IDProperties" in str(error):
                return ()
            raise
        checkpoint = self.checkpoint_prefix is not None and owner.bl_rna.identifier == "Scene"
        marker = "_codex_bridge_undo_marker"
        if checkpoint and marker in names:
            raw = owner[marker]
            if (
                not isinstance(raw, str)
                or not raw.startswith(self.checkpoint_prefix)
                or re.fullmatch(r"BCB1:[0-9a-f]{32}:[0-9a-f]{32}", raw) is None
            ):
                refuse("Reserved native checkpoint marker is not owned by this checkpoint manager.")
        result = tuple(
            (str(name), value(owner[name], allow_ids=False, custom_scalars=True))
            for name in names
            if not (checkpoint and name == marker)
        )
        return (*result, (marker, "<validated checkpoint-owned marker>")) if checkpoint else result

    def primitive(
        self,
        owner: Any,
        exclude: frozenset[str] = frozenset(),
        *,
        predicted: dict[str, Any] | None = None,
        structural_identity: tuple | None = None,
    ) -> tuple:
        props = self.props(owner)
        data = []
        for prop in props:
            name = prop.identifier
            if (
                prop.is_runtime
                or prop.is_readonly
                or name in exclude
                or (int(owner.as_pointer()), name) in self.owned
                or prop.type == "COLLECTION"
            ):
                continue
            if prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER"}:
                refuse("Render RNA kind needs an explicit reader.", property=name)
            observed = value(
                predicted[name]
                if predicted is not None and name in predicted
                else getattr(owner, name)
            )
            if (
                self.checkpoint_prefix is not None
                and self.checkpoint_static
                and prop.type != "POINTER"
                and name != "name"
                and (owner.bl_rna.identifier, name)
                not in {
                    ("MaterialSlot", "link"),
                    ("CollectionLightLinking", "link_state"),
                    ("ShaderNodeUVMap", "uv_map"),
                    ("MeshPolygon", "material_index"),
                    ("Object", "active_material_index"),
                    ("MeshUVLoopLayer", "active"),
                    ("MeshUVLoopLayer", "active_render"),
                    ("MeshUVLoopLayer", "active_clone"),
                    ("LayerCollection", "exclude"),
                    ("LayerCollection", "holdout"),
                    ("LayerCollection", "indirect_only"),
                    ("LayerCollection", "hide_viewport"),
                    ("ViewLayer", "use"),
                }
            ):
                continue
            data.append((name, observed))
        signatures = tuple(
            (p.identifier, p.type, bool(p.is_readonly), bool(p.is_runtime), int(p.as_pointer()))
            for p in props
        )
        return (
            key(owner) if structural_identity is None else structural_identity,
            signatures,
            tuple(data),
            self.custom(owner),
        )

    def availability(self, node: Any, direction: str, socket: Any) -> dict[str, bool] | None:
        if (
            not self.predict_native_availability
            or direction != "inputs"
            or node.bl_rna.identifier != "ShaderNodeBsdfPrincipled"
        ):
            return None
        name = self.field(socket, "identifier")
        if name not in {"Subsurface IOR", "Subsurface Anisotropy"}:
            return None
        # Exact source receipts bind node_shader_update_principled, the RNA
        # custom2 enum, negative SOCK_UNAVAIL and node_set_socket_availability.
        # This prediction is frozen before providers. Ordinary snapshots retain
        # the actual raw flag, including before every pre-render owned write.
        build = self.bpy.app.build_hash.decode("ascii")
        if build not in {"62c1db4208e8", "d13f752e3b9c"}:
            refuse(
                "Principled native socket-availability prediction needs an exact reviewed build."
            )
        method = self.field(node, "subsurface_method")
        allowed = {"BURLEY", "RANDOM_WALK", "RANDOM_WALK_SKIN"} | (
            {"RANDOM_WALK_LEGACY"} if build == "d13f752e3b9c" else set()
        )
        if method not in allowed:
            refuse("Principled native subsurface method needs separate review.")
        prop = {p.identifier: p for p in self.props(socket)}.get("enabled")
        if prop is None or prop.type != "BOOLEAN" or prop.is_runtime or prop.is_readonly:
            refuse(
                "Principled native availability requires the reviewed writable boolean descriptor."
            )
        if name == "Subsurface IOR":
            return {"enabled": method == "RANDOM_WALK_SKIN"}
        return {"enabled": method != "BURLEY"} if build == "62c1db4208e8" else None

    def graph(self, owner: Any) -> tuple:
        tree = self.field(owner, "node_tree")
        if tree is None:
            return ()
        self.header(tree)
        nodes = bounded(self.field(tree, "nodes"), 128, "shader nodes")
        links = bounded(self.field(tree, "links"), 512, "shader links")
        self.nodes += len(nodes)
        self.links += len(links)
        if self.nodes > 512 or self.links > 2048:
            refuse("Render aggregate shader budget exceeded.")
        records = []
        for node in nodes:
            # Check exact native class before touching any custom node getter.
            if node.bl_rna.identifier not in NODES:
                refuse(
                    "Render accepts reviewed procedural shaders without images, groups or object/media dependencies.",
                    node_type=node.bl_rna.identifier,
                )
            self.props(node)
            sockets = []
            for direction in ("inputs", "outputs"):
                for socket in bounded(self.field(node, direction), 64, "node sockets"):
                    if socket.bl_rna.identifier not in SOCKETS:
                        refuse(
                            "Render socket kind needs explicit review.",
                            socket_type=socket.bl_rna.identifier,
                        )
                    self.props(socket)
                    sockets.append(
                        (
                            direction,
                            socket.identifier,
                            self.primitive(
                                socket, predicted=self.availability(node, direction, socket)
                            ),
                        )
                    )
            records.append((node.name, self.primitive(node), tuple(sockets)))
        for link in links:
            self.props(link)
        link_state = tuple(
            (
                key(link.from_node),
                link.from_socket.identifier,
                key(link.to_node),
                link.to_socket.identifier,
                bool(link.is_muted),
            )
            for link in links
        )
        return self.primitive(tree), tuple(records), link_state

    def mesh_array(
        self, mesh: Any, family: str, index: int, owner: Any, *, attribute: tuple | None = None
    ) -> tuple:
        if self.checkpoint_prefix is None:
            return self.primitive(owner)
        kind = owner.bl_rna.identifier
        approved = {
            "vertices": {"MeshVertex"},
            "edges": {"MeshEdge"},
            "loops": {"MeshLoop"},
            "polygons": {"MeshPolygon"},
            "attribute_data": {
                "FloatVectorAttributeValue",
                "Int2AttributeValue",
                "IntAttributeValue",
                "BoolAttributeValue",
                "Float2AttributeValue",
            },
        }
        if kind not in approved.get(family, ()) or self.bpy.app.build_hash.decode("ascii") not in {
            "62c1db4208e8",
            "d13f752e3b9c",
        }:
            refuse("Checkpoint mesh-array identity requires a measured native element role.")
        # Exact-build RNA iteration exposes *_for_write/ensure-mutable buffers.
        # Their address can relocate after native undo push without changing any
        # authored value. Only these measured ordered array elements use a
        # parent-Mesh/role/index identity; Main/graph/descriptors retain raw IDs.
        identity = ("native_mesh_array", key(mesh), family, attribute, index, kind)
        return self.primitive(owner, structural_identity=identity)

    def mesh(self, mesh: Any) -> tuple:
        if self.field(mesh, "has_custom_normals"):
            refuse("Authored custom split normals need a separate complete preservation reader.")
        if self.field(mesh, "shape_keys") is not None:
            refuse("Render shape-key/evaluated geometry requires a broader measured profile.")
        containers = [
            bounded(self.field(mesh, name), MAX_ELEMENTS, "mesh elements")
            for name in ("vertices", "edges", "loops", "polygons")
        ]
        self.elements += sum(len(items) for items in containers)
        if self.elements > MAX_ELEMENTS:
            refuse("Render aggregate base-geometry budget exceeded.")
        vertices, edges, loops, polygons = containers
        memberships = []
        for vertex in vertices:
            groups = bounded(self.field(vertex, "groups"), 256, "vertex memberships")
            memberships.append(tuple((self.field(g, "group"), self.primitive(g)) for g in groups))
        geometry = (
            tuple(
                (self.mesh_array(mesh, "vertices", index, v), memberships[index])
                for index, v in enumerate(vertices)
            ),
            tuple(
                (tuple(self.field(e, "vertices")), self.mesh_array(mesh, "edges", index, e))
                for index, e in enumerate(edges)
            ),
            tuple(
                (
                    int(self.field(v, "vertex_index")),
                    int(self.field(v, "edge_index")),
                    self.mesh_array(mesh, "loops", index, v),
                )
                for index, v in enumerate(loops)
            ),
            tuple(
                (
                    tuple(self.field(v, "vertices")),
                    int(self.field(v, "loop_start")),
                    int(self.field(v, "loop_total")),
                    self.mesh_array(mesh, "polygons", index, v),
                )
                for index, v in enumerate(polygons)
            ),
        )
        attrs = []
        for attr in bounded(self.field(mesh, "attributes"), 128, "mesh attributes"):
            self.props(attr)
            items = bounded(self.field(attr, "data"), MAX_ELEMENTS, "attribute data")
            self.elements += len(items)
            if self.elements > MAX_ELEMENTS:
                refuse("Render aggregate mesh-attribute budget exceeded.")
            attrs.append(
                (
                    attr.name,
                    attr.domain,
                    attr.data_type,
                    self.primitive(attr),
                    tuple(
                        self.mesh_array(
                            mesh,
                            "attribute_data",
                            index,
                            v,
                            attribute=(key(attr), attr.name, attr.domain, attr.data_type),
                        )
                        for index, v in enumerate(items)
                    ),
                )
            )
        ignored = (
            frozenset({"texspace_location", "texspace_size"})
            if self.field(mesh, "use_auto_texspace")
            else frozenset()
        )
        uv = self.field(mesh, "uv_layers")
        uv_props = self.props(uv)
        uv_state = tuple(
            (p.identifier, value(getattr(uv, p.identifier)))
            for p in uv_props
            if not p.is_readonly
            and not p.is_runtime
            and p.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER"}
        )
        uv_layers = tuple(self.primitive(layer) for layer in bounded(uv, 16, "UV layers"))
        return (
            self.primitive(mesh, ignored),
            geometry,
            tuple(attrs),
            tuple(key(m) for m in self.field(mesh, "materials")),
            uv_state,
            uv_layers,
        )

    def obj(self, obj: Any) -> tuple:
        self.header(obj)
        if self.field(obj, "mode") != "OBJECT":
            refuse("Every render dependency object must be in Object Mode.")
        if (
            self.field(obj, "type") not in {"MESH", "CAMERA", "LIGHT", "EMPTY"}
            or self.field(obj, "instance_type") != "NONE"
        ):
            refuse(
                "Render requires plain static meshes, cameras, lights and non-instanced empties."
            )
        if (
            self.field(obj, "parent") is not None
            or len(self.field(obj, "modifiers"))
            or len(self.field(obj, "constraints"))
            or len(self.field(obj, "particle_systems"))
        ):
            refuse(
                "Render parenting, modifiers, constraints and particles need a separately proven dependency closure."
            )
        if (
            self.field(obj, "rigid_body") is not None
            or self.field(obj, "rigid_body_constraint") is not None
        ):
            refuse("Render physical dependencies need a separately proven closure.")
        field = self.field(obj, "field")
        if field is not None and self.field(field, "type", "NONE") != "NONE":
            refuse("Render force fields need a separately proven closure.")
        groups = tuple(
            self.primitive(g)
            for g in bounded(self.field(obj, "vertex_groups"), 256, "vertex groups")
        )
        data = self.field(obj, "data")
        if data is not None:
            self.header(data)
            if obj.type == "EMPTY":
                refuse("Image empties are outside the procedural render contract.")
        slots = tuple(
            self.primitive(slot)
            for slot in bounded(self.field(obj, "material_slots"), 128, "object material slots")
        )
        light_linking = self.field(obj, "light_linking")
        return (
            self.primitive(obj, OBJECT_DERIVED),
            groups,
            slots,
            None if light_linking is None else self.primitive(light_linking),
        )

    def layer_collection(self, collection: Any, depth: int = 0) -> tuple:
        if depth > 8:
            refuse("Render collection nesting exceeds eight levels.")
        return (
            self.primitive(collection),
            key(self.field(collection, "collection")),
            tuple(
                self.layer_collection(c, depth + 1)
                for c in bounded(self.field(collection, "children"), 128, "layer collections")
            ),
        )

    def collection(self, owner: Any) -> tuple:
        self.header(owner)
        records = []
        for plain, wrapper, maximum in (
            ("objects", "collection_objects", MAX_OBJECTS),
            ("children", "collection_children", 128),
        ):
            actual = tuple(
                key(item)
                for item in bounded(self.field(owner, plain), maximum, "collection members")
            )
            wrapped = bounded(self.field(owner, wrapper), maximum, "collection light-link members")
            # Both exact native builds iterate the SAME gobject/children
            # ListBase for plain IDs and per-member wrappers. The wrappers do
            # not expose an object/collection pointer. Freeze their native
            # zipped order, member IDs, wrapper identities and linking fields.
            if len(actual) != len(wrapped) or len(set(actual)) != len(actual):
                refuse("Native collection/light-linking member identities are inconsistent.")
            members = []
            for target, item in zip(actual, wrapped, strict=True):
                self.props(item)
                linking = self.field(item, "light_linking")
                if linking is None:
                    refuse(
                        "Native collection members require their non-null light-linking settings."
                    )
                members.append((target, self.primitive(item), self.primitive(linking)))
            records.append((plain, actual, tuple(members)))
        return self.primitive(owner), tuple(records)

    def scene_state(self) -> tuple:
        scene = self.scene
        self.header(scene)
        render = self.field(scene, "render")
        native_engine(self.bpy, self.field(render, "engine"))
        if (
            self.field(scene, "node_tree") is not None
            or self.field(scene, "compositing_node_group") is not None
        ):
            refuse(
                "Compositor graphs, including File Output and nested/custom nodes, need a separate closed render contract."
            )
        sequencer = self.field(scene, "sequence_editor")
        if sequencer is not None and (
            len(self.field(sequencer, "strips_all", self.field(sequencer, "sequences_all", ())))
        ):
            refuse("Sequencer/media dependencies are outside the current render contract.")
        if (
            self.field(render, "use_multiview")
            or self.field(render, "use_freestyle")
            or self.field(scene, "timeline_markers")
        ):
            refuse(
                "Multiview, Freestyle and timeline-camera dependencies need separate render qualification."
            )
        if self.field(render, "use_motion_blur"):
            refuse(
                "Motion blur and its nested shutter curve need a separate complete render contract."
            )
        if self.field(self.field(scene, "view_settings"), "use_curve_mapping"):
            refuse("View curves need a separate bounded render reader.")
        layers = []
        for layer in bounded(self.field(scene, "view_layers"), 8, "view layers"):
            if len(self.field(layer, "aovs", ())) or len(self.field(layer, "lightgroups", ())):
                refuse("Custom AOV/light-group outputs need a separate render contract.")
            layer_eevee = self.field(layer, "eevee")
            layers.append(
                (
                    self.primitive(layer),
                    self.layer_collection(self.field(layer, "layer_collection")),
                    None if layer_eevee is None else self.primitive(layer_eevee),
                )
            )
        image = self.field(render, "image_settings")
        if self.field(image, "color_management", "FOLLOW_SCENE") != "FOLLOW_SCENE":
            refuse(
                "Per-image color-management overrides need a separate complete nested-settings reader."
            )
        settings = [self.primitive(render), self.primitive(image)]
        for name in (
            "view_settings",
            "display_settings",
            "sequencer_colorspace_settings",
            "eevee",
            "display",
            "unit_settings",
        ):
            owner = self.field(scene, name)
            if owner is not None:
                settings.append((name, self.primitive(owner)))
                if name == "eevee":
                    raytrace = self.field(owner, "ray_tracing_options")
                    if raytrace is not None:
                        settings.append(("ray_tracing_options", self.primitive(raytrace)))
        root = self.field(scene, "collection")
        self.header(root)
        root_state = self.collection(root)
        return (
            self.primitive(scene),
            root_state,
            tuple(settings),
            tuple(layers),
            () if sequencer is None else self.primitive(sequencer),
        )


def snapshot(
    bpy: Any,
    scene: Any,
    owned: frozenset[tuple[int, str]] = frozenset(),
    *,
    predict_native_availability: bool = False,
    checkpoint_prefix: str | None = None,
    checkpoint_static: bool = True,
    predict_checkpoint_roles: bool = False,
) -> tuple:
    """Complete admitted native dependencies, with only literal owned fields omitted."""
    require_raw_storage_reader(bpy)
    ctx = bpy.context
    if (
        ctx.scene != scene
        or ctx.window is None
        or ctx.window.scene != scene
        or ctx.window.view_layer != ctx.view_layer
        or ctx.mode != "OBJECT"
    ):
        refuse("Render requires the actual current Scene/window/view layer in Object Mode.")
    reader = Reader(
        bpy,
        scene,
        owned,
        predict_native_availability=predict_native_availability,
        checkpoint_prefix=checkpoint_prefix,
        checkpoint_static=checkpoint_static,
    )
    handlers = bpy.app.handlers
    for name in dir(handlers):
        if name.startswith(("render_", "composite_", "depsgraph_update_", "frame_change_")) and len(
            getattr(handlers, name)
        ):
            refuse(
                "Native render/frame/dependency handlers prevent a closed render contract.",
                handler=name,
            )
    windows = bounded(ctx.window_manager.windows, 8, "native windows")
    if windows != [ctx.window]:
        refuse("The initial render context requires one actual current native window.")
    reader.header(scene)
    native_engine(bpy, reader.field(reader.field(scene, "render"), "engine"))
    if predict_checkpoint_roles and checkpoint_prefix is None:
        refuse("Checkpoint role prediction requires a request-owned checkpoint ledger.")
    roles = reader.checkpoint_roles(predicted=predict_checkpoint_roles)
    incoming = bounded(bpy.data.user_map(subset={scene}).get(scene, ()), 64, "Scene consumers")
    loopbacks = [owner for owner in incoming if key(owner) == key(scene)]
    if loopbacks and (
        len(loopbacks) != 1
        or int(scene.user_of_id(scene)) != 1
        or reader.field(scene, "is_evaluated")
        or not scene.use_extra_user
    ):
        refuse("Scene has an unexplained self-reference beyond native checkpoint bookkeeping.")
    external = [owner for owner in incoming if key(owner) != key(scene)]
    wm_props = ctx.window_manager.bl_rna.properties
    if ctx.window_manager.bl_rna != bpy.types.WindowManager.bl_rna or any(
        wm_props.get(name) is not None and wm_props[name].is_runtime for name in ("windows", "name")
    ):
        refuse("WindowManager ownership readers require native descriptors.")
    wm_custom = reader.custom(ctx.window_manager)  # Refuse raw custom Scene/ID aliases.
    pin = ctx.workspace.bl_rna.properties.get("use_pin_scene")
    if (
        ctx.workspace.bl_rna != bpy.types.WorkSpace.bl_rna
        or pin is None
        or pin.is_runtime
        or pin.type != "BOOLEAN"
        or ctx.workspace.use_pin_scene
    ):
        refuse("The initial native render closure requires an unpinned native workspace.")
    reference_count = int(ctx.window_manager.user_of_id(scene))
    # Exact-build C visitors contain one USER_ONE win.scene and one NOP
    # win.unpinned_scene. With one Main Scene/Window and no raw ID aliases,
    # a second reference can only be that measured weak native Scene slot.
    # Native RNA does not expose unpinned_scene; other builds fail closed.
    build = bpy.app.build_hash.decode("ascii")
    reviewed_weak_slot = build in {"62c1db4208e8", "d13f752e3b9c"}
    if (
        len(external) != 1
        or external[0] != ctx.window_manager
        or reference_count not in ({1, 2} if reviewed_weak_slot else {1})
        or int(scene.users) - int(bool(scene.use_fake_user)) != 1
    ):
        refuse(
            "Render Scene has external consumers outside its actual current window context.",
            native_users=int(scene.users),
            fake_user=bool(scene.use_fake_user),
            consumers=[
                (owner.bl_rna.identifier, owner.name, int(owner.user_of_id(scene)))
                for owner in incoming
            ],
        )
    main_props = bounded(bpy.data.bl_rna.properties, 128, "Main properties")
    # Admit every Main owner and embedded evaluation graph before reading
    # authored primitive values. A later unused driver cannot be hidden by
    # an earlier object's lazy native getter.
    for prop in main_props:
        if prop.type != "COLLECTION" or prop.identifier == "all_ids":
            continue
        if prop.is_runtime:
            refuse("Runtime Main collections are unreviewed.")
        owners = bounded(getattr(bpy.data, prop.identifier), MAX_IDS, "Main admission")
        if owners and prop.identifier not in FAMILIES:
            refuse(
                "Render Main dependencies include an unreviewed ID family.", family=prop.identifier
            )
        if prop.identifier in UI:
            continue
        for owner in owners:
            reader.header(owner)
            if prop.identifier in {"materials", "worlds", "lights", "linestyles"}:
                tree = reader.field(owner, "node_tree")
                if tree is not None:
                    reader.header(tree)
                    for node in bounded(reader.field(tree, "nodes"), 128, "shader node admission"):
                        if node.bl_rna.identifier not in NODES:
                            refuse(
                                "Unreviewed image/group/custom shader node is refused before any node getter.",
                                node_type=node.bl_rna.identifier,
                            )
                        reader.props(node)
                        for direction in ("inputs", "outputs"):
                            for socket in bounded(
                                reader.field(node, direction), 64, "socket admission"
                            ):
                                if socket.bl_rna.identifier not in SOCKETS:
                                    refuse("Unreviewed socket class is refused before its getter.")
                                reader.props(socket)
    inventories, all_ids = [], set()
    aliases = []
    objects = []
    for prop in main_props:
        if prop.type != "COLLECTION":
            continue
        if prop.is_runtime:
            refuse("Runtime Main collections are unreviewed.")
        owners = bounded(getattr(bpy.data, prop.identifier), MAX_IDS, "Main IDs")
        if prop.identifier == "all_ids":
            aliases.append({key(o) for o in owners})
            continue
        if owners and prop.identifier not in FAMILIES:
            refuse(
                "Render Main dependencies include an unreviewed ID family.", family=prop.identifier
            )
        if prop.identifier == "scenes" and owners != [scene]:
            refuse("The initial render closure requires exactly the actual current Scene.")
        rows = []
        for owner in owners:
            all_ids.add(key(owner))
            if len(all_ids) > MAX_IDS:
                refuse("Render aggregate Main ID budget exceeded.")
            if prop.identifier in UI:
                # UI IDs are not evaluated or mutated. Read only native identity
                # and animation ownership, never plugin/UI runtime getters.
                animation = owner.bl_rna.properties.get("animation_data")
                if animation is not None and (
                    animation.is_runtime or owner.animation_data is not None
                ):
                    refuse("Animated UI IDs need a broader render closure.")
                if (
                    owner.bl_rna.identifier not in {"Screen", "WorkSpace", "WindowManager"}
                    or owner.bl_rna != getattr(bpy.types, owner.bl_rna.identifier).bl_rna
                ):
                    refuse("Render UI identity requires canonical native classes.")
                name_prop = owner.bl_rna.properties.get("name")
                if name_prop is None or name_prop.is_runtime:
                    refuse("Render UI names cannot invoke runtime getters.")
                rows.append((key(owner), owner.name, owner.bl_rna.identifier, reader.custom(owner)))
                continue
            reader.header(owner)
            kind = prop.identifier
            if kind == "images":
                role = (
                    reader.field(owner, "name"),
                    reader.field(owner, "source"),
                    reader.field(owner, "type"),
                )
                if role not in {
                    ("Render Result", "VIEWER", "RENDER_RESULT"),
                    ("Viewer Node", "VIEWER", "COMPOSITING"),
                }:
                    refuse(
                        "External/generated image inputs need approved stored-byte and pixel closure before rendering."
                    )
                if role[2] == "COMPOSITING":
                    rows.append((role, key(owner)))
                # Render Result is an explicitly disclosed native output buffer.
                continue
            if kind == "objects":
                objects.append(owner)
                if len(objects) > MAX_OBJECTS:
                    refuse("Render object budget exceeded.")
                rows.append(reader.obj(owner))
            elif kind == "meshes":
                rows.append(reader.mesh(owner))
            elif kind in {"materials", "worlds", "lights"}:
                nested = []
                for name in {
                    "materials": ("grease_pencil", "lineart"),
                    "worlds": ("light_settings", "mist_settings"),
                    "lights": (),
                }[kind]:
                    setting = reader.field(owner, name)
                    if setting is not None:
                        nested.append((name, reader.primitive(setting)))
                rows.append((reader.primitive(owner), reader.graph(owner), tuple(nested)))
            elif kind == "cameras":
                if (
                    len(reader.field(owner, "background_images"))
                    or reader.field(reader.field(owner, "dof"), "focus_object") is not None
                ):
                    refuse(
                        "Camera image/focus-object dependencies need a separate render contract."
                    )
                rows.append((reader.primitive(owner), reader.primitive(reader.field(owner, "dof"))))
            elif kind == "collections":
                rows.append(reader.collection(owner))
            elif kind == "palettes":
                rows.append(
                    (
                        reader.primitive(owner),
                        tuple(
                            reader.primitive(c)
                            for c in bounded(
                                reader.field(owner, "colors"), 256, "inactive palette colors"
                            )
                        ),
                    )
                )
            elif kind == "linestyles":
                if reader.field(owner, "node_tree") is not None:
                    refuse("Freestyle node dependencies need separate render review.")
                modifiers = []
                for name in (
                    "alpha_modifiers",
                    "color_modifiers",
                    "geometry_modifiers",
                    "thickness_modifiers",
                ):
                    items = bounded(
                        reader.field(owner, name, ()), 8, "inactive Freestyle modifiers"
                    )
                    if any(
                        item.bl_rna.identifier != "LineStyleGeometryModifier_Sampling"
                        for item in items
                    ):
                        refuse(
                            "Unreviewed inactive Freestyle modifier needs a separate render reader."
                        )
                    modifiers.append((name, tuple(reader.primitive(item) for item in items)))
                rows.append((reader.primitive(owner), tuple(modifiers)))
        inventories.append((prop.identifier, tuple(rows)))
    if any(alias != all_ids for alias in aliases):
        refuse("Main all_ids alias differs from the concrete native family inventory.")
    session = (
        key(scene),
        int(ctx.window.as_pointer()),
        int(ctx.view_layer.as_pointer()),
        bpy.data.filepath,
        ctx.mode,
        tuple(key(o) for o in bounded(ctx.selected_objects, MAX_OBJECTS, "selection")),
        key(ctx.view_layer.objects.active),
        int(scene.frame_current),
        float(scene.frame_subframe),
        key(ctx.screen),
        key(ctx.area),
        key(ctx.region),
        key(ctx.workspace),
        reference_count,
        wm_custom,
    )
    # Scene.original is preserved literally in roles. Native undo polling
    # changes only the independently predicted weak ParticleEdit pair.
    result = session, tuple(inventories), reader.scene_state(), roles
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
        refuse("Render preservation evidence exceeds 2 MiB.")
    return result


def digest(state: Any) -> str:
    return hashlib.sha256(
        json.dumps(state, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()
