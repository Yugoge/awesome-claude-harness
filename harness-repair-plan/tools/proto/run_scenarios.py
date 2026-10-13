#!/usr/bin/env python3
"""Run current Stop hooks (HEAD copy) and the prototype unified gate over the
same synthetic sessions. Scratch only; writes nothing outside its own scratch directory."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
H = W / "harness"
sys.path.insert(0, str(W / "proto")); sys.path.insert(0, str(W / "harness" / "tests"))
from txbuild import Tx, with_status, obligation  # noqa: E402

ENV = {"PATH": os.environ["PATH"], "HOME": str(W / "home"), "CLAUDE_STATE_DIR": str(W / "state"),
       "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
CURRENT = ["stop-workflow-coordinator.py", "stop-do-report-gate.py", "stop-obligation-gate.py",
           "stop-completion-gate.py"]
spec = importlib.util.spec_from_file_location("fx", H / "tests" / "test_resolve_dev_artifact_chain.py")


def todos(cmd, args=""):
    r = subprocess.run([sys.executable, str(H / "scripts/todo" / f"{cmd}.py")], capture_output=True, text=True,
                       env={**ENV, "CLAUDE_TODO_PROMPT": f"/{cmd} {args}"}, cwd=str(H / "scripts/todo"))
    return json.loads(r.stdout)


def git(root, *a, check=True):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, env=ENV, check=check)


def project(name):
    p = W / "projs" / name
    shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True)
    git(p, "init", "-q", "-b", "master")
    (p / "README").write_text("x\n")
    git(p, "add", "-A")
    git(p, "commit", "-qm", "init")
    return p


def prompt_hook(proj, sid, text, tx_path):
    _ = None
    pl = {"session_id": sid, "transcript_path": str(tx_path), "cwd": str(proj), "prompt": text,
          "hook_event_name": "UserPromptSubmit"}
    r = subprocess.run([sys.executable, str(H / "hooks/prompt-workflow.py")], input=json.dumps(pl),
                       capture_output=True, text=True, env={**ENV, "CLAUDE_PROJECT_DIR": str(proj)}, cwd=str(proj))
    if r.returncode or r.stderr.strip():
        print("PROMPT HOOK rc", r.returncode, "stderr", r.stderr[-800:])
    return r.stdout


def stop(proj, sid, tx_path, last, active=False, hooks=None, proto=False):
    pl = {"session_id": sid, "transcript_path": str(tx_path), "cwd": str(proj), "hook_event_name": "Stop",
          "stop_hook_active": active, "last_assistant_message": last}
    out = {}
    env = {**ENV, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_OBLIGATION_TERMINAL": "block",
           "PROTO_HARNESS": str(H)}
    targets = [(n, H / "hooks" / n) for n in (hooks or CURRENT)] if not proto else \
        [("proto", W / "proto" / "stop_command_gate.py")]
    for name, path in targets:
        r = subprocess.run([sys.executable, str(path)], input=json.dumps(pl), capture_output=True, text=True,
                           env=env, cwd=str(proj), timeout=200)
        out[name] = (r.returncode, (r.stderr.strip().splitlines() or [""])[0][:150],
                     len(r.stderr), (r.stdout.strip()[:120]))
    return out


RESULTS = []


def record(name, d):
    RESULTS.append((name, d))
    print(f"== {name}")
    for k, v in d.items():
        print(f"   {k:32s} rc={v[0]} stderr_bytes={v[2]} | {v[1]} | stdout={v[3]}")


def scenario_dev_abandon():
    proj = project("dev-abandon"); sid = "sess-dev1"; tp = W / "tx" / "dev1.jsonl"
    tx = Tx(tp, sid); tx.slash("dev", "fix the calculator")
    prompt_hook(proj, sid, "/dev fix the calculator", tp)
    td = todos("dev"); tx.todo(with_status(td, 0)); tx.todo(with_status(td, 1))
    last = tx.text("Done. The calculator is fixed."); tx.write()
    record("S1 /dev stop at 1/17 todos, QA never dispatched [current hooks]", stop(proj, sid, tp, last))
    record("S1 same [proto gate]", stop(proj, sid, tp, last, proto=True))
    record("S1 same, stop_hook_active=true [proto gate: no bound]", stop(proj, sid, tp, last, active=True, proto=True))
    last2 = tx.text("BA needs a decision.\nAWAITING_INPUT: need=choose rounding mode; why=spec is silent; addressee=human")
    tx.write()
    record("S1b question pause final line [proto gate]", stop(proj, sid, tp, last2, proto=True))
    tx.say("use banker's rounding")  # plain answer continues the /dev span
    last3 = tx.text("ok, continuing later"); tx.write()
    record("S1c plain-text answer keeps /dev span; stop without pause [proto gate]",
           stop(proj, sid, tp, last3, proto=True))
    tx.slash("allow", "git status"); last4 = tx.text("allowed"); tx.write()
    record("S1d /allow is a control command; /dev span kept [proto gate]", stop(proj, sid, tp, last4, proto=True))
    tx.slash("stop"); last5 = tx.text("stopped"); tx.write()
    record("S1e human /stop opens a non-gated span (release) [proto gate]", stop(proj, sid, tp, last5, proto=True))


def scenario_dev_complete(qa_status="pass"):
    proj = project(f"dev-complete-{qa_status}"); sid = f"sess-dev2-{qa_status}"; tp = W / "tx" / f"dev2-{qa_status}.jsonl"
    tx = Tx(tp, sid); tx.slash("dev", "add feature")
    out = prompt_hook(proj, sid, "/dev add feature", tp)
    import re as _re
    dsid = _re.search(r"DEV_SESSION_ID pre-initialized by hook: (\S+)", out).group(1)
    fx = importlib.util.module_from_spec(spec); fx.__dict__["__file__"] = str(H / "tests/x.py")
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    spec.loader.exec_module(fx)
    task = dsid[len("dev-"):]
    fx.TASK_ID = task
    paths = fx._make_singular(proj)
    if qa_status != "pass":
        fx._write(paths["qa"], fx._qa_document(task, qa_status))
    td = todos("dev")
    tx.tool("Agent", {"subagent_type": "ba", "prompt": "BA\n" + obligation(dsid, "ba", "dev")})
    tx.tool("Agent", {"subagent_type": "qa", "prompt": "QA\n" + obligation(task, "qa", "dev")})
    tx.todo(with_status(td, len(td), in_progress=False))
    last = tx.text("Development completed."); tx.write()
    record(f"S2 /dev 17/17 todos, chain qa.status={qa_status} [current hooks]", stop(proj, sid, tp, last))
    record(f"S2 same [proto gate]", stop(proj, sid, tp, last, proto=True))
    return proj, task


def scenario_do(status):
    proj = project(f"do-{status}"); sid = f"sess-do-{status}"; tp = W / "tx" / f"do-{status}.jsonl"
    tx = Tx(tp, sid); tx.slash("do", "rename a var")
    prompt_hook(proj, sid, "/do rename a var", tp)
    task = json.loads((W / "state" / f"claude-do-task-{sid}.json").read_text())["task_id"]
    rp = proj / "docs/dev" / f"do-report-{task}.json"
    if status != "pending":
        doc = json.loads(rp.read_text()); doc["do"].update(status=status, summary="renamed", files_modified=[],
                                                           files_created=[])
        rp.write_text(json.dumps(doc))
    td = todos("do"); tx.todo(with_status(td, len(td), in_progress=False))
    last = tx.text("Done."); tx.write()
    for i in range(3):
        record(f"S3 /do report={status} stop #{i + 1} [current do-report gate]",
               stop(proj, sid, tp, last, active=i > 0, hooks=["stop-do-report-gate.py"]))
    flag = W / "state" / f"claude-orchestrator-consent-{sid}.flag"
    flag.write_text("true")
    for i in range(2):
        record(f"S3 /do report={status} stop #{i + 1} [proto gate] consent_flag_before={flag.exists()}",
               stop(proj, sid, tp, last, active=i > 0, proto=True))
    print("   consent flag after proto:", flag.exists())


def scenario_commit_merge_push():
    proj, task = scenario_dev_complete("pass")
    # close report YES
    (proj / "docs/dev" / f"close-report-{task}.md").write_text(f"# Close\nTask-id: {task}\n\nCLOSE: YES\n")
    sid = "sess-commit"; tp = W / "tx" / "commit.jsonl"
    tx = Tx(tp, sid); tx.slash("commit", task)
    tx.tool("Agent", {"subagent_type": "changelog-analyst", "prompt": "commit\n" + obligation(
        task, "changelog-analyst", "commit", "commit-landing",
        [{"kind": "response_block", "begin": "B", "end": "E", "format": "json", "schema": "changelog-status.v1"}])})
    last = tx.text("Committed."); tx.write()
    record("S4 /commit, nothing actually committed [current hooks]", stop(proj, sid, tp, last))
    record("S4 same [proto gate]", stop(proj, sid, tp, last, proto=True))
    git(proj, "add", "-A"); git(proj, "commit", "-qm", f"feat: x\n\nTask-id: {task}")
    record("S4b after a commit carrying the Task-id trailer [proto gate]", stop(proj, sid, tp, last, proto=True))
    # merge
    git(proj, "checkout", "-qb", "feature"); (proj / "f.txt").write_text("f\n"); git(proj, "add", "-A")
    git(proj, "commit", "-qm", "feature"); tip = git(proj, "rev-parse", "HEAD").stdout.strip()
    git(proj, "checkout", "-q", "master")
    sid = "sess-merge"; tp = W / "tx" / "merge.jsonl"; tx = Tx(tp, sid); tx.slash("merge", "feature")
    tx.tool("Agent", {"subagent_type": "merge-analyst", "prompt":
                      f"RESOLVED_REF=feature\nSOURCE_TIP={tip}\nDEFAULT_BRANCH=master\nREPO_ROOT={proj}\n"})
    last = tx.text("Merged."); tx.write()
    record("S5 /merge, merge never executed [current hooks]", stop(proj, sid, tp, last))
    record("S5 same [proto gate]", stop(proj, sid, tp, last, proto=True))
    git(proj, "merge", "-q", "--no-edit", "feature")
    record("S5b after merge [proto gate]", stop(proj, sid, tp, last, proto=True))
    # push
    bare = W / "projs" / "origin.git"; shutil.rmtree(bare, ignore_errors=True)
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=ENV)
    git(proj, "remote", "add", "origin", str(bare))
    sid = "sess-push"; tp = W / "tx" / "push.jsonl"; tx = Tx(tp, sid); tx.slash("push")
    tx.tool("Agent", {"subagent_type": "push-analyst", "prompt": "BRANCH=master\nREMOTE_NAME=origin\n"})
    last = tx.text("Pushed."); tx.write()
    record("S6 /push, nothing pushed [current hooks minus coordinator]",
           stop(proj, sid, tp, last, hooks=CURRENT[1:]))
    record("S6 same [proto gate]", stop(proj, sid, tp, last, proto=True))
    git(proj, "push", "-q", "origin", "master")
    record("S6b after push [proto gate]", stop(proj, sid, tp, last, proto=True))


def scenario_subagent():
    proj = project("sub"); tp = W / "tx" / "dev1.jsonl"
    pl = {"session_id": "sess-dev1", "agent_id": "a1", "transcript_path": str(tp), "hook_event_name": "Stop"}
    r = subprocess.run([sys.executable, str(W / "proto/stop_command_gate.py")], input=json.dumps(pl),
                       capture_output=True, text=True, env={**ENV, "PROTO_HARNESS": str(H)})
    record("S7 payload with agent_id [proto gate]", {"proto": (r.returncode, r.stderr[:100], len(r.stderr), "")})


if __name__ == "__main__":
    (W / "state").mkdir(exist_ok=True); (W / "tx").mkdir(exist_ok=True)
    scenario_dev_abandon()
    scenario_dev_complete("fail")
    scenario_do("pending"); scenario_do("blocked"); scenario_do("completed")
    scenario_commit_merge_push()
    scenario_subagent()
    json.dump([(n, {k: list(v) for k, v in d.items()}) for n, d in RESULTS],
              open(W / "results.json", "w"), indent=1)


def scenario_extra():
    proj = project("extra"); sid = "sess-x"; tp = W / "tx" / "extra.jsonl"
    tx = Tx(tp, sid); tx.slash("dev", "x")
    td = todos("dev"); tx.todo(with_status(td, 0))
    tx.slash("model", "opus")  # CLI built-in: not a harness command file
    last = tx.text("switched model"); tx.write()
    record("S8 built-in /model mid-cycle keeps the /dev span [proto gate]", stop(proj, sid, tp, last, proto=True))
    tx._add({"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit", "apiErrorStatus": 429,
             "message": {"role": "assistant", "content": [{"type": "text", "text": "API Error: 429"}]}})
    tx.write()
    record("S9 CLI API-error final record (quota) [proto gate]", stop(proj, sid, tp, "API Error: 429", proto=True))
    # overnight time-lock, span-independent, pause not honoured
    from datetime import datetime, timedelta, timezone
    (proj / ".claude").mkdir(exist_ok=True)
    st = {"session_id": sid, "end_time": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    (proj / ".claude" / f"overnight-state-{sid}.json").write_text(json.dumps(st))
    tx.slash("commit", "x")
    last = tx.text("need you\nAWAITING_INPUT: need=x; why=y; addressee=human"); tx.write()
    record("S10 live time-lock + other command + pause line [proto gate]", stop(proj, sid, tp, last, proto=True))
    for tz in ("Asia/Shanghai", "America/Los_Angeles"):
        os.environ["TZ"] = tz
        ENV["TZ"] = tz
        record(f"S10b same under TZ={tz} [proto gate]", stop(proj, sid, tp, last, proto=True))
    ENV.pop("TZ", None)
    st["terminal_status"] = "cancelled_by_user"
    (proj / ".claude" / f"overnight-state-{sid}.json").write_text(json.dumps(st))
    record("S10c after human /stop cancel, pause honoured [proto gate]", stop(proj, sid, tp, last, proto=True))


def scenario_close_auto():
    proj, task = scenario_dev_complete("pass")
    sid = "sess-close-auto"; tp = W / "tx" / "close-auto.jsonl"
    tx = Tx(tp, sid); tx.slash("close", "--auto")
    tx.tool("Bash", {"command": "python3 scripts/dev-lifecycle.py list-actionable --next-action close --project-dir ."},
            result=f"{task}\n")
    tx.todo(with_status(todos("close", "--auto"), 3, in_progress=False))
    last = tx.text("closed all"); tx.write()
    record("S11 /close --auto, snapshot task has no close-report [proto gate]", stop(proj, sid, tp, last, proto=True))
    (proj / "docs/dev" / f"close-report-{task}.md").write_text(f"# Close\nTask-id: {task}\n\nCLOSE: YES\n")
    record("S11b after CLOSE: YES [proto gate]", stop(proj, sid, tp, last, proto=True))


if __name__ == "__main__" and os.environ.get("EXTRA"):
    RESULTS.clear()
    scenario_extra()
    scenario_close_auto()
