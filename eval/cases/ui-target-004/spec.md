---
ui_target:
  route: "/projects"
  component: "CardGrid"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "Project CardGrid on /projects displays project tiles in a responsive 3-column desktop / 1-column mobile layout. Each card has a 16px internal padding, 8px border-radius, and a subtle shadow on hover. Cards align to a 24px gutter."
  reference_screenshot_path: null
  figma_url: "https://figma.com/file/projectgrid-2026"
  design_tokens_path: null
---

# UI-Target Eval Case 004: Projects Card Grid Layout

## Acceptance Criteria
- AC-1: CardGrid renders 3 columns on desktop (>=1280px), 1 column on mobile (<=430px), with 24px gap between cards.
- AC-2: Each card has padding=16px, border-radius=8px on both viewports.
- AC-3: Card hover state (desktop only) elevates shadow from 0/2/4 rgba(0,0,0,0.06) to 0/8/16 rgba(0,0,0,0.12).

## Out of Scope
- Empty-state illustration (separate spec).
- Card content (title, description) styling.
