#!/usr/bin/env python3
# STUB: settings.json registers it, but its only effect was G4's re-validation of every dispatch's artifacts at the session's Stop, which G2 decides at each producer's own stop.
"""Stop hook (G4, session-terminal obligation gate), retired to a no-op.

It re-validated, at the orchestrating session's Stop, the json artifacts its
dispatches had declared. Each of those artifacts is decided where it is made:
G2 (subagentstop-artifact-contract-enforce.py) at its producer's own stop, and
G3 (pretool-aggregate-check.py) at the next dispatch; a Stop-time copy decides
nothing they have not (P1b row 3, D15). The command's own Stop gate (P5)
takes this registration over. settings.json still registers this file, and a
running session keeps the hook list it loaded, so the file stays as an exit-0
stub that reads nothing and decides nothing."""
import sys

sys.exit(0)
