# Non-interrupting native Blender checks

Run native checks through `scripts/run_blender_checks.py`, not by launching the UI smoke
scripts directly. The default selection is background-only; `--include-interactive` adds
the fixtures that need real windows, viewport drawing and native undo. An explicit
`--case` can select any fixture, including a UI fixture. Phased cases are opt-in by default;
`--include-interactive` selects the complete registry, including those cases.

```powershell
.\.venv\Scripts\python.exe scripts/run_blender_checks.py --blender "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --include-interactive --output build/blender-checks
```

Choose a new output directory each time. Reports retain source hashes, versions, logs,
per-case execution mode, timeout/failure and native success evidence. A clean process exit
without a valid fixture marker is not a pass. Isolated scenes and config/scripts/datafiles/
temporary recovery folders keep these tests separate from an existing user project.

## Fresh-process phases

`image_reopen`, `image_portability_probe`, `task_plans` and `asset_delivery` launch a writer
then a fresh reader. Each phase has its own timeout, temporary profile, log, completion
status and correlated process-instance evidence. The reader starts only after the writer
has a valid marker and successful exit; a timeout or failed writer never starts a reader.
Only the owned artifact bundle is shared. PID reuse is allowed; independent issued instance
tokens are required. On Windows any UI phase retains the private-desktop isolation contract.

`image_reopen` exports eight small COLOR/DATA encoding variants and a complete 4096² raw DATA
texture, binds FILE versions and explicitly saves an owned project in a child folder. Its
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

Win32 contracts: [desktop creation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createdesktopw),
[startup desktop](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ns-processthreadsapi-startupinfow),
[handle allow-list](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute),
[job limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information).
