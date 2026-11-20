#!/usr/bin/env python3
"""PreToolUse (a rule of hooks/pretool-write-gate.py): no tool carries a prompt that types /harness.

Every tool but Bash, the file-writing tools, Skill and SlashCommand (hooks/pretool-harness-switch-guard.py
judges those) and the CLI's own that deliver no prompt (harness_switch.NO_PROMPT, which pass): a string of
its input, under any key at any depth, that types /harness is refused, whatever the tool's name, since a
delivered or scheduled prompt reaches UserPromptSubmit as if the owner typed it; Agent / Task is refused
only where a string is the command (hooks/lib/switch_prompt.prompt_refusal). No exemption: only the owner
switches the harness. While the harness is off this rule does not run either.
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib")); import harness_switch; sys.path.pop(0)  # noqa: E402,E702
harness_switch.exit_if_off()

import json  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
import switch_prompt  # noqa: E402 -- what types /harness, the guard's matching too
sys.path.pop(0)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    ti = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    why = switch_prompt.prompt_refusal(data.get("tool_name") or "", ti)
    return switch_prompt.refuse(why) if why else 0


if __name__ == "__main__":
    sys.exit(main())
