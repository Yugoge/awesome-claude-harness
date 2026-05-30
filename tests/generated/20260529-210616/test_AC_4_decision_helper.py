# Auto-generated for task 20260529-210616 AC-4.
# AC-4: scripts/close-scoring-decide.py executable helper returns correct
#       events per fixture matrix (M4 + codex iter-2 C1/C2).
#       8-row decision matrix: 4 close-report states x 2 qa_ever_rejected.
#       Also static-read sub-assertions on commands/close.md Step 3.
#
# kind: subprocess-stdout-json-matrix + static-read
# Helper under test: scripts/close-scoring-decide.py

import json
import pathlib
import re
import subprocess

import pytest

AC_UID = "ac4-decision-helper-runtime-contract"
AC_TYPE = "data"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
HELPER = REPO_ROOT / "scripts" / "close-scoring-decide.py"
CLOSE_MD = REPO_ROOT / "commands" / "close.md"
DOCS_DEV = REPO_ROOT / "docs" / "dev"
VENV_PY = REPO_ROOT.parent / "dot-claude" / "venv" / "bin" / "python3"
# Fall back to ~/.claude/venv/bin/python3 — REPO_ROOT may be the symlinked path
# already. Try absolute path:
import os
HOME_VENV_PY = pathlib.Path(os.path.expanduser("~/.claude/venv/bin/python3"))
PYTHON_BIN = HOME_VENV_PY if HOME_VENV_PY.exists() else (VENV_PY if VENV_PY.exists() else pathlib.Path("python3"))


@pytest.fixture
def fixture_close_report():
    """Yields a callable (stem, last_line)->Path and cleans up created files."""
    created = []

    def _make(stem, last_line=None):
        p = DOCS_DEV / f"close-report-{stem}.md"
        if last_line is None:
            # Caller wants the file ABSENT — make sure it doesn't exist.
            if p.exists():
                p.unlink()
            return p
        body = f"# fixture\n\nbody\n\n{last_line}\n"
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


def _run_helper(task_id, qa_ever_rejected):
    proc = subprocess.run(
        [str(PYTHON_BIN), str(HELPER),
         "--task-id", task_id,
         "--qa-ever-rejected", qa_ever_rejected,
         "--repo-root", str(REPO_ROOT)],
        capture_output=True, text=True, timeout=15, cwd=str(REPO_ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


# Stems for each fixture state — unique to avoid collision.
STEM_MISSING = "ac4-fix-missing-aa"
STEM_NO = "ac4-fix-close-no-aa"
STEM_FORCED = "ac4-fix-close-forced-aa"
STEM_YES = "ac4-fix-close-yes-aa"


MATRIX = [
    # (label, stem, last_line_or_None, qa_ever_rejected, expected_events, skip_reason_substring_or_None)
    ("missing/false", STEM_MISSING, None, "false", [], "missing"),
    ("missing/true", STEM_MISSING, None, "true", [], "missing"),
    ("NO/false", STEM_NO, "CLOSE: NO - reason", "false", [], None),  # any non-null reason
    ("NO/true", STEM_NO, "CLOSE: NO - reason", "true", [], None),
    ("FORCED/false", STEM_FORCED, "CLOSE: YES (FORCED)", "false", [], "FORCED"),
    ("FORCED/true", STEM_FORCED, "CLOSE: YES (FORCED)", "true", [], "FORCED"),
    ("YES/false", STEM_YES, "CLOSE: YES", "false", ["close_success_qa_pass"], None),
    ("YES/true", STEM_YES, "CLOSE: YES", "true", ["close_success_qa_fail_fixed"], None),
]


@pytest.mark.parametrize(
    "label,stem,last_line,qa,expected_events,skip_substr",
    MATRIX,
    ids=[row[0] for row in MATRIX],
)
def test_AC_4_decision_matrix_row(fixture_close_report, label, stem, last_line, qa, expected_events, skip_substr):
    fixture_close_report(stem, last_line)
    rc, stdout, stderr = _run_helper(stem, qa)
    assert rc == 0, f"[{label}] helper must exit 0 for valid decisions, got {rc}; stderr={stderr!r}"
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"[{label}] stdout not JSON: {stdout!r} ({e})")
    assert result["events"] == expected_events, (
        f"[{label}] events mismatch: expected {expected_events}, got {result['events']!r}"
    )
    if skip_substr is None:
        # null skip_reason expected for the YES branches
        if expected_events:
            assert result["skip_reason"] is None, (
                f"[{label}] expected null skip_reason on YES branch, got {result['skip_reason']!r}"
            )
        else:
            assert result["skip_reason"], (
                f"[{label}] expected non-null skip_reason when events empty"
            )
    else:
        assert result["skip_reason"], f"[{label}] expected non-null skip_reason"
        assert skip_substr.lower() in result["skip_reason"].lower(), (
            f"[{label}] expected skip_reason to contain {skip_substr!r}, got {result['skip_reason']!r}"
        )


def test_AC_4_missing_task_id_exits_2():
    proc = subprocess.run(
        [str(PYTHON_BIN), str(HELPER),
         "--qa-ever-rejected", "false",
         "--repo-root", str(REPO_ROOT)],
        capture_output=True, text=True, timeout=15, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 2, f"argparse should exit 2 on missing --task-id, got {proc.returncode}; stderr={proc.stderr!r}"


def test_AC_4_io_error_exits_3(tmp_path, fixture_close_report):
    """Permission-denied on the close-report file -> exit 3 (distinct from missing exit 0)."""
    stem = "ac4-fix-ioerror-aa"
    p = fixture_close_report(stem, "CLOSE: YES")
    # chmod 000 to make it unreadable
    import os
    original_mode = p.stat().st_mode
    try:
        os.chmod(p, 0o000)
        # If running as root (which we are), chmod 000 does NOT block reads.
        # Skip this test if reads still succeed.
        try:
            p.read_text(encoding="utf-8")
            pytest.skip("running as root; chmod 000 doesn't block read — IO error path untestable here")
        except PermissionError:
            pass
        rc, stdout, stderr = _run_helper(stem, "false")
        assert rc == 3, f"expected exit 3 on IO error, got {rc}; stderr={stderr!r}"
    finally:
        os.chmod(p, original_mode)


# ---------- Static-read assertions on commands/close.md Step 3 -------------

def _close_md_text():
    return CLOSE_MD.read_text(encoding="utf-8")


def test_AC_4_close_md_cites_helper_invocation():
    text = _close_md_text()
    assert "close-scoring-decide.py" in text, "commands/close.md must cite the helper"


def test_AC_4_close_md_cites_classify_helper_concept():
    text = _close_md_text()
    # M4 may say "last non-empty line" OR cite last_nonempty by name
    has_phrase = ("last non-empty line" in text) or ("last_nonempty" in text)
    assert has_phrase, "commands/close.md must reference last-non-empty-line classification concept"


def test_AC_4_close_md_forbids_test_harness_reimplementation():
    text = _close_md_text()
    # M4 mandate: "Tests MUST invoke the helper directly; tests MUST NOT
    # reimplement the decision logic in a parallel test harness."
    forbid_phrases = ["MUST NOT reimplement", "MUST NOT re-implement", "must not reimplement"]
    assert any(p in text for p in forbid_phrases), (
        "commands/close.md must forbid tests reimplementing decision logic in a parallel test harness"
    )


def test_AC_4_close_md_lists_all_4_event_names():
    text = _close_md_text()
    for ev in [
        "close_success_qa_pass",
        "close_success_qa_fail_fixed",
        "close_fail_qa_pass",
        "close_fail_qa_fail",
    ]:
        assert ev in text, f"commands/close.md must still mention event {ev!r}"


def test_AC_4_close_md_close_fail_not_routed_through_helper():
    text = _close_md_text()
    # The text must explicitly state that close_fail_* branches remain direct.
    # Accept either "NOT routed through helper" or "NOT routed through the helper"
    # or "directly when the verdict is CLOSE: NO".
    candidates = [
        "NOT routed through the helper",
        "NOT routed through helper",
        "issues them directly",
        "issued directly",
        "orchestrator-direct",
        "orchestrator issues them directly",
    ]
    assert any(c in text for c in candidates), (
        "commands/close.md must state close_fail_* branches are NOT routed through the helper"
    )


def test_AC_4_close_md_force_skip_text_intact():
    text = _close_md_text()
    assert "CLOSE: YES (FORCED)" in text
    # SKIP close-event score updates entirely
    assert "SKIP close-event score updates" in text, (
        "commands/close.md must retain --force SKIP scoring text"
    )
