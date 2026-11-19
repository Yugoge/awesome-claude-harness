"""The duplicate-definition check (tests/defs_registry) on throwaway git trees, and this tree
held to the register's ceiling.

Each synthetic tree is a scratch git repository holding a few hooks/ and scripts/ files and
a register; nothing outside tmp_path is read or written.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.defs_registry.__main__ import main
from tests.defs_registry.check import REGISTER, RegisterError, fingerprint, load_register, run

REPO = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

FIND = '("-exec", "-execdir", "-ok", "-okdir")'
FIND_SET = ["-exec", "-execdir", "-ok", "-okdir"]


def tree(tmp_path: Path, files: dict, entries: list | None = None) -> Path:
    root = tmp_path / "t"
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    reg = root / REGISTER
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({"version": 1, "entries": entries or []}))
    subprocess.run(["git", "init", "-q", str(root)], check=True, env=ENV)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=ENV)
    return root


def where(root: Path) -> list[list[str]]:
    res = run(root)
    return [[res.defs[i].where for i in g] for g in res.uncovered]


def slot(name, members):
    return {"name": name, "fingerprint": fingerprint(members)}


# ------------------------------------------------------------------ the sameness rule
def test_exact_copy_in_another_file_is_one_group_naming_both(tmp_path):
    root = tree(tmp_path, {"hooks/a.py": f"X = {FIND}\n", "scripts/b.py": f"\n\nY = frozenset({FIND})\n"})
    assert where(root) == [["hooks/a.py:1", "scripts/b.py:3"]]


@pytest.mark.parametrize("other", [
    '("-exec", "-execdir", "-ok")',                       # one member fewer
    '("-exec", "-execdir", "-ok", "-okdir", "-delete")',  # one member more
    '("-exec", "-execdir", "-ok", "-fprint")',            # one member replaced
])
def test_copy_differing_by_one_member_is_found(tmp_path, other):
    root = tree(tmp_path, {"hooks/a.py": f"X = {FIND}\n", "hooks/b.py": f"if w in {other}:\n    pass\n"})
    assert where(root) == [["hooks/a.py:1", "hooks/b.py:1"]]


@pytest.mark.parametrize("a, b", [
    ('("a", "b", "c", "d")', '("a", "b", "c", "x", "y")'),  # two members apart
    ('("a", "b")', '("a", "b", "c")'),                      # one apart, but only two shared
    ('("a", "b", "c")', '("a", "b", "c", "d", "e", "f", "g", "h")'),  # a small table inside a big one
])
def test_unrelated_or_distant_tables_are_not_linked(tmp_path, a, b):
    root = tree(tmp_path, {"hooks/a.py": f"X = {a}\n", "hooks/b.py": f"Y = {b}\n"})
    assert where(root) == []


def test_no_chaining_through_a_shared_table(tmp_path):
    """The first inventory's flaw: a table linked by overlap to two others joined them.
    Here {a b c d} is one member from neither {a b c d e f} nor {a b c d x y}."""
    root = tree(tmp_path, {"hooks/a.py": 'A = ("a", "b", "c", "d")\n'
                                         'B = ("a", "b", "c", "d", "e", "f")\n'
                                         'C = ("a", "b", "c", "d", "x", "y")\n'})
    assert where(root) == []


@pytest.mark.parametrize("rel, text", [
    ("hooks/r.py", 'import re\nRX = re.compile(r"^(?:-exec|-execdir|-ok|-okdir)\\b")\n'),
    ("hooks/r.py", 'import re\nPAT = r"\\s(-exec|-execdir|-ok|-okdir)\\s"\nre.search(PAT, s)\n'),
    ("hooks/r.py", 'if a == "-exec" or a == "-execdir" or a == "-ok" or a == "-okdir":\n    pass\n'),
    ("hooks/r.py", 'if a.startswith(("-exec", "-execdir", "-ok", "-okdir")):\n    pass\n'),
    ("hooks/r.py", 'X = "-exec -execdir -ok -okdir".split()\n'),
    ("hooks/r.sh", '#!/bin/bash\ncase "$w" in\n  -exec|-execdir|-ok|-okdir) echo run ;;\nesac\n'),
    ("hooks/r.sh", '#!/bin/bash\nFIND_RUN=(\n  -exec -execdir\n  -ok -okdir\n)\n'),
    ("hooks/r.sh", '#!/bin/bash\nfor a in -exec -execdir -ok -okdir; do :; done\n'),
    ("hooks/r.sh", '#!/bin/bash\n[[ $w =~ ^(-exec|-execdir|-ok|-okdir)$ ]] && echo run\n'),
    ("scripts/r", '#!/usr/bin/env bash\necho "$c" | grep -qE "(-exec|-execdir|-ok|-okdir)"\n'),
])
def test_every_shape_is_compared_with_every_other(tmp_path, rel, text):
    root = tree(tmp_path, {"hooks/a.py": f"X = {FIND}\n", rel: text})
    groups = where(root)
    assert len(groups) == 1 and groups[0][0] == "hooks/a.py:1" and groups[0][1].startswith(rel + ":")


def test_a_scripts_own_option_arms_are_not_facts(tmp_path):
    sh = '#!/bin/bash\nwhile [ $# -gt 0 ]; do\n  case "$1" in\n    -h|--help) usage ;;\n  esac\ndone\n'
    root = tree(tmp_path, {"scripts/one.sh": sh, "scripts/two.sh": sh})
    assert where(root) == []


def test_test_files_are_not_read(tmp_path):
    root = tree(tmp_path, {"hooks/a.py": f"X = {FIND}\n", "hooks/tests/test_a.py": f"Y = {FIND}\n"})
    assert where(root) == []


# ------------------------------------------------------------------ the register
def lookalike(sides, reason="one is what the guard refuses, the other what the linter reads"):
    return [{"id": "e", "reason": reason, "sides": sides}]


def test_registered_lookalikes_pass_and_a_new_copy_fails(tmp_path):
    files = {"hooks/a.py": f"X = {FIND}\n", "hooks/b.py": "Y = (\"-exec\", \"-execdir\", \"-ok\")\n"}
    entries = lookalike([[slot("<module>.X", FIND_SET)], [slot("<module>.Y", FIND_SET[:3])]])
    root = tree(tmp_path, files, entries)
    assert where(root) == []
    (root / "hooks/c.py").write_text(f"def f(w):\n    return w in {FIND}\n")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=ENV)
    assert where(root) == [["hooks/a.py:1", "hooks/b.py:1", "hooks/c.py:2"]]


def test_two_copies_on_one_side_still_fail(tmp_path):
    files = {"hooks/a.py": f"X = {FIND}\n", "hooks/b.py": f"X = {FIND}\n"}
    entries = [{"id": "e", "reason": "the same table registered twice on one side",
                "sides": [[slot("<module>.X", FIND_SET), slot("<module>.X", FIND_SET)],
                          [slot("<module>.Z", ["p", "q"])]]}]
    assert where(tree(tmp_path, files, entries)) == [["hooks/a.py:1", "hooks/b.py:1"]]


def test_a_registered_definition_may_move(tmp_path):
    entries = lookalike([[slot("<module>.X", FIND_SET)], [slot("<module>.Y", FIND_SET)]])
    root = tree(tmp_path, {"hooks/a.py": f"X = {FIND}\n", "hooks/b.py": f"Y = {FIND}\n"}, entries)
    assert where(root) == []
    (root / "hooks/a.py").unlink()
    (root / "scripts").mkdir()
    (root / "scripts/moved.py").write_text(f"import os\n\n\nX = {FIND}\n")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=ENV)
    assert where(root) == []


@pytest.mark.parametrize("reason", [None, "", "   ", "because"])
def test_an_entry_without_a_reason_is_refused(tmp_path, reason):
    entries = lookalike([[slot("<module>.X", FIND_SET)], [slot("<module>.Y", FIND_SET)]], reason)
    if reason is None:
        del entries[0]["reason"]
    root = tree(tmp_path, {"hooks/a.py": f"X = {FIND}\n", "hooks/b.py": f"Y = {FIND}\n"}, entries)
    with pytest.raises(RegisterError, match="no reason"):
        run(root)
    assert main(["--tree", str(root)]) == 2


def test_command_exit_status_and_count(tmp_path, capsys):
    root = tree(tmp_path, {"hooks/a.py": f"X = {FIND}\n", "hooks/b.py": f"Y = {FIND}\n",
                           "hooks/c.py": 'Z = ("p", "q")\nW = ("p", "q")\n'})
    assert main(["--tree", str(root), "--count"]) == 1
    assert capsys.readouterr().out == "2\n"
    assert main(["--tree", str(root)]) == 1
    out = capsys.readouterr().out
    assert "hooks/a.py:1" in out and "hooks/b.py:1" in out and "uncovered groups: 2" in out
    clean = tree(tmp_path / "clean", {"hooks/a.py": f"X = {FIND}\n"})
    assert main(["--tree", str(clean), "--count"]) == 0


# ------------------------------------------------------------------ this tree
def test_this_register_is_valid():
    reg = load_register(REPO / REGISTER)
    assert len(reg["entries"]) >= 61


def test_this_tree_stays_under_the_ceiling():
    """The standing check while the merge lanes work: the number of uncovered groups, and of
    definitions in them, may only fall. A new private copy of a table raises the second
    number even when it joins a group that already exists."""
    ceiling = json.loads((REPO / REGISTER).read_text())["ceiling"]
    res = run(REPO)
    assert not res.errors
    report = "\n".join(res.defs[g[0]].where + " ..." for g in res.uncovered)
    assert len(res.uncovered) <= ceiling["uncovered_groups"], report
    assert res.n_definitions <= ceiling["definitions_in_uncovered_groups"], report


@pytest.mark.skipif(os.environ.get("HARNESS_DEFS_STRICT") != "1",
                    reason="strict once the merge lanes have landed (HARNESS_DEFS_STRICT=1)")
def test_this_tree_has_no_uncovered_group():
    assert main(["--tree", str(REPO)]) == 0
