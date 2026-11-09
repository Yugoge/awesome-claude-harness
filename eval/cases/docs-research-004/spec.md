# Docs-Research Eval Case 004: Svelte 5 Runes

## Research Question
What are Svelte 5 runes, how do they replace the legacy reactive-let
pattern, and what are the migration costs for an existing Svelte 4 app?

## Required Sources
- official docs of svelte.dev (runes RFC + 5.x release notes)
- at least 3 distinct domains (svelte.dev, github.com, learn.svelte.dev)
- exclude marketing/blog spam (no influencer threads)

## Required Outputs
- /docs/research/svelte-5-runes.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: covers $state, $derived, $effect, $props, snippets, and the
  fine-grained reactivity rationale.

## Out of Scope
No comparison with Vue/React signals. No SvelteKit-specific routing.
