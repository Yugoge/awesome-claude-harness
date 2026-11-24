"""The register of accepted deciding reads: rule (6) violations a stated reason accepts.

policies/artifact-check-accepted-reads.v1.json, tracked in the tree under test, built like the register of
look-alike definitions (policies/definition-lookalikes.v1.json). Each entry names a position at which an
artifact may be read to decide: the artifact (its key in the map) and the hook event and tool of the call,
and carries a reason, required. A 6-move or 6-recheck violation on that artifact is covered when every
decision it reports was taken at a position an entry on that artifact names, whichever reader the check names (a merged
gate's change is charged to its refusing rules that read the path) and whichever mutation it measured. Nothing else is coverable: a
violation of rules 1, 2, 4, 5, 7 or 8 is reported whatever the register holds.

Several entries may cover one violation together, one per position (a read measured at the stops of a dev, a qa
and a spec: three entries). Why: what the register accepts is a position with its reason, and a violation is
measured at every position its decisions were taken; requiring one entry to equal all of them made a read at
several accepted positions uncoverable, though each position carries its own reason. A decision at a
position no entry names still leaves the violation reported, and each entry is still stale on its own.

A position at an event whose call carries no tool (TOOLLESS: Stop, UserPromptSubmit; their payload names no
tool or agent type, so the check's position there is (event, "")) is named by that event and an empty tool,
"tool": "". Why: a read at such an event could not be named at all while every entry needed a tool, so a
read accepted for a stated reason there stayed reported. An empty tool at any other event is still refused
(it would name no one tool's call), and so is a tool at a tool-less event (no call there has one). What is
no longer checked: nothing at another event; at a tool-less event the entry names the event alone.

The register cannot go stale silently: an entry that covers no current violation is a violation of its own
(register-stale), as is an entry that does not parse or carries no reason (register-invalid). The check
reports how many violations the register covers (counts()["register_covered"]), and lists them in the map.
"""
from __future__ import annotations

import json
import os

PATH = os.path.join("policies", "artifact-check-accepted-reads.v1.json")
COVERABLE = ("6-move", "6-recheck")
TOOLLESS = ("Stop", "UserPromptSubmit")  # the events whose call carries no tool or agent type
_KEYS = ("artifact", "event", "tool", "reason")


def _problem(i: int, e) -> str | None:
    """Why entry `i` is refused, or None."""
    if not isinstance(e, dict) or set(e) != set(_KEYS):
        return f"entry {i}: the keys are exactly {', '.join(_KEYS)}"
    if not all(isinstance(e[k], str) for k in _KEYS):
        return f"entry {i}: artifact, event, tool and reason are strings"
    if not all(e[k].strip() for k in ("artifact", "event", "reason")):
        return (f"entry {i}: artifact, event and reason are non-empty strings"
                + (" (an empty reason is refused)" if not e["reason"].strip() else ""))
    if e["event"] in TOOLLESS and e["tool"]:
        return f"entry {i}: {e['event']} carries no tool: its tool is \"\""
    if e["event"] not in TOOLLESS and not e["tool"].strip():
        return f"entry {i}: the tool is a non-empty string at {e['event']} (only {', '.join(TOOLLESS)} carry none)"
    return None


def load(tree: str) -> tuple[list[dict], list[str]]:
    """(entries, problems) of the tree's register; no file: no entries."""
    path = os.path.join(tree, PATH)
    if not os.path.exists(path):
        return [], []
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        return [], [f"{PATH} does not load: {e}"]
    entries = doc.get("entries") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        return [], [f"{PATH} holds no entries list"]
    good, problems = [], []
    for i, e in enumerate(entries):
        why = _problem(i, e)
        if why:
            problems.append(why)
        else:
            good.append(dict(e, index=i))
    return good, problems


def covering(entries: list[dict], v) -> list[dict]:
    """The entries that together cover `v`: one per position of its decisions, each on its artifact; [] when
    a position (or the rule) has none."""
    if v.rule not in COVERABLE or not v.at:
        return []
    out = []
    for at in dict.fromkeys(v.at):
        e = next((e for e in entries if v.artifact == e["artifact"] and at == (e["event"], e["tool"])), None)
        if e is None:
            return []
        out.append(e)
    return out


def apply(vs: list, entries: list[dict], problems: list[str], make) -> tuple[list, list]:
    """(the violations left, the ones covered as (violation, entry); several entries covering one violation
    together appear as one entry whose index and reason join theirs). `make(rule, artifact, message)` builds
    a Violation: the register's own problems and its stale entries are added to those left."""
    left, covered, used = [], [], set()
    for v in vs:
        es = covering(entries, v)
        if not es:
            left.append(v)
            continue
        covered.append((v, es[0] if len(es) == 1 else {
            "artifact": v.artifact, "index": ", ".join(str(e["index"]) for e in es),
            "reason": " | ".join(e["reason"] for e in es)}))
        used.update(e["index"] for e in es)
    left += [make("register-invalid", PATH, p) for p in problems]
    left += [make("register-stale", PATH, f"entry {e['index']} ({e['artifact']} at {e['event']} {e['tool'] or '(no tool)'}) "
                  "covers no current violation: remove it")
             for e in entries if e["index"] not in used]
    return left, covered
