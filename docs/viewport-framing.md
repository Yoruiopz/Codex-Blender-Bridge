# Exact-object viewport framing

`viewport.capture` accepts an optional strict boolean `frame_object`, defaulting to
`false`. Existing calls retain their current framing. `object_name` alone temporarily
isolates the named object; it does not move the view toward an offscreen object.

Use `frame_object: true` with an exact, nonempty `object_name` to fit that object's
evaluated bounding box into the requested image dimensions. This supports `current`
and the six named axis views. A current perspective or orthographic view keeps its
orientation and projection type. Named axis views use Blender's canonical orientation
and orthographic projection.
Framing changes only temporary viewport state; it does not move geometry or a camera.

```json
{
  "object_name": "SurfacePlane",
  "frame_object": true,
  "view": "top",
  "shading": "solid",
  "include_overlays": false,
  "resolution": [768, 512]
}
```

Framing requires a desktop 3D viewport in Object mode and a currently visible target
in the current scene and view layer. Supported object types are `MESH`, `CURVE`,
`SURFACE`, `FONT` and `META`. Camera framing, headless framing, locked or clipped
views, local views and quad views are outside this bounded feature. Invisible targets,
unavailable or nonfinite bounds, and bounds that cannot fit within the existing
near/far clipping range fail explicitly. The feature does not expose lens, clip,
camera, arbitrary orientation, or selection controls.

The fit uses eight evaluated bounding-box corners transformed into world space,
then into the chosen view orientation. It accounts for requested output aspect
ratio and leaves a fixed 5% border. Its projection math follows Blender's
native viewport path: `ED_view3d_draw_offscreen_imbuf` calls
`ED_view3d_viewplane_get` with the output dimensions; that function uses
`BKE_camera_params_from_view3d` and `BKE_camera_params_compute_viewplane`.
Canonical axis orientations come from `view3d_quat_axis`, inverted for the
`RegionView3D.view_rotation` RNA accessor. This source mapping explains the
implementation; it is not evidence that a particular native Blender build passed.
The retained source receipt at `build/viewport-framing-source-20261023/receipt.json`
records upstream paths, Git blob IDs and SHA-256 digests for these exact references:

- Blender 4.5.14: `62c1db4208e862312bc36db5bc15d4a6dbcfa3e3`.
- Blender 5.2.2: `d13f752e3b9c4f8c261cda552b1021f8bcc0382c`.

The result reports the requested `frame_object` and, when framing is enabled, a compact
`framing` receipt with `object_name`, `projection`,
`bounds_source: "evaluated_object_bounding_box"` and `frame_fraction: 0.9`.
With framing disabled, `framing` is `null`.

Capture restores temporary view, lens, projection, shading, overlays, render settings,
visibility, selection and active-object state on success and failure. Mode is preserved.
If Blender prevents restoration, capture fails with `context_restored: false` and
`verification_required: true`; reinspect the scene before continuing.
The existing `CAPTURE_VIEWPORT` permission and main-thread dispatch still apply; no
tool or permission is added. A successful capture still replaces Blender's session
**Render Result** and creates a managed temporary PNG. It does not save the project.

This improves visual evidence for offscreen objects. Capture remains refused while an
artist plan is armed. A separate reviewed change must admit bounded, restorative capture
under that protection, and future Scene-job reservation must block capture while a job
owns the Scene. Those boundaries and the full artist-loop 1.0 benchmark remain separate
work.

Focused Linux Blender 4.5.14 and 5.2.2 UI runs passed at frozen source `cdbc1c5`:
five framed surface-paint captures per build restored context, and the complete
before/recovered and protected before/after PNG pairs matched exactly. The separate
[axis/aspect fixture](viewport-framing-native.md) passed at `447ef57`: sixteen
captures covered all named axes and current perspective/orthographic views. An
independent host pixel mask matched projected bounds within 0.63 pixels. This native
geometry evidence is limited to a static transformed Mesh; wider supported object
types and artist appearance acceptance remain unqualified. Historical offscreen
captures remain historical evidence. Windows testing remains paused.
