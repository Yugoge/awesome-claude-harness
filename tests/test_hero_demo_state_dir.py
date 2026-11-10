"""The hero demo honours an absolute CLAUDE_STATE_DIR end to end.

scripts/capture-hero-run.py writes the demo's single-use grant with allowlist.py's own
writer, under <state dir>/claude-grants (hooks/lib/harness_state_dir.py: CLAUDE_STATE_DIR
when absolute, else /tmp). examples/guard-demo/run-hero-demo.sh runs the real guard and
the real consumer under `env -i`; when that list dropped CLAUDE_STATE_DIR the hooks looked
in /tmp/claude-grants, never saw the grant, and the capture exited 2 -- so
scripts/verify-claims.sh failed on any host that sets an absolute state dir.

The run uses a fresh state dir of its own, so no grant from another test or a live
session is in its inventory, and it watches the default root for the demo's reserved
grant name the whole time: a grant written or read there would mean the two sides
still disagree. The capture it makes is then compared as scripts/verify-hero-provenance.py
compares a rerun with the committed capture: the consumer's marker names the grant under
the run's own state root, and that one path is all the comparison may map.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CAPTURE = REPO / "scripts" / "capture-hero-run.py"
PROVENANCE = REPO / "scripts" / "verify-hero-provenance.py"
RESERVED_TASK_ID = "readme-hero-demo-reserved"
DEFAULT_GRANT = Path("/tmp/claude-grants") / f"{RESERVED_TASK_ID}.json"

pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("python3") is None,
                                reason="the hero demo needs git and python3 on PATH")


def test_capture_succeeds_with_an_absolute_state_dir(tmp_path):
    assert not DEFAULT_GRANT.exists(), f"precondition: {DEFAULT_GRANT} already exists"
    state = tmp_path / "state"
    state.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    scratch_tmp = tmp_path / "tmp"
    scratch_tmp.mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and not k.startswith("CLAUDE_")}
    env.update(HOME=str(home), TMPDIR=str(scratch_tmp), GIT_CONFIG_NOSYSTEM="1",
               CLAUDE_STATE_DIR=str(state))

    seen_default: list[str] = []
    stop = threading.Event()

    def watch() -> None:
        while not stop.is_set():
            if DEFAULT_GRANT.exists():
                seen_default.append("present")
                return
            stop.wait(0.01)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        r = subprocess.run([sys.executable, str(CAPTURE),
                            "--capture", str(tmp_path / "capture.txt"),
                            "--evidence", str(tmp_path / "evidence.json")],
                           cwd=str(REPO), env=env, capture_output=True, text=True, timeout=180)
    finally:
        stop.set()
        watcher.join(timeout=5)

    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert not seen_default, f"a demo grant appeared under the default root {DEFAULT_GRANT}"
    assert not DEFAULT_GRANT.exists()
    # The real consumer removed the grant from the state dir the verifier wrote it to.
    grants = state / "claude-grants"
    assert grants.is_dir(), "the verifier did not write its grant under CLAUDE_STATE_DIR"
    assert list(grants.iterdir()) == []

    # The rerun comparison verify-claims.sh makes: the normalized diff is empty.
    compare = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('vhp', sys.argv[1])\n"
        "vhp = importlib.util.module_from_spec(spec); spec.loader.exec_module(vhp)\n"
        "fresh = open(sys.argv[2], encoding='utf-8').read()\n"
        "committed = vhp.CAPTURE.read_text(encoding='utf-8')\n"
        "same = vhp.norm_text(vhp.align_state_root(fresh, committed)) == vhp.norm_text(committed)\n"
        "sys.exit(0 if same and not vhp.fails else 3)\n"
    )
    c = subprocess.run([sys.executable, "-c", compare, str(PROVENANCE), str(tmp_path / "capture.txt")],
                       cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60)
    assert c.returncode == 0, f"fresh capture differs from the committed one\n{c.stdout}\n{c.stderr}"
