# Install compatibility matrix

**This file is the single source of truth for install support status.** The
installer and its preflight (`scripts/install/preflight`) *parse this file* and print the
row for the detected host. They do not carry a hardcoded answer — change a row here and
the emitted status line changes with it.

Two axes are tracked, because "does it work?" has two independent answers: the operating
system, and the Claude Code build the guarantee was verified against.

---

## Axis 1 — operating system

Machine-readable table. The `uname` column is matched against `uname -s` on the host.
`status` is one of `supported` / `unsupported` / `untested`.

<!-- os-matrix:begin -->

| OS | uname | status | ci_coverage | notes |
|---|---|---|---|---|
| Linux (glibc, GNU userland) | Linux | supported | yes — `.github/workflows/baseline.yml` runs on `ubuntu-latest` across Python 3.10/3.11/3.12 | The declared, tested platform. |
| macOS | Darwin | unsupported | none | No confirmed support and no CI coverage. `.github/workflows/baseline.yml:18-20` states "macOS/Windows are not part of the supported matrix" and pins `runs-on: ubuntu-latest`. Shell hooks and scripts additionally assume GNU userland flags, which BSD/macOS userland does not provide. Nobody has run the suite on macOS. Treat installation there as unverified. |
| Windows | Windows_NT | unsupported | none | Not in scope. Not asked for, not tested, not claimed. |

<!-- os-matrix:end -->

### Why macOS says "unsupported" and not "probably fine"

Because the honest answer is that **there is no confirmed macOS support and no CI
coverage** — the CI matrix is Linux-only by explicit configuration, not by oversight.
Making it work is a separate portability project (rewriting GNU-flag-dependent hooks and
scripts for BSD userland). This row will change when that work lands *and* CI proves it,
not before.

---

## Axis 2 — Claude Code build

The harness's guarantees are enforced by Claude Code's hook lifecycle. A build that
dispatches different events, or ignores exit code 2, silently voids them. This axis
records **which build a support claim was actually verified against**; every other build
is unverified.

This lane (the installer) *publishes* this data. Binding runtime behavior to a specific
build/settings hash — refusing to activate protected workflows when the live host fails a
capability handshake — is the capability-gate work, not the installer's.

<!-- build-matrix:begin -->

| build | status | verified_by | notes |
|---|---|---|---|
| (none recorded) | unverified | — | No Claude Code build has a recorded, reproduced capability-handshake pass in this repository yet. Until a build appears here with a verification reference, the installer must not claim the enforcement guarantee holds on any build. |

<!-- build-matrix:end -->

### How a build gets added

A row is added only when a full capability handshake has been run on that build and the
result recorded — never from "it seemed to work". Until then the installer reports the
host as unverified and refuses to imply protection it has not measured.

---

## What the installer does with this file

1. Detects the host with `uname -s`.
2. Finds the Axis-1 row whose `uname` cell matches (falling back to a loud "no row for
   this OS" line rather than silence).
3. Prints `status` + `ci_coverage` + `notes` as its support line.
4. Refuses to print "works" for any row whose status is not `supported`.

If this file is missing, the preflight fails rather than guessing.
