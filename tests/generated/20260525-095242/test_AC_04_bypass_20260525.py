# Realized by dev for task 20260525-095242 (sibling-file wiring choice).
# AC ID: AC-04 (parent cycle 20260524-205206 BLOCKER) — Layer 1.F compound-bypass
# hardening. Mirrors the 33-row matrix from
# docs/dev/acceptance-criteria-20260525-095242.json AC-01 with EXACT
# `rc == 2` / `rc == 0` + stable stderr token assertions (codex iter-1
# finding #9 — must use exact equality (rc equals 2 or rc equals 0).
#
# This file is the AC-02 "sibling_new_file" wiring target. The dev-report
# at docs/dev/dev-report-20260525-095242.json declares
# `test_extension_path_chosen: sibling_new_file`; AC-02 honors that field.
#
# The 33 case_ids are emitted as one parametrize entry each, using the
# same `_run_hook_with_payload` helper as the prior cycle
# (tests/generated/20260524-205206/test_AC_04_d4e6f8a0c3b5d7ea.py:54-63).

import json
import pathlib
import subprocess

import pytest

AC_UID = "d4e6f8a0c3b5d7ea"
AC_TYPE = "hook"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
HOOK_PATH = REPO_ROOT / "hooks" / "pretool-bash-safety.sh"
STABLE_STDERR_TOKEN = "bulk-commit-sentinel-write"


def _run_hook_with_payload(hook_path, payload):
    """Run a hook script with a JSON payload on stdin; return (exit, stdout, stderr).

    Mirrors the helper at
    tests/generated/20260524-205206/test_AC_04_d4e6f8a0c3b5d7ea.py:54-63
    (same name, same shape — AC-02(f) contract).
    """
    proc = subprocess.run(
        ["bash", str(hook_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode, proc.stdout, proc.stderr


_FLAG = "/tmp/claude-bulk-commit-sentinel-testsid.flag"
_SENTINEL = "/tmp/claude-bulk-commit-sentinel-testsid-abc.json"


# 33-row matrix preserved verbatim from acceptance-criteria-20260525-095242.json
# AC-01 (28 primary case_ids + 5 -supp regression rows). Tuple shape:
# (case_id, command_string, expected_rc, expected_token_present).
_MATRIX = [
    # --- pure_read_allow (5) ------------------------------------------------
    ("C1", f"ls {_FLAG}", 0, False),
    ("C2", f"stat {_FLAG}", 0, False),
    ("C3", f"cat {_SENTINEL}", 0, False),
    ("C3b", f"cat {_FLAG}", 0, False),
    ("C21", f"find {_FLAG}", 0, False),

    # --- real_bypass_exhibitor_prefix_allowlist (; && || pipe) --------------
    ("C4", f"ls {_FLAG} ; python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'", 2, True),
    ("C5", f"ls {_FLAG} && python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'", 2, True),
    ("C6", f"ls {_FLAG} || python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'", 2, True),
    ("C7", f"ls {_FLAG} | python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'", 2, True),
    ("C7-supp", f"ls {_FLAG} | tee {_FLAG}", 2, True),
    ("C8", f"ls {_FLAG} $(python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")')", 2, True),
    ("C8-supp", f"echo $(ls {_FLAG}) ; python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'", 2, True),
    ("C9", f"ls {_FLAG} `python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'`", 2, True),
    ("C9-supp", f"echo `ls {_FLAG}` ; python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'", 2, True),

    # --- real_bypass_exhibitor — process substitution -----------------------
    ("C10", f"ls <(python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")')", 2, True),

    # --- regression_guard_already_denied_today (C11-C13) --------------------
    ("C11", f"P={_FLAG} ; touch \"$P\"", 2, True),
    ("C12", f"bash -c \"ls {_FLAG}\"", 2, True),
    ("C13", f"python3 -c 'print(open(\"{_FLAG}\").read())'", 2, True),

    # --- m2_official_writer_safelist_tightening (C14) -----------------------
    ("C14", f"python3 scripts/write-bulk-commit-sentinel.py --sid x ; touch {_FLAG}", 2, True),

    # --- negative_control_lookalike_path (C15, C15b, C15c) ------------------
    ("C15",
     "touch /tmp/claude-bulk-allowed-testsid.txt ; ls /tmp/claude-bulk-allowed-testsid.txt",
     0, False),
    # C15b: lookalike path .json.bak — DENY after Cycle 053746 widened the
    # gate to deny any compound shape touching the protected-path PREFIX.
    # M5 (task 20260529-210616): expected updated from (0, False) to (2, True);
    # source NOT rolled back.
    ("C15b",
     "touch /tmp/claude-bulk-commit-sentinel-testsid.json.bak ; "
     "ls /tmp/claude-bulk-commit-sentinel-testsid.json.bak",
     2, True),
    ("C15c",
     "touch /tmp/some-other-file.txt ; ls /tmp/some-other-file.txt",
     0, False),

    # --- negative_control_bare_official_writer (C16) ------------------------
    ("C16", "python3 scripts/write-bulk-commit-sentinel.py --sid x", 0, False),

    # --- real_bypass_exhibitor — xargs / find -exec / find -delete ----------
    ("C17", f"ls {_FLAG} | xargs touch", 2, True),
    ("C18", f"find {_FLAG} -exec touch {{}} +", 2, True),
    ("C19", f"find {_FLAG} -delete", 2, True),

    # --- compound-no-write locks broader M1 semantics (C20) -----------------
    ("C20", f"ls {_FLAG} ; true", 2, True),

    # --- real_bypass_exhibitor — newline / & / |& / shell-keyword (C22-C25)-
    ("C22", f"ls {_FLAG}\npython3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'", 2, True),
    ("C23", f"ls {_FLAG} & python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'", 2, True),
    ("C24", f"ls {_FLAG} |& python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'", 2, True),
    ("C25", f"if ls {_FLAG}; then python3 -c 'open(\"{_FLAG}\",\"w\").write(\"y\")'; fi", 2, True),

    # --- m2_official_writer_safelist_tightening (C26, C27) ------------------
    ("C26", f"touch {_FLAG} # scripts/write-bulk-commit-sentinel.py", 2, True),
    ("C27", f"scripts/write-bulk-commit-sentinel.py ; touch {_FLAG}", 2, True),
]

assert len(_MATRIX) == 33, f"AC-04 bypass matrix must contain 33 rows, got {len(_MATRIX)}"


# Build two disjoint parametrize lists so the literal `rc == 2` / `rc == 0`
# tokens appear in the source text (AC-02(d)(e) static-text contract). The
# two body functions both use the prior-cycle `_run_hook_with_payload`
# helper (AC-02(f)) and share the stable stderr-token assertion.
_DENY_CASES = [
    (cid, cmd, present) for (cid, cmd, rc, present) in _MATRIX if rc == 2
]
_ALLOW_CASES = [
    (cid, cmd, present) for (cid, cmd, rc, present) in _MATRIX if rc == 0
]


@pytest.mark.parametrize(
    "case_id,command,expected_token_present",
    _DENY_CASES,
    ids=[row[0] for row in _DENY_CASES],
)
def test_AC_04_bypass_deny_rows(case_id, command, expected_token_present):
    """DENY rows: EXACT `rc == 2` AND stable stderr token PRESENT.

    Codex iter-1 finding #9 — must use exact equality, not inequality.
    """
    payload = {
        "tool_name": "Bash",
        "agent_id": "qa-test",
        "tool_input": {"command": command},
    }
    rc, _stdout, stderr = _run_hook_with_payload(HOOK_PATH, payload)
    assert rc == 2, (
        f"[{case_id}] expected rc == 2, got {rc}. stderr={stderr!r}"
    )
    token_present = STABLE_STDERR_TOKEN in stderr
    assert token_present is expected_token_present, (
        f"[{case_id}] expected stable stderr token "
        f"'{STABLE_STDERR_TOKEN}' present={expected_token_present}, "
        f"got present={token_present}. stderr={stderr!r}"
    )


@pytest.mark.parametrize(
    "case_id,command,expected_token_present",
    _ALLOW_CASES,
    ids=[row[0] for row in _ALLOW_CASES],
)
def test_AC_04_bypass_allow_rows(case_id, command, expected_token_present):
    """ALLOW rows: EXACT `rc == 0` AND stable stderr token ABSENT."""
    payload = {
        "tool_name": "Bash",
        "agent_id": "qa-test",
        "tool_input": {"command": command},
    }
    rc, _stdout, stderr = _run_hook_with_payload(HOOK_PATH, payload)
    assert rc == 0, (
        f"[{case_id}] expected rc == 0, got {rc}. stderr={stderr!r}"
    )
    token_present = STABLE_STDERR_TOKEN in stderr
    assert token_present is expected_token_present, (
        f"[{case_id}] expected stable stderr token "
        f"'{STABLE_STDERR_TOKEN}' present={expected_token_present}, "
        f"got present={token_present}. stderr={stderr!r}"
    )
