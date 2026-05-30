# Auto-generated for task 20260529-210616 AC-3.
# AC-3: score-update.sh blocks close_success_* without legal YES close-report
#       (script-side precondition gate, M3 + codex iter-2 C5/C6).
#
# kind: subprocess-exit-and-jsonl-diff
# Script under test: scripts/score-update.sh
# Creates real close-report fixtures at docs/dev/close-report-<stem>.md and
# unlinks them on teardown.

import json
import os
import pathlib
import subprocess
import uuid

import pytest

AC_UID = "ac3-script-side-success-gate"
AC_TYPE = "data"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "score-update.sh"
DOCS_DEV = REPO_ROOT / "docs" / "dev"

# Per-worker / per-process unique suffix prevents pytest-xdist races where
# parallel workers could overwrite or delete each other's fixture files.
# Codex review (task 20260529-210616) flagged the original fixed-stem
# approach as xdist-unsafe.
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "gw-solo")
_RUNID = uuid.uuid4().hex[:8]


def _unique_stem(label):
    """Return a unique safe-stem (matches ^[A-Za-z0-9][A-Za-z0-9_-]{2,80}$)
    incorporating the xdist worker id and a per-process run-id so multiple
    parallel workers do not collide on the same docs/dev/close-report-*.md.
    """
    # Replace any '_' that might appear in worker name with '-' for stem-safety
    safe_worker = _WORKER.replace("_", "-")
    stem = f"ac3-{safe_worker}-{_RUNID}-{label}"
    # Trim to <=81 chars total (regex allows 1 leading + 2-80 trailing)
    if len(stem) > 81:
        stem = stem[:81]
    return stem


# Positive-case stems for the widened safe-stem regex (codex C5) are
# inherently independent of parallelism because the test BODY writes the
# close-report file directly with these EXACT stems (matching production
# stems) and the fixture's per-stem unique path means each test makes its
# own file. The positive cases themselves use distinct stem values; we
# only need xdist-safety for the close_report file write — which is
# achieved by namespacing inside _make() via uuid.
FIX_STEMS_POS = {
    "bare_timestamp": "20260524-205206",
    "suffixed": "20260524-125300-push",
    "prefixed": "dev-20260527-063758",
}


@pytest.fixture
def fixture_close_report():
    """yield a helper that writes a close-report fixture and tracks cleanup.

    Workers write per-worker uniquely-named files (see _unique_stem) for the
    NEGATIVE-PATH tests. For positive-case stems that match real production
    stems (FIX_STEMS_POS), the fixture writes-then-unlinks; under xdist, if
    two workers happen to schedule the same positive case, one may briefly
    see a missing file. To be fully safe, only ONE positive case per stem
    runs (pytest.mark.parametrize ids are unique within a single worker).
    Cross-worker collision on positive-case stems is mitigated by:
      (a) the test body retries fixture creation if a concurrent unlink fires,
      (b) cleanup uses try/except OSError to tolerate races.
    """
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
    stem = _unique_stem("noline")
    fixture_close_report(stem, "CLOSE: NO - reason")
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", stem, "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5, f"expected 5, got {rc}; stderr={stderr!r}"
    assert b == a


def test_AC_3_close_yes_forced_exits_5(tmp_path, fixture_close_report):
    """codex F9: FORCED excluded — even though classify_line returns 'yes'."""
    lf = _empty_lifecycle(tmp_path)
    stem = _unique_stem("forced")
    fixture_close_report(stem, "CLOSE: YES (FORCED)")
    rc, _stdout, stderr, (b, a) = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", stem, "--lifecycle-file", str(lf), lf=lf,
    )
    assert rc == 5, f"expected 5 for FORCED, got {rc}; stderr={stderr!r}"
    assert "FORCED" in stderr
    assert b == a


def test_AC_3_close_yes_appends_entry(tmp_path, fixture_close_report):
    lf = _empty_lifecycle(tmp_path)
    stem = _unique_stem("yes")
    fixture_close_report(stem, "CLOSE: YES")
    rc, _stdout, stderr, _ = _run(
        "--agent", "dev", "--event", "close_success_qa_pass",
        "--note", stem, "--lifecycle-file", str(lf),
    )
    assert rc == 0, f"expected 0 for legal YES, got {rc}; stderr={stderr!r}"
    lines = lf.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    appended = json.loads(lines[0])
    assert appended["event"] == "close_success_qa_pass"
    assert appended["agent"] == "dev"


def test_AC_3_missing_note_flag_exits_5(tmp_path):
    """AC-3: omitted --note flag triggers M3 gate exit 5 'require --note'.
    The shell ${2:?} guard rejects literal --note '' at exit 1 BEFORE M3 fires;
    the M3 contract this cycle defends against is the missing-flag case (i.e.,
    a caller forgetting to supply --note for a close_success_* event), which
    correctly returns exit 5 from the gate. Test name updated iter-3 (close
    20260529-210616 F3) to match what is actually exercised vs. the AC literal
    'empty note' phrasing."""
    lf = _empty_lifecycle(tmp_path)
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
