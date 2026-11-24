"""/allow grant and /do consent reader for Claude Code hooks.

The /allow grant's one writer (write_sentinel_grant), its one release decision
(release, asked only by the pre-tool launcher, lib/hook_launch.py, for a call
the harness refused) and its removal at the owner's next prompt (remove_grant,
hooks/userprompt-consent-allowlist.sh); and the one /do consent decision
(has_do_consent).

The grant, <state dir>/claude-grants/<task_id>.json (<state dir>:
hooks/lib/harness_state_dir.py; task_id: grant_key), holds {task_id,
session_id, scope, created_at}; scope is what recognise() made of the text
after /allow. It releases one refused call of its session (main agent or
subagent, any tool, any rule), is spent by that release, and ends at the
owner's next prompt. reap_expired_sentinel_grants() (hooks/stop-cleanup-
allowlist.sh) removes malformed grant files.

Shell hooks reach has_do_consent() through this file's one entry point:
`python3 <hooks>/lib/allowlist.py consent` with the hook payload on stdin
exits 0 when it holds /do consent and 1 when it does not.

Stdlib-only (plus hooks/lib/shell_parse.py to recognise a command); Python 3.10+.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from lib.harness_state_dir import harness_state_dir
    from lib.subagent import is_subagent_context
except ImportError:  # hooks/lib itself is on sys.path
    from harness_state_dir import harness_state_dir
    from subagent import is_subagent_context


# The /do consent flag, <state dir>/<prefix><session id><suffix>: written by
# hooks/prompt-workflow.py on a typed /do, read by has_do_consent below. Its
# one definition; lib/bash_safety_rules.py reads the name from here.
DO_CONSENT_FLAG_PREFIX = "claude-orchestrator-consent-"
DO_CONSENT_FLAG_SUFFIX = ".flag"

# The grant directory, <state dir>/claude-grants, resolved once at import.
SENTINEL_GRANT_DIR = harness_state_dir() + "/claude-grants"


def has_do_consent(payload) -> bool:
    """The one decision on /do consent, for every hook that honours it.

    True iff the payload comes from the main agent (lib.subagent: a subagent
    never holds /do consent) and the flag hooks/prompt-workflow.py writes for
    the payload's session_id, <state dir>/claude-orchestrator-consent-<sid>.flag,
    holds `true`. The session_id is the writer's own key, so a payload without
    one has no consent. Never raises.
    """
    try:
        if not isinstance(payload, dict) or is_subagent_context(payload):
            return False
        sid = payload.get("session_id")
        if not isinstance(sid, str) or not sid:
            return False
        flag = Path(harness_state_dir(), f"{DO_CONSENT_FLAG_PREFIX}{sid}{DO_CONSENT_FLAG_SUFFIX}")
        return flag.read_text().strip() == "true"
    except Exception:
        return False


def tool_streak_path(session_id: str) -> Path:
    """The orchestrator gate's per-session tool streak record."""
    return Path(harness_state_dir(), f"claude-tool-streak-{session_id}.json")


def state_entry_failure(path, error) -> str:
    """A hook's text for a control-state entry that cannot be written or read:
    the file, the error and the volume (mount point, bytes free). Never raises."""
    path = mount = os.path.abspath(path)
    while not os.path.ismount(mount):
        mount = os.path.dirname(mount)
    try:
        free = f"{(st := os.statvfs(mount)).f_bavail * st.f_frsize} bytes free"
    except OSError:
        free = "free space unknown"
    error = f"[Errno {error.errno}] {error.strerror}" if getattr(error, "strerror", None) else error
    return f"{path}: {error}, on the volume mounted at {mount} ({free})"


def write_state_entry(path, text: str, mode: int = 0o666) -> None:
    """Replace a control-state entry whole (a temp file beside it, then a
    rename): no reader meets a partial or empty one. A state dir that does not
    exist yet (a fresh install, a fresh CLAUDE_STATE_DIR) is made, 0700. Raises
    OSError, the temp file removed and the earlier entry left as it was."""
    tmp = Path(path).with_name(f".{Path(path).name}.tmp.{os.getpid()}")
    try:
        tmp.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def write_tool_streak(session_id: str, state: dict | None) -> None:
    """The one writer of the tool streak: `state` replaces the record (raises
    OSError), None removes it and the log of the calls that ran (tool_ran_path).
    hooks/pretool-orchestrator-gate.py calls it for its update and its Agent
    reset, hooks/prompt-workflow.py for the reset at each prompt; it lives
    here, the one library both import."""
    if state is not None:
        write_state_entry(tool_streak_path(session_id), json.dumps(state))
        return
    for path in (tool_streak_path(session_id), tool_ran_path(session_id)):
        try:
            path.unlink()
        except OSError:
            pass


def tool_ran_path(session_id: str) -> Path:
    """The main agent's calls that ran this turn, one tool_use_id per line,
    appended by hooks/posttool-orchestrator-ran.py on the CLI's PostToolUse or
    PostToolUseFailure event. The CLI fires one of the two for every call it
    ran, failed and interrupted runs included, and neither for a call a
    PreToolUse hook refused."""
    return Path(harness_state_dir(), f"claude-tool-ran-{session_id}.log")


def record_tool_ran(session_id: str, tool_use_id) -> None:
    """Append one ran call's tool_use_id to tool_ran_path. Raises OSError; an
    append cut short is cut back, so the log never holds a partial line."""
    if not isinstance(tool_use_id, str) or not tool_use_id or "\n" in tool_use_id or "\r" in tool_use_id:
        return
    line = (tool_use_id + "\n").encode("utf-8")
    tool_ran_path(session_id).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(tool_ran_path(session_id), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
    size = os.fstat(fd).st_size
    try:
        if os.write(fd, line) != len(line):
            raise OSError(28, os.strerror(28))
    except OSError:
        os.ftruncate(fd, size)
        raise
    finally:
        os.close(fd)


def read_tool_ran(session_id: str) -> set | None:
    """The tool_use_ids record_tool_ran appended this turn: empty when no call
    has run, None when the log cannot be read (the caller then gives nothing
    back). Never raises."""
    try:
        return {line for line in tool_ran_path(session_id).read_text(encoding="utf-8").splitlines() if line}
    except FileNotFoundError:
        return set()
    except (OSError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────
# The /allow grant: a one-time switch-off of the harness for one call
#
# The owner's typed /allow writes the session's one grant (write_sentinel_grant,
# through hooks/userprompt-consent-allowlist.sh). The pre-tool launcher
# (lib/hook_launch.py), where every pre-tool verdict of the harness comes
# together, asks release() when the combined verdict is a refusal: a grant whose
# scope the refused call fits lets that call through and is spent by it. Nothing
# else reads a grant to decide. The grant ends when it is spent or at the
# owner's next prompt (the prompt hook removes it); no clock limit.
#
# Scope (recognise): the text after /allow is
#   - a TOOL when, stripped, it is exactly one of TOOL_NAMES or an MCP tool name
#     (mcp__<server>__<tool>): only a refused call of that tool is released;
#   - a COMMAND when it is one line of ASCII the shell parser reads without
#     error and its first word is a program on PATH: only a refused Bash (or
#     Monitor) call whose command, whitespace runs folded, starts with it at a
#     word boundary is released;
#   - otherwise (nothing, free text, anything else): ANY, the next refused call.
# ─────────────────────────────────────────────────────────────────────

ANY, TOOL, COMMAND = "any", "tool", "command"
# The CLI's tool names a scope may name (exact, case-sensitive).
TOOL_NAMES = frozenset({
    "Agent", "Task", "Bash", "BashOutput", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep",
    "LSP", "TodoWrite", "WebFetch", "WebSearch", "Skill", "SlashCommand", "SendMessage", "ListAgents", "Monitor",
    "TaskStop", "TaskOutput", "KillShell", "AskUserQuestion", "CronCreate", "CronDelete", "CronList",
    "ScheduleWakeup", "PushNotification", "EnterWorktree", "ExitWorktree", "EnterPlanMode", "ExitPlanMode",
    "Workflow", "ReadMcpResourceTool", "ListMcpResourcesTool",
})
_MCP_TOOL = re.compile(r"mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+")
# The tools whose call runs an arbitrary shell command (tool_input.command): a command scope fits
# only them, and hooks/pretool-orchestrator-gate.py caps them in Bash's one counter (BASH_CAPPED).
COMMAND_TOOLS = frozenset({"Bash", "Monitor"})


def grant_key(session_id: str) -> str:
    """The name a session's grant is filed under: CLAUDE_TASK_ID, else the session id."""
    return os.environ.get("CLAUDE_TASK_ID") or session_id


def recognise(text: str) -> dict:
    """The scope the text after /allow gives (see above): {"kind": ANY}, {"kind": TOOL, "tool": name}
    or {"kind": COMMAND, "command": text}."""
    text = (text or "").strip()
    if text in TOOL_NAMES or _MCP_TOOL.fullmatch(text):
        return {"kind": TOOL, "tool": text}
    if text and "\n" not in text and text.isascii():
        try:
            try:
                from lib.shell_parse import parse
            except ImportError:
                from shell_parse import parse
            import shutil
            script = parse(text)
            first = text.split()[0]
            if not script.errors() and script.items and (shutil.which(first) or (
                    os.path.isabs(first) and os.access(first, os.X_OK) and os.path.isfile(first))):
                return {"kind": COMMAND, "command": " ".join(text.split())}
        except Exception:  # noqa: BLE001 - what cannot be read as a command is free text
            pass
    return {"kind": ANY}


def describe(scope: dict) -> str:
    """The scope in plain words, for the notice and the release line."""
    if scope.get("kind") == TOOL:
        return f"the next refused call of the tool {scope.get('tool')}"
    if scope.get("kind") == COMMAND:
        return f"the next refused shell command that starts with: {scope.get('command')}"
    return "the next refused call, whatever it is"


def fits(scope: dict, payload: dict) -> bool:
    """Whether a call (its PreToolUse payload) is one the scope lets through."""
    kind, tool = scope.get("kind"), payload.get("tool_name")
    if kind == TOOL:
        return tool == scope.get("tool")
    if kind == COMMAND:
        ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        want, cmd = str(scope.get("command") or ""), " ".join(str(ti.get("command") or "").split())
        return bool(want) and tool in COMMAND_TOOLS and (cmd == want or cmd.startswith(want + " "))
    return kind == ANY


def _enumerate_sentinel_grant_files(task_id: str | None = None) -> list[Path]:
    """The grant files under SENTINEL_GRANT_DIR (task_id: its one file, "<task_id>.json")."""
    try:
        d = Path(SENTINEL_GRANT_DIR)
        if not d.is_dir():
            return []
        return [p for p in d.glob("*.json") if not task_id or p.name == f"{task_id}.json"]
    except Exception:
        return []


def sentinel_grant_path(task_id: str) -> Path:
    """Where write_sentinel_grant() files the grant for task_id."""
    return Path(SENTINEL_GRANT_DIR) / f"{task_id}.json"


def write_sentinel_grant(task_id: str, session_id: str, scope: dict, *, exclusive: bool = False) -> Path:
    """The one writer of a grant; returns its path, raises OSError. It replaces the task's grant
    atomically; exclusive=True creates it with O_EXCL instead (FileExistsError when one exists:
    scripts/capture-hero-run.py's exclusivity check)."""
    path = sentinel_grant_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"task_id": task_id, "session_id": session_id, "scope": scope, "created_at": time.time()},
                      indent=2, sort_keys=True) + "\n"
    if not exclusive:  # 0o600: another user's session cannot read the grant
        write_state_entry(path, body, 0o600)
        return path
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def _read_sentinel_grant_file(grant_path: Path) -> dict | None:
    """The grant in one file, or None when it is missing or malformed. Never raises, never unlinks."""
    try:
        with open(grant_path) as f:
            grant = json.load(f)
    except Exception:
        return None
    if not (isinstance(grant, dict) and isinstance(grant.get("session_id"), str)
            and isinstance(grant.get("scope"), dict) and grant["scope"].get("kind") in (ANY, TOOL, COMMAND)):
        return None
    return grant


def load_sentinel_grant_for_task(task_id: str) -> dict | None:
    """The task's grant, or None (missing or malformed). Never unlinks."""
    return _read_sentinel_grant_file(sentinel_grant_path(task_id)) if task_id else None


def remove_grant(task_id: str) -> bool:
    """End the task's grant (the owner's next prompt). True when one was removed."""
    try:
        sentinel_grant_path(task_id).unlink()
        return True
    except OSError:
        return False


def release(payload) -> dict | None:
    """The one release decision, asked by the pre-tool launcher for a call the harness refused: the
    session's grant when it fits the call, spent by this call (claimed by a rename, so of calls
    refused at the same time only one is released); None otherwise. Never raises."""
    try:
        if not isinstance(payload, dict) or payload.get("hook_event_name") != "PreToolUse":
            return None
        sid = payload.get("session_id")
        if not isinstance(sid, str) or not sid:
            return None
        path = sentinel_grant_path(grant_key(sid))
        grant = _read_sentinel_grant_file(path)
        if grant is None or grant["session_id"] != sid or not fits(grant["scope"], payload):
            return None
        claimed = path.with_name(f".{path.name}.spent.{os.getpid()}")
        os.rename(path, claimed)  # FileNotFoundError: another refused call spent it first
        claimed.unlink(missing_ok=True)
        return grant
    except Exception:  # noqa: BLE001 - no release is the answer a fault gives
        return None


def reap_expired_sentinel_grants() -> int:
    """Stop-cleanup helper: unlink every grant file the reader rejects (malformed), and any spent
    claim a crash left. Returns the count. Never raises."""
    count = 0
    for p in _enumerate_sentinel_grant_files(None) + list(Path(SENTINEL_GRANT_DIR).glob(".*.spent.*")
                                                          if Path(SENTINEL_GRANT_DIR).is_dir() else []):
        if not p.name.startswith(".") and _read_sentinel_grant_file(p) is not None:
            continue
        try:
            os.unlink(p)
            count += 1
        except Exception:
            pass
    return count


if __name__ == "__main__":
    # The shell hooks' one entry point to has_do_consent (see the module docstring).
    if sys.argv[1:] != ["consent"]:
        sys.exit(2)
    try:
        _payload = json.load(sys.stdin)
    except Exception:
        _payload = None
    sys.exit(0 if has_do_consent(_payload) else 1)
