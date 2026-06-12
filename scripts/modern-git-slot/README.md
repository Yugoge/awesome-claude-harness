# Pinned modern-git slot (Option A, M17)

This is the **operator-supplied prerequisite** slot for the git ≥2.46
distribution that gives the overnight reference-transaction keystone its
git-native STRUCTURAL HEAD-switch guarantee. This cycle delivers the **slot
layout + selector wiring + launch self-test + rollback docs** ONLY — it does
**NOT** download or build git (no in-cycle network build; AC-A-prereq).

## Slot location

Default: `<main_root>/.claude/modern-git-slot/`
Override: set `CLAUDE_MODERN_GIT_SLOT=<dir>`.

The repo-tracked copy here (`scripts/modern-git-slot/`) is the template +
documentation. The live slot is created under `.claude/` (git-ignored) by the
operator placing the distribution there.

## Required layout (full distribution, NOT a lone binary)

```
<slot>/bin/git                  # the pinned >=2.46 git binary
<slot>/libexec/git-core/...     # matching helpers (git --exec-path target)
<slot>/manifest.json            # provenance: {version, sha256}
```

`git --exec-path` MUST resolve inside `<slot>/libexec/git-core` so helper
subcommands (`git-checkout`, `git-switch`, …) are the modern ones too
(codex round-2 finding #6 — a lone executable with mismatched system helpers
is rejected by the self-test).

## Provenance manifest (`manifest.json`)

```json
{
  "version": "2.46.0",
  "sha256": "<sha256 of bin/git>",
  "source": "operator-supplied pinned distribution",
  "placed_at": "<ISO-8601>"
}
```

The launch self-test (`scripts/overnight-git-selftest.sh`) verifies
`git --version` ≥ 2.46 AND `git --exec-path` inside the slot AND a functional
keystone-abort test before it lets state record
`guarantee_level=structural_head_switch`.

## REQUIRED git version for the keystone half-a guarantee

The keystone half-a structural HEAD-switch guarantee REQUIRES git **2.54.0**
(installed package `1:2.54.0-0ppa1~ubuntu24.04.1`, supplied from the git-core
PPA at `/etc/apt/sources.list.d/git-core-ubuntu-ppa-noble.sources` →
`https://ppa.launchpadcontent.net/git-core/ppa/ubuntu noble/main`). On git 2.54
the `reference-transaction` hook fires for a main-worktree symref HEAD
branch-switch off master, so the keystone can ABORT it; on git 2.43 that hook
is silent for the symref switch and the keystone gives no structural HEAD-switch
protection.

**Functional check (authoritative):** `scripts/overnight-git-selftest.sh` MUST
report `reference_transaction_selftest_result="structural_head_switch"` (and
`structural_claim_allowed=true`) on the host. That is the single source of truth
for whether half-a is structural — not the version string alone.

**Reversible rollback + its consequence:** downgrade to the pinned
`1:2.43.0-1ubuntu7.3` (still in the apt version table — `apt-cache policy git`
shows both) and remove the `git-core-ubuntu-ppa-noble.sources` PPA. The
CONSEQUENCE of rollback is that half-a DEGRADES from structural to best-effort:
the self-test records `reference_transaction_selftest_result` other than
`structural_head_switch` and `structural_claim_allowed=false`. Isolation,
worktree creation, the bwrap write-half, and the M13 policy-shim / M14a firewall
/ M15 bash-safety defense-in-depth ALL still hold — isolation is NEVER gated on
the git version. "核心加固不得被宿主升级阻断" cuts both ways: the core hardening
must be broken neither by a host upgrade nor by a downgrade.

## How it is used

`scripts/overnight-git/git-selector` (the modern-git PATH selector) is prepended
to the overnight actor's PATH and delegates to `<slot>/bin/git` when the slot is
populated; otherwise it falls through to the system git. The selector is
SEPARATE from the policy shim (`git-policy-shim`) so relaxing policy never drops
the selector.

## Rollback (minimal + reversible — AC-A-prereq)

Removing the slot directory fully reverts the Option-A overlay:

```bash
rm -rf <main_root>/.claude/modern-git-slot
```

After removal the selector falls through to **system git**. On the current host
(system git 2.54, sub-mode A1) the self-test still records
`structural_head_switch` / `structural_claim_allowed=true`, because the keystone
guarantee comes from the host git version, not from this slot overlay. (Only if
the system git is ALSO downgraded below 2.46 does the self-test record
`best_effort_head_switch` / `structural_claim_allowed=false`.) Either way the
compensating layers (M13 policy shim + M14a firewall + M15 bash-safety) carry
the exact-incident block (AC11) unchanged, and the isolation, worktree creation,
and master-branch-ref protection do not depend on the slot.

> **ACCEPTED LIMITATION (2026-06-12) — keystone is disablable via shared `.git`.**
> The "master-branch-ref protection" above and the A1 "covers the branch-switch
> structurally on every path" claim below hold ONLY while the keystone remains
> installed. A linked overnight worktree shares the repo `.git` common-dir; an
> actor that mutates `core.hooksPath` (e.g. `git config --unset core.hooksPath`)
> can DISABLE the keystone and then move master. This is a USER-ACCEPTED residual
> for this cycle and **QA remains FAIL by accepted deviation** — do NOT read the
> word "UNCONDITIONAL"/"every path" as protection against shared-.git mutation.

## Sub-modes (codex round-2 finding #1)

- **A1** (host-wide modern git: PATH `git` AND `/usr/bin/git` AND
  `/usr/lib/git-core/git` all ≥2.46): keystone covers the branch-switch
  structurally on every path; M13/M15 MAY relax to Should-Have. **This is the
  current host** — git 2.54.0 is installed host-wide (the 2.43 → 2.54 PPA
  upgrade was applied), so `/usr/bin/git` is also ≥2.46 and the keystone fires
  for the symref HEAD switch.
- **A2** (PATH-pinned only, an old absolute `/usr/bin/git` < 2.46 still
  reachable): M13/M14a/M15 remain MUST and AC11 must pass. This is the
  post-rollback sub-mode (downgrade git + remove the PPA → `/usr/bin/git`
  returns to 2.43.0).

The host now runs A1 (host-wide 2.54). The compensating M13 policy-shim / M14a
firewall / M15 bash-safety layers are RETAINED as defense-in-depth regardless of
sub-mode; rolling git back to 2.43 returns the host to A2 and is fully
reversible.
