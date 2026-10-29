"""E1's differential: does a reader decide on an artifact it read?

A reader decides on an artifact when re-running its recorded invocation with
the artifact removed, or made schema-invalid (for an artifact with no schema,
its bytes replaced at the same size by content its reader cannot parse),
changes its exit code or its decision output (P1b E1, row 19 rules (3), (4)).

After a traced replay, the sandbox keeps its final state. candidates() reads
the run's relation-events.tsv (who read which pattern under which hook event)
and invocations.jsonl (each hook event's payload and registered commands) and
returns one unit per (origin, event) that read an artifact: a file some
component of the run wrote. A unit is re-run as the replay ran it:

* kind "hook": the registered hook the reading process belongs to, with the
  event's payload on stdin, the env every hook got (env.json) and the project
  as cwd;
* kind "bash": the Bash tool call whose command ran the reading script, with
  the env every Bash call got (bash-env.json).

execute() runs, inside the sandbox's namespace, each unit once intact and once
per (artifact, mutation), every run on a fresh overlay of the same final state
(a mount and pid namespace of its own over HOME, the state dir and the temp
dirs), so no run sees another's writes and nothing a run writes survives it.
A run's decision is (exit code, verdict, how) as hookrun.interpret reads a
hook's output; for a Bash call, its exit code. Results go to
<run>/differential.json, sorted by event and artifact.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

from . import hookrun, sandbox

MUTATIONS = ("removed", "invalid")
_HARNESS_DIRS = ("hooks/", "scripts/")
OVERLAY = r'''
set -e
mkdir -p /mnt/ovl
mount -t tmpfs none /mnt/ovl
i=0
for r in "$@"; do
  [ "$r" = "--" ] && break
  i=$((i+1))
  if [ -d "$r" ]; then
    mkdir -p "/mnt/ovl/$i/u" "/mnt/ovl/$i/w"
    mount -t overlay overlay -o "lowerdir=$r,upperdir=/mnt/ovl/$i/u,workdir=/mnt/ovl/$i/w" "$r"
  fi
done
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
shift
cd "$PWD"
exec "$@"
'''


def norm_comp(path: str) -> str:
    return os.path.normpath(path) if path else path


def _harness_file(comp: str) -> bool:
    return bool(comp) and norm_comp(comp).startswith(_HARNESS_DIRS)


def git_store(pattern: str) -> bool:
    """A path inside a git directory (`.git/`, a bare `*.git/`): git's own store, read and written
    only through git (the platform), never an artifact of its own."""
    return any(seg == ".git" or (seg.endswith(".git") and len(seg) > 4) for seg in pattern.split("/")[:-1])


def load_events(run_dir: str) -> list[dict]:
    out = []
    path = os.path.join(run_dir, "relation-events.tsv")
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", errors="surrogateescape") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 8:
                continue
            comp, origin, actor, op, pattern, event, bulk, raw = parts
            out.append({"comp": norm_comp(comp), "origin": norm_comp(origin), "actor": actor, "op": op,
                        "pattern": pattern, "event": int(event) if event.isdigit() else 0, "bulk": bulk == "bulk",
                        "raw": raw})
    return out


def load_invocations(run_dir: str) -> dict[int, dict]:
    out = {}
    path = os.path.join(run_dir, "invocations.jsonl")
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                rec = json.loads(line)
                out[rec["seq"]] = rec
    return out


def written_patterns(events: list[dict]) -> set:
    """Patterns some component of the run writes: the artifacts a mutation may touch (rule (1):
    a file present at replay start that nothing writes is an input)."""
    out = set()
    for e in events:
        if e["op"] in ("write", "create"):
            out.add(e["pattern"])
        elif e["op"] == "rename" and " -> " in e["pattern"]:
            out.add(e["pattern"].split(" -> ", 1)[1])
    return out


def _match_value(inv: dict) -> str:
    p = inv["payload"]
    return str(p.get("tool_name") or p.get("agent_type") or p.get("source") or p.get("reason") or "")


def candidates(run_dir: str) -> list[dict]:
    """Units to re-run: per (reader, pattern, event, match value) the first and the last event
    that read it, grouped by (origin, event)."""
    events = load_events(run_dir)
    invs = load_invocations(run_dir)
    written = written_patterns(events)
    picks: dict[tuple, list] = {}
    for e in events:
        if e["op"] != "read" or e["bulk"] or e["pattern"] not in written or not _harness_file(e["comp"]) \
                or git_store(e["pattern"]):
            continue
        inv = invs.get(e["event"])
        if inv is None:
            continue
        key = (e["origin"] or e["comp"], e["comp"], e["pattern"], inv["event"], _match_value(inv))
        picks.setdefault(key, []).append(e)
    units: dict[tuple, dict] = {}
    for key in sorted(picks):
        evs = sorted(picks[key], key=lambda e: (e["event"], e["raw"]))
        for e in {id(x): x for x in (evs[0], evs[-1])}.values():
            origin = e["origin"] or e["comp"]
            inv = invs[e["event"]]
            hooks = [h for h in inv["hooks"] if norm_comp(hookrun.hook_name(h["command"])) == origin]
            p = inv["payload"]
            if hooks:
                unit = {"kind": "hook", "command": hooks[0]["command"], "timeout": hooks[0]["timeout"],
                        "original": [hooks[0]["rc"], hooks[0]["verdict"], hooks[0]["how"]]}
            elif inv["event"] == "PreToolUse" and p.get("tool_name") == "Bash":
                ti = p.get("tool_input") or {}
                unit = {"kind": "bash", "command": ti.get("command", ""),
                        "timeout": int((ti.get("timeout") or 120000) / 1000), "original": None}
            else:
                continue
            u = units.setdefault((e["event"], origin), dict(
                unit, seq=e["event"], origin=origin, event=inv["event"], label=inv["label"],
                tool=p.get("tool_name"), agent_type=p.get("agent_type"), agent_id=p.get("agent_id"), reads=[]))
            r = {"comp": e["comp"], "pattern": e["pattern"], "raw": e["raw"]}
            if r not in u["reads"]:
                u["reads"].append(r)
    out = []
    for k in sorted(units):
        u = units[k]
        u["reads"].sort(key=lambda r: (r["pattern"], r["raw"], r["comp"]))
        out.append(u)
    return out


def run_count(units: list[dict]) -> int:
    return sum(1 + len(MUTATIONS) * len({r["raw"] for r in u["reads"]}) for u in units)


# ---------------------------------------------------------------- outer side

def execute(sb: str, run_dir: str, units: list[dict], schemas: dict | None = None, workers: int = 1,
            mode: str = "ns") -> dict:
    """Run `units` in the sandbox `sb` (left in its final state by the replay of `run_dir`);
    writes and returns <run_dir>/differential.json."""
    if mode != "ns":
        raise RuntimeError("the differential runs need the mount namespace (mode ns)")
    sb = os.path.abspath(sb)
    lay = sandbox.layout_for(sb, mode)
    work = os.path.join(sb, "differential")
    if os.path.exists(work):
        sandbox._rm(sb, work)
    os.makedirs(work)
    shutil.rmtree(os.path.join(sb, "replay"), ignore_errors=True)  # the framework as it is now
    shutil.copytree(sandbox.HERE, os.path.join(sb, "replay"), ignore=sandbox.COPY_IGNORE)
    for name in ("env.json", "bash-env.json", "invocations.jsonl"):
        shutil.copyfile(os.path.join(run_dir, name), os.path.join(work, name))
    with open(os.path.join(work, "units.json"), "w") as fh:
        json.dump({"units": units, "schemas": schemas or {}, "workers": workers,
                   "layout": lay.to_json()}, fh)
    env_inner = {"PATH": f"{lay.harness}/venv/bin:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": lay.home,
                 "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": lay.sb}
    t0 = time.monotonic()
    rc = sandbox.launch(sb, lay, [lay.python, "-m", "replay.differential", lay.sb + "/differential/units.json"],
                        env_inner)
    wall = time.monotonic() - t0
    try:
        with open(os.path.join(work, "results.json")) as fh:
            res = json.load(fh)
    except OSError:
        res = {"units": [], "error": f"the differential exited {rc} before writing its results"}
    res.update(wall_s=round(wall, 2), rc=rc)
    with open(os.path.join(run_dir, "differential.json"), "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    return res


# ---------------------------------------------------------------- inner side (in the sandbox)

def _invalid_content(path: str, schema_path: str | None) -> bytes | None:
    """Schema-invalid JSON when the artifact has a schema; else its size in bytes no parser reads."""
    if schema_path and os.path.isfile(schema_path):
        try:
            import jsonschema  # the harness venv carries it (requirements.txt)
            with open(schema_path) as fh:
                schema = json.load(fh)
            for cand in ({}, [], None, 0, ""):
                try:
                    jsonschema.validate(cand, schema)
                except jsonschema.ValidationError:
                    return json.dumps(cand).encode() + b"\n"
                except Exception:
                    break
        except Exception:
            pass
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    return b"#" * size if size else None


def _decision(kind: str, rc, stdout: str) -> list:
    if kind == "bash":
        return [rc, "ok" if rc == 0 else "fail", ""]
    verdict, how = hookrun.interpret(rc, stdout)
    return [rc, verdict, how]


def _roots(lay: dict) -> list[str]:
    return [lay["home"], lay["state"]] + [d for d in lay["temp_dirs"] if os.path.isdir(d)]


def _one(cfg: dict, n: int, unit: dict, mutation: dict | None, payload: str, env: dict) -> dict:
    lay = cfg["layout"]
    roots = _roots(lay)
    spec = os.path.join(cfg["work"], f"run-{n:06d}.json")
    with open(spec, "w") as fh:
        json.dump({"mutation": mutation, "roots": roots}, fh)
    argv = (["unshare", "--mount", "--propagation", "private", "--pid", "--fork", "--mount-proc",
             "bash", "-c", OVERLAY, "overlay", *roots, "--",
             sys.executable, "-m", "replay.differential", "--apply", spec, "--",
             "env", "-i", *[f"{k}={v}" for k, v in sorted(env.items())], "bash", "-c", unit["command"]])
    t0 = time.monotonic()
    try:
        p = subprocess.run(argv, input=payload, capture_output=True, text=True, cwd=lay["project"],
                           timeout=max(5, int(unit.get("timeout") or hookrun.DEFAULT_TIMEOUT_S)) + 5,
                           errors="replace")
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = "timeout", "", "timeout"
    os.unlink(spec)
    return {"decision": _decision(unit["kind"], rc, out), "ms": round((time.monotonic() - t0) * 1000),
            "stderr": (err or "")[-300:]}


def _apply(spec_path: str, argv: list[str]) -> int:
    """In the run's own namespace, over the overlays: apply the mutation, then become the hook."""
    with open(spec_path) as fh:
        spec = json.load(fh)
    m = spec["mutation"]
    if m:
        path = os.path.realpath(m["path"])
        if not any(path.startswith(r.rstrip("/") + "/") for r in spec["roots"]):
            sys.stderr.write(f"differential: {path} lies outside the sandbox roots\n")
            return 97
        if os.path.isfile(path):
            if m["how"] == "removed":
                os.unlink(path)
            else:
                with open(m["content_file"], "rb") as src, open(path, "wb") as dst:
                    dst.write(src.read())
    os.execvp(argv[0], argv)
    return 127


def _inner(units_path: str) -> int:
    with open(units_path) as fh:
        cfg = json.load(fh)
    work = os.path.dirname(units_path)
    cfg["work"] = work
    lay = cfg["layout"]
    with open(os.path.join(work, "env.json")) as fh:
        hook_env = json.load(fh)
    with open(os.path.join(work, "bash-env.json")) as fh:
        bash_env = json.load(fh)
    invs = {}
    with open(os.path.join(work, "invocations.jsonl")) as fh:
        for line in fh:
            rec = json.loads(line)
            invs[rec["seq"]] = rec
    schemas = cfg.get("schemas") or {}
    jobs = []
    contents: dict[str, str] = {}
    for ui, u in enumerate(cfg["units"]):
        payload = json.dumps(invs[u["seq"]]["payload"]) if u["kind"] == "hook" else ""
        env = hook_env if u["kind"] == "hook" else bash_env
        jobs.append((ui, None, None, payload, env))
        for raw in sorted({r["raw"] for r in u["reads"]}):
            pattern = next(r["pattern"] for r in u["reads"] if r["raw"] == raw)
            for how in MUTATIONS:
                m = {"how": how, "path": raw, "pattern": pattern}
                if how == "invalid":
                    key = raw
                    if key not in contents:
                        schema = schemas.get(pattern)
                        data = _invalid_content(raw, os.path.join(lay["harness"], schema) if schema else None)
                        if data is None:
                            contents[key] = ""
                        else:
                            f = os.path.join(work, f"content-{len(contents):05d}")
                            with open(f, "wb") as fh:
                                fh.write(data)
                            contents[key] = f
                    if not contents[key]:
                        continue
                    m["content_file"] = contents[key]
                    m["schema"] = schemas.get(pattern) or ""
                jobs.append((ui, m, pattern, payload, env))
    results: dict[int, dict] = {}
    t0 = time.monotonic()

    def run(n_job):
        n, job = n_job
        ui, m, pattern, payload, env = job
        return job, _one(cfg, n, cfg["units"][ui], m, payload, env)

    workers = max(1, int(cfg.get("workers") or 1))
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            done = list(ex.map(run, enumerate(jobs)))
    else:
        done = [run(j) for j in enumerate(jobs)]
    for (ui, m, pattern, _p, _e), r in done:
        u = cfg["units"][ui]
        rec = results.setdefault(ui, {k: u.get(k) for k in ("seq", "origin", "kind", "event", "label", "tool",
                                                          "agent_type", "agent_id", "original")})
        rec.setdefault("runs", [])
        if m is None:
            rec["intact"] = r["decision"]
            rec["intact_ms"] = r["ms"]
            if r["decision"][0] not in (0, 2) and u["kind"] == "hook":
                rec["intact_stderr"] = r["stderr"]
        else:
            rec["runs"].append({"pattern": pattern, "raw": m["path"], "how": m["how"], "schema": m.get("schema", ""),
                                "decision": r["decision"], "ms": r["ms"],
                                "readers": sorted({x["comp"] for x in u["reads"] if x["raw"] == m["path"]})})
    out = []
    for ui in sorted(results):
        rec = results[ui]
        intact = rec.get("intact")
        rec["reproduced"] = rec.get("original") is None or intact == rec.get("original")
        for r in rec["runs"]:
            r["changed"] = r["decision"] != intact
        rec["runs"].sort(key=lambda r: (r["pattern"], r["raw"], r["how"]))
        out.append(rec)
    res = {"units": out, "runs": len(jobs), "inner_wall_s": round(time.monotonic() - t0, 2)}
    with open(os.path.join(work, "results.json"), "w") as fh:
        json.dump(res, fh)
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--apply":
        sep = argv.index("--")
        return _apply(argv[1], argv[sep + 1:])
    return _inner(argv[0])


if __name__ == "__main__":
    sys.exit(main())
