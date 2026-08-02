#!/usr/bin/env python3
"""PreToolUse Hook (Bash): Block Bash write-bypass into views and cp-state.

Parallels pretool-bash-safety.sh but focuses on views/cp-state write bypass.

Blocks Bash commands that:
  - Redirect into `*.lock.json` or `*/manifest.json.lock`
  - Redirect into `docs/dev/specs/*/views/*.md` (views are read-only)
  - Redirect into `.claude/specs/*/cp-state-*.json` (spec-check.py only)
  - Redirect into `docs/dev/specs/*/views/manifest.json` (Write tool only)

Whitelist: commands invoking `.claude/scripts/spec-check.py` are
allowed even if they appear to touch these paths (these ARE the legal writers).

Fail-open on parse errors. Exit 0 = allow, exit 2 = block.
"""

import json
import re
import sys
from pathlib import Path

# Remediation paths are derived from THIS hook's own on-disk location
# (<harness-home>/hooks/<name>.py), so the message names the spec-check.py that
# actually exists for the invoking user instead of an author-absolute literal.
SPEC_CHECK = Path(__file__).resolve().parent.parent / "scripts" / "spec-check.py"


BLOCK_PATTERNS = [
    re.compile(r"(>|>>)\s*\S*\.lock\.json"),
    re.compile(r"(>|>>)\s*\S*manifest\.json\.lock"),
    re.compile(r"(>|>>)\s*\S*docs/dev/specs/[^/]+/views/[^/]+\.md"),
    re.compile(r"(>|>>)\s*\S*docs/dev/specs/[^/]+/views/manifest\.json"),
    re.compile(r"(>|>>)\s*\S*\.claude/specs/[^/]+/cp-state-[^/]+\.json"),
]

# Whitelisted invocations (bypass all views/cp-state write checks)
WHITELIST_PATTERNS = [
    re.compile(r"\.claude/scripts/spec-check\.py"),
    re.compile(r"bin/spec-check\.py"),  # legacy path; retained for compatibility with old invocations
]


def _load_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return None


def _extract_command(data):
    if not isinstance(data, dict):
        return ""
    if data.get("tool_name") != "Bash":
        return ""
    tool_input = data.get("tool_input") or {}
    return tool_input.get("command") or ""


def _is_whitelisted(command):
    return any(p.search(command) for p in WHITELIST_PATTERNS)


def _matches_block(command):
    for pattern in BLOCK_PATTERNS:
        if pattern.search(command):
            return pattern.pattern
    return None


def _emit_block(pattern, command):
    sys.stderr.write(
        "BLOCKED: Bash write-bypass into views/cp-state is forbidden\n"
        f"Pattern: {pattern}\n"
        f"Command: {command}\n"
        "Legal writers:\n"
        "  - views/*.md, manifest.json: Write tool (not Bash)\n"
        f"  - cp-state-*.json: python3 {SPEC_CHECK}\n"
        "Never `echo >` or `cat >` these paths.\n"
    )


def main():
    data = _load_stdin()
    if data is None:
        sys.exit(0)
    command = _extract_command(data)
    if not command:
        sys.exit(0)
    if _is_whitelisted(command):
        sys.exit(0)
    hit = _matches_block(command)
    if hit:
        _emit_block(hit, command)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
