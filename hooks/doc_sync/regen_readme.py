#!/usr/bin/env python3
"""Regenerate README.md for a directory."""

from pathlib import Path

# Dual-mode import: relative when loaded as `hooks.doc_sync.regen_readme`
# (production), package-context fallback when loaded standalone via
# importlib.util spec_from_file_location (spec-20260518-225715 Cycle 3
# Debt 7 / AC-07 test). The fallback installs the parent of `hooks/` onto
# sys.path and imports the full package, so transitive relative imports
# (regen_readme -> patch -> claude/docker/systemd) all resolve.
try:
    from .extract import extract_description
    from .patch import _replace_section
    from .config import tracked_names
except ImportError:
    import importlib as _importlib
    import os as _os
    import sys as _sys
    _pkg_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    if _pkg_root not in _sys.path:
        _sys.path.insert(0, _pkg_root)
    _extract = _importlib.import_module("hooks.doc_sync.extract")
    _patch = _importlib.import_module("hooks.doc_sync.patch")
    _config = _importlib.import_module("hooks.doc_sync.config")
    extract_description = _extract.extract_description  # type: ignore[no-redef]
    _replace_section = _patch._replace_section  # type: ignore[no-redef]
    tracked_names = _config.tracked_names  # type: ignore[no-redef]

SKIP_NAMES = {
    'INDEX.md', 'README.md', '__init__.py', '.DS_Store',
    # Runtime telemetry — gitignored per spec-20260518-225715 Cycle 2 P2.3;
    # excluding from the README listing prevents re-leakage on regen.
    'agent-scores.json', 'agent-scores.json.lock',
    # Lifecycle JSONL score log and its lock file (arch-7 phase 2, task 20260525-050824).
    # lifecycle.jsonl is tracked in git but must not appear in generated README listings.
    'lifecycle.jsonl', 'lifecycle.jsonl.lock',
}
SKIP_DIRS = {'__pycache__', '.git', 'node_modules'}
# Prefix-aware suppression (spec-20260518-225715 Cycle 3 Debt 7 / AC-07):
# cp-state-*.json and spec-2026*-* artifacts are runtime telemetry / spec
# views that must NOT appear in any generated README. Set membership cannot
# match timestamped variants (cp-state-ba.json, cp-state-qa.json, cp-state-
# dev.json, spec-20260520-221059, spec-20260524-test ...), so we use a
# prefix-aware `startswith` filter applied in _build_stats and _list_files.
SKIP_PREFIXES = ('cp-state-', 'spec-2026')


def _is_skipped(name: str) -> bool:
    """True iff the basename matches an exact SKIP_NAMES entry or a SKIP_PREFIXES prefix."""
    if name in SKIP_NAMES:
        return True
    for prefix in SKIP_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


def _published_names(dir_path: Path) -> set[str] | None:
    """Git-tracked basenames directly under dir_path, or None when git was not
    consulted (not a work-tree / git unavailable) so callers fall back to the
    hand denylist only (AC-WS5-1)."""
    return tracked_names(dir_path)


def _is_published(name: str, published: set[str] | None) -> bool:
    """An entry is listable iff it is not denylisted AND (git was not consulted
    OR the entry is git-tracked). When git IS consulted, untracked/gitignored
    entries are dropped — the doc-sync output lists only published files."""
    if _is_skipped(name) or name.startswith('.'):
        return False
    if published is not None and name not in published:
        return False
    return True


def _build_stats(dir_path: Path) -> dict:
    published = _published_names(dir_path)
    total = 0
    dirs = 0
    for item in dir_path.iterdir():
        if not _is_published(item.name, published):
            continue
        total += 1
        if item.is_dir():
            dirs += 1
    return {'total': total, 'dirs': dirs}


def _detect_convention(dir_path: Path) -> str:
    files = list(dir_path.iterdir())
    if not files:
        return 'kebab'
    kebab_count = sum(1 for f in files if '-' in f.name)
    if kebab_count > len(files) // 2:
        return 'kebab'
    return 'lower'


def _readme_needs_update(readme_path: Path) -> bool:
    if not readme_path.exists():
        return True
    return '<!-- AUTO:readme-stats -->' in readme_path.read_text()


def _list_files(dir_path: Path) -> list[str]:
    published = _published_names(dir_path)
    files = sorted(f for f in dir_path.iterdir()
                   if f.is_file() and _is_published(f.name, published))
    return [f'- `{f.name}` - {extract_description(f)}' for f in files]


def _list_subdirs(dir_path: Path) -> list[str]:
    published = _published_names(dir_path)
    subdirs = sorted(d for d in dir_path.iterdir()
                     if d.is_dir() and d.name not in SKIP_DIRS
                     and _is_published(d.name, published))
    return [f'- `{d.name}/`' for d in subdirs]


def _build_readme_content(dir_path: Path, convention: str) -> str:
    stats = _build_stats(dir_path)
    file_lines = _list_files(dir_path)
    dir_lines = _list_subdirs(dir_path)
    lines = [f'# {dir_path.name}', '', '<!-- AUTO:readme-stats -->']
    lines.append(f'## Overview\n- **Total files**: {stats["total"]}')
    lines.append(f'- **Subdirectories**: {stats["dirs"]}')
    lines.append(f'- **Naming convention**: {convention}')
    if file_lines:
        lines.append('\n## Files\n' + '\n'.join(file_lines))
    if dir_lines:
        lines.append('\n## Subdirectories\n' + '\n'.join(dir_lines))
    lines.append('\n---\n*Auto-generated by doc-sync hook.*')
    return '\n'.join(lines)


def regen_readme(dir_path: Path):
    """Regenerate README.md for a directory."""
    readme_path = dir_path / 'README.md'
    if not _readme_needs_update(readme_path):
        return
    convention = _detect_convention(dir_path)
    content = _build_readme_content(dir_path, convention)
    if readme_path.exists():
        old = readme_path.read_text()
        if '<!-- AUTO:readme-stats -->' in old:
            body = content.split('<!-- AUTO:readme-stats -->')[1].split('-->')[0]
            content = _replace_section(old, 'readme-stats', body)
    readme_path.write_text(content)
