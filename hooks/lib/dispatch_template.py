#!/usr/bin/env python3
"""The obligation a dispatch's current command template declares (P1b row 8, E3).

A dispatch made from a base template before a merge carries no obligation block
(D15: a running command keeps the text it loaded, while every hook runs the
current files). What applies to such a dispatch is what the template it was
dispatched from declares in the current command files: the command whose span
holds the dispatch record (stop_contract's span rule), the one dispatch template
of that command it was made from (its subagent_type, the role and profile its
own block names, the template lines its prompt carries), each placeholder bound
to the dispatch's own values. A placeholder takes its value from the dispatch
prompt's line that the template line holding it matches; a placeholder no
prompt line binds stays unbound, and an entry that keeps one outside its
identity is left out. G2 reads the /spec split rule this way for a spec
subagent dispatched from the base's /spec template; the codex gate reads
whether that template asks for codex.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:  # imported as hooks.lib.dispatch_template (tests) or lib.dispatch_template (hooks)
    from . import stop_contract
except ImportError:  # hooks/lib placed directly on sys.path
    import stop_contract  # type: ignore[no-redef]

DEFAULT_SUBAGENT_TYPE = "general-purpose"  # the CLI's type for an Agent call that names none
_FENCE_RE = re.compile(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", re.M | re.S)
_BLOCK_RE = re.compile(r'<obligation v="1">\s*(.*?)\s*</obligation>', re.S)
_SUBAGENT_RE = re.compile(r'subagent_type\W{1,4}([A-Za-z0-9_-]+)')
_PLACEHOLDER_RE = re.compile(r"<([A-Za-z][A-Za-z0-9_-]*)>")
# What a template's obligation declares, as G1 reads it: the role="r" and
# profile="p"/"q" of an "embed ... here with" sentence or the "role": "r" of a
# worked example; a placeholder role (role="<specialist.type>") names none.
_ROLE_RE = re.compile(r'\brole="([a-z][a-z0-9-]*)"|"role"\s*:\s*"([a-z][a-z0-9-]*)"')
_PROFILE_RE = re.compile(r'\bprofile=((?:"[^"<]*"/?)+)|"profile"\s*:\s*"([^"<]*)"')
_QUOTED_RE = re.compile(r'"([^"]*)"')


def dispatch_of(agent_transcript: str | Path) -> tuple[str, str, str] | None:
    """(command, subagent_type, prompt) of the dispatch that started the agent
    whose transcript this is: its meta file names the Agent tool_use, the parent
    session transcript holds that call and the human-typed command opening the
    span it lies in. None when any of these cannot be read."""
    agent = Path(agent_transcript)
    try:
        meta = json.loads(agent.with_name(agent.stem + ".meta.json").read_text(encoding="utf-8"))
        tool_use_id = meta["toolUseId"]
        session_dir = agent.parent.parent
        parent = session_dir.parent / f"{session_dir.name}.jsonl"
        commands, command = stop_contract.harness_commands(), None
        with parent.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                opener = stop_contract.span_opener(record, commands)
                if opener:
                    command = opener[0]
                message = record.get("message") if isinstance(record, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                for block in content if isinstance(content, list) else ():
                    if (isinstance(block, dict) and block.get("type") == "tool_use"
                            and block.get("id") == tool_use_id and isinstance(block.get("input"), dict)):
                        if command is None:
                            return None
                        tool_input = block["input"]
                        return (command, tool_input.get("subagent_type") or DEFAULT_SUBAGENT_TYPE,
                                str(tool_input.get("prompt") or ""))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return None


def _fences(text: str):
    """Each fence of a command file as (body, subagent_type, roles, profiles,
    worked example): the roles and profiles its worked example or its "embed
    ... here with role=..." sentence declares; its subagent_type the one it
    names before its obligation, else the one role it declares. G1 refuses a
    dispatch whose role is not its subagent_type, so a fence that names no type
    (dev.md's "Use Task tool with:", close.md's QA, whose type its prose
    names) dispatches that role."""
    for fence in _FENCE_RE.finditer(text):
        body = fence.group(1)
        block = _BLOCK_RE.search(body)
        named = _SUBAGENT_RE.search(body[:block.start()] if block else body)
        roles = {a or b for a, b in _ROLE_RE.findall(body)}
        profiles = {p for alternatives, one in _PROFILE_RE.findall(body)
                    for p in (_QUOTED_RE.findall(alternatives) if alternatives else [one])}
        if named:
            subagent_type = named.group(1)
        elif len(roles) == 1:
            subagent_type = next(iter(roles))
        else:
            subagent_type = DEFAULT_SUBAGENT_TYPE
        yield body, subagent_type, roles, profiles, block.group(1) if block else None


# A hook that reads every dispatch of a long session asks for the same command
# file's fences once per dispatch: they are parsed once per file text.
_PARSED: dict[str, tuple] = {}


def _parsed_fences(text: str) -> tuple:
    """_fences(text), parsed once per text in a process."""
    found = _PARSED.get(text)
    if found is None:
        found = _PARSED[text] = tuple(_fences(text))
    return found


def _fill(line: str, fixed: list[str], i: int = 0, pos: int | None = None) -> list[str] | None:
    """The values a template line binds in a prompt line: the line read as
    ^fixed[0](.+?)fixed[1](.+?)...fixed[-1]$, each value as re.match finds it
    (the shortest that lets the rest match, at least one character); None when
    the line does not read so. Matched by hand, not by a compiled pattern: a
    tool-policy run reads every dispatch of the session against its template,
    and compiling each template line's pattern was most of what that cost. A
    prompt line holds no newline (str.splitlines), so every character counts."""
    if pos is None:
        if not line.startswith(fixed[0]):
            return None
        pos = len(fixed[0])
    following = fixed[i + 1]
    if i + 2 == len(fixed):  # the last value runs to the text after it, which ends the line
        end = len(line) - len(following)
        return [line[pos:end]] if end > pos and line.endswith(following) else None
    at = line.find(following, pos + 1)
    while at >= 0:
        rest = _fill(line, fixed, i + 1, at + len(following))
        if rest is not None:
            return [line[pos:at]] + rest
        at = line.find(following, at + 1)
    return None


def _matched_lines(template: str, prompt: str) -> list[list[tuple[str, str]]]:
    """The template lines some prompt line matches, each as the (placeholder,
    value) pairs it binds. A line with no fixed word matches nothing: it would
    tie its placeholder to any line."""
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    found = []
    for raw in template.splitlines():
        text = raw.strip()
        if not re.search(r"\w", _PLACEHOLDER_RE.sub("", text)):
            continue
        names, fixed, pos = [], [], 0
        for m in _PLACEHOLDER_RE.finditer(text):
            fixed.append(text[pos:m.start()])
            names.append(m.group(1))
            pos = m.end()
        fixed.append(text[pos:])
        # Early exits, each a condition every line the template line matches
        # meets: it equals a line that holds no placeholder, and it starts with
        # the text before the first placeholder and ends with the text after
        # the last.
        if not names:
            if text in lines:
                found.append([])
            continue
        if not any(line.startswith(fixed[0]) and line.endswith(fixed[-1]) for line in lines):
            continue
        for line in lines:
            values = _fill(line, fixed)
            if values is not None:
                found.append([(name, value.strip()) for name, value in zip(names, values)])
                break
    return found


def _bindings(matched: list[list[tuple[str, str]]]) -> dict[str, str]:
    values: dict[str, str] = {}
    clashes: set[str] = set()
    for pairs in matched:
        for name, value in pairs:
            if values.setdefault(name, value) != value:
                clashes.add(name)
    return {k: v for k, v in values.items() if k not in clashes}


def _template(command: str, subagent_type: str, prompt: str, commands_dir) -> tuple | None:
    """(body, worked example, matched lines) of the one fence of
    commands/<command>.md this dispatch was made from: among the fences of its
    subagent_type that declare the role and the profile its own obligation
    block names (when it carries one), the one whose lines its prompt carries
    most, the first on a tie. A dispatch with no block of its own must carry
    one of the fence's lines. None when no fence qualifies."""
    try:
        text = (Path(commands_dir or stop_contract.COMMANDS_DIR) / f"{command}.md").read_text(encoding="utf-8")
    except OSError:
        return None
    own_block = _BLOCK_RE.search(prompt)
    try:
        own = json.loads(own_block.group(1)) if own_block else None
    except ValueError:
        own = None
    own = own if isinstance(own, dict) else {}
    role, profile = own.get("role"), own.get("profile")
    best = None
    for body, kind, roles, profiles, example in _parsed_fences(text):
        if kind != subagent_type or (role and role not in roles) or (profile and profile not in profiles):
            continue
        matched = _matched_lines(body, prompt)
        if best is None or len(matched) > len(best[2]):
            best = (body, example, matched)
    if best is None or not (best[2] or own):
        return None
    return best


def _bind(value, values: dict[str, str]):
    if isinstance(value, str):
        return _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [_bind(v, values) for v in value]
    if isinstance(value, dict):
        return {k: _bind(v, values) for k, v in value.items()}
    return value


def _unbound(value) -> bool:
    if isinstance(value, str):
        return bool(_PLACEHOLDER_RE.search(value))
    if isinstance(value, list):
        return any(_unbound(v) for v in value)
    if isinstance(value, dict):
        return any(_unbound(v) for v in value.values())
    return False


def _kept(entry: dict) -> dict | None:
    """An artifact entry with the identity values its dispatch leaves unbound
    dropped (the path is what names the artifact); None when a placeholder
    outside its identity stays unbound."""
    if isinstance(entry.get("identity"), dict):
        entry = dict(entry, identity={k: v for k, v in entry["identity"].items() if not _unbound(v)})
    if _unbound(entry.get("identity_anchor")):
        entry = {k: v for k, v in entry.items() if k != "identity_anchor"}
    return None if _unbound(entry) else entry


def template_of(command: str, subagent_type: str, prompt: str,
                commands_dir: str | Path | None = None) -> str | None:
    """The text of the dispatch template in the current commands/<command>.md
    that a dispatch of `subagent_type` with this prompt was made from
    (_template); None when none was."""
    found = _template(command, subagent_type, prompt, commands_dir)
    return found[0] if found else None


def template_obligation(command: str, subagent_type: str, prompt: str,
                        commands_dir: str | Path | None = None) -> dict | None:
    """The obligation the worked example of the template this dispatch was
    made from (_template) declares in the current commands/<command>.md, bound
    to the prompt's values, each artifact entry kept as _kept keeps it. None
    when that template has no worked example or keeps no entry."""
    found = _template(command, subagent_type, prompt, commands_dir)
    if found is None or found[1] is None:
        return None
    try:
        declared = json.loads(found[1])
    except ValueError:
        return None
    if not isinstance(declared, dict):
        return None
    bound = _bind(declared, _bindings(found[2]))
    artifacts = [kept for a in bound.get("artifacts") or [] if isinstance(a, dict)
                 for kept in (_kept(a),) if kept is not None]
    return dict(bound, artifacts=artifacts) if artifacts else None
