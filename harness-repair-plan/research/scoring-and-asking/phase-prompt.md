Owner steps: none.

# Phase P13: ask by AskUserQuestion in /spec and /dev; agent scores that drive the agents (D28)

Effort: L in total, split into P13-1 and P13-2 (M, about one day each) and P13-3 (S, about half a day) (D26).
Order (FAST-TRACK.md): P13-2 runs beside P12, from P12's base (the second train's head); P13-1 starts from the merged
P12 head; P13-3 starts when P13-1 and P13-2 are merged. P13-1 and P13-2 share the AskUserQuestion hook, close_rating,
the dev replay driver, the subagent player and the enforcement ledger. Keep each change in its own function. Whichever
merges second merges `origin/master` and keeps both sides' behaviour. Each sub-phase has its own branch
(`repair/P13-<n>`), PR, acceptance tests and merge, and its hand-off header (`prompts/handoff/P13-<n>.md`) names its
base. Place: after P12, before P11. Push after every commit.
Design, evidence and file:line facts: `harness-repair-plan/research/scoring-and-asking/design.md` (planning branch, in
Chinese). Read prompts/_common.md; this file overrides it, and design.md, where they differ.

## Dependencies
After `git fetch origin master`, check; on a failure stop and tell the reviewer in your session output (never the owner):
- `git log --merges --format='%s%n%b' origin/master` shows the P12 lane merges `P12-L1` to `P12-L6` and P12's
  integration merge. P13-2 starts before them, from P12's base, and checks them before its own merge. P13-3 also needs
  P13-1 and P13-2. P11 has not run (D30: it publishes a clean public copy, after P13).
- On origin/master (P12 may have merged or renamed hook files: find each by function, not by file name):
  `close_rating.rating_asked`; `command_span` with `minted_id`; the unified Stop gate with its `PREDICATES`; the overnight
  AskUserQuestion deny; schemas/producer-question.v1.json; the G1 dispatch gate; the producer stop gate G2.
- The scoring code P9 was told to keep: a score-log reader, scripts/score-update.sh, scripts/score-inject.sh. If P9 deleted
  any of it, do not restore it: build on what is there and list the gap in the PR.
- P1c's replay suite and the artifact check are green in origin/master's latest CI run.
- The owner answered design.md §7 in D29 (DECISIONS.md), and design.md follows it. Never ask the owner.

## Goal
1. Interactive /spec, /dev, /redev and /dev-command ask at least one AskUserQuestion round that digs into intent, scope,
   edge cases and acceptance. BA writes the questions. The owner's answers are kept verbatim as a project artifact. A
   hook, not prose, makes sure the round was asked (asked, not answered). Nothing is asked in plain text, and nothing is
   asked inside /dev-overnight.
2. Agent scores come from facts that hooks record in the existing score log, and are computed on read. At dispatch each
   agent sees its score, its rank and a reminder that differs by rank (D29). The owner sees the scores after each rating.

## Owner rulings
- D28: the two goals above. D9a's retirement is withdrawn. The rating stays a native AskUserQuestion (D9, D9b).
- D29: rounds have no cap, until the task is completely clear. /dev after a finished /spec asks every point that needs
  the owner, with at least one round. /close asks the rating only. A score changes the dispatch reminder and nothing else:
  no gate at a producer's stop, and no stricter QA.
- D3, D23: a question is a real, specific decision; asking is the pause. An answer never releases a gate or ends a command.
- D9b: a gate needs the question asked, not answered. Skip, no answer, AFK or a denial blocks nothing, and hooks record
  nothing for them.
- D18: no question asks the owner for a technical choice. You decide each remaining choice by one experiment, recorded.
- D20: inside /dev-overnight nobody is asked. P13 adds no overnight exception and no overnight question.
- D21: no file-name-to-role table. Roles come from dispatch records and obligations.
- D24: every artifact P13 adds or changes has one producer and at least one deciding consumer (artifact check at 0).
- D25: never fail. One agent action clears every new block. P1c's suite and its dead-end check stay green.
- D8: the orchestrator writes no producer artifact, no answer file and no score row.
- D15, D17: scoring is redesigned, not retired. A script is deleted only in the sub-phase that removes its last caller,
  with its reachability proof.
- Producer side: close.md, commit.md, changelog-analyst.md and the scripts they call gain no check and read no score log;
  no new state file. Hooks may observe their dispatches. No verdict anywhere depends on a score (D29).

## Names used below
- Round file: `docs/dev/requirement-round-<task>-r<n>.json`, schema `schemas/requirement-round.v1.json`, written by BA.
  A fresh, valid round file r<n+1> stands in for a BA dispatch's declared artifacts at G2, and that dispatch may write
  it, exactly as for a producer question (contract_runtime.producer_question, the write gate's question path).
- Answer files, written only by the AskUserQuestion hook:
  - answer file: `docs/dev/requirement-answers-<task>-r<n>.json`;
  - producer answer: `docs/dev/producer-answer-<task>-<role>-<q8>.json`, where q8 is the first 8 hex digits of the
    question file's sha256.
- Sources: `requirement-round:<task>:r<n>`, `producer-question:<task>:<role>`, `close-rating:<task>` (unchanged).
- Ask span: a /spec, /dev, /redev or /dev-command span opened by a human-typed prompt (command_span's opener rule).
- `asked(span, source, file)` is true when the span has a main-agent AskUserQuestion with that `metadata.source` and any
  tool_result (is_error included). For a round file, its `input.questions` must also equal, as canonical JSON, the
  file's questions with `id`, `dimension`, `assume` and `spec_ref` removed. It is one new function in hooks/lib that
  reads the transcript the way `close_rating.rating_asked` does; from P13-1 on, `rating_asked` calls it.
- Score log: the existing `${CLAUDE_CONFIG_DIR:-~/.claude}/logs/lifecycle.jsonl` and its lock.
- Scored identity: the obligation's role. The one exception is role qa in pipeline close, which is scored as `close-qa`.
- Rank: score-inject.sh's tiers: Disgraced below 0, Apprentice 0-20, Journeyman 21-40, Skilled Craftsman 41-60 (where
  an identity with no rows sits), Senior Craftsman 61-80, Master 81-100.

## P13-1: the requirement round (M)
Owns: schemas/requirement-round.v1.json (new); agents/ba.md (intake and contract sections, or P12's shared file);
commands/dev.md, dev-command.md (its difference only), spec.md; scripts/todo/dev.py, spec.py (dev-command's if separate);
the dispatch gate (G1's PreToolUse Agent hook); G2's round and contract checks; the PostToolUse AskUserQuestion hook, the
`asked` library and close_rating's `rating_asked`; the write gate's hook-owned paths; the Stop gate's text-question
predicate; the /spec window predicate; the resolver's commit whitelist entries; tests/replay drivers dev, dev_command and
spec and the subagent player (tests/replay roles and agents); the ledger rows; the tests of all of these.

R1. Schema: `{task_id, round, questions[1..4]}`. Each question is `{id, dimension, header, question, multiSelect,
    options[2..4]{label, description}, assume, spec_ref}`, with `dimension` one of intent, scope, edge_cases, acceptance,
    `header` at most 12 characters, `assume` one of its labels, and `spec_ref` the spec section a question probes (or
    null). Rounds have no cap (D29). G2 checks at BA's stop:
    - task_id equals the obligation's;
    - round is the next one, and the previous one was asked;
    - with no spec attached, r1 has exactly four questions, one per dimension;
    - with a spec attached, the same rule (D29): at least one question, asking every point that needs the owner;
    - no question repeats one already answered (same canonical question text) in an answer file of the task or of its
      attached spec;
    - a code token (a backtick, a path with an extension, `()`, `::`) in a question or option fails. This lint catches
      only code tokens; state that strength in the enforcement ledger.
R2. agents/ba.md has two modes:
    - intake writes only r1;
    - analysis reads every answer file of the task. It maps each answered question into
      `context.requirement.contract_refs` (`[{answer_ref: "r1.q2", criterion_ids}]`), and lists each unanswered question
      under `assumptions` with its `assume` label. While any point still needs the owner's decision, it writes r<n+1>
      instead of its declared artifacts (the stand-in above), with no cap (D29). A skipped question is settled by its
      `assume` and is not asked again.

    G2 at analysis' stop: the mapping covers every answered question, and the assumptions cover every unanswered one.
    Delete the technical-choice examples (dev.md "which API?", dev-command.md "which metrics?").
R3. commands/dev.md, and dev-command.md by difference (redev.md stays a pointer, D22):
    - the steps are BA intake, then one AskUserQuestion per round file (its questions verbatim, its source), then BA
      analysis;
    - the todo lists name those steps, and check-todo-md-sync stays silent.

    commands/spec.md:
    - delete "No 'deep-dive', no 'acceptance criteria' interview";
    - dispatch BA intake after Section 5's first write; the task id is the spec id;
    - `spec-write.py append` copies each answer file byte for byte into Section 5, as `### 5.N: Requirement round r<n>`;
    - the /spec window predicate allows a foreground `ba` dispatch;
    - the empty-argument ask is one AskUserQuestion.
R4. The AskUserQuestion hook (P4's PostToolUse hook, generalized) routes by source prefix to one `handle(payload) -> hook
    JSON or None` per library, and prints what the handler returns. The close-rating branch keeps P4's behaviour.
    - It writes, main agent only, with `tool_response` holding user content and no `afkTimeoutMs`: an answer file when the
      call satisfies `asked`'s question equality, and a producer answer when the source matches.
    - Content: `{task_id, round, source, tool_use_id, asked_at, question_file_sha256, questions, answers, response,
      annotations}`, copied verbatim from tool_input and tool_response. The first matching ask per file wins.
    - Skip, AFK, decline or error: nothing is written.
    - The task's round files and answer files join its commit whitelist, where the resolver lists
      commit_whitelist_artifacts.
R5. Dispatch gate, inside an ask span, for the span's task only (`minted_id()` for the /dev family; the obligation's task
    in /spec):
    - (a) While a schema-valid round or producer-question file, whose declaring dispatch returned ok, is not `asked`, any
      other dispatch is refused with: `ASK_FIRST: ask <file> with one AskUserQuestion, metadata.source "<source>",
      questions exactly as written; then dispatch.`
    - (b) A dispatch that declares any artifact other than r1 is refused until r1 is `asked`.
    - A dispatch that declares that same question file always passes (it repairs it), and so does a dispatch without an
      obligation block. No count, no release file, no retry cap.
R6. Write gate: answer files, producer answers, the score log and its lock are hook-owned. Every agent's Write, Edit,
    NotebookEdit and Bash write target (redirect, tee, cp, mv) to them is refused, the main agent's included.
R7. Stop gate, in an ask span: a stop whose last main-agent text block ends with `?` or `？` (last non-empty line) is the
    gap `<command>: the turn ends with a question in text; ask it with AskUserQuestion, or end without it.`
    /spec is checked for this predicate only, and stays out of GATED_COMMANDS. The gate still writes nothing.
R8. Experiment (D18): read the CLI bundle statically. Does a call to an unavailable AskUserQuestion (dontAsk mode, or
    headless with no permission host) leave a tool_use and an error tool_result? If it does, R5 needs nothing more. If not,
    R5 applies only when a CLI-written fact says the tool is offered. Record the fact used.

Acceptance. Replays run as `python -m tests.replay run --driver <d> --arg variant=<v> --settings shipped --runs plain`,
with the runner's required `--tree` and `--out`; add the variants named here. Record each command with pass or fail.
A1. pytest on touched and added tests: 0 failed. CI green on 3.10, 3.11 and 3.12. Artifact check at 0. P1c's suite and
    dead-end check green, with the new blocking sites enumerated. dev_command `plain` lands, with its round asked.
A2. dev `round`: an AskUserQuestion with source `requirement-round:<task>:r1`, whose questions equal r1's four, comes
    before the first dispatch declaring a context, ticket or dev-report; the answer file's `answers` equals the replayed
    tool_response byte for byte; contract_refs cover every answered id; it lands with 0 undeclared blocks, 0 hook errors.
A3. Asking out of order:
    - dev `round-unasked`: BA analysis before the ask is refused with ASK_FIRST; after the ask it passes and lands;
    - dev `round-paraphrase`: altered questions write no answer file and are refused; the exact questions pass and write
      the file;
    - dev `round-broken`: an intake that left a malformed r1 is re-dispatched and not refused.
A4. dev `round-skip`, `round-decline` and `round-afk`: no answer file, no block, and BA lists the assume labels.
A5. dev `devquestion` (new): two producer questions in a row. Each re-dispatch before its ask is refused. Each ask writes
    its own producer answer file (two distinct q8), and BA proceeds.
A6. spec `round`: BA intake runs inside /spec unblocked; Finalize before r1 is asked is refused, and passes after;
    Section 5 holds the answer bytes verbatim. /dev after that /spec asks at least one question, and none the /spec
    rounds already answered.
A7. dev `round-many`: BA analysis writes r2, then r3 and r4, instead of its artifacts while it declares an open point;
    G2 accepts each; after the last is asked, analysis lands. No round number is refused. A round that repeats an answered
    question is refused at G2. overnight `unattended`: 0 AskUserQuestion, no round file, no ASK_FIRST.
A8. dev and spec `text-question`: a turn ending "...?" is blocked with R7's text. The same text in a /close span is not.
A9. G2 refuses: r1 with three questions or a repeated dimension (no spec); a backtick path in an option; an assume that
    is not one of its labels; an analysis that misses one answered id.
A10. R6: main-agent Write, Edit and `echo >>` on an answer file and on the score log are refused, while the hook's own
     writes land. R8 is recorded. A unit test feeds an error tool_result, and `asked` is true.

## P13-2: score events and the owner's view (M; beside P12 and P13-1)
Owns:
- hooks/lib/score_log.py, moved from scripts/lib; a one-line re-export stays there until P13-3;
- hooks/lib/close_rating.py; commands/close.md Step 4;
- the AskUserQuestion hook, which gains matcher `Agent`, and its one settings.json entry;
- scripts/close-scoring-decide.py (deleted); tests/test_score_log.py;
- tests/replay drivers close and dev, and the subagent player; the ledger rows; their tests.

S1. One module, one writer function:
    - it provides `read_lines`, `append(row)`, `score`, `tier`, `render_dispatch_line` and `render_owner_summary`;
      `append`'s caller holds the lock, and the first row per `key` wins;
    - `close_rating.append_row` stays as a delegate that writes a row unchanged, until P13-3 deletes score-update.sh;
    - rows gain `kind`: `{kind: "event", ts, project, task_id, role, event, points, key, why, ref}` and `{kind: "rating",
      ts, project, task_id, rating, roles, tool_use_id}`;
    - `roles` is read from the task's dispatch records when the rating is written;
    - `project` is the first 12 hex digits of the sha256 of the git top-level's identity;
    - rating dedup compares rating rows only, by canonical task id;
    - rows with no `kind` are read and never scored.
S2. On `Agent` (the main agent's dispatches) the hook never blocks, exits 0, and runs every rule in its own try. It
    appends events from facts only:
    - lane QA's `qa.status` with `primary_cause`: qa_first_pass and qa_fail. qa_catch only when dev's re-dispatch
      changed a file the failure's `location` names;
    - close-QA's classified last line and each finding's `declaring_dispatch` role: escaped, for that role and for lane
      qa; close-qa +1 per finding whose cited artifact's producer fixed it in a later round;
    - a re-dispatch of the same (task, lane, role, declared paths) caused by a gap: rerun_gap. A re-dispatch caused by a QA
      fail, a close finding, a clarification or an API error is not one;
    - refused main-agent calls in the span segment since its last observation: main_refused.

    Points start at design.md §3.2's values; settle them by S5's fixture experiment and record them. It never recomputes
    a gate's verdict. This hook file is the only writer of the score log and of the answer files.
S3. Experiment: do SubagentStop and Stop blocks leave a recognisable record in the subagent's and the main transcript? If
    they do, enable stop_blocked and main_stop_blocked from those records. If not, drop both and list them under "Out of
    scope, found".
S4. Rating:
    - close.md Step 4 keeps P4's one rating question; no second question (D29);
    - the handler writes one rating row (5, 4, 3, and "1-2" stored as 1);
    - it returns the owner summary as `systemMessage`, at most 5 lines: each identity's score, rank and trend, this cycle's
      points with reasons, and the worst identity and why;
    - experiment: is it shown to the user, and does the hook run on Skip? If it is not shown, return it as
      additionalContext asking for a verbatim relay (the one relay D28 allows; the main agent computes nothing);
    - close.md reads no log and computes nothing.
S5. Score function (D29, the earlier design: cumulative):
    - fold, in ts order, every event row and rating-derived row of the identity in the project with `ts < as_of`;
    - start at s = 50, then for each row set s = min(100, s + points), with no lower bound (score-update.sh's rule), so
      Disgraced is reachable;
    - trend = the score minus the score before the identity's 5 most recent tasks;
    - tier: the rank (Names above); an identity with no rows sits at 50, Skilled Craftsman.

    Fixture experiment:
    - on the same points, the fold equals score-update.sh's running new_score;
    - 2 QA fails in 3 tasks drop dev one rank, and only later positive events raise it again;
    - a run of failing tasks keeps falling below 0; a long good run stops at 100.
S6. Delete scripts/close-scoring-decide.py (no caller since P4), with its residue-allowlist and index rows.

Acceptance:
B1. pytest, CI and artifact check as in A1. The artifact check names one producer of the score log. score-update.sh and
    score-inject.sh still run and pass their shell tests.
B2. dev `qa-fail`, then close: the log gains qa_fail (dev, dev_implementation) and qa_catch, and no rerun_gap for the
    QA-driven re-dispatch. A QA fail whose fix touches no named file gives no qa_catch. Replaying again adds 0 rows.
B3. close `findings` (a finding on a dev artifact after lane QA passed): escaped for dev and for lane qa, and close-qa +1
    once dev's fix lands. A clean close gives close-qa nothing.
B4. Rating: the dialog has one question; "4 - Minor gaps" writes one rating row with its roles, and the hook output holds
    the summary naming the worst identity and why. Skip, free text, AFK and decline write no rating row. An event row
    with the same task_id does not stop the rating row (P4's dedup defect).
B5. Unit tests of the score function over fixtures; rows with no kind are ignored; 20 parallel appends give 20 rows.
B6. `grep -nE 'score_log|lifecycle\.jsonl|score-(inject|update)' commands/close.md commands/commit.md
    agents/changelog-analyst.md` prints nothing. `git grep close-scoring-decide` prints nothing outside history docs.

## P13-3: what agents see at dispatch: score, rank and the rank's reminder (S; after P13-2)
Owns:
- the SubagentStart injector (one new registration); the UserPromptSubmit line;
- agents/ba.md, dev.md and qa.md, commands/dev.md and dev-command.md (deletions only);
- scripts/score-update.sh, scripts/score-inject.sh, the scripts/lib re-export and the two score shell-test directories
  (all deleted);
- settings.json; the tests that pin any of these (including P4's test_close_rating); the ledger rows; the replay variants.

C1. SubagentStart, outside spans of /close, /commit, /merge and /push: from agent_type, cwd and the active span, it
    outputs additionalContext of at most 3 lines and 400 bytes:
    - the score, rank and trend;
    - the top reason: an event's `why`, at most 80 characters, never a task id;
    - the rank's reminder: one line per rank, worded as in design.md §3.6, kept in score_log.

    A role with no rows gets one line: no record yet, Skilled Craftsman, and that rank's reminder. `as_of` is the span
    opener's timestamp. Experiment: confirm the text reaches the subagent (CLI bundle). If it does not, append the text
    to the dispatch prompt through the dispatch gate's updatedInput, after every rule passes, and record which way was
    used.
C2. UserPromptSubmit, in ask spans only: one line with the main agent's own score, rank and top miss.
C3. Nothing else follows from a score (D29): no producer's stop requires a field because of it, no gate reads the score
    log, and QA is not made stricter by it.
C4. Delete what the hooks now do, with a reachability proof for each deleted file:
    - in dev.md: the injection blocks, the placeholders, Step 14's scoring, "Mascot Score Changes" and the line-93 reason;
    - the INJECTION_PROOF echo contracts, and the agents' `score:` front matter (points live in score_log);
    - score-update.sh and score-inject.sh with their allow entries, the shell tests, the re-export and the
      append_row delegate;
    - the stale style-inspector rank-label exemption and the "ba +8" example, if still there.

Acceptance:
C-A1. pytest, CI, artifact check, P1c suite and dead-end check as in A1. Prompt bytes of commands/ and agents/ fall; report
      the figure.
C-A2. The injector over fixture logs: each of the six ranks gives its own reminder; scores -1, 0, 20, 21, 40, 41, 60,
      61, 80, 81 and 100 land in the right rank; each output fits in 3 lines and 400 bytes, with the reason and no task
      id; no rows gives one line; a /close span gives none. The experiment is recorded.
C-A3. dev `plain` and dev `qa-fail` over fixture logs that put dev, ba and qa at each rank: every dispatch carries its
      rank's reminder, and every G2 and Stop-gate verdict equals the one with an empty log. close `plain` under the same
      fixtures gets no injection and no new block.
C-A4. `git grep -nE 'score-inject|score-update|INJECTION_PROOF|rank_acknowledged|SCORE_HEADER' -- commands agents hooks
      scripts settings.json ':!hooks/tests'` prints nothing, and the replay drivers play no score calls.

## DO NOT (every sub-phase)
- Add any check, scan, filter or score-log read to close.md, commit.md, changelog-analyst.md or the scripts they call.
- Let the orchestrator or any subagent write an answer file, a producer answer or a score row, or paraphrase an answer.
- Add a state file, counter, flag, stored score, release token or retry cap, or use an agent-writable file as a release.
- Let a hook record anything for Skip, no answer, AFK, a denial or an error; synthesize an answer or a rating.
- Let asking or answering release a gate or end a command; offer a "stop here" option.
- Ask anything inside /dev-overnight, add an overnight exception to P2's deny, or ask for a technical choice in an example.
- Ask the owner anything: no AskUserQuestion to measure outside the sandbox, no REQUEST, no machine step.
- Inject more than 3 lines or 400 bytes per dispatch, or inject through orchestrator prose or a Bash call.
- Make any stop, dispatch or QA verdict depend on a score, or add a second question to the /close rating (D29).
- Recompute the verdict of G2, the Stop gate or close-QA in the observer, or attribute by a file-name-to-role table.
- Block in the AskUserQuestion hook, or let it fail a tool call.
- Delete a hook file in the same change that unregisters it (make it an exit-0 stub for one phase), or retire a feature.
- Touch harness-repair-plan/ or P11's files. Put a personal value in a row, a fixture or the PR (the project key is a hash).
- Exceed net code in hooks/, scripts/ and schemas/ (tests excluded): P13-1 at most +400, P13-2 at most +150, P13-3 at
  most -400, so the phase total is at most +150. A file this prompt deletes that is already gone counts as deleted by the
  sub-phase that names it.

## Pull request (one per sub-phase)
Title `P13-<n>: <short goal>`. Body: `Owner steps: none.` first; a summary; release notes on what changes in the owner's
sessions; each acceptance test's command with pass or fail (raw output in a comment, only on a failure); one line per
decision with its experiment and key number (points, thresholds, channels); the D24 rows the artifact check reports for
the artifacts you add or change; rules added and retired; net code lines; "Out of scope, found".
