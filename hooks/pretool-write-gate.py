#!/usr/bin/env python3
"""PreToolUse (every tool): the write gate, one decision on "may this actor make this write".

It replaces seven parallel hooks (hooks-audit O4) with one process: the rules of
lib/write_gate.RULES the call matches run, each in its own try (lib/rule_runner), and their
answers combine into one (lib/write_gate.combine), read in rule order: every refusal is
reported at once.
The rules are the guards' own files, so each decides exactly as it did alone:
pretool-bash-views-guard.py, pretool-overnight-hook-guard.py, pretool-tool-policy.py,
pretool-cp-state-write-guard.py, lib/write_gate/overwrite.py (pretool-write-guard.sh's
checks), pretool-claude-config-guard.py and pretool-harness-switch-guard.py.

The rules run at the same time, one fork of this process each (lib/rule_fork), as the CLI
ran the seven guards: the call waits for the slowest rule, not for their sum. No rule writes
anything another reads, so none waits for another. Each fork keeps its rule's budget (the gate
sends the overrun signal at its deadline and ends a fork still running after a grace), so a
rule that errors, overruns, dies or exits early fails in its own direction (tool-policy's
closed one refuses) and the others' answers stand; combine() reads the results in rule order
whatever order they ended in, so the gate prints byte for byte what the one-after-another run
prints. Where this process cannot fork safely (no os.fork, another thread alive, a runner's
watchdog thread running: lib/rule_fork.can_fork), one rule matches or the tool is one of
ONE_AFTER_ANOTHER (Bash, whose call waits for a slower shell hook anyway), they run one after
another in this process, as before; a fork that cannot be made runs its rule as its own process.

If the gate's own code fails (loading the rule table, or the runner around a rule), it runs
each rule the call matches as a separate process, as the CLI ran them, so a fault here
neither refuses every tool nor skips tool-policy's fail-closed check.
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
import subprocess
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
# The standard-library modules lib/hook_launch.py imports before its forks (its WARM, which says why
# that changes nothing a hook decides): pkgutil is the runner's own (runpy.run_path imports it for
# every file), so without it each fork would import it again. Never a harness module.
WARM = ("pkgutil", "pathlib", "datetime", "shlex")
# The tools whose rules run one after another even where the gate may fork. Bash: its call waits
# for pretool-bash-safety.sh (about 470 ms, a shell registration of its own) whatever the gate
# does, so forking its six rules saved no wait and cost about 30 ms CPU a call (measured with
# tests/replay/launch_cost.py, eight invocations each way).
ONE_AFTER_ANOTHER = frozenset({"Bash"})


def _tool(raw: bytes):
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data.get("tool_name") if isinstance(data, dict) else None


def _fallback(raw: bytes) -> int:
    """Run each matching rule as its own process and combine the answers."""
    sys.path.insert(0, HOOKS_DIR)
    from lib.write_gate import RULES, combine
    tool = _tool(raw)
    return _emit(combine([(rule, _own_process(rule, raw)) for rule in RULES if rule.applies(tool)]))


def _own_process(rule, raw: bytes):
    """The rule as its own process, as the CLI ran its guard."""
    from lib.rule_runner import RuleRun
    try:
        proc = subprocess.run([sys.executable, rule.file], input=raw, capture_output=True,
                              timeout=rule.budget)
        return RuleRun(proc.returncode, proc.stdout.decode("utf-8", "replace"),
                       proc.stderr.decode("utf-8", "replace"))
    except subprocess.TimeoutExpired:
        return RuleRun(1, "", "", error=f"ran past its {rule.budget:g} s budget", overrun=True)
    except Exception as exc:
        return RuleRun(1, "", "", error=f"{type(exc).__name__}: {exc}")


def _runs(rules, raw: bytes, tool=None) -> list:
    """(rule, RuleRun) of every rule, in rule order: at the same time, one fork each
    (lib/rule_fork), where this process may fork and ``tool`` is not one of ONE_AFTER_ANOTHER;
    else one after another in this process."""
    from lib.rule_runner import run_rule
    if len(rules) > 1 and tool not in ONE_AFTER_ANOTHER:
        try:
            from lib import rule_fork
            at_once = rule_fork.can_fork()
            for name in WARM if at_once else ():
                __import__(name)
        except Exception:
            at_once = False
        if at_once:
            jobs = [rule_fork.Job(rule.file, raw, rule.budget) for rule in rules]
            runs = rule_fork.run_at_once(jobs, fallback=lambda i: _own_process(rules[i], raw))
            return list(zip(rules, runs))
    return [(rule, run_rule(rule.file, raw, rule.budget)) for rule in rules]


def _emit(answer) -> int:
    if answer.stdout:
        sys.stdout.write(answer.stdout)
    if answer.stderr:
        sys.stderr.write(answer.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    return answer.code


def main() -> int:
    raw = sys.stdin.buffer.read()
    try:
        sys.path.insert(0, HOOKS_DIR)
        from lib.write_gate import RULES, combine
        tool = _tool(raw)
        rules = [rule for rule in RULES if rule.applies(tool)]
        # A rule's own failure is in its RuleRun; an exception here is the runner's, and
        # would otherwise end the gate with exit 1, which the CLI lets through.
        results = _runs(rules, raw, tool)
    except Exception:
        return _fallback(raw)
    return _emit(combine(results))


if __name__ == "__main__":
    status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)
