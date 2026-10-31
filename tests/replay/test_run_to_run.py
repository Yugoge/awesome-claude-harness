"""Run to run: two replays of one driver variant on one tree give the artifact check the same input and result.

The artifact check (tests/test_artifact_graph.py) derives its relations from traced replays,
so a reduction that depends on timing makes its verdict differ from run to run. This
replays the variant whose declared cost (its driver's COST, tests/artifact_graph/shards.py) is
the lowest twice, at the same time, on one tree, each in its own copy of one sandbox template, as
the check's runtime half does (tests/artifact_graph/runtime.py), runs E1's differential on
each, and asserts:

- every process the trace saw ended in it (trace-stats.json's lost_exits is 0: a pid given out
  again is never taken for its earlier process);
- the normalised relation events are identical: every event of relation-events.tsv but its raw
  path, without the two kinds the derivation leaves out (a read rule (3) leaves out, marked by
  trace.py, and a path inside a git directory, git's own store), whose presence git's racy-index
  timing decides;
- the differential's decisions are identical;
- the check derives the same map (artifacts, producers, readers, deciding readers, with their
  evidence) and the same violations from each replay.

The first test traces a shell script whose processes end every way a hook's can (exit, a
SIGPIPE in a pipeline, a SIGTERM, an execve in a thread) and asserts the trace ends each one.

Known time dependence of the harness, not of the runner: hooks/pretool-worktree-guard.sh caches
its answer for 60 seconds of wall clock, so in a replay longer than that, the hook events at which
it reads or rewrites its cache depend on timing. The cheapest variant ends well inside the window.

It needs strace and a mount namespace (root, or passwordless sudo); without either it fails with
the reason, never skips (the convention of tests/test_artifact_graph.py). CI runs it in the job
"artifact check run to run" (baseline.yml), beside the check's shards; the baseline job's plain
pytest step leaves it out with --ignore.
"""
from __future__ import annotations

import difflib
import json
import os
import subprocess
import threading

import pytest

from tests.artifact_graph import check as C
from tests.artifact_graph import runtime as RT
from tests.artifact_graph import shards as SH
from tests.replay import differential as D
from tests.replay import trace

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _require():
    missing = RT.preconditions()
    if missing:
        pytest.fail("run-to-run replays cannot run here: " + "; ".join(missing), pytrace=False)


def _diff(a: list[str], b: list[str], what: str, limit: int = 40) -> str:
    d = list(difflib.unified_diff(a, b, "run A", "run B", lineterm="", n=0))
    return f"{what} differ between two runs:\n" + "\n".join(d[:limit]) + (f"\n... {len(d) - limit} more"
                                                                             if len(d) > limit else "")


def test_the_trace_ends_every_process(tmp_path):
    _require()
    raw = tmp_path / "raw.txt"
    script = ("yes fill | head -3 >/dev/null; sleep 30 & kill -TERM $!; wait\n"
              "python3 -c 'import os, threading\n"
              "t = threading.Thread(target=lambda: os.execv(\"/bin/true\", [\"true\"])); t.start(); t.join()'\n")
    p = subprocess.run(trace.strace_argv(str(raw)) + ["bash", "-c", script], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-2000:]
    seen, ended = set(), set()
    for pid, name, *_rest in trace._records(str(raw)):
        (ended if name == trace.EXIT else seen).add(pid)
    assert seen and seen <= ended, f"processes with no end in the trace: {sorted(seen - ended)}"


def _decisions(run_dir: str) -> list[str]:
    try:
        with open(os.path.join(run_dir, "differential.json")) as fh:
            res = json.load(fh)
    except OSError:     # no reader of an artifact to re-run
        return []
    out = []
    for u in res.get("units", []):
        out.append(json.dumps({k: u.get(k) for k in ("seq", "origin", "kind", "event", "intact", "reproduced")},
                              sort_keys=True))
        out += ["  " + json.dumps({k: r.get(k) for k in ("pattern", "how", "decision", "changed", "readers")},
                                  sort_keys=True) for r in u.get("runs", [])]
    return out


def test_two_replays_reduce_and_derive_the_same(tmp_path):
    _require()
    pairs = RT.drivers()
    cost = SH.plan(pairs).variant_cost
    driver, variant = min(pairs, key=lambda p: (cost.get(SH.label(*p), float("inf")), p))
    work = str(tmp_path)
    box: dict = {}

    def static():   # the static half runs beside the replays, as in the check
        from tests.artifact_graph.static_half import derive
        try:
            box["static"] = derive(REPO)
        except Exception as e:  # noqa: BLE001 -- reported by the test thread below
            box["error"] = e
    th = threading.Thread(target=static)
    th.start()
    tpl = RT.template(REPO, work, log=lambda s: None)
    jobs = [RT.Job(driver, variant, "shipped", os.path.join(work, f"run-{n}"), os.path.join(work, f"sb-{n}"))
            for n in "ab"]
    RT.replay_all(REPO, jobs, workers=2, template=tpl)
    th.join()
    if "error" in box:
        raise box["error"]
    static = box["static"]
    for j in jobs:
        assert j.rc == 0 and not j.error, f"replay {j.label} exited {j.rc} {j.error}; see {j.log}"
    schemas = C.schemas_for(static.records)
    # E1's differential of each, in its full mode, both at the same time, as the check's workers run them
    th = [threading.Thread(target=C._differential, args=(j, "full", schemas)) for j in jobs]
    for t in th:
        t.start()
    for t in th:
        t.join()
    for j in jobs:
        assert not j.error, j.error
        with open(os.path.join(j.run_dir, "trace-stats.json")) as fh:
            lost = json.load(fh)["lost_exits"]
        assert lost == 0, f"{j.label}: {lost} processes the trace never ended (their pids' later processes " \
                          "may be taken for them)"

    a, b = (D.derived_events(j.run_dir) for j in jobs)
    assert a, f"replay {jobs[0].label} left no relation events"
    assert a == b, _diff(a, b, f"normalised relation events of {jobs[0].label}")
    a, b = (_decisions(j.run_dir) for j in jobs)
    assert a == b, _diff(a, b, f"differential decisions of {jobs[0].label}")
    texts = []
    for j in jobs:
        m = C.derive(REPO, static, [C.load_run(j.label, j.settings, j.run_dir)])
        vs = C.violations(m, static.records)
        texts.append((C.map_text(m, vs).splitlines(), [v.text() for v in vs]))
    (map_a, vs_a), (map_b, vs_b) = texts
    assert map_a == map_b, _diff(map_a, map_b, f"the check's map derived from {jobs[0].label}")
    assert vs_a == vs_b, _diff(vs_a, vs_b, f"the check's violations derived from {jobs[0].label}")
