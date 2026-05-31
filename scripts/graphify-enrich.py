#!/usr/bin/env python3
"""
graphify-enrich.py — pre-DEV focused subgraph extractor (runs between Step 7 and Step 8).

Drives the REAL `graphify` v0.8.25 CLI. Runs as graphify subagent (mode=enrich)
after BA-QA validation, before DEV. Operations:
  1. Incremental real `graphify update <repo>` (advisory, out-of-repo cwd, ≤60s)
  2. Read blast-radius-map.json modified paths
  3. Resolve each modified path to real graph node.id values (source_file/label/symbols)
  4. Build the focused subgraph DETERMINISTICALLY from graph.json nodes+links
     around those ids (the PRIMARY signal) — translated to real human-readable
     fields (label, source_file, relation) per AC14
  5. Invoke real `graphify affected "<node.id>" --graph <cacheDir/graph.json> --depth N`
     seeded with a RESOLVED node id (never raw path/label); consume its stdout as
     enrichment layered on top; text-parse failure/timeout → status=degraded but the
     deterministic subgraph is kept (AC3)
  6. Patch context-{ts}.json in-place with graph_context (arch-6); sensitive paths
     scrubbed on read + on CLI stdout (AC15)

Nil-map fallback (arch-1): blast-radius-map absent → status=skipped, valid empty
graph_context, zero exception.

Usage:
  python3 scripts/graphify-enrich.py --task-id <ID> --context-file <path> [--no-graphify]

Exit codes:
  0 — always (advisory; DEV is never blocked by Graphify failure)
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Sequence

# --- R1 reverse-blast-radius contract (design-input-dev-20260531-134455 lines 26-75) ---
# Orientation is empirically validated on the real Applio graph (37 AST import pairs,
# 100% importer_to_imported): graphify edges are source=depender, target=dependency.
# Therefore reverse dependents of a seed X = links where target == X.
ORIENTATION_MODE = "source_depender_target_dependency"
# Coupling relations that constitute real blast radius (used for BOTH reverse-dependent
# selection by target==seed AND forward-dependency context by source==seed).
REVERSE_DEPENDENT_RELATIONS = frozenset(
    {"imports", "imports_from", "calls", "inherits", "uses", "re_exports"}
)
# `contains` is file->symbol containment: NOT coupling, anchor-only.
CONTAINS_RELATIONS = frozenset({"contains"})
MAX_NODES = 100
MAX_EDGES = 200
MAX_IMPACT_FILES = 25
MAX_IDS_PER_IMPACT_FILE = 5
MAX_LABELS_PER_IMPACT_FILE = 3

_PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
sys.path.insert(0, str(_PROJECT_DIR / "scripts"))

from graphify_lib import (
    STATUS_OK, STATUS_DEGRADED, STATUS_FAILED, STATUS_UNAVAILABLE, STATUS_SKIPPED,
    EXCLUDE_FRAGMENTS, TIMEOUT_UPDATE, TIMEOUT_AFFECTED,
    check_cache_available, contains_sensitive_fragment, empty_graph_context,
    get_cache_dir, get_repo_key, graph_json_path, is_cache_root_inside_repo,
    is_graphify_enabled, load_graph, resolve_paths_to_node_ids, run_graphify_cmd,
    scrub_sensitive, should_exclude_path, write_json_locked, read_json_safe,
    reset_semantic_mode_in_manifest,
)


def _graph_content_hash(path: Path) -> str | None:
    """Content-hash snapshot of graph.json, or None if absent (AC11 iter #3 guard)."""
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_blast_radius_map(task_id: str) -> tuple[dict | None, str]:
    """Load blast-radius-map.json. Returns (map_data, status)."""
    map_path = _PROJECT_DIR / ".claude" / "dev-registry" / task_id / "blast-radius-map.json"
    if not map_path.exists():
        return None, f"blast-radius-map.json absent at {map_path}"
    data, status = read_json_safe(map_path)
    if data is None:
        return None, f"blast-radius-map.json parse error (status={status})"
    return data, "ok"


def _collect_modified_paths(blast_radius_map: dict) -> list[str]:
    """Collect modified file paths from blast-radius-map (edges + modified_files)."""
    paths: list[str] = []
    # Real blast-radius-map edges use source/target; tolerate legacy from/to too.
    for edge in blast_radius_map.get("edges", []):
        for key in ("source", "target", "from", "to"):
            v = edge.get(key)
            if v and not should_exclude_path(v):
                paths.append(v)
    for f in blast_radius_map.get("modified_files", []):
        if f and not should_exclude_path(f):
            paths.append(f)
    for f in blast_radius_map.get("files", []):
        if isinstance(f, str) and f and not should_exclude_path(f):
            paths.append(f)
    return list(dict.fromkeys(paths))


def _build_deterministic_subgraph(graph: dict, resolved_node_ids: Sequence[str]) -> dict:
    """Build the R1 reverse-blast-radius focused subgraph from graph.json.

    PRIMARY signal (AC3 b). The DOMINANT blast-radius signal injected into DEV's
    graph_context. ONE hop only — directional, relation-filtered, file-aggregated.

    Orientation (validated, ORIENTATION_MODE): graphify edges are
    source=depender, target=dependency. So the IMPACT set (who is affected when a
    seed changes) is the REVERSE dependents = links where target == seed AND
    relation in REVERSE_DEPENDENT_RELATIONS; the dependent is the edge source.

    Sections, in deterministic emission order:
      1. Seeds in resolved order (deduped, missing/sensitive dropped). Seeds are
         emitted BEFORE neighbours so the MAX_NODES cap can never evict a seed
         unless the seed count alone exceeds the cap. `resolved_node_ids` MUST be an
         ORDERED sequence (NOT a set) — a set at the call site destroys seed order.
      2. `contains` anchors: a `contains` edge is included ONLY when directly
         incident to a seed (source==seed or target==seed). Anchor-only: it never
         creates a reverse dependent, never appears in impact_files, never recurses.
      3. Reverse dependents (impact): target==seed coupling edges; source = dependent.
      4. Forward dependencies (context only): source==seed coupling edges; never impact.

    Additive return fields (back-compat, no schema bump): impact_files,
    orientation_mode, expansion_stats. Legacy keys nodes/edges/module_boundaries and
    their item shapes (node={id,label,source_file}; edge={source,target,relation})
    are preserved verbatim.
    """
    all_nodes = {n.get("id"): n for n in graph.get("nodes", []) if n.get("id")}
    links = graph.get("links", [])

    def _node_allowed(nid: str) -> bool:
        n = all_nodes.get(nid)
        if not n:
            return False
        if should_exclude_path(n.get("source_file", "")) or should_exclude_path(n.get("label", "")):
            return False
        return True

    # --- Section 1: ordered, deduped, valid seeds (preserve resolved order) ---
    seed_count = 0
    valid_seeds: list[str] = []
    seen_seed = set()
    for nid in resolved_node_ids:
        seed_count += 1
        if nid in seen_seed:
            continue
        seen_seed.add(nid)
        if _node_allowed(nid):
            valid_seeds.append(nid)
    valid_seed_count = len(valid_seeds)
    missing_seed_count = len(seen_seed) - valid_seed_count
    seed_set = set(valid_seeds)

    # --- Scan links once into the four directional buckets ---
    contains_anchor_edges: list[dict] = []   # contains incident to a seed (anchor-only)
    reverse_edges: list[dict] = []           # target==seed coupling (impact)
    forward_edges: list[dict] = []           # source==seed coupling (context only)

    def _edge_ok(src: str, tgt: str, rel: str) -> bool:
        # Preserve the existing sensitive-path guard (pre_existing_guard line 115).
        return not should_exclude_path(json.dumps({"source": src, "target": tgt, "relation": rel}))

    for l in links:
        src, tgt, rel = l.get("source"), l.get("target"), l.get("relation")
        if not src or not tgt:
            continue
        if rel in CONTAINS_RELATIONS:
            if (src in seed_set or tgt in seed_set) and _edge_ok(src, tgt, rel):
                contains_anchor_edges.append({"source": src, "target": tgt, "relation": rel})
            continue
        if rel in REVERSE_DEPENDENT_RELATIONS:
            if tgt in seed_set and _edge_ok(src, tgt, rel):
                reverse_edges.append({"source": src, "target": tgt, "relation": rel})
            elif src in seed_set and _edge_ok(src, tgt, rel):
                forward_edges.append({"source": src, "target": tgt, "relation": rel})

    # --- Section 6: deterministic node id assembly (seeds first, then neighbours) ---
    ordered_ids: list[str] = []
    seen_id = set()

    def _add_id(nid: str) -> None:
        if nid in seen_id:
            return
        if not _node_allowed(nid):
            return
        seen_id.add(nid)
        ordered_ids.append(nid)

    for nid in valid_seeds:                       # (1) seeds in resolved order
        _add_id(nid)
    for e in contains_anchor_edges:               # (2) contains anchors
        _add_id(e["source"])
        _add_id(e["target"])
    for e in reverse_edges:                        # (3) reverse-dependent sources
        _add_id(e["source"])
    for e in forward_edges:                        # (4) forward-dependency targets
        _add_id(e["target"])

    nodes_truncated = len(ordered_ids) > MAX_NODES
    seed_nodes_truncated = valid_seed_count > MAX_NODES
    kept_ids = ordered_ids[:MAX_NODES]
    kept_set = set(kept_ids)

    nodes_out = []
    for nid in kept_ids:
        n = all_nodes.get(nid)
        sf = n.get("source_file", "")
        nodes_out.append({"id": nid, "label": n.get("label", nid), "source_file": sf})

    # --- Section 7: edges in deterministic sections; both endpoints must survive cap ---
    def _surviving(edges: list[dict]) -> list[dict]:
        return [e for e in edges if e["source"] in kept_set and e["target"] in kept_set]

    edges_ordered = (
        _surviving(contains_anchor_edges) + _surviving(reverse_edges) + _surviving(forward_edges)
    )
    seen_edge = set()
    uniq_edges = []
    for e in edges_ordered:
        k = (e["source"], e["target"], e["relation"])
        if k not in seen_edge:
            seen_edge.add(k)
            uniq_edges.append(e)
    edges_truncated = len(uniq_edges) > MAX_EDGES
    edges_out = uniq_edges[:MAX_EDGES]

    # --- Section 5: impact_files aggregation from reverse-dependent edges ONLY ---
    # Grouped by the dependent node's source_file. contains/forward never appear here.
    # seed_rank maps each seed id to its resolved-seed order so impact files sort by
    # the FIRST resolved seed they impact (design step 5), not by raw links order.
    seed_rank = {nid: i for i, nid in enumerate(valid_seeds)}
    impact_map: dict[str, dict] = {}
    for e in reverse_edges:
        dep = all_nodes.get(e["source"])
        if not dep:
            continue
        sf = dep.get("source_file", "") or "(unknown)"
        rec = impact_map.get(sf)
        if rec is None:
            rec = {
                "source_file": sf,
                "edge_count": 0,
                "relations": {},
                "_dep_ids": [],
                "_dep_labels": [],
                "_seed_ids": [],
                "_first_seed_rank": seed_rank.get(e["target"], len(valid_seeds)),
            }
            impact_map[sf] = rec
        rec["edge_count"] += 1
        # First-touched seed rank = the lowest resolved-seed rank among this file's edges.
        rec["_first_seed_rank"] = min(
            rec["_first_seed_rank"], seed_rank.get(e["target"], len(valid_seeds)))
        rel = e["relation"]
        rec["relations"][rel] = rec["relations"].get(rel, 0) + 1
        if e["source"] not in rec["_dep_ids"]:
            rec["_dep_ids"].append(e["source"])
        lbl = dep.get("label", e["source"])
        if lbl not in rec["_dep_labels"]:
            rec["_dep_labels"].append(lbl)
        if e["target"] not in rec["_seed_ids"]:
            rec["_seed_ids"].append(e["target"])

    impact_file_count_total = len(impact_map)
    # Deterministic order: (first resolved-seed rank touched, source_file) — O(n log n).
    sorted_files = sorted(impact_map, key=lambda sf: (impact_map[sf]["_first_seed_rank"], sf))
    impact_files = []
    for sf in sorted_files[:MAX_IMPACT_FILES]:
        rec = impact_map[sf]
        impact_files.append({
            "source_file": rec["source_file"],
            "edge_count": rec["edge_count"],
            "relations": dict(sorted(rec["relations"].items())),
            "dependent_node_ids": rec["_dep_ids"][:MAX_IDS_PER_IMPACT_FILE],
            "dependent_labels": rec["_dep_labels"][:MAX_LABELS_PER_IMPACT_FILE],
            "seed_node_ids": rec["_seed_ids"][:MAX_IDS_PER_IMPACT_FILE],
        })

    expansion_stats = {
        "seed_count": seed_count,
        "valid_seed_count": valid_seed_count,
        "missing_seed_count": missing_seed_count,
        "contains_anchor_edge_count": len(contains_anchor_edges),
        "reverse_edge_count": len(reverse_edges),
        "forward_edge_count": len(forward_edges),
        "impact_file_count_total": impact_file_count_total,
        "impact_file_count_emitted": len(impact_files),
        "caps": {
            "max_nodes": MAX_NODES,
            "max_edges": MAX_EDGES,
            "max_impact_files": MAX_IMPACT_FILES,
        },
        "truncated": {
            "nodes": nodes_truncated,
            "edges": edges_truncated,
            "impact_files": impact_file_count_total > MAX_IMPACT_FILES,
            "seed_nodes": seed_nodes_truncated,
        },
    }

    return {
        "nodes": nodes_out,
        "edges": edges_out,
        "module_boundaries": [],
        "impact_files": impact_files,
        "orientation_mode": ORIENTATION_MODE,
        "expansion_stats": expansion_stats,
    }


def _run_real_affected(node_id: str, graph_file: Path, cache_dir: Path) -> dict:
    """Invoke real `graphify affected "<node_id>" --graph <graph_file> --depth N`.

    node_id MUST be a RESOLVED node id (caller's responsibility — never a raw path
    or bare label, AC3). Consumes + scrubs the real stdout. On error/timeout returns
    affected_cli_status=degraded with the reason (advisory; the call WAS attempted).
    """
    args = ["affected", node_id, "--graph", str(graph_file), "--depth", "2"]
    exit_code, stdout, stderr = run_graphify_cmd(args, timeout_seconds=TIMEOUT_AFFECTED, cache_dir=cache_dir)
    record = {
        "node_id": node_id,
        "argv": ["graphify"] + args,  # recorded vector for proof-of-call
        "affected_cli_status": STATUS_OK,
    }
    if exit_code != 0:
        record["affected_cli_status"] = STATUS_DEGRADED
        record["reason"] = (stderr or f"exit={exit_code}")[:200]
        return record
    safe_lines = [ln for ln in (stdout or "").splitlines() if not contains_sensitive_fragment(ln)]
    record["output"] = "\n".join(safe_lines)[:4000]
    return record


def _build_graph_summary(subgraph: dict, status: str, run_manifest: dict) -> dict:
    """Build compact graph-summary.json.

    R1 additive fields are SCALARS ONLY (AC-A7, codex #5): impact_file_count,
    orientation_mode, and the truncated{...} flags. The full impact_files[] list
    MUST NOT be embedded here — it lives only on the focused-subgraph artifact and
    the DEV-facing graph_context patch, to keep graph-summary.json compact.
    """
    stats = subgraph.get("expansion_stats", {}) or {}
    return {
        "status": status,
        "node_count": len(subgraph.get("nodes", [])),
        "edge_count": len(subgraph.get("edges", [])),
        "impact_file_count": len(subgraph.get("impact_files", [])),
        "orientation_mode": subgraph.get("orientation_mode", ORIENTATION_MODE),
        "truncated": stats.get("truncated", {}),
        "update_run": run_manifest.get("update_run", {}),
        "generated_at": _now_iso(),
    }


def _build_graph_context_patch(subgraph: dict, status: str, task_id: str,
                               resolved_node_ids: list[str], unresolved_paths: list[str],
                               affected_records: list[dict], affected_cli_status: str) -> dict:
    """Build graph_context to patch into context-{ts}.json with REAL translated content (AC14)."""
    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])
    patch = {
        "status": status,
        "task_id": task_id,
        "generated_at": _now_iso(),
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "high_centrality_nodes": [n.get("label") for n in nodes[:5]],
        },
        # REAL translated machine-readable fields (AC14): id+label+source_file / source+target+relation.
        "nodes": nodes,
        "edges": edges,
        # R1 additive blast-radius signal (AC-A6): full impact list reaches DEV here.
        "impact_files": subgraph.get("impact_files", []),
        "orientation_mode": subgraph.get("orientation_mode", ORIENTATION_MODE),
        "expansion_stats": subgraph.get("expansion_stats", {}),
        "resolved_node_ids": resolved_node_ids,
        "unresolved_paths": unresolved_paths,
        "affected_cli_status": affected_cli_status,
        "graphify_affected_results": affected_records,
        "focused_subgraph_path": f".claude/dev-registry/{task_id}/graphify/focused-subgraph.json",
        "advisory": True,
    }
    return scrub_sensitive(patch)


def main() -> int:
    parser = argparse.ArgumentParser(description="graphify enrichment subagent (between Step 7 and Step 8)")
    parser.add_argument("--task-id", required=True, help="Dev session task ID")
    parser.add_argument("--context-file", help="Path to context-{ts}.json for in-place patching")
    parser.add_argument("--no-graphify", action="store_true", help="Explicit disable")
    args = parser.parse_args()

    task_id = args.task_id
    output_dir = _PROJECT_DIR / ".claude" / "dev-registry" / task_id / "graphify"
    output_dir.mkdir(parents=True, exist_ok=True)

    run_manifest: dict = {
        "status": STATUS_SKIPPED,
        "task_id": task_id,
        "generated_at": _now_iso(),
        "update_run": {"attempted": False},
        "subgraph_extraction": {"attempted": False, "blast_radius_map_present": False},
        "context_patch": {"patched": False},
        "artifacts": {},
    }

    # Feature flag — no-op when disabled
    if args.no_graphify or not is_graphify_enabled():
        run_manifest["status"] = STATUS_SKIPPED
        run_manifest["error_detail"] = "graphify disabled by flag or CLAUDE_GRAPHIFY_ENABLED=0"
        _write_outputs(output_dir, task_id, run_manifest, {}, STATUS_SKIPPED)
        print(f"graphify-enrich: status=skipped (disabled)")
        return 0

    # Nil-map fallback (arch-1) — status=skipped when blast-radius-map absent
    blast_radius_map, br_reason = _load_blast_radius_map(task_id)
    run_manifest["subgraph_extraction"]["blast_radius_map_present"] = blast_radius_map is not None

    if blast_radius_map is None:
        run_manifest["status"] = STATUS_SKIPPED
        run_manifest["error_detail"] = f"nil blast-radius-map: {br_reason}"
        run_manifest["subgraph_extraction"]["attempted"] = False
        _write_outputs(output_dir, task_id, run_manifest, {}, STATUS_SKIPPED)
        print(f"graphify-enrich: status=skipped ({br_reason})")
        _patch_context(args, empty_graph_context(STATUS_SKIPPED, br_reason), run_manifest)
        return 0  # Zero exception — DEV receives empty graph_context

    # Cache availability check (keyed on cacheDir/graph.json, AC12). Also refuses
    # cache-root-inside-repo (AC13) since check_cache_available reports that reason.
    repo_key = get_repo_key(_PROJECT_DIR)
    cache_dir = get_cache_dir(_PROJECT_DIR)
    graph_file = graph_json_path(_PROJECT_DIR)
    available, reason = check_cache_available(repo_key, project_dir=_PROJECT_DIR)

    if not available:
        run_manifest["status"] = STATUS_UNAVAILABLE
        run_manifest["error_detail"] = reason
        _write_outputs(output_dir, task_id, run_manifest, {}, STATUS_UNAVAILABLE)
        _patch_context(args, empty_graph_context(STATUS_UNAVAILABLE, reason), run_manifest)
        print(f"graphify-enrich: status=unavailable ({reason})")
        return 0  # advisory

    # Step 1: incremental real `graphify update` (advisory; cwd+GRAPHIFY_OUT=cacheDir in lib).
    run_manifest["update_run"]["attempted"] = True
    start = time.time()
    # Pre-update snapshot so we can prove whether the update mutated graph.json
    # (OBJ-1/AC11 three-branch reconciliation of maintain's stale semantic_mode).
    pre_snapshot = _graph_content_hash(graph_file)
    if not is_cache_root_inside_repo(_PROJECT_DIR):
        exit_code, stdout, stderr = run_graphify_cmd(
            ["update", str(_PROJECT_DIR)], timeout_seconds=TIMEOUT_UPDATE, cache_dir=cache_dir,
        )
    else:
        exit_code, stdout, stderr = -1, "", "cache_root_inside_repo"
    run_manifest["update_run"].update({
        "duration_seconds": round(time.time() - start, 1),
        "exit_code": exit_code,
    })
    if exit_code != 0:
        run_manifest["update_run"]["error"] = (stderr or "non-zero exit")[:500]
        # advisory — continue to extraction against the existing cache

    # OBJ-1 (AC11): whenever the Step-1 update actually MUTATED graph.json (success
    # exit 0, OR failed-but-mutated per iter #3), reconcile maintain's run-manifest
    # semantic_mode -> ast_only via the SHARED helper so `status` cannot lie. Done
    # AFTER the graph overwrite (graph-then-manifest). Advisory: errors swallowed.
    try:
        post_snapshot = _graph_content_hash(graph_file)
        if exit_code == 0 or (pre_snapshot != post_snapshot):
            reconciled = reset_semantic_mode_in_manifest(cache_dir)
            run_manifest["update_run"]["semantic_mode_reconciled"] = bool(reconciled)
    except Exception as exc:  # advisory — never break enrich (exit-0-always)
        run_manifest["update_run"]["semantic_reconcile_error"] = str(exc)
        print(f"graphify-enrich: semantic_mode reconcile failed (advisory): {exc}", file=sys.stderr)

    # Step 2: read real node-link graph (sensitive nodes/links scrubbed on read).
    graph, gstatus = load_graph(graph_file)
    modified_paths = _collect_modified_paths(blast_radius_map)
    resolved_map, unresolved_paths = resolve_paths_to_node_ids(modified_paths, graph)
    resolved_node_ids = list(dict.fromkeys(
        nid for ids in resolved_map.values() for nid in ids))

    run_manifest["subgraph_extraction"]["attempted"] = True
    run_manifest["subgraph_extraction"]["blast_radius_map_path"] = str(
        _PROJECT_DIR / ".claude" / "dev-registry" / task_id / "blast-radius-map.json"
    )
    run_manifest["subgraph_extraction"]["resolved_node_ids"] = resolved_node_ids
    run_manifest["subgraph_extraction"]["unresolved_paths"] = unresolved_paths

    # Step 3: build the deterministic focused subgraph (PRIMARY signal, AC3 b / AC14).
    try:
        # Pass the ORDERED resolved id list (NOT a set) so seed order reaches the
        # builder intact — seed-first node assembly requires it (AC-A4 seed-drop fix).
        subgraph = _build_deterministic_subgraph(graph, resolved_node_ids)
        status = STATUS_OK if (subgraph["nodes"] or not resolved_node_ids) else STATUS_DEGRADED
    except Exception as exc:
        # Keep the additive R1 fields present even on the degraded fallback so the
        # focused-subgraph artifact stays shape-consistent (codex finding 2).
        subgraph = {
            "nodes": [], "edges": [], "module_boundaries": [],
            "impact_files": [],
            "orientation_mode": ORIENTATION_MODE,
            "expansion_stats": {
                "seed_count": len(resolved_node_ids),
                "valid_seed_count": 0,
                "missing_seed_count": 0,
                "contains_anchor_edge_count": 0,
                "reverse_edge_count": 0,
                "forward_edge_count": 0,
                "impact_file_count_total": 0,
                "impact_file_count_emitted": 0,
                "caps": {"max_nodes": MAX_NODES, "max_edges": MAX_EDGES,
                         "max_impact_files": MAX_IMPACT_FILES},
                "truncated": {"nodes": False, "edges": False,
                              "impact_files": False, "seed_nodes": False},
            },
        }
        run_manifest["error_detail"] = f"subgraph extraction error: {exc}"
        status = STATUS_DEGRADED

    # Step 4: real `graphify affected` enrichment — MUST be attempted when ≥1 id
    # resolved (AC3 c). Seed with a RESOLVED node id ONLY.
    affected_records: list[dict] = []
    affected_cli_status = "not_attempted"
    for nid in resolved_node_ids[:5]:
        rec = _run_real_affected(nid, graph_file, cache_dir)
        affected_records.append(rec)
        affected_cli_status = rec.get("affected_cli_status", STATUS_DEGRADED)
    if affected_records and affected_cli_status == STATUS_DEGRADED:
        # text-parse/timeout degrades enrichment but keeps the deterministic subgraph.
        status = STATUS_DEGRADED if status == STATUS_OK else status
    run_manifest["affected_run"] = {
        "attempted": bool(resolved_node_ids),
        "affected_cli_status": affected_cli_status,
        "seeds": resolved_node_ids[:5],
    }
    run_manifest["status"] = status

    # Step 5: write artifacts.
    subgraph_artifact = dict(subgraph)
    subgraph_artifact["resolved_node_ids"] = resolved_node_ids
    subgraph_artifact["unresolved_paths"] = unresolved_paths
    _write_outputs(output_dir, task_id, run_manifest, subgraph_artifact, status)

    # Step 6: patch context.json in-place with REAL translated graph_context (AC14, arch-6).
    patch = _build_graph_context_patch(
        subgraph, status, task_id, resolved_node_ids, unresolved_paths,
        affected_records, affected_cli_status)
    _patch_context(args, patch, run_manifest)

    print(f"graphify-enrich: status={status}, nodes={len(subgraph.get('nodes', []))}, "
          f"edges={len(subgraph.get('edges', []))}, resolved={len(resolved_node_ids)}, "
          f"affected_cli={affected_cli_status}")
    return 0


def _patch_context(args, graph_context: dict, run_manifest: dict) -> None:
    """Patch graph_context into context-{ts}.json in place (scrubbed, advisory)."""
    if not args.context_file:
        return
    context_path = Path(args.context_file)
    if not context_path.exists():
        return
    try:
        ctx_data = json.loads(context_path.read_text(encoding="utf-8"))
        ctx_data["graph_context"] = scrub_sensitive(graph_context)
        write_json_locked(context_path, ctx_data)
        run_manifest["context_patch"] = {
            "patched": True,
            "context_path": str(context_path),
            "graph_context_size_tokens": len(json.dumps(ctx_data["graph_context"])) // 4,
        }
        print(f"graphify-enrich: patched graph_context into {context_path}")
    except Exception as exc:
        run_manifest["context_patch"] = {"patched": False, "error": str(exc)}
        print(f"graphify-enrich: context-patch failed (advisory): {exc}", file=sys.stderr)


def _write_outputs(output_dir: Path, task_id: str, run_manifest: dict, subgraph: dict, status: str) -> None:
    """Write all per-task artifacts."""
    # graphify-run.json
    write_json_locked(output_dir / "graphify-run.json", run_manifest)
    run_manifest["artifacts"] = {
        "focused_subgraph": str(output_dir / "focused-subgraph.json"),
        "graph_summary": str(output_dir / "graph-summary.json"),
        "graph_report": str(output_dir / "graph-report.md"),
    }

    # focused-subgraph.json (recursively scrubbed of sensitive paths, AC15)
    focused = {
        "status": status,
        "task_id": task_id,
        "generated_at": _now_iso(),
        "source_blast_radius_map": run_manifest.get("subgraph_extraction", {}).get("blast_radius_map_path"),
        **subgraph,
    }
    if status == STATUS_SKIPPED:
        focused["skip_reason"] = run_manifest.get("error_detail", "")
    write_json_locked(output_dir / "focused-subgraph.json", scrub_sensitive(focused))

    # graph-summary.json
    summary = _build_graph_summary(subgraph, status, run_manifest)
    write_json_locked(output_dir / "graph-summary.json", summary)

    # graph-report.md (human-readable; arch-6 notes context.json in-place patching diverges from sidecar pattern)
    report_lines = [
        f"# Graphify Enrichment Report — Task {task_id}",
        f"",
        f"**Status**: {status}",
        f"**Generated**: {_now_iso()}",
        f"",
        f"## Subgraph Summary",
        f"",
        f"- Nodes: {len(subgraph.get('nodes', []))}",
        f"- Edges: {len(subgraph.get('edges', []))}",
        f"",
        f"## Architecture Note",
        f"",
        f"context.json was patched in-place with the graph_context field. This diverges from the",
        f"sidecar pattern (writing a separate file) but is accepted per spec Section 5 (arch-6).",
        f"The deviation is recorded here for future audit.",
        f"",
        f"## Update Run",
        f"",
        f"- Exit code: {run_manifest.get('update_run', {}).get('exit_code', 'N/A')}",
        f"- Duration: {run_manifest.get('update_run', {}).get('duration_seconds', 0):.1f}s",
    ]
    if run_manifest.get("error_detail"):
        report_lines += ["", f"## Error Detail", "", run_manifest["error_detail"]]

    (output_dir / "graph-report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
