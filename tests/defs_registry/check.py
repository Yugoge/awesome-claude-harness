"""Group the definitions that state the same fact and hold every group to the register.

THE SAMENESS RULE. Two definitions state the same fact when their member sets
  (a) are equal (two or more members), or
  (b) differ by one member: one is the other plus one member, or one member replaced,
      i.e. max(|A - B|, |B - A|) == 1, and they still share at least three members.
A group is a connected component of that relation. (b) is what catches the copy that
differs by one member. It cannot chain unrelated tables: every link changes the member
set by at most one member and keeps three in common, so a small table can never be
linked to a large one through overlap (the first inventory's 75%-containment link
joined a 4-name table into any table holding three of its names, and through that
table to everything else it overlapped). On f199dfb1e the widest group spans two
members between its farthest definitions.

THE REGISTER (policies/definition-lookalikes.v1.json) lists sets of definitions that
are allowed to coexist. Each entry has a reason and two or more sides; the definitions
of one side answer one question, different sides answer different questions. A link
between two definitions is dropped when they sit on different sides of one entry; the
groups that remain after dropping are the uncovered groups. So two copies on the same
side, or a new copy no entry names, still form a group.

A register definition is (name, fingerprint): the scope-qualified name of scan.py and
a hash of the sorted members. Neither changes when the definition moves to another
line or file; renaming it or changing a member does change it, and the entry must be
re-stated. `at` is where it was when registered, for the reader only.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .scan import Definition, scan

REGISTER = "policies/definition-lookalikes.v1.json"
CORE = 3


def fingerprint(members) -> str:
    blob = json.dumps(sorted(members), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class RegisterError(Exception):
    pass


def load_register(path: Path) -> dict:
    """The register, validated: every entry has a reason sentence and at least two sides,
    every side at least one definition, every definition a name and a fingerprint."""
    try:
        reg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegisterError(f"{path}: cannot read the register: {exc}") from None
    problems, ids = [], set()
    for n, e in enumerate(reg.get("entries", [])):
        eid = e.get("id") or f"entry #{n}"
        if eid in ids:
            problems.append(f"{eid}: id used twice")
        ids.add(eid)
        reason = e.get("reason")
        if not isinstance(reason, str) or len(reason.split()) < 3:
            problems.append(f"{eid}: no reason (a sentence saying why these answer different questions)")
        sides = e.get("sides")
        if not isinstance(sides, list) or len(sides) < 2:
            problems.append(f"{eid}: fewer than two sides")
            continue
        for s in sides:
            if not isinstance(s, list) or not s:
                problems.append(f"{eid}: an empty side")
                continue
            for d in s:
                if not (isinstance(d, dict) and isinstance(d.get("name"), str)
                        and isinstance(d.get("fingerprint"), str) and len(d["fingerprint"]) == 16):
                    problems.append(f"{eid}: a definition without name and fingerprint: {d!r}")
    if problems:
        raise RegisterError("invalid register " + str(path) + ":\n  " + "\n  ".join(problems))
    return reg


def assign_slots(defs: list[Definition], reg: dict) -> tuple[dict[int, list[tuple[str, int]]], list[str]]:
    """Which (entry, side) each live definition fills, and the register definitions that
    match nothing in the tree. A slot covers one live definition: when the tree holds more
    definitions of one (name, fingerprint) than an entry lists, the extra ones (the later
    by path and line) stay unregistered."""
    live = defaultdict(list)
    for i in sorted(range(len(defs)), key=lambda i: (defs[i].file, defs[i].line)):
        live[(defs[i].name, fingerprint(defs[i].members))].append(i)
    placed: dict[int, list[tuple[str, int]]] = defaultdict(list)
    stale = []
    for e in reg.get("entries", []):
        used = defaultdict(int)
        for k, side in enumerate(e["sides"]):
            for d in side:
                key = (d["name"], d["fingerprint"])
                pool = live.get(key, [])
                if used[key] < len(pool):
                    placed[pool[used[key]]].append((e["id"], k))
                    used[key] += 1
                else:
                    stale.append(f"{e['id']}: {d['name']} {d['fingerprint']} (registered at {d.get('at', '?')})")
    return placed, stale


def _near_pairs(sets) -> set[frozenset]:
    """Pairs of distinct member sets that differ by one member and share >= CORE."""
    buckets = defaultdict(set)
    for s in sets:
        if len(s) >= CORE:
            buckets[s].add(s)
        if len(s) > CORE:
            for m in s:
                buckets[s - {m}].add(s)
    pairs = set()
    for bucket in buckets.values():
        for a, b in itertools.combinations(sorted(bucket, key=sorted), 2):
            if len(a & b) >= CORE and max(len(a - b), len(b - a)) == 1:
                pairs.add(frozenset((a, b)))
    return pairs


def groups(defs: list[Definition], placed: dict | None = None) -> list[list[int]]:
    """Connected components (two or more definitions) of the sameness relation, minus the
    links the register allows; each sorted by path and line, the list sorted likewise."""
    placed = placed or {}
    by_set = defaultdict(list)
    for i, d in enumerate(defs):
        by_set[d.members].append(i)

    def allowed(i, j):
        si = {(e, k) for e, k in placed.get(i, ())}
        return any(e == f and k != m for e, k in si for f, m in placed.get(j, ()))

    parent = list(range(len(defs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def link(a: list[int], b: list[int] | None = None):
        pairs = itertools.combinations(a, 2) if b is None else itertools.product(a, b)
        for i, j in pairs:
            if not allowed(i, j):
                parent[find(i)] = find(j)

    for ids in by_set.values():
        if len(ids) > 1:
            link(ids)
    for p in _near_pairs(by_set):
        a, b = tuple(p)
        link(by_set[a], by_set[b])
    comps = defaultdict(list)
    for i in range(len(defs)):
        comps[find(i)].append(i)
    key = lambda i: (defs[i].file, defs[i].line, defs[i].name)
    out = [sorted(c, key=key) for c in comps.values() if len(c) > 1]
    return sorted(out, key=lambda c: key(c[0]))


@dataclass
class Result:
    defs: list[Definition]
    uncovered: list[list[int]]
    stale: list[str]
    errors: list[str]

    @property
    def n_definitions(self) -> int:
        return sum(len(g) for g in self.uncovered)


def run(tree: Path, register: Path | None = None) -> Result:
    defs, errors = scan(tree)
    reg = load_register(register or tree / REGISTER)
    placed, stale = assign_slots(defs, reg)
    return Result(defs, groups(defs, placed), stale, errors)


def describe(defs: list[Definition], group: list[int]) -> list[str]:
    """A group as text: the shared members, then one line per definition with what it
    adds to or lacks from them."""
    sets = [defs[i].members for i in group]
    common = frozenset.intersection(*sets)
    lines = [f"{len(group)} definitions, {len({defs[i].file for i in group})} files; common: "
             + " ".join(repr(m) for m in sorted(common))[:200]]
    for i in group:
        d = defs[i]
        extra = sorted(d.members - common)
        lines.append(f"  {d.where}  {d.name}  [{d.kind}, fp {fingerprint(d.members)}]"
                     + (f"  +{' '.join(repr(m) for m in extra)}"[:160] if extra else ""))
    return lines
