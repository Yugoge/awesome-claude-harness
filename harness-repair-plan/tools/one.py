#!/usr/bin/env python3
# one.py <settings> <log> <label> <event> <json-extra> [sid]  -- single hook event in a (new or given) session
import sys, json
sys.path.insert(0, "/mnt/sb/tools")
sys.argv_saved = sys.argv[:]
SETTINGS, LOG, LABEL, EVENT, EXTRA = sys.argv[1:6]
SID = sys.argv[6] if len(sys.argv) > 6 else None
sys.argv = ["baseline.py", SETTINGS, LOG, "none"]
import baseline as b
s = b.Session(SID)
extra = json.loads(EXTRA)
agent = None
if "agent_id" in extra:
    agent = (extra.pop("agent_id"), extra.pop("agent_type"))
if "_transcript_user" in extra:
    s.user_text(extra.pop("_transcript_user"))
b.ev(s, EVENT, LABEL, extra, agent)
print("SID", s.sid)
