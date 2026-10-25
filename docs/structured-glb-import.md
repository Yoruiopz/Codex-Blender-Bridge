# Structured GLB import plan prerequisite

`asset_glb_import_plan.plan_glb` is an unregistered, Blender-free numeric planning
component. It is **not an import tool or a native backend**. It allocates no
Blender IDs, probes no paths, invokes no operators and changes no permissions,
checkpoints or quarantine. The public tool inventory is unchanged. In particular,
existing typed import remains quarantined on Blender 5.2.2 build `d13f752e3b9c`.

This is initial implementation toward the separate H03/DELIVER alternative. Full
textured, skinned and animated GLB, FBX, portable `.blend`, protected consumers,
recovery and the complete artist workflow remain mandatory unfinished work. All
fourteen release gates remain open; Windows testing remains deferred/unverified.

## Complete source admission

The function accepts only an exact immutable `bytes` value, 28 bytes through
8 MiB. It first calls the existing `asset_glb_preflight.preflight_glb` unchanged.
That parser validates the complete envelope, duplicate-free bounded JSON, every
accessor's bytes even when unused, resource indices, embedded buffer ranges,
finite values and the whole reachable hierarchy. The new decoder only reads
layouts already admitted by that parser. The reviewed node-matrix helper is
reused; this component does not provide another acceptance path around preflight.

The narrower plan profile requires referenced indexed triangle meshes:

| Resource | Initial limit |
| --- | --- |
| Nodes | 32, with source indices and one parent per non-root node |
| Meshes | 16, all referenced by reachable source nodes |
| Materials | 16 including an explicit implicit-default resource when needed |
| Triangle primitives | 64 across all meshes |
| Vertices / triangles | 8,192 each for definitions and expanded instances |
| Numeric scalars | 131,072, checked in aggregate before copying plan arrays |
| Source label text | 8,192 UTF-8 bytes in total |
| Normalized canonical JSON | 4 MiB |
| Node/mesh/material source names | Valid Unicode strings within 59 UTF-8 bytes |

Indices can be unsigned 8-, 16- or 32-bit. Positions and optional normals/first UV
coordinates use admitted FLOAT accessors, including interleaved views. Missing
normals and UVs remain explicitly absent; they are never fabricated. Repeated
triangle indices and exact zero-area geometry refuse pending a repair contract.
Normals must already be unit vectors within the stated Float32-source tolerance
(`abs(length_squared - 1) <= 2e-5`); their values are not renormalized.

Image/texture/sampler inventories, tangents/additional vertex attributes,
non-indexed primitives and unused meshes/materials refuse. The inherited core
parser also refuses external/data URIs, extensions/extras, sparse/normalized
accessors, skinning, animation, cameras and unsupported material channels. These
refusals apply before any future Blender allocation; unsupported content is not
silently discarded. Embedded images can be validated by the core parser before
the narrower plan refuses their unsupported reconstruction.

All source node/mesh/material names are retained. Generator/copyright, scene,
buffer, view and accessor labels are retained as immutable source labels. All
source bytes, including unused validated raw buffer/accessor data and padding,
are bound by the complete source SHA-256. Unused raw accessor arrays are not
invented as Blender resources. The caller must retain the original source bytes;
this numeric plan is not a source-file backup.

## Explicit numeric intent

The frozen dataclasses contain nested tuples of ordinary scalar values, source
indices and immutable strings. No caller list/dictionary, `bytearray`,
`memoryview`, native wrapper or callback is retained. A canonical JSON digest
binds the complete normalized numeric intent and source identity. It is a
fingerprint, not an authorization token. A future native consumer must construct
and retain its own plan from the independently approved source, rather than trust
a client-supplied plan/hash.

Coordinates and translations retain glTF's meter units, recorded as `METERS`;
no destination Scene unit scale is read or assumed. A future constructor must
qualify and explicitly plan any conversion into that Scene's units.

The right-handed basis conversion is `(x, y, z) -> (x, -z, y)`, with determinant
`+1`. Positions and normals use that signed permutation without normalization or
winding reversal. Local and world matrices use `B M B^-1`; source hierarchy and
mesh instancing are retained by source index. World multiplication uses an
explicit Float64 left fold, avoiding Python-version-dependent compensated sums.
Node matrices remain Float64 numeric intent: **no Blender matrix decomposition,
channel assignment, parenting or evaluated-transform accuracy is qualified**.
Exactly projective matrix components refuse, even when within the older core
parser's affine tolerance. Singular/negative-scale affine intent can be represented;
its future native handling must be qualified or refused before mutation.

UVs use `Float32(u, 1-v)` to convert glTF's origin convention to Blender's. The
Float32 subtraction/rounding can lose source precision, so any UV stream adds
`UV_ORIGIN_CONVERSION` to the declared conversion losses. The first coordinate's
source Float32 value is retained. Source material factors remain Float64 values;
alpha mode/cutoff and double-sided state are explicit, never silently changed to
opaque or one-sided. Native shader/color-space/alpha reconstruction and storage
quantization still require separate proof.

An absent source material becomes a separate explicit glTF default material
plan: base color `(1,1,1,1)`, metallic/roughness `1`, OPAQUE and one-sided. This
avoids substituting Blender's different unassigned-material appearance. Primitive
bindings reference plan material indices; explicit source materials retain their
source indices, while the generated default has `source_index=None`.

The inherited declared losses are `VERTEX_SPLITS`, `AXIS_UNIT_CONVERSION` and
`PBR_MATERIAL_RECONSTRUCTION`, plus the UV loss when present.
`require_loss_acceptance` checks an exact copy of that ordered preview list.
It does **not** establish human approval, a Blender grant or ownership. The
`check` callback is only a trusted validation/lifecycle signal and may stop the
calculation by raising; it confers no permission and runs no native work here.

## Gates before a native or public import workflow

A future constructor must first prove Blender-side file permissions and approved
source confinement, complete source identity revalidation, independent desired
ID/name/binding intent, bounded destination ownership and affected-consumer
closure. Native transform/normal/material/UV storage must match measured source
intent, or the unsupported conversion must refuse/report an explicit reviewed
loss before allocation. Name collisions need a reviewed allocation map; source
names here are not an unchecked allocation instruction.

Checkpoint creation is not presumed passive. Existing investigation found that a
native checkpoint can materialize unrelated dirty animated Object channels. A
constructor must prove its admitted global/context profile and checkpoint effects
before relying on them, then preserve unrelated geometry/materials, hierarchy,
animation, context and protected data under provider changes and manual edits.
Owned new IDs, per-write lifetime/permissions, partial allocation, cancellation,
disconnect, cleanup deletion permission, recovery and no late writes need direct
adversarial native evidence. Retained arrays or undo history are not durable
backups. Fresh-process delivery/reimport and reviewed appearance remain required.

No operator-based importer, exact-build quarantine, held Timeline/provider path,
project-save refusal or protected-capture restriction is invoked or weakened by
this planning component. Public registration and MCP/schema/documentation changes
come only after a separately reviewed native backend passes its required gates.
