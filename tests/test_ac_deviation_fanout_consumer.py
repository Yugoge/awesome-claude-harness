"""Regression tests for harness backlog #92 residuals: fan-out AC-deviation
records and the lifecycle presentation of ``pass_with_exceptions``.

Commit 17615575 lets a singular blocked dev-report that carries a legitimate
AC-deviation record reach the quality judgment as ``pass_with_exceptions``.
This file protects the two residuals that commit disclosed:

1. the record must pass through FAN-OUT aggregation into the canonical report
   with the same semantics as the single-lane path, and
2. the lifecycle consumer must present ``pass`` / ``pass_with_exceptions`` /
   ``fail`` consistently with the resolver (never ``blocked``, never an empty
   reason).

Boundary kept from the previous cycle: a record that passes through
aggregation only ENTERS the judgment, it never passes it.  A fan-out cycle with
a legitimate record but a failing quality result must still get an explicit
not-pass verdict (class 5).  What these scripts cannot prove: the substantive
``CLOSE: NO`` verdict and QA's corroboration of every disclosed entry live in
the close command, not here.  A shape-valid but fabricated record with a passing
lane qa-report still reaches ``pass_with_exceptions``; nothing here prevents
that (form is judged, never truth).

Test functions are named ``test_c<N>_<description>__pin`` or ``__change``: N is
the class of the acceptance criterion AC<N> (1 single lane, 2 fan-out with a
record, 3 fan-out without one, 4 partial lanes and merge, 5 release is not a
pass, 6 anti-bypass rows, 7 refresh and failure canonical, 8 one shape place and
default compatibility, 9 lifecycle stage 2 with a stub resolver, 10 real
lifecycle over singular and fan-out chains).  ``__pin`` passes on the unmodified
baseline scripts; ``__change`` fails there and passes after the change.

Self-contained: every fixture is built under pytest's ``tmp_path`` with inline
builders.  The scripts are loaded from the directory named by the environment
variable ``AC_FANOUT_SCRIPTS_DIR`` (default: the repository ``scripts/``
directory), so the same file can be aimed at a copy of the baseline scripts.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = os.path.abspath(
    os.environ.get("AC_FANOUT_SCRIPTS_DIR") or str(REPO_ROOT / "scripts")
)

TASK = "20260920-880093"
FLAG = "ac_deviation_with_user_need_satisfied"
BLOCK = FLAG + "_block"
K_IDS = "clause_a_deviated_ac_ids"
K_VERB = "clause_b_user_need_verbatim"
K_EVID = "clause_c_evidence"
NEWCODE = "INVALID_AC_DEVIATION_RECORD"
KIND = "ac_deviation"
NA = "not_applicable"
NOTE = "AC-deviation provider unavailable"
BLOCKED_LINE = "shard 'lane-a': dev.status is 'blocked', expected 'completed' or 'needs_review'"
CANON = "docs/dev/dev-report-%s.json" % TASK
LANE_A = "docs/dev/dev-report-%s-lane-a.json" % TASK
LANE_B = "docs/dev/dev-report-%s-lane-b.json" % TASK
LANE_A_QA = "docs/dev/qa-report-%s-lane-a.json" % TASK
LANE_B_QA = "docs/dev/qa-report-%s-lane-b.json" % TASK
SINGULAR_DEV = "docs/dev/dev-report-%s.json" % TASK
LANES = ["lane-a", "lane-b"]
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
RATIONALE = {
    "classification": "pending_commit_handoff",
    "blocked_by": "commit",
    "forbidden_action": "git commit",
}

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
    way the previous cycle's fixtures build a baseline-style canonical."""
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


def record(ids, text="need-A", source="spec s5"):
    return {
        K_IDS: list(ids),
        K_VERB: {"text": text, "source": source},
        K_EVID: {
            "deviation_is_real": "m-deviation_is_real",
            "user_need_satisfied": "m-user_need_satisfied",
        },
    }


def with_deviation(ids=("AC19",), blockers=("AC19: literal check exits 1",), text="need-A", source="spec s5"):
    def apply(report):
        report["dev"]["status"] = "blocked"
        report["blocking_issues"] = list(blockers)
        report[FLAG] = True
        report[BLOCK] = record(ids, text, source)

    return apply


def without_flag(report):
    with_deviation()(report)
    report.pop(FLAG)


def with_string_flag(report):
    with_deviation()(report)
    report[FLAG] = "true"


def with_unattributed_blocker(report):
    with_deviation(blockers=("AC19: x", "unrelated thing"))(report)


def completed_with_garbage(report):
    report[FLAG] = True
    report[BLOCK] = "garbage"


def needs_review(report):
    report["dev"]["status"] = "needs_review"
    report["dev"]["status_rationale"] = dict(RATIONALE)
    report["blocking_issues"] = ["awaiting commit"]


def head_sha_ffff(report):
    report["baseline_head_sha"] = "ffff"


def many_ids(prefix):
    ids = ["%s%02d" % (prefix, number) for number in range(1, 21)]
    return with_deviation(ids=ids, blockers=("%s: y" % ids[0],))


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


def build_fanout(base, lane_a=None, lane_b=None, qa=None, omit_ref=None, baseline_canonical=False):
    """Two-lane fan-out chain: every lane artifact, the completion note listing
    every reference, and (only when asked) a baseline-style canonical."""
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
    if omit_ref is not None:
        refs = [ref for ref in refs if ref != omit_ref]
    _write(
        dev_dir / ("completion-%s.md" % TASK),
        "# C\n\n**Request ID**: `%s`\n" % TASK + "".join("- `%s`\n" % ref for ref in refs),
    )
    if baseline_canonical:
        _write(root / CANON, bare_aggregator()["_build_aggregate"](loaded, TASK))
    return root


def completed_singular(ident=TASK):
    return {
        "request_id": ident,
        "task_id": ident,
        "dev": {"status": "completed", "files_modified": ["scripts/one.py"], "files_created": []},
        "blocking_issues": [],
    }


def build_singular(base, mutate=None, qa_status="pass", omit_ref=None):
    root = _new_root(base)
    (root / "scripts").mkdir()
    (root / "scripts" / "one.py").write_text("")
    dev_dir = root / "docs" / "dev"
    report = completed_singular()
    if mutate is not None:
        mutate(report)
    _write(dev_dir / ("ticket-%s.md" % TASK), "# T\n\n**TASK-ID**: `%s`\n" % TASK)
    _write(dev_dir / ("context-%s.json" % TASK), {"request_id": TASK, "task_id": TASK})
    _write(dev_dir / ("dev-report-%s.json" % TASK), report)
    _write(dev_dir / ("qa-report-%s.json" % TASK), qa_report(TASK, qa_status))
    refs = ["docs/dev/%s-%s.%s" % (kind, TASK, "md" if kind == "ticket" else "json")
            for kind in ("ticket", "context", "dev-report", "qa-report")]
    if omit_ref is not None:
        refs = [ref for ref in refs if ref != omit_ref]
    _write(
        dev_dir / ("completion-%s.md" % TASK),
        "# C\n\n**Request ID**: `%s`\n" % TASK + "".join("- `%s`\n" % ref for ref in refs),
    )
    return root


# --------------------------------------------------------------------------
# execution and reading helpers
# --------------------------------------------------------------------------


def run_aggregator(root, *extra, scripts_dir=None):
    script = os.path.join(scripts_dir or SCRIPTS_DIR, "aggregate-dev-report.py")
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    done = subprocess.run(
        [sys.executable, script, "--task-id", TASK] + list(extra),
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


def run_script(script, root):
    done = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, script), "--task-id", TASK, "--project-dir", str(root)],
        capture_output=True,
        text=True,
        cwd=str(root),
        timeout=120,
    )
    try:
        payload = json.loads(done.stdout)
    except ValueError:
        payload = {"unparseable": done.stdout[:300], "stderr": done.stderr[:300]}
    return done.returncode, payload


def cli(root):
    return run_script("resolve-dev-artifact-chain.py", root)


def select(root):
    return run_script("close-route-select.py", root)


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


def entry_tuples(entries):
    return sorted(
        (e["path"], e["code"], e["lane_task_id"], e["kind"], e["classification"],
         e["evidence_ref_count"], tuple(e["deviated_ac_ids"]))
        for e in entries
    )


def lane_tuples(entries, path):
    return sorted(
        (e["code"], e["kind"], e["classification"], tuple(e["deviated_ac_ids"]), e["evidence_ref_count"])
        for e in entries
        if e["path"] == path
    )


def deviation_key_names(document):
    return [key for key in document if "ac_deviation" in key]


# ==========================================================================
# class 1: single-lane path (regression pins of commit 17615575)
# ==========================================================================


def test_c1_singular_deviation_chain_reaches_pass_with_exceptions__pin(tmp_path):
    root = build_singular(tmp_path, with_deviation())
    result = resolve(root)
    assert result["status"] == "pass_with_exceptions"
    assert result["status"] != "pass"
    assert result["errors"] == []
    assert sorted(e["code"] for e in result["disclosed_exceptions"]) == [
        "INVALID_DEV_STATUS",
        "UNRESOLVED_BLOCKERS",
    ]
    assert entry_tuples(result["disclosed_exceptions"]) == [
        (SINGULAR_DEV, "INVALID_DEV_STATUS", TASK, KIND, FLAG, 2, ("AC19",)),
        (SINGULAR_DEV, "UNRESOLVED_BLOCKERS", TASK, KIND, FLAG, 2, ("AC19",)),
    ]
    assert gap(result) == ([], [], False, "complete")
    rc, out = cli(root)
    assert rc == 0
    assert out == result
    rc, out = select(root)
    assert rc == 0
    assert sorted(out) == ["artifact_chain", "outcome"]
    assert out["artifact_chain"] == result


def test_c1_ordinary_singular_chain_stays_pass__pin(tmp_path):
    root = build_singular(tmp_path)
    result = resolve(root)
    assert result["status"] == "pass"
    assert result["errors"] == []
    assert result["disclosed_exceptions"] == []
    assert gap(result) == ([], [], False, "complete")
    rc, out = cli(root)
    assert rc == 0
    assert out["status"] == "pass"


def test_c1_blocked_singular_report_without_the_flag_keeps_todays_codes__pin(tmp_path):
    root = build_singular(tmp_path, without_flag)
    result = resolve(root)
    assert result["status"] == "fail"
    assert codes(result) == ["INVALID_DEV_STATUS", "UNRESOLVED_BLOCKERS"]
    assert result["disclosed_exceptions"] == []
    assert NEWCODE not in codes(result)
    rc, out = cli(root)
    assert rc == 2
    assert out["status"] == "fail"


# ==========================================================================
# class 2: fan-out deviation end to end
# ==========================================================================


def test_c2_first_aggregation_exits_zero_and_writes_the_merged_record__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "aggregated"
    canonical = read_canonical(root)
    assert canonical["dev"]["status"] == "blocked"
    assert canonical["blocking_issues"] == ["AC19: literal check exits 1"]
    assert canonical[FLAG] is True
    assert canonical[BLOCK] == {
        K_IDS: ["AC19"],
        K_VERB: {
            "text": "need-A",
            "source": "spec s5",
            "lanes": {"lane-a": {"text": "need-A", "source": "spec s5"}},
        },
        K_EVID: {
            "lane-a:deviation_is_real": "m-deviation_is_real",
            "lane-a:user_need_satisfied": "m-user_need_satisfied",
        },
    }


def test_c2_second_aggregation_validates_and_leaves_the_bytes_unchanged__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    before = (root / CANON).read_bytes()
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "validated"
    assert (root / CANON).read_bytes() == before
    assert read_canonical(root)[FLAG] is True


def test_c2_resolver_releases_the_chain_as_pass_with_exceptions__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    result = resolve(root)
    assert result["status"] == "pass_with_exceptions"
    assert result["status"] != "pass"
    assert result["mode"] == "fanout"
    assert result["errors"] == []
    assert entry_tuples(result["disclosed_exceptions"]) == sorted([
        (CANON, "INVALID_DEV_STATUS", TASK, KIND, FLAG, 2, ("AC19",)),
        (CANON, "UNRESOLVED_BLOCKERS", TASK, KIND, FLAG, 2, ("AC19",)),
        (LANE_A, "INVALID_DEV_STATUS", TASK + "-lane-a", KIND, FLAG, 2, ("AC19",)),
        (LANE_A, "UNRESOLVED_BLOCKERS", TASK + "-lane-a", KIND, FLAG, 2, ("AC19",)),
    ])
    assert gap(result) == (NA, NA, NA, NA)


def test_c2_resolver_cli_and_route_selector_exit_zero__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    result = resolve(root)
    rc, out = cli(root)
    assert rc == 0
    assert out == result
    rc, out = select(root)
    assert rc == 0
    assert sorted(out) == ["artifact_chain", "outcome"]
    assert out["artifact_chain"] == result
    assert out["artifact_chain"]["status"] == "pass_with_exceptions"


def test_c2_lane_entries_match_the_single_lane_path__change(tmp_path):
    fan_root = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(fan_root)
    assert rc == 0
    fan = resolve(fan_root)
    single = resolve(build_singular(tmp_path, with_deviation()))
    assert single["status"] == "pass_with_exceptions"
    single_tuples = lane_tuples(single["disclosed_exceptions"], SINGULAR_DEV)
    assert single_tuples == [
        ("INVALID_DEV_STATUS", KIND, FLAG, ("AC19",), 2),
        ("UNRESOLVED_BLOCKERS", KIND, FLAG, ("AC19",), 2),
    ]
    assert lane_tuples(fan["disclosed_exceptions"], LANE_A) == single_tuples
    assert fan["status"] == "pass_with_exceptions"


# ==========================================================================
# class 3: fan-out without a deviation is unchanged
# ==========================================================================


def test_c3_deviation_free_fanout_aggregates_and_resolves_as_pass__pin(tmp_path):
    root = build_fanout(tmp_path)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "aggregated"
    canonical = read_canonical(root)
    assert canonical["dev"]["status"] == "completed"
    assert deviation_key_names(canonical) == []
    result = resolve(root)
    assert result["status"] == "pass"
    assert result["mode"] == "fanout"
    assert result["disclosed_exceptions"] == []
    assert gap(result) == (NA, NA, NA, NA)


def test_c3_second_aggregation_validates_the_deviation_free_canonical__pin(tmp_path):
    root = build_fanout(tmp_path)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    before = (root / CANON).read_bytes()
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "validated"
    assert (root / CANON).read_bytes() == before


def test_c3_baseline_style_canonical_stays_fresh__pin(tmp_path):
    root = build_fanout(tmp_path, baseline_canonical=True)
    before = (root / CANON).read_bytes()
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "validated"
    assert (root / CANON).read_bytes() == before
    result = resolve(root)
    assert result["status"] == "pass"
    assert "STALE_CANONICAL" not in codes(result)
    assert result["disclosed_exceptions"] == []


def test_c3_projection_with_one_argument_is_the_eleven_keys__pin(tmp_path):
    root = build_fanout(tmp_path)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    projection = aggregator()._canonical_projection(read_canonical(root))
    assert list(projection) == ELEVEN_KEYS
    assert projection["dev"]["status"] == "completed"


# ==========================================================================
# class 4: partial lanes and merge semantics
# ==========================================================================


def test_c4_only_lane_a_carries_a_record__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    canonical = read_canonical(root)
    assert canonical[BLOCK][K_IDS] == ["AC19"]
    assert sorted(canonical[BLOCK][K_VERB]["lanes"]) == ["lane-a"]
    assert sorted(canonical[BLOCK][K_EVID]) == [
        "lane-a:deviation_is_real",
        "lane-a:user_need_satisfied",
    ]
    result = resolve(root)
    assert result["status"] == "pass_with_exceptions"
    assert sorted(set(e["path"] for e in result["disclosed_exceptions"])) == sorted([CANON, LANE_A])
    assert len(result["disclosed_exceptions"]) == 4
    assert [e for e in result["disclosed_exceptions"] if e["path"] == LANE_B] == []


def test_c4_overlapping_ids_merge_in_lane_order_without_duplicates__change(tmp_path):
    root = both_lanes(tmp_path)
    canonical = read_canonical(root)
    assert canonical[BLOCK][K_IDS] == ["AC19", "AC20", "AC21"]
    assert canonical[BLOCK][K_VERB]["text"] == "need-A"
    assert canonical[BLOCK][K_VERB]["source"] == "spec s5"
    assert canonical[BLOCK][K_VERB]["lanes"] == {
        "lane-a": {"text": "need-A", "source": "spec s5"},
        "lane-b": {"text": "need-B", "source": "spec s7"},
    }
    assert canonical["blocking_issues"] == ["AC19: x", "AC21: y"]
    assert canonical["dev"]["status"] == "blocked"


def test_c4_evidence_keys_are_qualified_per_lane_and_lose_no_value__change(tmp_path):
    root = both_lanes(tmp_path)
    evidence = read_canonical(root)[BLOCK][K_EVID]
    assert sorted(evidence) == [
        "lane-a:deviation_is_real",
        "lane-a:user_need_satisfied",
        "lane-b:deviation_is_real",
        "lane-b:user_need_satisfied",
    ]
    assert evidence["lane-b:deviation_is_real"] == "m-deviation_is_real"
    assert resolver()._ac_deviation_violations(read_canonical(root)) == []


def test_c4_two_record_bearing_lanes_release_with_six_disclosed_entries__change(tmp_path):
    root = both_lanes(tmp_path)
    result = resolve(root)
    assert result["status"] == "pass_with_exceptions"
    assert result["errors"] == []
    assert len(result["disclosed_exceptions"]) == 6
    assert sorted(
        (e["path"], e["code"], tuple(e["deviated_ac_ids"]), e["evidence_ref_count"])
        for e in result["disclosed_exceptions"]
    ) == sorted([
        (CANON, "INVALID_DEV_STATUS", ("AC19", "AC20", "AC21"), 4),
        (CANON, "UNRESOLVED_BLOCKERS", ("AC19", "AC20", "AC21"), 4),
        (LANE_A, "INVALID_DEV_STATUS", ("AC19", "AC20"), 2),
        (LANE_A, "UNRESOLVED_BLOCKERS", ("AC19", "AC20"), 2),
        (LANE_B, "INVALID_DEV_STATUS", ("AC20", "AC21"), 2),
        (LANE_B, "UNRESOLVED_BLOCKERS", ("AC20", "AC21"), 2),
    ])


def test_c4_canonical_file_union_covers_both_lanes__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    canonical = read_canonical(root)
    assert canonical["dev"]["files_modified"] == ["scripts/lane-0.py", "scripts/lane-1.py"]
    assert canonical["dev"]["files_created"] == []
    assert resolve(root)["checks"]["file_unions_exact"] is True


def both_lanes(base):
    root = build_fanout(
        base,
        lane_a=with_deviation(ids=("AC19", "AC20"), blockers=("AC19: x",)),
        lane_b=with_deviation(ids=("AC20", "AC21"), blockers=("AC21: y",), text="need-B", source="spec s7"),
    )
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    return root


# ==========================================================================
# class 5: a released record is not a pass
# ==========================================================================


def test_c5_a_failing_lane_b_qa_report_gives_an_explicit_not_pass__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation(), qa={"lane-b": "fail"})
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    result = resolve(root)
    assert result["status"] == "fail"
    assert errs(result) == [("INVALID_QA_STATUS", LANE_B_QA)]
    rc, out = cli(root)
    assert rc == 2
    assert out["status"] == "fail"
    rc, out = select(root)
    assert rc == 2
    assert sorted(out) == ["artifact_chain", "outcome"]


def test_c5_a_failing_record_bearing_lane_qa_report_keeps_every_error_hard__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation(), qa={"lane-a": "fail"})
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    result = resolve(root)
    assert result["status"] == "fail"
    assert errs(result) == sorted([
        ("INVALID_DEV_STATUS", CANON),
        ("INVALID_DEV_STATUS", LANE_A),
        ("INVALID_QA_STATUS", LANE_A_QA),
        ("UNRESOLVED_BLOCKERS", CANON),
        ("UNRESOLVED_BLOCKERS", LANE_A),
    ])
    assert result["disclosed_exceptions"] == []
    rc, out = cli(root)
    assert rc == 2
    assert out["status"] == "fail"


def test_c5_an_unrelated_quality_defect_fails_exactly_like_a_deviation_free_chain__change(tmp_path):
    with_record = build_fanout(tmp_path, lane_a=with_deviation(), omit_ref=LANE_B_QA)
    rc, payload, stderr = run_aggregator(with_record)
    assert rc == 0
    plain = build_fanout(tmp_path, omit_ref=LANE_B_QA)
    rc, payload, stderr = run_aggregator(plain)
    assert rc == 0
    record_result = resolve(with_record)
    plain_result = resolve(plain)
    assert plain_result["status"] == "fail"
    assert record_result["status"] == "fail"
    assert errs(record_result) == errs(plain_result)
    assert errs(plain_result) != []
    rc, out = cli(with_record)
    assert rc == 2
    assert out["status"] == "fail"


def test_c5_only_the_record_and_each_qa_status_separate_release_from_failure__change(tmp_path):
    flagged = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(flagged)
    assert rc == 0
    assert resolve(flagged)["status"] == "pass_with_exceptions"
    unflagged = build_fanout(tmp_path, lane_a=without_flag)
    rc, payload, stderr = run_aggregator(unflagged)
    assert rc == 1
    unflagged_result = resolve(unflagged)
    assert unflagged_result["status"] == "fail"
    assert "INVALID_DEV_STATUS" in codes(unflagged_result)
    assert "UNRESOLVED_BLOCKERS" in codes(unflagged_result)
    failing = build_fanout(tmp_path, lane_a=with_deviation(), qa={"lane-a": "fail"})
    rc, payload, stderr = run_aggregator(failing)
    assert rc == 0
    assert resolve(failing)["status"] == "fail"


def two_record_lanes(base, qa):
    """Two record-bearing lanes with disjoint ids, blockers and needs; the
    canonical is produced by the aggregator (exit 0: aggregation is not judgment)."""
    root = build_fanout(
        base,
        lane_a=with_deviation(),
        lane_b=with_deviation(ids=("AC21",), blockers=("AC21: y",), text="need-B", source="spec s7"),
        qa=qa,
    )
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "aggregated"
    return root


def test_c5_one_failing_lane_qa_among_two_record_bearing_lanes_keeps_the_canonical_hard__change(tmp_path):
    """Multi-lane form of the boundary: the canonical's deviation entries are
    released only when EVERY record-bearing lane is itself releasable."""
    root = two_record_lanes(tmp_path, {"lane-a": "fail", "lane-b": "pass"})
    canonical = read_canonical(root)
    assert canonical["dev"]["status"] == "blocked"
    assert canonical[BLOCK][K_IDS] == ["AC19", "AC21"]
    result = resolve(root)
    assert result["status"] == "fail"
    assert errs(result) == sorted([
        ("INVALID_DEV_STATUS", CANON),
        ("UNRESOLVED_BLOCKERS", CANON),
        ("INVALID_DEV_STATUS", LANE_A),
        ("UNRESOLVED_BLOCKERS", LANE_A),
        ("INVALID_QA_STATUS", LANE_A_QA),
    ])
    assert sorted(e["code"] for e in result["errors"] if e["path"] == CANON) == [
        "INVALID_DEV_STATUS",
        "UNRESOLVED_BLOCKERS",
    ]
    assert [e["code"] for e in result["disclosed_exceptions"] if e["path"] == CANON] == []
    assert [e["code"] for e in result["disclosed_exceptions"] if e["path"] == LANE_A] == []
    assert entry_tuples(result["disclosed_exceptions"]) == sorted([
        (LANE_B, "INVALID_DEV_STATUS", TASK + "-lane-b", KIND, FLAG, 2, ("AC21",)),
        (LANE_B, "UNRESOLVED_BLOCKERS", TASK + "-lane-b", KIND, FLAG, 2, ("AC21",)),
    ])
    rc, out = cli(root)
    assert rc == 2
    assert out["status"] == "fail"
    assert errs(out) == errs(result)
    rc, out = select(root)
    assert rc == 2
    assert sorted(out) == ["artifact_chain", "outcome"]
    assert out["artifact_chain"]["status"] == "fail"
    assert errs(out["artifact_chain"]) == errs(result)


def test_c5_two_passing_lane_qa_reports_release_both_lanes_and_the_canonical__change(tmp_path):
    """Symmetric control of the boundary above: same two lanes, both lane
    qa-reports pass, so the canonical is released with the lanes."""
    root = two_record_lanes(tmp_path, {"lane-a": "pass", "lane-b": "pass"})
    result = resolve(root)
    assert result["status"] == "pass_with_exceptions"
    assert result["errors"] == []
    assert len(result["disclosed_exceptions"]) == 6
    assert entry_tuples(result["disclosed_exceptions"]) == sorted([
        (CANON, "INVALID_DEV_STATUS", TASK, KIND, FLAG, 4, ("AC19", "AC21")),
        (CANON, "UNRESOLVED_BLOCKERS", TASK, KIND, FLAG, 4, ("AC19", "AC21")),
        (LANE_A, "INVALID_DEV_STATUS", TASK + "-lane-a", KIND, FLAG, 2, ("AC19",)),
        (LANE_A, "UNRESOLVED_BLOCKERS", TASK + "-lane-a", KIND, FLAG, 2, ("AC19",)),
        (LANE_B, "INVALID_DEV_STATUS", TASK + "-lane-b", KIND, FLAG, 2, ("AC21",)),
        (LANE_B, "UNRESOLVED_BLOCKERS", TASK + "-lane-b", KIND, FLAG, 2, ("AC21",)),
    ])
    rc, out = cli(root)
    assert rc == 0
    assert out == result
    rc, out = select(root)
    assert rc == 0
    assert sorted(out) == ["artifact_chain", "outcome"]
    assert out["artifact_chain"] == result


# ==========================================================================
# class 6: anti-bypass rows R1-R10
# ==========================================================================

# rows that already behave this way on the baseline scripts
PIN_ROWS = [
    (
        "r1_record_on_the_canonical_only",
        0,
        "fail",
        [("INVALID_DEV_STATUS", CANON), ("STALE_CANONICAL", CANON), ("UNRESOLVED_BLOCKERS", CANON)],
    ),
    (
        "r6_blocked_lane_without_the_flag",
        1,
        "fail",
        [
            ("INVALID_DEV_STATUS", CANON),
            ("INVALID_DEV_STATUS", LANE_A),
            ("INVALID_SHARD_SET", CANON),
            ("UNRESOLVED_BLOCKERS", CANON),
            ("UNRESOLVED_BLOCKERS", LANE_A),
        ],
    ),
    ("r7_completed_lane_carrying_a_garbage_record", 0, "pass", []),
    ("r10_completed_canonical_carrying_a_record", 0, "pass", []),
]

# rows whose outcome the change introduces (-1 = the aggregator is not run)
REJECTED_FANOUT = [
    ("INVALID_AC_DEVIATION_RECORD", LANE_A),
    ("INVALID_DEV_STATUS", CANON),
    ("INVALID_DEV_STATUS", LANE_A),
    ("INVALID_SHARD_SET", CANON),
    ("INVALID_SHARD_SET", CANON),
    ("UNRESOLVED_BLOCKERS", CANON),
    ("UNRESOLVED_BLOCKERS", LANE_A),
]
CANONICAL_REJECTED = [
    ("INVALID_AC_DEVIATION_RECORD", CANON),
    ("INVALID_DEV_STATUS", CANON),
    ("UNRESOLVED_BLOCKERS", CANON),
]
CHANGE_ROWS = [
    (
        "r2_record_lane_with_a_baseline_style_canonical",
        -1,
        "fail",
        [("STALE_CANONICAL", CANON), ("UNRESOLVED_BLOCKERS", CANON)],
        False,
    ),
    ("r3_lane_and_canonical_disagree", 0, "fail", [("STALE_CANONICAL", CANON)], False),
    ("r4_blocker_not_attributable_to_a_recorded_id", 1, "fail", REJECTED_FANOUT, True),
    ("r5_flag_is_the_string_true", 1, "fail", REJECTED_FANOUT, True),
    ("r8_record_lane_plus_a_needs_review_lane", 0, "fail", CANONICAL_REJECTED, False),
    ("r9_union_of_ids_above_the_cap", 0, "fail", CANONICAL_REJECTED, False),
]


def row_fixture(base, row):
    """Build one anti-bypass row; returns (root, aggregator exit code or -1)."""
    if row.startswith("r1_"):
        root = build_fanout(base)
        rc, payload, stderr = run_aggregator(root)

        def forge(document):
            document["dev"]["status"] = "blocked"
            document["blocking_issues"] = ["AC19: literal check exits 1"]
            document[FLAG] = True
            document[BLOCK] = record(["AC19"])

        edit_canonical(root, forge)
        return root, rc
    if row.startswith("r2_"):
        return build_fanout(base, lane_a=with_deviation(), baseline_canonical=True), -1
    if row.startswith("r3_"):
        root = build_fanout(base, lane_a=with_deviation())
        rc, payload, stderr = run_aggregator(root)
        assert rc == 0
        edit_canonical(root, lambda document: document[BLOCK].update({K_IDS: ["AC19", "AC77"]}))
        return root, rc
    if row.startswith("r10_"):
        root = build_fanout(base)
        rc, payload, stderr = run_aggregator(root)
        edit_canonical(
            root, lambda document: document.update({FLAG: True, BLOCK: record(["AC19"])})
        )
        return root, rc
    lane_a, lane_b = {
        "r4_": (with_unattributed_blocker, None),
        "r5_": (with_string_flag, None),
        "r6_": (without_flag, None),
        "r7_": (completed_with_garbage, None),
        "r8_": (with_deviation(), needs_review),
        "r9_": (many_ids("A"), many_ids("B")),
    }[row[:3]]
    root = build_fanout(base, lane_a=lane_a, lane_b=lane_b)
    rc, payload, stderr = run_aggregator(root)
    return root, rc


@pytest.mark.parametrize("row,agg_rc,status,expected", PIN_ROWS, ids=[r[0] for r in PIN_ROWS])
def test_c6_pinned_anti_bypass_rows__pin(tmp_path, row, agg_rc, status, expected):
    root, rc = row_fixture(tmp_path, row)
    assert rc == agg_rc
    result = resolve(root)
    assert result["status"] == status
    assert errs(result) == sorted(expected)
    assert result["disclosed_exceptions"] == []
    assert NEWCODE not in codes(result)


@pytest.mark.parametrize(
    "row,agg_rc,status,expected,no_disclosure", CHANGE_ROWS, ids=[r[0] for r in CHANGE_ROWS]
)
def test_c6_changed_anti_bypass_rows__change(tmp_path, row, agg_rc, status, expected, no_disclosure):
    root, rc = row_fixture(tmp_path, row)
    assert rc == agg_rc
    result = resolve(root)
    assert result["status"] == status
    assert errs(result) == sorted(expected)
    if no_disclosure:
        assert result["disclosed_exceptions"] == []
    rc, out = cli(root)
    assert rc == 2
    assert out["status"] == "fail"


def test_c6_route_selector_surfaces_the_explicit_rejection__change(tmp_path):
    root, rc = row_fixture(tmp_path, "r4_blocker_not_attributable_to_a_recorded_id")
    assert rc == 1
    rc, out = select(root)
    assert rc == 2
    assert out["explicit_rejection"]["code"] == "INVALID_AC_DEVIATION_RECORD"
    assert out["explicit_rejection"]["path"] == LANE_A
    assert out["artifact_chain"]["status"] == "fail"


def test_c6_aggregator_stderr_names_the_rejected_record__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_unattributed_blocker)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 1
    assert BLOCKED_LINE in stderr
    assert "shard 'lane-a': AC-deviation record rejected:" in stderr


def test_c6_a_blocked_lane_without_the_flag_gets_no_rejection_line__pin(tmp_path):
    root = build_fanout(tmp_path, lane_a=without_flag)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 1
    assert BLOCKED_LINE in stderr
    assert "AC-deviation record rejected" not in stderr


# ==========================================================================
# class 7: refresh of an old canonical, failure canonical, dry-run
# ==========================================================================


def test_c7_a_stale_baseline_style_canonical_is_refreshed_with_the_record__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation(), baseline_canonical=True)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "aggregated"
    canonical = read_canonical(root)
    assert canonical[FLAG] is True
    assert canonical[BLOCK][K_IDS] == ["AC19"]
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    assert payload["action"] == "validated"
    assert resolve(root)["status"] == "pass_with_exceptions"


def test_c7_the_failure_canonical_is_blocked_and_carries_no_record__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation(), lane_b=head_sha_ffff)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 1
    canonical = read_canonical(root)
    assert canonical["dev"]["status"] == "blocked"
    assert deviation_key_names(canonical) == []
    assert canonical["blocking_issues"] == [
        "AC19: literal check exits 1",
        "shard 'lane-b': baseline_head_sha 'ffff' != first shard '0123456789abcdef'",
    ]
    result = resolve(root)
    assert result["status"] == "fail"
    assert codes(result) == ["INVALID_DEV_STATUS", "INVALID_SHARD_SET", "UNRESOLVED_BLOCKERS"]


def test_c7_dry_run_validates_without_writing_a_canonical__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(root, "--dry-run")
    assert rc == 0
    assert payload["action"] == "skipped"
    assert (root / CANON).exists() is False


# ==========================================================================
# class 8: one shape place, default compatibility, provider, fail-closed loader
# ==========================================================================

SIX_LITERALS = [FLAG, K_IDS, K_VERB, K_EVID, NEWCODE, KIND]


def string_constant_counts(script):
    tree = ast.parse(Path(SCRIPTS_DIR, script).read_text(encoding="utf-8"))
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    counts = {literal: 0 for literal in SIX_LITERALS + [BLOCK]}
    loads = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if node.value in counts:
                counts[node.value] += 1
        if isinstance(node, ast.Name) and node.id == "AC_DEVIATION_RECORD_KEY" and isinstance(node.ctx, ast.Load):
            loads += 1
    return counts, loads


def two_shards():
    blocked = lane_report(0, "lane-a")
    with_deviation()(blocked)
    return [("lane-a", blocked), ("lane-b", lane_report(1, "lane-b"))]


def test_c8_the_shape_is_defined_once_in_the_resolver_only__pin():
    counts, loads = string_constant_counts("resolve-dev-artifact-chain.py")
    for literal in SIX_LITERALS:
        assert counts[literal] == 1, literal
    assert counts[BLOCK] in (0, 1)
    assert loads >= 1
    for script in ("aggregate-dev-report.py", "dev-lifecycle.py"):
        counts, loads = string_constant_counts(script)
        for literal in SIX_LITERALS + [BLOCK]:
            assert counts[literal] == 0, script + " " + literal


def test_c8_baseline_signatures_keep_the_baseline_behaviour__pin():
    module = aggregator()
    shards = two_shards()
    assert module._validate_shards(shards, TASK) == [BLOCKED_LINE]
    built = module._build_aggregate(shards, TASK)
    assert built["dev"]["status"] == "completed"
    assert deviation_key_names(built) == []
    assert list(module._canonical_projection(built)) == ELEVEN_KEYS


def test_c8_the_aggregator_source_executes_into_a_bare_namespace__pin():
    names = sorted(bare_aggregator())
    assert "__file__" not in names
    assert "resolve_chain" not in names
    assert "_ac_deviation_violations" not in names
    assert "AC_DEVIATION_FLAG_KEY" not in names
    assert "_validate_shards" in names


def test_c8_provider_matches_the_single_validator_and_drives_the_aggregator__change():
    module = resolver()
    provider = module.ac_deviation_provider()
    valid = lane_report(0, "lane-a")
    with_deviation()(valid)
    plain_blocked = lane_report(0, "lane-a")
    plain_blocked["dev"]["status"] = "blocked"
    flag_false = copy.deepcopy(valid)
    flag_false[FLAG] = False
    malformed = copy.deepcopy(valid)
    malformed[BLOCK][K_IDS] = []
    non_literal = copy.deepcopy(valid)
    non_literal[FLAG] = "true"
    completed = lane_report(0, "lane-a")
    completed[FLAG] = True
    inputs = [plain_blocked, flag_false, valid, malformed, non_literal, completed]
    for document in inputs:
        assert provider.violations(document) == module._ac_deviation_violations(document)
    assert provider.violations(valid) == []
    assert provider.violations(plain_blocked) is None
    assert provider.violations(completed) is None
    assert provider.violations(malformed) != []
    aggregate = aggregator()
    shards = two_shards()
    assert aggregate._validate_shards(shards, TASK, deviation=provider) == []
    built = aggregate._build_aggregate(shards, TASK, deviation=provider)
    assert built["dev"]["status"] == "blocked"
    assert built[FLAG] is True
    assert built[BLOCK][K_IDS] == ["AC19"]
    projection = aggregate._canonical_projection(built, deviation=provider)
    assert sorted(set(projection) - set(ELEVEN_KEYS)) == sorted([FLAG, BLOCK])


@pytest.mark.parametrize("resolver_source", [None, "raise RuntimeError('provider load failure')\n"], ids=["absent", "raising"])
def test_c8_an_unusable_resolver_fails_closed_with_exactly_one_note__change(tmp_path, resolver_source):
    scripts_copy = tmp_path / "scripts-copy"
    scripts_copy.mkdir()
    (scripts_copy / "aggregate-dev-report.py").write_bytes(Path(SCRIPTS_DIR, "aggregate-dev-report.py").read_bytes())
    if resolver_source is not None:
        (scripts_copy / "resolve-dev-artifact-chain.py").write_text(resolver_source, encoding="utf-8")
    root = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(root, scripts_dir=str(scripts_copy))
    assert rc == 1
    assert BLOCKED_LINE in stderr
    assert "Traceback" not in stderr
    canonical = read_canonical(root)
    assert canonical["dev"]["status"] == "blocked"
    assert deviation_key_names(canonical) == []
    assert len([line for line in stderr.splitlines() if NOTE in line]) == 1


# ==========================================================================
# class 9: lifecycle stage 2 with a stub resolver
# ==========================================================================


def stage2(tmp_path, canned):
    dev_dir = tmp_path / "docs" / "dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    stub = types.SimpleNamespace(resolve_chain=lambda project_root, task_id: canned)
    return lifecycle().stage2_close_eligibility(
        tmp_path, dev_dir, TASK, {"dev": {"status": "completed"}}, types.SimpleNamespace(), stub
    )


def canned_result(status, mode="singular", errors=None, disclosed=None, schema_version=2):
    return {
        "schema_version": schema_version,
        "mode": mode,
        "status": status,
        "errors": errors if errors is not None else [],
        "disclosed_exceptions": disclosed if disclosed is not None else [],
    }


def test_c9_a_passing_singular_chain_keeps_its_exact_row__pin(tmp_path):
    row = stage2(tmp_path, canned_result("pass"))
    assert row == {
        "state": "close_pending",
        "next_action": "close",
        "invoke_resolver": True,
        "resolver_schema_version": 2,
        "resolver_mode": "singular",
    }
    assert sorted(row) == [
        "invoke_resolver",
        "next_action",
        "resolver_mode",
        "resolver_schema_version",
        "state",
    ]


def test_c9_pass_with_exceptions_is_close_eligible_and_never_blocked__change(tmp_path):
    entries = [
        {"code": "INVALID_DEV_STATUS", "path": SINGULAR_DEV, "kind": KIND, "classification": FLAG,
         "lane_task_id": TASK, "evidence_ref_count": 2, "deviated_ac_ids": ["AC19"]},
        {"code": "UNRESOLVED_BLOCKERS", "path": SINGULAR_DEV, "kind": KIND, "classification": FLAG,
         "lane_task_id": TASK, "evidence_ref_count": 2, "deviated_ac_ids": ["AC19"]},
    ]
    row = stage2(tmp_path, canned_result("pass_with_exceptions", disclosed=entries))
    assert row["state"] == "close_pending"
    assert row["next_action"] == "close"
    assert row["invoke_resolver"] is True
    assert row["resolver_status"] == "pass_with_exceptions"
    assert row["disclosed_exceptions"] == [
        {"code": "INVALID_DEV_STATUS", "path": SINGULAR_DEV, "kind": KIND, "classification": FLAG},
        {"code": "UNRESOLVED_BLOCKERS", "path": SINGULAR_DEV, "kind": KIND, "classification": FLAG},
    ]
    assert "blocker" not in row
    assert row["state"] != "blocked"


def test_c9_a_failing_chain_is_blocked_with_the_real_errors__pin(tmp_path):
    errors = [
        {"code": "INVALID_QA_STATUS", "path": "docs/dev/qa-report-x.json", "detail": "d1"},
        {"code": "MISSING_ARTIFACT", "path": "docs/dev/ticket-x.md", "detail": "d2"},
    ]
    row = stage2(tmp_path, canned_result("fail", errors=errors))
    assert row["state"] == "blocked"
    assert row["next_action"] == "inspect"
    assert row["blocker"] == "RESOLVER_FAIL"
    assert row["resolver_errors"] == errors


def test_c9_an_unmapped_status_never_gives_an_empty_reason__change(tmp_path):
    row = stage2(tmp_path, canned_result("pass", mode="fanout"))
    assert row["state"] == "blocked"
    assert row["blocker"] == "RESOLVER_FAIL"
    assert [e["code"] for e in row["resolver_errors"]] == ["RESOLVER_STATUS_UNMAPPED"]
    assert "pass" in row["resolver_errors"][0]["detail"]
    assert "fanout" in row["resolver_errors"][0]["detail"]
    assert row["resolver_errors"] != []


def test_c9_a_foreign_schema_version_is_a_contract_mismatch__pin(tmp_path):
    row = stage2(tmp_path, canned_result("pass", schema_version=3))
    assert row["state"] == "blocked"
    assert row["next_action"] == "inspect"
    assert row["blocker"] == "RESOLVER_CONTRACT_MISMATCH"


# ==========================================================================
# class 10: the real lifecycle over singular and fan-out chains
# ==========================================================================


def derive(root):
    return lifecycle().derive_state(root, TASK)


def shape(row):
    return (row["state"], row["next_action"], row["invoke_resolver"])


def test_c10_a_released_singular_chain_is_close_pending__change(tmp_path):
    row = derive(build_singular(tmp_path, with_deviation()))
    assert shape(row) == ("close_pending", "close", True)
    assert row["resolver_status"] == "pass_with_exceptions"
    assert len(row["disclosed_exceptions"]) == 2
    assert sorted(e["code"] for e in row["disclosed_exceptions"]) == [
        "INVALID_DEV_STATUS",
        "UNRESOLVED_BLOCKERS",
    ]


def test_c10_a_released_chain_is_listed_by_scan_and_list_actionable__change(tmp_path):
    root = build_singular(tmp_path, with_deviation())
    rows = lifecycle().scan(root)
    mine = [r for r in rows if r["task_id"] == TASK]
    assert [r["next_action"] for r in mine] == ["close"]
    assert lifecycle().actionable_parents(rows, "close") == [TASK]
    done = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "dev-lifecycle.py"), "list-actionable",
         "--next-action", "close", "--project-dir", str(root)],
        capture_output=True, text=True, cwd=str(root), timeout=120,
    )
    assert done.returncode == 0
    assert done.stdout.split() == [TASK]


def test_c10_a_plain_blocked_report_is_still_developing__pin(tmp_path):
    row = derive(build_singular(tmp_path, without_flag))
    assert shape(row) == ("developing", "wait", False)


def test_c10_a_malformed_record_is_still_developing__pin(tmp_path):
    def malformed(report):
        with_deviation()(report)
        report[BLOCK][K_IDS] = []

    row = derive(build_singular(tmp_path, malformed))
    assert shape(row) == ("developing", "wait", False)


def test_c10_a_released_chain_with_a_failing_parent_qa_is_qa_failed__change(tmp_path):
    row = derive(build_singular(tmp_path, with_deviation(), qa_status="fail"))
    assert row["state"] == "qa_failed"
    assert row["next_action"] == "resume_dev"
    assert row["invoke_resolver"] is False


def test_c10_a_released_chain_with_a_missing_reference_is_blocked_with_real_errors__change(tmp_path):
    root = build_singular(tmp_path, with_deviation(), omit_ref="docs/dev/qa-report-%s.json" % TASK)
    row = derive(root)
    expected = resolve(root)["errors"]
    assert row["state"] == "blocked"
    assert row["next_action"] == "inspect"
    assert row["blocker"] == "RESOLVER_FAIL"
    assert row["resolver_errors"] == expected
    assert row["resolver_errors"] != []


def test_c10_a_released_fanout_canonical_is_close_pending_and_previews_complete__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation())
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    row = derive(root)
    assert shape(row) == ("close_pending", "close", False)
    assert row["roster_preview"] is True
    assert [lane["task_id"] for lane in row["lanes"]] == [TASK + "-lane-a", TASK + "-lane-b"]
    preview = lifecycle().roster_preview(
        root / "docs" / "dev", TASK, aggregator(), deviation=resolver().ac_deviation_provider()
    )
    assert preview["complete"] is True
    assert preview["lane_labels"] == ["lane-a", "lane-b"]


def test_c10_a_released_fanout_with_a_failing_lane_qa_is_roster_incomplete__change(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation(), qa={"lane-b": "fail"})
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    row = derive(root)
    assert row["state"] == "blocked"
    assert row["next_action"] == "inspect"
    assert row["blocker"].split(":", 1)[0] == "ROSTER_INCOMPLETE"
    assert row["blocker"] == "ROSTER_INCOMPLETE:lane 'lane-b' qa-report missing or qa.status != pass"


def test_c10_a_failure_canonical_of_a_blocked_lane_is_still_developing__pin(tmp_path):
    root = build_fanout(tmp_path, lane_a=without_flag)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 1
    assert shape(derive(root)) == ("developing", "wait", False)


def test_c10_an_ordinary_fanout_chain_is_close_pending__pin(tmp_path):
    root = build_fanout(tmp_path)
    rc, payload, stderr = run_aggregator(root)
    assert rc == 0
    row = derive(root)
    assert shape(row) == ("close_pending", "close", False)
    assert row["roster_preview"] is True
    rows = lifecycle().scan(root)
    lane_rows = [r for r in rows if r["task_id"] in (TASK + "-lane-a", TASK + "-lane-b")]
    assert sorted(r["kind"] for r in lane_rows) == ["lane", "lane"]
    assert sorted(r["next_action"] for r in lane_rows) == ["none", "none"]


def test_c10_the_preview_without_a_provider_keeps_the_baseline_answer__pin(tmp_path):
    root = build_fanout(tmp_path, lane_a=with_deviation())
    preview = lifecycle().roster_preview(root / "docs" / "dev", TASK, aggregator())
    assert preview["complete"] is False
    assert BLOCKED_LINE in preview["reason"]
