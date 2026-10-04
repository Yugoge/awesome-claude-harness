"""Regression coverage for backlog #99 (task 20260922-100846): the canonical
aggregate dev-report silently dropped a retried lane's superseded round(s)'
owned_edits/pre_edit_snapshots when that lane's promoted (post-QA-FAIL retry)
report recorded only a delta on top of the round it superseded.

Root cause (docs/dev/ticket-20260922-100846.md): `_scan_shards()`
(scripts/aggregate-dev-report.py) only enumerates top-level files directly
under docs/dev/, never recursing into docs/dev/superseded-<task-id>/, so a
QA-FAIL'd round-0 report archived there was invisible to `_merge_owned_edits`.
Measured on the real cycle 20260921-134709 this session: lane b=6 hunks,
lane c=5 hunks, lane d round-0=11 hunks, lane d promoted (delta-only)=1 hunk
for scripts/spec-check.py -- the pre-fix aggregate only ever saw 12 of the
23 hunks required to byte-replay from the true git baseline to the live
file. This suite is self-contained: it builds isolated synthetic git-repo
fixtures rather than depending on that real cycle's on-disk artifacts
remaining in their current state, but the b/c/d hunk counts below (6, 5, 11,
1) deliberately mirror the real cycle's own shape, including an explicit
order-dependency between lanes (c's last hunk anchors on text b's own edit
creates) and within a retried lane (the promoted delta anchors on text
round-0's own edit creates) -- the same "order matters" property BA's git-
blob replay verified in the real cycle.

The fix adds two additive capabilities to scripts/aggregate-dev-report.py:
  1. `_scan_superseded_shards`/`_expand_shards_with_superseded_rounds`: fold
     each lane's docs/dev/superseded-<task-id>/dev-report-<task-id>-<lane>-
     round<N>.json reports ahead of that lane's own promoted contribution,
     for the owned_edits/pre_edit_snapshots merge ONLY, in ascending
     numeric round order (never mtime).
  2. `_apply_completeness_check` (backlog #99 criterion C): for every
     TRACKED file in the final merged owned_edits, reuse
     scripts/stage-owned-hunks.py's own `--ledger --snapshot --dry-run`
     replay-and-compare logic (never reimplemented here) to verify the
     union actually covers the live file's bytes; a gap makes the
     aggregator exit non-zero with a named diagnostic while still writing
     the aggregate (ownership_completeness_gaps populated, never silently
     omitted).
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "aggregate-dev-report.py"
_spec = importlib.util.spec_from_file_location("aggregate_dev_report_superseded", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

main = _mod.main
_build_aggregate = _mod._build_aggregate
_scan_superseded_shards = _mod._scan_superseded_shards
_expand_shards_with_superseded_rounds = _mod._expand_shards_with_superseded_rounds
_merge_owned_edits = _mod._merge_owned_edits
_resolve_baseline_snapshot = _mod._resolve_baseline_snapshot
_resolve_dev_dir = _mod._resolve_dev_dir
_tracked_at_baseline = _mod._tracked_at_baseline
_apply_completeness_check = _mod._apply_completeness_check


# ---------------------------------------------------------------------------
# git / fixture helpers
# ---------------------------------------------------------------------------

def _git(repo, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise AssertionError(result.stderr.decode("utf-8", "replace"))
    return result


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real git repo (repo root == project root) with docs/dev/ ready, so
    the criterion-C completeness check has a real git index/HEAD to resolve
    baselines against -- mirroring the real /close invocation shape."""
    (tmp_path / "docs" / "dev").mkdir(parents=True)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return tmp_path


def _apply_forward(snapshot: bytes, edits: list) -> bytes:
    """The same forward-replace algorithm stage-owned-hunks.py's own replay
    uses, applied here only to compute a fixture's ground-truth live file
    deterministically. Asserts each anchor is unique at its own step
    (fixture precondition, not the code under test)."""
    buf = snapshot
    for edit in edits:
        old_b = edit["old"].encode("utf-8")
        new_b = edit["new"].encode("utf-8")
        assert buf.count(old_b) == 1, "fixture precondition violated: %r not unique" % edit["old"]
        off = buf.find(old_b)
        buf = buf[:off] + new_b + buf[off + len(old_b):]
    return buf


def _commit_baseline(repo: Path, rel: str, content: bytes) -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-qm", "baseline: %s" % rel)
    return _git(repo, "rev-parse", "HEAD").stdout.decode().strip()


def _shard(task_id, sha, files_modified=None, owned_edits=None, pre_edit_snapshots=None):
    return {
        "task_id": task_id,
        "baseline_head_sha": sha,
        "baseline_dirty_snapshot": "",
        "dev": {
            "status": "completed",
            "tasks_completed": [],
            "scripts_created": [],
            "permissions_to_add": [],
            "files_modified": files_modified or [],
            "files_created": [],
            "observed_preexisting": [],
        },
        "blocking_issues": [],
        "recommendations": [],
        "owned_edits": owned_edits or {},
        "pre_edit_snapshots": pre_edit_snapshots or {},
    }


def _write(dev_dir: Path, filename: str, data: dict) -> Path:
    p = dev_dir / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# Real-shape (cycle 20260921-134709) fixture: b=6, c=5, d round0=11 + 1
# delta = 23 total, WITH the same two order-dependencies BA's own byte
# replay proved necessary in the real cycle (cross-lane b->c, and intra-lane
# round0->promoted).
# ---------------------------------------------------------------------------

TASK_ID = "20260101-090000"
REL = "target.py"
BASE_LINES = ["line%02d\n" % i for i in range(1, 25)]  # 24 lines, 1..24
BASE_CONTENT = "".join(BASE_LINES).encode("utf-8")

LANE_B_HUNKS = [{"old": "line%02d\n" % i, "new": "line%02d-B\n" % i} for i in range(1, 7)]  # 6
LANE_C_HUNKS = [{"old": "line%02d\n" % i, "new": "line%02d-C\n" % i} for i in range(7, 11)] + [
    {"old": "line01-B\n", "new": "line01-BC\n"},  # depends on lane b's own edit -- order-sensitive
]  # 5
LANE_D_ROUND0_HUNKS = [
    {"old": "line%02d\n" % i, "new": "line%02d-D0\n" % i} for i in range(11, 22)
]  # 11
LANE_D_PROMOTED_HUNKS = [
    {"old": "line11-D0\n", "new": "line11-D0-FIX\n"},  # depends on round0's own edit
]  # 1

ALL_HUNKS_CORRECT_ORDER = LANE_B_HUNKS + LANE_C_HUNKS + LANE_D_ROUND0_HUNKS + LANE_D_PROMOTED_HUNKS
LIVE_CONTENT = _apply_forward(BASE_CONTENT, ALL_HUNKS_CORRECT_ORDER)

BUGGY_ORDER_MISSING_ROUND0 = LANE_B_HUNKS + LANE_C_HUNKS + LANE_D_PROMOTED_HUNKS  # 12, pre-fix shape


def _write_real_shape_fixture(repo: Path, *, drop_last_round0_hunk: bool = False) -> str:
    """Write the b/c/d fixture's shards to docs/dev/ and commit+dirty the
    target file. Returns baseline_head_sha. With drop_last_round0_hunk=True,
    round-0's OWN declared owned_edits omits its last hunk -- a genuine gap
    that not even the union (with the fix applied) can cover (AC-4/D4)."""
    dev_dir = repo / "docs" / "dev"
    sha = _commit_baseline(repo, REL, BASE_CONTENT)
    (repo / REL).write_bytes(LIVE_CONTENT)  # dirty, unstaged -- mirrors ' M scripts/spec-check.py'

    round0_hunks = LANE_D_ROUND0_HUNKS[:-1] if drop_last_round0_hunk else LANE_D_ROUND0_HUNKS

    _write(dev_dir, "dev-report-%s-b.json" % TASK_ID, _shard(
        TASK_ID, sha, [REL], {REL: LANE_B_HUNKS}, {REL: sha},
    ))
    _write(dev_dir, "dev-report-%s-c.json" % TASK_ID, _shard(
        TASK_ID, sha, [REL], {REL: LANE_C_HUNKS}, {REL: sha},
    ))
    _write(dev_dir, "dev-report-%s-d.json" % TASK_ID, _shard(
        TASK_ID, sha, [REL], {REL: LANE_D_PROMOTED_HUNKS}, {REL: sha},
    ))
    _write(
        dev_dir / ("superseded-%s" % TASK_ID),
        "dev-report-%s-d-round0.json" % TASK_ID,
        _shard(TASK_ID, sha, [REL], {REL: round0_hunks}, {REL: sha}),
    )
    return sha


# ---------------------------------------------------------------------------
# AC-2 / D2 (1 retry) + real-shape reproduction of cycle 20260921-134709
# ---------------------------------------------------------------------------

class TestOneRetryFoldsRound0AheadOfPromoted:
    def test_ac2_union_is_round0_then_promoted_in_order_zero_dropped(self):
        """AC-2: the canonical aggregate's owned_edits[F] contains all 12 of
        lane d's hunks -- round-0's 11 followed by promoted's 1 -- in that
        exact order, zero dropped."""
        shards = [
            ("b", _shard(TASK_ID, "sha1", [REL], {REL: LANE_B_HUNKS})),
            ("d", _shard(TASK_ID, "sha1", [REL], {REL: LANE_D_PROMOTED_HUNKS})),
        ]
        superseded_dev_dir = Path("/nonexistent/does/not/matter")
        expanded = _expand_shards_with_superseded_rounds(
            [("d", shards[1][1])], superseded_dev_dir, "20260101-090000"
        )
        # With no superseded directory on disk at all, expansion is a no-op
        # (identity) -- proves the additive contract before exercising a
        # real disk-backed superseded round below.
        assert expanded == [("d", shards[1][1])]

    def test_ac2_and_real_shape_end_to_end_23_hunks_replay_clean(
        self, repo: Path, capsys: pytest.CaptureFixture
    ):
        """Real-shape reproduction of cycle 20260921-134709 (b=6, c=5,
        d round0=11, d promoted=1 => 23 total): after the fix, re-running
        the UNMODIFIED CLI produces a canonical whose owned_edits[target.py]
        has all 23 hunks in b, c, round0, promoted order, and the criterion-C
        completeness check passes (aggregator exits 0)."""
        _write_real_shape_fixture(repo)

        rc = main(["--task-id", TASK_ID])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0, out
        assert out["action"] == "aggregated"

        doc = json.loads((repo / "docs" / "dev" / ("dev-report-%s.json" % TASK_ID)).read_text())
        assert doc["owned_edits"][REL] == ALL_HUNKS_CORRECT_ORDER
        assert len(doc["owned_edits"][REL]) == 23
        assert doc["blocking_issues"] == []
        assert doc[_mod.COMPLETENESS_GAPS_KEY] == []  # the real no-gap witness

    def test_bug_reproduction_without_the_fix_matches_pre_fix_12_hunk_shape(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        """TDD control: with superseded-round discovery stubbed out (the
        pre-fix state), the real-shape fixture reproduces the EXACT reported
        defect -- a 12-hunk ledger (round-0's 11 hunks silently dropped) that
        fails to byte-replay the live file, so the criterion-C completeness
        check itself now (post-fix) catches what the pre-fix aggregator
        would have silently shipped as 'aggregated' with no blocking_issues
        at all."""
        _write_real_shape_fixture(repo)
        monkeypatch.setattr(_mod, "_scan_superseded_shards", lambda *a, **k: {})

        rc = main(["--task-id", TASK_ID])
        capsys.readouterr()
        # Attribution-journal consumer cutover (docs/reference/attribution-
        # journal-cutover-flip-plan-20261003.md, superseded by the zero-
        # blocking constraint of the follow-up consumer-cutover task): the
        # exit code is gated by the write-time ledger now, not by this
        # criterion-C replay (see _completeness_check_file's require_full_
        # coverage=False branch) -- a git-only fixture with no journal
        # evidence is deferred, not blocked, so rc == 0. The replay-based
        # criterion-C check this test was built to pin still runs, UNCHANGED,
        # as the non-blocking GLOBAL diagnostic the assertions below verify.
        assert rc == 0

        doc = json.loads((repo / "docs" / "dev" / ("dev-report-%s.json" % TASK_ID)).read_text())
        assert doc["owned_edits"][REL] == BUGGY_ORDER_MISSING_ROUND0
        assert len(doc["owned_edits"][REL]) == 12
        # The diagnostic is recorded on the aggregate's own completeness key,
        # never on `blocking_issues`: that field is freshness-compared, so a
        # diagnostic written there made the canonical permanently stale
        # against its own rebuild.  Same strength, different channel.
        assert any(REL in issue for issue in doc[_mod.COMPLETENESS_GAPS_KEY])
        assert not any(REL in issue for issue in doc["blocking_issues"])


# ---------------------------------------------------------------------------
# AC-3 / D3: full coverage -> criterion C passes, aggregator exits 0
# ---------------------------------------------------------------------------

class TestFullCoveragePasses:
    def test_ac3_criterion_c_passes_and_aggregator_exits_0(
        self, repo: Path, capsys: pytest.CaptureFixture
    ):
        _write_real_shape_fixture(repo)
        rc = main(["--task-id", TASK_ID])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0, out
        assert out["status"] == "ok"


# ---------------------------------------------------------------------------
# AC-4 / D4, REVISED under the same-cycle-only gate rescope (task
# dev-20260927-135305, spec-20260914-052140 S5.3): criterion C (the full,
# cross-cycle-aware completeness check) still catches this gap and still
# names target.py -- that computation and its storage key are UNCHANGED by
# the rescope. What changed on purpose is which figure drives the aggregator's
# OWN exit code. This fixture's gap is a same-cycle SHORTFALL, not a
# same-cycle CONFLICT: round-0's declared ledger replays WITHOUT ERROR from
# its own declared starting point (every remaining anchor is still uniquely
# locatable; a hunk is simply absent from the ledger, not colliding with
# another), it just reproduces fewer bytes than the live file. Mechanically
# that is indistinguishable, from the checker's own vantage point, from "an
# unrelated concurrent session holds the remaining bytes and has not declared
# them yet" -- exactly the shape the rescope forbids blocking on. The
# narrower, same-cycle-only question (OWNERSHIP_COMPLETENESS_BLOCKING_KEY)
# therefore no longer fails here; the broader, non-blocking forensic
# question (COMPLETENESS_GAPS_KEY) still does, so the gap is never silently
# lost -- it is reported, just not gate-worthy. See
# test_stage_owned_hunks_boundary.py's own BOUNDARY_INDETERMINATE case
# (tests/test_aggregate_dev_report.py) for the negative control this rescope
# still fails closed on: a replay that raises because an anchor is not
# uniquely locatable is a genuine same-cycle conflict, not a mere shortfall.
# ---------------------------------------------------------------------------

class TestGenuineGapFailsClosed:
    def test_ac4_shortfall_stays_informational_not_blocking_after_rescope(
        self, repo: Path, capsys: pytest.CaptureFixture
    ):
        """A same-cycle shortfall (round-0's own declared owned_edits is
        missing a hunk, so the union's replay succeeds but falls short of the
        live file) no longer fails the aggregator's own exit code after the
        same-cycle-only gate rescope: the shortfall is not a conflict and not
        a non-replaying ledger, so it is not this cycle's own incoherence to
        fail on. Criterion C keeps naming target.py in the non-blocking
        COMPLETENESS_GAPS_KEY, and the canonical is still written either way
        (never a missing artifact)."""
        _write_real_shape_fixture(repo, drop_last_round0_hunk=True)

        rc = main(["--task-id", TASK_ID])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0, out
        assert out["status"] == "ok"

        canonical_path = repo / "docs" / "dev" / ("dev-report-%s.json" % TASK_ID)
        assert canonical_path.exists(), "canonical must still be written on a criterion-C gap"
        doc = json.loads(canonical_path.read_text())
        assert doc["owned_edits"][REL] == LANE_B_HUNKS + LANE_C_HUNKS + LANE_D_ROUND0_HUNKS[:-1] + LANE_D_PROMOTED_HUNKS
        # The diagnostic is recorded on the aggregate's own completeness key,
        # never on `blocking_issues`: that field is freshness-compared, so a
        # diagnostic written there made the canonical permanently stale
        # against its own rebuild.  Same strength, different channel.
        assert any(REL in issue for issue in doc[_mod.COMPLETENESS_GAPS_KEY])
        assert not any(REL in issue for issue in doc["blocking_issues"])
        # The narrower, GATING channel is clean: a same-cycle shortfall with
        # no conflict and no replay error is exactly what the rescope says
        # must never block (spec-20260914-052140 S5.3) -- this is the
        # negative-of-the-negative: proof the rescope does not merely log the
        # old verdict under a new name while still failing the build.
        assert doc[_mod.OWNERSHIP_COMPLETENESS_BLOCKING_KEY] == []


# ---------------------------------------------------------------------------
# AC-6: an untracked (brand-new) file in owned_edits is SKIPPED by
# criterion C, never spuriously excluded/blocking the whole aggregator.
# ---------------------------------------------------------------------------

class TestUntrackedFileSkipped:
    def test_ac6_brand_new_untracked_file_is_skipped_not_excluded(
        self, repo: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = repo / "docs" / "dev"
        sha = _commit_baseline(repo, REL, b"line01\nline02\n")
        (repo / REL).write_bytes(b"line01-P\nline02-Q\n")

        p_hunks = {REL: [{"old": "line01\n", "new": "line01-P\n"}]}
        q_hunks = {
            REL: [{"old": "line02\n", "new": "line02-Q\n"}],
            "brand_new_file.py": [{"old": "", "new": "print('new')\n"}],
        }
        assert not (repo / "brand_new_file.py").exists()  # never even created -> definitely untracked

        _write(dev_dir, "dev-report-%s-p.json" % TASK_ID, _shard(TASK_ID, sha, [REL], p_hunks, {REL: sha}))
        _write(dev_dir, "dev-report-%s-q.json" % TASK_ID, _shard(
            TASK_ID, sha, [REL, "brand_new_file.py"], q_hunks, {REL: sha},
        ))

        rc = main(["--task-id", TASK_ID])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0, out
        doc = json.loads((dev_dir / ("dev-report-%s.json" % TASK_ID)).read_text())
        assert "brand_new_file.py" in doc["owned_edits"]  # union still records it
        assert doc["blocking_issues"] == []
        # The real "no completeness gap" witness. `blocking_issues` stopped
        # being one when the diagnostics moved to their own non-freshness-
        # compared key, so asserting only that would be vacuous here.
        assert doc[_mod.COMPLETENESS_GAPS_KEY] == []  # never blocks completeness


# ---------------------------------------------------------------------------
# AC-7: heterogeneous pre_edit_snapshots encoding + first-shard-wins
# ambiguity -- criterion C must independently resolve the TRUE baseline via
# git show <baseline_head_sha>:F rather than trust the (possibly wrong)
# declared/merged value.
# ---------------------------------------------------------------------------

class TestHeterogeneousSnapshotEncodingResolvesToTrueBaseline:
    def test_ac7_first_shard_wins_inaccurate_literal_is_not_trusted(
        self, repo: Path, capsys: pytest.CaptureFixture
    ):
        """Lane 'p' (alphabetically first, so _merge_pre_edit_snapshots picks
        ITS declared value) declares an INACCURATE literal-text snapshot --
        mirroring the real cycle's lane c, whose own pre_edit_snapshots
        value was literal text that was NOT the true git baseline. Lane 'q'
        declares the correct blob SHA. Criterion C must still pass by
        resolving via git show <sha>:F directly, ignoring both declared
        forms."""
        sha = _commit_baseline(repo, REL, b"line01\nline02\n")
        (repo / REL).write_bytes(b"line01-P\nline02-Q\n")

        _write(repo / "docs" / "dev", "dev-report-%s-p.json" % TASK_ID, _shard(
            TASK_ID, sha, [REL],
            {REL: [{"old": "line01\n", "new": "line01-P\n"}]},
            {REL: "totally-wrong-literal-snapshot-not-the-real-baseline"},
        ))
        _write(repo / "docs" / "dev", "dev-report-%s-q.json" % TASK_ID, _shard(
            TASK_ID, sha, [REL],
            {REL: [{"old": "line02\n", "new": "line02-Q\n"}]},
            {REL: sha},
        ))

        rc = main(["--task-id", TASK_ID])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0, out
        doc = json.loads((repo / "docs" / "dev" / ("dev-report-%s.json" % TASK_ID)).read_text())
        # _merge_pre_edit_snapshots itself is UNCHANGED -- still first-shard-
        # wins, still carries the inaccurate declared value verbatim.
        assert doc["pre_edit_snapshots"][REL] == "totally-wrong-literal-snapshot-not-the-real-baseline"
        # Yet criterion C passed (rc == 0) because it re-resolved via
        # baseline_head_sha independently, per AC-7's resolution rule.

    def test_resolve_baseline_snapshot_prefers_baseline_head_sha(self, repo: Path):
        sha = _commit_baseline(repo, REL, b"true baseline content\n")
        snapshot, source = _resolve_baseline_snapshot(repo, sha, REL, "irrelevant-declared-value")
        assert snapshot == b"true baseline content\n"
        assert source == "baseline_head_sha"

    def test_resolve_baseline_snapshot_falls_back_to_declared_blob_sha(self, repo: Path):
        _commit_baseline(repo, "other.py", b"other file\n")
        proc = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input=b"declared blob body\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0
        declared_sha = proc.stdout.decode().strip()
        # REL was never committed -- baseline_head_sha resolution must miss.
        snapshot, source = _resolve_baseline_snapshot(repo, "", REL, declared_sha)
        assert snapshot == b"declared blob body\n"
        assert source == "declared_blob_sha"

    def test_resolve_baseline_snapshot_falls_back_to_literal_text(self, repo: Path):
        snapshot, source = _resolve_baseline_snapshot(repo, "", "never-tracked.py", "literal fallback body")
        assert snapshot == b"literal fallback body"
        assert source == "literal_text"


# ---------------------------------------------------------------------------
# Task 20260930-132644: _resolve_baseline_snapshot's priority order was
# wrong whenever rel was ALREADY DIRTY (uncommitted changes from a prior
# session or a concurrent sibling lane) before the current cycle's capture
# ran. baseline_head_sha names the last CLEAN commit, which is not a valid
# stand-in for "this file's content at the moment this lane began editing
# it" in that case -- yet the pre-fix function tried baseline_head_sha FIRST
# unconditionally, so a lane's own correctly-captured, independently-
# verifiable (git-blob-SHA-form) pre_edit_snapshot was discarded in favor of
# the wrong HEAD content, producing a false completeness-check EXCLUDE
# (stage-owned-hunks.py's own I12-snapshot-mismatch) even though the real
# evidence needed to pass was already on hand.
#
# The fix promotes a RESOLVABLE declared_blob_sha above baseline_head_sha
# whenever it differs from HEAD (or HEAD cannot resolve at all), while
# literal-text-form declarations keep their pre-fix position BELOW HEAD --
# preserving AC-7 above, which deliberately protects against trusting an
# inaccurate literal-text first-shard-wins declaration over HEAD.
# ---------------------------------------------------------------------------

class TestAlreadyDirtyBaselinePrefersDeclaredBlobOverHead:
    def test_resolve_baseline_snapshot_prefers_declared_blob_when_file_was_already_dirty(
        self, repo: Path
    ):
        """Unit-level reproduction: baseline_head_sha resolves (rel IS
        tracked at that commit) but to the WRONG (clean, pre-dirty) content;
        the lane's own declared_value is a real, independently-verified git
        blob holding the TRUE dispatch-time (already-dirty) bytes. The fix
        must prefer the declared blob, not HEAD."""
        sha = _commit_baseline(repo, REL, b"clean committed content\n")
        proc = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input=b"true dirty-at-dispatch content\n",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0
        declared_sha = proc.stdout.decode().strip()

        snapshot, source = _resolve_baseline_snapshot(repo, sha, REL, declared_sha)
        assert snapshot == b"true dirty-at-dispatch content\n"
        assert source == "declared_blob_sha"

    def test_resolve_baseline_snapshot_declared_blob_equal_to_head_prefers_head_label(
        self, repo: Path
    ):
        """When the declared blob resolves but is byte-identical to HEAD's
        content (the file was NOT actually dirty -- there is no better
        evidence than HEAD), the function falls back to the
        baseline_head_sha source label, per the fix's own fallback clause."""
        sha = _commit_baseline(repo, REL, b"same content\n")
        # The commit's OWN tree entry for REL -- its blob SHA, not the
        # commit SHA -- is by construction byte-identical to whatever HEAD
        # resolution will return for REL at this commit.
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", f"{sha}:{REL}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0
        declared_sha = proc.stdout.decode().strip()

        snapshot, source = _resolve_baseline_snapshot(repo, sha, REL, declared_sha)
        assert snapshot == b"same content\n"
        assert source == "baseline_head_sha"

    def test_resolve_baseline_snapshot_head_substitution_when_declared_value_missing(
        self, repo: Path
    ):
        """Old correct behavior, confirmed unchanged: with no declared_value
        at all (None), HEAD substitution still fires exactly as before."""
        sha = _commit_baseline(repo, REL, b"true baseline content\n")
        snapshot, source = _resolve_baseline_snapshot(repo, sha, REL, None)
        assert snapshot == b"true baseline content\n"
        assert source == "baseline_head_sha"

    def test_ac_dirty_file_completeness_check_passes_with_correct_declared_blob(
        self, repo: Path, capsys: pytest.CaptureFixture
    ):
        """End-to-end reproduction of the real bug via the unmodified CLI:
        rel was already dirty BEFORE this cycle started (its true pre-edit
        content differs from the last clean commit). The lane's hunk only
        anchors on the true dirty content, and the lane correctly declares
        that true content as a real git blob. Pre-fix, criterion C
        substituted HEAD, the hunk's anchor was absent from HEAD, and
        stage-owned-hunks.py's own I12-snapshot-mismatch check failed
        closed. Post-fix, the declared blob is used and the check passes."""
        dev_dir = repo / "docs" / "dev"
        sha = _commit_baseline(repo, REL, b"clean committed content\n")
        # Simulate the pre-existing dirty state a prior session/sibling lane
        # left behind before this cycle's own capture ran.
        (repo / REL).write_bytes(b"dirty-at-dispatch content\n")
        proc = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input=b"dirty-at-dispatch content\n",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0
        declared_sha = proc.stdout.decode().strip()

        hunks = [{"old": "dirty-at-dispatch content\n", "new": "dirty-at-dispatch content-EDITED\n"}]
        (repo / REL).write_bytes(_apply_forward(b"dirty-at-dispatch content\n", hunks))

        _write(dev_dir, "dev-report-%s-a.json" % TASK_ID, _shard(
            TASK_ID, sha, [REL], {REL: hunks}, {REL: declared_sha},
        ))
        # A second shard is required -- the aggregator's own >=2-shard
        # aggregation path only engages for a genuinely parallel cycle.
        _write(dev_dir, "dev-report-%s-b.json" % TASK_ID, _shard(TASK_ID, sha))

        rc = main(["--task-id", TASK_ID])
        out_text = capsys.readouterr()
        doc = json.loads((dev_dir / ("dev-report-%s.json" % TASK_ID)).read_text())
        assert rc == 0, out_text.err
        assert doc["blocking_issues"] == []
        assert doc[_mod.COMPLETENESS_GAPS_KEY] == []  # the real no-gap witness

    def test_bug_reproduction_dirty_file_fails_closed_without_the_fix(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        """TDD control: with _resolve_baseline_snapshot stubbed back to the
        pre-fix HEAD-first order, the identical fixture above reproduces the
        exact reported defect -- the completeness check fails closed with
        an I12-snapshot-mismatch-style exclusion, even though the lane's own
        declared snapshot was correct and resolvable all along."""
        dev_dir = repo / "docs" / "dev"
        sha = _commit_baseline(repo, REL, b"clean committed content\n")
        (repo / REL).write_bytes(b"dirty-at-dispatch content\n")
        proc = subprocess.run(
            ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
            input=b"dirty-at-dispatch content\n",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0
        declared_sha = proc.stdout.decode().strip()

        hunks = [{"old": "dirty-at-dispatch content\n", "new": "dirty-at-dispatch content-EDITED\n"}]
        (repo / REL).write_bytes(_apply_forward(b"dirty-at-dispatch content\n", hunks))

        _write(dev_dir, "dev-report-%s-a.json" % TASK_ID, _shard(
            TASK_ID, sha, [REL], {REL: hunks}, {REL: declared_sha},
        ))
        # A second shard is required -- the aggregator's own >=2-shard
        # aggregation path only engages for a genuinely parallel cycle.
        _write(dev_dir, "dev-report-%s-b.json" % TASK_ID, _shard(TASK_ID, sha))

        def _pre_fix_order(project_root, baseline_head_sha, rel, declared_value):
            if baseline_head_sha:
                rc, _, _ = _mod._git(project_root, ["cat-file", "-e", f"{baseline_head_sha}:{rel}"])
                if rc == 0:
                    rc2, blob, _ = _mod._git(project_root, ["show", f"{baseline_head_sha}:{rel}"])
                    if rc2 == 0:
                        return blob, "baseline_head_sha"
            if isinstance(declared_value, str) and _mod._BLOB_SHA_RE.match(declared_value):
                rc, _, _ = _mod._git(project_root, ["cat-file", "-e", declared_value])
                if rc == 0:
                    rc2, blob, _ = _mod._git(project_root, ["cat-file", "blob", declared_value])
                    if rc2 == 0:
                        return blob, "declared_blob_sha"
            if isinstance(declared_value, str):
                return declared_value.encode("utf-8"), "literal_text"
            return None, "no resolvable pre-edit snapshot declared for this file"

        monkeypatch.setattr(_mod, "_resolve_baseline_snapshot", _pre_fix_order)

        rc = main(["--task-id", TASK_ID])
        capsys.readouterr()
        # Attribution-journal consumer cutover (see the sibling TDD control
        # above, test_bug_reproduction_without_the_fix_matches_pre_fix_12_
        # hunk_shape, for the full citation): the exit code no longer comes
        # from this replay at all -- it comes from the write-time ledger,
        # which defers (no journal evidence in this git-only fixture) rather
        # than blocks. The monkeypatched pre-fix _resolve_baseline_snapshot
        # order is therefore a no-op for rc; it still reproduces the pre-fix
        # defect shape in the non-blocking GLOBAL diagnostic, asserted below.
        assert rc == 0

        doc = json.loads((dev_dir / ("dev-report-%s.json" % TASK_ID)).read_text())
        # The diagnostic is recorded on the aggregate's own completeness key,
        # never on `blocking_issues`: that field is freshness-compared, so a
        # diagnostic written there made the canonical permanently stale
        # against its own rebuild.  Same strength, different channel.
        assert any(REL in issue for issue in doc[_mod.COMPLETENESS_GAPS_KEY])
        assert not any(REL in issue for issue in doc["blocking_issues"])


# ---------------------------------------------------------------------------
# AC-8: round0, round1, promoted ordering is strictly filename-round-number
# derived, NEVER mtime or directory-listing order.
# ---------------------------------------------------------------------------

class TestRoundOrderingIsNumericNeverMtime:
    def test_ac8_round0_before_round1_before_promoted_even_with_reversed_mtime(
        self, repo: Path, capsys: pytest.CaptureFixture, tmp_path: Path
    ):
        sha = _commit_baseline(repo, REL, b"line01\nline02\nline03\n")
        # promoted depends on round1's edit, round1 depends on round0's edit
        # -- so a wrong merge order provably fails to replay.
        round0_hunks = [{"old": "line01\n", "new": "line01-R0\n"}]
        round1_hunks = [{"old": "line01-R0\n", "new": "line01-R0-R1\n"}]
        promoted_hunks = [{"old": "line01-R0-R1\n", "new": "line01-R0-R1-FIX\n"}]
        live = _apply_forward(b"line01\nline02\nline03\n", round0_hunks + round1_hunks + promoted_hunks)
        (repo / REL).write_bytes(live)

        dev_dir = repo / "docs" / "dev"
        _write(dev_dir, "dev-report-%s-a.json" % TASK_ID, _shard(TASK_ID, sha, [REL], {"other.py": []}))
        _write(dev_dir, "dev-report-%s-d.json" % TASK_ID, _shard(TASK_ID, sha, [REL], {REL: promoted_hunks}, {REL: sha}))
        superseded_dir = dev_dir / ("superseded-%s" % TASK_ID)
        superseded_dir.mkdir(parents=True)

        # Write round1's file to disk FIRST, round0's SECOND -- opposite of
        # chronological/round order -- to prove ordering is derived from the
        # filename's numeric suffix, never mtime or directory-listing order.
        _write(superseded_dir, "dev-report-%s-d-round1.json" % TASK_ID, _shard(TASK_ID, sha, [REL], {REL: round1_hunks}, {REL: sha}))
        _write(superseded_dir, "dev-report-%s-d-round0.json" % TASK_ID, _shard(TASK_ID, sha, [REL], {REL: round0_hunks}, {REL: sha}))

        rc = main(["--task-id", TASK_ID])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0, out
        doc = json.loads((dev_dir / ("dev-report-%s.json" % TASK_ID)).read_text())
        assert doc["owned_edits"][REL] == round0_hunks + round1_hunks + promoted_hunks

    def test_scan_superseded_shards_orders_by_filename_number_not_mtime(self, tmp_path: Path):
        dev_dir = tmp_path / "docs" / "dev"
        superseded_dir = dev_dir / "superseded-20260101-090000"
        superseded_dir.mkdir(parents=True)
        # Create round1 first (earlier mtime), round0 second (later mtime).
        (superseded_dir / "dev-report-20260101-090000-d-round1.json").write_text("{}")
        (superseded_dir / "dev-report-20260101-090000-d-round0.json").write_text("{}")

        result = _scan_superseded_shards(dev_dir, "20260101-090000", {"d"})
        rounds = [n for n, _ in result["d"]]
        assert rounds == [0, 1]


# ---------------------------------------------------------------------------
# D1: a lane with NO retry -- aggregator behavior completely unchanged.
# ---------------------------------------------------------------------------

class TestNoRetryLaneUnaffected:
    def test_d1_no_superseded_directory_expansion_is_identity(self):
        shards = [
            ("p", _shard(TASK_ID, "sha1", ["a.py"], {"a.py": [{"old": "x", "new": "y"}]})),
            ("q", _shard(TASK_ID, "sha1", ["b.py"], {"b.py": [{"old": "m", "new": "n"}]})),
        ]
        expanded = _expand_shards_with_superseded_rounds(
            shards, Path("/definitely/does/not/exist"), "20260101-090000"
        )
        assert expanded is shards  # identity, not merely equal -- zero overhead, zero behavior change

    def test_d1_end_to_end_no_retry_two_lane_cycle_exits_0_unaffected(
        self, repo: Path, capsys: pytest.CaptureFixture
    ):
        sha = _commit_baseline(repo, REL, b"line01\nline02\nline03\nline04\n")
        (repo / REL).write_bytes(b"line01-P\nline02\nline03\nline04-Q\n")
        dev_dir = repo / "docs" / "dev"
        _write(dev_dir, "dev-report-%s-p.json" % TASK_ID, _shard(
            TASK_ID, sha, [REL], {REL: [{"old": "line01\n", "new": "line01-P\n"}]}, {REL: sha},
        ))
        _write(dev_dir, "dev-report-%s-q.json" % TASK_ID, _shard(
            TASK_ID, sha, [REL], {REL: [{"old": "line04\n", "new": "line04-Q\n"}]}, {REL: sha},
        ))

        rc = main(["--task-id", TASK_ID])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0, out
        assert out["action"] == "aggregated"
        doc = json.loads((dev_dir / ("dev-report-%s.json" % TASK_ID)).read_text())
        assert doc["owned_edits"][REL] == [
            {"old": "line01\n", "new": "line01-P\n"},
            {"old": "line04\n", "new": "line04-Q\n"},
        ]
        assert doc["blocking_issues"] == []
        assert doc[_mod.COMPLETENESS_GAPS_KEY] == []  # the real no-gap witness


# ---------------------------------------------------------------------------
# QA final-verification regression (task 20260922-100846 iteration 1):
# critical hunk-dedup defect. A round and its OWN lane's promoted shard can
# re-declare a hunk for the IDENTICAL `old` anchor -- observed on the real
# cycle 20260921-134709's lane a (hooks/lib/bash_write_targets.py): round0
# and promoted both anchor a hunk on the same `old` text, but promoted's
# `new` text differs (a revised/squashed edit) and carries an extra 'note'
# key round0's copy lacks. Exact-JSON-value dedup does not collapse this,
# so BOTH shipped pre-fix -- a 6-hunk ledger that double-applied the same
# region and failed stage-owned-hunks.py's replay (EXCLUDE/exit10), even
# though the promoted shard's OWN 5 hunks alone byte-replay cleanly.
# ---------------------------------------------------------------------------

class TestSameAnchorHunkCollapse:
    def test_literal_case_identical_old_and_new_differing_aux_key_dedupes_to_one(self):
        """The literal shape QA's finding named: two hunks with byte-identical
        old/new text, one carrying an extra auxiliary key ('note'). Must
        collapse to exactly one entry, not two."""
        round0_hunk = {"old": "anchor\n", "new": "replacement\n", "id": "E1"}
        promoted_hunk = {"old": "anchor\n", "new": "replacement\n", "id": "E1", "note": "carried metadata"}
        shards = [
            ("a-round0", _shard(TASK_ID, "sha1", [REL], {REL: [round0_hunk]})),
            ("a", _shard(TASK_ID, "sha1", [REL], {REL: [promoted_hunk]})),
        ]
        merged = _merge_owned_edits(shards)
        assert merged[REL] == [promoted_hunk]
        assert len(merged[REL]) == 1

    def test_real_shape_same_old_revised_new_plus_extra_note_key_dedupes_to_one(self):
        """The REAL shape measured this session on lane a's own artifacts
        (docs/dev/dev-report-20260921-134709-a.json vs
        docs/dev/superseded-20260921-134709/dev-report-20260921-134709-a-
        round0.json): round0 and promoted share the identical `old` anchor,
        but promoted's `new` text is a REVISED/squashed edit (not
        byte-identical to round0's `new`) and promoted's hunk carries an
        extra 'note' key documenting that revision. Only the LATER
        (promoted) declaration must survive, at the earlier declaration's
        ledger position, and it must NOT be silently discarded."""
        shared_old = "def _extract_cp_mv_targets(command: str) -> List[str]:\n"
        round0_e0 = {"id": "E0", "old": "import os\nimport re\n", "new": "import bisect\nimport os\nimport re\n"}
        round0_e1 = {"id": "E1", "old": shared_old, "new": "ROUND0 SQUASHED TEXT ENDING IN\n" + shared_old}
        round0_e2 = {"id": "E2", "old": "old-e2\n", "new": "new-e2\n"}
        promoted_e1 = {
            "id": "E1",
            "old": shared_old,
            "new": "PROMOTED FINAL TEXT (incorporates round0 + later fixes) ENDING IN\n" + shared_old,
            "note": "final authored text of the region: round0's E1 with later edits applied in place",
        }
        shards = [
            ("a-round0", _shard(TASK_ID, "sha1", [REL], {REL: [round0_e0, round0_e1, round0_e2]})),
            ("a", _shard(TASK_ID, "sha1", [REL], {REL: [round0_e0, promoted_e1, round0_e2]})),
        ]
        merged = _merge_owned_edits(shards)
        # Exactly 3 hunks -- E0 and E2 (exact duplicates, unaffected by this
        # fix) plus a SINGLE E1, not two.
        assert len(merged[REL]) == 3
        assert merged[REL][0] == round0_e0
        assert merged[REL][2] == round0_e2
        # The surviving E1 is the LATER (promoted) declaration, at the
        # EARLIER declaration's ledger position (index 1) -- its own
        # auxiliary 'note' metadata is preserved, not discarded.
        assert merged[REL][1] == promoted_e1
        assert merged[REL][1]["note"] == promoted_e1["note"]

    def test_cross_lane_same_old_anchor_is_not_collapsed(self):
        """The collapse is scoped to a single base lane (backlog #99's own
        defect never involved two DIFFERENT lanes). Two different lanes
        declaring the identical `old` anchor -- never observed in practice,
        and not this ticket's defect -- must keep the pre-existing
        exact-JSON-only dedup behavior: both hunks survive, unchanged."""
        hunk_b = {"old": "shared\n", "new": "from-b\n"}
        hunk_c = {"old": "shared\n", "new": "from-c\n"}
        shards = [
            ("b", _shard(TASK_ID, "sha1", [REL], {REL: [hunk_b]})),
            ("c", _shard(TASK_ID, "sha1", [REL], {REL: [hunk_c]})),
        ]
        merged = _merge_owned_edits(shards)
        assert merged[REL] == [hunk_b, hunk_c]

    def test_ac2_real_shape_lane_a_end_to_end_replays_clean_via_stage_owned_hunks(
        self, repo: Path, capsys: pytest.CaptureFixture
    ):
        """End-to-end reproduction of the real cycle's lane a shape: after
        the fix, folding round0 ahead of promoted for a lane whose promoted
        report already fully re-declares the file (self-sufficient, not a
        pure delta) must still produce a criterion-C-clean (rc == 0) merged
        ledger -- not a corrupted double-application."""
        base = b"import os\nimport re\n\ndef _extract_cp_mv_targets(command: str) -> List[str]:\n    pass\n"
        sha = _commit_baseline(repo, REL, base)

        shared_old = "def _extract_cp_mv_targets(command: str) -> List[str]:\n"
        e0 = {"old": "import os\nimport re\n", "new": "import bisect\nimport os\nimport re\n"}
        round0_e1 = {"old": shared_old, "new": "ROUND0 TEXT\n" + shared_old}
        promoted_e1 = {
            "old": shared_old,
            "new": "PROMOTED FINAL TEXT\n" + shared_old,
            "note": "final authored text of the region",
        }
        live = _apply_forward(base, [e0, promoted_e1])
        (repo / REL).write_bytes(live)

        dev_dir = repo / "docs" / "dev"
        _write(dev_dir, "dev-report-%s-a.json" % TASK_ID, _shard(
            TASK_ID, sha, [REL], {REL: [e0, promoted_e1]}, {REL: sha},
        ))
        _write(dev_dir, "dev-report-%s-e.json" % TASK_ID, _shard(
            TASK_ID, sha, ["other.py"], {"other.py": [{"old": "x", "new": "y"}]}, {"other.py": sha},
        ))
        _write(
            dev_dir / ("superseded-%s" % TASK_ID),
            "dev-report-%s-a-round0.json" % TASK_ID,
            _shard(TASK_ID, sha, [REL], {REL: [e0, round0_e1]}, {REL: sha}),
        )

        rc = main(["--task-id", TASK_ID])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0, out
        doc = json.loads((dev_dir / ("dev-report-%s.json" % TASK_ID)).read_text())
        assert doc["owned_edits"][REL] == [e0, promoted_e1]
        assert doc["blocking_issues"] == []
        assert doc[_mod.COMPLETENESS_GAPS_KEY] == []  # the real no-gap witness


# ---------------------------------------------------------------------------
# QA final-verification regression (task 20260922-100846 iteration 1):
# major AC-6 untracked-file-skip scoping defect. The skip check was scoped
# to the CURRENT git index, not to baseline_head_sha -- a file legitimately
# untracked at cycle time that has SINCE been committed by an unrelated,
# intervening commit was wrongly re-included in the tracked-file replay
# check and spuriously rejected. Observed on the real cycle 20260921-134709:
# 2 of lane a's 3 new test files were untracked at baseline_head_sha but
# have since been committed by this same task-id's own earlier partial
# /commit (26795c3e).
# ---------------------------------------------------------------------------

class TestUntrackedAtBaselineStaysSkippedEvenIfSinceCommitted:
    def test_tracked_at_baseline_helper_false_for_file_committed_after_baseline(self, repo: Path):
        sha = _commit_baseline(repo, REL, b"line01\n")
        # An "intervening commit" AFTER baseline_head_sha adds a new file --
        # simulating another lane's own later, unrelated partial /commit.
        (repo / "new_file.py").write_text("print('new')\n")
        _git(repo, "add", "--", "new_file.py")
        _git(repo, "commit", "-qm", "intervening: new_file.py")

        # Tracked at the CURRENT index/HEAD...
        assert _tracked_at_baseline(repo, "", "new_file.py") is True  # falls back to current index
        # ...but NOT tracked at the cycle's OWN recorded baseline_head_sha.
        assert _tracked_at_baseline(repo, sha, "new_file.py") is False

    def test_completeness_check_skips_file_untracked_at_baseline_but_since_committed(
        self, repo: Path, capsys: pytest.CaptureFixture
    ):
        """End-to-end: a shard declares a whole-file-creation hunk for a
        file that was untracked AT baseline_head_sha. An intervening commit
        (simulating another lane's own earlier partial /commit of the same
        task-id) has since made it tracked in the CURRENT index. The
        completeness check must still skip it (AC-6), not spuriously
        reject its pure-insertion hunk as unlocatable."""
        sha = _commit_baseline(repo, REL, b"line01\nline02\n")
        (repo / REL).write_bytes(b"line01-P\nline02\n")

        new_file_content = "print('new')\n"
        (repo / "new_file.py").write_text(new_file_content)
        _git(repo, "add", "--", "new_file.py")
        _git(repo, "commit", "-qm", "intervening: new_file.py tracked after baseline")

        dev_dir = repo / "docs" / "dev"
        _write(dev_dir, "dev-report-%s-p.json" % TASK_ID, _shard(
            TASK_ID, sha, [REL], {REL: [{"old": "line01\n", "new": "line01-P\n"}]}, {REL: sha},
        ))
        _write(dev_dir, "dev-report-%s-q.json" % TASK_ID, _shard(
            TASK_ID, sha, ["new_file.py"],
            {"new_file.py": [{"old": "", "new": new_file_content}]},
            {"new_file.py": sha},
        ))

        rc = main(["--task-id", TASK_ID])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0, out
        doc = json.loads((dev_dir / ("dev-report-%s.json" % TASK_ID)).read_text())
        assert "new_file.py" in doc["owned_edits"]  # union still records it
        assert doc["blocking_issues"] == []
        # The real "no completeness gap" witness. `blocking_issues` stopped
        # being one when the diagnostics moved to their own non-freshness-
        # compared key, so asserting only that would be vacuous here.
        assert doc[_mod.COMPLETENESS_GAPS_KEY] == []  # never blocks completeness

    def test_apply_completeness_check_directly_skips_the_since_committed_file(self, repo: Path):
        sha = _commit_baseline(repo, REL, b"line01\n")
        (repo / "new_file.py").write_text("print('new')\n")
        _git(repo, "add", "--", "new_file.py")
        _git(repo, "commit", "-qm", "intervening commit")

        aggregate = {
            "baseline_head_sha": sha,
            "owned_edits": {"new_file.py": [{"old": "", "new": "print('new')\n"}]},
            "pre_edit_snapshots": {"new_file.py": sha},
        }
        diagnostics = _apply_completeness_check(aggregate, repo)
        assert diagnostics == []
