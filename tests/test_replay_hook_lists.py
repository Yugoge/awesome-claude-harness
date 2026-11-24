"""No hook list a replay session keeps across a landing names a file this tree lacks.

The replays under tests/replay load a base tree's settings.json from git history and land this tree
under the running session; a kept list runs each hook at its path, so a retired file is a hook error
there. policies/replay-hook-lists.v1.json registers every base revision a replay module names; this
test reads the module's own constant for whether the list is kept, and fails on an absent file in a
kept list (unless registered as the replay's subject), on an unregistered revision and on a stale
entry. So the next retirement fails here, not in the replay shards.
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTER = os.path.join(REPO, "policies", "replay-hook-lists.v1.json")
REV = re.compile(r"\b[0-9a-f]{40}\b")
NAMED = re.compile(r"""/((?:hooks|scripts)/[^"'\s]+)""")


def _register() -> dict:
    with open(REGISTER) as fh:
        return json.load(fh)


def _named_revs() -> set[tuple[str, str]]:
    out = set()
    for path in glob.glob(os.path.join(REPO, "tests", "replay", "**", "*.py"), recursive=True):
        with open(path) as fh:
            for rev in REV.findall(fh.read()):
                out.add((os.path.relpath(path, REPO), rev))
    return out


def _constant(module: str, name: str):
    with open(os.path.join(REPO, module)) as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{module} has no module constant {name}")


def _absent(settings_text: str) -> list[str]:
    """The hooks/ and scripts/ files the settings.json's hook commands name that this tree lacks."""
    missing = []
    for groups in (json.loads(settings_text).get("hooks") or {}).values():
        for group in groups:
            for h in group.get("hooks", []):
                missing += [rel for rel in NAMED.findall(h.get("command", ""))
                            if not os.path.isfile(os.path.join(REPO, rel))]
    return sorted(set(missing))


def _base_settings(rev: str) -> str:
    p = subprocess.run(["git", "-C", REPO, "show", f"{rev}:settings.json"], capture_output=True, text=True)
    if p.returncode:
        pytest.fail(f"{rev}:settings.json cannot be read (the replays need the full history): {p.stderr.strip()}")
    return p.stdout


def test_every_named_revision_is_registered_and_no_entry_is_stale():
    entries = {(e["module"], e["rev"]) for e in _register()["entries"]}
    named = _named_revs()
    assert not named - entries, f"replay base revisions missing from the register: {sorted(named - entries)}"
    assert not entries - named, f"register entries whose module no longer names the revision: {sorted(entries - named)}"


@pytest.mark.parametrize("entry", _register()["entries"], ids=lambda e: f"{os.path.basename(e['module'])}-{e['rev'][:9]}")
def test_a_kept_list_names_no_file_this_tree_lacks(entry):
    assert entry.get("reason"), entry
    kept_by = entry["kept_by"]
    held = "kept" if kept_by["key"] in _constant(entry["module"], kept_by["constant"]) else "reloaded"
    assert held == entry["held"], f"{entry['module']} {kept_by}: the code holds the list {held}, the register says {entry['held']}"
    if held != "kept":
        return
    declared = entry.get("absent_by_design") or {}
    absent = _absent(_base_settings(entry["rev"]))
    assert set(absent) == set(declared), (f"{entry['module']} keeps {entry['rev'][:9]}'s hook list across the landing; "
                                          f"files it names that this tree lacks: {absent}, declared absent: {sorted(declared)}")


def test_this_trees_list_names_no_file_this_tree_lacks():
    """The list a replay reloads at the landing (hooklist=landed) and every replay of this tree loads."""
    with open(os.path.join(REPO, "settings.json")) as fh:
        assert _absent(fh.read()) == []
