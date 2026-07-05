"""PreToolUse allowlist grant reader for Claude Code hooks.

Single source of truth for grant-read, grant-match, and grant-consume
logic used by PreToolUse and PostToolUse hooks.

Contract:
  - PreToolUse hooks ONLY read the grant; they never delete it.
  - Deletion is deferred to posttool-allowlist-consume.py (PostToolUse).
  - Subagent firewall check stays in each caller; this library has no
    subagent awareness.

Extracted from pretool-orchestrator-gate.py lines 155-183 (initial
extraction, task aaf3c44). Extended with consolidation functions for
allow-6 (task 20260518-155948) to eliminate 4 independent open/flock/
JSON-load/match implementations across hook files.

Sentinel-file grant lifecycle (task 20260519-211515 R2 / AC2):
  - In addition to the legacy pattern-string grant file
    (/tmp/claude-bash-allowlist-<sid>.json), the orchestrator may write a
    structured sentinel grant at /tmp/claude-grants/<task_id>-<nonce>.json
    containing {task_id, session_id, allowed_operations[], created_at,
    expires_at}. allowed_operations[] is a structured list of {op, target,
    args_contain?, ...} dicts, NOT a free-text regex.
  - load_sentinel_grant_for_task() reads and validates the sentinel.
  - match_sentinel_grant_for_bash_command() returns True iff the bash
    command structurally satisfies at least one entry in allowed_operations[].
    The predicate NEVER substring-matches against the raw command line;
    the only allowed predicate is structured-equality on op/target/args.
  - consume_sentinel_grant_on_terminal_result() unlinks the sentinel on
    ANY terminal result (success, non-zero exit, malformed grant, or
    comment-only attack). This is the consume-on-any-terminal-result
    semantic (item 2 of qa-output-retrospective-classification-20260519-175339).
  - reap_expired_sentinel_grants() is called by stop-cleanup hook to remove
    unconsumed grants at session end.

Stdlib-only; Python 3.12+ required.
"""

import fcntl
import json
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import NamedTuple


# Sentinel-grant filesystem layout (task 20260519-211515 R2 / AC2)
SENTINEL_GRANT_DIR = "/tmp/claude-grants"


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


class MatchResult(NamedTuple):
    """Result of a grant-pattern match."""
    pattern: str
    is_regex: bool
    matched_sub: str


def _match_loaded_grant(
    grant: dict,
    candidates: list[str],
    literal_policy: str,
    regex_timeout: int = 1,
) -> MatchResult | None:
    """Pure match step: takes an already-loaded grant dict, no file I/O.

    Args:
        grant: decoded JSON grant dict (keys: pattern, is_regex)
        candidates: list of strings to match against (e.g. subcommands,
                    tool_name, full command)
        literal_policy: "exact_or_substr" (pattern==cand or pattern in cand),
                        "substr_only" (pattern in cand only), or
                        "exact_only" (pattern==cand only — used by PreTool
                        read_grant to mirror PostTool consume_grant_for_posttool
                        Branch 3 exact-only semantics)
        regex_timeout: SIGALRM timeout in seconds for regex match (default 1).

    Returns:
        MatchResult on first match, None if no candidate matches or grant
        is invalid.
    """
    pattern = grant.get("pattern", "")
    if not isinstance(pattern, str) or not pattern:
        return None
    is_regex = bool(grant.get("is_regex", False))

    for cand in candidates:
        matched = False
        if is_regex:
            matched = _regex_safe(pattern, cand, regex_timeout)
        else:
            if literal_policy == "exact_or_substr":
                matched = pattern == cand or pattern in cand
            elif literal_policy == "exact_only":
                matched = pattern == cand
            else:  # substr_only
                matched = pattern in cand

        if matched:
            return MatchResult(pattern=pattern, is_regex=is_regex, matched_sub=cand)

    return None


def _load_and_match(
    sid: str,
    candidates: list[str],
    literal_policy: str,
    regex_timeout: int = 1,
) -> MatchResult | None:
    """Blocking-lock wrapper: acquire LOCK_EX on grant file, json.load,
    then delegate to _match_loaded_grant.

    Args:
        sid: session id (used to locate /tmp/claude-bash-allowlist-<sid>.json)
        candidates: list of strings to match against
        literal_policy: passed through to _match_loaded_grant
        regex_timeout: passed through to _match_loaded_grant

    Returns:
        MatchResult on match, None otherwise. Never unlinks the grant file.
    """
    flag_path = Path(f"/tmp/claude-bash-allowlist-{sid}.json")
    try:
        with open(flag_path, "r+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                grant = json.load(fh)
            except Exception:
                return None
            return _match_loaded_grant(grant, candidates, literal_policy, regex_timeout)
    except (FileNotFoundError, OSError):
        return None
    except Exception:
        return None


def read_grant(tool_name: str, sid: str) -> bool:
    """Check /allow grant for tool_name. Read-only — does NOT delete the grant.

    Literal match: pattern == tool_name ONLY (exact_only). Mirrors PostToolUse
    consume_grant_for_posttool Branch 3 to close the PreTool/PostTool
    asymmetry that allowed substring grants (e.g. '/allow Re') to bypass
    PreTool gates while never being consumed at PostTool — causing grant
    leakage past single-use. See cycle 20260519-211515 Item D.
    Regex match: re.search(pattern, tool_name) (unchanged, see is_regex
    branch of _match_loaded_grant).

    Deletion is deferred to posttool-allowlist-consume.py (PostToolUse).
    Returns True if grant matches, False otherwise (missing file = False).
    """
    result = _load_and_match(sid, [tool_name], "exact_only", 1)
    if result is not None:
        sys.stderr.write(f"[ALLOW] grant matched for {tool_name}, consume deferred to PostToolUse\n")
        return True
    return False


def read_grant_for_git_command(command: str, sid: str) -> bool:
    """Check /allow grant for a git command. Read-only — does NOT delete the grant.

    Literal match: pattern in command (substr_only — no exact match branch).
    Regex match: re.search(pattern, command).

    Subagent firewall check stays in the caller (_check_git_allowlist).
    Returns True if grant matches, False otherwise.
    """
    result = _load_and_match(sid, [command], "substr_only", 1)
    if result is not None:
        sys.stderr.write("[ALLOW] grant matched, consume deferred to PostToolUse\n")
        return True
    return False


def match_grant_for_bash_command(
    command: str,
    sid: str,
    regex_timeout: int = 1,
) -> MatchResult | None:
    """Match /allow grant for a compound bash command. Read-only — does NOT delete.

    Acquires LOCK_EX | LOCK_NB on sidecar .lock file with 3x100ms retry
    (matches existing bash heredoc NB-flock behavior — distinct from the
    blocking LOCK_EX used by _load_and_match).

    Splits command on &&, ||, ;, | (order: || before | so || becomes single
    newline, not |\\n).

    Returns MatchResult on first subcommand match, None if no match / no grant.
    Subagent firewall check stays in the bash wrapper caller.
    """
    flag_file = f"/tmp/claude-bash-allowlist-{sid}.json"
    lock_file = f"{flag_file}.lock"

    # NB flock with 3x100ms retry (preserves existing bash heredoc behavior)
    lock_fd = None
    try:
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
        attempts = 0
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                attempts += 1
                if attempts >= 3:
                    return None
                time.sleep(0.1)

        # Lock held — read grant file
        if not os.path.exists(flag_file):
            return None
        try:
            with open(flag_file) as f:
                grant = json.load(f)
        except Exception:
            return None

        # Build subcommand candidates (split on && || ; |)
        # Order matters: || before | so '||' becomes a single newline
        s = command.replace("||", "\n").replace("&&", "\n").replace(";", "\n").replace("|", "\n")
        subcmds = [t.strip() for t in s.split("\n") if t.strip()]
        if not subcmds:
            subcmds = [command]

        return _match_loaded_grant(grant, subcmds, "substr_only", regex_timeout)

    except Exception:
        return None
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(lock_fd)
            except Exception:
                pass


def consume_grant_for_posttool(sid: str, tool_name: str, command: str) -> bool:
    """Atomically match and unlink the /allow grant for a PostToolUse event.

    This is the SOLE tool-execution consumption unlink site for /allow grant files.
    PreToolUse hooks must NEVER unlink; only this function does.

    Replicates posttool-allowlist-consume.py lines 68-91 branch logic:
      Branch 1 (Bash tool): compound-split + exact-or-substr match against
                            subcommands and full command
      Branch 2 (Bash fallback): exact pattern == tool_name if no subcommand matched
      Branch 3 (non-Bash, literal): exact-only (pattern == tool_name) —
                                    prevents /allow Write consuming TodoWrite
      Branch 4 (non-Bash, regex): re.search(pattern, tool_name)

    Performs match + os.unlink under a single fcntl.flock(LOCK_EX) (atomicity).

    Args:
        sid: session id
        tool_name: the tool that was called (e.g. "Bash", "Write", "TodoWrite")
        command: the Bash command string (empty string for non-Bash tools)

    Returns:
        True if grant matched and was consumed (unlinked), False otherwise.
    """
    grant_path = Path(f"/tmp/claude-bash-allowlist-{sid}.json")
    try:
        with open(grant_path, "r+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                grant = json.load(fh)
            except Exception:
                return False

            pattern = grant.get("pattern", "")
            if not isinstance(pattern, str) or not pattern:
                return False
            is_regex = bool(grant.get("is_regex", False))

            matched = False
            if tool_name == "Bash":
                # Branch 1: split compound command, check each subcommand and full command
                # Mirrors posttool-allowlist-consume.py:34 — || before | (double-newline for ||)
                s = command.replace("||", "\n\n").replace("&&", "\n").replace(";", "\n").replace("|", "\n")
                subcommands = [t.strip() for t in s.split("\n") if t.strip()]
                candidates = subcommands + [command]
                for part in candidates:
                    if is_regex:
                        if _regex_safe(pattern, part):
                            matched = True
                            break
                    else:
                        if pattern == part or pattern in part:
                            matched = True
                            break
                # Branch 2 (Bash fallback): exact tool-name match for grants like `/allow Bash`
                if not matched and not is_regex and pattern == tool_name:
                    matched = True
            else:
                if is_regex:
                    # Branch 4
                    matched = _regex_safe(pattern, tool_name)
                else:
                    # Branch 3: exact-only — prevents /allow Write consuming TodoWrite
                    matched = (pattern == tool_name)

            if matched:
                try:
                    os.unlink(grant_path)
                except FileNotFoundError:
                    pass
                sys.stderr.write(f"[ALLOW] grant CONSUMED for {tool_name}\n")
                return True
            return False

    except FileNotFoundError:
        return False
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────
# Sentinel-grant lifecycle (task 20260519-211515 R2 / AC2)
#
# The sentinel grant is a STRUCTURED replacement for the legacy
# pattern-string grant. The hook reads /tmp/claude-grants/<task_id>.json
# at PreToolUse time instead of grepping the command text. The predicate
# never substring-matches against the command line; allowed_operations[]
# is a structured list of {op, target?, args_contain?} dicts that must
# match by exact op-and-target equality.
#
# Contract (consume-on-any-terminal-result):
#   - success: grant unlinked on exit 0
#   - failure: grant unlinked on non-zero exit (1..255)
#   - malformed: grant unlinked when JSON parse fails during posttool
#   - comment_only: pretool denies; posttool MUST NOT leave leftover state
# ─────────────────────────────────────────────────────────────────────


def _enumerate_sentinel_grant_files(task_id: str | None = None) -> list[Path]:
    """List existing sentinel grant files under SENTINEL_GRANT_DIR.

    If task_id is provided, restrict to files whose basename starts with
    "<task_id>-" or equals "<task_id>.json".
    """
    try:
        d = Path(SENTINEL_GRANT_DIR)
        if not d.is_dir():
            return []
        if task_id:
            return [p for p in d.glob("*.json")
                    if p.name == f"{task_id}.json" or p.name.startswith(f"{task_id}-")]
        return list(d.glob("*.json"))
    except Exception:
        return []


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
    grant_path = matches[0]
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


def _bash_subcommands(command: str) -> list[str]:
    """Split a compound bash command on && || ; | into stripped sub-tokens."""
    s = command.replace("||", "\n").replace("&&", "\n").replace(";", "\n").replace("|", "\n")
    parts = [p.strip() for p in s.split("\n") if p.strip()]
    return parts or [command]


def match_sentinel_grant_for_bash_command(task_id: str, command: str) -> dict | None:
    """Structural match of bash command against sentinel-grant allowed_operations[].

    Two entry types are supported:

    1. Structural entries (op != "*"): the first whitespace-separated token of
       each sub-command after compound splitting is compared against entry["op"]
       by exact equality. Leading KEY=VALUE env-var assignments are skipped
       before extracting the head token so that `GIT_DIR=/tmp git push` matches
       an entry with op="git". Optional entry["target"] (second token) and
       entry["args_contain"] (list[str] of arg-fragment substrings) apply as
       before.

    2. Regex entries (op="*" with "regex" field): the "regex" value is tested
       with re.search() against the full subcommand string (before env-var
       stripping). This allows regex /allow grants to reach subagents, which
       cannot use the legacy grant path.

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
    for entry in ops:
        if not isinstance(entry, dict):
            continue
        want_op = entry.get("op")
        if not isinstance(want_op, str) or want_op == "*" or want_op != head_op:
            continue
        want_target = entry.get("target")
        if want_target is not None and want_target != head_target:
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
        rest_tokens_list = tokens[1:]
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

    The 'target' field name mirrors the existing schema (allowlist.py:22);
    do NOT use 'target_path'.

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

    This implements the consume-on-any-terminal-result semantic mandated by
    AC2: grants must be unlinked on the four mandatory terminal-consumption
    cases (success, non_zero exit, malformed grant, comment_only attack).

    Args:
        task_id: the task whose sentinel grant should be reaped.
        terminal_result: one of "success", "failure", "non_zero", "malformed",
                         "comment_only", or any other terminal sentinel string.
                         The value is logged but does not change behavior —
                         all four cases unlink unconditionally.

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
    """Stop-cleanup helper: unlink every sentinel grant whose expires_at has
    elapsed. Returns the count of reaped files. Best-effort; never raises."""
    count = 0
    for p in _enumerate_sentinel_grant_files(None):
        try:
            with open(p) as f:
                grant = json.load(f)
        except Exception:
            # Malformed grant — also reap.
            try:
                os.unlink(p)
                count += 1
            except Exception:
                pass
            continue
        exp = grant.get("expires_at")
        elapsed = False
        try:
            now = time.time()
            if isinstance(exp, (int, float)) and exp < now:
                elapsed = True
            elif isinstance(exp, str):
                from datetime import datetime
                s = exp.replace("Z", "+00:00")
                if datetime.fromisoformat(s).timestamp() < now:
                    elapsed = True
        except Exception:
            elapsed = True
        if elapsed:
            try:
                os.unlink(p)
                count += 1
            except Exception:
                pass
    return count
