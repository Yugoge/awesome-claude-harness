"""A site whose message reads a module-level constant carries that constant's strings (sites.PyModule.named_text).

A refusal whose text lives in a module-level name (a string, or a dict, tuple or list of strings
looked up at the call) prints no string constant at the call, so the site's message pieces are the
constant's strings, and match() maps the refusal to that site. A name the function binds itself, a
constant read only as a membership operand, and a name bound twice at module level are not
credited. A throwaway hook in a tree of its own, registered at PreToolUse; no replay.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.replay import sites

HOOK = '''
import json, sys

PLAIN = "Refused by the plain module constant: decide and record it."
BY_ROLE = {  # looked up at the call, as hooks/pretool-overnight-hook-guard.py's _UNATTENDED_DENY is
    False: "Refused for the main agent: the dict constant's first message.",
    True: "Refused for a subagent: the dict constant's second message.",
}
PAIR = ("Refused by the tuple constant's first message.", "Refused by the tuple constant's second message.")
TEMPLATE = "Refused by the template constant for tool {}."
LISTED = ("a listed tool name that is long", "another listed tool name, long too")
NOTE = "The module's note, which the function below shadows."
TWICE = "The first binding of a name bound twice."
TWICE = "The second binding of a name bound twice."


def _block(message):
    sys.stderr.write(message)
    sys.exit(2)


def shadowed(data):
    NOTE = data.get("note") or ""
    if data.get("e"):
        _block(NOTE)  # site shadowed


def main():
    data = json.load(sys.stdin)
    if data.get("a"):
        _block(PLAIN)  # site plain
    if data.get("b"):
        _block(BY_ROLE[bool(data.get("agent_id"))] + "\\n")  # site dict
    if data.get("c"):
        _block(PAIR[1] if data.get("x") else PAIR[0])  # site tuple
    if data.get("d"):
        _block(TEMPLATE.format(data.get("tool_name")))  # site template
    if data.get("f"):
        _block(f"Refused, the tool is listed: {data.get('tool_name') in LISTED}")  # site membership
    if data.get("g"):
        _block(TWICE)  # site twice
    shadowed(data)


if __name__ == "__main__":
    main()
'''

HOOK_FILE = "hooks/h.py"
CREDITED = {
    "plain": ["Refused by the plain module constant: decide and record it."],
    "dict": ["Refused for the main agent: the dict constant's first message.",
             "Refused for a subagent: the dict constant's second message."],
    "tuple": ["Refused by the tuple constant's first message.", "Refused by the tuple constant's second message."],
    "template": ["Refused by the template constant for tool {}."],
    "membership": [],
    "twice": [],
    "shadowed": [],
}
CONSTANTS = [t for ts in CREDITED.values() for t in ts] + [
    "a listed tool name that is long", "another listed tool name, long too",
    "The module's note, which the function below shadows.",
    "The first binding of a name bound twice.", "The second binding of a name bound twice."]


def _found(tmp_path: Path) -> tuple[dict, list]:
    (tmp_path / "hooks").mkdir()
    (tmp_path / HOOK_FILE).write_text(HOOK)
    cmd = {"type": "command", "command": f'python3 "${{CLAUDE_HOME:-$HOME/.claude}}/{HOOK_FILE}"'}
    settings = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [cmd]}]}}
    (tmp_path / "settings.json").write_text(json.dumps(settings))
    lines = HOOK.splitlines()
    marks = {i: ln.split("# site ", 1)[1] for i, ln in enumerate(lines, 1) if "# site " in ln}
    found = sites.Enumerator(str(tmp_path)).sites()
    assert {s.line for s in found} == set(marks), [(s.line, s.func, s.kind) for s in found]
    return {marks[s.line]: s for s in found}, found


def test_a_message_read_from_a_module_constant_carries_its_strings(tmp_path):
    by_mark, _found_sites = _found(tmp_path)
    got = {m: [t for t in s.text if t in CONSTANTS] for m, s in by_mark.items()}
    assert got == CREDITED, got


def test_a_refusal_whose_text_is_a_module_constant_maps_to_its_site(tmp_path):
    by_mark, found = _found(tmp_path)
    for mark, refusal in [("plain", CREDITED["plain"][0] + "\n"),
                          ("dict", CREDITED["dict"][0] + "\n"), ("dict", CREDITED["dict"][1] + "\n"),
                          ("tuple", CREDITED["tuple"][1]),
                          ("template", "Refused by the template constant for tool Bash.")]:
        assert sites.match(HOOK_FILE, refusal, found) == [by_mark[mark]], (mark, refusal)
