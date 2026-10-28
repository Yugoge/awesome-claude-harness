#!/usr/bin/env python3
# STUB: settings.json registers it, but its only effect was an idle log no reader or owner output names.
"""Notification hook (idle_prompt) for /dev-overnight, retired to a no-op.

Its only effect was appending a record to the harness home's
logs/overnight-idle.jsonl on each idle event of a live overnight session.
Nothing reads that log and no command output or hook systemMessage names its
path, so the write is gone. settings.json still registers this file, and a
running session keeps the hook list it loaded, so the file stays as an
exit-0 stub."""
import sys

sys.exit(0)
