---
ui_target:
  route: "/settings/account"
  component: "AccountSettingsForm"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "AccountSettingsForm on /settings/account uses sectioned layout: each settings group (Profile, Security, Notifications, Danger Zone) is a labeled card with a sticky save bar at the bottom that appears only when fields are dirty."
  reference_screenshot_path: null
  figma_url: "https://figma.com/file/account-settings-2026"
  design_tokens_path: null
---

# UI-Target Eval Case 009: Account Settings Form

## Acceptance Criteria
- AC-1: Four settings sections render as separate cards, each with 24px internal padding and 16px gap between cards.
- AC-2: Sticky save bar at viewport bottom is hidden (display:none) when form pristine; visible (display:flex) and contains 'Save changes' button when dirty.
- AC-3: Danger Zone card has border-color = danger-300 and a confirmation modal triggers before destructive actions.

## Out of Scope
- Billing settings (separate route).
- Profile picture upload widget styling.
