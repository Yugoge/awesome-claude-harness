# Auto-generated for task 20260529-210616 AC-2.
# AC-2: score-update.sh --undo <ts> reverses a named prior entry (M2).
#
# kind: subprocess-exit-and-jsonl-diff
# Script under test: scripts/score-update.sh

import json
import pathlib
import subprocess

AC_UID = "ac2-undo-named-entry"
AC_TYPE = "data"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "score-update.sh"


def _seed_two_ba_entries(tmp_path):
    lf = tmp_path / "lifecycle.jsonl"
    entries = [
        {"ts": "2026-05-29T20:00:00Z", "agent": "ba",
         "event": "qa_first_pass", "prev_score": 50, "new_score": 51,
         "delta": 1, "unclamped_score": 51, "actor": "orchestrator", "reason": "A"},
        {"ts": "2026-05-29T20:05:00Z", "agent": "ba",
         "event": "close_success_qa_pass", "prev_score": 51, "new_score": 53,
         "delta": 2, "unclamped_score": 53, "actor": "orchestrator", "reason": "B"},
    ]
    with lf.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return lf


def _run(*args, lf=None):
    before = lf.read_bytes() if lf else None
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT),
    )
    after = lf.read_bytes() if lf else None
    return proc.returncode, proc.stdout, proc.stderr, (before, after)


def test_AC_2_undo_named_entry_appends_inverse(tmp_path):
    lf = _seed_two_ba_entries(tmp_path)
    before_lines = lf.read_text(encoding="utf-8").splitlines()
    rc, _stdout, stderr, _ = _run(
        "--agent", "ba", "--undo", "2026-05-29T20:05:00Z",
        "--reason", "premature scoring", "--lifecycle-file", str(lf),
    )
    assert rc == 0, f"rc={rc} stderr={stderr!r}"
    after_lines = lf.read_text(encoding="utf-8").splitlines()
    assert len(after_lines) == 3
    # Lines 1+2 byte-identical
    assert after_lines[0] == before_lines[0]
    assert after_lines[1] == before_lines[1]
    appended = json.loads(after_lines[2])
    assert appended["prev_score"] == 53
    assert appended["delta"] == -2
    assert appended["unclamped_score"] == 51
    assert appended["new_score"] == 51
    assert appended["event"] == "manual_reversal"
    assert appended["reason"] == "premature scoring"
    assert appended["agent"] == "ba"


def test_AC_2_undo_not_found_exits_4(tmp_path):
    lf = _seed_two_ba_entries(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "ba", "--undo", "2026-05-29T99:99:99Z",
        "--reason", "x", "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 4, f"expected 4, got {rc}; stderr={stderr!r}"
    assert "not found" in stderr
    assert b == a


def test_AC_2_undo_ambiguous_exits_4(tmp_path):
    lf = tmp_path / "lifecycle.jsonl"
    dup_ts = "2026-05-29T20:00:00Z"
    entries = [
        {"ts": dup_ts, "agent": "ba", "event": "qa_first_pass",
         "prev_score": 50, "new_score": 51, "delta": 1,
         "unclamped_score": 51, "actor": "orchestrator", "reason": "A"},
        {"ts": dup_ts, "agent": "ba", "event": "qa_first_pass",
         "prev_score": 51, "new_score": 52, "delta": 1,
         "unclamped_score": 52, "actor": "orchestrator", "reason": "B"},
    ]
    with lf.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "ba", "--undo", dup_ts, "--reason", "x",
        "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 4, f"expected 4 ambiguous, got {rc}; stderr={stderr!r}"
    assert "ambiguous" in stderr
    assert b == a


def test_AC_2_undo_target_non_numeric_delta_exits_2(tmp_path):
    lf = tmp_path / "lifecycle.jsonl"
    entry = {
        "ts": "2026-05-29T20:00:00Z", "agent": "ba", "event": "qa_first_pass",
        "prev_score": 50, "new_score": 51, "delta": "garbage",
        "unclamped_score": 51, "actor": "orchestrator", "reason": "A",
    }
    lf.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "ba", "--undo", "2026-05-29T20:00:00Z",
        "--reason", "x", "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 2, f"expected 2 for malformed target delta, got {rc}; stderr={stderr!r}"
    assert b == a


def test_AC_2_undo_without_reason_exits_1(tmp_path):
    lf = _seed_two_ba_entries(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "ba", "--undo", "2026-05-29T20:00:00Z",
        "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 1, f"expected 1, got {rc}"
    assert b == a


def test_AC_2_undo_with_delta_mutex_exits_1(tmp_path):
    lf = _seed_two_ba_entries(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "ba", "--undo", "2026-05-29T20:00:00Z",
        "--delta", "-1", "--reason", "x",
        "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 1
    assert "mutually exclusive" in stderr
    assert b == a


def test_AC_2_chain_undo_of_manual_reversal_entry(tmp_path):
    """codex F8: chain undo allowed. Undo a manual_reversal entry by its ts."""
    lf = tmp_path / "lifecycle.jsonl"
    entries = [
        {"ts": "2026-05-29T20:00:00Z", "agent": "ba", "event": "qa_first_pass",
         "prev_score": 50, "new_score": 51, "delta": 1,
         "unclamped_score": 51, "actor": "orchestrator", "reason": "A"},
        {"ts": "2026-05-29T20:05:00Z", "agent": "ba", "event": "manual_reversal",
         "prev_score": 51, "new_score": 50, "delta": -1,
         "unclamped_score": 50, "actor": "orchestrator", "reason": "rev"},
    ]
    with lf.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    rc, _stdout, stderr, _ = _run(
        "--agent", "ba", "--undo", "2026-05-29T20:05:00Z",
        "--reason", "re-undo", "--lifecycle-file", str(lf),
    )
    assert rc == 0, f"chain undo must succeed, got rc={rc}; stderr={stderr!r}"
    after = lf.read_text(encoding="utf-8").splitlines()
    assert len(after) == 3
    appended = json.loads(after[2])
    assert appended["delta"] == 1, "inverse of -1 is +1"
    assert appended["event"] == "manual_reversal"
    assert appended["agent"] == "ba"
