# Auto-generated for task 20260529-210616 AC-5.
# AC-5: 5 carried-forward test failures cleared; sibling dirs no regression.
#
# kind: pytest-multi-dir
# Verifies the fix dirs exit 0, the sibling regression dirs exit 0,
# and a static-text guard that commands/close.md still contains the
# 6-bucket Session Summary labels (no source rollback).

import pathlib
import subprocess

import pytest

AC_UID = "ac5-clear-5-failures-no-regress"
AC_TYPE = "hook"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

FIX_DIRS = [
    "tests/generated/20260524-205206/",
    "tests/generated/20260525-095242/",
]

SIBLING_DIRS = [
    "tests/generated/20260526-052559/",
    "tests/generated/20260526-053746/",
    "tests/generated/20260527-132200/",
    "tests/generated/20260529-080709/",
    "tests/generated/20260529-081014/",
]


def _run_pytest(*paths):
    proc = subprocess.run(
        ["python3", "-m", "pytest", *paths, "-q"],
        capture_output=True, text=True, timeout=300, cwd=str(REPO_ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_AC_5_fix_dirs_exit_zero():
    rc, stdout, stderr = _run_pytest(*FIX_DIRS)
    assert rc == 0, (
        f"FIX dirs pytest must exit 0, got {rc}.\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    )


def test_AC_5_sibling_dirs_no_regression():
    rc, stdout, stderr = _run_pytest(*SIBLING_DIRS)
    assert rc == 0, (
        f"Sibling regression pytest must exit 0, got {rc}.\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    )


def test_AC_5_close_md_session_summary_6_bucket_intact():
    """NG7: commands/close.md Session Summary 6-bucket form NOT reverted."""
    text = (REPO_ROOT / "commands" / "close.md").read_text(encoding="utf-8")
    for label in [
        "Accomplished",
        "Not accomplished",
        "User needs satisfied",
        "User needs not satisfied",
        "Bugs encountered",
        "Improvement opportunities",
    ]:
        assert label in text, f"commands/close.md must still contain Session Summary label {label!r}"
