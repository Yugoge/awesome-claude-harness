"""The trace reducer's process lifetimes, minted names and left-out reads (trace.py), on hand-written traces.

Each case is a run-to-run difference two replays of one driver showed under load:
a pipeline writer killed by SIGPIPE whose pid a later hook's shell got (the shell's
writes went to the dead process's component), a pid inside a git object's name,
and git reading a work-tree file only when the index's stat data could not vouch
for it (racy git: a file written in the index's second). None needs strace.
"""
from __future__ import annotations

import json
import os

from tests.replay import differential, trace

ROOT = "/sbx"
LAYOUT = {"mode": "ns", "sb": ROOT + "/sb", "home": ROOT + "/hm", "harness": ROOT + "/hm/.claude",
          "project": ROOT + "/hm/proj", "origin": ROOT + "/hm/proj-origin.git", "state": ROOT + "/sb/state",
          "out": ROOT + "/sb/out", "trace": ROOT + "/sb/trace", "markers": ROOT + "/sb/markers",
          "config_dir": None, "scratch": [ROOT], "temp_dirs": ["/tmp"]}
H, P = LAYOUT["harness"], LAYOUT["project"]


def reduce(tmp_path, lines: list[str], markers=()) -> tuple[list[dict], dict]:
    """parse() over `lines` (strace -f -y output); the relation events as the check loads them, and the stats."""
    out = tmp_path / f"out{len(list(tmp_path.glob('out*')))}"
    out.mkdir()
    (out / "ids.json").write_text(json.dumps({"ids": {}, "window": [0, 1], "layout": LAYOUT}))
    (out / "markers.jsonl").write_text("".join(json.dumps({"seq": i, "kind": k, "value": v}) + "\n"
                                               for i, (k, v) in enumerate(markers, 1)))
    raw = out / "raw.txt"
    raw.write_text("".join(line + "\n" for line in lines))
    stats = trace.parse(str(raw), str(out))
    return differential.load_events(str(out)), stats


def opn(pid: int, path: str, flags: str = "O_RDONLY", cwd: str = P) -> str:
    return f'{pid} openat(AT_FDCWD<{cwd}>, "{path}", {flags}) = 3<{os.path.join(cwd, path)}>'


def run(pid: int, prog: str, *argv: str) -> str:
    args = ", ".join(f'"{a}"' for a in argv)
    return f'{pid} execve("{prog}", [{args}], 0x7ffd /* 9 vars */) = 0'


def mark(pid: int, n: int, kind: str) -> str:
    return opn(pid, f"{LAYOUT['markers']}/{n:07d}.{kind}", "O_WRONLY|O_CREAT, 0644")


def comps_of(events, path: str) -> set:
    return {(e["comp"], e["op"]) for e in events if e["raw"] == path}


def _reused(child_first: bool) -> list[str]:
    """The driver (100) runs hook a, whose shell (200) forks `yes` (300), killed by SIGPIPE; then hook c,
    which runs `sh -c` (no harness file of its own) with pid 300 again and writes a file."""
    child = [f'300 execve("/bin/sh", ["sh", "-c", "echo x > state/c.json"], 0x7f /* 9 vars */) = 0',
             opn(300, f"{H}/state/c.json", "O_WRONLY|O_CREAT|O_TRUNC, 0644")]
    again = (["100 vfork( <unfinished ...>"] + child + ["100 <... vfork resumed>) = 300"] if child_first
             else ["100 vfork() = 300"] + child)
    return ([run(100, "/usr/bin/python3", "python3", "-m", "replay.inner"),
             mark(100, 1, "event"), "100 vfork() = 200", run(200, "/bin/bash", "bash", f"{H}/hooks/a.sh"),
             "200 clone(child_stack=NULL, flags=SIGCHLD) = 300", run(300, "/usr/bin/yes", "yes"),
             "300 +++ killed by SIGPIPE +++", "200 +++ exited with 0 +++", mark(100, 2, "event")]
            + again + ["300 +++ exited with 0 +++", "100 +++ exited with 0 +++"])


def test_a_process_a_signal_killed_ends_there_and_its_pid_is_a_new_process_after(tmp_path):
    markers = [("event", "1"), ("event", "2")]
    for child_first in (False, True):
        events, stats = reduce(tmp_path, _reused(child_first), markers)
        got = {(e["comp"], e["origin"], e["event"]) for e in events if e["raw"] == f"{H}/state/c.json"}
        assert got == {("cli", "", 2)}, (child_first, got)     # the driver's, at event 2: not hook a's
        assert stats["lost_exits"] == 0
    # strace without the "killed by" line (its -e signal=none hid it): the fork that gives the pid out
    # again ends the dead lifetime, and the stats say so; reported after the child's own calls, it
    # comes too late for them, which the stats say as well
    events, stats = reduce(tmp_path, [x for x in _reused(False) if "killed" not in x], markers)
    assert {(e["comp"], e["event"]) for e in events if e["raw"] == f"{H}/state/c.json"} == {("cli", 2)}
    assert stats["lost_exits"] == 1
    _events, stats = reduce(tmp_path, [x for x in _reused(True) if "killed" not in x], markers)
    assert stats["lost_exits"] == 1


def test_strace_prints_the_end_of_a_process_a_signal_killed():
    argv = trace.strace_argv("/dev/null")
    sig = argv[argv.index("-e", argv.index("-q")) + 1]
    # strace prints "+++ killed by SIG" only for a signal in this set: all but SIGCHLD, which kills nothing
    assert sig == "signal=!SIGCHLD", sig


def test_a_thread_that_ran_execve_ends_there(tmp_path):
    lines = [run(100, "/usr/bin/python3", "python3", "-m", "replay.inner"),
             "100 vfork() = 200", run(200, "/usr/bin/python3", "python3", f"{H}/hooks/t.py"),
             "200 clone3({flags=CLONE_VM|CLONE_THREAD}, 88) = 201",
             "201 execve(\"/bin/true\", [\"true\"], 0x7f /* 9 vars */ <unfinished ...>",
             "200 +++ superseded by execve in pid 201 +++", "200 <... execve resumed>) = 0",
             "200 +++ exited with 0 +++",
             "100 vfork() = 201", run(201, "/bin/bash", "bash", f"{H}/hooks/u.sh"),
             opn(201, f"{H}/state/u.json", "O_WRONLY|O_CREAT|O_TRUNC, 0644"),
             "201 +++ exited with 0 +++", "100 +++ exited with 0 +++"]
    events, stats = reduce(tmp_path, lines)
    assert comps_of(events, f"{H}/state/u.json") == {("hooks/u.sh", "create")}
    assert stats["lost_exits"] == 0


def test_a_pid_inside_a_git_object_name_is_not_minted(tmp_path):
    obj = f"{P}/.git/objects/ec/1f2e300a7e" + "b" * 28      # holds the creating process's pid, 300
    lines = [run(100, "/usr/bin/python3", "python3", "-m", "replay.inner"),
             "100 vfork() = 300", run(300, "/usr/bin/git", "git", "hash-object", "-w", f"{P}/f"),
             opn(300, f"{P}/f"), opn(300, f"{P}/.git/objects/ec/tmp_obj_aB3dE9", "O_RDWR|O_CREAT|O_EXCL, 0444"),
             f'300 link("{P}/.git/objects/ec/tmp_obj_aB3dE9", "{obj}") = 0',
             f'300 unlink("{P}/.git/objects/ec/tmp_obj_aB3dE9") = 0',
             "300 +++ exited with 0 +++", "100 +++ exited with 0 +++"]
    events, _stats = reduce(tmp_path, lines)
    pats = {e["pattern"] for e in events if "/objects/" in e["pattern"]}
    assert pats == {"<project>/.git/objects/<obj>"}, pats


def test_git_reading_a_work_tree_against_its_index_is_not_its_callers_read(tmp_path):
    lines = [run(100, "/usr/bin/python3", "python3", "-m", "replay.inner"),
             "100 vfork() = 200", run(200, "/bin/bash", "bash", f"{H}/hooks/h.sh"),
             # `git diff`: the index, then the one file its stat data could not vouch for
             "200 vfork() = 201", run(201, "/usr/bin/git", "git", "diff", "--name-only"),
             opn(201, ".git/index"), opn(201, "README.md"), "201 +++ exited with 0 +++",
             # `git commit -F msg`: the message file its command line names is still read
             "200 vfork() = 202", run(202, "/usr/bin/git", "git", "commit", "-F", "msg.txt"),
             opn(202, ".git/index"), opn(202, "msg.txt"), opn(202, "toy.py"),
             opn(202, "toy.py", "O_WRONLY|O_CREAT|O_TRUNC, 0644"), "202 +++ exited with 0 +++",
             # a GIT_INDEX_FILE elsewhere in the git directory is an index too
             "200 vfork() = 203", run(203, "/usr/bin/git", "git", "write-tree"),
             opn(203, ".git/checkpoint-index.200.17"), opn(203, "toy.py"), "203 +++ exited with 0 +++",
             # hash-object loads no index: the files it is given are read
             "200 vfork() = 204", run(204, "/usr/bin/git", "git", "hash-object", "-w", "--stdin-paths"),
             opn(204, "notes.md"), "204 +++ exited with 0 +++",
             "200 +++ exited with 0 +++", "100 +++ exited with 0 +++"]
    events, stats = reduce(tmp_path, lines)
    kept = {(os.path.basename(e["raw"]), e["op"]) for e in events if not e["bulk"] and "/.git/" not in e["raw"]}
    assert ("README.md", "read") not in kept
    assert ("msg.txt", "read") in kept
    assert ("toy.py", "read") not in kept and ("toy.py", "write") in kept    # a write is never left out
    assert ("notes.md", "read") in kept
    assert stats["stat_reads"] == 3
