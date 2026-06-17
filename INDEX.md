# dot-claude

<!-- AUTO:index-stats -->
*Last updated: 2026-06-17T00:04:29Z*
**Total entries**: 1973
**Convention**: kebab

## Tree
```
dot-claude/
├── agents/
│   ├── `architect.md` - Architecture review specialist for overnight exploration. Identifies structural issues, technical debt, optimization opportunities, dependency problems, and pattern inconsistencies. Returns structured JSON report.
│   ├── `ba.md` - Business analyst subagent for requirements analysis and context building. Receives user requirement text, performs git analysis, identifies affected files, and returns either clarification questions or dual-format output (Markdown spec + JSON context).
│   ├── `changelog-analyst.md` - Agentic commit subagent. Reads git state and dev-report to classify files, stages them, writes conventional commit messages (diff-first), handles nested repo, and writes push-gate token. Dispatched exclusively by /commit.
│   ├── `cleaner.md` - Cleanup execution specialist. Executes approved cleanup actions from cleanliness-inspector and style-inspector reports. Returns structured JSON execution report with results.
│   ├── `cleanliness-inspector.md` - File organization inspector for cleanup tasks. Detects misplaced docs, duplicates, temp files, build artifacts. Returns structured JSON report with cleanup recommendations.
│   ├── `dev.md` - Implementation specialist for development tasks. Receives rich JSON context from orchestrator, creates parameterized scripts, implements changes based on git root cause analysis. Returns structured execution report.
│   ├── `git-edge-case-analyst.md` - Git history analysis specialist. Discovers development edge cases by analyzing commits, violations, and patterns. Returns structured edge case report with prevention recommendations.
│   ├── `graphify.md` - Graphify enrichment subagent. Runs between Step 7 and Step 8 of the /dev pipeline (between BA-QA validation and DEV). Performs incremental Graphify cache update, extracts focused subgraph from BA blast-radius-map, patches context-<ts>.json with graph_context field, writes per-task artifacts to .claude/dev-registry/<task_id>/graphify/. Pure infrastructure agent — does NOT analyze requirements, make implementation decisions, write code, or interpret graph data for DEV.
│   ├── `merge-analyst.md` - Pre-merge analyst subagent. Inspects branch divergence, diff stat, conflict markers, and overnight-state consistency; writes a nonce-keyed merge-analyst grant (60s expiry) to /tmp/agentic-commit/merge-analyst/. Dispatched exclusively by /merge.
│   ├── `pm.md` - >-
│   ├── `product-owner.md` - Product-level analysis specialist for overnight exploration. Examines logical consistency, feature completeness, user flows, missing features, and business logic bugs. Returns structured JSON report.
│   ├── `prompt-inspector.md` - Prompt optimization inspector. Detects verbose non-functional content in command/agent documentation following 'rules not stories' principle. Returns structured JSON report with verbosity violations.
│   ├── `pull-analyst.md` - Post-pull advisory analyst subagent. Reads the new-commits range after a successful git pull --rebase and produces a structured semantic risk summary. Writes no grant and blocks nothing. Dispatched exclusively by /pull when HEAD actually changed.
│   ├── `push-analyst.md` - Pre-push analyst subagent. Inspects the commits-to-push range for sensitive files, divergence, and branch protection violations; writes a nonce-keyed push-analyst grant to /tmp/agentic-commit/push-analyst/. Dispatched exclusively by /push.
│   ├── `qa.md` - Quality assurance specialist for verification tasks. Receives implementation report from dev subagent, validates against success criteria, runs verification scripts, identifies issues. Returns structured verification report with pass/fail status.
│   ├── `rule-inspector.md` - Folder rule discovery agent. Analyzes Git history to discover file creation patterns, extracts folder organization rules, generates INDEX.md and README.md documentation. Returns structured JSON with discovered rules.
│   ├── `spec.md` - Three-phase spec subagent. Phase 0 = read spec, decide which agents need views (free judgment). Phase 1 = content-block extraction from full monolith (verbatim byte-slices, no section pre-filtering). Phase 2 = Gawande-style checkpoint generation. Invoked by /spec command with monolith path.
│   ├── `style-inspector.md` - Development standards auditor. Enforces /dev quality standards: no hardcoding, naming conventions, venv usage, step numbering, language, script merging, documentation conciseness. Returns structured JSON report with violations.
│   ├── `test-executor.md` - Execution specialist for test infrastructure. Executes script-based and AI instruction-based tests. Returns structured execution report with results and recommendations.
│   ├── `test-validator.md` - Validation specialist for test infrastructure. Validates test syntax, dependencies, and quality before execution. Returns structured validation report.
│   ├── `test-writer.md` - Generate pytest skeleton tests from BA-produced acceptance-criteria-<task_id>.json with pytest.fail("TEST_INCOMPLETE:...") hard-stops; manage tests/generated/manifest.json with UPDATE vs CREATE logic keyed on ac_uid hashes. Triggered by /dev when complexity_tier >= STANDARD or any tier with risk_level = high (per spec-20260518-225715 §5.2).
│   ├── `ui-specialist.md` - UI/UX review specialist for overnight exploration. Evaluates visual design quality, aesthetic beauty, design system adherence, styling consistency, responsive design, and component quality. Returns structured JSON report with beauty score and design quality assessment. Accessibility checks are advisory.
│   └── `user.md` - End-user simulation specialist for overnight exploration. Tests actual usage scenarios, checks if things work as expected, identifies UX friction, broken flows, and confusing behavior. Returns structured JSON report.
├── commands/
│   ├── `allow.md` - Single-use break-glass — bypass all safety blocks for the next matching bash command this turn. /allow = anything; /allow --tool <pattern> = explicit pattern (regex auto-detected). Trailing tokens become an audit-log comment. Auto-expires at stop.
│   ├── `checkpoint.md` - Checkpoint Command
│   ├── `clean.md` - Aggressive project cleanup - normalize docs structure, archive everything, delete one-time scripts/tests. Pass --codex to enable adversarial codex consultation on cleanliness-inspector and style-inspector; default is self-review only.
│   ├── `close.md` - Close the current dev cycle (agent infers task-id from conversation). QA evaluates Workflow Integrity bullets and returns CLOSE YES/NO. Pass --codex to enable multi-round QA-codex debate; default is QA-only single-round assessment. Append --force to skip the debate entirely.
│   ├── `code-review.md` - Comprehensive code review with best practices analysis
│   ├── `codex.md` - Delegate a task to OpenAI Codex CLI (gpt-5.5, xhigh reasoning) for a second opinion or parallel coding
│   ├── `commit.md` - Commit session changes via changelog-analyst subagent
│   ├── `deep-search.md` - Deep website exploration with iterative search strategy
│   ├── `dev-command.md` - Enhanced development workflow with BA subagent delegation, command development best practices, Three-Party Architecture, and comprehensive automation patterns
│   ├── `dev-overnight.md` - Autonomous overnight development loop - continuously explores codebase, finds issues, fixes them, and repeats until end-time
│   ├── `dev.md` - Orchestrated development workflow with BA subagent delegation, parallel agent execution, and iterative QA verification. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
│   ├── `do.md` - Allow main agent to bypass orchestrator-gate restrictions for this turn (subagent-only operations become directly allowed). Auto-clears at stop.
│   ├── `doc-gen.md` - Generate comprehensive documentation for code
│   ├── `doc-sync.md` - Regenerate all INDEX.md files and patch CLAUDE.md auto-sections
│   ├── `explain-code.md` - Deep explanation of code functionality and design
│   ├── `file-analyze.md` - Analyze PDF, Excel, Word, images and other files with deep insights
│   ├── `fswatch.md` - FSWatch Command
│   ├── `merge.md` - Merge the current overnight worktree branch into the default branch (agent infers branch from active overnight state). Bare /merge typical; explicit /merge <branch> overrides. Auto-cleans worktree + branch + overnight-state file when merge succeeds and the diff is clean.
│   ├── `optimize.md` - Analyze code for performance optimization opportunities
│   ├── `playwright-helper.md` - Guide for using Playwright MCP with deep search commands
│   ├── `pull.md` - Pull Command
│   ├── `push.md` - Push Command
│   ├── `quick-commit.md` - Create a well-formatted git commit with auto-generated message
│   ├── `quick-prototype.md` - Rapidly create interactive prototypes and demos combining multiple artifact capabilities
│   ├── `redev.md` - dev workflow, context-light invocation — same task semantics as /dev, but assumes the /dev workflow instructions are already loaded. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
│   ├── `refactor.md` - Suggest refactoring improvements for code quality
│   ├── `reflect-search.md` - Reflection-driven iterative search with goal evaluation
│   ├── `research-deep.md` - Multi-source deep research with 15-20 iterative searches
│   ├── `search-tree.md` - Tree search exploration with MCTS-inspired path evaluation
│   ├── `security-check.md` - Security vulnerability analysis and recommendations
│   ├── `site-navigate.md` - Intelligent site navigation simulating "click-through" exploration
│   ├── `spec-update.md` - Continuation spec update or temp session note (was /update then /spec-continue — renamed to avoid collision with MAP's /update portfolio mutation command)
│   ├── `spec.md` - Create spec files for any dev workflow (/dev, /dev-overnight, or standalone reference). Pass --codex to enable adversarial codex consultation on each spec-subagent / QA dispatch; default is self-review only.
│   ├── `stop.md` - Cancel active overnight time-lock + workflow-enforce so the session can terminate normally. User-invoked only — agents cannot self-stop.
│   └── `test.md` - Test validation workflow with edge case detection, systematic validation, and quality enforcement
├── docs/
│   ├── clean/
│   │   ├── `cleanliness-report-clean-20260107-101825.json` - json config
│   │   ├── `cleanliness-report-clean-20260108-130050.json` - json config
│   │   ├── `cleanliness-report-clean-20260517-102341.json` - json config
│   │   ├── `cleanup-execution-clean-20260107-101825.json` - json config
│   │   ├── `cleanup-execution-clean-20260517-102341.json` - json config
│   │   ├── `combined-report-clean-20260107-101825.json` - json config
│   │   ├── `combined-report-clean-20260517-102341.json` - json config
│   │   ├── `completion-20251226-115500.md` - Development Completion Report
│   │   ├── `completion-clean-20260107-101825.md` - Cleanup Completion Report
│   │   ├── `completion-clean-20260108-130050.md` - Cleanup Completion Report
│   │   ├── `completion-clean-20260517-102341.md` - Clean Cycle Completion — clean-20260517-102341
│   │   ├── `context-clean-20260107-101825.json` - json config
│   │   ├── `context-clean-20260108-130050.json` - json config
│   │   ├── `context-clean-20260517-102341.json` - json config
│   │   ├── `dev-subagent-violations-fix-20251228.md` - Dev Subagent Quality Standard Violations - Fixed
│   │   ├── `freshness-analysis-20260108-130050.json` - json config
│   │   ├── `freshness-clean-20260517-102341.json` - json config
│   │   ├── `readme-generation-20260108-130050.json` - json config
│   │   ├── `rule-context-clean-20260108-130050.json` - json config
│   │   ├── `rule-context-clean-20260517-102341.json` - json config
│   │   ├── `rule-inspector-summary.md` - Rule Inspector Summary
│   │   ├── `rule-report-clean-20260108-130050.json` - json config
│   │   ├── `rule-report-clean-20260517-102341.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group1.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group10.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group11.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group12.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group13.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group2.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group3.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group4.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group5.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group6.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group7.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group8.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-group9.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupA1.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupA2.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupA3.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupA4.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupC1.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupC2.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupC3.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupC4.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupC6.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupC7.json` - json config
│   │   ├── `style-partial-clean-20260517-102341-groupC8.json` - json config
│   │   ├── `style-plan-clean-20260517-102341.json` - json config
│   │   ├── `style-report-clean-20260107-101825.json` - json config
│   │   ├── `style-report-clean-20260108-130050.json` - json config
│   │   ├── `style-report-clean-20260517-102341.json` - json config
│   │   ├── `style-report-extended-clean-20260517-102341.json` - json config
│   │   ├── `user-approvals-clean-20260107-101825.json` - json config
│   │   └── `user-approvals-clean-20260517-102341.json` - json config
│   ├── codex/
│   │   ├── 20260524-122910/
│   │   ├── 20260524-122947/
│   │   ├── 20260524-123039/
│   │   ├── 20260524-125300/
│   │   ├── 20260524-125300-A/
│   │   ├── 20260524-125300-B/
│   │   ├── 20260524-125300-C/
│   │   ├── 20260524-125300-C-stubs/
│   │   ├── 20260524-133650/
│   │   ├── 20260524-171714/
│   │   ├── 20260524-172805/
│   │   ├── 20260524-205206/
│   │   ├── 20260525-050824/
│   │   ├── 20260525-095242/
│   │   ├── 20260525-095245/
│   │   ├── 20260526-042454/
│   │   ├── 20260526-052559/
│   │   ├── 20260526-053746/
│   │   ├── 20260526-202532/
│   │   ├── 20260527-054705/
│   │   ├── 20260529-080709/
│   │   ├── 20260529-210616/
│   │   ├── 20260530-081334/
│   │   ├── 20260530-170350/
│   │   ├── 20260604-204954/
│   │   ├── 20260611-100500/
│   │   ├── 20260614-093452/
│   │   ├── 20260615-094546/
│   │   ├── 20260615-125319/
│   │   ├── 20260615-151335/
│   │   ├── 20260616-dehardcode/
│   │   ├── dev-20260524-205811/
│   │   ├── dev-20260525-053326/
│   │   ├── dev-20260525-053326-A/
│   │   ├── dev-20260525-053326-F/
│   │   ├── dev-20260526-200855/
│   │   ├── dev-20260526-203808/
│   │   ├── dev-20260526-203808-issubagent/
│   │   ├── dev-20260526-203808-manifest/
│   │   ├── dev-20260527-063758-T1/
│   │   ├── dev-20260527-063758-T3/
│   │   ├── dev-20260527-063758-T4/
│   │   ├── dev-20260529-081000/
│   │   ├── dev-20260529-092512/
│   │   ├── dev-20260529-210759/
│   │   ├── dev-20260531-193000/
│   │   ├── dev-20260610-205358/
│   │   ├── dev-20260615-213842/
│   │   ├── dev-20260616-204226/
│   │   ├── do-20260602-150727/
│   │   └── overnight-master-hardening/
│   ├── dev/
│   │   ├── specs/
│   │   ├── `acceptance-criteria-20260519-132417.json` - json config
│   │   ├── `acceptance-criteria-20260520-085647-d1722b.json` - json config
│   │   ├── `acceptance-criteria-20260520-221452.json` - json config
│   │   ├── `acceptance-criteria-20260521-090100.json` - json config
│   │   ├── `acceptance-criteria-20260521-090200.json` - json config
│   │   ├── `acceptance-criteria-20260521-090300.json` - json config
│   │   ├── `acceptance-criteria-20260522-000000.json` - json config
│   │   ├── `acceptance-criteria-20260522-080646-A.json` - json config
│   │   ├── `acceptance-criteria-20260522-080646-B.json` - json config
│   │   ├── `acceptance-criteria-20260522-080646-D.json` - json config
│   │   ├── `acceptance-criteria-20260524-101700-A.json` - json config
│   │   ├── `acceptance-criteria-20260524-101700-B.json` - json config
│   │   ├── `acceptance-criteria-20260524-101700-D.json` - json config
│   │   ├── `acceptance-criteria-20260524-101700-H.json` - json config
│   │   ├── `acceptance-criteria-20260524-122910.json` - json config
│   │   ├── `acceptance-criteria-20260524-122947.json` - json config
│   │   ├── `acceptance-criteria-20260524-123039.json` - json config
│   │   ├── `acceptance-criteria-20260524-125300-A.json` - json config
│   │   ├── `acceptance-criteria-20260524-125300-B.json` - json config
│   │   ├── `acceptance-criteria-20260524-125300-C.json` - json config
│   │   ├── `acceptance-criteria-20260524-125300-D.json` - json config
│   │   ├── `acceptance-criteria-20260524-125300-push.json` - json config
│   │   ├── `acceptance-criteria-20260524-133650.json` - json config
│   │   ├── `acceptance-criteria-20260524-171714.json` - json config
│   │   ├── `acceptance-criteria-20260524-172805.json` - json config
│   │   ├── `acceptance-criteria-20260524-205206.json` - json config
│   │   ├── `acceptance-criteria-20260524-205459.json` - json config
│   │   ├── `acceptance-criteria-20260525-050824.json` - json config
│   │   ├── `acceptance-criteria-20260525-095242.json` - json config
│   │   ├── `acceptance-criteria-20260525-095245.json` - json config
│   │   ├── `acceptance-criteria-20260526-042454.json` - json config
│   │   ├── `acceptance-criteria-20260526-052559.json` - json config
│   │   ├── `acceptance-criteria-20260526-053746.json` - json config
│   │   ├── `acceptance-criteria-20260526-202532.json` - json config
│   │   ├── `acceptance-criteria-20260527-054705.json` - json config
│   │   ├── `acceptance-criteria-20260527-132200.json` - json config
│   │   ├── `acceptance-criteria-20260529-080709.json` - json config
│   │   ├── `acceptance-criteria-20260529-081014.json` - json config
│   │   ├── `acceptance-criteria-20260529-164939.json` - json config
│   │   ├── `acceptance-criteria-20260529-210616.json` - json config
│   │   ├── `acceptance-criteria-20260529-211406.json` - json config
│   │   ├── `acceptance-criteria-20260530-081334.json` - json config
│   │   ├── `acceptance-criteria-20260530-105221.json` - json config
│   │   ├── `acceptance-criteria-20260530-170350.json` - json config
│   │   ├── `acceptance-criteria-20260531-112831-bug1.json` - json config
│   │   ├── `acceptance-criteria-20260531-112831-bug2a.json` - json config
│   │   ├── `acceptance-criteria-20260531-112831-bug2b.json` - json config
│   │   ├── `acceptance-criteria-20260531-112831-gap1.json` - json config
│   │   ├── `acceptance-criteria-20260601-060455.json` - json config
│   │   ├── `acceptance-criteria-20260604-204954.json` - json config
│   │   ├── `acceptance-criteria-20260611-100500.json` - json config
│   │   ├── `acceptance-criteria-20260614-093452.json` - json config
│   │   ├── `acceptance-criteria-20260614-205834.json` - json config
│   │   ├── `acceptance-criteria-d1e94e-CYCLE2-iter1.json` - json config
│   │   ├── `acceptance-criteria-d1e94e-CYCLE2.json` - json config
│   │   ├── `acceptance-criteria-d1e94e.json` - json config
│   │   ├── `acceptance-criteria-dev-20260524-170335.json` - json config
│   │   ├── `acceptance-criteria-dev-20260524-205811.json` - json config
│   │   ├── `acceptance-criteria-dev-20260525-050935.json` - json config
│   │   ├── `acceptance-criteria-dev-20260525-053326-A.json` - json config
│   │   ├── `acceptance-criteria-dev-20260525-053326-B.json` - json config
│   │   ├── `acceptance-criteria-dev-20260525-053326-F.json` - json config
│   │   ├── `acceptance-criteria-dev-20260526-203808-issubagent.json` - json config
│   │   ├── `acceptance-criteria-dev-20260526-203808-manifest.json` - json config
│   │   ├── `acceptance-criteria-dev-20260526-203808.json` - json config
│   │   ├── `acceptance-criteria-dev-20260527-063758-T1.json` - json config
│   │   ├── `acceptance-criteria-dev-20260527-063758-T2.json` - json config
│   │   ├── `acceptance-criteria-dev-20260527-063758-T3.json` - json config
│   │   ├── `acceptance-criteria-dev-20260527-063758-T4.json` - json config
│   │   ├── `acceptance-criteria-dev-20260529-152050.json` - json config
│   │   ├── `acceptance-criteria-dev-20260529-210759.json` - json config
│   │   ├── `acceptance-criteria-dev-20260530-084735.json` - json config
│   │   ├── `acceptance-criteria-dev-20260530-144032.json` - json config
│   │   ├── `acceptance-criteria-dev-20260531-134455.json` - json config
│   │   ├── `acceptance-criteria-dev-20260531-193000.json` - json config
│   │   ├── `acceptance-criteria-dev-20260615-213842.json` - json config
│   │   ├── `acceptance-criteria-dev-20260616-204226.json` - json config
│   │   ├── `architect-report-20260517-155838.json` - json config
│   │   ├── `architect-report-20260527-061433.json` - json config
│   │   ├── `architect-report-dev-20260517-215114.json` - json config
│   │   ├── `architect-report-dev-20260525-050824.json` - json config
│   │   ├── `architect-report-dev-20260616-204226.json` - json config
│   │   ├── `architect-report-spec-20260520-221059.json` - json config
│   │   ├── `ba-qa-report-20260416-063500.json` - json config
│   │   ├── `ba-qa-report-20260416-073000.json` - json config
│   │   ├── `ba-qa-report-20260517-153856.json` - json config
│   │   ├── `ba-qa-report-20260517-155838.json` - json config
│   │   ├── `ba-qa-report-20260517-172600.json` - json config
│   │   ├── `ba-qa-report-20260517-211508.json` - json config
│   │   ├── `ba-qa-report-20260517-215114.json` - json config
│   │   ├── `ba-qa-report-20260517-222440.json` - json config
│   │   ├── `ba-qa-report-20260518-071337.json` - json config
│   │   ├── `ba-qa-report-20260518-094616.json` - json config
│   │   ├── `ba-qa-report-20260518-155948.json` - json config
│   │   ├── `ba-qa-report-20260518-214050.json` - json config
│   │   ├── `ba-qa-report-20260519-132417.json` - json config
│   │   ├── `ba-qa-report-20260519-151734-iter2.json` - json config
│   │   ├── `ba-qa-report-20260519-151734.json` - json config
│   │   ├── `ba-qa-report-20260519-161035.json` - json config
│   │   ├── `ba-qa-report-20260519-175339-iter2.json` - json config
│   │   ├── `ba-qa-report-20260519-175339-iter3.json` - json config
│   │   ├── `ba-qa-report-20260519-175339.json` - json config
│   │   ├── `ba-qa-report-20260519-211515-iter2.json` - json config
│   │   ├── `ba-qa-report-20260519-211515-iter3.json` - json config
│   │   ├── `ba-qa-report-20260519-211515.json` - json config
│   │   ├── `ba-qa-report-20260520-085647-d1722b-iter2.json` - json config
│   │   ├── `ba-qa-report-20260520-085647-d1722b-iter3.json` - json config
│   │   ├── `ba-qa-report-20260520-085647-d1722b.json` - json config
│   │   ├── `ba-qa-report-20260520-221452.json` - json config
│   │   ├── `ba-qa-report-20260521-090100.json` - json config
│   │   ├── `ba-qa-report-20260521-090200.json` - json config
│   │   ├── `ba-qa-report-20260521-090300.json` - json config
│   │   ├── `ba-qa-report-20260522-000000.json` - json config
│   │   ├── `ba-qa-report-20260522-080646-A-iter2.json` - json config
│   │   ├── `ba-qa-report-20260522-080646-A.json` - json config
│   │   ├── `ba-qa-report-20260522-080646-B.json` - json config
│   │   ├── `ba-qa-report-20260522-080646-C-iter2.json` - json config
│   │   ├── `ba-qa-report-20260522-080646-C.json` - json config
│   │   ├── `ba-qa-report-20260522-080646-D-iter2.json` - json config
│   │   ├── `ba-qa-report-20260522-080646-D-iter3.json` - json config
│   │   ├── `ba-qa-report-20260522-080646-D.json` - json config
│   │   ├── `ba-qa-report-20260522-080646-F.json` - json config
│   │   ├── `ba-qa-report-20260524-101700-A-iter2.json` - json config
│   │   ├── `ba-qa-report-20260524-101700-A.json` - json config
│   │   ├── `ba-qa-report-20260524-101700-B-iter2.json` - json config
│   │   ├── `ba-qa-report-20260524-101700-B.json` - json config
│   │   ├── `ba-qa-report-20260524-101700-D-iter2.json` - json config
│   │   ├── `ba-qa-report-20260524-101700-D.json` - json config
│   │   ├── `ba-qa-report-20260524-101700-H.json` - json config
│   │   ├── `ba-qa-report-20260524-122910.json` - json config
│   │   ├── `ba-qa-report-20260524-122947.json` - json config
│   │   ├── `ba-qa-report-20260524-123039.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-A.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-B-iter2.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-B.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-C.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-D-iter2.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-D-iter3.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-D.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-push-iter2.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-push-iter3.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-push-iter4.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-push-iter5.json` - json config
│   │   ├── `ba-qa-report-20260524-125300-push.json` - json config
│   │   ├── `ba-qa-report-20260524-133650.json` - json config
│   │   ├── `ba-qa-report-20260524-171714.json` - json config
│   │   ├── `ba-qa-report-20260524-172805.json` - json config
│   │   ├── `ba-qa-report-20260524-205206.json` - json config
│   │   ├── `ba-qa-report-20260524-205459.json` - json config
│   │   ├── `ba-qa-report-20260525-050824.json` - json config
│   │   ├── `ba-qa-report-20260525-095242.json` - json config
│   │   ├── `ba-qa-report-20260525-095245.json` - json config
│   │   ├── `ba-qa-report-20260526-042454.json` - json config
│   │   ├── `ba-qa-report-20260526-052545.json` - json config
│   │   ├── `ba-qa-report-20260526-052559.json` - json config
│   │   ├── `ba-qa-report-20260526-053746.json` - json config
│   │   ├── `ba-qa-report-20260526-202532.json` - json config
│   │   ├── `ba-qa-report-20260527-054705.json` - json config
│   │   ├── `ba-qa-report-20260527-132200-pass2.json` - json config
│   │   ├── `ba-qa-report-20260527-132200-pass3.json` - json config
│   │   ├── `ba-qa-report-20260527-132200.json` - json config
│   │   ├── `ba-qa-report-20260529-080709-pass2.json` - json config
│   │   ├── `ba-qa-report-20260529-080709-pass3.json` - json config
│   │   ├── `ba-qa-report-20260529-080709.json` - json config
│   │   ├── `ba-qa-report-20260529-164939-pass2.json` - json config
│   │   ├── `ba-qa-report-20260529-164939.json` - json config
│   │   ├── `ba-qa-report-20260529-211406.json` - json config
│   │   ├── `ba-qa-report-20260530-081334-pass2.json` - json config
│   │   ├── `ba-qa-report-20260530-081334.json` - json config
│   │   ├── `ba-qa-report-20260530-091304.json` - json config
│   │   ├── `ba-qa-report-20260530-105221-pass2.json` - json config
│   │   ├── `ba-qa-report-20260530-105221.json` - json config
│   │   ├── `ba-qa-report-20260530-170350-pass2.json` - json config
│   │   ├── `ba-qa-report-20260530-170350-pass3.json` - json config
│   │   ├── `ba-qa-report-20260530-170350-pass4.json` - json config
│   │   ├── `ba-qa-report-20260530-170350.json` - json config
│   │   ├── `ba-qa-report-20260531-112831-bug1.json` - json config
│   │   ├── `ba-qa-report-20260531-112831-bug2b.json` - json config
│   │   ├── `ba-qa-report-20260601-060455.json` - json config
│   │   ├── `ba-qa-report-20260604-204954.json` - json config
│   │   ├── `ba-qa-report-20260611-100500.json` - json config
│   │   ├── `ba-qa-report-20260614-093452.json` - json config
│   │   ├── `ba-qa-report-20260614-205834.json` - json config
│   │   ├── `ba-qa-report-d1e94e-CYCLE2-iter1.json` - json config
│   │   ├── `ba-qa-report-d1e94e.json` - json config
│   │   ├── `ba-qa-report-dev-20260524-170335.json` - json config
│   │   ├── `ba-qa-report-dev-20260525-050935.json` - json config
│   │   ├── `ba-qa-report-dev-20260526-203808-manifest.json` - json config
│   │   ├── `ba-qa-report-dev-20260526-203808.json` - json config
│   │   ├── `ba-qa-report-dev-20260527-063758-T1.json` - json config
│   │   ├── `ba-qa-report-dev-20260527-063758-T2.json` - json config
│   │   ├── `ba-qa-report-dev-20260527-063758-T3.json` - json config
│   │   ├── `ba-qa-report-dev-20260527-063758-T4-pass5.json` - json config
│   │   ├── `ba-qa-report-dev-20260527-063758-T4.json` - json config
│   │   ├── `ba-qa-report-dev-20260529-081000.json` - json config
│   │   ├── `ba-qa-report-dev-20260529-092512-pass2.json` - json config
│   │   ├── `ba-qa-report-dev-20260529-092512.json` - json config
│   │   ├── `ba-qa-report-dev-20260529-152050.json` - json config
│   │   ├── `ba-qa-report-dev-20260529-210759.json` - json config
│   │   ├── `ba-qa-report-dev-20260530-084735.json` - json config
│   │   ├── `ba-qa-report-dev-20260530-144032.json` - json config
│   │   ├── `ba-qa-report-dev-20260531-134455.json` - json config
│   │   ├── `ba-qa-report-dev-20260531-193000.json` - json config
│   │   ├── `ba-qa-report-dev-20260615-213842.json` - json config
│   │   ├── `ba-qa-report-dev-20260616-204226.json` - json config
│   │   ├── `ba-report-spec-20260520-221059.json` - json config
│   │   ├── `cleanliness-inspector-report-005efeec-bb32-4361-ad8e-21e673e7f61d.json` - json config
│   │   ├── `cleanliness-inspector-report-20260517-153856.json` - json config
│   │   ├── `cleanliness-inspector-report-20260517-155838.json` - json config
│   │   ├── `cleanliness-inspector-report-20260517-172600.json` - json config
│   │   ├── `cleanliness-inspector-report-20260517-211508.json` - json config
│   │   ├── `cleanliness-inspector-report-20260517-214922.json` - json config
│   │   ├── `cleanliness-inspector-report-20260517-215114.json` - json config
│   │   ├── `cleanliness-inspector-report-20260517-222440.json` - json config
│   │   ├── `cleanliness-inspector-report-20260518-071337.json` - json config
│   │   ├── `cleanliness-inspector-report-20260518-094616.json` - json config
│   │   ├── `cleanliness-inspector-report-20260518-155948.json` - json config
│   │   ├── `cleanliness-inspector-report-20260518-214050.json` - json config
│   │   ├── `cleanliness-inspector-report-20260519-132417.json` - json config
│   │   ├── `cleanliness-inspector-report-20260519-151734.json` - json config
│   │   ├── `cleanliness-inspector-report-20260519-161035.json` - json config
│   │   ├── `cleanliness-inspector-report-20260519-175339.json` - json config
│   │   ├── `cleanliness-inspector-report-20260519-211515-recheck.json` - json config
│   │   ├── `cleanliness-inspector-report-20260519-211515.json` - json config
│   │   ├── `cleanliness-inspector-report-20260520-085647-d1722b.json` - json config
│   │   ├── `cleanliness-inspector-report-20260520-221452.json` - json config
│   │   ├── `cleanliness-inspector-report-20260521-090100.json` - json config
│   │   ├── `cleanliness-inspector-report-20260521-090200.json` - json config
│   │   ├── `cleanliness-inspector-report-20260521-090300.json` - json config
│   │   ├── `cleanliness-inspector-report-20260522-000000.json` - json config
│   │   ├── `cleanliness-inspector-report-20260522-080646.json` - json config
│   │   ├── `cleanliness-inspector-report-20260524-122910.json` - json config
│   │   ├── `cleanliness-inspector-report-20260524-122947.json` - json config
│   │   ├── `cleanliness-inspector-report-20260524-123039.json` - json config
│   │   ├── `cleanliness-inspector-report-20260524-125300.json` - json config
│   │   ├── `cleanliness-inspector-report-20260524-133650.json` - json config
│   │   ├── `cleanliness-inspector-report-20260524-171714.json` - json config
│   │   ├── `cleanliness-inspector-report-20260524-172805.json` - json config
│   │   ├── `cleanliness-inspector-report-20260524-205206.json` - json config
│   │   ├── `cleanliness-inspector-report-20260524-205459.json` - json config
│   │   ├── `cleanliness-inspector-report-20260525-050824.json` - json config
│   │   ├── `cleanliness-inspector-report-20260525-095242.json` - json config
│   │   ├── `cleanliness-inspector-report-20260525-095245.json` - json config
│   │   ├── `cleanliness-inspector-report-20260526-042454.json` - json config
│   │   ├── `cleanliness-inspector-report-20260526-052559.json` - json config
│   │   ├── `cleanliness-inspector-report-20260526-053746.json` - json config
│   │   ├── `cleanliness-inspector-report-20260526-202532.json` - json config
│   │   ├── `cleanliness-inspector-report-20260527-054705.json` - json config
│   │   ├── `cleanliness-inspector-report-20260527-132200.json` - json config
│   │   ├── `cleanliness-inspector-report-20260529-080709.json` - json config
│   │   ├── `cleanliness-inspector-report-20260529-081014.json` - json config
│   │   ├── `cleanliness-inspector-report-20260529-164939.json` - json config
│   │   ├── `cleanliness-inspector-report-20260529-210616.json` - json config
│   │   ├── `cleanliness-inspector-report-20260529-211406.json` - json config
│   │   ├── `cleanliness-inspector-report-20260530-081334.json` - json config
│   │   ├── `cleanliness-inspector-report-20260530-091304.json` - json config
│   │   ├── `cleanliness-inspector-report-20260530-092123.json` - json config
│   │   ├── `cleanliness-inspector-report-20260530-105221.json` - json config
│   │   ├── `cleanliness-inspector-report-20260530-165718.json` - json config
│   │   ├── `cleanliness-inspector-report-20260530-170350.json` - json config
│   │   ├── `cleanliness-inspector-report-20260530-212215.json` - json config
│   │   ├── `cleanliness-inspector-report-20260531-082707.json` - json config
│   │   ├── `cleanliness-inspector-report-20260601-060455.json` - json config
│   │   ├── `cleanliness-inspector-report-20260602-210702.json` - json config
│   │   ├── `cleanliness-inspector-report-20260604-204954.json` - json config
│   │   ├── `cleanliness-inspector-report-20260606-131137.json` - json config
│   │   ├── `cleanliness-inspector-report-20260606-201330.json` - json config
│   │   ├── `cleanliness-inspector-report-20260608-215123.json` - json config
│   │   ├── `cleanliness-inspector-report-20260611-100500.json` - json config
│   │   ├── `cleanliness-inspector-report-20260614-093452.json` - json config
│   │   ├── `cleanliness-inspector-report-20260614-182549.json` - json config
│   │   ├── `cleanliness-inspector-report-20260614-205834.json` - json config
│   │   ├── `cleanliness-inspector-report-20260615-125319.json` - json config
│   │   ├── `cleanliness-inspector-report-20260616-094643.json` - json config
│   │   ├── `cleanliness-inspector-report-30fbb321-8921-44aa-bd65-de59e4c70730.json` - json config
│   │   ├── `cleanliness-inspector-report-441b0d47-3cbf-4fa5-9038-76ef39df048a.json` - json config
│   │   ├── `cleanliness-inspector-report-44e208af-b8b8-4266-a2ba-fcfc77f92d24.json` - json config
│   │   ├── `cleanliness-inspector-report-77be7954-cf76-4fea-a146-5cb88f32a69f.json` - json config
│   │   ├── `cleanliness-inspector-report-8cfdc493-794f-4367-941b-2e2a150db230.json` - json config
│   │   ├── `cleanliness-inspector-report-c2667fea-a84e-4ba8-9dc7-fae4c1abfc24.json` - json config
│   │   ├── `cleanliness-inspector-report-c7452b2d-d6dd-4fa6-b61a-f0642a46c906.json` - json config
│   │   ├── `cleanliness-inspector-report-cc7a706f-2662-4274-976d-d2f19e6dd767.json` - json config
│   │   ├── `cleanliness-inspector-report-d1e94e.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260524-170335.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260524-205811.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260525-050935.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260525-053326.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260526-044731.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260526-200855.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260526-203808-manifest.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260526-203808.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260527-063758.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260529-081000.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260529-092512.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260529-152050.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260529-210759.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260530-084735.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260530-144032.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260531-134455.json` - json config
│   │   ├── `cleanliness-inspector-report-dev-20260531-193000.json` - json config
│   │   ├── `cleanliness-inspector-report-do-20260529-210815.json` - json config
│   │   ├── `cleanliness-inspector-report-do-20260530-165637.json` - json config
│   │   ├── `cleanliness-inspector-report-do-20260531-111311.json` - json config
│   │   ├── `cleanliness-inspector-report-do-20260531-171010.json` - json config
│   │   ├── `cleanliness-inspector-report-do-20260602-150727.json` - json config
│   │   ├── `cleanliness-inspector-report-do-20260603-084448.json` - json config
│   │   ├── `cleanliness-inspector-report-eeeabad1-554e-4a04-a040-149797afaed7.json` - json config
│   │   ├── `close-debate-20260518-214050.json` - json config
│   │   ├── `close-debate-20260526-052559.md` - Close Debate Transcript -- 20260526-052559
│   │   ├── `close-debate-20260526-053746.md` - Close Debate Transcript — 20260526-053746
│   │   ├── `close-report-005efeec-bb32-4361-ad8e-21e673e7f61d.md` - Close Report — 005efeec-bb32-4361-ad8e-21e673e7f61d
│   │   ├── `close-report-20260510-115954.md` - Close Debate Report (mirror for dot-claude commit.sh admission)
│   │   ├── `close-report-20260510-191533.md` - Close Debate Report
│   │   ├── `close-report-20260511-094500.md` - Close Report — 20260511-094500
│   │   ├── `close-report-20260511-180000.md` - Close Report — 20260511-180000
│   │   ├── `close-report-20260517-153856.md` - Close Debate Report
│   │   ├── `close-report-20260517-155838.md` - Close Debate Report
│   │   ├── `close-report-20260517-172600.md` - Close Debate Report
│   │   ├── `close-report-20260517-211508.md` - Close Report — 20260517-211508
│   │   ├── `close-report-20260517-214922.md` - Close Debate Report — 20260517-214922
│   │   ├── `close-report-20260517-215114.md` - Close Report — 20260517-215114
│   │   ├── `close-report-20260517-222440.md` - Close Debate — 20260517-222440 (MULTI-ROUND, codex_required: true)
│   │   ├── `close-report-20260518-071337.md` - Close Report — 20260518-071337
│   │   ├── `close-report-20260518-094616.md` - Close Debate Report — 20260518-094616
│   │   ├── `close-report-20260518-155948.md` - Close Report — 20260518-155948
│   │   ├── `close-report-20260518-214050.md` - Close Debate Report
│   │   ├── `close-report-20260519-132417.md` - Close Debate Report
│   │   ├── `close-report-20260519-151734.md` - Close Debate Report
│   │   ├── `close-report-20260519-161035.md` - Close Debate Report — 20260519-161035
│   │   ├── `close-report-20260519-175339.md` - Close Report — 20260519-175339
│   │   ├── `close-report-20260519-211515.md` - Close Report — task-id 20260519-211515
│   │   ├── `close-report-20260520-085647-d1722b.md` - Close Debate Report
│   │   ├── `close-report-20260520-221452.md` - Close Debate Report (RE-EVALUATION)
│   │   ├── `close-report-20260521-090100.md` - Close Debate Report
│   │   ├── `close-report-20260521-090200.md` - Close Debate Report
│   │   ├── `close-report-20260521-090300.md` - Close Debate Report
│   │   ├── `close-report-20260522-000000.md` - Close Debate Report
│   │   ├── `close-report-20260522-080646.md` - Close Debate Report
│   │   ├── `close-report-20260524-101700.md` - Close Debate Report — 20260524-101700
│   │   ├── `close-report-20260524-122910.md` - Close Report — Task 20260524-122910
│   │   ├── `close-report-20260524-122947.md` - Close Report: task 20260524-122947
│   │   ├── `close-report-20260524-123039.md` - Close Report: task 20260524-123039
│   │   ├── `close-report-20260524-125300.md` - Close Debate Report
│   │   ├── `close-report-20260524-133650.md` - Close Debate Report — Task 20260524-133650
│   │   ├── `close-report-20260524-171714.md` - Close Report: task 20260524-171714
│   │   ├── `close-report-20260524-172805.md` - Close Report — Task 20260524-172805
│   │   ├── `close-report-20260524-205459.md` - Close Report: task 20260524-205459
│   │   ├── `close-report-20260524-allow-gaps.md` - Close Debate Report (FORCED)
│   │   ├── `close-report-20260525-050824.md` - Close Report — Task 20260525-050824
│   │   ├── `close-report-20260525-095242.md` - Close Report: 20260525-095242 (Cycle 6 — Layer 1.F compound-command bypass fix)
│   │   ├── `close-report-20260525-095245.md` - Close Report — Task 20260525-095245
│   │   ├── `close-report-20260526-042454.md` - Close Report — Task 20260526-042454
│   │   ├── `close-report-20260526-052559.md` - Close Debate Report
│   │   ├── `close-report-20260526-053746.md` - Close Report -- 20260526-053746
│   │   ├── `close-report-20260526-202532.md` - Close Report: 20260526-202532
│   │   ├── `close-report-20260527-054705.md` - Close Report: 20260527-054705
│   │   ├── `close-report-20260527-132200.md` - Close Report — 20260527-132200
│   │   ├── `close-report-20260527-133200.md` - Close Report — 20260527-133200
│   │   ├── `close-report-20260529-080709.md` - Close Report — Task 20260529-080709
│   │   ├── `close-report-20260529-081014.md` - Close Report — dev-20260529-081014
│   │   ├── `close-report-20260529-164939.md` - Close Report — 20260529-164939
│   │   ├── `close-report-20260529-210616.md` - Close-debate Transcript — 20260529-210616
│   │   ├── `close-report-20260529-211406.md` - Close Debate Report
│   │   ├── `close-report-20260530-081334.md` - Close Report — Task 20260530-081334
│   │   ├── `close-report-20260530-084303.md` - Close Debate Report — 20260530-084303
│   │   ├── `close-report-20260530-091304.md` - Close Report — 20260530-091304
│   │   ├── `close-report-20260530-105221.md` - Close Report — 20260530-105221
│   │   ├── `close-report-20260530-112914.md` - Close Debate Report (FORCED)
│   │   ├── `close-report-20260530-170350.md` - Close Debate Report — 20260530-170350
│   │   ├── `close-report-20260530-170414.md` - Close Debate Report (FORCED)
│   │   ├── `close-report-20260530-212215.md` - Close Debate Report
│   │   ├── `close-report-20260531-082707.md` - Close Debate Report
│   │   ├── `close-report-20260601-060455.md` - Close Report — task 20260601-060455
│   │   ├── `close-report-20260602-210702.md` - Close Report — Task 20260602-210702
│   │   ├── `close-report-20260604-204954.md` - Close Report — task-id 20260604-204954
│   │   ├── `close-report-20260606-131137.md` - Close Report — Task-id 20260606-131137
│   │   ├── `close-report-20260606-201330.md` - Close Report — 20260606-201330
│   │   ├── `close-report-20260611-100500.md` - Close Report — task-id 20260611-100500
│   │   ├── `close-report-20260614-093452.md` - Close Report — 20260614-093452
│   │   ├── `close-report-20260614-182549.md` - Close Debate Report
│   │   ├── `close-report-20260614-205834.md` - Close Debate Report
│   │   ├── `close-report-20260615-125319.md` - Close Debate Report
│   │   ├── `close-report-20260616-094643.md` - Close Debate Report
│   │   ├── `close-report-30fbb321-8921-44aa-bd65-de59e4c70730.md` - Close Report — /do cycle 30fbb321-8921-44aa-bd65-de59e4c70730
│   │   ├── `close-report-441b0d47-3cbf-4fa5-9038-76ef39df048a.md` - Close Debate Report
│   │   ├── `close-report-44e208af-b8b8-4266-a2ba-fcfc77f92d24.md` - Close Report — 44e208af-b8b8-4266-a2ba-fcfc77f92d24
│   │   ├── `close-report-77be7954-cf76-4fea-a146-5cb88f32a69f.md` - Close Debate Report
│   │   ├── `close-report-8cfdc493-794f-4367-941b-2e2a150db230.md` - Close Report — 8cfdc493-794f-4367-941b-2e2a150db230
│   │   ├── `close-report-c2667fea-a84e-4ba8-9dc7-fae4c1abfc24.md` - Close Report — c2667fea-a84e-4ba8-9dc7-fae4c1abfc24
│   │   ├── `close-report-c7452b2d-d6dd-4fa6-b61a-f0642a46c906.md` - Close Report — Task c7452b2d-d6dd-4fa6-b61a-f0642a46c906
│   │   ├── `close-report-cc7a706f-2662-4274-976d-d2f19e6dd767.md` - Close Debate Report
│   │   ├── `close-report-d1e94e-prior.md` - Close Debate Report
│   │   ├── `close-report-d1e94e.md` - Close Debate Report — d1e94e
│   │   ├── `close-report-dev-20260524-170335.md` - Close Debate Report
│   │   ├── `close-report-dev-20260524-205811.md` - Close Debate Report (FORCED)
│   │   ├── `close-report-dev-20260525-050824.md` - Close Debate Report (FORCED)
│   │   ├── `close-report-dev-20260525-050935.md` - Close Debate Report
│   │   ├── `close-report-dev-20260525-053326.md` - Close Debate Report
│   │   ├── `close-report-dev-20260526-044731.md` - Close Debate — dev-20260526-044731
│   │   ├── `close-report-dev-20260526-200855.md` - Close Debate Report: dev-20260526-200855
│   │   ├── `close-report-dev-20260526-203808-manifest.md` - Close Debate Report — dev-20260526-203808-manifest
│   │   ├── `close-report-dev-20260526-203808.md` - Close Debate Transcript — dev-20260526-203808
│   │   ├── `close-report-dev-20260529-081000.md` - Close Report — dev-20260529-081000
│   │   ├── `close-report-dev-20260529-092512.md` - Close Report — dev-20260529-092512
│   │   ├── `close-report-dev-20260529-152050.md` - Close Debate Report
│   │   ├── `close-report-dev-20260529-210759.md` - Close Report — dev-20260529-210759 (RE-EVALUATION after security fix)
│   │   ├── `close-report-dev-20260530-084735.md` - Close Report — dev-20260530-084735
│   │   ├── `close-report-dev-20260530-144032.md` - Close Debate Report
│   │   ├── `close-report-dev-20260531-134455.md` - Close Debate Report — dev-20260531-134455
│   │   ├── `close-report-dev-20260531-193000.md` - Close Debate Report — dev-20260531-193000
│   │   ├── `close-report-do-20260525-050636.md` - Close Debate Report (FORCED)
│   │   ├── `close-report-do-20260529-210815.md` - Close Report — do-20260529-210815
│   │   ├── `close-report-do-20260531-111311.md` - Close Report — Task do-20260531-111311
│   │   ├── `close-report-do-20260531-171010.md` - Close Report — do-20260531-171010
│   │   ├── `close-report-do-20260602-150727.md` - Close Report — do-20260602-150727
│   │   ├── `close-report-do-20260603-084448.md` - Close Report — do-20260603-084448
│   │   ├── `close-report-eeeabad1-554e-4a04-a040-149797afaed7.md` - Close Report — eeeabad1-554e-4a04-a040-149797afaed7
│   │   ├── `commit-manifest-20260509-114002-cycle4.json` - json config
│   │   ├── `commit-message-dev-20260615-213842.txt` - txt file
│   │   ├── `commit-qa-report-20260606-131137.md` - Pre-commit QA Gate Report — TASK_ID 20260606-131137
│   │   ├── `commit-qa-report-20260606-201330.md` - Commit QA Report — TASK_ID 20260606-201330
│   │   ├── `commit-qa-report-20260611-100500.md` - Commit-QA Gate Report — task 20260611-100500
│   │   ├── `commit-qa-report-20260614-182549.md` - Pre-Commit QA Report — 20260614-182549
│   │   ├── `commit-qa-report-20260614-205834.md` - Commit-QA Report — TASK_ID 20260614-205834
│   │   ├── `commit-qa-report-20260616-094643.md` - Commit QA Report — TASK_ID 20260616-094643
│   │   ├── `commit-qa-report-77be7954-cf76-4fea-a146-5cb88f32a69f.md` - Pre-Commit QA Report — TASK 77be7954-cf76-4fea-a146-5cb88f32a69f
│   │   ├── `completion-20260510-191533.md` - Development Completion Report — 20260510-191533
│   │   ├── `completion-20260511-094500.md` - Development Completion Report — 20260511-094500
│   │   ├── `completion-20260511-180000.md` - Development Completion Report — 20260511-180000
│   │   ├── `completion-20260517-153856.md` - Development Completion Report — 20260517-153856
│   │   ├── `completion-20260517-155838.md` - Development Completion Report — 20260517-155838
│   │   ├── `completion-20260517-172600.md` - Development Completion Report — 20260517-172600
│   │   ├── `completion-20260517-211508.md` - Development Completion Report — 20260517-211508
│   │   ├── `completion-20260517-215114.md` - Development Completion Report — 20260517-215114
│   │   ├── `completion-20260517-222440.md` - Development Completion Report — 20260517-222440
│   │   ├── `completion-20260518-071337.md` - Development Completion Report — 20260518-071337
│   │   ├── `completion-20260518-094616.md` - Development Completion Report — 20260518-094616
│   │   ├── `completion-20260518-155948.md` - Development Completion Report — 20260518-155948
│   │   ├── `completion-20260519-132417.md` - Development Completion Report — 20260519-132417
│   │   ├── `completion-20260519-151734.md` - Development Completion Report — 20260519-151734
│   │   ├── `completion-20260519-161035.md` - Development Completion Report — 20260519-161035
│   │   ├── `completion-20260519-175339.md` - Development Completion Report — 20260519-175339
│   │   ├── `completion-20260519-211515-redev9items.md` - Development Completion Report — 20260519-211515 (redev 9-item retrospective)
│   │   ├── `completion-20260519-211515.md` - Development Completion Report — 20260519-211515
│   │   ├── `completion-20260520-085647-d1722b.md` - Development Completion Report — 20260520-085647-d1722b
│   │   ├── `completion-20260520-221452.md` - Development Completion Report — 20260520-221452
│   │   ├── `completion-20260521-090100.md` - Development Completion Report — 20260521-090100
│   │   ├── `completion-20260521-090200.md` - Development Completion Report — 20260521-090200
│   │   ├── `completion-20260521-090300.md` - Development Completion Report — 20260521-090300
│   │   ├── `completion-20260522-000000.md` - Dev Cycle Completion Report
│   │   ├── `completion-20260522-080646.md` - Dev Cycle Completion — 20260522-080646
│   │   ├── `completion-20260524-101700.md` - Dev Completion — 20260524-101700
│   │   ├── `completion-20260524-122910.md` - Development Completion Report -- 20260524-122910
│   │   ├── `completion-20260524-122947.md` - Development Completion Report — 20260524-122947
│   │   ├── `completion-20260524-123039.md` - Dev Cycle Completion Report
│   │   ├── `completion-20260524-125300.md` - Completion Report — Cycle 20260524-125300
│   │   ├── `completion-20260524-133650.md` - Completion Report
│   │   ├── `completion-20260524-171714.md` - Dev Cycle Completion Report
│   │   ├── `completion-20260524-172805.md` - Development Completion Report -- 20260524-172805
│   │   ├── `completion-20260524-205206.md` - Development Completion Report -- 20260524-205206
│   │   ├── `completion-20260524-205459.md` - Dev Cycle Completion Report
│   │   ├── `completion-20260525-050824.md` - Completion Report: task 20260525-050824
│   │   ├── `completion-20260525-095242.md` - Development Completion Report -- 20260525-095242
│   │   ├── `completion-20260525-095245.md` - Completion Report: task 20260525-095245
│   │   ├── `completion-20260526-042454.md` - Completion Report — Task 20260526-042454
│   │   ├── `completion-20260526-052559.md` - Development Completion Report — 20260526-052559
│   │   ├── `completion-20260526-053746.md` - Development Completion Report -- 20260526-053746
│   │   ├── `completion-20260527-054705.md` - Development Completion Report -- 20260527-054705
│   │   ├── `completion-20260527-132200.md` - Completion Report — 20260527-132200
│   │   ├── `completion-20260529-080709.md` - Completion Report — 20260529-080709
│   │   ├── `completion-20260529-081014.md` - Development Completion Report -- 20260529-081014
│   │   ├── `completion-20260529-164939.md` - Completion Report — 20260529-164939
│   │   ├── `completion-20260529-210616.md` - Development Completion Report -- 20260529-210616
│   │   ├── `completion-20260529-211406.md` - Development Completion Report — 20260529-211406
│   │   ├── `completion-20260530-081334.md` - Completion Report — 20260530-081334
│   │   ├── `completion-20260530-091304.md` - Development Completion Report — 20260530-091304
│   │   ├── `completion-20260530-105221.md` - Completion Report — 20260530-105221
│   │   ├── `completion-20260530-170350.md` - Completion Report — 20260530-170350
│   │   ├── `completion-20260531-162901.md` - 20260531-162901 — project-name-free daemon-protection guard engine
│   │   ├── `completion-20260601-060455.md` - Development Completion Report
│   │   ├── `completion-20260604-204954.md` - Development Completion Report — 20260604-204954
│   │   ├── `completion-20260611-100500.md` - 20260611-100500 — Harden /dev-overnight so an overnight session can NEVER touch master
│   │   ├── `completion-20260614-093452.md` - Development Completion Report — 20260614-093452
│   │   ├── `completion-20260614-205834.md` - Development Completion Report — 20260614-205834
│   │   ├── `completion-d1e94e.md` - Development Completion Report — d1e94e
│   │   ├── `completion-dev-20260524-170335.md` - Completion Report: dev-20260524-170335
│   │   ├── `completion-dev-20260524-205811.md` - Completion Report
│   │   ├── `completion-dev-20260525-050935.md` - Dev Cycle Completion Report
│   │   ├── `completion-dev-20260525-053326.md` - Completion Report
│   │   ├── `completion-dev-20260526-044731.md` - Completion Report
│   │   ├── `completion-dev-20260526-200855.md` - Completion Report: dev-20260526-200855
│   │   ├── `completion-dev-20260526-203808-manifest.md` - Development Completion Report — dev-20260526-203808-manifest
│   │   ├── `completion-dev-20260526-203808.md` - Development Completion Report — dev-20260526-203808
│   │   ├── `completion-dev-20260527-063758.md` - Completion Report — dev-20260527-063758
│   │   ├── `completion-dev-20260529-081000.md` - Completion Report — dev-20260529-081000
│   │   ├── `completion-dev-20260529-092512.md` - Completion Report — dev-20260529-092512
│   │   ├── `completion-dev-20260529-152050.md` - Completion Report — dev-20260529-152050
│   │   ├── `completion-dev-20260529-210759.md` - Completion Report — dev-20260529-210759
│   │   ├── `completion-dev-20260530-084735.md` - Completion Report — dev-20260530-084735
│   │   ├── `completion-dev-20260530-144032.md` - Completion Report — dev-20260530-144032
│   │   ├── `completion-dev-20260531-134455.md` - Development Completion Report — dev-20260531-134455
│   │   ├── `completion-dev-20260531-193000.md` - Development Completion Report — dev-20260531-193000
│   │   ├── `completion-do-20260529-210815.md` - Completion Report — do-20260529-210815
│   │   ├── `context-20260416-063500.json` - json config
│   │   ├── `context-20260416-073000.json` - json config
│   │   ├── `context-20260510-191533.json` - json config
│   │   ├── `context-20260511-094500.json` - json config
│   │   ├── `context-20260511-180000.json` - json config
│   │   ├── `context-20260517-153856.json` - json config
│   │   ├── `context-20260517-155838.json` - json config
│   │   ├── `context-20260517-172600.json` - json config
│   │   ├── `context-20260517-211508.json` - json config
│   │   ├── `context-20260517-215114.json` - json config
│   │   ├── `context-20260517-222440.json` - json config
│   │   ├── `context-20260518-071337.json` - json config
│   │   ├── `context-20260518-094616.json` - json config
│   │   ├── `context-20260518-155948.json` - json config
│   │   ├── `context-20260518-214050.json` - json config
│   │   ├── `context-20260519-132417.json` - json config
│   │   ├── `context-20260519-151734.json` - json config
│   │   ├── `context-20260519-161035.json` - json config
│   │   ├── `context-20260519-175339.json` - json config
│   │   ├── `context-20260519-211515-CYCLE2-round3.json` - json config
│   │   ├── `context-20260519-211515.json` - json config
│   │   ├── `context-20260520-085647-d1722b.json` - json config
│   │   ├── `context-20260520-221452.json` - json config
│   │   ├── `context-20260521-090100.json` - json config
│   │   ├── `context-20260521-090200.json` - json config
│   │   ├── `context-20260521-090300.json` - json config
│   │   ├── `context-20260522-000000.json` - json config
│   │   ├── `context-20260522-080646-A.json` - json config
│   │   ├── `context-20260522-080646-B.json` - json config
│   │   ├── `context-20260522-080646-C.json` - json config
│   │   ├── `context-20260522-080646-D.json` - json config
│   │   ├── `context-20260522-080646-F.json` - json config
│   │   ├── `context-20260524-101700-A.json` - json config
│   │   ├── `context-20260524-101700-B.json` - json config
│   │   ├── `context-20260524-101700-D.json` - json config
│   │   ├── `context-20260524-101700-H.json` - json config
│   │   ├── `context-20260524-101700-X.json` - json config
│   │   ├── `context-20260524-101700.json` - json config
│   │   ├── `context-20260524-122910.json` - json config
│   │   ├── `context-20260524-122947.json` - json config
│   │   ├── `context-20260524-123039.json` - json config
│   │   ├── `context-20260524-125300-A.json` - json config
│   │   ├── `context-20260524-125300-B.json` - json config
│   │   ├── `context-20260524-125300-C.json` - json config
│   │   ├── `context-20260524-125300-D.json` - json config
│   │   ├── `context-20260524-125300-push.json` - json config
│   │   ├── `context-20260524-133650.json` - json config
│   │   ├── `context-20260524-171714.json` - json config
│   │   ├── `context-20260524-172805.json` - json config
│   │   ├── `context-20260524-205206.json` - json config
│   │   ├── `context-20260524-205459.json` - json config
│   │   ├── `context-20260525-050824.json` - json config
│   │   ├── `context-20260525-095242.json` - json config
│   │   ├── `context-20260525-095245.json` - json config
│   │   ├── `context-20260526-042454.json` - json config
│   │   ├── `context-20260526-052545.json` - json config
│   │   ├── `context-20260526-052559.json` - json config
│   │   ├── `context-20260526-053746.json` - json config
│   │   ├── `context-20260526-202532.json` - json config
│   │   ├── `context-20260527-054705.json` - json config
│   │   ├── `context-20260527-132200.json` - json config
│   │   ├── `context-20260527-133200.json` - json config
│   │   ├── `context-20260529-080709.json` - json config
│   │   ├── `context-20260529-081014.json` - json config
│   │   ├── `context-20260529-164939.json` - json config
│   │   ├── `context-20260529-210616.json` - json config
│   │   ├── `context-20260529-211406.json` - json config
│   │   ├── `context-20260529-211406.json.lock` - lock file
│   │   ├── `context-20260530-081334.json` - json config
│   │   ├── `context-20260530-091304.json` - json config
│   │   ├── `context-20260530-105221.json` - json config
│   │   ├── `context-20260530-170350.json` - json config
│   │   ├── `context-20260531-112831-bug1.json` - json config
│   │   ├── `context-20260531-112831-bug2a.json` - json config
│   │   ├── `context-20260531-112831-bug2b.json` - json config
│   │   ├── `context-20260531-112831-gap1.json` - json config
│   │   ├── `context-20260601-060455.json` - json config
│   │   ├── `context-20260601-060455.json.lock` - lock file
│   │   ├── `context-20260604-204954.json` - json config
│   │   ├── `context-20260604-204954.json.lock` - lock file
│   │   ├── `context-20260611-100500.json` - json config
│   │   ├── `context-20260611-100500.json.lock` - lock file
│   │   ├── `context-20260614-093452.json` - json config
│   │   ├── `context-20260614-093452.json.lock` - lock file
│   │   ├── `context-20260614-205834.json` - json config
│   │   ├── `context-20260614-205834.json.lock` - lock file
│   │   ├── `context-75463e-DH.json` - json config
│   │   ├── `context-d1e94e-CYCLE2-round2.json` - json config
│   │   ├── `context-d1e94e-CYCLE2.json` - json config
│   │   ├── `context-d1e94e.json` - json config
│   │   ├── `context-dev-20260107-091716.json` - json config
│   │   ├── `context-dev-20260107-100221.json` - json config
│   │   ├── `context-dev-20260107-104430.json` - json config
│   │   ├── `context-dev-20260108-111618.json` - json config
│   │   ├── `context-dev-20260108-153719.json` - json config
│   │   ├── `context-dev-20260108-163807.json` - json config
│   │   ├── `context-dev-20260108-164915.json` - json config
│   │   ├── `context-dev-20260110-001044.json` - json config
│   │   ├── `context-dev-20260111-193314.json` - json config
│   │   ├── `context-dev-20260524-170335.json` - json config
│   │   ├── `context-dev-20260524-205811.json` - json config
│   │   ├── `context-dev-20260525-050935.json` - json config
│   │   ├── `context-dev-20260525-053326-A.json` - json config
│   │   ├── `context-dev-20260525-053326-B.json` - json config
│   │   ├── `context-dev-20260525-053326-F.json` - json config
│   │   ├── `context-dev-20260526-044731.json` - json config
│   │   ├── `context-dev-20260526-200855.json` - json config
│   │   ├── `context-dev-20260526-203808-issubagent.json` - json config
│   │   ├── `context-dev-20260526-203808-manifest.json` - json config
│   │   ├── `context-dev-20260526-203808.json` - json config
│   │   ├── `context-dev-20260527-063758-T1.json` - json config
│   │   ├── `context-dev-20260527-063758-T2.json` - json config
│   │   ├── `context-dev-20260527-063758-T3.json` - json config
│   │   ├── `context-dev-20260527-063758-T4.json` - json config
│   │   ├── `context-dev-20260529-081000.json` - json config
│   │   ├── `context-dev-20260529-092512.json` - json config
│   │   ├── `context-dev-20260529-152050.json` - json config
│   │   ├── `context-dev-20260529-210759.json` - json config
│   │   ├── `context-dev-20260530-084735.json` - json config
│   │   ├── `context-dev-20260530-144032.json` - json config
│   │   ├── `context-dev-20260531-134455.json` - json config
│   │   ├── `context-dev-20260531-134455.json.lock` - lock file
│   │   ├── `context-dev-20260531-193000.json` - json config
│   │   ├── `context-dev-20260531-193000.json.lock` - lock file
│   │   ├── `context-dev-20260615-213842.json` - json config
│   │   ├── `context-dev-20260615-213842.json.lock` - lock file
│   │   ├── `context-dev-20260616-204226.json` - json config
│   │   ├── `context-dev-20260616-204226.json.lock` - lock file
│   │   ├── `context-do-20260529-210815.json` - json config
│   │   ├── `context-iter2-dev-20260111-193314.json` - json config
│   │   ├── `design-input-dev-20260531-134455.md` - Design Input — dev-20260531-134455
│   │   ├── `design-input-dev-20260531-193000.md` - Design Input — dev-20260531-193000
│   │   ├── `dev-report-20260110-001044.json` - json config
│   │   ├── `dev-report-20260416-063500-iter2.json` - json config
│   │   ├── `dev-report-20260416-063500.json` - json config
│   │   ├── `dev-report-20260416-073000-iter2.json` - json config
│   │   ├── `dev-report-20260416-073000.json` - json config
│   │   ├── `dev-report-20260510-115954.json` - json config
│   │   ├── `dev-report-20260510-191533.json` - json config
│   │   ├── `dev-report-20260511-094500.json` - json config
│   │   ├── `dev-report-20260511-180000.json` - json config
│   │   ├── `dev-report-20260517-153856.json` - json config
│   │   ├── `dev-report-20260517-155838.json` - json config
│   │   ├── `dev-report-20260517-172600.json` - json config
│   │   ├── `dev-report-20260517-211508.json` - json config
│   │   ├── `dev-report-20260517-215114.json` - json config
│   │   ├── `dev-report-20260517-222440.json` - json config
│   │   ├── `dev-report-20260518-071337.json` - json config
│   │   ├── `dev-report-20260518-094616.json` - json config
│   │   ├── `dev-report-20260518-155948.json` - json config
│   │   ├── `dev-report-20260518-214050-application-assistant.json` - json config
│   │   ├── `dev-report-20260518-214050-budget-management.json` - json config
│   │   ├── `dev-report-20260518-214050-dot-claude.json` - json config
│   │   ├── `dev-report-20260518-214050-excel-analyzer.json` - json config
│   │   ├── `dev-report-20260518-214050-happy.json` - json config
│   │   ├── `dev-report-20260518-214050-knowledge-system-jade.json` - json config
│   │   ├── `dev-report-20260518-214050-knowledge-system-qijie.json` - json config
│   │   ├── `dev-report-20260518-214050-knowledge-system.json` - json config
│   │   ├── `dev-report-20260518-214050-multi-asset-portfolio.json` - json config
│   │   ├── `dev-report-20260518-214050-orchestra.json` - json config
│   │   ├── `dev-report-20260518-214050-rednote-mcp.json` - json config
│   │   ├── `dev-report-20260518-214050-travel-planner.json` - json config
│   │   ├── `dev-report-20260518-214050.json` - json config
│   │   ├── `dev-report-20260519-132417.json` - json config
│   │   ├── `dev-report-20260519-151734.json` - json config
│   │   ├── `dev-report-20260519-161035.json` - json config
│   │   ├── `dev-report-20260519-175339.json` - json config
│   │   ├── `dev-report-20260519-211515-iter3.json` - json config
│   │   ├── `dev-report-20260519-211515.json` - json config
│   │   ├── `dev-report-20260520-085647-d1722b.json` - json config
│   │   ├── `dev-report-20260520-221452.json` - json config
│   │   ├── `dev-report-20260521-085554.json` - json config
│   │   ├── `dev-report-20260521-090100.json` - json config
│   │   ├── `dev-report-20260521-090200.json` - json config
│   │   ├── `dev-report-20260521-090300.json` - json config
│   │   ├── `dev-report-20260522-000000.json` - json config
│   │   ├── `dev-report-20260522-080646-A.json` - json config
│   │   ├── `dev-report-20260522-080646-B.json` - json config
│   │   ├── `dev-report-20260522-080646-C.json` - json config
│   │   ├── `dev-report-20260522-080646-D.json` - json config
│   │   ├── `dev-report-20260522-080646-F.json` - json config
│   │   ├── `dev-report-20260522-080646.json` - json config
│   │   ├── `dev-report-20260524-101700-A.json` - json config
│   │   ├── `dev-report-20260524-101700-B.json` - json config
│   │   ├── `dev-report-20260524-101700-D.json` - json config
│   │   ├── `dev-report-20260524-101700-H.json` - json config
│   │   ├── `dev-report-20260524-101700.json` - json config
│   │   ├── `dev-report-20260524-122910.json` - json config
│   │   ├── `dev-report-20260524-122947.json` - json config
│   │   ├── `dev-report-20260524-123039.json` - json config
│   │   ├── `dev-report-20260524-125300-A-stubs.json` - json config
│   │   ├── `dev-report-20260524-125300-A.json` - json config
│   │   ├── `dev-report-20260524-125300-B.json` - json config
│   │   ├── `dev-report-20260524-125300-C-stubs.json` - json config
│   │   ├── `dev-report-20260524-125300-C.json` - json config
│   │   ├── `dev-report-20260524-125300-D.json` - json config
│   │   ├── `dev-report-20260524-125300-push.json` - json config
│   │   ├── `dev-report-20260524-125300.json` - json config
│   │   ├── `dev-report-20260524-133650.json` - json config
│   │   ├── `dev-report-20260524-171714.json` - json config
│   │   ├── `dev-report-20260524-172805.json` - json config
│   │   ├── `dev-report-20260524-205206.json` - json config
│   │   ├── `dev-report-20260524-205459.json` - json config
│   │   ├── `dev-report-20260525-050824.json` - json config
│   │   ├── `dev-report-20260525-095242.json` - json config
│   │   ├── `dev-report-20260525-095245.json` - json config
│   │   ├── `dev-report-20260526-042454.json` - json config
│   │   ├── `dev-report-20260526-052559.json` - json config
│   │   ├── `dev-report-20260526-053746.json` - json config
│   │   ├── `dev-report-20260526-202532.json` - json config
│   │   ├── `dev-report-20260527-054705.json` - json config
│   │   ├── `dev-report-20260527-132200.json` - json config
│   │   ├── `dev-report-20260527-133200.json` - json config
│   │   ├── `dev-report-20260529-080709.json` - json config
│   │   ├── `dev-report-20260529-081014.json` - json config
│   │   ├── `dev-report-20260529-164939.json` - json config
│   │   ├── `dev-report-20260529-210616.json` - json config
│   │   ├── `dev-report-20260529-211406.json` - json config
│   │   ├── `dev-report-20260530-081334.json` - json config
│   │   ├── `dev-report-20260530-091304.json` - json config
│   │   ├── `dev-report-20260530-105221.json` - json config
│   │   ├── `dev-report-20260530-170350.json` - json config
│   │   ├── `dev-report-20260531-112831-bug1.json` - json config
│   │   ├── `dev-report-20260531-112831-bug2b.json` - json config
│   │   ├── `dev-report-20260531-112831.json` - json config
│   │   ├── `dev-report-20260531-162901.json` - json config
│   │   ├── `dev-report-20260601-060455.json` - json config
│   │   ├── `dev-report-20260604-000000.json` - json config
│   │   ├── `dev-report-20260604-204954.json` - json config
│   │   ├── `dev-report-20260611-100500.json` - json config
│   │   ├── `dev-report-20260614-093452.json` - json config
│   │   ├── `dev-report-20260614-205834.json` - json config
│   │   ├── `dev-report-d1e94e.json` - json config
│   │   ├── `dev-report-dev-20260107-091716.json` - json config
│   │   ├── `dev-report-dev-20260107-100221.json` - json config
│   │   ├── `dev-report-dev-20260107-104430.json` - json config
│   │   ├── `dev-report-dev-20260108-111618.json` - json config
│   │   ├── `dev-report-dev-20260108-153719.json` - json config
│   │   ├── `dev-report-dev-20260108-163807.json` - json config
│   │   ├── `dev-report-dev-20260108-164641.json` - json config
│   │   ├── `dev-report-dev-20260111-193314.json` - json config
│   │   ├── `dev-report-dev-20260524-170335.json` - json config
│   │   ├── `dev-report-dev-20260524-205811.json` - json config
│   │   ├── `dev-report-dev-20260525-050935.json` - json config
│   │   ├── `dev-report-dev-20260525-053326-A.json` - json config
│   │   ├── `dev-report-dev-20260525-053326-B.json` - json config
│   │   ├── `dev-report-dev-20260525-053326-F.json` - json config
│   │   ├── `dev-report-dev-20260525-053326.json` - json config
│   │   ├── `dev-report-dev-20260526-044731.json` - json config
│   │   ├── `dev-report-dev-20260526-200855.json` - json config
│   │   ├── `dev-report-dev-20260526-203808-manifest.json` - json config
│   │   ├── `dev-report-dev-20260526-203808.json` - json config
│   │   ├── `dev-report-dev-20260527-063758-T1.json` - json config
│   │   ├── `dev-report-dev-20260527-063758-T2.json` - json config
│   │   ├── `dev-report-dev-20260527-063758-T3.json` - json config
│   │   ├── `dev-report-dev-20260527-063758-T4.json` - json config
│   │   ├── `dev-report-dev-20260527-063758.json` - json config
│   │   ├── `dev-report-dev-20260529-081000.json` - json config
│   │   ├── `dev-report-dev-20260529-092512-A.json` - json config
│   │   ├── `dev-report-dev-20260529-092512-B.json` - json config
│   │   ├── `dev-report-dev-20260529-092512-C.json` - json config
│   │   ├── `dev-report-dev-20260529-092512-F.json` - json config
│   │   ├── `dev-report-dev-20260529-092512.json` - json config
│   │   ├── `dev-report-dev-20260529-152050.json` - json config
│   │   ├── `dev-report-dev-20260529-210759.json` - json config
│   │   ├── `dev-report-dev-20260530-082409.json` - json config
│   │   ├── `dev-report-dev-20260530-084735.json` - json config
│   │   ├── `dev-report-dev-20260530-144032.json` - json config
│   │   ├── `dev-report-dev-20260531-134455-taska.json` - json config
│   │   ├── `dev-report-dev-20260531-134455-taskb.json` - json config
│   │   ├── `dev-report-dev-20260531-134455.json` - json config
│   │   ├── `dev-report-dev-20260531-193000-taska.json` - json config
│   │   ├── `dev-report-dev-20260531-193000-taskb.json` - json config
│   │   ├── `dev-report-dev-20260531-193000.json` - json config
│   │   ├── `dev-report-dev-20260615-213842.json` - json config
│   │   ├── `dev-report-do-20260529-210815.json` - json config
│   │   ├── `do-deprivatize-report-20260614-182549.json` - json config
│   │   ├── `do-report-005efeec-bb32-4361-ad8e-21e673e7f61d.json` - json config
│   │   ├── `do-report-20260530-212215.json` - json config
│   │   ├── `do-report-20260531-082707.json` - json config
│   │   ├── `do-report-20260602-210702.json` - json config
│   │   ├── `do-report-20260606-131137.json` - json config
│   │   ├── `do-report-20260606-201330.json` - json config
│   │   ├── `do-report-20260614-182549.json` - json config
│   │   ├── `do-report-20260615-125319.json` - json config
│   │   ├── `do-report-20260615-151335.json` - json config
│   │   ├── `do-report-20260616-094643.json` - json config
│   │   ├── `do-report-30fbb321-8921-44aa-bd65-de59e4c70730.json` - json config
│   │   ├── `do-report-441b0d47-3cbf-4fa5-9038-76ef39df048a.json` - json config
│   │   ├── `do-report-44e208af-b8b8-4266-a2ba-fcfc77f92d24.json` - json config
│   │   ├── `do-report-77be7954-cf76-4fea-a146-5cb88f32a69f.json` - json config
│   │   ├── `do-report-8cfdc493-794f-4367-941b-2e2a150db230.json` - json config
│   │   ├── `do-report-c2667fea-a84e-4ba8-9dc7-fae4c1abfc24.json` - json config
│   │   ├── `do-report-c7452b2d-d6dd-4fa6-b61a-f0642a46c906.json` - json config
│   │   ├── `do-report-cc7a706f-2662-4274-976d-d2f19e6dd767.json` - json config
│   │   ├── `do-report-do-20260531-111311.json` - json config
│   │   ├── `do-report-do-20260531-171010.json` - json config
│   │   ├── `do-report-do-20260602-150727.json` - json config
│   │   ├── `do-report-do-20260603-084448.json` - json config
│   │   ├── `do-report-eeeabad1-554e-4a04-a040-149797afaed7.json` - json config
│   │   ├── `graphify-spike-report-20260530-081334.md` - Graphify Validation Spike Report — Task 20260530-081334
│   │   ├── `meta-assessment-20260519-161035.json` - json config
│   │   ├── `note-20260524-123039-root-bin-manual-commit.md` - Manual Commit Instructions: /root/bin/happy-session-recovery.sh
│   │   ├── `observations-ledger.md` - Observations Ledger
│   │   ├── `product-owner-dev-20260615-213842.json` - json config
│   │   ├── `prompt-inspector-report-005efeec-bb32-4361-ad8e-21e673e7f61d.json` - json config
│   │   ├── `prompt-inspector-report-20260517-153856.json` - json config
│   │   ├── `prompt-inspector-report-20260517-155838.json` - json config
│   │   ├── `prompt-inspector-report-20260517-172600.json` - json config
│   │   ├── `prompt-inspector-report-20260517-211508.json` - json config
│   │   ├── `prompt-inspector-report-20260517-214922.json` - json config
│   │   ├── `prompt-inspector-report-20260517-215114.json` - json config
│   │   ├── `prompt-inspector-report-20260517-222440.json` - json config
│   │   ├── `prompt-inspector-report-20260518-071337.json` - json config
│   │   ├── `prompt-inspector-report-20260518-094616.json` - json config
│   │   ├── `prompt-inspector-report-20260518-155948.json` - json config
│   │   ├── `prompt-inspector-report-20260518-214050.json` - json config
│   │   ├── `prompt-inspector-report-20260519-132417.json` - json config
│   │   ├── `prompt-inspector-report-20260519-151734.json` - json config
│   │   ├── `prompt-inspector-report-20260519-161035.json` - json config
│   │   ├── `prompt-inspector-report-20260519-175339.json` - json config
│   │   ├── `prompt-inspector-report-20260519-211515-recheck.json` - json config
│   │   ├── `prompt-inspector-report-20260519-211515-redev9items.json` - json config
│   │   ├── `prompt-inspector-report-20260519-211515.json` - json config
│   │   ├── `prompt-inspector-report-20260520-085647-d1722b.json` - json config
│   │   ├── `prompt-inspector-report-20260520-221452.json` - json config
│   │   ├── `prompt-inspector-report-20260521-090100.json` - json config
│   │   ├── `prompt-inspector-report-20260521-090200.json` - json config
│   │   ├── `prompt-inspector-report-20260521-090300.json` - json config
│   │   ├── `prompt-inspector-report-20260522-000000.json` - json config
│   │   ├── `prompt-inspector-report-20260522-080646.json` - json config
│   │   ├── `prompt-inspector-report-20260524-122910.json` - json config
│   │   ├── `prompt-inspector-report-20260524-122947.json` - json config
│   │   ├── `prompt-inspector-report-20260524-123039.json` - json config
│   │   ├── `prompt-inspector-report-20260524-125300.json` - json config
│   │   ├── `prompt-inspector-report-20260524-133650.json` - json config
│   │   ├── `prompt-inspector-report-20260524-171714.json` - json config
│   │   ├── `prompt-inspector-report-20260524-172805.json` - json config
│   │   ├── `prompt-inspector-report-20260524-205459.json` - json config
│   │   ├── `prompt-inspector-report-20260525-050824.json` - json config
│   │   ├── `prompt-inspector-report-20260525-095242.json` - json config
│   │   ├── `prompt-inspector-report-20260525-095245.json` - json config
│   │   ├── `prompt-inspector-report-20260526-042454.json` - json config
│   │   ├── `prompt-inspector-report-20260526-052559.json` - json config
│   │   ├── `prompt-inspector-report-20260526-053746.json` - json config
│   │   ├── `prompt-inspector-report-20260526-202532.json` - json config
│   │   ├── `prompt-inspector-report-20260527-054705.json` - json config
│   │   ├── `prompt-inspector-report-20260527-132200.json` - json config
│   │   ├── `prompt-inspector-report-20260529-080709.json` - json config
│   │   ├── `prompt-inspector-report-20260529-081014.json` - json config
│   │   ├── `prompt-inspector-report-20260529-164939.codex.txt` - txt file
│   │   ├── `prompt-inspector-report-20260529-164939.json` - json config
│   │   ├── `prompt-inspector-report-20260529-210616.json` - json config
│   │   ├── `prompt-inspector-report-20260529-211406.json` - json config
│   │   ├── `prompt-inspector-report-20260530-081334.json` - json config
│   │   ├── `prompt-inspector-report-20260530-091304.json` - json config
│   │   ├── `prompt-inspector-report-20260530-092123.json` - json config
│   │   ├── `prompt-inspector-report-20260530-105221.json` - json config
│   │   ├── `prompt-inspector-report-20260530-170350.json` - json config
│   │   ├── `prompt-inspector-report-20260530-212215.json` - json config
│   │   ├── `prompt-inspector-report-20260531-082707.json` - json config
│   │   ├── `prompt-inspector-report-20260531-162901.json` - json config
│   │   ├── `prompt-inspector-report-20260601-060455.json` - json config
│   │   ├── `prompt-inspector-report-20260602-210702.json` - json config
│   │   ├── `prompt-inspector-report-20260604-204954.json` - json config
│   │   ├── `prompt-inspector-report-20260606-131137.json` - json config
│   │   ├── `prompt-inspector-report-20260606-201330.json` - json config
│   │   ├── `prompt-inspector-report-20260611-100500.json` - json config
│   │   ├── `prompt-inspector-report-20260614-093452.json` - json config
│   │   ├── `prompt-inspector-report-20260614-182549.json` - json config
│   │   ├── `prompt-inspector-report-20260614-205834.json` - json config
│   │   ├── `prompt-inspector-report-20260615-125319.json` - json config
│   │   ├── `prompt-inspector-report-20260616-094643.json` - json config
│   │   ├── `prompt-inspector-report-30fbb321-8921-44aa-bd65-de59e4c70730.json` - json config
│   │   ├── `prompt-inspector-report-441b0d47-3cbf-4fa5-9038-76ef39df048a.json` - json config
│   │   ├── `prompt-inspector-report-44e208af-b8b8-4266-a2ba-fcfc77f92d24.json` - json config
│   │   ├── `prompt-inspector-report-77be7954-cf76-4fea-a146-5cb88f32a69f.json` - json config
│   │   ├── `prompt-inspector-report-8cfdc493-794f-4367-941b-2e2a150db230.json` - json config
│   │   ├── `prompt-inspector-report-c2667fea-a84e-4ba8-9dc7-fae4c1abfc24.json` - json config
│   │   ├── `prompt-inspector-report-c7452b2d-d6dd-4fa6-b61a-f0642a46c906.json` - json config
│   │   ├── `prompt-inspector-report-cc7a706f-2662-4274-976d-d2f19e6dd767.json` - json config
│   │   ├── `prompt-inspector-report-d1e94e.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260524-170335.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260524-205811.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260525-050935.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260525-053326.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260526-044731.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260526-200855.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260526-203808-manifest.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260526-203808.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260527-063758.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260529-081000.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260529-092512.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260529-152050.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260529-210759.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260530-084735.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260530-144032.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260531-134455.json` - json config
│   │   ├── `prompt-inspector-report-dev-20260531-193000.json` - json config
│   │   ├── `prompt-inspector-report-do-20260529-210815.json` - json config
│   │   ├── `prompt-inspector-report-do-20260531-111311.json` - json config
│   │   ├── `prompt-inspector-report-do-20260531-171010.json` - json config
│   │   ├── `prompt-inspector-report-do-20260602-150727.json` - json config
│   │   ├── `prompt-inspector-report-do-20260603-084448.json` - json config
│   │   ├── `prompt-inspector-report-eeeabad1-554e-4a04-a040-149797afaed7.json` - json config
│   │   ├── `qa-final-blame-audit-20260416-063500.json` - json config
│   │   ├── `qa-input-20260110-001044.json` - json config
│   │   ├── `qa-input-dev-20260107-091716.json` - json config
│   │   ├── `qa-input-dev-20260107-100221.json` - json config
│   │   ├── `qa-input-dev-20260107-104430.json` - json config
│   │   ├── `qa-input-dev-20260108-111618.json` - json config
│   │   ├── `qa-input-dev-20260108-153719.json` - json config
│   │   ├── `qa-input-dev-20260108-163807.json` - json config
│   │   ├── `qa-input-dev-20260108-164641.json` - json config
│   │   ├── `qa-input-dev-20260111-193314.json` - json config
│   │   ├── `qa-output-20260519-211515-iter3-codex.txt` - txt file
│   │   ├── `qa-output-ba-validation-20260519-211515-iter2.json` - json config
│   │   ├── `qa-output-ba-validation-20260519-211515.json` - json config
│   │   ├── `qa-output-final-verification-20260519-211515.json` - json config
│   │   ├── `qa-output-retrospective-classification-20260519-175339.json` - json config
│   │   ├── `qa-report-20260110-001044.json` - json config
│   │   ├── `qa-report-20260416-063500-iter2.json` - json config
│   │   ├── `qa-report-20260416-063500.json` - json config
│   │   ├── `qa-report-20260416-073000-iter2.json` - json config
│   │   ├── `qa-report-20260416-073000.json` - json config
│   │   ├── `qa-report-20260510-191533.json` - json config
│   │   ├── `qa-report-20260511-094500.json` - json config
│   │   ├── `qa-report-20260511-180000.json` - json config
│   │   ├── `qa-report-20260517-153856.json` - json config
│   │   ├── `qa-report-20260517-155838.json` - json config
│   │   ├── `qa-report-20260517-172600.json` - json config
│   │   ├── `qa-report-20260517-211508.json` - json config
│   │   ├── `qa-report-20260517-215114.json` - json config
│   │   ├── `qa-report-20260517-222440.json` - json config
│   │   ├── `qa-report-20260518-071337.json` - json config
│   │   ├── `qa-report-20260518-094616.json` - json config
│   │   ├── `qa-report-20260518-155948.json` - json config
│   │   ├── `qa-report-20260518-214050.json` - json config
│   │   ├── `qa-report-20260519-132417.json` - json config
│   │   ├── `qa-report-20260519-151734.json` - json config
│   │   ├── `qa-report-20260519-161035.json` - json config
│   │   ├── `qa-report-20260519-175339.json` - json config
│   │   ├── `qa-report-20260519-211515-close-debate.json` - json config
│   │   ├── `qa-report-20260519-211515-final.json` - json config
│   │   ├── `qa-report-20260519-211515.json` - json config
│   │   ├── `qa-report-20260520-085647-d1722b.json` - json config
│   │   ├── `qa-report-20260520-221452.json` - json config
│   │   ├── `qa-report-20260521-085554.json` - json config
│   │   ├── `qa-report-20260521-090100.json` - json config
│   │   ├── `qa-report-20260521-090200.json` - json config
│   │   ├── `qa-report-20260521-090300.json` - json config
│   │   ├── `qa-report-20260522-000000.json` - json config
│   │   ├── `qa-report-20260522-080646-A-iter2.json` - json config
│   │   ├── `qa-report-20260522-080646-A-iter3.json` - json config
│   │   ├── `qa-report-20260522-080646-A.json` - json config
│   │   ├── `qa-report-20260522-080646-B-iter2.json` - json config
│   │   ├── `qa-report-20260522-080646-B-iter3.json` - json config
│   │   ├── `qa-report-20260522-080646-B.json` - json config
│   │   ├── `qa-report-20260522-080646-C.json` - json config
│   │   ├── `qa-report-20260522-080646-D-iter2.json` - json config
│   │   ├── `qa-report-20260522-080646-D.json` - json config
│   │   ├── `qa-report-20260522-080646-F.json` - json config
│   │   ├── `qa-report-20260522-080646.json` - json config
│   │   ├── `qa-report-20260524-101700-A.json` - json config
│   │   ├── `qa-report-20260524-101700-B.json` - json config
│   │   ├── `qa-report-20260524-101700-D.json` - json config
│   │   ├── `qa-report-20260524-101700.json` - json config
│   │   ├── `qa-report-20260524-122910.json` - json config
│   │   ├── `qa-report-20260524-122947.json` - json config
│   │   ├── `qa-report-20260524-123039.json` - json config
│   │   ├── `qa-report-20260524-125300-A.json` - json config
│   │   ├── `qa-report-20260524-125300-B.json` - json config
│   │   ├── `qa-report-20260524-125300-C.json` - json config
│   │   ├── `qa-report-20260524-125300-D.json` - json config
│   │   ├── `qa-report-20260524-125300-push.json` - json config
│   │   ├── `qa-report-20260524-125300.json` - json config
│   │   ├── `qa-report-20260524-133650.json` - json config
│   │   ├── `qa-report-20260524-171714.json` - json config
│   │   ├── `qa-report-20260524-172805.json` - json config
│   │   ├── `qa-report-20260524-205206.json` - json config
│   │   ├── `qa-report-20260524-205459.json` - json config
│   │   ├── `qa-report-20260525-050824.json` - json config
│   │   ├── `qa-report-20260525-095242.json` - json config
│   │   ├── `qa-report-20260525-095245.json` - json config
│   │   ├── `qa-report-20260526-042454.json` - json config
│   │   ├── `qa-report-20260526-052559.json` - json config
│   │   ├── `qa-report-20260526-053746.json` - json config
│   │   ├── `qa-report-20260526-202532.json` - json config
│   │   ├── `qa-report-20260527-054705.json` - json config
│   │   ├── `qa-report-20260527-132200.json` - json config
│   │   ├── `qa-report-20260527-133200.json` - json config
│   │   ├── `qa-report-20260529-080709.json` - json config
│   │   ├── `qa-report-20260529-081014.json` - json config
│   │   ├── `qa-report-20260529-164939.json` - json config
│   │   ├── `qa-report-20260529-210616.json` - json config
│   │   ├── `qa-report-20260529-211406.json` - json config
│   │   ├── `qa-report-20260530-081334.json` - json config
│   │   ├── `qa-report-20260530-091304.json` - json config
│   │   ├── `qa-report-20260530-105221.json` - json config
│   │   ├── `qa-report-20260530-170350.json` - json config
│   │   ├── `qa-report-20260531-112831-bug1.json` - json config
│   │   ├── `qa-report-20260601-060455.json` - json config
│   │   ├── `qa-report-20260604-204954.json` - json config
│   │   ├── `qa-report-20260611-100500.json` - json config
│   │   ├── `qa-report-20260614-093452.json` - json config
│   │   ├── `qa-report-20260614-205834.json` - json config
│   │   ├── `qa-report-20260616-094643.json` - json config
│   │   ├── `qa-report-close-20260525-050824.json` - json config
│   │   ├── `qa-report-close-20260525-095245.json` - json config
│   │   ├── `qa-report-close-20260526-042454.json` - json config
│   │   ├── `qa-report-d1e94e.json` - json config
│   │   ├── `qa-report-dev-20260107-091716.json` - json config
│   │   ├── `qa-report-dev-20260107-100221.json` - json config
│   │   ├── `qa-report-dev-20260107-104430.json` - json config
│   │   ├── `qa-report-dev-20260108-111618.json` - json config
│   │   ├── `qa-report-dev-20260108-153719.json` - json config
│   │   ├── `qa-report-dev-20260108-163807.json` - json config
│   │   ├── `qa-report-dev-20260108-164641.json` - json config
│   │   ├── `qa-report-dev-20260111-193314.json` - json config
│   │   ├── `qa-report-dev-20260524-170335.json` - json config
│   │   ├── `qa-report-dev-20260524-205811.json` - json config
│   │   ├── `qa-report-dev-20260525-050935.json` - json config
│   │   ├── `qa-report-dev-20260525-053326-A.json` - json config
│   │   ├── `qa-report-dev-20260525-053326-B.json` - json config
│   │   ├── `qa-report-dev-20260525-053326-F.json` - json config
│   │   ├── `qa-report-dev-20260525-053326.json` - json config
│   │   ├── `qa-report-dev-20260526-044731.json` - json config
│   │   ├── `qa-report-dev-20260526-200855.json` - json config
│   │   ├── `qa-report-dev-20260526-203808-manifest.json` - json config
│   │   ├── `qa-report-dev-20260526-203808.json` - json config
│   │   ├── `qa-report-dev-20260527-063758-T1.json` - json config
│   │   ├── `qa-report-dev-20260527-063758-T2.json` - json config
│   │   ├── `qa-report-dev-20260527-063758-T3.json` - json config
│   │   ├── `qa-report-dev-20260527-063758-T4.json` - json config
│   │   ├── `qa-report-dev-20260529-081000.json` - json config
│   │   ├── `qa-report-dev-20260529-092512.json` - json config
│   │   ├── `qa-report-dev-20260529-152050.json` - json config
│   │   ├── `qa-report-dev-20260529-210759.json` - json config
│   │   ├── `qa-report-dev-20260530-084735.json` - json config
│   │   ├── `qa-report-dev-20260530-144032.json` - json config
│   │   ├── `qa-report-dev-20260531-134455.json` - json config
│   │   ├── `qa-report-dev-20260531-193000.json` - json config
│   │   ├── `qa-report-dev-20260610-205358.json` - json config
│   │   ├── `qa-report-dev-20260615-213842.json` - json config
│   │   ├── `qa-report-do-20260529-210815.json` - json config
│   │   ├── `qa-report-iter2-dev-20260107-091716.json` - json config
│   │   ├── `refined-context-dev-20260111-193314.json` - json config
│   │   ├── `style-inspector-report-005efeec-bb32-4361-ad8e-21e673e7f61d.json` - json config
│   │   ├── `style-inspector-report-20260517-153856.json` - json config
│   │   ├── `style-inspector-report-20260517-155838.json` - json config
│   │   ├── `style-inspector-report-20260517-172600.json` - json config
│   │   ├── `style-inspector-report-20260517-211508.json` - json config
│   │   ├── `style-inspector-report-20260517-214922.json` - json config
│   │   ├── `style-inspector-report-20260517-215114.json` - json config
│   │   ├── `style-inspector-report-20260517-222440.json` - json config
│   │   ├── `style-inspector-report-20260518-071337.json` - json config
│   │   ├── `style-inspector-report-20260518-094616.json` - json config
│   │   ├── `style-inspector-report-20260518-155948.json` - json config
│   │   ├── `style-inspector-report-20260518-214050.json` - json config
│   │   ├── `style-inspector-report-20260519-132417.json` - json config
│   │   ├── `style-inspector-report-20260519-151734.json` - json config
│   │   ├── `style-inspector-report-20260519-161035.json` - json config
│   │   ├── `style-inspector-report-20260519-175339.json` - json config
│   │   ├── `style-inspector-report-20260519-211515-recheck.json` - json config
│   │   ├── `style-inspector-report-20260519-211515.json` - json config
│   │   ├── `style-inspector-report-20260520-085647-d1722b.json` - json config
│   │   ├── `style-inspector-report-20260520-221452.json` - json config
│   │   ├── `style-inspector-report-20260521-090100.json` - json config
│   │   ├── `style-inspector-report-20260521-090200.json` - json config
│   │   ├── `style-inspector-report-20260521-090300.json` - json config
│   │   ├── `style-inspector-report-20260522-000000.json` - json config
│   │   ├── `style-inspector-report-20260522-080646.json` - json config
│   │   ├── `style-inspector-report-20260524-101700.json` - json config
│   │   ├── `style-inspector-report-20260524-122910.json` - json config
│   │   ├── `style-inspector-report-20260524-122947.json` - json config
│   │   ├── `style-inspector-report-20260524-123039.json` - json config
│   │   ├── `style-inspector-report-20260524-125300.json` - json config
│   │   ├── `style-inspector-report-20260524-133650.json` - json config
│   │   ├── `style-inspector-report-20260524-171714.json` - json config
│   │   ├── `style-inspector-report-20260524-172805.json` - json config
│   │   ├── `style-inspector-report-20260524-205206.json` - json config
│   │   ├── `style-inspector-report-20260524-205459.json` - json config
│   │   ├── `style-inspector-report-20260525-050824.json` - json config
│   │   ├── `style-inspector-report-20260525-095242.json` - json config
│   │   ├── `style-inspector-report-20260525-095245.json` - json config
│   │   ├── `style-inspector-report-20260526-042454.json` - json config
│   │   ├── `style-inspector-report-20260526-052559.json` - json config
│   │   ├── `style-inspector-report-20260526-053746.json` - json config
│   │   ├── `style-inspector-report-20260526-202532.json` - json config
│   │   ├── `style-inspector-report-20260527-054705.json` - json config
│   │   ├── `style-inspector-report-20260527-132200.json` - json config
│   │   ├── `style-inspector-report-20260529-080709.json` - json config
│   │   ├── `style-inspector-report-20260529-081014.json` - json config
│   │   ├── `style-inspector-report-20260529-164939.json` - json config
│   │   ├── `style-inspector-report-20260529-210616.json` - json config
│   │   ├── `style-inspector-report-20260529-211406.json` - json config
│   │   ├── `style-inspector-report-20260530-081334.json` - json config
│   │   ├── `style-inspector-report-20260530-091304.json` - json config
│   │   ├── `style-inspector-report-20260530-105221.json` - json config
│   │   ├── `style-inspector-report-20260530-170350.json` - json config
│   │   ├── `style-inspector-report-20260530-212215.json` - json config
│   │   ├── `style-inspector-report-20260531-082707.json` - json config
│   │   ├── `style-inspector-report-20260601-060455.json` - json config
│   │   ├── `style-inspector-report-20260602-210702.json` - json config
│   │   ├── `style-inspector-report-20260604-204954.json` - json config
│   │   ├── `style-inspector-report-20260606-131137.json` - json config
│   │   ├── `style-inspector-report-20260606-201330.json` - json config
│   │   ├── `style-inspector-report-20260611-100500.json` - json config
│   │   ├── `style-inspector-report-20260614-093452.json` - json config
│   │   ├── `style-inspector-report-20260614-182549.json` - json config
│   │   ├── `style-inspector-report-20260614-205834.json` - json config
│   │   ├── `style-inspector-report-20260615-125319.json` - json config
│   │   ├── `style-inspector-report-20260616-094643.json` - json config
│   │   ├── `style-inspector-report-30fbb321-8921-44aa-bd65-de59e4c70730.json` - json config
│   │   ├── `style-inspector-report-441b0d47-3cbf-4fa5-9038-76ef39df048a.json` - json config
│   │   ├── `style-inspector-report-44e208af-b8b8-4266-a2ba-fcfc77f92d24.json` - json config
│   │   ├── `style-inspector-report-77be7954-cf76-4fea-a146-5cb88f32a69f.json` - json config
│   │   ├── `style-inspector-report-8cfdc493-794f-4367-941b-2e2a150db230.json` - json config
│   │   ├── `style-inspector-report-c2667fea-a84e-4ba8-9dc7-fae4c1abfc24.json` - json config
│   │   ├── `style-inspector-report-c7452b2d-d6dd-4fa6-b61a-f0642a46c906.json` - json config
│   │   ├── `style-inspector-report-cc7a706f-2662-4274-976d-d2f19e6dd767.json` - json config
│   │   ├── `style-inspector-report-d1e94e.json` - json config
│   │   ├── `style-inspector-report-dev-20260524-170335.json` - json config
│   │   ├── `style-inspector-report-dev-20260524-205811.json` - json config
│   │   ├── `style-inspector-report-dev-20260525-050935.json` - json config
│   │   ├── `style-inspector-report-dev-20260525-053326.json` - json config
│   │   ├── `style-inspector-report-dev-20260526-044731.json` - json config
│   │   ├── `style-inspector-report-dev-20260526-200855.json` - json config
│   │   ├── `style-inspector-report-dev-20260526-203808-manifest.json` - json config
│   │   ├── `style-inspector-report-dev-20260526-203808.json` - json config
│   │   ├── `style-inspector-report-dev-20260527-063758.json` - json config
│   │   ├── `style-inspector-report-dev-20260529-081000.json` - json config
│   │   ├── `style-inspector-report-dev-20260529-092512.json` - json config
│   │   ├── `style-inspector-report-dev-20260529-152050.json` - json config
│   │   ├── `style-inspector-report-dev-20260529-210759.json` - json config
│   │   ├── `style-inspector-report-dev-20260530-084735.json` - json config
│   │   ├── `style-inspector-report-dev-20260530-144032.json` - json config
│   │   ├── `style-inspector-report-dev-20260531-134455.json` - json config
│   │   ├── `style-inspector-report-dev-20260531-193000.json` - json config
│   │   ├── `style-inspector-report-do-20260529-210815.json` - json config
│   │   ├── `style-inspector-report-do-20260531-111311.json` - json config
│   │   ├── `style-inspector-report-do-20260531-171010.json` - json config
│   │   ├── `style-inspector-report-do-20260602-150727.json` - json config
│   │   ├── `style-inspector-report-do-20260603-084448.json` - json config
│   │   ├── `style-inspector-report-eeeabad1-554e-4a04-a040-149797afaed7-v2.json` - json config
│   │   ├── `style-inspector-report-eeeabad1-554e-4a04-a040-149797afaed7.json` - json config
│   │   ├── `style-progress-dev-20260530-144032.json` - json config
│   │   ├── `style-progress-dev-20260531-193000.json` - json config
│   │   ├── `style-progress-eeeabad1-554e-4a04-a040-149797afaed7-v2.json` - json config
│   │   ├── `test-writer-report-20260520-221452.json` - json config
│   │   ├── `test-writer-report-20260521-090100.json` - json config
│   │   ├── `test-writer-report-20260521-090200.json` - json config
│   │   ├── `test-writer-report-20260521-090300.json` - json config
│   │   ├── `test-writer-report-20260522-000000.json` - json config
│   │   ├── `test-writer-report-20260522-080646-A.json` - json config
│   │   ├── `test-writer-report-20260522-080646-B.json` - json config
│   │   ├── `test-writer-report-20260522-080646-D.json` - json config
│   │   ├── `test-writer-report-20260524-122910.json` - json config
│   │   ├── `test-writer-report-20260524-122947.json` - json config
│   │   ├── `test-writer-report-20260524-125300-A.json` - json config
│   │   ├── `test-writer-report-20260524-125300-B.json` - json config
│   │   ├── `test-writer-report-20260524-125300-C.json` - json config
│   │   ├── `test-writer-report-20260524-125300-D.json` - json config
│   │   ├── `test-writer-report-20260524-125300-push.json` - json config
│   │   ├── `test-writer-report-20260524-172805.json` - json config
│   │   ├── `test-writer-report-20260524-205206.json` - json config
│   │   ├── `test-writer-report-20260525-050824.json` - json config
│   │   ├── `test-writer-report-20260525-095242.json` - json config
│   │   ├── `test-writer-report-20260526-052559.json` - json config
│   │   ├── `test-writer-report-20260526-053746.json` - json config
│   │   ├── `test-writer-report-20260527-132200.json` - json config
│   │   ├── `test-writer-report-20260529-080709.json` - json config
│   │   ├── `test-writer-report-20260529-211406.json` - json config
│   │   ├── `test-writer-report-20260530-105221.json` - json config
│   │   ├── `test-writer-report-20260530-170350.json` - json config
│   │   ├── `test-writer-report-20260531-112831-bug1.json` - json config
│   │   ├── `test-writer-report-20260604-204954.json` - json config
│   │   ├── `test-writer-report-20260611-100500.json` - json config
│   │   ├── `test-writer-report-20260614-093452.json` - json config
│   │   ├── `test-writer-report-20260614-205834.json` - json config
│   │   ├── `test-writer-report-dev-20260531-134455.json` - json config
│   │   ├── `test-writer-report-dev-20260531-193000.json` - json config
│   │   ├── `test-writer-report-dev-20260615-213842.json` - json config
│   │   ├── `test-writer-report-dev-20260616-204226.json` - json config
│   │   ├── `ticket-20260510-191533.md` - BA Specification: Restore v3 Manifest as OPTIONAL Precision Layer + Eliminate Hardcoded "v3"
│   │   ├── `ticket-20260511-094500.md` - BA Specification: C2 worktree-recognition rollback (single-item cycle)
│   │   ├── `ticket-20260511-180000.md` - BA Specification: Enterprise commit hardening — hash chain trailer + message-vs-evidence guard + CC type lint + optional audit-log persistence
│   │   ├── `ticket-20260517-153856.md` - BA Specification: Establish Bidirectional Handoff Contracts Between Specialist Agents and BA
│   │   ├── `ticket-20260517-155838.md` - BA Specification: /do direct-development cannot be closed via /close normal path
│   │   ├── `ticket-20260517-172600.md` - BA Specification: Add close→commit/push Ending Workflow Adaptation to clean.md + Enumerate Other Commands
│   │   ├── `ticket-20260517-211508.md` - BA Specification: Fix broken ending-workflow in clean.md (Cycle 2)
│   │   ├── `ticket-20260517-215114.md` - BA Specification: Agentic Analyst Mechanism for /push, /merge, /pull
│   │   ├── `ticket-20260517-222440.md` - BA Specification: /allow bypass does not extend to git commit in pretool-git-privilege-guard.py
│   │   ├── `ticket-20260518-071337.md` - BA Specification: /allow Universal Bypass — systemctl and git push
│   │   ├── `ticket-20260518-094616.md` - BA Specification: /allow Bypass System — 6-Issue Architectural Refactor
│   │   ├── `ticket-20260518-155948.md` - BA Specification: Consolidate 5 /allow Grant-Read Implementations into lib/allowlist.py
│   │   ├── `ticket-20260518-214050.md` - BA Specification: Multi-Repo .gitignore Cleanup and Stale File Removal
│   │   ├── `ticket-20260519-132417.md` - BA Specification: Dev Harness Extension Plan — Scoring, Test-Writer, Blast Radius, Executable AC, Canary
│   │   ├── `ticket-20260519-151734.md` - BA Specification: Fix /do and /allow Bypass Coverage in PreToolUse Hooks
│   │   ├── `ticket-20260519-161035.md` - BA Specification: Layered prevention of tmp/ramdisk pressure recurrence
│   │   ├── `ticket-20260519-175339.md` - BA Specification: Chrome CDP Page-Target Deadlock — Wrapper Lock + Stale-Page Cleanup + Cron Surgical Edit
│   │   ├── `ticket-20260519-211515-CYCLE2-round3.md` - BA Specification: 3-Cluster Harness Fixes (Shippability Gate / Real-Fixture Verification / Event-Sourced Lifecycle Log)
│   │   ├── `ticket-20260519-211515.md` - BA Specification: Implement 9 retrospective remediation items from cycle 20260519-175339
│   │   ├── `ticket-20260520-085647-d1722b.md` - BA Specification: Close /allow grant leakage (D) and PostToolUse:Agent tracker race (H) — TRANSFERRED
│   │   ├── `ticket-20260520-221452.md` - BA Specification: spec-20260518-225715 Cycle 2 — P1+P2+P3 Close-Gate Remediation
│   │   ├── `ticket-20260520-allow-dh-7faae4.md` - BA Specification: Close `/allow` grant leakage (D) and PostToolUse:Agent tracker race (H)
│   │   ├── `ticket-20260521-085827-fa9f07.md` - BA Specification: Batched remediation — codex output relocation + sentinel investigation + /allow vs orchestra tracker-gate
│   │   ├── `ticket-20260521-090100.md` - BA Specification: Canonical Codex Output Path (docs/codex/)
│   │   ├── `ticket-20260521-090200.md` - BA Specification: /allow Grant Not Honored — Hook Chain Investigation
│   │   ├── `ticket-20260521-090300.md` - BA Specification: `.hook-refactor-allow` Sentinel Security Audit
│   │   ├── `ticket-20260522-000000.md` - BA Specification: Gitignore fixes, spec commitment, tmp-cleanup.sh mirror, and score-update uncapped_delta
│   │   ├── `ticket-20260522-080646-A.md` - BA Specification: bash-safety hook false positives — substring vs executable-context matching
│   │   ├── `ticket-20260522-080646-B.md` - BA Specification: Write-Guard Sentinel Integration
│   │   ├── `ticket-20260522-080646-C.md` - BA Specification: Tighten Step 7 Stage-3 Candidate Predicate to Machine-Readable Marker
│   │   ├── `ticket-20260522-080646-D.md` - BA Specification: Dev Self-Report Provenance (OOS Item D)
│   │   ├── `ticket-20260522-080646-F.md` - BA Specification: hooks/tests underscore-prefix rename + cleanup
│   │   ├── `ticket-20260524-101700-A.md` - BA Specification: bash-safety hook — DANGER_COMMANDS quoted-arg bypass (second attempt)
│   │   ├── `ticket-20260524-101700-B.md` - BA Specification: Write-Guard Sentinel Integration — Add Missing Wildcard Test
│   │   ├── `ticket-20260524-101700-D.md` - BA Specification: Spec Text/Test Correction — Task D (test_AC3 provenance gap only)
│   │   ├── `ticket-20260524-101700-H.md` - BA Specification: Three Structural Gaps in happy-session-recovery.sh
│   │   ├── `ticket-20260524-101700-X.md` - BA Specification: Infrastructure Audit — daily-trade, swap-drain, post-start, disk-monitor
│   │   ├── `ticket-20260524-101700.md` - BA Specification Aggregate: dev-20260524-101700
│   │   ├── `ticket-20260524-122910.md` - BA Specification: spec-20260518-225715 Cycle 3 — 10-Debt Clearance
│   │   ├── `ticket-20260524-122947.md` - BA Specification: /push execute-push.py Script + Step 5 Delegation Warning
│   │   ├── `ticket-20260524-123039.md` - BA Specification: Session Wrap-Up — Commit Remaining Artifacts + Document Manual Action
│   │   ├── `ticket-20260524-125300-A.md` - BA Specification: Three Bypass Paths in bash_context_strip.py
│   │   ├── `ticket-20260524-125300-B.md` - BA Specification: Fix /allow Write Sentinel — Writer Path Bugs + Schema Mismatch (Privilege Escalation)
│   │   ├── `ticket-20260524-125300-C.md` - BA spec — missing spec-continuation-of marker in spec-update producer
│   │   ├── `ticket-20260524-125300-D.md` - BA Specification: Dev Provenance Completeness — Three QA Gate Gaps
│   │   ├── `ticket-20260524-125300-push.md` - BA Spec: execute-push.py — atomic push eliminating && timing window (iteration 3)
│   │   ├── `ticket-20260524-133650.md` - BA Specification: /allow sentinel bypass for git ref-mutation guard
│   │   ├── `ticket-20260524-171714.md` - BA Specification: arch-6 Gitignore Preflight Gate + arch-3 ENOSPC Fallback
│   │   ├── `ticket-20260524-172805.md` - BA Specification: Scoring Rebalance, Rating UX Fix, Session Summary, and Commit Isolation
│   │   ├── `ticket-20260524-205206.md` - BA Specification: Cycle-Total Score Cap +5, Verifiable Score Injection, Timeline Session Summary, User-Gated /commit --bulk
│   │   ├── `ticket-20260524-205459.md` - BA Specification: LOCK_FILE EISDIR stderr leak fix (arch-3 phase 2)
│   │   ├── `ticket-20260525-050824.md` - BA Specification: Score CAS Architecture (arch-7 phase 2, R9)
│   │   ├── `ticket-20260525-095242.md` - BA Specification: Fix Layer 1.F compound-command bypass in pretool-bash-safety.sh
│   │   ├── `ticket-20260525-095245.md` - BA Specification: Wrap bare python3 heredoc calls with venv activation
│   │   ├── `ticket-20260526-042454.md` - BA Specification: Parameterize flock timeout constants (Standard 2/9 fix)
│   │   ├── `ticket-20260526-052545.md` - BA Specification: Privilege Guard Security Gap — auto-bulk: Bypass in BULK=false Mode
│   │   ├── `ticket-20260526-052559.md` - BA Specification: Close Layer 1.F bypass paths for write-bulk-commit-sentinel.py
│   │   ├── `ticket-20260526-053746.md` - BA Specification: Fix 6 Outstanding Items from Cycle 1-6
│   │   ├── `ticket-20260526-202532.md` - BA Specification: Remove dead auth-flag code from hooks
│   │   ├── `ticket-20260527-054705.md` - BA Specification: Fix 3 Codex Assessment Residuals
│   │   ├── `ticket-20260527-132200.md` - BA Specification: Graphify Knowledge Graph Integration — Dual-Touchpoint Architecture
│   │   ├── `ticket-20260527-133200.md` - BA Specification: Changelog-analyst warn-and-skip for provenance-anomaly files in BULK=false mode
│   │   ├── `ticket-20260529-080709.md` - BA Specification: Graphify Close-Blocker Fixes (Cycle 2)
│   │   ├── `ticket-20260529-081014.md` - BA Specification: QA empty-active vacuity guard + venv broken-symlink repair
│   │   ├── `ticket-20260529-164939.md` - BA Specification: Replace bash sentinel guard with prose in commands/dev.md
│   │   ├── `ticket-20260529-210616.md` - BA Specification: score-update reversal + /close premature-score guard + clear 5 carried-forward test failures
│   │   ├── `ticket-20260529-211406.md` - BA Specification: Recovery commit when task files pre-empted by foreign bulk session
│   │   ├── `ticket-20260530-081334.md` - BA Specification: Graphify safety gate + real-CLI validation spike
│   │   ├── `ticket-20260530-091304.md` - BA Specification: changelog-analyst.md Style Fixes — /close Unblock
│   │   ├── `ticket-20260530-105221.md` - BA Specification: Graphify FULL B-lite Integration — rewrite 3 wrappers to drive REAL graphify CLI
│   │   ├── `ticket-20260530-170350.md` - BA Specification: Graphify Semantic Path — Fix Proof-Gate + Add Manual `semantic` Command (Verdict P)
│   │   ├── `ticket-20260531-112831-bug1.md` - BA Specification: Bug 1 — Scoped Restore for Manual Single-Daemon Restarts
│   │   ├── `ticket-20260531-112831-bug2b.md` - BA Specification: Fix pid_to_happy_home() happy-sessions.slice Recognition
│   │   ├── `ticket-20260531-112831-gap1.md` - BA Specification: Fix Gap 1 — Restored Codex Session Shows Blank History
│   │   ├── `ticket-20260531-112831.md` - BA Specification: Bug 2a — Codex Process-Exit Tombstone
│   │   ├── `ticket-20260601-060455.md` - BA Specification: /spec must persist + reference user-supplied design and evidence
│   │   ├── `ticket-20260604-204954.md` - BA Specification: Harden /dev-overnight so an overnight session can NEVER touch master (always-create-worktree, no hard-abort) — OPTION A (git ≥2.46 structural keystone)
│   │   ├── `ticket-20260611-100500.md` - BA Specification: CONJUNCTIVE HARDENING — (a) block "overnight actor moves main HEAD off master" via the git-native reference-transaction keystone (L5, half a, PASSED) **AND** (b) block "overnight actor writes/checks-out in place in the main working tree" via a per-Bash-command bwrap OS execution boundary (L6, half b, this update)
│   │   ├── `ticket-20260614-093452.md` - BA Specification: Close the blank-check wildcard fallback in /allow consent
│   │   ├── `ticket-20260614-205834.md` - BA Specification: HEAD Public-Hygiene Prep — Residual Refs + Stale INDEX + Public-Readiness Quick-Wins
│   │   ├── `ticket-75463e-DH.md` - BA Specification: Close `/allow` grant leakage (D) and PostToolUse:Agent tracker race (H) — iter3
│   │   ├── `ticket-close-cont-20260524-170335.md` - Continuation: Fix bare python3 invocations introduced in dev-20260524-170335
│   │   ├── `ticket-d1e94e-CYCLE2-round2.md` - BA Specification: Dev Harness Extension — Cycle 2 Remediation
│   │   ├── `ticket-d1e94e-CYCLE2.md` - BA Specification: Dev Harness Extension — Cycle 2 Remediation
│   │   ├── `ticket-d1e94e.md` - BA Specification: Close `/allow` grant leakage (D) and PostToolUse:Agent tracker race (H) — iter3
│   │   ├── `ticket-dev-20260524-170335.md` - BA Specification: Parallel-Worker Pipeline Conflict Fixes (5-Fix Consensus Plan)
│   │   ├── `ticket-dev-20260524-205811.md` - BA Specification: Fix Legacy Grant Subagent Leak in /allow Hook Infrastructure
│   │   ├── `ticket-dev-20260525-050935.md` - BA Specification: Git Hygiene — Multi-Repo Gitignore Gaps + Harness Propagation Hook
│   │   ├── `ticket-dev-20260525-053326-A.md` - BA Specification: Context-Aware Dangerous Token Stripping for Script Interpreter Argv
│   │   ├── `ticket-dev-20260525-053326-B.md` - BA Specification: Write-Guard Sentinel Integration (worker B)
│   │   ├── `ticket-dev-20260525-053326-F.md` - BA Specification: Shell Cleanliness Fixes — Permissions, mktemp+trap, Stale Comments
│   │   ├── `ticket-dev-20260526-044731.md` - BA Specification: Rename spec-continue → spec-update + Verify Flock Timeout Parameterization
│   │   ├── `ticket-dev-20260526-200855.md` - BA Specification: Fix execute-push.py CWD dependency via --repo-root
│   │   ├── `ticket-dev-20260526-203808-issubagent.md` - BA Specification: IS_SUBAGENT Gate on BLESSED_BRIDGE_RE Commit Path
│   │   ├── `ticket-dev-20260526-203808-manifest.md` - BA Specification: Register AC7 and AC7b in per-task manifest (task 20260526-052559)
│   │   ├── `ticket-dev-20260526-203808.md` - BA Specification: Fix stale M5 allowlist regex in ticket-20260526-052559 Edge Cases
│   │   ├── `ticket-dev-20260527-063758-T1.md` - BA Spec: Fix push-gate token session_id mismatch in changelog-analyst
│   │   ├── `ticket-dev-20260527-063758-T2.md` - BA Specification: Increase Commit Grant TTL from 10 to 30 Minutes
│   │   ├── `ticket-dev-20260527-063758-T3.md` - BA Specification: Push-analyst grant TTL increase 180s -> 600s
│   │   ├── `ticket-dev-20260527-063758-T4.md` - BA Specification: Fix `python` → `python3` and `CLAUDE_SESSION_ID` fallback
│   │   ├── `ticket-dev-20260529-081000.md` - BA Specification: Fix failing test — write-bulk-commit-sentinel.py session-ID fallback
│   │   ├── `ticket-dev-20260529-092512.md` - BA Specification: Backlog batch — context-strip extension, write-guard hardening, step-7 marker parity, test cleanliness
│   │   ├── `ticket-dev-20260529-152050.md` - BA Specification: Positive regression test for CLAUDE_CODE_SESSION_ID fallback
│   │   ├── `ticket-dev-20260529-210759.md` - BA Specification: Fix Layer 1.F False Positive — Protected Name in Quoted String Arg
│   │   ├── `ticket-dev-20260530-084735.md` - BA Specification: Clarify `baseline_dirty_snapshot` Point-in-Time Semantics Under Concurrency
│   │   ├── `ticket-dev-20260530-144032.md` - BA Specification: Line-precise (hunk-filtered) staging in changelog-analyst
│   │   ├── `ticket-dev-20260531-134455.md` - BA Specification: Reverse-blast-radius (RB1) + integer renumbering of the /dev graphify todo items
│   │   ├── `ticket-dev-20260531-193000.md` - BA Specification: Renumber commands/dev.md to integer Step 1..17 + fully integrate graphify dual-touchpoint into /dev-overnight
│   │   ├── `ticket-dev-20260615-213842.md` - BA Specification: Dependency documentation + repo self-consistency for open-box public release
│   │   ├── `ticket-dev-20260616-204226.md` - BA Specification: Open-Box-Usable Harness — Shared Resolver, Fail-Closed Security, Fresh-Clone Smoke
│   │   ├── `ticket-do-20260529-210815.md` - /do Fix: bare dd/shred gap + Chinese diagnostic string
│   │   ├── `user-requirement-dev-20260517-215114.md` - No description
│   │   ├── `user-requirement-dev-20260517-222440.md` - No description
│   │   ├── `user-requirement-dev-20260518-214050.md` - No description
│   │   ├── `user-requirement-dev-20260519-132417.md` - No description
│   │   ├── `user-requirement-dev-20260519-151734.md` - No description
│   │   ├── `user-requirement-dev-20260519-161035.md` - User Requirement — dev-20260519-161035
│   │   ├── `user-requirement-dev-20260519-175339.md` - No description
│   │   ├── `user-requirement-dev-20260520-221452.md` - No description
│   │   ├── `user-requirement-dev-20260521-085554.md` - No description
│   │   ├── `user-requirement-dev-20260521-085627.md` - No description
│   │   ├── `user-requirement-dev-20260522-080646.md` - No description
│   │   ├── `user-requirement-dev-20260524-101700.md` - No description
│   │   ├── `user-requirement-dev-20260524-122910.md` - No description
│   │   ├── `user-requirement-dev-20260524-122947.md` - No description
│   │   ├── `user-requirement-dev-20260524-123039.md` - No description
│   │   ├── `user-requirement-dev-20260524-125300.md` - No description
│   │   ├── `user-requirement-dev-20260524-133650.md` - No description
│   │   ├── `user-requirement-dev-20260524-170335.md` - No description
│   │   ├── `user-requirement-dev-20260524-171714.md` - No description
│   │   ├── `user-requirement-dev-20260524-172805.md` - No description
│   │   ├── `user-requirement-dev-20260524-205206.md` - No description
│   │   ├── `user-requirement-dev-20260524-205459.md` - No description
│   │   ├── `user-requirement-dev-20260524-205811.md` - No description
│   │   ├── `user-requirement-dev-20260525-050824.md` - No description
│   │   ├── `user-requirement-dev-20260525-050935.md` - No description
│   │   ├── `user-requirement-dev-20260525-053326.md` - No description
│   │   ├── `user-requirement-dev-20260525-095242.md` - No description
│   │   ├── `user-requirement-dev-20260525-095245.md` - No description
│   │   ├── `user-requirement-dev-20260526-042454.md` - No description
│   │   ├── `user-requirement-dev-20260526-044731.md` - No description
│   │   ├── `user-requirement-dev-20260526-052559.md` - No description
│   │   ├── `user-requirement-dev-20260526-053746.md` - No description
│   │   ├── `user-requirement-dev-20260526-200855.md` - No description
│   │   ├── `user-requirement-dev-20260526-202532.md` - No description
│   │   ├── `user-requirement-dev-20260526-203808.md` - No description
│   │   ├── `user-requirement-dev-20260527-054705.md` - No description
│   │   ├── `user-requirement-dev-20260527-063758.md` - No description
│   │   ├── `user-requirement-dev-20260527-132135.md` - No description
│   │   ├── `user-requirement-dev-20260527-132200.md` - No description
│   │   ├── `user-requirement-dev-20260527-132220.md` - No description
│   │   ├── `user-requirement-dev-20260529-071720.md` - No description
│   │   ├── `user-requirement-dev-20260529-080709.md` - No description
│   │   ├── `user-requirement-dev-20260529-081000.md` - No description
│   │   ├── `user-requirement-dev-20260529-081014.md` - No description
│   │   ├── `user-requirement-dev-20260529-092512.md` - No description
│   │   ├── `user-requirement-dev-20260529-152050.md` - No description
│   │   ├── `user-requirement-dev-20260529-164939.md` - No description
│   │   ├── `user-requirement-dev-20260529-204939.md` - No description
│   │   ├── `user-requirement-dev-20260529-210616.md` - No description
│   │   ├── `user-requirement-dev-20260529-210759.md` - No description
│   │   ├── `user-requirement-dev-20260529-211406.md` - No description
│   │   ├── `user-requirement-dev-20260530-081334.md` - No description
│   │   ├── `user-requirement-dev-20260530-082409.md` - No description
│   │   ├── `user-requirement-dev-20260530-084735.md` - No description
│   │   ├── `user-requirement-dev-20260530-091304.md` - No description
│   │   ├── `user-requirement-dev-20260530-105221.md` - No description
│   │   ├── `user-requirement-dev-20260530-144032.md` - No description
│   │   ├── `user-requirement-dev-20260530-170350.md` - No description
│   │   ├── `user-requirement-dev-20260531-112831.md` - No description
│   │   ├── `user-requirement-dev-20260531-134455.md` - No description
│   │   ├── `user-requirement-dev-20260531-193000.md` - No description
│   │   ├── `user-requirement-dev-20260610-205358.md` - No description
│   │   ├── `user-requirement-dev-20260611-100500.md` - No description
│   │   ├── `user-requirement-dev-20260614-093452.md` - No description
│   │   ├── `user-requirement-dev-20260614-205834.md` - No description
│   │   ├── `user-requirement-dev-20260615-213842.md` - No description
│   │   ├── `user-requirement-dev-20260616-204226.md` - No description
│   │   ├── `user-requirement-dev-command-20260601-060455.md` - User Requirement — dev-command-20260601-060455
│   │   └── `user-requirement-dev-d1e94e.md` - User Requirement — dev-20260519-211515
│   ├── examples/
│   │   └── `settings-with-checkpoint.json` - json config
│   ├── guides/
│   │   ├── `auto-sync-quickstart.md` - 自动同步快速开始指南
│   │   ├── `integration-guide.md` - 📊 Excel Analyzer 深度集成指南
│   │   ├── `project-settings-template.md` - Project Settings Template Guide
│   │   └── `skills-test-guide.md` - Claude Code Office Skills 测试指南
│   ├── planning/
│   ├── reference/
│   │   ├── `checkpoint-mechanism.md` - Auto-Commit / Checkpoint Mechanism
│   │   ├── `fswatch-quickref.md` - FSWatch 快速参考卡片
│   │   ├── `git-fswatch.md` - Git File Watcher (fswatch) 使用文档
│   │   ├── `graphify-integration.md` - Graphify Knowledge Graph Integration
│   │   ├── `lock-file-handling.md` - Git Lock File Handling
│   │   ├── `slashcommand-quick-reference.md` - Slash Command Quick Reference
│   │   ├── `tmp-cleanup-convention.md` - Ad-hoc scratch directory convention
│   │   └── `venv-repair.md` - venv-repair — restoring `~/.claude/venv` when interpreter symlinks break
│   ├── reports/
│   │   └── `slashcommand-rollout-summary.md` - SlashCommand Permission Rollout Summary
│   ├── templates/
│   │   └── `settings.json.template` - template file
│   └── test/
│       ├── `edge-case-analysis-qa.json` - json config
│       ├── `edge-case-analysis-summary.md` - Edge Case Analysis Summary - Git History Deep Dive
│       ├── `test-design.md` - Test Framework Design
│       └── `test-implementation-guide.md` - Test Implementation Guide - Quick Reference
├── hooks/
│   ├── doc_sync/
│   │   ├── `claude.py` - CLAUDE.md auto-creation and patching.
│   │   ├── `config.py` - Load doc-sync project-local config.
│   │   ├── `docker.py` - Parse docker-compose.yml and generate markdown table.
│   │   ├── `extract.py` - Extract description from various file types.
│   │   ├── `main.py` - Main entry point for doc-sync hook.
│   │   ├── `patch.py` - Patch CLAUDE.md dynamic sections using AUTO markers.
│   │   ├── `regen_index.py` - Regenerate INDEX.md for a directory.
│   │   ├── `regen_readme.py` - Regenerate README.md for a directory.
│   │   ├── `systemd.py` - Query systemctl for project-configured services and generate a markdown table.
│   │   └── `tree.py` - Build directory trees for INDEX.md.
│   ├── git-hooks/
│   │   ├── `post-commit-auto-push` - unknown file
│   │   └── `pre-commit` - unknown file
│   ├── git-keystone/
│   │   └── `reference-transaction` - unknown file
│   ├── lib/
│   │   ├── `agent_resolver.py` - Refactored from pretool-subagent-code-block.py::_find_agent_type so that
│   │   ├── `allowlist.py` - Single source of truth for grant-read, grant-match, and grant-consume
│   │   ├── `bash_context_strip.py` - This is deliberately NOT a full shell parser.  It only computes a conservative
│   │   ├── `bash_write_targets.py` - Provides two public functions used by tool-policy and overnight-hook-guard:
│   │   ├── `checkpoint-core.sh` - ============================================================================
│   │   ├── `close-verdict.py` - Shared CLOSE verdict classifier for commit/close tooling.
│   │   ├── `closeout.py` - Public API:
│   │   ├── `contract_runtime.py` - This module is the single shared engine consumed by every contract-aware
│   │   ├── `overnight.py` - Single source of truth for "is a /dev-overnight session currently live?". A
│   │   ├── `policy_registry.py` - Reads /root/.claude/policies/tool-policy.v1.json and provides a single
│   │   ├── `runtime_guard.py` - This module contains ZERO project identifiers. Every project-specific name
│   │   ├── `schema_registry.py` - Reads schemas/registry.json once and lazily loads referenced schema files
│   │   ├── `specialist_yield.py` - Public API:
│   │   ├── `subagent.py` - Single source of truth for is_subagent_context() and supporting helpers
│   │   └── `todo_canonical.py` - Shared canonical todo validation utilities
│   ├── tests/
│   │   ├── `test_ac10_verify.sh` - Shell script
│   │   ├── `test_ac1_verify.sh` - Shell script
│   │   ├── `test_ac3_verify.sh` - Shell script
│   │   ├── `test_ac5_verify.sh` - Shell script
│   │   ├── `test_ac6_verify.sh` - Shell script
│   │   ├── `test_ac9_verify.sh` - Shell script
│   │   ├── `test_allowlist_consolidation.py` - Covers AC8 IS_SUBAGENT firewall scenarios and matching semantics invariants
│   │   ├── `test_bash_safety_context.py` - Tests strip_non_executable_contexts() in isolation, covering the main
│   │   ├── `test_bash_safety_context_rules.py` - converted to COMMAND_CONTEXT_STRIPPED in hooks/pretool-bash-safety.sh
│   │   ├── `test_block_branch_pr_worktree.py` - The hook forbids branch / PR / worktree CREATION on the Bash surface, with three
│   │   ├── `test_bulk_commit_sentinel.py` - Covers:
│   │   ├── `test_commit_strip_dotfile_paths.py` - Bug surfaced cycle 20260511-100000: dev-report listed 6 `.claude/commands/*`
│   │   ├── `test_cp_checkin.py` - of ba-spec-20260427-194324.md (P1 view-trigger removal + P2 generation field)
│   │   ├── `test_do_taskid_mint.py` - Covers the root-cause fix for the do-report task-id collision (memory
│   │   ├── `test_final_sweep.sh` - Final sweep — run inline AC checks and print PASS/FAIL summary.
│   │   ├── `test_push_sentinel_abort.sh` - Unit test for AC1 V5: hooks/push.sh self-aborts before any real git push
│   │   └── `test_runtime_guard.py` - Two layers:
│   ├── `audit-slashcommand.sh` - audit-slashcommand.sh
│   ├── `auto-commit.sh` - ============================================================================
│   ├── `check-todo-md-sync.py` - check-todo-md-sync.py — Session-start drift detector for todo scripts
│   ├── `checkpoint.sh` - checkpoint.sh - Manual /checkpoint command
│   ├── `fswatch-manager.sh` - fswatch-manager.sh - Manage git-fswatch instances
│   ├── `git-fswatch.sh` - git-fswatch.sh - Comprehensive Git file watcher using fswatch
│   ├── `git-fswatch@.service` - service file
│   ├── `hook-todo-injection.py` - Global PreToolUse Hook: Todo Injection for Slash Commands
│   ├── `install-auto-sync.sh` - ============================================================================
│   ├── `install-git-hooks.sh` - ============================================================================
│   ├── `install-protection-all.sh` - ============================================================================
│   ├── `install.sh` - ============================================================================
│   ├── `merge.sh` - merge.sh - wrapper for /merge slash command
│   ├── `notification-idle-overnight.py` - Notification hook: Observe overnight idle events
│   ├── `post-commit-warn.sh` - post-commit-warn.sh - Warn about untracked files after commit
│   ├── `post_tool_use.sh` - PostToolUse Hook - Code quality hints after file modifications
│   ├── `posttool-allowlist-consume.py` - PostToolUse Hook: /allow grant consumption
│   ├── `posttool-codex-skill-ledger.py` - Fires on every PostToolUse for the Skill tool. When tool_input.skill == "codex",
│   ├── `posttool-command-frontmatter-validate.py` - PostToolUse Hook: Validate .claude/commands/*.md frontmatter structure
│   ├── `posttool-doc-sync.py` - PostToolUse Hook: Auto-sync INDEX.md and CLAUDE.md when structural files change
│   ├── `posttool-git-checkpoint.sh` - posttool-git-checkpoint.sh - PostToolUse checkpoint trigger
│   ├── `posttool-git-warn.sh` - post-commit-warn.sh - Warn about untracked files after commit
│   ├── `posttool-overnight-file-check.py` - PostToolUse:Agent Hook — Contract-driven overnight file check
│   ├── `posttool-overnight-loop.py` - PostToolUse:TodoWrite Hook: Overnight Loop Detection
│   ├── `posttool-overnight-trace.py` - Writes one JSONL trace record per Agent invocation to:
│   ├── `posttool-runcode-watchdog.py` - PostToolUse Hook: Cancel timeout watchdog after browser_run_code completes
│   ├── `posttool-subagent-track.py` - PostToolUse:Agent Hook: Track subagent invocations in workflow bookmark
│   ├── `posttool-todo-count.py` - PostToolUse Hook: Enforce canonical todo count immediately after TodoWrite
│   ├── `posttool-todo-sequence.py` - PostToolUse Hook: Enforce one-step-at-a-time progression in workflow checklists
│   ├── `posttool-todo-tracker.py` - PostToolUse Hook: Output checklist progress after every TodoWrite call
│   ├── `pre-commit-check.sh` - pre-commit-check.sh - Detect untracked files before commit
│   ├── `pre_slashcommand_validate.sh` - pre_slashcommand_validate.sh
│   ├── `pre_tool_use_safety.sh` - PreToolUse Safety Hook - Warn before dangerous operations
│   ├── `pretool-aggregate-check.py` - existence before allowing the orchestrator to dispatch the QA subagent in
│   ├── `pretool-bash-safety.sh` - PreToolUse Safety Hook - Warn or block before dangerous operations
│   ├── `pretool-bash-views-guard.py` - Parallels pretool-bash-safety.sh but focuses on views/cp-state write bypass
│   ├── `pretool-bisect-gate.sh` - pretool-bisect-gate.sh
│   ├── `pretool-block-branch-pr-worktree.py` - Policy (user directive 2026-06-04; the verbatim user directive is preserved in
│   ├── `pretool-block-enterworktree.sh` - PreToolUse hook: Block EnterWorktree tool
│   ├── `pretool-bulk-commit-detector.py` - Write to stderr and exit 0 (warn-only per user policy: no text-smell hard-blocks).
│   ├── `pretool-claude-config-guard.py` - PreToolUse Hook: Claude config (.claude/hooks + .claude/commands) protection
│   ├── `pretool-cp-checkin.py` - cp-state file read
│   ├── `pretool-cp-state-write-guard.py` - Cycle-3 slim form (2026-05-14): Bash-extractor removed — 22-form adversarial
│   ├── `pretool-git-privilege-guard.py` - PreToolUse Hook: Agent git-privilege guard
│   ├── `pretool-gitignore-preflight.py` - pretool-gitignore-preflight.py — PreToolUse hook (matcher: Agent)
│   ├── `pretool-layer-escalation-check.sh` - pretool-layer-escalation-check.sh
│   ├── `pretool-layer-match-gate.sh` - pretool-layer-match-gate.sh
│   ├── `pretool-orchestrator-gate.py` - PreToolUse Hook: Orchestrator Gate (Unified)
│   ├── `pretool-orchestrator-prompt-purity.py` - PreToolUse hook: Orchestrator Prompt Purity
│   ├── `pretool-overnight-hook-guard.py` - PreToolUse Hook: Overnight session file modification guard
│   ├── `pretool-quality-gate.py` - PreToolUse Hook: Quality gate for Write/Edit operations
│   ├── `pretool-read-size-guard.py` - PreToolUse Hook: Read Size Guard
│   ├── `pretool-runcode-watchdog.py` - PreToolUse Hook: Start timeout watchdog for browser_run_code
│   ├── `pretool-spec-block-foreground-agent.py` - PreToolUse Hook: Block foreground Agent during an active /spec Interview
│   ├── `pretool-subagent-code-block.py` - Canonical enforcement: pretool-tool-policy.py + lib/policy_registry — this
│   ├── `pretool-subagent-enforce.py` - PreToolUse:Agent Hook — Contract-driven role/pipeline enforcement
│   ├── `pretool-todo-validate.py` - PreToolUse Hook: Validate TodoWrite input BEFORE execution
│   ├── `pretool-tool-policy.py` - Single hook that consumes /root/.claude/policies/tool-policy.v1.json via
│   ├── `pretool-workflow-gate.py` - PreToolUse Hook: Require TodoWrite/TodoRead acknowledgment before other tools
│   ├── `pretool-worktree-guard.sh` - PreToolUse hook: Detect stale agent worktrees before ANY tool call
│   ├── `pretool-wrapper-userintent.py` - fix-4 (Cycle-2, spec-20260604-204954 §7.4). The /stop slash command releases
│   ├── `pretool-write-guard.sh` - PreToolUse Hook - Block Write tool from overwriting existing files
│   ├── `project-settings-template.json` - json config
│   ├── `prompt-workflow.py` - UserPromptSubmit Hook: Checklist Injection for Slash Commands
│   ├── `protection-status.sh` - protection-status.sh - Display protection status for all git repositories
│   ├── `pull.sh` - pull.sh - Executable version of /pull command
│   ├── `push.sh` - push.sh - Executable version of /push command
│   ├── `QUICKSTART.md` - Quick Start — the hooks layer
│   ├── `README-TODO-INJECTION.md` - Global Todo Injection Hook
│   ├── `sentinel-lint.sh` - sentinel-lint.sh - Guards the dev-registry sentinel anchor in orchestrator files
│   ├── `session-git-init.sh` - ============================================================================
│   ├── `session-gitignore-propagate.sh` - SessionStart hook: append missing standard harness gitignore rules to project repo
│   ├── `session-info.sh` - s-info.sh — SessionStart: display environment info + tool quick reference
│   ├── `session-promote-hook.sh` - Description: SessionStart hook that promotes a cold session back to ramdisk.
│   ├── `session-tmpfs-banner.sh` - session-tmpfs-banner.sh — SessionStart hook (6th in the SessionStart hooks block).
│   ├── `session_start.sh` - SessionStart Hook - Display working environment info
│   ├── `start-fswatch-all.sh` - start-fswatch-all.sh - Start fswatch monitoring for all important repositories
│   ├── `stop-cleanup-allowlist.sh` - Stop Hook: Wipe any unconsumed /allow grant at turn end.
│   ├── `stop-overnight-timelock.py` - Stop Hook: Block conversation termination until overnight end-time
│   ├── `stop-spec-coverage-enforce.py` - Stop Hook: Block spec agent from exiting with < 100% monolith coverage
│   ├── `stop.sh` - stop.sh - wrapper for /stop slash command
│   ├── `subagent-stop-diff-check.sh` - SubagentStop hook: flag large diffs without minimum-diff justification
│   ├── `subagent-stop-guard-integrity.sh` - subagent-stop-guard-integrity.sh
│   ├── `subagentstop-codex-enforce.py` - Activation logic:
│   ├── `subagentstop-cp-enforce.py` - Description: SubagentStop hook for spec checkpoint enforcement (W6).
│   ├── `subagentstop-e2e-enforce.py` - Activation logic:
│   ├── `userprompt-bulk-commit-capability.py` - human prompt, NOT from an LLM-emitted Bash command
│   ├── `userprompt-consent-allowlist.sh` - UserPromptSubmit Hook: parse `/allow <pattern>` and write a single-use
│   ├── `userprompt-doc-sync-check.py` - UserPromptSubmit Hook: Periodic file deletion detection for doc-sync
│   └── `userprompt-tmpfs-pressure.sh` - userprompt-tmpfs-pressure.sh — UserPromptSubmit hook (4th block, appended).
├── policies/
│   ├── `specialist-degradation.v1.json` - json config
│   └── `tool-policy.v1.json` - json config
├── schemas/
│   ├── `context.v1.json` - json config
│   ├── `cycle-contract.v1.json` - json config
│   ├── `dev-report.v1.json` - json config
│   ├── `graphify-focused-subgraph.v1.json` - json config
│   ├── `graphify-prequery.v1.json` - json config
│   ├── `graphify-run.v1.json` - json config
│   ├── `qa-report.v1.json` - json config
│   ├── `registry.json` - json config
│   └── `test-plan.v1.json` - json config
├── scripts/
│   ├── install/
│   │   └── `tmp-cleanup-install.sh` - /usr/local/sbin/tmp-cleanup.sh
│   ├── modern-git-slot/
│   ├── overnight-git/
│   │   ├── `git-policy-shim` - unknown file
│   │   └── `git-selector` - unknown file
│   ├── spec-verify/
│   │   ├── `spec-verify-views.py` - Usage:
│   │   ├── `spec-verify.py` - Every non-blank, non-separator line from the monolith must appear
│   │   ├── `spec_verify_gated.py` - Three sibling checks that share the T5 ``is_strict_guide_mode`` gate and
│   │   ├── `spec_verify_mandate.py` - Activated only when the monolith declares ``guide_version: 1`` (or higher)
│   │   ├── `spec_verify_parsers.py` - Authoritative grammar: /root/docs/dev/specs/MONOLITH-WRITING-GUIDE.md R6.6
│   │   └── `spec_verify_summary.py` - Lives alongside `spec_verify_parsers.py` as a sibling sidecar because
│   ├── todo/
│   │   ├── `clean.py` - Preloaded TodoList for /clean workflow
│   │   ├── `close.py` - Three user-visible TodoSteps (flat-integer per agents/style-inspector.md
│   │   ├── `code-review.py` - Python script
│   │   ├── `deep-search.py` - Python script
│   │   ├── `dev-command.py` - This todo script generates workflow steps for the BA-delegated dev-command workflow
│   │   ├── `dev-overnight.py` - Preloaded TodoList for /dev-overnight workflow
│   │   ├── `dev.py` - Preloaded TodoList for /dev workflow
│   │   ├── `do.py` - Injects the 4-step /do workflow checklist via hook-todo-injection
│   │   ├── `doc-gen.py` - Python script
│   │   ├── `explain-code.py` - Python script
│   │   ├── `file-analyze.py` - Preloaded TodoList for /file-analyze workflow
│   │   ├── `optimize.py` - Python script
│   │   ├── `playwright-helper.py` - Python script
│   │   ├── `quick-prototype.py` - Preloaded TodoList for /quick-prototype workflow
│   │   ├── `redev.py` - Preloaded TodoList for /redev workflow. Delegates to dev.py (single source of truth).
│   │   ├── `refactor.py` - Python script
│   │   ├── `reflect-search.py` - Preloaded TodoList for /reflect-search workflow
│   │   ├── `research-deep.py` - Python script
│   │   ├── `security-check.py` - Python script
│   │   ├── `site-navigate.py` - Python script
│   │   ├── `spec.py` - Mirrors the ask.py structure in the knowledge-system scripts/todo directory
│   │   └── `test.py` - Preloaded TodoList for /test workflow
│   ├── `aggregate-dev-report.py` - Scans docs/dev/ for per-worker shard dev-reports matching a given task-id,
│   ├── `aggregate-permissions.py` - Usage: aggregate-permissions.py <qa-glob-or-dir> [pipelines.json]
│   ├── `analyze-folder-history.sh` - Description: Analyze Git history for folder to discover file creation patterns
│   ├── `analyze-git-edge-cases.sh` - Description: Analyze git history for edge cases from bug fix commits
│   ├── `apply-permissions.sh` - apply-permissions.sh — merge aggregated permissions JSON list into settings.json
│   ├── `blast-radius-tool.py` - Two phases:
│   ├── `break-overnight-lock.py` - Backdates end_time on every active overnight-state-*.json so
│   ├── `build-pipelines-from-triage.py` - Consumes PM triage schema (issues[] keyed by triage_index + pipeline_order[] +
│   ├── `canary-verify.sh` - Description: Cache-safe canary that behaviorally verifies the four core PreToolUse hooks.
│   ├── `check-file-references.sh` - File reference detection script - used by /clean command
│   ├── `check-overnight-reports.py` - Description: Validates all overnight required outputs declared by the active
│   ├── `check-overnight-reports.sh` - DEPRECATED — replaced by check-overnight-reports.py per spec-20260426-090235 P0/M5.
│   ├── `check-readme-freshness.sh` - Check README.md freshness for all major folders
│   ├── `check-security-hook-drift.sh` - Description: Audit always-on security-critical hook files against a cycle baseline SHA
│   ├── `checkpoint-prune.sh` - checkpoint-prune.sh — trim refs/checkpoints/* to the most recent N commits
│   ├── `cleanup-close-force-sentinel.sh` - Removes the force-close sentinel file for a given dev session.
│   ├── `cleanup-tests-folder.sh` - Description: Remove validators that don't match git edge cases, preserving reports/
│   ├── `close-scoring-decide.py` - Description: Decide which close_success_* event /close should issue based on
│   ├── `create-overnight-state.sh` - create-overnight-state.sh — Create overnight state file (v7 schema)
│   ├── `create-worktree.sh` - Create a git worktree from local HEAD (not origin/main).
│   ├── `derive-default-branch.sh` - Description: Resolve the repository's default branch name dynamically (handles main/master/any other).
│   ├── `detect-dead-functions.sh` - Shell script
│   ├── `detect-duplicate-content.sh` - Shell script
│   ├── `detect-hardcoded-paths.sh` - Shell script
│   ├── `detect-merge-conflicts.sh` - Shell script
│   ├── `detect-orphan-agents.sh` - Description: Detect agents not referenced by any command
│   ├── `detect-orphan-commands.sh` - Description: Detect orphan commands (one-time patterns, no todo script, unused)
│   ├── `detect-orphan-scripts.sh` - Description: Detect scripts not referenced by any command/agent/other script
│   ├── `discover-folders.sh` - Description: Dynamically discover project folders excluding system directories
│   ├── `execute-push.py` - Eliminates the timing window that exists when validate + push are && -chained
│   ├── `generate-folder-index.sh` - Description: Generate INDEX.md for folder (inventory of contents)
│   ├── `generate-folder-readme.sh` - Description: Generate README.md for folder (purpose and organization rules)
│   ├── `graphify-enrich.py` - graphify-enrich.py — pre-DEV focused subgraph extractor (runs between Step 7 and Step 8)
│   ├── `graphify-maintain.py` - graphify-maintain.py — Global Graphify cache lifecycle manager (REAL CLI)
│   ├── `graphify-query.py` - graphify-query.py — deterministic pre-BA graph hydrator (runs between Step 1 and Step 2)
│   ├── `graphify_lib.py` - graphify_lib.py — shared library for Graphify knowledge-graph integration
│   ├── `install-checkpoint-refspec.sh` - install-checkpoint-refspec.sh — idempotently add refs/checkpoints/* to
│   ├── `install-git-keystone.sh` - install-git-keystone.sh — wire the git-native reference-transaction keystone
│   ├── `iterate-failed-pipelines.py` - Reads pipelines JSON path; outputs iteration plan JSON to stdout. The orchestrator
│   ├── `lifecycle-baseline-import.sh` - Description: One-time idempotent migration — import current agent scores from agent-scores.json
│   ├── `lint-spec-id-centralization.py` - markdown from re-deriving a spec-id / views_dir / split_marker / cp_dir from a
│   ├── `migrate-test-to-tests.sh` - Description: Merge test/ folder into tests/ preserving all content (idempotent)
│   ├── `mint-git-blessed-token.sh` - mint-git-blessed-token.sh — issuer of the keystone blessed token (M12).
│   ├── `normalize-doc-names.sh` - normalize-doc-names.sh - Detect and report non-compliant documentation file names
│   ├── `orchestrator.sh` - Description: Agent orchestration coordinator for development and cleanup workflows
│   ├── `overnight-git-env.sh` - overnight-git-env.sh — prepare the overnight actor's git PATH + env (M11/AC9).
│   ├── `overnight-git-selftest.sh` - overnight-git-selftest.sh — launch git-version + symref self-test (M8, M16).
│   ├── `overnight-status.sh` - overnight-status.sh — Zero-LLM overnight session status query
│   ├── `plan-style-inspection.sh` - Description: Discover auditable files and split into groups for parallel style inspection
│   ├── `precommitted-recovery.sh` - Description: Recovery path helpers for nothing_to_commit_precommitted detection.
│   ├── `qa-manifest-guard.py` - Dual-mode tool per BA spec docs/dev/ticket-20260529-081014.md M4:
│   ├── `qa-report-stale-iter-lint.py` - lacks an explicit resolution marker
│   ├── `refine-context.sh` - refine-context.sh — merge QA-refined context with original context
│   ├── `regen-index-dirs.py` - hand-written prose outside the generated stats+tree block), then regenerate the
│   ├── `repair-venv.sh` - repair-venv.sh — durably restore a Python venv when its bin/python3 symlink target is missing.
│   ├── `resolve-close-report.sh` - Resolve the close-report path for a given TASK_ID using subproject path-walk.
│   ├── `resolve-dev-report.py` - Usage:
│   ├── `resolve-spec-artifacts.py` - spec-id resolver shared by /spec finalize and every /dev* consumer)
│   ├── `runcode-watchdog.py` - Watchdog process for browser_run_code timeout enforcement
│   ├── `scan-project.sh` - Description: Scan project structure and detect project type
│   ├── `score-inject.sh` - Description: Emit a prompt-injection text block describing an agent's current rank/range
│   ├── `score-update.sh` - Description: Update agent score by appending an entry to the lifecycle JSONL log.
│   ├── `spec-check.py` - Subcommands: check-in, mark, waive, status, check-out, unlock
│   ├── `stage-owned-hunks.py` - Stages ONLY this cycle's owned hunks within a single already-authorized file,
│   ├── `step7-spec-update.py` - Step 8 (Spec-update dispatch) reference harness — task 20260524-205206 iter-2
│   ├── `update-gitignore.sh` - update-gitignore.sh - Auto-update .gitignore with project-specific rules
│   ├── `update-overnight-state.sh` - update-overnight-state.sh — Atomically update overnight state file
│   ├── `write-bulk-commit-sentinel.py` - Invoked from commands/commit.md Step 5 (BULK=true) to authorize the
│   ├── `write-codex-enforce.sh` - Writes codex-enforce.json into the dev-registry for the given session.
│   ├── `write-commit-grant.py` - Invoked from `commands/commit.md` Step 5 (non-bulk mode) to author a
│   ├── `write-e2e-enforce.sh` - Writes e2e-enforce.json into the dev-registry for the given session.
│   └── `write-qa-mode.sh` - Write or update qa_mode field in the QA sentinel file for a dev-registry session.
├── skills/
│   ├── ui-anti-pattern-catalog/
│   │   └── `SKILL.md` - Apply the 58-rule anti-pattern catalog (10 Color + 5 Motion + 5 Typography + 5 Spacing + 2 Glass + 5 Heuristic + 4 UX-Writing + 5 Form + 4 Interactive + 5 Nielsen + 8 AI-slop) against a Playwright page. Outputs aesthetic_findings[] with category=hard_defect|taste_heuristic, with the SCHEMA-ENFORCED severity hard-cap on taste_heuristic at minor + advisory:true. Use during ui-specialist Phases 4.5/5/6.5.
│   ├── ui-apca-contrast/
│   │   └── `SKILL.md` - Run APCA Lc text-contrast measurement on a Playwright page in BOTH light and dark color schemes. Returns deterministic apca.* findings against rule-map.json. Use during ui-specialist Phase 6 (Accessibility).
│   ├── ui-axe-injector/
│   │   ├── vendor/
│   │   └── `SKILL.md` - Inject axe-core 4.10.0 into a Playwright page and run the WCAG 2.1 a/aa rule set; emit a single deterministic findings list against rule-map.json. Use during ui-specialist Phase 6 (Accessibility) before ui-contextual-heuristics.
│   ├── ui-beauty-score/
│   │   └── `SKILL.md` - Aggregate aesthetic_findings, automated_findings, and alignment_measurements into a single 1.0-10.0 beauty_score plus 7 weighted sub-scores and a 0.0-1.0 consistencyScore. Pure calculation step — never fails. Use during ui-specialist Phase 7 (Aggregation) AFTER all other ui-* skills have completed and BEFORE writing the final 6-channel report.
│   ├── ui-contextual-heuristics/
│   │   └── `SKILL.md` - Five LLM-driven contextual accessibility insights that axe cannot detect (heading hierarchy, link text, focus order, color reliance, decorative-as-interactive). MUST receive axe findings as input and dedup against them. Use during ui-specialist Phase 6 (Accessibility) AFTER ui-axe-injector.
│   ├── ui-shared/
│   │   ├── `anti-pattern-catalog.yml` - yml config
│   │   ├── `report-schema.json` - json config
│   │   ├── `review-phases.yml` - yml config
│   │   └── `rule-map.json` - json config
│   ├── ui-state-matrix/
│   │   └── `SKILL.md` - Verify presence of 7 interactive states (default / hover / focus / active / disabled / loading / error / success) on key interactive elements. Returns deterministic state.* findings + state_coverage_pct + not_applicable[]. Use during ui-specialist Phase 4 (Interactive Element Visual Testing).
│   └── ui-token-conformance/
│       └── `SKILL.md` - Conditional capability — measure design-token conformance (color/spacing/typography) of computed CSS values against a project's declared token source (DTCG / tailwind.config.js / theme.ts). If no token source is detected, emit capability_unavailable to unknowns and DO NOT raise findings on guesses. Use during ui-specialist Phase 5 (Aesthetic).
├── specs/
│   ├── 20260514-174852/
│   ├── qa-c7-test/
│   └── qa-c7-test-w/
├── subagents/
├── templates/
│   ├── `overnight-spec.md` - Spec: <issue_description>
│   └── `spec-template.md` - Spec: <issue_description>
├── tests/
│   ├── cycle1-baseline-20260507-142952/
│   │   ├── `realpath_audit.py` - Audit realpath behavior in the guard for the codex finding.
│   │   ├── `run_ac1.py` - AC-1 verification: pretool-cp-state-write-guard.py.
│   │   ├── `run_ac1_v2.py` - AC-1 verification v2: pretool-cp-state-write-guard.py with correct fixture paths.
│   │   ├── `run_ac2.py` - AC-2 verification: subagentstop-cp-enforce.py orphan finalization.
│   │   ├── `run_ac3.py` - AC-3 verification: agent_resolver.py inactive cp-state non-authoritative + collision fail-closed.
│   │   ├── `setup_fixtures.py` - Create test fixtures via Python (Bash heredoc/echo to cp-state is blocked by hooks).
│   │   └── `symlink_test.py` - Test codex's symlink/realpath finding for AC-1 guard hook.
│   ├── generated/
│   │   ├── 20260520-221452/
│   │   ├── 20260521-090100/
│   │   ├── 20260521-090200/
│   │   ├── 20260521-090300/
│   │   ├── 20260522-000000/
│   │   ├── 20260522-080646-A/
│   │   ├── 20260522-080646-B/
│   │   ├── 20260522-080646-D/
│   │   ├── 20260524-122910/
│   │   ├── 20260524-122947/
│   │   ├── 20260524-125300-A/
│   │   ├── 20260524-125300-B/
│   │   ├── 20260524-125300-C/
│   │   ├── 20260524-125300-D/
│   │   ├── 20260524-125300-push/
│   │   ├── 20260524-133650/
│   │   ├── 20260524-171714/
│   │   ├── 20260524-172805/
│   │   ├── 20260524-205206/
│   │   ├── 20260524-205459/
│   │   ├── 20260525-050824/
│   │   ├── 20260525-095242/
│   │   ├── 20260526-052559/
│   │   ├── 20260526-053746/
│   │   ├── 20260527-132200/
│   │   ├── 20260529-080709/
│   │   ├── 20260529-081014/
│   │   ├── 20260529-210616/
│   │   ├── 20260529-211406/
│   │   ├── 20260530-105221/
│   │   ├── 20260530-165718/
│   │   ├── 20260530-170350/
│   │   ├── 20260531-112831-bug1/
│   │   ├── 20260604-204954/
│   │   ├── 20260611-100500/
│   │   ├── 20260614-093452/
│   │   ├── 20260614-205834/
│   │   ├── dev-20260530-144032/
│   │   ├── dev-20260531-134455/
│   │   ├── dev-20260531-193000/
│   │   ├── dev-20260615-213842/
│   │   ├── dev-20260616-204226/
│   │   └── `manifest.json` - json config
│   ├── instructions/
│   │   ├── `execution-guide.md` - AI Test Execution Guide
│   │   └── `validation-guide.md` - AI-Driven Validation Guide
│   ├── reports/
│   │   ├── `completion-test-20260107-104018.md` - Test Execution Completion Report
│   │   ├── `edge-case-analysis.json` - json config
│   │   ├── `execution-report-test-20260107-095503.json` - json config
│   │   └── `execution-report-test-20260107-104018.json` - json config
│   ├── score-inject-contract/
│   │   ├── `runtime-verify.sh` - Description: Runtime verifier for the 4-field score-injection echo contract.
│   │   └── `test-inject-branches.sh` - Description: Verify scripts/score-inject.sh emits INJECTION_PROOF block with
│   ├── score-lifecycle-contract/
│   │   └── `test-lifecycle-cas.sh` - Description: Verify CAS and append-only invariants for scripts/score-update.sh and
│   ├── scripts/
│   │   ├── `validate-checklist-completeness.py` - Validator: validate-checklist-completeness
│   │   ├── `validate-chinese-content.py` - Validator: validate-chinese-content
│   │   ├── `validate-claude-md-protection.py` - Validator: validate-claude-md-protection
│   │   ├── `validate-debug-file-age.py` - Validator: validate-debug-file-age
│   │   ├── `validate-file-naming.py` - Validator: validate-file-naming
│   │   ├── `validate-optionality-language.py` - Validator: validate-optionality-language
│   │   ├── `validate-posttool-ac-dev-20260524-205811.py` - QA verification for dev-20260524-205811: posttool-allowlist-consume.py AC tests
│   │   ├── `validate-step-numbering.py` - Validator: validate-step-numbering
│   │   ├── `validate-todowrite-requirement.py` - Validator: validate-todowrite-requirement
│   │   ├── `validate-venv-usage.py` - Validator: validate-venv-usage
│   │   └── `validate-workflow-json-cleanup.py` - Validator: validate-workflow-json-cleanup
│   ├── `integration-test.sh` - integration-test.sh - Integration tests for git tracking solution
│   ├── `test-lock-detection.sh` - Test script to verify git lock file detection and handling
│   ├── `test_aggregate_dev_report.py` - Unit tests for scripts/aggregate-dev-report.py
│   ├── `test_graphify_scripts.py` - tests/test_graphify_scripts.py — smoke tests for scripts/graphify_lib.py
│   ├── `test_graphify_workflow_contract.py` - tests/test_graphify_workflow_contract.py — contract tests for graphify agent registration
│   ├── `test_overnight_loop_tz.py` - Verifies the overnight loop hook compares end_time correctly against the
│   ├── `test_resolve_spec_artifacts.py` - resolver) + the static centralization lint (AC-B4 cases 1-12, task 20260530-092123)
│   ├── `test_specialist_yield.py` - Tests use a tmp dir for the yield log and the bundled production policy file
│   └── `verify-stop-spec-session-isolation.sh` - QA verification harness for stop-spec-coverage-enforce.py session isolation fix.
├── `ARCHITECTURE.md` - Architecture — `.claude` Agent Operating System
├── `CLAUDE.md` - CLAUDE.md
├── `history.jsonl` - jsonl file
├── `LICENSE` - unknown file
├── `mcp-needs-auth-cache.json` - json config
├── `NESTED-REPO.md` - Nested Repo Sentinel
├── `NOTICE` - unknown file
├── `playwright-storage-state.json` - json config
├── `push.sh` - 
├── `session.log` - log file
├── `settings.json` - json config
├── `settings.json.bak-20260523-184533` - bak-20260523-184533 file
├── `settings.local.json` - json config
├── `workflow-019e0d4c-09bf-77a1-a19a-cd74736ab48e.json` - json config
├── `workflow-019e0d52-4184-7e83-9695-bce01c179a8d.json` - json config
├── `workflow-019e1d0c-d666-76e0-a080-10a6c4811cb4.json` - json config
├── `workflow-019e1d17-3e27-77a0-891b-5d9aef797d53.json` - json config
├── `workflow-11d0da00-24f0-4e23-bbe0-bc15d31b993b.json` - json config
├── `workflow-1f9f0472-7a89-4cfa-87f2-c85616fed777.json` - json config
├── `workflow-215eec0e-0e9c-4f81-bd52-b73036e3d33a.json` - json config
├── `workflow-30b4bbbc-a873-4ba8-b8fd-804dc05492bc.json` - json config
├── `workflow-483e030c-3ab6-42d0-973e-8a2a4b8b8806.json` - json config
├── `workflow-49d0cdde-0555-4c6a-9354-0076adf7db42.json` - json config
├── `workflow-4e6b0a9e-bdd6-47ca-8ec4-95cae992867d.json` - json config
├── `workflow-758ea7a9-12e8-4854-9799-3e03dfb2ec3e.json` - json config
├── `workflow-78c6f989-5b0e-4d7b-b692-6cabbe0008bf.json` - json config
├── `workflow-d5e5ffb8-89bd-409f-a8c0-d00f45ecbce3.json` - json config
├── `workflow-dd3a870c-9440-4274-896f-462dfe972646.json` - json config
├── `workflow-eaa1077b-49ad-4697-8e01-e4a923d2b116.json` - json config
├── `workflow-edfda281-beb8-434f-a45b-2a8053975db8.json` - json config
└── `workflow-fe05ca9a-7892-40ea-a3ba-660db57180b9.json` - json config
```
<!-- /AUTO:index-stats -->

# 


# dot-claude


# .claude


# dot-claude


# .claude


# dot-claude


# .claude

---
*Auto-generated by doc-sync hook.*