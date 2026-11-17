# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `/spec-update --update` mode: append enrichment content to an existing
  spec's Section 5 without implying a new dev cycle, distinct from the
  default continuation-spec mode. Requires an explicit `--spec <path>`
  naming an existing spec file; there is no auto-resolution fallback. Also
  added an explicit `--continue` flag as a named alias for the existing
  default (no-flag) continuation-spec behavior. `--update`, `--continue`,
  and `--temp` are mutually exclusive.

### Changed
- The harness-switch rule (`hooks/pretool-harness-switch-guard.py`) refuses an agent's change to
  the `env`, `hooks`, `disableAllHooks` or `permissions` of a Claude Code settings file: a
  project's `.claude/settings.json` or `.claude/settings.local.json`, `managed-settings.json` and
  its `managed-settings.d/`, and `.claude.json`. Write, Edit and MultiEdit are judged by the
  keys' resulting values; a Bash write, move or removal of such a file is refused unless it is a
  literal `echo` the Write rule passes. Other keys, other JSON files and reads stay free; the
  owner edits the file or grants one call with `/allow`.
- Moved `/spec-update`'s inline rename-history note out of the live command
  body and frontmatter into this changelog entry: the command was previously
  `/update` at `~/.claude/commands/update.md`, then renamed to
  `/spec-continue`, and is now `/spec-update`. The renames (which predate the
  `1.0.0` tag) resolved a name collision and improved clarity; that history
  no longer lives in the command's operative instructions.
- **Version claim held below a stable `1.0.0`.** `VERSION` now reads `1.0.0-dev`.
  The previous unconditioned `1.0.0` marker overclaimed: it was never published as
  a git tag, and the release-hygiene work it implies was still open. The marker is
  intentionally held at a pre-release form until this release-hygiene lane's own
  requirements pass — generated-not-tracked `settings.json`, CI hard-failing (not
  advisory) on author-path and workspace-path residue in public-core, commit-SHA
  pinned GitHub Actions, hash-pinned Python dependencies, an enforced non-root
  clean-install smoke, and a signed release archive published with checksums, an
  SBOM and provenance and verified against the PUBLISHED artifact. Re-promoting the
  marker to a stable version is a separate, later decision and is deliberately not
  gated here.

### Fixed
- **G1's order rule (R17) reads every way an agent's end comes back.** `hooks/pretool-obligation-gate.py`
  took a dispatch as returned only by its own Agent call's ok result. A close QA cut off and resumed
  with SendMessage (its end: the task-notification naming it), or cut off after it had stopped by
  itself (its end: its own transcript's stop and SubagentStop record), refused `/commit`'s planning
  dispatch with `producer_not_stopped ... which has not returned a result` while its CLOSE: YES report
  was on disk; a background launch, whose result comes back while the agent runs, counted as
  returned at once. The rule now takes an agent as stopped when its latest end (its Agent call's
  result, a completed task-notification, a /restart journal that saw the response, or a recorded
  stop of a cut agent that was not resumed) follows its latest start (the dispatch, each SendMessage
  resume); a running, resumed or failed agent stays refused. The CLI records it reads are recorded by
  `scripts/cli-fixture-record.sh` (now ten runs). Covered by `hooks/tests/test_obligation_gate_returns.py`.
- **Every reader of "has this dispatch returned" reads it as G1 does.** The reading moved from the
  gate into `hooks/lib/agent_returns.py` (`Returns`: when the agent stopped and its reply then: its
  Agent call's result, the `<result>` of a completed task-notification, or a cut agent's own last
  reply), and three readers that took only an ok Agent result now use it. The `/commit --bulk`
  Stop read the planning dry-run's `dryrun` block when the landing analyst was cut and resumed, or
  cut after its stop, and let the commit end whatever the landing reported; with no planning block
  before it, a landing that reported `committed` that way, or in the background, held the Stop with
  `commit --bulk: no changelog-analyst status block in this /commit`. A close QA that landed
  `CLOSE: YES` by those channels required no rating, so `/close` ended without `close <task>: the
  close-rating question (AskUserQuestion) was not asked`. G1's ask-first let the next dispatch out
  without asking round 2 a resumed BA had written (round 1: it asked for a new BA intake instead),
  and asked a round a background BA was still writing. `command_span.Span.dispatches()` lists a
  span's dispatches however their calls came back. The replay's `/restart` writes the resumed
  agent's end as the CLI records it: the SendMessage result names the agent, and the
  task-notification answers that SendMessage and is delivered into the running turn (enqueue,
  `queued_command`, remove); it wrote a lone queue-operation answering the cut Agent call.
  `requirement_round.asked` and `spec_path` read only the main agent's own calls and are unchanged.
  Covered by `hooks/tests/test_agent_end_readers.py`.
- **The worktree guard can no longer lock a session.** `hooks/pretool-worktree-guard.sh`
  runs before every tool and exited 2 while any agent worktree was behind the main
  branch. That blocked the `git worktree remove` it recommended, and every Read,
  AskUserQuestion and Agent call, while the other half of its advice, `git branch -D`,
  is refused by `pretool-bash-safety.sh`; only the human could end the state. The
  guard is now advisory: it always exits 0 and hands the lesson (a stale worktree
  causes merge conflicts) to Claude as PreToolUse `additionalContext` and to the user
  as `systemMessage`, with the exact `git worktree remove` command for each stale
  worktree. Branch deletion is left to the user. Covered by
  `hooks/tests/test_worktree_guard.py`.

## [1.0.0] - 2026-07-05

### Added
- Multi-layer orchestration pipeline: /spec -> /dev -> /close -> /commit -> /push
- BA/QA/dev subagent roles with structured JSON context contracts
- Hook-enforced safety gates (pretool-bash-safety.sh, pretool-git-privilege-guard.py)
- Parallel-dev worker model with canonical aggregate dev-report
- Graphify knowledge graph integration (advisory, non-blocking)
- Overnight long-running session mode with wall-clock enforcement
- Checkpoint-based spec system (/spec with split views, cp-state tracking)
- Break-glass grant mechanism for authorized privilege operations (/do, /allow)
- Session git-init and canary-verify startup hooks for newcomer safety
- Path-qualified git invocation detection (git_command_classifier.py)
- Doc-sync auto-indexing with excluded pattern support
- World-class readiness improvements: README overhaul, CI, test infrastructure
- QA-of-BA pre-code review gate (analysis validated before any code is written)
- Schema-enforced cycle-contract validation with Draft7 JSON schemas (overnight pipeline)
- Self-updating documentation via PostToolUse doc-sync hooks
- UI-audit skill suite (axe-core, APCA contrast, 58-rule anti-pattern catalog, beauty score)
- Adversarial second opinion via --codex flag integration

[Unreleased]: https://github.com/Yugoge/awesome-claude-harness/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Yugoge/awesome-claude-harness/releases/tag/v1.0.0
