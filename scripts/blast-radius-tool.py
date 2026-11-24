#!/usr/bin/env python3
"""blast-radius-tool.py — TDAD blast-radius analyser (spec-20260518-225715 §5.3).

Two phases:
  Phase 1 (BA-side, prediction):  --files <file_list> --output <path>
  Phase 2 (QA-side, verification): --git-diff [--base <ref>] --output <path>

The tool uses Python ast + subprocess grep (no jedi/rope) to produce a JSON
blast-radius-map.json with these top-level keys:
    schema_version, task_id, phase, generated_at,
    scope_filter_applied, analyzed_files, files_to_modify, files_to_create,
    edges[], coverage_gaps[], required_validation[]

Edges carry a confidence label (high|medium) indicating import vs textual reference.
hooks/ coverage_gaps are tagged severity=critical per spec §5.3.

Exits 0 on success, 1 on bad arguments, 2 on IO error.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Scope filtering -- spec §5.3 mandates excluding venv/, worktrees/, .archive,
# plugins/. Tool runs from project root; paths are made relative for output.
# The fragments are graphify_lib's filesystem-noise list, one list for both.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from graphify_lib import _FILESYSTEM_NOISE_FRAGMENTS as EXCLUDE_FRAGMENTS  # noqa: E402

# Per-source edge cap (spec-20260518-225715 Cycle 3 Debt 4 / AC-04): bound
# the number of edges emitted with the same `from` value, so a high-fanout
# source file (e.g., a widely-imported utility) cannot bloat the map. Edges
# beyond this cap are skipped and counted into top-level omitted_edges_count.
MAX_EDGES_PER_SOURCE_FILE = 50


def in_scope(path: str) -> bool:
    norm = "/" + path.replace("\\", "/").lstrip("/") + "/"
    return not any(frag in norm for frag in EXCLUDE_FRAGMENTS)


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Python AST analysis
# ---------------------------------------------------------------------------
def python_imports(file_path: Path) -> list[str]:
    """Return imported module dotted names (best-effort) for a .py file."""
    try:
        src = file_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(file_path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.append(mod)
    return out


def find_callers_via_grep(root: Path, basename: str) -> list[str]:
    """Use grep to find files that textually reference `basename`. In-scope filter applied.

    Two passes:
      1. Fixed-string search for the basename (`util.py`). Broad — picks up
         documentation, comments, and code; this is the historical behaviour
         and is preserved verbatim.
      2. Python-only module-stem search (`util`) constrained to Python import
         contexts. Uses a regex anchored to `import` / `from` keywords so a
         file that merely says the word `util` in prose does NOT count as a
         caller. Without this constraint the high-fanout cap test (AC-04)
         would never trigger because `from util import util` callers use the
         stem only, but a bare `-F util` scan would emit many false-positive
         edges from documentation / log files.
    """
    hits: set[str] = set()
    # Pass 1: fixed-string basename search (broad, historical).
    try:
        result = subprocess.run(
            ["grep", "-r", "-l", "--exclude-dir=.git",
             "--exclude-dir=venv", "--exclude-dir=__pycache__",
             "--exclude-dir=.archive", "--exclude-dir=worktrees",
             "--exclude-dir=plugins", "--exclude-dir=node_modules",
             "-F", basename, str(root)],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        result = None
    if result is not None:
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            rel = os.path.relpath(line, str(root))
            if in_scope(rel):
                hits.add(rel)
    # Pass 2: Python module-stem search constrained to import sites only.
    if basename.endswith(".py"):
        stem = basename[:-3]
        if stem and stem != basename:
            # Regex matches an import statement that mentions the stem as a
            # word, e.g. `import util`, `from util import x`, `from .util ...`,
            # `from pkg.util import ...`. Word-boundaries (`\b`) on each side
            # prevent matching `from utility import ...` or a prose mention
            # of `util` inside docstring narrative.
            # POSIX ERE (grep -E) — no Perl groups; use word boundaries via [^A-Za-z0-9_].
            # Two acceptable shapes:
            #   ^[ \t]*from <pkg-prefix>?<stem>([ \t.]|$)
            #   ^[ \t]*import <pre>?<stem>([ \t,]|$)
            # The leading anchor ^[ \t]* ensures the line is an import
            # statement (not prose). The trailing boundary ensures `util`
            # does not match `utility`.
            stem_re = (
                r"^[[:space:]]*(from[[:space:]]+[A-Za-z0-9_.]*"
                + stem
                + r"([[:space:]]|\.|$)|import[[:space:]]+[A-Za-z0-9_.,[:space:]]*"
                + stem
                + r"([[:space:]]|,|$))"
            )
            try:
                result2 = subprocess.run(
                    ["grep", "-r", "-l", "-E",
                     "--include=*.py",
                     "--exclude-dir=.git", "--exclude-dir=venv",
                     "--exclude-dir=__pycache__", "--exclude-dir=.archive",
                     "--exclude-dir=worktrees", "--exclude-dir=plugins",
                     "--exclude-dir=node_modules",
                     stem_re, str(root)],
                    capture_output=True, text=True, timeout=30,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                result2 = None
            if result2 is not None:
                for line in result2.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    rel = os.path.relpath(line, str(root))
                    if in_scope(rel):
                        hits.add(rel)
    return sorted(hits)


def find_dependent_tests(root: Path, target_rel: str) -> list[str]:
    """Search tests/** for files that reference the target by basename, module
    path, or relative path. Returns relative paths of matching test files.
    Limited to .py / .sh / .md test descriptors under tests/.
    """
    tests_root = root / "tests"
    if not tests_root.exists():
        return []
    basename = os.path.basename(target_rel)
    needles = {basename}
    # If the target is a Python module, also search for its dotted module path.
    if target_rel.endswith(".py"):
        mod = target_rel[:-3].replace("/", ".").lstrip(".")
        if mod:
            needles.add(mod)
    hits: set[str] = set()
    for needle in needles:
        try:
            result = subprocess.run(
                ["grep", "-r", "-l",
                 "--include=*.py", "--include=*.sh", "--include=*.md",
                 "--exclude-dir=__pycache__", "--exclude-dir=.archive",
                 "-F", needle, str(tests_root)],
                capture_output=True, text=True, timeout=20,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            rel = os.path.relpath(line, str(root))
            if in_scope(rel) and rel != target_rel:
                hits.add(rel)
    return sorted(hits)


def severity_for(rel_path: str) -> str:
    """Per spec §5.3: hooks/ coverage gaps are critical."""
    norm = rel_path.replace("\\", "/").lstrip("./")
    if norm.startswith("hooks/") or "/hooks/" in norm:
        return "critical"
    return "medium"


# ---------------------------------------------------------------------------
# Edge + coverage_gap construction
# ---------------------------------------------------------------------------
def build_report(
    root: Path,
    target_files: list[str],
    phase: str,
    task_id: str | None,
) -> dict:
    analyzed: list[str] = []
    edges: list[dict] = []
    coverage_gaps: list[dict] = []
    required_validation: list[dict] = []
    # Per spec-20260518-225715 Cycle 3 Debt 4 / AC-04: dedup key is the
    # 3-tuple (from, to, edge_type). Two edges with the same (from, to) but
    # different edge_type (e.g. python_import vs textual_reference) are
    # legitimately distinct semantic relationships and MUST be preserved.
    seen_edges: set[tuple[str, str, str]] = set()
    # Per-source-file edge-count tracker for MAX_EDGES_PER_SOURCE_FILE cap.
    # The "source file" here is the analyzed file `tf` being processed (the
    # file the user passed via --files or that turned up in --git-diff). The
    # cap bounds the number of edges contributed by a single analyzed file
    # in either direction (outgoing python_import + incoming textual/test).
    # This bounds a high-fanout source (e.g. a widely-imported util.py with
    # >50 sibling callers) from bloating the map. Edges beyond the cap are
    # skipped and counted into top-level omitted_edges_count.
    edges_per_analyzed_source: dict[str, int] = {}
    omitted_edges_count = 0
    current_analyzed: list[str] = [""]  # mutable holder so closure can read

    def _try_add_edge(edge: dict) -> None:
        """Add edge if (from,to,edge_type) is unique AND the analyzed-source
        cap is not exceeded; otherwise increment omitted_edges_count."""
        nonlocal omitted_edges_count
        key = (edge["from"], edge["to"], edge["edge_type"])
        if key in seen_edges:
            return
        src = current_analyzed[0]
        if src and edges_per_analyzed_source.get(src, 0) >= MAX_EDGES_PER_SOURCE_FILE:
            omitted_edges_count += 1
            return
        seen_edges.add(key)
        if src:
            edges_per_analyzed_source[src] = edges_per_analyzed_source.get(src, 0) + 1
        edges.append(edge)

    for tf in target_files:
        tf_norm = tf.replace("\\", "/")
        if not in_scope(tf_norm):
            continue
        abs_p = root / tf_norm
        analyzed.append(tf_norm)
        current_analyzed[0] = tf_norm

        # Import-based edges (Python files only)
        if tf_norm.endswith(".py") and abs_p.exists():
            for mod in python_imports(abs_p):
                if mod:
                    _try_add_edge({
                        "from": tf_norm,
                        "to": mod,
                        "confidence": "high",
                        "edge_type": "python_import",
                    })

        # Outgoing textual-reference fanout: who calls / imports this file?
        # Direction convention (spec-20260518-225715 Cycle 3 Debt 4 / AC-04):
        # textual_reference edges are emitted as (from=analyzed_source,
        # to=caller). This matches the "fanout from the analyzed source"
        # semantic used by the high-fanout cap test (the cap bounds outgoing
        # fanout, so per-edge `from` is the analyzed source). The reverse-
        # direction (caller → target) information is preserved in
        # `required_validation.callers[]` below.
        bn = os.path.basename(tf_norm)
        if bn:
            for caller in find_callers_via_grep(root, bn):
                if caller == tf_norm:
                    continue
                _try_add_edge({
                    "from": tf_norm,
                    "to": caller,
                    "confidence": "medium",
                    "edge_type": "textual_reference",
                })

        # Coverage gap detection: search tests/** for any dependent tests.
        # Only emit a coverage_gap when no dependent tests are found.
        # Per spec 5.3, hooks/ gaps are critical when present.
        sev = severity_for(tf_norm)
        is_hook = sev == "critical" and "hooks/" in tf_norm
        dependent_tests = find_dependent_tests(root, tf_norm)
        if dependent_tests:
            # Tests exist that reference this file — record edges, no gap.
            for t in dependent_tests:
                _try_add_edge({
                    "from": t,
                    "to": tf_norm,
                    "confidence": "medium",
                    "edge_type": "test_dependency",
                })
        else:
            coverage_gaps.append({
                "file": tf_norm,
                "gap_type": "no_automated_test",
                "severity": sev,
                "behavioral_test_only": is_hook,
                "exemption_hint": (
                    "canary-verify.sh tests this hook without modifying it; "
                    "Dev should declare an explicit exemption with this reason"
                    if is_hook else None
                ),
                "dependent_tests": [],
                "note": (
                    "spec 5.3: hooks/ severity critical" if is_hook
                    else f"No automated test for {tf_norm}; declare validation in dev-report"
                ),
            })

        # Required validation entries for callers of modified files.
        # Callers are now recovered from the outgoing textual_reference fanout
        # (from=tf_norm, to=caller) and from any test_dependency edges that
        # still use the (from=test, to=tf_norm) convention.
        callers = [e["to"] for e in edges
                   if e.get("from") == tf_norm and e.get("edge_type") == "textual_reference"]
        callers += [e["from"] for e in edges
                    if e.get("to") == tf_norm and e.get("edge_type") == "test_dependency"]
        if callers:
            required_validation.append({
                "file": tf_norm,
                "callers": sorted(set(callers))[:10],
                "validation_required": (
                    f"Verify edits to {tf_norm} do not break callers; "
                    "read full modified sections before and after edit."
                ),
            })

    report = {
        "schema_version": "1.2",
        "task_id": task_id,
        "phase": phase,
        "generated_at": now_iso(),
        "scope_filter_applied": "exclude: venv/, worktrees/, .archive, plugins/",
        "analyzed_files": sorted(set(analyzed)),
        "files_to_modify": sorted(set(analyzed)),
        "files_to_create": [],
        "edges": edges,
        "omitted_edges_count": omitted_edges_count,
        "max_edges_per_source_file": MAX_EDGES_PER_SOURCE_FILE,
        "coverage_gaps": coverage_gaps,
        "required_validation": required_validation,
    }
    return report


# ---------------------------------------------------------------------------
# Git diff source for Phase 2
# ---------------------------------------------------------------------------
def git_diff_files(base: str) -> list[str]:
    """Phase-2 file list: union of (a) tracked-modified files from
    `git diff --name-only <base>` and (b) untracked, non-ignored files from
    `git ls-files --others --exclude-standard`. Returns a deduplicated list
    preserving first-seen order so the output is stable across runs.

    Per spec-20260518-225715 Cycle 3 Debt 4 / AC-04: previously this only
    returned tracked-modified files, missing every new file the user added
    but did not yet git-add. Untracked-non-ignored detection closes that gap.
    """
    seen: set[str] = set()
    files: list[str] = []

    def _add(line: str) -> None:
        line = line.strip()
        if not line:
            return
        if line in seen:
            return
        if not in_scope(line):
            return
        seen.add(line)
        files.append(line)

    # (a) Tracked-modified files
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base],
            capture_output=True, text=True, timeout=20, check=False,
        )
        for line in result.stdout.splitlines():
            _add(line)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # (b) Untracked-non-ignored files (gitignore-aware)
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        for line in result.stdout.splitlines():
            _add(line)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="TDAD blast-radius tool (spec-20260518-225715 §5.3)"
    )
    parser.add_argument("--files", nargs="*", default=None,
                        help="Phase 1: comma- or space-separated file list to analyse")
    parser.add_argument("--git-diff", action="store_true",
                        help="Phase 2: take file list from `git diff --name-only <base>`")
    parser.add_argument("--base", default="HEAD",
                        help="Phase 2 git base ref (default HEAD)")
    parser.add_argument("--output", required=True,
                        help="Output JSON path")
    parser.add_argument("--task-id", default=None,
                        help="Optional task_id to embed in the JSON (for dev-registry/<task_id>/)")
    parser.add_argument("--root", default=os.getcwd(),
                        help="Project root (default: cwd)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    phase = "2-verification" if args.git_diff else "1-prediction"

    if args.git_diff:
        target_files = git_diff_files(args.base)
    else:
        if not args.files:
            print("blast-radius-tool: --files <list> required (or use --git-diff)",
                  file=sys.stderr)
            return 1
        # Accept either repeated args or a single comma-separated string.
        target_files = []
        for entry in args.files:
            target_files.extend(p.strip() for p in entry.split(",") if p.strip())

    report = build_report(root, target_files, phase, args.task_id)

    out_path = Path(args.output)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        print(f"blast-radius-tool: failed to write {out_path}: {e}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
