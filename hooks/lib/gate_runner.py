"""Run one event's rules in one process, in order (P12 L5).

Claude Code starts every hook registered on an event at once, so two hooks that
read and write the same file race, and a hook that records a dispatch cannot know
whether another hook refused it. A gate file built on this module runs its rules
one after another in its own process instead:

- a rule is a hook file run whole, as `python3 <file>` would run it: the event
  payload on stdin, its own `__main__` wrapper, its own switches read from the
  environment, its stdout and stderr captured at the file-descriptor level (so a
  child process's output is captured too), and its exit status taken from
  SystemExit;
- each rule runs in its own try: an exception that escapes the rule's own wrapper
  is recorded as that rule's exit 1 (a non-blocking error, as when it ran alone)
  and the next rule still runs;
- `refuse` rules decide: exit 2 refuses the call;
- `witness` rules record that the call really happens, so they run only when no
  refuse rule refused, after all of them; their errors and exit codes never block;
- `observe` rules run in their place in the list whatever the refuse rules decided
  (a writer before the rules that read what it writes); their errors and exit codes
  never block;
- the reasons of every refusing rule are reported together, once, on stderr with
  exit 2, so a producer fixes them in one round instead of meeting them one by one;
  where two rules refuse on the same fact, the gate may state it once.

Nothing here decides a fact: each rule keeps the decision, the switch and the
failure direction it had as its own hook.
"""
from __future__ import annotations

import io
import json
import os
import runpy
import sys
import tempfile
import traceback
from dataclasses import dataclass

REFUSE, WITNESS, OBSERVE = "refuse", "witness", "observe"
REFUSAL_EXIT = 2


@dataclass(frozen=True)
class Rule:
    name: str
    path: str
    kind: str = REFUSE


@dataclass
class Outcome:
    rule: Rule
    code: int = 0
    stdout: str = ""
    stderr: str = ""
    ran: bool = True
    superseded_by: str = ""  # another rule's refusal states this one's reason; it still refuses

    @property
    def refused(self) -> bool:
        return self.rule.kind == REFUSE and self.code == REFUSAL_EXIT


def _exit_code(value) -> tuple[int, str]:
    """SystemExit's argument as the exit status the interpreter would give it."""
    if value is None:
        return 0, ""
    if isinstance(value, int):
        return value & 0xFF, ""
    return 1, f"{value}\n"


def run_rule(rule: Rule, raw: bytes) -> Outcome:
    """Run `rule.path` as `__main__` with `raw` on stdin; never raises."""
    saved_streams = sys.stdin, sys.stdout, sys.stderr
    saved_argv = sys.argv[:]
    saved_fds = []
    files = []
    code, extra = 0, ""
    try:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        for fd in (1, 2):
            tmp = tempfile.TemporaryFile()
            files.append(tmp)
            saved_fds.append(os.dup(fd))
            os.dup2(tmp.fileno(), fd)
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
        sys.stdout = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding="utf-8", line_buffering=True)
        sys.stderr = io.TextIOWrapper(os.fdopen(os.dup(2), "wb"), encoding="utf-8", line_buffering=True)
        sys.argv = [rule.path]
        try:
            runpy.run_path(rule.path, run_name="__main__")
        except SystemExit as stop:
            code, extra = _exit_code(stop.code)
        except BaseException:  # the rule's own try: an escaped error is this rule's exit 1
            code, extra = 1, traceback.format_exc()
    except BaseException:
        code, extra = 1, traceback.format_exc()
    finally:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
                if stream not in saved_streams:
                    stream.close()
            except Exception:
                pass
        sys.stdin, sys.stdout, sys.stderr = saved_streams
        sys.argv = saved_argv
        for fd, saved in zip((1, 2), saved_fds):
            os.dup2(saved, fd)
            os.close(saved)
    captured = []
    for tmp in files:
        tmp.seek(0)
        captured.append(tmp.read().decode("utf-8", "replace"))
        tmp.close()
    while len(captured) < 2:
        captured.append("")
    return Outcome(rule, code, captured[0], captured[1] + extra)


def check_order(rules: list[Rule]) -> None:
    """A witness records a call every refuse rule let through, so none may follow it."""
    seen_witness = False
    for r in rules:
        if r.kind not in (REFUSE, WITNESS, OBSERVE):
            raise ValueError(f"{r.name}: unknown rule kind {r.kind!r}")
        if r.kind == WITNESS:
            seen_witness = True
        elif r.kind == REFUSE and seen_witness:
            raise ValueError(f"{r.name}: a refuse rule after a witness")


def evaluate(rules: list[Rule], raw: bytes) -> list[Outcome]:
    """Every rule's outcome, in list order; a witness runs only when no refuse rule refused."""
    check_order(rules)
    outcomes: list[Outcome] = []
    for r in rules:
        if r.kind == WITNESS and any(o.refused for o in outcomes):
            outcomes.append(Outcome(r, ran=False))
        else:
            outcomes.append(run_rule(r, raw))
    return outcomes


def _context(text: str) -> tuple[str, str] | None:
    """(event, additionalContext) of a rule's stdout that is one such JSON object."""
    try:
        obj = json.loads(text)
        out = obj["hookSpecificOutput"]
        if set(obj) == {"hookSpecificOutput"} and isinstance(out.get("additionalContext"), str):
            return str(out.get("hookEventName") or ""), out["additionalContext"]
    except Exception:
        pass
    return None


def report(outcomes: list[Outcome]) -> int:
    """Write the gate's output and return its exit status.

    Refused: every refusing rule's stderr, together, and exit 2 (the other rules'
    plain output stays out of the model's context, as it did when each ran alone;
    a rule's additionalContext, which reached the model alone, follows the reasons,
    since exit 2 makes the CLI read stderr only).
    Not refused: the rules' stdout (their additionalContext objects merged into one)
    and stderr, and exit 1 if a refuse rule failed with a non-blocking error (as that
    rule alone would have), else 0.
    """
    contexts = [c for c in (_context(o.stdout) for o in outcomes if o.stdout) if c]
    refusals = [o for o in outcomes if o.refused]
    if refusals:
        stated = [o for o in refusals if not o.superseded_by] or refusals
        text = "\n".join(o.stderr.rstrip("\n") for o in stated)
        if contexts:
            text += "\n" + "\n".join(c for _, c in contexts)
        sys.stderr.write(text + "\n")
        return REFUSAL_EXIT
    outs = [o.stdout for o in outcomes if o.stdout]
    if len(contexts) > 1 or (contexts and len(outs) > 1):
        event = next((e for e, _ in contexts if e), "")
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": event, "additionalContext": "\n".join(c for _, c in contexts)}}) + "\n")
    else:
        sys.stdout.write("".join(outs))
    for o in outcomes:
        if o.stderr:
            sys.stderr.write(o.stderr)
    failed = any(o.ran and o.rule.kind == REFUSE and o.code not in (0, REFUSAL_EXIT) for o in outcomes)
    return 1 if failed else 0


def main(rules: list[Rule], one_reason=None) -> int:
    """Run the gate. `one_reason(outcomes)`, if given, marks a refusal whose reason
    another refusal already states (Outcome.superseded_by), so each fact is stated
    once; a marking error is ignored, and the decision never depends on it."""
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""
    outcomes = evaluate(rules, raw)
    if one_reason is not None:
        try:
            one_reason(outcomes)
        except Exception:
            for o in outcomes:
                o.superseded_by = ""
    return report(outcomes)
