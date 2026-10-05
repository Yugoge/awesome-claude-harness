"""Span-accounting for the ownership-completeness diagnostic: ONE defect, two
halves on one code path.

  HALF A -- STALL-ACCOUNTING.  `_follow_declared_claim_chain` walks declared
  cross-cycle boundaries forward byte-exactly and stops at the first position
  no declaration continues from.  The diagnostic then subtracted that stall
  position from the live size and called the whole remainder "claimed by no
  declaration".  A single mid-chain hole therefore makes EVERY later
  declaration read as unclaimed, however well evidenced it is, because the
  byte-exact walk cannot reach it from behind the hole.

  HALF B -- ADMISSION BY FILENAME.  `_foreign_claim_index` pre-filtered
  candidate artifacts to names beginning `dev-report-`.  That is a proxy for
  "carries an ownership declaration", not the question itself, and it
  excluded a real evidenced claimant solely because of its name.

Measured on this repository's own scripts/aggregate-dev-report.py at
2026-10-02T09Z, against a pinned 181285-byte subject so the four readings are
instant-consistent:

    NEITHER half   79625 bytes "claimed by no declaration", 0 spans shown
    HALF B only    78377 bytes, 0 spans shown        (chain reaches 102908)
    HALF A only    37087 bytes, 4 spans              (chain reaches 101660)
    BOTH          *37086* bytes, 4 spans             (chain reaches 102908)

Neither half alone produces the honest figure: half B alone keeps the ~2x
overstatement, and half A alone mis-places the first span's lower bound by one
byte (102907 instead of 102908) because the link it cannot admit is the thing
that establishes that bound.  So the assertions that matter are bundled into
ONE function, `assert_joint_span_invariant`, which fails if EITHER half is
reverted -- the specific hazard of a two-part invariant being that reverting
one half leaves a green suite.

Nothing is mocked.  Every scenario is a real git repository under tmp_path, a
really-edited tracked file, and the real `aggregate-dev-report.py` entry
points.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGG_PATH = REPO_ROOT / "scripts" / "aggregate-dev-report.py"

_SUBJECT = "subject.md"
_TASK_ID = "20260101-000000"
_WORKERS = ("r01", "r02")

# Four successive states of one tracked file.  Lengths are strictly increasing
# so a span's arithmetic is unambiguous, and every `old` anchor below occurs
# exactly once in the state it is applied to (the replay primitive refuses a
# non-uniquely-locatable anchor, which would make a scenario vacuous).
_BASE = "alpha\nbeta\ngamma\ndelta\nepsilon\n"
_LANE_HUNKS = [{"old": "beta", "new": "beta-LANE-aaaa"}]
_LINK_HUNKS = [{"old": "gamma", "new": "gamma-LINK-bbbbbbbb"}]
_PAST_HUNKS = [{"old": "epsilon", "new": "epsilon-PAST-cccccccccccc"}]
# The hole: bytes NO artifact declares, written straight into the worktree.
_HOLE_OLD = "delta"
_HOLE_NEW = "delta-HOLE-dddddddddddddddd"
# A second, independent hole at the tail, for the positive control.
_TAIL_OLD = "alpha"
_TAIL_NEW = "alpha-TAIL-eeeeeeeeeeeeeeeeeeee"

_LINK_TID = "20260202-000000"
_PAST_TID = "20260303-000000"
# The link claimant's filename deliberately does NOT begin with `dev-report-`.
# This is the real shape half B excluded: docs/dev/aggregator-fix-report-
# 20260930-132644.json, an evidenced 101660 -> 102908 boundary on this
# repository's own aggregator, skipped solely because of its name.
_LINK_NAME = f"aggregator-fix-report-{_LINK_TID}.json"
_PAST_NAME = f"dev-report-{_PAST_TID}.json"


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AGG = load_module(AGG_PATH, "_span_accounting_aggregator")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(value, str):
        value = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(value, encoding="utf-8")


def _apply(text: str, hunks: list[dict]) -> str:
    for hunk in hunks:
        assert text.count(hunk["old"]) == 1, (
            "fixture is vacuous: anchor %r is not uniquely locatable" % hunk["old"]
        )
        text = text.replace(hunk["old"], hunk["new"])
    return text


def _claimant(task_id: str, snapshot: str, hunks: list[dict]) -> dict:
    """A foreign cycle's ownership declaration for the subject: a ledger AND a
    starting point, which is the whole of what admission now asks for."""
    return {
        "request_id": task_id,
        "task_id": task_id,
        "baseline_head_sha": "",
        "baseline_dirty_snapshot": "",
        "dev": {"status": "completed", "files_modified": [_SUBJECT], "files_created": []},
        "owned_edits": {_SUBJECT: list(hunks)},
        "pre_edit_snapshots": {_SUBJECT: snapshot},
    }


def build_scenario(
    root: Path, *, hole: bool = True, past_declared: bool = True,
    tail_hole: bool = False, link_evidenced: bool = True,
) -> dict:
    """A real repo whose tracked subject passed through four editors in turn:
    this cycle's lane, a foreign LINK claimant, an UNDECLARED hole, and a
    foreign PAST-THE-HOLE claimant.

    `hole=False` removes the hole, so the chain closes and there is no gap at
    all -- the negative control that proves the gate is discriminating rather
    than always-on.  `past_declared=False` withdraws the past-the-hole
    declaration, so its span becomes genuinely unclaimed and must be reported.
    `tail_hole=True` adds a SECOND undeclared span, the positive control for
    "a newly constructed unattributed span is also reported".
    `link_evidenced=False` keeps the non-prefixed artifact but breaks its
    evidence, so admission must refuse it.
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / _SUBJECT).write_text(_BASE, encoding="utf-8")
    _git(root, "add", _SUBJECT)
    _git(root, "commit", "-q", "-m", "seed subject")
    head = _git(root, "rev-parse", "HEAD")

    after_lane = _apply(_BASE, _LANE_HUNKS)
    after_link = _apply(after_lane, _LINK_HUNKS)
    after_hole = _apply(after_link, [{"old": _HOLE_OLD, "new": _HOLE_NEW}]) if hole else after_link
    live = _apply(after_hole, _PAST_HUNKS)
    if tail_hole:
        live = _apply(live, [{"old": _TAIL_OLD, "new": _TAIL_NEW}])
    (root / _SUBJECT).write_text(live, encoding="utf-8")

    dev_dir = root / "docs" / "dev"
    for index, worker in enumerate(_WORKERS):
        identity = f"{_TASK_ID}-{worker}"
        _write(dev_dir / f"dev-report-{identity}.json", {
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
            # exactly one lane's declaration and an unaccounted remainder is
            # unambiguously unaccounted.
            "owned_edits": {_SUBJECT: list(_LANE_HUNKS)} if index == 0 else {},
            "pre_edit_snapshots": {_SUBJECT: _BASE} if index == 0 else {},
        })

    link_snapshot = after_lane if link_evidenced else after_lane + "DIVERGED\n"
    _write(dev_dir / _LINK_NAME, _claimant(_LINK_TID, link_snapshot, _LINK_HUNKS))
    if past_declared:
        _write(dev_dir / _PAST_NAME, _claimant(_PAST_TID, after_hole, _PAST_HUNKS))

    return {
        "head": head,
        "base": _BASE,
        "after_lane": after_lane,
        "after_link": after_link,
        "after_hole": after_hole,
        "live": live,
    }


def observe(root: Path, agg_mod: ModuleType, states: dict) -> dict:
    """Run the REAL production completeness check on the scenario and parse the
    figures back out of the diagnostic a gate would actually print."""
    dev_dir = root / "docs" / "dev"
    bare = agg_mod._bare_task_id(_TASK_ID)
    loaded, failures = agg_mod._load_all_shards(
        agg_mod._scan_shards(dev_dir, bare, _TASK_ID)
    )
    assert not failures, failures
    aggregate = agg_mod._build_aggregate(loaded, _TASK_ID)
    gaps = agg_mod._apply_completeness_check(aggregate, root, loaded)
    diagnostic = gaps[0] if gaps else ""
    reaches = re.search(r"reaches (\d+) bytes", diagnostic)
    total = re.search(r"leaving (\d+) of the (\d+) live bytes", diagnostic)
    return {
        "roster": [label for label, _ in loaded],
        "gaps": gaps,
        "diagnostic": diagnostic,
        "chain_reaches": int(reaches.group(1)) if reaches else None,
        "reported_total": int(total.group(1)) if total else None,
        "reported_live": int(total.group(2)) if total else None,
        "spans": [
            (int(lo), int(hi), int(n))
            for lo, hi, n in re.findall(r"(\d+)-(\d+) \((\d+) bytes\)", diagnostic)
        ],
        "covered": re.findall(r"(\d+)-(\d+) by ([^,)]+)", diagnostic),
    }


def assert_joint_span_invariant(observation: dict, states: dict) -> None:
    """Every clause the two halves must JOINTLY satisfy on a real mid-chain
    hole.  Reverting half A breaks A1-A3; reverting half B breaks B1-B2 and,
    transitively, A1's lower bound.  One function, so no single-half revert
    leaves this green.
    """
    hole_lo, hole_hi = len(states["after_link"]), len(states["after_hole"])
    live_size = len(states["live"])
    assert observation["gaps"], "precondition: the scenario must present a real gap"
    diagnostic = observation["diagnostic"]

    # B1: the non-prefixed artifact is admitted as a chain link, which can
    # only happen when admission is decided by declaration and not by name.
    assert _LINK_TID in diagnostic, (
        "half B reverted: the non-prefixed evidenced claimant %s never became a "
        "chain link.\n%s" % (_LINK_NAME, diagnostic)
    )
    # B2: and the chain therefore reaches that link's own replay output.
    assert observation["chain_reaches"] == hole_hi - (hole_hi - hole_lo) == hole_lo

    # A1: exactly the hole is reported, as its own span -- not the whole tail.
    assert observation["spans"] == [(hole_lo, hole_hi, hole_hi - hole_lo)], (
        "half A reverted: spans are not the union of genuinely unclaimed "
        "intervals.\n%s" % diagnostic
    )
    # A2: the total is the hole, NOT the stall subtraction.
    assert observation["reported_total"] == hole_hi - hole_lo
    assert observation["reported_total"] != live_size - hole_lo, (
        "half A reverted: the reported total is still the stall subtraction"
    )
    # A3: the declared span past the hole is NOT counted, and the declaration
    # that accounts for it is NAMED -- every byte this stops counting is
    # attributed to a declaration rather than quietly dropped.
    assert any(src.strip() == _PAST_TID for _lo, _hi, src in observation["covered"]), (
        "half A reverted: the past-the-hole declaration is not named as "
        "covering its span.\n%s" % diagnostic
    )
    assert (str(hole_hi), str(live_size)) in [
        (lo, hi) for lo, hi, _src in observation["covered"]
    ]

    # Untouched either way: the live size is still stated, and the gap class is
    # still recognisable by its own wording.
    assert observation["reported_live"] == live_size
    assert "claimed by no declaration" in diagnostic
    # And the roster is unaffected: no claimant can become a worker.
    assert observation["roster"] == list(_WORKERS)


@pytest.fixture(autouse=True)
def _clear_caches():
    for cache in (AGG._FOREIGN_CLAIM_INDEX_CACHE, AGG._CYCLE_CLAIMANT_INDEX_CACHE,
                  AGG._DECLARED_INTERVALS_CACHE):
        cache.clear()
    yield
    for cache in (AGG._FOREIGN_CLAIM_INDEX_CACHE, AGG._CYCLE_CLAIMANT_INDEX_CACHE,
                  AGG._DECLARED_INTERVALS_CACHE):
        cache.clear()


def test_mid_chain_hole_reports_only_the_hole(tmp_path):
    """The whole invariant, on a genuine mid-chain hole."""
    root = tmp_path / "joint"
    states = build_scenario(root)
    assert_joint_span_invariant(observe(root, AGG, states), states)


def test_non_prefixed_declaration_is_admitted_as_a_chain_link(tmp_path):
    """Half B in isolation: admission by declaration, not by filename prefix."""
    root = tmp_path / "admission"
    states = build_scenario(root)
    observation = observe(root, AGG, states)
    assert _LINK_TID in observation["diagnostic"]
    assert observation["chain_reaches"] == len(states["after_link"])


def test_unevidenced_non_prefixed_declaration_is_refused(tmp_path):
    """The evidence guard: dropping the filename proxy must not admit a claim
    whose own snapshot does not resolve to the chain position it claims to
    continue from.  Without this, half B would be a hole rather than a fix.
    """
    root = tmp_path / "unevidenced"
    states = build_scenario(root, link_evidenced=False)
    observation = observe(root, AGG, states)
    assert _LINK_TID not in observation["diagnostic"], (
        "an unevidenced claimant advanced the chain:\n%s" % observation["diagnostic"]
    )
    # The chain cannot pass the lane's own output, so the hole it could not
    # bridge is reported from there -- still reported, never silently excused.
    assert observation["gaps"]


def test_unreplayable_non_prefixed_declaration_is_refused(tmp_path):
    """The second half of the evidence guard: a resolvable starting point whose
    ledger cannot replay with uniquely locatable anchors is not a claim."""
    root = tmp_path / "unreplayable"
    states = build_scenario(root)
    bad = _claimant(_LINK_TID, states["after_lane"], [{"old": "NOT-PRESENT-ANYWHERE", "new": "x"}])
    _write(root / "docs" / "dev" / _LINK_NAME, bad)
    observation = observe(root, AGG, states)
    assert _LINK_TID not in observation["diagnostic"], (
        "an unreplayable ledger advanced the chain:\n%s" % observation["diagnostic"]
    )
    assert observation["gaps"]


def test_withdrawing_the_past_the_hole_declaration_reports_its_span(tmp_path):
    """Discrimination: the span past the hole is excluded ONLY because a
    declaration covers it.  Withdraw the declaration and the span must come
    back -- this is what proves the reduction is a found declaration and not a
    decision to stop counting bytes.
    """
    root = tmp_path / "withdrawn"
    states = build_scenario(root, past_declared=False)
    observation = observe(root, AGG, states)
    hole_lo, hole_hi = len(states["after_link"]), len(states["after_hole"])
    assert observation["spans"] == [(hole_lo, len(states["live"]), len(states["live"]) - hole_lo)]
    assert observation["reported_total"] == len(states["live"]) - hole_lo
    assert observation["covered"] == []


def test_newly_constructed_unattributed_span_is_also_reported(tmp_path):
    """Positive control for "no unclaimed byte becomes invisible": a SECOND,
    independently constructed undeclared span must appear individually, not be
    absorbed into a neighbour or dropped.
    """
    root = tmp_path / "positive-control"
    states = build_scenario(root, tail_hole=True)
    observation = observe(root, AGG, states)
    hole_lo, hole_hi = len(states["after_link"]), len(states["after_hole"])
    past_out = len(_apply(states["after_hole"], _PAST_HUNKS))
    assert observation["spans"] == [
        (hole_lo, hole_hi, hole_hi - hole_lo),
        (past_out, len(states["live"]), len(states["live"]) - past_out),
    ], observation["diagnostic"]
    assert observation["reported_total"] == (hole_hi - hole_lo) + (
        len(states["live"]) - past_out
    )


def test_no_hole_means_no_gap_at_all(tmp_path):
    """Negative control: the diagnostic is discriminating, not always-on.  A
    chain that closes byte-exactly must produce no gap, so span-accounting
    cannot be mistaken for a gate that simply reports less of everything."""
    root = tmp_path / "negative-control"
    states = build_scenario(root, hole=False)
    observation = observe(root, AGG, states)
    assert observation["gaps"] == [], observation["gaps"]


def test_length_covered_but_not_byte_closed_still_fails(tmp_path):
    """Fail-closed: span-accounting narrows the ACCOUNTING, never the verdict.

    When declarations happen to cover the whole remainder BY LENGTH while the
    byte-exact chain is still open, the verdict must stay a failure and the
    diagnostic must say that a length-neutral undeclared edit is unreconciled
    -- otherwise a zero total would read as a clean file.
    """
    root = tmp_path / "length-neutral"
    states = build_scenario(root)
    # A declaration spanning the hole's own length interval, from a starting
    # point that is NOT the chain position, so it covers by length only.
    spanning = _claimant(
        "20260404-000000", states["after_link"] + "UNRELATED-PREFIX-BYTES\n",
        [{"old": _HOLE_OLD, "new": _HOLE_NEW}],
    )
    _write(root / "docs" / "dev" / "spanning-report-20260404-000000.json", spanning)
    observation = observe(root, AGG, states)
    assert observation["gaps"], "a non-byte-closed chain must still fail"
    if observation["spans"] == []:
        assert "BY LENGTH" in observation["diagnostic"]
        assert "not byte-closed" in observation["diagnostic"]


def test_both_diagnostic_sites_share_one_wording(tmp_path):
    """The two call sites must not drift into disagreeing about the same fact.

    A mirrored pair of hand-written f-strings is how the pre-fix code held this
    wording, and a mirrored pair is exactly what lets one site be corrected
    while the other keeps overstating.  Pin the single formatter and the
    absence of any surviving stall subtraction.
    """
    source = AGG_PATH.read_text(encoding="utf-8")
    assert source.count("_span_shortfall_diagnostic(") == 3, (
        "expected one definition and two call sites"
    )
    assert "len(live_bytes) - len(end_bytes)" not in source, (
        "a stall subtraction survives in the diagnostic wording"
    )


def test_unclaimed_spans_is_a_union_not_a_subtraction():
    """`_unclaimed_spans` directly: overlapping, out-of-order and
    out-of-window declared intervals must all reduce to one honest union.

    Intervals are primed in the shape `_declared_length_intervals` actually
    stores them -- already normalised to (min, max), which is why a shrinking
    edit appears here as (800, 900) rather than (900, 800).
    """
    intervals = [
        (300, 400, "b"), (100, 200, "a"), (150, 250, "a2"),
        (800, 900, "shrinking-edit"), (10, 50, "before-window"),
        (1000, 2000, "past-window"),
    ]
    # The function reads its intervals from the memoized index, so prime that
    # cache to exercise the pure reduction it performs on them.
    AGG._DECLARED_INTERVALS_CACHE[("d", "t", "rel")] = intervals
    spans, covered = AGG._unclaimed_spans(Path("/"), Path("d"), "t", "rel", 100, 1000)
    assert spans == [(250, 300), (400, 800), (900, 1000)]
    assert sum(hi - lo for lo, hi in spans) == 50 + 400 + 100
    # Every covering interval is clipped into the window and named; intervals
    # wholly outside the window contribute nothing and name nothing.
    assert covered == [
        (100, 200, "a"), (150, 250, "a2"), (300, 400, "b"), (800, 900, "shrinking-edit"),
    ]


def test_a_shrinking_edit_is_normalised_into_a_forward_interval(tmp_path):
    """A declaration whose replay SHRINKS the file still accounts for the span
    between the two sizes; storing it as (hi, lo) would silently contribute
    nothing, which would overstate the gap exactly as the stall subtraction
    did.  Verified through the real producer, not by priming the cache.
    """
    root = tmp_path / "shrink"
    states = build_scenario(root)
    shrink_from = states["live"] + "SURPLUS-LINE-TO-BE-REMOVED\n"
    _write(root / "docs" / "dev" / "shrink-report-20260505-000000.json",
           _claimant("20260505-000000", shrink_from,
                     [{"old": "SURPLUS-LINE-TO-BE-REMOVED\n", "new": ""}]))
    intervals = AGG._declared_length_intervals(
        root, root / "docs" / "dev", AGG._bare_task_id(_TASK_ID), _SUBJECT
    )
    shrinking = [t for t in intervals if t[2] == "20260505-000000"]
    assert shrinking == [(len(states["live"]), len(shrink_from), "20260505-000000")]
    assert shrinking[0][0] < shrinking[0][1], "interval must be forward-oriented"
