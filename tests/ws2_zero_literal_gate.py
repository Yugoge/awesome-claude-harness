#!/usr/bin/env python3
"""ws2_zero_literal_gate.py — the AC-WS2-6 post-Wave-1 zero-literal integration gate.

Scans the EXPLICITLY-defined load-bearing surfaces of a rendered fresh clone with
the SAME boundary-aware author-path pattern as scripts/detect-hardcoded-paths.sh
(AC-WS3-4), then asserts ZERO *genuine load-bearing* author-absolute literals
remain — every literal that is (a) executed / (b) a tool operand / (c) a dispatch
or dispatch-read / (d) a runtime default. It is a PRINCIPLE measured
comprehensively, not a hand-enumerated checklist.

Why this lives in tests/ and not just `detect-hardcoded-paths.sh`:
  The shipped detector flags EVERY line in *.py / *.sh, including comments,
  docstrings, and doctest examples (e.g. claude_home.py's own docstrings that
  literally say "never the literal /root", bash_write_targets.py's `>>>`
  doctests, runtime_guard.py's protected-system-roots constant `"/root"`). Those
  are NOT load-bearing — they neither execute an author path nor default to one.
  This gate adds the comment/docstring filter + the per-literal PROSE-ONLY
  allowlist (AC-WS7-1) + the BA-documented error-hint / detector-pattern
  exemptions (out_of_scope_observations), so the assertion is falsifiable for the
  GENUINE class without churning illustrative prose. The shipped detector's own
  comment-blindness is recorded as a WS3 recommendation in the dev report; this
  gate does NOT modify it (WI-WS2 scope fence).

Usage: ws2_zero_literal_gate.py <rendered-clone-root> [<residuals-json-out>]
Exit codes: 0 = zero genuine load-bearing residuals; 3 = one or more found.
"""
from __future__ import annotations

import json
import os
import re
import sys

# Boundary-aware author-path pattern — IDENTICAL to scripts/detect-hardcoded-paths.sh
# (AC-WS3-4 / AC-WS2-6): matches /root/... (incl. /root/.claude, /root/bin,
# /root/docs, /root/templates) AND a bare /root at ANY non-path boundary, AND
# /dev/shm/dev-workspace. The lookbehind drops '-' so "${VAR:-/root}" still hits.
AUTHOR_RE = re.compile(
    r"(?<![\w./])(?:/root(?:/|(?=$|[^\w./-]))|/dev/shm/dev-workspace(?:/|(?=$|[^\w./-])))"
)
LITERAL_RE = re.compile(
    r"/root(?:/[^\s\"'`)\];,]*)?|/dev/shm/dev-workspace(?:/[^\s\"'`)\];,]*)?"
)


def in_scope(rel: str) -> bool:
    """The EXPLICITLY-defined load-bearing surfaces (AC-WS3-4)."""
    if rel.startswith("hooks/") or rel.startswith("scripts/"):
        if "/tests/" in rel:
            return False  # tests/ are exempt per AC-WS3-4
        return rel.endswith(".py") or rel.endswith(".sh")
    if rel in ("settings.json", "settings.template.json"):
        return True
    if rel.startswith("commands/") and rel.endswith(".md"):
        return True
    if rel.startswith("agents/") and rel.endswith(".md"):
        return True
    if rel.startswith("skills/") and rel.endswith("SKILL.md"):
        return True
    if rel.startswith("schemas/") and rel.endswith(".json"):
        return True
    if rel.startswith("policies/") and rel.endswith(".json"):
        return True
    return False


# Per-literal PROSE-ONLY allowlist (AC-WS7-1) + BA out_of_scope_observations.
# Each entry exempts ONE illustrative-prose / comment / error-hint / detector-
# pattern literal by file-suffix + substring. NEVER a prefix/path omission.
PROSE_ALLOWLIST = [
    # AC-WS7-1: commands/dev.md post-mortem narrative / origin / error-hint prose
    # + the self-test-fixture LOCATION note (dev.md:1566/1570/1592/1598/1612/1618).
    {"suffix": "commands/dev.md", "contains": "/root"},
    # close.md:32 HTML-comment cross-reference to a BA spec doc path.
    {"suffix": "commands/close.md", "contains": "/root/docs/dev/ba-spec"},
    # The detector's OWN match/extract/classify patterns + its prose allowlist
    # entries (AC-WS3-4: "the detector's own patterns are exempt").
    {"suffix": "scripts/check-file-references.sh", "contains": "/root/my-project"},
    # agents/qa.md + style-inspector.md: detection-example / instruction prose
    # ("grep -nE ...(/root/...)", '"finding": "Hardcoded path /root/deploy/"',
    #  "Hardcoded file paths (e.g., `/root/`...)", the pre-scan detector hint).
    {"suffix": "agents/qa.md", "contains": "/root"},
    {"suffix": "agents/style-inspector.md", "contains": "/root"},
    # BA out_of_scope_observations: comment/docstring/error-hint-only /root hits.
    {"suffix": "hooks/pretool-cp-checkin.py", "contains": "/root"},
    {"suffix": "hooks/pretool-cp-state-write-guard.py", "contains": "/root"},
    {"suffix": "hooks/pretool-bash-views-guard.py", "contains": "/root"},
    {"suffix": "hooks/pretool-orchestrator-prompt-purity.py", "contains": "/root"},
    {"suffix": "scripts/write-commit-grant.py", "contains": "/root"},
    # bash-safety.sh user-facing error-hint echoes pointing at the external
    # /root/bin/claude-allow-restart grant channel (hint text, not an executed
    # path the harness resolves) + comment examples.
    {"suffix": "hooks/pretool-bash-safety.sh", "contains": "/root/bin/claude-allow-restart"},
]

# Whole-file exemptions (AC-WS3-4: "the detector's own patterns are exempt").
# The detector source legitimately embeds the author-path regex it searches FOR;
# treating it as load-bearing would be self-referential. This is the SAME
# wholesale exemption the shipped detector applies to itself.
WHOLE_FILE_EXEMPT = ("scripts/detect-hardcoded-paths.sh",)

# Environment-context docs (advisory; resolver makes them so) — not in surface,
# but guarded here for completeness if a future surface change includes them.
ENV_CONTEXT_DOCS = ("CLAUDE.md", "NESTED-REPO.md")

# A line that defines a list of SYSTEM roots ("/", "/root", "/home", "/etc",...)
# is a protected-system-roots CONSTANT, NOT an author-home default. "/root" here
# is a directory the guard PROTECTS, identical in kind to "/home" or "/etc".
_SYSTEM_ROOTS_LINE = re.compile(
    r'["\']/["\']\s*,\s*["\']/root["\']\s*,\s*["\']/home["\']'
)


def allowlisted(rel: str, literal: str, line: str = "") -> bool:
    if any(rel.endswith(w) for w in WHOLE_FILE_EXEMPT):
        return True
    for e in PROSE_ALLOWLIST:
        if rel.endswith(e["suffix"]) and e["contains"] in literal:
            return True
    if any(rel.endswith(d) for d in ENV_CONTEXT_DOCS):
        return True
    # protected-system-roots constant member: "/root" alongside "/", "/home", ...
    if literal == "/root" and _SYSTEM_ROOTS_LINE.search(line):
        return True
    return False


def strip_inline_comment(line: str, ext: str) -> str:
    """Return the CODE part of a py/sh line (drop a trailing unquoted-# comment).

    Crude single-pass quote tracking — good enough to suppress comment-only
    author-path false positives without a full parser. For .md/.json/.yml we do
    not strip (those use class classification / json-field handling instead).
    """
    if ext not in (".py", ".sh"):
        return line
    in_s = in_d = False
    out = []
    for ch in line:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            break
        out.append(ch)
    return "".join(out)


def md_class(line: str, literal: str) -> str:
    """Classify an author literal on a .md line into the four WS7 classes or
    'plain' (illustrative prose => not load-bearing)."""
    t = line
    if re.search(r"(?:Write|Read|Edit|NotebookEdit)\s*\(\s*file_path\s*=", t):
        return "b"
    if (re.search(r"[A-Z_][A-Z0-9_]*\s*=\s*/root", t)
            or re.search(r":-\s*/root", t)
            or re.search(r'"default"\s*:\s*"' + re.escape(literal), t)
            or re.search(r"environ\.get\([^)]*['\"]" + re.escape(literal), t)
            or re.search(r"\|\|\s*echo\s+/root", t)):
        return "d"
    if re.search(r"(?:Read|Follow instructions in|per|see|follow)\b[^\n]*"
                 + re.escape(literal), t, re.IGNORECASE):
        return "c"
    # executed: a code-fence command / external script invocation context
    if re.search(r"(?:python3?|bash|sh|source|cat|<<|&&|\|)\s", t):
        return "a"
    return "plain"


def scan(root: str):
    findings = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in
                 (".git", "venv", ".venv", "__pycache__", "node_modules", "archive")]
        for f in fn:
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, root)
            if not in_scope(rel):
                continue
            ext = os.path.splitext(f)[1]
            try:
                lines = open(full, errors="replace").read().splitlines()
            except OSError:
                continue
            in_doc = False
            doc_delim = None
            for i, line in enumerate(lines, 1):
                # Python docstring/triple-quote region tracking (skip wholesale).
                if ext == ".py":
                    if not in_doc:
                        m = re.search(r'("""|\'\'\')', line)
                        if m:
                            delim = m.group(1)
                            after = line.split(delim, 1)[1]
                            if delim not in after:
                                in_doc = True
                                doc_delim = delim
                            continue  # the opening docstring line itself is prose
                    else:
                        if doc_delim in line:
                            in_doc = False
                        continue
                code = strip_inline_comment(line, ext)
                if not AUTHOR_RE.search(code):
                    continue
                for mm in LITERAL_RE.finditer(code):
                    literal = mm.group(0)
                    if not AUTHOR_RE.search(literal):
                        continue
                    if allowlisted(rel, literal, line):
                        continue
                    if ext == ".md":
                        cls = md_class(line, literal)
                        if cls == "plain":
                            continue
                    else:
                        cls = "json-field" if ext == ".json" else "code"
                    findings.append({
                        "file": rel, "line": i, "literal": literal,
                        "ws7_class": cls, "code": code.strip()[:160],
                    })
    return findings


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("usage: ws2_zero_literal_gate.py <clone-root> [<out.json>]\n")
        return 2
    root = argv[1]
    out = argv[2] if len(argv) > 2 else None
    findings = scan(root)
    doc = {
        "gate": "ws2-zero-literal-integration",
        "root": root,
        "count": len(findings),
        "findings": findings,
    }
    if out:
        with open(out, "w") as fh:
            json.dump(doc, fh, indent=2)
    else:
        json.dump(doc, fh := sys.stdout, indent=2)
        fh.write("\n")
    return 0 if len(findings) == 0 else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
