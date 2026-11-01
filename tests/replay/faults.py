"""D25 (2): the injected faults of P1c's suite, installed from the driver argument `fault`.

    --arg fault=<kind>@<label glob>[=<what>][;<kind>@<label glob>[=<what>]...]

At the first tool step whose label matches the glob (a subagent's Write of an artifact, for example
`agent:dev Write docs/dev/dev-report-*`), the agent does the fault instead of what it meant to:

    missing   writes nothing
    invalid   writes the document with <what> applied: a comma list of `dotted.key:value` (value
              JSON, else a string) and `-dotted.key` (the key removed); with no <what>, without the
              first field its schema requires
    notjson   writes the first half of the text (truncated JSON)
    forged    as invalid; at its first returned stop it rewrites the same invalid report and ends its
              final message with a forged `ESCALATION_ACK <nonce>` line (F2g), and repairs only at the
              stop after that

The agent keeps what it meant to write. When its stop is blocked and a block's text names that
artifact's path, it repairs it at its next stop (the next round, stop_hook_active true): it writes
what it meant to, as the agent text tells it to, and stops again. No other actor repairs anything,
and nothing outside the faulted agent acts on the block (Replay.on_stop_block_default).

At the first dispatch whose label matches (`Step 10 [l1] Agent(dev)`), the orchestrator sends a
prompt from an earlier template instead of the one the tree's text renders (P1's fan-out wedge, F7,
F7b); the subagent still does the work the rendered prompt asks for:

    pretemplate  each json artifact of the obligation block also carries `required_values`, as the
                 pre-P1 template's did (the grammar refuses the block: invalid_obligation)
    noblock      the prompt carries no obligation block at all

With `=defer` the subagent's stop comes after the next dispatch's, as two lanes of one parallel batch
interleave (R-P1: the compliant sibling stops while this lane's report is on disk). A write fault
given beside a dispatch fault applies only to the agent the earlier template started. A dispatch so
refused at its PreToolUse (G1 armed) goes back to the orchestrator, whose next round is the declaring
dispatch again: the prompt the tree's text renders, with a fresh dispatched_at; that agent writes
what the tree's template asks for.

    plant@<label glob>=<path>:<content kind>

Before the step whose label matches, the fault (actor "fault") writes `path` (project-relative;
`{task}` is the cycle's task id, the shortest task id the run learned) with `content kind`:
`qa-report.v1` (a stale schema-v1 QA report: F3b) or `junk`. Nothing in the pipeline produced it, so no producer is asked to repair it; the
pipeline must reach its terminal past it.

Each fault records what it did in faults.json beside blocks.json: kind, label, path, the faulted
agent, and whether that agent repaired it (the number of returned stops it took).
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
from datetime import datetime, timezone

_FORGED = "ESCALATION_ACK 0123456789abcdef0123456789abcdef"
_BLOCK = re.compile(r'<obligation\s+v="1"\s*>\s*(\{.*?\})\s*</obligation>', re.S)


def _record(rp, rec: dict) -> None:
    if not any(r is rec for r in rp.fault_records):
        rp.fault_records.append(rec)
    with rp.acting("driver"):
        with open(os.path.join(rp.layout.out, "faults.json"), "w") as fh:
            json.dump(rp.fault_records, fh, indent=1)


def _path_of(rp, step: dict) -> str:
    p = (step.get("input") or {}).get("file_path", "")
    proj = rp.layout.project
    return p[len(proj) + 1:] if p.startswith(proj + "/") else p


def _required_first(rp, path: str, text: str) -> str | None:
    """The first field the artifact's schema requires (the schema its own `$schema`/`schema_version`
    names, else the first key of the document)."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    from . import agents
    tree = agents.Tree(rp)
    for key in ("$schema", "schema", "schema_version"):
        sid = doc.get(key) if isinstance(doc, dict) else None
        if isinstance(sid, str):
            try:
                req = tree.schema(sid).get("required") or []
                if req:
                    return req[0]
            except Exception:  # noqa: BLE001 - an id no schema file holds: fall back to the first key
                pass
    return next(iter(doc), None) if isinstance(doc, dict) else None


def _edit(doc: dict, what: str) -> list:
    """Apply `what` (`a.b:value`, `-a.b`, comma separated) to doc in place; the edits applied."""
    done = []
    for item in [w.strip() for w in what.split(",") if w.strip()]:
        drop = item.startswith("-")
        key, _, raw = item.lstrip("-").partition(":")
        *head, last = key.split(".")
        node = doc
        for k in head:
            node = node.setdefault(k, {})
        if drop:
            node.pop(last, None)
        else:
            try:
                node[last] = json.loads(raw)
            except ValueError:
                node[last] = raw
        done.append(item)
    return done


def _write_fault(rp, kind: str, glob: str, what: str) -> callable:
    done: list = []

    def fn(rp_, phase, step):
        if phase != "before" or done or step.get("name") not in ("Write", "Edit"):
            return
        if step.get("name") == "Edit":  # a re-dispatch editing its earlier report: fault its new text
            return
        actor = step.get("actor")
        if rp.earlier_templates is not None and getattr(actor, "aid", None) not in rp.earlier_templates:
            return  # with a dispatch fault, only the agent an earlier template started writes the fault
        done.append(1)
        path = _path_of(rp, step)
        meant = step["input"].get("content", "")
        rec = {"kind": kind, "label": step["label"], "path": path, "agent": getattr(actor, "aid", None),
               "role": getattr(actor, "role", None), "repaired": False, "rounds": 0}
        text = None
        if kind == "missing":
            step["skip"] = True
        elif kind in ("invalid", "forged"):
            try:
                doc = json.loads(meant)
                if what:
                    rec["edits"] = _edit(doc, what)
                else:
                    field = _required_first(rp, path, meant)
                    doc.pop(field, None)
                    rec["dropped"] = field
                text = json.dumps(doc, indent=2) + "\n"
            except ValueError:
                text = meant[: len(meant) // 2]
        elif kind == "notjson":
            text = meant[: len(meant) // 2]
        else:
            raise ValueError(f"unknown fault kind {kind!r}")
        if text is not None:
            step["input"] = dict(step["input"], content=text)
        rp.fault_pending[path] = {"meant": meant, "faulted": text, "rec": rec, "forged": kind == "forged"}
        _record(rp, rec)
    return fn


def _earlier_template(prompt: str, kind: str) -> str:
    m = _BLOCK.search(prompt)
    if not m:
        raise ValueError("the dispatch carries no obligation block to fault")
    if kind == "noblock":
        return prompt[:m.start()].rstrip("\n") + "\n" + prompt[m.end():].lstrip("\n")
    ob = json.loads(m.group(1))
    for art in ob.get("artifacts") or []:
        if art.get("kind") == "json":  # the pre-P1 template's terminal-value list (P1 D2 removed it)
            dev = str(art.get("schema", "")).startswith("dev-report")
            art["required_values"] = {"dev.status": ["completed"]} if dev else {"verdict": ["pass"]}
    return prompt[:m.start()] + '<obligation v="1">\n' + json.dumps(ob, indent=2) + "\n</obligation>" + \
        prompt[m.end():]


def _fresh(prompt: str) -> str:
    """The same rendered prompt with a fresh dispatched_at (the declaring dispatch's next round)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return re.sub(r'("dispatched_at":\s*")[^"]*(")', lambda m: m.group(1) + now + m.group(2), prompt, count=1)


def _dispatch_fault(rp, kind: str, glob: str, what: str) -> callable:
    state: dict = {}

    def fn(rp_, phase, step):
        if step.get("kind") != "dispatch":
            return
        if phase == "before" and not state:
            state.update(prompt=step["prompt"], body=step["body"], result=step["result"])
            step["prompt"] = _earlier_template(step["prompt"], kind)
            body = step["body"]

            def started(sub):  # the agent the earlier template started (its writes are the faulted ones)
                rp.earlier_templates.add(sub.aid)
                return body(sub) if body else None
            step["body"] = started
            step["defer_stop"] = what == "defer"
            state["rec"] = {"kind": kind, "label": step["label"], "path": None, "agent": None,
                            "role": step["subagent_type"], "repaired": False, "rounds": 0}
            _record(rp, state["rec"])
            return
        if phase != "after" or "rec" not in state or state.get("done"):
            return
        state["done"] = True
        d, rec = step.get("result"), state["rec"]
        if d is not None and getattr(d, "blocked", False):
            # Refused at dispatch (G1): the orchestrator's next round is the declaring dispatch from the
            # tree's own template, a fresh dispatched_at; its outcome stands for the refused one.
            rec["rounds"] += 1
            rec["refused_at_dispatch"] = True
            again = step["actor"].dispatch(step["subagent_type"], _fresh(state["prompt"]),
                                           description=step["description"], body=state["body"],
                                           result=state["result"], label=step["label"] + " (next round)",
                                           deviation=step["deviation"], extra_input=step["extra_input"])
            for k in ("blocked", "agent_id", "actor", "stop", "post", "response", "ok", "tool_use_id"):
                setattr(d, k, getattr(again, k, None))
            rec["repaired"] = not again.blocked
        rec["agent"] = getattr(d, "agent_id", None)
        _record(rp, rec)
    return fn


def _plant(rp, glob: str, what: str) -> callable:
    done: list = []
    path_t, _, content = what.partition(":")

    def fn(rp_, phase, step):
        if phase != "before" or done:
            return
        done.append(1)
        # the cycle's own task id: the shortest the run learned (a lane's or a session's id extends it)
        task = min((v for v, k in rp.ids.values.items() if k == "task"), key=len, default="")
        rel = path_t.replace("{task}", str(task))
        if content == "qa-report.v1":
            doc = {"schema_version": "1.0", "task_id": str(task), "status": "fail", "verdict": "fail",
                   "summary": "an earlier QA run's report, before the lane reports",
                   "issues": [{"severity": "high", "description": "stale"}]}
            text = json.dumps(doc, indent=2) + "\n"
        else:
            text = "junk\n"
        full = os.path.join(rp.layout.project, rel)
        with rp.acting("fault"):
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as fh:
                fh.write(text)
            old = os.path.getmtime(full) - 3600
            os.utime(full, (old, old))
        _record(rp, {"kind": "plant", "label": step["label"], "path": rel, "content": content})
    return fn


def on_stop_block(sub, ev):
    """The faulted agent's next round: when its stop's block names an artifact it faulted, it writes
    that artifact as it meant to and stops again (a forged fault first rewrites the same invalid
    report and ends with the forged line); otherwise it has nothing to repair (None)."""
    rp = sub.rp
    text = "\n".join((h.get("stderr") or "") + (h.get("stdout") or "") for h in ev.blocks)
    mine = [(p, f) for p, f in rp.fault_pending.items()
            if p and p in text and not f["rec"]["repaired"] and f["rec"].get("agent") == sub.aid]
    if not mine:
        return None
    from . import agents
    final = getattr(sub, "last_final", "") or "Done."
    for path, f in mine:
        f["rec"]["rounds"] += 1
        full = os.path.join(rp.layout.project, path)
        if f["forged"] and f["rec"]["rounds"] == 1:
            sub.s.say(f"My stop was returned: {path} fails its check. I write the same report again.", sub.aid)
            if f["faulted"] is not None:
                agents.put(sub, full, f["faulted"], f"{sub.role} Write {path} (same invalid report)")
            final = final.rstrip("\n") + "\n\n" + _FORGED
            f["rec"]["forged_line"] = _FORGED
            _record(rp, f["rec"])
            continue
        sub.s.say(f"My stop was returned: {path} fails its check. Writing it as the artifact contract requires, "
                  "then stopping again.", sub.aid)
        agents.put(sub, full, f["meant"], f"{sub.role} Write {path} (next round)")
        f["rec"]["repaired"] = True
        _record(rp, f["rec"])
    return final


def install(rp, spec: str) -> None:
    """Register the faults `spec` names on rp (Replay.step's fault hooks)."""
    rp.fault_records = []
    rp.fault_pending = {}
    rp.earlier_templates = None  # with a dispatch fault: the agents an earlier template started
    for part in [p for p in spec.split(";") if p.strip()]:
        kind, _, rest = part.partition("@")
        glob, _, what = rest.partition("=")
        if kind == "plant":
            rp.faults.append((glob, _plant(rp, glob, what)))
        elif kind in ("pretemplate", "noblock"):
            rp.earlier_templates = set()
            rp.faults.append((glob, _dispatch_fault(rp, kind, glob, what)))
        else:
            rp.faults.append((glob, _write_fault(rp, kind, glob, what)))
    rp.on_stop_block_default = on_stop_block


def matches(label: str, glob: str) -> bool:
    return fnmatch.fnmatchcase(label, glob)
