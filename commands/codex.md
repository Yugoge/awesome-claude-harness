---
description: Delegate a task to OpenAI Codex CLI (gpt-5.5, xhigh reasoning) for a second opinion or parallel coding
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
Usage: /codex <prompt>              — run codex exec with the given prompt (default: gpt-5.5, reasoning: xhigh)
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
- Otherwise, run **exec mode** with the full `$ARGUMENTS` as the prompt (no `--model` flag — uses gpt-5.5 default with xhigh reasoning).

### 2. Generate unique output path

Run this first to establish where output will be written. The canonical path is
`$CLAUDE_PROJECT_DIR/docs/codex/<task_id>/<role>.txt` when `CODEX_OUT_TASK_ID`
and `CODEX_OUT_ROLE` env vars are set, safe, and non-empty. Falls back to
`/var/tmp/codex-outputs/` (disk-backed, 601G) otherwise.

```bash
_safe_re='^[A-Za-z0-9._-]+$'
if [ -n "${CODEX_OUT_TASK_ID:-}" ] && [ -n "${CODEX_OUT_ROLE:-}" ] \
    && [[ "$CODEX_OUT_TASK_ID" =~ $_safe_re ]] \
    && [[ "$CODEX_OUT_ROLE" =~ $_safe_re ]] \
    && [[ "$CODEX_OUT_TASK_ID" != "." && "$CODEX_OUT_TASK_ID" != ".." ]] \
    && [[ "$CODEX_OUT_ROLE" != "." && "$CODEX_OUT_ROLE" != ".." ]]; then
  _CODEX_USE_CANONICAL=1
  _base="$CLAUDE_PROJECT_DIR/docs/codex/$CODEX_OUT_TASK_ID"
  mkdir -p "$_base"
  echo "$_base/$CODEX_OUT_ROLE.txt"
else
  _CODEX_USE_CANONICAL=0
  if [ -n "${CODEX_OUT_TASK_ID:-}${CODEX_OUT_ROLE:-}" ]; then
    echo "[codex skill] warning: env vars present but unsafe; falling back to /var/tmp/codex-outputs/" >&2
  fi
  mkdir -p /var/tmp/codex-outputs
  echo "/var/tmp/codex-outputs/codex-output-$$-$(date +%s).txt"
fi
```

Capture the printed path as `$CODEX_OUT` if needed for the Read step, but do
NOT pass `$CODEX_OUT` as the tee argument. Steps 3 and 4 branch directly.

**Isolation (host policy — do NOT call bare `codex` here).** Steps 3 and 4 invoke codex through
`/root/bin/codex-iso`, a fail-closed wrapper that forces an isolated `CODEX_HOME=/root/.codex-cli`
so codex rollouts never land in the daemon-watched `/root/.codex` (which the default Happy daemon
would otherwise claim and surface as "gpt" sessions on the root account). The wrapper refuses to run
if `CODEX_HOME` resolves into `/root/.codex`. This keeps codex audits from polluting the root account.

### 3. Review mode

```bash
if [ "${_CODEX_USE_CANONICAL:-0}" = "1" ]; then
  /root/bin/codex-iso review -c 'model="gpt-5.5"' -c 'reasoning_effort="xhigh"' < /dev/null 2>&1 | tee "$CLAUDE_PROJECT_DIR/docs/codex/$CODEX_OUT_TASK_ID/$CODEX_OUT_ROLE.txt"
else
  /root/bin/codex-iso review -c 'model="gpt-5.5"' -c 'reasoning_effort="xhigh"' < /dev/null 2>&1 | tee "/var/tmp/codex-outputs/codex-output-$$-$(date +%s).txt"
fi
```

Use 10 minute Bash timeout. Then Read the output file with the Read tool.

### 4. Exec mode

**Without --model (default gpt-5.5):**
```bash
if [ "${_CODEX_USE_CANONICAL:-0}" = "1" ]; then
  /root/bin/codex-iso exec -c 'model="gpt-5.5"' -c 'reasoning_effort="xhigh"' "$PROMPT" < /dev/null 2>&1 | tee "$CLAUDE_PROJECT_DIR/docs/codex/$CODEX_OUT_TASK_ID/$CODEX_OUT_ROLE.txt"
else
  /root/bin/codex-iso exec -c 'model="gpt-5.5"' -c 'reasoning_effort="xhigh"' "$PROMPT" < /dev/null 2>&1 | tee "/var/tmp/codex-outputs/codex-output-$$-$(date +%s).txt"
fi
```

**With --model (user-specified model, still xhigh reasoning):**
```bash
if [ "${_CODEX_USE_CANONICAL:-0}" = "1" ]; then
  /root/bin/codex-iso exec -c 'model="<model>"' -c 'reasoning_effort="xhigh"' "$PROMPT" < /dev/null 2>&1 | tee "$CLAUDE_PROJECT_DIR/docs/codex/$CODEX_OUT_TASK_ID/$CODEX_OUT_ROLE.txt"
else
  /root/bin/codex-iso exec -c 'model="<model>"' -c 'reasoning_effort="xhigh"' "$PROMPT" < /dev/null 2>&1 | tee "/var/tmp/codex-outputs/codex-output-$$-$(date +%s).txt"
fi
```

Use 10 minute Bash timeout. Then Read the output file with the Read tool.

### 5. Present results

Read the output file (path printed in Step 2) with the Read tool. Show the complete Codex output to the user. If Codex made file changes, summarize what was modified. If it failed, show the error and suggest corrections.
