#!/usr/bin/env python3
# STUB: settings.json no longer registers it (P12); pretool-tool-policy.py, a rule of hooks/pretool-write-gate.py, refuses every non-dev role's code write.
"""PreToolUse (Write|Edit|NotebookEdit|MultiEdit) advisory shim, retired to a no-op.

It printed a stderr warning when a subagent whose role does not resolve to dev
wrote a code file, and always exited 0, so the warning reached no model. The
role's path rows in pretool-tool-policy.py (lib/policy_registry) refuse those
writes. A running session keeps the hook list it loaded, so the file stays as an
exit-0 stub that reads nothing and decides nothing (D15)."""
import sys

sys.exit(0)
