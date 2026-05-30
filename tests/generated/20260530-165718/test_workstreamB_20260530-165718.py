# Tests for Workstream B of task 20260530-165718 (Happy rendering cycles 6-8).
#   B1 — close-report path misresolution (AC-B1-1/2/3)
#   B2 — graphify tool-policy role registration (AC-B2-1/2/3)
#
# Version-agnostic: NO exact policy_version == N assertions (QA-B2 / AC-B2-4).
# Run: cd /root/.claude && python3 -m pytest tests/generated/20260530-165718/ -q

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path("/root/.claude")
POLICY_PATH = REPO_ROOT / "policies" / "tool-policy.v1.json"
DECIDE = REPO_ROOT / "scripts" / "close-scoring-decide.py"
RESOLVER = REPO_ROOT / "scripts" / "resolve-close-report.sh"
NESTED_CWD = "/dev/shm/dev-workspace/dot-claude"
VENV_PY = REPO_ROOT / "venv" / "bin" / "python3"


def _python() -> str:
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def _run_decide(task_id, cwd, env_extra=None, qa_rejected="false"):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [_python(), str(DECIDE), "--task-id", task_id,
         "--qa-ever-rejected", qa_rejected, "--repo-root", str(REPO_ROOT)],
        capture_output=True, text=True, cwd=cwd, env=env, timeout=20,
    )
    return proc.returncode, json.loads(proc.stdout.strip())


# ----------------------------------------------------------------------------
# B1
# ----------------------------------------------------------------------------

def test_AC_B1_1_nested_cwd_resolves_root_report(tmp_path):
    """AC-B1-1: from cwd=nested .claude repo, CLAUDE_PROJECT_DIR unset, a report
    at /root/docs/dev/close-report-<task>.md with CLOSE: YES resolves to
    events=[close_success_qa_pass], NOT 'close-report missing'."""
    task = "b1ac1-20260530-165718-tmp"
    report = Path("/root/docs/dev") / f"close-report-{task}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# tmp\n\nCLOSE: YES\n", encoding="utf-8")
    try:
        rc, out = _run_decide(task, cwd=NESTED_CWD)
        assert rc == 0
        assert out == {"events": ["close_success_qa_pass"], "skip_reason": None}, out
    finally:
        report.unlink(missing_ok=True)


def test_AC_B1_2_genuine_nested_report_still_found(tmp_path):
    """AC-B1-2: a report that genuinely lives at /root/.claude/docs/dev/ (and NOT
    at /root/docs/dev/) is still found — the nested candidate stays in the chain."""
    task = "b1ac2-20260530-165718-tmp"
    nested = REPO_ROOT / "docs" / "dev" / f"close-report-{task}.md"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("# nested\n\nCLOSE: YES\n", encoding="utf-8")
    root_dup = Path("/root/docs/dev") / f"close-report-{task}.md"
    assert not root_dup.exists(), "precondition: report must NOT exist at /root/docs/dev"
    try:
        rc, out = _run_decide(task, cwd=NESTED_CWD)
        assert rc == 0
        assert out["events"] == ["close_success_qa_pass"], out
        assert out["skip_reason"] is None, out
    finally:
        nested.unlink(missing_ok=True)


def test_AC_B1_3_resolver_probe_order_and_graceful_fallback():
    """AC-B1-3: resolver probe order CLAUDE_PROJECT_DIR -> git-toplevel-of-cwd ->
    /root/.claude -> CONTROL_ROOT; missing report -> python returns events=[] with
    a skip_reason and exit 0 (never non-zero on missing-report)."""
    text = RESOLVER.read_text(encoding="utf-8")
    # Anchor on the four candidate strings as they appear inside the `for` loop
    # (the close-report-${TASK_ID}.md suffix only occurs on the candidate lines,
    # never in the surrounding comments).
    i_proj = text.index("${CLAUDE_PROJECT_DIR:-}/docs/dev/close-report-")
    i_git = text.index("${GIT_TOPLEVEL:+${GIT_TOPLEVEL}/docs/dev/close-report-")
    i_claude = text.index("/root/.claude/docs/dev/close-report-")
    i_ctrl = text.index("${CONTROL_ROOT}/docs/dev/close-report-")
    assert i_proj < i_git < i_claude < i_ctrl, "probe order incorrect"

    # graceful fallback: missing report from nested cwd
    rc, out = _run_decide("zzz-nonexistent-20260530-165718", cwd=NESTED_CWD)
    assert rc == 0, f"gate must exit 0 on missing report, got {rc}"
    assert out["events"] == []
    assert out["skip_reason"] and "missing" in out["skip_reason"]


def test_AC_B1_3_python_falls_back_when_resolver_absent(tmp_path):
    """AC-B1-3: if resolve-close-report.sh is absent, the python falls back to its
    prior 2-candidate logic without crashing. Exercise _resolve_close_report_path
    against a repo_root that has no scripts/resolve-close-report.sh."""
    from importlib.machinery import SourceFileLoader
    mod = SourceFileLoader("csdecide", str(DECIDE)).load_module()
    fake_root = tmp_path / "fakerepo"
    (fake_root / "scripts").mkdir(parents=True)  # no resolver script inside
    p = mod._resolve_close_report_path(fake_root, "whatever-task")
    assert isinstance(p, Path)
    assert p.name == "close-report-whatever-task.md"


# ----------------------------------------------------------------------------
# B2
# ----------------------------------------------------------------------------

@pytest.fixture
def pr():
    sys.path.insert(0, str(REPO_ROOT / "hooks" / "lib"))
    import policy_registry as _pr
    _pr._reset_cache_for_tests()
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    yield _pr
    _pr._reset_cache_for_tests()


def test_AC_B2_1_graphify_role_registered_version_agnostic(pr):
    """AC-B2-1: graphify role exists with allowed_tools exactly [Read,Bash,Write]
    (no Skill/Edit); Read/Bash/Write-to-graphify-artifact all allowed; JSON
    schema-valid; policy_version is a monotonically-increased integer. NO exact
    policy_version == N assertion (version-agnostic)."""
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))  # schema-valid parse
    roles = policy["roles"]
    assert "graphify" in roles, "graphify role not registered"
    g = roles["graphify"]
    assert g["allowed_tools"] == ["Read", "Bash", "Write"], g["allowed_tools"]
    assert "Skill" not in g["allowed_tools"] and "Edit" not in g["allowed_tools"]

    # monotonic version check, NOT an exact integer
    assert isinstance(policy["policy_version"], int)
    assert policy["policy_version"] >= 5, "policy_version must have increased"

    assert pr.is_allowed("graphify", "Read", "/root/.claude/dev-registry/t1/graphify.json")[0]
    assert pr.is_allowed("graphify", "Bash", None)[0]
    assert pr.is_allowed(
        "graphify", "Write",
        "/root/.claude/dev-registry/t1/graphify/graphify-run.json",
    )[0]


def test_AC_B2_2_graphify_write_grant_is_tight(pr):
    """AC-B2-2: Write allowed inside dev-registry/<task>/graphify/; a fully-anchored
    shared-protected path is DENIED citing denied_write_path_prefixes (positive
    match, not allowlist miss); a non-graphify dev-registry path (outside
    /graphify/) is DENIED; graphify denied_write_path_prefixes EQUALS the shared
    protected list verbatim."""
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    g = policy["roles"]["graphify"]
    shared = policy["_shared_protected_path_prefixes"]
    assert g["denied_write_path_prefixes"] == shared, "denied list must equal shared verbatim"

    # allow inside graphify sub-prefix
    ok, _ = pr.is_allowed(
        "graphify", "Write",
        "/root/.claude/dev-registry/t1/graphify/focused-subgraph.json",
    )
    assert ok

    # deny anchored shared-protected path — must cite denied_write_path_prefixes
    denied, reason = pr.is_allowed("graphify", "Write", "/root/.claude/hooks/x.py")
    assert not denied
    assert "denied_write_path_prefixes" in reason, reason

    # deny non-graphify dev-registry path (proves sub-prefix scope, not whole registry)
    denied2, reason2 = pr.is_allowed(
        "graphify", "Write",
        "/root/.claude/dev-registry/t1/blast-radius-map.json",
    )
    assert not denied2
    assert "allowed_write_path_prefixes" in reason2, reason2


def test_AC_B2_2_codex_finding2_loadbearing_denials_hold_even_deep(pr):
    """Codex finding #2 (in_scope_minor): the policy_registry fnmatch '*' spans '/',
    so '*/.claude/dev-registry/*/graphify/' also allows a deeper graphify-namespace
    path like dev-registry/t1/other/graphify/. This is a GLOBAL matcher property
    shared by every role using a '*/<dir>/' prefix (cleaner, changelog-analyst, ...),
    NOT graphify-specific, and tightening it requires a shared-matcher change that is
    out of scope for B2 (affects 25 roles). The LOAD-BEARING denials AC-B2-2 actually
    requires still hold regardless of nesting depth: protected infra and NON-graphify
    dev-registry artifacts are DENIED even when deeply nested. This test pins those
    invariants so a future matcher tightening cannot silently regress them."""
    # protected infra denied (cites positive protected match)
    d1, r1 = pr.is_allowed("graphify", "Write", "/root/.claude/hooks/x.py")
    assert not d1 and "denied_write_path_prefixes" in r1
    # non-graphify dev-registry artifact denied, shallow AND deep
    d2, _ = pr.is_allowed("graphify", "Write", "/root/.claude/dev-registry/t1/blast-radius-map.json")
    assert not d2
    d3, _ = pr.is_allowed("graphify", "Write", "/root/.claude/dev-registry/t1/other/blast-radius-map.json")
    assert not d3, "deep non-graphify dev-registry path must remain denied"


def test_AC_B2_3_no_broad_context_write_grant():
    """AC-B2-3: graphify write prefixes must NOT contain the broad
    '*/docs/dev/context-'; context is patched by graphify-enrich.py --context-file
    under Bash (B2-S1 preferred path: omit context from the policy entirely)."""
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    prefixes = policy["roles"]["graphify"]["allowed_write_path_prefixes"]
    assert "*/docs/dev/context-" not in prefixes
    for p in prefixes:
        assert "context-" not in p, f"unexpected context- grant: {p}"
