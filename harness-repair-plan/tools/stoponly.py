import sys
sys.argv=["baseline.py", sys.argv[1], sys.argv[2], "none"]
sys.path.insert(0,"/mnt/sb/tools")
import baseline as b
s=b.Session()
b.ev(s,"SessionStart","SS",{"source":"startup"})
b.ev(s,"UserPromptSubmit","UPS",{"prompt":"tidy add"}); s.user_text("tidy add")
b.tool(s,"Edit",{"file_path":f"{b.PROJ}/toy/__init__.py","old_string":"return a + b","new_string":"return a + b  # x","replace_all":False},b.do_edit(f"{b.PROJ}/toy/__init__.py","return a + b","return a + b  # x"),"main Edit")
s.append({"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}})
r=b.ev(s,"Stop","Stop (no subagent, fresh logs/)",{"stop_hook_active":False})
for h in r["hooks"]:
    print(h["hook"],h["rc"],h["verdict"],h["stdout"][:600].replace("\n"," | "),"ERR:",h["stderr"][:600].replace("\n"," | "))
