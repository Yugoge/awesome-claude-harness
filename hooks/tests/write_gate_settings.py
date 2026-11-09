"""The registration change that switches the write gate on, as a function of settings.json.

``gate_settings(settings)`` returns a copy of a settings dict where the seven write
guards' PreToolUse registrations are gone and hooks/pretool-write-gate.py is registered
once, on every tool, at the place of the first one removed. The tests and the replay
comparison register the gate with it; the integration lane makes the same change in the
tracked settings.json.

    python3 hooks/tests/write_gate_settings.py IN OUT   # writes the scratch copy
"""
from __future__ import annotations

import copy
import json
import sys

REPLACED = (
    "pretool-bash-views-guard.py",
    "pretool-overnight-hook-guard.py",
    "pretool-tool-policy.py",
    "pretool-cp-state-write-guard.py",
    "pretool-subagent-code-block.py",
    "pretool-write-guard.sh",
    "pretool-claude-config-guard.py",
)
GATE_COMMAND = 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/pretool-write-gate.py"'
GATE_TIMEOUT = 70


def _replaced(command: str) -> bool:
    return any(command.rstrip('"').endswith("/hooks/" + name) for name in REPLACED)


def gate_settings(settings: dict) -> dict:
    out = copy.deepcopy(settings)
    groups = out["hooks"]["PreToolUse"]
    kept, at = [], None
    for group in groups:
        hooks = [h for h in group["hooks"] if not _replaced(h.get("command", ""))]
        if len(hooks) != len(group["hooks"]) and at is None:
            at = len(kept)
        if hooks:
            kept.append({**group, "hooks": hooks})
    if at is None:
        raise ValueError("none of the write guards is registered")
    kept.insert(at, {"matcher": "*", "hooks": [{"type": "command", "command": GATE_COMMAND,
                                                 "timeout": GATE_TIMEOUT}]})
    out["hooks"]["PreToolUse"] = kept
    return out


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as fh:
        data = json.load(fh)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(gate_settings(data), fh, indent=2)
        fh.write("\n")
