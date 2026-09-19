#!/usr/bin/env python3
"""Patch CLAUDE.md dynamic sections using AUTO markers."""

from datetime import datetime, timezone
from pathlib import Path
from .claude import ensure_claude_md
from .docker import build_docker_table
from .systemd import build_systemd_table


def _is_global_claude_md(claude_md: Path) -> bool:
    """True when the target path resolves to the global ~/.claude/CLAUDE.md."""
    try:
        return claude_md.resolve() == (Path.home() / '.claude' / 'CLAUDE.md').resolve()
    except OSError:
        return False


def _replace_section(content: str, marker_id: str, new_body: str) -> str:
    start = f'<!-- AUTO:{marker_id} -->'
    end = f'<!-- /AUTO:{marker_id} -->'
    s = content.find(start)
    e = content.find(end)
    if s == -1 or e == -1 or e < s:
        return content
    return content[:s + len(start)] + '\n' + new_body + '\n' + content[e:]


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


def _patch_inventory(content: str, project_dir: Path) -> str:
    if '<!-- AUTO:claude-inventory -->' in content:
        return _replace_section(content, 'claude-inventory', _build_inventory(project_dir))
    return content


def _patch_commands(content: str, project_dir: Path) -> str:
    if '<!-- AUTO:command-list -->' in content:
        return _replace_section(content, 'command-list', _build_file_list(project_dir / '.claude' / 'commands'))
    return content


def _patch_agents(content: str, project_dir: Path) -> str:
    if '<!-- AUTO:agent-list -->' in content:
        return _replace_section(content, 'agent-list', _build_file_list(project_dir / '.claude' / 'agents'))
    return content


def _patch_skills(content: str, project_dir: Path) -> str:
    if '<!-- AUTO:skill-list -->' in content:
        sd = project_dir / '.claude' / 'skills'
        if sd.is_dir():
            dirs = sorted([d.name for d in sd.iterdir() if d.is_dir() and not d.name.startswith('.')])
            return _replace_section(content, 'skill-list', '\n'.join(f'- `{d}/`' for d in dirs))
    return content


def _patch_last_updated(content: str) -> str:
    if '<!-- AUTO:last-updated -->' in content:
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        return _replace_section(content, 'last-updated', f'> Last updated: {ts}')
    return content


def _patch_docker(content: str) -> str:
    if '<!-- AUTO:docker-services -->' in content:
        table = build_docker_table()
        if table:
            return _replace_section(content, 'docker-services', table)
    return content


def _patch_systemd(content: str, project_dir: Path) -> str:
    if '<!-- AUTO:systemd-services -->' in content:
        table = build_systemd_table(project_dir)
        if table:
            return _replace_section(content, 'systemd-services', table)
    return content


def patch_claude_md(project_dir: Path):
    """Patch CLAUDE.md dynamic sections using AUTO markers."""
    ensure_claude_md(project_dir)
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
        new_content = _patch_inventory(new_content, project_dir)
        new_content = _patch_commands(new_content, project_dir)
        new_content = _patch_agents(new_content, project_dir)
        new_content = _patch_skills(new_content, project_dir)
        new_content = _patch_last_updated(new_content)
        # Project-specific infrastructure (docker/systemd) must never be patched
        # into the global ~/.claude/CLAUDE.md — it leaks one project's service
        # status into every other project's context.
        if not is_global:
            new_content = _patch_docker(new_content)
            new_content = _patch_systemd(new_content, project_dir)
        if new_content != content:
            claude_md.write_text(new_content)
        break
