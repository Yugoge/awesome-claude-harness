"""R1.1 / R4a.3 / R5.x gated checks for spec-verify.py.

Three sibling checks that share the T5 ``is_strict_guide_mode`` gate and
all activate only when the monolith declares ``guide_version: 1`` (or
higher) in YAML front-matter:

    R1.1  utility / self-sufficiency check
          (qa.md / pm.md / ba.md / dev.md must be role-consumable)
    R4a.3 AMBIGUOUS gate
          (any unresolved ``<!-- AMBIGUOUS ... -->`` marker blocks the run)
    R5.1-R5.3 meta-rule detection + compliance summary
          (per the R6.3 ``## Meta-Rules`` section grammar)

Lives in a sibling sidecar (alongside ``spec_verify_parsers.py``,
``spec_verify_summary.py``, ``spec_verify_mandate.py``) because the
parent module is at the 800-line quality-gate ceiling.

Public API:
    run_utility_check(monolith_text, views_dir) -> CheckResult
    run_ambiguous_check(monolith_text, views_dir) -> CheckResult
    run_meta_rule_check(monolith_text, views_dir) -> CheckResult

Annotation-only by design (R3.3 round-3 Option 1 lineage):
Heuristic-A (agent-name token search inside basis ranges) is
structurally absent from this module -- the utility check uses
heading-based heuristics ONLY at the view level, never at the
monolith basis-range level.
"""

import os
import re

from spec_verify_mandate import is_strict_guide_mode
from spec_verify_parsers import parse_front_matter
from spec_verify_summary import CheckResult


# Files that are never required-consumer views.
_VIEW_SKIP_FILES = {
    "orchestrator.md", "manifest.json", "INDEX.md",
    "README.md", "checkpoints.json",
}

# Required consumer views per R1.1 with hard FAIL semantics.
_REQUIRED_VIEWS = ("qa.md", "pm.md", "ba.md", "dev.md")

# AMBIGUOUS marker grammar -- mirrors the WHITELIST_PATTERNS regex in
# spec-verify.py + spec_verify_mandate.py. Re-defining locally avoids
# importing private constants across sidecars.
_AMBIGUOUS_LINE_RE = re.compile(
    r"<!--\s*AMBIGUOUS\s+source:L(?P<start>\d+)-L(?P<end>\d+)\s+"
    r"candidates:(?P<cands>\[[^\]]*\])\s*-->"
)

# Meta-rule grammar per R6.3 / R5.1: bullets of the form
#   - **R{id}**: <description>
# inside a ``## Meta-Rules`` section.
_META_HEADING_RE = re.compile(r"^\s*##\s+Meta-Rules\s*$", re.IGNORECASE)
_META_BULLET_RE = re.compile(
    r"^\s*[-*]\s+\*\*(?P<id>[A-Z]\d+(?:\.\d+)?)\*\*\s*[:\-]\s*"
    r"(?P<desc>.+?)\s*$"
)
_NEXT_H2_RE = re.compile(r"^\s*##\s+\S")
_HEADING_LINE_RE = re.compile(r"^\s*#{1,6}\s+\S")

# R5.2 recognized operators. Detection is substring-based so authors
# can phrase rules in prose ("views should cite by line-range, not
# inline-paste") and still get matched.
_RECOGNIZED_OPERATORS = {
    "cite-by-range": ("cite by", "line-range", "line range"),
    "no-paraphrase": ("no paraphrase", "no-paraphrase", "do not paraphrase"),
    "verbatim-only": ("verbatim only", "verbatim-only", "must be verbatim"),
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _read_text(path):
    """Read a file as utf-8 text; '' if missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _list_view_files(views_dir):
    """Sorted .md view filenames eligible for these checks."""
    if not os.path.isdir(views_dir):
        return []
    out = []
    for name in sorted(os.listdir(views_dir)):
        if not name.endswith(".md"):
            continue
        if name in _VIEW_SKIP_FILES:
            continue
        out.append(name)
    return out


def _has_heading(view_text, heading_options):
    """True if any ``## <option>`` heading appears (case-insensitive)."""
    lowered = view_text.lower()
    for option in heading_options:
        if option.lower() in lowered:
            return True
    return False


def _line_matches_section(stripped, lowered_opts):
    """True if a stripped line is an H2 heading matching one option."""
    if not stripped.startswith("##"):
        return False
    return any(opt in stripped for opt in lowered_opts)


def _find_section_start(lines, heading_options):
    """Return the 0-indexed line of the first matching H2, or None."""
    lowered_opts = [o.lower() for o in heading_options]
    for i, raw in enumerate(lines):
        stripped = raw.strip().lower()
        if _line_matches_section(stripped, lowered_opts):
            return i
    return None


def _section_body(view_text, heading_options):
    """Return the body text under the first matching ## heading.

    Empty string when no heading matches. The body runs from the line
    AFTER the matching heading down to (but excluding) the next H2.
    """
    lines = view_text.splitlines()
    start = _find_section_start(lines, heading_options)
    if start is None:
        return ""
    end = _find_next_h2(lines, start + 1)
    return "\n".join(lines[start + 1:end])


def _find_next_h2(lines, from_idx):
    """Return 0-indexed line of next ## heading at or after from_idx."""
    for j in range(from_idx, len(lines)):
        if _NEXT_H2_RE.match(lines[j]):
            return j
    return len(lines)


def _has_bullet(body):
    """True if body contains at least one list bullet."""
    for raw in body.splitlines():
        stripped = raw.strip()
        if stripped.startswith(("- ", "* ", "1. ", "2. ", "3. ")):
            return True
    return False


# ---------------------------------------------------------------------------
# R1.1 utility / self-sufficiency check
# ---------------------------------------------------------------------------


def _check_qa_view(view_text):
    """Verify qa.md has an Acceptance-Criteria block with at least one bullet."""
    options = ("acceptance criteria", "## ac", "### ac", "验收")
    if not _has_heading(view_text, options):
        return False, "qa.md lacks acceptance-criteria block"
    body = _section_body(view_text, options)
    if not _has_bullet(body):
        return False, "qa.md acceptance-criteria block has no list items"
    return True, ""


def _has_priority_tags(view_text):
    """True if the view carries P{N}-{n} ids OR Priority:/Tier: tags."""
    if re.search(r"\bP\d+-\d+\b", view_text):
        return True
    if re.search(r"(?:Priority|Tier)\s*:", view_text, re.IGNORECASE):
        return True
    return False


def _check_pm_view(view_text):
    """Verify pm.md has a priority-tagged item list."""
    options = ("priorities", "优先级")
    has_section = _has_heading(view_text, options)
    has_priority_tags = _has_priority_tags(view_text)
    if not has_section and not has_priority_tags:
        return False, "pm.md lacks Priorities section AND P-id / Priority: tags"
    return True, ""


def _check_ba_view(view_text):
    """Verify ba.md has an atomic-requirement decomposition."""
    options = ("requirement decomposition", "需求拆解", "atomic task")
    has_section = _has_heading(view_text, options)
    has_ids = bool(re.search(r"###\s+(?:T|R)\d+(?:\.\d+)?\b", view_text))
    if not has_section and not has_ids:
        return False, (
            "ba.md lacks Requirement Decomposition section AND "
            "T{n}/R{n} atomic-requirement headings"
        )
    return True, ""


def _committed_ids(monolith_text):
    """Return committed_requirement_ids from front-matter, with fallback.

    Falls back to scraping ``P\\d+-\\d+`` ids from monolith body when
    the front-matter list is absent. Empty list disables the dev.md
    coverage rule (R1.1: "every committed ID...if any").
    """
    fm = parse_front_matter(monolith_text or "")
    declared = fm.get("committed_requirement_ids")
    if isinstance(declared, list) and declared:
        return [str(x) for x in declared]
    return sorted(set(re.findall(r"\bP\d+(?:\.\d+)?-\d+\b", monolith_text or "")))


def _missing_ids(view_text, committed):
    """Return committed ids absent from a view's text."""
    return [rid for rid in committed if rid not in view_text]


def _check_dev_view(view_text, monolith_text):
    """Verify dev.md covers every committed requirement id from monolith."""
    options = ("tasks", "任务")
    if not _has_heading(view_text, options):
        return False, "dev.md lacks Tasks section"
    committed = _committed_ids(monolith_text)
    if not committed:
        return True, ""
    missing = _missing_ids(view_text, committed)
    if missing:
        sample = ", ".join(missing[:5])
        more = "" if len(missing) <= 5 else f", +{len(missing) - 5} more"
        return False, f"dev.md missing committed ids: {sample}{more}"
    return True, ""


_REQUIRED_CHECKERS = {
    "qa.md": ("qa", lambda v, _m: _check_qa_view(v)),
    "pm.md": ("pm", lambda v, _m: _check_pm_view(v)),
    "ba.md": ("ba", lambda v, _m: _check_ba_view(v)),
    "dev.md": ("dev", lambda v, m: _check_dev_view(v, m)),
}


def _check_required_view(view_name, views_dir, monolith_text):
    """Run the per-agent utility checker on one required view."""
    path = os.path.join(views_dir, view_name)
    if not os.path.isfile(path):
        return "fail", f"required view {view_name} is missing from views_dir"
    text = _read_text(path)
    _, checker = _REQUIRED_CHECKERS[view_name]
    ok, msg = checker(text, monolith_text)
    if ok:
        return "pass", ""
    return "fail", msg


def _check_optional_view(name, views_dir, required_consumers):
    """WARN for non-required views; FAIL only when in required_consumers."""
    if name not in required_consumers:
        return "warn", f"{name}: optional view -- utility not enforced"
    text = _read_text(os.path.join(views_dir, name))
    if not text.strip():
        return "fail", f"required consumer {name} is empty"
    return "pass", ""


def _utility_required_iter(views_dir, monolith_text):
    """Yield (status, msg) tuples for the four hard-required views."""
    for view_name in _REQUIRED_VIEWS:
        yield _check_required_view(view_name, views_dir, monolith_text)


def _utility_optional_iter(views_dir, required_consumers):
    """Yield (status, msg) tuples for non-required views in views_dir."""
    for name in _list_view_files(views_dir):
        if name in _REQUIRED_VIEWS:
            continue
        yield _check_optional_view(name, views_dir, required_consumers)


def _required_consumers(monolith_text):
    """Return required_consumers list from front-matter (lowercased)."""
    fm = parse_front_matter(monolith_text or "")
    declared = fm.get("required_consumers")
    if isinstance(declared, list):
        return {str(x).strip().lower() for x in declared}
    return set()


def _utility_results(monolith_text, views_dir):
    """Aggregate fail/warn lists from required + optional view checks."""
    failures = []
    warnings = []
    for status, msg in _utility_required_iter(views_dir, monolith_text):
        if status == "fail":
            failures.append(msg)
    required_consumers = _required_consumers(monolith_text)
    for status, msg in _utility_optional_iter(views_dir, required_consumers):
        if status == "fail":
            failures.append(msg)
        elif status == "warn":
            warnings.append(msg)
    return failures, warnings


def _print_utility(failures, warnings):
    """Print the human-readable utility check section."""
    print("\n--- Utility checks (R1.1) ---")
    if not failures and not warnings:
        print("All required views satisfy role-consumability rules.")
        return
    if failures:
        print(f"FAIL: {len(failures)} utility violation(s):")
        for msg in failures:
            print(f"  {msg}")
    if warnings:
        print(f"WARN: {len(warnings)} optional-view note(s):")
        for msg in warnings:
            print(f"  {msg}")


def run_utility_check(monolith_text, views_dir):
    """R1.1 utility / self-sufficiency check. Returns CheckResult.

    Legacy monoliths return ``N/A (guide_version < 1)``. Strict-guide
    monoliths run per-agent role-consumability checks on qa.md / pm.md /
    ba.md / dev.md (FAIL on miss) and WARN-only on other consumer views.
    """
    if not is_strict_guide_mode(monolith_text):
        return CheckResult("utility", "N/A", "guide_version < 1", 0)
    failures, warnings = _utility_results(monolith_text, views_dir)
    _print_utility(failures, warnings)
    if failures:
        return CheckResult("utility", "FAIL", f"{len(failures)} violation(s)", 1)
    if warnings:
        return CheckResult("utility", "WARN", f"{len(warnings)} note(s)", 0)
    return CheckResult("utility", "PASS", "", 0)


# ---------------------------------------------------------------------------
# R4a.3 AMBIGUOUS gate
# ---------------------------------------------------------------------------


def _scan_view_for_ambiguous(view_text):
    """Yield (line_num, candidates) tuples for AMBIGUOUS markers in a view."""
    for line_num, raw in enumerate(view_text.splitlines(), 1):
        match = _AMBIGUOUS_LINE_RE.search(raw)
        if match:
            yield line_num, match.group("cands")


def _collect_ambiguous(views_dir):
    """Walk every consumer view and gather AMBIGUOUS marker locations."""
    findings = []
    for name in _list_view_files(views_dir):
        text = _read_text(os.path.join(views_dir, name))
        for line_num, cands in _scan_view_for_ambiguous(text):
            findings.append((name, line_num, cands))
    return findings


def _print_ambiguous(findings):
    """Print the ambiguous gate section."""
    print("\n--- AMBIGUOUS gate (R4a.3) ---")
    if not findings:
        print("No unresolved AMBIGUOUS markers found.")
        return
    print(f"FAIL: {len(findings)} AMBIGUOUS marker(s) require user resolution:")
    for name, line_num, cands in findings:
        print(f"  {name}:L{line_num} candidates={cands}")


def run_ambiguous_check(monolith_text, views_dir):
    """R4a.3 AMBIGUOUS gate. Returns CheckResult.

    Any unresolved ``<!-- AMBIGUOUS ... -->`` marker in any view file
    blocks the run -- the operator (or upstream /spec subagent) must
    resolve the candidate set or escalate to the user. No auto-resolve.
    """
    if not is_strict_guide_mode(monolith_text):
        return CheckResult("ambiguous", "N/A", "guide_version < 1", 0)
    findings = _collect_ambiguous(views_dir)
    _print_ambiguous(findings)
    if findings:
        return CheckResult("ambiguous", "FAIL", f"{len(findings)} marker(s)", 1)
    return CheckResult("ambiguous", "PASS", "", 0)


# ---------------------------------------------------------------------------
# R5.1-R5.3 meta-rule detection + compliance
# ---------------------------------------------------------------------------


def _find_meta_rules_section(monolith_text):
    """Return body lines under ``## Meta-Rules``, or [] when absent."""
    lines = (monolith_text or "").splitlines()
    start = None
    for i, raw in enumerate(lines):
        if _META_HEADING_RE.match(raw):
            start = i
            break
    if start is None:
        return []
    end = _find_next_h2(lines, start + 1)
    return lines[start + 1:end]


def _parse_meta_rule_bullet(raw):
    """Return (rule_id, description) for a recognized bullet, or (None, None)."""
    match = _META_BULLET_RE.match(raw)
    if match:
        return match.group("id"), match.group("desc")
    return None, None


def _classify_meta_rule(description):
    """Determine the operator + machine-readability of a meta-rule."""
    desc_lower = description.lower()
    for op_name, needles in _RECOGNIZED_OPERATORS.items():
        if any(needle in desc_lower for needle in needles):
            return op_name, True
    return "unrecognized", False


def _build_meta_rule_record(rule_id, description):
    """Build one parsed meta-rule record."""
    operator, machine_readable = _classify_meta_rule(description)
    return {
        "id": rule_id,
        "description": description,
        "operator": operator,
        "machine_readable": machine_readable,
    }


def _parse_meta_rules(monolith_text):
    """Return list of meta-rule records found in the ## Meta-Rules section."""
    body = _find_meta_rules_section(monolith_text)
    records = []
    for raw in body:
        rule_id, desc = _parse_meta_rule_bullet(raw)
        if rule_id is not None:
            records.append(_build_meta_rule_record(rule_id, desc))
    return records


def _meta_rule_compliance(record):
    """Return a one-line compliance summary for one meta-rule."""
    if not record["machine_readable"]:
        return "WARN: non-machine-readable, manual review"
    if record["operator"] == "cite-by-range":
        return "handled by overlap<30% (R1.4)"
    if record["operator"] in ("no-paraphrase", "verbatim-only"):
        return "handled by fabrication check (R4a.4)"
    return "no automated handler"


def _print_meta_rule(records):
    """Print the meta-rule compliance section."""
    print("\n--- Meta-Rule Compliance (R5.1-R5.3) ---")
    if not records:
        print("No ## Meta-Rules section found in monolith.")
        return
    for rec in records:
        print(f"  {rec['id']}: {rec['description'][:60]}")
        print(f"    operator={rec['operator']} -> {_meta_rule_compliance(rec)}")


def _meta_rule_status(records):
    """Compute the overall meta-rule CheckResult from parsed records."""
    if not records:
        return CheckResult("meta_rule", "PASS", "no meta-rules declared", 0)
    has_warn = any(not r["machine_readable"] for r in records)
    if has_warn:
        warn_count = sum(1 for r in records if not r["machine_readable"])
        return CheckResult(
            "meta_rule", "WARN",
            f"{warn_count} non-machine-readable rule(s)", 0,
        )
    return CheckResult("meta_rule", "PASS", f"{len(records)} rule(s)", 0)


def run_meta_rule_check(monolith_text, views_dir):
    """R5.1-R5.3 meta-rule detection + compliance summary. Returns CheckResult.

    Pure reporter: detects ``## Meta-Rules`` bullets matching the R6.3
    grammar and emits a compliance summary. Returns PASS when no rules
    declared OR all detected rules map to a known automated handler;
    WARN when one or more rules are non-machine-readable (manual review
    needed). Never FAILs -- non-fatal reporting per the prompt.
    """
    if not is_strict_guide_mode(monolith_text):
        return CheckResult("meta_rule", "N/A", "guide_version < 1", 0)
    records = _parse_meta_rules(monolith_text)
    _print_meta_rule(records)
    return _meta_rule_status(records)
