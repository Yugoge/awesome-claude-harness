"""scripts/canary-verify.sh's cleanup-drift check tells a host's own file from drift of the harness's copy.

The SessionStart canary compares each deployed cleanup artifact with its repo copy. A host file at one
of those paths that the harness never deployed (an image or an administrator put
/etc/tmpfiles.d/tmp.conf there) was reported as drift: exit 2 at every SessionStart, which every replay
on CI met on 2026-11-16 (#51, #52). Only the first stderr line reached the replay's record, and it was
an advisory, so the failure itself was hidden. Now a file without the line that names its own deploy
target is an advisory, real drift of the harness's copy still fails, and failure lines come first.
"""
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP_CONF = REPO / "scripts" / "install" / "tmpfiles-tmp-override.conf"


def _home(tmp_path: Path) -> Path:
    """A harness home that is this tree, plus the venv the canary requires before it checks anything."""
    home = tmp_path / "home"
    home.mkdir()
    for entry in REPO.iterdir():
        if entry.name not in (".git", "venv"):
            (home / entry.name).symlink_to(entry)
    (home / "venv" / "bin").mkdir(parents=True)
    (home / "venv" / "bin" / "activate").write_text("")
    return home


def _canary(tmp_path: Path, host_tmp_conf: str | None):
    home = _home(tmp_path)
    root = tmp_path / "host"
    (root / "etc" / "tmpfiles.d").mkdir(parents=True)
    if host_tmp_conf is not None:
        (root / "etc" / "tmpfiles.d" / "tmp.conf").write_text(host_tmp_conf)
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path / "user"), "CLAUDE_HOME": str(home),
           "CLAUDE_STATE_DIR": str(tmp_path / "state"), "TMPDIR": str(tmp_path)}
    (tmp_path / "user").mkdir()
    proc = subprocess.run(["bash", str(home / "scripts" / "canary-verify.sh"), "--host-root", str(root)],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stderr.splitlines()


def test_a_host_tmp_conf_the_harness_did_not_deploy_is_an_advisory(tmp_path):
    rc, err = _canary(tmp_path, "# the image's own rule\nD /tmp 1777 root root -\n")
    assert rc == 0, err
    assert not [line for line in err if "[FAIL]" in line], err
    assert any("a host file the harness did not deploy" in line and "tmp.conf" in line for line in err), err


def test_drift_of_the_harness_copy_still_fails_and_its_line_comes_first(tmp_path):
    rc, err = _canary(tmp_path, TMP_CONF.read_text() + "e /tmp - - - 1d\n")
    assert rc == 2, err
    assert err[0].startswith("canary-verify[FAIL]: cleanup artifact drift:") and "tmp.conf" in err[0], err
    assert any("[ADVISORY]" in line for line in err[1:]), "the missing artifacts are still reported, after it"


def test_the_harness_copy_unchanged_is_no_drift(tmp_path):
    rc, err = _canary(tmp_path, TMP_CONF.read_text())
    assert rc == 0, err
    assert not [line for line in err if "tmp.conf" in line], err


def test_the_canary_is_unchanged_without_a_host_file(tmp_path):
    rc, err = _canary(tmp_path, None)
    assert rc == 0, err
    assert not [line for line in err if "[FAIL]" in line], err


# The write-gate probe (N14). Its deny case once overwrote a bare file it made below $TMPDIR; OB-L46's
# overwrite scope lets a Write replace such a temp file, so the real gate allowed it and the canary
# reported "FAILED to block Write to existing file" at every SessionStart (every armed replay). The
# probe is now a tracked file below tests/reports/ in a throwaway git work tree: refused by the
# overwrite rule wherever that tree lies, temp root or not.

WRITE_GATE_FAIL = "pretool-write-gate.py FAILED to block Write to existing file"


def _run(tmp_path: Path, home: Path):
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path / "user"), "CLAUDE_HOME": str(home),
           "CLAUDE_STATE_DIR": str(tmp_path / "state"), "TMPDIR": str(tmp_path / "tmp"),
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    (tmp_path / "user").mkdir(exist_ok=True)
    (tmp_path / "tmp").mkdir(exist_ok=True)
    root = tmp_path / "host"
    root.mkdir(exist_ok=True)
    proc = subprocess.run(["bash", str(home / "scripts" / "canary-verify.sh"), "--host-root", str(root)],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stderr.splitlines()


def _home_with_stub_write_gate(tmp_path: Path) -> Path:
    """This tree's harness home, but its write gate allows every call (a fail-open gate)."""
    home = _home(tmp_path)
    (home / "hooks").unlink()
    (home / "hooks").mkdir()
    for entry in (REPO / "hooks").iterdir():
        if entry.name != "pretool-write-gate.py":
            (home / "hooks" / entry.name).symlink_to(entry)
    (home / "hooks" / "pretool-write-gate.py").write_text("import sys\nsys.stdin.read()\nsys.exit(0)\n")
    return home


def test_the_real_write_gate_passes_the_probe_with_tmpdir_a_temp_root(tmp_path):
    rc, err = _run(tmp_path, _home(tmp_path))
    assert not [line for line in err if WRITE_GATE_FAIL in line], err
    assert rc == 0, err


def test_a_fail_open_write_gate_is_still_reported(tmp_path):
    rc, err = _run(tmp_path, _home_with_stub_write_gate(tmp_path))
    assert rc == 2, err
    assert err[0].startswith("canary-verify[FAIL]: " + WRITE_GATE_FAIL), err


def test_the_write_probe_leaves_nothing_in_tmpdir(tmp_path):
    _run(tmp_path, _home(tmp_path))
    assert not [p.name for p in (tmp_path / "tmp").iterdir() if p.name.startswith("canary-")]
