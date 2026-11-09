---
ui_target:
  route: "/notifications"
  component: "NotificationList"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "NotificationList on /notifications: vertical list of notification items with avatar, title, body excerpt, timestamp, and unread indicator. Pagination at bottom with Previous/Next buttons + page-N-of-M label. Unread items have left-border accent in brand-primary."
  reference_screenshot_path: null
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 013: Notifications List With Pagination

## Acceptance Criteria
- AC-1: Each notification item has a left border = 3px solid brand-primary if unread, 3px solid transparent if read; total item height = 72px.
- AC-2: Pagination footer renders 'Previous' button, 'Page X of Y' label, 'Next' button with 12px gap; disabled buttons have aria-disabled="true" and 50% opacity.
- AC-3: Timestamp text uses relative format ('2h ago', '3d ago') in neutral-500 at 12px font-size.

## Out of Scope
- Real-time push notification arrival.
- Mark-all-as-read bulk action UI.
