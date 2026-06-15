#!/usr/bin/env python3
"""Build directory trees for INDEX.md."""

from pathlib import Path

# Dual-mode import: relative when loaded as `hooks.doc_sync.tree`
# (production), package-context fallback when loaded standalone via
# importlib.util spec_from_file_location (spec-20260518-225715 Cycle 3
# Debt 7 / AC-07 test).
try:
    from .extract import extract_description
except ImportError:
    import importlib as _importlib
    import os as _os
    import sys as _sys
    _pkg_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    if _pkg_root not in _sys.path:
        _sys.path.insert(0, _pkg_root)
    _extract = _importlib.import_module("hooks.doc_sync.extract")
    extract_description = _extract.extract_description  # type: ignore[no-redef]

SKIP_FILES = {
    'INDEX.md', 'README.md', '__init__.py', '.DS_Store',
    # Runtime telemetry — gitignored per spec-20260518-225715 Cycle 2 P2.3;
    # excluding from the rendered tree prevents re-leakage on regen.
    'agent-scores.json', 'agent-scores.json.lock',
    # Lifecycle JSONL score log and its lock file (arch-7 phase 2, task 20260525-050824).
    # lifecycle.jsonl is tracked in git but must not appear in rendered INDEX trees.
    'lifecycle.jsonl', 'lifecycle.jsonl.lock',
}
IGNORE_DIRS = {
    'node_modules', '.git', '__pycache__', '.venv', 'venv',
    'dist', 'build', '.next', '.cache', 'coverage',
    # Gitignored runtime/archive top-level dirs (task 20260614-205834): these
    # are never tracked, so listing them in a tracked INDEX leaks deleted/ignored
    # content on regen (e.g. archive/commands/* reappearing). Excluding them from
    # the rendered tree mirrors the existing gitignored-leak-suppression intent
    # above. NOTE: 'specs' is deliberately NOT here — it is handled selectively by
    # _is_dot_claude_specs so legitimate non-.claude specs/ siblings survive.
    'archive', 'backups', 'cache', 'debug', 'dev-registry', 'eval',
    'file-history', 'graphify-out', 'logs', 'paste-cache', 'plans', 'plugins',
    'projects', 'session-env', 'sessions', 'shell-snapshots', 'state',
    'statsig', 'tasks', 'todos', 'worktrees',
}
# Prefix-aware leak suppression (spec-20260518-225715 Cycle 3 Debt 7 / AC-07):
# cp-state-*.json runtime telemetry and spec-2026*-* spec views must NOT
# appear in any rendered INDEX tree. We use a `startswith` prefix filter
# applied via _matches_skip_prefix because timestamped variants cannot be
# enumerated as exact set members.
SKIP_PREFIXES = ('cp-state-', 'spec-2026')


def _matches_skip_prefix(name: str) -> bool:
    """True iff name begins with any SKIP_PREFIXES entry (prefix-aware filter)."""
    for prefix in SKIP_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


# PATH-AWARE leak suppression (spec-20260518-225715 Cycle 2 P2.4b): suppress
# `.claude/specs/...` cp-state telemetry subtrees while preserving any
# legitimate non-.claude `specs/` sibling (e.g. `ordinary/specs/`). The
# predicate matches a directory whose own name is `specs` AND whose parent's
# name is `.claude`; a blanket `i.name == 'specs'` check would also suppress
# `ordinary/specs/` and is explicitly forbidden by the AC-09 negative control.
def _is_dot_claude_specs(item: Path) -> bool:
    return item.is_dir() and item.name == 'specs' and item.parent.name == '.claude'


def build_tree(dir_path: Path, prefix: str = '', depth: int = 0,
               max_depth: int = 3) -> list[str]:
    if depth >= max_depth or not dir_path.is_dir():
        return []
    items = sorted(
        dir_path.iterdir(),
        key=lambda x: (x.is_file(), x.name.lower()),
    )
    items = [
        i for i in items
        if i.name not in SKIP_FILES
        and i.name not in IGNORE_DIRS
        and not i.name.startswith('.')
        and not _is_dot_claude_specs(i)
        and not _matches_skip_prefix(i.name)
    ]
    lines = []
    for idx, item in enumerate(items):
        is_last = (idx == len(items) - 1)
        conn = '\u2514\u2500\u2500 ' if is_last else '\u251c\u2500\u2500 '
        if item.is_dir():
            ext = '    ' if is_last else '\u2502   '
            lines.append(f'{prefix}{conn}{item.name}/')
            lines.extend(build_tree(item, prefix + ext, depth + 1, max_depth))
        else:
            desc = extract_description(item)
            lines.append(f'{prefix}{conn}`{item.name}` - {desc}')
    return lines
