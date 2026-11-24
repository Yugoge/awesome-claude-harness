"""A file the lane created, recorded as agents/dev.md prescribes: pre_edit_snapshots "" and one owned_edits entry
{"old": "", "new": <content>}. stage-owned-hunks.py's replay locates an empty old only in an empty buffer (the one
offset there is), so the ledger replays to the file; an empty old in a non-empty buffer stays a malformed entry.
The late-repair route (scripts/check-late-repair-provenance.py, whole_created) takes such a report through it."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


soh = _load("soh_created", "scripts/stage-owned-hunks.py")
CONTENT = "def created():\n    return 1\n"


def test_replay_of_a_created_files_entry_gives_the_file():
    assert soh._replay_live(b"", [{"old": "", "new": CONTENT}], "src/new.py") == (CONTENT.encode(), "")
    replay, _prov, _components = soh._replay_with_provenance(b"", [{"old": "", "new": CONTENT}], "src/new.py")
    assert bytes(replay) == CONTENT.encode()


def test_a_created_file_then_edited_replays_in_order():
    edits = [{"old": "", "new": CONTENT}, {"old": "return 1", "new": "return 2"}]
    assert soh._replay_live(b"", edits, "src/new.py") == (CONTENT.replace("1", "2").encode(), "")


def test_an_empty_old_in_a_non_empty_buffer_is_still_malformed():
    replay, error = soh._replay_live(b"alpha\n", [{"old": "", "new": "G\n"}], "f.txt")
    assert replay is None and "empty old_string" in error
    replay, error = soh._replay_live(b"", [{"old": "", "new": "x"}, {"old": "", "new": "y"}], "f.txt")
    assert replay is None and "entry 1 has an empty old_string" in error
    with pytest.raises(soh.EmptyOwnedOldStringError):
        soh._locate_unique(b"x", b"")


def test_the_late_repair_route_takes_a_created_file_written_as_dev_md_says(tmp_path):
    checker = _load("late_repair_created", "scripts/check-late-repair-provenance.py")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    rel = "src/new.py"
    (tmp_path / "src").mkdir()
    (tmp_path / rel).write_text(CONTENT, encoding="utf-8")
    report = {"dev": {"status": "completed", "files_modified": [], "files_created": [rel]},
              "owned_edits": {rel: [{"old": "", "new": CONTENT}]}, "pre_edit_snapshots": {rel: ""}}
    path = tmp_path / "dev-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    route, detail = checker.route_file(tmp_path, "20990101-000000", rel, report, path)
    assert (route, detail) == ("whole_created", "replay reproduces current bytes exactly")
