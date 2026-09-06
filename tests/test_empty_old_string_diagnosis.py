"""An empty ledger `old` must be diagnosed as malformed, not as content drift.

A real cycle emitted twenty-one ledger entries whose `old` was the empty string
(pure insertions). They are shape-valid and can never execute. Before this
change `_count_occurrences` returned -1 for an empty needle and `_locate_unique`
collapsed that into the same `None` it returns for a genuinely absent string, so
both callers printed the identical "absent or duplicated ... -> ambiguous"
message. The structurally impossible ledger was indistinguishable from ordinary
drift in the message a human reads.

These tests pin the new distinguishable error AND act as the positive control
that non-empty needles are counted exactly as before.
"""

import importlib.util
import os

import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "stage-owned-hunks.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("stage_owned_hunks", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


soh = _load()


# --- the empty-needle case is now an explicit, distinguishable error ---------

def test_count_occurrences_raises_on_empty_needle():
    with pytest.raises(soh.EmptyOwnedOldStringError) as exc:
        soh._count_occurrences(b"alpha beta", b"")
    assert "structurally unlocatable" in str(exc.value)


def test_locate_unique_propagates_empty_needle_error():
    with pytest.raises(soh.EmptyOwnedOldStringError):
        soh._locate_unique(b"alpha beta", b"")


def test_empty_needle_is_distinguishable_from_a_genuine_miss():
    """The whole point: absent returns None, empty raises. Not the same signal."""
    assert soh._locate_unique(b"alpha beta", b"ZZZ") is None
    with pytest.raises(soh.EmptyOwnedOldStringError):
        soh._locate_unique(b"alpha beta", b"")


# --- POSITIVE CONTROL: non-empty needles count exactly as before -------------

@pytest.mark.parametrize(
    "haystack, needle, expected",
    [
        (b"alpha beta", b"ZZZ", 0),          # absent
        (b"alpha beta", b"alpha", 1),        # unique
        (b"aa aa aa", b"aa", 3),             # repeated
        (b"aaaa", b"aa", 2),                 # non-overlapping semantics
        (b"alpha", b"alpha", 1),             # whole haystack
        (b"", b"x", 0),                      # empty haystack, non-empty needle
    ],
)
def test_count_occurrences_unchanged_for_non_empty_needles(haystack, needle, expected):
    assert soh._count_occurrences(haystack, needle) == expected


@pytest.mark.parametrize(
    "haystack, needle, expected",
    [
        (b"alpha beta", b"beta", 6),         # unique -> offset
        (b"alpha beta", b"ZZZ", None),       # absent -> None
        (b"aa aa", b"aa", None),             # duplicated -> None
    ],
)
def test_locate_unique_unchanged_for_non_empty_needles(haystack, needle, expected):
    assert soh._locate_unique(haystack, needle) == expected


# --- caller 1: _replay_live (the provenance-plan replay path) ----------------

def test_replay_live_names_the_empty_old_string():
    replay, error = soh._replay_live(b"alpha\n", [{"old": "", "new": "G\n"}], "f.txt")
    assert replay is None                      # SAME outcome as before
    assert "empty old_string" in error         # NEW, specific diagnosis
    assert "absent or duplicated" not in error


def test_replay_live_still_reports_real_drift_as_drift():
    replay, error = soh._replay_live(b"alpha\n", [{"old": "ZZZ", "new": "G\n"}], "f.txt")
    assert replay is None
    assert "absent or duplicated" in error     # unchanged wording for real drift
    assert "empty old_string" not in error


def test_replay_live_two_failures_no_longer_share_one_message():
    empty = soh._replay_live(b"alpha\n", [{"old": "", "new": "G\n"}], "f.txt")[1]
    absent = soh._replay_live(b"alpha\n", [{"old": "ZZZ", "new": "G\n"}], "f.txt")[1]
    assert empty != absent


def test_replay_live_valid_ledger_still_replays():
    """Non-regression: a well-formed ledger is unaffected."""
    replay, error = soh._replay_live(
        b"alpha\nbeta\n", [{"old": "beta\n", "new": "BETA\n"}], "f.txt"
    )
    assert error == ""
    assert replay == b"alpha\nBETA\n"


# --- caller 2: the live-provenance replay inside main() ----------------------

def _live_invocation(tmp_path, monkeypatch, ledger_json):
    """Drive real main() to the replay loop with the git shell-outs stubbed.

    No git process is started: _git is replaced by a stub reporting a tracked,
    unstaged, mode-stable path, which is exactly the state the gates ahead of
    the replay loop require.
    """
    target = tmp_path / "f.txt"
    target.write_text("alpha\nbeta\nGAMMA\n")
    snapshot = tmp_path / "snap.txt"
    snapshot.write_text("alpha\nbeta\n")
    ledger = tmp_path / "ledger.json"
    ledger.write_text(ledger_json)

    monkeypatch.setattr(soh, "_git", lambda root, args: (0, b"", b""))
    return soh.main([
        "--git-root", str(tmp_path),
        "--file", "f.txt",
        "--ledger", str(ledger),
        "--snapshot", str(snapshot),
    ])


def test_main_empty_old_string_excludes_with_the_specific_message(tmp_path, monkeypatch, capsys):
    rc = _live_invocation(tmp_path, monkeypatch, '[{"old": "", "new": "GAMMA\\n"}]')
    err = capsys.readouterr().err
    assert rc == soh.EXCLUDE                   # SAME outcome, not a new gate
    assert "empty old_string" in err           # NEW diagnosis
    assert "absent or duplicated" not in err


def test_main_real_drift_still_reports_drift(tmp_path, monkeypatch, capsys):
    rc = _live_invocation(tmp_path, monkeypatch, '[{"old": "ZZZ", "new": "GAMMA\\n"}]')
    err = capsys.readouterr().err
    assert rc == soh.EXCLUDE
    assert "absent or duplicated" in err
    assert "empty old_string" not in err
