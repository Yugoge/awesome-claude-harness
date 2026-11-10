"""scripts/readme_facts.py: each fact equals an independent recount, moves when its input moves, and
names its input when it is missing.

For every fact three kinds of test:

* RECOUNT: the value on this repository equals a count the test makes another way (a regular
  expression over the text, `git`, the suite's own class imported here, the suite's own `derive()`);
* CHANGE: the needed files are copied to a scratch git repository under a temporary directory,
  one input is changed, and the value changes with it;
* MISSING: an input is left out (or broken) and FactError names it.

Nothing here replays the replay suite or runs the artifact check. Two tests are slow on purpose:
the suite's own catalog of blocking sites (about 8 s) and the static half's whole `derive()` (about
30 s), the second being what proves that `static_artifacts` is not a different count.
"""
from __future__ import annotations

import ast
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "readme_facts.py"

sys.dont_write_bytecode = True  # the module under test and the suite's modules leave no __pycache__
_spec = importlib.util.spec_from_file_location("readme_facts_under_test", SCRIPT)
rf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rf
_spec.loader.exec_module(rf)


# ---------------------------------------------------------------- scratch repositories

def git(root: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
    return done.stdout


def make_repo(tmp_path: Path, files: dict, name: str = "repo") -> Path:
    """A git work tree holding `files` ({relative path: text, or a Path of this repository to copy}), all staged."""
    root = tmp_path / name
    root.mkdir(parents=True)
    for rel, content in files.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Path) and content.is_dir():
            shutil.copytree(content, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif isinstance(content, Path):
            shutil.copy2(content, dest)
        else:
            dest.write_text(content, encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", "-A")
    return root


def edit(root: Path, rel: str, old: str, new: str, count: int = 1) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) >= 1, f"{rel} has no {old!r}"
    path.write_text(text.replace(old, new, count), encoding="utf-8")
    git(root, "add", "-A")


def tracked_text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def line_of(rel: str, number: int) -> str:
    return tracked_text(rel).splitlines()[number - 1]


@pytest.fixture(scope="module")
def real():
    """Every fact on this repository, once."""
    return types.SimpleNamespace(facts={name: fn(REPO) for name, fn in rf.FACTS.items()})


# ================================================================ 1. the baseline job's Python versions

def test_python_versions_equal_the_matrix_line_of_the_workflow(real):
    text = tracked_text(".github/workflows/baseline.yml")
    listed = re.search(r"python-version:\s*\[([^\]]*)\]", text).group(1)
    assert real.facts["ci_python_versions"] == re.findall(r'"([^"]+)"', listed)
    assert len(real.facts["ci_python_versions"]) >= 1


def _workflow_repo(tmp_path, mutate=lambda t: t):
    text = mutate(tracked_text(".github/workflows/baseline.yml"))
    return make_repo(tmp_path, {".github/workflows/baseline.yml": text})


def test_python_versions_follow_the_matrix(tmp_path):
    root = _workflow_repo(tmp_path)
    assert rf.ci_python_versions(root) == rf.ci_python_versions(REPO)  # the same file, the same answer
    edit(root, ".github/workflows/baseline.yml", '["3.10", "3.11", "3.12"]', '["3.9", "3.13", "3.14"]')
    assert rf.ci_python_versions(root) == ["3.9", "3.13", "3.14"]  # order kept
    edit(root, ".github/workflows/baseline.yml", '["3.9", "3.13", "3.14"]', '["3.13"]')
    assert rf.ci_python_versions(root) == ["3.13"]


def test_python_versions_missing_workflow_names_the_file(tmp_path):
    root = make_repo(tmp_path, {"README.md": "x"})
    with pytest.raises(rf.FactError, match=r"baseline\.yml"):
        rf.ci_python_versions(root)


@pytest.mark.parametrize("old,new,message", [
    ('["3.10", "3.11", "3.12"]', "[3.10, 3.11]", "quoted"),                        # YAML reads 3.10 as 3.1
    ('python-version: ["3.10", "3.11", "3.12"]', 'python-version: "3.12"', "non-empty list"),
    ('python-version: ["3.10", "3.11", "3.12"]', 'os: [a]', "no strategy.matrix.python-version"),
    ("python-version: ${{ matrix.python-version }}", "python-version: 3.12", "setup-python"),
    ("name: baseline\n", "name: nothing\n", "no job"),
])
def test_python_versions_refuse_a_matrix_it_cannot_read(tmp_path, old, new, message):
    root = _workflow_repo(tmp_path, lambda t: t.replace(old, new, 1))
    with pytest.raises(rf.FactError, match=message):
        rf.ci_python_versions(root)


# ================================================================ 2. the replay suite's size

REPLAY_FILES = {"tests/replay/suite.py": REPO / "tests/replay/suite.py"} | {
    f"tests/replay/{p.name}": p for p in (REPO / "tests/replay").glob("test_*.py")}


def test_replay_suite_size_equals_the_imported_suite_and_the_text(real):
    from tests.replay import suite  # the suite's own definitions, imported (nothing is replayed)
    got = real.facts["replay_suite_size"]
    assert got["compliant_scenarios"] == len(suite.COMPLIANT)
    assert got["pipelines"] == len({p for s in suite.COMPLIANT for p in s.pipelines}) == len(suite.TEN)
    assert got["settings_modes"] == list(suite.SETTINGS)
    assert got["compliant_replays"] == len(suite.COMPLIANT) * len(suite.SETTINGS)
    # the fault classes by a plain pattern over the two test files that name them
    text = tracked_text("tests/replay/test_faults.py") + tracked_text("tests/replay/test_regressions.py")
    ids = sorted(set(re.findall(r"\bF[1-9][a-z]?\b", text)))
    assert got["fault_ids"] == len(ids)
    assert got["fault_classes"] == len({i[:2] for i in ids})
    assert {"F1", "F2", "F3", "F4", "F5", "F6", "F7"} <= {i[:2] for i in ids}  # the owner's list, and more
    # the regressions by the ids the whole file mentions
    assert got["regression_ids"] == sorted(set(re.findall(r"\bR-[A-Z]\d\b", tracked_text("tests/replay/test_regressions.py"))))
    assert got["regression_replays"] == len(got["regression_ids"])


def _replay_repo(tmp_path):
    return make_repo(tmp_path, dict(REPLAY_FILES))


def test_replay_suite_size_follows_its_inputs(tmp_path):
    root = _replay_repo(tmp_path)
    base = rf.replay_suite_size(root)
    # one compliant scenario fewer
    suite = (root / "tests/replay/suite.py").read_text(encoding="utf-8")
    line = next(l for l in suite.splitlines() if l.startswith('    Scenario("/dev qafail"'))
    edit(root, "tests/replay/suite.py", line + "\n", "")
    smaller = rf.replay_suite_size(root)
    assert smaller["compliant_scenarios"] == base["compliant_scenarios"] - 1
    assert smaller["compliant_replays"] == base["compliant_replays"] - len(base["settings_modes"])
    # a third settings mode is only a mode if test_pipelines runs the scenarios under suite.SETTINGS
    edit(root, "tests/replay/suite.py", 'SETTINGS = ("shipped", "armed")', 'SETTINGS = ("shipped", "armed", "extra")')
    assert rf.replay_suite_size(root)["settings_modes"] == ["shipped", "armed", "extra"]
    # a new fault class
    edit(root, "tests/replay/test_faults.py", '    "F9": "bash@', '    "F10": "missing@x",\n    "F9": "bash@')
    assert rf.replay_suite_size(root)["fault_classes"] == base["fault_classes"] + 1
    # a new variant of an existing class is no new class
    edit(root, "tests/replay/test_faults.py", '    "F9": "bash@', '    "F9z": "missing@x",\n    "F9": "bash@')
    after = rf.replay_suite_size(root)
    assert after["fault_classes"] == base["fault_classes"] + 1 and after["fault_ids"] == base["fault_ids"] + 2
    # a new regression named in the docstring needs a test, and counts once it has one
    edit(root, "tests/replay/test_regressions.py", "R-E1, E1 (F3a", "R-Z9, a made-up defect. R-E1, E1 (F3a")
    with pytest.raises(rf.FactError, match=r"R-Z9"):
        rf.replay_suite_size(root)
    edit(root, "tests/replay/test_regressions.py", "def _e1_key", "def test_r_z9_made_up():\n    pass\n\n\ndef _e1_key")
    assert rf.replay_suite_size(root)["regression_replays"] == base["regression_replays"] + 1


@pytest.mark.parametrize("rel,message", [
    ("tests/replay/suite.py", r"tests/replay/suite\.py"),
    ("tests/replay/test_pipelines.py", r"test_pipelines\.py"),
    ("tests/replay/test_regressions.py", r"test_regressions\.py"),
])
def test_replay_suite_size_missing_input_is_named(tmp_path, rel, message):
    files = dict(REPLAY_FILES)
    del files[rel]
    with pytest.raises(rf.FactError, match=message):
        rf.replay_suite_size(make_repo(tmp_path, files))


def test_replay_suite_size_refuses_cases_that_do_not_run_every_mode(tmp_path):
    root = _replay_repo(tmp_path)
    edit(root, "tests/replay/test_pipelines.py", "for scn in suite.COMPLIANT for s in suite.SETTINGS",
         "for scn in suite.COMPLIANT for s in suite.SETTINGS[:1]")
    with pytest.raises(rf.FactError, match="CASES"):
        rf.replay_suite_size(root)


def test_replay_suite_size_refuses_a_pipeline_no_scenario_types(tmp_path):
    root = _replay_repo(tmp_path)
    edit(root, "tests/replay/suite.py", 'TEN = ("spec",', 'TEN = ("nowhere", "spec",')
    with pytest.raises(rf.FactError, match="nowhere"):
        rf.replay_suite_size(root)
    # the only scenario that types /merge is gone: the pipeline is no longer replayed
    root = _replay_repo(tmp_path / "second")
    line = next(l for l in (root / "tests/replay/suite.py").read_text().splitlines() if l.startswith('    Scenario("/merge"'))
    edit(root, "tests/replay/suite.py", line + "\n", "")
    with pytest.raises(rf.FactError, match="merge"):
        rf.replay_suite_size(root)


# ================================================================ 3. blocking sites

def test_blocking_sites_equal_the_suites_own_catalog(real, tmp_path):
    """The numbers of tests/replay/test_no_dead_end.py's Catalog, which this fact repeats without pytest."""
    from tests.replay import test_no_dead_end as dead_end
    catalog = dead_end.Catalog(str(REPO), str(tmp_path / "relay"))
    got = real.facts["blocking_sites"]
    from collections import Counter
    counts = Counter(catalog.of(s) for s in catalog.sites)
    assert got["sites"] == len(catalog.sites) > 0
    assert got["by_class"] == {c: counts.get(c, 0) for c in "GDHU-"}
    assert sum(got["by_class"].values()) == got["sites"]
    assert got["no_class"] == got["by_class"]["-"] == counts.get("-", 0)
    assert sum(got["no_class_reasons"].values()) == got["no_class"]
    assert set(got) == {"sites", "by_class", "no_class", "no_class_reasons"}


HOOK = """import json, sys


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") == "Bash":
        print("BLOCKED: that command is not allowed here", file=sys.stderr)
        sys.exit(2)


main()
"""
SETTINGS_ONE_HOOK = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
    {"type": "command", "command": 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/h.py"'}]}]}}


def _sites_repo(tmp_path, settings=SETTINGS_ONE_HOOK, hook=HOOK):
    return make_repo(tmp_path, {
        "tests/replay/sites.py": REPO / "tests/replay/sites.py",
        "tests/replay/test_no_dead_end.py": REPO / "tests/replay/test_no_dead_end.py",
        "settings.json": json.dumps(settings, indent=1) + "\n",
        "hooks/h.py": hook,
    })


def test_blocking_sites_follow_the_hook_code(tmp_path):
    root = _sites_repo(tmp_path)
    one = rf.blocking_sites(root)
    assert one["sites"] == 1 and sum(one["by_class"].values()) == 1
    edit(root, "hooks/h.py", "        sys.exit(2)\n", "        sys.exit(2)\n"
         '    if data.get("tool_name") == "Edit":\n        print("BLOCKED: no edits here", file=sys.stderr)\n'
         "        sys.exit(2)\n")
    assert rf.blocking_sites(root)["sites"] == 2


def test_blocking_sites_read_the_registrations_from_the_index_not_the_working_file(tmp_path):
    root = _sites_repo(tmp_path)
    second = HOOK.replace('"Bash"', '"Write"')
    (root / "hooks/h2.py").write_text(second, encoding="utf-8")
    git(root, "add", "hooks/h2.py")
    wider = json.loads(json.dumps(SETTINGS_ONE_HOOK))
    wider["hooks"]["PreToolUse"][0]["hooks"].append(
        {"type": "command", "command": 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/h2.py"'})
    (root / "settings.json").write_text(json.dumps(wider), encoding="utf-8")  # machine-only, never staged
    assert rf.blocking_sites(root)["sites"] == 1
    git(root, "add", "settings.json")
    assert rf.blocking_sites(root)["sites"] == 2


def test_blocking_sites_leave_no_bytecode_in_the_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    root = _sites_repo(tmp_path)
    rf.blocking_sites(root)
    assert not list(root.rglob("__pycache__"))
    assert sys.dont_write_bytecode is False  # and the caller's setting is back


@pytest.mark.parametrize("leave_out,message", [
    ("tests/replay/sites.py", r"tests/replay/sites\.py"),
    ("settings.json", r"settings\.json"),
])
def test_blocking_sites_missing_input_is_named(tmp_path, leave_out, message):
    files = {"tests/replay/sites.py": REPO / "tests/replay/sites.py",
             "tests/replay/test_no_dead_end.py": REPO / "tests/replay/test_no_dead_end.py",
             "settings.json": json.dumps(SETTINGS_ONE_HOOK), "hooks/h.py": HOOK}
    del files[leave_out]
    with pytest.raises(rf.FactError, match=message):
        rf.blocking_sites(make_repo(tmp_path, files))


def test_blocking_sites_with_no_registered_hook_are_an_error_not_zero(tmp_path):
    root = _sites_repo(tmp_path, settings={"hooks": {"Stop": []}})
    with pytest.raises(rf.FactError, match="registers no hook file"):
        rf.blocking_sites(root)


# ================================================================ 4. what the static half derives

def independent_obligations() -> tuple[int, list[dict]]:
    """Obligation templates and their artifacts, read from commands/*.md by pattern: the JSON blocks, the
    prose form (`<obligation v="1">{...}</obligation>` then role=... artifacts=[...]) and, for a block
    whose placeholders break JSON, its "kind" keys."""
    def balanced(text, start):
        depth = 0
        for j in range(start, len(text)):
            depth += text[j] == "["
            depth -= text[j] == "]"
            if depth == 0:
                return text[start:j + 1]
    count, arts = 0, []
    for path in sorted((REPO / "commands").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'<obligation v="1">((?:(?!<obligation v="1">).)*?)</obligation>', text, re.S):
            body = m.group(1).strip()
            if body in ("{...}", "{…}", ""):
                tail = text[m.end():].split("\n", 1)[0]
                if 'role="' not in tail:
                    continue
                at = tail.find("artifacts=[")
                arts += json.loads(balanced(tail, at + len("artifacts="))) if at >= 0 else []
            else:
                try:
                    arts += json.loads(body).get("artifacts") or []
                except ValueError:  # placeholders break JSON: one artifact per "kind" key, with its "path" if it has one
                    for piece in re.split(r'(?="kind"\s*:)', body)[1:]:
                        arts.append({"kind": re.match(r'"kind"\s*:\s*"([^"]+)"', piece).group(1),
                                     **({"path": "x"} if '"path"' in piece else {})})
            count += 1
    return count, arts


def test_static_artifacts_equal_an_independent_reading_of_the_command_files(real):
    got = real.facts["static_artifacts"]
    templates, arts = independent_obligations()
    assert got["obligation_templates"] == templates > 0
    assert got["artifact_declarations"] == len(arts)
    raw_paths = {a["path"] for a in arts if a.get("path")}
    assert 0 < got["declared_file_artifacts"] <= len(raw_paths)  # patterns fold the spellings of one id
    assert "not the artifact total" in got["label"]


def test_static_artifacts_equal_the_static_halfs_own_derive():
    """One run of the static half's whole derive(): its obligation declarations are what the quick path
    reports, and its relations' path patterns are another, larger number."""
    from tests.artifact_graph import static_half
    result = static_half.derive(REPO)
    obligations = [r for r in result.records if r["kind"] == "declaration" and r["type"] == "obligation"]
    arts = [a for o in obligations for a in o["artifacts"]]
    quick = rf.static_artifacts(REPO)
    assert quick["obligation_templates"] == len(obligations)
    assert quick["artifact_declarations"] == len(arts)
    assert quick["declared_file_artifacts"] == len({a["path"] for a in arts if a.get("path")})
    # the static relations' path patterns are not the declared artifacts either
    relations = [r for r in result.records if r["kind"] == "relation"]
    assert len({r["path"] for r in relations}) != quick["declared_file_artifacts"]


def _artifact_repo(tmp_path):
    return make_repo(tmp_path, {"tests/artifact_graph": REPO / "tests/artifact_graph", "commands": REPO / "commands",
                                "agents": REPO / "agents"})


NEW_OBLIGATION = ('\n<obligation v="1">{"role": "qa", "pipeline": "x", "profile": "p", "artifacts": '
                  '[{"kind": "json", "path": "docs/dev/zzz-report-<timestamp>.json", "schema": "qa-report.v2"}]}'
                  "</obligation>\n")


def test_static_artifacts_follow_the_command_files(tmp_path):
    root = _artifact_repo(tmp_path)
    base = rf.static_artifacts(root)
    with open(root / "commands/merge.md", "a", encoding="utf-8") as fh:
        fh.write(NEW_OBLIGATION)
    git(root, "add", "-A")
    more = rf.static_artifacts(root)
    assert more["obligation_templates"] == base["obligation_templates"] + 1
    assert more["artifact_declarations"] == base["artifact_declarations"] + 1
    assert more["declared_file_artifacts"] == base["declared_file_artifacts"] + 1
    assert not list(root.rglob("__pycache__"))


def test_static_artifacts_missing_inputs_are_named(tmp_path):
    with pytest.raises(rf.FactError, match="artifact_graph"):
        rf.static_artifacts(make_repo(tmp_path, {"commands": REPO / "commands"}))
    root = make_repo(tmp_path, {"tests/artifact_graph": REPO / "tests/artifact_graph", "commands/x.md": "no block\n"},
                     "bare")
    with pytest.raises(rf.FactError, match="no obligation template"):
        rf.static_artifacts(root)


def test_static_artifacts_name_a_static_half_that_lost_a_function(tmp_path):
    root = _artifact_repo(tmp_path)
    edit(root, "tests/artifact_graph/static_half.py", "def _obligations(", "def _obligations_renamed(")
    with pytest.raises(rf.FactError, match="_obligations"):
        rf.static_artifacts(root)


# ================================================================ 5. test functions and test files

def recount(prefix: str) -> tuple[int, int]:
    files = [p for p in git(REPO, "ls-files", "-z", "--", prefix).split("\0")
             if p and (fnmatch.fnmatch(Path(p).name, "test_*.py") or fnmatch.fnmatch(Path(p).name, "*_test.py"))
             and not p.startswith("tests/generated/")]
    # a def at column 0 (module) or 4 (a class's method); no test in this repository nests deeper
    return len(files), sum(len(re.findall(r"(?m)^(?: {4})?(?:async )?def test_",
                                          (REPO / p).read_text(encoding="utf-8"))) for p in files)


def test_test_counts_equal_a_recount(real):
    got = real.facts["count_tests"]
    for key, prefix in (("hooks_tests", "hooks/tests"), ("tests", "tests")):
        files, functions = recount(prefix)
        assert got[key] == {"files": files, "test_functions": functions}
        assert files > 0 and functions > 0


def test_test_counts_follow_the_files(tmp_path):
    root = make_repo(tmp_path, {
        "hooks/tests/test_a.py": "def test_one():\n    pass\n\n\ndef helper():\n    pass\n",
        "hooks/tests/conftest.py": "def test_not_in_a_test_file():\n    pass\n",
        "tests/test_b.py": ("class Anything:\n    def test_m1(self):\n        pass\n\n    def test_m2(self):\n"
                            "        pass\n\n    def other(self):\n        pass\n\n\n"
                            "def outer():\n    def test_inner():\n        pass\n\n\nasync def test_async():\n    pass\n"),
        "tests/sub/test_c.py": "import pytest\n\n\n" "@pytest.mark.parametrize('x', [1, 2, 3])\ndef test_param(x):\n    pass\n",
        "tests/sub/d_test.py": "def test_d():\n    pass\n",
        "tests/generated/test_g.py": "def test_g():\n    pass\n",
    })
    assert rf.count_tests(root) == {"hooks_tests": {"files": 1, "test_functions": 1},
                                    "tests": {"files": 3, "test_functions": 5}}  # 2 methods + async + param + d
    edit(root, "hooks/tests/test_a.py", "def helper():", "def test_two():")
    assert rf.count_tests(root)["hooks_tests"]["test_functions"] == 2
    (root / "tests/test_untracked.py").write_text("def test_u():\n    pass\n", encoding="utf-8")
    assert rf.count_tests(root)["tests"]["files"] == 3  # not in the index: not a test
    git(root, "add", "-A")
    assert rf.count_tests(root)["tests"] == {"files": 4, "test_functions": 6}


def test_test_counts_missing_and_broken_inputs_are_named(tmp_path):
    with pytest.raises(rf.FactError, match=r"hooks/tests"):
        rf.count_tests(make_repo(tmp_path, {"tests/test_b.py": "def test_x():\n    pass\n"}, "no-hooks-tests"))
    with pytest.raises(rf.FactError, match=r"test_broken\.py"):
        rf.count_tests(make_repo(tmp_path, {"hooks/tests/test_a.py": "def test_x():\n    pass\n",
                                            "tests/test_broken.py": "def test_x(:\n"}, "broken"))


def test_a_directory_that_is_not_a_git_work_tree_is_refused(tmp_path):
    bare = tmp_path / "plain"
    (bare / "tests").mkdir(parents=True)
    (bare / "tests/test_x.py").write_text("def test_x():\n    pass\n")
    with pytest.raises(rf.FactError, match="git"):
        rf.count_tests(bare)


# ================================================================ 6. hook registrations

def tracked_settings() -> dict:
    return json.loads(git(REPO, "cat-file", "blob", ":settings.json"))


def test_hook_registrations_equal_a_recount_of_the_tracked_settings(real):
    settings = tracked_settings()
    per_event = {event: sum(len(g["hooks"]) for g in groups) for event, groups in settings["hooks"].items()}
    got = real.facts["hook_registrations"]
    assert got["by_event"] == dict(sorted(per_event.items()))
    assert got["entries"] == sum(per_event.values()) > 0
    assert got["events"] == len(per_event)
    assert set(got) == {"entries", "by_event", "events"}


def _hooks_repo(tmp_path):
    settings = {"hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/a.py"'},
            {"type": "command", "command": 'bash "${CLAUDE_HOME:-$HOME/.claude}/hooks/b.sh"'}]}],
        "Stop": [{"hooks": [{"type": "command", "command": 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/a.py"'}]}]}}
    return make_repo(tmp_path, {"scripts/check-enforcement-evidence.py": REPO / "scripts/check-enforcement-evidence.py",
                                "settings.json": json.dumps(settings, indent=1) + "\n",
                                "hooks/a.py": "", "hooks/b.sh": "", "hooks/c.py": ""})


def test_hook_registrations_follow_the_tracked_settings_not_the_working_file(tmp_path):
    root = _hooks_repo(tmp_path)
    assert rf.hook_registrations(root) == {"entries": 3, "by_event": {"PreToolUse": 2, "Stop": 1}, "events": 2}
    machine = json.loads((root / "settings.json").read_text())
    machine["hooks"]["SessionStart"] = [{"hooks": [{"type": "command", "command": "bash hooks/c.py"}]}]
    (root / "settings.json").write_text(json.dumps(machine), encoding="utf-8")  # a module's hook, not staged
    assert rf.hook_registrations(root)["entries"] == 3
    git(root, "add", "settings.json")
    after = rf.hook_registrations(root)
    assert after["entries"] == 4 and after["by_event"]["SessionStart"] == 1


def test_hook_registrations_missing_inputs_are_named(tmp_path):
    root = _hooks_repo(tmp_path)
    git(root, "rm", "-q", "--cached", "settings.json")
    with pytest.raises(rf.FactError, match=r"settings\.json"):
        rf.hook_registrations(root)


def test_hook_registrations_refuse_a_settings_without_hooks(tmp_path):
    root = _hooks_repo(tmp_path)
    (root / "settings.json").write_text('{"permissions": {}}', encoding="utf-8")
    git(root, "add", "settings.json")
    with pytest.raises(rf.FactError, match="hooks"):
        rf.hook_registrations(root)


# ================================================================ 7. enforcement strength

def ledger_rows() -> tuple[list[str], list[list[str]]]:
    """The registered-hook rows of the ledger by plain line parsing (rows start with an H- id)."""
    split = lambda line: [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
    lines = tracked_text("docs/ENFORCEMENT-LEDGER.md").splitlines()
    header = next(split(l) for l in lines if l.startswith("| row_id | event_class"))
    return header, [split(l) for l in lines if re.match(r"\| H-\d+ \|", l)]


def test_enforcement_strength_equals_a_recount_of_the_ledger(real):
    from collections import Counter
    header, rows = ledger_rows()
    got = real.facts["enforcement_strength"]
    assert got["rows"] == len(rows) == real.facts["hook_registrations"]["entries"]
    for key, column in (("by_behavior", "behavior"), ("by_proof_layer", "proof_layer")):
        seen = Counter(r[header.index(column)] for r in rows)
        assert {k: v for k, v in got[key].items() if v} == dict(seen)
        assert sum(got[key].values()) == len(rows)
    assert {"enforced", "detected", "advisory", "unsupported"} == set(got["by_behavior"])  # zeros are listed


def _ledger_repo(tmp_path):
    return make_repo(tmp_path, {"scripts/check-enforcement-evidence.py": REPO / "scripts/check-enforcement-evidence.py",
                                "docs/ENFORCEMENT-LEDGER.md": REPO / "docs/ENFORCEMENT-LEDGER.md",
                                "settings.json": git(REPO, "cat-file", "blob", ":settings.json")})


def test_enforcement_strength_follows_the_ledger(tmp_path):
    root = _ledger_repo(tmp_path)
    base = rf.enforcement_strength(root)
    first = next(l for l in (root / "docs/ENFORCEMENT-LEDGER.md").read_text().splitlines() if l.startswith("| H-001 |"))
    cells = first.split(" | ")
    assert "detected" in cells[5] or "advisory" in cells[5] or "enforced" in cells[5]
    was = next(c for c in cells if c in ("detected", "advisory"))
    to = "advisory" if was == "detected" else "detected"
    edit(root, "docs/ENFORCEMENT-LEDGER.md", first, first.replace(f" | {was} | ", f" | {to} | ", 1))
    moved = rf.enforcement_strength(root)
    assert moved["by_behavior"][was] == base["by_behavior"][was] - 1
    assert moved["by_behavior"][to] == base["by_behavior"][to] + 1
    assert moved["rows"] == base["rows"]
    # a label outside the gate's closed set is not counted under another name
    edit(root, "docs/ENFORCEMENT-LEDGER.md", f" | {to} | ", " | enforcedish | ", 1)
    with pytest.raises(rf.FactError, match="enforcedish"):
        rf.enforcement_strength(root)


def test_enforcement_strength_refuses_a_ledger_that_lags_the_settings(tmp_path):
    root = _ledger_repo(tmp_path)
    first = next(l for l in (root / "docs/ENFORCEMENT-LEDGER.md").read_text().splitlines() if l.startswith("| H-001 |"))
    edit(root, "docs/ENFORCEMENT-LEDGER.md", first + "\n", "")
    with pytest.raises(rf.FactError, match="differ from the tracked settings"):
        rf.enforcement_strength(root)


def test_enforcement_strength_missing_inputs_are_named(tmp_path):
    files = {"scripts/check-enforcement-evidence.py": REPO / "scripts/check-enforcement-evidence.py",
             "docs/ENFORCEMENT-LEDGER.md": REPO / "docs/ENFORCEMENT-LEDGER.md", "settings.json": "{}"}
    for gone, message in (("docs/ENFORCEMENT-LEDGER.md", "ENFORCEMENT-LEDGER"),
                          ("scripts/check-enforcement-evidence.py", "check-enforcement-evidence")):
        left = {k: v for k, v in files.items() if k != gone}
        with pytest.raises(rf.FactError, match=message):
            rf.enforcement_strength(make_repo(tmp_path / gone.replace("/", "_"), left))


# ================================================================ 8. the commands table and the cast of agents

def command_files() -> list[Path]:
    return sorted(p for p in (REPO / "commands").glob("*.md") if p.stem.upper() not in ("README", "INDEX"))


def agent_files() -> list[Path]:
    return sorted(p for p in (REPO / "agents").glob("*.md") if p.stem.upper() not in ("README", "INDEX"))


def front_value(path: Path, key: str):
    m = re.search(rf"(?m)^{re.escape(key)}:[ \t]*(.*)$", path.read_text(encoding="utf-8").split("\n---", 1)[0])
    return m.group(1).strip() if m else None


def unquoted(value: str) -> str:
    return json.loads(value) if value.startswith('"') else value


def test_command_rows_equal_a_recount(real):
    rows = real.facts["command_rows"]
    files = command_files()
    assert [r["name"] for r in rows] == sorted(p.stem for p in files)  # by name: dev, then dev-command
    files = sorted(files, key=lambda p: p.stem)
    for row, path in zip(rows, files):
        assert row["human_only"] == (front_value(path, "disable-model-invocation") == "true")
        hint = front_value(path, "argument-hint")
        assert row["argument_hint"] == (hint.strip('"') if hint else None), path.name
        assert row["summary"] == unquoted(front_value(path, "summary")), path.name  # verbatim, never cut
        assert 0 < len(row["summary"]) <= rf.SUMMARY_MAX and "\n" not in row["summary"]
        assert not rf.INTERNAL_NAME.search(row["summary"]), path.name
        assert row["group"] == front_value(path, "group") and row["group"] in rf.COMMAND_GROUPS
        assert row["module"] == front_value(path, "module")
    assert any(r["human_only"] for r in rows) and any(not r["human_only"] for r in rows)
    assert not [r for r in rows if r["name"].upper() in ("README", "INDEX")]
    assert {r["group"] for r in rows} == set(rf.COMMAND_GROUPS)  # every group holds a command
    assert [r["name"] for r in rows if r["module"]] == ["paseo-daemon"]


def test_the_rows_carry_exactly_their_fields(real):
    for row in real.facts["command_rows"]:
        assert set(row) == {"name", "argument_hint", "human_only", "summary", "group", "module"}
    for row in real.facts["agent_rows"]:
        assert set(row) == {"name", "summary"}


def test_agent_rows_equal_a_recount(real):
    rows = real.facts["agent_rows"]
    files = agent_files()
    assert [r["name"] for r in rows] == sorted(p.stem for p in files)
    for row, path in zip(rows, sorted(files, key=lambda p: p.stem)):
        assert front_value(path, "name") == row["name"]
        assert row["summary"] == unquoted(front_value(path, "summary")), path.name
        assert 0 < len(row["summary"]) <= rf.SUMMARY_MAX and not rf.INTERNAL_NAME.search(row["summary"])


def _commands_repo(tmp_path, **extra):
    files = {
        "commands/README.md": "---\ndescription: not a command\n---\n",
        "commands/INDEX.md": "---\ndescription: not a command\n---\n",
        "commands/beta.md": "---\ndescription: \"Beta Command\"\ndisable-model-invocation: true\nsummary: Do the beta thing.\n"
                            "group: Ship\nmodule: extra\n---\n\n# Beta Command\n\nDo the beta thing carefully. Then more.\n",
        "commands/alpha.md": "---\ndescription: Alpha does a thing for the owner. And more detail follows here.\n"
                             "argument-hint: \"[--x] <y>\"\ndisable-model-invocation: true\n"
                             "summary: \"Alpha does a thing for the owner, and this whole sentence is kept.\"\ngroup: Spec\n---\n\n# Alpha\n",
        "commands/gamma.md": "---\ndescription: Gamma may be called by an agent\nargument-hint: [a or b]\n"
                             "summary: Gamma may be called by an agent.\ngroup: Control\n---\n\ntext\n",
    }
    files.update(extra)
    return make_repo(tmp_path, files)


def test_command_rows_follow_the_command_files(tmp_path):
    root = _commands_repo(tmp_path)
    rows = rf.command_rows(root)
    assert rows == [
        {"name": "alpha", "argument_hint": "[--x] <y>", "human_only": True,
         "summary": "Alpha does a thing for the owner, and this whole sentence is kept.", "group": "Spec", "module": None},
        {"name": "beta", "argument_hint": None, "human_only": True,
         "summary": "Do the beta thing.", "group": "Ship", "module": "extra"},
        {"name": "gamma", "argument_hint": "[a or b]", "human_only": False,
         "summary": "Gamma may be called by an agent.", "group": "Control", "module": None},
    ]
    edit(root, "commands/gamma.md", "description: Gamma", "disable-model-invocation: true\ndescription: Gamma")
    assert [r["human_only"] for r in rf.command_rows(root)] == [True, True, True]
    edit(root, "commands/alpha.md", "Alpha does a thing for the owner, and this whole sentence is kept.", "Alpha is rewritten.")
    assert rf.command_rows(root)[0]["summary"] == "Alpha is rewritten."
    edit(root, "commands/alpha.md", "group: Spec", "group: Quality")
    assert rf.command_rows(root)[0]["group"] == "Quality"
    git(root, "mv", "commands/gamma.md", "commands/aaa.md")
    assert [r["name"] for r in rf.command_rows(root)] == ["aaa", "alpha", "beta"]


LONG = "x" * (rf.SUMMARY_MAX + 1)


@pytest.mark.parametrize("name,content,message", [
    ("nofront", "just text\n", r"nofront\.md: no YAML frontmatter"),
    ("badflag", "---\ndescription: d\ndisable-model-invocation: maybe\nsummary: s\ngroup: Ship\n---\nx\n", r"badflag\.md: .*maybe"),
    ("badyaml", "---\ndescription: [unclosed\n---\nx\n", r"badyaml\.md"),
    ("nosummary", "---\ndescription: d\ngroup: Ship\n---\nx\n", r"nosummary\.md: the frontmatter has no summary"),
    ("emptysummary", "---\ndescription: d\nsummary: \"  \"\ngroup: Ship\n---\nx\n", r"emptysummary\.md: .*no summary"),
    ("longsummary", f"---\ndescription: d\nsummary: {LONG}\ngroup: Ship\n---\nx\n",
     rf"longsummary\.md: the summary has {rf.SUMMARY_MAX + 1} characters, more than {rf.SUMMARY_MAX}; shorten it"),
    ("twolines", "---\ndescription: d\nsummary: \"one\\ntwo\"\ngroup: Ship\n---\nx\n", r"twolines\.md: the summary must be one line"),
    ("internal", "---\ndescription: d\nsummary: Drive the Paseo daemon.\ngroup: Ship\n---\nx\n",
     r"internal\.md: the summary names 'Paseo', an internal name"),
    ("modelid", "---\ndescription: d\nsummary: Ask gpt-5.6-sol.\ngroup: Ship\n---\nx\n", r"modelid\.md: the summary names 'gpt-5'"),
    ("nogroup", "---\ndescription: d\nsummary: s\n---\nx\n", r"nogroup\.md: the group is None, not one of Spec, Develop"),
    ("badgroup", "---\ndescription: d\nsummary: s\ngroup: Misc\n---\nx\n", r"badgroup\.md: the group is 'Misc'"),
    ("badmodule", "---\ndescription: d\nsummary: s\ngroup: Ship\nmodule: [a]\n---\nx\n", r"badmodule\.md: the module is"),
])
def test_command_rows_refuse_what_they_cannot_show_whole(tmp_path, name, content, message):
    root = _commands_repo(tmp_path, **{f"commands/{name}.md": content})
    with pytest.raises(rf.FactError, match=message):
        rf.command_rows(root)


def test_command_rows_without_a_commands_directory_is_an_error(tmp_path):
    with pytest.raises(rf.FactError, match=r"commands/\*\.md"):
        rf.command_rows(make_repo(tmp_path, {"README.md": "x"}))


def _agents_repo(tmp_path, **extra):
    files = {
        "agents/README.md": "---\nname: README\n---\n",
        "agents/INDEX.md": "x\n",
        "agents/zeta.md": "---\nname: zeta\ndescription: z\nsummary: \"Zeta checks things: carefully.\"\ntools: Read\n---\nbody\n",
        "agents/alpha.md": "---\nname: alpha\ndescription: >-\n  folded\n  text\nsummary: Alpha builds.\n---\nbody\n",
    }
    files.update(extra)
    return make_repo(tmp_path, files)


def test_agent_rows_follow_the_agent_files(tmp_path):
    root = _agents_repo(tmp_path)
    assert rf.agent_rows(root) == [{"name": "alpha", "summary": "Alpha builds."},
                                   {"name": "zeta", "summary": "Zeta checks things: carefully."}]
    edit(root, "agents/zeta.md", "Zeta checks things: carefully.", "Zeta is rewritten.")
    assert rf.agent_rows(root)[1]["summary"] == "Zeta is rewritten."


@pytest.mark.parametrize("name,content,message", [
    ("nosummary", "---\nname: nosummary\ndescription: d\n---\n", r"nosummary\.md: the frontmatter has no summary"),
    ("wrongname", "---\nname: other\nsummary: s\n---\n", r"wrongname\.md: the frontmatter name is 'other', not 'wrongname'"),
    ("long", f"---\nname: long\nsummary: {LONG}\n---\n", r"long\.md: the summary has"),
    ("internal", "---\nname: internal\nsummary: Tracks Unfuddle tickets.\n---\n", r"internal\.md: the summary names 'Unfuddle'"),
    ("nofront", "no frontmatter\n", r"nofront\.md: no YAML frontmatter"),
])
def test_agent_rows_refuse_what_they_cannot_show_whole(tmp_path, name, content, message):
    root = _agents_repo(tmp_path, **{f"agents/{name}.md": content})
    with pytest.raises(rf.FactError, match=message):
        rf.agent_rows(root)


def test_agent_rows_without_an_agents_directory_is_an_error(tmp_path):
    with pytest.raises(rf.FactError, match=r"agents/\*\.md"):
        rf.agent_rows(make_repo(tmp_path, {"README.md": "x"}))


@pytest.mark.parametrize("text,found", [
    ("drive the paseo daemon", "paseo"), ("an Unfuddle-style table", "Unfuddle"), ("ask gpt-5.6-sol", "gpt-5"),
    ("run claude-opus-5-5", "claude-opus"), ("use codex-mini", "codex-mini"), ("try o4-mini", "o4-mini"),
    ("OpenAI Codex reviews it", None), ("claude-codex-settings", None), ("/codex --review", None), ("Claude Code", None),
])
def test_the_internal_names(text, found):
    m = rf.INTERNAL_NAME.search(text)
    assert (m.group(0) if m else None) == found


# ================================================================ 9. what CI enforces

CI_FILES = {rel: REPO / rel for rel in ("tests/replay/test_pipelines.py", "tests/replay/test_no_dead_end.py",
                                        "tests/test_artifact_graph.py", "tests/artifact_graph/check.py",
                                        "tests/replay/test_faults.py", ".github/workflows/baseline.yml")}
WORKFLOW = ".github/workflows/baseline.yml"


def fault_table() -> list[str]:
    table = re.search(r"(?s)\nFAULTS = \{(.*?)\n\}", tracked_text("tests/replay/test_faults.py")).group(1)
    return re.findall(r'(?m)^    "(F\d+[a-z]*)":', table)


def test_ci_enforces_on_this_repository(real):
    got = real.facts["ci_enforces"]
    assert set(got) == {"compliant_replays_clean", "no_site_without_class", "artifact_check_clean",
                        "faults_returned_and_repaired", "unit_suite_on_every_version"}
    for name, verdict in got.items():
        assert set(verdict) >= {"holds", "claim", "file", "missing"}, name
        assert verdict["holds"] == (not verdict["missing"]), name  # false always says what was missing
    assert got["compliant_replays_clean"]["holds"] and got["compliant_replays_clean"]["file"] == "tests/replay/test_pipelines.py"
    assert got["artifact_check_clean"]["holds"] and got["artifact_check_clean"]["file"] == "tests/test_artifact_graph.py"
    # the owner's claim (b) is stronger than anything the suite asserts: false, with the weaker one shown
    b = got["no_site_without_class"]
    assert b["holds"] is False and b["missing"] and b["weaker"]["holds"] is True
    # every fault of the table goes through the repair check, in its order, but the one the test treats apart
    f = got["faults_returned_and_repaired"]
    assert f["holds"] and f["file"] == "tests/replay/test_faults.py"
    assert f["ids"] == [i for i in fault_table() if i != "F3b"] and "F3b" in fault_table()
    # the unit suite: the baseline job's pytest step, in every leg of the matrix
    u = got["unit_suite_on_every_version"]
    assert u["holds"] and u["file"] == WORKFLOW and u["versions"] == real.facts["ci_python_versions"]
    step = tracked_text(u["file"]).split("- name: Run tests", 1)[1].split("- name:", 1)[0]  # the baseline job's pytest step
    assert u["ignored"] == sorted(re.findall(r"--ignore=(\S+)", step))


def _ci_repo(tmp_path):
    return make_repo(tmp_path, dict(CI_FILES))


def test_ci_enforces_compliant_replays_follow_the_assertions(tmp_path):
    root = _ci_repo(tmp_path)
    rel = "tests/replay/test_pipelines.py"
    assert rf.ci_enforces(root)["compliant_replays_clean"]["holds"]
    for gone, what in (("    assert not r.blocks, ", "no gate block"), ("    assert not r.hook_errors, ", "no hook error"),
                       ("    assert r.reached(), ", "reaches its terminal")):
        broken = _ci_repo(tmp_path / what.replace(" ", "_"))
        text = (broken / rel).read_text()
        line = next(l for l in text.splitlines() if l.startswith(gone))
        edit(broken, rel, line, "    pass  # " + line.strip()[:20])
        verdict = rf.ci_enforces(broken)["compliant_replays_clean"]
        assert verdict["holds"] is False and what in " ".join(verdict["missing"]), verdict
    skipped = _ci_repo(tmp_path / "skipped")
    param = '@pytest.mark.parametrize("key", CASES)'
    edit(skipped, rel, param, "@pytest.mark.skip" + chr(10) + param)
    assert "skip" in " ".join(rf.ci_enforces(skipped)["compliant_replays_clean"]["missing"])
    narrowed = _ci_repo(tmp_path / "narrowed")
    edit(narrowed, rel, "for s in suite.SETTINGS]", "for s in suite.SETTINGS[:1]]")
    assert rf.ci_enforces(narrowed)["compliant_replays_clean"]["holds"] is False


def test_ci_enforces_no_site_without_class_needs_an_assertion(tmp_path):
    root = _ci_repo(tmp_path)
    rel = "tests/replay/test_no_dead_end.py"
    assert rf.ci_enforces(root)["no_site_without_class"]["holds"] is False
    edit(root, rel, "    assert catalog.sites, \"the enumerator found no blocking site\"\n",
         "    assert catalog.sites, \"the enumerator found no blocking site\"\n"
         "    no_class = [s.id for s in catalog.sites if catalog.of(s) == \"-\"]\n    assert not no_class\n")
    verdict = rf.ci_enforces(root)["no_site_without_class"]
    assert verdict["holds"] is True and verdict["missing"] == []
    # the weaker assertion alone, without its check, is not found either
    cut = _ci_repo(tmp_path / "cut")
    edit(cut, rel, "        if \"-\" in classes:", "        if \"-\" in nothing:")
    assert rf.ci_enforces(cut)["no_site_without_class"]["weaker"]["holds"] is False


def test_ci_enforces_artifact_check_follows_the_assertion_and_the_exception_names(tmp_path):
    rel = "tests/test_artifact_graph.py"
    assert rf.ci_enforces(_ci_repo(tmp_path))["artifact_check_clean"]["holds"]
    loosened = _ci_repo(tmp_path / "loose")
    edit(loosened, rel, "assert not vs", "assert len(vs) < 3")
    assert "asserts no" in " ".join(rf.ci_enforces(loosened)["artifact_check_clean"]["missing"])
    filtered = _ci_repo(tmp_path / "filtered")
    edit(filtered, rel, 'vs = check["violations"]', 'vs = [v for v in check["violations"] if v.rule != "2-unread"]')
    assert "taken whole" in " ".join(rf.ci_enforces(filtered)["artifact_check_clean"]["missing"])
    listed = _ci_repo(tmp_path / "listed")
    with open(listed / rel, "a", encoding="utf-8") as fh:
        fh.write("\nKNOWN_VIOLATIONS = []\n")
    git(listed, "add", "-A")
    verdict = rf.ci_enforces(listed)["artifact_check_clean"]
    assert verdict["holds"] is False and "KNOWN_VIOLATIONS" in " ".join(verdict["missing"])
    in_check = _ci_repo(tmp_path / "in-check")
    with open(in_check / "tests/artifact_graph/check.py", "a", encoding="utf-8") as fh:
        fh.write("\nWAIVERS = {}\n")
    git(in_check, "add", "-A")
    assert "WAIVERS" in " ".join(rf.ci_enforces(in_check)["artifact_check_clean"]["missing"])


def test_ci_enforces_faults_follow_the_assertions(tmp_path):
    rel = "tests/replay/test_faults.py"
    base = rf.ci_enforces(_ci_repo(tmp_path))["faults_returned_and_repaired"]
    assert base["holds"] and "F3b" not in base["ids"] and set(base["ids"]) | {"F3b"} == set(fault_table())
    for gone, what in (("    assert r.blocks, ", "a gate returned the fault"),
                       ("    assert agent in expected, ", "producer"),
                       ("    assert mine and mine[0][\"blocked\"], ", "first stop is returned"),
                       ("    assert not others, ", "another actor"),
                       ("    assert not mine[-1][\"blocked\"] and mine[-1][\"active\"], ", "next stop passes"),
                       ("    assert repaired, ", "writes the repair"),
                       ("    assert f[\"repaired\"], ", "faulted agent repaired"),
                       ("    assert not human_events(r, injected), ", "no human event"),
                       ("    assert not r.hook_errors, ", "no hook error"),
                       ("    assert r.reached(), ", "reaches its terminal")):
        broken = _ci_repo(tmp_path / what.replace(" ", "_"))
        line = next(l for l in (broken / rel).read_text().splitlines() if l.startswith(gone))
        edit(broken, rel, line, "    pass  # " + line.strip()[:20])
        verdict = rf.ci_enforces(broken)["faults_returned_and_repaired"]
        assert verdict["holds"] is False and what in " ".join(verdict["missing"]), (what, verdict)
    narrowed = _ci_repo(tmp_path / "narrowed")
    edit(narrowed, rel, "for fault in FAULTS for s in suite.SETTINGS]", "for fault in FAULTS for s in suite.SETTINGS[:1]]")
    assert "CASES is not FAULTS x suite.SETTINGS" in " ".join(rf.ci_enforces(narrowed)["faults_returned_and_repaired"]["missing"])
    skipped = _ci_repo(tmp_path / "skipped")
    edit(skipped, rel, "@pytest.mark.parametrize(\"fault,settings\", CASES)",
         "@pytest.mark.skip" + chr(10) + "@pytest.mark.parametrize(\"fault,settings\", CASES)")
    assert "skip" in " ".join(rf.ci_enforces(skipped)["faults_returned_and_repaired"]["missing"])
    unreadable = _ci_repo(tmp_path / "unreadable")
    edit(unreadable, rel, "    if fault == \"F3b\":", "    if fault in (\"F3b\", \"F9\"):")
    verdict = rf.ci_enforces(unreadable)["faults_returned_and_repaired"]
    assert verdict["holds"] is False and "cannot tell for which faults" in " ".join(verdict["missing"])
    # a fault added to the table goes through the helper like the others
    grown = _ci_repo(tmp_path / "grown")
    edit(grown, rel, '    "F9": "bash@', '    "F10": "missing@x",\n    "F9": "bash@')
    after = rf.ci_enforces(grown)["faults_returned_and_repaired"]
    assert after["holds"] and "F10" in after["ids"] and len(after["ids"]) == len(base["ids"]) + 1
    empty = _ci_repo(tmp_path / "empty")
    edit(empty, rel, "FAULTS = {", "FAULTS = {}\nOTHER = {")
    assert rf.ci_enforces(empty)["faults_returned_and_repaired"]["holds"] is False


def test_ci_enforces_unit_suite_follows_the_workflow(tmp_path):
    base = rf.ci_enforces(_ci_repo(tmp_path))["unit_suite_on_every_version"]
    assert base["holds"] and base["versions"] == ["3.10", "3.11", "3.12"] and "tests/replay" in base["ignored"]
    grown = _ci_repo(tmp_path / "grown")
    edit(grown, WORKFLOW, "--ignore=tests/replay", "--ignore=tests/replay --ignore=tests/extra")
    edit(grown, WORKFLOW, '["3.10", "3.11", "3.12"]', '["3.11", "3.13"]')
    after = rf.ci_enforces(grown)["unit_suite_on_every_version"]
    assert after["versions"] == ["3.11", "3.13"] and "tests/extra" in after["ignored"]
    for what, old, new, message in (
            ("swallowed", "-n auto --dist loadfile", "-n auto --dist loadfile || true", "not one plain pytest command"),
            ("continued", "      - name: Run tests\n", "      - name: Run tests\n        continue-on-error: true\n",
             "can fail without failing the job"),
            ("conditional", "      - name: Run tests\n", "      - name: Run tests\n        if: always()\n",
             "can fail without failing the job"),
            ("job continued", "    strategy:\n", "    continue-on-error: true\n    strategy:\n", "continue-on-error"),
            ("not the unit suite", "pytest hooks/tests tests", "pytest tests", "runs pytest over hooks/tests and tests")):
        broken = _ci_repo(tmp_path / what.replace(" ", "_"))
        edit(broken, WORKFLOW, old, new)
        verdict = rf.ci_enforces(broken)["unit_suite_on_every_version"]
        assert verdict["holds"] is False and message in " ".join(verdict["missing"]), (what, verdict)


@pytest.mark.parametrize("gone,predicate", [
    ("tests/replay/test_pipelines.py", "compliant_replays_clean"),
    ("tests/replay/test_no_dead_end.py", "no_site_without_class"),
    ("tests/test_artifact_graph.py", "artifact_check_clean"),
    ("tests/artifact_graph/check.py", "artifact_check_clean"),
    ("tests/replay/test_faults.py", "faults_returned_and_repaired"),
    (".github/workflows/baseline.yml", "unit_suite_on_every_version"),
])
def test_ci_enforces_fails_closed_on_a_missing_source(tmp_path, gone, predicate):
    files = dict(CI_FILES)
    del files[gone]
    got = rf.ci_enforces(make_repo(tmp_path, files))
    assert got[predicate]["holds"] is False
    assert Path(gone).name in " ".join(got[predicate]["missing"])
    if gone == WORKFLOW:  # no workflow shows CI running any of them: every predicate is false and says so
        for name, verdict in got.items():
            assert verdict["holds"] is False and "baseline.yml" in " ".join(verdict["missing"]), name
        assert got["no_site_without_class"]["weaker"]["holds"] is False
        return
    assert [n for n, v in got.items() if n != predicate and gone not in v["missing"] and not v["holds"]] in (
        [], ["no_site_without_class"])  # the other predicates still answer from their own sources


def test_ci_enforces_fails_closed_on_a_source_that_does_not_parse(tmp_path):
    root = _ci_repo(tmp_path)
    (root / "tests/replay/test_pipelines.py").write_text("def broken(:\n", encoding="utf-8")
    verdict = rf.ci_enforces(root)["compliant_replays_clean"]
    assert verdict["holds"] is False and "test_pipelines.py" in " ".join(verdict["missing"])


# ================================================================ 9a. the workflow really runs the test

REPLAY_THREE = {"compliant_replays_clean", "no_site_without_class", "faults_returned_and_repaired"}
BASE_HOLDS = {"compliant_replays_clean": True, "no_site_without_class": False, "artifact_check_clean": True,
              "faults_returned_and_repaired": True}  # on this repository's sources (the dead-end claim is not asserted)
FOUR = REPLAY_THREE | {"artifact_check_clean"}
# the D30 visibility gate every job carries (tests/test_ci_visibility_gate.py), ANDed with the draft skip
GATE = "(github.event_name == 'workflow_dispatch' || toJSON(github.event.repository.private) == 'false')"
DRAFT_SKIP = "(github.event_name != 'pull_request' || !github.event.pull_request.draft)"
GATED_DRAFT_SKIP = f"{GATE} && {DRAFT_SKIP}"
GATED_IF = f"if: ${{{{ {GATED_DRAFT_SKIP} }}}}"
ARTIFACT_IF = f"if: ${{{{ !cancelled() && needs.artifact-graph-plan.result == 'success' && {GATE} }}}}"


def must_replace(text: str, old: str, new: str) -> str:
    assert text.count(old) >= 1, f"the workflow has no {old!r}"
    return text.replace(old, new, 1)


def replace_last(text: str, old: str, new: str) -> str:
    assert old in text, old
    head, _, tail = text.rpartition(old)
    return head + new + tail


def drop_job(text: str, job: str) -> str:
    """The workflow without the job `job` (the text from its key to the next job's key)."""
    start = text.index(f"\n  {job}:\n")
    nxt = re.search(r"\n  [\w-]+:\n", text[start + 1:])
    return text[:start] + (text[start + 1 + nxt.start():] if nxt else "\n")


def run_workflow_variant(tmp_path, name, mutate):
    root = _ci_repo(tmp_path / name)
    text = (root / WORKFLOW).read_text(encoding="utf-8")
    changed = mutate(text)
    assert changed != text, name
    (root / WORKFLOW).write_text(changed, encoding="utf-8")
    git(root, "add", "-A")
    return rf.ci_enforces(root)


def not_run(verdict: dict) -> list[str]:
    return [m for m in verdict["missing"] if m.startswith("CI does not run it: ")]


def assert_ci_verdicts(got: dict, false_for, message: str):
    """The predicates in `false_for` (a set, or {predicate: reason}) are false because CI does not run their test,
    with the workflow's reason (for the dead-end predicate, its weaker claim too); every other predicate still
    finds the workflow running its test."""
    reasons = false_for if isinstance(false_for, dict) else {name: message for name in false_for}
    for name, verdict in got.items():
        if name == "unit_suite_on_every_version":
            continue
        if name in reasons:
            assert verdict["holds"] is False and any(reasons[name] in m for m in not_run(verdict)), (name, verdict["missing"])
            if name == "no_site_without_class":
                assert verdict["weaker"]["holds"] is False and not_run(verdict["weaker"])
        else:
            assert not not_run(verdict) and verdict["holds"] is BASE_HOLDS[name], (name, verdict["missing"])


def test_the_workflow_runs_each_test_on_this_repository(real):
    """The real workflow passes every rule: each of the four tests is run by a step of a job that cannot be
    skipped or ignored, and the baseline job's own pytest step, which leaves them out, is not that step."""
    expect = {"tests/replay/test_pipelines.py": "replay-suite", "tests/replay/test_no_dead_end.py": "replay-suite",
              "tests/replay/test_faults.py": "replay-suite", "tests/test_artifact_graph.py": "artifact-graph"}
    for target, job in expect.items():
        wf = rf._ci_runs(REPO, (target,))
        assert wf["holds"] is True and wf["missing"] == [] and wf["job"] == job, (target, wf)
        alone = rf._ci_runs(REPO, (target,), only_job="baseline")
        assert alone["holds"] is False and "ignores it" in " ".join(alone["missing"]), (target, alone)
    got = real.facts["ci_enforces"]
    assert {n: v["holds"] for n, v in got.items() if n in BASE_HOLDS} == BASE_HOLDS
    assert got["no_site_without_class"]["weaker"]["holds"] is True and not not_run(got["no_site_without_class"])
    unit = rf._ci_runs(REPO, ("hooks/tests", "tests"), only_job="baseline")
    assert unit["holds"] and unit["job"] == "baseline"
    # an independent reading of the job names: the replay shards and the artifact check
    text = tracked_text(WORKFLOW)
    assert re.search(r"(?m)^  replay-suite:\n", text) and re.search(r"(?m)^  artifact-graph:\n", text)


NOT_PLAIN = "not one plain pytest command"
# (name, mutation of the workflow text, the predicates that turn false, the reason it names). The recognizer
# reads only one plain pytest command of known options, so an unknown option or any shell syntax fails the
# step whatever it would have done; the last two were harmless to the interpreter it replaced.
MUTATIONS = [
    # with the job gone, the only step that still reaches the test is the baseline job's, which leaves it out
    ("replay job removed", lambda t: drop_job(t, "replay-suite"), REPLAY_THREE, "no step runs pytest over"),
    ("artifact job removed", lambda t: drop_job(t, "artifact-graph"), {"artifact_check_clean"}, "ignores it"),
    ("replay dir ignored", lambda t: must_replace(t, "--ignore=tests/replay/test_run_to_run.py",
                                                  "--ignore=tests/replay/test_run_to_run.py --ignore=tests/replay"),
     REPLAY_THREE, "ignores it"),
    ("replay dir ignored, spaced", lambda t: must_replace(t, "--ignore=tests/replay/test_run_to_run.py",
                                                          "--ignore tests/replay"), REPLAY_THREE, "ignores it"),
    ("one file ignored", lambda t: must_replace(t, "--ignore=tests/replay/test_run_to_run.py",
                                                "--ignore=tests/replay/test_run_to_run.py --ignore=tests/replay/test_faults.py"),
     {"faults_returned_and_repaired"}, "ignores it"),
    ("one file ignored by a glob", lambda t: must_replace(t, "--ignore=tests/replay/test_run_to_run.py",
                                                          "--ignore-glob=*test_pipelines.py"),
     REPLAY_THREE, "`--ignore-glob=*test_pipelines.py`"),
    ("artifact test ignored", lambda t: must_replace(t, "pytest tests/test_artifact_graph.py -q",
                                                     "pytest tests/test_artifact_graph.py --ignore=tests/test_artifact_graph.py -q"),
     {"artifact_check_clean"}, "ignores it"),
    ("artifact step runs another file", lambda t: must_replace(t, "pytest tests/test_artifact_graph.py -q",
                                                               "pytest tests/artifact_graph/test_mutations.py -q"),
     {"artifact_check_clean"}, "ignores it"),  # the baseline step that reaches it leaves it out
    ("replay step continue-on-error", lambda t: must_replace(
        t, "      - name: Replay suite, shard ${{ matrix.shard }} of 6\n",
        "      - name: Replay suite, shard ${{ matrix.shard }} of 6\n        continue-on-error: true\n"),
     REPLAY_THREE, "continue-on-error"),
    ("artifact step continue-on-error", lambda t: must_replace(
        t, "      - name: Artifact check\n", "      - name: Artifact check\n        continue-on-error: true\n"),
     {"artifact_check_clean"}, "continue-on-error"),
    ("replay job continue-on-error", lambda t: must_replace(
        t, "    name: replay suite ${{ matrix.shard }}/6\n", "    name: replay suite ${{ matrix.shard }}/6\n    continue-on-error: true\n"),
     REPLAY_THREE, "job `replay-suite` has continue-on-error"),
    ("replay job continue-on-error by expression", lambda t: must_replace(
        t, "    name: replay suite ${{ matrix.shard }}/6\n",
        "    name: replay suite ${{ matrix.shard }}/6\n    continue-on-error: ${{ matrix.shard == 6 }}\n"),
     REPLAY_THREE, "continue-on-error"),
    ("artifact job continue-on-error", lambda t: must_replace(
        t, "    name: artifact check (traced replays)\n",
        "    name: artifact check (traced replays)\n    continue-on-error: true\n"),
     {"artifact_check_clean"}, "job `artifact-graph` has continue-on-error"),
    ("job it needs continue-on-error", lambda t: must_replace(
        t, "    name: artifact check plan\n", "    name: artifact check plan\n    continue-on-error: true\n"),
     {"artifact_check_clean"}, "needed job: job `artifact-graph-plan` has continue-on-error"),
    ("replay step conditional", lambda t: must_replace(
        t, "      - name: Replay suite, shard ${{ matrix.shard }} of 6\n",
        "      - name: Replay suite, shard ${{ matrix.shard }} of 6\n        if: github.event_name == 'push'\n"),
     REPLAY_THREE, "the step has an `if`"),
    ("replay job conditional", lambda t: replace_last(
        t, GATED_IF, f"if: ${{{{ {GATE} && (github.event_name == 'push') }}}}"), REPLAY_THREE, "is conditional"),
    ("artifact job conditional", lambda t: must_replace(
        t, ARTIFACT_IF, f"if: ${{{{ github.ref == 'refs/heads/master' && {GATE} }}}}"), {"artifact_check_clean"},
     "is conditional"),
    ("artifact job gated on a job it does not need", lambda t: must_replace(
        t, "needs.artifact-graph-plan.result == 'success'", "needs.baseline.result == 'success'"),
     {"artifact_check_clean"}, "is conditional"),
    ("replay selection -k", lambda t: must_replace(t, "-rfE --durations=0", "-rfE --durations=0 -k smoke"),
     REPLAY_THREE, "`-k`"),
    ("replay selection -k attached", lambda t: must_replace(t, "-rfE --durations=0", "-rfE --durations=0 -ksmoke"),
     REPLAY_THREE, "`-ksmoke`"),
    ("replay selection -m", lambda t: must_replace(t, "-rfE --durations=0", "-rfE --durations=0 -m 'not slow'"),
     REPLAY_THREE, NOT_PLAIN),
    ("replay last-failed", lambda t: must_replace(t, "-rfE --durations=0", "-rfE --durations=0 --lf"),
     REPLAY_THREE, "`--lf`"),
    ("artifact selection", lambda t: must_replace(t, "pytest tests/test_artifact_graph.py -q",
                                                  "pytest tests/test_artifact_graph.py -k test_no_violation -q"),
     {"artifact_check_clean"}, "`-k`"),
    ("replay deselect file", lambda t: must_replace(t, "-rfE --durations=0", "-rfE --durations=0 --deselect=tests/replay/test_pipelines.py"),
     REPLAY_THREE, "`--deselect=tests/replay/test_pipelines.py`"),
    ("replay deselect test", lambda t: must_replace(
        t, "-rfE --durations=0", "-rfE --durations=0 --deselect tests/replay/test_faults.py::test_fault_returns_to_its_producer"),
     REPLAY_THREE, "`--deselect`"),
    ("replay collect only", lambda t: must_replace(t, "-rfE --durations=0", "-rfE --durations=0 --collect-only"),
     REPLAY_THREE, "`--collect-only`"),
    ("replay collect only, short", lambda t: must_replace(t, "-rfE --durations=0", "-rfE --durations=0 --co"),
     REPLAY_THREE, "`--co`"),
    ("artifact setup plan", lambda t: must_replace(t, "pytest tests/test_artifact_graph.py -q",
                                                   "pytest tests/test_artifact_graph.py --setup-plan -q"),
     {"artifact_check_clean"}, "`--setup-plan`"),
    ("replay config override", lambda t: must_replace(t, "-rfE --durations=0", "-rfE --durations=0 -o addopts=-q"),
     REPLAY_THREE, "`-o`"),
    # a node id is no plain path: the step reaches none of the three, and the baseline step leaves them out
    ("replay node id", lambda t: must_replace(t, "pytest tests/replay -q", "pytest tests/replay/test_faults.py::test_x -q"),
     REPLAY_THREE, "ignores it"),
    ("replay exit code swallowed", lambda t: must_replace(t, "--ignore=tests/replay/test_run_to_run.py",
                                                          "--ignore=tests/replay/test_run_to_run.py || true"),
     REPLAY_THREE, NOT_PLAIN),
    ("replay exit code swallowed by echo", lambda t: must_replace(t, "--ignore=tests/replay/test_run_to_run.py",
                                                                  "--ignore=tests/replay/test_run_to_run.py || echo failed"),
     REPLAY_THREE, NOT_PLAIN),
    ("replay piped", lambda t: must_replace(t, "--ignore=tests/replay/test_run_to_run.py",
                                            "--ignore=tests/replay/test_run_to_run.py | tee replay.log"),
     REPLAY_THREE, NOT_PLAIN),
    ("replay in the background", lambda t: must_replace(t, "--ignore=tests/replay/test_run_to_run.py",
                                                        "--ignore=tests/replay/test_run_to_run.py &"),
     REPLAY_THREE, NOT_PLAIN),
    ("artifact exit code swallowed", lambda t: must_replace(t, "pytest tests/test_artifact_graph.py -q -p no:cacheprovider -s",
                                                            "pytest tests/test_artifact_graph.py -q -p no:cacheprovider -s || true"),
     {"artifact_check_clean"}, NOT_PLAIN),
    ("replay shards cut", lambda t: must_replace(t, "shard: [1, 2, 3, 4, 5, 6]", "shard: [1, 2, 3]"),
     REPLAY_THREE, "splits the tests over 6 shards"),
    ("replay shard count raised", lambda t: must_replace(t, "REPLAY_SHARD: ${{ matrix.shard }}/6", "REPLAY_SHARD: ${{ matrix.shard }}/8"),
     REPLAY_THREE, "splits the tests over 8 shards"),
    ("selection in the environment", lambda t: must_replace(t, "          REPLAY_WORK: ${{ runner.temp }}/replay\n",
                                                            "          REPLAY_WORK: ${{ runner.temp }}/replay\n          PYTEST_ADDOPTS: \"-k smoke\"\n"),
     REPLAY_THREE, "PYTEST_ADDOPTS"),
    ("another directory", lambda t: must_replace(
        t, "      - name: Replay suite, shard ${{ matrix.shard }} of 6\n",
        "      - name: Replay suite, shard ${{ matrix.shard }} of 6\n        working-directory: tests\n"),
     REPLAY_THREE, "working-directory"),
    ("another shell", lambda t: must_replace(
        t, "      - name: Artifact check\n", "      - name: Artifact check\n        shell: sh {0}\n"),
     {"artifact_check_clean"}, "shell"),
    ("an exit code kept", lambda t: must_replace(t, "--ignore=tests/replay/test_run_to_run.py",
                                                 "--ignore=tests/replay/test_run_to_run.py || exit 1"), REPLAY_THREE, NOT_PLAIN),
    ("a pipe with pipefail", lambda t: must_replace(
        t, "      - name: Artifact check\n", "      - name: Artifact check\n        shell: bash\n").replace(
        "pytest tests/test_artifact_graph.py -q -p no:cacheprovider -s", "pytest tests/test_artifact_graph.py -q -p no:cacheprovider -s | tee check.log"),
     {"artifact_check_clean"}, NOT_PLAIN),
]


@pytest.mark.parametrize("name,mutate,false_for,message", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_the_workflow_rules_turn_the_predicates_false(tmp_path, name, mutate, false_for, message):
    got = run_workflow_variant(tmp_path, "mutated", mutate)
    assert_ci_verdicts(got, false_for, message)
    assert got["unit_suite_on_every_version"]["holds"] is True  # none of these touches the baseline job's pytest step


# changes that do not narrow the run, narrow nothing: the predicates stay as they are
HARMLESS = [
    ("more output", lambda t: must_replace(t, "-rfE --durations=0", "-rfE --durations=0 -vv --tb=short -x")),
    ("another ignored file", lambda t: must_replace(t, "--ignore=tests/replay/test_run_to_run.py",
                                                    "--ignore=tests/replay/test_run_to_run.py --ignore=tests/replay/test_trace_reduce.py")),
    ("an explicit bash", lambda t: must_replace(t, "      - name: Artifact check\n", "      - name: Artifact check\n        shell: bash\n")),
    ("a job with no if", lambda t: must_replace(t, f"    {ARTIFACT_IF}\n", "")),
    ("an always() job", lambda t: must_replace(
        t, "!cancelled() && needs.artifact-graph-plan.result == 'success'", "always()")),
]


@pytest.mark.parametrize("name,mutate", HARMLESS, ids=[h[0] for h in HARMLESS])
def test_the_workflow_rules_leave_harmless_changes_alone(tmp_path, name, mutate):
    got = run_workflow_variant(tmp_path, "harmless", mutate)
    for predicate, verdict in got.items():
        assert not not_run(verdict) and verdict["holds"] is BASE_HOLDS.get(predicate, True), (name, predicate, verdict["missing"])


def test_a_baseline_job_skipped_on_another_condition_is_no_reference(tmp_path):
    """Every job shares the draft-skip `if`, so a change that gives them all another condition keeps them equal to
    one another; the baseline job's own `if` is the reference only while it is the draft skip."""
    got = run_workflow_variant(tmp_path, "alike", lambda t: t.replace(
        GATED_IF, f"if: ${{{{ {GATE} && (github.event_name == 'push') }}}}"))
    for name, verdict in got.items():
        assert verdict["holds"] is False and "is conditional" in " ".join(verdict["missing"]), name
    always = run_workflow_variant(tmp_path, "never", lambda t: must_replace(
        t, f"    {GATED_IF}\n    # Supported OS:", f"    if: ${{{{ {GATE} && false }}}}\n    # Supported OS:"))
    assert always["unit_suite_on_every_version"]["holds"] is False
    assert "is conditional" in " ".join(always["unit_suite_on_every_version"]["missing"])


def test_the_visibility_gate_anded_with_the_draft_skip_is_no_condition(tmp_path):
    """D30 ANDs every job's `if` with the visibility gate (tests/test_ci_visibility_gate.py), which holds on every pull
    request of the public repository, so in the shapes that test pins it skips nothing there: in front of the baseline
    job's draft skip it leaves that `if` the reference, and alone, or as one `&&` term in parentheses, it is no
    condition."""
    import yaml
    jobs = yaml.safe_load(tracked_text(WORKFLOW))["jobs"]
    assert jobs["baseline"]["if"] == f"${{{{ {GATED_DRAFT_SKIP} }}}}"
    assert jobs["replay-suite"]["if"] == jobs["artifact-graph-plan"]["if"] == jobs["baseline"]["if"]
    assert f"if: {jobs['artifact-graph']['if']}" == ARTIFACT_IF
    got = rf.ci_enforces(_ci_repo(tmp_path))
    for name, verdict in got.items():
        assert not not_run(verdict) and verdict["holds"] is BASE_HOLDS.get(name, True), (name, verdict["missing"])
    assert not not_run(got["no_site_without_class"]["weaker"]) and got["no_site_without_class"]["weaker"]["holds"]
    # the gate as the artifact job's whole `if`: the jobs it needs are read as for a job with no `if`, the shards too,
    # whose `if` is the gate alone
    alone = run_workflow_variant(tmp_path, "alone", lambda t: must_replace(t, ARTIFACT_IF, f"if: ${{{{ {GATE[1:-1]} }}}}"))
    assert alone["artifact_check_clean"]["holds"] is True, alone["artifact_check_clean"]["missing"]


# (name, mutation, the predicates that turn false): the gate in any shape but those is a condition like another
GATE_REFUSED = [
    ("the gate joined with ||", lambda t: replace_last(t, GATED_IF, f"if: ${{{{ {GATE} || {DRAFT_SKIP} }}}}"),
     REPLAY_THREE),
    ("every gate joined with ||", lambda t: t.replace(GATED_IF, f"if: ${{{{ {GATE} || {DRAFT_SKIP} }}}}"),
     FOUR | {"unit_suite_on_every_version"}),
    ("a job without the gate", lambda t: replace_last(t, GATED_IF, f"if: ${{{{ {DRAFT_SKIP[1:-1]} }}}}"), REPLAY_THREE),
    ("the baseline job's gate without its draft skip", lambda t: must_replace(
        t, f"    {GATED_IF}\n    # Supported OS:", f"    if: ${{{{ {GATE[1:-1]} }}}}\n    # Supported OS:"), FOUR),
    ("the gate ANDed with another condition", lambda t: replace_last(
        t, GATED_IF, f"if: ${{{{ {GATE} && (github.event_name != 'pull_request') }}}}"), REPLAY_THREE),
    ("a gate that counts a payload with no repository as public", lambda t: replace_last(
        t, GATED_IF, GATED_IF.replace("toJSON(github.event.repository.private) == 'false'",
                                      "github.event.repository.private == false")), REPLAY_THREE),
]


@pytest.mark.parametrize("name,mutate,false_for", GATE_REFUSED, ids=[g[0] for g in GATE_REFUSED])
def test_the_visibility_gate_in_another_shape_is_a_condition(tmp_path, name, mutate, false_for):
    got = run_workflow_variant(tmp_path, "gate", mutate)
    assert_ci_verdicts(got, false_for - {"unit_suite_on_every_version"}, "is conditional")
    unit = got["unit_suite_on_every_version"]
    assert unit["holds"] is ("unit_suite_on_every_version" not in false_for), (name, unit["missing"])
    if not unit["holds"]:
        assert "is conditional" in " ".join(unit["missing"]), unit["missing"]


UNIT_STEP = "python3 -m pytest hooks/tests tests -q -n auto --dist loadfile"


@pytest.mark.parametrize("extra,message", [
    ("-k smoke", "`-k`"), ("-ksmoke", "`-ksmoke`"), ("-m 'not slow'", NOT_PLAIN),
    ("--collect-only", "`--collect-only`"), ("--co", "`--co`"), ("--setup-plan", "`--setup-plan`"),
    ("--deselect tests/test_x.py::test_y", "`--deselect`"), ("--deselect=hooks/tests/test_z.py", "`--deselect=hooks/tests/test_z.py`"),
    ("--lf", "`--lf`"), ("--sw", "`--sw`"), ("-o addopts=-q", "`-o`"),
    ("|| true", NOT_PLAIN), ("|| echo ok", NOT_PLAIN), ("| tee unit.log", NOT_PLAIN), ("&", NOT_PLAIN),
    ("--ignore=tests", "ignores it"), ("--ignore=hooks/tests", "ignores it"), ("--ignore-glob=*tests", "`--ignore-glob=*tests`"),
], ids=lambda v: v if isinstance(v, str) else None)
def test_unit_suite_rejects_what_narrows_or_swallows_the_run(tmp_path, extra, message):
    got = run_workflow_variant(tmp_path, "unit", lambda t: must_replace(t, UNIT_STEP, f"{UNIT_STEP} {extra}"))
    unit = got["unit_suite_on_every_version"]
    assert unit["holds"] is False, unit
    assert message in " ".join(unit["missing"]), unit["missing"]
    assert unit["ignored"] == []  # nothing is claimed about what it leaves out


def test_unit_suite_keeps_its_cell_when_the_run_is_whole(tmp_path):
    """Options that narrow nothing leave the predicate, its `ignored` list and its `versions` as they were."""
    base = rf.ci_enforces(_ci_repo(tmp_path / "base"))["unit_suite_on_every_version"]
    got = run_workflow_variant(tmp_path, "whole", lambda t: must_replace(t, UNIT_STEP, f"{UNIT_STEP} -x --tb=short -vv"))
    assert got["unit_suite_on_every_version"] == base and base["holds"]


def test_a_workflow_that_cannot_be_read_fails_every_predicate_closed(tmp_path):
    root = _ci_repo(tmp_path)
    (root / WORKFLOW).write_text("jobs: [unclosed\n", encoding="utf-8")
    git(root, "add", "-A")
    got = rf.ci_enforces(root)
    assert set(got) == {"compliant_replays_clean", "no_site_without_class", "artifact_check_clean",
                        "faults_returned_and_repaired", "unit_suite_on_every_version"}
    for name, verdict in got.items():
        assert verdict["holds"] is False and "baseline.yml" in " ".join(verdict["missing"]), name


@pytest.mark.parametrize("run,paths,ignores", [
    ("python3 -m pytest tests -q", ["tests"], []),
    ("pytest tests -q", ["tests"], []),
    ("python3 -m pytest hooks/tests tests -q -n auto --dist loadfile --ignore=tests/replay", ["hooks/tests", "tests"],
     ["tests/replay"]),
    ("python3 -m pytest tests/replay -q -p no:cacheprovider -rfE --durations=0 --ignore tests/x.py", ["tests/replay"],
     ["tests/x.py"]),
    ("python3 -m pytest tests -vv --tb=short -x -s --durations 5", ["tests"], []),
])
def test_a_plain_pytest_command_is_read(run, paths, ignores):
    assert rf._pytest_args(run) == (paths, ignores, None)


@pytest.mark.parametrize("run,why", [
    ("FOO=1 python3 -m pytest tests", NOT_PLAIN), ("python3 -m pip install pytest", NOT_PLAIN),
    ("python3 -m pytest tests || exit 1", NOT_PLAIN), ("python3 -m pytest tests | tee x.log", NOT_PLAIN),
    ("python3 -m pytest tests &", NOT_PLAIN), ("set -e\npython3 -m pytest tests", NOT_PLAIN),
    ("python3 -m pytest 'tests'", NOT_PLAIN), ("python3 -m pytest $TESTS", NOT_PLAIN),
    ("python3 -m pytest tests -k smoke", "`-k`"), ("python3 -m pytest tests -m slow", "`-m`"),
    ("python3 -m pytest tests --deselect=tests/a.py", "`--deselect=tests/a.py`"),
    ("python3 -m pytest tests/a.py::test_x", "`tests/a.py::test_x`"), ("python3 -m pytest tests -p xdist", "`-p`"),
    ("python3 -m pytest tests -n", "`-n`"), ("python3 -m pytest ./tests", "`./tests`"),
    ("python3 -m pytest tests/*.py", "`tests/*.py`"), ("python3 -m pytest -o addopts=-q tests", "`-o`"),
    ("python3 -m pytest tests --ignore-glob=*x", "`--ignore-glob=*x`"),
])
def test_anything_else_is_not_read_as_a_plain_run(run, why):
    paths, ignores, odd = rf._pytest_args(run)
    assert (paths, ignores) == ([], []) and why in odd, odd


@pytest.mark.parametrize("path,target,under", [
    ("tests", "tests/replay/test_faults.py", True), ("tests/replay/test_faults.py", "tests/replay/test_faults.py", True),
    ("tests/rep", "tests/replay/test_faults.py", False), ("tests/replay/test_f.py", "tests/replay/test_faults.py", False),
    ("hooks/tests", "tests/replay/test_faults.py", False),
])
def test_a_path_holds_what_is_under_it(path, target, under):
    assert rf._under(target, path) is under


def test_a_run_that_names_no_path_is_not_shown_to_run_the_test(tmp_path):
    """pytest.ini's testpaths are not read: a step that names no path is not evidence that it runs the test."""
    root = _ci_repo(tmp_path)
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = hooks/tests tests\n", encoding="utf-8")
    edit(root, WORKFLOW, "python3 -m pytest tests/test_artifact_graph.py -q", "python3 -m pytest -q")
    got = rf.ci_enforces(root)["artifact_check_clean"]
    assert got["holds"] is False and not_run(got)


# ================================================================ all facts, the JSON dump, the command line

def run_cli(*args, env_extra=None, cwd=REPO):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", **(env_extra or {}))
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True, env=env,
                          cwd=str(cwd), timeout=300)


def test_every_fact_is_derived_and_none_is_empty(real):
    assert set(real.facts) == set(rf.FACTS)
    for name, value in real.facts.items():
        assert value, f"{name} is empty"


def test_the_command_line_prints_each_fact_as_json(real):
    one = run_cli("--fact", "ci_python_versions", "--fact", "count_tests")
    assert one.returncode == 0, one.stderr
    assert json.loads(one.stdout)["facts"] == {k: real.facts[k] for k in ("ci_python_versions", "count_tests")}


def test_the_command_line_names_the_missing_input_and_exits_2(tmp_path):
    root = make_repo(tmp_path, {"README.md": "x"})
    done = run_cli("--root", str(root), "--fact", "ci_python_versions")
    assert done.returncode == 2 and "baseline.yml" in done.stderr and done.stdout == ""
    assert run_cli("--fact", "no_such_fact").returncode == 2


def test_two_runs_with_different_hash_seeds_print_the_same_bytes():
    runs = [subprocess.Popen([sys.executable, "-B", str(SCRIPT)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, cwd=str(REPO),
                             env={**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
                                  "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"})
            for seed in ("1", "4242")]
    outs = [p.communicate(timeout=300) for p in runs]
    assert [p.returncode for p in runs] == [0, 0], outs
    assert outs[0][0] == outs[1][0] and outs[0][0]


def test_the_module_runs_where_pytest_is_not_importable():
    """Nothing in the module needs the test framework: run it with pytest made unimportable."""
    code = ("import sys; sys.dont_write_bytecode = True; sys.modules['pytest'] = None; sys.modules['_pytest'] = None; "
            f"sys.argv = ['readme_facts', '--fact', 'ci_python_versions', '--fact', 'command_rows', '--fact', 'ci_enforces']; "
            f"sys.path.insert(0, {str(SCRIPT.parent)!r}); import readme_facts; raise SystemExit(readme_facts.main())")
    done = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, cwd=str(REPO), timeout=120,
                          env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
    assert done.returncode == 0, done.stderr
    assert "ci_python_versions" in json.loads(done.stdout)["facts"]


def test_the_module_has_no_personal_value_and_no_network_call():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"socket", "urllib", "http", "requests", "ssl", "ftplib", "smtplib"}
    assert not re.search("/ho" + "me/|/Us" + "ers/|[A-Za-z0-9._+-]+@[A-Za-z0-9-]+\\.[A-Za-z]{2,}", source)
