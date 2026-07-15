#!/usr/bin/env python3
"""CLAUDE.md auto-creation and patching."""

from datetime import datetime, timezone
from pathlib import Path

# A CLAUDE.md that already leads with an AUTO-managed block is a doc-sync-managed
# file whose header is intentional; treat '<!-- AUTO:' as a valid header marker so
# the legacy '# CLAUDE.md' preamble is not re-prepended above a deduped single H1.
CLAUDE_HEADER_MARKERS = ['---', '# CLAUDE.md', '> Project-specific settings', '<!-- AUTO:']


def has_claude_header(content: str) -> bool:
    lines = content.strip().split('\n')
    return any(any(m in line for m in CLAUDE_HEADER_MARKERS) for line in lines[:5])


def ensure_claude_md(project_dir: Path):
    """Ensure CLAUDE.md exists with proper header. Never overwrites existing content."""
    claude_md = project_dir / 'CLAUDE.md'
    if claude_md.exists():
        content = claude_md.read_text()
        if not has_claude_header(content):
            ts = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            header = f'# CLAUDE.md\n\n> Project-specific settings for {project_dir.name}\n> Last updated: {ts}\n\n---\n\n'
            claude_md.write_text(header + content)
        return
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    template = f'# CLAUDE.md\n\n> Project-specific settings for {project_dir.name}\n> Last updated: {ts}\n\n---\n\n<!-- AUTO:claude-inventory -->\n<!-- /AUTO:claude-inventory -->\n'
    claude_md.write_text(template)
