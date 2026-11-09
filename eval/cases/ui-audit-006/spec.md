# UI-Audit Eval Case ui-audit-006: SaaS helpdesk / support ticketing

## App Description
Internal-facing helpdesk console built on Angular 17 + RxJS. Primary user
is a tier-1 support agent who triages, replies to, escalates, and resolves
customer tickets. Heavy keyboard usage (j/k navigation, hotkeys for canned
responses) is a core workflow, so accessibility for keyboard-first
operation is the dominant audit lens.

## Routes to Audit
- /inbox/unassigned
- /inbox/mine
- /tickets/123
- /tickets/123/conversation
- /macros
- /reports/sla
- /admin/agents

## Audit Focus
Keyboard navigation flow (focus order, visible focus rings, no focus traps
outside modals), ticket-conversation rendering of inline images and code
blocks, sidebar information density, and the sticky reply composer behaviour
when conversation length exceeds the viewport.

## Acceptance
- 7 routes captured at both viewports (>= 14 shots).
- Visible focus indicators present on every interactive element (ui-state-matrix).
- Hotkey reference modal opens with `?` and is itself accessible.
- ui-axe-injector raises zero serious violations across the inbox routes.
- Final verdict PASS or WARNING.
