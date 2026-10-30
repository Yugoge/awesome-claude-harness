"""commands/*.md and agents/*.md: front matter, fenced shell blocks, obligation
templates and the text a command shows the owner.

Template placeholders (``<TASK_ID>``, ``{pipeline.timestamp_suffix}``) become
placeholder tokens (patterns.placeholder) before a block is parsed, so a block
parses as the shell the orchestrator runs once it fills them in.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import patterns as P

SHELL_INFO = {"bash", "sh", "shell", "zsh", "console"}

_FENCE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<info>[^\n`]*)$")
# `<TASK_ID>`, `<path or none>`, and a placeholder of a few words (`<resolved dev_report_path>`)
_PLACEHOLDER = re.compile(r"<([A-Za-z_][A-Za-z0-9_.:-]*(?: or [^<>\n]{0,40}| [A-Za-z_][A-Za-z0-9_.:-]*(?: [A-Za-z_][A-Za-z0-9_.:-]*){0,3})?)>")
# `{pipeline.index}`, `{REQUEST_ID}`: a brace with no comma or range is literal text to the
# shell, so in a command block it is the template's placeholder
_DOTTED_PH = re.compile(r"(?<![$\w])\{([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_.]+|[A-Z][A-Z0-9]*_[A-Z0-9_]+)\}")
# Text that addresses the owner: an imperative to announce/display/print/show/
# tell at the start of the line, or a phrase naming the user or the owner as
# the reader.
_OUTPUT_VERBS = re.compile(
    r"^\W*(announce|display|print|show|tell)\b"
    r"|\b(announce(?:ment)?|(?:display|print|show|report|surface|link)(?:s|ed)?\b[^.]{0,40}\b(?:to|for) (?:the )?(?:user|owner)"
    r"|tell (?:the )?(?:user|owner)|inform (?:the )?(?:user|owner)|final (?:summary|message|announcement)"
    r"|completion (?:message|announcement)|user-facing|owner-facing)\b", re.I)


@dataclass
class Block:
    info: str
    start_line: int          # line of the first content line
    text: str
    indent: str


def front_matter(text: str) -> dict | None:
    """The front matter's keys (simple `key: value` lines), or None without one."""
    if not text.startswith("---"):
        return None
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return None
    out = {}
    for i in range(1, min(len(lines), 200)):
        if lines[i].strip() == "---":
            return out
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", lines[i])
        if m:
            out[m.group(1)] = m.group(2).strip()
    return None


def blocks(text: str) -> list[Block]:
    out: list[Block] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = _FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        indent, fence, info = m.group("indent"), m.group("fence"), m.group("info").strip()
        body = []
        j = i + 1
        while j < len(lines):
            m2 = _FENCE.match(lines[j])
            if m2 and m2.group("fence")[0] == fence[0] and len(m2.group("fence")) >= len(fence) and not m2.group("info").strip():
                break
            ln = lines[j]
            if indent and ln.startswith(indent):
                ln = ln[len(indent):]
            body.append(ln)
            j += 1
        out.append(Block(info.split()[0].lower() if info else "", i + 2, "\n".join(body), indent))
        i = j + 1
    return out


def with_placeholders(text: str) -> str:
    """Template placeholders written as placeholder tokens."""
    text = _PLACEHOLDER.sub(lambda m: P.placeholder(m.group(1)), text)
    return _DOTTED_PH.sub(lambda m: P.placeholder(m.group(1)), text)


# ----------------------------------------------------------------- obligations

def _replace_outside_strings(text: str) -> str:
    """Placeholders outside JSON strings (``<"$TASK_ID" when ...>``) -> null."""
    out = []
    i = 0
    in_str = False
    while i < len(text):
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "<":
            j = text.find(">", i)
            if j > 0:
                out.append("null")
                i = j + 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _balanced(text: str, start: int, open_c: str, close_c: str) -> str | None:
    depth = 0
    in_str = False
    i = start
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return None


def _loads(text: str):
    for cand in (text, _replace_outside_strings(text)):
        try:
            return json.loads(cand)
        except (ValueError, TypeError):
            continue
    return None


def _artifacts_from_text(text: str) -> list[dict]:
    out = []
    i = 0
    while True:
        k = text.find("{", i)
        if k < 0:
            break
        obj = _balanced(text, k, "{", "}")
        if obj is None:
            break
        d = _loads(obj)
        if isinstance(d, dict) and "kind" in d:
            out.append(d)
            i = k + len(obj)
            continue
        if '"kind"' in obj:
            rec = {}
            for key in ("kind", "path", "schema", "terminal_line_regex", "begin_marker", "end_marker"):
                m = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % key, obj)
                if m:
                    rec[key] = m.group(1)
            if rec:
                out.append(rec)
            i = k + len(obj)
            continue
        i = k + 1
    return out


def obligations(text: str) -> list[dict]:
    """Obligation templates: the JSON blocks and the prose forms
    (``embed `<obligation v="1">{...}</obligation>` here with role="qa", ...``)."""
    out = []
    starts = [0]
    for i, c in enumerate(text):
        if c == "\n":
            starts.append(i + 1)

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts)
        while lo < hi:
            mid = (lo + hi) // 2
            if starts[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid
        return lo

    for m in re.finditer(r'<obligation v="1">((?:(?!<obligation v="1">).)*?)</obligation>', text, re.S):
        body = m.group(1).strip()
        line = line_of(m.start())
        if body in ("{...}", "{…}", ""):
            eol = text.find("\n", m.end())
            tail = text[m.end(): eol if eol >= 0 else len(text)]
            rec = _prose_obligation(tail)
            if rec:
                rec["form"] = "prose"
                rec["line"] = line
                out.append(rec)
            continue
        d = _loads(body)
        if isinstance(d, dict):
            rec = {
                "role": d.get("role"),
                "pipeline": d.get("pipeline"),
                "profile": [d.get("profile")] if isinstance(d.get("profile"), str) else [],
                "artifacts": [a for a in (d.get("artifacts") or []) if isinstance(a, dict)],
            }
        else:
            rec = {"role": _field(body, "role"), "pipeline": _field(body, "pipeline"),
                   "profile": [x for x in [_field(body, "profile")] if x],
                   "artifacts": _artifacts_from_text(body[body.find('"artifacts"'):] if '"artifacts"' in body else "")}
        rec["form"] = "json"
        rec["line"] = line
        out.append(rec)
    return out


def _field(text: str, key: str) -> str | None:
    m = re.search(r'"%s"\s*:\s*"([^"]*)"' % key, text)
    return m.group(1) if m else None


def _prose_obligation(tail: str) -> dict | None:
    role = re.search(r'\brole="([^"]+)"', tail)
    if not role:
        return None
    pipeline = re.search(r'\bpipeline="([^"]+)"', tail)
    prof = re.search(r'\bprofile=((?:"[^"]+"/?)+)', tail)
    profiles = re.findall(r'"([^"]+)"', prof.group(1)) if prof else []
    arts: list = []
    am = re.search(r"\bartifacts=\[", tail)
    if am:
        seg = _balanced(tail, am.end() - 1, "[", "]")
        if seg:
            d = _loads(seg)
            if isinstance(d, list):
                arts = [a for a in d if isinstance(a, dict)]
            else:
                arts = _artifacts_from_text(seg)
    return {"role": role.group(1), "pipeline": pipeline.group(1) if pipeline else None,
            "profile": profiles, "artifacts": arts}


# --------------------------------------------------------- command text output

def command_text_outputs(text: str) -> list[tuple[int, str, str]]:
    """(line, shown path, evidence) for paths the command text shows the owner:
    paths in a non-shell fenced block that an output line introduces, and
    backticked paths on an output line."""
    out = []
    lines = text.split("\n")
    shell_lines = set()
    for b in blocks(text):
        n = b.text.count("\n") + 1
        rng = range(b.start_line, b.start_line + n)
        if b.info in SHELL_INFO:
            shell_lines.update(rng)
            continue
        if b.info in ("json", "python", "yaml"):
            continue
        intro = ""
        k = b.start_line - 3
        seen = 0
        while k >= 0 and seen < 3:
            if lines[k].strip():
                intro = lines[k] + " " + intro
                seen += 1
            k -= 1
        if not _OUTPUT_VERBS.search(intro):
            continue
        for off, ln in enumerate(b.text.split("\n")):
            for shown in P.paths_in_text(_placeholders_shown(ln)):
                out.append((b.start_line + off, shown, "block"))
    in_fence = False
    for i, ln in enumerate(lines, start=1):
        if _FENCE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence or i in shell_lines:
            continue
        if not _OUTPUT_VERBS.search(ln):
            continue
        for code in re.findall(r"`([^`]+)`", ln):
            for shown in P.paths_in_text(_placeholders_shown(code)):
                out.append((i, shown, "prose"))
    return out


def _placeholders_shown(text: str) -> str:
    return P.shown_text(with_placeholders(text))
