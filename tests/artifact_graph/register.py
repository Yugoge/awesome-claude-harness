"""The register of accepted deciding reads: rule (6) violations a stated reason accepts.

policies/artifact-check-accepted-reads.v1.json, tracked in the tree under test, built like the register of
look-alike definitions (policies/definition-lookalikes.v1.json). Each entry names a deciding read: the
artifact (its key in the map), the reader (the component the violation names), the position (the hook event
and the tool of the call it decides) and the mutations it decides on, and carries a reason, required. A
6-move or 6-recheck violation is covered when an entry names its artifact, its reader and its mutation and
every decision the violation reports was taken at the entry's event and tool. Nothing else is coverable: a
violation of rules 1, 2, 4, 5, 7 or 8 is reported whatever the register holds.

The register cannot go stale silently: an entry that covers no current violation is a violation of its own
(register-stale), as is an entry that does not parse or carries no reason (register-invalid). The check
reports how many violations the register covers (counts()["register_covered"]), and lists them in the map.
"""
from __future__ import annotations

import json
import os

PATH = os.path.join("policies", "artifact-check-accepted-reads.v1.json")
COVERABLE = ("6-move", "6-recheck")
MUTATIONS = ("removed", "invalid", "any", "unreadable")
_KEYS = ("artifact", "reader", "event", "tool", "mutations", "reason")


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
        if not isinstance(e, dict) or set(e) != set(_KEYS):
            problems.append(f"entry {i}: the keys are exactly {', '.join(_KEYS)}")
        elif not all(isinstance(e[k], str) and e[k].strip() for k in _KEYS if k != "mutations"):
            problems.append(f"entry {i}: artifact, reader, event, tool and reason are non-empty strings"
                            + (" (an empty reason is refused)" if not str(e.get("reason") or "").strip() else ""))
        elif not (isinstance(e["mutations"], list) and e["mutations"] and set(e["mutations"]) <= set(MUTATIONS)):
            problems.append(f"entry {i}: mutations is a non-empty list of {', '.join(MUTATIONS)}")
        else:
            good.append(dict(e, index=i))
    return good, problems


def covers(e: dict, v) -> bool:
    return (v.rule in COVERABLE and v.artifact == e["artifact"] and v.reader == e["reader"]
            and v.how in e["mutations"] and bool(v.at) and all(at == (e["event"], e["tool"]) for at in v.at))


def apply(vs: list, entries: list[dict], problems: list[str], make) -> tuple[list, list]:
    """(the violations left, the ones covered as (violation, entry)). `make(rule, artifact, message)` builds a
    Violation: the register's own problems and its stale entries are added to those left."""
    left, covered, used = [], [], set()
    for v in vs:
        e = next((e for e in entries if covers(e, v)), None)
        if e is None:
            left.append(v)
        else:
            covered.append((v, e))
            used.add(e["index"])
    left += [make("register-invalid", PATH, p) for p in problems]
    left += [make("register-stale", PATH, f"entry {e['index']} ({e['reader']} on {e['artifact']}, {e['event']} "
                  f"{e['tool']}, {'/'.join(e['mutations'])}) covers no current violation: remove it")
             for e in entries if e["index"] not in used]
    return left, covered
