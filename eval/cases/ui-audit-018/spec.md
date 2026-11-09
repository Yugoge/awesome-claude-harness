# UI-Audit Eval Case ui-audit-018: Utility multi-step financial calculator

## App Description
Public-facing mortgage refinance calculator built on Next.js 14 with a
custom multi-step form library. Primary user is a homeowner exploring
refinance scenarios, entering loan details across 5-7 form steps, and
reviewing a results page with interactive charts. The tool acts as a lead-
generation surface and must function flawlessly on slow mobile networks.

## Routes to Audit
- /calculator
- /calculator/step-1
- /calculator/step-2
- /calculator/step-3
- /calculator/step-4
- /calculator/results
- /calculator/results?scenario=alt

## Audit Focus
Step progress indicator clarity, numeric input formatting and validation
(currency masks, percentage formats), back-navigation preserving state,
results-chart axis legibility on mobile, scenario-comparison toggle
behaviour, and accessibility of the lead-capture form gating the full
results PDF download.

## Acceptance
- 7 calculator surfaces captured at both viewports (>= 14 shots).
- Numeric inputs accept and display localized formats (commas, decimals).
- Back navigation preserves previously entered values without prompting.
- Results chart axes legible at 390px width.
- Final verdict PASS or WARNING.
