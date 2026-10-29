"""Records the static half collects, and their JSON form.

Every scanner appends plain facts to one `Findings`; `static_half.derive` turns
them into the sorted record list. Templates are converted to patterns here, so
every record carries the same path form (patterns.to_pattern).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from . import patterns as P
from . import values as V


@dataclass
class Op:
    component: str          # the file whose code performs the operation
    line: int               # file:line of the literal code site
    op: str                 # read | write | create | unlink | rename
    path: V.Val             # abstract path
    mode: str               # content | name | list | append | truncate | exclusive | lock | temp | tree | source | db | touch
    via: str                # the API or command (open, os.replace, rm, >, ...)
    lang: str               # python | shell
    function: str = ""      # enclosing function, "" at module or script level
    src: V.Val | None = None  # rename source
    chain: tuple = ()       # inner sites when the path is bound at a call site
    origin: str = ""        # "md-block" for extracted command/agent blocks
    argv_from: str = ""     # the invocation site whose argument the path is (static_half._bind_argv)


@dataclass
class Decision:
    kind: str               # exit2 | exit | block | raise | route
    line: int
    code: int | None = None
    detail: str = ""        # exception name, or the helper that decides
    via: tuple = ()


@dataclass
class Deciding:
    component: str
    function: str
    read_line: int
    path: V.Val
    read_mode: str
    decision: Decision
    evidence: str           # branch | except | order | assert
    lang: str


@dataclass
class ChainCall:
    component: str
    line: int
    how: str                # exec | load | proxy
    uses: tuple             # sorted subset of verbatim, fields, status, returned
    fields: tuple
    function: str
    detail: str = ""


@dataclass
class OwnerOutput:
    component: str
    line: int
    channel: str            # system_message | command_text | command_print | script_print
    shown: str              # the path as shown (tokens written <name>)
    stream: str = ""        # stdout | stderr for prints
    reaches: str = ""       # registered | relayed:<file> | invoked_by:<file> | ""


@dataclass
class Invocation:
    component: str
    line: int
    target: str             # tree-relative file it runs
    interpreter: str
    captured: bool = False  # stdout captured into a value
    function: str = ""
    args: tuple = ()        # the values it passes after the target (argv[1:], $1...)


@dataclass
class LiteralFact:
    """A literal in code for rule (7): a collection, a mapping or an alternation."""
    component: str
    line: int
    shape: str              # collection | mapping | alternation | branch_map
    elements: tuple         # strings
    pairs: tuple = ()       # (key, value) for mappings
    lang: str = "python"


@dataclass
class EnvRead:
    component: str
    line: int
    name: str
    default: str | None
    compared: tuple = ()


@dataclass
class Findings:
    ops: list = field(default_factory=list)
    unresolved_sites: list = field(default_factory=list)   # (component, line, op, reason, function, lang)
    deciding: list = field(default_factory=list)
    chain_calls: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    system_message_relays: list = field(default_factory=list)  # (component, line)
    invocations: list = field(default_factory=list)
    literals: list = field(default_factory=list)
    env_reads: list = field(default_factory=list)
    raise_handlers: list = field(default_factory=list)     # (component, line, exception names, blocks)
    files: list = field(default_factory=list)              # (component, lang, status, detail)


def op_records(op: Op, tree_files: set[str]) -> list[dict]:
    """The relation records of one operation (one per resolved alternative)."""
    out: list[dict] = []
    temps = V.as_templates(op.path)
    srcs = V.as_templates(op.src) if op.src is not None else []
    if not temps:
        return out
    seen = set()
    for t in temps:
        if P.hole("none") in t or t == "":
            continue
        pat, holes, status = P.to_pattern(t)
        if P.is_os_path(pat):
            continue
        key = (pat, status)
        if key in seen:
            continue
        seen.add(key)
        rec = {
            "kind": "relation",
            "component": op.component,
            "op": op.op,
            "path": pat,
            "resolution": status,
            "holes": list(holes),
            "mode": op.mode,
            "via": op.via,
            "lang": op.lang,
            "site": f"{op.component}:{op.line}",
            "function": op.function,
        }
        if op.origin:
            rec["origin"] = op.origin
        if op.chain:
            rec["through"] = list(op.chain)
        if op.argv_from:
            rec["argv_from"] = op.argv_from
        if srcs:
            rec["from"] = sorted({P.to_pattern(s)[0] for s in srcs})
        if pat.startswith("<harness>/"):
            rel = pat[len("<harness>/"):]
            rec["in_tree"] = rel in tree_files
        out.append(rec)
    return out


def resolved_any(records: Iterable[dict]) -> bool:
    return any(r["resolution"] != "unresolved" for r in records)
