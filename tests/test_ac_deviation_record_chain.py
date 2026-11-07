"""Regression tests for harness backlog #92 under strict pass.

A dev report that records an acceptance-criteria deviation is reported
``blocked`` with a non-empty ``blocking_issues`` list.  The resolver no longer
reads the record: such a report fails with exactly the two codes every other
blocked report gets (``INVALID_DEV_STATUS``, ``UNRESOLVED_BLOCKERS``), exit 2,
whatever the record holds, and the route selector passes that chain through
verbatim.  Ordinary chains are unchanged.

Self-contained: every fixture is built under pytest's ``tmp_path``.  The
resolver and the route selector are loaded from the directory named by the
environment variable ``AC_DEVIATION_SCRIPTS_DIR`` (default: the repository
``scripts/`` directory), so the same tests can be aimed at a mutated copy.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = os.path.abspath(
    os.environ.get("AC_DEVIATION_SCRIPTS_DIR")
    or str(Path(__file__).resolve().parent.parent / "scripts")
)

TASK = "20260920-880092"
FLAG = "ac_deviation_with_user_need_satisfied"
BLOCK = FLAG + "_block"
OLD_REJECTION_CODE = "INVALID_AC_DEVIATION_RECORD"
DEV_CODES = ["INVALID_DEV_STATUS", "UNRESOLVED_BLOCKERS"]
PATHS = {
    "ticket": "docs/dev/ticket-%s.md" % TASK,
    "context": "docs/dev/context-%s.json" % TASK,
    "dev": "docs/dev/dev-report-%s.json" % TASK,
    "qa": "docs/dev/qa-report-%s.json" % TASK,
    "completion": "docs/dev/completion-%s.md" % TASK,
}
LANE_A_DEV = "docs/dev/dev-report-%s-lane-a.json" % TASK

_MODULES: dict = {}


def _load(name):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(
            "ac_dev_" + re.sub(r"[^A-Za-z0-9]", "_", name), os.path.join(SCRIPTS_DIR, name)
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULES[name] = module
    return _MODULES[name]


def resolver():
    return _load("resolve-dev-artifact-chain.py")


# --------------------------------------------------------------------------
# fixture builders
# --------------------------------------------------------------------------


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")


def _new_root(base):
    root = base / ("chain%03d" % sum(1 for _ in base.iterdir()))
    root.mkdir()
    return root


def mutated(value, fn):
    clone = copy.deepcopy(value)
    fn(clone)
    return clone


def completed_dev(tid=TASK, files=("scripts/one.py",)):
    return {
        "request_id": tid,
        "task_id": tid,
        "dev": {"status": "completed", "files_modified": list(files), "files_created": []},
        "blocking_issues": [],
    }


GOOD_RECORD = {
    "clause_a_deviated_ac_ids": ["AC19"],
    "clause_b_user_need_verbatim": {"text": "verbatim user need", "source": "spec Section 5"},
    "clause_c_evidence": {"deviation_is_real": "measured", "user_need_satisfied": "measured"},
    "clause_d_guard": "reserved to QA",
}


def recorded_dev(tid=TASK, record=GOOD_RECORD):
    """A blocked report carrying a fully shaped deviation record."""
    dev = completed_dev(tid)
    dev["dev"]["status"] = "blocked"
    dev["blocking_issues"] = ["AC19: literal check exits 1"]
    dev[FLAG] = True
    dev[BLOCK] = copy.deepcopy(record)
    return dev


def qa_report(tid=TASK, status="pass"):
    return {"request_id": tid, "task_id": tid, "qa": {"status": status}}


def singular(base, dev=None, qa=None, skip=(), empty=()):
    root = _new_root(base)
    (root / "scripts").mkdir()
    (root / "scripts" / "one.py").write_text("")
    _write(root / PATHS["ticket"], "# T\n\n**TASK-ID**: `%s`\n" % TASK)
    _write(root / PATHS["context"], {"request_id": TASK, "task_id": TASK})
    _write(root / PATHS["dev"], dev if dev is not None else completed_dev())
    _write(root / PATHS["qa"], qa if qa is not None else qa_report())
    listed = [PATHS[k] for k in ("ticket", "context", "dev", "qa")]
    _write(
        root / PATHS["completion"],
        "# C\n\n**Request ID**: `%s`\n" % TASK + "".join("- `%s`\n" % r for r in listed),
    )
    for key in skip:
        (root / PATHS[key]).unlink()
    for key in empty:
        (root / PATHS[key]).write_text("")
    return root


def fanout(base, lane_a=None, parent_extra=None):
    root = _new_root(base)
    dev_dir = root / "docs" / "dev"
    (root / "scripts").mkdir()
    aggregate: dict = {}
    source = Path(SCRIPTS_DIR, "aggregate-dev-report.py").read_bytes()
    exec(compile(source, "aggregate", "exec"), aggregate)
    loaded = []
    refs = [PATHS["dev"]]
    for index, worker in enumerate(["lane-a", "lane-b"]):
        ident = "%s-%s" % (TASK, worker)
        (root / "scripts" / ("lane-%d.py" % index)).write_text("")
        report = {
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
        if index == 0 and lane_a is not None:
            lane_a(report)
        _write(dev_dir / ("ticket-%s.md" % ident), "# T\n\n**TASK-ID**: `%s`\n" % ident)
        _write(dev_dir / ("context-%s.json" % ident), {"request_id": ident, "task_id": ident})
        _write(dev_dir / ("dev-report-%s.json" % ident), report)
        _write(dev_dir / ("qa-report-%s.json" % ident), qa_report(ident))
        loaded.append((worker, report))
        refs += [
            "docs/dev/%s-%s.%s" % (kind, ident, "md" if kind == "ticket" else "json")
            for kind in ("ticket", "context", "dev-report", "qa-report")
        ]
    parent = aggregate["_build_aggregate"](loaded, TASK)
    parent.update(parent_extra or {})
    _write(root / PATHS["dev"], parent)
    _write(
        root / PATHS["completion"],
        "# C\n\n**Request ID**: `%s`\n" % TASK + "".join("- `%s`\n" % r for r in refs),
    )
    return root


# --------------------------------------------------------------------------
# execution and reading helpers
# --------------------------------------------------------------------------


def resolve(root):
    return resolver().resolve_chain(str(root), TASK)


def run_script(script, root, *extra):
    completed = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, script), "--task-id", TASK, "--project-dir", str(root)]
        + list(extra),
        capture_output=True,
        text=True,
        cwd=str(root),
        timeout=120,
    )
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        payload = {"unparseable": completed.stdout[:300], "stderr": completed.stderr[:300]}
    return completed.returncode, payload


def cli(root):
    return run_script("resolve-dev-artifact-chain.py", root)


def select(root, *extra):
    return run_script("close-route-select.py", root, *extra)


def codes(result):
    return sorted(e["code"] for e in result["errors"])


def errs(result):
    return sorted((e["code"], e["path"]) for e in result["errors"])


def gap(result):
    return (
        result["stage_gaps"],
        result["non_gap_errors"],
        result["late_repair_eligible"],
        result["gap_classification"],
    )


def assert_passes_through(root, want_rc):
    """The CLI exits with the chain's verdict and the selector passes the very
    same chain through with the same exit status."""
    rc_cli, out_cli = cli(root)
    rc, out = select(root)
    assert rc_cli == rc == want_rc
    assert out["outcome"] == "not_selected"
    assert sorted(out) == ["artifact_chain", "outcome"]
    assert json.dumps(out["artifact_chain"], sort_keys=True) == json.dumps(out_cli, sort_keys=True)
    return out_cli


# ==========================================================================
# ordinary chains keep today's behavior
# ==========================================================================


def test_ordinary_singular_chain_passes(tmp_path):
    root = singular(tmp_path)
    result = resolve(root)
    assert result["status"] == "pass"
    assert result["errors"] == []
    assert "disclosed_exceptions" not in result
    assert gap(result) == ([], [], False, "complete")
    assert assert_passes_through(root, 0) == result


def test_ordinary_fanout_chain_passes(tmp_path):
    root = fanout(tmp_path)
    result = resolve(root)
    assert result["status"] == "pass"
    assert result["mode"] == "fanout"
    assert result["errors"] == []
    assert gap(result) == ("not_applicable",) * 4
    assert assert_passes_through(root, 0) == result


@pytest.mark.parametrize(
    "extra",
    [{FLAG: True, BLOCK: "garbage"}, {FLAG: "yes", BLOCK: [1, 2]}, {FLAG: True, BLOCK: GOOD_RECORD}],
    ids=["flag-true-garbage-record", "flag-string-list-record", "flag-true-valid-record"],
)
def test_a_completed_report_carrying_a_flag_or_record_passes(tmp_path, extra):
    dev = completed_dev()
    dev.update(copy.deepcopy(extra))
    root = singular(tmp_path, dev)
    result = resolve(root)
    assert result["status"] == "pass"
    assert result["errors"] == []
    assert assert_passes_through(root, 0) == result


def test_a_failing_qa_is_still_a_fail(tmp_path):
    root = singular(tmp_path, qa=qa_report(status="fail"))
    result = resolve(root)
    assert result["status"] == "fail"
    assert codes(result) == ["INVALID_QA_STATUS"]
    assert_passes_through(root, 2)


# ==========================================================================
# a blocked report fails whatever deviation record it carries
# ==========================================================================


def replay_report():
    """The motivating cycle's report, reduced to a self-contained fixture."""
    dev = recorded_dev(record={
        "shape_source": "close command verdict branch 2 clauses (a) to (d)",
        "clause_a_deviated_ac_ids": ["AC19"],
        "clause_b_user_need_verbatim": {"text": "index README regeneration", "source": "ticket line 9"},
        "clause_c_evidence": {
            "deviation_is_real": {"literal_command": "check.command of AC19"},
            "user_need_satisfied": {"measured_now": "AC1 exit 0"},
        },
    })
    dev["dev"]["status_note"] = "n"
    dev["blocking_issues"] = ["AC19: the literal check still exits 1 (landing log single_write is false)"]
    return dev


RECORDED_REPORTS = [
    ("valid-record", lambda: recorded_dev()),
    ("record-absent", lambda: mutated(recorded_dev(), lambda d: d.pop(BLOCK))),
    ("record-nested-under-dev", lambda: mutated(recorded_dev(), lambda d: d["dev"].update({BLOCK: d.pop(BLOCK)}))),
    ("flag-a-string", lambda: mutated(recorded_dev(), lambda d: d.update({FLAG: "true"}))),
    ("flag-absent", lambda: mutated(recorded_dev(), lambda d: d.pop(FLAG))),
    ("unattributed-blocker", lambda: mutated(recorded_dev(), lambda d: d.update(blocking_issues=["AC19: ok", "real failure"]))),
    ("blank-verbatim-need", lambda: mutated(
        recorded_dev(), lambda d: d[BLOCK]["clause_b_user_need_verbatim"].update(text=""))),
    ("status-rationale", lambda: mutated(recorded_dev(), lambda d: d["dev"].update(status_rationale={
        "classification": "pending_commit_handoff", "blocked_by": "x", "forbidden_action": "y"}))),
    ("real-cycle-replay", replay_report),
]


@pytest.mark.parametrize("name,build", RECORDED_REPORTS, ids=[r[0] for r in RECORDED_REPORTS])
def test_a_blocked_report_fails_with_todays_two_codes_whatever_its_record(tmp_path, name, build):
    root = singular(tmp_path, build())
    result = resolve(root)
    assert result["status"] == "fail"
    assert errs(result) == [(code, PATHS["dev"]) for code in DEV_CODES]
    assert OLD_REJECTION_CODE not in codes(result)
    assert gap(result) == ([], [PATHS["dev"]], False, "beyond_qa")
    assert assert_passes_through(root, 2) == result


@pytest.mark.parametrize("qa_status", ["pass", "fail"])
def test_the_qa_status_never_changes_the_dev_codes(tmp_path, qa_status):
    result = resolve(singular(tmp_path, recorded_dev(), qa=qa_report(status=qa_status)))
    assert result["status"] == "fail"
    assert sorted(c for c in codes(result) if c != "INVALID_QA_STATUS") == DEV_CODES
    assert ("INVALID_QA_STATUS" in codes(result)) is (qa_status == "fail")


# ==========================================================================
# the late-repair route is not laundered
# ==========================================================================


@pytest.mark.parametrize(
    "kwargs,gone,code",
    [
        ({"skip": ("completion",)}, "completion", "MISSING_ARTIFACT"),
        ({"skip": ("ticket",)}, "ticket", "MISSING_ARTIFACT"),
        ({"empty": ("completion",)}, "completion", "EMPTY_ARTIFACT"),
    ],
    ids=["missing-completion", "missing-ticket", "empty-completion"],
)
def test_a_recorded_report_plus_a_stage_gap_is_not_late_repair_eligible(tmp_path, kwargs, gone, code):
    root = singular(tmp_path, recorded_dev(), **kwargs)
    result = resolve(root)
    assert result["status"] == "fail"
    assert errs(result) == sorted([(code, PATHS[gone])] + [(c, PATHS["dev"]) for c in DEV_CODES])
    assert gap(result) == ([PATHS[gone]], [PATHS["dev"]], False, "beyond_qa")
    rc, out = select(root, "--late-repair")
    assert rc == 2 and out.get("outcome") == "not_selected"
    assert out["late_repair"]["outcome"] == "refuse"
    assert json.dumps(out["artifact_chain"], sort_keys=True) == json.dumps(cli(root)[1], sort_keys=True)
    assert not (root / "docs" / "dev" / ("late-repair-run-%s.json" % TASK)).exists()


@pytest.mark.parametrize("skip", ["completion", "ticket"])
def test_control_an_ordinary_stage_gap_is_late_repair_eligible(tmp_path, skip):
    root = singular(tmp_path, completed_dev(), skip=(skip,))
    result = resolve(root)
    assert gap(result) == ([PATHS[skip]], [], True, "beyond_qa")
    rc, out = select(root, "--late-repair")
    assert rc == 0 and out.get("outcome") == "initialized"
    assert (root / "docs" / "dev" / ("late-repair-run-%s.json" % TASK)).exists()


def test_late_repair_combined_with_force_is_still_a_usage_refusal(tmp_path):
    rc, out = select(singular(tmp_path), "--late-repair", "--force")
    assert rc == 1
    assert out.get("outcome") == "refuse"


# ==========================================================================
# fan-out: a recorded lane fails, a record on the parent changes nothing
# ==========================================================================


def _blocked_lane(report):
    report["dev"]["status"] = "blocked"
    report["blocking_issues"] = ["AC19: literal check exits 1"]
    report[FLAG] = True
    report[BLOCK] = copy.deepcopy(GOOD_RECORD)


def test_a_blocked_lane_with_a_record_fails_at_the_lane(tmp_path):
    root = fanout(tmp_path, lane_a=_blocked_lane)
    result = resolve(root)
    assert result["mode"] == "fanout"
    assert result["status"] == "fail"
    lane_codes = sorted(code for code, path in errs(result) if path == LANE_A_DEV)
    assert lane_codes == DEV_CODES
    assert OLD_REJECTION_CODE not in codes(result)
    assert gap(result) == ("not_applicable",) * 4
    assert_passes_through(root, 2)


def test_a_completed_parent_carrying_flag_and_record_is_identical_to_the_plain_chain(tmp_path):
    plain = resolve(fanout(tmp_path))
    carrying = resolve(fanout(tmp_path, parent_extra={FLAG: True, BLOCK: copy.deepcopy(GOOD_RECORD)}))
    assert carrying["status"] == plain["status"] == "pass"
    assert errs(carrying) == errs(plain) == []


def test_a_blocked_parent_carrying_flag_and_record_keeps_todays_errors(tmp_path):
    blocked = {"dev": {"status": "blocked", "files_modified": [], "files_created": []},
               "blocking_issues": ["AC19: x"]}
    base = resolve(fanout(tmp_path, parent_extra=copy.deepcopy(blocked)))
    carrying = resolve(fanout(tmp_path, parent_extra={
        **copy.deepcopy(blocked), FLAG: True, BLOCK: copy.deepcopy(GOOD_RECORD)}))
    assert carrying["status"] == "fail"
    assert errs(carrying) == errs(base)
    assert OLD_REJECTION_CODE not in codes(carrying)
