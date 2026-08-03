# Guard demo — block-then-grant-then-complete

A reproducible, in-repo example that demonstrates the harness catching a
dangerous operation with a security guard, and then completing a
properly-authorized, grant-gated fix.

This is the executable WS6 deliverable for **AC-WS6-1**. The substantive
artifact is the script itself — a recorded terminal cast is optional and is
**not** required for the scenario to be valid. *That statement is scoped to
`run-demo.sh`, and remains true of it.* It does **not** extend to the sibling
arc below: `run-hero-demo.sh` exists precisely so that its recording is
load-bearing, because the README hero is generated from it.

## The hero arc — `run-hero-demo.sh`

A second, sibling scenario covering the five beats the README hero shows:

1. an agent attempts `git push`;
2. `hooks/pretool-git-privilege-guard.py` refuses it **before execution**;
3. the terminal shows the rule, the reason and two safe remedies — all of it
   printed by the hook, never by the script;
4. a narrowly-scoped single-use grant permits **exactly one** push, which
   really executes against a hermetic **local bare remote** reached by the
   relative path `../hero-remote.git` inside a throwaway fixture;
5. the real `hooks/posttool-allowlist-consume.py` consumes that grant and the
   identical command is refused again.

Run it through its capture harness — the harness, not the demo, invokes the
hooks and records their own streams, so the demo cannot mediate the evidence:

```sh
python3 scripts/capture-hero-run.py
```

That writes `.github/assets/hero-capture.txt` (a timestamped, byte-exact
capture, captured through a **pipe**, never a pseudo-terminal) plus an evidence
JSON. To rebuild the manifest and the animated SVG from it:

```sh
python3 tools/demo/build-hero-manifest.py .github/assets/hero-capture.txt .github/assets/guard-hero.json
node tools/demo/gen-svg.mjs .github/assets/guard-hero.json .github/assets/guard-hero.svg
```

To prove the committed capture really is the product of a re-runnable run —
regenerate-and-diff, raw-timing agreement, per-event delta agreement, an
adversarial check that the normalizer never rewrites rule / reason / remedy /
consumption text, and the manifest's order-faithful bijection over the capture:

```sh
python3 scripts/verify-hero-provenance.py --tamper
```

**Safety.** The demo reserves the fixed task id `readme-hero-demo-reserved` and
aborts before doing anything if that token collides with `$CLAUDE_TASK_ID` /
`$CLAUDE_SESSION_ID`, or if a grant matching it already exists. It never globs
`/tmp/claude-grants/`, never calls `reap_expired_sentinel_grants()` or
`hooks/stop-cleanup-allowlist.sh`, and never deletes a grant — only the real
consumer does that. Grants belonging to other task ids are verified
byte-identical and mtime-unchanged after the run.

## Run it

```sh
examples/guard-demo/run-demo.sh
```

Re-run it as many times as you like; the result is deterministic. It runs under
any non-root `$HOME` with the author's `/root/.claude` absent — the demo builds
its own ephemeral home and resolves it through the shared harness-home resolver,
so there are no author-absolute paths.

Flags:

| Flag | Effect |
| --- | --- |
| `--keep` | Leave the ephemeral demo home on disk for inspection. |
| `--quiet` | Suppress the narration; the exit code still reflects success. |

Exit codes: `0` = the full sequence behaved as designed; `1` = a step
misbehaved (the narration names which); `2` = setup precondition unmet (could
not locate the live harness from the script's own location, or could not build
the demo home).

## What it shows

The demo runs the **real** PreToolUse enforcer (`hooks/pretool-tool-policy.py`)
and the **real** shared resolver (`hooks/lib/claude_home.sh` /
`hooks/lib/claude_home.py`) against an isolated, freshly-built demo home, then
walks three steps:

1. **STEP 1 — dangerous op BLOCKED.** An agent (role `dev`) attempts to write to
   a protected target. The guard exits `2` (fail-closed) and prints its own
   marker `BLOCKED by tool-policy.v1`. The dangerous write never lands, because
   the guard runs *before* the tool.
2. **STEP 2 — authorized fix ALLOWED.** The same agent performs an in-scope,
   grant-gated fix. The guard exits `0` — the operation is within policy.
3. **STEP 3 — fix COMPLETES.** The authorized write actually lands on disk,
   proving the fix went through after authorization.

## How it stays portable

- The script finds the live harness from **its own location** (two directories
  up), never from a hardcoded path.
- The ephemeral demo home is created under `/tmp` with the basename
  `dot-claude`, which exercises the **structural-sentinel** resolver
  (`settings.json` + `hooks/` + `policies/` + `scripts/` present together) — the
  resolver must *not* key on a directory literally named `.claude`.
- Each guard probe runs in a clean environment (`env -i`), so no author home can
  leak into the decision; the demo's own scoped `policies/tool-policy.v1.json`
  drives the block, making the outcome independent of install location.

## Relationship to the test suite

`tests/generated/dev-20260616-204226/test_AC_WS6_1_ws6dem-blockthengrnt1.py`
runs this script twice and asserts the deterministic block-then-grant-then-
complete behaviour, treating the terminal cast as optional.

<!-- AUTO:readme-stats -->
## Overview
- **Total files**: 0
- **Subdirectories**: 0
- **Naming convention**: lower

---
*Auto-generated by doc-sync hook.*