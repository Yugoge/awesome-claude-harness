"""The artifact check's CI shards (tests/artifact_graph/shards.py) and their merge (check.run_check).

The plan is computed from the drivers present at run time: every driver lands
in exactly one shard with all its variants, a driver that declares no cost
still lands in one, E1's mode is the same for every shard count, and the count
is the fewest shards whose expected critical path fits the budget (reported,
never hidden, when none does). The merge derives over every shard's replays
exactly what one job derives over the same replays, wherever each shard ran,
and fails on a shard that is missing or ran another plan. None of this needs
strace or a namespace: the merged replays here are written by the test.
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.artifact_graph import check as C
from tests.artifact_graph import runtime as RT
from tests.artifact_graph import shards as SH

REPO = Path(__file__).resolve().parents[2]
# today's measured costs (CPU seconds per variant), plus one driver that declares none
COSTS = {("close", v): c for v, c in (("plain", 448), ("route", 485), ("append", 530), ("auto", 462))}
COSTS |= {("commit", v): c for v, c in (("auto", 482), ("commit-route", 694), ("full", 796))}
COSTS |= {("dev", v): c for v, c in (("plain", 301), ("qa-fail", 366), ("question", 300), ("ba-qa-fail", 322),
                                      ("fanout", 430), ("fanout-qa-fail", 508))}
COSTS |= {("overnight", "plain"): 813, ("overnight", "stop"): 345, ("redev", ""): 503, ("smoke", ""): 51,
          ("do", ""): 289, ("dev_command", "plain"): 187, ("dev_command", "qa-fail"): 236}
COSTS |= {("spec", v): c for v, c in (("plain", 206), ("omission", 202), ("bad-split", 213),
                                       ("split-qa-fail", 263), ("update", 232))}


def pairs_of(costs: dict) -> list[tuple[str, str]]:
    return sorted(costs)


def test_the_plan_places_every_driver_present_in_exactly_one_shard():
    pairs = RT.drivers()
    p = SH.plan(pairs)
    placed = [d for s in p.shards for d in s]
    assert sorted(placed) == sorted({d for d, _v in pairs}), "a driver is missing from the shards or placed twice"
    assert all(p.shards), "an empty shard"
    assert set(p.variant_cost) == {SH.label(d, v) for d, v in pairs}
    assert p.to_json()["matrix"] == list(range(1, p.count + 1))


def test_a_driver_that_declares_no_cost_lands_in_a_shard_by_itself():
    costs = dict(COSTS)
    costs[("newpipe", "a")] = None
    costs[("newpipe", "b")] = None
    p = SH.plan(pairs_of(costs), costs=costs)
    assert sum(s.count("newpipe") for s in p.shards) == 1
    assert p.undeclared == ["newpipe~a", "newpipe~b"]
    # it costs as much as the costliest declared variant, so it never looks cheaper than it may be
    assert p.variant_cost["newpipe~a"] == max(c for c in costs.values() if c)


def test_every_variant_of_a_pipeline_stays_in_its_shard():
    p = SH.plan(pairs_of(COSTS), costs=COSTS, count=3)
    for d in {d for d, _v in COSTS}:
        assert sum(d in s for s in p.shards) == 1
    assert {SH.label(d, v) for d, v in COSTS} == set(p.variant_cost)


def test_e1_mode_does_not_depend_on_the_shard_count():
    pairs = pairs_of(COSTS)
    drivers = len({d for d, _v in pairs})
    for budget, mode in ((1500.0, "fallback"), (100000.0, "measure")):
        modes = {SH.plan(pairs, costs=COSTS, budget_s=budget, count=n).mode for n in range(1, drivers + 1)}
        assert modes == {mode}, (budget, modes)


def test_a_job_that_fits_one_runner_is_not_sharded():
    p = SH.plan(pairs_of(COSTS), costs=COSTS, budget_s=100000.0)
    assert (p.mode, p.count) == ("measure", 1)
    assert SH.shard_errors(p, (1, 1)) == []
    forced = SH.plan(pairs_of(COSTS), costs=COSTS, budget_s=100000.0, count=2)
    assert any("not sharded" in e for e in SH.shard_errors(forced, (1, 2)))


def test_the_shard_count_is_the_fewest_whose_critical_path_fits_with_headroom():
    pairs = pairs_of(COSTS)
    p = SH.plan(pairs, costs=COSTS)
    assert p.mode == "fallback" and p.count > 1
    assert p.expected["critical_path_s"] <= SH.HEADROOM * p.budget_s and not p.expected["over_budget"]
    for n in range(2, p.count):
        fewer = SH.plan(pairs, costs=COSTS, count=n)
        assert fewer.expected["critical_path_s"] > SH.HEADROOM * p.budget_s, n


def test_over_budget_is_reported_with_the_budget_unchanged():
    costs = dict(COSTS)
    costs[("huge", "")] = 40000.0          # one pipeline alone overruns any shard
    p = SH.plan(pairs_of(costs), costs=costs)
    assert p.budget_s == 1500.0
    assert p.expected["over_budget"] and p.expected["critical_path_s"] > 1500.0
    best = min(SH.plan(pairs_of(costs), costs=costs, count=n).expected["critical_path_s"]
               for n in range(2, len({d for d, _v in costs}) + 1))
    assert p.expected["critical_path_s"] == best


def test_the_shards_are_balanced_within_lpt_bound_of_the_best_split():
    # small enough to try every split: the costliest shard is within 4/3 of the best one (LPT's bound)
    costs = {(d, ""): c for d, c in (("a", 900), ("b", 700), ("c", 650), ("d", 400), ("e", 380), ("f", 120),
                                      ("g", 60))}
    p = SH.plan(pairs_of(costs), costs=costs, count=3)
    worst = max(sum(costs[(d, "")] for d in s) for s in p.shards)
    best = min(max(sum(costs[(d, "")] for d, k in zip("abcdefg", ks) if k == i) for i in range(3))
               for ks in itertools.product(range(3), repeat=7))
    assert worst <= best * 4 / 3


def test_the_plan_is_byte_identical_under_two_hash_seeds():
    outs = []
    for seed in ("1", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-m", "tests.artifact_graph.check", "--tree", str(REPO), "--plan"],
                           cwd=REPO, env=env, capture_output=True, text=True)
        assert p.returncode == 0, p.stderr[-2000:]
        outs.append(p.stdout)
    assert outs[0] == outs[1] and json.loads(outs[0])["shards"]


def test_parse_shard():
    assert SH.parse_shard("2/3") == (2, 3)
    for bad in ("0/3", "4/3", "x", "1-3"):
        with pytest.raises(ValueError):
            SH.parse_shard(bad)


# ---------------------------------------------------------------- the merge

TREE_FILES = {
    "settings.json": json.dumps({"env": {}, "hooks": {}}),
    "hooks/lib/harness_state_dir.py": "import os\n\ndef harness_state_dir():\n    return os.environ.get('X', '/tmp')\n",
    "agents/ba.md": "---\nname: ba\n---\n# BA\n",
    "hooks/w.py": "import json\n",
    "hooks/r.py": "import json\n",
}
ONLY = ["smoke", "do"]


def tiny_tree(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    for rel, text in TREE_FILES.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return root


def write_run(out: Path, driver: str, settings: str, sb: Path, full_s: float = 500.0) -> None:
    """A replay as a shard leaves it: job.json (its runner's paths, E1's full differential estimated at
    `full_s` seconds) and run1-traced/."""
    rd = out / "run1-traced"
    rd.mkdir(parents=True)
    w, r = "hooks/w.py\thooks/w.py\t\twrite", "hooks/r.py\thooks/r.py\t\tread"
    ev = [f"{w}\t<state>/{driver}-<sid>.json\t1\t\t/mnt/sb/state/{driver}-1.json",
          f"{r}\t<state>/{driver}-<sid>.json\t2\t\t/mnt/sb/state/{driver}-1.json",
          f"{r}\t<state>/shared-<sid>.json\t2\t\t/mnt/sb/state/shared-1.json"]
    if driver == "do":
        ev.append(f"{w}\t<state>/shared-<sid>.json\t1\t\t/mnt/sb/state/shared-1.json")
    (rd / "relation-events.tsv").write_text("\n".join(ev) + "\n", encoding="utf-8")
    (rd / "relations.tsv").write_text("", encoding="utf-8")
    (rd / "env.json").write_text(json.dumps({"CLAUDE_STATE_DIR": "/mnt/sb/state"}), encoding="utf-8")
    job = RT.Job(driver, "", settings, str(out), str(sb), rc=0, wall_s=10.0, log=str(out / "replay.log"),
                 extra={"e1_full_runs": 40, "e1_full_estimate_s": full_s, "e1_selected_runs": 0,
                        "e1_mode": "fallback"})
    RT.save_job(job)


def shard_outputs(base: Path, p: SH.Plan) -> list[Path]:
    """Each shard's work directory, as its runner leaves it (its own absolute paths in job.json)."""
    dirs = []
    for i, ds in enumerate(p.shards, 1):
        w = base / f"runner-{i}" / "work"
        for d in ds:
            for s in RT.SETTINGS:
                write_run(w / "runs" / d / s, d, s, w / "sb" / d / s)
        SH.write_record(str(w), p, (i, p.count), {"replays_wall_s": 10.0}, [])
        dirs.append(w)
    return dirs


def merge(dirs: list[Path], into: Path) -> Path:
    for w in dirs:
        shutil.copytree(w, into, dirs_exist_ok=True)
    return into


def outputs(work: Path) -> tuple[bytes, bytes]:
    return (work / "map.txt").read_bytes(), (work / "violations.txt").read_bytes()


def test_the_merged_derivation_equals_one_jobs_on_the_same_replays(tmp_path):
    tree = tiny_tree(tmp_path)
    p = SH.plan([(d, "") for d in ONLY], budget_s=100.0, count=2)
    assert p.mode == "fallback" and all(p.shards)
    merged = merge(shard_outputs(tmp_path / "ci", p), tmp_path / "merged")
    one = tmp_path / "one"            # one job's directory: the same replays, no shard records
    for d in ONLY:
        for s in RT.SETTINGS:
            write_run(one / "runs" / d / s, d, s, one / "sb" / d / s)
    a = C.run_check(str(tree), str(merged), budget_s=100.0, replays=False, differential=False, only=ONLY, log=str)
    b = C.run_check(str(tree), str(one), budget_s=100.0, replays=False, differential=False, only=ONLY, log=str)
    assert a["errors"] == [] and b["errors"] == []
    assert a["counts"]["runtime_artifacts"] > 0
    assert outputs(merged) == outputs(one)
    assert [j["rc"] for j in a["measures"]["jobs"]] == [0] * 4
    # every job is read from the merge's own directory, not the runner's
    assert all(j["out"].startswith(str(merged)) for j in a["measures"]["jobs"])
    assert [r["index"] for r in a["measures"]["shards"]] == [1, 2]


def test_the_merge_fails_on_a_missing_shard(tmp_path):
    tree = tiny_tree(tmp_path)
    p = SH.plan([(d, "") for d in ONLY], budget_s=100.0, count=2)
    dirs = shard_outputs(tmp_path / "ci", p)
    merged = merge(dirs[:1], tmp_path / "merged")
    res = C.run_check(str(tree), str(merged), budget_s=100.0, replays=False, differential=False, only=ONLY, log=str)
    missing = sorted(d for d in ONLY if d not in p.shards[0])
    assert any("records are [1]" in e for e in res["errors"])
    assert {e.split()[3] for e in res["errors"] if e.startswith("no replay of")} == set(missing)


def test_the_merge_fails_on_a_shard_that_ran_another_plan(tmp_path):
    p = SH.plan([(d, "") for d in ONLY], budget_s=100.0, count=2)
    w = tmp_path / "w"
    SH.write_record(str(w), p, (1, 2), {}, [])
    other = SH.Plan(2, "measure", 100000.0, list(reversed(p.shards)))
    SH.write_record(str(w), other, (2, 2), {}, [])
    errs = SH.merge_errors(str(w), p)
    assert any("shard 2 ran E1's measure mode" in e for e in errs)
    assert any("shard 2 replayed" in e for e in errs)
    assert SH.merge_errors(str(tmp_path / "none"), p) == []


def test_the_plans_fallback_may_not_cut_a_differential_the_measurement_fits(tmp_path):
    """Declared costs that overstate the drivers would cut E1's differential to the fallback where the
    measured full differential fits the budget: the merge says so and fails."""
    tree = tiny_tree(tmp_path)
    one = tmp_path / "one"
    for d in ONLY:
        for s in RT.SETTINGS:
            write_run(one / "runs" / d / s, d, s, one / "sb" / d / s, full_s=1.0)
    res = C.run_check(str(tree), str(one), budget_s=100.0, replays=False, differential=False, only=ONLY, log=str)
    assert res["measures"]["timing"]["differential_mode_measured"] == "full"
    assert any("COST overstates" in e for e in res["errors"])


def test_a_sharded_job_that_fits_one_runner_replays_nothing(tmp_path):
    tree = tiny_tree(tmp_path)
    res = C.run_check(str(tree), str(tmp_path / "w"), budget_s=100000.0, only=ONLY, shard=(1, 2), log=str)
    assert any("not sharded" in e for e in res["errors"])
    assert res["measures"]["jobs"] == []
    assert not (tmp_path / "w" / "runs").exists()


def test_a_loaded_job_is_rebased_onto_the_directory_it_is_read_from(tmp_path):
    runner = tmp_path / "runner" / "runs" / "do" / "shipped"
    write_run(runner, "do", "shipped", tmp_path / "runner" / "sb" / "do" / "shipped")
    here = tmp_path / "merge" / "runs" / "do" / "shipped"
    shutil.copytree(runner, here)
    j = RT.load_job(str(here), str(tmp_path / "merge" / "sb" / "do" / "shipped"))
    assert (j.out, j.log, j.run_dir) == (str(here), str(here / "replay.log"), str(here / "run1-traced"))
    assert j.rc == 0 and j.extra["e1_mode"] == "fallback"
