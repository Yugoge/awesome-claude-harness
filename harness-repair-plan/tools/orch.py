import sys, os
sys.argv=["baseline.py", sys.argv[1], sys.argv[2], "none"]
sys.path.insert(0,"/mnt/sb/tools")
import baseline as b
P=b.PROJ
open(f"{P}/big.txt","w").write("line\n"*700)
s=b.Session()
b.ev(s,"UserPromptSubmit","UPS turn1",{"prompt":"tidy up"}); s.user_text("tidy up")
b.tool(s,"Edit",{"file_path":f"{P}/README.md","old_string":"# toy","new_string":"# toy1"},b.do_edit(f"{P}/README.md","# toy","# toy1"),"turn1 Edit#1")
b.tool(s,"Read",{"file_path":f"{P}/README.md"},b.do_read(f"{P}/README.md"),"turn1 Read between")
b.tool(s,"Edit",{"file_path":f"{P}/README.md","old_string":"# toy1","new_string":"# toy2"},b.do_edit(f"{P}/README.md","# toy1","# toy2"),"turn1 Edit#2 (expect block)")
for i in range(6):
    b.tool(s,"Bash",{"command":f"echo {i}"},lambda: b.sh("true"),f"turn1 Bash#{i+1}")
b.tool(s,"Read",{"file_path":f"{P}/big.txt"},b.do_read(f"{P}/big.txt"),"Read 700-line file (expect block)")
b.tool(s,"Read",{"file_path":f"{P}/big.txt","offset":1,"limit":100},b.do_read(f"{P}/big.txt"),"Read 700-line file limit=100")
b.tool(s,"Agent",{"description":"x","prompt":"Describe toy. DO NOT modify files.","subagent_type":"Explore"},None,"Agent w/o run_in_background (expect block)")
b.tool(s,"Agent",{"description":"x","prompt":"Describe toy. DO NOT modify files.","subagent_type":"Explore","run_in_background":True},None,"Agent run_in_background=true (expect block)")
s.append({"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}})
b.ev(s,"Stop","Stop turn1",{"stop_hook_active":False})
b.ev(s,"UserPromptSubmit","UPS turn2",{"prompt":"one more tweak"}); s.user_text("one more tweak")
b.tool(s,"Edit",{"file_path":f"{P}/README.md","old_string":"# toy","new_string":"# toyX"},b.do_edit(f"{P}/README.md","# toy","# toyX"),"turn2 Edit#1 (expect allow)")
