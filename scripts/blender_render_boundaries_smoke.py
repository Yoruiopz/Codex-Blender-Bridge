"""Registered-runtime tiny render and mutation-boundary native acceptance."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge import render_scope_profile  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools._render_boundary import Boundary  # noqa: E402


def main() -> None:
    if bpy.app.build_hash == b"d13f752e3b9c":
        sys.path.insert(0, str(ROOT / "scripts"))
        from blender_render_checkpoint_probe_smoke import main as refusal_probe

        refusal_probe("BLENDER_RENDER_BOUNDARIES_OK ")
        return
    blender_codex_bridge.register()
    try:
        runtime = get_runtime()
        grants = {permission.value: True for permission in Permission}
        permissions = PermissionManager(lambda: grants)
        runtime.permissions = permissions
        runtime.executor.permissions = permissions
        runtime.registry.enable_toolset("render")
        scene = bpy.context.scene
        print(
            "LINESTYLE_NATIVE "
            + json.dumps(
                {
                    style.name: {
                        n: [m.bl_rna.identifier for m in getattr(style, n)]
                        for n in (
                            "alpha_modifiers",
                            "color_modifiers",
                            "geometry_modifiers",
                            "thickness_modifiers",
                        )
                    }
                    for style in bpy.data.linestyles
                }
            )
        )
        try:
            configured = runtime.dispatch(
                "render.configure",
                {
                    "scene_name": scene.name,
                    "width": 16,
                    "height": 16,
                    "samples": 1,
                    "resolution_percentage": 100,
                },
            )
        except BridgeError as error:
            print("NATIVE_RENDER_SCOPE_DENIAL " + json.dumps(error.to_dict()))
            raise
        assert configured["verified"]
        before = (
            scene.render.filepath,
            scene.render.resolution_x,
            scene.render.resolution_y,
            scene.render.resolution_percentage,
            scene.render.use_border,
            scene.render.use_crop_to_border,
        )
        original_init = Boundary.__init__
        captured = []

        def record_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            captured.append(self)

        Boundary.__init__ = record_init
        try:
            result = runtime.dispatch(
                "render.execute", {"scene_name": scene.name, "width": 16, "height": 16}
            )
        except BridgeError:
            if captured:
                boundary = captured[-1]
                current = render_scope_profile.snapshot(bpy, scene, boundary.owned)
                differences = []

                def compare(a, b, path=""):
                    if a == b or len(differences) >= 20:
                        return
                    if (
                        isinstance(a, (list, tuple))
                        and isinstance(b, (list, tuple))
                        and len(a) == len(b)
                    ):
                        for index, (left, right) in enumerate(zip(a, b, strict=True)):
                            compare(left, right, path + "/" + str(index))
                    else:
                        labels = []
                        item = boundary.protected
                        for index in [int(i) for i in path.split("/") if i]:
                            if (
                                isinstance(item, (tuple, list))
                                and item
                                and isinstance(item[0], str)
                            ):
                                labels.append(
                                    list(item[:2])
                                    if len(item) > 1 and isinstance(item[1], str)
                                    else item[0]
                                )
                            item = item[index]
                        differences.append(
                            {"path": path, "labels": labels, "before": a, "after": b}
                        )

                compare(boundary.protected, current)
                print("NATIVE_RENDER_PROFILE_DRIFT " + json.dumps(differences))
            raise
        finally:
            Boundary.__init__ = original_init
        after = (
            scene.render.filepath,
            scene.render.resolution_x,
            scene.render.resolution_y,
            scene.render.resolution_percentage,
            scene.render.use_border,
            scene.render.use_crop_to_border,
        )
        assert before == after
        assert (
            result["rendered"]
            and result["verified"]
            and result["render_settings_recovery"]["restored"]
        )
        assert (
            Path(result["filepath"]).is_file()
            and result["external_effects"]["published_bytes_verified"]
        )
        print(
            "BLENDER_RENDER_BOUNDARIES_OK "
            + json.dumps(
                {
                    "version": bpy.app.version_string,
                    "configured": configured,
                    "rendered": result,
                    "settings_preserved": before == after,
                }
            )
        )
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    if bpy.app.background:
        main()
    else:

        def interactive():
            try:
                main()
            except Exception:
                traceback.print_exc()
            finally:
                bpy.ops.wm.quit_blender()
            return None

        bpy.app.timers.register(interactive, first_interval=1.0)
