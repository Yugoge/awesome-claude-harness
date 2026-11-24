"""Every run of the hero demo gives its hooks a fresh state dir of its own.

scripts/capture-hero-run.py builds a new fixture for each run and points both sides at
<fixture>/state: itself, for the grant it writes with allowlist.py's own writer (the
grant /allow writes), and examples/guard-demo/run-hero-demo.sh, for the hooks it sends
each push to through the real pre-tool launcher (hooks/pretool-launch.py) under `env -i`.
The hooks keep state between calls: when they used the caller's CLAUDE_STATE_DIR, a
second run against the same dir found the first run's call streak and the third push
was also refused by the orchestrator's call limit, so a rerun differed from the
committed capture.

Two runs here share one caller environment, with an absolute CLAUDE_STATE_DIR. Both must
succeed, leave that dir and the default grant root untouched, and give a capture whose
normalized text equals the committed one, as scripts/verify-hero-provenance.py compares.
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


COMPARE = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('vhp', sys.argv[1])\n"
    "vhp = importlib.util.module_from_spec(spec); spec.loader.exec_module(vhp)\n"
    "fresh = open(sys.argv[2], encoding='utf-8').read()\n"
    "committed = vhp.CAPTURE.read_text(encoding='utf-8')\n"
    "same = vhp.norm_text(fresh) == vhp.norm_text(committed)\n"
    "sys.exit(0 if same and not vhp.fails else 3)\n"
)


def test_two_runs_in_one_environment_give_the_committed_capture(tmp_path):
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
        for run in (1, 2):
            cap = tmp_path / f"capture-{run}.txt"
            r = subprocess.run([sys.executable, str(CAPTURE), "--capture", str(cap),
                                "--evidence", str(tmp_path / f"evidence-{run}.json")],
                               cwd=str(REPO), env=env, capture_output=True, text=True, timeout=180)
            # The comparison verify-hero-provenance.py makes. The capture holds a run to a lower
            # bound only (a busy host lengthens it), so every failure of it fails this test.
            c = subprocess.run([sys.executable, "-c", COMPARE, str(PROVENANCE), str(cap)],
                               cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60)
            assert c.returncode == 0, (f"run {run}: the capture differs from the committed one\n"
                                       f"{cap.read_text(encoding='utf-8')}\n{c.stderr}")
            assert r.returncode == 0, f"run {run}: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    finally:
        stop.set()
        watcher.join(timeout=5)

    assert not seen_default, f"a demo grant appeared under the default root {DEFAULT_GRANT}"
    assert not DEFAULT_GRANT.exists()
    assert list(state.iterdir()) == [], "the demo wrote into the caller's state dir"
    assert list(scratch_tmp.iterdir()) == [], "the run left its fixture behind"
