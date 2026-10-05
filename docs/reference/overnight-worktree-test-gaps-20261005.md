# Overnight 20260809 worktree test landing: diagnosis of 15 failures

**Source**: worktree `overnight-20260809-685c203b`, session `685c203b-2819-47f4-b612-f60f285a1602`, spec `20260808-035658`, tickets `20260809-102007-0/-3/-5/-7`.

**Cycle status**: the source overnight cycle is abandoned. Its own `overnight-summary-2026-08-09.md` records every per-cycle commit failing at exit 127, with only LANE-RS passing out of 11 lanes. The 5 test files below are landed because their tested units are live on master and had zero prior coverage — this is a net coverage addition, not a revival of that cycle's result.

**Test run**: the 5 files, run verbatim (no edits) against master HEAD `12f3f3625`. 32 collected, 17 passed, 15 failed.

| File | Pass | Fail |
|---|---|---|
| `hooks/tests/test_bash_write_targets_policy.py` | 9 | 5 |
| `hooks/tests/test_grep_backtrack_guard.py` | 4 | 0 |
| `hooks/tests/test_runcode_watchdog_aliases.py` | 4 | 3 |
| `hooks/tests/test_tool_policy_contracts.py` | 0 | 3 |
| `tests/test_write_qa_mode.py` | 0 | 4 |

The failures fall into three independent categories. They are kept separate deliberately — collapsing them into "tests are stale" would misrepresent at least one of them.

## 1. paseo/playwright tool-parity gap — likely real defect, hit independently by two files

Two test files with different authors' intent and different test targets each independently measure the same underlying fact: paseo's browser-automation tools are not wired to the same policy/watchdog surface as the live playwright equivalent, even though the paseo tools are in active use.

- **`hooks/tests/test_runcode_watchdog_aliases.py`** (watchdog layer): `test_each_alias_starts_exactly_one_watchdog[mcp__paseo__browser_run_code]` and `test_each_alias_cancels_and_checks_exactly_once[mcp__paseo__browser_run_code]` both fail — the playwright alias starts/cancels exactly one watchdog as expected (`len(stale)==1`, `len(cancelled)==len(markers)==1`); the paseo alias starts/cancels zero (`len(...)==0`). `hooks/pretool-runcode-watchdog.py` / `hooks/posttool-runcode-watchdog.py` do not currently treat `mcp__paseo__browser_run_code` as a watched tool name the way they treat the playwright alias.
- **`hooks/tests/test_tool_policy_contracts.py`** (policy layer): `test_browser_provider_aliases_are_role_equivalent` fails — for every role tested (`user`, `ui-specialist`, `qa`, `pm`), `policy_registry.is_allowed(role, "mcp__paseo__browser_run_code" | "mcp__paseo__browser_navigate", None)` returns deny (`not in allowed_tools`) where the playwright equivalent returns allow.

Two unrelated test files, from two unrelated angles (runtime watchdog lifecycle vs. static role-policy registry), land on the same conclusion. That convergence is why this is flagged as a probable real gap rather than two unrelated stale expectations.

Separately, in the same file: `test_template_and_live_settings_preserve_full_alias_parity` fails on a `settings.json`-vs-rendered-`settings.template.json` content mismatch (differing `env` keys and hook group lists). This is unrelated to the alias-parity logic above — listed here only so it isn't folded into the paseo/playwright finding.

## 2. Tested capability missing from master: `bash_write_targets` resolver functions

`hooks/tests/test_bash_write_targets_policy.py` — 5 of 14 tests fail. Root cause: master's `hooks/lib/bash_write_targets.py` does not resolve a shell variable to its last-assigned value at the point of sink use — `extract_bash_write_paths()` returns the raw token (e.g. `'$OUT'`) instead of the assigned path, for several `OUT=<path>; ...; tee "$OUT"` shapes. The test names its expectation around `_resolve_assignment_at_use` / `_project_assignment_value`-shaped behavior that master does not currently implement. One sub-failure (`test_projection_timeout_fails_closed`) is a narrower API-shape mismatch: the test monkeypatches `targets.subprocess`, but master's module does not expose `subprocess` as a module-level attribute. One more (`test_projected_result_still_traverses_deny_before_allow`) is a downstream consequence of the same unresolved-assignment behavior.

## 3. Interface change: `scripts/write-qa-mode.sh` now requires `CLAUDE_PROJECT_DIR`

`tests/test_write_qa_mode.py` — all 4 tests fail on one root cause: `scripts/write-qa-mode.sh:35` dereferences `$CLAUDE_PROJECT_DIR` and errors immediately when unset (`CLAUDE_PROJECT_DIR: CLAUDE_PROJECT_DIR not set`), rather than self-resolving its root via `hooks/lib/claude_home.sh` the way the test (`test_env_unset_uses_validated_script_root`) assumes a sibling resolver still does. Whether master intentionally dropped that self-resolution path, or the test's expectation is simply stale relative to a since-changed interface, is not determined here — left as an open question for whoever picks this up.

## Disposition

Landed as-is, unmodified (no assertion/skip/xfail/rename changes), in the same commit as this record. Not added to `tests/baselines/default-run-failures.json`: that file's semantics are "accepted known failure," and category 1 above is an open, unaccepted defect — registering it there would misrepresent it as resolved-enough-to-ignore.
