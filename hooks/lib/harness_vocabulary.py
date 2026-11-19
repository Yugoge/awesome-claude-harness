"""Small vocabularies the harness's hooks decide by (tool names, gate modes), each defined once.

Plain data, standard library only: a hook imports it before it reads its payload.
"""

# The MCP tools that run code in a browser page; the run-code watchdog's PreToolUse hook starts
# a watchdog for each call and its PostToolUse hook ends it. (The launchers register the watchdog
# for the playwright name; scripts/install/render-settings adds the paseo name's own registration
# when that module is installed.)
RUN_CODE_TOOLS = frozenset({"mcp__playwright__browser_run_code", "mcp__paseo__browser_run_code"})

# The modes of a Stop-time gate: hooks/stop-command-gate.py's --mode and the obligation branch's
# CLAUDE_OBLIGATION_STOPGATE (hooks/subagentstop-artifact-contract-enforce.py). Any other value
# is not a mode: each reader keeps its own default for it.
GATE_MODES = ("block", "advisory", "off")

# The markdown files of a folder that are its folder documents (doc-sync writes them), never its
# content: not a command, an agent, a spec, a template or a todo script's command.
FOLDER_DOCUMENTS = ("INDEX.md", "README.md")
