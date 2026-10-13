import json, subprocess, uuid, os
P="/root/toyproj"
for cmd in ["/spec add validation", "/dev add validation", "/do rename heading", "/dev-command add lint cmd", "/close", "/clean", "/commit", "/push"]:
    sid=str(uuid.uuid4()); tp=f"/root/.claude/projects/-root-toyproj/{sid}.jsonl"; os.makedirs(os.path.dirname(tp),exist_ok=True); open(tp,"w").close()
    p={"session_id":sid,"transcript_path":tp,"cwd":P,"hook_event_name":"UserPromptSubmit","permission_mode":"default","prompt":cmd}
    r=subprocess.run(["python3","/root/.claude/hooks/prompt-workflow.py"],input=json.dumps(p),capture_output=True,text=True,cwd=P,env=dict(os.environ,CLAUDE_PROJECT_DIR=P,HOME="/root"))
    md=f"/root/.claude/commands/{cmd.split()[0][1:]}.md"
    print(f"{cmd:28s} rc={r.returncode} injected_chars={len(r.stdout):7d} command_md_chars={os.path.getsize(md) if os.path.exists(md) else 0:7d} stdout_is_json={r.stdout.strip().startswith('{')}")
