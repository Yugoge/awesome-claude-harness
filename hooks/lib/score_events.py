"""Score events from facts: sweep() appends the active span's events to the score log; observe() is the dispatch hook's entry."""
import importlib
import json
import os
import re
import runpy
from contextlib import suppress
from datetime import datetime, timezone

# as hooks.lib.score_events, or from hooks/lib on the path
command_span, obligation, score_log = (importlib.import_module(f"{__package__}.{n}" if __package__ else n)
                                       for n in ("command_span", "obligation", "score_log"))


def _event(ctx, d, event, role, why, key=None, ref=None):  # a rule's event dict: the result's time, a one-line why without task id, ref (default: d's report)
    return {"event": event, "role": role, "task_id": d["task"], "key": key or f"{event}:{d['id']}:{role}",
            "why": score_log._why({"task_id": d["task"], "why": why}), "ref": ref or d["path"] or "",
            "ts": (obligation.parse_iso8601(d["at"]) or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def _dispatches(span, tp):  # ok dispatches with an obligation: id, who (scored identity), task (canonical), lane, ob, path (lane QA's
    uses, ds = {u.id: u for u in span.uses("Agent", "Task")}, []  # report), at (the result's time), sub (its own transcript)
    with open(tp, "rb") as handle:
        for call, ob in span.obligations():
            handle.seek(uses[call.id].result_at)
            result = (record := json.loads(handle.readline())).get("toolUseResult")  # the CLI's record of the result; the agentId in it names the subagent's transcript
            who = score_log.identity(ob.get("role"), ob.get("pipeline"))
            ds.append(dict(n=len(ds), id=call.id, who=who, task=obligation.canonical_task_id(ob.get("task_id")), lane=ob.get("lane"), ob=ob, at=record.get("timestamp"),
                           sub=f"{os.path.splitext(tp)[0]}/subagents/agent-{result.get('agentId') if isinstance(result, dict) else None}.jsonl",
                           path=next((a.get("path") for a in ob["artifacts"] if a.get("schema") == "qa-report.v2"), None) if who == "qa" else None))
    return [d for d in ds if d["task"]]


def _walk(d):  # the content blocks of dispatch d's own transcript, in order
    for _, record in command_span._records(d["sub"]):
        content = (record.get("message") or {}).get("content")
        yield from (b for b in content if isinstance(b, dict)) if isinstance(content, list) else ()


def _report(ctx, d, later):  # the report file; once the next dispatch of that file has overwritten it, d's own last Write of it
    path = os.path.join(ctx["cwd"], d["path"])
    with suppress(OSError, ValueError, TypeError, AttributeError, IndexError):  # missing, unreadable, malformed: no report
        mtime = os.stat(path).st_mtime
        if not obligation.artifact_freshness_satisfied("json", mtime, d["ob"]["dispatched_at"]):
            return None
        if not later or mtime < obligation.parse_iso8601(later["ob"]["dispatched_at"]).timestamp():
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        return json.loads([i.get("content") for b in _walk(d) if b.get("name") == "Write" and str((i := b.get("input") or {}).get("file_path")).endswith(d["path"])][-1])  # overwritten: as d last wrote it


def _lane_qa(ctx):  # ctx["qa"]: lane QA (role qa outside close) in order, each with rep (its report), status and fails (dicts)
    qa = ctx["qa"] = [d for d in ctx["ds"] if d["path"]]
    for i, d in enumerate(qa):
        d["rep"] = _report(ctx, d, next((e for e in qa[i + 1:] if e["path"] == d["path"]), None))
        d["status"] = obligation.terminal_status("qa-report.v2", d["rep"])
        d["fails"] = [f for f in (d["rep"]["qa"].get("failures") if d["status"] == "fail" else None) or () if isinstance(f, dict)]


def _rel(ctx, loc):  # the project-relative file part of a "file:line" location
    return os.path.relpath(os.path.join(ctx["cwd"], re.sub(r"(?::\d+)+(?:-\d+)?$", "", str(loc).strip())), ctx["cwd"])


def _written(ctx, d):  # the project-relative files dispatch d's own tool calls wrote (excluded=(): docs/dev files count too)
    return set(getattr(command_span.write_set(d["sub"], ctx["cwd"], excluded=()), "written", ()))


def qa_first_pass(ctx):  # the lane's first QA dispatch passed (a later pass, or one after an unreadable report, is not first)
    first = {(d["task"], d["lane"]): d for d in reversed(ctx["qa"])}.values()
    yield from (_event(ctx, d, "qa_first_pass", role, "lane QA passed at the first round") for d in first if d["status"] == "pass" for role in score_log.POINTS["qa_first_pass"])


def qa_fail(ctx):  # a row per scored role the failures blame, with the first such failure's issue (reversed: the first wins)
    for d in ctx["qa"]:
        blamed = {r: f.get("issue") or "lane QA failed" for f in reversed(d["fails"])  # a failure's primary_cause names the role it costs
                  if (r := {"dev_implementation": "dev", "ba_spec": "ba"}.get(str(f.get("primary_cause"))))}
        for role, issue in blamed.items():
            yield _event(ctx, d, "qa_fail", role, issue)


def qa_catch(ctx):  # a QA failure, the lane's next dev dispatch wrote a file a failure names, then QA passes: at most 2 a task
    pending, taken = {}, {}  # (task, lane) -> [files the last failure named, fixed or None]; catches per task
    for d in ctx["ds"]:
        key = d["task"], d["lane"]
        if d["who"] == "dev" and pending.get(key) and pending[key][1] is None:
            pending[key][1] = bool(pending[key][0] & _written(ctx, d))
        elif "status" in d:
            if d["status"] == "pass" and pending.get(key) and pending[key][1] and taken.get(d["task"], 0) < 2:
                taken[d["task"]] = taken.get(d["task"], 0) + 1
                yield _event(ctx, d, "qa_catch", "qa", "a failure it reported was fixed in the file it named", f"qa_catch:{d['id']}")
            pending[key] = [{_rel(ctx, f["location"]) for f in d["fails"] if f.get("location")}, None] if d["status"] == "fail" else None


def _producer(ctx, d, path):  # (task, lane, identity) of the dispatch that owes path, and whether its lane's QA report now reads pass; (None, False): none, or a close-time one
    ob = (obligation.declaring_dispatch(d["task"], path, ctx["cwd"], ctx["roots"]) or {}).get("obligation") or {}
    group = (obligation.canonical_task_id(ob.get("task_id")), ob.get("lane"), score_log.identity(ob["role"], ob["pipeline"])) if ob.get("role") and ob.get("pipeline") != "close" else None
    return group, bool(group) and any(obligation.terminal_status("qa-report.v2", _report(ctx, {"path": a["path"], "ob": o}, None)) == "pass"
                                      for r in obligation._task_records(d["task"], ctx["cwd"], ctx["roots"]) for o in [r["obligation"]] for a in o["artifacts"]  # every session's records
                                      if score_log.identity(o.get("role"), o.get("pipeline")) == "qa" and a.get("schema") == "qa-report.v2"
                                      and (obligation.canonical_task_id(o.get("task_id")), o.get("lane")) == group[:2])


def _close_qa(ctx):  # ctx["close"]: close-QA rounds in order, each with verdict (yes/no/unknown) and finds (cited file, producer group, lane QA passed)
    ctx["close"] = [d for d in ctx["ds"] if d["who"] == "close-qa"]
    cv = runpy.run_path(os.path.join(os.path.dirname(__file__), "close-verdict.py")) if ctx["close"] else None
    for d in ctx["close"]:
        blocks = list(_walk(d))  # its reply is the last text it said (a launch notice carries none); its section, what it wrote or ran
        d["verdict"] = cv["classify_line"](cv["last_nonempty"](str(next((b.get("text") for b in reversed(blocks) if b.get("type") == "text"), ""))))
        wrote = "\n".join(str(v) for b in blocks for v in (b.get("input") or {}).values()).rpartition("## Findings")[2]  # after its last findings heading
        found = re.findall(r"(?m)^- `?([^\s`]+?)`?:\s", re.split(r"(?m)^## ", wrote)[0]) if d["verdict"] == "no" else []
        d["finds"] = [(rel, *_producer(ctx, d, rel)) for rel in (_rel(ctx, p) for p in found)]


def escaped(ctx):  # a close round opened a finding on a file whose producer's lane QA had passed: the producer and lane QA lose points
    for d in ctx["close"]:
        for i, (path, group, passed) in enumerate(d.get("finds", ())):
            for role in (group[2], "qa") if passed else ():
                yield _event(ctx, d, "escaped", role, "close QA opened a finding after lane QA passed", f"escaped:{d['id']}:{i}:{role}", path)


def close_catch(ctx):  # a finding's producer wrote the cited file in a later dispatch and a later close round landed: close-qa's catch
    for d in ctx["close"]:
        for i, (path, group, _) in enumerate(d.get("finds", ())):
            fix = next((e for e in ctx["ds"] if group and e["n"] > d["n"] and (e["task"], e["lane"], e["who"]) == group and path in _written(ctx, e)), None)
            for land in [m for m in ctx["close"] if fix and m["n"] > fix["n"] and m.get("verdict") == "yes"][:1]:
                yield _event(ctx, land, "close_catch", "close-qa", "a close finding was fixed by its producer, then a round landed", f"close_catch:{land['id']}:{i}", path)


def rerun_gap(ctx):  # a dispatch whose previous one in its group (task, lane, identity, declared paths) never touched them, nor wrote a producer question
    last = {}
    for d in ctx["ds"]:
        paths = frozenset(a["path"] for a in d["ob"]["artifacts"] if a.get("path"))
        key = d["task"], d["lane"], d["who"], paths
        before, last[key] = last.get(key), d
        if before and paths and os.path.isfile(before["sub"]):  # touched: any tool call of its own names the path (a Write, a heredoc, a helper script)
            seen = " ".join(str(v) for b in _walk(before) for v in (b.get("input") or {}).values())
            if not any(p in seen for p in paths | {f"docs/dev/producer-question-{before['ob']['task_id']}-{before['ob']['role']}.json"}):
                yield _event(ctx, d, "rerun_gap", d["who"], "dispatched again after its previous dispatch left a declared artifact unwritten", f"rerun_gap:{d['id']}")


RULES = [qa_first_pass, qa_fail, qa_catch, escaped, close_catch, rerun_gap]  # a rule is f(ctx) -> event dicts built with _event; list it here (ctx: tp, cwd, roots, project, ds, qa, close)


def sweep(transcript_path, cwd):  # all ok dispatches of the span, every run: first-row-per-key makes a repeat write nothing; never raises
    with suppress(Exception):
        # a non-string path is refused: active_span would take an int for a file descriptor and close it
        if span := command_span.active_span(transcript_path) if isinstance(transcript_path, str) and isinstance(cwd, str) else None:
            ctx, rows = {"tp": transcript_path, "cwd": cwd, "roots": [os.path.dirname(os.path.dirname(transcript_path))],  # the CLI's store root holds <slug>/<session>.jsonl
                         "ds": _dispatches(span, transcript_path), "project": score_log.project_key(cwd)}, []
            for facts in (_lane_qa, _close_qa):
                with suppress(Exception):  # a rule's facts: a failure here costs only the rules that read them
                    facts(ctx)
            for rule in RULES:
                with suppress(Exception):  # one failing rule never stops another (and writes nothing)
                    rows += [{"kind": "event", "project": ctx["project"], **e, "points": p}
                             for e in rule(ctx) if (p := score_log.points_for(e["event"], e["role"])) is not None]
            if rows:
                with score_log.locked(log := score_log.log_path()):
                    for row in rows:
                        score_log.append(log, row)


def observe(payload):  # the PostToolUse hook's entry: the main agent's dispatches only
    if isinstance(payload, dict) and not payload.get("agent_id") and payload.get("tool_name") in ("Agent", "Task"):
        sweep(payload.get("transcript_path"), payload.get("cwd"))
