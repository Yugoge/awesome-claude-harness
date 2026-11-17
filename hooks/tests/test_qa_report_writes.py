"""
qa writes report and evidence files under the project's reports/ and tests/reports/ only

Owner decision (2026-11-17): a qa subagent may write under `<project>/reports/` and
`<project>/tests/reports/`; it still may NOT edit test code anywhere else under `tests/`, nor
hooks, settings or source. The qa row of policies/tool-policy.v1.json names the two directories in
`write_carveout_prefixes` (hooks/lib/policy_registry.py): a target is in a carve-out only when its
logical form AND its resolved form both lie inside one (anchored at the project, never at the
carve-out directory's own realpath), and an existing file there with more than one hard link is
not; such a target passes the allow list and the deny prefixes the carve-out sits under
(`/tests/`), and no other deny prefix.

Three levels, each run with HOME and the git global config in tmp_path:
- the registry (is_allowed) on a real project tree in tmp_path, symlinks and hard links included;
- the hook file (hooks/pretool-tool-policy.py) as a qa subagent, its raw-temp roots moved off
  tmp_path as hooks/tests/test_clean_approved_writes.py does, for Write, Edit and Bash forms;
- every PreToolUse command settings.json registers, run as the CLI runs it, for the owner's
  `docker exec ... > tests/reports/age.txt <<'SQL'` case and its neighbours, from a project outside
  the raw temp roots (pytest's tmp_path when it is, else /dev/shm).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
import policy_registry  # noqa: E402

HOOK = ROOT / "hooks" / "pretool-tool-policy.py"
SID = "3c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f"
QA = ("a0qa", "qa")
BLOCK = "BLOCKED by tool-policy.v1: "
RUN_POLICY = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('tool_policy_qa_reports', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)\n"
    "m._SYSTEM_TEMP_ROOTS = ('/nonexistent-ob-qa-reports-raw-temp',)\n"
    "m.main()\n"
)
OWNER_CASE = ("docker exec -i app-postgres psql -X -U app -d app -P pager=off "
              "> tests/reports/age.txt <<'SQL'\n"
              "SELECT now() - min(created_at) AS oldest_job_age, count(*) AS jobs\n"
              "FROM jobs WHERE status = 'pending';\n"
              "SQL")


def _tree(project: Path) -> Path:
    """A product project: test code, a reports tree, hooks and settings."""
    for d in ("tests/reports", "tests/unit", "reports", "hooks", ".claude/hooks", "src"):
        (project / d).mkdir(parents=True, exist_ok=True)
    for f in ("tests/test_x.py", "tests/unit/test_y.py", "hooks/h.py", ".claude/hooks/h.py",
              "settings.json", ".claude/settings.json", ".claude/settings.local.json", "src/app.py"):
        (project / f).write_text("x\n")
    return project


def _links(project: Path, outside: Path) -> None:
    """Symlinked and hard-linked escapes out of the two carve-outs."""
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "o.txt").write_text("o\n")
    r, tr = project / "reports", project / "tests" / "reports"
    (tr / "to-test").symlink_to(project / "tests" / "test_x.py")
    (tr / "to-test-rel").symlink_to(Path("..") / "test_x.py")
    (tr / "to-tests").symlink_to(project / "tests")
    (tr / "to-hooks").symlink_to(project / "hooks")
    (r / "to-settings").symlink_to(project / ".claude" / "settings.json")
    (r / "to-claude-hooks").symlink_to(project / ".claude" / "hooks")
    (r / "to-outside").symlink_to(outside)
    (r / "to-root-settings").symlink_to(project / "settings.json")
    os.link(project / "tests" / "test_x.py", tr / "hard-test")
    # A sibling directory whose name is a carve-out's, symlinked: the carve-out is the logical path.
    (project / "tests" / "unit" / "reports").symlink_to(tr)


ALLOWED_REL = [
    "reports/qa-age.txt",
    "reports/sub/deeper/evidence.json",
    "tests/reports/age.txt",
    "tests/reports/run-1/screenshot.png",
    "tests/reports/./age.txt",
    "tests//reports/age.txt",
    "reports/../reports/x.md",
]
REFUSED_REL = [
    "tests/test_x.py",
    "tests/unit/test_y.py",
    "tests/conftest.py",
    "tests/reports/../test_x.py",
    "tests/reports/./../x.py",
    "tests//reports/../x",
    "tests/reports/../../hooks/h.py",
    "reports/../tests/test_x.py",
    "tests/reportsx/a.txt",
    "tests/reports-old/a.txt",
    "tests/Reports/a.txt",
    "tests/unit/reports/a.txt",
    "Tests/reports/a.txt",
    "reportsx/a.txt",
    "hooks/h.py",
    ".claude/hooks/h.py",
    "settings.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
    "src/app.py",
]
REFUSED_LINKS = [
    "tests/reports/to-test",
    "tests/reports/to-test-rel",
    "tests/reports/to-tests/test_x.py",
    "tests/reports/to-tests/new_test.py",
    "tests/reports/to-hooks/h.py",
    "reports/to-settings",
    "reports/to-claude-hooks/h.py",
    "reports/to-outside/o.txt",
    "reports/to-root-settings",
    "tests/reports/hard-test",
]


# ------------------------------------------------------------------ the registry


@pytest.fixture
def project(tmp_path, monkeypatch):
    p = _tree(tmp_path / "product")
    _links(p, tmp_path / "outside")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(p))
    monkeypatch.chdir(p)
    policy_registry._reset_cache_for_tests()
    assert policy_registry.load_policy() is not None
    yield p
    policy_registry._reset_cache_for_tests()


@pytest.mark.parametrize("absolute", [False, True], ids=["relative", "absolute"])
@pytest.mark.parametrize("rel", ALLOWED_REL)
@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
def test_qa_writes_reports_and_tests_reports(project, tool, rel, absolute):
    target = str(project / rel) if absolute else rel
    assert policy_registry.is_allowed("qa", tool, target) == (True, "ok")


@pytest.mark.parametrize("absolute", [False, True], ids=["relative", "absolute"])
@pytest.mark.parametrize("rel", REFUSED_REL + REFUSED_LINKS)
@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_qa_still_refused_outside_the_two_reports_trees(project, tool, rel, absolute):
    target = str(project / rel) if absolute else rel
    allowed, reason = policy_registry.is_allowed("qa", tool, target)
    assert not allowed, (target, reason)


def test_qa_test_code_keeps_its_test_denial(project):
    for rel in ("tests/test_x.py", "tests/reports/../test_x.py", "tests/reports/to-test",
                "tests/reports/to-tests/new_test.py", "tests/reports/hard-test"):
        allowed, reason = policy_registry.is_allowed("qa", "Write", rel)
        assert (allowed, reason.endswith("matches denied_write_path_prefixes")) == (False, True), (rel, reason)


def test_a_carved_out_directory_that_is_itself_a_symlink_into_tests_is_no_carve_out(tmp_path, monkeypatch):
    p = _tree(tmp_path / "product")
    shutil.rmtree(p / "tests" / "reports")
    (p / "tests" / "reports").symlink_to(p / "tests")
    shutil.rmtree(p / "reports")
    (p / "reports").symlink_to(p / "hooks")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(p))
    monkeypatch.chdir(p)
    policy_registry._reset_cache_for_tests()
    try:
        for rel in ("tests/reports/test_x.py", "tests/reports/new.txt", "reports/h.py", "reports/new.txt"):
            allowed, reason = policy_registry.is_allowed("qa", "Write", rel)
            assert not allowed, (rel, reason)
    finally:
        policy_registry._reset_cache_for_tests()


def test_a_project_reached_through_a_symlink_keeps_its_carve_out(tmp_path, monkeypatch):
    real = _tree(tmp_path / "real-product")
    (tmp_path / "linked-product").symlink_to(real)
    logical = tmp_path / "linked-product"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(logical))
    monkeypatch.chdir(logical)
    policy_registry._reset_cache_for_tests()
    try:
        assert policy_registry.is_allowed("qa", "Write", str(logical / "tests/reports/a.txt")) == (True, "ok")
        assert policy_registry.is_allowed("qa", "Write", str(real / "tests/reports/a.txt")) == (True, "ok")
        assert not policy_registry.is_allowed("qa", "Write", str(logical / "tests/test_x.py"))[0]
    finally:
        policy_registry._reset_cache_for_tests()


def test_only_the_qa_row_holds_a_carve_out_and_it_names_the_two_directories(project):
    roles = policy_registry.load_policy()["roles"]
    holders = {r: spec["write_carveout_prefixes"] for r, spec in roles.items() if "write_carveout_prefixes" in spec}
    assert holders == {"qa": ["/reports/", "/tests/reports/"]}
    assert "/tests/" in roles["qa"]["denied_write_path_prefixes"]
    for prefix in roles["qa"]["allowed_write_path_prefixes"]:
        assert "reports" not in prefix, prefix


@pytest.mark.parametrize("rel", ["reports/x.txt", "tests/reports/x.txt"])
def test_no_other_role_gains_a_reports_write(project, rel):
    policy = policy_registry.load_policy()
    for role, spec in policy["roles"].items():
        if role == "qa":
            continue
        allowed, _ = policy_registry.is_allowed(role, "Write", rel)
        wildcard = "*" in spec.get("allowed_write_path_prefixes", [])
        denied_tests = "/tests/" in spec.get("denied_write_path_prefixes", [])
        assert allowed == (wildcard and not (denied_tests and rel.startswith("tests/"))), (role, rel)


@pytest.mark.parametrize("entry", ["*/reports/", "reports/", "/reports", "/tests/../hooks/", "/reports/*", ""])
def test_a_malformed_carve_out_entry_carves_nothing(project, entry):
    pol = {"allowed_write_path_prefixes": ["*/docs/codex/"], "denied_write_path_prefixes": ["/tests/"],
           "write_carveout_prefixes": [entry]}
    for rel in ("reports/x.txt", "tests/reports/x.txt", "hooks/h.py"):
        assert not policy_registry._check_write_path(pol, rel)[0], (entry, rel)


def test_a_carve_out_waives_only_the_deny_prefixes_it_sits_under(project):
    pol = {"allowed_write_path_prefixes": ["*/docs/codex/"],
           "denied_write_path_prefixes": ["/tests/", "/tests/reports/secret/", "/reports/"],
           "write_carveout_prefixes": ["/tests/reports/"]}
    assert policy_registry._check_write_path(pol, "tests/reports/a.txt") == (True, "ok")
    assert not policy_registry._check_write_path(pol, "tests/reports/secret/a.txt")[0]
    assert not policy_registry._check_write_path(pol, "reports/a.txt")[0]


def test_a_declared_write_meets_the_same_carve_out(project):
    # A path the qa dispatch's own obligation declares takes the row's deny prefixes only
    # (pretool-tool-policy.py _declared_write_allowed): the carve-out holds there too.
    import importlib.util
    spec = importlib.util.spec_from_file_location("tool_policy_qa_reports_declared", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    hook._bootstrap_security()
    assert hook._declared_write_allowed("qa", "Write", "tests/reports/qa-report.json") == (True, "ok")
    for rel in ("tests/test_x.py", "tests/reports/../test_x.py", "tests/reports/to-test", "tests/reports/hard-test"):
        allowed, reason = hook._declared_write_allowed("qa", "Write", rel)
        assert not allowed and reason.endswith("matches denied_write_path_prefixes"), (rel, reason)


# ------------------------------------------------------------------ the hook file


def _payload(tool: str, tool_input: dict, cwd: Path) -> dict:
    return {"session_id": SID, "transcript_path": str(cwd.parent / "home" / ".claude" / "projects" / "-p" / f"{SID}.jsonl"),
            "cwd": str(cwd), "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "agent_id": QA[0], "agent_type": QA[1], "subagent_type": QA[1]}


def _env(tmp_path: Path, project: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(project),
               CLAUDE_STATE_DIR=str(tmp_path / "state"), GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"),
               GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def run_hook(tmp_path: Path, project: Path, tool: str, tool_input: dict):
    return subprocess.run([sys.executable, "-c", RUN_POLICY, str(HOOK)],
                          input=json.dumps(_payload(tool, tool_input, project)), capture_output=True,
                          text=True, cwd=str(project), env=_env(tmp_path, project), timeout=60)


def _forms(rel: str) -> dict:
    return {"Write": ("Write", {"file_path": rel, "content": "x"}),
            "Edit": ("Edit", {"file_path": rel, "old_string": "a", "new_string": "b"}),
            "redirect": ("Bash", {"command": f"echo x > {rel}"}),
            "append": ("Bash", {"command": f"echo x >> {rel}"}),
            "tee": ("Bash", {"command": f"echo x | tee {rel}"}),
            "tee-a": ("Bash", {"command": f"echo x | tee -a {rel}"}),
            "cp": ("Bash", {"command": f"cp notes.txt {rel}"}),
            "mv": ("Bash", {"command": f"mv notes.txt {rel}"}),
            "heredoc": ("Bash", {"command": f"cat > {rel} <<'EOF'\nrow\nEOF"})}


FORMS = list(_forms("x"))


@pytest.fixture
def hook_project(tmp_path):
    p = _tree(tmp_path / "product")
    _links(p, tmp_path / "outside")
    return p


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("rel", ["reports/qa-age.txt", "tests/reports/age.txt", "tests/reports/run-1/e.json"])
def test_hook_lets_qa_write_the_reports_trees(tmp_path, hook_project, rel, form):
    tool, tool_input = _forms(rel)[form]
    proc = run_hook(tmp_path, hook_project, tool, tool_input)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("rel", ["tests/test_x.py", "tests/reports/../test_x.py", "tests/reports/./../x.py",
                                 "tests//reports/../x", "tests/reports/to-test", "tests/reports/to-tests/test_x.py",
                                 "tests/reports/hard-test", "reports/to-settings", "reports/to-outside/o.txt",
                                 "tests/reports/to-hooks/h.py", "hooks/h.py", ".claude/hooks/h.py",
                                 ".claude/settings.json", "settings.json", "src/app.py"])
def test_hook_still_refuses_qa_outside_the_reports_trees(tmp_path, hook_project, rel, form):
    tool, tool_input = _forms(rel)[form]
    proc = run_hook(tmp_path, hook_project, tool, tool_input)
    assert proc.returncode == 2 and proc.stderr.startswith(BLOCK), (rel, form, proc.stderr)


def test_hook_judges_each_target_of_one_command(tmp_path, hook_project):
    ok = run_hook(tmp_path, hook_project, "Bash", {"command": "echo x | tee reports/a tests/reports/b"})
    assert ok.returncode == 0, ok.stderr
    mixed = run_hook(tmp_path, hook_project, "Bash", {"command": "echo x | tee tests/reports/b tests/test_x.py"})
    assert mixed.returncode == 2 and "tests/test_x.py" in mixed.stderr, mixed.stderr


def test_hook_owner_case_with_an_absolute_target(tmp_path, hook_project):
    command = OWNER_CASE.replace("> tests/reports/age.txt", f"> {hook_project}/tests/reports/age.txt")
    assert run_hook(tmp_path, hook_project, "Bash", {"command": command}).returncode == 0


# ------------------------------------------------------------------ the registered pipeline


def _outside_temp_base(tmp_path: Path) -> Path:
    """A writable directory outside /tmp and /var/tmp, which the scratch rule denies every role."""
    def free(p: Path) -> bool:
        real = os.path.realpath(p)
        return not any(real == r or real.startswith(r + "/") for r in ("/tmp", "/var/tmp"))
    if free(tmp_path):
        return tmp_path
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK) and free(shm):
        base = shm / f"ob-qa-reports-{uuid.uuid4().hex[:12]}"
        base.mkdir()
        return base
    pytest.skip("no writable directory outside /tmp and /var/tmp for a project the CLI would run in")


@pytest.fixture
def pipeline_project(tmp_path):
    base = _outside_temp_base(tmp_path)
    p = _tree(base / "product")
    (p / "notes.txt").write_text("n\n")
    _links(p, base / "outside")
    yield p
    if base != tmp_path:
        shutil.rmtree(base, ignore_errors=True)


def run_pipeline(tmp_path: Path, project: Path, tool: str, tool_input: dict) -> list:
    """Every PreToolUse command settings.json registers for ``tool``, run as the CLI runs it."""
    env = _env(tmp_path, project)
    env["CLAUDE_HOME"] = str(ROOT)
    payload = json.dumps(_payload(tool, tool_input, project))
    out = []
    for group in json.loads((ROOT / "settings.json").read_text())["hooks"]["PreToolUse"]:
        matcher = group.get("matcher")
        if matcher and matcher != "*" and not re.fullmatch(matcher, tool):
            continue
        for h in group["hooks"]:
            proc = subprocess.run(["bash", "-c", h["command"]], input=payload, capture_output=True, text=True,
                                  cwd=str(project), env=env, timeout=h.get("timeout", 120))
            out.append((h["command"], proc))
    assert out, tool
    return out


def _refusals(results: list) -> list:
    return [(cmd, p.returncode, p.stderr) for cmd, p in results if p.returncode == 2]


def test_pipeline_owner_case_is_allowed_for_qa(tmp_path, pipeline_project):
    results = run_pipeline(tmp_path, pipeline_project, "Bash", {"command": OWNER_CASE})
    assert not _refusals(results), _refusals(results)


@pytest.mark.parametrize("tool,tool_input", [
    ("Write", {"file_path": "tests/reports/age.txt", "content": "age\n"}),
    ("Write", {"file_path": "reports/qa-evidence.json", "content": "{}\n"}),
    ("Bash", {"command": "echo x | tee -a reports/log.txt"}),
    ("Bash", {"command": "cp notes.txt tests/reports/notes.txt"}),
], ids=["write-tests-reports", "write-reports", "tee-reports", "cp-tests-reports"])
def test_pipeline_qa_writes_the_reports_trees(tmp_path, pipeline_project, tool, tool_input):
    results = run_pipeline(tmp_path, pipeline_project, tool, tool_input)
    assert not _refusals(results), _refusals(results)


@pytest.mark.parametrize("tool,tool_input", [
    ("Write", {"file_path": "tests/test_x.py", "content": "x"}),
    ("Edit", {"file_path": "tests/unit/test_y.py", "old_string": "x", "new_string": "y"}),
    ("Write", {"file_path": "tests/reports/../test_x.py", "content": "x"}),
    ("Write", {"file_path": "tests/reports/to-test", "content": "x"}),
    ("Write", {"file_path": "tests/reports/hard-test", "content": "x"}),
    ("Write", {"file_path": "reports/to-settings", "content": "x"}),
    ("Write", {"file_path": ".claude/hooks/h.py", "content": "x"}),
    ("Write", {"file_path": ".claude/settings.json", "content": "x"}),
    ("Bash", {"command": OWNER_CASE.replace("tests/reports/age.txt", "tests/test_x.py")}),
    ("Bash", {"command": OWNER_CASE.replace("tests/reports/age.txt", "tests/reports/../conftest.py")}),
    ("Bash", {"command": OWNER_CASE.replace("tests/reports/age.txt", "tests/reports/to-tests/test_x.py")}),
    ("Bash", {"command": "echo x | tee tests/reports/ok.txt tests/unit/test_y.py"}),
    ("Bash", {"command": "cp notes.txt reports/to-outside/o.txt"}),
    ("Bash", {"command": "echo x >> hooks/h.py"}),
], ids=["write-test", "edit-test", "traversal", "symlink-file", "hard-link", "symlink-settings", "claude-hooks",
        "claude-settings", "owner-case-test-code", "owner-case-traversal", "owner-case-symlinked-dir",
        "tee-second-target", "cp-symlink-outside", "append-hooks"])
def test_pipeline_still_refuses_qa(tmp_path, pipeline_project, tool, tool_input):
    results = run_pipeline(tmp_path, pipeline_project, tool, tool_input)
    refused = _refusals(results)
    assert any(err.startswith(BLOCK) for _, _, err in refused), [(c, p.returncode, p.stderr) for c, p in results]
