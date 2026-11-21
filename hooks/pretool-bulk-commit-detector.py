#!/usr/bin/env python3
# STUB: no registration runs it (its rule of hooks/pretool-launch.py is retired); hooks/pretool-git-privilege-guard.py refuses or reviews every agent commit it read.
"""PreToolUse (matcher Bash) advisory hook, retired to a no-op.

It warned through additionalContext when a plain commit staged files across three or more of
hooks/, commands/, scripts/, packages/ and docs/ under a sync-shaped subject, and always exited 0;
the warning reached no model, and every agent commit it read is refused or reviewed by the
privilege guard. A hook list loaded or copied before its retirement may still name it by path, so
the file stays as an exit-0 stub that reads nothing and decides nothing (D15)."""
import sys

sys.exit(0)
