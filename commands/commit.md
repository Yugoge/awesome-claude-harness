---
description: Commit session changes via changelog-analyst subagent
disable-model-invocation: true
---

# /commit

Agentic commit command. Validates the close-gate (unless `--force`), then dispatches
the `changelog-analyst` subagent to classify files, stage them, and create a real
branch commit. Handles nested repo (`/dev/shm/dev-workspace/dot-claude/`) automatically.

## Usage

```
/commit [<task-id>] [--force] [--bulk] [--dry-run] [--codex]
```

| Flag | Meaning |
|------|---------|
| `<task-id>` | Required unless `--force` or `--bulk`. Task-id from the completed `/dev` cycle (e.g. `20260516-212024`). |
| `--force` | Bypass close-gate check **AND the pre-commit QA gate** (Step 6). Human-only (enforced by `disable-model-invocation: true`). Audited. |
| `--bulk` | Smart batch mode — group by task-id then subsystem, commit coherently, flag orphan files separately. Human-only (enforced by `disable-model-invocation: true`). |
| `--dry-run` | Print what would be staged/committed (and the QA verdict); do not execute the real commit. |
| `--codex` | In the pre-commit QA gate (Step 6), QA additionally runs an adversarial Codex round on the planned per-file changes (each PLAN_GROUPS path vs HEAD), not the staged index. Without it, QA does a single-round self-review. |

## Step-by-step workflow

### Step 1: Parse arguments

Parse `$ARGUMENTS`:
- Strip `--force` if present → set `FORCE=true`; else `FORCE=false`
- Strip `--bulk` if present → set `BULK=true`; else `BULK=false`
- Strip `--dry-run` if present → set `DRYRUN=true`; else `DRYRUN=false`
- Strip `--codex` if present → set `QA_CODEX=true`; else `QA_CODEX=false`
- Remaining token (if any) is `TASK_ID`

### Step 2: Resolve task-id (unless --bulk)

If `BULK=false`:
- If `TASK_ID` was supplied, use it directly.
- If `TASK_ID` is empty: exit with: `No task-id provided. Supply an explicit task-id (/commit <task-id>), use --force to bypass close-gate, or use --bulk for batch mode.` Do NOT scan close-reports by mtime — mtime-scan picks up unrelated reports from other sessions and causes close-gate failures on unrelated tasks.

If `BULK=true`: `TASK_ID` may remain empty; changelog-analyst operates in bulk mode.

### Step 3: Close-gate validation (skip if FORCE=true or BULK=true)

If `FORCE=false` AND `BULK=false`:

Resolve the close-report path via the helper script (which probes
subproject docs/dev/ first, then falls back to `/root/docs/dev/` — see
`scripts/resolve-close-report.sh`). The script exits 1 when no candidate
file exists; `CLOSE_REPORT` still holds the fallback path for the error
message in check 1 below.

```
CLOSE_REPORT="$(bash ~/.claude/scripts/resolve-close-report.sh "$TASK_ID")" || true
```

Run these checks (abort on first failure with a clear error message):

1. **File exists**: `CLOSE_REPORT` must exist. Error: `Close-gate: no close-report for task ${TASK_ID} at ${CLOSE_REPORT}. Run /close first.`
2. **Last non-empty line starts with CLOSE: YES**: extract the last non-empty line from the file and verify it begins with `CLOSE: YES`. Accepted variants:
   - `CLOSE: YES`
   - `CLOSE: YES — FORCED`
   - `CLOSE: YES - degraded codex consultation: codex_status=<...>`
   - `CLOSE: YES — codex disabled by user`
   - `CLOSE: YES (FORCED)`
   Error: `Close-gate: task ${TASK_ID} close-report does not end with CLOSE: YES (found: <last-line>). Run /close to produce a passing verdict.`
3. **Mtime recency**: close-report mtime must be within 86400 seconds (24 h) of now. Error: `Close-gate: close-report for task ${TASK_ID} is older than 24h (mtime: <mtime>). Re-run /close or use --force.`
4. **Task-id in filename matches argument**: the task-id derived from the filename must equal `TASK_ID`. Error: `Close-gate: filename task-id mismatch (file has <file-task-id>, argument is ${TASK_ID}).`

### Step 4: Force-bypass audit (only when FORCE=true)

If `FORCE=true`: create `~/.claude/logs/` and append a line with ISO timestamp, task-id, and mode=force to `~/.claude/logs/commit-overrides.log`. Best-effort; proceed even if log append fails.

Print: `WARNING: --force bypasses close-gate. Audit entry written to ~/.claude/logs/commit-overrides.log.`

### Step 5: Write commit grant and dispatch-snapshot manifest

Before dispatching changelog-analyst, write the appropriate authorization token:
- **BULK=true**: the multi-use bulk-commit capability is now minted by the TRUSTED `userprompt-bulk-commit-capability.py` hook the moment the human submits `/commit --bulk` (an LLM cannot self-invoke a `disable-model-invocation: true` slash command, so the prompt itself is the trust root). The orchestrator MUST NOT emit a Bash command to write the sentinel — that fragile exact-string path is retired.
  - PRIMARY: assume the hook already minted `/tmp/claude-bulk-commit-sentinel-<sid>-<nonce>.json` (origin `userpromptsubmit-hook`). Proceed to the **Step 6 pre-commit QA gate** (then Step 7) — `--bulk` is NOT exempt from the QA gate (only `FORCE=true` bypasses it). An optional read-only check is a single bare `ls /tmp/claude-bulk-commit-sentinel-*.json`.
  - NO FALLBACK: the canonical writer is no longer Bash-executable (Layer 1.F deny-only, stage-2). The hook is the SOLE minter. If the capability is absent, the `userprompt-bulk-commit-capability.py` hook is not yet active in this session — instruct the user to restart the session so settings.json reloads the hook, then re-run `/commit --bulk`. Do NOT attempt to write the sentinel via Bash.
- **BULK=false**: write **two single-use commit grants** (one for root-repo commit or root-repo recovery, one for nested-repo recovery commit). Activate venv and run Python to write the grants. The script resolves the session ID from `CLAUDE_CODE_SESSION_ID` (primary) or `CLAUDE_SESSION_ID` (fallback). If neither is set, abort immediately with: `Cannot write commit grant: CLAUDE_CODE_SESSION_ID (and CLAUDE_SESSION_ID) not set. Invoke /commit from within a Claude Code session.` Do NOT proceed to dispatch changelog-analyst. If `sid` is set, generate `grant_path = /tmp/claude-commit-grant-{sid}-{nonce}.json` containing `task_id`, `sid`, `nonce`, `expires_at`, and `created_at`. The guard IS registered and active — grant absence WILL block the changelog-analyst commit.

**Grant timestamp format (NON-NEGOTIABLE)**: The `expires_at` and `created_at` fields MUST be ISO-8601 strings produced from timezone-aware UTC datetimes (e.g. `(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()` yields `"2026-05-19T16:18:56.123456+00:00"`). Epoch integers and epoch floats (e.g. `int(time.time()) + 600`, `time.time() + 600`) are NOT accepted by the privilege guard. The guard at `/root/.claude/hooks/pretool-git-privilege-guard.py:377-384` parses these fields via `datetime.fromisoformat(end_str.replace('Z', '+00:00'))`; on `ValueError`/`TypeError`/`AttributeError` the helper `_end_time_passed` returns `True` (i.e. "already expired"), which silently rejects the grant and blocks the commit. The expiration window is 30 minutes from `created_at` — bake the offset into `expires_at` at write time. Activate the venv and invoke the grant-writer script (resolves `CLAUDE_SESSION_ID` from the environment, generates a fresh nonce, writes timezone-aware ISO-8601 `created_at` and `expires_at` on a 30-minute window, and emits the resulting grant path on stdout):

```bash
# First grant: covers the normal commit (root or nested repo, whichever commits first)
source venv/bin/activate && python3 /root/.claude/scripts/write-commit-grant.py --task-id "$TASK_ID"
# Second grant: covers nested-repo recovery commit when nothing_to_commit_precommitted is
# detected in the nested repo — the first grant is consumed by the root-repo commit (or
# root-repo recovery commit); the second grant is available for the nested-repo recovery.
# If only one repo needs a recovery commit, the second grant expires unused (30-min TTL).
source venv/bin/activate && python3 /root/.claude/scripts/write-commit-grant.py --task-id "$TASK_ID"
```

Both `created_at` and `expires_at` MUST match the regex `^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+\d{2}:\d{2}|Z)$`. Do NOT substitute `time.time()`, `int(time.time())`, or `datetime.utcnow()` (the last returns a naive datetime whose `.isoformat()` omits the TZ offset and falls into the naive-comparison branch at line 382).

Also write the dispatch-snapshot manifest (non-bulk mode only): activate venv and run Python to capture `git status --porcelain=v1` from both repos, then write `manifest_path = /tmp/claude-commit-manifest-{sid}.json` containing `session_id`, `task_id`, `dispatched_at`, and `files_at_dispatch`. Best-effort; skip entirely in bulk mode.

### Step 6: Pre-commit QA review gate (skip if FORCE=true)

A QA agent reviews **what is actually about to be committed** (each planned file's change vs HEAD) and may BLOCK the commit. This is an independent second reviewer on top of `changelog-analyst`'s own staging judgment — it exists because `--bulk` / `--force` skip `/close` entirely, and even a normal commit's *actual file changes* deserve a fresh adversarial check for junk / secrets / scope contamination. The gate reviews the file changes themselves, NOT the dev-report.

**If `FORCE=true`: skip this entire step.** Print `WARNING: --force bypasses the pre-commit QA gate.` and proceed to Step 7 (human override accepts the risk; the bypass is already audited by Step 4).

Otherwise (applies to BOTH `BULK=false` and `BULK=true`):

**Step 6a — Produce the staging plan (internal dry-run; plan-only).**
Dispatch `changelog-analyst` (Agent, `subagent_type: changelog-analyst`) with the **same prompt as Step 7 but `DRYRUN=true`** (force dry-run regardless of the user's `--dry-run`). Under `DRYRUN=true` changelog-analyst classifies, stages the candidate set into the index, and STOPS before commit — it does NOT commit, write push-gate tokens, run any recovery commit, or consume the Step 5 grant (guaranteed by the DRYRUN guard in `agents/changelog-analyst.md` — the `nothing_to_commit_precommitted` recovery path is disabled under DRYRUN). Capture from its output:
- `PLAN_GROUPS` — the per-proposed-commit groups, each `{repo, commit_message, files[]}` (one entry per intended commit; bulk yields several). **Preserve group boundaries — do NOT flatten across groups** (QA needs them to detect cross-task mixing).
- `PLAN_FILES` — the union of all group files, per repo.
- If the dry-run reports `nothing_to_commit` / empty plan: print `Nothing to commit — QA gate skipped.`; then **when `BULK=false`, revoke the Step 5 commit grant** (it will never be consumed — same Grant-hygiene rationale as Step 6c) via `source venv/bin/activate && python3 "/root/.claude/scripts/write-commit-grant.py" --task-id "$TASK_ID" --revoke-only` (skip in `BULK=true` — no per-task grant, empty TASK_ID); then proceed to Step 7 (which also no-ops). Do NOT dispatch QA on an empty plan.

QA reviews each planned file's change **directly against HEAD** (staging-independent), NOT via `git diff --cached`. Rationale: in multi-group `--bulk`, changelog-analyst stages per subsystem group and Phase 4 unstages cross-group files each iteration, so after the dry-run only the LAST group remains staged — a `--cached` review would silently skip every earlier group while ALL groups still enter `QA_APPROVED_FILES` and get committed. Reviewing each `PLAN_GROUPS` file vs HEAD (or reading new files) covers ALL groups regardless of staging state.

**Step 6b — QA reviews the planned set (vs HEAD, staging-independent).**
Dispatch ONE QA subagent (Agent, `subagent_type: qa`). The dispatch prompt MUST include `codex_required: <QA_CODEX>` and `PLAN_GROUPS`, and instruct QA as follows:

```
You are the pre-commit QA gate. Review ONLY what is about to be committed — the files
in PLAN_GROUPS — by reading each file's ACTUAL change, NOT the dev-report.

Proposed commit groups (preserve boundaries): <PLAN_GROUPS>
  (each = {repo, commit_message, files[]} — one intended commit)
TASK_ID: <TASK_ID or "bulk">   BULK: <true|false>

For EVERY path in EVERY group, review its actual change DIRECTLY (do NOT rely on the
staging state — in multi-group bulk only the LAST group is left staged, so `git diff
--cached` would silently skip earlier groups). For each path, gather BOTH sources and
review every one that is non-empty:
  - DIFF: `git -C <repo> diff --text HEAD -- <path>` — `--text` forces a content patch even
    when `.gitattributes` marks the path `-diff`. If git instead reports "Binary files …
    differ", the path is a real binary blob: do NOT text-review it — judge it under
    rejection rule 1/4 below (intended asset vs accidental/junk binary).
  - CONTENTS: if `<path>` currently EXISTS on disk, ALSO read its contents directly.
  Both sources can be non-empty at once and you MUST review both — e.g. a path deleted at
  HEAD yet recreated on disk (status `D` + `??`: the diff shows only the old deletion, the
  file holds the new content), or a rename/copy's new side an earlier bulk group left
  unstaged (untracked → empty diff, but the file exists).
  - for a rename/copy, treat the OLD and NEW paths as TWO separate entries under this rule.
Feed the SAME per-path material to the Codex sub-round below (NOT the staged set).
Judge by intelligent review — NEVER a hardcoded junk list. REJECT the commit if any of:
  1. Transient / non-authored byproducts (runtime/session state, caches, registries,
     scratch/temp outputs, generated indexes, build products) — by what the file IS,
     regardless of which folder it sits in.
  2. Secrets / sensitive content (credentials, keys, tokens, .env material).
  3. Scope contamination — files unrelated to TASK_ID (BULK=false); or, WITHIN ONE
     proposed group, files belonging to two different task-ids / unrelated subsystems
     (BULK=true) — use the group boundaries above.
  4. Obvious correctness/quality defects in the diff (syntax-broken code, committed
     debug leftovers, accidental large/binary blobs).

codex_required = <QA_CODEX>:
  - true  → after your own review run ONE adversarial Codex round via Skill(codex) on the
            SAME per-file PLAN_GROUPS material you reviewed above (the HEAD diffs / new-file
            contents — NOT the staged set, which in multi-group bulk holds only the last group)
            + your draft verdict (reply `CODEX: APPROVE` / `CODEX: REJECT` +
            rationale). A substantive codex REJECT flips you to REJECT. Codex-status
            handling MIRRORS /close: quota/timeout MAY degrade to your own verdict with a
            recorded note; a PARSE FAILURE is NOT auto-degrade — record the verbatim raw
            codex output, manually scan it for dissent signals (`NO`, `bug`, `secret`,
            `junk`, `must not`, `wrong`, `should not`…), and REJECT (fail-closed) if ANY
            dissent signal or ambiguity is present.
  - false → single-round self-review; do NOT invoke codex.

Write a transcript to docs/dev/commit-qa-report-<TASK_ID or "bulk">.md (verdict +
per-file findings + codex_status when run).

Return, as the LAST line, EXACTLY one of:
  COMMIT: APPROVE
  COMMIT: REJECT - <one sentence naming the offending file(s) and why>
```

**Step 6c — Gate decision.**

**Grant hygiene (`BULK=false` stop paths only — REJECT, `--dry-run` stop, unparseable):** in addition to unstaging, when `BULK=false` REVOKE the Step 5 commit grant so a blocked/stopped gate never leaves live commit authorization lingering (30-min TTL):
```bash
source venv/bin/activate && python3 "/root/.claude/scripts/write-commit-grant.py" --task-id "$TASK_ID" --revoke-only
```
**Skip this revoke entirely when `BULK=true`**: bulk wrote NO per-task commit grant (Step 5 minted the multi-use bulk-commit sentinel, which self-expires on its own 30-min TTL) and `TASK_ID` is empty, so calling the writer with an empty `--task-id` would error (exit 2). (Only the `COMMIT: APPROVE` + real-commit path keeps the grant — it is consumed by Step 7.)

- `COMMIT: REJECT`: print the verdict + offending files; **unstage the dry-run-staged set so the tree is left clean** — per repo, unstage ONLY currently-staged paths, computed rename-aware. Run `git -C <repo> diff --cached --name-status -z -M` and build the unstage set from its entries: a plain (non-rename) staged path → include it if it is in `PLAN_FILES`; a staged `R`/`C` entry → include BOTH its old and new paths if EITHER endpoint is in `PLAN_FILES` (the analyst may list only the new path, yet `--name-only` / a single-endpoint unstage leaves the other endpoint — e.g. `D old` — staged). Unstage that set via `git -C <repo> restore --staged -- <those>` (unborn repo: `git -C <repo> rm --cached -- <those>`). Do NOT pass planned files that are not currently staged — in multi-group bulk Phase 4 already unstaged the earlier groups, and `restore --staged` / `rm --cached` on an unstaged/untracked pathspec errors out and leaves the last group staged. Then revoke the grant (Grant hygiene above). Do NOT proceed to Step 7; do NOT commit. Tell the user to remove/fix the flagged files, or re-run with `--force` to override. **Stop.**
- `COMMIT: APPROVE`:
  - Record `QA_APPROVED_FILES` = `PLAN_FILES` (the exact reviewed set, per repo). This is passed to Step 7 as the commit **ceiling** (TOCTOU guard — Step 7 must not commit anything outside it).
  - If the user passed `--dry-run` (`DRYRUN=true`): print the plan + `QA: APPROVE`, unstage the dry-run-staged set (clean tree, as in the REJECT branch), and **stop** — no real commit.
  - Otherwise proceed to Step 7 for the real commit.
- Unparseable / missing `COMMIT:` final line: treat as REJECT (fail-closed); unstage (as above), print the raw QA output, and stop.

### Step 7: Dispatch changelog-analyst

Use the Agent tool with `subagent_type: changelog-analyst`. Pass a structured prompt:

```
CONTROL_ROOT=/root
NESTED_REPO=/dev/shm/dev-workspace/dot-claude
TASK_ID=<resolved task-id or empty for bulk>
BULK=<true|false>
DRYRUN=<true|false>
FORCE=<true|false>
QA_APPROVED_FILES=<the Step 6c QA-approved file set, per repo; empty when FORCE=true (gate skipped)>

You are the changelog-analyst subagent. Execute the commit workflow as specified
in your agent definition (agents/changelog-analyst.md). Use the variables above
to guide your behavior.

Constraints:
- CONTROL_ROOT is the fallback root for dev-report resolution; changelog-analyst MUST apply the subproject path-walk (dirname-of-changed-files → commonpath → walk up to docs/dev/) and check the subproject docs/dev/ first before falling back to ${CONTROL_ROOT}/docs/dev/
- GIT_ROOT must be computed per repo via `git rev-parse --show-toplevel`; never conflate with CONTROL_ROOT
- **TOCTOU guard (pre-commit QA gate)**: when `QA_APPROVED_FILES` is non-empty (the Step 6 gate ran and approved this exact set), it is the commit CEILING. Re-classify normally, then intersect the classified set with `QA_APPROVED_FILES`: stage/commit ONLY files in both. If your fresh classification yields any file NOT in `QA_APPROVED_FILES` (working tree changed since QA review), do NOT commit the unreviewed file; if the divergence is material (a QA-approved file vanished, or a new non-approved candidate appeared that you would otherwise commit), ABORT with `failure_code: scope_violation` rather than commit an unreviewed set. When `QA_APPROVED_FILES` is empty (FORCE bypass), this guard does not apply.
- Stage only files in the classified set; never use `git add -A` or `git add .`
- Commit message must NOT match: `\bsync\b.*\buncommitted\b` or `chore\(claude\)\s*:\s*sync`
- Handle nested repo at /dev/shm/dev-workspace/dot-claude/ independently
- Write push-gate token after each successful commit
- Push-gate token path MUST be: `/tmp/agentic-commit/push/<sha256(os.path.realpath(GIT_ROOT))[:16]>/<BRANCH with / replaced by __>.json`
- Push-gate validates commit_sha only; expires_at is no longer written or checked
- **BULK mode commit message prefix (REQUIRED when BULK=true)**: every commit message MUST begin with `auto-bulk: end-of-cycle commit for <current-branch>` where `<current-branch>` is the actual current git branch of the repo being committed (run `git rev-parse --abbrev-ref HEAD`). This prefix matches `BLESSED_BRIDGE_RE`; the privilege guard requires a valid bulk-commit sentinel (written in Step 5) to allow the commit. Do NOT use this prefix when BULK=false.
```

Wait for changelog-analyst to complete. Echo its final status to the user.

#### Changelog-analyst result handling and retry protocol

Parse changelog-analyst's structured status output (see `agents/changelog-analyst.md` §Structured Final Status Output). The machine-readable JSON block contains `commit_status` and, when applicable, `failure_code`, `failure_reason`, and `auto_bulk_commits[]`.

**Handle each commit_status value:**

#### status = `committed`
Continue to Step 8 normally.

#### status = `nothing_to_commit`
Print: `WARNING: changelog-analyst found nothing to commit after exclusions. Verify the task cycle produced staged changes.`
Continue to Step 8 (skip spec-update if no real commit occurred — Step 8 skip conditions apply).

#### status = `nothing_to_commit_precommitted`
Record `auto_bulk_commits[]` from the structured output in the Step 8 summary.
Print: `INFO: Changes were already committed in an auto-bulk commit. auto_bulk_commits: <auto_bulk_commits[]>`
Continue to Step 8.

#### status = `failed` — retryable grant codes

Check `failure_code`:

**Retryable** (`grant_missing`, `grant_expired`, `grant_consumed`):

Retry exactly once (max 1 retry):
1. Revoke stale grants by running (use the literal `/root/.claude/scripts/write-commit-grant.py` — `CONTROL_ROOT` is NOT bound in the orchestrator shell, so match Step 5's working literal path):
   ```bash
   source venv/bin/activate && python3 "/root/.claude/scripts/write-commit-grant.py" \
       --task-id "$TASK_ID" \
       --revoke-existing-for-task "$TASK_ID"
   ```
   This revokes any stale grant for `$TASK_ID` and writes a fresh one atomically.
2. Re-dispatch changelog-analyst (same prompt as Step 7).
3. Parse the retry result using the same status table as the initial result:
   - If `commit_status = committed` or `commit_status = nothing_to_commit_precommitted`: continue to Step 8 (handle as specified above for each status).
   - If `commit_status = nothing_to_commit`: warn user and continue to Step 8.
   - If retry `commit_status = failed` or unknown: print `ERROR: changelog-analyst retry failed (failure_code: <code>, reason: <reason>). Manual intervention required.` and stop — do NOT proceed to Step 8.

**Non-retryable** (`git_error`, `staging_error`, `hook_blocked`, `scope_violation`, or any other code):

Print: `ERROR: changelog-analyst failed with non-retryable failure_code: <failure_code>. Reason: <failure_reason>. Manual intervention required.`
Stop — do NOT retry, do NOT proceed to Step 8.

#### status unknown / unparseable
Treat as non-retryable. Print the raw changelog-analyst output and stop.

### Step 8: Spec-update dispatch (post-commit, deterministic fail-closed)

**This step is dispatched by `/commit` from its own orchestrator context — NOT from within changelog-analyst.** changelog-analyst has already returned before this step executes.

Skip this step entirely if ANY of the following are true:
- `BULK=true`
- `DRYRUN=true`
- `TASK_ID` is empty
- changelog-analyst did not report a successful real commit (no push-gate token written, or changelog-analyst reported an error)

**Observable Step 8 trace (AC-05 Phase B contract — task 20260524-205206 iter-2)**: when env var `COMMIT_STEP7_TRACE=1` is set, Step 8 MUST emit a deterministic single-line marker to **stderr** at every decision point. The markers are:

- `STEP7_SKIPPED: bulk=true` — at the BULK=true skip branch
- `STEP7_SKIPPED: dryrun=true` — at the DRYRUN=true skip branch
- `STEP7_SKIPPED: task_id_empty` — at the empty-TASK_ID skip branch
- `STEP7_SKIPPED: changelog_no_real_commit` — at the no-push-gate / changelog-error skip branch
- `STEP7_SPEC_UPDATE_DISPATCHED: task-id=<TASK_ID> stage=<1|2> spec_path=<SPEC_PATH>` — emitted IMMEDIATELY BEFORE the Agent dispatch in stages (1) and (2)
- `STEP7_NO_SPEC: task-id=<TASK_ID>` — at stage (3) empty-set outcome
- `STEP7_UNLINKED_SPEC: task-id=<TASK_ID> count=<N> paths=<paths>` — at stage (3) one-or-more-element outcome (fail-closed)

This trace is OFF by default (no env var). When ON, the markers are emitted to stderr only; they MUST NOT affect stdout, exit codes, or dispatch behavior. The trace is consumed by the AC-05 Phase B test harness (tests/generated/20260524-205206/test_AC_05_e5f7a9b1c4d6e8fb.py) which exercises the Step 8 SELECTION + TRACE algorithm via `scripts/step7-spec-update.py` — the executable reference embodiment of the SELECTION portion of this Step 8 specification (stages 1-4 + STEP7_* markers). The script does NOT perform the Agent dispatch described in the "Dispatch payload" subsection below — that step is the orchestrator's responsibility, performed as a Claude Code Agent call after the selection marker emits. The orchestrator MAY either follow the prose directly OR invoke the harness to compute the selection; in both cases the orchestrator must perform the real Agent dispatch when a stage 1 or stage 2 path is selected.

When `BULK=false` AND `DRYRUN=false` AND `TASK_ID` is set AND changelog-analyst reported success:

Set `DEV_DOCS_ROOT` using the same CONTROL_ROOT logic as Step 7: `DEV_DOCS_ROOT=${CONTROL_ROOT}/docs/dev` (where `CONTROL_ROOT=/root`). Use absolute paths throughout Step 8.

**Step 8 algorithm (verbatim contract — total-ordered, deterministic, fail-closed):**

The algorithm is total-ordered and mandatory. Implementers MUST NOT introduce wording that admits implementer discretion; every nondeterminism alias is forbidden by AC5-V3. Prior-cycle artifacts MUST NOT be matched: the glob and content predicates are anchored to the CURRENT cycle's `${TASK_ID}`; no cross-cycle drag-in. This operationalizes the user binding directive that prohibits loading any non-current-cycle content (verbatim Chinese phrasing preserved at `docs/dev/ticket-20260519-211515.md`, Standard 6 exemption scope).

(1) context.spec_path first.
    If `${DEV_DOCS_ROOT}/context-${TASK_ID}.json` field `spec_path` is non-null AND the file at that path exists as a regular file, dispatch `/dev` with that `spec_path` (when `COMMIT_STEP7_TRACE=1`, emit `STEP7_SPEC_UPDATE_DISPATCHED: task-id=${TASK_ID} stage=1 spec_path=<SPEC_PATH>` to stderr immediately before the dispatch). STOP.

(2) Continuation spec line (parenthetical-qualifier + markdown-bullet + backtick tolerant).
    Else parse `${DEV_DOCS_ROOT}/close-report-${TASK_ID}.md` fence-aware: read each line outside a fenced code block (skip ranges between ``` and ```). Apply the regex

        ^[-*+]?\s*Continuation spec(\s*\([^)]*\))?\s*:\s*`?(docs/dev/specs/spec-[^\s`]+\.md)`?\s*$

    against each non-fenced line, where:
      - Leading `^[-*+]?\s*` accepts an optional markdown list marker (`- `, `* `, `+ `).
      - Optional `(\s*\([^)]*\))?` accepts parenthetical qualifiers such as `(from prior NO)`, `(this cycle)`, `(rebuilt)`.
      - Inline backticks `` ` `` around the path are accepted (markdown code-span).
    The verbatim real-world close-report line proving this case is `docs/dev/close-report-20260519-175339.md:151` —

        - Continuation spec (from prior NO): `docs/dev/specs/spec-20260520-044700.md`

    Note the leading dash AND the backticks AND the parenthetical qualifier — ALL THREE must be tolerated.
    If exactly one such line matches AND the captured path exists on disk, dispatch `/dev` with that path, emit a WARNING `linked via close-report, not context.spec_path` (when `COMMIT_STEP7_TRACE=1`, also emit `STEP7_SPEC_UPDATE_DISPATCHED: task-id=${TASK_ID} stage=2 spec_path=<SPEC_PATH>` to stderr immediately before the dispatch). STOP.

(3) Mtime window + machine-readable marker predicate (final stage).
    Else glob `docs/dev/specs/spec-YYYYMMDD-HHMMSS.md` (basename pattern enforced) with mtime in [close-report mtime - 24h, close-report mtime + 1h]. For each candidate, run `grep -lF "<!-- spec-continuation-of: ${TASK_ID} -->" candidate.md` — this is the ONLY content predicate allowed; no other grep, no free-form content scan. Collect the set of candidates that pass both the basename pattern, mtime window, and machine-readable marker grep.

(4) Outcome (fail-closed).
    - If set is empty: print `No spec associated with task-id ${TASK_ID}` and exit 0 (silent, unchanged from prior behavior). When `COMMIT_STEP7_TRACE=1`, also emit `STEP7_NO_SPEC: task-id=${TASK_ID}` to stderr.
    - If set has exactly one element: print `spec produced this cycle but not linked in context: <path>` and exit non-zero (fail-closed). When `COMMIT_STEP7_TRACE=1`, also emit `STEP7_UNLINKED_SPEC: task-id=${TASK_ID} count=1 paths=<path>` to stderr.
    - If set has multiple elements: print `multiple specs produced this cycle without context linkage: <paths>; explicit context.spec_path required` and exit non-zero (fail-closed). When `COMMIT_STEP7_TRACE=1`, also emit `STEP7_UNLINKED_SPEC: task-id=${TASK_ID} count=<N> paths=<paths>` to stderr.

**Dispatch payload (when stage 1 or 2 selects a path)**

Dispatch an inline Agent (do NOT invoke `/spec-update` as a slash-command) with the following prompt, substituting `TASK_ID`, `SPEC_PATH`, and `DEV_DOCS_ROOT`:

```
You are executing the spec-continuation logic for task-id=<TASK_ID>.

Target spec file: <SPEC_PATH> (absolute path — this file exists; update it in place).

DO NOT:
- Invoke /spec-update as a slash command
- Create a new spec file; only update the existing one at <SPEC_PATH>
- Overwrite or delete prior "### Cycle N" sections
- Modify any git state, commit grants, push tokens, or command files
- Write any artifacts outside <SPEC_PATH>
- Read or modify files outside <DEV_DOCS_ROOT>/, <SPEC_PATH>, and /root/.claude/commands/spec-update.md (allowed: read spec-update.md for instructions)

Follow the ## Continuation-spec mode instructions from /root/.claude/commands/spec-update.md exactly:

- The active task-id is <TASK_ID>.
- The target spec to update is <SPEC_PATH>. Update this spec; do not create a new one.
- Gather source artifacts from <DEV_DOCS_ROOT>/:
    context-<TASK_ID>.json, dev-report-<TASK_ID>*.json, qa-report-<TASK_ID>*.json,
    close-report-<TASK_ID>.md, completion-<TASK_ID>.md
- Determine the next cycle number: max(existing "### Cycle N" headings) + 1; if none exist, use Cycle 1.
- Append the new cycle block to the spec. Never overwrite prior cycles.
- Populate sections 2-8 per the spec-update continuation-spec instructions.
- Output the spec path when done.
```

If the Agent dispatch fails for any reason (error, timeout, or exception), print `WARNING: spec-update dispatch failed for task-id=${TASK_ID} — spec not updated` and continue. The commit is already recorded; Step 8 failure does NOT roll back or affect the commit.

**Reversal-rationale guidance for changelog-analyst (R9 cross-reference)**: the binding rule that any forward-fix commit which intentionally reverses prior behavior MUST include `Reverses <SHA>: <one-line rationale for why prior reasoning no longer holds>` in the commit-message body lives in `agents/changelog-analyst.md` Phase 6 (the SOLE binding landing). `/commit` orchestrator does NOT enforce the rule directly; changelog-analyst owns commit-message construction and is the contract holder.

## Close-gate verification reference

The close-gate is the only guard this command owns. All git operations (staging, committing,
nested-repo handling, push-gate write) are delegated entirely to `changelog-analyst`.

## Privilege guard compatibility note

`pretool-git-privilege-guard.py` is REGISTERED in `settings.json` (PreToolUse, Bash matcher).

Authorization flow for changelog-analyst commits:

1. `/commit` writes `/tmp/claude-commit-grant-<SID>-<nonce>.json` before dispatching changelog-analyst (Step 5).
2. `_evaluate_commit(command, data)` calls `_find_grant('commit', sid)` using the subagent's session_id from the PreToolUse payload.
3. If SID-specific grant not found (subagent session_id differs from orchestrator's CLAUDE_SESSION_ID), falls back to `_find_grant_any('commit')` — any valid unexpired commit grant is accepted.
4. Grant validates: expires_at (30 min window), single-use unlink. No message-hash validation.

**DO NOT extend `BLESSED_BRIDGE_RE` with conventional commit patterns** (e.g. `^feat\(`, `^fix\(`).
This would allow any agent that learns the commit format to bypass the guard — destroying the
security model. The grant-file mechanism provides the correct narrow authorization.

auto-bulk bridge commits (matching BLESSED_BRIDGE_RE) require a **bulk-commit sentinel**
written by `/commit --bulk` Step 5 (`scripts/write-bulk-commit-sentinel.py`, 30 min TTL,
multi-use). Without it the guard blocks the commit even if the message prefix is correct.
changelog-analyst non-bulk commits use the single-use grant-file path.
The BLESSED_BRIDGE_RE check runs first in `_evaluate_commit`, followed by the sentinel check.

## Related

- `/close <task-id>` — must run before `/commit` (produces the close-report gate token)
- `/push` — must run after `/commit` (reads the push-gate token written by changelog-analyst)
- `agents/changelog-analyst.md` — the subagent that does all git work
