# Character NLA persistence evidence

The isolated, phased `character_nla` fixture exercises a bounded complete character path:
typed two-bone rig creation, empty-group skin binding and numeric weights, layered Action
creation/binding, pose keys and interpolation, first-track push-down, a second clip and native
transition, a second nonempty track, track permutation, sampled deformation, authorized save,
and independent fresh-process reopen. Arbitrary Python permission stays disabled. Fixture
construction and independent observations use native APIs inside the disposable test process;
the artist operations use registered structured tools.

The five older NLA endpoints now accept optional `affected_objects`. For example:

```json
{
  "object_name": "Character Rig",
  "track_name": "Character Motion",
  "strip_name": "Left",
  "affected_objects": ["Character Skin"],
  "expected_action_name": "Character Zero"
}
```

This is a `nla.push_down` request. The declared closure excludes the rig itself and must
account for every reviewed incoming object dependency. Omission retains the old scope and
refuses a rig with undeclared skin consumers. The optional Action name prevents pushing a
different active Action after the artist's plan was prepared. The first track and clip are
created together; unknown allocations are retained and reported on failure.

## Independent evidence

The fixture shares the Armature data and procedural material with another independently
animated rig and skin. It separately hashes complete base vertices, edges, faces, numeric
weights and group order/locks, UVs, generic attributes, material/node bindings, modifiers,
parent relationships and rest bones. Every sampled frame rechecks those protected values.
The sample contains every evaluated skin vertex and every world-space bone matrix for both
characters at frames 1, 6, 11, 16, 21, 26 and 31. An independent weighted-rotation formula
checks the primary skin, including the blended middle row; no representative-vertex shortcut
is used. Transition motion and both track orders must match their expected rotation.

The writer serializes complete bounded Action slots/layers/channelbags, curves, keyframe
handles/interpolation, modifiers, group colors and markers, together with ordered NLA tracks,
clips, transition, settings, slots and controls. The independent reader excludes process-local
pointers from comparison and verifies all semantic fields, protected rest state and sampled
motion after reopen. It then makes and restores a typed track permutation in the reopened
project. The saved `.blend` hash and distinct process tokens bind the phases to the same bytes.
The reopen uses the runner-owned native fixture loader; there is no product `project.open`
capability implied by this test.

Writer and reader each retain matched 512 by 512 solid-view images of the primary and
protected skin at frames 1, 16 and 31. An orthographic top view uses the same orientation,
distance, owner-relative center, studio light, single color and background. The evidence
records all explicit view settings, capture metadata and each retained PNG's SHA-256; the
reader verifies the writer images' bytes and repeats the exact view settings. Temporary
frame/view/shading/editor changes are restored. These images are available for technical
and artist review; retaining a capture does not mark the result artist-approved.

Adversarial checks cover absent or incorrect dependency closure, an incorrect expected Action,
permission denial, pause/stop, a missing NLA Editor, a manual dependency change after preflight,
a failure immediately after a verified private strip allocation, late permission revocation
between track setters, cancellation of a real running queue request inside each final NLA
permission provider before any strip/track allocation, separately authorized recovery,
and finalized native checkpoint undo
after transition removal. Compensation reports complete restoration only when the complete
known state matches again; a revoked permission leaves a measured partial edit for a later
authorized correction. A manual dependency change is preserved when the bridge refuses.

## Running and limits

Use `scripts/run_blender_checks.py --case character_nla --include-interactive` through the
[isolated native runner](native-testing.md), with explicit Blender executables and a new
evidence output directory. The runner starts independent writer and reader processes, and
the reader requires its own NLA Editor for UI-dependent track ordering. It never borrows the
artist's Blender session.

Paired Linux Blender 4.5.14 LTS and 5.2.2 LTS development receipts are retained under
`build/next2-character-*`. This small two-bone fixture is numerical deformation and persistence
evidence. It does not complete the broad character workflow, human visual review, constrained-
memory/manual-undo-history requirements, installed-package qualification, Windows acceptance,
or the full release gates. Those remain in the [readiness ledger](release-1.0-readiness.md).

The production NLA dependency guard freezes object/data identities and reference edges;
the fixture independently measures protected rest contents at every sampled frame. These
are separate proofs. The guard does not yet reject every possible in-place weight, rest-bone
or material edit made by another callback without changing the dependency graph. A general
content-preservation claim under that interleaving remains an open ownership gate.
