#!/usr/bin/env python3
"""
graphify-enrich.py — pre-DEV focused subgraph extractor (runs between Step 7 and Step 8).

Runs as graphify subagent (mode=enrich) after BA-QA validation passes, before DEV.
Operations:
  1. Runs graphify --update (incremental refresh, advisory)
  2. Reads blast-radius-map.json from dev-registry to seed the focused subgraph
  3. Extracts focused subgraph for files in blast-radius-map
  4. Patches context-{ts}.json in-place with graph_context field (arch-6 accepted divergence from sidecar)
  5. Writes per-task artifacts to .claude/dev-registry/{task_id}/graphify/

Nil-map fallback (arch-1):
  When blast-radius-map.json is absent (BA ran MICRO/SMALL tier), exits immediately
  with status=skipped. DEV receives a valid empty graph_context. Zero exception.

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

_PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
sys.path.insert(0, str(_PROJECT_DIR / "scripts"))

from graphify_lib import (
    STATUS_OK, STATUS_DEGRADED, STATUS_FAILED, STATUS_UNAVAILABLE, STATUS_SKIPPED,
    EXCLUDE_FRAGMENTS,
    check_cache_available, empty_graph_context, get_cache_root, get_repo_key,
    is_graphify_enabled, run_graphify_cmd, should_exclude_path,
    write_json_locked, read_json_safe,
)

INCREMENTAL_TIMEOUT = 300  # 5 min


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


def _extract_focused_subgraph(blast_radius_map: dict, cache_dir: Path) -> dict:
    """Extract subgraph nodes/edges for files in blast-radius-map."""
    # Collect all files from blast-radius-map edges
    modified_files = set()
    edges = blast_radius_map.get("edges", [])
    for edge in edges:
        src = edge.get("from", "")
        dst = edge.get("to", "")
        for f in (src, dst):
            if f and not should_exclude_path(f):
                modified_files.add(f)

    # Also include top-level modified_files if present
    for f in blast_radius_map.get("modified_files", []):
        if not should_exclude_path(f):
            modified_files.add(f)

    # Build node list
    nodes = [{"path": f, "node_type": "source"} for f in sorted(modified_files)]

    # Try to load graph.json for edge data
    graph_path = cache_dir / "graph.json"
    subgraph_edges = []
    if graph_path.exists():
        try:
            graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
            all_edges = graph_data.get("edges", [])
            for e in all_edges:
                src = e.get("from", "")
                dst = e.get("to", "")
                if (src in modified_files or dst in modified_files) and \
                        not should_exclude_path(src) and not should_exclude_path(dst):
                    subgraph_edges.append({
                        "from": src,
                        "to": dst,
                        "edge_type": e.get("type", "import"),
                    })
        except Exception:
            pass

    return {
        "nodes": nodes,
        "edges": subgraph_edges[:200],  # Cap edges to avoid token explosion
        "module_boundaries": [],
    }


def _build_graph_summary(subgraph: dict, status: str, run_manifest: dict) -> dict:
    """Build compact graph-summary.json."""
    return {
        "status": status,
        "node_count": len(subgraph.get("nodes", [])),
        "edge_count": len(subgraph.get("edges", [])),
        "update_run": run_manifest.get("update_run", {}),
        "generated_at": _now_iso(),
    }


def _build_graph_context_patch(subgraph: dict, status: str, task_id: str) -> dict:
    """Build graph_context object to patch into context-{ts}.json."""
    return {
        "status": status,
        "task_id": task_id,
        "generated_at": _now_iso(),
        "summary": {
            "node_count": len(subgraph.get("nodes", [])),
            "edge_count": len(subgraph.get("edges", [])),
            "high_centrality_nodes": [
                n["path"] for n in subgraph.get("nodes", [])[:5]
            ],
        },
        "focused_subgraph_path": f".claude/dev-registry/{task_id}/graphify/focused-subgraph.json",
        "graph_report_path": f".claude/dev-registry/{task_id}/graphify/graph-report.md",
        "advisory": True,
    }


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
        if args.context_file:
            context_path = Path(args.context_file)
            if context_path.exists():
                try:
                    ctx_data = json.loads(context_path.read_text(encoding="utf-8"))
                    ctx_data["graph_context"] = empty_graph_context(STATUS_SKIPPED, br_reason)
                    write_json_locked(context_path, ctx_data)
                    print(f"graphify-enrich: patched graph_context(status=skipped) into {context_path}")
                except Exception as exc:
                    print(f"graphify-enrich: context-patch failed (advisory): {exc}", file=sys.stderr)
        return 0  # Zero exception — DEV receives empty graph_context

    # Cache availability check
    repo_key = get_repo_key(_PROJECT_DIR)
    cache_root = get_cache_root()
    cache_dir = cache_root / repo_key
    available, reason = check_cache_available(repo_key)

    if not available:
        run_manifest["status"] = STATUS_UNAVAILABLE
        run_manifest["error_detail"] = reason
        _write_outputs(output_dir, task_id, run_manifest, {}, STATUS_UNAVAILABLE)
        print(f"graphify-enrich: status=unavailable ({reason})")
        return 0  # advisory

    # Step 1: incremental update
    run_manifest["update_run"]["attempted"] = True
    start = time.time()
    exit_code, stdout, stderr = run_graphify_cmd(
        ["--update", "--output-dir", str(cache_dir), "--project-dir", str(_PROJECT_DIR)],
        timeout_seconds=INCREMENTAL_TIMEOUT,
        cwd=str(_PROJECT_DIR),
    )
    elapsed = time.time() - start
    run_manifest["update_run"].update({
        "duration_seconds": round(elapsed, 1),
        "exit_code": exit_code,
    })
    if exit_code != 0:
        run_manifest["update_run"]["error"] = stderr[:500] if stderr else "non-zero exit"
        # Update failed is advisory — continue to extraction with existing cache

    # Step 2: focused subgraph extraction
    run_manifest["subgraph_extraction"]["attempted"] = True
    run_manifest["subgraph_extraction"]["blast_radius_map_path"] = str(
        _PROJECT_DIR / ".claude" / "dev-registry" / task_id / "blast-radius-map.json"
    )

    try:
        subgraph = _extract_focused_subgraph(blast_radius_map, cache_dir)
        run_manifest["subgraph_extraction"]["nodes_extracted"] = len(subgraph["nodes"])
        run_manifest["subgraph_extraction"]["edges_extracted"] = len(subgraph["edges"])
        status = STATUS_OK
    except Exception as exc:
        subgraph = {"nodes": [], "edges": [], "module_boundaries": []}
        run_manifest["error_detail"] = f"subgraph extraction error: {exc}"
        status = STATUS_DEGRADED

    run_manifest["status"] = status

    # Step 3: write artifacts
    _write_outputs(output_dir, task_id, run_manifest, subgraph, status)

    # Step 4: patch context.json in-place (arch-6 accepted divergence from sidecar)
    if args.context_file:
        context_path = Path(args.context_file)
        if context_path.exists():
            try:
                ctx_data = json.loads(context_path.read_text(encoding="utf-8"))
                ctx_data["graph_context"] = _build_graph_context_patch(subgraph, status, task_id)
                write_json_locked(context_path, ctx_data)
                run_manifest["context_patch"] = {
                    "patched": True,
                    "context_path": str(context_path),
                    "graph_context_size_tokens": len(json.dumps(ctx_data["graph_context"])) // 4,
                }
                print(f"graphify-enrich: patched graph_context into {context_path}")
            except Exception as exc:
                run_manifest["context_patch"] = {"patched": False, "error": str(exc)}

    print(f"graphify-enrich: status={status}, nodes={len(subgraph.get('nodes',[]))}, edges={len(subgraph.get('edges',[]))}")
    return 0


def _write_outputs(output_dir: Path, task_id: str, run_manifest: dict, subgraph: dict, status: str) -> None:
    """Write all per-task artifacts."""
    # graphify-run.json
    write_json_locked(output_dir / "graphify-run.json", run_manifest)
    run_manifest["artifacts"] = {
        "focused_subgraph": str(output_dir / "focused-subgraph.json"),
        "graph_summary": str(output_dir / "graph-summary.json"),
        "graph_report": str(output_dir / "graph-report.md"),
    }

    # focused-subgraph.json
    focused = {
        "status": status,
        "task_id": task_id,
        "generated_at": _now_iso(),
        "source_blast_radius_map": run_manifest.get("subgraph_extraction", {}).get("blast_radius_map_path"),
        **subgraph,
    }
    if status == STATUS_SKIPPED:
        focused["skip_reason"] = run_manifest.get("error_detail", "")
    write_json_locked(output_dir / "focused-subgraph.json", focused)

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
