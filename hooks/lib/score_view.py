"""What a score shows at a dispatch and what a low one costs (D29, D32): the readers of the score log that hooks call. They read the log and the
transcript and write nothing. ``as_of`` is the active span opener's time, so one command sees one score; a score earned inside the command counts from the next."""
from __future__ import annotations

import json
import os
import time
from contextlib import suppress

try:  # as hooks.lib.score_view (tests), or from hooks/lib on the path (the hooks)
    from . import command_span, obligation, roster, score_log
except ImportError:
    import command_span, obligation, roster, score_log  # noqa: E401

NO_INJECTION = ("close", "commit", "merge", "push")  # spans whose dispatches see no score: /close and /commit stay out of scoring
ASK_COMMANDS = tuple(json.loads(command_span.COMMAND_SETS_FILE.read_text(encoding="utf-8"))["ASK_COMMANDS"])  # the ask spans: they open with the main agent's own line
ROUNDS = (("dev", "final_verification"), ("ba", "ba_validation"))  # role, the profile of the QA dispatch that judges its work
DEV_PIPELINES = ("dev", "dev-command")  # the obligations of /dev and /redev, and of /dev-command


def _utc(seconds) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def _rows() -> list:
    with suppress(score_log.ScoreLogError):
        return [row for _, row in score_log.read_lines(str(score_log.log_path()))]
    return []


def _as_of(span) -> str:
    return _utc((span.opened_at() if span else None) or time.time())


def _project(cwd) -> str:
    return score_log.project_key(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)


def is_low(role, cwd, span) -> bool:
    """The role's record is low (the two lowest ranks) as of the span's opener."""
    return score_log.low(_rows(), role, _project(cwd), _as_of(span))


def dispatch_context(payload) -> str | None:
    """The SubagentStart text for the payload's subagent: None outside the roster, and in a /close, /commit, /merge or /push span."""
    span = command_span.active_span(payload["transcript_path"])
    if payload["agent_type"] not in roster.roles() or (span and span.command in NO_INJECTION):
        return None
    return score_log.render_dispatch_line(_rows(), payload["agent_type"], _project(payload["cwd"]), _as_of(span))


def main_line(command, cwd) -> str | None:
    """The UserPromptSubmit line of an ask span's opener (the prompt's time is now)."""
    return score_log.render_main_line(_rows(), _project(cwd), _utc(time.time())) if command in ASK_COMMANDS else None


def extra_round_gaps(span, cwd) -> list[str]:
    """/dev, /redev, /dev-command (D32): a lane whose dev has a low record owes a second, independent final-verification QA dispatch after the dev's last
    dispatch, and a BA with a low record a second BA-validation one after its last: one such dispatch so far is the gap. A lane's QA fail sends its dev again."""
    ds = [(call.line, obligation.task_family(ob.get("task_id")), ob.get("lane"), ob.get("role"), ob.get("profile"))
          for call, ob in span.obligations() if ob.get("pipeline") in DEV_PIPELINES and call.ok]
    return [f"dev: lane {lane or fam} owes one more independent {profile} QA dispatch: {role}'s record is low (D32); dispatch QA once more, as the first, with file paths only and nothing of the first round"
            for role, profile in ROUNDS if is_low(role, cwd, span)
            for (fam, lane), line in {(fam, lane): line for line, fam, lane, who, _ in ds if who == role}.items()  # the role's last dispatch per lane: span order
            if sum(1 for at, f, ln, who, prof in ds if (who, prof, f, ln) == ("qa", profile, fam, lane) and at > line) == 1]


def codex_forced(payload, own) -> bool:
    """The stopping agent is a /dev-family QA whose record is low: its round holds a Codex debate whether or not --codex was given (D32). An error is no."""
    with suppress(Exception):
        return own.get("role") == "qa" and own.get("pipeline") in DEV_PIPELINES and is_low("qa", payload["cwd"], command_span.active_span(payload["transcript_path"]))
    return False
