#!/usr/bin/env python3
"""CLI: journal-based three-way staging adjudicator (read-only unless --capture-dispatch-baselines-into or --escalation-store is given; see scripts/lib/attribution_adjudicator.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from attribution_adjudicator import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
