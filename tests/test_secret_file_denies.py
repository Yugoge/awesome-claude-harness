"""OB-L19: settings.json's secret-file Read/Edit denies name secret files, not substrings of any path.

The base globs `**/*password*`, `**/*secret*`, `**/credentials*` and `**/shadow` refused ordinary source
(`src/auth/ForgotPassword.tsx`, `src/secret_scanner.py`, `src/components/Shadow/index.tsx`) and every file
under a directory whose name held the word, and `**/.env.*` refused the committed templates
(`.env.example`). The list now refuses files by the shape of their NAME, whatever the extension:

* `password`, `passwords`, `password.*`, `passwords.*`, `.password*`, `*_password`, `*_password.*`,
  `*-password.*`; `secret`, `secrets`, `secret.*`, `secrets.*`, `.secret*`, `*_secret.*`, `*-secret.*`,
  `*_secrets.*`, `*-secrets.*`, `client_secret*.json`; `credentials`, `credentials.*`; `etc/shadow` at any
  depth (`//etc/shadow`, `//etc/passwd`, `**/passwd`, `**/.env`, `**/.env.*` kept);
* then, at the END of the deny list and in this order for each tool (last match wins, so the order is the
  contract; test_the_tail_keeps_its_order):
  1. directory lifts: `secret/`, `secrets/`, `password/`, `passwords/`, `*_password/` (a trailing `/`
     matches directories only: a FILE of that name stays refused, `auth/passwords/email.blade.php` opens);
  2. source and doc lifts: `!**/*password*.<ext>`, `!**/*secret*.<ext>`, `!**/*credentials*.<ext>` for
     SOURCE_EXT, never a data extension (`ForgotPassword`-style names: `forgot_password.dart`,
     `reset-password.tsx`, `client_secret.py`);
  3. re-denies of what no lift may open: `**/.env`, `**/.env.*` (else `.env.password.md` would open), and
     the bare stems `secret.*`, `secrets.*`, `*_secrets.*`, `*-secrets.*`, `credentials.*`, `password.*`,
     `passwords.*`: a file named after the secret itself is a likely secret store whatever its extension
     (`settings/secrets.py`, `config/credentials.rb`, `secrets.php`), so it stays refused as on the base;
  4. the three `.env` templates, last, so nothing after them closes them again.

Every refusal entry is a subset of what the base refused (test_the_new_names_only_narrow_the_old_globs).
What the base refused and this list opens on purpose is DELIBERATELY_OPEN, listed and justified.

How the CLI matches (code.claude.com/docs/en/permissions, "Read and Edit"): gitignore syntax, a bare name
or `**/name` at any depth under the current directory, `//path` from the filesystem root; deny before
allow, and an allow cannot carve an exception out of a deny; a Read deny also blocks Edit and Write on
the path; Edit rules apply to every built-in tool that edits files; Read and Edit denies apply to the
operands of file commands the CLI recognises in Bash (cat, head, ...) and to redirection targets.

What the docs leave out was measured on Claude Code 2.1.326 (Linux), offline: a throwaway HOME whose
user settings held only the `permissions` block under test (no hooks), a throwaway project, and
`claude -p` pointed through ANTHROPIC_BASE_URL at a local stand-in for the Messages API that answers the
first turn with one scripted tool call and records the tool_result the CLI sends back:

* matching is case-insensitive (`.ENV`, `Password.TXT`, `SECRETS.json` refused; negations too);
* a pattern's name also matches a directory, refusing every file under it ("File is in a directory that
  is denied");
* a `!` negation re-admits what an EARLIER rule of the same tool's list matched (last match wins): placed
  before the rule it lifts, it lifts nothing; alone it refuses nothing; Read negations do not lift Edit
  rules, so each list carries its own;
* `!**/passwords/` re-admits directories named `passwords` and their contents, never a file of that name;
  `!**/passwords/**` instead re-admitted the file `passwords` as well, so no lift uses that form;
* a name negation does NOT pierce a directory rule written `dir/**` (`.claude/hooks/**`, `**/vault/**`,
  `**/.harness-switch/**`: `<dir>/secrets.py` stays refused), but it DOES pierce one written `dir/*`
  (`vault2/*` let `vault2/secrets.py` through). No deny rule here ends in a single `/*`, and
  test_no_deny_rule_a_name_negation_could_pierce keeps it so;
* `[!...]` is not a negated class, so no rule uses brackets.

Precedence between tiers: the entries added here are deny rules and same-list negations only; no allow
or ask rule changed, so an exact-vs-wildcard tier ordering (measured by another lane for Bash rules) has
nothing to reorder: no deny is downgraded to ask or allow. The protected exact names and `/**` trees
measured still refused for writes (PROTECTED_WRITES) confirm the negations reach no other deny.

MEASURED is that run's table over this lane's examples, the independent verifier's list of base-refused
secret names, extra source names and the protected paths, on the base (origin/claude/train-c @ d1abc798)
and on this settings.json: `deny` is a refusal by a rule, `ask` a call headless `-p` could not approve,
`allow` a call that ran. The model below reproduces every measured decision.
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
    ("Read", "src/utils/password.ts", "deny", "deny"),
    ("Read", "src/secrets.py", "deny", "deny"),
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
    ("Read", "vault/secrets/db_password.txt", "deny", "deny"),
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
    ("Read", "secrets", "deny", "deny"),
    ("Read", "password", "deny", "deny"),
    ("Read", "passwords", "deny", "deny"),
    ("Read", "secret", "deny", "deny"),
    ("Read", "secrets.properties", "deny", "deny"),
    ("Read", "secrets.xml", "deny", "deny"),
    ("Read", "secrets.cfg", "deny", "deny"),
    ("Read", "secrets.conf", "deny", "deny"),
    ("Read", "secret.yaml", "deny", "deny"),
    ("Read", "secret.json", "deny", "deny"),
    ("Read", "secrets.local.yaml", "deny", "deny"),
    ("Read", "secrets.prod.json", "deny", "deny"),
    ("Read", "secrets.dev.yml", "deny", "deny"),
    ("Read", "app-secrets.yaml", "deny", "deny"),
    ("Read", "credentials.local.json", "deny", "deny"),
    ("Read", "credentials.properties", "deny", "deny"),
    ("Read", "credentials.yml.enc", "deny", "deny"),
    ("Read", "password.yml", "deny", "deny"),
    ("Read", "passwords.yaml", "deny", "deny"),
    ("Read", "user_password", "deny", "deny"),
    ("Read", "redis_password", "deny", "deny"),
    ("Read", "vault_password", "deny", "deny"),
    ("Read", ".password", "deny", "deny"),
    ("Read", ".passwords", "deny", "deny"),
    ("Read", "d/secrets/db.txt", "deny", "allow"),
    ("Read", "d/secrets/prod.env.json", "deny", "allow"),
    ("Read", "k8s/secrets/app.yaml", "deny", "allow"),
    ("Read", "d/credentials/gcp.json", "deny", "deny"),
    ("Read", "config/credentials/x.json", "deny", "deny"),
    ("Read", "d/password/x", "deny", "allow"),
    ("Read", "shadow", "deny", "allow"),
    ("Read", "db/shadow", "deny", "allow"),
    ("Read", "etc/shadow.bak", "allow", "allow"),
    ("Read", "client_secret.json", "deny", "deny"),
    ("Read", "api_secret.txt", "deny", "deny"),
    ("Read", "jwt-secret.txt", "deny", "deny"),
    ("Read", "SECRETS.YAML", "deny", "deny"),
    ("Read", "d/.env/inner", "deny", "deny"),
    ("Read", "secrets.yaml.bak", "deny", "deny"),
    ("Read", "passwd", "deny", "deny"),
    ("Read", "lib/features/forgot_password/forgot_password.dart", "deny", "allow"),
    ("Read", "app/reset-password.tsx", "deny", "allow"),
    ("Read", "src/auth/client_secret.py", "deny", "allow"),
    ("Read", "src/lib/credentials.ts", "deny", "deny"),
    ("Read", "docs/secrets.md", "deny", "deny"),
    ("Read", "src/secrets/index.ts", "deny", "allow"),
    ("Read", "src/password/index.ts", "deny", "allow"),
    ("Read", "lib/forgot_password/view.dart", "deny", "allow"),
    ("Read", "src/auth/passwords.rb", "deny", "deny"),
    ("Read", "docs/password-policy.md", "deny", "allow"),
    ("Read", "db-password.txt", "deny", "deny"),
    ("Read", "app_secrets.json", "deny", "deny"),
    ("Read", "secret.yml", "deny", "deny"),
    ("Read", "credentials.yaml", "deny", "deny"),
    ("Read", "src/credentials/index.ts", "deny", "deny"),
    ("Read", ".secret", "deny", "deny"),
    ("Read", "config/password.env", "deny", "deny"),
    ("Read", "secrets.py.bak", "deny", "deny"),
    ("Read", "x/user_password", "deny", "deny"),
    ("Write", ".claude/hooks/password_check.py", "deny", "deny"),
    ("Write", ".claude/scripts/secrets.md", "deny", "deny"),
    ("Write", ".claude/CLAUDE.md", "deny", "deny"),
    ("Write", ".claude/settings.json", "deny", "deny"),
    ("Write", "a/.harness-switch/password.py", "deny", "deny"),
    ("Read", ".env.password.md", "deny", "deny"),
    ("Write", "w/.env.password.md", "deny", "deny"),
    ("Bash", "cat .env.password.md", "deny", "deny"),
    ("Read", ".env.secrets.py", "deny", "deny"),
    ("Write", "w/.env.secrets.py", "deny", "deny"),
    ("Bash", "cat .env.secrets.py", "deny", "deny"),
    ("Read", ".env.secret.ts", "deny", "deny"),
    ("Write", "w/.env.secret.ts", "deny", "deny"),
    ("Bash", "cat .env.secret.ts", "deny", "deny"),
    ("Read", "app/.env.credentials.rb", "deny", "deny"),
    ("Write", "w/app/.env.credentials.rb", "deny", "deny"),
    ("Bash", "cat app/.env.credentials.rb", "deny", "deny"),
    ("Read", "settings/secrets.py", "deny", "deny"),
    ("Read", "local_secrets.py", "deny", "deny"),
    ("Read", "secrets.php", "deny", "deny"),
    ("Read", "secrets.ts", "deny", "deny"),
    ("Read", "config/credentials.rb", "deny", "deny"),
    ("Read", "credentials.md", "deny", "deny"),
    ("Read", "password.py", "deny", "deny"),
    ("Read", "passwords.html", "deny", "deny"),
    ("Read", "app-secrets.ts", "deny", "deny"),
    ("Read", "auth/passwords/.env", "deny", "deny"),
    ("Read", "auth/passwords/.env.local", "deny", "deny"),
    ("Read", "auth/passwords/a.key", "deny", "deny"),
    ("Read", "auth/passwords/a.pem", "deny", "deny"),
    ("Read", "auth/passwords/session_dirs.txt", "deny", "deny"),
    ("Read", "src/secrets/.env.prod", "deny", "deny"),
    ("Write", ".claude/hooks/passwords/x.py", "deny", "deny"),
    ("Write", "a/.harness-switch/passwords/x", "deny", "deny"),
    ("Write", ".claude/hooks/.env.example", "deny", "deny"),
    ("Write", "a/.harness-switch/.env.example", "deny", "deny"),
    ("Write", ".claude/scripts/forgot_password.py", "deny", "deny"),
    ("Read", "src/api_secret.ts", "deny", "allow"),
    ("Read", "src/jwt-secret.ts", "deny", "allow"),
    ("Read", "src/db_password.py", "deny", "allow"),
]

# The lane's examples (AUDIT §2 OB-L19 and the lane brief), plus source names the families must not catch.
MUST_PASS = ["src/auth/ForgotPassword.tsx", "src/secret_scanner.py", "docs/secrets-management.md", ".env.example",
             ".env.sample", ".env.template", "src/components/Shadow/index.tsx", "src/auth/CredentialsProvider.ts",
             "src/auth/password_reset.py", "app/reset-password.tsx", "src/auth/client_secret.py",
             "docs/password-policy.md", "lib/features/forgot_password/forgot_password.dart",
             "resources/views/auth/passwords/email.blade.php", "src/secrets/index.ts", "src/password/index.ts"]
MUST_REFUSE = [".env", ".env.local", ".env.staging", ".env.development", ".env.test", ".env.production",
               "config/secrets.yaml", "secrets.toml", "secrets.json", "credentials.json", ".aws/credentials",
               "config2/credentials", "password.txt", "db_password", "passwords.csv", "rootfs/etc/shadow",
               "/etc/shadow", "/etc/passwd", "certs/server.key", "certs/server.pem",
               # an unknown valued variant stays refused: only the three template names are re-admitted
               ".env.foo", ".env.example.local", ".env.development.local",
               # a `.env.*` name that also fits a source lift: the re-deny after the lifts keeps it refused
               ".env.password.md", ".env.secrets.py", ".env.secret.ts", "app/.env.credentials.rb"]
# Kept refused as on the base: a source or doc file named after the secret itself (the bare stems).
KEPT_REFUSED = ["src/secrets.py", "settings/secrets.py", "local_secrets.py", "secrets.php", "secrets.ts",
                "config/credentials.rb", "credentials.md", "src/lib/credentials.ts", "password.py",
                "src/utils/password.ts", "passwords.html", "src/auth/passwords.rb", "docs/secrets.md",
                "app-secrets.ts"]
# The independent verifier's list of secret names the base refused (scratchpad v19, drop_base.json).
VERIFIER_DROP = ["secrets", "password", "passwords", "secret", "secrets.properties", "secrets.xml", "secrets.cfg",
                 "secrets.conf", "secret.yaml", "secret.json", "secrets.local.yaml", "secrets.prod.json",
                 "secrets.dev.yml", "app-secrets.yaml", "credentials.local.json", "credentials.properties",
                 "credentials.yml.enc", "password.yml", "passwords.yaml", "user_password", "redis_password",
                 "vault_password", ".password", ".passwords", "d/secrets/db.txt", "d/secrets/prod.env.json",
                 "k8s/secrets/app.yaml", "d/credentials/gcp.json", "config/credentials/x.json", "d/password/x",
                 "shadow", "db/shadow", "etc/shadow.bak", "client_secret.json", "api_secret.txt", "jwt-secret.txt",
                 "SECRETS.YAML", "d/.env/inner", "secrets.yaml.bak", "passwd"]
# Refused on the base, readable now, on purpose:
DELIBERATELY_OPEN = {
    # a directory named secret(s)/password(s)/*_password is usually code (Laravel auth/passwords/, Flutter
    # features/forgot_password/, src/secrets/); the AUDIT names `ls config/secrets` as an over-block. Its
    # files stay refused where their own name is a secret name (vault/secrets/db_password.txt).
    "d/secrets/db.txt": "contents of a secrets/ directory",
    "d/secrets/prod.env.json": "contents of a secrets/ directory",
    "k8s/secrets/app.yaml": "contents of a secrets/ directory",
    "d/password/x": "contents of a password/ directory",
    # the shadow database is etc/shadow; `shadow` elsewhere is a component, a git object or a backup name
    "shadow": "shadow outside etc/",
    "db/shadow": "shadow outside etc/",
    "etc/shadow.bak": "not the shadow file's name (not refused on the base either)",
}
# Writes the name negations must not open: `/**` trees and exact names refused for other reasons.
PROTECTED_WRITES = [".claude/hooks/password_check.py", ".claude/scripts/secrets.md", ".claude/CLAUDE.md",
                    ".claude/settings.json", "a/.harness-switch/password.py", ".env"]
TEMPLATES = (".env.example", ".env.sample", ".env.template")
# The substring globs this lane retired; none of them may come back.
RETIRED = ["**/*password*", "**/*secret*", "**/credentials*", "**/shadow"]
# The base's file-name denies (both tools; *.key and *.pem were Read-only), for the no-widening check.
BASE_SECRET_RULES = RETIRED + ["**/*.key", "**/*.pem", "**/.env", "**/.env.*", "**/passwd", "**/session_dirs.txt",
                               ".env", "//etc/passwd", "//etc/shadow"]
# The base's other Edit denies the measured writes meet.
BASE_PROTECTED = [".claude/hooks/**", ".claude/scripts/**", ".claude/CLAUDE.md", ".claude/settings.json",
                  "**/.harness-switch/**"]
DIR_LIFTS = {"secret", "secrets", "password", "passwords", "*_password"}
DATA_EXT = {"json", "yaml", "yml", "toml", "env", "ini", "txt", "csv", "xml", "properties", "cfg", "conf", "enc",
            "bak", "key", "pem", "local"}


# ------------------------------------------------------------------ the CLI's documented matching, as measured
def _regex(pattern: str) -> tuple[re.Pattern, bool]:
    """gitignore pattern -> (regex over a project-relative path, or the absolute one for `//`, dir_only)."""
    dir_only = pattern.endswith("/") and not pattern.endswith("**/")
    pattern = pattern.rstrip("/") if dir_only else pattern
    if pattern.startswith("//"):
        body, prefix = pattern[2:], "/"
    else:
        body = pattern[2:] if pattern.startswith("./") else pattern
        prefix = "" if "/" in body else "(?:.*/)?"  # a bare name matches at any depth
    tree = body.endswith("/**")  # `dir/**` matches the directory itself too (measured: not pierceable)
    if tree:
        body = body[:-3]
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
    return re.compile(prefix + out + ("(?:/.*)?" if tree else ""), re.IGNORECASE), dir_only  # case: measured


def _rules(deny: list[str], tool: str):
    out = []
    for entry in deny:
        m = re.fullmatch(rf"{tool}\((.*)\)", entry)
        if m:
            pat = m.group(1)
            rx, dir_only = _regex(pat.lstrip("!"))
            out.append((pat.startswith("!"), rx, dir_only))
    return out


def _list_denies(rules, path: str) -> bool:
    """gitignore: last matching rule wins; a path under a matched directory is matched."""
    parts = path.lstrip("/").split("/")
    absolute = path.startswith("/")
    for n in range(1, len(parts) + 1):
        prefix = ("/" if absolute else "") + "/".join(parts[:n])
        is_dir = n < len(parts)
        hit = None
        for negated, rx, dir_only in rules:
            if (is_dir or not dir_only) and rx.fullmatch(prefix):
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


@pytest.mark.parametrize("tool,arg,base,now", MEASURED)
def test_model_reproduces_the_measured_base_decision(tool, arg, base, now):
    deny = ([f"Read({p})" for p in BASE_SECRET_RULES]
            + [f"Edit({p})" for p in BASE_SECRET_RULES if p not in ("**/*.key", "**/*.pem")]
            + [f"Edit({p})" for p in BASE_PROTECTED])
    got = bash_denied(deny, arg) if tool == "Bash" else denied(deny, tool, arg)
    assert got == (base == "deny"), f"{tool} {arg}: model says {'deny' if got else 'not deny'}, base measured {base}"


@pytest.mark.parametrize("path", MUST_PASS)
def test_ordinary_source_and_templates_are_not_refused(path):
    deny = _deny()
    assert not denied(deny, "Read", path), f"Read {path} is refused"
    assert not bash_denied(deny, f"grep -n TODO {path}"), f"grep -n TODO {path} is refused"
    assert not denied(deny, "Write", path), f"a write of {path} is refused"


@pytest.mark.parametrize("path", MUST_REFUSE)
def test_secret_files_stay_refused(path):
    deny = _deny()
    assert denied(deny, "Read", path), f"Read {path} is no longer refused"
    assert denied(deny, "Write", path), f"a write of {path} is no longer refused"
    assert bash_denied(deny, f"cat {path}"), f"cat {path} is no longer refused"
    assert bash_denied(deny, f"echo x > {path}"), f"echo x > {path} is no longer refused"
    assert denied(deny, "Read", path.upper()), f"Read {path.upper()} is no longer refused"


@pytest.mark.parametrize("path", VERIFIER_DROP)
def test_no_narrowing_beyond_intent(path):
    """Every base-refused secret name stays refused, except the listed and justified DELIBERATELY_OPEN."""
    deny = _deny()
    if path in DELIBERATELY_OPEN:
        assert not denied(deny, "Read", path), f"{path} is listed as open but refused; drop it from the list"
    else:
        assert denied(deny, "Read", path), f"Read {path} is no longer refused"
        assert denied(deny, "Write", path), f"a write of {path} is no longer refused"


@pytest.mark.parametrize("path", KEPT_REFUSED)
def test_files_named_after_the_secret_stay_refused(path):
    deny = _deny()
    assert denied(deny, "Read", path), f"Read {path} is no longer refused"
    assert denied(deny, "Write", path), f"a write of {path} is no longer refused"


@pytest.mark.parametrize("path", PROTECTED_WRITES)
def test_name_negations_open_no_protected_path(path):
    assert denied(_deny(), "Write", path), f"a write of {path} is no longer refused"


def _lifted_names(pat: str) -> list[str]:
    """Sample paths a negation pattern re-admits: a file name, or a file inside a lifted directory."""
    if pat.endswith("/"):
        return [pat[3:-1].replace("*", "db") + "/x"]
    return [pat[3:].replace("*", "db")]


def _guarded(name: str) -> list[tuple[str, str]]:
    """(tool, path) pairs that put a lifted name where another deny must still hold."""
    leaf = name.rsplit("/", 1)[-1]
    out = [("Read", f".env.{leaf}"), ("Write", f"w/.env.{leaf}"), ("Read", f".env.local/{name}"),
           ("Write", f".claude/hooks/{name}"), ("Write", f".claude/scripts/{name}"),
           ("Write", f"a/.harness-switch/{name}")]
    if name.endswith("/x"):  # inside a lifted directory: the files other rules name
        d = name[:-2]
        out += [("Read", f"{d}/.env"), ("Read", f"{d}/.env.local"), ("Read", f"{d}/a.key"), ("Read", f"{d}/a.pem"),
                ("Read", f"{d}/session_dirs.txt"), ("Write", f"{d}/.env.production")]
    return out


def _negation_cases():
    deny = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]
    pats = dict.fromkeys(e[6:-1] for e in deny if e.startswith(("Read(!", "Edit(!")))
    return [(p, tool, path) for p in pats for n in _lifted_names(p) for tool, path in _guarded(n)]


@pytest.mark.parametrize("pat,tool,path", _negation_cases())
def test_no_negation_opens_a_path_another_deny_holds(pat, tool, path):
    """For every negation, a name it lifts stays refused where it is also a `.env.*`, `*.key`/`*.pem`,
    `session_dirs.txt`, `.harness-switch` or protected `.claude/` path."""
    assert denied(_deny(), tool, path), f"!{pat} opens {tool} {path}"


def test_the_substring_globs_are_retired():
    deny = _deny()
    back = [f"{t}({p})" for t in ("Read", "Edit") for p in RETIRED if f"{t}({p})" in deny]
    assert not back, "substring secret globs are back: " + ", ".join(back)


REDENY = ["**/.env", "**/.env.*", "**/secret.*", "**/secrets.*", "**/*_secrets.*", "**/*-secrets.*",
          "**/credentials.*", "**/password.*", "**/passwords.*"]


@pytest.mark.parametrize("tool", ["Read", "Edit"])
def test_the_tail_keeps_its_order(tool):
    """Last match wins (measured): per tool, the lifts, then the re-denies, then the templates, last."""
    rules = [e[len(tool) + 1:-1] for e in _deny() if e.startswith(tool + "(")]
    first = next(i for i, p in enumerate(rules) if p.startswith("!"))
    tail = rules[first:]
    templates = [f"!**/{t}" for t in TEMPLATES]
    assert tail[-3:] == templates, f"{tool}: the .env templates are not the last three entries"
    lifts_end = max(i for i, p in enumerate(tail) if p.startswith("!") and p not in templates)
    assert tail[lifts_end + 1:-3] == REDENY, f"{tool}: the re-denies do not follow the last lift"
    assert all(p.startswith("!") for p in tail[:lifts_end + 1]), f"{tool}: a refusal sits among the lifts"


def test_negations_lift_only_templates_name_directories_and_source():
    """No negation re-admits a data file: each lifts a template, a directory, or a source/doc extension."""
    for entry in _deny():
        m = re.fullmatch(r"(?:Read|Edit)\(!(.*)\)", entry)
        if not m:
            continue
        pat = m.group(1)
        if pat in {f"**/{t}" for t in TEMPLATES}:
            continue
        if pat.endswith("/"):
            assert pat.startswith("**/") and pat[3:-1] in DIR_LIFTS, entry
            continue
        ext = pat.rsplit(".", 1)[-1]
        assert ext not in DATA_EXT and re.fullmatch(r"\*\*/\*(password|secret|credentials)\*\.[a-z]+", pat), entry


def test_no_deny_rule_a_name_negation_could_pierce():
    """A name negation pierces `dir/*` (measured) but not `dir/**`: keep every directory deny in `/**` form."""
    single = [e for e in _deny() if re.search(r"/\*\)$", e) and not e.endswith("/**)")]
    assert not single, "deny rules a trailing name negation would pierce: " + ", ".join(single)


def test_read_and_edit_name_the_same_secret_files():
    deny = _deny()
    read = [e[5:-1] for e in deny if e.startswith("Read(")]
    edit = [e[5:-1] for e in deny if e.startswith("Edit(")]
    read_only = {"**/*.key", "**/*.pem", "**/session_dirs.txt"}  # as before; a Read deny blocks writes as well
    assert set(read) - read_only <= set(edit), sorted(set(read) - read_only - set(edit))
    assert [p for p in read if p.startswith("!")] == [p for p in edit if p.startswith("!")]


def test_the_new_names_only_narrow_the_old_globs():
    """Every refusal entry names what the base list already refused: nothing widened."""
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
