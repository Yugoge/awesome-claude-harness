# UI-Audit Eval Case ui-audit-004: SaaS CRM pipeline app

## App Description
B2B sales CRM built on Vue 3 + Vite + Pinia, themed with a custom Tailwind
preset. Primary user is an account executive who works the deal pipeline,
logs calls, and edits contact records. The app integrates with a phone
dialer modal that overlays every page, so audit must validate the dialer
does not regress focus management or contrast.

## Routes to Audit
- /pipeline
- /deals
- /deals/new
- /contacts
- /contacts/edit
- /accounts
- /reports/forecast
- /admin/team

## Audit Focus
Form field validation states, modal focus trapping when the dialer overlay
is open, color encoding of pipeline stages (must remain distinguishable for
Deuteranopia per the brand spec), and table sticky-header behaviour on
mobile when scrolling 20+ row contact lists.

## Acceptance
- All 8 routes audited; >= 16 screenshots; both viewports required.
- ui-axe-injector reports zero color-contrast violations.
- ui-contextual-heuristics flags any reliance on color alone for pipeline state.
- Dialer modal traps focus; Escape closes; focus returns to trigger.
- Final ui-specialist verdict PASS or WARNING.
