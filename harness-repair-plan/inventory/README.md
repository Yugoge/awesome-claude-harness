# Artifact map at d625284

**This map is planning evidence for master d625284db59399568c50424ea3162175d982ae04 only. No hook and no test may read
it. P1b regenerates the map on the master of its own day, and P1b's CI check derives every relation at test time; it
never compares against this file or any other committed list.**

`artifact-map-d625284.tsv` lists every harness artifact found on d625284 but two (`protected-runtime.json` and the
session-resource trust registry, see "How it was produced"), one row per artifact, with its producers, readers,
deciding consumers, where it is checked, which D24 violations it shows, what P7b and P8 change, and how the row was
proved. It reconciles five sources: the audit ledger (`audit/2026-10-23/ledger.md`), a corrected re-check of that
ledger against the code, a static extractor, and two runtime traces, plus probes run for this map to settle the
disagreements. Run date 2026-10-24.

## Counts

| | rows |
|---|---|
| artifacts (rows) | 120 |
| covering the 56 ledger rows (split where one ledger row holds several files with different producers) | 81 |
| found by the static extractor or the traces outside the ledger | 39 |
| several producers | 43 |
| several deciding consumers (each with its own rule) | 52 |
| consumer-side re-check or re-derivation | 29 |
| written never read | 26 |
| read never written | 24 |
| hand-written table | 27 |
| no violation found | 18 |
| evidence: both code and trace / code only / trace only | 87 / 32 / 1 |

Check positions named in the rows: producer stop 34, G1 dispatch 9, G3 collection 27, elsewhere 77.

Rows per group (the groups become P1b's scope rows): G01 cycle identity and registry 8; G02 workflow bookmark, todo
list, replay stores 5; G03 dispatch record and producer-gate outputs 4; G04 BA and context family 12; G05 test-writer
artifacts 4; G06 dev-report family and ownership facts 10; G07 QA report, completion report, chain disposition 3; G08
spec, checkpoints, split views 4; G09 /do 5; G10 /close 6; G11 /commit chain 9; G12 /push and /merge grants 5; G13
overnight 12; G14 grants, consent, intent 7; G15 logs, scores, capability, daemon state 9; G16 settings and landing 4;
G17 doc-sync and session by-products 8; G18 probes nothing writes, tables, rosters, transcripts 5.

Compared with the ledger (22 rows with several producers, 20 with several deciding consumers, 8 dead, 5 tables): the
map splits rows and adds 39 artifacts the ledger did not list, and it counts a table wherever a hand-written list in
code or prose names the artifact (D21's wider reading, 51 tables in the ledger re-check). The ledger's own 18
claims that the code does not support are removed (column `resolution`).

## Columns

| column | meaning |
|---|---|
| `id` | A01-A124 (A17, A25, A115 and A123 were dropped, see "Excluded") |
| `group` | G01-G18, the planning groups P1b's scope rows follow |
| `ledger_row` | the `ledger.md` row(s), or `-` for an artifact the ledger does not list |
| `artifact`, `paths` | name and path pattern (`<proj>` the product repository, `<state>` the hook state directory, `CLAUDE_STATE_DIR` or `/tmp`, `<ts>` a cycle timestamp, `<lane>` a fan-out lane, `<sid>` a session id) |
| `producers` | every writer, with file:line and how it was proved |
| `readers` | content consumers (tool-call target guards such as pretool-read-size-guard.py and snapshot scanners such as auto-commit.sh are left out; they open every file a tool touches) |
| `deciding_consumers` | readers whose read leads to a block, an exit code, a route or a verdict |
| `check_producer_stop` | checks at the producing subagent's own SubagentStop (or the producing hook itself) |
| `check_G1_dispatch` | checks at the orchestrator's Agent dispatch (PreToolUse) |
| `check_G3_collection` | checks at the orchestrator's collection point (the next dispatch's barrier, or PostToolUse of the producer's Agent call), including prose steps the orchestrator runs there |
| `check_elsewhere` | every other deciding check: /close, /commit, the Stop hooks (G4), scripts consumers run, other hooks |
| `violations` | any of: several producers; several deciding consumers; consumer-side re-check; written never read; read never written; hand-written table; with the detail in brackets |
| `p7b_p8_effect` | what P8 (head 0d26692, measured) or P7b (PR #7, merged at 301d696 from head 1071ad3, based on d625284; rows A88 and A105-A107 re-read at that head) changes |
| `evidence` | `code` (read at file:line), `trace` (seen in a sandbox runtime trace) or `both` |
| `resolution` | the disagreement between sources, and the experiment or code read that settled it |

Tags inside cells: `{c}` code read at file:line; `{p}` a prose instruction an agent executes (commands/*.md,
agents/*.md); `{t}` seen in trace-a or trace-b; `{x}` confirmed by this map's own probe; `{s}` found by the static
extractor only.

Definitions used for the violations (D24 and the 2026-09-28 ruling):
- several producers: more than one component writes the artifact, or one fact lives in two places. A consumer that
  rewrites or renames the artifact it reads counts as a producer; deleting a single-use grant when it is spent is
  consumption. The Claude Code CLI is the platform, not a harness producer: its transcripts, its todo writes and the
  settings keys it owns are records, but a harness component writing a CLI-owned file is counted.
- several deciding consumers: more than one consumer decides on the artifact, each with its own rule. Consumers that
  all call one function (for example agent_resolver for the agent index) take one conclusion and are not counted.
- consumer-side re-check: a check at a position other than producer stop, G1 or G3 that re-validates or re-derives
  what the producer side establishes (class b or c at /close or /commit is always one).
- written never read / read never written: no consumer other than snapshot scanners and a writer that only checks its
  own copy (a writer that reads its file back to decide later, such as a cache, a throttle or the dev-start replay
  store, counts as a consumer); or a read with no writer anywhere, including a reader that looks in another directory
  than the writer uses. An absence probe of a file that is written in another pipeline (for example the overnight
  state probed during /dev) is not a dead read.
- hand-written table: a literal list in code or prose that maps file names to roles, or repeats a role roster, an
  artifact-name list or a terminal vocabulary that a dispatch record, a schema or a canonical todo step already
  declares (D21).

## Sources and how they disagreed

| source | what it is | key numbers |
|---|---|---|
| `audit/2026-10-23/ledger.md` | 56 rows read from code and prose on the expected tree (P7b and P8 merged) | MP 22, MC 20, RD 24, DEAD 8, TABLE 5 |
| ledger re-check (not published) | all 418 ledger elements re-read on d625284 and P8's head | 364 confirmed, 18 ledger errors, 19 omissions, 4 corrected; 51 hand-written tables on 28 rows |
| static extractor (not published) | literal path extraction from Python, shell and markdown, scored against the ledger | recall producers 74.8%, consumers 54.8%, deciding 38.5%; precision about 82%; 329 families |
| trace-a (not published) | one sandbox session: /dev (2 lanes), /close, /commit, /do, /close of the do-report, /redev, under `strace -f --seccomp-bpf` | 5782 hook runs, 0 blocks, 0 hook errors; 505 path patterns |
| trace-b (not published) | /spec, /dev-command with /close and /commit, /merge, /push, a /dev-overnight start, and an overnight what-if with marked deviations | 5732 traced invocations; 2157 path patterns; overnight first cycle is a dead end |

The disagreements and how each was settled are in the `resolution` column. The probes run for this map (sandbox
built from d625284 with the kit, hooks run under strace inside the namespace):

| probe | question | result | rows |
|---|---|---|---|
| X1 | does `/allow` write anything? (static: no writer; traces never ran /allow) | userprompt-consent-allowlist.sh writes the legacy flag and the structured sentinel, under /tmp and under CLAUDE_STATE_DIR | A88 |
| X2 | is workflow-history ever written? (static: no writer; traces never saw it) | a second /dev in one session writes `workflow-history/<sid>/000001-dev-<ts>/{bookmark,todos}.json`; only its writer reads it | A13 |
| X3 | does /close's aggregate run rewrite a singular dev report? (trace-b saw a rename onto it) | not without doc-sync ledger records (bytes and inode unchanged); the code writes only when hook-landed-files records exist, which trace-b had | A34, A08 |
| X4 | is the todo list written-never-read? (trace-a flag) | pretool-spec-block-foreground-agent.py and pretool-workflow-gate.py read it (rc 2 on a /spec bookmark) | A10 |
| X11a | where does the privilege guard look for /do consent when CLAUDE_STATE_DIR is set? | writer: `$CLAUDE_STATE_DIR/claude-orchestrator-consent-<sid>.flag`; guard: `/tmp/claude-orchestrator-consent-<sid>.flag` (ENOENT) | A51 |
| X11b2 | where does the guard look for the push grant? | `/tmp/claude-push-grant-<sid>-*.json` with CLAUDE_STATE_DIR set, while hooks/push.sh:369 writes under the state dir | A73 |

Other disagreements were settled by reading the cited line (code-line check), for example: hook-landed-files is
written by doc_sync/hook_ledger.py and read only by aggregate-dev-report.py (static saw nothing); journal-view's four
trace readers open it only while listing docs/dev (the only literal is its writer, :460); the chain-B sentinel and the
push-gate token are written under a fixed /tmp and read under harness_state_dir() (execute-push.py:35 against
push.sh:106; agents/changelog-analyst.md:1221 and :1247, dispatched by commit.md:666, against push.sh:212);
contract_runtime probes `~/docs/dev/overnight/...` and cycle-0 contract candidates on every Agent call outside
overnight (trace-b, posttool-subagent-track.py and pretool-subagent-enforce.py).

## Excluded (not artifacts)

- From the traces (123 patterns): 53 directories, 44 private scratch files of one hook (canary self-tests, the runtime
  guard, O_TMPFILE), 11 OS, git or shell lookups and root probes, 11 repo-versioned directories, 4 repo-versioned
  files or git ignore lookups. Atomic-write temporaries and lock files were folded into the artifact they protect.
- From the static extractor (84 families that match no row): 41 tool-policy write-prefix families that name files
  nothing writes or reads (counted under A118, which covers all 94 such families, 74 of them outside the ledger),
  22 repo-versioned files, test fixtures and docs, 11 OS files, home dotfiles or another tool's files (for example
  the Codex CLI's session log), 9 directories, and `.git/index.lock` (git's own lock; hooks/pull.sh deletes it,
  which matters for P1c's fault list).
- Dropped rows: A17 (`docs/dev/arbitration-<cycle_id>.json`: named only in a comment,
  hooks/subagentstop-artifact-contract-enforce.py:295-296; nothing writes or reads it), A25
  (`docs/dev/ba-report-<ts>.json`, a path the replay driver passed to spec-check.py; no harness file names it), A115
  (`<proj>/**/.gitignore`, git's own lookups) and A123 (`/tmp/agentic-commit/pull-analyst/...`: named only in the
  prohibitions at agents/merge-analyst.md:34 and push-analyst.md:33; the pull-analyst writes no file,
  agents/pull-analyst.md:33-34, :158, and policies/tool-policy.v1.json:841-860 gives it no Write tool).

## Not covered, or covered only in part (step-1 work for P1b)

- Pipelines and steps the traces did not replay, or replayed with substitutions: prompts/P1b.md, "What the planning
  trace replayed". Singular /dev was not replayed either, and the CLI's settings writes were modelled as well as its
  transcripts and todos.
- 32 rows rest on code reading alone (`evidence` = code); they are the first places the regenerated map must trace.
- Commands outside the ten pipelines (/clean, /pull, /test) appear only where their artifacts were found.

## How it was produced

The inputs and this map were made by the planning workflow's scratch scripts, which are not published: the static
extractor (run on d625284 and on P8's head 0d26692), the trace-a and trace-b drivers and analysers, the ledger
re-check, the joins, the probe drivers for X1-X4, X11a and X11b2, and the map builder `build_map.py` (Python 3.12).
P1b does not rerun them: its scope row 0 regenerates the map on its own base with its own trace runner and the static
half of E1. The rows' producers, readers and deciding consumers were written by hand from the five sources and the
probe log; a reader enters the map only when the code line or a trace event backs it.

An independent verification pass then corrected six rows by hand from code reads at d625284 (no count above changes):
A31 (the test-writer's write instruction is agents/test-writer.md:207), A51 (eleven consent reader hooks with thirteen
read sites, not twelve), A86 (the overnight delivery marker is written at prompt-workflow.py:1039-1040 and read back
at :1180-1182, a cache; the idle and self-repair logs stay written-never-read), A88 (the /allow writes are
userprompt-consent-allowlist.sh:653-663 and :711-754; pretool-bash-safety.sh:499 and hooks/lib/allowlist.py read the
legacy flag), A94 (the `-all` daemon-restart flag is read at pretool-bash-safety.sh:613-620; per-target flags come
from the operator's external helper) and A117 (the agent bookmark is read at posttool-overnight-trace.py:394).

A review of the map (reviews/P1b-P1c-review-findings.md, facts-F1 and facts-F3) then corrected four more rows from
code reads at d625284: A52 and A71 gain a read never written when CLAUDE_STATE_DIR is set (/do reads its task sidecar
at /tmp; the push-analyst grant guard reads the state dir while the push-analyst writes /tmp); A73's read is
`_find_grant` at pretool-git-privilege-guard.py:328, not the block message at :2093; A117 drops four paths that are
written and the glob of the uncalled `_find_grant_any` (its `resolution` names each writer). None of the four has a
row now. Three are not written by the harness (`.claude/.awesome-claude-harness` is tracked,
`.claude/.hook-refactor-allow` is the human's sentinel, `<proj>/.claude/CLAUDE.md` is the user's project file). The
fourth, `~/.config/claude/protected-runtime.json` (written by scripts/bootstrap:362-386, read at
hooks/lib/runtime_guard/config.py:63), is a harness artifact this map does not list; it is left to P1b's regenerated
map (row 0).
The same review (facts-F7, F8, F10, F11, F12, F17, F18, owner-R17, R18) then deleted one row and corrected nine: A123,
the pull-analyst grant, is gone (the pull-analyst writes no file, agents/pull-analyst.md:33-34, :158; its directory is
named only in the prohibitions at agents/merge-analyst.md:34 and push-analyst.md:33); A58's append-error markers are
written (scripts/close-report-append.py:296) and never read, not the reverse; A106's landing log has two writers
(scripts/install/land and render-settings cmd_land) and the landing's notices name it to the owner; A109's doc-sync
notice state is read back by its writer (hooks/doc_sync/notice.py:469-470, a cache); A112 notes that /spec's output
names its temp note (commands/spec.md:473); A88 and A105 give P7b as merged (1071ad3); A40 adds the aggregator's two
status sets (scripts/aggregate-dev-report.py:784, :2099), A47 the spec writers it missed, and A98 marks its two
writers that settings.json does not register. A verification read then added a second writer to A68, the push-gate
token: the cleaner under /clean (agents/cleaner.md:109-111). A later code read added the writers of the overnight
per-pipeline spec to A80 (the orchestrator's template copy and the section updates of BA, dev, QA and the PM retro,
commands/dev-overnight.md:858-874, :1041, :1303, :1406-1407, :1613-1618), made A92, the /stop helper-auth token, a read
never written when CLAUDE_STATE_DIR is set (its writer, hooks/pretool-wrapper-userintent.py:74, uses the state dir; its
reader, scripts/break-overnight-lock.py:35, a fixed /tmp), and gave A93 the residual-override grants, which had no row
(scripts/write-git-residual-override.py:39, read at pretool-git-privilege-guard.py:2237). A further code read put
A93's keystone grants in `${TMPDIR:-/tmp}/claude-git-blessed` (scripts/mint-git-blessed-token.sh:39), not the state
dir, and gave them their reader and check, the git keystone hook (hooks/git-keystone/reference-transaction:48-63),
not the privilege guard. A verification read then corrected three more rows: A03 gains a read never written (/close's
inspectors read dev-registry/dev-<TASK_ID>/, commands/close.md:553-561, which nothing writes after /dev-command or
/do); A89's flags each have at most one deciding reader, not several (pretool-wrapper-userintent.py guards only /stop,
:66-71; write-commit-grant.py:460-473 reads the commit flag; break-overnight-lock.py reads only A92's token), so the
push and merge flags are written never read; A91's deciding readers all call hooks/lib/subagent_restart.py and take
one conclusion. A further verification read corrected A103 the same way: stop-overnight-timelock.py only tries to
publish terminal.json and ignores the result (:217-235), and the deciding readers left, pretool-tool-policy.py, the
Stop coordinator and scripts/session-resources.py, all decide through hooks/lib/session_resources.py. A103's producers
are that library's writes inside the project (session_resources.py:1127, :1149, :1168-1170, :1433, :1575, :2265), and
its paths add the pointer `.claude/session-resources/by-claude-session/<sid>.json` that every decider reads (:1286,
:1782); the row's earlier cites (:297-301, :485-513) write the session-resource trust registry outside the project
(`$LANEB_SESSION_RESOURCE_TRUST_ROOT/<sha256 of the project root>/<sid>.json`, written by provision at :1193 and by
finalize at :2298-2348), a second harness artifact this map does not list, also left to P1b's regenerated map. A later
code read took the hand-written-table label off two command lists in hooks/prompt-workflow.py, :1925 (A89: commit,
push, merge and stop get a user-intent flag) and :1929 (A01: dev, dev-command and redev reach the task-id mint at
:1462-1480; /do reaches that mint at :1320-1360 by its own branch, :1927-1928): each is the only rule deciding its
question and repeats no declaration (no dispatch record, schema or canonical todo step names either set:
scripts/todo/ has no commit, push, merge or stop step, and the obligation schema's pipeline enum, which
obligation.py:81-83 and pretool-obligation-gate.py:88-90 copy (A14), lists seven pipelines). A later
verification read found that the timelock's publish call reaches neither a read nor its write: the Stop coordinator,
the timelock's only runner, starts every phase without the two trust keys (stop-workflow-coordinator.py:108-111,
:147-155), so _trust_configuration raises first (session_resources.py:335-336), and terminal.json, which finalize
reads, is read never written (A103). A later verification read corrected A63, the commit grant: the privilege guard
reads it in `_collect_commit_grant_candidates` and `_has_active_commit_grant` (pretool-git-privilege-guard.py:388-420,
:1387-1417), not in `_find_grant`, which reads only push grants (:2135); the gitignore preflight's E5 is a second
deciding reader at the Agent dispatch (hooks/pretool-gitignore-preflight.py:669-698, called at :810); and the grant,
its .lck and its -active- pointer are written under a fixed /tmp (scripts/write-commit-grant.py:266, the guard's
:636), while the preflight (:655-656), the PostToolUse finalizer (posttool-allowlist-consume.py:55, :590) and the Stop
sweep (stop-cleanup-allowlist.sh:93, :286, :304) look for them in the state dir, a read never written when
CLAUDE_STATE_DIR is set. The same read found A62, the dispatch manifest, read never written as well: /commit writes it
under the state dir (commands/commit.md:404-407) while the changelog-analyst's check reads it at a fixed /tmp
(agents/changelog-analyst.md:206). The same read also corrected A70, the commit-event journal: it lives under the
state dir (hooks/lib/commit_journal.py:109) and is read by the changelog-analyst's push-gate reconciliation through
the module's query (agents/changelog-analyst.md:1644-1646), not by scripts/step7-spec-update.py, which imports nothing
from it and only accepts the resulting status (:161-170). The same read also put A94's `-all` daemon-restart flag
under CLAUDE_DAEMON_RESTART_GRANT_DIR, else CLAUDE_TMPDIR, TMPDIR or /tmp (hooks/pretool-bash-safety.sh:9, :17), and
A124's orchestrator.sh outputs under a fixed /tmp (scripts/orchestrator.sh:25-27, :243-244, :287, :352, :381, :429),
not the state dir; no writer or reader of either changes. A later code read corrected A105, the harness settings:
scripts/bootstrap:272-280 writes the overlay rather than reading it; render-settings' render, clean, smudge and
`check --staged` read the overlay and the record as `check` does, and smudge also writes settings.json's machine
form through git; the coexistence installer merges its hook groups into the config home's settings.json
(scripts/install/installer.py:1164, :1168); and besides render-settings, whose subcommands take one conclusion from
`load_overlay` and `load_record`, the files have deciding readers with their own rules: the commit block in
hooks/pretool-bash-safety.sh:355-368, the /allow deny preflight in hooks/userprompt-consent-allowlist.sh:437-615, the
claude_home probes, bootstrap's env.TMPDIR step (scripts/bootstrap:341-353), the capability binding, the
cleanliness-inspector's reference scripts and the installer. A105 therefore shows several deciding consumers too.
A later code read corrected A104, the project settings, the same way: /dev-command Step 14
(commands/dev-command.md:678-707) edits the file as /dev Step 15 does; the static candidate
scripts/create-overnight-state.sh:419 writes neither file itself but runs create-worktree.sh, which writes
settings.local.json; and besides the CLI's permission engine, the files have deciding readers with their own rules:
the /allow deny preflight (hooks/userprompt-consent-allowlist.sh:438-439, :597-623), the reference scripts the
cleanliness-inspector and QA run (scripts/check-file-references.sh, scripts/detect-orphan-scripts.sh),
scripts/apply-permissions.sh and the orchestrator's edit step, which stop on a file they cannot merge into, and, when
the project is the harness home, the capability binding. A104 therefore shows several deciding consumers too, and its
`check_elsewhere` names them. A later verification read of every row, from code and prose reads at d625284, then
corrected the following. A02, A03 and A05 gain the overnight launcher's check of the initializer's output
(scripts/create-overnight-state.sh:881-1019, exit 1 at :1019) and the initializer's own checks, which the actor
re-runs with --verify-only at every cycle (scripts/overnight-init.sh:284-293, :341-364, :451-452;
commands/dev-overnight.md:261, :325); A02 also gains the aggregator's minted-identity test
(hooks/doc_sync/ledger_contract.py:161-173) and graphify-query.py's status rule (scripts/graphify-query.py:284-288),
and A03 loses hooks/pretool-cp-checkin.py, which only matches the Read call's path (:132-151), while its read never
written now includes graphify's FIRST ACTION read under /dev-command, which checks no sentinel
(commands/dev-command.md:571, agents/graphify.md:22; hooks/prompt-workflow.py:1531-1547 writes graphify.json only when
a graphify binary resolves). A02, A05, A06, A26, A31, A32, A33, A48, A61 and A80 now show several deciding consumers:
A06 adds graphify-enrich.py's nil-map skip (scripts/graphify-enrich.py:477-491), A26 the orchestrator's status rule
for the BA dispatch (commands/dev.md:249), A32 and A33 QA Phase 5 (agents/qa.md:1125-1129), and A33 the orchestrator's
existence check (commands/dev.md:818), which A31 and A32 already list; agent_resolver's role resolution reads A48's
cp-state before the agent index (hooks/lib/agent_resolver.py:211-242) besides subagentstop-cp-enforce.py, while
pretool-cp-state-write-guard.py opens no cp-state file (a tool-call target guard); two hooks look for A61's
forced-close flag in different directories (hooks/subagentstop-e2e-enforce.py:387-388,
hooks/subagentstop-artifact-contract-enforce.py:365-373); and the orchestrator's prose field checks of A80's PM and
specialist reports sit beside the contract's schema check. A56 keeps that label through close QA, which routes only
inspector findings new in the diff (commands/close.md:677-699), while the gitignore preflight reads no inspector
report (hooks/pretool-gitignore-preflight.py:785-791) and the other deciders call one validator; A62 loses it, since
the changelog-analyst's manifest read only warns (agents/changelog-analyst.md:204-210). A24 shows a consumer-side
re-check (its G4 re-check and scripts/dev-lifecycle.py:614-626); A95 no longer does, because score-update.sh's
close-report precondition reads the close report, not the ledger, and A57 counts it. A07's start-sha is read by QA
(agents/qa.md:1161) and written by nothing; scripts/overnight-status.sh looks for A76's overnight state in
docs/dev/overnight (:11), while the launcher writes `.claude` (scripts/create-overnight-state.sh:93, :704); A99's
hooks/fswatch-manager.sh reads a state file and a log under names the watcher never writes (:17, :171;
hooks/git-fswatch.sh:27, :31); and no step creates A116's context-with-reports, which /clean's Step 11 reads
(commands/clean.md:333): each is a read never written. A16 reads nothing its writer does not write, A17's file is
named only in a comment, A29's requirement copy is written in the Bash block that reads it
(commands/dev-overnight.md:961-968), and A87's specialist yield log has a writer (hooks/lib/specialist_yield.py:307)
and its deciding reader is the PM's degradation check (agents/pm.md:351-371), not closeout, so none of the four is
read never written. A60's human-operator transcript has no reader (its parser, scripts/dev-lifecycle.py:766-790, has
no caller); the orchestrator writes A81's qa-verification-plans.json at /dev-overnight Step 14
(commands/dev-overnight.md:1357-1364) and nothing reads it, and the ledger's cycle-contract reader reads none of A81's
files; no owner-facing output names A82's overnight deadlock report (commands/dev-overnight.md:117, E12); and only BA
opens A122's observations ledger (agents/ba.md:504-509): each is written never read. A20's context-iter is consumed by
the next dev dispatch and also written by scripts/refine-context.sh (commands/dev-overnight.md:1492-1497); A27's
graphify outputs, A28's per-pipeline run record and A33's global test index have prose readers (commands/dev.md:780,
agents/dev.md:127, agents/qa.md:120-121, commands/dev-overnight.md:1246, agents/qa.md:1129); and A79's artifact-status
sidecar has one in code (hooks/posttool-subagent-track.py:358-368, called at :403). A19, A22 and A44 gain the
late-repair controller as a producer (scripts/late-repair-controller.py:312 embeds its disclosure in the BA context
and ticket and in the singular QA report, as it does in A34's dev report); A49's `.split-complete` marker is written
by the /spec orchestrator (commands/spec.md:420), not by the spec subagent that writes the views, so A49 shows several
producers; and A108's INDEX.md and README.md are also written under /clean by the rule-inspector and the cleaner,
while the cleanliness-inspector /close dispatches reads each folder's README.md
(agents/cleanliness-inspector.md:74, :82) and scripts/orchestrator.sh:204-224 stops on a missing one before the
rule-inspector has run, so A108 shows several producers and several deciding consumers. A15's QUESTION_ARTIFACT_ROLES
(hooks/subagentstop-artifact-contract-enforce.py:716) repeats the producer-question schema's role enum, a hand-written
table recorded on A15, the artifact it serves; A119 adds two rosters it missed (hooks/posttool-overnight-trace.py:50,
scripts/late-repair-controller.py:51). A100's deciding read is the handshake verdict that scripts/doctor --strict and
scripts/install/preflight act on (scripts/capability-doctor-strict.py:146, :158); the capability gate is not
registered. A85 drops the modern-git slot, the operator's distribution that no harness file writes
(scripts/modern-git-slot/README.md:3-16), so like `.hook-refactor-allow` it has no row; A124 drops its six -output-*
paths, which orchestrator.sh only prints, as A123 was dropped. The check columns follow one rule (a later read moved
the entries this read had left outside it). A hook or script decider is named under `check_producer_stop` when the
producer reads its own file to decide, as A16's G2 does (A11, A13, A30's ensure-async, A43's late-repair controller,
A48's spec-check.py, A53, A55, A85's helper at the launch, A90, A93's refusal journal, A113, A99's watcher, the
launcher's check in A02, A03, A05 and A85, and the producing hook's re-check in A02, A03 and A05), so A11's dev-start
replay store, a cache its writer reads back, shows no violation; otherwise it goes under `check_elsewhere`, as in A93
and A104 (A02, A05, A29, A30, A81, A85's helper each time the actor sources it, A91's and A120's checks on /restart's
SendMessage, A92, A99's manager, A108, A111, A116). A check at a collection point is named at G3 (A33's existence
check; A79's reader at the Agent call's PostToolUse; check-overnight-reports.py, whose one run is at the specialists'
collection, commands/dev-overnight.md:682, for A77 and A80), and an orchestrator prose route elsewhere goes under
`check_elsewhere` (A26's status route before the BA dispatch; A28's Step 11g fingerprint check, which A19 and A20 also
name, leaves G1, which the column keeps for PreToolUse checks on the Agent call). A decision made inside an agent's
own work gets no column (QA in A06, A26, A32, A33 and A121, A87's PM, A108's cleanliness-inspector), apart from the
/close and /commit checks that `check_elsewhere` names (close QA in A56, the changelog-analyst in A34 and A54). Cells
that named a skip, a write, a hint, a read that does not happen, or a check that decides nothing or never runs lose
their entry (A10, A21, A39, A45, A60, A64, A78, A87). The same read completed the producers, readers, deciders, check
cells or cite ranges of A01, A09, A14, A19, A22, A34, A35, A40, A43, A44, A45, A47, A50, A54, A57, A65, A76, A84, A91,
A96, A98, A101, A102, A103, A107, A117, A120 and A121, among them four warn-only hooks that read the newest BA context
by mtime (A19), and recorded P8's line shifts in A51, A62, A65, A69, A73 and A76. A later code read then completed
nine rows: A06's QA comparison is its Phase 6 (agents/qa.md:1150-1169; :1609 is the report field); in the actor's
--verify-only run the initializer first asserts that A02's requirement document exists and matches
(scripts/overnight-init.sh:163-165, through :447) and that A03's registry directory exists (:136, through :253);
/dev-command runs A26's pre-query and routes on its status too (commands/dev-command.md:194);
late-repair-controller.py verify-disclosure reads the singular context or ticket (A19, A22), dev report (A34) and QA
report (A44) its run record names and refuses on a missing file, a missing block or a hash mismatch (:438-454), at
/close --late-repair (commands/close.md:143) and, through resolve_effective_report_state (:496), at /commit; and
A108's cleaner writes only INDEX.md, through the rule-inspector's index script (agents/cleaner.md:77, :91). Another
verification read of every row, from code and prose reads at d625284, then corrected the following. A producer that
reads its own file back to decide is now named under `check_producer_stop` in more rows: the producing hook runs the
initializer's --verify-only check itself, at the /dev-overnight launch (a failure removes the record and exits 2) and
at each prompt that names no command while the record is live, with a --repair-only run between two checks
(hooks/prompt-workflow.py:1966-1972, :1179, :1690-1729), which A02, A03 and A05 now name, as A02 does the id mint's
skip of a timestamp whose requirement document exists (:1470-1472); the late-repair controller refuses on A43's run
record at record-stage and finalize (scripts/late-repair-controller.py:273-290, :327-334), and A43 also gains
verify-disclosure's run at /close --late-repair (commands/close.md:143), which reads the run record and the effective
report; scripts/spec-check.py refuses a mark or waive on A48's cp-state that another role or agent owns or that is
closed (:495-514, :564-654, :804-827, :873-908); and the git privilege guard, the only writer of A93's refusal
journal, reads it back at a later call (hooks/pretool-git-privilege-guard.py:2281-2303). A28, A30, A85, A95 and A120
now show several deciding consumers: closeout re-checks A28's cycle copy before the time-lock's exit 2
(hooks/lib/closeout.py:451-470, hooks/stop-overnight-timelock.py:248-250) beside Step 11g's fingerprint skip;
graphify-maintain.py ensure-async decides by its own rule on A30's cache, which its own init builds
(scripts/graphify-maintain.py:675-691), a `check_producer_stop` entry; A85's shims are checked by their own writer,
which refuses to arm when an installed file differs from its source (scripts/overnight-git-env.sh:49-55, :77-82), at
the launch, where the launcher also refuses a shim it cannot execute (scripts/create-overnight-state.sh:609-625), and
each time the actor sources it before a git op (commands/dev-overnight.md:289); scripts/score-inject.sh exits 1 on an
unreadable or malformed score ledger (:128-160); and A120's transcripts, which only the CLI writes, are decided on by
harness readers through parsers of their own (hooks/lib/subagent_restart.py with hooks/lib/obligation.py,
hooks/lib/stop_contract.py, hooks/pretool-aggregate-check.py:409, hooks/stop-spec-coverage-enforce.py:129-160), while
hooks/pretool-workflow-gate.py and hooks/lib/subagent.py look in them only for a Codex record type and decide nothing
on them. posttool-todo-count.py and posttool-todo-tracker.py decide on A09's bookmark
(hooks/posttool-todo-count.py:85-88, exit 2 at :60). Entries that run at the stop or the write of an agent that does
not produce the file move to `check_elsewhere`: the G2, e2e, codex and lane-watch entries of A01, A03, A04, A05, A14,
A34 and A36; the probes of A61's forced-close flag, which has no producer, at QA and dev stops
(hooks/subagentstop-e2e-enforce.py:387-388, hooks/subagentstop-artifact-contract-enforce.py:365-373, :1215); the /do
Stop gate's read of A52's task sidecar, which hooks/prompt-workflow.py writes at UserPromptSubmit
(hooks/stop-do-report-gate.py:187-191); and the e2e gate's read of A54's do-report at a QA stop
(hooks/subagentstop-e2e-enforce.py:166-209, :410). The deciders on /restart's SendMessage, which is no Agent dispatch,
move from G1 to `check_elsewhere` in A91 and are named there in A120. A check the orchestrator runs when the producing
subagent returns is named at G3, inside /close, /commit, /push and /merge too, as commands/close.md:567 is in A56: the
aggregator's shard check at /dev Step 11, after the parallel devs return, in A34 and A39 (commands/dev.md:898-912,
scripts/aggregate-dev-report.py:796-835), A49's finalize resolver run (commands/spec.md:424), A57's scoring scripts
(commands/close.md:803-845), A66's file cross-check (commands/commit.md:579-583), A67's status parse
(:673-681, :851-854), A71's execute-push.py (commands/push.md:180-230) and A74's grant validation
(commands/merge.md:127-166). A71 shows a consumer-side re-check, as A74 does:
hooks/pretool-push-analyst-grant-guard.py re-validates at the Bash PreToolUse (:209-245) the fields execute-push.py
validates. Cells that named a check that decides nothing or never runs lose it: hooks/pretool-subagent-code-block.py,
which exits 0 on every path (:34-56), is no longer a decider or a check in A04 and A48; nor is
hooks/pretool-overnight-hook-guard.py in A48, reached only behind a contract self_repair block no writer sets
(:339-343); the unregistered hooks/sessionstart-artifact-census.py leaves A46 and A57; and A103's
scripts/session-resources.py, which no command, hook or script runs (settings.json:183-184 only permit it), loses its
check position, as A100's uncalled --route mode has none. A31 loses QA Phase 5 as a reader (agents/qa.md never names
the test-writer report), and A85 loses overnight-git-selftest.sh, which runs the source shim. A98, A99, A104 and A105
no longer cite as live the legacy installers hooks/install-auto-sync.sh, hooks/install-protection-all.sh and
hooks/install.sh, which exit 0 before any step (:12, :11, :15), so logs/git-watcher.log, written only by
install-auto-sync.sh, leaves A99. A108 adds /dev-overnight's PM and specialists, which read the project root's
README.md for the app URL or the product description (agents/pm.md:232-236), a file doc-sync creates when the root has
none. A17, a name only a comment carries (hooks/subagentstop-artifact-contract-enforce.py:295-296), is dropped as A123
was. The same read completed the producers, readers, deciders, check cells or cite ranges of A01, A02, A06, A10, A14,
A19, A23, A24, A27, A31, A32, A34, A35, A36, A37, A38, A39, A45, A47, A49, A53, A57, A59, A63, A64, A68, A69, A76,
A77, A80, A88, A92, A96, A100, A111, A116 and A119, among them the G3 barrier
(hooks/pretool-aggregate-check.py:558-633) on every obligation-declared file in A01-A40. The counts in this README
include all of these corrections; `build_map.py` printed 122 rows, 82 covering the ledger rows, 40 outside the ledger,
several producers 35, several deciding consumers 37, written never read 29, read never written 18, no violation
found 21, evidence 86 / 33 / 3, 33 code-only rows, producer stop 30, G1 dispatch 13, G3 collection 18, elsewhere 67,
G03 5 and G12 6.

## Limits

- One replay per pipeline in a sandbox with modelled agents; agent prose behaviour (which files an agent opens) is as
  the drivers modelled it.
- P7b's entries (A88, A105-A107) were re-read at its merged head 1071ad3; no other row was re-traced on master 301d696.
- Static-only rows (`{s}`) are candidates: their producer or reader was found by the extractor and not checked line by
  line unless the `resolution` says so.
