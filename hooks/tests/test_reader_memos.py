"""What a hook reads once per process says what reading it each time said (P1b FX1).

A hook that reads every dispatch of a long session asks for the same roster and
the same command file at each one. lib/roster.py remembers a directory's roster
until the directory changes; lib/dispatch_template.py parses a command file's
fences once per text and skips, without compiling it, a template line no prompt
line can match. Each answer here is held to the reading it replaces.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]
REPO = HOOKS.parent
sys.path.insert(0, str(REPO))
from hooks.lib import dispatch_template, roster  # noqa: E402


def _read_roster(directory):
    """The roster rule, read afresh: stems of *.md files whose first line is ---."""
    found = set()
    for path in Path(directory).glob("*.md"):
        try:
            first = path.read_text(encoding="utf-8").splitlines()[:1]
        except (OSError, UnicodeDecodeError):
            continue
        if first == ["---"]:
            found.add(path.stem)
    return frozenset(found)


def test_the_remembered_roster_follows_every_added_removed_or_renamed_file(tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "ba.md").write_text("---\nname: ba\n---\n", encoding="utf-8")
    (agents / "README.md").write_text("# agents\n", encoding="utf-8")
    assert roster.roles(agents) == _read_roster(agents) == {"ba"}
    steps = [
        lambda: (agents / "qa.md").write_text("---\nname: qa\n---\n", encoding="utf-8"),
        lambda: (agents / "notes.md").write_text("no front matter\n", encoding="utf-8"),
        lambda: (agents / "qa.md").rename(agents / "pm.md"),
        lambda: (agents / "ba.md").unlink(),
        lambda: (agents / "dev.txt").write_text("---\n", encoding="utf-8"),
        lambda: (agents / "dev.md").write_text("---\r\nname: dev\r\n", encoding="utf-8"),
    ]
    for step in steps:  # however soon after the read before it: a coarse mtime need not move
        step()
        assert roster.roles(agents) == _read_roster(agents)
        assert roster.roles(str(agents)) == _read_roster(agents)
    assert roster.roles(agents) == {"pm", "dev"}


def test_a_missing_or_unlistable_directory_is_read_each_time_and_never_remembered(tmp_path):
    missing = tmp_path / "missing"
    assert roster.roles(missing) == frozenset()
    assert os.path.abspath(missing) not in roster._SEEN
    missing.mkdir()
    (missing / "ba.md").write_text("---\n", encoding="utf-8")
    assert roster.roles(missing) == {"ba"}


def test_the_harness_rosters_are_the_files_read_afresh():
    for directory in (REPO / "agents", REPO / "commands"):
        assert roster.roles(directory) == roster.roles(directory) == _read_roster(directory)
    assert roster.roles() == _read_roster(REPO / "agents")


_PLACEHOLDER = re.compile(r"<([A-Za-z][A-Za-z0-9_-]*)>")


def _matched_by_pattern(template: str, prompt: str):
    """The template lines some prompt line matches, each placeholder standing
    for one or more characters, every line tried with its full pattern."""
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    found = []
    for raw in template.splitlines():
        text = raw.strip()
        if not re.search(r"\w", _PLACEHOLDER.sub("", text)):
            continue
        names, parts, pos = [], [], 0
        for i, m in enumerate(_PLACEHOLDER.finditer(text)):
            parts.append(re.escape(text[pos:m.start()]) + f"(?P<g{i}>.+?)")
            names.append(m.group(1))
            pos = m.end()
        pattern = re.compile("^" + "".join(parts) + re.escape(text[pos:]) + "$")
        for line in lines:
            match = pattern.match(line)
            if match:
                found.append([(name, match.group(f"g{i}").strip()) for i, name in enumerate(names)])
                break
    return found


def _prompts(bodies):
    """Prompts a dispatch could carry: each template filled in, cut in half,
    and with its lines decorated so their ends no longer meet the template's."""
    out = []
    for n, body in enumerate(bodies):
        filled = _PLACEHOLDER.sub(lambda m: f"v{n}-{m.group(1)}", body)
        lines = filled.splitlines()
        out += [filled, "\n".join(lines[: len(lines) // 2]),
                "\n".join(f"> {line} <" for line in lines), "\n".join(lines[::-1])]
    return out


def test_template_lines_skipped_uncompiled_are_lines_no_prompt_line_matches():
    commands = sorted((REPO / "commands").glob("*.md"))
    checked = 0
    for path in commands:
        text = path.read_text(encoding="utf-8")
        fences = tuple(dispatch_template._fences(text))
        assert dispatch_template._parsed_fences(text) == fences
        assert dispatch_template._parsed_fences(text) is dispatch_template._parsed_fences(text)
        bodies = [fence[0] for fence in fences if fence[4] is not None or _PLACEHOLDER.search(fence[0])]
        for prompt in _prompts(bodies):
            for body in bodies:
                assert dispatch_template._matched_lines(body, prompt) == _matched_by_pattern(body, prompt), path.name
                checked += 1
    assert checked > 100
