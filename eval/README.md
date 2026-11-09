# /dev-overnight Eval Harness

Regression-test harness for the `/dev-overnight` command. Each case is a small,
self-contained spec that the harness will eventually feed to `/dev-overnight`
and compare the cycle output against an expected.json fixture.

## Wave-1 Scope

In this Wave, `runner.py` only validates the structural integrity of every
case directory: it checks that `spec.md` and `expected.json` exist, that the
JSON is well-formed, and that at least one of the documented core fields is
present. It does NOT yet drive an actual `/dev-overnight` invocation. Wave 4
populates the 100+ regression cases and a later wave will wire the runner up
to actual cycle execution + diff comparison.

## Directory Layout

```
/root/.claude/eval/
  runner.py                    # CLI harness (this directory)
  README.md                    # This file
  categories/                  # One subdir per category (placeholders)
    bug-fix/.gitkeep
    ui-target/.gitkeep
    ui-audit/.gitkeep
    backend-api/.gitkeep
    infra-hook/.gitkeep
    docs-research/.gitkeep
  cases/                       # All case dirs live here, FLAT
    bug-fix-smoke-01/
      spec.md
      expected.json
    ui-target-001/
      spec.md
      expected.json
    ...
```

## Categories (6 total)

- `bug-fix` — small, surgical bug fixes in existing code.
- `ui-target` — targeted UI work against a specific route+component (uses
  `ui_target` YAML frontmatter in spec.md).
- `ui-audit` — full-app or multi-route UI audit scenarios.
- `backend-api` — server-side API endpoint or middleware work.
- `infra-hook` — Claude Code hook authoring (PreToolUse / PostToolUse / Stop).
- `docs-research` — documentation writing or deep-research scenarios.

## Case Naming

- Smoke cases: `<category>-smoke-NN` (e.g., `bug-fix-smoke-01`).
- Regression cases: `<category>-NNN` (e.g., `ui-target-007`).

The case id MUST start with one of the six known category prefixes above; the
runner uses this prefix to map each case to a category.

## How to Add a New Case

1. Pick a category and an unused 3-digit case number.
2. Create the case dir: `/root/.claude/eval/cases/<category>-NNN/`.
3. Write `spec.md` (>= 10 lines): a concise, realistic prompt the way a user
   would phrase the request to `/dev-overnight`. For UI cases, include the
   `ui_target:` / `viewport_targets:` / `design_inputs:` YAML frontmatter at
   the top of the file (see `ui-target-smoke-01` for an example).
4. Write `expected.json`: the harness contract for that case. At least one of
   the required core fields below MUST be present.
5. Run the harness against your new case:
   `python3 /root/.claude/eval/runner.py --case <category>-NNN`

## expected.json Schema

Top-level JSON object. At least one of these **core** keys must be present:

- `pipelines_count` (int) — expected number of pipelines (`/dev` invocations)
  the cycle should produce for this case.
- `tier_distribution` (object) — expected tier histogram, e.g.
  `{"tier1": 1, "tier2": 0, "tier3": 0}`.
- `verdict_pattern` (string) — regex-like pattern the QA verdict must match
  (e.g., `"pass|warning"`).
- `evidence_kind_required` (array of strings) — evidence kinds the QA report
  MUST include (e.g., `["test_output", "screenshot_desktop"]`).
- `ui_evidence_required` (bool) — whether UI evidence (screenshots, traces)
  is mandatory.

Optional auxiliary keys (forward-compatible with Wave-4 cases):

- `pages_visited_minimum` (int) — minimum unique pages the audit must visit.
- `screenshots_minimum` (int) — minimum screenshot count.
- `both_viewports_required` (bool) — desktop + mobile required.
- `ui_pipeline` (bool) — true if the case must trigger the UI specialist.
- `dev_only_modify` (bool) — restrict modifications to dev-only paths.
- `primary_artifact` (string) — primary deliverable path the dev report must
  reference.

## Running the Harness

- Smoke (one case per category): `python3 runner.py --smoke`
- Extended (first 30 cases): `python3 runner.py --extended`
- Full regression (all cases): `python3 runner.py --regression`
- Single case: `python3 runner.py --case bug-fix-smoke-01`
- Single category: `python3 runner.py --category ui-target`
- JSON output (any of the above): add `--json`

## Exit Codes

- `0` — every selected case validated cleanly.
- `1` — at least one selected case failed validation.
- `2` — no cases matched the selected scope (typo, empty subset, etc.).

## Future Enhancements (post-Wave-1)

The runner will be extended in a later wave to actually drive
`/dev-overnight` against each case spec, capture the cycle output, and diff
the artifacts against `expected.json`. The CLI surface above is forward-
compatible with that change — the same flags will then trigger end-to-end
case execution rather than schema-only validation.