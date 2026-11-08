"""Run every hook a settings file registers for one event, the way the CLI does.

Selection follows the planning kit's runhook.py: a matcher that is empty or "*"
matches everything, a plain name list ("Write|Edit") matches by equality, and
anything else is a regex searched in the event's match value (the tool name for
tool events, the source for SessionStart, and so on); an identical command
registered twice runs once. Each hook gets the payload on stdin, the settings
file's env exported over the replay's base env, and its own timeout (CLI
default 60 s). A hook's verdict is "ok", "block" (exit 2, or exit 0 with a JSON
deny / block / ask / continue:false decision) or "error" (any other exit, a
timeout, or a launch failure).

A run keeps the last TAIL characters of the hook's stdout and stderr. For a
block it also keeps the refusal's head ("refusal_head": its first HEAD
characters, never cutting its first line), taken from the uncut output: the
tail of a long refusal can be its echoed command alone, while the first line
names the block (refusal_first). An allowing hook's hookSpecificOutput.updatedInput
(a PreToolUse rewrite of the tool's input) is kept whole as "updated_input", for
the same reason. What the hook receives and returns is the same.
What a run that did not block hands the model is context(): a driver acting as the
model reads that, never a hook's raw stdout.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"}
DEFAULT_TIMEOUT_S = 60
TAIL = 4000
HEAD = 1000  # a refusal's opening characters kept beside the tail; its first line is kept whole
_HOOK_PATH_RE = re.compile(r"""[^"'\s]*?/((?:hooks|scripts)/[^"'\s]+)""")


def matches(matcher, value) -> bool:
    if matcher in (None, "", "*"):
        return True
    if re.fullmatch(r"[A-Za-z0-9_|]+", matcher):
        return value in matcher.split("|")
    try:
        return re.search(matcher, value or "") is not None
    except re.error:
        return False


def match_value(event: str, payload: dict):
    if event in TOOL_EVENTS:
        return payload.get("tool_name", "")
    key = {"SessionStart": "source", "Notification": "notification_type", "SessionEnd": "reason",
           "SubagentStop": "agent_type", "SubagentStart": "agent_type", "PreCompact": "trigger"}.get(event)
    return payload.get(key, "") if key else None  # None: the event ignores matchers


def hook_name(command: str) -> str:
    """The registered hook file, relative to the harness home (hooks/x.py)."""
    found = _HOOK_PATH_RE.findall(command)
    return found[-1] if found else command


def select(settings: dict, event: str, payload: dict) -> list[dict]:
    mv = match_value(event, payload)
    out, seen = [], set()
    for group in (settings.get("hooks") or {}).get(event, []):
        m = group.get("matcher")
        if mv is not None and not matches(m, mv):
            continue
        for h in group.get("hooks", []):
            cmd = h.get("command")
            if h.get("type", "command") != "command" or not cmd or cmd in seen:
                continue
            seen.add(cmd)
            out.append({"matcher": m, "command": cmd, "hook": hook_name(cmd),
                        "timeout": h.get("timeout") or DEFAULT_TIMEOUT_S})
    return out


def settings_env(settings: dict) -> dict:
    return {k: v if isinstance(v, str) else json.dumps(v) for k, v in (settings.get("env") or {}).items()}


def interpret(rc, stdout: str) -> tuple[str, str]:
    """(verdict, how) for one hook run."""
    if rc == 2:
        return "block", "exit2"
    if rc != 0:
        return "error", "timeout" if rc == "timeout" else f"exit{rc}"
    s = stdout.strip()
    if s.startswith("{"):
        try:
            j = json.loads(s)
        except ValueError:
            j = None
        if isinstance(j, dict):
            pd = (j.get("hookSpecificOutput") or {}).get("permissionDecision")
            if pd in ("deny", "ask"):
                return "block", f"json-{pd}"
            if j.get("decision") == "block":
                return "block", "json-block"
            if j.get("continue") is False:
                return "block", "json-stop"
    return "ok", ""


def refusal(result: dict) -> str:
    """The text a blocking hook gives the model."""
    out = result.get("stdout", "")
    if result.get("how", "").startswith("json"):
        try:
            j = json.loads(out)
            hso = j.get("hookSpecificOutput") or {}
            return str(hso.get("permissionDecisionReason") or j.get("reason") or j.get("stopReason") or out)
        except ValueError:
            pass
    return (result.get("stderr") or out).strip()


# The events whose plain-text stdout the CLI adds as context (hooks reference, "Exit code 0"): for every other
# event an exit-0 hook's plain stdout goes to the debug log only, and its stderr reaches nobody.
PLAIN_CONTEXT_EVENTS = {"UserPromptSubmit", "UserPromptExpansion", "SessionStart", "PostModelSwitch"}


def context(event: str, result: dict) -> str:
    """What the CLI hands the model from one hook run that did not block: its JSON object's
    hookSpecificOutput.additionalContext (the object names this event, as the reference requires), or
    plain-text stdout on the events above; nothing else."""
    if result.get("verdict") != "ok":
        return ""
    out = (result.get("stdout") or "").strip()
    if out.startswith("{") and out.endswith("}"):  # JSON output; unparseable is a non-blocking error
        try:
            hso = json.loads(out).get("hookSpecificOutput")
        except (ValueError, AttributeError):
            return ""
        ok = isinstance(hso, dict) and hso.get("hookEventName") == event
        return str(hso.get("additionalContext") or "") if ok else ""
    return out if event in PLAIN_CONTEXT_EVENTS else ""


def first_line(text) -> str:
    """The first non-blank line of a refusal, stripped."""
    for line in str(text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def refusal_head(text: str) -> str:
    """A refusal's first HEAD characters, extended to the end of its first line."""
    text = (text or "").strip()
    end = text.find("\n")
    return text[:max(HEAD, end if end >= 0 else len(text))]


def refusal_first(result: dict) -> str:
    """The refusal's first line: from its uncut head when the run kept one, else from the kept tail
    (a record written before the head was kept)."""
    return first_line(result.get("refusal_head") or refusal(result))


def _run_one(h: dict, payload_raw: str, env: dict, cwd: str) -> dict:
    t0 = time.monotonic()
    try:
        p = subprocess.run(h["command"], shell=True, input=payload_raw, capture_output=True, text=True,
                           env=env, cwd=cwd, timeout=h["timeout"], errors="replace")
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        rc, err = "timeout", "timeout"
    except OSError as e:
        rc, out, err = -1, "", f"launch failed: {e}"
    verdict, how = interpret(rc, out)
    rec = {"hook": h["hook"], "matcher": h["matcher"], "rc": rc, "verdict": verdict, "how": how,
           "ms": round((time.monotonic() - t0) * 1000), "stdout": out[-TAIL:], "stderr": err[-TAIL:],
           "command": h["command"], "timeout": h["timeout"]}
    if verdict == "block":  # from the uncut output: the kept tail can lack the refusal's first line
        rec["refusal_head"] = refusal_head(refusal({"how": how, "stdout": out, "stderr": err}))
    elif verdict == "ok" and out.strip().startswith("{"):  # a PreToolUse input rewrite, from the uncut output
        try:
            upd = (json.loads(out).get("hookSpecificOutput") or {}).get("updatedInput")
        except (ValueError, AttributeError):
            upd = None
        if isinstance(upd, dict):
            rec["updated_input"] = upd
    return rec


def run_event(settings: dict, event: str, payload: dict, env: dict, cwd: str, parallel: bool = False) -> dict:
    """Run the event's hooks; returns {event, hooks: [...], total_ms}."""
    payload = dict(payload, hook_event_name=event)
    raw = json.dumps(payload)
    hooks = select(settings, event, payload)
    t0 = time.monotonic()
    if parallel and len(hooks) > 1:
        with ThreadPoolExecutor(max_workers=len(hooks)) as ex:
            results = list(ex.map(lambda h: _run_one(h, raw, env, cwd), hooks))
    else:
        results = [_run_one(h, raw, env, cwd) for h in hooks]
    return {"event": event, "hooks": results, "total_ms": round((time.monotonic() - t0) * 1000)}
