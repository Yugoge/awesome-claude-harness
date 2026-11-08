"""D30: scripts/publish-public. The private repository keeps its whole history; the public one gets ONE
parentless commit holding the clean tree, then one commit per publish, made in a scratch repository
that borrows the private objects and gated by P8's engine (default mode, on a checkout of the tree)
and P11's guard (on the push itself). Each test builds, in the scratch HOME of tests.test_landing's env
fixture, two local bare remotes (private, public) and a private clone of a small synthetic tree whose
older commits hold stand-in values; every value is a stand-in."""
import json
import shutil
import time

import pytest

from tests.test_landing import REPO, env, git, run, write  # noqa: F401  (env: the scratch-home fixture)

NAME, MAIL, TOKEN = "Jane Standin", "jane.standin@example.invalid", "tok-standin-4711"
SHORT, LONG = "orbit-standin", "zeta-orbit-standin-vault"  # one listed literal inside another
ROWS = ("PUBLIC-CORE.md", "README.md", "policies/", "scripts/")
LEDGER = ("# Public core (stand-in)\n<!-- BEGIN:public-core-manifest -->\n| Path | Class | Why |\n|---|---|---|\n"
          + "".join(f"| `{p}` | `public-core` | stand-in |\n" for p in ROWS) + "<!-- END:public-core-manifest -->\n")
ALLOWLIST = {"self_exempt_paths": ["policies/public-core-residue-allowlist.v1.json", "scripts/check-public-core.sh"],
             "legitimate_classes": ["comment_or_narrative_doc"], "entries": []}
TOOLS = ("scripts/check-public-core.sh", "scripts/install/push-guard", "scripts/publish-public")


def snapshot(path):
    return {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in path.rglob("*")}


class Repo:
    def __init__(self, path, env):
        self.path, self.env = path, env

    def __call__(self, *args, check=True, **env):
        r = git(dict(self.env, **env), self.path, *args, check=check)
        return r.stdout.strip() if check else r

    def commit(self, name="README.md", text="clean\n", **env):
        write(self.path / name, text)
        self("add", "-A")
        self("commit", "-q", "-m", "c", **env)
        return self("rev-parse", "HEAD")

    def state(self):  # the refs and the object set
        return self("for-each-ref"), set(self("cat-file", "--batch-all-objects", "--batch-check=%(objectname)").split())

    def publish(self, *args, cwd=None, **env):
        """The identity is the clone's own config unless env overrides it; a publish writes nothing here
        and leaves no scratch behind."""
        base = {k: v for k, v in self.env.items() if not k.startswith(("GIT_AUTHOR", "GIT_COMMITTER"))}
        before = snapshot(self.path)
        r = run([str(self.path / "scripts/publish-public"), *args], dict(base, **env), cwd or self.path, False)
        assert snapshot(self.path) == before and not any((self.path.parent / "tmp").iterdir())
        return r


@pytest.fixture
def repos(tmp_path, env):
    env["TMPDIR"] = str(tmp_path / "tmp")
    (tmp_path / "tmp").mkdir()
    top, priv, pub = Repo(tmp_path, env), Repo(tmp_path / "priv", env), Repo(tmp_path / "public.git", env)
    for bare in ("private.git", "public.git"):
        top("init", "-q", "--bare", bare)
    top("init", "-q", "-b", "master", "priv")
    for rel in TOOLS:
        (priv.path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, priv.path / rel)
    write(priv.path / "PUBLIC-CORE.md", LEDGER)
    write(priv.path / "policies/public-core-residue-allowlist.v1.json", json.dumps(ALLOWLIST))
    write(priv.path / ".git/info/exclude", "/private-literals.txt\n")
    priv.commit("contacts.txt", f"{MAIL}\n{TOKEN}\n", GIT_AUTHOR_NAME=NAME, GIT_AUTHOR_EMAIL=MAIL)
    (priv.path / "contacts.txt").unlink()
    priv.commit()  # the stand-ins stay in the history only: the tip tree is clean
    write(priv.path / "private-literals.txt", f"# stand-ins\n{NAME}\n{MAIL}\n{TOKEN}\n")
    for key, value in (("user.name", "Pat Example"), ("user.email", "pat@example.invalid")):
        priv("config", key, value)
    priv("remote", "add", "origin", "../private.git")
    priv("remote", "add", "public", "../public.git")
    priv("push", "-q", "origin", "master")
    return priv, pub


def test_a_clean_tree_publishes_as_one_parentless_commit(repos):
    priv, pub = repos
    r = priv.publish("public", GIT_COMMITTER_DATE="@1000000000 +0000")  # a date override: the time is still now
    head, tree, src = pub("rev-parse", "main"), priv("rev-parse", "master^{tree}"), priv("rev-parse", "master")
    assert (r.returncode, r.stdout) == (0, f"publish-public: published {head} (tree {tree}, parent none) to the "
                                           "public main\n")
    assert pub("for-each-ref", "--format=%(refname)") == "refs/heads/main"
    assert pub("rev-list", "--parents", "main") == head  # one commit, no parent
    assert pub("rev-parse", "main^{tree}") == tree
    meta = pub("log", "-1", "--format=%an <%ae>|%cn <%ce>|%B", "main")
    assert meta == f"Pat Example <pat@example.invalid>|Pat Example <pat@example.invalid>|Publish {src}"
    assert abs(int(pub("log", "-1", "--format=%ct", "main")) - time.time()) < 600


@pytest.mark.parametrize("leak", ["content", "path", "identity"])
def test_a_stand_in_in_the_tree_or_the_identity_refuses_with_nothing_pushed(repos, leak):
    priv, pub = repos
    assert priv.publish("public").returncode == 0
    before = pub.state()
    priv.commit(*{"content": ("README.md", f"clean\nticket {TOKEN}\n"), "path": (f"{TOKEN}/a.txt",),
                  "identity": ("README.md", "cleaner\n")}[leak])
    r = priv.publish("public", **({"GIT_AUTHOR_NAME": NAME} if leak == "identity" else {}))
    assert (r.returncode, r.stdout) == (1, "") and r.stderr.splitlines()[-1].startswith("publish-public: REFUSED: ")
    assert {"content": "-> README.md:2", "path": "-> <path with private-literals.txt line 4> (path name)",
            "identity": "-> commit "}[leak] in r.stderr
    assert all(v not in r.stderr for v in (NAME, MAIL, TOKEN)) and pub.state() == before


@pytest.mark.parametrize("short_first", [True, False])
def test_a_literal_holding_another_is_masked_whole_in_either_list_order(repos, short_first):
    priv, pub = repos
    pair = (SHORT, LONG) if short_first else (LONG, SHORT)
    write(priv.path / "private-literals.txt", f"# stand-ins\n{NAME}\n{MAIL}\n{TOKEN}\n{pair[0]}\n{pair[1]}\n")
    priv.commit(f"{LONG}/a.txt")  # the engine echoes an unclassified top-level path by name
    r = priv.publish("public")
    assert (r.returncode, r.stdout) == (1, "") and "check-public-core.sh failed" in r.stderr.splitlines()[-2]
    assert f"\n    <private-literals.txt line {5 + pair.index(LONG)}>\n" in r.stderr
    assert not [v for v in (SHORT, LONG, *LONG.split(SHORT)) if v in r.stderr] and pub.state() == ("", set())


@pytest.mark.parametrize("case", ["publishes only", "initial commit", "direct edit", "merge"])
def test_a_public_main_holding_a_commit_the_script_did_not_make_is_refused(repos, tmp_path, case):
    priv, pub = repos
    if case != "initial commit":
        assert priv.publish("public").returncode == 0
    odd = None
    if case in ("initial commit", "direct edit"):  # made on the public side: a host's initial README, a web edit
        work = Repo(tmp_path / "pubwork", pub.env)
        Repo(tmp_path, pub.env)("init", "-q", "pubwork")
        if case == "direct edit":
            work("pull", "-q", "../public.git", "main")
        odd = work.commit("README.md", "# stand-in, made on the public side\n")
        work("push", "-q", "../public.git", "HEAD:main")
    if case == "merge":  # each message is the script's own form; the merge alone gives it away
        msg = f"Publish {priv('rev-parse', 'master')}"
        root = pub("commit-tree", "main^{tree}", "-m", msg)
        odd = pub("commit-tree", "main^{tree}", "-p", "main", "-p", root, "-m", msg)
        pub("update-ref", "refs/heads/main", odd)
    priv.commit("README.md", "clean, again\n")
    before = pub.state()
    r = priv.publish("public")
    if odd is None:  # a normal second publish
        assert r.returncode == 0 and len(pub("rev-list", "--parents", "main").splitlines()) == 2
        return
    assert (r.returncode, r.stdout) == (1, "") and pub.state() == before
    assert r.stderr == (f"publish-public: REFUSED: the public main holds commit {odd}, which this script did not make"
                        ' (a merge, or a message other than "Publish <full commit id>"): the public repository is'
                        " publish-only\n")


def test_each_later_publish_adds_one_commit_and_an_unchanged_tree_pushes_nothing(repos, tmp_path):
    priv, pub = repos
    assert priv.publish("public").returncode == 0
    first = pub("rev-parse", "main")
    priv("fetch", "-q", "public")  # its remote-tracking main reaches the public tip: still not private history
    priv.commit("README.md", "clean, again\n")
    assert priv.publish("public", cwd=priv.path / "policies").returncode == 0  # from a subdirectory
    second = pub("rev-parse", "main")
    assert pub("rev-list", "--parents", "main").splitlines() == [f"{second} {first}", first]
    assert pub("rev-parse", "main^{tree}") == priv("rev-parse", "master^{tree}")
    before = pub.state()
    r = priv.publish(str(tmp_path / "public.git"))  # by path this time
    assert r.returncode == 0 and r.stdout.startswith("publish-public: nothing to publish") and pub.state() == before


def test_the_public_repository_holds_no_object_of_the_private_history(repos, tmp_path):
    priv, pub = repos
    assert priv.publish("public").returncode == 0
    priv.commit("README.md", "clean, again\n")
    packets = tmp_path / "packets"  # nor is the public host offered a private commit when the tip is fetched
    assert priv.publish("public", GIT_TRACE_PACKET=str(packets)).returncode == 0
    assert "fetch> want " in packets.read_text()
    assert not [c for c in priv("rev-list", "--all").split() if f"have {c}" in packets.read_text()]
    held, commits = pub.state()[1], set(pub("rev-list", "main").split())
    published = set(pub("rev-list", "--objects", "--no-object-names", "main").split())
    private = set(priv("rev-list", "--objects", "--no-object-names", "--all").split())
    assert held == published and len(commits) == 2  # every public object is reachable from the publish commits
    assert not held & set(priv("rev-list", "--all").split()) and not held & (private - (published - commits))
    assert priv("rev-parse", "master~2:contacts.txt") not in held


@pytest.mark.parametrize("case", ["no list", "empty list", "private main", "no source", "no public", "itself"])
def test_a_publish_that_cannot_be_trusted_is_refused_with_nothing_pushed(repos, tmp_path, case):
    """A missing or empty list fails closed: the guard's strict mode, the list's one reader and decider."""
    priv, pub = repos
    if case == "no list":
        (priv.path / "private-literals.txt").unlink()
    if case == "empty list":
        write(priv.path / "private-literals.txt", "# none yet\n \t\n")
    if case == "private main":
        priv("push", "-q", "public", "master:main")
    before = pub.state()
    r = priv.publish(*{"no source": ("--source", "nowhere", "public"), "itself": (".",),
                       "no public": (str(tmp_path / "nowhere.git"),)}.get(case, ("public",)))
    why = {"no list": "strict: private-literals.txt is missing or lists no literal",
           "empty list": "strict: private-literals.txt is missing or lists no literal",
           "private main": "this repository's refs reach", "no source": "cannot read the source commit",
           "no public": "cannot read the public repository", "itself": "is this repository"}[case]
    assert (r.returncode, r.stdout) == (1, "") and why in r.stderr
    assert r.stderr.splitlines()[-1].startswith("publish-public: REFUSED: ") and pub.state() == before


def test_a_dry_run_or_a_usage_error_pushes_nothing(repos):
    priv, pub = repos
    for args in ((), ("--bogus", "public"), ("public", "extra"), ("--source",)):
        assert priv.publish(*args).returncode == 2
    r = priv.publish("--dry-run", "public")
    assert r.returncode == 0 and r.stdout.startswith("publish-public: dry run: would push ")
    assert "parent none) to the public main; nothing pushed" in r.stdout
    assert pub.state() == ("", set())
