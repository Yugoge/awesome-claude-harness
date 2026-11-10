#!/usr/bin/env python3
"""/clean Step 16: merge the owner's approvals and the safety checkpoint into the cleaner's context.

    python3 scripts/steps/clean-merge-approvals.py <request_id> <checkpoint_commit>

Run from the project root. Reads `docs/clean/context-<request_id>.json` (Step 3) and
`docs/clean/user-approvals-<request_id>.json` (Step 13) and writes
`docs/clean/context-with-approvals-<request_id>.json`, the file the cleaner is dispatched with:
the context, recursively merged with `{user_approvals: <the approvals' user_approvals>}` and
`{orchestrator: {analysis: {safety_checkpoint_created: true, checkpoint_commit: <commit>}}}`
(the merge the prompt used to spell as one `jq -s '.[0] * ... * ...'` call; an object merges
key by key, any other value is replaced).

Prints one line, `context_with_approvals=<path>`. Neither input file is changed.

Exit codes:
  0  merged file written
  1  an input is missing or is not a JSON object, or the approvals file has no `user_approvals`
     object; nothing is written
  2  usage error
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CLEAN_DIR = Path("docs") / "clean"


def merge(base: dict, extra: dict) -> dict:
    """jq's `base * extra`: objects merge recursively, any other value of `extra` replaces `base`'s."""
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def load_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"clean-merge-approvals: cannot read {path}: {exc.strerror or exc}")
    except ValueError as exc:
        raise SystemExit(f"clean-merge-approvals: {path} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"clean-merge-approvals: {path} is not a JSON object")
    return data


def main(argv: list[str]) -> int:
    if len(argv) != 3 or not all(argv[1:]):
        print("usage: clean-merge-approvals.py <request_id> <checkpoint_commit>", file=sys.stderr)
        return 2
    request_id, commit = argv[1], argv[2]
    context = load_object(CLEAN_DIR / f"context-{request_id}.json")
    approvals = load_object(CLEAN_DIR / f"user-approvals-{request_id}.json").get("user_approvals")
    if not isinstance(approvals, dict):
        print(f"clean-merge-approvals: user-approvals-{request_id}.json has no user_approvals object",
              file=sys.stderr)
        return 1
    merged = merge(context, {"user_approvals": approvals})
    merged = merge(merged, {"orchestrator": {"analysis": {"safety_checkpoint_created": True,
                                                            "checkpoint_commit": commit}}})
    target = CLEAN_DIR / f"context-with-approvals-{request_id}.json"
    target.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"context_with_approvals={target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
