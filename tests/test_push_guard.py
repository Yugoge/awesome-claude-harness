"""P11: the pre-push guard. hooks/git-hooks/pre-push, installed in a home's hooks directory, runs
scripts/install/push-guard: P8's engine with the home's list over every object a push sends, a hit
refused naming the object, never the value. Histories are built with git alone, in the scratch
HOME of tests.test_landing's env fixture; every value is a stand-in."""
import shutil

import pytest

from tests.test_landing import REPO, env, git, write  # noqa: F401  (env: the scratch-home fixture)

NOREPLY, RESERVED, LIT = "123+demo@users.noreply.github.com", "demo@example.invalid", "acct-test-123"
LISTED = (LIT, "/opt/demo/bin/tool", NOREPLY, RESERVED)  # every commit here carries the last two


class Repo:
    def __init__(self, path, env):
        self.path, self.env = path, env

    def __call__(self, *args, check=True, **env):
        r = git(dict(self.env, **env), self.path, *args, check=check)
        return r.stdout.strip() if check else r

    def commit(self, name="f.txt", text="clean\n", msg="c", **env):
        write(self.path / name, text)
        self("add", "-A")
        self("commit", "-q", "-m", msg, **env)
        return self("rev-parse", "HEAD")

    def listing(self, *values):
        write(self.path / "private-literals.txt", "".join(v + "\n" for v in values))

    def remote(self, ref):
        return self("--git-dir=../origin.git", "rev-parse", "-q", "--verify", ref, check=False).stdout


@pytest.fixture
def home(tmp_path, env):
    env.update(GIT_AUTHOR_NAME="Demo", GIT_AUTHOR_EMAIL=NOREPLY, GIT_COMMITTER_EMAIL=RESERVED)
    h, top = Repo(tmp_path / "home", env), Repo(tmp_path, env)
    top("init", "-q", "--bare", "origin.git")
    top("init", "-q", "-b", "master", "home")
    for rel in ("scripts/check-public-core.sh", "scripts/install/push-guard", "hooks/git-hooks/pre-push"):
        (h.path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, h.path / rel)
    shutil.copy2(REPO / "hooks/git-hooks/pre-push", h.path / ".git/hooks/pre-push")
    write(h.path / ".git/info/exclude", "/scripts/\n/hooks/\n/private-literals.txt\n")
    h("remote", "add", "origin", "../origin.git")
    return h


@pytest.mark.parametrize("field", ["blob", "path", "author", "committer", "message", "tag"])
def test_a_listed_literal_in_any_field_refuses_the_push_naming_the_object(home, field):
    home.commit()
    home("push", "-q", "origin", "master")  # no list yet: the push proceeds
    home.listing(*LISTED)
    head = home.commit(**{"name": "g.txt", **{
        "blob": {"text": f"ticket {LIT}\n"}, "path": {"name": f"{LIT}/g.txt"}, "author": {"GIT_AUTHOR_NAME": LIT},
        "committer": {"GIT_COMMITTER_EMAIL": f"{LIT}@example.invalid"}, "message": {"msg": "see /opt/demo/bin/tool"},
        "tag": {}}[field]})
    if field == "tag":
        home("tag", "-a", "v1", "-m", f"release {LIT}")
    spec = {"blob": "HEAD:g.txt", "path": "HEAD^{tree}", "tag": "v1"}.get(field, "HEAD")
    r = home("push", "origin", "refs/tags/v1" if field == "tag" else "master", check=False)
    assert r.returncode == 1 and f"-> {home('cat-file', '-t', spec)} {home('rev-parse', spec)}:" in r.stderr
    assert "pre-push: push REFUSED by the private-literal guard" in r.stderr
    assert LIT not in r.stderr and "/opt/demo/bin/tool" not in r.stderr
    assert home.remote("master") != head and not home.remote("v1")


def test_only_the_objects_the_push_sends_are_scanned(home):
    home.listing()  # an empty list: nothing scanned
    old = home.commit(text=f"ticket {LIT}\n")
    home("push", "-q", "origin", "master", "master:gone")
    home.listing(*LISTED)  # the public addresses every commit carries are listed as well
    home.commit("g.txt", msg=f"Co-Authored-By: Demo <{NOREPLY}>")
    assert home("push", "origin", "master", check=False).returncode == 0  # the new objects only
    assert home("push", "origin", ":gone", check=False).returncode == 0  # a deletion sends nothing
    head = home.commit("h.txt", GIT_COMMITTER_NAME=LIT)  # a listed identity that is not public
    r = home("push", "origin", "master", check=False)
    assert r.returncode == 1 and f"-> commit {head}:" in r.stderr and home.remote("master") != head
    # A branch name new to the remote: no remote value on the input, so everything it reaches.
    r = home("push", "origin", "master~:refs/heads/new", check=False)
    assert r.returncode == 1 and f"-> blob {home('rev-parse', old + ':f.txt')}:1" in r.stderr


def test_a_stale_remote_tracking_ref_does_not_hide_the_history_a_push_sends(home, tmp_path):
    home.commit()
    old = home.commit("b.txt", f"ticket {LIT}\n")
    home.commit("c.txt")
    home("push", "-q", "origin", "master")
    up = Repo(tmp_path / "up", home.env)  # elsewhere: the upstream rewritten to one new root, b.txt gone
    Repo(tmp_path, home.env)("clone", "-q", "origin.git", "up")
    up("rm", "-q", "b.txt")
    up("push", "-q", "-f", "origin", up("commit-tree", up("write-tree"), "-m", "rewritten") + ":refs/heads/master")
    home.listing(*LISTED)  # not pulled: origin/master is still the old tip
    home("checkout", "-q", "-b", "feature")
    home.commit("d.txt")
    r = home("push", "origin", "feature", check=False)
    assert r.returncode == 1 and f"-> blob {home('rev-parse', old + ':b.txt')}:1" in r.stderr
    assert not home.remote("feature")


@pytest.mark.parametrize("gone", ["scripts/check-public-core.sh", "scripts/install/push-guard"])
def test_a_scan_that_cannot_run_refuses_in_one_line_naming_the_step(home, gone):
    home.listing(*LISTED)
    home.commit()
    (home.path / gone).unlink()
    r = home("push", "origin", "master", check=False)
    assert r.returncode == 1 and r.stderr.startswith("pre-push: push REFUSED") \
        and r.stderr.splitlines()[0].endswith(f"{gone} is missing") and not home.remote("master")


def test_a_displaced_pre_push_runs_after_the_guard_with_the_same_input(home, tmp_path):
    log = tmp_path / "local.log"
    write(home.path / ".git/hooks/pre-push.local", f'#!/bin/sh\necho "$@" > {log}\ncat >> {log}\n', 0o755)
    home.listing(*LISTED)
    head = home.commit()
    assert home("push", "origin", "master", check=False).returncode == 0
    assert log.read_text() == f"origin ../origin.git\nrefs/heads/master {head} refs/heads/master {'0' * 40}\n"
