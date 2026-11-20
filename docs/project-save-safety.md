# Save and recover a Blender project

This guide applies to the development source after v0.9.1 alpha. Published
installers have their own release notes and tool behavior.

1. In Blender's Bridge preferences, enable **Save Project**. To select an explicit
   path, also enable **Access External Files** and choose an existing **Approved
   Project Folder**. Bridge preferences persist when changed.
2. To read the native Save or Save As dialog, call `project.save_dialog_state`.
   It reads the proposed directory and filename and requires **Inspect Scene** and
   **Access External Files**. It reports whether the dialog is open, closed,
   ambiguous or unavailable. Use the reported absolute `.blend` path, or provide
   another path, in `project.save`. This call does not click dialog controls.
3. For first save and Save As, call `project.save` with the explicit absolute
   `.blend` path, including the filename. For Save Current, omit the path. Set
   `overwrite` to `true` when deliberately replacing an existing Save As target.
   The result includes the saved filepath Blender reported and the observed size.
   An error after native saving starts can describe a partial or uncertain write.
   Inspect the paths before retrying it.

The Bridge uses Blender's native save. Blender can synchronize data and write
backups, catalogs, recent-file history and callback output during this operation.
Native writes cannot be interrupted mid-call. A completed save and a verified
checkpoint receipt are reported separately.

**Enable all dangerous permissions** in Bridge preferences enables the individual
Delete Objects, Execute Python, Access External Files and Save Project grants as
one explicit local choice. A separate **Allow unrestricted project and texture
paths** checkbox removes those folder allowlists while the master choice is on.
Without that opt-in, blank folders grant no path access. Asset Source and Asset
Delivery folders are separate. Turning off the master choice removes unrestricted
path access and restores the individual choices. The setting controls Bridge
permissions and leaves Blender's OS access and Codex permissions as configured.

On reconnect, `bridge.status` can report a retained project checkpoint. Call
`project.checkpoint_status` to verify its complete SHA-256 and obtain the current
checkpoint ID. Call `project.checkpoint_reopen` with that ID and
`confirm_reopen: true` to load the saved project in a clean Object Mode session.
The Bridge checks permission and bytes again before reopening, keeps its listener
available for the result, and clears obsolete project handles. Dirty projects,
modified image buffers and active editor sessions are refused. Stock Blender
provides no equivalent public dirty-state check for asset catalogs.

Ordinary save receipts identify one actual saved `.blend` of up to 4 GiB. The
receipt records byte verification, while a successful reopen confirms the file
was loadable. Recovery uses the saved file on disk. It carries the changes that
were saved to that file. If the file changes or is replaced outside the Bridge,
verification fails.
The separate [verification jobs](native-project-saving.md) use a fresh Blender
reader for their supported source profiles.

The native source checks passed on Windows 11 x64 with Blender 4.5.1 LTS and
5.1.2. On each build, both master switch settings passed dialog inspection,
first save, Save Current, Save As, checkpoint reopen, and permission restoration
after normal and abrupt process exits. The fixture also checked denial for a
dirty scene and verified that allowing outside textures takes both opt-ins.
See [the Windows fixture instructions](native-testing.md).
