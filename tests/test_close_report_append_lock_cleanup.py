#!/usr/bin/env python3
"""scripts/close-report-append.py leaves no lock file behind (P10-36, P10 A25: a
product repository is clean after the pipelines; R8 rule 3: a file with no consumer
is deleted by its producer).

The append takes an advisory flock on `docs/dev/.close-report-<t>.md.append-lock`
beside the report. Before this fix the file stayed in the product repository after
every append and nothing read it again. The holder now unlinks it at release, and
the acquirer only keeps a lock whose inode is still the one at the path, so the
unlink cannot let two appends hold the lock at once. This suite checks: one append
leaves no lock file; every failure path leaves none; a stale lock file from a killed
holder is taken and removed; the unlink race cannot hand out a lock on an orphaned
inode; concurrent appends still produce intact, non-interleaved sections.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "close-report-append.py"

PRIOR_REPORT_TEXT = "# Close Report\n\nPrior attempt notes.\n\nCLOSE: NO - pending\n"
SECTION_TEXT = "## New attempt\n\nDetails of this attempt.\n\nCLOSE: YES\n"


def _load_module():
    return SourceFileLoader("close_report_append_lock_under_test", str(_SCRIPT_PATH)).load_module()


@pytest.fixture
def mod():
    return _load_module()


@pytest.fixture
def scenario(tmp_path):
    """A product-repo shaped layout: the report under docs/dev, the section outside it."""
    dev = tmp_path / "product" / "docs" / "dev"
    dev.mkdir(parents=True)
    report_path = dev / "close-report-t1.md"
    report_path.write_text(PRIOR_REPORT_TEXT, encoding="utf-8")
    section_path = tmp_path / "section.md"
    section_path.write_text(SECTION_TEXT, encoding="utf-8")
    return {"dev": dev, "report_path": report_path, "section_path": section_path,
            "lock_path": dev / ".close-report-t1.md.append-lock"}


def _leftovers(dev: Path) -> list[str]:
    return sorted(p.name for p in dev.iterdir() if p.name != "close-report-t1.md")


def _run(mod, scenario):
    return mod.run(scenario["report_path"], scenario["section_path"], _REPO_ROOT)


# -- success ------------------------------------------------------------------

def test_one_append_leaves_no_lock_file(scenario):
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--report-path", str(scenario["report_path"]),
         "--section-file", str(scenario["section_path"]), "--task-id", "t1"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["status"] == "ok"
    assert scenario["report_path"].read_text(encoding="utf-8").endswith("CLOSE: YES\n")
    assert _leftovers(scenario["dev"]) == [], "the append left a file beside the report"


def test_a_new_report_leaves_only_the_report(mod, tmp_path):
    dev = tmp_path / "docs" / "dev"
    section = tmp_path / "section.md"
    section.write_text(SECTION_TEXT, encoding="utf-8")
    ok, line = mod.run(dev / "close-report-t1.md", section, _REPO_ROOT)
    assert ok, line
    assert sorted(p.name for p in dev.iterdir()) == ["close-report-t1.md"]


def test_a_stale_lock_file_from_a_killed_holder_is_taken_and_removed(mod, scenario):
    scenario["lock_path"].write_text("")  # no process holds its flock
    ok, line = _run(mod, scenario)
    assert ok, line
    assert _leftovers(scenario["dev"]) == []


# -- failure paths ----------------------------------------------------------

def test_a_pre_publish_append_failure_leaves_no_lock_file(mod, scenario, monkeypatch):
    def failing_replace(src, dst):
        raise OSError(28, "No space left on device (injected)")

    monkeypatch.setattr(os, "replace", failing_replace)
    ok, line = _run(mod, scenario)
    assert not ok and line.startswith("CLOSE_REPORT_APPEND_ERROR: append:"), line
    assert scenario["report_path"].read_text(encoding="utf-8") == PRIOR_REPORT_TEXT
    assert _leftovers(scenario["dev"]) == []


def test_a_post_publish_readback_failure_leaves_no_lock_file(mod, scenario, monkeypatch):
    report_path = scenario["report_path"]
    original_read_bytes = Path.read_bytes
    calls = {"n": 0}

    def flaky_read_bytes(self):
        if self == report_path:
            calls["n"] += 1
            if calls["n"] == 2:  # the post-publish readback (1st is the locked pre-read)
                raise OSError(5, "Input/output error (injected)")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)
    ok, line = _run(mod, scenario)
    assert not ok and "readback" in line, line
    assert _leftovers(scenario["dev"]) == []


def test_an_unexpected_exception_under_the_lock_leaves_no_lock_file(mod, scenario, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("injected")

    monkeypatch.setattr(mod.json, "dumps", boom)
    with pytest.raises(RuntimeError):
        _run(mod, scenario)
    assert _leftovers(scenario["dev"]) == []


def test_a_lock_timeout_refuses_and_the_holder_leaves_no_lock_file(mod, scenario):
    holder = mod._acquire_lock(scenario["report_path"], timeout=1.0)
    try:
        mod._LOCK_TIMEOUT_SECONDS = 0.2
        ok, line = _run(mod, scenario)
        assert not ok and line.startswith("CLOSE_REPORT_APPEND_ERROR: append: could not acquire"), line
        assert scenario["report_path"].read_text(encoding="utf-8") == PRIOR_REPORT_TEXT
    finally:
        mod._release_lock(scenario["report_path"], holder)
    assert _leftovers(scenario["dev"]) == []


def test_an_invalid_lock_timing_leaves_no_lock_file(scenario):
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--report-path", str(scenario["report_path"]),
         "--section-file", str(scenario["section_path"]), "--task-id", "t1",
         "--lock-poll-seconds", "-1"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 1 and proc.stdout.startswith("CLOSE_REPORT_APPEND_ERROR: append:"), proc.stdout
    assert _leftovers(scenario["dev"]) == []


# -- mutual exclusion is not weakened by the unlink -------------------------

def _orphaning_open(mod, lock_path: Path, monkeypatch, relock: bool):
    """The first open the acquirer makes gets a handle on the file at the path, then
    that file is unlinked, as a previous holder's release does while this acquirer
    waits. With relock, a third process has meanwhile created and locked a fresh
    file at the path. Returns the handle of that third process (or None)."""
    real_open = open
    state = {"first": True, "third": None}

    def fake_open(path, *a, **k):
        fh = real_open(path, *a, **k)
        if state["first"] and Path(path) == lock_path:
            state["first"] = False
            os.unlink(lock_path)
            if relock:
                third = real_open(lock_path, "a+")
                fcntl.flock(third.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                state["third"] = third
        return fh

    monkeypatch.setattr(mod, "open", fake_open, raising=False)
    return state


def test_a_lock_on_an_unlinked_inode_is_not_kept(mod, scenario, monkeypatch):
    scenario["lock_path"].write_text("")
    _orphaning_open(mod, scenario["lock_path"], monkeypatch, relock=False)
    fh = mod._acquire_lock(scenario["report_path"], timeout=2.0)
    try:
        held, at_path = os.fstat(fh.fileno()), os.stat(scenario["lock_path"])
        assert (held.st_dev, held.st_ino) == (at_path.st_dev, at_path.st_ino), \
            "the acquirer kept a lock on an inode no longer at the lock path"
    finally:
        mod._release_lock(scenario["report_path"], fh)
    assert _leftovers(scenario["dev"]) == []


def test_a_lock_on_an_unlinked_inode_does_not_admit_a_second_holder(mod, scenario, monkeypatch):
    scenario["lock_path"].write_text("")
    state = _orphaning_open(mod, scenario["lock_path"], monkeypatch, relock=True)
    try:
        with pytest.raises(mod._LockTimeout):
            mod._acquire_lock(scenario["report_path"], timeout=0.3)
    finally:
        if state["third"] is not None:
            state["third"].close()


def test_concurrent_appends_are_serialised_into_intact_sections(scenario, tmp_path):
    n = 8
    sections = []
    procs = []
    for i in range(n):
        text = f"## Attempt {i}\n\n" + "".join(f"line {i}.{j}\n" for j in range(200)) + "\nCLOSE: YES\n"
        sections.append(text)
        sp = tmp_path / f"section-{i}.md"
        sp.write_text(text, encoding="utf-8")
        procs.append(subprocess.Popen(
            [sys.executable, str(_SCRIPT_PATH), "--report-path", str(scenario["report_path"]),
             "--section-file", str(sp), "--task-id", "t1", "--lock-timeout-seconds", "60"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    results = [(p.wait(timeout=120), p.stdout.read(), p.stderr.read()) for p in procs]
    for p in procs:
        p.stdout.close()
        p.stderr.close()
    for rc, out, err in results:
        assert rc == 0, out + err

    body = scenario["report_path"].read_text(encoding="utf-8")
    order = sorted(range(n), key=lambda i: body.find(f"## Attempt {i}\n"))
    assert all(body.count(f"## Attempt {i}\n") == 1 for i in range(n)), "a section lost or duplicated"
    expected = PRIOR_REPORT_TEXT
    for i in order:
        expected += "\n\n" + sections[i]
    assert body == expected, "the sections are not intact, whole and in sequence"
    assert _leftovers(scenario["dev"]) == []
