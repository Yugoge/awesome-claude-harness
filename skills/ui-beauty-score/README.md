# ui-beauty-score

Aggregator skill for the ui-specialist subagent. Computes the final 1-10 beauty_score, 7 weighted sub-scores, and a 0-1 consistencyScore from upstream skill findings.

## Purpose

Provide deterministic aggregation arithmetic so each ui-specialist run yields a stable, comparable score across pages and over time, and so the orchestrator can rank findings, gate releases, or trend regressions.

## When this skill runs

Called once per ui-specialist invocation, **after** every per-phase ui-* skill (axe-injector, apca-contrast, token-conformance, state-matrix, contextual-heuristics, anti-pattern-catalog) has produced its findings. It is the **last** skill before report write.

## Inputs

- `aesthetic_findings[]` — from ui-anti-pattern-catalog (and any contextual aesthetic rules)
- `automated_findings[]` — from ui-axe-injector + ui-apca-contrast + ui-token-conformance + ui-state-matrix + ui-contextual-heuristics
- `alignment_measurements[]` — optional grid/baseline/spacing measurements harvested in Phase 5
- `scope` — `page | flow | session`

## Outputs

- `beauty_score` (1.0-10.0, 1 decimal)
- `sub_scores{}` (7 weighted categories)
- `consistencyScore` (0.0-1.0, 2 decimals; `null` if token capability unavailable)
- `rationale`, `calculation_basis`, `unknowns[]`, `needs_review[]`

## Why a separate skill

Keeping aggregation isolated from the per-phase capture skills:

- Lets the calculation be unit-tested independently of browser state
- Prevents per-phase skills from holding state across phases
- Makes weight changes (spec 5.15.7) a single-file edit

## Failure mode

This skill is pure arithmetic over JSON — it cannot fail in the operational sense. Missing inputs surface as `unknowns[]` entries and 9.0-default sub-scores. `beauty_score=null` is only ever emitted when ui-specialist deliberately bypasses the skill (e.g., navigation failed, zero findings of any channel).

## See also

- `SKILL.md` — operational contract, JSON schemas, calculation rules
- `INDEX.md` — relationship to other ui-* skills and ui-shared/ artifacts
- `<harness-home>/skills/ui-shared/report-schema.json` — the schema this skill's output feeds into
- `<harness-home>/docs/dev/specs/spec-20260426-080555.md` §5.15.7 — weight rationale