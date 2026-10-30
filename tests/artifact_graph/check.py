"""The artifact check (P1b goal 5, Scope row 19): derivation and invariants.

`derive(tree, static, runs)` joins the static half (static_half.derive) and the
runtime relations of every traced replay (runtime.py: each driver and variant,
with the tree's own settings.json, "shipped", and with the sandbox-armed copy,
"armed") into one map of artifacts, and `violations(m)` states the invariants of
goals 1-4 over every artifact it finds. Nothing here names an artifact, a role,
a hook or a command: every name comes from the tree under test (settings.json,
the obligation templates of commands/*.md, scripts/todo/, agents/*.md,
schemas/) or from the replays.

Derivation rules, in the order row 19 states them:

(1) A file artifact is a path pattern (roots and the replay's ids as tokens).
    Runtime: every path a traced replay reads or writes, folded by trace.py
    (locks, same-run temporaries, private scratch) and here (a file one hook
    run creates and removes, whichever of its processes does each). A
    producer is the code that writes: a process, or the one file of the
    function it calls that writes only that artifact (a writer function two
    callers share is one producer, a generic helper is not). Static: relations at
    literal code sites (full, or partial with a known root); a static relation
    whose pattern matches exactly one runtime artifact joins it, else it is an
    artifact of its own. Inputs, not artifacts: a file present at replay start,
    a tracked tree file, a file under a directory nothing in the harness
    writes (the user's own project and home files: the platform's, as the
    CLI's), and a file whose reader's own text says the user creates it by
    hand, unless a trace event or a literal code site writes it. Git's own
    store (paths inside a git directory) is the platform's.
(2) Non-file artifacts from their declarations: a response block or line by
    its obligation's markers and terminal_line_regex (producer: the declaring
    obligation's role; readers: code and command-block sites holding the
    marker outside the producer side), a vocabulary by its schema enum
    (readers: the copies rule (7) finds), the task-id rule by the forms the
    command files mint (producer: the hook whose output carried the replay's
    task id first; readers: the sites that template or match a minted id), and
    the chain function's stdout (readers: its call sites, deciding when they
    test fields of it: a decision on the chain function's output that is not
    its use verbatim, rule (5)).
(3) Readers read content or names; a bulk read (trace.py: a program reading
    most files of a directory it listed, `git add -A`) reads nothing; a hook
    whose artifact reads in one run are exactly the triggering tool call's
    target paths reads them only where the differential's content mutation
    changes its decision.
(4) Deciders: a reader whose decision changes on a mutation (E1's
    differential, runtime.py and tests/replay/differential.py: every reader in
    the shipped replays, the producer side's readers in the armed ones); without
    a measurement, a static branch to an exit or a block on a read of the
    artifact (E1's fallback), armed-only when the hook reads a gate switch the
    armed copy sets otherwise (E4). Deciders of one artifact are one rule only
    when their deciding reads are the same code site (the one function they all
    call). Over E2's budget the differential runs only for the shipped readers
    outside the allowed positions (E1's fallback).
(5) Position of a deciding read: from the hook's event and matcher
    (settings.json) and the event's payload: the producer side (the artifact's
    producer's own stop or tool call), G1 (PreToolUse on Agent), G3
    (PostToolUse on Agent), the main agent's own stop (Stop, deciding on what
    the main agent's side wrote), a completion read (Stop, deciding on a
    subagent's artifact), the chain function's own call, elsewhere.
(6) A deciding read outside the allowed positions is a re-check when the
    producer side rejects the same mutation with the tree's switches; it is
    that fault's only stop (a copy for the arming commit to delete) when the
    producer side rejects it only armed; otherwise it is a rule to move into a
    gate or a use.
(7) Lists that repeat a declaration: the static half's rule-(7) literals, and
    the tool-policy prefixes that name the file of an artifact derived here.
(8) Every replay sets CLAUDE_STATE_DIR to a directory other than /tmp, and a
    file is read and written under one root (a reader under /tmp or TMPDIR of
    a file its writer puts under the state dir is a split).

`python -m tests.artifact_graph.check --tree T --work W` runs the static half,
the replays and the differential, prints every violation as facts and writes
the artifact map (text, sorted) under W.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field

from . import patterns as P

RUNTIME_ROLE = re.compile(r"^(main|agent:.+|cli)$")
ALLOWED = ("producer stop", "producer tool call", "own artifact", "G1", "G3", "own stop", "chain call", "library")
_HAND = re.compile(r"\b(by hand|manually|(user|owner|human|operator|you)\b[^\n]{0,60}\b(creat|touch|add|write|place|put)"
                   r"|(user|owner|human|operator)-run\b)", re.I)
# a path the text writes with its varying parts as placeholders (`claude-allow-<target>.flag`,
# `${DIR}/x-$ID.json`, `x-*.log`)
_TEXT_PATH = re.compile(r"[\w.$<>{}*-]*[\w>}*]\.[A-Za-z0-9]{1,6}\b")
_TEXT_HOLE = re.compile(r"<[^<>\s]+>|\$\{[^}\s]+\}|\$\w+|\*")
# a call that loads a module from a file path
_LOAD_BY_PATH = re.compile(r"\b(spec_from_file_location|SourceFileLoader|run_path|load_sibling_module)\b")


# ---------------------------------------------------------------- inputs

@dataclass
class Run:
    """One traced replay: its relation events, invocations, env and differential results."""
    label: str              # driver[~variant]
    settings: str           # shipped | armed
    dir: str
    events: list = field(default_factory=list)
    invocations: dict = field(default_factory=dict)
    env: dict = field(default_factory=dict)
    manifest: set = field(default_factory=set)
    differential: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    ids: dict = field(default_factory=dict)
    hooks: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.label}/{self.settings}"


def load_run(label: str, settings: str, run_dir: str) -> Run:
    from tests.replay import differential as D
    r = Run(label, settings, run_dir)
    r.events = D.load_events(run_dir)
    r.invocations = D.load_invocations(run_dir)
    for name, attr in (("env.json", "env"), ("differential.json", "differential"), ("summary.json", "summary"),
                       ("ids.json", "ids")):
        try:
            with open(os.path.join(run_dir, name)) as fh:
                setattr(r, attr, json.load(fh))
        except (OSError, ValueError):
            pass
    try:
        with open(os.path.join(run_dir, "start-manifest.txt"), encoding="utf-8", errors="surrogateescape") as fh:
            r.manifest = set(fh.read().splitlines())
    except OSError:
        pass
    try:
        with open(os.path.join(run_dir, "hooks.jsonl")) as fh:
            r.hooks = [json.loads(line) for line in fh]
    except (OSError, ValueError):
        pass
    return r


# ---------------------------------------------------------------- the map

@dataclass
class Rel:
    """One relation of a component to an artifact, with its evidence."""
    who: str                # component identity (hooks/x.py, main, agent:<type>, cli, owner, schema ...)
    op: str                 # write | read | unlink
    evidence: str           # file:line, or run/event
    source: str             # runtime | static | declaration | owner
    via: str = ""           # the process component when `who` is a writer function, the origin hook
    actor: str = ""         # the role whose call ran it (runtime)
    proc: str = ""          # runtime: the process component the trace saw


@dataclass
class Decision:
    who: str
    position: str
    evidence: str           # run/event/mutation, or file:line
    source: str             # differential | static
    how: str = ""           # mutation: removed | invalid | any
    settings: str = ""      # shipped | armed | static
    event: str = ""
    matcher: str = ""
    rule: str = ""          # code identity of the deciding read (rule (4))


@dataclass
class Artifact:
    key: str
    kind: str = "file"      # file | response | vocabulary | rule | stdout
    writers: list = field(default_factory=list)
    readers: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    declared: list = field(default_factory=list)   # obligations that declare it: {"role", "site", "schema"}
    runtime: bool = False
    note: str = ""

    def producers(self) -> list[str]:
        return sorted({w.who for w in self.writers})

    def consumers(self) -> list[str]:
        return sorted({r.who for r in self.readers})


@dataclass
class Map:
    tree: str
    artifacts: dict = field(default_factory=dict)
    runs: list = field(default_factory=list)
    static_records: int = 0
    extra: list = field(default_factory=list)       # violations not tied to one artifact
    measures: dict = field(default_factory=dict)
    ctx: object = None

    def art(self, key: str, kind: str = "file") -> Artifact:
        a = self.artifacts.get(key)
        if a is None:
            a = self.artifacts[key] = Artifact(key, kind)
        return a


# ---------------------------------------------------------------- names and patterns

def comp_identity(component: str) -> str:
    """Static components as the runtime names them: a command file's blocks run as the main
    agent, an agent file's blocks as that agent; code as its file."""
    m = re.match(r"^commands/[^/]+\.md(?:#\d+)?$", component)
    if m:
        return "main"
    m = re.match(r"^agents/([^/]+)\.md(?:#\d+)?$", component)
    if m:
        return "agent:" + m.group(1)
    return os.path.normpath(component)


def git_store(pattern: str) -> bool:
    from tests.replay.differential import git_store as g
    return g(pattern)


def runtime_pattern(pattern: str, env: dict) -> str:
    """A runtime pattern in the static half's root vocabulary."""
    if pattern.startswith("<project>"):
        pattern = "<proj>" + pattern[len("<project>"):]
    for key in ("TMPDIR", "CLAUDE_CODE_TMPDIR"):
        t = (env.get(key) or "").rstrip("/")
        if t and t != "/tmp" and (pattern == t or pattern.startswith(t + "/")):
            return "<tmpdir>" + pattern[len(t):]
    return pattern


def literal_root(pattern: str) -> bool:
    return bool(re.match(r"^(<(harness|home|proj|state|tmpdir)>|/)", pattern))


def directory(pattern: str) -> str:
    return pattern.rsplit("/", 1)[0] if "/" in pattern else ""


def _regex(pattern: str) -> re.Pattern:
    """A pattern as a regex over other patterns: <*> matches any text; an id token (<task>,
    <sid>, <lane>: the static half names an id by the variable that holds it, the replay by its
    value, as `session_id="$1"` given dev-<ts>) and <rand> (a temp-name generator's random part,
    which the runtime half writes <rand> inside its prefix and suffix) any text within a segment;
    <ts> a minted id that ends in a timestamp (dev-<ts>: rule (1) replaces only the timestamp);
    other tokens themselves."""
    out = []
    for m in re.finditer(r"<([a-z*]+)>|[^<]+|<", pattern):
        if m.group(1) is None:
            out.append(re.escape(m.group(0)))
        elif m.group(1) == "*":
            out.append(r"(?:(?!<rand>).)*?")      # no code names a temp-name generator's part
        elif m.group(1) in ("task", "sid", "lane"):
            out.append(r"(?:(?!<rand>)[^/])+?")    # an id is never a temp-name generator's part
        elif m.group(1) == "rand":
            out.append(r"[^/]+?")
        elif m.group(1) == "ts":
            out.append(r"[A-Za-z0-9_-]*?<ts>")
        else:
            out.append(re.escape("<" + m.group(1) + ">"))
    return re.compile("^" + "".join(out) + "$")


_RX: dict[str, re.Pattern] = {}


def matches(static_pattern: str, pattern: str) -> bool:
    rx = _RX.get(static_pattern)
    if rx is None:
        rx = _RX[static_pattern] = _regex(static_pattern)
    return bool(rx.match(pattern))


# ---------------------------------------------------------------- derivation

def derive(tree: str, static, runs: list[Run], *, chain_script: str | None = None) -> Map:
    from .static_half import DEFAULT_CHAIN_SCRIPT
    chain_script = chain_script or DEFAULT_CHAIN_SCRIPT
    m = Map(os.path.abspath(tree), runs=runs, static_records=len(static.records))
    recs = static.records
    decl = [r for r in recs if r["kind"] == "declaration"]
    obligations = [d for d in decl if d["type"] == "obligation"]
    registrations = [d for d in decl if d["type"] == "hook_registration"]
    switches = [d for d in decl if d["type"] == "gate_switch"]
    tree_files = _tree_files(tree)
    ctx = _Ctx(m, recs, obligations, registrations, switches, tree_files, chain_script, runs, tree)
    ctx.runtime_files()
    ctx.static_files()
    ctx.inputs()
    ctx.declarations()
    ctx.owner_outputs()
    ctx.platform_installs()
    ctx.deciding()
    ctx.non_file()
    m.ctx = ctx
    return m


def _tree_files(tree: str) -> set:
    from .static_half import list_files
    return set(list_files(__import__("pathlib").Path(tree)))


class _Ctx:
    def __init__(self, m, recs, obligations, registrations, switches, tree_files, chain_script, runs, tree):
        self.m, self.recs, self.obl, self.regs, self.switches = m, recs, obligations, registrations, switches
        self.tree_files, self.chain_script, self.runs, self.tree = tree_files, chain_script, runs, tree
        self.rt_keys: set = set()
        self.measured: dict = {}        # (reader, artifact) -> {"changed": set(how), "settings": set}
        self.texts: dict = {}
        # writer identity per (process component, artifact): the innermost static write site's file
        self.writer_fn: dict = {}
        self.dirs: set = set()          # paths code tests to be directories (rule (3))
        self.moved: dict = {}           # a name joined to the file it aliases (rule (1)'s roots)

    # ------------------------------------------------------------ runtime
    def runtime_files(self) -> None:
        m = self.m
        for run in self.runs:
            private = _private_scratch(run.events)
            for e in run.events:
                op = e["op"]
                if e["bulk"] or e["raw"] in private:
                    continue
                if op == "rename":
                    if " -> " not in e["pattern"]:
                        continue
                    src, dst = e["pattern"].split(" -> ", 1)
                    for pat, rop in ((src, "write"), (dst, "write")):
                        if pat == "?":
                            continue
                        self._rt(run, e, runtime_pattern(pat, run.env), rop)
                    continue
                pat = runtime_pattern(e["pattern"], run.env)
                rop = {"create": "write", "write": "write", "read": "read", "unlink": "unlink"}.get(op)
                if rop:
                    self._rt(run, e, pat, rop)

    def _rt(self, run: Run, e: dict, pat: str, op: str) -> None:
        if git_store(pat) or pat.startswith(("<origin>", "<sb>")):
            return
        if op == "unlink":
            return      # removing a file reads none of its content and writes none

        a = self.m.art(pat)
        a.runtime = True
        self.rt_keys.add(pat)
        who = e["comp"] if RUNTIME_ROLE.match(e["comp"]) else os.path.normpath(e["comp"])
        inv = run.invocations.get(e["event"]) or {}
        evidence = f"{run.name}#{e['event']}:{inv.get('event', '')}:{inv.get('label', '')}"
        rel = Rel(who, op, evidence, "runtime", via=e["origin"], actor=e["actor"] or self._actor(inv), proc=who)
        rel.raw = e["raw"]        # type: ignore[attr-defined]
        rel.seq = e["event"]      # type: ignore[attr-defined]
        rel.run = run             # type: ignore[attr-defined]
        (a.writers if op == "write" else a.readers).append(rel)

    @staticmethod
    def _actor(inv: dict) -> str:
        p = inv.get("payload") or {}
        return ("agent:" + p["agent_type"]) if p.get("agent_type") else ("main" if p else "")

    # ------------------------------------------------------------ static
    def static_files(self) -> None:
        m = self.m
        rels = [r for r in self.recs if r["kind"] == "relation" and r["resolution"] != "unresolved"]
        rt = sorted(self.rt_keys)
        own: dict = {}
        staged = []
        temps = _rename_sources(rels)
        floating: set = set()
        # a project-dir resolver's last tiers are the harness home or HOME (the session ran
        # there): a site whose alternatives name the same path under the project (<proj>, or the
        # payload's cwd the static half cannot root) and under <harness> (<proj>/.claude/x beside
        # HOME's .claude/x, which is <harness>/x) names one file, the project's
        proj_tails = {(r["site"], r["op"], r["path"].split("/", 1)[1]) for r in rels
                      if r["path"].startswith(("<proj>/", "<*>/"))}
        # a path some code tests to be a directory is one: its other name tests (`-nt`, exists)
        # name no file either
        dirs = {r["path"] for r in rels if r["op"] == "read" and r.get("mode") == "name"
                and _DIR_TEST.search(r.get("via") or "")}
        # a directory moved to a new name (`mv "$VENV" "$VENV.bak-<ts>"`) is still a directory:
        # its new name names no file either
        dirs |= {r["path"] for r in rels if r["op"] == "rename" and r.get("from")
                 and all(s in dirs for s in r["from"])}
        self.dirs = dirs
        for r in rels:
            if (r["op"] == "rename" or r["op"] == "read" and r.get("mode") == "name") and r["path"] in dirs:
                continue
            if r["path"].startswith(("<harness>/", "<home>/")):
                root, tail = r["path"].split("/", 1)
                tails = {tail, ".claude/" + tail} if root == "<harness>" else {tail}
                if {(r["site"], r["op"], t) for t in tails} & proj_tails:
                    continue
            if r.get("mode") in ("temp", "lock", "tree") or not _content_relation(r):
                continue
            pat = r["path"]
            if git_store(pat) or pat.rsplit("/", 1)[-1] == ".git" or _LOCK.search(pat):
                continue    # git's store (and a repository's .git entry) is the platform's; a lock
                # folds into the file it serves
            if r["op"] != "rename" and (r["component"], pat) in temps:
                continue    # a same-run temporary folds into the file it is renamed onto
            op = {"read": "read", "write": "write", "create": "write", "rename": "write"}[r["op"]]
            hits = self._joins(pat, rt)
            family = literal_root(pat) or _family(pat)
            if family and (len(hits) > 1 and op == "read" and ("<*>" not in pat or _named(pat, 4))
                           or hits and "<*>" in pat and _named(pat)):
                # one code site reading an id-keyed file (or a scan of a name family) reads each
                # instance the replays made of it (context-<task>.json: a /dev task's and a
                # fan-out lane's); a named family
                # (claude-<*>-userintent-<sid>.flag) is each member, those only code names too. A
                # write keyed by an id stays with the one instance it matches, or none: which
                # task's file a writer makes is the run's, not the pattern's. A writer of a named
                # family that the replays show writing some of its members writes those: the run
                # shows which of them its code makes (the fan-out's aggregate, not the lanes'
                # reports beside it)
                if op == "write":
                    mine = [h for h in hits if any(w.source == "runtime" and w.who == comp_identity(r["component"])
                                                   for w in m.artifacts[h].writers)]
                    hits = mine or hits
                for h in hits:
                    staged.append((r, op, h))
                if "<*>" in pat and literal_root(pat):
                    floating.add(pat)
                    staged.append((r, op, pat))
                continue
            if len(hits) > 1:
                continue    # an id-keyed write the replays made several instances of: each
                # instance's writer is the trace's; the pattern names no artifact of its own
            target = hits[0] if len(hits) == 1 else None
            if target is None:
                if not literal_root(pat) and _named(pat) and _family(pat):
                    floating.add(pat)   # an unknown root, a name of its own: it joins or goes
                elif not literal_root(pat) or "<*>" in pat and not self._specific(pat):
                    continue
                target = pat
            staged.append((r, op, target))
        # the writer of an artifact is the innermost frame of its write chain that writes only it
        # (a function that names the artifact), not a generic helper many artifacts go through
        frame_targets: dict = {}
        for r, op, target in staged:
            if op == "write":
                for f in self._frames(r):
                    frame_targets.setdefault(f, set()).add(target)
        for r, op, target in staged:
            who = comp_identity(r["component"])
            if op == "write":
                ident = who
                for f in reversed(self._frames(r)):
                    if len(frame_targets.get(f, ())) <= 2 and not f.startswith(("main", "agent:")):
                        ident = f.split(":", 1)[0]   # functions of one file are one writer
                        break
                self.writer_fn.setdefault((who, target), set()).add(ident)
                own.setdefault(target, []).append(Rel(ident, op, r["site"], "static", via=who))
            else:
                own.setdefault(target, []).append(Rel(who, op, r["site"], "static"))
        # one process reaching an artifact through several files of its own code is one producer
        for target, rels_ in own.items():
            idents: dict[str, set] = {}
            for rel in rels_:
                if rel.op == "write" and rel.via:
                    idents.setdefault(rel.via, set()).add(rel.who)
            for via, ids in idents.items():
                if len(ids) > 1:
                    for rel in rels_:
                        if rel.op == "write" and rel.via == via:
                            rel.who = via
                    self.writer_fn[(via, target)] = {via}
        # static-only patterns: a partial one joins the narrower static patterns it matches (the
        # narrowest: those no other one narrows further) when that is exactly one, or when its
        # file name keeps a name of its own beside the varying part (claude-<*>-intent-<sid>.flag:
        # its code writes or reads each of their instances); one with an unknown root joins them
        # or names no artifact
        static_only = sorted(k for k in own if k not in self.rt_keys)
        # a name a temp-name generator minted is known only to the run that minted it and what
        # that run hands it to: no other code's pattern reaches it
        rooted = [k for k in static_only if literal_root(k) and "<rand>" not in k]

        def narrower(k: str) -> list:
            # f is narrower when k matches it and f has fewer varying parts, or f does not match k
            return [f for f in rooted if f != k and matches(k, f)
                    and (f.count("<*>") < k.count("<*>") or not matches(f, k))]

        under = {k: narrower(k) for k in static_only if "<*>" in k}
        moves = {}
        for k, hits in under.items():
            dest = [f for f in hits if not under.get(f)]
            if len(dest) == 1 or dest and _named(k):
                moves[k] = dest
            elif k in floating:
                moves[k] = []
        # a pattern that goes (it joined the runtime instances it matches, or it names no
        # artifact) is no destination: a wider pattern narrowing to it joined those instances
        # itself, and brought there it would come back as an artifact holding half the relations
        gone = {k for k, dest in moves.items() if not dest}
        for k, dest in list(moves.items()):
            if set(dest) & gone:
                kept = [h for h in dest if h not in gone]
                if kept:
                    moves[k] = kept
                elif k in floating:
                    moves[k] = []
                else:
                    del moves[k]
        for k, dest in moves.items():
            moved = own.pop(k)
            for h in dest:
                own.setdefault(h, []).extend(moved)
        own = self._without_scratch(own, rels)
        # a file under a tree a component creates whole (python -m venv DIR) is that component's
        trees = [r for r in rels if r["op"] == "create" and r.get("mode") == "tree" and literal_root(r["path"])]
        for k, rels_ in own.items():
            if any(x.op == "write" for x in rels_):
                continue
            for r in trees:
                if k.startswith(r["path"].rstrip("/") + "/"):
                    who = comp_identity(r["component"])
                    rels_.append(Rel(who, "write", r["site"], "static", via=who))
                    break
        for k in sorted(own):
            a = m.art(k)
            for rel in own[k]:
                if rel.op == "write":
                    if not self._seen(a.writers, rel):
                        a.writers.append(rel)
                else:
                    if not self._seen(a.readers, rel):
                        a.readers.append(rel)
        # a runtime writer counts as its writer function when the static half finds one for that
        # process and artifact (rows 11 and 14: one writer function that both callers call)
        for a in m.artifacts.values():
            static_writers = sorted({w.who for w in a.writers if w.source == "static"})
            for w in a.writers:
                if w.source != "runtime":
                    continue
                fns = self.writer_fn.get((w.who, a.key))
                if not fns:
                    # a library the process sources or imports, which the static half finds writing it
                    fns = {x for x in static_writers if x != w.who and self._loads(w.who, x)}
                if fns and len(fns) == 1:
                    fn = next(iter(fns))
                    if fn != w.who:
                        w.via, w.who = w.who, fn
            # a static write the runtime already shows (same writer) adds nothing
            seen = {(w.who, w.via) for w in a.writers if w.source == "runtime"}
            a.writers = [w for w in a.writers if w.source != "static" or (w.who, w.via) not in seen
                         and w.who not in {x.who for x in a.writers if x.source == "runtime"}]

    def _without_scratch(self, own: dict, rels: list) -> dict:
        """Rule (1) at literal code sites: a file a temp-name generator named, or one under a
        directory it named (<rand>), is the private scratch of the run that minted the name (the
        name exists in that run alone, and only what the run hands it to finds it; two
        components' <rand> files are two files); a file only one component relates to is its
        private scratch when that component writes it and also removes it or a directory above it.
        A reader that removes what another component wrote consumes it: not scratch. A file a
        trace event shows is the runtime half's to fold (tests/replay/trace.py)."""
        removed: dict = {}
        for r in rels:
            if r["op"] == "unlink":
                removed.setdefault(comp_identity(r["component"]), []).append(r["path"])

        def scratch(target: str, rels_: list) -> bool:
            cs = {(x.via or x.who) if x.op == "write" else x.who for x in rels_}
            if target in self.rt_keys:
                return False
            if any("<rand>" in seg for seg in target.split("/")):
                return True     # each creation mints its own name: two components' are two files
            if len(cs) != 1:
                return False
            return any(x.op == "write" for x in rels_) and any(
                p == target or matches(p, target) or target.startswith(p.rstrip("/") + "/")
                for p in removed.get(next(iter(cs)), ()))

        return {t: rels_ for t, rels_ in own.items() if not scratch(t, rels_)}

    def _loads(self, component: str, lib: str, depth: int = 3) -> bool:
        """The component's code runs `lib`'s in its own process: its text sources or imports `lib`
        (a shell `source`/`.` of the file, or of a variable assigned its path; a Python import), or
        loads it by its file name (importlib's spec_from_file_location, runpy), or a library it
        imports or sources does (a writer function reached through a library is still that
        function, rows 11 and 14)."""
        if not component.startswith(("hooks/", "scripts/")) or not lib.startswith(("hooks/", "scripts/")):
            return False
        key = (component, lib, depth)
        cache = self.__dict__.setdefault("_loads_seen", {})
        if key not in cache:
            cache[key] = False      # a cycle of imports loads nothing new
            cache[key] = self._loads_directly(component, lib) or depth > 0 and any(
                self._loads(mid, lib, depth - 1) for mid in self._loaded_libs(component))
        return cache[key]

    def _loads_directly(self, component: str, lib: str) -> bool:
        text = self._text(component)
        base = lib.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0] if "." in base else base
        if base.endswith(".sh") or "." not in base:
            if re.search(r"(^|[\s;&|])(source|\.)\s+[^\n]*" + re.escape(base), text, re.M):
                return True
            # `. "$LIB"` where LIB is assigned the library's path
            for var in re.findall(r"(?:^|[\s;&|])(?:source|\.)\s+\"?\$\{?(\w+)", text, re.M):
                if re.search(r"(?:^|[\s;])(?:local\s+)?" + re.escape(var) + r"=[^\n]*" + re.escape(base), text, re.M):
                    return True
            return False
        if re.search(r"^\s*(from\s+[\w.]*\b" + re.escape(stem) + r"\b|import\s+[\w., ]*\b"
                     + re.escape(stem) + r"\b|from\s+[\w.]+\s+import\s+[\w., (]*\b" + re.escape(stem) + r"\b)",
                     text, re.M):
            return True
        # a module loaded by its file name: the name within a few lines of the loading call
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if _LOAD_BY_PATH.search(line) and any(base in x for x in lines[max(0, i - 3):i + 1]):
                return True
        return False

    def _loaded_libs(self, component: str) -> list[str]:
        """The tree's library files a component imports or sources by name."""
        cache = self.__dict__.setdefault("_libs_of", {})
        if component not in cache:
            cache[component] = [f for f in self._libs() if f != component and self._loads_directly(component, f)]
        return cache[component]

    def _libs(self) -> list[str]:
        if not hasattr(self, "_lib_files"):
            self._lib_files = sorted(f for f in self.tree_files if f.startswith(("hooks/lib/", "scripts/lib/"))
                                     and f.endswith((".py", ".sh")) and "/tests/" not in f)
        return self._lib_files

    def _frames(self, r: dict) -> list[str]:
        """file:function of each frame of a relation's chain, outermost first."""
        out = []
        for site in [r["site"]] + list(r.get("through") or []):
            f, _, line = site.rpartition(":")
            fn = self._function_at(f, int(line) if line.isdigit() else 0)
            out.append(comp_identity(f) + (":" + fn if fn else ""))
        return out

    def _function_at(self, rel: str, line: int) -> str:
        key = ("fn", rel)
        spans = self.texts.get(key)
        if spans is None:
            spans = []
            text = self._text(rel)
            if rel.endswith(".py") or text.startswith("#!") and "python" in text.split("\n", 1)[0]:
                import ast
                try:
                    tree = ast.parse(text)
                    for n in ast.walk(tree):
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            spans.append((n.lineno, getattr(n, "end_lineno", n.lineno) or n.lineno, n.name))
                except SyntaxError:
                    pass
            else:
                for i, ln in enumerate(text.splitlines(), 1):
                    mm = re.match(r"^\s*(?:function\s+)?([A-Za-z_][\w:.-]*)\s*\(\)\s*\{?\s*$", ln)
                    if mm:
                        spans.append((i, i + 10**6, mm.group(1)))
            self.texts[key] = spans
        best = ""
        best_start = -1
        for a, b, name in spans:
            if a <= line <= b and a > best_start:
                best, best_start = name, a
        return best

    @staticmethod
    def _seen(rels: list, rel: Rel) -> bool:
        """A static relation adds nothing where the runtime already shows that component on it."""
        return any(x.who == rel.who and x.op == rel.op and (x.source == "runtime" or x.evidence == rel.evidence)
                   for x in rels)

    @staticmethod
    def _specific(pat: str) -> bool:
        base = pat.rsplit("/", 1)[-1]
        return len(re.sub(r"<[a-z*]+>", "", base).strip(".-_")) >= 4

    def _joins(self, pat: str, rt: list) -> list:
        """The runtime artifacts a static pattern names."""
        if pat in self.rt_keys:
            return [pat]
        return [k for k in rt if matches(pat, k)]

    def _join(self, pat: str, rt: list) -> str | None:
        """The one runtime artifact a static pattern names, if exactly one."""
        if pat in self.rt_keys:
            return pat
        hits = [k for k in rt if matches(pat, k)]
        return hits[0] if len(hits) == 1 else None

    # ------------------------------------------------------------ inputs (rule 1)
    def _home_aliases(self) -> None:
        """Rule (1), the roots' own aliases. The harness home is a git checkout that is a
        session's project when the harness itself is worked on (its pre-commit hook and CI run
        there, render-settings changes into it), and it is the `.claude` directory of a session
        whose project is the home directory. So a file code reads under one of these names, which
        nothing writes under that name while code writes it under the other, is that one file:
        `<proj>/X` and `<harness>/X`, `<proj>/.claude/X` and `<harness>/X` (as the rule for
        tracked files below treats a tracked file's two names). Only code sites join this way;
        a replay reads a file where the replay's own layout puts it."""
        m = self.m
        written = sorted(k for k, a in m.artifacts.items() if a.kind == "file" and a.writers)
        for k in sorted(m.artifacts):
            a = m.artifacts[k]
            if a.kind != "file" or a.writers or not a.readers or a.runtime \
                    or any(r.source != "static" for r in a.readers):
                continue
            root, _, tail = k.partition("/")
            if root == "<proj>":
                names = ["<harness>/" + (tail[len(".claude/"):] if tail.startswith(".claude/") else tail)]
            elif root == "<harness>":
                names = ["<proj>/.claude/" + tail, "<proj>/" + tail]
            else:
                continue
            hits = [w for w in written if any(w == n or matches(n, w) for n in names)]
            if not hits:
                continue
            for h in hits:
                dest = m.artifacts[h]
                for r in a.readers:
                    if not any(x.who == r.who and x.evidence == r.evidence for x in dest.readers):
                        dest.readers.append(r)
            self.moved[k] = hits
            del m.artifacts[k]

    def inputs(self) -> None:
        m = self.m
        self._home_aliases()
        written_dirs = {directory(k) for k, a in m.artifacts.items()
                        if any(w.source == "static" or not RUNTIME_ROLE.match(w.who) or w.who == "cli"
                               for w in a.writers)}
        declared = self._declared_patterns()
        written_dirs |= {directory(p) for p in declared}
        drop = []
        keys = sorted(m.artifacts)
        for i, k in enumerate(keys):
            a = m.artifacts[k]
            if k.rsplit("/", 1)[-1] in ("-", "") or (not a.runtime and i + 1 < len(keys)
                                                     and keys[i + 1].startswith(k + "/")):
                drop.append(k)      # stdout, or a directory: the files under it are the artifacts
                continue
        written_tails = {_state_tail(k) for k, a in m.artifacts.items() if a.writers} - {None}
        for k, a in m.artifacts.items():
            if a.writers or k in drop:
                continue
            if _state_tail(k) in written_tails:
                continue    # the same file under another state root: rule (8)'s split, not an input
            if a.runtime:
                raws = {getattr(r, "raw", None) for r in a.readers if r.source == "runtime"}
                manifests = [r.run.manifest for r in a.readers if r.source == "runtime"]
                if raws and all(any(raw in man for man in manifests) for raw in raws):
                    drop.append(k)      # present at replay start, written by nothing
                    continue
            if k.startswith(("<harness>/", "<proj>/")) and k.split("/", 1)[1] in self.tree_files:
                # a tracked file of the tree: in the harness home, or in the project when the
                # harness's own checkout is the project a script runs in (its git toplevel)
                drop.append(k)
                continue
            if _local_layer(k, self.tree_files):
                drop.append(k)          # the local layer of a tracked file: the user's or the CLI's
                continue
            if directory(k) not in written_dirs and not any(matches(p, k) or matches(k, p) for p in declared):
                drop.append(k)          # the user's or the platform's file
                continue
            if self._by_hand(k, a):
                drop.append(k)
        for k in drop:
            del m.artifacts[k]
        # artifacts whose only relations are the roles' own tool calls on the user's project
        # (product work) and that no declaration names stay outside the check
        for k in list(m.artifacts):
            a = m.artifacts[k]
            rels = a.writers + a.readers
            if rels and all(r.source == "runtime" and RUNTIME_ROLE.match(r.who) and r.who != "cli" for r in rels) \
                    and not any(matches(p, k) or matches(k, p) for p in declared):
                del m.artifacts[k]

    def _declared_patterns(self) -> list[str]:
        out = []
        for ob in self.obl:
            for art in ob.get("artifacts") or []:
                if art.get("path"):
                    out.append(art["path"])
        return sorted(set(out))

    def _text(self, rel: str) -> str:
        if rel not in self.texts:
            try:
                with open(os.path.join(self.tree, rel), encoding="utf-8", errors="replace") as fh:
                    self.texts[rel] = fh.read()
            except OSError:
                self.texts[rel] = ""
        return self.texts[rel]

    def _by_hand(self, key: str, a: Artifact) -> bool:
        """The reading code's own text says the user creates the file by hand."""
        base = re.sub(r"<[a-z*]+>", "", key.rsplit("/", 1)[-1])
        if len(base) < 4:
            return False
        # or a message of the reader's tells whoever reads it to write the file (`use --baseline
        # <sha> or write a SHA into .claude-cycle-baseline-sha`)
        told = re.compile(r"\b(?:write|create|touch|put|add)\b[^\n]{0,40}" + re.escape(base), re.I)
        name = key.rsplit("/", 1)[-1]
        for r in a.readers:
            comp = r.evidence.split(":", 1)[0] if r.source == "static" else r.who
            if not comp.startswith(("hooks/", "scripts/")):
                continue
            lines = self._text(comp).splitlines()
            for i, line in enumerate(lines):
                if base not in line and not _text_names(line, name):
                    continue
                # the sentence that names the file, which may run on to the next lines
                para = " ".join(x.strip(" #*\"'") for x in lines[i:i + 4])
                if _HAND.search(line) or told.search(line) or _HAND.search(para):
                    return True
        return False

    # ------------------------------------------------------------ declarations
    def declarations(self) -> None:
        m = self.m
        for ob in self.obl:
            for art in ob.get("artifacts") or []:
                pat = art.get("path")
                if not pat:
                    continue
                hits = [k for k, a in m.artifacts.items() if a.kind == "file" and (k == pat or matches(pat, k))]
                if not hits:
                    hits = [pat]
                    m.art(pat)
                for k in hits:
                    rec = {"role": _bound_role(ob.get("role"), art.get("template") or "", k), "site": ob["site"],
                           "schema": art.get("schema") or ""}
                    if rec not in m.artifacts[k].declared:
                        m.artifacts[k].declared.append(rec)
        # D21: the obligation that declares a file names its producer. A role writes it with its
        # own tool call, which no code site holds and a replay of another pipeline never makes;
        # where neither a trace event nor a code site shows a writer, the declared role is it
        # (G2 checks the file at that role's stop).
        for k, a in m.artifacts.items():
            if a.kind == "file" and not a.writers and not any(k == d or matches(d, k) for d in self.dirs):
                # (a declared directory, which code tests as one, is no file: its files are)
                for d in sorted(a.declared, key=lambda d: (d["role"] or "", d["site"])):
                    if d.get("role"):
                        a.writers.append(Rel("agent:" + d["role"], "write", d["site"], "declaration"))

    def owner_outputs(self) -> None:
        """E12: a path an owner-facing output shows has the owner as a reader. A script's output
        its caller writes into a file (`bash x | sed >> "$LOG"`) reaches the owner when that file
        is the owner's to read: an owner-facing output names it (the landing's notice names
        logs/landing.log, which holds what the landing's steps print)."""
        recs = [r for r in self.recs if r["kind"] == "owner_output" and r.get("reaches")]
        for r in recs:
            if not r["reaches"].startswith("into:"):
                self._owner_shown(r)
        for r in recs:
            into = r["reaches"][len("into:"):] if r["reaches"].startswith("into:") else None
            if into and any(x.who == "owner" for k, a in self.m.artifacts.items()
                            if k == into or matches(into, k) for x in a.readers):
                self._owner_shown(r)

    def _owner_shown(self, r: dict) -> None:
        m = self.m
        shown = r["shown"]
        if shown.startswith("~/"):
            shown = "<home>/" + shown[2:]
        pat = shown if shown.startswith(("<", "/")) else P.to_pattern(shown)[0]
        if pat.startswith("<home>/.claude/"):
            pat = "<harness>" + pat[len("<home>/.claude"):]
        # a shown path as a person reads it: a glob (`logs/fswatch-*.log`) names each file it
        # matches, and an upper-case name (`fswatch-REPO_NAME.pid`) is a value the reader fills in
        pat = re.sub(r"(?<![<\w])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![\w>])", "<*>", pat)
        pat = re.sub(r"(?<!<)\*(?!>)", "<*>", pat)
        if not self._specific(pat):
            return      # a shown path with no file name of its own names no file
        pats = [pat]
        if not shown.startswith(("<", "/")):
            # a relative path is relative to where the emitting code runs: the file of that
            # path its own code writes or reads (land runs in the harness home and shows
            # logs/landing.log)
            comp = comp_identity(r["component"])
            tail = "/" + pat.split("/", 1)[1]
            own = [k for k, a in m.artifacts.items() if a.kind == "file" and k.endswith(tail)
                   and any(comp in (x.who, x.via) for x in a.writers + a.readers)]
            pats = own or pats
        for k, a in m.artifacts.items():
            if a.kind != "file":
                continue
            if any(k == p or matches(p, k) for p in pats):
                rel = Rel("owner", "read", r["site"], "owner", via=r["channel"])
                if not any(x.who == "owner" and x.evidence == r["site"] for x in a.readers):
                    a.readers.append(rel)

    def platform_installs(self) -> None:
        """Rule (1)'s platform files the other way round: a file a component installs by copying
        it into the operating system's own tree (an absolute path under none of the roots the
        harness works in: its home, the user's home, the project, the state and temp dirs) is
        there for the platform that loads files from that place (a unit file in systemd's
        directory), which is its consumer, as the CLI is the consumer of the project settings
        the harness writes (row 16)."""
        for r in self.recs:
            if r["kind"] != "relation" or r["op"] != "write" or r.get("via") not in ("cp", "install"):
                continue
            pat = r["path"]
            if not pat.startswith("/") or pat.startswith(_OS_TEMP_ROOTS):
                continue
            a = self.m.artifacts.get(pat)
            if a is not None and a.kind == "file" and not any(x.who == "platform" for x in a.readers):
                a.readers.append(Rel("platform", "read", r["site"], "platform"))

    # ------------------------------------------------------------ deciding (rules 3-6)
    def deciding(self) -> None:
        m = self.m
        # E1's differential
        for run in self.runs:
            for u in (run.differential or {}).get("units", []):
                inv = run.invocations.get(u["seq"]) or {}
                targets = _targets(inv)
                art_reads = {r["raw"] for r in u["runs"]}
                exact_targets = bool(targets) and art_reads and art_reads <= targets
                for r in u["runs"]:
                    key = runtime_pattern(r["pattern"], run.env)
                    a = m.artifacts.get(key)
                    if a is None:
                        continue
                    for reader in r["readers"]:
                        rk = (os.path.normpath(reader), key)
                        rec = self.measured.setdefault(rk, {"changed": set(), "settings": set(), "reproduced": False})
                        rec["settings"].add(run.settings)
                        if u.get("reproduced"):
                            rec["reproduced"] = True
                        if not r["changed"]:
                            continue
                        if exact_targets and r["how"] != "invalid":
                            continue    # rule (3): a call's own targets count on a content change only
                        rec["changed"].add((run.settings, r["how"]))
                        pos = self._position(a, u["event"], u.get("tool"), u.get("agent_type"), u["origin"],
                                             u["kind"])
                        a.decisions.append(Decision(
                            os.path.normpath(reader), pos, f"{run.name}#{u['seq']}:{u['event']}:{u['label']}",
                            "differential", r["how"], run.settings, u["event"], u.get("tool") or u.get("agent_type") or "",
                            rule=self._rule_id(os.path.normpath(reader), key)))
        self._target_reads()
        # E1's fallback: a static branch to an exit or a block on a read, for readers not measured
        rt = sorted(self.rt_keys)
        rels = [r for r in self.recs if r["kind"] == "relation"]
        content = {(r["site"], r["path"]) for r in rels if _content_relation(r)}
        names_only = {(r["site"], r["path"]) for r in rels if not _content_relation(r)} - content
        for d in self.recs:
            if d["kind"] != "deciding" or d["evidence"] not in ("branch", "except", "assert"):
                continue
            if (d["read_site"], d["path"]) in names_only:
                continue    # a branch on a directory test or a listing reads no file (rule (3))
            if not (d["decision"] in ("exit2", "block") or d["decision"] == "exit" and d.get("code") not in (0, None)):
                continue
            pat = d["path"]
            if d["resolution"] == "unresolved":
                continue
            if pat in self.moved:
                keys = self.moved[pat]      # a name rule (1)'s root aliases joined to its file
            else:
                key = self._join(pat, rt) or (pat if pat in m.artifacts else None)
                if key is not None and key not in m.artifacts:
                    continue
                if key is None:
                    hits = [k for k in m.artifacts if "<*>" in pat and matches(pat, k)]
                    key = hits[0] if len(hits) == 1 else None
                if key is None:
                    continue
                keys = [key]
            for key in keys:
                self._static_decision(d, key)

    def _static_decision(self, d: dict, key: str) -> None:
        a = self.m.artifacts[key]
        who = comp_identity(d["component"])
        meas = self.measured.get((who, key))
        if meas and meas["reproduced"]:
            return      # the differential measured this reader on this artifact
        settings = "static-armed" if d["component"] in self.switched() else "static"
        for event, matcher in self._registrations(d["component"]):
            pos = self._position(a, event, None, None, who, "static", matcher=matcher)
            a.decisions.append(Decision(who, pos, d["decision_site"], "static", "any", settings, event,
                                        matcher or "", rule=self._static_rule(d)))
        if not any(x.who == who and x.op == "read" for x in a.readers):
            a.readers.append(Rel(who, "read", d["read_site"], "static"))

    def _loaded_names(self) -> set:
        """Module stems and file names some hook or script imports or sources."""
        key = ("loaded",)
        if key not in self.texts:
            names = set()
            for f in sorted(self.tree_files):
                if not f.startswith(("hooks/", "scripts/")):
                    continue
                text = self._text(f)
                names |= set(re.findall(r"(?:^|[\s;&|])(?:source|\.)\s+\S*?([\w.-]+\.sh)\b", text))
                for mm in re.finditer(r"^\s*(?:from\s+([\w.]+)\s+import\s+([\w, ]+)|import\s+([\w., ]+))", text, re.M):
                    for part in re.split(r"[\s,.]+", " ".join(x for x in mm.groups() if x)):
                        if part:
                            names.add(part)
            self.texts[key] = names
        return self.texts[key]

    def is_library(self, component: str) -> bool:
        """Code other components load and nothing runs on its own: its decisions take the position
        of the caller (rule (5) is the caller's)."""
        if not component.startswith(("hooks/", "scripts/")) or self._registrations(component) != [("", "")]:
            return False
        key = ("sourced",)
        if key not in self.texts:
            self.texts[key] = {re.sub(r"^(<[a-z*]+>/|/)", "", r["path"]) for r in self.recs
                               if r["kind"] == "relation" and r.get("mode") == "source"}
        if component in self.texts[key]:
            return True     # loaded by path (source, SourceFileLoader)
        base = component.rsplit("/", 1)[-1]
        stem = base[:-3] if base.endswith(".py") else base
        return base in self._loaded_names() or stem in self._loaded_names()

    def _target_reads(self) -> None:
        """Rule (3): a hook whose artifact reads in one run are exactly the triggering tool call's
        target paths reads them only where the content mutation changes its decision."""
        m = self.m
        for run in self.runs:
            reads: dict = {}
            for a in m.artifacts.values():
                for r in a.readers:
                    if r.source == "runtime" and getattr(r, "run", None) is run and r.via:
                        reads.setdefault((r.via, r.seq), set()).add(r.raw)
            exact = set()
            for (origin, seq), raws in reads.items():
                targets = _targets(run.invocations.get(seq) or {})
                if targets and raws <= targets:
                    exact.add((origin, seq))
            if not exact:
                continue
            for key, a in m.artifacts.items():
                keep = []
                for r in a.readers:
                    if r.source == "runtime" and getattr(r, "run", None) is run and (r.via, r.seq) in exact:
                        meas = self.measured.get((r.who, key)) or {}
                        if not any(how == "invalid" for _s, how in meas.get("changed", ())):
                            continue
                    keep.append(r)
                a.readers = keep

    def switched(self) -> set:
        """Hooks whose gate switch (settings.json env, read by the hook) the armed copy sets to
        another value than the tree's settings.json: they decide only armed (E4)."""
        key = ("switched",)
        if key not in self.texts:
            shipped = next((r.env for r in self.runs if r.settings == "shipped" and r.env), None)
            armed = next((r.env for r in self.runs if r.settings == "armed" and r.env), None)
            out = set()
            if shipped is not None and armed is not None:
                for sw in self.switches:
                    if shipped.get(sw["name"]) != armed.get(sw["name"]):
                        out |= {rd["hook"] for rd in sw.get("readers") or []}
            self.texts[key] = out
        return self.texts[key]

    def _registrations(self, component: str) -> list[tuple]:
        out = [(r["event"], r["matcher"]) for r in self.regs if r.get("component") == component]
        return out or [("", "")]

    def _static_rule(self, d: dict) -> str:
        through = d.get("through") or []
        return (through[-1] if through else d["read_site"])

    def _rule_id(self, reader: str, key: str) -> str:
        """The code identity of a reader's deciding read: its static deciding read site, when the
        static half finds exactly one read site of that artifact in that component's code."""
        ck = ("rule", reader, key)
        if ck not in self.texts:
            if ("dec_by",) not in self.texts:
                by: dict = {}
                for d in self.recs:
                    if d["kind"] == "deciding":
                        by.setdefault(comp_identity(d["component"]), []).append(d)
                self.texts[("dec_by",)] = by
            sites = {self._static_rule(d) for d in self.texts[("dec_by",)].get(reader, ())
                     if d["path"] == key or matches(d["path"], key)}
            self.texts[ck] = sorted(sites)[0] if len(sites) == 1 else reader
        return self.texts[ck]

    def _runners(self, script: str) -> set:
        """Who runs a script, from the command and agent text that names it (main, agent:<role>)."""
        key = ("runners", script)
        if key not in self.texts:
            out = set()
            name = script.split("/", 1)[-1] if script.startswith("scripts/") else script
            for f in sorted(self.tree_files):
                mm = re.match(r"^(commands|agents)/([^/]+)\.md$", f)
                if mm and name in self._text(f):
                    out.add("main" if mm.group(1) == "commands" else "agent:" + mm.group(2))
            self.texts[key] = out
        return self.texts[key]

    def _producer_actors(self, a: Artifact) -> set:
        out = set()
        for w in a.writers:
            if w.who.startswith("agent:") or w.who == "main":
                out.add(w.who)
            elif w.actor:
                out.add(w.actor)
            elif w.source == "runtime":
                out.add("main")     # a hook or script outside any role's call: the session's side
            elif any(r.get("component") in (w.who, w.via) for r in self.regs):
                out.add("*")        # a registered hook writes in whichever actor's event triggers it
            else:
                out |= self._runners((w.via or w.who).split(":", 1)[0])
        for d in a.declared:
            if d.get("role"):
                out.add("agent:" + d["role"])
        return out

    def _position(self, a: Artifact, event: str, tool, agent_type, origin: str, kind: str, matcher=None) -> str:
        from tests.replay.hookrun import matches as hook_matches
        actors = self._producer_actors(a)
        origin = os.path.normpath(origin) if origin and not RUNTIME_ROLE.match(origin) else origin
        if kind == "static" and not event and origin and self.is_library(origin):
            return "library"        # its callers' positions are the ones rule (5) judges
        if origin and any(origin in (w.who, w.via) for w in a.writers):
            return "own artifact"   # a producer reading back what it wrote (its state, its cache)
        if kind == "bash" or (not event and kind == "static"):
            if os.path.normpath(origin) == self.chain_script or origin == self.chain_script:
                return "chain call"
            return "elsewhere"
        if event == "SubagentStop":
            if agent_type is not None:
                return "producer stop" if ("agent:" + agent_type) in actors or "*" in actors else "elsewhere"
            return "producer stop" if any(x.startswith("agent:") or x == "*" for x in actors) else "elsewhere"
        if event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            is_agent = tool == "Agent" if tool is not None else hook_matches(matcher, "Agent")
            if is_agent:
                return "G1" if event == "PreToolUse" else "G3"
            caller = ("agent:" + agent_type) if agent_type else ("main" if tool is not None else None)
            if caller is not None:
                return "producer tool call" if caller in actors or "*" in actors else "elsewhere"
            return "producer tool call" if actors else "elsewhere"
        if event == "Stop":
            subagent = any(x.startswith("agent:") for x in actors)
            return "completion read" if subagent else "own stop"
        return "elsewhere"

    # ------------------------------------------------------------ rule (2)
    def non_file(self) -> None:
        m = self.m
        lits = [r for r in self.recs if r["kind"] == "declared_literal"]
        # response blocks and lines
        for ob in self.obl:
            role = ob.get("role")
            for art in ob.get("artifacts") or []:
                markers = [art[k] for k in ("begin_marker", "end_marker") if art.get(k)]
                if art.get("terminal_line_regex"):
                    from .static_half import _marker_literals
                    markers += _marker_literals(art["terminal_line_regex"])
                if not markers or not role:
                    continue
                key = f"response:{role}:{markers[0]}"
                a = m.art(key, "response")
                rec = {"role": role, "site": ob["site"], "schema": art.get("schema") or ""}
                if rec not in a.declared:
                    a.declared.append(rec)
                if not any(w.who == "agent:" + role for w in a.writers):
                    a.writers.append(Rel("agent:" + role, "write", ob["site"], "declaration"))
                for lit in lits:
                    if lit["literal"] not in markers:
                        continue
                    comp = lit["component"].split("#")[0]
                    if comp == f"agents/{role}.md" or lit["site"].split("#")[0] == ob["site"]:
                        continue
                    who = comp_identity(comp)
                    if not any(x.who == who and x.evidence == lit["site"] for x in a.readers):
                        a.readers.append(Rel(who, "read", lit["site"], "static"))
                    if comp.startswith(("hooks/", "scripts/")):
                        for event, matcher in self._registrations(comp):
                            pos = self._position(a, event, None, None, who, "static", matcher=matcher)
                            d = Decision(who, pos, lit["site"], "static", "any", "static", event, matcher or "",
                                         rule=who)
                            if not any(x.who == who and x.evidence == d.evidence and x.event == event
                                       for x in a.decisions):
                                a.decisions.append(d)
        # vocabularies: an enum and the literals that copy it (rule (7) states the violation)
        for r in self.recs:
            if r["kind"] == "rule7" and r["class"] == "enum_copy":
                a = m.art(f"vocabulary:{r['schema']}{r['pointer']}", "vocabulary")
                if not a.writers:
                    a.writers.append(Rel("schema:" + r["schema"], "write", r["enum_site"], "declaration"))
                a.readers.append(Rel(comp_identity(r["component"]), "read", r["site"], "static"))
        # the task-id rule: the minting hook, and every site that templates or matches a minted id
        self._task_id_rule()
        # the chain function's stdout
        a = None
        for r in self.recs:
            if r["kind"] != "chain_call":
                continue
            if a is None:
                a = m.art("stdout:" + self.chain_script, "stdout")
                a.writers.append(Rel(self.chain_script, "write", self.chain_script + ":1", "declaration"))
            who = comp_identity(r["component"])
            a.readers.append(Rel(who, "read", r["site"], "static", via=",".join(r["uses"])))
            if set(r["uses"]) & {"fields", "status"}:
                a.decisions.append(Decision(who, "elsewhere", r["site"], "static", "any", "static",
                                            rule=r["site"], matcher=",".join(r["uses"])))

    def _task_id_rule(self) -> None:
        m = self.m
        minters = set()
        for run in self.runs:
            tasks = [v for v, k in (run.ids.get("ids") or {}).items() if k == "task"]
            if not tasks:
                continue
            first = None
            for h in sorted(run.hooks, key=lambda h: h.get("t", 0)):
                for x in h.get("hooks", []):
                    if any(t in (x.get("stdout") or "") for t in tasks):
                        first = os.path.normpath(x["hook"])
                        break
                if first:
                    break
            if first:
                minters.add(first)
        forms = [r for r in self.recs if r["kind"] in ("id_form", "id_regex")]
        if not minters and not forms:
            return
        a = m.art("rule:task-id", "rule")
        for w in sorted(minters):
            a.writers.append(Rel(w, "write", "replay", "runtime"))
        for r in forms:
            if r["kind"] == "id_form" and "<task>" not in r["form"]:
                continue
            who = comp_identity(r["component"])
            if who in minters:
                continue
            a.readers.append(Rel(who, "read", r["site"], "static", via=r.get("form") or r.get("regex") or ""))
            if r["kind"] == "id_regex" or r["component"].startswith(("hooks/", "scripts/")):
                a.decisions.append(Decision(who, "elsewhere", r["site"], "static", "any", "static", rule=who))


_STATE_ROOTS = ("<state>/", "/tmp/", "<tmpdir>/")
# the operating system's scratch trees, which are temp roots, not the system's own files
_OS_TEMP_ROOTS = ("/tmp/", "/var/tmp/", "/dev/", "/proc/")
# rule (1): a lock file folds into the file it serves; the runtime half folds the same names
# (tests/replay/trace.py), so both halves agree on what a lock is
_LOCK = re.compile(r"\.(?:lock|lck)$")


_DIR_TEST = re.compile(r"(^|\.)(is_?dir)$|^test -d$")


def _local_layer(key: str, tree_files: set) -> bool:
    """`<harness>/settings.local.json` beside the tracked settings.json: a tracked file's local
    layer, which its owner or the platform writes (the CLI records a permission approval in its
    settings' local layer); an input unless a trace event or a code site writes it."""
    m = re.match(r"^<(?:harness|proj)>/(.+?)\.local(\.[A-Za-z0-9]+)?$", key)
    return bool(m) and (m.group(1) + (m.group(2) or "")) in tree_files


def _bound_role(role, template: str, key: str):
    """D21: a template that declares its role by a placeholder its path also holds
    (role="<specialist.type>", ".../<specialist.type>-report.json": one template for every
    specialist it dispatches) declares, for each file it matches, the role that placeholder takes
    in that file's name; a role the path does not bind stays as declared."""
    if not (isinstance(role, str) and re.fullmatch(r"<[^<>]+>", role) and role in template):
        return role
    tail = re.sub(r"^<[a-z]+>/", "", key)
    parts = re.split(r"(<[^<>]+>)", template)
    rx = "".join("(?P<role>[^/<>]+?)" if p == role and "(?P<role>" not in "".join(parts[:i]) else
                 "[^/]+?" if re.fullmatch(r"<[^<>]+>", p) else re.escape(p) for i, p in enumerate(parts))
    hit = re.fullmatch(rx, tail)
    return hit.group("role") if hit else role


def _text_names(line: str, name: str) -> bool:
    """The line writes the file name `name` as a template: a path whose varying parts are
    placeholders (`claude-allow-daemon-restart-<target>.flag` names
    claude-allow-daemon-restart-default.flag), with four or more characters of its own."""
    for m in _TEXT_PATH.finditer(line):
        last = m.group(0).rsplit("/", 1)[-1]
        parts = _TEXT_HOLE.split(last)
        if len(parts) < 2 or len("".join(parts).strip(".-_")) < 4:
            continue
        rx = "[^/]+".join(re.escape(p) for p in parts)
        if re.fullmatch(rx, re.sub(r"<[a-z*]+>", "x", name)):
            return True
    return False


def _family(pattern: str) -> bool:
    """A pattern that names its file by more than one fixed name in an unknown directory: a
    varying part in the file name (overnight-state-<*>.json) or a literal directory above it
    (<*>/.claude/x.json). `<*>/.gitignore` names a file every directory may hold."""
    segs = pattern.split("/")
    return bool(re.search(r"<[a-z*]+>", segs[-1])) or any(s and "<" not in s for s in segs[1:-1])


def _named(pattern: str, least: int = 8) -> bool:
    """A pattern whose file name keeps `least` or more characters of its own beside its tokens
    and its extension: it names one family of files, not every file of a kind (claude-<*>.json,
    <*>.json)."""
    base = pattern.rsplit("/", 1)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", base)
    return len(re.sub(r"<[a-z*]+>|[-_.]", "", stem)) >= least


def _content_relation(r: dict) -> bool:
    """Rules (1) and (3): a relation to a file's content. Removing a file reads none of its
    content and writes none; a listing (a scan, with or without a name test) reads names, not
    the files it lists; a test that the path is a directory names a directory, which is no file
    artifact (the files under it are). A test of one file's existence or metadata (a flag, a
    stamp's mtime) reads what its writer left there."""
    if r["op"] == "unlink":
        return False
    if r["op"] == "read" and r.get("mode") == "list":
        return False
    return not (r["op"] == "read" and r.get("mode") == "name" and _DIR_TEST.search(r.get("via") or ""))


def _rename_sources(rels: list) -> set:
    """(component, pattern) of every file a component renames onto another path: its writes and
    reads of that path are a same-run temporary's, which fold into the destination (rule (1))."""
    out = set()
    for r in rels:
        if r["op"] == "rename":
            for src in r.get("from") or ():
                if src != r["path"]:
                    out.add((r["component"], src))
    return out


def _state_tail(key: str) -> str | None:
    """The path below the hook-state root a pattern lies under (the state dir, /tmp, TMPDIR)."""
    for root in _STATE_ROOTS:
        if key.startswith(root):
            return key[len(root):]
    return None


def _private_scratch(events: list[dict]) -> set:
    """Rule (1): raw paths one hook run (one origin, one event) creates and removes, whichever
    of its processes does each: its private scratch. A name a temp-name generator minted
    (<rand>) is known only to the run that minted it, so a file under such a name that only that
    run touched is its scratch also when the run did not remove it (a run stopped before its
    cleanup)."""
    made, gone, other, minted = {}, {}, set(), set()
    for e in events:
        run = (e["origin"], e["event"])
        if e["op"] == "create":
            made.setdefault(e["raw"], set()).add(run)
            if "<rand>" in e["pattern"]:
                minted.add(e["raw"])
        elif e["op"] == "unlink":
            gone.setdefault(e["raw"], set()).add(run)
    for e in events:
        if e["op"] in ("read", "write") and e["raw"] in made and (e["origin"], e["event"]) not in made[e["raw"]]:
            other.add(e["raw"])     # another run touched it: not private
    return {raw for raw, runs in made.items() if raw not in other and len(runs) == 1
            and (gone.get(raw) == runs or raw in minted and raw not in gone) and next(iter(runs))[0]}


def _targets(inv: dict) -> set:
    ti = ((inv.get("payload") or {}).get("tool_input")) or {}
    out = set()
    for k in ("file_path", "notebook_path", "path"):
        if isinstance(ti.get(k), str):
            out.add(ti[k])
    for e in ti.get("edits") or []:
        if isinstance(e, dict) and isinstance(e.get("file_path"), str):
            out.add(e["file_path"])
    return out


# ---------------------------------------------------------------- invariants

@dataclass
class Violation:
    rule: str
    artifact: str
    message: str
    writers: list = field(default_factory=list)
    deciders: list = field(default_factory=list)
    position: str = ""
    evidence: list = field(default_factory=list)

    def text(self) -> str:
        parts = [f"[{self.rule}] {self.artifact}: {self.message}"]
        if self.writers:
            parts.append("  writers: " + "; ".join(self.writers))
        if self.deciders:
            parts.append("  deciding readers: " + "; ".join(self.deciders))
        if self.position:
            parts.append("  position: " + self.position)
        for e in self.evidence:
            parts.append("  at " + e)
        return "\n".join(parts)

    def sort_key(self):
        return (self.rule, self.artifact, self.message, self.text())


def _ev(rels, limit=4) -> list[str]:
    out = []
    for r in sorted(rels, key=lambda r: (r.who, r.source, r.evidence)):
        s = f"{r.who} ({r.source}: {r.evidence}{'; via ' + r.via if r.via and r.via != r.who else ''})"
        if s not in out:
            out.append(s)
    return out[:limit] + ([f"... {len(out) - limit} more"] if len(out) > limit else [])


def _dec(ds, limit=6) -> list[str]:
    out = []
    for d in sorted(ds, key=lambda d: (d.who, d.position, d.settings, d.how, d.evidence)):
        s = f"{d.who} at {d.position} [{d.source} {d.settings} {d.how}: {d.evidence}]"
        if s not in out:
            out.append(s)
    return out[:limit] + ([f"... {len(out) - limit} more"] if len(out) > limit else [])


def violations(m: Map, static_records: list | None = None) -> list[Violation]:
    out: list[Violation] = []
    for key in sorted(m.artifacts):
        a = m.artifacts[key]
        prods = a.producers()
        writers_txt = [f"{p}: " + ", ".join(sorted({w.evidence for w in a.writers if w.who == p})[:3]) for p in prods]
        # goal 1 / rule (1): one producer
        producing = _producing(a)
        if len(producing) > 1:
            out.append(Violation("1-producers", key, f"{len(producing)} producers", writers_txt,
                                 evidence=_ev(a.writers, 8)))
        # D21: the producer is the role the declaring obligation names
        roles = sorted({"agent:" + d["role"] for d in a.declared if d.get("role")})
        if roles and a.kind == "file":
            others = [p for p in prods if p not in roles and not _runs_for(a, p, roles)]
            if others:
                out.append(Violation("1-declared-role", key, f"declared for {', '.join(roles)} "
                                     f"({', '.join(sorted({d['site'] for d in a.declared}))}), written by "
                                     + ", ".join(others), writers_txt, evidence=_ev([w for w in a.writers if w.who in others])))
        consumers = [c for c in a.consumers()]
        # goal 2: at least one consumer; read and never written
        if prods and not consumers and a.kind == "file":
            out.append(Violation("2-unread", key, "written and never read", writers_txt, evidence=_ev(a.writers)))
        if not prods and consumers and a.kind == "file":
            out.append(Violation("2-unwritten", key, "read and never written",
                                 evidence=_ev(a.readers)))
        # rule (4): one deciding rule per mutation
        seen_rules = set()
        for how in (("removed", "invalid") if a.kind != "stdout" else ()):
            ds = [d for d in a.decisions if d.how in (how, "any") and d.settings in ("shipped", "static")
                  and d.position != "own artifact"]
            groups = _rule_groups(ds)
            if len(groups) > 1 and tuple(groups) not in seen_rules:
                seen_rules.add(tuple(groups))
                out.append(Violation("4-one-rule", key, f"{len(groups)} deciders with rules of their own on "
                                     f"mutation '{how}': " + "; ".join(groups), writers_txt, _dec(ds, 10)))
        # rules (5) and (6): deciding reads outside the allowed positions (file artifacts; a response
        # block's or the task-id rule's second parser is rule (4)'s)
        if a.kind == "file":
            out += _rechecks(a, key, writers_txt)
        if a.kind == "stdout":
            for d in sorted(a.decisions, key=lambda d: d.evidence):
                out.append(Violation("5-chain-verbatim", key, f"{d.who} decides on the chain function's output "
                                     f"({d.matcher}) instead of using it verbatim", deciders=_dec([d]),
                                     evidence=[d.evidence]))
    out += m.extra
    # rule (7)
    for r in static_records or []:
        if r["kind"] != "rule7":
            continue
        if r["class"] == "policy_file_prefix":
            pre = r["prefix"].strip("/")
            names = [k for k, a in m.artifacts.items() if a.kind == "file" and len(pre) >= 3
                     and re.search(r"(^|/)" + re.escape(pre) + r"[^/]*$", re.sub(r"^<[a-z]+>/?|^/", "", k))]
            if not names:
                continue
            out.append(Violation("7-list", sorted(names)[0], f"tool-policy prefix {r['prefix']!r} for role "
                                 f"{r['role']} names the file of {len(names)} derived artifact(s)",
                                 evidence=[r["site"]] + sorted(names)[:3]))
            continue
        what = {"roster_list": f"names roster entries {r.get('names')}",
                "enum_copy": f"copies {r.get('schema')}{r.get('pointer')} ({r.get('match')}: {r.get('values')})",
                "path_to_role": f"maps {r.get('key')!r} to role {r.get('role')!r} (declared {r.get('declared')})"}
        out.append(Violation("7-list", r["component"], what.get(r["class"], r["class"]), evidence=[r["site"]]))
    # rule (8)
    for run in m.runs:
        st = (run.env or {}).get("CLAUDE_STATE_DIR", "")
        if not st or not st.startswith("/") or os.path.normpath(st) == "/tmp":
            out.append(Violation("8-state-dir", run.name, f"replay ran with CLAUDE_STATE_DIR={st!r}"))
    keys = sorted(m.artifacts)
    for k in keys:
        if not k.startswith("<state>/"):
            continue
        tail = _state_tail(k)
        for root in _STATE_ROOTS[1:]:
            other = m.artifacts.get(root + tail)
            if other is not None:
                a = m.artifacts[k]
                out.append(Violation("8-state-dir", k, f"also used under {root}: one file, two roots",
                                     _ev(a.writers) + _ev(other.writers), evidence=_ev(a.readers) + _ev(other.readers)))
    uniq = {}
    for v in out:
        uniq.setdefault(v.text(), v)
    return sorted(uniq.values(), key=Violation.sort_key)


def _rule_groups(ds: list) -> list[str]:
    """Deciders (components) grouped into rules: two are one rule when a deciding read of each is
    the same code site (both call the one function that reads and decides)."""
    sites: dict[str, set] = {}
    for d in ds:
        sites.setdefault(d.who, set()).add(d.rule or d.who)
    parent = {w: w for w in sites}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owners: dict[str, str] = {}
    for w in sorted(sites):
        for s in sorted(sites[w]):
            if s in owners:
                parent[find(w)] = find(owners[s])
            else:
                owners[s] = w
    groups: dict[str, list] = {}
    for w in sorted(sites):
        groups.setdefault(find(w), []).append(w)
    return sorted("+".join(g) for g in groups.values())


def _producing(a: Artifact) -> list[str]:
    """Rule (1)'s producers of an artifact, each counted once:
    - a script or hook whose every write of a declared artifact ran inside the call of the role
      the declaration names (the fan-out's aggregate, written by the hook the lane's dev report
      sets off; QA's close-report section, appended by the helper QA runs) is that role's write
      path, not a producer of its own (D21: the declared role owns it, and G2 returns it there);
    - a file of the user's project that was there at replay start, that no declaration names and
      no harness code writes, and that only the roles' own tool calls write, is the task's work
      product, whichever role the command gives the work (dev under /dev, the main agent under
      /do or in a session with no command): one producer, the task's work."""
    prods = a.producers()
    roles = sorted({"agent:" + d["role"] for d in a.declared if d.get("role")})
    if roles and a.kind == "file":
        mapped = set()
        for p in prods:
            if p not in roles and _runs_for(a, p, roles):
                acts = {w.actor for w in a.writers if w.who == p and w.source == "runtime"}
                mapped |= acts
            else:
                mapped.add(p)
        prods = sorted(mapped)
    if len(prods) > 1 and a.kind == "file" and a.key.startswith("<proj>/") and not a.declared and a.writers and all(
            w.source == "runtime" and RUNTIME_ROLE.match(w.who) and w.who != "cli"
            and getattr(w, "raw", None) and w.raw in getattr(getattr(w, "run", None), "manifest", ())
            for w in a.writers):
        return ["the task's work (" + ", ".join(prods) + ")"]
    return prods


def _runs_for(a: Artifact, producer: str, roles: list[str]) -> bool:
    """A script or hook writing a declared artifact counts as the declared role's own when every
    such write ran inside that role's call."""
    ws = [w for w in a.writers if w.who == producer]
    return bool(ws) and all(w.actor in roles for w in ws if w.source == "runtime") and \
        any(w.source == "runtime" for w in ws)


def _rechecks(a: Artifact, key: str, writers_txt: list) -> list[Violation]:
    out = []
    outside = [d for d in a.decisions if d.position not in ALLOWED]
    if not outside:
        return out
    side = [d for d in a.decisions if d.position in ("producer stop", "producer tool call", "G1", "G3")]

    def rejects(how: str, settings: str) -> bool:
        ok = ("shipped", "static") if settings == "shipped" else ("armed", "static", "static-armed")
        return any(d.settings in ok and (how == "any" or d.how in (how, "any")) for d in side)

    groups: dict[tuple, list] = {}
    for d in outside:
        if d.settings in ("armed", "static-armed"):
            continue    # rule (6) classifies the shipped decision; the armed run only answers "who else stops it"
        groups.setdefault((d.who, d.position, d.how), []).append(d)
    for (who, position, how), ds in sorted(groups.items()):
        shipped = rejects(how, "shipped")
        armed = rejects(how, "armed")
        sites = sorted({d.evidence for d in ds})
        if shipped:
            out.append(Violation("6-recheck", key, f"re-check by {who}: the producer side rejects mutation '{how}' "
                                 f"with the tree's switches", writers_txt, _dec(ds), position,
                                 evidence=sites[:6] + _dec([x for x in side if x.settings in ("shipped", "static")], 4)))
        elif armed:
            continue    # E4: the fault's only stop while its gate is advisory (listed by the map)
        else:
            out.append(Violation("6-move", key, f"{who} decides outside the allowed positions and no gate rejects "
                                 f"mutation '{how}' even armed: a rule to move into the gate, or a use",
                                 writers_txt, _dec(ds), position, evidence=sites[:6]))
    return out


# ---------------------------------------------------------------- the map as text

def advisory_copies(m: Map) -> list[str]:
    """Deciding reads outside the allowed positions whose mutation only an armed gate rejects (E4)."""
    out = []
    for key in sorted(m.artifacts):
        a = m.artifacts[key]
        side = [d for d in a.decisions if d.position in ("producer stop", "producer tool call", "G1", "G3")]
        for d in a.decisions:
            if d.position in ALLOWED or d.settings not in ("shipped", "static"):
                continue
            ship = any(x.settings in ("shipped", "static") and x.how in (d.how, "any") for x in side)
            arm = any(x.settings in ("armed", "static-armed") and x.how in (d.how, "any") for x in side)
            if arm and not ship:
                gates = sorted({x.who + " at " + x.position for x in side if x.settings in ("armed", "static-armed")})
                out.append(f"{key}: {d.who} at {d.position} ({d.how}) is the fault's only stop while "
                           f"{', '.join(gates)} is advisory")
    return sorted(set(out))


def map_text(m: Map, vs: list[Violation]) -> str:
    by_art: dict[str, list] = {}
    for v in vs:
        by_art.setdefault(v.artifact, []).append(v)
    lines = [f"# Artifact map of {os.path.basename(m.tree.rstrip('/')) or m.tree}",
             f"# {len(m.artifacts)} artifacts; {len(vs)} violations; runs: "
             + ", ".join(sorted(r.name for r in m.runs)), ""]
    for key in sorted(m.artifacts):
        a = m.artifacts[key]
        lines.append(f"## {key}" + (f"  [{a.kind}]" if a.kind != "file" else ""))
        lines.append("producers: " + ("; ".join(f"{p} [{_first(a.writers, p)}]" for p in a.producers()) or "-"))
        lines.append("readers: " + (", ".join(a.consumers()) or "-"))
        ds = sorted({(d.who, d.position) for d in a.decisions if d.settings in ("shipped", "static")})
        lines.append("deciding: " + ("; ".join(
            f"{w} at {p} [{min(d.evidence for d in a.decisions if d.who == w and d.position == p)}]"
            for w, p in ds) or "-"))
        if a.declared:
            lines.append("declared: " + ", ".join(sorted({f"{d['role']} {d['site']}" for d in a.declared})))
        for v in by_art.get(key, []):
            lines.append(f"VIOLATION [{v.rule}] {v.message}")
        lines.append("")
    rest = [v for v in vs if v.artifact not in m.artifacts]
    if rest:
        lines.append("## violations outside the artifacts")
        for v in rest:
            lines.append(f"VIOLATION [{v.rule}] {v.artifact}: {v.message} " + " ".join(v.evidence[:2]))
        lines.append("")
    return "\n".join(lines)


def _first(rels: list, who: str) -> str:
    """The first evidence of each source for one component: a trace event and a code site."""
    out = []
    for src in ("runtime", "static", "declaration", "owner"):
        ev = sorted(r.evidence for r in rels if r.who == who and r.source == src)
        if ev:
            out.append(ev[0] + (f" +{len(ev) - 1}" if len(ev) > 1 else ""))
    return "; ".join(out)


def chunks(text: str, limit: int = 60000) -> list[str]:
    """Split the map into PR-comment-sized parts at artifact boundaries (UTF-8 bytes)."""
    parts, cur = [], ""
    for block in text.split("\n\n"):
        piece = block + "\n\n"
        if cur and len((cur + piece).encode("utf-8")) > limit - 200:
            parts.append(cur)
            cur = ""
        while len(piece.encode("utf-8")) > limit - 200:
            cut = piece.encode("utf-8")[: limit - 300].decode("utf-8", "ignore")
            parts.append(cut + "\n")
            piece = piece[len(cut):]
        cur += piece
    if cur.strip():
        parts.append(cur)
    n = len(parts)
    return [f"<!-- part {i + 1}/{n} -->\n```\n{p.rstrip()}\n```\n" for i, p in enumerate(parts)]


def counts(m: Map, vs: list[Violation]) -> dict:
    by_rule: dict[str, int] = {}
    for v in vs:
        by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
    prod_dist: dict[int, int] = {}
    for a in m.artifacts.values():
        n = len(a.producers())
        prod_dist[n] = prod_dist.get(n, 0) + 1
    kinds: dict[str, int] = {}
    for a in m.artifacts.values():
        kinds[a.kind] = kinds.get(a.kind, 0) + 1
    positions: dict[str, int] = {}
    for a in m.artifacts.values():
        for pos in {(d.who, d.position) for d in a.decisions if d.settings in ("shipped", "static")}:
            positions[pos[1]] = positions.get(pos[1], 0) + 1
    evidence: dict[str, int] = {}
    for a in m.artifacts.values():
        srcs = {r.source for r in a.writers + a.readers}
        k = ("code and trace" if "runtime" in srcs and srcs - {"runtime"} else "trace only" if "runtime" in srcs
             else "code only")
        evidence[k] = evidence.get(k, 0) + 1
    with_v = {v.artifact for v in vs}
    return {"artifacts": len(m.artifacts), "artifacts_by_kind": dict(sorted(kinds.items())),
            "violations": len(vs), "violations_by_rule": dict(sorted(by_rule.items())),
            "artifacts_with_violations_by_rule": {r: len({v.artifact for v in vs if v.rule == r})
                                                  for r in sorted(by_rule)},
            "artifacts_without_violation": sum(1 for k in m.artifacts if k not in with_v),
            "producers_per_artifact": {str(k): v for k, v in sorted(prod_dist.items())},
            "deciding_positions": dict(sorted(positions.items())),
            "evidence": dict(sorted(evidence.items())),
            "runtime_artifacts": sum(1 for a in m.artifacts.values() if a.runtime)}


# ---------------------------------------------------------------- E1's measurement

def e1_recall(m: Map, static_records: list) -> dict:
    """On the artifacts the runtime trace sees: how many runtime producers, readers and deciding
    consumers the static half finds too (same component, a static pattern matching the artifact)."""
    rels = [r for r in static_records if r["kind"] == "relation" and r["resolution"] != "unresolved"]
    dec = [r for r in static_records if r["kind"] == "deciding" and r["resolution"] != "unresolved"]
    by_comp: dict = {}
    for r in rels:
        op = "write" if r["op"] in ("write", "create", "rename") else "read" if r["op"] == "read" else None
        if op:
            by_comp.setdefault((comp_identity(r["component"]), op), set()).add(r["path"])
    dec_by: dict = {}
    for d in dec:
        dec_by.setdefault(comp_identity(d["component"]), set()).add(d["path"])

    def found(pats, key):
        return any(p == key or matches(p, key) for p in pats or ())

    comps = sorted({c for c, _op in by_comp})
    loads: dict = {}

    def static_of(proc: str, op: str) -> set:
        """Static patterns of the process's own code and of the libraries it loads."""
        if proc not in loads:
            loads[proc] = [c for c in comps if c != proc and m.ctx is not None and m.ctx._loads(proc, c)]
        out = set(by_comp.get((proc, op), ()))
        for c in loads[proc]:
            out |= by_comp.get((c, op), set())
        return out

    out = {}
    for name, op in (("producers", "write"), ("readers", "read")):
        pairs = set()
        for key, a in m.artifacts.items():
            if not a.runtime:
                continue
            for r in (a.writers if op == "write" else a.readers):
                if r.source == "runtime" and r.proc and not RUNTIME_ROLE.match(r.proc):
                    pairs.add((r.proc, key))
        hit = sum(1 for who, key in pairs if found(static_of(who, op), key))
        out[name] = {"runtime": len(pairs), "static_found": hit,
                     "recall": round(hit / len(pairs), 3) if pairs else None}
    pairs = {(d.who, k) for k, a in m.artifacts.items() for d in a.decisions
             if d.source == "differential" and d.settings == "shipped"}
    hit = sum(1 for who, key in pairs if found(dec_by.get(who), key))
    out["deciding"] = {"runtime": len(pairs), "static_found": hit, "recall": round(hit / len(pairs), 3) if pairs else None}
    return out


def static_only_sample(m: Map, n: int = 60, seed: int = 19) -> list[str]:
    """A fixed random sample of static-only edges (for E1's hand-checked precision)."""
    import random
    edges = sorted({f"{r.who}\t{r.op}\t{k}\t{r.evidence}" for k, a in m.artifacts.items()
                    for r in a.writers + a.readers if r.source == "static"})
    rnd = random.Random(seed)
    return sorted(rnd.sample(edges, min(n, len(edges))))


# ---------------------------------------------------------------- command line

def schemas_for(static_records: list) -> dict:
    """pattern -> schemas/<id>.json, from the obligations that declare a path with a schema."""
    files = {r["id"]: r["site"].split(":")[0] for r in static_records
             if r["kind"] == "declaration" and r.get("type") == "schema"}
    out = {}
    for r in static_records:
        if r["kind"] == "declaration" and r.get("type") == "obligation":
            for art in r.get("artifacts") or []:
                if art.get("path") and art.get("schema") in files:
                    out[art["path"]] = files[art["schema"]]
    return out


def run_check(tree: str, work: str, *, jobs: int = 4, budget_s: float = 1500.0, replays: bool = True,
              differential: bool = True, settings=("shipped", "armed"), only: list | None = None,
              log=print) -> dict:
    """The whole check on `tree`: static half, replays, differential, derivation, invariants.
    With replays=False the replays under `work` are reused (their sandboxes keep their final
    state, so the differential can still run on them); with differential=False the differential
    results already under `work` are used. Writes under `work`: static.jsonl, runs/, sb/,
    check.json, violations.txt, map.txt, map-comments/, advisory-copies.txt, e1-sample.tsv."""
    from . import runtime as RT
    from .static_half import derive as static_derive
    from tests.replay import differential as D
    tree = os.path.abspath(tree)
    os.makedirs(work, exist_ok=True)
    timing = {}
    t0 = time.monotonic()
    static = static_derive(tree)
    timing["static_s"] = round(time.monotonic() - t0, 1)
    with open(os.path.join(work, "static.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(static.jsonl())
    log(f"static half: {len(static.records)} records in {timing['static_s']} s")
    pairs = RT.drivers()
    if only:
        pairs = [p for p in pairs if p[0] in only or f"{p[0]}~{p[1]}" in only]
    jl = RT.jobs_for(work, pairs, settings)
    if replays:
        t0 = time.monotonic()
        RT.replay_all(tree, jl, jobs)
        timing["replays_wall_s"] = round(time.monotonic() - t0, 1)
        for j in jl:
            RT.save_job(j)
            log(f"replay {j.label} {j.settings}: rc {j.rc}, {j.wall_s} s {j.error}")
    else:
        jl = [RT.load_job(j.out) or j for j in jl]
        # the replays ran earlier, `jobs` at a time: their wall time as they were scheduled
        timing["replays_wall_s"] = round(sum(j.wall_s for j in jl) / max(1, jobs), 1)
    timing["replays_sum_s"] = round(sum(j.wall_s for j in jl), 1)
    schemas = schemas_for(static.records)
    if differential:
        units = {j.out: D.candidates(j.run_dir) if os.path.isdir(j.run_dir) else [] for j in jl}
        for j in jl:
            if j.settings != "shipped" and units[j.out]:
                units[j.out] = outside_units(j.run_dir, units[j.out], inside=True)
        total = sum(D.run_count(u) for u in units.values())
        # E2's budget counts the replays; E1's fallback cuts the differential to the readers
        # outside the allowed positions when the estimate does not fit
        est = _estimate(jl, units)
        left = budget_s - timing.get("replays_wall_s", 0) - timing["static_s"]
        mode = "full"
        if est / max(1, jobs) > left:
            mode = "fallback"
            for j in jl:
                # the readers outside the allowed positions, with the tree's switches; the producer
                # side's decisions, armed or not, come from its static branches and their switches
                units[j.out] = outside_units(j.run_dir, units[j.out]) if j.settings == "shipped" else []
        timing["differential_planned_runs"] = total
        timing["differential_estimate_s"] = round(est, 1)
        timing["differential_budget_left_s"] = round(left, 1)
        timing["differential_mode"] = mode
        timing["differential_selected_runs"] = sum(D.run_count(u) for u in units.values())
        t0 = time.monotonic()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            list(ex.map(lambda j: RT.differential(j, units[j.out], run_schemas(j.run_dir, units[j.out], schemas), 1)
                        if units[j.out] else j, jl))
        timing["differential_wall_s"] = round(time.monotonic() - t0, 1)
        timing["differential_runs"] = sum(j.diff_runs for j in jl)
        for j in jl:
            if os.path.isdir(j.out):    # with reuse, a driver added since has no replay to record
                RT.save_job(j)
    runs = []
    for j in jl:
        if os.path.isfile(os.path.join(j.run_dir, "relations.tsv")):
            runs.append(load_run(j.label, j.settings, j.run_dir))
    t0 = time.monotonic()
    m = derive(tree, static, runs)
    vs = violations(m, static.records)
    timing["derive_s"] = round(time.monotonic() - t0, 1)
    m.measures = {"e1": e1_recall(m, static.records), "timing": timing,
                  "jobs": [j.to_json() for j in jl]}
    c = counts(m, vs)
    text = map_text(m, vs)
    with open(os.path.join(work, "map.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)
    cdir = os.path.join(work, "map-comments")
    os.makedirs(cdir, exist_ok=True)
    for f in os.listdir(cdir):
        os.unlink(os.path.join(cdir, f))
    for i, part in enumerate(chunks(text), 1):
        with open(os.path.join(cdir, f"part-{i:02d}.md"), "w", encoding="utf-8") as fh:
            fh.write(part)
    with open(os.path.join(work, "violations.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(v.text() for v in vs) + ("\n" if vs else ""))
    with open(os.path.join(work, "advisory-copies.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(advisory_copies(m)) + "\n")
    with open(os.path.join(work, "e1-sample.tsv"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(static_only_sample(m)) + "\n")
    result = {"tree": tree, "counts": c, "measures": m.measures,
              "errors": [j.error for j in jl if j.error]}
    with open(os.path.join(work, "check.json"), "w") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    result["violations"] = vs
    result["map"] = m
    return result


def run_schemas(run_dir: str, units: list[dict], schemas: dict) -> dict:
    """The schema of each runtime pattern a unit reads: the one its declaring obligation names."""
    try:
        with open(os.path.join(run_dir, "env.json")) as fh:
            env = json.load(fh)
    except (OSError, ValueError):
        env = {}
    out = {}
    for u in units:
        for r in u["reads"]:
            key = runtime_pattern(r["pattern"], env)
            hits = sorted({f for p, f in schemas.items() if p == key or matches(p, key)})
            if len(hits) == 1:
                out[r["pattern"]] = hits[0]
    return out


def outside_units(run_dir: str, units: list[dict], inside: bool = False) -> list[dict]:
    """E1's fallback: keep only the reads at a position outside the allowed ones (rule (5)),
    judged from the run's own writers: not the stopping agent's or the calling actor's own
    artifact, not G1 or G3, not the reader's own artifact. inside=True keeps the complement:
    the producer side's reads, all an armed replay's differential has to measure (rule (6) asks
    only whether the producer side rejects a mutation when armed)."""
    from tests.replay import differential as D
    events = D.load_events(run_dir)
    invs = D.load_invocations(run_dir)
    actors: dict[str, set] = {}
    writers: dict[str, set] = {}
    for e in events:
        if e["op"] in ("write", "create") or e["op"] == "rename":
            pat = e["pattern"].split(" -> ", 1)[-1]
            inv = invs.get(e["event"]) or {}
            p = inv.get("payload") or {}
            actors.setdefault(pat, set()).add(e["actor"] or (("agent:" + p["agent_type"]) if p.get("agent_type")
                                                               else "main"))
            writers.setdefault(pat, set()).update({e["comp"], e["origin"]})
    out = []
    for u in units:
        caller = ("agent:" + u["agent_type"]) if u.get("agent_type") else "main"
        keep = []
        for r in u["reads"]:
            ws, acts = writers.get(r["pattern"], set()), actors.get(r["pattern"], set())
            allowed = (r["comp"] in ws or u["origin"] in ws
                       or u["event"] in ("PreToolUse", "PostToolUse") and u.get("tool") == "Agent"
                       or u["event"] in ("SubagentStop", "PreToolUse", "PostToolUse", "PostToolUseFailure")
                       and caller in acts)
            if allowed == inside:
                keep.append(r)
        if keep:
            out.append(dict(u, reads=keep))
    return out


def _estimate(jobs, units) -> float:
    """Seconds the differential would take: each planned run at its hook's recorded mean time."""
    from tests.replay import differential as D
    total = 0.0
    for j in jobs:
        ms: dict[str, list] = {}
        try:
            with open(os.path.join(j.run_dir, "hooks.jsonl")) as fh:
                for line in fh:
                    for h in json.loads(line)["hooks"]:
                        ms.setdefault(os.path.normpath(h["hook"]), []).append(h["ms"])
        except OSError:
            pass
        for u in units.get(j.out, []):
            per = ms.get(u["origin"]) or [500]
            mean = sum(per) / len(per) / 1000 + 0.05
            total += mean * (1 + len(D.MUTATIONS) * len({r["raw"] for r in u["reads"]}))
    return total


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m tests.artifact_graph.check", description=__doc__.split("\n")[0])
    ap.add_argument("--tree", required=True, help="the harness tree to check (working tree or a clone)")
    ap.add_argument("--work", required=True, help="output directory, outside the repository and the tree")
    ap.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    ap.add_argument("--budget-s", type=float, default=1500.0, help="E2's time budget for the job (seconds)")
    ap.add_argument("--reuse", action="store_true", help="reuse the replays already under --work")
    ap.add_argument("--no-differential", action="store_true",
                    help="use the differential results already under --work instead of running it")
    ap.add_argument("--only", action="append", default=[], help="driver or driver~variant (repeatable)")
    ap.add_argument("--show", type=int, default=0, help="print at most N violations (0: all)")
    a = ap.parse_args(argv)
    from tests.replay.cli import _outside_repo
    work = _outside_repo(a.work, a.tree)
    if not a.reuse:
        from . import runtime as RT
        missing = RT.preconditions()
        if missing:
            print("the check's replays cannot run: " + "; ".join(missing), file=sys.stderr)
            return 2
    res = run_check(a.tree, work, jobs=a.jobs, budget_s=a.budget_s, replays=not a.reuse,
                    differential=not a.no_differential, only=a.only or None)
    vs = res["violations"]
    for v in vs[: a.show or len(vs)]:
        print(v.text())
    print(json.dumps({"counts": res["counts"], "e1": res["measures"]["e1"], "timing": res["measures"]["timing"],
                      "errors": res["errors"]}, indent=1, sort_keys=True))
    parts = len(os.listdir(os.path.join(work, "map-comments")))
    print(f"map: {work}/map.txt ({parts} PR-comment parts in {work}/map-comments/); "
          f"violations: {work}/violations.txt; advisory copies (E4): {work}/advisory-copies.txt")
    return 1 if vs or res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
