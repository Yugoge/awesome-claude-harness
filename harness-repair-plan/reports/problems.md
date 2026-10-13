# Harness problem inventory (2026-10-09)

110 problems, deduplicated from 7 thematic investigations + 7 per-file partitions, adversarially verified. Severity counts: critical 10, high 43, medium 47, low 10

## critical (10)

### X01. /clean cannot delete or rewrite anything: every change path is hook-blocked and the escapes are human-only and per command
- Evidence: pretool-bash-safety.sh:1901-2019 runs before the /do bypass at :2752; tool-policy.v1.json:347-385; pretool-claude-config-guard.py:48-66; pretool-git-privilege-guard.py:179; the 2026-05-17 run shows files_deleted 0
- Fixed in: P3 PR-A (cleanup done as a PR); P4 PR-B (/clean replaced; D3)

### X02. /clean aims at the wrong targets: 0 commands, agents or hooks audited; prompt-inspector covers 1.4% of prompt lines
- Evidence: plan-style-inspection.sh:27,32 shows commands=0, agents=0, hooks=0; prompt-inspector.md:83-108 matches 362 of 25,268 lines
- Fixed in: P4 PR-B

### X06. A UserPromptSubmit hook re-injects the full command file
- Evidence: prompt-workflow.py:1278-1280; /dev 108,227 B, /close 119,654 B
- Fixed in: P1 PR-0; P3 PR-A (injection budget)

### X07. Agents cannot delete anything, so junk gets committed
- Evidence: bash_execution_boundary.py:3862; 'stage' committed in e227a70; 349 files added and 2 deleted since 2026-07-17
- Fixed in: P4 PR-B (D3)

### X08. No feedback loop: CI aborts at collection and has been red since 2026-07-16
- Evidence: tests/test_tool_policy_inference_note.py:39-40; last green run 2026-07-16
- Fixed in: P1 PR-0; P3 PR-A

### X09. No size budget or ratchet exists
- Evidence: No budget in CI or scripts; 120,457 to 327,782 lines between July and October
- Fixed in: P3 PR-A; P8

### X10. Agents edit the harness they run under, inside a live checkout shared by concurrent sessions
- Evidence: 85 of 188 commits since 07-17 touch hooks/ or settings; 02fe8fe landed settings 'whole'
- Fixed in: P2 Wave 1 (config dir is no longer a repo; manifest restore); P3 PR-A (native deny); P5 PR-C1 (Bash tamper rule)

### X21. 'You are me' versus 19 of 21 human-only commands drove ~19 grant namespaces
- Evidence: teachings:132-139; backlog:58
- Fixed in: P5 PR-C1; D10 (measured revisit)

### X77. Moving the live tree to a new path would break the boot restore, sync-backup and real-path references
- Evidence: NESTED-REPO.md:7-11 (/root/.claude.bak mirrored every 5 min by /root/sync-backup.sh); 37 tracked files / 51 references to /dev/shm/dev-workspace/dot-claude (git grep)
- Fixed in: P2 Wave 1 (paths unchanged; ext4 releases; ensure-layout at boot; simulated boot)

### X79. The checkout is Claude Code's config dir: the CLI writes settings and owns credentials and transcripts inside it
- Evidence: .gitignore:4,16-26 ignore .credentials.json, projects/, todos/, plugins/, history.jsonl; 02fe8fe records model and tui changes as unattributed; settings.json has tui, the template does not
- Fixed in: P2 Wave 1 (source moved out; CLI keys untouched); P7 PR-D

## high (43)

### X03. /clean standards and doc-sync add files: archive instead of delete, and an INDEX in every folder regenerated on each edit
- Evidence: clean.md:95,139-143; doc_sync/main.py:107-124; 85 INDEX/README files; 359 of 774 commits touch them
- Fixed in: P3 PR-A

### X04. Keep/delete detectors protect dead code
- Evidence: check-file-references.sh:331,347 returns 118 of 119 scripts as 'cannot delete'; detect-orphan-scripts.sh found 7 of 24 dead scripts
- Fixed in: P3 PR-A (AST reach); P4 PR-B

### X100. Pipeline shape, the main cost driver, was never put to the user
- Evidence: 17 steps, ~14 dispatches, only step 10 writes code
- Fixed in: P0 (D18); P6 PR-C2

### X103. Nothing verifies completion claims in product cycles
- Evidence: controller-error-taxonomy-20260924.md:7-22, 0 of 23 caught
- Fixed in: P6 PR-C2 (claims checked against recorded exit codes)

### X11. Every incident fix adds a hook, rule or doc, and nothing is retired
- Evidence: 42 of 43 fix commits are net growth; 0 hook deletions since 2026-06-16
- Fixed in: P3 PR-A; P8

### X12. Rules carry task-id stamps pointing at gitignored evidence and never expire
- Evidence: 329 task ids, 177 unresolvable; 0 review_by clauses
- Fixed in: P3 PR-A (register, stamp lint); P5; P6

### X13. The system is bigger than one agent can hold, so copies drift
- Evidence: 91 files exceed 600 lines; 23 charter variants; laneb-integration-gate.py has 9,076 lines
- Fixed in: P3 PR-A; P5; P6

### X14. 'Record, don't fix' backlog has no consumer and is a mandatory read for BA
- Evidence: harness-issues-backlog.md:27; 697 KB; agents/ba.md:18
- Fixed in: P3 PR-A; P8

### X15. Human-only escapes and the 'auto-bulk:'-only commit guard pile work into huge unreviewed commits
- Evidence: git-privilege-guard.py:179; 257 of 774 commits bulk-style; 4828bb4 is +42,010 lines
- Fixed in: P2 Wave 1 (no harness commits on live); P3 PR-A; P8

### X16. Concurrent writers in one tree produced ~19k lines of attribution machinery
- Evidence: 40 files / 18,934 lines; 20 commits marked '归属未定' (attribution undetermined)
- Fixed in: P2 Wave 1; P7 PR-D (D7b)

### X18. Enforcement theatre: no-effect hooks and false enforcement claims
- Evidence: pretool-orchestrator-prompt-purity.py:22-23 always exits 0; ledger shows 0 of 72 enforced
- Fixed in: P1 PR-0; P3 PR-A; P4 PR-B

### X20. Model failure modes: additive bias, local fixes, over-documentation, claiming completion without evidence
- Evidence: Median commit message 331 B to 1,943 B; b108c16
- Fixed in: P8 (CI-artifact eligibility); P6 PR-C2 (claim verification); P3 PR-A

### X22. Every rule lives in both prompt and hook layers and drifts
- Evidence: a6e19d9, 8d0ff95 vs teachings:124,287
- Fixed in: P3 PR-A (owner layer in register); P6 PR-C2 (generated hook-rule index, duplicate lint)

### X23. /close and /commit carry 474 failure points
- Evidence: close-commit-failure-inventory-20260927.md:7-11
- Fixed in: P4 PR-B; P6 PR-C2

### X25. Public-product machinery sits on a personal tool and is permanently red
- Evidence: check-public-core 79 FAIL; release.yml 0 runs
- Fixed in: P4 PR-B (D1; private-literal check kept)

### X26. Real-work gaps: no secret scan, no continuation record, an uncommitted restart fix, no idle watchdog
- Evidence: MORNING-20260907.md:69-78; teachings:636,681-688,712-721
- Fixed in: P5 PR-C1; P8 (seeded issues)

### X27. Every tool call pays for many interpreter launches
- Evidence: No-op Bash: 22 hooks, 724 ms, 123 launches
- Fixed in: P1 PR-0; P3 PR-A; P5 PR-C1

### X28. Single-tool hooks are registered for every tool
- Evidence: pretool-subagent-enforce.py imports jsonschema before its tool check at :317
- Fixed in: P1 PR-0

### X29. settings.json drifts from the template, and CI tests a config nobody runs
- Evidence: 83 vs 73 entries; 75 vs 10 commits; baseline.yml:63-64
- Fixed in: P2 Wave 1 (harness-owned keys rendered); P7 PR-D (template plus overlay)

### X30. Grant and consent sprawl
- Evidence: userprompt-consent-allowlist.sh is 756 lines; ~19 namespaces
- Fixed in: P5 PR-C1

### X34. Role resolution ignores payload.agent_type and fails open when the role is unresolved
- Evidence: agent_resolver.py:8-12 order is subagent_type, cp-state, agent-index; pretool-tool-policy.py:348-356 exits 0; CLI 2.1.295 sends agent_type
- Fixed in: P3 PR-A (moved forward from PR-C1)

### X36. Self-locking defects in worktree-guard and the Stop coordinator
- Evidence: pretool-worktree-guard.sh:73-79; stop-workflow-coordinator.py:175-176; auto-commit.sh:54
- Fixed in: P1 PR-0

### X37. Hidden couplings would break Stop or publication if deleted naively
- Evidence: stop-workflow-coordinator.py:37, :40, :63, :68; git-privilege-guard.py:1497-1507; bash-safety.sh:289; obligation grammar referenced from lib/obligation.py:5 and schemas/obligation.v1.json:5
- Fixed in: P4 PR-B and P5 PR-C1 (same-commit edits)

### X38. Runtime state is written into the source tree
- Evidence: claude_home.py:48-60; a no-op session writes >=5 paths
- Fixed in: P2 Wave 1 (CLI writes go to the config dir); P7 PR-D

### X39. Split-brain state resolver
- Evidence: git-privilege-guard.py has 13 /tmp literals; bash-safety.sh:1390,1686
- Fixed in: P7 PR-D

### X40. The source of truth lives on tmpfs, and master drifted 139 ahead / 7 behind
- Evidence: NESTED-REPO.md:7-11
- Fixed in: P1 (delta exported); P2 Wave 1 (source in ext4 releases; no live repo)

### X46. Prompt-layer load is extreme
- Evidence: 1,575,620 B; qa ~47.3k on invoke (plugin details), loaded 4x
- Fixed in: P6 PR-C2

### X47. Hand-copied boilerplate makes up 15.9% of prompt lines
- Evidence: codex block 707 lines in 12 agents; charter in 23
- Fixed in: P6 PR-C2; P4 PR-B

### X48. Plumbing and inline schemas are embedded in prompts
- Evidence: 209 of 218 qa keys are absent from qa-report.v2
- Fixed in: P6 PR-C2

### X49. Some prompt bash cannot run
- Evidence: route_finding is undefined at commit.md:317,336,357
- Fixed in: P6 PR-C2

### X50. 17 contradictions between prompts and hooks
- Evidence: CLAUDE.md:57,102,117,125
- Fixed in: P1 PR-0; P6 PR-C2

### X58. Isolation worktrees bypass the branch firewall
- Evidence: The CLI bundle contains bgIsolation; CLAUDE.md:82-86
- Fixed in: P5 PR-C1

### X60. The test suite is red and wasteful
- Evidence: 371 failed / 20 errors / 765 skipped
- Fixed in: P3 PR-A

### X62. ~305 files / ~64k lines are verified dead
- Evidence: Partition digests
- Fixed in: P3 PR-A

### X65. Stray tracked junk and duplicates
- Evidence: stage (e227a70), .r05_part*.json; templates/overnight-spec.md is a symlink, so both templates are kept
- Fixed in: P3 PR-A

### X68. Server-side gates can be forged by the gated party
- Evidence: gh api: permissions.admin true; baseline.yml:10-13
- Fixed in: P3 PR-A; P8 (D14 PAT)

### X69. Live-update hazard: a pull can delete a registered hook while sessions run
- Evidence: git-fswatch.sh:174, :210
- Fixed in: P1 (fswatch stopped); P2 Wave 1 (release flips); P3 PR-A (pullsafe)

### X70. The earlier live migration mechanics were unsafe
- Evidence: mv -T of a dir onto a symlink gives rc=1
- Fixed in: P2 Wave 1

### X78. /pull or fswatch on live would rebase local commits onto new PRs while sessions run
- Evidence: hooks/pull.sh:28 stash, :120 pull --rebase, :126-147 leaves the rebase in progress; git-fswatch.sh:210, :220
- Fixed in: P1 (freeze before the first merge; no /pull)

### X80. Supply-chain path to a root host through auto-merge, fork PRs, issue text and public reports
- Evidence: gh api: public, allow_forking true, has_issues true, admin true, allow_auto_merge null
- Fixed in: P3 PR-A (eligibility function; D13 fork approvals); P8 (D14 PAT; owner-only input; verified-merge installs)

### X81. QA live-E2E and role limits fail open once the agent-index writer is gone
- Evidence: subagentstop-e2e-enforce.py:5-13 fail-open; pretool-cp-checkin.py:155,182 is the only writer
- Fixed in: P3 PR-A (before the PR-B deletion)

### X84. The prompt diet relocates rules but cannot retire them
- Evidence: Manifest with no 'retired' disposition; 512 MUST; 17 steps and ~14 dispatches kept
- Fixed in: P6 PR-C2 (retired dispositions; D18)

### X99. Live harness work between P0 and Wave 1 would be dropped
- Evidence: ~10 commits per day in October
- Fixed in: P1 (freeze plus delta export before the first merge)

## medium (47)

### X05. /clean is bloated and contradicts harness rules
- Evidence: 2,665 prompt lines, ~35 dispatches, ~420k tokens per run; clean.md:223 run_in_background:true
- Fixed in: P1 PR-0; P4 PR-B

### X101. No rule had a single owning layer
- Evidence: Prompts restate hooks
- Fixed in: P3 PR-A; P6 PR-C2

### X102. Per-command /do and /allow round-trips continue for product work
- Evidence: C1 deferred
- Fixed in: P2 Wave 1 (weekly counts); D10

### X110. /restart cross-account candidate fan-out is unaddressed
- Evidence: backlog #146
- Fixed in: P3 PR-A (seeded issue); P8

### X17. Quota-recovery machinery generates its own incidents
- Evidence: subagent_restart.py has 1,264 lines; a 486-line incident doc
- Fixed in: P5 PR-C1; P3 PR-A

### X19. Over-compliance gets fixed by adding exception text
- Evidence: de25fe0; MUST appears 512 times
- Fixed in: P6 PR-C2 (retire dispositions, D18); P3 PR-A

### X24. Oscillating rulings: quota burn, Codex default, honest terminal
- Evidence: teachings:80 vs :83; teachings:103 vs CLAUDE.md:98
- Fixed in: P0 (D12, D4, D15)

### X31. Duplicated parsing: 9 lexers, 5 git locators
- Evidence: git_command_classifier.py:361, git_clean_guard.py:134, allowlist.py:463, ...
- Fixed in: P5 PR-C1

### X32. Dead, never-registered and misdocumented hooks
- Evidence: 31 of 112 unregistered; posttool-git-warn.sh == post-commit-warn.sh
- Fixed in: P1 PR-0; P3 PR-A

### X33. Self-policing dominates the hook surface
- Evidence: 70 of 86 scripts enforce harness rules; 11 can never block
- Fixed in: P3 PR-A; P4 PR-B; P5 PR-C1

### X35. Hook side effects keep the tree dirty
- Evidence: doc-sync patches INDEX.md and CLAUDE.md
- Fixed in: P3 PR-A

### X41. .gitignore has become a subsystem with unanchored rules
- Evidence: .gitignore:183-184
- Fixed in: P3 PR-A; P7 PR-D

### X42. A fresh install is broken, and two installers contradict each other
- Evidence: settings.json has 134 /root/.claude lines; the installer registers 2 of 83 hooks
- Fixed in: P4 PR-B; P7 PR-D

### X43. The config dir is confused with the harness home
- Evidence: posttool-todo-tracker.py:57-58; subagent_restart.py:150,820
- Fixed in: P2 Wave 1; P7 PR-D

### X44. Tests share live /tmp and the live settings file
- Evidence: 20 tests use real /tmp/claude-* paths
- Fixed in: P3 PR-A

### X45. Host and private literals sit in code in a public repo
- Evidence: paseo-daemon-ledger.py:133,1626,3010; 70 tracked files
- Fixed in: P3 PR-A; P4 PR-B; P7 PR-D (untracked overlay)

### X51. Dangling references and dead config
- Evidence: 17 dead Skill() denies; prompt-workflow.py:330-335
- Fixed in: P1 PR-0; P3 PR-A

### X52. 58 test files pin prompt wording
- Evidence: Up to 638 'assert ... in' lines
- Fixed in: P3 PR-A; P6 PR-C2

### X53. Rarely or never dispatched agents are kept up to date
- Evidence: git-edge-case-analyst has 0 dispatch sites
- Fixed in: P4 PR-B

### X55. Multi-mode agents load every mode on every dispatch
- Evidence: qa.md has 5 modes
- Fixed in: P6 PR-C2

### X56. CLAUDE.md is ~43% hook internals
- Evidence: 11,106 B
- Fixed in: P1 PR-0; P6 PR-C2

### X57. Native capabilities are re-implemented or misconfigured
- Evidence: settings.json env: ENABLE_TASKS 'false', ENABLE_TOOL_SEARCH 'false', AGENT_TEAMS '1'
- Fixed in: P5 PR-C1 (D16 revised)

### X61. conftest masks failures; tests/generated is tracked garbage
- Evidence: TEST_INCOMPLETE converted to xfail; 59 generated files
- Fixed in: P3 PR-A

### X63. The never-configured LANE-B broker raises on every call
- Evidence: session_resources.py:31-32
- Fixed in: P4 PR-B

### X64. runtime_guard blocks npm and node on unconfigured hosts and adds a shim interpreter
- Evidence: 'BLOCK STEP1: indeterminate policy'
- Fixed in: P5 PR-C1

### X66. docs/reference holds ~60 dated incident records
- Evidence: 50 of 64 marked DELETE
- Fixed in: P3 PR-A; P4 PR-B (the grammar doc moves with its gate)

### X67. 252 tracked files reference gitignored docs/dev, and a kept command cites it as binding
- Evidence: paseo-daemon.md:10-12, :257
- Fixed in: P2 Wave 1 (docs/dev stays in place; D9 prune exempts cited files); P4 PR-B (paseo-spec.md); P6 PR-C2

### X71. A shadow replay against installed hooks would mutate shared state
- Evidence: pretool-wrapper-userintent.py:16-17
- Fixed in: P2 Wave 1 (isolated replay)

### X72. 'Snapshot then allow' deletion cannot recover gitignored files
- Evidence: checkpoint-core.sh:534
- Fixed in: P4 PR-B

### X73. Some protections are easy to drop in a rewrite
- Evidence: grep OOM guard; runtime_guard KILL_VERBS; bash-safety.sh:1793-1804
- Fixed in: P3 PR-A

### X74. Overnight machinery runs on every call although overnight is unused
- Evidence: 10 files / 4,960 lines
- Fixed in: P4 PR-B

### X75. fswatch auto-push bypasses the push gate
- Evidence: git-fswatch.sh:357
- Fixed in: P1 (~/.claude unit stopped); P5 PR-C1 (D20)

### X76. Optional features without a user ruling add steps and code
- Evidence: graphify 2,302 lines; scoring 887
- Fixed in: P4 PR-B

### X82. CLAUDE_CODE_DISABLE_BACKGROUND_TASKS would break /spec background Explore
- Evidence: pretool-block-background-tasks.py:108-117; commands/spec.md:70-78
- Fixed in: P0 (D16 revised); P5 PR-C1 (hook kept)

### X83. Literal-path reachability misses imports, dynamic loads and external roots
- Evidence: 64 top-level + 49 indented lib imports; 47 dynamic-load sites; git-fswatch@.service:11
- Fixed in: P3 PR-A (AST reach, external-roots.txt); P8 (no auto-merge of executable deletions)

### X85. Expiry and ratchet mechanics bring back red CI, rubber stamps and taps
- Evidence: Same-day review_by dates; policies/** protected; 76 of 158 backlog entries concern false positives
- Fixed in: P3 PR-A (staggered dates, warn on expiry); P8 (2 per week, throttle, kill switch)

### X86. The quota floor is not readable from the cloud
- Evidence: paseo-usage-read.mjs:1-22 reads the local daemon WebSocket only
- Fixed in: P2 Wave 1 (snapshot publisher); P8

### X87. Shadow replay writes into product repos and flakes on clock-dependent checks
- Evidence: pretool-cp-checkin.py:155,182; agent_resolver staleness
- Fixed in: P2 Wave 1 (read-only repos, fresh state, verdict classes, local reports)

### X88. Bash tamper and push re-validation would weaken
- Evidence: pretool-claude-config-guard.py:48-66; pretool-push-analyst-grant-guard.py:4-10
- Fixed in: P5 PR-C1 (both stay in the hook layer); P7 PR-D

### X89. An XDG_RUNTIME_DIR-based runtime dir recreates the split brain
- Evidence: stop-cleanup-allowlist.sh:27-40 removes the /do flag only at the resolver path
- Fixed in: P7 PR-D (fixed dir; no token fallback)

### X90. Hook-injected context has no budget
- Evidence: budgets list lacks hook stdout; plugin details counts only commands and agents
- Fixed in: P3 PR-A

### X92. Defaults would override recorded rulings
- Evidence: f6fabf7 authorizes AGENT_TEAMS=1
- Fixed in: P0 (defaults follow rulings; D16)

### X93. The golden was padded by one classifier and too slow
- Evidence: 436 POL rows all stateless with 0 agent_id; 550 x 2 x 724 ms is about 13 min
- Fixed in: P3 PR-A (>=3 per row, subagent envelopes, parallel)

### X94. The quiesce check missed non-claude writers
- Evidence: paseo-daemon-timers.py:141-146; git-fswatch.sh:274-275
- Fixed in: P2 Wave 1

### X95. Product-repo auto-push bypasses the secret scan and the push gate
- Evidence: git-fswatch.sh:335-357
- Fixed in: P5 PR-C1 (D11, D20)

### X96. Self-repair evidence is text written by the agent itself
- Evidence: b108c16; harness-defects D17
- Fixed in: P8 (eligibility from CI artifacts only)

### X98. Sequencing contradictions
- Evidence: pull_request_target cannot judge PR-A; repoint of pretool-obligation-gate.py:78; 30 min vs 6 h; squash merges
- Fixed in: P3 PR-A (post-merge exits); P4 PR-B; D13 (merge commits)

## low (10)

### X104. The email and private paths remain in public history
- Evidence: History scan: only placeholder AKIA<16-char-placeholder>; 0 forks
- Fixed in: P0 (D19)

### X105. The old tree would sit in RAM for 14 days
- Evidence: 2.4 GB docs/dev
- Fixed in: P2 Wave 1 (pre-swap on ext4; D9 prune)

### X106. Stale remote branches
- Evidence: origin/fix/dev-fanout-gatekeeper-20260717 and origin/worktree-overnight-20260810-019fe5c1, each 0 commits ahead of master
- Fixed in: P3 PR-A post-merge (D13)

### X107. canary-verify's host drift check has no host in CI
- Evidence: canary-verify.sh:156-185
- Fixed in: P2 Wave 1 (runs in harness-update)

### X108. Whether the CLI re-captures hooks on settings reload is untested
- Evidence: captureHooksConfigSnapshotFromLoadedSettings exported in the 2.1.295 bundle
- Fixed in: P2 Wave 1 (flip-then-render; observed and recorded)

### X109. The issue cap fell back to an unconsumed JSONL
- Evidence: Earlier harness-issue.py design
- Fixed in: P3 PR-A (no fallback)

### X54. INDEX/README inside commands/ and agents/ load as /INDEX and /README
- Evidence: plugin validate warns on all 4 files
- Fixed in: P3 PR-A

### X59. Agent frontmatter is unused
- Evidence: 0 of 23 agents declare tools or model
- Fixed in: P6 PR-C2

### X91. In-place fast-forward installs are non-atomic
- Evidence: 113 lib import statements in hooks; an exception exits 1 and does not block
- Fixed in: P2 Wave 1 (release dir plus atomic flip for every install)

### X97. /clean --apply could delete untracked user work
- Evidence: Age rule and zero-reference rule; 14-day purge
- Fixed in: P4 PR-B (explicit patterns only; no auto purge)
