---
ui_target:
  route: "/analytics"
  component: "RevenueChart"
viewport_targets:
  - desktop
  - mobile
design_inputs:
  verbal_description: "RevenueChart on /analytics: a responsive line chart showing daily revenue over the past 30 days with hover tooltip, axis labels, and a legend. Uses brand-primary for the line stroke and a 16% alpha brand-primary fill for the area gradient."
  reference_screenshot_path: "examples/revenue-chart.png"
  figma_url: null
  design_tokens_path: null
---

# UI-Target Eval Case 012: Revenue Analytics Chart

## Acceptance Criteria
- AC-1: Chart container fills 100% of its parent width; height = 320px desktop, 240px mobile; SVG viewBox preserves aspect via preserveAspectRatio="none".
- AC-2: Line stroke = brand-primary, stroke-width = 2px; area fill = brand-primary @ 16% alpha.
- AC-3: Hover tooltip appears within 100ms of pointer entering chart bounds, shows date + formatted currency value.

## Out of Scope
- Date-range picker control above the chart.
- Other chart types on /analytics (bar, donut).
