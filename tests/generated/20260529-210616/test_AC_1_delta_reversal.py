# Auto-generated for task 20260529-210616 AC-1.
# AC-1: score-update.sh --delta appends compensating entry;
#       manual_reversal cannot be called externally (M1/M1b).
#
# kind: subprocess-exit-and-jsonl-diff
# Script under test: scripts/score-update.sh

import json
import pathlib
import subprocess

import pytest

AC_UID = "ac1-delta-reversal"
AC_TYPE = "data"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "score-update.sh"


def _seed_lifecycle(tmp_path, entries):
    """Write provided dict entries as JSONL to a tmp lifecycle file."""
    lf = tmp_path / "lifecycle.jsonl"
    with lf.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return lf


def _run(*args, expect_no_change_path=None):
    """Run score-update.sh; return (rc, stdout, stderr, snapshot_after)."""
    before = expect_no_change_path.read_bytes() if expect_no_change_path else None
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    after = expect_no_change_path.read_bytes() if expect_no_change_path else None
    return proc.returncode, proc.stdout, proc.stderr, (before, after)


def _seed_dev_at_52(tmp_path):
    return _seed_lifecycle(tmp_path, [{
        "ts": "2026-05-29T19:00:00Z", "agent": "dev",
        "event": "qa_first_pass", "prev_score": 50, "new_score": 52,
        "delta": 2, "unclamped_score": 52, "actor": "orchestrator",
        "reason": "seed",
    }])


def test_AC_1_delta_minus2_appends_manual_reversal(tmp_path):
    """--delta -2 --reason 'test reversal' appends 1 line with delta=-2 manual_reversal."""
    lf = _seed_dev_at_52(tmp_path)
    line1_before = lf.read_text(encoding="utf-8").splitlines()[0]
    rc, stdout, stderr, _ = _run(
        "--agent", "dev", "--delta", "-2", "--reason", "test reversal",
        "--lifecycle-file", str(lf),
    )
    assert rc == 0, f"rc={rc} stderr={stderr!r}"
    after_lines = lf.read_text(encoding="utf-8").splitlines()
    assert len(after_lines) == 2, f"lifecycle should have exactly 2 lines, got {len(after_lines)}"
    assert after_lines[0] == line1_before, "line 1 must be byte-identical"
    appended = json.loads(after_lines[1])
    # 9 required fields
    expected_fields = {"ts", "agent", "event", "prev_score", "new_score",
                       "delta", "unclamped_score", "actor", "reason"}
    assert set(appended.keys()) == expected_fields
    assert appended["prev_score"] == 52
    assert appended["delta"] == -2
    assert appended["unclamped_score"] == 50
    assert appended["new_score"] == 50
    assert appended["event"] == "manual_reversal"
    assert appended["reason"] == "test reversal"
    assert appended["agent"] == "dev"


def test_AC_1_delta_without_reason_rejected(tmp_path):
    lf = _seed_dev_at_52(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--delta", "-2",
        "--lifecycle-file", str(lf),
        expect_no_change_path=lf,
    )
    assert rc == 1, f"expected exit 1, got {rc}"
    assert "--reason" in stderr, f"stderr should mention --reason: {stderr!r}"
    assert b == a, "lifecycle must be byte-identical when reason missing"


def test_AC_1_delta_with_event_mutex_rejected(tmp_path):
    lf = _seed_dev_at_52(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--delta", "-2", "--reason", "x",
        "--event", "close_success_qa_pass",
        "--lifecycle-file", str(lf),
        expect_no_change_path=lf,
    )
    assert rc == 1
    assert "mutually exclusive" in stderr, f"stderr should say mutually exclusive: {stderr!r}"
    assert b == a


def test_AC_1_delta_on_fresh_file_with_expected_prev_score_50(tmp_path):
    """codex F6: CAS baseline 50 must work even when no prior entry exists."""
    lf = tmp_path / "lifecycle.jsonl"
    lf.write_text("")  # empty file
    rc, _stdout, stderr, _ = _run(
        "--agent", "dev", "--delta", "3", "--reason", "test",
        "--expected-prev-score", "50",
        "--lifecycle-file", str(lf),
    )
    assert rc == 0, f"rc={rc} stderr={stderr!r}"
    appended = json.loads(lf.read_text(encoding="utf-8").splitlines()[-1])
    assert appended["prev_score"] == 50
    assert appended["delta"] == 3
    assert appended["new_score"] == 53


def test_AC_1_delta_with_wrong_expected_prev_score_cas_conflict(tmp_path):
    lf = _seed_dev_at_52(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--delta", "-2", "--reason", "x",
        "--expected-prev-score", "40",
        "--lifecycle-file", str(lf),
        expect_no_change_path=lf,
    )
    assert rc == 3, f"expected exit 3 (CAS), got {rc}; stderr={stderr!r}"
    assert b == a, "no append on CAS conflict"


# ---- M1b negative sub-scenarios (codex C3/C4) ----------------------------

def test_AC_1_M1b_event_manual_reversal_alone_rejected(tmp_path):
    lf = _seed_dev_at_52(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "manual_reversal",
        "--note", "test-stem",
        "--lifecycle-file", str(lf),
        expect_no_change_path=lf,
    )
    assert rc == 1
    assert "manual_reversal" in stderr
    assert "internal-only" in stderr, f"stderr should contain 'internal-only': {stderr!r}"
    assert b == a


def test_AC_1_M1b_event_manual_reversal_with_delta_rejected(tmp_path):
    lf = _seed_dev_at_52(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "manual_reversal",
        "--delta", "-2", "--reason", "x",
        "--lifecycle-file", str(lf),
        expect_no_change_path=lf,
    )
    assert rc == 1
    assert "manual_reversal" in stderr
    assert b == a


def test_AC_1_M1b_event_manual_reversal_with_undo_rejected(tmp_path):
    lf = _seed_dev_at_52(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "manual_reversal",
        "--undo", "2026-05-29T19:00:00Z", "--reason", "x",
        "--lifecycle-file", str(lf),
        expect_no_change_path=lf,
    )
    assert rc == 1
    assert "manual_reversal" in stderr
    assert b == a


def test_AC_1_help_does_not_list_manual_reversal_as_caller_event(tmp_path):
    """--help/usage text MUST NOT list manual_reversal as caller-available."""
    rc, _stdout, stderr, _ = _run("--help")
    # Help exits 1 (via usage()). The "Canonical events (caller-available):"
    # section must NOT include manual_reversal.
    text = stderr
    # Find caller-available section
    if "Canonical events (caller-available):" in text:
        caller_section_start = text.find("Canonical events (caller-available):")
        caller_section_end = text.find("Internal events", caller_section_start)
        caller_section = text[caller_section_start:caller_section_end] if caller_section_end != -1 else text[caller_section_start:]
        assert "manual_reversal" not in caller_section, (
            f"manual_reversal must NOT appear in caller-available events section: {caller_section!r}"
        )
