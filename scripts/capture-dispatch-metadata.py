#!/usr/bin/env python3
"""CLI: persist write-time dispatch metadata (agent-identity-to-lane mapping +
dispatch-time baseline content for files already dirty at dispatch) in the --lanes
shape scripts/adjudicate-attribution-staging.py and scripts/attribution-aggregate-
view.py already require (see scripts/lib/dispatch_metadata.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from dispatch_metadata import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
