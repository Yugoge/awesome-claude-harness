"""P5 R14 / A26 (tests/replay/test_r14_faults.py): fault replays of the /merge and /push refusals that
test_refusals.py does not reach, each played by drivers/merge.py (MergeRun) or drivers/push.py (PushRun)
unchanged, with one fault injected at the step it names, and the action the refusal names taken.

    --arg case=<name>

The leading underscore keeps it out of the artifact check's driver set (tests/artifact_graph/
runtime.py drivers()): its replays inject faults, and P1c's suite runs it, not the check.

  merge-nogrant    /merge (drivers/merge.py, variant plain): the merge-analyst's first Write of its grant is
                   not made (faults.py `missing`), so Step 3 finds no grant at its path: refused, the owner
                   picks the action it names ("re-run the analysis now": Step 1's REQUEST_ID line, then Step
                   2), and the second analysis's grant goes on to Steps 4 and 5 in the same turn.
  merge-blocked    /merge after the owner committed conflict-marker lines on the feature branch: the
                   merge-analyst's Phase 4 blocks, Step 3 refuses with its risks ("resolve the listed risks
                   first"), the turn ends; the owner resolves them (a commit removing the markers, in their
                   terminal) and types /merge again (his own command), which merges.
  merge-moved      /merge whose feature branch takes one more commit of the owner's (their terminal) after
                   the analyst's grant and before Step 4's tip re-read: Step 4 refuses ("re-run the
                   analysis now"), the owner picks it, and the turn goes on as the action says.
  merge-nosession  /merge whose first Step 1 snapshot runs without the session id the CLI's Bash exports
                   (CLAUDE_CODE_SESSION_ID unset in that call's process only; the hooks see the call as
                   usual): Step 1 refuses ("re-run the snapshot now"), the owner picks it, and the snapshot
                   run again goes on to the merge.
  push-nosession   /push (drivers/push.py `after=none token=owner`: one owner commit ahead of the origin and
                   the push-gate token its one writer wrote for it) whose first Step 2 snapshot runs without
                   CLAUDE_SESSION_ID and CLAUDE_CODE_SESSION_ID: Step 2 refuses ("re-run the snapshot now"),
                   and the snapshot run again goes on to the push.
  push-blocked     as push-nosession's setup, the owner's commit adding a settings file whose name the
                   push-analyst's Phase 2 flags and whose content carries a credential-shaped placeholder:
                   the analyst blocks, execute-push.py refuses ("push BLOCKED by push-analyst": "resolve the
                   listed risks first"), the turn ends; the owner resolves it (the file taken out of his
                   commit, which he amends, and the token's one writer run for the amended commit, as before)
                   and types /push again, which pushes.

Each fault records itself in facts.json ("r14 fault": case, step label or owner setup), merge-nogrant's
in faults.json (faults.py's own record); drivers/merge.py and drivers/push.py record each refusal they
ask ("merge refusal" / "push refusal") and the outcome. One terminal for the scenario's command, from
the last turn's Stop.
"""
from __future__ import annotations

import subprocess

from .. import faults, replay
from . import close as closedrv
from . import merge as mergedrv
from . import push as pushdrv

PIPELINE = "r14"
CASES = ("merge-nogrant", "merge-blocked", "merge-moved", "merge-nosession", "push-nosession", "push-blocked")

# merge-blocked: the owner's feature commit with an unresolved conflict left in it (git diff --check's
# "leftover conflict marker"), and the commit that resolves it back to the feature's own text.
SUB_MARKED = ("def sub(a, b):\n<<<<<<< HEAD\n    return a - b\n=======\n    return -(b - a)\n"
              ">>>>>>> other\n")
# merge-moved: the owner's commit on the feature branch while the analysis runs.
SUB_MORE = mergedrv.SUB_NEW + "\n\ndef neg(a):\n    return -a\n"
# push-blocked: a file the push-analyst's sensitive-name list matches (`*secret*`), its value a
# credential-shaped placeholder (no real secret).
SECRET_FILE = "toy/secret_settings.py"
SECRET_TEXT = 'API_SECRET = "PLACEHOLDER0PLACEHOLDER0PLACEHOLDER"\n'


def _once(rp, case: str, fn):
    """A fault hook doing `fn(step)` at the first step its label matches (before the call), recorded."""
    done: list = []

    def hook(rp_, phase, step):
        if phase != "before" or done:
            return
        done.append(1)
        fn(step)
        closedrv.fact(rp, "r14 fault", {"case": case, "label": step["label"]})
    return hook


def _without_session_id(rp):
    """The call's tool runs with no session id in its environment (the CLI's Bash not exporting it)."""
    def fn(step):
        ti = step["input"]

        def perform():
            env = {k: v for k, v in rp.bash_env.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")}
            p = subprocess.run(["bash", "-c", ti["command"]], cwd=rp.layout.project, env=env, capture_output=True,
                               text=True, timeout=replay.BASH_TIMEOUT_S, errors="replace")
            if p.returncode:
                raise replay.ToolError(f"Exit code {p.returncode}\n{p.stderr}{p.stdout}".strip())
            return {"stdout": p.stdout, "stderr": p.stderr, "interrupted": False, "isImage": False}
        step["perform"] = perform
    return fn


def _owner_commit(rp, rel: str, text: str, msg: str, date: str) -> None:
    p = rp.layout.project
    with rp.acting("owner"):
        mergedrv._write(p, rel, text)
        mergedrv._owner_git(p, "add", rel)
        mergedrv._owner_git(p, "commit", "-qm", msg, date=date)


def _merged(rp) -> bool:
    p = rp.layout.project
    with rp.acting("driver"):
        tip = subprocess.run(["git", "-C", p, "rev-parse", "-q", "--verify", mergedrv.FEATURE], capture_output=True,
                             text=True).stdout.strip()
        return bool(tip) and not subprocess.run(["git", "-C", p, "merge-base", "--is-ancestor", tip, "master"],
                                                capture_output=True).returncode


def merge(rp, case: str) -> None:
    mergedrv.owner_setup(rp, "plain")
    if case == "merge-blocked":
        _owner_commit(rp, "toy/util.py", SUB_MARKED, "toy: sub from the other side", "2026-01-01T00:03:00+0000")
        closedrv.fact(rp, "r14 fault", {"case": case, "label": "owner setup: conflict markers on the feature branch"})
    closedrv.fact(rp, "owner setup", mergedrv.toy_state(rp))
    if case == "merge-nogrant":
        faults.install(rp, "missing@agent:merge-analyst Write grant")
    elif case == "merge-moved":
        rp.faults.append(("/merge Step 4 Bash revalidate tips", _once(rp, case, lambda step: _owner_commit(
            rp, "toy/util.py", SUB_MORE, "toy: neg", "2026-01-01T00:04:00+0000"))))
    elif case == "merge-nosession":
        rp.faults.append(("/merge Step 1 Bash snapshot", _once(rp, case, _without_session_id(rp))))
    last = mr = mergedrv.MergeRun(rp)
    mr.run("")
    if case == "merge-blocked" and not _merged(rp):
        # The action the refusal names is the owner's: he resolves the listed risks in his terminal, then
        # types his own command again.
        _owner_commit(rp, "toy/util.py", mergedrv.SUB_RESOLVED, "toy: resolve sub", "2026-01-01T00:05:00+0000")
        closedrv.fact(rp, "owner resolved the risks", mergedrv.toy_state(rp))
        last = mergedrv.MergeRun(rp, session=mr.o.s, tag="/merge again")
        last.run("")
    rp.terminal("merge", _merged(rp), getattr(last, "stop_ev", None), topic=mergedrv.FEATURE)


def _pushed(rp) -> bool:
    rows = [f["value"] for f in pushdrv._facts(rp) if f.get("key") == "push"]
    return bool(rows) and bool(rows[-1].get("pushed"))


def push(rp, case: str) -> None:
    if case == "push-blocked":
        _owner_commit(rp, SECRET_FILE, SECRET_TEXT, "toy: settings", "2026-01-01T00:02:00+0000")
        closedrv.fact(rp, "r14 fault", {"case": case, "label": f"owner setup: {SECRET_FILE} in the commit to push"})
    else:
        pushdrv.owner_commit(rp)
    pushdrv.owner_token(rp)
    s = rp.session()
    closedrv.fact(rp, "before /push", {"owner commit": True, "toy": pushdrv.origin_state(rp),
                                       "left": pushdrv.leftovers(rp)})
    if case == "push-nosession":
        rp.faults.append(("/push Step 2 Bash snapshot", _once(rp, case, _without_session_id(rp))))
    last = pr = pushdrv.PushRun(rp, s)
    pr.run()
    if case == "push-blocked" and not _pushed(rp):
        # The owner's action: the flagged file out of his commit (amended), the token's one writer run for
        # the amended commit as before, and his own /push again.
        p = rp.layout.project
        with rp.acting("owner"):
            mergedrv._owner_git(p, "rm", "-q", SECRET_FILE)
            mergedrv._write(p, "README.md", mergedrv.README_MAIN)
            mergedrv._owner_git(p, "commit", "-q", "-a", "--amend", "-m", "docs: say what toy does",
                                date="2026-01-01T00:03:00+0000")
        pushdrv.owner_token(rp)
        closedrv.fact(rp, "owner resolved the risks", {"toy": pushdrv.origin_state(rp)})
        last = pushdrv.PushRun(rp, s, tag="/push again")
        last.run()
    rp.terminal("push", _pushed(rp), getattr(last, "stop_ev", None))


def run(rp) -> None:
    case = rp.args.get("case", "")
    if case not in CASES:
        raise ValueError(f"unknown case {case!r}")
    rp.pipeline = f"r14/{case}"
    (merge if case.startswith("merge") else push)(rp, case)
