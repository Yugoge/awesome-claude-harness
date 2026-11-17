"""The pure read-only `permissions.allow` entries (owner decision: read-only commands stop prompting in
default mode) and the proof that none of them also allows a mutating or executing neighbour.

Matching semantics modelled here, from code.claude.com/docs/en/permissions ("Wildcard patterns",
"Compound commands", "Wrappers", "Redirections", "Read-only commands"):

* A `*` matches any text, spaces included; a rule with no `*` matches one exact command
  (`Bash(npm run build)` does not match `npm run build --watch`). Everything before the first `*` is
  matched as written.
* `:*` at the end is the same as a trailing ` *`; a trailing ` *` that is the rule's only wildcard also
  matches the bare command (`Bash(ls *)` matches `ls`, not `lsof`).
* A compound command is split at `&&`, `||`, `;`, `|`, `|&`, `&` and newlines; every subcommand must be
  allowed for the whole to run unasked.
* The wrappers `timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command` (not `command -v`), `builtin`,
  `noglob` and a bare `xargs` are stripped before matching; a leading assignment is stripped only for
  certain known-safe variables ("An allow rule won't match past an assignment of any other variable").
  SAFE_ENV is that set as Claude Code 2.1.326's own binary carries it (read from the shipped build).
* An output redirect's target is checked against the `Edit` rules, protected paths and working
  directories as if Claude wrote the file: "A rule such as `Bash(git commit *)` allows the command, not
  the target." So `jq . a > b` writes only where an Edit rule already lets it; this lane adds no Edit,
  Write or `tee` rule.

Consequence for entry forms: a prefix entry (`P:*`) admits every flag the program accepts, so a
program with a flag that writes a file or runs a program cannot get one. Those are omitted (OMITTED),
or are given exact entries only (`git fetch`, `git remote`), or `*` sits after a subcommand word whose
arguments cannot select another subcommand (`git remote get-url *`, `git remote show *`; the git cases
below run git itself to show it).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Each new entry -> why it can only read.
READ_ONLY_ENTRIES = {
    "Bash(comm:*)": "comm compares two sorted files; no option writes a file or runs a program "
                    "(GNU coreutils: --check-order, --output-delimiter, --total, -z)",
    "Bash(diff:*)": "GNU diff writes only to stdout; -l/--paginate pipes through the fixed `pr`, never a "
                    "named program; diff has no --output option",
    "Bash(jq:*)": "jq has no builtin that writes a file or runs a program; -f/--rawfile/--slurpfile/-L read",
    "Bash(git fetch)": "exact: updates remote-tracking refs and FETCH_HEAD of the configured remote only",
    "Bash(git fetch origin)": "exact: as above, for origin's configured refspec",
    "Bash(git fetch --all)": "exact: as above, for every configured remote",
    "Bash(git fetch origin main)": "exact: one branch into refs/remotes/origin/main and FETCH_HEAD",
    "Bash(git fetch origin master)": "exact: one branch into refs/remotes/origin/master and FETCH_HEAD",
    "Bash(git remote)": "exact: lists remote names",
    "Bash(git remote -v)": "exact: lists remotes with URLs",
    "Bash(git remote --verbose)": "exact: lists remotes with URLs",
    "Bash(git remote get-url *)": "get-url takes only --push/--all and one name; anything else exits 129",
    "Bash(git remote show *)": "show takes only -n and names; every further word is a name it shows",
    "Bash(kubectl logs:*)": "reads container logs (GET); its flag surface is that of the existing "
                            "`kubectl get:*`/`kubectl describe:*` entries",
}

# Owner-listed examples deliberately left out: a prefix entry would also match the form named.
OMITTED = {
    "Bash(rg:*)": "rg --pre <program> runs a program on every searched file",
    "Bash(git show:*)": "git show --output=<file> writes a file; --ext-diff runs the configured differ",
    "Bash(git blame:*)": "git blame --output=<file> writes a file (it passes diff options through)",
    "Bash(journalctl:*)": "--vacuum-*, --rotate, --flush, --sync, --relinquish-var, --setup-keys, "
                          "--update-catalog mutate the journal; --cursor-file=<file> writes a file",
    "Bash(git fetch:*)": "a refspec `src:dst` writes any local ref; --upload-pack=<cmd> runs a program; "
                         "--set-upstream writes config",
    "Bash(git remote:*)": "matches git remote add/remove/rename/set-url/prune/set-head/update",
}

# Known-safe assignment prefixes stripped before allow matching (Claude Code 2.1.326 binary).
SAFE_ENV = frozenset({
    "GOEXPERIMENT", "GOOS", "GOARCH", "CGO_ENABLED", "GO111MODULE", "RUST_BACKTRACE", "RUST_LOG",
    "NODE_ENV", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE", "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTEST_DEBUG", "ANTHROPIC_API_KEY", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_TIME", "CHARSET",
    "TERM", "COLORTERM", "NO_COLOR", "FORCE_COLOR", "TZ", "LS_COLORS", "LSCOLORS", "GREP_COLOR",
    "GREP_COLORS", "GCC_COLORS", "TIME_STYLE", "BLOCK_SIZE", "BLOCKSIZE", "COLUMNS", "LINES", "CLICOLOR",
    "CLICOLOR_FORCE", "CI", "DEBIAN_FRONTEND", "GIT_TERMINAL_PROMPT",
})


# ------------------------------------------------------------------ the documented matcher
def _pattern(rule: str) -> re.Pattern:
    body = re.fullmatch(r"Bash\((.*)\)", rule, re.S).group(1)
    if body.endswith(":*"):
        body = body[:-2] + " *"
    rx = ".*".join(re.escape(part) for part in body.split("*"))
    if body.count("*") == 1 and body.endswith(" *"):
        rx = f"(?:{rx}|{re.escape(body[:-2])})"
    return re.compile(rx, re.S)


def split_compound(command: str) -> list[str]:
    """Split at the documented separators outside quotes; `$(...)` and backtick bodies become parts too."""
    parts, cur, quote, i = [], "", "", 0
    nested = re.findall(r"\$\(([^()]*)\)|`([^`]*)`", command)
    while i < len(command):
        ch = command[i]
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote, cur = ch, cur + ch
        elif command.startswith(("&&", "||", "|&"), i):
            parts.append(cur)
            cur = ""
            i += 1
        elif ch in ";|&\n":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur)
    out = [p.strip() for p in parts if p and p.strip()]
    return out + [a or b for a, b in nested if (a or b).strip()]


_WRAPPER = re.compile(
    r"^(?:timeout(?:\s+-\S+)*\s+\S+|time|nice(?:\s+-n\s+\S+|\s+-\d+)?|nohup|stdbuf(?:\s+-\S+)*"
    r"|command(?!\s+-v)|builtin|noglob|xargs(?=\s+[^-\s]))\s+")
_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(?:'[^']*'|\"[^\"]*\"|\S*)\s+")
_REDIRECT = re.compile(r"\s*(?:\d*>>?|&>|<)\s*(?:'[^']*'|\"[^\"]*\"|[^\s;|&]+)")


def normalized(simple: str) -> list[str]:
    """The texts an allow rule is matched against: wrappers and safe assignments stripped, with the
    redirections both kept and removed (the target goes to the Edit check either way)."""
    text = simple.strip()
    while True:
        m = _WRAPPER.match(text)
        if not m:
            m = _ASSIGN.match(text)
            m = m if m and m.group(1) in SAFE_ENV else None
        if not m:
            break
        text = text[m.end():]
    return [text, _REDIRECT.sub("", text).strip()]


def rule_allows(rule: str, simple: str) -> bool:
    return any(_pattern(rule).fullmatch(t) for t in normalized(simple))


def allowed_by(rules, command: str) -> bool:
    """Every part of the command is matched by one of `rules`."""
    return all(any(rule_allows(r, part) for r in rules) for part in split_compound(command))


def _allow() -> list[str]:
    return json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]


# ------------------------------------------------------------------ the matcher reproduces the docs
@pytest.mark.parametrize("rule, command, expected", [
    ("Bash(npm run build)", "npm run build", True),
    ("Bash(npm run build)", "npm run build --watch", False),
    ("Bash(npm run *)", "npm run build", True),
    ("Bash(npm run *)", "npm run test --watch", True),
    ("Bash(npm run *)", "npm run", True),
    ("Bash(npm run *)", "npm install", False),
    ("Bash(git log * main)", "git log --oneline main", True),
    ("Bash(git log * main)", "git log --output=f main", True),
    ("Bash(git log * main)", "git log main", False),
    ("Bash(git log * main)", "git push origin main", False),
    ("Bash(git * main)", "git -c core.fsmonitor=x diff main", True),
    ("Bash(git * main)", "git log", False),
    ("Bash(* --version)", "node --version", True),
    ("Bash(* --version)", "node -v", False),
    ("Bash(ls *)", "ls -la", True),
    ("Bash(ls *)", "ls", True),
    ("Bash(ls *)", "lsof", False),
    ("Bash(ls*)", "lsof", True),
    ("Bash(ls:*)", "ls", True),
    ("Bash(ls:*)", "lsof", False),
    ("Bash(* --help *)", "npm --help x", True),
    ("Bash(* --help *)", "npm --help", False),
    ("Bash(npm test *)", "timeout 30 npm test", True),
    ("Bash(npm test *)", "NODE_ENV=test npm test", True),
    ("Bash(npm test *)", "FOO=bar npm test", False),
    ("Bash(grep *)", "xargs grep pattern", True),
    ("Bash(grep *)", "xargs -n1 grep pattern", False),
])
def test_the_matcher_reproduces_the_documented_rows(rule, command, expected):
    assert rule_allows(rule, command) is expected


def test_the_matcher_splits_compound_commands():
    assert not allowed_by(["Bash(safe-cmd *)"], "safe-cmd && other-cmd")
    assert allowed_by(["Bash(safe-cmd *)"], "safe-cmd a && safe-cmd b | safe-cmd c")
    assert split_compound('echo "a; b" && x $(y z)') == ['echo "a; b"', "x $(y z)", "y z"]


# ------------------------------------------------------------------ the entries
def test_each_read_only_entry_is_in_the_allow_list():
    allow = _allow()
    assert [e for e in READ_ONLY_ENTRIES if e not in allow] == []


def test_no_omitted_prefix_entry_is_in_the_allow_list():
    assert [e for e in OMITTED if e in _allow()] == []


def test_the_lane_adds_no_file_rule():
    """Redirect targets and tee destinations are decided by the Edit rules; no new entry is one."""
    assert all(e.startswith("Bash(") for e in READ_ONLY_ENTRIES)
    assert not any(re.match(r"Bash\((tee|sh|bash|env|sudo)\b", e) for e in READ_ONLY_ENTRIES)


@pytest.mark.parametrize("command", [
    "comm -12 a.txt b.txt", "comm -3 --check-order a b", "diff -u a.py b.py", "diff -r dir1 dir2",
    "jq -r '.items[].name' data.json", "jq --rawfile t notes.txt -n '$t'", "cat x.json | jq .",
    "git fetch", "git fetch origin", "git fetch --all", "git fetch origin main", "timeout 60 git fetch origin",
    "git remote", "git remote -v", "git remote get-url origin", "git remote get-url --push origin",
    "git remote show origin", "git remote show -n origin",
    "kubectl logs pod-x -n ns --tail=100", "kubectl logs deploy/api -c app --since=1h",
    "LC_ALL=C diff a b",
])
def test_the_read_forms_are_allowed(command):
    assert allowed_by(_allow(), command), command


MUTATING = [
    # git branch (no new entry is a branch entry; listed so a later one cannot slip in)
    "git branch -d x", "git branch -D x", "git branch -m a b", "git branch -M a b",
    "git branch --set-upstream-to=origin/x", "git branch newname",
    # git remote writes
    "git remote add x https://h/r", "git remote remove x", "git remote rm x",
    "git remote set-url origin https://h/r", "git remote rename a b", "git remote prune origin",
    "git remote set-head origin -a", "git remote set-branches origin x", "git remote update",
    "git remote -v add x u", "git remote --verbose add x u", "git remote -v update",
    # git fetch beyond remote-tracking refs, or running a program
    "git fetch origin +main:main", "git fetch origin main:main", "git fetch origin refs/heads/x:refs/heads/main",
    "git fetch origin main:refs/heads/main", "git fetch --upload-pack=touch origin", "git fetch -u touch origin",
    "git fetch origin --upload-pack='sh -c x'", "git fetch --set-upstream origin main",
    "git fetch --prune origin", "git fetch --update-head-ok origin main:main", "git fetch --force origin",
    "git fetch origin main --depth=1", "git fetch 'ext::sh -c touch% x'",
    "git -c protocol.ext.allow=always fetch 'ext::sh -c x'", "git -C /elsewhere fetch origin",
    "GIT_SSH_COMMAND='sh -c x' git fetch origin",
    # programs, pagers and file writes through git options
    "git log --output=f", "git diff --output=f", "git show --output=f HEAD", "git show --ext-diff HEAD",
    "git blame --output=f README.md", "git log -p --ext-diff", "git -c core.pager=x log",
    "git -c diff.external=x diff", "GIT_PAGER=x git log", "PAGER=x git remote -v",
    "GIT_EXTERNAL_DIFF=x git diff", "git -p remote -v",
    # rg
    "rg --pre sh pat .", "rg --pre=cat x", "rg --pre-glob '*' --pre sh x", "rg -n --pre sh x",
    "RIPGREP_CONFIG_PATH=/tmp/r rg x",
    # journalctl
    "journalctl --vacuum-size=1M", "journalctl --vacuum-time=1s", "journalctl --vacuum-files=1",
    "journalctl --rotate", "journalctl --flush", "journalctl --sync", "journalctl --relinquish-var",
    "journalctl --smart-relinquish-var", "journalctl --setup-keys", "journalctl --update-catalog",
    "journalctl --cursor-file=/tmp/c", "journalctl -u x --vacuum-time=1s",
    # kubectl writes
    "kubectl delete pod x", "kubectl apply -f m.yaml", "kubectl create ns x", "kubectl edit cm x",
    "kubectl patch cm x -p '{}'", "kubectl label pod x a=b", "kubectl annotate pod x a=b",
    "kubectl scale deploy x --replicas=0", "kubectl exec pod -- sh", "kubectl cp a pod:/b",
    "kubectl rollout restart deploy x", "kubectl drain node", "kubectl cordon node", "kubectl replace -f m",
    "kubectl set image deploy/x a=b", "KUBECONFIG=/tmp/k kubectl logs p",
    # database clients, mutating requests, project code
    "psql -c 'drop table t'", "sqlite3 db 'delete from t'", "mysql -e 'drop database d'",
    "gh api -X DELETE repos/o/r", "gh api repos/o/r", "curl -X POST https://h", "make install", "make",
    "pytest", "npm install", "python -c 'x'", "python3 x.py", "node x.js", "bash x.sh", "sh -c 'jq .'",
    # wrapped and compound forms
    "timeout 30 git fetch origin +main:main", "nice git remote add x u", "nohup journalctl --vacuum-size=1M",
    "xargs git remote remove", "command git fetch --upload-pack=x origin", "time rg --pre sh x",
    "git fetch origin && git push --force origin main", "git remote -v; git remote add x u",
    "jq . f | sh", "kubectl logs p | kubectl apply -f -", "diff a b || rm -f a", "comm a b & rm b",
    "git remote show $(git remote add x u)", "jq . `touch x`",
]


@pytest.mark.parametrize("command", MUTATING)
def test_no_new_entry_allows_a_mutating_neighbour(command):
    assert not allowed_by(READ_ONLY_ENTRIES, command), command


def test_kubectl_logs_adds_no_execution_path():
    """`--kubeconfig` names a file whose exec credential plugin kubectl runs; `kubectl get:*` already allows
    every such flag, so `kubectl logs:*` grants nothing the list did not grant."""
    allow = [e for e in _allow() if e not in READ_ONLY_ENTRIES]
    assert allowed_by(allow, "kubectl get pods --kubeconfig=/tmp/k")
    assert rule_allows("Bash(kubectl logs:*)", "kubectl logs p --kubeconfig=/tmp/k")


@pytest.mark.parametrize("command", ["jq . a.json > b.json", "diff -u a b > p.patch", "comm a b >> c.txt"])
def test_a_redirect_target_is_left_to_the_edit_rules(command):
    """The rule allows the command, not the target: the target is checked as an Edit, which this lane
    leaves as it was (test_the_lane_adds_no_file_rule)."""
    assert allowed_by(READ_ONLY_ENTRIES, command)
    assert _REDIRECT.search(command)


# ------------------------------------------------------------------ git itself, isolated
@pytest.fixture
def repo(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path / "home"), "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_PAGER": "cat", "PAGER": "cat"}
    (tmp_path / "home").mkdir()
    (tmp_path / "gitconfig").write_text("")
    work = tmp_path / "w"
    work.mkdir()

    def git(*args):
        return subprocess.run(["git", *args], cwd=work, env=env, capture_output=True, text=True)

    git("init", "-q")
    (work / "f.txt").write_text("a\n")
    git("add", "f.txt")
    git("-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "c")
    git("remote", "add", "origin", str(tmp_path / "nowhere"))
    return work, git


def test_get_url_and_show_take_no_other_subcommand(repo):
    work, git = repo
    out = work.parent / "out"
    assert git("remote", "get-url", "--output=" + str(out), "origin").returncode == 129
    assert git("remote", "show", "--output=" + str(out), "origin").returncode == 129
    assert git("remote", "get-url", "origin", "add", "x", "u").returncode == 129
    git("remote", "show", "-n", "add", "x", "u")
    assert git("remote").stdout.split() == ["origin"] and not out.exists()


def test_the_omitted_git_forms_do_write_a_file(repo):
    work, git = repo
    for sub in (["show", "--stat", "HEAD"], ["blame", "f.txt"]):
        target = work.parent / f"written-{sub[0]}"
        git(sub[0], f"--output={target}", *sub[1:])
        assert target.exists(), sub
