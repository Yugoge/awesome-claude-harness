"""The runtime half of the artifact check: traced replays and E1's differential.

Every driver under tests/replay/drivers/ is replayed, each variant it offers,
traced, once with the tree's own settings.json ("shipped") and once with the
sandbox-armed copy ("armed"), each in a sandbox of its own (E2: the check's
replay runs with the tree's settings; rule (6) measures the gates armed too),
copied from one sandbox built for the tree (start(): the template, built while
the check's static half runs, then the replays, `workers` at a time).
A driver offers variants through a module-level VARIANTS list of argument
dicts, or, without one, through the ``variant=NAME`` lines of its docstring's
argument list; a driver with neither runs once with no arguments. Adding a
driver or a variant needs no change here.

After a replay, its sandbox keeps the final state, and E1's differential re-runs
the recorded invocations of every reader of an artifact in it
(tests/replay/differential.py). Its run count and wall time are measured
against E2's budget; over budget, E1's fallback applies (the differential runs
only for readers outside the allowed positions, and the static half's
branches decide for the rest): the caller passes the unit filter.
"""
from __future__ import annotations

import importlib
import json
import os
import pkgutil
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETTINGS = ("shipped", "armed")
_VARIANT_LINE = re.compile(r"^\s+variant=([A-Za-z0-9_.-]+)\s", re.M)


@dataclass
class Job:
    driver: str
    variant: str
    settings: str
    out: str
    sb: str
    rc: int | None = None
    wall_s: float = 0.0
    log: str = ""
    diff_wall_s: float = 0.0
    diff_runs: int = 0
    diff_units: int = 0
    error: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def run_dir(self) -> str:
        return os.path.join(self.out, "run1-traced")

    @property
    def label(self) -> str:
        return self.driver + (f"~{self.variant}" if self.variant else "")

    def to_json(self) -> dict:
        return asdict(self)


def drivers() -> list[tuple[str, str]]:
    """(driver, variant) pairs of every driver module under tests/replay/drivers/."""
    pkg = importlib.import_module("tests.replay.drivers")
    out = []
    for m in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        if m.ispkg or m.name.startswith("_"):
            continue
        mod = importlib.import_module(f"tests.replay.drivers.{m.name}")
        if not callable(getattr(mod, "run", None)):
            continue
        variants = getattr(mod, "VARIANTS", None)
        if variants:
            names = [str(v.get("variant", "")) if isinstance(v, dict) else str(v) for v in variants]
        else:
            names = list(dict.fromkeys(_VARIANT_LINE.findall(mod.__doc__ or "")))
        for v in names or [""]:
            out.append((m.name, v))
    return out


def jobs_for(work: str, pairs: list[tuple[str, str]], settings=SETTINGS) -> list[Job]:
    out = []
    for d, v in pairs:
        label = d + (f"~{v}" if v else "")
        for s in settings:
            out.append(Job(d, v, s, os.path.join(work, "runs", label, s), os.path.join(work, "sb", label, s)))
    return out


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def template(tree: str, work: str, log=print) -> str:
    """The sandbox every replay starts from: built once from `tree`, then copied per replay."""
    from tests.replay import sandbox
    sb = os.path.join(work, "template")
    log(f"sandbox template: {json.dumps(sandbox.build(tree, sb, log=log))}")
    return sb


def replay(tree: str, job: Job, template: str | None = None) -> Job:
    """One traced replay of `job`, in a copy of `template` (else a sandbox rebuilt from `tree`)."""
    os.makedirs(job.out, exist_ok=True)
    argv = [sys.executable, "-m", "tests.replay", "run", "--tree", tree, "--out", job.out, "--sandbox", job.sb,
            "--driver", job.driver, "--settings", job.settings, "--runs", "traced"]
    t0 = time.monotonic()
    job.log = os.path.join(job.out, "replay.log")
    if template:
        from tests.replay import sandbox
        try:
            sandbox.clone(template, job.sb)
        except (OSError, RuntimeError) as e:
            job.rc, job.wall_s = 1, round(time.monotonic() - t0, 2)
            job.error = f"replay {job.label} ({job.settings}) has no sandbox: {e}; see {job.log}"
            with open(job.log, "w") as fh:
                fh.write(job.error + "\n")
            return job
    else:
        argv.append("--rebuild")
    if job.variant:
        argv += ["--arg", f"variant={job.variant}"]
    p = subprocess.run(argv, cwd=REPO, env=_env(), capture_output=True, text=True)
    job.wall_s = round(time.monotonic() - t0, 2)
    job.rc = p.returncode
    with open(job.log, "w") as fh:
        fh.write(p.stdout + p.stderr)
    if not os.path.isfile(os.path.join(job.run_dir, "relations.tsv")):
        job.error = f"replay {job.label} ({job.settings}) left no trace; see {job.log}"
    return job


def replay_all(tree: str, jobs: list[Job], workers: int, template: str | None = None) -> list[Job]:
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(lambda j: replay(tree, j, template), jobs))


def start(tree: str, work: str, jobs: list[Job], workers: int, log=print):
    """Build the template, then replay every job `workers` at a time, in a thread of its own; the
    future's result is the timing: template_s, and replays_wall_s from the start to the last replay's end."""
    def run() -> dict:
        t0 = time.monotonic()
        tpl = None
        try:
            tpl = template(tree, work, log) if jobs else None
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            log(f"sandbox template: {e}; every replay builds its own sandbox")
        built = round(time.monotonic() - t0, 1)
        replay_all(tree, jobs, workers, tpl)
        return {"template_s": built, "replays_wall_s": round(time.monotonic() - t0, 1)}
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(run)
    ex.shutdown(wait=False)
    return fut


def differential(job: Job, units: list[dict], schemas: dict, workers: int) -> Job:
    from tests.replay import differential as D
    t0 = time.monotonic()
    res = D.execute(job.sb, job.run_dir, units, schemas, workers=workers)
    job.diff_wall_s = round(time.monotonic() - t0, 2)
    job.diff_runs = res.get("runs", 0)
    job.diff_units = len(res.get("units", []))
    if res.get("error"):
        job.error = (job.error + "; " if job.error else "") + res["error"]
    return job


def load_job(out: str) -> Job | None:
    try:
        with open(os.path.join(out, "job.json")) as fh:
            return Job(**json.load(fh))
    except (OSError, ValueError, TypeError):
        return None


def save_job(job: Job) -> None:
    with open(os.path.join(job.out, "job.json"), "w") as fh:
        json.dump(job.to_json(), fh, indent=1, sort_keys=True)


def preconditions() -> list[str]:
    """What the traced replays need and this host lacks (strace, the mount namespace)."""
    from tests.replay import trace
    missing = []
    ok, ver = trace.available()
    if not ok:
        missing.append(f"strace: {ver} (CI installs it: sudo apt-get install -y strace)")
    pre = [] if os.geteuid() == 0 else ["sudo", "-n"]
    p = subprocess.run(pre + ["unshare", "--mount", "--propagation", "private", "true"], capture_output=True, text=True)
    if p.returncode:
        missing.append("a mount namespace: `" + " ".join(pre + ["unshare", "--mount", "true"]) + "` failed: "
                       + (p.stderr.strip() or f"exit {p.returncode}"))
    return missing
