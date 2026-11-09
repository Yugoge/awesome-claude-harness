#!/usr/bin/env python3
"""Behind /rating: print the score log's per-agent view of the current project. Reads only; exit 0 even for a log it cannot read."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks" / "lib"))
import score_log  # noqa: E402

log = score_log.log_path()
try:  # a log never written means no records yet
    rows = [row for _, row in score_log.read_lines(str(log))] if log.exists() else []
    print(score_log.render_rating_view(rows, score_log.project_key(os.getcwd()), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
except score_log.ScoreLogError as exc:
    print(f"The score log cannot be read: {exc}")
