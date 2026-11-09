# Docs-Research Eval Case 009: OAuth 2.1 Changes from OAuth 2.0

## Research Question
What does the OAuth 2.1 consolidation draft change relative to OAuth 2.0
+ best-current-practice RFCs, and which flows are deprecated for new
deployments in 2026?

## Required Sources
- official docs of IETF (oauth-v2-1 draft, RFC 6749, RFC 8252, RFC 9700)
- at least 3 distinct domains (ietf.org, oauth.net, datatracker.ietf.org,
  blog.cloudflare.com)
- exclude marketing/blog spam (no vendor product launch posts)

## Required Outputs
- /docs/research/oauth-2.1-changes.md (>=800 words)
- citations array with >=5 entries, each with author/title/url/access_date

## Acceptance
- AC-1: source_citation_count >= 5
- AC-2: word_count >= 800
- AC-3: each citation has author/title/url/access_date
- AC-4: explicitly enumerates the deprecated implicit/password grants and
  describes mandatory PKCE for public clients.

## Out of Scope
No OpenID Connect deep-dive. No SSO product comparisons.
