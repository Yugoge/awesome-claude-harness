#!/usr/bin/env python3
"""
graphify-query.py — deterministic pre-BA graph hydrator (runs between Step 1 and Step 2).

Drives the REAL `graphify` v0.8.25 CLI. Builds structural_context for BA from:
  Layer 1 — deterministic file/path mention extraction from the requirement text
  Layer 2 — node-link graph.json read (the DETERMINISTIC primary signal): edges
            are under `links` with source/target/relation; sensitive nodes/links
            are scrubbed ON READ (AC15)
  Layer 3 — real `graphify query "<anchor>" --graph <cacheDir/graph.json> --budget N`
            enrichment layered on top; its real stdout is consumed (and scrubbed)
            into structural_context. A query failure/timeout degrades to the
            graph.json-only signal (advisory, exit 0) but the call MUST be
            attempted when an anchor is present (AC2).

Output (≤2000 tokens, advisory, fail-open):
  .claude/dev-registry/{task_id}/graphify/pre_query.json

Usage:
  python3 scripts/graphify-query.py --task-id <ID> --requirement-file <path> [--no-graphify]

Feature flags:
  CLAUDE_GRAPHIFY_ENABLED=0  — exits immediately with status=skipped
  GRAPHIFY_BIN               — override CLI path
  CLAUDE_GRAPHIFY_CACHE_ROOT — override /var/tmp/claude-graphify (must be outside repo)

Exit codes:
  0 — always advisory (even status=unavailable/skipped/degraded)
  1 — hard error (cannot write output file)
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

_PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
# _PROJECT_DIR is the SUBJECT repo (what gets graphed). The tool's own libs live
# next to this script, NOT in the subject repo — resolve them relative to __file__
# so this script runs against any repo from a single global install (~/.claude).
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from graphify_lib import (
    STATUS_OK, STATUS_DEGRADED, STATUS_UNAVAILABLE, STATUS_SKIPPED,
    EXCLUDE_FRAGMENTS, TIMEOUT_QUERY,
    check_cache_available, contains_sensitive_fragment, empty_graph_context,
    get_cache_dir, get_repo_key, graph_json_path, is_graphify_enabled,
    load_graph, run_graphify_cmd, scrub_sensitive, should_exclude_path,
    write_json_locked,
)

# Implicit reference trigger words that signal ambiguity — per spec §5
IMPLICIT_REFERENCE_WORDS = [
    "\u4e4b\u524d", "\u5df2\u6709", "\u73b0\u6709", "\u539f\u6765\u7684",  # Chinese (Unicode escapes; runtime-equivalent to CJK glyphs)
    "previous", "existing", "original",  # English
]

# Hard token cap for structural_context
HARD_TOKEN_CAP = 2000
TARGET_TOKEN_MIN = 800
TARGET_TOKEN_MAX = 1500

# Rough token estimate: 1 token ≈ 4 chars
def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Layer 1: Deterministic rule-based extraction
# ---------------------------------------------------------------------------

def _extract_layer1_deterministic(requirement_text: str) -> list[str]:
    """Extract file/path mentions using regex patterns."""
    mentions = []

    # Pattern: explicit file paths (contains / or . with common extensions)
    path_re = re.compile(
        r'\b((?:[\w.-]+/)+[\w.-]+\.\w+|[\w.-]+\.(?:py|js|ts|tsx|jsx|sh|md|json|yaml|yml|toml|cfg|ini|txt))\b'
    )
    for m in path_re.finditer(requirement_text):
        candidate = m.group(1)
        if not should_exclude_path(candidate):
            mentions.append(candidate)

    # Pattern: quoted file names
    quoted_re = re.compile(r'[`"\']([^`"\']+\.(?:py|js|ts|tsx|jsx|sh|md|json|yaml|yml))[`"\']')
    for m in quoted_re.finditer(requirement_text):
        candidate = m.group(1)
        if not should_exclude_path(candidate):
            mentions.append(candidate)

    return list(dict.fromkeys(mentions))  # deduplicate preserving order


# ---------------------------------------------------------------------------
# Layer 2: deterministic node-link graph.json read (primary signal)
# ---------------------------------------------------------------------------

def _resolve_anchors_in_graph(mentions: list[str], graph: dict) -> dict[str, str]:
    """Resolve each mention to a graph node label/id present in graph.json.

    Returns {mention: anchor_label} for mentions that match a real node by
    basename/label/source_file. Used both to (a) populate resolved_path and
    (b) pick the input-derived anchor string passed to real `graphify query`.
    """
    resolved: dict[str, str] = {}
    nodes = graph.get("nodes", [])
    for mention in mentions:
        base = mention.replace("\\", "/").rsplit("/", 1)[-1]
        for n in nodes:
            label = n.get("label", "") or ""
            sf = (n.get("source_file", "") or "").replace("\\", "/")
            if label == base or label == mention or sf.endswith("/" + base) or sf == base or sf == mention:
                if not should_exclude_path(label) and not should_exclude_path(sf):
                    resolved[mention] = label or base
                    break
    return resolved


# Coupling relations that constitute real structural signal — aligned with
# scripts/graphify-enrich.py R1 REVERSE_DEPENDENT_RELATIONS. The pre-BA excerpt
# PRIORITISES these so inert `contains` (file->symbol skeleton, ~80% of links on
# doc/config-heavy repos) and bare `references` (mostly return-type-annotation noise)
# do NOT dominate the [:20] cap. Mirrors the Step-7.5/9 focused-subgraph emphasis so both
# touchpoints surface coupling first; non-coupling edges only fill leftover slots (so the
# excerpt is never empty on a coupling-poor graph — it just shows skeleton as last resort).
COUPLING_RELATIONS = frozenset(
    {"imports", "imports_from", "calls", "inherits", "uses", "re_exports"}
)


def _build_import_excerpt(graph: dict, anchor_labels: set[str]) -> list[str]:
    """Build a compact 'src --relation--> tgt' excerpt from node-link `links`.

    Reads edges from `links` (source/target/relation) — the REAL schema. Orders by
    (1) real coupling relations (COUPLING_RELATIONS), (2) everything else — and within
    each, anchor-touching links first. So a coupling-rich repo fills the [:20] cap with
    signal and never shows `contains` skeleton, while a coupling-poor graph still yields a
    populated excerpt from whatever edges exist. Sensitive links already removed on read.
    """
    nodes = graph.get("nodes", [])
    id_to_label = {n.get("id"): (n.get("label") or n.get("id")) for n in nodes}
    anchor_ids = {n.get("id") for n in nodes if (n.get("label") or "") in anchor_labels}
    coupling: list[str] = []
    other: list[str] = []
    for l in graph.get("links", []):
        src = l.get("source")
        tgt = l.get("target")
        rel = l.get("relation", "rel")
        line = f"{id_to_label.get(src, src)} --{rel}--> {id_to_label.get(tgt, tgt)}"
        if should_exclude_path(line):
            continue
        bucket = coupling if rel in COUPLING_RELATIONS else other
        # Anchor-touching links first within their bucket.
        if anchor_ids and (src in anchor_ids or tgt in anchor_ids):
            bucket.insert(0, line)
        else:
            bucket.append(line)
    # Coupling signal before skeleton/noise fallback; dedupe, then cap.
    return list(dict.fromkeys(coupling + other))[:20]


# ---------------------------------------------------------------------------
# Layer 3: real `graphify query` enrichment (MUST be attempted on healthy path)
# ---------------------------------------------------------------------------

def _run_real_query(anchor: str, graph_file: Path, cache_dir: Path) -> dict:
    """Invoke real `graphify query "<anchor>" --graph <graph_file> --budget N`.

    Consumes (and scrubs) the real stdout. Returns a record carrying the recorded
    argv (for proof-of-call), status, and the scrubbed text output. On error/timeout
    returns query_cli_status=degraded with the reason (advisory; the call WAS
    attempted — AC2 ADVISORY EXCEPTION).
    """
    args = ["query", anchor, "--graph", str(graph_file), "--budget", "2000"]
    exit_code, stdout, stderr = run_graphify_cmd(args, timeout_seconds=TIMEOUT_QUERY, cache_dir=cache_dir)
    record = {
        "anchor": anchor,
        "argv": ["graphify"] + args,  # recorded vector for proof-of-call
        "query_cli_status": STATUS_OK,
    }
    if exit_code != 0:
        record["query_cli_status"] = STATUS_DEGRADED
        record["reason"] = (stderr or f"exit={exit_code}")[:200]
        return record
    # Scrub raw stdout line-by-line: never emit a line carrying a sensitive fragment (AC15).
    safe_lines = [ln for ln in (stdout or "").splitlines() if not contains_sensitive_fragment(ln)]
    record["output"] = "\n".join(safe_lines)[:4000]
    return record


# ---------------------------------------------------------------------------
# Ambiguity detection
# ---------------------------------------------------------------------------

def _detect_ambiguity(requirement_text: str, candidate_anchors: list[dict]) -> list[dict]:
    """Detect implicit reference words and build ambiguity hypotheses."""
    hypotheses = []
    text_lower = requirement_text.lower()

    for word in IMPLICIT_REFERENCE_WORDS:
        if word.lower() in text_lower:
            # Build a hypothesis: what might 'previous/existing' refer to?
            hypothesis = {
                "trigger_word": word,
                "candidate_a": candidate_anchors[0]["mention"] if candidate_anchors else "unknown_file_A",
                "candidate_b": candidate_anchors[1]["mention"] if len(candidate_anchors) > 1 else "unknown_file_B",
                "evidence": f"Requirement contains implicit reference word '{word}'; BA must resolve before analysis",
            }
            hypotheses.append(hypothesis)

    return hypotheses


# ---------------------------------------------------------------------------
# Token truncation
# ---------------------------------------------------------------------------

def _truncate_structural_context(context: dict, hard_cap: int) -> tuple[dict, bool]:
    """Truncate structural_context to stay under hard_cap tokens."""
    serialized = json.dumps(context, ensure_ascii=False)
    if _estimate_tokens(serialized) <= hard_cap:
        return context, False

    # Progressive truncation: trim query results, excerpt, centrality nodes.
    context = dict(context)
    for key in ["graphify_query_results", "import_graph_excerpt", "high_centrality_nodes"]:
        if key in context and isinstance(context[key], list):
            while context[key] and _estimate_tokens(json.dumps(context, ensure_ascii=False)) > hard_cap:
                context[key] = context[key][:-1]

    # Trim candidate_anchors if still over
    if "candidate_anchors" in context:
        while context["candidate_anchors"] and _estimate_tokens(json.dumps(context, ensure_ascii=False)) > hard_cap:
            context["candidate_anchors"] = context["candidate_anchors"][:-1]

    return context, True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="graphify pre-BA hydrator (between Step 1 and Step 2)")
    parser.add_argument("--task-id", required=True, help="Dev session task ID")
    parser.add_argument("--requirement-file", required=True, help="Path to user requirement .md file")
    parser.add_argument("--no-graphify", action="store_true", help="Explicit per-invocation disable")
    args = parser.parse_args()

    output_dir = _PROJECT_DIR / ".claude" / "dev-registry" / args.task_id / "graphify"
    output_path = output_dir / "pre_query.json"

    # Feature flag check — no-op (status=skipped) when disabled
    if args.no_graphify or not is_graphify_enabled():
        result = empty_graph_context(STATUS_SKIPPED, "graphify disabled by flag or CLAUDE_GRAPHIFY_ENABLED=0")
        result.update({"task_id": args.task_id, "generated_at": _now_iso()})
        write_json_locked(output_path, result)
        print(f"graphify-query: skipped (status={STATUS_SKIPPED})")
        return 0

    # Cache availability check (keyed on cacheDir/graph.json, AC12)
    repo_key = get_repo_key(_PROJECT_DIR)
    cache_dir = get_cache_dir(_PROJECT_DIR)
    graph_file = graph_json_path(_PROJECT_DIR)
    available, reason = check_cache_available(repo_key, project_dir=_PROJECT_DIR)
    if not available:
        result = empty_graph_context(STATUS_UNAVAILABLE, reason)
        result.update({"task_id": args.task_id, "generated_at": _now_iso()})
        write_json_locked(output_path, scrub_sensitive(result))
        print(f"graphify-query: status=unavailable ({reason})")
        return 0

    # Read requirement text
    req_path = Path(args.requirement_file)
    if not req_path.exists():
        result = empty_graph_context(STATUS_UNAVAILABLE, f"requirement file not found: {req_path}")
        result.update({"task_id": args.task_id, "generated_at": _now_iso()})
        write_json_locked(output_path, scrub_sensitive(result))
        return 0

    requirement_text = req_path.read_text(encoding="utf-8")
    layers_used = []

    # Layer 1: deterministic mention extraction from the input under test.
    raw_mentions = _extract_layer1_deterministic(requirement_text)
    if raw_mentions:
        layers_used.append("deterministic_rules")

    # Layer 2: read the REAL node-link graph.json (sensitive nodes/links scrubbed on read).
    graph, gstatus = load_graph(graph_file)
    if gstatus == STATUS_OK:
        layers_used.append("graph_json_node_link")
    resolved_map = _resolve_anchors_in_graph(raw_mentions, graph)
    anchor_labels = set(resolved_map.values())
    import_graph = _build_import_excerpt(graph, anchor_labels)

    # Layer 3: real `graphify query` enrichment — MUST be attempted when an
    # input-derived anchor present/resolvable in graph.json exists (AC2).
    query_records: list[dict] = []
    query_cli_status = "not_attempted"
    # Prefer anchors resolvable in graph.json; fall back to raw mentions present as node labels.
    anchors_for_query = list(dict.fromkeys(resolved_map.values())) or [
        m for m in raw_mentions if m in {n.get("label") for n in graph.get("nodes", [])}
    ]
    for anchor in anchors_for_query[:5]:
        rec = _run_real_query(anchor, graph_file, cache_dir)
        query_records.append(rec)
        query_cli_status = rec.get("query_cli_status", STATUS_DEGRADED)
    if query_records:
        layers_used.append("real_graphify_query")

    # Build candidate_anchors (resolved_path comes from graph.json node match).
    candidate_anchors = []
    for mention in raw_mentions:
        if should_exclude_path(mention):
            continue
        candidate_anchors.append({
            "mention": mention,
            "resolved_path": resolved_map.get(mention, mention),
            "confidence": 0.9 if mention in resolved_map else 0.5,
        })

    ambiguity_hypotheses = _detect_ambiguity(requirement_text, candidate_anchors)

    structural_context = {
        "candidate_anchors": candidate_anchors,
        "import_graph_excerpt": import_graph,
        "high_centrality_nodes": [],
        "graphify_query_results": query_records,  # consumed real stdout (scrubbed)
        "query_cli_status": query_cli_status,
        "token_count": 0,
        "truncated": False,
    }

    # Final recursive sensitive scrub before truncation/emit (AC15 — defense in depth).
    structural_context = scrub_sensitive(structural_context)
    structural_context, was_truncated = _truncate_structural_context(structural_context, HARD_TOKEN_CAP)
    structural_context["truncated"] = was_truncated
    structural_context["token_count"] = _estimate_tokens(json.dumps(structural_context, ensure_ascii=False))

    if candidate_anchors or import_graph:
        status = STATUS_DEGRADED if query_cli_status == STATUS_DEGRADED else STATUS_OK
    else:
        status = STATUS_DEGRADED

    result = {
        "status": status,
        "task_id": args.task_id,
        "generated_at": _now_iso(),
        "structural_context": structural_context,
        "ambiguity_hypotheses": ambiguity_hypotheses,
        "extraction_layers_used": layers_used,
        "query_cli_status": query_cli_status,
        "cache_metadata": {
            "cache_dir": str(cache_dir),
            "repo_key": repo_key,
            "graph_json": str(graph_file),
        },
    }
    result = scrub_sensitive(result)
    write_json_locked(output_path, result)
    print(f"graphify-query: status={status}, anchors={len(candidate_anchors)}, "
          f"query_cli={query_cli_status}, output={output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
