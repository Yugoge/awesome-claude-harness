"""The terminal receipt of an overnight session (P1b acceptance 21, Scope row 15), replayed through the
registered Stop hooks with both trust keys in the replay's environment.

The owner, in their own terminal, binds a resource session to an overnight session with
`scripts/session-resources.py --project-dir <project> provision --binding-json <binding>` (the
`dev-overnight` binding of hooks/tests/test_laneb_stop_coordinator.py's `_binding`, its workflow
generation the one the receipt carries: the cycle plus one), both keys in that call's environment too.
The session's overnight state and closeout are the time-lock test's
(`test_timelock_uses_exact_state_and_publishes_without_finalizing`): the resource session as its dev
registry session, cycle 0, and the closeout on disk that lib/overnight `closeout_gaps` reads after
end_time (Step 20's PM retrospective of cycle 1 and Step 21's summary), so one cycle ended and the
receipt's generation is 2. Then the main agent's Stop is replayed three times: with end_time in the
future, then twice with it past.

Fixtures, not harness writes: the trust root (an absolute directory outside the project, mode 0700),
the overnight state, the retrospective and the summary. prepare() writes the state and the closeout
before the replay starts (cli.prepare: outside the trace, so they are inputs), the state's end_time
LOCK_S seconds ahead; the first Stop comes before it and the driver waits it out before the other two,
so no step of the replay writes any of those files. The trust root is a directory of the sandbox's own (the operator's store
of the keys' records, outside the user's home and project, as the test file's tmp directory is). So
the artifact check's trace (row 19, E1) shows the receipt's writer and readers (terminal.json) and
finalized.json's writer and its later-run reader from the provision call and the Stops alone.

The registered Stop hook is the launcher (hooks/stop-launch.py, P5 R10): it runs the coordinator and
relays its exit 0 or 2, its stdout (the coordinator's record, read here) and its stderr (the Stop
gate's refusal). The time-lock is the Stop gate's step 4 (hooks/stop-command-gate.py), which the
coordinator runs as its completion phase, so a time-lock block is failed_phase completion with the
gate's time-lock refusal. The expected outcomes, recorded in out/facts.json; the replay fails (driver
error) when one does not hold on the tree under test:
  future  the launcher exits 2, blocked at the time-lock (phase_block, failed_phase completion, the
          refusal the time-lock's), finalizer not called, the only block; no terminal.json; the
          scratch intact; no finalized.json
  past1   the launcher exits 0, status pass, finalizer called, not idempotent, no block;
          terminal.json written (terminal_status completed_by_deadline, the binding's workflow
          generation and resource session); the scratch gone; finalized.json written
  past2   the launcher exits 0 again, status pass, finalizer called and idempotent, no block;
          terminal.json not written again (same inode, mtime and size; finalize vouches for the same
          receipt digest)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone

from .. import hookrun
from .close import fact

PIPELINE = "dev-overnight-receipt"
# The artifact check's cost of this driver (tests/artifact_graph/shards.py balances its CI shards by it):
# CPU seconds of the shipped and armed traced replays and their differential runs, measured at 0ea9d65
# (`check --only receipt` 47.8-49.2 CPU-s against 23.2-23.5 for the same check with no replay, less
# the sandbox template's 2.5); its wall time is mostly the LOCK_S wait, which takes no CPU
COST = 22

TRUST_KEY_ENV = "LANEB_SESSION_RESOURCE_TRUST_KEY"
TRUST_ROOT_ENV = "LANEB_SESSION_RESOURCE_TRUST_ROOT"
TRUST_KEY = "cd" * 32       # 64 lowercase hex digits, not all zero
# The registered Stop hook, which relays the coordinator's exit, record and refusal (P5 R10)
LAUNCHER = "stop-launch.py"
# The first line of the Stop gate's time-lock refusal while the window is open (stop-command-gate.py
# window_lock), which the coordinator relays from its completion phase
TIMELOCK = "COMMAND_GATE time-lock: overnight window open until "
# The ids are fixed: prepare() names the session's state file before the replay knows anything else.
SID = "5f0c2e7a-8b1d-4c3e-9a6f-2d4b8e1c7a90"
RSID = "overnight-resource-3c9e1a7b5d20"
DISPATCH = "dispatch-7d2b4f9e1c3a"
TRUST_DIR = "laneb-trust"
# The closeout the time-lock reads after end_time, under the working root (lib/overnight closeout_gaps)
RETRO = f"docs/dev/overnight/{SID}/retro-report-cycle1.json"
SUMMARY = "docs/dev/overnight-summary-2026-01-01.md"
# How far ahead of prepare() the state's end_time lies: the first Stop must come before it (the
# replay's start, a traced provision call), and the replay then waits it out.
LOCK_S = 30
MARGIN_S = 2


def state(end_time: datetime) -> dict:
    return {"session_id": SID, "dev_registry_session_id": RSID, "cycle_count": 0,
            "end_time": end_time.isoformat(timespec="seconds")}


def prepare(project: str, git) -> None:
    """The owner's state before the replay: the overnight state record and its closeout."""
    os.makedirs(os.path.join(project, ".claude"), exist_ok=True)
    for rel, body in ((RETRO, "{}\n"), (SUMMARY, "done\n")):
        os.makedirs(os.path.dirname(os.path.join(project, rel)), exist_ok=True)
        with open(os.path.join(project, rel), "w") as fh:
            fh.write(body)
    end = datetime.now(timezone.utc) + timedelta(seconds=LOCK_S)
    with open(os.path.join(project, ".claude", f"overnight-state-{SID}.json"), "w") as fh:
        json.dump(state(end), fh)


class Unexpected(AssertionError):
    """An outcome acceptance 21 expects did not hold."""


def _stat(path: str) -> dict | None:
    try:
        st = os.stat(path)      # a stat, no open: the driver reads none of the receipt's content here
    except OSError:
        return None
    return {"ino": st.st_ino, "mtime_ns": st.st_mtime_ns, "size": st.st_size}


def _tree(path: str) -> list | None:
    if not path or not os.path.isdir(path):
        return None
    return sorted(os.path.relpath(os.path.join(dp, f), path) + f":{os.stat(os.path.join(dp, f)).st_size}"
                  for dp, _, fs in os.walk(path) for f in fs)


class ReceiptRun:
    def __init__(self, rp):
        self.rp = rp
        lay = rp.layout
        self.project = lay.project
        for kind, value in (("sid", SID), ("sid", RSID), ("agent", DISPATCH)):
            rp.ids.add(kind, value)
        self.trust_root = os.path.join(lay.sb, TRUST_DIR)
        self.keys = {TRUST_KEY_ENV: TRUST_KEY, TRUST_ROOT_ENV: self.trust_root}
        self.binding = {"claude_session_id": SID, "resource_session_id": RSID, "role": "dev",
                        "dispatch_id": DISPATCH, "agent_id": DISPATCH, "command": "dev-overnight",
                        "workflow_instance_id": f"overnight:{SID}", "workflow_generation": 2,
                        "spec_id": "20260808-035658"}
        res = os.path.join(self.project, ".claude", "session-resources", RSID)
        self.terminal = os.path.join(res, "terminal.json")
        self.finalized = os.path.join(res, "finalized.json")
        self.state_path = os.path.join(self.project, ".claude", f"overnight-state-{SID}.json")
        self.scratch = ""
        self.errors: list[str] = []

    def expect(self, what: str, ok: bool, got) -> None:
        if not ok:
            self.errors.append(f"{what}: got {got!r}")

    def end_bounds(self) -> tuple[float, float]:
        """The state's end_time, from the record's mtime (a stat: the driver reads no input): prepare()
        took it LOCK_S seconds after a moment just before the write, cut to whole seconds."""
        written = os.stat(self.state_path).st_mtime
        return written + LOCK_S - 1, written + LOCK_S

    # ------------------------------------------------------------ the trust root and the owner's call
    def trust(self) -> None:
        with self.rp.acting("driver"):
            # the sandbox's reset leaves its own directories: a trust root an earlier run left goes
            shutil.rmtree(self.trust_root, ignore_errors=True)
            os.mkdir(self.trust_root, 0o700)
            os.chmod(self.trust_root, 0o700)
        # both keys in every hook's environment, as runhook.py's --env sets them
        self.rp.env.update(self.keys)

    def provision(self) -> None:
        self.rp.step("script", "owner provision", {})
        env = dict(self.rp.bash_env, **self.keys)
        argv = ["python3", os.path.join(self.rp.layout.harness, "scripts", "session-resources.py"),
                "--project-dir", self.project, "provision", "--binding-json", json.dumps(self.binding)]
        with self.rp.acting("owner"):
            p = subprocess.run(argv, cwd=self.project, env=env, capture_output=True, text=True)
        try:
            out = json.loads(p.stdout)
        except ValueError:
            out = {}
        self.scratch = str(out.get("scratch_path") or "")
        fact(self.rp, "provision", {"rc": p.returncode, "scratch": bool(self.scratch),
                                    "stderr": self.rp.norm_text(p.stderr)[-400:]})
        if p.returncode != 0 or not self.scratch:
            raise Unexpected(f"provision exited {p.returncode} with no scratch_path: {p.stderr[-400:]}")

    def receipt(self, digest: str | None) -> tuple[dict, str]:
        """The receipt's content, as finalize vouched for it (its sha256 the finalizer's
        terminal_receipt_sha256): the copy the Stop's checkpoint phase committed, read from git's
        store, so the driver is no reader of the receipt in the trace; else the file itself."""
        rel = os.path.relpath(self.terminal, self.project)
        with self.rp.acting("driver"):
            refs = subprocess.run(["git", "-C", self.project, "for-each-ref", "--format=%(refname)",
                                   "refs/checkpoints/"], capture_output=True, text=True).stdout.split()
            for ref in refs:
                p = subprocess.run(["git", "-C", self.project, "show", f"{ref}:{rel}"], capture_output=True)
                if p.returncode == 0 and digest and hashlib.sha256(p.stdout).hexdigest() == digest:
                    return json.loads(p.stdout), "checkpoint"
            with open(self.terminal, "rb") as fh:
                body = fh.read()
        return (json.loads(body) if hashlib.sha256(body).hexdigest() == digest else {}), "file"

    # ------------------------------------------------------------ the Stops
    def stop(self, s, label: str) -> dict:
        ev = s.stop("The overnight session's work is done.", label=f"Stop {label}")
        coord = next((h for h in ev.hooks if h["hook"].endswith(LAUNCHER)), None)
        try:
            result = json.loads(coord["stdout"]) if coord else {}
        except ValueError:
            result = {}
        fin = result.get("finalizer") or {}
        refusal = hookrun.refusal_first(coord) if coord and coord["verdict"] == "block" else ""
        seen = {"rc": coord["rc"] if coord else None, "status": result.get("status"),
                "reason": result.get("reason"), "failed_phase": result.get("failed_phase"),
                "finalizer_called": result.get("finalizer_called"), "idempotent": fin.get("idempotent"),
                "receipt_sha256": (fin.get("finalized") or {}).get("terminal_receipt_sha256"),
                "blocks": sorted(h["hook"] for h in ev.blocks), "terminal": _stat(self.terminal),
                "scratch": _tree(self.scratch), "finalized": _stat(self.finalized) is not None,
                "refusal": refusal, "timelock": refusal.startswith(TIMELOCK)}
        fact(self.rp, f"Stop {label}", {k: v for k, v in seen.items() if k not in ("terminal", "refusal")}
             | {"terminal": seen["terminal"] is not None})
        return seen

    def run(self) -> None:
        e = self.expect
        self.trust()
        self.provision()
        scratch0 = _tree(self.scratch)
        s = self.rp.session(SID, start=None)

        ahead = self.end_bounds()[0] - time.time()
        fact(self.rp, "end_time ahead at the first Stop (s, at least)", round(ahead, 1))
        if ahead < MARGIN_S:
            raise Unexpected(f"the state's end_time is {ahead:.1f} s ahead at the first Stop (LOCK_S {LOCK_S}): "
                             "the replay reached it too late to replay the Stop in the window")
        f = self.stop(s, "future")
        e("future: launcher exit", f["rc"] == 2, f["rc"])
        e("future: status/reason/phase", (f["status"], f["reason"], f["failed_phase"])
          == ("blocked", "phase_block", "completion"), (f["status"], f["reason"], f["failed_phase"]))
        e("future: the time-lock's refusal", f["timelock"], f["refusal"])
        e("future: finalizer_called", f["finalizer_called"] is False, f["finalizer_called"])
        e("future: blocks", f["blocks"] == ["hooks/" + LAUNCHER], f["blocks"])
        e("future: terminal.json", f["terminal"] is None, f["terminal"])
        e("future: scratch intact", f["scratch"] is not None and f["scratch"] == scratch0, f["scratch"])
        e("future: finalized.json", f["finalized"] is False, f["finalized"])

        wait = self.end_bounds()[1] + 1 - time.time()
        if wait > 0:
            time.sleep(wait)
        p1 = self.stop(s, "past1")
        e("past1: launcher exit", p1["rc"] == 0, p1["rc"])
        e("past1: status", p1["status"] == "pass", (p1["status"], p1["reason"]))
        e("past1: finalizer_called", p1["finalizer_called"] is True, p1["finalizer_called"])
        e("past1: idempotent", p1["idempotent"] is False, p1["idempotent"])
        e("past1: blocks", p1["blocks"] == [], p1["blocks"])
        e("past1: terminal.json written", p1["terminal"] is not None, p1["terminal"])
        e("past1: scratch gone", p1["scratch"] is None, p1["scratch"])
        e("past1: finalized.json", p1["finalized"] is True, p1["finalized"])
        receipt, source = self.receipt(p1["receipt_sha256"]) if p1["terminal"] else ({}, "")
        got = tuple(receipt.get(k) for k in ("terminal_status", "workflow_generation", "resource_session_id",
                                            "claude_session_id", "command"))
        fact(self.rp, "receipt", dict(zip(("terminal_status", "workflow_generation"), got), source=source))
        e("past1: receipt", got == ("completed_by_deadline", 2, RSID, SID, "dev-overnight"), got)

        p2 = self.stop(s, "past2")
        e("past2: launcher exit", p2["rc"] == 0, p2["rc"])
        e("past2: status", p2["status"] == "pass", (p2["status"], p2["reason"]))
        e("past2: finalizer_called", p2["finalizer_called"] is True, p2["finalizer_called"])
        e("past2: idempotent", p2["idempotent"] is True, p2["idempotent"])
        e("past2: blocks", p2["blocks"] == [], p2["blocks"])
        e("past2: terminal.json not written again", p1["terminal"] is not None and p2["terminal"] == p1["terminal"]
          and p1["receipt_sha256"] is not None and p2["receipt_sha256"] == p1["receipt_sha256"],
          (p1["terminal"], p2["terminal"], p1["receipt_sha256"], p2["receipt_sha256"]))
        fact(self.rp, "acceptance 21", {"pass": not self.errors, "errors": self.errors})
        if self.errors:
            raise Unexpected("acceptance 21's expected outcomes do not hold:\n  " + "\n  ".join(self.errors))


def run(rp) -> None:
    ReceiptRun(rp).run()
