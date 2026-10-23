# Non-interrupting native Blender checks

Run native checks through `scripts/run_blender_checks.py`, not by launching the UI smoke
scripts directly. The default selection is background-only; `--include-interactive` adds
the fixtures that need real windows, viewport drawing and native undo. An explicit
`--case` can select any fixture, including a UI fixture. Phased cases are opt-in by default;
`--include-interactive` selects those cases too. The installed add-on probe additionally
requires explicit package inputs; without them it is excluded and `all_cases_selected`
remains false. A complete registry run supplies `--package-probe-config` as described below.

```powershell
.\.venv\Scripts\python.exe scripts/run_blender_checks.py --blender "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --include-interactive --output build/blender-checks
```

Choose a new output directory each time. Reports retain source hashes, versions, logs,
per-case execution mode, timeout/failure and native success evidence. A clean process exit
without a valid fixture marker is not a pass. Isolated scenes and config/scripts/datafiles/
temporary recovery folders keep these tests separate from an existing user project.

Current Windows testing is paused at the user's request. Historical Windows
reports remain source-specific; current Linux checks and the private-desktop
runner do not establish Windows qualification. The
[2026-10-23 development checkpoint](artist-workflow-checkpoint-20261023.md) separates
current source/report fingerprints from historical evidence; all fourteen release
requirements remain open.

The small background `project_save_denial` case proves public save refusals and
late permission/caller/stop errors without Blender/save entry. Public `project.save`
is [unavailable](project-save-safety.md). Feature writer/reader cases that need
`.blend` input first assert that refusal, then use explicit owned fixture-only
native serialization. Their evidence marks `fixture_native_save=true` and
`bridge_safe_project_save_verified=false`; a reopen pass cannot qualify safe
production saving. Historical typed-save results belong to their older sources.

`exclusive_mutation` is an opt-in interactive fixture for the structured-entry
interlock used by `asset.import`. It attempts nested writes through executor,
registry dispatch and prepared invocation from admission, permission, checkpoint,
handler and actual Python-finalizer callbacks. It verifies rejection before the
nested providers/checkpoints, read-only execution-display preservation, release
on success/failure, measured native edits and actual native undo after the owned
scope unwinds. It does not import assets, constrain arbitrary native/Python
callbacks, preempt a native call or qualify whole-project recovery. Run the
separate `asset_import` fixture on admitted builds for the actual import path.

## Fresh-process phases

`image_reopen`, `image_portability_probe`, `task_plans` and `asset_delivery` launch a writer
then a fresh reader. Each phase has its own timeout, temporary profile, log, completion
status and correlated process-instance evidence. The reader starts only after the writer
has a valid marker and successful exit; a timeout or failed writer never starts a reader.
Only the owned artifact bundle is shared. PID reuse is allowed; independent issued instance
tokens are required. On Windows any UI phase retains the private-desktop isolation contract.

`image_reopen` exports eight small COLOR/DATA encoding variants and a complete 4096² raw DATA
texture, binds FILE versions and prepares an owned project in a child folder using labeled fixture-only native serialization. Its
reader opens the saved project with new-profile consent, refreshes `//../textures/...` sources
through typed tools, checks complete pixel digests, protected bindings and eight matched
32px RGBA8 camera pairs. Missing-source relocation, revoked read consent and denied saving
are exercised. It does not certify edited generated input durability, UI undo or artistic
quality. UI file-load inspection is deferred to the next timer tick. The 4K case requires
8 GiB available RAM on Windows; a 900-second per-phase timeout is appropriate.

`image_portability_probe` contrasts FILE_BYTES and CURRENT_PIXELS with external sources
unavailable in the reader, then exercises typed packed versions and exact original-ID
loaded-float restoration. See [its proven limits](image-portability.md). `task_plans` verifies
explicit scene persistence/load without baseline reuse. `asset_delivery` verifies static and
animated GLB/FBX files by hashes and sampled evaluated geometry in a fresh process, within
the [reviewed export subset](asset-delivery.md). These are separate development checks, not
installed-package, Windows-version or full 1.0 acceptance.

`artist_loop` is a small background fixture for opt-in static-prop protection. It resolves
references, previews/applies/corrects transforms, compares protected structure, and exercises
denial before checkpoints, stale previews, permission-provider context/identity changes,
partial interruptions and audited explicit disablement. Runtime-getter/handler probes must
remain uninvoked. It neither renders nor saves and does not accept visual intent, protected
delivery or the full UX-01 benchmark. The two-process `task_plans` fixture separately covers
saved schema-v1 persistence/reopen without imported operational authority.
The extended fixture also checks step-bound placement/correction and rejected-operation
receipts against actual outer history IDs, protected-only comparison observations, fresh
context/reconnect bookkeeping retention and passive saved-v1 exclusion. Its undo/redo
receipt invalidation invokes the registered handler directly; it explicitly reports that
this probe does not execute native undo. Frozen source `cdbc1c5` passed the extended
`artist_loop`, `artist_multitarget` and interactive `undo_lifecycle` cases on Linux
Blender 4.5.14 and 5.2.2. The latter two exercise actual native pushes and undo;
these focused results retain the bounded static-prop profile and do not accept UX-01.
The separate [object-framing fixture](viewport-framing-native.md) passed sixteen
matched captures and independent host pixel checks at frozen source `447ef57`.

The separate [Scene kernel fixture](scene-job-kernel.md) qualifies internal
reservation/owned-checkpoint scheduling with five measured scenarios on each Linux
build. It adds no public rigid-body job API. `readonly_context_probe` records the
source-pinned getter side effect; [artist_public_entry_probe](artist-public-entry-probe.md)
uses actual registered permission-denied calls. Its current host checks verify
[optional context-effect metadata](entry-context-effects.md) in errors and history;
portable regressions separately verify rejected-step receipt timing. Requested transforms, protected geometry and
handler/checkpoint/native-push counts remain unchanged. This is diagnostic
evidence; selection can still normalize before denial, and armed capture remains
refused. See the dated checkpoint for exact tested sources.

The loaded-participant [shader interface removal research](shader-interface-remove-probe.md)
is a separate opt-in native probe with actual undo/redo and fresh-reader evidence.
It changes no production interface operations. Its original fresh-created negative
case and changed active UI socket identifiers remain explicit limitations; loaded
setup serialization is owned fixture setup, not public project-save qualification.

The interactive `undo_lifecycle` fixture additionally exercises real manual undo/redo and
known bridge recovery while a protected plan remains active. It records whether native
identities/context and authored pre-states match, requires stale artist references/previews
to fail without applying, and checks that a pre-undo write boundary cannot cross the new
generation. Baselines and protection remain intact. The trusted fixture recovery does not
add an exception to the public armed whole-scene undo restriction.
It also stops queued/lifetime cancellation, expiry, disconnect, disabled toolsets,
pause and emergency stop during new-request preflight, before automatic checkpoint
entry. Executor and batch probes require unchanged native Scene markers and no
checkpoint snapshot/undo push or requested edit. These checks do not establish
interruptibility during an already running native undo push.
Fault-injected native marker and preference readers exercise cancellation and
expiry inside initial automatic/explicit checkpoint work. Each following marker
write and undo push must stop; rejection after one marker deletion reports that
partial bookkeeping without compensation. Existing checkpoints remain listed.
Direct dispatch, protected re-preflight after checkpoint creation, and a later
batch child also exercise the shared final handler-entry gate; the earlier batch
writer retains measured native recovery while rejected handlers never run.

## Installed add-on development probe

`installed_addon_probe` installs actual pinned ZIP bytes into the runner's disposable
user-scripts profile, enables the add-on, verifies every installed member and imported
module path, checks disabled dangerous permissions, reconnects through literal loopback,
and performs bounded creation/transform checks. It then tests clean-directory replacement
with the previous package, upgrade and rollback. Staged ZIP paths contain spaces. It saves
neither the user preferences nor a project. The standalone installed wheel and plugin
acceptance remain separate.

Prepare explicit inputs using the documented tool counts for those exact packages:

```text
python scripts/package_probe_config.py --candidate path/to/candidate.zip --candidate-tools COUNT --previous path/to/previous.zip --previous-tools 108 --allow-previous-undiscoverable --output build/package-probe.json
python scripts/run_blender_checks.py --blender path/to/blender --case installed_addon_probe --package-probe-config build/package-probe.json --output build/installed-probe
```

The configuration pins complete ZIP hashes, member hashes, versions and expected tool
counts. It refuses an existing output configuration. The runner freezes that configuration;
the fixture freezes and independently verifies both ZIPs before installation. Complete
native runs pass the same configuration together with `--include-interactive`.

Native research found two real installation issues: nonliteral `bl_info` prevented Blender's
add-on browser from discovering the published alpha, and overwrite installation retained
obsolete files. Development source now uses literal, version-checked discovery metadata.
The explicit `--allow-previous-undiscoverable` option records known-name enablement for
that historical package; it does not certify its browser installation. The tested replacement
path removes only the old add-on directory inside the owned disposable profile. It does not
certify preferences migration, UI uninstall, the installed artist scenarios A–F, or Windows.
Never replace the immutable published alpha assets with development ZIPs carrying 0.3.0 metadata.

## Windows: private desktop, not just a hidden-window hint

Background cases use `--background` plus `CREATE_NO_WINDOW` to suppress a console.
UI-dependent cases use a fresh, randomly named Win32 desktop. `CreateProcessW` explicitly
assigns that desktop through `STARTUPINFO.lpDesktop`. The runner does not call
`SwitchDesktop`, request desktop-switch access, minimize other windows, restore foreground
focus, change system preferences, or enumerate/terminate the user's Blender processes.
Even if Blender overrides `SW_HIDE` and shows its window, it remains off the input desktop.

The launcher uses an inherited-handle allow-list for logs/null input, a suspended start,
and a kill-on-close job assigned before Blender runs. Timeout/cancellation kills only the
owned test process/job; handles are released afterward. An isolation or launch failure is
recorded as failure and **never retried on the user's desktop**. Nothing is installed and
no persistent desktop helper remains running. This isolates UI, not file/network permissions
or GPU/CPU load; it is not a security sandbox.

The report marks this as `private_windows_desktop`; background cases remain `background`.
Native regression tests explicitly show a small test window on the private desktop,
compare its desktop identity to the input desktop, and check timeout cleanup of a process
and its descendant. Actual Blender fixtures must still pass to confirm graphics/undo on a
given machine. Driver, Remote Desktop or restricted-session limitations must be reported as
failures, not bypassed by opening windows in front of the user.

The earlier runner only set `SW_HIDE`. That startup hint could be overridden by Blender
and was insufficient to prevent focus stealing.

The `image_delivery` fixture exercises actual socket/timer export/reimport, all four encodings
for COLOR/DATA, controlled color/alpha camera comparisons, a complete 4096² raw EXR, cancellation,
retained-file audit and native undo. Use `--case image_delivery --timeout 900` through the runner.
On Windows it requires at least 8 GiB available host RAM before allocating; it does not induce
global memory pressure or use a visible fallback. Its native decode/source-validation tails
are measured, not assumed to meet the cooperative CPU-slice target.

## Other platforms

Private-desktop execution is Windows-only. UI checks on Linux/macOS are reported as
`interactive_display`, require a display, and may show windows. Use background-only runs
or a separately managed test display/session where needed; the runner does not claim
cross-platform hidden UI support.

Large Linux fixtures measure `/proc/meminfo` availability together with the tightest
visible cgroup-v2 ancestor headroom before requiring 8 GiB. An unmeasurable hierarchy
fails before allocating the workload. Process RSS and its lifetime high-water mark are
read from procfs. These are point-in-time/lifetime measurements, not a memory reservation,
allocation cap or constrained-memory acceptance. Other-platform unsupported probes remain
explicit; no Windows acceptance is inferred from a Linux test display.

Win32 contracts: [desktop creation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createdesktopw),
[startup desktop](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ns-processthreadsapi-startupinfow),
[handle allow-list](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute),
[job limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information).
