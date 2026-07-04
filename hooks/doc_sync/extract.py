#!/usr/bin/env python3
"""Extract description from various file types."""

import json
from pathlib import Path

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# Known-file descriptions for files whose content cannot be introspected
# reliably via generic key scanning (e.g. no title/name key at top level).
_KNOWN_FILE_DESCRIPTIONS: dict[str, str] = {
    'settings.json': 'Claude Code harness configuration (permissions, hooks, env, model)',
    'settings.template.json': 'Distributable harness settings template (uses CLAUDE_HOME placeholders)',
    'requirements.txt': 'Python dependency manifest for the Claude Code harness venv',
}


def extract_description(file_path: Path) -> str:
    # Known-file lookup takes priority over all suffix-based logic.
    known = _KNOWN_FILE_DESCRIPTIONS.get(file_path.name)
    if known:
        return known
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
        return _extract_json_yaml_desc(text, suffix)
    # AC-WS5-2: never emit the placeholder "unknown file". Derive a meaningful
    # description from the file: its suffix if it has one (e.g. "toml file"),
    # otherwise the file's own stem so the entry is self-describing.
    if suffix:
        return f'{suffix.lstrip(".")} file'
    return f'{file_path.stem} file'


def _extract_json_yaml_desc(text: str, suffix: str) -> str:
    """Introspect JSON/YAML content for title/name/description key."""
    # Priority order: description (most specific) > title > name.
    _PRIORITY_KEYS = ('description', 'title', 'name')
    try:
        if suffix == '.json':
            data = json.loads(text)
            if isinstance(data, dict):
                for key in _PRIORITY_KEYS:
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
                # Fall back to comma-delimited summary of first 5 top-level keys.
                keys = list(data.keys())[:5]
                if keys:
                    return f"JSON config: {', '.join(keys)}"
        else:
            if _YAML_AVAILABLE:
                data = _yaml.safe_load(text)
            else:
                # Minimal line-scan fallback when PyYAML not installed.
                data = _yaml_line_scan(text)
            if isinstance(data, dict):
                for key in _PRIORITY_KEYS:
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
                keys = list(data.keys())[:5]
                if keys:
                    return f"YAML config: {', '.join(str(k) for k in keys)}"
    except Exception:
        pass
    return f'{suffix.lstrip(".")} config'


def _yaml_line_scan(text: str) -> dict:
    """Minimal YAML top-level key scanner (no PyYAML dependency)."""
    result: dict = {}
    for line in text.split('\n'):
        if line.startswith('---') or line.startswith('#') or not line.strip():
            continue
        if ':' in line and not line.startswith(' ') and not line.startswith('\t'):
            key, _, val = line.partition(':')
            result[key.strip()] = val.strip()
    return result


def _parse_frontmatter(text: str) -> str | None:
    """Extract description from markdown frontmatter."""
    if not text.startswith('---'):
        return None
    end = text.find('---', 3)
    if end == -1:
        return None
    fm = text[3:end]
    # Prefer PyYAML when available — handles folded scalars, quoted strings, etc.
    if _YAML_AVAILABLE:
        try:
            data = _yaml.safe_load(fm)
            if isinstance(data, dict):
                val = data.get('description')
                if isinstance(val, str) and val.strip():
                    # YAML normalizes folded block scalars; collapse remaining newlines.
                    return ' '.join(val.split())
        except Exception:
            pass  # Fall through to manual scanner.
    # Manual scanner fallback (no PyYAML or YAML parse failed).
    lines = fm.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith('description:'):
            continue
        inline = line.split(':', 1)[1].strip().strip('"').strip("'")
        # Handle YAML block scalar indicators (>- and >) by collecting indented lines.
        if inline in ('>', '>-', '|', '|-'):
            # Collect subsequent indented continuation lines.
            parts = []
            for continuation in lines[i + 1:]:
                if continuation and (continuation[0] == ' ' or continuation[0] == '\t'):
                    parts.append(continuation.strip())
                else:
                    break
            if parts:
                return ' '.join(parts)
        elif inline:
            return inline
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
    import re as _re
    # Encoding cookie: # -*- coding: ... -*- or # coding: ...
    _encoding_re = _re.compile(r'^#.*coding[:=]\s*[-\w.]+')
    lines = text.split('\n')
    first_comment: str | None = None  # fallback if no docstring found
    for i, line in enumerate(lines):
        if i >= 30:
            break
        s = line.strip()
        # Stop scanning once we hit class/def/import — module-level docstrings
        # must precede all imports; a string after imports is not a module docstring.
        if s.startswith(('class ', 'def ', 'async def ', 'import ', 'from ')):
            break
        # Single-line inline docstring: """doc text"""
        doc = _check_single_line_docstring(s)
        if doc:
            return doc
        # Multi-line docstring opening — collect first non-empty line.
        if s.startswith('"""') or s.startswith("'''"):
            content = _find_next_line_content(lines, i + 1, 10)
            if content:
                return content
        # Informative comment: skip shebang, encoding cookies, and bare separators.
        # Save as fallback only (docstring takes priority when appearing later).
        if s.startswith('#') and not s.startswith('#!') and not _encoding_re.match(s):
            text_part = s.lstrip('# ').strip()
            if text_part and first_comment is None:
                first_comment = text_part
    if first_comment:
        return first_comment
    return 'Python script'


def _extract_sh_desc(text: str) -> str:
    import re as _re
    # Separator pattern: lines like # ====, # ----, # ....  (all non-alphanumeric after #)
    _sep_re = _re.compile(r'^#+\s*[^a-zA-Z0-9]*$')
    for line in text.split('\n'):
        s = line.strip()
        if s.startswith('#!'):
            # Shebang line — skip.
            continue
        if s.startswith('#'):
            # Skip bare separator lines (e.g. # ===========, # ---------, bare #).
            if _sep_re.match(s):
                continue
            text_part = s.lstrip('# ').strip()
            if text_part:
                return text_part
        elif s:
            # Reached non-comment, non-empty code line without finding a description.
            break
    return 'Shell script'
