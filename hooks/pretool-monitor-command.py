#!/usr/bin/env python3
"""PreToolUse (Monitor): a Monitor's shell command meets every Bash rule, as a Bash call would.

Monitor runs an arbitrary shell command in the background. On CLI 2.1.325 the CLI delivers that
command as a Bash call ({command, description}, the same tool_use_id) only to hooks registered
under a "Bash" matcher in settings.json (none now: pretool-bash-safety.sh is a launcher rule). The launcher's Bash rules
(hooks/pretool-launch.py) select by tool_name, and so does the write gate's Bash branch, so they
saw the call only as Monitor and skipped it: `gh pr create` was refused as Bash and passed as
Monitor.

This rule hands each of them the Bash call the CLI hands the Bash matcher: the launcher's rules
whose tools name Bash, and the write gate (registered on every tool, it picks its Bash rules by
tool_name). Each runs as its own process with its own timeout, and their answers combine as the
launcher combines them (lib/hook_launch.combine): any refusal refuses the Monitor, with the
rules' reasons. An ask or defer decision and additional context pass on; an allow or an
updatedInput, meant for a Bash call, does not.

Fail closed: a Monitor whose command cannot be read (a non-string or empty command, or neither a
command nor a WebSocket `ws` object) is refused, and so is any fault in this rule's own code. A
WebSocket Monitor (`ws`, no command) runs no shell and passes. Rules that see every tool and
already decide Monitor themselves (the orchestrator gate counts it against the Bash cap) are not
run twice.
"""
from __future__ import annotations
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import json
import os
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOOKS_DIR)
LOAD_ERROR = None
try:
    from lib.hook_launch import Rule, combine, run_process  # noqa: E402
except Exception as exc:  # refused below, on a Monitor that carries a command (fail closed)
    LOAD_ERROR = exc
    Rule = None

# The launcher's rules (hooks/pretool-launch.py RULES, in its order) that a Bash call reaches and a
# Monitor call does not: those whose tools name Bash, and the write gate, which is registered on
# every tool and picks its Bash rules by tool_name. hooks/tests/test_monitor_command.py derives this
# list from the launcher and fails when they differ.
BASH_RULES = () if Rule is None else (
    Rule('write-gate', 'pretool-write-gate.py', None, timeout=70, matcher_spelling='*'),
    Rule('wrapper-userintent', 'pretool-wrapper-userintent.py', ('Bash',)),
    Rule('grep-backtrack-guard', 'pretool-grep-backtrack-guard.py', ('Bash',)),
    Rule('attribution-pre', 'pretool-attribution-pre.py', ('Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Bash'), timeout=30),
    Rule('lane-ledger', 'pretool-lane-ledger.py', ('Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Bash'), timeout=10),
    Rule('block-branch-pr-worktree', 'pretool-block-branch-pr-worktree.py', ('Bash',)),
    Rule('git-privilege-guard', 'pretool-git-privilege-guard.py', ('Bash',)),
    Rule('merge-verdict', 'pretool-merge-verdict.py', ('Bash',), timeout=20),
    Rule('deny-list', 'pretool-deny-list.py', ('Bash', 'Read', 'Grep', 'Glob', 'Edit', 'Write', 'MultiEdit',
                                               'NotebookEdit', 'Skill'), timeout=10),
    Rule('bash-safety', 'pretool-bash-safety.sh', ('Bash',)),
)


def _refuse(why: str) -> int:
    sys.stderr.write(f"[BLOCK] Monitor: {why}\n")
    return 2


def command_of(tool_input):
    """(command or None, reason it cannot be read or None). None, None: a WebSocket Monitor."""
    if not isinstance(tool_input, dict):
        return None, "its tool_input is not an object"
    if "command" in tool_input:
        cmd = tool_input["command"]
        if isinstance(cmd, str) and cmd.strip():
            return cmd, None
        return None, "its command is not a non-empty string"
    if isinstance(tool_input.get("ws"), dict):
        return None, None
    return None, "it carries neither a command nor a ws object"


def as_bash(data: dict, command: str) -> bytes:
    """The Bash call the CLI hands a "Bash" matcher for this Monitor (measured on CLI 2.1.325)."""
    tool_input = {"command": command}
    desc = data["tool_input"].get("description")
    if isinstance(desc, str):
        tool_input["description"] = desc
    return json.dumps({**data, "tool_name": "Bash", "tool_input": tool_input}).encode()


def _answer(code: int, out: str, err: str) -> int:
    """Pass on a refusal, a non-blocking error, ask/defer and context; drop allow and updatedInput."""
    if code == 2:
        sys.stderr.write("Monitor's command, checked as a Bash call, is refused:\n" + err)
        return 2
    if code != 0:
        sys.stderr.write(err)
        return code
    try:
        merged = json.loads(out) if out.strip() else {}
    except ValueError:
        merged = {}
    hso = merged.get("hookSpecificOutput") if isinstance(merged, dict) else None
    keep: dict = {}
    if isinstance(hso, dict):
        if hso.get("permissionDecision") in ("ask", "defer"):
            keep["permissionDecision"] = hso["permissionDecision"]
            keep["permissionDecisionReason"] = hso.get("permissionDecisionReason", "")
        if hso.get("additionalContext"):
            keep["additionalContext"] = hso["additionalContext"]
    answer: dict = {}
    if keep:
        answer["hookSpecificOutput"] = {"hookEventName": "PreToolUse", **keep}
    if isinstance(merged, dict) and merged.get("systemMessage"):
        answer["systemMessage"] = merged["systemMessage"]
    if answer:
        sys.stdout.write(json.dumps(answer) + "\n")
    return 0


def main(raw: bytes) -> int:
    try:
        data = json.loads(raw)
    except ValueError:
        return 0  # not a call this rule can name: every rule of the launcher runs on it
    if not isinstance(data, dict) or data.get("tool_name") != "Monitor":
        return 0
    command, why = command_of(data.get("tool_input"))
    if why:
        return _refuse(f"its command cannot be read ({why}), so the Bash rules cannot check it.")
    if command is None:
        return 0  # a WebSocket Monitor runs no shell command
    if LOAD_ERROR is not None:
        return _refuse(f"lib/hook_launch.py did not load ({LOAD_ERROR}), so the Bash rules cannot check its command.")
    payload = as_bash(data, command)
    results = [run_process(rule, payload) for rule in BASH_RULES]
    return _answer(*combine("PreToolUse", results))


if __name__ == "__main__":
    try:
        code = main(sys.stdin.buffer.read())
    except Exception as exc:  # fail closed: an unchecked Monitor command must not run
        code = _refuse(f"the Bash-rule check failed ({type(exc).__name__}: {exc}), so the call is refused.")
    sys.exit(code)
