# Infra-Hook Eval Case infra-hook-006: pretool-mcp-policy.py

## Trigger
PreToolUse with matcher `mcp__*`. Hook fires before any MCP tool
invocation, including playwright, claudeai-proxy, and happy.

## Behavior Required
- Reads PreToolUse hook input JSON on stdin and inspects `tool_name`.
- Matches the prefix `mcp__` and extracts the server name and tool
  name segments.
- Applies a per-server policy table: `playwright` is allow-all,
  `claudeai-proxy` requires authenticated state file, `happy` is
  blocked for subagents (orchestrator-only).
- Emits structured stderr naming the violated policy when blocking.
- Logs every MCP invocation to `~/.claude/logs/mcp-policy.log` with
  timestamp, tool name, and decision.

## Exit Code Contract
- exit 0: MCP tool is allowed by policy table.
- exit 2: MCP tool is blocked (e.g., subagent calling `mcp__happy__*`).

## Acceptance
- AC-1: allows `mcp__playwright__browser_snapshot` for orchestrator
  with exit 0.
- AC-2: blocks `mcp__happy__change_title` when `agent_id` present
  with exit 2.
- AC-3: log file gains exactly one new line per invocation regardless
  of decision.
