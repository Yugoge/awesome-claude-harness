---
ui_target:
  route: "/inbox"
  component: "Modal"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "Confirmation Modal triggered from /inbox 'Delete' action. Centered dialog box (480px wide on desktop, full-width minus 32px gutter on mobile) with semitransparent backdrop, 16px border-radius, and primary/secondary action buttons aligned right."
  reference_screenshot_path: "examples/confirm-modal.png"
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 006: Inbox Confirmation Modal

## Acceptance Criteria
- AC-1: Modal width = 480px on desktop (>=1280px), calc(100vw - 32px) on mobile (<=430px); centered both axes.
- AC-2: Backdrop = rgba(0, 0, 0, 0.5); modal box-shadow = 0 12px 32px rgba(0, 0, 0, 0.16).
- AC-3: Action buttons (Cancel, Delete) align flex-end with 8px gap; Delete button uses danger color, Cancel uses neutral.

## Out of Scope
- Modal entry/exit animation timing curve.
- Other modals on /inbox (e.g., compose, archive).
