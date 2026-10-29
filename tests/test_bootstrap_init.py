"""scripts/bootstrap (init) on a fresh clone and on a populated home.

Every case runs in its own temporary clone of this repository, synced to the
working tree (tracked and untracked-but-not-ignored files) and committed there,
so the scripts under test are the ones in the working tree. Two exceptions keep
the result the same on a fresh clone, on CI and on a home that has run init:
a file git filters (settings.json) comes from the index, its tracked clean form,
because init leaves its working copy in the machine form; and the untracked
files init creates (OWNER_FILES) are never copied, whatever the ignore rules.
Nothing touches this repository or a real home:

- HOME and CLAUDE_CONFIG_DIR point at temporary directories (the
  protected-runtime file and the global git config land under the temporary
  HOME); CLAUDE_HOME, CLAUDE_PROTECTED_RUNTIME_FILE, XDG_CONFIG_HOME and every
  GIT_* variable are dropped, and the system git config is ignored (one case
  points GIT_CONFIG_SYSTEM at a temporary file instead);
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
# What init creates in a harness home beside the machine form of settings.json; the
# record of what render applied lives in the git dir, which a clone never copies.
OWNER_FILES = ("settings.machine.json", "private-literals.txt", "venv", "logs")
RECORD = "claude-settings.applied"


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
                   "PYTHONPATH", "XDG_CONFIG_HOME")}
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
        git = ["git", "-C", str(REPO)]
        index = {}  # tracked path -> (mode, blob id), as staged in this repository
        for entry in _run([*git, "ls-files", "-z", "--stage"], env).stdout.split("\0"):
            if entry:
                meta, rel = entry.split("\t", 1)
                index[rel] = tuple(meta.split()[:2])
        attrs = _run([*git, "check-attr", "-z", "--stdin", "filter"], env,
                     stdin="".join(p + "\0" for p in index)).stdout.split("\0")
        filtered = {attrs[i] for i in range(0, len(attrs) - 2, 3)
                    if attrs[i + 2] not in ("unspecified", "unset")
                    and index[attrs[i]][0] in ("100644", "100755")}
        others = _run([*git, "ls-files", "-z", "--others", "--exclude-standard"], env).stdout
        listed = set(index) | {p for p in others.split("\0")
                               if p and p.split("/", 1)[0] not in OWNER_FILES}
        for rel in sorted(filtered):  # never the working copy: it can be the machine form
            mode, oid, dst = *index[rel], clone / rel
            if os.path.lexists(dst):
                dst.unlink()
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(subprocess.run([*git, "cat-file", "blob", oid], capture_output=True,
                                           env=env, timeout=300, check=True).stdout)
            dst.chmod(0o755 if mode == "100755" else 0o644)
        for rel in sorted(listed - filtered):
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
        assert "settings.json" in filtered, "settings.json comes from its tracked clean form"
        assert not [p for p in (*OWNER_FILES, f".git/{RECORD}") if os.path.lexists(clone / p)], \
            "a test clone never carries what init created in this repository"
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
        return {str(p): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) if p.exists() else None
                for p in paths}

    def commit_readme(self):
        """Commit one tracked change in the clone, through whatever hooks git runs."""
        with (self.clone / "README.md").open("a", encoding="utf-8") as fh:
            fh.write("\ntest line\n")
        self.git("add", "README.md")
        return self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "test: hooked commit",
                        check=False)


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


STAND_IN = "acct-test-123"  # a stand-in personal value; nothing else in the run contains it


@pytest.mark.parametrize("case", ["created", "exists", "relative", "fails"])
def test_init_output_names_overlay_keys_never_their_values(home, case):
    # The overlay sets env.TMPDIR and other values to stand-ins: init still acts on them,
    # but its stdout and stderr name the key (env.TMPDIR) and never print a value.
    personal = home.tmp / STAND_IN
    tmp_root = f"{STAND_IN}/tmp-root" if case == "relative" else str(personal / "tmp-root")
    if case == "exists":
        (personal / "tmp-root").mkdir(parents=True)
        existing = _mode(personal / "tmp-root")
    elif case == "fails":
        personal.write_text("")  # a regular file where the TMPDIR's parent should be
    sync = str(personal / "bin" / "sync.sh")
    home.overlay.write_text(_canonical({
        "modules": {"paseo": False},
        "env": {"CLAUDE_HOME": home.h, "TMPDIR": tmp_root, "CLAUDE_CODE_TMPDIR": tmp_root,
                "DEMO_SYNC": sync, "DEMO_ACCOUNT": STAND_IN},
        "permissions": {"allow": [f"Bash({sync}:*)", f"Read({personal}/notes/**)"]}}),
        encoding="utf-8")

    result = home.bootstrap("--yes", "--no-doctor", check=False)
    out = result.stdout + result.stderr
    assert home.settings()["env"]["TMPDIR"] == tmp_root, "the overlay's values are rendered"
    assert f"Bash({sync}:*)" in home.settings()["permissions"]["allow"]
    assert STAND_IN not in out and "sync.sh" not in out, out
    expected = {
        "created": ("created the env.TMPDIR directory (mode 1777)", result.stdout, 0),
        "exists": ("the env.TMPDIR directory exists", result.stdout, 0),
        "relative": ("env.TMPDIR in settings.json is not an absolute path — not created; "
                     "set an absolute env.TMPDIR in settings.machine.json", result.stdout, 0),
        "fails": ("could not create the env.TMPDIR directory (Not a directory); create it "
                  "(mode 1777; its path is env.TMPDIR in settings.json) or set another "
                  "env.TMPDIR in settings.machine.json.", result.stderr, 1)}
    message, stream, rc = expected[case]
    assert f"bootstrap: {message}" in stream.splitlines(), out
    assert result.returncode == rc, out
    if case in ("created", "exists"):
        assert _mode(personal / "tmp-root") == (0o1777 if case == "created" else existing)
        assert "bootstrap: created protected-runtime file (~/.config/claude/protected-runtime.json, " \
               "empty lists)" in result.stdout.splitlines()
    elif case == "relative":
        assert not (home.tmp / STAND_IN).exists() and not (home.clone / STAND_IN).exists()


def test_a_settings_file_the_load_finds_unusable_stops_init_with_its_reason(home):
    # init reads settings.json through the one load of a settings file (hooks/lib/claude_home.py
    # load_settings): made unparseable at the same size, the render (step 3) refuses with the
    # load's reason, and so does step 4's env.TMPDIR read; the file stays as it is.
    assert home.bootstrap("--yes", "--no-doctor").returncode == 0
    settings = home.clone / "settings.json"
    data = b"{" * settings.stat().st_size
    settings.write_bytes(data)
    for step, line in (("3", "render-settings: render refused: settings.json: not valid JSON ("),
                       ("4", f"bootstrap: env.TMPDIR not read: {home.h}/settings.json: not valid JSON (")):
        result = home.bootstrap("--steps", step, check=False)
        assert result.returncode == 1, result.stdout + result.stderr
        assert line in result.stdout + result.stderr, result.stdout + result.stderr
    assert settings.read_bytes() == data


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


def test_the_overlay_writer_init_seeds_through_never_clobbers(home):
    # Step 2 writes a new overlay through render-settings' one writer (migrate and the landing
    # use it too); one created meanwhile is kept byte for byte.
    home.overlay.write_text('{"modules": {}}\n', encoding="utf-8")
    result = _run([sys.executable, str(home.clone / "scripts" / "install" / "render-settings"),
                   "seed", "--claude-home", home.h, "paseo=on"], home.env, check=False)
    assert result.returncode == 1 and "seed refused" in result.stderr
    assert home.overlay.read_text(encoding="utf-8") == '{"modules": {}}\n'


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


def _own_hook(hooks_dir: Path, log: Path, name: str) -> str:
    """A user's own pre-commit hook in hooks_dir that records each run in log."""
    hooks_dir.mkdir(parents=True, exist_ok=True)
    text = f"#!/bin/sh\necho {name} >> {shlex.quote(str(log))}\n"
    hook = hooks_dir / "pre-commit"
    hook.write_text(text)
    hook.chmod(0o755)
    return text


def _tree(d: Path):
    return {p.name: (p.read_bytes(), _mode(p)) for p in sorted(d.iterdir())}


def _toy_commit(home, toy: Path):
    """A commit in a repository that has nothing to do with the harness."""
    if not toy.exists():
        _run(["git", "init", "-q", str(toy)], home.env)
    n = len(list(toy.glob("*.txt")))
    (toy / f"f{n}.txt").write_text(f"{n}\n")
    _run(["git", "-C", str(toy), "add", "-A"], home.env)
    return _run(["git", "-C", str(toy), "-c", "commit.gpgsign=false", "commit", "-q",
                 "-m", f"toy {n}"], home.env, check=False)


def test_global_hooks_path_is_left_untouched_and_init_fails_until_the_repo_has_its_own(home):
    shared, log = home.tmp / "home" / ".githooks", home.tmp / "own-hook.log"
    own = _own_hook(shared, log, "own-hook")
    _run(["git", "config", "--global", "core.hooksPath", str(shared)], home.env)
    scope = home.git("config", "--show-scope", "--get", "core.hooksPath").stdout.split("\t")[0]
    assert scope == "global", "the scratch HOME's global config names the hooks dir"
    pinned = _tree(shared)
    fix = f"git -C {home.h} config --local core.hooksPath {home.h}/.git/hooks"

    runs = [home.bootstrap("--yes", "--no-doctor", check=False)]
    pinned_home = home.snapshot()  # overlay, literals, runtime file, settings, git config
    runs += [home.bootstrap("--yes", "--no-doctor", check=False) for _ in range(2)]
    assert home.snapshot() == pinned_home, "a re-run changes nothing"
    for run in runs:
        assert run.returncode == 1, run.stdout + run.stderr
        assert "SUCCESS" not in run.stdout
        assert "pre-commit hook is NOT installed" in run.stderr
        assert "global git config (file:" in run.stderr
        assert fix in [line.strip() for line in run.stderr.splitlines()]
        assert _tree(shared) == pinned, "nothing is written to the global hooks dir"
    assert (runs[1].stdout, runs[1].stderr) == (runs[2].stdout, runs[2].stderr)
    assert not home.pre_commit.exists()

    # Every other step ran: overlay, filter, render, literal list, protected-runtime file.
    assert json.loads(home.overlay.read_text(encoding="utf-8"))["modules"] == {"paseo": False}
    assert home.git("config", "--local", "--get", "filter.claude-settings.required").stdout.strip() == "true"
    assert home.settings()["env"]["CLAUDE_HOME"] == home.h
    assert home.literals.exists() and home.protected_runtime.exists()

    # An unrelated repository still runs the user's own hook, and its commit lands.
    toy = home.tmp / "toy"
    assert _toy_commit(home, toy).returncode == 0
    assert log.read_text() == "own-hook\n"

    # Follow the message: copy the own hook into the repository's hooks dir, run the
    # printed command, re-run init. The harness hook is installed there and chains
    # to the displaced own hook; the global hooks dir is still untouched.
    shutil.copy2(shared / "pre-commit", home.pre_commit)
    _run(shlex.split(fix), home.env)
    done = home.bootstrap("--yes", "--no-doctor")
    assert done.stdout.rstrip().splitlines()[-1].startswith("bootstrap: SUCCESS")
    assert home.pre_commit.read_bytes() == home.hook_src.read_bytes()
    assert home.pre_commit.with_name("pre-commit.local").read_text() == own
    assert _tree(shared) == pinned
    log.unlink()
    committed = home.commit_readme()
    assert committed.returncode == 0, committed.stderr
    assert log.read_text() == "own-hook\n", "the harness hook chained to pre-commit.local"
    assert _toy_commit(home, toy).returncode == 0
    assert log.read_text() == "own-hook\nown-hook\n"


@pytest.mark.parametrize("scope", ["system", "command"])
def test_system_or_command_line_hooks_path_is_refused(home, scope):
    shared = home.tmp / "shared-hooks"
    shared.mkdir()
    if scope == "system":  # a temporary system config file, written directly
        system = home.tmp / "system-gitconfig"
        system.write_text(f"[core]\n\thooksPath = {shared}\n")
        del home.env["GIT_CONFIG_NOSYSTEM"]
        home.env["GIT_CONFIG_SYSTEM"] = str(system)
    else:
        home.env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.hooksPath",
                        GIT_CONFIG_VALUE_0=str(shared))
    result = home.bootstrap("--yes", "--no-doctor", check=False)
    assert result.returncode == 1 and f"{scope} git config (" in result.stderr
    assert list(shared.iterdir()) == [] and not home.pre_commit.exists()


def test_local_hooks_path_is_used_and_a_foreign_hook_there_is_chained(home):
    # A global hooks path is set too: the repository's local one wins, and the
    # global dir is never touched.
    shared, log = home.tmp / "home" / ".githooks", home.tmp / "hooks.log"
    _own_hook(shared, log, "global-hook")
    _run(["git", "config", "--global", "core.hooksPath", str(shared)], home.env)
    pinned = _tree(shared)
    repo_hooks = home.tmp / "repo-hooks"  # outside the git common dir
    foreign = _own_hook(repo_hooks, log, "foreign-hook")
    home.git("config", "--local", "core.hooksPath", str(repo_hooks))

    runs = [home.bootstrap("--yes", "--no-doctor") for _ in range(3)]
    assert "kept the existing pre-commit hook as pre-commit.local" in runs[0].stdout
    assert runs[1].stdout == runs[2].stdout
    assert f"pre-commit hook up to date ({repo_hooks}/pre-commit)" in runs[2].stdout
    assert (repo_hooks / "pre-commit").read_bytes() == home.hook_src.read_bytes()
    assert (repo_hooks / "pre-commit.local").read_text() == foreign
    assert sorted(p.name for p in repo_hooks.iterdir()) == ["pre-commit", "pre-commit.local"]
    assert not home.pre_commit.exists() and _tree(shared) == pinned

    committed = home.commit_readme()
    assert committed.returncode == 0, committed.stderr
    assert log.read_text() == "foreign-hook\n"


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
