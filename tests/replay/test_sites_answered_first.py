"""A site's registrations are those whose event can run it (sites.answered_first, Enumerator.at_event).

A hook that answers an event first and leaves (an else-less `if` on the payload's hook_event_name
ending in an exit) runs nothing after that `if` at the event, so the sites after it, and those of
the functions only the code after it calls, carry the hook's other registrations only. Each case is
a throwaway hook in a tree of its own, registered at SessionStart and UserPromptSubmit; no replay.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from tests.replay import sites

BOTH = ["SessionStart", "UserPromptSubmit"]
PROMPT = ["UserPromptSubmit"]

# Each hook's blocking sites are the lines marked `# site <name>`.
HELPERS = '''
import json, sys


def refuse(data):
    if data.get("x"):
        sys.exit(2)  # site refuse
'''

CASES = {
    # the answer drops SessionStart from what runs after it: main's own site and refuse's, which only
    # that code calls; the `["hook_event_name"]` and `in (...)` spellings count as `.get(...) ==`
    "answered and left": ('''
def main():
    data = json.loads(sys.stdin.read())
    if data.get("hook_event_name") == "SessionStart":
        print("{}")
        sys.exit(0)
    if data.get("z"):
        sys.exit(2)  # site after
    refuse(data)
''', {"after": PROMPT, "refuse": PROMPT}),
    "answered by subscript, in a tuple": ('''
def main():
    data = json.load(sys.stdin)
    if data["hook_event_name"] in ("SessionStart", "SubagentStart"):
        return
    refuse(data)
''', {"refuse": PROMPT}),
    # a site before the answer runs at every event
    "a site before the answer": ('''
def main():
    data = json.loads(sys.stdin.read())
    if data.get("z"):
        sys.exit(2)  # site before
    if data.get("hook_event_name") == "SessionStart":
        sys.exit(0)
    refuse(data)
''', {"before": BOTH, "refuse": PROMPT}),
    # a function the answer itself calls runs at its event
    "a site called inside the answer": ('''
def answer(data):
    if data.get("y"):
        sys.exit(2)  # site answer


def main():
    data = json.loads(sys.stdin.read())
    if data.get("hook_event_name") == "SessionStart":
        answer(data)
        sys.exit(0)
    answer(data)
    refuse(data)
''', {"answer": BOTH, "refuse": PROMPT}),
    # a test whose block does not leave answers nothing
    "a guard with no exit": ('''
def main():
    data = json.loads(sys.stdin.read())
    if data.get("hook_event_name") == "SessionStart":
        print("{}")
    refuse(data)
''', {"refuse": BOTH}),
    # nor one with an else, which runs at the other events instead
    "a guard with an else": ('''
def main():
    data = json.loads(sys.stdin.read())
    if data.get("hook_event_name") == "SessionStart":
        sys.exit(0)
    else:
        print("{}")
    refuse(data)
''', {"refuse": BOTH}),
    # hook_event_name read from a dict that is not the payload (json.load / json.loads) is no answer
    "a dict that is not the payload": ('''
def main():
    rec = {"hook_event_name": "Stop"}
    data = json.loads(sys.stdin.read())
    if rec.get("hook_event_name") == "SessionStart":
        sys.exit(0)
    refuse(data)
''', {"refuse": BOTH}),
}


def _tree(tmp_path: Path, main: str) -> Path:
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "h.py").write_text(
        HELPERS + textwrap.dedent(main) + '\n\nif __name__ == "__main__":\n    main()\n')
    cmd = {"type": "command", "command": 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/h.py"'}
    (tmp_path / "settings.json").write_text(json.dumps({"hooks": {ev: [{"hooks": [cmd]}] for ev in BOTH}}))
    return tmp_path


def _marked(tree: Path) -> dict[int, str]:
    lines = (tree / "hooks" / "h.py").read_text().splitlines()
    return {i: ln.split("# site ", 1)[1] for i, ln in enumerate(lines, 1) if "# site " in ln}


@pytest.mark.parametrize("case", CASES)
def test_a_sites_events_are_those_that_can_run_it(tmp_path, case):
    main, want = CASES[case]
    tree = _tree(tmp_path, main)
    marks = _marked(tree)
    found = sites.Enumerator(str(tree)).sites()
    assert {s.line for s in found} <= set(marks), [(s.line, s.func, s.kind) for s in found]
    got = {marks[s.line]: sorted(ev for _, ev, _ in s.regs) for s in found}
    assert got == want, got


def test_answered_first_names_the_lines_after_the_answer(tmp_path):
    tree = _tree(tmp_path, CASES["answered and left"][0])
    mod = sites.PyModule(str(tree), "hooks/h.py")
    src = mod.lines
    after = {i for i, ln in enumerate(src, 1) if ln.startswith("    if data.get(\"z\")") or "site after" in ln
             or ln.strip() == "refuse(data)"}
    assert sites.answered_first(mod) == {"SessionStart": {"main": after}}
    reach, skip = sites.Enumerator(str(tree)).at_event("hooks/h.py")["SessionStart"]
    assert skip == {("hooks/h.py", "main"): after}
    assert ("hooks/h.py", "main") in reach and ("hooks/h.py", "refuse") not in reach


def test_a_hook_answering_nothing_has_no_event_paths(tmp_path):
    tree = _tree(tmp_path, CASES["a guard with no exit"][0])
    assert sites.answered_first(sites.PyModule(str(tree), "hooks/h.py")) == {}
    assert sites.Enumerator(str(tree)).at_event("hooks/h.py") == {}
