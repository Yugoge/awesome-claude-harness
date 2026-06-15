#!/bin/bash
# pre_slashcommand_validate.sh
# Documentation-only slash-command policy stub.
# Currently performs no validation and exits 0.

# Read the tool use JSON from stdin (if available)
# Format: {"tool": "SlashCommand", "arguments": {"command": "/think hard ..."}}

# Define safe (auto-approved) commands
SAFE_COMMANDS=(
  "/think"
  "/ultrathink"
  "/status"
  "/explain-code"
  "/code-review"
  "/refactor"
  "/optimize"
  "/security-check"
  "/doc-gen"
  "/test-gen"
  "/debug-help"
  "/playwright-helper"
  "/file-analyze"
  "/artifact-mermaid"
  "/artifact-react"
  "/quick-prototype"
  "/deep-search"
  "/research-deep"
  "/search-tree"
  "/reflect-search"
  "/site-navigate"
)

# Define commands requiring approval (destructive)
ASK_COMMANDS=(
  "/push"
  "/pull"
  "/quick-commit"
  "/checkpoint"
  "/fswatch"
)

# Allow by default (no-op policy stub; validation logic not yet implemented)
exit 0
