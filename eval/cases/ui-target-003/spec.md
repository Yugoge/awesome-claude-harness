---
ui_target:
  route: "/home"
  component: "Header"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "Sticky top Header on /home that compacts after 80px of vertical scroll: full-height (80px) at top of page, condensed (48px) once user scrolls past threshold. Logo scales down proportionally; nav links remain visible on desktop, collapse to icon-only on mobile."
  reference_screenshot_path: "examples/sticky-header.png"
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 003: Sticky Compacting Header

## Acceptance Criteria
- AC-1: Header height = 80px when scrollY < 80, 48px when scrollY >= 80, with a 200ms ease transition.
- AC-2: Logo image height transitions from 40px to 28px synchronized with header compaction.
- AC-3: On mobile (<=430px), nav-link text is hidden and only icons render at any scroll position.

## Out of Scope
- Footer scroll behavior.
- Header on routes other than /home.
