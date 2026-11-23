"""A blocking site is named by its key, not its line (sites.name_sites).

test_no_dead_end.py's tables (sites per class, the G sites and the replays that clear them) name each site by
its key: file, function, kind and the longest piece of its message. An edit that only moves lines (an empty
line near the top of the hook) names every site as before; a new refusal is one new key, beside the others
unchanged; two refusals of one function with the same message are told apart by #2. A throwaway hook in a
tree of its own, registered at PreToolUse; no replay.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.replay import sites

HOOK = '''import json, sys


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") == "Bash":
        sys.stderr.write("Refused: the first rule of the toy hook names its own release.\\n")
        sys.exit(2)
    if data.get("tool_name") == "Write":
        sys.stderr.write("Refused: the same message twice in one function.\\n")
        sys.exit(2)
    if data.get("tool_name") == "Edit":
        sys.stderr.write("Refused: the same message twice in one function.\\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
'''
NEW = '''    if data.get("tool_name") == "Read":
        sys.stderr.write("Refused: a new rule added at the top of main.\\n")
        sys.exit(2)
'''
HOOK_FILE = "hooks/h.py"


def _catalogue(tree: Path, source: str) -> dict[str, int]:
    (tree / "hooks").mkdir(exist_ok=True)
    (tree / HOOK_FILE).write_text(source)
    cmd = {"type": "command", "command": f'python3 "${{CLAUDE_HOME:-$HOME/.claude}}/{HOOK_FILE}"'}
    (tree / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [cmd]}]}}))
    found = sites.Enumerator(str(tree)).sites()
    assert len({s.key for s in found}) == len(found), [s.key for s in found]
    return {s.key: s.line for s in found}


def test_an_edit_that_only_moves_lines_keeps_every_key(tmp_path):
    before = _catalogue(tmp_path, HOOK)
    after = _catalogue(tmp_path, "\n" + HOOK)
    assert len(before) == 3, before
    assert set(after) == set(before), (before, after)
    assert all(after[k] == before[k] + 1 for k in before), (before, after)


def test_a_new_refusal_is_one_new_key(tmp_path):
    before = _catalogue(tmp_path, HOOK)
    head, tail = HOOK.split('    if data.get("tool_name") == "Bash":\n', 1)
    after = _catalogue(tmp_path, head + NEW + '    if data.get("tool_name") == "Bash":\n' + tail)
    new = set(after) - set(before)
    assert set(before) <= set(after) and len(new) == 1, (before, after)
    assert "a new rule added at the top of main" in new.pop()


def test_one_message_twice_in_one_function_is_numbered(tmp_path):
    lines = _catalogue(tmp_path, HOOK)
    keys = sorted(lines, key=lines.get)
    assert keys[2] == keys[1] + " #2", keys
    assert f"{HOOK_FILE} main() exit2 " in keys[0], keys
