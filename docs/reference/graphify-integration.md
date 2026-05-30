# Graphify Knowledge Graph Integration

**Tool**: graphifyy v0.8.25, CLI `graphify` (installed in `~/.claude/venv`)
**Architecture**: Dual-touchpoint integration in the /dev pipeline (B-lite — real CLI)
**Integration cycle**: task 20260530-105221 (rewrote the 3 wrappers to drive the REAL CLI)

---

## Overview

Graphify is a code-to-knowledge-graph tool that provides structural codebase context (import chains, module topology, function call graphs). The integration adds two phases to the /dev workflow:

- **Step 1.5** — Deterministic pre-BA Bash hydrator (`graphify-query.py`): reads the real node-link `graph.json` and runs real `graphify query` to inject structural context BEFORE BA analysis.
- **Step 7.5** — Graphify subagent enrichment (`graphify-enrich.py`): resolves the blast-radius-map paths to real graph node IDs, builds a focused subgraph deterministically from `graph.json`, and runs real `graphify affected`, AFTER BA-QA validation and BEFORE DEV dispatch.

Both phases are **advisory** (fail-open): Graphify tool failure never blocks DEV. Only requirement ambiguity (unresolved implicit references) is clarification-blocking.

---

## Real CLI Surface (graphify 0.8.25 — empirically verified)

| Subcommand | Purpose | Output |
|------------|---------|--------|
| `graphify update <repo>` | AST-only re-extract (no LLM). Writes `graph.json` + `GRAPH_REPORT.md` + `graph.html` + `cache/` + `.graphify_root` to `$GRAPHIFY_OUT`; writes `manifest.json` to `<cwd>/graphify-out/manifest.json`. | node-link JSON |
| `graphify extract <repo> --out DIR --backend B` | AST + semantic (LLM extraction on docs/papers/images; code stays AST). Writes to `DIR/graphify-out/graph.json`. | node-link JSON |
| `graphify query "<q>" --graph G --budget N` | BFS traversal for a question. | human-readable TEXT (NODE/EDGE lines) |
| `graphify affected "<node.id>" --graph G --depth N` | reverse traversal — nodes impacted by a node. | human-readable TEXT |

There is **NO** `--init`, `--update`, `--output-dir`, `--project-dir`, `--cache-dir`, `--file`, or `--format` flag — those were fictional. The wrappers never use them.

### Graph schema (NetworkX node-link)

```
{ "directed", "multigraph", "graph", "nodes", "links", "hyperedges" }
```
Edges live under **`links`** (NOT `edges`): `{source, target, relation, confidence, confidence_score, source_file, weight}`.
Nodes: `{id, label, source_file, source_location, community, file_type, norm_label}`.
Affected/query match by node **id** (e.g. `mod_a_py`), not file path — the wrappers resolve modified paths → node IDs via `source_file`/`label` before seeding `affected`.

### Cwd-pollution handling

`graphify update` honours `GRAPHIFY_OUT` (absolute) for `graph.json` but ALWAYS writes `manifest.json` to `<cwd>/graphify-out/manifest.json` (cwd-relative). The wrappers therefore run EVERY graphify subprocess with **cwd = cacheDir AND `GRAPHIFY_OUT` = cacheDir** (both absolute, set in `run_graphify_cmd`) so all byproducts land inside the out-of-repo cache and the source repo stays clean. If the configured cache resolves INSIDE the repo, the wrappers refuse to run (advisory `cache_root_inside_repo`).

---

## Storage Layout

```
/var/tmp/claude-graphify/<repo_key>/     # Global cache (OUTSIDE the repo, disk not /dev/shm)
├── graph.json                            # node-link graph (the availability signal)
├── GRAPH_REPORT.md
├── graph.html
├── .graphify_root / .graphify_labels.json
├── cache/
├── graphify-out/manifest.json            # cwd-relative manifest byproduct
└── run-manifest.json                     # wrapper-written: semantic_mode, head_sha, timestamps

.claude/dev-registry/{task_id}/graphify/  # Per-task immutable artifacts
├── pre_query.json                        # Step 1.5 output (structural_context)
├── graphify-run.json                     # Step 7.5 run manifest
├── focused-subgraph.json                 # Task-scoped subgraph (translated node-link)
├── graph-summary.json                    # Compact summary
└── graph-report.md                       # Human-readable report
```

---

## Failure State Machine

| Status      | Trigger                                                                      |
|-------------|------------------------------------------------------------------------------|
| ok          | Binary present, `cacheDir/graph.json` present, data extracted without errors |
| degraded    | Binary ran, but a `query`/`affected` text parse error or partial data        |
| failed      | Non-zero exit code, timeout, or subprocess error                             |
| unavailable | GRAPHIFY_BIN absent, `cacheDir/graph.json` missing, or `cache_root_inside_repo` |
| skipped     | CLAUDE_GRAPHIFY_ENABLED=0, --no-graphify flag, or nil blast-radius-map       |

Availability is keyed on **`cacheDir/graph.json`** (NOT a legacy manifest path). DEV always receives a valid (possibly empty) `graph_context` object regardless of status.

---

## Feature Flags

| Variable                   | Default | Description                                          |
|----------------------------|---------|------------------------------------------------------|
| CLAUDE_GRAPHIFY_ENABLED    | auto    | auto=run if available; 1=force on; 0=disable         |
| GRAPHIFY_BIN               | (PATH)  | Override CLI path                                    |
| CLAUDE_GRAPHIFY_CACHE_ROOT | /var/tmp/claude-graphify | Override cache root (MUST be OUTSIDE the repo) |
| GRAPHIFY_TRIAGE_BACKEND    | (auto)  | Force semantic backend (else auto-detect via API keys → keyless `claude-cli`) |
| GEMINI_API_KEY / GOOGLE_API_KEY | (unset) | Enable Gemini semantic extraction               |

`GRAPHIFY_OUT` is **wrapper-internal** (set to cacheDir by `run_graphify_cmd`) and is NOT a user override for the wrappers — it only affects a human running `graphify` directly. Pass `--no-graphify` to `/dev` for per-invocation disable.

---

## Semantic Extraction (AST-first, proof-gated)

`graphify update` is AST-only by design. Semantic edges come from `graphify extract --backend B`, which runs LLM extraction on docs/papers/images. Backend selection: API-key env vars (Gemini/Kimi/Claude/OpenAI/DeepSeek) auto-detect via graphify's `detect_backend()`; with NO key set, the keyless **`claude-cli`** backend works when `/usr/bin/claude` is present (uses the Pro/Max subscription, no API key).

`graphify-maintain.py init` ALWAYS builds the AST graph FIRST, then runs a bounded semantic probe. It only promotes the semantic graph (and reports `semantic_mode=semantic:<backend>`) when the probe **demonstrably changes the graph** (node count differs — proof, not mere backend presence). Otherwise it keeps the AST graph and reports `semantic_mode=ast_only` with a reason. A semantic failure never loses the AST graph.

**AST-only quality caveat**: on prompt/config-heavy repos, AST-only blast-radius signal can be weak (high builtin/noise ratio). Semantic mode materially improves it but is environment-gated.

---

## Global Cache Lifecycle

```bash
# One-time initial build (user-triggered only — NEVER auto-triggered inside /dev)
python3 scripts/graphify-maintain.py init      # real `graphify update <repo>` + semantic probe (≤300s)

# Incremental refresh (runs automatically at Step 7.5 and post-/pull)
python3 scripts/graphify-maintain.py update    # real `graphify update <repo>` (≤60s)

# Status check (node/link counts + semantic mode)
python3 scripts/graphify-maintain.py status
```

The first full build is NEVER auto-triggered inside /dev. It must be run manually.

---

## Command Coverage

| Command        | Graphify integration                                     |
|----------------|----------------------------------------------------------|
| /dev           | Step 1.5 (pre-BA hydrator) + Step 7.5 (subagent)         |
| /dev-command   | Same as /dev (mirrors commands/dev.md)                   |
| /dev-overnight | Enabled; shares global cache via graphify-maintain.py    |
| /redev         | Inherits /dev behavior                                   |
| /pull          | Post-pull incremental update (non-blocking advisory)     |
| /refactor      | Optional (not implemented in v1)                         |
| /clean         | Disabled                                                 |

---

## Advisory vs Clarification-Blocking

- **Graphify tool failure** (status: degraded/failed/unavailable/skipped) → **advisory**: DEV always receives a valid graph_context object; tool failure never blocks DEV.
- **Requirement ambiguity** (implicit reference trigger words with no unique resolution) → **clarification-blocking**: BA must return `needs_clarification`.

---

## Architecture Note (arch-6)

`context-{ts}.json` is patched in-place by `graphify-enrich.py` to add the `graph_context` field. This diverges from a pure sidecar pattern (writing a separate file) but is accepted per spec Section 5. The deviation is recorded in `graph-report.md` for each task cycle.

---

## Sensitive Data Exclusion (arch-8)

`graphify_lib.py` defines `EXCLUDE_FRAGMENTS` from two authorities:

1. **Sensitive-data patterns** (spec §5 Risk-7 + arch-8): `.env`, `credentials`, `keys`, `/logs/`, `.pem`, `.key`, `.secret`
2. **Filesystem-noise patterns** (blast-radius-tool.py:35-38): `/venv/`, `/worktrees/`, `/.archive/`, `/plugins/`, `/.git/`, `/__pycache__/`, `/node_modules/`

---

## Agent Registration (arch-2)

`graphify` is registered at three sites together:
1. `CP_AGENTS` in `hooks/pretool-cp-checkin.py`
2. `ALLOWED_AGENTS` in `scripts/spec-check.py`
3. `agent_types` list in `hooks/prompt-workflow.py`

This mirrors the test-writer precedent (spec-20260518-225715 §5.2).
