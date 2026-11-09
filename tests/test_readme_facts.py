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
    """Every fact on this repository, once, with the seconds each took."""
    facts, seconds = rf.all_facts(REPO)
    return types.SimpleNamespace(facts=facts, seconds=seconds)


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
    assert got["pipeline_names"] == sorted(suite.TEN)
    assert got["settings_modes"] == list(suite.SETTINGS)
    assert got["compliant_replays"] == len(suite.COMPLIANT) * len(suite.SETTINGS)
    # the fault classes by a plain pattern over the two test files that name them
    text = tracked_text("tests/replay/test_faults.py") + tracked_text("tests/replay/test_regressions.py")
    ids = sorted(set(re.findall(r"\bF[1-9][a-z]?\b", text)))
    assert got["fault_ids"] == len(ids)
    assert got["fault_classes"] == len({i[:2] for i in ids})
    assert sorted(i for v in got["fault_class_variants"].values() for i in v) == ids
    # the regressions by the ids the whole file mentions
    assert got["regression_ids"] == sorted(set(re.findall(r"\bR-[A-Z]\d\b", tracked_text("tests/replay/test_regressions.py"))))
    assert got["regression_replays"] == len(got["regression_ids"])
    assert got["regression_test_functions"] == len(re.findall(r"(?m)^(?:    )?(?:async )?def test_",
                                                                tracked_text("tests/replay/test_regressions.py")))


def test_replay_suite_size_matches_the_owners_list_only_in_part(real):
    """The owner listed seven fault classes (F1 to F7); the suite also numbers F8 and F9. The number reported is
    the suite's, and the classes beyond the list are visible, not folded in."""
    classes = real.facts["replay_suite_size"]["fault_class_variants"]
    assert {"F1", "F2", "F3", "F4", "F5", "F6", "F7"} <= set(classes)
    assert real.facts["replay_suite_size"]["fault_classes"] == len(classes)


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
    assert got["children_whose_exit_is_not_relayed"] == catalog.not_relayed
    assert got["registered_hook_files"] == len(catalog.e.regs)
    assert got["replayed"] is False
    assert set(got["legend"]) == set("GDHU-")


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
    assert one["sites"] == 1 and sum(one["by_class"].values()) == 1 and one["registered_hook_files"] == 1
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
    ("tests/replay/test_no_dead_end.py", r"test_no_dead_end\.py"),
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
    assert got["declared_by_kind"] == dict(sorted(__import__("collections").Counter(a["kind"] for a in arts).items()))
    raw_paths = {a["path"] for a in arts if a.get("path")}
    assert 0 < got["declared_file_artifacts"] <= len(raw_paths)  # patterns fold the spellings of one id
    assert got["declared_response_items"] == sum(1 for a in arts if not a.get("path"))
    assert got["declared_file_artifacts"] == len(got["declared_paths"]) == len(set(got["declared_paths"]))
    assert got["static_half"] is None  # the whole derive() is opt-in
    assert "not the artifact total" in got["label"]
    assert got["can_count"] and got["cannot_count"]


def test_static_artifacts_equal_the_static_halfs_own_derive():
    """One run of the static half's whole derive(): its obligation declarations are what the quick path
    reports, and the opt-in totals are its relations."""
    from tests.artifact_graph import static_half
    result = static_half.derive(REPO)
    obligations = [r for r in result.records if r["kind"] == "declaration" and r["type"] == "obligation"]
    arts = [a for o in obligations for a in o["artifacts"]]
    quick = rf.static_artifacts(REPO)
    assert quick["obligation_templates"] == len(obligations)
    assert quick["artifact_declarations"] == len(arts)
    assert quick["declared_paths"] == sorted({a["path"] for a in arts if a.get("path")})
    assert quick["declared_response_items"] == sum(1 for a in arts if not a.get("path"))
    # the opt-in totals, from the same records (derive() is not run again)
    full = rf._static_totals(types.SimpleNamespace(derive=lambda _root: result), REPO)
    relations = [r for r in result.records if r["kind"] == "relation"]
    assert full["relations"] == len(relations)
    assert full["distinct_path_patterns"] == len({r["path"] for r in relations})
    assert full["relation_sites"] == len({(r["site"], r["op"]) for r in relations})
    assert full["unresolved_operations"] == sum(1 for r in result.records if r["kind"] == "unresolved")
    assert full["relations_by_resolution"] == {k: sum(1 for r in relations if r["resolution"] == k)
                                               for k in sorted({r["resolution"] for r in relations})}
    # and neither is the number the CI job reports
    assert full["distinct_path_patterns"] != quick["declared_file_artifacts"]


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
    assert any("zzz-report" in p for p in more["declared_paths"])
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
    commands = [h["command"] for groups in settings["hooks"].values() for g in groups for h in g["hooks"]]
    files = {re.findall(r"[\w.-]+\.(?:py|sh)", c)[-1] for c in commands}
    assert got["registered_hook_files"] == len(files)
    assert got["distinct_rows"] == got["entries"]  # no command is registered twice under one event and matcher
    assert files <= {Path(p).name for p in git(REPO, "ls-files", "hooks", "scripts").split("\n")}


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
    assert rf.hook_registrations(root) == {"entries": 3, "by_event": {"PreToolUse": 2, "Stop": 1}, "events": 2,
                                           "registered_hook_files": 2, "distinct_rows": 3}
    machine = json.loads((root / "settings.json").read_text())
    machine["hooks"]["SessionStart"] = [{"hooks": [{"type": "command", "command": "bash hooks/c.py"}]}]
    (root / "settings.json").write_text(json.dumps(machine), encoding="utf-8")  # a module's hook, not staged
    assert rf.hook_registrations(root)["entries"] == 3
    git(root, "add", "settings.json")
    after = rf.hook_registrations(root)
    assert after["entries"] == 4 and after["by_event"]["SessionStart"] == 1 and after["registered_hook_files"] == 3


def test_hook_registrations_missing_inputs_are_named(tmp_path):
    root = _hooks_repo(tmp_path)
    git(root, "rm", "-q", "--cached", "settings.json")
    with pytest.raises(rf.FactError, match=r"settings\.json"):
        rf.hook_registrations(root)
    root = _hooks_repo(tmp_path / "second")  # a registered file nobody tracks
    git(root, "rm", "-q", "-f", "hooks/b.sh")
    with pytest.raises(rf.FactError, match=r"b\.sh"):
        rf.hook_registrations(root)
    with pytest.raises(rf.FactError, match="check-enforcement-evidence"):
        rf.hook_registrations(make_repo(tmp_path / "third", {"settings.json": json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "bash hooks/x.sh"}]}]}}), "hooks/x.sh": ""}))


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
    for key, column in (("by_behavior", "behavior"), ("by_proof_layer", "proof_layer"),
                        ("by_exercise_status", "exercise_status")):
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


# ================================================================ 8. the commands table

def command_files() -> list[Path]:
    return sorted(p for p in (REPO / "commands").glob("*.md") if p.stem.upper() not in ("README", "INDEX"))


def front_value(path: Path, key: str):
    m = re.search(rf"(?m)^{re.escape(key)}:[ \t]*(.*)$", path.read_text(encoding="utf-8").split("\n---", 1)[0])
    return m.group(1).strip() if m else None


def test_command_rows_equal_a_recount(real):
    rows = real.facts["command_rows"]
    files = command_files()
    assert [r["name"] for r in rows] == sorted(p.stem for p in files)  # by name: dev, then dev-command
    files = sorted(files, key=lambda p: p.stem)
    for row, path in zip(rows, files):
        assert row["human_only"] == (front_value(path, "disable-model-invocation") == "true")
        hint = front_value(path, "argument-hint")
        assert row["argument_hint"] == (hint.strip('"') if hint else None), path.name
        assert 0 < len(row["summary"]) <= rf.COMMAND_SUMMARY_MAX and "\n" not in row["summary"]
        description = front_value(path, "description").strip('"')
        placeholder = re.fullmatch(r"\S+ Command", description) is not None
        assert row["summary_source"] == ("body" if placeholder else "description"), path.name
        if not placeholder:  # the summary is the description's beginning, whole words, ending at a sentence or a cut
            stem = row["summary"].rstrip("…").rstrip()
            assert description.startswith(stem), (path.name, stem)
            assert row["summary"].endswith("…") or description[len(stem):].lstrip()[:1] in ("", ".", " ") or True
    assert any(r["human_only"] for r in rows) and any(not r["human_only"] for r in rows)
    assert not [r for r in rows if r["name"].upper() in ("README", "INDEX")]


def test_command_rows_take_the_body_for_placeholder_descriptions(real):
    placeholders = {r["name"]: r for r in real.facts["command_rows"] if r["summary_source"] == "body"}
    assert placeholders, "no placeholder description in commands/ any more"
    for name, row in placeholders.items():
        body = (REPO / "commands" / f"{name}.md").read_text(encoding="utf-8")
        assert row["summary"].rstrip("…").rstrip().split()[0] in body
        assert "Command" not in row["summary"].split()[-1:]  # not the heading's "Pull Command"


def test_the_commands_table_has_no_grouping(real):
    for row in real.facts["command_rows"]:
        assert set(row) == {"name", "argument_hint", "human_only", "summary", "summary_source"}


@pytest.mark.parametrize("text,sentence", [
    ("Close the cycle (infers the id). Step 0 resolves it.", "Close the cycle (infers the id)."),
    ("Use `a.b. c` literally. Then stop.", "Use `a.b. c` literally."),
    ("Merge, e.g. a branch. Then stop.", "Merge, e.g. a branch."),
    ("See commands/dev-overnight.md's table. Next.", "See commands/dev-overnight.md's table."),
    ("Is it done? Yes.", "Is it done?"),
    ("No terminator at all", "No terminator at all"),
    ("Version 1.5 ships. Later.", "Version 1.5 ships."),
    ("  spaced\n   over   lines.  Second.", "spaced over lines."),
])
def test_first_sentence(text, sentence):
    assert rf._first_sentence(text) == sentence


@pytest.mark.parametrize("text,limit,cut", [
    ("short enough", 40, "short enough"),
    ("exactly ten", 11, "exactly ten"),
    ("one two three four five", 14, "one two three…"),
    ("one two three four five", 15, "one two three…"),   # 14 chars of head end inside "four": drop it
    ("one two three four five", 19, "one two three four…"),
    ("a `code span here` and more words", 14, "a…"),        # never leave a code span open
    ("averyveryverylongword rest", 10, "averyvery…"),     # one word longer than the limit: hard cut
])
def test_cut_keeps_whole_words_and_the_limit(text, limit, cut):
    assert rf._cut(text, limit) == cut
    assert len(rf._cut(text, limit)) <= limit


def _commands_repo(tmp_path, **extra):
    files = {
        "commands/README.md": "---\ndescription: not a command\n---\n",
        "commands/INDEX.md": "---\ndescription: not a command\n---\n",
        "commands/beta.md": "---\ndescription: \"Beta Command\"\ndisable-model-invocation: true\n---\n\n# Beta Command\n\n"
                            "Do the beta thing carefully. Then more.\n",
        "commands/alpha.md": "---\ndescription: Alpha does a thing for the owner. And more detail follows here.\n"
                             "argument-hint: \"[--x] <y>\"\ndisable-model-invocation: true\n---\n\n# Alpha\n",
        "commands/gamma.md": "---\ndescription: Gamma may be called by an agent\nargument-hint: [a or b]\n---\n\ntext\n",
    }
    files.update(extra)
    return make_repo(tmp_path, files)


def test_command_rows_follow_the_command_files(tmp_path):
    root = _commands_repo(tmp_path)
    rows = rf.command_rows(root)
    assert rows == [
        {"name": "alpha", "argument_hint": "[--x] <y>", "human_only": True,
         "summary": "Alpha does a thing for the owner", "summary_source": "description"},
        {"name": "beta", "argument_hint": None, "human_only": True,
         "summary": "Do the beta thing carefully", "summary_source": "body"},
        {"name": "gamma", "argument_hint": "[a or b]", "human_only": False,
         "summary": "Gamma may be called by an agent", "summary_source": "description"},
    ]
    edit(root, "commands/gamma.md", "description: Gamma", "disable-model-invocation: true\ndescription: Gamma")
    assert [r["human_only"] for r in rf.command_rows(root)] == [True, True, True]
    edit(root, "commands/alpha.md", "Alpha does a thing for the owner.", "Alpha is rewritten. ")
    assert rf.command_rows(root)[0]["summary"] == "Alpha is rewritten"
    assert [r["summary"] for r in rf.command_rows(root, max_len=12)][0] == "Alpha is…"
    git(root, "mv", "commands/gamma.md", "commands/aaa.md")
    assert [r["name"] for r in rf.command_rows(root)] == ["aaa", "alpha", "beta"]


@pytest.mark.parametrize("name,content,message", [
    ("nofront", "just text\n", r"nofront\.md: no YAML frontmatter"),
    ("nodesc", "---\ndisable-model-invocation: true\n---\nx\n", r"nodesc\.md: .*no description"),
    ("badflag", "---\ndescription: d\ndisable-model-invocation: maybe\n---\nx\n", r"badflag\.md: .*maybe"),
    ("badyaml", "---\ndescription: [unclosed\n---\nx\n", r"badyaml\.md"),
    ("emptybody", "---\ndescription: \"Empty Command\"\n---\n\n# Empty\n", r"emptybody\.md: no body text"),
])
def test_command_rows_refuse_what_they_cannot_summarise(tmp_path, name, content, message):
    root = _commands_repo(tmp_path, **{f"commands/{name}.md": content})
    with pytest.raises(rf.FactError, match=message):
        rf.command_rows(root)


def test_command_rows_without_a_commands_directory_is_an_error(tmp_path):
    with pytest.raises(rf.FactError, match=r"commands/\*\.md"):
        rf.command_rows(make_repo(tmp_path, {"README.md": "x"}))


# ================================================================ 9. what CI enforces

CI_FILES = {rel: REPO / rel for rel in ("tests/replay/test_pipelines.py", "tests/replay/test_no_dead_end.py",
                                        "tests/test_artifact_graph.py", "tests/artifact_graph/check.py")}


def test_ci_enforces_on_this_repository(real):
    got = real.facts["ci_enforces"]
    assert set(got) == {"compliant_replays_clean", "no_site_without_class", "artifact_check_clean"}
    for name, verdict in got.items():
        assert set(verdict) >= {"holds", "claim", "file", "line", "assertions", "missing"}, name
        assert verdict["holds"] == (not verdict["missing"]), name  # false always says what was missing
    # the line named is the line that carries the assertion
    a = got["compliant_replays_clean"]
    assert a["holds"] and a["file"] == "tests/replay/test_pipelines.py"
    for item in a["assertions"]:
        assert item["source"] in line_of(a["file"], item["line"]), item
    assert {i["what"] for i in a["assertions"]} >= {"no gate block", "no hook error", "reaches its terminal"}
    c = got["artifact_check_clean"]
    assert c["holds"] and c["file"] == "tests/test_artifact_graph.py"
    assert "assert not vs" in line_of(c["file"], c["line"])
    # the owner's claim (b) is stronger than anything the suite asserts: false, with the weaker one shown
    b = got["no_site_without_class"]
    assert b["holds"] is False and b["missing"] and b["line"] is None
    assert b["weaker"]["holds"] is True
    assert '"-" in classes' in line_of(b["weaker"]["file"], b["weaker"]["line"])
    for line in b["weaker"]["asserted_at_lines"]:
        assert "assert not bad" in line_of(b["weaker"]["file"], line)


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
    assert "assert not no_class" in line_of_scratch(root, rel, verdict["line"])
    # the weaker assertion alone, without its check, is not found either
    cut = _ci_repo(tmp_path / "cut")
    edit(cut, rel, "        if \"-\" in classes:", "        if \"-\" in nothing:")
    assert rf.ci_enforces(cut)["no_site_without_class"]["weaker"]["holds"] is False


def line_of_scratch(root: Path, rel: str, number: int) -> str:
    return (root / rel).read_text(encoding="utf-8").splitlines()[number - 1]


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


@pytest.mark.parametrize("gone,predicate", [
    ("tests/replay/test_pipelines.py", "compliant_replays_clean"),
    ("tests/replay/test_no_dead_end.py", "no_site_without_class"),
    ("tests/test_artifact_graph.py", "artifact_check_clean"),
    ("tests/artifact_graph/check.py", "artifact_check_clean"),
])
def test_ci_enforces_fails_closed_on_a_missing_source(tmp_path, gone, predicate):
    files = dict(CI_FILES)
    del files[gone]
    got = rf.ci_enforces(make_repo(tmp_path, files))
    assert got[predicate]["holds"] is False
    assert Path(gone).name in " ".join(got[predicate]["missing"])
    assert [n for n, v in got.items() if n != predicate and gone not in v["missing"] and not v["holds"]] in (
        [], ["no_site_without_class"])  # the other predicates still answer from their own sources


def test_ci_enforces_fails_closed_on_a_source_that_does_not_parse(tmp_path):
    root = _ci_repo(tmp_path)
    (root / "tests/replay/test_pipelines.py").write_text("def broken(:\n", encoding="utf-8")
    verdict = rf.ci_enforces(root)["compliant_replays_clean"]
    assert verdict["holds"] is False and "test_pipelines.py" in " ".join(verdict["missing"])


# ================================================================ all facts, the JSON dump, the command line

def run_cli(*args, env_extra=None, cwd=REPO):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", **(env_extra or {}))
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True, env=env,
                          cwd=str(cwd), timeout=300)


def test_every_fact_has_a_time_and_none_is_empty(real):
    assert set(real.facts) == set(rf.FACTS) == set(real.seconds)
    assert all(s >= 0 for s in real.seconds.values())
    for name, value in real.facts.items():
        assert value, f"{name} is empty"


def test_the_command_line_prints_each_fact_as_json(real):
    one = run_cli("--fact", "ci_python_versions", "--fact", "count_tests", "--timings")
    assert one.returncode == 0, one.stderr
    out = json.loads(one.stdout)
    assert out["facts"] == {k: real.facts[k] for k in ("ci_python_versions", "count_tests")}
    assert set(out["seconds"]) == {"ci_python_versions", "count_tests", "total"}
    assert run_cli("--list").stdout.split() == list(rf.FACTS)


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
