"""Command line: build a sandbox and run a named driver in a chosen mode and settings.

    python -m tests.replay build --tree T --sandbox SB
    python -m tests.replay run --tree T --out DIR --driver smoke [--arg K=V ...] [--sandbox SB]
        [--mode ns|scratch] [--guard] [--settings shipped|armed|FILE] [--env K=V ...] [--runs plain,traced,traced]
        [--parallel-hooks] [--rebuild] [--keep-raw]
    python -m tests.replay text FILE HEADING [--index N | --anchor A] [--lang L] [--dispatch] [--set K=V ...]

`run` writes, per run, DIR/run<N>-<kind>/ (hooks.jsonl, invocations.jsonl, blocks.json,
summary.json, transcripts/, and for traced runs relations.tsv, relation-steps.tsv,
relation-events.tsv, outside-writes.txt, trace-stats.json), plus DIR/summary.tsv (one row per run),
DIR/summary.json and, with two or more traced runs, DIR/determinism.txt. --arg
values reach the driver as rp.args (for example a variant); --env
values may name {home}, {harness}, {project}, {state} or {sb}, filled with the
paths as the replay sees them. The sandbox and DIR must lie outside the
repository and outside the tree under test.
"""
from __future__ import annotations

import argparse
import difflib
import gzip
import hashlib
import json
import os
import resource
import shutil
import sys
import time

from . import cmdtext, sandbox, trace

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COLUMNS = ["pipeline", "settings", "mode", "kind", "hook_events", "hook_runs", "blocks", "deviations",
           "hook_errors", "failed_calls", "wall_s", "outer_s", "cpu_s", "raw_trace_bytes", "relations",
           "outside_writes"]


def _outside_repo(path: str, *trees: str) -> str:
    path = os.path.abspath(path)
    for t in (REPO,) + trees:
        t = os.path.realpath(t)
        if os.path.realpath(path) == t or os.path.realpath(path).startswith(t + "/"):
            raise SystemExit(f"{path} lies inside {t}; outputs and sandboxes stay outside the repository")
    return path


def _env_pairs(pairs) -> dict:
    out = {}
    for kv in pairs or []:
        k, sep, v = kv.partition("=")
        if not sep:
            raise SystemExit(f"--env wants K=V, got {kv!r}")
        out[k] = v
    return out


def run_one(sb: str, tree: str, out_dir: str, *, driver: str, mode: str, settings: str, env: dict,
            kind: str, guard: bool, parallel: bool, keep_raw: bool, driver_args: dict | None = None) -> dict:
    """Reset the sandbox, run one replay, collect its outputs into out_dir."""
    traced = kind == "traced"
    sandbox.reset(sb, mode)
    lay = sandbox.layout_for(sb, mode)
    label, spath = sandbox.settings_file(sb, mode, settings)
    host_home = os.path.realpath(os.environ.get("HOME", "/"))
    cfg = {"layout": lay.to_json(), "driver": driver, "settings_path": spath, "settings_label": label,
           "env": env, "traced": traced, "parallel_hooks": parallel, "driver_args": driver_args or {}}
    if mode == "scratch" and not traced:
        cfg["scan_outside"] = [d for d in ["/tmp", "/var/tmp", "/dev/shm", host_home] if os.path.isdir(d)]
        cfg["scan_skip"] = [os.path.abspath(out_dir)]
    with open(os.path.join(sb, "run-config.json"), "w") as fh:
        json.dump(cfg, fh, indent=1)
    argv = [lay.python, "-m", "replay.inner", lay.sb + "/run-config.json"]
    if traced:
        argv = trace.strace_argv(lay.trace + "/raw.txt") + argv
    env_inner = {"PATH": f"{lay.harness}/venv/bin:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": lay.home,
                 "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": lay.sb}
    t0, ru0 = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    rc = sandbox.launch(sb, lay, argv, env_inner, guard=guard)
    outer, ru1 = time.monotonic() - t0, resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)  # the whole tree, strace included
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(os.path.join(sb, "out"), out_dir)
    tdir = os.path.join(sb, "home", ".claude", "projects")
    if os.path.isdir(tdir):
        shutil.copytree(tdir, os.path.join(out_dir, "transcripts"))
    try:
        with open(os.path.join(out_dir, "summary.json")) as fh:
            row = json.load(fh)
    except OSError:
        return {"pipeline": driver, "settings": settings, "mode": mode, "kind": kind, "rc": rc,
                "driver_error": f"the replay exited {rc} before writing its summary (see its stderr above)"}
    row.update(mode=mode + ("+guard" if guard and mode == "scratch" else ""), kind=kind, rc=rc,
               outer_s=round(outer, 2), cpu_s=round(cpu, 1), tree=tree, raw_trace_bytes="", relations="", outside_writes="")
    if traced:
        raw = os.path.join(sb, "trace", "raw.txt")
        stats = trace.parse(raw, out_dir)
        row.update(raw_trace_bytes=stats["raw_bytes"], relations=stats["relations"],
                   outside_writes=stats["outside_writes"])
        if keep_raw:
            with open(raw, "rb") as src, gzip.open(os.path.join(out_dir, "raw.txt.gz"), "wb") as dst:
                shutil.copyfileobj(src, dst)
        os.unlink(raw)  # reduced into out_dir; tens of MB per replay, and reset() would remove it anyway
    elif os.path.exists(os.path.join(out_dir, "outside-writes.txt")):
        with open(os.path.join(out_dir, "outside-writes.txt")) as fh:
            row["outside_writes"] = sum(1 for _ in fh)
    with open(os.path.join(out_dir, "summary.json"), "w") as fh:
        json.dump(row, fh, indent=1)
    return row


def determinism(out: str, dirs: list[str]) -> str:
    files = [os.path.join(d, "relations.tsv") for d in dirs]
    blobs = [open(f, "rb").read() for f in files]
    if all(b == blobs[0] for b in blobs):
        lines = blobs[0].count(b"\n")
        verdict = (f"identical: {len(dirs)} traced runs, {lines} relations, "
                   f"sha256 {hashlib.sha256(blobs[0]).hexdigest()}")
    else:
        diff = difflib.unified_diff(blobs[0].decode().splitlines(), blobs[1].decode().splitlines(),
                                    files[0], files[1], lineterm="", n=0)
        verdict = "DIFFERENT\n" + "\n".join(list(diff)[:80])
    with open(os.path.join(out, "determinism.txt"), "w") as fh:
        fh.write(verdict + "\n")
    return verdict


def cmd_run(a) -> int:
    tree = os.path.abspath(a.tree)
    out = _outside_repo(a.out, tree)
    sb = _outside_repo(a.sandbox or os.path.join(out, "sb"), tree)
    if a.rebuild or not os.path.isfile(os.path.join(sb, sandbox.MARK)) or "snapshot" not in sandbox.info(sb):
        print(f"building sandbox {sb} from {tree}")
        print(json.dumps(sandbox.build(tree, sb)))
    elif sandbox.info(sb).get("tree") != tree:
        raise SystemExit(f"sandbox {sb} was built from {sandbox.info(sb).get('tree')}; pass --rebuild")
    if "traced" in a.runs:
        ok, ver = trace.available()
        if not ok:
            raise SystemExit(f"tracing needs strace: {ver}")
        print(ver)
    env = _env_pairs(a.env)
    rows, traced_dirs = [], []
    for n, kind in enumerate(a.runs.split(","), 1):
        if kind not in ("plain", "traced"):
            raise SystemExit(f"run kind must be plain or traced, not {kind!r}")
        d = os.path.join(out, f"run{n}-{kind}")
        row = run_one(sb, tree, d, driver=a.driver, mode=a.mode, settings=a.settings, env=env, kind=kind,
                      guard=a.guard, parallel=a.parallel_hooks, keep_raw=a.keep_raw,
                      driver_args=_env_pairs(a.arg))
        rows.append(row)
        if kind == "traced":
            traced_dirs.append(d)
        print("\t".join(str(row.get(c, "")) for c in COLUMNS))
        with open(os.path.join(d, "blocks.json")) as fh:
            bl = json.load(fh)
        for b in bl["blocks"]:
            print(f"  BLOCK {b['hook']} at {b['step']!r} ({b['event']}, {b['how']}"
                  f"{', deviation' if b['passed_by_deviation'] else ''}): {b['text'][:300]}")
        for e in bl["hook_errors"]:
            print(f"  HOOK ERROR {e['hook']} at {e['step']!r} ({e['how']}): {e['stderr'][-300:]}")
        if row.get("driver_error"):
            print("  DRIVER ERROR:\n" + row["driver_error"])
    with open(os.path.join(out, "summary.tsv"), "w") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        fh.writelines("\t".join(str(r.get(c, "")) for c in COLUMNS) + "\n" for r in rows)
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(rows, fh, indent=1)
    if len(traced_dirs) >= 2:
        print("determinism: " + determinism(out, traced_dirs))
    return 1 if any(r.get("driver_error") or r.get("rc") for r in rows) else 0


def cmd_build(a) -> int:
    tree = os.path.abspath(a.tree)
    print(json.dumps(sandbox.build(tree, _outside_repo(a.sandbox, tree)), indent=1))
    return 0


def cmd_text(a) -> int:
    if a.dispatch:
        fields = cmdtext.dispatch(a.file, a.heading, index=a.index, anchor=a.anchor)
        if a.set:
            fields = {k: cmdtext.fill(v, _env_pairs(a.set)) for k, v in fields.items()}
        print(json.dumps(fields, indent=1))
        text = fields.get("prompt", "")
    else:
        text = cmdtext.block(a.file, a.heading, index=a.index, anchor=a.anchor, lang=a.lang)
        text = cmdtext.fill(text, _env_pairs(a.set))
        sys.stdout.write(text)
    left = cmdtext.placeholders(text)
    if left:
        print(f"# unfilled placeholders: {left}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.replay", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build a sandbox from a harness tree")
    b.add_argument("--tree", required=True)
    b.add_argument("--sandbox", required=True)
    r = sub.add_parser("run", help="run a driver in a sandbox")
    r.add_argument("--tree", required=True, help="harness tree under test (working tree or a clone)")
    r.add_argument("--out", required=True, help="output directory, outside the repository")
    r.add_argument("--sandbox", help="sandbox root (default OUT/sb); built if missing")
    r.add_argument("--driver", default="smoke")
    r.add_argument("--arg", action="append", default=[], metavar="K=V", help="driver argument (rp.args)")
    r.add_argument("--mode", choices=["ns", "scratch"], default="ns")
    r.add_argument("--guard", action="store_true", help="mode scratch only: mask host HOME and temp dirs")
    r.add_argument("--settings", default="shipped", help="shipped, armed, or a settings file path")
    r.add_argument("--env", action="append", default=[], metavar="K=V")
    r.add_argument("--runs", default="plain", help="comma list of plain|traced")
    r.add_argument("--parallel-hooks", action="store_true", help="run one event's hooks in parallel, as the CLI")
    r.add_argument("--rebuild", action="store_true")
    r.add_argument("--keep-raw", action="store_true", help="keep each raw trace, gzipped")
    t = sub.add_parser("text", help="print a block or dispatch template of a command or agent file")
    t.add_argument("file")
    t.add_argument("heading")
    t.add_argument("--index", type=int)
    t.add_argument("--anchor")
    t.add_argument("--lang")
    t.add_argument("--dispatch", action="store_true")
    t.add_argument("--set", action="append", default=[], metavar="PLACEHOLDER=VALUE")
    a = ap.parse_args(argv)
    return {"build": cmd_build, "run": cmd_run, "text": cmd_text}[a.cmd](a)
