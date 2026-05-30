"""Per-check-type summary + R4a.4 Layer-1 sha256 helper for spec-verify.py.

Lives alongside `spec_verify_parsers.py` as a sibling sidecar because
`spec-verify.py` + inlined infrastructure exceeds the 800-line
quality-gate ceiling enforced by `pretool-quality-gate.py`.

Public API (re-exported by spec-verify.py):
    CheckResult            - namedtuple(name, status, detail, exit_code)
    validate_layer_1       - R4a.4 sha256 validator (T5 will call this)
    format_summary_row     - render one "  name: STATUS (detail)" row
    print_summary          - emit the R1.3 verification summary block
    stub_mandate_result    - placeholder while T5 wires R3.0/R3.3
    stub_utility_result    - placeholder while T6 wires R1.1
    stub_meta_rule_result  - placeholder while T6 wires R5.3
    stub_ambiguous_result  - placeholder while T6 wires R4a.3
"""

import hashlib
from collections import namedtuple


# R1.3: uniform check record. Consumed by main() in spec-verify.py.
# `name`      - lowercase label printed in the summary
#               (coverage / structural / fabrication / overlap /
#                uniqueness / mandate / utility / ambiguous / meta_rule).
# `status`    - PASS | FAIL | WARN | N/A.
# `detail`    - short parenthesized context string; may be empty.
# `exit_code` - 0 for PASS/WARN/N/A, 1 for FAIL; accumulated by main().
CheckResult = namedtuple("CheckResult", ["name", "status", "detail", "exit_code"])


def _normalize_range_text(monolith_text, line_start, line_end):
    """Extract and normalize the lines[line_start-1:line_end] slice.

    Normalization matches the existing fabrication check convention in
    spec-verify.py (raw.rstrip() per line, blank lines preserved):
      1. Strip trailing whitespace from each line.
      2. Join with newlines.

    Returns None on out-of-bounds ranges.
    """
    lines = monolith_text.splitlines()
    if line_start < 1 or line_end > len(lines) or line_start > line_end:
        return None
    chunk = [ln.rstrip() for ln in lines[line_start - 1:line_end]]
    return "\n".join(chunk)


def _bounds_diagnostic(line_start, line_end, total):
    """Return (ok, diag) for the Layer-1 bounds preconditions."""
    if line_start > line_end:
        msg = f"invalid_range: line_start L{line_start} > line_end L{line_end}"
        return False, msg
    if line_start < 1 or line_end > total:
        msg = f"out_of_bounds: range L{line_start}-L{line_end} exceeds monolith length {total}"
        return False, msg
    return True, ""


def validate_layer_1(monolith_text, basis_line_start, basis_line_end, expected_sha256):
    """R4a.4 Layer-1 hash validator.

    Returns (True, "") if sha256 of the normalized basis range matches
    `expected_sha256`. Returns (False, diagnostic) otherwise; diagnostic
    prefixes are 'invalid_range:', 'out_of_bounds:', 'hash_mismatch:'.
    T5 (R3.3 mandate check) will be the consumer.

    Whitespace normalization mirrors the fabrication check in
    spec-verify.py: each line in [start..end] (1-indexed inclusive)
    is rstrip()-ed and joined with '\\n'.
    """
    total = len(monolith_text.splitlines())
    ok, diag = _bounds_diagnostic(basis_line_start, basis_line_end, total)
    if not ok:
        return False, diag
    normalized = _normalize_range_text(
        monolith_text, basis_line_start, basis_line_end,
    )
    actual = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if actual != expected_sha256:
        return False, f"hash_mismatch: actual={actual} expected={expected_sha256}"
    return True, ""


def format_summary_row(result):
    """Render one '  name:    STATUS (detail)' summary row."""
    label = f"{result.name}:"
    if result.detail:
        body = f"{result.status} ({result.detail})"
    else:
        body = result.status
    return f"  {label:<13} {body}"


def print_summary(results, exit_code):
    """Emit the R1.3 verification summary block to stdout.

    Format (per prompt):
        === Verification Summary ===
          coverage:    PASS
          ...
        ============================
        EXIT: <integer>
    """
    print()
    print("=== Verification Summary ===")
    for r in results:
        print(format_summary_row(r))
    print("============================")
    print(f"EXIT: {exit_code}")


# T5 / T6 stubs ------------------------------------------------------
# These functions return the N/A placeholder CheckResults that occupy
# the summary slots for checks that are not yet wired up. T5 replaces
# stub_mandate_result with R3.0/R3.3/R3.7; T6 replaces stub_utility_result,
# stub_meta_rule_result, stub_ambiguous_result with R1.1/R5.3/R4a.3.
#
# Keeping them as functions (rather than module-level constants) lets T5/T6
# swap them in-place by adding new imports or modifying main() without
# needing to also adjust the summary block ordering.


def stub_mandate_result():
    """Placeholder for T5's R3.0/R3.3/R3.7 mandate check."""
    return CheckResult("mandate", "N/A", "guide_version < 1", 0)


def stub_utility_result():
    """Placeholder for T6's R1.1 utility check."""
    return CheckResult("utility", "N/A", "guide_version < 1", 0)


def stub_meta_rule_result():
    """Placeholder for T6's R5.3 meta-rule check."""
    return CheckResult("meta_rule", "N/A", "guide_version < 1", 0)


def stub_ambiguous_result():
    """Placeholder for T6's R4a.3 AMBIGUOUS block gate."""
    return CheckResult("ambiguous", "N/A", "guide_version < 1", 0)
