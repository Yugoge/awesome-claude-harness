# Owner decisions (2026-10-13)

These decisions were made by the repository owner. They override PLAN-v1.md wherever the two disagree.
PLAN-v1.md still gives the file:line scope for each phase. Where it says "honest_blocked", "untrack settings.json",
"ask for curl/wget/docker" or "per-cycle commit", read the decision below instead.

## Product stance

- **D15 Published product.** The repo is a public, general-purpose harness that anyone can clone and use.
  No feature is retired. Live sessions keep running on this tree while it is edited (status quo), so a
  registered hook file is never deleted in the same change that unregisters it: it becomes an exit-0 stub
  for one phase.
- **Architecture is producer-side** (see docs/reference/close-commit-zero-failure-mechanism-20260928.md).
  Each fix lands on the single producer of an artifact: a hook, a launcher, the UserPromptSubmit hook, a
  producer prompt, the renderer, or CI. Never add consumer-side checks: nothing new in /close, /commit or
  the changelog-analyst (no scan, no cleanup class, no filter). /close and /commit only shrink.
- **D10 Technical choices by rule.** Pure technical choices are not put to the owner. The implementer
  picks the option that (1) follows the producer-side design doc, (2) adds the least code and the fewest
  rules, (3) is covered by a regression test, and (4) is listed in the PR's technical-choices table
  (choice / why / how to revert) so the reviewer or owner can veto it.

## dev never "honestly fails"

- **D2 dev has exactly one terminal: completed, with no gap.**
  - Remove dev report states blocked / needs_review and the status_rationale escape. There is no
    honest_blocked disposition anywhere.
  - QA fail or warning, and BA needs_clarification, are process steps inside the cycle. They are not
    terminals.
  - Remove the `required_values` lines that force a QA report to say "pass" (dev.md, dev-command.md,
    dev-overnight.md). Instead, the code-computed disposition reaches chain_pass only when every lane's
    QA verdict is pass. A failing QA sends the lane back to dev and the cycle continues.
- **D3 Questions are in-turn and never an exit.** When dev, BA or any pipeline needs the owner, it asks
  with Claude Code's native AskUserQuestion tool inside the turn. Asking never releases a stop gate.
  A question must be a real, specific decision the agent cannot make from the request, the code or a
  sensible default. It is never an escape hatch.
- **D4 Stop gates on eight commands.** /do, /dev, /dev-command, /dev-overnight, /close, /commit, /merge
  and /push cannot stop until the todo list is complete and their artifacts are verified by code.
  No retry bound, no self-release, no agent-writable release file. The only way out is human:
  interrupting the session, or a human-only /stop command.
- **D4b Overnight is unattended.** Inside the time-lock window, a pipeline that needs a genuine owner
  decision is parked: its question goes into the morning report, it stays incomplete and lands nothing, and
  the session continues with the other pipelines. Routine choices that the overnight autonomy rules
  already cover (dev-overnight.md Clause A) are still made by the orchestrator, with the assumption recorded.
  After the window, the parked questions are asked with AskUserQuestion, so the session waits for the owner
  inside a turn instead of looping on blocked Stops.
- **D7 /close and /commit complete an incomplete dev.** When /close or /commit finds an unfinished dev
  cycle, it resumes it through the /redev continuation with the same subagents and the same obligations
  until it completes. If the user asks for dev, dev completes; if the user asks for close, close completes.
- **D8 The orchestrator never writes a producer's artifact.** Only the producer subagent writes its report.

## Pipelines

- **D4c Interrupts and API errors need no gate code.** Claude Code does not run the Stop hook when the
  user interrupts a turn, and on an API error it runs `StopFailure` instead of `Stop` and ignores that
  hook's output (code.claude.com/docs/en/hooks, sections Stop and StopFailure). So the Stop gate contains
  no API-error or interrupt rule and parses no error records (nothing hardcoded). Such a cycle simply stays
  incomplete, and /restart resumes it.
- **D5 /do consent lasts one turn.**
- **D6 Overnight lands once, at the end.** After the whole overnight session ends:
  /close --auto, then /commit --auto, then /merge, then /push. /commit --auto follows the normal /commit
  route but batches cycles the way /close --auto does. Never /commit --bulk. Remove the per-cycle commit
  at commands/dev-overnight.md:1576-1578 and give the post-loop flow (:1794-1809) the /close step.
  - **D6a The owner types the four landing commands** in the morning, each held by its own Stop gate.
    The overnight session never runs /commit or /push itself (they stay human-only, CLAUDE.md #15); its
    final summary prints the exact commands to type, and in isolated modes where to type them.
- **D9 Close rating uses AskUserQuestion.** Replace the Happy `<options>` block in commands/close.md
  (about :867-880) with a native AskUserQuestion. A dedicated section studies the agent scoring system
  (landscape/H-scoring.md).
  - **D9a Scope: keep only the owner's rating log (plan option S-B).** A hook records the native rating.
    Score injection into agent prompts, automatic score events, the agents' score echo contracts and their
    scripts and tests are deleted (their effect on behaviour was never measured).
  - **D9b The Stop gate requires the rating question to be asked, not answered.** Skip, no answer or a
    denial never blocks the session and records nothing.

## Git, remote and privacy

- **D1 Remote push is opt-in.** One switch, GIT_AUTO_PUSH, default off ('0' or unset means off). Every
  automatic push path (checkpoint push, post-commit auto-push, installers that default it on) obeys it.
  Local checkpoints stay. /push is the only normal route to a remote. Deleting the 255 refs already on
  the public origin (252 refs/backups/claude/*, 3 refs/checkpoints/*) is low priority and happens at the
  very end, with an explicit go-ahead at that time.
- **D11 settings.json stays tracked, sanitized.** The tracked settings.json is the clean, public form.
  A git clean/smudge filter (declared in .gitattributes, registered locally by init) strips machine
  values on commit and restores them on checkout. Machine values live in an untracked
  settings.machine.json overlay (gitignored), with a tracked settings.machine.example.json. Init makes a
  fresh clone the user's own. A machine where the filter is not registered must not be able to commit
  personal values (fail closed).
- **D12 Personal values are never tracked.** Account names, emails, private project names, personal paths
  and the paseo account list leave code and docs. The owner's machine keeps full support through the
  overlay. The list of private literals used by any check stays local (untracked).
- **D13 paseo is an optional module.** Init lets the user choose modules. With paseo off, nothing paseo
  runs, nothing fails because paseo is missing, and the core harness is complete. The paseo commands stay
  in the repo for users who enable it.
- **D14 Public permissions = the owner's local allow list, minus personal-path entries.** curl, wget,
  docker run, docker exec and package.json edits are allowed (they are normal operations, not "ask").
  The owner does not want to curate fine-grained entries; pick the strongest coherent posture.
- **D17 Dead code and its tests are deleted, not quarantined (P8).** Code that no live entry point reaches is
  deleted together with the tests that exercise only that code. Live entry points: hooks registered in settings.json,
  commands, agents, skills, and scripts any of those run. This applies to the abandoned-cycle code and to tests that
  belong to another tool, such as the Codex tests. It is not feature retirement (D15), because nothing reachable is
  removed. Each deletion carries its reachability proof in the PR. A failing test of live code is never deleted or
  quarantined: the code or the test is fixed. No collect_ignore or skip list is used to make CI green.
- **D16 History cleanup at the end.** Emails and account names are removed from git history in the final
  phase (git filter-repo with a mailmap, replace-text and replace-message), followed by deleting the 255
  remote refs. This is destructive and runs only after every phase PR is merged and the owner gives an
  explicit go-ahead at execution time. Every clone must re-clone afterwards.

## Execution

- One session per phase, one branch and one PR per phase, PR base `master`.
- The reviewing session reviews and merges. Phase sessions never merge their own PR.
- Phase numbering follows PLAN-v2.md: P0-P11 (P5 = the unified Stop gate, P6 = producer input and
  identity, P7 = portable product, P8 = private tree and CI, P9 = prose pass, P10 = clean tree,
  P11 = remote refs and history cleanup). Wave 1 = P0 + P7. The later waves are in PLAN-v2.md.
- The policy choices listed as OPEN in PLAN-v2.md's decision ledger are no longer asked: they are decided by
  experiment under D18 when their phase reaches them.

## Owner delegation (2026-10-18 / 2026-10-19)

- **D18 No more owner arbitration; decide by experiment.** The owner (2026-10-19): "我不会管以上你如何决定，我只想告诉你你必须
  研究后再做决定，你的研究是有实验的研究而不是空口无凭，只要是有实验的无论实验结果我都接受 ... 不要让我裁决任何事情了". Every remaining
  choice, product or technical, is made by the reviewer or the phase session from an experiment it ran (a sandbox run,
  a test, a measurement), recorded with its result in the PR's technical-choices table. No phase asks him anything.
  The single exception is the irreversible step of P11 (force-push of rewritten history and deletion of the public
  refs), which keeps D16's go-ahead at execution time because it cannot be undone.
- **D19 No owner machine step.** The owner (2026-10-18): "我不做，没空，我不能停止claude". No phase gives him a step on his
  machine or needs his sessions stopped; merged code lands on a live home by itself (P7b). Merged code reaches his
  homes only when he types /pull (answered 2026-10-19; no automatic pull is added).
- Answers recorded 2026-10-19: P7b also handles the other repositories (legacy auto-push hooks, stale fswatch).
  TC-47 (P8): BA may write docs/dev/observations-ledger.md (agents/ba.md makes BA its producer); BA may use WebSearch
  and WebFetch; browser roles keep playwright only (the owner prefers it).
