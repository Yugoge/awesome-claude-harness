#!/usr/bin/env python3
"""The canary compares a deployed cleanup artifact with its repository copy, and a host's own file is no artifact.

Measured on the CI runners of 2026-11-16 (runs 43796228298 and 43799397143, the latter a PR that changes
no hook): every replay met `scripts/canary-verify.sh` exiting 2 at SessionStart, with
`canary-verify[FAIL]: cleanup artifact drift: /etc/tmpfiles.d/tmp.conf differs from ...`. The runner image
ships its own /etc/tmpfiles.d/tmp.conf, and the canary took any file at a deploy target for the harness's
deployed copy. A replay record keeps only the first stderr line, which was an advisory, so the failure did
not show. Now a file whose first line is not its artifact's first line is named as the host's and not
compared, a deployed copy that differs still fails, and failure lines come before advisories.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CANARY = ROOT / "scripts" / "canary-verify.sh"
INSTALL = ROOT / "scripts" / "install"
TMP_CONF = "/etc/tmpfiles.d/tmp.conf"


@pytest.fixture
def run(tmp_path):
    home = tmp_path / "claude-home"
    (home / "venv" / "bin").mkdir(parents=True)
    (home / "venv" / "bin" / "activate").write_text("")  # the canary needs a venv to run its checks
    deploy = tmp_path / "root"

    def _run(**files: str):
        for target, text in files.items():
            path = deploy / target.lstrip("/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return subprocess.run(["bash", str(CANARY), "--deploy-root", str(deploy)], capture_output=True, text=True,
                              env={**os.environ, "CLAUDE_HOME": str(home)}, timeout=300)
    return _run


def test_a_host_file_at_a_deploy_target_is_named_not_compared(run):
    r = run(**{TMP_CONF: "# host image rule\nD /tmp 1777 root root -\n"})
    assert r.returncode == 0, r.stderr
    assert "not a deployed cleanup artifact" in r.stderr and TMP_CONF in r.stderr
    assert "[FAIL]" not in r.stderr


def test_a_deployed_copy_as_reviewed_passes(run):
    r = run(**{TMP_CONF: (INSTALL / "tmpfiles-tmp-override.conf").read_text()})
    assert r.returncode == 0, r.stderr
    assert "drift" not in r.stderr and "not a deployed cleanup artifact" not in r.stderr


def test_a_deployed_copy_that_changed_fails_and_says_so_first(run):
    reviewed = (INSTALL / "tmpfiles-tmp-override.conf").read_text()
    r = run(**{TMP_CONF: reviewed + "D /tmp 1777 root root 1h\n"})
    assert r.returncode == 2, r.stderr
    first = r.stderr.splitlines()[0]
    assert first.startswith("canary-verify[FAIL]: cleanup artifact drift:") and TMP_CONF in first, r.stderr
