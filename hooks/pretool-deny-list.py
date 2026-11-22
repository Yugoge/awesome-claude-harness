#!/usr/bin/env python3
"""PreToolUse rule: the deny list that was Claude Code's own (settings.json permissions.deny).

The entries are policies/cli-deny.v1.json, matched as the CLI matched them (lib/deny_list.py). A call an entry
refuses is refused here with the entry and its purpose, so the launcher records it and an owner's /allow
releases it like any other refusal. A rule that cannot decide (the list unreadable, a fault in the matcher, no
verdict within DEADLINE) refuses and names the cause: before, the CLI's list held whatever the hooks did.
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

import json
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TAG = "[deny-list]"
# Seconds to a verdict. The launcher treats a rule past its Rule timeout (pretool-launch.py: 10) as a non-blocking
# error and lets the call go on, so this rule refuses at its own, earlier deadline.
DEADLINE = 5.0


class Late(BaseException):
    """The rule's own deadline passed (a BaseException, so no `except Exception` on the way swallows it)."""


def _late(signum, frame):
    raise Late(f"no verdict within {DEADLINE:g} s")


def verdict(payload: dict):
    """(hit or None, None), or (None, the refusal text) when no verdict can be given: each step names its cause."""
    step = "loading its matcher (hooks/lib/deny_list.py)"
    try:
        signal.signal(signal.SIGALRM, _late)
        signal.setitimer(signal.ITIMER_REAL, DEADLINE)
        from lib import deny_list
        step = "reading the list (policies/cli-deny.v1.json and settings.json's permissions.deny)"
        listed = deny_list.entries()
        step = "preparing the list's entries"
        policy = deny_list.Policy(listed=listed)
        step = "matching this call"
        return policy.refusal(payload), None
    except Late as exc:  # cannot decide in time, or at all: refuse, as the CLI's list held regardless
        cause = f"it ran out of time while {step} ({exc})"
    except Exception as exc:  # noqa: BLE001
        cause = f"{step} failed ({type(exc).__name__}: {exc})"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return None, (f"{TAG} BLOCKED: the deny list gave no verdict: {cause}; the call is refused until it can. "
                  "Release: the owner's /allow.\n")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    hit, refusal = verdict(payload)
    if refusal:
        sys.stderr.write(refusal)
        return 2
    if not hit:
        return 0
    tool, entry, purpose = hit
    sys.stderr.write(f"{TAG} BLOCKED: {purpose}. The {tool} call meets the entry {entry} of policies/cli-deny.v1.json "
                     f"(the list that was settings.json's permissions.deny). Release: the owner's /allow.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
