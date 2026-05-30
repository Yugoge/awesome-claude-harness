"""AC6 (ac_uid 6f2b8e4d5a7c9f16) supplemental — empty_diff, overlapping_hunks,
multi-owned isolation, and helper existence.

These cover the remaining named test cases from AC6 not covered elsewhere
(empty_diff, overlapping) plus a multi-owned happy case proving several owned
hunks in one clean file all stage.
"""

import os

from conftest import EXCLUDE, OK, HELPER


def test_helper_exists():
    assert os.path.isfile(HELPER), "scripts/stage-owned-hunks.py must exist"
    assert os.access(HELPER, os.X_OK) or HELPER.endswith(".py")


def test_empty_diff_noop(repo):
    """If the recorded new_string equals old_string (no actual change) and the
    worktree == snapshot, the owned diff is empty -> no-op (exit 0), nothing
    staged, NEVER a whole-file fallback."""
    repo.write("f.txt", "a\nb\nc\n")
    repo.commit("base")
    snap = repo.write_snapshot("a\nb\nc\n")
    # worktree unchanged from snapshot; ledger records a no-op edit.
    repo.write("f.txt", "a\nb\nc\n")
    ledger = repo.write_ledger([{"old": "b\n", "new": "b\n"}])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == OK, err
    assert "NO-OP" in err
    assert repo.cached_diff("f.txt").strip() == "", "empty diff must stage nothing"


def test_overlapping_owned_ranges(repo):
    """Two ledger entries whose located ranges overlap -> ambiguous -> EXCLUDE."""
    repo.write("f.txt", "X\nY\nZ\n")
    repo.commit("base")
    snap = repo.write_snapshot("X\nY\nZ\n")
    repo.write("f.txt", "AAA\nBBB\nZ\n")
    # Both entries locate to overlapping byte ranges (the first spans both lines).
    ledger = repo.write_ledger([
        {"old": "X\nY\n", "new": "AAA\nBBB\n"},
        {"old": "Y\n", "new": "BBB\n"},
    ])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == EXCLUDE
    assert "overlap" in err.lower() or "not uniquely locatable" in err.lower()
    assert repo.cached_diff("f.txt").strip() == ""


def test_multi_owned_clean_stages(repo):
    """Several owned hunks in one clean file (out-of-owned == snapshot) all stage."""
    base = "l1\nl2\nl3\nl4\nl5\nl6\n"
    repo.write("f.txt", base)
    repo.commit("base")
    snap = repo.write_snapshot(base)
    repo.write("f.txt", "l1\nl2 OWNED\nl3\nl4\nl5 OWNED\nl6\n")
    ledger = repo.write_ledger([
        {"old": "l2\n", "new": "l2 OWNED\n"},
        {"old": "l5\n", "new": "l5 OWNED\n"},
    ])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == OK, err
    cached = repo.cached_diff("f.txt")
    assert "+l2 OWNED" in cached and "+l5 OWNED" in cached
