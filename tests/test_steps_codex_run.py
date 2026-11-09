"""scripts/steps/codex-run.py: the one Codex call /codex makes, through the codex-isolation wrapper.

Every test runs the real script against a stub wrapper in a temp dir (CODEX_ISO_BIN). No real codex, no
network, no dependence on the runner's home: HOME, CLAUDE_PROJECT_DIR and PATH are built per test. A fake
`codex` first on PATH records any call, so "never falls back to a bare codex" is observed, not assumed.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "steps" / "codex-run.py"
COMMAND = REPO / "commands" / "codex.md"

STUB = f"""#!{sys.executable}
import json, os, signal, sys, time
log = os.environ["STUB_LOG"]
record = {{"argv": sys.argv[1:], "stdin": sys.stdin.read(), "pid": os.getpid(), "sid": os.getsid(0),
          "sighup_ignored": signal.getsignal(signal.SIGHUP) == signal.SIG_IGN}}
with open(log, "w") as handle:
    json.dump(record, handle)
release = os.environ.get("STUB_WAIT_FOR")
deadline = time.time() + 30
while release and not os.path.exists(release) and time.time() < deadline:
    time.sleep(0.02)
sys.stdout.write("stub-stdout\\n")
sys.stdout.flush()
if os.environ.get("STUB_BIG"):
    sys.stdout.write("x" * int(os.environ["STUB_BIG"]) + "\\n")
    sys.stdout.flush()
sys.stderr.write("stub-stderr\\n")
sys.stderr.flush()
with open(log + ".done", "w") as handle:
    handle.write("done")
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""
FAKE_CODEX = '#!/bin/sh\necho "$@" >> "$FAKE_CODEX_MARKER"\n'
MODEL_DEFAULT = 'model="gpt-5.6-sol"'
EFFORT = 'model_reasoning_effort="xhigh"'
# The Codex CLI key is `model_reasoning_effort`; a bare `reasoning_effort` is silently ignored, so the
# level would never be applied. This matches that bare key and nothing that carries the `model_` prefix.
BARE_EFFORT_KEY = re.compile(r"(?<!model_)reasoning_effort")


class Box:
    """A throwaway home, project, PATH and stub wrapper."""

    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.project = root / "project"
        self.bin = root / "bin"
        for directory in (self.home, self.project, self.bin):
            directory.mkdir()
        self.wrapper = self._script(self.bin / "wrapper-stub", STUB)
        self._script(self.bin / "codex", FAKE_CODEX)
        self.log = root / "stub.json"
        self.marker = root / "bare-codex-called"

    @staticmethod
    def _script(path: Path, text: str) -> Path:
        path.write_text(text, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def env(self, **extra) -> dict:
        env = {"PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(self.home),
               "CLAUDE_PROJECT_DIR": str(self.project), "CODEX_ISO_BIN": str(self.wrapper),
               "STUB_LOG": str(self.log), "FAKE_CODEX_MARKER": str(self.marker), "PYTHONDONTWRITEBYTECODE": "1"}
        env.update(extra)
        return {key: value for key, value in env.items() if value is not None}

    def run(self, *args: str, stdin: str = "", env: dict | None = None, cwd: Path | None = None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, text=True, capture_output=True,
                              env=self.env() if env is None else env, cwd=cwd or self.root, check=False)

    def record(self) -> dict:
        return json.loads(self.log.read_text(encoding="utf-8"))

    def wait_done(self) -> None:
        deadline = time.time() + 20
        while not Path(str(self.log) + ".done").exists():
            assert time.time() < deadline, "the detached stub never finished"
            time.sleep(0.02)


@pytest.fixture
def box(tmp_path) -> Box:
    return Box(tmp_path)


def keys(stdout: str) -> dict:
    return dict(line.split("=", 1) for line in stdout.splitlines() if re.match(r"^(out|pid)=", line))


def canonical(box: Box, task: str, role: str) -> Path:
    return box.project / "docs" / "codex" / task / f"{role}.txt"


def assert_nothing_ran(box: Box, proc) -> None:
    assert proc.stdout == "" and not box.log.exists() and not box.marker.exists()
    assert not (box.project / "docs").exists()


# ---- the three modes -------------------------------------------------------------------------------------

# The full argument vector the wrapper must receive, spelled out literally (not built from the script's own
# constants): the subcommand, then each `-c` flag and its value in order, then the prompt.
PINNED_ARGV = [
    pytest.param(["review"],
                 ["review", "-c", 'model="gpt-5.6-sol"', "-c", 'model_reasoning_effort="xhigh"'],
                 id="review"),
    pytest.param(["exec", "the prompt"],
                 ["exec", "-c", 'model="gpt-5.6-sol"', "-c", 'model_reasoning_effort="xhigh"', "the prompt"],
                 id="exec"),
    pytest.param(["detach", "the prompt"],
                 ["exec", "-c", 'model="gpt-5.6-sol"', "-c", 'model_reasoning_effort="xhigh"', "the prompt"],
                 id="detach"),
    pytest.param(["exec", "--model", "o3", "the prompt"],
                 ["exec", "-c", 'model="o3"', "-c", 'model_reasoning_effort="xhigh"', "the prompt"],
                 id="exec-custom-model"),
]


@pytest.mark.parametrize("args, expected", PINNED_ARGV)
def test_every_mode_passes_exactly_the_model_and_model_reasoning_effort_overrides(box, args, expected):
    proc = box.run(*args, env=box.env(CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r"))
    assert proc.returncode == 0, proc.stderr
    if args[0] == "detach":
        box.wait_done()
    argv = box.record()["argv"]
    assert argv == expected
    for arg in argv:
        assert not BARE_EFFORT_KEY.search(arg), f"bare reasoning_effort key in {arg!r}"


def test_the_script_source_names_the_effort_key_only_with_the_model_prefix():
    assert not BARE_EFFORT_KEY.search(SCRIPT.read_text(encoding="utf-8"))
    assert BARE_EFFORT_KEY.search('reasoning_effort="xhigh"') and not BARE_EFFORT_KEY.search(EFFORT)  # the guard bites

def test_exec_calls_the_wrapper_with_model_effort_and_the_prompt_and_tees(box):
    proc = box.run("exec", "do the thing", env=box.env(CODEX_OUT_TASK_ID="T-1.0", CODEX_OUT_ROLE="dev"))
    out = canonical(box, "T-1.0", "dev")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[0] == f"out={out}"
    assert box.record()["argv"] == ["exec", "-c", MODEL_DEFAULT, "-c", EFFORT, "do the thing"]
    # stdout and stderr of the wrapper both reach the terminal and the file
    assert proc.stdout == f"out={out}\nstub-stdout\nstub-stderr\n"
    assert out.read_text() == "stub-stdout\nstub-stderr\n"
    assert not box.marker.exists()


def test_exec_with_a_model(box):
    proc = box.run("exec", "--model", "o3", "p", env=box.env(CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r"))
    assert proc.returncode == 0, proc.stderr
    assert box.record()["argv"] == ["exec", "-c", 'model="o3"', "-c", EFFORT, "p"]


def test_review_takes_no_prompt_and_reads_no_stdin(box):
    proc = box.run("review", stdin="this must not reach the wrapper", env=box.env(CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r"))
    assert proc.returncode == 0, proc.stderr
    assert box.record()["argv"] == ["review", "-c", MODEL_DEFAULT, "-c", EFFORT]
    assert box.record()["stdin"] == ""


def test_the_wrapper_stdin_is_dev_null_even_when_the_prompt_arrives_on_stdin(box):
    proc = box.run("exec", stdin="prompt on stdin\n")
    assert proc.returncode == 0, proc.stderr
    assert box.record()["stdin"] == ""
    assert box.record()["argv"][-1] == "prompt on stdin"


def test_the_wrapper_exit_status_is_the_scripts_and_the_output_is_still_kept(box):
    proc = box.run("exec", "p", env=box.env(STUB_EXIT="3", CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r"))
    assert proc.returncode == 3
    assert canonical(box, "T", "r").read_text() == "stub-stdout\nstub-stderr\n"


def test_large_output_streams_to_both_without_loss(box):
    big = 400_000
    proc = box.run("exec", "p", env=box.env(STUB_BIG=str(big), CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r"))
    assert proc.returncode == 0, proc.stderr
    kept = canonical(box, "T", "r").read_text()
    assert kept == "stub-stdout\n" + "x" * big + "\nstub-stderr\n"
    assert proc.stdout == f"out={canonical(box, 'T', 'r')}\n" + kept


def test_a_second_run_with_the_same_names_replaces_the_file(box):
    env = box.env(CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r")
    canonical(box, "T", "r").parent.mkdir(parents=True)
    canonical(box, "T", "r").write_text("older and longer output than the new run\n" * 5)
    assert box.run("exec", "p", env=env).returncode == 0
    assert canonical(box, "T", "r").read_text() == "stub-stdout\nstub-stderr\n"


def test_detach_returns_at_once_with_out_and_pid_and_the_run_is_detached(box, tmp_path):
    release = tmp_path / "release"
    proc = box.run("detach", "--model", "o3", "long task",
                   env=box.env(STUB_WAIT_FOR=str(release), CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r"))
    assert proc.returncode == 0, proc.stderr
    printed = keys(proc.stdout)
    assert proc.stdout.splitlines() == [f"out={canonical(box, 'T', 'r')}", f"pid={printed['pid']}"]
    assert not Path(str(box.log) + ".done").exists()  # the stub is still waiting: the script did not
    release.write_text("go")
    box.wait_done()
    record = box.record()
    assert record["argv"] == ["exec", "-c", 'model="o3"', "-c", EFFORT, "long task"]  # the model is kept
    assert record["pid"] == int(printed["pid"])
    assert record["sid"] == record["pid"]            # setsid: a session of its own
    assert record["sighup_ignored"] is True          # nohup
    assert record["stdin"] == ""
    assert canonical(box, "T", "r").read_text() == "stub-stdout\nstub-stderr\n"


# ---- the output path -------------------------------------------------------------------------------------

@pytest.mark.parametrize("task, role", [("T-1.0", "dev"), ("20260101-000530", "qa_2"), ("a.b-c_D", "R-1"), ("...", "x")])
def test_safe_names_give_the_canonical_path_and_no_warning(box, task, role):
    proc = box.run("exec", "p", env=box.env(CODEX_OUT_TASK_ID=task, CODEX_OUT_ROLE=role))
    assert proc.returncode == 0, proc.stderr
    assert keys(proc.stdout)["out"] == str(canonical(box, task, role))
    assert canonical(box, task, role).is_file() and proc.stderr == ""


UNSAFE = ["../x", "a/b", "a b", ".", "..", "x;y", "a\nb", "ab\n", "$(id)", "é", "-x/..", "a\\b", "~"]


@pytest.mark.parametrize("bad", UNSAFE)
@pytest.mark.parametrize("which", ["task", "role"])
def test_an_unsafe_name_falls_back_with_a_warning_and_writes_nothing_under_the_project(box, bad, which, tmp_path):
    fallback = tmp_path / "fallback"
    task, role = (bad, "dev") if which == "task" else ("T-1", bad)
    proc = run_with_fallback(box, fallback, "exec", "p", env=box.env(CODEX_OUT_TASK_ID=task, CODEX_OUT_ROLE=role))
    assert proc.returncode == 0, proc.stderr
    assert re.fullmatch(rf"{re.escape(str(fallback))}/codex-output-\d+-\d+\.txt", keys(proc.stdout)["out"])
    assert "warning" in proc.stderr and "unsafe" in proc.stderr
    assert not (box.project / "docs").exists()
    assert not (tmp_path / "x").exists() and not (tmp_path / "docs").exists()


@pytest.mark.parametrize("task, role", [(None, None), ("", ""), ("T-1", None), (None, "dev"), ("T-1", ""), ("", "dev")])
def test_unset_or_empty_names_fall_back_and_warn_only_when_one_is_set(box, task, role, tmp_path):
    fallback = tmp_path / "fallback"
    proc = run_with_fallback(box, fallback, "exec", "p", env=box.env(CODEX_OUT_TASK_ID=task, CODEX_OUT_ROLE=role))
    assert proc.returncode == 0, proc.stderr
    assert keys(proc.stdout)["out"].startswith(f"{fallback}/codex-output-")
    assert ("warning" in proc.stderr) == bool(task or role)
    assert not (box.project / "docs").exists()


def run_with_fallback(box: Box, fallback: Path, *args, env: dict):
    """The script's own main(), with only the fallback directory constant pointed at a temp dir."""
    driver = ("import importlib.util, sys\n"
              f"spec = importlib.util.spec_from_file_location('codex_run', {str(SCRIPT)!r})\n"
              "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
              f"from pathlib import Path; mod.FALLBACK_DIR = Path({str(fallback)!r})\n"
              "sys.exit(mod.main(sys.argv[1:]))\n")
    return subprocess.run([sys.executable, "-c", driver, *args], input="", text=True, capture_output=True,
                          env=env, cwd=box.root, check=False)


def test_the_fallback_file_is_the_printed_one_and_the_default_directory_is_var_tmp(box, tmp_path):
    spec = importlib.util.spec_from_file_location("codex_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert str(module.FALLBACK_DIR) == "/var/tmp/codex-outputs"
    fallback = tmp_path / "fallback" / "deeper"
    proc = run_with_fallback(box, fallback, "exec", "p", env=box.env())
    assert proc.returncode == 0, proc.stderr
    printed = Path(keys(proc.stdout)["out"])
    assert list(fallback.iterdir()) == [printed]
    assert printed.read_text() == "stub-stdout\nstub-stderr\n"


def test_without_a_project_dir_the_git_toplevel_is_the_root(box, tmp_path):
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    env = box.env(CLAUDE_PROJECT_DIR=None, CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r")
    proc = box.run("exec", "p", env=env, cwd=repo / "sub")
    assert proc.returncode == 0, proc.stderr
    assert Path(keys(proc.stdout)["out"]).resolve() == (repo / "docs" / "codex" / "T" / "r.txt").resolve()


def test_without_a_project_dir_and_no_git_it_falls_back_instead_of_writing_to_the_filesystem_root(box, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    env = box.env(CLAUDE_PROJECT_DIR=None, CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r", GIT_CEILING_DIRECTORIES=str(tmp_path))
    proc = run_with_fallback(box, tmp_path / "fallback", "exec", "p", env=env)
    proc_out = keys(proc.stdout)["out"]
    assert proc.returncode == 0, proc.stderr
    assert proc_out.startswith(f"{tmp_path}/fallback/codex-output-") and "warning" in proc.stderr


def test_an_output_directory_that_cannot_be_made_stops_before_the_wrapper_runs(box):
    (box.project / "docs").write_text("a file where the docs directory should be")
    proc = box.run("exec", "p", env=box.env(CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r"))
    assert proc.returncode == 73 and "cannot create output directory" in proc.stderr
    assert proc.stdout == "" and not box.log.exists() and not box.marker.exists()


# ---- fail closed -----------------------------------------------------------------------------------------

def _unavailable(box: Box) -> list:
    directory = box.root / "a-directory"
    directory.mkdir()
    plain = box.root / "not-executable"
    plain.write_text("#!/bin/sh\n")
    return [("missing path", box.env(CODEX_ISO_BIN=str(box.root / "absent"))),
            ("directory", box.env(CODEX_ISO_BIN=str(directory))),
            ("not executable", box.env(CODEX_ISO_BIN=str(plain))),
            ("bare name not on PATH", box.env(CODEX_ISO_BIN="no-such-wrapper")),
            ("unset, default absent", box.env(CODEX_ISO_BIN=None)),
            ("empty, default absent", box.env(CODEX_ISO_BIN="")),
            ("unset, no HOME", box.env(CODEX_ISO_BIN=None, HOME=None))]


@pytest.mark.parametrize("mode", ["review", "exec", "detach"])
def test_no_usable_wrapper_fails_closed_in_every_mode_and_never_calls_bare_codex(box, mode):
    args = (mode,) if mode == "review" else (mode, "p")
    for label, env in _unavailable(box):
        env["CODEX_OUT_TASK_ID"], env["CODEX_OUT_ROLE"] = "T", "r"
        proc = box.run(*args, env=env)
        assert proc.returncode == 127, (label, proc.returncode, proc.stderr)
        assert "CODEX_ISO_BIN" in proc.stderr and "no fallback" in proc.stderr, label
        assert_nothing_ran(box, proc)


def test_the_default_wrapper_is_home_bin_codex_iso(box):
    (box.home / "bin").mkdir()
    default = Box._script(box.home / "bin" / "codex-iso", STUB)
    proc = box.run("exec", "p", env=box.env(CODEX_ISO_BIN=None, CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r"))
    assert proc.returncode == 0, proc.stderr
    assert box.record()["argv"][0] == "exec" and default.exists()


def test_a_bare_wrapper_name_is_resolved_on_path_but_a_bare_codex_is_never_chosen(box):
    Box._script(box.bin / "codex-iso", STUB)
    proc = box.run("exec", "p", env=box.env(CODEX_ISO_BIN="codex-iso", CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r"))
    assert proc.returncode == 0, proc.stderr
    assert box.record()["argv"][0] == "exec" and not box.marker.exists()
    # the fake codex is on PATH and executable, yet with no CODEX_ISO_BIN nothing reaches it
    none = box.run("exec", "p", env=box.env(CODEX_ISO_BIN=None))
    assert none.returncode == 127 and not box.marker.exists()


def test_the_script_never_names_a_bare_codex_as_a_program():
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"""which\(\s*['"]codex|Popen\(\s*\[\s*['"]codex|run\(\s*\[\s*['"]codex""", source)


# ---- the prompt ------------------------------------------------------------------------------------------

NASTY = ('line one with "double" and \'single\' quotes\nline two: $HOME $(id) `id` \\n \\\\ & | ; > <\n\n'
         "  indented after a blank line, unicode: é 日本語 \U0001F600, a lone ' and a lone \"\n"
         "-leading dash line\nEOF\nCODEX_PROMPT")


@pytest.mark.parametrize("mode", ["exec", "detach"])
def test_a_prompt_with_quotes_and_newlines_reaches_the_wrapper_verbatim_from_stdin(box, mode):
    proc = box.run(mode, "--model", "o3", stdin=NASTY + "\n")  # a heredoc ends with one newline
    assert proc.returncode == 0, proc.stderr
    if mode == "detach":
        box.wait_done()
    assert box.record()["argv"] == ["exec", "-c", 'model="o3"', "-c", EFFORT, NASTY]


def test_a_prompt_with_quotes_and_newlines_reaches_the_wrapper_verbatim_as_an_argument(box):
    assert box.run("exec", NASTY).returncode == 0
    assert box.record()["argv"][-1] == NASTY
    assert box.run("exec", "--model", "o3", "-starts-with-a-dash").returncode == 0
    assert box.record()["argv"][-1] == "-starts-with-a-dash"


@pytest.mark.parametrize("args, stdin, word", [
    ([], "", "usage"),
    (["bogus", "p"], "", "usage"),
    (["exec"], "", "no prompt"),
    (["exec"], "  \n\n", "no prompt"),
    (["exec", ""], "", "no prompt"),
    (["exec", "a", "b"], "", "exactly one"),
    (["review", "a prompt"], "", "review takes no prompt"),
    (["exec", "--model"], "", "needs a value"),
    (["exec", "--model", 'o3" -c sandbox_mode="danger-full-access', "p"], "", "plain model name"),
    (["review", "--model", "a b"], "", "plain model name"),
    (["detach", "--model", "", "p"], "", "plain model name"),
])
def test_bad_calls_are_usage_errors_and_never_reach_the_wrapper(box, args, stdin, word):
    proc = box.run(*args, stdin=stdin, env=box.env(CODEX_OUT_TASK_ID="T", CODEX_OUT_ROLE="r"))
    assert proc.returncode == 64 and word in proc.stderr, proc.stderr
    assert_nothing_ran(box, proc)


# ---- the call shapes in commands/codex.md ----------------------------------------------------------------

def _blocks() -> list[str]:
    return re.findall(r"```bash\n(.*?)```", COMMAND.read_text(encoding="utf-8"), flags=re.S)


def test_the_command_calls_only_the_script_and_the_script_exists():
    blocks = _blocks()
    assert len(blocks) == 2 and SCRIPT.is_file()
    for block in blocks:
        assert block.startswith('python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/steps/codex-run.py" ')
        assert "CODEX_ISO_BIN" not in block and not re.search(r"(^|\s)codex\s", block)
    text = COMMAND.read_text(encoding="utf-8")
    assert "fail-closed" in text and "Never call bare `codex`" in text and "`CODEX_ISO_BIN`" in text


def test_the_command_defers_the_calling_protocol_to_the_one_shared_include():
    text = COMMAND.read_text(encoding="utf-8")
    include = REPO / "templates" / "prompt-includes" / "codex-consultation.md"
    assert include.is_file()
    assert "Codex calls follow `templates/prompt-includes/codex-consultation.md`." in text
    assert not re.search(r"Calling Protocol|### Rule \d|in_scope_real_bug|USER REQUIREMENT", text)


def _command_shapes() -> list[str]:
    shapes = []
    for block in _blocks():
        shape = block.replace("[--model <model>]", "--model o3").replace("<the prompt>", "audit the diff")
        shapes += [shape, shape.replace(" exec", " detach")]
    return shapes


@pytest.mark.parametrize("command", _command_shapes())
def test_the_bash_safety_hook_lets_the_command_shapes_through(command):
    hooks_tests = str(REPO / "hooks" / "tests")
    sys.path.insert(0, hooks_tests)
    try:
        from pol_replay_harness import run_hook_command
    finally:
        sys.path.remove(hooks_tests)
    code, _out, err = run_hook_command(command)
    assert code == 0, (command, err)
