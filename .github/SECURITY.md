# Security Policy

## Reporting a Vulnerability (Disclosure)

If you discover a security vulnerability in this harness, please report it
privately. **Do not open a public issue for security problems.**

- Preferred: open a private GitHub Security Advisory
  (Security tab → "Report a vulnerability") on this repository.
- Alternatively: contact the maintainer via the email on the GitHub profile of
  the repository owner.

Please include enough detail to reproduce: affected file(s), the conditions
that trigger the issue, and the impact. We aim to acknowledge a report within a
few days and will coordinate a fix and a coordinated disclosure timeline with
you.

## Secrets must never be committed

This is a configuration harness, and the single highest-impact failure mode is a
committed secret.

- Never commit API keys, tokens, passwords, credentials, or private
  infrastructure paths. Use environment variables or an untracked `.env`.
- If a secret is accidentally committed, treat it as compromised: rotate it
  immediately and report it through the disclosure path above so the history can
  be addressed.
- The git-protection hooks block force-pushes and history rewrites by default;
  removing a leaked secret from history is a deliberate, human-authorized
  operation, not an automated one.

## Scope

Security reports about the harness's own hooks, scripts, agents, and commands
are in scope. Note that some bundled third-party skills are non-redistributable
and carry their own terms — see the root [`NOTICE`](../NOTICE).
