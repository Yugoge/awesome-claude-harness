"""P11: the pre-push guard. hooks/git-hooks/pre-push, installed in a home's hooks directory, runs
scripts/install/push-guard: P8's engine with the home's list over every object a push sends, a hit
refused naming the object, never the value. Histories are built with git alone, in the scratch
HOME of tests.test_landing's env fixture; every value is a stand-in."""
import shutil

import pytest

from tests.test_landing import REPO, env, git, run, write  # noqa: F401  (env: the scratch-home fixture)

NOREPLY, RESERVED, LIT = "123+demo@users.noreply.github.com", "demo@example.invalid", "acct-test-123"
LISTED = (LIT, "/opt/demo/bin/tool", NOREPLY, RESERVED)  # every identity here is NOREPLY: listed, a no-reply form


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
    env.update(GIT_AUTHOR_NAME="Demo", GIT_AUTHOR_EMAIL=NOREPLY, GIT_COMMITTER_EMAIL=NOREPLY)
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


@pytest.mark.parametrize("field", ["blob", "path", "author", "committer", "message", "tag", "mail blob", "mail"])
def test_a_listed_literal_in_any_field_refuses_the_push_naming_the_object(home, field):
    home.commit()
    home("push", "-q", "origin", "master")  # no list yet: the push proceeds
    home.listing(*LISTED)
    head = home.commit(**{"name": "g.txt", **{
        "blob": {"text": f"ticket {LIT}\n"}, "path": {"name": f"{LIT}/g.txt"}, "author": {"GIT_AUTHOR_NAME": LIT},
        "committer": {"GIT_COMMITTER_EMAIL": f"{LIT}@example.invalid"}, "message": {"msg": "see /opt/demo/bin/tool"},
        "tag": {}, "mail blob": {"text": f"to {RESERVED}\n"}, "mail": {"GIT_AUTHOR_EMAIL": RESERVED}}[field]})
    if field == "tag":
        home("tag", "-a", "v1", "-m", f"release {LIT}")
    spec = {"blob": "HEAD:g.txt", "mail blob": "HEAD:g.txt", "path": "HEAD^{tree}", "tag": "v1"}.get(field, "HEAD")
    r = home("push", "origin", "refs/tags/v1" if field == "tag" else "master", check=False)
    assert r.returncode == 1 and f"-> {home('cat-file', '-t', spec)} {home('rev-parse', spec)}:" in r.stderr
    assert "pre-push: push REFUSED by the private-literal guard" in r.stderr
    assert LIT not in r.stderr and "/opt/demo/bin/tool" not in r.stderr and RESERVED not in r.stderr
    assert home.remote("master") != head and not home.remote("v1")


def test_only_the_objects_the_push_sends_are_scanned(home):
    home.listing()  # an empty list: nothing scanned
    home.commit(text=f"ticket {LIT}\n")  # on the remote: no push below scans it again
    home("push", "-q", "origin", "master", "master:gone")
    home.listing(*LISTED)  # the public address every commit carries is listed as well
    home.commit("g.txt", msg=f"Co-Authored-By: Demo <{NOREPLY}>")
    assert home("push", "origin", "master", check=False).returncode == 0  # the new objects only
    assert home("push", "origin", ":gone", check=False).returncode == 0  # a deletion sends nothing
    head = home.commit("h.txt", GIT_COMMITTER_NAME=LIT)  # a listed identity that is not public
    r = home("push", "origin", "master", check=False)
    assert r.returncode == 1 and f"-> commit {head}:" in r.stderr and home.remote("master") != head
    # A branch name new to the remote: what the remote's branches and tags reach is left out.
    home("checkout", "-q", "-b", "side", "master~")
    home.commit("i.txt", "side\n")
    assert home("push", "origin", "side", check=False).returncode == 0
    r = home("push", "origin", "master:refs/heads/new", check=False)
    assert r.returncode == 1 and f"-> commit {head}:" in r.stderr and "-> blob" not in r.stderr


def test_a_stale_remote_tracking_ref_does_not_hide_the_history_a_push_sends(home, tmp_path):
    home.commit()
    old = home.commit("b.txt", f"ticket {LIT}\n")
    home.commit("c.txt")
    home("push", "-q", "origin", "master")
    up = Repo(tmp_path / "up", home.env)  # elsewhere: the upstream rewritten to one new root, b.txt gone
    Repo(tmp_path, home.env)("clone", "-q", "origin.git", "up")
    up("rm", "-q", "b.txt")
    up("push", "-q", "-f", "origin", up("commit-tree", up("write-tree"), "-m", "rewritten") + ":refs/heads/master")
    home.listing(*LISTED)  # not pulled: origin/master is the old tip, the remote's new one is not held
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


def test_a_new_ref_whose_remote_cannot_be_read_refuses_in_one_line_naming_the_step(home):
    home.listing(*LISTED)
    line = f"refs/heads/master {home.commit()} refs/heads/master {'0' * 40}\n"
    r = run(["bash", ".git/hooks/pre-push", "origin", "../nowhere.git"], home.env, home.path, False, input=line)
    assert (r.returncode, r.stderr) == (1, "pre-push: push REFUSED by the private-literal guard: "
                                           "cannot read the remote's branches and tags\n")


def test_a_displaced_pre_push_runs_after_the_guard_with_the_same_input(home, tmp_path):
    log = tmp_path / "local.log"
    write(home.path / ".git/hooks/pre-push.local", f'#!/bin/sh\necho "$@" > {log}\ncat >> {log}\n', 0o755)
    home.listing(*LISTED)
    head = home.commit()
    assert home("push", "origin", "master", check=False).returncode == 0
    assert log.read_text() == f"origin ../origin.git\nrefs/heads/master {head} refs/heads/master {'0' * 40}\n"


@pytest.mark.parametrize("listing", ["no list", "empty list"])
def test_strict_fails_closed_on_a_missing_or_empty_list_naming_the_step(home, listing):
    """--strict, the publish's mode (scripts/publish-public, D30): the guard, the list's one reader and
    decider, refuses where an ordinary push would scan nothing."""
    if listing == "empty list":
        write(home.path / "private-literals.txt", "# none yet\n \t\n")
    line = f"refs/heads/main {home.commit()} refs/heads/main {'0' * 40}\n"
    plain = run(["bash", "scripts/install/push-guard", "origin", "../origin.git"], home.env, home.path, False, input=line)
    assert plain.returncode == 0
    r = run(["bash", "scripts/install/push-guard", "--strict", "origin", "../origin.git"], home.env, home.path, False,
            input=line)
    assert (r.returncode, r.stderr) == (1, "pre-push: push REFUSED by the private-literal guard: "
                                           "strict: private-literals.txt is missing or lists no literal\n")


def test_strict_runs_the_engine_on_the_pushed_tree_naming_the_step_and_masking_the_report(home):
    home.listing(*LISTED)
    head = home.commit(f"{LIT}-dir/a.txt")  # a tree the engine's default mode refuses (no ledger), its path listed
    line = f"refs/heads/main {head} refs/heads/main {'0' * 40}\n"
    r = run(["bash", "scripts/install/push-guard", "--strict", "origin", "../origin.git"], home.env, home.path, False,
            input=line)
    tree = home("rev-parse", "HEAD^{tree}")
    assert r.returncode == 1 and r.stderr.splitlines()[-1] == (
        "pre-push: push REFUSED by the private-literal guard: strict: scripts/check-public-core.sh failed on tree "
        f"{tree} (files named above)")
    assert LIT not in r.stderr and not home.remote("main")


def guard(home, line, *mode):
    return run(["bash", "scripts/install/push-guard", *mode, "origin", "../origin.git"], home.env, home.path, False,
               input=line)


@pytest.mark.parametrize("mode", [(), ("--strict",)])
def test_a_pushed_tip_this_repository_does_not_hold_refuses_naming_the_step(home, mode):
    """After an error nothing is clean: a pushed object that cannot be listed stops the push. Only the remote
    tips (--not) may be absent, a stale home lacking them."""
    home.listing(*LISTED)
    home.commit()
    gone = "0123456789abcdef" * 2 + "01234567"
    assert home("cat-file", "-e", gone, check=False).returncode != 0
    r = guard(home, f"refs/heads/main {gone} refs/heads/main {'0' * 40}\n", *mode)
    assert (r.returncode, r.stderr) == (1, "pre-push: push REFUSED by the private-literal guard: "
                                           "cannot list the objects this push sends: a pushed tip is not in this "
                                           "repository\n")


def test_strict_refuses_a_pushed_tip_whose_tree_cannot_be_looked_up_naming_the_step(home):
    home.listing(*LISTED)
    home.commit()
    blob = home("rev-parse", "HEAD:f.txt")  # held, sent, but it has no tree: no checkout to run the engine on
    line = f"refs/tags/b {blob} refs/tags/b {'0' * 40}\n"
    assert guard(home, line).returncode == 0  # an ordinary push scans the blob it sends: clean
    r = guard(home, line, "--strict")
    assert (r.returncode, r.stderr) == (1, "pre-push: push REFUSED by the private-literal guard: "
                                           "strict: cannot look up the tree of a pushed tip\n")


def test_every_line_of_the_input_is_read_or_the_push_refused(home):
    home.listing(*LISTED)
    head = home.commit(text=f"ticket {LIT}\n")
    r = guard(home, f"refs/heads/master {head} refs/heads/master {'0' * 40}")  # its last line unterminated: scanned
    assert r.returncode == 1 and f"-> blob {home('rev-parse', 'HEAD:f.txt')}:1" in r.stderr and LIT not in r.stderr
    for mode in ((), ("--strict",)):  # a line naming no local object is no deletion
        r = guard(home, "refs/heads/master\n", *mode)
        assert (r.returncode, r.stderr) == (1, "pre-push: push REFUSED by the private-literal guard: "
                                               "cannot read the push's input: a line names no local object\n")
