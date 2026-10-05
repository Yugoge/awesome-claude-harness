"""The `parent_cycle` claimant reader in scripts/aggregate-dev-report.py.

THE DEFECT.  Admission to a cycle's ownership-completeness claimant set was
decidable solely from a report's FILENAME.  A tool-owner round does cycle-level
work and is legitimately NOT a lane, so it had two outcomes and no third: a
report named inside `dev-report-<task-id>-*` is admitted but fail-closes to its
filename label and manufactures a PHANTOM LANE, while a report named outside it
never reaches any claimant enumeration at all.  Compliance itself therefore
produced unattributable bytes.

THE FIX IS A READER, NOT A FIELD.  Those rounds already declare
`parent_cycle: <cycle>` in their own reports and the repository's ledger
contract checker already accepts them; nothing read the field.  So no producer
changes: `_cycle_claimant_index` reads what is already declared, and
`_evidenced_claimant_candidates` admits a declaration only when it is
evidenced.

THE GAP CLASS THIS CLOSES, which nothing else can.  `_follow_declared_claim
_chain` already recognises cross-cycle boundaries, but it walks FORWARD from a
lane's replay output, so it structurally cannot account for a claimant that
edited the path BEFORE the lane did.  Every scenario below is built in that
shape, which is why a revert of the reader turns them red.

WHAT MUST NOT MOVE.  The lane roster stays filename-keyed: a report that
declares `parent_cycle` AND is filename-admissible as a worker is refused by
the reader and still counted as a lane.  And widening only ever turns FAIL into
PASS -- genuinely unattributed bytes still fail, under their own resolver error
code.

Everything runs against a REAL git repository under tmp_path and the REAL
`_apply_completeness_check` / `resolve_chain`; the subject's bytes are produced
by actually editing a tracked file, and nothing is mocked.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGG_PATH = REPO_ROOT / "scripts" / "aggregate-dev-report.py"
RESOLVER_PATH = REPO_ROOT / "scripts" / "resolve-dev-artifact-chain.py"

GAP_CODE = "OWNERSHIP_COMPLETENESS_GAP"

_SUBJECT = "subject.md"
_TASK_ID = "20260101-000000"
_WORKERS = ("r01", "r02")
_CLAIMANT_TID = "20260202-toolowner"

# B -> X is the CLAIMANT's edit; X -> Y is the LANE's.  The claimant therefore
# edited the path BEFORE the lane, which is the shape the forward-only
# cross-cycle chain cannot reach back past.
_B = "alpha\nbeta\ngamma\n"
_X = "alpha\nbeta-CLAIMANT\ngamma\n"
_Y = "alpha\nbeta-CLAIMANT\ngamma-LANE\n"
_CLAIMANT_HUNKS = [{"old": "beta\n", "new": "beta-CLAIMANT\n"}]
_LANE_HUNKS = [{"old": "gamma\n", "new": "gamma-LANE\n"}]
# Bytes no ledger in the scenario accounts for -- the positive control.
_UNATTRIBUTED = "delta-NOBODY\n"

# The already-dirty-baseline shape `_resolve_baseline_snapshot` documents: the
# path carried an uncommitted change from a prior session BEFORE this cycle
# began, so HEAD names the last clean commit and is NOT a valid stand-in for
# "this file's content when editing began".  Both declarants' starting point is
# therefore B_DIRTY, which no commit holds.
_B_DIRTY = "alpha\nbeta\ngamma\nextra\n"
_Y_DIRTY = "alpha\nbeta-CLAIMANT\ngamma-LANE\nextra\n"


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AGG = load_module(AGG_PATH, "_parent_cycle_reader_aggregator")
RESOLVER = load_module(RESOLVER_PATH, "_parent_cycle_reader_resolver")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(value, str):
        value = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(value, encoding="utf-8")


def build_scenario(
    root: Path,
    *,
    claimant: str | None = "blob",
    claimant_parent_cycle: str | None = _TASK_ID,
    claimant_hunks: list | None = None,
    claimant_name: str | None = None,
    unattributed: bool = False,
    dirty_baseline: bool = False,
) -> dict:
    """A real git repo, a complete fan-out chain, and one non-lane claimant.

    `claimant` selects how the claimant declares its own starting point:
      "blob"      -- the 40-hex git blob SHA of B (independently verifiable);
      "unresolvable" -- declared as JSON null: no starting point at all;
      None        -- no claimant report is written at all.

    `dirty_baseline` switches both declarants' starting point to `_B_DIRTY`,
    declared as LITERAL text and held by NO commit.  Resolved against the
    cycle's baseline_head_sha, `_resolve_baseline_snapshot` prefers HEAD and
    hands back `_B` instead -- so in this shape the claimant's declared start
    is the ONLY viable start for the whole candidate set, and whether the
    evidence gate resolves it against the claimant's own declared object
    decides the outcome.  That is the precise defect the gate exists for.
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / _SUBJECT).write_text(_B, encoding="utf-8")
    _git(root, "add", _SUBJECT)
    _git(root, "commit", "-q", "-m", "seed subject")
    head = _git(root, "rev-parse", "HEAD")
    blob_b = _git(root, "rev-parse", f"HEAD:{_SUBJECT}")
    lane_start = _B_DIRTY if dirty_baseline else _B
    live = (_Y_DIRTY if dirty_baseline else _Y) + (
        _UNATTRIBUTED if unattributed else ""
    )
    (root / _SUBJECT).write_text(live, encoding="utf-8")

    dev_dir = root / "docs" / "dev"
    for index, worker in enumerate(_WORKERS):
        identity = f"{_TASK_ID}-{worker}"
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
            # Only the first lane declares the subject, so the merged union is
            # exactly one lane's declaration: an unaccounted remainder is then
            # unambiguously unaccounted.  Its declared starting point is B --
            # a first-shard-wins value that is correct for the repo baseline
            # and wrong for this lane's own edit, which is precisely why a
            # claimant must be able to supply the B -> X step.
            "owned_edits": {_SUBJECT: list(_LANE_HUNKS)} if index == 0 else {},
            "pre_edit_snapshots": {_SUBJECT: lane_start} if index == 0 else {},
        }
        _write(dev_dir / f"ticket-{identity}.md", f"# Ticket\n\n**TASK-ID**: `{identity}`\n")
        _write(dev_dir / f"context-{identity}.json",
               {"request_id": identity, "task_id": identity})
        _write(dev_dir / f"dev-report-{identity}.json", lane)
        _write(dev_dir / f"qa-report-{identity}.json",
               {"request_id": identity, "task_id": identity, "qa": {"status": "pass"}})

    if claimant is not None:
        snapshot = {"blob": _B_DIRTY if dirty_baseline else blob_b,
                    "unresolvable": None}[claimant]
        report = {
            "request_id": _CLAIMANT_TID,
            "task_id": _CLAIMANT_TID,
            "report_version": 2,
            "baseline_head_sha": head,
            "baseline_dirty_snapshot": "",
            "dev": {"status": "completed", "files_modified": [_SUBJECT],
                    "files_created": [], "observed_preexisting": []},
            "blocking_issues": [],
            "recommendations": [],
            "owned_edits": {
                _SUBJECT: list(
                    claimant_hunks if claimant_hunks is not None else _CLAIMANT_HUNKS
                )
            },
            "pre_edit_snapshots": {_SUBJECT: snapshot},
        }
        if claimant_parent_cycle is not None:
            report["parent_cycle"] = claimant_parent_cycle
        _write(dev_dir / (claimant_name or f"dev-report-{_CLAIMANT_TID}.json"), report)

    references = [
        f"docs/dev/ticket-{_TASK_ID}.md",
        f"docs/dev/context-{_TASK_ID}.json",
        f"docs/dev/dev-report-{_TASK_ID}.json",
        f"docs/dev/qa-report-{_TASK_ID}.json",
    ]
    _write(dev_dir / f"ticket-{_TASK_ID}.md", f"# Ticket\n\n**TASK-ID**: `{_TASK_ID}`\n")
    _write(dev_dir / f"context-{_TASK_ID}.json",
           {"request_id": _TASK_ID, "task_id": _TASK_ID})
    _write(dev_dir / f"qa-report-{_TASK_ID}.json",
           {"request_id": _TASK_ID, "task_id": _TASK_ID, "qa": {"status": "pass"}})
    _write(dev_dir / f"completion-{_TASK_ID}.md",
           f"# Completion\n\n**Request ID**: `{_TASK_ID}`\n"
           + "".join(f"- `{reference}`\n" for reference in references))
    return {"head": head, "blob_b": blob_b, "live": live}


def measure(root: Path, agg_mod: ModuleType) -> dict:
    """Lane-only vs widened completeness, through the REAL production path."""
    dev_dir = root / "docs" / "dev"
    bare = agg_mod._bare_task_id(_TASK_ID)
    loaded, _ = agg_mod._load_all_shards(agg_mod._scan_shards(dev_dir, bare, _TASK_ID))
    aggregate = agg_mod._build_aggregate(loaded, _TASK_ID)
    expanded = agg_mod._expand_shards_with_superseded_rounds(loaded, dev_dir, bare)
    lane_only = agg_mod._lane_candidates_for_file(expanded, _SUBJECT)
    claimants = agg_mod._cycle_claimant_index(dev_dir, bare, _TASK_ID)
    lane_only_ok, lane_only_diagnostic = agg_mod._completeness_check_file(
        root, aggregate["baseline_head_sha"], _SUBJECT,
        aggregate["owned_edits"][_SUBJECT],
        (aggregate.get("pre_edit_snapshots") or {}).get(_SUBJECT),
        lane_candidates=lane_only, dev_dir=dev_dir, own_bare_tid=bare,
    )
    return {
        "aggregate": aggregate,
        "lane_labels": [name for name, _, _ in lane_only],
        "claimant_paths": sorted(claimants),
        "claimant_sources": [source for source, _, _ in claimants.get(_SUBJECT, ())],
        "admitted": agg_mod._evidenced_claimant_candidates(
            root, _SUBJECT, claimants.get(_SUBJECT, [])
        ),
        "lane_only_ok": lane_only_ok,
        "lane_only_diagnostic": lane_only_diagnostic,
        # The production entry point -- it performs the two-phase widening.
        "gaps": agg_mod._apply_completeness_check(aggregate, root, loaded),
    }


@pytest.fixture(autouse=True)
def _clear_caches():
    for cache in (AGG._FOREIGN_CLAIM_INDEX_CACHE, AGG._CYCLE_CLAIMANT_INDEX_CACHE):
        cache.clear()
    yield
    for cache in (AGG._FOREIGN_CLAIM_INDEX_CACHE, AGG._CYCLE_CLAIMANT_INDEX_CACHE):
        cache.clear()


def assert_reader_invariant(observation: dict) -> None:
    """The clauses the reader must satisfy, bundled so a revert turns them red.

    R1 the claimant is REACHABLE by the claimant enumeration;
    R2 it is NOT a lane -- the roster is untouched and its label is namespaced;
    R3 the lane-only check genuinely fails, so the scenario is not vacuous;
    R4 widening closes it, so the claimant's bytes are actually claimed.
    """
    assert observation["claimant_sources"] == [_CLAIMANT_TID]          # R1
    assert observation["aggregate"]["parallel_workers"] == list(_WORKERS)  # R2
    assert observation["lane_labels"] == ["r01"]                        # R2
    assert [name for name, _, _ in observation["admitted"]] == [
        AGG._CLAIMANT_LABEL_PREFIX + _CLAIMANT_TID
    ]                                                                  # R2
    assert observation["lane_only_ok"] is False                        # R3
    assert observation["gaps"] == []                                   # R4


def test_a_non_lane_claimant_is_reachable_without_being_a_lane(tmp_path):
    """The whole invariant, on a blob-SHA-declared claimant."""
    root = tmp_path / "blob"
    build_scenario(root)
    assert_reader_invariant(measure(root, AGG))


def test_the_claimants_own_declared_start_is_not_replaced_by_head(tmp_path):
    """The evidence gate's first half, in the shape that found the defect.

    Both declarants' real starting point is `_B_DIRTY`, which no commit holds,
    and it is declared as literal text.  Resolved against the cycle's
    baseline_head_sha, `_resolve_baseline_snapshot` prefers HEAD and hands back
    `_B` -- so in this shape the claimant's own declared start is the ONLY
    viable start for the entire candidate set, and substituting HEAD's bytes
    verifies a start nobody declared.  This test fails if the gate resolves the
    claimant's snapshot against anything but the claimant's own declaration.
    """
    root = tmp_path / "dirty-baseline"
    built = build_scenario(root, claimant="blob", dirty_baseline=True)
    observation = measure(root, AGG)
    admitted = observation["admitted"]
    assert len(admitted) == 1
    assert admitted[0][1] == _B_DIRTY.encode("utf-8"), "claimant's start must survive"
    assert admitted[0][1] != _B.encode("utf-8"), "HEAD's bytes must not be substituted"
    # Not merely resolved: HEAD-first resolution of this very declaration does
    # return _B, which is what an unguarded admission would have carried.
    head_substituted, source = AGG._resolve_baseline_snapshot(
        root, built["head"], _SUBJECT, _B_DIRTY
    )
    assert (head_substituted, source) == (_B.encode("utf-8"), "baseline_head_sha")
    # And the lane-only check does fail here, so the pass below is the gate's.
    assert observation["lane_only_ok"] is False
    assert observation["gaps"] == []


def test_a_claimant_with_no_declared_start_is_never_admitted(tmp_path):
    """The evidence gate's first half, fail-closed.

    A ledger with no resolvable starting point is not a claim, so it cannot
    suppress the gap -- and the gap keeps its lane-anchored diagnostic.
    """
    root = tmp_path / "unresolvable"
    build_scenario(root, claimant="unresolvable")
    observation = measure(root, AGG)
    assert observation["claimant_sources"] == [_CLAIMANT_TID]
    assert observation["admitted"] == []
    assert observation["gaps"], "an unevidenced declaration must not clear a real gap"


def test_a_claimant_whose_ledger_cannot_replay_is_never_admitted(tmp_path):
    """The evidence gate's second half, fail-closed.

    The declared anchor is absent from the declared starting point, so the
    replay primitive refuses it.  A ledger that cannot replay from its own
    declared start is not a claim.
    """
    root = tmp_path / "unreplayable"
    build_scenario(root, claimant="blob",
                   claimant_hunks=[{"old": "no-such-anchor\n", "new": "whatever\n"}])
    observation = measure(root, AGG)
    assert observation["claimant_sources"] == [_CLAIMANT_TID]
    assert observation["admitted"] == []
    assert observation["gaps"]


def test_unattributed_bytes_still_fail_under_their_own_error_code(tmp_path, monkeypatch):
    """Positive control: no gap class becomes unreachable.

    Identical to the passing scenario except that the live file carries bytes
    NO ledger declares.  The fully-evidenced claimant is admitted, its own
    edit is claimed, and the gate still fails -- through the real producer and
    the real resolver, under OWNERSHIP_COMPLETENESS_GAP.
    """
    root = tmp_path / "unattributed"
    build_scenario(root, unattributed=True)
    observation = measure(root, AGG)
    assert [name for name, _, _ in observation["admitted"]] == [
        AGG._CLAIMANT_LABEL_PREFIX + _CLAIMANT_TID
    ], "precondition: the claimant must be admitted, so the failure is the bytes"
    assert observation["gaps"], "unattributed bytes must still be reported"

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    assert AGG.main(["--task-id", _TASK_ID]) == 1
    resolved = RESOLVER.resolve_chain(root, _TASK_ID)
    codes = [error["code"] for error in resolved.get("errors") or []]
    assert GAP_CODE in codes
    assert resolved["status"] != "pass"


def test_a_parent_cycle_declaration_cannot_create_or_merge_a_lane(tmp_path):
    """The lane roster is filename-keyed and stays that way.

    The claimant is renamed into this cycle's worker namespace while still
    declaring `parent_cycle`.  It is then filename-admissible as a worker, so
    the reader must REFUSE it -- membership in the claimant set and membership
    in the lane set are decided by different questions, and the second one did
    not change.
    """
    root = tmp_path / "lane-named"
    lane_shaped = f"dev-report-{_TASK_ID}-r09.json"
    build_scenario(root, claimant="blob", claimant_name=lane_shaped)
    is_worker, label = AGG._is_worker_for_task(
        lane_shaped, AGG._bare_task_id(_TASK_ID), _TASK_ID
    )
    assert (is_worker, label) == (True, "r09"), "precondition: filename IS lane-shaped"
    claimants = AGG._cycle_claimant_index(
        root / "docs" / "dev", AGG._bare_task_id(_TASK_ID), _TASK_ID
    )
    assert _SUBJECT not in claimants, "a lane-shaped name must never be a claimant"

    # And a report that declares no parent_cycle at all is equally not a claimant,
    # so the reader is keyed on the declaration rather than on being non-lane.
    root_b = tmp_path / "no-declaration"
    build_scenario(root_b, claimant="blob", claimant_parent_cycle=None)
    assert _SUBJECT not in AGG._cycle_claimant_index(
        root_b / "docs" / "dev", AGG._bare_task_id(_TASK_ID), _TASK_ID
    )


def test_reverting_the_reader_turns_the_invariant_red(tmp_path):
    """Coverage that fails if the reader is removed.

    The revert is applied to a byte-identical COPY of the production script
    rather than in place: this repository's work tree is shared with concurrent
    sessions that have already clobbered one round's edits to this very file, so
    mutating the live bytes even briefly is the hazard rather than the evidence.
    The copy is asserted to differ from the original by exactly the reverted
    call, and the SAME `assert_reader_invariant` bundle is then run against it.
    """
    reverted_path = tmp_path / "aggregate-dev-report-reverted.py"
    shutil.copyfile(AGG_PATH, reverted_path)
    source = reverted_path.read_text(encoding="utf-8")
    original_call = (
        "            widened = _lane_candidates_for_file(\n"
        "                expanded_shards or [], rel,\n"
        "                cycle_claimants=claimants[rel], project_root=project_root,\n"
        "            )\n"
    )
    assert source.count(original_call) == 1, "the reader's call site must be locatable"
    reverted_path.write_text(
        source.replace(original_call, "            widened = lane_candidates or []\n"),
        encoding="utf-8",
    )
    reverted = load_module(reverted_path, "_parent_cycle_reader_reverted")
    reverted._FOREIGN_CLAIM_INDEX_CACHE.clear()
    reverted._CYCLE_CLAIMANT_INDEX_CACHE.clear()

    root = tmp_path / "revert"
    build_scenario(root)
    # The unmodified module passes this scenario (proved by the first test);
    # the reverted copy must not.
    with pytest.raises(AssertionError):
        assert_reader_invariant(measure(root, reverted))
    reverted_observation = measure(root, reverted)
    assert reverted_observation["gaps"], "reverting the reader must reopen the gap"
