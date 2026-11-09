---
ui_target:
  route: "/dashboard"
  component: "Header"
viewport_targets: [desktop, mobile]
design_inputs:
  verbal_description: "Refresh the Header on /dashboard so the brand mark sits flush left, the primary nav links cluster center with even gaps, and the user-menu avatar sits flush right with a consistent vertical rhythm."
  reference_images: []
  tokens_to_respect: ["color.brand.primary", "spacing.4", "spacing.6", "radius.md"]
---

# ui-target-smoke-01

## Title
Targeted Header redesign on the `/dashboard` route

## Scope
Update only the Header component rendered at the `/dashboard` route. Do not
touch headers used on `/settings`, `/billing`, or `/auth/*`.

## Goal
Achieve a visually balanced, evenly-spaced top navigation bar that respects
the declared design tokens and renders correctly at both desktop (1440x900)
and mobile (390x844) viewports.

## Verification
- Desktop and mobile screenshots showing the updated layout.
- DOM measurements (computed gap, padding, alignment) matching the tokens.
- Playwright trace of the `/dashboard` route load.
