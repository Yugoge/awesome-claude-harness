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

The Write call is the Edit call's payload with tool_name Write (a new file, NOTES.md); the Read
call is the smoke replay's main-agent Read.

What a call waits for (the "wait" table): the CLI starts every hook an event registers at once
and the call goes on when the last one has ended. So each call's events also run N times that way,
each run from the same saved state: all the event's selected hooks (settings.json's registrations,
matchers applied) are started at the same moment, one thread each, and the wait is the time from
the first start to the last end. Reported per call: PreToolUse, PostToolUse and Pre + Post (median,
min and max over the N runs), the CPU time of every process the hooks started in those runs, each
started process's own time and, for a launcher, each of its rules' own time (the launcher's record,
hookrun.RECORD_ENV), and the "slowest alone" model (per event, the slowest started process of the
one-after-another runs: what the call would wait for on enough cores).

The saved state is the state dir, the project's .claude/ and .git, and the harness home's state/
(a directory missing when it was saved is removed again). --state fresh empties the state dir and
removes the project's .claude/ and the harness home's state/ after the smoke replay, so every
call meets a session's first-call state with the smoke replay's transcript and files;
--transcript-mb M makes the main transcript M MiB, with an earlier conversation (prompts, Reads
and their results, answers) put before the smoke replay's own records, the same for every tree
but the session id.

DIR/launch-cost.json holds the result (DIR/launch-cost-meta.json what it was measured on); the
tables go to stdout.
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
import threading
import time
import uuid

if __package__ in (None, ""):  # pragma: no cover
    sys.exit("run as: python -m tests.replay.launch_cost")

from . import hookrun

CALLS = (("Bash", "main Bash git-status"), ("Write", "main Edit"), ("Edit", "main Edit"),
         ("Agent", "main Agent(Explore)"), ("Read", "main Read"))
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
    """The state directories, saved once and put back before each run (one missing when saved is
    removed again)."""

    def __init__(self, dirs):
        self.dirs = list(dirs)
        self.saved = tempfile.mkdtemp(prefix="launch-cost-")
        for i, d in enumerate(self.dirs):
            if os.path.isdir(d):
                shutil.copytree(d, os.path.join(self.saved, str(i)), symlinks=True)

    def restore(self) -> None:
        for i, d in enumerate(self.dirs):
            if os.path.isdir(d):
                shutil.rmtree(d)
            if os.path.isdir(os.path.join(self.saved, str(i))):
                shutil.copytree(os.path.join(self.saved, str(i)), d, symlinks=True)


def _fresh(state_dir: str, removed) -> None:
    """A session's first-call state: the state dir emptied, the other state directories removed."""
    for name in os.listdir(state_dir) if os.path.isdir(state_dir) else ():
        p = os.path.join(state_dir, name)
        shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)
    for d in removed:
        if os.path.isdir(d):
            shutil.rmtree(d)


_FILLER_TEXT = ("The module keeps one decision per call and writes it before it answers; a reader of the "
                "record finds the call, the rule that decided it and the reason it gave, in that order.\n")


def _pad_transcript(path: str, project: str, mib: float) -> int:
    """Put an earlier conversation before the transcript's own records until it holds `mib` MiB;
    returns its size. The filler is the same for every tree (fixed ids and times; the session id is
    the transcript's own)."""
    with open(path, "rb") as fh:
        own = fh.read()
    want = int(mib * 1024 * 1024) - len(own)
    if want <= 0:
        return len(own)
    first = {}
    for line in own.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") in ("user", "assistant"):
            first = r
            break
    sid, version = first.get("sessionId", ""), first.get("version", "")
    ns = uuid.UUID("6b2f0c1e-6c1a-4d3e-9a51-2f7d1c0e5a10")
    lines, size, parent, n = [], 0, None, 0

    def rec(kind, message, **extra):
        nonlocal parent, n
        n += 1
        r = {"type": kind, "message": message, "uuid": str(uuid.uuid5(ns, str(n))), "parentUuid": parent,
             "isSidechain": False, "userType": "external", "cwd": project, "sessionId": sid,
             "version": version, "timestamp": "2026-01-01T00:%02d:%02d.000Z" % (n // 60 % 60, n % 60), **extra}
        parent = r["uuid"]
        return json.dumps(r) + "\n"

    turn = 0
    while size < want:
        turn += 1
        path_i = f"{project}/docs/notes-{turn % 40}.md"
        body = _FILLER_TEXT * 22
        tid = "toolu_filler%08d" % turn
        for line in (
                rec("user", {"role": "user", "content": f"Summarise part {turn} of the design notes in a few sentences."}),
                rec("assistant", {"role": "assistant", "model": "claude-opus-5-5",
                                  "content": [{"type": "tool_use", "id": tid, "name": "Read",
                                               "input": {"file_path": path_i}}]}),
                rec("user", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": body}]},
                    toolUseResult={"type": "text", "file": {"filePath": path_i, "content": body, "numLines": 22,
                                                             "startLine": 1, "totalLines": 22}}),
                rec("assistant", {"role": "assistant", "model": "claude-opus-5-5",
                                  "content": [{"type": "text", "text": _FILLER_TEXT * 3}]})):
            lines.append(line)
            size += len(line)
    with open(path, "wb") as fh:
        fh.write("".join(lines).encode())
        fh.write(own)
    return os.path.getsize(path)


def _run_hooks(settings, event, payload, env, cwd) -> tuple[list, float, float]:
    """The event's hooks one after another, as hookrun runs them: per-hook (hook, cpu, rc, ms), wall, cpu."""
    payload = dict(payload, hook_event_name=event)
    raw = json.dumps(payload)
    rows, t0, c0 = [], time.monotonic(), _cpu()
    for h in hookrun.select(settings, event, payload):
        c = _cpu()
        rec = hookrun._run_one(h, raw, env, cwd)
        rows.append((h["hook"], _cpu() - c, rec["rc"], rec["ms"]))
    return rows, time.monotonic() - t0, _cpu() - c0


def _wait_hooks(settings, event, payload, env, cwd) -> tuple[float, list]:
    """The event's hooks all started at the same moment, as the CLI starts them: (the time from the
    first start to the last end, each started process's record as hookrun._run_one gives it)."""
    payload = dict(payload, hook_event_name=event)
    raw = json.dumps(payload)
    hooks = hookrun.select(settings, event, payload)
    if not hooks:
        return 0.0, []
    go = threading.Barrier(len(hooks))
    done: list = [None] * len(hooks)

    def one(i, h):
        go.wait()
        t = time.monotonic()
        rec = hookrun._run_one(h, raw, env, cwd)
        done[i] = (t, t + rec["ms"] / 1000, rec)  # rec["ms"]: from its start to its process's end

    threads = [threading.Thread(target=one, args=(i, h)) for i, h in enumerate(hooks)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return max(e for _s, e, _r in done) - min(s for s, _e, _r in done), [r for _s, _e, r in done]


def _spread(values) -> dict:
    """The median, min and max in ms of values in seconds, and every run's."""
    ms = [round(v * 1000) for v in values]
    return {"median_ms": round(statistics.median(values) * 1000), "min_ms": min(ms), "max_ms": max(ms),
            "runs_ms": ms}


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
    if cfg.get("state") == "fresh":
        _fresh(cfg["state_dirs"][0], cfg["fresh_removed"])
    meta = {"transcripts": {}}
    for tpath in sorted({p.get("transcript_path") for p in payloads.values() if p.get("transcript_path")}):
        size = _pad_transcript(tpath, cfg["project"], cfg["transcript_mb"]) if cfg.get("transcript_mb") \
            else os.path.getsize(tpath)
        meta["transcripts"][tpath] = size
    meta.update(state=cfg.get("state", "smoke"), repeat=cfg["repeat"], cpus=os.cpu_count(),
                state_dirs=cfg["state_dirs"])
    with open(cfg["result"][:-len(".json")] + "-meta.json", "w") as fh:
        json.dump(meta, fh, indent=1)
    state = _State(cfg["state_dirs"])
    out = {}
    for call, _label in CALLS:
        walls, cpus, per, alone = [], [], {}, []
        for n in range(cfg["repeat"] + 1):
            state.restore()
            wall = cpu = slowest = 0.0
            for ev in EVENTS:
                rows, w, c = _run_hooks(settings, ev, payloads[(call, ev)], env, cfg["project"])
                wall, cpu = wall + w, cpu + c
                slowest += max((ms for *_x, ms in rows), default=0) / 1000
                if n:
                    for hook, hc, rc, _ms in rows:
                        per.setdefault(f"{ev} {hook}", []).append(hc)
            if n:  # the first run warms the page cache and is left out
                walls.append(wall)
                cpus.append(cpu)
                alone.append(slowest)
        waits: dict = {ev: [] for ev in EVENTS}
        waits["total"], wcpus, procs_ms, rules_ms, verdicts = [], [], {}, {}, {}
        for n in range(cfg["repeat"] + 1):
            state.restore()
            total, c0 = 0.0, _cpu()
            for ev in EVENTS:
                w, recs = _wait_hooks(settings, ev, payloads[(call, ev)], env, cfg["project"])
                total += w
                if not n:
                    continue
                waits[ev].append(w)
                for rec in recs:
                    key = f"{ev} {rec['hook']}"
                    procs_ms.setdefault(key, []).append(rec["ms"] / 1000)
                    verdicts.setdefault(key, set()).add(rec["verdict"])
                    for r in rec.get("rules", []):
                        rules_ms.setdefault(key, {}).setdefault(r["hook"], []).append(r["ms"] / 1000)
                        verdicts.setdefault(f"{key} > {r['hook']}", set()).add(r["verdict"])
            if n:  # the first run warms the page cache and is left out
                waits["total"].append(total)
                wcpus.append(_cpu() - c0)
        state.restore()
        procs, pythons = _count(cfg, call)
        state.restore()
        out[call] = {"processes": procs, "python": pythons,
                     "hooks": sum(len(hookrun.select(settings, ev, dict(payloads[(call, ev)], hook_event_name=ev)))
                                  for ev in EVENTS),
                     "wall_ms": round(statistics.median(walls) * 1000), "cpu_ms": round(statistics.median(cpus) * 1000),
                     "per_hook_cpu_ms": {k: round(statistics.median(v) * 1000, 1)
                                         for k, v in sorted(per.items(), key=lambda kv: -statistics.median(kv[1]))},
                     "wait": {k: _spread(v) for k, v in waits.items()},
                     "wait_cpu": _spread(wcpus),
                     "slowest_alone_ms": round(statistics.median(alone) * 1000),
                     "wait_per_process_ms": {k: round(statistics.median(v) * 1000, 1) for k, v in procs_ms.items()},
                     "wait_per_rule_ms": {k: {h: round(statistics.median(v) * 1000, 1) for h, v in rs.items()}
                                          for k, rs in rules_ms.items()},
                     "verdicts": {k: "/".join(sorted(v)) for k, v in verdicts.items()}}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.replay.launch_cost", description=__doc__.split("\n")[0])
    ap.add_argument("--tree")
    ap.add_argument("--work")
    ap.add_argument("--settings", default="shipped", help="shipped, or a settings file path")
    ap.add_argument("--repeat", type=int, default=9)
    ap.add_argument("--state", choices=("smoke", "fresh"), default="smoke",
                    help="the state every run starts from: as the smoke replay leaves it, or a first call's")
    ap.add_argument("--transcript-mb", type=float, default=0,
                    help="pad the main transcript to this many MiB (0: as the smoke replay leaves it)")
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
           "project": lay.project, "repeat": a.repeat, "result": lay.out + "/launch-cost.json",
           "state_dirs": [lay.state, lay.project + "/.claude", lay.project + "/.git", lay.harness + "/state"],
           "fresh_removed": [lay.project + "/.claude", lay.harness + "/state"],
           "state": a.state, "transcript_mb": a.transcript_mb}
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
    shutil.copyfile(os.path.join(sb, "out", "launch-cost-meta.json"), os.path.join(work, "launch-cost-meta.json"))
    print("call\thooks\tprocesses\tpython\twall_ms\tcpu_ms")
    for call, r in res.items():
        print(f"{call}\t{r['hooks']}\t{r['processes']}\t{r['python']}\t{r['wall_ms']}\t{r['cpu_ms']}")
    for call, r in res.items():
        print(f"\n{call}: CPU per hook (ms)")
        for k, v in r["per_hook_cpu_ms"].items():
            print(f"  {v:8.1f}  {k}")
    print("\nwait (ms, median [min-max])\tPreToolUse\tPostToolUse\tPre+Post\tcpu\tslowest alone")
    for call, r in res.items():
        cols = [f"{w['median_ms']} [{w['min_ms']}-{w['max_ms']}]"
                for w in (r["wait"]["PreToolUse"], r["wait"]["PostToolUse"], r["wait"]["total"], r["wait_cpu"])]
        print(f"{call}\t" + "\t".join(cols) + f"\t{r['slowest_alone_ms']}")
    for call, r in res.items():
        print(f"\n{call}: wait per started process (ms), and a launcher's rules")
        for k, v in r["wait_per_process_ms"].items():
            print(f"  {v:8.1f}  {k}  {r['verdicts'].get(k, '')}")
            for h, ms in r["wait_per_rule_ms"].get(k, {}).items():
                print(f"  {ms:8.1f}      {h}  {r['verdicts'].get(f'{k} > {h}', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
