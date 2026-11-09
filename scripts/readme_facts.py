#!/usr/bin/env python3
"""Every number and table row the README shows, derived from this repository's files.

Description: One module, one function per fact, one source per function. No number is typed here:
  each is counted or read from a committed file, or produced by the suite's own enumerator. A fact
  that cannot be derived raises FactError naming the missing input; none returns zero, or a value
  from an earlier run, in its place. Standard library plus PyYAML (already a dependency); Python
  3.10 to 3.12; no network; nothing here needs pytest.

Usage: readme_facts.py [--root DIR] [--fact NAME]... [--timings]   # print the facts as JSON
       readme_facts.py --list                                       # the fact names

Exit codes: 0 = printed, 2 = a fact could not be derived (the message names the input)

Facts (function -> what it returns):
  ci_python_versions        the baseline CI job's Python versions, in order
  replay_suite_size         pipelines, compliant scenarios, settings modes, fault classes, regressions
  blocking_sites            the registered hooks' blocking sites, per class, enumerated by the suite
  static_artifacts          what the artifact check's static half derives, and what it cannot count
  count_tests               test functions and test files, hooks/tests and tests, counted statically
  hook_registrations        hook entries per event in the tracked settings.json; registered files
  enforcement_strength      the ledger's registered-hook rows by behavior and by proof layer
  command_rows              the commands table: name, argument hint, human-only flag, one-line summary
  ci_enforces               five predicates over the test sources and the CI workflow, each with the assertion's file:line

WHAT "READ" MEANS HERE. File contents come from the working tree, so an edit shows at once. Which
files exist comes from the git index (`git ls-files`): an untracked scratch file is not a test, a
command or a hook. settings.json is the exception, read as the index blob (`git cat-file blob
:settings.json`), the way scripts/verify-claims.sh hands it to scripts/check-enforcement-evidence.py:
a working copy on a machine may carry machine-only additions (an enabled module's hooks) that no
commit holds. `root` must therefore be the top of a git work tree with the needed files staged.

NOTHING IS REPLAYED. The replay suite and the artifact check's traced replays need a mount namespace
and take about an hour; no function here runs either. blocking_sites runs the suite's static
enumerator (tests/replay/sites.py) and the suite's relay probe, which executes a copy of a hook with
a stub child in a throwaway directory; static_artifacts runs a part of the static half.

NO BYTE-CODE. The suite's modules are loaded from `root` by path under throwaway names with byte-code
writing off, so a run leaves no __pycache__ in the tree.
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
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class FactError(RuntimeError):
    """A fact could not be derived. The message names the missing or unusable input."""


# ---------------------------------------------------------------------------------------------
# inputs: files, git, parsing
# ---------------------------------------------------------------------------------------------

def _root(root) -> Path:
    path = Path(root) if root is not None else REPO_ROOT
    if not path.is_dir():
        raise FactError(f"root {path} is not a directory")
    return path.resolve()


def _need(root: Path, rel: str) -> Path:
    path = root / rel
    if not path.is_file():
        raise FactError(f"missing input {rel} (looked in {root})")
    return path


def _read(root: Path, rel: str) -> str:
    path = _need(root, rel)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FactError(f"cannot read {rel}: {exc}") from exc


def _parse(root: Path, rel: str, text: str | None = None) -> ast.Module:
    try:
        return ast.parse(_read(root, rel) if text is None else text, filename=rel)
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
    out = _git(root, "ls-files", "-z", "--", *prefixes).decode("utf-8")
    return sorted(p for p in out.split("\0") if p)


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
def _load_file(path: Path, hint: str):
    """A module loaded from `path` under a throwaway name; registered while it is used because a
    dataclass looks its own module up."""
    name = f"_readme_facts_{hint}_{next(_loads)}"
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise FactError(f"cannot load {path} as a Python module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        try:
            with _no_bytecode():
                spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 - whatever the source did, it is an input we cannot use
            raise FactError(f"cannot load {path}: {type(exc).__name__}: {exc}") from exc
        yield module
    finally:
        sys.modules.pop(name, None)


@contextlib.contextmanager
def _load_package(directory: Path, hint: str):
    """A package (its relative imports resolve inside it) loaded from `directory` under a throwaway name."""
    init = directory / "__init__.py"
    if not init.is_file():
        raise FactError(f"missing input {init}")
    name = f"_readme_facts_{hint}_{next(_loads)}"
    spec = importlib.util.spec_from_file_location(name, str(init), submodule_search_locations=[str(directory)])
    if spec is None or spec.loader is None:
        raise FactError(f"cannot load {directory} as a Python package")
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    try:
        try:
            with _no_bytecode():
                spec.loader.exec_module(package)
        except Exception as exc:  # noqa: BLE001
            raise FactError(f"cannot load {directory}: {type(exc).__name__}: {exc}") from exc
        with _no_bytecode():
            yield package, name
    finally:
        for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
            del sys.modules[key]


# ---------------------------------------------------------------------------------------------
# AST helpers over the test sources
# ---------------------------------------------------------------------------------------------

def _module_value(tree: ast.Module, name: str):
    """The value expression of the module-level assignment to `name`, or None."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node.value
    return None


def _literal(node: ast.AST, rel: str, what: str):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError) as exc:
        raise FactError(f"{rel}:{getattr(node, 'lineno', '?')}: {what} is not a literal ({exc})") from exc


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _function(tree: ast.Module, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _asserts(node: ast.AST) -> list[ast.Assert]:
    return sorted((n for n in ast.walk(node) if isinstance(n, ast.Assert)), key=lambda n: n.lineno)


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


def ci_python_versions(root=None) -> list[str]:
    """Python versions of the baseline CI job, in the order its matrix lists them, e.g. ["3.10", ...].

    Source: `jobs.<job>.strategy.matrix.python-version` of .github/workflows/baseline.yml, where <job>
    is the job named like the workflow itself (`name: baseline`). It is accepted only if a
    `actions/setup-python` step of that job takes `${{ matrix.python-version }}` (a matrix nothing
    uses is no run), if it lists plain strings (an unquoted 3.10 is read by YAML as 3.1), and if the
    matrix has no include/exclude (their effect on the legs is not derived here).
    """
    root = _root(root)
    doc = _yaml(_read(root, BASELINE_WORKFLOW), BASELINE_WORKFLOW)
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
        raise FactError(f"{BASELINE_WORKFLOW}: no `jobs` mapping")
    job_id = doc.get("name")
    job = doc["jobs"].get(job_id)
    if not isinstance(job, dict):
        raise FactError(f"{BASELINE_WORKFLOW}: no job `{job_id}` (the job named like the workflow)")
    matrix = ((job.get("strategy") or {}).get("matrix")) if isinstance(job.get("strategy"), dict) else None
    if not isinstance(matrix, dict) or "python-version" not in matrix:
        raise FactError(f"{BASELINE_WORKFLOW}: job `{job_id}` has no strategy.matrix.python-version")
    if "include" in matrix or "exclude" in matrix:
        raise FactError(f"{BASELINE_WORKFLOW}: the matrix of `{job_id}` has include/exclude; "
                        "the legs are not just the python-version list")
    versions = matrix["python-version"]
    if not isinstance(versions, list) or not versions:
        raise FactError(f"{BASELINE_WORKFLOW}: strategy.matrix.python-version of `{job_id}` is not a non-empty list")
    for v in versions:
        if not isinstance(v, str) or not re.fullmatch(r"\d+\.\d+", v):
            raise FactError(f"{BASELINE_WORKFLOW}: matrix python-version entry {v!r} is not a quoted \"M.N\" string")
    uses = [s for s in job.get("steps") or []
            if isinstance(s, dict) and str(s.get("uses", "")).startswith("actions/setup-python@")
            and re.fullmatch(r"\$\{\{\s*matrix\.python-version\s*\}\}",
                             str((s.get("with") or {}).get("python-version", "")).strip())]
    if not uses:
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


def _scenarios(root: Path) -> tuple[list[dict], tuple, tuple]:
    """(compliant scenarios, SETTINGS, TEN) read from tests/replay/suite.py without importing it."""
    tree = _parse(root, REPLAY_SUITE)
    compliant = _module_value(tree, "COMPLIANT")
    if not isinstance(compliant, (ast.Tuple, ast.List)) or not compliant.elts:
        raise FactError(f"{REPLAY_SUITE}: no COMPLIANT tuple of Scenario(...) literals")
    fields = ("name", "driver", "args", "pipelines", "cost")
    scenarios = []
    for elt in compliant.elts:
        if not (isinstance(elt, ast.Call) and _call_name(elt) == "Scenario"):
            raise FactError(f"{REPLAY_SUITE}:{elt.lineno}: COMPLIANT holds something other than a Scenario(...) literal")
        values = {f: _literal(a, REPLAY_SUITE, f"Scenario argument {f}") for f, a in zip(fields, elt.args)}
        for kw in elt.keywords:
            values[kw.arg] = _literal(kw.value, REPLAY_SUITE, f"Scenario argument {kw.arg}")
        if not values.get("name"):
            raise FactError(f"{REPLAY_SUITE}:{elt.lineno}: a Scenario without a name")
        values.setdefault("pipelines", ())
        scenarios.append(values)
    out = []
    for name in ("SETTINGS", "TEN"):
        node = _module_value(tree, name)
        value = _literal(node, REPLAY_SUITE, name) if node is not None else None
        if not isinstance(value, tuple) or not value or not all(isinstance(x, str) for x in value):
            raise FactError(f"{REPLAY_SUITE}: no {name} tuple of strings")
        out.append(value)
    return scenarios, out[0], out[1]


def _cases_run_every_scenario_in_every_mode(root: Path) -> tuple[ast.Module, ast.AST]:
    """tests/replay/test_pipelines.py builds its CASES from suite.COMPLIANT x suite.SETTINGS."""
    tree = _parse(root, REPLAY_PIPELINES_TEST)
    cases = _module_value(tree, "CASES")
    if not isinstance(cases, ast.ListComp):
        raise FactError(f"{REPLAY_PIPELINES_TEST}: CASES is no list comprehension")
    iters = [ast.unparse(g.iter) for g in cases.generators]
    if iters != ["suite.COMPLIANT", "suite.SETTINGS"]:
        raise FactError(f"{REPLAY_PIPELINES_TEST}:{cases.lineno}: CASES iterates {iters}, "
                        "not suite.COMPLIANT then suite.SETTINGS: a scenario may not run in every mode")
    return tree, cases


def _fault_ids(root: Path) -> dict[str, list[str]]:
    """{class: [ids]}, the suite's numbered fault ids grouped by their number (F8, F8q -> class F8)."""
    files = [p for p in _tracked(root, REPLAY_DIR)
             if p.count("/") == 2 and fnmatch.fnmatch(p.rsplit("/", 1)[1], "test_*.py")]
    if not files:
        raise FactError(f"no test_*.py under {REPLAY_DIR} in the git index of {root}")
    found: set[str] = set()
    for rel in files:
        tree = _parse(root, rel)
        for node in tree.body:  # a module-level table keyed by fault id: FAULTS, _LOCK, SHAPES, E1
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if isinstance(value, ast.Dict):
                for key in value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str) and _FAULT_ID.fullmatch(key.value):
                        found.add(key.value)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) == "Scenario" and node.args:
                first = node.args[0]  # a fault's own scenario: Scenario("F8", ...)
                if isinstance(first, ast.Constant) and isinstance(first.value, str) and _FAULT_ID.fullmatch(first.value):
                    found.add(first.value)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):  # test_f5f_both_lanes_cut_...
                m = _FAULT_TEST.match(node.name)
                if m:
                    found.add(f"F{m.group(1)}{m.group(2)}")
    classes: dict[str, list[str]] = {}
    for fid in sorted(found, key=lambda s: (int(_FAULT_ID.fullmatch(s).group(1)), s)):
        classes.setdefault(f"F{_FAULT_ID.fullmatch(fid).group(1)}", []).append(fid)
    if not classes:
        raise FactError(f"no fault id (F<number>[letters]) named in the tests under {REPLAY_DIR}")
    return classes


def _regressions(root: Path) -> dict:
    """The defects tests/replay/test_regressions.py replays: the R-<letter><digit> ids its docstring names,
    each required to have a test (a test_r_<id>_ function, or the id in a string of the test code)."""
    tree = _parse(root, REPLAY_REGRESSIONS_TEST)
    doc = ast.get_docstring(tree) or ""
    ids = sorted(set(_REGRESSION_ID.findall(doc)))
    if not ids:
        raise FactError(f"{REPLAY_REGRESSIONS_TEST}: the module docstring names no R-<id> regression")
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    names = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    strings = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
    untested = [i for i in ids if not any(n.startswith("test_" + i.lower().replace("-", "_") + "_") for n in names)
                and not any(i in s for s in strings)]
    if untested:
        raise FactError(f"{REPLAY_REGRESSIONS_TEST}: named in the docstring but with no test: {untested}")
    return {"ids": ids, "test_functions": _count_test_functions(tree)}


def replay_suite_size(root=None) -> dict:
    """The replay suite's size, read from tests/replay without replaying anything.

    Sources and rules:
      pipelines            the distinct `pipelines` of the Scenario literals in suite.COMPLIANT
                           (tests/replay/suite.py), required to include every one of suite.TEN
      compliant_scenarios  len(suite.COMPLIANT)
      settings_modes       suite.SETTINGS, required to be what test_pipelines.CASES runs every
                           scenario under (CASES = suite.COMPLIANT x suite.SETTINGS)
      compliant_replays    compliant_scenarios x settings_modes
      fault_classes        the suite numbers its injected faults F1 ... F<n> with letters for variants
                           (F8, F8q ...). A fault id is counted when a test under tests/replay/test_*.py
                           names it as the key of a module-level table (FAULTS, _LOCK, SHAPES, E1), as the
                           name of a Scenario, or in a test function name test_f<id>_*. The class is
                           its number. `fault_class_variants` lists the ids of each class.
      regression_replays   the R-<letter><digit> defects the docstring of tests/replay/test_regressions.py
                           names (each must have a test there)
    """
    root = _root(root)
    scenarios, settings, ten = _scenarios(root)
    _cases_run_every_scenario_in_every_mode(root)
    pipelines = sorted({p for s in scenarios for p in s["pipelines"]})
    uncovered = [p for p in ten if p not in pipelines]
    if uncovered:
        raise FactError(f"{REPLAY_SUITE}: suite.TEN names {uncovered}, which no compliant scenario types")
    classes = _fault_ids(root)
    regressions = _regressions(root)
    return {
        "pipelines": len(pipelines),
        "pipeline_names": pipelines,
        "compliant_scenarios": len(scenarios),
        "settings_modes": list(settings),
        "compliant_replays": len(scenarios) * len(settings),
        "fault_classes": len(classes),
        "fault_class_variants": classes,
        "fault_ids": sum(len(v) for v in classes.values()),
        "regression_replays": len(regressions["ids"]),
        "regression_ids": regressions["ids"],
        "regression_test_functions": regressions["test_functions"],
    }


# ---------------------------------------------------------------------------------------------
# 3. the registered hooks' blocking sites
# ---------------------------------------------------------------------------------------------

SITES_MODULE = "tests/replay/sites.py"
DEAD_END_TEST = "tests/replay/test_no_dead_end.py"
SITE_CLASSES = ("G", "D", "H", "U", "-")  # the suite's own order (test_no_dead_end.Catalog.table)


def _read_tracked_settings(sites, root: Path) -> None:
    """Make the suite's enumerator (the throwaway copy of tests/replay/sites.py this run loaded) read
    settings.json as the index holds it: only that one file's open() is answered from the index blob,
    everything else opens as it did. The registered hooks are then the tracked ones even on a machine
    whose working settings.json carries an enabled module's hooks. Nothing is written for it."""
    text = _tracked_settings_text(root)
    settings = os.path.realpath(root / "settings.json")
    real_open = open

    def tracked_open(file, *args, **kwargs):
        if isinstance(file, (str, os.PathLike)) and os.path.realpath(file) == settings:
            return io.StringIO(text)
        return real_open(file, *args, **kwargs)

    sites.open = tracked_open  # shadows the builtin inside that module only


def blocking_sites(root=None) -> dict:
    """The blocking sites of the registered hooks, per class, enumerated from code. Replays nothing.

    Source: tests/replay/sites.py, the replay suite's own enumerator (`Enumerator`, `classify`,
    `relayed`), run the way tests/replay/test_no_dead_end.py's `Catalog` runs it (that class sits in a
    pytest module, so its few lines are repeated here, not imported): every path of every hook that the
    tracked settings.json registers, and of the modules and child processes it follows, that exits 2 or
    prints a block or deny decision; a child process counts only if its parent relays its exit 2.

    by_class      G own-obligation gate (the same actor's next action clears it), D denial of a forbidden
                  operation, H time-lock Stop block, U unreachable, "-" no class: the suite calls such a
                  site a dead end. The legend is the suite's own, read from the docstring of
                  tests/replay/test_no_dead_end.py.
    no_class      by_class["-"]. The suite does not assert that none exists; it asserts that no replay
                  reaches one. Whether a replay reaches one cannot be derived without replaying.
    no_class_reasons  the enumerator's stated reason per no-class site, counted.
    The probe `relayed` executes a copy of a hook with a stub child in a throwaway directory; that is
    not a replay and needs no mount namespace.
    """
    root = _root(root)
    _need(root, SITES_MODULE)
    docstring = ast.get_docstring(_parse(root, DEAD_END_TEST)) or ""
    legend = {m.group(1): m.group(2).strip().rstrip(";")
              for m in re.finditer(r"(?m)^ {2}([GDHU-]) {2}(\S.*)$", docstring)}
    with tempfile.TemporaryDirectory(prefix="readme-facts-") as relay, \
            _load_file(root / SITES_MODULE, "sites") as sites:
        try:
            _read_tracked_settings(sites, root)
            enum = sites.Enumerator(str(root))
            dropped = set()
            for parent, kids in enum.children.items():
                event = next((ev for ev, _ in enum.regs.get(parent, [])), "Stop")
                for kid in kids:
                    if not sites.relayed(str(root), parent, kid, event, os.path.join(relay, os.path.basename(kid))):
                        dropped.add(kid)
            found = [s for s in enum.sites() if s.file not in dropped]
            classified = [(s, sites.classify(enum, s)) for s in found]
        except FactError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise FactError(f"the suite's enumerator ({SITES_MODULE}) failed: {type(exc).__name__}: {exc}") from exc
        registered = sorted(enum.regs)
    if not registered:
        raise FactError(f"the tracked settings.json registers no hook file {SITES_MODULE} can follow")
    if not classified:
        raise FactError(f"{SITES_MODULE} found no blocking site in {len(registered)} registered hook files")
    counts = Counter(cls for _site, (cls, _why) in classified)
    unknown = sorted(set(counts) - set(SITE_CLASSES))
    if unknown:
        raise FactError(f"{SITES_MODULE} classified a site as {unknown}, outside {list(SITE_CLASSES)}")
    return {
        "sites": len(classified),
        "by_class": {c: counts.get(c, 0) for c in SITE_CLASSES},
        "no_class": counts.get("-", 0),
        "no_class_reasons": dict(sorted(Counter(why for _s, (cls, why) in classified if cls == "-").items())),
        "legend": legend,
        "registered_hook_files": len(registered),
        "hook_files_with_a_site": len({hook for s, _c in classified for hook, _ev, _m in s.regs}),
        "children_whose_exit_is_not_relayed": sorted(dropped),
        "replayed": False,
    }


# ---------------------------------------------------------------------------------------------
# 4. the artifacts the artifact check's static half derives
# ---------------------------------------------------------------------------------------------

ARTIFACT_PACKAGE = "tests/artifact_graph"

_STATIC_CAN_COUNT = (
    "obligation templates the command files embed, and the artifacts each declares (path pattern, kind)",
    "file operations (read, write, create, unlink, rename) at literal code sites, with their path patterns",
    "file operations whose path it could not resolve, with the reason",
)
_STATIC_CANNOT_COUNT = (
    "which files exist at run time: a path pattern with a hole (<*>) stands for any number of files, and "
    "most relations are partial",
    "the same artifact once: command texts spell one id as <ts> in /dev and <task> in /close, so one family "
    "of files appears under two patterns",
    "which relations are artifacts: the check joins a static relation to a traced artifact only when exactly "
    "one matches, and leaves out files present at replay start, tracked tree files, directories, git's own "
    "store and the user's own project files (tests/artifact_graph/check.py, rule (1))",
    "producers, consumers and deciding reads per artifact: those, and every violation, need the traced replays",
)


def static_artifacts(root=None, *, with_static_totals: bool = False) -> dict:
    """What the artifact check's static half derives about artifacts, and what it cannot count.

    Source: tests/artifact_graph/static_half.py. Default (about 0.1 s): the obligation declarations
    `derive()` records, built by the same functions in the same order as `derive()` (`_markdown_envs`,
    `_obligations`) over the tracked commands/*.md and agents/*.md, without the Python and shell walk
    that makes the rest of `derive()` take about 30 s. tests/test_readme_facts.py compares the two.
    With `with_static_totals=True` the whole `derive()` runs and its relation counts are added
    (it reads the working tree, as the suite does).

    The honest label of the number: `declared_file_artifacts` is the number of distinct file path
    patterns that producers' obligations declare. It is NOT the "artifacts" the CI job "artifact check
    (traced replays)" reports (check.py counts[\"artifacts\"]): that count exists only after the traced
    replays join their relations to the static ones. A count of the static relations' path patterns
    (`static_half.distinct_path_patterns`) is not an artifact count either; see `cannot_count`.
    """
    root = _root(root)
    files = _tracked(root)
    with _load_package(root / ARTIFACT_PACKAGE, "artifact_graph") as (pkg, name):
        try:
            static = sys.modules[f"{name}.static_half"]
            pyscan, shscan, model = (sys.modules[f"{name}.{m}"] for m in ("pyscan", "shscan", "model"))
        except KeyError as exc:
            raise FactError(f"{ARTIFACT_PACKAGE} does not load {exc} as the static half does") from exc
        missing = [n for n in ("_markdown_envs", "_obligations", "_id_samples", "_in_scope", "_lang", "derive")
                   if not hasattr(static, n)]
        if missing:
            raise FactError(f"{ARTIFACT_PACKAGE}/static_half.py no longer has {missing}; "
                            "readme_facts.static_artifacts follows derive() through them")
        try:
            file_set = set(files)

            def read_text(rel: str) -> str:
                return (root / rel).read_text(encoding="utf-8", errors="replace")

            findings = model.Findings()
            chain = static.DEFAULT_CHAIN_SCRIPT.rsplit("/", 1)[-1]
            scope = [f for f in files if static._in_scope(f)]
            py_files = [f for f in scope if static._lang(root, f) == "python"]
            py = pyscan.Analyzer(py_files, read_text, findings, chain)
            py.file_set = file_set
            py.id_samples = static._id_samples(root, files)
            shell = shscan.ShellAnalyzer(py, findings, file_set, read_text, chain)
            _parsed, md_env = static._markdown_envs(root, files, shell)
            obligations = static._obligations(root, files, md_env)
            totals = _static_totals(static, root) if with_static_totals else None
        except FactError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise FactError(f"the static half ({ARTIFACT_PACKAGE}/static_half.py) failed: "
                            f"{type(exc).__name__}: {exc}") from exc
    declarations = [a for ob in obligations for a in ob["artifacts"]]
    if not obligations or not declarations:
        raise FactError("the static half found no obligation template with an artifact in commands/*.md")
    paths = sorted({a["path"] for a in declarations if a.get("path")})
    return {
        "label": "file artifacts declared by the producers' obligation templates in commands/*.md, read "
                 "statically; not the artifact total the CI job \"artifact check (traced replays)\" reports",
        "obligation_templates": len(obligations),
        "artifact_declarations": len(declarations),
        "declared_by_kind": dict(sorted(Counter(a.get("kind") for a in declarations).items())),
        "declared_file_artifacts": len(paths),
        "declared_response_items": sum(1 for a in declarations if not a.get("path")),
        "declared_paths": paths,
        "can_count": list(_STATIC_CAN_COUNT),
        "cannot_count": list(_STATIC_CANNOT_COUNT),
        "static_half": totals,
    }


def _static_totals(static, root: Path) -> dict:
    summary = static.derive(root).summary
    keys = ("relations_by_op", "relations_by_resolution", "unresolved_by_reason", "distinct_paths", "relation_sites")
    absent = [k for k in keys if k not in summary]
    if absent:
        raise FactError(f"the static half's summary no longer has {absent}")
    return {
        "relations": sum(summary["relations_by_op"].values()),
        "relation_sites": summary["relation_sites"],
        "distinct_path_patterns": summary["distinct_paths"],
        "relations_by_resolution": summary["relations_by_resolution"],
        "unresolved_operations": sum(summary["unresolved_by_reason"].values()),
    }


# ---------------------------------------------------------------------------------------------
# 5. test functions and test files, counted statically
# ---------------------------------------------------------------------------------------------

_TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")


def count_tests(root=None) -> dict:
    """Test functions and test files in hooks/tests and in tests, counted statically.

    Rule: a test file is a git-tracked file under the directory, at any depth, named test_*.py or
    *_test.py (pytest's defaults, which pytest.ini does not change), leaving out tests/generated/ (opt-in
    skeletons the root conftest.py deselects). A test function is a def or async def named test_* at
    module level or in a class at any nesting, whatever the class is called, found in the file's syntax
    tree; a function defined inside another function is not one. Parametrization is not expanded and
    nothing is imported or collected, so this is not the number pytest reports. Shell test scripts
    (*.sh) are not counted.
    """
    root = _root(root)
    out = {}
    for key, prefix in (("hooks_tests", "hooks/tests"), ("tests", "tests")):
        files = [p for p in _tracked(root, prefix)
                 if any(fnmatch.fnmatch(p.rsplit("/", 1)[-1], pat) for pat in _TEST_FILE_PATTERNS)
                 and not p.startswith("tests/generated/")]
        if not files:
            raise FactError(f"no test file under {prefix}/ in the git index of {root}")
        out[key] = {"files": len(files), "test_functions": sum(_count_test_functions(_parse(root, p)) for p in files)}
    return out


# ---------------------------------------------------------------------------------------------
# 6. hook registrations and 7. enforcement strength (one reader: scripts/check-enforcement-evidence.py)
# ---------------------------------------------------------------------------------------------

GATE_SCRIPT = "scripts/check-enforcement-evidence.py"
LEDGER = "docs/ENFORCEMENT-LEDGER.md"


@contextlib.contextmanager
def _gate(root: Path):
    with _load_file(_need(root, GATE_SCRIPT), "enforcement_gate") as gate:
        for name in ("settings_triples", "ledger_tables", "DECLARED_SCHEMA", "Fail"):
            if not hasattr(gate, name):
                raise FactError(f"{GATE_SCRIPT} no longer has {name}")
        yield gate


def _settings_triples(gate, root: Path) -> set[tuple[str, str, str]]:
    """The (event, matcher, hook file) triples of the tracked settings.json, by the gate's own reader.
    The gate's `settings_triples` takes a path and reads it with its `read_json`; that function, in this
    run's throwaway copy of the gate, answers with the index blob, so no file is written for it."""
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


def hook_registrations(root=None) -> dict:
    """Hook entries per event in the tracked settings.json, and the hook files they register.

    Sources: the index blob of settings.json (`git cat-file blob :settings.json`, as scripts/verify-claims.sh
    reads it; the working file may carry machine-only additions) for the entries: one entry is one
    command object under `hooks.<event>[].hooks[]`. scripts/check-enforcement-evidence.py's
    `settings_triples` (the reader that gate and the ledger use) for `registered_hook_files`, the distinct
    script names; each must exist as hooks/<name> or scripts/<name> in the index.
    `distinct_rows` is what the gate derives (event, matcher, script) and the ledger has one row for;
    it equals `entries` unless a command is registered twice under one event and matcher.
    """
    root = _root(root)
    try:
        doc = json.loads(_tracked_settings_text(root))
    except ValueError as exc:
        raise FactError(f"tracked settings.json is not JSON: {exc}") from exc
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    if not isinstance(hooks, dict) or not hooks:
        raise FactError("tracked settings.json: `hooks` is missing or not a non-empty object")
    by_event: dict[str, int] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise FactError(f"tracked settings.json: hooks[{event!r}] is not a list")
        by_event[event] = sum(len(g.get("hooks") or []) for g in groups if isinstance(g, dict))
    with _gate(root) as gate:
        triples = _settings_triples(gate, root)
    tracked = set(_tracked(root, "hooks", "scripts"))
    scripts = sorted({script for _e, _m, script in triples})
    absent = [s for s in scripts if f"hooks/{s}" not in tracked and f"scripts/{s}" not in tracked]
    if absent:
        raise FactError(f"registered in the tracked settings.json but not in the index as hooks/ or scripts/: {absent}")
    return {
        "entries": sum(by_event.values()),
        "by_event": dict(sorted(by_event.items())),
        "events": len(by_event),
        "registered_hook_files": len(scripts),
        "distinct_rows": len(triples),
    }


def enforcement_strength(root=None) -> dict:
    """The registered-hook rows of docs/ENFORCEMENT-LEDGER.md by behavior, proof layer and exercise status.

    Source: the ledger, parsed by scripts/check-enforcement-evidence.py's own `ledger_tables` (the one
    reader of that ledger); the closed sets of values are that script's DECLARED_SCHEMA. Every set value
    is listed, with 0 where no row has it. A row with a blank or out-of-set value, or a row set that
    differs from the tracked settings.json's hooks (what the gate's --claims also checks), is an error.
    """
    root = _root(root)
    with _gate(root) as gate:
        try:
            registered = gate.ledger_tables(str(_need(root, LEDGER)))["registered"]
        except gate.Fail as exc:
            raise FactError(str(exc)) from exc
        if registered is None or not registered["rows"]:
            raise FactError(f"{LEDGER}: no registered-hook table (the one with an event_class column) or it has no rows")
        schema = gate.DECLARED_SCHEMA
        rows = registered["rows"]
        counts = {}
        for field in ("behavior", "proof_layer", "exercise_status"):
            if field not in registered["columns"]:
                raise FactError(f"{LEDGER}: the registered-hook table has no `{field}` column")
            allowed = schema[field]
            seen = Counter((r.get(field) or "").strip() for r in rows)
            bad = sorted(set(seen) - set(allowed))
            if bad:
                raise FactError(f"{LEDGER}: {field} values {bad} are outside the closed set {allowed} of {GATE_SCRIPT}")
            counts[field] = {v: seen.get(v, 0) for v in allowed}
        published = {((r.get("event_class") or "").strip(), (r.get("matcher") or "").strip(),
                      (r.get("hook") or "").strip()) for r in rows}
        derived = _settings_triples(gate, root)
    if published != derived:
        diff = sorted(derived ^ published)[:5]
        raise FactError(f"{LEDGER} registered-hook rows differ from the tracked settings.json's hooks "
                        f"({len(derived - published)} unlisted, {len(published - derived)} stale), e.g. {diff}")
    return {
        "rows": len(rows),
        "by_behavior": counts["behavior"],
        "by_proof_layer": counts["proof_layer"],
        "by_exercise_status": counts["exercise_status"],
    }


# ---------------------------------------------------------------------------------------------
# 8. the commands table
# ---------------------------------------------------------------------------------------------

COMMAND_SUMMARY_MAX = 100
_NOT_COMMANDS = {"README", "INDEX"}
_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
_PLACEHOLDER = re.compile(r"\S+\s+Command")
_ABBREVIATIONS = {"e.g", "i.e", "etc", "vs", "cf", "approx", "incl"}


def _first_sentence(text: str) -> str:
    """Text up to the first sentence end: ., ! or ? (then optional closing quotes/brackets) followed by
    white space or the end, outside `inline code`, not after an abbreviation such as e.g."""
    text = " ".join(text.split())
    in_code = False
    for i, ch in enumerate(text):
        if ch == "`":
            in_code = not in_code
        elif ch in ".!?" and not in_code:
            j = i + 1
            while j < len(text) and text[j] in "\"')]*":
                j += 1
            if j < len(text) and not text[j].isspace():
                continue
            word = text[:i].rsplit(" ", 1)[-1].lower().lstrip("(\"'")
            if word in _ABBREVIATIONS:
                continue
            return text[:j]
    return text


def _cut(text: str, limit: int) -> str:
    """`text` if it has at most `limit` characters; else its longest prefix of whole words that leaves room for
    a closing ellipsis, with the ellipsis, so the result has at most `limit` characters. A cut never leaves
    an inline-code span open."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    if not text[limit - 1].isspace():  # the cut fell inside a word: drop the part of it
        head = head.rsplit(" ", 1)[0] if " " in head else head
    if head.count("`") % 2:
        head = head[: head.rindex("`")]
    return head.rstrip(" ,;:-–—(") + "…"


def _body_first_sentence(body: str, rel: str) -> str:
    """The first sentence of the body's first paragraph: the first run of lines that are neither blank,
    a heading (#), a fence (```), a rule, nor a quote or comment opener."""
    lines, para, fenced = body.splitlines(), [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if not stripped or stripped.startswith(("#", ">", "<!--")) or re.fullmatch(r"[-*_=]{3,}", stripped):
            if para:
                break
            continue
        para.append(stripped)
    if not para:
        raise FactError(f"{rel}: no body text to take a summary from")
    return _first_sentence(" ".join(para))


def command_rows(root=None, max_len: int = COMMAND_SUMMARY_MAX) -> list[dict]:
    """The commands table, one row per file in commands/ (README and INDEX files left out), by name.

    Each row: name (the file name without .md, no slash), argument_hint (frontmatter `argument-hint`, a
    YAML list rebuilt as "[a, b]", else None), human_only (frontmatter `disable-model-invocation` is
    true; an agent may call the command when the key is absent or false), summary, summary_source.

    summary: the first sentence of the frontmatter description (see _first_sentence), without a final
    full stop, cut on a word boundary so that it has at most `max_len` characters, the last being an
    ellipsis when it was cut. A description is a placeholder when it is exactly one word followed by
    the word Command (a YAML-quoted "Pull Command": `^\\S+\\s+Command$`); the summary is then taken the same
    way from the body: the first sentence of its first paragraph after the frontmatter, headings
    and fenced code skipped. summary_source is "description" or "body". Rows are sorted by name; there is
    no grouping and no category. The summary is the text as written: a pipe or an angle bracket in it
    is for the caller to escape when it renders a table.
    """
    root = _root(root)
    names = sorted(p for p in _tracked(root, "commands")
                   if p.count("/") == 1 and p.endswith(".md") and Path(p).stem.upper() not in _NOT_COMMANDS)
    if not names:
        raise FactError(f"no command file (commands/*.md) in the git index of {root}")
    rows = []
    for rel in names:
        text = _read(root, rel)
        match = _FRONTMATTER.match(text)
        if not match:
            raise FactError(f"{rel}: no YAML frontmatter")
        front = _yaml(match.group(1), f"the frontmatter of {rel}")
        if not isinstance(front, dict):
            raise FactError(f"{rel}: the frontmatter is not a mapping")
        description = front.get("description")
        if not isinstance(description, str) or not description.strip():
            raise FactError(f"{rel}: the frontmatter has no description")
        human = front.get("disable-model-invocation")
        if human is not None and not isinstance(human, bool):
            raise FactError(f"{rel}: disable-model-invocation is {human!r}, not true or false")
        hint = front.get("argument-hint")
        if isinstance(hint, list):
            hint = "[" + ", ".join(str(x) for x in hint) + "]"
        elif hint is not None and not isinstance(hint, str):
            raise FactError(f"{rel}: argument-hint is {hint!r}, not text")
        if _PLACEHOLDER.fullmatch(description.strip()):
            sentence, source = _body_first_sentence(text[match.end():], rel), "body"
        else:
            sentence, source = _first_sentence(description), "description"
        sentence = sentence[:-1] if sentence.endswith(".") and not sentence.endswith("..") else sentence
        rows.append({"name": Path(rel).stem, "argument_hint": hint or None, "human_only": human is True,
                     "summary": _cut(sentence, max_len), "summary_source": source})
    return sorted(rows, key=lambda r: r["name"])


# ---------------------------------------------------------------------------------------------
# 9. what CI enforces, as predicates over the test sources
# ---------------------------------------------------------------------------------------------

ARTIFACT_CHECK_TEST = "tests/test_artifact_graph.py"
ARTIFACT_CHECK_MODULE = "tests/artifact_graph/check.py"
_CLAIM_COMPLIANT = "a compliant replay of each pipeline meets no gate block, no hook error, and reaches its terminal"
_CLAIM_NO_CLASS = "no blocking site may lack a clearing class (a site of class \"-\" fails the suite)"
_CLAIM_ARTIFACT = "the artifact check asserts no violation and keeps no exception list"
FAULTS_TEST = "tests/replay/test_faults.py"
_CLAIM_FAULTS = ("an injected fault is returned by a gate to the actor that produced the faulted artifact, which "
                 "repairs it with no human action, and the pipeline reaches its terminal")
_CLAIM_UNIT = ("the unit suite (pytest over hooks/tests and tests) runs in the baseline job on every Python version "
               "of its matrix, and a failing test fails the job")
_EXCEPTION_NAME = re.compile(r"(?i)exception|exempt|waiv|suppress|allowlist|whitelist|grandfather|"
                             r"known[_-]?(?:violation|issue|failure)|expected[_-]?viol|baseline[_-]?viol")


def _verdict(holds: bool, file: str, line: int | None, claim: str, assertions=(), missing=(), **extra) -> dict:
    return {"holds": holds, "claim": claim, "file": file, "line": line,
            "assertions": list(assertions), "missing": list(missing), **extra}


def _skipped(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        text = ast.unparse(node) if isinstance(node, (ast.Call, ast.Attribute)) else ""
        if re.search(r"\bpytest\.(?:skip|xfail|importorskip)\b|\bmark\.(?:skip|skipif|xfail)\b", text):
            return True
    return False


def _compliant_replays(root: Path) -> dict:
    claim = _CLAIM_COMPLIANT
    rel = REPLAY_PIPELINES_TEST
    tree = _parse(root, rel)
    missing, found = [], []
    fn = _function(tree, "test_compliant_run")
    if fn is None:
        return _verdict(False, rel, None, claim, missing=[f"no function test_compliant_run in {rel}"])
    asserts = _asserts(fn)
    for what, pattern in (("no gate block", r"not \w+\.blocks"), ("no hook error", r"not \w+\.hook_errors"),
                          ("reaches its terminal", r"\w+\.reached\(\)")):
        hit = next((a for a in asserts if re.fullmatch(pattern, ast.unparse(a.test))), None)
        if hit is None:
            missing.append(f"test_compliant_run asserts nothing shaped `{pattern}` ({what})")
        else:
            found.append({"what": what, "line": hit.lineno, "source": ast.unparse(hit.test)})
    if not any("parametrize" in ast.unparse(d) and "CASES" in ast.unparse(d) for d in fn.decorator_list):
        missing.append("test_compliant_run is not parametrized over CASES")
    try:
        _cases_run_every_scenario_in_every_mode(root)
    except FactError as exc:
        missing.append(str(exc))
    if _skipped(fn):
        missing.append("test_compliant_run can skip or xfail")
    every = _function(tree, "test_every_pipeline_has_a_compliant_scenario")
    covered = [a for a in _asserts(every) if re.fullmatch(r"set\(suite\.TEN\) <= \w+", ast.unparse(a.test))] if every else []
    if not covered:
        missing.append("no assertion that every pipeline of suite.TEN has a compliant scenario")
    else:
        found.append({"what": "every pipeline of suite.TEN has a compliant scenario", "line": covered[0].lineno,
                      "source": ast.unparse(covered[0].test)})
    return _verdict(not missing, rel, found[0]["line"] if found else None, claim, found, missing)


def _no_class_site_may_exist(root: Path) -> dict:
    claim = _CLAIM_NO_CLASS
    rel = DEAD_END_TEST
    tree = _parse(root, rel)
    hit = None
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        assigned = {t.id: ast.unparse(a.value) for a in ast.walk(fn) if isinstance(a, ast.Assign)
                    for t in a.targets if isinstance(t, ast.Name)}
        for a in _asserts(fn):
            names = {n.id for n in ast.walk(a.test) if isinstance(n, ast.Name)}
            text = ast.unparse(a.test) + " " + " ".join(assigned.get(n, "") for n in names)
            if re.search(r"\.of\(\w+\)\s*[!=]=\s*[\"']-[\"']", text) and "sites" in text:
                hit = (fn.name, a)
                break
        if hit:
            break
    # What the suite does assert about a site with no class: a replay that reaches one fails. That is an
    # `if "-" in <classes>:` whose <classes> is built from the sites' classes (`catalog.of(s)`) and whose body
    # appends a failure, in a function whose result a test asserts empty (`assert not bad`).
    weaker = None
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        built = {t.id: ast.unparse(a.value) for a in ast.walk(fn) if isinstance(a, ast.Assign)
                 for t in a.targets if isinstance(t, ast.Name)}
        for node in ast.walk(fn):
            if isinstance(node, ast.If):
                m = re.fullmatch(r"[\"']-[\"'] in (\w+)", ast.unparse(node.test))
                if m and ".of(" in built.get(m.group(1), "") and ".append(" in "".join(ast.unparse(b) for b in node.body):
                    weaker = node
    consumers = [a.lineno for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef) and fn.name.startswith("test_")
                 for a in _asserts(fn) if ast.unparse(a.test) == "not bad"]
    extra = {"weaker": {
        "holds": bool(weaker and consumers),
        "claim": "a replay that reaches a blocking site with no class fails the suite",
        "file": rel, "line": weaker.lineno if weaker else None,
        "asserted_at_lines": consumers,
        "missing": [] if weaker and consumers else ["no check that fails a replay reaching a site of class \"-\" "
                                                       "(an `if \"-\" in <classes>` appending a failure that a test "
                                                       "asserts empty)"],
    }}
    if hit is None:
        return _verdict(False, rel, None, claim,
                        missing=["no assertion in the dead-end test that no enumerated site has class \"-\"; "
                                 "the suite prints those sites and fails only when a replay reaches one"], **extra)
    return _verdict(True, rel, hit[1].lineno, claim, [{"what": "no site of class \"-\"", "line": hit[1].lineno,
                                                       "source": ast.unparse(hit[1].test)}], **extra)


def _artifact_check_clean(root: Path) -> dict:
    claim = _CLAIM_ARTIFACT
    rel = ARTIFACT_CHECK_TEST
    tree = _parse(root, rel)
    missing, found = [], []
    fn = _function(tree, "test_no_violation")
    if fn is None:
        return _verdict(False, rel, None, claim, missing=[f"no function test_no_violation in {rel}"])
    source = {t.id: a.value for a in ast.walk(fn) if isinstance(a, ast.Assign) for t in a.targets
              if isinstance(t, ast.Name)}
    hit = next((a for a in _asserts(fn) if re.fullmatch(r"not \w+", ast.unparse(a.test))), None)
    if hit is None:
        missing.append("test_no_violation asserts no `not <violations>`")
    else:
        name = ast.unparse(hit.test)[4:]
        origin = ast.unparse(source[name]) if name in source else ""
        if not re.fullmatch(r"\w+\[['\"]violations['\"]\]", origin):
            missing.append(f"the asserted `{name}` is not taken whole from the check's violations (it is `{origin}`)")
        else:
            found.append({"what": "no violation", "line": hit.lineno, "source": f"{ast.unparse(hit.test)}  # {name} = {origin}"})
    if _skipped(fn):
        missing.append("test_no_violation can skip or xfail")
    for module in (rel, ARTIFACT_CHECK_MODULE):
        for node in ast.walk(_parse(root, module)):
            names = []
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.append(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
            elif isinstance(node, ast.arg):
                names.append(node.arg)
            for n in names:
                if _EXCEPTION_NAME.search(n):
                    missing.append(f"{module}:{node.lineno}: `{n}` looks like an exception list")
    if not missing:
        found.append({"what": "no identifier of an exception list", "line": None,
                      "source": f"no name matching /{_EXCEPTION_NAME.pattern}/ in {rel} or {ARTIFACT_CHECK_MODULE}"})
    return _verdict(not missing, rel, hit.lineno if hit is not None else None, claim, found, missing)


def _fault_table(tree: ast.Module) -> list[str]:
    node = _module_value(tree, "FAULTS")
    ids = [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
           and _FAULT_ID.fullmatch(k.value)] if isinstance(node, ast.Dict) else []
    if not ids or len(ids) != len(node.keys):
        raise FactError(f"{FAULTS_TEST}: FAULTS is no table keyed by fault ids (F<number>[letters])")
    return ids


def _treated_apart(test: ast.AST) -> tuple[set[str], list[str]]:
    """(fault ids the test does not run through _returned_and_repaired, problems). A call made outside every
    `if fault == "<id>":` covers all ids; one made only in such an if's else branch covers all but that id."""
    calls = lambda nodes: any(isinstance(n, ast.Call) and _call_name(n) == "_returned_and_repaired"  # noqa: E731
                              for node in nodes for n in ast.walk(node))
    if any(isinstance(n, ast.Expr) and calls([n]) for n in test.body):
        return set(), []
    apart: set[str] = set()
    for node in test.body:
        if isinstance(node, ast.If) and calls(node.orelse) and not calls(node.body):
            m = re.fullmatch(r"fault == ['\"]([^'\"]+)['\"]", ast.unparse(node.test))
            if m:
                apart.add(m.group(1))
                continue
        if isinstance(node, ast.If) and calls([node]):
            return set(), ["cannot tell for which faults the test calls _returned_and_repaired"]
    return apart, ([] if calls(test.body) else ["test_fault_returns_to_its_producer never calls _returned_and_repaired"])


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


def _faults_returned_and_repaired(root: Path) -> dict:
    claim, rel = _CLAIM_FAULTS, FAULTS_TEST
    tree = _parse(root, rel)
    table = _fault_table(tree)
    test = _function(tree, "test_fault_returns_to_its_producer")
    helper = _function(tree, "_returned_and_repaired")
    if test is None or helper is None:
        return _verdict(False, rel, None, claim, missing=[f"no function {'test_fault_returns_to_its_producer' if test is None else '_returned_and_repaired'} in {rel}"])
    missing, found = [], []
    cases = _module_value(tree, "CASES")
    iters = [ast.unparse(g.iter) for g in cases.generators] if isinstance(cases, ast.ListComp) else None
    if iters != ["FAULTS", "suite.SETTINGS"]:
        missing.append(f"CASES is not FAULTS x suite.SETTINGS (it iterates {iters})")
    if not any("parametrize" in ast.unparse(d) and "CASES" in ast.unparse(d) for d in test.decorator_list):
        missing.append("test_fault_returns_to_its_producer is not parametrized over CASES")
    apart, problems = _treated_apart(test)
    missing += problems
    unknown = sorted(apart - set(table))
    if unknown:
        missing.append(f"the test treats apart {unknown}, which FAULTS does not list")
    helper_asserts = _asserts(helper)
    for what, pattern in _REPAIR_ASSERTS:
        hit = next((a for a in helper_asserts if re.fullmatch(pattern, ast.unparse(a.test))), None)
        if hit is None:
            missing.append(f"_returned_and_repaired asserts nothing shaped `{pattern}` ({what})")
        else:
            found.append({"what": what, "line": hit.lineno, "source": ast.unparse(hit.test)})
    for what, pattern in (("no hook error", r"not \w+\.hook_errors"), ("reaches its terminal", r"\w+\.reached\(\)")):
        hit = next((a for a in _asserts(test) if re.fullmatch(pattern, ast.unparse(a.test))), None)
        if hit is None:
            missing.append(f"test_fault_returns_to_its_producer asserts nothing shaped `{pattern}` ({what})")
        else:
            found.append({"what": what, "line": hit.lineno, "source": ast.unparse(hit.test)})
    if _skipped(test) or _skipped(helper):
        missing.append("test_fault_returns_to_its_producer or _returned_and_repaired can skip or xfail")
    covered = [i for i in table if i not in apart]
    if not covered:
        missing.append("no fault of FAULTS goes through _returned_and_repaired")
    return _verdict(not missing, rel, found[0]["line"] if found else None, claim, found, missing,
                    ids=covered, treated_apart=sorted(apart), table=table)


def _unit_suite_on_every_version(root: Path) -> dict:
    claim, rel = _CLAIM_UNIT, BASELINE_WORKFLOW
    versions = ci_python_versions(root)  # FactError when the matrix cannot be read: the caller reports it
    text = _read(root, rel)
    doc = _yaml(text, rel)
    job = doc["jobs"][doc["name"]]
    missing, hit = [], None
    if job.get("continue-on-error") not in (None, False):
        missing.append(f"job `{doc['name']}` has continue-on-error")
    for step in job.get("steps") or []:
        run = str(step.get("run", "")) if isinstance(step, dict) else ""
        words = run.split()
        if "pytest" in words and "hooks/tests" in words and "tests" in words:
            if step.get("continue-on-error") not in (None, False) or "if" in step or re.search(r"\|\|\s*(?:true|:)", run):
                missing.append(f"the pytest step `{step.get('name')}` can fail without failing the job (continue-on-error, if, or `|| true`)")
            else:
                hit = (step, words)
            break
    if hit is None and not missing:
        missing.append(f"no step of job `{doc['name']}` runs pytest over hooks/tests and tests")
    line = next((i for i, l in enumerate(text.splitlines(), 1) if "pytest hooks/tests tests" in l), None)
    found = []
    if hit is not None:
        found.append({"what": "pytest over hooks/tests and tests in every matrix leg", "line": line,
                      "source": f"{hit[0].get('name')}: " + " ".join(hit[1][:4])})
    return _verdict(not missing, rel, line, claim, found, missing, versions=versions,
                    ignored=sorted(w.split("=", 1)[1] for w in (hit[1] if hit else []) if w.startswith("--ignore=")))


def ci_enforces(root=None) -> dict:
    """What CI enforces, as five predicates over the test sources and the CI workflow. Each is a dict: holds (bool), claim, file,
    line (the line of the asserting statement), assertions (what was found, with lines), missing (what could
    not be found; non-empty whenever holds is false). Fail closed: evidence not found means holds is false.
    This reads the sources only; whether the suite passes is what CI runs.

    compliant_replays_clean  tests/replay/test_pipelines.py: test_compliant_run, parametrized over every
        compliant scenario in every settings mode, asserts `not r.blocks`, `not r.hook_errors` and
        `r.reached()`, cannot skip, and test_every_pipeline_has_a_compliant_scenario asserts that
        suite.TEN is covered.
    no_site_without_class  tests/replay/test_no_dead_end.py: an assertion over the enumerated sites that
        none has class "-". The suite makes a weaker assertion (a replay that reaches such a site fails),
        reported under `weaker`; holds is false while only the weaker one exists.
    artifact_check_clean  tests/test_artifact_graph.py: test_no_violation asserts `not vs` for
        `vs = check["violations"]` taken whole, cannot skip, and neither that file nor
        tests/artifact_graph/check.py names anything like an exception list (waiver, exemption,
        known-violation, allowlist ...; the pattern is in the `source` of the last assertion).
    faults_returned_and_repaired  tests/replay/test_faults.py: test_fault_returns_to_its_producer, parametrized
        over every fault of its FAULTS table in every settings mode, calls _returned_and_repaired for each
        fault but the ones it treats apart (`treated_apart`, the stale report nothing produced), and that
        helper asserts that a gate returned the fault, that the block landed on the producer of the faulted
        artifact and on no one else, that the producer's first stop was returned and its next passed, that it
        wrote the repair and that no human event followed; the test asserts no hook error and the terminal.
        `ids` lists the faults that go through it, `table` every fault of FAULTS. The fault ids the suite
        numbers beyond FAULTS (F4, F5, F6, F8 ...) have tests of their own that this does not read.
    unit_suite_on_every_version  .github/workflows/baseline.yml: the job named like the workflow runs pytest
        over hooks/tests and tests in a step that is unconditional and cannot fail without failing the
        job, in every leg of the matrix ci_python_versions reads (`versions`); `ignored` lists the paths the
        step leaves out (--ignore=...), which other jobs or nobody run.
    """
    root = _root(root)
    return {
        "compliant_replays_clean": _guarded(_compliant_replays, root, REPLAY_PIPELINES_TEST, _CLAIM_COMPLIANT),
        "no_site_without_class": _guarded(_no_class_site_may_exist, root, DEAD_END_TEST, _CLAIM_NO_CLASS),
        "artifact_check_clean": _guarded(_artifact_check_clean, root, ARTIFACT_CHECK_TEST, _CLAIM_ARTIFACT),
        "faults_returned_and_repaired": _guarded(_faults_returned_and_repaired, root, FAULTS_TEST, _CLAIM_FAULTS),
        "unit_suite_on_every_version": _guarded(_unit_suite_on_every_version, root, BASELINE_WORKFLOW, _CLAIM_UNIT),
    }


def _guarded(predicate, root: Path, rel: str, claim: str) -> dict:
    """The predicate's verdict; a source it cannot read or parse is evidence not found: holds is false."""
    try:
        return predicate(root)
    except FactError as exc:
        return _verdict(False, rel, None, claim, missing=[str(exc)])


# ---------------------------------------------------------------------------------------------
# all facts, and the JSON dump
# ---------------------------------------------------------------------------------------------

FACTS = {
    "ci_python_versions": ci_python_versions,
    "replay_suite_size": replay_suite_size,
    "blocking_sites": blocking_sites,
    "static_artifacts": static_artifacts,
    "count_tests": count_tests,
    "hook_registrations": hook_registrations,
    "enforcement_strength": enforcement_strength,
    "command_rows": command_rows,
    "ci_enforces": ci_enforces,
}


def all_facts(root=None, only=None) -> tuple[dict, dict]:
    """(facts, seconds): every fact by function name, or the names in `only`, and the wall time of each."""
    names = list(FACTS) if not only else list(only)
    unknown = [n for n in names if n not in FACTS]
    if unknown:
        raise FactError(f"unknown fact {unknown}; the facts are {list(FACTS)}")
    facts, seconds = {}, {}
    for name in names:
        started = time.monotonic()
        try:
            facts[name] = FACTS[name](root)
        except FactError as exc:
            raise FactError(f"{name}: {exc}") from exc
        seconds[name] = round(time.monotonic() - started, 3)
    return facts, seconds


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Print the README's facts as JSON.")
    ap.add_argument("--root", default=None, help="the top of the git work tree to read (default: this repository)")
    ap.add_argument("--fact", action="append", metavar="NAME", help="only this fact (repeatable)")
    ap.add_argument("--timings", action="store_true", help="add the seconds each fact took")
    ap.add_argument("--list", action="store_true", help="print the fact names and stop")
    args = ap.parse_args(argv)
    if args.list:
        print("\n".join(FACTS))
        return 0
    try:
        facts, seconds = all_facts(args.root, args.fact)
    except FactError as exc:
        print(f"readme_facts: {exc}", file=sys.stderr)
        return 2
    out = {"facts": facts}
    if args.timings:
        out["seconds"] = {**seconds, "total": round(sum(seconds.values()), 3)}
    print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
