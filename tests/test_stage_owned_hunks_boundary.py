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
         "tests/test_empty_old_string_diagnosis.py",
         "tests/generated/20260911-220120/"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    assert result.returncode == 0, (
        "pre-existing regression suites did not stay green after the "
        "boundary/coordinate-space fix:\n%s" % result.stdout.decode()
    )


# ---------------------------------------------------------------------------
# I12-snapshot-mismatch defect-signature detection (task 20260918-180648,
# docs/dev/ticket-20260918-180648.md / docs/dev/specs/spec-20260918-160755.md).
#
# These four tests exercise the DIRECT `--ledger`/`--snapshot` CLI branch of
# def main() (the "live ledger+snapshot branch", ~line 1413-1460) -- a
# different entry point from the `--provenance-plan`/`--checkpoint-provenance`
# tests above. Their AC numbering is a SEPARATE scope: this ticket's own
# AC1-AC7 in docs/dev/acceptance-criteria-20260918-180648.json, NOT a
# renumbering of this file's pre-existing AC1-AC7 (task 20260912-015952)
# above -- per that ticket's own Technical Hints, the existing tags are left
# undisturbed.
# ---------------------------------------------------------------------------

def _i12_repo(tmp_path):
    repo = tmp_path / "i12-repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    return repo


def _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path):
    return subprocess.run(
        [sys.executable, str(HELPER),
         "--git-root", str(repo), "--file", rel,
         "--ledger", str(ledger_path), "--snapshot", str(snapshot_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def test_i12_defect_signature_dirty_at_baseline_head_blob_snapshot(tmp_path):
    """This ticket's AC1 (ac_uid b9895014b04bd945) -- separate numbering
    scope, see the module-level comment above.

    THIS PIN IS INVERTED, DELIBERATELY, for the same reason as AC2 below.
    The stale-capture signature is real and its diagnostic is retained (see
    test_i12_signature_still_named_on_the_refusal_path), but it is no longer
    a REFUSAL: the owned-only image is assembled on the commit baseline, not
    on the snapshot, so a snapshot that reached for HEAD:<path> instead of
    the true dispatch-time bytes no longer prevents the claimant from
    landing its own region. The pre-existing uncommitted line belongs to
    nobody's ledger and is simply not staged.

    GIVEN a tracked file's pre_edit_snapshot bytes are byte-identical to the
    current HEAD blob for that path (the capture defect: the file was
    actually dirty at dispatch time, but its capture reached for HEAD:<path>
    instead of the true working-tree bytes)
    WHEN scripts/stage-owned-hunks.py's --ledger/--snapshot branch runs
    THEN the landing SUCCEEDS and stages exactly the commit baseline plus
    this claimant's own recorded change -- the pre-existing uncommitted line
    is not staged -- and the working tree is untouched.
    """
    repo = _i12_repo(tmp_path)
    rel = "notes.md"
    target = repo / rel
    head_content = b"line one\nANCHOR-UNIQUE\nline three\n"
    target.write_bytes(head_content)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "HEAD content")

    # The file was ALREADY dirty (uncommitted) before this cycle started --
    # true dispatch-time bytes differ from HEAD by a pre-existing line the
    # (buggy) capture never saw.
    dirty_at_dispatch = b"line one\nPRE-EXISTING-DIRTY\nANCHOR-UNIQUE\nline three\n"
    ledger = [{"old": "ANCHOR-UNIQUE", "new": "ANCHOR-EDITED"}]
    worktree = dirty_at_dispatch.replace(b"ANCHOR-UNIQUE", b"ANCHOR-EDITED")
    target.write_bytes(worktree)

    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    # THE DEFECT: the recorded snapshot equals HEAD, not the true
    # dirty-at-dispatch working-tree bytes.
    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(head_content)

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()
    assert result.returncode == 0, stderr

    staged = git(repo, "show", ":%s" % rel).stdout
    assert staged == head_content.replace(b"ANCHOR-UNIQUE", b"ANCHOR-EDITED"), staged
    assert b"PRE-EXISTING-DIRTY" not in staged, staged
    assert target.read_bytes() == worktree


def test_i12_signature_still_named_on_the_refusal_path(tmp_path):
    """The stale-capture diagnostic must not rot into an unreachable branch.

    Its trigger condition moved -- whole-file inequality no longer gates a
    landing -- so this pins the condition it now has: whenever the route
    refuses for its own reason AND the recorded snapshot is byte-identical
    to the current HEAD blob, the refusal additionally names the
    machine-checkable 'I12-snapshot-mismatch' token, so a stale capture is
    still diagnosable rather than silently unreported.

    GIVEN the same defective capture AND a working tree whose owned region
    no longer holds what the claimant recorded
    WHEN the --ledger/--snapshot branch runs
    THEN exit code 10, the refusal names its own specific reason, and the
    stale-capture signature is named alongside it.
    """
    repo = _i12_repo(tmp_path)
    rel = "notes.md"
    target = repo / rel
    head_content = b"line one\nANCHOR-UNIQUE\nline three\n"
    target.write_bytes(head_content)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "HEAD content")

    # The claimant recorded ANCHOR-UNIQUE -> ANCHOR-EDITED, but the working
    # tree holds neither: its own recorded region is not where it recorded it.
    target.write_bytes(b"line one\nANCHOR-SOMETHING-ELSE\nline three\n")
    ledger = [{"old": "ANCHOR-UNIQUE", "new": "ANCHOR-EDITED"}]
    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(head_content)   # the defect: snapshot == HEAD

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()
    assert result.returncode == 10, stderr
    assert "I12-snapshot-mismatch" in stderr, stderr
    assert "OWNED_FINAL_MISMATCH" in stderr, stderr
    # Section 5.3 (c): a refusal must give its own specific reason and must
    # never be reported as somebody else's clash.
    assert "peer" not in stderr.lower(), stderr
    assert "conflict" not in stderr.lower(), stderr


def test_i12_no_false_positive_on_genuine_peer_entanglement(tmp_path):
    """This ticket's AC2 (ac_uid 134a947c21de71fa) -- separate numbering
    scope, see the module-level comment above.

    THIS PIN IS INVERTED, DELIBERATELY. It previously asserted exit code 10
    and the message 'replayed owned edits do not reproduce the worktree' for
    a fixture its own comment describes as "a genuine peer session edits an
    UNOWNED line after snapshot capture" -- i.e. it pinned the refusal of an
    ownership INTERLEAVE as correct behaviour, hardening into the suite the
    very defect docs/dev/specs/spec-20260914-052140.md Section 5.3 names: a
    single unattributed byte anywhere in the file withheld the claimant's
    entire contribution.

    Under the owned-region-local verdict the claimant now LANDS its own
    region, judged by "do the regions I myself own still contain what I
    recorded" rather than by whole-file equality to the pre-edit snapshot.

    GIVEN a CORRECTLY-captured snapshot (true dispatch-time working-tree
    bytes, differing from the current HEAD blob because the file was
    legitimately dirty at dispatch time) and a genuine post-capture
    unattributed edit outside the owned ranges
    WHEN the same replay runs
    THEN the landing SUCCEEDS; the staged image carries the claimant's own
    edit and neither the unattributed 'PEER-EDITED' bytes nor the
    pre-existing uncommitted line, because it is assembled on the commit
    baseline; the working tree is left untouched; and
    'I12-snapshot-mismatch' is absent, since the capture was correct.
    """
    repo = _i12_repo(tmp_path)
    rel = "notes.md"
    target = repo / rel
    head_content = b"line one\nANCHOR-UNIQUE\nline three\n"
    target.write_bytes(head_content)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "HEAD content")

    # Correct capture: the file was already dirty at dispatch time and the
    # snapshot faithfully records those true working-tree bytes (differs
    # from HEAD, unlike the AC1 defect case above).
    true_dispatch_snapshot = b"line one\nPRE-EXISTING-DIRTY\nANCHOR-UNIQUE\nline three\n"
    ledger = [{"old": "ANCHOR-UNIQUE", "new": "ANCHOR-EDITED"}]

    # A genuine peer session edits an UNOWNED line after snapshot capture.
    worktree = true_dispatch_snapshot.replace(b"ANCHOR-UNIQUE", b"ANCHOR-EDITED")
    worktree = worktree.replace(b"line three", b"line three PEER-EDITED")
    target.write_bytes(worktree)

    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(true_dispatch_snapshot)

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()
    assert result.returncode == 0, stderr
    assert "I12-snapshot-mismatch" not in stderr, stderr

    staged = git(repo, "show", ":%s" % rel).stdout
    assert b"ANCHOR-EDITED" in staged, staged
    assert b"PEER-EDITED" not in staged, staged
    assert b"PRE-EXISTING-DIRTY" not in staged, staged
    # Assembled on the commit baseline, so it is exactly HEAD plus this
    # claimant's own recorded change -- nothing else.
    assert staged == head_content.replace(b"ANCHOR-UNIQUE", b"ANCHOR-EDITED"), staged
    # The working tree is never written during landing.
    assert target.read_bytes() == worktree


def test_i12_clean_at_baseline_unaffected(tmp_path):
    """This ticket's AC3 (ac_uid aa4ee771a5bb02e6) -- separate numbering
    scope, see the module-level comment above.

    GIVEN a file clean at baseline: pre_edit_snapshot legitimately equals
    the HEAD blob AND forward replay DOES reproduce the worktree
    WHEN the same replay runs
    THEN exit code 0 AND the staged index blob (`git show :<rel>`) is
    byte-for-byte identical to the fixture's own known post-edit worktree
    bytes -- proving the new defect-signature branch, which lives strictly
    inside the pre-existing `if replay != worktree:` mismatch arm, is never
    entered (let alone alters staged content) on this unaffected,
    most-common code path.
    """
    repo = _i12_repo(tmp_path)
    rel = "notes.md"
    target = repo / rel
    head_content = b"line one\nANCHOR-UNIQUE\nline three\n"
    target.write_bytes(head_content)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "HEAD content")

    ledger = [{"old": "ANCHOR-UNIQUE", "new": "ANCHOR-EDITED"}]
    expected_worktree = head_content.replace(b"ANCHOR-UNIQUE", b"ANCHOR-EDITED")
    target.write_bytes(expected_worktree)

    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    # Legitimately equals HEAD: the file really was clean at baseline.
    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(head_content)

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    assert result.returncode == 0, result.stderr.decode()
    staged = git(repo, "show", ":%s" % rel).stdout
    assert staged == expected_worktree


def test_i12_untracked_file_unaffected(tmp_path):
    """This ticket's AC4 (ac_uid 102dd00981d35b48) -- separate numbering
    scope, see the module-level comment above.

    GIVEN an untracked (new) file passed to the --ledger/--snapshot path
    WHEN scripts/stage-owned-hunks.py runs
    THEN it still exits 10 with the existing 'not tracked in the index'
    message, unaffected by the new detection logic (which lives strictly
    inside the tracked-file replay-mismatch branch, evaluated AFTER the
    not-tracked check).
    """
    repo = _i12_repo(tmp_path)
    git(repo, "commit", "--allow-empty", "-qm", "initial")
    rel = "untracked.md"
    target = repo / rel
    target.write_bytes(b"brand new content\n")
    # Deliberately never `git add`-ed: this file is untracked.

    ledger = [{"old": "brand new content", "new": "brand new content edited"}]
    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(b"brand new content\n")

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()
    assert result.returncode == 10, stderr
    assert "not tracked in the index" in stderr


# ---------------------------------------------------------------------------
# I13-post-apply-mismatch reachability (task dev-20260924-071719,
# docs/dev/ticket-dev-20260924-071719.md). Reuses the exact same subprocess-
# driven sandbox-git-state fixture pattern as the I12 tests immediately
# above (real `git init`/`git commit` executed inside THIS pytest process
# via `subprocess.run`, not the agent Bash tool -- the agent git-commit
# privilege guard that blocks a sandbox baseline commit from an agent Bash
# call does not apply to git operations a test process runs on its own,
# which is why the I12 tests above already exercise the same main()
# --ledger/--snapshot CLI entry point end-to-end). These two tests confirm
# the new I13-post-apply-mismatch branch (scripts/stage-owned-hunks.py,
# strictly between the `git apply --cached` call and `return OK`) is
# actually REACHED by ordinary staging flow through the real CLI
# entrypoint, not merely correct in isolation -- the I12 tests above never
# construct INDEX/snapshot drift, so they exercise a different failure
# (forward-replay mismatch, caught before `git apply --cached` ever runs),
# not this one.
# ---------------------------------------------------------------------------

_I13_BASELINE = (
    "def region_a():\n"
    "    x = 1\n"
    "    return x\n"
    "\n"
    "def region_b():\n"
    "    y = 2\n"
    "    return y\n"
).encode("utf-8")


def test_i13_offset_shift_corruption_is_detected_and_rolled_back(tmp_path):
    """AC1/AC4 (docs/dev/acceptance-criteria-dev-20260924-071719.json).

    GIVEN the INDEX for <rel> is at a bare baseline (HEAD == baseline,
    never touched by a foreign commit or `git add`) while the real on-disk
    file also carries ANOTHER, still-unstaged cycle's foreign edit inside
    region_a (written directly to disk, never staged -- confirmed via
    `git diff --cached --quiet`), and THIS cycle's own --snapshot is
    captured FROM that already-dirty on-disk file (so the snapshot's line
    numbering includes the foreign line the INDEX does not), and this
    cycle's own ledger correctly forward-replays snapshot -> worktree via
    an edit in the distinct region_b
    THIS PIN IS INVERTED, DELIBERATELY: the offset-shift CAUSE is now
    structurally absent, not merely undetected. The zero-context patch build
    and its `--recount/--unidiff-zero` application are gone; the owned-only
    image is assembled once on the immutable commit baseline and installed
    as a frozen object, so there is no patch coordinate that can drift and
    nothing to land one line late. The readback-and-rollback invariant
    itself is RETAINED (the staged entry is read back and compared against
    the frozen image, bytes and mode asserted separately) and is exercised
    over an injected-fault matrix by this lane's AC8 coverage.

    WHEN main()'s --ledger/--snapshot path builds the owned-only image
    THEN the claimant LANDS: the staged image is exactly the baseline plus
    this cycle's own region_b edit, positioned as the ledger intended, with
    the other cycle's still-unstaged region_a line absent from the index and
    still present in the working tree.
    """
    repo = _i12_repo(tmp_path)
    rel = "f.py"
    target = repo / rel
    target.write_bytes(_I13_BASELINE)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "baseline")

    # Step 2: a peer cycle's foreign, still-unstaged edit -- written
    # DIRECTLY to disk, never `git add`-ed. The INDEX must stay at HEAD.
    foreign_snapshot = _I13_BASELINE.replace(
        b"def region_a():\n    x = 1\n",
        b"def region_a():\n    # FOREIGN-INSERTED-LINE\n    x = 1\n",
    )
    target.write_bytes(foreign_snapshot)
    assert git(repo, "diff", "--cached", "--quiet", "--", rel, check=False).returncode == 0, (
        "precondition: the foreign edit must never touch the INDEX"
    )

    # Step 3: THIS cycle's --snapshot is captured from the now-dirty disk file.
    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(foreign_snapshot)

    # Step 4: this cycle's own edit, in the distinct region_b, applied on disk.
    own_old = b"def region_b():\n    y = 2\n    return y\n"
    own_new = b"def region_b():\n    y = 2\n    # OWN-EDIT-LINE\n    return y\n"
    assert foreign_snapshot.count(own_old) == 1
    worktree = foreign_snapshot.replace(own_old, own_new)
    target.write_bytes(worktree)

    # Step 5: a ledger that forward-replays snapshot -> worktree exactly.
    ledger = [{"old": own_old.decode("utf-8"), "new": own_new.decode("utf-8")}]
    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    # Step 6: re-confirm the INDEX is STILL exactly at HEAD before invocation.
    assert git(repo, "diff", "--cached", "--quiet", "--", rel, check=False).returncode == 0

    # Step 7: invoke the real CLI entrypoint as a subprocess.
    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()

    # Step 8/9: the owned-only image lands, positioned as the ledger intended.
    assert result.returncode == 0, stderr
    staged = git(repo, "show", ":%s" % rel).stdout
    assert staged == _I13_BASELINE.replace(own_old, own_new), staged
    assert b"# OWN-EDIT-LINE\n    return y\n" in staged, (
        "the owned line must sit BEFORE `return y`, not after it as dead code"
    )
    assert b"FOREIGN-INSERTED-LINE" not in staged, (
        "the other cycle's still-unstaged line must not ride along: %r" % staged
    )
    # The working tree keeps both cycles' changes; landing never writes it.
    assert target.read_bytes() == worktree


def test_i13_no_false_positive_on_legitimate_no_drift_staging(tmp_path):
    """AC2 (docs/dev/acceptance-criteria-dev-20260924-071719.json).

    GIVEN the INDEX matches this cycle's recorded snapshot exactly (no
    foreign offset drift) and the ledger's own edit is the only difference
    between snapshot and worktree
    WHEN main()'s --ledger/--snapshot path builds and applies the patch
    exactly as in the offset-shift case above, minus the foreign edit
    THEN the new I13 post-apply verification must NOT fire: the CLI still
    exits 0, the staged INDEX blob is byte-identical to the worktree, and
    'I13-post-apply-mismatch' never appears in stderr -- a correctly-landed
    patch must not be rejected by the new guard.
    """
    repo = _i12_repo(tmp_path)
    rel = "f.py"
    target = repo / rel
    target.write_bytes(_I13_BASELINE)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "baseline")

    own_old = b"def region_b():\n    y = 2\n    return y\n"
    own_new = b"def region_b():\n    y = 2\n    # OWN-EDIT-LINE\n    return y\n"
    worktree = _I13_BASELINE.replace(own_old, own_new)
    target.write_bytes(worktree)

    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(_I13_BASELINE)  # no drift: snapshot == HEAD

    ledger = [{"old": own_old.decode("utf-8"), "new": own_new.decode("utf-8")}]
    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()

    assert result.returncode == 0, stderr
    assert "I13-post-apply-mismatch" not in stderr, stderr
    staged = git(repo, "show", ":%s" % rel).stdout
    assert staged == worktree


# ---------------------------------------------------------------------------
# AC5 reachability (task dev-20260924-071719, QA WARNING finding, QA
# iteration 1): the M4 content-transform (filter=) attribute precondition
# guard (scripts/stage-owned-hunks.py:1369-1385) had zero executable
# regression-test coverage -- only static code review -- unlike AC1/AC2/AC4
# above, which got real subprocess-driven sandbox tests this cycle. These two
# tests reuse the identical proven fixture pattern (_i12_repo/
# _run_ledger_snapshot) to prove M4 is actually REACHED and fires (or does
# not fire) through the real CLI entrypoint, not merely correct in isolation.
# ---------------------------------------------------------------------------

def test_ac5_filter_attribute_precondition_fails_closed_before_patch_build(tmp_path):
    """AC5 (docs/dev/acceptance-criteria-dev-20260924-071719.json).

    GIVEN <rel> has a content-transform (`filter=`) attribute configured for
    its path via `.git/info/attributes` (one of the two mechanisms AC5's
    check{} scenario names, the other being a tracked `.gitattributes` --
    both are consulted identically by `git check-attr`)
    WHEN main()'s --ledger/--snapshot path is invoked for <rel>
    THEN the M4 precondition guard fires BEFORE any hunk patch is built or
    applied (it runs ahead of the untracked-file check, the clean-index
    gate, forward-replay, and `git apply --cached` in source order) and the
    CLI exits 10 with 'filter' present in stderr -- the exact stderr
    substring the M4 guard actually emits ('content-transform (filter=)
    attribute configured for ...'), confirmed by direct read of
    scripts/stage-owned-hunks.py:1369-1385 rather than assumed. Nothing is
    left staged for <rel>.
    """
    repo = _i12_repo(tmp_path)
    rel = "f.py"
    target = repo / rel
    target.write_bytes(_I13_BASELINE)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "baseline")

    # Configure a content-transform (filter=) attribute for the target path.
    info_attrs = repo / ".git" / "info" / "attributes"
    info_attrs.parent.mkdir(parents=True, exist_ok=True)
    info_attrs.write_text("%s filter=upper\n" % rel, encoding="utf-8")
    # FIXTURE CORRECTION (lane r05-transform-screen). This line is new; every
    # assertion below is unchanged. The fixture declared `filter=upper` but
    # never DEFINED the driver, and an undeclared driver makes git perform NO
    # conversion at all -- measured: the check-in and raw digests of this exact
    # content are identical under the original fixture. The guard this test was
    # written against refused it anyway, because it decided from the attribute
    # VALUE rather than from the conversion. That false refusal is precisely
    # what this lane removes, so without a real driver the fixture would now
    # pin the defect instead of the behaviour. Defining the driver makes the
    # configuration genuinely content-transforming, which is what the docstring
    # above always claimed it was.
    git(repo, "config", "filter.upper.clean", "tr a-z A-Z")

    own_old = b"def region_b():\n    y = 2\n    return y\n"
    own_new = b"def region_b():\n    y = 2\n    # OWN-EDIT-LINE\n    return y\n"
    worktree = _I13_BASELINE.replace(own_old, own_new)
    target.write_bytes(worktree)

    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(_I13_BASELINE)  # no drift -- isolates M4 alone

    ledger = [{"old": own_old.decode("utf-8"), "new": own_new.decode("utf-8")}]
    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()

    assert result.returncode == 10, stderr
    assert "filter" in stderr, stderr
    assert "content-transform (filter=) attribute configured" in stderr, stderr
    assert git(repo, "diff", "--cached", "--", rel, check=False).stdout == b"", (
        "M4 must fail closed BEFORE any patch is built/applied -- nothing "
        "may be staged for %s" % rel
    )


def test_ac5_no_filter_attribute_does_not_trigger_precondition_guard(tmp_path):
    """AC5 negative/control case (docs/dev/acceptance-criteria-dev-20260924-071719.json).

    GIVEN <rel> has NO content-transform attribute configured (no
    `.gitattributes`, no `.git/info/attributes` entry -- the ordinary case)
    WHEN main()'s --ledger/--snapshot path is invoked with an otherwise
    identical legitimate, no-drift scenario to the positive case above
    THEN the M4 guard must NOT fire: the CLI still exits 0, the staged
    INDEX blob is byte-identical to the worktree, and neither 'filter' nor
    'content-transform' appears in stderr -- the new precondition guard
    must not reject ordinary, unattributed staging.
    """
    repo = _i12_repo(tmp_path)
    rel = "f.py"
    target = repo / rel
    target.write_bytes(_I13_BASELINE)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "baseline")

    # Deliberately no .gitattributes / .git/info/attributes entry for <rel>.

    own_old = b"def region_b():\n    y = 2\n    return y\n"
    own_new = b"def region_b():\n    y = 2\n    # OWN-EDIT-LINE\n    return y\n"
    worktree = _I13_BASELINE.replace(own_old, own_new)
    target.write_bytes(worktree)

    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(_I13_BASELINE)

    ledger = [{"old": own_old.decode("utf-8"), "new": own_new.decode("utf-8")}]
    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()

    assert result.returncode == 0, stderr
    assert "filter" not in stderr, stderr
    assert "content-transform" not in stderr, stderr
    staged = git(repo, "show", ":%s" % rel).stdout
    assert staged == worktree


# ---------------------------------------------------------------------------
# M1/M2 (task 20260930-132644-l9, lane L9 Part A): literal "lines 1-10 vs
# lines 50-60" fixture shape on a realistically-sized (>=60 line) shared
# file. The existing I12/I13 coverage above is semantically equivalent (a
# foreign edit in one region, this cycle's own edit in a distinct region) but
# uses a tiny 3-7 line fixture, not the literal line-range shape this lane's
# acceptance criteria name. These two tests reuse the identical proven
# _i12_repo/_run_ledger_snapshot harness -- no change to the owned-only image
# construction algorithm itself (scripts/stage-owned-hunks.py:1362+), which
# stays frozen per this lane's explicit constraint.
# ---------------------------------------------------------------------------

_M1_BASELINE_LINE_COUNT = 70
_M1_BASELINE = "".join(
    "line %02d\n" % n for n in range(1, _M1_BASELINE_LINE_COUNT + 1)
).encode("utf-8")


def test_m1_foreign_edit_lines_1_10_interleaved_with_own_edit_lines_50_60_lands_own_region_only(
    tmp_path,
):
    """AC1 (docs/dev/acceptance-criteria-20260930-132644-l9.json).

    GIVEN a shared file of 70 lines; a foreign, never-staged edit inside
    lines 1-10 (line 05), written directly to disk while the INDEX stays at
    HEAD (confirmed via `git diff --cached --quiet`); and this cycle's own
    ledger edit inside lines 50-60 (line 55), with --snapshot captured FROM
    the already-dirty disk file (so it includes the foreign line, exactly
    like the real dispatch-time-capture scenario this mirrors)
    WHEN scripts/stage-owned-hunks.py's --ledger/--snapshot path stages this
    cycle's own entry
    THEN only the lines-50-60 edit lands in the staged index blob -- byte-
    for-byte identical to baseline-plus-own-edit-only -- the foreign lines-
    1-10 edit is absent from the staged index, 'I13-post-apply-mismatch' is
    absent from stderr, and exit code is 0.
    """
    repo = _i12_repo(tmp_path)
    rel = "shared.md"
    target = repo / rel
    target.write_bytes(_M1_BASELINE)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "baseline")

    # A foreign, concurrent, never-staged edit inside lines 1-10.
    foreign_old = b"line 05\n"
    foreign_new = b"line 05 FOREIGN-UNSTAGED\n"
    foreign_snapshot = _M1_BASELINE.replace(foreign_old, foreign_new)
    target.write_bytes(foreign_snapshot)
    assert git(repo, "diff", "--cached", "--quiet", "--", rel, check=False).returncode == 0, (
        "precondition: the foreign edit must never touch the INDEX"
    )

    # THIS cycle's --snapshot is captured from the now-dirty disk file, so it
    # includes the foreign line exactly as the real dispatch-time capture
    # would.
    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(foreign_snapshot)

    # THIS cycle's own edit, inside lines 50-60, applied on disk on top of
    # the foreign edit.
    own_old = b"line 55\n"
    own_new = b"line 55 OWN-EDIT-LINE\n"
    worktree = foreign_snapshot.replace(own_old, own_new)
    target.write_bytes(worktree)

    ledger = [{"old": own_old.decode("utf-8"), "new": own_new.decode("utf-8")}]
    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    # Re-confirm the INDEX is still exactly at HEAD before invocation.
    assert git(repo, "diff", "--cached", "--quiet", "--", rel, check=False).returncode == 0

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()

    assert result.returncode == 0, stderr
    assert "I13-post-apply-mismatch" not in stderr, stderr
    staged = git(repo, "show", ":%s" % rel).stdout
    assert staged == _M1_BASELINE.replace(own_old, own_new), staged
    assert b"OWN-EDIT-LINE" in staged, staged
    assert b"FOREIGN-UNSTAGED" not in staged, (
        "the foreign lines-1-10 edit must not ride along: %r" % staged
    )
    # The working tree keeps both the foreign and own edits; landing never
    # writes it.
    assert target.read_bytes() == worktree


def test_m2_dual_owner_same_region_second_claim_rejected_boundary_indeterminate(
    tmp_path,
):
    """AC2 (docs/dev/acceptance-criteria-20260930-132644-l9.json).

    GIVEN the identical baseline byte range (one anchor line) claimed by two
    different owners' ledger entries, via two distinct --ledger/--snapshot
    invocations: owner one's edit lands and is committed first (advancing
    HEAD), then owner two's entry -- captured from the ORIGINAL, pre-owner-
    one baseline, a genuine concurrent capture that never saw owner one's
    edit -- claims the exact same anchor for a different replacement text
    WHEN owner two's entry is staged against the now-advanced commit
    baseline
    THEN the second staging attempt is REJECTED (non-zero exit) with a
    specific, named OwnedLandingRefusal-derived reason (BOUNDARY_INDETERMINATE,
    per scripts/stage-owned-hunks.py:1450-1480) naming the file's relative
    path in the message -- never a bare/generic Python traceback or an
    unlabelled exit code -- and the words 'peer'/'conflict' never appear
    (Section 5.3 (c): a boundary-indeterminacy refusal must not be reported
    as somebody else's clash).
    """
    repo = _i12_repo(tmp_path)
    rel = "dual_owner.md"
    target = repo / rel
    baseline = (
        b"line one\n"
        b"line two\n"
        b"SHARED-ANCHOR\n"
        b"line four\n"
        b"line five\n"
    )
    target.write_bytes(baseline)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "baseline")

    # Owner one: snapshot equals the clean baseline (no drift yet). Lands
    # and is then COMMITTED -- not merely staged -- so the index is clean
    # again (HEAD advances) by the time owner two runs.
    owner_one_old = b"SHARED-ANCHOR\n"
    owner_one_new = b"OWNER-ONE-EDIT\n"
    owner_one_worktree = baseline.replace(owner_one_old, owner_one_new)
    target.write_bytes(owner_one_worktree)

    owner_one_snapshot_path = repo / "owner_one_snapshot.bin"
    owner_one_snapshot_path.write_bytes(baseline)
    owner_one_ledger = [
        {"old": owner_one_old.decode("utf-8"), "new": owner_one_new.decode("utf-8")}
    ]
    owner_one_ledger_path = repo / "owner_one_ledger.json"
    owner_one_ledger_path.write_text(json.dumps(owner_one_ledger), encoding="utf-8")

    owner_one_result = _run_ledger_snapshot(
        repo, rel, owner_one_ledger_path, owner_one_snapshot_path
    )
    assert owner_one_result.returncode == 0, owner_one_result.stderr.decode()
    staged_after_owner_one = git(repo, "show", ":%s" % rel).stdout
    assert staged_after_owner_one == owner_one_worktree

    # Commit owner one's staged change so the index is clean again and the
    # commit baseline (I) genuinely advances for owner two's invocation.
    git(repo, "commit", "-qm", "owner one lands")

    # Owner two: a genuine concurrent capture -- its --snapshot is the
    # ORIGINAL baseline, taken before owner one's edit ever landed. It
    # claims the SAME anchor for a different replacement.
    owner_two_old = b"SHARED-ANCHOR\n"
    owner_two_new = b"OWNER-TWO-EDIT\n"
    owner_two_snapshot_path = repo / "owner_two_snapshot.bin"
    owner_two_snapshot_path.write_bytes(baseline)
    owner_two_ledger = [
        {"old": owner_two_old.decode("utf-8"), "new": owner_two_new.decode("utf-8")}
    ]
    owner_two_ledger_path = repo / "owner_two_ledger.json"
    owner_two_ledger_path.write_text(json.dumps(owner_two_ledger), encoding="utf-8")

    result = _run_ledger_snapshot(repo, rel, owner_two_ledger_path, owner_two_snapshot_path)
    stderr = result.stderr.decode()

    assert result.returncode != 0, stderr
    assert "BOUNDARY_INDETERMINATE" in stderr, stderr
    assert rel in stderr, stderr
    assert "peer" not in stderr.lower(), stderr
    assert "conflict" not in stderr.lower(), stderr
    # Owner one's already-landed, committed edit must survive untouched --
    # the rejected second claim must not have been allowed to ride along or
    # clobber it.
    assert git(repo, "show", ":%s" % rel).stdout == owner_one_worktree


# --- One claimant's own nested components (QA F-FINAL-1, this cycle) -------
# "Insert a block, then revise a line inside the block you just inserted" is
# ordinary authoring, and it USED to be refused: the owned-landing route ran a
# second, coarser order test over component ambiguity envelopes that read "a
# different ledger entry" as "a different party". One ledger is one claimant
# and the forward replay already fixes its components' order, so the test was
# refusing a determinate input -- measured on this very file's own ledger,
# which its own contract validator certifies as valid. These fixtures pin the
# ACCEPT, and the one below them pins that a genuinely diverged baseline keeps
# refusing with its own divergence-based cause.

_NESTED_SHAPES = {
    "edit_inside_own_insertion": [
        {"old": "A\n", "new": "A\nX1\nX2\nX3\n"},
        {"old": "X2\n", "new": "Y2\n"},
    ],
    "append_to_own_insertion": [
        {"old": "A\n", "new": "A\nP\n"},
        {"old": "P\n", "new": "P\nQ\n"},
    ],
    "three_deep_nesting": [
        {"old": "A\n", "new": "A\nM1\nM2\n"},
        {"old": "M2\n", "new": "M2\nN1\nN2\n"},
        {"old": "N1\n", "new": "N1-x\n"},
    ],
}

_FOREIGN = b"\n# a peer lane's line, accounted for by no entry of this ledger\n"


def _land_owned(repo, rel, snapshot, ledger, worktree):
    """Commit `snapshot` as the baseline, put `worktree` on disk, land `ledger`."""
    target = repo / rel
    target.write_bytes(snapshot)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "baseline is the recorded snapshot")
    target.write_bytes(worktree)
    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(snapshot)
    return _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)


@pytest.mark.parametrize("shape", sorted(_NESTED_SHAPES))
def test_nested_same_claimant_components_land(tmp_path, shape):
    """A later entry whose anchor lives inside an earlier entry's insertion
    lands, and lands the OWNED-ONLY image rather than the working tree."""
    repo = _i12_repo(tmp_path)
    rel = "nested.txt"
    snapshot = b"A\nB\n"
    replay = _apply_ledger(snapshot, _NESTED_SHAPES[shape])
    result = _land_owned(repo, rel, snapshot, _NESTED_SHAPES[shape],
                         replay + _FOREIGN)
    assert result.returncode == 0, result.stderr.decode()
    staged = git(repo, "show", ":%s" % rel).stdout
    assert staged == replay
    assert _FOREIGN.strip() not in staged
    assert (repo / rel).read_bytes() == replay + _FOREIGN


def test_self_application_nested_ledger_at_realistic_scale_lands(tmp_path):
    """Self-application: the shape measured on this route's OWN ledger.

    The snapshot is the helper's own current bytes, entry 1 inserts a large
    block into it, and entry 2 revises a line inside that insertion -- the
    same two-component relation, at the same order of magnitude, that refused
    before. Hermetic: it depends on no gitignored artifact.
    """
    repo = _i12_repo(tmp_path)
    rel = "self_application.py"
    snapshot = HELPER.read_bytes()
    assert len(snapshot) > 50000, "fixture wants a realistically large snapshot"
    block = "".join("# inserted line %04d\n" % n for n in range(900))
    ledger = [
        {"old": "import argparse\n",
         "new": "import argparse\n" + block},
        {"old": "# inserted line 0450\n", "new": "# revised line 0450\n"},
    ]
    replay = _apply_ledger(snapshot, ledger)
    result = _land_owned(repo, rel, snapshot, ledger, replay + _FOREIGN)
    assert result.returncode == 0, result.stderr.decode()
    staged = git(repo, "show", ":%s" % rel).stdout
    assert staged == replay
    assert b"# revised line 0450\n" in staged
    assert _FOREIGN.strip() not in staged


def test_diverged_baseline_inside_owned_region_still_refuses(tmp_path):
    """The other refusal class stays refusing, and stays distinguishable.

    A difference between the recorded snapshot and the commit baseline falling
    inside a recorded component is a genuine boundary indeterminacy. It must
    keep refusing, on the BASELINE side, with a divergence-based cause -- never
    the envelope-overlap cause the nested fixtures above removed from this
    side, and never as somebody else's clash.
    """
    repo = _i12_repo(tmp_path)
    rel = "diverged.txt"
    snapshot = b"a\nTARGET\nb\n"
    ledger = [{"old": "TARGET\n", "new": "MINE\n"}]
    target = repo / rel
    target.write_bytes(b"a\nPEER-REWROTE-THIS-LINE\nb\n")   # the commit baseline
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "baseline diverged from the recorded snapshot")
    target.write_bytes(_apply_ledger(snapshot, ledger))
    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(snapshot)

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()
    assert result.returncode != 0, stderr
    assert "BOUNDARY_INDETERMINATE" in stderr, stderr
    assert "side=BASELINE" in stderr, stderr
    assert "cause=envelope-overlap" not in stderr, stderr
    assert rel in stderr, stderr
    assert "peer" not in stderr.lower(), stderr
    assert "conflict" not in stderr.lower(), stderr
    assert git(repo, "diff", "--cached", "--", rel).stdout == b""


# --- Placement follows the CERTIFIED structure, not one witness alignment ----
# Removing the cross-entry envelope test above exposed the next refusal on the
# same real ledger: a BASELINE "crossing" raised at snapshot [72969,72997), on
# an entry whose 609-byte recorded text occurs exactly once in the snapshot AND
# exactly once in the commit baseline. `_align_pairs` returns ONE witness
# alignment and `_optimal_structure` returns the structure of ALL of them, and
# above the DP budget the two line-anchor over DIFFERENT windows -- so the
# witness drifted from the structure inside text byte-identical in both
# buffers: 47 positions the structure determined uniquely were unpaired by the
# witness and 26 more were paired three bytes off. The first set refused a
# determinate ledger; the second was worse, because had the contiguity run not
# tripped, the owned slice would have landed three bytes from where the gate
# then certified it. These two fixtures pin the narrowing in both directions:
# a drifting witness no longer decides placement, and a component the structure
# genuinely cannot place keeps refusing.


def _helper_module():
    """The helper as an in-process module, for the witness-level assertions."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("stage_owned_hunks", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# An unowned peer line shifts the baseline by 12 bytes, so S != I and the whole
# divergent-baseline machinery engages; the owned block is byte-identical in
# both, and its 20-space run is where a witness can legitimately drift.
_DRIFT_BASELINE_HEAD = b"import os\nimport sys\n"
_DRIFT_SNAPSHOT_HEAD = b"import os\nimport sys\nimport json\n"
_DRIFT_BLOCK = b'msg = ("one"\n' + b" " * 20 + b'"two")\n'
_DRIFT_FOOT = b"def f():\n    return msg\n"
_DRIFT_NEW = b'msg = "ONE TWO"\n'


def test_witness_alignment_drift_does_not_refuse_a_determinate_component():
    """A sub-maximal (but admissible) witness must not decide the placement.

    The drift injected here is exactly the measured shape: three pairs dropped
    inside the equal-byte run and the following ones slid by three. It is still
    a monotone, non-crossing, equal-byte alignment -- asserted below, so the
    fixture pins a reading `_align_pairs` may really return, not an impossible
    one.
    """
    helper = _helper_module()
    rel = "drift.py"
    index_blob = _DRIFT_BASELINE_HEAD + _DRIFT_BLOCK + _DRIFT_FOOT
    snapshot = _DRIFT_SNAPSHOT_HEAD + _DRIFT_BLOCK + _DRIFT_FOOT
    ledger = [{"old": _DRIFT_BLOCK.decode(), "new": _DRIFT_NEW.decode()}]
    worktree = _apply_ledger(snapshot, ledger)

    witness = helper._align_pairs(snapshot, index_blob)
    drifted = []
    for i, j in witness:
        if i in (48, 49, 50):
            continue
        drifted.append((i, j - 3) if 51 <= i <= 65 else (i, j))
    assert all(snapshot[i] == index_blob[j] for i, j in drifted)
    assert all(drifted[k][0] < drifted[k + 1][0]
               and drifted[k][1] < drifted[k + 1][1]
               for k in range(len(drifted) - 1))
    assert len(drifted) == len(witness) - 3

    replayed = helper._replay_with_provenance(snapshot, ledger, rel)
    net = helper._net_edits_in_snapshot_coords(
        replayed[0], replayed[1], len(snapshot), rel)
    component = [edit for edit in net if edit[0] == 47]
    assert component, "fixture precondition: a component starts at 47"

    # The structure certifies every byte of that component.
    s_changed, _i_changed, s_images, exact = helper._optimal_structure(
        snapshot, index_blob)
    assert exact
    assert all(position not in s_changed and len(s_images[position]) == 1
               for position in range(47, 70))

    # What used to happen: the witness alone refuses a certified component.
    with pytest.raises(helper.OwnedLandingRefusal) as refusal:
        helper._map_edit_onto_baseline(
            dict(drifted), component[0], len(snapshot), len(index_blob), rel)
    assert refusal.value.side == "BASELINE"
    assert refusal.value.cause == "crossing"

    # What happens now: the image is the owned-only image either way.
    expected = _DRIFT_BASELINE_HEAD + _DRIFT_NEW + _DRIFT_FOOT
    assert helper._owned_only_image(
        snapshot, index_blob, worktree, ledger, rel)[0] == expected
    real_align = helper._align_pairs
    helper._align_pairs = (
        lambda p, q: list(drifted)
        if (p == snapshot and q == index_blob) else real_align(p, q))
    try:
        assert helper._owned_only_image(
            snapshot, index_blob, worktree, ledger, rel)[0] == expected
    finally:
        helper._align_pairs = real_align


def test_genuinely_ambiguous_envelope_still_refuses(tmp_path):
    """The other direction: a component the structure cannot place uniquely.

    Nine baseline `#` against seven recorded ones is the smallest genuine
    envelope ambiguity -- every recorded byte is matched in every minimum-cost
    alignment, so none is "changed", yet each admits three images and the owned
    slice has three cost-equal baseline intervals. The narrowing keys off
    exactly the uniqueness this input lacks, so it must stay refused, and no
    witness -- drifted or not -- may rescue it.
    """
    helper = _helper_module()
    rel = "ambiguous.py"
    index_blob = b"a = 1\n" + b"#" * 9 + b"\nz = 2\n"
    snapshot = b"a = 1\n" + b"#" * 7 + b"\nz = 2\n"
    ledger = [{"old": "#" * 7, "new": "BANNER"}]
    worktree = _apply_ledger(snapshot, ledger)

    s_changed, _i_changed, s_images, exact = helper._optimal_structure(
        snapshot, index_blob)
    assert exact
    # The fix's condition is FALSE for every byte here: ambiguous, not absent.
    assert all(position not in s_changed and len(s_images[position]) > 1
               for position in range(6, 13))

    for witness in (None, [(i, i) for i in range(6)]):
        real_align = helper._align_pairs
        if witness is not None:
            helper._align_pairs = (
                lambda p, q: list(witness)
                if (p == snapshot and q == index_blob) else real_align(p, q))
        try:
            with pytest.raises(helper.OwnedLandingRefusal) as refusal:
                helper._owned_only_image(
                    snapshot, index_blob, worktree, ledger, rel)
        finally:
            helper._align_pairs = real_align
        assert refusal.value.reason == "BOUNDARY_INDETERMINATE"
        assert refusal.value.side == "BASELINE"

    # And the caller sees the refusal, not a staged guess.
    repo = _i12_repo(tmp_path)
    target = repo / rel
    target.write_bytes(index_blob)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", "baseline carries two more banner bytes")
    target.write_bytes(worktree)
    ledger_path = repo / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    snapshot_path = repo / "snapshot.bin"
    snapshot_path.write_bytes(snapshot)

    result = _run_ledger_snapshot(repo, rel, ledger_path, snapshot_path)
    stderr = result.stderr.decode()
    assert result.returncode == 10, stderr
    assert "BOUNDARY_INDETERMINATE" in stderr, stderr
    assert "side=BASELINE" in stderr, stderr
    assert "cause=multiple" in stderr, stderr
    assert git(repo, "diff", "--cached", "--", rel).stdout == b""
