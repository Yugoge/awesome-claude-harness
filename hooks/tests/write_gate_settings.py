"""P12-L4's registration change, as a function of settings.json.

``gate_settings(settings)``: the seven write guards' PreToolUse registrations go, and
hooks/pretool-write-gate.py is registered once, on every tool, where the first one stood.

``l4_settings(settings)``: all of L4's change, the gate included:
- the five anti-loop hooks' registrations go (two on PreToolUse Agent, three on
  SubagentStop), and hooks/lib/dev_loop_checks.py is registered on PreToolUse Agent and
  on PostToolUse Agent, where the orchestrator reads its advice;
- posttool-git-warn.sh is registered on ``Bash`` (its old matcher was a regex on the tool
  name, which never matched);
- the three registered stubs go: notification-idle-overnight.py,
  posttool-push-gate-token-verify.py, pretool-push-analyst-grant-guard.py (the files stay,
  exit 0, for a session that loaded an older list: D15).

The tests and the replay comparison use these copies; the integration lane makes the same
change in the tracked settings.json.

    python3 hooks/tests/write_gate_settings.py IN OUT [--gate-only]
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
ANTI_LOOP = (
    "pretool-layer-escalation-check.sh",
    "pretool-bisect-gate.sh",
    "subagent-stop-diff-check.sh",
    "pretool-layer-match-gate.sh",
    "subagent-stop-guard-integrity.sh",
)
STUBS = (
    "notification-idle-overnight.py",
    "posttool-push-gate-token-verify.py",
    "pretool-push-analyst-grant-guard.py",
)
GATE_COMMAND = 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/pretool-write-gate.py"'
GATE_TIMEOUT = 70
DEV_LOOP_COMMAND = 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/lib/dev_loop_checks.py"'
GIT_WARN = "posttool-git-warn.sh"


def _names(command: str, names) -> bool:
    return any(command.rstrip('"').endswith("/hooks/" + name) for name in names)


def _replaced(command: str) -> bool:
    return _names(command, REPLACED)


def _drop(groups: list, names) -> tuple[list, int | None]:
    """``groups`` without the registrations of ``names``; and where the first one stood."""
    kept, at = [], None
    for group in groups:
        hooks = [h for h in group["hooks"] if not _names(h.get("command", ""), names)]
        if len(hooks) != len(group["hooks"]) and at is None:
            at = len(kept)
        if hooks:
            kept.append({**group, "hooks": hooks})
    return kept, at


def gate_settings(settings: dict) -> dict:
    out = copy.deepcopy(settings)
    kept, at = _drop(out["hooks"]["PreToolUse"], REPLACED)
    if at is None:
        raise ValueError("none of the write guards is registered")
    kept.insert(at, {"matcher": "*", "hooks": [{"type": "command", "command": GATE_COMMAND,
                                                 "timeout": GATE_TIMEOUT}]})
    out["hooks"]["PreToolUse"] = kept
    return out


def l4_settings(settings: dict) -> dict:
    out = gate_settings(settings)
    hooks = out["hooks"]
    dev_loop = {"matcher": "Agent", "hooks": [{"type": "command", "command": DEV_LOOP_COMMAND, "timeout": 30}]}
    pre, at = _drop(hooks["PreToolUse"], ANTI_LOOP + STUBS)
    pre.insert(at if at is not None else len(pre), copy.deepcopy(dev_loop))
    hooks["PreToolUse"] = pre
    post, _ = _drop(hooks["PostToolUse"], STUBS)
    for group in post:
        if any(_names(h.get("command", ""), (GIT_WARN,)) for h in group["hooks"]):
            group["matcher"] = "Bash"
    post.append(copy.deepcopy(dev_loop))
    hooks["PostToolUse"] = post
    for event in ("SubagentStop", "Notification"):
        if event in hooks:
            hooks[event], _ = _drop(hooks[event], ANTI_LOOP + STUBS)
            if not hooks[event]:
                del hooks[event]
    return out


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as fh:
        data = json.load(fh)
    change = gate_settings if "--gate-only" in sys.argv[3:] else l4_settings
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(change(data), fh, indent=2)
        fh.write("\n")
