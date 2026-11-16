#!/usr/bin/env bash
# Description: Record the installed Claude Code CLI's hook records and hook stdin as test fixtures.
# Usage: bash scripts/cli-fixture-record.sh [--out <dir>] [--keep-raw <dir>]
#   Runs the installed CLI headless, twice in one session, in a throwaway HOME whose minimal
#   settings.json registers trivial hooks (SessionStart; UserPromptSubmit plain stdout;
#   UserPromptSubmit JSON additionalContext; PreToolUse; Stop; SubagentStop). The second
#   prompt dispatches a subagent, so SubagentStop fires and a subagent transcript is written.
#   Writes tests/fixtures/cli/<version>/{transcript.jsonl,subagent.jsonl,stdin/<Event>.json,
#   shapes.json} and sets tests/fixtures/cli/CURRENT to <version>.
# Kept: hook attachment records, system/stop_hook_summary, the user/assistant envelopes and
#   each event's hook stdin. Home, cwd, uuids and timestamps become placeholders; every other
#   string becomes "<redacted>" unless its key is a structural one (type, hookEvent, ...) or it
#   is a marker this script's own hooks print. No prompt or system-prompt text is kept.
# Cost: about $0.03 and 30 s a run; it needs the CLI's model access. Run it on a CLI upgrade,
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
mkdir -p "$HOME_DIR/.claude" "$WORK_DIR" "$RAW/stdin"
HOME_DIR="$(cd "$HOME_DIR" && pwd -P)"
WORK_DIR="$(cd "$WORK_DIR" && pwd -P)"

# The one hook program: saves its stdin under raw/stdin/<Event>[.<mode>].json, then prints.
cat > "$HOME_DIR/.claude/fixture-hook.py" <<'PY'
import json, os, sys
event, mode = sys.argv[1], sys.argv[2]
data = sys.stdin.read()
if mode != "json":  # the JSON-output hook of an event sees the same stdin as its plain one
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
    "SubagentStop": [entry("SubagentStop", "plain")],
}}
with open(path, "w") as fh:
    json.dump(settings, fh, indent=2)
PY

SESSION="$(python3 -c 'import uuid; print(uuid.uuid4())')"
run_cli() {
  # The throwaway HOME is the CLI's whole config; nothing of the caller's home or session is read.
  (cd "$WORK_DIR" && env -u CLAUDECODE -u CLAUDE_CONFIG_DIR -u CLAUDE_PROJECT_DIR -u CLAUDE_HOME \
      HOME="$HOME_DIR" FIXTURE_RAW="$RAW" "$CLI" -p "$@" --max-turns 6 \
      --allowedTools "Agent Task" --output-format json >>"$RAW/cli-output.log" 2>>"$RAW/cli-stderr.log" \
    || echo "cli-fixture-record: a CLI run exited $? (see what still recorded)" >&2)
}
run_cli --session-id "$SESSION" "Reply with the single word ok."
run_cli --resume "$SESSION" \
  "Use the Agent tool once to dispatch a general-purpose subagent whose only task is to reply with the single word ok. Then reply with the single word ok."

if [[ -n "$KEEP_RAW" ]]; then
  mkdir -p "$KEEP_RAW" && cp -r "$RAW" "$HOME_DIR/.claude/projects" "$KEEP_RAW"/ 2>/dev/null || true
fi

DEST="$OUT_ROOT/$VERSION"
python3 - "$HOME_DIR" "$WORK_DIR" "$SESSION" "$RAW" "$DEST" <<'PY'
import json, pathlib, re, sys

home, cwd, session, raw, dest = sys.argv[1:6]
raw, dest = pathlib.Path(raw), pathlib.Path(dest)
projects = pathlib.Path(home) / ".claude" / "projects"

UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?")
API_ID = re.compile(r"\b(toolu|msg|req)_[0-9A-Za-z]+\b")
USER_TMP = re.compile(r"/tmp/claude-\d+(?=/)")
# The kept values of `command`: the label the CLI itself records for a command hook.
CLI_COMMAND_LABEL = re.compile(r"^command hook( \d+)?$")
# Keys whose string value is structure (a record kind, an event or a tool name), never text.
KEEP = {"type", "subtype", "role", "hookEvent", "hookName", "hook_event_name", "permission_mode",
        "permissionMode", "stop_reason", "stop_sequence", "model", "userType", "entrypoint", "version",
        "level", "name", "tool_name", "matcher", "source", "effort", "service_tier", "agentType",
        "subagent_type", "agent_type", "operation", "isSidechain", "outputStyle", "gitBranch",
        "promptSource", "turnOrigin", "madeBy", "renderedRole", "perTurnEffort", "requestedModel",
        "resolvedModel", "promptCacheRequested", "speed", "status", "decision", "reasonType", "ruleSource"}
MARKERS = re.compile(r"^(fixture-plain-stdout|fixture-additional-context)-[A-Za-z]+\n?$")

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

def clean(value, key=None):
    if isinstance(value, dict):
        return {scrub(k): clean(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v, key) for v in value]
    if isinstance(value, str):
        s = scrub(value)
        if not s or key in KEEP or MARKERS.match(s) or (key == "command" and CLI_COMMAND_LABEL.match(s)):
            return s
        if s != value and not re.search(r"\s", s):  # an id or a path, its machine parts replaced
            return s
        return "<redacted>"
    return value

def wanted(rec):
    t = rec.get("type")
    if t in ("user", "assistant"):
        return True
    if t == "attachment":
        a = rec.get("attachment")
        return isinstance(a, dict) and str(a.get("type", "")).startswith("hook_")
    if t == "system":
        return rec.get("subtype") == "stop_hook_summary" or "hook" in str(rec.get("subtype", "")).lower()
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

main = next(iter(projects.glob(f"*/{session}.jsonl")), None)
subs = sorted(projects.glob(f"**/{session}/subagents/*.jsonl")) or sorted(
    p for p in projects.glob("**/agent-*.jsonl") if p != main)
dest.mkdir(parents=True, exist_ok=True)
(dest / "stdin").mkdir(exist_ok=True)
n_main = keep_file(main, dest / "transcript.jsonl")
n_sub = keep_file(subs[0] if subs else None, dest / "subagent.jsonl")
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
