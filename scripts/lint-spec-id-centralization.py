#!/usr/bin/env python3
"""Static lint (M9 / F5, task 20260530-092123): forbid any /dev*//spec command
markdown from re-deriving a spec-id / views_dir / split_marker / cp_dir from a
path INLINE instead of calling the centralized resolver helper
(scripts/resolve-spec-artifacts.py).

Centralization is the root-cause fix: prose re-derivation is the exact mechanism by
which the spec- prefix rule drifted. This lint mechanically prevents recurrence.

A line FAILS if it contains a forbidden inline spec-id-from-path derivation
pattern AND is NOT whitelisted. Whitelist:
  - the resolver invocation line itself (contains `resolve-spec-artifacts`)
  - the lint script's own name (self-reference)
  - any line carrying the explicit allow-marker `# spec-id-lint: allow`

Usage:
  lint-spec-id-centralization.py --paths <file> [<file> ...]
Exit: 0 = clean ; 1 = forbidden inline derivation found ; 2 = usage error
"""

import argparse
import re
import sys

# Forbidden inline derivation patterns (prose or bash) that re-derive a spec-id /
# views_dir / split_marker / cp_dir from a path instead of consuming the resolver.
#
# Patterns are CASE-INSENSITIVE on the spec-path/spec-id variable name so the lint
# catches BOTH the uppercase env-var form (${SPEC_PATH...}) AND the lowercase
# shell-local form (${spec_path...}). The lowercase miss is exactly how the
# inline derivation at commands/spec.md:238 slipped past the original lint
# (task 20260530-092123 F-QA-1): EXPECT_ID="${spec_path##*/}"; %.md; #spec-.
#
# `SPEC_VAR` matches the spec-path/spec-id variable name component (optional
# USER_ prefix, either spec_path or spec_id, any case).
SPEC_VAR = r"(?:USER_)?SPEC_(?:PATH|ID)"
# An identifier-shaped bash variable name (for intermediate id vars stripped by hand).
ANY_VAR = r"[A-Za-z_][A-Za-z0-9_]*"
FORBIDDEN = [
    # basename($SPEC_PATH) / basename "$spec_path" / basename -- "$spec_path" .md —
    # any same-line basename invocation referencing the spec-path/id var, including
    # option tokens (-- / -s suffix) between `basename` and the var.
    re.compile(r"basename\b[^\n]*\$\{?" + SPEC_VAR, re.IGNORECASE),
    # ${spec_path##*/} / ${spec_path#*/} — basename via parameter expansion
    # (one or two leading '#', strip up to a '/').
    re.compile(r"\$\{" + SPEC_VAR + r"#{1,2}[^}]*/", re.IGNORECASE),
    # ${spec_path%/*} / ${spec_path%%/*} — dirname via parameter expansion.
    re.compile(r"\$\{" + SPEC_VAR + r"%{1,2}[^}]*/", re.IGNORECASE),
    # ${spec_path%.md} / ${spec_path%%.md} — strip .md suffix derivation.
    re.compile(r"\$\{" + SPEC_VAR + r"%{1,2}\.md\}", re.IGNORECASE),
    # ${spec_id#spec-} / ${spec_path##spec-} — strip the leading spec- prefix
    # directly off the spec-path/id var.
    re.compile(r"\$\{" + SPEC_VAR + r"#{1,2}spec-\}", re.IGNORECASE),
    # ${VAR#spec-} / ${VAR##spec-} applied to ANY intermediate id var derived inline
    # (the chained spec.md:238 form: EXPECT_ID="${EXPECT_ID#spec-}").
    re.compile(r"\$\{" + ANY_VAR + r"#{1,2}spec-\}"),
    # inline views/split/cp paths built from a $SPEC_ID variable
    re.compile(r"docs/dev/specs/\$\{?spec_id\}?/", re.IGNORECASE),
    re.compile(r"\.claude/specs/\$\{?spec_id\}?\b", re.IGNORECASE),
    # building manifest/split paths from a bare basename-derived id
    re.compile(r"docs/dev/specs/\$\{?(?:ARTIFACT_ID|SPEC_BASENAME)\}?/views", re.IGNORECASE),
]

# Whitelist markers — a line matching any of these is exempt (these denote a
# genuine resolver invocation or this lint's own self-reference, so they may sit on
# a line that also contains pattern-shaped text).
WHITELIST = [
    re.compile(r"resolve-spec-artifacts"),
    re.compile(r"lint-spec-id-centralization"),
]

# The intentional-example allow marker. CRITICAL: this marker is honored ONLY on a
# COMMENT-ONLY line (first non-blank char is `#`). Allowing it on a code line would
# let a REAL inline derivation be hidden by appending the marker to the same line
# (codex F-QA-1 bypass-hole finding). A counter-example mention belongs in a comment.
ALLOW_MARKER = re.compile(r"#\s*spec-id-lint:\s*allow")


def _is_comment_only(line):
    """True iff the line's first non-blank character begins a comment (`#`)."""
    stripped = line.lstrip()
    return stripped.startswith("#")


def lint_file(path):
    violations = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return [("<read-error>", 0, str(exc))]
    for n, line in enumerate(lines, 1):
        if any(w.search(line) for w in WHITELIST):
            continue
        # allow-marker exempts the line ONLY when it is comment-only — a code line
        # carrying a real derivation cannot be excused by tacking on the marker.
        if ALLOW_MARKER.search(line) and _is_comment_only(line):
            continue
        for pat in FORBIDDEN:
            if pat.search(line):
                violations.append((path, n, line.rstrip()))
                break
    return violations


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lint command markdown for inline spec-id derivation.")
    parser.add_argument("--paths", nargs="+", required=True, help="Files to lint")
    args = parser.parse_args(argv)

    all_violations = []
    for p in args.paths:
        all_violations.extend(lint_file(p))

    if all_violations:
        sys.stderr.write("spec-id centralization lint FAILED — inline spec-id-from-path derivation found:\n")
        for path, n, line in all_violations:
            sys.stderr.write("  %s:%d  %s\n" % (path, n, line))
        sys.stderr.write("Route spec-id/views_dir/split_marker/cp_dir through scripts/resolve-spec-artifacts.py "
                         "(or add `# spec-id-lint: allow` to an intentional example line).\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
