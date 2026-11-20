"""The register of accepted deciding reads: rule (6) violations a stated reason accepts.

policies/artifact-check-accepted-reads.v1.json, tracked in the tree under test, built like the register of
look-alike definitions (policies/definition-lookalikes.v1.json). Each entry names a position at which an
artifact may be read to decide: the artifact (its key in the map) and the hook event and tool of the call,
and carries a reason, required. A 6-move or 6-recheck violation on that artifact is covered when every
decision it reports was taken at the entry's event and tool, whichever reader the check names (a merged
gate's change is charged to its refusing rules that read the path) and whichever mutation it measured. Nothing else is coverable: a
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
_KEYS = ("artifact", "event", "tool", "reason")


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
        elif not all(isinstance(e[k], str) and e[k].strip() for k in _KEYS):
            problems.append(f"entry {i}: artifact, event, tool and reason are non-empty strings"
                            + (" (an empty reason is refused)" if not str(e.get("reason") or "").strip() else ""))
        else:
            good.append(dict(e, index=i))
    return good, problems


def covers(e: dict, v) -> bool:
    return (v.rule in COVERABLE and v.artifact == e["artifact"] and bool(v.at)
            and all(at == (e["event"], e["tool"]) for at in v.at))


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
    left += [make("register-stale", PATH, f"entry {e['index']} ({e['artifact']} at {e['event']} {e['tool']}) "
                  "covers no current violation: remove it")
             for e in entries if e["index"] not in used]
    return left, covered
