#!/usr/bin/env python3
"""PermissionRequest: answer every permission request by rule, so no tool call waits for a person.

Claude Code raises this event where it would ask a person to approve a call: an ask rule, its own
critical-path removal check (`rm`/`rmdir`, which no allow rule or PreToolUse "allow" approves, even in
bypassPermissions mode), or, outside bypassPermissions, a call no allow rule covers. The PreToolUse
hooks have already run on the call and not refused it. The answer:

- Bash and Monitor: the harness's Bash rules (lib/bash_safety_rules.py, the rules of
  hooks/pretool-bash-safety.sh, its removal rule among them) are asked again of the command. A refusal
  is a deny with their text, and so is a command whose text holds what a Bash deny rule of settings.json
  refuses (Claude Code asks for one it cannot split). A command they let run is allowed in bypassPermissions mode, and in any
  mode when its text holds a removal word (lib/pol_degraded_removal_reference.ere): the removal rule
  lets such a command run only when it proves it, today an own-scratch removal (every file written out
  and inside the caller's own scratch directory) or a command proven inert.
- Any other tool: allowed in bypassPermissions mode (the mode runs every call the hooks and deny rules
  let through; Claude Code asks only for its own checks), refused in any other mode, where it asks
  because no allow rule in settings covers the call.
- AskUserQuestion and ExitPlanMode ask the person a question rather than for a permission: left to
  the hooks that decide those tools.

Failure: any error of this file, and a decision not reached within DEADLINE seconds, is a deny. Where
this process itself dies or is killed (no decision printed), Claude Code applies no decision: a run
without a prompt host refuses the call, and a session whose host answers prompts (--permission-prompt-tool
stdio) leaves the request to that host.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys

HOOKS = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = ("AskUserQuestion", "ExitPlanMode")
DEADLINE = 30  # seconds; the registration's timeout is longer (hooks/permissionrequest-launch.py)
NOTE = ("No person is asked to approve a tool call in this harness: a rule allows it or refuses it. "
        "This call was refused; change the call, do not retry it unchanged.")


def answer(behavior: str, message: str = "") -> None:
    decision = {"behavior": behavior}
    if behavior == "deny":
        decision["message"] = (message.strip() + "\n" + NOTE).strip()
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}))


def bash_rules(payload: dict) -> str | None:
    """The Bash rules' refusal text for the call's command, or None when they let it run."""
    probe = dict(payload, tool_name="Bash")
    run = subprocess.run([sys.executable, os.path.join(HOOKS, "lib", "bash_safety_rules.py"), HOOKS],
                         input=json.dumps(probe), capture_output=True, text=True, timeout=DEADLINE - 5)
    if run.returncode == 0 and run.stdout.split()[:1] in (["ALLOW"], ["CONSENT"], ["SENTINEL"]):
        return None
    return run.stderr.strip() or f"the harness's Bash rules gave no verdict (exit {run.returncode})"


def denied_in_text(command: str) -> str | None:
    """A Bash deny rule of the harness's settings.json whose command appears anywhere in the text, where a word
    starts. Claude Code asks, rather than denies, when it finds a deny rule's command in a part of the text it
    could not split into commands (`...; su postgres -c "..."`); that request is refused here as the rule says."""
    with open(os.path.join(os.path.dirname(HOOKS), "settings.json")) as fh:
        rules = json.load(fh).get("permissions", {}).get("deny", [])
    for rule in rules:
        if not (isinstance(rule, str) and rule.startswith("Bash(") and rule.endswith(")")):
            continue
        body = rule[5:-1]
        body = body[:-2] if body.endswith(":*") else body
        # `*` inside a word stands for word characters (b*ash: bash), elsewhere for any text; a rule not
        # ending in `*` ends where a word ends.
        rx = re.sub(r"(?<=\w)\\\*(?=\w)", r"\\w*", re.escape(body)).replace(r"\*", ".*")
        rx = r"(?:^|[\s;&|(){}`'\"])" + rx + ("" if body.endswith("*") else r"(?=[\s;&|)`'\"]|$)")
        if re.search(rx, command):
            return rule
    return None


def names_removal(command: str) -> bool:
    """The removal rule's one test of whether a command's text holds a removal word."""
    with open(os.path.join(HOOKS, "lib", "pol_degraded_removal_reference.ere")) as fh:
        pattern = re.compile(fh.read().strip())
    return any(pattern.search(line) for line in command.split("\n"))


def decide(payload: dict) -> tuple[str, str] | None:
    tool, mode = payload.get("tool_name"), payload.get("permission_mode")
    if tool in QUESTIONS:
        return None
    bypass = mode == "bypassPermissions"
    command = (payload.get("tool_input") or {}).get("command")
    if isinstance(command, str):  # a call that runs a shell command: Bash, Monitor
        refusal, rule = bash_rules(payload), denied_in_text(command)
        if refusal is not None:
            return "deny", refusal
        if rule is not None:
            return "deny", f"BLOCKED: the command holds what the deny rule {rule} of settings.json refuses."
        if bypass or names_removal(command):
            return "allow", ""
    elif bypass:
        return "allow", ""
    return "deny", (f"BLOCKED: no allow rule in settings covers this {tool} call in {mode} mode, and outside "
                    "bypassPermissions mode a call runs only when one does.")


def record(raw: str, message: str) -> None:
    """REFUSAL-RECORD CALL SITE: the refusal record's writer (lib/refusal_record.py, branch pledge/20261119)
    is not on this branch; once joined, this records the deny (its EVENTS must then name PermissionRequest)."""
    try:
        from lib import refusal_record  # type: ignore[attr-defined]
    except ImportError:
        return
    try:
        me = os.path.abspath(__file__)
        refusal_record.report(raw, [(me, message)], me)
    except Exception:  # noqa: BLE001 -- recording never decides
        pass


def main() -> int:
    raw = sys.stdin.read()

    def late(signum, frame):
        raise TimeoutError(f"no decision within {DEADLINE} s")

    signal.signal(signal.SIGALRM, late)
    signal.alarm(DEADLINE)
    try:
        payload = json.loads(raw)
        result = decide(payload if isinstance(payload, dict) else {})
    except BaseException as exc:  # noqa: BLE001 -- failing to decide is a refusal, never a prompt
        result = ("deny", f"BLOCKED: the permission-request hook could not decide this call ({type(exc).__name__}: "
                          f"{exc}); refused rather than asking a person.")
    signal.alarm(0)
    if result is None:
        return 0
    behavior, message = result
    answer(behavior, message)
    if behavior == "deny":
        sys.path.insert(0, HOOKS)
        record(raw, message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
