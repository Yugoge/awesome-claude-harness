"""What an existence test raises, per fault (pyscan._read_errors).

CPython 3.10 and 3.12 (the CI versions): os.path.exists/isfile/isdir/lexists catch every OSError
and ValueError and answer False (Lib/genericpath.py, Lib/posixpath.py), so they raise nothing
under any fault, a removed file included. pathlib.Path.exists/is_file/is_dir answer False only
for ENOENT, ENOTDIR, EBADF and ELOOP (a removed file or parent) and ValueError, and re-raise
every other OSError (Lib/pathlib.py `_ignore_error`), so an except clause around them still
decides on an unreadable path (EACCES, ENAMETOOLONG, EIO).
"""

from __future__ import annotations

import ast

from tests.artifact_graph import pyscan
from tests.artifact_graph.test_check import check, hook, make_tree

REC = "<state>/claude-rec-<sid>.json"

_LIB = '''
    import os
    from pathlib import Path
    from lib.harness_state_dir import harness_state_dir
    def present(sid):
        p = Path(harness_state_dir(), f"claude-rec-{sid}.json")
        if not {test}:
            return None
        try:
            return p.read_text()
        except (OSError, ValueError):
            return None
'''
_OWN_RULE = hook('''
    import json
    d = json.load(sys.stdin)
    try:
        json.loads(open(harness_state_dir() + "/claude-rec-" + d["session_id"] + ".json").read())
    except ValueError:
        sys.exit(2)
''')
_CALLER = hook('''
    import json
    from lib.rec import present
    d = json.load(sys.stdin)
    try:
        present(d["session_id"])
    except Exception:
        sys.exit(2)
''')
_OS_PATH = "os.path.{fn}(p)"
_PATHLIB = "p.{fn}()"


def _deciders(tmp_path, test: str) -> set:
    root = make_tree(tmp_path, {
        "hooks/lib/rec.py": _LIB.replace("{test}", test),
        "hooks/w.py": hook('open(harness_state_dir() + "/claude-rec-x.json", "w").write("{}")\n'),
        "hooks/a.py": _OWN_RULE,
        "hooks/b.py": _CALLER,
    })
    m, _ = check(root)
    return {d.who for d in m.artifacts[REC].decisions}


def test_an_os_path_existence_test_raises_nothing_so_no_outer_except_decides_on_it(tmp_path):
    """os.path.exists/isfile/isdir/lexists swallow every OSError and ValueError: a removed file
    (and any other fault) answers False. `present` tests the record's existence outside its try
    and reads it inside one that swallows the read's errors, so b.py's `except Exception:
    sys.exit(2)` around the call does not decide on the record (the shape of
    contract_runtime.validate_report_artifact under resolve-dev-artifact-chain's main)."""
    for fn in ("exists", "isfile", "isdir", "lexists"):
        assert "hooks/b.py" not in _deciders(tmp_path / fn, _OS_PATH.format(fn=fn)), fn


def test_a_pathlib_existence_test_under_a_non_removal_fault_still_reaches_the_except(tmp_path):
    """The counter-case: Path.exists/is_file/is_dir re-raise an OSError that is not a removal
    (a permission error, a name too long), so the outer except clause keeps deciding on the
    record: the unreadable case is not hidden."""
    for fn in ("exists", "is_file", "is_dir"):
        assert "hooks/b.py" in _deciders(tmp_path / fn, _PATHLIB.format(fn=fn)), fn


def test_what_an_existence_test_raises_at_its_own_call():
    """os.path's tests raise nothing; pathlib's raise the I/O error of a fault that is not a
    removal; a stat raises it under every fault, a removal included."""
    call = ast.parse("f(x)", mode="eval").body
    for via in ("os.path.exists", "os.path.isfile", "os.path.isdir", "os.path.lexists"):
        assert pyscan._read_errors("name", via, call) == frozenset(), via
    for via in ("Path.exists", "Path.is_file", "Path.is_dir", "os.stat", "Path.stat"):
        assert pyscan._read_errors("name", via, call) == frozenset({"OSError"}), via
