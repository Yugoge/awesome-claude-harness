"""``python -m tests.artifact_graph <tree> <output.jsonl>``."""

import sys

if __package__:
    from .static_half import main
else:  # run as a directory: put the repository root on the path
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tests.artifact_graph.static_half import main

sys.exit(main())
