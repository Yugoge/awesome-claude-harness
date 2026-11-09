---
ui_target:
  route: "/onboarding"
  component: "MultiStepWizard"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "MultiStepWizard on /onboarding with 4 steps (Welcome, Profile, Preferences, Done). Top progress indicator shows current step with brand-primary fill; previous steps are check-marked; future steps are neutral-300. Bottom action row: Back (left, ghost) + Next/Finish (right, primary)."
  reference_screenshot_path: null
  figma_url: "https://figma.com/file/onboarding-2026"
  design_tokens_path: null
---

# UI-Target Eval Case 016: Onboarding Multi-Step Wizard

## Acceptance Criteria
- AC-1: Progress indicator renders 4 step nodes connected by a horizontal track; current step node has background = brand-primary, completed steps show check-mark icon, future steps have background = neutral-300.
- AC-2: 'Back' button is hidden on Step 1; 'Next' button label changes to 'Finish' on the final step.
- AC-3: Step transition animates content with 200ms slide-left (forward) or slide-right (back); progress indicator updates synchronously.

## Out of Scope
- Form validation rules per step (handled by individual step components).
- Save-and-resume capability for partial completion.
