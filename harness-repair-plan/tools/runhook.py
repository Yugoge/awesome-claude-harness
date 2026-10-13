#!/usr/bin/env python3
"""Replay Claude Code hook events against a settings.json, inside the sandbox namespace.

Usage: runhook.py --settings S --event E --payload FILE|- [--label L] [--log LOG] [--no-snap]
Emits one JSON record per event to --log (appends) and a human summary to stdout.
"""
import argparse, json, os, re, subprocess, sys, time

RV_HOME = os.environ.get("RV_HOME", "/root")
RV_CLAUDE = os.environ.get("RV_CLAUDE", RV_HOME + "/.claude")
SNAP_ROOTS = ["/tmp", "/var/tmp", "/dev/shm", RV_HOME] + (["/root"] if RV_HOME != "/root" else [])
SNAP_EXCLUDE = [RV_CLAUDE + "/venv", RV_CLAUDE + "/.git/objects", "/root/.ccr", RV_CLAUDE + "/.git/logs"]

TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"}


def matches(matcher, value):
    if matcher in (None, "", "*"):
        return True
    if re.fullmatch(r"[A-Za-z0-9_|]+", matcher):
        return value in matcher.split("|")
    try:
        return re.search(matcher, value or "") is not None
    except re.error:
        return False


def match_value(event, payload):
    if event in TOOL_EVENTS:
        return payload.get("tool_name", "")
    if event == "SessionStart":
        return payload.get("source", "")
    if event == "Notification":
        return payload.get("notification_type", "")
    if event == "SessionEnd":
        return payload.get("reason", "")
    if event in ("SubagentStop", "SubagentStart"):
        return payload.get("agent_type", "")
    return None  # matcher ignored


def snapshot():
    snap = {}
    for root in SNAP_ROOTS:
        for dp, dns, fns in os.walk(root):
            if any(dp == ex or dp.startswith(ex + "/") for ex in SNAP_EXCLUDE):
                dns[:] = []
                continue
            for fn in fns:
                p = os.path.join(dp, fn)
                try:
                    st = os.lstat(p)
                    snap[p] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    pass
    return snap


def diff(a, b):
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(p for p in set(a) & set(b) if a[p] != b[p])
    return {"added": added, "removed": removed, "changed": changed}


def build_env(settings, cwd, extra=None):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": RV_HOME, "USER": os.path.basename(RV_HOME), "LOGNAME": os.path.basename(RV_HOME), "SHELL": "/bin/bash",
        "LANG": "C.UTF-8", "TERM": "xterm-256color",
        "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli",
        "CLAUDE_PROJECT_DIR": cwd,
    }
    for k, v in (settings.get("env") or {}).items():
        env[k] = v if isinstance(v, str) else json.dumps(v)
    if extra:
        env.update(extra)
    return env


def interpret(event, rc, out):
    verdict = {0: "ok", 2: "BLOCK(exit2)"}.get(rc, f"HOOK-ERROR(exit{rc})")
    j = None
    s = out.strip()
    if rc == 0 and s.startswith("{"):
        try:
            j = json.loads(s)
        except Exception:
            j = None
    if isinstance(j, dict):
        hso = j.get("hookSpecificOutput") or {}
        pd = hso.get("permissionDecision")
        if pd in ("deny", "ask"):
            verdict = f"BLOCK(json:{pd})" if pd == "deny" else "ASK(json)"
        if j.get("decision") == "block":
            verdict = "BLOCK(json:decision=block)"
        if j.get("continue") is False:
            verdict = "STOP(json:continue=false)"
    return verdict, j


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", required=True)
    ap.add_argument("--event", required=True)
    ap.add_argument("--payload", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--log", default=None)
    ap.add_argument("--no-snap", action="store_true")
    ap.add_argument("--env", action="append", default=[])
    a = ap.parse_args()
    settings = json.load(open(a.settings))
    payload_raw = sys.stdin.read() if a.payload == "-" else open(a.payload).read()
    payload = json.loads(payload_raw)
    payload.setdefault("hook_event_name", a.event)
    payload_raw = json.dumps(payload)
    cwd = payload.get("cwd", "/root")
    extra = dict(kv.split("=", 1) for kv in a.env)
    env = build_env(settings, cwd, extra)
    mv = match_value(a.event, payload)
    hooks, seen = [], set()
    for grp in (settings.get("hooks") or {}).get(a.event, []):
        m = grp.get("matcher")
        if mv is not None and not matches(m, mv):
            continue
        for h in grp.get("hooks", []):
            c = h.get("command")
            if c in seen:
                continue
            seen.add(c)
            hooks.append((m, c, h.get("timeout", 60)))
    before = None if a.no_snap else snapshot()
    results = []
    t_all = time.monotonic()
    def run_one(item):
        m, c, to = item
        t0 = time.monotonic()
        try:
            p = subprocess.run(c, shell=True, input=payload_raw, capture_output=True, text=True,
                               env=env, cwd=cwd, timeout=to)
            rc, out, err = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            rc, out, err = "TIMEOUT", "", "timeout"
        dt = time.monotonic() - t0
        verdict, j = interpret(a.event, rc if isinstance(rc, int) else -1, out)
        if rc == "TIMEOUT":
            verdict = "HOOK-TIMEOUT"
        name = re.findall(r"/([^/\" ]+)\"?\s*$", c)
        return {"hook": name[0] if name else c, "matcher": m, "rc": rc, "verdict": verdict,
                "ms": round(dt * 1000), "stdout": out[-4000:], "stderr": err[-4000:]}
    if os.environ.get("RV_PARALLEL") == "1":
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(1, len(hooks))) as ex:
            results = list(ex.map(run_one, hooks))
    else:
        results = [run_one(h) for h in hooks]
    total = time.monotonic() - t_all
    after = None if a.no_snap else snapshot()
    d = diff(before, after) if before is not None else None
    rec = {"label": a.label, "event": a.event, "tool": payload.get("tool_name"),
           "agent_type": payload.get("agent_type"), "total_ms": round(total * 1000),
           "hooks": results, "fs": d}
    if a.log:
        with open(a.log, "a") as f:
            f.write(json.dumps(rec) + "\n")
    blocked = [r for r in results if r["verdict"].startswith(("BLOCK", "STOP", "ASK"))]
    errs = [r for r in results if r["verdict"].startswith("HOOK-")]
    print(f"[{a.label}] {a.event} tool={payload.get('tool_name')} agent={payload.get('agent_type')} "
          f"hooks={len(results)} total={rec['total_ms']}ms blocked={[(r['hook'], r['verdict']) for r in blocked]} "
          f"errors={[(r['hook'], r['rc']) for r in errs]}")
    for r in blocked + errs:
        msg = (r["stderr"] or r["stdout"]).strip().replace("\n", " | ")
        print(f"    -> {r['hook']} {r['verdict']}: {msg[:700]}")
    if d:
        n = sum(len(v) for v in d.values())
        print(f"    fs: +{len(d['added'])} ~{len(d['changed'])} -{len(d['removed'])}")


if __name__ == "__main__":
    main()
