# Exact-object framing native fixture

`viewport_framing` is an opt-in interactive case in `scripts/run_blender_checks.py`.
Run it only through that runner on a separately managed test display on Linux;
Windows testing remains paused. The runner retains its existing private-desktop
requirement on Windows. At frozen source `447ef57`, the fixture passed on Linux
Blender 4.5.14 and 5.2.2, with eight captures per build and independent host pixel
review of all sixteen images. This is focused development evidence.

```text
python scripts/run_blender_checks.py --blender /path/to/blender --case viewport_framing --output build/framing-native-unique
```

The factory scene contains an off-origin, rotated, nonuniformly scaled red cuboid,
a selected active peer and an initially hidden peer. The fixture uses exactly eight
actual typed `viewport.capture` calls with `frame_object: true`: all six named axes,
current perspective and current orthographic. Portrait, landscape and square output
sizes are covered. Flat Object-color solid shading and a dark viewport background
make the cuboid separable by a host-side red-pixel mask without Pillow in Blender.
No camera is moved or added, and no framing operator is called.

A fixture-only observer reads the actual temporary fitted viewport RNA before
restoration. It calls the original restoration in `finally`, including when a
measurement fails. Independent standard world look/up vectors qualify named axes;
current views must retain their prior look/up vectors and projection type. The
observer constructs conventional world-to-view and clip matrices from the measured
state and projects the eight previously evaluated world corners. It never calls
or repeats the production fit-distance solver. The exact-build viewport viewplane
mapping is documented and pinned by the earlier [framing source review](viewport-framing.md).
The numeric receipt checks finite coordinates, clipping and the fixed frame margin.

Each capture has a retained PNG and JSON receipt in the runner's owned temporary
evidence directory. Receipts contain the world corners, projected corners, matrices,
expected pixel bounds in top-left image coordinates, and authoritative before/after
context. The latter checks view, lens, projection, shading, overlays, camera identity,
render output/border/image/sampling settings, visibility, selection, active object,
mode, object transforms/data/material identities and object/mesh/camera/material
inventory. Draw caches and the documented Render Result replacement are excluded.
All compared fields are exact except quaternion accessor round trips, which allow
sign-equivalent components within `2e-6`; both rotations must remain unit length.
Camera-view and Edit-mode refusals retain equivalent before/after evidence.

A successful native marker requires all eight captures and restoration checks.
It reports PNG/receipt paths and SHA-256 digests. It does **not** declare the images
visually accepted: host-side review must independently verify a nonempty red mask,
its bounds against the recorded projected pixel bounds, and the expected margin.
Native execution and pixel review qualify only the exact tested source/build pair.
The fixture does not save a project or preferences, qualify armed artist-plan capture,
run on a user's project, or establish full artist-loop 1.0 acceptance.

The retained report is `build/viewport-axis-native-20261023/native/report.json`
(SHA-256 `e56906933fa6edb58e938b316ffb1b4fcf80b77a0ed8b25c1c87223c58f5bcb7`).
Its 316 Python source files have fingerprint
`e0e381a70cfdada4e0bced10d8c4668409de1a8e9b61820d61642e820112a778`.
The independent audit (`independent-audit.json`, SHA-256
`56adfd9afa1c920b165dbc5838ae01f518fda01f6bbcc60cb901a17f2db669b7`)
verified every reported source, PNG and receipt digest. The host mask required
`R > 70`, `R > 1.8G`, `R > 1.8B`, nonempty coverage of at least one percent,
at least four percent margin on each border and projected-bound error at most
2.5 pixels; all passed, with maximum observed bound error below 0.630 pixels.
A retained contact sheet was visually reviewed for visibility, cropping and axis
silhouette. These local reports and images are retained separately from CI artifacts;
they are not packaged-installation or full release evidence.
