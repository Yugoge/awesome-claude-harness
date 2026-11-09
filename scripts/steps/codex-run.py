#!/usr/bin/env python3
"""One Codex call through the codex-isolation wrapper (host policy), output teed to a file.

    codex-run.py review                    [--model M]
    codex-run.py exec    [--model M] [PROMPT]
    codex-run.py detach  [--model M] [PROMPT]    (exec, detached: survives the tool call)

PROMPT is one argument, or stdin when absent (a quoted heredoc needs no escaping). The model defaults
to gpt-5.6-sol; reasoning effort is always xhigh.

The wrapper is the executable named by $CODEX_ISO_BIN (default $HOME/bin/codex-iso): a fail-closed
host policy that forces an isolated CODEX_HOME. This script never calls a bare `codex` and has no
fallback to it: no usable wrapper means exit 127 before anything is created or run.

Output file: <project root>/docs/codex/<CODEX_OUT_TASK_ID>/<CODEX_OUT_ROLE>.txt when both variables
are set and each matches [A-Za-z0-9._-]+ and is neither "." nor ".."; otherwise
/var/tmp/codex-outputs/codex-output-<pid>-<epoch>.txt. The project root is $CLAUDE_PROJECT_DIR, else
`git rev-parse --show-toplevel`.

stdout: `out=<path>` first (then the wrapper's output, for review and exec), and for detach also
`pid=<pid>` of the detached run. The wrapper's stdout and stderr are merged into the file and its stdin
is /dev/null. Exit: the wrapper's own status (detach: 0 once launched); 64 usage; 73 output directory
not creatable; 127 wrapper unavailable.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "xhigh"
FALLBACK_DIR = Path("/var/tmp/codex-outputs")
SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")
SAFE_MODEL = re.compile(r"[A-Za-z0-9._:/-]+")
MODES = ("review", "exec", "detach")


class Refusal(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def _safe_name(value: str) -> bool:
    return SAFE_NAME.fullmatch(value) is not None and value not in (".", "..")


def resolve_wrapper(env) -> str:
    """The wrapper named by CODEX_ISO_BIN, or its default; never anything else."""
    named = env.get("CODEX_ISO_BIN") or (env["HOME"] + "/bin/codex-iso" if env.get("HOME") else "")
    found = shutil.which(named, path=env.get("PATH")) if named else None
    if not found:
        raise Refusal("codex isolation wrapper unavailable: set CODEX_ISO_BIN to an executable "
                      f"(got {named or 'nothing'}); no fallback to a bare codex", 127)
    return found


def _project_root(env) -> str:
    if env.get("CLAUDE_PROJECT_DIR"):
        return env["CLAUDE_PROJECT_DIR"]
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             check=False, env=env).stdout.strip()
    except OSError:
        top = ""
    return top


def resolve_output_path(env) -> Path:
    """Create the output directory and return the file to write (no file is created yet)."""
    task, role = env.get("CODEX_OUT_TASK_ID", ""), env.get("CODEX_OUT_ROLE", "")
    root = _project_root(env) if task and role and _safe_name(task) and _safe_name(role) else ""
    if root:
        directory, name = Path(root) / "docs" / "codex" / task, role + ".txt"
    else:
        if task or role:
            print(f"codex-run: warning: CODEX_OUT_TASK_ID/CODEX_OUT_ROLE unsafe or incomplete, or no "
                  f"project root; using {FALLBACK_DIR}/", file=sys.stderr)
        directory, name = FALLBACK_DIR, f"codex-output-{os.getpid()}-{int(time.time())}.txt"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Refusal(f"cannot create output directory {directory}: {exc}", 73)
    return directory / name


def parse(argv: list[str], stdin) -> tuple[str, str, str | None]:
    """(mode, model, prompt); prompt is None for review."""
    if not argv or argv[0] not in MODES:
        raise Refusal(f"usage: codex-run.py {'|'.join(MODES)} [--model M] [PROMPT]", 64)
    mode, rest, model, positional = argv[0], argv[1:], DEFAULT_MODEL, []
    while rest:
        arg = rest.pop(0)
        if arg == "--model":
            if not rest:
                raise Refusal("--model needs a value", 64)
            model = rest.pop(0)
        else:
            positional.append(arg)
    if not SAFE_MODEL.fullmatch(model):
        raise Refusal(f"model {model!r} is not a plain model name", 64)
    if mode == "review":
        if positional:
            raise Refusal("review takes no prompt", 64)
        return mode, model, None
    if len(positional) > 1:
        raise Refusal("exactly one PROMPT argument (or the prompt on stdin)", 64)
    prompt = positional[0] if positional else (None if stdin.isatty() else stdin.read().rstrip("\n"))
    if not prompt or not prompt.strip():
        raise Refusal("no prompt given (argument or stdin)", 64)
    return mode, model, prompt


def build_command(wrapper: str, mode: str, model: str, prompt: str | None) -> list[str]:
    command = [wrapper, "review" if mode == "review" else "exec",
               "-c", f'model="{model}"', "-c", f'reasoning_effort="{REASONING_EFFORT}"']
    return command + ([prompt] if prompt is not None else [])


def run_foreground(command: list[str], sink) -> int:
    """Wrapper stdout+stderr to our stdout and to `sink`, like `2>&1 | tee out`."""
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    to_terminal = True
    while chunk := os.read(proc.stdout.fileno(), 1 << 16):
        sink.write(chunk)
        sink.flush()
        if to_terminal:
            try:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            except (BrokenPipeError, ValueError):
                to_terminal = False
    code = proc.wait()
    return code if code >= 0 else 128 - code


def run_detached(command: list[str], sink) -> int:
    """Like `setsid nohup wrapper ... </dev/null >out 2>&1 &`; returns the pid."""
    signal.signal(signal.SIGHUP, signal.SIG_IGN)  # an ignored signal stays ignored across exec: nohup
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT,
                            start_new_session=True).pid


def main(argv: list[str] | None = None) -> int:
    try:
        mode, model, prompt = parse(list(sys.argv[1:] if argv is None else argv), sys.stdin)
        wrapper = resolve_wrapper(os.environ)
        out = resolve_output_path(os.environ)
        try:
            sink = open(out, "wb")
        except OSError as exc:
            raise Refusal(f"cannot write {out}: {exc}", 73)
        command = build_command(wrapper, mode, model, prompt)
        print(f"out={out}", flush=True)
        with sink:
            if mode == "detach":
                print(f"pid={run_detached(command, sink)}", flush=True)
                return 0
            return run_foreground(command, sink)
    except Refusal as refusal:
        print(f"codex-run: {refusal}", file=sys.stderr)
        return refusal.code
    except OSError as exc:  # the wrapper exists but cannot be executed: still fail closed
        print(f"codex-run: cannot run the codex isolation wrapper: {exc}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    sys.exit(main())
