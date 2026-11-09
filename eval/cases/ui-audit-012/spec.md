# UI-Audit Eval Case ui-audit-012: Developer documentation site

## App Description
Open-source SDK documentation site built on Docusaurus 3 (React under the
hood) with Algolia DocSearch. Primary user is a developer integrating the
SDK, jumping between concept pages, API reference, and runnable code
samples. The doc site supports a versioned URL scheme (/v1, /v2, /next)
and ships in light + dark + system themes.

## Routes to Audit
- /
- /docs/getting-started
- /docs/concepts/auth
- /docs/api/clients/list
- /docs/guides/migration-v1-to-v2
- /blog
- /search?q=auth

## Audit Focus
Code-block syntax theme contrast in both color modes, copy-button affordance
on code samples, sidebar TOC scroll-spy accuracy, version-switcher
visibility, search modal accessibility (focus trap, escape to close), and
mobile sidebar drawer interaction.

## Acceptance
- 7 routes captured at both viewports (>= 14 shots).
- Code-block APCA Lc >= 60 in BOTH light and dark for every supported language.
- Copy button is keyboard-reachable and announces success state.
- Search modal traps focus and returns focus to trigger on close.
- Final verdict PASS or WARNING.
