"""The artifact check of P1b (Scope row 19): goals 1-4 over every artifact, derived at test time.

The check (tests/artifact_graph/check.py) replays every driver under
tests/replay/drivers/, each variant it offers, traced, with this tree's own
settings.json and with the sandbox-armed copy (tests/artifact_graph/runtime.py),
re-runs each reader's recorded invocation with the artifact removed and made
invalid (E1's differential), joins the static half's relations at literal code
sites (tests/artifact_graph/static_half.py), and asserts that no violation is
left: one producer per artifact, at least one consumer, one deciding rule,
deciding reads only at the allowed positions, no list that repeats a
declaration, one state root. It compares against no committed list and keeps no
exception.

Run alone (a local `pytest tests/test_artifact_graph.py`) it is the whole
check on one runner. It needs strace and a mount namespace (root, or
passwordless sudo); without either the replays cannot run and the tests below
fail with the reason, never skip. CI shards the replays by pipeline
(tests/artifact_graph/shards.py): each shard job replays its drivers with
`check.py --shard I/N`, and the job "artifact check (traced replays)" runs this
module over every shard's outputs with ARTIFACT_GRAPH_REUSE=1, the check's
`--reuse --no-differential` path, so every assertion below holds over every
replay. The baseline job's plain pytest step leaves this module to that job with
`--ignore=tests/test_artifact_graph.py`.

Environment: ARTIFACT_GRAPH_WORK (keep the replays, the map and the violations
in that directory instead of a temporary one), ARTIFACT_GRAPH_JOBS (parallel
replays, default the CPU count up to 4), ARTIFACT_GRAPH_BUDGET_S (E2's budget
for the job, default 1500 seconds), ARTIFACT_GRAPH_ONLY (a comma list of drivers
or driver~variant, for a local run of part of the check; CI leaves it unset,
since an artifact one pipeline writes and another reads needs every replay),
ARTIFACT_GRAPH_REUSE ("1": derive from the replays and differential results
already in ARTIFACT_GRAPH_WORK, the shards' merged outputs, instead of running
them; a planned replay missing there fails the check).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def check(tmp_path_factory):
    from tests.artifact_graph import runtime
    from tests.artifact_graph.check import run_check

    reuse = os.environ.get("ARTIFACT_GRAPH_REUSE") == "1"
    if reuse and not os.environ.get("ARTIFACT_GRAPH_WORK"):
        pytest.fail("ARTIFACT_GRAPH_REUSE=1 derives from the replays in ARTIFACT_GRAPH_WORK, which is unset",
                    pytrace=False)
    missing = [] if reuse else runtime.preconditions()
    if missing:
        pytest.fail("the artifact check's traced replays cannot run here: " + "; ".join(missing), pytrace=False)
    work = os.environ.get("ARTIFACT_GRAPH_WORK") or str(tmp_path_factory.mktemp("artifact-graph"))
    jobs = int(os.environ.get("ARTIFACT_GRAPH_JOBS") or max(1, min(4, os.cpu_count() or 1)))
    budget = float(os.environ.get("ARTIFACT_GRAPH_BUDGET_S") or 1500)
    only = [x for x in (os.environ.get("ARTIFACT_GRAPH_ONLY") or "").split(",") if x] or None
    return run_check(str(REPO), work, jobs=jobs, budget_s=budget, only=only, replays=not reuse,
                     differential=not reuse, log=lambda s: print(s, flush=True))


def test_every_driver_replays_traced_in_both_settings(check):
    jobs = check["measures"]["jobs"]
    assert jobs, "no driver under tests/replay/drivers/"
    assert not check["errors"], "\n".join(check["errors"])
    for j in jobs:
        assert j["rc"] == 0, f"replay {j['driver']} {j['variant']} ({j['settings']}) exited {j['rc']}; see {j['log']}"
    assert {j["settings"] for j in jobs} == {"shipped", "armed"}


def test_no_violation(check):
    vs = check["violations"]
    counts = check["counts"]
    assert not vs, (f"{len(vs)} violations {counts['violations_by_rule']} over {counts['artifacts']} artifacts:\n\n"
                    + "\n\n".join(v.text() for v in vs[:300]))


def _static_bytes(tmp_path: Path, *seeds: str) -> list[bytes]:
    """The static half's output under each hash seed, the runs side by side (separate processes)."""
    runs = []
    for seed in seeds:
        out = tmp_path / f"static-{seed}.jsonl"
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
        runs.append((out, subprocess.Popen([sys.executable, "-m", "tests.artifact_graph", str(REPO), str(out)],
                                           cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True)))
    for _out, p in runs:
        _stdout, stderr = p.communicate()
        assert p.returncode == 0, stderr[-2000:]
    return [out.read_bytes() for out, _p in runs]


def test_static_half_is_byte_identical_over_two_runs(tmp_path):
    """Rule (10): the static half's output is sorted, and two runs (different hash seeds) agree byte for byte."""
    a, b = _static_bytes(tmp_path, "1", "4242")
    assert a, "the static half wrote nothing"
    assert a == b, (f"two static runs differ: sha256 {hashlib.sha256(a).hexdigest()} vs "
                    f"{hashlib.sha256(b).hexdigest()}")
