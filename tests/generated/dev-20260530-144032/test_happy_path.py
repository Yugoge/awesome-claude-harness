"""AC1 + AC2 — owned hunks stage, peer hunks do not; peer survives uncommitted.

AC1 (ac_uid 1a7c3f9e0b2d4a61): a whitelisted file with this cycle's owned hunk and
a pre-edit snapshot where all out-of-owned regions are byte-identical to the
snapshot -> only the owned hunk stages. Per the AC1 note, within a SINGLE file the
legitimate stage path is "exactly one authored region and no foreign region";
peer-in-the-same-file is AC7 (EXCLUDE). The owned/peer co-presence that legitimately
stages is when the peer content lives in a SEPARATE whitelisted file.

AC2 (ac_uid 2b8d4a0f1c3e5b72): after committing the staged owned change, the
committed tree contains the owned change only; a separate unstaged region remains
dirty in the working tree.
"""

from conftest import OK


def test_AC1_happy_path_owned_stages(repo):
    repo.write("f.txt", "line 1\nline 2\nline 3\nline 4\nline 5\n")
    repo.commit("base")
    snap = repo.write_snapshot("line 1\nline 2\nline 3\nline 4\nline 5\n")
    # This cycle authors exactly one owned edit; no foreign region in this file.
    repo.write("f.txt", "line 1\nline 2\nline 3 OWNED\nline 4\nline 5\n")
    ledger = repo.write_ledger([{"old": "line 3\n", "new": "line 3 OWNED\n"}])

    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == OK, "happy path must PROCEED; stderr=%s" % err

    cached = repo.cached_diff("f.txt")
    assert "+line 3 OWNED" in cached, "owned hunk must be staged"
    assert "PEER" not in cached
    # Nothing unattributed remained unstaged in this file.
    assert repo.unstaged_diff("f.txt").strip() == "", "no leftover unstaged owned content"


def test_AC1_peer_in_separate_file(repo):
    """The legitimate owned+peer co-presence: peer content in a SEPARATE file.

    Only the owned file is passed to the helper; the peer file is never passed
    (it would be a foreign_session_candidate, excluded upstream — see AC4).
    The owned file stages cleanly; the peer file remains entirely untouched.
    """
    repo.write("owned.txt", "a\nb\nc\n")
    repo.write("peer.txt", "x\ny\nz\n")
    repo.commit("base")
    snap = repo.write_snapshot("a\nb\nc\n")
    repo.write("owned.txt", "a\nb OWNED\nc\n")
    repo.write("peer.txt", "x\ny PEER\nz\n")  # peer's separate-file change
    ledger = repo.write_ledger([{"old": "b\n", "new": "b OWNED\n"}])

    rc, err = repo.run_helper("owned.txt", ledger, snap)
    assert rc == OK, err
    assert "+b OWNED" in repo.cached_diff("owned.txt")
    # peer.txt was never staged by the helper (helper only touched owned.txt).
    assert "peer.txt" not in repo.cached_names()
    assert "y PEER" in repo.unstaged_diff("peer.txt")


def test_AC2_peer_survives_after_commit(repo):
    """Owned change committed; a separate unstaged region remains dirty."""
    repo.write("f.txt", "line 1\nline 2\nline 3\nline 4\nline 5\n")
    repo.commit("base")
    snap = repo.write_snapshot("line 1\nline 2\nline 3\nline 4\nline 5\n")
    repo.write("f.txt", "line 1\nline 2\nline 3 OWNED\nline 4\nline 5\n")
    ledger = repo.write_ledger([{"old": "line 3\n", "new": "line 3 OWNED\n"}])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == OK, err

    # A separate file carries an unstaged (peer-like) change that must survive.
    repo.write("g.txt", "untracked peer content\n")

    # Commit ONLY the staged index (owned change).
    p = repo.git("commit", "-qm", "owned only")
    assert p.returncode == 0, p.stderr.decode()

    head_f = repo.git_text("show", "HEAD:f.txt")
    assert "line 3 OWNED" in head_f, "committed tree must contain the owned change"
    # g.txt (the separate dirty file) survives uncommitted.
    assert "g.txt" in repo.porcelain()
