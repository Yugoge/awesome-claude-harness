# FAQ

Questions people ask before they adopt the harness.

[Back to the README](../README.md)

## FAQ

**Is this a framework I import?** No. It is a *configuration* for Claude Code specifically — not a library, not an npm package, not an LLM SDK. Its hooks + commands + agents change how Claude Code behaves in every session. There is nothing to `npm install` into your app and no API to call. It is Claude Code-specific — it will not work with other LLM clients without substantial adaptation. The full harness is a git clone plus one init run (`scripts/bootstrap`), which keeps your machine values in an untracked overlay; the guardrails alone install with `scripts/install/install --profile core`, which keeps them in their own isolated directory and merges a short, enumerable footprint into your Claude config home instead of replacing it (`scripts/install/uninstall` reverses that). See [Install](installation.md).

**Does the orchestrator-only rule make simple edits slow?** For a one-line fix you can `/do` to let the main agent act directly for one turn. The delegation overhead is the price of consistent quality on real tasks — and the autonomous loop pays for itself overnight.

**Can the agent disable its own guardrails?** The design makes it *hard*, not metaphysically impossible. Release commands are `disable-model-invocation: true` *and* denied as `Skill(<name>:*)`; the git-privilege-guard is always-on and default-denies every agent — a matching structured `/allow` sentinel is honored even for subagents (only legacy git-allowlist grants are main-agent-only) and subagents never get `/do`; the commit grant is single-use and time-boxed; the push grant is branch/head/remote-bound and wrapper-managed (unlinked on success, retryable on failure); the bash-safety hook blocks destructive shell forms by shape. One residual remains: during `--worktree` overnight runs the linked worktree shares the `.git` common-dir (an in-place run works in the checkout itself, with no worktree boundary) — `commands/dev-overnight.md` documents this as an accepted deviation.

**Can I use this with a team or in CI?** The harness is designed for single-developer use. For team use, each developer clones it to their own `~/.claude`; hooks and grants are per-session and use `$HOME`-relative paths. CI use requires the full Claude Code environment — hooks fire only when Claude Code runs. The test suite (`pytest hooks/tests tests`) is CI-safe and runs without Claude Code.

**What about parallel Claude Code sessions?** Multiple sessions on the same machine share the same `~/.claude` working tree. Grant files in `/tmp/` are session-keyed by session ID. The `flock`-based serialization in checkpoint writes prevents concurrent corruption. The overnight loop works in your checkout by default (in a linked worktree only with `--worktree`) and should not be started alongside an interactive session editing the same files. The doc-sync hook is idempotent.

**Where do I go deeper?**
- The constitution: [`CLAUDE.md`](../CLAUDE.md)
- System architecture: [`ARCHITECTURE.md`](../ARCHITECTURE.md)
- Git protection kernel: [`hooks/pretool-git-privilege-guard.py`](../hooks/pretool-git-privilege-guard.py), [`hooks/pretool-bash-safety.sh`](../hooks/pretool-bash-safety.sh)
- Checkpoint mechanism: [`docs/reference/checkpoint-mechanism.md`](reference/checkpoint-mechanism.md)
