# Contributing

Blender Codex Bridge is alpha software. Contributions should make a documented workflow
more reliable, inspectable or useful. The published 0.3.0 packages and the unreleased
development branch have different tool surfaces despite sharing version metadata.
See [development status](docs/development-status.md) before proposing a feature.

For a bug or feature proposal, use [GitHub Issues](https://github.com/Yoruiopz/Codex-Blender-Bridge/issues).
Explain the Blender task, the current limitation and a small example. Check existing issues
first. Follow [SECURITY.md](SECURITY.md) for vulnerabilities rather than posting exploit details.

## Set up a checkout

Use standalone Python 3.10+ in a virtual environment, separate from Blender's Python.
Fork the repository if needed, then clone your fork and create a branch for the change.
From the repository root, create and activate a virtual environment using your platform's
normal commands (`py -3 -m venv .venv` on Windows or `python3 -m venv .venv` on macOS/Linux).
With that environment active:

```bash
python -m pip install -e ".[dev]"
```

The remaining commands assume `python` is that environment's interpreter. To test a specific
CI dependency combination, also install `mcp==2.0.0` or `mcp==2.2.0` in the environment.
Keep development add-on and MCP sources from the same checkout. Do not install a source
build over a user project merely to test a change.

## Make a focused change

Read [AGENTS.md](AGENTS.md), [architecture](docs/architecture.md) and
[tool design](docs/tool-design.md). Read the [protocol](docs/protocol.md) before changing
transport, errors or request lifecycle. Keep these boundaries:

- The standalone MCP process does not import `bpy`; Blender operations run on its main thread.
- Blender checks permissions and live pause/stop state. A client-side check cannot grant access.
- The listener stays on literal `127.0.0.1`; remote access and shell tools are outside the model.
- Use bounded typed tools with explicit ownership, affected scope, failure and recovery evidence.
  Preserve unrelated data and user context. Unsupported work must fail explicitly.
- Inspect and verify meaningful changes. A successful return or a checkpoint is not proof of
  correct scene state or a durable backup. Saving a project needs explicit intent and permission.

Add meaningful tests for changed behavior, especially failure, denial, partial effects and
preservation. Update the relevant domain contract when public behavior changes. If registered
tools change, regenerate the README inventory with `python scripts/readme_tools.py`; do not
hand-edit its generated block. Keep planned features in the roadmap rather than current claims.

## Validate

Run the relevant focused tests, followed by the full non-Blender suite and repository checks:

```bash
python -m pytest tests/test_relevant_module.py
python -m pytest
python -m ruff check .
python -m mypy mcp_server
python -m compileall -q addon/blender_codex_bridge
python scripts/readme_tools.py --check
```

Replace the example test path with the tests for your change. Documentation-only edits need
appropriate link, formatting and inventory checks; they do not need tests that repeat prose.
CI covers Python 3.10/3.11/3.12 with MCP SDK 2.0.0/2.2.0, lint, typing, compilation and packages.
CI does not establish native Blender compatibility or full 1.0 acceptance.

For a packaging change, build matching development artifacts with
`python scripts/build_release.py` and verify `dist/release/SHA256SUMS.txt`.
These are local test builds; do not replace published release assets with them.

Blender-dependent changes also need a disposable native fixture through
`scripts/run_blender_checks.py`. Follow [native testing](docs/native-testing.md) for explicit
executable paths, output directories, UI isolation and logs. Never launch UI smoke scripts
directly or test against someone's open project. Windows UI checks must use the runner's
private desktop; other platforms need a separately managed display/session where appropriate.
Record the exact OS, Blender build, source commit/worktree state, commands and failures.
State unavailable environments as untested; smoke results do not approve release gates.

## Open a pull request

Describe the concrete problem, resulting behavior, validation and remaining limits. Include
source-matched native evidence when Blender behavior changed. Call out permission, dependency,
file-effect, recovery or compatibility changes so a reviewer can assess their scope.
Avoid private scenes, credentials, personal paths, generated build output and unrelated edits.
The [PR template](.github/pull_request_template.md) provides short prompts.

The project is licensed under [GPL-3.0-or-later](LICENSE). Keep license notices intact.
