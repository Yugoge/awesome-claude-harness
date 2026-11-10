# Extending the harness

How to add a command, an agent or a hook so that it follows the harness's conventions.

[Back to the README](../README.md)

## Extending it

A `PostToolUse` doc-sync hook keeps the marked sections of the INDEX and README files that already exist in sync the moment you save (it creates none), so a new agent appears in `agents/INDEX.md` and `agents/README.md` without manual bookkeeping. Commands have no index files. The README's command and agent tables are generated from each file's own frontmatter by `scripts/generate-hero-status.py`: its `summary:` (one short sentence, never cut: `scripts/readme_facts.py` sets the length limit and the internal names, such as an optional module's own name or a model id, that it may not hold) and, for a command, its `group:` (Spec, Develop, Ship, Quality or Control); a command of an optional module also carries `module: <name>` and is left off the front page. A missing or broken summary or group fails `scripts/verify-claims.sh`. Mirror existing conventions: prompts state what is **required** and what is **forbidden**, and a hook that guards anything dangerous should *fail closed* (block on doubt) and leave its evidence behind.

| Extension type | File location | Required fields | Validation |
|---|---|---|---|
| Slash command | `commands/<name>.md` | `description:`, `summary:`, `group:` in YAML frontmatter | Malformed frontmatter hides the command; a missing summary or group fails the README check |
| Subagent | `agents/<name>.md` | `name:`, `description:`, `summary:`, `tools:` in YAML frontmatter | Incorrect `tools:` silently limits toolchain; a missing summary fails the README check |
| Hook | `hooks/<name>.{sh,py}` + `settings.json` wiring | Executable bit set; correct lifecycle event in `settings.json` | exit 2 = block; exit 0 = allow |
| Post-hook verification | Run `examples/guard-demo/run-demo.sh` after any hook changes | Behavioral verification of block-then-grant-then-complete | Standalone; no Claude Code required |

<details>
<summary>Example: slash command</summary>

```bash
cat > ~/.claude/commands/my-command.md << 'EOF'
---
description: My custom command
summary: "What the command does, in one sentence for the README's command table."
group: Develop
---

Command instructions here.
EOF
```

</details>

<details>
<summary>Example: subagent</summary>

```bash
cat > ~/.claude/agents/my-agent.md << 'EOF'
---
name: my-agent
description: When the orchestrator should dispatch this agent
summary: "What the agent does, in one sentence for the README's cast of agents."
tools: Read, Write, Bash
---

Agent system prompt here.
EOF
```

</details>

<details>
<summary>Example: hook + test</summary>

```bash
cat > ~/.claude/hooks/my-hook.sh << 'EOF'
#!/bin/bash
# exit 2 to block the tool call.
EOF
chmod +x ~/.claude/hooks/my-hook.sh
```

Wire it in `settings.json` under the lifecycle event (`PreToolUse`, `PostToolUse`, `Stop`, …), through the harness-home channel like every other entry — `"command": "bash \"${CLAUDE_HOME:-$HOME/.claude}/hooks/my-hook.sh\""` — so it resolves in any clone (`scripts/doctor` fails on a hook path that does not). Then test:

```bash
# Run the full hook test suite:
scripts/test

# Or run just the hooks/ tests:
python3 -m pytest hooks/tests -q
```

Write test files in `hooks/tests/test_my_hook.py` — use repo-relative paths and `pytest`'s `tmp_path` fixture; assert exit 0 (allow) and exit 2 (block) behavior explicitly.

</details>
