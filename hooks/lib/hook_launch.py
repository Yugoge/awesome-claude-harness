"""One process per hook event: run the event's Python hooks in order and answer as the CLI would.

Claude Code starts every hook registered on an event as its own process, so one
Bash call started a dozen Python interpreters before it ran. A dispatcher
(hooks/<event>-launch.py) is the event's one Python registration: it holds the
event's Python hooks in a module-level ``RULES`` table, in the order settings.json
registered them, and runs each one the call matches in its own process
(lib/rule_runner: each file as ``__main__``, its stdin, exit status, output, atexit
handlers and excepthook as when it ran alone, the environment, working directory,
signal handlers and harness modules put back after it). The shell hooks keep their
own registrations.

Each rule keeps what its registration said:
- ``tools``: the tool names of its old matcher (None: every call of the event). The
  dispatcher is registered without a matcher and selects by ``tool_name`` here,
  matching as the CLI matched;
- ``timeout``: its old timeout (the CLI's default, 60 s, when it had none). A hook
  that runs past it ends as a timed-out hook ended: a non-blocking error, and the
  later hooks still run. The dispatcher's own registered timeout is the sum of its
  rules' (hooks/tests/test_hook_launch.py), so the CLI never kills it first.

Failure direction. A hook ran alone fails as the CLI let it fail: an uncaught error
is exit 1 and a timeout a non-blocking error, both letting the call go on; a hook
that must refuse when it cannot decide (tool-policy, git-privilege-guard) does that
in its own code, and still does here. One hook's error never changes another's
answer: a refusal stands whatever the other hooks did. If the dispatcher's own code
fails (this module cannot load, or the runner around a hook raises), the hooks run
as separate processes instead, as the CLI ran them (``fallback``), so a fault here
skips no hook; a hook still running long after its timeout is answered for by the
watchdog the same way (``emergency``).

The answer (``combine``) is what the CLI makes of the hooks' answers together:
- a refusal (exit 2, a ``deny``, or a ``block`` decision) from any hook: exit 2, the
  refusals' reasons in rule order on stderr;
- ``continue: false`` from any hook: that JSON, stopping the turn;
- else one hook's output alone is passed on as it is; several are merged into one
  JSON object: the strongest permission decision (defer > ask > allow), the first
  ``updatedInput``, every ``additionalContext`` (and, on the events whose plain
  stdout reaches the model, every plain stdout) and every ``systemMessage``;
- a hook's non-blocking error reaches the user: as the dispatcher's own exit 1 with
  its stderr when no hook printed an answer, else as a ``systemMessage``.

Registering a hook. A new Python hook is a ``Rule`` line in its event's dispatcher,
at the place its registration would have had, with its matcher's tool names and its
timeout; a shell hook is registered in settings.json as before. The CI test
(hooks/tests/test_hook_launch.py) fails when an event registers a second Python
process. hooks/lib/launch_settings.py expands the dispatchers back into one
registration per hook (the old shape) for the readers that need it.

The replay suite asks for each hook's own result (env ``RECORD_ENV``, a file
descriptor to write them to), so its records keep naming the hook files, and a
traced replay asks the launcher to mark which hook it runs (env ``MARK_ENV``), so the
trace names the hook as the component; the hooks never see either variable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TIMEOUT = 60.0          # the CLI's default hook timeout, seconds
RECORD_ENV = "CLAUDE_HOOK_LAUNCH_RECORD_FD"
MARK_ENV = "CLAUDE_HOOK_LAUNCH_MARKS"  # a traced replay's marker directory (tests/replay/trace.py)
TOOL_EVENTS = frozenset({"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"})
PLAIN_CONTEXT_EVENTS = frozenset({"UserPromptSubmit", "SessionStart"})
TIMEOUT = "timeout"             # a hook's status when it ran past its timeout


@dataclass(frozen=True)
class Rule:
    name: str
    path: str                          # relative to hooks/
    tools: tuple | None = None         # its old matcher's tool names, in its order; None: every call
    timeout: float = DEFAULT_TIMEOUT
    matcher_spelling: str | None = None   # how its registration spelled "every tool" ("*"), for readers

    def applies(self, tool) -> bool:
        return self.tools is None or tool in self.tools

    @property
    def file(self) -> str:
        return os.path.join(HOOKS, self.path)

    @property
    def matcher(self) -> str:
        if self.matcher_spelling is not None:
            return self.matcher_spelling
        return "|".join(self.tools) if self.tools is not None else ""


@dataclass
class Result:
    rule: Rule
    code: object        # int, or TIMEOUT
    stdout: str = ""
    stderr: str = ""
    seconds: float = 0.0
    how: str = "in-process"   # or "process": run as its own process (the fallback)


def _json(text: str):
    text = (text or "").strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _tool(raw: bytes):
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data.get("tool_name") if isinstance(data, dict) else None


def selected(rules, event: str, raw: bytes) -> list:
    """The rules this call matches, in order (every rule when the event has no tool, or the
    payload names none)."""
    tool = _tool(raw) if event in TOOL_EVENTS else None
    return [r for r in rules if tool is None or r.applies(tool)]


# ------------------------------------------------------------------ combining

def combine(event: str, results) -> tuple[int, str, str]:
    """(exit status, stdout, stderr) the hooks' results give together, as the CLI reads them."""
    refusals, errors, stops, answers = [], [], [], []
    for r in results:
        if r.code == 2:
            refusals.append(r.stderr)
            continue
        if r.code != 0:  # a non-blocking error: its stderr is for the user
            errors.append(r.stderr if r.code != TIMEOUT else
                          f"{r.rule.path} ran past its {r.rule.timeout:g} s timeout\n")
            continue
        out = _json(r.stdout)
        if out is not None and out.get("continue") is False:
            stops.append(out)
            continue
        if out is not None:
            hso = out.get("hookSpecificOutput") if isinstance(out.get("hookSpecificOutput"), dict) else {}
            if hso.get("permissionDecision") == "deny":
                refusals.append(str(hso.get("permissionDecisionReason") or r.stderr))
                continue
            if out.get("decision") == "block":
                refusals.append(str(out.get("reason") or r.stderr))
                continue
        answers.append((r, out))
    if stops:  # continue: false ends the turn, whatever else the hooks decided
        return 0, json.dumps(stops[0]) + "\n", ""
    if refusals:
        return 2, "", "".join(t if t.endswith("\n") else t + "\n" for t in refusals if t)
    printed = [(r, out) for r, out in answers if r.stdout.strip()]
    err_text = "".join(e if e.endswith("\n") else e + "\n" for e in errors if e)
    quiet = "".join(r.stderr for r, _ in answers)  # an exit-0 hook's stderr reaches no one
    if not printed:
        return (1, "", err_text) if errors else (0, "", quiet)
    if len(printed) == 1 and not errors:
        return 0, printed[0][0].stdout, quiet
    merged: dict = {}
    spec: dict = {}
    contexts, messages, decisions = [], [], {}
    for r, out in printed:
        if out is None:
            if event in PLAIN_CONTEXT_EVENTS:
                contexts.append(r.stdout.strip())
            continue
        hso = out.get("hookSpecificOutput") if isinstance(out.get("hookSpecificOutput"), dict) else {}
        if hso.get("hookEventName") not in (None, event):
            hso = {}
        d = hso.get("permissionDecision")
        if d in ("defer", "ask", "allow"):
            decisions.setdefault(d, []).append(str(hso.get("permissionDecisionReason") or ""))
        if out.get("decision") == "approve" and event == "PreToolUse":
            decisions.setdefault("allow", []).append(str(out.get("reason") or ""))
        if isinstance(hso.get("updatedInput"), dict) and "updatedInput" not in spec:
            spec["updatedInput"] = hso["updatedInput"]
        if hso.get("additionalContext"):
            contexts.append(str(hso["additionalContext"]))
        if out.get("systemMessage"):
            messages.append(str(out["systemMessage"]))
        if out.get("suppressOutput"):
            merged["suppressOutput"] = True
    for d in ("defer", "ask", "allow"):
        if d in decisions:
            spec["permissionDecision"] = d
            spec["permissionDecisionReason"] = "\n".join(t for t in decisions[d] if t)
            break
    if contexts:
        spec["additionalContext"] = "\n".join(contexts)
    if err_text:
        messages.append(err_text.rstrip("\n"))
    if spec:
        merged["hookSpecificOutput"] = {"hookEventName": event, **spec}
    if messages:
        merged["systemMessage"] = "\n".join(messages)
    if not merged:
        return (1, "", err_text) if errors else (0, "", quiet)
    return 0, json.dumps(merged) + "\n", quiet


# ------------------------------------------------------------------ running

def run_process(rule: Rule, raw: bytes, timeout: float | None = None) -> Result:
    """The hook as its own process, as the CLI ran it."""
    t0 = time.monotonic()
    try:
        p = subprocess.run([sys.executable, rule.file], input=raw, capture_output=True,
                           timeout=timeout if timeout is not None else rule.timeout)
        return Result(rule, p.returncode, p.stdout.decode("utf-8", "replace"),
                      p.stderr.decode("utf-8", "replace"), time.monotonic() - t0, "process")
    except subprocess.TimeoutExpired:
        return Result(rule, TIMEOUT, "", "", time.monotonic() - t0, "process")
    except Exception as exc:
        return Result(rule, 1, "", f"{rule.path}: could not start: {exc}\n", time.monotonic() - t0, "process")


class Dispatch:
    def __init__(self, event: str, rules, raw: bytes, record_fd=None, marks=None):
        self.event, self.raw, self.marks = event, raw, marks
        self.rules = selected(rules, event, raw)
        self.results: list = []
        self.record_fd = record_fd
        self.lock = threading.Lock()
        self.finished = False
        self.real = (os.dup(1), os.dup(2))

    def run(self) -> None:
        """Run every selected hook, in order; their results are in ``self.results``. Where the
        runner cannot load or fails around a hook, that hook runs as its own process."""
        try:
            from lib.rule_runner import run_rule
        except Exception:
            run_rule = None
        for rule in self.rules:
            if self.finished:
                break
            self.mark(rule.path)
            try:
                if run_rule is None:
                    raise RuntimeError("lib/rule_runner.py did not load")
                rr = run_rule(rule.file, self.raw, rule.timeout, fresh_modules=True,
                              on_stuck=lambda rule=rule: self.emergency(rule))
                res = Result(rule, TIMEOUT if rr.overrun else rr.code, rr.stdout, rr.stderr, rr.seconds)
            except Exception:  # the runner's own fault: this hook runs as the CLI ran it
                res = run_process(rule, self.raw)
            self.mark(None)
            with self.lock:
                if self.finished:
                    break
                self.results.append(res)

    def emergency(self, stuck: Rule) -> None:  # pragma: no cover - needs a hook that ignores its timeout
        """From the watchdog: `stuck` ran past its timeout and did not stop. Answer for the event
        with the hooks after it run as their own processes, and end this process."""
        with self.lock:
            if self.finished:
                return
            self.finished = True
            done = list(self.results)
        done.append(Result(stuck, TIMEOUT))
        rest = self.rules[self.rules.index(stuck) + 1:]
        done += [run_process(r, self.raw) for r in rest]
        self.results = done
        code, out, err = combine(self.event, done)
        self.record()
        _write(self.real[0], out)
        _write(self.real[1], err)
        from lib.rule_runner import _REAL_OS_EXIT
        _REAL_OS_EXIT(code)

    def mark(self, path) -> None:
        """For a traced replay only: name the hook this process now runs (None: the launcher's own
        code), by opening a marker file the trace reads (tests/replay/trace.py LAUNCH_MARK)."""
        if not self.marks:
            return
        from urllib.parse import quote
        name = "launch." + (quote("hooks/" + path, safe="") if path else "-")
        try:
            os.close(os.open(os.path.join(self.marks, name), os.O_WRONLY | os.O_CREAT, 0o644))
        except OSError:
            pass

    def record(self) -> None:
        if self.record_fd is None:
            return
        lines = "".join(json.dumps({"hook": "hooks/" + r.rule.path, "matcher": r.rule.matcher,
                                    "timeout": r.rule.timeout, "rc": r.code, "stdout": r.stdout,
                                    "stderr": r.stderr if r.code != TIMEOUT else "timeout",
                                    "ms": round(r.seconds * 1000), "how": r.how}) + "\n"
                        for r in self.results)
        _write(self.record_fd, lines)


def _write(fd, text: str) -> None:
    data = (text or "").encode("utf-8", "replace")
    while data:
        try:
            n = os.write(fd, data)
        except OSError:
            return
        data = data[n:]


def record_fd():
    """The descriptor the replay runner asked the results on, taken out of the environment."""
    value = os.environ.pop(RECORD_ENV, "")
    try:
        return int(value) if value else None
    except ValueError:
        return None


def main(event: str, rules, raw: bytes | None = None) -> int:
    """Run the dispatcher; its own fault runs every hook as its own process instead."""
    if raw is None:
        raw = sys.stdin.buffer.read()
    fd = record_fd()
    marks = os.environ.pop(MARK_ENV, "") or None
    try:
        d = Dispatch(event, rules, raw, fd, marks)
    except Exception:  # before any hook ran: every hook as its own process
        from lib import hook_launch_fallback
        return hook_launch_fallback.run(event, rules, raw, fd)
    d.run()  # a hook's runner fault already falls back to that hook's own process
    try:
        code, out, err = combine(event, d.results)
    except Exception:  # the hooks ran once; never again (their side effects would repeat)
        from lib import hook_launch_fallback
        code, out, err = hook_launch_fallback.minimal(d.results)
    d.record()
    _write(1, out)
    _write(2, err)
    return code
