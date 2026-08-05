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
  shared matcher.** An agent cannot mint its own grant.
- Consumed on any terminal result by the existing
  `hooks/posttool-allowlist-consume.py`.
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
| `check-use-race` | The decision is pre-execution; a path absent at check time can exist by open time. No pre-execution check closes this. |
| `concurrent-grant-reuse` | Consumption is PostToolUse, so two calls issued before the first terminal result both observe one grant. Single-use holds for **serial** use only. |
| `semantic-lexer-corruption` | A lexer that imports cleanly but returns incomplete targets degrades this guard **silently**, without tripping tool-policy's fail-closed bootstrap. |
| `redirect-ampersand` | `&>` shares its prefix with fd duplication (`2>&1`), which must never be treated as a write. The verb set was fixed by requirement, so this is declared rather than silently absent. |
| `recursive-copy` | `cp -r` replaces children beneath a destination directory, invisibly to a command-text lexer. |
| `rsync-dest` | Same undecidable destination set as `cp -r`. |
| `archive-extract` | Member enumeration needs the archive read at preflight — impossible for `curl … \| tar -x`. |
| `gzip-force` | The write target is derived from the operand rather than named by it. |
| `symlink-force` | `ln -sf`'s one-argument form targets `./<basename>`, so target derivation is ambiguous across the verb's forms. |

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

**This artifact is not registered by the lane that built it.** Adding a hook
entry moves counts that two documents publish and that a gate asserts, so all
new registrations land together as one atomic integration step.

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
