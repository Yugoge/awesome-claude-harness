#!/usr/bin/env python3
"""PreToolUse (Bash), every caller: the merge-analyst's verdict decides whether /merge's wrapper runs.

A Bash call that runs this harness's hooks/merge.sh exits 2 unless it is /merge Step 5's call as
merge.md writes it (stop-command-gate.step5_call) inside a /merge the owner typed, and this
session's newest merge-analyst grant for the repository since that opener passes
lib/merge_grant.approval: verdict `approved`, unexpired, both tips live, its `branch` the call's
ref. merge.sh runs git merge in its own process, which no hook sees, so this is where the verdict
holds (Steps 3-4 of merge.md, which were prose). Recorded and released by /allow as every refusal
of pretool-launch.py's chain is.
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import importlib.util
import json
import subprocess

HOOKS = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HOOKS)
WRAPPER = os.path.join(HOOKS, "merge.sh")


def _runs_wrapper(command: str, cwd: str) -> bool:
    """A shell site of ``command`` runs merge.sh: as its command word, or as a shell's script operand;
    an operand the parser cannot read (an expansion) in a command that names merge.sh counts."""
    from lib import shell_parse
    script = shell_parse.parse(command)
    if script.error is not None:
        return True
    for site in shell_parse.walk(script):
        resolved = shell_parse.resolve(site.cmd)
        argv, head = resolved.argv(), resolved.head.value() if resolved.head is not None else None
        if resolved.name in ("bash", "sh", "dash", "zsh", "source", "."):
            head = next((a for a in argv if a is None or not a.startswith(shell_parse.OPTION_SIGNS)), "")
        if head is None:
            return True
        if head and os.path.realpath(os.path.join(cwd, os.path.expanduser(head))) == os.path.realpath(WRAPPER):
            return True
    return False


def refusal(data: dict) -> str:
    command = str((data.get("tool_input") or {}).get("command") or "")
    cwd = data.get("cwd") or os.getcwd()
    if "merge.sh" not in command or not _runs_wrapper(command, cwd):
        return ""
    from lib import command_span, merge_grant
    span = command_span.active_span(data["transcript_path"]) if data.get("transcript_path") else None
    since = span.opened_at() if span is not None and span.command == "merge" else None
    if since is None:
        return "merge.sh runs only inside a /merge the owner typed (no /merge opener in this session)"
    from lib import locations
    top = locations.repo_top(cwd) or cwd  # a repository at the filesystem root is no repository
    grant, why = merge_grant.approval(top, str(data.get("session_id") or ""), int(since))
    if why:
        return why
    spec = importlib.util.spec_from_file_location("_stop_command_gate", os.path.join(HOOKS, "stop-command-gate.py"))
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    if not gate.step5_call(command, gate.MERGE_CALL, grant.get("branch")):
        return (f"the call is not /merge Step 5's `bash \"<HARNESS_ROOT>/hooks/merge.sh\" [--no-commit] "
                f"{grant.get('branch')}`, alone, with the approved grant's branch")
    return ""


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    why = refusal(data)
    if not why:
        return 0
    sys.stderr.write(f"BLOCKED: merge.sh without the merge-analyst's approval - {why}.\n"
                     "Action: run /merge Steps 1-4 again for a fresh grant; on `blocked`, report its risks "
                     "and do not merge.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
