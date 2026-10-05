#!/usr/bin/env python3
"""SessionStart hook: census of /dev chains with a dev-report but no close-report.

Enumerates and notifies only. Every unclosed chain gets a queue record; the
existing scripts/resolve-dev-artifact-chain.py runs on as many as the time
budget allows (this hook has no chain-validation logic of its own); a bounded
additionalContext notice is emitted. Never launches claude, /close, /commit,
/restart or git. Always exits 0; failures are made visible, never silent.

Env: CLAUDE_PROJECT_DIR, CLAUDE_ARTIFACT_CENSUS_DIR, CLAUDE_RESTART_STATE_DIR,
CLAUDE_CONTROL_ROOT / CONTROL_ROOT, CLAUDE_CENSUS_WINDOW_DAYS (14),
CLAUDE_CENSUS_MAX_CHAINS (20), CLAUDE_CENSUS_NOTICE_CHARS (2000),
CLAUDE_CENSUS_TOTAL_BUDGET_SECONDS (20), CLAUDE_CENSUS_RESOLVER_TIMEOUT (5),
test-only: CLAUDE_CENSUS_TEST_MODE=1 + CLAUDE_CENSUS_RESOLVER_CMD.
"""

import json
import os
import shlex
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

START = time.monotonic()
HARNESS_HOME = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
GAP_CODES = ("MISSING_ARTIFACT", "EMPTY_ARTIFACT")
NON_WORKER = {"draft", "final", "fix", "continuation", "wip", "template"}
NEXT_ACTION = (
    "Recover interrupted agents via the human-only restart path first, then "
    "run /close (resolver pass) or repair via /dev per the resolver codes."
)


def _env_num(name, default, cast=float):
    try:
        return cast(os.environ.get(name, default))
    except (TypeError, ValueError):
        return cast(default)


def _now():
    return datetime.now(timezone.utc).isoformat()


def project_dir():
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def restart_state_dir():
    override = os.environ.get("CLAUDE_RESTART_STATE_DIR")
    return Path(override) if override else Path.home() / ".claude" / "restart-state"


def census_dir():
    override = os.environ.get("CLAUDE_ARTIFACT_CENSUS_DIR")
    return Path(override) if override else restart_state_dir() / "artifact-census"


def _is_shard_or_template(stem, stems):
    last = stem.rsplit("-", 1)[-1].lower()
    if stem.lower() == "template" or last in NON_WORKER:
        return True
    if last.startswith(("iter", "retry", "attempt")) and last.rstrip("0123456789") in (
        "iter", "retry", "attempt"
    ):
        return True
    return any(o != stem and stem.startswith(o + "-") for o in stems)


def enumerate_chains(pdir):
    ddir = pdir / "docs" / "dev"
    if not os.path.exists(ddir):
        return []
    names = os.listdir(ddir)  # raises on unreadable: surfaced by fail-safe
    stems = {}
    for n in names:
        if n.startswith("dev-report-") and n.endswith(".json"):
            stems[n[len("dev-report-"):-len(".json")]] = ddir / n
    return [(s, p) for s, p in stems.items() if not _is_shard_or_template(s, stems)]


def close_roots(pdir):
    roots = [pdir]
    cur = pdir.resolve()
    for anc in [cur, *cur.parents]:
        if (anc / ".git").exists():
            roots.append(anc)
            break
    ctl = os.environ.get("CLAUDE_CONTROL_ROOT") or os.environ.get("CONTROL_ROOT")
    roots.append(Path(ctl) if ctl else HARNESS_HOME)
    return roots


def is_closed(task_id, roots):
    return any((r / "docs" / "dev" / f"close-report-{task_id}.md").exists() for r in roots)


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def resolver_argv(task_id, pdir):
    if os.environ.get("CLAUDE_CENSUS_TEST_MODE") == "1" and os.environ.get("CLAUDE_CENSUS_RESOLVER_CMD"):
        base = shlex.split(os.environ["CLAUDE_CENSUS_RESOLVER_CMD"])
    else:
        base = [sys.executable, str(HARNESS_HOME / "scripts" / "resolve-dev-artifact-chain.py")]
    return base + ["--task-id", task_id, "--project-dir", str(pdir)]


def run_resolver(task_id, pdir, timeout):
    """Return fields to merge into the record."""
    try:
        cp = subprocess.run(
            resolver_argv(task_id, pdir), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return {"resolver_status": "resolver_error", "resolver_exit": None,
                "resolver_stderr_tail": "timeout", "error_codes": [], "lane_gap": False}
    except Exception as exc:
        return {"resolver_status": "resolver_error", "resolver_exit": None,
                "resolver_stderr_tail": f"{type(exc).__name__}: {exc}"[-300:],
                "error_codes": [], "lane_gap": False}
    try:
        res = json.loads(cp.stdout)
        if not isinstance(res, dict):
            raise ValueError("not an object")
    except Exception:
        return {"resolver_status": "resolver_error", "resolver_exit": cp.returncode,
                "resolver_stderr_tail": (cp.stderr or "")[-300:],
                "error_codes": [], "lane_gap": False}
    codes = [e.get("code") for e in res.get("errors", []) if isinstance(e, dict)]
    status = res.get("status")
    if status not in ("pass", "pass_with_exceptions", "fail"):
        status = "pass" if cp.returncode == 0 else "fail"
    return {
        "resolver_status": status, "resolver_exit": cp.returncode, "error_codes": codes,
        "lane_gap": any(c in GAP_CODES for c in codes),
        "gap_classification": res.get("gap_classification"),
        "late_repair_eligible": res.get("late_repair_eligible"),
        "resolver_result": res,
    }


def pending_restart_count():
    sd = restart_state_dir()
    count = 0
    try:
        files = [p for p in sd.iterdir() if p.is_file() and p.suffix == ".json"]
    except Exception:
        return 0
    for p in files:
        data = load_json(p)
        cands = data.get("candidates") if isinstance(data, dict) else None
        if isinstance(cands, list):
            count += sum(
                1 for c in cands
                if isinstance(c, dict) and c.get("status") != "response_observed"
            )
    return count


def mark_closed(qdir, roots):
    if not qdir.is_dir():
        return
    for rec_path in qdir.glob("*.json"):
        if rec_path.name == "census-error.json":
            continue
        rec = load_json(rec_path)
        if isinstance(rec, dict) and rec.get("resolver_status") != "closed" \
                and rec.get("task_id") and is_closed(rec["task_id"], roots):
            rec["resolver_status"] = "closed"
            rec["last_seen"] = _now()
            rec["next_action"] = "close-report present; chain closed."
            atomic_write(rec_path, rec)


def build_notice(total, window_ids, omitted_age, pending, qdir, cap_chars, restart_n, max_chains):
    ids = window_ids[:max_chains]

    def render(shown):
        omitted_cap = len(window_ids) - len(shown)
        lines = [
            "Artifact census: /dev chains with a dev-report but no close-report.",
            f"total_unclosed={total} listed={len(shown)} omitted_for_age={omitted_age} "
            f"omitted_for_cap={omitted_cap} resolver_pending={pending}",
            f"queue_dir={qdir}",
        ]
        if restart_n:
            lines.append(f"{restart_n} interrupted agent(s) await restart (human-only restart path).")
        if shown:
            lines.append("chains: " + ", ".join(shown))
        lines.append("Enumerate/notify only: restart interrupted agents first, then /close or /dev.")
        return "\n".join(lines)

    text = render(ids)
    while len(text) > cap_chars and ids:
        ids = ids[:-1]
        text = render(ids)
    return text[:cap_chars]


def emit(text):
    sys.stdout.write(json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
    sys.stdout.flush()


def run():
    try:
        sys.stdin.read()
    except Exception:
        pass
    pdir = project_dir()
    roots = close_roots(pdir)
    qdir = census_dir()
    window_s = _env_num("CLAUDE_CENSUS_WINDOW_DAYS", 14) * 86400
    max_chains = _env_num("CLAUDE_CENSUS_MAX_CHAINS", 20, int)
    cap_chars = _env_num("CLAUDE_CENSUS_NOTICE_CHARS", 2000, int)
    budget = _env_num("CLAUDE_CENSUS_TOTAL_BUDGET_SECONDS", 20)
    per_chain = _env_num("CLAUDE_CENSUS_RESOLVER_TIMEOUT", 5)

    mark_closed(qdir, roots)
    unclosed = []
    for stem, path in enumerate_chains(pdir):
        if not is_closed(stem, roots):
            unclosed.append((os.stat(path).st_mtime, stem, path))
    if not unclosed:
        return
    unclosed.sort(reverse=True)
    now = time.time()
    records = {}
    for mtime, stem, path in unclosed:
        rp = qdir / f"{stem}.json"
        old = load_json(rp) if rp.exists() else None
        rec = {
            "schema_version": SCHEMA_VERSION, "task_id": stem,
            "first_seen": (old or {}).get("first_seen") or _now(), "last_seen": _now(),
            "resolver_status": "resolver_pending", "error_codes": [], "lane_gap": False,
            "in_notice_window": (now - mtime) <= window_s,
            "dev_report_path": str(path), "next_action": NEXT_ACTION,
        }
        records[stem] = (rp, rec)
        atomic_write(rp, rec)
    for _, stem, _p in unclosed:
        remaining = budget - (time.monotonic() - START)
        if remaining <= 0:
            break
        rp, rec = records[stem]
        rec.update(run_resolver(stem, pdir, min(per_chain, remaining)))
        rec["last_seen"] = _now()
        atomic_write(rp, rec)
    window_ids = [s for _, s, _p in unclosed if records[s][1]["in_notice_window"]]
    pending = sum(1 for _, r in records.values() if r["resolver_status"] == "resolver_pending")
    emit(build_notice(len(unclosed), window_ids, len(unclosed) - len(window_ids),
                      pending, qdir, cap_chars, pending_restart_count(), max_chains))


def main():
    try:
        run()
    except BaseException as exc:  # never wedge session start; stay visible
        if isinstance(exc, SystemExit):
            return 0
        cls = type(exc).__name__
        where = "(census dir unwritable)"
        try:
            qdir = census_dir()
            atomic_write(qdir / "census-error.json", {
                "timestamp": _now(), "exception_class": cls,
                "traceback_tail": traceback.format_exc()[-1500:]})
            where = str(qdir / "census-error.json")
        except Exception:
            pass
        line = f"artifact census FAILED: {cls} (see {where})"
        sys.stderr.write(line + "\n")
        try:
            emit(line)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
