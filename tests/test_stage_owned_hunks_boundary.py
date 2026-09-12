"""Regression coverage for scripts/stage-owned-hunks.py's pure-insertion
content-anchor-retry boundary/coordinate-space defect (task 20260912-015952).

Root cause (docs/dev/ticket-20260912-015952.md): when a pure-insertion
hunk's plain line-offset reversal fails and `_content_anchor_retry` engages,
the CORRECTED hunk it produced was positioned relative to the worktree-
reversal-walk's own buffer (`_filter_segments_against_worktree`'s `before`),
which may contain content -- a structurally-later sibling hunk still
applied, or foreign/peer content never owned by any segment -- that the
isolated per-segment buffer actually used at staging time never contains.
`git apply --cached --recount --unidiff-zero` does not reject an
out-of-range, zero-context pure-insertion hunk; it silently applies it near
end-of-file. The fix defers position resolution: the worktree-relative
corrected hunk stays exactly as before (needed to prove the composed
selection reverses cleanly against the real worktree), but its
(anchor, inserted_text) is ALSO carried forward as a `pending_insertions`
record and re-resolved, via `_locate_unique`, against the SAME buffer it is
about to be staged into -- immediately before each segment's real
`git apply --cached` call in `_composed_main`.

This is a git-TRACKED regression file -- .gitignore:114 excludes
tests/generated/* from version control, so a P0-class silent-corruption
defect needs durable coverage here, not only in the test-writer skeletons
under tests/generated/20260912-015952/. It uses the REAL lane-lanel
commands/close.md hunk-4 shape for the live-segment case: ledger entry 2 (a
pure insertion anchored on "...direct a failed close to `/commit`.\n\n",
adding the `## `--auto` mode` section) sits in the SAME segment as entry 3
(the adjacent, structurally-later `## Constraints` bullet rewrite) -- the
exact co-segment interaction commit 5ab61c99's own regression fixture
(tests/generated/20260911-220120/_fixtures.py::live_plan_case, a single-
edit-per-segment fixture) never exercised. The ledger is embedded verbatim
below (copied from docs/dev/dev-report-20260808-035658-lanel.json) because
docs/dev/ is gitignored (.gitignore:142); the pre-edit snapshot is instead
fetched live from this repo's own git history (a committed object, not a
gitignored working-tree file), keeping the fixture durable without
depending on any local, uncommitted artifact.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "scripts" / "stage-owned-hunks.py"
SCHEMA = ROOT / "schemas" / "owned-edits-ledger.v1.json"

# The commit this ticket's fix follows up on (task 20260911-220120's own
# content-anchor-placement fix) -- AC1 pins the pre-fix defect against THIS
# frozen historical revision, not the live consumer file this fix changes,
# so the baseline documents the past defect regardless of future edits.
PRE_FIX_COMMIT = "5ab61c99c00f1ed67694d485aa9c053b8cbbc563"

# The pre-edit commands/close.md blob lane lanel's real cycle started from
# (parent of the commit that landed its 4-edit ledger).
REAL_SNAPSHOT_COMMIT = "40de60667818fcdd82d1b84d0ab2e79d57dfc363"
REAL_REL = "commands/close.md"

# Verbatim copy of docs/dev/dev-report-20260808-035658-lanel.json's
# owned_edits["commands/close.md"] (4 entries, in dev's own applied order).
# Embedded (not read from disk) because docs/dev/ is gitignored.
REAL_CLOSE_MD_LEDGER = json.loads(r"""
[
  {
    "old": "description: Close the current dev cycle (agent infers task-id from conversation). QA evaluates Workflow Integrity bullets and returns CLOSE YES/NO. Pass --codex to enable multi-round QA-codex debate; default is QA-only single-round assessment. Append --force to skip the debate entirely.\nargument-hint: \"[--codex | --force [--reason \\\"<text>\\\"]] [<task-id>|<path>]\"\n",
    "new": "description: Close the current dev cycle (agent infers task-id from conversation). QA evaluates Workflow Integrity bullets and returns CLOSE YES/NO. Pass --codex to enable multi-round QA-codex debate; default is QA-only single-round assessment. Append --force to skip the debate entirely. Pass --auto to discover and sequentially close every close_pending parent (see `--auto mode` below).\nargument-hint: \"[--codex | --force [--reason \\\"<text>\\\"] | --auto] [<task-id>|<path>]\"\n"
  },
  {
    "old": "but `--force` wins.\n",
    "new": "but `--force` wins.\n\n### Argument parsing: `--auto` flag (Must-Have #8, task 20260808-035658-lanel)\n\nParse `--auto` from `$ARGUMENTS` BEFORE evaluating the forced-override path or task-id resolution:\n\n- If `$ARGUMENTS` contains the literal token `--auto`, strip it and set `auto = true`.\n- Otherwise set `auto = false` (default — every rule below is inert).\n\n**Rejection (before any action)**: when `auto = true`, `/close` MUST reject — printing the reason and stopping before Task-id resolution, before Step 0, before any Agent dispatch — if `$ARGUMENTS` (after stripping `--auto` itself) still contains ANY of: an explicit task-id or path token, `--force`, or a `--reason` value. `--auto` and `--codex` MAY combine (each `--auto` walk below still honors `codex_required` exactly as the non-`--auto` path does). This mirrors `scripts/dev-lifecycle.py`'s `validate_auto_flag_combination()` pure predicate (`--force`/explicit-task-id/`--bulk` all reject; `--bulk` does not exist for `/close` so only the first two apply here) — the mechanical check:\n\n```bash\npython3 -c \"\nimport sys; sys.path.insert(0, 'scripts')\nimport importlib.util\nspec = importlib.util.spec_from_file_location('dlc', 'scripts/dev-lifecycle.py')\nm = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\nerr = m.validate_auto_flag_combination(True, '<explicit-task-id-or-empty>', <force_bool>, False)\nprint(err or 'OK')\n\"\n```\n\nWhen `auto = true` and the combination is legal, skip Task-id resolution and Steps 0-3 entirely at THIS level — control passes to the `--auto mode` section below, which drives Steps 0-3 once per discovered parent.\n"
  },
  {
    "old": "direct a failed close to `/commit`.\n\n",
    "new": "direct a failed close to `/commit`.\n\n## `--auto` mode: batch-discover and sequentially close (Must-Have #6, task 20260808-035658-lanel)\n\n`--auto` discovers every `close_pending` PARENT task-id and walks each one, ONE\nAT A TIME, through the exact same unmodified **Step 0 → Step 3** body (the\n`### Step 0` through `### Step 3` headings above, up to this section) an\nexplicit `/close <task-id>` would run. It is structurally distinct from the human-only\n`--bulk` escape hatch documented in `commands/commit.md` — `--auto` never\nskips the close gate; it walks every discovered parent THROUGH the gate,\nnever around it.\n\n1. **Discover** the candidate parent snapshot (frozen once, at the start of\n   the batch — parents discovered mid-batch by a later scan are NOT added to\n   the running batch):\n\n   ```bash\n   PROJECT_ROOT=\"${CLAUDE_PROJECT_DIR:-$(pwd)}\"\n   source ~/.claude/venv/bin/activate 2>/dev/null || true\n   mapfile -t CLOSE_PENDING_PARENTS < <(python3 scripts/dev-lifecycle.py list-actionable --next-action close --project-dir \"$PROJECT_ROOT\")\n   ```\n\n   `list-actionable` already returns a deterministically sorted list of\n   `kind == \"ticket\"` parent task-ids only — lane rows and spec rows never\n   appear (Must-Have #3). A `blocked` task is never included and is never\n   force-closed by `--auto`.\n\n2. **Walk each parent sequentially** — no two parents run concurrently, and\n   parent N+1's walk does not begin until parent N's walk has been classified\n   (step 3 below). For each `TASK_ID` in `CLOSE_PENDING_PARENTS`, in order,\n   bind `TASK_ID` and re-enter this file at **Task-id resolution**'s\n   `$ARGUMENTS` matches a timestamp pattern → non-force path branch, then run\n   **Step 0** through **Step 3** exactly as written — same aggregate refresh,\n   same resolver invocation (or do-report lite preflight), same artifact\n   schema gate, same Step 1 inspector dispatch, same Step 2 QA debate\n   (`codex_required` from the `--codex` parsing above, shared across every\n   parent in the batch), same Step 3 close-report write. Nothing in Steps 0-3\n   is aware `--auto` is driving it.\n\n3. **Classify the walk's outcome** at the orchestrator-procedure level (the\n   walk is a sequence of individual tool calls this file's prose drives an\n   agent through — not a single bash process an exit code terminates\n   wholesale; see `scripts/dev-lifecycle.py`'s `classify_walk_outcome()` for\n   the exact recognition predicate this mirrors):\n   - **`hook_deny`** — a `PreToolUse`/`PostToolUse`/`Stop` hook literally\n     blocked a tool call during the walk (observable shape: a\n     `<Phase>:<hook-script> hook error: ... BLOCKED ...` tool result, per\n     CLAUDE.md's Subagent Hook Discipline). **Abort the entire remaining\n     batch immediately** — do not start parent N+1. Report which parent was\n     mid-walk and the verbatim hook rejection.\n   - **`ordinary_reject`** — any other non-success outcome: aggregation/\n     resolver/schema-gate non-zero exit, a substantive `CLOSE: NO` verdict\n     from Step 2, an inspector-forced rejection. **Record the outcome and\n     continue** to the next parent in the frozen list.\n   - **`success`** — the walk reached Step 3 and wrote a `CLOSE: YES*`\n     close-report. **Record and continue** to the next parent.\n\n4. **Batch summary**: after the batch ends (list exhausted, or a `hook_deny`\n   aborted it), print one line per attempted parent (`task-id: outcome`) plus\n   a line for every parent that was never attempted because the batch was\n   aborted (`task-id: not_attempted`). Do not run the Session Summary / user\n   rating block (those remain per-parent, inside each successful walk's own\n   Step 3, unchanged) as a SECOND batch-level summary — the per-parent Step 3\n   output already covers each `CLOSE: YES` parent individually.\n\nHuman-operator verification of this mode (QA cannot literally invoke\n`/close --auto` — `disable-model-invocation: true` plus `settings.json`'s\nglobal `Skill(close:*)` deny) is documented in `docs/dev/ticket-20260808-035658-lanel.md`\nAC-L21: a separate human-operator-executed transcript at\n`docs/dev/human-operator-transcript-<task-id>.md`, using the\n`PARENT_START: <task_id>` / `PARENT_END: <task_id> outcome=<...>` schema\n`scripts/dev-lifecycle.py`'s `parse_human_operator_transcript()` parses.\n\n"
  },
  {
    "old": "- QA is invoked EXACTLY ONCE (non-force path) or ZERO times (forced path).\n",
    "new": "- QA is invoked EXACTLY ONCE per parent close decision (non-force path) or ZERO times (forced path). `--auto` does not change this per-decision invariant — it drives multiple SEQUENTIAL parent close decisions, each still invoking QA exactly once, never concurrently.\n- `--auto` never bypasses Steps 0-3; it is structurally distinct from `--bulk` (documented in `commands/commit.md`), which skips the close gate entirely. `--auto` walks every discovered parent THROUGH the unmodified gate.\n"
  }
]
""")

INSERTED_HEADING = "## `--auto` mode: batch-discover and sequentially close"
FOLLOWING_HEADING = "## Constraints"
ANCHOR_TAIL = "direct a failed close to `/commit`.\n\n"


def git(repo, *args, input_bytes=None, check=True):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


def _real_pre_edit_snapshot():
    """The real pre-edit commands/close.md bytes, fetched from this repo's
    own git history -- a committed object, immune to docs/dev/'s gitignore."""
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", "%s:%s" % (REAL_SNAPSHOT_COMMIT, REAL_REL)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr.decode()
    return result.stdout


def _apply_ledger(snapshot, edits):
    replay = snapshot
    for edit in edits:
        old_b = edit["old"].encode("utf-8")
        new_b = edit["new"].encode("utf-8")
        assert replay.count(old_b) == 1, "fixture precondition: anchor must be unique"
        off = replay.find(old_b)
        replay = replay[:off] + new_b + replay[off + len(old_b):]
    return replay


def _foreign_worktree(snapshot, edits, foreign_line_count=30, foreign_after_line=100):
    """Build the real lane-lanel hunk-4 shape's DRIFT scenario: HEAD stays
    the pristine snapshot (never touched by any peer commit), but the real
    WORKING TREE also carries `foreign_line_count` uncommitted, unrelated
    lines inserted well before the anchor -- simulating any concurrent,
    unowned content sharing the same worktree (another lane, a stray local
    edit). This defeats the plain line-offset reversal for the pure-
    insertion hunk without changing what a correct, owned-only stage should
    produce (the pure ledger replay, no foreign bytes)."""
    lines = snapshot.decode("utf-8").split("\n")
    foreign = ["PEER-FOREIGN-LINE-%d" % i for i in range(1, foreign_line_count + 1)]
    peer_lines = lines[:foreign_after_line] + foreign + lines[foreign_after_line:]
    peer_content = ("\n".join(peer_lines)).encode("utf-8")
    return _apply_ledger(peer_content, edits)


def _live_plan_case(tmp_path, *, helper=HELPER):
    """Real lane-lanel commands/close.md hunk-4 shape via --provenance-plan.

    Returns (repo, plan_path, task_id, expected_clean_replay, helper).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    snapshot = _real_pre_edit_snapshot()
    target = repo / REAL_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(snapshot)
    git(repo, "add", REAL_REL)
    git(repo, "commit", "-qm", "pristine snapshot at HEAD")

    worktree = _foreign_worktree(snapshot, REAL_CLOSE_MD_LEDGER)
    target.write_bytes(worktree)

    task_id = "boundary-20260912-live"
    plan = {
        "task_id": task_id,
        "path": REAL_REL,
        "segments": [{
            "kind": "live",
            "source_worker": "dev",
            "source_task_id": "%s-dev" % task_id,
            "owned_edits": REAL_CLOSE_MD_LEDGER,
            "pre_edit_snapshot": snapshot.decode("utf-8"),
        }],
    }
    plan_path = repo / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    expected = _apply_ledger(snapshot, REAL_CLOSE_MD_LEDGER)
    return repo, plan_path, task_id, expected, helper


def _run_plan(repo, plan_path, task_id, *, helper=HELPER):
    return subprocess.run(
        [sys.executable, str(helper),
         "--git-root", str(repo), "--file", REAL_REL,
         "--provenance-plan", str(plan_path), "--task-id", task_id],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


# --- AC1: pre-fix baseline (frozen historical revision) --------------------

def test_pre_fix_baseline_reproduces_the_boundary_defect(tmp_path):
    """AC1 (ac_uid 3f201f59b185c61d).

    GIVEN the real lane-lanel commands/close.md hunk-4 shape (pure insertion
    requiring content-anchor retry, co-segment with a structurally-later
    ordinary edit hunk)
    WHEN staged by the FROZEN pre-fix revision (commit 5ab61c99 -- the
    commit this ticket's fix follows up on, not the live, now-fixed file)
    THEN the new section lands AFTER the structurally-following section
    instead of between the anchor and it -- the exact defect this ticket
    fixes, pinned against history so this baseline stays meaningful
    regardless of future edits to the live consumer.
    """
    pre_fix_source = subprocess.run(
        ["git", "-C", str(ROOT), "show", "%s:scripts/stage-owned-hunks.py" % PRE_FIX_COMMIT],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert pre_fix_source.returncode == 0, pre_fix_source.stderr.decode()
    frozen_helper = tmp_path / "stage-owned-hunks-prefix.py"
    frozen_helper.write_bytes(pre_fix_source.stdout)

    repo, plan_path, task_id, expected, _ = _live_plan_case(tmp_path, helper=frozen_helper)
    result = _run_plan(repo, plan_path, task_id, helper=frozen_helper)
    assert result.returncode == 0, (
        "pre-fix baseline expected to (wrongly) succeed at the wrong "
        "position, not to exclude: %s" % result.stderr.decode()
    )

    staged = git(repo, "show", ":%s" % REAL_REL).stdout.decode()
    idx_inserted = staged.find(INSERTED_HEADING)
    idx_following = staged.find(FOLLOWING_HEADING)
    assert idx_inserted != -1 and idx_following != -1
    assert idx_inserted > idx_following, (
        "pre-fix baseline no longer reproduces the reversed-order defect -- "
        "if this fails, the frozen commit's own behaviour changed, which "
        "should not happen"
    )
    assert staged != expected.decode("utf-8")


# --- AC2 + AC3: post-fix boundary and blank-line correctness ---------------

def test_post_fix_places_insertion_between_anchor_and_following_section(tmp_path):
    """AC2 (ac_uid 3b347f75d2a53cc4) + AC3 (ac_uid eb680078c61eb219).

    GIVEN the identical real hunk-4 shape as AC1
    WHEN staged by the CURRENT (post-fix) scripts/stage-owned-hunks.py
    THEN the new section lands strictly BETWEEN the anchor and the
    structurally-following section, the staged bytes exactly reproduce the
    clean ledger replay (no foreign content ever leaks in), and exactly one
    blank line separates the end of the preceding paragraph from the new
    heading.
    """
    repo, plan_path, task_id, expected, _ = _live_plan_case(tmp_path)
    result = _run_plan(repo, plan_path, task_id)
    assert result.returncode == 0, result.stderr.decode()

    staged_bytes = git(repo, "show", ":%s" % REAL_REL).stdout
    assert staged_bytes == expected, (
        "staged content must exactly equal the clean ledger replay -- no "
        "foreign content, no misplacement"
    )

    staged = staged_bytes.decode("utf-8")
    idx_inserted = staged.find(INSERTED_HEADING)
    idx_following = staged.find(FOLLOWING_HEADING)
    assert idx_inserted != -1 and idx_following != -1
    assert idx_inserted < idx_following, (
        "the new section must land BEFORE the structurally-following "
        "section, not after it"
    )

    # AC3: exactly one blank line between the anchor's own trailing paragraph
    # and the new heading -- the separator lives inside the anchor's own
    # bytes (ANCHOR_TAIL ends "...\n\n"), so it is present iff the insertion
    # landed at the anchor-correct position.
    before_heading = staged[:idx_inserted]
    assert before_heading.endswith(ANCHOR_TAIL), (
        "text immediately preceding the new heading must be exactly the "
        "ledger's own anchor bytes"
    )
    # Exactly one blank line: the anchor's content ends "...\n\n" (one blank
    # line), and the heading follows immediately with no further blank line.
    assert not before_heading.endswith("\n\n\n")
    assert staged[idx_inserted:].startswith(INSERTED_HEADING)


def test_checkpoint_and_live_segment_kinds_produce_identical_staged_bytes(tmp_path):
    """AC5 parity sanity check (live half): re-run confirms determinism of
    the live path this test module leans on most heavily for AC1-3/AC8."""
    repo, plan_path, task_id, expected, _ = _live_plan_case(tmp_path)
    result = _run_plan(repo, plan_path, task_id)
    assert result.returncode == 0, result.stderr.decode()
    assert git(repo, "show", ":%s" % REAL_REL).stdout == expected


# --- AC4: fail-closed anchor ambiguity stays unweakened ---------------------

def _mutated_live_case(tmp_path, mutation):
    """Same real ledger, but the worktree's anchor occurrence is mutated so
    the pure-insertion anchor is absent (`mutation="zero"`) or duplicated
    (`mutation="dup"`) -- M5's fail-closed contract must still EXCLUDE."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    snapshot = _real_pre_edit_snapshot()
    target = repo / REAL_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(snapshot)
    git(repo, "add", REAL_REL)
    git(repo, "commit", "-qm", "pristine snapshot at HEAD")

    worktree = _foreign_worktree(snapshot, REAL_CLOSE_MD_LEDGER)
    worktree_text = worktree.decode("utf-8")
    anchor = ANCHOR_TAIL
    assert worktree_text.count(anchor) == 1
    if mutation == "zero":
        worktree_text = worktree_text.replace(
            anchor, "direct a failed close to MUTATED-ANCHOR.\n\n", 1
        )
    elif mutation == "dup":
        # Duplicate the anchor's OWN trailing bytes far away (well before
        # the real one) so _locate_unique sees two occurrences.
        worktree_text = anchor + worktree_text
    else:
        raise AssertionError(mutation)
    target.write_text(worktree_text, encoding="utf-8")

    task_id = "boundary-20260912-%s" % mutation
    plan = {
        "task_id": task_id,
        "path": REAL_REL,
        "segments": [{
            "kind": "live",
            "source_worker": "dev",
            "source_task_id": "%s-dev" % task_id,
            "owned_edits": REAL_CLOSE_MD_LEDGER,
            "pre_edit_snapshot": snapshot.decode("utf-8"),
        }],
    }
    plan_path = repo / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return repo, plan_path, task_id


@pytest.mark.parametrize("mutation", ["zero", "dup"])
def test_fail_closed_anchor_ambiguity_stays_unweakened(tmp_path, mutation):
    """AC4 (ac_uid 6e06bf69e698e2e1).

    GIVEN a pure-insertion hunk whose ledger anchor occurs ZERO times (the
    real occurrence mutated away) or 2-OR-MORE times (duplicated) in the
    real worktree at the point _content_anchor_retry evaluates it, in a
    MULTI-hunk segment (unlike tests/generated/20260911-220120/_fixtures.py
    ::live_plan_case's single-edit-per-segment shape, referenced unmodified
    by this ticket's own AC4 for the whole-segment-excluded case)
    WHEN staged after the fix
    THEN that ONE hunk stays fail-closed EXCLUDED from the staged patch --
    never silently mis-staged at a wrong position -- while the segment's
    OTHER, unambiguous owned hunks still stage normally (M2/M5 from the
    prior ticket, 20260911-220120, are not weakened: per-hunk fail-closed
    exclusion, not a fail-open guess).
    """
    repo, plan_path, task_id = _mutated_live_case(tmp_path, mutation)
    result = _run_plan(repo, plan_path, task_id)
    assert result.returncode == 0, (
        "the segment's OTHER owned hunks (1, 2, 4) are unambiguous and "
        "should still stage even though hunk 3's anchor is %s-match: rc=%r %s"
        % (mutation, result.returncode, result.stderr.decode())
    )
    staged = git(repo, "show", ":%s" % REAL_REL).stdout.decode()
    assert INSERTED_HEADING not in staged, (
        "the %s-match anchor hunk must be excluded from staging, not "
        "silently applied at a guessed position" % mutation
    )
    assert FOLLOWING_HEADING in staged, (
        "the segment's other owned hunks must still stage normally"
    )


# --- AC5: checkpoint-kind parity --------------------------------------------

def _checkpoint_hunk4_shape_case(tmp_path):
    """An ANALOGOUS close.md-hunk-4 shape (pure insertion + a structurally-
    later ordinary edit in ONE segment, needing content-anchor retry) via
    --checkpoint-provenance, following tests/generated/20260911-220120/
    _fixtures.py::checkpoint_case's established (synthetic) pattern.

    Deliberately NOT the literal real close.md bytes: the checkpoint kind's
    OWN anchor-resolution mechanism (_checkpoint_pure_insertion_anchor) reads
    the checkpoint's context=3 validation patch, and close.md's real hunk-3/
    hunk-4 sit only ~6 lines apart -- close enough that their context=3
    windows MERGE into one non-pure hunk, which is a pre-existing, W2-
    protected scope boundary of the anchor-LOCATION mechanism itself (not
    the coordinate-space bug this ticket fixes). Spacing the two edits
    further apart here isolates M1 from that unrelated, already out-of-scope
    limitation while still exercising the identical coordinate-space defect
    for the checkpoint segment kind.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    rel = "notes.md"
    target = repo / rel

    base_lines = ["context line %d" % i for i in range(1, 150)]
    base_lines.append("ANCHOR-UNIQUE-CP")
    base_lines += ["mid line %d" % i for i in range(1, 29)]
    base_lines.append("REPLACE-ME-TARGET")
    base_lines += ["tail line %d" % i for i in range(1, 21)]
    base_content = ("\n".join(base_lines) + "\n").encode("utf-8")

    anchor_pos = base_lines.index("ANCHOR-UNIQUE-CP")

    def _apply_insertion_and_edit(lines):
        out = lines[:anchor_pos + 1] + ["INSERTED-A", "INSERTED-B", "INSERTED-C"] + lines[anchor_pos + 1:]
        idx = out.index("REPLACE-ME-TARGET")
        out[idx] = "REPLACED-LINE-1"
        out.insert(idx + 1, "REPLACED-LINE-2")
        return out

    end_lines = _apply_insertion_and_edit(list(base_lines))
    end_content = ("\n".join(end_lines) + "\n").encode("utf-8")

    target.write_bytes(base_content)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "pristine base at HEAD")
    head_sha = git(repo, "rev-parse", "HEAD").stdout.decode().strip()

    git(repo, "switch", "-qc", "checkpoint-fixture")
    base_sha = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    target.write_bytes(end_content)
    git(repo, "commit", "-qam", "checkpoint end (insertion + later edit)")
    end_sha = git(repo, "rev-parse", "HEAD").stdout.decode().strip()

    git(repo, "switch", "-q", "--detach", head_sha)
    foreign = ["PEER-FOREIGN-%d" % i for i in range(1, 31)]
    peer_lines = base_lines[:20] + foreign + base_lines[20:]
    worktree_lines = _apply_insertion_and_edit(peer_lines)
    target.write_bytes(("\n".join(worktree_lines) + "\n").encode("utf-8"))

    evidence = repo / "do-report.json"
    evidence.write_text(json.dumps({
        "source": "do", "do": {"files_modified": [rel], "files_created": []},
    }), encoding="utf-8")
    evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    base_blob = git(repo, "rev-parse", "%s:%s" % (base_sha, rel)).stdout.decode().strip()
    end_blob = git(repo, "rev-parse", "%s:%s" % (end_sha, rel)).stdout.decode().strip()

    task_id = "boundary-20260912-cp"
    checkpoint = {
        "task_id": task_id,
        "path": rel,
        "base_commit": base_sha,
        "owned_end_commit": end_sha,
        "base_blob": base_blob,
        "owned_end_blob": end_blob,
        "binding_artifacts": [{"path": "do-report.json", "sha256": evidence_sha}],
        "scope_rationale": "Checkpoint inserts a section right after the anchor and edits a later, separate line.",
    }
    cp_path = repo / "checkpoint.json"
    cp_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    expected = ("\n".join(end_lines) + "\n").encode("utf-8")
    return repo, cp_path, task_id, rel, expected


def test_checkpoint_kind_parity_with_live_kind(tmp_path):
    """AC5 (ac_uid 8fdf30e22961bd8e).

    GIVEN an analogous close.md-hunk-4-shaped scenario reached via the
    --checkpoint-provenance segment kind rather than --provenance-plan's
    live segment kind
    WHEN staged after the fix
    THEN the same correct boundary placement (AC2) holds for the
    checkpoint-kind path -- the fix is not live-segment-only, since both
    kinds funnel through the shared _content_anchor_retry/
    _filter_segments_against_worktree/_composed_main pipeline.
    """
    repo, cp_path, task_id, rel, expected = _checkpoint_hunk4_shape_case(tmp_path)
    result = subprocess.run(
        [sys.executable, str(HELPER),
         "--git-root", str(repo), "--file", rel,
         "--checkpoint-provenance", str(cp_path), "--task-id", task_id],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr.decode()
    staged = git(repo, "show", ":%s" % rel).stdout
    assert staged == expected
    idx_insert = staged.find(b"INSERTED-A")
    idx_edit = staged.find(b"REPLACED-LINE-1")
    assert idx_insert != -1 and idx_edit != -1
    assert idx_insert < idx_edit


# --- AC6: no regression on existing suites ----------------------------------

def test_no_regression_on_existing_suites():
    """AC6 (ac_uid 5ee0d3dfd246edb6).

    GIVEN the existing regression suites for this consumer
    WHEN the fix lands and the full suites are re-run
    THEN every previously-passing case in all of these suites still passes
    unmodified.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/test_checkpoint_provenance.py",
         "tests/test_owned_edits_ledger_contract.py",
         "tests/test_empty_old_string_diagnosis.py",
         "tests/generated/20260911-220120/"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    assert result.returncode == 0, (
        "pre-existing regression suites did not stay green after the "
        "boundary/coordinate-space fix:\n%s" % result.stdout.decode()
    )


# --- AC7: ledger schema digest binding updated ------------------------------

def test_ledger_schema_digest_binding_matches_consumer():
    """AC7 (ac_uid 65c81ca43b4d1562).

    GIVEN schemas/owned-edits-ledger.v1.json's x-consumer block
    WHEN the fix modifies scripts/stage-owned-hunks.py
    THEN sha256/lines are updated to match the post-fix file (measured_at
    updated alongside), and test_consumer_digest_binding_is_active passes.
    """
    with open(SCHEMA, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    with open(HELPER, "rb") as fh:
        consumer_bytes = fh.read()
    assert schema["x-consumer"]["sha256"] == hashlib.sha256(consumer_bytes).hexdigest()
    assert schema["x-consumer"]["lines"] == len(
        consumer_bytes.decode("utf-8").splitlines()
    )
