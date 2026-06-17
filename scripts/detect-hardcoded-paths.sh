#!/bin/bash
# Description: Detect load-bearing author-absolute path literals across the harness surface.
# Usage: detect-hardcoded-paths.sh [project-root]
# Exit codes: 0=no load-bearing author literals found, 1=one or more found.
#
# REV4 (AC-WS3-4 / AC-WS2-6 / AC-WS7-1): a BOUNDARY-AWARE author-path detector as
# wide as the AC-WS7-1 principle. It:
#   * scans *.json (incl. settings.json executable fields + schema defaults),
#     plus *.py *.sh *.md *.yml *.yaml;
#   * matches the FULL /root/... family (/root/.claude, /root/bin, /root/docs,
#     /root/templates) AND a BARE /root followed by ANY non-path boundary
#     (slash, quote, brace, comma, paren, colon, whitespace, EOL) — so bare-/root
#     env-default forms (${...:-/root}, os.environ.get('HOME','/root'),
#     JSON "default": "/root", || echo /root) are caught — AND /dev/shm/dev-workspace;
#   * in the command/agent/skill/schema instruction surface classifies each
#     literal by the four WS7 classes (executed / tool-operand / dispatch-or-
#     dispatch-read / runtime-default) and flags any load-bearing one;
#   * exempts purely-illustrative prose ONLY by a PER-LITERAL allowlist proof,
#     never by prefix omission or a trailing-slash-only regex.
#
# The boundary-aware match pattern is:
#   (?<![\w./])(?:/root(?:/|(?=$|[^\w./-]))|/dev/shm/dev-workspace(?:/|(?=$|[^\w./-])))
# Note: the lookbehind deliberately EXCLUDES '-' so the shell default operator
# ':-' in "${VAR:-/root}" does NOT suppress the bare-/root match (the '-' right
# before /root must be allowed in the lookbehind position).
set -euo pipefail

PROJECT_ROOT="${1:-.}"

python3 - "$PROJECT_ROOT" <<'PYEOF'
import json
import os
import re
import sys

project_root = sys.argv[1]

# --- Boundary-aware author-path pattern (REV4) ----------------------------------
# Matches /root/... AND a bare /root at any non-path boundary, AND /dev/shm/dev-workspace.
# The lookbehind drops '-' so "${VAR:-/root}" is still matched (':-' precedes /root).
AUTHOR_RE = re.compile(
    r"(?<![\w./-])(?:/root(?:/|(?=$|[^\w./-]))|/dev/shm/dev-workspace(?:/|(?=$|[^\w./-])))"
)

# Extract the full literal token for reporting (the boundary-aware anchor + its tail).
LITERAL_RE = re.compile(r"/root(?:/[^\s\"'`)\];,]*)?|/dev/shm/dev-workspace(?:/[^\s\"'`)\];,]*)?")

SCANNED_INCLUDES = (".py", ".sh", ".md", ".yml", ".yaml", ".json")
EXCLUDE_DIRS = {"venv", ".venv", "node_modules", ".git", "archive"}
EXCLUDE_PATH_FRAGMENTS = ("docs/archive/",)

# Surfaces that are EXEMPT wholesale: the detector's own source, tests, examples.
# (Per AC-WS3-4: tests/ + examples/ + the detector's own patterns are exempt.)
def _is_self_or_exempt_surface(rel: str) -> bool:
    if rel.endswith("detect-hardcoded-paths.sh"):
        return True
    parts = rel.split("/")
    if parts and parts[0] in ("tests", "examples"):
        return True
    return False

# --- Per-literal PROSE-ONLY allowlist -------------------------------------------
# Each entry exempts ONE specific illustrative-prose literal by file + literal
# substring. NEVER a prefix/path omission — every other literal is still scanned.
# (AC-WS7-1: dev.md:1566/1570/1592/1598/1612 post-mortem/origin/error-hint prose;
#  dev.md:1618 self-test-fixture LOCATION note.)
PROSE_ALLOWLIST = [
    {"file_suffix": "commands/dev.md", "contains": "/root/docs/dev/redev-prompt-purity"},
    {"file_suffix": "commands/dev.md", "contains": "/root/.claude"},  # illustrative narrative/origin/error-hint prose
]

# Environment-context docs recorded as out-of-scope (resolver makes them advisory).
ENV_CONTEXT_DOCS = ("CLAUDE.md", "NESTED-REPO.md")

def _allowlisted(rel: str, literal: str, line_text: str) -> bool:
    for entry in PROSE_ALLOWLIST:
        if rel.endswith(entry["file_suffix"]) and entry["contains"] in literal:
            return True
    # Environment-context docs: the symlink-boundary description is advisory.
    if any(rel.endswith(doc) for doc in ENV_CONTEXT_DOCS):
        return True
    return False

# --- Four-class context classification (instruction surface only) ---------------
INSTRUCTION_SURFACE = (".md",) + (".json",)  # commands/agents/skills .md + schemas .json

def classify(line_text: str, literal: str) -> str:
    """Return the WS7 class (a/b/c/d) or 'plain' for a literal on a line."""
    t = line_text
    # (b) tool operand: Write(file_path="...") / Read(file_path="...")
    if re.search(r"(?:Write|Read|Edit|NotebookEdit)\s*\(\s*file_path\s*=", t):
        return "b"
    # (d) runtime default: CONTROL_ROOT=/root, ${VAR:-/root}, "default": "/root",
    #     os.environ.get(...,'/root'), || echo /root
    if (re.search(r"[A-Z_][A-Z0-9_]*\s*=\s*/root", t)
            or re.search(r"\$\{[^}]*:-\s*" + re.escape(literal.split('/')[0] or '/root'), t)
            or re.search(r":-\s*/root", t)
            or re.search(r'"default"\s*:\s*"' + re.escape(literal), t)
            or re.search(r"environ\.get\([^)]*['\"]" + re.escape(literal), t)
            or re.search(r"\|\|\s*echo\s+/root", t)):
        return "d"
    # (c) dispatch / dispatch-read: "Read <path>", "Follow instructions in <path>",
    #     "per <path>", "see <path>", "Read that document"
    if re.search(r"(?:Read|Follow instructions in|per|see|follow)\b[^\n]*" + re.escape(literal), t, re.IGNORECASE):
        return "c"
    # (a) executed: inside a code/command context — path used as a command/arg/redir/source operand
    if re.search(r"(?:python3?|bash|sh|source|cat|<|>|&&|\|)\s", t) or re.search(re.escape(literal) + r"\s", t):
        return "a"
    return "plain"

def line_is_load_bearing(rel: str, line_text: str, literal: str) -> bool:
    ext = os.path.splitext(rel)[1]
    # Executable code (*.py *.sh) and settings/schema JSON: every author literal is load-bearing.
    if ext in (".py", ".sh"):
        return True
    if ext == ".json":
        return True
    # *.yml / *.yaml: treat as load-bearing config.
    if ext in (".yml", ".yaml"):
        return True
    # Instruction surface (*.md): classify; plain illustrative prose is NOT load-bearing.
    if ext == ".md":
        cls = classify(line_text, literal)
        return cls in ("a", "b", "c", "d")
    return True

# --- Walk + scan ----------------------------------------------------------------
findings = []
for dirpath, dirnames, filenames in os.walk(project_root):
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
    for fname in filenames:
        ext = os.path.splitext(fname)[1]
        if ext not in SCANNED_INCLUDES:
            continue
        full = os.path.join(dirpath, fname)
        rel = os.path.relpath(full, project_root)
        if any(frag in rel for frag in EXCLUDE_PATH_FRAGMENTS):
            continue
        if _is_self_or_exempt_surface(rel):
            continue
        try:
            with open(full, "r", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for i, line_text in enumerate(lines, start=1):
            if not AUTHOR_RE.search(line_text):
                continue
            for m in LITERAL_RE.finditer(line_text):
                literal = m.group(0)
                if not AUTHOR_RE.search(literal):
                    continue
                if _allowlisted(rel, literal, line_text):
                    continue
                if not line_is_load_bearing(rel, line_text, literal):
                    continue
                cls = classify(line_text, literal) if ext == ".md" else (
                    "json-field" if ext == ".json" else "code")
                findings.append({
                    "file": rel,
                    "line": i,
                    "hardcoded_path": literal,
                    "ws7_class": cls,
                    "severity": "critical",
                })

total = len(findings)
print(json.dumps({
    "detector": "hardcoded-paths",
    "project_root": project_root,
    "findings": findings,
    "summary": {
        "total": total,
        "severity": "critical" if total > 0 else "none",
    },
}, indent=2))

sys.exit(1 if total > 0 else 0)
PYEOF
