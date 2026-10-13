#!/usr/bin/env python3
"""Baseline driver: runs inside the mount namespace. Replays a realistic session through the hook chain.

Usage: baseline.py <settings.json> <log.jsonl> <phase>
phase: main | slash | all
"""
import json, os, subprocess, sys, time, uuid, shutil

SETTINGS, LOG, PHASE = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "all")
RUNHOOK = "/mnt/sb/tools/runhook.py"
RV_HOME = os.environ.get("RV_HOME", "/root")
RV_CLAUDE = os.environ.get("RV_CLAUDE", RV_HOME + "/.claude")
PROJ = RV_HOME + "/toyproj"
SLUG = PROJ.replace("/", "-")
TDIR = f"{RV_CLAUDE}/projects/{SLUG}"
os.makedirs(TDIR, exist_ok=True)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


class Session:
    def __init__(self, sid=None):
        self.sid = sid or str(uuid.uuid4())
        self.tpath = f"{TDIR}/{self.sid}.jsonl"
        self.parent = None
        open(self.tpath, "a").close()

    def append(self, entry, agent_id=None):
        entry.setdefault("sessionId", self.sid)
        entry.setdefault("cwd", PROJ)
        entry.setdefault("timestamp", now())
        entry.setdefault("uuid", str(uuid.uuid4()))
        entry.setdefault("parentUuid", self.parent)
        entry.setdefault("version", "2.1.295")
        if agent_id:
            entry["isSidechain"] = True
            entry["agentId"] = agent_id
            p = self.agent_tpath(agent_id)
        else:
            entry.setdefault("isSidechain", False)
            p = self.tpath
            self.parent = entry["uuid"]
        with open(p, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def agent_tpath(self, agent_id):
        d = f"{TDIR}/{self.sid}/subagents"
        os.makedirs(d, exist_ok=True)
        return f"{d}/agent-{agent_id}.jsonl"

    def user_text(self, text, agent_id=None):
        self.append({"type": "user", "message": {"role": "user", "content": text}}, agent_id)

    def base(self, event, agent=None):
        p = {"session_id": self.sid, "transcript_path": self.tpath, "cwd": PROJ,
             "hook_event_name": event, "permission_mode": "default"}
        if agent:
            p["agent_id"], p["agent_type"] = agent
        return p


def ev(sess, event, label, extra=None, agent=None, env=None):
    p = sess.base(event, agent)
    if extra:
        p.update(extra)
    pf = f"/tmp/.rv_payload_{uuid.uuid4().hex}.json"
    # payload file lives outside the snapshot noise: write to /mnt/sb instead
    pf = f"/mnt/sb/payloads/{label.replace('/', '_').replace(' ', '_')}_{uuid.uuid4().hex[:6]}.json"
    os.makedirs("/mnt/sb/payloads", exist_ok=True)
    with open(pf, "w") as f:
        json.dump(p, f)
    cmd = [sys.executable, RUNHOOK, "--settings", SETTINGS, "--event", event, "--payload", pf,
           "--label", label, "--log", LOG]
    for e in (env or []):
        cmd += ["--env", e]
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stdout.write("RUNNER-STDERR: " + r.stderr[-2000:] + "\n")
    # return last record
    with open(LOG) as f:
        last = json.loads(f.readlines()[-1])
    return last


def blocked(rec):
    return any(h["verdict"].startswith(("BLOCK", "STOP", "ASK")) for h in rec["hooks"])


def tool(sess, name, tinput, perform, label, agent=None):
    """Pre -> (perform if allowed) -> Post, writing transcript tool_use/tool_result."""
    tuid = "toolu_" + uuid.uuid4().hex[:24]
    aid = agent[0] if agent else None
    sess.append({"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-5-5",
                 "content": [{"type": "tool_use", "id": tuid, "name": name, "input": tinput}]}}, aid)
    pre = ev(sess, "PreToolUse", f"PRE {label}", {"tool_name": name, "tool_input": tinput, "tool_use_id": tuid}, agent)
    if blocked(pre):
        sess.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tuid, "is_error": True, "content": "blocked by hook"}]}}, aid)
        return pre, None
    resp = perform() if perform else {}
    sess.append({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tuid, "content": json.dumps(resp)[:2000]}]},
        "toolUseResult": resp}, aid)
    post = ev(sess, "PostToolUse", f"POST {label}",
              {"tool_name": name, "tool_input": tinput, "tool_response": resp, "tool_use_id": tuid}, agent)
    return pre, post


def sh(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=PROJ)
    return {"stdout": p.stdout, "stderr": p.stderr, "interrupted": False, "isImage": False}


def do_read(path):
    def f():
        c = open(path).read()
        return {"type": "text", "file": {"filePath": path, "content": c, "numLines": c.count("\n"),
                                         "startLine": 1, "totalLines": c.count("\n")}}
    return f


def do_edit(path, old, new):
    def f():
        c = open(path).read()
        open(path, "w").write(c.replace(old, new, 1))
        return {"filePath": path, "oldString": old, "newString": new, "originalFile": c,
                "structuredPatch": [], "userModified": False, "replaceAll": False}
    return f


def do_write(path, content):
    def f():
        typ = "update" if os.path.exists(path) else "create"
        open(path, "w").write(content)
        return {"type": typ, "filePath": path, "content": content, "structuredPatch": []}
    return f


AGENT_PROMPT = (
    "Problem: the toy package add() function lacks input validation for non-numeric arguments.\n"
    "Acceptance criteria: add() raises TypeError for non-numeric input; existing test still passes; "
    "a new test covers the TypeError path.\n"
    "Constraints: change only toy/__init__.py and tests/.\n"
    "DO NOT: modify CI config, git history, branches, remotes, or any file outside the toy repository; "
    "DO NOT push; DO NOT create branches or worktrees."
)


def tool_suite(sess, who, agent=None):
    a = agent
    tool(sess, "Read", {"file_path": f"{PROJ}/toy/__init__.py"}, do_read(f"{PROJ}/toy/__init__.py"), f"{who} Read", a)
    tool(sess, "Grep", {"pattern": "def add", "path": PROJ, "output_mode": "files_with_matches"},
         lambda: {"mode": "files_with_matches", "filenames": ["toy/__init__.py"], "numFiles": 1}, f"{who} Grep", a)
    tool(sess, "Glob", {"pattern": "**/*.py", "path": PROJ},
         lambda: {"filenames": [f"{PROJ}/toy/__init__.py", f"{PROJ}/tests/test_add.py"], "durationMs": 3,
                  "numFiles": 2, "truncated": False}, f"{who} Glob", a)
    tool(sess, "Bash", {"command": "ls", "description": "List files"}, lambda: sh("ls"), f"{who} Bash-ls", a)
    tool(sess, "Bash", {"command": "git status", "description": "Show status"}, lambda: sh("git status"), f"{who} Bash-git-status", a)
    tool(sess, "Bash", {"command": "python3 -m pytest -q", "description": "Run tests"},
         lambda: sh(f"{RV_CLAUDE}/venv/bin/python -m pytest -q"), f"{who} Bash-pytest", a)
    tag = who.replace(" ", "_")
    tool(sess, "Edit", {"file_path": f"{PROJ}/toy/__init__.py", "old_string": "return a + b",
                        "new_string": f"return a + b  # {tag}", "replace_all": False},
         do_edit(f"{PROJ}/toy/__init__.py", "return a + b", f"return a + b  # {tag}"), f"{who} Edit-src", a)
    tool(sess, "Write", {"file_path": f"{PROJ}/toy/util_{tag}.py", "content": "def sub(a, b):\n    return a - b\n"},
         do_write(f"{PROJ}/toy/util_{tag}.py", "def sub(a, b):\n    return a - b\n"), f"{who} Write-src", a)
    todos = [{"content": "Add validation", "status": "in_progress", "activeForm": "Adding validation"},
             {"content": "Add test", "status": "pending", "activeForm": "Adding test"}]
    tool(sess, "TodoWrite", {"todos": todos}, lambda: {"oldTodos": [], "newTodos": todos}, f"{who} TodoWrite", a)


def main_phase():
    s = Session()
    print(f"=== MAIN session {s.sid}")
    ev(s, "SessionStart", "SessionStart-startup", {"source": "startup", "model": "claude-opus-5-5"})
    prompt = "What does the add function in the toy package do? Please look and also tidy it."
    ev(s, "UserPromptSubmit", "UPS plain", {"prompt": prompt})
    s.user_text(prompt)
    tool_suite(s, "main")
    # Agent dispatch, foreground
    aid = uuid.uuid4().hex[:17]
    agent_in = {"description": "Validate add inputs", "prompt": AGENT_PROMPT, "subagent_type": "dev",
                "run_in_background": False}
    # subagent tool calls happen "during" the Agent call: Pre(Agent) -> subagent calls -> SubagentStop -> Post(Agent)
    tuid = "toolu_" + uuid.uuid4().hex[:24]
    s.append({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tuid, "name": "Agent", "input": agent_in}]}})
    pre = ev(s, "PreToolUse", "PRE main Agent(dev)", {"tool_name": "Agent", "tool_input": agent_in, "tool_use_id": tuid})
    s.user_text(AGENT_PROMPT, aid)
    tool_suite(s, "dev sub", ("a" + aid, "dev"))
    s.append({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "Done. Added validation; tests pass."}]}}, "a" + aid)
    ev(s, "SubagentStop", "SubagentStop dev", {"stop_hook_active": False, "agent_id": "a" + aid, "agent_type": "dev",
                                               "agent_transcript_path": s.agent_tpath("a" + aid)})
    resp = {"status": "completed", "agentId": "a" + aid, "prompt": AGENT_PROMPT,
            "content": [{"type": "text", "text": "Done. Added validation; tests pass."}],
            "totalDurationMs": 1000, "totalTokens": 100, "totalToolUseCount": 9}
    s.append({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tuid, "content": "Done."}]}, "toolUseResult": resp})
    ev(s, "PostToolUse", "POST main Agent(dev)", {"tool_name": "Agent", "tool_input": agent_in, "tool_response": resp,
                                                  "tool_use_id": tuid})
    # QA subagent
    qid = "a" + uuid.uuid4().hex[:17]
    qa_in = {"description": "QA add validation", "subagent_type": "qa", "run_in_background": False,
             "prompt": "Verify the add() validation change meets its acceptance criteria. DO NOT modify source files."}
    tuid = "toolu_" + uuid.uuid4().hex[:24]
    s.append({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tuid, "name": "Agent", "input": qa_in}]}})
    ev(s, "PreToolUse", "PRE main Agent(qa)", {"tool_name": "Agent", "tool_input": qa_in, "tool_use_id": tuid})
    s.user_text(qa_in["prompt"], qid)
    tool_suite(s, "qa sub", (qid, "qa"))
    s.append({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "QA PASS"}]}}, qid)
    ev(s, "SubagentStop", "SubagentStop qa", {"stop_hook_active": False, "agent_id": qid, "agent_type": "qa",
                                              "agent_transcript_path": s.agent_tpath(qid)})
    resp = {"status": "completed", "agentId": qid, "content": [{"type": "text", "text": "QA PASS"}]}
    s.append({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tuid, "content": "QA PASS"}]}, "toolUseResult": resp})
    ev(s, "PostToolUse", "POST main Agent(qa)", {"tool_name": "Agent", "tool_input": qa_in, "tool_response": resp,
                                                 "tool_use_id": tuid})
    s.append({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "The add function returns a + b. Validation was added."}]}})
    ev(s, "Stop", "Stop normal", {"stop_hook_active": False})
    ev(s, "SessionEnd", "SessionEnd", {"reason": "prompt_input_exit"})
    ev(s, "SessionStart", "SessionStart-resume", {"source": "resume", "model": "claude-opus-5-5"})
    return s


SLASH = [
    ("/spec", "add input validation to toy.add"),
    ("/dev", "add input validation to toy.add"),
    ("/do", "rename README heading"),
    ("/dev-command", "add a /lint command"),
    ("/dev-overnight", "harden toy package"),
    ("/close", ""),
    ("/commit", ""),
    ("/merge", ""),
    ("/push", ""),
    ("/restart", ""),
    ("/allow", "git status"),
    ("/clean", ""),
]


def slash_phase():
    for cmd, args in SLASH:
        s = Session()
        print(f"=== SLASH {cmd} session {s.sid}")
        prompt = f"{cmd} {args}".strip()
        ev(s, "UserPromptSubmit", f"UPS {cmd}", {"prompt": prompt})
        name = cmd.lstrip("/")
        s.user_text(f"<command-message>{name} is running…</command-message>\n<command-name>{cmd}</command-name>\n"
                    f"<command-args>{args}</command-args>")


if __name__ == "__main__":
    if PHASE in ("main", "all"):
        main_phase()
    if PHASE in ("slash", "all"):
        slash_phase()
