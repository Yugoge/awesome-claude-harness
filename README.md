<div align="center">

<a href="#install"><img src=".github/assets/logo.png" width="420" alt="awesome-claude-harness"></a>

**An agent operating system for Claude Code.**

[![license: MIT](https://img.shields.io/badge/license-MIT-000000)](LICENSE)
[![Claude Code: required](https://img.shields.io/badge/Claude_Code-required-000000)](#install)
[![Codex: optional](https://img.shields.io/badge/Codex-optional-555555)](#install)
[![proof: status page](https://img.shields.io/badge/proof-status_page-000000)](docs/status.md)

[Install](#install) • [Pipeline](#the-full-pipeline) • [Example](#pipeline-in-action) • [Architecture](#system-architecture) • [Docs](#documentation)

</div>

<a id="at-a-glance"></a>The main session is the orchestrator. It routes. One-issue agents do the work. A git kernel gates every agent commit, push, merge and hard reset. The overnight run works while you sleep. You land it in the morning.

> A dev agent used `git stash` as a scratch buffer, then a wide-path checkout. Seventeen days of UI work, gone. It reported that as an accident.
>
> An orchestrator read "commit and push everything" as a ninety-three-file commit and push. Nobody signed off.

Both are refused now. Only something you typed lets one through.

## Install

> **Needs:** `python3`, `git`, `jq` and Claude Code. Codex is optional. Only `--codex` and `/codex` use it. They need the OpenAI Codex CLI and an isolation wrapper you supply (`CODEX_ISO_BIN`).

### Full install: clone + init

```bash
# needs an empty ~/.claude
git clone https://github.com/Yugoge/awesome-claude-harness.git ~/.claude
# init: asks once per optional module, ends with the preflight
~/.claude/scripts/bootstrap
# sandboxed demo: a push refused, allowed once by a grant, refused again
python3 ~/.claude/scripts/capture-hero-run.py --check-only
```

**`~/.claude` already in use?** `git clone` refuses a target that is not empty. Move yours aside, or use [another install location](docs/installation.md#other-install-locations).

After init, `git status` stays clean. Your machine's own values live in an overlay. They never show up as a diff and never reach a commit.

The demo needs no Claude Code. It runs the real hooks in a sandbox. It writes nothing into the checkout. It prints where it saved its log. Then, in Claude Code:

```text
/dev the login button is misaligned on mobile
```

Before any code, it asks you. Intent, scope, edge cases, acceptance, in Claude Code's question dialog. Skip what you like. A skipped question settles to its stated default.

**Ways out.** `/stop` ends a held command or the overnight run. Esc interrupts a loop. `/allow` lets one refused operation through, once, never past a `settings.json` deny. `/restart` resumes what a usage limit cut off. `/harness off` switches the whole harness off. `/harness on` restores exactly what it removed.

### Guardrails only: the installer core profile

A few hooks, no agents, no overlay, no init. Not the git kernel. Run it from a checkout:

```bash
# guardrails in an isolated directory, hook registrations merged additively
scripts/install/install --profile core
```

Its only command, `/harness-doctor`, runs the installed preflight. `scripts/install/uninstall` takes it back out.

**Next:** [one cycle, step by step](#pipeline-in-action) • [the installation guide](docs/installation.md) for the settings overlay, optional modules, dependencies and troubleshooting • [what is proven](docs/status.md)

## The full pipeline

You give it a requirement. It finds the root cause. It asks you only the decisions that are yours. Then it builds the change and checks it.

BA, the business analyst, finds the root cause. QA, the checker, passes or fails the analysis and the build. Dev, the developer, makes the change.

```mermaid
flowchart TD
    subgraph LANE["/dev · one lane per outcome, lanes in parallel"]
        BA["BA<br/>root cause, with evidence"] --> QA1["QA<br/>checks the analysis"]
        QA1 -->|fail| BA
        QA1 -->|pass| DEV["dev<br/>smallest change"]
        DEV --> QA2["QA<br/>verifies the build"]
        QA2 -->|fail| DEV
    end
    subgraph LAND["you land it, one command each"]
        direction LR
        CLOSE["/close<br/>release readiness"] --> COMMIT["/commit<br/>QA first, then commits the task's files"] --> PUSH["/push<br/>checked, then published"]
    end
    REQ(["your requirement"]) --> SPEC["/spec · optional<br/>a durable spec"]
    REQ --> ASK["ask first<br/>BAs find the options, you decide"]
    SPEC --> ASK
    ASK --> LANE
    NIGHT(["/dev-overnight 6:00"]) -.->|"nobody is asked<br/>one pipeline per real issue"| LANE
    LANE -->|"every lane's QA passes"| LAND
    LAND ~~~ PAD["<br/><br/><br/><br/><br/>"]
    classDef pad fill:none,stroke:none
    class PAD pad
```

| You type | You get |
|---|---|
| `/spec` | Optional. It asks you first. Then a durable spec with per-agent briefs. `/dev` and `/dev-overnight` build from it. |
| `/dev <requirement>` | It asks you first. BA finds the root cause. QA checks the analysis before any code. Dev builds in one-issue lanes, in parallel. QA verifies until it passes. |
| `/close` | Release readiness. Inspectors and QA judge the diff. `CLOSE: YES` or the findings. After `CLOSE: YES` it asks for your rating. |
| `/commit` | QA reviews the commit first. The changelog analyst stages the task's own files and commits them. |
| `/merge` | Optional, for work on a branch. A real merge into the default branch, after a pre-merge analysis. |
| `/push` | The push analyst checks what would go out. The wrapper publishes it. It needs a commit made by `/commit`. |
| `/dev-overnight 6:00` | Unattended until the end time. Nobody is asked. It commits nothing. You land it in the morning. |

`/redev` starts a fresh `/dev` cycle in the same conversation. `/dev-command` is `/dev` for a command, an agent or another harness file. `/do` lets the main agent do one task itself, for one turn.

Each stage hands a checked artifact to the next. You start each stage with one command. Agents do the work inside it. Only `/dev-overnight` needs no command from you until its end time.

<details>
<summary><strong>How a cycle runs.</strong> Parallel lanes, when a loop ends, a second opinion, when it asks.</summary>

- **One cycle, parallel lanes.** `/dev` splits your requirement into outcomes that each verify alone. One lane per outcome. BA, QA, dev and QA run once per lane, in parallel. A failing lane retries alone. The cycle passes only when every lane's QA passes.
- **A loop ends on a pass, or when you stop it.** No round cap. Your `/stop` or Esc interrupts either loop at any time. So a stubborn failure loops until you stop it.
- **Adversarial second opinion, one loop.** Add `--codex` to `/dev` and its variants, `/spec`, `/clean`, `/close` or `/commit`. An agent asks Codex once for a complete review. After that, only a capped number of fix checks. Claude classifies each finding as a real bug, a minor point, out of scope or a nitpick.
- **Asked first, then only when it matters.** Without a spec, a panel of independent BAs analyses the requirement from separate angles. Panel QA checks the evidence each one cites. Only a verified root cause becomes an option. With a spec, one BA asks what the spec left open. No other agent is dispatched until the round is asked. Later, an agent that needs a decision writes one question with options and a default. Nothing is asked in plain text.

</details>

## Pipeline in action

<a id="walkthrough-dev-the-login-button-is-misaligned-on-mobile"></a>One `/dev` run, from the words you type to a pushed commit. Reading it is quicker than running it.

1. **You type it.** `/dev the login button is misaligned on mobile`. A hook writes your words to `docs/dev/` before any agent runs. The cycle is armed.
2. **The orchestrator plans.** One outcome, one lane. Each specialist is marked RELEVANT or SKIP, with a reason. A layout bug makes `ui-specialist` relevant. Its findings go to BA.
3. **The BAs ask first.** No spec, so a panel of BAs analyses from separate angles. Root cause, smallest change, your intent. Panel QA drops a cause it cannot verify. Their disagreements become one round of questions. What you should see on a phone. How far the fix goes. Which screens count as done. You answer or skip.
4. **BA analyses.** The file and the cause that actually produce the misalignment, not a plausible cousin. Cited file and line, search results, git history. Then the ticket, the context and the acceptance criteria.
5. **QA checks the analysis.** Before any code. Real evidence? The scope you asked for? Anything narrowed, renamed or deferred? A failing analysis goes back to BA until QA passes.
6. **Dev builds.** The smallest change that meets the acceptance criteria. A report of what it changed and ran. One dev per lane, in parallel.
7. **QA verifies.** It drives the running product against the criteria, on desktop and mobile. A warning or a failure sends dev back, until QA passes or you stop it.
8. **The Stop gate holds.** `/dev` cannot end while a todo is open or an artifact fails its check. `/stop` ends it at any time.
9. **You land it.** `/close` has inspectors and QA judge the diff. It asks for your rating and shows each agent's score, rank and trend. `/commit` commits the task's files under a single-use grant. `/push` publishes through the wrapper. Pushed.

<details>
<summary><a id="usage-examples"></a><strong>More to copy.</strong> Lanes, a second opinion, landing, overnight, stop.</summary>

```text
# Orchestrated development. A vague requirement is fine.
/dev add a --dry-run flag to the export command

# Several outcomes in one cycle: parallel lanes, never phases
/dev fix the pagination off-by-one and add a CSV export to the report page

# With a Codex review of each agent's draft
/dev --codex fix the off-by-one in pagination

# Land the work
/close
/commit
/push

# Unattended until 6am, focused on one subsystem. Land it in the morning.
/dev-overnight 6:00 fix flaky tests in the parser

# End an overnight run early
/stop
```

</details>

## System architecture

Not a prompt pack. An operating system for agents. The orchestrator schedules one-issue agents. Grants and role write paths are the permission model. `docs/dev/` is the filesystem layout. A git protection kernel guards history.

```mermaid
graph TD
    U([You]) -->|type a command| CMD[Slash commands]
    U -->|"/commit · /push · /merge · /allow"| G["Grants<br/>started only by a command you type"]
    CMD --> ORC{{"Orchestrator: your main session<br/>routes work, writes little itself"}}
    ORC ==>|"dispatch WHAT, not HOW<br/>one issue per agent"| SUB["Agents<br/>BA → QA → dev → QA<br/>in parallel lanes"]
    ORC -->|"/dev-overnight"| OVN["Overnight loop, until the end time<br/>PM plan · specialists · triage · retro"]
    OVN -->|"one pipeline per real issue"| SUB
    SUB -->|"each stage writes its own"| ART[("Artifacts in docs/dev/<br/>your words · ticket · context · reports")]
    ART -->|"the next stage reads it"| SUB
    CMD -.->|"prompt hook: your words to disk"| ART

    subgraph PRE["PreToolUse hooks"]
        GATES["orchestrator gate · write gate · dispatch gate<br/>branch and PR firewall"]
        KER["git protection kernel<br/>bash safety · git privilege guard"]
    end
    ORC -.->|every tool call| PRE
    SUB -.->|every tool call| PRE
    G -->|"/commit · /allow: checked by"| PRE
    G -->|"/push · /merge: checked before their wrapper runs git"| TOOL
    PRE -->|allow| TOOL[("Tool runs<br/>files · shell · git")]
    PRE -->|"refuse: the rule, the reason, a remedy"| BLK[/Refused/]
    TOOL --> POST["PostToolUse hooks<br/>/allow grants spent · checkpoints · doc sync · lane aggregate"]
    POST -->|"snapshots, HEAD never moves"| CK[("refs/checkpoints")]
    CK ~~~ PAD["<br/><br/><br/>"]

    SUB -.->|on stop| SS["SubagentStop producer gate<br/>artifact contract · end-to-end status · Codex record"]
    ORC -.->|on stop| SG["Stop gate, on a gated command<br/>todos done · artifacts checked · overnight time-lock"]

    classDef restricted fill:#ffebee,stroke:#c62828
    classDef gate fill:#fff3e0,stroke:#e67e22
    classDef pad fill:none,stroke:none
    class BLK restricted
    class GATES,KER,SS,SG gate
    class PAD pad
```

In words. You type a command. The orchestrator splits the work into lanes and dispatches one-issue agents. Every tool call, the orchestrator's and each agent's, meets the PreToolUse gates first. Allowed, the tool runs. Refused, the caller gets the rule, the reason and a remedy. Each stage writes its artifact under `docs/dev/`, and the next stage reads it. When an agent stops, the producer gate checks what it owes. The Stop gate holds a gated command until its todos are done and its artifacts check out. It holds the overnight run until its end time. [How it works](docs/how-it-works.md) has the long form.

<details>
<summary><strong>Each part, one line.</strong> What it does and where to read on.</summary>

| Part | What it does |
|---|---|
| You | The trust root. You type each owner-only command. Only a command you type starts a grant. Read on: [Who may do what](#trust-model-in-practice). |
| Slash commands | Start each stage. An agent cannot start an owner-only one. Read on: [The command surface](#the-command-surface). |
| Orchestrator | Your main session. It splits the work into lanes, dispatches agents and keeps the todo list. A hook caps what it does itself. Read on: [Context guardrails](docs/how-it-works.md#context-engineering-guardrails). |
| Agents | One issue each, in a clean context. Each writes only to its role's paths and returns a structured report. Read on: [The cast of agents](#the-cast-of-agents). |
| Artifacts | Files under `docs/dev/`. Your words, the ticket, the context, the acceptance criteria, each report. Each stage reads the last one's checked output. Read on: [The full pipeline](#the-full-pipeline). |
| Hooks | Code at every prompt, every tool call and every stop. A prompt hook writes your words to disk before any agent runs. PreToolUse refuses before a call runs. PostToolUse spends `/allow` grants, takes checkpoints and syncs docs. SubagentStop checks what an agent owes. The Stop gate holds a gated command while a todo is open or an artifact fails its check. It holds the overnight run until its end time and its closeout are on disk. Read on: [Failure modes](docs/how-it-works.md#failure-modes-this-exists-to-prevent) and the [enforcement ledger](docs/ENFORCEMENT-LEDGER.md). |
| Git protection kernel | Refuses an agent's commit, push, merge and hard reset. Only something you typed lets one through. Checkpoints snapshot the tree to `refs/checkpoints/`, one ref per branch. Read on: [The git protection kernel](#the-git-protection-kernel). |
| Grants | Each expires. A commit, push or `/allow` grant works once. `/commit` and `/allow` grants are checked before the tool runs. `/push` and `/merge` grants are checked before their wrapper runs git. Who may use which is in the trust model. Read on: [Who may do what](#trust-model-in-practice). |
| Overnight loop | The same pipeline, unattended until a clock time. Nobody is asked. It commits nothing. Read on: [The overnight pipeline](#the-overnight-pipeline). |
| Deny list | `settings.json` denies destructive shell forms and reads of secret files. No grant and no `/do` lifts it. Read on: [Every capability](#feature-highlights). |

</details>

## Why a harness

<a id="why-this-exists"></a>Long chats lose context. Agents run destructive shell and git commands. They drift from what you asked. "Please don't force-push" is a wish. A hook that exits `2` refuses the call before it runs.

| Without it | With the harness |
|---|---|
| One context does too much. Quality silently degrades. | The main session routes. A one-issue agent with a clean context does each piece of work. |
| Agents build what they guessed you meant. | It asks you first, in the question dialog. A hook writes your answers to disk. |
| The build drifts from the requirement. | Your words are on disk before any agent runs. BA cites evidence. QA checks the analysis before any code. |
| Unfinished work is handed off as done. | The Stop gate holds a gated command until every todo is done and the artifact chain passes. |
| An irreversible git operation. | Agent commit, push, merge and `reset --hard` are refused by default. Stash-as-buffer and wide-path checkout are refused by shape. |

<a id="failure-modes"></a><a id="failure-modes-this-exists-to-prevent"></a><a id="design-philosophy"></a><a id="context-engineering-guardrails"></a>Every failure mode and its rule, the guardrails that keep the main session small, and the taste behind the rules: [How it works](docs/how-it-works.md#failure-modes-this-exists-to-prevent). Every registered hook has a row in the [enforcement ledger](docs/ENFORCEMENT-LEDGER.md) that names its file.

<details>
<summary><a id="feature-highlights"></a><strong>Every capability.</strong> One line each.</summary>

| Capability | What it does |
|---|---|
| **Orchestrator-only main session** | The main session routes. A fresh one-issue agent does each piece of work in a clean context. Quality does not decay as the chat grows. A hook caps what the main session does itself. Enforced, not asked nicely. |
| **Git protection kernel** | On in every session, interactive or overnight, for the main agent and every subagent. An agent's `commit`, `push`, `merge` and `reset --hard` are refused. Only something you typed lets one through. |
| **Autonomous overnight pipeline** | `/dev-overnight 6:00` explores, triages, fixes and verifies until a clock time. Nobody is asked. It commits nothing. You land the work in the morning. |
| **QA before code** | BA cites evidence for the root cause. QA checks the analysis before any code exists. Fixing an analysis is cheaper than build loops on the wrong layer. QA checks the build after. A loop ends only on a QA pass, or when you stop it. |
| **Verbatim contract** | A hook writes your words to disk before any agent runs. BA, QA, dev and the specialists get the file. Paraphrase is drift. |
| **Durable specs** | `/spec` asks you first and writes a durable spec. It splits it into per-agent briefs with checklist-style checkpoints. `/dev` and `/dev-overnight` build from it. |
| **Release-readiness gate** | `/close` checks that the system can ship it, not only that the code works. Inspectors and QA judge the diff. Plus workflow-integrity checks. It ends on `CLOSE: YES` or the findings. |
| **Adversarial second opinion** | `--codex` sends each agent's draft to OpenAI Codex through an isolation wrapper you supply (`CODEX_ISO_BIN`). No wrapper, no call. Never a bare `codex`. It hunts real defects and missed edge cases before QA inherits them. Claude classifies every finding. Codex never sets the verdict. |
| **Branch, PR and worktree firewall** | Agents create no branch, pull request or worktree. The exceptions: a live `/dev-overnight`, `/do` for the main agent, an `/allow` grant for that command. |
| **Short-lived grants** | Only a command you type starts one: `/commit`, `/push`, `/merge` or `/allow`. Each expires. A commit, push or `/allow` grant works once. A `/commit --bulk` run covers its whole batch. A commit grant names the repository, branch and HEAD. `/allow` matches the command's structure, never a substring. |
| **Crash-proof checkpoints** | Snapshots go to `refs/checkpoints/`, one ref per branch, through git plumbing. HEAD never moves. `git blame` points at real commits. |
| **Self-updating docs** | A session edits a command, agent or hook. A hook regenerates the marked sections of the folder's `INDEX.md` and `README.md` and of `CLAUDE.md`. Your prose outside the markers stays. CI fails when a folder's generated sections drift. |
| **Generated acceptance tests** | For standard or risky tasks, `test-writer` writes failing skeletons from the acceptance criteria. A `TEST_INCOMPLETE` stop left in a test is a critical QA finding. |
| **Shell and secrets deny list** | `settings.json` denies `sudo`, `rm -rf`, `dd`, `mkfs`, force-push, `git reset --hard`, `systemctl restart`, `kubectl delete` and package publish. It denies `Read` on `.env` files, keys, credentials and secret files. `Edit` and a shell redirect are refused on all of them but keys. A shell read is not refused. |
| **UI-audit skills** | Playwright review: axe-core injection, APCA contrast, an anti-pattern catalog, a state matrix, token conformance, a weighted beauty score. |
| **Ask-first round** | `/spec`, `/dev`, `/redev` and `/dev-command` ask you first. Intent, scope, edge cases, acceptance. In Claude Code's question dialog. A skipped question settles to its stated default. |
| **Hard Stop gate** | `/dev`, `/close`, `/commit` and the other gated commands cannot end until code confirms their todo list and artifacts. `/stop` is your exit. An environment switch turns it off. The shipped settings never set it. |
| **Parallel lanes, no phases** | Several outcomes run as parallel lanes in one cycle. QA fails a plan that phases or defers one. |
| **Declared obligations** | Each dispatch declares the artifacts its agent owes. A hook checks them when the agent stops, while its context still exists. |
| **Usage-limit resume** | `/restart` resumes each interrupted agent by its original id. Never a replacement. |
| **Fact-based scores** | A hook scores each agent from what its dispatch did. No agent reports its own score. Your `/close` rating counts too. The two lowest ranks add a QA round or a Codex debate. |
| **Generated claims** | The repository computes every figure about itself. CI fails when one drifts or is typed by hand. |

</details>

## The git protection kernel

Every agent commit, push, merge and hard reset is refused. Something you typed lets one through. It covers the main agent and every subagent, interactive or overnight. Only `/harness off` switches it off. Built from the two incidents above. Scars, not hypotheticals. The code names both, with dates. Interactive matters. The ninety-three-file push happened in one.

- **Grants.** `/commit` or `/allow` for a commit. `/push` or `/allow` for a push. `/allow` or `/do` for the rest. `/do` is the main agent's, for one turn, and only where the protected branch cannot move. It never covers a commit or a push. A command that starts with `git reset --hard` also meets the `settings.json` deny, which nothing lifts.
- **Stays free.** Read-only git, `add`, a checkout or `restore` of a single file, `stash list`, `show` and `pop`.
- **Limits.** `/push` and `/merge` run git inside their own wrappers. No hook sees inside.

<details>
<summary><a id="trust-model-in-practice"></a><strong>Who may do what.</strong> You, the main agent, a subagent.</summary>

You are the trust root. The threat model treats the agent itself as the adversary. The table shows who may do what, and which grant lets an operation through.

| Actor | Edit, Write | git commit | git push | git reset --hard | Break-glass |
|---|---|---|---|---|---|
| You, in your own shell | yes | yes | yes | yes | not needed |
| Main agent | Once per tool per turn. Its own session scratch is uncounted. Free under `/do`. | Not itself. Only the changelog analyst that `/commit` dispatches spends the `/commit` grant. Or a matching `/allow`. | Through `/push`, or a matching `/allow` | Under `/do` when it cannot move the protected branch. Or a matching `/allow`. Never a command that starts with `git reset --hard`. | `/do` for one turn. Never for commit, push or protected files. `/allow` for one operation. |
| Subagent | Its role's write paths | Only the changelog analyst that `/commit` dispatched, under that grant. Or a matching `/allow`. | A matching `/allow` only | A matching `/allow` only. Never a command that starts with `git reset --hard`. | `/allow` only. Subagents never get `/do`. |

The commit grant works once and expires. The guard spends it as it authorizes the commit. An `/allow` grant matches the command's structure, or an anchored pattern on one sub-command. Never a substring of the raw text. It expires. It is consumed once the matched call ends, whatever the result.

</details>

<details>
<summary><a id="walkthrough-a-hook-firing"></a><strong>A hook firing.</strong> An agent forges the push wrapper's variable.</summary>

An agent tries the obvious shortcut. It sets the push wrapper's own variable on the command line:

```bash
CLAUDE_PUSH_COMMAND_ACTIVE=1 git push
```

The git privilege guard runs before the tool executes. It finds the wrapper's variable in the raw command text. It refuses with exit code `2` and prints `BLOCKED: agent git push - inline-env injection blocked`. This check runs before the guard reads any grant. `/do` does not cover pushes. Nothing the agent can arrange lets this form through.

| What the agent runs | Result |
|---|---|
| The forged command above | Refused, exit `2`. Inline environment injection. Decided before any grant is read. |
| `git push` | Refused, exit `2`. Agents may not push. The message points to `/push`. |
| `/push`, typed by you | The push analyst checks what would go out and writes a grant. The push script spends it once, then hands over to the wrapper. The wrapper exits `3` unless a `/commit` token names an ancestor of HEAD. It refuses force, delete and mirror pushes. |

The whole philosophy in miniature. Steered toward the right path. Stopped on the wrong one. The refusal names the right path. The install's demo replays the plain `git push` case in a sandbox. Refused. A single-use `/allow` grant lets it through once, and the real consumer spends the grant. Refused again. The [status page](docs/status.md) holds the recording.

</details>

[The kernel guide](docs/git-protection-kernel.md) has every guard in one picture, the grant lifecycle and what each guard does not see.

## The overnight pipeline

The unattended stage of [the full pipeline](#the-full-pipeline). Hand it a vague bug report at midnight. PM, the planning agent, explores the running app. Specialists scan it. PM triages what they find. One BA → QA → dev → QA pipeline runs per real issue, in parallel, until the end time. Nobody is asked. An experiment decides, else the question's default, and the summary lists each decision. Nothing is committed. The work waits in your working tree. Checkpoints snapshot it to `refs/checkpoints/<branch>`. [The git kernel](#the-git-protection-kernel) stays on all night.

- **Morning.** You type `/close --auto`, `/commit --auto` and `/push`. A `--worktree` run adds `/merge` before `/push`.
- **Rule.** The Stop gate refuses to end the session before the end time. A typed `/stop` ends the run at once.
- **Limits.** It runs in your checkout by default, with no worktree boundary. A `--worktree` run shares the repository's git directory.

[The overnight guide](docs/overnight-pipeline.md) has the loop in one picture, the default end time, the closeout and what each mode does and does not protect.

## The cast of agents

The orchestrator dispatches each agent by describing the problem. It never names the tooling. A hook warns when a dispatch names a tool. Before `/dev` dispatches BA, it marks each specialist RELEVANT or SKIP with a reason. A silent skip is invalid. Each agent works one issue in a clean context and returns a structured report.

<details>
<summary><strong>All agents.</strong> One line each, generated from each agent's own file.</summary>

<!-- BEGIN canonical-region id=agents — generated by scripts/generate-hero-status.py; do not hand-edit -->
| Agent | What it does |
|---|---|
| `architect` | Reviews architecture: structural issues, technical debt, dependency problems and inconsistent patterns. |
| `ba` | Writes the requirement round's questions, finds the root cause with cited evidence, alone or on a panel, and writes the ticket, context and acceptance criteria. |
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
| `qa` | Checks a BA panel's evidence and writes your first questions; verifies the analysis before any code and the implementation after it; when in doubt it fails. |
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

</details>

## The command surface

These are the commands you type. An owner-only command carries `disable-model-invocation: true` and a `Skill(...)` deny in `settings.json`. An agent cannot start one itself.

**Limits.** `disable-model-invocation` alone stops only the slash form. The `Skill(...)` deny is the real barrier. A coverage test fails when a command lacks one. `/codex` and `/tickets` are open to agents too.

<details>
<summary><strong>All commands.</strong> Who may type each, generated from each command's own file.</summary>

<!-- BEGIN canonical-region id=commands — generated by scripts/generate-hero-status.py; do not hand-edit -->
| Command | What it does |
|---|---|
| `/spec [--codex] [<requirement>]`<br>owner only, Spec | Ask you about the requirement first, then write a durable spec and split it into per-agent briefs with checkpoints, for /dev or /dev-overnight to build from. |
| `/spec-update [--update --spec <path> \| --continue \| --temp] [--spec <path>] [what the next session should focus on]`<br>owner only, Spec | Turn unfinished work into a continuation spec for a fresh session, enrich an existing spec, or write a short session note. |
| `/dev [--codex] [--spec <path>] <requirement>`<br>owner only, Develop | Build a requirement end to end: ask you first, then BA finds the root cause, QA checks it, dev builds in parallel one-issue lanes, QA verifies until it passes. |
| `/dev-command`<br>owner only, Develop | The /dev workflow for building a slash command, a subagent or another harness file, with the differences such a file needs. |
| `/dev-overnight`<br>owner only, Develop | Run unattended until an end time: explore, fix each real issue in its own pipeline, decide without the owner, and commit nothing. |
| `/redev [--codex] [--spec <path>] [<requirement>]`<br>owner only, Develop | Start a fresh /dev cycle in the same conversation without repeating the text of /dev, to save context. |
| `/checkpoint`<br>owner only, Ship | Snapshot the working tree to the safety ref `refs/checkpoints/`, one per branch, without moving HEAD, touching the index or pushing. |
| `/close [--codex \| --auto \| --late-repair] [<task-id>\|<path>]`<br>owner only, Ship | Close the cycle: finish what is unfinished, have inspectors and QA judge it, end on `CLOSE: YES` or the findings, then ask you to rate it. |
| `/commit`<br>owner only, Ship | Commit a task's changes through the changelog analyst, closing an unfinished cycle first and staging only the task's own files. |
| `/merge`<br>owner only, Ship | Merge a branch or commit into the default branch with a real merge that keeps the full history, after a pre-merge analysis. |
| `/pull`<br>owner only, Ship | Pull with rebase, stashing and restoring local changes and stopping on conflicts, then summarize the risk of what arrived. |
| `/push`<br>owner only, Ship | Publish the current branch through the push wrapper after the push analyst reviews what would go out; it needs a commit made by /commit. |
| `/clean [--codex]`<br>owner only, Quality | Clean up the project: inspectors find misplaced docs, byproducts and style violations, and the cleaner applies the approved fixes. |
| `/test`<br>owner only, Quality | Check the project's tests against edge cases found in its git history, then run them and report. |
| `/allow`<br>owner only, Control | Grant one single-use permission for an operation a grant-aware safety hook refused; it never overrides a settings deny rule. |
| `/codex [prompt or --review or --model <model> <prompt>]`<br>owner or agent, Control | Ask OpenAI Codex for a second opinion, a code review or a delegated coding task, through an isolated wrapper. |
| `/do`<br>owner only, Control | Let the main agent do one task itself for this turn, past the orchestrator gate; it does not cover commits or pushes. |
| `/harness off \| on \| status`<br>owner only, Control | Switch the whole harness off or back on for this harness home, or show its state; on restores exactly what off removed. |
| `/rating`<br>owner only, Control | Show every agent's score, rank, trend and latest scored events for this project, then your latest ratings; it writes nothing. |
| `/restart`<br>owner only, Control | Resume every subagent a usage limit interrupted, by its original agent id; with none to resume, continue the main agent. |
| `/stop`<br>owner only, Control | End the overnight run before its end time, or any command the Stop gate holds; only the owner can type it. |
| `/tickets [--format table\|json]`<br>owner or agent, Control | Print a read-only table of every ticket, spec and lane, with its state and next action. |

22 commands, generated from the frontmatter of `commands/*.md`. An optional module's own commands are described with the module in the [installation guide](docs/installation.md).
<!-- END canonical-region id=commands -->

</details>

Did you hit a usage limit? `/restart` resumes every recoverable interrupted child in the current parent transcript by its original agent id. It never creates a replacement agent. It claims recovery only on response evidence from every candidate.

<details>
<summary><strong>Switches.</strong> What you can turn off, and how.</summary>

- **`/harness off | on | status`**: the whole harness, for this harness home. `on` restores exactly what `off` removed.
- **`CLAUDE_COMMAND_GATE=off`**: switches the Stop gate off. The shipped settings never set it.
- **`.claude/.hook-refactor-allow`**: a file you create in a project. Until it exists, a hook refuses agent writes to that project's `.claude/hooks/` and `.claude/commands/`.
- **`CODEX_ISO_BIN`**: your Codex isolation wrapper. No wrapper, no call. Never a bare `codex`.

</details>

## Proof and limits

The [status page](docs/status.md) says what is proven and what is not. The measured proof, the demo recording, the claim rows and the known limits. The repository generates every figure on it. CI checks each one again.

The [enforcement ledger](docs/ENFORCEMENT-LEDGER.md) has one row per registered hook. It says what each hook does and how far that is proven. A script that exits `2` is evidence about the script, not about a Claude Code host honouring it.

What still needs you. Your answers to the requirement round at the start of a cycle. The decisions only you can make. Your rating of the work. `/close` asks for the rating after a cycle lands. You may skip it. `/dev-overnight` asks nobody. It decides by experiment, else by the question's default, and lists each decision in its summary.

## FAQ

<details>
<summary><strong>Is this a framework I import?</strong></summary>

No. A configuration for Claude Code. Its hooks, commands and agents change how every session behaves. No package. No API. Other agent clients need substantial changes.

</details>

<details>
<summary><strong>Does the orchestrator-only rule make small edits slow?</strong></summary>

Not for a one-line fix. Type `/do <task>`. The main agent does it itself for one turn. Commits and pushes still go through `/close`, `/commit` and `/push`.

</details>

<details>
<summary><strong>Can an agent switch off its own guardrails?</strong></summary>

That is the threat model the kernel is built against. The design makes it hard, not impossible:

- An agent cannot start an owner-only command.
- The git guard refuses every agent by default.
- Each grant expires. A commit, push or `/allow` grant works once.
- A hook refuses agent writes to a project's `.claude/hooks/` and `.claude/commands/`. The owner allows them with a sentinel file.

The [status page](docs/status.md) lists what is not covered.

</details>

<details>
<summary><strong>Is everything in this README real?</strong></summary>

Every hook here has a row in the [ledger](docs/ENFORCEMENT-LEDGER.md): its file, what it does and how far that is proven.

</details>

<details>
<summary><strong>Can I use it with a team or in CI?</strong></summary>

Built for one developer per `~/.claude`. Grants live in one machine's state directory. Hooks fire only when Claude Code runs. The test suite runs without Claude Code (`scripts/test`). CI runs it on every pull request.

</details>

The longer [FAQ](docs/faq.md) covers parallel sessions and where to go deeper.

## Documentation

- [Status](docs/status.md): the measured proof, the demo recording, the claim rows and the known limits.
- [Installation](docs/installation.md): clone and init, the settings overlay, optional modules, the guardrails-only profile, dependencies and troubleshooting.
- [How it works](docs/how-it-works.md): the architecture, the agents, the guardrails, the failure modes, the design philosophy and the project structure.
- [The git protection kernel](docs/git-protection-kernel.md): what git operations are refused, how grants work, who may do what, and what each guard does not see.
- [The overnight pipeline](docs/overnight-pipeline.md): `/dev-overnight` until a clock time.
- <a id="extending-it"></a>[Extending the harness](docs/extending.md): plain Markdown and scripts. A command, an agent or a hook, what each must carry and what checks it. And the longer [FAQ](docs/faq.md).
- [The enforcement ledger](docs/ENFORCEMENT-LEDGER.md), the [threat model](docs/THREAT-MODEL.md) and the [adversarial corpus](docs/ADVERSARIAL-CORPUS.md).
- [`CLAUDE.md`](CLAUDE.md), [`ARCHITECTURE.md`](ARCHITECTURE.md) and the [changelog](CHANGELOG.md).

## Acknowledgements

This configuration grew out of these sources, and remains grateful to them:

- [Claude Code](https://claude.com/claude-code) and the official [documentation](https://docs.claude.com/en/docs/claude-code).
- [fcakyon/claude-codex-settings](https://github.com/fcakyon/claude-codex-settings), an early real-world configuration reference.
- The broader Claude Code community. Its shared patterns and hard-won lessons shaped the hooks and agents here.

## License

Released under the **MIT License**. Use, copy, modify and adapt it for your own `~/.claude`. See [LICENSE](LICENSE).
