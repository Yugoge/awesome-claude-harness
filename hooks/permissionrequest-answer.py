#!/usr/bin/env python3
"""PermissionRequest: answer every permission request by rule, so no tool call waits for a person.

Its rules are stated once, in docs/how-it-works.md ("Permission prompts") and ledger row H-101; decide() is that
table. An error or no decision within DEADLINE seconds is a deny; exit 2, which leaves it to a person, is never used.
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


def bash_rules(payload: dict) -> tuple[str, bool] | None:
    """(the Bash rules' refusal text, whether they refused themselves: exit 2, which they record) for the call's
    command, or None when they let it run."""
    probe = dict(payload, tool_name="Bash")
    run = subprocess.run([sys.executable, os.path.join(HOOKS, "lib", "bash_safety_rules.py"), HOOKS],
                         input=json.dumps(probe), capture_output=True, text=True, timeout=DEADLINE - 5)
    if run.returncode == 0 and run.stdout.split()[:1] in (["ALLOW"], ["CONSENT"], ["SENTINEL"]):
        return None
    return (run.stderr.strip() or f"the harness's Bash rules gave no verdict (exit {run.returncode})",
            run.returncode == 2)


def denied_in_text(command: str) -> str | None:
    """A Bash deny rule of settings.json whose command starts a word anywhere in the text: Claude Code asks, not
    denies, for one in a part it cannot split (`...; su postgres -c "..."`); refused here as the rule says."""
    with open(os.path.join(os.path.dirname(HOOKS), "settings.json")) as fh:
        rules = json.load(fh).get("permissions", {}).get("deny", [])
    for rule in rules:
        if not (isinstance(rule, str) and rule.startswith("Bash(") and rule.endswith(")")):
            continue
        body = rule[5:-1]
        body = body[:-2] if body.endswith(":*") else body
        # `*` inside a word: word characters (b*ash: bash), elsewhere any text; no trailing `*`: ends with a word.
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


def decide(payload: dict) -> tuple[str, str, bool] | None:
    """(behavior, message, whether this file records a deny: the Bash rules record their own refusals)."""
    tool, mode = payload.get("tool_name"), payload.get("permission_mode")
    if tool in QUESTIONS:
        return None
    bypass = mode == "bypassPermissions"
    command = (payload.get("tool_input") or {}).get("command")
    if isinstance(command, str):  # a call that runs a shell command: Bash, Monitor
        refusal, rule = bash_rules(payload), denied_in_text(command)
        if refusal is not None:
            return "deny", refusal[0], not refusal[1]
        if rule is not None:
            return "deny", f"BLOCKED: the command holds what the deny rule {rule} of settings.json refuses.", True
        if bypass or names_removal(command):
            return "allow", "", False
    elif bypass:
        return "allow", "", False
    return "deny", (f"BLOCKED: no allow rule in settings covers this {tool} call in {mode} mode, and outside "
                    "bypassPermissions mode a call runs only when one does."), True


def record(raw: str, message: str) -> None:
    """REFUSAL-RECORD CALL SITE: lib/refusal_record.report(<payload>, [(<this file>, <deny message>)], <this file>)."""
    try:
        from lib import refusal_record
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
                          f"{exc}); refused rather than asking a person.", True)
    signal.alarm(0)
    if result is None:
        return 0
    behavior, message, own = result
    answer(behavior, message)
    if behavior == "deny" and own:
        sys.path.insert(0, HOOKS)
        record(raw, message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
