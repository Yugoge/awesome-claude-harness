"""OB-L19: settings.json's secret-file Read/Edit denies name real secret files, not substrings.

The old globs `**/*password*`, `**/*secret*`, `**/credentials*` and `**/shadow` refused ordinary source
(`src/auth/ForgotPassword.tsx`, `src/secret_scanner.py`, `src/components/Shadow/index.tsx`) and every file
under a directory whose name held the word, and `**/.env.*` refused the committed templates
(`.env.example`). The list now names the secret files themselves; `**/.env.*` stays, and the three
template names are taken back out of it by gitignore negations listed after it.

How the CLI matches (code.claude.com/docs/en/permissions, "Read and Edit"): gitignore syntax, a bare name
or `**/name` at any depth under the current directory, `//path` from the filesystem root; deny before
allow, and an allow cannot carve an exception out of a deny; a Read deny also blocks Edit and Write on
the path; Edit rules apply to every built-in tool that edits files; Read and Edit denies apply to the
operands of file commands the CLI recognises in Bash (cat, head, ...) and to redirection targets.

What the docs leave out was measured on Claude Code 2.1.326 (Linux), offline: a throwaway HOME whose
user settings held only the `permissions` block under test (no hooks), a throwaway project, and
`claude -p` pointed through ANTHROPIC_BASE_URL at a local stand-in for the Messages API that answers the
first turn with one scripted tool call and records the tool_result the CLI sends back:

* matching is case-insensitive: `Read(**/.env)` refuses `.ENV` and `.Env`, `Read(**/password.txt)`
  refuses `Password.TXT`, `Read(**/secrets.*)` refuses `SECRETS.json`;
* a pattern's name also matches a directory, refusing every file under it (`Read(**/credentials)`
  refuses `src/credentials/index.ts`; the refusal reads "File is in a directory that is denied");
* a `!` negation in the deny list re-admits what an EARLIER rule of the same list matched (last match
  wins, as in a .gitignore): `Read(**/.env.*)` then `Read(!**/.env.example)` admits `.env.example` and
  `x/.env.example` and still refuses `.env.local` and `.env.foo`; the same two in the other order refuse
  `.env.example`; a negation alone refuses nothing; Read negations do not lift `Edit(**/.env.*)`, so
  each list carries its own;
* `[!...]` is not a negated class (`Read(**/.env.[!est]*)` refused `.env.example` and admitted
  `.env.local`), so no rule here uses brackets.

MEASURED is that run's table over this lane's examples, base (origin/claude/train-c @ d1abc798) and this
settings.json: `deny` is a refusal by a rule, `ask` a call headless `-p` could not approve, `allow` a call
that ran. The model below reproduces the measured decisions and the tests hold settings.json to it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# (tool, path or command, base decision, decision with this settings.json): Claude Code 2.1.326, measured.
MEASURED = [
    ("Read", "src/auth/ForgotPassword.tsx", "deny", "allow"),
    ("Read", "src/secret_scanner.py", "deny", "allow"),
    ("Read", "docs/secrets-management.md", "deny", "allow"),
    ("Read", ".env.example", "deny", "allow"),
    ("Read", ".env.sample", "deny", "allow"),
    ("Read", ".env.template", "deny", "allow"),
    ("Read", "src/components/Shadow/index.tsx", "deny", "allow"),
    ("Read", "src/auth/CredentialsProvider.ts", "deny", "allow"),
    ("Read", "app/forgot-password/page.tsx", "deny", "allow"),
    ("Read", "resources/views/auth/passwords/email.blade.php", "deny", "allow"),
    ("Read", "config/secrets/README.md", "deny", "allow"),
    ("Read", "lib/features/forgot_password/view.dart", "deny", "allow"),
    ("Read", "src/utils/password.ts", "deny", "allow"),
    ("Read", "src/secrets.py", "deny", "allow"),
    ("Read", ".env", "deny", "deny"),
    ("Read", ".env.local", "deny", "deny"),
    ("Read", ".env.staging", "deny", "deny"),
    ("Read", ".env.development", "deny", "deny"),
    ("Read", ".env.test", "deny", "deny"),
    ("Read", ".env.production", "deny", "deny"),
    ("Read", ".env.foo", "deny", "deny"),
    ("Read", ".env.development.local", "deny", "deny"),
    ("Read", ".env.example.local", "deny", "deny"),
    ("Read", "app/.env.prod", "deny", "deny"),
    ("Read", ".ENV.STAGING", "deny", "deny"),
    ("Read", "config/secrets.yaml", "deny", "deny"),
    ("Read", "secrets.toml", "deny", "deny"),
    ("Read", "secrets.json", "deny", "deny"),
    ("Read", "credentials.json", "deny", "deny"),
    ("Read", ".aws/credentials", "deny", "deny"),
    ("Read", "config2/credentials", "deny", "deny"),
    ("Read", "password.txt", "deny", "deny"),
    ("Read", "db_password", "deny", "deny"),
    ("Read", "passwords.csv", "deny", "deny"),
    ("Read", "rootfs/etc/shadow", "deny", "deny"),
    ("Read", "etc/shadow", "deny", "deny"),
    ("Read", "certs/server.key", "deny", "deny"),
    ("Read", "certs/server.pem", "deny", "deny"),
    ("Read", "Password.TXT", "deny", "deny"),
    ("Read", "secrets/db_password.txt", "deny", "deny"),
    ("Read", "client_secret_123.apps.googleusercontent.com.json", "deny", "deny"),
    ("Read", "credentials.csv", "deny", "deny"),
    ("Read", ".secrets", "deny", "deny"),
    ("Read", "/etc/shadow", "deny", "deny"),
    ("Read", "/etc/passwd", "deny", "deny"),
    ("Write", ".env.example", "deny", "ask"),
    ("Write", ".env.sample", "deny", "ask"),
    ("Write", ".env.template", "deny", "ask"),
    ("Write", "src/auth/ForgotPassword2.tsx", "deny", "ask"),
    ("Write", "src/components/Shadow/new.tsx", "deny", "ask"),
    ("Write", ".env.staging2", "deny", "deny"),
    ("Write", ".env", "deny", "deny"),
    ("Write", ".env.production", "deny", "deny"),
    ("Write", "config/secrets.yaml", "deny", "deny"),
    ("Write", "secrets.toml", "deny", "deny"),
    ("Write", "credentials.json", "deny", "deny"),
    ("Write", "config2/credentials", "deny", "deny"),
    ("Write", "password.txt", "deny", "deny"),
    ("Write", "db_password", "deny", "deny"),
    ("Write", "rootfs/etc/shadow", "deny", "deny"),
    ("Write", "new.key", "deny", "deny"),
    ("Bash", "grep -n TODO src/auth/password_reset.py", "deny", "allow"),
    ("Bash", "cat .env.staging", "deny", "deny"),
    ("Bash", "cat .env.example", "deny", "allow"),
    ("Bash", "cat config/secrets.yaml", "deny", "deny"),
    ("Bash", "head .aws/credentials", "deny", "deny"),
    ("Bash", "cat src/secret_scanner.py", "deny", "allow"),
    ("Bash", "echo x > .env.local", "deny", "deny"),
    ("Bash", "echo x > .env.template", "deny", "ask"),
]

# The lane's examples (AUDIT §2 OB-L19 and the lane brief).
MUST_PASS = ["src/auth/ForgotPassword.tsx", "src/secret_scanner.py", "docs/secrets-management.md", ".env.example",
             ".env.sample", ".env.template", "src/components/Shadow/index.tsx", "src/auth/CredentialsProvider.ts",
             "src/auth/password_reset.py"]
MUST_REFUSE = [".env", ".env.local", ".env.staging", ".env.development", ".env.test", ".env.production",
               "config/secrets.yaml", "secrets.toml", "secrets.json", "credentials.json", ".aws/credentials",
               "config2/credentials", "password.txt", "db_password", "passwords.csv", "rootfs/etc/shadow",
               "/etc/shadow", "/etc/passwd", "certs/server.key", "certs/server.pem",
               # an unknown valued variant stays refused: only the three template names are re-admitted
               ".env.foo", ".env.example.local", ".env.development.local"]
TEMPLATES = (".env.example", ".env.sample", ".env.template")
# The substring globs this lane retired; none of them may come back.
RETIRED = ["**/*password*", "**/*secret*", "**/credentials*", "**/shadow"]
# The base's file-name denies (both tools; *.key and *.pem were Read-only), for the no-widening check.
BASE_SECRET_RULES = RETIRED + ["**/*.key", "**/*.pem", "**/.env", "**/.env.*", "**/passwd", "**/session_dirs.txt",
                               ".env", "//etc/passwd", "//etc/shadow"]


# ------------------------------------------------------------------ the CLI's documented matching, as measured
def _regex(pattern: str) -> re.Pattern:
    """gitignore pattern -> regex over a path relative to the project (`//` ones over the absolute path)."""
    if pattern.startswith("//"):
        body, prefix = pattern[2:], "/"
    else:
        body = pattern[2:] if pattern.startswith("./") else pattern
        prefix = "" if "/" in body.rstrip("/") else "(?:.*/)?"  # a bare name matches at any depth
    out, i = "", 0
    while i < len(body):
        if body.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif body.startswith("**", i):
            out, i = out + ".*", i + 2
        elif body[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif body[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(body[i]), i + 1
    return re.compile(prefix + out, re.IGNORECASE)  # case-insensitive: measured


def _rules(deny: list[str], tool: str) -> list[tuple[bool, re.Pattern]]:
    out = []
    for entry in deny:
        m = re.fullmatch(rf"{tool}\((.*)\)", entry)
        if m:
            pat = m.group(1)
            out.append((pat.startswith("!"), _regex(pat.lstrip("!"))))
    return out


def _list_denies(rules, path: str) -> bool:
    """gitignore: last matching rule wins; a path under a matched directory is matched."""
    parts = path.lstrip("/").split("/")
    absolute = path.startswith("/")
    for n in range(1, len(parts) + 1):
        prefix = ("/" if absolute else "") + "/".join(parts[:n])
        hit = None
        for negated, rx in rules:
            if rx.fullmatch(prefix):
                hit = not negated
        if hit:
            return True
    return False


def denied(deny: list[str], tool: str, path: str) -> bool:
    """A Read is held to the Read list; Edit and Write to both lists (a Read deny blocks writes too)."""
    tools = ["Read"] if tool == "Read" else ["Read", "Edit"]
    return any(_list_denies(_rules(deny, t), path) for t in tools)


def bash_denied(deny: list[str], cmd: str) -> bool:
    """A recognised file command's operand is held to the Read list, a redirection target to both."""
    m = re.fullmatch(r".*>\s*(\S+)", cmd)
    if m:
        return denied(deny, "Write", m.group(1))
    return denied(deny, "Read", cmd.split()[-1])


def _deny() -> list[str]:
    return json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]


# ------------------------------------------------------------------ tests
@pytest.mark.parametrize("tool,arg,base,now", MEASURED)
def test_model_reproduces_the_measured_decision(tool, arg, base, now):
    deny = _deny()
    got = bash_denied(deny, arg) if tool == "Bash" else denied(deny, tool, arg)
    assert got == (now == "deny"), f"{tool} {arg}: model says {'deny' if got else 'not deny'}, CLI measured {now}"


@pytest.mark.parametrize("path", MUST_PASS)
def test_ordinary_source_and_templates_are_not_refused(path):
    deny = _deny()
    assert not denied(deny, "Read", path), f"Read {path} is refused"
    assert not bash_denied(deny, f"grep -n TODO {path}"), f"grep -n TODO {path} is refused"


@pytest.mark.parametrize("path", TEMPLATES + ("src/auth/ForgotPassword.tsx", "src/components/Shadow/index.tsx"))
def test_templates_and_source_can_be_edited(path):
    assert not denied(_deny(), "Write", path), f"a write of {path} is refused"


@pytest.mark.parametrize("path", MUST_REFUSE)
def test_secret_files_stay_refused(path):
    deny = _deny()
    assert denied(deny, "Read", path), f"Read {path} is no longer refused"
    assert denied(deny, "Write", path), f"a write of {path} is no longer refused"
    assert bash_denied(deny, f"cat {path}"), f"cat {path} is no longer refused"
    assert bash_denied(deny, f"echo x > {path}"), f"echo x > {path} is no longer refused"


@pytest.mark.parametrize("path", MUST_REFUSE)
def test_secret_files_stay_refused_in_any_case(path):
    assert denied(_deny(), "Read", path.upper())


def test_the_substring_globs_are_retired():
    deny = _deny()
    back = [f"{t}({p})" for t in ("Read", "Edit") for p in RETIRED if f"{t}({p})" in deny]
    assert not back, "substring secret globs are back: " + ", ".join(back)


def test_each_negation_follows_the_rule_it_lifts():
    """Last match wins: a negation listed before `<Tool>(**/.env.*)` lifts nothing (measured)."""
    deny = _deny()
    for tool in ("Read", "Edit"):
        positive = deny.index(f"{tool}(**/.env.*)")
        negations = [i for i, e in enumerate(deny) if e.startswith(f"{tool}(!")]
        assert sorted(deny[i] for i in negations) == sorted(f"{tool}(!**/{t})" for t in TEMPLATES)
        assert all(i > positive for i in negations), f"a {tool} negation precedes {tool}(**/.env.*)"


def test_read_and_edit_name_the_same_secret_files():
    deny = _deny()
    read = {e[5:-1] for e in deny if e.startswith("Read(")}
    edit = {e[5:-1] for e in deny if e.startswith("Edit(")}
    read_only = {"**/*.key", "**/*.pem"}  # Read-only as before; a Read deny blocks writes as well
    assert read - read_only - {"**/session_dirs.txt"} <= edit, sorted(read - read_only - edit)


def test_the_new_names_only_narrow_the_old_globs():
    """Every secret entry is a name the retired globs (or a kept rule) already refused: nothing widened."""
    widened = []
    for tool in ("Read", "Edit"):
        old = [f"{tool}({p})" for p in BASE_SECRET_RULES]
        for entry in _deny():
            m = re.fullmatch(rf"{tool}\(((?:\*\*/|//|\.)[^!].*)\)", entry)
            if m and not entry.startswith(("Edit(.claude/", "Edit(**/.harness-switch/")):
                sample = m.group(1).removeprefix("**/").replace("*", "x")
                if not _list_denies(_rules(old, tool), "/" + sample[2:] if sample.startswith("//") else sample):
                    widened.append(f"{entry} ({sample})")
    assert not widened, "entries refusing what the base list did not: " + ", ".join(widened)
