# UI-Audit Eval Case ui-audit-007: E-commerce storefront

## App Description
Direct-to-consumer fashion storefront built on Next.js 14 with React Server
Components and a Shopify Storefront API backend. Primary user is a shopper
browsing on either desktop or smartphone, often anonymously. The brand
identity is photo-led with large hero imagery, heavy use of editorial
typography, and a custom serif/sans pairing.

## Routes to Audit
- /
- /collections/new-arrivals
- /collections/sale
- /products/sample-jacket
- /search?q=jacket
- /lookbook
- /journal

## Audit Focus
Hero LCP image loading behaviour, gallery zoom and pinch interactions on
mobile, product-card hover affordances on desktop, tap-target spacing on
the mega-menu, and serif body legibility under APCA contrast on warm
neutral backgrounds (a known weak point for the brand palette).

## Acceptance
- 7 routes captured at both viewports (>= 14 shots).
- LCP element identified per route; no layout-shift findings of severity major+.
- Mega-menu items meet 24px minimum vertical spacing.
- ui-apca-contrast Lc >= 60 for body copy on warm neutral panels.
- Final verdict PASS or WARNING.
