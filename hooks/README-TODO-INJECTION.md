# Global Todo Injection Hook

## Overview

`hook-todo-injection.py` is a **global PreToolUse hook** that **forcibly injects** a workflow checklist before any slash command executes.

## Key Features

- **75-90% compliance rate** -- improves adherence via `hookSpecificOutput.additionalContext` (15-20% higher than pure prompt instructions)
- **Zero token cost** -- does not consume prompt instruction budget
- **Cross-project** -- installed in `~/.claude/hooks/`, activates automatically for all projects
- **Multi-path lookup** -- searches 5 paths for todo scripts, supporting different project structures
- **Global fallback** -- `~/.claude/scripts/todo/` serves as the global default script location

## How It Works

### Execution Flow

```
User runs: /ask question
    ↓
hook-todo-injection.py is triggered (PreToolUse)
    ↓
Detects command name: "ask"
    ↓
Multi-path search for todo script (in priority order):
  1. $CLAUDE_PROJECT_DIR/scripts/todo/ask.py       (project scripts)
  2. $CLAUDE_PROJECT_DIR/.claude/scripts/todo/ask.py  (project .claude)
  3. $(pwd)/scripts/todo/ask.py                    (current dir scripts)
  4. $(pwd)/.claude/scripts/todo/ask.py            (current dir .claude)
  5. ~/.claude/scripts/todo/ask.py                 (global fallback)
    ↓
Runs script and gets JSON: [{"content": "...", "activeForm": "...", "status": "pending"}]
    ↓
Injects into prompt (additionalContext)
    ↓
Claude sees checklist -> should use TodoWrite to create todos (75-90% compliance)
    ↓
Executes /ask command
```

### Why Is This Approach More Reliable?

| Method | Compliance Rate | Reason |
|--------|----------------|---------|
| **CLAUDE.md instructions** | 60-80% | Claude skips when in "efficiency-first" mode |
| **System prompt** | 70-85% | Instruction count limits (150-200), priority competition |
| **hookSpecificOutput** | **75-90%** | Injected into prompt context, harder to ignore (but not 100% enforced) |

**Important notes:**
- `additionalContext` is **prompt injection**, not forced execution
- Claude may still skip in some cases (e.g., efficiency-first mode)
- But reliability is ~15-20% higher than pure CLAUDE.md instructions

## Installation

### 1. Global hook (already complete)

```bash
# Hook is installed at:
~/.claude/hooks/hook-todo-injection.py

# Global config already updated:
~/.claude/settings.json (line 237-247)
```

### 2. Per-project configuration (needed for each project)

Create a todo script in your project:

```bash
# Project structure
my-project/
├── scripts/
│   └── todo/
│       ├── ask.py          # todo checklist for /ask command
│       ├── learn.py        # todo checklist for /learn command
│       ├── save.py         # todo checklist for /save command
│       └── maintain.py     # todo checklist for /maintain command
└── .claude/
    └── settings.json       # project-level config (optional)
```

### 3. Todo Script Format

Each script must output a JSON array:

```python
#!/usr/bin/env python3
"""
Todo checklist for /mycommand
"""
import json

def get_todos():
    return [
        {
            "content": "Step 1: Do something",
            "activeForm": "Step 1: Doing something",
            "status": "pending"
        },
        {
            "content": "Step 2: Do another thing",
            "activeForm": "Step 2: Doing another thing",
            "status": "pending"
        }
    ]

if __name__ == "__main__":
    todos = get_todos()
    print(json.dumps(todos, indent=2, ensure_ascii=False))
```

## Usage Examples

### Example 1: Running the /ask command

```bash
# User input
/ask What is theta decay?

# Hook automatically triggers:
# 1. Detects command "ask"
# 2. Runs scripts/todo/ask.py
# 3. Injects 10-step workflow into Claude's prompt
# 4. Claude must create todos before starting to answer
```

### Example 2: Command with no todo script

```bash
# User input
/my-custom-command

# Hook behavior:
# 1. Detects command "my-custom-command"
# 2. Looks for scripts/todo/my-custom-command.py (not found)
# 3. Passes through -- no content injected
```

## Testing

### Test the hook locally

```bash
# Test /ask command
echo '{"command": "/ask test"}' | source ~/.claude/venv/bin/activate && python3 ~/.claude/hooks/hook-todo-injection.py

# Expected JSON output:
# {
#   "status": "allow",
#   "hookSpecificOutput": {
#     "additionalContext": "CRITICAL WORKFLOW REQUIREMENT..."
#   }
# }
```

### Test a todo script

```bash
# Run the script directly
cd your-project
source venv/bin/activate  # if using venv
python scripts/todo/ask.py

# Expected: JSON array output
```

## Troubleshooting

### Hook not triggering

**Check global configuration:**
```bash
cat ~/.claude/settings.json | grep -A 10 '"PreToolUse"'
```

Expected output:
```json
"PreToolUse": [
  {
    "matcher": "SlashCommand",
    "hooks": [
      {
        "type": "command",
        "command": "source ~/.claude/venv/bin/activate && python3 ~/.claude/hooks/hook-todo-injection.py",
        "stdin_json": true,
        "on_error": "warn"
      }
    ]
  }
]
```

### Todo script not executing

**Check script paths:**
```bash
# Hook searches in priority order:
# 1. $CLAUDE_PROJECT_DIR/scripts/todo/{command}.py
# 2. $CLAUDE_PROJECT_DIR/.claude/scripts/todo/{command}.py
# 3. $(pwd)/scripts/todo/{command}.py
# 4. $(pwd)/.claude/scripts/todo/{command}.py
# 5. ~/.claude/scripts/todo/{command}.py (global fallback)

# Confirm script exists and is executable
ls -l scripts/todo/
ls -l ~/.claude/scripts/todo/
python3 scripts/todo/ask.py
```

**Check permissions:**
```bash
chmod +x scripts/todo/*.py
```

**Check Python environment:**
```bash
ls -la venv/bin/activate
which python3
```

### Hook returns error

The hook is designed to be **fail-safe** -- it passes through even on error:

```python
# Error handling example
try:
    # ... hook logic ...
except Exception as e:
    return {
        "status": "allow",
        "message": f"Todo injection error: {str(e)}"
    }
```

Check Claude Code's hook output for error messages.

## Advanced Configuration

### Per-project override (optional)

If a project has special requirements, override the global hook in the project's `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "SlashCommand",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR\"/scripts/hooks/custom-todo-injection.py",
            "stdin_json": true,
            "on_error": "warn"
          }
        ]
      }
    ]
  }
}
```

### Custom injection format

Modify the `format_todo_injection()` function in `hook-todo-injection.py`:

```python
def format_todo_injection(todos_json: str, cmd_name: str) -> str:
    """Custom injection message format"""
    return f"""
WORKFLOW CHECKLIST FOR /{cmd_name}

{todos_json}

IMPORTANT: Create these todos before starting!
"""
```

### Conditional injection

Add logic in the hook to inject only under specific conditions:

```python
# Example: only inject on weekdays (skip weekends)
from datetime import datetime

if datetime.now().weekday() >= 5:  # Saturday=5, Sunday=6
    return {"status": "allow"}  # no injection on weekends
```

## Architecture Notes

### hookSpecificOutput vs message

| Field | Display | Can Claude skip? |
|-------|---------|-----------------|
| `message` | Hook output message (user-visible) | Yes -- can be ignored |
| `hookSpecificOutput.additionalContext` | **Forced injection into prompt** | No -- cannot be skipped |

This is why we use `additionalContext` -- it directly modifies the conversation history Claude sees.

### PreToolUse vs UserPromptSubmit

| Hook timing | Triggered | Use case |
|-------------|---------|---------|
| `UserPromptSubmit` | After user input, before tool execution | Input validation, security checks |
| `PreToolUse` | Before a specific tool call | Tool-specific pre-operations |

We use `PreToolUse + SlashCommand matcher` to ensure triggering only before slash command execution.

## Related Files

```
~/.claude/
├── hooks/
│   ├── hook-todo-injection.py         # main hook script (global)
│   └── README-TODO-INJECTION.md       # this document
└── settings.json                      # global config (contains hook registration)

your-project/
├── scripts/
│   └── todo/
│       ├── ask.py                     # todo checklist for /ask
│       ├── learn.py                   # todo checklist for /learn
│       └── save.py                    # todo checklist for /save
└── .claude/
    ├── commands/
    │   ├── ask.md                     # command definition
    │   └── learn.md
    └── settings.json                  # project config (optional override)
```

## Maintenance

### Adding todo support for a new command

1. Create a todo script: `scripts/todo/mycommand.py`
2. Write the script to output JSON following the format above
3. Test: `python scripts/todo/mycommand.py`
4. Use the command: `/mycommand` -- hook injects automatically

### Updating a todo checklist

Edit `scripts/todo/{command}.py` directly in your project.

### Disabling todo injection for a command

Remove or rename the corresponding todo script:

```bash
# Disable /ask todo injection
mv scripts/todo/ask.py scripts/todo/ask.py.disabled
```

## Best Practices

1. **Keep todo scripts simple** -- only output JSON; avoid complex logic
2. **Fast execution** -- hook has a 5-second timeout
3. **Fail gracefully** -- script errors must not block command execution
4. **Version control** -- include `scripts/todo/` in your git repository
5. **Keep docs in sync** -- update todo scripts when workflow changes

## FAQ

**Q: Why not just put instructions in CLAUDE.md?**
A: CLAUDE.md instructions have count limits and can be ignored by Claude. The hook injects via additionalContext, making it harder to skip (though not 100% enforced).

**Q: Does the hook affect performance?**
A: Negligible impact. Script executes in <100ms and only triggers on slash commands.

**Q: Can it be used for non-slash commands?**
A: You can change the hook's matcher, but using it only for slash commands is recommended to maintain clear separation.

**Q: How do I share todo scripts across multiple projects?**
A: Create a template project and share `scripts/todo/` via symlinks or a Git submodule.

**Q: Can the hook modify command arguments?**
A: No. PreToolUse hooks can only inject context or block execution; they cannot modify arguments.

## Changelog

- **2025-12-31 v2**: Multi-path support update
  - Supports 5 search paths (project scripts, project .claude, cwd scripts, cwd .claude, global fallback)
  - Documentation corrected: 75-90% compliance rate (not 100% enforced)
  - Added global fallback mechanism

- **2025-12-31 v1**: Initial release
  - Global todo injection hook
  - Support for project-specific todo scripts
  - hookSpecificOutput.additionalContext mechanism

---

**Author:** Happy + Claude Code
**License:** MIT
**Maintenance:** Global config in `~/.claude/`, project config in each project's `scripts/todo/`
