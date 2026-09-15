# Quarantine record: phantom `/dev` cycle `dev-20260915-020044`

**Executed by**: dev subagent, task `dev-20260915-051511-b`, 2026-09-15T11:58Z
**Quarantine root**: `.claude/quarantined-phantom-dev-cycles/dev-20260915-020044/` (manifest + note inside; this record lives outside it, as required)

## Origin (cross-referenced, not re-narrated)

The full account of how `dev-20260915-020044` came to exist — a quoted
command-line string inside a user message being misfired by the harness's
command-detection mechanism as a real invocation — is already documented at
`docs/dev/specs/spec-20260914-052140.md`, Section 5.4's twin entry — the
"### 5.4 的孪生病症(反方向):散文中引用的命令文本被当真触发" subsection
(heading-anchored, not line-numbered). That record is the authoritative
origin account; it is not repeated here. This citation is heading-anchored,
not line-numbered, because that spec file is under active, ongoing edit by a
different, concurrent session in this shared multi-session worktree tonight
(the controller's own spec-authoring workflow) — a line-number citation would
have silently gone stale again regardless of what number was originally
written, which is why the citation form itself was changed to a heading
anchor rather than simply corrected to a new line range. In one sentence: no
development was ever requested under this task-id, and none occurred — the
task-id's only content is the harness's own mechanical byproducts plus one
requirement-doc file whose body text is literally the user's complaint about
the misfire, not a requirement.

## Search method (bypass-aware)

The default `grep` in this environment is a `.gitignore`-respecting wrapper
(`ugrep ... --ignore-files --hidden`) that produces false negatives on the
gitignored paths these artifacts live under (`docs/dev/`, `.claude/dev-registry/`).
All searches below used `command grep` (bypassing the wrapper) directly.

1. **Basename-pattern-first, structural pre-exclusion** for any file whose
   basename matches `.claude/workflow-<session-id>.json`, evaluated BEFORE any
   content matching — implemented as a two-stage grep: stage 1 excludes
   `.claude/` entirely (`--exclude-dir=.claude`); stage 2 rescans `./.claude`
   alone with a basename-only `--exclude='workflow-*.json'` (correctly scoped
   to `.claude/` by the search root; verified NOT to over-match
   `.claude/workflow-history/**/{bookmark,todos}.json`, whose entries carry a
   different basename). Real GNU grep's `--exclude=GLOB` is basename-only and
   does not support a `/`-containing path-scoped glob (empirically verified: a
   single `--exclude='.claude/workflow-*.json'` on one recursive call has zero
   effect). `find -path`/bash `case "$f" in ./.claude/workflow-*.json)` were
   both tried and both over-match into `workflow-history/**`, because `*`
   matches `/` in both forms.
2. **Path-OR-content substring filter** for the real cycle's own task-id
   (`20260915-051511`), applied only to files that survive step 1, to exclude
   this lane's (and its sibling QA/BA passes') own investigation deliverables,
   which legitimately quote the phantom id in prose.
3. `command grep -rl "dev-20260915-020044" . --exclude-dir=.git` from repo
   root (content search), `find . -iname "*20260915-020044*" -not -path
   "./.git/*"` (filename search, to catch the one true positive whose body
   text does not contain the literal task-id string), and a session-id
   correlation pass on the controller session `0a0db999-3273-4172-82e1-9ef1c91a8fa2`.

Pre-move, this pipeline returned exactly 21 content-matching true positives +
1 filename-only true positive (`docs/dev/user-requirement-dev-20260915-020044.md`)
= 22 files across 3 path groups. Post-move, the same pipeline (with the
quarantine directory additionally excluded) returns empty.

## Inventory: relocated (3 groups, 22 files)

| # | Group | Files | Identity evidence |
|---|-------|-------|--------------------|
| 1 | `.claude/dev-registry/dev-20260915-020044/` | 20 files (18 per-subagent check-ins + `codex-enforce.json` + `e2e-enforce.json`) | dirname = exact task-id; sentinel JSONs carry `"dev_session_id": "dev-20260915-020044"` |
| 2 | `.claude/dev-start-replays/0a0db999-3273-4172-82e1-9ef1c91a8fa2/c0e2280e0968f70cea9a79f345b72e20389b7263562d1c8aba4a89cd58218906.json` | 1 file | own stdout content: `"DEV_SESSION_ID pre-initialized by hook: dev-20260915-020044"` |
| 3 | `docs/dev/user-requirement-dev-20260915-020044.md` | 1 file | filename = exact task-id; body is the user's complaint text, not a requirement |

All 22 files were moved (never copied, never deleted) one file at a time from
their original path to
`.claude/quarantined-phantom-dev-cycles/dev-20260915-020044/<original relative path>`,
with size + sha256 verified identical immediately after each move (see
`original-path-manifest.json` inside the quarantine root for the full
per-file mapping and hashes). Zero files remain at their original paths.

## Inventory: content-matched but categorically excluded (2 files, NOT moved)

Both files below content-match the phantom id `dev-20260915-020044` but are
**not** phantom-cycle residue — they are live `.claude/workflow-*.json`
workflow-gate bookmarks that `hooks/pretool-workflow-gate.py` actively reads
and writes for real, currently-relevant Claude Code sessions. Per a direct
user override (see `docs/dev/ticket-20260915-051511-b.md` Revision Log —
Round 3), any file whose basename matches the `.claude/workflow-<session-id>.json`
pattern is categorically excluded from this move, evaluated structurally
before content is ever read — **content-matched but excluded, referred to the
user for final disposition**:

| File | Content-matches phantom id | Content-matches real id `20260915-051511` | Why excluded |
|------|:---:|:---:|--------------|
| `.claude/workflow-0a0db999-3273-4172-82e1-9ef1c91a8fa2.json` | yes | no | The phantom-misfired session's own live workflow-gate bookmark — `hooks/pretool-workflow-gate.py` gates that session's tool calls with it. Not proven-dead residue; reclassified from a round-1/2 confirmed relocate target to a categorical exclusion by direct user override. |
| `.claude/workflow-ec2ae4f0-a321-4d7d-a711-8ae6da3a0524.json` | yes | yes | This real cycle's own live, actively-rewritten workflow-gate bookmark. Content-matches the phantom id only because its `arguments` field is this cycle's own user-requirement text, which quotes the incident in prose. |

Both files were verified byte-identical (size + sha256) before and after this
lane's entire operation — they were never touched.

## The general lesson (basename-pattern-first exclusion)

This lane's correction history (four rounds — two QA rejections, one direct
user review, one narrow QA-driven machine-check fix) converged on a single
general hazard that must be carried forward, verbatim, into any future
identifier-quarantine work:

> A single string can simultaneously be an identifier to search for and live
> process state that a running mechanism reads and writes, and no purely
> reactive content-matching rule can safely distinguish those two
> occurrences — only a pre-emptive structural exclusion evaluated before the
> identifier search is safe.

Concretely: round 2's Residual-Hit Rule excluded `.claude/workflow-ec2ae4f0-....json`
because its *current content* happened to carry the real task-id — a
heuristic that worked at the time but was not a structural guarantee, since
that file's content is rewritten continuously as the hosting session's own
workflow state advances. A future content/schema change to that file could
have silently defeated the content-based exclusion and caused a live
workflow-gate bookmark to be misclassified as phantom-cycle residue and moved.
The fix applied in round 3 (and used throughout this move) is a basename
pattern (`.claude/workflow-<session-id>.json`) evaluated *before* any content
is read — it does not depend on, and cannot be defeated by, what either
bookmark file currently contains.

## Known open item (Should-Have, not actioned this cycle)

`/root/.claude.bak/` (12GB, outside the repo) contains an apparently
live-synced mirror of the same phantom-cycle artifacts (mtime-correlated to
the 2026-09-15T02:00:44Z incident). Its sync mechanism and direction are
unknown and were judged outside this lane's investigation budget. Flagged
here for a follow-up decision; not touched.
