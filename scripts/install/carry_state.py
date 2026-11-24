#!/usr/bin/env python3
"""carry_state.py -- the explicit carry-over of what an earlier version kept in its old default places.

An earlier version kept its control state directly in /tmp, its score log in <harness home>/logs/lifecycle.jsonl
and its restart state in <harness home>/restart-state/. This version keeps all three under the state root on
disk (hooks/lib/harness_state_dir.py). Nothing in the harness carries them over by itself: carry_over() is
called on purpose, as a step of installing or landing a version, and by nothing else.

carry_over() refuses unless the code running it is the harness the user's configuration points to
(hooks/lib/claude_home.config_home, by real path): a copy or a checkout has no claim on the installed
harness's state. It takes only entries the inventory names (lib/harness_temp_state.moved_by_default) that
this user owns and that are not symlinks; an entry at the destination stays unless the old one is newer;
score-log rows are joined, the old rows first, none twice by the log's own repeat rule (score_log.marks), the
count of repeats dropped in the output; running it again changes nothing.

usage: python3 scripts/install/carry_state.py      (prints what was carried, as JSON; exit 2 when refused)
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

import claude_home  # noqa: E402
import harness_state_dir  # noqa: E402
import harness_temp_state  # noqa: E402

OLD_STATE_ROOT = "/tmp"  # the default control-state directory before 2026-11-21


class NotTheConfiguredHarness(RuntimeError):
    """The running code is not the harness the user's configuration points to."""


def configured_harness() -> str:
    return os.path.realpath(claude_home.config_home())


def _carry(src: str, dst: str, rel: str, out: dict) -> None:
    st = os.lstat(src)
    if st.st_uid != os.geteuid() or os.path.islink(src):
        out["left"].append(rel)
        return
    if os.path.isdir(src):
        os.makedirs(dst, mode=st.st_mode & 0o7777, exist_ok=True)
        for name in sorted(os.listdir(src)):
            _carry(os.path.join(src, name), os.path.join(dst, name), f"{rel}/{name}", out)
        if not os.listdir(src):
            os.rmdir(src)
        return
    if os.path.lexists(dst) and os.lstat(dst).st_mtime >= st.st_mtime:
        out["kept_newer"].append(rel)  # the destination's entry is as new or newer: it wins
        return
    try:
        os.rename(src, dst)
    except OSError:  # another volume: published on the destination before the old name goes
        tmp = f"{dst}.carry-{os.getpid()}"
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        os.unlink(src)
    out["carried"].append(rel)


def _locked_dir(path: str):
    fd = os.open(path, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _carry_control(old_state_root: str, out: dict) -> None:
    state_override = os.environ.get("CLAUDE_STATE_DIR", "")
    if state_override and os.path.isabs(state_override):
        out["skipped"].append("control state: CLAUDE_STATE_DIR names it, as it did before")
        return
    if not os.path.isdir(old_state_root):
        return
    new = harness_state_dir.harness_state_dir()
    os.makedirs(new, mode=0o700, exist_ok=True)
    fd = _locked_dir(new)
    try:
        for name in sorted(n for n in os.listdir(old_state_root) if harness_temp_state.moved_by_default(n)):
            try:
                _carry(os.path.join(old_state_root, name), os.path.join(new, name), f"state/{name}", out)
            except OSError:
                out["left"].append(f"state/{name}")
    finally:
        os.close(fd)


def _carry_restart(old_records: str, out: dict) -> None:
    import subagent_restart
    if os.environ.get("CLAUDE_RESTART_STATE_DIR"):
        out["skipped"].append("restart state: CLAUDE_RESTART_STATE_DIR names it, as it did before")
        return
    src, dst = os.path.join(old_records, "restart-state"), str(subagent_restart.state_dir())
    if not os.path.isdir(src) or os.path.realpath(src) == os.path.realpath(dst):
        return
    os.makedirs(dst, mode=0o700, exist_ok=True)
    fd = _locked_dir(dst)
    try:
        for name in sorted(os.listdir(src)):
            _carry(os.path.join(src, name), os.path.join(dst, name), f"restart-state/{name}", out)
    finally:
        os.close(fd)


def _carry_score_log(old_records: str, out: dict) -> None:
    import score_log
    src, dst = os.path.join(old_records, "logs", "lifecycle.jsonl"), score_log.log_path()
    if not os.path.isfile(src) or os.path.islink(src) or os.path.realpath(src) == os.path.realpath(dst):
        return
    if os.lstat(src).st_uid != os.geteuid():
        out["left"].append("logs/lifecycle.jsonl")
        return
    with score_log.locked(dst):
        out["repeats_dropped"] = score_log.join_older(dst, Path(src).read_text())  # the log's one writer joins the rows
        os.unlink(src)
    out["carried"].append("logs/lifecycle.jsonl")


def carry_over(old_state_root: str = OLD_STATE_ROOT, old_records: str | None = None) -> dict:
    """Carry the control state, the score log and the restart state of the earlier version into this one's
    places; return what was carried, what stayed because the new entry is newer, and what was left alone.
    ``old_records``: where the earlier version kept its score log and restart state (the harness home)."""
    here = os.path.realpath(ROOT)
    if configured_harness() != here:
        raise NotTheConfiguredHarness(f"{here} is not the configured harness ({configured_harness()})")
    out: dict = {"carried": [], "kept_newer": [], "left": [], "skipped": []}
    _carry_control(old_state_root, out)
    _carry_restart(old_records or here, out)
    _carry_score_log(old_records or here, out)
    return out


def main() -> int:
    try:
        print(json.dumps(carry_over(), indent=1))
    except NotTheConfiguredHarness as exc:
        print(f"carry_state: refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
