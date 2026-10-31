#!/usr/bin/env python3
"""What the dispatches of a session declare, as tool-policy's derived write permission reads it (P1b E3).

hooks/pretool-tool-policy.py decides who may write a path a dispatch of the
session declares; these are the readers it decides from, kept here so that
the hook's own source, compiled on every tool call, holds the rule and the
transcript reader (_Record) only:
  - the shapes of every path the current command files' templates can
    declare (_declarable_shapes), and of each command's templates of a
    subagent type (_template_shapes) or of any (_template_bounds);
  - the session's started dispatches, read from the files the CLI keeps for
    each subagent it started (_started_dispatches), and the calling
    subagent's own (_caller_dispatches, _agent_files);
  - what a set of dispatches declares (_declarations), a template bound only
    where its paths could cover a target, an obligation validated and bound
    only where it or its templates could (_obligation_may_declare).
One decision (``with decision():``) reads each command file once; nothing is
kept from one hook process to the next.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# The hook imports this as lib.declared_paths, so these are the lib.* modules
# its own code and the tests patch.
from . import command_span, dispatch_template, obligation, stop_contract

_HARNESS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_SUBAGENT_TYPE = "general-purpose"  # the CLI's type for an Agent call that names none
_AGENT_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


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


# The question G2 takes in place of the declared artifacts
# (subagentstop-artifact-contract-enforce.py _producer_question).
_QUESTION_PATH = "docs/dev/producer-question-{task_id}-{role}.json"
# A path a command file's template declares, as its JSON writes it, and a
# placeholder in one: <task_id>, <TASK_ID or "bulk">, {pipeline.x}. Any text
# in brackets counts as one, so no template path is read narrower than the
# dispatch that fills it in may write it.
_TEMPLATE_PATH_RE = re.compile(r'"path"\s*:\s*"((?:[^"\\\n]|\\.)*)"')
_SHAPE_PLACEHOLDER_RE = re.compile(r"<[^<>]*>|\{[^{}]*\}")
_ANY = None  # a shape whose declared path may end in any name


def _shape(path: str):
    """What the last part of a declared path made from template path ``path``
    is: ("parts", the parts) for a path without placeholders, ("last", name)
    or ("ends", text) after the last placeholder, or _ANY. A placeholder's
    value may hold "/" and "..", and the declared path is normalised, so only
    the text after the last placeholder is certain, and only while no ".."
    in it can take a part back."""
    pieces = _SHAPE_PLACEHOLDER_RE.split(path)
    if len(pieces) == 1:
        return ("parts", _parts(path))
    tail = pieces[-1]
    head, slash, rest = tail.partition("/")
    if slash:
        names = rest.split("/")
        if ".." in names:
            return _ANY
        names = [n for n in names if n not in ("", ".")]
        if names:
            return ("last", names[-1])
    return _ANY if head in ("", ".", "..") else ("ends", head)


_DECISION = None  # within one decision: what it read of the command files


class decision:
    """``with decision():`` -- one decision of the hook: within it each
    command file is read once (_command_text), and the bounds of every
    template once (_template_bounds)."""

    def __enter__(self):
        global _DECISION
        self._outer = _DECISION
        if _DECISION is None:
            _DECISION = {}
        return self

    def __exit__(self, *exc):
        global _DECISION
        _DECISION = self._outer
        return False


def _read_text(path) -> str:
    """Path.read_text(encoding="utf-8"): the same text, or an error of the
    same class, from one raw read: a strict UTF-8 decode, then the line ends
    the text reader turns into "\\n" ("\\r\\n", then a lone "\\r")."""
    text = path.read_bytes().decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n") if "\r" in text else text


def _command_text(path) -> str:
    """Command file ``path`` as Path.read_text reads it. Within one decision
    each file is read once and every reader of it takes that text, or meets
    the error its read raised: the shapes, the template bounds and each
    template's fences are read from one text per file per decision."""
    if _DECISION is None:
        return path.read_text(encoding="utf-8")
    texts = _DECISION.setdefault("texts", {})
    key = str(path)
    if key not in texts:
        try:
            texts[key] = (_read_text(path), None)
        except Exception as error:
            texts[key] = (None, error)
    text, error = texts[key]
    if error is not None:
        raise error
    return text


def _declarable_shapes():
    """The shapes (_shape) of every path a dispatch can declare from a
    template: each "path" the current command files write, read at run time,
    and the producer question's. _ANY when a command file cannot be read:
    then any target may be declared."""

    shapes = {_shape(_QUESTION_PATH)}
    try:
        files = sorted(stop_contract.COMMANDS_DIR.glob("*.md"))
        for file in files:
            for raw in set(_TEMPLATE_PATH_RE.findall(_command_text(file))):
                # A JSON string with no escape in it is its own value (json.loads
                # gives it back, or refuses a control character and the raw
                # text is taken): only one with an escape is decoded.
                if "\\" in raw:
                    try:
                        value = json.loads(f'"{raw}"')
                    except ValueError:
                        value = raw
                else:
                    value = raw
                shapes.add(_shape(value))
    except (OSError, UnicodeDecodeError):
        return _ANY
    return _ANY if _ANY in shapes else shapes


def _could_be_declared(shapes, forms: list) -> bool:
    """Whether a path of one of ``shapes`` may cover a target of these forms:
    a declared path covers a run of the target's parts that ends with its own
    last part, so some part of the target must be that last part."""
    if shapes is _ANY:
        return True
    for kind, value in shapes:
        for form in forms:
            if (kind == "parts" and value and _covers(value, form)
                    or kind == "last" and value in form
                    or kind == "ends" and any(part.endswith(value) for part in form)):
                return True
    return False


def _declared_paths(obligation_doc: dict) -> list:
    return [a["path"] for a in obligation_doc.get("artifacts") or []
            if isinstance(a, dict) and isinstance(a.get("path"), str) and a["path"]]


_TEXT_ENCODING = None  # the encoding open() reads a text file with in this process, once one was opened


def _load_json(path):
    """json.load(open(path)): the same document, or an error of the same class
    (OSError, ValueError), from raw reads once the encoding open() decodes with
    in this process is known (the first file is read by open() itself). The
    line ends open() would translate cannot change what json.loads makes of
    the text: between tokens they are whitespace, inside a string an error."""
    global _TEXT_ENCODING
    if _TEXT_ENCODING is None:
        with open(path) as fh:
            _TEXT_ENCODING = fh.encoding
            return json.load(fh)
    fd = os.open(path, os.O_RDONLY)
    try:
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(fd)
    return json.loads(b"".join(chunks).decode(_TEXT_ENCODING))


def _plain_agent_id(agent_id) -> bool:
    return isinstance(agent_id, str) and 0 < len(agent_id) <= 128 and set(agent_id) <= _AGENT_ID_CHARS


def _agent_files(transcript, agent_id: str):
    """(transcript, meta) paths the CLI keeps for one subagent of the session."""
    if not _plain_agent_id(agent_id):
        return None, None
    sub = transcript.parent / transcript.stem / "subagents"
    return sub / f"agent-{agent_id}.jsonl", sub / f"agent-{agent_id}.meta.json"


_FENCE_SHAPES: dict = {}  # (command, subagent_type) -> _template_shapes(), once per process


def _segment_prefix(path: str) -> str:
    """The literal text that starts the segment of template path ``path``
    holding its last placeholder, up to that segment's first placeholder ("ticket-"
    for docs/dev/ticket-<timestamp>.md; "" for docs/dev/<x>.md). Every value
    goes in after it, so unless a value takes a part back with "/..", the
    declared path keeps a part that starts with it."""
    found = list(_SHAPE_PLACEHOLDER_RE.finditer(path))
    if not found:
        return ""
    start = path.rfind("/", 0, found[-1].start()) + 1
    first = next(m for m in found if m.start() >= start)
    return path[start:first.start()]


def _template_shapes(command, subagent_type: str):
    """(shape, segment prefix) of each path the worked examples of the fences
    of ``subagent_type`` in commands/<command>.md declare (_shape,
    _segment_prefix), read as dispatch_template._template reads that file
    (every harness command's when ``command`` is None: a dispatch carrying no
    obligation takes its span's). A file _template cannot open declares
    nothing; _ANY when reading one raises anything else, so the template is
    read and raises as it did."""

    key = (command, subagent_type)
    if key not in _FENCE_SHAPES:
        shapes = set()
        try:
            names = [command] if command is not None else sorted(stop_contract.harness_commands())
            for name in names:
                try:
                    text = _command_text(Path(stop_contract.COMMANDS_DIR) / f"{name}.md")
                except OSError:
                    continue
                for _body, kind, _roles, _profiles, example in dispatch_template._parsed_fences(text):
                    if kind != subagent_type or example is None:
                        continue
                    _example_shapes(example, shapes)
        except Exception:
            shapes = _ANY
        _FENCE_SHAPES[key] = shapes
    return _FENCE_SHAPES[key]


def _example_shapes(example: str, shapes: set, multi: set | None = None) -> None:
    """Add to ``shapes`` the (_shape, _segment_prefix) of each artifact path
    the worked example ``example`` declares; nothing when it is no JSON. A
    path of any shape raises ValueError. With ``multi``, also add there each
    pair of a shape "ends" made by a path whose last segment does not hold
    exactly one placeholder, a placeholder with no "/" in it (_one_value)."""
    try:
        declared = json.loads(example)
    except ValueError:
        return
    for entry in (declared.get("artifacts") or []) if isinstance(declared, dict) else ():
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            shape = _shape(entry["path"])
            if shape is _ANY:
                raise ValueError("a template path of any shape")
            pair = (shape, _segment_prefix(entry["path"]) if shape[0] == "ends" else "")
            shapes.add(pair)
            if multi is not None and shape[0] == "ends" and not _one_value(entry["path"]):
                multi.add(pair)


def _one_value(path: str) -> bool:
    """Whether the segment of template path ``path`` that holds its last
    placeholder holds no other, and that one holds no "/". Bound, such a
    segment is <prefix><value><tail>: its last part is that whole segment, or,
    when the value holds a "/", the value's text after its last "/" followed
    by the tail. A placeholder left unbound stays as it is written."""
    found = list(_SHAPE_PLACEHOLDER_RE.finditer(path))
    if not found:
        return False
    start = path.rfind("/", 0, found[-1].start()) + 1
    inside = [m for m in found if m.start() >= start]
    return len(inside) == 1 and "/" not in inside[0].group()


_OBLIGATION_OPEN, _OBLIGATION_CLOSE = '<obligation v="1">', "</obligation>"


def _template_bounds():
    """The (shape, segment prefix) of each path the obligation blocks of
    every command file declare: what _template_shapes gives for any command
    and subagent type is among them, for a fence's worked example is the
    text from one such opener to the first close after it, as
    dispatch_template's block pattern reads it (its whitespace stripped).
    _ANY where _template_shapes would be _ANY for one of them, or a file
    could be read that is not listed. Read once per decision; with a gate
    on it, a dispatch whose templates cannot cover a target is decided
    without reading any command's fences (cold, every command's were most
    of what a dispatch carrying no obligation cost)."""

    return _bounds()[0]


def _bounds():
    """(_template_bounds, the pairs among them _example_shapes puts in its
    ``multi``), read once per decision."""
    memo = _DECISION if _DECISION is not None else {}
    if "bounds" not in memo:
        shapes, multi = set(), set()
        try:
            folder = stop_contract.COMMANDS_DIR
            # Every name a template is read under (<command>.md, whatever the
            # case a file system folds) is listed here.
            for name in sorted(n for n in os.listdir(folder) if n.lower().endswith(".md")):
                try:
                    text = _command_text(folder / name)
                except OSError:
                    continue
                start = text.find(_OBLIGATION_OPEN)
                while start >= 0:
                    body = start + len(_OBLIGATION_OPEN)
                    end = text.find(_OBLIGATION_CLOSE, body)
                    if end < 0:
                        break
                    _example_shapes(text[body:end].strip(), shapes, multi)
                    start = text.find(_OBLIGATION_OPEN, body)
        except Exception:
            shapes = _ANY
        memo["bounds"] = (shapes, multi)
    return memo["bounds"]


def _bounds_may_cover_back(prompt: str, targets, bounds, multi) -> bool:
    """Whether a path of ``bounds`` may cover one of ``targets`` once bound to
    the values of ``prompt``, which holds "/.." (a value may take a part
    back), where none may without it (_shapes_may_cover). Each value is text
    of one of the prompt's lines (dispatch_template binds no other), so a
    pair whose paths all bind one value in their last segment (not in
    ``multi``) covers a target's part p ending with its tail only through a
    value ending in "/" + p without its tail: one the prompt then holds."""
    if bounds is _ANY:
        return True
    for forms in targets:
        for shape, prefix in bounds:
            if not prefix or not _could_be_declared({shape}, forms):
                continue  # covers no target, or already would without "/.."
            if (shape, prefix) in multi:
                return True
            tail = shape[1]
            if any(part.endswith(tail) and "/" + part[:-len(tail)] in prompt for form in forms for part in form):
                return True
    return False


def _shapes_may_cover(shapes, back: bool, targets) -> bool:
    """Whether a path of one of ``shapes`` ((shape, segment prefix) pairs, or
    _ANY) may cover one of ``targets`` (each a target's _target_forms): a
    path of a shape "ends" only through a part that starts with its segment
    prefix, unless a value may take a part back (``back``)."""
    if shapes is _ANY:
        return True
    for forms in targets:
        for shape, prefix in shapes:
            if (_could_be_declared({shape}, forms)
                    and (back or not prefix or any(part.startswith(prefix) for form in forms for part in form))):
                return True
    return False


def _template_may_cover(command, subagent_type: str, prompt: str, targets) -> bool:
    """Whether a path the template of such a dispatch declares may cover one
    of ``targets`` (each a target's _target_forms; None: any path). A path of
    a shape "ends" covers a target only through a part that starts with its
    segment prefix, unless the prompt, which every value is taken from, holds
    "/..". A template that cannot is not read: binding it to the prompt is
    most of a dispatch's cost in a long session, and nothing it declares
    could change a decision."""
    if targets is None:
        return True
    return _shapes_may_cover(_template_shapes(command, subagent_type), "/.." in prompt, targets)


# Fields obligation.validate_obligation compiles as patterns: the one step
# of its validation that can raise on a parsed JSON document (re.compile).
_PATTERN_FIELDS = ("terminal_line_regex", "waived_by_response")


def _obligation_may_declare(prompt: str, targets) -> bool:
    """Whether the obligation block of ``prompt``, valid or not, may declare a
    path that covers one of ``targets``: one of its artifacts' paths or the
    producer question its role and task name. The block is read as
    obligation.parse_obligation reads it, without validating it: a valid
    block declares no more than these, an invalid one nothing of its own, so
    where none covers a target the dispatch declares nothing that does
    whether its block is valid or not (its templates aside), and neither
    validating nor binding it can change a decision. Validation raises on no
    parsed document but through re.compile, and a block whose artifacts name
    a pattern is read in full; anything unexpected here reads it in full."""

    try:
        extracted = obligation.extract_obligation_block(prompt)
        if not isinstance(extracted, obligation.ExtractedBlock):
            return False
        try:
            doc = json.loads(extracted.body)
        except ValueError:
            return False
        if not isinstance(doc, dict) or not isinstance(doc.get("artifacts"), list):
            return False  # refused by validation: it declares nothing
        paths = []
        for entry in doc["artifacts"]:
            if isinstance(entry, dict):
                if any(field in entry for field in _PATTERN_FIELDS):
                    return True
                if isinstance(entry.get("path"), str) and entry["path"]:
                    paths.append(entry["path"])
        role, task_id = doc.get("role"), doc.get("task_id")
        if isinstance(role, str) and isinstance(task_id, str) and task_id:
            paths.append(_QUESTION_PATH.format(task_id=task_id, role=role))
        for path in paths:
            parts = _parts(path)
            if (parts and ".." not in parts and not path.startswith("/")
                    and any(_covers(parts, form) for forms in targets for form in forms)):
                return True
        return False
    except Exception:
        return True


def _declarations(record, calls: list, targets=None) -> list:
    """(path parts, role, task_id, dispatch id) for every path these
    dispatches declare, in call order; with ``targets`` (each a target's
    _target_forms), every template-declared path that may cover one of them,
    the obligations' own paths and producer questions all. A dispatch that
    carries no obligation takes its subagent_type's template in the command
    whose span holds its call in ``record``, or, with ``record`` None (calls
    read from their subagents' files, _started_dispatches), each of that
    type's templates in every command file."""

    question_roles = None
    # Whether any command's template may cover a target (_template_bounds):
    # where none may, no dispatch's template is looked for. Without "/.." in
    # the prompt that is each command's _template_may_cover; with it, where
    # none would cover without it, the prompt's own text says whether a value
    # can make one cover (_bounds_may_cover_back).
    bounded = None
    out = []
    for call in calls:
        prompt = call.input.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            continue
        subagent_type = call.input.get("subagent_type") or _DEFAULT_SUBAGENT_TYPE
        if targets is None:
            templates = True
        else:
            if bounded is None:
                bounds = _template_bounds()
                multi = _bounds()[1] if bounds is not _ANY else set()
                bounded = _shapes_may_cover(bounds, False, targets)
            templates = bounded or ("/.." in prompt and _bounds_may_cover_back(prompt, targets, bounds, multi))
            if not templates and not _obligation_may_declare(prompt, targets):
                continue  # declares nothing that covers a target, valid or not
        parsed = obligation.parse_obligation(prompt)
        own = parsed.obligation if isinstance(parsed, obligation.ParsedObligation) else None
        found = []  # (paths, role, task_id)
        if own is not None:
            role, task_id = own.get("role"), own.get("task_id")
            paths = _declared_paths(own)
            if templates and _template_may_cover(own.get("pipeline"), subagent_type, prompt, targets):
                template = dispatch_template.template_obligation(own.get("pipeline"), subagent_type, prompt)
                # Only the template this dispatch was made from: same role and profile.
                if template and all(template.get(k) == own.get(k) for k in ("role", "profile")):
                    paths += _declared_paths(template)
            if question_roles is None:
                question_roles = _question_roles()
            if role in question_roles and isinstance(task_id, str) and task_id:
                paths.append(_QUESTION_PATH.format(task_id=task_id, role=role))
            found.append((paths, role, task_id))
        else:
            if not templates:
                commands = []
            elif record is None:
                commands = [c for c in sorted(stop_contract.harness_commands())
                            if _template_may_cover(c, subagent_type, prompt, targets)]
            else:
                commands = ([record.command_before(call.line)]
                            if _template_may_cover(None, subagent_type, prompt, targets) else [])
            for command in commands:
                template = dispatch_template.template_obligation(command, subagent_type, prompt) if command else None
                if template:
                    found.append((_declared_paths(template), template.get("role") or subagent_type,
                                  template.get("task_id")))
        for paths, role, task_id in found:
            for path in dict.fromkeys(paths):
                parts = _parts(path)
                if parts and ".." not in parts and not path.startswith("/"):
                    out.append((parts, role, task_id, call.id))
    return out


def _started_dispatches(transcript) -> list:
    """The session's dispatches the CLI started a subagent for, as calls: each
    subagent whose meta names its call (toolUseId) and type (agentType, the
    CLI's general-purpose when it names none) and whose own transcript's first
    record holds its prompt (_agent_files). Only these files are read, never
    the session transcript, so the cost grows with the started dispatches; a
    dispatch refused at PreToolUse started none and is not among them."""

    folder = transcript.parent / transcript.stem / "subagents"
    try:
        names = sorted(n for n in os.listdir(folder) if n.startswith("agent-") and n.endswith(".meta.json"))
    except OSError:
        return []
    folder = os.fspath(folder)
    calls = []
    for name in names:
        agent_id = name[len("agent-"):-len(".meta.json")]
        if not _plain_agent_id(agent_id):
            continue
        # _agent_files' two paths, spelled once per dispatch as strings
        agent_transcript, meta = os.path.join(folder, f"agent-{agent_id}.jsonl"), os.path.join(folder, name)
        try:
            doc = _load_json(meta)
        except (OSError, ValueError):
            continue
        ident = doc.get("toolUseId") if isinstance(doc, dict) else None
        if not isinstance(ident, str) or not ident:
            continue
        prompt = obligation.read_first_record_prompt(agent_transcript)
        if prompt is not None:
            kind = doc.get("agentType")
            calls.append(command_span.Call(id=ident, name="Agent", line=-1, result_line=0, ok=False, input={
                "prompt": prompt, "subagent_type": kind if isinstance(kind, str) and kind else _DEFAULT_SUBAGENT_TYPE}))
    return calls


def _caller_dispatches(data: dict, transcript, calls: list) -> set:
    """The dispatch record(s) the calling subagent was started from: the one
    its CLI meta names when that call's prompt is the agent's own first
    record, else the calls carrying that prompt. The main agent has none."""

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
