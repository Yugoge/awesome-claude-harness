"""AC3 (ac_uid 3c9e5b1a2d4f6c83) — fail-closed on ANY ambiguity.

Parametrized over the 8 fail-closed cases. Each MUST: exit 10, leave
`git diff --cached -- <file>` EMPTY, and print a fail-closed reason on stderr.
The whole file is NEVER staged and no guessed hunk is staged.
"""

import os

from conftest import EXCLUDE, OK


def _stage_empty(repo, rel):
    return repo.cached_diff(rel).strip() == ""


def test_missing_ledger(repo):
    repo.write("f.txt", "a\nb\nc\n")
    repo.commit("base")
    snap = repo.write_snapshot("a\nb\nc\n")
    repo.write("f.txt", "a\nb OWNED\nc\n")
    missing = os.path.join(repo.root, "does-not-exist.json")
    rc, err = repo.run_helper("f.txt", missing, snap)
    assert rc == EXCLUDE
    assert "ledger missing" in err
    assert _stage_empty(repo, "f.txt")


def test_empty_ledger(repo):
    repo.write("f.txt", "a\nb\nc\n")
    repo.commit("base")
    snap = repo.write_snapshot("a\nb\nc\n")
    repo.write("f.txt", "a\nb OWNED\nc\n")
    ledger = repo.write_ledger([])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == EXCLUDE
    assert "empty" in err.lower()
    assert _stage_empty(repo, "f.txt")


# Any fail-closed reason that indicates ownership/peer ambiguity is acceptable —
# the binding contract is exit 10 + empty stage, not a specific wording.
_AMBIGUITY_REASONS = (
    "not uniquely locatable",
    "do not reproduce the worktree",
    "peer edited",
    "staged content in the index",
    "not tracked in the index",
)


def _reason_ok(err):
    return any(r in err for r in _AMBIGUITY_REASONS)


def test_owned_content_not_unique(repo):
    # old_string is non-unique during replay -> ambiguous -> EXCLUDE
    repo.write("f.txt", "dup\ndup\nx\n")
    repo.commit("base")
    snap = repo.write_snapshot("dup\ndup\nx\n")
    repo.write("f.txt", "dup\ndup\nx OWNED\n")
    # 'dup\n' appears twice in the snapshot; an edit keyed on it is non-unique.
    ledger = repo.write_ledger([{"old": "dup\n", "new": "dup CHANGED\n"}])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == EXCLUDE
    assert _reason_ok(err), err
    assert _stage_empty(repo, "f.txt")


def test_owned_content_absent(repo):
    # recorded old_string not present in the snapshot at all -> EXCLUDE
    repo.write("f.txt", "a\nb\nc\n")
    repo.commit("base")
    snap = repo.write_snapshot("a\nb\nc\n")
    repo.write("f.txt", "a\nb OWNED\nc\n")
    # old_string never existed in the snapshot -> replay cannot locate it.
    ledger = repo.write_ledger([{"old": "NONEXISTENT\n", "new": "b OWNED\n"}])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == EXCLUDE
    assert _reason_ok(err), err
    assert _stage_empty(repo, "f.txt")


def test_peer_edit_inside_owned_range(repo):
    """Peer mutates content INSIDE the line range dev authored. The forward replay
    of dev's authored edit does NOT reproduce the worktree (the peer byte is not
    what dev wrote) -> EXCLUDE. A peer change hidden inside an owned range is NEVER
    staged."""
    repo.write("f.txt", "h1\nh2\nh3\nh4\nh5\n")
    repo.commit("base")
    snap = repo.write_snapshot("h1\nh2\nh3\nh4\nh5\n")
    # Dev authored a 3-line block h2/h3/h4 -> "OWNED A/OWNED B/OWNED C".
    # Peer then mutated the middle line of that block.
    repo.write("f.txt", "h1\nOWNED A\nPEERHACK\nOWNED C\nh5\n")
    ledger = repo.write_ledger([{"old": "h2\nh3\nh4\n", "new": "OWNED A\nOWNED B\nOWNED C\n"}])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == EXCLUDE
    assert _reason_ok(err), err
    assert _stage_empty(repo, "f.txt")


def test_peer_insertion_line_shift(repo):
    """A peer insertion ABOVE the owned region shifts line numbers. Ledger line
    numbers are irrelevant (replay uses content). The peer insertion makes the
    forward replay of the owned edit NOT reproduce the worktree -> EXCLUDE."""
    base = "a\nb\nc\nd\ne\n"
    repo.write("f.txt", base)
    repo.commit("base")
    snap = repo.write_snapshot(base)
    # owned edit (d -> d OWNED); peer INSERTS a new line near the top.
    repo.write("f.txt", "a\nPEER INSERTED\nb\nc\nd OWNED\ne\n")
    ledger = repo.write_ledger([{"old": "d\n", "new": "d OWNED\n"}])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == EXCLUDE
    assert _reason_ok(err), err
    assert _stage_empty(repo, "f.txt")


def test_binary_file(repo):
    data = b"\x00\x01\x02BIN\x00owned\x00"
    repo.write("f.bin", data)
    repo.commit("base")
    snap = repo.write_snapshot(data)
    repo.write("f.bin", b"\x00\x01\x02BIN\x00OWNED\x00")
    ledger = repo.write_ledger([{"old": "owned", "new": "OWNED"}])
    rc, err = repo.run_helper("f.bin", ledger, snap)
    assert rc == EXCLUDE
    assert "binary" in err.lower()
    assert _stage_empty(repo, "f.bin")


def test_mode_change(repo):
    repo.write("f.sh", "#!/bin/sh\necho hi\n")
    repo.commit("base")
    snap = repo.write_snapshot("#!/bin/sh\necho hi\n")
    repo.write("f.sh", "#!/bin/sh\necho OWNED\n")
    os.chmod(repo.path("f.sh"), 0o755)  # mode change vs committed 0644
    ledger = repo.write_ledger([{"old": "echo hi\n", "new": "echo OWNED\n"}])
    rc, err = repo.run_helper("f.sh", ledger, snap)
    assert rc == EXCLUDE
    assert "mode change" in err.lower()
    assert _stage_empty(repo, "f.sh")


def test_crlf_mismatch(repo):
    # snapshot is LF, worktree got CRLF-converted -> encoding mismatch -> EXCLUDE
    repo.write("f.txt", b"a\nb\nc\n")
    repo.commit("base")
    snap = repo.write_snapshot(b"a\nb\nc\n")  # LF snapshot
    repo.write("f.txt", b"a\r\nb OWNED\r\nc\r\n")  # CRLF worktree
    ledger = repo.write_ledger([{"old": "b\n", "new": "b OWNED\r\n"}])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == EXCLUDE
    assert "crlf" in err.lower() or "encoding" in err.lower()
    assert _stage_empty(repo, "f.txt")


def test_context_drift_apply_reject(repo):
    """A pre-staged (non-clean index) target must fail-closed, NEVER apply the owned
    patch on top of unknown staged content and NEVER whole-file fallback.

    The clean-index gate catches this BEFORE apply: if the file already has staged
    content, EXCLUDE. (This converts the codex-flagged 'apply on top of a peer hunk
    already in the index' fail-open into a deterministic EXCLUDE.)
    """
    repo.write("f.txt", "p\nq\nr\ns\n")
    repo.commit("base")
    snap = repo.write_snapshot("p\nq\nr\ns\n")
    repo.write("f.txt", "p\nq OWNED\nr\ns\n")
    ledger = repo.write_ledger([{"old": "q\n", "new": "q OWNED\n"}])
    # A peer-like change is ALREADY staged in the index for this file.
    repo.write("f.txt", "p\nq PEER STAGED\nr\ns\n")
    repo.git("add", "f.txt")
    # Restore worktree to the owned-only state.
    repo.write("f.txt", "p\nq OWNED\nr\ns\n")
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == EXCLUDE
    assert "staged content in the index" in err, err
    # The pre-staged peer content must NOT have been augmented by an owned hunk
    # applied on top — the file was excluded, so the index is untouched by us.
    assert "q OWNED" not in repo.cached_diff("f.txt"), \
        "owned hunk must NOT be applied on top of pre-staged peer content"


def test_clean_index_gate_peer_prestaged(repo):
    """Codex fix #1 regression: a peer hunk pre-staged in the SAME candidate file
    must never be combined with an owned hunk in the index."""
    repo.write("f.txt", "1\n2\n3\n4\n")
    repo.commit("base")
    snap = repo.write_snapshot("1\n2\n3\n4\n")
    # Peer staged a change at line 2.
    repo.write("f.txt", "1\n2 PEER\n3\n4\n")
    repo.git("add", "f.txt")
    # This cycle's owned change at line 4 in the worktree.
    repo.write("f.txt", "1\n2 PEER\n3\n4 OWNED\n")
    ledger = repo.write_ledger([{"old": "4\n", "new": "4 OWNED\n"}])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == EXCLUDE
    assert "staged content in the index" in err
    # Index must still contain ONLY the peer's pre-staged change (we did not touch
    # the index), and crucially must NOT contain the owned hunk layered on top.
    assert "4 OWNED" not in repo.cached_diff("f.txt")


def test_duplicate_old_swap_excluded(repo):
    """Codex fix #2 regression: duplicate old_string values must not let a peer
    swap/relocation pass the ownership check. snapshot 'slot\\nslot\\n'; dev authored
    slot->A then slot->B; the worktree is the peer's swap 'B\\nA\\n'. The endpoint
    recon would falsely match the snapshot, but forward replay is order-sensitive
    and EXCLUDES."""
    repo.write("f.txt", "slot\nslot\n")
    repo.commit("base")
    snap = repo.write_snapshot("slot\nslot\n")
    repo.write("f.txt", "B\nA\n")  # peer's swapped arrangement
    ledger = repo.write_ledger([
        {"old": "slot\n", "new": "A\n"},
        {"old": "slot\n", "new": "B\n"},
    ])
    rc, err = repo.run_helper("f.txt", ledger, snap)
    assert rc == EXCLUDE, "duplicate-old swap MUST fail-closed"
    assert _stage_empty(repo, "f.txt")


def test_new_file_excluded(repo):
    """Codex fix #4 regression: an untracked (new) file is not hunk-stageable via
    git apply --cached; the helper EXCLUDES rather than emitting a malformed
    new-file patch. (Genuinely-owned new files go through the caller's whole-file
    path, never this helper.)"""
    # base commit so the repo has HEAD; the target is a brand-new untracked file.
    repo.write("seed.txt", "seed\n")
    repo.commit("base")
    snap = repo.write_snapshot("")  # empty pre-edit snapshot (new file)
    repo.write("new.txt", "owned content\n")
    ledger = repo.write_ledger([{"old": "", "new": "owned content\n"}])
    rc, err = repo.run_helper("new.txt", ledger, snap)
    assert rc == EXCLUDE
    assert "not tracked in the index" in err
    assert "new.txt" not in repo.cached_names()
