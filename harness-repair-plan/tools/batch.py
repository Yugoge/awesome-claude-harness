#!/usr/bin/env python3
# batch.py <settings> <log> -- legit-call matrix through PreToolUse, new session per call
import json, os, subprocess, sys, uuid
SETTINGS, LOG = sys.argv[1], sys.argv[2]
P = "/root/toyproj"
BASH = ["ls -la", "cat README.md", "head -20 toy/__init__.py", "grep -rn 'def add' .", "find . -name '*.py'",
        "git status", "git diff", "git log --oneline -5", "git diff --stat", "git show HEAD --stat", "git branch",
        "git add toy/__init__.py", "git stash list", "git fetch origin", "git restore toy/__init__.py",
        "python3 -m pytest -q", "pytest -q", "python3 -c 'print(1)'", "cd tests && python3 -m pytest -q",
        "ls | wc -l", "wc -l toy/*.py", "mkdir -p build && echo hi > build/out.txt", "rm build/out.txt",
        "sed -i 's/a + b/b + a/' toy/__init__.py", "echo x > /tmp/scratch.txt", "mktemp", "jq . package.json",
        "make test", "npm test", "pip list", "git commit -m 'add validation'", "git push origin master",
        "git pull --ff-only", "git checkout -- toy/__init__.py", "git log -p -1", "tree -L 2",
        "python3 -m pip install -r requirements.txt", "env | sort", "which python3", "date"]
EDITS = [("Edit", {"file_path": f"{P}/README.md", "old_string": "# toy", "new_string": "# toy project"}),
         ("Write", {"file_path": f"{P}/tests/test_sub.py", "content": "def test_x():\n    assert True\n"}),
         ("Write", {"file_path": f"{P}/docs/notes.md", "content": "notes\n"}),
         ("Edit", {"file_path": f"{P}/tests/test_add.py", "old_string": "== 5", "new_string": "== 5  # ok"}),
         ("Write", {"file_path": f"{P}/toy/__init__.py", "content": "def add(a, b):\n    return a + b\n"}),
         ("Read", {"file_path": f"{P}/toy/__init__.py"}),
         ("Read", {"file_path": f"{P}/README.md", "offset": 1, "limit": 10}),
         ("Grep", {"pattern": "add", "path": P}),
         ("Glob", {"pattern": "**/*.md"}),
         ("TodoWrite", {"todos": [{"content": "x", "status": "pending", "activeForm": "x"}]}),
         ("Agent", {"description": "Explore toy", "prompt": "Describe the toy package structure. DO NOT modify files.",
                    "subagent_type": "Explore", "run_in_background": False}),
         ("Agent", {"description": "Explore toy", "prompt": "Describe the toy package structure. DO NOT modify files.",
                    "subagent_type": "general-purpose", "run_in_background": False}),
         ("WebFetch", {"url": "https://example.com", "prompt": "summarize"}),
         ("WebSearch", {"query": "python typeerror"}),
         ("Skill", {"skill": "simplify"}),
         ("AskUserQuestion", {"questions": [{"question": "ok?", "header": "q", "options": [{"label": "y", "description": "y"}, {"label": "n", "description": "n"}], "multiSelect": False}]})]
whos = [("main", None), ("dev", ("a" + uuid.uuid4().hex[:16], "dev")), ("qa", ("a" + uuid.uuid4().hex[:16], "qa")),
        ("Explore", ("a" + uuid.uuid4().hex[:16], "Explore"))]
os.makedirs("/mnt/sb/payloads", exist_ok=True)
for who, agent in whos:
    calls = [("Bash", {"command": c, "description": "x"}) for c in BASH] + EDITS
    for name, ti in calls:
        sid = str(uuid.uuid4())
        tp = f"/root/.claude/projects/-root-toyproj/{sid}.jsonl"
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        with open(tp, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "please help with toy"}, "sessionId": sid, "cwd": P, "uuid": str(uuid.uuid4()), "timestamp": "2026-10-09T09:00:00.000Z"}) + "\n")
        p = {"session_id": sid, "transcript_path": tp, "cwd": P, "hook_event_name": "PreToolUse",
             "permission_mode": "default", "tool_name": name, "tool_input": ti, "tool_use_id": "toolu_" + uuid.uuid4().hex[:20]}
        if agent:
            p["agent_id"], p["agent_type"] = agent
        pf = f"/mnt/sb/payloads/batch_{uuid.uuid4().hex[:8]}.json"
        json.dump(p, open(pf, "w"))
        label = f"{who} {name} {ti.get('command') or ti.get('file_path') or ti.get('subagent_type') or ''}"
        r = subprocess.run([sys.executable, "/mnt/sb/tools/runhook.py", "--settings", SETTINGS, "--event", "PreToolUse",
                            "--payload", pf, "--label", label, "--log", LOG, "--no-snap"], capture_output=True, text=True,
                           env=dict(os.environ, RV_PARALLEL="1"))
        out = r.stdout.strip().splitlines()
        if "blocked=[]" not in out[0] or "errors=[]" not in out[0]:
            print("\n".join(l[:500] for l in out[:4]))
        else:
            print(f"OK  {label}")
