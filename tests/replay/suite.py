"""P1c: D25's replay suite on P1b's runner (tests/replay).

A scenario names one of P1b's drivers (tests/replay/drivers/) and its arguments. run() replays it
untraced, in a sandbox copied from one template built from the tree under test, with the tree's own
settings.json ("shipped") or the sandbox-armed copy ("armed": CLAUDE_OBLIGATION_GATE, _STOPGATE and
_BARRIER block, as tests/replay/sandbox.py arms it). The sandbox runs in the mount namespace
sandbox.py sets up: HOME, CLAUDE_CONFIG_DIR, CLAUDE_STATE_DIR, TMPDIR and the toy project all lie
under the scenario's own directory, and a proxy guard counts every connection a hook or a command
tries (X2: one is a hook error).

What a result says, read from the run's own files (summary.json, blocks.json, hooks.jsonl,
facts.json, terminals.json), never from a list kept here:

* gate blocks: every block the replay met, a block a driver's declared deviation passed included
  (a compliant run passes none);
* hook errors: hookrun's error verdicts (an exit other than 0 and 2, a timeout), a Python traceback
  on a hook's stderr, GATE_ERROR or GATE_FAULT text, and each connection the proxy guard counted;
* terminals: what each pipeline the scenario typed reached, as its driver recorded it
  (Replay.terminal).

The suite's tests (test_pipelines.py, test_faults.py, test_regressions.py, test_no_dead_end.py)
share one Runner per pytest session (conftest.py). It replays every scenario the session's
selected tests need, `REPLAY_WORKERS` at a time, before the first test reads one.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETTINGS = ("shipped", "armed")
TRACEBACK = "Traceback (most recent call last)"
GATE_TEXT = re.compile(r"\bGATE_(?:ERROR|FAULT)\b")


@dataclass(frozen=True)
class Scenario:
    """One replay: `driver` with `args` (cli.py --arg K=V); `pipelines` the commands it types, the last
    one the scenario's own; `cost` its untraced wall seconds on a 4-CPU runner (for the CI split)."""
    name: str
    driver: str
    args: tuple = ()
    pipelines: tuple = ()
    cost: int = 120

    @property
    def key(self) -> str:
        return self.driver + "".join(f"~{k}={v}" for k, v in self.args)

    @property
    def pipeline(self) -> str:
        return self.pipelines[-1]


# (1) compliant: each of the ten pipelines at least once, and the variants P1b's drivers offer
# for the flows D25 names (fan-out, a QA fail, a producer question, a close routing round).
COMPLIANT = (
    Scenario("/spec", "spec", (("variant", "plain"),), ("spec",), 110),
    Scenario("/dev singular", "dev", (("variant", "plain"),), ("dev",), 90),
    Scenario("/dev 2-lane fan-out", "dev", (("variant", "fanout"),), ("dev",), 140),
    Scenario("/dev qafail", "dev", (("variant", "qa-fail"),), ("dev",), 110),
    Scenario("/dev clarify", "dev", (("variant", "question"),), ("dev",), 100),
    Scenario("/redev", "redev", (), ("dev", "redev"), 170),
    Scenario("/dev-command", "dev_command", (("variant", "plain"),), ("dev-command",), 80),
    Scenario("/dev-overnight", "overnight", (("variant", "plain"),), ("dev-overnight",), 600),
    Scenario("/do", "do", (("then", "none"),), ("do",), 60),
    Scenario("/close after /dev", "close", (("variant", "plain"),), ("dev", "close"), 150),
    Scenario("/close after /do", "do", (("then", "close"),), ("do", "close"), 110),
    Scenario("/close append round", "close", (("variant", "append"),), ("dev", "close"), 180),
    # The /do task's close routing round: close QA names the file the /do main agent wrote, and Routes'
    # /do bullet dispatches dev under the same task id (drivers/close.py do_dev).
    Scenario("/close /do route round", "do", (("then", "close"), ("variant", "main-file")), ("do", "close"), 150),
    Scenario("/commit", "commit", (("variant", "auto"),), ("dev", "close", "commit"), 170),
    Scenario("/merge", "merge", (("variant", "plain"),), ("merge",), 40),
    Scenario("/push", "push", (), ("do", "close", "commit", "push"), 130),
)

TEN = ("spec", "dev", "redev", "dev-command", "dev-overnight", "do", "close", "commit", "merge", "push")


@dataclass
class Result:
    scenario: Scenario
    settings: str
    out: str
    rc: int
    wall_s: float
    summary: dict = field(default_factory=dict)
    blocks: list = field(default_factory=list)
    hook_errors: list = field(default_factory=list)
    failed_calls: list = field(default_factory=list)
    respellings: list = field(default_factory=list)
    terminals: list = field(default_factory=list)
    facts: list = field(default_factory=list)
    connections: int = 0
    error: str = ""

    @property
    def run_dir(self) -> str:
        return os.path.join(self.out, "run1-plain")

    def terminal(self, pipeline: str) -> dict | None:
        """The last terminal record of `pipeline` (Replay.terminal), None when the driver recorded none."""
        rows = [t for t in self.terminals if t.get("pipeline") == pipeline]
        return rows[-1] if rows else None

    def fact(self, key: str):
        rows = [f["value"] for f in self.facts if f.get("key") == key]
        return rows[-1] if rows else None

    def hook_events(self) -> list[dict]:
        return _jsonl(os.path.join(self.run_dir, "hooks.jsonl"))

    def row(self) -> dict:
        s = self.summary
        return {"scenario": self.scenario.name, "mode": self.settings, "hook events": s.get("hook_events", 0),
                "hook runs": s.get("hook_runs", 0), "blocks": len(self.blocks), "errors": len(self.hook_errors),
                "terminal": "yes" if self.reached() else "no", "wall s": round(self.wall_s)}

    def reached(self) -> bool:
        return all((self.terminal(p) or {}).get("reached") for p in self.scenario.pipelines)

    def explain(self) -> str:
        lines = [f"{self.scenario.name} ({self.settings}): rc {self.rc}, out {self.out}"]
        if self.error:
            lines.append("  error: " + self.error)
        if self.summary.get("driver_error"):
            lines.append("  driver error: " + self.summary["driver_error"][-1500:])
        for b in self.blocks:
            lines.append(f"  BLOCK {b['hook']} at {b['step']!r} ({b['how']}"
                         f"{', passed by deviation' if b.get('passed_by_deviation') else ''}): {b.get('first') or b['text'][:200]}")
        for e in self.hook_errors:
            lines.append(f"  HOOK ERROR {e['hook']} at {e['step']!r} ({e['how']}): {e.get('stderr', '')[-300:]}")
        for p in self.scenario.pipelines:
            lines.append(f"  terminal {p}: {self.terminal(p)}")
        return "\n".join(lines)


def _jsonl(path: str) -> list[dict]:
    try:
        with open(path) as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except OSError:
        return []


def _json(path: str, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def hook_errors(run_dir: str) -> list[dict]:
    """Every hook error of a run: hookrun's error verdicts (blocks.json) and, from hooks.jsonl, each hook
    run that printed a Python traceback or GATE_ERROR / GATE_FAULT while exiting 0 or 2."""
    out = list(_json(os.path.join(run_dir, "blocks.json"), {}).get("hook_errors", []))
    seen = {(e["step"], e["hook"]) for e in out}
    for ev in _jsonl(os.path.join(run_dir, "hooks.jsonl")):
        for h in ev.get("hooks", []):
            text = (h.get("stderr") or "") + "\n" + (h.get("stdout") or "")
            how = "traceback" if TRACEBACK in (h.get("stderr") or "") else \
                "gate-error-text" if GATE_TEXT.search(text) else ""
            if how and (ev.get("label"), h["hook"]) not in seen:
                seen.add((ev.get("label"), h["hook"]))
                out.append({"step": ev.get("label"), "event": ev.get("event"), "hook": h["hook"], "how": how,
                            "stderr": (h.get("stderr") or "")[-600:]})
    return out


class ProxyGuard:
    """A listener every proxy variable of the replay points at; it counts each connection and closes it
    (X2: a network attempt is a hook error). The replay shares the host's network namespace."""

    def __init__(self):
        self.count = 0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self._lock = threading.Lock()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with self._lock:
                self.count += 1
            conn.close()

    def env(self) -> dict:
        url = f"http://127.0.0.1:{self.port}"
        return {k: url for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                                 "all_proxy")} | {"NO_PROXY": "", "no_proxy": ""}

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


def preconditions() -> list[str]:
    """What the replays need and this host lacks: the mount namespace (root or passwordless sudo)."""
    pre = [] if os.geteuid() == 0 else ["sudo", "-n"]
    try:
        p = subprocess.run(pre + ["unshare", "--mount", "--propagation", "private", "true"], capture_output=True,
                           text=True)
        why = (p.stderr.strip() or f"exit {p.returncode}") if p.returncode else ""
    except OSError as e:
        why = str(e)
    return [f"a mount namespace: `{' '.join(pre + ['unshare', '--mount', 'true'])}` failed: {why}"] if why else []


REGISTRY: dict[str, tuple] = {}


def replay_key(scn: Scenario, settings: str, faults: tuple = (), tag: str = "") -> str:
    """The id a test's `replay` marker names: one replay of `scn` with `settings` and extra driver
    arguments `faults`; registered so the session runner can replay it before the test reads it."""
    key = f"{scn.key}{tag}{''.join(f'~{k}={v}' for k, v in faults)}|{settings}"
    REGISTRY[key] = (scn, settings, tuple(faults), tag)
    return key


class Runner:
    """Replays scenarios of one tree in sandboxes copied from one template under `work`; results cached."""

    def __init__(self, work: str, tree: str = REPO, workers: int | None = None, log=None, env=None,
                 settings_files=None):
        self.work = os.path.abspath(work)
        self.env = dict(env or {})  # added to every replay's hook environment (cli.py --env)
        self.settings_files = dict(settings_files or {})  # a settings name -> the file it replays with
        self.tree = os.path.abspath(tree)
        self.workers = workers or int(os.environ.get("REPLAY_WORKERS") or max(1, min(4, os.cpu_count() or 1)))
        self.log = log or (lambda *a: None)
        self._tpl = None
        self._lock = threading.Lock()
        self._results: dict[tuple, Result] = {}
        self._pending: dict[tuple, threading.Event] = {}
        self.guard = ProxyGuard()

    def template(self) -> str:
        with self._lock:
            if self._tpl is None:
                from tests.replay import sandbox
                sb = os.path.join(self.work, "template")
                info = sandbox.build(self.tree, sb, log=self.log)
                self.log(f"sandbox template: {json.dumps(info)}")
                self._tpl = sb
            return self._tpl

    def run(self, scn: Scenario, settings: str, *, faults: tuple = (), tag: str = "") -> Result:
        """One replay of `scn` with `settings` (shipped or armed); `faults` are extra driver arguments
        (K, V) a fault scenario adds; `tag` keeps such a run apart from the compliant one."""
        key = (scn.key + tag, settings, faults)
        with self._lock:
            if key in self._results:
                return self._results[key]
            ev = self._pending.get(key)
            mine = ev is None
            if mine:
                ev = self._pending[key] = threading.Event()
        if not mine:
            ev.wait()
            return self._results[key]
        try:
            res = self._replay(scn, settings, faults, tag)
        except Exception as e:  # noqa: BLE001 - a replay that cannot start is a failed scenario, reported
            res = Result(scn, settings, "", 1, 0.0, error=f"{type(e).__name__}: {e}")
        with self._lock:
            self._results[key] = res
        ev.set()
        return res

    def run_all(self, items: list[tuple]) -> list[Result]:
        """Replay every (scenario, settings[, faults, tag]) item, `workers` at a time, costliest first."""
        items = sorted(items, key=lambda it: -it[0].cost)
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = [ex.submit(self.run, it[0], it[1], **({"faults": it[2]} if len(it) > 2 else {}),
                              **({"tag": it[3]} if len(it) > 3 else {})) for it in items]
            return [f.result() for f in futs]

    def run_keys(self, keys: list[str]) -> list[Result]:
        """Replay every registered key (replay_key) not yet replayed, `workers` at a time."""
        return self.run_all([REGISTRY[k] for k in keys])

    def get(self, key: str) -> Result:
        scn, settings, faults, tag = REGISTRY[key]
        return self.run(scn, settings, faults=faults, tag=tag)

    def _replay(self, scn: Scenario, settings: str, faults: tuple, tag: str) -> Result:
        from tests.replay import sandbox
        label = re.sub(r"[^A-Za-z0-9_.=~-]", "_", scn.key + tag + "".join(f"~{k}={v}" for k, v in faults))
        out = os.path.join(self.work, "runs", label, settings)
        sb = os.path.join(self.work, "sb", label, settings)
        if os.path.exists(out):
            shutil.rmtree(out)
        os.makedirs(out)
        sandbox.clone(self.template(), sb)
        argv = [sys.executable, "-m", "tests.replay", "run", "--tree", self.tree, "--out", out, "--sandbox", sb,
                "--driver", scn.driver, "--settings", self.settings_files.get(settings, settings), "--runs", "plain"]
        for k, v in tuple(scn.args) + tuple(faults):
            argv += ["--arg", f"{k}={v}"]
        for k, v in {**self.guard.env(), **self.env}.items():
            argv += ["--env", f"{k}={v}"]
        before = self.guard.count
        t0 = time.monotonic()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, text=True)
        wall = time.monotonic() - t0
        with open(os.path.join(out, "replay.log"), "w") as fh:
            fh.write(p.stdout + p.stderr)
        shutil.rmtree(sb, ignore_errors=True)
        rd = os.path.join(out, "run1-plain")
        bl = _json(os.path.join(rd, "blocks.json"), {})
        res = Result(scn, settings, out, p.returncode, wall,
                     summary=_json(os.path.join(rd, "summary.json"), {}),
                     blocks=bl.get("blocks", []), hook_errors=hook_errors(rd),
                     failed_calls=bl.get("failed_calls", []), respellings=bl.get("respellings", []),
                     terminals=_json(os.path.join(rd, "terminals.json"), []),
                     facts=_json(os.path.join(rd, "facts.json"), []))
        # Connections counted while this replay ran; replays run concurrently, so a count is charged to
        # every replay running at the time (any count fails the suite either way).
        res.connections = self.guard.count - before
        for i in range(res.connections):
            res.hook_errors.append({"step": "?", "event": "?", "hook": "network", "how": "connection",
                                    "stderr": f"proxy guard counted a connection ({i + 1})"})
        if not res.summary:
            res.error = f"the replay left no summary (rc {p.returncode}); see {out}/replay.log:\n" + \
                (p.stdout + p.stderr)[-2000:]
        self.log(f"replayed {scn.name} ({settings}) in {wall:.0f} s: rc {p.returncode}, "
                 f"{len(res.blocks)} blocks, {len(res.hook_errors)} hook errors")
        return res


def table(rows: list[dict]) -> str:
    """A markdown table of `rows` (dicts with the same keys)."""
    if not rows:
        return "(no rows)"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    return "\n".join(out)
