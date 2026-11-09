# UI-Audit Eval Case ui-audit-010: E-commerce account & order history

## App Description
Authenticated post-purchase account portal for a subscription meal-kit
service built on React 18 + Redux Toolkit. Primary user is a returning
subscriber managing upcoming deliveries, skipping weeks, swapping recipes,
and reviewing past order details. The portal also exposes referral and
gifting flows that are heavily promoted in marketing emails.

## Routes to Audit
- /account
- /account/upcoming
- /account/orders
- /account/orders/12345
- /account/preferences
- /account/referrals
- /account/gift

## Audit Focus
Empty-state design when a user has no upcoming orders, calendar/week-picker
keyboard accessibility, swap-recipe interaction (drag, click, and long-press
on touch), gifting form validation clarity, and consistency of CTA styling
across promotional surfaces (referrals, gifting) vs transactional surfaces
(skip, change recipes).

## Acceptance
- 7 routes captured at both viewports (>= 14 shots).
- Calendar week-picker fully keyboard-operable (arrow keys + enter).
- Empty states present non-generic copy and a clear next-step CTA.
- ui-token-conformance flags any CTA that diverges from declared brand tokens.
- Final verdict PASS or WARNING.
