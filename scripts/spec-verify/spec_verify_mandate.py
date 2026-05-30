"""R3.0 / R3.3 / R3.6 / R3.7 mandate check for spec-verify.py.

Activated only when the monolith declares ``guide_version: 1`` (or higher)
in YAML front-matter. On legacy monoliths, ``run_mandate_check`` returns
the ``N/A (guide_version < 1)`` result and performs no semantic work,
preserving the no-brick invariant in spec Sec 1.4.

Lives in a sibling sidecar (alongside ``spec_verify_parsers.py`` and
``spec_verify_summary.py``) because the parent module is at the
800-line quality-gate ceiling.

Public API:
    is_strict_guide_mode(monolith_text) -> bool
    run_mandate_check(monolith_text, views_dir) -> CheckResult

Annotation-only role-evidence (R3.3 round-3 Option 1): role evidence
derives SOLELY from ``## Role: {agent}`` headings or ``consumers:``
annotations in the monolith body, looked up via
``spec_verify_parsers.lookup_role_block``. Heuristic-A (agent-name
token search inside the basis byte-range) is structurally absent from
this module.
"""

import itertools
import json
import os
import re

from spec_verify_parsers import (
    lookup_role_block,
    parse_consumers_tags,
    parse_front_matter,
    parse_role_headings,
)
from spec_verify_summary import CheckResult, validate_layer_1


# Files that do not carry a per-agent Role Mandate section. Mirrors the
# parent module's SKIP_FILES set; orchestrator.md is also excluded
# because its mandate is structurally different (Pipeline Workflow).
_MANDATE_SKIP_FILES = {
    "orchestrator.md", "manifest.json", "INDEX.md",
    "README.md", "checkpoints.json",
}


_INFERRED_MARKER_RE = re.compile(
    r"^<!--\s*INFERRED\s+basis:L(?P<start>\d+)-L(?P<end>\d+)\s+"
    r"sha256:(?P<sha>[0-9a-f]+)\s+derivation:(?P<deriv>\w+)\s*-->\s*$"
)
_AMBIGUOUS_MARKER_RE = re.compile(
    r"^<!--\s*AMBIGUOUS\s+source:L(?P<start>\d+)-L(?P<end>\d+)\s+"
    r"candidates:(?P<cands>\[[^\]]*\])\s*-->\s*$"
)
_ROLE_MANDATE_HEADING_RE = re.compile(
    r"^\s*##\s+role\s+mandate\s*$", re.IGNORECASE,
)
_NEXT_H2_RE = re.compile(r"^\s*##\s+\S")


def is_strict_guide_mode(monolith_text):
    """Return True iff the monolith declares ``guide_version: 1`` or higher.

    R3.0 activation gate. Also reused by T6's utility / ambiguous /
    meta-rule checks so they share the same gate semantics.
    """
    fm = parse_front_matter(monolith_text or "")
    gv = fm.get("guide_version")
    if not isinstance(gv, int):
        return False
    return gv >= 1


def _agent_from_filename(name):
    """Derive canonical agent name from view filename (strip '.md')."""
    if name.endswith(".md"):
        return name[:-3].lower()
    return name.lower()


def _read_text(path):
    """Read a file as utf-8 text; '' if missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _list_consumer_views(views_dir):
    """Sorted .md view filenames eligible for mandate validation."""
    if not os.path.isdir(views_dir):
        return []
    out = []
    for name in sorted(os.listdir(views_dir)):
        if not name.endswith(".md"):
            continue
        if name in _MANDATE_SKIP_FILES:
            continue
        out.append(name)
    return out


def _find_role_mandate_block(view_text):
    """Locate the ``## Role Mandate`` section in a view.

    Returns (header_idx, body_lines) where ``body_lines`` is the list of
    raw lines between the header and the next ``##`` sibling (exclusive).
    Returns (None, None) if no Role Mandate section exists.
    """
    lines = view_text.splitlines()
    header_idx = None
    for i, raw in enumerate(lines):
        if _ROLE_MANDATE_HEADING_RE.match(raw):
            header_idx = i
            break
    if header_idx is None:
        return None, None
    body = []
    for j in range(header_idx + 1, len(lines)):
        if _NEXT_H2_RE.match(lines[j]):
            break
        body.append(lines[j])
    return header_idx, body


def _strip_blank(body_lines):
    """Drop leading/trailing blank lines from a body slice."""
    start = 0
    end = len(body_lines)
    while start < end and not body_lines[start].strip():
        start += 1
    while end > start and not body_lines[end - 1].strip():
        end -= 1
    return body_lines[start:end]


def _classify_marker(stripped):
    """Match ``stripped`` against INFERRED / AMBIGUOUS marker grammars."""
    inferred = _INFERRED_MARKER_RE.match(stripped)
    if inferred:
        return "inferred", inferred
    ambiguous = _AMBIGUOUS_MARKER_RE.match(stripped)
    if ambiguous:
        return "ambiguous", ambiguous
    return None, None


def _first_marker_in_body(body_lines):
    """Return (kind, match) for the first marker, or (None, None) if absent."""
    for raw in body_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        kind, match = _classify_marker(stripped)
        if kind is not None:
            return kind, match
        # First non-blank, non-marker content -> no leading marker.
        return None, None
    return None, None


def _basis_inside_block(basis_start, basis_end, block):
    """True if [basis_start..basis_end] sits inside the role block."""
    return block["line_start"] <= basis_start and basis_end <= block["line_end"]


def _bad_derivation_msg(view_name, deriv):
    """R3.7 derivation enum check failure message."""
    return (
        f"view {view_name}: Role Mandate INFERRED marker has "
        f"derivation:{deriv} (expected role_mapping)"
    )


def _no_evidence_msg(view_name, agent):
    """R3.3 missing-annotation failure message."""
    return (
        f"view {view_name}: no annotation in monolith provides "
        f"role-evidence for agent {agent}. Add `## Role: {agent}` "
        f"heading or `<!-- consumers: [{agent}] -->` tag."
    )


def _basis_outside_msg(view_name, agent, basis_start, basis_end, block):
    """R3.3 basis-not-contained failure message."""
    return (
        f"view {view_name}: basis L{basis_start}-L{basis_end} is "
        f"not contained within role block for agent {agent} "
        f"(block at L{block['line_start']}-L{block['line_end']})"
    )


def _check_role_evidence(view_name, agent, basis_start, basis_end, monolith_text, ctx):
    """R3.3 annotation-based role-evidence check. Returns (status, msg)."""
    block = lookup_role_block(
        monolith_text, agent,
        role_headings=ctx["role_headings"],
        consumers_tags=ctx["consumers_tags"],
    )
    if block is None:
        return "fail", _no_evidence_msg(view_name, agent)
    if not _basis_inside_block(basis_start, basis_end, block):
        return "fail", _basis_outside_msg(
            view_name, agent, basis_start, basis_end, block,
        )
    return "pass", ""


def _check_inferred_marker(view_name, agent, match, monolith_text, ctx):
    """Validate one INFERRED marker. Returns (status, message)."""
    deriv = match.group("deriv")
    if deriv != "role_mapping":
        return "fail", _bad_derivation_msg(view_name, deriv)
    basis_start = int(match.group("start"))
    basis_end = int(match.group("end"))
    expected_sha = match.group("sha")
    ok, diag = validate_layer_1(
        monolith_text, basis_start, basis_end, expected_sha,
    )
    if not ok:
        return "fail", f"view {view_name}: Layer-1 basis check failed -- {diag}"
    return _check_role_evidence(
        view_name, agent, basis_start, basis_end, monolith_text, ctx,
    )


def _ambiguous_failure(view_name, match):
    """Build the R3.5 AMBIGUOUS escalation failure message."""
    cands = match.group("cands")
    return (
        f"view {view_name}: Role Mandate escalated to AMBIGUOUS -- "
        f"user decision required: {cands}"
    )


def _missing_marker_msg(view_name):
    """R3.7 marker-wrapping failure message."""
    return (
        f"view {view_name}: Role Mandate has no INFERRED marker "
        f"(R3.7: section must be wrapped in derivation:role_mapping marker)"
    )


def _signature_for(body_lines):
    """Whitespace-normalized body signature used by R3.6 byte-equality."""
    return "\n".join(line.rstrip() for line in body_lines)


def _validate_view_mandate(view_name, view_text, monolith_text, ctx):
    """Validate one view's Role Mandate. Returns (outcome, message, sig).

    outcome is 'pass' / 'fail' / 'omit'; ``sig`` is the body signature
    (empty string when the section is absent or empty).
    """
    _, body = _find_role_mandate_block(view_text)
    if body is None:
        return "omit", "no Role Mandate section in view", ""
    trimmed = _strip_blank(body)
    if not trimmed:
        return "omit", "Role Mandate section is empty in view", ""
    body_sig = _signature_for(trimmed)
    kind, match = _first_marker_in_body(trimmed)
    if kind is None:
        return "fail", _missing_marker_msg(view_name), body_sig
    if kind == "ambiguous":
        return "fail", _ambiguous_failure(view_name, match), body_sig
    agent = _agent_from_filename(view_name)
    status, msg = _check_inferred_marker(
        view_name, agent, match, monolith_text, ctx,
    )
    return status, msg, body_sig


def _byte_equal_pair_msg(name_a, name_b):
    """R3.6 byte-equality failure message."""
    return (
        f"views {name_a} and {name_b} have byte-equal Role Mandate sections"
    )


def _byte_equal_pair_issue(pair):
    """Return a failure message if a (view_a, view_b) pair has equal sigs."""
    (name_a, sig_a), (name_b, sig_b) = pair
    if sig_a == sig_b:
        return _byte_equal_pair_msg(name_a, name_b)
    return None


def _check_byte_equality(signatures):
    """R3.6 cross-contamination: pairwise byte-equal Role Mandate sections."""
    items = sorted((n, s) for n, s in signatures.items() if s)
    issues = []
    for pair in itertools.combinations(items, 2):
        issue = _byte_equal_pair_issue(pair)
        if issue is not None:
            issues.append(issue)
    return issues


def _load_omissions_doc(path):
    """Read the existing omissions JSON, or return a fresh skeleton."""
    if not os.path.isfile(path):
        return {"omissions": []}
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"omissions": []}
    doc.setdefault("omissions", [])
    return doc


def _write_omissions_doc(path, doc):
    """Persist the omissions doc; swallow OS errors silently."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError:
        pass


def _record_omission(views_dir, view_name, agent, reason):
    """Append an entry to ``views/mandate-omissions.json`` (R3.4)."""
    path = os.path.join(views_dir, "mandate-omissions.json")
    doc = _load_omissions_doc(path)
    if any(o.get("view") == view_name for o in doc["omissions"]):
        return
    doc["omissions"].append({
        "view": view_name,
        "agent": agent,
        "reason": reason,
    })
    _write_omissions_doc(path, doc)


def _build_parser_context(monolith_text):
    """Precompute role-heading / consumers-tag records once per run."""
    return {
        "role_headings": parse_role_headings(monolith_text),
        "consumers_tags": parse_consumers_tags(monolith_text),
    }


def _validate_all_views(views_dir, monolith_text, ctx):
    """Run mandate validation across every consumer view in views_dir."""
    failures = []
    omissions = []
    signatures = {}
    for view_name in _list_consumer_views(views_dir):
        view_text = _read_text(os.path.join(views_dir, view_name))
        outcome, msg, sig = _validate_view_mandate(
            view_name, view_text, monolith_text, ctx,
        )
        if sig:
            signatures[view_name] = sig
        if outcome == "fail":
            failures.append(msg)
        elif outcome == "omit":
            omissions.append((view_name, msg))
    return failures, omissions, signatures


def _emit_omissions(views_dir, omissions):
    """Persist R3.4 OMIT entries; safe to call with an empty list."""
    if not omissions:
        return
    for view_name, msg in omissions:
        agent = _agent_from_filename(view_name)
        _record_omission(views_dir, view_name, agent, msg)


def _print_failures(failures):
    """Print mandate violation lines, if any."""
    if not failures:
        return
    print(f"FAIL: {len(failures)} mandate violation(s):")
    for msg in failures:
        print(f"  {msg}")


def _print_omissions(omissions):
    """Print mandate OMIT lines, if any."""
    if not omissions:
        return
    print(f"OMIT: {len(omissions)} view(s) skipped Role Mandate "
          f"(recorded in mandate-omissions.json):")
    for view_name, msg in omissions:
        print(f"  {view_name}: {msg}")


def _print_findings(failures, omissions):
    """Human-readable diagnostic block for the operator."""
    print("\n--- Mandate checks (R3.0/R3.3/R3.6/R3.7) ---")
    if not failures and not omissions:
        print("All Role Mandate sections pass annotation-based role-evidence.")
        return
    _print_failures(failures)
    _print_omissions(omissions)


def run_mandate_check(monolith_text, views_dir):
    """R3.0/R3.3/R3.6/R3.7 entry point. Returns a ``CheckResult``.

    Legacy monoliths (no ``guide_version: 1`` front-matter) yield the
    ``N/A`` result without performing any semantic work. Strict-guide
    monoliths run the full annotation-based role-evidence + cross-
    contamination + content-rule checks. Annotation-only by design --
    Heuristic-A is structurally absent.
    """
    if not is_strict_guide_mode(monolith_text):
        return CheckResult("mandate", "N/A", "guide_version < 1", 0)
    ctx = _build_parser_context(monolith_text)
    failures, omissions, signatures = _validate_all_views(
        views_dir, monolith_text, ctx,
    )
    failures.extend(_check_byte_equality(signatures))
    _emit_omissions(views_dir, omissions)
    _print_findings(failures, omissions)
    if failures:
        detail = f"{len(failures)} violation(s)"
        return CheckResult("mandate", "FAIL", detail, 1)
    return CheckResult("mandate", "PASS", "", 0)
