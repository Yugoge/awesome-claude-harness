# reference

<!-- AUTO:index-stats -->
*Last updated: 2026-10-06T01:18:02Z*
**Total entries**: 59
**Convention**: kebab

## Tree
```
reference/
├── `abandoned-cycles-20260905.md` - Abandoned cycles — terminal determination
├── `attribution-journal-consumer-cutover-20261004.md` - Attribution-journal consumer cutover: APPLIED (task 20261004-001927)
├── `attribution-journal-cutover-flip-plan-20261003.md` - Attribution-journal cutover: FLIP PLAN (Phase D, plan only)
├── `attribution-journal-phase0-facility.md` - Write-time attribution journal — Phase 0 facility notes
├── `bash-write-targets-capability-gap-20261005.md` - bash_write_targets.py capability gap: a fail-open/fail-shut pair from one resolution gap
├── `checkpoint-mechanism.md` - Auto-Commit / Checkpoint Mechanism
├── `claim-verification-methodology-20260925.md` - backlog claim 有效性核实方法论（2026-09-25 夜）
├── `close-commit-failure-inventory-20260927.md` - /close 与 /commit 失败方式全量清单(2026-09-27)
├── `close-commit-zero-failure-mechanism-20260928.md` - Close/commit zero-failure mechanism — converged design (2026-09-28/29)
├── `codex-sandbox-verification.md` - Codex CLI Sandbox Verification Report
├── `commit-dryrun-close-gate-ruling.md` - /commit dry-run close-gate relaxation: ruling record
├── `commit-gate-bypass-via-background-exec-20261005.md` - Commit gate bypassed by background execution — 2026-10-05
├── `controller-error-taxonomy-20260924.md` - 控制器错误归纳（2026-09-24 夜 spec 台席会话）
├── `core-context-refactor-plan.md` - Core Context Refactor Plan (Plan-of-Record)
├── `dev-command-20261003-020648-takeover-record.md` - Takeover record — cycle `dev-command-20261003-020648` over interrupted `dev-command-20261002-170011`
├── `fswatch-quickref.md` - FSWatch Quick Reference Card
├── `generated-tests-policy.md` - `tests/generated/` policy — tracked but ignored, on purpose
├── `git-fswatch.md` - Git File Watcher (fswatch) Documentation
├── `graphify-integration.md` - Graphify Knowledge Graph Integration
├── `harness-defects-20260906-controller.md` - 控制器实测缺陷记录 — 2026-09-06
├── `harness-fix-status-20260905.md` - Harness fix status — R1..R20 of `spec-20260904-harness-fixes.md`
├── `harness-gaps-found-20261005.md` - Harness gaps found during the 2026-10-05 tree-to-zero campaign
├── `harness-issues-backlog.md` - 待下次 spec 处理的 harness 问题清单（当前有 harness 修复在 worktree 跑，新问题只记录不并行修）
├── `infeasibility-without-execution-20261006.md` - An infeasibility judgment that was never executed is a hypothesis, not a finding
├── `install-compatibility-matrix.md` - Install compatibility matrix
├── `lane-pol-catchup-plan-20260808-035658-lanepolcatchup.md` - LANE-POL Catch-Up Plan — origin/master → fix/dev-fanout-gatekeeper-20260717
├── `launch-plan.md` - Launch Plan — ROI-ranked channels, gated on recorded evidence
├── `lock-file-handling.md` - Git Lock File Handling
├── `master-origin-reconciliation-gap-20261005.md` - No history-preserving reconciliation path exists between local master and diverged origin/master
├── `mat-doc10-writer-order.v2.json` - JSON config: schema, contract_id, spec_id, lane_id, published_by_task_id
├── `monolith-split-plan.md` - Monolith Split Plan (Plan-of-Record)
├── `MORNING-20260907.md` - 晨间交接 — 2026-09-07
├── `open-findings-from-read-only-cycles-20261005.md` - Open findings from read-only cycles — extracted 2026-10-05
├── `overnight-cycle-20260809-013317-shared-file-attribution-20260914.md` - Attribution of unattributed content in four shared files, cycle 20260809-013317
├── `overnight-reference.md` - Overnight reference (maintainer-facing)
├── `overnight-worktree-20260810-test-gaps-20261005.md` - Overnight 20260810 worktree test landing: diagnosis of 22 files
├── `overnight-worktree-test-gaps-20261005.md` - Overnight 20260809 worktree test landing: diagnosis of 15 failures
├── `overwrite-prohibition.md` - Prohibition on wholesale replacement of an existing file
├── `paseo-daemon-caller-id-rollout-20261004.md` - `--caller-id` enforcement: immediate rollout, no deploy step, doc gap
├── `paseo-daemon-concurrent-staging-triple-repro-20260904-181435-20260914.md` - Triple, independent reproduction of the shared-file concurrent-staging defect
├── `paseo-daemon-shared-file-attribution-20260913.md` - Attribution of unattributed content in the three paseo-daemon shared files
├── `paseo-daemon-teachings-20260910.md` - paseo-daemon 控制器教训合并与运行契约（2026-09-10）
├── `positioning.md` - Positioning
├── `push-gate-reconciliation-decision.md` - Push-gate reconciliation — decision to keep
├── `qa-status-gate-gap-orchestrator-side-20261005.md` - The QA-verdict gate does not cover the orchestrator — still open 2026-10-05
├── `quarantine-record-dev-20260915-020044.md` - Quarantine record: phantom `/dev` cycle `dev-20260915-020044`
├── `recoverable-discard-register-20261005.md` - Recoverable-discard register — 2026-10-05 tree-to-zero campaign
├── `rename-execution-plan.md` - Rename execution plan — `awesome-claude-harness` → `claude-code-guardrails`
├── `restart-detector-quota-text-match-false-positive-20260915.md` - `/restart` interruption detector: textual quota-proxy instead of structural liveness check
├── `roadmap-decomposition-productization.md` - Roadmap: Monolith Decomposition + Productization
├── `slashcommand-quick-reference.md` - Slash Command Quick Reference
├── `subagentstop-payload-s0-measurement-20260929.md` - SubagentStop payload availability — S0 measurement (2026-09-29)
├── `test-suite-overhaul-plan.md` - Test Suite Overhaul Plan (Plan-of-Record)
├── `tmp-cleanup-convention.md` - Ad-hoc scratch directory convention
├── `tmpfs-persistent-backups-20261005.md` - Persistent-disk backups of the tmpfs-only checkout (2026-10-05)
├── `venv-repair.md` - venv-repair — restoring `~/.claude/venv` when interpreter symlinks break
├── `workflow-bookmark-orphans-20261005.md` - Root-level `workflow-*.json` bookmarks have no lifecycle management; 22/22 are orphans
├── `workspace-disposition-criteria-20261005.md` - Workspace disposition criteria, and the five verdicts that existed only in a transcript
└── `worktree-685c203b-remaining-18-disposition-20261005.md` - Worktree `overnight-20260809-685c203b`: disposition of the remaining 18 items
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*