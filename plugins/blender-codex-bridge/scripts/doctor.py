"""Read-only local installation check for Blender Codex Bridge."""

from __future__ import annotations

import json
import shutil
import socket


def main() -> int:
    command = shutil.which("blender-codex-mcp")
    listener = False
    detail = "connection refused"
    try:
        with socket.create_connection(("127.0.0.1", 9876), timeout=0.5):
            listener = True
            detail = "accepting local connections"
    except OSError as exc:
        detail = str(exc)
    print(
        json.dumps(
            {
                "mcp_command": command,
                "mcp_command_found": command is not None,
                "blender_listener": listener,
                "blender_listener_detail": detail,
                "endpoint": "127.0.0.1:9876",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if command is not None and listener else 1


if __name__ == "__main__":
    raise SystemExit(main())
