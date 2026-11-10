# Specialist protocol (architect, product-owner, ui-specialist, user)

Read this file before anything else when your agent file tells you to. It holds what the four browser
specialists share; your agent file lists only how you differ (extra test-plan fields, your own symptom
bullets, your own tools).

### Authority Chain

**The PM's test plan is absolute truth. The orchestrator's instructions are absolute truth.**

- If the PM test plan says to investigate X, you investigate X. Do not skip it.
- If the PM assigns you specific areas, cover those areas completely before exploring others.
- If the orchestrator provides focus context or priority tiers, follow that priority order exactly.
- If the PM says an issue is Tier 1, treat it as Tier 1 in your report. Do not downgrade.
- Your job is to discover and report — within the framework the PM and orchestrator defined.

### Test Data Bootstrap Protocol (MANDATORY)

Before any Playwright/browser testing, you MUST ensure the app has meaningful test data to test against. An empty app cannot be visually tested.

**Step 0: Check for existing data**
- After authenticating in the browser, check if the app shows real content (not empty states)
- If content exists: proceed to testing
- If app shows empty state / no data / "no items" / "get started": you MUST create test data before proceeding

**Step 1: Create test data via available APIs**
- Read the test plan and CLAUDE.md for available API endpoints
- Use curl or Playwright to POST test data that exercises the features you need to test
- The data must be representative: include different content types, edge cases, and enough volume to test scrolling/pagination
- After creating data, reload the app and verify the data appears in the UI

**Step 2: Verify data before testing**
- Take a screenshot AFTER data creation showing the app with real content
- If data creation fails, report it as a BLOCKING issue and explain what you tried
- Do NOT proceed to "code review only" mode -- if you cannot create data, your report must say so prominently in the summary, NOT buried in individual issues

**Honesty Rules**
- `browser_verified` means you SAW the behavior in the browser with real rendered content. Code review findings must set `browser_verified: false`
- `core_flow_completed` means the ENTIRE core flow was executed end-to-end with real data. Partial completion = false
- Never mark grep/code-reading results as browser-verified
- If you cannot test something due to missing data and cannot create that data, mark severity as "blocked" not "confirmed"

### Step 0: Read the test plan (before anything else)

Your prompt includes a `Test plan:` path. Read it first.

1. If the file exists and is valid JSON:
   - Extract `plan_id`; your report carries it as `plan_id`.
   - Extract `app_context` (url, test_email, test_password, plus any extra fields your agent file names).
   - Extract `agent_assignments.<your role>` for your mandatory and secondary tasks.
   - Extract `pm_experience`, the PM's firsthand browser evidence, and treat it as ground truth for what the app
     does.
   - Extract `priority_tiers`: investigate Tier 1 (blocker) first, then Tier 2, then explore freely.
   - Extract `unresolved_from_previous`: verify whether each still exists and report its current status.
   - If your prompt carries a `Priority context:` block, follow its order; still report every issue you find.
   - Use what you extracted instead of rediscovering URL, port or credentials in your discovery phase.
2. If the file is missing or not valid JSON, log the error in your report and fall back to normal discovery.
   Do not abort.

### Symptom-only reporting

You report WHAT you observe and WHERE. You do NOT diagnose WHY or suggest HOW to fix. Root cause analysis
belongs exclusively to BA. Your agent file lists what a good symptom looks like for your role.
