---
name: ui-anti-pattern-catalog
description: Apply the 58-rule anti-pattern catalog (10 Color + 5 Motion + 5 Typography + 5 Spacing + 2 Glass + 5 Heuristic + 4 UX-Writing + 5 Form + 4 Interactive + 5 Nielsen + 8 AI-slop) against a Playwright page. Outputs aesthetic_findings[] with category=hard_defect|taste_heuristic, with the SCHEMA-ENFORCED severity hard-cap on taste_heuristic at minor + advisory:true. Use during ui-specialist Phases 4.5/5/6.5.
---

# ui-anti-pattern-catalog

Layer: **Aesthetic (L3)**.
Output channel: `aesthetic_findings[]` with `rule_id="aesthetic.<rule-id>"`.
Source data: `~/.claude/skills/ui-shared/anti-pattern-catalog.yml` (read at runtime; never inlined at build time).

## Trigger Conditions

Invoke this skill when:

- ui-specialist enters **Phase 4.5 (Nielsen)** — request `category_filter: hard_defect` + `dimension_filter: heuristic`.
- ui-specialist enters **Phase 5 (Visual Design Quality)** — request all C/M/T/S/G/H/AI rules; this is the largest invocation.
- ui-specialist enters **Phase 6.5 (UX Writing)** — request W rules with `category_filter: taste_heuristic`.

## Inputs

```
{
  "page_url": "string",
  "viewport": "mobile|desktop",
  "color_scheme": "light|dark",
  "category_filter": "all|hard_defect|taste_heuristic (default all)",
  "dimension_filter": "all|<dimension list> (default all)",
  "rule_id_filter": "optional: array of explicit rule IDs to evaluate (e.g., ['C7','AI1'])"
}
```

## Outputs

A single ```json fenced block:

```
{
  "skill": "ui-anti-pattern-catalog",
  "page_url": "<url>",
  "viewport": "mobile|desktop",
  "color_scheme": "light|dark",
  "rules_evaluated": <integer>,
  "rules_matched": <integer>,
  "aesthetic_findings": [
    {
      "rule_id": "aesthetic.<id>",
      "description": "<rule's detection_pseudocode triggered on this evidence>",
      "location": "<page_url> + selector",
      "severity": "minor|major|cosmetic (NEVER critical from this skill)",
      "viewport": "mobile|desktop|both",
      "color_scheme": "light|dark",
      "evidence_mode": "aesthetic",
      "category": "hard_defect | taste_heuristic",
      "severity_capped_at": "minor|major (must equal yaml severity_cap)",
      "advisory": <boolean>,
      "evidence": "<screenshot filename or computed-style snapshot>",
      "false_positive_risk": "low|medium|medium-high|high",
      "browser_verified": true
    }
  ],
  "needs_review": [],
  "unknowns": []
}
```

## Severity Hard-Cap (FIRST DEFENSE per spec 5.11 #6 + 5.15.6)

For every finding emitted:

1. Look up the rule in `anti-pattern-catalog.yml`.
2. Read its `category` field.
3. **If `category == "taste_heuristic"`**: the emitted finding MUST have `severity_capped_at: "minor"` AND `advisory: true` AND `severity: "minor"`. Any attempt to emit a higher severity for a taste_heuristic rule MUST be downgraded by this skill BEFORE returning. This is the SKILL-LEVEL half of the double defense.
4. **If `category == "hard_defect"`**: read `severity_cap` from the YAML and clamp the emitted `severity` to that ceiling.
5. The aggregator (subagent ui-specialist.md) re-applies the same cap before writing the report — that is the SECOND defense.

This skill MUST refuse to emit any taste_heuristic finding with severity above minor. If the LLM is tempted to "elevate" a taste finding because it is egregious, it MUST instead write to `needs_review[]` with the question "Is this rule miscategorized?" — never bypass the cap.

## AI-Slop Rules (AI1-AI8)

The 8 AI-slop rules (AI1 = purple/violet, AI2 = glass-overuse, AI3 = emoji-icons, AI4 = 3-stat-card cliché, AI5 = blob-bg, AI6 = AI hero copy, AI7 = neon glow, AI8 = shadcn defaults) are ALL `category: taste_heuristic`, `severity_cap: minor`, `advisory_flag: true`. They flag designs that look LLM-generated; they are NEVER blocking on their own. The cap protects projects that legitimately use purple, glass, or shadcn from auto-blocking findings.

## Catalog Loading (runtime, per spec 5.1 #3)

This skill MUST read `anti-pattern-catalog.yml` at invocation time (PyYAML or equivalent JSON-tolerant YAML parser). It MUST NOT cache parsed rules across subagent invocations and MUST NOT have rules pre-baked into the skill prompt. Build-time inlining is explicitly forbidden by spec 5.22.3 row 4.

## Fallback Strategy

Single-tier: if `anti-pattern-catalog.yml` cannot be loaded (corrupted YAML, file missing), emit ONE entry to `unknowns[]`: `{ "thing_not_tested": "anti-pattern-catalog rules", "reason": "catalog file unreadable: <error>" }`. Do not invent rules from training data.

## Example Invocation

ui-specialist Phase 5 prompt fragment: *"Use the ui-anti-pattern-catalog skill on the current page (light + dark color schemes); category_filter=all."*

---

Your final message MUST be a single ```json fenced block, nothing else
