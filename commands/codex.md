---
description: Delegate a task to OpenAI Codex CLI (gpt-5.6-sol, xhigh reasoning) for a second opinion or parallel coding
argument-hint: [prompt or --review or --model <model> <prompt>]
allowed-tools: [Bash, Read, Glob, Grep]
summary: "Ask OpenAI Codex for a second opinion, a code review or a delegated coding task, through an isolated wrapper."
group: Control
---

# Codex CLI Integration

Run OpenAI Codex CLI for a second opinion, a delegated coding task or a code review.
Codex calls follow `templates/prompt-includes/codex-consultation.md`.

**Isolation (host policy).** Every call goes through the codex-isolation wrapper named by the
`CODEX_ISO_BIN` environment variable (default `$HOME/bin/codex-iso`), a fail-closed wrapper that forces an
isolated `CODEX_HOME`, so codex rollouts never land in the default `CODEX_HOME` that the Happy daemon
watches and would surface as "gpt" sessions. Never call bare `codex` and never fall back to it: with no
usable wrapper the call fails (exit 127) and you report that.

## Instructions

If `$ARGUMENTS` is empty or blank, print this usage and stop:

```
Usage: /codex <prompt>                    run codex exec (gpt-5.6-sol, reasoning: xhigh)
       /codex --review                    run codex review on the current directory
       /codex --model <model> <prompt>    use a specific model (still xhigh reasoning)
```

### 1. Detect mode

- `$ARGUMENTS` starts with `--review`: **review**.
- It starts with `--model`: **exec** with that model, and the rest as the prompt.
- Otherwise: **exec** with the whole of `$ARGUMENTS` as the prompt (default model).

### 2. Run

One Bash call runs `scripts/steps/codex-run.py`: it calls the wrapper, tees the output into a file and
prints `out=<path>` first (`detach` also prints `pid=<pid>`). The file is
`docs/codex/<task_id>/<role>.txt` when `CODEX_OUT_TASK_ID` and `CODEX_OUT_ROLE` are set to safe names,
else a new file under `/var/tmp/codex-outputs/`. The prompt goes in through a quoted heredoc, verbatim.

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/steps/codex-run.py" review
```

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/steps/codex-run.py" exec [--model <model>] <<'CODEX_PROMPT'
<the prompt>
CODEX_PROMPT
```

The Bash tool caps `timeout` at 600000 ms and the wrapper sets none, so a longer foreground run is killed
(exit 143) after the work but before the verdict, the usual codex failure. A short consultation runs in the
foreground with `timeout: 600000`. A long investigation uses `detach` in place of `exec`, with the same
arguments: it returns at once, and later turns poll with a short foreground call that checks the pid is
alive and tails the output file. A run is `failed_timeout` only after its process has exited without a
verdict, not because one poll found it unfinished.

### 3. Present results

Read the file at `out=` with the Read tool and show the complete Codex output. If Codex changed files,
summarize what changed. If it failed, show the error and suggest corrections.
