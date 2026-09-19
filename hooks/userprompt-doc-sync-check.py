#!/usr/bin/env python3
"""
UserPromptSubmit Hook: Periodic file deletion detection for doc-sync.

Compares current file lists in watched directories against cached state.
If deletions detected, regenerates INDEX.md for affected directories
by invoking posttool-doc-sync.py via subprocess.

Hook type: UserPromptSubmit
Exit codes: 0 always (never blocks)
Cache file: ~/.claude/.doc-sync-cache.json
Check interval: 300 seconds
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CACHE_FILE: Path = Path.home() / '.claude' / '.doc-sync-cache.json'
CHECK_INTERVAL: int = 300  # seconds between checks
HOOK_EVENT_NAME: str = 'UserPromptSubmit'
MAX_OUTPUT_CHARS: int = 10000  # documented cap for hook output strings

# Must match posttool-doc-sync.py constants
WATCHED_DIRS: set[str] = {
    '.claude/commands',
    '.claude/agents',
    '.claude/hooks',
    '.claude/skills',
    '.claude/scripts',
}
SKIP_FILES: set[str] = {'INDEX.md', 'README.md', '__init__.py', '.DS_Store'}

# Project roots to scan, derived generically (no hardcoded private projects).
# Sources, in order:
#   1. CLAUDE_DOC_SYNC_ROOTS — colon-separated list of absolute paths (override).
#   2. CLAUDE_PROJECT_DIR — the active project directory, if set.
#   3. The home directory (covers a top-level ~/.claude install).
def _discover_project_roots() -> list[Path]:
    roots: list[Path] = []
    override = os.environ.get('CLAUDE_DOC_SYNC_ROOTS', '')
    if override:
        roots.extend(Path(p).expanduser() for p in override.split(':') if p)
    project_dir = os.environ.get('CLAUDE_PROJECT_DIR', '')
    if project_dir:
        roots.append(Path(project_dir).expanduser())
    roots.append(Path.home())
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


PROJECT_ROOTS: list[Path] = _discover_project_roots()


def get_dir_snapshot(dir_path: Path) -> set[str]:
    """Get set of file names in a directory (excluding skip files)."""
    if not dir_path.is_dir():
        return set()
    return {
        f.name for f in dir_path.iterdir()
        if f.is_file() and f.name not in SKIP_FILES
    }


def relay_child_notice(child_stdout) -> str | None:
    """Notice text carried by the posttool-doc-sync.py child's stdout, else None.

    Empty, non-JSON and wrong-shape output all mean "nothing to relay". Kept free of
    doc_sync imports: an import error here would break every prompt submission.
    """
    if not isinstance(child_stdout, str) or not child_stdout.strip():
        return None
    try:
        output = json.loads(child_stdout)
    except ValueError:
        return None
    text = output.get('systemMessage') if isinstance(output, dict) else None
    return text if isinstance(text, str) and text.strip() else None


def flush_output(lines: list[str], notices: list[str]) -> None:
    """Print what was collected, then empty both lists so a later failure cannot repeat it.

    With a relayed notice the whole stdout is one JSON object: the harness reads JSON
    only when the output starts with '{' and parses as a whole, so plain lines and JSON
    are never mixed. The resynced lines move into additionalContext (agent) and
    systemMessage carries only the notices (user). Without a notice the output is the
    plain resync text, unchanged.
    """
    if notices:
        output = {
            'systemMessage': '\n'.join(notices)[:MAX_OUTPUT_CHARS],
            'hookSpecificOutput': {
                'hookEventName': HOOK_EVENT_NAME,
                'additionalContext': '\n'.join(lines + notices)[:MAX_OUTPUT_CHARS],
            },
        }
        print(json.dumps(output, ensure_ascii=True))
    elif lines:
        print('\n'.join(lines))
    lines.clear()
    notices.clear()


def main() -> None:
    lines: list[str] = []
    notices: list[str] = []
    try:
        now: float = datetime.now(timezone.utc).timestamp()

        # Throttle: only check every CHECK_INTERVAL seconds
        cache: dict = {}
        if CACHE_FILE.exists():
            try:
                cache = json.loads(CACHE_FILE.read_text())
            except Exception:
                cache = {}

        last_check: float = cache.get('last_check', 0)
        if now - last_check < CHECK_INTERVAL:
            sys.exit(0)

        cached_snapshots: dict[str, list[str]] = cache.get('snapshots', {})
        new_snapshots: dict[str, list[str]] = {}
        dirs_to_resync: list[Path] = []

        for root in PROJECT_ROOTS:
            for wd in WATCHED_DIRS:
                dir_path: Path = root / wd
                key: str = str(dir_path)
                current: set[str] = get_dir_snapshot(dir_path)
                new_snapshots[key] = sorted(current)

                if key in cached_snapshots:
                    old: set[str] = set(cached_snapshots[key])
                    deleted: set[str] = old - current
                    if deleted:
                        dirs_to_resync.append(dir_path)

        # Resync affected directories via posttool-doc-sync.py
        if dirs_to_resync:
            hook_dir: Path = Path.home() / '.claude' / 'hooks'
            for dir_path in dirs_to_resync:
                # Find any remaining file to use as trigger
                remaining: list[Path] = [
                    f for f in dir_path.iterdir()
                    if f.is_file() and f.name not in SKIP_FILES
                ] if dir_path.is_dir() else []

                if remaining:
                    trigger_file: str = str(remaining[0])
                else:
                    # Directory empty or gone, just remove INDEX.md
                    idx: Path = dir_path / 'INDEX.md'
                    if idx.exists():
                        idx.unlink()
                    continue

                fake_input: str = json.dumps({
                    'tool_input': {'file_path': trigger_file}
                })
                child = subprocess.run(
                    ['python3', str(hook_dir / 'posttool-doc-sync.py')],
                    input=fake_input,
                    capture_output=True,
                    text=True,
                    env={**os.environ, 'CLAUDE_PROJECT_DIR': str(dir_path.parent)},
                    timeout=5,
                )
                lines.append(
                    f'doc-sync: detected deletion in {dir_path}, '
                    f'resynced INDEX.md'
                )
                notice = relay_child_notice(child.stdout)
                if notice:
                    notices.append(notice)

        # Output goes out before the cache update, as before.
        flush_output(lines, notices)

        # Update cache
        cache = {
            'last_check': now,
            'snapshots': new_snapshots,
        }
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache))

    except Exception:
        pass
    try:
        # Output collected before a failure (e.g. a timeout on a later directory).
        flush_output(lines, notices)
    except Exception:
        pass
    sys.exit(0)


if __name__ == '__main__':
    main()
