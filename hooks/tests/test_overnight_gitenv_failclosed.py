"""Fail-closed detectors for the overnight actor's git-environment provisioning.

Two halves of one fail-open, scoped together because closing either alone leaves
the other open:

  DEFECT ONE (launcher) -- scripts/create-overnight-state.sh provisions the actor
  git wrappers inside a guarded branch (`elif [[ -x "$GITENV_HELPER" ]]`, and the
  in-place `[[ -f "$INPLACE_ENV_HELPER" ]] &&` guard). When the helper is missing
  or not executable the branch simply does not run: the actor_git_env.* fields
  stay empty and the session record is published anyway. A downstream consumer
  then reads a record that looks entirely normal while carrying no wrapper
  provisioning at all.

  DEFECT TWO (actor startup instruction) -- the documented startup instruction
  separates `source <env_helper>` from the git op that verifies it with a
  statement separator instead of a conjunction, so a non-zero source does not
  stop the git call and execution proceeds to whatever git $PATH resolves.

MEASURED TRAP (earlier lane, do not undo): every lab here is built under
/dev/shm, NOT under /tmp. The overnight isolation boundary mounts its own tmpfs
over /tmp, which shadows a lab placed there and silently fabricates a false
read-only-filesystem result.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# Overridable so the fail-first measurement can be re-run against a neutralized
# (pre-fix) copy of the launcher on demand, with no other input changed.
LAUNCHER = Path(os.environ.get("OVERNIGHT_LAUNCHER_UNDER_TEST")
                or REPO / "scripts" / "create-overnight-state.sh")
SCRIPTS = REPO / "scripts"
DOC = REPO / "commands" / "dev-overnight.md"
PROMPT_WORKFLOW = REPO / "hooks" / "prompt-workflow.py"

LAB_BASE = Path(os.environ.get("OVERNIGHT_GITENV_LAB_BASE")
                or "/dev/shm/claude-gitenv-labs")

# The provisioning region is sliced out of the live launcher at test time, so the
# harness can never drift into a stale copy of the code it claims to test.
REGION_START = "# --- Prepare + CAPTURE the overnight actor's git PATH wrappers"
REGION_END = "# --- Launch git self-test: record honest guarantee fields"

ISOLATED_KINDS = ["registered_worktree", "fresh_clone_checkout"]
ALL_KINDS = ["in_place"] + ISOLATED_KINDS


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def lab():
    LAB_BASE.mkdir(parents=True, exist_ok=True)
    d = LAB_BASE / uuid.uuid4().hex[:12]
    d.mkdir()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def extract_region() -> str:
    lines = LAUNCHER.read_text(encoding="utf-8").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(REGION_START)), None)
    end = next((i for i, ln in enumerate(lines) if ln.startswith(REGION_END)), None)
    assert start is not None, f"region start anchor vanished from {LAUNCHER}"
    assert end is not None and end > start, f"region end anchor vanished from {LAUNCHER}"
    return "\n".join(lines[start:end])


def build_scripts_dir(lab: Path, helpers: dict[str, int | None]) -> Path:
    """Synthetic scripts dir: $0 roots SCRIPT_DIR_ABS here, so helper presence
    and mode are controllable without touching the real repo."""
    scripts = lab / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name, mode in helpers.items():
        if mode is None:
            continue
        dst = scripts / name
        shutil.copy2(SCRIPTS / name, dst)
        dst.chmod(mode)
    if (scripts / "overnight-git-env.sh").exists():
        shutil.copytree(SCRIPTS / "overnight-git", scripts / "overnight-git", dirs_exist_ok=True)
    return scripts


def run_region(lab: Path, kind: str, helpers: dict[str, int | None],
               with_wrapper_sources: bool = True) -> subprocess.CompletedProcess:
    scripts = build_scripts_dir(lab, helpers)
    if not with_wrapper_sources:
        shutil.rmtree(scripts / "overnight-git", ignore_errors=True)
    main_root = lab / "main"
    main_root.mkdir(exist_ok=True)
    wt = main_root if kind == "in_place" else lab / "wt"
    wt.mkdir(exist_ok=True)
    harness = scripts / "region-harness.sh"
    harness.write_text(
        "#!/bin/bash\nset -euo pipefail\n"
        f'MAIN_ROOT="{main_root}"\nWORKTREE_PATH="{wt}"\nISOLATION_KIND="{kind}"\n'
        + extract_region()
        + '\necho "REGION_PUBLISHED shim=[$ACTOR_GIT_SHIM] helper=[$ACTOR_ENV_HELPER_PATH]"\n',
        encoding="utf-8",
    )
    harness.chmod(0o755)
    return subprocess.run([str(harness)], capture_output=True, text=True, timeout=120)


def make_repo(main_root: Path) -> None:
    """Minimal primary checkout: HEAD on 'work', protected branch 'master'.
    No branch-creating verb is used -- HEAD is re-pointed before the first commit."""
    main_root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")

    def g(*args):
        return subprocess.run(["git", "-C", str(main_root), *args],
                              capture_output=True, text=True, env=env, timeout=60)

    subprocess.run(["git", "init", "-q", str(main_root)], capture_output=True,
                   text=True, env=env, timeout=60)
    g("config", "user.email", "lab@example.invalid")
    g("config", "user.name", "lab")
    g("symbolic-ref", "HEAD", "refs/heads/work")
    g("commit", "--allow-empty", "-q", "-m", "init")
    sha = g("rev-parse", "HEAD").stdout.strip()
    g("update-ref", "refs/remotes/origin/master", sha)
    g("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")


def load_prompt_workflow():
    spec = importlib.util.spec_from_file_location("_pw_under_test", PROMPT_WORKFLOW)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# DEFECT ONE -- launcher must fail closed on a missing / non-executable helper
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ISOLATED_KINDS)
def test_isolated_missing_helper_fails_closed(lab, kind):
    r = run_region(lab, kind, helpers={})
    assert r.returncode != 0, (
        f"[{kind}] absent git-env helper did not refuse the launch: rc={r.returncode}\n"
        f"stdout={r.stdout!r}"
    )
    assert "REGION_PUBLISHED" not in r.stdout, (
        f"[{kind}] provisioning region completed with empty actor-git fields: {r.stdout!r}"
    )
    assert "refus" in r.stderr.lower(), f"[{kind}] refusal was not loud: {r.stderr!r}"


@pytest.mark.parametrize("kind", ISOLATED_KINDS)
def test_isolated_non_executable_helper_fails_closed(lab, kind):
    r = run_region(lab, kind, helpers={"overnight-git-env.sh": 0o644})
    assert r.returncode != 0, (
        f"[{kind}] non-executable git-env helper did not refuse: rc={r.returncode}\n"
        f"stdout={r.stdout!r}"
    )
    assert "REGION_PUBLISHED" not in r.stdout
    assert "refus" in r.stderr.lower()


def test_in_place_missing_helper_fails_closed(lab):
    r = run_region(lab, "in_place", helpers={})
    assert r.returncode != 0, (
        "[in_place] absent marker-only helper did not refuse the launch: "
        f"rc={r.returncode}\nstdout={r.stdout!r}"
    )
    assert "REGION_PUBLISHED" not in r.stdout
    assert "refus" in r.stderr.lower()


@pytest.mark.skipif(os.geteuid() == 0,
                    reason="root bypasses read permission bits, so [[ -r ]] cannot be exercised")
def test_in_place_unreadable_helper_fails_closed(lab):
    r = run_region(lab, "in_place", helpers={"overnight-inplace-env.sh": 0o200})
    assert r.returncode != 0, (
        f"[in_place] unreadable marker-only helper did not refuse: rc={r.returncode}"
    )
    assert "REGION_PUBLISHED" not in r.stdout


def test_in_place_dangling_helper_fails_closed(lab):
    """uid-independent corruption: the helper path exists but resolves to nothing."""
    scripts = build_scripts_dir(lab, {})
    (scripts / "overnight-inplace-env.sh").symlink_to(scripts / "gone.sh")
    main_root = lab / "main"
    main_root.mkdir(exist_ok=True)
    harness = scripts / "region-harness.sh"
    harness.write_text(
        "#!/bin/bash\nset -euo pipefail\n"
        f'MAIN_ROOT="{main_root}"\nWORKTREE_PATH="{main_root}"\nISOLATION_KIND="in_place"\n'
        + extract_region()
        + '\necho "REGION_PUBLISHED helper=[$ACTOR_ENV_HELPER_PATH]"\n',
        encoding="utf-8",
    )
    harness.chmod(0o755)
    r = subprocess.run([str(harness)], capture_output=True, text=True, timeout=120)
    assert r.returncode != 0, f"[in_place] dangling helper did not refuse: {r.stdout!r}"
    assert "REGION_PUBLISHED" not in r.stdout


# --- healthy path must stay healthy (no failure made quieter, none invented) --
@pytest.mark.parametrize("kind", ISOLATED_KINDS)
def test_isolated_healthy_provisioning_still_publishes(lab, kind):
    r = run_region(lab, kind, helpers={"overnight-git-env.sh": 0o755})
    assert r.returncode == 0, f"[{kind}] healthy provisioning refused: {r.stderr!r}"
    assert "REGION_PUBLISHED" in r.stdout
    assert "overnight-git-policy-bin/git" in r.stdout, r.stdout


def test_in_place_healthy_provisioning_still_publishes(lab):
    r = run_region(lab, "in_place", helpers={"overnight-inplace-env.sh": 0o644})
    assert r.returncode == 0, f"[in_place] healthy provisioning refused: {r.stderr!r}"
    assert "REGION_PUBLISHED" in r.stdout
    assert "overnight-inplace-env.sh" in r.stdout


# --- end-to-end: the record must not be published, and nothing downstream of
# --- the region may run (dev-registry creation is the first such side effect).
def test_launch_does_not_publish_when_in_place_helper_missing(lab):
    main_root = lab / "main"
    make_repo(main_root)
    scripts = build_scripts_dir(lab, {})
    shutil.copy2(LAUNCHER, scripts / LAUNCHER.name)
    (scripts / LAUNCHER.name).chmod(0o755)
    sid = "labsession-" + uuid.uuid4().hex[:8]

    r = subprocess.run(
        [str(scripts / LAUNCHER.name), "--project-dir", str(main_root),
         "--session-id", sid, "--end-time", "8h", "--no-worktree"],
        capture_output=True, text=True, timeout=300,
        env=dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null"),
    )
    assert r.returncode != 0, f"launch succeeded with no actor-git provisioning: {r.stdout!r}"
    assert not list((main_root / ".claude").glob("overnight-state-*.json")), \
        "a session record was published without actor-git provisioning"
    # Line ordering is the proof: DEV_REGISTRY_DIR is created immediately AFTER
    # the provisioning region. Its existence means execution sailed past the
    # fail-open instead of refusing at it.
    assert not (main_root / ".claude" / "dev-registry" / sid).exists(), (
        "execution continued past the git-env provisioning region "
        f"(dev-registry/{sid} was created); the guard failed open"
    )
    assert "helper" in r.stderr.lower() and "refus" in r.stderr.lower(), r.stderr


# --------------------------------------------------------------------------- #
# DEFECT TWO -- the actor startup instruction must join source and git with &&
# --------------------------------------------------------------------------- #
def _guard_bullet() -> str:
    text = DOC.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "marker_only: false" in line and "source" in line:
            return line
    pytest.fail("ACTOR GIT-ENV GUARD worktree bullet not found in commands/dev-overnight.md")


def test_doc_startup_instruction_uses_conjunction():
    bullet = _guard_bullet()
    assert re.search(r'source\s+"<env_helper>"[^`]*&&\s*command -v git', bullet), (
        "commands/dev-overnight.md separates `source <env_helper>` from the git op "
        "with a statement separator instead of `&&`; a non-zero source does not "
        f"stop the git call.\nbullet: {bullet[:400]}"
    )


def test_generated_startup_instruction_uses_conjunction():
    mod = load_prompt_workflow()
    state = {
        "worktree_path": "/dev/shm/lab/wt",
        "main_root": "/dev/shm/lab/main",
        "isolation_kind": "registered_worktree",
        "protected_branch": "master",
        "actor_git_env": {
            "env_helper": "/dev/shm/lab/scripts/overnight-git-env.sh",
            "shim_git": "/dev/shm/lab/main/.claude/overnight-git-policy-bin/git",
        },
    }
    inst = mod._build_worktree_instruction(state)
    assert re.search(r'source "[^"]+"[^`]*&&\s*command -v git', inst), (
        "the injected actor startup instruction separates source from the git "
        f"verification with a statement separator instead of `&&`:\n{inst}"
    )


# --------------------------------------------------------------------------- #
# REQUIREMENT 3 -- pin the already-measured bad state as a regression case
# --------------------------------------------------------------------------- #
def _absent_wrapper_lab(lab: Path) -> tuple[Path, Path]:
    """Helper present and executable, wrapper SOURCES absent -> the repair inside
    the helper cannot succeed, which is the measured state."""
    scripts = build_scripts_dir(lab, {"overnight-git-env.sh": 0o755})
    shutil.rmtree(scripts / "overnight-git", ignore_errors=True)
    main_root = lab / "main"
    main_root.mkdir(exist_ok=True)
    return scripts / "overnight-git-env.sh", main_root


def test_regression_absent_wrappers_measured_bad_state(lab):
    """The measured state: sourcing returns non-zero with visible error output,
    yet the resulting shell resolves git to the system binary, carries no
    overnight actor marker, and has no shim on its search path."""
    helper, main_root = _absent_wrapper_lab(lab)
    script = (
        f'source "{helper}" --main-root "{main_root}" ; echo "SOURCE_RC=$?" ; '
        'echo "GIT=$(command -v git)" ; '
        'echo "MARKER=${CLAUDE_OVERNIGHT_ACTOR:-unset}" ; '
        'case ":$PATH:" in *overnight-git-policy-bin*) echo "SHIM=yes";; *) echo "SHIM=no";; esac'
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=120)
    assert "SOURCE_RC=1" in r.stdout, f"sourcing did not return non-zero: {r.stdout!r}"
    assert "absent or corrupt" in r.stderr, f"the failure was not visible: {r.stderr!r}"
    # This is the bad state itself -- asserted so it stays a documented, pinned
    # hazard rather than folklore.
    assert "MARKER=unset" in r.stdout and "SHIM=no" in r.stdout, r.stdout
    # The property is "a non-shim git", not one absolute path.
    resolved = re.search(r"^GIT=(.*)$", r.stdout, re.M)
    assert resolved and resolved.group(1), r.stdout
    assert "overnight-git" not in resolved.group(1), resolved.group(1)


def test_regression_conjunction_form_never_reaches_git(lab):
    """The fix's operative property: with `&&`, a failed source stops the chain
    before git is ever resolved."""
    helper, main_root = _absent_wrapper_lab(lab)
    script = (
        f'source "{helper}" --main-root "{main_root}" && '
        '{ echo "REACHED_GIT=$(command -v git)" ; }'
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=120)
    assert r.returncode != 0, "a failed source left the chain succeeding"
    assert "REACHED_GIT" not in r.stdout, (
        f"execution proceeded to git after a failed source: {r.stdout!r}"
    )


# --------------------------------------------------------------------------- #
# DEFECT TWO (b) -- the SAME fail-open in the generator's IN-PLACE branch.
#
# The earlier round closed the conjunction gap in the document and in the
# generator's ISOLATED branch, and left the in-place branch emitting a bare
# `source` with no conjunction and no chained op. In-place is the NON-ISOLATED
# DEFAULT, so the untouched branch was the one most sessions actually run.
# --------------------------------------------------------------------------- #
def _in_place_state(main_root: Path, helper: Path) -> dict:
    return {
        "worktree_path": str(main_root),
        "main_root": str(main_root),
        "isolation_kind": "in_place",
        "worktree_branch": "work",
        "protected_branch": "master",
        "actor_git_env": {"env_helper": str(helper), "marker_only": True,
                          "shim_git": None},
    }


def _source_snippets(instruction: str) -> list[str]:
    """Backticked shell snippets the instruction hands the actor to run."""
    return [s for s in re.findall(r"`([^`]*)`", instruction) if s.startswith("source ")]


def _absent_helper_lab(lab: Path) -> tuple[Path, Path]:
    """The QA-measured condition: helper path recorded in state, file not there."""
    main_root = lab / "main"
    main_root.mkdir(parents=True, exist_ok=True)
    return main_root, lab / "scripts" / "overnight-inplace-env.sh"


def test_generated_in_place_startup_instruction_uses_conjunction(lab):
    """Shape: the in-place snippet must join `source` to a following op with `&&`."""
    main_root, helper = _absent_helper_lab(lab)
    mod = load_prompt_workflow()
    inst = mod._build_worktree_instruction(_in_place_state(main_root, helper))
    snippets = _source_snippets(inst)
    assert snippets, f"the in-place branch emitted no `source` snippet at all:\n{inst}"
    for snippet in snippets:
        assert re.search(r'source\s+"[^"]+"[^`]*&&\s*\S', snippet), (
            "the injected IN-PLACE actor startup instruction emits a bare `source` "
            "with no conjunction, so a non-zero source does not stop the git call "
            f"that follows it:\nsnippet: {snippet}\nfull instruction: {inst}"
        )


def test_generated_in_place_instruction_refuses_when_helper_absent(lab):
    """Runtime: the emitted snippet, run verbatim with the helper absent, must
    exit non-zero and must never reach the op chained after the source."""
    main_root, helper = _absent_helper_lab(lab)
    assert not helper.exists(), "lab precondition: the helper must be absent"
    mod = load_prompt_workflow()
    inst = mod._build_worktree_instruction(_in_place_state(main_root, helper))
    snippets = _source_snippets(inst)
    assert snippets, f"the in-place branch emitted no `source` snippet at all:\n{inst}"
    snippet = snippets[0]
    tail = snippet.split("&&", 1)
    assert len(tail) == 2 and tail[1].strip(), (
        "the emitted in-place snippet chains NO op onto the source, so following "
        "it necessarily means running git as a separate statement -- the fail-open "
        f"itself:\nsnippet: {snippet}"
    )
    r = subprocess.run(["bash", "-c", snippet + ' ; echo "CHAIN_RC=$?"'],
                       capture_output=True, text=True, timeout=120)
    assert "CHAIN_RC=0" not in r.stdout, (
        f"a failed source left the chain succeeding: {r.stdout!r}")
    assert r.stderr.strip(), "the refusal produced no visible output"
    # nothing after the `&&` may have run
    assert "/git" not in r.stdout and "CLAUDE_OVERNIGHT_ACTOR" not in r.stdout, (
        f"execution proceeded past the failed source: {r.stdout!r}")


def test_in_place_hazard_signature_bare_source_reaches_system_git(lab):
    """The measured bad state, pinned so it stays evidence rather than folklore:
    with the helper absent, a `;`-separated form yields a non-zero source result,
    no actor marker, no shim on PATH, and git resolved to the system binary --
    at an overall exit status of zero."""
    main_root, helper = _absent_helper_lab(lab)
    script = (
        f'source "{helper}" --main-root "{main_root}" ; echo "SOURCE_RC=$?" ; '
        'echo "GIT=$(command -v git)" ; '
        'echo "MARKER=${CLAUDE_OVERNIGHT_ACTOR:-unset}" ; '
        'case ":$PATH:" in *overnight-git*) echo "SHIM=yes";; *) echo "SHIM=no";; esac'
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=120)
    assert "SOURCE_RC=0" not in r.stdout, f"sourcing an absent helper succeeded: {r.stdout!r}"
    assert "MARKER=unset" in r.stdout and "SHIM=no" in r.stdout, r.stdout
    assert r.returncode == 0, "the `;` form is dangerous precisely because it exits 0"
    resolved = re.search(r"^GIT=(.*)$", r.stdout, re.M)
    assert resolved and resolved.group(1), r.stdout
    assert "overnight-git" not in resolved.group(1), resolved.group(1)


def test_generated_in_place_instruction_keeps_marker_only_asymmetry(lab):
    """The asymmetry the conjunction fix must not disturb: in-place exports the
    actor marker and deliberately does NOT set the main-root variable, because
    setting it arms the policy shim, which in this mode denies every git op."""
    main_root, helper = _absent_helper_lab(lab)
    mod = load_prompt_workflow()
    inst = mod._build_worktree_instruction(_in_place_state(main_root, helper))
    assert "CLAUDE_OVERNIGHT_MAIN_ROOT" in inst, inst
    assert re.search(r"(does NOT|do NOT) set CLAUDE_OVERNIGHT_MAIN_ROOT", inst), (
        "the in-place instruction stopped stating that the main-root variable is "
        f"deliberately unset:\n{inst}")
    assert not re.search(r"export\s+CLAUDE_OVERNIGHT_MAIN_ROOT", inst), (
        f"the in-place instruction now tells the actor to arm the policy shim:\n{inst}")
    for snippet in _source_snippets(inst):
        assert "--worktree" not in snippet, (
            f"in-place mode must not pass a worktree to the helper: {snippet}")


def test_every_generated_source_instruction_uses_conjunction():
    """Sibling sweep: EVERY isolation mode the generator can emit a `source` for
    must chain it with `&&`. This lane already missed one branch by inspecting a
    single one; this fails on the next sibling instead of the next incident."""
    mod = load_prompt_workflow()
    bases = {
        "in_place": {"isolation_kind": "in_place", "worktree_path": "/dev/shm/lab/main"},
        "registered_worktree": {"isolation_kind": "registered_worktree",
                                "worktree_path": "/dev/shm/lab/wt"},
        "fresh_clone_checkout": {"isolation_kind": "fresh_clone_checkout",
                                 "worktree_path": "/dev/shm/lab/wt"},
    }
    for kind, extra in bases.items():
        state = {
            "main_root": "/dev/shm/lab/main", "worktree_branch": "work",
            "protected_branch": "master",
            "actor_git_env": {
                "env_helper": "/dev/shm/lab/scripts/helper.sh",
                "shim_git": "/dev/shm/lab/main/.claude/overnight-git-policy-bin/git",
            },
            **extra,
        }
        inst = mod._build_worktree_instruction(state)
        snippets = _source_snippets(inst)
        assert snippets, f"[{kind}] emitted no `source` snippet: {inst}"
        for snippet in snippets:
            assert re.search(r'source\s+"[^"]+"[^`]*&&\s*\S', snippet), (
                f"[{kind}] emits a `source` with no conjunction: {snippet}")


def test_source_instructions_live_only_in_the_worktree_instruction_builder():
    """...and a NEW `source` emission added anywhere else in the generator trips
    this, because the sweep above can only cover branches it knows to call."""
    mod = load_prompt_workflow()
    builder = inspect.getsource(mod._build_worktree_instruction)
    stray = [
        f"{i}: {ln.strip()}"
        for i, ln in enumerate(PROMPT_WORKFLOW.read_text(encoding="utf-8").splitlines(), 1)
        if 'source "' in ln and ln.strip() not in
        {line.strip() for line in builder.splitlines()}
    ]
    assert not stray, (
        "a shell `source` instruction is emitted outside _build_worktree_instruction, "
        "where the conjunction sweep above cannot see it:\n" + "\n".join(stray))


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_regression_absent_wrappers_never_published(lab, kind):
    """...and the launcher must never publish that state, in any isolation mode."""
    helpers = {"overnight-inplace-env.sh": 0o644} if kind == "in_place" \
        else {"overnight-git-env.sh": 0o755}
    r = run_region(lab, kind, helpers=helpers, with_wrapper_sources=False)
    if kind == "in_place":
        # marker-only mode installs no wrappers, so absent sources are not a
        # failure there; it must still publish a non-empty helper path.
        assert r.returncode == 0 and "helper=[]" not in r.stdout, r.stdout
        return
    assert r.returncode != 0, f"[{kind}] unprovisioned wrappers were published: {r.stdout!r}"
    assert "REGION_PUBLISHED" not in r.stdout
