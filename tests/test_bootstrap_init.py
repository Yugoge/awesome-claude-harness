"""scripts/bootstrap (init) on a fresh clone and on a populated home.

Every case runs in its own temporary clone of this repository, synced to the
working tree (tracked and untracked-but-not-ignored files) and committed there,
so the scripts under test are the ones in the working tree. Nothing touches
this repository or a real home:

- HOME and CLAUDE_CONFIG_DIR point at temporary directories (the
  protected-runtime file lands under the temporary HOME); CLAUDE_HOME,
  CLAUDE_PROTECTED_RUNTIME_FILE and every GIT_* variable are dropped, and the
  system git config is ignored;
- the clone's clean settings.json names a temporary TMPDIR, so the TMPDIR step
  creates a directory inside the test's own temporary tree;
- <clone>/venv is a stub whose bin/python execs this interpreter, which already
  imports pytest, jsonschema and yaml (imported below), so bootstrap reuses it
  and never installs anything;
- bootstrap runs with --no-doctor (doctor is exercised separately for its
  missing-render-settings failure).
"""

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import jsonschema  # noqa: F401  (the stub venv forwards to this interpreter)
import pytest
import yaml  # noqa: F401

REPO = Path(__file__).resolve().parent.parent
HOOK_MARKER = "# claude-harness pre-commit (installed by scripts/bootstrap)"
QUESTION = 'Enable module "paseo"?'


def _canonical(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _run(cmd, env, cwd=None, stdin="", check=True):
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env,
                       cwd=cwd, timeout=300, check=False)
    if check and r.returncode != 0:
        raise AssertionError(f"{cmd!r} exited {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


class Home:
    """A temporary clone plus the hermetic environment bootstrap runs in."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        home, config = tmp / "home", tmp / "config"
        home.mkdir()
        config.mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GIT_") and k not in (
                   "CLAUDE_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROTECTED_RUNTIME_FILE",
                   "PYTHONPATH")}
        env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(config), GIT_CONFIG_NOSYSTEM="1",
                   PYTHONDONTWRITEBYTECODE="1",
                   GIT_AUTHOR_NAME="bootstrap-test", GIT_AUTHOR_EMAIL="bootstrap-test@example.invalid",
                   GIT_COMMITTER_NAME="bootstrap-test",
                   GIT_COMMITTER_EMAIL="bootstrap-test@example.invalid")
        self.env = env
        self.protected_runtime = home / ".config" / "claude" / "protected-runtime.json"
        self.tmp_root = tmp / "scratch-tmp"

        clone = tmp / "harness"
        _run(["git", "clone", "-q", "--no-hardlinks", str(REPO), str(clone)], env)
        listed = _run(["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others",
                       "--exclude-standard"], env).stdout
        for rel in sorted({p for p in listed.split("\0") if p}):
            src, dst = REPO / rel, clone / rel
            if not os.path.lexists(src):  # deleted in the working tree
                if os.path.lexists(dst):
                    dst.unlink()
                continue
            if os.path.lexists(dst) and not src.is_symlink() and not dst.is_symlink() \
                    and src.read_bytes() == dst.read_bytes() \
                    and stat.S_IMODE(src.stat().st_mode) == stat.S_IMODE(dst.stat().st_mode):
                continue
            if os.path.lexists(dst) or dst.is_symlink():
                dst.unlink()
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_symlink():
                os.symlink(os.readlink(src), dst)
            else:
                shutil.copy2(src, dst)
        settings = json.loads((clone / "settings.json").read_text(encoding="utf-8"))
        assert "TMPDIR" in settings.get("env", {}), "the clean form names a TMPDIR"
        for key in ("TMPDIR", "CLAUDE_CODE_TMPDIR"):
            if key in settings["env"]:
                settings["env"][key] = str(self.tmp_root)
        (clone / "settings.json").write_text(_canonical(settings), encoding="utf-8")
        _run(["git", "-C", str(clone), "add", "-A"], env)
        _run(["git", "-C", str(clone), "-c", "commit.gpgsign=false", "commit", "-q",
              "-m", "test: working tree, scratch TMPDIR"], env)

        venv_bin = clone / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        stub = venv_bin / "python"
        stub.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
        stub.chmod(0o755)

        self.clone = clone
        self.h = str(clone.resolve())
        self.overlay = clone / "settings.machine.json"
        self.literals = clone / "private-literals.txt"
        self.pre_commit = clone / ".git" / "hooks" / "pre-commit"
        self.hook_src = clone / "hooks" / "git-hooks" / "pre-commit"

    def bootstrap(self, *args, stdin="", check=True):
        return _run(["bash", str(self.clone / "scripts" / "bootstrap"), *args], self.env,
                    cwd=str(self.tmp), stdin=stdin, check=check)

    def settings(self):
        return json.loads((self.clone / "settings.json").read_text(encoding="utf-8"))

    def git(self, *args, check=True):
        return _run(["git", "-C", str(self.clone), *args], self.env, check=check)

    def required_keys(self):
        code = ("import json, sys; sys.path.insert(0, sys.argv[1]); import config; "
                "print(json.dumps(list(config.REQUIRED_KEYS)))")
        out = _run([sys.executable, "-B", "-I", "-c", code,
                    str(self.clone / "hooks" / "lib" / "runtime_guard")], self.env).stdout
        return json.loads(out)

    def snapshot(self):
        paths = [self.overlay, self.literals, self.protected_runtime, self.clone / "settings.json",
                 self.clone / ".git" / "config", self.pre_commit, self.clone / "venv" / "bin" / "python"]
        return {str(p): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in paths}


@pytest.fixture
def home(tmp_path):
    return Home(tmp_path)


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_fresh_clone_init_creates_the_home_and_reruns_identically(home):
    first = home.bootstrap("--yes", "--no-doctor")
    assert first.stdout.rstrip().splitlines()[-1].startswith("bootstrap: SUCCESS")
    assert QUESTION not in first.stdout, "--yes never asks"

    assert home.overlay.read_text(encoding="utf-8") == _canonical(
        {"modules": {"paseo": False}, "env": {"CLAUDE_HOME": home.h}})
    assert _mode(home.overlay) == 0o600
    assert home.literals.read_bytes() == b"" and _mode(home.literals) == 0o600
    runtime = json.loads(home.protected_runtime.read_text(encoding="utf-8"))
    keys = home.required_keys()
    assert runtime == dict({"schema_version": 1}, **{k: [] for k in keys}) and len(keys) == 10
    assert (home.clone / "logs").is_dir()
    assert home.tmp_root.is_dir() and _mode(home.tmp_root) == 0o1777

    for key, value in (("clean", "python3 scripts/install/render-settings clean"),
                       ("smudge", "python3 scripts/install/render-settings smudge"),
                       ("required", "true")):
        got = home.git("config", "--local", "--get", f"filter.claude-settings.{key}").stdout.strip()
        assert got == value
    assert home.pre_commit.read_bytes() == home.hook_src.read_bytes()
    assert _mode(home.pre_commit) == 0o755
    assert not home.pre_commit.with_name("pre-commit.local").exists()

    # The machine form carries the overlay; through the filter git still sees the
    # clean form (content comparison: a size change alone can leave the entry
    # stat-dirty in `git status` until it is re-staged).
    assert home.settings()["env"]["CLAUDE_HOME"] == home.h
    assert home.git("diff", "--name-only", "HEAD").stdout == ""
    assert home.git("diff", "--cached", "--name-only").stdout == ""

    before = home.snapshot()
    second = home.bootstrap("--yes", "--no-doctor")
    third = home.bootstrap("--yes", "--no-doctor")
    assert second.stdout == third.stdout
    assert home.snapshot() == before
    assert "settings.machine.json exists" in second.stdout


def test_populated_home_keeps_overlay_literals_and_runtime_file(home):
    overlay = '{"modules": {"paseo": false}, "env": {"CLAUDE_HOME": "%s", "DEMO_SETTING": "demo"}}\n' % home.h
    home.overlay.write_text(overlay, encoding="utf-8")
    home.overlay.chmod(0o640)
    home.literals.write_text("acct-test-123\n", encoding="utf-8")
    home.protected_runtime.parent.mkdir(parents=True)
    runtime = dict({"schema_version": 1}, **{k: [] for k in home.required_keys()})
    runtime["protected_services"] = ["demo-daemon"]
    home.protected_runtime.write_text(json.dumps(runtime) + "\n", encoding="utf-8")
    pinned = {p: (p.read_bytes(), _mode(p)) for p in (home.overlay, home.literals, home.protected_runtime)}

    runs = [home.bootstrap("--with", "paseo", "--no-doctor") for _ in range(3)]
    for run in runs:
        assert QUESTION not in run.stdout, "an existing overlay is never asked about"
        assert "existing overlay wins" in run.stdout
    assert runs[1].stdout == runs[2].stdout
    assert {p: (p.read_bytes(), _mode(p)) for p in pinned} == pinned

    rendered = home.settings()
    assert rendered["env"]["DEMO_SETTING"] == "demo"
    assert "mcp__paseo__*" not in rendered["permissions"]["allow"], "the overlay keeps paseo off"


def test_module_question_reads_one_line_and_defaults_to_no(home):
    # One clone, the overlay removed before each run. Every "off" answer comes
    # first: turning the module off after it was on would leave its entries in
    # the working settings.json, which render refuses to drop without --force.
    cases = [("", False), ("n\n", False), ("No\n", False), ("\n", False), ("maybe\n", False),
             ("y\n", True), ("Yes\n", True), ("maybe\n  YES \n", True), ("yes", True)]
    for answers, enabled in cases:
        home.overlay.unlink(missing_ok=True)
        result = home.bootstrap("--no-doctor", stdin=answers)
        assert QUESTION in result.stdout and "[y/N]" in result.stdout, answers
        assert ("please answer" in result.stdout) == answers.startswith("maybe"), answers
        overlay = json.loads(home.overlay.read_text(encoding="utf-8"))
        assert overlay["modules"] == {"paseo": enabled}, answers
        assert ("mcp__paseo__*" in home.settings()["permissions"]["allow"]) is enabled, answers


def test_foreign_pre_commit_is_kept_as_local_and_chained(home):
    foreign = "#!/bin/sh\necho foreign hook\n"
    home.pre_commit.write_text(foreign)
    home.pre_commit.chmod(0o755)
    home.bootstrap("--yes", "--no-doctor")
    local = home.pre_commit.with_name("pre-commit.local")
    assert local.read_text() == foreign
    assert home.pre_commit.read_bytes() == home.hook_src.read_bytes()
    assert HOOK_MARKER in home.pre_commit.read_text().splitlines()

    home.bootstrap("--yes", "--no-doctor")
    assert local.read_text() == foreign
    assert sorted(p.name for p in home.pre_commit.parent.glob("pre-commit*")
                  if not p.name.endswith(".sample")) == ["pre-commit", "pre-commit.local"]


def test_bad_arguments_are_refused_before_any_change(home):
    for args, message in (
            (["--with", "nosuch"], "unknown module 'nosuch'"),
            (["--with", "paseo", "--without", "paseo"], "both --with and --without"),
            (["--settings-file", "settings.json"], "--settings-file needs --migrate-from"),
            (["--bogus"], "unknown argument '--bogus'")):
        result = home.bootstrap(*args, check=False)
        assert result.returncode == 1 and message in result.stderr, args
    assert not home.overlay.exists() and not home.literals.exists()
    assert not home.protected_runtime.exists()


def test_help_names_every_flag(home):
    out = home.bootstrap("--help").stdout
    for flag in ("--yes", "--with", "--without", "--migrate-from", "--settings-file",
                 "--force", "--no-doctor"):
        assert flag in out
    assert not home.overlay.exists()


def test_doctor_fails_clearly_without_render_settings(home):
    (home.clone / "scripts" / "install" / "render-settings").unlink()
    result = _run(["bash", str(home.clone / "scripts" / "doctor")], home.env, check=False)
    assert result.returncode == 1
    assert "scripts/install/render-settings is missing" in result.stderr
