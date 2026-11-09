---
ui_target:
  route: "/board"
  component: "DragDropKanbanColumn"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "DragDropKanbanColumn on /board: column of cards that supports drag-and-drop reorder within a column and across columns. Dragging card shows ghost placeholder at insertion point; drop zones highlight with brand-primary @ 8% alpha background while card is hovering."
  reference_screenshot_path: "examples/kanban-drag.png"
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 015: Kanban Drag-and-Drop Column

## Acceptance Criteria
- AC-1: Card drag preview has opacity = 0.6, transform: rotate(2deg), and box-shadow = 0 16px 32px rgba(0,0,0,0.18).
- AC-2: Drop-zone highlight applies background = brand-primary @ 8% alpha and a 2px dashed brand-primary border on the receiving column.
- AC-3: After drop, card animates into final position over 200ms ease-out; drag preview removed and original card re-rendered in new position.

## Out of Scope
- Touch-device gesture support (separate spec).
- Persistence of column-order to backend.
