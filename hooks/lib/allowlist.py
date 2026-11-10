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
  - match_sentinel_grant_for_bash_command() returns the entry a single bash
    sub-command satisfies: a structural entry by equality on op/target and
    a positional prefix of the arguments, never a substring of the raw
    command line; a regex entry by re.search over that sub-command.
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

Stdlib-only; Python 3.10+.
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


def _legacy_subcommands(command: str) -> list[str]:
    """Split on every && || ; | and newline, quoted or not (the conservative view)."""
    s = command.replace("||", "\n").replace("&&", "\n").replace(";", "\n").replace("|", "\n")
    return [p.strip() for p in s.split("\n") if p.strip()]


def _bash_subcommands(command: str) -> list[str]:
    """Split a compound bash command on && || ; | and newline into stripped sub-commands.

    A separator inside a quoted word is text, as the shell reads it: `git commit -m
    "fix(x): a; b"` is one command. The quoting is read only where it is purely lexical:
    '...' and $'...' hold anything, "..." holds anything but an expansion that runs code,
    and a backslash before a quote keeps that quote from opening one. Whatever else could
    make this scan disagree with the shell -- a here-document, `$(`, a backquote, a process
    substitution, a quote left open -- is split on every separator as before, so a command
    with any of them can only get more sub-commands than the shell runs, never fewer. A
    separator outside quotes, a backslash-escaped one and one in a comment split as before.
    `&` alone is no separator, as before.
    """
    n, i, start = len(command), 0, 0
    parts: list[str] = []
    while i < n:
        ch = command[i]
        if ch == "\\":
            nxt = command[i + 1:i + 2]
            i += 2 if nxt and nxt not in ";|&\n" else 1
        elif ch in "'\"" or (ch == "$" and command[i + 1:i + 2] == "'"):
            ansi = ch == "$"
            i += 1 if ansi else 0
            quote, i = command[i], i + 1
            while i < n and command[i] != quote:
                if command[i] == "\\" and (ansi or quote == '"'):
                    i += 1
                elif quote == '"' and (command[i] == "`" or command.startswith("$(", i)):
                    return _legacy_subcommands(command) or [command]
                i += 1
            if i >= n:
                return _legacy_subcommands(command) or [command]
            i += 1
        elif ch == "`" or command.startswith(("$(", "<(", ">(", "<<"), i):
            return _legacy_subcommands(command) or [command]
        elif ch == "#" and (i == 0 or command[i - 1] in " \t\n;&|()<>"):
            # A comment: no quote in it opens one. Its separators still split, as before.
            while i < n and command[i] != "\n":
                if command[i] in ";|":
                    parts.append(command[start:i])
                    start = i + 1
                elif command.startswith("&&", i):
                    parts.append(command[start:i])
                    start, i = i + 2, i + 1
                i += 1
        elif ch in ";|\n":
            parts.append(command[start:i])
            start, i = i + 1, i + 1
        elif command.startswith("&&", i):
            parts.append(command[start:i])
            start, i = i + 2, i + 2
        else:
            i += 1
    parts.append(command[start:])
    return [p.strip() for p in parts if p.strip()] or [command]


# git global options that may be skipped when locating the subcommand for grant
# matching: a subset of git_command_classifier's git global-option table (a test
# pins it; the core install profile ships this module without the classifier),
# DELIBERATELY NARROWER: the table is for *classification* (identify the verb no
# matter what), while this subset gates *authorization*. Only options that
# retarget the repository or toggle a no-op are listed; every option carrying a
# code-execution vector is omitted on purpose, so a command bearing one never
# inherits a shorter grant and instead fails closed:
#   -c <k=v> / --config-env=  -> core.pager, alias.*, core.sshCommand,
#                                uploadpack.packObjectsHook => arbitrary exec
#   --exec-path[=<p>]         -> redirects the git subcommand binaries
#   --super-prefix            -> not needed here; omitted conservatively
# Anything unrecognized also stops the skip (default-deny).
#
# `-C` has NO bare-attached form in real git: `git -C/tmp status` is rejected
# by git itself with "unknown option: -C/tmp" (verified against git 2.54.0).
# Only the separated form `-C <dir>` (handled by _GRANT_SKIPPABLE_GIT_VALUE_OPTS
# below) is valid git syntax for `-C`, unlike --git-dir/--work-tree/--namespace,
# which DO have a real `=`-joined attached form. So `-C` is deliberately
# excluded from _GRANT_SKIPPABLE_GIT_ATTACHED_PREFIXES — including it would
# model a syntax that does not exist (harmless, since git itself fails closed
# on that token before running anything, but incorrect domain modeling). The
# table says the same: only its long value options take `=<value>`.
_GRANT_SKIPPABLE_GIT_VALUE_OPTS = frozenset({
    '-C', '--git-dir', '--work-tree', '--namespace',
})
_GRANT_SKIPPABLE_GIT_ATTACHED_PREFIXES = ('--git-dir=', '--work-tree=', '--namespace=')
_GRANT_SKIPPABLE_GIT_FLAGS = frozenset({
    '-p', '--paginate', '--no-pager', '--bare', '--literal-pathspecs',
    '--no-literal-pathspecs', '--icase-pathspecs', '--no-replace-objects',
    '--no-optional-locks',
})


def _strip_git_global_opts(arg_tokens: list[str]) -> list[str]:
    """Drop repo-retargeting git global options sitting before the subcommand.

    Input is the token list FOLLOWING the `git` head token. Returns the suffix
    beginning at the first token that is not a safely-skippable global option.
    Stops (rather than skipping) at any option not on the safe-list, so
    `git -c core.pager=x commit` keeps its `-c` and can never prefix-match a
    plain `git commit` grant.
    """
    i = 0
    n = len(arg_tokens)
    while i < n:
        tok = arg_tokens[i]
        if tok in _GRANT_SKIPPABLE_GIT_VALUE_OPTS:
            # Separated form: `-C <dir>`. A dangling option (no value) is
            # malformed; stop rather than run off the end.
            if i + 1 >= n:
                break
            i += 2
            continue
        if tok in _GRANT_SKIPPABLE_GIT_FLAGS:
            i += 1
            continue
        # Attached form: `--git-dir=<dir>`, `--work-tree=<dir>`, `--namespace=<ns>`.
        # `-C` is NOT included here: real git has no bare-attached `-C<dir>`
        # form (only the separated `-C <dir>` form above is valid git syntax).
        # Require a non-empty value so a bare `--git-dir=` etc. is not silently
        # treated as attached.
        if any(tok.startswith(p) and len(tok) > len(p)
               for p in _GRANT_SKIPPABLE_GIT_ATTACHED_PREFIXES):
            i += 1
            continue
        break
    return arg_tokens[i:]


def _is_git_head(head_op: str) -> bool:
    """True when the head token invokes git (bare or path-qualified)."""
    return head_op == 'git' or head_op.rsplit('/', 1)[-1] == 'git'


def match_sentinel_grant_for_bash_command(task_id: str, command: str) -> dict | None:
    """Structural match of bash command against sentinel-grant allowed_operations[].

    Two entry types are supported:

    1. Structural entries (op != "*"): the first whitespace-separated token of
       each sub-command after compound splitting is compared against entry["op"]
       by exact equality. Leading KEY=VALUE env-var assignments are skipped
       before extracting the head token so that `GIT_DIR=/tmp git push` matches
       an entry with op="git". Optional entry["target"] (second token) and
       entry["args_contain"] (a POSITIONAL PREFIX of the argument tokens, not a
       free substring search) apply as before.

       When the head token is git, the argument tokens are matched twice: once
       verbatim, and once with repo-retargeting global options removed (see
       _strip_git_global_opts). This is what lets `/allow git commit` authorize
       the canonical `git -C <dir> commit -F <msgfile>` shape. The verbatim view
       is retained so a grant that names a global option itself keeps pinning it
       exactly. Options carrying a code-execution vector (-c, --exec-path) are
       never skipped, so such a command fails closed against a shorter grant.

    2. Regex entries (op="*" with "regex" field): the "regex" value is tested
       with re.search() against the full subcommand string (before env-var
       stripping). This lets regex /allow grants reach subagents too.

    The function NEVER substring-matches the entry["op"] against the raw
    command line — that was the legacy bash-safety bypass closed by R2.

    Returns the matched allowed_operations[] entry on success, None otherwise.
    """
    grant = load_sentinel_grant_for_task(task_id)
    if grant is None:
        return None
    ops = grant.get("allowed_operations", [])
    subcommands = _bash_subcommands(command)

    # Compound-command guard (applies to BOTH regex and structural grants):
    # a single grant authorizes exactly one operation. Compound commands like
    # "git push origin; echo PWNED" or "git push && rm -rf /" would otherwise
    # let an attacker chain an unauthorized operation after the authorized one.
    if len(subcommands) != 1:
        return None

    # Pass 1: regex sentinel entries (op="*" with "regex" field).
    # Single subcommand already guaranteed above.
    for entry in ops:
        if not isinstance(entry, dict) or entry.get("op") != "*":
            continue
        regex_pattern = entry.get("regex")
        if isinstance(regex_pattern, str):
            if _regex_safe(regex_pattern, subcommands[0]):
                return entry

    # Pass 2: structural entries.
    sub = subcommands[0]
    # Skip leading KEY=VALUE env-var tokens.
    tokens = sub.split()
    if not tokens:
        return None
    env_skip = 0
    while env_skip < len(tokens) and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[env_skip]):
        env_skip += 1
    if env_skip >= len(tokens):
        return None
    tokens = tokens[env_skip:]
    head_op = tokens[0]
    head_target = tokens[1] if len(tokens) >= 2 else None
    raw_rest = tokens[1:]
    # Second candidate view with repo-retargeting git global options removed, so
    # a short `git commit` grant reaches the canonical `git -C <dir> commit ...`
    # shape this repo actually emits. Both views are tried; the raw view is kept
    # so an explicitly-pinned grant (`/allow git --git-dir=/a commit`) still
    # requires that exact prefix and is never widened to another repository.
    stripped_rest = _strip_git_global_opts(raw_rest) if _is_git_head(head_op) else raw_rest
    rest_views = [raw_rest] if stripped_rest == raw_rest else [raw_rest, stripped_rest]
    target_views = {head_target}
    target_views.update(v[0] for v in rest_views if v)
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
        # Normalize: split multi-word entries into individual tokens for
        # prefix matching. Prevents comment-injection bypass via substring
        # matching (e.g. "push origin" in "commit -m push origin").
        normalized_ac: list[str] = []
        for a in args_contain:
            if isinstance(a, str):
                normalized_ac.extend(a.split())
        if not normalized_ac:
            return entry
        for rest_tokens_list in rest_views:
            if (len(rest_tokens_list) >= len(normalized_ac)
                    and rest_tokens_list[:len(normalized_ac)] == normalized_ac):
                return entry
    return None


def match_sentinel_grant_for_write(task_id: str, session_id: str, target_path: str) -> dict | None:
    """Structural match of a Write-overwrite operation against sentinel-grant allowed_operations[].

    Mirrors match_sentinel_grant_for_bash_command() for the Write tool.
    Match requires session_id equality and op=='Write'. Target matching:
      - 'target' key present: exact string equality with target_path required;
        absent or null or non-string 'target' values deny (fail-closed).
      - 'args_contain' key present (no 'target'): legacy fallback — allow only
        if args_contain is a one-item list whose sole element exactly equals
        target_path (no substring matching).
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
        # Key-presence branching (ORIGINAL matcher fix):
        #   'target' present  → exact equality required; fail-closed on non-string/empty
        #   'args_contain' present (no 'target') → legacy compat: one-item exact equality
        #   neither → intentional wildcard (bare /allow Write)
        if "target" in entry:
            t = entry["target"]
            if isinstance(t, str) and t and t == target_path:
                return entry
            # else: target present but null/empty/wrong path — deny (fail-closed)
        elif "args_contain" in entry:
            ac = entry["args_contain"]
            if isinstance(ac, list) and len(ac) == 1 and isinstance(ac[0], str) and ac[0] == target_path:
                return entry
        else:
            # Bare {"op":"Write"} — intentional wildcard
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
