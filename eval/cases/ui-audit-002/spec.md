# UI-Audit Eval Case ui-audit-002: SaaS analytics dashboard

## App Description
Multi-tenant analytics SaaS built on React 18 + TanStack Router + Recharts.
Primary user is a marketing operations analyst who logs in daily to review
funnel conversion, cohort retention, and channel attribution dashboards.
The product ships both a light and dark theme, and the design system claims
WCAG 2.1 AA compliance across all chart components.

## Routes to Audit
- /login
- /home
- /dashboards/overview
- /dashboards/funnels
- /dashboards/cohorts
- /reports/scheduled
- /settings/account

## Audit Focus
Brand consistency between marketing-style /home and data-dense dashboards,
chart color contrast under both themes, mobile breakpoints for the data
tables (which historically overflow horizontally on 390px viewports), and
keyboard focus order across nested filter dropdowns.

## Acceptance
- All 7 routes captured at desktop 1440x900 AND mobile 390x844 (min 14 shots).
- ui-axe-injector reports zero serious/critical accessibility violations.
- ui-apca-contrast Lc score >= 60 for body text in both themes.
- ui-anti-pattern-catalog applied to /dashboards/overview and /reports/scheduled.
- Final ui-specialist verdict is PASS or WARNING (FAIL is a regression).
