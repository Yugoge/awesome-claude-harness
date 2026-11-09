#!/usr/bin/env python3
"""
PostToolUse Hook: Validate .claude/commands/*.md frontmatter structure.

Checks format only:
1. Must start with opening "---"
2. Must have closing "---"
3. Must have "description" field

Hook type: PostToolUse (Write|Edit|NotebookEdit|MultiEdit matcher): it runs
after the write, so an invalid file stays written.
Exit codes: 0 = valid or not a command file, 1 = invalid (errors on stderr)
"""

import json
import sys
import re


def get_file_path():
    try:
        data = json.load(sys.stdin)
        tool_input = data.get('tool_input', {})
        return tool_input.get('file_path', '')
    except Exception:
        return ''


def is_command_file(path):
    """Match .claude/commands/something.md but not subdirs like scripts/."""
    return bool(re.search(r'\.claude/commands/[^/]+\.md$', path))


def validate(path):
    basename = path.rsplit('/', 1)[-1]
    if basename in {'INDEX.md', 'README.md'}:
        return True, []

    try:
        with open(path, 'r') as f:
            content = f.read()
    except Exception:
        return True, []

    errors = []

    # Check opening ---
    if not content.startswith('---\n'):
        errors.append('Missing opening "---" delimiter')
        return False, errors

    # Check closing ---
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        errors.append('Missing closing "---" delimiter')
        return False, errors

    # Check description field exists
    fm_text = match.group(1)
    has_description = bool(re.search(r'^description\s*:', fm_text, re.MULTILINE))
    if not has_description:
        errors.append('Missing required field: description')

    return len(errors) == 0, errors


def main():
    path = get_file_path()
    if not path or not is_command_file(path):
        sys.exit(0)

    ok, errors = validate(path)
    if ok:
        sys.exit(0)

    basename = path.rsplit('/', 1)[-1]
    print(f'INVALID: {basename} was written with invalid command frontmatter; fix the file:', file=sys.stderr)
    for e in errors:
        print(f'  - {e}', file=sys.stderr)
    print(f'\nCommand files must start with "---", have a closing "---", and include a "description" field.', file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
