# Graphify Knowledge Graph Integration

**Tool**: graphifyy v0.8.25, CLI `graphify` (installed in `~/.claude/venv`)
**Architecture**: Dual-touchpoint integration in the /dev pipeline (B-lite — real CLI)
**Integration cycle**: task 20260530-105221 (rewrote the 3 wrappers to drive the REAL CLI)

---

## Overview

Graphify is a code-to-knowledge-graph tool that provides structural codebase context (import chains, module topology, function call graphs). The integration adds two phases to the /dev workflow:

- **Pre-BA hydrator (between Step 1 and Step 2)** — Deterministic pre-BA Bash hydrator (`graphify-query.py`): reads the real node-link `graph.json` and runs real `graphify query` to inject structural context BEFORE BA analysis.
- **Graphify enrichment (between Step 7 and Step 8)** — Graphify subagent enrichment (`graphify-enrich.py`): resolves the blast-radius-map paths to real graph node IDs, builds a focused subgraph deterministically from `graph.json` as a **reverse-blast-radius (R1) impact view** (see "Focused subgraph: R1 reverse-blast-radius" below), and runs real `graphify affected`, AFTER BA-QA validation and BEFORE DEV dispatch.

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

### Focused subgraph: R1 reverse-blast-radius (graphify-enrich.py)

`_build_deterministic_subgraph` builds the focused subgraph as a **directional, relation-filtered, file-aggregated reverse-dependent view** (ONE hop). This is the PRIMARY blast-radius signal DEV consumes via `graph_context`.

- **Orientation** (empirically validated; constant `ORIENTATION_MODE = "source_depender_target_dependency"`): graphify edges are `source = depender, target = dependency`. So the IMPACT set — who is affected when a seed changes — is the set of **reverse dependents**: links where `target == seed` AND `relation ∈ {imports, imports_from, calls, inherits, uses, re_exports}`; the dependent is the edge **source**.
- **`contains` is anchor-only**: a `contains` (file→symbol containment) edge is emitted ONLY when directly incident to a seed, to make the seed interpretable. It NEVER creates a reverse dependent, NEVER appears in `impact_files`, and is NEVER recursed through. Containment is not coupling and is not blast radius.
- **Forward dependencies are context-only**: `source == seed` coupling edges (what the seed uses) are emitted in `nodes`/`edges` for context but NEVER aggregated into `impact_files`.
- **Seed-first determinism**: node ids are assembled in the order seeds (in resolved order) → `contains` anchors → reverse-dependent sources → forward-dependency targets, THEN capped to `MAX_NODES` (100). Seeds are emitted before neighbours so the cap can never evict a seed unless the seed count alone exceeds the cap. The builder receives an ORDERED sequence of resolved ids (NOT a set) so seed order survives.
- **Additive output** (strictly back-compat, no schema version bump): `impact_files[]` (file-aggregated reverse-dependent impact, ≤25), `orientation_mode`, and `expansion_stats` (seed/edge counts + `truncated{nodes,edges,impact_files,seed_nodes}`). The full `impact_files[]` list reaches DEV on BOTH the `focused-subgraph.json` artifact AND the in-place `graph_context` patch; `graph-summary.json` carries ONLY the scalars `impact_file_count`, `orientation_mode`, and the `truncated` flags. Legacy `nodes`/`edges`/`module_boundaries` keys and item shapes are unchanged.

Depth-2 traversal, hub-pruning, per-intermediate caps, and scoring weights are explicitly deferred (not built). A future graphify orientation change is caught by tests / an explicit revalidation task, not by a noisy runtime self-check.

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
├── pre_query.json                        # pre-BA hydrator output (between Step 1 and Step 2): structural_context
├── graphify-run.json                     # graphify enrichment run manifest (between Step 7 and Step 8)
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

## Semantic Extraction (user-triggered, edge-signature proof-gated)

`graphify update` is AST-only by design. **`init` and `update` are AST-only and fast — they NEVER auto-probe semantic extraction.** Semantic edges come from `graphify extract --backend B`, which runs LLM extraction on docs/papers/images. Backend selection: API-key env vars (Gemini/Kimi/Claude/OpenAI/DeepSeek) auto-detect via graphify's `detect_backend()`; with NO key set, the keyless **`claude-cli`** backend works when `/usr/bin/claude` is present (uses the Pro/Max subscription, no API key).

### The manual `semantic` command

```bash
python3 scripts/graphify-maintain.py semantic [--timeout SECONDS]   # default 3600s
```

`semantic` is the explicit, user-triggered path that enables semantic mode. It:

1. Runs a fresh AST baseline `update` FIRST (never diffs `extract` output against a stale/garbage baseline). If that baseline fails/times-out or leaves `graph.json` missing/unparseable, it does NOT run `extract` and exits 0 advisory (`no fresh AST baseline`, AST retained).
2. Resolves the backend across the full 4-case matrix (forced → keyed → keyless-claude → none); it never passes `--backend None` and never labels a mode `semantic:None`. A keyed environment runs `extract` WITHOUT `--backend` (graphify auto-detects) and labels a promotion `semantic:auto`.
3. **Clears the prior `graphify-out/graph.json` BEFORE running extract** (clear-before-extract is mandatory) so a failed/timed-out current run can never promote a stale prior semantic graph.
4. Applies the corrected proof-gate: an **edge-signature set-diff** over valid confidences (`{EXTRACTED, INFERRED, AMBIGUOUS}`), NOT a node-count comparison. The signature is the 7-tuple `(source, target, relation, confidence, source_file, source_location, context)`. Because the AST graph already carries `EXTRACTED`/`INFERRED` confidences, confidence presence alone is NOT a discriminator — only NEW edges (by full signature, absent from the AST link set) count. Promotion requires `len(sem_nodes) >= len(ast_nodes)`, `len(sem_links) >= len(ast_links)`, AND at least one added valid-confidence edge.
5. Promotes the semantic graph (reports `semantic_mode=semantic:<backend>` + the added-link count) only on success; otherwise keeps the AST graph and reports `semantic_mode=ast_only`. A semantic failure never loses the AST graph.

### Source-of-truth reconciliation

Maintain's `run-manifest.json` `semantic_mode` is the authoritative semantic-state record; the on-disk `graph.json` is the authoritative graph — they must not diverge. Any AST overwrite of `graph.json` (maintain's `update` AND `graphify-enrich.py`'s Step-1 update during graphify enrichment, between Step 7 and Step 8) resets `semantic_mode` back to `ast_only` via the shared `graphify_lib.reset_semantic_mode_in_manifest(cache_dir)` helper whenever the graph was actually mutated, so `status` can never report a stale `semantic:<backend>` for a graph that is now AST-only.

**AST-only quality caveat**: on prompt/config-heavy repos, AST-only blast-radius signal can be weak (high builtin/noise ratio). Semantic mode materially improves it but is environment-gated and user-triggered.

---

## Global Cache Lifecycle

```bash
# One-time initial build (user-triggered only — NEVER auto-triggered inside /dev)
python3 scripts/graphify-maintain.py init               # real `graphify update <repo>` AST-only (≤300s)

# Incremental refresh (runs automatically during graphify enrichment, between Step 7 and Step 8, and post-/pull)
python3 scripts/graphify-maintain.py update             # real `graphify update <repo>` AST-only (≤60s)

# User-triggered semantic extraction (edge-signature proof-gated; promotes only on NEW edges)
python3 scripts/graphify-maintain.py semantic [--timeout SECONDS]   # real `graphify extract` (default 3600s)

# Status check (node/link counts + semantic mode + added-link counts when promoted)
python3 scripts/graphify-maintain.py status
```

`init` and `update` are AST-only and fast; they do NOT run semantic extraction. The first full build and any semantic enrichment are NEVER auto-triggered inside /dev — they must be run manually.

---

## Command Coverage

| Command        | Graphify integration                                     |
|----------------|----------------------------------------------------------|
| /dev           | pre-BA hydrator (between Step 1 and Step 2) + graphify enrichment subagent (between Step 7 and Step 8) |
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
