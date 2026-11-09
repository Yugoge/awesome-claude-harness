#!/usr/bin/env python3
r"""
PreToolUse Hook: Bulk-commit detector (advisory: exit 0 always).

Scope: Runs on every Bash tool call. Inspects a `git commit` written with
nothing between `git` and `commit` (`git -C <dir> commit` is not inspected)
and warns on stderr when the commit matches the b5d447e shape:
  - staged set spans 3 or more of {hooks/, commands/, scripts/, packages/, docs/}
  - AND commit subject matches `\bsync\b.*\buncommitted\b` (case-insensitive)
    OR `chore\(claude\)\s*:\s*sync` (the b5d447e exact form)

Why exists:
  - At 2026-04-21 17:45:03 UTC, commit b5d447e
    `chore(claude): sync all uncommitted config, hooks, scripts, sessions, docs`
    landed 93 files spanning hooks/, commands/, scripts/, sessions/, docs/.
    This is the canonical AI-bulk signature.

Exit code: 0 (the warning is the only effect).

Fail-open: Any uncaught exception during hook evaluation results in
exit 0 — the hook never wedges the harness. In particular, if `git diff
--cached --name-only` fails (e.g. CWD is not a git repo), the hook
exits 0.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from lib.git_command_classifier import iter_git_invocations
except Exception:  # fail open: the regex below still runs
    def iter_git_invocations(_command):
        return iter(())


SUBSYSTEM_PREFIXES = ['hooks/', 'commands/', 'scripts/', 'packages/', 'docs/']
BULK_THRESHOLD = 3

# D3 (ticket-20260511-070000): tighten the loose `sync.*uncommitted` regex to
# word-boundary anchored form. The previous pattern false-positives on prose
# like `synchronized` or `re-committed`. The b5d447e exact form
# `chore(claude): sync all uncommitted ...` still matches via word-boundary
# `\bsync\b.*\buncommitted\b` AND continues to be matched by the dedicated
# chore(claude) pattern -- belt-and-suspenders. Subsystem fan-out (>= 3
# subsystem prefixes) is still required for a block, so a commit whose
# subject is JUST `sync uncommitted notes` but only touches docs/ remains
# allowed.
SUBJECT_PATTERNS = [
    re.compile(r'\bsync\b.*\buncommitted\b', re.IGNORECASE),
    re.compile(r'chore\(claude\)\s*:\s*sync', re.IGNORECASE),
]


def _warn(message: str) -> None:
    """Write to stderr and exit 0 (warn-only per user policy: no text-smell hard-blocks)."""
    sys.stderr.write(message)
    sys.exit(0)


def _looks_like_git_commit(command: str) -> bool:
    """True iff the command starts a `git commit` invocation (one in a shell -c string too)."""
    return bool(re.search(r'(?:^|[\s;&|()`])git\s+commit\b', command)) or any(
        inv.subcommand == 'commit' for inv in iter_git_invocations(command))


def _extract_commit_message(command: str) -> str:
    """Best-effort extraction of `-m <msg>` content from a `git commit`."""
    patterns = [
        r"-m\s*=?\s*'([^']*)'",
        r'-m\s*=?\s*"([^"]*)"',
        r'--message\s*=?\s*"([^"]*)"',
        r"--message\s*=?\s*'([^']*)'",
    ]
    for p in patterns:
        m = re.search(p, command)
        if m:
            return m.group(1)
    m = re.search(r'-m\s+(\S+)', command)
    if m:
        return m.group(1)
    return ''


def _subject_matches_bulk(message: str) -> bool:
    """True iff the commit subject matches any AI-bulk pattern."""
    if not message:
        return False
    return any(p.search(message) for p in SUBJECT_PATTERNS)


def _staged_files() -> list:
    """Return the staged file list via `git diff --cached --name-only`.

    Returns [] on any failure (including non-repo CWD).
    """
    try:
        result = subprocess.run(
            ['git', 'diff', '--cached', '--name-only'],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _file_matches_prefix(file_path: str, prefix: str) -> bool:
    """True iff file_path is under the given subsystem prefix.

    Matches both top-level (`hooks/foo.sh`) and nested (`.claude/hooks/foo.sh`,
    `project/scripts/x.sh`) layouts.
    """
    if file_path.startswith(prefix):
        return True
    return ('/' + prefix) in file_path


def _prefixes_for_file(file_path: str) -> set:
    """Return the set of subsystem prefixes a single file belongs to."""
    return {p for p in SUBSYSTEM_PREFIXES if _file_matches_prefix(file_path, p)}


def _classify_subsystems(files: list) -> list:
    """Return subsystem prefixes touched across all files (deduped, sorted)."""
    matched = set()
    for f in files:
        matched.update(_prefixes_for_file(f))
    return sorted(matched)


def _emit_bulk_block(message: str, prefixes: list, files: list) -> None:
    """Emit the formatted bulk-commit warning and exit 0 (warn-only)."""
    _warn(
        f'\nWARN (bulk-commit-detector, not blocking): touched: '
        f'{", ".join(prefixes)}\n'
        f'Commit subject {message[:120]!r} matches AI-bulk pattern '
        f'(the words sync ... uncommitted, or `chore(claude): sync`) AND staged set '
        f'spans {len(prefixes)} subsystem prefixes (threshold: '
        f'{BULK_THRESHOLD}).\n'
        f'Sample staged files (first 10): {files[:10]}\n'
        f'This is the b5d447e shape (2026-04-21 17:45 UTC, 93 files). '
        f'If this is intentional, split into per-subsystem commits OR '
        f'use a non-AI-bulk subject line.\n'
    )


def _evaluate_commit(command: str) -> None:
    """Apply the bulk-detection rule for a `git commit` command."""
    message = _extract_commit_message(command)
    if not _subject_matches_bulk(message):
        return
    files = _staged_files()
    if not files:
        return
    matched_prefixes = _classify_subsystems(files)
    if len(matched_prefixes) < BULK_THRESHOLD:
        return
    _emit_bulk_block(message, matched_prefixes, files)


def main() -> None:
    """Entry point: read JSON-from-stdin, evaluate, exit 0."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    try:
        if data.get('tool_name', '') != 'Bash':
            sys.exit(0)
        command = (data.get('tool_input', {}) or {}).get('command', '') or ''
        if not _looks_like_git_commit(command):
            sys.exit(0)
        _evaluate_commit(command)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == '__main__':
    main()
