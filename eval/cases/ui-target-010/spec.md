---
ui_target:
  route: "/search"
  component: "SearchWithFilters"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "SearchWithFilters on /search: a top search input with autocomplete, a left filter rail (desktop) or filter sheet (mobile bottom-sheet), and a results pane on the right. Active filter chips show selected values inline with X-to-remove."
  reference_screenshot_path: null
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 010: Search With Filters

## Acceptance Criteria
- AC-1: Search input height = 48px, border-radius = 24px, leading icon = magnifying-glass at 20px, padded 16px from left edge.
- AC-2: Filter rail width = 280px on desktop; on mobile, filters live in a bottom sheet that slides up from viewport-bottom triggered by a 'Filters' button.
- AC-3: Each active filter chip has background = brand-primary @ 8% alpha, color = brand-primary-700, and a clickable X icon at 16px.

## Out of Scope
- Backend search ranking algorithm.
- Saved search functionality.
