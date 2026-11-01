"""The artifact check's CI shards (E2): the plan, E1's mode for the whole job, and the merge's checks.

One 4-CPU runner needs about 3,000 s for every traced replay and E1's differential: twice E2's
1,500 s. E2's remedy is to shard by pipeline with a matrix. plan() splits the drivers present at
run time (runtime.drivers()) into shards balanced by the cost each driver declares, and decides E1's
mode once for the whole job:

- Cost. A driver module may declare COST: the CPU seconds one of its variants costs the check (its
  two traced replays, shipped and armed, their sandbox copies and their differential runs as E1's
  fallback selects them), one number for every variant or a dict by variant name. A variant with no
  declaration costs as much as the costliest declared one, so a new driver lands in a shard with no
  change here; the plan names it under `undeclared`.
- E1's mode. The full differential runs a superset of the fallback's runs, so when the whole job's
  declared cost (with the fallback) does not fit E2's budget on one runner, neither does the full
  differential: the fallback then applies to every replay, whatever the shard count, and is known
  before any replay runs ("fallback"). Otherwise ("measure") the job fits one runner, runs as one
  shard, and E1's measured rule decides after its replays (check.run_check), as an unsharded job
  always has. The mode is a function of the drivers and the budget alone, never of the shard count.
- Shards. Every driver (pipeline) stays whole in one shard: E2 allows at most one traced job per
  pipeline. Drivers are placed costliest first, each on the least loaded shard. The count is the
  fewest shards whose expected critical path (the plan job, the slowest shard, the merge job) fits
  HEADROOM of the budget; when none does, the count with the shortest critical path, and the plan
  says when that is over the budget itself.

Expected seconds are CI seconds on ubuntu-latest: a shard's replays and differential are list-
scheduled, costliest first, on SLOTS slots, each doing CPU_PER_CI_S / SLOTS CPU seconds per second,
plus the fixed seconds below. The merge job (check.run_check with replays=False and
differential=False) derives the check over every shard's replays; merge_errors() checks that the
shards' records agree with the plan.
"""
from __future__ import annotations

import glob
import importlib
import json
import os
from dataclasses import asdict, dataclass, field

# Measured on CI: b8e34f4's single job on ubuntu-latest (4 CPUs, 4 replays at a time) ran the 54
# replays its drivers declare at 9,945 CPU seconds, with their differential, in 4,166 s (replays
# 3,682 s, then differential and derivation 485 s; 4,197.5 s of pytest). With this rate the model
# below gives that job 4,262 s. (33d0435's run had suggested 3.30, which gives it 3,131 s.)
CPU_PER_CI_S = 2.40
SLOTS = 4
# Fixed CI seconds. Job set-up: baseline.yml's step times on PR #8's runs (runner, checkout, Python,
# Node, strace and the locked dependencies: 15-20 s). A shard adds the sandbox template (28 s on
# b8e34f4's run), the static half's CPU alongside the replays (26 CPU-s) and its upload. The merge
# job downloads, then derives over every replay (static half, loading the runs, derivation: 80 CPU-s
# over 50 replays, one thread) and runs the determinism test's two static runs side by side (31 s).
SETUP_S = 20.0
TEMPLATE_S = 28.0
SHARD_FIXED_S = SETUP_S + TEMPLATE_S + 26.0 / CPU_PER_CI_S + 20.0
MERGE_S = SETUP_S + 20.0 + 80.0 + 31.0
PLAN_S = 15.0
# The expected critical path must fit this share of the budget: the two measured runs of the single
# job scale to 2,990 and 3,230 CI seconds, 8% apart, so an estimate within 10% of the budget is not a fit.
HEADROOM = 0.9
# The single job (one runner, no plan or merge job): set-up, template, the derivation after the
# replays (the static half runs alongside them) and the determinism test.
SINGLE_FIXED_S = SETUP_S + TEMPLATE_S + 54.0 + 31.0
RECORDS = "shards"


@dataclass
class Plan:
    count: int
    mode: str                                   # "fallback" | "measure"
    budget_s: float
    shards: list = field(default_factory=list)  # drivers per shard, shard 1 first
    driver_cost: dict = field(default_factory=dict)
    variant_cost: dict = field(default_factory=dict)  # "driver~variant" (or "driver") -> CPU seconds
    undeclared: list = field(default_factory=list)
    expected: dict = field(default_factory=dict)

    def cost(self, driver: str, variant: str) -> float:
        return self.variant_cost.get(label(driver, variant), 0.0)

    def shard_of(self, driver: str) -> int:
        for i, ds in enumerate(self.shards, 1):
            if driver in ds:
                return i
        return 0

    def to_json(self) -> dict:
        out = asdict(self)
        out["matrix"] = list(range(1, self.count + 1))
        return out


def label(driver: str, variant: str) -> str:
    return driver + (f"~{variant}" if variant else "")


def declared(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], float | None]:
    """The COST each driver module declares for each of its variants (None where it declares none)."""
    out = {}
    for d, v in pairs:
        mod = importlib.import_module(f"tests.replay.drivers.{d}")
        c = getattr(mod, "COST", None)
        if isinstance(c, dict):
            c = c.get(v)
        out[(d, v)] = float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) and c > 0 else None
    return out


def makespan(tasks: list[float], slots: int = SLOTS) -> float:
    """CI seconds `tasks` (CPU seconds each) take list-scheduled costliest first on `slots` slots."""
    rate = CPU_PER_CI_S / slots
    free = [0.0] * slots
    for t in sorted(tasks, reverse=True):
        i = free.index(min(free))
        free[i] += t / rate
    return max(free) if tasks else 0.0


def _tasks(variant_cost: dict, drivers) -> list[float]:
    # each variant is two replays (shipped, armed), each with its share of the differential
    ds = set(drivers)
    return [c / 2 for k, c in sorted(variant_cost.items()) if k.split("~", 1)[0] in ds for _ in (0, 1)]


def _assign(driver_cost: dict, count: int) -> list[list[str]]:
    shards: list[list[str]] = [[] for _ in range(count)]
    load = [0.0] * count
    for d in sorted(driver_cost, key=lambda d: (-driver_cost[d], d)):
        i = load.index(min(load))
        shards[i].append(d)
        load[i] += driver_cost[d]
    return [sorted(s) for s in shards]


def plan(pairs: list[tuple[str, str]], *, budget_s: float = 1500.0, count: int | None = None,
         costs: dict | None = None) -> Plan:
    """The shards of the check over `pairs` ((driver, variant) of runtime.drivers()) and E1's mode.
    `costs` maps (driver, variant) to declared CPU seconds or None (default: each module's COST);
    `count` fixes the shard count (default: the rule in the module docstring)."""
    dec = costs if costs is not None else declared(pairs)
    known = [c for c in dec.values() if c]
    default = max(known) if known else 1.0
    vc = {label(d, v): (dec.get((d, v)) or default) for d, v in pairs}
    undeclared = sorted(label(d, v) for d, v in pairs if not dec.get((d, v)))
    dc: dict[str, float] = {}
    for d, v in pairs:
        dc[d] = dc.get(d, 0.0) + vc[label(d, v)]
    drivers = sorted(dc)
    single = SINGLE_FIXED_S + makespan(_tasks(vc, drivers))
    mode = "fallback" if single > budget_s else "measure"

    def critical(n: int) -> tuple[float, list, list]:
        shards = _assign(dc, n)
        per = [SHARD_FIXED_S + makespan(_tasks(vc, s)) for s in shards]
        return PLAN_S + max(per) + MERGE_S, shards, per

    if count is None:
        if mode == "measure" or len(drivers) <= 1:
            count = 1
        else:
            options = [(critical(n)[0], n) for n in range(2, len(drivers) + 1)]
            fits = [n for c, n in options if c <= HEADROOM * budget_s]
            count = fits[0] if fits else min(options)[1]
    count = max(1, min(count, max(1, len(drivers))))
    crit, shards, per = critical(count)
    expected = {"single_runner_s": round(single), "shards_s": [round(s) for s in per],
                "critical_path_s": round(crit), "over_budget": crit > budget_s,
                "cpu_s": round(sum(vc.values())), "shard_cpu_s": [round(sum(dc[d] for d in s)) for s in shards]}
    return Plan(count, mode, budget_s, shards, {d: round(c, 1) for d, c in sorted(dc.items())},
                {k: round(c, 1) for k, c in sorted(vc.items())}, undeclared, expected)


def parse_shard(text: str) -> tuple[int, int]:
    """`I/N` (shard I of N, from 1)."""
    try:
        i, n = (int(x) for x in text.split("/", 1))
    except ValueError:
        raise ValueError(f"--shard takes I/N (shard I of N, from 1), not {text!r}") from None
    if not 1 <= i <= n:
        raise ValueError(f"--shard {text}: I must be between 1 and N")
    return i, n


def shard_errors(p: Plan, shard: tuple[int, int]) -> list[str]:
    i, n = shard
    errs = []
    if n != p.count:
        errs.append(f"shard {i}/{n}: the plan has {p.count} shards")
    if p.mode != "fallback" and n > 1:
        errs.append(f"shard {i}/{n}: the job fits one runner by its declared cost ({p.expected['single_runner_s']} s "
                    f"of {p.budget_s:g}), so E1's mode is measured after every replay, in one job; it is not sharded")
    return errs


def record_path(work: str, index: int) -> str:
    return os.path.join(work, RECORDS, f"shard-{index}.json")


def write_record(work: str, p: Plan, shard: tuple[int, int], timing: dict, errors: list[str],
                 drivers: list[str] | None = None) -> str:
    """shards/shard-I.json: what shard I of N replayed (`drivers`, default the plan's share), in which
    E1 mode, its timing and its refusals. An unsharded job records itself as shard 1 of 1."""
    path = record_path(work, shard[0])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if drivers is None:
        drivers = p.shards[shard[0] - 1] if shard[0] <= len(p.shards) else []
    rec = {"index": shard[0], "count": shard[1], "mode": p.mode, "budget_s": p.budget_s,
           "drivers": sorted(drivers), "timing": timing, "errors": errors}
    with open(path, "w") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
    return path


def records(work: str) -> list[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(work, RECORDS, "shard-*.json"))):
        try:
            with open(path) as fh:
                out.append(json.load(fh))
        except (OSError, ValueError) as e:
            out.append({"error": f"{path}: {e}"})
    return out


def recorded_count(work: str) -> int | None:
    """The shard count the shards under `work` ran with (None when no shard left a record)."""
    counts = {r.get("count") for r in records(work) if isinstance(r.get("count"), int)}
    return counts.pop() if len(counts) == 1 else None


def merge_errors(work: str, p: Plan) -> list[str]:
    """What the shards' records under `work` say against the plan `p` the merge computed: one record
    per shard, each with the plan's count, its drivers and E1's mode."""
    recs = records(work)
    if not recs:
        return []
    errs = [r["error"] for r in recs if "error" in r]
    recs = [r for r in recs if "error" not in r]
    if p.mode != "fallback" and p.count > 1:
        errs.append(f"the job fits one runner by its declared cost, but {p.count} shards ran it: E1's measured mode "
                    "needs every replay in one job")
    seen = sorted(r.get("index") for r in recs)
    if seen != list(range(1, p.count + 1)):
        errs.append(f"the shards' records are {seen}; the plan has shards 1 to {p.count}")
    for r in recs:
        i = r.get("index")
        if r.get("count") != p.count:
            errs.append(f"shard {i} ran as one of {r.get('count')} shards; the plan has {p.count}")
        if r.get("mode") != p.mode:
            errs.append(f"shard {i} ran E1's {r.get('mode')} mode; the whole job's is {p.mode}")
        want = p.shards[i - 1] if isinstance(i, int) and 1 <= i <= len(p.shards) else None
        if r.get("drivers") != want:
            errs.append(f"shard {i} replayed {r.get('drivers')}; the plan gives it {want}")
        errs += [f"shard {i}: {e}" for e in r.get("errors") or []]
    return errs
