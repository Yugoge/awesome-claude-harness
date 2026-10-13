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
- **D4b Overnight is unattended.** A pipeline that needs a decision overnight is parked. Its question goes
  into the morning report, the pipeline stays incomplete, and the session continues with the others.
- **D7 /close and /commit complete an incomplete dev.** When /close or /commit finds an unfinished dev
  cycle, it resumes it through the /redev continuation with the same subagents and the same obligations
  until it completes. If the user asks for dev, dev completes; if the user asks for close, close completes.
- **D8 The orchestrator never writes a producer's artifact.** Only the producer subagent writes its report.

## Pipelines

- **D5 /do consent lasts one turn.**
- **D6 Overnight lands once, at the end.** After the whole overnight session ends:
  /close --auto, then /commit --auto, then /merge, then /push. /commit --auto follows the normal /commit
  route but batches cycles the way /close --auto does. Never /commit --bulk. Remove the per-cycle commit
  at commands/dev-overnight.md:1576-1578 and give the post-loop flow (:1794-1809) the /close step.
- **D9 Close rating uses AskUserQuestion.** Replace the Happy `<options>` block in commands/close.md
  (about :867-880) with a native AskUserQuestion. A dedicated section studies the agent scoring system
  (landscape/H-scoring.md).

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
- **D16 History cleanup at the end.** Emails and account names are removed from git history in the final
  phase (git filter-repo with a mailmap, replace-text and replace-message), followed by deleting the 255
  remote refs. This is destructive and runs only after every phase PR is merged and the owner gives an
  explicit go-ahead at execution time. Every clone must re-clone afterwards.

## Execution

- One session per phase, one branch and one PR per phase, PR base `master`.
- The reviewing session reviews and merges. Phase sessions never merge their own PR.
- Waves: 1) P0 + P6; 2) P1; 3) P2 + P3 + P5; 4) P4 + P7; 5) P8, then P9, then history cleanup.
- Still open (asked when the phase starts): about 20 policy choices in P7-P9, and A3 (check
  files_created against the CLI transcript; recommended yes).
