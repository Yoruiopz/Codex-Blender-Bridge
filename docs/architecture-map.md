# Local architecture map

Graphify is an optional **development navigation tool**, not a bridge runtime dependency,
Blender capability, release verifier or replacement for inspecting source and running tests.
Neither the add-on nor the standalone MCP server imports it.

## Build and use

Invoke the Graphify skill from the repository root with `/graphify .`. For a later refresh,
use `/graphify . --update`; the skill handles code extraction, documentation analysis,
cache/manifest provenance, integrity checks and community labels. Do not silently discard
failed documentation chunks or overwrite a larger graph with an incomplete extraction.

The generated `graphify-out/` folder contains:

- `graph.html`: interactive local map; no server is needed to open the file.
- `graph.json`: graph data, source locations and extracted/inferred relationship tags.
- `GRAPH_REPORT.md`: community names, numeric cohesion, hubs and audit limitations.
- `graph-health.json`: raw extraction diagnostics, before the undirected projection.
- `manifest.json`, caches and `cost.json`: refresh/provenance bookkeeping.

The folder is ignored by Git because it includes large generated artifacts and a
machine-specific interpreter path. Share deliberately reviewed findings in project docs
instead. `.graphifyignore` excludes unrelated local game work and agent-configuration
directories; normal Git exclusions also keep builds, environments and captures out.
No auto-rebuild hook, watcher, cloud upload or persistent Graphify server was installed.

With the Graphify environment available, run queries from the root:

```text
graphify query "exact graph vocabulary" --budget 1800
graphify path "UV authoring" "Mesh Edit recovery"
graphify path "UV authoring" "Scoped scene evidence"
graphify reflect --if-stale
```

Use the interpreter recorded in `graphify-out/.graphify_python` if the executable is not
on PATH. Expand questions using actual node vocabulary; prefer exact labels for paths.
Read `reflections/LESSONS.md`, preserve confidence/source tags, and save useful paths and
dead ends. If output is truncated, narrow the scope rather than treating it as complete.
Rebuild after source changes before relying on the graph for a new change. This document
and the latest execution-log entry were written after the snapshot below and require a
subsequent refresh; the existing map is a dated snapshot, not a continuously live view.

## Initial snapshot, 2026-10-19

Built locally with Graphify 0.9.92 against the code now committed as `1e565e1` and the
then-current documentation. Detection found **194 files / 159,639 words**: 170 code files
and 24 documents, no sensitive-file skips or directory scan errors. Six unclassified files
are not represented. AST extraction yielded 2,578 nodes / 9,290 relationships; a sub-agent
read all 24 documents and returned 83 nodes / 123 relationships / one grouped relationship.
The merged post-build map has **2,714 nodes, 8,645 edges and 97 named communities**.
Build-added reference nodes and undirected edge projection mean these totals are not a
simple sum of the extraction counts. Not every graph node represents executable code.

### Integrity and cost limits

The raw integrity check reported **883 dangling-endpoint edges, 8 self-loops and 766
undirected same-endpoint collapses** (zero missing endpoint fields, zero exact duplicates).
These are Graphify extraction/projection warnings, not 883 proven bridge defects. The map
is incomplete and can merge distinct relations/contexts. Investigate the original source
before acting on any inferred dependency, cycle or apparently missing connection; passing
bridge tests does not fix these mapper limitations. Full diagnostics remain in the local
health report. No installed Graphify code was patched to hide the warnings.

The host did not expose the documentation sub-agent's token usage. `cost.json` explicitly
marks semantic usage unavailable; its zero counters are placeholders, **not zero-cost
measurements**. The report states that limitation. AST extraction uses no LLM. Graphify's
benchmark estimated about 1,621 tokens per query and 111.6× reduction against its own
135,700-word naive corpus estimate; that differs from detection's corpus accounting and
is not measured end-to-end savings or a performance guarantee.

### What the map helped establish

The largest hubs were `invalid_argument()` (253 edges), `BridgeError` (216) and `ToolContext`
(173): shared validation, failure and execution-context contracts deserve cross-domain
review, not only isolated happy-path tests. Centrality is a navigation signal, not proof
that these contracts are consistently enforced. Documentation communities separately expose
the artist acceptance plan, prop/UV evidence loop, consent workflow and protocol outcomes.

A broad authoring/evidence/recovery query found 201 nodes but returned only 51 at its
budget; generic test fixtures dominated its seeds. It was recorded as a dead end. Narrow
exact-label paths then returned these **EXTRACTED documentation references**:

```text
UV authoring -> Mesh Edit recovery
UV authoring -> Scoped scene evidence
```

These point to the documented edit / inspect-and-compare / recover workflow. They are not
a runtime call trace, a whole-project preservation guarantee, or acceptance of the full
1.0 artist scenario. The next asset-workflow increment still needs mesh-validity evidence
and approved image assets, followed by a richer textured-prop revision; character, paint,
simulation, UX, delivery and release gates remain open in [the plan](plan-1.0.md).

## Local skill versus cloud connector

The local `$graphify` skill and generated graph do **not** establish a Graphify cloud
connection, authenticated workspace or repository access. Cloud `list_repositories` and
workspace switching require that service's tools in the active client session. The browser
can show `dino-s-workspace` while a chat still has no Graphify service tools. Do not invent
repository results, treat a UI connection wizard as proof of MCP access, or reuse GitHub
results as if they came from Graphify. No credentials or cloud connector settings were
changed by this local mapping run.
