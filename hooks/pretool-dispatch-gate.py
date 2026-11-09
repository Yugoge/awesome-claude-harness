#!/usr/bin/env python3
"""PreToolUse (Agent): the dispatch gate, one process for the rules that decide a dispatch.

The rules run in this order, each as its own hook would run alone (its switch, its
exemptions, its failure direction; hooks/lib/gate_runner.py):

1. pretool-subagent-enforce.py: inside /dev-overnight, the dispatch is one the
   cycle contract allows at the current step;
2. pretool-aggregate-check.py (G3): a QA dispatch finds its canonical aggregate,
   and a family's earlier stages left their artifacts;
3. pretool-gitignore-preflight.py: no dev report the dispatch names declares a
   gitignored deliverable (the one decider of that fact);
4. pretool-obligation-gate.py (G1): the dispatch's obligation block is valid, and
   the producer it waits for has returned;
5. consulted, not decided here: the hooks that refuse an Agent call from their own
   registration (pretool-block-background-tasks.py, pretool-do-block-subagents.py,
   pretool-spec-block-foreground-agent.py, pretool-workflow-gate.py). The gate runs
   each only to learn whether it refuses this call; it reports nothing for them;
6. pretool-commit-dispatch-attest.py, the witness: a changelog-analyst dispatch is
   recorded only when no rule above refused it and no consulted hook would, so the
   record never witnesses a dispatch that was refused. It never blocks.

When rules refuse, their reasons are reported together, once, with exit 2.
"""
from __future__ import annotations

import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS))

from lib.gate_runner import CONSULT, REFUSE, WITNESS, Rule, main  # noqa: E402

RULES = [
    Rule("overnight-contract", str(HOOKS / "pretool-subagent-enforce.py"), REFUSE),
    Rule("g3-aggregate", str(HOOKS / "pretool-aggregate-check.py"), REFUSE),
    Rule("gitignore-preflight", str(HOOKS / "pretool-gitignore-preflight.py"), REFUSE),
    Rule("g1-obligation", str(HOOKS / "pretool-obligation-gate.py"), REFUSE),
    Rule("background-dispatch", str(HOOKS / "pretool-block-background-tasks.py"), CONSULT),
    Rule("do-no-dispatch", str(HOOKS / "pretool-do-block-subagents.py"), CONSULT),
    Rule("spec-window", str(HOOKS / "pretool-spec-block-foreground-agent.py"), CONSULT),
    Rule("checklist-started", str(HOOKS / "pretool-workflow-gate.py"), CONSULT),
    Rule("commit-dispatch-witness", str(HOOKS / "pretool-commit-dispatch-attest.py"), WITNESS),
]

if __name__ == "__main__":
    sys.exit(main(RULES))
