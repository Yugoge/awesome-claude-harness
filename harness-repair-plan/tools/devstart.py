import sys, json, glob
sys.argv=["baseline.py", sys.argv[1], sys.argv[2], "none"]
sys.path.insert(0,"/mnt/sb/tools")
import baseline as b
P=b.PROJ
s=b.Session()
b.ev(s,"SessionStart","SS",{"source":"startup"})
r=b.ev(s,"UserPromptSubmit","UPS /dev",{"prompt":"/dev add input validation to toy.add"})
inj=[h for h in r["hooks"] if h["hook"]=="prompt-workflow.py"][0]
s.user_text("<command-message>dev is running…</command-message>\n<command-name>/dev</command-name>\n<command-args>add input validation to toy.add</command-args>")
b.tool(s,"Read",{"file_path":f"{P}/toy/__init__.py"},b.do_read(f"{P}/toy/__init__.py"),"after /dev: Read before TodoWrite")
b.tool(s,"Agent",{"description":"BA spec","prompt":"Problem: add() lacks validation. Acceptance: TypeError on non-numeric. DO NOT edit code.","subagent_type":"ba","run_in_background":False},None,"after /dev: Agent(ba) before TodoWrite")
todo=json.load(open(sorted(glob.glob(f"/root/.claude/todos/{s.sid}-agent-*.json"))[-1]))
print("todos file entries:",len(todo)); print([t.get("content","")[:60] for t in todo[:4]])
todo[0]["status"]="in_progress"
b.tool(s,"TodoWrite",{"todos":todo},lambda: {"oldTodos":[],"newTodos":todo},"TodoWrite (canonical list, step1 in_progress)")
b.tool(s,"Read",{"file_path":f"{P}/toy/__init__.py"},b.do_read(f"{P}/toy/__init__.py"),"after TodoWrite: Read")
b.tool(s,"Agent",{"description":"BA spec","prompt":"Problem: add() lacks validation. Acceptance: TypeError on non-numeric. DO NOT edit code.","subagent_type":"ba","run_in_background":False},None,"after TodoWrite: Agent(ba)")
