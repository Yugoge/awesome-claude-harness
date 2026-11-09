"""Score events from facts: observe(payload) runs after the main agent's dispatches and appends what files on disk and the
CLI's transcripts show about lane QA to the score log. It never blocks, prints or raises, and takes no gate's verdict. A
rule is f(ctx) -> event dicts (build one with _event); observe adds kind, project and the table's points. A lane adds a
rule by writing that function and listing it in RULES. Every run sweeps all ok dispatches of the span: the log's
first-row-per-key makes a repeat write nothing, and a dispatch whose facts are not on disk yet is scored by a later run."""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

try:  # imported as hooks.lib.score_events (tests) or from hooks/lib on the path
    from . import command_span, obligation, score_log
except ImportError:
    import command_span, obligation, score_log  # type: ignore[no-redef]

CAUSE_ROLE = {"dev_implementation": "dev", "ba_spec": "ba"}  # a failure's primary_cause -> the role it costs


def _utc(value=None) -> str:
    return (obligation.parse_iso8601(value) or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(ctx, ident) -> dict:
    """The CLI's record of a dispatch's result (timestamp, toolUseResult); {} when unreadable."""
    uses = ctx.setdefault("uses", {u.id: u for u in ctx["span"].uses("Agent", "Task")})
    try:
        with open(ctx["tp"], "rb") as handle:
            handle.seek(uses[ident].result_at)
            return json.loads(handle.readline()) or {}
    except (KeyError, OSError, TypeError, ValueError):
        return {}


def _event(ctx, d, event, role, why, key=None) -> dict:
    """The event dict of dispatch d: its result's time (else now), its task, one line of why, its report as ref."""
    return {"event": event, "role": role, "task_id": d["task"], "ts": _utc(_record(ctx, d["id"]).get("timestamp")),
            "key": key or f"{event}:{d['id']}:{role}", "why": score_log._why({"task_id": d["task"], "why": why}),
            "ref": d["path"] or ""}


def _dispatches(span) -> list[dict]:
    """The span's ok dispatches with an obligation: id, who (scored identity), task (canonical), lane, ob, path (the
    qa-report.v2 file a lane QA declares, else None)."""
    found = []
    for call, ob in span.obligations():
        who, task = score_log.identity(ob.get("role"), ob.get("pipeline")), obligation.canonical_task_id(ob.get("task_id"))
        path = next((a.get("path") for a in ob.get("artifacts") or () if a.get("schema") == "qa-report.v2"), None)
        if task:
            found.append({"id": call.id, "who": who, "task": task, "lane": ob.get("lane"), "ob": ob, "path": path if who == "qa" else None})
    return found


def _sub(ctx, d) -> str:
    """The path of dispatch d's own transcript, which the CLI keeps beside the main one."""
    result = _record(ctx, d["id"]).get("toolUseResult")
    return f"{os.path.splitext(ctx['tp'])[0]}/subagents/agent-{result.get('agentId') if isinstance(result, dict) else None}.jsonl"


def _wrote(ctx, d):
    """The report d's own transcript last wrote to its path, parsed: what the file held before a later dispatch overwrote it."""
    found = None
    try:
        for _, record in command_span._records(_sub(ctx, d)):
            for block in record["message"]["content"]:
                if block.get("name") == "Write" and str(block["input"].get("file_path")).endswith(d["path"]):
                    found = json.loads(block["input"]["content"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return found


def _report(ctx, d, later):
    """d's report file parsed, if it is not older than d's dispatched_at (obligation's slack). When the next dispatch of the
    same file has overwritten it, what d's own transcript wrote there. None when missing, unreadable or stale."""
    path = os.path.join(ctx["cwd"], d["path"])
    try:
        mtime = os.stat(path).st_mtime
        if not obligation.artifact_freshness_satisfied("json", mtime, d["ob"]["dispatched_at"]):
            return None
        if later and mtime >= obligation.parse_iso8601(later["ob"]["dispatched_at"]).timestamp():
            return _wrote(ctx, d)
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, AttributeError):
        return None


def _lane_qa(ctx) -> list[dict]:
    """The lane-QA dispatches (role qa outside close) in order, each with rep (its report) and status (pass, fail, warning or None)."""
    if "qa" not in ctx:
        ctx["qa"] = qa = [d for d in ctx["ds"] if d["path"]]
        for i, d in enumerate(qa):
            d["rep"] = _report(ctx, d, next((e for e in qa[i + 1:] if e["path"] == d["path"]), None))
            d["status"] = obligation.terminal_status("qa-report.v2", d["rep"])
    return ctx["qa"]


def qa_first_pass(ctx):
    """The lane's first QA dispatch passed (a later pass, or one after a report that cannot be read, is not first)."""
    for d in {(d["task"], d["lane"]): d for d in reversed(_lane_qa(ctx))}.values():
        for role in score_log.POINTS["qa_first_pass"] if d["status"] == "pass" else ():
            yield _event(ctx, d, "qa_first_pass", role, "lane QA passed at the first round")


def _failures(d) -> list[dict]:
    found = d["rep"]["qa"].get("failures") if d["status"] == "fail" else None
    return [f for f in found if isinstance(f, dict)] if isinstance(found, list) else []


def qa_fail(ctx):
    """A failed lane-QA report: a row per scored role its failures blame, with the first such failure's issue."""
    for d in _lane_qa(ctx):  # reversed, so the first failure naming a role sets its issue
        blamed = {CAUSE_ROLE[c]: f.get("issue") or "lane QA failed" for f in reversed(_failures(d)) if (c := str(f.get("primary_cause"))) in CAUSE_ROLE}
        for role, issue in blamed.items():
            yield _event(ctx, d, "qa_fail", role, issue)


def _named(ctx, d) -> set:
    """The project-relative files the failures of d's report name in their location (file:line)."""
    names = (re.sub(r"(?::\d+)+(?:-\d+)?$", "", str(f.get("location") or "").strip()) for f in _failures(d))
    return {os.path.relpath(os.path.join(ctx["cwd"], name), ctx["cwd"]) for name in names if name}


def _written(ctx, d) -> set:
    """The project-relative files the dev dispatch's own tool calls wrote."""
    found = command_span.write_set(_sub(ctx, d), ctx["cwd"], excluded=())
    return set(found.written) if found else set()


def qa_catch(ctx):
    """A lane-QA failure, then the lane's next dev dispatch wrote a file a failure names, then its QA passes: qa's catch."""
    _lane_qa(ctx)
    pending, taken = {}, Counter()  # (task, lane) -> [files the last failure named, fixed or None]; catches per task
    for d in ctx["ds"]:
        key = d["task"], d["lane"]
        if d["who"] == "dev" and pending.get(key) and pending[key][1] is None:
            pending[key][1] = bool(pending[key][0] & _written(ctx, d))
        elif "status" in d:
            if d["status"] == "pass" and pending.get(key) and pending[key][1] and taken[d["task"]] < 2:
                taken[d["task"]] += 1
                yield _event(ctx, d, "qa_catch", "qa", "a failure it reported was fixed in the file it named", f"qa_catch:{d['id']}")
            pending[key] = [_named(ctx, d), None] if d["status"] == "fail" else None


RULES = [qa_first_pass, qa_fail, qa_catch]


def observe(payload) -> None:
    """Append the events every rule finds in the active span of a main agent's dispatch payload. Never raises."""
    try:
        if not isinstance(payload, dict) or payload.get("agent_id") or payload.get("tool_name") not in ("Agent", "Task"):
            return
        span = command_span.active_span(payload["transcript_path"])
        if span is None:
            return
        ctx, rows = {"span": span, "tp": payload["transcript_path"], "cwd": payload["cwd"], "ds": _dispatches(span),
                     "project": score_log.project_key(payload["cwd"])}, []
        for rule in RULES:
            try:
                for e in rule(ctx):
                    points = score_log.points_for(e["event"], e["role"])
                    if points is not None:
                        rows.append({"kind": "event", "ts": _utc(), "project": ctx["project"], "ref": "", **e, "points": points})
            except Exception:
                pass
        if rows:
            log = score_log.log_path()
            with score_log.locked(log):
                for row in rows:
                    score_log.append(log, row)
    except Exception:
        pass
