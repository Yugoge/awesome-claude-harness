#!/usr/bin/env python3
# STUB: settings.json no longer registers it (P5 R21); a session that loaded an older hook list still runs it.
"""Stop hook (the /do do-report's shape at session stop), retired to a no-op.

It held a /do session's Stop until the do-report the consent sidecar named had
a terminal status and its fields' shapes. The Stop gate behind
hooks/stop-launch.py holds every /do span instead (P5 R7, R8): the task is the
hook-minted id of the span's opener (never the sidecar), and it is complete
when its do-report validates, do.status is completed (the schema's one value,
R21) and its file lists equal the span's write set. A running session keeps
the hook list it loaded, so the file stays as an exit-0 stub that reads
nothing and decides nothing (D15)."""
import sys

sys.exit(0)
