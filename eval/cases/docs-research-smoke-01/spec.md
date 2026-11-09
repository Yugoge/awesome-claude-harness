# docs-research-smoke-01

## Title
Write a research brief on managed CI/CD options for self-hosted Forgejo

## Goal
Produce `docs/research/forgejo-ci-options.md` summarizing the current
landscape of CI runners and managed CI services compatible with self-hosted
Forgejo, with a recommendation for our use case (small team, < 50 jobs/day,
budget-conscious).

## Required Sections
1. Overview of Forgejo Actions native runner.
2. Comparison: Woodpecker CI, Drone, Gitea Actions runners (Forgejo fork).
3. Hosted alternatives (Earthly, Nixie, others) and how they integrate.
4. Cost / operational comparison table.
5. Final recommendation + migration cost estimate.

## Source Requirements
- Cite at least 5 distinct authoritative sources (project docs, primary
  blog posts from maintainers, conference talks). No anonymous Medium
  posts. Each source must be inline-linked.

## Out of Scope
No code changes. No infrastructure provisioning. No UI work.
