"""Text a command only writes into a file is data to the git privilege guard; what a command runs is an act.

A live call wrote a Markdown report with `cat > <absolute path> <<'EOF'`; the report quoted git commands in
backquotes (`git commit -qm base`), and the command went on with `cd <dir> && tail ... | cut ...`. The guard
read the quoted body as shell code and refused the call as an agent commit: its rule for a here-document written
to a file (_written_file_is_data in hooks/lib/git_command_classifier.py) took an absolute path outside the
project and the temp roots for a file a tool runs, and `cd` and `cut` for commands that may run the file. The
`-c` string scan (_shell_words) read the same body as data, so the two readings disagreed. Both now ask the one
question, and the call passes; each way the text is run is still refused.

Each case runs the real hook of this tree with a scratch HOME, CLAUDE_STATE_DIR and git config.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "hooks" / "pretool-git-privilege-guard.py"
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
import git_command_classifier as gcc  # noqa: E402

B = "`"
RECORDED = (
    "cat > /srv/release/tests/reports/r07/hook-rejections.md <<'EOF'\n"
    "# Hook rejections during lane r07\n\n"
    "| # | Time | Refused operation | Hook output | What was done instead |\n"
    "|---|---|---|---|---|\n"
    "| 1 | ~09:26 | one Bash command that began " + B + "mkdir -p .../work && cd ... && rm -rf repo && mkdir repo"
    " && cd repo && git init ... && git commit -qm base" + B + " | " + B + "BLOCKED: removal-policy ..." + B
    + " | nothing was deleted |\n"
    "| 2 | ~09:27 | " + B + "git commit -qm base" + B + " in a scratch repository (a base for " + B
    + "git apply --3way" + B + ") | " + B + "BLOCKED: agent git commit - cd/pushd cwd-change ..." + B
    + " | the engine uses " + B + "git merge-file" + B + " and needs no commit |\n"
    "| 3 | ~10:10 | " + B + "Monitor" + B + " | " + B + 'BLOCKED by tool-policy.v1: {"role":"dev"}' + B
    + " | a Bash " + B + "until" + B + " loop |\n\n"
    "one " + B + "docker run --rm --network none" + B + " container for " + B + "pip freeze" + B
    + "; refused commands retried 0.\n"
    "EOF\n"
    "cd /srv/release && tail -3 evidence/full-rehearsal.out | cut -c1-300"
)

DATA = {
    "the recorded call": RECORDED,
    "absolute path, nothing after": "cat > /srv/out/notes.md <<'EOF'\na " + B + "git commit -qm base" + B + " b\nEOF\n",
    "absolute path, mkdir before and ls after": "mkdir -p /srv/out && cat > /srv/out/n.md <<'EOF'\n$(git commit -m x)"
                                               " and " + B + "git push" + B + "\nEOF\nls /srv/out\n",
    "relative path, tee": "tee notes.md <<'EOF' >/dev/null\nrun " + B + "git reset --hard" + B + "\nEOF\n",
    "a quoted string with a backquote, printf": "printf '%s\\n' 'run " + B + "git commit -qm base" + B
                                                + " now' > /srv/out/notes.md",
    "a quoted string, echo": "echo 'a; git commit -m x' > notes.md",
}

ACTS = {
    # a here-document or string handed to a shell or another interpreter
    "here-document read by bash": "bash <<'EOF'\necho a " + B + "git commit -qm base" + B + "\nEOF\n",
    "here-document read by sh -s": "sh -s <<'EOF'\ngit push origin master\nEOF\n",
    "here-document piped into sh": "cat <<'EOF' | sh\ngit commit -qm base\nEOF\n",
    "here-document read by python": "python3 - <<'EOF'\nimport os\nos.system('git push')\nEOF\n",
    "string piped into sh": "echo 'a; git push' | sh",
    # a commit whose message comes from a here-document or standard input
    "commit -F - from a here-document": "git commit -F - <<'EOF'\nsubject\nEOF\n",
    "commit -F - from a pipe": "echo subject | git commit -F -",
    "commit -m from a here-document": "git commit -m \"$(cat <<'EOF'\nsubject\nEOF\n)\"",
    # a script file the same command writes and then runs
    "written, then sh": "cat > /srv/out/x.sh <<'EOF'\ngit commit -qm base\nEOF\nsh /srv/out/x.sh\n",
    "written, then sourced": "cat > /srv/out/x.sh <<'EOF'\ngit push\nEOF\n. /srv/out/x.sh\n",
    "written, chmod, run": "cat > /srv/out/x.sh <<'EOF'\ngit push\nEOF\nchmod +x /srv/out/x.sh && /srv/out/x.sh\n",
    "written, cd, run": "cat > /srv/out/x.sh <<'EOF'\ngit push\nEOF\ncd /srv/out && ./x.sh\n",
    "written, run by find -exec": "cat > /srv/out/x.sh <<'EOF'\ngit push\nEOF\n"
                                  "find /srv/out -name '*.sh' -exec sh {} \\;\n",
    "written, run by name": "cat > x.sh <<'EOF'\ngit push\nEOF\nbash x.sh\n",
    "written with a run-time -c string, then run": "cat > x.sh <<'EOF'\nbash -c \"git push $R\"\nEOF\nsh x.sh\n",
    "string written, then run": "echo 'a; git push' > x.sh; sh x.sh",
    # text passed to an evaluating builtin
    "eval of a string": "eval 'git commit -qm base'",
    "eval of a here-document": "eval \"$(cat <<'EOF'\ngit push\nEOF\n)\"",
    "source of a here-document": "source <(cat <<'EOF'\ngit push\nEOF\n)",
    # an unquoted delimiter: the outer shell runs the body's substitutions
    "unquoted here-document, $( )": "cat > /srv/out/n.md <<EOF\n$(git commit -qm base)\nEOF\n",
    "unquoted here-document, backquote": "cat > /srv/out/n.md <<EOF\n" + B + "git commit -qm base" + B + "\nEOF\n",
    # a file a tool runs by itself
    "a git hook": "cat > .git/hooks/pre-commit <<'EOF'\ngit push\nEOF\n",
    "a git hook through cd": "cd .git/hooks && cat > pre-push <<'EOF'\ngit push\nEOF\n",
    "a program directory": "cat > /usr/local/bin/helper <<'EOF'\ngit push\nEOF\n",
    "a shell start-up file": "cat > ~/.bashrc <<'EOF'\ngit push\nEOF\n",
}


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("written-text")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    gitconfig = base / "gitconfig"
    gitconfig.write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_STATE_DIR": str(state),
           "GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
    subprocess.run(["git", "init", "-q", "-b", "master"], cwd=repo, env=env, check=True, capture_output=True)
    return env, str(repo)


def _guard(sandbox, command):
    env, repo = sandbox
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "written-text",
               "cwd": repo, "hook_event_name": "PreToolUse", "agent_id": "agent-written-text",
               "agent_type": "dev"}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=repo, timeout=120)


@pytest.mark.parametrize("name", list(DATA))
def test_text_only_written_to_a_file_is_data(sandbox, name):
    proc = _guard(sandbox, DATA[name])
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", list(ACTS))
def test_text_that_is_run_is_refused(sandbox, name):
    proc = _guard(sandbox, ACTS[name])
    assert proc.returncode == 2 and "BLOCKED" in proc.stderr, proc.stderr


def test_both_readings_answer_the_recorded_call_alike():
    # The invocation scan and the -c string scan: no invocation and no residual.
    assert gcc.classify_git_command(RECORDED) == ([], [])


def test_both_readings_see_a_written_script_that_is_run():
    invocations, residuals = gcc.classify_git_command(ACTS["written with a run-time -c string, then run"])
    assert [inv.subcommand for inv in invocations] == ["push"]
    assert [kind for kind, _seg in residuals] == ["unresolved_shell_string"]


@pytest.mark.parametrize("target", ["/proc/self/fd/1", "/proc/self/fd/2", "/proc/thread-self/fd/1", "/dev/fd/1"])
def test_a_stream_name_is_code_whatever_the_hook_output_is(sandbox, tmp_path, target):
    # /proc/self/fd/1 resolves to where the hook's own output goes: a pipe in live use, a file under a
    # runner that captures output. The verdict is the same either way: the written name is no data file.
    command = f"cat > {target} <<'EOF'\ngit push origin master\nEOF\ntrue"
    env, repo = sandbox
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "written-text",
                          "cwd": repo, "hook_event_name": "PreToolUse", "agent_id": "agent-written-text",
                          "agent_type": "dev"})
    verdicts = []
    for mode in ("pipe", "file"):
        out, err = (subprocess.PIPE, subprocess.PIPE) if mode == "pipe" else (
            open(tmp_path / "out.txt", "w+"), open(tmp_path / "err.txt", "w+"))
        proc = subprocess.run([sys.executable, str(GUARD)], input=payload, stdout=out, stderr=err, text=True,
                              env=env, cwd=repo, timeout=120)
        stderr = proc.stderr if mode == "pipe" else (err.seek(0), err.read())[1]
        verdicts.append((mode, proc.returncode, "BLOCKED" in stderr))
    assert [v[1:] for v in verdicts] == [(2, True), (2, True)], verdicts


# g-loctriage U40: a file in the call's own directory is the same file however the call names it, wherever
# the hook process itself runs. The call's directory need not exist: only paths are judged.
CALL_DIR = "/nonexistent-u40/work"
HERE = "cat > {t} <<'EOF'\nrun " + B + "git push" + B + " later\nEOF\n"


def _guard_in(sandbox, command, call_cwd):
    env, repo = sandbox
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "written-text",
               "cwd": call_cwd, "hook_event_name": "PreToolUse", "agent_id": "agent-written-text",
               "agent_type": "dev"}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), capture_output=True,
                          text=True, env=dict(env, CLAUDE_PROJECT_DIR=repo), cwd=repo, timeout=120)


@pytest.mark.parametrize("target", ["bin/notes.txt", CALL_DIR + "/bin/notes.txt"])
def test_a_here_document_in_the_calls_own_directory_is_data_however_it_is_named(sandbox, target):
    proc = _guard_in(sandbox, HERE.format(t=target), CALL_DIR)
    assert proc.returncode == 0, proc.stderr


def test_the_same_absolute_path_outside_the_calls_directory_stays_code(sandbox):
    proc = _guard_in(sandbox, HERE.format(t=CALL_DIR + "/bin/notes.txt"), sandbox[1])
    assert proc.returncode == 2 and "BLOCKED" in proc.stderr, proc.stderr


def test_the_classifier_cache_does_not_carry_a_verdict_to_another_directory():
    """The same command text classified for two call directories, in turn: each gets its own answer. The body
    holds a `bash -c` string, so whether that string is a layer (_shell_layers, cached) depends on the directory."""
    cmd = "cat > {t} <<'EOF'\nbash -c \"git push\"\nEOF\n".format(t=CALL_DIR + "/bin/n.txt")
    assert gcc.classify_git_command(cmd, cwd=CALL_DIR)[0] == []
    assert gcc.classify_git_command(cmd, cwd="/nonexistent-u40/elsewhere")[0] != []
    assert gcc.classify_git_command(cmd, cwd=CALL_DIR)[0] == []
