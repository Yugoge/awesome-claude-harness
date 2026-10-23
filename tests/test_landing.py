"""P7b: the landing of P7 on a harness home that ran pre-P7 code (scripts/install/land and
render-settings land, run from hooks/auto-commit.sh), migrate's push exclusion and the settings
check line, and the pre-landing env rule (hooks/lib/claude_home.py settings_env, the checkpoint push,
the bash-safety knobs, subagent_restart's accounts root).

Every harness home is a small temporary git repository: a pre-P7 commit (no settings filter,
personal stand-in values in settings.json and in the code defaults) followed by a P7 commit (the
filter declared, the clean form, the scripts under test copied from this checkout). HOME,
CLAUDE_CONFIG_DIR and the global git config point into the test's temporary directory, and no
Claude Code variable is inherited. All values are stand-ins (acct-test-*, demo-*, /opt/demo/*).
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.test_settings_filter import (CODE_NEW, CODE_OLD, canon, clean_form, hook,
                                        previous_settings)

REPO = Path(__file__).resolve().parent.parent
HARNESS_FILES = ("scripts/install/land", "scripts/install/render-settings", "scripts/bootstrap",
                 "hooks/lib/claude_home.sh", "hooks/lib/claude_home.py",
                 "hooks/lib/runtime_guard/config.py", "hooks/lib/runtime_guard/shell_lex.py",
                 "hooks/lib/runtime_guard/pathmatch.py", "hooks/git-hooks/pre-commit",
                 "hooks/git-hooks/post-commit-auto-push", "hooks/git-hooks/README.md")
LEGACY_HOOK = '#!/bin/bash\n# post-commit-auto-push (pre-P0)\nif [ "${GIT_AUTO_PUSH:-1}" = "0" ]; then exit 0; fi\n' \
              'git push origin HEAD:refs/backups/x >/dev/null 2>&1 &\n'
LFS_LEGACY_HOOK = '#!/bin/bash\n# post-commit - Combined hook: Git LFS + Auto-Push\n' \
                  'command -v git-lfs >/dev/null 2>&1 && git lfs post-commit "$@"\n' + LEGACY_HOOK
MARKERS_OLD = ("#!/bin/bash\nWS_MARKER='/opt/demo/ws-marker'\nHARD_MARKERS=(\n"
               "  'git@example.invalid:demo-owner'   # the remote's SSH form\n"
               "  '/home/demo-user'\n)\nPARAM_MARKERS=(\n  'demo-private-proj'\n  'xyz'\n"
               "  'C.UTF-8'   # a shipped default\n  \"$HOME/never\"\n)\n")
STAND_INS = ("acct-a", "acct-b", "acct-test-123", "demo-", "/opt/demo", "demo@example.invalid",
             "/home/demo-user", "xyz")


def run(cmd, env, cwd=None, check=True, **kw):
    proc = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=300, **kw)
    if check:
        assert proc.returncode == 0, "%r -> %d\n%s\n%s" % (cmd, proc.returncode, proc.stdout,
                                                         proc.stderr)
    return proc


def git(env, home, *args, check=True):
    return run(["git", "-C", str(home), *args], env, check=check)


@pytest.fixture
def env(tmp_path):
    """Scratch HOME, CLAUDE_CONFIG_DIR and global git config; no inherited git, harness or
    Claude Code variable."""
    user, config = tmp_path / "userhome", tmp_path / "config-dir"
    user.mkdir()
    config.mkdir()
    (user / ".gitconfig").write_text("")
    drop = ("CLAUDE_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROTECTED_RUNTIME_FILE", "CLAUDECODE",
            "CLAUDE_PROJECT_DIR", "CLAUDE_STATE_DIR", "PYTHONPATH", "XDG_CONFIG_HOME") + \
        tuple(k for k in os.environ if k.startswith("CLAUDE_HARD") or k.startswith("CLAUDE_DEV"))
    out = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in drop}
    out.update(HOME=str(user), CLAUDE_CONFIG_DIR=str(config), GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=str(user / ".gitconfig"), PYTHONDONTWRITEBYTECODE="1",
               CLAUDE_PROTECTED_RUNTIME_FILE=str(tmp_path / "protected-runtime.json"),
               CLAUDE_STATE_DIR=str(tmp_path / "state"),
               GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid")
    (tmp_path / "state").mkdir()
    return out


def write(path, text, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)


def clean_settings(tmp_path):
    doc = clean_form()
    doc["env"]["TMPDIR"] = str(tmp_path / "scratch-tmp")
    return doc


def make_home(tmp_path, env, prev=None, name="harness"):
    """A harness home whose HEAD reflog holds a pre-P7 commit (returned as rev) and whose HEAD is
    the P7 tree with the scripts under test. Returns (home, rev)."""
    home = tmp_path / name
    git(env, tmp_path, "init", "-q", "-b", "master", str(home))
    write(home / ".gitignore", "/settings.machine.json\n/private-literals.txt\nlogs/\n")
    for rel, text in CODE_OLD.items():
        write(home / rel, text)
    write(home / "scripts/check-public-core.sh", MARKERS_OLD)
    write(home / "policies/README.md", "stand-in\n")
    write(home / "notes.txt", "a tracked note\n")
    write(home / "a*b.txt", "a tracked file with a glob character in its name\n")
    write(home / "settings.json", canon(prev or previous_settings()).decode())
    git(env, home, "add", "-A")
    git(env, home, "commit", "-q", "-m", "pre-P7")
    rev = git(env, home, "rev-parse", "HEAD").stdout.strip()
    for rel, text in CODE_NEW.items():
        write(home / rel, text)
    for rel in HARNESS_FILES:
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, home / rel)
    for rel in ("hooks/session-info.sh", "hooks/userprompt-demo.py", "hooks/stop-demo.py",
                "hooks/pretool-runcode-watchdog.py", "hooks/posttool-runcode-watchdog.py",
                "hooks/userprompt-usage-snapshot.py"):
        write(home / rel, "# stub\n")
    write(home / ".gitattributes", "/settings.json filter=claude-settings\n")
    write(home / "settings.json", canon(clean_settings(tmp_path)).decode())
    git(env, home, "add", "-A")
    git(env, home, "commit", "-q", "-m", "P7")
    return Path(os.path.realpath(home)), rev


def land(env, home, *args):
    proc = run(["bash", str(home / "scripts/install/land"), *args], env, cwd=str(home))
    assert proc.returncode == 0
    return proc.stdout


def overlay(home):
    return json.loads((home / "settings.machine.json").read_text(encoding="utf-8"))


def landing_log(home):
    path = home / "logs" / "landing.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def assert_landed(env, home):
    assert land(env, home, "--state").strip() == "landed"
    assert stat.S_IMODE((home / "settings.machine.json").stat().st_mode) == 0o600
    assert git(env, home, "config", "--local", "--get", "filter.claude-settings.clean").stdout
    record = git(env, home, "rev-parse", "--git-path", "claude-settings.applied").stdout.strip()
    assert (home / record).is_file()
    hooks = home / git(env, home, "rev-parse", "--git-path", "hooks").stdout.strip()
    assert (hooks / "pre-commit").read_bytes() == (home / "hooks/git-hooks/pre-commit").read_bytes()
    assert git(env, home, "status", "--porcelain").stdout == ""
    rendered = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    assert rendered["env"].get("CLAUDE_HOME") == str(home)


# --------------------------------------------------------------------------- R3: migrate, check

def test_migrate_never_writes_git_auto_push_one(tmp_path, env):
    prev = previous_settings()
    prev["env"]["GIT_AUTO_PUSH"] = "1"
    home, rev = make_home(tmp_path, env, prev)
    rs = str(home / "scripts/install/render-settings")
    proc = run([sys.executable, rs, "migrate", "--from", rev], env, cwd=str(home))
    assert "GIT_AUTO_PUSH" not in overlay(home)["env"]
    assert "not migrated: GIT_AUTO_PUSH" in proc.stdout and '"1"' not in proc.stdout
    (home / "settings.machine.json").unlink()  # the same through --settings-file
    (tmp_path / "prev.json").write_bytes(canon(prev))
    run([sys.executable, rs, "migrate", "--from", rev, "--settings-file",
         str(tmp_path / "prev.json")], env, cwd=str(home))
    assert "GIT_AUTO_PUSH" not in overlay(home)["env"]
    (home / "settings.machine.json").unlink()  # "0" is not "1": migrated like any other value
    prev["env"]["GIT_AUTO_PUSH"] = "0"
    prev["env"]["LANG"] = "C"
    (tmp_path / "prev.json").write_bytes(canon(prev))
    proc = run([sys.executable, rs, "migrate", "--from", rev, "--settings-file",
                str(tmp_path / "prev.json")], env, cwd=str(home))
    assert "not migrated" not in proc.stdout and overlay(home)["env"]["LANG"] == "C"


def test_check_names_git_auto_push_one_without_failing(tmp_path, env):
    home, rev = make_home(tmp_path, env)
    land(env, home)
    rs = [sys.executable, str(home / "scripts/install/render-settings")]
    base = run([*rs, "check"], env, cwd=str(home), check=False)
    assert "GIT_AUTO_PUSH" not in base.stdout
    ov = overlay(home)
    ov["env"]["GIT_AUTO_PUSH"] = "1"
    (home / "settings.machine.json").write_bytes(canon(ov))
    run([*rs, "render"], env, cwd=str(home))
    proc = run([*rs, "check"], env, cwd=str(home), check=False)
    lines = [ln for ln in proc.stdout.splitlines() if "GIT_AUTO_PUSH" in ln]
    assert lines == ['[info] env.GIT_AUTO_PUSH is "1" in settings.machine.json: automatic pushes '
                     'are on']
    assert proc.returncode == base.returncode  # D1: an opt-in, so a line, not a failure


def test_migrate_skips_hooks_upstream_unregistered(tmp_path, env):
    """A hook of a harness script the previous revision tracks is public there; missing from
    the clean form, upstream unregistered it (P1's retired Stop gate): it is not migrated. A
    personal hook (outside the harness, or an untracked script) still is."""
    prev = previous_settings()
    retired = {"hooks": [hook("python3", "hooks/retired-gate.py", prefix="/opt/demo/.claude")]}
    personal = {"hooks": [hook("bash", "hooks/personal-acct-test-123.sh", prefix="/opt/demo/.claude")]}
    prev["hooks"]["Stop"] += [retired, personal]
    home, rev = make_home(tmp_path, env, prev)
    git(env, home, "checkout", "-q", rev)
    write(home / "hooks/retired-gate.py", "import sys\nsys.exit(0)\n")
    git(env, home, "add", "-A")
    git(env, home, "commit", "-q", "-m", "pre-P7: the gate tracked")
    rev2 = git(env, home, "rev-parse", "HEAD").stdout.strip()
    git(env, home, "checkout", "-q", "master")
    run([sys.executable, str(home / "scripts/install/render-settings"), "migrate", "--from", rev2],
        env, cwd=str(home))
    stop = [h["command"] for g in overlay(home)["hooks"]["Stop"] for h in g["hooks"]]
    assert stop == [personal["hooks"][0]["command"]]


# ------------------------------------------------------------------ R1, R3: the pre-pull revision

def test_rev_detection_survives_an_overwritten_orig_head(tmp_path, env):
    home, rev = make_home(tmp_path, env)
    rs = [sys.executable, str(home / "scripts/install/render-settings"), "land", "--rev"]
    assert run(rs, env).stdout.strip() == rev
    git(env, home, "reset", "-q", "--soft", "HEAD")  # a later git operation rewrites ORIG_HEAD
    assert git(env, home, "rev-parse", "ORIG_HEAD").stdout.strip() != rev
    assert run(rs, env).stdout.strip() == rev
    shutil.rmtree(home / ".git" / "logs")  # no reflog: ORIG_HEAD is the fallback
    git(env, home, "update-ref", "ORIG_HEAD", rev)
    assert run(rs, env).stdout.strip() == rev
    clone = tmp_path / "clone"  # a fresh clone: only the clone entry, the filter declared
    git(env, tmp_path, "clone", "-q", str(home), str(clone))
    proc = run([sys.executable, str(clone / "scripts/install/render-settings"), "land", "--rev"],
               env, check=False)
    assert proc.returncode == 1 and proc.stdout.strip() == ""
    assert land(env, clone, "--state").strip() == "none"
    assert land(env, clone) == "" and not (clone / "logs").exists()
    assert not (clone / "settings.machine.json").exists()


def test_a_clone_made_after_p7_that_looked_at_history_is_not_landed(tmp_path, env):
    """D13 (a fresh clone is never switched on): a clone whose reflog starts at a revision that
    declares the filter, then checked out a pre-P7 revision and came back, is still a fresh clone.
    Nothing is written and nothing is said; init is its producer."""
    origin, rev = make_home(tmp_path, env, name="origin")
    clone = tmp_path / "fresh"
    git(env, tmp_path, "clone", "-q", str(origin), str(clone))
    git(env, clone, "checkout", "-q", rev)
    git(env, clone, "checkout", "-q", "-")
    assert land(env, clone, "--state").strip() == "none"
    assert land(env, clone) == ""
    assert not [p for p in ("settings.machine.json", "private-literals.txt", "logs")
                if (clone / p).exists()]


@pytest.mark.parametrize("mode", ["--no-rebase", "--rebase"])
def test_a_home_whose_reflog_expired_before_the_pull_is_upgraded(tmp_path, env, mode):
    """R1, R3: a home whose HEAD had not moved for longer than the reflog keeps entries (expired by
    gc) has, after a fast-forward pull, one reflog entry whose new value declares the filter; its
    old value is rev, and so is ORIG_HEAD. Either one is enough."""
    origin, rev = make_home(tmp_path, env, name="origin")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", rev)
    git(env, home, "branch", "-q", "-u", "origin/master")
    git(env, home, "reflog", "expire", "--expire=now", "--all")
    assert git(env, home, "reflog", "HEAD").stdout == ""
    git(env, home, "pull", "-q", mode, "--no-edit", "origin", "master")
    assert len(git(env, home, "reflog", "HEAD").stdout.splitlines()) == 1
    rs = [sys.executable, str(home / "scripts/install/render-settings"), "land", "--rev"]
    assert run(rs, env).stdout.strip() == rev
    git(env, home, "update-ref", "-d", "ORIG_HEAD")  # the reflog's old value alone
    assert run(rs, env).stdout.strip() == rev
    assert land(env, home, "--state").strip() == "upgraded"
    assert land(env, home).startswith("Harness landing: P7 landed on this home")
    assert_landed(env, home)


# ------------------------------------------------------- R2: the states a pull path leaves behind

def clone_home(env, tmp_path, origin):
    """The harness home as a clone made before P7: the clone entry at origin's P7 revision is
    dropped from the HEAD reflog (a clone made at a filter revision is left to init, D13)."""
    home = tmp_path / "harness"
    git(env, tmp_path, "clone", "-q", str(origin), str(home))
    (home / ".git" / "logs" / "HEAD").unlink()
    return Path(os.path.realpath(home))


def pulled_home(tmp_path, env, live_edit, other=None):
    """A pre-P7 home (at rev, with a live edit) pulling P7 the way fswatch does: stash, pull
    --rebase, pop. Returns (home, rev, pop result)."""
    origin, rev = make_home(tmp_path, env, name="origin")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", rev)
    git(env, home, "branch", "-q", "-u", "origin/master")
    live = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    live_edit(live)
    (home / "settings.json").write_bytes(canon(live))
    for rel, text in (other or {}).items():
        write(home / rel, text)
    git(env, home, "stash", "push", "-q", "-m", "a message the match ignores")
    git(env, home, "pull", "-q", "--rebase", "origin", "master")
    return home, rev, git(env, home, "stash", "pop", check=False)


def add_allow(live):  # at the top, away from the lines P7 changed: the pop merges it
    live["permissions"]["allow"].insert(0, "Bash(/opt/demo/bin/live-tool:*)")


def model_and_allow(live):
    add_allow(live)
    live["model"] = "demo-live-model"


def test_s3_conflicted_pop_lands_from_the_stash_and_unstages_what_it_staged(tmp_path, env):
    other = {"notes.txt": "owner note\n", "a*b.txt": "glob-named, edited\n"}
    home, rev, pop = pulled_home(tmp_path, env, model_and_allow, other)
    assert pop.returncode != 0 and "settings.json" in git(env, home, "diff", "--name-only",
                                                          "--diff-filter=U").stdout
    staged = set(git(env, home, "diff", "--cached", "--name-only", "HEAD").stdout.split())
    assert {"notes.txt", "a*b.txt"} <= staged
    write(home / "user-staged.txt", "staged by the user, not by the pop\n")
    git(env, home, "add", "user-staged.txt")
    notice = land(env, home)
    assert "P7 landed" in notice and "stash entry kept" in notice
    staged = git(env, home, "diff", "--cached", "--name-only", "HEAD").stdout
    assert staged.split() == ["user-staged.txt"]
    assert (home / "notes.txt").read_text() == "owner note\n"  # working content unchanged
    assert git(env, home, "ls-files", "-u").stdout == ""
    assert len(git(env, home, "stash", "list").stdout.splitlines()) == 1
    ov = overlay(home)
    assert ov["model"] == "demo-live-model"  # the live file at pull time, from the stash
    assert "Bash(/opt/demo/bin/live-tool:*)" in ov["permissions"]["allow"]
    rendered = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    assert rendered["model"] == "demo-live-model"


def test_a_path_the_pop_merged_and_staged_is_unstaged_too(tmp_path, env):
    """R2's goal, the index equal to HEAD for the paths the conflicted pop staged: a path changed
    upstream and in the stash in different lines is merged and staged by the pop (its index blob
    is the merge, not the stash's). It is unstaged too, its merged working content kept."""
    lines = "".join("line %d\n" % i for i in range(1, 11))
    origin, rev = make_home(tmp_path, env, name="origin")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", rev)
    git(env, home, "branch", "-q", "-u", "origin/master")
    write(home / "multi.txt", lines)
    git(env, home, "add", "multi.txt")
    git(env, home, "commit", "-q", "-m", "pre-P7: multi.txt")
    git(env, origin, "fetch", "-q", str(home), "master:pre")  # upstream: P7 merged, line 1 edited
    git(env, origin, "merge", "-q", "--no-edit", "pre")
    write(origin / "multi.txt", lines.replace("line 1\n", "line 1 upstream\n"))
    git(env, origin, "commit", "-q", "-am", "upstream: multi.txt")
    git(env, home, "fetch", "-q", "origin")
    write(home / "multi.txt", lines.replace("line 10\n", "line 10 live\n"))
    write(home / "notes.txt", "owner note\n")
    live(home, model_and_allow)
    git(env, home, "stash", "push", "-q")
    git(env, home, "pull", "-q", "--rebase", "origin", "master")
    assert git(env, home, "stash", "pop", check=False).returncode != 0
    status = git(env, home, "status", "--porcelain").stdout.splitlines()
    assert {"M  multi.txt", "M  notes.txt", "UU settings.json"} <= set(status)
    notice = land(env, home)
    assert "1 file(s) a pull left conflicted taken from upstream (0 doc-sync), 2 staged path(s) " \
        "unstaged, the stash entry kept" in notice
    assert git(env, home, "diff", "--cached", "--name-only", "HEAD").stdout == ""
    merged = lines.replace("line 1\n", "line 1 upstream\n").replace("line 10\n", "line 10 live\n")
    assert (home / "multi.txt").read_text() == merged
    assert (home / "notes.txt").read_text() == "owner note\n"


def test_other_unmerged_paths_stay_and_an_empty_unstage_list_resets_nothing(tmp_path, env):
    """An unmerged file the owner edited stays unmerged (counted); with nothing the pop staged,
    no `git reset` runs (without a pathspec it would reset the whole index)."""
    origin, rev = make_home(tmp_path, env, name="origin")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", rev)
    git(env, home, "branch", "-q", "-u", "origin/master")
    write(home / "hooks/lib/subagent_restart.py", "# owner's edit\n")  # tracked; P7 rewrote it
    live = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    model_and_allow(live)
    (home / "settings.json").write_bytes(canon(live))
    git(env, home, "stash", "push", "-q")
    git(env, home, "pull", "-q", "--rebase", "origin", "master")
    git(env, home, "stash", "pop", check=False)
    unmerged = set(git(env, home, "diff", "--name-only", "--diff-filter=U").stdout.split())
    assert unmerged == {"settings.json", "hooks/lib/subagent_restart.py"}
    notice = land(env, home)
    assert "1 other conflicted path(s) left as they are" in notice
    assert git(env, home, "diff", "--name-only", "--diff-filter=U").stdout.split() == \
        ["hooks/lib/subagent_restart.py"]
    assert git(env, home, "diff", "--cached", "--name-only", "HEAD", "--", "settings.json").stdout == ""


def pre_pull_clone(tmp_path, env):
    origin, rev = make_home(tmp_path, env, name="origin")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", rev)
    git(env, home, "branch", "-q", "-u", "origin/master")
    return Path(os.path.realpath(home)), rev


def live(home, edit):
    doc = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    edit(doc)
    (home / "settings.json").write_bytes(canon(doc))


def test_a_pop_conflicting_only_on_another_file_still_unstages_what_it_staged(tmp_path, env):
    """settings.json merges, an owner's hook edit conflicts: what the pop staged is unstaged all
    the same, the owner's conflict stays."""
    home, rev = pre_pull_clone(tmp_path, env)
    write(home / "hooks/lib/subagent_restart.py", "# owner's edit\n")
    write(home / "notes.txt", "owner note\n")
    live(home, add_allow)
    git(env, home, "stash", "push", "-q")
    git(env, home, "pull", "-q", "--rebase", "origin", "master")
    git(env, home, "stash", "pop", check=False)
    assert git(env, home, "diff", "--name-only", "--diff-filter=U").stdout.split() == \
        ["hooks/lib/subagent_restart.py"]
    assert "notes.txt" in git(env, home, "diff", "--cached", "--name-only", "HEAD").stdout
    notice = land(env, home)
    assert "staged path(s) unstaged" in notice and "1 other conflicted path(s) left" in notice
    assert git(env, home, "diff", "--cached", "--name-only", "HEAD", "--", "notes.txt",
               "settings.json").stdout == ""
    assert (home / "notes.txt").read_text() == "owner note\n"
    assert "Bash(/opt/demo/bin/live-tool:*)" in overlay(home)["permissions"]["allow"]


def test_an_older_entry_at_rev_is_not_the_pulls_once_the_pop_merged(tmp_path, env):
    """S2 with an older stash entry kept at rev (an earlier attempt): the pull's own entry was
    dropped by its clean pop, so the working file, not that entry, holds the previous settings."""
    home, rev = pre_pull_clone(tmp_path, env)
    live(home, lambda doc: doc.update(model="demo-stale-model"))
    git(env, home, "stash", "push", "-q")  # kept from an earlier attempt, first parent rev
    live(home, add_allow)
    git(env, home, "stash", "push", "-q")
    git(env, home, "pull", "-q", "--rebase", "origin", "master")
    git(env, home, "stash", "pop", "-q")
    assert len(git(env, home, "stash", "list").stdout.splitlines()) == 1
    land(env, home)
    ov = overlay(home)
    assert "Bash(/opt/demo/bin/live-tool:*)" in ov["permissions"]["allow"]
    assert ov.get("model") != "demo-stale-model"


@pytest.mark.parametrize("edit", [add_allow, lambda live: None], ids=["S2", "S1"])
def test_s1_s2_land_with_the_working_file(tmp_path, env, edit):
    home, rev, pop = pulled_home(tmp_path, env, edit)
    assert pop.returncode == 0 or "No stash entries" in pop.stderr
    notice = land(env, home)
    assert notice.count("\n") == 1 and "P7 landed" in notice
    assert_landed(env, home)
    rendered = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    has = "Bash(/opt/demo/bin/live-tool:*)" in rendered["permissions"]["allow"]
    assert has == (edit is add_allow)
    assert git(env, home, "stash", "list").stdout == ""


def test_working_git_auto_push_one_is_dropped_not_stuck(tmp_path, env):
    """A live "1" the overlay may not carry (D1): the landing still renders, push off."""
    home, rev, pop = pulled_home(tmp_path, env, lambda live: live["env"].update(GIT_AUTO_PUSH="1"))
    assert json.loads((home / "settings.json").read_text())["env"]["GIT_AUTO_PUSH"] == "1"
    notice = land(env, home)
    assert "GIT_AUTO_PUSH not migrated" in notice
    assert_landed(env, home)
    assert json.loads((home / "settings.json").read_text())["env"]["GIT_AUTO_PUSH"] == "0"


def render_settings(env, home, code):
    """Run code with `rs` = this home's render-settings module, cwd the home."""
    loader = ("import os, sys; sys.dont_write_bytecode = True; import importlib.machinery as m, "
              "importlib.util as u; home, rev = sys.argv[1], sys.argv[2]; os.chdir(home); "
              "ld = m.SourceFileLoader('rs', 'scripts/install/render-settings'); "
              "rs = u.module_from_spec(u.spec_from_loader('rs', ld)); ld.exec_module(rs); ")
    return run([sys.executable, "-c", loader + code, str(home), ""], env, cwd=str(home))


@pytest.mark.parametrize("edit", ["push-one", "allow"])
def test_a_landing_cut_short_after_the_migration_completes(tmp_path, env, edit):
    """R1 (a landing killed half-way completes at the next trigger): the landing stopped right
    after its migration, before settings.json was taken from HEAD. The next Stop takes it from
    HEAD all the same, so the render does not refuse the working GIT_AUTO_PUSH "1" that D1 keeps
    out of the overlay, and the home lands."""
    fn = (lambda live: live["env"].update(GIT_AUTO_PUSH="1")) if edit == "push-one" else add_allow
    home, rev, pop = pulled_home(tmp_path, env, fn)
    render_settings(env, home, "rev = rs.pre_pull_rev(home); sys.exit(rs.cmd_migrate(home, rev, None, "
                               "'HEAD', rs.previous_settings(home, rev, None)))")
    notice = land(env, home)
    assert "P7 landed" in notice and "dropped" not in notice
    assert ("GIT_AUTO_PUSH not migrated" in notice) == (edit == "push-one")
    assert_landed(env, home)
    rendered = json.loads((home / "settings.json").read_text())
    assert rendered["env"]["GIT_AUTO_PUSH"] == "0"
    assert ("Bash(/opt/demo/bin/live-tool:*)" in rendered["permissions"]["allow"]) == (edit == "allow")


@pytest.mark.parametrize("edit", [add_allow, lambda live: None], ids=["S2", "S1"])
def test_a_cli_write_between_the_settings_step_and_the_render_does_not_wedge(tmp_path, env, edit):
    """The CLI writes an allow entry after render-settings land took settings.json from HEAD and
    before init step 3 rendered it (that render refused it at every later Stop). The next Stop
    takes settings.json from HEAD again, names what it dropped (the overlay that exists is never
    rewritten), and lands."""
    home, rev, pop = pulled_home(tmp_path, env, edit)
    run([sys.executable, str(home / "scripts/install/render-settings"), "land"], env, cwd=str(home))
    doc = json.loads((home / "settings.json").read_text())
    doc["permissions"]["allow"].append("Bash(demo-cli-approved:*)")
    (home / "settings.json").write_text(json.dumps(doc, indent=2) + "\n")
    notice = land(env, home)
    assert "P7 landed" in notice
    assert "dropped from settings.json, as the overlay does not hold them: permissions.allow: " \
        "1 entry" in notice
    assert_landed(env, home)
    rendered = json.loads((home / "settings.json").read_text())
    assert "Bash(demo-cli-approved:*)" not in rendered["permissions"]["allow"]
    has = "Bash(/opt/demo/bin/live-tool:*)" in rendered["permissions"]["allow"]
    assert has == (edit is add_allow)
    assert "demo-cli-approved" not in notice + landing_log(home)


def test_s4_stopped_rebase_changes_nothing(tmp_path, env):
    home, rev = make_home(tmp_path, env)
    gd = home / ".git"
    (gd / "rebase-merge").mkdir()
    (gd / "rebase-merge" / "head-name").write_text("refs/heads/master\n")
    before = [(gd / "index").read_bytes(), git(env, home, "rev-parse", "HEAD").stdout]
    notice = land(env, home)
    assert notice.startswith("Harness landing waits: a rebase is stopped in the harness home")
    assert "nothing was changed" in notice
    assert [(gd / "index").read_bytes(), git(env, home, "rev-parse", "HEAD").stdout] == before
    assert not (home / "settings.machine.json").exists() and (gd / "rebase-merge").is_dir()
    assert git(env, home, "config", "--local", "--get", "filter.claude-settings.clean",
               check=False).returncode == 1


def test_s4_stopped_merge_on_pre_p7_head_gets_the_notice(tmp_path, env):
    """A merge pull stopped on a local commit: HEAD is still the pre-P7 revision, MERGE_HEAD
    declares the filter. The session that runs the merged hooks sees the S4 notice."""
    origin, rev = make_home(tmp_path, env, name="origin")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", rev)
    live = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    live["env"]["TMPDIR"] = "/opt/demo/local"  # a local commit on a line P7 changed
    (home / "settings.json").write_bytes(canon(live))
    git(env, home, "commit", "-q", "-am", "local")
    assert git(env, home, "pull", "-q", "--no-rebase", "--no-edit", "origin", "master",
               check=False).returncode != 0
    assert (home / ".git" / "MERGE_HEAD").exists()
    index = (home / ".git" / "index").read_bytes()
    notice = land(env, home)
    assert notice.startswith("Harness landing waits: a merge is stopped in the harness home")
    assert (home / ".git" / "index").read_bytes() == index
    assert not (home / "settings.machine.json").exists()


def settings_commit(env, home, parent, value, msg):
    """A commit on parent whose settings.json sets env.DEMO_SIDE (plumbing: no filter, no hook)."""
    doc = json.loads(git(env, home, "show", "%s:settings.json" % parent).stdout)
    doc["env"]["DEMO_SIDE"] = value
    data = run(["git", "-C", str(home), "hash-object", "-w", "--no-filters", "--stdin"], env,
               input=canon(doc).decode()).stdout.strip()
    index = dict(env, GIT_INDEX_FILE=str(home / ".git" / ("index-" + msg)))
    git(index, home, "read-tree", parent)
    git(index, home, "update-index", "--cacheinfo", "100644,%s,settings.json" % data)
    tree = git(index, home, "write-tree").stdout.strip()
    os.unlink(index["GIT_INDEX_FILE"])
    return git(env, home, "commit-tree", tree, "-p", parent, "-m", msg).stdout.strip()


def test_a_stopped_squash_merge_is_an_integration_in_progress(tmp_path, env):
    """S4: `git merge --squash` that conflicts leaves SQUASH_MSG and no MERGE_HEAD. On a landed
    home with a kept stash entry, settings.json unmerged by that squash is the owner's work in
    progress, not a pull's pop: nothing is changed. An upgraded home waits with the notice."""
    home, rev, pop = pulled_home(tmp_path, env, model_and_allow)
    land(env, home)
    assert len(git(env, home, "stash", "list").stdout.splitlines()) == 1
    head = git(env, home, "rev-parse", "HEAD").stdout.strip()
    git(env, home, "branch", "-q", "side", settings_commit(env, home, head, "side-value", "side"))
    ours = settings_commit(env, home, head, "master-value", "master")
    git(env, home, "merge", "-q", "--ff-only", ours)
    assert git(env, home, "merge", "--squash", "side", check=False).returncode != 0
    assert (home / ".git/SQUASH_MSG").exists() and not (home / ".git/MERGE_HEAD").exists()
    before = (home / ".git/index").read_bytes(), (home / "settings.json").read_bytes()
    assert land(env, home) == ""
    assert ((home / ".git/index").read_bytes(), (home / "settings.json").read_bytes()) == before
    assert "UU settings.json" in git(env, home, "status", "--porcelain").stdout
    assert "stopped=squash merge" in landing_log(home)
    home2, _ = make_home(tmp_path, env, name="h2")
    (home2 / ".git/SQUASH_MSG").write_text("Squashed commit of the following:\n")
    assert land(env, home2).startswith("Harness landing waits: a squash merge is stopped in the "
                                       "harness home")


def test_stash_is_found_by_content_not_by_message(tmp_path, env):
    """Two entries whose first parent is rev: the newest one whose settings.json differs from
    rev's is the pull's, whatever its message."""
    home, rev, pop = pulled_home(tmp_path, env, model_and_allow)
    rs = [sys.executable, "-c", "import importlib.machinery as m, importlib.util as u, sys;"
          "sys.dont_write_bytecode = True; ld = m.SourceFileLoader('rs', sys.argv[1]);"
          "rs = u.module_from_spec(u.spec_from_loader('rs', ld)); ld.exec_module(rs);"
          "print(rs.pull_stash(sys.argv[2], sys.argv[3]) or '')",
          str(home / "scripts/install/render-settings"), str(home), rev]
    pull = git(env, home, "rev-parse", "stash@{0}").stdout.strip()
    assert run(rs, env).stdout.strip() == pull
    # A newer entry at rev that leaves settings.json alone is not the pull's.
    tree = git(env, home, "rev-parse", rev + "^{tree}").stdout.strip()
    other = run(["git", "-C", str(home), "commit-tree", tree, "-p", rev, "-p", rev, "-m",
                 "fswatch auto-stash 1"], env).stdout.strip()
    git(env, home, "update-ref", "--create-reflog", "refs/stash", other)
    assert git(env, home, "rev-parse", "stash@{0}").stdout.strip() == other
    assert run(rs, env).stdout.strip() == pull


# ------------------------------------------------------- R2: the doc-sync exception (later pulls)

DATED = "# commands\n\n<!-- AUTO:index-stats -->\n*Last updated: %s*\n**Total entries**: 2\n" \
        "<!-- /AUTO:index-stats -->\n"
CLAUDE_MD = "# Config\n\n<!-- AUTO:last-updated -->\n> Last updated: %s\n%s\n<!-- /AUTO:last-updated -->\n"


def test_doc_sync_only_conflicts_take_upstreams_side(tmp_path, env):
    """A landed home; doc-sync re-dated commands/INDEX.md and CLAUDE.md; upstream deletes the
    index (DU at the pop) and edits the line next to CLAUDE.md's date (UU): both take upstream's
    side, the stash entry stays, and the next pull is not stopped by "needs merge". A file whose
    stash change is more than the date stays unmerged."""
    origin, _rev = make_home(tmp_path, env, name="origin")
    write(origin / "commands/INDEX.md", DATED % "2026-01-01T00:00:00Z")
    write(origin / "CLAUDE.md", CLAUDE_MD % ("2026-01-01", "---"))
    write(origin / "agents/INDEX.md", DATED % "2026-01-01T00:00:00Z")
    git(env, origin, "add", "-A")
    git(env, origin, "commit", "-q", "-m", "indexes")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", _rev)
    git(env, home, "merge", "-q", "--ff-only", "origin/master")
    land(env, home)  # an upgraded home lands first
    assert_landed(env, home)
    git(env, origin, "rm", "-q", "commands/INDEX.md")  # upstream: P8/P9-style index deletion
    write(origin / "CLAUDE.md", CLAUDE_MD % ("2026-01-01", "--- upstream edit"))
    write(origin / "agents/INDEX.md", DATED % "2026-01-01T00:00:00Z" + "upstream line\n")
    git(env, origin, "add", "-A")
    git(env, origin, "commit", "-q", "-m", "upstream")
    write(home / "commands/INDEX.md", DATED % "2026-02-02T00:00:00Z")  # doc-sync re-dates
    write(home / "CLAUDE.md", CLAUDE_MD % ("2026-02-02", "---"))
    write(home / "agents/INDEX.md", (DATED % "2026-02-02T00:00:00Z") + "owner line\n")
    git(env, home, "stash", "push", "-q", "-m", "Auto-stash before pull")
    git(env, home, "pull", "-q", "--rebase", "origin", "master")
    assert git(env, home, "stash", "pop", check=False).returncode != 0
    status = git(env, home, "status", "--porcelain").stdout
    assert "DU commands/INDEX.md" in status and "UU CLAUDE.md" in status
    assert land(env, home, "--state").strip() == "landed"
    notice = land(env, home)
    assert notice == "Harness landing: 2 file(s) a pull left conflicted taken from upstream (2 " \
        "doc-sync), 0 staged path(s) unstaged, the stash entry kept; 1 other conflicted path(s) " \
        "left as they are.\n"
    assert git(env, home, "diff", "--name-only", "--diff-filter=U").stdout.split() == \
        ["agents/INDEX.md"]
    assert not (home / "commands/INDEX.md").exists()
    assert (home / "CLAUDE.md").read_text() == CLAUDE_MD % ("2026-01-01", "--- upstream edit")
    assert len(git(env, home, "stash", "list").stdout.splitlines()) == 1
    assert land(env, home) == ""  # nothing left that the repair owns: no notice, no change
    git(env, home, "checkout", "-q", "HEAD", "--", "agents/INDEX.md")  # the owner's own conflict
    write(origin / "README.md", "next upstream change\n")
    git(env, origin, "add", "-A")
    git(env, origin, "commit", "-q", "-m", "next")
    assert git(env, home, "pull", "-q", "--rebase", "origin", "master").returncode == 0


def test_an_owners_own_doc_conflict_runs_no_repair_at_each_stop(tmp_path, env):
    """R1 (review LH-5): a landed home whose later pull left CLAUDE.md unmerged with the owner's
    own change (more than doc-sync's date line) runs no repair at its Stops (no python process,
    no log line, no notice) until the owner resolves it; nothing in it is the repair's to take."""
    origin, rev = make_home(tmp_path, env, name="origin")
    write(origin / "CLAUDE.md", CLAUDE_MD % ("2026-01-01", "---"))
    git(env, origin, "add", "-A")
    git(env, origin, "commit", "-q", "-m", "CLAUDE.md")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", rev)
    git(env, home, "merge", "-q", "--ff-only", "origin/master")
    land(env, home)
    write(origin / "CLAUDE.md", CLAUDE_MD % ("2026-01-01", "--- upstream edit"))
    git(env, origin, "commit", "-q", "-am", "upstream")
    write(home / "CLAUDE.md", CLAUDE_MD % ("2026-02-02", "--- the owner's edit"))
    git(env, home, "stash", "push", "-q", "-m", "Auto-stash before pull")
    git(env, home, "pull", "-q", "--rebase", "origin", "master")
    assert git(env, home, "stash", "pop", check=False).returncode != 0
    log = landing_log(home)
    assert land(env, home) == "" and land(env, home) == ""
    assert landing_log(home) == log
    assert "UU CLAUDE.md" in git(env, home, "status", "--porcelain").stdout


def append_allow(path, entry):  # at the end of the list, the way the CLI adds one
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["permissions"]["allow"].append(entry)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def test_a_landed_repair_names_the_live_entries_it_drops(tmp_path, env):
    """R2, R9 (review LH-7): a landed home's later pull conflicts on settings.json (upstream and
    the CLI each appended an allow entry). settings.json takes upstream's side; the live entry the
    overlay does not hold is then only in the kept stash entry, and the notice and the log name
    it by key path, never by value."""
    origin, rev = make_home(tmp_path, env, name="origin")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", rev)
    git(env, home, "merge", "-q", "--ff-only", "origin/master")
    land(env, home)
    assert land(env, home, "--state").strip() == "landed"
    append_allow(origin / "settings.json", "Bash(demo-upstream-tool:*)")
    git(env, origin, "commit", "-q", "-am", "upstream allow")
    append_allow(home / "settings.json", "Bash(/opt/demo/bin/live-tool2:*)")
    git(env, home, "stash", "push", "-q", "-m", "Auto-stash before pull")
    git(env, home, "pull", "-q", "--rebase", "origin", "master")
    assert git(env, home, "stash", "pop", check=False).returncode != 0
    assert "UU settings.json" in git(env, home, "status", "--porcelain").stdout
    notice = land(env, home)
    assert notice.startswith("Harness landing: 1 file(s) a pull left conflicted taken from upstream")
    assert "dropped from settings.json, as the overlay does not hold them: permissions.allow: 1 " \
        "entry (in the stash entry)" in notice
    assert "settings.json taken from HEAD; dropped: permissions.allow: 1 entry" in landing_log(home)
    rendered = (home / "settings.json").read_text(encoding="utf-8")
    assert "demo-upstream-tool" in rendered and "live-tool2" not in rendered
    assert "live-tool2" in git(env, home, "show", "stash@{0}:settings.json").stdout
    assert "live-tool2" not in notice + landing_log(home)


def test_a_repair_that_git_refused_claims_nothing_and_runs_again(tmp_path, env):
    """R2, R9 (review LH-6): while a git lock refuses the checkout or rm, the path stays unmerged
    and is neither counted as taken from upstream nor said to be; the next Stop resolves it."""
    origin, _rev = make_home(tmp_path, env, name="origin")
    write(origin / "commands/INDEX.md", DATED % "2026-01-01T00:00:00Z")
    git(env, origin, "add", "-A")
    git(env, origin, "commit", "-q", "-m", "index")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", _rev)
    git(env, home, "merge", "-q", "--ff-only", "origin/master")
    land(env, home)
    git(env, origin, "rm", "-q", "commands/INDEX.md")
    git(env, origin, "commit", "-q", "-m", "upstream deletes the index")
    write(home / "commands/INDEX.md", DATED % "2026-02-02T00:00:00Z")  # doc-sync re-dates it
    git(env, home, "stash", "push", "-q", "-m", "Auto-stash before pull")
    git(env, home, "pull", "-q", "--rebase", "origin", "master")
    assert git(env, home, "stash", "pop", check=False).returncode != 0
    (home / ".git" / "index.lock").write_text("")
    assert land(env, home) == ""
    assert "DU commands/INDEX.md" in git(env, home, "status", "--porcelain").stdout
    assert "repair resolved=0 doc-sync=0 unstaged=0 unmerged-left=1" in landing_log(home)
    (home / ".git" / "index.lock").unlink()
    assert land(env, home).startswith("Harness landing: 1 file(s) a pull left conflicted taken "
                                      "from upstream (1 doc-sync)")
    assert git(env, home, "diff", "--name-only", "--diff-filter=U").stdout == ""


def test_an_upgraded_home_whose_repair_git_refused_claims_nothing(tmp_path, env):
    """The same on an upgraded S3 home: neither settings.json nor the path the pop staged is
    counted while the lock refuses them; the next Stop repairs both and lands."""
    home, rev, pop = pulled_home(tmp_path, env, model_and_allow, {"notes.txt": "owner note\n"})
    assert pop.returncode != 0
    (home / ".git" / "index.lock").write_text("")
    assert "taken from upstream" not in land(env, home)
    assert "repair resolved=0 doc-sync=0 unstaged=0 unmerged-left=1" in landing_log(home)
    (home / ".git" / "index.lock").unlink()
    assert "1 file(s) a pull left conflicted taken from upstream (0 doc-sync), 1 staged path(s) " \
        "unstaged" in land(env, home)
    assert land(env, home, "--state").strip() == "landed"
    assert git(env, home, "status", "--porcelain").stdout == " M notes.txt\n"


def test_doc_sync_conflicts_on_an_upgraded_home_whose_pull_left_settings_alone(tmp_path, env):
    """R2's doc-sync exception in the landing itself: the pull's entry holds only doc-sync's
    re-dated CLAUDE.md and commands/INDEX.md (settings.json untouched, so no entry differs from
    rev on it); upstream deleted the index and edited the line next to CLAUDE.md's date. The
    landing takes upstream's side for both in the same Stop."""
    origin, rev = make_home(tmp_path, env, name="origin")
    home = clone_home(env, tmp_path, origin)
    git(env, home, "checkout", "-q", "-B", "master", rev)
    git(env, home, "branch", "-q", "-u", "origin/master")
    write(home / "commands/INDEX.md", DATED % "2026-01-01T00:00:00Z")
    write(home / "CLAUDE.md", CLAUDE_MD % ("2026-01-01", "---"))
    git(env, home, "add", "-A")
    git(env, home, "commit", "-q", "-m", "pre-P7 indexes")
    git(env, origin, "fetch", "-q", str(home), "master:pre")  # upstream: P7 merged with them
    git(env, origin, "merge", "-q", "--no-edit", "-X", "theirs", "pre")
    git(env, origin, "rm", "-q", "commands/INDEX.md")
    write(origin / "CLAUDE.md", CLAUDE_MD % ("2026-01-01", "--- upstream edit"))
    git(env, origin, "add", "-A")
    git(env, origin, "commit", "-q", "-m", "upstream")
    git(env, home, "fetch", "-q", "origin")
    write(home / "commands/INDEX.md", DATED % "2026-02-02T00:00:00Z")  # doc-sync re-dates both
    write(home / "CLAUDE.md", CLAUDE_MD % ("2026-02-02", "---"))
    git(env, home, "stash", "push", "-q", "-m", "Auto-stash before pull")
    git(env, home, "pull", "-q", "--rebase", "origin", "master")
    assert git(env, home, "stash", "pop", check=False).returncode != 0
    status = git(env, home, "status", "--porcelain").stdout
    assert "DU commands/INDEX.md" in status and "UU CLAUDE.md" in status
    notice = land(env, home)
    assert "P7 landed" in notice
    assert "2 file(s) a pull left conflicted taken from upstream (2 doc-sync)" in notice
    assert git(env, home, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert not (home / "commands/INDEX.md").exists()
    assert (home / "CLAUDE.md").read_text() == CLAUDE_MD % ("2026-01-01", "--- upstream edit")
    assert_landed(env, home)


# ------------------------------------- the pull paths' own stash and pop (routed by PR #6's review)

def upstream_commit(env, origin, rel="upstream-note.md"):
    write(origin / rel, "an upstream change\n")
    git(env, origin, "add", rel)
    git(env, origin, "commit", "-q", "-m", "upstream: " + rel)


@pytest.mark.parametrize("kept", [True, False], ids=["kept-entry", "no-entry"])
def test_pull_sh_pops_only_an_entry_its_own_push_made(tmp_path, env, kept):
    """hooks/pull.sh counts untracked files as changes, but `git stash push` saves nothing for
    them. With only an untracked file, a clean fast-forward must not pop anything: not the entry a
    conflicted pop kept (the landing keeps it, R2), and not "no entry" as a failure."""
    if kept:
        home, rev, pop = pulled_home(tmp_path, env, model_and_allow)
        land(env, home)
    else:
        home, rev = pre_pull_clone(tmp_path, env)
        git(env, home, "merge", "-q", "--ff-only", "origin/master")
        land(env, home)
    assert_landed(env, home)
    entries = git(env, home, "stash", "list", "--format=%H").stdout
    assert len(entries.splitlines()) == (1 if kept else 0)
    settings = (home / "settings.json").read_bytes()
    upstream_commit(env, tmp_path / "origin")
    write(home / "scratch-note.txt", "an untracked file, nothing else\n")
    proc = run(["bash", str(REPO / "hooks/pull.sh")], env, cwd=str(home), check=False)
    assert proc.returncode == 0, proc.stdout[-600:] + proc.stderr[-600:]
    assert (home / "upstream-note.md").exists() and (home / "scratch-note.txt").exists()
    assert git(env, home, "stash", "list", "--format=%H").stdout == entries
    assert (home / "settings.json").read_bytes() == settings
    assert git(env, home, "status", "--porcelain").stdout == "?? scratch-note.txt\n"


# ------------------------------------------------------------------------------ R5: seeding

def test_seeding_sources_filters_and_no_value_printed(tmp_path, env):
    """R5's sources and filters. A permission path under the harness home that rev's hook
    commands name for the scripts rev tracks (the old settings' /opt/demo/.claude here, as
    /root/.claude in a /home/<user> layout: review F3) is a harness script, not a personal tool
    path: it is not seeded."""
    prev = previous_settings()
    prev["permissions"]["allow"] += ["Read(//opt/demo/notes/**)", "Bash(/tmp:*)"]
    home, rev = make_home(tmp_path, env, prev)
    git(env, home, "config", "--local", "user.email", "demo@example.invalid")
    git(env, home, "remote", "add", "origin", "git@example.invalid:demo-owner/harness.git")
    ov_env = {"CLAUDE_HOME": str(home), "CLAUDE_DEV_CONTAINERS": "demo-web-dev, demo-api-dev",
              "CLAUDE_HARD_BANNED_SCRIPTS": "demo-recovery|(^|/)demo-re[a-z]+\\.sh|session-recovery",
              "PASEO_DAEMON_ACCOUNTS": "acct-test-123,demo-owner,abc,acct-test-123",
              "PASEO_DAEMON_MODEL": "demo-model-without-account",
              "CLAUDE_CHECKPOINT_EXTRA_TRAILER": "Co-Authored-By: Demo Bot <demo-bot@example.invalid>",
              "GRAPHIFY_BIN": "/opt/demo/bin/graphify", "DEMO_FLAG": "/opt/demo/not-a-seed-key"}
    (home / "settings.machine.json").write_bytes(canon(
        {"modules": {"paseo": False}, "env": ov_env,
         "permissions": {"allow": prev["permissions"]["allow"]}}))
    (home / "settings.machine.json").chmod(0o600)
    notice = land(env, home)
    lines = (home / "private-literals.txt").read_text().splitlines()
    assert "Bash(/opt/demo/.claude/scripts/demo-tool.sh:*)" in prev["permissions"]["allow"]
    assert lines == ["demo-web-dev", "demo-api-dev", "demo-recovery", "demo-bot@example.invalid",
                     "acct-test-123", "/opt/demo/bin/graphify", "/opt/demo/bin/helper",
                     "/opt/demo/notes", "demo@example.invalid", "git@example.invalid:demo-owner",
                     "/home/demo-user", "demo-private-proj", "/opt/demo/ws-marker"]
    assert stat.S_IMODE((home / "private-literals.txt").stat().st_mode) == 0o600
    shown = notice + landing_log(home)
    assert "seeded with 13 value(s)" in notice
    assert "overlay-env=6 permission-paths=2 git-e-mail=1 check-markers=4" in shown
    assert not [v for v in lines if v in shown]


def test_seeding_never_rewrites_a_list_that_has_lines(tmp_path, env):
    """R5: seeded only when absent or empty (blank lines only); a list with any line, a comment
    included, is kept as it is."""
    home, rev = make_home(tmp_path, env)
    write(home / "private-literals.txt", "\n\n")
    assert "seeded" in land(env, home)
    assert len((home / "private-literals.txt").read_text().splitlines()) > 2
    home1, _ = make_home(tmp_path, env, name="h1")
    write(home1 / "private-literals.txt", "# my list\n\n")
    assert "seeded" not in land(env, home1)
    assert (home1 / "private-literals.txt").read_text() == "# my list\n\n"
    home2, _ = make_home(tmp_path, env, name="h2")
    write(home2 / "private-literals.txt", "acct-test-999\n")
    before = (home2 / "private-literals.txt").read_bytes()
    assert "seeded" not in land(env, home2)
    assert (home2 / "private-literals.txt").read_bytes() == before


def test_a_value_the_tracked_tree_holds_in_100_lines_is_not_seeded(tmp_path, env):
    """R5 (review LH-2): a value that HEAD's tracked files hold in 100 or more lines is the tree's
    own vocabulary; the list cannot keep it out of the tree, and seeded it would refuse every
    snapshot that adds one more such line. A value in 99 lines is seeded; the log counts the one
    left out, and no value is printed."""
    home, rev = make_home(tmp_path, env)
    write(home / "docs/family.md", "demo-family runs here\n" * 100 + "demo-fam2 runs here\n" * 99)
    git(env, home, "add", "docs/family.md")
    git(env, home, "commit", "-q", "-m", "a public doc")
    (home / "settings.machine.json").write_bytes(canon(
        {"modules": {"paseo": False}, "env": {"CLAUDE_HOME": str(home),
                                              "CLAUDE_PROTECTED_PROCESS_FAMILY": "demo-family|demo-fam2"}}))
    (home / "settings.machine.json").chmod(0o600)
    notice = land(env, home)
    lines = (home / "private-literals.txt").read_text().splitlines()
    assert "demo-fam2" in lines and "demo-family" not in lines
    assert "not seeded, in 100 or more tracked lines at HEAD: 1 value(s)" in landing_log(home)
    assert not [v for v in lines + ["demo-family"] if v in notice + landing_log(home)]


# ------------------------------------------------------- R1, R4, R6, R9: the landing end to end

@pytest.mark.skipif(shutil.which("git-lfs") is None, reason="needs git-lfs")
def test_the_lfs_post_commit_is_restored_and_no_other_hook_is_touched(tmp_path, env):
    """R6 / D15: where the renamed combined hook carried the LFS step, git-lfs's own post-commit
    takes its place; the repository's other hooks (an owner's pre-push, post-merge) stay as they
    are and no LFS hook is added beside them; no global git config is written."""
    home, rev = make_home(tmp_path, env)
    repo = Path(env["HOME"]) / "repos" / "lfs"
    git(env, tmp_path, "init", "-q", str(repo))
    hooks = repo / ".git" / "hooks"
    write(hooks / "post-commit", LFS_LEGACY_HOOK, 0o755)
    for name in ("pre-push", "post-merge"):
        write(hooks / name, "#!/bin/sh\n# the owner's own %s\n" % name, 0o755)
    config = Path(env["GIT_CONFIG_GLOBAL"]).read_bytes()
    assert "(LFS hooks restored in 1)" in land(env, home)
    assert "git lfs post-commit" in (hooks / "post-commit").read_text()
    assert os.access(hooks / "post-commit", os.X_OK)
    for name in ("pre-push", "post-merge"):
        assert (hooks / name).read_text() == "#!/bin/sh\n# the owner's own %s\n" % name
    assert not (hooks / "post-checkout").exists()
    assert Path(env["GIT_CONFIG_GLOBAL"]).read_bytes() == config


def test_a_timed_out_repository_scan_is_logged_and_named(tmp_path, env):
    """R6 / R1: the scan for other repositories under $HOME stops after 5 s; the log and the
    notice say so (the home's own hooks are handled all the same)."""
    home, rev = make_home(tmp_path, env)
    write(home / ".git/hooks/post-commit", LEGACY_HOOK, 0o755)
    late = Path(env["HOME"]) / "zz" / "late-repo"
    git(env, tmp_path, "init", "-q", str(late))
    write(late / ".git/hooks/post-commit", LEGACY_HOOK, 0o755)
    stub = tmp_path / "slow-bin" / "find"  # a scan of $HOME that takes longer than its limit
    write(stub, '#!/bin/bash\n[ "$1" = "$HOME" ] && exec sleep 30\nexec %s "$@"\n'
          % shutil.which("find"), 0o755)
    notice = land(dict(env, PATH="%s:%s" % (stub.parent, env["PATH"])), home)
    assert "P7 landed" in notice and "1 legacy auto-push hook(s) renamed aside" in notice
    assert "the scan for other repositories under ~ stopped at its time limit; those it did not " \
        "reach keep their legacy hooks" in notice
    assert "legacy-hooks disabled=1 lfs-restored=0 scan=timed-out" in landing_log(home)
    assert (late / ".git/hooks/post-commit").exists()


def test_the_loop_over_the_repositories_found_keeps_to_the_time_bound(tmp_path, env):
    """R1 / R6 (review RQ-4): the loop over the repositories the scan found (one git call each)
    stops taking new ones after 8 s, so thousands of repositories under $HOME cannot push the
    landing past its 15 s bound; the harness home's own hooks come first, and the cut is logged
    and named like a cut scan. Here each of 5 repositories takes 3 s (a slow git stand-in)."""
    home, rev = make_home(tmp_path, env, name="zz-harness")  # not first by name
    write(home / ".git/hooks/post-commit", LEGACY_HOOK, 0o755)
    many = [Path(env["HOME"]) / "many" / ("r%d" % i) for i in range(5)]
    for repo in many:
        git(env, tmp_path, "init", "-q", str(repo))
        write(repo / ".git/hooks/post-commit", LEGACY_HOOK, 0o755)
    stub = tmp_path / "slow-bin" / "git"
    write(stub, '#!/bin/bash\ncase "$*" in "-C $HOME/many/"*" config --get core.hooksPath")'
          ' sleep 3 ;; esac\nexec %s "$@"\n' % shutil.which("git"), 0o755)
    started = time.time()
    notice = land(dict(env, PATH="%s:%s" % (stub.parent, env["PATH"])), home)
    assert time.time() - started < 15
    assert "P7 landed" in notice and "the scan for other repositories under ~ stopped at its time " \
        "limit" in notice
    assert "scan=timed-out" in landing_log(home)
    assert (home / ".git/hooks/post-commit.auto-push-disabled").exists()
    assert [(r / ".git/hooks/post-commit").exists() for r in many].count(True) >= 2


def test_a_legacy_hook_a_repository_tracks_is_left_and_counted(tmp_path, env):
    """R6 (review LH-3): a legacy post-commit that a repository tracks (core.hooksPath naming a
    tracked .githooks/) is left as it is, counted in the notice and the log: renamed, it would be
    deleted from that repository by its next `git commit -a`. Untracked ones are renamed."""
    home, rev = make_home(tmp_path, env)
    write(home / ".git/hooks/post-commit", LEGACY_HOOK, 0o755)
    team = Path(env["HOME"]) / "repos" / "team"
    git(env, tmp_path, "init", "-q", str(team))
    write(team / ".githooks/post-commit", LEGACY_HOOK, 0o755)
    git(env, team, "add", ".githooks/post-commit")
    git(env, team, "commit", "-q", "-m", "shared hooks")
    git(env, team, "config", "core.hooksPath", ".githooks")
    notice = land(env, home)
    assert "1 legacy auto-push hook(s) renamed aside" in notice
    assert "1 tracked legacy auto-push hook(s) left as they are" in notice
    assert "legacy-hooks disabled=1 lfs-restored=0 tracked-left=1" in landing_log(home)
    assert git(env, team, "status", "--porcelain").stdout == ""
    assert not (home / ".git/hooks/post-commit").exists()


def test_landing_end_to_end_and_idempotent(tmp_path, env):
    home, rev = make_home(tmp_path, env)
    gd = home / ".git"
    write(gd / "hooks/post-commit", LEGACY_HOOK, 0o755)
    write(gd / "keystone-hooks/preserved/post-commit", LEGACY_HOOK, 0o755)
    other = Path(env["HOME"]) / "projects" / "demo-repo"  # another repository under HOME
    git(env, tmp_path, "init", "-q", str(other))
    write(other / ".git/hooks/post-commit", LFS_LEGACY_HOOK, 0o755)
    optin = Path(env["HOME"]) / "optin"
    git(env, tmp_path, "init", "-q", str(optin))
    shutil.copy2(REPO / "hooks/git-hooks/post-commit-auto-push", optin / ".git/hooks/post-commit")
    assert land(env, home, "--state").strip() == "upgraded"
    notice = land(env, home)
    assert notice.count("\n") == 1 and notice.startswith("Harness landing: P7 landed on this home")
    assert "3 legacy auto-push hook(s) renamed aside" in notice
    for path in (gd / "hooks/post-commit", gd / "keystone-hooks/preserved/post-commit",
                 other / ".git/hooks/post-commit"):
        assert "GIT_AUTO_PUSH:-1" in Path(str(path) + ".auto-push-disabled").read_text()
        assert not path.exists() or "GIT_AUTO_PUSH:-1" not in path.read_text()
    if shutil.which("git-lfs"):  # the combined hook carried the repository's LFS step
        assert "(LFS hooks restored in 1)" in notice
        assert "git lfs post-commit" in (other / ".git/hooks/post-commit").read_text()
    assert (optin / ".git/hooks/post-commit").read_bytes() == \
        (REPO / "hooks/git-hooks/post-commit-auto-push").read_bytes()
    assert_landed(env, home)
    assert "GIT_AUTO_PUSH" not in overlay(home)["env"]
    log = landing_log(home)
    assert "result=landed" in log and str(home) not in log
    snapshot = {p: (home / p).read_bytes() for p in ("settings.json", "settings.machine.json",
                                                     "private-literals.txt")}
    config = git(env, home, "config", "--local", "--list").stdout
    write(home / "hooks/git-hooks/post-merge-example", "#!/bin/sh\n# an opt-in template\n")
    assert land(env, home, "--state").strip() == "landed"  # step 5 does not install it
    assert land(env, home) == ""  # landed: nothing to do, no notice, no log line
    assert landing_log(home) == log
    assert {p: (home / p).read_bytes() for p in snapshot} == snapshot
    assert git(env, home, "config", "--local", "--list").stdout == config


def test_auto_commit_relays_the_notice_as_its_last_line(tmp_path, env):
    home, rev = make_home(tmp_path, env)
    shutil.copy2(REPO / "hooks/auto-commit.sh", home / "hooks/auto-commit.sh")
    proc = run(["bash", str(home / "hooks/auto-commit.sh")], env, cwd=str(tmp_path), input="{}")
    last = json.loads(proc.stdout.strip().splitlines()[-1])
    assert last["systemMessage"].startswith("Harness landing: P7 landed on this home")
    proc = run(["bash", str(home / "hooks/auto-commit.sh")], env, cwd=str(tmp_path), input="{}")
    assert "systemMessage" not in proc.stdout  # landed: auto-commit's own output only


def test_stale_installed_hook_is_refreshed_by_step_5_alone(tmp_path, env):
    home, rev = make_home(tmp_path, env)
    land(env, home)
    snapshot = [(home / p).read_bytes() for p in ("settings.json", "settings.machine.json")]
    with open(home / "hooks/git-hooks/pre-commit", "a") as fh:
        fh.write("# stand-in change\n")
    assert land(env, home, "--state").strip() == "hooks"
    assert "reinstalled the git hooks" in land(env, home)
    assert "steps 5 done" in landing_log(home) and "result=hooks-refreshed" in landing_log(home)
    hooks = home / git(env, home, "rev-parse", "--git-path", "hooks").stdout.strip()
    assert (hooks / "pre-commit").read_bytes() == (home / "hooks/git-hooks/pre-commit").read_bytes()
    assert land(env, home, "--state").strip() == "landed" and land(env, home) == ""
    assert [(home / p).read_bytes() for p in ("settings.json", "settings.machine.json")] == snapshot


def test_a_missing_installed_hook_is_reinstalled_and_not_called_changed(tmp_path, env):
    """R1, R9 (review RQ-7's side note): an installed pre-commit that is gone is reinstalled by
    step 5 alone, and the notice says the hooks differed, not that their source changed."""
    home, rev = make_home(tmp_path, env)
    land(env, home)
    hooks = home / git(env, home, "rev-parse", "--git-path", "hooks").stdout.strip()
    (hooks / "pre-commit").unlink()
    assert land(env, home, "--state").strip() == "hooks"
    assert land(env, home) == "Harness landing: init step 5 reinstalled the git hooks that differed " \
        "from hooks/git-hooks/.\n"
    assert (hooks / "pre-commit").read_bytes() == (home / "hooks/git-hooks/pre-commit").read_bytes()


def test_global_hooks_path_gives_one_notice_then_counts_as_landed(tmp_path, env):
    home, rev = make_home(tmp_path, env)
    shared = tmp_path / "shared-hooks"
    shared.mkdir()
    git(env, home, "config", "--global", "core.hooksPath", str(shared))
    notice = land(env, home)
    assert "pre-commit hook not installed: core.hooksPath comes from the global git config" in notice
    assert "pre-commit hook installed" not in notice and not (shared / "pre-commit").exists()
    assert land(env, home, "--state").strip() == "landed"
    assert land(env, home) == ""


@pytest.mark.parametrize("kind", ["directory", "dangling-symlink"])
def test_a_failed_step_is_a_notice_and_retried(tmp_path, env, kind):
    home, rev = make_home(tmp_path, env)
    target = home / "settings.machine.json"
    if kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(tmp_path / "nowhere")
    for _ in range(2):  # every turn end until it can land, never a claim of landed
        notice = land(env, home)
        assert notice.startswith("Harness landing failed at the overlay step") and "landed" not in notice
        assert land(env, home, "--state").strip() == "upgraded"
    shutil.rmtree(target) if kind == "directory" else target.unlink()
    assert "P7 landed" in land(env, home)
    assert_landed(env, home)


@pytest.mark.parametrize("step", ["overlay", "steps"])
def test_a_failed_landing_names_what_it_did_before_the_failure(tmp_path, env, step):
    """R9 (review F2): the legacy hook a failed landing renamed aside is named in that Stop's
    notice; the next landing finds none to rename, so no later notice would name it."""
    home, rev = make_home(tmp_path, env)
    write(home / ".git/hooks/post-commit", LEGACY_HOOK, 0o755)
    if step == "overlay":
        (home / "settings.machine.json").symlink_to(tmp_path / "nowhere")
    else:  # init step 4 cannot create the protected-runtime file
        write(tmp_path / "blocker", "a file where a directory goes\n")
        env = dict(env, CLAUDE_PROTECTED_RUNTIME_FILE=str(tmp_path / "blocker" / "runtime.json"))
    notice = land(env, home)
    assert notice.startswith("Harness landing failed at %s" % ("the overlay step" if step ==
                                                                "overlay" else "init steps 3,4,5"))
    done = notice.split(" (done so far: ", 1)[1]
    assert "1 legacy auto-push hook(s) renamed aside" in done
    assert ("overlay migrated" in done) == (step == "steps")  # migrated once: said once
    assert (home / ".git/hooks/post-commit.auto-push-disabled").exists()


def test_lock_taken_lands_nothing(tmp_path, env):
    home, rev = make_home(tmp_path, env)
    import fcntl
    with open(home / ".git" / "claude-landing.lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        notice = land(env, home)
    assert notice.startswith("Harness landing: another session is landing this home")
    assert not (home / "settings.machine.json").exists()
    assert "result=skipped" in landing_log(home)


@pytest.mark.skipif(not os.path.isdir("/proc/self") or shutil.which("pgrep") is None,
                    reason="needs /proc and pgrep")
def test_stale_daemon_restarts_with_its_own_env_and_without_the_lock(tmp_path, env):
    """R8: a git-fswatch.sh daemon older than the current script is restarted with its own
    environment (never the session's GIT_AUTO_PUSH), detached and not holding the landing lock."""
    home, rev = make_home(tmp_path, env)
    daemon = home / "hooks/git-fswatch.sh"
    write(daemon, '#!/bin/bash\ncd "$1" || exit 1\ntrap "exit 0" TERM\nwhile :; do sleep 1; done\n', 0o755)
    started = subprocess.Popen(["bash", str(daemon), str(home)], env=dict(
        env, DEMO_DAEMON_SETTING="7"), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        time.sleep(1.2)
        later = time.time() + 2
        os.utime(daemon, (later, later))  # the current script is newer than the running one
        (home / ".git" / "index.lock").write_text("")  # the daemon in its git work: the landing
        notice = land(env, home)                        # waits, and nothing is migrated yet
        assert notice.startswith("Harness landing waits: a stale git-fswatch daemon")
        assert not (home / "settings.machine.json").exists() and started.poll() is None
        assert land(env, home, "--state").strip() == "upgraded"
        (home / ".git" / "index.lock").unlink()
        notice = run(["bash", str(home / "scripts/install/land")], dict(env, GIT_AUTO_PUSH="1"),
                     cwd=str(home)).stdout
        assert "1 stale git-fswatch daemon(s) restarted" in notice
        started.wait(timeout=10)
        new = [p for p in run(["pgrep", "-f", "%s %s" % (daemon, home)], env, check=False).stdout.split()
               if int(p) != started.pid]
        assert len(new) == 1
        environ = Path("/proc/%s/environ" % new[0]).read_bytes().split(b"\0")
        assert b"DEMO_DAEMON_SETTING=7" in environ and not [e for e in environ if e.startswith(b"GIT_AUTO_PUSH=")]
        import fcntl
        with open(home / ".git" / "claude-landing.lock", "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the new daemon does not hold it
    finally:
        subprocess.run(["pkill", "-f", "%s %s" % (daemon, home)], check=False)
        if started.poll() is None:
            started.kill()


DAEMON = '#!/bin/bash\ncd "$1" || exit 1\ntrap "exit 0" TERM\nwhile :; do sleep 1; done\n'
needs_proc = pytest.mark.skipif(not os.path.isdir("/proc/self") or shutil.which("pgrep") is None,
                                reason="needs /proc and pgrep")


def stale_daemons(env, home, *watches, script=DAEMON, **extra):
    """Stand-ins for home's git-fswatch.sh running on each watch, started before the current
    daemon code: the script's mtime is set between their start and now, 2.5 s away from both
    (/proc's boot time has whole seconds)."""
    daemon = home / "hooks/git-fswatch.sh"
    write(daemon, script, 0o755)
    procs = [subprocess.Popen(["bash", str(daemon), str(watch)], env=dict(env, **extra),
                              cwd=str(watch), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, start_new_session=True) for watch in watches]
    time.sleep(5)
    then = time.time() - 2.5
    os.utime(daemon, (then, then))
    return procs


def stale_daemon(env, home, watch, **extra):
    return stale_daemons(env, home, watch, **extra)[0]


def daemons_of(env, home, watch):
    pattern = "%s %s$" % (home / "hooks/git-fswatch.sh", watch)
    return [int(p) for p in run(["pgrep", "-f", pattern], env, check=False).stdout.split()]


def kill_daemons(home, *procs):
    subprocess.run(["pkill", "-KILL", "-f", str(home / "hooks/git-fswatch.sh")], check=False)
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


@needs_proc
@pytest.mark.parametrize("session, kept", [({"CLAUDECODE": "1"}, False),
                                           ({"CLAUDE_PROJECT_DIR": "/opt/demo/proj"}, False),
                                           ({"CLAUDECODE": "1", "CLAUDE_HOME": "/opt/demo/h"}, True),
                                           ({}, True)],
                         ids=["session", "session-project-dir", "post-landing-session", "shell"])
def test_a_daemon_a_session_started_loses_that_sessions_push_switch(tmp_path, env, session, kept):
    """R8 with R7 and D1: a daemon that a session started before the landing (a Claude Code
    variable, no CLAUDE_HOME) is restarted without its GIT_AUTO_PUSH; any other daemon keeps its
    own environment, the switch included (a human's own export for fswatch)."""
    home, rev = make_home(tmp_path, env)
    old = stale_daemon(env, home, home, GIT_AUTO_PUSH="1", **session)
    try:
        assert "1 stale git-fswatch daemon(s) restarted" in land(env, home)
        old.wait(timeout=10)
        new = daemons_of(env, home, home)
        assert len(new) == 1
        environ = Path("/proc/%d/environ" % new[0]).read_bytes().split(b"\0")
        assert (b"GIT_AUTO_PUSH=1" in environ) == kept
        assert all(("%s=%s" % kv).encode() in environ for kv in session.items())
    finally:
        kill_daemons(home, old)


@needs_proc
@pytest.mark.parametrize("age", [0, 600], ids=["fresh-lock", "left-over-lock"])
def test_a_busy_daemon_in_another_repository_does_not_hold_the_landing(tmp_path, env, age):
    """R8: only a stale daemon on the harness home holds the landing while it is in its git work;
    one in another repository is left running (counted) and the home lands. A git lock older than
    a minute was left by a git that is gone: no git work, so that daemon is restarted."""
    home, rev = make_home(tmp_path, env)
    plain = Path(env["HOME"]) / "repos" / "plain"
    git(env, tmp_path, "init", "-q", str(plain))
    lock = plain / ".git" / "index.lock"
    lock.write_text("")
    os.utime(lock, (time.time() - age, time.time() - age))
    old = stale_daemon(env, home, plain)
    try:
        notice = land(env, home)
        assert notice.startswith("Harness landing: P7 landed on this home")
        if age:
            assert "1 stale git-fswatch daemon(s) restarted" in notice
            old.wait(timeout=10)
        else:
            assert "1 stale git-fswatch daemon(s) left running: in the middle of their git work" \
                in notice and old.poll() is None
        assert "busy=%d busy-home=0" % (0 if age else 1) in landing_log(home)
        lock.unlink(missing_ok=True)  # its git work done: restarted at the next turn end
        restarted = "Harness landing: 1 stale git-fswatch daemon(s) restarted.\n"
        assert land(env, home) == ("" if age else restarted)
        old.wait(timeout=10)
        assert len(daemons_of(env, home, plain)) == 1
    finally:
        kill_daemons(home, old)


@needs_proc
def test_daemon_restarts_stop_at_the_time_budget_and_go_on_at_the_next_turn_end(tmp_path, env):
    """R1's 15 s bound: daemons that need the KILL after the TERM wait are restarted only while the
    landing is under 8 s; the rest wait for the next turn end, which restarts them."""
    home, rev = make_home(tmp_path, env)
    watches = [Path(env["HOME"]) / "repos" / ("r%d" % i) for i in range(3)]
    for watch in watches:
        git(env, tmp_path, "init", "-q", str(watch))
    olds = stale_daemons(env, home, *watches, script=DAEMON.replace('"exit 0" TERM', '"" TERM'))
    try:
        started = time.time()
        notice = land(env, home)
        assert time.time() - started < 15
        assert "2 stale git-fswatch daemon(s) restarted" in notice
        assert "1 stale git-fswatch daemon(s) left for a later turn end: the landing's time budget " \
            "is used" in notice
        assert land(env, home) == "Harness landing: 1 stale git-fswatch daemon(s) restarted.\n"
        for old in olds:
            old.wait(timeout=10)
        assert [len(daemons_of(env, home, watch)) for watch in watches] == [1, 1, 1]
    finally:
        kill_daemons(home, *olds)


@needs_proc
def test_a_daemon_left_running_is_restarted_at_a_later_turn_end(tmp_path, env):
    """R8: a stale daemon the landing left running (a rebase stopped in its repository) is tried
    again at later turn ends of the landed home, quietly, and restarted once it can be; a landed
    home whose daemons run the current code gets no notice and no log line."""
    home, rev = make_home(tmp_path, env)
    proj = Path(env["HOME"]) / "proj"
    git(env, tmp_path, "init", "-q", str(proj))
    (proj / ".git" / "rebase-merge").mkdir()
    old = stale_daemon(env, home, proj)
    try:
        notice = land(env, home)
        assert "P7 landed" in notice and "1 stale git-fswatch daemon(s) left running: a rebase " \
            "or merge is stopped in its repository" in notice
        log = landing_log(home)
        assert land(env, home) == "" and landing_log(home) == log and old.poll() is None
        (proj / ".git" / "rebase-merge").rmdir()
        assert land(env, home) == "Harness landing: 1 stale git-fswatch daemon(s) restarted.\n"
        old.wait(timeout=10)
        assert len(daemons_of(env, home, proj)) == 1
        log = landing_log(home)
        assert land(env, home) == "" and landing_log(home) == log
    finally:
        kill_daemons(home, old)


@needs_proc
def test_a_daemon_started_just_after_its_code_was_written_is_current(tmp_path, env):
    """R8 (review LH-4): a daemon's start is compared with its code's mtime in centiseconds, not
    in whole seconds (/proc/stat's btime is truncated): one started 0.4 s or more after the code
    was written, in a second that whole-second arithmetic makes the same, runs the current code
    and is not restarted. (One started before the write is: the other daemon tests.)"""
    home, rev = make_home(tmp_path, env)
    land(env, home)
    daemon = home / "hooks/git-fswatch.sh"
    write(daemon, DAEMON, 0o755)
    uptime = lambda: float(Path("/proc/uptime").read_text().split()[0])  # noqa: E731
    while not 0.4 <= uptime() % 1 < 0.6:  # the start's fraction of a second since boot
        time.sleep(0.01)
    proc = subprocess.Popen(["bash", str(daemon), str(home)], env=env, cwd=str(home),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        time.sleep(1)
        ticks = int(Path("/proc/%d/stat" % proc.pid).read_text().rsplit(") ", 1)[1].split()[19])
        btime = next(int(ln.split()[1]) for ln in Path("/proc/stat").read_text().splitlines()
                     if ln.startswith("btime "))
        whole = btime + ticks // os.sysconf("SC_CLK_TCK")  # the start, rounded down twice
        for path in (daemon, home / "hooks/lib/checkpoint-core.sh"):
            os.utime(path, (whole, whole))  # 0.4 s or more before the start
        assert land(env, home) == ""
        assert proc.poll() is None and daemons_of(env, home, home) == [proc.pid]
    finally:
        kill_daemons(home, proc)


@pytest.mark.skipif(not os.path.isdir("/proc/self"), reason="needs /proc")
def test_a_zombie_named_like_the_daemon_leaves_the_landing_at_exit_0(tmp_path, env):
    """R8, R9: an unreaped child that ran a script named git-fswatch.sh (state Z: an empty
    cmdline, still listed under /proc) is no daemon; the landing goes on and exits 0."""
    home, rev = make_home(tmp_path, env)
    write(tmp_path / "z" / "git-fswatch.sh", "#!/bin/bash\nexit 0\n", 0o755)
    zombie = subprocess.Popen([str(tmp_path / "z" / "git-fswatch.sh")])  # not waited for: a zombie
    try:
        deadline = time.time() + 10
        while Path("/proc/%d/stat" % zombie.pid).read_text().rsplit(") ", 1)[1][0] != "Z":
            assert time.time() < deadline
            time.sleep(0.05)
        proc = run(["bash", str(home / "scripts/install/land")], env, cwd=str(home), check=False)
        assert (proc.returncode, proc.stderr) == (0, "")
        assert proc.stdout.startswith("Harness landing: P7 landed on this home")
    finally:
        zombie.wait()


@needs_proc
def test_a_process_that_exits_during_the_daemon_scan_prints_nothing(tmp_path, env):
    """R9: a process listed by the /proc scan that is gone when its cmdline, stat or environ is
    read (short-lived processes, some of them named like the daemon) makes the landed home's check
    print nothing on stderr: the shell reports a failed input redirection before a later 2>/dev/null
    applies, so the redirection to /dev/null comes first."""
    home, rev = make_home(tmp_path, env)
    land(env, home)
    daemon = home / "hooks/git-fswatch.sh"  # newer than any process: each one named like it is a
    write(daemon, DAEMON, 0o755)            # stale candidate, read again by restart_daemons
    os.utime(daemon, (time.time() + 3600, time.time() + 3600))
    write(tmp_path / "z" / "git-fswatch.sh", "exit 0\n")  # gone within a few ms, or 0-30 ms:
    write(tmp_path / "y" / "git-fswatch.sh", "read -t 0.0$((RANDOM % 4)) <> <(:)\n")
    churn = [subprocess.Popen(["bash", "-c", "while :; do %s; done" % cmd], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for cmd in ("/bin/true", "bash %s" % (tmp_path / "z" / "git-fswatch.sh"),
                         "bash %s" % (tmp_path / "y" / "git-fswatch.sh"))]
    try:
        procs = [run(["bash", str(home / "scripts/install/land")], env, cwd=str(home), check=False)
                 for _ in range(40)]
    finally:
        for proc in churn:
            proc.kill()
            proc.wait()
    assert [(p.returncode, p.stderr) for p in procs if (p.returncode, p.stderr) != (0, "")] == []
    assert land(env, home, "--state").strip() == "landed"


# --------------------------------------------------------- R7: processes started before the landing

def r7_home(tmp_path, settings_env, raw=None):
    """A minimal harness home (the structural sentinels) whose settings.json env is given."""
    home = tmp_path / "r7"
    for rel in ("hooks/lib/claude_home.py", "hooks/lib/checkpoint-core.sh",
                "hooks/lib/harness_state_dir.sh"):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, home / rel)
    (home / "policies").mkdir()
    (home / "scripts").mkdir()
    (home / "settings.json").write_text(raw if raw is not None else json.dumps({"env": settings_env}))
    return home


@pytest.mark.parametrize("case, proc_env, settings, pushed", [
    ("pre-landing, rendered 0", {"CLAUDECODE": "1", "GIT_AUTO_PUSH": "1"}, {"GIT_AUTO_PUSH": "0"}, False),
    ("pre-landing, rendered 1", {"CLAUDE_PROJECT_DIR": "/x", "GIT_AUTO_PUSH": "0"}, {"GIT_AUTO_PUSH": "1"}, True),
    ("pre-landing, invalid settings", {"CLAUDECODE": "1", "GIT_AUTO_PUSH": "1"}, None, False),
    ("post-landing (CLAUDE_HOME)", {"CLAUDECODE": "1", "CLAUDE_HOME": "/x", "GIT_AUTO_PUSH": "1"},
     {"GIT_AUTO_PUSH": "0"}, True),
    ("non-Claude process", {"GIT_AUTO_PUSH": "1"}, {"GIT_AUTO_PUSH": "0"}, True),
    ("non-Claude process, unset", {}, {"GIT_AUTO_PUSH": "1"}, False),
])
def test_checkpoint_push_switch(tmp_path, env, case, proc_env, settings, pushed):
    home = r7_home(tmp_path, settings, raw="{ not json" if settings is None else None)
    repo, mark = tmp_path / "repo", tmp_path / "pushed"
    git(env, tmp_path, "init", "-q", str(repo))
    git(env, repo, "commit", "-q", "--allow-empty", "-m", "x")
    git(env, repo, "update-ref", "refs/checkpoints/master", "HEAD")
    git(env, repo, "remote", "add", "origin", str(tmp_path / "nowhere.git"))
    script = ('source "$1"; _checkpoint_push_worker() { echo pushed > "$MARK"; }; disown() { :; }; '
              '_checkpoint_rate_limited_push "$2" refs/checkpoints/master; wait')
    (tmp_path / "logs").mkdir()
    run(["bash", "-c", script, "x", str(home / "hooks/lib/checkpoint-core.sh"), str(repo)],
        dict(env, CHECKPOINT_PUSH_MIN_INTERVAL="0", CHECKPOINT_LOG_DIR=str(tmp_path / "logs"),
             MARK=str(mark), **proc_env))
    assert mark.exists() == pushed, case


def test_settings_env_rule(tmp_path, env):
    home = r7_home(tmp_path, {"CLAUDE_RESTART_ACCOUNTS_ROOT": "/opt/demo/accounts", "N": 1})
    code = ("import json, sys; sys.path.insert(0, sys.argv[1]); from lib import claude_home as c;"
            "print(json.dumps(c.settings_env('CLAUDE_RESTART_ACCOUNTS_ROOT', 'N', 'ABSENT')))")
    cmd = [sys.executable, "-c", code, str(home / "hooks")]
    assert json.loads(run(cmd, dict(env, CLAUDECODE="1")).stdout) == {
        "CLAUDE_RESTART_ACCOUNTS_ROOT": "/opt/demo/accounts"}  # strings only
    assert json.loads(run(cmd, dict(env, CLAUDECODE="1", CLAUDE_RESTART_ACCOUNTS_ROOT="")).stdout) == {}
    assert json.loads(run(cmd, dict(env, CLAUDECODE="1", CLAUDE_HOME="/x")).stdout) == {}
    assert json.loads(run(cmd, env).stdout) == {}  # not a Claude Code process
    (home / "settings.json").write_text("<<<<<<< conflict")
    assert json.loads(run(cmd, dict(env, CLAUDECODE="1")).stdout) == {}
    out = run([sys.executable, str(home / "hooks/lib/claude_home.py"), "env", "A"], env).stdout
    assert out == ""


def test_subagent_restart_reads_the_accounts_root_from_rendered_settings(tmp_path, env):
    home = r7_home(tmp_path, {"CLAUDE_RESTART_ACCOUNTS_ROOT": "/opt/demo/accounts"})
    shutil.rmtree(home / "hooks" / "lib")
    shutil.copytree(REPO / "hooks" / "lib", home / "hooks" / "lib",
                    ignore=shutil.ignore_patterns("__pycache__", "tests"))
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from lib import subagent_restart as r;"
            "print(r.ACCOUNTS_ROOT)")
    cmd = [sys.executable, "-c", code, str(home / "hooks")]
    assert run(cmd, dict(env, CLAUDECODE="1")).stdout.strip() == "/opt/demo/accounts"
    assert run(cmd, env).stdout.strip() == "None"  # outside Claude Code: env only
    assert run(cmd, dict(env, CLAUDECODE="1", CLAUDE_HOME=str(home))).stdout.strip() == "None"


@pytest.fixture(scope="module")
def safety_home(tmp_path_factory):
    home = tmp_path_factory.mktemp("safety") / "h"
    shutil.copytree(REPO / "hooks", home / "hooks", ignore=shutil.ignore_patterns(
        "__pycache__", "tests"))
    shutil.copytree(REPO / "policies", home / "policies")
    (home / "scripts").mkdir()
    return home


@pytest.mark.parametrize("case, proc_env, settings, blocked", [
    ("pre-landing", {"CLAUDECODE": "1"}, {"CLAUDE_HOME": "/x", "CLAUDE_HARD_BANNED_SCRIPTS": "demo-recovery"}, True),
    ("process env wins", {"CLAUDECODE": "1", "CLAUDE_HARD_BANNED_SCRIPTS": "other-name"},
     {"CLAUDE_HOME": "/x", "CLAUDE_HARD_BANNED_SCRIPTS": "demo-recovery"}, False),
    ("non-Claude process", {}, {"CLAUDE_HOME": "/x", "CLAUDE_HARD_BANNED_SCRIPTS": "demo-recovery"}, False),
    ("invalid settings", {"CLAUDECODE": "1"}, None, False),
])
def test_bash_safety_knobs_from_rendered_settings(safety_home, env, tmp_path, case, proc_env,
                                                   settings, blocked):
    raw = '{"env": {"CLAUDE_HOME": "/x", "CLAUDE_HARD_BANNED_SCRIPTS": "demo-recovery"' \
        if settings is None else json.dumps({"env": settings})
    (safety_home / "settings.json").write_text(raw)
    payload = json.dumps({"session_id": "t", "cwd": str(tmp_path), "tool_name": "Bash",
                          "tool_input": {"command": "bash demo-recovery.sh"}})
    proc = run(["bash", str(safety_home / "hooks/pretool-bash-safety.sh")],
               dict(env, CLAUDE_PYTHON_BIN=sys.executable, **proc_env), cwd=str(tmp_path),
               check=False, input=payload)
    assert (proc.returncode == 2 and "hard-banned script 'demo-recovery'" in proc.stderr) == blocked, \
        (case, proc.returncode, proc.stderr[-400:])
