# Scoped GLB and FBX asset delivery

**Save availability:** `project.save` currently refuses Save and Save As before
native/path access; see [the safety change](project-save-safety.md). Fresh-process
results below establish feature serialization through owned fixture setup, not a
safe bridge project-save capability. Earlier typed-save reports are historical.

Unreleased development functionality. `asset.export_preview` and `asset.export` use Blender's
native exporters for a deliberately reviewed subset; this does not complete DELIVER-01,
production import/export, full artist coverage or release acceptance.

Choose **Approved Asset Folder** locally in Blender preferences, then enable the
`asset_delivery` toolset. Export requires Inspect Scene, Edit Scene, Access External Files
and Save Project. A texture-folder approval never grants asset-folder approval. No preference
can be changed by these MCP tools.

1. Call `asset.export_preview` with exact `object_names`, `format="GLB"` or `"FBX"`, and an
   explicit `include_animation` choice. Include every parent and the complete armature dependency.
2. Review the returned scope, frame range, one-metre unit scale, fingerprint and required
   format losses. Vertex splitting and axis conversion prevent project/topology identity claims;
   armatures also convert bone axes. Animated output samples integer frames and does not promise
   original action/keyframe/interpolation identity or subframe motion.
3. Call `asset.export` with the same inputs, an exact unused absolute output path, the returned
   `expected_fingerprint`, and `accepted_losses` copied verbatim from `required_accepted_losses`.
   Changed source/context requires a new preview. Paths must remain inside the approved folder
   with existing ordinary local parents and the matching `.glb`/`.fbx` extension.
4. Inspect `external_effects`, preserve the artifact hash/size, and validate the output in the
   intended downstream application. A successful export does not automatically certify a fresh
   reimport, appearance, production delivery, a saved `.blend` or crash durability.

The reviewed scope is local, editable, visible/selectable mesh, armature and empty objects in
Object Mode: material-free triangle meshes, at most one UV layer, 100000 total vertices,
256 bones and 250 integer animation frames. Linear skinning needs one included armature and
1–4 normalized deform-bone influences per vertex. Static rigs must be undeformed. Drivers,
NLA, constraints, shape keys, custom normals/attributes, vertex colors, other modifiers,
simulations, instancing, materials and textures are rejected before export. Native exporters
are not permitted to load arbitrary image dependencies through this workflow. This is an
asset exchange format, not a `.blend` project archive or a general import API.

Native export runs synchronously on Blender's main thread and is non-preemptible. Cancellation
is observed afterward. Selection, active object, frame/subframe and source signatures are
restored/compared before publication. Export writes to an owned private staging directory,
checks that no unexpected sidecars appeared, inspects the native binary envelope and hashes
every byte. Publication uses a same-filesystem hard link with create-if-absent semantics and
no overwrite/copy/rename fallback. Unsupported filesystems fail closed.

Published files are never removed by native undo, cancellation or cleanup. An uncertain link
outcome reports `publication_outcome_unknown`; `file_published=false` does not then prove no
file exists. Cleanup removes only unchanged owned staging with live grants; denied consent,
changed identity/bytes or unexpected entries retain the exact directory for inspection.
Terminal operation history retains bounded file evidence and redacts it from MCP recovery
history without scene-inspection permission. Detailed diagnostics remain local.

Directory pins reuse the texture-staging implementation; this asset workflow has not received
Windows native qualification. POSIX resolution/identity checks do not eliminate hostile
filesystem namespace races. No filesystem sandbox, power-loss durability or publication
latency guarantee is claimed.

The phased `asset_delivery` native fixture exports static and two-frame skinned assets, then
imports only its owned binary artifacts in a fresh isolated process. It verifies complete
artifact hashes and sampled evaluated world vertices. The controlled FBX reader explicitly
uses `anim_offset=0`; its normal importer default shifts the timeline. Blender's glTF importer
can add a hidden bone-display Icosphere; target geometry is checked separately from support
objects. This fixture is bounded geometry/deformation evidence, not material, artistic,
cross-platform or full-version acceptance. Windows Blender 4.5/5.x acceptance remains open.

Approved-source typed import has a separate [bounded static contract](asset-import.md),
including source admission, owned native staging and fresh saved-project reopen evidence.
