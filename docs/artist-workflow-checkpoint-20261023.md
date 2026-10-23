# Artist workflow development checkpoint — 2026-10-23

This records selected Linux development evidence, not release qualification.
Published 0.3.0 remains alpha, the development registry contains 260 MCP tools,
and all fourteen [ledger requirements](release-1.0-ledger.json) remain open with
empty acceptance evidence. Windows testing is paused at the user's request.
Installed scenarios A–F, full native inventory, safe saving and full artist
acceptance are not established by these runs.

## Frozen production source and selected native results

Source: `ff8b0f06e2cc2614eb9192b7d90ea4a6f414b517`. Its 324 Python source files
under the add-on, MCP server and runner/scripts directories have fingerprint
`7d552d3e032a5d8af58893b57137bff71a8a723492f68817644958bc80cd46a1`.
Portable validation passed 6,169 tests with three Windows-only skips; Ruff,
typing, inventory, compilation and whitespace checks passed. Later documentation
or probe integration does not become this exact tested source automatically.

Both development builds are Linux: Blender 4.5.14 at
`62c1db4208e862312bc36db5bc15d4a6dbcfa3e3` and 5.2.2 at
`d13f752e3b9c4f8c261cda552b1021f8bcc0382c`. Their versions do not qualify
Windows or widen the separate exact-build import admission.

| Selected report | Results | SHA-256 |
| --- | --- | --- |
| `build/scene-entry-effects-native-20261023/native/report.json` | 2/2: Scene kernel on both builds | `2b74f1300eb69bea14701f8841ea0b116d554f53211429c18fd794fed4429518` |
| `build/scene-entry-effects-native-20261023/independent-audit.json` | Source bytes and five scenarios per build verified | `30bcbcb645c84d6bc137ef5be7a26589af5f401f3871a773900a7e96f020f7e1` |
| `build/scene-entry-effects-composition-native-20261023/native/report.json` | 14/14: seven cases on each build | `7219313178623788d7cfc1c62cc77f1aba1df1d7446012f25a862c4e9502de95` |
| `build/scene-entry-effects-composition-native-20261023/independent-audit.json` | Source bytes and entry-effect assertions verified | `873ae9535dbd6bdb5db9d8ef1a7ad21adcd4f85f38bc5cd31eb2cbf80bf8eab2` |

The composition cases are `artist_public_entry_probe`, `artist_loop`,
`artist_multitarget`, `undo_lifecycle`, `scene_checkpoint_admission`, `paint_jobs`
and `exclusive_mutation`. These are **16 selected results**, not a complete
native matrix; both reports have `all_cases_selected=false` and do not assess
release readiness.

The [internal Scene kernel](scene-job-kernel.md) passes success, explicit cancel,
permission revocation, disconnect and authored external-edit scenarios. Success
compares complete three-body matrices against its synchronous reference with
zero matrix error. Reservation refusals precede foreign providers/handlers.
One checkpoint or domain phase runs per tick, status stays cached, and stopped
jobs retain measured partial marker/push receipts without driver cleanup,
context restoration or AFTER pushes. This evaluates the fixture; it proves no
bake, public rigid-body job API, production latency/memory ceiling or native
preemption. Public simulation adapters remain work to complete.

The public-entry audit verifies the exact optional four booleans in guarded
errors and history, with no addition on the no-factory denied control. Primary
error codes/messages and existing execution-flag presence stay unchanged, as do
requested transforms, protected geometry, same-process native identity and zero handler,
checkpoint and native-push counts. The three guarded calls include a synchronized
control: the flag reports possible native context effects rather than measuring
a selection change. Actual selection still normalizes before the first provider
in the hidden-selected transform and preview cases. Portable receipt tests
separately verify pre-terminal metadata timing with rejected step classification;
[entry diagnostics](entry-context-effects.md) are not prevention.
Armed artist capture still refuses.

## Later exact shader preservation increment

The integrated source `87ffd23408cfb78612baaf1d8a253189e92f75f7` includes the
shader research scripts and preserves marker-named shader user data. Its 325
Python files have fingerprint
`8fcf7f5bec28a91227ce931460726d66366b9ed8a103b5e4c2256ec5e569b7dd`.
Portable validation passed **6,221 tests, three Windows-only skips**, plus lint,
typing, inventory and whitespace checks. This later increment does not turn the
earlier sixteen selected cases into a new complete current-source native matrix.

All shader user-property keys enter the existing bounded proof. Complete scope,
output and compensation comparisons use the fingerprint's unchanged canonical
representation, distinguishing Boolean/integer/float values and signed zero.
The former Python-equality path let protected typed drift pass and could falsely
verify rollback; eight original portable reproductions and the failing regression
run are retained separately. The correction also makes an exact requested
zero-sign default change an assignment requiring matching native readback.

At that source, both phased `shader_interface` cases pass on the two Linux builds
(four writer/reader processes). Each build verifies eight actual typed/sign
changes before editing or compensation, two successful zero-sign default edits,
marker payload preservation, native undo and fresh reopen. The native report
SHA-256 is `a02839827ba8d882f35b0bcb9874a6efd1cc3998123b4282663b4d4dae94e98f`;
its independent audit SHA-256 is
`76c4fdad6f22a21c306c8657049e80ea70ad9488bde2922fa6d57674953ecdcb`, under
`build/shader-exact-composition-native-20261023/`. Native user properties on
sockets are demonstrated on 4.5 only; 5.2's system-only socket properties are
explicitly outside that claim. This is structural preservation evidence, not
visual look development, complete custom-property metadata preservation, safe
saving, production removal or release acceptance.

## Separate loaded shader-removal research

Research source: `31eb64d4f26c7bc223464c8c099c1cd49547f895`; its 317 Python
source files have fingerprint
`a0db63721892b0e08c4962b62fb0ff6e751dc777c7b8da207021d4641dbdc114`.
It is separate from the production source above and adds no production REMOVE
or conversion operation.

| Selected report | Results | SHA-256 |
| --- | --- | --- |
| `build/shader-remove-postload-native-20261023/native/report.json` | Both phased cases passed: four writer/reader processes | `97b004fcb1a21c7c217b2c15a8cb3ae5b7a6baf1a391e3e5a601590572fc777b` |
| `build/shader-remove-postload-native-20261023/independent-audit.json` | Twelve removal/undo/redo cases per build and fresh readers verified | `ca149e91725c075e052e761d46ddea5f0349bc99c379f7eea71db58622e1c53e` |

The [probe](shader-interface-remove-probe.md) uses explicit owned loaded setup
and one post-load timer yield before measuring. Every participant must report
literal `is_runtime_data=False`; that field remains in every comparison and no
runtime-field exclusion makes the cases pass. Actual undo recovers the original
socket identifier and redo restores the removed state; fresh readers agree.
Surviving selection, undo UI and redo UI are checked separately. Native active
interface identifiers change in **all twelve cases on each build**, so the run
does not qualify UI preservation or an eventual public removal policy.

Fresh-created source `ade6eb4` failed complete native-undo comparison after
removal because embedded runtime status changed. Loaded source `ba7c7db` failed
before removal when the immediate post-load callback lacked selected-object
context. Both negatives remain retained. The corrected timer result does not
erase them, normalize user data or qualify public project saving. Broader shader
dependencies, animated maintenance and a recoverable public removal/conversion
contract remain open.

## Retention and remaining work

Reports and audits above are retained under `build/` in the original workspace.
The byte-verified 322-member archive
`build/scene-shader-entry-evidence-20261023.tar.gz` is 11,828,291 bytes with SHA-256
`267400d1b48dc44454ef944177d31ebe02a72d8f563f189dddc6757e64b3bfa4`.
It retains earlier `c847`/`071`/`e739` Scene negatives, `ff8` positives,
`ade6`/`ba7` shader negatives, the `31eb` loaded result, owner patches, raw logs
and causal source traces. Its source bundle SHA-256 is
`daad13feeed032c4b4fad15b736168cf04111c24fd17009a30fb5ff8b9efcacf`.
This local retention is not immutable external release evidence or ledger
qualification.

Historical Windows results and the [2026-10-22 checkpoint](artist-workflow-checkpoint-20261022.md)
remain tied to their original sources. Earlier object-framing source `447ef57`
retains sixteen matched captures and independent host projection/pixel checks;
it is not a fresh full visual acceptance run at `ff8`.

Mandatory open work includes safe authorized project save, the exact 5.2 import
quarantine, supported native read-only context witnesses and protected visual
verification, public cooperative simulation jobs, production shader removal,
whole-workflow recovery/performance, Windows and installed-package A–F
qualification. No release gate or full-artist requirement is reduced by this
checkpoint.
