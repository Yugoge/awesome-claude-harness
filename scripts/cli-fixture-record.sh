#!/usr/bin/env bash
# Description: Record the installed Claude Code CLI's hook records and hook stdin as test fixtures.
# Usage: bash scripts/cli-fixture-record.sh [--out <dir>] [--keep-raw <dir>]
#   Runs the installed CLI headless, ten times in one session, in a throwaway HOME whose minimal
#   settings.json registers trivial hooks (SessionStart; UserPromptSubmit plain stdout;
#   UserPromptSubmit JSON additionalContext; PreToolUse; Stop; SubagentStart plain stdout and JSON
#   additionalContext; SubagentStop, plus one SubagentStop hook that blocks the session's first
#   subagent stop once). The first prompt is
#   a typed slash command whose body calls a skill (the Skill expansion record) and Bash; the
#   second dispatches a subagent that calls Bash, so SubagentStop fires (blocked once: the stop
#   hook feedback record) and a subagent transcript is written; the third calls CronCreate (its
#   toolUseResult). The other seven record each way a dispatched agent's end comes back other than
#   by its own Agent call's result: a background dispatch (the launch result, then the
#   task-notification turn); a SendMessage resume of it (its result, then its task-notification);
#   a background agent that ends while the main turn is busy (the notification delivered mid-turn,
#   attachment queued_command); a foreground dispatch whose CLI gets SIGINT mid-run (its error
#   result) and a resumed session's SendMessage to that agent; a foreground dispatch whose CLI is
#   killed mid-run, then a resumed session (the CLI's result for the call the end cut off) that
#   compacts (/compact: system/compact_boundary and the summary record).
#   Writes tests/fixtures/cli/<version>/{transcript.jsonl,subagent.jsonl,subagent.meta.json,
#   stdin/<Event>.json,shapes.json} and sets tests/fixtures/cli/CURRENT to <version>; stdin is
#   the first three runs' (the events of the later runs leave it as those wrote it).
# Kept: hook attachment records, system/stop_hook_summary, system/compact_boundary, the
#   queued_command attachment, the queue-operation, user and assistant envelopes, each event's
#   hook stdin and the first subagent's meta file. Home, cwd, uuids, agent ids and timestamps
#   become placeholders; every other string becomes "<redacted>" unless its key is a structural one
#   (type, hookEvent, ...) or it is a marker this script's own hooks print; a task-notification
#   keeps its tags, its ids (as placeholders) and its status, its text redacted. Token, request
#   and cost counts and a clock time kept as a number become 0. No prompt or system-prompt text
#   is kept.
# Cost: about $3.50 and 5 min for the ten runs on CLI 2.1.326 (the two cut runs wait for their
#   agent to be busy); it needs the CLI's model access. Run it on a CLI upgrade,
#   when scripts/canary-verify.sh prints its re-record advisory. Never in CI (owner decision O1).
# Exit codes: 0 = recorded; 1 = the CLI is missing or recorded no hook record; 2 = bad usage.
set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
OUT_ROOT="$REPO/tests/fixtures/cli"
KEEP_RAW=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT_ROOT="${2:?--out needs a directory}"; shift 2 ;;
    --keep-raw) KEEP_RAW="${2:?--keep-raw needs a directory}"; shift 2 ;;
    -h|--help) sed -n '2,17p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "cli-fixture-record: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

CLI="${CLAUDE_CLI_BIN:-claude}"
command -v "$CLI" >/dev/null 2>&1 || { echo "cli-fixture-record: '$CLI' not found on PATH" >&2; exit 1; }
VERSION="$("$CLI" --version 2>/dev/null | awk 'NR == 1 { print $1 }')"
[[ "$VERSION" =~ ^[0-9][0-9A-Za-z.+-]*$ ]] || { echo "cli-fixture-record: cannot read the CLI version" >&2; exit 1; }

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/cli-fixture-record.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT
HOME_DIR="$SCRATCH/home"
WORK_DIR="$SCRATCH/work"
RAW="$SCRATCH/raw"
mkdir -p "$HOME_DIR/.claude/commands" "$HOME_DIR/.claude/skills/fixture-skill" "$WORK_DIR" "$RAW/stdin"
HOME_DIR="$(cd "$HOME_DIR" && pwd -P)"
WORK_DIR="$(cd "$WORK_DIR" && pwd -P)"

# The one hook program: saves its stdin under raw/stdin/<Event>[.<mode>].json, then prints.
cat > "$HOME_DIR/.claude/fixture-hook.py" <<'PY'
import json, os, sys
event, mode = sys.argv[1], sys.argv[2]
data = sys.stdin.read()
if mode == "block-once":  # the session's first subagent stop is blocked once: the CLI's feedback record
    marker = os.path.join(os.environ["FIXTURE_RAW"], "subagent-stop-blocked")
    if not os.path.exists(marker):
        open(marker, "w").close()
        sys.stderr.write("fixture-subagent-stop-block\n")
        sys.exit(2)
    sys.exit(0)
# The JSON-output hook of an event sees the same stdin as its plain one; the stdin kept is the
# first three runs' (FIXTURE_STDIN).
if mode != "json" and os.environ.get("FIXTURE_STDIN") == "1":
    with open(os.path.join(os.environ["FIXTURE_RAW"], "stdin", event + ".json"), "w") as fh:
        fh.write(data)
if mode == "plain":
    print(f"fixture-plain-stdout-{event}")
elif mode == "json":
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                             "additionalContext": f"fixture-additional-context-{event}"}}))
PY

python3 - "$HOME_DIR/.claude/settings.json" "$HOME_DIR/.claude/fixture-hook.py" <<'PY'
import json, sys
path, hook = sys.argv[1], sys.argv[2]
def entry(event, mode, matcher=None):
    e = {"hooks": [{"type": "command", "command": f"python3 {hook} {event} {mode}"}]}
    if matcher is not None:
        e["matcher"] = matcher
    return e
settings = {"hooks": {
    "SessionStart": [entry("SessionStart", "silent")],
    "UserPromptSubmit": [entry("UserPromptSubmit", "plain"), entry("UserPromptSubmit", "json")],
    "PreToolUse": [entry("PreToolUse", "plain", "*")],
    "Stop": [entry("Stop", "plain")],
    "SubagentStart": [entry("SubagentStart", "plain"), entry("SubagentStart", "json")],
    "SubagentStop": [entry("SubagentStop", "plain"), entry("SubagentStop", "block-once")],
}}
with open(path, "w") as fh:
    json.dump(settings, fh, indent=2)
PY

# The typed command and the skill it calls (a command's isMeta body; a Skill call's isMeta expansion).
printf -- '---\ndescription: fixture command\n---\nUse the Skill tool once with the skill fixture-skill, then run the Bash command true, then reply with the single word ok. $ARGUMENTS\n' \
  > "$HOME_DIR/.claude/commands/fixture.md"
printf -- '---\nname: fixture-skill\ndescription: A fixture skill. Use it when asked to.\n---\nReply with the single word ok.\n' \
  > "$HOME_DIR/.claude/skills/fixture-skill/SKILL.md"

SESSION="$(python3 -c 'import uuid; print(uuid.uuid4())')"
TOOLS="Agent Task Bash Skill CronCreate SendMessage ToolSearch"
STDIN=1
cli() {
  # The throwaway HOME is the CLI's whole config; nothing of the caller's home or session is read.
  cd "$WORK_DIR" && exec env -u CLAUDECODE -u CLAUDE_CONFIG_DIR -u CLAUDE_PROJECT_DIR -u CLAUDE_HOME \
      HOME="$HOME_DIR" FIXTURE_RAW="$RAW" FIXTURE_STDIN="$STDIN" "$CLI" -p "$@" --max-turns 6 \
      --allowedTools "$TOOLS" --output-format json </dev/null >>"$RAW/cli-output.log" 2>>"$RAW/cli-stderr.log"
}
run_cli() {
  (cli "$@") || echo "cli-fixture-record: a CLI run exited $? (see what still recorded)" >&2
}
# A foreground dispatch whose agent runs the busy script; once it runs, the CLI gets signal $1. The
# pattern matches the script's process only (the CLI's own arguments name it too).
printf 'import time\ntime.sleep(61)\n' > "$WORK_DIR/fixture-busy.py"
BUSY_RE='^python3 fixture-busy[.]py'
cut_run() {
  local sig="$1" pid
  (cli --resume "$SESSION" "Use the Agent tool exactly once, with run_in_background set to false, to dispatch a general-purpose subagent whose only task is to run in the foreground, with a 120000 ms timeout, the Bash command: python3 fixture-busy.py and then reply with the single word ok. Then reply with the single word ok.") &
  pid=$!
  for _ in $(seq 1 120); do pgrep -f "$BUSY_RE" >/dev/null && break; sleep 1; done
  sleep 2
  kill "-$sig" "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  pkill -f "$BUSY_RE" 2>/dev/null || true
}
newest_meta_agent() {  # the agent id of the newest subagent meta file of the session
  local f
  f="$(ls -t "$HOME_DIR"/.claude/projects/*/"$SESSION"/subagents/agent-*.meta.json 2>/dev/null | head -1 || true)"
  f="${f##*/agent-}"; printf '%s' "${f%.meta.json}"
}
run_cli --session-id "$SESSION" "/fixture now"
run_cli --resume "$SESSION" \
  "Use the Agent tool once to dispatch a general-purpose subagent whose only task is to run the Bash command true and reply with the single word ok. Then reply with the single word ok."
run_cli --resume "$SESSION" \
  "Use the CronCreate tool once to schedule the prompt noop with cron 7 3 1 1 *, not recurring. Then reply with the single word ok."
STDIN=0
run_cli --resume "$SESSION" \
  "Use the Agent tool exactly once, with run_in_background set to true, to dispatch a general-purpose subagent whose only task is to run the Bash command true and reply with the single word ok. Do not poll or sleep yourself. When you are notified that it completed, reply with the single word ok."
run_cli --resume "$SESSION" \
  "Use the SendMessage tool once to send the background agent you dispatched last the message 'Run the Bash command true, then reply with the single word ok.' Do not poll or sleep yourself. When you are notified that it completed, reply with the single word ok."
run_cli --resume "$SESSION" \
  "First use the Agent tool exactly once, with run_in_background set to true, to dispatch a general-purpose subagent whose only task is to run the Bash command true and reply with the single word ok. Right after it launches, in the same turn, run the Bash command: python3 -c 'import time; time.sleep(25)' with a 60000 ms timeout. Then run the Bash command true. Then reply with the single word ok."
cut_run INT
CUT="$(newest_meta_agent)"
run_cli --resume "$SESSION" \
  "The subagent with agentId $CUT was cut off. Use the SendMessage tool once with to set to $CUT and the message 'Reply with the single word ok.' Do not poll or sleep yourself. When you are notified that it completed, reply with the single word ok."
cut_run KILL
run_cli --resume "$SESSION" "/compact"

if [[ -n "$KEEP_RAW" ]]; then
  mkdir -p "$KEEP_RAW" && cp -r "$RAW" "$HOME_DIR/.claude/projects" "$KEEP_RAW"/ 2>/dev/null || true
fi

DEST="$OUT_ROOT/$VERSION"
python3 - "$HOME_DIR" "$WORK_DIR" "$SESSION" "$RAW" "$DEST" <<'PY'
import json, os, pathlib, re, sys

home, cwd, session, raw, dest = sys.argv[1:6]
raw, dest = pathlib.Path(raw), pathlib.Path(dest)
projects = pathlib.Path(home) / ".claude" / "projects"

UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?")
API_ID = re.compile(r"\b(toolu|msg|req)_[0-9A-Za-z]+\b")
# The CLI's own temporary root, under $TMPDIR (else /tmp): /claude-<uid>/<cwd slug>/<session>/...
USER_TMP = re.compile(re.escape((os.environ.get("TMPDIR") or "/tmp").rstrip("/") or "/tmp") + r"/claude-\d+(?=/)"
                      r"|/tmp/claude-\d+(?=/)")
# The kept values of `command`: the label the CLI itself records for a command hook.
CLI_COMMAND_LABEL = re.compile(r"^command hook( \d+)?$")
# Keys whose string value is structure (a record kind, an event or a tool name), never text.
KEEP = {"type", "subtype", "role", "hookEvent", "hookName", "hook_event_name", "permission_mode",
        "permissionMode", "stop_reason", "stop_sequence", "model", "userType", "entrypoint", "version",
        "level", "name", "tool_name", "matcher", "source", "effort", "service_tier", "agentType",
        "subagent_type", "agent_type", "operation", "isSidechain", "outputStyle", "gitBranch",
        "promptSource", "turnOrigin", "madeBy", "renderedRole", "perTurnEffort", "requestedModel",
        "resolvedModel", "promptCacheRequested", "speed", "status", "decision", "reasonType", "ruleSource",
        "kind", "commandMode", "requestShape"}
MARKERS = re.compile(r"^(fixture-plain-stdout|fixture-additional-context)-[A-Za-z]+\n?$")
# Numbers that tell an account's usage (token, request and cost counts) or the recording's clock.
USAGE_COUNT = re.compile(r"(tokens|Tokens|_usd|_requests)$")
TIME_NUMBERS = {"nextFireAt"}

CWD_SLUG = re.sub(r"[^A-Za-z0-9]", "-", cwd)
AGENT_IDS = sorted({p.stem[len("agent-"):] for p in projects.glob("**/agent-*.jsonl")}, key=len, reverse=True)

def scrub(s):
    s = s.replace(cwd, "<CWD>").replace(home, "<HOME>").replace(CWD_SLUG, "<CWD_SLUG>")
    s = USER_TMP.sub("<TMP>/claude-<UID>", s)
    for agent in AGENT_IDS:
        s = s.replace(agent, "<AGENT_ID>")
    s = UUID.sub("<UUID>", s)
    s = TS.sub("<TIMESTAMP>", s)
    return API_ID.sub("<ID>", s)

# A task-notification keeps its tags, its ids (placeholders), its status and a scrubbed output-file
# path; the text of every other tag is redacted.
NOTIFICATION_TAG = re.compile(r"<([a-z-]+)>(.*?)</\1>", re.S)
NOTIFICATION_KEEP = {"task-id", "tool-use-id", "status"}
OUTPUT_FILE = re.compile(r"<TMP>/claude-<UID>/<CWD_SLUG>/<UUID>/tasks/<AGENT_ID>\.output")

def notification(s):
    def tag(m):
        name, text = m.group(1), m.group(2)
        if name in NOTIFICATION_KEEP:
            return m.group(0)
        if name == "output-file" and OUTPUT_FILE.fullmatch(text):  # every machine part a placeholder
            return m.group(0)
        return f"<{name}><redacted></{name}>"
    inner = s[len("<task-notification>"):s.rindex("</task-notification>")]
    return "<task-notification>" + NOTIFICATION_TAG.sub(tag, inner) + "</task-notification>"

def clean(value, key=None):
    if isinstance(value, dict):
        return {scrub(k): clean(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v, key) for v in value]
    if isinstance(value, str):
        s = scrub(value)
        if s.startswith("<task-notification>") and s.rstrip().endswith("</task-notification>"):
            return notification(s)
        if not s or key in KEEP or MARKERS.match(s) or (key == "command" and CLI_COMMAND_LABEL.match(s)):
            return s
        if s != value and not re.search(r"\s", s):  # an id or a path, its machine parts replaced
            return s
        return "<redacted>"
    if isinstance(value, (int, float)) and not isinstance(value, bool) and key is not None \
            and (USAGE_COUNT.search(key) or key in TIME_NUMBERS):
        return 0  # a usage or cost count, or a clock time as a number: 0 keeps its shape
    return value

def wanted(rec):
    t = rec.get("type")
    if t in ("user", "assistant", "queue-operation"):
        return True
    if t == "attachment":
        a = rec.get("attachment")
        return isinstance(a, dict) and (str(a.get("type", "")).startswith("hook_") or a.get("type") == "queued_command")
    if t == "system":
        return (rec.get("subtype") in ("stop_hook_summary", "compact_boundary")
                or "hook" in str(rec.get("subtype", "")).lower())
    return False

def keep_file(src, out):
    n = 0
    lines = []
    if src is not None and src.exists():
        for line in src.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if wanted(rec):
                lines.append(json.dumps(clean(rec), sort_keys=True))
                n += 1
    out.write_text("".join(l + "\n" for l in lines))
    return n

def started(path):  # the first record's timestamp: the session's first subagent is the second run's
    for line in path.read_text().splitlines():
        if line.strip():
            return str(json.loads(line).get("timestamp", ""))
    return ""

main = next(iter(projects.glob(f"*/{session}.jsonl")), None)
subs = sorted(projects.glob(f"**/{session}/subagents/*.jsonl"), key=started) or sorted(
    p for p in projects.glob("**/agent-*.jsonl") if p != main)
dest.mkdir(parents=True, exist_ok=True)
(dest / "stdin").mkdir(exist_ok=True)
n_main = keep_file(main, dest / "transcript.jsonl")
n_sub = keep_file(subs[0] if subs else None, dest / "subagent.jsonl")
meta = subs[0].with_name(subs[0].stem + ".meta.json") if subs else None
if meta is not None and meta.exists():
    (dest / "subagent.meta.json").write_text(
        json.dumps(clean(json.loads(meta.read_text())), indent=2, sort_keys=True) + "\n")
events = []
for f in sorted((raw / "stdin").glob("*.json")):
    data = json.loads(f.read_text())
    (dest / "stdin" / f.name).write_text(json.dumps(clean(data), indent=2, sort_keys=True) + "\n")
    events.append(f.stem)
print(f"cli-fixture-record: transcript {n_main} records, subagent {n_sub} records, stdin {events}",
      file=sys.stderr)
if not n_main and not events:
    sys.exit(1)
PY

python3 "$REPO/tests/cli_shapes.py" shape "$DEST" > "$DEST/shapes.json"
printf '%s\n' "$VERSION" > "$OUT_ROOT/CURRENT"
echo "cli-fixture-record: wrote $DEST (CURRENT=$VERSION)" >&2
