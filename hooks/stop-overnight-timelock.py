#!/usr/bin/env python3
# STUB: no hook list runs it since P5; the overnight time-lock and the wake check are hooks/stop-command-gate.py's (step 4).
"""Stop hook (the /dev-overnight time-lock), retired to a no-op.

It blocked the session's Stop while its overnight window was open, then after
end_time until Step 21's summary was written and the session's wake had a later
CronDelete, and published the terminal receipt. The Stop gate behind
hooks/stop-launch.py holds the same time-lock for every Stop (P5 R7, step 4,
the Codex runtime excepted), and the coordinator publishes the receipt from the
gate's terminal status (R9). A session that loaded an older hook list runs the
current coordinator, which no longer runs this file; it stays an exit-0 stub
that reads nothing and decides nothing (D15)."""
import sys

sys.exit(0)
