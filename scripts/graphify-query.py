#!/usr/bin/env python3
"""
graphify-query.py — deterministic pre-BA graph hydrator (runs between Step 1 and Step 2).

Extracts file/concept mentions from user requirement text using 3-layer extraction:
  Layer 1 — deterministic rules (file extensions, path separators, known prefixes)
  Layer 2 — repo alias index (basename -> full path lookup from graph cache)
  Layer 3 — graph/fuzzy query via graphify CLI

Queries the global Graphify cache (read-only) and returns structural_context
(800-1500 tokens, hard cap 2000). Output is written to:
  .claude/dev-registry/{task_id}/graphify/pre_query.json

Usage:
  python3 scripts/graphify-query.py --task-id <ID> --requirement-file <path> [--no-graphify]

Feature flags:
  CLAUDE_GRAPHIFY_ENABLED=0  — exits immediately with status=skipped
  GRAPHIFY_BIN               — override CLI path
  CLAUDE_GRAPHIFY_CACHE_ROOT — override /var/tmp/claude-graphify

Exit codes:
  0 — success (even if status=unavailable/skipped — advisory)
  1 — hard error (cannot write output file)
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

_PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
sys.path.insert(0, str(_PROJECT_DIR / "scripts"))

from graphify_lib import (
    STATUS_OK, STATUS_DEGRADED, STATUS_UNAVAILABLE, STATUS_SKIPPED,
    EXCLUDE_FRAGMENTS,
    check_cache_available, empty_graph_context, get_cache_root, get_repo_key,
    is_graphify_enabled, run_graphify_cmd, should_exclude_path, write_json_locked,
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
# Layer 2: Repo alias index lookup
# ---------------------------------------------------------------------------

def _extract_layer2_alias_index(mentions: list[str], cache_dir: Path) -> dict[str, str]:
    """Resolve basenames to full paths via the graphify alias index."""
    index_path = cache_dir / "index" / "alias_index.json"
    if not index_path.exists():
        return {}
    try:
        alias_index = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    resolved = {}
    for mention in mentions:
        basename = Path(mention).name
        if basename in alias_index:
            full_path = alias_index[basename]
            if not should_exclude_path(full_path):
                resolved[mention] = full_path
    return resolved


# ---------------------------------------------------------------------------
# Layer 3: Graph/fuzzy query
# ---------------------------------------------------------------------------

def _extract_layer3_graph_query(mentions: list[str], cache_dir: Path) -> list[dict]:
    """Query graphify CLI for structural context around mentioned files."""
    bin_path = os.environ.get("GRAPHIFY_BIN", "").strip()
    if not bin_path:
        import shutil
        bin_path = shutil.which("graphify") or ""
    if not bin_path:
        return []

    results = []
    for mention in mentions[:10]:  # Limit to 10 to avoid token explosion
        exit_code, stdout, stderr = run_graphify_cmd(
            ["query", "--file", mention, "--format", "json", "--cache-dir", str(cache_dir)],
            timeout_seconds=30,
        )
        if exit_code == 0 and stdout.strip():
            try:
                data = json.loads(stdout)
                results.append({"mention": mention, "graph_data": data})
            except json.JSONDecodeError:
                pass
    return results


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

    # Progressive truncation: trim high_centrality_nodes and import_graph_excerpt
    context = dict(context)
    for key in ["import_graph_excerpt", "high_centrality_nodes"]:
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

    # Cache availability check
    repo_key = get_repo_key(_PROJECT_DIR)
    cache_root = get_cache_root()
    cache_dir = cache_root / repo_key
    available, reason = check_cache_available(repo_key)
    if not available:
        result = empty_graph_context(STATUS_UNAVAILABLE, reason)
        result.update({"task_id": args.task_id, "generated_at": _now_iso()})
        write_json_locked(output_path, result)
        print(f"graphify-query: status=unavailable ({reason})")
        return 0

    # Read requirement text
    req_path = Path(args.requirement_file)
    if not req_path.exists():
        result = empty_graph_context(STATUS_UNAVAILABLE, f"requirement file not found: {req_path}")
        result.update({"task_id": args.task_id, "generated_at": _now_iso()})
        write_json_locked(output_path, result)
        return 0

    requirement_text = req_path.read_text(encoding="utf-8")

    # 3-layer extraction
    layers_used = []

    # Layer 1: deterministic
    raw_mentions = _extract_layer1_deterministic(requirement_text)
    if raw_mentions:
        layers_used.append("deterministic_rules")

    # Layer 2: alias index
    resolved_map = _extract_layer2_alias_index(raw_mentions, cache_dir)
    if resolved_map:
        layers_used.append("repo_alias_index")

    # Layer 3: graph query
    graph_data = _extract_layer3_graph_query(raw_mentions, cache_dir)
    if graph_data:
        layers_used.append("graph_fuzzy_query")

    # Build candidate_anchors
    candidate_anchors = []
    for mention in raw_mentions:
        anchor = {
            "mention": mention,
            "resolved_path": resolved_map.get(mention, mention),
            "confidence": 0.9 if mention in resolved_map else 0.5,
        }
        candidate_anchors.append(anchor)

    # Build import_graph_excerpt from Layer 3 results
    import_graph = []
    for item in graph_data:
        gd = item.get("graph_data", {})
        if isinstance(gd, dict):
            edges = gd.get("edges", [])
            import_graph.extend([f"{e.get('from','?')} -> {e.get('to','?')}" for e in edges[:5]])

    # Detect ambiguity
    ambiguity_hypotheses = _detect_ambiguity(requirement_text, candidate_anchors)

    # Read cache manifest for metadata
    try:
        manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
    except Exception:
        manifest = {}

    structural_context = {
        "candidate_anchors": candidate_anchors,
        "import_graph_excerpt": import_graph[:20],
        "high_centrality_nodes": [],
        "token_count": 0,
        "truncated": False,
    }

    # Truncate to hard cap
    structural_context, was_truncated = _truncate_structural_context(structural_context, HARD_TOKEN_CAP)
    structural_context["truncated"] = was_truncated
    structural_context["token_count"] = _estimate_tokens(json.dumps(structural_context, ensure_ascii=False))

    status = STATUS_OK if candidate_anchors or import_graph else STATUS_DEGRADED

    result = {
        "status": status,
        "task_id": args.task_id,
        "generated_at": _now_iso(),
        "structural_context": structural_context,
        "ambiguity_hypotheses": ambiguity_hypotheses,
        "extraction_layers_used": layers_used,
        "cache_metadata": {
            "cache_root": str(cache_root),
            "repo_key": repo_key,
            "branch": manifest.get("branch", "unknown"),
            "head_sha": manifest.get("head_sha", "unknown"),
            "graphify_version": manifest.get("graphify_version", "unknown"),
        },
    }

    write_json_locked(output_path, result)
    print(f"graphify-query: status={status}, anchors={len(candidate_anchors)}, output={output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
