#!/usr/bin/env python3
"""Extract description from various file types."""

from pathlib import Path


def extract_description(file_path: Path) -> str:
    try:
        text = file_path.read_text(errors='replace')
    except Exception:
        return 'Unreadable'
    suffix = file_path.suffix
    if suffix == '.md':
        return _extract_md_desc(text, file_path)
    if suffix == '.py':
        return _extract_py_desc(text)
    if suffix in ('.sh', '.bash'):
        return _extract_sh_desc(text)
    if suffix in ('.json', '.yaml', '.yml'):
        return f'{suffix.lstrip(".")} config'
    # AC-WS5-2: never emit the placeholder "unknown file". Derive a meaningful
    # description from the file: its suffix if it has one (e.g. "toml file"),
    # otherwise the file's own stem so the entry is self-describing.
    if suffix:
        return f'{suffix.lstrip(".")} file'
    return f'{file_path.stem} file'


def _parse_frontmatter(text: str) -> str | None:
    """Extract description from markdown frontmatter."""
    if not text.startswith('---'):
        return None
    end = text.find('---', 3)
    if end == -1:
        return None
    fm = text[3:end]
    for line in fm.split('\n'):
        stripped = line.strip()
        if not stripped.startswith('description:'):
            continue
        desc = line.split(':', 1)[1].strip().strip('"').strip("'")
        if desc:
            return desc
    return None


def _extract_md_desc(text: str, file_path: Path | None = None) -> str:
    desc = _parse_frontmatter(text)
    if desc:
        return desc
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('# '):
            return stripped[2:].strip()
    # AC-WS5-2: never emit the placeholder "No description" for a published file.
    # Fall back to the document's own name so the list item is self-describing.
    if file_path is not None:
        return f'{file_path.stem} document'
    return 'Markdown document'


def _check_single_line_docstring(s: str) -> str | None:
    """Check if line has inline docstring on single line."""
    quote = s[:3]
    if quote not in ('"""', "'''"):
        return None
    if s.count(quote) < 2 or len(s) <= 6:
        return None
    start = s.index(quote) + 3
    end = s.index(quote, start)
    return s[start:end].strip()


def _find_next_line_content(lines: list[str], start_i: int, max_lines: int) -> str | None:
    """Find first non-empty line content after docstring start."""
    end_i = min(start_i + max_lines, len(lines))
    for j in range(start_i, end_i):
        ds = lines[j].strip()
        if ds:
            return ds.rstrip('.') if len(ds) < 100 else ds[:97] + '...'
    return None


def _extract_py_desc(text: str) -> str:
    lines = text.split('\n')
    for i, line in enumerate(lines):
        s = line.strip()
        doc = _check_single_line_docstring(s)
        if doc:
            return doc
        if s.startswith('#') and not s.startswith('#!') and i < 5:
            return s.lstrip('# ').strip()
        if (s.startswith('"""') or s.startswith("'''")) and i < 5:
            content = _find_next_line_content(lines, i + 1, 5)
            if content:
                return content
    return 'Python script'


def _extract_sh_desc(text: str) -> str:
    for line in text.split('\n'):
        s = line.strip()
        if s.startswith('#!'):
            continue
        if s.startswith('#'):
            return s.lstrip('# ').strip()
        if s:
            break
    return 'Shell script'
