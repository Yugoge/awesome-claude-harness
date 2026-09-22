#!/usr/bin/env python3
"""Patch CLAUDE.md dynamic sections using AUTO markers."""

from datetime import datetime, timezone
from pathlib import Path
from .claude import ensure_claude_md
from .docker import build_docker_table
from .regions import (
    ArtifactKind, RegenRecord, RegenStatus, RegionShape, classify_region, replace_region,
)
from .systemd import build_systemd_table


def _is_global_claude_md(claude_md: Path) -> bool:
    """True when the target path resolves to the global ~/.claude/CLAUDE.md."""
    try:
        return claude_md.resolve() == (Path.home() / '.claude' / 'CLAUDE.md').resolve()
    except OSError:
        return False


def _replace_section(content: str, marker_id: str, new_body: str) -> str:
    """The text with the region's body replaced, or `content` itself when the region is not
    well-formed or the body would break it (see regions.replace_region)."""
    return replace_region(content, marker_id, new_body).text


def _count_entries(subdir_path: Path, is_skills: bool) -> int:
    if is_skills:
        return len([dd for dd in subdir_path.iterdir() if dd.is_dir() and not dd.name.startswith('.')])
    return len([f for f in subdir_path.iterdir() if f.is_file() and f.name not in ('INDEX.md', 'README.md', '__init__.py', '.DS_Store')])


def _format_inventory_line(subdir: str, count: int) -> str:
    if subdir == 'skills':
        return f'- **{subdir}**: {count} active'
    return f'- **{subdir}**: {count} files'


def _build_inventory(project_dir: Path) -> str:
    claude_dir = project_dir / '.claude'
    if not claude_dir.is_dir():
        return ''
    lines = []
    for subdir in ['commands', 'agents', 'hooks', 'skills', 'scripts']:
        d = claude_dir / subdir
        if not d.is_dir():
            continue
        count = _count_entries(d, subdir == 'skills')
        lines.append(_format_inventory_line(subdir, count))
    return '\n'.join(lines)


def _build_file_list(dir_path: Path) -> str:
    if not dir_path.is_dir():
        return ''
    files = [
        f for f in dir_path.iterdir()
        if f.is_file() and f.name not in ('INDEX.md', 'README.md', '__init__.py', '.DS_Store')
    ]
    rel = dir_path.name
    return f'See `.claude/{rel}/INDEX.md` ({len(files)} entries)'


def _patch_section(content: str, marker_id: str, build_body, notes: list) -> str:
    """Regenerate one section. A section without markers is not opted in and stays silent; any
    other shape the classifier refuses is appended to `notes` and the text is left untouched."""
    region = classify_region(content, marker_id)
    if region.shape is RegionShape.NO_MARKERS:
        return content
    if region.shape is not RegionShape.WELL_FORMED:
        notes.append((marker_id, region.status, region.shape, region.fence_line))
        return content
    body = build_body()
    if body is None:
        return content
    replaced = replace_region(content, marker_id, body)
    if not replaced.replaced:
        notes.append((marker_id, RegenStatus.SKIPPED_MALFORMED_MARKERS, replaced.shape, None))
    return replaced.text


def _patch_inventory(content: str, project_dir: Path, notes: list | None = None) -> str:
    return _patch_section(content, 'claude-inventory', lambda: _build_inventory(project_dir),
                          [] if notes is None else notes)


def _patch_commands(content: str, project_dir: Path, notes: list | None = None) -> str:
    return _patch_section(content, 'command-list',
                          lambda: _build_file_list(project_dir / '.claude' / 'commands'),
                          [] if notes is None else notes)


def _patch_agents(content: str, project_dir: Path, notes: list | None = None) -> str:
    return _patch_section(content, 'agent-list',
                          lambda: _build_file_list(project_dir / '.claude' / 'agents'),
                          [] if notes is None else notes)


def _build_skill_list(project_dir: Path):
    sd = project_dir / '.claude' / 'skills'
    if not sd.is_dir():
        return None
    dirs = sorted([d.name for d in sd.iterdir() if d.is_dir() and not d.name.startswith('.')])
    return '\n'.join(f'- `{d}/`' for d in dirs)


def _patch_skills(content: str, project_dir: Path, notes: list | None = None) -> str:
    return _patch_section(content, 'skill-list', lambda: _build_skill_list(project_dir),
                          [] if notes is None else notes)


def _patch_last_updated(content: str, notes: list | None = None) -> str:
    def build_body():
        return f'> Last updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d")}'
    return _patch_section(content, 'last-updated', build_body, [] if notes is None else notes)


def _patch_docker(content: str, notes: list | None = None) -> str:
    return _patch_section(content, 'docker-services', lambda: build_docker_table() or None,
                          [] if notes is None else notes)


def _patch_systemd(content: str, project_dir: Path, notes: list | None = None) -> str:
    return _patch_section(content, 'systemd-services', lambda: build_systemd_table(project_dir) or None,
                          [] if notes is None else notes)


def patch_claude_md(project_dir: Path) -> list:
    """Patch CLAUDE.md dynamic sections using AUTO markers.

    Returns one RegenRecord per opted-in section the classifier refused (nothing was written
    for it); a section without markers and a regenerated one produce no record.
    """
    ensure_claude_md(project_dir)
    records: list = []
    candidates = [
        project_dir / 'CLAUDE.md',
        project_dir / '.claude' / 'CLAUDE.md',
    ]
    for claude_md in candidates:
        if not claude_md.exists():
            continue
        content = claude_md.read_text()
        if '<!-- AUTO:' not in content:
            continue
        is_global = _is_global_claude_md(claude_md)
        new_content = content
        notes: list = []
        new_content = _patch_inventory(new_content, project_dir, notes)
        new_content = _patch_commands(new_content, project_dir, notes)
        new_content = _patch_agents(new_content, project_dir, notes)
        new_content = _patch_skills(new_content, project_dir, notes)
        new_content = _patch_last_updated(new_content, notes)
        # Project-specific infrastructure (docker/systemd) must never be patched
        # into the global ~/.claude/CLAUDE.md — it leaks one project's service
        # status into every other project's context.
        if not is_global:
            new_content = _patch_docker(new_content, notes)
            new_content = _patch_systemd(new_content, project_dir, notes)
        if new_content != content:
            claude_md.write_text(new_content)
        records = [
            RegenRecord(ArtifactKind.CLAUDE_MD_SECTION, claude_md, status, marker_id, shape,
                        None if fence_line is None else str(fence_line))
            for marker_id, status, shape, fence_line in notes
        ]
        break
    return records
