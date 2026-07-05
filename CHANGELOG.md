# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Schema-enforced agent contracts with Draft7 JSON schema validation
- Self-updating documentation via PostToolUse doc-sync hooks
- UI-audit skill suite (axe-core, APCA contrast, 58-rule anti-pattern catalog, beauty score)
- Adversarial second opinion via --codex flag integration

[Unreleased]: https://github.com/Yugoge/awesome-claude-harness/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Yugoge/awesome-claude-harness/releases/tag/v1.0.0
