# Contributing

Thanks for your interest in improving awesome-claude-harness.

## Before you start

- This repository is a Claude Code configuration harness: hooks, agents, slash
  commands, scripts, and documentation. Most changes are Markdown, shell, or
  Python.
- Read [`ARCHITECTURE.md`](../ARCHITECTURE.md) and [`CLAUDE.md`](../CLAUDE.md)
  to understand the orchestrator-only model and the git-protection kernel before
  proposing changes to hooks.

## Ground rules

- **Never commit secrets.** No API keys, tokens, passwords, or private paths.
  See [`SECURITY.md`](SECURITY.md).
- **Keep diffs minimal.** Make the smallest change that solves the problem;
  avoid drive-by refactors.
- **Match existing style.** Respect the conventions already present in the file
  you are editing. Comments explain *why*, not *what*.
- **Validate before committing.** Run `bash -n` on shell scripts you touch and
  `python3 -m py_compile` on Python you touch. Confirm `settings.json` parses
  (`python3 -m json.tool settings.json`).
- **Do not weaken safety checks.** If a hook blocks you, fix the upstream cause;
  do not bypass, comment out, or lower a guard.

## Workflow

1. Open an issue describing the problem or proposal (use a template under
   `.github/ISSUE_TEMPLATE/`).
2. Make a focused change.
3. Open a pull request and fill in the PR template.

## Scope note

Some bundled components are non-redistributable — see the root
[`NOTICE`](../NOTICE). Do not add code that assumes those components may be
redistributed.
