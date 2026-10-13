"""Build Claude Code 2.1.29x-shaped main transcripts for gate experiments.

Record shapes follow the real transcript of this session (queue-operation first,
slash command as <command-name>, isMeta command body, attachment records) and the
armed-sandbox drivers (adv3-do-close-commit-push/tools/drv.py).
"""
import itertools
import json
import uuid

_ids = itertools.count(1)


class Tx:
    def __init__(self, path, sid="sess-g"):
        self.path = path
        self.sid = sid
        self.recs = []

    def _add(self, rec):
        rec.setdefault("sessionId", self.sid)
        rec.setdefault("uuid", str(uuid.uuid4()))
        rec.setdefault("version", "2.1.295")
        self.recs.append(rec)

    def qop(self, content):
        self._add({"type": "queue-operation", "operation": "enqueue", "content": content})

    def slash(self, cmd, args=""):
        self.qop(f"/{cmd} {args}".strip())
        self._add({"type": "user", "message": {"role": "user", "content":
                   f"<command-message>{cmd} is running…</command-message>\n"
                   f"<command-name>/{cmd}</command-name>\n<command-args>{args}</command-args>"}})
        self._add({"type": "user", "isMeta": True,
                   "message": {"role": "user", "content": [{"type": "text", "text": f"(body of {cmd}.md)"}]}})
        self._add({"type": "attachment", "attachment": {"type": "hook_additional_context",
                                                        "content": f"hook output for /{cmd}"}})

    def say(self, text):
        self.qop(text)
        self._add({"type": "user", "message": {"role": "user", "content": text}})

    def tool(self, name, inp, result="ok", is_error=False):
        tid = f"toolu_{next(_ids):06d}"
        self._add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
        block = {"type": "tool_result", "tool_use_id": tid, "content": result}
        if is_error:
            block["is_error"] = True
        self._add({"type": "user", "message": {"role": "user", "content": [block]}})
        return tid

    def todo(self, todos):
        return self.tool("TodoWrite", {"todos": todos})

    def text(self, text):
        self._add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": text}]}})
        return text

    def write(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            for r in self.recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return self.path


def with_status(todos, done, in_progress=True):
    """First `done` items completed, next one in_progress (if any)."""
    out = []
    for i, t in enumerate(todos):
        t = {k: v for k, v in t.items() if k in ("content", "activeForm")}
        if i < done:
            t["status"] = "completed"
        elif i == done and in_progress:
            t["status"] = "in_progress"
        else:
            t["status"] = "pending"
        out.append(t)
    return out


def obligation(task_id, role, pipeline, profile="singular", artifacts=None):
    doc = {"task_id": task_id, "role": role, "pipeline": pipeline, "profile": profile,
           "dispatched_at": "2026-10-13T00:00:00Z",
           "artifacts": artifacts or [{"kind": "json", "path": f"docs/dev/qa-report-{task_id}.json",
                                       "schema": "qa-report.v2", "identity": {"task_id": task_id}}]}
    return f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>'
