"""P11 fact 9: the private-literal list's extra seeding sources, the harness home's own git history.

render-settings' seeding (the list's one producer, P7b R5) also takes, from every ref (branches,
remote-tracking refs, tags, every stash entry, refs/backups/*, refs/checkpoints/*), the e-mail and
the name of each author and committer whose e-mail is not public, and each e-mail address outside
P11 A2's public allowlist in a commit or tag message or a blob. An absent or empty list gets every
source at once; a list with lines keeps them and gets the history values it lacks appended, when
the landing reinstalls the git hooks ("hooks" state) or lands an upgraded home.

Homes are P7b's temporary test homes (tests/test_landing.py); histories are built with git alone
and never on a branch name. Stand-ins only: acct-test-123, demo@example.invalid, /opt/demo/bin/tool.
An address outside the public classes is joined at run time, so no tracked line holds one.
"""
import re
import shutil
import stat

import pytest

from tests.test_landing import (  # noqa: F401
    assert_landed, env, git, land, landing_log, make_home, run, write)

STAND_IN = "acct-test-123"
DOMAIN = "demo" + ".internal"  # a private-use name outside A2's allowlist
ADDED = "value(s) from the home's git history added to private-literals.txt"
REFRESHED = ("Harness landing: init step 5 reinstalled the git hooks that differed from "
             "hooks/git-hooks/")


def private(tag=""):
    """A stand-in address outside the public classes: acct-test-123[+tag] at DOMAIN."""
    return STAND_IN + ("+" + tag if tag else "") + "@" + DOMAIN


def commit(env, home, files, message, ref=None, parent="HEAD", name="Test",
           mail="test@example.invalid"):
    """A commit of parent's tree plus files (path -> text), authored by name <mail>; ref (never a
    branch) is set to it. The working tree and the index are left alone."""
    index = home.parent / ("index-%s" % home.name)
    e = dict(env, GIT_INDEX_FILE=str(index), GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=mail)
    g = lambda *a, **kw: run(["git", "-C", str(home), *a], e, **kw).stdout.strip()  # noqa: E731
    g("read-tree", parent)
    for path, text in files.items():
        g("update-index", "--add", "--cacheinfo",
          "100644,%s,%s" % (g("hash-object", "-w", "--stdin", input=text), path))
    sha = g("commit-tree", g("write-tree"), "-p", parent, "-m", message)
    index.unlink()
    if ref:
        git(env, home, "update-ref", ref, sha)
    return sha


def raw_commit(env, home, ref, author, extra=""):
    """A hand-made commit object (HEAD's tree; `extra` header lines) on ref, as git would not
    write it: an author line kept byte for byte, or a parent the home does not have."""
    tree = git(env, home, "rev-parse", "HEAD^{tree}").stdout.strip()
    raw = ("tree %s\n%sauthor %s 1700000000 +0000\ncommitter Test <test@example.invalid> "
           "1700000000 +0000\n\na hand-made commit\n" % (tree, extra, author))
    sha = run(["git", "-C", str(home), "hash-object", "-t", "commit", "-w", "--stdin",
               "--literally"], env, input=raw).stdout.strip()
    git(env, home, "update-ref", ref, sha)


def literals(home):
    return (home / "private-literals.txt").read_text(encoding="utf-8").splitlines()


def mode(home):
    return stat.S_IMODE((home / "private-literals.txt").stat().st_mode)


def to_hooks_state(env, home):
    """The landing's "hooks" state, as the new pre-push guard file brings it to a landed home."""
    hooks = home / git(env, home, "rev-parse", "--git-path", "hooks").stdout.strip()
    (hooks / "pre-commit").unlink()
    assert land(env, home, "--state").strip() == "hooks"


def history_landing(env, home, args=()):
    """The seeding step alone, as the landing runs it before step 5: its stdout."""
    return run(["python3", str(home / "scripts/install/render-settings"), "land", "--history",
                *args], env).stdout


def shown(notice, home):
    return notice + landing_log(home)


def every_ref_class(env, home):
    """One value from each source on each ref class; returns {class: value}."""
    values = {"identity-mail": private("backup"), "branch-message": private("branch"),
              "remote-message": private("remote"), "tag-message": private("tag"),
              "checkpoint-blob": private("checkpoint"), "older-stash-blob": private("stash")}
    commit(env, home, {"notes/backup.txt": "a backup\n"}, "a backup",
           "refs/backups/claude/master/1", name=STAND_IN, mail=values["identity-mail"])
    git(env, home, "commit", "-q", "--allow-empty", "-m", "contact " + values["branch-message"])
    commit(env, home, {}, "upstream: write to %s\n" % values["remote-message"],
           "refs/remotes/origin/other")
    git(env, home, "tag", "-a", "v-demo", "-m", "release notes, %s" % values["tag-message"])
    commit(env, home, {"notes/snapshot.txt": "snapshot by %s\n" % values["checkpoint-blob"]},
           "snapshot", "refs/checkpoints/master")
    write(home / "notes.txt", "a stashed edit for %s\n" % values["older-stash-blob"])
    git(env, home, "stash", "push", "-q", "-m", "older")
    write(home / "notes.txt", "a later stashed edit\n")
    git(env, home, "stash", "push", "-q", "-m", "newer")  # the first entry is in the reflog only
    return values


def test_an_absent_list_gets_every_source_at_once_from_every_ref_class(tmp_path, env):
    home, _ = make_home(tmp_path, env)
    values = every_ref_class(env, home)
    notice = land(env, home)
    assert notice.startswith("Harness landing: P7 landed on this home")
    lines = literals(home)
    assert mode(home) == 0o600 and len(lines) == len(set(lines))
    assert re.search(r"seeded overlay-env=\d+ .* history-identities=2 history-e-mails=5 "
                     r"history-held=0 history-objects=\d+\n", landing_log(home))
    assert "private-literals.txt seeded with %d value(s)" % len(lines) in notice
    assert lines[-7:-5] == [values["identity-mail"], STAND_IN]  # after R5's sources
    assert set(lines[-5:]) == set(values.values()) - {values["identity-mail"]}
    assert not [v for v in lines if v in shown(notice, home)]


def test_a_list_with_lines_keeps_them_and_gets_only_what_it_lacks_appended(tmp_path, env):
    home, _ = make_home(tmp_path, env)
    land(env, home)
    own = ("# my list\n/opt/demo/bin/tool\n\n  demo-owner-kept  \n# %s\nlast-line-without-newline"
           % private("backup"))
    write(home / "private-literals.txt", own, 0o640)
    commit(env, home, {"notes/backup.txt": "a backup\n"}, "a backup",
           "refs/backups/claude/master/1", name=STAND_IN, mail=private("backup"))  # on a #-line
    commit(env, home, {"notes/snapshot.txt": "by %s\n" % private("checkpoint")}, "snapshot",
           "refs/checkpoints/master")
    to_hooks_state(env, home)
    notice = land(env, home)
    assert notice == "%s; 2 %s.\n" % (REFRESHED, ADDED)
    after = (home / "private-literals.txt").read_text(encoding="utf-8")
    assert after == own + "\n" + STAND_IN + "\n" + private("checkpoint") + "\n"
    assert mode(home) == 0o640  # the owner's mode is kept
    assert re.search(r"appended history-identities=1 history-e-mails=1 history-held=0 "
                     r"history-objects=\d+\n", landing_log(home))
    assert land(env, home, "--state").strip() == "landed"
    assert not [v for v in (STAND_IN, private("checkpoint"), private("backup"))
                if v in shown(notice, home)]


def test_an_upgraded_home_with_a_list_gets_the_history_values_appended(tmp_path, env):
    home, _ = make_home(tmp_path, env)
    write(home / "private-literals.txt", "/opt/demo/bin/tool\n", 0o600)
    commit(env, home, {}, "a message for %s" % private("msg"), "refs/backups/claude/master/2")
    assert "1 %s" % ADDED in land(env, home)
    assert literals(home) == ["/opt/demo/bin/tool", private("msg")]


def test_public_classes_are_never_seeded(tmp_path, env):
    home, _ = make_home(tmp_path, env)
    public = ["demo@example.com", "demo@example.net", "Demo@Example.Org", "demo@sub.example.com",
              "demo@example.invalid", "demo@host.test", "demo@host.example", "demo@sub.localhost",
              "noreply@demo-forge.invalid.zz", "no-reply@demo-forge.zz",
              "12345+acct-test-123@users.noreply.demo-forge.zz"]
    commit(env, home, {"notes/public.txt": "\n".join(public) + "\n"}, "public: " + " ".join(public),
           "refs/checkpoints/master", name=STAND_IN, mail="noreply@demo-forge.zz")
    for mail in ("demo@example.invalid", STAND_IN + "@localhost",
                 "41898282+demo-bot@users.noreply.demo-forge.zz"):
        commit(env, home, {}, "by a public identity", "refs/backups/claude/" + mail.split("@")[0],
               name="demo-public-name", mail=mail)
    commit(env, home, {}, "one control: %s" % private("control"), "refs/remotes/origin/control")
    land(env, home)
    lines = literals(home)
    assert private("control") in lines
    assert not [v for v in lines if v in public or v in (STAND_IN, "demo-public-name")
                or "noreply" in v or "localhost" in v]
    assert re.search(r"history-identities=0 history-e-mails=1 ", landing_log(home))


def test_the_filters_apply_to_the_history_values(tmp_path, env):
    """R5's filters on every value (trim, at least 4 characters, shipped defaults, the bare owner
    name of the origin URL, de-duplicated, 100 or more lines at HEAD) and fact 9's experiment: a
    history value HEAD's tracked files hold at all is not seeded."""
    home, _ = make_home(tmp_path, env)
    git(env, home, "remote", "add", "origin", "git@example.invalid:demo-owner/harness.git")
    held, common = ("contact-%s@contacts" % k + ".internal" for k in ("held", "common"))
    write(home / "docs/contact.md", "write to %s\n" % held + "%s\n" % common * 100)
    git(env, home, "add", "docs/contact.md")
    git(env, home, "commit", "-q", "-m", "a public contact")
    for i, (name, tag) in enumerate((("abc", "short"), ("C.UTF-8", "shipped"),
                                     ("Demo-Owner", "owner"), (STAND_IN, "twice"),
                                     (STAND_IN, "twice"))):
        commit(env, home, {"notes/%d.txt" % i: "a backup\n"}, "by %s" % name,
               "refs/backups/claude/master/%d" % i, name=name, mail=private(tag))
    raw_commit(env, home, "refs/backups/claude/trim",
               "  demo-trimmed-name   <%s>" % private("trim"))
    notice = land(env, home)
    lines = literals(home)
    for tag in ("short", "shipped", "owner", "twice", "trim"):
        assert lines.count(private(tag)) == 1
    assert lines.count(STAND_IN) == 1 and "demo-trimmed-name" in lines
    assert not [v for v in ("abc", "C.UTF-8", "Demo-Owner", "demo-owner", held, common)
                if v in lines]
    assert "not seeded, in 100 or more tracked lines at HEAD: 1 value(s)" in landing_log(home)
    # history-held: the held address, and C.UTF-8 (a shipped default HEAD's settings.json holds)
    assert re.search(r"history-identities=7 history-e-mails=0 history-held=2 ", landing_log(home))
    assert not [v for v in lines + [held, common] if v in shown(notice, home)]


def test_idempotent_and_a_landing_cut_short_completes_at_the_next_trigger(tmp_path, env):
    home, _ = make_home(tmp_path, env)
    land(env, home)
    before = (home / "private-literals.txt").read_bytes()
    commit(env, home, {"notes/snapshot.txt": "by %s\n" % private("snap")}, "snapshot",
           "refs/checkpoints/master", name=STAND_IN, mail=private("author"))
    to_hooks_state(env, home)
    # A landing killed after the seeding and before step 5: the seeding alone, then the next Stop.
    assert history_landing(env, home) == "3 %s\n" % ADDED
    seeded = (home / "private-literals.txt").read_bytes()
    assert seeded == before + ("%s\n%s\n%s\n" % (private("author"), STAND_IN,
                                                 private("snap"))).encode()
    assert land(env, home, "--state").strip() == "hooks"
    assert land(env, home) == REFRESHED + ".\n"  # nothing appended a second time
    assert (home / "private-literals.txt").read_bytes() == seeded
    to_hooks_state(env, home)
    assert land(env, home) == REFRESHED + ".\n"
    assert (home / "private-literals.txt").read_bytes() == seeded


def test_the_scan_past_its_time_limit_reads_commits_only_and_says_so(tmp_path, env):
    home, _ = make_home(tmp_path, env)
    land(env, home)
    commit(env, home, {"notes/snapshot.txt": "by %s\n" % private("snap")}, "snapshot",
           "refs/checkpoints/master", name=STAND_IN, mail=private("author"))
    out = history_landing(env, home, ("--spent", "60"))  # the author's address and name
    assert re.fullmatch(r"2 %s; the history scan for private-literals.txt stopped at its time "
                        r"limit after \d+ object\(s\)\n" % re.escape(ADDED), out)
    assert private("snap") not in literals(home) and private("author") in literals(home)
    assert "history-cut=time-limit" in landing_log(home)
    to_hooks_state(env, home)
    assert "1 %s" % ADDED in land(env, home)
    assert private("snap") in literals(home)


def test_a_landed_home_whose_list_is_gone_gets_every_source_at_the_hooks_state(tmp_path, env):
    home, _ = make_home(tmp_path, env)
    land(env, home)
    first = literals(home)
    (home / "private-literals.txt").unlink()
    commit(env, home, {}, "by %s" % private("late"), "refs/backups/claude/master/3")
    to_hooks_state(env, home)
    assert "private-literals.txt seeded with %d value(s)" % (len(first) + 1) in land(env, home)
    assert literals(home) == first + [private("late")] and mode(home) == 0o600


def test_a_ref_to_an_object_the_home_lacks_is_skipped(tmp_path, env):
    """A broken ref, or a parent the home lacks, holds no value and stops nothing: the walk skips
    it, so no owner step is ever needed before the git hooks are reinstalled."""
    home, _ = make_home(tmp_path, env)
    land(env, home)
    write(home / ".git/refs/backups/claude/broken", "1" * 40 + "\n")
    raw_commit(env, home, "refs/backups/claude/orphan", "%s <%s>" % (STAND_IN, private("orphan")),
               "parent %s\n" % ("2" * 40))
    to_hooks_state(env, home)
    assert "2 %s" % ADDED in land(env, home)
    assert literals(home)[-2:] == [private("orphan"), STAND_IN]
    assert land(env, home, "--state").strip() == "landed"


@pytest.mark.parametrize("state", ["hooks", "upgraded"])
def test_a_failed_history_scan_exits_0_with_one_notice_and_a_counts_only_log(tmp_path, env, state):
    """The walk fails (a git that refuses rev-list, put first on PATH): exit 0, one notice line
    naming the step, a log of counts and names only, and the list left as it was. An upgraded home
    is left as it was and lands at the next turn end; at the hooks state step 5 installs the hooks
    (the pre-push guard too) with the list as it is, so the next Stop scans nothing, and the next
    hooks state appends what the failed scan lacked."""
    home, _ = make_home(tmp_path, env)
    if state == "hooks":
        land(env, home)
        to_hooks_state(env, home)
    write(home / "private-literals.txt", "/opt/demo/bin/tool\n", 0o600)
    commit(env, home, {}, "by %s" % private("kept"), "refs/backups/claude/master/4")
    stub = tmp_path / "stub"
    write(stub / "git", '#!/bin/sh\ncase " $* " in *" rev-list "*) exit 1 ;; esac\nexec %s "$@"\n'
          % shutil.which("git"), 0o755)
    log_before = landing_log(home)
    notice = land(dict(env, PATH="%s:%s" % (stub, env["PATH"])), home)  # asserts exit 0
    new = landing_log(home)[len(log_before):]
    if state == "hooks":
        assert notice == REFRESHED + (", with private-literals.txt as it is: the history seeding "
                                      "step failed (see logs/landing.log).\n")
        assert "steps 5 done" in new
        assert "result=hooks-refreshed failed-history seeding head=" in new
    else:
        assert notice.startswith("Harness landing failed at the settings step (see "
                                 "logs/landing.log)")
        assert notice.count("\n") == 1 and notice.endswith("it runs again at the next turn end.\n")
        assert "result=failed-settings head=" in new
    assert "land: failed: RuntimeError" in new
    assert not [v for v in ("/opt/demo/bin/tool", private("kept"), STAND_IN) if v in notice + new]
    assert literals(home) == ["/opt/demo/bin/tool"]
    if state == "hooks":
        assert_landed(env, home)  # the git hooks installed, the pre-push guard among them
        log_after = landing_log(home)
        assert land(env, home) == "" and landing_log(home) == log_after
        to_hooks_state(env, home)
    else:
        assert land(env, home, "--state").strip() == state  # tried again at the next turn end
    assert "1 %s" % ADDED in land(env, home)
    assert literals(home) == ["/opt/demo/bin/tool", private("kept")]
    assert land(env, home, "--state").strip() == "landed"
