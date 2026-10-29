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
    dispatch. What a dispatch declares is read from its own record in the
    session transcript: the artifacts[].path of its obligation, the producer
    question that obligation names when schemas/producer-question.v1.json lets
    its role write one, and what the template it was dispatched from declares
    in the current command files (lib/dispatch_template; the template of its
    obligation's pipeline, role and profile, or, for a dispatch that carries
    none, of its subagent_type in the command whose span holds it), each
    placeholder bound to that dispatch's own values. A declared directory
    covers what lies beneath it.
  - The declaring dispatch's write skips the role's allow prefixes; its deny
    prefixes, tool lists and the scratch rule below still apply.
  - Any other caller's write of a declared path -> exit 2 naming the path and
    the declaring obligation's role, whatever an allow prefix (dev's '*',
    general-purpose's '*/docs/dev/*') says. No prefix table names an artifact.
  - An undeclared path keeps the role policy rows below.

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
avoid bricking the tool pipeline on a hook bug.
"""

from __future__ import annotations

import json
import os
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

_HARNESS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_SUBAGENT_TYPE = "general-purpose"  # the CLI's type for an Agent call that names none
_AGENT_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


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


def _parts(path: str) -> tuple:
    return tuple(p for p in os.path.normpath(path).split(os.sep) if p and p != ".")


def _question_roles() -> frozenset:
    """Roles schemas/producer-question.v1.json lets write a producer question."""
    try:
        with open(os.path.join(_HARNESS_ROOT, "schemas", "producer-question.v1.json")) as fh:
            values = json.load(fh)["properties"]["role"]["enum"]
        return frozenset(v for v in values if isinstance(v, str))
    except (OSError, ValueError, KeyError, TypeError):
        return frozenset()


def _declared_paths(obligation_doc: dict) -> list:
    return [a["path"] for a in obligation_doc.get("artifacts") or []
            if isinstance(a, dict) and isinstance(a.get("path"), str) and a["path"]]


def _agent_files(transcript, agent_id: str):
    """(transcript, meta) paths the CLI keeps for one subagent of the session."""
    if not isinstance(agent_id, str) or not 0 < len(agent_id) <= 128 or not set(agent_id) <= _AGENT_ID_CHARS:
        return None, None
    sub = transcript.parent / transcript.stem / "subagents"
    return sub / f"agent-{agent_id}.jsonl", sub / f"agent-{agent_id}.meta.json"


def _dispatch_calls(record_bytes: bytes) -> list:
    """The session's Agent/Task calls, read as command_span's Span.calls reads
    them (its line reader, the main session's own records only), without the
    search for each call's result that this rule does not use."""
    from lib import command_span

    calls = []
    for number, _end, raw in command_span._Lines(record_bytes).having((b'"Agent"', b'"Task"')):
        for block in command_span._blocks(command_span._decode(raw)):
            if (block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task")
                    and isinstance(block.get("input"), dict)):
                calls.append(command_span.Call(id=block.get("id") or "", name=block["name"], input=block["input"],
                                               line=number, result_line=0, ok=False))
    return calls


def _span_commands(record_bytes: bytes, until: int) -> list:
    """(line, command) of each human-typed harness command of the session
    before line ``until`` (the last dispatch: no later command opens a
    dispatch's span), read as command_span.active_span reads them (its line
    reader, the stop_contract span rule); a dispatch's span is the last one
    before it."""
    from lib import command_span, stop_contract

    commands, openers = stop_contract.harness_commands(), []
    for number, _end, raw in command_span._Lines(record_bytes).having(command_span._USER_RECORD,
                                                              unless=command_span._RESULT_BLOCK):
        if number >= until:
            break
        record = command_span._decode(raw)
        opener = stop_contract.span_opener(record, commands) if record else None
        if opener:
            openers.append((number, opener[0]))
    return openers


def _declarations(record_bytes: bytes, calls: list) -> list:
    """(path parts, role, task_id, dispatch id) for every path a dispatch of
    the session declares, in record order."""
    from lib import dispatch_template, obligation

    question_roles = None
    openers = None
    out = []
    for call in calls:
        prompt = call.input.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            continue
        subagent_type = call.input.get("subagent_type") or _DEFAULT_SUBAGENT_TYPE
        parsed = obligation.parse_obligation(prompt)
        own = parsed.obligation if isinstance(parsed, obligation.ParsedObligation) else None
        paths, role, task_id = [], subagent_type, None
        if own is not None:
            role, task_id = own.get("role"), own.get("task_id")
            paths += _declared_paths(own)
            template = dispatch_template.template_obligation(own.get("pipeline"), subagent_type, prompt)
            # Only the template this dispatch was made from: same role and profile.
            if template and all(template.get(k) == own.get(k) for k in ("role", "profile")):
                paths += _declared_paths(template)
            if question_roles is None:
                question_roles = _question_roles()
            if role in question_roles and isinstance(task_id, str) and task_id:
                # The question G2 takes in place of the declared artifacts
                # (subagentstop-artifact-contract-enforce.py _producer_question).
                paths.append(f"docs/dev/producer-question-{task_id}-{role}.json")
        else:
            if openers is None:
                openers = _span_commands(record_bytes, calls[-1].line)
            command = next((name for number, name in reversed(openers) if number < call.line), None)
            template = dispatch_template.template_obligation(command, subagent_type, prompt) if command else None
            if template:
                role, task_id = template.get("role") or role, template.get("task_id")
                paths += _declared_paths(template)
        for path in dict.fromkeys(paths):
            parts = _parts(path)
            if parts and ".." not in parts and not path.startswith("/"):
                out.append((parts, role, task_id, call.id))
    return out


def _caller_dispatches(data: dict, transcript, calls: list) -> set:
    """The dispatch record(s) the calling subagent was started from: the one
    its CLI meta names when that call's prompt is the agent's own first
    record, else the calls carrying that prompt. The main agent has none."""
    from lib import obligation

    agent_id = data.get("agent_id")
    if not agent_id:
        return set()
    agent_transcript, meta = _agent_files(transcript, agent_id)
    if agent_transcript is None:
        return set()
    prompt = obligation.read_first_record_prompt(agent_transcript)
    if prompt is None:
        return set()
    try:
        with open(meta) as fh:
            named = json.load(fh).get("toolUseId")
    except (OSError, ValueError, AttributeError):
        named = None
    if named:
        return {c.id for c in calls if c.id == named and c.input.get("prompt") == prompt}
    return {c.id for c in calls if c.input.get("prompt") == prompt}


def _covers(declared: tuple, target: tuple) -> bool:
    n = len(declared)
    return any(target[i:i + n] == declared for i in range(len(target) - n + 1))


def _target_forms(target: str, data: dict) -> list:
    base = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    path = os.path.expanduser(target)
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    forms = {os.path.normpath(path)}
    try:
        forms.add(os.path.realpath(path))
    except OSError:
        pass
    return [_parts(f) for f in forms]


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
        from lib import command_span, dispatch_template, obligation, stop_contract  # noqa: F401
    except Exception as e:
        sys.stderr.write(
            "BLOCKED by tool-policy.v1: derived write permission bootstrap FAILED — "
            f"the dispatch-record readers could not be imported ({e}). Failing CLOSED "
            "(exit 2) rather than allowing; repair the harness install.\n"
        )
        sys.exit(2)

    try:
        record_bytes = command_span._read(transcript)
    except (OSError, TypeError, ValueError):
        return set()
    calls = _dispatch_calls(record_bytes)
    if not calls:
        return set()
    declarations = _declarations(record_bytes, calls)
    if not declarations:
        return set()
    mine = None
    own = set()
    for target in writes:
        forms = _target_forms(target, data)
        covering = [d for d in declarations if any(_covers(d[0], f) for f in forms)]
        if not covering:
            continue
        if mine is None:
            mine = _caller_dispatches(data, transcript, calls)
        if any(d[3] in mine for d in covering):
            own.add(target)
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


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"pretool-tool-policy: unexpected ({e})\n")
        sys.exit(0)
