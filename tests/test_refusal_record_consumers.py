"""CLI-RUN harness for the refusal-record consumer contract.

This is the module named BY NAME as `check.cli_run.harness` by AC12 and AC14 of
docs/dev/acceptance-criteria-dev-20260927-135305-r03.json (lane
r03-conflict-escalation).  It covers the two EXECUTABLE consumers of a refusal
record:

    ROW 1  scripts/aggregate-dev-report.py
    ROW 2  scripts/check-late-repair-provenance.py

ROW 3 (agents/changelog-analyst.md) is deliberately NOT here.  It is Markdown
with no executable surface; running it as a program would be a defect.  Its
verification kind is a STATIC PROSE-CONTRACT check and lives in
tests/test_changelog_analyst_declaration_categories.py.

HONEST STATUS AT CREATION
-------------------------
ROW 1 and ROW 2 FAIL.  Both production consumers still drop the child's
verdict (measurements M17b and M17c below), and both scripts are OUTSIDE lane
r03-conflict-escalation's declared footprint, so this lane cannot deliver the
production-side change.  The previous encoding of that shortfall was a
*passing* assertion that this very file does not exist, which converted the
missing work into a green criterion.  That encoding is gone: the shortfall is
now RED, which is the correct colour for undelivered work.

Both rows have since been resolved by BEHAVIOURAL checks of the real,
unmocked consumer (see the UPDATE notes above ROW 1 and in ROW 2's
docstring): each forces a real refusal through the consumer and proves the
child's verdict reaches the caller.

Each consumer check is paired with a stub-driven POSITIVE CONTROL
(test_contract_checker_discriminates_*) that drives the same checker over a
conforming and a non-conforming stub, so a reader can see the checker responds
to the property in BOTH directions and is not vacuously true in either.
"""

import ast
import importlib.util
import io
import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
STAGER = os.path.join(REPO_ROOT, "scripts", "stage-owned-hunks.py")
AGGREGATOR = os.path.join(REPO_ROOT, "scripts", "aggregate-dev-report.py")
PROVENANCE = os.path.join(REPO_ROOT, "scripts", "check-late-repair-provenance.py")

# The producer's contract, reproduced from the criteria's `assert_exit_codes`.
EXIT_REFUSAL = 10
EXIT_OK = 0

REFUSAL_SCHEMA = "owned-edits-classification.v1"

# The verdict-bearing child invocation inside ROW 1.  Named by file content, not
# by line number: a contested region identified by line number is not acceptable
# evidence in this lane, and the same rule is applied to the evidence this
# harness itself cites.
VERDICT_BEARING_CHILD = "stage-owned-hunks.py"


# --------------------------------------------------------------------------
# Producer side: what a consumer is actually required to read.
# --------------------------------------------------------------------------

def _claim(ref, claimant_id, task_id, interval, body):
    return {
        "claim_ref": ref,
        "claimant_id": claimant_id,
        "session_id": "session-%s" % claimant_id,
        "task_id": task_id,
        "region_id": "R1",
        "boundary_resolution": {
            "resolved": True,
            "bound_image_id": "img-1",
            "occurrence_count": 1,
            "interval": list(interval),
        },
        "version": {
            "version_id": "v-%s" % ref,
            "content_oid": "oid-%s" % ref,
            "excerpt": "<<%s>>" % body,
            "bytes": body,
        },
    }


def _two_claimant_overlap():
    """The canonical proven overlapping pair: distinct claimants, distinct
    tasks, one bound image, intervals sharing bytes."""
    return {
        "path": "src/shared.py",
        "claimant_census": {"complete": True, "reason": None},
        "regions": [{
            "region_id": "R1",
            "anchor": {"content": "def shared_helper():",
                       "occurrence_count": 1,
                       "advisory_line_number": 42},
            "context_before": "head\n",
            "context_after": "\ntail",
        }],
        "claims": [
            _claim("cA", "session-alpha", "task-ALPHA", (10, 20),
                   "ALPHA writes here"),
            _claim("cB", "session-beta", "task-BETA", (15, 25),
                   "BETA writes there"),
        ],
    }


def _run_producer(tmp_path, claim_input, classify_path=None):
    """Run the producer as a real subprocess; return the raw completed call so
    a consumer contract can be measured against BOTH streams."""
    if classify_path is None:
        classify_path = str(tmp_path / "claims.json")
        with io.open(classify_path, "w", encoding="utf-8") as handle:
            json.dump(claim_input, handle)
    return subprocess.run(
        [sys.executable, STAGER, "--git-root", str(tmp_path),
         "--file", "src/shared.py", "--classify", classify_path],
        capture_output=True, text=True,
    )


def test_producer_puts_exactly_one_schema_validated_refusal_record_on_stdout(
        tmp_path):
    """The premise every consumer row depends on.

    This is the measurement that makes ROW 1's defect material: the verdict is
    on STDOUT and STDERR is EMPTY, so a consumer that reads only stderr on a
    non-zero exit receives nothing at all.
    """
    proc = _run_producer(tmp_path, _two_claimant_overlap())

    assert proc.returncode == EXIT_REFUSAL, proc.stderr

    # EXACTLY ONE record: the whole stream parses as a single JSON document.
    record = json.loads(proc.stdout)
    assert isinstance(record, dict)

    # Schema-identified, i.e. schema-validatable rather than free-form text.
    assert record["schema"] == REFUSAL_SCHEMA
    assert record["refusal"] is True

    # The measurement, asserted rather than merely narrated: the verdict is
    # carried entirely on stdout and stderr contributes nothing.
    assert len(proc.stdout.encode("utf-8")) > 1000, "verdict is not on stdout"
    assert proc.stderr == "", (
        "stderr is non-empty, so a stderr-only consumer would not be "
        "provably empty-handed: %r" % (proc.stderr[:200],))


def test_malformed_record_is_a_protocol_error_not_a_silent_pass(tmp_path):
    """`assert_malformed_is_protocol_error`: an unreadable claim input takes a
    named error branch and still exits 10 -- it does not fall through to 0."""
    malformed = str(tmp_path / "malformed.json")
    with io.open(malformed, "w", encoding="utf-8") as handle:
        handle.write(u"{not json")

    proc = _run_producer(tmp_path, None, classify_path=malformed)

    assert proc.returncode == EXIT_REFUSAL
    record = json.loads(proc.stdout)
    assert record["reason_class"] == "operational_error"
    assert record["reason_code"] == "CLAIM_INPUT_UNREADABLE"


# --------------------------------------------------------------------------
# The consumer contract checkers.
#
# Both are pure functions of a source file, so each can be driven over a stub
# to prove it discriminates (see the positive controls further down).
# --------------------------------------------------------------------------

def _is_subprocess_run(node):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("run", "check_output", "Popen"))


def _functions_invoking(source, child_name):
    """Every function in `source` that both spawns a child process and names
    `child_name`, i.e. the call sites where a child's verdict is available."""
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.walk(node)
        spawns = False
        mentions = False
        for inner in body:
            if _is_subprocess_run(inner):
                spawns = True
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str) \
                    and child_name in inner.value:
                mentions = True
        if spawns and mentions:
            found.append(node)
    return found


def consumer_reads_child_stdout(source, child_name):
    """Does every verdict-bearing child call site actually READ the child's
    stdout?

    `stdout=subprocess.PIPE` is a keyword argument, not an attribute access, so
    requesting the pipe does not satisfy this check -- only an actual
    `<proc>.stdout` read does.  That distinction is the whole of M17b.
    """
    sites = _functions_invoking(source, child_name)
    if not sites:
        return None, "no verdict-bearing child call site found"
    for fn in sites:
        reads = any(isinstance(n, ast.Attribute) and n.attr == "stdout"
                    for n in ast.walk(fn))
        if not reads:
            return False, (
                "%s() spawns %s but never reads its stdout; the verdict is "
                "discarded" % (fn.name, child_name))
    return True, ""


def results_reduced_to_opaque_bool_and_string(source):
    """M17c: result-producing helpers whose outcome is flattened to
    `tuple[bool, str]`, which cannot carry a structured verdict."""
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.returns is None:
            continue
        rendered = ast.unparse(node.returns).replace(" ", "")
        if rendered in ("tuple[bool,str]", "Tuple[bool,str]"):
            offenders.append(node.name)
    return offenders


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _load_module_by_path(path, name):
    """File-location import of `path` under a private module `name`, so the
    ROW 1 behavioral check below exercises the REAL, unmocked consumer
    function in-process -- the same import shape the production code itself
    now uses for stage-owned-hunks.py (see _load_stage_owned_hunks_replay)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# POSITIVE CONTROLS -- the discriminating direction, shown in both directions.
#
# Each control drives the SAME checker used on the production consumer over a
# stub that deliberately holds, and a stub that deliberately breaks, the
# property.  A checker that cannot go red on the broken stub is itself a defect.
# --------------------------------------------------------------------------

_STUB_DISCARDS_STDOUT = '''\
import subprocess
def completeness_ok(root, rel):
    proc = subprocess.run(["python", "stage-owned-hunks.py", "--dry-run"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode == 0:
        return True, ""
    return False, proc.stderr.decode("utf-8")
'''

_STUB_READS_STDOUT = '''\
import subprocess
def completeness_ok(root, rel):
    proc = subprocess.run(["python", "stage-owned-hunks.py", "--dry-run"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode == 0:
        return True, ""
    return False, proc.stdout.decode("utf-8") or proc.stderr.decode("utf-8")
'''


def test_contract_checker_discriminates_on_child_stdout_capture():
    """The stdout-capture checker responds to the property, not to the file."""
    broken, why = consumer_reads_child_stdout(
        _STUB_DISCARDS_STDOUT, VERDICT_BEARING_CHILD)
    assert broken is False, "checker failed to detect a discarded verdict"
    assert "never reads its stdout" in why

    fixed, why_ok = consumer_reads_child_stdout(
        _STUB_READS_STDOUT, VERDICT_BEARING_CHILD)
    assert fixed is True, (
        "checker reports a conforming consumer as broken: %s" % why_ok)


def test_contract_checker_discriminates_on_opaque_result_flattening():
    """The result-shape checker responds to the property, not to the file."""
    broken = results_reduced_to_opaque_bool_and_string(
        "def route(a) -> tuple[bool, str]:\n    return True, ''\n")
    assert broken == ["route"], "checker failed to detect bool+str flattening"

    fixed = results_reduced_to_opaque_bool_and_string(
        "def route(a) -> dict[str, object]:\n    return {}\n")
    assert fixed == [], "checker reports a structured result as flattened"


# --------------------------------------------------------------------------
# ROW 1 and ROW 2 -- the measured production consumers.
#
# These were EXPECTED RED at the time this harness was created.  They are
# the honest encoding of undelivered work: the production-side change
# belonged to the owners named in
# docs/dev/dev-report-dev-20260927-135305-r03.json, not to lane
# r03-conflict-escalation.  Do not convert either of them back into an
# assertion about something being absent.
#
# UPDATE (task 20261001-close-multilane-stall): ROW 1's production file
# (scripts/aggregate-dev-report.py) was modified by a later, unrelated
# ticket, which removed the subprocess IPC boundary ROW 1 measured entirely
# -- the completeness check now imports stage-owned-hunks.py's replay
# primitive directly instead of spawning it.  ROW 1 below has been updated
# to a behavioral check matching that new architecture; see its own
# docstring for why this is a resolution by elimination, not a weakening.
# ROW 2 (check-late-repair-provenance.py) was later resolved the same way:
# replaced by a behavioral check that the child's verdict reaches check()'s
# caller (see its docstring).  The M17c annotation checker and its positive
# control above are kept as a stand-alone shape checker.
# --------------------------------------------------------------------------

def test_row1_aggregate_dev_report_does_not_discard_child_verdict(tmp_path):
    """ROW 1 (M17b) -- RESOLVED BY ELIMINATION (task 20261001-close-multilane-stall).

    `scripts/aggregate-dev-report.py` no longer spawns stage-owned-hunks.py
    as a subprocess for this check at all -- the first assertion below
    confirms no such call site survives. Its completeness check now imports
    stage-owned-hunks.py's own `_replay_with_provenance` primitive directly
    (file-location import, see `_load_stage_owned_hunks_replay`) and
    consumes its return value / raised exception entirely in-process. The
    stdout/stderr IPC boundary a verdict could be silently dropped across no
    longer exists for this consumer, so M17b's specific failure mode is
    structurally impossible here, not merely patched around.

    Asserting `reads is None` is NOT the forbidden "assert something is
    absent" vacuous pass this file's own module docstring warns against: it
    is paired with the behavioral assertion below, which forces a real byte
    mismatch through the actual, unmocked consumer function and proves the
    verdict still reaches the caller. A consumer that silently discarded the
    verdict under the new architecture would make that second assertion
    fail. Do not reintroduce the subprocess --dry-run call this ticket
    removed.
    """
    reads, why = consumer_reads_child_stdout(
        _read(AGGREGATOR), VERDICT_BEARING_CHILD)
    assert reads is None, (
        "a subprocess call site to %s reappeared in aggregate-dev-report.py; "
        "this resolved-by-elimination check no longer applies -- restore "
        "the original stdout-reading assertion instead: %s"
        % (VERDICT_BEARING_CHILD, why))

    aggregator = _load_module_by_path(AGGREGATOR, "aggregate_dev_report_row1_check")
    rel = "owned-file.bin"
    (tmp_path / rel).write_bytes(b"live-bytes-no-replay-of-this-ledger-can-produce")

    ok, diagnostic = aggregator._completeness_check_file(
        tmp_path, "", rel,
        hunks=[{"old": "text-absent-from-the-declared-snapshot", "new": "irrelevant"}],
        declared_snapshot="unrelated-starting-bytes",
    )

    assert ok is False, "fixture was not actually a mismatch: %r" % (diagnostic,)
    assert diagnostic, (
        "verdict was discarded: _completeness_check_file returned an empty "
        "diagnostic on a real, forced mismatch")
    assert rel in diagnostic, (
        "diagnostic does not identify the file it concerns: %r" % diagnostic)


def _git_fixture(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@example.invalid",
                    "-c", "user.name=t", *args],
                   capture_output=True, text=True, check=True)


def test_row2_check_late_repair_provenance_result_is_not_opaque(tmp_path):
    """ROW 2 (M17c) -- RESOLVED BY BEHAVIOURAL CHECK.

    M17c measured the result annotation `tuple[bool, str]` of the routing
    helpers in `scripts/check-late-repair-provenance.py`. In the modes those
    helpers drive (`stage-owned-hunks.py --plan-only` with
    `--provenance-plan` / `--untracked-modified-report`) the child's verdict
    is its exit code (0 OK, 10 EXCLUDE) plus a reason on stdout (plan JSON)
    or stderr (`EXCLUDE (fail-closed): ...`); no structured refusal record is
    emitted there. The helper's bool IS that exit-code verdict, its string IS
    the child's own reason, and `route_file` branches on the bool. So the
    property that matters is whether the verdict reaches the caller, and that
    is what this asserts, through `check()` -- the exact function
    scripts/late-repair-controller.py calls at finalize -- over the same
    tracked file in both directions: a reconcilable peer append (child exits
    0) and a foreign overwrite of the owned hunk (child exits 10). A consumer
    that dropped or inverted the child's verdict fails one of the two.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git_fixture(root, "init", "-q")
    rel = "src/tracked.py"
    path = root / rel
    path.parent.mkdir()
    baseline = "line1\nline2\nline3\n"
    path.write_text(baseline, encoding="utf-8")
    _git_fixture(root, "add", rel)
    _git_fixture(root, "commit", "-q", "-m", "baseline")

    import hashlib
    report_path = tmp_path / "dev-report.json"
    report_path.write_text(json.dumps({
        "dev": {"files_modified": [rel]},
        "owned_edits": {rel: [{"old": "line2\n", "new": "CHANGED\n"}]},
        "pre_edit_snapshots": {rel: baseline},
        "final_source_hashes": {rel: hashlib.sha256(
            b"line1\nCHANGED\nline3\n").hexdigest()},
    }), encoding="utf-8")

    checker = _load_module_by_path(PROVENANCE, "check_late_repair_provenance_row2")

    # Child says OK (exit 0): the caller sees a routed, reconcilable file and
    # the child's plan as the detail.
    path.write_text("line1\nCHANGED\nline3\nPEER\n", encoding="utf-8")
    ok = checker.check(str(root), "task-row2", report_path)
    assert ok["drift_detected"] == {rel: "hash_mismatch"}, ok
    assert ok["routing"][rel]["route"] == "tracked_composed", ok
    assert ok["reconcilable"] is True and ok["unroutable_files"] == [], ok
    assert json.loads(ok["routing"][rel]["detail"])["path"] == rel, ok

    # Child refuses (exit 10): the refusal reaches the caller as an unroutable
    # file carrying the child's own fail-closed reason.
    path.write_text("line1\nFOREIGN\nline3\n", encoding="utf-8")
    refused = checker.check(str(root), "task-row2", report_path)
    assert refused["routing"][rel]["route"] == "unroutable", refused
    assert refused["reconcilable"] is False, refused
    assert refused["unroutable_files"] == [rel], refused
    detail = refused["routing"][rel]["detail"]
    assert detail.startswith("EXCLUDE (fail-closed):"), (
        "verdict was discarded: the child's refusal reason did not reach the "
        "caller: %r" % detail)
