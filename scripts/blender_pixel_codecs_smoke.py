"""Internal codec interoperability foundation, not a registered texture export tool."""
from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
import time
from array import array
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
from blender_codex_bridge import pixel_codecs as codecs  # noqa: E402


def expected(values, format, role):
    result = array("f")
    for offset in range(0, len(values), 4):
        rgba = list(values[offset:offset+4])
        if format.startswith("PNG"):
            if role == "COLOR":
                rgba[:3] = [12.92*v if v <= .0031308 else 1.055*v**(1/2.4)-.055 for v in rgba[:3]]
            maximum = 255 if format == "PNG8" else 65535
            rgba = [math.floor(v*maximum+.5)/maximum for v in rgba]
            if format == "PNG16" and role == "COLOR":
                # Native float ImBuf is scene-linear and associated, unlike the
                # encoded, unassociated channels physically stored in PNG16.
                rgba[:3] = [(v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4)*rgba[3] for v in rgba[:3]]
        elif format == "EXR32" and role == "COLOR":
            rgba[:3] = [v*rgba[3] for v in rgba[:3]]
        result.extend(rgba)
    return result


def run():
    assert bpy.app.background, "Use the non-interrupting runner, never a visible window"
    bpy.context.preferences.use_preferences_save = False
    reports = []
    with tempfile.TemporaryDirectory(prefix="bridge-pixel-codecs-") as temporary:
        folder = Path(temporary)
        for format in ("PNG8", "PNG16", "EXR32", "EXR32_RAW"):
            for role in ("COLOR", "DATA"):
                if format.startswith("PNG"):
                    values = array("f", [.25,.5,.75,.25, .1,.2,.3,0., .9,.8,.7,1., .3,.2,.1,.5])*3
                else:
                    values = array("f", [4.,2.,1.,.25, -.125,65536.,1.234567,0., .9,.8,.7,1., .3,.2,.1,.5])*3
                    if role == "DATA":
                        values[3], values[7] = -2., 2.
                # Native row orientation is independently observable, not only
                # verified by a constant-color file or our own parser.
                base = values[:16]
                for row in range(3):
                    shift = row*4
                    values[row*16:(row+1)*16] = base[shift:] + base[:shift]
                layout = codecs.interpretation(format, role)
                path = folder / (format+"-"+role+layout["extension"])
                before = hashlib.sha256(values).hexdigest()
                maximum_block, steps = 0, 0
                with path.open("xb") as stream:
                    for step in codecs.encode_steps(values, 4, 3, format, role):
                        stream.write(step.data)
                        maximum_block = max(maximum_block, len(step.data))
                        steps += 1
                assert hashlib.sha256(values).hexdigest() == before
                image = bpy.data.images.load(str(path), check_existing=False)
                image.colorspace_settings.name = layout["colorspace"]
                image.alpha_mode = layout["reopen_alpha_mode"]
                assert tuple(image.size) == (4,3) and image.channels == 4
                actual = array("f", [0.])*len(values)
                image.pixels.foreach_get(actual)
                anticipated = expected(values, format, role)
                error = max(abs(a-b) for a,b in zip(actual, anticipated, strict=True))
                reports.append({"format": format, "role": role, "alpha_mode": image.alpha_mode,
                    "colorspace": image.colorspace_settings.name, "is_float": bool(image.is_float),
                    "max_expected_storage_error": error, "first_pixels": list(actual[:8]),
                    "expected_first_pixels": list(anticipated[:8]), "source_unchanged": True,
                    "file_alpha_mode": layout["alpha_mode"], "native_png16_color_is_linear_associated": format == "PNG16" and role == "COLOR",
                    "bytes": path.stat().st_size, "maximum_emitted_block_bytes": maximum_block, "steps": steps})
        print("PIXEL_CODEC_OBSERVATIONS " + json.dumps(reports), flush=True)
        # Native OCIO float conversion is not bit-identical to the independent
        # double standard-sRGB reference. Bound it explicitly in encoded-channel
        # units; the PNG byte/quantization unit tests are exact and separate.
        assert all(row["max_expected_storage_error"] < (2/65535 if row["format"] == "PNG16" and row["role"] == "COLOR" else 1e-6) for row in reports), reports
        # Exercise the full 4K float payload with native reopening, without a
        # second encoded file-sized bytes copy or hidden-alpha loss.
        from blender_large_paint_smoke import check_memory_headroom
        available = check_memory_headroom()
        values = array("f", [.25,-.125,65536.,-2.]) * (4096*4096)
        for x,y,rgba in ((0,0,[-0.,1.,2.,3.]), (4095,0,[4.,5.,6.,7.]),
                         (0,4095,[-1.,-2.,-3.,-4.]), (4095,4095,[8.,9.,10.,11.])):
            start = (y*4096+x)*4
            values[start:start+4] = array("f", rgba)
        source_digest = hashlib.sha256(values).hexdigest()
        path = folder / "large-raw.exr"
        maximum_block, steps = 0, 0
        started = time.perf_counter()
        with path.open("xb") as stream:
            for step in codecs.encode_steps(values, 4096, 4096, "EXR32_RAW", "DATA"):
                stream.write(step.data)
                maximum_block = max(maximum_block, len(step.data))
                steps += 1
        encode_seconds = time.perf_counter()-started
        assert path.stat().st_size <= codecs.MAX_ENCODED_BYTES
        image = bpy.data.images.load(str(path), check_existing=False)
        image.colorspace_settings.name, image.alpha_mode = "Non-Color", "CHANNEL_PACKED"
        assert tuple(image.size) == (4096,4096) and image.channels == 4
        actual = array("f", [0.])*len(values)
        image.pixels.foreach_get(actual)
        assert hashlib.sha256(actual).hexdigest() == source_digest == hashlib.sha256(values).hexdigest()
        large = {"size": [4096,4096], "file_bytes": path.stat().st_size, "source_digest": source_digest,
            "native_full_digest_match": True, "maximum_emitted_block_bytes": maximum_block,
            "steps": steps, "encode_seconds": encode_seconds, "host_available_bytes_at_start": available,
            "scope": "Codec/native raw-channel round trip, not a publication/job/memory-pressure or production throughput verdict"}
    print("BLENDER_PIXEL_CODECS_OK " + json.dumps({"blender": bpy.app.version_string,
        "observations": reports, "export_tool_registered": False,
        "public_exr_import_implemented": False, "source_arrays_unchanged": True,
        "large": large,
        "project_saved": False, "user_preferences_saved": False}), flush=True)


run()
