"""Abstract values for the static half's evaluator (Python and shell alike).

A value is one of:

* `Str`: up to CAP alternative string templates (see patterns.py for tokens);
* `Unk`: nothing known, with the reason (E1's miss classes) and an optional id
  hint (``sid`` for a payload's ``session_id``);
* `Num`, `NoneV`: constants that matter for exit codes and defaults;
* `Lst`, `Dct`: literal containers;
* `Mod`, `Fn`, `Obj`, `Handle`, `Listing`: references the evaluator follows.

Every operation is pure and deterministic: alternatives are kept sorted.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import Iterable

from . import patterns as P

CAP = 8


@dataclass(frozen=True)
class Val:
    pass


@dataclass(frozen=True)
class Unk(Val):
    reason: str = "dynamic"
    hint: str | None = None


@dataclass(frozen=True)
class Str(Val):
    alts: tuple[str, ...]


@dataclass(frozen=True)
class Num(Val):
    value: int


@dataclass(frozen=True)
class NoneV(Val):
    pass


@dataclass(frozen=True)
class Lst(Val):
    items: tuple[Val, ...]


@dataclass(frozen=True)
class Dct(Val):
    items: tuple[tuple[Val, Val], ...]


@dataclass(frozen=True)
class Mod(Val):
    path: str | None      # tree-relative module file, or None for an external module
    name: str


@dataclass(frozen=True)
class Fn(Val):
    module: str
    qual: str


@dataclass(frozen=True)
class Obj(Val):
    kind: str             # 'args', 'proc', 'self', 'instance', 'chain', ...
    data: tuple = field(default=())


@dataclass(frozen=True)
class Handle(Val):
    path: Val
    mode: str
    site: int             # line of the open


@dataclass(frozen=True)
class Listing(Val):
    """An iterable of entries under a directory: ``names`` (os.listdir) yields
    bare names, ``paths`` (glob) yields full paths matching the template."""
    pattern: Val
    names: bool = False


NONE = NoneV()


def s(text: str) -> Str:
    return Str((text,))


def make_str(alts: Iterable[str]) -> Val:
    uniq = sorted(set(alts))
    if not uniq:
        return Unk("dynamic")
    if len(uniq) > CAP:
        uniq = uniq[:CAP]
    return Str(tuple(uniq))


def union(vals: Iterable[Val], drop_empty: bool = True) -> Val:
    """Join of alternative values (assignments in different branches).

    An empty string never wins over an unknown; with drop_empty (reaching
    assignments, where `x=""` initializes) it is also dropped beside other
    strings, while an explicit `"-x" if c else ""` keeps it."""
    vals = list(vals)
    if not vals:
        return Unk("dynamic")
    strs: list[str] = []
    others: list[Val] = []
    unks: list[Unk] = []
    for v in vals:
        if isinstance(v, Str):
            strs.extend(v.alts)
        elif isinstance(v, Unk):
            unks.append(v)
        elif isinstance(v, NoneV):
            continue
        else:
            others.append(v)
    nonempty = [x for x in strs if x != ""]
    if nonempty and not drop_empty:
        return make_str(strs)
    if nonempty:
        return make_str(nonempty)
    if unks:
        return unks[0]
    if strs:
        return make_str(strs)
    if others:
        # Prefer a container/reference over unknowns; first in source order.
        if all(isinstance(o, Lst) for o in others):
            items: list[Val] = []
            for o in others:
                items.extend(o.items)
            return Lst(tuple(items[:64]))
        if all(isinstance(o, Dct) for o in others) and len(others) > 1:
            return _merge_dicts(others, bool(unks))
        return others[0]
    if unks:
        return unks[0]
    return NONE


def _merge_dicts(dicts: list, open_ended: bool) -> Val:
    keys: list = []
    vals: dict = {}
    for d in dicts:
        for k, v in d.items:
            kk = k.alts if isinstance(k, Str) else None
            if kk is None:
                continue
            if kk not in vals:
                keys.append((k, kk))
                vals[kk] = []
            vals[kk].append(v)
    items = []
    for k, kk in keys:
        vs = vals[kk]
        if len(vs) < len(dicts) or open_ended:
            vs = vs + [Unk("assembled:dict", hint=kk[0] if len(kk) == 1 else None)]
        items.append((k, union(vs)))
    return Dct(tuple(items[:64]))


def piece(v: Val, name_hint: str | None = None) -> list[str]:
    """Templates for v used inside a larger string."""
    if isinstance(v, Str):
        return list(v.alts)
    if isinstance(v, Num):
        return [str(v.value)]
    if isinstance(v, NoneV):
        return [P.hole("none")]
    if isinstance(v, Handle):
        return piece(v.path, name_hint)
    if isinstance(v, Unk):
        if v.hint in P.IDS or v.hint == "proj":
            return [P.tok(v.hint)]
        for h in (v.hint, name_hint):
            t = P.id_template(h or "")
            if t:
                return [t]
        return [P.hole(v.reason)]
    if isinstance(v, Listing):
        if v.names:
            return [P.hole("assembled:listing")]
        return piece(v.pattern, name_hint)
    t = P.id_template(name_hint or "")
    if t:
        return [t]
    if isinstance(v, (Lst, Dct)):
        return [P.hole("assembled:container")]
    if isinstance(v, Obj) and v.kind == "args":
        return [P.hole("data:argv")]
    return [P.hole("dynamic")]


def concat(*vals: Val, hints: Iterable[str | None] = ()) -> Val:
    hints = list(hints)
    acc = [""]
    for i, v in enumerate(vals):
        h = hints[i] if i < len(hints) else None
        ps = piece(v, h)
        acc = [a + p for a in acc for p in ps]
        if len(acc) > CAP:
            acc = sorted(set(acc))[:CAP]
    return make_str(acc)


def _is_abs(t: str) -> bool:
    if t.startswith("/") or t.startswith("~"):
        return True
    sp = P.split(t)
    return bool(sp and sp[0][0] and sp[0][1] in P.ROOTS)


def _join2(a: str, b: str) -> str:
    if not b:
        return a
    if _is_abs(b):
        return b
    if not a:
        return b
    return a.rstrip("/") + "/" + b


def join(*vals: Val) -> Val:
    """os.path.join / Path / '/' over templates."""
    if not vals:
        return Unk("dynamic")
    acc: list[str] | None = None
    for v in vals:
        if isinstance(v, Handle):
            v = v.path
        ps = piece(v)
        if acc is None:
            acc = ps
        else:
            acc = [_join2(a, p) for a in acc for p in ps]
        if len(acc) > CAP:
            acc = sorted(set(acc))[:CAP]
    return make_str(acc or [])


def map_str(v: Val, fn) -> Val:
    if isinstance(v, Str):
        out = []
        for a in v.alts:
            r = fn(a)
            if r is not None:
                out.append(r)
        return make_str(out) if out else Unk("assembled:call")
    if isinstance(v, Handle):
        return map_str(v.path, fn)
    if isinstance(v, Listing) and not v.names:
        return map_str(v.pattern, fn)
    return v if isinstance(v, Unk) else Unk("dynamic")


def _tail_param(t: str):
    """(head, token) when the last path segment of t is one parameter token."""
    parts = P.split(t)
    if not parts or not parts[-1][0] or not parts[-1][1].startswith("@"):
        return None
    token = parts[-1][1]
    head = "".join(P.tok(x) if is_tok else x for is_tok, x in parts[:-1])
    if head and not head.endswith("/"):
        return None
    return head.rstrip("/"), token


def param_op(token: str, op: str) -> str:
    return P.tok(token + "|" + op)


def _argv_part(t: str) -> bool:
    """A template whose last segment holds a script argument (argv:N): its directory, name or
    suffix is not known until an invocation binds the whole argument."""
    last = t.rstrip("/").rsplit("/", 1)[-1]
    return any(x.startswith("argv:") for x in P.tokens_in(last))


def dirname(v: Val) -> Val:
    def f(t: str) -> str | None:
        if _argv_part(t):
            return P.hole("data:argv")
        tp = _tail_param(t)
        if tp is not None:
            head, token = tp
            return (head + "/" if head else "") + param_op(token, "parent")
        t = t.rstrip("/") if t != "/" else t
        if "/" not in t:
            sp = P.split(t)
            if len(sp) == 1 and sp[0][0] and sp[0][1] in P.ROOTS:
                return P.tok(sp[0][1]) + "/.."
            if len(sp) == 1 and sp[0][0] and sp[0][1].startswith("?"):
                return P.tok(sp[0][1])      # the directory of an unknown path is unknown
            return "."
        return t.rsplit("/", 1)[0] or "/"
    return map_str(v, f)


def basename(v: Val) -> Val:
    def f(t: str) -> str:
        if _argv_part(t):
            return P.hole("data:argv")
        tp = _tail_param(t)
        if tp is not None:
            return param_op(tp[1], "name")
        return t.rstrip("/").rsplit("/", 1)[-1]
    return map_str(v, f)


def with_suffix(v: Val, suffix: str) -> Val:
    def f(t: str) -> str:
        tp = _tail_param(t)
        if tp is not None and re.fullmatch(r"[A-Za-z0-9_.-]*", suffix):
            return (tp[0] + "/" if tp[0] else "") + param_op(tp[1], "wsfx=" + suffix)
        head, _, last = t.rpartition("/")
        root, ext = posixpath.splitext(last)
        new = (root if ext and P.L not in ext else last) + suffix
        return (head + "/" if head or t.startswith("/") else "") + new
    return map_str(v, f)


def with_name(v: Val, name: str) -> Val:
    def f(t: str) -> str:
        tp = _tail_param(t)
        if tp is not None:
            # a parameter's sibling lies in the parameter's directory, wherever the caller puts it
            head, token = tp
            return (head + "/" if head else "") + param_op(token, "parent") + "/" + name
        head, sep, _ = t.rpartition("/")
        return head + sep + name
    return map_str(v, f)


def stem(v: Val) -> Val:
    def f(t: str) -> str:
        if _argv_part(t):
            return P.hole("data:argv")
        tp = _tail_param(t)
        if tp is not None:
            return param_op(tp[1], "stem")
        last = t.rstrip("/").rsplit("/", 1)[-1]
        root, ext = posixpath.splitext(last)
        return root if ext else last
    return map_str(v, f)


def suffix_of(v: Val) -> Val:
    def f(t: str) -> str:
        if _argv_part(t):
            return P.hole("data:argv")
        tp = _tail_param(t)
        if tp is not None:
            return param_op(tp[1], "suffix")
        last = t.rstrip("/").rsplit("/", 1)[-1]
        return posixpath.splitext(last)[1]
    return map_str(v, f)


def reason_of(v: Val) -> str:
    if isinstance(v, Unk):
        return v.reason
    if isinstance(v, (Lst, Dct)):
        return "assembled:container"
    if isinstance(v, (Mod, Fn, Obj)):
        return "dynamic"
    return "dynamic"


def is_strlike(v: Val) -> bool:
    return isinstance(v, (Str, Handle)) or (isinstance(v, Listing) and not v.names)


def as_templates(v: Val) -> list[str]:
    if isinstance(v, Str):
        return list(v.alts)
    if isinstance(v, Handle):
        return as_templates(v.path)
    if isinstance(v, Listing) and not v.names:
        return as_templates(v.pattern)
    return []


def access(v: Val, op: str) -> Val:
    """One access-path step on a bound parameter value."""
    if op.startswith("."):
        key = op[1:]
        if isinstance(v, Dct):
            for k, val in v.items:
                if isinstance(k, Str) and k.alts == (key,):
                    return val
            return Unk("assembled:dict", hint=key)
        if isinstance(v, Obj) and v.kind == "args":
            return Unk("data:argv", hint=key)
        if isinstance(v, Str) and all(_is_param_only(a) for a in v.alts):
            return make_str([P.tok(a[1:-1] + "|" + op) for a in v.alts])
        if isinstance(v, Unk):
            return Unk(v.reason, hint=key)
        return Unk("assembled:container", hint=key)
    if op == "name":
        return basename(v)
    if op == "parent":
        return dirname(v)
    if op == "stem":
        return stem(v)
    if op == "suffix":
        return suffix_of(v)
    if op.startswith("wsfx="):
        return with_suffix(v, op[5:])
    return Unk("dynamic")


def _is_param_only(t: str) -> bool:
    sp = P.split(t)
    return len(sp) == 1 and sp[0][0] and sp[0][1].startswith("@")


def param_hint(token: str) -> str | None:
    """The name a parameter token's value is classified by (None after a path op)."""
    parts = token[1:].split("|")
    keys = [p[1:] for p in parts[1:] if p.startswith(".")]
    if any(not p.startswith(".") for p in parts[1:]):
        return None
    return keys[-1] if keys else parts[0]


def subst_params(template: str, binding: dict) -> list[str]:
    """Replace @name tokens (with their access paths) by every combination of
    the bound values' alternatives."""
    acc = [""]
    for is_tok, text in P.split(template):
        if is_tok and text.startswith("@"):
            parts = text[1:].split("|")
            base = parts[0]
            if base in binding:
                v = binding[base]
                for op in parts[1:]:
                    v = access(v, op)
                opts = piece(v, param_hint(text)) or [P.tok(text)]
            else:
                opts = [P.tok(text)]
        elif is_tok:
            opts = [P.tok(text)]
        else:
            opts = [text]
        acc = [a + o for a in acc for o in opts]
        if len(acc) > CAP:
            acc = sorted(set(acc))[:CAP]
    return acc


def subst_val(v: Val, binding: dict) -> Val:
    if isinstance(v, Str):
        out: list[str] = []
        for a in v.alts:
            out.extend(subst_params(a, binding))
        return make_str(out)
    if isinstance(v, Lst):
        return Lst(tuple(subst_val(i, binding) for i in v.items))
    if isinstance(v, Handle):
        return Handle(subst_val(v.path, binding), v.mode, v.site)
    if isinstance(v, Listing):
        return Listing(subst_val(v.pattern, binding), v.names)
    return v
