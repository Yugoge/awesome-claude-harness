# awesome-claude-harness

An unattended development harness for Claude Code. Give it a requirement and go to work: it finds the root cause, asks you only the decisions that are yours, then builds and verifies; the commands you type to land the work, `/close`, `/commit` and `/push`, have agents review, commit and push it, with no human review in the loop. Prompts guide the agents; hooks refuse what prompts can only ask for.

After you type `/dev <requirement>`:

1. A hook writes your words to disk as the binding spec before any agent runs, so no agent works from a reformulation.
2. A BA agent finds the root cause and must cite evidence (file and line, search results, git history); a QA agent checks that analysis before any code exists. A question reaches you only for a decision the request, the code and sensible defaults cannot settle.
3. Dev agents build, one issue per agent, in parallel lanes inside the one cycle; QA verifies and sends a failure back to dev until it passes.
4. The Stop gate keeps the session open until every todo is done and every artifact is checked by code; only the finished work, your `/stop` or switching the gate off in the environment releases it.
5. You type `/close`, `/commit` and `/push` (and `/merge` for branches); agents review, commit and push under grants that hooks check.

What is proven and what is not is stated on the [status page](docs/status.md).

<p>
<img alt="license" src="https://img.shields.io/badge/license-MIT-000000">
</p>

## Why this exists

Autonomous coding agents hurt in places the field has already documented. Each point names its source, then what this repository does about it.

- **A person stays in the loop.** Practitioner guides keep developer review, testing and security review before merge ([Augment Code](https://www.augmentcode.com/guides/autonomous-engineering-loop), [Kilo](https://kilo.ai/articles/beyond-autocomplete)). In a study of 37,623 agent-authored pull requests, Claude Code's waited a median of 12.6 hours for a first human review ([arXiv](https://arxiv.org/pdf/2609.17598)). *Here:* a BA or dev agent raises a question and the orchestrator asks you, in the turn and with the question tool, only for a decision the request, the code and sensible defaults cannot settle. The gate before landing is automated verification, the case [one paper](https://arxiv.org/abs/2606.13175v1) argues for (an argument, not an empirical study): inspectors and QA at `/close`, QA before and after dev.
- **Autonomy depends on a person building the test oracle.** The parallel-Claude C compiler rested on test suites and verifiers a human wrote, and on new tests added as mistakes showed ([Anthropic](https://anthropic.com/engineering/building-c-compiler)). *Here:* the oracle lives in `tests/` and runs in CI on every pull request. The replay suite drives each pipeline through the real hooks, the fault replays inject failures, and the artifact check demands one producer and a reader for every artifact.
- **Instructions are not enforcement.** Hooks are the deterministic layer ([Claude Code docs](https://code.claude.com/docs/en/best-practices)); `CLAUDE.md` is context, not enforced configuration ([Towards AI](https://towardsai.com/p/machine-learning/claude-code-skills-vs-subagents-vs-hooks-vs-workflows-which-to-use-in-2026)). *Here:* what must hold is a hook, not a sentence in a prompt. [The ledger](docs/ENFORCEMENT-LEDGER.md) says how far each hook is proven, and a replay test fails when a replay reaches a blocking site that no action clears. The proof table counts the blocking sites its enumerator finds in the registered hooks' code, by class; those with no clearing class are counted on the [status page](docs/status.md).
- **Claims outrun the code.** Critics of Cursor's agent-built browser found recent commits that do not compile and failing CI on main ([The Register](https://www.theregister.com/2026/01/26/cursor_opinion/)). *Here:* every figure this README states about the repository is produced from it by `scripts/readme_facts.py` and `scripts/generate-hero-status.py`, and `scripts/verify-claims.sh` fails CI when one drifts or a numeral is typed by hand outside a sourced, declared figure.

**What still needs you:** the decisions the request, the code and sensible defaults cannot settle, and your rating of the work. `/close` asks one rating question after a landed cycle, and you may skip it. `/dev-overnight` asks nobody: it decides by experiment, else by the question's default, and lists each decision in its summary.

## Status

The measured proof, the hero recording, the claim rows and the known limits are on the [status page](docs/status.md).

## Install

### Full install: clone + init

```bash
git clone https://github.com/Yugoge/awesome-claude-harness.git ~/.claude   # needs an empty ~/.claude
~/.claude/scripts/bootstrap            # init: asks once per optional module; ends with the preflight
bash ~/.claude/examples/guard-demo/run-demo.sh   # watch a guard refuse, then allow
```

Then, in Claude Code, type `/dev <your requirement>`.

### Guardrails only: the installer core profile

```bash
scripts/install/install --profile core   # from a checkout; guardrails only, in an isolated directory
```

Other install locations, the settings overlay, dependencies and troubleshooting: [installation](docs/installation.md).

## The pipeline

Each step, what goes wrong without it (the repository's own words where it has them), and the mechanism that makes it happen. Each mechanism's proof level is the ledger's, not this table's.

| Step | What goes wrong without it | Mechanism |
|---|---|---|
| Capture your words | Subagents see a reformulation, not "the user's literal request" | `hooks/prompt-workflow.py` writes your prompt to `docs/dev/user-requirement-<id>.md`, create-exclusive |
| Declare what each agent owes | Missing artifacts surface at `/close`, "where the producing agent's context is already gone" | `hooks/pretool-obligation-gate.py` refuses a dispatch with no obligation block, or one naming an artifact before its producer returned |
| Root cause | "Misanalysis cascades into wasted dev cycles" | BA's evidence rules in `agents/ba.md`; `schemas/context.v1.json` is checked at BA's stop by `hooks/subagentstop-artifact-contract-enforce.py` |
| Check before code | A wasted dev and QA cycle | QA in BA-validation mode; `hooks/pretool-todo-validate.py` completes the step only after an ok QA dispatch; any verdict but pass is a gap at Stop (`scripts/resolve-dev-artifact-chain.py`) |
| Build | An agent writes outside its job; QA runs before every lane returned | `hooks/pretool-tool-policy.py` role write paths (`policies/tool-policy.v1.json`); `hooks/pretool-aggregate-check.py` refuses a QA dispatch without the fan-out aggregate |
| Verify | "A false PASS is worse than a false FAIL" | QA against the acceptance criteria; `hooks/subagentstop-e2e-enforce.py` reads only the recorded end-to-end status and cannot see the rendering |
| Cannot end early | Unfinished work handed to `/close` | The Stop gate (`hooks/stop-command-gate.py`) exits `2` until every todo is complete and the chain passes; released by the finished work, by your `/stop`, or by switching the gate off in the environment |
| Go or no-go | Shipping work with an unresolved finding | `/close`: inspectors on the diff, QA on the workflow-integrity checks, a last line `CLOSE: YES` or `CLOSE_FINDINGS`; then one rating question to you |
| Commit | A bulk commit skips `/close`'s gate and may hold junk, secrets or scope contamination | `/commit`: changelog-analyst and a pre-commit QA; `scripts/write-commit-grant.py` mints a single-use, time-boxed grant that `hooks/pretool-git-privilege-guard.py` binds to repository, branch, HEAD and caller |
| Push and merge | A sweep authored by the orchestrator "with no human signoff" | `/push`: push-analyst and `scripts/execute-push.py`, which exits `3` without a token naming an ancestor of HEAD; the guard refuses an agent's own `git push` and `git commit` |

Words used here:

- **Orchestrator**: your main Claude Code session. It routes work to agents, and a hook limits what it may write itself (`hooks/pretool-orchestrator-gate.py`).
- **BA, QA, dev**: the business-analyst agent that analyses the requirement and its root cause, the quality-assurance agent that verifies, and the implementation agent that builds (`agents/ba.md`, `agents/qa.md`, `agents/dev.md`).
- **Hook**: a script Claude Code runs around a tool call or at Stop. In this repository a hook that exits `2` refuses the action.
- **Stop gate**: the hook that decides whether a session may end.
- **Grant**: a hook-checked permission, minted by a command you type (`/commit`, `/push`, `/allow`), that lets one operation through.
- **Ledger**: `docs/ENFORCEMENT-LEDGER.md`, one row per registered hook with how it behaves and how far that is proven.
- **Replay**: a pipeline run through the real hooks in a sandbox, with synthetic tool calls instead of a live Claude Code session.

## The command surface

Generated from the frontmatter of `commands/*.md`. A command marked owner-only carries `disable-model-invocation: true` and a `Skill(...)` deny in `settings.json`, so an agent cannot start it.

<!-- BEGIN canonical-region id=commands — generated by scripts/generate-hero-status.py; do not hand-edit -->
| Command | Group | Typed by | What it does |
|---|---|---|---|
| `/spec [--codex] [<requirement>]` | Spec | owner only | Write a durable spec from your requirement and split it into per-agent briefs with checkpoints, for /dev or /dev-overnight to build from. |
| `/spec-update [--update --spec <path> \| --continue \| --temp] [--spec <path>] [what the next session should focus on]` | Spec | owner only | Turn unfinished work into a continuation spec for a fresh session, enrich an existing spec, or write a short session note. |
| `/dev [--codex] [--spec <path>] <requirement>` | Develop | owner only | Build a requirement end to end: BA finds the root cause, QA checks it, dev builds in parallel one-issue lanes, QA verifies until it passes. |
| `/dev-command` | Develop | owner only | The /dev workflow for building a slash command, a subagent or another harness file, with the differences such a file needs. |
| `/dev-overnight` | Develop | owner only | Run unattended until an end time: explore, fix each real issue in its own pipeline, decide without the owner, and commit nothing. |
| `/redev [--codex] [--spec <path>] [<requirement>]` | Develop | owner only | Start a fresh /dev cycle in the same conversation without repeating the text of /dev, to save context. |
| `/checkpoint` | Ship | owner only | Snapshot the working tree to the safety ref `refs/checkpoints/<branch>` without moving HEAD, touching the index or pushing. |
| `/close [--codex \| --auto \| --late-repair] [<task-id>\|<path>]` | Ship | owner only | Close the cycle: finish what is unfinished, have inspectors and QA judge it, end on `CLOSE: YES` or the findings, then ask you to rate it. |
| `/commit` | Ship | owner only | Commit a task's changes through the changelog analyst, closing an unfinished cycle first and staging only the task's own files. |
| `/merge` | Ship | owner only | Merge a branch or commit into the default branch with a real merge that keeps the full history, after a pre-merge analysis. |
| `/pull` | Ship | owner only | Pull with rebase, stashing and restoring local changes and stopping on conflicts, then summarize the risk of what arrived. |
| `/push` | Ship | owner only | Publish the current branch through the push wrapper after the push analyst reviews what would go out; it needs a commit made by /commit. |
| `/clean [--codex]` | Quality | owner only | Clean up the project: inspectors find misplaced docs, byproducts and style violations, and the cleaner applies the approved fixes. |
| `/test` | Quality | owner only | Check the project's tests against edge cases found in its git history, then run them and report. |
| `/allow` | Control | owner only | Grant one single-use permission for an operation a grant-aware safety hook refused; it never overrides a settings deny rule. |
| `/codex [prompt or --review or --model <model> <prompt>]` | Control | owner or agent | Ask OpenAI Codex for a second opinion, a code review or a delegated coding task, through an isolated wrapper. |
| `/do` | Control | owner only | Let the main agent do one task itself for this turn, past the orchestrator gate; it does not cover commits or pushes. |
| `/restart` | Control | owner only | Resume every subagent a usage limit interrupted, by its original agent id; with none to resume, continue the main agent. |
| `/stop` | Control | owner only | End the overnight run before its end time, or any command the Stop gate holds; only the owner can type it. |
| `/tickets [--format table\|json]` | Control | owner or agent | Print a read-only table of every ticket, spec and lane, with its state and next action. |

20 commands, generated from the frontmatter of `commands/*.md`. An optional module's own commands are described with the module in the [installation guide](docs/installation.md).
<!-- END canonical-region id=commands -->

## The cast of agents

Generated from the frontmatter of `agents/*.md`. The orchestrator dispatches each by describing the problem, never the tooling.

<!-- BEGIN canonical-region id=agents — generated by scripts/generate-hero-status.py; do not hand-edit -->
| Agent | What it does |
|---|---|
| `architect` | Reviews architecture: structural issues, technical debt, dependency problems and inconsistent patterns. |
| `ba` | Analyses the requirement and finds its root cause with cited evidence, then writes the spec, the context and the acceptance criteria, or asks. |
| `changelog-analyst` | Stages a task's files, writes the conventional commit message and the push-gate token; dispatched only by /commit. |
| `cleaner` | Applies the cleanup actions approved from the inspectors' reports and reports what it did. |
| `cleanliness-inspector` | Finds misplaced docs, duplicates, temporary files and build artifacts, and recommends a cleanup. |
| `dev` | Implements the analysed plan with the smallest change that passes the acceptance criteria, and reports what it changed and ran. |
| `git-edge-case-analyst` | Mines git history for edge cases and past violations, and recommends how to prevent them. |
| `graphify` | Refreshes the optional code-graph cache and extracts the subgraph around the change for dev and QA; it analyses nothing itself. |
| `merge-analyst` | Checks divergence, conflicts and overnight state before a merge and writes a short-lived merge grant; dispatched only by /merge. |
| `pm` | Runs the overnight cycle's planning: a test plan from exploring the running app, triage of the specialists' issues, and the retrospective. |
| `product-owner` | Checks product logic: consistency, feature completeness, user flows and business-logic bugs. |
| `prompt-inspector` | Finds verbose, non-functional text in command and agent prompts. |
| `pull-analyst` | Summarizes the risk of the commits a pull brought in; advisory, it writes no grant and blocks nothing. |
| `push-analyst` | Checks what a push would publish for sensitive files, divergence and branch protection, and writes the push grant; dispatched only by /push. |
| `qa` | Verifies the analysis before any code and the implementation after it against the acceptance criteria; when in doubt it fails. |
| `rule-inspector` | Discovers each folder's organisation rules from git history and documents them. |
| `spec` | Splits a spec into the briefs each agent needs and adds checkpoints; dispatched by /spec. |
| `style-inspector` | Audits development standards: no hardcoding, naming, environment use, step numbering, language and concise documentation. |
| `test-executor` | Runs the project's script and instruction tests and reports the results. |
| `test-validator` | Checks the tests' syntax, dependencies and quality before they run. |
| `test-writer` | Writes failing test skeletons from the acceptance criteria and keeps the task's test manifest; dispatched for standard or risky tasks. |
| `ui-specialist` | Reviews visual design: design-system adherence, consistent styling, responsive layout and component quality, with a beauty score. |
| `user` | Simulates an end user: tries real usage scenarios and reports broken flows, friction and confusing behaviour. |

23 agents, generated from the frontmatter of `agents/*.md`.
<!-- END canonical-region id=agents -->

Usage limit hit? `/restart` resumes every recoverable interrupted child in the current parent transcript by its original agent id; it never creates a replacement agent.

## Design principles

- **Hooks decide, prompts guide.** A rule that must hold is a hook that exits with the blocking code. Prompts carry judgment and point at the hook instead of repeating it. The ledger states, per hook, how far that is proven.
- **No flow may strand you.** The suite's enumerator finds the blocking sites in the registered hooks' code, and a replay fails CI when it reaches one that no action clears. Your `/stop` and Esc are the exits no hook gates.
- **One producer per fact.** Every artifact has one producer and at least one reader that decides on it; the artifact check enforces that in CI. Every figure about the repository in this README has one producer, `scripts/readme_facts.py` or `scripts/generate-hero-status.py`, and `scripts/verify-claims.sh` re-derives it.
- **You decide what only you can; evidence decides the rest.** A question reaches you only when the request, the code and sensible defaults cannot settle it. In `/dev-overnight` an experiment decides, else the question's default, and the summary lists each decision.

## Documentation

- [Status](docs/status.md): the measured proof, the hero recording, the claim rows and the known limits.
- [Installation](docs/installation.md): clone and init, the settings overlay, the guardrails-only profile, dependencies, troubleshooting.
- [The git protection kernel](docs/git-protection-kernel.md): what is refused in git, the grants, and what each guard does not see.
- [The overnight pipeline](docs/overnight-pipeline.md): `/dev-overnight` until a wall-clock end time.
- [How it works](docs/how-it-works.md): the architecture, the agents, the guardrails, the project structure.
- [Extending the harness](docs/extending.md) and the [FAQ](docs/faq.md).
- [The enforcement ledger](docs/ENFORCEMENT-LEDGER.md), the [threat model](docs/THREAT-MODEL.md) and the [adversarial corpus](docs/ADVERSARIAL-CORPUS.md).
- [`CLAUDE.md`](CLAUDE.md), [`ARCHITECTURE.md`](ARCHITECTURE.md) and the [changelog](CHANGELOG.md).

## Acknowledgements

This configuration grew out of, and remains grateful to:

- [Claude Code](https://claude.com/claude-code) and the official [documentation](https://docs.claude.com/en/docs/claude-code).
- [fcakyon/claude-codex-settings](https://github.com/fcakyon/claude-codex-settings) — an early real-world configuration reference.
- The broader Claude Code community, whose shared patterns and hard-won lessons are baked into the hooks and agents here.

## License

Released under the **MIT License** — free to use, copy, modify, and adapt for your own `~/.claude`. Source: [`Yugoge/awesome-claude-harness`](https://github.com/Yugoge/awesome-claude-harness).
