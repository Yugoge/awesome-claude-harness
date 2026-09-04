#!/usr/bin/env python3
"""Adversarial tests for the deferred commit-grant finalizer in
hooks/posttool-allowlist-consume.py, and for the pointer WRITE side in
hooks/pretool-git-privilege-guard.py that has to agree with it.

THE DEFECT UNDER TEST. PreToolUse renames an authorized single-use commit grant aside
(<path>.lck) and writes a pointer file; the matching PostToolUse finds that pointer,
consumes or restores the grant, removes the pointer, and — this is what raised the stakes —
writes a commit-event journal entry a later push-gate token can be reconciled from.

The pointer used to be named for a SESSION id, and two containments were tried on the READ
side. The first refused to journal when the session-specific lookup missed AND several
pointers were live. The second resolved the pointer by trying the same session keys the
writer uses (payload sid, then CLAUDE_SESSION_ID, then CLAUDE_CODE_SESSION_ID), and refused
to journal whenever the pointer was reached only by an untargeted wildcard scan.

Neither is enough, because a targeted NAME proves only that two things share a session id.
An event with NO pointer of its own — an auto-bulk commit, where _evaluate_commit accepts a
multi-use sentinel and returns BEFORE _lock_grant_for_posttool, or an event whose pointer
write failed — still resolves a stale or concurrent ORDINARY grant living under the same
environment session id. It then journals a record mixing that grant's task_id / branch /
parent_head with this event's session id AND consumes or restores a grant that is not its
own. When the two commits share an expected parent the mixed record also passes
_parent_linkage_verified, so it is SPENDABLE, not inert. `mutation_reopens_*` below pins
exactly that, by re-deriving the key the pre-fix way and watching the attack land.

THE FIX UNDER TEST: bind the pointer to the EVENT. `tool_use_id` is the one identifier the
runtime hands to both hook payloads of a single tool call, so the guard names the pointer
for it and the finalizer looks up that one name — no session keys, no wildcard, no
fallback. An event with no pointer of its own therefore acts on nothing at all: no journal
entry, and no touch of any other event's grant.

AUDIT ROUND 2 EXTENSIONS. R2-2: the derived key is lossy (fold + cap), so the pointer
also records the RAW tool_use_id and the finalizer compares raw values — the `r22_*`
checks pin that two distinct raw ids sharing a derived name can never cross-finalize.
R2-3: a grant that cannot be deferred (no key, rename failure) is left IN PLACE rather
than destroyed pre-commit — the expected_head binding neutralizes reuse-after-success —
and a pointer write that fails after the rename RESTORES the grant instead of stranding
the .lck. R2-4: revocation discovers event-keyed pointers by their recorded grant paths
(the `r24_*` checks drive scripts/write-commit-grant.py's real revoke path).

TWO PROPERTIES THIS FILE EXISTS TO HOLD.
  - The ORDINARY path must keep journaling. The grant is minted under the orchestrator's
    session id while the finalizer runs under the subagent's; that divergence is normal
    (the guard records it in _find_grant_any) and `ordinary_flow_*` keeps every session id
    distinct, so a binding that quietly depended on one would fail here and not in
    production, where reconciliation would just stop working unnoticed.
  - Grants must not be stranded. The wildcard scan used to clear abandoned pointers by
    accident; `stranding_*` pins the deliberate replacements.

Run: python3 hooks/tests/test_posttool_commit_grant_finalize.py
"""

import fnmatch
import glob
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import lib.allowlist as AL  # noqa: E402
import lib.commit_journal as CJ  # noqa: E402

CHECKS = []
FAILURES = []


def _load(filename, module_name):
    """Import a hook by path — hook filenames are not valid module names."""
    path = HOOKS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PT = _load("posttool-allowlist-consume.py", "posttool_allowlist_consume")
GUARD = _load("pretool-git-privilege-guard.py", "pretool_git_privilege_guard")


def _load_script(filename, module_name):
    path = HOOKS_DIR.parent / "scripts" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Revocation (audit R2-4) discovers event-keyed pointers by their RECORDED grant
# paths; its namespace glob is redirected alongside the hooks' templates in main().
WCG = _load_script("write-commit-grant.py", "write_commit_grant")

# The globs hooks/stop-cleanup-allowlist.sh sweeps at session end, copied verbatim. The
# event-keyed pointer names must keep matching them, because that Stop hook is now the
# outer deliberate reaper for anything the mid-session sweep has not yet aged out.
STOP_CLEANUP_POINTER_GLOB = "/tmp/claude-commit-grant-active-*.json"
STOP_CLEANUP_LOCKED_GLOB = "/tmp/claude-commit-grant-*.json.lck"


def check(name, condition):
    # CHECKS is appended to by every executed check, so the summary counts what actually
    # ran. Do NOT reintroduce a hardcoded total: a literal cannot notice a check being
    # deleted or short-circuited, and the exit status is computed from FAILURES
    # independently, so a stale total would misreport coverage silently.
    CHECKS.append(name)
    print(("PASS  " if condition else "FAIL  ") + name)
    if not condition:
        FAILURES.append(name)


def git(root, *args):
    return subprocess.run(["git", "-C", str(root)] + list(args),
                          capture_output=True, text=True, check=True).stdout.strip()


def make_repo(parent, name):
    root = os.path.join(parent, name)
    os.makedirs(root)
    for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                 ["config", "user.name", "test"]):
        git(root, *args)
    return root


def make_commit(root, message):
    with open(os.path.join(root, "f.txt"), "a") as handle:
        handle.write(message + "\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def grant_bytes(sid, task_id, repo_root, parent):
    """The on-disk grant payload. Byte-stable so a restore can be compared exactly."""
    return json.dumps({"task_id": task_id, "sid": sid, "repo_root": repo_root,
                       "branch": "master", "expected_head": parent},
                      sort_keys=True).encode()


def raw_of(key):
    """Default RAW tool_use_id for a derived key (audit R2-2 pointer field).

    Every ordinary scenario here uses keys whose raw id is already filename-safe, so
    the raw form is just the key minus its 'tu-' prefix. Mutation scenarios key by
    session id — the pre-fix world had no separate raw at all, so the key doubles as
    both there, which is exactly what lets `mutation_reopens_*` land its attack.
    """
    return key[3:] if key.startswith("tu-") else key


def finalize(key, session_id, result, raw=None):
    """Drive the finalizer with the derived key AND the raw id it must prove against."""
    PT._finalize_deferred_commit_grant(key, raw_of(key) if raw is None else raw,
                                       session_id, result)


def mint(base, key, task_id, repo_root, parent, sid=None, raw=None):
    """A locked grant + its pointer, exactly as the guard's _lock_grant_for_posttool writes.

    `key` is the pointer's event key. Production always derives it from `tool_use_id`;
    passing a session id here is what `mutation_reopens_*` uses to re-create the pre-fix
    world, so the two are deliberately separable at this seam and nowhere else. `raw` is
    the pointer's recorded verbatim tool_use_id (audit R2-2); it defaults to raw_of(key)
    and is passed explicitly by the collision scenarios, where key and raw diverge.

    `parent` must be the REAL first parent of the head the entry will record: the matcher
    verifies recorded parent == actual first parent, so a placeholder would make every
    attribution check below pass vacuously.
    """
    original = os.path.join(base, "claude-commit-grant-%s-nonce.json" % task_id)
    locked = original + ".lck"
    payload_bytes = grant_bytes(sid if sid is not None else "sid-%s-orch" % task_id.lower(),
                                task_id, repo_root, parent)
    with open(locked, "wb") as handle:
        handle.write(payload_bytes)
    pointer = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid=key)
    with open(pointer, "w") as handle:
        json.dump({"locked_path": locked, "original_path": original,
                   "event_key": key,
                   "tool_use_id": raw_of(key) if raw is None else raw}, handle)
    return {"key": key, "task_id": task_id, "original": original, "locked": locked,
            "pointer": pointer, "payload": payload_bytes}


def life(state):
    """The three observable grant-lifecycle facts: locked grant, restored grant, pointer."""
    return {"locked": os.path.exists(state["locked"]),
            "original": os.path.exists(state["original"]),
            "pointer": os.path.exists(state["pointer"])}


UNTOUCHED = {"locked": True, "original": False, "pointer": True}
CONSUMED = {"locked": False, "original": False, "pointer": False}
RESTORED = {"locked": False, "original": True, "pointer": False}


def clear_pointers():
    for path in glob.glob(PT._COMMIT_GRANT_POINTER_GLOB):
        try:
            os.unlink(path)
        except OSError:
            pass


def set_env(**values):
    """Set/clear the session-id environment. main() saves and restores both variables.

    Resolution no longer reads these at all — that is the point, and
    `resolution_ignores_the_session_environment` pins it — but they still reach
    append_commit_event's recorded session_ids[], and the pre-fix key derivation that
    `mutation_reopens_*` restores was keyed on them. Both are always cleared first so a
    scenario can never inherit the previous one's chain and pass for the wrong reason.
    """
    for key in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        os.environ.pop(key, None)
    for key, value in values.items():
        if value is not None:
            os.environ[key] = value


def scene(tmp, label):
    """Fresh repo + journal root + empty pointer namespace. Returns (base, repo, parent, head)."""
    base = os.path.join(tmp, label)
    os.makedirs(base)
    CJ.JOURNAL_ROOT = os.path.join(base, "commit-events")
    repo = make_repo(base, "repo")
    make_commit(repo, "chore: base")
    parent = git(repo, "rev-parse", "HEAD")
    head = make_commit(repo, "feat: work")
    clear_pointers()
    return base, repo, parent, head


def entries_for(repo):
    path = CJ.journal_path(repo)
    if not os.path.isfile(path):
        return []
    return [json.loads(line) for line in open(path) if line.strip()]


def age(path, seconds):
    """Backdate a file so the stale-pointer sweep sees it as abandoned."""
    stamp = os.stat(path).st_mtime - seconds
    os.utime(path, (stamp, stamp))


def payload(tool_use_id, session_id="sid-subagent"):
    """A hook payload shaped like the ones claude-code delivers to BOTH hook events."""
    return {"tool_name": "Bash", "session_id": session_id, "tool_use_id": tool_use_id}


def drive_main(full_payload):
    """Run the hook's REAL entrypoint with a full harness payload on stdin.

    This is the seam audit R2-1 said no test exercised: main() parses the payload
    JSON, classifies the terminal result from what the payload actually carries, and
    only then drives the finalizer. Session/task ids are cleared from the environment
    for the call so resolution can only come from the payload, and restored
    exception-safely. Returns main()'s exit status (the fail-open contract pins 0).
    """
    saved_stdin = sys.stdin
    saved_env = {key: os.environ.pop(key, None)
                 for key in ("CLAUDE_TASK_ID", "CLAUDE_SESSION_ID",
                             "CLAUDE_CODE_SESSION_ID")}
    sys.stdin = io.StringIO(json.dumps(full_payload))
    try:
        PT.main()
    except SystemExit as exc:
        return exc.code
    finally:
        sys.stdin = saved_stdin
        for key, value in saved_env.items():
            if value is not None:
                os.environ[key] = value
    return None


def sentinel_grant(task_id):
    """A valid structural sentinel grant authorizing `git commit`, in the redirected
    sentinel namespace. Written exactly as scripts/write-allow-grant would shape it."""
    path = os.path.join(AL.SENTINEL_GRANT_DIR, task_id + ".json")
    with open(path, "w") as handle:
        json.dump({"task_id": task_id, "session_id": task_id,
                   "allowed_operations": [{"op": "git", "target": "commit"}],
                   "created_at": time.time(), "expires_at": time.time() + 600}, handle)
    return path


def _run(tmp):
    # ======================================================== the correlating identifier.
    # tool_use_id is what the runtime puts in BOTH hook payloads for one tool call. The two
    # hooks are separate programs with no shared import, so the derivation is duplicated;
    # these pin the copies together. Drift here silently un-binds every pointer: the guard
    # would write a name the finalizer never looks up, and journalling would just stop.
    check("guard and finalizer derive the SAME event key from a payload",
          all(GUARD._event_key(case) == PT._event_key(case) for case in (
              {"tool_use_id": "toolu_01AVXSexmJfLLbjRQJR8ZGeS"},
              {"tool_use_id": ""}, {"tool_use_id": None}, {}, {"tool_use_id": 12345},
              {"tool_use_id": "../../etc/passwd"}, {"tool_use_id": "*"},
              {"tool_use_id": "///"}, "not-a-dict")))
    check("event key is derived from a real toolu_ id",
          PT._event_key(payload("toolu_01AVXSexmJfLLbjRQJR8ZGeS"))
          == "tu-toolu_01AVXSexmJfLLbjRQJR8ZGeS")
    check("distinct tool_use_ids give distinct keys (per-EVENT, not per-session)",
          PT._event_key(payload("toolu_A", "sid-same"))
          != PT._event_key(payload("toolu_B", "sid-same")))
    check("absent / empty / unusable tool_use_id yields no key at all",
          PT._event_key({}) == "" and PT._event_key({"tool_use_id": ""}) == ""
          and PT._event_key({"tool_use_id": None}) == ""
          and PT._event_key("not-a-dict") == ""
          and PT._event_key({"tool_use_id": "///"}) == "")
    # The key becomes a filename, so a payload value must not be able to leave the pointer
    # namespace or reach the reader's glob as a metacharacter.
    traversal = PT._event_key({"tool_use_id": "../../etc/passwd"})
    check("event key cannot escape the pointer namespace or carry glob metacharacters",
          "/" not in traversal and ".." not in traversal
          and PT._event_key({"tool_use_id": "*"}) == ""
          and all(char.isalnum() or char in "_-"
                  for char in PT._event_key(payload("toolu_01x"))))

    # ============================================================== the write side agrees.
    # An end-to-end pass through the REAL guard writer, so the two sides are checked against
    # each other rather than against this file's idea of what a pointer looks like.
    base, repo, parent, head = scene(tmp, "writer-roundtrip")
    event = payload("toolu_01ROUNDTRIP")
    original = os.path.join(base, "claude-commit-grant-T-RT-nonce.json")
    with open(original, "wb") as handle:
        handle.write(grant_bytes("sid-orchestrator", "T-RT", repo, parent))
    GUARD._lock_grant_for_posttool(original, GUARD._event_key(event),
                                   GUARD._raw_tool_use_id(event))
    written = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid=PT._event_key(event))
    check("guard writes the pointer at the name the finalizer will look up",
          os.path.isfile(written) and not os.path.exists(original)
          and os.path.isfile(original + ".lck"))
    check("guard records the event key INSIDE the pointer too",
          json.load(open(written)).get("event_key") == PT._event_key(event))
    check("guard records the RAW tool_use_id inside the pointer (R2-2 ownership proof)",
          json.load(open(written)).get("tool_use_id") == "toolu_01ROUNDTRIP")
    finalize(PT._event_key(event), event["session_id"], "success",
             raw=PT._raw_tool_use_id(event))
    got = entries_for(repo)
    check("guard-written pointer round-trips through the finalizer and journals",
          len(got) == 1 and got[0]["task_id"] == "T-RT"
          and got[0]["resulting_head"] == head and not os.path.exists(written))

    # When the guard cannot bind a pointer to the event, the grant is LEFT IN PLACE
    # (audit R2-3a — reverses the earlier spend-it-immediately call). Destroying it
    # pre-commit meant a failed commit could never retry and a successful one had
    # nothing to journal; leaving it is safe against reuse-after-success because the
    # expected_head binding rejects it once the authorized commit moves HEAD, and the
    # TTL bounds the file. Residuals accepted and documented in the guard: no journal
    # entry for a keyless event, auto-bulk deferral until TTL, and a pre-landing
    # double-authorization sliver against the identical repo/branch/HEAD.
    base, repo, parent, head = scene(tmp, "writer-no-key")
    original = os.path.join(base, "claude-commit-grant-T-NOKEY-nonce.json")
    nokey_payload = grant_bytes("sid-orchestrator", "T-NOKEY", repo, parent)
    with open(original, "wb") as handle:
        handle.write(nokey_payload)
    GUARD._lock_grant_for_posttool(original, GUARD._event_key({}), "")
    check("guard with no event key leaves the grant IN PLACE for the commit it just "
          "authorized (no pre-commit destruction, no lock, no orphan pointer)",
          os.path.exists(original) and not os.path.exists(original + ".lck")
          and glob.glob(PT._COMMIT_GRANT_POINTER_GLOB) == []
          and open(original, "rb").read() == nokey_payload)
    # The neutralizer the decision USED to lean on, checked by execution: once HEAD has
    # moved past expected_head, the leftover cannot match any later commit's target —
    # while the same grant bound to the LIVE head would (positive control, so this
    # check cannot pass vacuously on a broken matcher). Necessary, but audit round 3
    # (F4) showed it is NOT sufficient; the two checks after it are the disproof.
    real_repo = git(repo, "rev-parse", "--show-toplevel")
    real_branch = git(repo, "branch", "--show-current")
    stale = {"repo_root": real_repo, "branch": real_branch, "expected_head": parent}
    live_bound = {"repo_root": real_repo, "branch": real_branch, "expected_head": head}
    probe_cmd = 'git -C "%s" commit -m x' % repo
    check("left-in-place grant is INERT once HEAD moved (expected_head binding), "
          "while a live-HEAD grant still matches (positive control)",
          GUARD._grant_matches_commit_target(stale, probe_cmd) is False
          and GUARD._grant_matches_commit_target(live_bound, probe_cmd) is True)
    check("the guard REPORTS that a keyless authorization was not deferred, which is "
          "what tells the caller to record a use instead",
          GUARD._lock_grant_for_posttool(original, GUARD._event_key({}), "") is False)
    os.unlink(original)

    # ============================== F4: single-use on the undeferrable path.
    # The leave-in-place decision argued that expected_head neutralizes reuse because a
    # successful commit moves HEAD. Two operations break that, and both are exercised
    # here against real repositories rather than argued:
    #   - `git reset --soft <expected_head>`, which this guard permits, puts the whole
    #     repo/branch/HEAD tuple back and re-arms the leftover — repeatably;
    #   - a deterministic `--amend` (fixed author AND committer dates, unchanged tree,
    #     parent and message) reproduces the IDENTICAL sha, so HEAD never moves at all.
    # Spentness therefore cannot be inferred from repo state. The guard now records its
    # own validation-time witness — HEAD sha plus HEAD reflog entry COUNT — which only
    # moves forward: a commit, a reset and an amend each APPEND a reflog entry, so none
    # of them can put the witness back. Every pair below asserts the OLD signal is fooled
    # and the NEW one is not, on the same repo state, so neither half can pass vacuously.
    base, repo, parent, head = scene(tmp, "f4-soft-reset-replay")
    real_repo = git(repo, "rev-parse", "--show-toplevel")
    real_branch = git(repo, "branch", "--show-current")
    replay_cmd = 'git -C "%s" commit -m x' % repo
    # The grant is bound to the LIVE head, which is the shape a real grant has when the
    # guard validates it. Anything else would not reproduce the replay: the whole attack
    # is that HEAD leaves expected_head and is then put back.
    grant = {"repo_root": real_repo, "branch": real_branch, "expected_head": head,
             "expires_at": ""}
    grant_path = os.path.join(base, "claude-commit-grant-T-F4-nonce.json")
    with open(grant_path, "wb") as handle:
        handle.write(grant_bytes("sid-orchestrator", "T-F4", real_repo, head))
    check("a first undeferrable authorization is permitted (no record yet)",
          GUARD._grant_use_permitted(grant, grant_path) is True)
    GUARD._record_undeferrable_grant_use(grant, grant_path)
    check("recording a use writes the sidecar next to the grant, and the grant file "
          "itself is untouched",
          os.path.isfile(grant_path + ".use") and os.path.isfile(grant_path))
    make_commit(repo, "the commit this grant authorized")
    check("CONTROL: immediately after the authorized commit the old expected_head "
          "signal does refuse — which is why it looked sufficient",
          GUARD._grant_matches_commit_target(grant, replay_cmd) is False)
    git(repo, "reset", "--soft", head)
    check("`git reset --soft <expected_head>` RE-ARMS the old binding — the signal the "
          "leave-in-place decision relied on is fooled",
          git(repo, "rev-parse", "HEAD") == head
          and GUARD._grant_matches_commit_target(grant, replay_cmd) is True)
    check("but the use record REFUSES the replay (F4: append-only witness moved even "
          "though HEAD came back)",
          GUARD._grant_use_permitted(grant, grant_path) is False)

    # Same disproof for the amend, where HEAD never moves at all.
    base, repo, parent, head = scene(tmp, "f4-same-sha-amend")
    fixed = dict(os.environ)
    fixed.update({"GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
                  "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000"})
    with open(os.path.join(repo, "det.txt"), "w") as handle:
        handle.write("deterministic\n")
    git(repo, "add", "-A")
    subprocess.run(["git", "-C", repo, "commit", "-q", "-m", "det"],
                   env=fixed, check=True, capture_output=True)
    det_head = git(repo, "rev-parse", "HEAD")
    real_repo = git(repo, "rev-parse", "--show-toplevel")
    real_branch = git(repo, "branch", "--show-current")
    amend_grant = {"repo_root": real_repo, "branch": real_branch,
                   "expected_head": det_head, "expires_at": ""}
    amend_path = os.path.join(base, "claude-commit-grant-T-AMEND-nonce.json")
    with open(amend_path, "wb") as handle:
        handle.write(grant_bytes("sid-orchestrator", "T-AMEND", real_repo, det_head))
    GUARD._record_undeferrable_grant_use(amend_grant, amend_path)
    subprocess.run(["git", "-C", repo, "commit", "-q", "--amend", "--no-edit"],
                   env=fixed, check=True, capture_output=True)
    amend_cmd = 'git -C "%s" commit -m x' % repo
    check("a deterministic amend reproduces the SAME sha, so HEAD never moves and the "
          "expected_head binding still matches after a commit object was created",
          git(repo, "rev-parse", "HEAD") == det_head
          and GUARD._grant_matches_commit_target(amend_grant, amend_cmd) is True)
    check("the use record refuses the amended-away grant anyway (F4)",
          GUARD._grant_use_permitted(amend_grant, amend_path) is False)

    # RETRY MUST SURVIVE. Leaving the grant in place existed so a FAILED commit could try
    # again; a fix that killed that would trade one defect for another. A failed commit
    # creates no reflog entry, so the witness is unchanged and the grant still authorizes.
    base, repo, parent, head = scene(tmp, "f4-retry-after-failure")
    real_repo = git(repo, "rev-parse", "--show-toplevel")
    real_branch = git(repo, "branch", "--show-current")
    retry_grant = {"repo_root": real_repo, "branch": real_branch,
                   "expected_head": head, "expires_at": ""}
    retry_path = os.path.join(base, "claude-commit-grant-T-RETRY-nonce.json")
    with open(retry_path, "wb") as handle:
        handle.write(grant_bytes("sid-orchestrator", "T-RETRY", real_repo, head))
    GUARD._record_undeferrable_grant_use(retry_grant, retry_path)
    with open(os.path.join(repo, "staged.txt"), "w") as handle:
        handle.write("work\n")
    git(repo, "add", "-A")
    failed = subprocess.run(["git", "-C", repo, "commit", "-m", "x",
                             "--author", "malformed"], capture_output=True, text=True)
    check("a FAILED commit plus staging churn leaves the witness unchanged, so retry is "
          "still authorized (the property leave-in-place was chosen to protect)",
          failed.returncode != 0
          and GUARD._grant_use_permitted(retry_grant, retry_path) is True)
    first_witness = json.load(open(retry_path + ".use"))["witness"]
    GUARD._record_undeferrable_grant_use(retry_grant, retry_path)
    check("a retry increments the use counter without disturbing the witness",
          json.load(open(retry_path + ".use"))["uses"] == 2
          and json.load(open(retry_path + ".use"))["witness"] == first_witness)
    make_commit(repo, "the authorized commit finally lands")
    check("once a commit actually lands, the same record refuses the next use",
          GUARD._grant_use_permitted(retry_grant, retry_path) is False)
    # The witness must be captured ONCE. If a later recording refreshed it to the
    # post-commit state, a grant whose commit had already landed would be re-armed —
    # so this asserts against the witness the FIRST use captured, now that the repo has
    # genuinely moved past it.
    GUARD._record_undeferrable_grant_use(retry_grant, retry_path)
    check("a recording made AFTER the commit landed does not refresh the witness, so a "
          "spent grant cannot be re-armed by simply asking again",
          json.load(open(retry_path + ".use"))["witness"] == first_witness
          and GUARD._repo_use_witness(real_repo) != first_witness
          and GUARD._grant_use_permitted(retry_grant, retry_path) is False)

    # Bounded, and fail-closed when the repo cannot answer.
    base, repo, parent, head = scene(tmp, "f4-bounds")
    real_repo = git(repo, "rev-parse", "--show-toplevel")
    bounds_grant = {"repo_root": real_repo, "branch": git(repo, "branch", "--show-current"),
                    "expected_head": head, "expires_at": ""}
    bounds_path = os.path.join(base, "claude-commit-grant-T-BOUNDS-nonce.json")
    with open(bounds_path, "wb") as handle:
        handle.write(grant_bytes("sid-orchestrator", "T-BOUNDS", real_repo, head))
    permitted = []
    for _ in range(GUARD._MAX_GRANT_USE_ATTEMPTS + 1):
        permitted.append(GUARD._grant_use_permitted(bounds_grant, bounds_path))
        GUARD._record_undeferrable_grant_use(bounds_grant, bounds_path)
    check("repeat authorizations against an unchanged witness are bounded, not endless "
          "(the residual concurrency window is finite)",
          permitted[:GUARD._MAX_GRANT_USE_ATTEMPTS] == [True] * GUARD._MAX_GRANT_USE_ATTEMPTS
          and permitted[-1] is False)
    check("an unreadable witness fails CLOSED rather than being treated as unchanged",
          GUARD._repo_use_witness(os.path.join(base, "not-a-repo")) == ""
          and GUARD._grant_use_permitted({"repo_root": os.path.join(base, "not-a-repo")},
                                         bounds_path) is False)
    # A corrupt counter must not read as "plenty of uses left".
    with open(bounds_path + ".use", "w") as handle:
        json.dump({"witness": GUARD._repo_use_witness(real_repo), "uses": "many"}, handle)
    check("a corrupt use counter fails CLOSED",
          GUARD._grant_use_permitted(bounds_grant, bounds_path) is False)

    # The record has to be INVISIBLE to every reader that already scans this namespace,
    # or it becomes a grant candidate, an in-flight signal, or sweep bait.
    sample = "/tmp/claude-commit-grant-sid-nonce.json"
    record_name = GUARD._use_record_path(sample)
    check("the use record's name matches none of the existing grant / pointer / sweep "
          "globs (it must be inert to every current reader)",
          record_name == sample + ".use"
          and not fnmatch.fnmatch(record_name, "/tmp/claude-commit-grant-*-*.json")
          and not fnmatch.fnmatch(record_name, "/tmp/claude-commit-grant-*.json")
          and not fnmatch.fnmatch(record_name, "/tmp/claude-commit-grant-*.lck")
          and not fnmatch.fnmatch(record_name, STOP_CLEANUP_POINTER_GLOB)
          and not fnmatch.fnmatch(record_name, STOP_CLEANUP_LOCKED_GLOB))
    # Rename-aside failure is the same trade (R2-3a): the grant is still at its
    # original name and must survive there, not be destroyed pre-commit. The .lck
    # name is occupied by a directory, which rename(2) refuses even under root.
    base, repo, parent, head = scene(tmp, "writer-rename-fails")
    original = os.path.join(base, "claude-commit-grant-T-RENFAIL-nonce.json")
    renfail_payload = grant_bytes("sid-orchestrator", "T-RENFAIL", repo, parent)
    with open(original, "wb") as handle:
        handle.write(renfail_payload)
    os.makedirs(original + ".lck")
    GUARD._lock_grant_for_posttool(original, "tu-toolu_01RENFAIL", "toolu_01RENFAIL")
    check("rename-aside failure leaves the grant in place and writes no pointer",
          os.path.exists(original) and open(original, "rb").read() == renfail_payload
          and glob.glob(PT._COMMIT_GRANT_POINTER_GLOB) == [])
    os.rmdir(original + ".lck")
    os.unlink(original)

    # And it refuses to clobber a name already taken: a writer may not overwrite another
    # event's — or another session's — token. The refusal must also not STRAND the late
    # grant (audit R2-3b): pre-fix, the just-renamed .lck was left referenced by nothing,
    # which nothing but the stale sweep would ever touch. Now the rename is undone.
    base, repo, parent, head = scene(tmp, "writer-no-clobber")
    squatter = mint(base, "tu-toolu_01SQUAT", "T-SQUAT", repo, parent)
    before_squatter = open(squatter["pointer"]).read()
    original = os.path.join(base, "claude-commit-grant-T-LATE-nonce.json")
    late_payload = grant_bytes("sid-orchestrator", "T-LATE", repo, parent)
    with open(original, "wb") as handle:
        handle.write(late_payload)
    GUARD._lock_grant_for_posttool(original, "tu-toolu_01SQUAT", "toolu_01LATE")
    check("guard never overwrites a pointer name that is already taken",
          open(squatter["pointer"]).read() == before_squatter
          and life(squatter) == UNTOUCHED)
    check("O_EXCL refusal RESTORES the late grant byte-identical instead of "
          "stranding it as an unreferenced .lck (R2-3b)",
          os.path.exists(original) and not os.path.exists(original + ".lck")
          and open(original, "rb").read() == late_payload)
    os.unlink(original)

    # The other R2-3b half: the pointer write fails AFTER both the rename and the
    # O_EXCL open succeeded (ENOSPC / serialization error while dumping). The partial
    # pointer must be removed and the grant restored — a corrupt pointer plus a .lck
    # is a strand the finalizer's corrupt-path would reap WITHOUT restoring.
    base, repo, parent, head = scene(tmp, "writer-dump-fails")
    original = os.path.join(base, "claude-commit-grant-T-DUMPFAIL-nonce.json")
    dump_payload = grant_bytes("sid-orchestrator", "T-DUMPFAIL", repo, parent)
    with open(original, "wb") as handle:
        handle.write(dump_payload)

    class _NoSpaceJson:
        @staticmethod
        def dump(*args, **kwargs):
            raise OSError(28, "No space left on device")

    saved_guard_json = GUARD.json
    GUARD.json = _NoSpaceJson  # patched on the GUARD module namespace only
    try:
        GUARD._lock_grant_for_posttool(original, "tu-toolu_01DUMPFAIL",
                                       "toolu_01DUMPFAIL")
    finally:
        GUARD.json = saved_guard_json
    check("pointer-content write failure removes the partial pointer and RESTORES "
          "the grant byte-identical (R2-3b: nothing stranded)",
          os.path.exists(original) and not os.path.exists(original + ".lck")
          and open(original, "rb").read() == dump_payload
          and glob.glob(PT._COMMIT_GRANT_POINTER_GLOB) == [])
    os.unlink(original)

    # F12: and when the RESTORE ITSELF fails. Every failure forced above ends with a
    # rename that succeeds, so all of them stay green against a _restore_locked_grant
    # that reacts to a failed rename by deleting the .lck — and that mutant destroys
    # the authorization the grant still owes a retry, silently. The documented
    # last-resort contract is the opposite: the .lck SURVIVES, and the sweeps (the Stop
    # hook's direct .lck glob, then the >7d /tmp cron) are what reap it. Forced by
    # occupying the destination name with a DIRECTORY, which rename(2) refuses even
    # under root — created from inside the failing write so it appears only after the
    # rename-aside has already happened.
    base, repo, parent, head = scene(tmp, "writer-restore-fails")
    original = os.path.join(base, "claude-commit-grant-T-RESTFAIL-nonce.json")
    restfail_payload = grant_bytes("sid-orchestrator", "T-RESTFAIL", repo, parent)
    with open(original, "wb") as handle:
        handle.write(restfail_payload)

    class _BlockTheRestore:
        @staticmethod
        def dump(*args, **kwargs):
            os.makedirs(original)          # destination now un-renameable-onto
            raise OSError(28, "No space left on device")

    saved_guard_json = GUARD.json
    GUARD.json = _BlockTheRestore
    try:
        deferred = GUARD._lock_grant_for_posttool(original, "tu-toolu_01RESTFAIL",
                                                  "toolu_01RESTFAIL")
    finally:
        GUARD.json = saved_guard_json
    check("restore-rename failure keeps the locked grant ON DISK instead of deleting "
          "it (F12: the .lck is the last-resort record, reaped only by the sweeps)",
          os.path.isdir(original)                       # the restore truly could not run
          and os.path.isfile(original + ".lck")         # <- the discriminating assertion
          and open(original + ".lck", "rb").read() == restfail_payload
          and glob.glob(PT._COMMIT_GRANT_POINTER_GLOB) == []
          and deferred is False)
    check("a stranded .lck still matches the Stop sweep's locked glob, so the residual "
          "the contract accepts is actually reachable by a reaper",
          fnmatch.fnmatch("/tmp/claude-commit-grant-sid-nonce.json.lck",
                          STOP_CLEANUP_LOCKED_GLOB))
    # Teardown must not depend on the checks above having passed: under the very mutant
    # this scenario exists to kill, the .lck is gone, and an unguarded unlink here would
    # abort the module instead of letting the remaining checks report.
    for cleanup in (lambda: os.unlink(original + ".lck"), lambda: os.rmdir(original)):
        try:
            cleanup()
        except OSError:
            pass

    # ================================================================== the ordinary flow.
    # POSITIVE CONTROL, and the regression this binding could most easily cause. Every
    # session id in play is DIFFERENT — payload (subagent), environment (orchestrator), and
    # the grant's own --sid — which is the production shape the guard records in
    # _find_grant_any. Journalling must survive it; if it does not, reconciliation stops
    # silently and nobody notices.
    base, repo, parent, head = scene(tmp, "ordinary-success")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    owner = mint(base, "tu-toolu_01ORDINARY", "T-OWNER", repo, parent, sid="sid-grant-cli")
    finalize("tu-toolu_01ORDINARY", "sid-subagent", "success")
    got = entries_for(repo)
    check("ordinary_flow_journals_across_three_divergent_session_ids",
          len(got) == 1 and got[0]["task_id"] == "T-OWNER"
          and got[0]["resulting_head"] == head)
    check("ordinary flow entry is attributable (real parent linkage verified)",
          CJ.find_attributable_event(repo, head, "T-OWNER", "sid-subagent") is not None)
    check("ordinary success consumes the locked grant and removes the pointer",
          life(owner) == CONSUMED)

    # Resolution must no longer read the session environment AT ALL. Same event, env cleared
    # and then pointed at an unrelated session: identical outcome both times.
    for label, env in (("env-absent", None), ("env-foreign", "sid-someone-else")):
        base, repo, parent, head = scene(tmp, "ordinary-" + label)
        set_env(CLAUDE_SESSION_ID=env)
        owner = mint(base, "tu-toolu_01ENV", "T-OWNER", repo, parent, sid="sid-grant-cli")
        finalize("tu-toolu_01ENV", "sid-subagent", "success")
        got = entries_for(repo)
        check("resolution_ignores_the_session_environment (%s)" % label,
              len(got) == 1 and got[0]["task_id"] == "T-OWNER" and life(owner) == CONSUMED)

    base, repo, parent, head = scene(tmp, "ordinary-failure")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    owner = mint(base, "tu-toolu_01FAIL", "T-OWNER", repo, parent, sid="sid-grant-cli")
    finalize("tu-toolu_01FAIL", "sid-subagent", "failure")
    check("ordinary failure writes no entry", entries_for(repo) == [])
    check("ordinary failure RESTORES the grant for retry and removes the pointer",
          life(owner) == RESTORED)
    check("restored grant is BYTE-IDENTICAL to the grant the guard locked",
          open(owner["original"], "rb").read() == owner["payload"])

    # Consumption is exact in the same sense: the entry carries the locked grant's own
    # fields, so the finalizer demonstrably read THAT grant and not some other live one.
    base, repo, parent, head = scene(tmp, "ordinary-consume-exact")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    owner = mint(base, "tu-toolu_01EXACT", "T-OWNER", repo, parent, sid="sid-grant-cli")
    expected = json.loads(owner["payload"].decode())
    finalize("tu-toolu_01EXACT", "sid-subagent", "success")
    got = entries_for(repo)
    check("consumed grant's OWN fields are what got journaled",
          len(got) == 1 and got[0]["task_id"] == expected["task_id"]
          and got[0]["branch"] == expected["branch"]
          and got[0]["parent_head"] == expected["expected_head"]
          and expected["sid"] in got[0]["session_ids"])
    check("consumption removes the locked grant without resurrecting the original",
          life(owner) == CONSUMED)

    # ================= THE RESIDUAL THIS LANE CLOSES: an event with NO POINTER OF ITS OWN.
    # Models an auto-bulk commit: _evaluate_commit accepts it on a multi-use sentinel and
    # returns BEFORE _lock_grant_for_posttool, so no grant and no pointer are ever minted for
    # it. (An event whose pointer write failed silently reaches the identical state.) A
    # concurrent ORDINARY grant is live and — this is the whole point — was minted under the
    # same environment session id this bulk event runs under, so the pre-fix targeted lookup
    # resolved it BY NAME and the wildcard containment never fired.
    #
    # It is also the SPENDABLE variant: the foreign grant is bound to this repo and to this
    # commit's REAL parent, so a record naming it passes _parent_linkage_verified and
    # reconciles into a push-gate token for an unrelated commit. The harm is not a junk line.
    base, repo, parent, head = scene(tmp, "no-pointer-success")
    set_env(CLAUDE_SESSION_ID="sid-shared-orch")
    foreign = mint(base, "sid-shared-orch", "T-FOREIGN", repo, parent, sid="sid-shared-orch")
    before_foreign = life(foreign)
    finalize(PT._event_key(payload("toolu_01BULK")), "sid-bulk-subagent", "success",
             raw="toolu_01BULK")
    check("no_pointer_event_writes_no_journal_entry "
          "(commit_journal's bulk-commit claim holds)", entries_for(repo) == [])
    check("no_pointer_event_yields_no_spendable_attribution",
          CJ.find_attributable_event(repo, head, "T-FOREIGN", "sid-bulk-subagent") is None
          and CJ.find_attributable_event(repo, head, "T-FOREIGN", "sid-shared-orch") is None)
    # THE REQUIREMENT: it must act on NOTHING. Not "journal nothing" — touch nothing.
    check("no_pointer_event_does_not_consume_another_events_grant",
          before_foreign == UNTOUCHED and life(foreign) == UNTOUCHED)

    base, repo, parent, head = scene(tmp, "no-pointer-failure")
    set_env(CLAUDE_SESSION_ID="sid-shared-orch")
    foreign = mint(base, "sid-shared-orch", "T-FOREIGN", repo, parent, sid="sid-shared-orch")
    finalize(PT._event_key(payload("toolu_01BULK2")), "sid-bulk-subagent", "failure",
             raw="toolu_01BULK2")
    check("no_pointer_event_does_not_restore_another_events_grant",
          entries_for(repo) == [] and life(foreign) == UNTOUCHED)

    # Degenerate shape of the same thing: the event has no usable key at all, so there is no
    # name to look up. Several pointers are live and every one must be left alone.
    base, repo, parent, head = scene(tmp, "no-key-event")
    set_env(CLAUDE_SESSION_ID="sid-shared-orch")
    peers = [mint(base, "tu-toolu_01P%d" % i, "T-PEER-%d" % i, repo, parent)
             for i in range(2)]
    finalize(PT._event_key({}), "sid-bulk-subagent", "success", raw="")
    check("keyless event journals nothing and touches no live pointer",
          entries_for(repo) == [] and all(life(p) == UNTOUCHED for p in peers))

    # The name is necessary but not sufficient: the pointer must also CLAIM this event, so a
    # file merely occupying the expected filename is left strictly alone.
    base, repo, parent, head = scene(tmp, "name-without-claim")
    squatter = mint(base, "tu-toolu_01CLAIM", "T-SQUAT", repo, parent)
    with open(squatter["pointer"], "w") as handle:
        json.dump({"locked_path": squatter["locked"], "original_path": squatter["original"],
                   "event_key": "tu-toolu_01SOMEONE_ELSE",
                   "tool_use_id": "toolu_01SOMEONE_ELSE"}, handle)
    finalize("tu-toolu_01CLAIM", "sid-subagent", "success")
    check("pointer whose recorded event key disagrees with its name is refused and untouched",
          entries_for(repo) == [] and life(squatter) == UNTOUCHED)

    # ========================================= R2-2: the derived key is not injective.
    # The safe-alphabet fold and the 96-char cap can map two DISTINCT raw tool_use_ids
    # onto one derived name. The pointer content check therefore compares RAW ids: the
    # pre-fix predicate compared derived values, which accepts the colliding second
    # event and recreates the exact mixed-record / wrong-grant defect the event binding
    # was added to close. Preconditions prove the collisions are real; the pre-fix-
    # predicate check proves the old comparison would have let event B in.
    raw_a, raw_b = "toolu_01X.COLLIDE", "toolu_01X-COLLIDE"
    shared_key = PT._event_key({"tool_use_id": raw_a})
    check("r22 distinct raw ids genuinely collide on the derived key (precondition)",
          raw_a != raw_b and shared_key == PT._event_key({"tool_use_id": raw_b}))
    base, repo, parent, head = scene(tmp, "r22-sanitize-collision")
    set_env(CLAUDE_SESSION_ID="sid-shared-orch")
    victim = mint(base, shared_key, "T-VICTIM", repo, parent, raw=raw_a)
    check("r22 the PRE-FIX predicate (derived == recorded derived) accepts the forger",
          json.load(open(victim["pointer"]))["event_key"]
          == PT._event_key({"tool_use_id": raw_b}))
    finalize(shared_key, "sid-event-b", "success", raw=raw_b)
    check("r22_colliding_id_cannot_cross_finalize (no journal, victim untouched)",
          entries_for(repo) == [] and life(victim) == UNTOUCHED)
    finalize(shared_key, "sid-event-b", "failure", raw=raw_b)
    check("r22_colliding_id_cannot_restore_anothers_grant_either",
          life(victim) == UNTOUCHED)
    finalize(shared_key, "sid-event-a", "success", raw=raw_a)
    got = entries_for(repo)
    check("r22_true_owner_still_finalizes_after_the_forgers_refusals",
          len(got) == 1 and got[0]["task_id"] == "T-VICTIM"
          and life(victim) == CONSUMED)

    # Ids differing only BEYOND the length cap are the other collision family.
    long_a = "toolu_01" + "A" * 96 + "TAIL1"
    long_b = "toolu_01" + "A" * 96 + "TAIL2"
    cap_key = PT._event_key({"tool_use_id": long_a})
    check("r22 ids differing only beyond the cap collide on the derived key (precondition)",
          long_a != long_b and cap_key == PT._event_key({"tool_use_id": long_b}))
    base, repo, parent, head = scene(tmp, "r22-cap-collision")
    victim = mint(base, cap_key, "T-CAP", repo, parent, raw=long_a)
    finalize(cap_key, "sid-cap-b", "success", raw=long_b)
    check("r22_beyond_cap_id_cannot_cross_finalize",
          entries_for(repo) == [] and life(victim) == UNTOUCHED)

    # Write side of the same collision: the second event's O_EXCL refusal must not
    # clobber the first event's pointer NOR strand the second grant (R2-3b restore).
    base, repo, parent, head = scene(tmp, "r22-write-collision")
    first = mint(base, shared_key, "T-FIRST", repo, parent, raw=raw_a)
    original = os.path.join(base, "claude-commit-grant-T-SECOND-nonce.json")
    second_payload = grant_bytes("sid-orch", "T-SECOND", repo, parent)
    with open(original, "wb") as handle:
        handle.write(second_payload)
    GUARD._lock_grant_for_posttool(original, shared_key, raw_b)
    check("r22_write_side_collision_restores_the_second_grant_and_keeps_the_firsts_pointer",
          os.path.exists(original) and not os.path.exists(original + ".lck")
          and open(original, "rb").read() == second_payload
          and json.load(open(first["pointer"]))["tool_use_id"] == raw_a
          and life(first) == UNTOUCHED)

    # Concurrency: the owner's pointer resolves while peers are live, and only the owner's
    # grant moves. The first containment refused this case outright, which was a false
    # negative that stopped legitimate commits being journaled.
    base, repo, parent, head = scene(tmp, "owner-among-peers")
    set_env(CLAUDE_SESSION_ID="sid-shared-orch")
    owner = mint(base, "tu-toolu_01MINE", "T-OWNER", repo, parent, sid="sid-grant-cli")
    peers = [mint(base, "tu-toolu_01PEER%d" % i, "T-PEER-%d" % i, repo, parent)
             for i in range(2)]
    finalize("tu-toolu_01MINE", "sid-subagent", "success")
    got = entries_for(repo)
    check("owner resolves its own pointer with peers live, and journals only itself",
          len(got) == 1 and got[0]["task_id"] == "T-OWNER")
    check("peers' grants and pointers are untouched by the owner's finalization",
          life(owner) == CONSUMED and all(life(p) == UNTOUCHED for p in peers))

    # ================================================================== stranding analysis.
    # The wildcard scan used to clear abandoned pointers as a side effect of the next
    # unrelated commit. Event binding removes that accident, so the reap must be deliberate.
    base, repo, parent, head = scene(tmp, "stranding")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    abandoned = mint(base, "tu-toolu_01ABANDONED", "T-GONE", repo, parent)
    fresh_peer = mint(base, "tu-toolu_01FRESH", "T-FRESH", repo, parent)
    owner = mint(base, "tu-toolu_01LIVE", "T-OWNER", repo, parent, sid="sid-grant-cli")
    # Production shape: the grant predates its pointer (write-commit-grant mints the
    # file before PreToolUse renames it aside, and rename preserves mtime), so a stale
    # pointer's grant is always at least as old as the pointer. R2-5 makes the reap
    # verify the TARGET's own age, so the fixture ages both; a FRESH .lck named by a
    # stale pointer is the forgery case pinned in the r25_* checks below.
    age(abandoned["pointer"], PT._POINTER_STALE_SECONDS + 60)
    age(abandoned["locked"], PT._POINTER_STALE_SECONDS + 90)
    finalize("tu-toolu_01LIVE", "sid-subagent", "success")
    check("stranding_abandoned_pointer_and_its_locked_grant_are_deliberately_reaped",
          life(abandoned) == {"locked": False, "original": False, "pointer": False})
    check("stranding sweep leaves a concurrent event's FRESH pointer alone",
          life(fresh_peer) == UNTOUCHED)
    check("stranding sweep does not disturb this event's own finalization",
          life(owner) == CONSUMED and len(entries_for(repo)) == 1)

    # The caller's own pointer is excluded by name, so even a slow event cannot sweep itself.
    base, repo, parent, head = scene(tmp, "stranding-self")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    owner = mint(base, "tu-toolu_01SLOW", "T-OWNER", repo, parent, sid="sid-grant-cli")
    age(owner["pointer"], PT._POINTER_STALE_SECONDS + 600)
    finalize("tu-toolu_01SLOW", "sid-subagent", "success")
    check("stranding_sweep_never_reaps_the_callers_own_pointer",
          len(entries_for(repo)) == 1 and life(owner) == CONSUMED)

    # The sweep reads a path out of a file it does not own, so it only ever unlinks something
    # shaped like a locked grant.
    base, repo, parent, head = scene(tmp, "stranding-arbitrary-path")
    bystander = os.path.join(base, "not-a-grant.txt")
    with open(bystander, "w") as handle:
        handle.write("keep me")
    rogue = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01ROGUE")
    with open(rogue, "w") as handle:
        json.dump({"locked_path": bystander, "original_path": bystander,
                   "event_key": "tu-toolu_01ROGUE"}, handle)
    age(rogue, PT._POINTER_STALE_SECONDS + 60)
    finalize("tu-toolu_01NOTHING", "sid-subagent", "success")
    check("stranding sweep reaps the stale pointer but will not unlink a non-grant path",
          not os.path.exists(rogue) and os.path.exists(bystander))

    # ========================================= R2-5: the reap must not trust what it reaps.
    # The pointer lives in world-writable /tmp and is UNTRUSTED input. A forged (or
    # corrupted) STALE pointer that records ANOTHER event's FRESH locked grant as its
    # locked_path used to get that grant deleted — the .json.lck suffix was the only
    # check — destroying a live commit's coordination state through the cleanup path.
    # The reap now proves ownership against the TARGET itself: grant-shaped basename
    # AND the file's own lstat age past the stale bound (grants predate their pointers,
    # so every legitimately stale pair passes; a fresh grant cannot).
    base, repo, parent, head = scene(tmp, "r25-forged-fresh-target")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    victim = mint(base, "tu-toolu_01R25VIC", "T-R25VIC", repo, parent, sid="sid-grant-cli")
    forged = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01R25FORGER")
    with open(forged, "w") as handle:
        json.dump({"locked_path": victim["locked"], "original_path": victim["original"],
                   "event_key": "tu-toolu_01R25FORGER",
                   "tool_use_id": "toolu_01R25FORGER"}, handle)
    age(forged, PT._POINTER_STALE_SECONDS + 60)
    finalize("tu-toolu_01R25RUNNER", "sid-x", "success")
    check("r25_forged_stale_pointer_cannot_delete_a_FRESH_locked_grant",
          not os.path.exists(forged) and entries_for(repo) == []
          and life(victim) == UNTOUCHED)
    finalize("tu-toolu_01R25VIC", "sid-subagent", "success")
    got = entries_for(repo)
    check("r25_victims_own_event_still_finalizes_after_the_forgery",
          len(got) == 1 and got[0]["task_id"] == "T-R25VIC"
          and life(victim) == CONSUMED)

    # The suffix alone is not license either: an OVER-AGE bystander that merely ends
    # in .json.lck but is not grant-shaped must survive. This is exactly the dangerous
    # shape the pre-R2-5 bystander check missed — its bystander lacked the suffix, so
    # the suffix-only predicate was never exercised against a passing non-grant path.
    base, repo, parent, head = scene(tmp, "r25-suffix-bystander")
    suffixed = os.path.join(base, "precious-data.json.lck")
    with open(suffixed, "w") as handle:
        handle.write("keep me")
    age(suffixed, PT._POINTER_STALE_SECONDS + 600)
    rogue = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01R25ROGUE")
    with open(rogue, "w") as handle:
        json.dump({"locked_path": suffixed, "original_path": suffixed[:-4],
                   "event_key": "tu-toolu_01R25ROGUE",
                   "tool_use_id": "toolu_01R25ROGUE"}, handle)
    age(rogue, PT._POINTER_STALE_SECONDS + 60)
    finalize("tu-toolu_01R25RUNNER2", "sid-x", "success")
    check("r25_over_age_non_grant_file_with_lck_suffix_survives_the_reap",
          not os.path.exists(rogue) and os.path.exists(suffixed))

    # The outer reaper: hooks/stop-cleanup-allowlist.sh globs the whole namespace at session
    # end. Event-keyed names must keep matching it, or anything the mid-session sweep has not
    # yet aged out would survive to the >7d cron sweep instead.
    sample = mint(base, PT._event_key(payload("toolu_01STOPCLEAN")), "T-STOP", repo, parent)
    real_pointer = GUARD._COMMIT_GRANT_ACTIVE_TEMPLATE.format(
        sid=PT._event_key(payload("toolu_01STOPCLEAN")))
    check("stranding_session_end_reaper_still_matches_event_keyed_names",
          fnmatch.fnmatch(os.path.basename(real_pointer),
                          os.path.basename(STOP_CLEANUP_POINTER_GLOB))
          and fnmatch.fnmatch(os.path.basename(sample["locked"]),
                              os.path.basename(STOP_CLEANUP_LOCKED_GLOB)))

    # ==================== R2-6: the session-end sweep is ownership-bound, BY EXECUTION.
    # Stop fires when ONE agent finishes responding — not when the machine's last
    # session ends (the shipped binary's Stop payload is the common hook input
    # {session_id, transcript_path, cwd} plus {hook_event_name:"Stop",
    # stop_hook_active, last_assistant_message?}) — so the old unscoped sweep deleted
    # a CONCURRENT session's live pointer and locked grant mid-commit. Identity
    # available at Stop time: the payload's session_id; a .lck grant payload records
    # its minting session's `sid`; a pointer records only paths + tool_use_id, so it
    # is owned exactly when the locked grant it records is owned. The sweep may
    # remove OWN-session or OVER-AGE artifacts only; undecidable is left alone.
    # This drives the REAL script through its CLAUDE_COMMIT_GRANT_SWEEP_DIR test
    # seam so live /tmp pointers are never touched. The script's other reaps run
    # against flag names keyed by this scenario's unique sid (no-ops) or reap only
    # expired/malformed sentinels — the same production behavior every real agent
    # Stop already performs; HOME is redirected so the consent log stays in tmp.
    stop_script = HOOKS_DIR / "stop-cleanup-allowlist.sh"
    sweep_dir = os.path.join(tmp, "r26-sweep")
    fake_home = os.path.join(tmp, "r26-home")
    os.makedirs(sweep_dir)
    os.makedirs(fake_home)
    own_sid = "sid-r26-own-%d" % os.getpid()

    def plant(name, content, backdate=0):
        path = os.path.join(sweep_dir, name)
        with open(path, "w") as handle:
            if isinstance(content, dict):
                json.dump(content, handle)
            else:
                handle.write(content)
        if backdate:
            age(path, backdate)
        return path

    def pointer_for(locked, tag):
        return {"locked_path": locked, "original_path": locked[:-4],
                "event_key": "tu-toolu_01" + tag, "tool_use_id": "toolu_01" + tag}

    stale_bound = 1800  # the script's own bound; mirrors PT._POINTER_STALE_SECONDS
    own_lck = plant("claude-commit-grant-%s-aa11.json.lck" % own_sid,
                    {"sid": own_sid, "task_id": "T-R26-OWN"})
    own_ptr = plant("claude-commit-grant-active-tu-toolu_01R26OWN.json",
                    pointer_for(own_lck, "R26OWN"))
    foreign_lck = plant("claude-commit-grant-sid-r26-foreign-bb22.json.lck",
                        {"sid": "sid-r26-foreign", "task_id": "T-R26-FOREIGN"})
    foreign_ptr = plant("claude-commit-grant-active-tu-toolu_01R26FOR.json",
                        pointer_for(foreign_lck, "R26FOR"))
    crashed_lck = plant("claude-commit-grant-sid-r26-crashed-cc33.json.lck",
                        {"sid": "sid-r26-crashed"}, backdate=stale_bound + 120)
    crashed_ptr = plant("claude-commit-grant-active-tu-toolu_01R26CRASH.json",
                        pointer_for(crashed_lck, "R26CRASH"), backdate=stale_bound + 120)
    undecidable = plant("claude-commit-grant-sid-r26-mystery-dd44.json.lck",
                        "{ not json")
    sweep_env = dict(os.environ, CLAUDE_COMMIT_GRANT_SWEEP_DIR=sweep_dir,
                     HOME=fake_home)
    for key in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        sweep_env.pop(key, None)
    try:
        proc = subprocess.run(
            ["bash", str(stop_script)],
            input=json.dumps({"session_id": own_sid, "hook_event_name": "Stop",
                              "stop_hook_active": False,
                              "transcript_path": os.path.join(tmp, "t.jsonl"),
                              "cwd": tmp}),
            text=True, capture_output=True, env=sweep_env, timeout=60)
        rc = proc.returncode
    except Exception:
        rc = "raised"
    check("r26_sweep_exits_0 (cleanup never blocks agent stop)", rc == 0)
    check("r26_sweep_removes_this_sessions_own_pointer_and_locked_grant",
          not os.path.exists(own_ptr) and not os.path.exists(own_lck))
    check("r26_sweep_leaves_a_concurrent_sessions_LIVE_pointer_and_grant_alone",
          os.path.exists(foreign_ptr) and os.path.exists(foreign_lck))
    check("r26_sweep_still_reaps_over_age_artifacts (crashed session, any owner)",
          not os.path.exists(crashed_ptr) and not os.path.exists(crashed_lck))
    check("r26_sweep_leaves_an_undecidable_fresh_grant_alone (fail-open = keep)",
          os.path.exists(undecidable))

    # ================================= R2-4: revocation of event-keyed pointers.
    # scripts/write-commit-grant.py's revoke path used to unlink a SESSION-named
    # pointer, which can never match an event-keyed name: revoking a locked grant
    # left its pointer behind, and a later flow on the same tool event then hit the
    # pointer's O_EXCL no-clobber. Revocation now discovers pointers by the grant
    # paths RECORDED in them (it never sees a tool_use_id, so it cannot reconstruct
    # names). WCG's namespace glob is redirected alongside the hook templates in
    # main(); the same-template identity is pinned there.
    base, repo, parent, head = scene(tmp, "r24-revoke")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    gdir = os.path.join(base, "grants")
    os.makedirs(gdir)
    original = os.path.join(gdir, "claude-commit-grant-R24-nonce.json")
    with open(original, "wb") as handle:
        handle.write(grant_bytes("sid-r24", "T-R24", repo, parent))
    event = payload("toolu_01R24EVENT")
    GUARD._lock_grant_for_posttool(original, GUARD._event_key(event),
                                   GUARD._raw_tool_use_id(event))
    ptr = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid=GUARD._event_key(event))
    check("r24 setup: grant locked and event-keyed pointer live (precondition)",
          os.path.exists(original + ".lck") and os.path.isfile(ptr))
    WCG._revoke_grants_for_task(gdir, "T-R24", "sid-r24")
    check("r24_revoke_removes_the_locked_grant_AND_its_event_keyed_pointer",
          not os.path.exists(original + ".lck") and not os.path.exists(ptr)
          and glob.glob(PT._COMMIT_GRANT_POINTER_GLOB) == [])
    # Replay on the same tool event: the fresh grant defers cleanly — pointer
    # re-written and referencing it — instead of striking a stale name's O_EXCL.
    fresh = os.path.join(gdir, "claude-commit-grant-R24-nonce2.json")
    with open(fresh, "wb") as handle:
        handle.write(grant_bytes("sid-r24", "T-R24", repo, parent))
    GUARD._lock_grant_for_posttool(fresh, GUARD._event_key(event),
                                   GUARD._raw_tool_use_id(event))
    replay_ptr = json.load(open(ptr)) if os.path.isfile(ptr) else {}
    check("r24_same_event_replay_is_not_stranded "
          "(pointer re-written and references the fresh grant)",
          os.path.exists(fresh + ".lck") and not os.path.exists(fresh)
          and replay_ptr.get("locked_path") == fresh + ".lck"
          and replay_ptr.get("tool_use_id") == "toolu_01R24EVENT")
    finalize(GUARD._event_key(event), "sid-subagent", "success", raw="toolu_01R24EVENT")
    got = entries_for(repo)
    check("r24_replayed_event_finalizes_normally_after_revocation",
          len(got) == 1 and got[0]["task_id"] == "T-R24"
          and not os.path.exists(fresh + ".lck") and not os.path.exists(ptr))
    # sid scoping is preserved: a revoke for the same task id under a DIFFERENT sid
    # leaves another session's locked grant and pointer strictly alone.
    other = os.path.join(gdir, "claude-commit-grant-R24-other.json")
    with open(other, "wb") as handle:
        handle.write(grant_bytes("sid-OTHER", "T-R24", repo, parent))
    ev2 = payload("toolu_01R24OTHER")
    GUARD._lock_grant_for_posttool(other, GUARD._event_key(ev2),
                                   GUARD._raw_tool_use_id(ev2))
    ptr2 = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid=GUARD._event_key(ev2))
    WCG._revoke_grants_for_task(gdir, "T-R24", "sid-r24")
    check("r24_revocation_stays_sid_scoped (another session's lock and pointer survive)",
          os.path.exists(other + ".lck") and os.path.isfile(ptr2))

    # ========================================================= mutation: is it load-bearing?
    # Re-derive the key the PRE-FIX way — the session id, which is what the pointer used to be
    # named for and what the finalizer used to try — and replay the audit's case verbatim. The
    # attack must LAND under the mutant, or the refusal above proves nothing.
    base, repo, parent, head = scene(tmp, "mutation-reopens")
    set_env(CLAUDE_SESSION_ID="sid-shared-orch")
    foreign = mint(base, "sid-shared-orch", "T-FOREIGN", repo, parent, sid="sid-shared-orch")
    finalize("sid-shared-orch", "sid-bulk-subagent", "success")
    mutant = entries_for(repo)
    check("mutation_reopens_the_hole: pre-fix session keying writes the MIXED record",
          len(mutant) == 1 and mutant[0]["task_id"] == "T-FOREIGN"
          and "sid-bulk-subagent" in mutant[0]["session_ids"])
    check("mutation_reopens_the_hole: that record is SPENDABLE (parent linkage passes)",
          CJ.find_attributable_event(repo, head, "T-FOREIGN", "sid-bulk-subagent") is not None)
    check("mutation_reopens_the_hole: it also consumed the foreign event's grant",
          life(foreign) == CONSUMED)

    # ...and the lifecycle assertions must NOT be what detects that mutation. Under the mutant
    # keying an event that legitimately owns its pointer still consumes and restores exactly as
    # it does under the fix, so every lifecycle check above is independent of the refusal and
    # cannot be quietly standing in for it.
    base, repo, parent, head = scene(tmp, "mutation-lifecycle-success")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    owner = mint(base, "sid-orchestrator", "T-OWNER", repo, parent, sid="sid-orchestrator")
    finalize("sid-orchestrator", "sid-subagent", "success")
    mutant_success = life(owner)
    base, repo, parent, head = scene(tmp, "mutation-lifecycle-failure")
    owner = mint(base, "sid-orchestrator", "T-OWNER", repo, parent, sid="sid-orchestrator")
    finalize("sid-orchestrator", "sid-subagent", "failure")
    check("mutation_leaves_lifecycle_assertions_unchanged (they do not encode the refusal)",
          mutant_success == CONSUMED and life(owner) == RESTORED
          and open(owner["original"], "rb").read() == owner["payload"])

    # ========================================================= fail-open on the write path.
    # The finalizer runs after the commit has already landed; nothing it does may raise.
    set_env()
    clear_pointers()
    bad_dir = os.path.join(tmp, "failopen")
    os.makedirs(bad_dir)
    corrupt = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01CORRUPT")
    with open(corrupt, "w") as handle:
        handle.write("{ not json")
    try:
        finalize("tu-toolu_01CORRUPT", "sid-subagent", "success")
        check("corrupt pointer at our own name does not raise and is reaped",
              not os.path.exists(corrupt))
    except Exception:
        check("corrupt pointer at our own name does not raise and is reaped", False)

    clear_pointers()
    dangling = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01DANGLING")
    with open(dangling, "w") as handle:
        json.dump({"locked_path": os.path.join(bad_dir, "gone.json.lck"),
                   "original_path": os.path.join(bad_dir, "gone.json"),
                   "event_key": "tu-toolu_01DANGLING",
                   "tool_use_id": "toolu_01DANGLING"}, handle)
    try:
        finalize("tu-toolu_01DANGLING", "sid-subagent", "success")
        check("pointer to a missing grant does not raise and is reaped",
              not os.path.exists(dangling))
    except Exception:
        check("pointer to a missing grant does not raise and is reaped", False)

    try:
        clear_pointers()
        finalize("", "", "success", raw="")
        finalize("tu-nobody", "sid-nobody", "unknown_terminal")
        GUARD._lock_grant_for_posttool(os.path.join(bad_dir, "absent.json"),
                                       "tu-absent", "absent")
        check("empty key, absent pointers and an absent grant do not raise", True)
    except Exception:
        check("empty key, absent pointers and an absent grant do not raise", False)

    # ================================================================ the real payload seam.
    # Audit R2-1: every check above hands the finalizer a PRE-CLASSIFIED string, so a
    # classifier that could not recognize the real payloads would pass this whole file while
    # production journaled nothing. These drive main() with full payload JSON on stdin, in
    # the two shapes the harness actually delivers — settled against the shipped binary's
    # BashOutput schema and live transcript records (see _classify_terminal_result): success
    # arrives as PostToolUse with tool_response={stdout,stderr,interrupted,...} and NO
    # exit_code / is_error; a failed command THROWS in the tool and arrives as a separate
    # PostToolUseFailure event carrying an `error` string and no tool_response at all.
    check("classifier derives success from the real BashOutput success shape",
          PT._classify_terminal_result(
              {"hook_event_name": "PostToolUse", "tool_name": "Bash",
               "tool_response": {"stdout": "ok", "stderr": "",
                                 "interrupted": False}}) == "success")
    check("classifier treats the PostToolUseFailure event as terminal failure",
          PT._classify_terminal_result(
              {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
               "error": "Exit code 7\nstderr text"}) == "failure")
    check("classifier refuses success for an interrupted command",
          PT._classify_terminal_result(
              {"tool_response": {"stdout": "", "stderr": "",
                                 "interrupted": True}}) == "failure")
    check("classifier treats a background-launch receipt as non-terminal",
          PT._classify_terminal_result(
              {"tool_response": {"stdout": "", "stderr": "", "interrupted": False,
                                 "backgroundTaskId": "b1"}}) == "unknown_terminal")
    check("classifier keeps SDK-style is_error / exit_code semantics",
          PT._classify_terminal_result({"tool_response": {"exit_code": 0}}) == "success"
          and PT._classify_terminal_result({"tool_response": {"exit_code": 7}}) == "non_zero"
          and PT._classify_terminal_result({"tool_response": {"is_error": True}}) == "failure"
          and PT._classify_terminal_result({}) == "unknown_terminal")

    # Combined shapes (audit F3): the shipped binary's explicit-background and
    # timeout-background paths both return {stdout:"", stderr:"", code:0,
    # interrupted:false, backgroundTaskId} — a receipt CARRIES a zero exit code —
    # and an SDK-style payload can carry exit_code next to either dominant
    # signal. Pre-fix, the exit_code branch ran first, so such a payload
    # classified success: an unfinished or interrupted commit was journaled and
    # its grant consumed. Nonterminal and interrupted must dominate any code.
    check("f3_background_receipt_dominates_exit_code_0",
          PT._classify_terminal_result(
              {"tool_response": {"exit_code": 0, "backgroundTaskId": "b1"}})
          == "unknown_terminal")
    check("f3_background_receipt_dominates_any_exit_code",
          PT._classify_terminal_result(
              {"tool_response": {"exit_code": 7, "backgroundTaskId": "b1"}})
          == "unknown_terminal")
    check("f3_interrupted_dominates_exit_code_0",
          PT._classify_terminal_result(
              {"tool_response": {"exit_code": 0, "interrupted": True}})
          == "failure")
    check("f3_real_receipt_shape_with_its_code_field_is_nonterminal",
          PT._classify_terminal_result(
              {"tool_response": {"stdout": "", "stderr": "", "code": 0,
                                 "interrupted": False, "backgroundTaskId": "b1"}})
          == "unknown_terminal")
    check("f3_background_plus_interrupted_reads_nonterminal (the recoverable "
          "reading: leaving state alone is retryable, consuming it is not)",
          PT._classify_terminal_result(
              {"tool_response": {"interrupted": True, "backgroundTaskId": "b1"}})
          == "unknown_terminal")

    # A real successful `git commit`, end to end through main(): journal written, grant
    # consumed. Under the pre-fix classifier this exact payload classified unknown_terminal,
    # which RESTORED the single-use grant and wrote nothing — the inert-journal defect.
    base, repo, parent, head = scene(tmp, "payload-success")
    owner = mint(base, "tu-toolu_01REALOK", "T-PAYLOAD", repo, parent, sid="sid-grant-cli")
    try:
        rc = drive_main({
            "hook_event_name": "PostToolUse",
            "session_id": "sid-payload-subagent",
            "transcript_path": os.path.join(base, "transcript.jsonl"),
            "cwd": repo,
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'feat: work'"},
            "tool_response": {"stdout": "[master 1234abc] feat: work", "stderr": "",
                              "interrupted": False, "isImage": False,
                              "noOutputExpected": False},
            "tool_use_id": "toolu_01REALOK",
            "duration_ms": 250,
        })
    except Exception:
        rc = "raised"
    got = entries_for(repo)
    check("payload_seam_real_success_shape_journals_and_consumes",
          rc == 0 and len(got) == 1 and got[0]["task_id"] == "T-PAYLOAD"
          and got[0]["resulting_head"] == head and life(owner) == CONSUMED)

    # A real failed `git commit`: the PostToolUseFailure payload restores the grant for
    # retry and journals nothing. settings.json registers this hook for that event; without
    # that wiring the .lck stayed locked until the stale reap.
    base, repo, parent, head = scene(tmp, "payload-failure")
    owner = mint(base, "tu-toolu_01REALFAIL", "T-PAYLOAD", repo, parent, sid="sid-grant-cli")
    try:
        rc = drive_main({
            "hook_event_name": "PostToolUseFailure",
            "session_id": "sid-payload-subagent",
            "transcript_path": os.path.join(base, "transcript.jsonl"),
            "cwd": repo,
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'feat: work'"},
            "tool_use_id": "toolu_01REALFAIL",
            "error": "Exit code 1\nnothing to commit, working tree clean",
            "is_interrupt": False,
        })
    except Exception:
        rc = "raised"
    check("payload_seam_real_failure_event_restores_for_retry_and_journals_nothing",
          rc == 0 and entries_for(repo) == [] and life(owner) == RESTORED
          and open(owner["original"], "rb").read() == owner["payload"])

    # Sentinel consume-on-any-terminal-result through the same seam: a structural /allow
    # grant is unlinked by main() on BOTH terminal outcomes. Success already consumed in
    # production (the unlink is unconditional, only the label was wrong); failure never
    # reached this hook at all before the PostToolUseFailure wiring.
    clear_pointers()
    for label, extra in (
            ("success", {"hook_event_name": "PostToolUse",
                         "tool_response": {"stdout": "", "stderr": "",
                                           "interrupted": False}}),
            ("failure", {"hook_event_name": "PostToolUseFailure",
                         "error": "Exit code 1"})):
        sid = "sid-sentinel-" + label
        spath = sentinel_grant(sid)
        try:
            rc = drive_main({"session_id": sid, "tool_name": "Bash",
                             "tool_input": {"command": "git commit -m 'x'"},
                             "tool_use_id": "toolu_01SENT" + label.upper(), **extra})
        except Exception:
            rc = "raised"
        check("sentinel_grant_consumed_on_%s_terminal_via_main" % label,
              rc == 0 and not os.path.exists(spath))

    # ==================================== F2: a nonterminal receipt finalizes NOTHING.
    # A backgrounded command's PostToolUse carries a receipt while the command is
    # still running, and no later PostToolUse ever fires for that tool_use_id
    # (completion arrives as a conversation task-notification, not a hook event).
    # Pre-fix the finalizer treated the receipt like a failure: it RESTORED the
    # locked grant and deleted the pointer — the backgrounded commit then finished
    # with its single-use grant already made reusable and no journal attribution
    # possible. Now the whole state survives for the terminal path or the
    # age-bounded sweeps, and the nonterminal event performs no deletions AT ALL,
    # the stale sweep included.
    base, repo, parent, head = scene(tmp, "f2-nonterminal")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    owner = mint(base, "tu-toolu_01BG", "T-BG", repo, parent, sid="sid-grant-cli")
    stale_peer = mint(base, "tu-toolu_01BGPEER", "T-BGPEER", repo, parent)
    age(stale_peer["pointer"], PT._POINTER_STALE_SECONDS + 60)
    age(stale_peer["locked"], PT._POINTER_STALE_SECONDS + 90)
    finalize("tu-toolu_01BG", "sid-subagent", "unknown_terminal")
    check("f2_nonterminal_receipt_finalizes_nothing "
          "(no journal, no consume, no restore, no pointer deletion)",
          entries_for(repo) == [] and life(owner) == UNTOUCHED)
    check("f2_nonterminal_event_runs_no_stale_sweep_either",
          life(stale_peer) == UNTOUCHED)
    finalize("tu-toolu_01BG", "sid-subagent", "success")
    got = entries_for(repo)
    check("f2_preserved_state_still_finalizes_on_a_terminal_event",
          len(got) == 1 and got[0]["task_id"] == "T-BG" and life(owner) == CONSUMED)

    # Same property through the REAL entrypoint: a background-receipt payload for
    # a git commit leaves the sentinel grant, the locked grant, and the pointer
    # all in place.
    clear_pointers()
    base, repo, parent, head = scene(tmp, "f2-payload-background")
    owner = mint(base, "tu-toolu_01BGMAIN", "T-BGMAIN", repo, parent,
                 sid="sid-grant-cli")
    spath = sentinel_grant("sid-bg-main")
    try:
        rc = drive_main({
            "hook_event_name": "PostToolUse",
            "session_id": "sid-bg-main",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'feat: slow'"},
            "tool_response": {"stdout": "", "stderr": "", "interrupted": False,
                              "backgroundTaskId": "bg_1"},
            "tool_use_id": "toolu_01BGMAIN",
        })
    except Exception:
        rc = "raised"
    check("f2_background_receipt_through_main_touches_nothing "
          "(sentinel, locked grant, pointer, journal all intact)",
          rc == 0 and os.path.exists(spath) and life(owner) == UNTOUCHED
          and entries_for(repo) == [])
    try:
        os.unlink(spath)
    except OSError:
        pass

    # ================================== F7: pointer publication is atomic.
    # The pre-fix writer opened the FINAL name O_EXCL and wrote JSON into the open
    # handle, so a concurrently colliding event could read PARTIAL JSON and reap
    # the half-written pointer as corrupt — stranding the owner's .lck with no
    # journal record. The writer now stages under a temp name, fsyncs, and
    # publishes with link(2). Demonstrated by execution: DURING the content write
    # the final name does not exist and the namespace glob is empty (there is
    # nothing a reader could partially read), and publication lands complete.
    base, repo, parent, head = scene(tmp, "f7-atomic-publication")
    original = os.path.join(base, "claude-commit-grant-T-ATOMIC-nonce.json")
    with open(original, "wb") as handle:
        handle.write(grant_bytes("sid-orchestrator", "T-ATOMIC", repo, parent))
    final_name = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01ATOMIC")
    observed = {}
    real_dump = json.dump

    class _MidWriteObserver:
        @staticmethod
        def dump(obj, fp):
            fp.write('{"locked_path": "half')  # partial JSON is on disk NOW
            fp.flush()
            observed["final_name_mid_write"] = os.path.exists(final_name)
            observed["glob_clean_mid_write"] = (
                glob.glob(PT._COMMIT_GRANT_POINTER_GLOB) == [])
            fp.seek(0)
            fp.truncate()
            real_dump(obj, fp)

    saved_guard_json = GUARD.json
    GUARD.json = _MidWriteObserver
    try:
        GUARD._lock_grant_for_posttool(original, "tu-toolu_01ATOMIC",
                                       "toolu_01ATOMIC")
    finally:
        GUARD.json = saved_guard_json
    check("f7_no_reader_can_observe_a_partial_pointer "
          "(final name absent and namespace glob empty during the content write)",
          observed.get("final_name_mid_write") is False
          and observed.get("glob_clean_mid_write") is True)
    published = json.load(open(final_name)) if os.path.isfile(final_name) else {}
    check("f7_publication_lands_complete_and_leaves_no_temp_residue",
          published.get("locked_path") == original + ".lck"
          and published.get("tool_use_id") == "toolu_01ATOMIC"
          and [p for p in os.listdir(os.path.dirname(final_name))
               if ".wip." in p] == [])
    finalize("tu-toolu_01ATOMIC", "sid-subagent", "success", raw="toolu_01ATOMIC")
    check("f7_atomically_published_pointer_finalizes_normally",
          len(entries_for(repo)) == 1 and not os.path.exists(final_name)
          and not os.path.exists(original + ".lck"))

    # Reader half of F7: a pointer that PARSES but lacks a required field carries
    # the same trust as one that does not parse — reaped like the corrupt case,
    # acted on never, and only the POINTER is unlinked (a .lck it half-names
    # survives for the ownership-bound sweeps).
    base, repo, parent, head = scene(tmp, "f7-field-incomplete")
    bystander_lck = os.path.join(base,
                                 "claude-commit-grant-T-INCOMPLETE-nonce.json.lck")
    with open(bystander_lck, "wb") as handle:
        handle.write(grant_bytes("sid-x", "T-INCOMPLETE", repo, parent))
    for label, content in (
            ("empty-object", {}),
            ("missing-locked-path", {"original_path": bystander_lck[:-4],
                                     "event_key": "tu-toolu_01INC",
                                     "tool_use_id": "toolu_01INC"}),
            ("non-dict", ["not", "a", "pointer"])):
        incomplete = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01INC")
        with open(incomplete, "w") as handle:
            json.dump(content, handle)
        finalize("tu-toolu_01INC", "sid-subagent", "success", raw="toolu_01INC")
        check("f7_field_incomplete_pointer_is_reaped_not_acted_on (%s)" % label,
              not os.path.exists(incomplete) and entries_for(repo) == []
              and os.path.exists(bystander_lck))
    os.unlink(bystander_lck)

    # ================================== F10: hostile names cannot stall the hook.
    # The pointer namespace is world-writable: a FIFO blocks open(2) until a
    # writer appears, and a symlink can point a read at a blocking device. Every
    # untrusted read is now lstat-gated (regular, non-symlink), opened
    # O_NOFOLLOW|O_NONBLOCK, fstat-rechecked, and size-bounded. Probes run on a
    # joined worker thread so a regression hangs a daemon thread, not the suite.
    def bounded(fn, seconds=10):
        box = {}

        def run():
            try:
                fn()
                box["done"] = True
            except Exception as exc:  # pragma: no cover - fail-open contract
                box["raised"] = exc
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(seconds)
        return box

    base, repo, parent, head = scene(tmp, "f10-fifo-own-name")
    fifo_own = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01FIFO")
    os.mkfifo(fifo_own)
    box = bounded(lambda: finalize("tu-toolu_01FIFO", "sid-subagent", "success",
                                   raw="toolu_01FIFO"))
    check("f10_fifo_at_the_callers_own_pointer_name_does_not_stall "
          "(bounded probe returned; unreadable name reaped, never opened blocking)",
          box.get("done") is True and not os.path.exists(fifo_own)
          and entries_for(repo) == [])

    base, repo, parent, head = scene(tmp, "f10-fifo-in-reaper-path")
    fifo_peer = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01FIFOPEER")
    os.mkfifo(fifo_peer)
    age(fifo_peer, PT._POINTER_STALE_SECONDS + 60)
    owner = mint(base, "tu-toolu_01FIFORUN", "T-FIFORUN", repo, parent,
                 sid="sid-grant-cli")
    box = bounded(lambda: finalize("tu-toolu_01FIFORUN", "sid-subagent", "success"))
    check("f10_stale_fifo_in_the_reapers_namespace_does_not_stall_finalization "
          "(callers own pointer still processed)",
          box.get("done") is True and not os.path.exists(fifo_peer)
          and life(owner) == CONSUMED and len(entries_for(repo)) == 1)

    base, repo, parent, head = scene(tmp, "f10-symlink-own-name")
    target = os.path.join(base, "precious.json")
    with open(target, "w") as handle:
        json.dump({"keep": "me"}, handle)
    link_name = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01SYM")
    os.symlink(target, link_name)
    box = bounded(lambda: finalize("tu-toolu_01SYM", "sid-subagent", "success",
                                   raw="toolu_01SYM"))
    check("f10_symlink_pointer_is_refused_unfollowed_and_its_target_survives",
          box.get("done") is True and not os.path.lexists(link_name)
          and os.path.exists(target) and entries_for(repo) == [])

    base, repo, parent, head = scene(tmp, "f10-fifo-locked-grant")
    fifo_grant = os.path.join(base, "claude-commit-grant-FIFO-nonce.json.lck")
    os.mkfifo(fifo_grant)
    forged = PT._COMMIT_GRANT_POINTER_TEMPLATE.format(sid="tu-toolu_01FIFOGRANT")
    with open(forged, "w") as handle:
        json.dump({"locked_path": fifo_grant, "original_path": fifo_grant[:-4],
                   "event_key": "tu-toolu_01FIFOGRANT",
                   "tool_use_id": "toolu_01FIFOGRANT"}, handle)
    box = bounded(lambda: finalize("tu-toolu_01FIFOGRANT", "sid-subagent",
                                   "success", raw="toolu_01FIFOGRANT"))
    check("f10_forged_pointer_naming_a_fifo_grant_cannot_stall_the_journal_read",
          box.get("done") is True and entries_for(repo) == []
          and not os.path.exists(forged))

    # Stop-sweep half of F10, by execution through the real script: a FIFO and a
    # symlink planted in the sweep namespace neither stall the sweep nor get
    # deleted (non-regular reads as undecidable, and aged() requires S_ISREG —
    # cleanup that cannot decide leaves things alone).
    sweep2 = os.path.join(tmp, "f10-sweep")
    home2 = os.path.join(tmp, "f10-home")
    os.makedirs(sweep2)
    os.makedirs(home2)
    fifo_sweep = os.path.join(sweep2,
                              "claude-commit-grant-active-tu-toolu_01SWFIFO.json")
    os.mkfifo(fifo_sweep)
    live_lck = os.path.join(sweep2, "claude-commit-grant-sid-f10-own-ee55.json.lck")
    with open(live_lck, "w") as handle:
        json.dump({"sid": "sid-f10-own"}, handle)
    link_lck = os.path.join(sweep2, "claude-commit-grant-sid-f10-link-ff66.json.lck")
    os.symlink(live_lck, link_lck)
    env2 = dict(os.environ, CLAUDE_COMMIT_GRANT_SWEEP_DIR=sweep2, HOME=home2)
    for key in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        env2.pop(key, None)
    try:
        proc = subprocess.run(
            ["bash", str(HOOKS_DIR / "stop-cleanup-allowlist.sh")],
            input=json.dumps({"session_id": "sid-f10-other",
                              "hook_event_name": "Stop", "stop_hook_active": False,
                              "transcript_path": os.path.join(tmp, "t2.jsonl"),
                              "cwd": tmp}),
            text=True, capture_output=True, env=env2, timeout=60)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = "stalled"
    except Exception:
        rc = "raised"
    check("f10_stop_sweep_with_fifo_and_symlink_in_namespace_exits_0_promptly",
          rc == 0)
    check("f10_stop_sweep_leaves_fifo_symlink_and_foreign_grant_alone "
          "(undecidable = keep)",
          os.path.exists(live_lck) and os.path.lexists(fifo_sweep)
          and os.path.lexists(link_lck))

    # ============================ F8: pathname ABA races in every cleanup path.
    # Four places validated a pathname INSTANCE — read its JSON, judged its age,
    # proved its ownership — and then unlinked or renamed BY NAME, with the whole
    # journal write (a `git` subprocess) sitting inside the gap on the widest of
    # them. If the validated entry is removed in that gap and a colliding live
    # event re-creates the same name, the old operation destroys the REPLACEMENT:
    # a live pointer, or a locked grant belonging to another event, which then
    # has nothing to finalize and no journal attribution. Name collisions are not
    # hypothetical here — pointer names come from a deliberately LOSSY fold of
    # tool_use_id (R2-2), and grant names are reused across the whole
    # lock/restore/revoke cycle.
    #
    # Every scenario below performs the swap FROM INSIDE the real code path, at
    # the exact seam between validation and the act, and then proves the
    # replacement survives AS THE SAME INODE — mere existence would be satisfied
    # by a delete-and-recreate and would prove nothing. Each is paired with a
    # mutation that restores the pure-name operation and watches the replacement
    # get destroyed, so the refusal is shown to be load-bearing rather than
    # incidental.
    def ident_of(path):
        try:
            st = os.lstat(path)
        except OSError:
            return None
        return (st.st_dev, st.st_ino)

    def swap_for_replacement(path, marker):
        """Remove the file at `path` and put a DIFFERENT, live inode there."""
        os.unlink(path)
        with open(path, "w") as handle:
            json.dump({"replacement": marker}, handle)
        return ident_of(path)

    def pure_name_unlink(path, ident=None):
        """The pre-fix operation: act on the NAME, whatever now occupies it."""
        try:
            os.unlink(path)
            return True
        except OSError:
            return False

    def journal_swap(state, targets):
        """Swap `targets` from inside append_commit_event — in production a git
        subprocess, i.e. the widest part of the window the old code left open."""
        real_append = CJ.append_commit_event

        def swapping(grant, session_id):
            real_append(grant, session_id)
            if not state:
                for label, path in targets:
                    state[label] = swap_for_replacement(path, label)
        return real_append, swapping

    # --- Path 1 of 4: the finalizer's own pointer handling (success path).
    base, repo, parent, head = scene(tmp, "f8-finalizer-success")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    victim = mint(base, "tu-toolu_01F8FIN", "T-F8FIN", repo, parent,
                  sid="sid-grant-cli")
    swapped = {}
    real_append, swapping = journal_swap(
        swapped, [("locked", victim["locked"]), ("pointer", victim["pointer"])])
    CJ.append_commit_event = swapping
    try:
        finalize("tu-toolu_01F8FIN", "sid-subagent", "success")
    finally:
        CJ.append_commit_event = real_append
    check("f8_finalizer_success_path_leaves_a_swapped_in_replacement_alone "
          "(locked grant AND pointer survive as the same inode)",
          len(swapped) == 2
          and ident_of(victim["locked"]) == swapped.get("locked")
          and ident_of(victim["pointer"]) == swapped.get("pointer"))

    base, repo, parent, head = scene(tmp, "f8-finalizer-success-mutant")
    victim = mint(base, "tu-toolu_01F8FINM", "T-F8FINM", repo, parent,
                  sid="sid-grant-cli")
    swapped = {}
    real_append, swapping = journal_swap(
        swapped, [("locked", victim["locked"]), ("pointer", victim["pointer"])])
    CJ.append_commit_event = swapping
    saved_unlink = PT._unlink_verified
    PT._unlink_verified = pure_name_unlink
    try:
        finalize("tu-toolu_01F8FINM", "sid-subagent", "success")
    finally:
        PT._unlink_verified = saved_unlink
        CJ.append_commit_event = real_append
    check("f8_mutation_finalizer: pure-name unlink DESTROYS both replacements",
          len(swapped) == 2 and not os.path.exists(victim["locked"])
          and not os.path.exists(victim["pointer"]))

    # --- Path 2 of 4: the finalizer's stale reaper.
    base, repo, parent, head = scene(tmp, "f8-reaper")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    abandoned = mint(base, "tu-toolu_01F8REAP", "T-F8REAP", repo, parent,
                     sid="sid-grant-cli")
    age(abandoned["pointer"], PT._POINTER_STALE_SECONDS + 60)
    age(abandoned["locked"], PT._POINTER_STALE_SECONDS + 90)
    swapped = {}
    real_pred = PT._stale_locked_grant_reapable

    def swapping_pred(locked, now):
        # The seam: the verdict is computed against the validated instance, and
        # the swap lands before the reaper can act on it.
        verdict = real_pred(locked, now)
        if verdict and not swapped:
            swapped["locked"] = swap_for_replacement(abandoned["locked"], "lck")
            swapped["pointer"] = swap_for_replacement(abandoned["pointer"], "ptr")
        return verdict

    PT._stale_locked_grant_reapable = swapping_pred
    try:
        finalize("tu-toolu_01F8REAPRUN", "sid-x", "success")
    finally:
        PT._stale_locked_grant_reapable = real_pred
    check("f8_stale_reaper_leaves_a_swapped_in_replacement_alone",
          len(swapped) == 2
          and ident_of(abandoned["locked"]) == swapped.get("locked")
          and ident_of(abandoned["pointer"]) == swapped.get("pointer"))

    base, repo, parent, head = scene(tmp, "f8-reaper-mutant")
    abandoned = mint(base, "tu-toolu_01F8REAPM", "T-F8REAPM", repo, parent,
                     sid="sid-grant-cli")
    age(abandoned["pointer"], PT._POINTER_STALE_SECONDS + 60)
    age(abandoned["locked"], PT._POINTER_STALE_SECONDS + 90)
    swapped = {}
    PT._stale_locked_grant_reapable = swapping_pred
    saved_unlink = PT._unlink_verified
    PT._unlink_verified = pure_name_unlink
    try:
        finalize("tu-toolu_01F8REAPRUN2", "sid-x", "success")
    finally:
        PT._unlink_verified = saved_unlink
        PT._stale_locked_grant_reapable = real_pred
    check("f8_mutation_stale_reaper: pure-name unlink DESTROYS both replacements",
          len(swapped) == 2 and not os.path.exists(abandoned["locked"])
          and not os.path.exists(abandoned["pointer"]))

    # --- The restore half of path 1: rename is name-resolved too, so the same
    # swap moves a replacement OUT from under its owner.
    def restore_scenario(label, rename_impl):
        b, r, p, _h = scene(tmp, label)
        v = mint(b, "tu-toolu_01F8RES", "T-F8RES", r, p, sid="sid-grant-cli")
        state = {}
        real_rename = PT._rename_verified

        def hooked(src, dst, ident):
            if not state:
                state["locked"] = swap_for_replacement(v["locked"], "lck")
            return rename_impl(real_rename, src, dst, ident)

        PT._rename_verified = hooked
        try:
            finalize("tu-toolu_01F8RES", "sid-subagent", "failure")
        finally:
            PT._rename_verified = real_rename
        return v, state

    victim, swapped = restore_scenario(
        "f8-restore", lambda real, src, dst, ident: real(src, dst, ident))
    check("f8_restore_path_will_not_move_a_swapped_in_replacement",
          swapped.get("locked") is not None
          and ident_of(victim["locked"]) == swapped["locked"]
          and not os.path.exists(victim["original"]))

    def _mutant_rename(real, src, dst, ident):
        try:
            os.rename(src, dst)
            return True
        except OSError:
            return False

    victim, swapped = restore_scenario("f8-restore-mutant", _mutant_rename)
    check("f8_mutation_restore: pure-name rename MOVES the replacement away",
          swapped.get("locked") is not None
          and not os.path.exists(victim["locked"])
          and ident_of(victim["original"]) == swapped["locked"])

    # --- Path 3 of 4: revocation in scripts/write-commit-grant.py.
    def revoke_scenario(label, swap_target, unlink_impl=None):
        """Drive the REAL revoke path, swapping `swap_target` right after the
        instance that authorizes its deletion has been read."""
        b, r, p, _h = scene(tmp, label)
        gdir = os.path.join(b, "grants")
        os.makedirs(gdir)
        original = os.path.join(gdir, "claude-commit-grant-F8REV-nonce.json")
        with open(original, "wb") as handle:
            handle.write(grant_bytes("sid-f8rev", "T-F8REV", r, p))
        event = payload("toolu_01" + label.replace("-", "").upper())
        GUARD._lock_grant_for_posttool(original, GUARD._event_key(event),
                                       GUARD._raw_tool_use_id(event))
        paths = {"locked": original + ".lck", "original": original,
                 "pointer": PT._COMMIT_GRANT_POINTER_TEMPLATE.format(
                     sid=GUARD._event_key(event))}
        state = {}
        real_read = WCG._read_identified
        real_unlink = WCG._unlink_identified

        def hooked_read(path, limit=WCG._UNTRUSTED_READ_LIMIT):
            result = real_read(path, limit)
            if path == paths[swap_target] and swap_target not in state:
                state[swap_target] = swap_for_replacement(paths[swap_target],
                                                          swap_target)
            return result

        WCG._read_identified = hooked_read
        if unlink_impl is not None:
            WCG._unlink_identified = unlink_impl
        try:
            WCG._revoke_grants_for_task(gdir, "T-F8REV", "sid-f8rev")
        finally:
            WCG._read_identified = real_read
            WCG._unlink_identified = real_unlink
        return paths, state

    paths, swapped = revoke_scenario("f8-revoke-grant", "locked")
    check("f8_revocation_will_not_delete_a_grant_swapped_in_after_the_read",
          swapped.get("locked") is not None
          and ident_of(paths["locked"]) == swapped["locked"])
    paths, swapped = revoke_scenario("f8-revoke-grant-mutant", "locked",
                                     unlink_impl=pure_name_unlink)
    check("f8_mutation_revocation_grant: pure-name unlink DESTROYS the replacement",
          swapped.get("locked") is not None
          and not os.path.exists(paths["locked"]))

    paths, swapped = revoke_scenario("f8-revoke-pointer", "pointer")
    check("f8_revocation_will_not_delete_a_pointer_swapped_in_after_the_read "
          "(and the grant it was revoking is still removed)",
          swapped.get("pointer") is not None
          and ident_of(paths["pointer"]) == swapped["pointer"]
          and not os.path.exists(paths["locked"]))
    paths, swapped = revoke_scenario("f8-revoke-pointer-mutant", "pointer",
                                     unlink_impl=pure_name_unlink)
    check("f8_mutation_revocation_pointer: pure-name unlink DESTROYS the "
          "replacement",
          swapped.get("pointer") is not None
          and not os.path.exists(paths["pointer"]))

    # --- Path 4 of 4: the Stop sweep. It is a separate PROGRAM, so the block is
    # extracted VERBATIM from the shipped hook and executed here; nothing can
    # drift between what is tested and what runs at session end, and the
    # interleave is deterministic instead of a timing gamble. The end-to-end bash
    # runs above and below keep the real shell path covered.
    stop_text = (HOOKS_DIR / "stop-cleanup-allowlist.sh").read_text()
    _sweep_head = stop_text.index("\n", stop_text.index("<<'PYSWEEP'")) + 1
    STOP_SWEEP_SRC = stop_text[_sweep_head:
                               stop_text.index("\nPYSWEEP\n", _sweep_head)]
    check("f8_stop_sweep_block_extracted_from_the_shipped_hook (not vacuous, "
          "both loops act through the identity-verified unlink)",
          len(STOP_SWEEP_SRC) > 500
          and STOP_SWEEP_SRC.count("unlink_verified(p, ident)") == 2
          and "os.unlink(p)\n" not in STOP_SWEEP_SRC
          and "claude-commit-grant-active-*.json" in STOP_SWEEP_SRC)

    def run_sweep_block(sweep_dir, sweep_sid, source=None, extra=None):
        namespace = {"__name__": "stop_cleanup_pysweep"}
        namespace.update(extra or {})
        saved_vars = {key: os.environ.get(key) for key in
                      ("CLAUDE_STOP_SWEEP_SID", "CLAUDE_COMMIT_GRANT_SWEEP_DIR")}
        os.environ["CLAUDE_STOP_SWEEP_SID"] = sweep_sid
        os.environ["CLAUDE_COMMIT_GRANT_SWEEP_DIR"] = sweep_dir
        saved_out = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exec(compile(source if source is not None else STOP_SWEEP_SRC,
                         "stop-cleanup-allowlist.sh[PYSWEEP]", "exec"), namespace)
        finally:
            sys.stdout = saved_out
            for key, value in saved_vars.items():
                os.environ.pop(key, None)
                if value is not None:
                    os.environ[key] = value

    def sweep_aba(label, plant_lck, source=None):
        """Swap the artifact the sweep is about to unlink, from inside the
        shipped loop. The seam is the liveness probe's own realpath() call,
        which BOTH loops make on their entry's recorded repo_root AFTER
        capturing that entry's identity and BEFORE deciding to unlink it.

        The locked-grant scenario deliberately plants NO pointer: with one, the
        pointer loop reaches the same repo_root first and the swap would land
        before the .lck loop ever validated its target — the assertion would
        then pass because nothing was reaped at all, which is exactly the way
        a concurrency test lies."""
        sweep_dir = os.path.join(tmp, label)
        os.makedirs(sweep_dir)
        probe_repo = os.path.join(tmp, label + "-repo")
        os.makedirs(probe_repo)
        lck = os.path.join(sweep_dir,
                           "claude-commit-grant-sid-%s-7777.json.lck" % label)
        with open(lck, "w") as handle:
            json.dump({"sid": "sid-" + label, "task_id": "T-" + label,
                       "repo_root": probe_repo}, handle)
        age(lck, 1800 + 90)
        target = lck
        if not plant_lck:
            ptr = os.path.join(sweep_dir,
                               "claude-commit-grant-active-tu-toolu_01%s.json"
                               % label.replace("-", "").upper()[:12])
            with open(ptr, "w") as handle:
                json.dump({"locked_path": lck, "original_path": lck[:-4],
                           "event_key": "tu-x", "tool_use_id": "x"}, handle)
            age(ptr, 1800 + 60)
            target = ptr
        state = {}
        real_realpath = os.path.realpath

        def swapping_realpath(path, *rest, **kwargs):
            if path == probe_repo and not state:
                state["ident"] = swap_for_replacement(target, "live")
            return real_realpath(path, *rest, **kwargs)

        os.path.realpath = swapping_realpath
        try:
            run_sweep_block(sweep_dir, "sid-unrelated-sweeper", source=source,
                            extra={"mutant_unlink": pure_name_unlink})
        finally:
            os.path.realpath = real_realpath
        return target, state

    target, swapped = sweep_aba("f8sweepptr", plant_lck=False)
    check("f8_stop_sweep_pointer_loop_leaves_a_swapped_in_replacement_alone",
          swapped.get("ident") is not None
          and ident_of(target) == swapped["ident"])
    mutant_src = STOP_SWEEP_SRC.replace("unlink_verified(p, ident)",
                                        "mutant_unlink(p, ident)")
    target, swapped = sweep_aba("f8sweepptrm", plant_lck=False,
                                source=mutant_src)
    check("f8_mutation_stop_sweep_pointer_loop: pure-name unlink DESTROYS the "
          "replacement",
          swapped.get("ident") is not None and not os.path.exists(target))

    target, swapped = sweep_aba("f8sweeplck", plant_lck=True)
    check("f8_stop_sweep_locked_grant_loop_leaves_a_swapped_in_replacement_alone",
          swapped.get("ident") is not None
          and ident_of(target) == swapped["ident"])
    target, swapped = sweep_aba("f8sweeplckm", plant_lck=True, source=mutant_src)
    check("f8_mutation_stop_sweep_locked_grant_loop: pure-name unlink DESTROYS "
          "the replacement",
          swapped.get("ident") is not None and not os.path.exists(target))

    # ================== F9: age is not proof that an event has terminated.
    # --- The Stop half, by execution through the REAL script. A grant carries
    # its MINT mtime, not its lock time: write-commit-grant.py creates the file,
    # it may sit for a long while, and the rename-aside that locks it preserves
    # mtime. So a grant minted 40 minutes ago and locked one second ago read as
    # "over-age" and was deleted out from under a live commit belonging to
    # another session. Its POINTER is the artifact whose timestamp really is the
    # lock time, so a surviving pointer now puts the grant out of scope.
    f9_dir = os.path.join(tmp, "f9-stop")
    f9_home = os.path.join(tmp, "f9-stop-home")
    os.makedirs(f9_dir)
    os.makedirs(f9_home)
    f9_repo = os.path.join(tmp, "f9-stop-repo")
    os.makedirs(f9_repo)

    def plant_freshly_locked(directory, tag):
        minted = os.path.join(directory,
                              "claude-commit-grant-sid-%s-8811.json" % tag)
        with open(minted, "w") as handle:
            json.dump({"sid": "sid-" + tag, "task_id": "T-" + tag,
                       "repo_root": f9_repo}, handle)
        age(minted, 1800 + 600)          # minted long ago, then left sitting
        locked = minted + ".lck"
        os.rename(minted, locked)        # locked NOW; rename preserves mtime
        pointer = os.path.join(
            directory, "claude-commit-grant-active-tu-toolu_01%s.json"
            % tag.upper())
        with open(pointer, "w") as handle:
            json.dump({"locked_path": locked, "original_path": minted,
                       "event_key": "tu-toolu_01" + tag.upper(),
                       "tool_use_id": "toolu_01" + tag.upper()}, handle)
        return locked, pointer

    f9_locked, f9_pointer = plant_freshly_locked(f9_dir, "f9peer")
    check("f9_precondition: the freshly locked grant still carries its MINT "
          "mtime, so age alone condemns it",
          time.time() - os.lstat(f9_locked).st_mtime >= 1800
          and time.time() - os.lstat(f9_pointer).st_mtime < 60)

    def run_stop_script(script, sweep_dir, home, sweep_sid):
        try:
            proc = subprocess.run(
                ["bash", str(script)],
                input=json.dumps({"session_id": sweep_sid,
                                  "hook_event_name": "Stop",
                                  "stop_hook_active": False,
                                  "transcript_path": os.path.join(tmp, "f9.jsonl"),
                                  "cwd": tmp}),
                text=True, capture_output=True, timeout=60,
                env=dict(os.environ, CLAUDE_COMMIT_GRANT_SWEEP_DIR=sweep_dir,
                         HOME=home))
            return proc.returncode
        except Exception:
            return "raised"

    rc = run_stop_script(HOOKS_DIR / "stop-cleanup-allowlist.sh", f9_dir,
                         f9_home, "sid-f9-unrelated-sweeper")
    check("f9_stop_sweep_leaves_a_freshly_locked_but_old_mtime_grant_alone "
          "(its fresh pointer is the lock-time evidence)",
          rc == 0 and os.path.exists(f9_locked) and os.path.exists(f9_pointer))

    mutant_script = os.path.join(tmp, "f9-stop-mutant.sh")
    with open(mutant_script, "w") as handle:
        handle.write(stop_text.replace("if real(p) in protected:", "if False:"))
    f9m_dir = os.path.join(tmp, "f9-stop-mutant-dir")
    os.makedirs(f9m_dir)
    f9m_locked, f9m_pointer = plant_freshly_locked(f9m_dir, "f9mut")
    rc = run_stop_script(mutant_script, f9m_dir, f9_home,
                         "sid-f9-unrelated-sweeper")
    check("f9_mutation_stop_sweep: without the lock-time evidence, mint-mtime "
          "age DESTROYS the freshly locked grant",
          rc == 0 and not os.path.exists(f9m_locked))

    # --- The mid-session half, against a REAL long-running commit. A commit that
    # outlives the bound is ordinary (hooks, signing, a large tree), and this
    # reaper fires on every terminal commit event, so an unrelated fast commit
    # used to destroy a slow peer's coordination state. A blocking pre-commit
    # hook produces a genuine `git commit` process to observe.
    base, repo, parent, head = scene(tmp, "f9-live-commit")
    set_env(CLAUDE_SESSION_ID="sid-orchestrator")
    hook_path = os.path.join(repo, ".git", "hooks", "pre-commit")
    with open(hook_path, "w") as handle:
        handle.write("#!/bin/sh\nsleep 120\n")
    os.chmod(hook_path, 0o755)
    with open(os.path.join(repo, "slow.txt"), "w") as handle:
        handle.write("slow\n")
    git(repo, "add", "-A")
    slow_proc = subprocess.Popen(
        ["git", "commit", "-m", "slow"], cwd=repo, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 30
        observed = False
        while time.time() < deadline:
            live = PT._live_commit_repos()
            if live is not None and os.path.realpath(repo) in live:
                observed = True
                break
            time.sleep(0.05)
        check("f9_precondition: a real long-running git commit is observable "
              "in this repository", observed)
        slow = mint(base, "tu-toolu_01F9SLOW", "T-F9SLOW", repo, parent,
                    sid="sid-f9-slow")
        age(slow["pointer"], PT._POINTER_STALE_SECONDS + 600)
        age(slow["locked"], PT._POINTER_STALE_SECONDS + 900)
        finalize("tu-toolu_01F9RUNNER", "sid-x", "success")
        check("f9_mid_session_reaper_leaves_a_running_commits_state_alone "
              "(over-age on both artifacts, still out of scope)",
              life(slow) == UNTOUCHED)

        # The Stop half of the same liveness rule, by execution: a running
        # commit's locked grant survives even when the SWEEPING session owns it.
        f9_live_dir = os.path.join(tmp, "f9-live-sweep")
        os.makedirs(f9_live_dir)
        own_sid = "sid-f9-live-own"
        live_lck = os.path.join(
            f9_live_dir, "claude-commit-grant-%s-9922.json.lck" % own_sid)
        with open(live_lck, "w") as handle:
            json.dump({"sid": own_sid, "task_id": "T-F9LIVE",
                       "repo_root": repo}, handle)
        rc = run_stop_script(HOOKS_DIR / "stop-cleanup-allowlist.sh",
                             f9_live_dir, f9_home, own_sid)
        check("f9_stop_sweep_leaves_a_running_commits_grant_alone_even_when_owned",
              rc == 0 and os.path.exists(live_lck))
        live_mutant = os.path.join(tmp, "f9-live-mutant.sh")
        with open(live_mutant, "w") as handle:
            handle.write(stop_text.replace("if repo_is_committing(",
                                           "if False and repo_is_committing("))
        rc = run_stop_script(live_mutant, f9_live_dir, f9_home, own_sid)
        check("f9_mutation_stop_liveness: without the liveness gate the running "
              "commit's grant is destroyed",
              rc == 0 and not os.path.exists(live_lck))

        saved_gate = PT._repo_is_committing
        PT._repo_is_committing = lambda repo_root, live_repos: False
        try:
            finalize("tu-toolu_01F9RUNNER", "sid-x", "success")
        finally:
            PT._repo_is_committing = saved_gate
        check("f9_mutation_mid_session: age-only reaping DESTROYS the running "
              "commit's pointer and grant",
              life(slow) == {"locked": False, "original": False,
                             "pointer": False})
    finally:
        try:
            os.killpg(os.getpgid(slow_proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            slow_proc.wait(timeout=30)
        except Exception:
            pass

    # ...and once no commit is running there, genuinely orphaned artifacts are
    # still reaped: the bound survives as a backstop, it just stopped being the
    # whole case.
    deadline = time.time() + 30
    quiet = False
    while time.time() < deadline:
        live = PT._live_commit_repos()
        if live is not None and os.path.realpath(repo) not in live:
            quiet = True
            break
        time.sleep(0.05)
    check("f9_precondition: the long-running commit is gone from the process "
          "table", quiet)
    orphan = mint(base, "tu-toolu_01F9ORPH", "T-F9ORPH", repo, parent,
                  sid="sid-f9-orph")
    age(orphan["pointer"], PT._POINTER_STALE_SECONDS + 600)
    age(orphan["locked"], PT._POINTER_STALE_SECONDS + 900)
    finalize("tu-toolu_01F9RUNNER3", "sid-x", "success")
    check("f9_genuinely_orphaned_artifacts_are_still_reaped_once_nothing_runs",
          life(orphan) == {"locked": False, "original": False, "pointer": False})

    print("\n%d/%d passed" % (len(CHECKS) - len(FAILURES), len(CHECKS)))
    return 1 if FAILURES else 0


def main():
    # PT, GUARD and CJ are shared interpreter state, and the pointer namespace these hooks
    # scan is a single shared /tmp namespace holding OTHER sessions' in-flight commit grants.
    # Both the module attributes and the environment are therefore redirected for the run and
    # restored in a finally block, so a raise anywhere above cannot leak the test's pointer
    # directory into a later test item or, worse, leave this process scanning real /tmp. The
    # GUARD template is redirected for exactly the same reason: this file drives the real
    # writer, and an un-redirected writer would plant pointers in the live namespace.
    del CHECKS[:]
    del FAILURES[:]
    saved = {
        "journal_root": CJ.JOURNAL_ROOT,
        "template": PT._COMMIT_GRANT_POINTER_TEMPLATE,
        "glob": PT._COMMIT_GRANT_POINTER_GLOB,
        "guard_template": GUARD._COMMIT_GRANT_ACTIVE_TEMPLATE,
        "sentinel_dir": AL.SENTINEL_GRANT_DIR,
        "wcg_glob": WCG.COMMIT_GRANT_POINTER_GLOB,
    }
    saved_env = {key: os.environ.pop(key, None)
                 for key in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID",
                             "CLAUDE_TASK_ID")}
    try:
        # Checked on the REAL templates, before either is redirected: the whole binding is
        # worthless if the writer and the reader name different files.
        if saved["template"] != saved["guard_template"]:
            print("FAIL  guard and finalizer share one pointer path template")
            FAILURES.append("guard and finalizer share one pointer path template")
            return 1
        # Same identity for the revoker (audit R2-4): revocation enumerates the
        # pointer namespace by glob, so its glob must match what the guard writes.
        if not fnmatch.fnmatch(saved["guard_template"].format(sid="tu-x"),
                               saved["wcg_glob"]):
            print("FAIL  revoker glob matches the guard's real pointer names")
            FAILURES.append("revoker glob matches the guard's real pointer names")
            return 1
        with tempfile.TemporaryDirectory(prefix="posttool-finalize-test-") as tmp:
            pointers = os.path.join(tmp, "pointers")
            os.makedirs(pointers)
            redirected = os.path.join(pointers, "claude-commit-grant-active-{sid}.json")
            PT._COMMIT_GRANT_POINTER_TEMPLATE = redirected
            PT._COMMIT_GRANT_POINTER_GLOB = os.path.join(
                pointers, "claude-commit-grant-active-*.json")
            GUARD._COMMIT_GRANT_ACTIVE_TEMPLATE = redirected
            WCG.COMMIT_GRANT_POINTER_GLOB = PT._COMMIT_GRANT_POINTER_GLOB
            # The payload-seam scenarios run the REAL main(), whose sentinel-consume
            # path scans the shared /tmp/claude-grants namespace; redirect it for the
            # same reason the pointer namespace is redirected.
            sentinels = os.path.join(tmp, "sentinel-grants")
            os.makedirs(sentinels)
            AL.SENTINEL_GRANT_DIR = sentinels
            return _run(tmp)
    finally:
        CJ.JOURNAL_ROOT = saved["journal_root"]
        PT._COMMIT_GRANT_POINTER_TEMPLATE = saved["template"]
        PT._COMMIT_GRANT_POINTER_GLOB = saved["glob"]
        GUARD._COMMIT_GRANT_ACTIVE_TEMPLATE = saved["guard_template"]
        AL.SENTINEL_GRANT_DIR = saved["sentinel_dir"]
        WCG.COMMIT_GRANT_POINTER_GLOB = saved["wcg_glob"]
        # Pop unconditionally BEFORE restoring: the scenarios above SET these variables, so a
        # restore that only wrote back non-None values would leak a test sid into the
        # interpreter whenever the variable was originally unset — and the very next reader of
        # this environment is a hook that resolves real commit grants from it.
        for key, value in saved_env.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value


def test_posttool_commit_grant_finalize():
    """Collected by the hooks/tests pytest run.

    Without this the module is importable but contributes no test items, so the
    binding checks would not execute as part of the suite at all.
    """
    assert main() == 0, "failed checks: %s" % (FAILURES,)


if __name__ == "__main__":
    sys.exit(main())
