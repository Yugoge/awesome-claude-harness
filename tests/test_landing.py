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


# ------------------------------------------------------- R2: the states a pull path leaves behind

def pulled_home(tmp_path, env, live_edit, other=None):
    """A pre-P7 home (at rev, with a live edit) pulling P7 the way fswatch does: stash, pull
    --rebase, pop. Returns (home, rev, pop result)."""
    origin, rev = make_home(tmp_path, env, name="origin")
    home = tmp_path / "harness"
    git(env, tmp_path, "clone", "-q", str(origin), str(home))
    home = Path(os.path.realpath(home))
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


def test_other_unmerged_paths_stay_and_an_empty_unstage_list_resets_nothing(tmp_path, env):
    """An unmerged file the owner edited stays unmerged (counted); with nothing the pop staged,
    no `git reset` runs (without a pathspec it would reset the whole index)."""
    origin, rev = make_home(tmp_path, env, name="origin")
    home = tmp_path / "harness"
    git(env, tmp_path, "clone", "-q", str(origin), str(home))
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
    home = tmp_path / "harness"
    git(env, tmp_path, "clone", "-q", str(origin), str(home))
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
    home = tmp_path / "harness"
    git(env, tmp_path, "clone", "-q", str(origin), str(home))
    home = Path(os.path.realpath(home))
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
    assert "2 file(s) a pull left conflicted taken from upstream (2 doc-sync)" in notice
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


# ------------------------------------------------------------------------------ R5: seeding

def test_seeding_sources_filters_and_no_value_printed(tmp_path, env):
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
    assert lines == ["demo-web-dev", "demo-api-dev", "demo-recovery", "demo-bot@example.invalid",
                     "acct-test-123", "/opt/demo/bin/graphify",
                     "/opt/demo/.claude/scripts/demo-tool.sh", "/opt/demo/bin/helper",
                     "/opt/demo/notes", "demo@example.invalid", "git@example.invalid:demo-owner",
                     "/home/demo-user", "demo-private-proj", "/opt/demo/ws-marker"]
    assert stat.S_IMODE((home / "private-literals.txt").stat().st_mode) == 0o600
    shown = notice + landing_log(home)
    assert "seeded with 14 value(s)" in notice
    assert "overlay-env=6 permission-paths=3 git-e-mail=1 check-markers=4" in shown
    assert not [v for v in lines if v in shown]


def test_seeding_never_rewrites_a_list_that_has_lines(tmp_path, env):
    home, rev = make_home(tmp_path, env)
    write(home / "private-literals.txt", "# my list\n\n")  # no literal yet: appended below
    land(env, home)
    text = (home / "private-literals.txt").read_text()
    assert text.startswith("# my list\n\n") and len(text.splitlines()) > 2
    home2, _ = make_home(tmp_path, env, name="h2")
    write(home2 / "private-literals.txt", "acct-test-999\n")
    before = (home2 / "private-literals.txt").read_bytes()
    assert "seeded" not in land(env, home2)
    assert (home2 / "private-literals.txt").read_bytes() == before


# ------------------------------------------------------- R1, R4, R6, R9: the landing end to end

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
