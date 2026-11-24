"""A dispatch's declared path names a file of the dispatch's project, not any file whose path ends in it
(lib/declared_paths.py _target_forms; location-rules U30).

A declared docs/dev/x.json covers <project>/docs/dev/x.json, written relative or absolute; a file of the same
name in shared temp or in another tree is no declared file, wherever it lies.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import declared_paths  # noqa: E402

PROJECT = "/nonexistent-u30/proj"
DECLARED = declared_paths._parts("docs/dev/x.json")


def _covered(target: str, data: dict) -> bool:
    return any(declared_paths._covers(DECLARED, form) for form in declared_paths._target_forms(target, data))


@pytest.mark.parametrize("data", [{"cwd": PROJECT}, {"cwd": PROJECT + "/sub", "project": PROJECT}])
def test_the_declared_file_is_the_projects_own(monkeypatch, data):
    if data.get("project"):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", data["project"])
    else:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert _covered(PROJECT + "/docs/dev/x.json", data)
    if data["cwd"] == PROJECT:
        assert _covered("docs/dev/x.json", data)
    assert not _covered(PROJECT + "/docs/dev/y.json", data)


@pytest.mark.parametrize("place", ["/tmp/anything", "/nonexistent-u30/other", "/nonexistent-u30"])
def test_a_file_of_the_declared_name_elsewhere_is_not_declared(monkeypatch, place):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert not _covered(place + "/docs/dev/x.json", {"cwd": PROJECT})


# Continuation: the declared path is anchored at the project root, not at any depth below it. A file of the
# declared name in a subfolder of the project is another file; a declared directory still covers its files.
def test_a_file_of_the_declared_name_in_a_subfolder_is_not_declared(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    for sub in ("sub", "a/b"):
        assert not _covered(f"{PROJECT}/{sub}/docs/dev/x.json", {"cwd": PROJECT})
        assert not _covered(f"{sub}/docs/dev/x.json", {"cwd": PROJECT})
    folder = declared_paths._parts("docs/dev/specs/S1")
    forms = declared_paths._target_forms(PROJECT + "/docs/dev/specs/S1/cp.json", {"cwd": PROJECT})
    assert any(declared_paths._covers(folder, f) for f in forms)
    forms = declared_paths._target_forms(PROJECT + "/x/docs/dev/specs/S1/cp.json", {"cwd": PROJECT})
    assert not any(declared_paths._covers(folder, f) for f in forms)
