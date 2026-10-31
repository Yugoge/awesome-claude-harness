#!/usr/bin/env python3
"""PreToolUse:* hook — the write permission dispatch records derive, then
tool-policy.v1.json for all subagents.

Single hook that consumes the harness ``policies/tool-policy.v1.json`` (resolved
via the shared hooks/lib/claude_home resolver) through
lib.policy_registry.is_allowed() and lib.agent_resolver.resolve_agent_type().

Derived write permission (P1b E3, TC-20 as corrected; D8, D21, D24), run first,
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
    general-purpose's '*/docs/dev/*') says. No prefix table names an artifact.
  - An undeclared path keeps the role policy rows below.
  - What a dispatch can declare has the shapes of the paths the current
    command files' templates write ("path" in their JSON, any bracketed text
    a placeholder) and the producer question's: a target with no part such a
    path can end on is undeclared without reading the transcript or a
    subagent's files, so its cost does not grow with the session (P1b review
    item 2). A path a
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
    transcript's bytes (P1b review 1 latency). Its template is the one of its
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

Behavior:
  - Main agent (no agent_id, no subagent_type) -> exit 0 after the derived
    permission (the orchestrator gate handles the rest of the main agent).
  - Subagent role unresolvable -> exit 0 (defer to the backstop shim). An
    unresolved role is a NORMAL state (a subagent may write before any sentinel-
    creating tool runs; agent_resolver LOW-10: callers MUST NOT hard-block on
    None). Role-specific deny is enforced once the role resolves.
  - Resolved role + denied tool/path -> exit 2 with structured stderr
    JSON: {"role", "tool", "target", "deny_reason"}.
  - Deny-logic import/bootstrap failure -> exit 2 (FAIL CLOSED, WS1): the
    security imports live inside a fail-closed bootstrap guard, NOT inside the
    blanket `except Exception: sys.exit(0)` (which would silently fail open).

Bash policy bypass fix (T2.1):
  - For Bash tool, parse the command with lib.bash_write_targets to
    extract every shell write target (heredoc-stripped). Each extracted
    path is authorized as if it were a Write target. The bash command
    itself is also authorized for tool-list membership (target=None).
  - This closes the heredoc/redirect bypass where a subagent could
    write to a protected path via 'cat > FILE << EOF' or similar.

Scratch namespace actor-exactness (LANE-B r02, parent RULING_2 G0 admission):
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

# WS1 CRITICAL: the deny-logic imports are loaded inside a FAIL-CLOSED bootstrap
# guard, NOT at module top (where an ImportError would be a dirty uncaught
# exit 1) and NOT inside the blanket `except Exception: sys.exit(0)` in __main__
# (which would silently fail OPEN). A missing/broken deny-logic module on a
# fresh clone must BLOCK (exit 2), never allow.
WRITE_TOOLS: set
resolve_agent_type = None  # type: ignore[assignment]
extract_bash_write_paths = None  # type: ignore[assignment]
is_allowed = None  # type: ignore[assignment]


def _bootstrap_security() -> None:
    """Import the deny-logic modules; FAIL CLOSED (exit 2) on any failure.

    This MUST be called from main() BEFORE any authorization decision and MUST
    NOT be wrapped by the blanket fail-open `except` in __main__.
    """
    global WRITE_TOOLS, resolve_agent_type, extract_bash_write_paths, is_allowed
    try:
        from lib.agent_resolver import resolve_agent_type as _rat
        from lib.bash_write_targets import extract_bash_write_paths as _ebwp
        from lib.policy_registry import WRITE_TOOLS as _wt, is_allowed as _ia
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
    is_allowed = _ia


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def _extract_targets(tool_name: str, tool_input: dict) -> list:
    """Return list of policy targets for the (tool, input) pair.

    For Bash: returns [None] followed by every extracted write target.
    The leading None preserves tool-list authorization (allowed_tools /
    denied_tools) even when the bash command has no write targets
    (e.g. 'echo hello'). Each subsequent extracted path is then
    authorized as a Write target — closing the heredoc/redirect bypass
    where a subagent could write to a protected path via 'cat > FILE
    << EOF' or other shell write idioms.
    """
    if not isinstance(tool_input, dict):
        return [None]
    if tool_name in WRITE_TOOLS:
        return [tool_input.get("file_path") or tool_input.get("notebook_path")]
    if tool_name == "Read":
        return [tool_input.get("file_path")]
    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        return [None] + extract_bash_write_paths(command)
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
    the role that holds each.
    """
    from lib.policy_registry import get_role_policy

    allowed = get_role_policy(role).get("allowed_write_path_prefixes", []) or []
    out = []
    for entry in allowed:
        if not isinstance(entry, str) or entry in _RAW_TEMP_GRANTS:
            continue
        parts = entry.strip("*").split("/")
        if "tmp" in parts:
            out.append(entry)
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
    """Explain an INFERRED Bash write-target refusal (lane e, self-explaining
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
    if tool_name == "Bash":
        found = targets[1:]
    elif tool_name in WRITE_TOOLS:
        found = targets[:1]
    else:
        return []
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
    for span openers was most of what a declared-path write cost (P1b review
    item 2).
    A file with no end to read back from (not a regular file) is read whole,
    as before."""

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
                  + "; only that dispatch writes it")
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
    if policy_registry._path_in_prefixes(target, role_pol.get("denied_write_path_prefixes", [])):
        return (False, f"write target {target} matches denied_write_path_prefixes")
    return (True, "ok")


def _check_targets(role: str, tool_name: str, targets: list, data: dict, own: set = frozenset()) -> None:
    """Iterate targets, exit 2 on first deny. For Bash, treat each
    extracted write target (idx > 0) as a Write authorization request.

    A write target that the prefix layer admits is then put through the
    actor-exact scratch gate, because a JSON prefix cannot distinguish an
    owner's scratch directory from a sibling's and cannot deny a role holding
    a bare '*' grant. A target in ``own`` is a path the caller's own dispatch
    declared: the prefix layer applies only its denials to it.
    """
    for idx, target in enumerate(targets):
        check_tool = tool_name
        if tool_name == "Bash" and idx > 0:
            check_tool = "Write"
        if check_tool in WRITE_TOOLS and target in own:
            allowed, reason = _declared_write_allowed(role, check_tool, target)
        else:
            allowed, reason = is_allowed(role, check_tool, target)
        if not allowed:
            _emit_block(role, check_tool, target, reason)
            if tool_name == "Bash" and idx > 0:
                _note_bash_write_target(data, target)
            sys.exit(2)
        if check_tool in WRITE_TOOLS:
            allowed, reason = _check_scratch_actor_exactness(role, target, data)
            if not allowed:
                _emit_block(role, check_tool, target, reason)
                if tool_name == "Bash" and idx > 0:
                    _note_bash_write_target(data, target)
                sys.exit(2)


def main() -> None:
    # WS1: bootstrap the deny-logic FIRST, fail-closed (exit 2) on import error.
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
    own = _check_declared_writes(role, tool_name, targets, data)
    if not role:
        # An unresolved role is a NORMAL state, not an error: Claude Code may
        # dispatch a subagent before any sentinel-creating tool runs, so the
        # agent-index entry can legitimately be missing during a first write.
        # Per the agent_resolver LOW-10 contract, callers MUST NOT hard-block on
        # None — defer to the backstop shim (exit 0). (Reverted: the prior
        # unresolved-role fail-closed broke every subagent lacking a registry.)
        # The main agent has no role rows either; the derived permission above
        # is all that applies to it.
        sys.exit(0)
    _check_targets(role, tool_name, targets, data, own)
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
