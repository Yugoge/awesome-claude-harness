---
ui_target:
  route: "/dashboard"
  component: "Sidebar"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "Persistent left Sidebar on /dashboard with collapsible nav groups, 240px expanded width on desktop, full-screen overlay on mobile triggered by a hamburger toggle. Nav items show active-route highlight using brand-primary at 12% opacity background."
  reference_screenshot_path: null
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 002: Dashboard Sidebar Navigation

## Acceptance Criteria
- AC-1: Sidebar width = 240px on desktop (>=1280px viewport), 0px (off-canvas) on mobile (<=430px viewport).
- AC-2: Active nav item background = brand-primary @ 12% alpha; inactive nav item background = transparent.
- AC-3: Mobile hamburger toggle opens Sidebar as full-screen overlay within 200ms; tap-outside dismisses.

## Out of Scope
- Sidebars on /settings, /billing, or any non-/dashboard route.
- Re-skinning of the brand-primary token itself.
