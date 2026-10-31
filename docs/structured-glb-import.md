# Structured GLB staging and publication candidate

The 0.9.1 release candidate excludes all five staging names from normal Blender
registration, MCP discovery and dispatch. Their implementation and explicit
development registration/tests remain preserved as **UNQUALIFIED** work. They
require exact-source Runtime, native and installed-package acceptance before a
future public release. Historical private constructor evidence qualifies only
its matching source and bounded constructor profile; it does not qualify these
Runtime entry points or publication.

The Blender-free `asset_glb_import_plan.plan_glb` remains the numeric prerequisite.
The candidate service must independently plan complete approved source bytes and
retain its own immutable intent. MCP opens no source files, sets no grants and
accepts no caller plan arrays or approved-root override. The legacy
`asset_glb_preflight.LOSSES` and `asset.import` contract are unchanged; the old
Blender 5.2.2 build `d13f752e3b9c` native-importer quarantine remains held.

Full textured, skinned and animated GLB, FBX, portable `.blend`, protected
consumers, recovery and the complete artist workflow remain mandatory unfinished
work. All 29 implementation items and fourteen stable gates remain **OPEN**;
Windows testing remains deferred and unverified.

## Current source preservation contract

The current Runtime profile requires the explicit current Scene to have
`unit_settings.scale_length == 1` and a plain active Empty with no modifiers,
constraints, particle systems, soft body or animation. It does not change Scene
units or switch the artist's active object to meet that profile.

The authorized target is preservation of logical authored bits, ID identities,
roles, group definitions/memberships and consumers. It does **not** promise
unchanged hidden storage layout or cache state. Source-qualified reads of existing
ARRAY storage may perform bit-preserving COW/unsharing and native cache tagging.
On both pinned builds, reading vertex groups may create an empty deform layer and
move layer descriptors; those observation effects must be declared and measured.
Detached physical headers precede geometry/groups, and the whole inventory,
by-name identity, class/schema and storage must be reacquired before every data
read and after groups. Cached wrappers never replace that proof.

Every 5.2 SINGLE layer refuses **before geometry/data begin** until a separately
authorized preparation exists. Legacy `MeshUVLoopLayer.data` optional-storage
creation remains forbidden. UV coordinates/flags use generic attributes only
when physical presence and storage are proved. Header/binding qualification and
matching Runtime/native/installed evidence remain gates; rich meshes, UVs, rigs,
images and other artist data must stay intact. Clearing or excluding them to
obtain a pass is not accepted qualification or a narrower product definition.

The native fixture may perform explicitly authorized raw owned-fixture storage
preparation after a genuine SINGLE refusal and before a **new fixture baseline**.
It preserves all IDs, topology, roles, groups and values; already-ARRAY layers
are no-ops. Only qualified BOOLEAN/FLOAT2 and source-proven INT/FLOAT_VECTOR
recipes are admitted; scalar FLOAT/unknown conversions refuse before any change.
The record retains detached before/after headers, action/read effects and complete
postreadback. When pre-SINGLE bits cannot be read without conversion, it records
source-equivalence proof and independent known-fixture oracles, not an invented
empirical before hash. This is raw fixture authoring under Edit Mesh semantics,
not a Bridge preparation API, support qualification or untouched-startup claim.

Full current canonical grants and protected/owned CAS run before every bounded
synchronous phase and after each provider or yield. Inside a source-qualified
callback-free native chain, provider-free pure stop/session/lease/source and
descriptor checks run before every native entry and at its first return; genuine
returned references enter escrow first. C remains nonpreemptible. Exact source
proof and measured bounded intervals are required; no deadline, cap or
performance claim follows from source-only models.

## Candidate request and job contract

| Candidate method | Intent | Required Blender permissions |
| --- | --- | --- |
| `asset.glb_stage_preview` | Approved `filepath`, new `collection_name`, explicit `overwrite_policy=REFUSE`; returns expiring preview, pre-issued stage ID, source/intent fingerprint, exact losses and proposed names before allocation | `INSPECT_SCENE`, `ACCESS_EXTERNAL_FILES` |
| `asset.glb_stage_create_start` | Exact preview ID/fingerprint and ordered `accepted_losses`; accepts a bounded creation job for an unlinked owned collection | Above plus `EDIT_SCENE`, `TRANSFORM_OBJECTS`, `EDIT_MESH`, `EDIT_MATERIALS` |
| `asset.glb_stage_inspect` | Bounded cached stage, phase, observed identity/role and effect facts, with unknown effects explicit | `INSPECT_SCENE` |
| `asset.glb_stage_publish_preview` | Exact stage and existing `destination_scene_name`, explicit `REFUSE`; seals destination identities/units/edge intent and the cached construction prefix | `INSPECT_SCENE` |
| `asset.glb_stage_publish_start` | Exact stage, `glb_publish_` preview ID and fingerprint, explicit `REFUSE`; accepts a job to link exactly one already-owned collection into the destination Scene master | `INSPECT_SCENE`, `EDIT_SCENE`, `TRANSFORM_OBJECTS`, `EDIT_MESH`, `EDIT_MATERIALS` |

Both start methods take a strict integer `time_limit_seconds` from 1 through 300,
default 60. Use existing `jobs.inspect`, `jobs.list` and `jobs.cancel`; keep the
owner connection until terminal. An accepted response is not completed creation
or publication. Work uses the canonical Scene job slot, checkpoint and lifetime
barriers under the bounded-phase authority contract above. There is no second scheduler or implicit permission grant.

Inspection is cached: it reads no source file or live owned Mesh attributes and
does not establish current native ownership. Publication preview also does not
refresh owned data. Only source-qualified destination header/context reads are
admitted; incompatible destination profiles must refuse. Publication start must
reconstruct and compare the complete live owned projection under mutation
authority and compare exact destination Scene edges before linking. A token,
name, fingerprint or earlier constructor pass cannot replace fresh qualification.

New-ID ownership is a fixed closure with sealed allocation names. Source units
are meters; destination conversion policy must bind the current Scene unit facts.
No existing Scene/Object data, mesh, material, rig, hierarchy or protected artist
baseline may be overwritten or adopted by name. `REFUSE` is the only overwrite
policy. No selection activation, source write, export or project save is implied.

Native-return references must enter owned escrow before a pure stop check. Stop,
deadline, disconnect or revoked authority prevents further native entries,
including reads, cleanup, inverse writes and provider calls. An active native
call cannot be interrupted. Per-entry attempt/effect records, including
none-returning writes, must expose known partial effects and explicit unknown IDs.
Retain partial or unknown IDs for inspection; never delete them as hidden cleanup
or restore over manual work. A cached record is not a durable backup or recovery
of the complete project.

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
coordinates use admitted FLOAT accessors, including interleaved views. The numeric plan keeps missing
normals and UVs explicitly absent. The bounded constructor may use geometric
AUTO normals only under the exact notice below. Mixed UV presence across
primitives refuses in the candidate service: zero fill has no accepted public
consent contract and remains an explicit public-registration gate. Repeated
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
the pure numeric plan reads no destination Scene unit scale. Runtime staging
must bind and qualify the explicit meter-to-current-Scene policy before native
construction or publication.

The right-handed basis conversion is `(x, y, z) -> (x, -z, y)`, with determinant
`+1`. Positions and normals use that signed permutation without normalization or
winding reversal. Local and world matrices use `B M B^-1`; source hierarchy and
mesh instancing are retained by source index. World multiplication uses an
explicit Float64 left fold, avoiding Python-version-dependent compensated sums.
Node matrices remain Float64 numeric intent. Private constructor checks retain
independent literal matrix/vertex expectations for their exact subset. Their
mathematical authored-world oracle is **not evaluated-world accuracy** or proof
of these Runtime entry points, broader matrix forms or full artist delivery.
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

The structured-only ordered losses begin with `VERTEX_SPLITS`,
`AXIS_UNIT_CONVERSION` and `PBR_MATERIAL_RECONSTRUCTION`. Append
`UV_ORIGIN_CONVERSION` when UVs are present, then
`NORMAL_STORAGE_QUANTIZATION` when source normals require custom storage, then
`MISSING_NORMALS_USE_GEOMETRIC_AUTO` when those normals coexist with primitives
whose normals are absent. AUTO requires NORMAL. These define exactly six wire
forms: core; core+UV; core+NORMAL; core+UV+NORMAL; core+NORMAL+AUTO;
core+UV+NORMAL+AUTO. The actual source-specific list, source-normal/AUTO loop
counts and summaries are sealed into the preview and fingerprints. A different
valid wire form is still insufficient for that source.

Normal quantization is a declared conversion loss. The native decoded component
bound `5e-4` is an observed postcondition, **not CAS tolerance**. Future native
comparisons retain exact encoded custom-normal shorts, selection booleans,
sharp-edge state, full attribute schemas and component values. Implicit owned
storage effects, including 5.2 SINGLE-normal materialization, must be attributed
to construction rather than called read-only artist inspection. No unknown
schema, bit drift or manual edit may be stripped, cleared or accepted by tolerance.
`require_loss_acceptance` checks an exact copy of that ordered preview list.
It does **not** establish human approval, a Blender grant or ownership. The
`check` callback is only a trusted validation/lifecycle signal and may stop the
calculation by raising; it confers no permission and runs no native work here.

## Qualification gates still open

The candidate Runtime workflow must prove Blender-side file permissions and approved
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
this planning component. Private candidate registration and schemas are reviewable implementation only.
Public acceptance, publication or release requires separately reviewed matching
Runtime/native/installed evidence; the candidate registrations cannot close that gate.
