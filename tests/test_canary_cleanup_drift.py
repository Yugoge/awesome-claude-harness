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
