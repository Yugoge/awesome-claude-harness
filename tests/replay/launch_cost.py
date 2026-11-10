"""What one tool call's hooks cost: processes started, wall time and CPU time (P12-L7).

    python -m tests.replay.launch_cost --tree T --work DIR [--settings FILE] [--repeat N]

It builds (or reuses) a sandbox of the tree T in DIR/sb, runs the smoke driver once (plain, mode ns)
so the hooks meet the state a real session leaves, and then, inside the sandbox's namespace, fires
the PreToolUse and PostToolUse events of one main-agent Bash, Write, Edit and Agent call as the
replay fires them (hookrun.run_event, the registered hooks in registration order, the env every
hook got). Each call's events run N times, each time from the same saved state (the state dir and
the project's .claude/ are put back before every run, so a counter a hook keeps never changes what
the next run decides), and the medians are reported:

* processes: the processes the call's hooks start (every fork, vfork or clone that is not a
  thread, counted by strace over one extra run), and of those the Python interpreters;
* wall: the time the events take, hook after hook (the CLI runs them side by side, so this is
  the work, not the latency the user sees);
* cpu: user + system CPU time of every process the hooks start;
* per hook: each registered hook's own CPU time, from the same runs.

The Write call is the Edit call's payload with tool_name Write (a new file, NOTES.md).
DIR/launch-cost.json holds the result; the table goes to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

if __package__ in (None, ""):  # pragma: no cover
    sys.exit("run as: python -m tests.replay.launch_cost")

from . import hookrun

CALLS = (("Bash", "main Bash git-status"), ("Write", "main Edit"), ("Edit", "main Edit"),
         ("Agent", "main Agent(Explore)"))
EVENTS = ("PreToolUse", "PostToolUse")


def _cpu() -> float:
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return ru.ru_utime + ru.ru_stime


def _payloads(invocations: str, project: str) -> dict:
    """{(call, event): payload} from the smoke replay's invocations.jsonl."""
    by = {}
    with open(invocations) as fh:
        for line in fh:
            r = json.loads(line)
            by.setdefault((r["label"], r["event"]), r["payload"])
    out = {}
    for call, label in CALLS:
        for ev in EVENTS:
            p = dict(by[(label, ev)])
            if call == "Write":
                path = os.path.join(project, "NOTES.md")
                p["tool_name"] = "Write"
                p["tool_input"] = {"file_path": path, "content": "# notes\n\nadd and sub.\n"}
                if ev == "PostToolUse":
                    p["tool_response"] = {"type": "create", "filePath": path,
                                          "content": p["tool_input"]["content"], "structuredPatch": []}
            out[(call, ev)] = p
    return out


class _State:
    """The state dir and the project's .claude/, saved once and put back before each run."""

    def __init__(self, dirs):
        self.dirs = [d for d in dirs if os.path.isdir(d)]
        self.saved = tempfile.mkdtemp(prefix="launch-cost-")
        for i, d in enumerate(self.dirs):
            shutil.copytree(d, os.path.join(self.saved, str(i)), symlinks=True)

    def restore(self) -> None:
        for i, d in enumerate(self.dirs):
            shutil.rmtree(d)
            shutil.copytree(os.path.join(self.saved, str(i)), d, symlinks=True)


def _run_hooks(settings, event, payload, env, cwd) -> tuple[list, float, float]:
    """The event's hooks one after another, as hookrun runs them: per-hook (hook, cpu, rc), wall, cpu."""
    payload = dict(payload, hook_event_name=event)
    raw = json.dumps(payload)
    rows, t0, c0 = [], time.monotonic(), _cpu()
    for h in hookrun.select(settings, event, payload):
        c = _cpu()
        rec = hookrun._run_one(h, raw, env, cwd)
        rows.append((h["hook"], _cpu() - c, rec["rc"]))
    return rows, time.monotonic() - t0, _cpu() - c0


_CLONE = re.compile(r"^(\d+)\s+(clone3?|fork|vfork)\((.*)\)\s+=\s+(\d+)")
_EXEC = re.compile(r'^(\d+)\s+execve\("([^"]+)".*\)\s+=\s+0$')


def _count(cfg: dict, call: str) -> tuple[int, int]:
    """(processes, python interpreters) one run of the call's events starts, by strace."""
    with tempfile.TemporaryDirectory() as tmp:
        spec = os.path.join(tmp, "spec.json")
        with open(spec, "w") as fh:
            json.dump(dict(cfg, only=call), fh)
        log = os.path.join(tmp, "strace.txt")
        subprocess.run(["strace", "-f", "-qq", "-s", "4096", "-o", log, "-e", "trace=clone,clone3,fork,vfork,execve",
                        sys.executable, "-m", f"{__package__}.launch_cost", "--once", spec], check=True)
        procs, pythons, root = 0, 0, None
        pending: dict = {}  # pid -> a call strace split in two ("<unfinished ...>", "<... resumed>")
        with open(log, errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                pid, _, rest = line.partition(" ")
                if root is None:
                    root = pid
                if rest.endswith("<unfinished ...>"):
                    pending[pid] = line[:-len("<unfinished ...>")].rstrip()
                    continue
                m = re.match(r"\s*<\.\.\. \w+ resumed>(.*)$", rest)
                if m:
                    line = pending.pop(pid, line) + m.group(1)
                m = _CLONE.match(line)
                if m and "CLONE_THREAD" not in m.group(3):
                    procs += 1
                m = _EXEC.match(line)
                if m and m.group(1) != root and re.match(r"python3?(\.\d+)?$", os.path.basename(m.group(2))):
                    pythons += 1  # an interpreter started (the measuring process itself left out)
        return procs, pythons


def _inner(cfg: dict) -> dict:
    with open(cfg["settings"]) as fh:
        settings = json.load(fh)
    with open(cfg["env"]) as fh:
        env = json.load(fh)
    payloads = _payloads(cfg["invocations"], cfg["project"])
    if cfg.get("only"):  # one untimed run, for _count
        for ev in EVENTS:
            _run_hooks(settings, ev, payloads[(cfg["only"], ev)], env, cfg["project"])
        return {}
    state = _State(cfg["state_dirs"])
    out = {}
    for call, _label in CALLS:
        walls, cpus, per = [], [], {}
        for n in range(cfg["repeat"] + 1):
            state.restore()
            wall = cpu = 0.0
            for ev in EVENTS:
                rows, w, c = _run_hooks(settings, ev, payloads[(call, ev)], env, cfg["project"])
                wall, cpu = wall + w, cpu + c
                if n:
                    for hook, hc, rc in rows:
                        per.setdefault(f"{ev} {hook}", []).append(hc)
            if n:  # the first run warms the page cache and is left out
                walls.append(wall)
                cpus.append(cpu)
        state.restore()
        procs, pythons = _count(cfg, call)
        state.restore()
        out[call] = {"processes": procs, "python": pythons,
                     "hooks": sum(len(hookrun.select(settings, ev, dict(payloads[(call, ev)], hook_event_name=ev)))
                                  for ev in EVENTS),
                     "wall_ms": round(statistics.median(walls) * 1000), "cpu_ms": round(statistics.median(cpus) * 1000),
                     "per_hook_cpu_ms": {k: round(statistics.median(v) * 1000, 1)
                                         for k, v in sorted(per.items(), key=lambda kv: -statistics.median(kv[1]))}}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.replay.launch_cost", description=__doc__.split("\n")[0])
    ap.add_argument("--tree")
    ap.add_argument("--work")
    ap.add_argument("--settings", default="shipped", help="shipped, or a settings file path")
    ap.add_argument("--repeat", type=int, default=9)
    ap.add_argument("--inner", help=argparse.SUPPRESS)
    ap.add_argument("--once", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.inner or a.once:
        with open(a.inner or a.once) as fh:
            cfg = json.load(fh)
        res = _inner(cfg)
        if a.inner:
            with open(cfg["result"], "w") as fh:
                json.dump(res, fh, indent=1)
        return 0
    from . import cli, sandbox
    tree, work = os.path.abspath(a.tree), os.path.abspath(a.work)
    sb = os.path.join(work, "sb")
    if not os.path.isfile(os.path.join(sb, sandbox.MARK)) or sandbox.info(sb).get("tree") != tree:
        sandbox.build(tree, sb)
    smoke = os.path.join(work, "smoke")
    row = cli.run_one(sb, tree, smoke, driver="smoke", mode="ns", settings=a.settings, env={}, kind="plain",
                      guard=False, parallel=False, keep_raw=False)
    if row.get("driver_error") or row.get("rc"):
        raise SystemExit(f"the smoke replay failed: {row.get('driver_error') or row.get('rc')}")
    lay = sandbox.layout_for(sb, "ns")
    _label, spath = sandbox.settings_file(sb, "ns", a.settings)
    shutil.copytree(smoke, os.path.join(sb, "out", "smoke"), dirs_exist_ok=True)
    cfg = {"settings": spath, "env": lay.out + "/smoke/env.json", "invocations": lay.out + "/smoke/invocations.jsonl",
           "project": lay.project, "state_dirs": [lay.state, lay.project + "/.claude"], "repeat": a.repeat,
           "result": lay.out + "/launch-cost.json"}
    with open(os.path.join(sb, "launch-cost.json"), "w") as fh:
        json.dump(cfg, fh)
    env_inner = {"PATH": lay.path, "HOME": lay.home, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONPATH": lay.sb}
    rc = sandbox.launch(sb, lay, [lay.python, "-m", "replay.launch_cost", "--inner", lay.sb + "/launch-cost.json"],
                        env_inner)
    if rc:
        return rc
    with open(os.path.join(sb, "out", "launch-cost.json")) as fh:
        res = json.load(fh)
    with open(os.path.join(work, "launch-cost.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    print("call\thooks\tprocesses\tpython\twall_ms\tcpu_ms")
    for call, r in res.items():
        print(f"{call}\t{r['hooks']}\t{r['processes']}\t{r['python']}\t{r['wall_ms']}\t{r['cpu_ms']}")
    for call, r in res.items():
        print(f"\n{call}: CPU per hook (ms)")
        for k, v in r["per_hook_cpu_ms"].items():
            print(f"  {v:8.1f}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
