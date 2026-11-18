"""S5 (under-defence): settings.json's secret-file denies also reach the home directory, by `~/` rules.

OB-L19's Read/Edit secret denies are written `**/<name>`, `<name>` or a relative path, and the CLI
anchors all three at the CURRENT directory ("`path` or `./path` = relative to current directory";
"A rule only matches files under its anchor": code.claude.com/docs/en/permissions, "How path patterns
match"). Run from a project, they never reached `~/.aws/credentials`, `~/.env`, `~/.ssh/id_ed25519`,
`~/.netrc`, `~/.docker/config.json`, `~/.kube/config`, `~/.config/gh/hosts.yml`, `~/.git-credentials`,
`~/.pgpass`, nor a sibling project's `.env` (`Read(~/**)` and `Bash(cat:*)` are allowed, so all of
them were read without a prompt). The docs name `~/path` as the home anchor; this lane adds, for Read
and Edit alike, before OB-L19's ordered negation tail:

* ANY_DEPTH, `~/**/<name>`: the L19 names no L19 lift ever re-opens inside a project (the names L19
  re-denies after its lifts, plus `credentials` and `client_secret*.json`), and `.env` with its usual
  valued variants spelled out. A file of these names is refused anywhere under HOME, as it already is
  inside the project.
* TOP_LEVEL, `~/<name>`: the L19 names a lift CAN re-open inside a project (`*_password.*`, the
  directory names `secrets`, `password`, ..., `.secret*`), the key files `*.key`/`*.pem`, and `.env.*`:
  refused at the top of HOME only (so `~/.env.example` there is refused on purpose; a project's own
  templates stay open). Not covered: `~/.claude/.credentials.json` and other stores not listed.
* STORES: the standard home credential stores, by exact path; under `~/.ssh` only private keys
  (`id_<type>`, `*.key`, `*.pem`), never `*.pub`, `config` or `known_hosts`; `~/.config/gh/hosts.yml`
  (the token) but not `config.yml`.

Measured on Claude Code 2.1.326 (Linux), offline, with OB-L19's rig (a throwaway HOME whose user settings
hold only the `permissions` block under test, `claude -p` pointed through ANTHROPIC_BASE_URL at a local
stand-in for the Messages API that answers the first turn with one scripted tool call and records the
tool_result the CLI sends back), varied so the project lives INSIDE that HOME (`~/work/proj`) and a case
can run with cwd = HOME:

* `~/<path>` anchors at HOME and does NOT match at depth, even for a bare name: `Read(~/.env)` refuses
  `~/.env`, not `~/sub/.env` nor `~/work/proj/.env`; `~/**/<name>` matches at any depth under HOME;
* `~/.ssh/id_*` also refuses `id_rsa.pub`, so the keys are named one by one;
* a Bash operand that names the file literally is held to the rules in each path spelling the CLI
  resolves: `cat ~/.env`, `cat $HOME/.env`, `cat <home>/.env` (absolute), `cat ../../.env`; a redirection
  `> ~/.netrc` likewise. `${HOME}` is never auto-run whatever the rules ("A variable in braces in this
  command can't be checked before it runs"), so it needs no rule. NOT covered: a glob operand or a
  recursive directory read. The CLI checks the operand as written, before the shell expands it, so
  `cat ~/.ssh/id_rs[a]`, `cat ~/.ssh/id_*`, `cat ~/.aws/cred*`, `grep -r token ~/.aws` and
  `grep -r x ~/work/other` return content (measured by the independent verifier on this branch; the
  same class exists in a project under OB-L19: `cat .env*`, `grep -r TODO .`). A directory-tree deny
  such as `~/.ssh/**` would catch the literal glob, but was rejected so that config files
  (`~/.ssh/config`, `known_hosts`, `*.pub`) stay readable;
* a `!` negation lifts only matches of rules with the SAME anchor: OB-L19's `!**/.env.example` (anchored
  at the cwd) did not lift a `~/**/.env.*` match even for `<proj>/.env.example`. That is why no `~/**/`
  entry names anything an L19 lift opens (a first try with `~/**/.env.*` refused the project's own
  `.env.example`), and why no `~/` lift exists: OB-L19's tail and its order are untouched, the entries sit
  before the tail, and every L19 decision inside a project under HOME is unchanged (measured over L19's
  own 168 cases and asserted by test_l19_project_decisions_are_unchanged).

Precedence tiers: every entry added here is a deny; no allow or ask rule changed. Measured, no ordinary
home file changed its decision (`~/.bashrc`, `~/.gitconfig`, `~/notes.txt`, `~/.ssh/id_rsa.pub`,
`~/.config/gh/config.yml`, ...: Read and `cat` still allowed, writes still `ask`), so the exact-path
entries (no `*`) neither downgrade nor upgrade anything beyond the files they name. OB-L08 later added `~/` Edit
asks for home dot-state (`Edit(~/.?)` ... `Edit(~/.wgetrc)`, `Edit(~/.pgpass)` among them); deny is checked before
ask, so every file refused here stays refused under them (test_every_home_secret_deny_wins_over_any_ask).

MEASURED is that run: (cwd, tool, target, decision on OB-L19's settings.json @ c0888950, decision with
this settings.json). `deny` is a refusal by a rule, `ask` a call headless `-p` could not approve, `allow` a
call that ran. The model below reproduces every row.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.test_secret_file_denies import (DELIBERATELY_OPEN, KEPT_REFUSED, MEASURED as L19_MEASURED, MUST_PASS,
                                           MUST_REFUSE, VERIFIER_DROP, _lifted_names)
from tests.test_secret_file_denies import denied as project_denied

REPO = Path(__file__).resolve().parent.parent
PROJ = "work/proj"  # the measured project, relative to HOME

ENV_VALUED = [".env.local", ".env.dev", ".env.development", ".env.development.local", ".env.prod", ".env.production",
              ".env.production.local", ".env.stage", ".env.staging", ".env.test", ".env.test.local"]
# OB-L19 never re-opens these inside a project: its tail re-denies them after the lifts, or no lift fits them.
NEVER_LIFTED = ["secret.*", "secrets.*", "*_secrets.*", "*-secrets.*", "credentials.*", "password.*", "passwords.*",
                "credentials", "client_secret*.json", ".env"]
ANY_DEPTH = NEVER_LIFTED + ENV_VALUED
TOP_LEVEL = ["*-password.*", "*-secret.*", "*_password", "*_password.*", "*_secret.*", "password", "passwords",
             "secret", "secrets", "*.key", "*.pem", ".password*", ".secret*", ".env.*"]
STORES = [".config/gh/hosts.yml", ".docker/config.json", ".git-credentials", ".kube/config", ".netrc", ".pgpass",
          ".ssh/*.key", ".ssh/*.pem", ".ssh/id_dsa", ".ssh/id_ecdsa", ".ssh/id_ecdsa_sk", ".ssh/id_ed25519",
          ".ssh/id_ed25519_sk", ".ssh/id_rsa"]
HOME_PATTERNS = sorted({f"~/**/{p}" for p in ANY_DEPTH} | {f"~/{p}" for p in TOP_LEVEL + STORES})

# The lane's must-deny targets (home-relative): the brief's stores, a sibling project's env files, L19 names.
SECRET_FILES = [".aws/credentials", ".env", ".ssh/id_rsa", ".ssh/id_ed25519", ".ssh/id_ecdsa", ".netrc",
                ".docker/config.json", ".kube/config", ".config/gh/hosts.yml", ".git-credentials", ".pgpass",
                ".ssh/aws-key.pem", ".env.local", ".env.foo", "secrets.yaml", "password.txt", "db_password",
                "credentials.json", "Downloads/client_secret_1.json", "keypair.pem", "other/.env",
                "other/.env.production", "other/.env.development.local", "other/config/credentials.yml", ".secrets",
                ".password-store/x.gpg", ".config/gcloud/credentials.db"]
# Ordinary home files: they keep their decision (never refused by a rule), from a project and from HOME.
ORDINARY = [".bashrc", ".gitconfig", "notes.txt", ".ssh/id_rsa.pub", ".ssh/config", ".ssh/known_hosts",
            ".config/gh/config.yml", ".docker/daemon.json", ".kube/cache/x.json", ".aws/config",
            "other/src/auth/ForgotPassword.tsx", "other/src/db_password.py", "other/config/secrets/README.md",
            "other/app/reset-password.tsx", "other/.env.example", "other/.env.template", "other/.env.foo",
            "other/.password.py", "other/.secret_scanner.py"]

# (cwd, tool, target, OB-L19 decision, decision now): Claude Code 2.1.326, measured. `~/` and `<HOME>/` are the
# throwaway HOME; a bare target is in the project (`~/work/proj`).
MEASURED = [
    ("proj", "Read", "~/.aws/credentials", "allow", "deny"),
    ("proj", "Read", "~/.env", "allow", "deny"),
    ("proj", "Read", "~/.netrc", "allow", "deny"),
    ("proj", "Read", "~/.docker/config.json", "allow", "deny"),
    ("proj", "Read", "~/.kube/config", "allow", "deny"),
    ("proj", "Read", "~/.config/gh/hosts.yml", "allow", "deny"),
    ("proj", "Read", "~/.git-credentials", "allow", "deny"),
    ("proj", "Read", "~/.pgpass", "allow", "deny"),
    ("proj", "Read", "~/.ssh/id_rsa", "allow", "deny"),
    ("proj", "Read", "~/.ssh/id_ed25519", "allow", "deny"),
    ("proj", "Read", "~/.ssh/aws-key.pem", "allow", "deny"),
    ("proj", "Read", "~/.env.local", "allow", "deny"),
    ("proj", "Read", "~/secrets.yaml", "allow", "deny"),
    ("proj", "Read", "~/password.txt", "allow", "deny"),
    ("proj", "Read", "~/db_password", "allow", "deny"),
    ("proj", "Read", "~/credentials.json", "allow", "deny"),
    ("proj", "Read", "~/Downloads/client_secret_1.json", "allow", "deny"),
    ("proj", "Read", "~/keypair.pem", "allow", "deny"),
    ("proj", "Read", "~/other/.env", "allow", "deny"),
    ("proj", "Read", "~/other/.env.production", "allow", "deny"),
    ("proj", "Read", "~/other/.env.development.local", "allow", "deny"),
    ("proj", "Read", "~/.env.foo", "allow", "deny"),
    ("proj", "Read", "~/.password-store/x.gpg", "allow", "deny"),
    ("proj", "Read", "~/other/config/credentials.yml", "allow", "deny"),
    ("proj", "Read", "~/.secrets", "allow", "deny"),
    ("proj", "Read", "~/.bashrc", "allow", "allow"),
    ("proj", "Read", "~/.gitconfig", "allow", "allow"),
    ("proj", "Read", "~/notes.txt", "allow", "allow"),
    ("proj", "Read", "~/.ssh/id_rsa.pub", "allow", "allow"),
    ("proj", "Read", "~/.ssh/config", "allow", "allow"),
    ("proj", "Read", "~/.ssh/known_hosts", "allow", "allow"),
    ("proj", "Read", "~/.config/gh/config.yml", "allow", "allow"),
    ("proj", "Read", "~/.docker/daemon.json", "allow", "allow"),
    ("proj", "Read", "~/.kube/cache/x.json", "allow", "allow"),
    ("proj", "Read", "~/.aws/config", "allow", "allow"),
    ("proj", "Read", "~/other/src/auth/ForgotPassword.tsx", "allow", "allow"),
    ("proj", "Read", "~/other/src/db_password.py", "allow", "allow"),
    ("proj", "Read", "~/other/config/secrets/README.md", "allow", "allow"),
    ("proj", "Read", "~/other/.env.example", "allow", "allow"),
    ("proj", "Read", "~/other/certs/ca.pem", "allow", "allow"),
    ("proj", "Read", "~/Documents/talk.key", "allow", "allow"),
    ("proj", "Read", "~/other/app/reset-password.tsx", "allow", "allow"),
    ("proj", "Read", "~/other/.env.template", "allow", "allow"),
    ("proj", "Read", "~/other/.password.py", "allow", "allow"),
    ("proj", "Read", "~/other/.secret_scanner.py", "allow", "allow"),
    ("proj", "Read", "~/other/.env.foo", "allow", "allow"),
    ("proj", "Read", ".env.example", "allow", "allow"),
    ("proj", "Read", ".env.template", "allow", "allow"),
    ("proj", "Read", "src/db_password.py", "allow", "allow"),
    ("proj", "Read", "src/auth/ForgotPassword.tsx", "allow", "allow"),
    ("proj", "Read", "config/secrets/README.md", "allow", "allow"),
    ("proj", "Read", "app/reset-password.tsx", "allow", "allow"),
    ("proj", "Read", "README.md", "allow", "allow"),
    ("proj", "Read", ".password.py", "allow", "allow"),
    ("proj", "Read", ".secret_scanner.py", "allow", "allow"),
    ("proj", "Read", ".env.sample", "allow", "allow"),
    ("proj", "Read", ".env", "deny", "deny"),
    ("proj", "Read", ".env.local", "deny", "deny"),
    ("proj", "Read", "credentials.json", "deny", "deny"),
    ("proj", "Read", "src/secrets.py", "deny", "deny"),
    ("proj", "Read", "certs/server.pem", "deny", "deny"),
    ("proj", "Write", "~/.netrc", "ask", "deny"),
    ("proj", "Write", "~/.env", "ask", "deny"),
    ("proj", "Write", "~/.config/gh/hosts.yml", "ask", "deny"),
    ("proj", "Write", "~/.ssh/id_rsa", "ask", "deny"),
    ("proj", "Write", "~/other/.env.local", "ask", "deny"),
    ("proj", "Write", "~/notes2.txt", "ask", "ask"),
    ("proj", "Write", "~/.config/gh/config.yml", "ask", "ask"),
    ("proj", "Write", "~/other/src/x.py", "ask", "ask"),
    ("proj", "Write", ".env.example", "ask", "ask"),
    ("proj", "Bash", "cat ~/.aws/credentials", "allow", "deny"),
    ("proj", "Bash", "cat $HOME/.env", "allow", "deny"),
    ("proj", "Bash", "cat <HOME>/.netrc", "allow", "deny"),
    ("proj", "Bash", "cat ~/.ssh/id_ed25519", "allow", "deny"),
    ("proj", "Bash", "head ~/.config/gh/hosts.yml", "allow", "deny"),
    ("proj", "Bash", "cat ~/.docker/config.json", "allow", "deny"),
    ("proj", "Bash", "cat ~/.kube/config", "allow", "deny"),
    ("proj", "Bash", "cat $HOME/.pgpass", "allow", "deny"),
    ("proj", "Bash", "cat <HOME>/other/.env", "allow", "deny"),
    ("proj", "Bash", "cat ~/.bashrc", "allow", "allow"),
    ("proj", "Bash", "cat ~/.gitconfig", "allow", "allow"),
    ("proj", "Bash", "cat ~/notes.txt", "allow", "allow"),
    ("proj", "Bash", "cat $HOME/.ssh/id_rsa.pub", "allow", "allow"),
    ("proj", "Bash", "cat ~/.config/gh/config.yml", "allow", "allow"),
    ("proj", "Bash", "cat <HOME>/notes.txt", "allow", "allow"),
    ("home", "Read", "~/.aws/credentials", "deny", "deny"),
    ("home", "Read", "~/.env", "deny", "deny"),
    ("home", "Read", "~/.netrc", "allow", "deny"),
    ("home", "Read", "~/.docker/config.json", "allow", "deny"),
    ("home", "Read", "~/.kube/config", "allow", "deny"),
    ("home", "Read", "~/.config/gh/hosts.yml", "allow", "deny"),
    ("home", "Read", "~/.git-credentials", "allow", "deny"),
    ("home", "Read", "~/.pgpass", "allow", "deny"),
    ("home", "Read", "~/.ssh/id_rsa", "allow", "deny"),
    ("home", "Read", "~/.ssh/id_ed25519", "allow", "deny"),
    ("home", "Read", "~/.ssh/aws-key.pem", "deny", "deny"),
    ("home", "Read", "~/.env.local", "deny", "deny"),
    ("home", "Read", "~/secrets.yaml", "deny", "deny"),
    ("home", "Read", "~/password.txt", "deny", "deny"),
    ("home", "Read", "~/db_password", "deny", "deny"),
    ("home", "Read", "~/credentials.json", "deny", "deny"),
    ("home", "Read", "~/Downloads/client_secret_1.json", "deny", "deny"),
    ("home", "Read", "~/keypair.pem", "deny", "deny"),
    ("home", "Read", "~/other/.env", "deny", "deny"),
    ("home", "Read", "~/other/.env.production", "deny", "deny"),
    ("home", "Read", "~/other/.env.development.local", "deny", "deny"),
    ("home", "Read", "~/.env.foo", "deny", "deny"),
    ("home", "Read", "~/.password-store/x.gpg", "deny", "deny"),
    ("home", "Read", "~/other/config/credentials.yml", "deny", "deny"),
    ("home", "Read", "~/.secrets", "deny", "deny"),
    ("home", "Read", "~/.config/gcloud/credentials.db", "deny", "deny"),
    ("home", "Read", "~/.bashrc", "allow", "allow"),
    ("home", "Read", "~/.gitconfig", "allow", "allow"),
    ("home", "Read", "~/notes.txt", "allow", "allow"),
    ("home", "Read", "~/.ssh/id_rsa.pub", "allow", "allow"),
    ("home", "Read", "~/.ssh/config", "allow", "allow"),
    ("home", "Read", "~/.ssh/known_hosts", "allow", "allow"),
    ("home", "Read", "~/.config/gh/config.yml", "allow", "allow"),
    ("home", "Read", "~/.docker/daemon.json", "allow", "allow"),
    ("home", "Read", "~/.kube/cache/x.json", "allow", "allow"),
    ("home", "Read", "~/.aws/config", "allow", "allow"),
    ("home", "Read", "~/other/src/auth/ForgotPassword.tsx", "allow", "allow"),
    ("home", "Read", "~/other/src/db_password.py", "allow", "allow"),
    ("home", "Read", "~/other/config/secrets/README.md", "allow", "allow"),
    ("home", "Read", "~/other/.env.example", "allow", "allow"),
    ("home", "Read", "~/other/certs/ca.pem", "deny", "deny"),
    ("home", "Read", "~/Documents/talk.key", "deny", "deny"),
    ("home", "Read", "~/other/app/reset-password.tsx", "allow", "allow"),
    ("home", "Read", "~/other/.env.template", "allow", "allow"),
    ("home", "Read", "~/other/.password.py", "allow", "allow"),
    ("home", "Read", "~/other/.secret_scanner.py", "allow", "allow"),
    ("home", "Read", "~/other/.env.foo", "deny", "deny"),
    ("home", "Read", ".env.example", "allow", "allow"),
    ("home", "Read", ".env.template", "allow", "allow"),
    ("home", "Read", "src/db_password.py", "allow", "allow"),
    ("home", "Read", "src/auth/ForgotPassword.tsx", "allow", "allow"),
    ("home", "Read", "config/secrets/README.md", "allow", "allow"),
    ("home", "Read", "app/reset-password.tsx", "allow", "allow"),
    ("home", "Read", "README.md", "allow", "allow"),
    ("home", "Read", ".password.py", "allow", "allow"),
    ("home", "Read", ".secret_scanner.py", "allow", "allow"),
    ("home", "Read", ".env.sample", "allow", "allow"),
    ("home", "Read", ".env", "deny", "deny"),
    ("home", "Read", ".env.local", "deny", "deny"),
    ("home", "Read", "credentials.json", "deny", "deny"),
    ("home", "Read", "src/secrets.py", "deny", "deny"),
    ("home", "Read", "certs/server.pem", "deny", "deny"),
    ("home", "Write", "~/.netrc", "ask", "deny"),
    ("home", "Write", "~/.env", "deny", "deny"),
    ("home", "Write", "~/.config/gh/hosts.yml", "ask", "deny"),
    ("home", "Write", "~/.ssh/id_rsa", "ask", "deny"),
    ("home", "Write", "~/other/.env.local", "deny", "deny"),
    ("home", "Write", "~/notes2.txt", "ask", "ask"),
    ("home", "Write", "~/.config/gh/config.yml", "ask", "ask"),
    ("home", "Write", "~/other/src/x.py", "ask", "ask"),
    ("home", "Write", ".env.example", "ask", "ask"),
    ("home", "Bash", "cat ~/.aws/credentials", "deny", "deny"),
    ("home", "Bash", "cat $HOME/.env", "deny", "deny"),
    ("home", "Bash", "cat <HOME>/.netrc", "allow", "deny"),
    ("home", "Bash", "cat ~/.ssh/id_ed25519", "allow", "deny"),
    ("home", "Bash", "head ~/.config/gh/hosts.yml", "allow", "deny"),
    ("home", "Bash", "cat ~/.docker/config.json", "allow", "deny"),
    ("home", "Bash", "cat ~/.kube/config", "allow", "deny"),
    ("home", "Bash", "cat $HOME/.pgpass", "allow", "deny"),
    ("home", "Bash", "cat <HOME>/other/.env", "deny", "deny"),
    ("home", "Bash", "cat ~/.bashrc", "allow", "allow"),
    ("home", "Bash", "cat ~/.gitconfig", "allow", "allow"),
    ("home", "Bash", "cat ~/notes.txt", "allow", "allow"),
    ("home", "Bash", "cat $HOME/.ssh/id_rsa.pub", "allow", "allow"),
    ("home", "Bash", "cat ~/.config/gh/config.yml", "allow", "allow"),
    ("home", "Bash", "cat <HOME>/notes.txt", "allow", "allow"),
]


# ------------------------------------------------------------------ the CLI's matching, as measured
def _home_regex(body: str) -> re.Pattern:
    out, i = "", 0
    while i < len(body):
        if body.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif body[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif body[i] == "?":  # one character: OB-L08's `~/.?` ... `~/.?????` asks, measured so
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(body[i]), i + 1
    return re.compile(out, re.IGNORECASE)  # case: as OB-L19 measured for the cwd-anchored rules


def _home_rules(deny: list[str], tool: str) -> list[re.Pattern]:
    return [_home_regex(m.group(1)) for e in deny if (m := re.fullmatch(rf"{tool}\(~/(.*)\)", e))]


def home_denied(deny: list[str], tool: str, rel: str) -> bool:
    """`~/` rules, anchored at HOME, matched against the path or any directory above it (no `~/` lift)."""
    tools = ["Read"] if tool == "Read" else ["Read", "Edit"]
    parts = rel.split("/")
    prefixes = ["/".join(parts[:n]) for n in range(1, len(parts) + 1)]
    return any(rx.fullmatch(p) for t in tools for rx in _home_rules(deny, t) for p in prefixes)


def home_reached(rules: list[str], tool: str, rel: str) -> list[str]:
    """The `~/` Read/Edit entries of `rules` (any tier) that reach `rel`, matched as home_denied matches a deny."""
    return [e for e in rules if re.fullmatch(r"(?:Read|Edit)\(~/.*\)", e) and home_denied([e], tool, rel)]


def decide(deny: list[str], cwd: str, tool: str, rel: str) -> bool:
    """True when a rule refuses `tool` on `rel` (home-relative) with cwd = HOME or the project."""
    if home_denied(deny, tool, rel):
        return True
    if cwd == "home":
        return project_denied(deny, tool, rel)
    return rel.startswith(PROJ + "/") and project_denied(deny, tool, rel[len(PROJ) + 1:])


SPELLINGS = {"~": "~/", "$HOME": "$HOME/", "abs": "/home/u/"}


def bash_target(cmd: str) -> tuple[str, str]:
    """(tool, home-relative path) of a `cat`/`head` operand or a redirection target, in any spelling."""
    m = re.fullmatch(r".*\s>\s*(\S+)", cmd)  # a redirection, not the `>` of `<HOME>`
    tool, arg = ("Write", m.group(1)) if m else ("Read", cmd.split()[-1])
    for prefix in ("~/", "$HOME/", "<HOME>/", "/home/u/"):
        if arg.startswith(prefix):
            return tool, arg[len(prefix):]
    raise ValueError(cmd)


def _deny() -> list[str]:
    return json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]


def _l19(deny: list[str]) -> list[str]:
    """The deny list without this lane's `~/` entries: OB-L19's list."""
    return [e for e in deny if not re.fullmatch(r"(?:Read|Edit)\(~/.*\)", e)]


def _measured_decision(deny, cwd, tool, target):
    if tool == "Bash":
        tool, rel = bash_target(target)
    else:
        rel = target[2:] if target.startswith("~/") else f"{PROJ}/{target}"
    return decide(deny, cwd, tool, rel)


# ------------------------------------------------------------------ tests
@pytest.mark.parametrize("cwd,tool,target,base,now", MEASURED)
def test_model_reproduces_the_measured_decision(cwd, tool, target, base, now):
    got = _measured_decision(_deny(), cwd, tool, target)
    assert got == (now == "deny"), f"cwd={cwd} {tool} {target}: model {'deny' if got else 'not deny'}, CLI {now}"


@pytest.mark.parametrize("cwd,tool,target,base,now", MEASURED)
def test_model_reproduces_the_measured_l19_decision(cwd, tool, target, base, now):
    got = _measured_decision(_l19(_deny()), cwd, tool, target)
    assert got == (base == "deny"), f"cwd={cwd} {tool} {target}: model {'deny' if got else 'not deny'}, L19 {base}"


def test_the_home_entries_are_exactly_the_lane_list():
    deny = _deny()
    for tool in ("Read", "Edit"):
        got = [e[len(tool) + 1:-1] for e in deny if e.startswith(f"{tool}(~/")]
        assert got == HOME_PATTERNS, f"{tool}: {sorted(set(got) ^ set(HOME_PATTERNS))}"


@pytest.mark.parametrize("cwd", ["proj", "home"])
@pytest.mark.parametrize("rel", SECRET_FILES)
def test_home_secret_files_are_refused(rel, cwd):
    deny = _deny()
    assert decide(deny, cwd, "Read", rel), f"cwd={cwd}: Read ~/{rel} is not refused"
    assert decide(deny, cwd, "Write", rel), f"cwd={cwd}: a write of ~/{rel} is not refused"
    for spelling in SPELLINGS.values():
        tool, path = bash_target(f"cat {spelling}{rel}")
        assert decide(deny, cwd, tool, path), f"cwd={cwd}: cat {spelling}{rel} is not refused"
    tool, path = bash_target(f"echo x > ~/{rel}")
    assert decide(deny, cwd, tool, path), f"cwd={cwd}: echo x > ~/{rel} is not refused"


@pytest.mark.parametrize("rel", ORDINARY)
def test_ordinary_home_files_keep_their_decision(rel):
    """From a project, no rule refuses them: not on OB-L19's list, not now."""
    deny = _deny()
    assert not decide(deny, "proj", "Read", rel), f"Read ~/{rel} is refused"
    assert not decide(deny, "proj", "Write", rel), f"a write of ~/{rel} is refused"
    assert decide(deny, "home", "Read", rel) == decide(_l19(deny), "home", "Read", rel), f"cwd=home: ~/{rel} changed"


def _l19_project_paths() -> list[str]:
    paths = MUST_PASS + MUST_REFUSE + VERIFIER_DROP + KEPT_REFUSED + list(DELIBERATELY_OPEN)
    paths += [arg for tool, arg, *_ in L19_MEASURED if tool != "Bash"]
    deny = _deny()
    for entry in deny:
        if entry.startswith(("Read(!", "Edit(!")):
            paths += _lifted_names(entry[6:-1])
    return sorted({p for p in paths if not p.startswith("/")})


@pytest.mark.parametrize("path", _l19_project_paths())
def test_l19_project_decisions_are_unchanged(path):
    """Inside a project under HOME no `~/` entry refuses what OB-L19 opens, nor opens what it refuses.
    (With cwd = HOME itself, a TOP_LEVEL entry also refuses its name at the top of HOME where an L19 lift
    would open it, e.g. `~/db_password.py`, `~/secrets/README.md`: on purpose, see TOP_LEVEL.)"""
    deny = _deny()
    rel = f"{PROJ}/{path}"
    for tool in ("Read", "Write"):
        assert decide(deny, "proj", tool, rel) == decide(_l19(deny), "proj", tool, rel), f"{tool} {rel}"


def test_any_depth_entries_name_only_what_l19_never_lifts():
    """A `!` lift only reaches rules of its own anchor (measured), so a `~/**/` entry naming a name an
    L19 lift opens would refuse it inside every project under HOME."""
    for entry in _deny():
        m = re.fullmatch(r"(?:Read|Edit)\(~/\*\*/(.*)\)", entry)
        if m:
            assert m.group(1) in ANY_DEPTH, entry


def test_the_home_entries_sit_before_the_tail_and_lift_nothing():
    deny = _deny()
    first_lift = next(i for i, e in enumerate(deny) if e.startswith(("Read(!", "Edit(!")))
    home = [i for i, e in enumerate(deny) if re.fullmatch(r"(?:Read|Edit)\(~/.*\)", e)]
    assert home and max(home) < first_lift, "a `~/` entry sits inside OB-L19's ordered tail"
    assert not [e for e in deny if e.startswith(("Read(!~", "Edit(!~"))], "a `~/` negation exists"


def test_no_home_entry_refuses_a_whole_config_directory():
    """Config directories hold non-secret config agents read: only files are named, never a tree."""
    for entry in _deny():
        if re.fullmatch(r"(?:Read|Edit)\(~/.*\)", entry):
            assert not entry.endswith(("/**)", "/*)", "/)")), entry
    deny = _deny()
    for rel in (".ssh/config", ".ssh/known_hosts", ".ssh/id_ed25519.pub", ".config/gh/config.yml", ".aws/config",
                ".docker/daemon.json", ".kube/cache/discovery.json"):
        assert not home_denied(deny, "Read", rel), rel


# The secret names this lane refuses, as a `~/` rule body spells them: its deny patterns and its must-deny files.
REFUSED_NAMES = set(TOP_LEVEL + STORES + ANY_DEPTH + SECRET_FILES) | {f"**/{p}" for p in ANY_DEPTH}


def _home_entries(perms: dict, tier: str) -> list[str]:
    return [e for e in perms.get(tier, []) if re.fullmatch(r"(?:Read|Edit)\(~/.*\)", e)]


def test_no_allow_or_ask_rule_names_a_home_secret():
    """Deny is checked first whatever a rule's tier; still, keep allow/ask free of the names refused here.

    The `~/` allow stays `Read(~/**)` alone, the allow MEASURED was taken under. The ask may hold other `~/`
    rules (OB-L08's asks return writes of home dot-state, `Edit(~/.?)` ... `Edit(~/.wgetrc)`, to a prompt), but
    none names a secret name refused here (REFUSED_NAMES) unless it repeats this lane's deny entry word for word:
    OB-L08's `Edit(~/.pgpass)` is the deny `Edit(~/.pgpass)`, checked first, so the ask never decides
    (test_every_home_secret_deny_wins_over_any_ask)."""
    perms = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]
    assert _home_entries(perms, "allow") == ["Read(~/**)"], _home_entries(perms, "allow")
    named = [e for e in _home_entries(perms, "ask") if e[e.index("(") + 3:-1] in REFUSED_NAMES]
    unshadowed = [e for e in named if e not in perms["deny"]]
    assert unshadowed == [], unshadowed


def _exemplars(body: str) -> list[str]:
    """Home-relative files a `~/` deny body refuses: `*` read as `x`; a `**/` name at the top and one level down."""
    names = [body[3:], f"sub/{body[3:]}"] if body.startswith("**/") else [body]
    return [n.replace("*", "x") for n in names]


def test_every_home_secret_deny_wins_over_any_ask():
    """Deny is checked before ask ("Rules are evaluated in order: deny, then ask, then allow", permissions.md; OB-L08
    measured it on its own asks: with cwd = HOME a Write of `~/.aws/credentials`, which its ask `Edit(~/.???)`
    reaches, stays `deny`). So a file one of this lane's denies refuses (one file per deny pattern, and each
    SECRET_FILES path) stays refused, from a project and from HOME, whatever `~/` ask also reaches it. OB-L08's asks
    reach many of them (`~/.?????` covers `~/.netrc`, `~/.config` covers `~/.config/gh/hosts.yml`, `~/.pgpass` names
    `~/.pgpass`); without this lane's denies those asks would decide, and a write of `~/.pgpass` would prompt."""
    perms = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]
    deny, asks = perms["deny"], _home_entries(perms, "ask")
    targets = sorted({x for p in HOME_PATTERNS for x in _exemplars(p[2:])} | set(SECRET_FILES))
    for rel in targets:
        for tool in ("Read", "Write"):
            by = home_reached(asks, tool, rel)
            for cwd in ("proj", "home"):
                assert decide(deny, cwd, tool, rel), f"cwd={cwd} {tool} ~/{rel} is not refused (asked by {by})"
    for cwd in ("proj", "home"):  # e.g. the ask `Edit(~/.pgpass)`: this lane's deny refuses it, OB-L19's does not
        assert decide(deny, cwd, "Write", ".pgpass") and not decide(_l19(deny), cwd, "Write", ".pgpass"), cwd
