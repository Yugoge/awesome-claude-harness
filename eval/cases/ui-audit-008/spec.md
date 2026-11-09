# UI-Audit Eval Case ui-audit-008: E-commerce checkout flow

## App Description
Multi-step checkout flow for a marketplace built with Remix + Stripe Elements.
Primary user is an authenticated shopper completing a purchase across
contact, shipping, payment, and confirmation steps. The flow is tracked as
a critical conversion funnel and any layout regression directly costs
revenue, so audit must be unusually conservative.

## Routes to Audit
- /checkout/cart
- /checkout/contact
- /checkout/shipping
- /checkout/payment
- /checkout/review
- /checkout/confirmation
- /checkout/error

## Audit Focus
Step-progress indicator clarity, inline validation for address and card
fields, Apple Pay / Google Pay button rendering parity, error-state
recovery affordances, and the confirmation page's order-summary printability
(some merchants users print this directly from the browser).

## Acceptance
- All 7 checkout steps captured at both viewports (>= 14 shots).
- ui-axe-injector reports zero critical violations on payment + review.
- Stripe Element iframes render with visible labels and error messages.
- ui-anti-pattern-catalog Form rules surface zero hard defects on /payment.
- Final verdict PASS or WARNING; FAIL on any checkout step is a regression.
