"""Dump every PreToolUse Bash decision from a REPLAY_WORK tree's invocations.jsonl files."""
import json, os, sys, hashlib, collections
root, out = sys.argv[1], sys.argv[2]
rows, per_hook = [], collections.Counter()
for dp, dn, fn in os.walk(root):
    if "invocations.jsonl" not in fn or "/sb/" in dp + "/":
        continue
    run = os.path.relpath(dp, root)
    for line in open(os.path.join(dp, "invocations.jsonl"), encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        p = r.get("payload") or {}
        if r.get("event") != "PreToolUse" or p.get("tool_name") != "Bash":
            continue
        cmd = (p.get("tool_input") or {}).get("command") or ""
        verdicts = []
        for h in r.get("hooks") or []:
            name = os.path.basename(h.get("hook", ""))
            verdicts.append(f"{name}={h.get('verdict')}/{h.get('rc')}")
            per_hook[(name, h.get("verdict"))] += 1
        rows.append("\t".join([run, str(r.get("seq")), r.get("label", ""), "subagent" if p.get("agent_id") else "main",
                               hashlib.sha256(cmd.encode()).hexdigest()[:12], json.dumps(cmd)[:300], " ".join(verdicts)]))
rows.sort()
with open(out, "w") as fh:
    fh.write("run\tseq\tlabel\tactor\tcmd_sha12\tcommand(json,300)\thook_verdicts\n")
    fh.writelines(r + "\n" for r in rows)
print(len(rows), "Bash PreToolUse decisions in", len({r.split('\t')[0] for r in rows}), "runs")
for (h, v), n in sorted(per_hook.items()):
    print(f"  {h} {v}: {n}")
