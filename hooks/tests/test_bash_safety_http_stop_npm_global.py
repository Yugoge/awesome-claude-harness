"""OB-L15: the HTTP /stop rule and the package-manager global-op rule, through the real hook entry.

The HTTP /stop rule (BS-02, search-15) refuses a request to a localhost port's /stop path segment only when the
command runs an HTTP client (or an interpreter calling an HTTP library); a mention, or a /stops or /stopwords
path, passes. The runtime guard's global-op rule (BS-20) reads every global form: flags (`-g`, `--global`,
`--location=global`, ...), `config set global true`, `yarn global`, and `npm_config_global` / `npm_config_location`
in the package manager's environment (prefix, `env`, `sudo`, `export` earlier in the text, nested `bash -c`).

Every call runs pretool-bash-safety.sh on a PreToolUse payload with a scratch HOME, state dir, git config and an
empty protected-runtime file. No command is ever executed.
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


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("ob-l15")
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
    subprocess.run(["git", "init", "-q", "-b", "master"], cwd=repo, env=env, check=True, capture_output=True)
    return {"env": env, "repo": str(repo)}


def run(sandbox, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "ob-l15",
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"], cwd=sandbox["repo"], timeout=120)


HTTP_STOP_ALLOWED = [
    "curl -s http://localhost:8000/stops/42",
    "curl -s http://127.0.0.1:5000/stopwords?lang=en",
    "grep -n 'localhost:8080/stop' tests/test_requests_client.py",
    "rg -n ':8080/stop' src/",
    "echo 'see http://localhost:8080/stop docs'",
]
HTTP_STOP_REFUSED = [
    "curl -X POST http://localhost:8080/stop",
    "python3 -c 'import requests; requests.post(\"http://localhost:8080/stop\")'",
    "http POST localhost:8080/stop",
    "xh post :8080/stop",
    "wget -qO- http://127.0.0.1:9000/stop?now=1",
    "timeout 5 curl localhost:8080/stop/",
    "URL=http://localhost:8080/stop; curl -X POST $URL",
    "echo localhost:8080/stop | xargs curl -X POST",
    "eval 'curl -X POST localhost:8080/stop'",
    "python3 - <<EOF\nimport requests\nrequests.post('http://localhost:8080/stop')\nEOF",
]
NPM_ALLOWED = [
    "npm install --save-dev eslint-config-google",
    "npm i node-gyp",
    "pnpm i -D vite-plugin-gzip",
    "NPM_CONFIG_GLOBAL=false npm i x",
    "npm install --global=false x",
    "npm i --location=project x",
    "npm config get global",
    "npm config set registry https://registry.example.invalid",
    "export NPM_CONFIG_GLOBAL=true; ls",
    "echo NPM_CONFIG_GLOBAL=true",
]
NPM_REFUSED = [
    "npm i -g foo",
    "npm install --global foo",
    "npm i --location=global foo",
    'bash -c "npm i -g foo"',
    "npm i --location global foo",
    "npm --global=true i foo",
    "npm config set global true",
    "npm config set location global",
    "yarn global add foo",
    # section 5, BS-20: the environment makes the install global
    "NPM_CONFIG_GLOBAL=true npm install left-pad",
    "npm_config_global=1 npm i x",
    "env NPM_CONFIG_GLOBAL=true npm i x",
    "export NPM_CONFIG_GLOBAL=true; npm i x",
    "export NPM_CONFIG_GLOBAL=true && npm i x",
    "NPM_CONFIG_LOCATION=global npm i x",
    "npm_config_location=global npm i x",
    "sudo NPM_CONFIG_GLOBAL=true npm i x",
    "declare -x NPM_CONFIG_GLOBAL=true; npm i x",
    "bash -c 'export NPM_CONFIG_LOCATION=global; npm i x'",
    "NPM_CONFIG_GLOBAL=true pnpm add x",
]


@pytest.mark.parametrize("command", HTTP_STOP_ALLOWED + NPM_ALLOWED)
def test_allowed(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("command", HTTP_STOP_REFUSED)
def test_http_stop_refused(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 2 and "daemon-restart-http-stop" in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("command", NPM_REFUSED)
def test_global_package_op_refused(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 2 and "protected-runtime-guard" in r.stderr, (command, r.stderr)
