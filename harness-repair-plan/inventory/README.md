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
| artifacts (rows) | 121 |
| covering the 56 ledger rows (split where one ledger row holds several files with different producers) | 82 |
| found by the static extractor or the traces outside the ledger | 39 |
| several producers | 38 |
| several deciding consumers (each with its own rule) | 34 |
| consumer-side re-check or re-derivation | 29 |
| written never read | 28 |
| read never written | 21 |
| hand-written table | 27 |
| no violation found | 22 |
| evidence: both code and trace / code only / trace only | 87 / 33 / 1 |

Check positions named in the rows: producer stop 30, G1 dispatch 13, G3 collection 18, elsewhere 67.

Rows per group (the groups become P1b's scope rows): G01 cycle identity and registry 8; G02 workflow bookmark, todo
list, replay stores 5; G03 dispatch record and producer-gate outputs 5; G04 BA and context family 12; G05 test-writer
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
| `id` | A01-A124 (A25, A115 and A123 were dropped, see "Excluded") |
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
- Dropped rows: A25 (`docs/dev/ba-report-<ts>.json`, a path the replay driver passed to spec-check.py; no harness file
  names it), A115 (`<proj>/**/.gitignore`, git's own lookups) and A123 (`/tmp/agentic-commit/pull-analyst/...`: named
  only in the prohibitions at agents/merge-analyst.md:34 and push-analyst.md:33; the pull-analyst writes no file,
  agents/pull-analyst.md:33-34, :158, and policies/tool-policy.v1.json:841-860 gives it no Write tool).

## Not covered, or covered only in part (step-1 work for P1b)

- Pipelines and steps the traces did not replay, or replayed with substitutions: prompts/P1b.md, "What the planning
  trace replayed". Singular /dev was not replayed either, and the CLI's settings writes were modelled as well as its
  transcripts and todos.
- 33 rows rest on code reading alone (`evidence` = code); they are the first places the regenerated map must trace.
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
:66-71; write-commit-grant.py:460-468 reads the commit flag; break-overnight-lock.py reads only A92's token), so the
push and merge flags are written never read; A91's deciding readers all call hooks/lib/subagent_restart.py and take
one conclusion. A further verification read corrected A103 the same way: stop-overnight-timelock.py only publishes
the terminal receipt and ignores the result (:217-235), and the two deciding readers left, pretool-tool-policy.py and
the Stop coordinator, both decide through hooks/lib/session_resources.py. A103's producers are that library's writes
inside the project (session_resources.py:1127, :1149, :1168-1170, :1433, :1575, :2265), and its paths add the pointer
`.claude/session-resources/by-claude-session/<sid>.json` that both deciders read (:1286); the row's earlier cites
(:297-301, :485-513) write the session-resource trust registry outside the project
(`$LANEB_SESSION_RESOURCE_TRUST_ROOT/<sha256 of the project root>/<sid>.json`, written by provision at :1193 and by
finalize at :2298-2348), a second harness artifact this map does not list, also left to P1b's regenerated map. The
counts in this README include all of these corrections; `build_map.py` printed 122 rows, 40 outside the ledger,
several producers 35, several deciding consumers 37, written never read 29, read never written 18, no violation
found 21, evidence 86 / 33 / 3 and G12 6.

## Limits

- One replay per pipeline in a sandbox with modelled agents; agent prose behaviour (which files an agent opens) is as
  the drivers modelled it.
- P7b's entries (A88, A105-A107) were re-read at its merged head 1071ad3; no other row was re-traced on master 301d696.
- Static-only rows (`{s}`) are candidates: their producer or reader was found by the extractor and not checked line by
  line unless the `resolution` says so.
