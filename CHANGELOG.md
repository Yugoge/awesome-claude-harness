# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Version claim held below a stable `1.0.0`.** `VERSION` now reads `1.0.0-dev`.
  The previous unconditioned `1.0.0` marker overclaimed: it was never published as
  a git tag, and the release-hygiene work it implies was still open. The marker is
  intentionally held at a pre-release form until this release-hygiene lane's own
  requirements pass — generated-not-tracked `settings.json`, CI hard-failing (not
  advisory) on author-path and workspace-path residue in public-core, commit-SHA
  pinned GitHub Actions, hash-pinned Python dependencies, an enforced non-root
  clean-install smoke, and a signed release archive published with checksums, an
  SBOM and provenance and verified against the PUBLISHED artifact. Re-promoting the
  marker to a stable version is a separate, later decision and is deliberately not
  gated here.

## [1.0.0] - 2026-07-05

### Added
- Multi-layer orchestration pipeline: /spec -> /dev -> /close -> /commit -> /push
- BA/QA/dev subagent roles with structured JSON context contracts
- Hook-enforced safety gates (pretool-bash-safety.sh, pretool-git-privilege-guard.py)
- Parallel-dev worker model with canonical aggregate dev-report
- Graphify knowledge graph integration (advisory, non-blocking)
- Overnight long-running session mode with wall-clock enforcement
- Checkpoint-based spec system (/spec with split views, cp-state tracking)
- Break-glass grant mechanism for authorized privilege operations (/do, /allow)
- Session git-init and canary-verify startup hooks for newcomer safety
- Path-qualified git invocation detection (git_command_classifier.py)
- Doc-sync auto-indexing with excluded pattern support
- World-class readiness improvements: README overhaul, CI, test infrastructure
- QA-of-BA pre-code review gate (analysis validated before any code is written)
- Schema-enforced cycle-contract validation with Draft7 JSON schemas (overnight pipeline)
- Self-updating documentation via PostToolUse doc-sync hooks
- UI-audit skill suite (axe-core, APCA contrast, 58-rule anti-pattern catalog, beauty score)
- Adversarial second opinion via --codex flag integration

[Unreleased]: https://github.com/Yugoge/awesome-claude-harness/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Yugoge/awesome-claude-harness/releases/tag/v1.0.0
