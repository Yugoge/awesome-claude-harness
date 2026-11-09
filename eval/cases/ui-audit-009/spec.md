# UI-Audit Eval Case ui-audit-009: E-commerce product detail experience

## App Description
Product detail page surface for a consumer electronics retailer built on
Astro + Preact islands. Primary user is a comparison shopper deep in
research mode, toggling variants, reading specs, watching embedded video,
and reading reviews. The PDP is the most complex single page in the
storefront and frequently exceeds 8000px on mobile.

## Routes to Audit
- /products/headphones-pro
- /products/headphones-pro?variant=midnight
- /products/headphones-pro#specs
- /products/headphones-pro#reviews
- /products/headphones-pro#qa
- /products/headphones-pro/compare
- /products/headphones-pro/bundle

## Audit Focus
Variant swatch contrast and selection feedback, sticky add-to-cart bar
behaviour during long-page scroll, lazy-loaded review section CLS budget,
embedded video accessibility (captions, controls, no autoplay-with-sound),
and tab-to-fragment navigation parity between desktop tabs and mobile
accordions.

## Acceptance
- 7 deep-link variations captured at both viewports (>= 14 shots).
- Sticky add-to-cart visible on viewports >= 600px tall, hidden on <500.
- Embedded video has visible controls and CC track present.
- CLS observed during lazy review load remains <= 0.1 (informational only).
- Final verdict PASS or WARNING.
