"""The replays' shared setup (tests/replay/sandbox.py): one sandbox built per tree, then copied.

A copied sandbox must be the built one as far as a replay can tell: the same
harness snapshot with an index whose stat data matches its files (else the
replay's first git command in the harness re-reads every tracked file), and the
same byte-compiled modules, checked-hash, so a hook's import still reads each
module's source (the trace sees the same reads) without compiling it again.
None of this needs strace or a namespace: the sandbox is reset in mode scratch.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.replay import sandbox

FILES = {
    "settings.json": json.dumps({"env": {}, "hooks": {}}),
    "hooks/lib/__init__.py": "",
    "hooks/lib/mod.py": "VALUE = 1\n",
    "hooks/h.py": "import os, sys\nsys.path.insert(0, os.path.dirname(__file__))\nfrom lib import mod\n",
}


def make_tree(tmp_path: Path, ignore: str | None) -> Path:
    root = tmp_path / "tree"
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    if ignore is not None:
        (root / ".gitignore").write_text(ignore, encoding="utf-8")
    return root


def git(cwd: Path, *args) -> str:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cwd), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


def caches(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*.pyc") if "venv" not in p.relative_to(root).parts)


def test_a_copied_sandbox_is_the_built_one(tmp_path):
    tree = make_tree(tmp_path, "__pycache__/\nvenv/\n")
    tpl, sb = tmp_path / "template", tmp_path / "sb"
    info = sandbox.build(str(tree), str(tpl), log=lambda s: None)
    assert info["bytecode"].endswith("modules, checked-hash"), info["bytecode"]
    stored = caches(tpl / "bytecode")
    assert any(p.startswith("hooks/lib/__pycache__/mod.") for p in stored), stored
    assert caches(tpl / "home" / ".claude") == []      # kept aside: reset() puts them back

    copied = sandbox.clone(str(tpl), str(sb))
    assert copied["snapshot"] == info["snapshot"] and copied["template"] == str(tpl)
    harness = sb / "home" / ".claude"
    # the copy's index matches its files' stat data, as build()'s `git add` left the template's
    assert git(harness, "diff-files", "--name-only") == ""

    sandbox.reset(str(sb), "scratch")
    assert caches(harness) == stored
    pyc = next(harness.rglob("mod.*.pyc")).read_bytes()
    assert int.from_bytes(pyc[4:8], "little") == 0b11     # checked-hash
    # the harness's git status is the tree's: the caches are ignored
    assert git(harness, "status", "--porcelain", "--untracked-files=all") == ""


def test_an_import_beside_checked_hash_bytecode_still_reads_the_source(tmp_path):
    tree = make_tree(tmp_path, "__pycache__/\nvenv/\n")
    sb = tmp_path / "sb"
    sandbox.build(str(tree), str(sb), log=lambda s: None)
    sandbox.reset(str(sb), "scratch")
    harness = sb / "home" / ".claude"
    probe = ("import sys\n"
             "sys.addaudithook(lambda e, a: e == 'open' and isinstance(a[0], str) and print(a[0], flush=True))\n"
             f"sys.path.insert(0, {str(harness / 'hooks')!r})\n"
             "from lib import mod\n")
    out = subprocess.run([str(harness / "venv" / "bin" / "python"), "-c", probe], capture_output=True, text=True,
                         check=True, env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}).stdout
    opened = [os.path.relpath(p, harness) for p in out.split()]
    assert "hooks/lib/mod.py" in opened, opened
    assert any(p.startswith("hooks/lib/__pycache__/mod.") for p in opened), opened


def test_bytecode_is_left_out_where_the_tree_does_not_ignore_it(tmp_path):
    tree = make_tree(tmp_path, None)
    sb = tmp_path / "sb"
    info = sandbox.build(str(tree), str(sb), log=lambda s: None)
    assert info["bytecode"].startswith("none"), info["bytecode"]
    sandbox.reset(str(sb), "scratch")
    assert caches(sb / "home" / ".claude") == [] and caches(sb / "bytecode") == []
    assert not list((sb / "home" / ".claude" / "venv").rglob("*.pyc"))


def test_reset_puts_the_harness_git_directory_back(tmp_path):
    # a replay's hooks write objects, refs and reflogs into the harness's git directory (`git hash-object
    # -w`, checkpoint refs); the next replay in the same sandbox must not find them already written
    tree = make_tree(tmp_path, "__pycache__/\nvenv/\n")
    tpl, sb = tmp_path / "template", tmp_path / "sb"
    sandbox.build(str(tree), str(tpl), log=lambda s: None)
    sandbox.clone(str(tpl), str(sb))
    sandbox.reset(str(sb), "scratch")
    harness = sb / "home" / ".claude"
    pristine = sorted(str(p.relative_to(harness)) for p in (harness / ".git").rglob("*") if p.is_file())
    (harness / "probe.txt").write_text("a replay's content\n", encoding="utf-8")
    oid = git(harness, "hash-object", "-w", "probe.txt").strip()
    git(harness, "update-ref", "refs/checkpoints/master", git(harness, "rev-parse", "HEAD").strip())
    sandbox.reset(str(sb), "scratch")
    after = sorted(str(p.relative_to(harness)) for p in (harness / ".git").rglob("*") if p.is_file())
    assert after == pristine
    assert subprocess.run(["git", "cat-file", "-e", oid], cwd=harness, capture_output=True).returncode != 0
    # and its index still vouches for the copy's files, as clone() left it
    assert git(harness, "diff-files", "--name-only") == ""
