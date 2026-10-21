# Shader interface lifecycle: native evidence

This increment adds a native research fixture, **not a public interface-edit API**.
`shader_group.interface_add` remains the existing structured append operation.
Rename, reorder, default editing, removal, conversion and animation-aware interface
maintenance remain required work in the [1.0 plan](plan-1.0.md).

The isolated phased `shader_interface_probe` fixture passed on Linux Blender
**4.5.14 LTS** and **5.2.2 LTS**. It creates a shared leaf shader, a nested parent,
two material roots, a World root and a Light root, plus an unrelated protected
material/group. It compares complete bounded interface/socket/default/link records,
including all those consumers, then saves and checks the same graphs and animation
in a separate reader process. Embedded node trees are identified by owner kind and
name; their default names are not assumed globally unique.

## Demonstrated unanimated behavior

- Renaming one exact interface identifier propagates its displayed name while
  retaining all original interface identifiers, instance values and graph links.
- Moving a flat interface socket preserves identifiers, links and defaults across
  nested consumers. Native `interface.move` uses insertion positions: moving down
  requires accounting for removal of the old position. The fixture checks the
  entire resulting peer permutation, not merely the requested item's position.
- Setting the interface default preserves existing instance defaults. A new group
  instance inherits the new interface default. The interface default and current
  instance values are separate state.
- The same identifier set, nested/root links, defaults, owner references and stored
  animation survive an actual fresh-process reopen of the saved project.

These results do not establish safety for animated interfaces, panels, arbitrary
shader nodes, linked/override owners, every consumer family or production scale.
They do not constitute Windows or installed-package acceptance.

## Measured conversion loss

For an **unlinked Float input**, changing `socket_type` to `NodeSocketVector`
retains the interface identifier but resets the interface default and every
existing instance's default to zero vectors on both versions. Changing the type
back to Float leaves zero defaults; it does not recover the former Float values.
The fixture restores the exact original interface and all instance defaults
explicitly and independently verifies the whole pre-conversion graph afterward.
This is measured fixture recovery, not a released conversion or general recovery
contract. Linked conversions and broader type/animation preservation remain open.

## Measured animation difference

The fixture keyframes one material group instance's Float input at frames 1 and 2,
then swaps its order with a second input. It retains actual FCurve paths and samples
the values by stable socket identifier:

| Native version | FCurve after reorder | Sampled result |
| --- | --- | --- |
| 4.5.14 LTS | Path remains `nodes["Surface"].inputs[0].default_value` | Animation targets the wrong peer socket; the original input retains a stale value |
| 5.2.2 LTS | Native code rewrites the path to `inputs[1].default_value` | Both sampled input values remain correct |

Restoring only the original order on 4.5 does not restore the wrong peer's old
default. The fixture explicitly restores that value and verifies both original
samples. Future typed edits must reject unsupported animation or demonstrate
complete action/driver/path preservation and measured recovery for the affected
versions and consumers. Native behavior on 5.2 cannot be assumed on 4.5.

## Retained development evidence

`build/next-wave-shader-interface-probe-20261022-final/report.json` in the original
workspace retains the paired native logs, source fingerprints, full result data
and separate-process identity. Earlier failed probe reports remain separate.
`docs/shader-groups.md` describes currently registered public tools; this document
records the new native behavior and the requirements it leaves open. The current
results come from a dirty development worktree, not a frozen release candidate.
