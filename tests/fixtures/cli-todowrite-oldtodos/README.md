# cli-todowrite-oldtodos

`stream-2.1.326.jsonl` is a **real recording**, not hand-written: the unedited
`--output-format stream-json --verbose` stdout of Claude Code CLI **2.1.326**,
recorded 2026-11-17, apart from the redactions listed below. The model was asked
for two sequential TodoWrite calls: first a list whose items are all
`completed`, then a list with one `pending` item. Each call's `tool_use_result`
shows what the CLI stored:

- call 1: `oldTodos: []`, `newTodos`: the two completed items (the input);
- call 2: `oldTodos: []`, `newTodos`: the pending item (the input).

Call 2's `oldTodos` is `[]`, not call 1's list: when every item is completed the
CLI stores `[]`, while that call's own `newTodos` is still its input.
`tests/replay/test_todowrite_recording.py` holds the replay's TodoWrite
simulation (`tests/replay/replay.py` `_default_perform`) to this sequence.

## Redactions

Plain string substitutions on the raw output, then the recorder's account rule
(`bash scripts/cli-fixture-record.sh --redact stream-2.1.326.jsonl`); nothing
else was changed.

| Placeholder | Replaced |
|---|---|
| `<HOME>` | the throwaway HOME's absolute path |
| `<WORKDIR>` | the temporary working directory's absolute path |
| `<WORKDIR-SLUG>` | that path as the CLI's project-dir slug (in `memory_paths`) |
| `<SOCKET>` | the absolute path of the CLI's messaging socket |
| `<MODEL>` | the model ID (every occurrence, including `modelUsage` keys) |
| `0` | every token, request and cost count (`usage`, `modelUsage`, `total_cost_usd`, `costUSD`) |
| `0`, `false`, `<redacted>` | every value of the `rate_limit_event` (utilization, thresholds, reset time, status, window, overage fields) |

Session, message, request and tool-use ids are kept.

## Recording procedure

Run from an empty temporary directory, with a throwaway HOME, never the real
`~/.claude`. `CLAUDE_CODE_ENABLE_TASKS=false` is needed: 2.1.326 offers the
Task tools instead of TodoWrite by default. Authentication comes from the
environment's API proxy, so only `ANTHROPIC_BASE_URL`, the proxy variables and
the proxy's CA bundle are passed through (no credentials on the command line):

```
H=$(mktemp -d); W=$(mktemp -d); cd "$W"
env -i PATH="$PATH" HOME="$H" ANTHROPIC_BASE_URL="$ANTHROPIC_BASE_URL" \
  HTTPS_PROXY="$HTTPS_PROXY" https_proxy="$https_proxy" NO_PROXY="$NO_PROXY" no_proxy="$no_proxy" \
  NODE_EXTRA_CA_CERTS=<proxy CA bundle> CLAUDE_CODE_ENABLE_TASKS=false \
  claude -p 'Make exactly two TodoWrite tool calls, sequentially (wait for the first result before the second), and nothing else. Call 1: todos = [{"content":"Alpha","status":"completed","activeForm":"Doing Alpha"},{"content":"Beta","status":"completed","activeForm":"Doing Beta"}]. Call 2: todos = [{"content":"Gamma","status":"pending","activeForm":"Doing Gamma"}]. Then reply DONE.' \
  --output-format stream-json --verbose --tools TodoWrite --allowedTools TodoWrite \
  < /dev/null > stream.jsonl
```

Then apply the string substitutions above, run
`bash scripts/cli-fixture-record.sh --redact stream.jsonl` for the account rule,
and confirm with `claude --version` which CLI version recorded it; name the file
after that version.
