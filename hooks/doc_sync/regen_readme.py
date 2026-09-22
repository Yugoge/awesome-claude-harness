#!/usr/bin/env python3
"""Regenerate README.md for a directory."""

from pathlib import Path

# Dual-mode import: relative when loaded as `hooks.doc_sync.regen_readme`
# (production), package-context fallback when loaded standalone via
# importlib.util spec_from_file_location (spec-20260518-225715 Cycle 3
# Debt 7 / AC-07 test). The fallback installs the parent of `hooks/` onto
# sys.path and imports the full package, so transitive relative imports
# (regen_readme -> regions/config/extract) all resolve. Loaded either way, RegenStatus is
# the one class object defined in regions, never a second copy.
try:
    from .extract import extract_description
    from .config import tracked_names, is_github_reserved_subtree
    from .regions import (
        README_MARKER_ID, RegenStatus, RegionShape, classify_region, marker_close,
        marker_line_numbers, marker_open, replace_region,
    )
except ImportError:
    import importlib as _importlib
    import os as _os
    import sys as _sys
    _pkg_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    if _pkg_root not in _sys.path:
        _sys.path.insert(0, _pkg_root)
    _extract = _importlib.import_module("hooks.doc_sync.extract")
    _config = _importlib.import_module("hooks.doc_sync.config")
    _regions = _importlib.import_module("hooks.doc_sync.regions")
    extract_description = _extract.extract_description  # type: ignore[no-redef]
    tracked_names = _config.tracked_names  # type: ignore[no-redef]
    is_github_reserved_subtree = _config.is_github_reserved_subtree  # type: ignore[no-redef]
    README_MARKER_ID = _regions.README_MARKER_ID  # type: ignore[no-redef]
    RegenStatus = _regions.RegenStatus  # type: ignore[no-redef,misc]
    RegionShape = _regions.RegionShape  # type: ignore[no-redef,misc]
    classify_region = _regions.classify_region  # type: ignore[no-redef]
    marker_close = _regions.marker_close  # type: ignore[no-redef]
    marker_line_numbers = _regions.marker_line_numbers  # type: ignore[no-redef]
    marker_open = _regions.marker_open  # type: ignore[no-redef]
    replace_region = _regions.replace_region  # type: ignore[no-redef]

README_OPEN_MARKER = marker_open(README_MARKER_ID)
README_CLOSE_MARKER = marker_close(README_MARKER_ID)


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
# The GitHub-reserved-subtree skip lives in config.is_github_reserved_subtree
# (canonicalized whole-subtree membership) and is applied in regen_readme().


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


def _skip_status(text: str) -> RegenStatus | None:
    """Skip status of an existing README's text, or None when its AUTO region is well-formed.

    The same classifier replace_region uses, so classifying a README and replacing its
    region can never disagree.
    """
    return classify_region(text, README_MARKER_ID).status


def _readme_needs_update(readme_path: Path) -> bool:
    if not readme_path.exists():
        return True
    return _skip_status(readme_path.read_text()) is None


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


def _build_readme_body(dir_path: Path, convention: str) -> str:
    """The generated text between the markers. Built on its own, never cut out of a whole
    README by splitting on marker text, so a description that carries a marker line cannot
    truncate it."""
    stats = _build_stats(dir_path)
    file_lines = _list_files(dir_path)
    dir_lines = _list_subdirs(dir_path)
    lines = [f'## Overview\n- **Total files**: {stats["total"]}']
    lines.append(f'- **Subdirectories**: {stats["dirs"]}')
    lines.append(f'- **Naming convention**: {convention}')
    if file_lines:
        lines.append('\n## Files\n' + '\n'.join(file_lines))
    if dir_lines:
        lines.append('\n## Subdirectories\n' + '\n'.join(dir_lines))
    return '\n'.join(lines)


def _compose_readme(dir_path: Path, body: str) -> str:
    # The closing marker terminates the AUTO region (mirrors regen_index's AUTO_START/AUTO_END
    # pair): without it replace_region cannot locate the region's end, which froze every
    # generated README at its first write -- stats could never be refreshed.
    return (f'# {dir_path.name}\n\n{README_OPEN_MARKER}\n{body}\n\n{README_CLOSE_MARKER}'
            '\n\n---\n*Auto-generated by doc-sync hook.*')


def _build_readme_content(dir_path: Path, convention: str) -> str:
    return _compose_readme(dir_path, _build_readme_body(dir_path, convention))


def regen_readme(dir_path: Path, project_dir: Path | None = None) -> RegenStatus:
    """Regenerate README.md for a directory and report what happened.

    project_dir (the repository root) anchors the GitHub-reserved-subtree check to
    the repo, making it CWD-independent; see config.is_github_reserved_subtree.
    An existing README is classified from its original text before anything is
    written, so a skip never touches the file (no bytes, no mtime). Content that would put
    marker text of its own into the file (a multi-line description) is refused the same way:
    a file the classifier rejects on the next run must never be produced by this one.
    """
    # GitHub renders .github/README.md in place of the repo-root README, so a
    # doc-sync stub anywhere under the GitHub-reserved subtree would hijack the
    # landing page (top-level) or add repo-noise (nested). Skip when the folder
    # IS .github or lies beneath it (tested relative to project_dir), robust to
    # non-canonical '..' inputs.
    if is_github_reserved_subtree(dir_path, project_dir):
        return RegenStatus.SKIPPED_GITHUB_RESERVED
    readme_path = dir_path / 'README.md'
    old = None
    if readme_path.exists():
        old = readme_path.read_text()
        # A README without a well-formed AUTO region is hand-written (or legacy) and
        # is never rewritten, so no hand annotation can be wiped; report why instead.
        skip = _skip_status(old)
        if skip is not None:
            return skip
    body = _build_readme_body(dir_path, _detect_convention(dir_path))
    if marker_line_numbers(body):
        return RegenStatus.SKIPPED_MALFORMED_MARKERS
    if old is None:
        content = _compose_readme(dir_path, body)
        if classify_region(content, README_MARKER_ID).shape is not RegionShape.WELL_FORMED:
            return RegenStatus.SKIPPED_MALFORMED_MARKERS
    else:
        replaced = replace_region(old, README_MARKER_ID, body.strip('\n'))
        if not replaced.replaced:
            return RegenStatus.SKIPPED_MALFORMED_MARKERS
        content = replaced.text
    readme_path.write_text(content)
    return RegenStatus.WRITTEN
