---
ui_target:
  route: "/profile"
  component: "TabNavigation"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "Horizontal TabNavigation at the top of /profile with 4 tabs (Overview, Activity, Connections, Settings). Active tab has 2px brand-primary underline; inactive tabs use neutral-600 text. On mobile, tabs become horizontally scrollable with snap-to-tab behavior."
  reference_screenshot_path: null
  figma_url: null
  design_tokens_path: "tokens/profile-tabs.json"
---

# UI-Target Eval Case 005: Profile Tab Navigation

## Acceptance Criteria
- AC-1: Active tab indicator = 2px solid brand-primary underline positioned at the bottom of the active tab; inactive tabs have no underline.
- AC-2: Tab text color = neutral-600 (inactive), neutral-900 (active); font-weight = 500 (inactive), 600 (active).
- AC-3: On mobile, the tab strip is horizontally scrollable with overflow-x: auto and scroll-snap-type: x mandatory.

## Out of Scope
- Tab content panels (each tab's body).
- Tab navigation in the SettingsModal (separate component).
