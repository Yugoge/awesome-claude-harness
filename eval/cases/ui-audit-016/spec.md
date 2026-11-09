# UI-Audit Eval Case ui-audit-016: Utility admin / settings console

## App Description
Internal admin console for an infrastructure platform built on Vue 3 +
Vuetify. Primary user is a platform engineer managing service tokens,
rotating secrets, configuring webhooks, and reviewing audit logs. The
console is intentionally dense (information per pixel matters more than
beauty) and uses a high-contrast dark-first theme.

## Routes to Audit
- /admin
- /admin/services
- /admin/services/tokens
- /admin/webhooks
- /admin/audit-log
- /admin/feature-flags
- /admin/users

## Audit Focus
Secret-token redaction by default + reveal affordance, audit-log table
density (must remain readable at default zoom), copy-to-clipboard feedback,
destructive-action confirmation patterns (delete service, rotate token),
and visual hierarchy between read-only and mutable controls.

## Acceptance
- 7 routes captured at both viewports (>= 14 shots).
- Secret tokens redacted by default; reveal requires explicit interaction.
- Destructive actions present a confirmation step with the affected resource named.
- Copy-to-clipboard surfaces a success toast within 100ms.
- Final verdict PASS or WARNING.
