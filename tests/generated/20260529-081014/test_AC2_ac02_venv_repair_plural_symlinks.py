"""AC2: venv repair script makes ALL THREE symlinks pytest-runnable + idempotent.

Source: docs/dev/acceptance-criteria-20260529-081014.json AC2.

NOTE: This test is destructive in principle (would damage the live venv) so it
verifies only the IDEMPOTENT path (running the script on an already-healthy venv).
The destructive path is verified manually in dev's self-verification and again by
QA. If you need to test the repair path, isolate to a throwaway venv via --venv.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
REPAIR = REPO / "scripts" / "repair-venv.sh"
VENV = REPO / "venv"
PY_RE = re.compile(r"^pytest\s+\d+\.\d+")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)


def test_all_three_symlinks_run_pytest():
    for name in ("python", "python3", "python3.12"):
        binp = VENV / "bin" / name
        proc = _run([str(binp), "-m", "pytest", "--version"])
        assert proc.returncode == 0, f"{binp} pytest --version exited {proc.returncode}: {proc.stderr!r}"
        out = proc.stdout.strip()
        assert PY_RE.match(out), f"{binp} stdout {out!r} does not match ^pytest\\s+\\d+\\.\\d+"


def test_no_broken_symlinks_remaining():
    proc = _run(["find", str(VENV / "bin"), "-maxdepth", "1", "-name", "python*", "-type", "l", "-xtype", "l"])
    assert proc.returncode == 0
    assert proc.stdout.strip() == "", f"broken python* symlinks found: {proc.stdout!r}"


def test_interpreter_lives_in_venv():
    proc = _run([str(VENV / "bin" / "python"), "-c",
                 'import sys; assert sys.prefix.endswith("venv"), sys.prefix'])
    assert proc.returncode == 0, f"sys.prefix check failed: {proc.stderr!r}"


def test_idempotent_no_mtime_change():
    target = VENV / "bin" / "python3"
    before = target.stat().st_mtime_ns
    proc = _run(["bash", str(REPAIR)])
    assert proc.returncode == 0, f"repair-venv.sh exited {proc.returncode}: {proc.stderr!r}"
    assert "already healthy" in proc.stdout, f"expected 'already healthy' on idempotent run; got {proc.stdout!r}"
    after = target.stat().st_mtime_ns
    assert before == after, f"mtime changed on idempotent run: {before} -> {after}"


def test_refuses_to_delete_real_non_symlink_file(tmp_path):
    """Regression (close 20260529-081014 codex BLOCKER #2): repair-venv MUST refuse
    to rm a real (non-symlink) file at bin/python*. Earlier code unconditionally
    `rm -f`ed the target when its --version probe failed, which would silently
    delete a real Python binary or any user-placed file. Guard added at
    scripts/repair-venv.sh: refuse-and-exit-1 when TARGET exists and is not a symlink.
    """
    venv = tmp_path / "throwaway-venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\nexecutable = /usr/bin/python3\n")
    # Plant a REAL non-symlink file at bin/python whose --version exits non-zero,
    # so the script's needs_repair branch would be reached on the un-guarded code.
    real_file = venv / "bin" / "python"
    real_file.write_text("#!/bin/sh\nexit 99\n")
    real_file.chmod(0o755)
    assert real_file.exists() and not real_file.is_symlink()
    before_inode = real_file.stat().st_ino
    proc = _run(["bash", str(REPAIR), "--venv", str(venv)])
    assert proc.returncode == 1, (
        f"expected exit 1 (guard refused), got {proc.returncode}\n"
        f"stderr={proc.stderr!r}\nstdout={proc.stdout!r}"
    )
    assert "refusing to delete a real" in proc.stderr or "non-symlink" in proc.stderr, (
        f"expected refusal message in stderr; got {proc.stderr!r}"
    )
    assert real_file.exists(), "repair-venv silently deleted a real non-symlink file"
    assert not real_file.is_symlink(), "repair-venv replaced the real file with a symlink"
    assert real_file.stat().st_ino == before_inode, "real file was replaced (inode changed)"


def test_no_hardcoded_interpreter_target():
    text = (REPO / "scripts" / "repair-venv.sh").read_text()
    # Strip comments and pyvenv.cfg lines, then look for /usr/bin/python3.NN literals.
    offenders: list[str] = []
    for ln in text.splitlines():
        stripped = ln.strip()
        if stripped.startswith("#"):
            continue
        if "pyvenv.cfg" in ln:
            continue
        if re.search(r"/usr/bin/python3\.[0-9]+", ln):
            offenders.append(ln)
    assert not offenders, f"hardcoded interpreter path(s) outside comments / pyvenv.cfg context:\n{offenders!r}"
