#!/usr/bin/env bash
# STUB: settings.json no longer registers it (P12); hooks/pretool-write-gate.py runs its checks as the
# write gate's overwrite rule, hooks/lib/write_gate/overwrite.py.
# It refused a Write over an existing file (Edit changes one), and any Write or NotebookEdit of the
# bulk-commit sentinel, unless /do consent or an /allow grant naming the target let the main agent's
# Write through. A running session keeps the hook list it loaded, so the file stays at its path as an
# exit-0 stub that reads nothing and decides nothing (D15).
exit 0
