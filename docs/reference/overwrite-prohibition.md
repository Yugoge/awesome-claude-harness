# Prohibition on wholesale replacement of an existing file

**Enforcement artifact**: `hooks/pretool-overwrite-guard.py`
**Route corpus**: `hooks/tests/fixtures/overwrite_corpus.json`
**Behavioural driver**: `hooks/tests/test_overwrite_guard.py`
**Shared lexer**: `hooks/lib/bash_write_targets.py` (`extract_bash_write_targets_with_modes`)

---

## 1. What this delivers, stated without inflation

> **For each Bash tool call, if the command names a replacing verb whose target
> resolves to an existing regular file, that call is refused unless a matching
> single-use grant names that exact file — and either outcome is recorded.**

That is a syntactic filter over one tool's visible input. It is defeated by a
two-line Python script, a wrapper script, an interpreter fed on stdin, a
compiled binary, a variable-indirected path, `mv`-away followed by creation,
racing the existence check, or editing the guard's own file. Section 6
enumerates all of it, and every entry there is **demonstrated by execution**,
not asserted.

What it does deliver is real: both incidents that motivated this work were
single-command, literal-path, direct-Bash replacements of the live
configuration, and both would have been refused. And after this, any
replacement through a covered route is **attributable** — which the third
replacement of that file was not, and which nothing else in this harness
provides.

## 2. What is never gated

Incremental modification is the legitimate path and is **completely ungated**.
The guard registers matcher `Bash` only; it places no interception on any edit
tool.

| Always allowed | Why |
|---|---|
| `Edit`, `MultiEdit`, `NotebookEdit`, the `Write` tool | Outside the matcher entirely. The guard never sees them. |
| `>>`, `tee -a` | Appending derives nothing from replacement. |
| `sed -i`, `perl -i`, `ex -s`, `patch` | Output is derived from the original as an input stream; no byte is reproduced from memory. |
| Any target that does not exist | Creation is never denied, however the path is spelled. |
| `mv src newname` | Renaming to a destination that does not exist is creation. |
| `mv`/`cp`/`install` into an existing **directory** | A move-into is not a replacement. Only the resolved `<dir>/<basename(src)>` collision is refused. |
| `> /dev/null`, `2>&1`, any device / FIFO / socket | Decided by **file type**, never by a path-string allowlist. |
| Any target the guard cannot affirmatively resolve | See section 5. Denying here would deny creation. |

A guard that fires on ordinary developer work gets switched off, and then
nothing is protected at all. Every row above is a regression pin in the test
module for exactly that reason.

## 3. Write-mode decision table

The verdict is decided on the **resolved identity**: symlinks followed to
`realpath`, relative paths resolved against `payload['cwd']`.

| Class | Verbs | Resolved target | Verdict |
|---|---|---|---|
| truncating | `>`, `>\|`, `tee` (no `-a`), `truncate`, `dd of=`, `cp` (non-recursive), `install`, `curl -o`, `wget -O` | existing regular file | **DENY** unless grant |
| truncating | as above | does not exist | ALLOW (creation) |
| truncating | as above | existing **directory** | ALLOW as move-into; re-resolve to `<dir>/<basename(src)>` and re-apply |
| truncating | as above | existing non-regular file | ALLOW |
| rename-into-place | `mv` | existing regular file | **DENY** unless grant |
| rename-into-place | `mv` | does not exist / directory | ALLOW (creation / move-into) |
| destroying | `unlink` | existing regular file | **DENY** unless grant |
| appending | `>>`, `tee -a` | any | ALLOW |
| in-place edit | `sed -i`, `perl -i`, `ex -s`, `patch` | any | ALLOW |
| unresolvable | any target not affirmatively resolvable | — | **ALLOW**, declared uncovered |

`mv` onto an existing regular file is denied despite being the crash-safe way
to write a file. Crash-atomicity says nothing about intent: `mv tmp victim`
loses the previous contents exactly as completely as `> victim` does, and
permitting it on shape would hand every agent a two-token bypass that merely
*looks* disciplined.

`unlink` is present to close the delete-then-create composition as far as it
can be closed. `rm` is not, because `hooks/pretool-bash-safety.sh` already
blocks all filesystem `rm` globally.

## 4. The authorized escape

A blanket prohibition with no escape blocks legitimate work, so the escape is a
**narrow, auditable, single-use grant** — not a mode.

- Issued through the existing human path: `/allow Write /absolute/path`, which
  `hooks/userprompt-consent-allowlist.sh` mints as
  `{"op": "Write", "target": "/absolute/path"}`.
- Matched by the existing `hooks/lib/allowlist.py::match_sentinel_grant_for_write`.
  **No new operation name, no new issuance channel, and no modification to the
  shared matcher.**
- **Correction, measured rather than assumed**: the specification for this work
  asserted that "an agent cannot mint its own grant". That is **false as
  shipped**, and pretending otherwise would be the exact species of unverified
  claim this document exists to avoid. The sentinel grant is an ordinary JSON
  file under `/tmp/claude-grants/`; creating it is *creation of a path that does
  not exist*, which is never denied — by binding requirement. An agent can
  therefore mint a grant naming any target and then replace that target. See
  `grant-self-minting` in section 6, where it is demonstrated by execution.
  This guard adds **no** new issuance channel; it inherits an escape hatch whose
  file-level integrity was never enforced.
- **Correction, measured rather than assumed (2)**: this document previously
  stated that the grant is "consumed on any terminal result by the existing
  `hooks/posttool-allowlist-consume.py`". That was **false as shipped**, and it
  made the escape a *mode* rather than the one-shot claimed two paragraphs
  above. That consumer gates its unlink on `match_sentinel_grant_for_bash_command`,
  which reads the shell command's **first word** as the op name; the only grant
  shape this guard accepts is `{"op": "Write", "target": …}`, which no shell
  command can spell. The unlink therefore never fired and one grant authorized
  replacements of its target **without limit** until it expired. Combined with
  the self-minting route above, one minted grant was an open licence.
- **Consumed by this guard, at the moment it authorizes.** The grant file is
  unlinked before the call is permitted, so the second identical attempt is
  refused. Because `unlink` is atomic, the file *is* the mutual exclusion:
  two guards racing on one grant both attempt it, exactly one succeeds, and the
  loser is refused with `decision: refused_grant_not_consumed`. The property
  therefore holds **concurrently**, not merely serially — see
  `concurrent-grant-reuse` in the corpus, which this reclassified from uncovered
  to covered.
- **The cost of that, stated plainly**: the grant is spent when the replacement
  is *authorized*, not when it succeeds. A call that another hook then blocks,
  or that fails, has still spent its grant and the human re-issues it. The
  opposite choice would restore unlimited reuse. Nothing else spends it: an
  ungated command, an append, an in-place edit, a creation, and a refused
  attempt on a different file all leave the grant intact.
- **Correction, measured rather than assumed (3)**: moving consumption into this
  guard was right, but the first version of it spent the grant through the
  shared consumer, which enumerates grant files by task-id **prefix**. Under
  this repository's own fan-out naming — parent `dev-<cycle>`, lanes
  `dev-<cycle>-<lane>` — a parent-task agent was therefore authorized by a
  **child lane's** grant and *destroyed* it. That was a consequence of the
  fix, and iteration 1 declared it nowhere. **Which** grant may be spent is now
  bound exactly: the grant's own `task_id` must equal the running task, its
  `session_id` must equal this session, and it must itself authorize every
  target credited to that task — all three on the same file. A call that cannot
  spend an exactly-owned authorizing grant is **denied**, so the prefix latitude
  in the shared matcher can no longer carry a replacement through. The latitude
  itself is unchanged, because that module is shared and was not modified: a
  prefix-sibling grant can still be *offered*, it simply can no longer be spent.
  Demonstrated by `cross-lane-grant-consumption` in the corpus.
- The grant must carry an explicit **absolute** target. Both the grant target
  and the candidate are `realpath`-normalized before comparison: the sentinel
  records no grant-time cwd, so a relative target could not be compared
  honestly, and a grant that silently authorizes nothing is worse than one
  refused loudly.
- A bare `{"op": "Write"}` entry is an intentional wildcard for the **Write
  tool** and stays exactly as it is there. It does **not** authorize shell
  replacement.

## 5. Failure behaviour

**Affirmative denial.** The guard denies only when it establishes BOTH (a) a
replacing verb and (b) a target resolving to an existing regular file. Every
other state allows.

**Bootstrap failure fails OPEN**, with a non-suppressible stderr warning naming
`hooks/pretool-overwrite-guard.py` and an audit row. A guard that cannot load
cannot tell `2>&1` from a real replacement, and failing closed would deny
nearly every Bash call in the session — including the diagnostics needed to
repair the guard. A fail-closed control that seals its own repair path is worse
than the risk it prevents.

The repair path is never sealed even at maximum strictness: the edit tools are
never touched, appending is never denied, and creating a file that does not yet
exist is never denied.

**Documented interaction, not an asserted outcome**: making the *shared* lexer
`hooks/lib/bash_write_targets.py` unimportable trips
`hooks/pretool-tool-policy.py`'s fail-CLOSED bootstrap (`exit 2` on
`ImportError`) and denies **every** Bash call in the session. That is a
property of the other hook, recorded here so nobody discovers it during an
incident. It covers import failure only — see `semantic-lexer-corruption` below.

**Attribution.** Every refusal and every grant-permitted replacement appends a
structured JSONL row (`flush` + `os.fsync`) to `logs/overwrite-guard.jsonl`
under the resolved harness home, naming the resolved target, the mechanism, the
decision, the grant identity when one was used, the session and task
identifiers, and a timestamp. **If the append fails, the operation is DENIED on
both paths.** A replacement that cannot be attributed must not proceed:
unattributability is precisely the defect this requirement exists to fix. This
can wedge an authorized replacement, which is the accepted fail-closed trade —
tolerable only because it is isolated from editing, appending and creation,
which are never gated.

## 6. Uncovered Routes

Every route below is recorded in `hooks/tests/fixtures/overwrite_corpus.json`
with `coverage: "uncovered"` and is **executed by the test suite against a file
containing known bytes, and required to still replace them**. A route that
turns out to be blocked fails the suite and forces this list to be corrected.
An uncovered set that is prose rather than a tested artifact is the defect this
work exists to end.

| route_id | Why it cannot be covered here |
|---|---|
| `displace-then-create` | `mv victim backup` then a creating write to the vacated path. Both halves must be allowed — moving a file to a new name is ordinary work. This is why the guarantee is per-Bash-call. |
| `interpreter-script` | The path exists only inside a script file; it is not in the text the hook is given. |
| `interpreter-stdin` | The program arrives as a quoted argument, which the lexer masks precisely so quoted content is never mistaken for a path. |
| `wrapper-script` | The hook sees `bash script.sh` and cannot see the redirect inside. |
| `compiled-binary` | Command-text analysis cannot reach inside a process. Unbounded class. |
| `variable-indirection` | The lexer yields the literal `$T`. Denying it would deny creation. |
| `quoted-command-word` | `'cp' src dest` — the pass that blanks quoted spans (which is what makes `echo 'foo > bar'` safe) blanks the verb too. Telling a quoted *command word* from quoted *content* needs the position-aware parsing that pass exists to avoid, and getting it wrong fires on ordinary work. |
| `absolute-path-verb-after-prefix-word` | `OVW=1 /bin/cp src dest`, `sudo /bin/cp`, `time /bin/cp`, `! /bin/cp`, and after the keywords `then`, `do` and inside `{ … }`, `case` bodies and function bodies — the absolute form is recognized only at a **command-word position** (start, or after `;` `\|` `&` `(` or a newline), and any preceding *word* puts it one token later. The *bare* spelling in every one of those positions **is** covered, so this is a real asymmetry, stated at its measured width. It is deliberate: the looser anchor that removes it fires on the read-only `ls -la /usr/bin/cp file`. Both the route and the rejected alternative are demonstrated by execution. |
| `command-substituted-verb` | `$(which cp) src dest` — the verb is not in the command text at all. Resolving it means executing the substitution at hook time, which a PreToolUse hook must never do. |
| `check-use-race` | The decision is pre-execution; a path absent at check time can exist by open time. No pre-execution check closes this. |
| `semantic-lexer-corruption` | A lexer that imports cleanly but returns incomplete targets degrades this guard **silently**, without tripping tool-policy's fail-closed bootstrap. |
| `redirect-ampersand` | `&>` shares its prefix with fd duplication (`2>&1`), which must never be treated as a write. The verb set was fixed by requirement, so this is declared rather than silently absent. |
| `recursive-copy` | `cp -r` replaces children beneath a destination directory, invisibly to a command-text lexer. |
| `rsync-dest` | Same undecidable destination set as `cp -r`. |
| `archive-extract` | Member enumeration needs the archive read at preflight — impossible for `curl … \| tar -x`. |
| `gzip-force` | The write target is derived from the operand rather than named by it. |
| `symlink-force` | `ln -sf`'s one-argument form targets `./<basename>`, so target derivation is ambiguous across the verb's forms. |
| `grant-self-minting` | The escape hatch's own file is creatable by an ordinary allowed write. Closing it would require gating creation of a path, which the binding narrowing forbids. See the correction in section 4. |
| `multi-source-copy` | `cp a b dir/` re-resolves only the LAST source, so `dir/basename(a)` is replaced undetected. |

### Routes reclassified OUT of this list

A route leaves this list only by being closed and demonstrated closed. It is
recorded here rather than deleted, because an uncovered set that can shrink
without trace is prose again.

| route_id | Was declared | What changed |
|---|---|---|
| `concurrent-grant-reuse` | "Consumption is PostToolUse, so two calls issued before the first terminal result both observe one grant. Single-use holds for **serial** use only." | Both halves were wrong: the grant was never consumed at all, so single-use did not hold even serially. Consumption now happens in this guard at authorization time and the atomic `unlink` is the mutual exclusion, so the concurrent case closed with the serial one. Now `coverage: "covered"` in the corpus, carrying `reclassified_from`, its reasoning, and its residual. |
| `absolute-path-verb` | "Accepting any token *ending* in the verb name would name a target from `./tools/backup-cp` — the cries-wolf direction the requirement forbids." | **The stated reason was disproved by execution, not merely superseded.** It defeats only a naive *suffix* match and says nothing against an *anchored* rule. An anchored rule — the token must begin with `/` **and** sit at a command-word position — closes the route with **zero** false positives on `./tools/backup-cp` and on every near-miss now pinned in the corpus's `false_positive_controls`. Only the directory part is blanked, so the basename is judged by exactly the same verb patterns as the bare spelling; no verb pattern was loosened and no verb added. Now `coverage: "covered"`, with the residual `absolute-path-verb-after-prefix-word` declared above. |

### Syntaxes that were silently uncovered, and are now covered

These were in neither this list nor the corpus. They are recorded because an
*unstated* gap is the exact defect this document exists to end — a gap that is
declared can be traded against, and a gap that is not cannot.

| Syntax | What it did | Status |
|---|---|---|
| `\cp SRC DEST` (leading backslash) | Every verb pattern required a `[\s;\|&]` boundary before the command word, and a backslash is not in that class. One byte defeated **nine of the eleven** covered verbs, with the path fully visible in the command text. `\cp` is the routine alias-bypass idiom. | Closed. Derived against **every** covered verb by `test_f1_backslash_prefix_defeats_no_covered_verb`, so a verb added later cannot reacquire it. |
| `(cmd > victim)` (grouping subshell) | Worse than a miss: `)` was absorbed into the path token, so the guard resolved a path that does not exist, classified a real replacement as **creation**, and returned an affirmative *allow*. `(cd dir && cmd > file)` is a common agent idiom. | Closed. `(` now opens a command word and `)` terminates an unquoted token. Derived against every covered route. |
| `curl -o<PATH>`, `wget -O<PATH>` (attached flag) | `getopt` accepts the attached form exactly as the spaced form; only the spaced form was read. Same shape as Incident 1. | Closed. |
| `/bin/cp SRC DEST` (absolute-path verb) | Declared uncovered in iteration 1 on a reason that did not survive execution — see the reclassification table above. It is the same family as `\cp`: the program is the covered verb and the path is fully visible in the command text. | Closed in iteration 2. The **directory** part of an absolute command word is blanked, length-preservingly, so the basename meets the unchanged verb patterns. Anchored twice — leading `/` **and** command-word position — and pinned by twelve executed `false_positive_controls`. |

Closing the backslash form made the *family* visible, so the family was probed
rather than assumed closed. Three further members — `quoted-command-word`,
`absolute-path-verb` and `command-substituted-verb` — run and replace, are
**not** closed, and are now demonstrated as uncovered routes in the table above.
They were undeclared before this iteration too. Each is left open for a stated
reason rather than an absent one: closing any of them means loosening a pattern
that currently prevents the guard from naming a target in a command that is not
a write at all, and a guard that fires on ordinary work gets switched off.

The token-termination fix lives in the **shared** lexer, so it also corrects a
false **positive** in `hooks/pretool-tool-policy.py`, which refused a read-only
`(… 2>/dev/null) | head` by inventing a write target named `/dev/null)`. One
absorbed byte failed *open* here and *closed* there. All four consumers of that
module were re-verified: 26 command shapes byte-identical, and the only changes
are the grouped and escaped forms now naming their true path.

A quoted filename that genuinely contains a parenthesis (`> "report (1).txt"`)
is read whole and still judged — the quoted branch of the token reader is
deliberately untouched, and the corpus row `quoted-paren-filename` pins it.

### Known false-positive profile — read this before registering

The guard refuses `cmd > logfile` when `logfile` already exists, because that
*is* wholesale replacement. Concretely, these ordinary commands are refused on
their **second** run:

```
npm run build > build.log
pytest -q > results.txt
git diff > /tmp/patch.txt
jq . conf.json > conf.tmp && mv conf.tmp conf.json     # the mv is refused
cp config.example.json config.json                      # once config.json exists
```

Since iteration 1 that profile also covers the **grouped and escaped spellings**
of the same commands — `(cd build && npm run build > build.log)` and
`\cp config.example.json config.json` are refused exactly as their plain forms
are. This widens the false-positive surface, and deliberately so: a boundary
that a one-character prefix walks around is not a boundary. It changes nothing
about what is ungated — editing, appending, in-place editing and creation stay
completely ungated in grouped and escaped form too, and that is pinned by
`test_f1_f2_do_not_gate_ordinary_developer_work`.

Since iteration 2 it also covers the **absolute spellings** of those same
verbs: `/bin/cp config.example.json config.json` and `/usr/bin/install -m 644
src dest` are refused exactly as `cp` and `install` are. **No verb was added** —
only the spellings of the verbs already listed in section 3. The widening is
therefore bounded by that table and by nothing else, and it inherits whatever
cries-wolf behaviour the bare spelling already had: a vendor script that happens
to be named `install` is refused as `/opt/tool/install` for the same reason it
is refused as `install`. What it deliberately does **not** widen to is any token
that merely *ends* in a verb name (`backup-cp`, `my-cp`, `scp`) or any absolute
path that is not the command word — a redirect target such as `> /tmp/cp`, an
argument such as `cp /bin/cp dest`, and read-only inspections such as
`ls -la /usr/bin/cp file`, `diff /bin/cp /usr/bin/cp` and `test -x /bin/cp` all
stay silent. Those twelve near-misses are executed, not argued: they are the
corpus's `false_positive_controls`.

Each has an ungated remedy the deny message names (`>>`, a fresh path, `Edit`,
or `/allow Write <abs path>`), and none of them is editing, appending or
creating — the four things the requirement fixes as ungated. But this is the
single most likely reason the guard gets switched off, and switching it off
protects nothing. **Whoever registers this hook is choosing that trade
deliberately**, and should read section 1 first: what is bought is refusal and
attribution of single-command literal-path replacement, which is the shape both
attributable incidents took.

### The self-disable switch is OPEN and unmitigated

An agent can edit a syntax error into `hooks/pretool-overwrite-guard.py`, and
replacement protection is off for the rest of the session. `Edit` is never
denied by this guard — by explicit, binding requirement — and bootstrap failure
fails open. Nothing here prevents, detects in advance, or reverses that. The
loud warning and the audit row provide detection **after the fact**, not
prevention. This is recorded as an accepted residual risk, not presented as
mitigated.

### Declared uncovered but NOT demonstrated in the corpus

These were ruled out of the verb set by requirement and are **not** exercised by
the suite. They are listed separately so that "declared" is never mistaken for
"tested":

- `tar`-family extraction beyond the single `archive-extract` row (`unzip -o`;
  `unzip` is not installed in this environment).
- `sponge` (moreutils; not installed in this environment).
- `git restore` / `git checkout -- <path>` — routine developer actions and the
  canonical repair verbs, while `git checkout <branch>`, `git reset --hard`,
  `git stash pop`, `git merge` and `git pull` replace worktree files just as
  wholesale and stay unguarded. Covering two verbs of that family buys friction
  on the honest route while the equivalent routes stay open.
- Replacement by non-agent processes (a daemon, a cron job, the user's own
  shell). The enforcement surface is agent-initiated tool calls only.

## 7. Registration requirement

**This artifact is not registered by the lane that built it, and iteration 1
does not register it either.** Adding a hook entry moves counts that two
documents publish and that a gate asserts, so all new registrations land
together as one atomic integration step. The substantive reason to keep
deferring is that section 6 is what a registrar relies on when accepting the
false-positive trade, and iteration 1 has just rewritten section 6 — three of
its entries were wrong or missing.

- **What**: `hooks/pretool-overwrite-guard.py`
- **Where**: `settings.json` **and** `settings.template.json`, under
  `hooks.PreToolUse`, as a new entry with `"matcher": "Bash"`.
- **Ordering**: order-independent for correctness — any hook exiting 2 blocks
  the call. Placing it adjacent to the existing `Bash`-matcher entry for
  `hooks/pretool-bash-safety.sh` is a readability preference only.
- **Until registered**: the guard is inert. It is fully exercised by
  `hooks/tests/test_overwrite_guard.py`, but it blocks nothing in a live
  session.

## 8. Checking a command before you run it

```
python3 hooks/pretool-overwrite-guard.py --explain '<command>' [cwd]
```

Prints each named write target, its mode, its resolved identity and the verdict.
It never audits and never blocks.
