"""Score events from facts: sweep() appends the active span's events to the score log; observe() is the dispatch hook's entry."""
import importlib
import json
import os
import re
from contextlib import suppress
from datetime import datetime, timezone

# as hooks.lib.score_events, or from hooks/lib on the path
command_span, obligation, score_log = (importlib.import_module(f"{__package__}.{n}" if __package__ else n)
                                       for n in ("command_span", "obligation", "score_log"))
CAUSE_ROLE = {"dev_implementation": "dev", "ba_spec": "ba"}  # a failure's primary_cause -> the role it costs


def _utc(value=None):
    return (obligation.parse_iso8601(value) or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(ctx, d, event, role, why, key=None):  # a rule's event dict: the result's time, a one-line why without task id, the report as ref
    return {"event": event, "role": role, "task_id": d["task"], "ts": _utc(d["at"]), "key": key or f"{event}:{d['id']}:{role}",
            "why": score_log._why({"task_id": d["task"], "why": why}), "ref": d["path"] or ""}


def _dispatches(span, tp):  # ok dispatches with an obligation: id, who (scored identity), task (canonical), lane, ob, path (lane QA's
    uses, ds = {u.id: u for u in span.uses("Agent", "Task")}, []  # report), at (the result's time), sub (its own transcript)
    with open(tp, "rb") as handle:
        for call, ob in span.obligations():
            handle.seek(uses[call.id].result_at)
            record = json.loads(handle.readline())  # the CLI's record of the result: its timestamp, toolUseResult.agentId
            agent = record.get("toolUseResult")
            agent = agent.get("agentId") if isinstance(agent, dict) else None
            who = score_log.identity(ob.get("role"), ob.get("pipeline"))
            ds.append(dict(id=call.id, who=who, task=obligation.canonical_task_id(ob.get("task_id")), lane=ob.get("lane"), ob=ob, at=record.get("timestamp"),
                           sub=f"{os.path.splitext(tp)[0]}/subagents/agent-{agent}.jsonl",
                           path=next((a.get("path") for a in ob["artifacts"] if a.get("schema") == "qa-report.v2"), None) if who == "qa" else None))
    return [d for d in ds if d["task"]]


def _report(ctx, d, later):  # the report file; once the next dispatch of that file has overwritten it, d's own last Write of it
    path = os.path.join(ctx["cwd"], d["path"])
    with suppress(OSError, ValueError, TypeError, AttributeError):  # missing, unreadable, malformed: no report
        mtime = os.stat(path).st_mtime
        if not obligation.artifact_freshness_satisfied("json", mtime, d["ob"]["dispatched_at"]):
            return None
        if not later or mtime < obligation.parse_iso8601(later["ob"]["dispatched_at"]).timestamp():
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        found = None
        for _, record in command_span._records(d["sub"]):  # overwritten: the file as d's own transcript last wrote it
            for block in (record.get("message") or {}).get("content") or ():
                args = block.get("input") if isinstance(block, dict) and block.get("name") == "Write" else None
                if isinstance(args, dict) and str(args.get("file_path")).endswith(d["path"]):
                    found = json.loads(args.get("content"))
        return found


def _lane_qa(ctx):  # ctx["qa"]: lane QA (role qa outside close) in order, each with rep (its report), status and fails (dicts)
    qa = ctx["qa"] = [d for d in ctx["ds"] if d["path"]]
    for i, d in enumerate(qa):
        d["rep"] = _report(ctx, d, next((e for e in qa[i + 1:] if e["path"] == d["path"]), None))
        d["status"] = obligation.terminal_status("qa-report.v2", d["rep"])
        found = d["rep"]["qa"].get("failures") if d["status"] == "fail" else None
        d["fails"] = [f for f in found if isinstance(f, dict)] if isinstance(found, list) else []


def qa_first_pass(ctx):  # the lane's first QA dispatch passed (a later pass, or one after an unreadable report, is not first)
    for d in {(d["task"], d["lane"]): d for d in reversed(ctx["qa"])}.values():
        for role in score_log.POINTS["qa_first_pass"] if d["status"] == "pass" else ():
            yield _event(ctx, d, "qa_first_pass", role, "lane QA passed at the first round")


def qa_fail(ctx):  # a row per scored role the failures blame, with the first such failure's issue (reversed: the first wins)
    for d in ctx["qa"]:
        blamed = {CAUSE_ROLE[c]: f.get("issue") or "lane QA failed" for f in reversed(d["fails"]) if (c := str(f.get("primary_cause"))) in CAUSE_ROLE}
        for role, issue in blamed.items():
            yield _event(ctx, d, "qa_fail", role, issue)


def qa_catch(ctx):  # a QA failure, the lane's next dev dispatch wrote a file a failure names, then QA passes: at most 2 a task
    pending, taken = {}, {}  # (task, lane) -> [files the last failure named, fixed or None]; catches per task
    for d in ctx["ds"]:
        key = d["task"], d["lane"]
        if d["who"] == "dev" and pending.get(key) and pending[key][1] is None:
            written = command_span.write_set(d["sub"], ctx["cwd"], excluded=())  # excluded=(): docs/dev files count too
            pending[key][1] = bool(pending[key][0] & set(getattr(written, "written", ())))
        elif "status" in d:
            if d["status"] == "pass" and pending.get(key) and pending[key][1] and taken.get(d["task"], 0) < 2:
                taken[d["task"]] = taken.get(d["task"], 0) + 1
                yield _event(ctx, d, "qa_catch", "qa", "a failure it reported was fixed in the file it named", f"qa_catch:{d['id']}")
            names = (re.sub(r"(?::\d+)+(?:-\d+)?$", "", str(f.get("location") or "").strip()) for f in d["fails"])  # file:line
            pending[key] = [{os.path.relpath(os.path.join(ctx["cwd"], n), ctx["cwd"]) for n in names if n}, None] if d["status"] == "fail" else None


RULES = [qa_first_pass, qa_fail, qa_catch]  # a rule is f(ctx) -> event dicts built with _event; list it here (ctx: span, tp, cwd, project, ds, qa)


def sweep(transcript_path, cwd):  # all ok dispatches of the span, every run: first-row-per-key makes a repeat write nothing; never raises
    with suppress(Exception):
        # a non-string path is refused: active_span would take an int for a file descriptor and close it
        span = command_span.active_span(transcript_path) if isinstance(transcript_path, str) and isinstance(cwd, str) else None
        if span is None:
            return
        ctx, rows = {"span": span, "tp": transcript_path, "cwd": cwd, "ds": _dispatches(span, transcript_path), "project": score_log.project_key(cwd)}, []
        _lane_qa(ctx)
        for rule in RULES:
            with suppress(Exception):  # one failing rule never stops another (and writes nothing)
                rows += [{"kind": "event", "ts": _utc(), "project": ctx["project"], "ref": "", **e, "points": p}
                         for e in rule(ctx) if (p := score_log.points_for(e["event"], e["role"])) is not None]
        if rows:
            log = score_log.log_path()
            with score_log.locked(log):
                for row in rows:
                    score_log.append(log, row)


def observe(payload):  # the PostToolUse hook's entry: the main agent's dispatches only
    if isinstance(payload, dict) and not payload.get("agent_id") and payload.get("tool_name") in ("Agent", "Task"):
        sweep(payload.get("transcript_path"), payload.get("cwd"))
