#!/usr/bin/env python3
"""
PostToolUse Hook: Validate .claude/commands/*.md frontmatter structure.

Checks format only:
1. Must start with opening "---"
2. Must have closing "---"
3. Must have "description" field

Hook type: PostToolUse (Write|Edit|NotebookEdit|MultiEdit matcher): it runs
after the write, so an invalid file stays written.
Exit code: 0. An invalid file's errors go to the model, which wrote it and can fix it, as
PostToolUse additionalContext JSON on stdout (the write cannot be undone; a non-zero
status other than 2 would show them to the user alone, and the check is advice, not a gate).
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib")); import harness_switch; sys.path.pop(0)  # noqa: E402,E702
harness_switch.exit_if_off()

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
    lines = [f'INVALID: {basename} was written with invalid command frontmatter; fix the file:']
    lines += [f'  - {e}' for e in errors]
    lines += ['', 'Command files must start with "---", have a closing "---", and include a "description" field.']
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                             "additionalContext": "\n".join(lines)}}))
    sys.exit(0)


if __name__ == '__main__':
    main()
