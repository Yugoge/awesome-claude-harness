---
ui_target:
  route: "/login"
  component: "LoginForm"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "LoginForm on /login: centered card with email + password fields, 'Remember me' checkbox, primary 'Sign in' button (full-width), and links for 'Forgot password' and 'Create account'. Card width 400px on desktop, full-width-minus-32px on mobile."
  reference_screenshot_path: null
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 007: Login Form

## Acceptance Criteria
- AC-1: Email and password input height = 44px; border = 1px solid neutral-300; focus border = 2px solid brand-primary.
- AC-2: 'Sign in' button is 100% width of the card, height = 48px, background = brand-primary, color = white.
- AC-3: On invalid credentials, an inline error banner appears above the form with role="alert" and background = danger-50.

## Out of Scope
- OAuth provider buttons (separate spec).
- Multi-factor authentication step.
