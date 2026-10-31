"""Bounded owned-node catalog research; no instance-getter/product qualification.

Import is inert. Run only through the isolated native runner. Configuration
observations are one-field-at-a-time, never a claim of Cartesian coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from pathlib import Path

PROFILE = "CLOTH_G0_AUTHORED_CATALOG_RESEARCH_V1"
MARKER = "BLENDER_CLOTH_G0_CATALOG_OK "
REPORT_NAME = "cloth-g0-catalog.json"
MAX_REPORT = 32 * 1024**2
MAX_CONFIGURATIONS = 2048
MAX_CLASSES = 512
MAX_PROPERTIES = 512
MAX_ENUM_ITEMS = 128
MAX_SOCKETS = 128
MAX_SECONDS = 270
TREE_TYPES = ("ShaderNodeTree", "CompositorNodeTree", "GeometryNodeTree")
OWNER_TYPES = ("Scene", "Material", "World", "PointLight", "AreaLight", "SpotLight", "SunLight", "FreestyleLineStyle")
INTERFACE_TYPES = ("NodeTreeInterfacePanel", "NodeTreeInterfaceSocketBool", "NodeTreeInterfaceSocketColor",
    "NodeTreeInterfaceSocketFloat", "NodeTreeInterfaceSocketInt", "NodeTreeInterfaceSocketRotation",
    "NodeTreeInterfaceSocketShader", "NodeTreeInterfaceSocketVector")
BUILDS = {b"62c1db4208e8": (4, 5, 14), b"d13f752e3b9c": (5, 2, 2)}
LEGACY_NODES = frozenset({
    "CompositorNodeComposite", "CompositorNodeGroup", "CompositorNodeRGB", "CompositorNodeValue",
    "GeometryNodeCurvePrimitiveCircle", "GeometryNodeCurvePrimitiveLine", "GeometryNodeCurveToMesh",
    "GeometryNodeCurveToPoints", "GeometryNodeDeleteGeometry", "GeometryNodeDuplicateElements",
    "GeometryNodeExtrudeMesh", "GeometryNodeGeometryToInstance", "GeometryNodeGroup", "GeometryNodeInputID",
    "GeometryNodeInputIndex", "GeometryNodeInputNamedAttribute", "GeometryNodeInputNormal",
    "GeometryNodeInputPosition", "GeometryNodeInputSceneTime", "GeometryNodeInstanceOnPoints",
    "GeometryNodeJoinGeometry", "GeometryNodeMergeByDistance", "GeometryNodeMeshCircle", "GeometryNodeMeshCone",
    "GeometryNodeMeshCube", "GeometryNodeMeshCylinder", "GeometryNodeMeshGrid", "GeometryNodeMeshIcoSphere",
    "GeometryNodeMeshLine", "GeometryNodeMeshToPoints", "GeometryNodeMeshUVSphere", "GeometryNodePointsToVertices",
    "GeometryNodeRealizeInstances", "GeometryNodeRemoveAttribute", "GeometryNodeRepeatInput", "GeometryNodeRepeatOutput",
    "GeometryNodeResampleCurve", "GeometryNodeRotateInstances", "GeometryNodeScaleInstances",
    "GeometryNodeSetCurveRadius", "GeometryNodeSetPosition", "GeometryNodeSetShadeSmooth",
    "GeometryNodeSimulationInput", "GeometryNodeSimulationOutput", "GeometryNodeStoreNamedAttribute",
    "GeometryNodeSubdivideMesh", "GeometryNodeSubdivisionSurface", "GeometryNodeSwitch", "GeometryNodeTransform",
    "GeometryNodeTranslateInstances", "NodeFrame", "NodeGroupInput", "NodeGroupOutput", "NodeReroute",
    "ShaderNodeAddShader", "ShaderNodeBackground", "ShaderNodeBsdfDiffuse", "ShaderNodeBsdfGlass",
    "ShaderNodeBsdfPrincipled", "ShaderNodeBsdfTransparent", "ShaderNodeClamp", "ShaderNodeCombineXYZ",
    "ShaderNodeEmission", "ShaderNodeGroup", "ShaderNodeMapRange", "ShaderNodeMath", "ShaderNodeMix",
    "ShaderNodeMixRGB", "ShaderNodeMixShader", "ShaderNodeNormalMap", "ShaderNodeOutputLight",
    "ShaderNodeOutputMaterial", "ShaderNodeOutputWorld", "ShaderNodeRGB", "ShaderNodeSeparateXYZ",
    "ShaderNodeTexGradient", "ShaderNodeTexNoise", "ShaderNodeTexVoronoi", "ShaderNodeTexWave",
    "ShaderNodeUVMap", "ShaderNodeValToRGB", "ShaderNodeValue", "ShaderNodeVectorMath", "ShaderNodeVectorTransform",
})
SEED_TYPES = ("ID", "Node", "NodeSocket", "NodeLink", "NodeTree", "NodeTreeInterface", "Image", "ImageUser",
    "PackedFile", "ColorManagedInputColorspaceSettings", "TexMapping", "ColorMapping", "ColorRamp",
    "ColorRampElement", "ColorRampElements", "NodePanelState")
GAPS = ("CONFIGURATION_CARTESIAN_PRODUCT_UNOBSERVED", "INSTANCE_PAYLOAD_GETTERS_UNQUALIFIED",
    "INTERFACE_AND_ZONE_ITEM_INSTANCE_AUTHORING_UNOBSERVED", "IMAGE_TILES_VIEWS_FRAMES_PAYLOAD_UNOBSERVED",
    "ENUM_IDENTIFIERS_ABOVE128_UNOBSERVED")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def fingerprints(root):
    paths = [root / "scripts/blender_cloth_storage_g0_catalog_smoke.py", root / "scripts/run_blender_checks.py"]
    paths.extend(sorted((root / "addon/blender_codex_bridge").rglob("*.py")))
    if not 3 <= len(paths) <= 512:
        raise ValueError("G0_SOURCE_COUNT")
    result = {}
    for path in paths:
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root) or path.stat().st_size > 2 * 1024**2:
            raise ValueError("G0_SOURCE_PATH")
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def bounded(values, maximum, label):
    size = len(values)
    if type(size) is not int or not 0 <= size <= maximum:
        raise ValueError("G0_BOUND:" + label)
    result = tuple(values)
    if len(result) != size:
        raise ValueError("G0_CHANGED:" + label)
    return result


def enum_observation(prop):
    """Retain an over-cap declaration without iterating or sampling its items."""
    items = prop.enum_items
    count = len(items)
    if type(count) is not int or not 0 <= count <= 2**31 - 1:
        raise ValueError("G0_ENUM_COUNT_SHAPE")
    if count > MAX_ENUM_ITEMS:
        return {"enum_identifiers": [], "enum_declared_count": count,
                "enum_separator_count": None, "enum_identifiers_complete": False}
    entries = bounded(items, MAX_ENUM_ITEMS, "enum_items")
    result = tuple(item.identifier for item in entries if item.identifier)
    if any(type(value) is not str or len(value) > 128 for value in result) or len(set(result)) != len(result):
        raise ValueError("G0_ENUM_SHAPE")
    return {"enum_identifiers": list(result), "enum_declared_count": count,
            "enum_separator_count": count - len(result), "enum_identifiers_complete": True}


def metadata(prop, owner_class):
    kind = prop.type
    fixed = prop.fixed_type if kind in {"POINTER", "COLLECTION"} else None
    wrapper = getattr(prop, "srna", None) if kind in {"POINTER", "COLLECTION"} else None
    result = {"identifier": prop.identifier, "type": kind, "readonly": prop.is_readonly,
        "runtime": prop.is_runtime, "registered": prop.is_registered,
        "array_length": prop.array_length if kind in {"BOOLEAN", "INT", "FLOAT"} else None,
        "fixed_type": None if fixed is None else fixed.identifier,
        "srna": None if wrapper is None else wrapper.identifier}
    if kind == "ENUM":
        observation = enum_observation(prop)
        result.update(enum_flag=prop.is_enum_flag, **observation)
        result["enum_refusal"] = None if observation["enum_identifiers_complete"] else {
            "owner_class": owner_class, "property": prop.identifier, "reason": "ENUM_METADATA_CAP",
            "declared_count": observation["enum_declared_count"], "maximum_items": MAX_ENUM_ITEMS,
            "identifiers_observed": 0}
    return result


def configurations(properties):
    """Declared finite OAT plan; callers retain skips and failed assignments."""
    result, skipped = [(None, None)], []
    for prop in properties:
        if prop.is_readonly or prop.is_runtime or prop.identifier.startswith("bl_"):
            continue
        if prop.type == "BOOLEAN" and prop.array_length == 0:
            result.extend((prop.identifier, value) for value in (False, True))
        elif prop.type == "ENUM":
            observation = enum_observation(prop)
            if not observation["enum_identifiers_complete"]:
                skipped.append({"field": prop.identifier, "reason": "ENUM_CONFIGURATION_CAP",
                    "declared_count": observation["enum_declared_count"], "maximum_items": MAX_ENUM_ITEMS})
                continue
            if prop.is_enum_flag:
                skipped.append({"field": prop.identifier, "reason": "ENUM_FLAG_POWERSET_UNOBSERVED"})
                continue
            identifiers = observation["enum_identifiers"]
            result.extend((prop.identifier, value) for value in identifiers)
            if not identifiers:
                skipped.append({"field": prop.identifier, "reason": "DYNAMIC_ENUM_ITEMS_UNOBSERVED"})
    return result, skipped


def collect(bpy, legacy):
    """Create only owned node groups. Never inspect socket default VALUES."""
    if frozenset(legacy.NODE_TYPES) != LEGACY_NODES:
        raise ValueError("G0_LEGACY_NODE_SET_CHANGED")
    started = time.monotonic()
    catalogs, rows, refusals, owned = {}, [], [], []
    pending = set((*SEED_TYPES, *TREE_TYPES, *OWNER_TYPES, *INTERFACE_TYPES, *LEGACY_NODES))

    def check():
        if time.monotonic() - started > MAX_SECONDS:
            raise ValueError("G0_INTERNAL_DEADLINE")

    def catalog(name):
        check()
        if name in catalogs:
            return catalogs[name]
        if len(catalogs) >= MAX_CLASSES:
            raise ValueError("G0_CLASS_BOUND")
        cls = getattr(bpy.types, name, None)
        if cls is None:
            result = {"present": False}
        else:
            rna = cls.bl_rna
            if rna.identifier != name:
                raise ValueError("G0_CLASS_IDENTIFIER")
            props = [metadata(prop, name) for prop in bounded(rna.properties, MAX_PROPERTIES, name + ".properties")]
            if len({prop["identifier"] for prop in props}) != len(props):
                raise ValueError("G0_DUPLICATE_PROPERTY")
            result = {"present": True, "identifier": name, "base": None if rna.base is None else rna.base.identifier,
                "properties": props, "functions": [fn.identifier for fn in bounded(rna.functions, 128, name + ".functions")]}
            result["sha256"] = hashlib.sha256(canonical(result)).hexdigest()
        catalogs[name] = result
        return result

    for name in sorted(pending):
        catalog(name)
    # Record node-owned fixed-target declarations without traversing every ID
    # pointer into Main or implicitly authorizing any instance getter.
    for name in sorted(LEGACY_NODES):
        if not catalogs[name]["present"]:
            continue
        for prop in catalogs[name]["properties"]:
            for target in (prop["fixed_type"], prop["srna"]):
                if target is not None:
                    catalog(target)
    count, plan_completed = 0, True
    try:
        for family in TREE_TYPES:
            tree = bpy.data.node_groups.new("BCB owned G0 " + family, family)
            owned.append(tree)
            for name in sorted(LEGACY_NODES):
                check()
                # Let the native constructor report every family/node refusal;
                # a class-name prefix does not establish compatibility.
                try:
                    probe = tree.nodes.new(name)
                except (RuntimeError, TypeError, ValueError) as error:
                    refusals.append({"tree": family, "node": name, "field": None, "reason": "NODE_CREATE_REFUSED",
                                     "error_type": type(error).__name__})
                    continue
                try:
                    plan, skipped = configurations(bounded(type(probe).bl_rna.properties, MAX_PROPERTIES, name))
                    for item in skipped:
                        refusals.append({"tree": family, "node": name, **item})
                finally:
                    tree.nodes.remove(probe)
                for field, value in plan:
                    check()
                    if count >= MAX_CONFIGURATIONS:
                        refusals.append({"tree": family, "node": name, "field": field,
                                         "value": value, "reason": "CONFIGURATION_CAP"})
                        plan_completed = False
                        continue
                    count += 1
                    node = tree.nodes.new(name)
                    try:
                        if field is not None:
                            try:
                                setattr(node, field, value)
                            except (RuntimeError, TypeError, ValueError) as error:
                                refusals.append({"tree": family, "node": name, "field": field,
                                    "value": value, "reason": "CONFIGURATION_SET_REFUSED", "error_type": type(error).__name__})
                                continue
                        directions = {}
                        for direction in ("inputs", "outputs"):
                            sockets = []
                            for socket in bounded(getattr(node, direction), MAX_SOCKETS, name + "." + direction):
                                kind = socket.bl_rna.identifier
                                row = catalog(kind)
                                default = next((prop for prop in row["properties"] if prop["identifier"] == "default_value"), None)
                                sockets.append({"class": kind, "identifier": socket.identifier, "name": socket.name,
                                    "default_property": default, "default_value_read": False})
                            directions[direction] = sockets
                        rows.append({"tree": family, "node": name, "field": field, "value": value, **directions})
                    finally:
                        tree.nodes.remove(node)
        return catalogs, rows, refusals, count, plan_completed
    finally:
        for tree in reversed(owned):
            bpy.data.node_groups.remove(tree)


def owned_profile(report):
    parent = report.parent
    if (sys.platform != "linux" or not report.is_absolute() or report.name != REPORT_NAME or report.exists()
            or report.is_symlink() or parent.is_symlink() or parent.resolve(strict=True) != parent
            or parent.stat().st_uid != os.getuid() or stat.S_IMODE(parent.stat().st_mode) != 0o700):
        raise ValueError("G0_PRIVATE_PROFILE")
    if any(os.environ.get(key) != str(parent) for key in ("TEMP", "TMP", "TMPDIR")):
        raise ValueError("G0_TEMP_PROFILE")
    for key in ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES",
                "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        if os.environ.get(key) != str(parent / ("worker-" + key.lower())):
            raise ValueError("G0_USER_PROFILE")
    if Path.cwd() != parent / "working" or "PYTHONPATH" in os.environ or "PYTHONHOME" in os.environ:
        raise ValueError("G0_WORKING_PROFILE")
    token = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("G0_PROCESS_TOKEN")
    return token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-report", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    token = owned_profile(args.bridge_report)
    import bpy

    if (not bpy.app.background or "--factory-startup" not in sys.argv or "--disable-autoexec" not in sys.argv
            or bpy.app.build_type != b"Release" or tuple(bpy.app.version) != BUILDS.get(bpy.app.build_hash)):
        raise ValueError("G0_OFFICIAL_BACKGROUND_BUILD")
    root = Path(__file__).resolve().parents[1]
    sources = fingerprints(root)
    sys.path.insert(0, str(root / "addon"))
    from blender_codex_bridge.tools import _rigid_evaluation_scope as legacy

    started = time.monotonic()
    catalogs, rows, refusals, count, plan_completed = collect(bpy, legacy)
    if fingerprints(root) != sources:
        raise ValueError("G0_SOURCE_CHANGED")
    full = {"schema": "cloth_g0_catalog_research_v1", "profile": PROFILE, "completed": True,
        "process_instance": token, "process_id": os.getpid(), "blender_version": bpy.app.version_string,
        "source_build": bpy.app.build_hash.decode(), "source_fingerprints": sources,
        "source_snapshot_sha256": hashlib.sha256(canonical(sources)).hexdigest(), "catalogs": catalogs,
        "legacy_nodes": sorted(LEGACY_NODES), "configuration_rows": rows, "refusals": refusals,
        "configuration_attempts": count, "plan_completed": plan_completed,
        "coverage": {"method": "DEFAULT_PLUS_ENUM_BOOL_ONE_FIELD_AT_A_TIME", "complete": False,
                     "gaps": list(GAPS), "instance_getters_qualified": False, "product_qualified": False,
                     "windows_qualified": False},
        "effects": {"owned_nodegroup_authoring": True, "socket_default_values_read": False,
                    "image_pixels_read": False, "frame_evaluation": False, "project_save": False,
                    "preferences_access": False, "runtime_started": False},
        "seconds": time.monotonic() - started}
    raw = canonical(full) + b"\n"
    if not 0 < len(raw) <= MAX_REPORT:
        raise ValueError("G0_REPORT_BOUND")
    descriptor = os.open(args.bridge_report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    compact = {key: full[key] for key in ("profile", "completed", "process_instance", "process_id",
        "blender_version", "source_build", "source_snapshot_sha256")}
    compact["full_receipt"] = {"path": str(args.bridge_report), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    print(MARKER + canonical(compact).decode(), flush=True)


if __name__ == "__main__":
    main()
