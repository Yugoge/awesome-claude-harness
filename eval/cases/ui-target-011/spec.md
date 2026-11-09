---
ui_target:
  route: "/admin/users"
  component: "DataTable"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "Sortable, paginated DataTable on /admin/users with row hover states, sticky header, and column-resize on desktop. On mobile, the table collapses to a vertical card-list view (one card per row) since horizontal scroll is poor UX."
  reference_screenshot_path: null
  figma_url: null
  design_tokens_path: "tokens/data-table.json"
---

# UI-Target Eval Case 011: Admin Users Data Table

## Acceptance Criteria
- AC-1: Table header is sticky (position: sticky; top: 0) on desktop scroll within the table container; row height = 56px.
- AC-2: Sort indicator (arrow icon) appears on hover of any sortable header, becomes filled when that column is the active sort key.
- AC-3: On mobile (<=430px), the table element is replaced with a vertical stack of cards, each card containing label/value pairs for that row's columns.

## Out of Scope
- Server-side pagination cursor logic.
- Inline-edit cell behavior.
