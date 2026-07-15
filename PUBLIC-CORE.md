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

## 2. Reference example — `settings.template.json` (public) vs `settings.json` (private)

The cleanest illustration of the carve already exists in the tree: the portable seed
`settings.template.json` is `public-core`; the tracked personal `settings.json`
(personal permission allow/deny/ask entries + absolute `/root` paths) is `private-lab`
and a live boundary violation slated for roadmap phase **P3** (generate-then-untrack).

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

**Deliberately-literal exception (NOT a leak):** the local daemon **unit names**
(`happy-daemon` + targets `dev|jade|qijie`) are intentionally *non*-env-overridable —
"a guard you can disable via env var is not a guard" (see the Layer-1 comment in
`hooks/pretool-bash-safety.sh`). They are documented private-lab coupling retained inside
a `public-core` file, so `check-public-core.sh` does **not** scan for them.

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
| `settings.template.json` | `public-core` | Portable, shippable config seed (the public counterpart of `settings.json`). |
| `.github/` | `shared/infra` | CI workflow (`baseline.yml`), community-health files, demo hero assets — build/CI/meta. |
| `.gitignore` | `shared/infra` | Repo meta; encodes the personal/public boundary at the ignore layer. |
| `.claude/` | `shared/infra` | Repo-identity sentinel (`.awesome-claude-harness`) that flags this repo to session hooks. |
| `INDEX.md` | `shared/infra` | Auto-generated navigation index (do-not-hand-edit meta). |
| `pytest.ini` | `shared/infra` | Test-runner configuration — build/CI. |
| `requirements.txt` | `shared/infra` | Python dependency manifest for the harness venv — build/infra. |
| `VERSION` | `shared/infra` | Release version marker — release meta. |
| `tests/` | `shared/infra` | Test net (incl. generated AC skeletons + fixture strings) that supports the core; not itself the shippable harness. |
| `PUBLIC-CORE.md` | `shared/infra` | This boundary manifest — governance/meta (self-classified for forward completeness once tracked). |
| `settings.json` | `private-lab` | Personal config, tracked: personal permission allow/deny/ask entries + absolute `/root` paths (roadmap §4.3 → P3). |
| `NESTED-REPO.md` | `private-lab` | Documents the maintainer's exact `/root/.claude`→tmpfs symlink topology, `git@github.com:Yugoge` remote, `/root/.claude.bak` mirror, `/root/sync-backup.sh` cron. |
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
4. **Advisory** — counts the deferred `/dev/shm/dev-workspace/dot-claude` leaks
   (roadmap P1/P2) without failing.

Run it in CI alongside `scripts/verify-claims.sh`.
