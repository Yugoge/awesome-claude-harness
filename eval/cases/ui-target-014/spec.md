---
ui_target:
  route: "/header"
  component: "UserDropdownMenu"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "UserDropdownMenu in the global header avatar area: clicking the avatar opens a vertical menu (220px wide) with options Profile, Settings, Help, Sign out. Menu has a 8px elevation shadow, opens with a 150ms fade+slide-down animation, and traps focus while open."
  reference_screenshot_path: null
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 014: User Dropdown Menu

## Acceptance Criteria
- AC-1: Menu width = 220px; opens within 150ms of avatar click; uses opacity 0->1 + translateY(-4px)->0 transition.
- AC-2: Menu has role="menu"; each item has role="menuitem"; arrow keys move focus, Esc closes the menu.
- AC-3: 'Sign out' menu item has color = danger-700 to distinguish destructive action; other items use neutral-900.

## Out of Scope
- Menu positioning relative to RTL languages.
- Avatar image fallback initials styling.
