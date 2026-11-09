# UI-Audit Eval Case ui-audit-003: SaaS project management workspace

## App Description
Cross-functional project management tool built with Next.js 14 (App Router)
and TanStack Query. Primary user is a project manager juggling 3-7 active
projects, switching between Kanban, Gantt, and timeline views many times
per session. The app is offered as both a web SaaS and an Electron desktop
shell, but this audit covers only the browser experience.

## Routes to Audit
- /workspace
- /projects
- /projects/board
- /projects/gantt
- /projects/timeline
- /inbox
- /team/members
- /settings/notifications

## Audit Focus
Drag-and-drop affordances across Kanban columns, density of the Gantt grid
on mobile (it currently degrades to a horizontal scroll surface), navigation
chrome consistency between work-tracking and admin areas, and contrast of
status pills (To-Do, In Progress, Blocked, Done) on both light and dark.

## Acceptance
- 8 routes captured at both viewports (>= 16 screenshots total).
- Status pill APCA Lc >= 45 for non-body chip text, >= 60 for any text >12pt.
- Drag-handle elements meet 44x44 px touch-target minimum on mobile.
- ui-state-matrix shows >= 5 of 7 interactive states present on Kanban cards.
- Final verdict PASS or WARNING; aggregated beauty_score >= 6.5.
