# Installation

How to install the harness, what init writes, how settings and the machine overlay work, and what to do when something does not install.

[Back to the README](../README.md)


There are two install paths. The **full install** is a clone plus one init run; the installer's
`core` profile is a **guardrails-only** install.

| Path | What you get | How |
|---|---|---|
| **Full harness** — clone + init | Every hook, agent, command and skill, the release pipeline, the settings overlay and filter, and the commit protection described below. Optional modules are chosen at init. | Clone the repository into any directory and run `scripts/bootstrap` (init) there. |
| **Guardrails only** — installer `core` profile | The background-dispatch hook and the `EnterWorktree` hook (each exits 2 on the call it guards; the [enforcement ledger](ENFORCEMENT-LEDGER.md) labels both advisory) plus the shared resolver and the preflight, copied into an isolated directory and registered additively in your existing Claude config home. No agents, skills, overlay, filter or init, and one command, `/harness-doctor`, that runs the installed preflight. | `scripts/install/install --profile core` from a checkout ([below](#guardrails-only-the-installer-core-profile)). |

Verify prerequisites — `python3`, `git`, `jq` (or run `scripts/doctor` for a full preflight):

```bash
python3 --version && git --version && jq --version
```

## Full install: clone + init

Clone into Claude Code's default configuration directory, `~/.claude`, and run init there:

```bash
git clone https://github.com/Yugoge/awesome-claude-harness.git ~/.claude
~/.claude/scripts/bootstrap        # init: asks once per optional module (Enter = off)
```

`git clone` refuses a non-empty target directory: if Claude Code has already created
`~/.claude`, move it aside first, or clone somewhere else ([Other install locations](#other-install-locations)).

Init is idempotent and safe to re-run on a populated home. In order, it:

1. reuses the harness venv `<harness-home>/venv` when it already imports `pytest`, `jsonschema`
   and `yaml`; installs them into it, hash-verified, when it exists without them; creates it when
   absent, with the first of `python3`, `python3.12`, `python3.11`, `python3.10` that has a
   hash-locked lockfile under `requirements/`;
2. writes the machine overlay `<harness-home>/settings.machine.json` — **only when it is
   absent** — holding the module choices and `env.CLAUDE_HOME = <harness-home>`;
3. registers the settings filter in the clone's local git config, sets `harness.autoPush false`
   there when the key is absent ([automatic push, per repository](#automatic-push-per-repository)),
   and renders the working `settings.json` (clean form + enabled modules + overlay);
4. creates, **only when absent** (it never overwrites any of them):
   - `<harness-home>/logs/`;
   - the `TMPDIR` root named by the rendered settings (`/var/tmp/claude-scratch` by default), mode 1777;
   - the empty private-literal list `<harness-home>/private-literals.txt`, mode 0600;
   - `~/.config/claude/protected-runtime.json` (or the path in `CLAUDE_PROTECTED_RUNTIME_FILE`)
     with `"schema_version": 1` and the keys `protected_cmds`, `protected_launch_paths`,
     `protected_services`, `protected_hotfiles`, `protected_statefiles`,
     `protected_endpoint_paths`, `protected_proc_idents`, `protected_global_bins`,
     `protected_build_workspaces` and `protected_build_paths`, each an empty list;
5. installs the pre-commit hook where git runs hooks for the clone (`core.hooksPath`
   respected), but only into this repository's own hooks directory: under its git directory,
   or named by `core.hooksPath` in its local (or worktree) config. A global, system or
   command-line `core.hooksPath` can serve every repository on the machine, so init writes
   nothing there, finishes the other steps and exits non-zero, printing the
   `git config --local core.hooksPath …` command that gives the clone its own hooks directory
   (copy your own hooks there first, then re-run init);
6. makes the shell hooks executable, runs `scripts/doctor`, repeats the entries render or
   doctor asked to move into the overlay, and exits non-zero if a required check failed or the
   pre-commit hook was not installed.

`protected-runtime.json` configures the runtime guard (`hooks/lib/runtime_guard/`). Without a
valid file the guard cannot tell what it protects, so for the verb families it covers (`npm`,
`node`, `npx`, `yarn`, `kill`, …) it returns a block verdict and `hooks/pretool-bash-safety.sh`
exits 2 (the [enforcement ledger](ENFORCEMENT-LEDGER.md) labels that hook advisory). List your own
services, launch paths and state files in it to have the guard protect them.

| Init flag | Effect |
|---|---|
| `--yes` | Non-interactive: asks nothing; every optional module not named by `--with` is off. |
| `--with <module>` / `--without <module>` | Enable / disable a module without asking (repeatable; the known module is `paseo`). |
| `--migrate-from <rev>` [`--settings-file <path>`] | Seed a **new** overlay from a previous personal `settings.json` — the file at git revision `<rev>`, or the given file — instead of the default overlay: the entries the clean form lacks (env values, permission entries, hook groups, top-level keys), the previous built-in defaults of the personal-value settings, and the enabled modules; a previous `GIT_AUTO_PUSH` of `"1"` is not carried over. Ignored, with a note, when an overlay already exists (`scripts/install/render-settings migrate` itself refuses). |
| `--force` | Back up and re-create the venv. Also lets the render replace a working `settings.json` holding entries the overlay does not explain (those entries are dropped — move them into the overlay first). |
| `--no-doctor` | Skip the final `scripts/doctor` run. |
| `--steps <list>` | Run only the given steps among 2-5 (comma-separated), without asking and without the venv, resolver and doctor steps (the landing below runs `--steps 3,4,5`). |

Module flags take effect only when init writes a new overlay. Once an overlay exists its
`modules` key wins: change it there and re-run init.

### Automatic push, per repository

The automatic pushes (the checkpoint push, git-fswatch's push, session-git-init's first push, and
the post-commit backup hook `hooks/git-hooks/post-commit-auto-push` where you copied it into a
repository) run where `GIT_AUTO_PUSH` is `"1"`; set it in the overlay's `env` (the tracked clean
form sets `"0"`).
A repository's own git config decides before that switch, for that repository only:

```bash
git -C <repo> config --local harness.autoPush true      # this repository pushes automatically
git -C <repo> config --local harness.autoPush false     # this repository never does
git -C <repo> config --local --unset harness.autoPush   # GIT_AUTO_PUSH decides again
```

Init and the landing set `false` in the harness home when the key is absent, because its `origin`
is the public repository; they never change a value you set. A value git cannot read as a boolean
means no push. `/push` is not affected. The post-commit hook reads the switch through the
harness's `hooks/lib/auto_push.sh`, found under `CLAUDE_HOME` or `~/.claude` (none there: no
push, and with `GIT_AUTO_PUSH` at `"1"` the commit prints why). A copy you made of an earlier
version, byte for byte, is replaced by the current one at a turn end (the first one after this
rule arrives, and again after each pull that writes the hook), in the harness home and in the
repositories under `$HOME`; a copy you edited, or one a repository tracks, stays as it is.

**Upgrading a home that predates the overlay.** A home that ran code from before the settings
filter (its HEAD reflog, or `ORIG_HEAD`, holds such a revision) lands by itself at the next turn
end of any of its sessions; nothing has to be stopped or typed. `hooks/auto-commit.sh` runs
`scripts/install/land`, one session at a time, which never blocks the Stop and shows one line:
it undoes what a conflicted stash pop of the pull left (`settings.json` from upstream, the paths
the pop staged unstaged, the stash entry kept), migrates the previous personal settings into a
new overlay (a `GIT_AUTO_PUSH` of `"1"` is not carried over), seeds an empty
`private-literals.txt` from values the machine already holds, replaces post-commit hooks that are
copies of an earlier `post-commit-auto-push` and renames aside the other ones that push unless
`GIT_AUTO_PUSH` is `0` (here and in the repositories under `$HOME`), restarts
git-fswatch daemons running older code with their own environment (one in its git work, or in a
repository with a stopped rebase, at a later turn end), and runs init steps 3-5. At each turn
end it also sets `harness.autoPush false` in the home when the key is absent, already-landed
homes included.
A rebase or merge stopped in the home is left alone: the landing says so and waits.
`logs/landing.log` lists what it did (counts and key names, never a value). For a home without
sessions, `scripts/bootstrap --migrate-from <rev>` and `scripts/install/render-settings migrate`
remain.

**When the upstream history is rewritten.** A harness home moves to the rewritten history with its
next `/pull`, which rebases the home's own commits onto it; nothing has to be typed or stopped. The
home keeps its local data, pre-rewrite objects included (stash entries, checkpoint and backup refs,
reflogs), as recoverable local history, and its pre-push guard (installed by the landing beside
the pre-commit hook) refuses any push that would send an object holding a literal listed in
`private-literals.txt` ([the private-literal list](git-protection-kernel.md#commit-protection-the-pre-commit-hook-and-the-private-literal-list)),
naming the object. If that rebase stops on a conflict, `/pull` stops too and keeps its stash
entry: finish or abort the rebase, then `git stash pop`. Any other clone of the repository should
be cloned again.

## Other install locations

The harness can live in any directory. For a clone outside `~/.claude`:

```bash
git clone <repository-url> <clone>    # the same URL as above
<clone>/scripts/bootstrap              # writes CLAUDE_HOME=<clone> into the overlay
export CLAUDE_CONFIG_DIR=<clone>       # in the shell that launches Claude Code
claude
```

`CLAUDE_CONFIG_DIR` makes Claude Code read `<clone>/settings.json` and keep its runtime state
(`logs/`, `projects/`, `todos/`, …) in the clone too, so the harness home and Claude Code's
configuration directory are one directory again.

**The harness-home channel.** Every hook command in `settings.json` reaches its file through
one expression, `"${CLAUDE_HOME:-$HOME/.claude}/hooks/<file>"` (the `SessionStart` canary check
reaches its script under `scripts/` the same way). The tracked file never sets
`CLAUDE_HOME`: init writes it into the overlay's `env`, and Claude Code passes settings `env`
values to every hook process and Bash tool command it starts. Without an overlay (a fresh clone
before init) the fallback `$HOME/.claude` is the default install location. `CLAUDE_CONFIG_DIR`
is deliberately not the channel: a multi-account setup may point it at a per-account directory
that holds no harness. Scripts locate their harness home from their own location
(`hooks/lib/claude_home.{sh,py}`); runtime state lives under `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`,
except the hook state root (consent flags, grants, sentinels), which is `$CLAUDE_STATE_DIR` when
that is an absolute path and `/tmp` otherwise.

`CLAUDE_HOME` is the one channel for harness paths: hook commands and the prompts in `commands/`
and `agents/` use it. The prompts spell harness scripts as `${CLAUDE_HOME:-$HOME/.claude}/...` —
which is also why the harness-script permission allows use that literal form (Bash permission
rules match the command text, with no variable expansion; a few allow entries also keep the
older `~/.claude/scripts/...` spelling) — so prompt-issued commands reach a clone outside the
default location.

## Settings: one tracked source, a machine overlay, a git filter

- **One source.** The tracked `settings.json` is the clean public form and the only
  hand-maintained settings file; there is no separate template. It carries no machine values:
  no install path, no `CLAUDE_HOME`, no personal tool paths, no CLI-owned keys.
- **The overlay.** Everything machine-specific lives in `<harness-home>/settings.machine.json`
  — untracked and gitignored, created only when absent: by init, or once by the landing on a
  home upgraded from code before the filter (see the install section), which later also drops
  from its `hooks` the commands that HEAD retired or already runs; never by agents.
  [`settings.machine.example.json`](../settings.machine.example.json) documents every key:
  `modules`; `env` (sets or replaces a value); `permissions.allow` / `deny` / `ask` (appended —
  the overlay cannot remove a clean-form entry); `hooks` groups; any other top-level key
  (replaces the clean value). Top-level keys starting with `_` are documentation and are never
  rendered. The guard key `env.CLAUDE_HARD_BANNED_SCRIPTS` has a built-in default: unset or
  empty, the names `session-recovery` and `restart-all-sessions` match only as the command word
  (`NAME` or `NAME.sh`, any directory path, also after an assignment, a `<` redirect or a listed
  wrapper or shell such as `sudo`, `timeout 30` or `bash -x`): reading, listing, editing or
  naming the script passes unless the name stands right after a command separator (`;`, `|`,
  `(`, `!`, `&`) — inside quotes that is only text, unless a word outside the quotes can run
  text (a shell, `eval`, `ssh`, an interpreter, a `-c` or `-e` option) — and a script piped into
  a shell or run by `find -exec` or an unlisted wrapper (`watch`) is not seen. A set value
  replaces them with `|`-separated EREs, each matched anywhere in the command.
- **The filter.** [`.gitattributes`](../.gitattributes) declares
  `/settings.json filter=claude-settings`; init registers its clean and smudge commands
  (`scripts/install/render-settings`) in the clone's local git config, with `required = true`.
  Smudge (on checkout) and render write the machine form — clean form + enabled modules +
  overlay — and record the layers they applied in `<git dir>/claude-settings.applied` (mode
  0600; inside the git directory, so never tracked). Clean (on staging) strips everything the
  modules, the overlay and that record added, plus the CLI-owned keys, so the values of an entry
  dropped from the overlay, or of a deleted overlay, are still stripped until the next render
  drops them from the working file. Clean fails closed: on input it cannot parse (a UTF-8 byte
  order mark included) it exits non-zero and `git add` fails instead of storing the file
  unchanged.
- **Messages.** Render and doctor name settings entries by key path and count (`env.<KEY>`,
  `permissions.allow: <n> entries`), never by value; the staged check names only files and
  keys; init names `env.TMPDIR` by its key, not its path.

Day to day:

- After init, `git status` stays clean: git compares the clean form, so overlay values never
  show up as a diff and never reach a commit.
- After editing the overlay, re-run init (`scripts/bootstrap`) to re-render `settings.json`.
- To change the public settings (a hook, a deny rule), edit `settings.json` and commit as usual;
  the filter strips the machine values on the way in.
- **CLI-owned keys** — `model`, `theme`, `tui`, `alwaysThinkingEnabled`, `effortLevel`,
  `autoCompactEnabled`, `modelSettings`, `fastMode`, `advisorModel` — are written by Claude Code
  itself (`/model`, `/config`, `/effort`, `/fast`). A render keeps the value Claude Code wrote;
  the clean filter removes them, so they never reach a commit. Put a default in the overlay if
  you want one on a fresh render.
- A permission Claude Code writes into the working file ("always allow") is not explained by
  the overlay: it shows as a change to `settings.json`, and init's render refuses to overwrite
  it (unless `--force`) and doctor fails on it, both naming only its key path and a count. Move
  it into the overlay's `permissions.allow`. Until you do, the commit checks cannot tell it from
  a public edit: `git add settings.json` stages it, and they pass it unless it holds a listed
  private literal.

## Optional module: paseo

Init asks about each optional module; today that is `paseo` (multi-session monitoring and
scheduling, `/paseo-daemon`). It is off by default and with `--yes`. With it off, nothing paseo is
registered and nothing fails because paseo is absent; its command and scripts stay in the tree
for those who enable it. With it on, the module adds the allow entries `mcp__paseo__*` and
`Bash(node scripts/paseo-usage-read.mjs:*)`, the `UserPromptSubmit` hook
`hooks/userprompt-usage-snapshot.py`, and the `mcp__paseo__browser_run_code` matcher on the
runcode-watchdog groups; its accounts and model go into the overlay's `env`
(`PASEO_DAEMON_ACCOUNTS`, `PASEO_DAEMON_MODEL`). The `Skill(paseo-daemon:*)` deny stays in the
clean form either way.

## Doctor

`scripts/doctor` is the preflight init ends with; run it any time. Besides `python3`, `git`, `jq`,
`openssl`, the venv, the manifest packages and the resolver, it checks the settings
(`scripts/install/render-settings check`):

- every hook command resolves to an existing file under the harness home, other than an exit-0
  `# STUB:` file that the clean form does not register (it prints `missing=<n>`, `stubs=<n>` when
  there are any, and each offending path; a hook outside the clean form and the modules is named
  by its event only);
- the filter is declared, registered and `required`, the staged clean form survives a
  smudge-then-clean round trip, and, when an overlay exists, the record of what render applied
  is present (on a home that is not a git checkout it says so instead of failing);
- every working-file entry is explained by the clean form, the enabled modules or the overlay;
  each one that is not fails the check, named by key path and count only — stage it if it is a
  public edit, or move it into the overlay;
- `protected-runtime.json` loads with `schema_version` 1 and all its required keys.

It also lists, without failing, CLI-owned keys whose working value differs from the overlay.
`scripts/doctor --strict` runs, in place of the checks above, a fresh host-capability handshake
and prints a short compatibility report (`--verbose` adds the per-check detail). Doctor exits
non-zero when a required check fails; with `--strict`, unless the fresh handshake passes.

## Switching the harness off: /harness

`/harness off`, typed by the owner in Claude Code, switches off the harness home the session runs
from. `/harness on` switches it back on, and `/harness status` reports it. Only the owner's typed
prompt switches: a UserPromptSubmit hook (`hooks/userprompt-harness-switch.sh`) runs
`scripts/harness-switch`. An agent's call is refused while the harness is on, whatever path it
takes: `Skill`, `Bash`, a write of the switch's state or of the home's settings, a script, a
scheduled prompt, a `disableAllHooks` written into any project's settings file
(`hooks/pretool-harness-switch-guard.py`).

A session an agent's script starts is not the owner's. `scripts/harness-switch` walks the hook's
process ancestry, and when a Claude Code process runs above the session's own (a `claude -p
"/harness off"` a Bash call launched, or an interactive `claude` under `script` or `tmux`), it
refuses `off` and `on`, says so, and changes nothing; `/harness status` still answers. The
environment cannot tell the two sessions apart: Claude Code sets `CLAUDECODE` and
`CLAUDE_CODE_CHILD_SESSION` in a top-level session's hooks too. The owner's terminal, desktop app
or IDE session has one Claude Code process in its ancestry and switches as before.

**Known limits.** The agent guard covers the tools the harness names. An MCP tool that schedules a
prompt (a remote `send_later` or trigger tool, for example) is not covered: the prompt it fires
reaches UserPromptSubmit like a typed one, and the hook cannot tell them apart
(`hooks/userprompt-restart-authorize.py` documents the same limit). The nested-session check names
a Claude Code process by its executable (`claude`, the installer's `claude/versions/` copy, or
node/bun running the npm package's `claude`): a copy of the binary under another name is not
recognized.

**What off does.**

- **At once, in the typing session too.** No harness hook runs, for any event. Each registered
  hook first asks `hooks/lib/harness_switch.{py,sh}` and exits 0, printing nothing, while
  `<home>/.harness-switch/off` exists.
- **No background work.** Checkpoint snapshots, the git-fswatch sync (the daemon keeps running
  and does nothing), the landing, automatic pushes and the keystone are inert.
- **No live overnight run.** A `/dev-overnight` run live at the switch is over, so after
  `/harness on` it arms no time-lock. Its record gets `harness_off_at`, through
  `hooks/lib/overnight.py`'s one writer; the switch finds the records from the session's project. The command's own text has the session delete its
  wake, and while off the hook refuses the wake's prompts.
- **From the next session.**
  - settings.json is in its off form: no harness hook, env var or permission rule (the
    settings filter's "harness switch" in `scripts/install/render-settings`).
  - A sparse checkout leaves `CLAUDE.md`, `commands/` (all but `commands/harness.md`),
    `agents/` and `skills/` out of the working tree. git keeps them in the index, so `git pull`
    works while off and lands the new version hidden.

**What it keeps.** MCP servers (`.claude.json`), plugins, login and credentials, session history,
and your own settings: the overlay's entries (`env.CLAUDE_HOME` included), CLI-written keys,
anything else in settings.json the harness does not ship. Two keys the harness ships are kept,
because dropping them would change what is not the harness:

- `cleanupPeriodDays`: without it Claude Code deletes session history after 30 days.
- `deniedMcpServers`: it keeps three connectors off.

**What on does.** It restores settings.json byte for byte when nothing changed while off. When
something did, it keeps the owner's changes; after a pull, it brings the pulled version.

**Coverage, and a cut switch.** A switch covers one harness home: the git checkout it is typed in,
which is also that account's Claude Code config dir. With one config dir per account
(`CLAUDE_CONFIG_DIR`), each account's clone has its own switch. A switch cut halfway leaves
`<home>/.harness-switch/journal.json`: `/harness status` names the step it reached, and the next
`/harness off` or `/harness on` finishes it first. `scripts/harness-switch status` gives the same
report in a terminal (exit 0 on, 3 off, 4 partial), and `scripts/doctor` prints it and exits 3
while the harness is off.

## Guardrails only: the installer `core` profile

The installer puts the guardrails in their own isolated directory and adds only a short,
enumerable list of paths to your Claude config home — it never clones over it, and merges its
hook registrations into your existing `settings.json` additively instead of replacing it:

```bash
scripts/install/install --dry-run --profile core
scripts/install/install --profile core
```

`--dry-run` prints every path it would create or modify and writes nothing. A strict preflight
runs before the first mutation and aborts the install if a baseline dependency or the Python 3.10
floor fails; a failing host-capability handshake prints an UNPROTECTED HOST verdict and aborts the
install only with `--require-handshake`. `--config-dir` and `--prefix` override the detected
Claude config home and the isolated install location.

Remove everything it added — taking only its own hook registrations back out of `settings.json`
(the pre-install file is written back whole only when `settings.json` is still exactly what the
installer wrote), and leaving files you created yourself in place — with:

```bash
scripts/install/uninstall
```

**Does it work on macOS?** No — there is no confirmed support and no CI coverage; the CI matrix
is Linux-only by explicit configuration. The installer parses
[`docs/reference/install-compatibility-matrix.md`](reference/install-compatibility-matrix.md)
and prints the status for your host rather than assuming one.

Run the guard demo: `bash examples/guard-demo/run-demo.sh`

## Try it without Claude Code

The project ships a runnable demo exercising the real guard (`pretool-tool-policy.py`) against an isolated ephemeral home — no Claude Code session needed:

```bash
examples/guard-demo/run-demo.sh
```

| Phase | Expected result | Exit code |
|---|---|---|
| STEP 1 — dangerous operation | The guard script exits 2 with its policy-deny marker | 2 |
| STEP 2 — authorized fix | ALLOWED (exit 0) — operation is within policy | 0 |
| STEP 3 — fix completes | Fix write landed on disk | — |

Exit 0 = allow, exit 2 = deny. The demo drives the guard script directly and reads its exit code, so it shows what the script returns, not a Claude Code host stopping a call (the [enforcement ledger](ENFORCEMENT-LEDGER.md) labels the guard advisory). See [`examples/guard-demo/run-demo.sh`](../examples/guard-demo/run-demo.sh) for details.

## Portability

A clone works from any directory after one init run ([Install](#installation)); no path in a tracked
file has to be rewritten. What carries that, and where it stops:

| Property | Mechanism | Caveat |
|---|---|---|
| **No install path in the tracked settings** | Every hook command in `settings.json` reaches its file through `${CLAUDE_HOME:-$HOME/.claude}`; init writes `CLAUDE_HOME` into the untracked overlay `settings.machine.json` | Before init (no overlay) the fallback `$HOME/.claude` applies — the default install location |
| **Scripts find their own home** | `hooks/lib/claude_home.{sh,py}` walk up from the script's location to the `settings.json + hooks/ + policies/ + scripts/` sentinel set | The repository may be cloned to any path |
| **Runtime state follows Claude Code's configuration directory** | State paths resolve under `${CLAUDE_CONFIG_DIR:-$HOME/.claude}` (hook grants and flags: `$CLAUDE_STATE_DIR`, else `/tmp`) | For a clone outside `~/.claude`, start Claude Code with `CLAUDE_CONFIG_DIR=<clone>` ([Other install locations](#other-install-locations)) |
| **Machine values stay out of commits** | Clean/smudge filter + overlay + the record of what render applied; the pre-commit hook's `render-settings check --staged` and private-literal rule, also run on checkpoint snapshots; CI's `check --staged` | Local protection needs init in that clone; CI has no overlay, so it cannot tell a personal entry from a public one |
| **A broken install is reported, not silent** | `scripts/doctor`: every hook path resolves, the filter round-trips, `protected-runtime.json` loads | — |
| **External extras degrade gracefully, never fall back unsafely** | D2 dependency table (below) | Codex CLI **never** falls back to a bare unsafe `codex`; bwrap absence → the in-place overnight launch is refused |

The prompts in `commands/`, `agents/` and `skills/` run harness files through the same
`${CLAUDE_HOME:-$HOME/.claude}` channel and take the project root as
`${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}`, so the commands they issue reach a clone
outside `~/.claude`. Not yet portable: `commands/close.md` (its `--force` audit log) and
`commands/redev.md` (its fallback read of `commands/dev.md`) still name `~/.claude/...`; every
other mention of `~/.claude` in the prompts only names the default location.

## Dependencies

### Quick dependency reference

| Tier | Component | Needed for | On absence |
|---|---|---|---|
| Tier 0 — core | Claude Code, Python 3 + venv, git ≥ 2.4x, jq, Bash/GNU userland | Everything | Guards fail silently / kernel inactive |
| Tier 1 — release | openssl | /merge, /push nonce grants | Those commands fail at grant-write step |
| Tier 1 — release | pytest + jsonschema + pyyaml (via bootstrap) | /test, generated AC tests | /test fails; test skeletons cannot execute |
| Tier 2 — overnight | bwrap (bubblewrap) | /dev-overnight write boundary | The default in-place launch is refused (no state written); a `--worktree` launch runs, and the overnight hook guard exits 2 for a command it cannot prove worktree-local (security-relevant) |
| Tier 2 — overnight | Playwright MCP | User-facing QA, UI audits, overnight PM | `agents/qa.md` requires a `fail` verdict for a user-facing change that cannot be browser-verified |
| Tier 3 — optional | Codex CLI + CODEX_ISO_BIN | --codex adversarial rounds | --codex unavailable; pipeline unaffected |
| Tier 3 — optional | graphify + GRAPHIFY_BIN | Code-graph enrichment in Dev context | Dev skips enrichment; proceeds degraded |
| Tier 3 — optional | websocket-client | Websocket enrichments | Silently skipped; core pipeline unaffected |

<details>
<summary>Dependency requirements</summary>

| Dependency | Tier | What needs it | Degrades when missing |
|---|---|---|---|
| [Claude Code](https://claude.com/claude-code) | **REQUIRED** | The host. Must be recent enough to fire `UserPromptSubmit` / `Notification` / `SubagentStop` hook events, honor `disable-model-invocation` frontmatter, and enforce `Skill(*)` permission denies — older clients silently skip these and the guardrails won't engage. | All hooks fail silently — the entire guardrail stack disengages. |
| Python 3 + the harness venv at `<harness-home>/venv` | **REQUIRED** | Hook commands run `python3` (the git kernel, gates); several hooks, the helper scripts and the tests use the venv's interpreter. The venv is not tracked — init (`scripts/bootstrap`) creates it from a hash-locked lockfile and installs the manifest, or reuses one that already has the manifest packages. | Python hooks fail at import time; git kernel inactive. |
| `git` | **REQUIRED** | The whole harness is git-native (checkpoints, grants, keystone). Any recent git (2.4x+) works for normal use; the overnight keystone needs **git ≥ 2.46** (verified by `scripts/overnight-git-selftest.sh`). | No checkpoints, no grant-gated git operations, no overnight loop. |
| `git reference-transaction` hook (keystone) | **REQUIRED keystone** | The overnight keystone (`hooks/git-keystone/`) installs a `reference-transaction` hook into `<git-common-dir>/keystone-hooks/` and sets `core.hooksPath`; it fires atomically on every HEAD/ref move. Needs git ≥ 2.46. | Without it, the overnight session (in the checkout, or in its linked worktree under `--worktree`) has no structural protection against unauthorized `HEAD` rewrites. Core `/dev` pipeline is unaffected. |
| `jq` | **REQUIRED** | JSON parsing in shell hooks/scripts across the pipeline. | Shell hooks that parse the cycle context (`docs/dev/context-*.json`) silently fail or misparse JSON. |
| Bash + GNU userland (coreutils, util-linux/`flock`, findutils, `grep`, `sed`, `awk`/gawk) | **REQUIRED** | `realpath`, `flock`, `stat`, `sha256sum`, `date`, `grep`, `sed`, `awk`, `find` are used pervasively. The GNU forms are assumed — BSD/macOS variants differ in flags; install the GNU userland there. | Hook failures on BSD/macOS with wrong flag variants; `flock`-based serialization unavailable. |
| `pytest`, `jsonschema`, `pyyaml` (the test/runtime manifest) | **REQUIRED** for `/test` + generated tests | Declared as compatible ranges in [`requirements.txt`](../requirements.txt) and installed, hash-verified, from the per-interpreter lockfile `requirements/py3XX.txt` by `scripts/bootstrap`; `scripts/doctor` reports any that are missing. | `/test` fails; test-writer skeletons cannot be executed; schema validation unavailable. |
| OpenAI Codex CLI + an isolation wrapper (`CODEX_ISO_BIN`) | **REQUIRED** for `--codex` / `/codex` | The adversarial second-opinion rounds shell out to the Codex CLI through a fail-closed isolation wrapper. **You must supply your own** Codex CLI and wrapper and point `CODEX_ISO_BIN` at it. | `--codex` / `/codex` unavailable; rest of the pipeline unaffected. |
| `openssl` | **REQUIRED** for `/merge`, `/push` | Nonce / token generation in the grant-gated git release path. | `/merge` and `/push` cannot generate nonce-keyed grants → those commands fail at grant-write step. |
| `bwrap` (bubblewrap) | **REQUIRED** for `/dev-overnight` | The per-Bash bind-mount boundary that isolates overnight main-tree writes. | The default in-place launch is refused, writing no state and naming bubblewrap and the `--worktree` remedy; a `--worktree` launch still works, and the overnight hook guard exits 2 for a command it cannot prove worktree-local (security-relevant). |
| `graphify` CLI (`graphifyy` v0.8.25 on PyPI; the binary is `graphify`) | OPTIONAL (graceful) | Incremental code-graph enrichment injected into the Dev context. Default-enabled (`CLAUDE_GRAPHIFY_ENABLED=auto`). Install: `<harness-home>/venv/bin/pip install graphifyy`, then put `graphify` on `PATH` or set `GRAPHIFY_BIN` to it in the overlay's `env`. | Code-graph context absent from Dev dispatch; Dev still runs — quality may be lower on large refactors. |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | OPTIONAL overall; **REQUIRED for user-facing QA/E2E + UI audits** | Powers the UI-audit skill suite, the overnight PM's live-app exploration, and QA's live browser verification of user-facing changes. Not needed for doc/config/non-user-facing cycles. | Non-user-facing cycles unaffected; for a user-facing change that cannot be browser-verified, `agents/qa.md` requires a `fail` verdict, while QA's stop hook (`hooks/subagentstop-e2e-enforce.py`) reads only the report's `e2e_enforcement.status` and cannot see whether the rendering happened. |
| Python pkg `websocket-client` | OPTIONAL (graceful) | A few websocket enrichments; hooks fall back to lenient paths when missing. | Websocket enrichments silently skipped; fallback path active. |

</details>

## Troubleshooting

| Symptom | Fix |
|---|---|
| **A hook isn't firing** | Run `scripts/doctor`: it lists every hook command whose file does not resolve under the harness home — for a clone outside `~/.claude`, usually a missing `env.CLAUDE_HOME` in `settings.machine.json` (re-run init) or Claude Code started without `CLAUDE_CONFIG_DIR=<clone>`. Shell hooks must be executable: `chmod +x <harness-home>/hooks/*.sh` (init does this). |
| **A slash command doesn't appear** | Check the YAML frontmatter at the top of the file in `commands/`; a malformed `---` block hides the command. |
| **`settings.json` won't load** | Validate both files: `python3 -m json.tool <harness-home>/settings.json` and `python3 -m json.tool <harness-home>/settings.machine.json` — a trailing comma or unquoted key surfaces here. Fix the overlay, then re-run init to re-render. |
| **`git status` shows `settings.json` modified after init** | The working file holds an entry the overlay does not explain — typically a permission Claude Code wrote ("always allow"). `scripts/doctor` fails on such entries, naming their key paths; move the machine-specific ones into `settings.machine.json` and re-run init. |
| **A commit is refused by the pre-commit hook** | It names the failed check: `settings.json` staged in machine form (register the filter with `scripts/bootstrap` and re-stage), `settings.machine.json` or `private-literals.txt` in the index (untrack it with `git rm --cached -- <path>`; the file stays on disk), a private literal at `file:line` (remove it from that file), or a missing check script. |
| **`npm` / `node` / `kill` refused by the runtime guard** | `protected-runtime.json` is missing or invalid (`~/.config/claude/protected-runtime.json`, or `$CLAUDE_PROTECTED_RUNTIME_FILE`). Init creates it when absent; `scripts/doctor` checks it. |
| **Helper scripts fail to import** | They expect the venv at `<harness-home>/venv`; re-run init (`scripts/bootstrap`), which creates it when it is missing. |
| **A commit/push is being refused** | The git privilege guard (`hooks/pretool-git-privilege-guard.py`) exits 2 for an agent `git commit` or `git push` without a live grant from `/commit` or `/push`. As a human, run the git command from your own shell, or `/allow` the exact command; `/do` does not cover `git commit` or `git push`. |
| **A command is refused and I don't know why** | The hook that refuses it writes its reason to stderr (visible in the Claude Code tool output). Look for `BLOCKED:` or `BLOCKED by` lines — they name the rule or the hook. Check `/tmp/claude-grants/` for any pending structured grants (`/tmp` is the default state directory; `CLAUDE_STATE_DIR` set to an absolute path replaces it). For grant-related refusals, `ls /tmp/claude-push-grant-*.json /tmp/claude-commit-grant-*.json 2>/dev/null` shows any live grant files. |
| **Bootstrap / venv failure** | Verify Python 3 is installed: `python3 --version`. If the venv creation fails, check disk space and that `python3-venv` is installed (`apt install python3-venv` on Debian/Ubuntu). Init uses the first of `python3`, `python3.12`, `python3.11`, `python3.10` that has a lockfile under `requirements/`. Re-run init with `--force` to back up and recreate the venv: `<harness-home>/scripts/bootstrap --force`. |
| **Resolver failure / wrong home detected** | Scripts resolve their own home structurally via `hooks/lib/claude_home.{sh,py}`; hook commands use `CLAUDE_HOME` from the overlay, falling back to `$HOME/.claude`. If either points at the wrong directory, check `env.CLAUDE_HOME` in `settings.machine.json` and run `scripts/doctor` for a preflight diagnostics report. |
