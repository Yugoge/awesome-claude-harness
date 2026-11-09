# UI-Audit Eval Case ui-audit-011: Editorial blog / magazine site

## App Description
Long-form editorial publication built on Astro + MDX with a custom
typography-first design system. Primary user is a casual reader who
arrives via social or search, reads one or two articles per session, and
occasionally subscribes to the newsletter. Reading-experience polish
(line length, leading, color of inline links) is the principal quality bar.

## Routes to Audit
- /
- /articles
- /articles/feature-piece
- /articles/feature-piece#section-3
- /authors/jane-doe
- /tags/longform
- /newsletter

## Audit Focus
Body-text measure (target 60-75 char), paragraph rhythm and leading, inline
link affordance (must be distinguishable without color), pull-quote and
figure styling consistency, and the floating reading-progress indicator
on long articles (must not occlude content on mobile).

## Acceptance
- 7 routes captured at both viewports (>= 14 shots).
- Body line length measured between 50-85 characters on /articles/feature-piece.
- Inline links have non-color affordance (underline or weight delta).
- ui-anti-pattern-catalog Typography rules raise zero hard defects.
- Final verdict PASS or WARNING.
