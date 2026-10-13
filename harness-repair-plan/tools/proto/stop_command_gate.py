#!/usr/bin/env python3
"""PROTOTYPE of hooks/stop-command-gate.py (the coordinator's `completion` phase).

One declarative table: command -> (todo required?, completion predicate).
State comes from the transcript (command_span) and disk/git; nothing is written
except unlinking the /do consent flag on an allowed /do completion.
No retry bound, no stop_hook_active release, no self-release token.
The only exit before completion: the final line `AWAITING_INPUT: need=..; why=..; addressee=..`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = Path(os.environ.get("PROTO_HARNESS") or HERE.parent)  # prod: parent.parent of hooks/
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HARNESS / "hooks"))
import command_span as cs  # noqa: E402

_MODS: dict = {}


def _mod(rel: str, name: str):
    if name not in _MODS:
        spec = importlib.util.spec_from_file_location(name, HARNESS / rel)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _MODS[name] = m
    return _MODS[name]


def _git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=20)


# ---------------------------------------------------------------- task identity
_LANE_RE = re.compile(r"-l\d+$")


def _family(task_id: str) -> str:
    t = task_id[len("dev-"):] if task_id.startswith("dev-") and not task_id.startswith("dev-command-") else task_id
    return _LANE_RE.sub("", t)


def _obligations(span, pipelines):
    from lib import obligation  # harness lib
    out = []
    for u in span.calls("Agent", "Task"):
        if not u.ok:
            continue
        p = obligation.parse_obligation(str(u.input.get("prompt", "")))
        if isinstance(p, obligation.ParsedObligation) and p.obligation.get("pipeline") in pipelines:
            out.append(p.obligation)
    return out


def _task_args(span):
    return [t for t in span.args.split() if not t.startswith("-")]


# ---------------------------------------------------------------- predicates (return gap strings)
def dev_gaps(root, task):
    r = _mod("scripts/resolve-dev-artifact-chain.py", "_g_resolver").resolve_chain(root, task)
    if r.get("status") == "pass":  # D2: strict, every lane's QA pass; no pass_with_exceptions
        return []
    errs = r.get("errors") or [{"code": "STATUS_" + str(r.get("status")), "path": "", "detail": ""}]
    return [f"dev {task}: {e.get('code')} {e.get('path')} {e.get('detail', '')}".rstrip() for e in errs]


def do_gaps(root, task):
    p = Path(root) / "docs" / "dev" / f"do-report-{task}.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"do {task}: {p} unreadable ({type(e).__name__})"]
    d = doc.get("do") if isinstance(doc, dict) else None
    g = []
    if not isinstance(d, dict) or d.get("status") != "completed":
        g.append(f"do {task}: do.status is {d.get('status') if isinstance(d, dict) else None!r}, needs 'completed'")
    if isinstance(d, dict) and not (isinstance(d.get("summary"), str) and d["summary"].strip()):
        g.append(f"do {task}: do.summary empty")
    if doc.get("task_id") != task or doc.get("source") != "do":
        g.append(f"do {task}: identity/source mismatch")
    return g


def _origin_gaps(root, task):
    dd = Path(root) / "docs" / "dev"
    if (dd / f"do-report-{task}.json").exists() and not (dd / f"dev-report-{task}.json").exists():
        return do_gaps(root, task)
    return dev_gaps(root, task)


def close_gaps(root, task):
    g = _origin_gaps(root, task)  # D7: close completes the cycle first
    cv = _mod("hooks/lib/close-verdict.py", "_g_close_verdict")
    p = Path(root) / "docs" / "dev" / f"close-report-{task}.md"
    try:
        verdict = cv.classify_line(cv.last_nonempty(p.read_text(encoding="utf-8")))
    except OSError:
        verdict = "absent"
    if verdict != "yes":
        g.append(f"close {task}: close-report verdict {verdict!r}, needs CLOSE: YES")
    return g


def commit_gaps(root, task):
    g = close_gaps(root, task)  # D7: commit completes dev and close first
    if g:
        return g
    row = _mod("scripts/dev-lifecycle.py", "_g_lifecycle").derive_state(Path(root), task)
    if row.get("state") != "committed":
        g.append(f"commit {task}: lifecycle state {row.get('state')!r} ({row.get('blocker', '')}), needs 'committed'")
    return g


def _auto_snapshot(span, action):
    for u in span.calls("Bash"):
        if u.ok and f"list-actionable --next-action {action}" in str(u.input.get("command", "")):
            return [ln.strip() for ln in u.result_text.splitlines() if ln.strip()]
    return None


def _targets(span, pipelines, action):
    if "--auto" in span.args.split():
        snap = _auto_snapshot(span, action)
        return snap if snap is not None else ["<--auto discovery not run>"]
    explicit = _task_args(span)
    if explicit:
        return explicit
    return sorted({_family(o["task_id"]) for o in _obligations(span, pipelines) if o.get("task_id")})


def _kv(prompt, key):
    m = re.search(rf"^{key}=(\S+)\s*$", prompt or "", re.M)
    return m.group(1) if m else None


def p_dev(span, root, payload):
    fams = sorted({_family(o["task_id"]) for o in _obligations(span, {"dev", "redev", "dev-command"})
                   if o.get("task_id")})
    if not fams:
        return ["dev: no obligated dispatch in this command span (cycle identity unknown)"]
    return [g for f in fams for g in dev_gaps(root, f)]


def p_do(span, root, payload):
    sd = os.environ.get("CLAUDE_STATE_DIR") or "/tmp"
    try:
        task = json.loads((Path(sd) / f"claude-do-task-{payload.get('session_id')}.json").read_text())["task_id"]
    except Exception:
        return ["do: task sidecar missing (hook did not mint a task id)"]
    return do_gaps(root, task)


def p_close(span, root, payload):
    ts = _targets(span, {"close"}, "close")
    return [g for t in ts for g in close_gaps(root, t)] if ts else ["close: no target task resolved"]


def p_commit(span, root, payload):
    ts = _targets(span, {"commit"}, "commit")
    return [g for t in ts for g in commit_gaps(root, t)] if ts else ["commit: no target task resolved"]


def p_merge(span, root, payload):
    ds = [u for u in span.calls("Agent", "Task") if u.ok and u.input.get("subagent_type") == "merge-analyst"]
    if not ds:
        return ["merge: merge-analyst not dispatched"]
    pr = str(ds[-1].input.get("prompt", ""))
    tip, br, repo = _kv(pr, "SOURCE_TIP"), _kv(pr, "DEFAULT_BRANCH"), _kv(pr, "REPO_ROOT") or root
    if _git(repo, "merge-base", "--is-ancestor", tip, f"refs/heads/{br}").returncode != 0:
        return [f"merge: {tip} is not contained in refs/heads/{br}"]
    if _git(repo, "ls-files", "-u").stdout.strip():
        return ["merge: unmerged index entries remain"]
    return []


def p_push(span, root, payload):
    ds = [u for u in span.calls("Agent", "Task") if u.ok and u.input.get("subagent_type") == "push-analyst"]
    if not ds:
        return ["push: push-analyst not dispatched"]
    pr = str(ds[-1].input.get("prompt", ""))
    br, remote = _kv(pr, "BRANCH"), _kv(pr, "REMOTE_NAME")
    ref = f"refs/remotes/{remote}/{br}"
    if _git(root, "merge-base", "--is-ancestor", "HEAD", ref).returncode != 0:
        return [f"push: HEAD is not published on {ref}"]
    return []


RULES = {  # command -> (todo list required, completion predicate, pause honoured)
    "do": (True, p_do, True), "dev": (True, p_dev, True), "redev": (True, p_dev, True),
    "dev-command": (True, p_dev, True), "close": (True, p_close, True),
    "commit": (False, p_commit, True), "merge": (False, p_merge, True), "push": (False, p_push, True),
    # dev-overnight: see design (time-lock window ignores the pause); not prototyped here
}


def timelock_gap(payload):
    from datetime import datetime, timezone
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
    sid = payload.get("session_id") or ""
    try:
        st = json.loads((root / ".claude" / f"overnight-state-{sid}.json").read_text())
    except Exception:
        return None
    if st.get("session_id") != sid or st.get("terminal_status") == "cancelled_by_user":
        return None
    try:
        end = datetime.fromisoformat(str(st.get("end_time")).replace("Z", "+00:00"))
    except ValueError:
        return None
    if end.tzinfo is None:
        end = end.astimezone()  # naive = local wall clock, compared in UTC
    if datetime.now(timezone.utc) < end.astimezone(timezone.utc):
        return f"overnight session runs until {end.isoformat()}; keep working (human /stop releases)"
    return None


def todo_gaps(span):
    script = HARNESS / "scripts" / "todo" / f"{span.command}.py"
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                       env={**os.environ, "CLAUDE_TODO_PROMPT": f"/{span.command} {span.args}"},
                       cwd=str(script.parent), timeout=20)
    canon = json.loads(r.stdout)
    cur = span.last_todos()
    if cur is None:
        return [f"todo: checklist never written ({len(canon)} canonical steps)"]
    if [t.get("content") for t in cur] != [t.get("content") for t in canon]:
        return [f"todo: checklist differs from the canonical {len(canon)} steps"]
    open_ = [t["content"] for t in cur if t.get("status") != "completed"]
    return [f"todo: not completed: {c}" for c in open_]


def main() -> int:
    payload = json.load(sys.stdin)
    if payload.get("agent_id"):
        return 0
    try:
        openers = frozenset(p.stem for p in (HARNESS / "commands").glob("*.md"))
        span = cs.active_span(payload.get("transcript_path") or "", openers)
    except OSError:
        return 0  # cannot scope: unknown command (pre-binding failure)
    from lib import interruption_signals
    if span is not None and interruption_signals.classify_record(span.last_assistant) is not None:
        return 0  # CLI aborted the turn on an API error: cycle stays incomplete, /restart resumes
    lock = timelock_gap(payload)
    if lock:
        sys.stderr.write(f"COMMAND_GATE time-lock: {lock}\n")
        return 2  # session-level, span-independent; the pause is not honoured; human /stop releases
    if span is None or span.command not in RULES:
        return 0
    todo_req, pred, pause_ok = RULES[span.command]
    if pause_ok and cs.is_pause(cs.final_text(payload, span)):
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    try:
        gaps = (todo_gaps(span) if todo_req else []) + pred(span, root, payload)
    except Exception as exc:  # bound to a gated command: instrument failure never releases
        gaps = [f"gate instrument failure: {type(exc).__name__}: {exc}"]
    if not gaps:
        if span.command == "do":
            sd = os.environ.get("CLAUDE_STATE_DIR") or "/tmp"
            try:
                (Path(sd) / f"claude-orchestrator-consent-{payload.get('session_id')}.flag").unlink()
            except OSError:
                pass
        return 0
    sys.stderr.write(f"COMMAND_GATE /{span.command}: not complete\n" + "".join(f"- {g}\n" for g in gaps) +
                     "Continue the work. To stop before completion, ask the user: end your message with\n"
                     "AWAITING_INPUT: need=<decision>; why=<reason>; addressee=human\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
