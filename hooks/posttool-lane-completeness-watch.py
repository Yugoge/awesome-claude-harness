#!/usr/bin/env python3
# STUB: no registration runs it (its rule of hooks/posttool-launch.py is retired); a dev lane's stop and the QA dispatch's check rebuild the aggregate (hooks/lib/aggregate_rebuild.py).
"""PostToolUse (matcher Write|Edit|NotebookEdit|MultiEdit) hook, retired to a no-op.

It ran scripts/aggregate-dev-report.py after each write of a lane report that declares a fan-out,
and always exited 0; the aggregate is now rebuilt where it is read, at a dev lane's stop and at the
QA dispatch's check. A hook list loaded before its retirement still names it by path at every file
edit, so the file stays as an exit-0 stub that reads nothing and decides nothing (D15)."""
import sys

sys.exit(0)
