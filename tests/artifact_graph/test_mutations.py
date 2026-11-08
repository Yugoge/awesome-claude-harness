"""P1b acceptance 3: the artifact check fails when it should (mutation tests).

Each test copies the tree under test (this checkout) to a scratch directory,
applies one mutation to the copy and runs the check on it: the static half on
the mutated copy, and the derivation and invariants of tests/artifact_graph/
check.py over the unmutated run's traced replays (ARTIFACT_GRAPH_WORK, the
directory the full check left them in; CI's job "artifact check (traced
replays)" runs this module after tests/test_artifact_graph.py over the shards'
replays it downloaded): the check's `--reuse --no-differential` path, run
in-process without writing the map. The test passes only when the mutated check
fails (it reports a violation, so `check.py` exits non-zero) with a violation
the unmutated check does not report, of the rule the mutation breaks, naming
the artifact, the mutated component and its file:line.

Every mutation's target comes from what the check derives on the unmutated tree
at test time (its artifacts, their writers and deciding readers, the
declarations it reads): no artifact, role, hook or schema is named here, and
nothing is compared with a committed map.

A mutation reruns only what it can change. Each one adds a single new file
under hooks/ or scripts/, which nothing in the unmutated tree runs: no hook
registration, command block, agent file or script names it, so no step of any
replayed pipeline reaches it, and the unmutated run's traces stand for every
pipeline (no replay is needed; the test asserts that no replay ran the file).
What it changes is the static half, which runs whole on the mutated copy. The
mutations run ARTIFACT_GRAPH_JOBS at a time (default the CPU count up to 4),
each in a worker process that loads the replays once; each test prints its
mutation's time, which E2's budget counts.

Like tests/test_artifact_graph.py, a test that cannot run fails with its
reason, never skips: without ARTIFACT_GRAPH_WORK, or with a planned replay
missing there, every test below fails. The baseline job's plain pytest step
leaves this module to that job (`--ignore=tests/artifact_graph/test_mutations.py`).
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from multiprocessing import get_context
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache", "node_modules")
# the roots of the check's path patterns (tests/artifact_graph/patterns.py) as the environment
# names them (pyscan.ENV_ROOTS): the code a mutation adds reaches a derived artifact under its root
_ROOT_ENV = {"<state>": "CLAUDE_STATE_DIR", "<proj>": "CLAUDE_PROJECT_DIR", "<harness>": "CLAUDE_CONFIG_DIR",
             "<home>": "HOME", "<tmpdir>": "TMPDIR"}
# the run-time ids of row 19 rule (1), as a hook payload names them (patterns.classify_name)
_ID_KEY = {"<sid>": "session_id", "<task>": "task_id", "<lane>": "lane", "<ts>": "ts"}


# ---------------------------------------------------------------- the unmutated run

def planned_runs(work: str) -> tuple[list, list[str]]:
    """Every planned replay under `work` (both settings of every driver variant), loaded as the
    check loads it, and the replays missing there."""
    from tests.artifact_graph import check as C
    from tests.artifact_graph import runtime as RT
    runs, missing = [], []
    for j in RT.jobs_for(work, RT.drivers()):
        if os.path.isfile(os.path.join(j.run_dir, "relations.tsv")):
            runs.append(C.load_run(j.label, j.settings, j.run_dir))
        else:
            missing.append(f"{j.label} ({j.settings})")
    return runs, missing


def check_tree(tree: str, runs: list) -> tuple[list, dict]:
    """The check on `tree` over `runs`: the static half on the tree, then the derivation and
    the invariants (check.run_check with replays=False, differential=False, minus its files)."""
    from tests.artifact_graph import check as C
    from tests.artifact_graph.static_half import derive as static_derive
    t0 = time.monotonic()
    st = static_derive(tree)
    t1 = time.monotonic()
    m = C.derive(tree, st, runs)
    vs = C.violations(m, st.records)
    t2 = time.monotonic()
    return vs, {"static_s": round(t1 - t0, 1), "derive_s": round(t2 - t1, 1), "map": m, "static": st}


def run_components(run) -> set:
    """The tree files a replay ran: every hook it fired and every process or origin the trace
    saw (scripts, hooks, their libraries)."""
    out = {os.path.normpath(h["hook"]) for x in run.hooks for h in x.get("hooks", []) if h.get("hook")}
    for e in run.events:
        for k in ("comp", "origin"):
            if e.get(k):
                out.add(os.path.normpath(e[k]))
    return out


# ---------------------------------------------------------------- mutations

@dataclass
class Mutation:
    name: str
    title: str                  # what the mutation is, with the target it chose
    files: dict                 # relpath -> text (new files)
    component: str              # the new file
    artifact: str               # the artifact a violation must name
    rules: tuple                # the violation rules that state what the mutation breaks
    lines: list = field(default_factory=list)   # the file's lines a violation may cite


@dataclass
class Outcome:
    name: str
    violations: list            # (rule, artifact, text) of the mutated check, every one
    new: list                   # those the unmutated check does not report
    static_s: float = 0.0
    derive_s: float = 0.0
    wall_s: float = 0.0
    cpu_s: float = 0.0          # the worker's CPU time for this mutation (E2's budget, at one CPU)
    rss_mb: int = 0             # the worker's peak resident memory
    error: str = ""


class Base:
    """The unmutated tree's check: its map, static records and violations."""

    def __init__(self, work: str, runs: list, vs: list, info: dict):
        self.work, self.runs, self.vs = work, runs, vs
        self.m, self.static = info["map"], info["static"]
        self.static_s, self.derive_s = info["static_s"], info["derive_s"]
        self.texts = {v.text() for v in vs}
        self.decl = [r for r in self.static.records if r["kind"] == "declaration"]
        self.ran = set().union(*(run_components(r) for r in runs)) if runs else set()

    def free_name(self, stem: str, where: str = "scripts") -> str:
        files = set(os.listdir(REPO / where))
        n = 0
        while True:
            name = f"mutation-{stem}{'-' + str(n) if n else ''}.py"
            if name not in files:
                return f"{where}/{name}"
            n += 1


def _expr(key: str) -> str | None:
    """A Python expression for the path of `key` that the static half reads back as `key`:
    its root from the environment, its ids from the hook payload."""
    root, _, tail = key.partition("/")
    if key.startswith("/"):
        root, tail = "", key[1:]
    elif root not in _ROOT_ENV:
        return None
    parts = re.split(r"(<[a-z*]+>)", tail)
    out = []
    for p in parts:
        if re.fullmatch(r"<[a-z*]+>", p):
            if p not in _ID_KEY:
                return None
            out.append(f"{{payload[{_ID_KEY[p]!r}]}}")
        else:
            out.append(p.replace("{", "{{").replace("}", "}}"))
    text = "".join(out)
    f = "f" if "{payload[" in text else ""
    if not root:
        return f + repr("/" + text)
    return f"os.path.join(os.environ[{_ROOT_ENV[root]!r}], {f}{text!r})"


def _code(head: str, body: list[str]) -> tuple[str, list[int]]:
    """A script's text, and the line numbers of the body's lines marked with a leading '>'."""
    lines = ["#!/usr/bin/env python3", f'"""{head}"""', "import json", "import os", "import re",
             "import subprocess", "import sys", "", "payload = json.load(sys.stdin)", ""]
    marked = []
    for b in body:
        if b.startswith(">"):
            marked.append(len(lines) + 1)
            b = b[1:]
        lines.append(b)
    return "\n".join(lines) + "\n", marked


def _ids(key: str) -> int:
    return len(re.findall(r"<[a-z*]+>", key.split("/", 1)[1] if "/" in key else key))


def _code_writers(a) -> list[str]:
    return [p for p in a.producers() if p.startswith(("hooks/", "scripts/"))]


def _file_artifacts(base: Base) -> list:
    """File artifacts the replays show, simplest paths first (fewest ids, then by key)."""
    arts = [a for a in base.m.artifacts.values() if a.kind == "file" and a.runtime and _expr(a.key)]
    return sorted(arts, key=lambda a: (_ids(a.key), a.key))


def second_writer(base: Base) -> Mutation | str:
    """A second writer of an artifact one piece of harness code writes (rule (1))."""
    from tests.artifact_graph import check as C
    for a in _file_artifacts(base):
        prods = C._producing(a, base.m.ctx)
        if len(prods) == 1 and _code_writers(a) == prods and not a.declared:
            comp = base.free_name("second-writer")
            text, lines = _code(f"Acceptance 3 mutation: a second writer of {a.key}.", [
                f"path = {_expr(a.key)}",
                ">with open(path, 'w', encoding='utf-8') as fh:",
                "    fh.write('{}\\n')",
            ])
            return Mutation("second_writer", f"{comp} writes {a.key}, which {prods[0]} alone writes",
                            {comp: text}, comp, a.key, ("1-producers",), lines)
    return "no file artifact with one code producer whose path the static half can be given"


def _written_dirs(base: Base) -> list[str]:
    out = []
    for a in _file_artifacts(base):
        if _code_writers(a) and _ids(a.key) == 0 and a.key.startswith("<") and "/" in a.key:
            d = a.key.rsplit("/", 1)[0]
            if d not in out:
                out.append(d)
    return out


def _fresh(base: Base, stem: str, op: str) -> str | None:
    """A file name in a directory harness code writes that no artifact has and no static relation
    of `op` (write: a writer; read: a reader) reaches: none whose pattern the check joins to the
    files it matches (a known root, or a file name of its own; check.static_files)."""
    from tests.artifact_graph import check as C
    pats = {r["path"] for r in base.static.records if r["kind"] == "relation"
            and (r["op"] in ("write", "create", "rename") if op == "write" else r["op"] == "read")
            and (C.literal_root(r["path"]) or C._named(r["path"]) and C._family(r["path"]))}
    for d in _written_dirs(base):
        key = f"{d}/claude-mutation-{stem}.json"
        if key not in base.m.artifacts and not any(C.matches(p, key) for p in pats):
            return key
    return None


def unwritten_read(base: Base) -> Mutation | str:
    key = _fresh(base, "nobody-writes", "write")
    if key is None:
        return "no directory harness code writes holds a name free of writers"
    comp = base.free_name("unwritten-read")
    text, lines = _code(f"Acceptance 3 mutation: a reader of {key}, which nothing writes.", [
        f"path = {_expr(key)}",
        ">with open(path, encoding='utf-8') as fh:",
        "    data = json.load(fh)",
        "print(len(data))",
    ])
    return Mutation("unwritten_read", f"{comp} reads {key}, which nothing writes", {comp: text}, comp, key,
                    ("2-unwritten",), lines)


def unread_write(base: Base) -> Mutation | str:
    key = _fresh(base, "nobody-reads", "read")
    if key is None:
        return "no directory harness code writes holds a name free of readers"
    comp = base.free_name("unread-write")
    text, lines = _code(f"Acceptance 3 mutation: a writer of {key}, which nothing reads.", [
        f"path = {_expr(key)}",
        ">with open(path, 'w', encoding='utf-8') as fh:",
        "    fh.write('{}\\n')",
    ])
    return Mutation("unread_write", f"{comp} writes {key}, which nothing reads", {comp: text}, comp, key,
                    ("2-unread",), lines)


def recheck(base: Base) -> Mutation | str:
    """A reader outside the allowed positions that re-validates an artifact the producer side
    already rejects with the tree's switches (rule (6)): a subagent's declared artifact first."""
    side = ("producer stop", "producer tool call", "G1", "G3")
    cands = [a for a in _file_artifacts(base) if a.writers and any(
        d.position in side and d.settings in ("shipped", "static") for d in a.decisions)]
    cands.sort(key=lambda a: (not a.declared, _ids(a.key), a.key))
    for a in cands:
        rejects = sorted({f"{d.who} at {d.position}" for d in a.decisions
                          if d.position in side and d.settings in ("shipped", "static")})
        comp = base.free_name("recheck")
        text, lines = _code(f"Acceptance 3 mutation: a re-validation of {a.key} outside the allowed positions.", [
            f"path = {_expr(a.key)}",
            "try:",
            "    with open(path, encoding='utf-8') as fh:",
            "        doc = json.load(fh)",
            "except (OSError, ValueError):",
            ">    sys.exit(2)",
            "if not isinstance(doc, dict) or not doc:",
            ">    sys.exit(2)",
        ])
        return Mutation("recheck", f"{comp} re-validates {a.key} (exit 2 when it is missing or not a JSON object), "
                        f"which the producer side rejects with the tree's switches ({'; '.join(rejects[:3])})",
                        {comp: text}, comp, a.key, ("6-recheck",), lines)
    return "no artifact whose producer side rejects a mutation with the tree's switches"


def role_map(base: Base) -> Mutation | str:
    """A hand-written filename-to-role mapping in a hook: two declared paths, each to the role its
    obligation names (rule (7))."""
    roster = {d["name"] for d in base.decl if d["type"] == "roster_entry"}
    pairs = {}
    for ob in sorted((d for d in base.decl if d["type"] == "obligation"), key=lambda d: d["site"]):
        role = ob.get("role")
        if role not in roster or role in pairs.values():
            continue
        for art in ob.get("artifacts") or []:
            name = (art.get("path") or "").rsplit("/", 1)[-1]
            glob = re.sub(r"<[a-z*]+>", "*", name)
            if len(re.sub(r"[*.\-_]", "", glob)) >= 4 and glob not in pairs:
                pairs[glob] = role
                break
        if len(pairs) == 2:
            break
    if len(pairs) < 2:
        return "fewer than two roster roles have an obligation that declares a file"
    comp = base.free_name("role-map", "hooks")
    body = [">ROLE_OF = {"] + [f">    {k!r}: {v!r}," for k, v in pairs.items()] + ["}",
            "print(ROLE_OF.get(os.path.basename(payload.get('tool_input', {}).get('file_path', ''))))"]
    text, lines = _code("Acceptance 3 mutation: a hand-written filename-to-role mapping in a hook.", body)
    return Mutation("role_map", f"{comp} maps {', '.join(f'{k} to {v}' for k, v in pairs.items())}",
                    {comp: text}, comp, comp, ("7-list",), lines)


def tmp_split(base: Base) -> Mutation | str:
    """A reader under /tmp of a file its writer puts under CLAUDE_STATE_DIR (rule (8))."""
    for a in _file_artifacts(base):
        if a.key.startswith("<state>/") and _code_writers(a) and "/tmp/" + a.key[len("<state>/"):] \
                not in base.m.artifacts:
            other = "/tmp/" + a.key[len("<state>/"):]
            comp = base.free_name("tmp-split")
            text, lines = _code(f"Acceptance 3 mutation: a reader of {other}, which its writer puts under "
                                "CLAUDE_STATE_DIR.", [
                f"path = {_expr(other)}",
                ">with open(path, encoding='utf-8') as fh:",
                "    print(fh.read())",
            ])
            return Mutation("tmp_split", f"{comp} reads {other}; {', '.join(_code_writers(a))} writes {a.key}",
                            {comp: text}, comp, a.key, ("8-state-dir",), lines)
    return "no file under the state dir that harness code writes"


def _decider_groups(a) -> list[str]:
    """Rule (4)'s rules among the artifact's deciders, as the check groups them."""
    from tests.artifact_graph import check as C
    ds = [d for d in a.decisions if d.settings in ("shipped", "static") and d.position != "own artifact"]
    return C._rule_groups(ds)


def response_parser(base: Base) -> Mutation | str:
    """A second parser of a declared response block in a hook: one that holds the block's marker
    and decides on it, beside the one the tree already has (rule (4))."""
    for key in sorted(base.m.artifacts):
        a = base.m.artifacts[key]
        if a.kind != "response" or not _decider_groups(a):
            continue
        marker = key.split(":", 2)[2]
        comp = base.free_name("response-parser", "hooks")
        text, lines = _code(f"Acceptance 3 mutation: a second parser of the response block {key}.", [
            f">MARKER = {marker!r}",
            "message = payload.get('last_assistant_message') or ''",
            "last = message.rstrip().splitlines()[-1] if message.strip() else ''",
            "if not last.startswith(MARKER):",
            "    sys.exit(2)",
        ])
        return Mutation("response_parser", f"{comp} parses {key} (marker {marker!r}), which "
                        f"{'; '.join(_decider_groups(a))} already decides on", {comp: text}, comp, key,
                        ("4-one-rule",), lines)
    return "no declared response block that a rule decides on"


def task_id_rule(base: Base) -> Mutation | str:
    """A second task-id-to-name derivation in a script: the regex the tree's one derivation
    matches a minted id with, copied (rule (4) on the task-id rule)."""
    rule = next((a for a in base.m.artifacts.values() if a.kind == "rule"), None)
    if rule is None or not _decider_groups(rule):
        return "the check derives no task-id rule that a rule decides on"
    deciders = {d.who for d in rule.decisions}
    from tests.artifact_graph import check as C
    regexes = sorted((r["site"], r["regex"]) for r in base.static.records
                     if r["kind"] == "id_regex" and C.comp_identity(r["component"]) in deciders)
    if not regexes:
        return f"no regex of the task-id rule's decider ({', '.join(sorted(deciders))}) to copy"
    site, rx = max(regexes, key=lambda x: (len(x[1]), x[0]))
    comp = base.free_name("task-id")
    text, lines = _code(f"Acceptance 3 mutation: a second task-id-to-name derivation (the regex of {site}).", [
        f">TASK_ID = re.compile({rx!r})",
        "task_id = payload.get('task_id') or ''",
        "if not TASK_ID.match(task_id):",
        "    sys.exit(2)",
        "print('dev-report-' + task_id + '.json')",
    ])
    return Mutation("task_id_rule", f"{comp} matches the task id with {site}'s regex and derives a name from it",
                    {comp: text}, comp, rule.key, ("4-one-rule",), lines)


def vocabulary_copy(base: Base) -> Mutation | str:
    """A copy of a schema's terminal vocabulary in a hook: the enum of a top-level property of a
    schema an obligation declares its artifact with (rule (7))."""
    declared = {art.get("schema") for d in base.decl if d["type"] == "obligation" for art in d.get("artifacts") or ()}
    enums = sorted((e["schema"], e["pointer"], [v for v in e["values"] if isinstance(v, str)])
                   for e in base.decl if e["type"] == "schema_enum" and e["schema"] in declared
                   and re.fullmatch(r"/properties/[^/]+/enum", e["pointer"]))
    enums = [e for e in enums if len(e[2]) >= 2]
    if not enums:
        return "no schema an obligation declares has a top-level enum of two or more values"
    schema, ptr, values = max(enums, key=lambda e: (len(e[2]), e[0], e[1]))
    comp = base.free_name("vocabulary", "hooks")
    text, lines = _code(f"Acceptance 3 mutation: a copy of {schema}{ptr} in a hook.", [
        f"SCHEMA = {schema!r}",
        f">TERMINAL = {tuple(values)!r}",
        "if payload.get('status') not in TERMINAL:",
        "    sys.exit(2)",
    ])
    return Mutation("vocabulary_copy", f"{comp} copies {schema}{ptr} {values}", {comp: text}, comp, comp,
                    ("7-list",), lines)


def chain_fields(base: Base) -> Mutation | str:
    """A script that runs the chain resolver and decides on a field of its stdout instead of using
    its output verbatim (rule (5)): the field its own code sets most often."""
    from tests.artifact_graph.static_half import DEFAULT_CHAIN_SCRIPT
    src = REPO / DEFAULT_CHAIN_SCRIPT
    if not src.is_file():
        return f"the chain function {DEFAULT_CHAIN_SCRIPT} is not in the tree"
    keys = Counter(n.slice.value for n in ast.walk(ast.parse(src.read_text(encoding="utf-8")))
                   if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                   and isinstance(n.slice.value, str) and isinstance(n.ctx, ast.Store))
    if not keys:
        return f"{DEFAULT_CHAIN_SCRIPT} sets no field"
    fld = min(keys.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    comp = base.free_name("chain-fields")
    rel = os.path.relpath(DEFAULT_CHAIN_SCRIPT, os.path.dirname(comp))
    text, lines = _code(f"Acceptance 3 mutation: the chain resolver run, its stdout's {fld!r} decided on.", [
        f"resolver = os.path.join(os.path.dirname(os.path.abspath(__file__)), {rel!r})",
        ">proc = subprocess.run([sys.executable, resolver, '--task-id', payload.get('task_id') or ''],",
        "                      capture_output=True, text=True)",
        "result = json.loads(proc.stdout)",
        f"if not result.get({fld!r}):",
        "    sys.exit(2)",
    ])
    return Mutation("chain_fields", f"{comp} runs {DEFAULT_CHAIN_SCRIPT} and exits on its stdout's {fld!r}",
                    {comp: text}, comp, "stdout:" + DEFAULT_CHAIN_SCRIPT, ("5-chain-verbatim",), lines)


PICKERS = (second_writer, unwritten_read, unread_write, recheck, role_map, tmp_split, response_parser,
           task_id_rule, vocabulary_copy, chain_fields)


# ---------------------------------------------------------------- workers

_RUNS: list = []


def _init_worker(work: str) -> None:
    global _RUNS
    _RUNS, _missing = planned_runs(work)


def mutate_and_check(mut: dict, scratch: str, base_texts: set) -> dict:
    """In a worker: copy the tree, add the mutation's files, run the check on the copy."""
    import resource
    t0, c0 = time.monotonic(), time.process_time()
    tree = os.path.join(scratch, mut["name"], "tree")
    out = Outcome(mut["name"], [], [])
    try:
        shutil.rmtree(os.path.dirname(tree), ignore_errors=True)
        shutil.copytree(REPO, tree, ignore=_IGNORE, symlinks=True)
        for rel, text in mut["files"].items():
            p = os.path.join(tree, rel)
            if os.path.lexists(p):
                raise FileExistsError(f"{rel} is in the tree: a mutation adds a new file")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.chmod(p, 0o755)
        vs, info = check_tree(tree, _RUNS)
        out.static_s, out.derive_s = info["static_s"], info["derive_s"]
        out.violations = [(v.rule, v.artifact, v.text()) for v in vs]
        out.new = [x for x in out.violations if x[2] not in base_texts]
    except Exception as e:  # noqa: BLE001 -- the test reports the worker's failure as its own
        out.error = f"{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(os.path.dirname(tree), ignore_errors=True)
    out.wall_s = round(time.monotonic() - t0, 1)
    out.cpu_s = round(time.process_time() - c0, 1)
    out.rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    return asdict(out)


# ---------------------------------------------------------------- fixtures

def _mutation(name: str):
    """Marks a test with the mutation it asserts on; the fixture runs only the selected tests'."""
    def mark(fn):
        fn.mutation = name
        return fn
    return mark


@pytest.fixture(scope="module")
def mutations(request, tmp_path_factory):
    from tests.artifact_graph import runtime as RT
    wanted = {getattr(getattr(i, "function", None), "mutation", None) for i in request.session.items} - {None}
    work = os.environ.get("ARTIFACT_GRAPH_WORK")
    if not work:
        pytest.fail("the mutation tests run the check over the unmutated replays in ARTIFACT_GRAPH_WORK, which is "
                    "unset (a full check with --work leaves them there; CI downloads the shards' replays)",
                    pytrace=False)
    jobs = int(os.environ.get("ARTIFACT_GRAPH_JOBS") or max(1, min(4, os.cpu_count() or 1)))
    t0 = time.monotonic()
    pool = ProcessPoolExecutor(max_workers=jobs, mp_context=get_context("spawn"), initializer=_init_worker,
                               initargs=(work,))
    try:
        warm = [pool.submit(time.monotonic) for _ in range(jobs)]   # the workers load the replays meanwhile
        runs, missing = planned_runs(work)
        if missing or not runs:
            pytest.fail(f"{len(missing)} of {len(RT.jobs_for(work, RT.drivers()))} planned replays are missing "
                        f"under {work}: " + ", ".join(missing[:10]), pytrace=False)
        c0 = time.process_time()
        vs, info = check_tree(str(REPO), runs)
        base_cpu = round(time.process_time() - c0, 1)
        base = Base(work, runs, vs, info)
        base_s = round(time.monotonic() - t0, 1)
        picked = {}
        for pick in PICKERS:
            if pick.__name__ not in wanted:
                continue
            mut = pick(base)
            picked[pick.__name__] = mut
        for w in warm:
            w.result()
        scratch = str(tmp_path_factory.mktemp("mutations"))
        futures = {name: pool.submit(mutate_and_check, asdict(mut), scratch, base.texts)
                   for name, mut in picked.items() if isinstance(mut, Mutation)}
        outcomes = {name: Outcome(**f.result()) for name, f in futures.items()}
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    wall = round(time.monotonic() - t0, 1)
    summary = {"base_violations": len(vs), "base_static_s": base.static_s, "base_derive_s": base.derive_s,
               "base_s": base_s, "base_cpu_s": base_cpu, "wall_s": wall, "jobs": jobs, "replays": len(runs),
               "mutations": {n: {"static_s": o.static_s, "derive_s": o.derive_s, "wall_s": o.wall_s,
                                 "cpu_s": o.cpu_s, "rss_mb": o.rss_mb} for n, o in outcomes.items()}}
    print("\nmutation tests: " + json.dumps(summary, sort_keys=True), flush=True)
    return {"base": base, "picked": picked, "outcomes": outcomes, "summary": summary}


def _assert_fails(mutations, name: str) -> None:
    mut = mutations["picked"][name]
    if not isinstance(mut, Mutation):
        pytest.fail(f"mutation {name}: no target in the tree under test: {mut}", pytrace=False)
    base = mutations["base"]
    ran = sorted(c for c in mut.files if c in base.ran)
    assert not ran, (f"mutation {name}: the unmutated replays ran {ran}, so the replays of the pipelines that "
                     "reach it would have to run again; a mutation adds a file nothing runs")
    o = mutations["outcomes"][name]
    assert not o.error, f"mutation {name} ({mut.title}): the check did not run on the mutated copy: {o.error}"
    sites = [f"{mut.component}:{n}" for n in mut.lines]
    hits = [t for r, a, t in o.new if r in mut.rules and mut.artifact in t and any(
        re.search(re.escape(s) + r"(?!\d)", t) for s in sites)]
    report = (f"mutation {name}: {mut.title}\n  no replay: no step of the {len(base.runs)} unmutated replays runs "
              f"{', '.join(mut.files)}; static half {o.static_s} s, derivation {o.derive_s} s, "
              f"{o.wall_s} s in all ({o.cpu_s} s of CPU)\n  the mutated check: {len(o.violations)} violations, "
              f"{len(o.new)} new ({', '.join(sorted({r for r, _a, _t in o.new})) or 'none'})")
    added = "".join(f"\n  added {rel}:\n" + "".join(f"    {ln}\n" for ln in text.splitlines())
                    for rel, text in mut.files.items())
    print("\n" + report + added + "".join("\n" + t + "\n" for t in hits), flush=True)
    assert o.violations, f"{report}\nthe mutated check reports no violation, so it exits 0"
    assert hits, (f"{report}\nno new {'/'.join(mut.rules)} violation names {mut.artifact} and "
                  f"{' or '.join(sites)}; the new ones:\n\n" + "\n\n".join(t for _r, _a, t in o.new[:20]))


@_mutation("second_writer")
def test_a_second_writer_of_an_existing_artifact(mutations):
    _assert_fails(mutations, "second_writer")


@_mutation("unwritten_read")
def test_a_reader_of_a_path_nothing_writes(mutations):
    _assert_fails(mutations, "unwritten_read")


@_mutation("unread_write")
def test_a_write_of_a_file_nothing_reads(mutations):
    _assert_fails(mutations, "unread_write")


@_mutation("recheck")
def test_a_consumer_outside_the_allowed_positions_that_revalidates_an_artifact(mutations):
    _assert_fails(mutations, "recheck")


@_mutation("role_map")
def test_a_hand_written_filename_to_role_mapping_in_a_hook(mutations):
    _assert_fails(mutations, "role_map")


@_mutation("tmp_split")
def test_a_consumer_under_tmp_of_a_state_dir_file(mutations):
    _assert_fails(mutations, "tmp_split")


@_mutation("response_parser")
def test_a_second_parser_of_a_declared_response_block_in_a_hook(mutations):
    _assert_fails(mutations, "response_parser")


@_mutation("task_id_rule")
def test_a_second_task_id_to_name_derivation_in_a_script(mutations):
    _assert_fails(mutations, "task_id_rule")


@_mutation("vocabulary_copy")
def test_a_copy_of_a_schemas_terminal_vocabulary_in_a_hook(mutations):
    _assert_fails(mutations, "vocabulary_copy")


@_mutation("chain_fields")
def test_a_script_that_decides_on_the_chain_resolvers_stdout_fields(mutations):
    _assert_fails(mutations, "chain_fields")
