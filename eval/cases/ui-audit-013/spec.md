# UI-Audit Eval Case ui-audit-013: News portal home + section pages

## App Description
General-news portal built on Next.js with ISR for top stories and a
custom CMS for editorial layout. Primary user is a returning reader who
checks headlines several times a day, scrolls a long home feed, and dives
into one or two stories per visit. The site monetizes via display ads
that share the page with editorial content, so audit must validate that
ad slots do not violate the design system.

## Routes to Audit
- /
- /world
- /business
- /technology
- /culture
- /story/sample-headline
- /video

## Audit Focus
Hierarchy of headline sizes across breakpoints, ad-slot containment (no
ads bleeding into editorial whitespace tokens), live-update banner
behaviour, video thumbnail tap targets, and continued readability of
captions and bylines under reduced motion preferences.

## Acceptance
- 7 routes captured at both viewports (>= 14 shots).
- Ad-slot wrappers respect declared min/max dimensions; no CLS spikes >0.1.
- Headline hierarchy validated by ui-contextual-heuristics (no skipped levels).
- Video thumbnails meet 44x44 touch-target on mobile.
- Final verdict PASS or WARNING.
