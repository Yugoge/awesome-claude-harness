"""Entry point inside the sandbox: run one driver against one settings file.

cli.py starts it as `python -m replay.inner <config.json>` from the sandbox's
copy of this package (inside the namespace in mode ns, directly in mode
scratch, under strace when traced). It writes into the layout's out dir:
hooks.jsonl (every hook run), invocations.jsonl (each hook event's payload and
registered commands, for E1's differential, differential.py), blocks.json (blocks, deviations, hook errors,
failed calls, respellings), summary.json (the per-run row), env.json and
bash-env.json (the environment every hook and every Bash call got), ids.json and markers.jsonl (what trace.parse needs), start-manifest.txt when traced, and, for an
untraced run in mode scratch, outside-writes.txt from an mtime scan. With the driver argument resweep=1
it also keeps the score log (score-log.jsonl) and records the score observer's second sweep (scorelog.py); score=<role>:<rank>,...
seeds that log first (P13-3).
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import time
import traceback

from . import replay, sandbox, trace


def scan_outside(roots, skip, since: float) -> list[str]:
    """Files under `roots` modified since `since`, outside `skip` (untraced runs: approximate)."""
    found = []
    for root in roots:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if not any(os.path.join(dp, d) == s or os.path.join(dp, d).startswith(s + "/")
                                                for s in skip)]
            for fn in fns:
                p = os.path.join(dp, fn)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if max(st.st_mtime, st.st_ctime) >= since:
                    found.append(f"write?\t{p}\tmtime-scan")
    return sorted(set(found))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    with open(argv[0]) as fh:
        cfg = json.load(fh)
    lay = sandbox.Layout(**cfg["layout"])
    os.makedirs(lay.out, exist_ok=True)
    os.chdir(lay.project)  # the CLI runs in the project directory
    if cfg.get("traced"):
        trace.manifest(lay, lay.out)
    driver = importlib.import_module(f"{__package__}.drivers.{cfg['driver']}")
    rp = replay.Replay(lay, cfg["settings_path"], pipeline=getattr(driver, "PIPELINE", cfg["driver"]),
                       settings_label=cfg["settings_label"], env_extra=cfg.get("env") or {},
                       faults=getattr(driver, "FAULTS", ()), parallel_hooks=cfg.get("parallel_hooks", False))
    rp.args = dict(cfg.get("driver_args") or {})
    rp.launch_differential = bool(cfg.get("launch_differential"))  # P12-L7 (launchdiff.py)
    if rp.args.get("fault"):  # P1c: the injected faults of the suite (tests/replay/faults.py)
        from . import faults
        faults.install(rp, rp.args["fault"])
    if rp.args.get("land") or rp.args.get("blocks"):  # P1c A11: the live landing (tests/replay/landing.py)
        from . import landing
        landing.install(rp)
    if rp.args.get("score"):  # P13-3: the score log the replay starts with (scorelog.py)
        from . import scorelog
        scorelog.seed(rp, rp.args["score"])
    t0, err = time.time(), ""
    rp.mark("run", "begin")
    try:
        driver.run(rp)
    except Exception:
        err = traceback.format_exc()
    rp.mark("run", "end")
    if rp.args.get("resweep") and not err:  # P13-2 B2: the score observer once more on the final transcript
        from . import scorelog
        scorelog.resweep(rp)
    rp.finish(time.time() - t0, err)
    if cfg.get("scan_outside"):
        lines = scan_outside(cfg["scan_outside"], [lay.sb] + cfg.get("scan_skip", []), t0 - 1)
        with open(os.path.join(lay.out, "outside-writes.txt"), "w") as fh:
            fh.write("".join(l + "\n" for l in lines))
    if err:
        sys.stderr.write(err)
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
