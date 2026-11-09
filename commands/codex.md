---
description: Delegate a task to OpenAI Codex CLI (gpt-5.6-sol, xhigh reasoning) for a second opinion or parallel coding
argument-hint: [prompt or --review or --model <model> <prompt>]
allowed-tools: [Bash, Read, Glob, Grep]
---

# Codex CLI Integration

Run OpenAI Codex CLI to get a second opinion, delegate coding tasks, or perform code review.

## Calling Protocol (MANDATORY — read before invoking)

**Codex serves the user's requirement, not its own audit appetite.** Codex is an audit tool with unbounded findings — for any non-trivial code path it can keep producing "issues" indefinitely. The caller (Claude Code, /dev orchestrator, any subagent) MUST scope and filter, not delegate the verdict.

### Rule 1 — every prompt must declare the requirement

Every codex invocation MUST begin with an explicit statement of what the user is trying to achieve. Codex's job is to surface bugs that **obstruct that requirement** — not to enumerate every theoretical defect in the surrounding code.

Required prompt prelude (place at the top of every codex prompt):

```
USER REQUIREMENT: <one-sentence statement of what the user actually asked for>
SCOPE: find bugs that prevent or threaten this requirement.
OUT OF SCOPE: adjacent improvements, hypothetical attack vectors that fall
outside the requirement's threat model, style preferences, defensive
hardening the user did not request.
```

### Rule 2 — codex finds reasonable bugs, not nitpicks

Codex should report:
- Logic errors that break the stated requirement
- Real defects the code path would hit at runtime
- Security issues directly tied to the user's threat model

Codex should NOT report (and the caller should reject if it does):
- Adjacent threat models the user didn't ask about
- Heuristic-defense gaps that can never be fully closed
- Style / structure preferences
- "What if a malicious actor..." vectors outside the user's stated trust assumptions
- Improvements that expand scope rather than fulfill it

### Rule 3 — caller filters codex output, codex does not set verdict

After codex returns, the caller MUST classify each finding:
- `in_scope_real_bug` → fix in this cycle
- `in_scope_minor` → fix or document, caller's choice
- `out_of_scope` → surface to the user as "codex also found N adjacent issues — separate cycle?" → do NOT auto-fix
- `nitpick` → reject

Codex's finding count is **information**, not a verdict. The verdict is "does the requirement hold?". A cycle can close with codex findings still open if those findings are out_of_scope or nitpicks.

### Rule 4 — when in doubt, the requirement wins

If codex's finding conflicts with the user's stated requirement (e.g. codex demands defense-in-depth the user didn't ask for), the requirement wins. Document the trade-off in the report; do not silently expand scope.

## Instructions

If `$ARGUMENTS` is empty or blank, print this usage guide and stop:

```
Usage: /codex <prompt>              — run codex exec with the given prompt (default: gpt-5.6-sol, reasoning: xhigh)
       /codex --review              — run codex review on the current directory
       /codex --model <model> <prompt> — use a specific model (still xhigh reasoning)

Examples:
  /codex refactor the auth middleware to use async/await
  /codex --review
  /codex --model o3 add input validation to all API endpoints
```

Otherwise, proceed:

### 1. Detect mode

- If `$ARGUMENTS` starts with `--review`, run **review mode**.
- If `$ARGUMENTS` starts with `--model`, extract the model name and the rest as the prompt, then run **exec mode** with `--model <model>`.
- Otherwise, run **exec mode** with the full `$ARGUMENTS` as the prompt (no `--model` flag — uses gpt-5.6-sol default with xhigh reasoning).

### 2. Generate unique output path

Run this first to establish where output will be written. The canonical path is
`<PROJECT_ROOT>/docs/codex/<task_id>/<role>.txt` when `CODEX_OUT_TASK_ID`
and `CODEX_OUT_ROLE` env vars are set, safe, and non-empty. Falls back to
`/var/tmp/codex-outputs/` (disk-backed, 601G) otherwise.

Keep each `[[ ]]` test to a single comparison. Collapsing the `.`/`..` checks
back into one bracket joined by an inner `and` operator makes the bash-safety
scanner split there and read the following quoted variable as a command head,
which it must reject as an unresolved dynamic head when the var is unset.

```bash
_safe_re='^[A-Za-z0-9._-]+$'
if [ -n "${CODEX_OUT_TASK_ID:-}" ] && [ -n "${CODEX_OUT_ROLE:-}" ] \
    && [[ "$CODEX_OUT_TASK_ID" =~ $_safe_re ]] \
    && [[ "$CODEX_OUT_ROLE" =~ $_safe_re ]] \
    && [[ "$CODEX_OUT_TASK_ID" != "." ]] \
    && [[ "$CODEX_OUT_TASK_ID" != ".." ]] \
    && [[ "$CODEX_OUT_ROLE" != "." ]] \
    && [[ "$CODEX_OUT_ROLE" != ".." ]]; then
  _base="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/docs/codex/$CODEX_OUT_TASK_ID"
  mkdir -p "$_base"
  _out="$_base/$CODEX_OUT_ROLE.txt"
else
  if [ -n "${CODEX_OUT_TASK_ID:-}${CODEX_OUT_ROLE:-}" ]; then
    echo "[codex skill] warning: env vars present but unsafe; falling back to /var/tmp/codex-outputs/" >&2
  fi
  mkdir -p /var/tmp/codex-outputs
  _out="/var/tmp/codex-outputs/codex-output-$$-$(date +%s).txt"
fi
: > "$_out"
echo "CODEX_OUT_PATH=$_out"
```

The printed `CODEX_OUT_PATH=` value is the ONE authoritative output path for the
whole run. This is the only step that resolves it, and the only step allowed to
mint a filename.

Steps 3, 4 and 5 run as SEPARATE invocations, and an unexported shell variable
does not survive between them. A flag set here (`_CODEX_USE_CANONICAL=1`) reads
back as unset there, so a later step branching on it always takes the fallback
leg; and a later step that rebuilt the fallback name from `$$` and
`$(date +%s)` would mint a *different* filename than the capture wrote, because
both the process and the clock have moved on. The written path and the read path
then diverge silently and the reader reports a stale, empty, or missing file as a
real consultation. Carry the path forward as a literal instead:

- **Canonical leg** (path under `docs/codex/`) — reuse the path expression shown
  in Steps 3 and 4 verbatim. It uses `CLAUDE_PROJECT_DIR` when set, otherwise
  the Git root of the current project. Keep that project working directory
  unchanged between steps; if it changes, paste the exact `CODEX_OUT_PATH`
  instead of resolving the root again. `CODEX_OUT_TASK_ID` and `CODEX_OUT_ROLE`
  remain exported.
- **Fallback leg** (path under `/var/tmp/codex-outputs/`) — paste the exact
  `<pid>-<epoch>` suffix printed above into the `<step2-suffix>` placeholder in
  Steps 3 and 4. Never recompute `$$` or `$(date +%s)` there.

This binds every later use of the path without exception: the foreground `tee`
target, a detached run's redirect, and the Read step. Which leg applies is
decided by the prefix Step 2 actually printed, never by a shell flag.

The `: > "$_out"` truncation is part of the same guarantee. A canonical path is
keyed only by task and role, so a previous run may already have filled it;
emptying it here means a failed consultation leaves an empty file the reader can
recognize as "no output" rather than silently re-reporting the older run.

**Isolation (host policy — do NOT call bare `codex` here).** Steps 3 and 4 invoke codex through
the codex-isolation wrapper at the literal path `/root/bin/codex-iso` (a fail-closed wrapper that
forces an isolated `CODEX_HOME` so codex rollouts never land in a daemon-watched default `CODEX_HOME`
that the Happy daemon would otherwise claim and surface as "gpt" sessions). The wrapper is the
isolation entry point for `/codex`; do not fall back to bare `codex`, which loses the isolation
guarantee — if the wrapper is absent the invocation simply fails at the call site, the baseline
behavior.

Write that path as a literal at every call site. Do NOT reintroduce an env-var
indirection such as `CODEX_ISO_BIN` and then use it in command-head position:
the bash-safety scanner must prove every execution boundary inert, and a
variable in command-head position is an unresolvable dynamic head that it
rejects (`UNRESOLVED dynamic_command_head`). The wrapper's own documented
calling convention is likewise the literal path.

### 3. Review mode

Run the leg matching the `CODEX_OUT_PATH` Step 2 printed.

**Canonical leg** — Step 2 printed a path under `docs/codex/`:
```bash
/root/bin/codex-iso review -c 'model="gpt-5.6-sol"' -c 'model_reasoning_effort="xhigh"' < /dev/null 2>&1 | tee "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/docs/codex/$CODEX_OUT_TASK_ID/$CODEX_OUT_ROLE.txt"
```

**Fallback leg** — Step 2 printed a path under `/var/tmp/codex-outputs/`.
Substitute the exact suffix from that line for `<step2-suffix>`:
```bash
/root/bin/codex-iso review -c 'model="gpt-5.6-sol"' -c 'model_reasoning_effort="xhigh"' < /dev/null 2>&1 | tee "/var/tmp/codex-outputs/codex-output-<step2-suffix>.txt"
```

**Timeout.** The Bash tool hard-caps `timeout` at 600000 ms (10 minutes); the
`codex-iso` wrapper imposes none of its own. A foreground invocation therefore
cannot run longer than 10 minutes, and a large investigation will be killed
mid-synthesis with exit 143 after having done the work but before emitting its
verdict — the dominant codex failure mode observed in practice.

- **Short consultations (default):** run in the foreground with `timeout: 600000`.
- **Long investigations (up to 30 minutes or more):** do NOT raise the Bash
  timeout — it will be rejected. Instead detach the run so it survives the tool
  call, and poll the output file on later turns:

  ```bash
  # Bind OUT to the exact CODEX_OUT_PATH Step 2 printed — keep ONE of these:
  OUT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/docs/codex/$CODEX_OUT_TASK_ID/$CODEX_OUT_ROLE.txt"
  #OUT="/var/tmp/codex-outputs/codex-output-<step2-suffix>.txt"
  setsid nohup /root/bin/codex-iso exec -c 'model="gpt-5.6-sol"' \
    -c 'model_reasoning_effort="xhigh"' "$PROMPT" </dev/null >"$OUT" 2>&1 &
  echo "detached pid=$! out=$OUT"
  ```

  The Bash call returns immediately. `OUT` is bound only inside the invocation
  that launched the run, so when polling from a later invocation paste the same
  `CODEX_OUT_PATH` value as a literal rather than referencing `$OUT`. Poll with a
  short foreground call that checks whether the process is still alive and tails
  that path. Treat the run as
  `failed_timeout` only after the process has actually exited without a verdict
  — not merely because one poll found it unfinished.

Then Read the output file with the Read tool.

### 4. Exec mode

Run the leg matching the `CODEX_OUT_PATH` Step 2 printed. On the fallback leg,
substitute the exact suffix from that line for `<step2-suffix>`.

**Without --model (default gpt-5.6-sol) — canonical leg:**
```bash
/root/bin/codex-iso exec -c 'model="gpt-5.6-sol"' -c 'model_reasoning_effort="xhigh"' "$PROMPT" < /dev/null 2>&1 | tee "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/docs/codex/$CODEX_OUT_TASK_ID/$CODEX_OUT_ROLE.txt"
```

**Without --model — fallback leg:**
```bash
/root/bin/codex-iso exec -c 'model="gpt-5.6-sol"' -c 'model_reasoning_effort="xhigh"' "$PROMPT" < /dev/null 2>&1 | tee "/var/tmp/codex-outputs/codex-output-<step2-suffix>.txt"
```

**With --model (user-specified model, still xhigh reasoning) — canonical leg:**
```bash
/root/bin/codex-iso exec -c 'model="<model>"' -c 'model_reasoning_effort="xhigh"' "$PROMPT" < /dev/null 2>&1 | tee "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/docs/codex/$CODEX_OUT_TASK_ID/$CODEX_OUT_ROLE.txt"
```

**With --model — fallback leg:**
```bash
/root/bin/codex-iso exec -c 'model="<model>"' -c 'model_reasoning_effort="xhigh"' "$PROMPT" < /dev/null 2>&1 | tee "/var/tmp/codex-outputs/codex-output-<step2-suffix>.txt"
```

**Timeout.** The Bash tool hard-caps `timeout` at 600000 ms (10 minutes); the
`codex-iso` wrapper imposes none of its own. A foreground invocation therefore
cannot run longer than 10 minutes, and a large investigation will be killed
mid-synthesis with exit 143 after having done the work but before emitting its
verdict — the dominant codex failure mode observed in practice.

- **Short consultations (default):** run in the foreground with `timeout: 600000`.
- **Long investigations (up to 30 minutes or more):** do NOT raise the Bash
  timeout — it will be rejected. Instead detach the run so it survives the tool
  call, and poll the output file on later turns:

  ```bash
  # Bind OUT to the exact CODEX_OUT_PATH Step 2 printed — keep ONE of these:
  OUT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/docs/codex/$CODEX_OUT_TASK_ID/$CODEX_OUT_ROLE.txt"
  #OUT="/var/tmp/codex-outputs/codex-output-<step2-suffix>.txt"
  setsid nohup /root/bin/codex-iso exec -c 'model="gpt-5.6-sol"' \
    -c 'model_reasoning_effort="xhigh"' "$PROMPT" </dev/null >"$OUT" 2>&1 &
  echo "detached pid=$! out=$OUT"
  ```

  The Bash call returns immediately. `OUT` is bound only inside the invocation
  that launched the run, so when polling from a later invocation paste the same
  `CODEX_OUT_PATH` value as a literal rather than referencing `$OUT`. Poll with a
  short foreground call that checks whether the process is still alive and tails
  that path. Treat the run as
  `failed_timeout` only after the process has actually exited without a verdict
  — not merely because one poll found it unfinished.

Then Read the output file with the Read tool.

### 5. Present results

Read exactly the `CODEX_OUT_PATH` value Step 2 printed, with the Read tool — not
a path reconstructed here. Show the complete Codex output to the user. If Codex
made file changes, summarize what was modified. If it failed, show the error and
suggest corrections.

If that file is missing or empty, the consultation produced no output. Report
that as the real failure; never substitute another file's contents, an earlier
run's output, or invented findings for a consultation that did not happen.
