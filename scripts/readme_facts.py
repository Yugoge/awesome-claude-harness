#!/usr/bin/env python3
"""Every number and table row README.md and docs/status.md show, derived from this repository's files.

Description: One function per fact (FACTS below), one source per function, nothing the pages do not
  show. No number is typed here: each is counted or read from a committed file, or produced by the
  suite's own enumerator. A fact that cannot be derived raises FactError naming the missing input,
  never a zero or an earlier value. Standard library plus PyYAML; no network; nothing needs pytest.

Usage: readme_facts.py [--root DIR] [--fact NAME]...   # print the facts as JSON
Exit codes: 0 = printed, 2 = a fact could not be derived (the message names the input) or a usage error

File contents come from the working tree; which files exist comes from the git index (an untracked
scratch file is not a test, a command or a hook); settings.json is read as the index blob, as
scripts/verify-claims.sh hands it on, since a working copy may carry an enabled module's hooks. `root`
is the top of a git work tree. Nothing is replayed: blocking_sites runs the suite's static enumerator
and relay probe, static_artifacts a part of the artifact check's static half, both loaded by path
under throwaway names with byte-code writing off, so a run leaves no __pycache__ in the tree.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import fnmatch
import importlib.util
import io
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class FactError(RuntimeError):
    """A fact could not be derived. The message names the missing or unusable input."""


# ---------------------------------------------------------------------------------------------
# inputs: files, git, parsing, loading the suite's modules
# ---------------------------------------------------------------------------------------------

def _root(root) -> Path:
    path = Path(root) if root is not None else REPO_ROOT
    if not path.is_dir():
        raise FactError(f"root {path} is not a directory")
    return path.resolve()


def _need(root: Path, rel: str) -> Path:
    if not (root / rel).is_file():
        raise FactError(f"missing input {rel} (looked in {root})")
    return root / rel


def _read(root: Path, rel: str) -> str:
    try:
        return _need(root, rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FactError(f"cannot read {rel}: {exc}") from exc


def _parse(root: Path, rel: str) -> ast.Module:
    try:
        return ast.parse(_read(root, rel), filename=rel)
    except SyntaxError as exc:
        raise FactError(f"cannot parse {rel}: {exc}") from exc


def _yaml(text: str, what: str):
    try:
        import yaml
    except ImportError as exc:  # PyYAML is a declared dependency (requirements.txt)
        raise FactError(f"PyYAML is needed to read {what} and is not importable") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise FactError(f"cannot parse {what} as YAML: {exc}") from exc


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _git(root: Path, *args: str) -> bytes:
    # No GIT_* variable of the caller (a hook or a test sets GIT_DIR / GIT_INDEX_FILE) may redirect it.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, env=env, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FactError(f"cannot run git in {root}: {exc}") from exc
    if done.returncode != 0:
        raise FactError(f"`git {' '.join(args)}` failed in {root}: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def _tracked(root: Path, *prefixes: str) -> list[str]:
    """Paths in the git index under `prefixes` (all when none), sorted."""
    top = _git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    if os.path.realpath(top) != os.path.realpath(root):
        raise FactError(f"{root} is not the top of a git work tree (the top is {top}): "
                        "the files that exist are the ones in the index")
    return sorted(p for p in _git(root, "ls-files", "-z", "--", *prefixes).decode("utf-8").split("\0") if p)


def _tracked_settings_text(root: Path) -> str:
    """settings.json as the index holds it: scripts/verify-claims.sh's `git cat-file blob :settings.json`."""
    _tracked(root, "settings.json")  # fails clearly when root is no git work tree
    try:
        return _git(root, "cat-file", "blob", ":settings.json").decode("utf-8")
    except FactError as exc:
        raise FactError(f"the tracked settings.json is not in the git index of {root} ({exc})") from exc


_loads = itertools.count()


@contextlib.contextmanager
def _no_bytecode():
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = old


@contextlib.contextmanager
def _load(path: Path, hint: str, package: bool = False):
    """The module at `path` (a package's directory when `package`, its relative imports resolving inside it)
    under a throwaway name, registered while it is used because a dataclass looks its own module up.
    Yields the module, or the package's module name."""
    name = f"_readme_facts_{hint}_{next(_loads)}"
    where = {"submodule_search_locations": [str(path)]} if package else {}
    spec = importlib.util.spec_from_file_location(name, str(_need(path, "__init__.py") if package else path), **where)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        with _no_bytecode():
            try:
                spec.loader.exec_module(module)
            except Exception as exc:  # noqa: BLE001 - whatever the source did, it is an input we cannot use
                raise FactError(f"cannot load {path}: {type(exc).__name__}: {exc}") from exc
            yield name if package else module
    finally:
        for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
            del sys.modules[key]


# ---------------------------------------------------------------------------------------------
# AST helpers over the test sources
# ---------------------------------------------------------------------------------------------

def _module_value(tree: ast.Module, name: str):
    """The value expression of the module-level assignment to `name`, or None."""
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return node.value
    return None


def _literal(node: ast.AST, rel: str, what: str):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError) as exc:
        raise FactError(f"{rel}:{getattr(node, 'lineno', '?')}: {what} is not a literal ({exc})") from exc


def _call_name(call: ast.Call) -> str:
    return getattr(call.func, "id", None) or getattr(call.func, "attr", None) or ""


def _functions(tree: ast.AST, kinds=(ast.FunctionDef, ast.AsyncFunctionDef)) -> list:
    return [n for n in ast.walk(tree) if isinstance(n, kinds)]


def _function(tree: ast.Module, name: str):
    return next((n for n in _functions(tree) if n.name == name), None)


def _asserts(node: ast.AST) -> list[ast.Assert]:
    return sorted((n for n in ast.walk(node) if isinstance(n, ast.Assert)), key=lambda n: n.lineno)


def _assigned(fn: ast.AST) -> dict[str, str]:
    """{name: the source of the value last assigned to it} inside `fn`."""
    return {t.id: ast.unparse(a.value) for a in ast.walk(fn) if isinstance(a, ast.Assign)
            for t in a.targets if isinstance(t, ast.Name)}


def _count_test_functions(tree: ast.AST) -> int:
    """Functions named test_* at module or class level (not inside another function)."""
    total = 0
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            total += child.name.startswith("test_")
        elif isinstance(child, ast.stmt):
            total += _count_test_functions(child)
    return total


# ---------------------------------------------------------------------------------------------
# 1. the baseline job's Python versions
# ---------------------------------------------------------------------------------------------

BASELINE_WORKFLOW = ".github/workflows/baseline.yml"
_MATRIX_PYTHON = re.compile(r"\$\{\{\s*matrix\.python-version\s*\}\}")


def _workflow(root: Path) -> dict:
    doc = _yaml(_read(root, BASELINE_WORKFLOW), BASELINE_WORKFLOW)
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
        raise FactError(f"{BASELINE_WORKFLOW}: no `jobs` mapping")
    return doc


def _matrix_versions(job: dict, job_id: str) -> list:
    matrix = _mapping(job.get("strategy")).get("matrix")
    if not isinstance(matrix, dict) or "python-version" not in matrix:
        raise FactError(f"{BASELINE_WORKFLOW}: job `{job_id}` has no strategy.matrix.python-version")
    if "include" in matrix or "exclude" in matrix:
        raise FactError(f"{BASELINE_WORKFLOW}: the matrix of `{job_id}` has include/exclude; "
                        "the legs are not just the python-version list")
    versions = matrix["python-version"]
    if not isinstance(versions, list) or not versions:
        raise FactError(f"{BASELINE_WORKFLOW}: strategy.matrix.python-version of `{job_id}` is not a non-empty list")
    bad = [v for v in versions if not isinstance(v, str) or not re.fullmatch(r"\d+\.\d+", v)]
    if bad:  # an unquoted 3.10 is read by YAML as 3.1
        raise FactError(f"{BASELINE_WORKFLOW}: matrix python-version entry {bad[0]!r} is not a quoted \"M.N\" string")
    return versions


def ci_python_versions(root=None) -> list[str]:
    """The Python versions of the baseline job (the job named like the workflow), in the order of its
    strategy.matrix.python-version, which an actions/setup-python step must take."""
    doc = _workflow(_root(root))
    job_id = doc.get("name")
    job = doc["jobs"].get(job_id)
    if not isinstance(job, dict):
        raise FactError(f"{BASELINE_WORKFLOW}: no job `{job_id}` (the job named like the workflow)")
    versions = _matrix_versions(job, job_id)
    if not any(str(s.get("uses", "")).startswith("actions/setup-python@")
               and _MATRIX_PYTHON.fullmatch(str(_mapping(s.get("with")).get("python-version", "")).strip())
               for s in map(_mapping, job.get("steps") or [])):
        raise FactError(f"{BASELINE_WORKFLOW}: no actions/setup-python step of `{job_id}` takes "
                        "${{ matrix.python-version }}")
    return list(versions)


# ---------------------------------------------------------------------------------------------
# 2. the replay suite's size
# ---------------------------------------------------------------------------------------------

REPLAY_DIR = "tests/replay"
REPLAY_SUITE = "tests/replay/suite.py"
REPLAY_PIPELINES_TEST = "tests/replay/test_pipelines.py"
REPLAY_REGRESSIONS_TEST = "tests/replay/test_regressions.py"
_FAULT_ID = re.compile(r"F(\d+)([a-z]*)")
_FAULT_TEST = re.compile(r"test_f(\d+)([a-z]*)_")
_REGRESSION_ID = re.compile(r"\bR-[A-Z]\d+\b")
_SCENARIO_FIELDS = ("name", "driver", "args", "pipelines", "cost")


def _scenario(elt: ast.AST) -> dict:
    if not (isinstance(elt, ast.Call) and _call_name(elt) == "Scenario"):
        raise FactError(f"{REPLAY_SUITE}:{elt.lineno}: COMPLIANT holds something other than a Scenario(...) literal")
    values = {f: _literal(a, REPLAY_SUITE, f"Scenario argument {f}") for f, a in zip(_SCENARIO_FIELDS, elt.args)}
    values.update({kw.arg: _literal(kw.value, REPLAY_SUITE, f"Scenario argument {kw.arg}") for kw in elt.keywords})
    if not values.get("name"):
        raise FactError(f"{REPLAY_SUITE}:{elt.lineno}: a Scenario without a name")
    return {"pipelines": (), **values}


def _string_tuple(tree: ast.Module, name: str) -> tuple:
    node = _module_value(tree, name)
    value = _literal(node, REPLAY_SUITE, name) if node is not None else None
    if not isinstance(value, tuple) or not value or not all(isinstance(x, str) for x in value):
        raise FactError(f"{REPLAY_SUITE}: no {name} tuple of strings")
    return value


def _cases_run_every_scenario_in_every_mode(root: Path) -> None:
    """tests/replay/test_pipelines.py builds its CASES from suite.COMPLIANT x suite.SETTINGS."""
    cases = _module_value(_parse(root, REPLAY_PIPELINES_TEST), "CASES")
    if not isinstance(cases, ast.ListComp):
        raise FactError(f"{REPLAY_PIPELINES_TEST}: CASES is no list comprehension")
    iters = [ast.unparse(g.iter) for g in cases.generators]
    if iters != ["suite.COMPLIANT", "suite.SETTINGS"]:
        raise FactError(f"{REPLAY_PIPELINES_TEST}:{cases.lineno}: CASES iterates {iters}, "
                        "not suite.COMPLIANT then suite.SETTINGS: a scenario may not run in every mode")


def _is_fault_id(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(_FAULT_ID.fullmatch(node.value))


def _fault_ids_in(tree: ast.Module) -> set[str]:
    """The fault ids a test file names: as a key of a module-level table (FAULTS, _LOCK, SHAPES, E1), as the
    name of a Scenario, or in a test function name test_f<id>_*."""
    found = {k.value for node in tree.body if isinstance(getattr(node, "value", None), ast.Dict)
             and isinstance(node, (ast.Assign, ast.AnnAssign)) for k in node.value.keys if _is_fault_id(k)}
    found |= {n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and _call_name(n) == "Scenario"
              and n.args and _is_fault_id(n.args[0])}
    return found | {f"F{m.group(1)}{m.group(2)}" for m in (_FAULT_TEST.match(f.name) for f in _functions(tree)) if m}


def _fault_ids(root: Path) -> dict[str, list[str]]:
    """{class: [ids]}, the suite's numbered fault ids grouped by their number (F8, F8q -> class F8)."""
    files = [p for p in _tracked(root, REPLAY_DIR) if p.count("/") == 2 and fnmatch.fnmatch(Path(p).name, "test_*.py")]
    if not files:
        raise FactError(f"no test_*.py under {REPLAY_DIR} in the git index of {root}")
    classes: dict[str, list[str]] = {}
    for fid in sorted(set().union(*(_fault_ids_in(_parse(root, rel)) for rel in files)),
                      key=lambda s: (int(_FAULT_ID.fullmatch(s).group(1)), s)):
        classes.setdefault(f"F{_FAULT_ID.fullmatch(fid).group(1)}", []).append(fid)
    if not classes:
        raise FactError(f"no fault id (F<number>[letters]) named in the tests under {REPLAY_DIR}")
    return classes


def _code_strings(tree: ast.Module) -> list[str]:
    """The string constants of the code, docstrings left out."""
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def _regressions(root: Path) -> list[str]:
    """The R-<letter><digit> defects the docstring of tests/replay/test_regressions.py names, each required to
    have a test there (a test_r_<id>_ function, or the id in a string of the test code)."""
    tree = _parse(root, REPLAY_REGRESSIONS_TEST)
    ids = sorted(set(_REGRESSION_ID.findall(ast.get_docstring(tree) or "")))
    if not ids:
        raise FactError(f"{REPLAY_REGRESSIONS_TEST}: the module docstring names no R-<id> regression")
    names, strings = [f.name for f in _functions(tree)], _code_strings(tree)
    untested = [i for i in ids if not any(n.startswith("test_" + i.lower().replace("-", "_") + "_") for n in names)
                and not any(i in s for s in strings)]
    if untested:
        raise FactError(f"{REPLAY_REGRESSIONS_TEST}: named in the docstring but with no test: {untested}")
    return ids


def replay_suite_size(root=None) -> dict:
    """The replay suite's size, read from tests/replay without replaying: the pipelines the compliant
    scenarios of suite.COMPLIANT type (every one of suite.TEN), the scenarios, the settings modes
    test_pipelines.CASES runs each under, the injected faults by class (F8, F8q ... are class F8) and
    variant, and the regressions test_regressions.py names."""
    root = _root(root)
    tree = _parse(root, REPLAY_SUITE)
    compliant = _module_value(tree, "COMPLIANT")
    if not isinstance(compliant, (ast.Tuple, ast.List)) or not compliant.elts:
        raise FactError(f"{REPLAY_SUITE}: no COMPLIANT tuple of Scenario(...) literals")
    scenarios, settings = [_scenario(e) for e in compliant.elts], _string_tuple(tree, "SETTINGS")
    ten = _string_tuple(tree, "TEN")
    _cases_run_every_scenario_in_every_mode(root)
    pipelines = {p for s in scenarios for p in s["pipelines"]}
    uncovered = [p for p in ten if p not in pipelines]
    if uncovered:
        raise FactError(f"{REPLAY_SUITE}: suite.TEN names {uncovered}, which no compliant scenario types")
    classes, regressions = _fault_ids(root), _regressions(root)
    return {"pipelines": len(pipelines), "compliant_scenarios": len(scenarios), "settings_modes": list(settings),
            "compliant_replays": len(scenarios) * len(settings), "fault_classes": len(classes),
            "fault_ids": sum(len(v) for v in classes.values()), "regression_replays": len(regressions),
            "regression_ids": regressions}


# ---------------------------------------------------------------------------------------------
# 3. the registered hooks' blocking sites
# ---------------------------------------------------------------------------------------------

SITES_MODULE = "tests/replay/sites.py"
DEAD_END_TEST = "tests/replay/test_no_dead_end.py"
SITE_CLASSES = ("G", "D", "H", "U", "-")  # the suite's own order (test_no_dead_end.Catalog.table)


def _classified_sites(sites, root: Path, relay: str) -> tuple[list, list]:
    """([(site, (class, reason))], registered hook files), as test_no_dead_end.Catalog runs the enumerator (a
    child process counts only if its parent relays its exit 2), reading settings.json from the index: only
    that file's open() in this run's throwaway copy of sites.py is answered from the index blob."""
    text, settings, real_open = _tracked_settings_text(root), os.path.realpath(root / "settings.json"), open

    def tracked_open(file, *args, **kwargs):
        if isinstance(file, (str, os.PathLike)) and os.path.realpath(file) == settings:
            return io.StringIO(text)
        return real_open(file, *args, **kwargs)

    sites.open = tracked_open  # shadows the builtin inside that module only
    enum = sites.Enumerator(str(root))
    dropped = set()
    for parent, kids in enum.children.items():
        event = next((ev for ev, _ in enum.regs.get(parent, [])), "Stop")
        dropped |= {kid for kid in kids
                    if not sites.relayed(str(root), parent, kid, event, os.path.join(relay, os.path.basename(kid)))}
    return [(s, sites.classify(enum, s)) for s in enum.sites() if s.file not in dropped], sorted(enum.regs)


def blocking_sites(root=None) -> dict:
    """The blocking sites of the registered hooks (every path of a hook the tracked settings.json registers that
    exits 2 or prints a block or deny decision), per class of the suite's own enumerator (tests/replay/sites.py):
    G own-obligation gate, D denial, H time-lock, U unreachable, "-" no class, with the enumerator's reasons
    for the no-class ones. The suite asserts that no replay reaches a no-class site, not that none exists."""
    root = _root(root)
    _need(root, SITES_MODULE)
    with tempfile.TemporaryDirectory(prefix="readme-facts-") as relay, _load(root / SITES_MODULE, "sites") as sites:
        try:
            classified, registered = _classified_sites(sites, root, relay)
        except FactError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise FactError(f"the suite's enumerator ({SITES_MODULE}) failed: {type(exc).__name__}: {exc}") from exc
    if not registered:
        raise FactError(f"the tracked settings.json registers no hook file {SITES_MODULE} can follow")
    if not classified:
        raise FactError(f"{SITES_MODULE} found no blocking site in {len(registered)} registered hook files")
    counts = Counter(cls for _site, (cls, _why) in classified)
    if set(counts) - set(SITE_CLASSES):
        raise FactError(f"{SITES_MODULE} classified a site as {sorted(set(counts) - set(SITE_CLASSES))}, "
                        f"outside {list(SITE_CLASSES)}")
    return {"sites": len(classified), "by_class": {c: counts.get(c, 0) for c in SITE_CLASSES},
            "no_class": counts.get("-", 0),
            "no_class_reasons": dict(sorted(Counter(why for _s, (cls, why) in classified if cls == "-").items()))}


# ---------------------------------------------------------------------------------------------
# 4. the artifacts the producers' obligation templates declare
# ---------------------------------------------------------------------------------------------

ARTIFACT_PACKAGE = "tests/artifact_graph"
ARTIFACT_LABEL = ("file artifacts declared by the producers' obligation templates in commands/*.md, read "
                  "statically; not the artifact total the CI job \"artifact check (traced replays)\" reports")


def _obligations(root: Path, files: list[str], name: str) -> list[dict]:
    """The obligation declarations the static half's derive() records, by the same functions in the same order
    (`_markdown_envs`, `_obligations`), without the Python and shell walk of the rest of derive()."""
    static, pyscan, shscan, model = (sys.modules[f"{name}.{m}"] for m in ("static_half", "pyscan", "shscan", "model"))

    def read_text(rel: str) -> str:
        return (root / rel).read_text(encoding="utf-8", errors="replace")

    findings, file_set = model.Findings(), set(files)
    chain = static.DEFAULT_CHAIN_SCRIPT.rsplit("/", 1)[-1]
    py = pyscan.Analyzer([f for f in files if static._in_scope(f) and static._lang(root, f) == "python"],
                         read_text, findings, chain)
    py.file_set, py.id_samples = file_set, static._id_samples(root, files)
    _parsed, md_env = static._markdown_envs(root, files, shscan.ShellAnalyzer(py, findings, file_set, read_text, chain))
    return static._obligations(root, files, md_env)


def static_artifacts(root=None) -> dict:
    """The distinct file path patterns the producers' obligation templates declare, as the artifact check's static
    half (tests/artifact_graph/static_half.py) reads them, with the templates and declarations behind them.
    It is not the "artifacts" count of the traced check, which needs the replays; the label says so."""
    root = _root(root)
    files = _tracked(root)
    with _load(root / ARTIFACT_PACKAGE, "artifact_graph", package=True) as name:
        try:
            obligations = _obligations(root, files, name)
        except Exception as exc:  # noqa: BLE001
            raise FactError(f"the static half ({ARTIFACT_PACKAGE}/static_half.py) failed: "
                            f"{type(exc).__name__}: {exc}") from exc
    declarations = [a for ob in obligations for a in ob["artifacts"]]
    if not declarations:
        raise FactError("the static half found no obligation template with an artifact in commands/*.md")
    return {"label": ARTIFACT_LABEL, "obligation_templates": len(obligations),
            "artifact_declarations": len(declarations),
            "declared_file_artifacts": len({a["path"] for a in declarations if a.get("path")})}


# ---------------------------------------------------------------------------------------------
# 5. test functions and test files, counted statically
# ---------------------------------------------------------------------------------------------

def count_tests(root=None) -> dict:
    """Test files (git-tracked test_*.py or *_test.py at any depth, tests/generated/ left out) and test functions
    (a def named test_* at module or class level, not inside a function) in hooks/tests and in tests, counted
    from the syntax trees. Parametrization is not expanded, so this is not the number pytest reports."""
    root = _root(root)
    out = {}
    for key, prefix in (("hooks_tests", "hooks/tests"), ("tests", "tests")):
        files = [p for p in _tracked(root, prefix) if not p.startswith("tests/generated/")
                 and any(fnmatch.fnmatch(Path(p).name, pat) for pat in ("test_*.py", "*_test.py"))]
        if not files:
            raise FactError(f"no test file under {prefix}/ in the git index of {root}")
        out[key] = {"files": len(files), "test_functions": sum(_count_test_functions(_parse(root, p)) for p in files)}
    return out


# ---------------------------------------------------------------------------------------------
# 6. hook registrations and 7. enforcement strength
# ---------------------------------------------------------------------------------------------

GATE_SCRIPT = "scripts/check-enforcement-evidence.py"
LEDGER = "docs/ENFORCEMENT-LEDGER.md"


def hook_registrations(root=None) -> dict:
    """Hook entries per event in the tracked settings.json: one entry is one command object under
    `hooks.<event>[].hooks[]`."""
    try:
        hooks = _mapping(json.loads(_tracked_settings_text(_root(root)))).get("hooks")
    except ValueError as exc:
        raise FactError(f"tracked settings.json is not JSON: {exc}") from exc
    if not isinstance(hooks, dict) or not hooks:
        raise FactError("tracked settings.json: `hooks` is missing or not a non-empty object")
    bad = [event for event, groups in hooks.items() if not isinstance(groups, list)]
    if bad:
        raise FactError(f"tracked settings.json: hooks[{bad[0]!r}] is not a list")
    by_event = {e: sum(len(g.get("hooks") or []) for g in groups if isinstance(g, dict)) for e, groups in hooks.items()}
    return {"entries": sum(by_event.values()), "by_event": dict(sorted(by_event.items())), "events": len(by_event)}


def _settings_triples(gate, root: Path) -> set[tuple[str, str, str]]:
    """The (event, matcher, hook file) triples of the tracked settings.json, by the gate's own reader, whose
    `read_json` in this run's throwaway copy of the gate answers with the index blob."""
    text = _tracked_settings_text(root)

    def read_tracked(path):
        try:
            return json.loads(text)
        except ValueError as exc:
            raise gate.Fail(f"cannot read/parse JSON {path}: {exc}") from exc

    gate.read_json = read_tracked
    try:
        return gate.settings_triples("git index :settings.json")
    except gate.Fail as exc:
        raise FactError(f"tracked settings.json: {exc}") from exc


def _ledger_counts(gate, root: Path) -> tuple[list[dict], dict]:
    """(the ledger's registered-hook rows, {behavior, proof_layer: {each value of its closed set: count}})."""
    try:
        registered = gate.ledger_tables(str(_need(root, LEDGER)))["registered"]
    except gate.Fail as exc:
        raise FactError(str(exc)) from exc
    if registered is None or not registered["rows"]:
        raise FactError(f"{LEDGER}: no registered-hook table (the one with an event_class column) or it has no rows")
    counts = {}
    for field in ("behavior", "proof_layer"):
        if field not in registered["columns"]:
            raise FactError(f"{LEDGER}: the registered-hook table has no `{field}` column")
        allowed, seen = gate.DECLARED_SCHEMA[field], Counter((r.get(field) or "").strip() for r in registered["rows"])
        if set(seen) - set(allowed):
            raise FactError(f"{LEDGER}: {field} values {sorted(set(seen) - set(allowed))} are outside the closed "
                            f"set {allowed} of {GATE_SCRIPT}")
        counts[field] = {v: seen.get(v, 0) for v in allowed}
    return registered["rows"], counts


def enforcement_strength(root=None) -> dict:
    """The registered-hook rows of docs/ENFORCEMENT-LEDGER.md by behavior and by proof layer, parsed by
    scripts/check-enforcement-evidence.py's own `ledger_tables` against its DECLARED_SCHEMA (every value listed,
    0 where no row has it). A row set that differs from the tracked settings.json's hooks is an error: the
    page says one row per registered hook."""
    root = _root(root)
    with _load(_need(root, GATE_SCRIPT), "enforcement_gate") as gate:
        lost = [n for n in ("settings_triples", "ledger_tables", "DECLARED_SCHEMA", "Fail") if not hasattr(gate, n)]
        if lost:
            raise FactError(f"{GATE_SCRIPT} no longer has {lost[0]}")
        rows, counts = _ledger_counts(gate, root)
        derived = _settings_triples(gate, root)
    published = {tuple((r.get(c) or "").strip() for c in ("event_class", "matcher", "hook")) for r in rows}
    if published != derived:
        raise FactError(f"{LEDGER} registered-hook rows differ from the tracked settings.json's hooks "
                        f"({len(derived - published)} unlisted, {len(published - derived)} stale), "
                        f"e.g. {sorted(derived ^ published)[:5]}")
    return {"rows": len(rows), "by_behavior": counts["behavior"], "by_proof_layer": counts["proof_layer"]}


# ---------------------------------------------------------------------------------------------
# 8. the commands table and the cast of agents
# ---------------------------------------------------------------------------------------------

SUMMARY_MAX = 160
COMMAND_GROUPS = ("Spec", "Develop", "Ship", "Quality", "Control")
_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
# Names the front page does not show: an optional module's own name, a tool the harness borrowed a
# word from, a model id. A summary that holds one makes its table uncomputable.
INTERNAL_NAME = re.compile(r"(?i)\b(?:paseo|unfuddle)\b|\bgpt-\w|\bclaude-(?:opus|sonnet|haiku|fable)\b|\b(?:codex|o\d)-mini\b")


def _front(root: Path, rel: str) -> dict:
    match = _FRONTMATTER.match(_read(root, rel))
    if not match:
        raise FactError(f"{rel}: no YAML frontmatter")
    front = _yaml(match.group(1), f"the frontmatter of {rel}")
    if not isinstance(front, dict):
        raise FactError(f"{rel}: the frontmatter is not a mapping")
    return front


def _roster(root: Path, directory: str) -> list[tuple[str, dict]]:
    """(path, frontmatter) of each tracked <directory>/*.md file, README and INDEX left out, by path."""
    names = sorted(p for p in _tracked(root, directory)
                   if p.count("/") == 1 and p.endswith(".md") and Path(p).stem.upper() not in ("README", "INDEX"))
    if not names:
        raise FactError(f"no {directory[:-1]} file ({directory}/*.md) in the git index of {root}")
    return [(rel, _front(root, rel)) for rel in names]


def _summary(front: dict, rel: str) -> str:
    """The frontmatter `summary`, verbatim: one line of at most SUMMARY_MAX characters, no internal name.
    It is never cut: one that breaks a rule is an error naming the file."""
    summary = front.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise FactError(f"{rel}: the frontmatter has no summary")
    if "\n" in summary.strip() or summary != summary.strip():
        raise FactError(f"{rel}: the summary must be one line with no surrounding space")
    if len(summary) > SUMMARY_MAX:
        raise FactError(f"{rel}: the summary has {len(summary)} characters, more than {SUMMARY_MAX}; shorten it")
    name = INTERNAL_NAME.search(summary)
    if name:
        raise FactError(f"{rel}: the summary names {name.group(0)!r}, an internal name the front page does not show")
    return summary


def _command_row(rel: str, front: dict) -> dict:
    human, hint, group, module = (front.get(k) for k in ("disable-model-invocation", "argument-hint", "group", "module"))
    if human is not None and not isinstance(human, bool):
        raise FactError(f"{rel}: disable-model-invocation is {human!r}, not true or false")
    if hint is not None and not isinstance(hint, (str, list)):
        raise FactError(f"{rel}: argument-hint is {hint!r}, not text")
    if group not in COMMAND_GROUPS:
        raise FactError(f"{rel}: the group is {group!r}, not one of {', '.join(COMMAND_GROUPS)}")
    if module is not None and (not isinstance(module, str) or not module.strip()):
        raise FactError(f"{rel}: the module is {module!r}, not a name")
    hint = "[" + ", ".join(str(x) for x in hint) + "]" if isinstance(hint, list) else hint
    return {"name": Path(rel).stem, "argument_hint": hint or None, "human_only": human is True,
            "summary": _summary(front, rel), "group": group, "module": module}


def command_rows(root=None) -> list[dict]:
    """The commands table, one row per commands/*.md (README and INDEX left out), by name: name, argument_hint
    (a YAML list rebuilt as "[a, b]"), human_only (`disable-model-invocation: true`), summary (verbatim),
    group (one of COMMAND_GROUPS) and module (the optional module it belongs to, else None)."""
    return sorted((_command_row(rel, front) for rel, front in _roster(_root(root), "commands")),
                  key=lambda r: r["name"])


def agent_rows(root=None) -> list[dict]:
    """The cast of agents, one row per agents/*.md (README and INDEX left out), by name: name (frontmatter
    `name`, which must be the file name) and summary (verbatim)."""
    rows = []
    for rel, front in _roster(_root(root), "agents"):
        if front.get("name") != Path(rel).stem:
            raise FactError(f"{rel}: the frontmatter name is {front.get('name')!r}, not {Path(rel).stem!r}")
        rows.append({"name": Path(rel).stem, "summary": _summary(front, rel)})
    return sorted(rows, key=lambda r: r["name"])


# ---------------------------------------------------------------------------------------------
# 9. what CI enforces: claims over the test sources, each needing the workflow to run its test
# ---------------------------------------------------------------------------------------------

ARTIFACT_CHECK_TEST = "tests/test_artifact_graph.py"
ARTIFACT_CHECK_MODULE = "tests/artifact_graph/check.py"
FAULTS_TEST = "tests/replay/test_faults.py"
_CLAIM_COMPLIANT = "a compliant replay of each pipeline meets no gate block, no hook error, and reaches its terminal"
_CLAIM_NO_CLASS = "no blocking site may lack a clearing class (a site of class \"-\" fails the suite)"
_CLAIM_WEAKER = "a replay that reaches a blocking site with no class fails the suite"
_CLAIM_ARTIFACT = "the artifact check asserts no violation and keeps no exception list"
_CLAIM_FAULTS = ("an injected fault is returned by a gate to the actor that produced the faulted artifact, which "
                 "repairs it with no human action, and the pipeline reaches its terminal")
_CLAIM_UNIT = ("the unit suite (pytest over hooks/tests and tests) runs in the baseline job on every Python version "
               "of its matrix, and a failing test fails the job")
_EXCEPTION_NAME = re.compile(r"(?i)exception|exempt|waiv|suppress|allowlist|whitelist|grandfather|"
                             r"known[_-]?(?:violation|issue|failure)|expected[_-]?viol|baseline[_-]?viol")
_RUN_ASSERTS = (("no hook error", r"not \w+\.hook_errors"), ("reaches its terminal", r"\w+\.reached\(\)"))
_REPAIR_ASSERTS = (
    ("a gate returned the fault", r"r\.blocks"),
    ("the block lands on the faulted artifact's producer", r"agent in expected"),
    ("the producer's first stop is returned", r"mine and mine\[0\]\['blocked'\]"),
    ("no block lands on another actor", r"not others"),
    ("the producer's next stop passes", r"not mine\[-1\]\['blocked'\] and mine\[-1\]\['active'\]"),
    ("the producer writes the repair after its returned stop", r"repaired"),
    ("the faulted agent repaired", r"f\['repaired'\]"),
    ("no human event after the injection", r"not human_events\(r, injected\)"),
)


def _verdict(claim: str, file: str, missing, **extra) -> dict:
    """holds is true exactly when nothing is missing: evidence not found means the claim is not asserted."""
    return {"holds": not missing, "claim": claim, "file": file, "missing": list(missing), **extra}


def _missing_asserts(fn: ast.AST, checks, owner: str) -> list[str]:
    """One message per (what, pattern) of `checks` that no assertion of `fn` matches whole."""
    tests = [ast.unparse(a.test) for a in _asserts(fn)]
    return [f"{owner} asserts nothing shaped `{pattern}` ({what})" for what, pattern in checks
            if not any(re.fullmatch(pattern, t) for t in tests)]


def _over_cases(fn: ast.AST) -> bool:
    return any("parametrize" in ast.unparse(d) and "CASES" in ast.unparse(d) for d in fn.decorator_list)


def _skips(fn: ast.AST) -> bool:
    return any(re.search(r"\bpytest\.(?:skip|xfail|importorskip)\b|\bmark\.(?:skip|skipif|xfail)\b", ast.unparse(n))
               for n in ast.walk(fn) if isinstance(n, (ast.Call, ast.Attribute)))


def _compliant_replays(root: Path) -> dict:
    """tests/replay/test_pipelines.py: test_compliant_run runs every compliant scenario in every settings mode,
    cannot skip, asserts `not r.blocks`, `not r.hook_errors` and `r.reached()`, and suite.TEN is asserted covered."""
    rel, tree = REPLAY_PIPELINES_TEST, _parse(root, REPLAY_PIPELINES_TEST)
    fn = _function(tree, "test_compliant_run")
    if fn is None:
        return _verdict(_CLAIM_COMPLIANT, rel, [f"no function test_compliant_run in {rel}"])
    missing = _missing_asserts(fn, (("no gate block", r"not \w+\.blocks"),) + _RUN_ASSERTS, "test_compliant_run")
    missing += [] if _over_cases(fn) else ["test_compliant_run is not parametrized over CASES"]
    missing += ["test_compliant_run can skip or xfail"] if _skips(fn) else []
    try:
        _cases_run_every_scenario_in_every_mode(root)
    except FactError as exc:
        missing.append(str(exc))
    every = _function(tree, "test_every_pipeline_has_a_compliant_scenario")
    if every is None or _missing_asserts(every, (("", r"set\(suite\.TEN\) <= \w+"),), ""):
        missing.append("no assertion that every pipeline of suite.TEN has a compliant scenario")
    return _verdict(_CLAIM_COMPLIANT, rel, missing)


def _asserts_no_dash_site(tree: ast.Module) -> bool:
    """An assertion over the enumerated sites that none has class "-"."""
    for fn in _functions(tree):
        assigned = _assigned(fn)
        for a in _asserts(fn):
            names = {n.id for n in ast.walk(a.test) if isinstance(n, ast.Name)}
            text = ast.unparse(a.test) + " " + " ".join(assigned.get(n, "") for n in names)
            if re.search(r"\.of\(\w+\)\s*[!=]=\s*[\"']-[\"']", text) and "sites" in text:
                return True
    return False


def _appends_on_a_dash_class(fn: ast.AST) -> bool:
    """An `if "-" in <classes>:` whose <classes> is built from the sites' classes (`.of(`) and whose body appends."""
    built = _assigned(fn)
    for node in (n for n in ast.walk(fn) if isinstance(n, ast.If)):
        m = re.fullmatch(r"[\"']-[\"'] in (\w+)", ast.unparse(node.test))
        if m and ".of(" in built.get(m.group(1), "") and ".append(" in "".join(ast.unparse(b) for b in node.body):
            return True
    return False


def _no_class_site_may_exist(root: Path) -> dict:
    """tests/replay/test_no_dead_end.py: an assertion that no enumerated site has class "-". `weaker` is what the
    suite asserts: a check that fails a replay reaching such a site, in a test that asserts its failures empty."""
    tree = _parse(root, DEAD_END_TEST)
    defs = _functions(tree, ast.FunctionDef)
    consumed = any(ast.unparse(a.test) == "not bad" for fn in defs if fn.name.startswith("test_") for a in _asserts(fn))
    weaker = _verdict(_CLAIM_WEAKER, DEAD_END_TEST, [] if consumed and any(map(_appends_on_a_dash_class, defs)) else [
        "no check that fails a replay reaching a site of class \"-\" (an `if \"-\" in <classes>` appending a "
        "failure that a test asserts empty)"])
    return _verdict(_CLAIM_NO_CLASS, DEAD_END_TEST, [] if _asserts_no_dash_site(tree) else [
        "no assertion in the dead-end test that no enumerated site has class \"-\"; the suite prints those sites "
        "and fails only when a replay reaches one"], weaker=weaker)


def _defined_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        return [node.id]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    return [node.arg] if isinstance(node, ast.arg) else []


def _violations_asserted_whole(fn: ast.AST) -> list[str]:
    hit = next((a for a in _asserts(fn) if re.fullmatch(r"not \w+", ast.unparse(a.test))), None)
    if hit is None:
        return ["test_no_violation asserts no `not <violations>`"]
    name = ast.unparse(hit.test)[4:]
    origin = _assigned(fn).get(name, "")
    return [] if re.fullmatch(r"\w+\[['\"]violations['\"]\]", origin) else [
        f"the asserted `{name}` is not taken whole from the check's violations (it is `{origin}`)"]


def _artifact_check_clean(root: Path) -> dict:
    """tests/test_artifact_graph.py: test_no_violation asserts `not vs` for `vs = check["violations"]` taken whole
    and cannot skip, and neither it nor tests/artifact_graph/check.py names an exception list (waiver ...)."""
    rel = ARTIFACT_CHECK_TEST
    fn = _function(_parse(root, rel), "test_no_violation")
    if fn is None:
        return _verdict(_CLAIM_ARTIFACT, rel, [f"no function test_no_violation in {rel}"])
    missing = _violations_asserted_whole(fn) + (["test_no_violation can skip or xfail"] if _skips(fn) else [])
    missing += [f"{module}:{node.lineno}: `{n}` looks like an exception list"
                for module in (rel, ARTIFACT_CHECK_MODULE) for node in ast.walk(_parse(root, module))
                for n in _defined_names(node) if _EXCEPTION_NAME.search(n)]
    return _verdict(_CLAIM_ARTIFACT, rel, missing)


def _calls_the_helper(nodes) -> bool:
    return any(isinstance(n, ast.Call) and _call_name(n) == "_returned_and_repaired"
               for node in nodes for n in ast.walk(node))


def _treated_apart(test: ast.AST) -> tuple[set[str], list[str]]:
    """(fault ids the test does not run through _returned_and_repaired, problems). A call made outside every
    `if fault == "<id>":` covers all ids; one made only in such an if's else branch covers all but that id."""
    if any(isinstance(n, ast.Expr) and _calls_the_helper([n]) for n in test.body):
        return set(), []
    apart: set[str] = set()
    for node in (n for n in test.body if isinstance(n, ast.If) and _calls_the_helper([n])):
        m = re.fullmatch(r"fault == ['\"]([^'\"]+)['\"]", ast.unparse(node.test))
        if not (m and _calls_the_helper(node.orelse) and not _calls_the_helper(node.body)):
            return set(), ["cannot tell for which faults the test calls _returned_and_repaired"]
        apart.add(m.group(1))
    if not _calls_the_helper(test.body):
        return apart, ["test_fault_returns_to_its_producer never calls _returned_and_repaired"]
    return apart, []


def _fault_table(tree: ast.Module) -> list[str]:
    node = _module_value(tree, "FAULTS")
    table = [k.value for k in node.keys if _is_fault_id(k)] if isinstance(node, ast.Dict) else []
    if not table or len(table) != len(node.keys):
        raise FactError(f"{FAULTS_TEST}: FAULTS is no table keyed by fault ids (F<number>[letters])")
    return table


def _fault_cases(tree: ast.Module, test: ast.AST) -> list[str]:
    cases = _module_value(tree, "CASES")
    iters = [ast.unparse(g.iter) for g in cases.generators] if isinstance(cases, ast.ListComp) else None
    missing = [] if iters == ["FAULTS", "suite.SETTINGS"] else [f"CASES is not FAULTS x suite.SETTINGS (it iterates {iters})"]
    return missing + ([] if _over_cases(test) else ["test_fault_returns_to_its_producer is not parametrized over CASES"])


def _faults_returned_and_repaired(root: Path) -> dict:
    """tests/replay/test_faults.py: test_fault_returns_to_its_producer runs every fault of FAULTS in every settings
    mode through _returned_and_repaired (but the ones it treats apart), which asserts that a gate returned the
    fault to the faulted artifact's producer and no one else, that its first stop was returned and its next
    passed, that it wrote the repair and that no human event followed; the test asserts no hook error and the
    terminal, and neither can skip. `ids` lists the faults that go through it."""
    rel, tree = FAULTS_TEST, _parse(root, FAULTS_TEST)
    table = _fault_table(tree)
    test, helper = _function(tree, "test_fault_returns_to_its_producer"), _function(tree, "_returned_and_repaired")
    if test is None or helper is None:
        gone = "test_fault_returns_to_its_producer" if test is None else "_returned_and_repaired"
        return _verdict(_CLAIM_FAULTS, rel, [f"no function {gone} in {rel}"])
    apart, missing = _treated_apart(test)
    unknown = sorted(apart - set(table))
    missing += [f"the test treats apart {unknown}, which FAULTS does not list"] if unknown else []
    missing += _fault_cases(tree, test) + _missing_asserts(helper, _REPAIR_ASSERTS, "_returned_and_repaired")
    missing += _missing_asserts(test, _RUN_ASSERTS, "test_fault_returns_to_its_producer")
    if _skips(test) or _skips(helper):
        missing.append("test_fault_returns_to_its_producer or _returned_and_repaired can skip or xfail")
    covered = [i for i in table if i not in apart]
    missing += [] if covered else ["no fault of FAULTS goes through _returned_and_repaired"]
    return _verdict(_CLAIM_FAULTS, rel, missing, ids=covered)


# ---- 9a. does the CI workflow really run the test? -----------------------------------------
# Only the plain form .github/workflows/baseline.yml uses counts; anything else fails closed. The step's run
# block is ONE `python3 -m pytest` (or `pytest`) command of plain paths and options from a short list that
# narrow nothing (_FLAG, _VALUE), with no shell syntax and no PYTEST_ADDOPTS anywhere; a path is the test or a
# directory holding it and no --ignore covers it; the step has no continue-on-error, `if`, working-directory
# or shell other than bash, and the workflow and job no `defaults`; the job has no continue-on-error and an
# `if` only when it is the baseline job's own draft skip or made of always(), !cancelled(), success() and
# `needs.<job>.result == 'success'` of a job it needs that passes these rules too; a matrix that splits the
# tests over shards (an env value `${{ matrix.K }}/N`) lists the shards 1..N.

_DRAFT_SKIP = "github.event_name != 'pull_request' || !github.event.pull_request.draft"
_SHELL_SYNTAX = re.compile(r"[;&|<>`$\\()#'\"\n]")
_PYTEST = (["python3", "-m", "pytest"], ["python", "-m", "pytest"], ["pytest"])
_FLAG = re.compile(r"-q+|-v+|-s|-x|-r[a-zA-Z]+")
_PATH = r"\w[\w.-]*(?:/[\w.-]+)*"
_VALUE = {"-p": r"no:[\w-]+", "-n": r"\w+", "--dist": r"\w+", "--durations": r"\d+", "--tb": r"\w+", "--ignore": _PATH}


def _expression(value) -> str:
    return " ".join(re.sub(r"^\$\{\{\s*(.*?)\s*\}\}$", r"\1", str(value).strip(), flags=re.S).split())


def _option(word: str, rest: list[str]):
    """(name, value) of an option of _VALUE whose value fits it, taking a separate value from `rest`; else None."""
    name, eq, value = word.partition("=")
    if name in _VALUE and not eq and rest:
        value, eq = rest.pop(0), "="
    return (name, value) if name in _VALUE and eq and re.fullmatch(_VALUE[name], value) else None


def _pytest_args(run: str) -> tuple[list[str], list[str], str | None]:
    """(paths, ignored paths, None) of a run block that is one plain pytest command, else ([], [], why not)."""
    words = [] if _SHELL_SYNTAX.search(run.strip()) else run.split()
    head = next((h for h in _PYTEST if words[:len(h)] == h), None)
    if head is None:
        return [], [], "its run block is not one plain pytest command"
    paths, ignores, rest = [], [], words[len(head):]
    while rest:
        word = rest.pop(0)
        option = _option(word, rest)
        if option:
            ignores += [option[1]] if option[0] == "--ignore" else []
        elif re.fullmatch(_PATH, word):
            paths.append(word)
        elif not _FLAG.fullmatch(word):
            return [], [], f"`{word}` is neither a plain path nor an option this check knows to narrow nothing"
    return paths, ignores, None


def _under(target: str, path: str) -> bool:
    return target == path or target.startswith(path + "/")


def _named_paths(run: str) -> list[str]:
    """The plain paths that follow `pytest` on a line of a run block that is not one plain command: which tests
    such a step reaches, so that its rejection is reported for those tests only. It never makes a step count."""
    return [w for line in run.splitlines() if "pytest" in line
            for w in line.split("pytest", 1)[1].split() if re.fullmatch(_PATH, w)]


def _gating_needs(job_id: str, job: dict, reference_if: str) -> tuple[list[str], list[str]]:
    """(the needed jobs this job's run depends on, why its `if` makes it conditional)."""
    needs = [job["needs"]] if isinstance(job.get("needs"), str) else list(job.get("needs") or [])
    expr = _expression(job["if"]) if "if" in job else None
    if expr is None or (expr == reference_if and reference_if in ("", _DRAFT_SKIP)):
        return needs, []
    gating = []
    for conjunct in (c.strip() for c in expr.split("&&")):
        m = re.fullmatch(r"needs\.([\w-]+)\.result == 'success'", conjunct)
        if conjunct not in ("always()", "!cancelled()", "success()") and not (m and m.group(1) in needs):
            return gating, [f"job `{job_id}` is conditional (`if: {expr}`)"]
        gating += [m.group(1)] if m else []
    return gating, []


def _shard_problems(doc: dict, job_id: str, job: dict) -> list[str]:
    matrix = _mapping(_mapping(job.get("strategy")).get("matrix"))
    env = {**_mapping(doc.get("env")), **_mapping(job.get("env"))}
    for step in job.get("steps") or []:
        env.update(_mapping(_mapping(step).get("env")))
    out = []
    for name, value in env.items():
        m = re.fullmatch(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}/(\d+)", str(value).strip())
        listed = matrix.get(m.group(1)) if m else None
        if m and (listed != list(range(1, int(m.group(2)) + 1)) or {"include", "exclude"} & set(matrix)):
            out.append(f"job `{job_id}` splits the tests over {m.group(2)} shards ({name}) but its matrix "
                       f"`{m.group(1)}` is {listed}, not 1..{m.group(2)}")
    return out


def _job_problems(doc: dict, job_id: str, reference_if: str, seen: tuple = ()) -> list[str]:
    """Why a job might not run, or not fail the workflow, on a change that runs the baseline job (9a)."""
    job = doc["jobs"].get(job_id)
    if not isinstance(job, dict):
        return [f"no job `{job_id}`"]
    if job_id in seen:
        return []
    needs, out = _gating_needs(job_id, job, reference_if)
    if job.get("continue-on-error") not in (None, False):
        out.insert(0, f"job `{job_id}` has continue-on-error")
    for need in needs:
        out += [f"needed job: {p}" for p in _job_problems(doc, need, reference_if, seen + (job_id,))]
    return out + _shard_problems(doc, job_id, job)


def _step_problems(doc: dict, job: dict, step: dict) -> list[str]:
    """Why a step might fail without failing its job, or run something its text does not show."""
    shell = step.get("shell")
    checks = (
        (step.get("working-directory") not in (None, ".", "./"),
         f"runs in another directory (working-directory: {step.get('working-directory')})"),
        (shell not in (None, "bash") or "defaults" in doc or "defaults" in job,
         f"uses a shell (`{shell}`) or `defaults` whose handling of a failing command is not shown"),
        (step.get("continue-on-error") not in (None, False), "can fail without failing the job (continue-on-error)"),
        ("if" in step, "can fail without failing the job (the step has an `if`)"),
        (any("PYTEST_ADDOPTS" in _mapping(scope.get("env")) for scope in (doc, job, step)),
         "PYTEST_ADDOPTS adds options this check does not see"))
    return [why for bad, why in checks if bad]


def _step_outcome(doc: dict, job_id: str, step: dict, targets: tuple, reference_if: str):
    """("runs", the step's ignores), ("ignores", why) or ("rejected", why) for a pytest step; None for a step
    that runs no pytest or does not reach every target."""
    run, where = step.get("run"), f"`{step.get('name') or 'a step'}` of job `{job_id}`"
    if not isinstance(run, str) or "pytest" not in run:
        return None
    paths, ignores, odd = _pytest_args(run)
    if not all(any(_under(t, p) for p in paths or _named_paths(run)) for t in targets):
        return None
    if odd:
        return "rejected", f"the pytest step {where}: {odd}"
    left_out = sorted({f"--ignore={i}" for i in ignores for t in targets if _under(t, i)})
    if left_out:
        return "ignores", f"the one that reaches it, {where}, ignores it ({', '.join(left_out)})"
    why = _step_problems(doc, doc["jobs"][job_id], step) + _job_problems(doc, job_id, reference_if)
    return ("rejected", f"the pytest step {where}: " + "; ".join(why)) if why else ("runs", sorted(ignores))


def _ci_runs(root: Path, targets: tuple, *, only_job: str | None = None) -> dict:
    """Whether .github/workflows/baseline.yml runs pytest over every path of `targets` in one step that qualifies
    (9a), in any job or `only_job`: holds, job, ignores (what that step leaves out), missing (why not)."""
    doc = _workflow(root)
    reference = _mapping(doc["jobs"].get(doc.get("name")))
    reference_if = _expression(reference["if"]) if "if" in reference else ""
    found: dict[str, list] = {"runs": [], "ignores": [], "rejected": []}
    for job_id, job in doc["jobs"].items():
        steps = (job.get("steps") or []) if isinstance(job, dict) and only_job in (None, job_id) else []
        for kind, detail in filter(None, (_step_outcome(doc, job_id, s, targets, reference_if)
                                          for s in steps if isinstance(s, dict))):
            found[kind].append((job_id, detail))
    if found["runs"]:
        return {"holds": True, "job": found["runs"][0][0], "ignores": found["runs"][0][1], "missing": []}
    where = " and ".join(targets)
    missing = [why for _job, why in found["rejected"]]
    missing += [f"no step runs pytest over {where}: {why}" for _job, why in found["ignores"]]
    scope = f"job `{only_job}`" if only_job else f"any job of {BASELINE_WORKFLOW}"
    return {"holds": False, "job": None, "ignores": [],
            "missing": missing or [f"no step of {scope} runs pytest over {where} (directly or through its directory)"]}


def _unit_suite_on_every_version(root: Path) -> dict:
    """.github/workflows/baseline.yml: the job named like the workflow runs pytest over hooks/tests and tests in a
    step that qualifies (9a), in every leg of its matrix (`versions`); `ignored` lists what the step leaves out."""
    versions = ci_python_versions(root)  # FactError when the matrix cannot be read: the caller reports it
    wf = _ci_runs(root, ("hooks/tests", "tests"), only_job=_workflow(root)["name"])
    return _verdict(_CLAIM_UNIT, BASELINE_WORKFLOW, wf["missing"], versions=versions, ignored=wf["ignores"])


def _guarded(predicate, root: Path, rel: str, claim: str, ci_target: str | None = None) -> dict:
    """The predicate's verdict (a source it cannot read is evidence not found), made false, its weaker claim too,
    unless the workflow runs `ci_target`."""
    try:
        verdict = predicate(root)
    except FactError as exc:
        verdict = _verdict(claim, rel, [str(exc)])
        if predicate is _no_class_site_may_exist:
            verdict["weaker"] = _verdict(_CLAIM_WEAKER, rel, [str(exc)])
    if ci_target is None:
        return verdict
    try:
        wf = _ci_runs(root, (ci_target,))
    except FactError as exc:
        wf = {"holds": False, "missing": [str(exc)]}
    if not wf["holds"]:
        reasons = [f"CI does not run it: {m}" for m in wf["missing"]]
        for v in filter(None, (verdict, verdict.get("weaker"))):
            v.update(holds=False, missing=v["missing"] + reasons)
    return verdict


def ci_enforces(root=None) -> dict:
    """What CI fails on, as five claims, each a dict: holds, claim, file, missing (non-empty exactly when holds
    is false), plus `ids` (the faults that go through the repair check), `weaker` (the suite's weaker dead-end
    claim), `versions` and `ignored` (the unit suite's matrix and left-out paths). The first four also need
    the workflow to run their test (9a): otherwise `missing` ends with "CI does not run it: <why>". This reads
    the sources and the workflow only; whether the suite passes is what CI runs."""
    root = _root(root)
    return {
        "compliant_replays_clean": _guarded(_compliant_replays, root, REPLAY_PIPELINES_TEST, _CLAIM_COMPLIANT,
                                            REPLAY_PIPELINES_TEST),
        "no_site_without_class": _guarded(_no_class_site_may_exist, root, DEAD_END_TEST, _CLAIM_NO_CLASS, DEAD_END_TEST),
        "artifact_check_clean": _guarded(_artifact_check_clean, root, ARTIFACT_CHECK_TEST, _CLAIM_ARTIFACT,
                                         ARTIFACT_CHECK_TEST),
        "faults_returned_and_repaired": _guarded(_faults_returned_and_repaired, root, FAULTS_TEST, _CLAIM_FAULTS,
                                                 FAULTS_TEST),
        "unit_suite_on_every_version": _guarded(_unit_suite_on_every_version, root, BASELINE_WORKFLOW, _CLAIM_UNIT),
    }


# ---------------------------------------------------------------------------------------------
# all facts, and the JSON dump
# ---------------------------------------------------------------------------------------------

FACTS = {f.__name__: f for f in (ci_python_versions, replay_suite_size, blocking_sites, static_artifacts, count_tests,
                                 hook_registrations, enforcement_strength, command_rows, agent_rows, ci_enforces)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Print the facts README.md and docs/status.md show, as JSON.")
    ap.add_argument("--root", default=None, help="the top of the git work tree to read (default: this repository)")
    ap.add_argument("--fact", action="append", choices=list(FACTS), help="only this fact (repeatable)")
    args = ap.parse_args(argv)
    try:
        facts = {name: FACTS[name](args.root) for name in (args.fact or FACTS)}
    except FactError as exc:
        print(f"readme_facts: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"facts": facts}, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
