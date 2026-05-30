"""AC7 (ac_uid 7a3c9f5e6b8d0a27) — Scenario B: post-capture NON-OVERLAPPING peer edit.

The iteration-1 fail-open: a clean snapshot is captured, this cycle authors an
owned edit (in the ledger), then a peer edits a non-overlapping region of the SAME
file (NOT in the ledger). A naive `git diff <snapshot> <worktree>` would attribute
the peer hunk as owned and stage it. The out-of-owned-region cross-check MUST
convert this to EXCLUDE: nothing staged, both hunks remain in the working tree.

Regression guard: if `git diff --cached -- <file>` is non-empty here, the
fail-open has regressed.
"""

from conftest import EXCLUDE


def test_AC7_scenario_b_excludes(repo):
    base = "".join("line %d\n" % i for i in range(1, 31))
    repo.write("f.txt", base)
    repo.commit("base")
    snap = repo.write_snapshot(base)  # clean pre-edit snapshot = base blob

    # owned edit at line 3 (recorded), peer edit at line 17 (NOT recorded)
    lines = base.split("\n")
    lines[2] = "line 3 OWNED"
    lines[16] = "line 17 PEER"
    repo.write("f.txt", "\n".join(lines))
    ledger = repo.write_ledger([{"old": "line 3\n", "new": "line 3 OWNED\n"}])

    rc, err = repo.run_helper("f.txt", ledger, snap)

    assert rc == EXCLUDE, "Scenario B MUST fail-closed EXCLUDE; got rc=%d" % rc
    # The forward replay of the owned edit (line 3) does NOT reproduce the worktree
    # because the peer's line-17 change is unattributed -> EXCLUDE. (This is the
    # out-of-owned-region detection, expressed via the replay invariant.)
    assert "do not reproduce the worktree" in err or "out-of-owned" in err, err
    # REGRESSION GUARD: nothing staged (not even the owned hunk partially).
    assert repo.cached_diff("f.txt").strip() == "", "fail-open regressed: cached diff not empty"
    # Both changes remain in the working tree, uncommitted.
    unstaged = repo.unstaged_diff("f.txt")
    assert "line 3 OWNED" in unstaged
    assert "line 17 PEER" in unstaged
