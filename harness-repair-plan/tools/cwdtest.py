import sys, os
sys.argv=["baseline.py", sys.argv[1], sys.argv[2], "none"]
sys.path.insert(0,"/mnt/sb/tools")
import baseline as b
for cwd in ["/root/notgit", "/root/toyproj/toy"]:
    os.makedirs(cwd, exist_ok=True)
    b.PROJ = cwd
    s=b.Session()
    for src in ["startup","resume","clear","compact"]:
        b.ev(s,"SessionStart",f"SS {src} cwd={cwd}",{"source":src})
    b.ev(s,"UserPromptSubmit",f"UPS plain cwd={cwd}",{"prompt":"hi"}); s.user_text("hi")
    b.tool(s,"Bash",{"command":"ls"},lambda: b.sh("ls"),f"Bash ls cwd={cwd}")
    b.tool(s,"Write",{"file_path":f"{cwd}/new_{os.getpid()}.txt","content":"x\n"},b.do_write(f"{cwd}/new_{os.getpid()}.txt","x\n"),f"Write cwd={cwd}")
    b.ev(s,"Stop",f"Stop cwd={cwd}",{"stop_hook_active":False})
    b.ev(s,"UserPromptSubmit",f"UPS /dev cwd={cwd}",{"prompt":"/dev add a thing"})
    b.ev(s,"SessionEnd",f"SessionEnd cwd={cwd}",{"reason":"clear"})
