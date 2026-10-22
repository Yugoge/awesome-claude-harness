#!/usr/bin/env python3
# STUB: unregistered in P1; exits 0 until P10 deletes it.
"""Retired Stop hook (TC-10, TC-37). P1 removed its settings.json entry: it
blocked compliant /dev Stops with GATE_ERROR and its only release was a
self-written arbitration file. A session that loaded the old hook list still
runs this path, and python3 on a missing file exits 2, so the file stays as an
exit-0 stub until P10."""
import sys

sys.exit(0)
