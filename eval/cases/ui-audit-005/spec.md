# UI-Audit Eval Case ui-audit-005: SaaS billing & subscription console

## App Description
Customer-facing self-service billing portal built with Svelte 5 + SvelteKit.
Primary user is the finance lead at a customer org managing seat counts,
plan tier, payment method, and invoice history. The app is multi-currency
and multi-locale (EN, DE, JA), and the audit must surface any layout
breakage in non-Latin scripts.

## Routes to Audit
- /billing/overview
- /billing/plan
- /billing/seats
- /billing/payment-methods
- /billing/invoices
- /billing/usage
- /settings/locale

## Audit Focus
Currency and date formatting across locales, table-cell wrapping under
Japanese text expansion, plan-tier upgrade dialog clarity, and payment-form
PCI-friendly input affordances (correct autocomplete tokens, separated
expiry/CVV, no autocomplete=off on legitimate fields).

## Acceptance
- All 7 routes captured at both viewports (>= 14 shots).
- Locale toggle exercised: at least one route captured in DE or JA.
- Form fields use correct WCAG-compliant autocomplete tokens.
- ui-anti-pattern-catalog Form rules raise zero major findings on /payment-methods.
- Final verdict PASS or WARNING.
