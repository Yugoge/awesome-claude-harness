# Bash refusal sweep: awesome-claude-harness

Investigation only (2026-11-17). No repository was modified. All hooks ran from throwaway copies of the target
trees; no corpus command was executed.

## Bottom line

- **Corpus: 388 everyday agent Bash commands** (341 core + 47 supplementary statistics/log/code-comparison commands).
- **origin/master a21dcbf9 (what the owner runs):**
  - main agent **354 / 388 pass** (34 refused);
  - `dev` subagent **351 / 388 pass** (37 refused);
  - on a 61-command write-bearing subset: `qa` subagent **40 / 61 pass**, built-in `general-purpose` subagent **52 / 61 pass**;
  - **342 / 388 commands pass in every context; 46 are refused in at least one.** 105 refusal rows in total (command x context x hook).
- **Every refusal hit a harmless command.** The corpus contains no dangerous command on purpose, so no refusal here is a
  justified stop of real damage. 31 commands are parser false positives (RC1); the rest are refusals by explicit
  policy (RC2-RC4) that hit harmless work.
- **origin/claude/p14-5-bash-safety 91815716 (next train): identical.** It produces the same 105 refusal rows (same hook,
  rule and reason), adds none and fixes none. The removal analyzer returns the same verdict on both targets for all 388
  commands.
- No hook errored in any of the 1,796 sweep payloads.

## Root-cause groups

| Group | What is refused | Hook (rule) | master refusal rows main / dev / qa / gp | distinct commands | Class | Reproduces on p14 |
|---|---|---|---|---|---|---|
| RC1 | data words (URL `&`, SQL `(*)`) given to programs the analyzer does not model | `pretool-bash-safety.sh` (removal-policy, UNRESOLVED `unproven_boundary_with_removal_reference`) | 31 / 31 / 6* / 6* | 31 | false positive (known, other lane) | yes, all |
| RC2 | `rm` of the agent's own `/tmp` file | `pretool-bash-safety.sh` (removal-policy, FORBIDDEN_REMOVAL `filesystem_removal`) | 3 / 3 / 3 / 3 | 3 | policy, harmless command | yes, all |
| RC3 | role-holding subagent writes into `/tmp` (`>`, `cp`, heredoc) | `pretool-write-gate.py` > `pretool-tool-policy.py` (scratch actor-exactness: system_temp) | 0 / 4 / (RC4) / 0 | 4 | policy, harmless command | yes, all |
| RC4 | `qa` writes a report file into the project or `/tmp` | `pretool-write-gate.py` > `pretool-tool-policy.py` (role write prefixes) | - / - / 15 / - | 15 | policy, harmless command | yes, all |
| D1 | main agent's 6th Bash call since the last prompt or dispatch | `pretool-orchestrator-gate.py` (Bash cap) | demonstrated separately | any | by design | yes (same code) |
| D2 | main agent's Bash with `run_in_background: true` | `pretool-block-background-tasks.py` | demonstrated separately | any | by design | yes (same code) |
| P1 | `rm -rf <tmp dir>` | `settings.json` `permissions.deny` | CLI-level | 1 | policy | yes (identical settings) |
| L1 | latent: analyzer gives no verdict, so the fallback refuses about half the corpus | `pretool-bash-safety.sh` (removal-policy FAIL-CLOSED) | not triggered (0) | 194 when forced | latent over-block | yes (same predicate) |

\* qa and gp ran the 61-command subset only, which contains 6 of the 31 RC1 commands.

### RC1: data words given to programs the analyzer does not model read as shell (known root cause; listed, not dug into)

- **Example:** `psql -X -U app -d app -c 'SELECT count(*) FROM jobs'` (main and every subagent) is refused with
  `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs`.
- **Responsible code (master):**
  - `hooks/lib/bash_execution_boundary.py:2502-2506` emits the structural UNRESOLVED when a residual argv word of a program
    it does not model satisfies `word_is_removal_reference` (`:2288`);
  - the refusal is printed by `hooks/pretool-bash-safety.sh:1860-1865`.
- **Responsible code (p14):** `hooks/lib/bash_execution_boundary.py:1730-1734` (predicate `:1533`); printed by
  `hooks/lib/bash_safety_rules.py:964`.
- **Two triggers explain all 31 commands:**
  - **1a. `&` inside a word (14 commands).** Query-string URLs given to `curl`, `wget`, `gh api` and `http` (httpie),
    including:
    - URLs written into a project file (`-o reports/fetch.json`) or into `/tmp`;
    - inside a `for` loop: `curl -s "http://localhost:3000/api/items?page=$i&limit=5"`;
    - inside process substitution: `diff <(curl -s '…?a=1&b=2') <(curl -s '…?a=1&b=2')`.
  - **1b. `(*)` in SQL text (17 commands).** SQL given via `-c` / `-e` / `-q` to `psql`, `sqlite3`, `mysql`,
    `clickhouse-client` and `duckdb`, in every form tried:
    - plain;
    - with `PGOPTIONS='-c default_transaction_read_only=on'`;
    - via `docker exec`, `docker compose exec`;
    - with `-At -F,`;
    - with `count(*) FILTER (…)`, `date_trunc(…), count(*)`;
    - with output redirected to `reports/*.txt`.
- **Controls that pass, on the same programs:**
  - SQL shapes:
    - `SELECT * FROM … WHERE … interval '1 day';` (a `*` without parentheses);
    - `id || ':' || name`;
    - `;`-separated statements, single quotes;
    - `count(1)`, `avg()`, `string_agg(…)`, window `over ()`;
    - `\dt`, `\d+`.
  - SQL delivered another way:
    - SQL in a heredoc (`psql … <<'SQL'`);
    - `-f queries/report.sql`, `< queries/stats.sql`.
  - Other data words:
    - `curl -G -d 'q=level:error' -d 'size=0'`, `--data-urlencode 'query=sum(rate(x[5m]))'`;
    - `'logs-*'`, `redis-cli keys 'job:*'`, `kubectl … jsonpath='{.items[*]…}'`;
    - every URL without `&`.
- **How this maps to the owner's report:**
  - "statistics queries" is RC1b;
  - "basic curl" is RC1a;
  - fetched-data comparisons are RC1a.
- **Fix direction:** treat a quoted argv word of a program the analyzer does not model as inert data, unless that program
  is known to run an argument as shell. Never re-read a quoted argument as shell text.

### RC2: `rm` of the agent's own temporary file

- **Example:** `rm -f /tmp/q.csv` is refused with `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm`.
  `rm /tmp/notes.txt` and `rm -rf /tmp/work` are refused the same way, for main and every subagent role.
- **Responsible code:**
  - master: `hooks/lib/bash_execution_boundary.py:2862-2865` (any `REMOVAL_EXES` head becomes FORBIDDEN_REMOVAL);
    printed at `hooks/pretool-bash-safety.sh:1860-1865`;
  - p14: `bash_execution_boundary.py:2090`, printed at `lib/bash_safety_rules.py:964`.
- **Class:** intentional policy ("every filesystem removal is forbidden for every caller"), but these commands are
  harmless. It also contradicts the shipped allow list: tracked `settings.json:113` `Bash(rm -f /tmp/*.json:*)` and
  `:116` `Bash(rm:*)`.
- **Fix direction:** an owner decision. Allow a non-recursive removal of a literal path under `/tmp`, `$TMPDIR` or the
  session scratch namespace, and keep the ban elsewhere. Or drop the contradicting allow entries so the policy is stated
  once.

### RC3: a role-holding subagent writes into `/tmp`

- **Example:** a `dev` subagent runs `grep -rn TODO src > /tmp/todos.txt` and is refused with
  `BLOCKED by tool-policy.v1: {"role":"dev","tool":"Write","target":"/tmp/todos.txt","deny_reason":"arbitrary /tmp and /var/tmp are denied for every role; use the managed scratch namespace .claude/scratch/<session>/<role>/<dispatch>/"}`.
- **Refused commands:**
  - `curl -s "…" > /tmp/q.json && jq length /tmp/q.json`;
  - `cat > /tmp/notes.txt <<'EOF'`;
  - `grep -rn TODO src > /tmp/todos.txt`;
  - `cp config.example.yml /tmp/config.yml`.
- **Responsible code (same lines on p14):**
  - `hooks/pretool-tool-policy.py:403-431` (`_check_scratch_actor_exactness`, reason text at `:429`);
  - roots at `:292` (`("/tmp", "/var/tmp")`), called at `:1355`;
  - it runs as a rule of `hooks/pretool-write-gate.py`.
- **Scope:** it applies to every subagent whose `agent_type` has a row in `policies/tool-policy.v1.json` (dev, qa, ba,
  ...). It does not apply to the main agent or to built-in `general-purpose` / `Explore` agents (no row, so the hook
  exits 0).
- **Inconsistent enforcement:** the Bash write extractor used here (`extract_bash_write_paths`, imported at `:158`, used
  at `:201`) does not report these targets, so all of them pass:
  - `curl -o /tmp/x`, `wget -O /tmp/x`;
  - `touch /tmp/x`, `mkdir -p /tmp/x`;
  - awk's internal `print > "/tmp/x"`.
  Only `>`, `>>`, `tee`, `cp` and heredoc-to-file are refused.
- **Fix direction:** an owner decision. Let subagents write plain `/tmp` (or at least `$TMPDIR`). Otherwise make the
  refusal name the exact writable path: it needs the agent's own dispatch id, which the agent is not told. Either way,
  use one write extractor.

### RC4: a `qa` subagent writes a report file

- **Example:** the owner's exact command shape, `docker exec -i app-postgres psql -X … -P pager=off > <project>/tests/reports/age.txt <<'SQL' … SQL`.
  - It passes for main and `dev`.
  - For `qa` it is refused with `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"<project>/tests/reports/age.txt","deny_reason":"write target … matches denied_write_path_prefixes"}`
    (the project-anchored `/tests/`).
  - Every other report target is refused with `… not in allowed_write_path_prefixes`. That covers `reports/*.txt`,
    `docs/dev/stats.txt`, the `/tmp` targets, and `.claude/scratch/loc.txt` (refused as "sibling scratch").
  - 15 refusals among the 61 subset commands.
- **What qa can write ad hoc:** only `$TMPDIR/qa/` (`/var/tmp/claude-scratch/qa/…`, probed: passes), its own
  `.claude/scratch/<session>/qa/<dispatch>/`, `docs/codex/`, `docs/dev/overnight/`, and what its dispatch obligation
  declares.
- **Responsible code (same on p14):**
  - `policies/tool-policy.v1.json:149` (qa row);
  - enforced by `hooks/lib/policy_registry.py:271` (denied prefix) and `:274` (not in the allowed prefixes), through
    `hooks/pretool-tool-policy.py`.
- **Fix direction:** an owner decision. Give read-only roles one project report directory for statistics output (e.g.
  `tests/reports/`, `reports/`). Or make the refusal name the writable path.

### D1: the Orchestrator Gate's Bash cap (by design; it hits ordinary search)

- **How the cap behaves:** the main agent's Bash calls are counted per `session_id` in
  `$CLAUDE_STATE_DIR/claude-tool-streak-<sid>.json`.
  - The 6th call is refused until an `Agent` dispatch or the next prompt resets the count.
  - Read, Grep and other tools in between do not reset it.
  - A refused call still increments the count, as does a call that another hook refuses.
  - Subagents and `/do` are exempt.
- **Demonstrated:** a session ran `ls` ×3, then Read, then `ls` ×4. Calls 1-6 passed (5 Bash calls plus the Read); the
  next two `ls` calls (Bash #6 and #7) were refused with
  `[Orchestrator Gate] BLOCKED: Bash used consecutively beyond limit (6/5) …`, then `(7/5)`.
- **Responsible code:** `hooks/pretool-orchestrator-gate.py:86` (`BASH_MAX_CONSECUTIVE = 5`) and `:219-224`.
- **In the sweep:** each payload used a fresh `session_id`, so every main-agent call was Bash #1 and the cap could not
  pollute results.
- **Fix direction:** an owner decision. For example, exempt commands the analyzer proves inert and read-only from the
  count. This is the most likely reason "even basic search" stops working mid-turn.

### D2: `run_in_background: true` for the main agent (by design)

- `npm run dev` with `run_in_background: true`:
  - the main agent is refused with `[BLOCK] Bash(run_in_background=true) is forbidden for orchestrator.`
    (`hooks/pretool-block-background-tasks.py:193`);
  - a subagent passes.

### P1: settings.json permissions

- **`permissions.ask`:** empty.
- **`permissions.deny`:** the only corpus hit is `rm -rf /tmp/work`, matched by tracked `settings.json:206`
  `Bash(rm -rf:*)` and `Bash(rm -rf /*:*)`. No deny entry matches any read command.
- **`Bash(curl:* | sh:*)`** (`:189`) and **`Bash(wget:* | sh:*)`** span a pipe. The CLI matches each subcommand of a
  compound command separately, so these entries most likely never match (exact matcher semantics unverified).
- **`permissions.allow` gaps (prompts, not refusals).** Many everyday read commands are absent, so in default permission
  mode they prompt unless the CLI's own read-only list covers them:
  - search and read: `rg`, `fd`, `jq`, `yq`, `stat`, `file`, `du`, `nl`, `column`, `cut`, `xxd`, `od`, `strings`, `zcat`,
    `zgrep`, `readlink`, `sha256sum`;
  - comparison: `diff`, `comm`, `cmp`, `sdiff`, `paste`;
  - git: `git show`, `git blame`, `git fetch`, `git remote`, `git rev-parse`, `git grep`, `git tag`, `git stash list`,
    `git ls-files`, `git config --get`, `git describe`, `git reflog`, `git shortlog`, `git worktree list`,
    `git cat-file`, `git -C`;
  - GitHub and HTTP: `gh api`, `gh pr`, `gh issue`, `gh run`, `http`;
  - databases: `psql`, `sqlite3`, `mysql`, `redis-cli`, `clickhouse-client`, `duckdb`, `mongosh`;
  - containers and logs: `docker compose`, `docker inspect`, `docker stats`, `journalctl`, `kubectl logs`,
    `systemctl status`;
  - builds and tests: `make`, `pytest` (only `pytest tests/generated` is allowed), `tsc`, `ruff`;
  - environment: `env`, `printenv`, `uname`, `whoami`, `id`, `hostname`, `ps`, `ss`, `nproc`, `free`, `df`;
  - wrappers: `time`, `timeout`, `source`, `sh -c`.

### L1: latent fail-closed mode of the removal policy

- **Trigger:** the analyzer runs under `timeout 5s` and `ulimit -v 512 MB`. On a timeout, the memory cap, a crash or bad
  output, bash-safety falls back to a predicate that refuses a command when any of these hold:
  - it contains `$ * ? [ ] { } !`, a backtick or `<<`;
  - it names a removal word (`rm`, `delete`, `remove`, …);
  - it ends on an option (`(^|[[:blank:]])[-+][A-Za-z0-9=_-]*[[:blank:]]*$`) or on an operator.
- **Code:** master `hooks/pretool-bash-safety.sh:1903-1910`; p14 `hooks/lib/bash_safety_rules.py:977-982`.
- **Forced experiment** (`CLAUDE_HOOK_BOUNDARY_TIMEOUT=0.001s`, master, main): **194 / 388 refused.** These include
  `git status --short`, `git log --oneline -5`, `date -u`, `uname -a`, `python3 --version` (all end on a flag), every awk
  program, `grep -rn 'def main' --include='*.py' .` and `wc -l logs/*.log`.
- **Not observed in the sweep:**
  - the analyzer took median 0.17 s and max 0.73 s per command at load average ~20;
  - zero FAIL-CLOSED refusals in 1,796 payloads.
- **Fix direction:** make the fallback refuse only commands that carry a removal reference or an assembly channel, not a
  trailing option. Raise or remove the 5 s wall clock.

### Checked and not a source of refusals

- **`pretool-grep-backtrack-guard.py`:**
  - its static pre-filter sends every grep with two `.*` gaps to a probe (e.g. `grep -rn 'error.*timeout.*retry' logs/`);
  - the probe needs systemd, which this container lacks, so the hook failed open in the sweep;
  - I replicated it by hand: the same embedded engine, its worst-case input, a 5 s wall clock and a 1.5 GB cap;
  - all 12 typical patterns finished in under 0.1 s, so the guard would allow them.
- **No refusals at all** from `pretool-git-privilege-guard.py`, `pretool-block-branch-pr-worktree.py`,
  `pretool-bulk-commit-detector.py`, `pretool-wrapper-userintent.py`, `pretool-workflow-gate.py`,
  `pretool-read-size-guard.py`, `pretool-do-block-subagents.py`, `pretool-attribution-pre.py` or
  `pretool-worktree-guard.sh`. Every git read passed, including `git fetch`, `git -C <dir> log` and `git worktree list`.
- **UserPromptSubmit fidelity:** running the registered UserPromptSubmit hooks for the plain prompt first, as the CLI
  does, gave identical PreToolUse decisions in 20 / 20 cases.
- **Operational cost, not refusals:**
  - one Bash call took 1.4-3 s of hook time, up to 11 s under load (bash-safety dominates);
  - `pretool-attribution-pre.py` runs `git status` in the harness home on every call (`hooks/lib/attribution_journal.py:224`).
    That fires the `claude-settings` clean filter (`render-settings clean`);
  - it also writes about 100 KB per call into `<harness>/state/attribution-journal/pending/` (206 MB after ~1,400
    calls here).

## Method

- **Targets:**
  - `git archive` of a21dcbf9 (origin/master) and 91815716 (origin/claude/p14-5-bash-safety) from the coordinator's
    clone, read-only;
  - each tree became a throwaway `$HOME/.claude` git repository;
  - each was initialized with the harness's own `scripts/bootstrap --yes --steps 2,3,4,5`: overlay with
    `env.CLAUDE_HOME`, rendered `settings.json`, `~/.config/claude/protected-runtime.json` with empty lists, and git
    hooks;
  - no venv (the system `python3` has pytest, jsonschema and yaml) and no doctor.
- **Paths:**
  - every run happened in a private mount namespace (`unshare -m`), with a namespace-only tmpfs on `/srv`;
  - HOME was bound at `/srv/home`; the project at `/srv/app` (a git repo with `main` and `feature` branches, an origin
    URL and sample files).
  - Reason: tool-policy classifies anything under `/tmp` as system temp. A first pass with the project under `/tmp`
    produced 15 artifact refusals of relative project writes, which I discarded.
- **Pipeline:** every PreToolUse registration in the rendered `settings.json` that matches `Bash`:
  - `pretool-launch.py`; its rules that apply to Bash are orchestrator-gate, block-background-tasks, do-block-subagents,
    read-size-guard, workflow-gate, write-gate (with its sub-rules), wrapper-userintent, grep-backtrack-guard,
    attribution-pre, block-branch-pr-worktree, bulk-commit-detector and git-privilege-guard;
  - `pretool-bash-safety.sh`;
  - `pretool-worktree-guard.sh`.
- **Runner:**
  - the target tree's own `tests/replay/hookrun.py`, with CLI matcher, env and timeout semantics;
  - hooks ran in parallel;
  - per-rule results came from the launcher's `CLAUDE_HOOK_LAUNCH_RECORD_FD`;
  - exit 2, a JSON `deny`/`ask`, or `decision: block` counted as a refusal.
- **Environment:**
  - `env -i` plus the rendered `settings.json` env;
  - `HOME`, `PATH`, `CLAUDECODE=1`, `CLAUDE_PROJECT_DIR`;
  - a fresh `CLAUDE_STATE_DIR` per target, isolated from other lanes' `/tmp` state;
  - `GIT_CONFIG_NOSYSTEM=1`.
- **Context:**
  - a plain user prompt (no slash command);
  - a transcript JSONL holding that prompt and the assistant's Bash `tool_use`;
  - no `/do`, no `/dev-overnight`, no `/allow` grants, an empty state dir;
  - a fresh `session_id` per payload.
  - The subagent payload adds an `Agent` dispatch record, `subagents/agent-<id>.meta.json`, and payload `agent_id` and
    `agent_type`:
    - `dev` on the full corpus;
    - `qa` and `general-purpose` on 61 commands: every write-bearing command plus 21 read-only controls.
- **Volume:** 898 payloads per target, plus the experiments (cap, background, qa paths, fidelity, forced-degraded).
- **Corpus:** `/tmp/claude-0/-home-user/fc2a4e86-9f11-582c-8078-b4c463755b6b/scratchpad/sweep/driver/corpus.py`
  (`{P}` = project dir). Categories:

  | Category | Commands |
  |---|---|
  | search | 44 |
  | read | 32 |
  | git | 47 |
  | network | 34 |
  | database | 41 |
  | logs | 18 |
  | diff-stats | 18 |
  | build-test | 27 |
  | env-quickcode | 33 |
  | shell-forms | 47 |
  | extra-stats | 47 |

- **Limitations:**
  - the grep-guard probe could not run natively here (no systemd), so it was replicated by hand;
  - SessionStart hooks were not run;
  - permission-rule matching was approximated (legacy `:*` prefix, per-subcommand), not run through the CLI;
  - other roles (ba, pm, test-*) were not swept; their write prefixes would refuse like RC4.

## Full refusal table (origin/master; p14 column = same hook, rule and reason on p14)

Contexts: `main` = main agent; `sub/dev`, `sub/qa`, `sub/general-purpose` = subagent with that `agent_type`.

| # | RC | ctx | command | hook | rule label | first reason line | class | p14 |
|---|----|-----|---------|------|-----------|-------------------|-------|-----|
| 1 | RC1 | main | `curl -s 'https://example.com/a?x=1&y=2'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://example.com/a?x=1&y=2` | false positive | yes |
| 2 | RC1 | sub/dev | `curl -s 'https://example.com/a?x=1&y=2'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://example.com/a?x=1&y=2` | false positive | yes |
| 3 | RC1 | main | `curl -sS 'https://api.github.com/repos/a/b/pulls?state=open&per_page=5' \| jq length` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://api.github.com/repos/a/b/pulls?state=open&per_page=5` | false positive | yes |
| 4 | RC1 | sub/dev | `curl -sS 'https://api.github.com/repos/a/b/pulls?state=open&per_page=5' \| jq length` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://api.github.com/repos/a/b/pulls?state=open&per_page=5` | false positive | yes |
| 5 | RC1 | main | `curl -sS -o /tmp/q.csv 'https://stooq.com/q/d/l/?s=aapl.us&i=d'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://stooq.com/q/d/l/?s=aapl.us&i=d` | false positive | yes |
| 6 | RC1 | sub/dev | `curl -sS -o /tmp/q.csv 'https://stooq.com/q/d/l/?s=aapl.us&i=d'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://stooq.com/q/d/l/?s=aapl.us&i=d` | false positive | yes |
| 7 | RC1 | sub/general-purpose | `curl -sS -o /tmp/q.csv 'https://stooq.com/q/d/l/?s=aapl.us&i=d'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://stooq.com/q/d/l/?s=aapl.us&i=d` | false positive | yes |
| 8 | RC1 | sub/qa | `curl -sS -o /tmp/q.csv 'https://stooq.com/q/d/l/?s=aapl.us&i=d'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://stooq.com/q/d/l/?s=aapl.us&i=d` | false positive | yes |
| 9 | RC1 | main | `curl -s 'https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcv&h&e=csv'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcv&h&e=csv` | false positive | yes |
| 10 | RC1 | sub/dev | `curl -s 'https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcv&h&e=csv'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcv&h&e=csv` | false positive | yes |
| 11 | RC1 | main | `curl -s 'http://localhost:8080/api/items?limit=10&offset=20' \| jq '.items[].id'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:http://localhost:8080/api/items?limit=10&offset=20` | false positive | yes |
| 12 | RC1 | sub/dev | `curl -s 'http://localhost:8080/api/items?limit=10&offset=20' \| jq '.items[].id'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:http://localhost:8080/api/items?limit=10&offset=20` | false positive | yes |
| 13 | RC1 | main | `curl -s -X GET 'https://api.example.com/search?q=foo%20bar&page=2'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://api.example.com/search?q=foo%20bar&page=2` | false positive | yes |
| 14 | RC1 | sub/dev | `curl -s -X GET 'https://api.example.com/search?q=foo%20bar&page=2'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://api.example.com/search?q=foo%20bar&page=2` | false positive | yes |
| 15 | RC1 | main | `curl -s "https://api.example.com/q?from=2024-01-01&to=2024-02-01" > /tmp/q.json && jq length /tmp/q.json` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://api.example.com/q?from=2024-01-01&to=2024-02-01` | false positive | yes |
| 16 | RC1 | sub/dev | `curl -s "https://api.example.com/q?from=2024-01-01&to=2024-02-01" > /tmp/q.json && jq length /tmp/q.json` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://api.example.com/q?from=2024-01-01&to=2024-02-01` | false positive | yes |
| 17 | RC1 | sub/general-purpose | `curl -s "https://api.example.com/q?from=2024-01-01&to=2024-02-01" > /tmp/q.json && jq length /tmp/q.json` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://api.example.com/q?from=2024-01-01&to=2024-02-01` | false positive | yes |
| 18 | RC1 | sub/qa | `curl -s "https://api.example.com/q?from=2024-01-01&to=2024-02-01" > /tmp/q.json && jq length /tmp/q.json` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://api.example.com/q?from=2024-01-01&to=2024-02-01` | false positive | yes |
| 19 | RC1 | main | `curl -s 'https://example.com/a?x=1&y=2' -o reports/fetch.json` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://example.com/a?x=1&y=2` | false positive | yes |
| 20 | RC1 | sub/dev | `curl -s 'https://example.com/a?x=1&y=2' -o reports/fetch.json` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://example.com/a?x=1&y=2` | false positive | yes |
| 21 | RC1 | sub/general-purpose | `curl -s 'https://example.com/a?x=1&y=2' -o reports/fetch.json` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://example.com/a?x=1&y=2` | false positive | yes |
| 22 | RC1 | sub/qa | `curl -s 'https://example.com/a?x=1&y=2' -o reports/fetch.json` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://example.com/a?x=1&y=2` | false positive | yes |
| 23 | RC1 | main | `wget -qO- 'https://example.com/?a=1&b=2'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:wget:https://example.com/?a=1&b=2` | false positive | yes |
| 24 | RC1 | sub/dev | `wget -qO- 'https://example.com/?a=1&b=2'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:wget:https://example.com/?a=1&b=2` | false positive | yes |
| 25 | RC1 | main | `gh api 'repos/a/b/pulls?state=open&per_page=5'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:gh:repos/a/b/pulls?state=open&per_page=5` | false positive | yes |
| 26 | RC1 | sub/dev | `gh api 'repos/a/b/pulls?state=open&per_page=5'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:gh:repos/a/b/pulls?state=open&per_page=5` | false positive | yes |
| 27 | RC1 | main | `gh api 'repos/a/b/commits?sha=main&per_page=3' --jq '.[].sha'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:gh:repos/a/b/commits?sha=main&per_page=3` | false positive | yes |
| 28 | RC1 | sub/dev | `gh api 'repos/a/b/commits?sha=main&per_page=3' --jq '.[].sha'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:gh:repos/a/b/commits?sha=main&per_page=3` | false positive | yes |
| 29 | RC1 | main | `http GET 'https://example.com/?a=1&b=2'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:http:https://example.com/?a=1&b=2` | false positive | yes |
| 30 | RC1 | sub/dev | `http GET 'https://example.com/?a=1&b=2'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:http:https://example.com/?a=1&b=2` | false positive | yes |
| 31 | RC1 | main | `psql -X -U app -d app -c 'SELECT count(*) FROM jobs'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs` | false positive | yes |
| 32 | RC1 | sub/dev | `psql -X -U app -d app -c 'SELECT count(*) FROM jobs'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs` | false positive | yes |
| 33 | RC1 | main | `psql -U app -d app -c "SELECT status, count(*) FROM jobs GROUP BY status ORDER BY 2 DESC;"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT status, count(*) FROM jobs GROUP BY status ORDER BY 2` | false positive | yes |
| 34 | RC1 | sub/dev | `psql -U app -d app -c "SELECT status, count(*) FROM jobs GROUP BY status ORDER BY 2 DESC;"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT status, count(*) FROM jobs GROUP BY status ORDER BY 2` | false positive | yes |
| 35 | RC1 | main | `psql -U app -d app -At -c "select count(*) from jobs where status='failed'"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:select count(*) from jobs where status='failed'` | false positive | yes |
| 36 | RC1 | sub/dev | `psql -U app -d app -At -c "select count(*) from jobs where status='failed'"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:select count(*) from jobs where status='failed'` | false positive | yes |
| 37 | RC1 | main | `PGOPTIONS='-c default_transaction_read_only=on' psql -X -U app -d app -c 'select count(*) from jobs'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:select count(*) from jobs` | false positive | yes |
| 38 | RC1 | sub/dev | `PGOPTIONS='-c default_transaction_read_only=on' psql -X -U app -d app -c 'select count(*) from jobs'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:select count(*) from jobs` | false positive | yes |
| 39 | RC1 | main | `psql -U app -d app -c 'SELECT count(*) FROM jobs' > reports/jobs-count.txt` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs` | false positive | yes |
| 40 | RC1 | sub/dev | `psql -U app -d app -c 'SELECT count(*) FROM jobs' > reports/jobs-count.txt` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs` | false positive | yes |
| 41 | RC1 | sub/general-purpose | `psql -U app -d app -c 'SELECT count(*) FROM jobs' > reports/jobs-count.txt` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs` | false positive | yes |
| 42 | RC1 | sub/qa | `psql -U app -d app -c 'SELECT count(*) FROM jobs' > reports/jobs-count.txt` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs` | false positive | yes |
| 43 | RC1 | main | `sqlite3 data/app.db 'SELECT count(*) FROM users;'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:sqlite3:SELECT count(*) FROM users;` | false positive | yes |
| 44 | RC1 | sub/dev | `sqlite3 data/app.db 'SELECT count(*) FROM users;'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:sqlite3:SELECT count(*) FROM users;` | false positive | yes |
| 45 | RC1 | main | `sqlite3 -header -column data/app.db "SELECT name, count(*) FROM events GROUP BY name ORDER BY 2 DESC LIMIT 10;"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:sqlite3:SELECT name, count(*) FROM events GROUP BY name ORDER BY 2 D` | false positive | yes |
| 46 | RC1 | sub/dev | `sqlite3 -header -column data/app.db "SELECT name, count(*) FROM events GROUP BY name ORDER BY 2 DESC LIMIT 10;"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:sqlite3:SELECT name, count(*) FROM events GROUP BY name ORDER BY 2 D` | false positive | yes |
| 47 | RC1 | main | `mysql -u app appdb -e "SELECT status, COUNT(*) FROM orders GROUP BY status;"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:mysql:SELECT status, COUNT(*) FROM orders GROUP BY status;` | false positive | yes |
| 48 | RC1 | sub/dev | `mysql -u app appdb -e "SELECT status, COUNT(*) FROM orders GROUP BY status;"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:mysql:SELECT status, COUNT(*) FROM orders GROUP BY status;` | false positive | yes |
| 49 | RC1 | main | `docker exec app-postgres psql -U app -d app -c "SELECT count(*) FROM jobs WHERE status = 'done';"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs WHERE status = 'done';` | false positive | yes |
| 50 | RC1 | sub/dev | `docker exec app-postgres psql -U app -d app -c "SELECT count(*) FROM jobs WHERE status = 'done';"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs WHERE status = 'done';` | false positive | yes |
| 51 | RC1 | main | `docker exec app-mysql mysql -uroot -e 'SELECT COUNT(*) FROM appdb.orders'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:mysql:SELECT COUNT(*) FROM appdb.orders` | false positive | yes |
| 52 | RC1 | sub/dev | `docker exec app-mysql mysql -uroot -e 'SELECT COUNT(*) FROM appdb.orders'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:mysql:SELECT COUNT(*) FROM appdb.orders` | false positive | yes |
| 53 | RC1 | main | `docker compose exec db psql -U app -d app -c 'SELECT count(*) FROM jobs'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs` | false positive | yes |
| 54 | RC1 | sub/dev | `docker compose exec db psql -U app -d app -c 'SELECT count(*) FROM jobs'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FROM jobs` | false positive | yes |
| 55 | RC1 | main | `for i in 1 2 3; do curl -s "http://localhost:3000/api/items?page=$i&limit=5" \| jq length; done` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:` | false positive | yes |
| 56 | RC1 | sub/dev | `for i in 1 2 3; do curl -s "http://localhost:3000/api/items?page=$i&limit=5" \| jq length; done` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:` | false positive | yes |
| 57 | RC1 | sub/general-purpose | `for i in 1 2 3; do curl -s "http://localhost:3000/api/items?page=$i&limit=5" \| jq length; done` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:` | false positive | yes |
| 58 | RC1 | sub/qa | `for i in 1 2 3; do curl -s "http://localhost:3000/api/items?page=$i&limit=5" \| jq length; done` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:` | false positive | yes |
| 59 | RC1 | main | `psql -U app -d app -c "SELECT date_trunc('day', created_at) AS d, count(*) FROM jobs GROUP BY 1 ORDER BY 1"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT date_trunc('day', created_at) AS d, count(*) FROM job` | false positive | yes |
| 60 | RC1 | sub/dev | `psql -U app -d app -c "SELECT date_trunc('day', created_at) AS d, count(*) FROM jobs GROUP BY 1 ORDER BY 1"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT date_trunc('day', created_at) AS d, count(*) FROM job` | false positive | yes |
| 61 | RC1 | main | `psql -U app -d app -c "SELECT count(*) FILTER (WHERE status = 'failed') FROM jobs"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FILTER (WHERE status = 'failed') FROM jobs` | false positive | yes |
| 62 | RC1 | sub/dev | `psql -U app -d app -c "SELECT count(*) FILTER (WHERE status = 'failed') FROM jobs"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:SELECT count(*) FILTER (WHERE status = 'failed') FROM jobs` | false positive | yes |
| 63 | RC1 | main | `sqlite3 data/app.db "select date(ts), count(*) from events group by 1 order by 1 desc limit 14"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:sqlite3:select date(ts), count(*) from events group by 1 order by 1` | false positive | yes |
| 64 | RC1 | sub/dev | `sqlite3 data/app.db "select date(ts), count(*) from events group by 1 order by 1 desc limit 14"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:sqlite3:select date(ts), count(*) from events group by 1 order by 1` | false positive | yes |
| 65 | RC1 | main | `docker exec app-postgres psql -U app -d app -At -F, -c "select source, count(*) from jobs group by source" > reports/by-source.csv` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:select source, count(*) from jobs group by source` | false positive | yes |
| 66 | RC1 | sub/dev | `docker exec app-postgres psql -U app -d app -At -F, -c "select source, count(*) from jobs group by source" > reports/by-source.csv` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:select source, count(*) from jobs group by source` | false positive | yes |
| 67 | RC1 | sub/general-purpose | `docker exec app-postgres psql -U app -d app -At -F, -c "select source, count(*) from jobs group by source" > reports/by-source.csv` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:select source, count(*) from jobs group by source` | false positive | yes |
| 68 | RC1 | sub/qa | `docker exec app-postgres psql -U app -d app -At -F, -c "select source, count(*) from jobs group by source" > reports/by-source.csv` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:psql:select source, count(*) from jobs group by source` | false positive | yes |
| 69 | RC1 | main | `clickhouse-client -q 'SELECT count(*) FROM events'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:clickhouse-client:SELECT count(*) FROM events` | false positive | yes |
| 70 | RC1 | sub/dev | `clickhouse-client -q 'SELECT count(*) FROM events'` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:clickhouse-client:SELECT count(*) FROM events` | false positive | yes |
| 71 | RC1 | main | `duckdb -c "select count(*) from read_csv_auto('data/sales.csv')"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:duckdb:select count(*) from read_csv_auto('data/sales.csv')` | false positive | yes |
| 72 | RC1 | sub/dev | `duckdb -c "select count(*) from read_csv_auto('data/sales.csv')"` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:duckdb:select count(*) from read_csv_auto('data/sales.csv')` | false positive | yes |
| 73 | RC1 | main | `diff <(curl -s 'https://a.example.com/v1/x?a=1&b=2') <(curl -s 'https://b.example.com/v1/x?a=1&b=2')` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://a.example.com/v1/x?a=1&b=2` | false positive | yes |
| 74 | RC1 | sub/dev | `diff <(curl -s 'https://a.example.com/v1/x?a=1&b=2') <(curl -s 'https://b.example.com/v1/x?a=1&b=2')` | pretool-bash-safety.sh | removal-policy UNRESOLVED unproven_boundary_with_removal_reference | `BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:https://a.example.com/v1/x?a=1&b=2` | false positive | yes |
| 75 | RC2 | main | `rm -f /tmp/q.csv` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 76 | RC2 | sub/dev | `rm -f /tmp/q.csv` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 77 | RC2 | sub/general-purpose | `rm -f /tmp/q.csv` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 78 | RC2 | sub/qa | `rm -f /tmp/q.csv` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 79 | RC2 | main | `rm /tmp/notes.txt` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 80 | RC2 | sub/dev | `rm /tmp/notes.txt` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 81 | RC2 | sub/general-purpose | `rm /tmp/notes.txt` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 82 | RC2 | sub/qa | `rm /tmp/notes.txt` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 83 | RC2 | main | `rm -rf /tmp/work` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 84 | RC2 | sub/dev | `rm -rf /tmp/work` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 85 | RC2 | sub/general-purpose | `rm -rf /tmp/work` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 86 | RC2 | sub/qa | `rm -rf /tmp/work` | pretool-bash-safety.sh | removal-policy FORBIDDEN_REMOVAL filesystem_removal | `BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm` | policy (harmless cmd) | yes |
| 87 | RC3 | sub/dev | `curl -s "https://api.example.com/q?from=2024-01-01&to=2024-02-01" > /tmp/q.json && jq length /tmp/q.json` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy system_temp (role=dev tool=Write) | `BLOCKED by tool-policy.v1: {"role":"dev","tool":"Write","target":"/tmp/q.json","deny_reason":"arbitrary /tmp and /var/tmp are denied for every role; u…` | policy (harmless cmd) | yes |
| 88 | RC3 | sub/dev | `cat > /tmp/notes.txt <<'EOF'⏎ some notes⏎ EOF` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy system_temp (role=dev tool=Write) | `BLOCKED by tool-policy.v1: {"role":"dev","tool":"Write","target":"/tmp/notes.txt","deny_reason":"arbitrary /tmp and /var/tmp are denied for every role…` | policy (harmless cmd) | yes |
| 89 | RC3 | sub/dev | `grep -rn TODO src > /tmp/todos.txt` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy system_temp (role=dev tool=Write) | `BLOCKED by tool-policy.v1: {"role":"dev","tool":"Write","target":"/tmp/todos.txt","deny_reason":"arbitrary /tmp and /var/tmp are denied for every role…` | policy (harmless cmd) | yes |
| 90 | RC3 | sub/dev | `cp config.example.yml /tmp/config.yml` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy system_temp (role=dev tool=Write) | `BLOCKED by tool-policy.v1: {"role":"dev","tool":"Write","target":"/tmp/config.yml","deny_reason":"arbitrary /tmp and /var/tmp are denied for every rol…` | policy (harmless cmd) | yes |
| 91 | RC4 | sub/qa | `curl -s "https://api.example.com/q?from=2024-01-01&to=2024-02-01" > /tmp/q.json && jq length /tmp/q.json` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target /tmp/q.json not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"/tmp/q.json","deny_reason":"write target /tmp/q.json not in allowed_write_path_prefix…` | policy (harmless cmd) | yes |
| 92 | RC4 | sub/qa | `psql -U app -d app -c 'SELECT count(*) FROM jobs' > reports/jobs-count.txt` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target reports/jobs-count.txt not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"reports/jobs-count.txt","deny_reason":"write target reports/jobs-count.txt not in all…` | policy (harmless cmd) | yes |
| 93 | RC4 | sub/qa | `mysql -u app appdb --batch -e 'select * from orders limit 3' > reports/orders.tsv` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target reports/orders.tsv not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"reports/orders.tsv","deny_reason":"write target reports/orders.tsv not in allowed_wri…` | policy (harmless cmd) | yes |
| 94 | RC4 | sub/qa | `docker exec -i app-postgres psql -X -U app -d app -P pager=off > /srv/app/tests/reports/age.txt <<'SQL'⏎ SELECT count(*) FROM jobs WHERE posted_at >= now() - interval '7 days' GROUP BY 1 ORDER BY 1;⏎ SQL` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target /srv/app/tests/reports/age.txt matches denied_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"/srv/app/tests/reports/age.txt","deny_reason":"write target /srv/app/tests/reports/ag…` | policy (harmless cmd) | yes |
| 95 | RC4 | sub/qa | `python3 scripts/stats.py --since 2024-01-01 > reports/stats.txt` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target reports/stats.txt not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"reports/stats.txt","deny_reason":"write target reports/stats.txt not in allowed_write…` | policy (harmless cmd) | yes |
| 96 | RC4 | sub/qa | `mkdir -p reports && wc -l src/*.py > reports/loc.txt` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target reports/loc.txt not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"reports/loc.txt","deny_reason":"write target reports/loc.txt not in allowed_write_pat…` | policy (harmless cmd) | yes |
| 97 | RC4 | sub/qa | `cat > /tmp/notes.txt <<'EOF'⏎ some notes⏎ EOF` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target /tmp/notes.txt not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"/tmp/notes.txt","deny_reason":"write target /tmp/notes.txt not in allowed_write_path_…` | policy (harmless cmd) | yes |
| 98 | RC4 | sub/qa | `cat <<'EOF' > reports/summary.md⏎ # Summary⏎ - 3 failures⏎ EOF` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target reports/summary.md not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"reports/summary.md","deny_reason":"write target reports/summary.md not in allowed_wri…` | policy (harmless cmd) | yes |
| 99 | RC4 | sub/qa | `grep -rn TODO src > /tmp/todos.txt` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target /tmp/todos.txt not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"/tmp/todos.txt","deny_reason":"write target /tmp/todos.txt not in allowed_write_path_…` | policy (harmless cmd) | yes |
| 100 | RC4 | sub/qa | `grep -rn TODO src > reports/todos.txt` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target reports/todos.txt not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"reports/todos.txt","deny_reason":"write target reports/todos.txt not in allowed_write…` | policy (harmless cmd) | yes |
| 101 | RC4 | sub/qa | `echo done >> reports/run.log` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target reports/run.log not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"reports/run.log","deny_reason":"write target reports/run.log not in allowed_write_pat…` | policy (harmless cmd) | yes |
| 102 | RC4 | sub/qa | `jq . /tmp/q.json \| tee reports/q.pretty.json \| head` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target reports/q.pretty.json not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"reports/q.pretty.json","deny_reason":"write target reports/q.pretty.json not in allow…` | policy (harmless cmd) | yes |
| 103 | RC4 | sub/qa | `{ date; git rev-parse HEAD; } > reports/meta.txt` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target reports/meta.txt not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"reports/meta.txt","deny_reason":"write target reports/meta.txt not in allowed_write_p…` | policy (harmless cmd) | yes |
| 104 | RC4 | sub/qa | `cp config.example.yml /tmp/config.yml` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target /tmp/config.yml not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"/tmp/config.yml","deny_reason":"write target /tmp/config.yml not in allowed_write_pat…` | policy (harmless cmd) | yes |
| 105 | RC4 | sub/qa | `docker exec app-postgres psql -U app -d app -At -F, -c "select source, count(*) from jobs group by source" > reports/by-source.csv` | pretool-write-gate.py > pretool-tool-policy.py | tool-policy write target reports/by-source.csv not in allowed_write_path_prefixes (role=qa tool=Write) | `BLOCKED by tool-policy.v1: {"role":"qa","tool":"Write","target":"reports/by-source.csv","deny_reason":"write target reports/by-source.csv not in allow…` | policy (harmless cmd) | yes |

p14-only refusals: 0
