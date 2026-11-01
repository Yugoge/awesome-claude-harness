"""The CLI's CronCreate scheduler, as /dev-overnight's wake meets it (P1c X8, R17), modeled.

Modeled CLI behaviour and its sources (none of it measured on a harness host):
* CronCreate `{cron, prompt, recurring}` returns a job id; its tool_result carries
  `toolUseResult{id, humanSchedule, recurring, durable:false, nextFireAt}` (P1's capture of a one-shot
  job, CLI 2.1.303, as COV-7 corrects it; the recurring job's result is assumed to have the same shape:
  UNVERIFIED). CronDelete `{id}` cancels the job (the tools' descriptions, read 2026-11-01).
* "Jobs only fire while the REPL is idle (not mid-query)"; a recurring job fires "on every cron match
  until deleted or auto-expired after 7 days"; jobs are session-only (the CronCreate description, read
  2026-11-01). The per-job firing offset ("up to 50% of its period late") is not modeled: a fire is an
  idle period of one cron interval.
* A fired prompt is an `enqueue` queue-operation, then UserPromptSubmit, then a `type:"user"` record with
  string content, `isMeta:true`, `turnOrigin:"scheduled"`, `promptSource:"system"`,
  `queueSkipSlashCommands:true`, `queueSkipAttachments:true`, `turnPosition`, and no `origin` (COV-7, CLI
  2.1.303). That UserPromptSubmit fires for a scheduled task is documented (COV-7's capability row);
  that the hook runs before the record is written is the order replay.py models for every prompt.
* That a usage-limit cut leaves the REPL idle, and that the job then fires once the limit has reset, is
  UNVERIFIED (P1c X8): F6o's replays model it so.

The clock is modeled: `idle(session, intervals)` lets `intervals` cron intervals pass while the session is
idle, and each live job fires once per interval. Nothing sleeps.
"""
from __future__ import annotations

import re
import uuid

from .replay import ToolError, now_iso


def interval_minutes(cron: str) -> int:
    """The shortest gap, in minutes, between two matches of the cron's minute field (`*/N`, a list, `*`)."""
    minute = (cron.split() or ["*"])[0]
    m = re.fullmatch(r"\*/(\d+)", minute)
    if m:
        return int(m.group(1))
    if minute == "*":
        return 1
    marks = sorted(int(x) for x in minute.split(",") if x.isdigit())
    if len(marks) < 2:
        return 60
    return min(b - a for a, b in zip(marks, marks[1:] + [marks[0] + 60]))


class Cron:
    """The session's cron jobs (rp.cron): the tool calls' performers, and the fires while idle."""

    def __init__(self, rp):
        self.rp = rp
        self.jobs: dict = {}       # id -> CronCreate input, while live
        self.created: list = []    # ids, in order
        self.deleted: list = []
        self.fired: list = []      # {"job", "label", "minute"} per fire
        self.minute = 0            # the modeled clock, minutes since the session started

    # ------------------------------------------------------------ the tools
    def create(self, tinput: dict) -> dict:
        job = uuid.uuid4().hex[:8]
        self.rp.rand(job)
        self.jobs[job] = dict(tinput)
        self.created.append(job)
        return {"id": job, "humanSchedule": f"cron {tinput.get('cron')}", "recurring": tinput.get("recurring", True),
                "durable": False, "nextFireAt": now_iso()}

    def delete(self, job: str) -> dict:
        if job not in self.jobs:
            raise ToolError(f"No scheduled job with id {job}")
        del self.jobs[job]
        self.deleted.append(job)
        return {"id": job}

    def tool_create(self, s, tinput: dict, label: str, deviation=None):
        return s.tool("CronCreate", tinput, perform=lambda: self.create(tinput), label=label, deviation=deviation)

    def tool_delete(self, s, job: str, label: str, deviation=None):
        return s.tool("CronDelete", {"id": job}, perform=lambda: self.delete(job), label=label, deviation=deviation)

    # ------------------------------------------------------------ the fires
    def idle(self, s, intervals: int = 1, label: str = "wake") -> list:
        """`intervals` cron intervals pass while the session is idle: each live job fires once per
        interval, as the scheduled prompt the CLI records. Returns the fires' UserPromptSubmit events."""
        events = []
        for _ in range(intervals):
            due = sorted(self.jobs.items())
            self.minute += min((interval_minutes(j.get("cron", "")) for _, j in due), default=10)
            for job, tinput in due:
                events.append(self.fire(s, job, tinput.get("prompt", ""), f"{label} (scheduled job {job})"))
        return events

    def fire(self, s, job: str, text: str, label: str):
        rp = self.rp
        step = rp.step("scheduled", label, {"text": text})
        s._write(s.tpath, {"type": "queue-operation", "operation": "enqueue", "content": text,
                           "timestamp": now_iso(), "sessionId": s.sid})
        ev = s.fire("UserPromptSubmit", label, {"prompt": text})
        if not rp.settle(ev, label, None):
            s.append({"type": "user", "isMeta": True, "turnOrigin": "scheduled", "promptSource": "system",
                      "queueSkipSlashCommands": True, "queueSkipAttachments": True,
                      "turnPosition": {"promptIndex": len(self.fired), "turnIndex": 0},
                      "message": {"role": "user", "content": text}})
            s._context(ev)
        self.fired.append({"job": job, "label": label, "minute": self.minute})
        rp.after(step, ev)
        return ev

    def facts(self) -> dict:
        return {"created": list(self.created), "deleted": list(self.deleted), "live": sorted(self.jobs),
                "fired": list(self.fired)}
