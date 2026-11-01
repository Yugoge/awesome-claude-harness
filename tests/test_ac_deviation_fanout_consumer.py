"""Regression tests for harness backlog #92 residuals under strict pass: fan-out
lanes that stop short of ``completed`` and the lifecycle row of a chain.

A lane's dev-report is a shard only when its ``dev.status`` is ``completed``.
A lane that stops short of it, whatever deviation record it carries, makes the
aggregator exit 1 writing no canonical, and the resolver fails the chain with
the lane's own codes.  A deviation-free fan-out aggregates and resolves as
before, and the lifecycle row of a dev chain is the chain's one call, carried
verbatim: close_pending only on ``pass``.

Self-contained: every fixture is built under pytest's ``tmp_path`` with inline
builders.  The scripts are loaded from the directory named by the environment
variable ``AC_FANOUT_SCRIPTS_DIR`` (default: the repository ``scripts/``
directory), so the same file can be aimed at a copy of the scripts.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = os.path.abspath(
    os.environ.get("AC_FANOUT_SCRIPTS_DIR") or str(REPO_ROOT / "scripts")
)

TASK = "20260920-880093"
FLAG = "ac_deviation_with_user_need_satisfied"
BLOCK = FLAG + "_block"
NA = "not_applicable"
CANON = "docs/dev/dev-report-%s.json" % TASK
LANE_A = "docs/dev/dev-report-%s-lane-a.json" % TASK
SINGULAR_DEV = "docs/dev/dev-report-%s.json" % TASK
LANES = ["lane-a", "lane-b"]
DEV_CODES = ["INVALID_DEV_STATUS", "UNRESOLVED_BLOCKERS"]
ELEVEN_KEYS = [
    "request_id",
    "task_id",
    "baseline_head_sha",
    "baseline_dirty_snapshot",
    "dev_report_path",
    "parallel_workers",
    "dev",
    "blocking_issues",
    "recommendations",
    "owned_edits",
    "pre_edit_snapshots",
]

_MODULES: dict = {}


def _load(name):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(
            "ac_fanout_" + re.sub(r"[^A-Za-z0-9]", "_", name), os.path.join(SCRIPTS_DIR, name)
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULES[name] = module
    return _MODULES[name]


def resolver():
    return _load("resolve-dev-artifact-chain.py")


def aggregator():
    return _load("aggregate-dev-report.py")


def lifecycle():
    return _load("dev-lifecycle.py")


def bare_aggregator():
    """The aggregator source executed into a bare namespace (no __file__), the
    way a fixture builds a canonical without running the aggregator."""
    namespace: dict = {}
    source = Path(SCRIPTS_DIR, "aggregate-dev-report.py").read_bytes()
    exec(compile(source, "aggregate", "exec"), namespace)
    return namespace


# --------------------------------------------------------------------------
# fixture builders
# --------------------------------------------------------------------------


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")


def _new_root(base):
    root = base / ("chain%03d" % sum(1 for _ in base.iterdir()))
    root.mkdir()
    verdict = root / "hooks" / "lib"
    verdict.mkdir(parents=True)
    shutil.copy(str(REPO_ROOT / "hooks" / "lib" / "close-verdict.py"), str(verdict / "close-verdict.py"))
    return root


def qa_report(ident, status="pass"):
    return {"request_id": ident, "task_id": ident, "qa": {"status": status}}


def with_deviation(ids=("AC19",), blockers=("AC19: literal check exits 1",)):
    def apply(report):
        report["dev"]["status"] = "blocked"
        report["blocking_issues"] = list(blockers)
        report[FLAG] = True
        report[BLOCK] = {
            "clause_a_deviated_ac_ids": list(ids),
            "clause_b_user_need_verbatim": {"text": "need-A", "source": "spec s5"},
            "clause_c_evidence": {"deviation_is_real": "m", "user_need_satisfied": "m"},
        }

    return apply


def without_flag(report):
    with_deviation()(report)
    report.pop(FLAG)


def with_string_flag(report):
    with_deviation()(report)
    report[FLAG] = "true"


def with_unattributed_blocker(report):
    with_deviation(blockers=("AC19: x", "unrelated thing"))(report)


def with_rationale(report):
    report["dev"]["status"] = "needs_review"
    report["dev"]["status_rationale"] = {
        "classification": "pending_commit_handoff",
        "blocked_by": "irrelevant",
        "forbidden_action": "irrelevant",
    }
    report["blocking_issues"] = ["awaiting commit"]


def completed_with_garbage(report):
    report[FLAG] = True
    report[BLOCK] = "garbage"


def lane_report(index, worker):
    ident = "%s-%s" % (TASK, worker)
    return {
        "request_id": ident,
        "task_id": ident,
        "baseline_head_sha": "0123456789abcdef",
        "baseline_dirty_snapshot": "",
        "dev": {
            "status": "completed",
            "tasks_completed": ["t"],
            "scripts_created": [],
            "permissions_to_add": [],
            "files_modified": ["scripts/lane-%d.py" % index],
            "files_created": [],
            "observed_preexisting": [],
        },
        "blocking_issues": [],
        "recommendations": [],
    }


def build_fanout(base, lane_a=None, lane_b=None, qa=None, baseline_canonical=False):
    """Two-lane fan-out chain: every lane artifact, the completion note listing
    every reference, and (only when asked) a canonical built without running
    the aggregator."""
    root = _new_root(base)
    dev_dir = root / "docs" / "dev"
    (root / "scripts").mkdir()
    qa = qa or {}
    loaded = []
    refs = [CANON]
    for index, worker in enumerate(LANES):
        ident = "%s-%s" % (TASK, worker)
        (root / "scripts" / ("lane-%d.py" % index)).write_text("")
        report = lane_report(index, worker)
        mutate = (lane_a, lane_b)[index]
        if mutate is not None:
            mutate(report)
        _write(dev_dir / ("ticket-%s.md" % ident), "# T\n\n**TASK-ID**: `%s`\n" % ident)
        _write(dev_dir / ("context-%s.json" % ident), {"request_id": ident, "task_id": ident})
        _write(dev_dir / ("dev-report-%s.json" % ident), report)
        _write(dev_dir / ("qa-report-%s.json" % ident), qa_report(ident, qa.get(worker, "pass")))
        loaded.append((worker, report))
        refs += [
            "docs/dev/%s-%s.%s" % (kind, ident, "md" if kind == "ticket" else "json")
            for kind in ("ticket", "context", "dev-report", "qa-report")
        ]
    _write(
        dev_dir / ("completion-%s.md" % TASK),
        "# C\n\n**Request ID**: `%s`\n" % TASK + "".join("- `%s`\n" % ref for ref in refs),
    )
    if baseline_canonical:
        _write(root / CANON, bare_aggregator()["_build_aggregate"](loaded, TASK))
    return root


def build_singular(base, mutate=None, qa_status="pass"):
    root = _new_root(base)
    (root / "scripts").mkdir()
    (root / "scripts" / "one.py").write_text("")
    dev_dir = root / "docs" / "dev"
    report = {
        "request_id": TASK,
        "task_id": TASK,
        "dev": {"status": "completed", "files_modified": ["scripts/one.py"], "files_created": []},
        "blocking_issues": [],
    }
    if mutate is not None:
        mutate(report)
    _write(dev_dir / ("ticket-%s.md" % TASK), "# T\n\n**TASK-ID**: `%s`\n" % TASK)
    _write(dev_dir / ("context-%s.json" % TASK), {"request_id": TASK, "task_id": TASK})
    _write(dev_dir / ("dev-report-%s.json" % TASK), report)
    _write(dev_dir / ("qa-report-%s.json" % TASK), qa_report(TASK, qa_status))
    refs = ["docs/dev/%s-%s.%s" % (kind, TASK, "md" if kind == "ticket" else "json")
            for kind in ("ticket", "context", "dev-report", "qa-report")]
    _write(
        dev_dir / ("completion-%s.md" % TASK),
        "# C\n\n**Request ID**: `%s`\n" % TASK + "".join("- `%s`\n" % ref for ref in refs),
    )
    return root


# --------------------------------------------------------------------------
# execution and reading helpers
# --------------------------------------------------------------------------


def run_aggregator(root, *extra):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    done = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "aggregate-dev-report.py"), "--task-id", TASK] + list(extra),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(root),
        timeout=120,
    )
    try:
        payload = json.loads(done.stdout)
    except ValueError:
        payload = {}
    return done.returncode, payload, done.stderr


def cli(root):
    done = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "resolve-dev-artifact-chain.py"),
         "--task-id", TASK, "--project-dir", str(root)],
        capture_output=True,
        text=True,
        cwd=str(root),
        timeout=120,
    )
    return done.returncode, json.loads(done.stdout)


def resolve(root):
    return resolver().resolve_chain(str(root), TASK)


def read_canonical(root):
    return json.loads((root / CANON).read_text(encoding="utf-8"))


def edit_canonical(root, change):
    document = read_canonical(root)
    change(document)
    (root / CANON).write_text(json.dumps(document), encoding="utf-8")


def errs(result):
    return sorted((e["code"], e["path"]) for e in result["errors"])


def codes(result):
    return sorted(e["code"] for e in result["errors"])


def gap(result):
    return (
        result["stage_gaps"],
        result["non_gap_errors"],
        result["late_repair_eligible"],
        result["gap_classification"],
    )


# ==========================================================================
# singular chains
# ==========================================================================


def test_an_ordinary_singular_chain_passes(tmp_path):
    root = build_singular(tmp_path)
    result = resolve(root)
    assert result["status"] == "pass"
    assert result["errors"] == []
    assert gap(result) == ([], [], False, "complete")
    assert cli(root) == (0, result)


@pytest.mark.parametrize("mutate", [with_deviation(), without_flag], ids=["recorded", "unrecorded"])
def test_a_blocked_singular_report_fails_with_todays_two_codes(tmp_path, mutate):
    root = build_singular(tmp_path, mutate)
    result = resolve(root)
    assert result["status"] == "fail"
    assert errs(result) == [(code, SINGULAR_DEV) for code in DEV_CODES]
    assert cli(root) == (2, result)


# ==========================================================================
# fan-out: a deviation-free chain is unchanged
# ==========================================================================


def test_a_deviation_free_fanout_aggregates_and_resolves_as_pass(tmp_path):
    root = build_fanout(tmp_path)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "aggregated"
    canonical = read_canonical(root)
    assert canonical["dev"]["status"] == "completed"
    assert [key for key in canonical if "ac_deviation" in key] == []
    result = resolve(root)
    assert result["status"] == "pass"
    assert result["mode"] == "fanout"
    assert gap(result) == (NA, NA, NA, NA)


def test_a_second_aggregation_validates_and_leaves_the_bytes_unchanged(tmp_path):
    root = build_fanout(tmp_path)
    assert run_aggregator(root)[0] == 0
    before = (root / CANON).read_bytes()
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "validated"
    assert (root / CANON).read_bytes() == before


def test_a_canonical_built_without_the_aggregator_stays_fresh(tmp_path):
    root = build_fanout(tmp_path, baseline_canonical=True)
    before = (root / CANON).read_bytes()
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "validated"
    assert (root / CANON).read_bytes() == before
    result = resolve(root)
    assert result["status"] == "pass"
    assert "STALE_CANONICAL" not in codes(result)


def test_the_projection_is_the_eleven_keys(tmp_path):
    root = build_fanout(tmp_path)
    assert run_aggregator(root)[0] == 0
    projection = aggregator()._canonical_projection(read_canonical(root))
    assert list(projection) == ELEVEN_KEYS
    assert projection["dev"]["status"] == "completed"


@pytest.mark.parametrize(
    "where", ["lane", "canonical"], ids=["completed-lane-garbage-record", "completed-canonical-record"]
)
def test_a_record_beside_completed_reports_changes_nothing(tmp_path, where):
    root = build_fanout(tmp_path, lane_a=completed_with_garbage if where == "lane" else None)
    assert run_aggregator(root)[0] == 0
    if where == "canonical":
        edit_canonical(root, lambda document: document.update({FLAG: True, BLOCK: {"x": 1}}))
    result = resolve(root)
    assert result["status"] == "pass"
    assert result["errors"] == []


# ==========================================================================
# fan-out: a lane short of completed is never a shard
# ==========================================================================

SHORT_LANES = [
    ("recorded", with_deviation()),
    ("unrecorded", without_flag),
    ("flag-a-string", with_string_flag),
    ("unattributed-blocker", with_unattributed_blocker),
    ("status-rationale", with_rationale),
]


@pytest.mark.parametrize("name,lane_a", SHORT_LANES, ids=[s[0] for s in SHORT_LANES])
def test_a_lane_short_of_completed_writes_no_canonical_and_fails_the_chain(tmp_path, name, lane_a):
    root = build_fanout(tmp_path, lane_a=lane_a)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 1
    assert "lane-a" in stderr
    assert not (root / CANON).exists()
    result = resolve(root)
    assert result["status"] == "fail"
    assert ("MISSING_ARTIFACT", CANON) in errs(result)
    assert cli(root)[0] == 2


@pytest.mark.parametrize("name,lane_a", SHORT_LANES, ids=[s[0] for s in SHORT_LANES])
def test_a_lane_short_of_completed_fails_at_the_lane_under_any_canonical(tmp_path, name, lane_a):
    root = build_fanout(tmp_path, lane_a=lane_a, baseline_canonical=True)
    result = resolve(root)
    assert result["status"] == "fail"
    assert sorted(code for code, path in errs(result) if path == LANE_A) == DEV_CODES
    assert "INVALID_SHARD_SET" in codes(result)
    assert "INVALID_AC_DEVIATION_RECORD" not in codes(result)
    assert cli(root)[0] == 2


def test_a_record_forged_onto_the_canonical_fails_it(tmp_path):
    root = build_fanout(tmp_path)
    assert run_aggregator(root)[0] == 0

    def forge(document):
        document["dev"]["status"] = "blocked"
        document["blocking_issues"] = ["AC19: literal check exits 1"]
        document[FLAG] = True

    edit_canonical(root, forge)
    result = resolve(root)
    assert result["status"] == "fail"
    assert errs(result) == sorted(
        [("INVALID_DEV_STATUS", CANON), ("STALE_CANONICAL", CANON), ("UNRESOLVED_BLOCKERS", CANON)]
    )


def test_divergent_baselines_write_no_canonical(tmp_path):
    def head_ffff(report):
        report["baseline_head_sha"] = "ffff"

    root = build_fanout(tmp_path, lane_a=with_deviation(), lane_b=head_ffff)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 1
    assert "baseline_head_sha 'ffff'" in stderr
    assert not (root / CANON).exists()


def test_validate_shards_names_the_short_lane_once():
    blocked = lane_report(0, "lane-a")
    with_deviation()(blocked)
    problems = aggregator()._validate_shards([("lane-a", blocked), ("lane-b", lane_report(1, "lane-b"))], TASK)
    assert len(problems) == 1
    assert problems[0].startswith("shard 'lane-a': dev.status is 'blocked'")


# ==========================================================================
# the lifecycle row of a dev chain is its one chain call, verbatim
# ==========================================================================


def derive(root):
    return lifecycle().derive_state(root, TASK)


def shape(row):
    return (row["state"], row["next_action"], row["invoke_resolver"])


def test_a_passing_chain_is_close_pending_with_the_chain_verbatim():
    canned = {"schema_version": 2, "mode": "singular", "status": "pass", "lanes": [], "errors": []}
    assert lifecycle().chain_state(TASK, canned) == {
        "state": "close_pending",
        "next_action": "close",
        "invoke_resolver": True,
        "artifact_chain": canned,
        "lanes": [],
    }


@pytest.mark.parametrize("mutate", [with_deviation(), without_flag], ids=["recorded", "unrecorded"])
def test_a_blocked_singular_report_is_not_close_pending(tmp_path, mutate):
    root = build_singular(tmp_path, mutate)
    row = derive(root)
    assert row["state"] != "close_pending"
    assert row["artifact_chain"] == resolve(root)


def test_an_ordinary_fanout_chain_is_close_pending(tmp_path):
    root = build_fanout(tmp_path)
    assert run_aggregator(root)[0] == 0
    row = derive(root)
    assert shape(row) == ("close_pending", "close", True)
    assert row["artifact_chain"] == resolve(root)
    rows = lifecycle().scan(root)
    lane_rows = [r for r in rows if r["task_id"] in (TASK + "-lane-a", TASK + "-lane-b")]
    assert sorted(r["kind"] for r in lane_rows) == ["lane", "lane"]
    assert sorted(r["next_action"] for r in lane_rows) == ["none", "none"]


def test_a_fanout_with_a_failing_lane_qa_is_not_close_pending(tmp_path):
    root = build_fanout(tmp_path, qa={"lane-b": "fail"})
    assert run_aggregator(root)[0] == 0
    row = derive(root)
    assert row["state"] != "close_pending"
    assert row["artifact_chain"] == resolve(root)
    assert any("lane-b" in e["path"] for e in row["artifact_chain"]["errors"])
