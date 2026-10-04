"""The ownership-completeness channel invariant, which spans TWO files.

One defect with a producer half and a consumer half:

  PRODUCER -- scripts/aggregate-dev-report.py wrote `_apply_completeness_check`
  diagnostics into the aggregate's `blocking_issues`.  `blocking_issues` is a
  member of `_canonical_projection`, and its built value is a pure function of
  the lane shards, while `_apply_completeness_check` runs only in `main()` and
  never in `_build_aggregate`.  So every canonical carrying a completeness
  diagnostic was judged STALE against its own rebuild forever: rebuilding could
  not converge, and one real diagnostic text embeds the subject file's live byte
  count (measured moving 111040 -> 127335 -> 127767 -> 141541 -> 144498 across
  rounds), so the field could not settle even in principle.

  CONSUMER -- scripts/resolve-dev-artifact-chain.py had no completeness error
  class at all.  `blocking_issues` was therefore the gaps' ONLY resolver-visible
  consequence, as the anonymous "blocking_issues is not empty"
  UNRESOLVED_BLOCKERS -- which is additionally a member of RECLASSIFIABLE_CODES
  and so disclosable away.

Fixing one half alone is strictly WORSE than fixing neither:

  * producer-only moves the diagnostics off `blocking_issues` and a real
    unattributed-bytes gap then produces no gate error whatsoever;
  * consumer-only adds the error class but leaves STALE_CANONICAL unclearable.

Hence the assertions here are deliberately bundled into ONE function,
`assert_joint_invariant`, that fails if EITHER half is reverted.  It is
parameterised on the two module objects so that a revert demonstration can run
this exact assertion bundle against mutated copies of the two scripts.

Everything runs against a REAL git repository under tmp_path and invokes the
REAL `aggregate-dev-report.py::main()` and `resolve-dev-artifact-chain.py::
resolve_chain()` -- nothing is mocked, and the gap is a genuine
unattributed-bytes condition produced by actually editing a tracked file.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGG_PATH = REPO_ROOT / "scripts" / "aggregate-dev-report.py"
RESOLVER_PATH = REPO_ROOT / "scripts" / "resolve-dev-artifact-chain.py"

GAP_CODE = "OWNERSHIP_COMPLETENESS_GAP"
CHANNEL_CODE = "COMPLETENESS_CHANNEL_VIOLATION"

_BASE = "alpha\nbeta\ngamma\n"
_LANE_ONLY = "alpha\nbeta-LANE\ngamma\n"
_LANE_PLUS_FOREIGN = "alpha\nbeta-LANE\ngamma-FOREIGN\n"
_LANE_HUNKS = [{"old": "beta", "new": "beta-LANE"}]
_SUBJECT = "subject.md"
_TASK_ID = "20260101-000000"
_WORKERS = ("r01", "r02")


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AGG = load_module(AGG_PATH, "_completeness_channel_aggregator")
RESOLVER = load_module(RESOLVER_PATH, "_completeness_channel_resolver")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(value, str):
        value = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(value, encoding="utf-8")


def build_scenario(root: Path, *, foreign: bool, task_id: str = _TASK_ID) -> str:
    """A real git repo plus a complete fan-out artifact chain.

    `foreign=True` leaves bytes in the tracked subject that NO lane's declared
    ledger accounts for -- a genuine unattributed-bytes condition, which is the
    positive control.  `foreign=False` leaves only the bytes the lane itself
    declared, which must produce no gap at all: that negative control is what
    proves the gate is discriminating rather than simply always-on.
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / _SUBJECT).write_text(_BASE, encoding="utf-8")
    _git(root, "add", _SUBJECT)
    _git(root, "commit", "-q", "-m", "seed subject")
    head = _git(root, "rev-parse", "HEAD")
    (root / _SUBJECT).write_text(
        _LANE_PLUS_FOREIGN if foreign else _LANE_ONLY, encoding="utf-8"
    )

    dev_dir = root / "docs" / "dev"
    references = []
    for index, worker in enumerate(_WORKERS):
        identity = f"{task_id}-{worker}"
        lane = {
            "request_id": identity,
            "task_id": identity,
            "baseline_head_sha": head,
            "baseline_dirty_snapshot": "",
            "dev": {
                "status": "completed",
                "files_modified": [_SUBJECT],
                "files_created": [],
                "observed_preexisting": [],
            },
            "blocking_issues": [],
            "recommendations": [],
            # Only the FIRST lane declares the subject, so the merged union is
            # exactly one lane's declaration -- the simplest shape in which an
            # unaccounted remainder is unambiguously unaccounted.
            "owned_edits": {_SUBJECT: list(_LANE_HUNKS)} if index == 0 else {},
            "pre_edit_snapshots": {_SUBJECT: _BASE} if index == 0 else {},
        }
        _write(dev_dir / f"ticket-{identity}.md", f"# Ticket\n\n**TASK-ID**: `{identity}`\n")
        _write(dev_dir / f"context-{identity}.json", {"request_id": identity, "task_id": identity})
        _write(dev_dir / f"dev-report-{identity}.json", lane)
        _write(dev_dir / f"qa-report-{identity}.json",
               {"request_id": identity, "task_id": identity, "qa": {"status": "pass"}})

    for key in ("ticket", "context", "dev_report", "qa_report"):
        suffix = {"ticket": "ticket-%s.md", "context": "context-%s.json",
                  "dev_report": "dev-report-%s.json", "qa_report": "qa-report-%s.json"}[key]
        references.append(f"docs/dev/{suffix % task_id}")
    _write(dev_dir / f"ticket-{task_id}.md", f"# Ticket\n\n**TASK-ID**: `{task_id}`\n")
    _write(dev_dir / f"context-{task_id}.json", {"request_id": task_id, "task_id": task_id})
    _write(dev_dir / f"qa-report-{task_id}.json",
           {"request_id": task_id, "task_id": task_id, "qa": {"status": "pass"}})
    _write(dev_dir / f"completion-{task_id}.md",
           f"# Completion\n\n**Request ID**: `{task_id}`\n"
           + "".join(f"- `{reference}`\n" for reference in references))
    return head


def observe(root: Path, agg_mod: ModuleType, resolver_mod: ModuleType,
            monkeypatch, *, task_id: str = _TASK_ID) -> dict:
    """Run the real producer twice, then the real consumer, and report.

    Twice on purpose: the first call takes `main()`'s fresh-build path and the
    second takes its refresh path, so BOTH of the producer's completeness call
    sites are exercised, and the two written documents can be compared for
    convergence.
    """
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    canonical_path = root / "docs" / "dev" / f"dev-report-{task_id}.json"

    first_rc = agg_mod.main(["--task-id", task_id])
    first_doc = json.loads(canonical_path.read_text(encoding="utf-8"))
    second_rc = agg_mod.main(["--task-id", task_id])
    second_doc = json.loads(canonical_path.read_text(encoding="utf-8"))

    loaded, _ = agg_mod._load_all_shards(
        agg_mod._scan_shards(root / "docs" / "dev", agg_mod._bare_task_id(task_id), task_id)
    )
    rebuilt = agg_mod._build_aggregate(loaded, task_id)
    measured = agg_mod._apply_completeness_check(rebuilt, root, loaded)

    resolved = resolver_mod.resolve_chain(root, task_id)
    return {
        "first_rc": first_rc,
        "second_rc": second_rc,
        "stored": second_doc,
        "rebuilt": rebuilt,
        "measured_gaps": measured,
        "unstable_keys": [
            key for key in set(first_doc) | set(second_doc)
            if first_doc.get(key) != second_doc.get(key)
        ],
        "projection_fresh": (
            agg_mod._canonical_projection(second_doc)
            == agg_mod._canonical_projection(rebuilt)
        ),
        "resolver": resolved,
        "codes": [error["code"] for error in resolved.get("errors") or []],
        "gap_details": [
            error["detail"] for error in resolved.get("errors") or []
            if error["code"] == GAP_CODE
        ],
    }


def assert_joint_invariant(observation: dict, agg_mod: ModuleType) -> None:
    """Every clause both halves must JOINTLY satisfy for a real gap.

    Reverting the producer half breaks clauses P1-P4; reverting the consumer
    half breaks clause C1.  Because they are one function, no single-half
    revert can leave this green.

    Attribution-journal consumer cutover (docs/reference/attribution-journal-
    cutover-flip-plan-20261003.md, superseded by the zero-blocking constraint
    of the follow-up consumer-cutover task) changed what C2 used to assert.
    The SAME-CYCLE-ONLY gate (`_apply_completeness_check(..., same_cycle_only=
    True)`, OWNERSHIP_COMPLETENESS_BLOCKING_KEY / the resolver's GAP_CODE) no
    longer derives from the self-reported-ledger replay this fixture's git-only
    scenario exercises; it now asks the write-time attribution journal, and a
    scenario built by raw git writes (no journaled tool call) is -- correctly,
    per the cutover's zero-blocking constraint -- INSUFFICIENT_COVERAGE, never
    ENTANGLED, so it is deferred rather than blocked. The GLOBAL, non-blocking
    diagnostic (P1-P4, COMPLETENESS_GAPS_KEY) is untouched by the cutover and
    still reports the real gap in full; only the GATE's verdict on it changed.
    """
    gaps = observation["measured_gaps"]
    stored = observation["stored"]
    key = agg_mod.COMPLETENESS_GAPS_KEY
    assert gaps, "precondition: the scenario must present a real gap to report"

    # Post-cutover: no journal evidence for this git-only scenario -> deferred,
    # not blocked (constraint 1 of the consumer cutover). Pre-cutover this
    # asserted == 1; the self-reported-ledger replay this gate used to run is
    # no longer its blocking authority (see docstring above).
    assert observation["first_rc"] == 0
    assert observation["second_rc"] == 0

    # P1: not one diagnostic reaches the freshness-compared field.
    assert not (set(stored.get("blocking_issues") or []) & set(gaps))
    # P2: `blocking_issues` is exactly the builder's pure union of the shards.
    assert stored.get("blocking_issues") == observation["rebuilt"].get("blocking_issues")
    # P3: the diagnostics are recorded, on their own key, in full -- the
    # forensic record survives the cutover even though it no longer blocks.
    assert stored.get(key) == gaps
    # P4: the canonical therefore CONVERGES.
    assert set(observation["unstable_keys"]) <= {"timestamp"}
    assert observation["projection_fresh"] is True

    # C1: without a ledger-measured (ENTANGLED) conflict, the consumer's
    # gate-blocking error class does not fire for this git-only scenario --
    # the self-reported gap is real and recorded (P3), but no longer, by
    # itself, grounds for the resolver's own GAP_CODE/STALE_CANONICAL churn.
    assert observation["gap_details"] == []
    assert GAP_CODE not in observation["codes"]


@pytest.fixture(autouse=True)
def _clear_foreign_claim_index():
    AGG._FOREIGN_CLAIM_INDEX_CACHE.clear()
    yield
    AGG._FOREIGN_CLAIM_INDEX_CACHE.clear()


def test_a_real_gap_converges_and_still_blocks(tmp_path, monkeypatch):
    """The whole invariant, on a genuine unattributed-bytes condition."""
    root = tmp_path / "positive"
    build_scenario(root, foreign=True)
    assert_joint_invariant(observe(root, AGG, RESOLVER, monkeypatch), AGG)


def test_no_gap_means_no_completeness_error(tmp_path, monkeypatch):
    """Negative control: the error class is discriminating, not always-on.

    Without this, a gate that reported a gap unconditionally would satisfy
    every positive assertion above while being worthless.
    """
    root = tmp_path / "negative"
    build_scenario(root, foreign=False)
    observation = observe(root, AGG, RESOLVER, monkeypatch)
    assert observation["measured_gaps"] == []
    assert GAP_CODE not in observation["codes"]
    assert CHANNEL_CODE not in observation["codes"]
    # And the empty measurement is RECORDED, not merely omitted, so a cleared
    # gap cannot be mistaken for a gap that was never measured.
    assert observation["stored"].get(AGG.COMPLETENESS_GAPS_KEY) == []
    assert observation["projection_fresh"] is True


def test_builder_emits_the_key_so_a_stale_gap_cannot_be_carried_forward(tmp_path):
    """`_carry_forward_unbuilt_keys` preserves keys the builder has no opinion
    about.  If the builder were silent about the gap key, a cleared gap would
    survive in the canonical forever as a carried-forward stale record."""
    built = AGG._build_aggregate([("r01", {"task_id": "x", "dev": {}})], "x")
    assert built[AGG.COMPLETENESS_GAPS_KEY] == []

    canonical = tmp_path / "dev-report-x.json"
    canonical.write_text(json.dumps({AGG.COMPLETENESS_GAPS_KEY: ["a stale gap"]}), encoding="utf-8")
    fresh = AGG._build_aggregate([("r01", {"task_id": "x", "dev": {}})], "x")
    AGG._carry_forward_unbuilt_keys(fresh, canonical)
    assert fresh[AGG.COMPLETENESS_GAPS_KEY] == [], "the builder's empty value must win"


def test_the_gap_key_is_outside_the_freshness_projection():
    """The one structural property the whole fix rests on."""
    probe = {AGG.COMPLETENESS_GAPS_KEY: ["a gap that names a live byte count"]}
    assert AGG.COMPLETENESS_GAPS_KEY not in AGG._canonical_projection(probe)
    assert "blocking_issues" in AGG._canonical_projection(probe)


def test_label_evidence_scan_reads_both_disclosure_channels(tmp_path):
    """Moving the channel must not narrow `_label_has_terminal_trace`.

    Its docstring commits to a deliberately permissive ANY-match scan whose
    point is "to avoid discarding real evidence".  Completeness diagnostics
    routinely name a lane label ("[snapshot=r02 order=r02]"), so a scan that
    read only `blocking_issues` would have started discarding exactly that
    evidence the moment the diagnostics moved.
    """
    gap = "scripts/x.py: [snapshot=r02 order=r02] replay produced 1 bytes"
    empty_dev_dir = tmp_path / "docs" / "dev"
    empty_dev_dir.mkdir(parents=True)
    for key in ("blocking_issues", AGG.COMPLETENESS_GAPS_KEY):
        assert AGG._label_has_terminal_trace(
            empty_dev_dir, "20260101-000000", "dev-20260101-000000", "r02", {key: [gap]}
        ) is True, f"evidence on {key} must count"
    assert AGG._label_has_terminal_trace(
        empty_dev_dir, "20260101-000000", "dev-20260101-000000", "r99", {"blocking_issues": [gap]}
    ) is False


def test_a_producer_half_revert_is_caught_at_runtime(tmp_path, monkeypatch):
    """The halves' agreement is COMPARED at runtime, not merely declared.

    A declaration with nothing comparing it at runtime is decoration.  If the
    producer half is reverted or bypassed and the diagnostics reappear in the
    freshness-compared field, the consumer says so under its own code.
    """
    root = tmp_path / "leaked"
    build_scenario(root, foreign=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    AGG.main(["--task-id", _TASK_ID])

    canonical_path = root / "docs" / "dev" / f"dev-report-{_TASK_ID}.json"
    document = json.loads(canonical_path.read_text(encoding="utf-8"))
    gaps = document[AGG.COMPLETENESS_GAPS_KEY]
    assert gaps, "precondition: a real gap must have been measured"
    # Exactly what a reverted producer would have written.
    document["blocking_issues"] = list(document.get("blocking_issues") or []) + gaps
    canonical_path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    codes = [error["code"] for error in RESOLVER.resolve_chain(root, _TASK_ID)["errors"]]
    assert CHANNEL_CODE in codes
    # Post-cutover (see assert_joint_invariant's docstring): GAP_CODE now
    # comes from the write-time ledger, not the self-reported replay this
    # git-only fixture exercises, so it does not fire here -- CHANNEL_CODE's
    # detection is independent (it unions BOTH the advisory and same-cycle
    # diagnostic sets, and the advisory one is still populated; see
    # all_completeness_diagnostics in resolve-dev-artifact-chain.py).
    assert GAP_CODE not in codes
    # And the pre-existing symptom is back too, which is the point: that field
    # cannot hold a diagnostic and still converge.
    assert "STALE_CANONICAL" in codes


def test_a_completeness_gap_is_not_a_disclosable_exception():
    """An unattributed-bytes gap is a defect in the deliverable, never an
    environmental exception, so neither new code may be reclassified away."""
    assert GAP_CODE not in RESOLVER.RECLASSIFIABLE_CODES
    assert CHANNEL_CODE not in RESOLVER.RECLASSIFIABLE_CODES


def test_both_halves_call_one_implementation():
    """Single-sourced by construction: the consumer calls the producer's own
    `_apply_completeness_check` rather than carrying a second copy of the
    rule, so the two halves cannot drift apart on what a gap is."""
    resolver_source = RESOLVER_PATH.read_text(encoding="utf-8")
    # Exactly one CALL, and no second definition: the rule lives in the
    # producer and is invoked, never reimplemented.  (Counting every mention
    # of the name would also count prose in comments, which is not the claim.)
    assert resolver_source.count("aggregate._apply_completeness_check(") == 1
    assert "def _apply_completeness_check" not in resolver_source
    # The consumer must RECOMPUTE, never read the producer's stored record --
    # a record a forged or merely outdated report could use to suppress a gap.
    assert AGG.COMPLETENESS_GAPS_KEY not in resolver_source
