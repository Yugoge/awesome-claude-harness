"""FROZEN REFERENCE, NOT PRODUCTION CODE: `combine` of hooks/lib/write_gate/__init__.py
copied verbatim as it stood at commit cc22f78, before it was split into helpers.

tests/differential/test_combine_differential.py runs this copy and the live `combine` on the
same inputs and asserts identical answers. Nothing else may import it, and it is never edited:
it is what "no behaviour change" is measured against. The helpers it calls (`Answer`, `_json`,
`_decision`) were not changed by that refactor and are imported from the live module, which
the test puts on the import path (hooks/).
"""
from __future__ import annotations

import json

from lib.write_gate import Answer, _decision, _json


def combine(results) -> Answer:
    """``results``: (Rule, RuleRun) pairs in rule order -> the gate's one answer."""
    refusals, asks, defers, allows, contexts, user_errors = [], [], [], [], [], []
    updated = None
    for rule, run in results:
        if run.error:
            note = f"write gate: rule {rule.name} {run.error}"
            if rule.fail == "closed":
                refusals.append(f"{note}; this rule fails closed, so the call is refused. Retry it; "
                                f"if it repeats, report the rule and this message.\n")
            else:
                user_errors.append(f"{note}; this rule fails open, so it did not decide this call.\n")
            continue
        out = _json(run.stdout) if run.code in (0, 2) else None
        decision, reason = _decision(out) if out else (None, "")
        if run.code == 2:
            refusals.append(reason or run.stderr)
            continue
        if run.code != 0:
            if run.stderr:
                user_errors.append(run.stderr)
            continue
        if not out:
            continue
        hso = out.get("hookSpecificOutput") if isinstance(out.get("hookSpecificOutput"), dict) else {}
        if decision == "deny":
            refusals.append(reason or run.stderr)
            continue
        if decision == "ask":
            asks.append(reason)
        elif decision == "defer":
            defers.append(reason)
        elif decision == "allow":
            allows.append(reason)
        if isinstance(hso.get("updatedInput"), dict) and updated is None:
            updated = hso["updatedInput"]
        if hso.get("additionalContext"):
            contexts.append(str(hso["additionalContext"]))

    if refusals:
        text = "".join(r if r.endswith("\n") else r + "\n" for r in refusals if r)
        return Answer(2, "", text)
    spec: dict = {}
    if defers or asks:
        spec["permissionDecision"] = "defer" if defers else "ask"
        spec["permissionDecisionReason"] = "\n".join(r for r in (defers or asks) if r)
    elif allows:
        spec["permissionDecision"] = "allow"
        spec["permissionDecisionReason"] = "\n".join(r for r in allows if r)
    if updated is not None:
        spec["updatedInput"] = updated
    if contexts:
        spec["additionalContext"] = "\n".join(contexts)
    if spec:
        return Answer(0, json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **spec}}),
                      "".join(user_errors))
    if user_errors:
        return Answer(1, "", "".join(user_errors))
    return Answer(0)
