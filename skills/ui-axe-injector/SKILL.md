---
name: ui-axe-injector
description: Inject axe-core 4.10.0 into a Playwright page and run the WCAG 2.1 a/aa rule set; emit a single deterministic findings list against rule-map.json. Use during ui-specialist Phase 6 (Accessibility) before ui-contextual-heuristics.
---

# ui-axe-injector

Layer: **Deterministic (L1)**.
Output channel: `automated_findings[]` with `rule_id="axe.<rule-name>"` per spec 5.5 + 5.15.1.

## Trigger Conditions

Invoke this skill when:

- ui-specialist enters **Phase 6 (Accessibility Audit)** for any page that has been navigated successfully via Playwright.
- A `ui-contextual-heuristics` invocation is queued for the same page — this skill MUST run first so contextual_findings can dedup against axe.* rule_ids.

Do NOT invoke when:

- The page has not loaded (no `browser_snapshot` available yet).
- The subagent has already received `infra.axe-injection-failed` for this page in this session — record `unknowns[]` once and move on.

## Inputs

```
{
  "page_url": "string (URL of currently-loaded Playwright page)",
  "viewport": "mobile|desktop (already set by Phase 3)",
  "rules_subset": "optional: array of axe rule_ids to run; defaults to all WCAG 2.1 a + aa",
  "color_scheme": "light|dark (optional; if dark, caller has already invoked page.emulateMedia({colorScheme:'dark'}))"
}
```

## Outputs

A single ```json fenced block with this shape:

```
{
  "skill": "ui-axe-injector",
  "page_url": "<url>",
  "viewport": "mobile|desktop",
  "color_scheme": "light|dark",
  "injection_status": "vendored|cdn|soft-fail",
  "axe_version": "4.10.0",
  "rules_executed": <integer>,
  "violations_count_by_impact": { "minor": <n>, "moderate": <n>, "serious": <n>, "critical": <n> },
  "automated_findings": [
    {
      "rule_id": "axe.<rule-name>",
      "description": "<axe rule help text>",
      "location": "<page_url> + CSS selector",
      "severity": "critical|major|minor|cosmetic",
      "viewport": "mobile|desktop|both",
      "color_scheme": "light|dark",
      "evidence_mode": "deterministic",
      "axe_impact": "minor|moderate|serious|critical",
      "evidence": "<axe target selector>",
      "browser_verified": true,
      "false_positive_risk": "low"
    }
  ],
  "unknowns": [],
  "needs_review": []
}
```

axe impact → severity mapping:
- `critical` → `critical`
- `serious` → `major`
- `moderate` → `minor`
- `minor` → `cosmetic`

## Fallback Strategy (3-tier per spec 5.17)

**Tier 1 — Vendored (PREFERRED)**:
1. Read `~/.claude/skills/ui-axe-injector/vendor/axe.min.js` (axe-core 4.10.0).
2. Inject into the page via `browser_evaluate` with the file contents wrapped as an IIFE.
3. Call `axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } })`.
4. Set `injection_status="vendored"`.

**Tier 2 — CDN fallback**:
1. If vendored file is missing/unreadable, fetch `https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.0/axe.min.js`.
2. If that also fails, try `https://cdn.jsdelivr.net/npm/axe-core@4.10/axe.min.js`.
3. Inject + run as in Tier 1.
4. Set `injection_status="cdn"`.

**Tier 3 — Soft-fail**:
1. If both Tier 1 and Tier 2 fail, do NOT abort the subagent.
2. Emit a single entry to `unknowns[]`: `{ "thing_not_tested": "axe-core a11y rules on <page_url>", "reason": "all 3 fallback tiers failed", "rule_id": "infra.axe-injection-failed" }`.
3. Set `injection_status="soft-fail"` and `automated_findings=[]`.

## Update Cadence

axe-core is bumped **monthly via manual operator** per spec 5.1 binding decision #5. Operator runs the bump script under `~/.claude/scripts/axe-bump.sh` (future), which downloads the new version, diffs the rule list against `rule-map.json`, and surfaces additions/removals for human review. **No automated CI bump. No auto-update hook.**

## Example Invocation

ui-specialist Phase 6 prompt fragment: *"Use the ui-axe-injector skill on the current page (desktop viewport, light scheme) before running ui-contextual-heuristics."*

---

Your final message MUST be a single ```json fenced block, nothing else
