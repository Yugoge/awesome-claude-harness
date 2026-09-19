#!/usr/bin/env python3
"""Regression coverage for scripts/close-report-append.py's post-publish
failure semantics (round-7 CRITICAL fix, ticket dev-20260919-135733).

scripts/close-report-append.py is untracked and has no git history (see
docs/dev/ticket-20260919-135733.md's Reference Source / root_cause_analysis
sections). Before this fix, ANY failure occurring after os.replace() had
already published the new report content was reported through the exact
same `CLOSE_REPORT_APPEND_ERROR: <stage>: <detail>` sentinel as a
pre-publish failure (report untouched) -- even though the live report
already contained the new, fully-landed verdict; a caller (including
hooks/lib/close-verdict.py, read directly and independently by /commit and
/close) could not tell the two apart.

This suite drives run() directly (no subprocess) via SourceFileLoader,
using the REAL repo's hooks/lib/close-verdict.py (read-only dependency,
never modified this cycle) and a scratch tmp_path for the report/section
files -- mirroring the isolated fault-injection method used to diagnose
the defect (docs/dev/ticket-20260919-135733.md's Evidence section).
"""

from __future__ import annotations

import os
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "close-report-append.py"

PRIOR_REPORT_TEXT = "# Close Report\n\nPrior attempt notes.\n\nCLOSE: NO - pending\n"
SECTION_TEXT = "## New attempt\n\nDetails of this attempt.\n\nCLOSE: YES\n"


def _load_module():
    """Fresh import of scripts/close-report-append.py per test (hyphenated
    filename -- not a valid Python module name for a normal import). A
    fresh load avoids module-global state (e.g. _DEFAULT_MARKER_DIR)
    leaking between tests."""
    return SourceFileLoader("close_report_append_under_test", str(_SCRIPT_PATH)).load_module()


@pytest.fixture
def mod(tmp_path, monkeypatch):
    m = _load_module()
    # Redirect the durable failure-marker directory into this test's own
    # scratch dir -- never the real /tmp/claude-close-report-markers.
    monkeypatch.setattr(m, "_DEFAULT_MARKER_DIR", tmp_path / "markers")
    return m


@pytest.fixture
def scenario(tmp_path):
    """A pre-populated report + section file pair, plus the exact bytes
    run() is expected to publish -- shared GIVEN for AC1-AC4."""
    report_path = tmp_path / "close-report-t1.md"
    section_path = tmp_path / "section.md"
    report_path.write_bytes(PRIOR_REPORT_TEXT.encode("utf-8"))
    section_path.write_text(SECTION_TEXT, encoding="utf-8")
    pre_bytes = report_path.read_bytes()
    normalized_section = SECTION_TEXT.rstrip("\n") + "\n"
    candidate_bytes = pre_bytes + b"\n\n" + normalized_section.encode("utf-8")
    return {
        "report_path": report_path,
        "section_path": section_path,
        "pre_bytes": pre_bytes,
        "candidate_bytes": candidate_bytes,
    }


def _run(mod, scenario):
    return mod.run(scenario["report_path"], scenario["section_path"], "t1", _REPO_ROOT)


# ---------------------------------------------------------------------------
# AC1 -- baseline: no fault injected
# ---------------------------------------------------------------------------

def test_ac1_baseline_success_unchanged(mod, scenario):
    ok, line = _run(mod, scenario)
    assert ok is True
    assert '"status": "ok"' in line
    live_bytes = scenario["report_path"].read_bytes()
    assert live_bytes == scenario["candidate_bytes"]


# ---------------------------------------------------------------------------
# AC2 -- os.replace() succeeds, post-publish readback raises OSError
# ---------------------------------------------------------------------------

def test_ac2_post_publish_readback_oserror_restores_pre_bytes(mod, scenario, monkeypatch):
    report_path = scenario["report_path"]
    original_read_bytes = Path.read_bytes
    call_count = {"n": 0}

    def fake_read_bytes(self):
        if str(self) == str(report_path):
            call_count["n"] += 1
            if call_count["n"] == 2:  # the post-publish readback
                raise OSError("simulated post-publish readback failure")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    ok, line = _run(mod, scenario)

    assert ok is False
    assert line.startswith("CLOSE_REPORT_APPEND_ERROR: readback:")
    assert not line.startswith(mod._POST_PUBLISH_CRITICAL_PREFIX)
    live_bytes = report_path.read_bytes()
    assert live_bytes == scenario["pre_bytes"], (
        "live report must be restored to its ORIGINAL bytes, never left "
        "containing the new verdict while run() reports failure"
    )


# ---------------------------------------------------------------------------
# AC3 -- os.replace() succeeds, post-publish read returns mismatched bytes
# ---------------------------------------------------------------------------

def test_ac3_post_publish_content_mismatch_recovers_when_safe(mod, scenario, monkeypatch):
    """Generic, cause-agnostic mismatch: the post-publish read surfaces
    the OLD content (a stale-read-style glitch, unrelated to any
    concurrent writer) -- restoration is safe, attempted, and verified."""
    report_path = scenario["report_path"]
    pre_bytes = scenario["pre_bytes"]
    original_read_bytes = Path.read_bytes
    call_count = {"n": 0}

    def fake_read_bytes(self):
        if str(self) == str(report_path):
            call_count["n"] += 1
            if call_count["n"] == 2:
                return pre_bytes
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    ok, line = _run(mod, scenario)

    assert ok is False
    assert line.startswith("CLOSE_REPORT_APPEND_ERROR: verification:")
    assert not line.startswith(mod._POST_PUBLISH_CRITICAL_PREFIX)
    live_bytes = report_path.read_bytes()
    assert live_bytes == pre_bytes


def test_ac3_post_publish_content_mismatch_reports_compounded_when_unrecoverable(mod, scenario, monkeypatch):
    """A generic mismatch whose own rollback attempt also fails must never
    be reported through the recoverable sentinel (AC3 option (b))."""
    report_path = scenario["report_path"]
    pre_bytes = scenario["pre_bytes"]
    original_read_bytes = Path.read_bytes
    read_call_count = {"n": 0}

    def fake_read_bytes(self):
        if str(self) == str(report_path):
            read_call_count["n"] += 1
            if read_call_count["n"] == 2:
                return pre_bytes  # generic post-publish mismatch, no conflict
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    original_replace = os.replace
    replace_call_count = {"n": 0}

    def fake_replace(src, dst):
        replace_call_count["n"] += 1
        if replace_call_count["n"] == 2:  # the rollback's own publish
            raise OSError("simulated rollback-write failure")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", fake_replace)

    ok, line = _run(mod, scenario)

    assert ok is False
    assert line.startswith(f"{mod._POST_PUBLISH_CRITICAL_PREFIX}:")
    assert "rollback not confirmed" in line


# ---------------------------------------------------------------------------
# AC4 -- concurrent non-lock-participating writer appends bytes directly
# onto the live report between this invocation's os.replace() and its own
# post-publish readback
# ---------------------------------------------------------------------------

def test_ac4_concurrent_external_writer_not_silently_clobbered(mod, scenario, monkeypatch):
    report_path = scenario["report_path"]
    candidate_bytes = scenario["candidate_bytes"]
    pre_bytes = scenario["pre_bytes"]
    intruder_suffix = b"\nEXTERNAL-WRITER-INTRUSION\n"

    original_replace = os.replace
    state = {"done": False}

    def fake_replace(src, dst):
        original_replace(src, dst)
        if str(dst) == str(report_path) and not state["done"]:
            state["done"] = True
            # Simulate a separate, non-cooperating process (bypasses
            # _acquire_lock entirely) appending its own bytes immediately
            # after this invocation's own publish.
            with open(dst, "ab") as fp:
                fp.write(intruder_suffix)

    monkeypatch.setattr(os, "replace", fake_replace)

    ok, line = _run(mod, scenario)

    assert ok is False, "must never report success when a conflict was detected"
    assert line.startswith(f"{mod._POST_PUBLISH_CRITICAL_PREFIX}:"), (
        "must be distinguishable from both AC1 (success) and the AC2/AC3 "
        "recoverable-failure case"
    )
    assert "concurrent external modification detected" in line
    live_bytes = report_path.read_bytes()
    assert live_bytes == candidate_bytes + intruder_suffix, (
        "the concurrent writer's bytes must NOT be silently discarded by a "
        "blind rollback overwrite"
    )
    assert live_bytes != pre_bytes


# ---------------------------------------------------------------------------
# AC5 -- file-scope isolation: the four named files this cycle must not
# touch stay byte-identical to their state at the start of this dev cycle
# (frozen sha256 constants; these files were already dirty from unrelated,
# concurrently in-flight work, so a HEAD-vs-working-tree diff is not the
# right check here -- see docs/dev/ticket-20260919-135733.md's AC5).
# ---------------------------------------------------------------------------

_FORBIDDEN_PATHS = (
    "commands/close.md",
    "agents/qa.md",
    "commands/commit.md",
    "hooks/lib/close-verdict.py",
)


def test_ac5_forbidden_files_untouched():
    """Git-history-layer check (not live filesystem bytes): the four
    forbidden paths must be untouched by the commit that lands this test
    file. Anchoring to a specific commit's own diff -- rather than hashing
    whatever bytes happen to be sitting in a shared working tree -- makes
    this checkout-stable: it does not care what a concurrent, unrelated
    session has dirtied on disk, and it gives the identical answer whether
    run against a clean checkout of the landed commit or against today's
    dirty working tree. Before that commit exists (this cycle has no
    landing channel yet -- dev may not `git commit`, only `/commit` may),
    there is nothing yet in git history that could violate the invariant,
    so the loop below has nothing to find; the check activates for real
    the moment this cycle's own commit is created, and stays correct on
    every future checkout of it."""
    this_file = str(Path(__file__).resolve().relative_to(_REPO_ROOT))
    log = subprocess.run(
        ["git", "log", "--format=%H", "--diff-filter=A", "--", this_file],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    commits = log.stdout.split()
    if not commits:
        return  # this cycle has not landed a commit yet -- nothing to check
    landing_commit = commits[-1]  # oldest hit: the commit that added this file
    for rel_path in _FORBIDDEN_PATHS:
        diff = subprocess.run(
            ["git", "diff", "--name-only", f"{landing_commit}^", landing_commit, "--", rel_path],
            cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
        )
        assert diff.stdout.strip() == "", (
            f"{rel_path} was modified by {landing_commit}, the commit that "
            "landed this dev cycle -- it has no landing channel this cycle "
            "and must remain untouched"
        )


def test_ac5_new_files_exist_at_expected_paths():
    assert _SCRIPT_PATH.is_file()
    assert (_REPO_ROOT / "tests" / "test_close_report_append.py").is_file()


# ---------------------------------------------------------------------------
# AC6 -- pre-publish sentinel/exit-code contract is byte-for-byte unchanged
# ---------------------------------------------------------------------------

def test_ac6_pre_publish_missing_section_file_sentinel_unchanged(mod, tmp_path):
    report_path = tmp_path / "close-report-t2.md"
    section_path = tmp_path / "does-not-exist.md"
    ok, line = mod.run(report_path, section_path, "t2", _REPO_ROOT)
    assert ok is False
    assert line.startswith("CLOSE_REPORT_APPEND_ERROR: read: section-file:")
    assert not report_path.exists()


def test_ac6_pre_publish_illegal_close_line_sentinel_unchanged(mod, tmp_path):
    report_path = tmp_path / "close-report-t3.md"
    section_path = tmp_path / "section-bad.md"
    section_path.write_text("Some notes.\n\nNo verdict line here.\n", encoding="utf-8")
    ok, line = mod.run(report_path, section_path, "t3", _REPO_ROOT)
    assert ok is False
    assert line.startswith("CLOSE_REPORT_APPEND_ERROR: append:")
    assert "not a legal CLOSE" in line
    assert not report_path.exists()


def test_ac6_main_exit_code_1_unchanged_for_pre_publish_failure(tmp_path, monkeypatch, capsys):
    # --section-file must itself exist (main()'s own is_file() precheck
    # returns exit code 2 for a missing/bad-invocation path, a DIFFERENT
    # and already-unchanged contract -- see AC6's own "2 = bad invocation"
    # exit code); the failure exercised here is inside run() itself
    # (illegal CLOSE: line), which is the pre-publish exit-1 path.
    m = _load_module()
    monkeypatch.setattr(m, "_DEFAULT_MARKER_DIR", tmp_path / "markers")
    report_path = tmp_path / "close-report-t4.md"
    section_path = tmp_path / "section-bad.md"
    section_path.write_text("Some notes.\n\nNo verdict line here.\n", encoding="utf-8")
    argv = [
        "close-report-append.py",
        "--report-path", str(report_path),
        "--section-file", str(section_path),
        "--task-id", "t4",
        "--repo-root", str(_REPO_ROOT),
    ]
    exit_code = m.main(argv)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert out.strip().startswith("CLOSE_REPORT_APPEND_ERROR: append:")


def test_ac6_main_exit_code_4_is_new_and_additive_for_post_publish_critical(mod, scenario, monkeypatch, capsys):
    """Not one of AC6's named pre-publish scenarios (those stay unchanged
    -- see the two tests above); demonstrates the new exit code introduced
    by this fix is strictly additive: 4 was never a possible exit code
    before this revision, and is only reachable via a post-publish
    CRITICAL outcome."""
    report_path = scenario["report_path"]
    original_replace = os.replace
    state = {"done": False}

    def fake_replace(src, dst):
        original_replace(src, dst)
        if str(dst) == str(report_path) and not state["done"]:
            state["done"] = True
            with open(dst, "ab") as fp:
                fp.write(b"\nEXTERNAL-WRITER-INTRUSION\n")

    monkeypatch.setattr(os, "replace", fake_replace)

    argv = [
        "close-report-append.py",
        "--report-path", str(report_path),
        "--section-file", str(scenario["section_path"]),
        "--task-id", "t1",
        "--repo-root", str(_REPO_ROOT),
    ]
    exit_code = mod.main(argv)
    assert exit_code == 4
    out = capsys.readouterr().out
    assert out.strip().startswith(f"{mod._POST_PUBLISH_CRITICAL_PREFIX}:")
