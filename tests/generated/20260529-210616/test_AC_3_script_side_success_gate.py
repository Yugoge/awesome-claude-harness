# Auto-generated for task 20260529-210616 AC-3.
# AC-3: score-update.sh blocks close_success_* without legal YES close-report
#       (script-side precondition gate, M3 + codex iter-2 C5/C6).
#
# kind: subprocess-exit-and-jsonl-diff
# Script under test: scripts/score-update.sh
# Creates real close-report fixtures at docs/dev/close-report-<stem>.md and
# unlinks them on teardown.

import json
import pathlib
import subprocess

import pytest

AC_UID = "ac3-script-side-success-gate"
AC_TYPE = "data"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "score-update.sh"
DOCS_DEV = REPO_ROOT / "docs" / "dev"

# Use unique fixture stems so we never collide with real close-reports.
# The stem MUST match safe-stem regex ^[A-Za-z0-9][A-Za-z0-9_-]{2,80}$.
FIX_STEM_PRIMARY = "ac3-fixture-aaaa-zz"  # 20 chars, safe-stem compliant
FIX_STEMS_POS = {
    "bare_timestamp": "20260524-205206",
    "suffixed": "20260524-125300-push",
    "prefixed": "dev-20260527-063758",
}


@pytest.fixture
def fixture_close_report():
    """yield a helper that writes a close-report fixture and tracks cleanup."""
    created = []

    def _make(stem, last_line):
        p = DOCS_DEV / f"close-report-{stem}.md"
        body = f"# Test fixture for AC-3\n\nSome body content.\n\n{last_line}\n"
        p.write_text(body, encoding="utf-8")
        created.append(p)
        return p

    yield _make

    for p in created:
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


def _run(*args, lf=None):
    before = lf.read_bytes() if lf else None
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT),
    )
    after = lf.read_bytes() if lf else None
    return proc.returncode, proc.stdout, proc.stderr, (before, after)


def _empty_lifecycle(tmp_path):
    lf = tmp_path / "lifecycle.jsonl"
    lf.write_text("")
    return lf


# ---------- Negative gate cases --------------------------------------------

def test_AC_3_no_close_report_exits_5(tmp_path):
    """When no close-report file exists, exit 5 precondition unmet."""
    lf = _empty_lifecycle(tmp_path)
    # Use a stem GUARANTEED non-existent.
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", "99999999-zzzzzz", "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5, f"expected 5, got {rc}; stderr={stderr!r}"
    assert "precondition unmet" in stderr
    assert b == a


def test_AC_3_close_no_last_line_exits_5(tmp_path, fixture_close_report):
    lf = _empty_lifecycle(tmp_path)
    fixture_close_report(FIX_STEM_PRIMARY, "CLOSE: NO - reason")
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", FIX_STEM_PRIMARY, "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5, f"expected 5, got {rc}; stderr={stderr!r}"
    assert b == a


def test_AC_3_close_yes_forced_exits_5(tmp_path, fixture_close_report):
    """codex F9: FORCED excluded — even though classify_line returns 'yes'."""
    lf = _empty_lifecycle(tmp_path)
    fixture_close_report(FIX_STEM_PRIMARY, "CLOSE: YES (FORCED)")
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", FIX_STEM_PRIMARY, "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5, f"expected 5 for FORCED, got {rc}; stderr={stderr!r}"
    assert "FORCED" in stderr
    assert b == a


def test_AC_3_close_yes_appends_entry(tmp_path, fixture_close_report):
    lf = _empty_lifecycle(tmp_path)
    fixture_close_report(FIX_STEM_PRIMARY, "CLOSE: YES")
    rc, _stdout, stderr, _ = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", FIX_STEM_PRIMARY, "--lifecycle-file", str(lf),
    )
    assert rc == 0, f"expected 0 for legal YES, got {rc}; stderr={stderr!r}"
    lines = lf.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    appended = json.loads(lines[0])
    assert appended["event"] == "close_success_qa_pass"
    assert appended["agent"] == "dev"


def test_AC_3_empty_note_exits_5(tmp_path):
    lf = _empty_lifecycle(tmp_path)
    # bash script consumes "" as the value for --note, so we pass an empty
    # explicit value. The shell script ${2:?...} guard rejects empty strings,
    # so we test with a no-note (omit --note entirely) which triggers our
    # "close_success_* events require --note" path.
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5, f"expected 5 for missing --note, got {rc}; stderr={stderr!r}"
    assert "require --note" in stderr or "precondition unmet" in stderr
    assert b == a


def test_AC_3_note_with_path_traversal_dotdot_exits_5(tmp_path):
    lf = _empty_lifecycle(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", "../../etc/passwd",
        "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5
    assert "path-traversal" in stderr or "forbidden" in stderr
    assert b == a


def test_AC_3_note_with_slash_exits_5(tmp_path):
    lf = _empty_lifecycle(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", "foo/bar",
        "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5
    assert b == a


def test_AC_3_note_starts_with_dot_exits_5(tmp_path):
    lf = _empty_lifecycle(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", ".hidden",
        "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5
    assert b == a


def test_AC_3_note_too_short_exits_5(tmp_path):
    """regex requires ^[A-Za-z0-9][A-Za-z0-9_-]{2,80}$ — minimum 3 chars."""
    lf = _empty_lifecycle(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", "ab",
        "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5
    assert b == a


def test_AC_3_note_with_space_exits_5(tmp_path):
    lf = _empty_lifecycle(tmp_path)
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", "not a stem with spaces",
        "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5
    assert b == a


# ---------- Positive cases (widened safe-stem, codex C5) -------------------

@pytest.mark.parametrize("label,stem", list(FIX_STEMS_POS.items()))
def test_AC_3_widened_safe_stem_positive(tmp_path, fixture_close_report, label, stem):
    lf = _empty_lifecycle(tmp_path)
    fixture_close_report(stem, "CLOSE: YES")
    rc, _stdout, stderr, _ = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", stem, "--lifecycle-file", str(lf),
    )
    assert rc == 0, f"[{label}/{stem}] expected 0 for valid YES, got {rc}; stderr={stderr!r}"
    appended = json.loads(lf.read_text(encoding="utf-8").splitlines()[-1])
    assert appended["event"] == "close_success_qa_pass"


# ---------- close_fail_* NOT gated -----------------------------------------

def test_AC_3_close_fail_not_gated(tmp_path):
    lf = _empty_lifecycle(tmp_path)
    rc, _stdout, stderr, _ = _run(
        "--agent", "dev", "--event", "close_fail_qa_pass",
        "--note", "99999999-ffffff",
        "--lifecycle-file", str(lf),
    )
    assert rc == 0, f"close_fail_* must NOT be gated, got {rc}; stderr={stderr!r}"


# ---------- No override flag exists (codex F1) -----------------------------

def test_AC_3_no_override_flag_recognized(tmp_path):
    lf = _empty_lifecycle(tmp_path)
    rc, _stdout, stderr, _ = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", "99999999-ffffff",
        "--allow-close-success-without-report",
        "--lifecycle-file", str(lf),
    )
    assert rc == 1, f"--allow-close-success-without-report MUST be unknown arg, got {rc}; stderr={stderr!r}"
    assert "Unknown argument" in stderr
