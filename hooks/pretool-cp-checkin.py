#!/usr/bin/env python3
"""PreToolUse Hook (Read): Auto-register subagent into cp-state on direct
cp-state file read (the write is scripts/spec-check.py's `register`).

Triggers when a subagent's `Read` tool call targets either of:

    <project>/.claude/specs/<spec-id>/cp-state-<agent>(-N).json
    <project>/.claude/dev-registry/<sid>/<agent>.json

The first pattern is the SECOND ACTION protocol mandated by /spec, /dev,
/dev-command, /dev-overnight, and /close. The second pattern is the
dev-registry sentinel for /dev workflows (no spec views).

P1 tombstone (ba-spec-20260427-194324, dev cycle 20260427-194324):
The legacy view-file trigger (VIEW_PATH_PATTERN matching
docs/dev/specs/<spec-id>/views/<agent>.md + _handle_spec_view +
_extract_target) was REMOVED on 2026-04-27 because Anthropic built-in
Explore subagents incidentally read view files for codebase research and
were getting falsely registered into cp-state. The SECOND ACTION protocol
already covers all legitimate registration via direct cp-state Read; the
view-file trigger was structurally redundant AND structurally unsafe. DO
NOT REINTRODUCE IT under any guise (Codex Q7).

Fail-open: any error -> exit 0. Never block on unexpected input.
"""

import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import roster  # noqa: E402

# The one writer of cp-state files, resolved from this hook's own location.
SPEC_CHECK = Path(__file__).resolve().parent.parent / "scripts" / "spec-check.py"
# spec-check.py waits at most 10 s for the spec directory's lock (exit 75 after).
REGISTER_TIMEOUT_S = 20


# Dev-registry sentinel: sibling mechanism for /dev, /dev-command, /dev-overnight
# workflows. These workflows produce no spec views, so VIEW_PATH_PATTERN never
# fires for them. Root cause: commit e086ccb scoped enforcement to /spec only;
# /dev sessions have no cp-state files, so the enforcement hook fails open.
# Fix: each dispatched subagent reads .claude/dev-registry/<session_id>/<agent>.json
# as its FIRST ACTION; this hook extracts the agent type from the path, writes the
# Claude-stdin agent_id -> agent_type mapping to .claude/dev-registry/agent-index.json,
# and is the sentinel's one producer: it creates the sentinel in the cycle's armed
# registry right before that read, so a sentinel exists for exactly the roles a
# dispatch reads (P1b goal 2). See ba-spec-20260424-110000.md.
DEV_SENTINEL_PATTERN = re.compile(
    r".*/\.claude/dev-registry/(?P<session_id>[^/]+)/(?P<agent>[^/]+)\.json$"
)

# CP-STATE direct-read pattern: subagents per /root/.claude/commands/dev.md
# SECOND ACTION blocks read .claude/specs/<spec-id>/cp-state-<agent>(-N).json
# directly to register their agent_id. The original VIEW_PATH_PATTERN only
# matched docs/dev/specs/<spec-id>/views/<agent>.md, so cp-state direct reads
# never triggered check-in. This pattern covers BOTH primary slot files
# (cp-state-<agent>.json) and numbered instance slots
# (cp-state-<agent>-<N>.json, N>=2). Mirrors _CP_STATE_FILENAME_RE in
# /root/.claude/scripts/spec-check.py (which is the writer).
CP_STATE_PATH_PATTERN = re.compile(
    r".*/\.claude/specs/(?P<spec_id>[^/]+)/cp-state-(?P<agent>[A-Za-z0-9_-]+?)(?:-\d+)?\.json$"
)


def _load_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return None


def _extract_cp_state_target(data):
    """Extract (spec_id, agent) for a Read targeting a cp-state file directly.

    Returns (None, None) when the Read does not match the cp-state path or
    the agent name is not a roster role. Mirrors the agent-name validation
    used by _extract_dev_sentinel to prevent arbitrary path reads from
    triggering registration.
    """
    if not isinstance(data, dict):
        return None, None
    if data.get("tool_name") != "Read":
        return None, None
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    m = CP_STATE_PATH_PATTERN.match(file_path)
    if not m:
        return None, None
    agent = m.group("agent")
    if agent not in roster.roles():
        return None, None
    return m.group("spec_id"), agent


def _extract_dev_sentinel(data):
    """Extract (session_id, agent) for a Read targeting the dev-registry.

    Returns (None, None) when the Read does not match the sentinel path or the
    agent name is not a roster role. Validating the agent name here
    prevents arbitrary JSON reads from being written into the index.
    """
    if not isinstance(data, dict):
        return None, None
    if data.get("tool_name") != "Read":
        return None, None
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    m = DEV_SENTINEL_PATTERN.match(file_path)
    if not m:
        return None, None
    agent = m.group("agent")
    if agent not in roster.roles():
        return None, None
    return m.group("session_id"), agent


def _dev_registry_index_path(project_dir):
    return Path(project_dir) / ".claude" / "dev-registry" / "agent-index.json"


def _read_index(index_path):
    """Load agent-index.json as dict, returning {} on any error."""
    try:
        existing = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return existing if isinstance(existing, dict) else {}


def _write_index_locked(index_path, agent_id, agent_type, dev_session_id=None):
    """Write the merged mapping while holding fcntl.LOCK_EX on a sibling lock."""
    lock_path = index_path.with_suffix(index_path.suffix + ".lock")
    with open(lock_path, "w") as lh:
        fcntl.flock(lh.fileno(), fcntl.LOCK_EX)
        existing = _read_index(index_path)
        existing[agent_id] = {"agent_type": agent_type, "dev_session_id": dev_session_id} if dev_session_id else agent_type
        index_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        fcntl.flock(lh.fileno(), fcntl.LOCK_UN)


def _update_dev_registry_index(project_dir, agent_id, agent_type, dev_session_id=None):
    """Append {agent_id: agent_type} to agent-index.json under fcntl.LOCK_EX.

    Fails silent (returns False) on I/O errors so the hook remains fail-open.
    """
    index_path = _dev_registry_index_path(project_dir)
    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        _write_index_locked(index_path, agent_id, agent_type, dev_session_id)
    except OSError:
        return False
    return True


def _handle_cp_state_direct_read(data, project_dir):
    """Process a CP_STATE_PATH_PATTERN Read: register the reading subagent.

    Treats a direct Read of .claude/specs/<spec-id>/cp-state-<agent>(-N).json
    as the SECOND ACTION registration trigger. The write itself is
    scripts/spec-check.py's (`register`), the one writer of cp-state files:
    it picks the slot (the one this agent_id holds, else the first idle one,
    else a new numbered slot carrying the primary's checklist), restamps
    ownership and keeps every checkpoint state, under the spec directory's
    lock. A Read with no agent_id (the main agent's) registers nobody.
    Returns True when the Read targets a cp-state file.

    BUG-CPSTATE-1: the SECOND ACTION blocks in commands/dev.md instruct
    subagents to Read cp-state files directly; without this handler the
    agent_id was never registered.
    """
    spec_id, agent = _extract_cp_state_target(data)
    if spec_id is None:
        return False
    agent_id = data.get("agent_id")
    if agent_id:
        subprocess.run(
            [sys.executable, str(SPEC_CHECK), "register", "--spec-id", spec_id,
             "--agent", agent, "--agent-id", agent_id],
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)},
            capture_output=True, timeout=REGISTER_TIMEOUT_S,
        )
    return True


def _ensure_dev_sentinel(file_path, agent, session_id):
    """Create the sentinel the subagent is about to read, in a registry the cycle's
    start armed (an existing, non-symlinked directory): its one producer, so the
    sentinel exists for the roles a dispatch reads and for no other. An existing
    sentinel is left as it is; the bytes appear whole (a temporary linked into
    place). Fail-open: any error leaves the read to report the missing file."""
    registry = Path(file_path).parent
    if registry.is_symlink() or not registry.is_dir() or os.path.lexists(file_path):
        return
    payload = (json.dumps({"agent_type": agent, "session_id": session_id}) + "\n").encode("utf-8")
    tmp = registry / f".{agent}.json.tmp-{os.getpid()}"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            pass        # a parallel dispatch of the same role created it first
    except OSError:
        pass
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _handle_dev_sentinel(data, project_dir):
    """Process a DEV_SENTINEL_PATTERN Read; create the sentinel, register UUID ->
    agent_type.

    Returns True when handled, False when the Read does not target a sentinel
    or the Claude-stdin agent_id is missing (main-agent Read is ignored).
    """
    session_id, agent = _extract_dev_sentinel(data)
    if session_id is None:
        return False
    agent_id = data.get("agent_id")
    if not agent_id:
        return False
    _ensure_dev_sentinel((data.get("tool_input") or {}).get("file_path") or "", agent, session_id)
    _update_dev_registry_index(project_dir, agent_id, agent, session_id)
    return True


def main():
    data = _load_stdin()
    if data is None:
        sys.exit(0)
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    # SECOND ACTION direct cp-state read (the legitimate registration trigger
    # mandated by /spec, /dev, /dev-command, /dev-overnight), then
    # /dev sentinel for /dev workflows without spec views. Both handlers are
    # fail-open: any miss or error -> exit 0. The legacy view-file trigger
    # was removed (see module docstring P1 tombstone).
    if _handle_cp_state_direct_read(data, project_dir):
        sys.exit(0)
    _handle_dev_sentinel(data, project_dir)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
