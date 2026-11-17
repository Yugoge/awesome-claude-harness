"""An except over presence tests alone decides on an unreadable path, not on a removal (check.py).

Every form _PRESENCE_TEST matches answers False on a removed file or parent (ENOENT, ENOTDIR) and
raises nothing then: CPython 3.10/3.12 Lib/pathlib.py `_ignore_error` (Path.exists, is_file,
is_symlink), Lib/genericpath.py and Lib/posixpath.py (os.path.exists, isfile, lexists, islink),
Modules/posixmodule.c os_access_impl (os.access returns `!result` and never raises on the call's
errno); `test -X` raises nothing. An except around them catches only a fault that leaves the file
in place unread (a permission, a name too long, an I/O error): the record keeps that decision under
its own fault class, 'unreadable', and rule (4)'s 'removed' and 'any' counting does not take it.
A branch on a presence test still decides on the removal, and an except on a content read on any
mutation.
"""

from __future__ import annotations

from tests.artifact_graph import check as C
from tests.artifact_graph.test_check import check, hook, make_tree, rules_on

REC = "<state>/claude-rec-<sid>.json"

_LIB = '''
    from pathlib import Path
    from lib.harness_state_dir import harness_state_dir
    def present(sid):
        p = Path(harness_state_dir(), f"claude-rec-{sid}.json")
        if not p.exists():
            return None
        try:
            return p.read_text()
        except (OSError, ValueError):
            return None
'''
_WRITER = hook('open(harness_state_dir() + "/claude-rec-x.json", "w").write("{}")\n')
_OWN_RULE = hook('''
    import json
    d = json.load(sys.stdin)
    try:
        json.loads(open(harness_state_dir() + "/claude-rec-" + d["session_id"] + ".json").read())
    except ValueError:
        sys.exit(2)
''')
_EXCEPT_OVER_PRESENCE = hook('''
    import json
    from lib.rec import present
    d = json.load(sys.stdin)
    try:
        present(d["session_id"])
    except Exception:
        sys.exit(2)
''')
_BRANCH_ON_PRESENCE = hook('''
    import json
    from pathlib import Path
    d = json.load(sys.stdin)
    if not Path(harness_state_dir(), "claude-rec-" + d["session_id"] + ".json").exists():
        sys.exit(2)
''')
_EXCEPT_ON_CONTENT = hook('''
    import json
    d = json.load(sys.stdin)
    try:
        open(harness_state_dir() + "/claude-rec-" + d["session_id"] + ".json").read()
    except OSError:
        sys.exit(2)
''')


def _hows(tmp_path, b: str) -> tuple:
    root = make_tree(tmp_path, {"hooks/lib/rec.py": _LIB, "hooks/w.py": _WRITER,
                                "hooks/a.py": _OWN_RULE, "hooks/b.py": b})
    m, vs = check(root)
    return m, vs, {d.how for d in m.artifacts[REC].decisions if d.who == "hooks/b.py"}


def test_an_except_over_presence_tests_alone_is_an_unreadable_fault_not_a_removal(tmp_path):
    """b.py's `except Exception: sys.exit(2)` reaches only through present()'s Path.exists():
    the decision is kept, tagged 'unreadable', in the records and in the check's output, and
    rule (4) no longer counts it as a second rule on the removal beside a.py's."""
    m, vs, hows = _hows(tmp_path, _EXCEPT_OVER_PRESENCE)
    assert hows == {"unreadable"}
    deciding = [ln for ln in C.map_text(m, vs).splitlines() if ln.startswith("deciding: ")]
    assert any("hooks/b.py at " in ln for ln in deciding), deciding
    assert "4-one-rule" not in rules_on(vs, REC)


def test_a_branch_on_a_presence_test_still_decides_on_the_removal(tmp_path):
    m, vs, hows = _hows(tmp_path, _BRANCH_ON_PRESENCE)
    assert hows == {"removed"}
    assert "4-one-rule" in rules_on(vs, REC)


def test_an_except_on_a_content_read_still_decides_on_any_mutation(tmp_path):
    m, vs, hows = _hows(tmp_path, _EXCEPT_ON_CONTENT)
    assert hows == {"any"}
    assert "4-one-rule" in rules_on(vs, REC)
