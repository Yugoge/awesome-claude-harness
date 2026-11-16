"""/allow grant and /do consent reader for Claude Code hooks.

The /allow grant file's one writer (write_sentinel_grant) and its readers,
and the one /do consent decision (has_do_consent), for the PreToolUse,
PostToolUse and Stop hooks that honour them. hooks/userprompt-consent-
allowlist.sh also removes a stale grant itself before /allow writes or
refuses one.

Contract:
  - PreToolUse hooks ONLY read the grant; they never delete it.
  - Deletion is deferred to posttool-allowlist-consume.py (PostToolUse).
  - Whether a grant reaches subagents is each caller's choice; the /do
    consent decision carries its own subagent check (has_do_consent).

Sentinel-file grant lifecycle:
  - /allow (hooks/userprompt-consent-allowlist.sh) and the README demo's
    capture (scripts/capture-hero-run.py) write the grant through
    write_sentinel_grant() at <state dir>/claude-grants/<task_id>.json
    (<state dir>: hooks/lib/harness_state_dir.py, CLAUDE_STATE_DIR when it
    is absolute, else /tmp), containing {task_id, session_id,
    allowed_operations[], created_at, expires_at}. allowed_operations[] is a
    structured list of {op, target, args_contain?, ...} dicts; a regex
    /allow (`/allow re:<regex>`) writes one {op: "*", regex} entry. It is
    the only /allow grant file.
  - load_sentinel_grant_for_task() reads and validates the sentinel.
  - match_sentinel_grant_for_bash_command() returns the entry a Bash command
    satisfies when hooks/lib/shell_parse.py reads it as exactly one simple
    command: a structural entry by equality on op/target and a positional
    prefix of the arguments, never a substring of the raw command line; a
    regex entry by re.search over that command.
    match_sentinel_grant_for_write() and match_sentinel_grant_for_tool()
    match a Write target and a tool name.
  - consume_sentinel_grant_on_terminal_result() unlinks the task's grant
    files; posttool-allowlist-consume.py calls it once the call a grant
    matched has ended, whatever its result, and for a grant file the reader
    rejects.
  - reap_expired_sentinel_grants() is called by hooks/stop-cleanup-allowlist.sh,
    the cleanup phase hooks/stop-workflow-coordinator.py runs at each Stop
    its earlier phases do not block, to remove every grant the reader rejects.

Shell hooks reach has_do_consent() through this file's one entry point:
`python3 <hooks>/lib/allowlist.py consent` with the hook payload on stdin
exits 0 when it holds /do consent and 1 when it does not.

Stdlib-only (plus hooks/lib/shell_parse.py for Bash matching); Python 3.10+.
"""

import json
import os
import re
import signal
import sys
import time
from pathlib import Path

try:
    from lib.harness_state_dir import harness_state_dir
    from lib.subagent import is_subagent_context
except ImportError:  # hooks/lib itself is on sys.path
    from harness_state_dir import harness_state_dir
    from subagent import is_subagent_context


# The grant directory, <state dir>/claude-grants, resolved once at import.
SENTINEL_GRANT_DIR = harness_state_dir() + "/claude-grants"


def _regex_safe(pattern: str, text: str, timeout: int = 1) -> bool:
    """re.search with SIGALRM timeout. Returns False on re.error or timeout."""
    if timeout is None:
        timeout = 1
    def _handler(signum, frame):
        raise TimeoutError("regex timeout")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout)
    try:
        return bool(re.search(pattern, text))
    except (re.error, TimeoutError):
        return False
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


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
        flag = Path(harness_state_dir(), f"claude-orchestrator-consent-{sid}.flag")
        return flag.read_text().strip() == "true"
    except Exception:
        return False


def tool_streak_path(session_id: str) -> Path:
    """The orchestrator gate's per-session tool streak record."""
    return Path(harness_state_dir(), f"claude-tool-streak-{session_id}.json")


def write_tool_streak(session_id: str, state: dict | None) -> None:
    """The one writer of the tool streak: `state` replaces the record, None
    removes it. hooks/pretool-orchestrator-gate.py calls it for its update and
    its Agent reset, hooks/prompt-workflow.py for the reset at each prompt; it
    lives here, the one library both import. Best-effort, never raises."""
    path = tool_streak_path(session_id)
    try:
        if state is None:
            path.unlink()
        else:
            path.write_text(json.dumps(state))
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────────
# Sentinel-grant lifecycle
#
# The sentinel grant is the one /allow grant file. PreToolUse hooks read
# <state dir>/claude-grants/<task_id>.json instead of grepping the command
# text. A structural entry {op, target?, args_contain?} matches by op and
# target equality and a positional argument prefix, never by substring.
#
# Consumption (posttool-allowlist-consume.py): a matched grant is unlinked
# once its call has ended (success, non-zero exit, interrupted); a grant
# file the reader rejects (malformed, expired) is unlinked at the task's
# next Bash or Write call.
# ─────────────────────────────────────────────────────────────────────


def _enumerate_sentinel_grant_files(task_id: str | None = None) -> list[Path]:
    """List existing sentinel grant files under SENTINEL_GRANT_DIR.

    If task_id is provided, restrict to "<task_id>.json", the one name
    write_sentinel_grant() writes.
    """
    try:
        d = Path(SENTINEL_GRANT_DIR)
        if not d.is_dir():
            return []
        if task_id:
            return [p for p in d.glob("*.json") if p.name == f"{task_id}.json"]
        return list(d.glob("*.json"))
    except Exception:
        return []


def sentinel_grant_path(task_id: str) -> Path:
    """Where write_sentinel_grant() files the grant for task_id."""
    return Path(SENTINEL_GRANT_DIR) / f"{task_id}.json"


def write_sentinel_grant(
    task_id: str,
    session_id: str,
    allowed_operations: list,
    *,
    exclusive: bool = False,
) -> Path:
    """The one writer of a sentinel grant; returns its path, raises OSError.

    The grant lives 300 s, one bash-safety grant window. By default it
    replaces the task's grant atomically (temp file + rename), so a reader
    never sees a partial file. exclusive=True creates it with O_EXCL
    instead and raises FileExistsError when the task already holds a grant:
    scripts/capture-hero-run.py's preflight is only a snapshot taken seconds
    earlier, so the create itself must be its exclusivity check.
    """
    path = sentinel_grant_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    body = json.dumps({
        "task_id": task_id,
        "session_id": session_id,
        "allowed_operations": allowed_operations,
        "created_at": now,
        "expires_at": now + 300,
    }, indent=2, sort_keys=True) + "\n"
    target = path if exclusive else path.with_name(f".{path.name}.tmp.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    # 0o600: another user's session cannot read the grant.
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    if not exclusive:
        os.replace(target, path)
    return path


def _read_sentinel_grant_file(grant_path: Path) -> dict | None:
    """The reader's verdict on one grant file: the grant, or None when it is
    missing, malformed or expired. Never raises, never unlinks."""
    try:
        with open(grant_path) as f:
            grant = json.load(f)
    except Exception:
        return None
    if not isinstance(grant, dict):
        return None
    required = ("task_id", "session_id", "allowed_operations", "created_at", "expires_at")
    if not all(k in grant for k in required):
        return None
    if not isinstance(grant.get("allowed_operations"), list):
        return None
    # Expiry check (deny-by-default on parse failure).
    exp = grant.get("expires_at")
    try:
        now = time.time()
        if isinstance(exp, (int, float)):
            if exp < now:
                return None
        elif isinstance(exp, str):
            # Accept ISO-8601 with Z or +00:00 suffix.
            from datetime import datetime, timezone
            s = exp.replace("Z", "+00:00")
            t = datetime.fromisoformat(s).timestamp()
            if t < now:
                return None
        else:
            return None
    except Exception:
        return None
    return grant


def load_sentinel_grant_for_task(task_id: str) -> dict | None:
    """Read and validate a sentinel grant JSON for a given task_id.

    Returns the decoded grant dict on success, None if missing/malformed/expired.
    Required schema keys: task_id, session_id, allowed_operations (list),
    created_at, expires_at. expires_at is an ISO-8601 string OR unix-epoch
    integer/float; if it has elapsed, the grant is treated as missing.

    NOTE: this function does NOT unlink the grant. Consumption goes through
    consume_sentinel_grant_on_terminal_result().
    """
    matches = _enumerate_sentinel_grant_files(task_id)
    if not matches:
        return None
    # Most-recent-mtime wins on the unlikely event of duplicates.
    try:
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        pass
    return _read_sentinel_grant_file(matches[0])


def match_sentinel_grant_for_tool(session_id: str, tool_name: str) -> dict | None:
    """The grant entry that authorizes one call of a tool by name, or None.

    Reads the session's grant under /allow's own key (CLAUDE_TASK_ID, else the
    session id) and requires the grant to be this session's, as the per-session
    file it replaces was. Only an entry naming the tool exactly with no target
    or arguments (`/allow Agent`) matches: a regex entry selects commands, which
    match_sentinel_grant_for_bash_command() tests, so the argument-less match-all
    grant still waits for the command it was given for. posttool-allowlist-
    consume.py spends the entry after the call.
    """
    if not session_id or not tool_name:
        return None
    grant = load_sentinel_grant_for_task(os.environ.get("CLAUDE_TASK_ID") or session_id)
    if grant is None or grant.get("session_id") != session_id:
        return None
    for entry in grant["allowed_operations"]:
        if (isinstance(entry, dict) and entry.get("op") == tool_name
                and not entry.get("target") and not entry.get("args_contain")):
            return entry
    return None


def _one_simple_command(command: str):
    """The one simple command ``command`` runs, read by hooks/lib/shell_parse.py, or None.

    A grant authorizes exactly one command, so this is None when the text does
    not parse, or runs more than one command anywhere (a list, a pipeline, a
    background job, a command substitution, a process substitution, a -c or
    eval payload, a fed shell), or runs its command inside a compound command,
    under `!` or under `time`. The parser is imported here, not at module load:
    the core install profile ships this module without it, and its hooks never
    match a Bash grant.
    """
    try:
        from lib.shell_parse import SimpleCommand, parse, walk
    except ImportError:
        try:
            from shell_parse import SimpleCommand, parse, walk
        except ImportError:
            return None
    script = parse(command)
    if script.errors() or len(script.items) != 1:
        return None
    pipeline = script.items[0][0]
    if len(pipeline.stages) != 1 or pipeline.negated or pipeline.timed:
        return None
    cmd = pipeline.stages[0]
    if (not isinstance(cmd, SimpleCommand) or not cmd.words
            or sum(1 for _ in walk(script)) != 1):
        return None
    return cmd


# The git global options a short grant may read past to reach the subcommand:
# a subset of shell_parse's GIT_GLOBAL_VALUE_OPTS and GIT_GLOBAL_FLAGS (a test
# pins it), narrower on purpose, since this table authorizes. Only options that
# retarget the repository or toggle a no-op are listed. An option that carries
# a code-execution vector (-c, --config-env, --exec-path) or is unknown stops
# the skip, so a command bearing one never inherits a shorter grant. `-C` has
# no attached form in git (`git -C/p` is rejected), so only `-C <dir>` skips.
_GRANT_SKIPPABLE_GIT_VALUE_OPTS = frozenset({
    '-C', '--git-dir', '--work-tree', '--namespace',
})
_GRANT_SKIPPABLE_GIT_ATTACHED_PREFIXES = ('--git-dir=', '--work-tree=', '--namespace=')
_GRANT_SKIPPABLE_GIT_FLAGS = frozenset({
    '-p', '--paginate', '--no-pager', '--bare', '--literal-pathspecs',
    '--no-literal-pathspecs', '--icase-pathspecs', '--no-optional-locks',
})


def _first_non_global_word(words) -> int:
    """Index of the first word after a git head that is not a skippable global option."""
    i = 1
    while i < len(words):
        value = words[i].value()
        if value in _GRANT_SKIPPABLE_GIT_VALUE_OPTS and i + 1 < len(words):
            i += 2
        elif value in _GRANT_SKIPPABLE_GIT_FLAGS or (value is not None and any(
                value.startswith(p) and len(value) > len(p)
                for p in _GRANT_SKIPPABLE_GIT_ATTACHED_PREFIXES)):
            i += 1
        else:
            break
    return i


def match_sentinel_grant_for_bash_command(task_id: str, command: str) -> dict | None:
    """The allowed_operations[] entry the task's grant gives ``command``, or None.

    The command must be exactly one simple command (_one_simple_command); its
    text runs from its first assignment or word to its last word or redirect,
    and its tokens from its first word or redirect, past its assignments.

    1. Regex entries (op "*" with a "regex"): re.search of the regex over that
       text, assignments included.
    2. Structural entries: the text's whitespace-separated tokens, from the
       command word on, as /allow splits its pattern. entry["op"] equals the
       command token; entry["target"], when present, equals the token after
       it; entry["args_contain"] is a positional prefix of the tokens after
       it, never a substring of the command line.

       For a git command the tokens after it are also read from its first
       word that is not a skippable global option (_first_non_global_word), so
       `/allow git commit` reaches `git -C <dir> commit -F <msgfile>`. The
       verbatim tokens are tried too, so a grant that names a global option
       keeps pinning it exactly.
    """
    grant = load_sentinel_grant_for_task(task_id)
    if grant is None:
        return None
    cmd = _one_simple_command(command)
    if cmd is None:
        return None
    ops = grant.get("allowed_operations", [])
    end = cmd.span[1]
    text = command[cmd.span[0]:end]

    for entry in ops:
        if not isinstance(entry, dict) or entry.get("op") != "*":
            continue
        regex_pattern = entry.get("regex")
        if isinstance(regex_pattern, str) and _regex_safe(regex_pattern, text):
            return entry

    words = cmd.words
    start = min([words[0].span[0]] + [r.off - len(r.io or "") for r in cmd.redirects])
    tokens = command[start:end].split()
    head_op = tokens[0]
    rest_views = [tokens[1:]]
    if head_op.rsplit('/', 1)[-1] == 'git':
        k = _first_non_global_word(words)
        if 1 < k < len(words):
            rest_views.append(command[words[k].span[0]:end].split())
    target_views = {v[0] for v in rest_views if v}
    for entry in ops:
        if not isinstance(entry, dict):
            continue
        want_op = entry.get("op")
        if not isinstance(want_op, str) or want_op == "*" or want_op != head_op:
            continue
        want_target = entry.get("target")
        if want_target is not None and want_target not in target_views:
            continue
        args_contain = entry.get("args_contain") or []
        if not isinstance(args_contain, list):
            continue
        # Multi-word items split into tokens, so "push origin" is a two-token
        # prefix, never a substring of "commit -m push origin".
        wanted = [t for a in args_contain if isinstance(a, str) for t in a.split()]
        if not wanted:
            return entry
        if any(view[:len(wanted)] == wanted for view in rest_views):
            return entry
    return None


def match_sentinel_grant_for_write(task_id: str, session_id: str, target_path: str) -> dict | None:
    """Structural match of a Write-overwrite operation against sentinel-grant allowed_operations[].

    Mirrors match_sentinel_grant_for_bash_command() for the Write tool.
    Match requires session_id equality and op=='Write'. Target matching:
      - 'target' key present: exact string equality with target_path required;
        absent or null or non-string 'target' values deny (fail-closed).
      - 'args_contain' key present (no 'target'): allow only if args_contain
        is a one-item list whose sole element exactly equals target_path (no
        substring matching).
      - Neither key present (bare {"op":"Write"}): intentional wildcard — matches
        any target_path. This preserves /allow Write (no path) wildcard behavior.

    The 'target' field name is the one /allow writes for `/allow Write <path>`
    (hooks/userprompt-consent-allowlist.sh); do NOT use 'target_path'.

    Args:
        task_id: task whose sentinel grant to load.
        session_id: current session_id; must equal grant['session_id'].
        target_path: absolute path of the file being written.

    Returns:
        The matched allowed_operations[] entry dict on success, None otherwise.
        Returns None if grant is missing, expired, session_id mismatches,
        or no entry matches op=='Write' with a compatible target.
    """
    grant = load_sentinel_grant_for_task(task_id)
    if grant is None:
        return None
    if grant.get("session_id") != session_id:
        return None
    ops = grant.get("allowed_operations", [])
    for entry in ops:
        if not isinstance(entry, dict):
            continue
        if entry.get("op") != "Write":
            continue
        if "target" in entry:
            t = entry["target"]
            if isinstance(t, str) and t and t == target_path:
                return entry
        elif "args_contain" in entry:
            ac = entry["args_contain"]
            if isinstance(ac, list) and len(ac) == 1 and isinstance(ac[0], str) and ac[0] == target_path:
                return entry
        else:
            return entry
    return None


def consume_sentinel_grant_on_terminal_result(task_id: str, terminal_result: str) -> bool:
    """Unlink the sentinel grant file on ANY terminal result.

    Its caller, posttool-allowlist-consume.py, decides when: once the call a
    grant matched has ended, whatever its result, and for a grant file the
    reader rejects.

    Args:
        task_id: the task whose sentinel grant should be reaped.
        terminal_result: one of "success", "failure", "non_zero", "malformed",
                         "comment_only", or any other terminal sentinel string.
                         The value is only logged: every call unlinks.

    Returns:
        True iff at least one matching grant file was unlinked, False otherwise.
    """
    unlinked = False
    for p in _enumerate_sentinel_grant_files(task_id):
        try:
            os.unlink(p)
            unlinked = True
            sys.stderr.write(
                f"[ALLOW-SENTINEL] grant CONSUMED for task_id={task_id} "
                f"terminal_result={terminal_result} path={p}\n"
            )
        except FileNotFoundError:
            pass
        except Exception as exc:
            sys.stderr.write(
                f"[ALLOW-SENTINEL] unlink failed for {p}: {exc}\n"
            )
    return unlinked


def reap_expired_sentinel_grants() -> int:
    """Stop-cleanup helper: unlink every sentinel grant the reader rejects
    (expired, malformed, or missing a required key), so no grant file outlives
    the reader's verdict on it. Returns the count of reaped files. Best-effort;
    never raises."""
    count = 0
    for p in _enumerate_sentinel_grant_files(None):
        if _read_sentinel_grant_file(p) is not None:
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
