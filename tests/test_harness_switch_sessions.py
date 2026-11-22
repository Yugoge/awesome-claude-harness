"""Sessions whose Claude Code process started while the harness was off (scripts/harness-switch
session_notes, late_setup, output_lines; hooks/userprompt-harness-switch.sh).

The CLI fixes where it keeps command output (<CLAUDE_CODE_TMPDIR, else $TMPDIR, else /tmp>/claude-
<uid>/<project>/<session>/tasks) when its process starts, and SessionStart hooks run only then. The
tests' session process is CLAUDE_PID, pytest's own; "started while off" means that no SessionStart
hook named it (no .owner of session-scratch-init.sh with its pid). Its late start runs once: on the
token /harness on made for that process, which the late start removes.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from tests.test_harness_switch import claude, home, load_switch  # noqa: F401 -- fixtures and helper


def write_tasks(root: Path, sid: str, fresh=True) -> Path:
    """A tasks directory of session `sid` under the CLI temp root `root`, with one output file
    written after the session's process started (fresh) or long before it (an earlier process's)."""
    tasks = root / "claude-0" / "-work-proj" / sid / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    out = tasks / "b1.output"
    out.write_text("")
    stamp = time.time() + 60 if fresh else 1_000_000_000
    os.utime(out, (stamp, stamp))
    return tasks


@pytest.fixture()
def memroot():
    """A directory on a memory-backed volume: /dev/shm, a tmpfs on Linux."""
    kind = subprocess.run(["stat", "-f", "-c", "%T", "/dev/shm"], capture_output=True, text=True).stdout.strip()
    if kind != "tmpfs":
        pytest.skip("no tmpfs at /dev/shm on this system")
    path = Path(tempfile.mkdtemp(dir="/dev/shm", prefix="switch-sessions-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def context(out):
    return out["hookSpecificOutput"]["additionalContext"] if out else ""


def test_a_session_started_while_off_gets_its_session_start_and_the_line_after_on(home, memroot):
    env = {"CLAUDE_CODE_TMPDIR": str(memroot)}  # where that process's CLI keeps its command output
    owner = Path(home.env["TMPDIR"]) / "S9" / ".owner"
    home.switch("off")
    tasks = write_tasks(memroot, "S9")
    off = home.prompt("hello", session="S9", env=env)
    line = off["systemMessage"]
    assert line.startswith("Restart needed: this session's command output is in %s, on a memory-backed volume"
                           % tasks.parent.resolve()), line
    assert "claude --resume S9" in line and "/restart does not do this" in line
    assert "SESSION START" not in context(off) and not owner.exists()  # while off no harness hook runs
    home.switch("on")
    first = home.prompt("hello", session="S9", env=env)
    assert first["systemMessage"] == line
    ctx = context(first)
    assert ctx.startswith("SESSION START, DONE LATE") and "Not done late" in ctx and "Session info:" in ctx
    assert json.loads(owner.read_text())["pid"] == str(os.getpid())
    second = home.prompt("hello", session="S9", env=env)
    assert "SESSION START" not in context(second) and second["systemMessage"] == line
    shutil.rmtree(tasks.parent)  # the process restarted: its output is no longer there
    assert home.prompt("hello", session="S9", env=env) is None


@pytest.mark.parametrize("state", ["on", "off"])
def test_a_session_whose_output_is_on_the_disk_gets_no_line(home, memroot, state):
    if state == "off":
        home.switch("off")
    disk = home.path.parent / "cli-root"
    write_tasks(disk, "S1")
    assert home.prompt("hello", env={"CLAUDE_CODE_TMPDIR": str(disk)}) is None
    write_tasks(memroot, "S1", fresh=False)  # what an earlier process of the session left on a tmpfs
    assert home.prompt("hello", env={"CLAUDE_CODE_TMPDIR": str(memroot)}) is None


def test_the_switch_report_lists_every_process_whose_output_is_on_a_memory_volume(monkeypatch, tmp_path):
    switch = load_switch()
    mem, disk = tmp_path / "mem", tmp_path / "disk"
    write_tasks(mem, "SID-A")
    write_tasks(disk, "SID-B")
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(mem))
    monkeypatch.setenv("TMPDIR", str(disk))
    monkeypatch.setenv("CLAUDE_PID", "1")
    monkeypatch.setattr(switch, "running_claudes", lambda: [
        (991, ["claude", "--resume=SID-A"], "/work/one"), (992, ["claude", "--resume", "SID-B"], "/work/two"),
        (993, ["claude"], "/work/three")])
    monkeypatch.setattr(switch, "process_start", lambda pid: 1000.0)
    monkeypatch.setattr(switch, "memory_backed", lambda path: path.startswith(str(mem.resolve())))
    text = "\n".join(switch.output_lines({}))
    assert "a restart is needed" in text and "/harness on cannot move it" in text
    assert "project /work/one, session SID-A, process 991: %s" % (mem / "claude-0" / "-work-proj" / "SID-A" / "tasks").resolve() in text
    assert "992" not in text and "SID-B" not in text  # on the disk
    assert "not checked for 1 Claude Code process(es)" in text and "993 (/work/three)" in text
    assert "end this Claude Code process and resume the same session" in text and "/restart does not do this" in text
    assert "every running" not in text
    monkeypatch.setattr(switch, "memory_backed", lambda path: None)  # no mount table: no all-clear
    text = "\n".join(switch.output_lines({}))
    assert "not checked for 3" in text and "a restart is needed" not in text and "every running" not in text
    monkeypatch.setattr(switch, "running_claudes", lambda: None)
    assert switch.output_lines({}) == [
        "Command output: could not check where running sessions keep it (no /proc on this system)"]
    monkeypatch.setattr(switch, "running_claudes", lambda: [(992, ["claude", "--resume", "SID-B"], "/work/two")])
    monkeypatch.setattr(switch, "memory_backed", lambda path: False)
    assert switch.output_lines({}) == ["Command output: every running Claude Code process keeps it on the disk"]


def late_starts(out):
    return context(out).count("SESSION START, DONE LATE")


def test_a_session_whose_owner_mark_cannot_be_written_gets_one_late_start_and_one_notice(home):
    (Path(home.env["TMPDIR"]) / "S9").write_text("")  # its scratch directory, so its .owner, cannot be made
    home.switch("off")
    home.switch("on")
    first = context(home.prompt("hello", session="S9"))
    assert first.startswith("SESSION START, DONE LATE") and first.count("session-scratch-init: cannot create") == 1
    assert [home.prompt("hello", session="S9") for _ in range(3)] == [None] * 3


def test_two_processes_of_one_session_each_get_their_late_start_at_most_once(home, claude):
    home.switch("off")
    other = subprocess.Popen([str(claude), "-c", "sleep 600; :"])  # a second process of S1, started while off
    try:
        time.sleep(0.2)
        home.switch("on")
        b = {"CLAUDE_PID": str(other.pid)}
        owner = Path(home.env["TMPDIR"]) / "S1" / ".owner"
        assert late_starts(home.prompt("hello", env=b)) == 1
        assert json.loads(owner.read_text())["pid"] == str(other.pid)
        counts = {"a": 0, "b": 0}
        for _ in range(3):  # each rewrites the session's one .owner when it runs its session start
            counts["a"] += late_starts(home.prompt("hello"))
            counts["b"] += late_starts(home.prompt("hello", env=b))
        assert counts["b"] == 0 and counts["a"] <= 1, counts
    finally:
        other.kill()
        other.wait()


def test_when_nothing_can_be_recorded_there_is_no_late_start_and_the_on_report_says_why_once(home):
    home.switch("off")
    (home.path / Path(load_switch().SW).name / "late").write_text("")  # where the switch records them: unusable
    on = json.loads(home.switch("on").stdout)["hookSpecificOutput"]["additionalContext"]
    assert on.count("no late session start") == 1, on
    assert [home.prompt("hello", session="S9") for _ in range(3)] == [None] * 3


def test_the_switch_on_report_says_where_command_output_is(home):
    home.switch("off")
    ctx = context(home.prompt("/harness on"))
    assert "Command output" in ctx and "Restart needed: yes: this session's process started while" not in ctx
