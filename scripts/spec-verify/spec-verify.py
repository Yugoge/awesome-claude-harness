#!/usr/bin/env python3
"""Verify 100% coverage of a monolith spec in agent view files.

Every non-blank, non-separator line from the monolith must appear
(stripped) in at least one view file. View file headers (lines before
the first '---' separator after the HTML comment) are ignored.

Usage:
    spec-verify.py --monolith <path.md> --views-dir <views-dir/>

Exit codes:
    0  All non-blank monolith lines are covered (>= min-coverage%).
    1  Coverage is below the threshold.
    2  Usage / file error.
"""

import argparse
import itertools
import os
import re
import sys

# Sidecars (800-line quality-gate budget forced the split). Re-exported
# so downstream checks can call them as module-level names. T2: parsers.
# T4: summary helpers + Layer-1 sha256 validator. T5: mandate check +
# is_strict_guide_mode gate (reused by T6). T6: utility / ambiguous /
# meta-rule checks gated on the same R3.0 strict-guide criterion.
from spec_verify_parsers import (  # noqa: F401 -- re-exports
    HEADING_REGEX, CONSUMERS_REGEX, CONSUMERS_INLINE_REGEX,
    parse_front_matter, parse_role_headings,
    parse_consumers_tags, lookup_role_block,
)
from spec_verify_summary import (  # noqa: F401 -- re-exports
    CheckResult, validate_layer_1, print_summary, stub_mandate_result,
)
from spec_verify_mandate import (  # noqa: F401 -- re-exports
    is_strict_guide_mode, run_mandate_check,
)
from spec_verify_gated import (  # noqa: F401 -- re-exports
    run_utility_check, run_ambiguous_check, run_meta_rule_check,
)


def _add_io_args(p):
    """Register input/output path arguments on the parser."""
    p.add_argument("--monolith", required=True,
        help="Path to the monolith spec .md file")
    p.add_argument("--views-dir", required=True,
        help="Directory containing agent view .md files")
    p.add_argument("--min-coverage", type=float, default=100.0,
        help="Minimum coverage percentage required (default: 100.0)")
    p.add_argument("--show-uncovered", action="store_true", default=False,
        help="Print uncovered line numbers and first 80 chars")


def _add_check_args(p):
    """Register check-tuning arguments on the parser."""
    p.add_argument("--strict", action="store_true", default=False,
        help="Treat structural issues (missing Role Mandate, etc.) as hard failures")
    p.add_argument("--max-pairwise-overlap", type=float, default=30.0,
        help="Reject if any pair of consumer views exceeds this overlap %% "
             "(default: 30.0 -- D12 rule: views cite monolith by line-range, "
             "not inline-paste. Default 30%% rejects inline-paste duplication.)")
    p.add_argument("--min-uniqueness", type=float, default=15.0,
        help="Reject if any consumer view has less than this %% unique lines (default: 15.0)")
    p.add_argument("--no-fabrication", action="store_true", default=False,
        help="Reject views with content lines that are neither verbatim monolith "
             "substrings nor matching the structural whitelist. Implied by --strict.")


def parse_args():
    p = argparse.ArgumentParser(
        description="Verify monolith spec coverage in agent views."
    )
    _add_io_args(p)
    _add_check_args(p)
    return p.parse_args()


def is_skippable(line_stripped):
    """Lines that do not count toward coverage."""
    if not line_stripped:
        return True
    if line_stripped == "---":
        return True
    return False


def _find_header_end(lines):
    """Return the 0-based index of the first '---' line after line 3."""
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped == "---" and (i + 1) > 3:
            return i
    return -1


def load_view_content_lines(view_path):
    """Load a view file, skip the header up to first '---' after line 3."""
    with open(view_path, encoding="utf-8") as f:
        lines = f.readlines()

    header_end = _find_header_end(lines)
    body = lines[header_end + 1:] if header_end >= 0 else lines

    content_lines = set()
    for raw in body:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("<!-- AUTO-GENERATED"):
            continue
        content_lines.add(stripped)
    return content_lines


def collect_view_lines(views_dir):
    """Scan views directory, return merged content lines and file info."""
    all_lines = set()
    file_info = []
    for name in sorted(os.listdir(views_dir)):
        if not name.endswith(".md"):
            continue
        vpath = os.path.join(views_dir, name)
        view_lines = load_view_content_lines(vpath)
        file_info.append((name, len(view_lines)))
        all_lines.update(view_lines)
    return all_lines, file_info


def check_coverage(monolith_lines, all_view_lines):
    """Compare monolith lines against view lines, return stats."""
    total = 0
    covered = 0
    uncovered = []
    for line_num, raw in enumerate(monolith_lines, 1):
        stripped = raw.strip()
        if is_skippable(stripped):
            continue
        total += 1
        if stripped in all_view_lines:
            covered += 1
        else:
            uncovered.append((line_num, stripped))
    return total, covered, uncovered


def print_report(args, file_info, monolith_lines, total, covered, uncovered):
    """Print human-readable coverage report."""
    print(f"Monolith: {args.monolith}")
    print(f"Views directory: {args.views_dir}")
    print(f"View files: {len(file_info)}")
    for name, count in file_info:
        print(f"  {name}: {count} content lines")
    print()
    print(f"Total monolith lines: {len(monolith_lines)}")
    print(f"Checkable lines (non-blank, non-separator): {total}")
    print(f"Covered lines: {covered}")
    print(f"Uncovered lines: {len(uncovered)}")
    pct = (covered / total * 100.0) if total else 0.0
    print(f"Coverage: {pct:.1f}%")
    if uncovered:
        print_uncovered(uncovered)
    return pct


def print_uncovered(uncovered):
    """Print the list of uncovered monolith lines."""
    print()
    print("Uncovered lines:")
    for ln, text in uncovered[:50]:
        preview = text[:100] + ("..." if len(text) > 100 else "")
        print(f"  L{ln}: {preview}")
    if len(uncovered) > 50:
        print(f"  ... and {len(uncovered) - 50} more")


def validate_inputs(args):
    """Check that monolith and views-dir exist."""
    if not os.path.isfile(args.monolith):
        print(f"ERROR: Monolith file not found: {args.monolith}", file=sys.stderr)
        sys.exit(2)
    if not os.path.isdir(args.views_dir):
        print(f"ERROR: Views directory not found: {args.views_dir}", file=sys.stderr)
        sys.exit(2)


def print_show_uncovered(uncovered):
    """Print uncovered lines in deterministic fallback format."""
    print("\n--- show-uncovered (deterministic fallback format) ---")
    for ln, text in uncovered:
        print(f"  L{ln}: {text[:80]}")
    print(f"--- end ({len(uncovered)} uncovered lines) ---")


SKIP_FILES = {"orchestrator.md", "manifest.json", "INDEX.md", "README.md", "checkpoints.json"}


def _check_view_file(name, path):
    """Check a single non-orchestrator view for mandatory sections."""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    checks = [
        ("Role Mandate", "## role mandate" in content.lower()),
    ]
    return [{"file": name, "check": c, "status": "missing"} for c, ok in checks if not ok]


def _check_orchestrator(views_dir):
    """Check orchestrator.md for its specific mandatory sections."""
    orch_path = os.path.join(views_dir, "orchestrator.md")
    if not os.path.isfile(orch_path):
        return []
    with open(orch_path, encoding="utf-8") as f:
        content = f.read()
    lower = content.lower()
    has_section = "## pipeline workflow" in lower or "## role mandate" in lower
    checks = [
        ("Pipeline Workflow or Role Mandate", has_section),
    ]
    return [{"file": "orchestrator.md", "check": c, "status": "missing"}
            for c, ok in checks if not ok]


def check_structure(views_dir):
    """Check mandatory sections in each view file. Returns list of issues."""
    issues = []
    for name in sorted(os.listdir(views_dir)):
        if not name.endswith(".md") or name in SKIP_FILES:
            continue
        issues.extend(_check_view_file(name, os.path.join(views_dir, name)))
    issues.extend(_check_orchestrator(views_dir))
    return issues


def print_structural_report(issues):
    """Print structural check results."""
    print("\n--- Structural checks ---")
    if not issues:
        print("All views pass structural checks.")
        return
    print(f"Found {len(issues)} structural issue(s):")
    for issue in issues:
        print(f"  {issue['file']}: {issue['check']} -> {issue['status']}")


def run_coverage(args):
    """Run coverage check and return coverage percentage. Exits on failure."""
    with open(args.monolith, encoding="utf-8") as f:
        monolith_lines = f.readlines()

    all_view_lines, file_info = collect_view_lines(args.views_dir)
    if not file_info:
        print("ERROR: No .md view files found in views directory.", file=sys.stderr)
        sys.exit(2)

    total, covered, uncovered = check_coverage(monolith_lines, all_view_lines)
    if total == 0:
        print("WARNING: Monolith has no checkable lines.")
        sys.exit(0)

    pct = print_report(args, file_info, monolith_lines, total, covered, uncovered)
    if args.show_uncovered and uncovered:
        print_show_uncovered(uncovered)
    return pct


# ---------------------------------------------------------------------------
# Overlap + uniqueness detection
# ---------------------------------------------------------------------------

# Consumer views are discovered dynamically from views_dir at runtime.
# orchestrator.md is special-cased (it legitimately references content from
# all pipelines, so we exclude it from overlap analysis) via SKIP_FILES.

# Warning tier thresholds (fixed -- the REJECT thresholds are CLI-configurable).
WARN_PAIRWISE_OVERLAP = 50.0
WARN_UNIQUENESS = 30.0


def discover_consumer_views(views_dir):
    """Return sorted list of .md view filenames in views_dir minus SKIP_FILES.

    Dynamic discovery replaces the former hardcoded CONSUMER_VIEWS tuple so
    that any consumer view file in views_dir (dev.md, qa.md, user.md, ba.md,
    ui-specialist.md, pm.md, architect.md, ...) is included in overlap
    analysis. orchestrator.md stays excluded via SKIP_FILES.
    """
    if not os.path.isdir(views_dir):
        return []
    names = []
    for name in sorted(os.listdir(views_dir)):
        if not name.endswith(".md"):
            continue
        if name in SKIP_FILES:
            continue
        names.append(name)
    return names


def load_consumer_views(views_dir):
    """Load content-line sets for consumer views present on disk."""
    views = {}
    for name in discover_consumer_views(views_dir):
        path = os.path.join(views_dir, name)
        if os.path.isfile(path):
            views[name] = load_view_content_lines(path)
    return views


def _pair_overlap_pct(lines_a, lines_b):
    """Overlap as a percentage of min(|A|, |B|)."""
    denom = min(len(lines_a), len(lines_b))
    if not denom:
        return 0.0, 0
    shared = len(lines_a & lines_b)
    return shared / denom * 100.0, shared


def compute_pairwise_overlap(views):
    """Pairwise max overlap ratio (%), sorted desc."""
    pairs = []
    for name_a, name_b in itertools.combinations(views.keys(), 2):
        pct, shared = _pair_overlap_pct(views[name_a], views[name_b])
        pairs.append((name_a, name_b, pct, shared))
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs


def _union_of_others(views, exclude_name):
    """Union of content lines from every view except exclude_name."""
    others = set()
    for name, lines in views.items():
        if name != exclude_name:
            others.update(lines)
    return others


def compute_uniqueness(views):
    """Fraction of each view's lines absent from every OTHER consumer view."""
    results = []
    for name, this_lines in views.items():
        if not this_lines:
            results.append((name, 0, 0, 0.0))
            continue
        others = _union_of_others(views, name)
        unique = this_lines - others
        pct = len(unique) / len(this_lines) * 100.0
        results.append((name, len(this_lines), len(unique), pct))
    return results


def _build_overlap_lookup(pairs):
    """Symmetric (name_a, name_b) -> pct dict for matrix lookups."""
    lookup = {}
    for a, b, pct, _ in pairs:
        lookup[(a, b)] = pct
        lookup[(b, a)] = pct
    return lookup


def _row_cell(row_name, col_name, lookup):
    """Render one matrix cell as a 10-char right-aligned string."""
    if row_name == col_name:
        return f"{'100.0':>10}"
    return f"{lookup.get((row_name, col_name), 0.0):>10.1f}"


def _print_matrix_row(name, names, short, lookup, col_w):
    """Print one row of the overlap matrix."""
    cells = [_row_cell(name, m, lookup) for m in names]
    print(f"{short[name]:<{col_w}}" + "".join(cells))


def print_overlap_matrix(views, pairs):
    """Print NxN pairwise-overlap matrix for operator readability."""
    names = list(views.keys())
    lookup = _build_overlap_lookup(pairs)
    short = {n: n.replace(".md", "") for n in names}
    col_w = max(14, max(len(s) for s in short.values()) + 2)
    print(" " * col_w + "".join(f"{short[n]:>10}" for n in names))
    for n in names:
        _print_matrix_row(n, names, short, lookup, col_w)


def _filter_reject_pairs(pairs, max_overlap):
    """Pairs strictly above the REJECT overlap threshold."""
    return [p for p in pairs if p[2] > max_overlap]


def _filter_warn_pairs(pairs, max_overlap):
    """Pairs in the WARN band (above WARN, at or below REJECT)."""
    out = []
    for p in pairs:
        if WARN_PAIRWISE_OVERLAP < p[2] <= max_overlap:
            out.append(p)
    return out


def _classify_overlap_findings(pairs, uniqueness, max_overlap, min_uniq):
    """Split pairs/uniqueness into reject and warn buckets."""
    reject_pairs = _filter_reject_pairs(pairs, max_overlap)
    warn_pairs = _filter_warn_pairs(pairs, max_overlap)
    reject_uniq = [u for u in uniqueness if u[3] < min_uniq]
    warn_uniq = [u for u in uniqueness if min_uniq <= u[3] < WARN_UNIQUENESS]
    return reject_pairs, warn_pairs, reject_uniq, warn_uniq


def _print_overlap_header(views):
    """Print the overlap-check section header with view line counts."""
    print("\n--- Overlap checks ---")
    print(f"Consumer views analyzed: {list(views.keys())}")
    counts = ", ".join(f"{n}={len(s)}" for n, s in views.items())
    print(f"Line counts: {counts}")
    print()
    print("Pairwise overlap matrix (shared / min(|A|, |B|) as %):")


def check_overlap(views_dir, max_pairwise_overlap, min_uniqueness):
    """Run overlap + uniqueness checks.

    Returns (had_reject_pairs, had_warn_pairs, had_reject_uniq, had_warn_uniq).
    R1.3 callers split overlap and uniqueness into two separate summary
    rows, so the four signals are returned independently rather than
    OR'd together.
    """
    views = load_consumer_views(views_dir)
    if len(views) < 2:
        print("\n--- Overlap checks ---")
        print(f"Skipped: need at least 2 consumer views (found {len(views)}).")
        return False, False, False, False
    return _run_overlap_pass(views, max_pairwise_overlap, min_uniqueness)


def _run_overlap_pass(views, max_pairwise_overlap, min_uniqueness):
    """Compute and report overlap+uniqueness on a non-empty `views` map."""
    pairs = compute_pairwise_overlap(views)
    uniqueness = compute_uniqueness(views)
    _print_overlap_header(views)
    print_overlap_matrix(views, pairs)
    buckets = _classify_overlap_findings(
        pairs, uniqueness, max_pairwise_overlap, min_uniqueness,
    )
    reject_pairs, warn_pairs, reject_uniq, warn_uniq = buckets
    _print_overlap_findings(
        buckets, max_pairwise_overlap, min_uniqueness, uniqueness,
    )
    return (
        bool(reject_pairs), bool(warn_pairs),
        bool(reject_uniq), bool(warn_uniq),
    )


def _uniqueness_tag(pct, min_uniq):
    """Return a REJECT/WARN/empty tag string for a uniqueness percentage."""
    if pct < min_uniq:
        return f"  REJECT < {min_uniq:.0f}%"
    if pct < WARN_UNIQUENESS:
        return f"  WARN < {WARN_UNIQUENESS:.0f}%"
    return ""


def _print_uniqueness_list(all_uniqueness, min_uniq):
    """Print per-view uniqueness percentages with REJECT/WARN tags."""
    print()
    print("Per-view uniqueness (lines unique to this view / total lines):")
    for name, total, unique, pct in all_uniqueness:
        short = name.replace(".md", "")
        tag = _uniqueness_tag(pct, min_uniq)
        print(f"  {short}: {pct:.1f}% unique ({unique}/{total}){tag}")


def _print_pair_list(pairs, label, threshold_pct):
    """Print a list of pairs with a REJECT/WARN label."""
    if not pairs:
        return
    print()
    print(f"Pairs exceeding {label} threshold {threshold_pct:.0f}%:")
    for a, b, pct, shared in pairs:
        sa, sb = a.replace(".md", ""), b.replace(".md", "")
        print(f"  {sa} vs {sb}: {pct:.1f}% ({shared} shared lines)  {label}")


def _print_overlap_findings(buckets, max_overlap, min_uniq, all_uniqueness):
    """Print human-readable findings + diagnosis if any rejects."""
    reject_pairs, warn_pairs, reject_uniq, _warn_uniq = buckets
    _print_uniqueness_list(all_uniqueness, min_uniq)
    _print_pair_list(reject_pairs, "REJECT", max_overlap)
    _print_pair_list(warn_pairs, "WARN", WARN_PAIRWISE_OVERLAP)
    if reject_pairs or reject_uniq:
        _print_diagnosis()


def _print_diagnosis():
    """Print the actionable diagnosis + fix recommendation block."""
    print()
    print("DIAGNOSIS: The spec agent's coverage fallback likely dumped")
    print("unrelated content into multiple views to force 100% coverage.")
    print("Each view should contain role-specific content only.")
    print()
    print("FIX: Re-run spec agent with clearer INCLUDE/SKIP criteria.")
    print("The coverage fallback should assign uncovered lines to ONE best-fit view,")
    print("not multiple views.")


# ---------------------------------------------------------------------------
# Fabrication detection (views -> monolith verbatim check)
# ---------------------------------------------------------------------------

# Structural whitelist: lines that may exist in a view without appearing
# verbatim in the monolith. Tightened to the strictest possible rule:
# ONLY section titles (##/###/####) and the minimal view-file header
# scaffolding may be non-verbatim. Every other line MUST be a byte-for-byte
# substring of the monolith. The spec agent may select, reorder, and
# combine monolith content — but may NOT paraphrase, summarize, or invent.
WHITELIST_PATTERNS = [
    re.compile(r"^<!--\s*AUTO-GENERATED\b.*-->\s*$"),  # view header HTML comment
    re.compile(r"^#\s+\S.*\s+view of\s+\S+\s*$"),       # "# <agent> view of <spec-id>"
    re.compile(r"^\*\*Monolith\*\*:\s+.+$"),             # monolith path reference
    re.compile(r"^\*\*Extraction\*\*:\s+.+$"),           # extraction description
    re.compile(r"^---\s*$"),                              # horizontal-rule separator
    re.compile(r"^#{2,4}\s+\S.*$"),                       # section titles (## / ### / ####)
    # R4a.2 / R4a.4: three-tier content markers. Spec R4a.1 (verbatim):
    #   EXPLICIT:  <!-- EXPLICIT source:L{N}-L{M} sha256:{hash} -->
    #   INFERRED:  <!-- INFERRED basis:L{N}-L{M} sha256:{hash} derivation:{type} -->
    #   AMBIGUOUS: <!-- AMBIGUOUS source:L{N}-L{M} candidates:["A","B",…] -->
    # derivation enum (induction / constraint_merge / role_mapping /
    # gap_identification / enumeration_closure) is enforced by T6, not here.
    re.compile(r"^<!--\s*EXPLICIT\s+source:L\d+-L\d+\s+sha256:[0-9a-f]+\s*-->\s*$"),
    re.compile(r"^<!--\s*INFERRED\s+basis:L\d+-L\d+\s+sha256:[0-9a-f]+\s+derivation:\w+\s*-->\s*$"),
    re.compile(r"^<!--\s*AMBIGUOUS\s+source:L\d+-L\d+\s+candidates:\[.*\]\s*-->\s*$"),
]


def _matches_whitelist(stripped):
    """True if the line matches any structural whitelist pattern."""
    return any(p.match(stripped) for p in WHITELIST_PATTERNS)


def _strip_quote_prefix(stripped):
    """Return the quoted content from a '> ...' line, or None if not a quote.

    Handles leading whitespace (indented quotes in nested lists) and the
    bare '>' sentinel used by GitHub-flavored Markdown for blank quote
    lines.
    """
    lstripped = stripped.lstrip()
    if lstripped.startswith("> "):
        return lstripped[2:].rstrip()
    if lstripped == ">":
        return ""
    return None


def _is_verbatim(stripped, monolith_text):
    """True if the stripped line is a byte-for-byte substring of monolith."""
    if not stripped:
        return True
    return stripped in monolith_text


def _view_body_lines(view_path):
    """Yield (line_num, stripped) for lines after the view's header."""
    with open(view_path, encoding="utf-8") as f:
        lines = f.readlines()
    header_end = _find_header_end(lines)
    start_idx = header_end + 1 if header_end >= 0 else 0
    for i, raw in enumerate(lines[start_idx:], start=start_idx + 1):
        stripped = raw.rstrip()
        if not stripped:
            continue
        yield i, stripped


def _is_acceptable(stripped, monolith_text):
    """True if the line is whitelisted, verbatim, or a verbatim quote."""
    if _matches_whitelist(stripped):
        return True
    if _is_verbatim(stripped, monolith_text):
        return True
    quoted = _strip_quote_prefix(stripped)
    if quoted is not None and (not quoted or _is_verbatim(quoted, monolith_text)):
        return True
    return False


def check_no_fabrication(monolith_text, view_path):
    """Return list of (line_num, preview) for fabricated content in view."""
    fabrications = []
    for line_num, stripped in _view_body_lines(view_path):
        if _is_acceptable(stripped, monolith_text):
            continue
        preview = stripped[:120] + ("..." if len(stripped) > 120 else "")
        fabrications.append((line_num, preview))
    return fabrications


def _print_fabrication_file(name, fabrications):
    """Print one file's fabrication findings."""
    print(f"\n{name}:")
    if not fabrications:
        print("  (none)")
        return
    for line_num, preview in fabrications:
        print(f"  Line {line_num}: {preview}")
        print("    <- not found verbatim in monolith")


def _print_fabrication_diagnosis():
    """Print the actionable diagnosis + fix recommendation."""
    print()
    print("DIAGNOSIS: Only section titles may be non-verbatim. All other")
    print("content must be byte-for-byte substring of monolith.")
    print()
    print("FIX: spec agent may freely select, reorder, and combine verbatim")
    print("content blocks from the monolith. It may NOT paraphrase, summarize,")
    print("or invent content. If a section cannot be constructed from verbatim")
    print("monolith content, OMIT the section rather than fabricate.")


def check_fabrication_all(monolith_text, views_dir):
    """Run fabrication check across all view files. Returns {name: [...]}"""
    results = {}
    for name in sorted(os.listdir(views_dir)):
        if not name.endswith(".md") or name in SKIP_FILES - {"orchestrator.md"}:
            continue
        results[name] = check_no_fabrication(
            monolith_text, os.path.join(views_dir, name),
        )
    return results


def report_fabrication(results):
    """Print fabrication results, return True if any fabrications found."""
    any_fab = any(fabs for fabs in results.values())
    print("\n--- Fabrication checks (views -> monolith verbatim) ---")
    if not any_fab:
        print("All view content lines are verbatim monolith substrings or "
              "whitelisted structural markers.")
        return False
    print("STRUCTURAL FAIL: Fabricated content detected in views")
    for name, fabrications in results.items():
        _print_fabrication_file(name, fabrications)
    _print_fabrication_diagnosis()
    return True


def _run_fabrication_check(args):
    """Run fabrication check if requested. Returns CheckResult (R1.3)."""
    if not (args.no_fabrication or args.strict):
        return CheckResult("fabrication", "N/A", "not requested", 0)
    with open(args.monolith, encoding="utf-8") as f:
        monolith_text = f.read()
    results = check_fabrication_all(monolith_text, args.views_dir)
    had_fab = report_fabrication(results)
    if not had_fab:
        return CheckResult("fabrication", "PASS", "", 0)
    if args.strict:
        print("\nFAIL: fabricated content found with --strict", file=sys.stderr)
        return CheckResult("fabrication", "FAIL", "non-verbatim lines", 1)
    print("\nWARNING: fabricated content found (run with --strict to fail).")
    return CheckResult("fabrication", "WARN", "non-strict", 0)


def _run_coverage_check(args):
    """Run coverage check; return CheckResult (R1.3)."""
    pct = run_coverage(args)
    if pct < args.min_coverage:
        print(f"\nFAIL: coverage {pct:.1f}% < {args.min_coverage:.1f}%", file=sys.stderr)
        detail = f"{pct:.1f}% < {args.min_coverage:.1f}%"
        return CheckResult("coverage", "FAIL", detail, 1)
    print(f"\nPASS: coverage {pct:.1f}% >= {args.min_coverage:.1f}%")
    return CheckResult("coverage", "PASS", f"{pct:.1f}%", 0)


def _run_structural_check(args):
    """Run structural check; return CheckResult (R1.3)."""
    structural_issues = check_structure(args.views_dir)
    print_structural_report(structural_issues)
    if not structural_issues:
        return CheckResult("structural", "PASS", "", 0)
    detail = f"{len(structural_issues)} issue(s)"
    if args.strict:
        print("\nFAIL: structural issues found with --strict", file=sys.stderr)
        return CheckResult("structural", "FAIL", detail, 1)
    return CheckResult("structural", "WARN", detail + " (non-strict)", 0)


def _run_overlap_check(args):
    """Run overlap+uniqueness check; return (overlap_result, uniqueness_result).

    R1.3 emits separate summary rows for overlap and uniqueness. The
    underlying check_overlap() already classifies pair vs uniqueness
    findings; here we surface them as two CheckResult records.
    """
    buckets = check_overlap(
        args.views_dir, args.max_pairwise_overlap, args.min_uniqueness,
    )
    had_reject_pairs, had_warn_pairs, had_reject_uniq, had_warn_uniq = buckets
    overlap_result = _overlap_result(
        had_reject_pairs, had_warn_pairs, args.strict,
    )
    uniqueness_result = _uniqueness_result(
        had_reject_uniq, had_warn_uniq, args.strict,
    )
    return overlap_result, uniqueness_result


def _overlap_result(had_reject, had_warn, strict):
    """Build the 'overlap' CheckResult and emit any --strict failure line."""
    if had_reject and strict:
        print("\nSTRUCTURAL FAIL: View overlap too high (--strict)", file=sys.stderr)
        return CheckResult("overlap", "FAIL", "pair > threshold", 1)
    if had_reject:
        print("\nWARNING: View overlap exceeds REJECT threshold "
              "(run with --strict to fail).")
        return CheckResult("overlap", "WARN", "REJECT band, non-strict", 0)
    if had_warn:
        print("\nNOTE: View overlap exceeds WARN threshold (non-fatal).")
        return CheckResult("overlap", "WARN", "WARN band", 0)
    return CheckResult("overlap", "PASS", "", 0)


def _uniqueness_result(had_reject, had_warn, strict):
    """Build the 'uniqueness' CheckResult mirroring overlap's strict gating."""
    if had_reject and strict:
        return CheckResult("uniqueness", "FAIL", "view < min-uniqueness", 1)
    if had_reject:
        return CheckResult("uniqueness", "WARN", "REJECT band, non-strict", 0)
    if had_warn:
        return CheckResult("uniqueness", "WARN", "WARN band", 0)
    return CheckResult("uniqueness", "PASS", "", 0)


def _run_gated_checks(args):
    """T5/T6: read monolith once; return (mandate, utility, ambiguous, meta_rule)."""
    with open(args.monolith, encoding="utf-8") as f:
        monolith_text = f.read()
    return (
        run_mandate_check(monolith_text, args.views_dir),
        run_utility_check(monolith_text, args.views_dir),
        run_ambiguous_check(monolith_text, args.views_dir),
        run_meta_rule_check(monolith_text, args.views_dir),
    )


def _gather_check_results(args):
    """Run every check and return ordered [CheckResult, ...] for the summary."""
    coverage = _run_coverage_check(args)
    structural = _run_structural_check(args)
    fabrication = _run_fabrication_check(args)
    overlap, uniqueness = _run_overlap_check(args)
    mandate, utility, ambiguous, meta_rule = _run_gated_checks(args)
    return [
        coverage, structural, fabrication, overlap, uniqueness,
        mandate, utility, ambiguous, meta_rule,
    ]


def main():
    """Run all checks, emit R1.3 per-check-type summary, exit at end.

    Reordered per R1.4: overlap runs BEFORE the final exit, so a broken
    fixture shows BOTH coverage and overlap findings. R1.3: a uniform
    `=== Verification Summary ===` block prints at the end with one
    row per check type. T5/T6 mandate/utility/ambiguous/meta_rule rows
    return N/A on legacy monoliths and run real checks under guide_version >= 1.
    """
    args = parse_args()
    validate_inputs(args)
    results = _gather_check_results(args)
    exit_code = max(r.exit_code for r in results)
    print_summary(results, exit_code)
    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
