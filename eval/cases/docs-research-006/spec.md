# Docs-Research Eval Case 006: Angular Signals

## Research Question
How do Angular Signals (introduced in Angular 16, stabilized through
17/18) change change-detection, and what is the migration story for
Zone.js apps?

## Required Sources
- official docs of angular.dev (signals guide + RFC)
- at least 3 distinct domains (angular.dev, blog.angular.io, github.com)
- exclude marketing/blog spam (no SEO-spam tutorials)

## Required Outputs
- /docs/research/angular-signals.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers signal/computed/effect, the zoneless mode preview, and
  interop with RxJS observables.

## Out of Scope
No comparison with React/Solid signals. No build-system specifics.
