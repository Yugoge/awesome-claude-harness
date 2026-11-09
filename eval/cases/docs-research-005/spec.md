# Docs-Research Eval Case 005: Vue 3.4 Composition API

## Research Question
What concrete improvements does Vue 3.4 ship for the Composition API,
including defineModel, generic components, and the reactive transform
status?

## Required Sources
- official docs of vuejs.org (3.4 release notes + composition API guide)
- at least 3 distinct domains (vuejs.org, github.com, blog.vuejs.org)
- exclude marketing/blog spam (no clickbait roundup posts)

## Required Outputs
- /docs/research/vue-3.4-composition.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers performance changes (parser rewrite), defineModel macro,
  generic components, and ref-vs-reactive guidance.

## Out of Scope
No comparison with Pinia/Vuex. No Nuxt-specific guidance.
