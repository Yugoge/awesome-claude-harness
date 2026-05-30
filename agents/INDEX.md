# agents

*Last updated: 2026-05-30T19:17:15Z*
**Total entries**: 23
**Convention**: kebab

## Tree
```
agents/
├── `architect.md` - Architecture review specialist for overnight exploration. Identifies structural issues, technical debt, optimization opportunities, dependency problems, and pattern inconsistencies. Returns structured JSON report.
├── `ba.md` - Business analyst subagent for requirements analysis and context building. Receives user requirement text, performs git analysis, identifies affected files, and returns either clarification questions or dual-format output (Markdown spec + JSON context).
├── `changelog-analyst.md` - Agentic commit subagent. Reads git state and dev-report to classify files, stages them, writes conventional commit messages (diff-first), handles nested repo, and writes push-gate token. Dispatched exclusively by /commit.
├── `cleaner.md` - Cleanup execution specialist. Executes approved cleanup actions from cleanliness-inspector and style-inspector reports. Returns structured JSON execution report with results.
├── `cleanliness-inspector.md` - File organization inspector for cleanup tasks. Detects misplaced docs, duplicates, temp files, build artifacts. Returns structured JSON report with cleanup recommendations.
├── `dev.md` - Implementation specialist for development tasks. Receives rich JSON context from orchestrator, creates parameterized scripts, implements changes based on git root cause analysis. Returns structured execution report.
├── `git-edge-case-analyst.md` - Git history analysis specialist. Discovers development edge cases by analyzing commits, violations, and patterns. Returns structured edge case report with prevention recommendations.
├── `graphify.md` - Graphify enrichment subagent. Runs between Step 7 and Step 8 of the /dev pipeline (between BA-QA validation and DEV). Performs incremental Graphify cache update, extracts focused subgraph from BA blast-radius-map, patches context-<ts>.json with graph_context field, writes per-task artifacts to .claude/dev-registry/<task_id>/graphify/. Pure infrastructure agent — does NOT analyze requirements, make implementation decisions, write code, or interpret graph data for DEV.
├── `merge-analyst.md` - Pre-merge analyst subagent. Inspects branch divergence, diff stat, conflict markers, and overnight-state consistency; writes a nonce-keyed merge-analyst grant (60s expiry) to /tmp/agentic-commit/merge-analyst/. Dispatched exclusively by /merge.
├── `pm.md` - >-
├── `product-owner.md` - Product-level analysis specialist for overnight exploration. Examines logical consistency, feature completeness, user flows, missing features, and business logic bugs. Returns structured JSON report.
├── `prompt-inspector.md` - Prompt optimization inspector. Detects verbose non-functional content in command/agent documentation following 'rules not stories' principle. Returns structured JSON report with verbosity violations.
├── `pull-analyst.md` - Post-pull advisory analyst subagent. Reads the new-commits range after a successful git pull --rebase and produces a structured semantic risk summary. Writes no grant and blocks nothing. Dispatched exclusively by /pull when HEAD actually changed.
├── `push-analyst.md` - Pre-push analyst subagent. Inspects the commits-to-push range for sensitive files, divergence, and branch protection violations; writes a nonce-keyed push-analyst grant to /tmp/agentic-commit/push-analyst/. Dispatched exclusively by /push.
├── `qa.md` - Quality assurance specialist for verification tasks. Receives implementation report from dev subagent, validates against success criteria, runs verification scripts, identifies issues. Returns structured verification report with pass/fail status.
├── `rule-inspector.md` - Folder rule discovery agent. Analyzes Git history to discover file creation patterns, extracts folder organization rules, generates INDEX.md and README.md documentation. Returns structured JSON with discovered rules.
├── `spec.md` - Three-phase spec subagent. Phase 0 = read spec, decide which agents need views (free judgment). Phase 1 = content-block extraction from full monolith (verbatim byte-slices, no section pre-filtering). Phase 2 = Gawande-style checkpoint generation. Invoked by /spec command with monolith path.
├── `style-inspector.md` - Development standards auditor. Enforces /dev quality standards: no hardcoding, naming conventions, venv usage, step numbering, language, script merging, documentation conciseness. Returns structured JSON report with violations.
├── `test-executor.md` - Execution specialist for test infrastructure. Executes script-based and AI instruction-based tests. Returns structured execution report with results and recommendations.
├── `test-validator.md` - Validation specialist for test infrastructure. Validates test syntax, dependencies, and quality before execution. Returns structured validation report.
├── `test-writer.md` - Generate pytest skeleton tests from BA-produced acceptance-criteria-<task_id>.json with pytest.fail("TEST_INCOMPLETE:...") hard-stops; manage tests/generated/manifest.json with UPDATE vs CREATE logic keyed on ac_uid hashes. Triggered by /dev when complexity_tier >= STANDARD or any tier with risk_level = high (per spec-20260518-225715 §5.2).
├── `ui-specialist.md` - UI/UX review specialist for overnight exploration. Evaluates visual design quality, aesthetic beauty, design system adherence, styling consistency, responsive design, and component quality. Returns structured JSON report with beauty score and design quality assessment. Accessibility checks are advisory.
└── `user.md` - End-user simulation specialist for overnight exploration. Tests actual usage scenarios, checks if things work as expected, identifies UX friction, broken flows, and confusing behavior. Returns structured JSON report.
```

---
*Auto-generated by doc-sync hook.*