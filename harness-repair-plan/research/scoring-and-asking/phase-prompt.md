Owner steps: none.

# Phase P13: ask by AskUserQuestion in /spec and /dev; agent scores that drive the agents (D28)

Effort: L in total, split into P13-1, P13-2 and P13-3, each M (about one day; D26). Each sub-phase has its own branch
(`repair/P13-<n>` from `origin/master`), PR, acceptance tests and merge. P13-1 and P13-2 may run at the same time on
different accounts; P13-3 starts when both are merged. Place: after P12, before P11.
Design, evidence and file:line facts: `harness-repair-plan/research/scoring-and-asking/design.md` (planning branch, in
Chinese). Read prompts/_common.md; this file overrides it, and design.md, where they differ.

## Dependencies
After `git fetch origin master`, check; on a failure stop and tell the reviewer in your session output (never the owner):
- `git log --merges --format='%s%n%b' origin/master` shows the P12 lane merges `P12-L1` to `P12-L6` and P12's integration
  merge; P11 has not run (no history rewrite, no deleted refs).
- On origin/master (P12 may have merged or renamed hook files: find each by function, not by file name):
  `close_rating.rating_asked`; `command_span` with `minted_id`; the unified Stop gate with its `PREDICATES`; the overnight
  AskUserQuestion deny; schemas/producer-question.v1.json; the G1 dispatch gate; the producer stop gate G2.
- The scoring code P9 was told to keep: a score-log reader, scripts/score-update.sh, scripts/score-inject.sh. If P9 deleted
  any of it, do not restore it: build on what is there and list the gap in the PR.
- P1c's replay suite and the artifact check are green in origin/master's latest CI run.
- Owner choices: the hand-off header gives the owner's answers to design.md §7 (Rounds, After /spec, Blame, Low score).
  Where it gives none, use the recommended option. Never ask the owner.

## Goal
1. Interactive /spec, /dev, /redev and /dev-command ask at least one AskUserQuestion round that digs into intent, scope,
   edge cases and acceptance. BA writes the questions. The owner's answers are kept verbatim as a project artifact. A
   hook, not prose, makes sure the round was asked (asked, not answered). Nothing is asked in plain text, and nothing is
   asked inside /dev-overnight.
2. Agent scores come from facts hooks record in the existing score log, are computed on read, are shown to each agent at
   dispatch and to the owner after each rating, and, when low, make the producer's own stop check more.

## Owner rulings
- D28: the two goals above. D9a's retirement is withdrawn. The rating stays a native AskUserQuestion (D9, D9b).
- D3, D23: a question is a real, specific decision; asking is the pause. An answer never releases a gate or ends a command.
- D9b: a gate needs the question asked, not answered. Skip, no answer, AFK or a denial blocks nothing and records nothing.
- D18: no question asks the owner for a technical choice. You decide each remaining choice by one experiment, recorded.
- D20: inside /dev-overnight nobody is asked. P13 adds no overnight exception and no overnight question.
- D21: no file-name-to-role table. Roles come from dispatch records and obligations.
- D24: every artifact P13 adds or changes has one producer and at least one deciding consumer (artifact check at 0).
- D25: never fail. One agent action clears every new block. P1c's suite and its dead-end check stay green.
- D8: the orchestrator writes no producer artifact, no answer file and no score row.
- D15, D17: scoring is redesigned, not retired. A script is deleted only in the sub-phase that removes its last caller,
  with its reachability proof.
- Producer side: no check, scan or score-log read in /close, /commit or the changelog-analyst; no new state file.

## Names used below
- Round file: `docs/dev/requirement-round-<task>-r<n>.json`, schema `schemas/requirement-round.v1.json`, written by BA.
- Answer file: `docs/dev/requirement-answers-<task>-r<n>.json`. Producer answer: `docs/dev/producer-answer-<task>-<role>.json`.
  The AskUserQuestion hook is the only writer of both.
- Sources: `requirement-round:<task>:r<n>`, `producer-question:<task>:<role>`, `close-rating:<task>` (unchanged).
- Ask span: a /spec, /dev, /redev or /dev-command span opened by a human-typed prompt (command_span's opener rule).
- `asked(span, source, file)` is true when the span has a main-agent AskUserQuestion with:
  - that `metadata.source`;
  - any tool_result (is_error included);
  - `input.questions` equal, as canonical JSON, to the file's questions with `id`, `dimension` and `assume` removed.

  It is one new function in hooks/lib that reads the transcript the way `close_rating.rating_asked` does; P13-3 makes
  `rating_asked` call it.
- Score log: the existing `${CLAUDE_CONFIG_DIR:-~/.claude}/logs/lifecycle.jsonl` and its lock.

## P13-1: the requirement round (M)
Owns: schemas/requirement-round.v1.json (new); agents/ba.md's intake and contract sections (or the shared file if P12 moved
them); commands/dev.md, dev-command.md (its difference only), spec.md; scripts/todo/dev.py, spec.py (and dev-command's list
if separate); the dispatch gate (G1's PreToolUse Agent hook); G2's round and contract checks; the PostToolUse
AskUserQuestion hook and the `asked` library; the write gate's hook-owned paths; the Stop gate's text-question predicate;
the /spec window predicate; tests/replay drivers dev and spec; the tests of all of these.

R1. Schema: `{task_id, round, spec_ref, questions[1..4]}`. Each question is `{id, dimension, header, question, multiSelect,
    options[2..4]{label, description}, assume}`, with `dimension` one of intent, scope, edge_cases, acceptance, `header`
    at most 12 characters, and `assume` one of the labels. The highest allowed round is 3 for "1 + up to 2 more", 1 for
    "Exactly 1", and unbounded for "No cap". G2 checks at BA's stop:
    - task_id equals the obligation's;
    - round is the next one, and the previous one was asked;
    - assume is one of that question's labels;
    - with no spec attached, r1 has exactly four questions, one per dimension;
    - with a spec attached ("Only open points"), at least one question, each with spec_ref;
    - a code token (a backtick, a path with an extension, `()`, `::`) in a question or option fails. This lint catches only
      code tokens; state that strength in the enforcement ledger.
R2. agents/ba.md has two modes:
    - intake: writes only the round file;
    - analysis: reads every answer file of the task. It maps each answered question into `context.requirement.contract_refs`
      as `[{answer_ref: "r1.q2", criterion_ids}]`, and lists each unanswered question under `assumptions` with its `assume`
      label. When an answer opened a point no default settles, it writes the next round file instead.

    G2 checks at BA analysis' stop: the mapping covers every answered question, and the assumptions cover every unanswered
    one. Delete the technical-choice examples (dev.md "which API?", dev-command.md "which metrics?").
R3. commands/dev.md, and dev-command.md by difference (redev.md stays a pointer, D22):
    - the steps are BA intake, then one AskUserQuestion per round file (its questions verbatim, its source), then BA
      analysis;
    - the todo lists name those steps, and check-todo-md-sync stays silent.

    commands/spec.md:
    - delete "No 'deep-dive', no 'acceptance criteria' interview";
    - dispatch BA intake after Section 5's first write; the task id is the spec id;
    - after the answers, `spec-write.py append` copies each answer file byte for byte into Section 5, as
      `### 5.N: Requirement round r<n>`;
    - the /spec window predicate allows a foreground `ba` dispatch;
    - the empty-argument ask is one AskUserQuestion.
R4. The AskUserQuestion hook (P4's PostToolUse hook, generalized):
    - It routes by source prefix to one `handle(payload) -> hook JSON or None` per library, and prints what the handler
      returns. The `close-rating:` branch keeps P4's behaviour unchanged; P13-2 moves it into `close_rating.handle`.
    - For `requirement-round:` and `producer-question:` sources it writes the answer file, main agent only, when
      `tool_response` holds any user content and no `afkTimeoutMs`.
    - The file is `{task_id, round, source, tool_use_id, asked_at, round_file_sha256, questions, answers, response,
      annotations}`, copied verbatim from tool_input and tool_response.
    - Skip, AFK, decline or error: nothing is written.
    - It is the one writer; the first answer per (task, round) wins.
R5. Dispatch gate, inside an ask span:
    - (a) A dispatch for a task whose declared round or producer-question file exists, is fresh and is not `asked` is
      refused with: `ASK_FIRST: ask <file> with one AskUserQuestion, metadata.source "<source>", questions exactly as
      written; then dispatch.`
    - (b) A dispatch for the span's task that declares any artifact other than that task's r1 round file is refused until
      r1 is `asked`. The span's task is `minted_id()` for the /dev family, and the obligation's task in /spec.
    - A dispatch without an obligation block passes. No count, no release file, no retry cap.
R6. Write gate: the answer files, the producer answer files, the score log and its lock are hook-owned. Every agent's
    Write, Edit, NotebookEdit and Bash write target (redirect, tee, cp, mv) to them is refused, the main agent's included.
R7. Stop gate: in an ask span, a stop whose last main-agent text block ends with `?` or `？` (its last non-empty line) is
    the gap `<command>: the turn ends with a question in text; ask it with AskUserQuestion, or end without it.`
    - /spec is checked for this predicate only, and stays out of GATED_COMMANDS.
    - The gate still writes nothing.
R8. Experiment (D18): read the CLI bundle statically. Does a call to an unavailable AskUserQuestion (dontAsk mode, or
    headless with no permission host) leave a tool_use and an error tool_result?
    - If it does, R5 needs nothing more.
    - If it does not, R5 applies only when a CLI-written fact says the tool is offered. Record the fact used.

Acceptance. Replays run as `python -m tests.replay run --driver <d> --arg variant=<v> --settings shipped --runs plain`; add
the variants named here. Run with armed shipped settings, and record each command with pass or fail.
A1. pytest on touched and added tests: 0 failed; CI green on 3.10, 3.11 and 3.12; artifact check at 0 violations; P1c's
    suite and dead-end check green, with the new blocking sites enumerated.
A2. dev `round`:
    - an AskUserQuestion with source `requirement-round:<task>:r1`, whose questions equal r1's four (one per dimension),
      comes before the first dispatch that declares a context, ticket or dev-report;
    - the answer file's `answers` equals the replayed tool_response byte for byte;
    - BA's contract_refs cover every answered id;
    - the cycle lands, with 0 undeclared blocks and 0 hook errors.
A3. dev `round-unasked`: BA analysis dispatched before the ask is refused with ASK_FIRST naming the file and source. After
    the ask it passes and lands. dev `round-paraphrase`: questions that differ from the file are refused; the exact
    questions pass.
A4. dev `round-skip`, `round-decline`, `round-afk`: no answer file, no block, and BA lists the assume labels as assumptions.
A5. dev `devquestion` (new): a BA producer question re-dispatched without asking is refused. Once asked, a producer answer
    file is written and BA proceeds.
A6. spec `round`:
    - BA intake runs inside /spec unblocked;
    - Finalize before r1 is asked is refused, and passes after;
    - Section 5 holds the answer bytes verbatim.

    dev with a spec attached: one question with spec_ref passes G2.
A7. overnight `unattended`: 0 AskUserQuestion, no round file, no ASK_FIRST; decisions are recorded as before.
A8. dev and spec `text-question`: a turn ending "...?" is blocked with R7's text. The same text in a /close span is not.
A9. G2 refuses each of these:
    - an r(max+1) round file;
    - r1 with three questions, or a repeated dimension (no spec);
    - a backtick path in an option;
    - an assume that is not one of its labels;
    - a BA analysis that misses one answered id.
A10. R6: the main agent's Write, Edit and `echo >>` on an answer file and on the score log are refused; the hook's own
     writes land.
A11. R8's experiment is recorded. A unit test feeds an AskUserQuestion with an error tool_result, and `asked` is true.

## P13-2: score events and the owner's view (M; may run beside P13-1)
Owns:
- hooks/lib/score_log.py (moved from scripts/lib, plus append and scoring), and hooks/lib/close_rating.py;
- commands/close.md Step 4;
- the new PostToolUse observer (matcher `Agent`), and its one registration in settings.json; its AskUserQuestion side
  plugs into R4's router;
- scripts/close-scoring-decide.py (deleted);
- tests/test_score_log.py, and the two score shell-test directories (replaced by pytest);
- tests/replay drivers close and dev, and the tests for all of the above.

Shared with P13-1: the AskUserQuestion hook file, where P13-2 changes only the close-rating branch. The sub-phase that
merges second merges origin/master and keeps both sides' behaviour. Do not edit commands/dev.md (P13-1, P13-3).
S1. One module, one writer function:
    - `read_lines` (today's reader), `append(row)`, `score`, `tier`, `render_dispatch_line`, `render_owner_summary`;
      `append`'s caller holds the lock, and the first row per `key` wins;
    - close_rating writes through it;
    - rows gain `kind`: `{kind: "event", ts, project, task_id, role, event, points, key, why, ref}` and
      `{kind: "rating", ts, project, task_id, rating, blame?, tool_use_id}`;
    - `project` is the first 12 hex digits of the sha256 of the git top-level's identity;
    - rating dedup compares rating rows only, by canonical task id;
    - rows with no `kind` are read and never scored.
S2. The observer runs on PostToolUse `Agent` for the main agent's dispatches. It never blocks, exits 0, and runs every rule
    in its own try. It appends events from facts only:
    - lane QA's `qa.status` with `primary_cause`: qa_first_pass, qa_fail, qa_catch;
    - close-QA's classified last line, and each finding's `declaring_dispatch` role: escaped, close_clean;
    - a re-dispatch of the same (task, lane, role, declared paths) caused by a gap: rerun_gap. A re-dispatch caused by a QA
      fail, a close finding, a clarification or an API error is not one;
    - refused main-agent calls in the span segment since its last observation: main_refused.

    Points start at design.md §3.2's values. Settle them by S5's fixture experiment and record the chosen values. The
    observer never recomputes a gate's verdict.
S3. Experiment: do SubagentStop and Stop blocks leave a recognisable record in the subagent's transcript and in the main
    transcript? If they do, enable stop_blocked and main_stop_blocked from those records. If not, drop both and list them
    under "Out of scope, found".
S4. Rating:
    - close.md Step 4 asks P4's question alone, or (per the Blame choice) with a second question: header `Improve`,
      options BA, dev, QA, No one;
    - the rating handler writes one rating row (5, 4, 3, and "1-2" stored as 1; plus blame if picked);
    - it returns the owner summary as `systemMessage`, at most 5 lines: each role's score and trend, this cycle's points
      with their reasons, and the worst role and why;
    - experiment: is a PostToolUse systemMessage shown to the user, and does the hook run on Skip? If it is not shown,
      return the summary as additionalContext that asks for a verbatim relay, and record that;
    - close.md reads no log and computes nothing.
S5. Score function:
    - window: the role's last 10 tasks in the project before `as_of`;
    - score = clamp(60 + sum, 0, 100); trend = the score minus the score 5 tasks earlier;
    - tier: good at 70 or more; watch at 50-69; probation below 50, or when the same miss category appears in 2 of the
      role's last 3 tasks.

    Fixture experiment: 2 QA fails in 3 tasks reach probation; 3 clean tasks after that leave it; 100 fails stay at 0.
S6. Delete scripts/close-scoring-decide.py (no caller since P4), with its residue-allowlist rows and index rows.

Acceptance:
B1. pytest, CI and artifact check as in A1; the artifact check names one producer of the score log.
B2. dev `qa-fail`, then close: the log gains qa_fail (dev, dev_implementation) and qa_catch, and no rerun_gap for the
    QA-driven re-dispatch. Replaying the same transcript again adds 0 rows.
B3. close `findings` (a finding on a dev artifact after lane QA passed): escaped for dev and for the lane's qa.
B4. Rating:
    - "4 - Minor gaps" (plus "dev" when Blame is on) writes one rating row, and the hook output holds the summary naming
      the worst role and its reason;
    - Skip, free text, AFK and decline write no rating row;
    - an event row carrying the same task_id does not stop the rating row (P4's dedup defect).
B5. Unit tests of the score function over fixtures; rows with no kind are ignored; 20 parallel appends give 20 rows.
B6. `grep -nE 'score_log|lifecycle|score-' commands/close.md commands/commit.md agents/changelog-analyst.md` prints
    nothing. `git grep close-scoring-decide` prints nothing outside history docs.

## P13-3: what agents see at dispatch, and what a low score makes them do (M; after P13-1 and P13-2)
Owns:
- the SubagentStart injector (a new hook with one registration), and the UserPromptSubmit line (prompt-workflow's output);
- G2's consequence checks, and `close_rating.rating_asked` (it calls P13-1's `asked`);
- agents/ba.md, dev.md, qa.md and the other producer prompts (new fields and deletions);
- commands/dev.md and dev-command.md (deletions only);
- the producer report schemas (new optional fields);
- scripts/score-update.sh and scripts/score-inject.sh (deleted), and settings.json;
- their tests and replay variants.

C1. SubagentStart: from agent_type, cwd and the active span, output additionalContext of at most 3 lines and 400 bytes:
    - the score, trend and tier;
    - the top reason: an event's `why`, at most 80 characters, never a task id;
    - the action this dispatch requires;
    - a role with no rows gets one line.

    `as_of` is the span opener's timestamp. Experiment: confirm the text reaches the subagent (CLI bundle). If it does
    not, append the text to the dispatch prompt through the dispatch gate's updatedInput, after every rule passes, and
    record which way was used.
C2. UserPromptSubmit, in ask spans and /close: one line with the main agent's own score and top miss.
C3. G2 applies the Low score choice, computing the same `tier(role, project, as_of)`. On probation:
    - dev needs `self_review [{criterion_id, test, result}]` covering every ac_uid, each with a test that exists in the tree;
    - ba needs each acceptance criterion to carry a contract_ref or a source_phrase;
    - qa needs `evidence[]` per criterion and `adversarial[]` with at least 3 entries;
    - any other producer needs `self_review[]` naming each declared artifact.

    Whatever the tier, a re-dispatch of a (task, lane, role) that QA failed earlier in the span needs self_review.
    - "Self-review + stricter QA": a lane QA whose dev is on probation also needs `adversarial[]`.
    - "Warning only": C1 and C2 only, and no G2 change.
C4. Delete what the hooks now do, with a reachability proof for each deleted file:
    - in dev.md: the injection blocks, the placeholders, Step 14's scoring, "Mascot Score Changes" and the line-93 reason;
    - the three INJECTION_PROOF echo contracts;
    - the agents' `score:` front matter (the points now live in score_log);
    - scripts/score-update.sh and scripts/score-inject.sh, with their settings allow entries;
    - the stale style-inspector rank-label exemption and the "ba +8" example, if still there.

Acceptance:
C-A1. pytest, CI, artifact check, P1c suite and dead-end check as in A1. The prompt bytes of commands/ and agents/ fall;
      report the figure.
C-A2. The injector over fixture logs: each tier's output fits in 3 lines and 400 bytes and carries the reason text and no
      task id; no rows gives one line; the experiment's result is recorded.
C-A3. dev `probation` (a fixture log with dev on probation):
    - dev's stop without self_review is blocked, naming the field;
    - with full coverage and real tests it passes;
    - a test name that does not exist is blocked.
C-A4. dev `qa-fail`: dev's re-dispatch after the fail needs self_review even at tier good.
C-A5. dev on probation with the stricter option: QA without adversarial[] is blocked, and with it passes. A "Warning only"
      fixture changes nothing in G2.
C-A6. Property test: the injector and G2 give the same tier for 200 random logs and span starts.
C-A7. `git grep -nE 'score-inject|score-update|INJECTION_PROOF|rank_acknowledged|SCORE_HEADER'` over commands, agents,
      hooks, scripts and settings.json prints nothing; the replay drivers no longer play score calls.

## DO NOT (every sub-phase)
- Add any check, scan, filter or score-log read to /close, /commit or the changelog-analyst.
- Let the orchestrator or any subagent write an answer file, a producer answer file or a score row, or paraphrase an answer.
- Add a state file, counter, flag, stored score, release token or retry cap; read gate state from anything an agent writes.
- Record anything for Skip, no answer, AFK, a denial or an error; synthesize an answer or a rating.
- Let asking or answering release a gate or end a command; offer a "stop here" option.
- Ask anything inside /dev-overnight, add an overnight exception to P2's deny, or ask for a technical choice in any example.
- Ask the owner anything: no AskUserQuestion to measure outside the sandbox, no REQUEST, no machine step.
- Inject more than 3 lines or 400 bytes per dispatch, or inject through orchestrator prose or a Bash call.
- Recompute the verdict of G2, the Stop gate or close-QA in the observer; attribute by a file-name-to-role table.
- Block in the observer or the AskUserQuestion hook, or let either fail a tool call.
- Delete a hook file in the same change that unregisters it (make it an exit-0 stub for one phase); retire a feature.
- Touch harness-repair-plan/, P11's files or another sub-phase's owned files.
- Put a personal value in a row, a fixture or the PR (the project key is a hash).
- Exceed net code in hooks/, scripts/ and schemas/ (tests excluded): P13-1 at most +400 lines, P13-2 at most +200,
  P13-3 at most -250; the phase total at most +300, with prompt bytes falling.

## Pull request (one per sub-phase)
Title `P13-<n>: <short goal>`. Body: `Owner steps: none.` first; a summary; release notes on what changes in the owner's
sessions; each acceptance test's command with pass or fail (raw output in a comment, only on a failure); one line per
decision with its experiment and key number (points, thresholds, channels); the D24 rows the artifact check reports for
the artifacts you add or change; rules added and retired; net code lines; "Out of scope, found".
