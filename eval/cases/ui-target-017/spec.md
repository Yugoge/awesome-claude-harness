---
ui_target:
  route: "/settings/appearance"
  component: "DarkModeToggle"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "DarkModeToggle on /settings/appearance: a 3-state segmented control (Light / System / Dark) that switches the global color theme. Selected segment has brand-primary background and white text; unselected segments are transparent with neutral-700 text. Theme switch animates color tokens over 240ms."
  reference_screenshot_path: null
  figma_url: null
  design_tokens_path: "tokens/theme-light.json"
---

# UI-Target Eval Case 017: Dark Mode Theme Toggle

## Acceptance Criteria
- AC-1: Segmented control renders exactly 3 segments (Light, System, Dark) with equal width within a 280px container; height = 36px.
- AC-2: Selecting a segment updates document.documentElement.dataset.theme to "light" | "system" | "dark" within 50ms.
- AC-3: Theme transition animates background-color and color CSS properties over 240ms ease-in-out across the entire viewport.

## Out of Scope
- Per-component override settings (use global theme).
- Persisting theme preference across sessions (handled by storage layer).
