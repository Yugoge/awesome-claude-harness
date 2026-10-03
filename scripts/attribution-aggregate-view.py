#!/usr/bin/env python3
"""CLI: journal-backed canonical aggregate view (read-only unless --escalation-store is given; see scripts/lib/attribution_aggregate_view.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from attribution_aggregate_view import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
