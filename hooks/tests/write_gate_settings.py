"""P12's registration change in settings.json (L4 #25, L5 #26), and the write guards it replaced.

At the P12 base (retired_hooks.BASE) settings.json registers 78 hooks of 77 files; the tracked file
registers 52 of 51:

- L4: the seven write guards' PreToolUse registrations (REPLACED) go, and hooks/pretool-write-gate.py
  is registered once, on every tool, with a 70 s timeout, where the first one stood; the five anti-loop
  hooks' registrations go (ANTI_LOOP: two on PreToolUse Agent, three on SubagentStop), and their checks,
  hooks/lib/dev_loop_checks.py, are an advise rule of the two dispatch gates below instead of two
  registrations of their own; posttool-git-warn.sh is registered on ``Bash`` (its old matcher was a
  regex on the tool name, which never matched); the three registered stubs go (STUBS; the files stay,
  exit 0, for a session that loaded an older list: D15).
- L5: fifteen registrations (DISPATCH) become three gates (GATES), none with a timeout, as none of the
  fifteen had one.

OLD_GUARDS are the seven guards' registrations at the base, in settings.json order: the write gate's
tests run them as the CLI ran them. Two of the seven files are exit-0 stubs now (D15);
``old_guards(dest)`` gives their commands with those two run as the base shipped them
(hooks/tests/retired_hooks.py).
"""
from __future__ import annotations

from pathlib import Path

import retired_hooks

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
DISPATCH = (
    "pretool-subagent-enforce.py",
    "pretool-spec-block-foreground-agent.py",
    "pretool-orchestrator-prompt-purity.py",
    "pretool-aggregate-check.py",
    "pretool-gitignore-preflight.py",
    "pretool-obligation-gate.py",
    "pretool-commit-dispatch-attest.py",
    "posttool-overnight-file-check.py",
    "posttool-subagent-track.py",
    "posttool-overnight-trace.py",
    "subagentstop-codex-enforce.py",
    "subagentstop-e2e-enforce.py",
    "subagentstop-artifact-contract-enforce.py",
    "subagentstop-cp-enforce.py",
    "subagentstop-restart-track.py",
)
GATE_COMMAND = 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/pretool-write-gate.py"'
GATE_TIMEOUT = 70
DEV_LOOP = "lib.dev_loop_checks:advice"
GIT_WARN = "posttool-git-warn.sh"
# (event, matcher, gate file, the rule name its RULES give dev_loop_checks or None)
GATES = (
    ("PreToolUse", "Agent", "pretool-dispatch-gate.py", "dev-loop-before"),
    ("PostToolUse", "Agent", "posttool-dispatch-record.py", "dev-loop-after"),
    ("SubagentStop", "*", "subagentstop-producer-gate.py", None),
)
BASE_COUNT = 78

_HOME = "${CLAUDE_HOME:-$HOME/.claude}/hooks/"
OLD_GUARDS = (  # (matcher, file, timeout) at the base; 60 is the CLI's default timeout
    ("Bash", "pretool-bash-views-guard.py", 60),
    ("Write|Edit|MultiEdit|Bash|AskUserQuestion", "pretool-overnight-hook-guard.py", 60),
    ("*", "pretool-tool-policy.py", 60),
    ("Write|Edit|MultiEdit|NotebookEdit|Bash", "pretool-cp-state-write-guard.py", 60),
    ("Write|Edit|NotebookEdit|MultiEdit", "pretool-subagent-code-block.py", 60),
    ("Write", "pretool-write-guard.sh", 5),
    ("Edit|Write|MultiEdit|Bash", "pretool-claude-config-guard.py", 5),
)
RETIRED = ("pretool-subagent-code-block.py", "pretool-write-guard.sh")


def _names(command: str, names) -> bool:
    return any(command.rstrip('"').endswith("/hooks/" + name) for name in names)


def _replaced(command: str) -> bool:
    return _names(command, REPLACED)


def old_guards(dest: Path) -> list[tuple[str, str, int]]:
    """(matcher, command, timeout) of the seven guards as the base registered them; the two retired
    files run from their base copies under ``dest``."""
    out = []
    for matcher, name, timeout in OLD_GUARDS:
        shell = "bash" if name.endswith(".sh") else "python3"
        where = f'"{retired_hooks.materialize(name, dest)}"' if name in RETIRED else f'"{_HOME}{name}"'
        out.append((matcher, f"{shell} {where}", timeout))
    return out
