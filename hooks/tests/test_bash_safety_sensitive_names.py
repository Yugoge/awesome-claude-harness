"""OB-L14: bash-safety's sensitive-file rule BS-20/21 (audit BS-10/11) keeps the base's case-sensitive substring
check (`.env`, `credentials`, `secret`, `password`) over the full path of each parsed write target and each word or
read source of a command that writes a file, lifted only by hooks/lib/sensitive_names.py's narrow exemptions, each in
its role (test files; reports, logs and templates written; a template read by cp or cat; a URL given to a network
client; a code file copied onto a code-file name); quoted data and heredoc bodies are data, computed words keep the
check.

Every hook call runs pretool-bash-safety.sh with a scratch HOME, state dir and git config, an empty
protected-runtime file, and a throwaway repository as its working directory. No command is ever executed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402

WRITE = "Attempting to write to sensitive file via Bash"
READ = "Attempting to redirect from/to sensitive file via Bash"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("bash-safety-sensitive")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    (base / "gitconfig").write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    runtime = base / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(state), "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
           "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime)}
    (repo / "README.md").write_text("toy\n")
    for step in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    return {"env": env, "repo": str(repo)}


def run(sandbox, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "bash-safety-sensitive",
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"], cwd=sandbox["repo"], timeout=120)


# The lane's must-pass commands: a name that merely contains a secret word is no secret file.
MUST_PASS = [
    "cat > tests/test_password_reset.py <<'EOF'\ndef test_reset():\n    assert reset_password('x')\nEOF",
    "ls -la src/ > /tmp/secret-scan-report.txt",
    "python3 -m pytest tests/test_auth_password.py > /tmp/pytest.log 2>&1",
    "curl -s https://example.com/docs/password-policy > /tmp/policy.html",
    "cat > src/config.ts <<'EOF'\nexport const port = () => process.env.PORT;\nEOF",
]


@pytest.mark.parametrize("command", MUST_PASS)
def test_a_name_that_only_contains_a_secret_word_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# The lane's must-still-refuse commands, each with the refusal it gets.
MUST_REFUSE = [
    ("cat > .env <<'EOF'\nA=1\nEOF", WRITE),
    ("echo x > .env.local", WRITE),
    ("cat .env > x", READ),
    ("cat ~/.aws/credentials > x", READ),
    ("> .git-credentials", WRITE),
    ("> secrets.yaml", WRITE),
    ("> id_rsa", WRITE),
    ("> db_password", WRITE),
    ("> passwords.csv", WRITE),
]


@pytest.mark.parametrize("command,label", MUST_REFUSE)
def test_a_listed_secret_file_is_still_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("command", [
    "cat > .env <<'EOF'\nA=1",                       # unterminated: the parser cannot read it
    "cat > id_rsa <<'EOF'\n-----BEGIN KEY-----",
    "cat > tests/test_password_reset.py <<'EOF'\nx",  # unreadable, so judged by substring: refused more, never less
])
def test_a_heredoc_the_parser_cannot_read_falls_back_to_refusal(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 2 and WRITE in r.stderr, (command, r.stderr)


# P14-5 (search-09) already reads quoted data and heredoc bodies as data; pinned here.
@pytest.mark.parametrize("command", [
    'echo "see secret > file"',
    "echo 'cat .env > x'",
    "cat > notes.md <<'EOF'\nnever run: echo KEY=1 > .env\nEOF",
    "cat > docs/auth.md <<'EOF'\nlogin form -> password check > db_password\nEOF",
])
def test_a_secret_name_inside_quoted_data_or_a_heredoc_body_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# The write targets come from the parser, payloads and wrappers included.
@pytest.mark.parametrize("command,label", [
    ("bash -c 'echo x > .env'", WRITE),
    ('eval "echo x > ~/.ssh/id_ed25519"', WRITE),
    ("echo k | tee .env", WRITE),
    ("echo k | sudo tee -a .env.production", WRITE),
    ("cp .env.example .env", WRITE),
    ("echo x > ~/.claude/.credentials.json", WRITE),
    ('echo x > "$HOME/.env"', WRITE),
    ("echo x > .ENV", WRITE),
    ("sudo cat .env > out.txt", READ),
    ("cp .env /tmp/leak.txt", READ),
    ("sort < secrets.yaml > /tmp/sorted.txt", READ),
])
def test_a_parsed_write_or_read_of_a_secret_file_is_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


def test_the_list_is_one_reusable_definition():
    from lib.sensitive_names import is_sensitive_name
    listed = [".env", ".env.local", "config/prod.env", ".envrc", "credentials", "/home/u/.aws/credentials",
              ".git-credentials", ".credentials.json", "client_secret.json", "secrets.yaml", "secret.txt",
              "secrets.enc.yaml", "id_rsa", "id_ed25519", "~/.ssh/id_ecdsa", "db_password", "passwords.csv",
              ".ENV", "ID_RSA", "password-policy", "secrets.py", "password_reset.md", ".env-prod", ".env_prod",
              "prod.env.bak", "my.secret", "x.secret.json", "secrets/prod.yaml", "config/secrets/db",
              ".password-store/foo.gpg", "topsecret", "secrets.yaml.j2", "~/.ssh/id_rsa.bak", "tests/secrets/test_x.py"]
    unlisted = ["test_password_reset.py", "test_auth_password.py", "config.ts", "pytest.log", "policy.html",
                "id_rsa.pub", "environment.ts", "venv", "", "src/password.test.ts", "auth_password_test.go",
                # Case-sensitive as on the base: an upper-case word in a code or doc name is no secret file.
                "PASSWORD.TXT", "src/auth/ForgotPassword.tsx", "SECRET_KEY", "docs/SecretSauce.md"]
    assert [n for n in listed if not is_sensitive_name(n)] == []
    assert [n for n in unlisted if is_sensitive_name(n)] == []
    # The URL, report/log and template exemptions hold only in the role the caller names.
    roled = [("https://example.com/docs/password-policy", {"url": True}),
             ("secret-scan-report.txt", {"report": True}), ("/tmp/secret-build.log", {"report": True}),
             (".env.example", {"template": True})]
    assert [n for n, roles in roled if is_sensitive_name(n, **roles)] == []
    assert [n for n, _ in roled if not is_sensitive_name(n)] == []
    # A report or log whose stem is the secret word, a `report` inside another word, and `.dist` are no exemption.
    never = [".env.report", ".env.log", "credentials.report", "password.log", "secret.log", "secrets-report.yaml",
             "reporter-secret.txt", "password_reporter.py", "secret-reporting.txt", ".env.dist", "secrets.yaml.dist"]
    assert [n for n in never if not is_sensitive_name(n, report=True, template=True)] == []
    # A word computed at run time keeps the substring check on its raw text, with no exemption.
    computed = ['"$HOME/.env"', ".env$X", "$(echo .env)", "report-$(cat .env).log", "https://$H/password"]
    assert [n for n in computed if not is_sensitive_name(n, computed=True)] == []


# The verifier's regressions of the exact-name design: each was refused by the base's substring rule and stays
# refused (a name the secret word only begins or ends, a dot-separated name, a path under a secret directory, an
# unresolved word, a heredoc-fed shell, interpreter code, a read of such a file).
REGRESSIONS = [
    ("echo x > .env-prod", WRITE), ("echo x > .env_prod", WRITE), ("echo x > prod.env.bak", WRITE),
    ("echo x > secret_key", WRITE), ("echo x > secret_key.txt", WRITE), ("echo x > api-secret-key.json", WRITE),
    ("echo x > .secret_token", WRITE), ("echo x > secrets.yaml.j2", WRITE), ("echo x > secrets.tfvars", WRITE),
    ("echo x > credentials.json.tmp", WRITE), ("echo x > secretsmanager.json", WRITE), ("echo x > topsecret", WRITE),
    ("echo x > mysecrets.yaml", WRITE), ("echo x > credentials.py", WRITE), ("echo x > secret.sh", WRITE),
    ("echo x > my.secret", WRITE), ("echo x > x.secret.json", WRITE),
    ("echo x > secrets/prod.yaml", WRITE), ("echo x > config/secrets/db", WRITE),
    ("echo x > .credentials/token", WRITE), ("echo x > .password-store/foo.gpg", WRITE),
    ("echo x > tests/secrets/test_x.py", WRITE),
    ("cat secrets/prod.yaml > /tmp/x", READ),
    ("echo x > .env*", WRITE), ("echo x > {.env,x}", WRITE), ("echo x > .env$X", WRITE),
    ("echo x > $(echo .env)", WRITE), ("echo x > `echo .env`", WRITE), ("echo x > .env\\ ", WRITE),
    ("bash <<'EOF'\necho x > .env-prod\nEOF", WRITE),
    ("python3 -c 'print(open(\".env\").read())' > /tmp/x", READ),
    ("cat .env-prod > /tmp/x", READ),
    ("cp .env.example .env", WRITE),
    ("grep -n password config/secrets.yaml > /tmp/hits.txt", READ),  # a file the search reads, not its pattern
]


@pytest.mark.parametrize("command,label", REGRESSIONS)
def test_a_name_the_base_refused_by_substring_is_still_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


# A word counts only where it can be the source of what the redirect keeps (the owner's ruling of 2026-11-19): a
# search pattern and echo's own text are not files. Until then this was "an over-block the base had too; kept".
@pytest.mark.parametrize("command", [
    "grep -n password src/auth.py > /tmp/hits.txt",
    'grep -rn -E "token|password|secret" src docs > /tmp/hits.txt',
    'echo "rotate the password monthly" > /tmp/policy-note.txt',
])
def test_a_pattern_or_printed_text_is_no_secret_source(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# The exemptions lift the substring check only for a plain static name of these kinds.
@pytest.mark.parametrize("command", [
    "cp .env.example docs/env-example.txt",
    "echo x > /tmp/build.log",
    "cp src/password.ts dist/",
    "echo x > ~/.ssh/id_rsa.pub",
])
def test_an_exempt_name_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# A URL is no file name only as a network client's argument: a redirection or write target, or another command's
# operand, is a local path whatever its spelling.
URL_AS_LOCAL_PATH = [
    ("echo x > http://x/.env", WRITE),
    ("echo x > HTTP://x/.env", WRITE),
    ("echo x > file:///tmp/.env", WRITE),
    ("cat x > ftp://h/.aws/credentials", WRITE),
    ("cat x > HTTP://h/.aws/credentials", WRITE),
    ("mkdir -p http:/x && echo k > http://x/.env", WRITE),
    ("cat http://x/.env > /tmp/y", READ),
    ("cat file:///home/u/.env > /tmp/y", READ),
    ("cat https://x/.aws/credentials > /tmp/y", READ),
]


@pytest.mark.parametrize("command,label", URL_AS_LOCAL_PATH)
def test_a_url_spelled_local_path_is_still_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


# A report or log is exempt only as a write target with `report` as a whole token and a stem that is not the secret
# word itself; a template only without `.dist`, and as a read only for a cp or cat source.
NARROW_EXEMPTIONS = [
    ("echo x > .env.report", WRITE),
    ("echo x > .env.log", WRITE),
    ("echo x > credentials.report", WRITE),
    ("echo x > password.log", WRITE),
    ("echo x > secret.log", WRITE),
    ("echo x > secrets-report.yaml", WRITE),
    ("echo x > reporter-secret.txt", WRITE),
    ("echo x > password_reporter.json", WRITE),
    ("echo x > .env.dist", WRITE),
    ("cat credentials.report > /tmp/x", READ),
    ("cat .env.dist > /tmp/x", READ),
    ("grep KEY .env.example > /tmp/x", READ),
]


@pytest.mark.parametrize("command,label", NARROW_EXEMPTIONS)
def test_a_name_outside_the_narrowed_exemptions_is_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("command", [
    "cp src/password.ts dist/password.ts",
    "cat .env.example > /tmp/x",
    "curl -s https://example.com/.well-known/password-policy > /tmp/x.html",
])
def test_a_code_copy_a_template_read_or_a_network_url_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


def test_a_code_copy_into_a_secret_directory_is_still_refused(sandbox):
    r = run(sandbox, "cp src/password.ts secrets/password.ts")
    assert r.returncode == 2 and WRITE in r.stderr, r.stderr


# A `file:` URL (any case, with or without a host) and a URL with no host are local files to curl and wget, never
# a network fetch: the URL exemption does not cover them, whether the client's output goes to a redirection or to
# its own output option.
LOCAL_FILE_URLS = [
    ("curl file:///home/u/.aws/credentials > /tmp/y", READ),
    ("curl file:///home/u/.env > /tmp/y", READ),
    ("curl -s FILE:///etc/.env > /tmp/y", READ),
    ("wget file:///home/u/.env > /tmp/y", READ),
    ("curl file:///root/.ssh/id_rsa > /tmp/k", READ),
    ("curl file:///home/u/.env -o /tmp/y", READ),
    ("curl -s -o /tmp/y File:///home/u/.aws/credentials", READ),
    ("curl -s file://localhost/home/u/.env > /tmp/y", READ),
    ("curl -s file:/home/u/.env > /tmp/y", READ),
    ("curl -s http:///home/u/.env > /tmp/y", READ),
]


@pytest.mark.parametrize("command,label", LOCAL_FILE_URLS)
def test_a_local_file_url_given_to_a_network_client_is_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


# A network client that names its output file after the URL (wget without -O, curl -O, --remote-name,
# --remote-name-all or -J) writes ./.env or ./credentials: the URL exemption does not cover that URL.
URL_NAMES_THE_OUTPUT = [
    ("wget https://x/.env > /tmp/y", READ),
    ("wget -q https://x/.env > /dev/null", READ),
    ("wget https://x/credentials > /tmp/log", READ),
    ("curl -s -O https://x/.env > /tmp/log", READ),
    ("curl -sO https://x/.env > /tmp/log", READ),
    ("curl --remote-name https://x/.env > /tmp/log", READ),
    ("curl --remote-name-all https://x/.env > /tmp/log", READ),
    ("curl -s -J https://x/.env > /tmp/log", READ),
]


@pytest.mark.parametrize("command,label", URL_NAMES_THE_OUTPUT)
def test_a_url_that_names_the_clients_output_file_is_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


# A network URL fetched into a named output or standard output still passes.
@pytest.mark.parametrize("command", [
    "wget -qO- https://example.com/docs/password-policy > /tmp/p.html",
    "wget -q -O /tmp/p.html https://example.com/docs/password-policy > /tmp/wget.log",
    "curl -s -o /tmp/p.html https://example.com/docs/password-policy > /tmp/curl.log",
    "curl -s https://example.com/docs/password-policy -o /tmp/p.html",
])
def test_a_network_url_fetched_into_a_named_output_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# A private-key name is a key name alone or followed by a suffix that is no source-code or document extension.
@pytest.mark.parametrize("command", [
    "echo x > id_rsa.test.py",
    "cp docs/id_rsa.md /tmp/",
    "cp id_rsa_backup.txt /tmp/",
])
def test_a_code_or_doc_file_named_after_a_key_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("command,label", [
    ("echo x > id_rsa", WRITE),
    ("echo x > id_rsa.bak", WRITE),
    ("echo x > ~/.ssh/id_ed25519", WRITE),
    ("echo x > id_ecdsa_sk", WRITE),
    ("cp ~/.ssh/id_rsa /tmp/k", READ),
    ("cp ~/.ssh/id_rsa.old /tmp/k", READ),
])
def test_a_private_key_name_is_still_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


def test_the_url_exemption_excludes_local_file_urls_and_keys_are_exact():
    from lib.sensitive_names import is_sensitive_name
    local = ["file:///home/u/.env", "FILE:///etc/.env", "file://localhost/home/u/.env", "file:/home/u/.env",
             "http:///home/u/.env", "File:///root/.ssh/id_rsa"]
    assert [n for n in local if not is_sensitive_name(n, url=True)] == []
    assert not is_sensitive_name("https://example.com/docs/password-policy", url=True)
    keys = ["id_rsa", "id_rsa.bak", "~/.ssh/id_ed25519", "id_ecdsa_sk", "id_rsa.old", "id_dsa-2020"]
    assert [n for n in keys if not is_sensitive_name(n)] == []
    not_keys = ["id_rsa.pub", "id_rsa.test.py", "docs/id_rsa.md", "id_rsa_backup.txt", "id_rsa_parser.go"]
    assert [n for n in not_keys if is_sensitive_name(n)] == []


# A network client's option values are local paths (a cookie jar, a trace or header dump, an upload, a config
# file, `--data @file`), never URLs: `curl -c http://../.env URL` writes ./.env. Only a positional operand or a
# `--url` value is a URL, and a URL whose host is `.`, `..` or empty is a local path too.
OPTION_VALUES_ARE_PATHS = [
    "curl -s --trace-ascii http://../.env https://example.com > /tmp/log",
    "mkdir -p http: && curl -s -c http://../.env https://example.com > /tmp/log",
    "curl -s --cookie-jar http://x/.env https://example.com > /tmp/log",
    "curl -s -D http://x/.env https://example.com > /tmp/log",
    "curl -s --dump-header http://x/credentials https://example.com > /tmp/log",
    "curl -s --trace http://x/.env https://example.com > /tmp/log",
    "curl -s --libcurl http://x/.env https://example.com > /tmp/log",
    "curl -s --etag-save http://x/.env https://example.com > /tmp/log",
    "curl -s --stderr http://x/.env https://example.com > /tmp/log",
    "curl -s -T http://x/.env https://example.com > /tmp/log",
    "curl -s --upload-file http://x/.env https://example.com > /tmp/log",
    "curl -s -b http://x/.env https://example.com > /tmp/log",
    "curl -s --cookie http://x/.env https://example.com > /tmp/log",
    "curl -s -K http://x/.env https://example.com > /tmp/log",
    "curl -s --config http://x/.env https://example.com > /tmp/log",
    "curl -s --data @http://x/.env https://example.com > /tmp/log",
    "curl -sc http://x/.env https://example.com > /tmp/log",
    "curl -s --trace-asc http://x/.env https://example.com > /tmp/log",
    "curl -s http://../.env > /tmp/log",
    "curl -s http://./.env > /tmp/log",
    "curl -s --url http://../.env > /tmp/log",
]


@pytest.mark.parametrize("command", OPTION_VALUES_ARE_PATHS)
def test_a_network_clients_option_value_is_a_local_path(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 2 and READ in r.stderr, (command, r.stderr)


# httpie and xh read short-option clusters and unique long prefixes: each of these downloads ./.env. A cluster
# holding `d` beside a letter the table does not know takes the URL exemption away.
HTTPIE_DOWNLOADS = [
    "http -db https://x/.env > /tmp/log",
    "http -bd https://x/.env > /tmp/log",
    "http -dc https://x/.env > /tmp/log",
    "http --downl https://x/.env > /tmp/log",
    "xh -dF https://x/.env > /tmp/log",
    "http -dZ https://x/.env > /tmp/log",
]


@pytest.mark.parametrize("command", HTTPIE_DOWNLOADS)
def test_an_httpie_download_in_a_cluster_or_abbreviated_is_refused(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 2 and READ in r.stderr, (command, r.stderr)


# Case-sensitive as on the base, and an option of a copy (`--exclude .env`) is no source operand.
@pytest.mark.parametrize("command", [
    "cat > src/auth/ForgotPassword.tsx <<'EOF'\nexport const ForgotPassword = () => null;\nEOF",
    "cat > src/components/SecretBanner.tsx <<'EOF'\nexport const SecretBanner = () => null;\nEOF",
    "git diff > /tmp/Password-change.diff",
    "grep -rn SECRET_KEY src/ > /tmp/hits.txt",
    "echo x > docs/SecretSauce.md",
    "rsync -a --exclude=.env ./ /tmp/backup/",
    "rsync -a --exclude .env ./ /tmp/backup/",
    "curl -s --url https://example.com/docs/password-policy > /tmp/p.html",
    "curl -sSL --compressed -H 'Accept: text/html' https://example.com/docs/password-policy > /tmp/p.html",
    "xh -do /tmp/p.html https://example.com/docs/password-policy > /tmp/log",
])
def test_an_upper_case_word_or_a_copy_option_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("command,label", [
    ("echo x > .ENV", WRITE),
    ("echo x > ID_RSA", WRITE),
    ("rsync -a .env /tmp/backup/", READ),
    ("rsync -a --exclude .git .env /tmp/backup/", READ),
    ("cp -t /tmp .env", READ),
])
def test_an_exact_name_in_any_case_or_a_copy_operand_is_still_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


# curl's URL globbing builds the output name from the URL (`-o "#1"` after `{.env}` writes ./.env), and aria2c's
# -Z/--force-sequential and -i/--input-file ignore -o: the URL exemption does not cover those invocations. An output
# value holding `#`, or a URL holding a glob character without -g/--globoff, names the output after the URL.
URL_GLOB_OR_SEQUENTIAL = [
    'curl -s "https://example.com/{.env}" -o "#1" > /tmp/log',
    "curl -s https://x/{.env} -o '#1' > /tmp/log",
    'curl -s -o "#1" "https://example.com/{.env}" > /tmp/log',
    'curl -s -o "#1" "https://example.com/{.env}" 2> /tmp/err.log',
    'curl -s "https://example.com/{secrets.yaml}" -o "#1" > /tmp/log',
    'curl -s "https://example.com/{.env,a}" -o "#1" > /tmp/log',
    'curl -s -g "https://example.com/{.env}" -o "#1" > /tmp/log',
    'curl -s --globoff "https://example.com/{.env}" -o "x#1" > /tmp/log',
    'curl -s "https://example.com/[1-2]/.env" -o /tmp/out > /tmp/log',
    'curl -s -o /tmp/out "https://example.com/{.env}" > /tmp/log',
    'wget -O "#1" https://example.com/.env > /tmp/log',
    "aria2c -Z -o out https://x/.env > /tmp/log",
    "aria2c -o out -Z https://x/.env > /tmp/log",
    "aria2c --force-sequential=true -o out https://x/.env > /tmp/log",
    "aria2c --force-sequential -o out https://x/.env > /tmp/log",
    "aria2c -i list.txt -o out https://x/.env > /tmp/log",
    "aria2c -o out 'https://x/{.env,a}' > /tmp/log",
    "aria2c https://x/.env > /tmp/log",
]


@pytest.mark.parametrize("command", URL_GLOB_OR_SEQUENTIAL)
def test_a_globbed_url_or_a_sequential_aria2c_download_is_refused(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 2 and READ in r.stderr, (command, r.stderr)


# A client's config file can turn on an output named after the URL (a curl config holding `remote-name` writes
# ./.env), so curl -K/--config (any spelling, abbreviation or cluster), wget --config, aria2c --conf-path, and httpie
# or xh without -o/--output (their default options file can add --download) take the URL exemption away.
CONFIG_NAMES_OUTPUT = [
    "printf 'remote-name\\n' | curl -K - http://127.0.0.1:8000/.env > /tmp/log",
    "curl -K cfg http://127.0.0.1:8000/.env > /tmp/log",
    "curl -Kcfg http://127.0.0.1:8000/.env > /tmp/log",
    "curl -sK cfg http://127.0.0.1:8000/.env > /tmp/log",
    "curl --config cfg http://127.0.0.1:8000/.env > /tmp/log",
    "curl --config=cfg http://127.0.0.1:8000/.env > /tmp/log",
    "curl --conf cfg http://127.0.0.1:8000/.env > /tmp/log",
    "curl --confi cfg http://127.0.0.1:8000/.env > /tmp/log",
    "curl -s -o /tmp/out -K cfg http://127.0.0.1:8000/.env > /tmp/log",
    "wget -O - --config cfg http://127.0.0.1:8000/.env > /tmp/log",
    "aria2c --conf-path cfg -o out http://127.0.0.1:8000/.env > /tmp/log",
    "aria2c --conf-path=cfg -o out http://127.0.0.1:8000/.env > /tmp/log",
    "aria2c --conf cfg -o out http://127.0.0.1:8000/.env > /tmp/log",
    "http http://127.0.0.1:8000/.env > /tmp/log",
    "https https://x/.env > /tmp/log",
    "xh https://x/.env > /tmp/log",
]


@pytest.mark.parametrize("command", CONFIG_NAMES_OUTPUT)
def test_a_client_config_file_takes_the_url_exemption_away(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 2 and READ in r.stderr, (command, r.stderr)


# With globbing off and a literal output, or aria2c with -o alone, the URL exemption still holds.
@pytest.mark.parametrize("command", [
    'curl -s -g "https://example.com/docs/password-policy" -o /tmp/p.html > /tmp/log',
    "aria2c -o out https://example.com/.env > /tmp/log",
])
def test_a_literal_output_with_no_glob_keeps_the_url_exemption(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# The base never judged cp, mv, install, rsync, ln or sed -i without an output redirection: a source-code or
# Markdown/reST document operand of theirs whose directories carry no secret word passes again.
@pytest.mark.parametrize("command", [
    "sed -i 's/a/b/' src/password_reset.py",
    "mv docs/password-reset.md docs/pw.md",
    "cp docs/password-policy.md /tmp/x",
    "cp /tmp/x docs/password-policy.md",
    "cp src/auth/reset_password.ts /tmp/",
])
def test_a_code_or_doc_operand_of_a_copy_or_sed_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# The code/doc operand exemption never covers env, credential or key names, data files, a secret directory, a name
# whose stem is the secret word, nor a command whose output goes to a file reading such a name.
@pytest.mark.parametrize("command,label", [
    ("sed -i s/a/b/ .env", WRITE),
    ("sed -i s/a/b/ config/secrets.yaml", WRITE),
    ("cp /tmp/x secrets.md", WRITE),
    ("mv secrets/notes.md /tmp/x", READ),
    ("cp passwords.txt /tmp/x", READ),
    ("cp db_password.txt /tmp/x", READ),
    ("cp ~/.ssh/id_rsa /tmp/x.md", READ),
    ("sed -i s/a/b/ src/password_reset.py > /tmp/log", READ),
])
def test_the_code_or_doc_operand_exemption_stays_narrow(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


# The rule judges the act, not the name (live refusals of 2026-11-20). Writing a code or doc file whose name only
# holds a secret word, by any writer, is no secret write; a proven reader whose only redirections go to /dev/null or
# merge a stream opens no file, whatever it names.
@pytest.mark.parametrize("command", [
    "cat > /srv/work/scripts/release/check_secrets.py <<'EOF'\n#!/usr/bin/env python3\n"
    '"""Static scan; the .env is never opened."""\nprint("ok")\nEOF',
    "echo x | tee src/check_secrets.py",
    "echo x > password_reporter.py",
    "echo x > docs/password-reset.md",
    "date -u +%FT%TZ; echo --- env file tracked?; git -C /srv/work ls-files .env .env.example | head; "
    "ls -la /srv/work/.env 2>/dev/null | cut -c1-60",
    "ls -la /srv/work/.env 2>/dev/null",
    "git ls-files .env 2>&1 | head",
])
def test_a_secret_word_in_a_written_or_listed_name_is_no_secret_act(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# What the rule exists for stays refused: a redirection into, appending to or out of an env, credential, key or
# token file, or a read of one into a file; a code name whose stem is the secret word or under a secret directory.
@pytest.mark.parametrize("command,label", [
    ("cat > /srv/work/.env <<'EOF'\nA=1\nEOF", WRITE),
    ("echo A=1 >> .env 2>/dev/null", WRITE),
    ("echo x 2>&1 > ~/.ssh/id_ed25519", WRITE),
    ("echo t > .secret_token 2>/dev/null", WRITE),
    ("cat > secrets.py <<'EOF'\nKEY = 'x'\nEOF", WRITE),
    ("cat > config/secrets/check.py <<'EOF'\nx = 1\nEOF", WRITE),
    ("ls -la .env 2>/srv/work/err.txt", READ),
    ("cat .env 2>/dev/null > /srv/work/copy.txt", READ),
    ("sort < .env > /srv/work/sorted.txt 2>/dev/null", READ),
])
def test_a_secret_files_redirection_stays_refused_whatever_else_is_redirected(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)
