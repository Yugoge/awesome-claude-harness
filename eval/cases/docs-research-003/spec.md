# Docs-Research Eval Case 003: Next.js App Router Deep-Dive

## Research Question
How does the Next.js App Router (>=14) replace the Pages Router, and what
are the migration, caching, and routing trade-offs in production?

## Required Sources
- official docs of nextjs.org (App Router reference)
- at least 3 distinct domains (nextjs.org, vercel.com, github.com)
- exclude marketing/blog spam (no SEO listicles)

## Required Outputs
- /docs/research/nextjs-app-router.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers segment-level caching, parallel routes, route groups, and
  the data-fetching model (fetch dedupe + revalidation tags).

## Out of Scope
No comparison with Remix or Astro. No deployment-platform recommendations.
