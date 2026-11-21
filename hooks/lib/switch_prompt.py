"""What types /harness: the harness switch's text matching and refusal, for its two write-gate rules.

A delivered or scheduled prompt reaches UserPromptSubmit as if the owner had typed it, so a prompt that
types /harness would switch the harness. hooks/pretool-harness-switch-guard.py (Bash, the file-writing
tools, Skill and SlashCommand) refuses a Bash command that types it into a Claude Code session the command
starts (TYPED); hooks/pretool-harness-switch-prompt.py (every other tool but the CLI's own that deliver no
prompt, harness_switch.NO_PROMPT) refuses an input that carries such a prompt (prompt_refusal).
"""
import re
import sys

try:
    from . import harness_switch
    from .subagent import DISPATCH_TOOLS
except ImportError:  # hooks/lib itself is on sys.path
    import harness_switch
    from subagent import DISPATCH_TOOLS

TYPED = re.compile(r"(?:^|[\s\"'`(])/harness(?:\s+(?:%s)\b|\s*$|[\s\"'`)])" % "|".join(harness_switch.VERBS), re.M)
TAGGED = r"<command-name>/?harness</command-name>"  # the other form scripts/harness-switch reads (parse_prompt)
PROMPT = re.compile(TYPED.pattern + "|" + TAGGED, re.M)  # a prompt that types /harness, anywhere in it
WHOLE = re.compile(r"\s*(?:/harness(?:\s+\S+)?|(?:<command-message>.*?</command-message>\s*)?" + TAGGED + r".*)\s*",
                   re.S)  # a prompt that is the command, as scripts/harness-switch acts on one
OWNER_SWITCHES = ("Only the owner switches the harness, by typing /harness off or /harness on; nothing an "
                  "agent runs, writes or schedules does")


def refuse(what: str, owner: str = OWNER_SWITCHES) -> int:
    sys.stderr.write("BLOCKED: harness-switch: %s. %s.\n" % (what, owner))
    return 2


def prompt_refusal(tool: str, ti) -> str | None:
    """Why `tool`'s input `ti` is refused: a string under any key at any depth that types /harness (for
    Agent / Task, a string that is the command); None for a tool of NO_PROMPT and an input that types none."""
    if tool in harness_switch.NO_PROMPT:
        return None
    typed = WHOLE.fullmatch if tool in DISPATCH_TOOLS else PROMPT.search
    stack = [ti]
    while stack:
        value = stack.pop()
        if isinstance(value, str) and typed(value):
            return "this %s carries a prompt that types /harness" % tool
        stack.extend(value.values() if isinstance(value, dict) else value if isinstance(value, list) else ())
    return None
