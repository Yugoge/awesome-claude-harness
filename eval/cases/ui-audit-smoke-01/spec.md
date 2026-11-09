# ui-audit-smoke-01

## Title
Full-app UI audit of the React SaaS dashboard

## Context
The application under audit is a React SaaS dashboard with eight customer-
facing routes: `/`, `/dashboard`, `/projects`, `/settings`, `/billing`,
`/team`, `/integrations`, and `/profile`. We need an aesthetic + UX audit
focused initially on `/` (homepage) and `/settings`, but the full route
graph must be visited to surface global navigation issues, dark-mode
regressions, and viewport breakpoints.

## Scope
- Visit every route at desktop (1440x900) AND mobile (390x844).
- Capture two screenshots per route (desktop + mobile) — minimum 16 images.
- Run the ui-axe-injector + ui-apca-contrast skills on every route.
- Use the ui-anti-pattern-catalog 58-rule pass on the homepage and settings
  pages specifically (deeper dive than the other routes).

## Deliverable
A single ui-specialist 6-channel report identifying hard defects, taste
heuristics, accessibility violations, and aggregated beauty score with sub-
scores per the ui-beauty-score skill.
