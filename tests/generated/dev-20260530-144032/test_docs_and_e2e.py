"""AC5 / AC8 / AC6-doc — agent-prose contracts + end-to-end wiring.

AC5 (5e1a7d3c4f6b8e05): honesty documented, no dormant framing.
AC8 (8b4d0a6f7c9e1b38): dev.md documents owned_edits + pre_edit_snapshots; the
    feature is wired end-to-end (a fixture dev-report drives a successful stage).
AC6 (6f2b8e4d5a7c9f16) doc slice: changelog-analyst preserves flock + staged-count
    guard + DO-NOT #1, and consumes the helper for entangled files.
"""

import json
import os
import re
import subprocess
import sys

import pytest
from conftest import OK

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHANGELOG = os.path.join(ROOT, "agents", "changelog-analyst.md")
DEVMD = os.path.join(ROOT, "agents", "dev.md")
TICKET = os.path.join(ROOT, "docs", "dev", "ticket-dev-20260530-144032.md")
HELPER = os.path.join(ROOT, "scripts", "stage-owned-hunks.py")


def _read(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ---------------- AC5: honesty, no dormant framing ----------------

def test_AC5_ticket_declares_peer_committed_unsolvable():
    if not os.path.isfile(TICKET):
        pytest.skip("ticket gitignored on disk in some environments")
    t = _read(TICKET)
    assert "peer-COMMITTED" in t
    assert "unsolvable with current provenance" in t
    assert "owned-edits ledger" in t
    assert "fail-closed" in t


def test_AC5_no_dormant_acceptable_framing():
    # The forbidden framing must not appear in the delivered agent prose.
    for p in (CHANGELOG, DEVMD):
        text = _read(p)
        assert not re.search(r"dormant\.?\s+this is acceptable", text, re.I), \
            "%s must not frame the deliverable as acceptably dormant" % p


def test_AC5_changelog_documents_end_to_end_signal():
    c = _read(CHANGELOG)
    assert "owned-edits ledger" in c or "owned_edits" in c
    assert "peer-UNCOMMITTED" in c
    assert "unsolvable with current provenance" in c


# ---------------- AC8: dev.md schema + end-to-end ----------------

def test_AC8_devmd_documents_owned_edits_fields():
    d = _read(DEVMD)
    assert "owned_edits" in d, "dev.md must document the owned_edits map field"
    assert "pre_edit_snapshots" in d, "dev.md must document the pre_edit_snapshots map"
    # dev is instructed to record old_string/new_string per applied edit.
    assert "old_string" in d and "new_string" in d
    # The schema block must carry both top-level fields.
    assert re.search(r'"owned_edits"\s*:', d)
    assert re.search(r'"pre_edit_snapshots"\s*:', d)


def test_AC8_changelog_reads_and_passes_to_helper():
    c = _read(CHANGELOG)
    assert "stage-owned-hunks.py" in c, "Phase 5 must invoke the helper"
    assert "owned_edits" in c
    assert "--ledger" in c and "--snapshot" in c


def test_AC8_end_to_end_fixture_dev_report_drives_stage(repo):
    """Simulate the full wiring: a dev-report-shaped owned_edits + pre_edit_snapshots
    map drives the helper to a successful AC1-style stage (proves NOT dormant)."""
    repo.write("agents/file.md", "intro\nold line\noutro\n")
    repo.commit("base")

    # dev-report-shaped maps (top-level fields per dev.md schema)
    dev_report = {
        "owned_edits": {
            "agents/file.md": [{"old": "old line\n", "new": "new OWNED line\n"}]
        },
        "pre_edit_snapshots": {
            "agents/file.md": "intro\nold line\noutro\n"
        },
    }
    # changelog-analyst would write these to temp files; emulate that here.
    repo.write("agents/file.md", "intro\nnew OWNED line\noutro\n")
    ledger_path = os.path.join(repo.root, "le.json")
    with open(ledger_path, "w") as fh:
        json.dump(dev_report["owned_edits"]["agents/file.md"], fh)
    snap_path = os.path.join(repo.root, "snap")
    with open(snap_path, "w") as fh:
        fh.write(dev_report["pre_edit_snapshots"]["agents/file.md"])

    rc, err = repo.run_helper("agents/file.md", ledger_path, snap_path)
    assert rc == OK, err
    assert "+new OWNED line" in repo.cached_diff("agents/file.md")


def test_AC8_blob_sha_snapshot_materialization(repo):
    """Codex fix #6: a pre_edit_snapshots value may be a git blob SHA. Phase 5 must
    resolve it via `git cat-file blob <sha>` before passing to the helper. This test
    proves the resolved-blob path drives a successful stage (the SHA-text path would
    fail the replay)."""
    repo.write("file.md", "intro\nold\nout\n")
    repo.commit("base")
    # blob sha of the pre-edit content
    p = repo.git("rev-parse", "HEAD:file.md")
    blob_sha = p.stdout.decode().strip()
    # The caller (Phase 5) resolves the SHA to bytes:
    resolved = repo.git("cat-file", "blob", blob_sha).stdout
    assert resolved == b"intro\nold\nout\n"

    repo.write("file.md", "intro\nOWNED\nout\n")
    ledger = repo.write_ledger([{"old": "old\n", "new": "OWNED\n"}])
    snap = repo.write_snapshot(resolved)  # materialized bytes, NOT the SHA text
    rc, err = repo.run_helper("file.md", ledger, snap)
    assert rc == OK, err
    assert "+OWNED" in repo.cached_diff("file.md")


def test_AC6_phase5_documents_snapshot_resolution():
    """Phase 5 prose must instruct resolving blob-SHA snapshots via cat-file."""
    c = _read(CHANGELOG)
    assert "cat-file blob" in c, "Phase 5 must resolve blob-SHA snapshots via cat-file"


def test_AC4_phase5_failclosed_for_unprovenanced_dirty_file():
    """Phase 5 must NOT whole-file stage a dirty tracked file lacking owned_edits/
    pre_edit_snapshots provenance (codex fix #5 — no fail-open whole-file add)."""
    c = _read(CHANGELOG)
    assert "no owned_edits/pre_edit_snapshots provenance" in c
    assert "warn-and-skip, not whole-file staged" in c


# ---------------- AC6 doc slice: guards preserved ----------------

def test_AC6_changelog_preserves_flock_and_guards():
    c = _read(CHANGELOG)
    # fd-9 flock still present
    assert "flock -w 30 -x 9" in c
    assert "exec 9>" in c
    # staged-file count guard still present
    assert "scope violation" in c and "whitelist limit" in c
    # DO-NOT #1 (no add -A / add .) preserved
    assert "NEVER use `git add -A` or `git add .`" in c or \
           "Never use `git add -A` or `git add .`" in c
    # foreign_session_candidate exclusion preserved
    assert "foreign_session_candidate" in c


def test_AC6_helper_runs_standalone():
    """The helper runs as a standalone module (sanity: importable / executable)."""
    p = subprocess.run([sys.executable, HELPER, "--help"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert p.returncode == 0
    assert b"--ledger" in p.stdout and b"--snapshot" in p.stdout
