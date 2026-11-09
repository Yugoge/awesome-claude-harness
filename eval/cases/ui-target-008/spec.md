---
ui_target:
  route: "/signup"
  component: "SignupForm"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "SignupForm on /signup with three fields (full name, email, password) and a real-time password-strength meter. Submit button disabled until all fields valid. Strength meter renders as a 4-segment bar with weak=red, fair=amber, good=lime, strong=green."
  reference_screenshot_path: "examples/signup-strength.png"
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 008: Signup Form with Strength Meter

## Acceptance Criteria
- AC-1: Password strength meter visually transitions through 4 states (weak/fair/good/strong) with correct color tokens at zxcvbn scores 0/1/2/3+ respectively.
- AC-2: Submit button has aria-disabled="true" and 50% opacity while any field is invalid; aria-disabled="false" and full opacity once all valid.
- AC-3: Inline field-level error text appears below each field on blur if invalid, color = danger-700, font-size = 12px.

## Out of Scope
- Server-side validation responses.
- Email verification flow after submit.
