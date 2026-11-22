"""P12-L7's differential: every hook event a launcher runs, through the old path and the new one.

The new path is what the replay runs: a launcher (hooks/<event>-launch.py) runs the event's
Python hooks in its one process. The old path is each of those hooks as its own process, as
settings.json registered them before the launchers: `python3 <hook file>`, with the event's
payload on stdin, the env and working directory every hook gets, and its own timeout, one after
another in the launcher's order. Before each such event, the replay runs the old path in a
mount namespace of its own whose writable roots (HOME, the state dir and the temp dirs) are
overlays of the state the event meets (differential.OVERLAY, E1's), so it sees what the launcher
sees and nothing it writes survives; then the event runs as usual.

Per event, compare() returns the differences between the two paths:
- each hook's exit status, stdout and stderr (the old process's against the launcher's record
  of that hook);
- the event's answer: the launcher's own exit status, stdout and stderr against
  lib/hook_launch.combine over the old processes' results (what the CLI makes of those hooks).
Each side of a difference is quoted as the region around its first differing character (_region).

Normalised before comparing (and only this): the replay's own ids, times and sandbox roots, as
norm.refusal_text normalises a refusal, and the durations a hook prints ("12 ms", "0.31 s", "7h 59m";
on stderr, the only stream the short-window warning reaches, also "time budget <1h (9m)" and that
warning's presence at a 60-minute window), which are its own measurement and differ run to run.
One decision is let differ: when an overnight record's isolation window ends between the old path's
start and the launcher's end, a stdout that is exactly the write boundary's bwrap rewrite on the old
side against nothing on the launcher's (the window closed in between: _window_closed, _boundary_rewrite).
A replay with any difference reports it as
a driver error (Replay.finish), so every pipeline scenario of the suite asserts there is none.
REPLAY_LAUNCH_DIFFERENTIAL=0 turns it off for a local run; a traced replay never runs it (the
old path's processes would join the trace).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

from . import differential, hookrun

# A clock reading a hook prints ("Time remaining: 7h 59m", posttool-overnight-loop.py) moves when a
# minute boundary falls between the two runs, so it is a duration too, on every stream.
_DURATION = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds)\b|\b\d+h \d+m\b")
# So is the minute count of scripts/create-overnight-state.sh's short-window warning ("WARNING: time
# budget <1h (9m)", echoed to its stderr and passed on by prompt-workflow.py to its own stderr at
# /dev-overnight): (end - now) // 60 from the script's own two clock reads, one less when a second ticks
# between them (a relative end time, "10m") or when the two runs straddle a minute before the end (a
# clock time, "20:10"). Only that count, in that form, and only on stderr (each hook's and the answer's),
# is normalised: the warning never reaches stdout, so the same text on stdout is a hook's own output and
# a changed count there stays a difference (compare()).
_BUDGET_COUNT = re.compile(r"(?<=time budget <1h \()-?\d+m(?=\))")
# The same reads decide whether the warning is printed at all (the count under 60): with a 60-minute
# window one path prints it, "(59m)", and the other prints nothing. That line, at that count, is
# dropped from stderr when the other path has no such line (_budget_flip); any other missing warning is
# a difference.
_BUDGET_LINE = re.compile(r"^WARNING: time budget <1h \((-?\d+)m\)\. Recommended minimum: 1h for 1 pipeline; "
                          r"2h for 2-3 pipelines; 6h\+ for overnight\.(?:\n|$)", re.M)


def _budget_flip(a: str, b: str) -> tuple:
    """a and b with the short-window warning dropped from the one that has it at (59m) while the other
    has none (the two runs either side of the 60-minute mark); otherwise unchanged."""
    ma, mb = _BUDGET_LINE.search(a), _BUDGET_LINE.search(b)
    if ma and not mb and ma.group(1) == "59":
        a = a[:ma.start()] + a[ma.end():]
    elif mb and not ma and mb.group(1) == "59":
        b = b[:mb.start()] + b[mb.end():]
    return a, b

# A difference is quoted as the region around its first differing character: _BEFORE characters
# ahead of it and the rest of _REGION after it, "..." where a side is cut. Quoting each side's last
# 600 characters hid a difference further back, and old and new then read identical (replay shard
# 6/6: a 979-character stderr whose one difference was its head). The region, markers included,
# fits the 300 characters Replay.finish quotes of the first difference.
_REGION, _BEFORE, _CUT = 290, 120, "..."


def _region(a: str, b: str) -> tuple:
    """`a` and `b`, each cut to the same window around their first difference."""
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    start = max(0, i - _BEFORE)

    def cut(s):
        return (_CUT if start else "") + s[start:start + _REGION] + (_CUT if start + _REGION < len(s) else "")
    return cut(a), cut(b)


_LIBS: dict = {}


def _settings_lib(harness: str):
    """hooks/lib/launch_settings.py of the tree under test (the launchers' table reader)."""
    if harness in _LIBS:
        return _LIBS[harness]
    import importlib.util
    path = os.path.join(harness, "hooks", "lib", "launch_settings.py")
    spec = importlib.util.spec_from_file_location("_launch_settings", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _LIBS[harness] = mod
    return mod


def launcher_rules(harness: str, hook: str) -> list | None:
    """(file, tools, timeout) of the RULES table of the launcher `hook` (hooks/x.py); None when the
    file is no launcher."""
    if not os.path.isfile(os.path.join(harness, "hooks", "lib", "launch_settings.py")):
        return None
    return _settings_lib(harness).rules(harness, hook)


def old_path(harness: str, launched: dict, event: str, payload: dict) -> list:
    """The old registrations a launcher's record stands for, for this call, in its order."""
    rules = launcher_rules(harness, launched["hook"]) or []
    tool = payload.get("tool_name") if event in hookrun.TOOL_EVENTS else None
    return [{"hook": "hooks/" + f, "matcher": "|".join(t) if t else None, "timeout": to,
             # a shell hook was registered, and is launched, as `bash <file>` (hooks/pretool-launch.py)
             "command": (hookrun.LAUNCHED_COMMAND.replace("python3 ", "bash ", 1) if f.endswith(".sh")
                         else hookrun.LAUNCHED_COMMAND) % ("hooks/" + f)}
            for f, t, to in rules if tool is None or t is None or tool in t]


def run_old(layout, hooks: list, payload_raw: str, env: dict, cwd: str) -> list:
    """Each hook of `hooks` as its own process, in an overlay of the current state."""
    lay = layout.to_json()
    roots = differential._roots(lay)
    spec = json.dumps({"hooks": hooks, "payload": payload_raw, "env": env, "cwd": cwd})
    inner = {"PATH": layout.path, "HOME": layout.home, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
             "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}
    argv = ["unshare", "--mount", "--propagation", "private", "bash", "-c", differential.OVERLAY, "overlay",
            *roots, "--", "--", "none", "", "", "env", "-i", *[f"{k}={v}" for k, v in sorted(inner.items())],
            sys.executable, "-m", f"{__package__}.launchdiff"]
    timeout = sum(int(h["timeout"] or hookrun.DEFAULT_TIMEOUT_S) for h in hooks) + 30
    started = time.time()  # compare() reads it: the clock the old path's first hook can meet (_window_closed)
    p = subprocess.run(argv, input=spec, capture_output=True, text=True, cwd=cwd, timeout=timeout, errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"the old path's runner exited {p.returncode}: {p.stderr[-800:]}")
    return [dict(r, started=started) for r in json.loads(p.stdout)]


def _window_closed(project: str, since: float, until: float) -> bool:
    """True iff an overnight record of `project` ends its isolation window (isolation_active_until, else
    end_time: lib/overnight.state_verdicts) between `since` and `until`: the old path ran inside the window
    and the launcher, after it, may have met it closed."""
    from datetime import datetime, timezone
    claude = os.path.join(project, ".claude")
    try:
        names = [n for n in os.listdir(claude) if n.startswith("overnight-state-") and n.endswith(".json")]
    except OSError:
        return False
    for name in names:
        try:
            with open(os.path.join(claude, name)) as fh:
                rec = json.load(fh)
            end = datetime.fromisoformat(str(rec.get("isolation_active_until") or rec.get("end_time"))
                                         .strip().replace("Z", "+00:00"))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
        if since <= end.timestamp() <= until:
            return True
    return False


def _boundary_rewrite(stdout: str) -> bool:
    """True iff `stdout` is exactly the overnight write boundary's answer (pretool-overnight-hook-guard.py
    _emit_command_rewrite): a PreToolUse updatedInput whose command is a bwrap re-exec, and nothing else."""
    try:
        d = json.loads(stdout)
        hso = d["hookSpecificOutput"]
        cmd = hso["updatedInput"]["command"]
    except (ValueError, TypeError, KeyError):
        return False
    return (set(d) == {"hookSpecificOutput"} and set(hso) == {"hookEventName", "updatedInput"}
            and isinstance(cmd, str) and os.path.basename(cmd.split(" ", 1)[0]) == "bwrap")


def _combine(harness: str, event: str, old: list) -> tuple:
    """lib/hook_launch.combine (the tree under test's) over the old processes' results."""
    sys.path.insert(0, os.path.join(harness, "hooks"))
    try:
        from lib import hook_launch
    finally:
        sys.path.pop(0)

    class _R:
        def __init__(self, r):
            self.rule = hook_launch.Rule(r["hook"], r["hook"][len("hooks/"):], None, r.get("timeout") or 60)
            self.code = r["rc"] if r["rc"] != "timeout" else hook_launch.TIMEOUT
            self.stdout, self.stderr = r["stdout"], r["stderr"]
    return hook_launch.combine(event, [_R(r) for r in old])


def compare(rp, event: str, launched: dict, old: list) -> list:
    """The differences between the launcher's record and the old path's, normalised."""
    def n(text, stderr):
        text = _DURATION.sub("<duration>", rp.norm_text(text or ""))
        return _BUDGET_COUNT.sub("<duration>", text) if stderr else text

    def pair(a, b, stderr):
        a, b = a or "", b or ""
        if stderr:
            a, b = _budget_flip(a, b)
        return n(a, stderr), n(b, stderr)
    tail = hookrun.TAIL
    # The one expected decision change: the isolation window closed between the old path's run and the
    # launcher's, so the old one was handed the boundary's bwrap rewrite and the launcher, rightly, nothing.
    closed = bool(old) and _window_closed(rp.layout.project, min(r.get("started", 0) for r in old), time.time())

    def window_moved(full_old, b):
        return closed and not b and _boundary_rewrite(full_old)
    old_full, old = old, [dict(r, stdout=r["stdout"][-tail:], stderr=r["stderr"][-tail:]) for r in old]
    diffs = []
    new = launched.get("rules") or []
    if [r["hook"] for r in new] != [r["hook"] for r in old]:
        diffs.append({"what": "hooks run", "old": [r["hook"] for r in old], "new": [r["hook"] for r in new]})
    for o, of, w in zip(old, old_full, new):
        for key in ("rc", "stdout", "stderr"):
            a, b = o[key], w[key]
            if key != "rc":
                a, b = pair(a, b, key == "stderr")
            if key == "stdout" and window_moved(of["stdout"], w["stdout"]):
                continue
            if a != b:
                a, b = _region(str(a), str(b))
                diffs.append({"what": f"{o['hook']} {key}", "old": a, "new": b})
    code, out, err = _combine(rp.layout.harness, event, old_full)
    for key, a, b in (("rc", code, launched["rc"]), ("stdout", *pair(out[-tail:], launched.get("stdout"), False)),
                      ("stderr", *pair(err[-tail:], launched.get("stderr"), True))):
        if key == "stdout" and window_moved(out, launched.get("stdout")):
            continue
        if a != b:
            a, b = _region(str(a), str(b))
            diffs.append({"what": f"answer {key}", "old": a, "new": b})
    return diffs


def _main() -> int:
    """Inside the overlay: each hook as its own process, its whole output kept (combine() reads a
    JSON answer whole; compare() cuts both paths to the replay's kept tail)."""
    spec = json.load(sys.stdin)
    out = []
    for h in spec["hooks"]:
        timeout = int(h["timeout"] or hookrun.DEFAULT_TIMEOUT_S)
        try:
            p = subprocess.run(h["command"], shell=True, input=spec["payload"], capture_output=True, text=True,
                               env=spec["env"], cwd=spec["cwd"], timeout=timeout, errors="replace")
            rc, o, e = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            rc, o, e = "timeout", "", "timeout"
        out.append({"hook": h["hook"], "timeout": timeout, "rc": rc, "stdout": o, "stderr": e})
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
