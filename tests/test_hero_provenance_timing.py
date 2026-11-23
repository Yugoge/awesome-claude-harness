"""The provenance rerun's raw timing does not measure the host it runs on.

scripts/verify-hero-provenance.py reruns the demo and compares the fresh capture's raw
timestamps with the committed one. It held the fresh run to the window [10,15] s, to the
committed duration within 2 s and to each committed interval within its tolerance, both
ways; on a loaded host the fresh run took 15.6-16.7 s and the check failed with the capture
text equal. A busy host only stretches a real run, so the fresh run is now held to lower
bounds and the window is checked on the committed file. The rerun here is the script's own
check_rerun with the capture step answered by a fixed text, so no timing of this machine
enters the verdict.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERIFY = REPO / "scripts" / "verify-hero-provenance.py"
CAPTURE = REPO / ".github" / "assets" / "hero-capture.txt"


def _scaled(text: str, factor: float, only: int | None = None) -> str:
    """The capture with every interval (or interval `only`) times `factor`, stamps as the demo writes them."""
    lines, out, prev_old, prev_new = text.splitlines(), [], None, None
    for i, ln in enumerate(lines):
        if not ln.startswith("["):
            out.append(ln)
            continue
        t = float(ln[1:ln.index("]")])
        k = sum(1 for l in lines[:i] if l.startswith("[")) - 1  # this line's interval index
        new = t if prev_old is None else prev_new + (t - prev_old) * (factor if only in (None, k) else 1.0)
        out.append(f"[{new:8.3f}]" + ln[ln.index("]") + 1:])
        prev_old, prev_new = t, new
    return "\n".join(out) + "\n"


def check_rerun(script: Path, fresh_text: str, committed_text: str | None = None) -> list[str]:
    """`script`'s check_rerun, its capture run answered by `fresh_text`; its failures."""
    spec = importlib.util.spec_from_file_location("verify_hero_provenance_under_test", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real = subprocess.run

    def run(cmd, *a, **kw):
        if any(str(c).endswith("capture-hero-run.py") for c in cmd):
            Path(cmd[cmd.index("--capture") + 1]).write_text(fresh_text, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real(cmd, *a, **kw)
    mod.subprocess.run = run
    if committed_text is not None:
        alt = Path(mod.tempfile.mkdtemp()) / "committed.txt"
        alt.write_text(committed_text, encoding="utf-8")
        mod.CAPTURE = alt
    try:
        mod.check_rerun()
    finally:
        mod.subprocess.run = real
    return list(mod.fails)


def test_the_same_run_passes():
    assert check_rerun(VERIFY, CAPTURE.read_text(encoding="utf-8")) == []


def test_a_fresh_run_on_a_slow_host_passes():
    """Every interval 1.4 times as long (18.3 s): what a loaded host does to a real run."""
    assert check_rerun(VERIFY, _scaled(CAPTURE.read_text(encoding="utf-8"), 1.4)) == []


def test_a_fresh_run_without_the_demos_pauses_fails():
    """A fresh run much shorter than the committed capture claims: its pauses did not run."""
    fails = check_rerun(VERIFY, _scaled(CAPTURE.read_text(encoding="utf-8"), 0.1))
    assert any("shorter than committed" in f for f in fails), fails


def test_an_inflated_committed_interval_fails():
    """One committed interval (the read of the refusal, 3.7 s) edited to 3 times its length."""
    text = CAPTURE.read_text(encoding="utf-8")
    fails = check_rerun(VERIFY, text, committed_text=_scaled(text, 3.0, only=5))
    assert any("inter-arrival delta 5 shorter than committed" in f for f in fails), fails


def test_a_committed_capture_outside_the_window_fails():
    text = CAPTURE.read_text(encoding="utf-8")
    fails = check_rerun(VERIFY, _scaled(text, 1.4), committed_text=_scaled(text, 1.4))
    assert any("committed raw duration" in f and "outside [10,15]" in f for f in fails), fails
