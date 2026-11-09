---
ui_target:
  route: "/profile/avatar"
  component: "ThemedAvatar"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "ThemedAvatar on /profile/avatar: circular user-avatar component that uses brand-themed border ring (2px, brand-primary) and a status dot (online=green-500, away=amber-500, offline=neutral-400) at the bottom-right corner. Falls back to initials with a deterministic background color derived from user-id hash."
  reference_screenshot_path: "examples/themed-avatar.png"
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 018: Themed Avatar With Status

## Acceptance Criteria
- AC-1: Avatar dimensions = 64px x 64px on desktop, 48px x 48px on mobile; border-radius = 50%; ring = 2px solid brand-primary.
- AC-2: Status dot is 12px diameter, positioned bottom-right with 2px white border; color matches status (online/away/offline) per spec.
- AC-3: Initials fallback (when avatar image fails to load) uses font-size = 24px desktop / 18px mobile, color = white, background-color computed from user-id hash deterministically.

## Out of Scope
- Avatar upload UI (handled by separate component).
- Group/team avatar stacking layout.
