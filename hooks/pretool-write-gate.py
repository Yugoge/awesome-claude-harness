#!/usr/bin/env python3
"""PreToolUse (every tool): the write gate, one decision on "may this actor make this write".

It replaces seven parallel hooks (hooks-audit O4) with one process: the rules of
lib/write_gate.RULES run in order, each in its own try (lib/rule_runner), and their
answers combine into one (lib/write_gate.combine): every refusal is reported at once.
The rules are the guards' own files, so each decides exactly as it did alone:
pretool-bash-views-guard.py, pretool-overnight-hook-guard.py, pretool-tool-policy.py,
pretool-cp-state-write-guard.py, lib/write_gate/overwrite.py (pretool-write-guard.sh's
checks) and pretool-claude-config-guard.py.

If the gate's own code fails (loading the rule table, or the runner around a rule), it runs
each rule the call matches as a separate process, as the CLI ran them, so a fault here
neither refuses every tool nor skips tool-policy's fail-closed check.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))


def _tool(raw: bytes):
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data.get("tool_name") if isinstance(data, dict) else None


def _fallback(raw: bytes) -> int:
    """Run each matching rule as its own process and combine the answers."""
    sys.path.insert(0, HOOKS_DIR)
    from lib.rule_runner import RuleRun
    from lib.write_gate import RULES, combine
    tool = _tool(raw)
    results = []
    for rule in RULES:
        if not rule.applies(tool):
            continue
        try:
            proc = subprocess.run([sys.executable, rule.file], input=raw, capture_output=True,
                                  timeout=rule.budget)
            results.append((rule, RuleRun(proc.returncode, proc.stdout.decode("utf-8", "replace"),
                                          proc.stderr.decode("utf-8", "replace"))))
        except subprocess.TimeoutExpired:
            results.append((rule, RuleRun(1, "", "", error=f"ran past its {rule.budget:g} s budget", overrun=True)))
        except Exception as exc:
            results.append((rule, RuleRun(1, "", "", error=f"{type(exc).__name__}: {exc}")))
    return _emit(combine(results))


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
        from lib.rule_runner import run_rule
        from lib.write_gate import RULES, combine
        tool = _tool(raw)
        rules = [rule for rule in RULES if rule.applies(tool)]
        # A rule's own failure is in its RuleRun; an exception here is the runner's, and
        # would otherwise end the gate with exit 1, which the CLI lets through.
        results = [(rule, run_rule(rule.file, raw, rule.budget)) for rule in rules]
    except Exception:
        return _fallback(raw)
    return _emit(combine(results))


if __name__ == "__main__":
    status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)
