---
description: Update an existing spec, continue unfinished development, or write a temp session note
argument-hint: "[--update|--continue|--temp] [--spec <path>|--path <path>] [--codex] [--] [material]"
disable-model-invocation: true
---

# /spec-update — Update, Continue, or Temp Note

Use exactly one of three purposes:

1. `--update` enriches an authorized existing spec. It does not create a cycle,
   add a continuation marker, or hand off to `/dev`.
2. `--continue` records unfinished development for a later spec-backed run. No
   purpose flag is the compatibility form of `--continue`.
3. `--temp` creates one compact non-spec session note.

The read-only contract at `scripts/spec-update-contract.py` is the authority for
argument parsing, target authorization, pre-state inventory, post-state
verification, and final response bytes. Fail closed on every contract error.

## Argument grammar

Pass the exact `$ARGUMENTS` string to the planner. It tokenizes with Python
`shlex.split(..., posix=True)`. Before the first literal `--`, the complete
grammar is:

```text
purpose := --update | --continue | --temp
value   := --spec PATH | --path PATH
review  := --codex
end     := --
```

- At most one purpose is allowed. With none, select `continue`.
- `--spec`, `--path`, and `--codex` may each appear at most once.
- Value options use separate tokens only; `--spec=x` and `--path=x` are invalid.
- The first `--` ends option parsing. Every later token, including flag-looking
  tokens and another `--`, is literal material.
- Any unrecognized pre-delimiter token beginning `-`, malformed quoting,
  missing/empty value, duplicate, or incompatible combination is invalid.
- Material tokens retain decoded order and join with one U+0020.

Mode compatibility is closed:

| Mode | `--spec` | `--path` | `--codex` | Material |
|---|---|---|---|---|
| update | optional only when an exact bound active task authorizes the target | forbidden | optional | required |
| continue/default | optional | forbidden | optional | optional for an existing target; required for creation |
| temp | forbidden | optional | forbidden | required |

Every invalid request exits 2 before writes. Its authorized `write_set` is empty.

## Pre-write plan

Before creating or modifying any file, run:

```text
python3 <project-root>/scripts/spec-update-contract.py plan
```

Supply one JSON object on stdin:

- `project_dir`: explicit absolute project root. Do not infer it from cwd, an
  environment variable, script location, mtime, or a newest-file search.
- `raw_arguments`: exact `$ARGUMENTS` bytes decoded as the command string.
- `active_task`: for repository modes without `--spec`, either
  `{"state":"bound","task_id":"<exact-id>"}` or `{"state":"none"}`.
  With explicit `--spec`, it is optional; a supplied bound task must agree.
- `actor_scratch_dir`: explicit absolute trusted actor scratch directory for
  temp mode.

The planner must exit 0 and return `status=pass` before any write. Preserve its
complete JSON object and digest for verification. It is read-only and exposes no
checkpoint mutation operation.

### Target authorization

For repository modes:

- The canonical spec root is the real, non-symlink directory
  `<project-root>/docs/dev/specs`.
- An existing target is a readable, non-symlink regular direct child named
  `spec-*.md`, where the middle is nonempty but is not timestamp-restricted.
- An explicit target must also pass `resolve-spec-artifacts.py` with the exact
  canonical target and explicit project root. Present-invalid or ambiguous split
  evidence is a hard rejection.
- A bound active task is resolved only through
  `resolve-dev-artifact-chain.py --task-id <id> --project-dir <root>`. Read the
  declared singular context or every declared fan-out `lanes[].context`; never
  glob, infer, or fabricate a parent context. Shape, lane, context identity, and
  schema errors reject. Every context must name one identical canonical
  `parent_spec` with one current SHA-256.
- If explicit and active evidence are both present, path and SHA-256 must agree.
- Update never creates. Continue may create only with explicit
  `active_task.state=none`, no `--spec`, and nonempty material. Missing, failed,
  or ambiguous task evidence never falls through to creation.

Reject nested paths, `..`, symlink components/files, directories, devices,
`README.md`, `INDEX.md`, and every non-`spec-*.md` name.

For temp mode, confine an explicit `--path` beneath the project root or actor
scratch directory through non-symlink parents, require an absent `.md` target,
and reject any canonical/same-file alias of a spec. Without `--path`, use the
planner's `temp_parent` and perform one exclusive `update-*.md` allocation. Temp
mode never enters spec resolution or split/checkpoint work. Post-write
verification uses that same confinement union for an explicit target; only the
allocator-only form is restricted to the actor scratch root. Audit every
existing lexical parent component with `lstat` before `resolve`; canonicalization
must never erase an intermediate directory symlink from the authorization proof.
For both explicit and allocated targets, post-write verification must preserve
the exact planned spec inventory and reject a target that is `samefile` with any
spec. A spec-named symlink inventory entry binds its raw link bytes, link
identity, valid/broken state, and, when valid, the resolved regular-file path,
identity, size, and SHA-256. Relative/absolute spelling changes, retargeting,
referent byte/type changes, and validity changes are inventory drift even when
they resolve to an otherwise equivalent referent. Read, hash, type, or observed
race uncertainty fails closed. Inspect referent type before acquisition and use
only a nonblocking read-only acquisition, then require the opened object to be
the same regular file observed by the preflight. FIFO/socket/device/directory,
broken, error, or raced states must return a contract rejection rather than
wait for I/O. Any inventory drift or hardlink alias rejects before target
hashing or a success response.

## Mode effects

### Update

Append only the supplied enrichment to the authorized existing monolith. Do not:

- create another spec;
- add a `### Cycle N` heading;
- add a `spec-continuation-of` marker;
- harvest unrelated artifacts; or
- include a `/dev` handoff in metadata or response text.

The final response is one `Updated spec:` line produced by the renderer.

## Continuation-spec mode

For an existing target, append; never overwrite earlier content. Determine the
next cycle number as the maximum existing `### Cycle N` across Sections 1–8 plus
one, or Cycle 1 when none exists. Add the exact
`<!-- spec-continuation-of: <task-id> -->` marker before the first new heading
only when that exact task/spec marker is absent. Never write a placeholder.

When a bound `/dev` task exists, consume the same validated resolver result used
for target authorization from
`scripts/resolve-dev-artifact-chain.py --task-id <id> --project-dir <root>`.
Gather source references only from `artifact_paths`, `report_paths`, `qa_inputs`, and
`lanes[]`. In singular mode this is the declared parent chain. In fan-out mode it
is every lane ticket/context/dev/QA plus the canonical/completion artifacts and
only optional parent artifacts that actually exist. A fan-out continuation does
not need, and this command must not create, a parent context. Do not replace the
lane matrix with a singular-parent assumption or fabricate missing parent artifacts.

Record concise references rather than raw diffs or copied reports:

- Section 2: attempted work and why it did not finish.
- Section 3: changed-file and artifact references.
- Section 4: measured state and latest QA/close result.
- Section 5: only a new or materially refined remaining criterion.
- Section 6: the measured gap to done.
- Section 7: the concrete next plan.
- Section 8: traps, stale assumptions, and warnings.

Leave Section 9 references intact. For a newly created continuation, retain the
original user goal when known and the remaining acceptance criteria. The final
response contains the continuation path and exactly one `/dev --spec` handoff.

## Temp-note mode

Create one compact note with the following shape:

```markdown
# Update — <short focus>

Generated: <ISO-8601>
Next focus: <what the next session should do>
Current phase: <spec|dev|close|commit|push|ad hoc>
Task/spec id: <id or "unknown">

## Resume prompt
<3-8 sentences>

## Artifact map
- Spec/ticket: <path or URL>
- Context/dev/QA/close reports: <paths>
- Commit/branch/remote: <known values>

## Decisions not captured elsewhere
- <only uncaptured decisions>

## Blockers / risks
- <known blocker or "none known">

## Next actions
1. <exact next action>
2. <verification or fallback>

## Suggested skills
- <skill/command> — <reason>
```

Temp writes no spec, view, checkpoint, manifest, or continuation marker.

## Codex review propagation

`--codex` is a review modifier, never material or a purpose. When the valid plan
has `codex_required=true`, include the literal line `codex_required: true` in
every enrichment/spec-split initial dispatch and every split-QA initial or retry
dispatch. Without it, omit the line and record `not_requested`. Temp plus
`--codex` is invalid.

## Canonical split and checkpoint lifecycle

After the authorized repository monolith mutation, use only the existing spec
provider and `scripts/spec-check.py` lifecycle. The contract script never writes
`cp-state-*.json`.

1. **Precheck:** retain the plan's complete spec/checkpoint inventory. Any
   corrupt, symlinked, invalid-generation, or active primary/numbered slot
   blocks before the monolith write. Normalize checkpoint slots by
   `(role, numeric instance)` and reject aliases such as `-2.json` plus
   `-02.json`, or a lone noncanonical numeric filename, before mutation.
2. **Split:** run the existing spec provider's Phase 0/1 for the authorized
   monolith, then recheck the exact checkpoint inventory before each role.
3. **Check in:** when a role has no primary or numbered slot, use ordinary
   primary check-in and require generation 1. When a terminal primary exists,
   use its `--bump-generation` primary path and require `g+1`. Numbered without
   primary, a changed pre-state, or an emitted numbered/wrong path is failure.
4. **Populate/status:** only the checked-in owner may populate 1–10 fresh,
   verb-first pending checkpoints through the existing locked provider stanza.
   Run real `spec-check.py status` and capture generation and population digest.
5. **Check out:** use the same role and agent id. Require a terminal canonical
   primary with `is_running=false`, `agent_id=null`, pending checkpoints, and the
   expected generation. Do not modify numbered or never-selected history.
6. **Bind:** after all selected roles are terminal, atomically commit the
   `checkpoint_binding.v1` manifest data and only then the split-complete marker.
   Bind post-monolith SHA, lifecycle receipt digest, selected primaries, and
   byte-identical historical slots. Each selected-primary binding contains the
   closed per-round object and its digest, including branch, pre-state and
   generation, check-in/argv kind, emitted path, agent id, before/after SHA,
   population digest, status/check-out exits, terminal SHA, and split round;
   bind the exact maximum as `final_round`. It must be a JSON integer with
   booleans excluded, not merely a value that compares equal to the maximum.
   Missing, extra, mistyped, or independently changed round fields fail even when
   the enclosing receipt digest is recomputed.
7. **Verify:** run the read-only verifier below. No failure branch may render a
   success response. Cleanup of an exactly owned running slot uses check-out
   only; never unlock, directly edit, delete, or fabricate checkpoint state.

## Post-write verification and response

Pass the preserved plan and the provider's `split_lifecycle_receipt.v1` as one
JSON object to:

```text
python3 <project-root>/scripts/spec-update-contract.py verify --emit-response
```

For an allocated temp note, also pass `allocated_target`. Verification must
prove the exact authorized post-state, fresh resolver output, manifest binding,
creation `null→1` or refresh `g→g+1` arithmetic, terminal selected primaries,
and unchanged historical slots. Temp verification must additionally prove the
exact planned spec inventory is unchanged and the note is not a same-file alias
of any spec, including exact symlink link and referent evidence. The verifier
internally calls the same closed renderer used by `render-response`.

On success, renderer stdout is the whole final command response. Append nothing:

```text
update:   Updated spec: <canonical-target>
continue: Continuation spec: <canonical-target>
          Next: /dev --spec <canonical-target>
temp:     Temp note: <canonical-target>
```

The canonical response object fixes mode, plan digest, status, handoff flag,
next command, line count/order/content, and rendered bytes. Reject embedded CR or
LF, any extra/different line, or any update response containing a boundary-safe
`/dev` token. Ordinary `docs/dev/specs/...` and `/dev/shm/...` paths are not
slash-command tokens.

## Universal limits

- Reference existing artifacts by path, URL, or SHA; do not duplicate raw
  diffs, full logs, reports, secrets, or transcripts.
- Do not touch unrelated specs, repository files, or checkpoint history.
- Never show a success response until planning, provider work, binding, and
  read-only verification all succeed.
