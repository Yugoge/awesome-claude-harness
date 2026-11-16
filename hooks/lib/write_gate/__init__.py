"""The write gate's rules and how their answers combine (hooks/pretool-write-gate.py).

One fact, "may this actor make this write", was decided by seven PreToolUse hooks that
ran in parallel (hooks-audit O4). The gate runs their rules in one process, in the
order below, each in its own try (lib/rule_runner), and gives the CLI one answer.

Each rule declares:
- ``tools``: the tool names it sees (its old matcher; None = every tool). The gate is
  registered on every tool and dispatches here by ``tool_name``, so a matcher typo can
  no longer silence a rule (the posttool-git-warn lesson).
- ``actors``: whom its code governs: "main", "subagent" or "both". The gate does not
  skip on it; hooks/tests/test_write_gate.py proves each declaration on the rule's own
  refusing input.
- ``fail``: what an error the rule's own handlers did not catch, or an overrun of its
  budget, means: "open" (the call goes on, as a crashed or timed-out hook let it) or
  "closed" (refused: WS1, tool-policy's import failure blocks).
- ``exemptions``: what lets the rule allow a call it would otherwise refuse. Each rule
  checks its own; the gate grants none (no consent check at the gate's entry).
- ``budget``: seconds, measured (test_write_gate.py::test_budgets_cover_the_measured_times).

Combining, as the CLI combines parallel hooks (code.claude.com/docs/en/hooks,
PreToolUse decision control: deny > defer > ask > allow):
- any refusal (exit 2, or a ``deny`` decision) -> exit 2 with every refusal's reason,
  in rule order, so one call reports every rule it breaks;
- else ``defer`` or ``ask`` -> that decision as JSON, with the rules' reasons;
- else a rule's ``allow``, ``updatedInput`` or ``additionalContext`` -> JSON carrying it;
- a rule's other non-zero status is a non-blocking error: its stderr goes to the user
  (exit 1) when nothing else is printed, as it did alone.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# A rule module this package holds is named by import, not by a path string: the gate loads it
# (it runs it as __main__), and the import states that, as the artifact check reads code. Its
# reads then sit at its caller's position (a library's), not at a file nothing runs.
# A module that cannot be imported must not stop this table from loading: then the gate would
# exit 1 and the CLI would skip every rule, tool-policy's fail-closed one included. The same
# path is kept, so the broken rule fails alone, in its own direction, when the runner runs it.
try:
    from . import overwrite as _overwrite
    _OVERWRITE = os.path.relpath(os.path.abspath(_overwrite.__file__), HOOKS_DIR)
except Exception:
    _OVERWRITE = os.path.join("lib", "write_gate", "overwrite.py")

WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})


@dataclass(frozen=True)
class Rule:
    name: str
    path: str                      # relative to hooks/
    tools: frozenset | None        # None: every tool
    actors: str                    # "main" | "subagent" | "both"
    fail: str                      # "open" | "closed"
    exemptions: tuple
    budget: float                  # seconds

    def applies(self, tool: str | None) -> bool:
        return self.tools is None or tool is None or tool in self.tools

    @property
    def file(self) -> str:
        return os.path.join(HOOKS_DIR, self.path)


RULES: tuple[Rule, ...] = (
    Rule("bash-views", "pretool-bash-views-guard.py", frozenset({"Bash"}), "both", "open",
         ("a command that runs scripts/spec-check.py, the cp-state writer",), 5.0),
    Rule("overnight-boundary", "pretool-overnight-hook-guard.py",
         frozenset({"Write", "Edit", "MultiEdit", "Bash", "AskUserQuestion"}), "both", "open",
         ("outside a live /dev-overnight session the rule allows everything",
          "no /do and no /allow exemption: the overnight self-repair boundary holds for both"), 20.0),
    Rule("tool-policy", "pretool-tool-policy.py", None, "both", "closed",
         ("the main agent passes the role rows once the derived write permission allows it",
          "the declaring dispatch's own write of a path it declares"), 20.0),
    Rule("cp-state", "pretool-cp-state-write-guard.py", WRITE_TOOLS | {"Bash"}, "subagent", "open",
         ("the main agent is not governed", "scripts/spec-check.py, the one cp-state writer"), 5.0),
    Rule("overwrite", _OVERWRITE, frozenset({"Write"}), "both", "open",
         ("/do consent (main agent; not for the bulk-commit sentinel)",
          "an /allow grant naming the target (main agent; not for the bulk-commit sentinel)"), 5.0),
    Rule("claude-config", "pretool-claude-config-guard.py", frozenset({"Edit", "Write", "MultiEdit", "Bash"}),
         "both", "open",
         ("the project's .claude/.hook-refactor-allow sentinel, made by hand",
          "/dev-command's dev writing the project command file its cycle develops"), 5.0),
    Rule("harness-switch", "pretool-harness-switch-guard.py",
         WRITE_TOOLS | {"Bash", "Skill", "SlashCommand", "CronCreate", "ScheduleWakeup", "SendMessage"},
         "both", "open",
         ("reading the switch's state or settings files",
          "the project's .claude/.hook-refactor-allow sentinel, made by hand, for the home's settings files"),
         5.0),
)


@dataclass
class Answer:
    code: int
    stdout: str = ""
    stderr: str = ""


def _json(text: str):
    text = text.strip()
    if not text.startswith("{"):
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _decision(out: dict) -> tuple[str | None, str]:
    """(decision, reason) a rule's JSON carries: deny / defer / ask / allow, or None."""
    hso = out.get("hookSpecificOutput")
    hso = hso if isinstance(hso, dict) else {}
    decision = hso.get("permissionDecision")
    reason = hso.get("permissionDecisionReason") or ""
    if decision is None and out.get("decision") in ("block", "approve"):  # the deprecated form
        decision = "deny" if out["decision"] == "block" else "allow"
        reason = out.get("reason") or ""
    return (decision if decision in ("deny", "defer", "ask", "allow") else None), str(reason)


@dataclass
class _Tally:
    """What the rules said so far, sorted by what it does to the gate's answer."""
    refusals: list = field(default_factory=list)
    asks: list = field(default_factory=list)
    defers: list = field(default_factory=list)
    allows: list = field(default_factory=list)
    contexts: list = field(default_factory=list)
    user_errors: list = field(default_factory=list)
    updated: dict | None = None  # the first rule's updatedInput wins


def _tally_error(tally: _Tally, rule, error) -> None:
    """A rule that raised past its handlers or overran: refused if it fails closed, else noted."""
    note = f"write gate: rule {rule.name} {error}"
    if rule.fail == "closed":
        tally.refusals.append(f"{note}; this rule fails closed, so the call is refused. Retry it; "
                              f"if it repeats, report the rule and this message.\n")
    else:
        tally.user_errors.append(f"{note}; this rule fails open, so it did not decide this call.\n")


def _tally_output(tally: _Tally, out: dict, decision: str | None, reason: str) -> None:
    """A rule's exit-0 JSON that does not deny: its decision, updated input and context."""
    bucket = {"ask": tally.asks, "defer": tally.defers, "allow": tally.allows}.get(decision)
    if bucket is not None:
        bucket.append(reason)
    hso = out.get("hookSpecificOutput") if isinstance(out.get("hookSpecificOutput"), dict) else {}
    if isinstance(hso.get("updatedInput"), dict) and tally.updated is None:
        tally.updated = hso["updatedInput"]
    if hso.get("additionalContext"):
        tally.contexts.append(str(hso["additionalContext"]))


def _tally_run(tally: _Tally, rule, run) -> None:
    """One rule's run into the tally. Exit 2 or a deny refuses; another non-zero exit is a
    non-blocking error (its stderr, if any); exit 0 with JSON may decide, update or add context."""
    if run.error:
        _tally_error(tally, rule, run.error)
        return
    if run.code not in (0, 2):
        if run.stderr:
            tally.user_errors.append(run.stderr)
        return
    out = _json(run.stdout)
    decision, reason = _decision(out) if out else (None, "")
    if run.code == 2 or decision == "deny":
        tally.refusals.append(reason or run.stderr)
    elif out:
        _tally_output(tally, out, decision, reason)


def _spec(tally: _Tally) -> dict:
    """The hookSpecificOutput fields the tally carries: defer > ask > allow, then input and context."""
    spec: dict = {}
    if tally.defers or tally.asks:
        spec["permissionDecision"] = "defer" if tally.defers else "ask"
        spec["permissionDecisionReason"] = "\n".join(r for r in (tally.defers or tally.asks) if r)
    elif tally.allows:
        spec["permissionDecision"] = "allow"
        spec["permissionDecisionReason"] = "\n".join(r for r in tally.allows if r)
    if tally.updated is not None:
        spec["updatedInput"] = tally.updated
    if tally.contexts:
        spec["additionalContext"] = "\n".join(tally.contexts)
    return spec


def combine(results) -> Answer:
    """``results``: (Rule, RuleRun) pairs in rule order -> the gate's one answer."""
    tally = _Tally()
    for rule, run in results:
        _tally_run(tally, rule, run)
    if tally.refusals:
        text = "".join(r if r.endswith("\n") else r + "\n" for r in tally.refusals if r)
        return Answer(2, "", text)
    spec = _spec(tally)
    if spec:
        return Answer(0, json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **spec}}),
                      "".join(tally.user_errors))
    if tally.user_errors:
        return Answer(1, "", "".join(tally.user_errors))
    return Answer(0)
