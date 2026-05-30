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


def _build_deterministic_subgraph(graph: dict, resolved_ids: set[str]) -> dict:
    """Build the focused subgraph from graph.json nodes+links around resolved ids.

    PRIMARY signal (AC3 b). Emits REAL translated fields per AC14: each node carries
    id+label+source_file; each edge carries source+target+relation (verbatim from
    the node-link graph.json link). Includes 1-hop neighbours of the resolved ids.
    """
    all_nodes = {n.get("id"): n for n in graph.get("nodes", []) if n.get("id")}
    links = graph.get("links", [])

    # Seed set = resolved ids; expand to 1-hop neighbours via links.
    keep_ids = set(resolved_ids)
    edges_out = []
    for l in links:
        src, tgt, rel = l.get("source"), l.get("target"), l.get("relation")
        if src in resolved_ids or tgt in resolved_ids:
            keep_ids.add(src)
            keep_ids.add(tgt)
            edge = {"source": src, "target": tgt, "relation": rel}
            if not should_exclude_path(json.dumps(edge)):
                edges_out.append(edge)

    nodes_out = []
    for nid in keep_ids:
        n = all_nodes.get(nid)
        if not n:
            continue
        sf = n.get("source_file", "")
        if should_exclude_path(sf) or should_exclude_path(n.get("label", "")):
            continue
        nodes_out.append({
            "id": nid,
            "label": n.get("label", nid),
            "source_file": sf,
        })
    # Dedupe edges; cap to avoid token explosion.
    seen = set()
    uniq_edges = []
    for e in edges_out:
        k = (e["source"], e["target"], e["relation"])
        if k not in seen:
            seen.add(k)
            uniq_edges.append(e)
    return {
        "nodes": nodes_out[:100],
        "edges": uniq_edges[:200],
        "module_boundaries": [],
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
    """Build compact graph-summary.json."""
    return {
        "status": status,
        "node_count": len(subgraph.get("nodes", [])),
        "edge_count": len(subgraph.get("edges", [])),
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
        subgraph = _build_deterministic_subgraph(graph, set(resolved_node_ids))
        status = STATUS_OK if (subgraph["nodes"] or not resolved_node_ids) else STATUS_DEGRADED
    except Exception as exc:
        subgraph = {"nodes": [], "edges": [], "module_boundaries": []}
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
