#!/usr/bin/env python3
"""PreToolUse:* hook — the write permission dispatch records derive, then
tool-policy.v1.json for all subagents.

Single hook that consumes the harness ``policies/tool-policy.v1.json`` (resolved
via the shared hooks/lib/claude_home resolver) through
lib.policy_registry.is_allowed() and lib.agent_resolver.resolve_agent_type().

Derived write permission (D8, D21, D24), run first,
for every caller, the main agent included, on the Write / Edit / MultiEdit /
NotebookEdit target and every Bash write target:
  - A path a dispatch of this session declares may be written only by that
    dispatch. What a dispatch declares: the artifacts[].path of its
    obligation, the producer question that obligation names when
    schemas/producer-question.v1.json lets its role write one, and what the
    template it was dispatched from declares in the current command files
    (lib/dispatch_template), each placeholder bound to that dispatch's own
    values. A declared directory covers what lies beneath it.
  - The declaring dispatch's write skips the role's allow prefixes; its deny
    prefixes, tool lists and the scratch rule below still apply.
  - Any other caller's write of a declared path -> exit 2 naming the path and
    the declaring obligation's role, whatever an allow prefix (dev's '*',
    changelog-analyst's '*/docs/dev/') says. No prefix table names an artifact.
  - An undeclared path keeps the role policy rows below.
  - What a dispatch can declare has the shapes of the paths the current
    command files' templates write ("path" in their JSON, any bracketed text
    a placeholder) and the producer question's: a target with no part such a
    path can end on is undeclared without reading the transcript or a
    subagent's files, so its cost does not grow with the session. A path a
    dispatch's own obligation names outside every template's shape is not
    held for it.
  - The calling subagent's own dispatch is read from its record in the
    session transcript, found back from the end by the call its meta names
    (_Record; when its meta cannot be read or names no call by a plain id,
    among every dispatch record, in one forward pass). Its template is the
    one of its obligation's pipeline, role and profile, or, when it carries
    none, of its subagent_type in the command whose span holds that record.
  - Every other dispatch, for the main agent's write and for a subagent's
    write its own dispatch does not declare, is read from the files the CLI
    keeps for the subagent it started, beside the session transcript
    (subagents/agent-<id>.meta.json: its call and subagent type;
    agent-<id>.jsonl: its prompt, the first record), never from the session
    transcript: the cost grows with the started dispatches, not with the
    transcript's bytes. Its template is the one of its
    obligation's pipeline, role and profile, or, when it carries none, each
    of its subagent_type's in every command file (a superset of its span's
    one: it can only deny more to other callers). A dispatch refused at
    PreToolUse started no subagent and declares nothing here: these are the
    dispatches G2 acts on, at a started subagent's stop.
  - A template is bound only where its paths could cover the target, and no
    command's fences are read where no obligation block of any command file
    declares a path that could (lib/declared_paths._template_bounds; with a
    "/.." in the prompt, where its own text lets no bound value make one
    cover: _bounds_may_cover_back). A
    dispatch whose obligation block, valid or not, names no artifact and no
    producer question that covers the target, and whose templates cannot,
    declares nothing that does: it is neither validated nor bound
    (_obligation_may_declare). One decision reads each command file once
    and the agent and command rosters once (roster.held); nothing is kept
    from one call to the next.
  - The readers (shapes, started dispatches, what a dispatch declares) are
    lib/declared_paths, loaded only for a write; this file keeps the rule
    and the session transcript's reader (_Record).

Grant binding (D8), beside it and for every caller alike: only <name> writes
under <state dir>/agentic-commit/<name>/, <name> a listed role (the push- and
merge-analyst grants); a removal is no write (_check_grant_writes).

/clean's approved actions (P9-4; D8), beside it and for every caller alike:
while a human-typed /clean's span is active, what its owner approved (the
request's docs/clean/user-approvals-<id>.json: a move's or rename's
destination, a fix_style file) is written by that span's cleaner only, and the
project's root README.md and ARCHITECTURE.md by its rule-inspector only
(_check_clean_writes; hooks/pretool-claude-config-guard.py reads clean_grant).

Behavior:
  - Every caller, first: a protected file's write, delete or rename, and a
    ScheduleWakeup prompt typing a harness command -> exit 2 (P5; _check_protected).
  - Main agent (no agent_id) -> exit 0 after the derived permission and the
    grant binding (the orchestrator gate handles the rest of the main agent).
  - Subagent role unresolvable (a NORMAL state in agent_resolver), or one
    the policy does not list (Explore, Plan, general-purpose, `<plugin>:<name>`)
    -> exit 0: no role row applies, never is_allowed's "unknown role".
  - Resolved role + denied tool/path -> exit 2 with structured stderr
    JSON: {"role", "tool", "target", "deny_reason"}.
  - Deny-logic import/bootstrap failure -> exit 2 (FAIL CLOSED): the
    security imports live inside a fail-closed bootstrap guard, NOT inside the
    blanket `except Exception: sys.exit(0)` (which would silently fail open).

Bash write targets:
  - Every write target of a Bash command is authorized as if it were a Write
    target, so a redirect, heredoc or copy writes nothing a Write may not.
  - What each shell -c string, eval or command substitution the command runs
    writes is read the same way, here and in the protected stage.

Scratch namespace actor-exactness:
  - Every write target the prefix layer admits is additionally classified as
    owner scratch / sibling scratch / arbitrary system temp.
  - Owner scratch is allowed for every role; a SIBLING's scratch directory is
    denied for every role; arbitrary /tmp and /var/tmp are denied for every
    role INCLUDING one holding a bare '*' grant, which no prefix list can deny.
  - Each role's OWN pre-existing exact temp prefixes are generated from the
    policy file and survive verbatim.

Fail-safe: any unexpected exception logs to stderr and exits 0 to
avoid bricking the tool pipeline on a hook bug. Run as a script, the process
ends with the status and output it decided without the interpreter's teardown
(_end).
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The deny-logic imports are loaded inside a FAIL-CLOSED bootstrap
# guard, NOT at module top (where an ImportError would be a dirty uncaught
# exit 1) and NOT inside the blanket `except Exception: sys.exit(0)` in __main__
# (which would silently fail OPEN). A missing/broken deny-logic module on a
# fresh clone must BLOCK (exit 2), never allow.
WRITE_TOOLS: set
resolve_agent_type = None  # type: ignore[assignment]
extract_bash_write_paths = None  # type: ignore[assignment]
extract_bash_touched_paths = None  # type: ignore[assignment]
is_allowed = None  # type: ignore[assignment]
harness_state_dir = None  # type: ignore[assignment]


def _bootstrap_security() -> None:
    """Import the deny-logic modules; FAIL CLOSED (exit 2) on any failure.

    This MUST be called from main() BEFORE any authorization decision and MUST
    NOT be wrapped by the blanket fail-open `except` in __main__.
    """
    global WRITE_TOOLS, resolve_agent_type, extract_bash_write_paths, extract_bash_touched_paths, is_allowed, \
        harness_state_dir
    try:
        from lib.agent_resolver import resolve_agent_type as _rat
        from lib.bash_write_targets import extract_bash_touched_paths as _ebtp, extract_bash_write_paths as _ebwp
        from lib.policy_registry import WRITE_TOOLS as _wt, is_allowed as _ia
        from lib.harness_state_dir import harness_state_dir as _hsd
    except Exception as e:  # ImportError, bootstrap failure, resolver failure
        sys.stderr.write(
            "BLOCKED by tool-policy.v1: deny-logic bootstrap FAILED — the policy "
            f"enforcement module could not be imported ({e}). Failing CLOSED "
            "(exit 2) rather than allowing; repair the harness install.\n"
        )
        sys.exit(2)
    WRITE_TOOLS = _wt
    resolve_agent_type = _rat
    extract_bash_write_paths = _ebwp
    extract_bash_touched_paths = _ebtp
    is_allowed = _ia
    harness_state_dir = _hsd


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def _extract_targets(tool_name: str, tool_input: dict) -> list:
    """Return list of policy targets for the (tool, input) pair.

    For Bash: every write target the command and each shell -c layer it runs
    names, each authorized as a Write target, so a heredoc or redirect writes
    nothing a Write of the same path may not. A Bash command with no write
    target has no row to check: no role's tool lists exclude Bash.
    """
    if not isinstance(tool_input, dict):
        return [] if tool_name == "Bash" else [None]
    if tool_name in WRITE_TOOLS:
        return [tool_input.get("file_path") or tool_input.get("notebook_path")]
    if tool_name == "Read":
        return [tool_input.get("file_path")]
    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        return extract_bash_write_paths(command) if isinstance(command, str) else []
    return [None]


_RAW_TEMP_GRANTS = {"/tmp/*", "/var/tmp/*", "*/tmp/*", "*/var/tmp/*",
                    "/tmp/", "/var/tmp/"}
_SYSTEM_TEMP_ROOTS = ("/tmp", "/var/tmp")


def _project_root() -> "os.PathLike | str":
    from lib import claude_home

    return claude_home.project_dir()


def _resolved(target: str):
    from pathlib import Path

    path = Path(target).expanduser()
    if not path.is_absolute():
        path = Path(_project_root()) / path
    return path.resolve(strict=False)


def _role_temp_exceptions(role: str) -> list:
    """The role's OWN pre-existing exact temp prefixes, generated from the
    policy file itself -- never from a prose enumeration.

    An entry qualifies when it names tmp/var-tmp and is NOT one of the bare
    raw-temp grants.  These survive the raw-temp denial verbatim, for exactly
    the role that holds each.  A CLAUDE_STATE_DIR below a temp root is no
    arbitrary temp: the role's '*/' entries (an analyst's grants) hold in it.
    """
    from lib.policy_registry import get_role_policy

    allowed = get_role_policy(role).get("allowed_write_path_prefixes", []) or []
    state = harness_state_dir()
    out = []
    for entry in allowed:
        if not isinstance(entry, str) or entry in _RAW_TEMP_GRANTS:
            continue
        parts = entry.strip("*").split("/")
        if "tmp" in parts:
            out.append(entry)
        elif state not in _SYSTEM_TEMP_ROOTS and entry.startswith("*/"):
            out.append(state + entry[1:] + ("" if entry.endswith("*") else "*"))
    return out


def _matches_role_exception(role: str, target: str) -> bool:
    from lib import policy_registry

    return bool(
        policy_registry._path_in_prefixes(target, _role_temp_exceptions(role))
    )


def _owner_binding(role: str, data: dict):
    """Best-effort owner binding for the caller, or None."""
    session_id = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID")
    dispatch_id = data.get("agent_id")
    if not session_id or not dispatch_id:
        return None
    try:
        from lib import session_resources

        pointer = session_resources.resolve_current_resource_session(
            _project_root(), session_id
        )
        return {
            "claude_session_id": session_id,
            "resource_session_id": pointer["resource_session_id"],
            "role": role,
            "dispatch_id": dispatch_id,
        }
    except Exception:
        return None


def _scratch_status(role: str, target: str, data: dict) -> str:
    """Classify a write target as owner / sibling / system_temp / outside.

    Authoritative path: session_resources.classify_target, which owns the
    namespace layout.  When no resource session is provisioned (or the module
    is absent) the same decision is taken structurally from the path shape
    <project>/.claude/scratch/<resource_session_id>/<role>/<dispatch_id>/...,
    because actor-exactness must not silently degrade to "allow" -- a JSON
    prefix admits a sibling's directory as readily as the owner's.
    """
    from pathlib import Path

    binding = _owner_binding(role, data)
    if binding is not None:
        try:
            from lib import session_resources

            return session_resources.classify_target(
                _project_root(), binding, target
            )["status"]
        except Exception:
            pass
    resolved = _resolved(target)
    scratch_root = Path(_project_root()).resolve(strict=False) / ".claude" / "scratch"
    try:
        rel = resolved.relative_to(scratch_root).parts
    except ValueError:
        for root in _SYSTEM_TEMP_ROOTS:
            root_path = Path(root)
            if resolved == root_path or root_path in resolved.parents:
                return "system_temp"
        return "outside"
    dispatch_id = data.get("agent_id")
    if len(rel) >= 3 and rel[1] == role and dispatch_id and rel[2] == dispatch_id:
        return "owner"
    return "sibling"


def _check_scratch_actor_exactness(role: str, target, data: dict):
    """Actor-exact scratch namespace + all-role raw-temp denial.

    Three decisions, taken for every write target:
      owner scratch        -> allow (every role)
      sibling scratch      -> DENY  (every role)
      arbitrary /tmp,/var/tmp -> DENY (every role, INCLUDING a role holding a
                               bare '*' grant, which no prefix list can deny)
                               unless the target matches one of that role's
                               OWN pre-existing exact temp prefixes.

    Returns (True, "ok") or (False, reason).  A target the gate cannot resolve
    (dynamic/unexpanded) is left to the prefix layer.
    """
    if not isinstance(target, str) or not target:
        return (True, "ok")
    if "$" in target or "`" in target or "\x00" in target:
        return (True, "ok")
    status = _scratch_status(role, target, data)
    if status == "sibling":
        return (False, "sibling scratch target denied: actor-exact namespace")
    if status == "system_temp":
        if _matches_role_exception(role, target):
            return (True, "ok")
        return (
            False,
            "arbitrary /tmp and /var/tmp are denied for every role; use the "
            "managed scratch namespace .claude/scratch/<session>/<role>/<dispatch>/",
        )
    return (True, "ok")


def _emit_block(role: str, tool: str, target, reason: str) -> None:
    payload = {
        "role": role,
        "tool": tool,
        "target": target,
        "deny_reason": reason,
    }
    sys.stderr.write(
        f"BLOCKED by tool-policy.v1: {json.dumps(payload, separators=(',', ':'))}\n"
    )


def _note_bash_write_target(data: dict, target) -> None:
    """Explain an INFERRED Bash write-target refusal (self-explaining
    denial for the known false-positive class): state the target is inferred
    from static shell-text scanning, not an observed write, name the target
    and the shell segment it came from, and give the actionable rewording.

    Entirely swallowed on any failure: an exception here must never turn a
    DENY into an ALLOW via the __main__ blanket `except Exception: sys.exit(0)`
    fail-open catch (D4 safety contract) -- this body never raises outward.
    """
    try:
        import re

        command = (data.get("tool_input") or {}).get("command") or ""
        word = str(target)
        pieces = re.split(r"&&|\|\||;|\||\n", command)
        pattern = re.compile(r"(?<![\w./~$-])" + re.escape(word) + r"(?![\w./-])")
        segment = command
        for piece in pieces:
            if pattern.search(piece):
                segment = piece
                break
        segment = segment.strip()
        if len(segment) > 200:
            segment = segment[:200] + "..."
        note = (
            'tool-policy.v1 note: the target above is INFERRED from the Bash '
            'command text by a static scan (Bash write targets are checked as '
            'Write requests, hence "tool":"Write"); it is not an observed file '
            'write. Inferred target: ' + json.dumps(target) + '; read from the '
            'command segment: ' + json.dumps(segment) + '. If the command does '
            'not really write that path, reword it: keep the checkpoint id as '
            'the LAST argument of the marking command, quote it '
            '(--cp-id "cp-01"), or drop the trailing redirect (such as 2>&1) '
            'and any pipe after it. To really write a file, use an absolute '
            'allowed scratch path.\n'
        )
        sys.stderr.write(note)
    except Exception:
        pass


# -- derived write permission ------------------------------------------------
#
# The readers it decides from (the command files' template shapes, the started
# dispatches' files, what a set of dispatches declares) are lib/declared_paths,
# loaded only for a write, its bytecode cached like every lib module: this
# file, compiled on every tool call, keeps the rule and the transcript reader.
# Under their old names here they are lib/declared_paths' own.
_READERS = frozenset({
    "_HARNESS_ROOT", "_DEFAULT_SUBAGENT_TYPE", "_AGENT_ID_CHARS", "_parts", "_question_roles", "_QUESTION_PATH",
    "_TEMPLATE_PATH_RE", "_SHAPE_PLACEHOLDER_RE", "_ANY", "_shape", "_read_text", "_command_text",
    "_declarable_shapes", "_could_be_declared", "_declared_paths", "_load_json", "_plain_agent_id", "_agent_files",
    "_FENCE_SHAPES", "_segment_prefix", "_template_shapes", "_example_shapes", "_template_bounds",
    "_shapes_may_cover", "_template_may_cover", "_PATTERN_FIELDS", "_obligation_may_declare",
    "_started_dispatches", "_caller_dispatches", "_covers", "_target_forms",
})


def __getattr__(name):
    if name in _READERS:
        from lib import declared_paths

        return getattr(declared_paths, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _write_targets(tool_name: str, targets: list) -> list:
    if tool_name != "Bash" and tool_name not in WRITE_TOOLS:
        return []
    found = targets
    # An unexpanded word cannot name a declared path, and the device tree (a
    # redirect's /dev/null) holds no artifact; the role rows judge both.
    return [t for t in found if isinstance(t, str) and t and not any(c in t for c in "$`\x00")
            and not t.startswith("/dev/")]


def _session_transcript(data: dict):
    from pathlib import Path

    raw = data.get("transcript_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if path.parent.name == "subagents":  # <sid>/subagents/agent-x.jsonl -> <sid>.jsonl
        session_dir = path.parent.parent
        path = session_dir.parent / f"{session_dir.name}.jsonl"
    return path


# A dispatch declares only through its prompt, so only a record line that
# holds the prompt key is decoded: an Agent or Task call has one, and a call
# without one declares nothing and is no caller's dispatch. One search of this
# needle replaces one of "Agent" and one of "Task", each a pass over the file.
_PROMPT_KEY = b'"prompt"'
_DISPATCH_NAMES = (b'"Agent"', b'"Task"')
_PIECE = 1 << 22  # bytes per read of the forward scan
_BACK_PIECE = 1 << 20  # the first read back from an offset; each further read doubles


class _Record:
    """The session transcript, read where the derived permission looks and no
    further: back from the end for the calling subagent's own dispatch, back
    from a dispatch for the command whose span holds it, and forward a piece
    at a time for the lines that hold a dispatch only for a caller whose meta
    cannot be read or names no call by a plain id. The whole file is never
    held at once: at 100 MB, reading it whole and scanning every user record
    for span openers was most of what a declared-path write cost.
    A file with no end to read back from (not a regular file) is read whole."""

    def __init__(self, transcript):
        self.handle = open(transcript, "rb")
        try:
            info = os.fstat(self.handle.fileno())
            regular = stat.S_ISREG(info.st_mode)
            self.data = None if regular else self.handle.read()  # None: read in pieces
            self.size = info.st_size if regular else len(self.data)
        except BaseException:
            self.handle.close()
            raise
        self._known = None  # (offset, opener): the last opener before offset, once searched

    def close(self):
        self.handle.close()

    def lines(self, needle: bytes):
        """(begin, end, line) of each line that holds ``needle``, in order, once
        per line, as command_span._Lines.offsets finds them in the whole file
        (a last line without a newline ends at the end of the file)."""
        if self.data is not None:
            pos = self.data.find(needle)
            while pos >= 0:
                begin = self.data.rfind(b"\n", 0, pos) + 1
                end = self.data.find(b"\n", pos)
                end = len(self.data) if end < 0 else end
                yield begin, end, self.data[begin:end]
                pos = self.data.find(needle, end)
            return
        self.handle.seek(0)
        base, start, pending = 0, 0, []  # pending: the line from offset start, not yet ended
        while True:
            piece = self.handle.read(_PIECE)
            if not piece:
                break
            first = piece.find(b"\n")
            if first < 0:
                pending.append(piece)
                base += len(piece)
                continue
            line = b"".join(pending) + piece[:first] if pending else piece[:first]
            if needle in line:  # a needle holds no newline: across the pieces it is in this line
                yield start, base + first, line
            last = piece.rfind(b"\n")
            pos = piece.find(needle, first + 1, last)
            while pos >= 0:
                begin = piece.rfind(b"\n", first, pos) + 1
                end = piece.find(b"\n", pos)
                yield base + begin, base + end, piece[begin:end]
                pos = piece.find(needle, end + 1, last)
            pending, start = [piece[last + 1:]], base + last + 1
            base += len(piece)
        line = b"".join(pending)
        if needle in line:
            yield start, base, line
        self.size = base

    def _back(self, hi: int, floor: int = 0):
        """(data, offset of data in the file, offset in data of its first whole
        line) for ever longer reads back from offset ``hi``, never below offset
        ``floor`` (a line start); the read doubles each time."""
        if self.data is not None:
            yield self.data[floor:hi], floor, 0
            return
        data, base, chunk = b"", hi, _BACK_PIECE
        while base > floor:
            start = max(floor, base - chunk)
            self.handle.seek(start)
            piece = self.handle.read(base - start)
            if len(piece) != base - start:  # it shrank since: hold it whole, as one read of it would have
                self.handle.seek(0)
                self.data = self.handle.read()
                yield from self._back(min(hi, len(self.data)), min(floor, len(self.data)))
                return
            data, base, chunk = piece + data, start, chunk * 2
            if base == floor:
                yield data, base, 0
                return
            newline = data.find(b"\n")  # the line before it may start in an earlier read
            if newline >= 0:
                yield data, base, newline + 1

    def find_call(self, ident: str, prompt: str):
        """The newest Agent/Task call with id ``ident`` and this prompt, read back
        from the end of the file as _dispatch_calls reads a call; None when no
        call has both. Only lines that hold the id's JSON string are decoded."""
        from lib import command_span

        token = json.dumps(ident).encode()
        top = self.size  # the lines from offset top on are searched
        for data, base, lo in self._back(self.size):
            pos = data.rfind(token, lo, top - base)
            while pos >= 0:
                begin = max(data.rfind(b"\n", lo, pos) + 1, lo)
                end = data.find(b"\n", pos, top - base)
                end = top - base if end < 0 else end
                line = data[begin:end]
                if any(name in line for name in _DISPATCH_NAMES):
                    for block in command_span._blocks(command_span._decode(line)):
                        if (block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task")
                                and isinstance(block.get("input"), dict) and (block.get("id") or "") == ident
                                and block["input"].get("prompt") == prompt):
                            return command_span.Call(id=ident, name=block["name"], input=block["input"],
                                                     line=base + begin, result_line=0, ok=False)
                pos = data.rfind(token, lo, begin) if begin > lo else -1
            top = base + lo
        return None

    def command_before(self, offset: int):
        """The command of the last human-typed harness command before offset
        ``offset`` (a dispatch's record: its span's), read back from there as
        command_span.active_span reads back from the end; None when none is.
        Asked in record order, each stretch of the file is searched once."""
        from lib import command_span, stop_contract

        known = self._known if self._known is not None and self._known[0] <= offset else None
        floor = known[0] if known else 0
        commands = stop_contract.harness_commands()
        found, top = None, offset
        for data, base, lo in self._back(offset, floor):
            found = command_span._last_opener(data, lo, top - base, commands)
            if found:
                found = (base + found[0], found[2][0])
                break
            top = base + lo
        if found is None and known:
            found = known[1]
        self._known = (offset, found)
        return found[1] if found else None


def _dispatch_calls(record: _Record) -> list:
    """The session's Agent/Task calls, read as command_span's Span.calls reads
    them (its line reader, the main session's own records only), without the
    search for each call's result that this rule does not use, from the lines
    that hold a prompt key; read only to find the calling subagent's own
    dispatch when its meta cannot be read or names no call by a plain id
    (_own_from_tail). A
    call's line is its record's offset in the transcript: it is only ordered
    against the commands that open spans, and numbering every line of a long
    transcript would be a pass of its own."""
    from lib import command_span

    calls = []
    for begin, _end, line in record.lines(_PROMPT_KEY):
        if not any(name in line for name in _DISPATCH_NAMES):
            continue
        for block in command_span._blocks(command_span._decode(line)):
            if (block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task")
                    and isinstance(block.get("input"), dict)):
                calls.append(command_span.Call(id=block.get("id") or "", name=block["name"], input=block["input"],
                                               line=begin, result_line=0, ok=False))
    return calls




def _declarations(record, calls: list, targets=None) -> list:
    """What these dispatches declare (lib/declared_paths._declarations)."""
    from lib import declared_paths

    return declared_paths._declarations(record, calls, targets)


def _caller_label(role, data: dict) -> str:
    if role:
        return role
    if not data.get("agent_id"):
        return "main"
    return data.get("agent_type") or "unresolved"


def _check_grant_writes(role, tool_name: str, targets: list, data: dict) -> None:
    """Exit 2 when a caller other than <name> creates or overwrites a file under
    <state dir>/agentic-commit/<name>/, <name> a listed role (any, the policy
    unreadable); an unexpanded Bash word is judged by the directory it spells."""
    from lib import policy_registry

    base = f"{_resolved(harness_state_dir())}/agentic-commit/"
    roles = (policy_registry.load_policy() or {}).get("roles")
    for target in targets if tool_name == "Bash" or tool_name in WRITE_TOOLS else []:
        if not isinstance(target, str) or not target or "\x00" in target:
            continue
        if "$" in target or "`" in target:
            match = re.search(r"/agentic-commit/([^/$`]+)/", target)
            owner = match.group(1) if match else None
        else:
            path = f"{_resolved(target)}/"
            owner = path[len(base):].split("/")[0] if path.startswith(base) else None
        if owner and owner != role and (roles is None or owner in roles):
            _emit_block(_caller_label(role, data), "Write" if tool_name == "Bash" else tool_name, target,
                        f"write target {target} is in the {owner} grant directory; only the {owner} "
                        "creates or overwrites a file there")
            sys.exit(2)


def _check_declared_writes(role, tool_name: str, targets: list, data: dict) -> set:
    """Apply the derived write permission; exit 2 on another caller's write of
    a declared path. Returns the targets the caller itself declared."""
    writes = _write_targets(tool_name, targets)
    if not writes:
        return set()
    transcript = _session_transcript(data)
    if transcript is None:
        return set()
    # Loaded only for a write (a read-only call pays nothing), and FAIL CLOSED
    # like _bootstrap_security: a broken reader must never let a write through.
    try:
        from lib import command_span, declared_paths, dispatch_template, obligation, roster, stop_contract  # noqa: F401
    except Exception as e:
        sys.stderr.write(
            "BLOCKED by tool-policy.v1: derived write permission bootstrap FAILED — "
            f"the dispatch-record readers could not be imported ({e}). Failing CLOSED "
            "(exit 2) rather than allowing; repair the harness install.\n"
        )
        sys.exit(2)
    # One decision reads each command file once (declared_paths.decision) and
    # the agent and command rosters once (roster.held), however many
    # dispatches it reads.
    with declared_paths.decision(), roster.held():
        return _derived_writes(role, tool_name, writes, data, transcript)


def _derived_writes(role, tool_name: str, writes: list, data: dict, transcript) -> set:
    # What a dispatch declares is read from its subagent's files and, for the
    # caller's own, from the session transcript, which grows with the
    # session; a target no template's path can name is undeclared without
    # reading either.
    from lib import declared_paths

    try:
        shapes = declared_paths._declarable_shapes()
        undeclared = not any(declared_paths._could_be_declared(shapes, declared_paths._target_forms(target, data))
                             for target in writes)
    except Exception:  # the check below decides, as it always did
        undeclared = False
    if undeclared:
        return set()
    try:
        record = _Record(transcript)
    except (OSError, TypeError, ValueError):
        return set()
    try:
        return _decide_declared_writes(role, tool_name, writes, data, transcript, record)
    finally:
        record.close()


def _own_from_tail(data: dict, transcript, record: _Record, writes: list, forms_of):
    """(the writes the calling subagent's own dispatch declares, the call id
    of that dispatch), decided from its own transcript and meta and that one
    dispatch record, found back from the end of the session transcript: a
    running subagent's dispatch is among the newest records, so this reads
    what the subagent's own run added, not the session. A caller whose own
    transcript holds no prompt, or whose meta names a call that no record
    with that prompt holds, has no dispatch: (empty, empty). None when its
    meta cannot be read or names no call by a plain id; then its dispatch is
    found among every dispatch record (_caller_dispatches), as before."""
    try:
        from lib import command_span, declared_paths, obligation

        agent_transcript, meta = declared_paths._agent_files(transcript, data.get("agent_id"))
        if agent_transcript is None:
            return set(), set()
        prompt = obligation.read_first_record_prompt(agent_transcript)
        if prompt is None:
            return set(), set()
        with open(meta) as fh:
            named = json.load(fh).get("toolUseId")
        if not isinstance(named, str) or not command_span._PLAIN_ID.match(named):
            return None  # an id the record may spell otherwise is matched call by call
        call = record.find_call(named, prompt)
        if call is None:
            return set(), set()
        declared = _declarations(record, [call], [forms_of(t) for t in writes])
        return {t for t in writes if any(declared_paths._covers(d[0], f) for f in forms_of(t) for d in declared)}, {named}
    except Exception:
        return None


def _decide_declared_writes(role, tool_name: str, writes: list, data: dict, transcript, record: _Record) -> set:
    from lib import declared_paths

    _covers, _target_forms = declared_paths._covers, declared_paths._target_forms
    known = {}

    def forms_of(target):
        # Each target's forms once, where the reading of every dispatch takes
        # them, so one that cannot be formed raises where it always did.
        if target not in known:
            known[target] = _target_forms(target, data)
        return known[target]

    def filter_for(targets):
        try:
            return [forms_of(t) for t in targets]
        except Exception:
            return None  # no filter: every template is read, as before

    # A subagent's write of a path its own dispatch declares is its own,
    # whatever any other dispatch declares: that dispatch's record decides it.
    own, mine = set(), set()
    if data.get("agent_id"):
        found = _own_from_tail(data, transcript, record, writes, forms_of)
        if found is None:
            try:
                calls = _dispatch_calls(record)
            except (OSError, TypeError, ValueError):
                return set()  # as when the transcript could not be read
            try:
                mine = declared_paths._caller_dispatches(data, transcript, calls)
                declared = _declarations(record, [c for c in calls if c.id in mine], filter_for(writes)) if mine else []
                found = {t for t in writes if any(_covers(d[0], f) for f in forms_of(t) for d in declared)}, mine
            except Exception:
                found = set(), set()
        own, mine = found
    rest = [t for t in writes if t not in own]
    if not rest:
        return own
    # Every other dispatch: the ones the CLI started a subagent for, read from
    # their files; the caller's own dispatch neither denies nor grants here.
    declarations = [d for d in _declarations(None, declared_paths._started_dispatches(transcript), filter_for(rest))
                    if d[3] not in mine]
    for target in rest:
        forms = forms_of(target)
        covering = [d for d in declarations if any(_covers(d[0], f) for f in forms)]
        if not covering:
            continue
        roles = sorted({str(d[1]) for d in covering})
        tasks = sorted({str(d[2]) for d in covering if d[2]})
        reason = (f"write target {target} is declared by the obligation of the "
                  f"{', '.join(roles)} dispatch" + (f" for task {', '.join(tasks)}" if tasks else "")
                  + f"; only {' or '.join(roles)} writes this artifact (D8)")
        check_tool = "Write" if tool_name == "Bash" else tool_name
        _emit_block(_caller_label(role, data), check_tool, target, reason)
        sys.exit(2)
    return own


def _declared_write_allowed(role: str, tool: str, target):
    """The role's denials on the declaring dispatch's own write: its tool
    lists, deny prefixes and an unreadable policy, never its allow prefixes."""
    from lib import policy_registry

    if policy_registry.load_policy() is None:
        return is_allowed(role, tool, target)
    role_pol = policy_registry.get_role_policy(role)
    if role_pol.get("_unknown_role"):
        return is_allowed(role, tool, target)
    tool_check = policy_registry._check_tool_lists(role_pol, tool)
    if tool_check is not None:
        return tool_check
    denial = policy_registry._write_denial(role_pol, target)
    if denial is not None:
        return (False, denial)
    return (True, "ok")


# -- /clean's approved actions (P9-4) -----------------------------------------
# What /clean's owner approves is written by the producer /clean dispatches for
# it, and by no other caller (D8). No obligation declares these paths (Step 16's
# declares the execution report only, and no command template's shape covers a
# script's fix_style edit), so they are derived here, only while a human-typed
# /clean's span is the active one:
#  - the cleaner: a subagent whose own dispatch is a cleaner dispatch of that
#    span (its obligation of role cleaner and pipeline clean names
#    docs/clean/cleanup-execution-<id>.json), made after an AskUserQuestion of
#    the span came back answered, writes the destination of each approved move
#    or rename and the file of each approved fix_style (or fix) of that
#    request's approvals: docs/clean/user-approvals-<id>.json as the main
#    agent's last Write of it (Step 13) before that dispatch left it in the
#    session transcript, the record of what the owner approved, read as the
#    dispatch records are and never from the file on disk, which nothing
#    validates;
#  - the rule-inspector: a subagent whose own dispatch is a rule-inspector
#    dispatch of that span writes the project's root README.md and
#    ARCHITECTURE.md (Step 4, every run);
#  - any other caller's write of such a path, the main agent's included,
#    exits 2 naming the path and its producer.
# The producer's write of one skips its role's allow prefixes and its source
# and test denials: the owner approved that write. Its tool lists, the shared
# protected prefixes (_shared_protected_path_prefixes) and the scratch rule
# still apply. No approval covers a path outside the project, the request's
# docs/clean/ files, a .git directory, or the harness home's hooks/,
# policies/, schemas/, scripts/ or settings.json. A refused or unread record,
# or approvals that cannot be read, hold nothing and grant nothing: the role
# rows decide, as before. The cost is a directory check for any write, and the
# active span's calls where the project has a docs/clean/ directory.
_CLEAN_EXECUTION_RE = re.compile(r"docs/clean/cleanup-execution-([A-Za-z0-9][A-Za-z0-9._-]*)\.json\Z")
_CLEAN_APPROVALS_RE = re.compile(r"user-approvals-([A-Za-z0-9][A-Za-z0-9._-]*)\.json")
_CLEAN_ROOT_DOCS = ("README.md", "ARCHITECTURE.md")
_CLEAN_MOVES = frozenset({"move", "rename"})
_CLEAN_EDITS = frozenset({"fix_style", "fix"})
_CLEAN_HOME_SURFACE = ("hooks", "policies", "schemas", "scripts", "settings.json")
_CLEAN_LINE_RE = re.compile(r":\d+(?:-\d+)?\Z")


def _clean_forms(path: str, base: str) -> set:
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    forms = {os.path.normpath(path)}
    try:
        forms.add(os.path.realpath(path))
    except (OSError, ValueError):
        pass
    return forms


def _clean_grantable(path: str, project: str, home) -> bool:
    """Whether an approval may name absolute normalised ``path`` (above)."""
    rel = _below(path, project)
    if not rel or rel == "." or ".git" in rel.split(os.sep):
        return False
    if rel == os.path.join("docs", "clean") or rel.startswith(os.path.join("docs", "clean") + os.sep):
        return False
    inside = _below(path, home) if home else None
    return not (inside and inside.split(os.sep)[0] in _CLEAN_HOME_SURFACE)


def _clean_approved(doc, project: str, home) -> tuple:
    """(paths written, paths removed) by the approved actions of /clean approvals
    document ``doc``, absolute and normalised (each in its written and real form)."""
    try:
        actions = (doc.get("user_approvals") or {}).get("approved_actions") or []
    except AttributeError:
        return frozenset(), frozenset()
    written, removed = set(), set()
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict) or action.get("approved") is not True:
            continue
        kind, source = action.get("action"), action.get("file") or action.get("location")
        if kind in _CLEAN_MOVES:
            target = action.get("destination")
        elif kind in _CLEAN_EDITS:
            target = _CLEAN_LINE_RE.sub("", action.get("location") or "") or action.get("file")
            source = None
        else:
            continue
        pairs = [(target, written)] + ([(source, removed)] if kind in _CLEAN_MOVES else [])
        for value, into in pairs:
            if not isinstance(value, str) or not value or "\x00" in value:
                continue
            forms = _clean_forms(value, project)
            if all(_clean_grantable(f, project, home) for f in forms):
                into.update(forms)
    return frozenset(written), frozenset(removed)


def _clean_holds(data: dict, project: str) -> list:
    """[(role, call id, prompt, paths written, paths removed)] of each producer
    dispatch of the active span when a human-typed /clean opened it, else []."""
    from lib import claude_home, command_span, obligation

    transcript = _session_transcript(data)
    span = command_span.active_span(transcript) if transcript else None
    if span is None or span.command != "clean":
        return []
    home = claude_home.resolve()
    home = os.path.normpath(str(home)) if home else None
    root = (frozenset(f for name in _CLEAN_ROOT_DOCS for f in _clean_forms(name, project)), frozenset())
    holds, answered, approvals, read = [], False, {}, {}
    for use in span.uses("Agent", "Task", "AskUserQuestion", "Write"):
        if use.name == "AskUserQuestion":
            answered = answered or use.ok
            continue
        if use.name == "Write":  # the approvals as the main agent's last ok Write of them left them
            path, text = use.input.get("file_path"), use.input.get("content")
            found = _CLEAN_APPROVALS_RE.fullmatch(os.path.basename(path)) if isinstance(path, str) else None
            if found and use.ok and isinstance(text, str) and _clean_forms(path, project) & _clean_forms(
                    os.path.join("docs", "clean", os.path.basename(path)), project):
                read.pop(found.group(1), None)
                try:
                    approvals[found.group(1)] = json.loads(text)
                except ValueError:
                    approvals.pop(found.group(1), None)
            continue
        if use.result_at is not None and not use.ok:  # refused, or it failed: no subagent wrote for it
            continue
        kind, prompt = use.input.get("subagent_type"), use.input.get("prompt")
        if kind == "rule-inspector":
            holds.append(("rule-inspector", use.id, prompt) + root)
        elif kind == "cleaner" and answered and isinstance(prompt, str):
            parsed = obligation.parse_obligation(prompt)
            doc = parsed.obligation if isinstance(parsed, obligation.ParsedObligation) else {}
            if doc.get("role") != "cleaner" or doc.get("pipeline") != "clean":
                continue
            for artifact in doc.get("artifacts") or []:
                found = _CLEAN_EXECUTION_RE.match(str((artifact or {}).get("path") or ""))
                if found and found.group(1) in approvals:
                    if found.group(1) not in read:
                        read[found.group(1)] = _clean_approved(approvals[found.group(1)], project, home)
                    holds.append(("cleaner", use.id, prompt) + read[found.group(1)])
    return holds


def _clean_dispatch(data: dict):
    """(the call id the calling subagent's CLI meta names, its first record's
    prompt); (None, None) when either cannot be read. clean_grant holds the
    call to that prompt."""
    from lib import declared_paths, obligation

    transcript = _session_transcript(data)
    agent_transcript, meta = declared_paths._agent_files(transcript, data.get("agent_id")) if transcript else (None, None)
    if agent_transcript is None:
        return None, None
    try:
        with open(meta) as fh:
            named = json.load(fh).get("toolUseId")
    except (OSError, ValueError, AttributeError):
        return None, None
    return (named if isinstance(named, str) and named else None), obligation.read_first_record_prompt(agent_transcript)


def _clean_may_hold(writes: list, data: dict, project: str) -> bool:
    """Whether a /clean's producer can hold one of ``writes``: the project has run
    a /clean (a docs/clean/ directory, under which its reports and approvals
    lie), so a project without one pays nothing for the transcript's reading."""
    return os.path.isdir(os.path.join(project, "docs", "clean"))


def clean_grant(data: dict, project: str | None = None, holds: list | None = None) -> tuple:
    """(paths written, paths removed) the calling subagent may write as /clean's
    producer of them (above); empty for every other caller. Also read by
    hooks/pretool-claude-config-guard.py for a harness-home /clean."""
    try:
        from lib.agent_resolver import resolve_agent_type as resolve

        role = resolve(data)
        if not role or not data.get("agent_id"):
            return frozenset(), frozenset()
        project = project or os.path.abspath(str(_project_root()))
        call, prompt = _clean_dispatch(data)
        if call is None:
            return frozenset(), frozenset()
        written, removed = set(), set()
        for held_role, held_call, held_prompt, paths, gone in (_clean_holds(data, project) if holds is None else holds):
            if held_role == role and held_call == call and prompt is not None and held_prompt == prompt:
                written |= paths
                removed |= gone
        return frozenset(written), frozenset(removed)
    except Exception:
        return frozenset(), frozenset()


def _check_clean_writes(role, tool_name: str, targets: list, data: dict) -> set:
    """Apply /clean's approved actions (above): exit 2 on another caller's write
    of a path a /clean producer holds. Returns the targets the caller holds."""
    writes = _write_targets(tool_name, targets)
    if not writes:
        return set()
    try:
        project = os.path.abspath(str(_project_root()))
        if not _clean_may_hold(writes, data, project):
            return set()
        holds = _clean_holds(data, project)
    except Exception:  # an unread record holds nothing: the role rows decide
        return set()
    if not holds:
        return set()
    base = data.get("cwd") or project
    mine = set()
    if data.get("agent_id") and role:
        try:
            written, _removed = clean_grant(data, project, holds)
        except Exception:
            written = frozenset()
        mine = {t for t in writes if _clean_forms(t, base) & written}
    for target in writes:
        if target in mine:
            continue
        holders = sorted({h[0] for h in holds if _clean_forms(target, base) & h[3]})
        if holders:
            _emit_block(_caller_label(role, data), "Write" if tool_name == "Bash" else tool_name, target,
                        f"write target {target} is what this /clean's owner approved for its "
                        f"{' and '.join(holders)}; only that {' or '.join(holders)} writes it (D8)")
            sys.exit(2)
    return mine


def _approved_write_allowed(role: str, tool: str, target):
    """The role's denials on its write of a path /clean's owner approved for it:
    its tool lists and the shared protected prefixes, never its allow prefixes
    or its source and test denials."""
    from lib import policy_registry

    policy = policy_registry.load_policy()
    if policy is None:
        return is_allowed(role, tool, target)
    role_pol = policy_registry.get_role_policy(role)
    if role_pol.get("_unknown_role"):
        return is_allowed(role, tool, target)
    tool_check = policy_registry._check_tool_lists(role_pol, tool)
    if tool_check is not None:
        return tool_check
    if policy_registry._path_in_prefixes(target, policy.get("_shared_protected_path_prefixes") or []):
        return (False, f"write target {target} matches _shared_protected_path_prefixes")
    return (True, "ok")


def _check_targets(role: str, tool_name: str, targets: list, data: dict, own: set = frozenset(),
                   approved: set = frozenset()) -> None:
    """Iterate targets, exit 2 on first deny. For Bash, each write target is
    judged as a Write request.

    A write target that the prefix layer admits is then put through the
    actor-exact scratch gate, because a JSON prefix cannot distinguish an
    owner's scratch directory from a sibling's and cannot deny a role holding
    a bare '*' grant. A target in ``own`` is a path the caller's own dispatch
    declared: the prefix layer applies only its denials to it. A target in
    ``approved`` is one /clean's owner approved for the caller
    (_check_clean_writes): its tool lists and the shared protected prefixes
    apply to it.
    """
    check_tool = "Write" if tool_name == "Bash" else tool_name
    for target in targets:
        if check_tool in WRITE_TOOLS and target in approved and target not in own:
            allowed, reason = _approved_write_allowed(role, check_tool, target)
        elif check_tool in WRITE_TOOLS and target in own:
            allowed, reason = _declared_write_allowed(role, check_tool, target)
        else:
            allowed, reason = is_allowed(role, check_tool, target)
        if not allowed:
            _emit_block(role, check_tool, target, reason)
            if tool_name == "Bash":
                _note_bash_write_target(data, target)
            _note_inflight_token_route(role, tool_name, target)
            sys.exit(2)
        if check_tool in WRITE_TOOLS:
            allowed, reason = _check_scratch_actor_exactness(role, target, data)
            if not allowed:
                _emit_block(role, check_tool, target, reason)
                if tool_name == "Bash":
                    _note_bash_write_target(data, target)
                sys.exit(2)


# -- protected paths (P5 R2, R3; D11/D12) -------------------------------------
# No caller, /do or not, writes, deletes or renames a file the settings filter,
# the commit checks or a Stop decision reads. The harness home's are its own
# (a product repository's of the same names stay writable); a transcript's
# agent meta counts with it, since the derived permission above reads it; the
# /push Stop's push-gate token and push-analyst grant count too (review H2),
# the grant's own producer's Write of it aside. What a script or interpreter
# writes is not seen.
_HOME_PROTECTED = ("settings.machine.json", "private-literals.txt", "scripts/check-public-core.sh",
                   "scripts/install/render-settings", "hooks/git-hooks/pre-commit", ".git/config",
                   ".git/config.worktree", ".git/hooks", ".gitattributes")


def _home_git_files(home) -> list:
    """(path, label) of the git files a linked-worktree harness home keeps
    outside its tree: the shared config and hooks of its common dir, its own
    git dir's config and config.worktree, and the <home>/.git file that points
    at them. A home whose .git is a directory holds them below it
    (_HOME_PROTECTED)."""
    dot = os.path.join(home, ".git") if home else ""
    if not dot or not os.path.isfile(dot):
        return []
    held = [(dot, "the harness home's .git file")]
    import subprocess

    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")}
    try:
        out = subprocess.run(["git", "-C", home, "rev-parse", "--path-format=absolute", "--git-dir",
                              "--git-common-dir"], capture_output=True, text=True, timeout=10, env=env)
        git_dir, common = out.stdout.splitlines()[:2] if out.returncode == 0 else ("", "")
    except (OSError, subprocess.SubprocessError, ValueError):
        git_dir = common = ""
    for root, names, label in ((common, ("config", "hooks"), "git common dir's"),
                               (git_dir, ("config", "config.worktree"), "git dir's")):
        held += [(os.path.join(root, n), f"the harness home's {label} {n}") for n in names if root]
    return held


def _below(path: str, root) -> str | None:
    """``path`` relative to ``root``, either taken as written or real; None outside it."""
    for p in {os.path.normpath(path), os.path.realpath(path)}:
        for r in {os.path.normpath(root), os.path.realpath(root)}:
            rel = os.path.relpath(p, r)
            if rel != os.pardir and not rel.startswith(os.pardir + os.sep):
                return rel
    return None


_GRANT = "a push-analyst grant, which only the push-analyst dispatched for its request writes"


def _push_input(path: str, state: str) -> str | None:
    """What the /push Stop reads at ``path``, else None: a file of the push-gate
    token tree (the token's one writer, scripts/write-push-gate-token.py, writes
    it from no tool call this hook sees), or a push-analyst grant
    (<grant tree>/<repo hash>/<session>/<request>.json, merge_grant's path rule)."""
    rel = _below(path, os.path.join(state, "agentic-commit"))
    parts = rel.split(os.sep) if rel else []
    if parts[:1] == ["push"] and len(parts) > 1:
        return "a push-gate token, whose one writer is scripts/write-push-gate-token.py"
    if parts[:1] == ["push-analyst"] and len(parts) == 4 and parts[3].endswith(".json"):
        return _GRANT
    return None


def _protected(path: str, removed: bool, home, config: str, state: str, git_files=()) -> str | None:
    """What protected file absolute ``path`` is, else None; deleting or
    renaming (``removed``) a directory takes the protected files beneath it:
    the harness home's by name, the projects tree's and the /push inputs' as
    the directory holds them. ``git_files`` are _home_git_files(home)."""
    from fnmatch import fnmatchcase

    def kept(name: str) -> bool:  # a transcript or agent meta, below ``config``
        return name.endswith(".jsonl") or fnmatchcase(name, "agent-*.meta.json")

    rel, name = (_below(path, home) if home else None), os.path.basename(path)
    if rel and any(rel == p or rel.startswith(p + "/") for p in _HOME_PROTECTED):
        return f"the harness home's {rel}"
    for held_path, label in git_files:
        if _below(path, held_path):
            return label
    from lib.requirement_round import HOOK_OWNED  # R6: hook-owned, refused to every agent

    if HOOK_OWNED.search(path.replace(os.sep, "/")):
        return "an owner's answer, which only the PostToolUse AskUserQuestion hook writes"
    if _below(path, os.path.join(os.path.dirname(config), "logs")) in ("lifecycle.jsonl", "lifecycle.jsonl.lock"):
        return "the score log or its lock, which only hooks write"
    if _below(path, config) and kept(name):
        return "a session transcript or its subagent meta"
    if _below(os.path.dirname(path), state) == "." and fnmatchcase(name, "claude-do-task-*.json"):
        return "a /do task sidecar"
    push = _push_input(path, state)
    if push:
        return push
    held = [os.path.join(home, p) for p in _HOME_PROTECTED] + [p for p, _ in git_files] if home else []
    if removed and (any(_below(p, path) for p in held + [config])
                    or (_below(path, config) and any(kept(n) for _, _, names in os.walk(path) for n in names))):
        return "a directory holding the harness home's protected files or the session transcripts"
    inputs = os.path.join(state, "agentic-commit")  # walked from the deeper of it and the removed directory
    walked = path if _below(path, inputs) else inputs if removed and _below(inputs, path) else None
    if removed and walked and any(_push_input(os.path.join(d, n), state) for d, _, names in os.walk(walked)
                                  for n in names):
        return "a directory holding a push-gate token or a push-analyst grant"
    return None


def _grant_producer(target: str, state: str, data: dict) -> bool:
    """Whether the caller is the push-analyst grant's producer: a subagent
    whose own dispatch (the declaring-dispatch reader's: its record found back
    from the end of the session transcript by the call its meta names, as
    _own_from_tail finds it) is a dispatch of the role the grant's folder names
    (merge_grant's path rule), by a subagent of that type, whose command
    template binds the grant's repository hash, session and request id."""
    try:
        from lib import command_span, declared_paths, dispatch_template, obligation

        transcript = _session_transcript(data)
        agent_transcript, meta = declared_paths._agent_files(transcript, data.get("agent_id"))
        if agent_transcript is None:
            return False
        prompt = obligation.read_first_record_prompt(agent_transcript)
        with open(meta) as fh:
            named = json.load(fh).get("toolUseId")
        if prompt is None or not isinstance(named, str) or not command_span._PLAIN_ID.match(named):
            return False
        record = _Record(transcript)
        try:
            call = record.find_call(named, prompt)
        finally:
            record.close()
        parsed = obligation.parse_obligation(prompt)
        own = parsed.obligation if isinstance(parsed, obligation.ParsedObligation) else {}
        folder, *values = _below(target, os.path.join(state, "agentic-commit")).split(os.sep)
        if call is None or not folder == own.get("role") == call.input.get("subagent_type"):
            return False
        found = dispatch_template._template(own.get("pipeline"), folder, prompt, None)
        bound = set(dispatch_template._bindings(found[2]).values()) if found else set()
        return {values[0], values[1], values[2][:-len(".json")]} <= bound
    except Exception:  # an unreadable record names no producer: the write stays refused
        return False


def _check_protected(role, tool_name: str, tool_input: dict, targets: list, data: dict) -> None:
    from lib import claude_home
    from lib.harness_state_dir import harness_state_dir

    if tool_name == "Bash":
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        found = list(extract_bash_touched_paths(command)) if isinstance(command, str) else []
    else:
        found = [(t, False) for t in _write_targets(tool_name, targets)]
    if not found:
        return
    base = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    roots = (claude_home.resolve(), os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"),
                                                 "projects"), harness_state_dir())
    git_files = _home_git_files(roots[0])
    for target, removed in dict.fromkeys(found):  # a variable the hook's environment holds is the shell's
        word = os.path.expandvars(re.sub(r"\$\{(\w+):-([^}]*)\}", lambda m: os.environ.get(m[1]) or m[2], target))
        path = os.path.join(base, os.path.expanduser(word))
        what = not any(c in word for c in "$`\x00") and _protected(path, removed, *roots, git_files)
        if what == _GRANT and not removed and data.get("agent_id") and _grant_producer(path, roots[2], data):
            continue  # the push-analyst's own Write of its grant (agents/push-analyst.md Phase 7)
        if what:
            _emit_block(_caller_label(role, data), "Write" if tool_name == "Bash" else tool_name, target,
                        f"{target} is {what}: no agent writes, deletes or renames it (D11/D12)")
            _note_inflight_token_route(role, tool_name, target)
            sys.exit(2)


# -- the token Write's refusal names its route ---------------------------------
# A changelog-analyst's Write of the push-gate token, at /tmp/agentic-commit/
# push/<repo hash>/<session digest>/<branch>.json, stays refused (D18): by the
# protected stage above where the state dir is /tmp, by the analyst's role row
# elsewhere. Its stderr names the route that reaches the push of the commit it
# names (D25): /push, whose Step 5 has the token's one writer write the token
# for that commit (scripts/execute-push.py, on the CLI's record of this refusal).
_INFLIGHT_TOKEN_RE = re.compile(r"/agentic-commit/push/[0-9a-f]{16}/[0-9a-f]{16}/[^/]+\.json\Z")
_INFLIGHT_TOKEN_ROUTE = (
    "tool-policy.v1 note: this Write stays refused; no agent writes a push-gate token. The "
    "commit it names reaches its push through /push (the harness home's commands/push.md, Steps 0-5): Step 3 "
    "dispatches the push-analyst, whose own dispatch binds its grant, and Step 5's scripts/execute-push.py, "
    "once that grant passes, has the token's one writer (scripts/write-push-gate-token.py) write the token for "
    "that commit while it is HEAD and no token names an ancestor of HEAD. Report this refusal; do not write "
    "the token any other way.")


def _note_inflight_token_route(role, tool_name: str, target) -> None:
    """The route of a changelog-analyst's refused Write of a push-gate token path."""
    if role == "changelog-analyst" and tool_name == "Write" and _INFLIGHT_TOKEN_RE.search(
            os.path.normpath(str(target))):
        sys.stderr.write(_INFLIGHT_TOKEN_ROUTE + "\n")


# -- scheduled prompts (P5 R5) ------------------------------------------------
# P1's capture (COV-7, CLI 2.1.303) measured a fired CronCreate prompt's record
# (isMeta, turnOrigin "scheduled"): stop_contract.is_human_prompt excludes it.
# A ScheduleWakeup prompt's record is unmeasured, so one typing a harness
# command outside CONTROL is refused, the overnight wake's own text aside.
def _check_scheduled_prompt(role, tool_name: str, tool_input: dict, data: dict) -> None:
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if tool_name != "ScheduleWakeup" or not isinstance(prompt, str):
        return
    from lib import stop_contract

    found = stop_contract.slash_command(prompt)
    if not found or found[0] not in stop_contract.harness_commands() or found[0] in stop_contract.CONTROL_COMMANDS:
        return
    try:
        from lib import overnight

        wake = overnight.WAKE_PROMPT
    except Exception:  # no wake text on this tree: nothing to exempt
        wake = None
    if prompt.strip() != wake:
        _emit_block(_caller_label(role, data), tool_name, f"/{found[0]}",
                    f"a {tool_name} prompt that types /{found[0]}: only the human types a harness command")
        sys.exit(2)


def main() -> None:
    # Bootstrap the deny-logic FIRST, fail-closed (exit 2) on import error.
    _bootstrap_security()
    data = _read_payload()
    if not data:
        sys.exit(0)
    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str):
        sys.exit(0)
    tool_input = data.get("tool_input") or {}
    role = resolve_agent_type(data)
    targets = _extract_targets(tool_name, tool_input)
    _check_protected(role, tool_name, tool_input, targets, data)
    _check_scheduled_prompt(role, tool_name, tool_input, data)
    own = _check_declared_writes(role, tool_name, targets, data)
    approved = _check_clean_writes(role, tool_name, targets, data)
    _check_grant_writes(role, tool_name, targets, data)
    from lib import policy_registry

    if not role or policy_registry.get_role_policy(role).get("_unknown_role"):
        # Unresolved is NORMAL (agent_resolver: never hard-block on None);
        # the main agent and an unlisted (built-in or plugin) role have no role
        # rows: the checks above are all that applies to them.
        sys.exit(0)
    _check_targets(role, tool_name, targets, data, own, approved)
    sys.exit(0)


def _end(stop: SystemExit) -> None:
    """End the process with the status ``stop`` carries and the output already
    written, as the interpreter ends it on an uncaught SystemExit, without its
    teardown: no atexit handler, thread or buffered output is left to it here,
    and unloading the dispatch-record readers' modules was a few ms of every
    call. Only when the interpreter runs this file itself: a caller that runs
    it as __main__ in its own process (runpy) still gets the SystemExit."""
    code = stop.code
    if code is None:
        status = 0
    elif isinstance(code, int):
        status = code
    else:
        sys.stderr.write(f"{code}\n")
        status = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)


if __name__ == "__main__":
    try:
        try:
            main()
        except Exception as e:  # pragma: no cover
            sys.stderr.write(f"pretool-tool-policy: unexpected ({e})\n")
            sys.exit(0)
    except SystemExit as stop:
        if sys._getframe().f_back is None:  # the interpreter runs this file itself: nothing runs after it
            _end(stop)
        raise
