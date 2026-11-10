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

Normalised before comparing (and only this): the replay's own ids, times and sandbox roots, as
norm.refusal_text normalises a refusal, and the durations a hook prints ("12 ms", "0.31 s"),
which are its own measurement and differ run to run. A replay with any difference reports it as
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

from . import differential, hookrun

_DURATION = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds)\b")


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
             "command": hookrun.LAUNCHED_COMMAND % ("hooks/" + f)}
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
    p = subprocess.run(argv, input=spec, capture_output=True, text=True, cwd=cwd, timeout=timeout, errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"the old path's runner exited {p.returncode}: {p.stderr[-800:]}")
    return json.loads(p.stdout)


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
    def n(text):
        return _DURATION.sub("<duration>", rp.norm_text(text or ""))
    tail = hookrun.TAIL
    old_full, old = old, [dict(r, stdout=r["stdout"][-tail:], stderr=r["stderr"][-tail:]) for r in old]
    diffs = []
    new = launched.get("rules") or []
    if [r["hook"] for r in new] != [r["hook"] for r in old]:
        diffs.append({"what": "hooks run", "old": [r["hook"] for r in old], "new": [r["hook"] for r in new]})
    for o, w in zip(old, new):
        for key in ("rc", "stdout", "stderr"):
            a, b = o[key], w[key]
            if key != "rc":
                a, b = n(a), n(b)
            if a != b:
                diffs.append({"what": f"{o['hook']} {key}", "old": str(a)[-600:], "new": str(b)[-600:]})
    code, out, err = _combine(rp.layout.harness, event, old_full)
    for key, a, b in (("rc", code, launched["rc"]), ("stdout", n(out[-tail:]), n(launched.get("stdout"))),
                      ("stderr", n(err[-tail:]), n(launched.get("stderr")))):
        if a != b:
            diffs.append({"what": f"answer {key}", "old": str(a)[-600:], "new": str(b)[-600:]})
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
