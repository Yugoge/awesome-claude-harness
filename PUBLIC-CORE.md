<!-- DO NOT hand-maintain the completeness of this file by memory: run `bash scripts/check-public-core.sh`. -->

# PUBLIC-CORE.md — public/private boundary manifest

> **Status**: boundary **definition + enforcement** only. This cycle does **not**
> move, rename, or delete any file. It draws the line and makes the line
> machine-checkable via [`scripts/check-public-core.sh`](scripts/check-public-core.sh).
>
> **Companion (planning, do not duplicate)**:
> [`docs/reference/roadmap-decomposition-productization.md`](docs/reference/roadmap-decomposition-productization.md)
> §4 (public-core surface, personal layer, blurred-boundary evidence, phased plan
> P1–P4). This manifest is the *classification ledger*; the roadmap is the *plan*.

---

## 1. Carve principle

Every tracked top-level path is exactly one of three classes. The test is **what the
file actually is**, not where it lives.

| Class | Question that puts a path here | A public consumer would… |
|---|---|---|
| `public-core` | Is this the general-purpose harness — reusable hooks, commands, agents, skills, scripts, schemas, policies, templates, tools, and the docs/licence that describe them? | adopt it as-is (overriding a few env knobs). |
| `private-lab` | Does it hardcode an author-environment identifier — personal container/daemon names, machine paths (`/root/…`, the tmpfs workspace), the maintainer's git remote / mirror / cron, or author-only workflow automation? | strip or replace it; it is meaningless off the author's box. |
| `shared/infra` | Is it build / CI / test / release / repo-meta that supports *both* sides but is not itself the shippable harness? | keep it, but it is plumbing, not the product. |

**Decision rule (tie-breaks):** a path is `public-core` only if a stranger could run it
without editing author-specific literals. If it *contains* author literals but they are
**env-overridable defaults** (see §3), it stays `public-core` — the override is the
escape hatch. If the author literal is **unconditional** (the file only makes sense on
the author's machine), it is `private-lab`. "Release-clean" is a higher bar than
"public-core": several `public-core` files still carry deferred `/root` leaks (roadmap
§4.3, phases P1–P2) — candidate, not yet clean.

---

## 2. Settings — one tracked clean source, a machine overlay, a git filter

The carve runs *through* the settings file rather than between two files. The tracked
`settings.json` is the **clean public form** and the only hand-maintained settings source
(the former `settings.template.json` seed is retired). It carries no machine value — every
hook command reaches its file through `${CLAUDE_HOME:-$HOME/.claude}`, and there is no
install path, no `CLAUDE_HOME`, no personal tool path and no CLI-owned key (`model`,
`theme`, `tui`, …) — so it is `public-core`.

The machine values live in `settings.machine.json` at the harness home: untracked and
gitignored, written only when absent: by init (`scripts/bootstrap`), or once by the landing
(`scripts/install/land`, run from `hooks/auto-commit.sh`) on a home upgraded from code before
the filter; never by agents. `settings.machine.example.json` (tracked, `public-core`) documents every key.
Optional modules (today only `paseo`) are fragments embedded in
`scripts/install/render-settings`, switched on by the overlay's `modules` key.

`.gitattributes` (tracked, `shared/infra`) declares `/settings.json filter=claude-settings`;
init registers the filter's clean and smudge commands (`scripts/install/render-settings`,
`required = true`) in the clone's local git config. Smudge and render write the machine form
(clean form + enabled modules + overlay) into the working file and record what they applied in
`<git dir>/claude-settings.applied` (never tracked); clean strips everything the modules,
the overlay and that record added, plus the CLI-owned keys, and refuses input it cannot
parse, so git only ever stores the clean form. A commit that would store `settings.json` in
machine form, or one made while the overlay or the private-literal list is in the index, is
refused by the pre-commit hook init installs (`render-settings check --staged`); CI runs the same
check without an overlay. `hooks/pretool-bash-safety.sh` denies agents the forms of skipping
that hook it can read in a command (`--no-verify`, `-n`, hook-path and include overrides and
`-c` aliases on `git commit`; `git config` writes to `core.hooksPath`, `alias.*`,
`filter.claude-settings.*`, `include.path` and `includeIf.<condition>.path` that can reach the
harness, such as a global, system or named-file write, a nested call or a write in the harness
home's own repository, while a plain local write in another repository is allowed); README.md,
"Commit protection", names what it denies and what it does not cover.

Personal literals have their own local guard: the private-literal list `private-literals.txt`
at the harness home (untracked, gitignored; init creates it empty and the human fills it, or
the landing seeds it once on an upgraded home while it is absent or empty, never a list that has lines). `scripts/check-public-core.sh` fails on any of its literals in a tracked file, and the
pre-commit hook runs that rule (`--private-literals`) over the staged content. Without the
list the rule is skipped.

`settings.json` is never untracked: the filter, not an ignore rule, keeps machine values out
of git. The earlier generate-then-untrack plan (roadmap phase **P3**) is withdrawn.

---

## 3. Reference examples — private-lab residue already parameterized (env-override knobs)

`hooks/pretool-bash-safety.sh` is the canonical case of author-environment residue that
was **parameterized last cycle** so the file can stay `public-core`: each author literal
is now the *default* of a `CLAUDE_*` env var, so a public consumer overrides it without
editing the hook. These defaults are the residue markers the checker treats as
**allowed only in env-default (`:-`) or comment position** — a bare, un-parameterized
reuse is a leak.

| Knob (env var) | Author default (residue) | Public consumer overrides via |
|---|---|---|
| dev container name (`CLAUDE_DEV_CONTAINERS`) | `happy-web-dev` | export `CLAUDE_DEV_CONTAINERS=…` |
| dev systemd units (`CLAUDE_DEV_SYSTEMD`) | *(empty)* | export `CLAUDE_DEV_SYSTEMD=…` |
| daemon-restart grant helper (`CLAUDE_DAEMON_RESTART_GRANT_HELPER`) | `/root/bin/claude-allow-restart` | export `CLAUDE_DAEMON_RESTART_GRANT_HELPER=…` |
| grant sentinel dir (`CLAUDE_DAEMON_RESTART_GRANT_DIR`) | `$TMPDIR` | export `CLAUDE_DAEMON_RESTART_GRANT_DIR=…` |
| protected daemon prefix (`CLAUDE_PROTECTED_DAEMON_PREFIX`) | `happy-daemon` | export `CLAUDE_PROTECTED_DAEMON_PREFIX=…` |
| protected daemon targets (`CLAUDE_PROTECTED_DAEMON_TARGETS`) | `dev\|jade\|qijie` | export `CLAUDE_PROTECTED_DAEMON_TARGETS=…` |

**Protected daemon identity — now parameterized (was a deliberately-literal exception):**
the local daemon **unit prefix** (`happy-daemon`) and its per-instance **targets**
(`dev|jade|qijie`) used to be hardcoded in the daemon-restart-prohibition (Layer 1.A) and
its wrapper/http/sentinel siblings, and were exempt from the residue scan. They are now the
DEFAULTS of `CLAUDE_PROTECTED_DAEMON_PREFIX` / `CLAUDE_PROTECTED_DAEMON_TARGETS` (rows
above), so a public consumer points the guard at their own daemon without editing the hook;
with both unset, Layer 1.A behaves byte-for-byte as before. `check-public-core.sh` therefore
treats `happy-daemon` as a **parameterized** residue marker (allowed only in `:-` default or
comment position, exactly like `happy-web-dev`; a bare un-parameterized reuse in shippable
code is flagged) rather than an un-scanned literal. Test fixtures that name the guarded unit
(e.g. `hooks/tests/*`) are test data, not residue, so the param scan skips test trees.
**Grant-channel caveat:** the target suffix also keys the external grant helper's sentinel
protocol (`claude-allow-daemon-restart-<target>.flag`), so a consumer that retargets the
prefix must also configure a matching grant helper (`CLAUDE_DAEMON_RESTART_GRANT_HELPER`) or
the gate is protective but un-grantable.

**Hard residue markers (must never appear in `public-core`, in any form):** the
maintainer's git remote `git@github.com:Yugoge/…`, the rsync mirror `/root/.claude.bak`,
and the sync cron `/root/sync-backup.sh` — all confined to `NESTED-REPO.md`
(`private-lab`). If any surfaces in a `public-core` file, that is a hard leak.

**Deferred, NOT gated this cycle:** the broad `/root/…` and tmpfs-workspace
(`/dev/shm/dev-workspace/dot-claude`) path leaks that still pepper `public-core` prompts
and scripts (roadmap §4.3 → phases **P1/P2**). The checker reports these as an
**advisory count only** — it does not fail on them yet, because cleaning them is a
separate, planned phase.

---

## 4. Classification ledger

Machine-readable region below (sentinel-delimited). `check-public-core.sh` parses it,
verifies **every** git-tracked top-level path appears here, and scans the `public-core`
set for the residue markers of §3. Path = first back-ticked token; class = second.

<!-- BEGIN:public-core-manifest -->
| Path | Class | Rationale (what the file actually is) |
|---|---|---|
| `agents/` | `public-core` | Reusable subagent role definitions (ba, dev, qa, cleaner, …) any harness user adopts. |
| `commands/` | `public-core` | Slash-command definitions — the harness's user-facing command surface. |
| `hooks/` | `public-core` | Hook kernel: PreToolUse/PostToolUse/Stop guards + `runtime_guard` lib (the security core; residue is env-parameterized per §3). |
| `scripts/` | `public-core` | General-purpose harness automation (bootstrap, doctor, verify-claims, scoring, this checker). |
| `schemas/` | `public-core` | JSON schemas validating artifacts/config at runtime. |
| `policies/` | `public-core` | Declarative policy definitions consumed by the hooks. |
| `templates/` | `public-core` | Artifact / document templates the pipeline instantiates. |
| `tools/` | `public-core` | Demo + provenance-audit tooling (`audit.mjs`, hero generators). |
| `skills/` | `public-core` | Skill definitions (ui-*, codex, deep-research, dataviz, …). |
| `examples/` | `public-core` | Worked `guard-demo` example a new adopter can run. |
| `docs/` | `public-core` | Reference documentation + threat model (`docs/reference/`, `docs/THREAT-MODEL.md`). |
| `README.md` | `public-core` | Project front page. |
| `ARCHITECTURE.md` | `public-core` | Architecture reference. |
| `CHANGELOG.md` | `public-core` | Release history. |
| `CLAUDE.md` | `public-core` | Harness operating manual — candidate public-core per roadmap §4.1. |
| `LICENSE` | `public-core` | MIT licence (harness's own code). |
| `NOTICE` | `public-core` | Attribution / licence notice. |
| `settings.json` | `public-core` | The one hand-maintained settings source, tracked in its clean public form: hooks reached through `${CLAUDE_HOME:-$HOME/.claude}`, no install path, CLI-owned key or personal entry. Machine values live in the untracked overlay `settings.machine.json`; the `claude-settings` filter keeps them out of git (§2). |
| `settings.machine.example.json` | `public-core` | Documented example of the untracked machine overlay: every overlay key, the `paseo` module, the private-literal list path. Demo values only. |
| `.github/` | `shared/infra` | CI workflow (`baseline.yml`), community-health files, demo hero assets — build/CI/meta. |
| `.gitignore` | `shared/infra` | Repo meta; encodes the personal/public boundary at the ignore layer (ignores the overlay and the private-literal list). |
| `.gitattributes` | `shared/infra` | Repo meta: declares the `claude-settings` clean/smudge filter for `/settings.json`, registered locally by init (§2). Only meaningful inside a git checkout. |
| `.claude/` | `shared/infra` | Repo-identity sentinel (`.awesome-claude-harness`) that flags this repo to session hooks. |
| `INDEX.md` | `shared/infra` | Auto-generated navigation index (do-not-hand-edit meta). |
| `pytest.ini` | `shared/infra` | Test-runner configuration — build/CI. |
| `conftest.py` | `shared/infra` | Pytest collection config — the `generated`-marker gate for tests/generated; build/CI. |
| `requirements.txt` | `shared/infra` | Python dependency manifest for the harness venv — build/infra. Human-authored ABSTRACT spec (compatible ranges); the concrete resolutions live in `requirements/`. |
| `requirements/` | `shared/infra` | Per-Python-version hash-pinned lockfiles (`py310/py311/py312.txt`) that every install call site uses with `pip install --require-hashes` — build/infra, and shipped, since the harness cannot install without them. |
| `VERSION` | `shared/infra` | Release version marker — release meta. |
| `tests/` | `shared/infra` | Test net (incl. generated AC skeletons + fixture strings) that supports the core; not itself the shippable harness. |
| `PUBLIC-CORE.md` | `shared/infra` | This boundary manifest — governance/meta (self-classified for forward completeness once tracked). |
| `release-membership.v1.json` | `shared/infra` | Shipping ledger: the EXPLICIT path set a release archive contains, plus per-path rationale. Governance/meta, beside this boundary ledger; consumed by the release workflow and by `scripts/verify-release-manifest.sh`. |
| `NESTED-REPO.md` | `private-lab` | Documents the maintainer's private machine topology (the harness symlinked into tmpfs, the git remote, a backup mirror and a sync cron). |
| `push.sh` | `private-lab` | Maintainer pre-push wrapper: `/root/.claude/push.sh` invocation, author git-workflow automation (identity now env-parameterized, purpose still maintainer-specific). |
<!-- END:public-core-manifest -->

---

## 5. Enforcement

`bash scripts/check-public-core.sh` (exit 0 = clean):

1. **Completeness** — recomputes the top-level tracked path set from `git ls-files`
   and fails loudly listing any path missing from the ledger above (catches a new file
   silently escaping classification).
2. **Class validity** — every ledger class must be one of the three labels.
3. **Residue scan** — expands the `public-core` set to files and flags the §3 markers:
   hard markers on any occurrence; parameterized markers only when used
   un-parameterized (not an env `:-` default, not a comment).
4. **Private literals** — fails on each literal of the local, untracked
   `private-literals.txt` (§2) found in a tracked file, reporting `file:line` and the
   literal's line number in the list, never the literal itself; prints `SKIP` when the list
   is absent or empty. `--private-literals` runs only this rule, over the index (what would
   be committed) — the pre-commit hook's mode. Archive mode (`--scan-root`) applies it to
   the archive files when the list exists.
5. **Author-home residue** — every author home-directory path (the root user's home, a
   Linux user home, a macOS user home) in the `public-core` set must match an entry of
   `policies/public-core-residue-allowlist.v1.json` whose class the source structure
   supports; an operational code literal is never allowlistable.

Run it in CI alongside `scripts/verify-claims.sh`.
