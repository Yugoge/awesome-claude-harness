"""Tool names the harness's hooks decide by, each list defined once.

Plain data, standard library only: a hook imports it before it reads its payload.
"""

# The MCP tools that run code in a browser page; the run-code watchdog's PreToolUse hook starts
# a watchdog for each call and its PostToolUse hook ends it. (The launchers register the watchdog
# for the playwright name; scripts/install/render-settings adds the paseo name's own registration
# when that module is installed.)
RUN_CODE_TOOLS = frozenset({"mcp__playwright__browser_run_code", "mcp__paseo__browser_run_code"})
