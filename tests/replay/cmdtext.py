"""Command and agent text extraction (row 19 rule 9).

Drivers never hard-code a block's text: they take it, at run time, from the
command or agent file of the tree under test, located by heading text (for
example "Step 10" of commands/dev.md) and then by block order or a content
anchor, and fill its placeholders. Heading parsing is fence-aware, so a "# ..."
comment inside a fenced block is not a heading. Every lookup that matches no
place or more than one raises, so a renamed step fails the driver loudly.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

_FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^\s`]*)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_PLACEHOLDER_RE = re.compile(r"<(?!/)(?![^<>\n]*=)[A-Za-z$][^<>\n]{0,400}>")


class TextNotFound(LookupError):
    pass


@dataclass
class Block:
    lang: str
    text: str
    line: int  # 1-based line of the opening fence


def _read(path_or_text: str) -> str:
    if "\n" not in path_or_text and os.path.isfile(path_or_text):
        with open(path_or_text, encoding="utf-8") as fh:
            return fh.read()
    return path_or_text


def strip_frontmatter(text: str) -> str:
    m = re.match(r"---\n.*?\n---[ \t]*(?:\n|$)", text, re.S)
    return text[m.end():] if m else text


def _scan(lines):
    """Yield (index, kind, data): kind is 'heading' (level, title) or 'fence' (Block)."""
    i = 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if m:
            ch, n = m.group(2)[0], len(m.group(2))
            body, j = [], i + 1
            while j < len(lines):
                c = re.match(r"^\s*(%s{%d,})\s*$" % (re.escape(ch), n), lines[j])
                if c:
                    break
                body.append(lines[j])
                j += 1
            indent = len(m.group(1))
            text = "\n".join(l[indent:] if l[:indent].strip() == "" else l for l in body)
            yield i, "fence", Block(m.group(3), text + ("\n" if body else ""), i + 1)
            i = j + 1
            continue
        h = _HEADING_RE.match(lines[i])
        if h:
            yield i, "heading", (len(h.group(1)), h.group(2))
        i += 1


def section(path_or_text: str, heading: str) -> str:
    """The text under the one heading whose title holds `heading` as a whole phrase."""
    lines = _read(path_or_text).split("\n")
    pat = re.compile(r"(?<![\w])%s(?![\w])" % re.escape(heading))
    heads = [(i, d) for i, k, d in _scan(lines) if k == "heading"]
    hits = [(n, i, d) for n, (i, d) in enumerate(heads) if pat.search(d[1])]
    if len(hits) != 1:
        raise TextNotFound(f"heading {heading!r}: {len(hits)} matches {[d[1] for _, _, d in hits]}")
    n, start, (level, _) = hits[0]
    end = next((i for i, d in heads[n + 1:] if d[0] <= level), len(lines))
    return "\n".join(lines[start:end]) + "\n"


def blocks(path_or_text: str, heading: str | None = None, lang: str | None = None) -> list[Block]:
    text = section(path_or_text, heading) if heading else _read(path_or_text)
    out = [d for _, k, d in _scan(text.split("\n")) if k == "fence"]
    return [b for b in out if lang is None or b.lang == lang]


def block(path_or_text: str, heading: str | None = None, index: int | None = None,
          anchor: str | None = None, lang: str | None = None) -> str:
    """One fenced block of a section: by order (0-based) among `lang` blocks, or the one holding `anchor`."""
    cands = blocks(path_or_text, heading, lang)
    if anchor is not None:
        cands = [b for b in cands if anchor in b.text]
        if len(cands) != 1:
            raise TextNotFound(f"block with {anchor!r} under {heading!r}: {len(cands)} matches")
        return cands[0].text
    if index is None:
        if len(cands) != 1:
            raise TextNotFound(f"{len(cands)} blocks under {heading!r}; give index or anchor")
        return cands[0].text
    if not -len(cands) <= index < len(cands):
        raise TextNotFound(f"block {index} under {heading!r}: only {len(cands)}")
    return cands[index].text


def parse_dispatch(text: str) -> dict:
    """Fields of a 'Use Task/Agent tool with:' template: '- key: value', a value of a lone '"' runs to a line '"'."""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if re.match(r"\s*Use (?:the )?(?:Task|Agent) tool with:", l)), None)
    if start is None:
        raise TextNotFound("no 'Use Task/Agent tool with:' line")
    fields, i = {}, start + 1
    while i < len(lines):
        m = re.match(r"^\s*-\s+([A-Za-z_]+):\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).rstrip()
        if val == '"':
            body, i = [], i + 1
            while i < len(lines) and lines[i].strip() != '"':
                body.append(lines[i])
                i += 1
            ind = min((len(l) - len(l.lstrip()) for l in body if l.strip()), default=0)
            fields[key] = "\n".join(l[ind:] for l in body).strip("\n")
        else:
            fields[key] = val[1:-1] if len(val) >= 2 and val[0] == val[-1] == '"' else val
        i += 1
    return fields


def dispatch(path_or_text: str, heading: str, index: int | None = None, anchor: str | None = None) -> dict:
    """The dispatch template (description, prompt, subagent_type, ...) of a section."""
    cands = [b for b in blocks(path_or_text, heading) if re.search(r"Use (?:the )?(?:Task|Agent) tool with:", b.text)]
    if anchor is not None:
        cands = [b for b in cands if anchor in b.text]
    if index is not None:
        cands = cands[index:index + 1] if -len(cands) <= index < len(cands) else []
    if len(cands) != 1:
        raise TextNotFound(f"dispatch template under {heading!r} (index={index}, anchor={anchor!r}): {len(cands)} matches")
    return parse_dispatch(cands[0].text)


def inline_codes(path_or_text: str, heading: str, anchor: str) -> list[str]:
    """Backtick spans of the one paragraph or list item of a section that holds `anchor`."""
    text = section(path_or_text, heading)
    items = re.split(r"\n(?=\s*(?:[-*]|\d+\.)\s)|\n\s*\n", text)
    hits = [it for it in items if anchor in it]
    if len(hits) != 1:
        raise TextNotFound(f"item with {anchor!r} under {heading!r}: {len(hits)} matches")
    return re.findall(r"`([^`]+)`", hits[0])


def fill(text: str, values: dict) -> str:
    """Substitute placeholders literally (keys such as '<DEV_SESSION_ID>' or '$CLAUDE_PROJECT_DIR')."""
    for key in sorted(values, key=len, reverse=True):
        text = text.replace(key, str(values[key]))
    return text


def placeholders(text: str) -> list[str]:
    """Placeholders still unfilled ('<...>' spans that are not markup tags)."""
    return sorted(set(_PLACEHOLDER_RE.findall(text)))


def command_body(harness: str, name: str, args: str = "") -> str:
    """The isMeta body the CLI records for a typed /name: the file minus frontmatter, $ARGUMENTS filled."""
    body = strip_frontmatter(_read(os.path.join(harness, "commands", name + ".md")))
    if "$ARGUMENTS" in body:
        return body.replace("$ARGUMENTS", args)
    return body + (f"\n\nARGUMENTS: {args}" if args else "")
