#!/usr/bin/env python3
"""Adversarial tests for hooks/lib/commit_journal.py — the push-gate reconciliation
attribution basis.

These exercise the two failure modes that sank the previous attribution design
(`Task-id:` trailer matching and file-set intersection), both of which read content the
committing actor chose:

  - a CONCURRENT PEER's commit must never be attributable to this session (test_peer_*)
  - a FAN-OUT LANE whose task id is a prefix-extension of its parent's must never be
    attributable to the parent (test_prefix_*) — the exact relationship this repository's
    dev-registry creates by construction
  - a HEAD RACE must never mint a token (test_head_race_*): the appending hook reads live
    HEAD after the commit lock is already released, so a peer commit landing in that window
    is journaled under this session's ids, and the entry's recorded parent then belongs to
    a different commit than its recorded sha
  - OBJECT SUBSTITUTION must not move the linkage answer in either direction
    (test_replace_ref_*, test_graft_file_*): refs/replace/* and .git/info/grafts make git
    report a first parent the commit object does not record, which under a parsing read
    both breaks true linkages and forges raced ones
  - a COMMIT-TYPED FORGERY must not verify (test_commit_typed_*): `cat-file commit`
    checks the stored type, not the structure, so an object minted with
    `hash-object -t commit --literally` needs only a plausible `parent` line to fool a
    naive header scan — structural validity is required before any parent is extracted,
    and the raw read must stay bounded to the header so an actor-sized message cannot
    deny reconciliation (test_large_message_*)

Plus the fail-open contract: no input may make the journal raise, because it is written
from a PostToolUse hook that runs after the commit has already landed.

Run: python3 hooks/tests/test_commit_journal.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import lib.commit_journal as CJ  # noqa: E402

CHECKS = []
FAILURES = []


def check(name, condition):
    # CHECKS is appended to by every executed check, so the summary line below counts
    # what actually ran. Do NOT reintroduce a hardcoded total: a literal cannot notice
    # a check being deleted or short-circuited, and the exit status is computed from
    # FAILURES independently, so a stale total would misreport coverage silently.
    CHECKS.append(name)
    print(("PASS  " if condition else "FAIL  ") + name)
    if not condition:
        FAILURES.append(name)


def make_repo(parent, name):
    root = os.path.join(parent, name)
    os.makedirs(root)
    for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                 ["config", "user.name", "test"]):
        subprocess.run(["git", "-C", root] + args, check=True, capture_output=True)
    return root


def make_commit(root, message):
    with open(os.path.join(root, "f.txt"), "a") as handle:
        handle.write(message + "\n")
    subprocess.run(["git", "-C", root, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", root, "commit", "-q", "-m", message],
                   check=True, capture_output=True)
    return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def head_of(root):
    """Current HEAD sha, or '' when the repository has no commits yet."""
    result = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def grant(task_id, repo_root, sid="grant-sid", parent="p"):
    # `parent` becomes the entry's parent_head, which the matcher now checks against the
    # ACTUAL first parent of the resulting sha. The "p" default is therefore an
    # unverifiable parent on purpose: it is only ever used by entries no check attributes,
    # so any test that starts relying on the default fails loudly instead of silently
    # passing on a linkage that was never real.
    return {"task_id": task_id, "sid": sid, "repo_root": repo_root,
            "branch": "master", "expected_head": parent}


def _run(tmp):
    CJ.JOURNAL_ROOT = os.path.join(tmp, "commit-events")
    repo_a = make_repo(tmp, "repoA")
    repo_b = make_repo(tmp, "repoB")

    # A root commit has no first parent, so its linkage can never be verified and it is
    # unattributable by construction. Every repository therefore gets a base commit that
    # no test journals, and the root case is asserted explicitly further down.
    base_a = make_commit(repo_a, "chore: base")

    # Baseline — a grant-authorized commit is journaled and attributable by either the
    # payload session id or the grant's own sid (orchestrator/subagent divergence).
    sha1 = make_commit(repo_a, "feat: real work")
    entry = CJ.append_commit_event(
        grant("T-A", repo_a, sid="sid-orch", parent=base_a), "sid-subagent")
    check("entry written with the observed resulting head",
          entry is not None and entry["resulting_head"] == sha1)
    check("attributable by payload session id",
          CJ.find_attributable_event(repo_a, sha1, "T-A", "sid-subagent") is not None)
    check("attributable by grant sid (orchestrator/subagent divergence)",
          CJ.find_attributable_event(repo_a, sha1, "T-A", "sid-orch") is not None)

    # THREAT — a concurrent peer session's commit.
    sha2 = make_commit(repo_a, "feat: peer work")
    CJ.append_commit_event(grant("T-B", repo_a, sid="peer-sid", parent=sha1), "peer-sid")
    check("test_peer_commit_not_attributable_to_my_session",
          CJ.find_attributable_event(repo_a, sha2, "T-B", "sid-subagent") is None)
    check("test_peer_commit_not_attributable_under_my_task_id",
          CJ.find_attributable_event(repo_a, sha2, "T-A", "sid-subagent") is None)

    # THREAT — prefix-related fan-out lane ids.
    sha3 = make_commit(repo_a, "feat: lane one")
    CJ.append_commit_event(grant("T-A-lane1", repo_a, sid="sid-subagent", parent=sha2),
                           "sid-subagent")
    check("test_prefix_lane_id_does_not_match_parent_task_id",
          CJ.find_attributable_event(repo_a, sha3, "T-A", "sid-subagent") is None)
    check("test_prefix_lane_id_matches_itself_exactly",
          CJ.find_attributable_event(repo_a, sha3, "T-A-lane1", "sid-subagent") is not None)

    # Freshness bind — `resulting_head` must equal the head being asked about, so an entry
    # that IS attributable while its commit sits at HEAD stops matching once anything is
    # built on top of it. Asked exactly the way reconciliation asks it: about LIVE head,
    # with the entry's OWN task id and session, so the only thing that differs between the
    # two queries is which commit is at HEAD. The first check is the positive control that
    # keeps the second from passing for some unrelated reason; delete the resulting_head
    # comparison in find_attributable_event and the second returns the stale entry, red.
    fresh_parent = head_of(repo_a)
    fresh_sha = make_commit(repo_a, "feat: fresh")
    CJ.append_commit_event(
        grant("T-FRESH", repo_a, sid="fresh-sid", parent=fresh_parent), "fresh-sid")
    check("entry attributes its commit while that commit is HEAD",
          CJ.find_attributable_event(repo_a, head_of(repo_a), "T-FRESH", "fresh-sid")
          is not None and head_of(repo_a) == fresh_sha)
    make_commit(repo_a, "feat: built on top")
    check("superseded commit no longer matches the new HEAD",
          CJ.find_attributable_event(repo_a, head_of(repo_a), "T-FRESH", "fresh-sid")
          is None)

    # A root commit has no first parent, so its linkage cannot be read and it fails closed.
    base_b = make_commit(repo_b, "chore: base")
    CJ.append_commit_event(grant("T-ROOT", repo_b, sid="root-sid", parent=""), "root-sid")
    check("test_root_commit_has_no_parent_so_attributes_nothing",
          CJ.find_attributable_event(repo_b, base_b, "T-ROOT", "root-sid") is None)

    # Repository binding. The positive control on repo_b is what keeps the negative below
    # from passing vacuously: without it, an entry refused for ANY reason would satisfy it.
    sha_b = make_commit(repo_b, "feat: other repo")
    CJ.append_commit_event(grant("T-A", repo_b, sid="sid-subagent", parent=base_b),
                           "sid-subagent")
    check("entry is attributable from its own repository",
          CJ.find_attributable_event(repo_b, sha_b, "T-A", "sid-subagent") is not None)
    check("entry for another repository is not visible from this one",
          CJ.find_attributable_event(repo_a, sha_b, "T-A", "sid-subagent") is None)

    # Degenerate session ids identify nobody and must never attribute.
    parent4 = head_of(repo_a)
    sha4 = make_commit(repo_a, "feat: anonymous")
    saved = {k: os.environ.pop(k, None)
             for k in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID")}
    anonymous = CJ.append_commit_event(
        grant("T-C", repo_a, sid="", parent=parent4), "default")
    for key, value in saved.items():
        if value is not None:
            os.environ[key] = value
    check("test_anonymous_commit_writes_no_entry", anonymous is None)
    check("placeholder session 'default' attributes nothing",
          CJ.find_attributable_event(repo_a, sha4, "T-C", "default") is None)
    check("placeholder session 'unknown' attributes nothing",
          CJ.find_attributable_event(repo_a, sha4, "T-C", "unknown") is None)

    # Fail-open contract.
    try:
        results = [CJ.append_commit_event(None, "s"),
                   CJ.append_commit_event({}, "s"),
                   CJ.append_commit_event({"task_id": "t", "repo_root": "/nope"}, "s")]
        check("malformed grants return None without raising",
              all(r is None for r in results))
    except Exception:
        check("malformed grants return None without raising", False)
    try:
        CJ.find_attributable_event("/nonexistent", "abc", "t", "s")
        check("query against a missing journal does not raise", True)
    except Exception:
        check("query against a missing journal does not raise", False)

    with open(CJ.journal_path(repo_a), "a") as handle:
        handle.write("{ not json\n")
    check("corrupt journal line is skipped, valid entries still found",
          CJ.find_attributable_event(repo_a, sha1, "T-A", "sid-subagent") is not None)

    # Growth bound. MAX_ENTRIES is restored in a finally block, exactly as main() does
    # for JOURNAL_ROOT: CJ is shared interpreter state, and an inline restore on the
    # normal path only would leak the test value into every later test item or repeated
    # invocation if anything between the override and the restore raises.
    original_max = CJ.MAX_ENTRIES
    CJ.MAX_ENTRIES = 5
    try:
        for _ in range(20):
            CJ.append_commit_event(grant("bulk", repo_a, sid="sid-subagent"),
                                   "sid-subagent")
        line_count = sum(1 for _ in open(CJ.journal_path(repo_a)))
        check("journal is pruned to MAX_ENTRIES", line_count <= 5)
    finally:
        CJ.MAX_ENTRIES = original_max

    # THREAT — the HEAD race that produces a FALSE attribution. The fd-9 commit lock is
    # released when the committing shell call exits; the PostToolUse hook that appends the
    # entry reads live HEAD only afterwards. A peer commit landing in that window is what
    # the hook observes, so this session journals the PEER's sha under its OWN task id and
    # session ids — while parent_head still holds its own grant's pre-commit head. The
    # entry is therefore internally inconsistent: its recorded parent is not the actual
    # first parent of the sha it claims. Reconciliation would have minted this session's
    # push-gate token for the peer's commit.
    #
    # Reproduced literally: append_commit_event reads live HEAD itself, so committing the
    # peer's commit before calling it produces the raced entry with no faking.
    race_grant_head = head_of(repo_a)                       # what MY grant pinned
    make_commit(repo_a, "feat: my own commit")              # my commit, on that parent
    peer_sha = make_commit(repo_a, "feat: peer wins the race")   # peer lands on top
    raced = CJ.append_commit_event(
        grant("T-RACE", repo_a, sid="race-sid", parent=race_grant_head), "race-sid")
    check("race entry records the peer's sha (the hook cannot see the race)",
          raced is not None and raced["resulting_head"] == peer_sha
          and raced["parent_head"] == race_grant_head)
    check("test_head_race_entry_mints_no_token",
          CJ.find_attributable_event(repo_a, peer_sha, "T-RACE", "race-sid") is None)

    # Control — same task, same session, same shape, no race: linkage holds and the entry
    # still attributes. Without this the check above would pass if attribution broke
    # outright.
    ordinary_parent = head_of(repo_a)
    ordinary_sha = make_commit(repo_a, "feat: ordinary, unraced")
    CJ.append_commit_event(
        grant("T-OK", repo_a, sid="ok-sid", parent=ordinary_parent), "ok-sid")
    check("test_unraced_entry_still_attributes",
          CJ.find_attributable_event(repo_a, ordinary_sha, "T-OK", "ok-sid") is not None)

    # An entry naming a commit this repository does not contain has no readable linkage,
    # so it fails closed rather than attributing on its self-declared parent.
    forged = {"schema": CJ.SCHEMA, "event": "commit", "task_id": "T-FORGED",
              "repo_root": repo_a, "branch": "master",
              "parent_head": ordinary_parent, "resulting_head": "0" * 40,
              "session_ids": ["forged-sid"], "created_at": "2026-01-01T00:00:00+00:00"}
    with open(CJ.journal_path(repo_a), "a") as handle:
        handle.write(json.dumps(forged, sort_keys=True) + "\n")
    check("test_unknown_commit_attributes_nothing",
          CJ.find_attributable_event(repo_a, "0" * 40, "T-FORGED", "forged-sid") is None)

    # Guards that nothing above reaches. Found by deleting each refusal in the module one
    # at a time and re-running: these four left the suite entirely green, which is the same
    # defect shape as a check asserting something it never exercises. Every synthetic entry
    # here is given a REAL linkage and a real session id, so the only thing that can refuse
    # it is the guard it is aimed at.
    def journal_line(fields):
        record = {"schema": CJ.SCHEMA, "event": "commit", "branch": "master",
                  "repo_root": repo_a, "parent_head": ordinary_parent,
                  "resulting_head": ordinary_sha,
                  "created_at": "2026-01-01T00:00:00+00:00"}
        record.update(fields)
        with open(CJ.journal_path(repo_a), "a") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    journal_line({"schema": "commit-event/999", "task_id": "T-SCHEMA",
                  "session_ids": ["schema-sid"]})
    check("entry written under another schema version attributes nothing",
          CJ.find_attributable_event(repo_a, ordinary_sha, "T-SCHEMA", "schema-sid")
          is None)

    # The EVENT half of the schema/event guard gets its own discriminating case: correct
    # schema, real linkage, real session id, wrong event. Every other check passes this
    # line, so only `entry.get("event") != "commit"` can refuse it — the line above
    # cannot stand in, because the schema half already refuses that one. Found the same
    # way as the rest of this block: deleting only the event-equality comparison left the
    # suite entirely green until this check existed.
    journal_line({"task_id": "T-EVENT", "session_ids": ["event-sid"],
                  "event": "amend"})
    check("a non-commit event under the current schema attributes nothing",
          CJ.find_attributable_event(repo_a, ordinary_sha, "T-EVENT", "event-sid")
          is None)

    # Pins the PAIR of degenerate-session refusals (the caller-side check and the
    # _identifying filter), which are independently redundant: removing either alone still
    # refuses, so only removing both turns this red.
    journal_line({"task_id": "T-DEGEN", "session_ids": ["default", "unknown"]})
    check("recorded placeholder session ids attribute nothing despite a real linkage",
          CJ.find_attributable_event(repo_a, ordinary_sha, "T-DEGEN", "default") is None
          and CJ.find_attributable_event(repo_a, ordinary_sha, "T-DEGEN", "unknown")
          is None)

    # The journal file is keyed by repo hash, so no test above could reach the in-entry
    # repo_root binding — nothing guards /tmp/agentic-commit/**, so an entry for another
    # repository landing in THIS file is exactly what that binding is for.
    journal_line({"task_id": "T-CROSS", "session_ids": ["cross-sid"],
                  "repo_root": repo_b, "parent_head": base_b, "resulting_head": sha_b})
    check("entry naming another repository attributes nothing from this journal file",
          CJ.find_attributable_event(repo_a, sha_b, "T-CROSS", "cross-sid") is None)

    # A recorded head must be a literal object name: without that guard the parent read
    # would resolve this as a revision expression and hand back a real, matching parent.
    journal_line({"task_id": "T-EXPR", "session_ids": ["expr-sid"],
                  "resulting_head": "HEAD"})
    check("a revision expression as resulting_head is never resolved",
          head_of(repo_a) == ordinary_sha
          and CJ.find_attributable_event(repo_a, "HEAD", "T-EXPR", "expr-sid") is None)

    # THREAT — OBJECT SUBSTITUTION. refs/replace/* and the deprecated-but-still-honoured
    # .git/info/grafts file both make git report a first parent the commit object does not
    # record, and both are writable by anyone who can write in the repository. Under a
    # parsing read (`rev-parse <sha>^1`) this moves attribution in BOTH directions, so both
    # are asserted: a TRUE linkage must not become unverifiable, and a RACED linkage must
    # not become verifiable. Given its own repository so the substitution cannot perturb
    # any other check, and the substitution is proved live before each pair so neither pair
    # can pass vacuously by simply not being in effect.
    repo_c = make_repo(tmp, "repoC")
    c0 = make_commit(repo_c, "chore: base")
    c1 = make_commit(repo_c, "feat: the true first parent")
    c2 = make_commit(repo_c, "feat: the subject commit")
    # T-SUB records c2's real parent. T-LIE is the raced shape: its grant pinned c0, a peer
    # landed c1, and the hook observed c2 — a recorded parent belonging to another commit.
    CJ.append_commit_event(grant("T-SUB", repo_c, sid="sub-sid", parent=c1), "sub-sid")
    CJ.append_commit_event(grant("T-LIE", repo_c, sid="lie-sid", parent=c0), "lie-sid")
    check("substitution baseline: true linkage attributes, raced linkage does not",
          CJ.find_attributable_event(repo_c, c2, "T-SUB", "sub-sid") is not None
          and CJ.find_attributable_event(repo_c, c2, "T-LIE", "lie-sid") is None)

    subprocess.run(["git", "-C", repo_c, "replace", "--graft", c2, c0],
                   check=True, capture_output=True)
    substituted = subprocess.run(
        ["git", "-C", repo_c, "rev-parse", "--verify", "--quiet", c2 + "^1"],
        capture_output=True, text=True).stdout.strip()
    check("replace ref really does move the parsed first parent to c0",
          c0 != c1 and substituted == c0)
    check("test_replace_ref_cannot_break_a_true_linkage",
          CJ.find_attributable_event(repo_c, c2, "T-SUB", "sub-sid") is not None)
    check("test_replace_ref_cannot_forge_a_raced_linkage",
          CJ.find_attributable_event(repo_c, c2, "T-LIE", "lie-sid") is None)

    subprocess.run(["git", "-C", repo_c, "replace", "-d", c2],
                   check=True, capture_output=True)
    os.makedirs(os.path.join(repo_c, ".git", "info"), exist_ok=True)
    with open(os.path.join(repo_c, ".git", "info", "grafts"), "w") as handle:
        handle.write("%s %s\n" % (c2, c0))
    grafted = subprocess.run(
        ["git", "-C", repo_c, "--no-replace-objects", "rev-parse", "--verify", "--quiet",
         c2 + "^1"], capture_output=True, text=True).stdout.strip()
    # Pins WHY the fix reads the raw object rather than merely disabling replacement:
    # grafts are imposed at parse time, so --no-replace-objects alone does not escape them.
    check("grafts move the parsed parent even under --no-replace-objects",
          grafted == c0)
    check("test_graft_file_cannot_break_a_true_linkage",
          CJ.find_attributable_event(repo_c, c2, "T-SUB", "sub-sid") is not None)
    check("test_graft_file_cannot_forge_a_raced_linkage",
          CJ.find_attributable_event(repo_c, c2, "T-LIE", "lie-sid") is None)

    # THREAT — an object TYPED commit that is not structurally a commit. `cat-file
    # commit` checks only the stored type, and `hash-object -t commit --literally`
    # stores arbitrary bytes under it, so a naive scan for the first `parent`-looking
    # line hands such an object a VERIFIED linkage the old parsing read refused. Both
    # required-header halves of the validator are pinned separately: an object with no
    # `tree` at all, and one whose tree/parent lines are well-formed but which names no
    # author or committer. Each records a REAL parent sha, so linkage comparison alone
    # cannot refuse them — only structural validation can.
    def mint_literal_commit(content):
        return subprocess.run(
            ["git", "-C", repo_a, "hash-object", "-t", "commit", "-w", "--literally",
             "--stdin"],
            input=content, capture_output=True, text=True, check=True).stdout.strip()

    headless = mint_literal_commit("parent %s\n\nnot a commit\n" % ordinary_parent)
    journal_line({"task_id": "T-MALFORMED", "session_ids": ["mal-sid"],
                  "resulting_head": headless})
    check("test_commit_typed_garbage_without_tree_is_unverifiable",
          CJ.find_attributable_event(repo_a, headless, "T-MALFORMED", "mal-sid")
          is None)

    identless = mint_literal_commit(
        "tree %s\nparent %s\n\nno idents\n" % ("0" * 40, ordinary_parent))
    journal_line({"task_id": "T-IDENTLESS", "session_ids": ["ident-sid"],
                  "resulting_head": identless})
    check("test_commit_typed_object_without_idents_is_unverifiable",
          CJ.find_attributable_event(repo_a, identless, "T-IDENTLESS", "ident-sid")
          is None)

    # Each structural refusal in the validator additionally gets a fixture whose ONLY
    # defect is the element that refusal guards. Found by deleting each refusal one at
    # a time and re-running: all four deletions left the suite green, because the two
    # objects above have OVERLAPPING defects, so a neighbouring check refused them
    # anyway. Each fixture below is canonical everywhere else and records the REAL
    # parent, so under its targeted deletion that parent IS extracted, linkage
    # verifies, and exactly this check turns red — nothing but the aimed-at refusal
    # can refuse it.
    ident = "a <a@example.invalid> 1700000000 +0000"
    no_tree = mint_literal_commit(
        "notree %s\nparent %s\nauthor %s\ncommitter %s\n\nforged\n"
        % ("0" * 40, ordinary_parent, ident, ident))
    journal_line({"task_id": "T-NO-TREE", "session_ids": ["notree-sid"],
                  "resulting_head": no_tree})
    check("test_sole_defect_missing_tree_line_is_unverifiable",
          CJ.find_attributable_event(repo_a, no_tree, "T-NO-TREE", "notree-sid")
          is None)

    no_author = mint_literal_commit(
        "tree %s\nparent %s\nnoauthor %s\ncommitter %s\n\nforged\n"
        % ("0" * 40, ordinary_parent, ident, ident))
    journal_line({"task_id": "T-NO-AUTHOR", "session_ids": ["noauthor-sid"],
                  "resulting_head": no_author})
    check("test_sole_defect_missing_author_line_is_unverifiable",
          CJ.find_attributable_event(repo_a, no_author, "T-NO-AUTHOR", "noauthor-sid")
          is None)

    no_committer = mint_literal_commit(
        "tree %s\nparent %s\nauthor %s\nnocommitter %s\n\nforged\n"
        % ("0" * 40, ordinary_parent, ident, ident))
    journal_line({"task_id": "T-NO-COMMITTER", "session_ids": ["nocommitter-sid"],
                  "resulting_head": no_committer})
    check("test_sole_defect_missing_committer_line_is_unverifiable",
          CJ.find_attributable_event(
              repo_a, no_committer, "T-NO-COMMITTER", "nocommitter-sid") is None)

    stray_late = mint_literal_commit(
        "tree %s\nparent %s\nauthor %s\ncommitter %s\nparent %s\n\nforged\n"
        % ("0" * 40, ordinary_parent, ident, ident, "f" * 40))
    journal_line({"task_id": "T-STRAY", "session_ids": ["stray-sid"],
                  "resulting_head": stray_late})
    check("test_sole_defect_stray_parent_after_idents_is_unverifiable",
          CJ.find_attributable_event(repo_a, stray_late, "T-STRAY", "stray-sid")
          is None)

    # The parent line's PAYLOAD must be an object name too, and this is the one structural
    # refusal whose fixture cannot record a real parent: the point is that the recorded
    # parent is the same non-sha the object carries, so the two sides agree and only the
    # oid check refuses. Delete it and the garbage is returned as the first parent, the
    # comparison matches it exactly, and the entry verifies.
    bad_oid = mint_literal_commit(
        "tree %s\nparent %s\nauthor %s\ncommitter %s\n\nforged\n"
        % ("0" * 40, "z" * 40, ident, ident))
    journal_line({"task_id": "T-BAD-OID", "session_ids": ["badoid-sid"],
                  "parent_head": "z" * 40, "resulting_head": bad_oid})
    check("test_sole_defect_non_oid_parent_payload_is_unverifiable",
          CJ.find_attributable_event(repo_a, bad_oid, "T-BAD-OID", "badoid-sid") is None)

    # TRUNCATION AMBIGUITY (R2-8). A bounded read cannot tell "the header ended" from "the
    # header had not ended when the bound stopped me", so it fails closed on both: only a
    # header the read saw TERMINATE is honoured. An object with no blank line at all is the
    # reachable form of that ambiguity, and it is canonical in every other respect and
    # records the REAL parent — so with the terminator requirement deleted the header is
    # returned anyway, validates, and mints a linkage for an object git never wrote.
    unterminated = mint_literal_commit(
        "tree %s\nparent %s\nauthor %s\ncommitter %s\n"
        % ("0" * 40, ordinary_parent, ident, ident))
    journal_line({"task_id": "T-UNTERM", "session_ids": ["unterm-sid"],
                  "resulting_head": unterminated})
    check("test_unterminated_header_is_unverifiable_not_guessed",
          CJ.find_attributable_event(repo_a, unterminated, "T-UNTERM", "unterm-sid")
          is None)

    # Control — with the minted garbage objects now sitting in the store, a well-formed
    # commit still verifies through the same validator. Without this, the refusals
    # above would also pass under a validator that refuses everything.
    check("well-formed commit still verifies beside the minted garbage",
          CJ.find_attributable_event(repo_a, ordinary_sha, "T-OK", "ok-sid")
          is not None)

    # BOUND — the header read must not buffer the message, whose size the committing
    # actor chooses. An 8 MiB message would have been slurped whole by the old
    # whole-object read; the bounded read stops at the header terminator, so the commit
    # stays verifiable and the bytes actually retained stay under the documented cap.
    # The duration is measured and printed, not asserted: wall time is load-dependent,
    # while the byte bound is deterministic.
    big_parent = head_of(repo_a)
    message_path = os.path.join(tmp, "big-message.txt")
    with open(message_path, "w") as handle:
        handle.write("feat: enormous message\n\n" + "x" * (8 * 1024 * 1024))
    with open(os.path.join(repo_a, "f.txt"), "a") as handle:
        handle.write("big\n")
    subprocess.run(["git", "-C", repo_a, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo_a, "commit", "-q", "-F", message_path],
                   check=True, capture_output=True)
    big_sha = head_of(repo_a)
    CJ.append_commit_event(
        grant("T-BIG", repo_a, sid="big-sid", parent=big_parent), "big-sid")
    started = time.monotonic()
    big_hit = CJ.find_attributable_event(repo_a, big_sha, "T-BIG", "big-sid")
    elapsed = time.monotonic() - started
    big_header = CJ._read_commit_header(repo_a, big_sha)
    check("test_large_message_commit_still_verifies", big_hit is not None)
    check("header read of the large commit stays within its byte bound",
          big_header is not None and len(big_header) <= CJ._HEADER_CAP)
    print("      (large-message attribution: %.3fs; header retained %d bytes of an"
          " 8 MiB object, cap %d)"
          % (elapsed, len(big_header or b""), CJ._HEADER_CAP))

    # BOUND, part two — the byte-bound check above inspects only the RETURNED value,
    # which a whole-object read that buffers everything and slices at the first blank
    # line reproduces byte-for-byte, silently discarding the memory/deadline
    # protection. Boundedness is therefore pinned deterministically at the pipe: a
    # `git` stand-in on PATH emits a canonical header, then must push a 4 MiB body
    # through the pipe before it may record `body-fully-drained` (`|| exit 1` keeps a
    # SIGPIPE'd dd from reaching the marker). The streaming reader stops consuming at
    # the header terminator and reaps the child, so at most one read chunk plus the
    # kernel pipe buffer (~72 KiB of the 4 MiB) can ever drain and the marker cannot
    # appear; a whole-object read drains to EOF and it does. No wall clock is
    # consulted, so this cannot flake under load. The header equality is the
    # non-vacuity control: it proves the stand-in (not real git) answered and that
    # the reader still returned the right bytes through it.
    shim_dir = os.path.join(tmp, "git-shim")
    probe_dir = os.path.join(tmp, "probe")
    os.makedirs(shim_dir)
    os.makedirs(probe_dir)
    shim_header = ("tree %s\nparent %s\nauthor %s\ncommitter %s"
                   % ("0" * 40, "1" * 40, ident, ident)).encode()
    with open(os.path.join(probe_dir, "header-bytes"), "wb") as handle:
        handle.write(shim_header + b"\n\n")
    drained_marker = os.path.join(probe_dir, "body-fully-drained")
    with open(os.path.join(shim_dir, "git"), "w") as handle:
        handle.write("#!/bin/sh\ncat '%s'\n"
                     "dd if=/dev/zero bs=65536 count=64 2>/dev/null || exit 1\n"
                     ": > '%s'\n"
                     % (os.path.join(probe_dir, "header-bytes"), drained_marker))
    os.chmod(os.path.join(shim_dir, "git"), 0o755)
    saved_path = os.environ.get("PATH", "")
    os.environ["PATH"] = shim_dir + os.pathsep + saved_path
    try:
        probed = CJ._read_commit_header(repo_a, "e" * 40)
    finally:
        os.environ["PATH"] = saved_path
    check("test_bounded_read_never_drains_the_object_body",
          probed == shim_header and not os.path.exists(drained_marker))

    # The two bounds the check above does NOT reach, each pinned the same marker-based way
    # and with no wall clock consulted. Both stand-ins emit an UNTERMINATED header, so the
    # reader returns None either way and the return value cannot distinguish them; the
    # marker each script writes only if it ran to completion is the whole observable.
    def stand_in(name, script):
        directory = os.path.join(tmp, name)
        os.makedirs(directory)
        with open(os.path.join(directory, "git"), "w") as handle:
            handle.write("#!/bin/sh\n" + script)
        os.chmod(os.path.join(directory, "git"), 0o755)
        return directory

    def through(directory, deadline=None):
        saved_deadline = CJ._HEADER_DEADLINE
        saved = os.environ.get("PATH", "")
        os.environ["PATH"] = directory + os.pathsep + saved
        if deadline is not None:
            CJ._HEADER_DEADLINE = deadline
        try:
            return CJ._read_commit_header(repo_a, "e" * 40)
        finally:
            os.environ["PATH"] = saved
            CJ._HEADER_DEADLINE = saved_deadline

    # _HEADER_CAP. Every other fixture terminates its header, so the loop always exits on
    # the terminator and the cap is never the thing that stops it — delete `len(buffer) <
    # _HEADER_CAP` from the loop condition and nothing else notices. Here 2 MiB arrives with
    # no terminator: the capped reader stops at 64 KiB and reaps the child while dd is still
    # blocked on a full pipe, so `|| exit 1` keeps the marker unwritten; an uncapped one
    # drains to EOF and writes it.
    cap_marker = os.path.join(probe_dir, "unterminated-stream-drained")
    cap_shim = stand_in("git-shim-cap",
                        "printf 'tree " + "0" * 40 + "\\n'\n"
                        "dd if=/dev/zero bs=65536 count=32 2>/dev/null || exit 1\n"
                        ": > '" + cap_marker + "'\n")
    check("test_header_cap_stops_an_unterminated_stream",
          through(cap_shim) is None and not os.path.exists(cap_marker))

    # _HEADER_DEADLINE. Its two refusals — the expired-remaining return and the
    # select()-timeout return — are MUTUALLY REDUNDANT, so no fixture can turn either alone
    # red; what is pinned here is the PAIR, i.e. that the read is bounded in time at all.
    # The stand-in emits a fragment and then stalls: the deadline returns while it is still
    # sleeping, so its trailing marker cannot exist. With both refusals gone the reader
    # blocks until the child exits and the marker appears. The deadline is shortened for the
    # call and restored in a finally, exactly as MAX_ENTRIES and JOURNAL_ROOT are.
    stall_marker = os.path.join(probe_dir, "stalled-child-ran-to-completion")
    stall_shim = stand_in("git-shim-stall",
                          "printf 'tree " + "0" * 40 + "\\n'\n"
                          "sleep 10\n"
                          ": > '" + stall_marker + "'\n")
    check("test_header_deadline_returns_before_a_stalled_child_finishes",
          through(stall_shim, deadline=0.25) is None
          and not os.path.exists(stall_marker))

    # CLI contract consumed by changelog-analyst: exit 0 + JSON on match, exit 1 on miss.
    cli_parent = head_of(repo_a)
    sha5 = make_commit(repo_a, "feat: cli")
    CJ.append_commit_event(
        grant("cli-task", repo_a, sid="cli-sid", parent=cli_parent), "cli-sid")
    bootstrap = (
        "import sys; sys.path.insert(0, %r); import lib.commit_journal as C; "
        "C.JOURNAL_ROOT = %r; sys.exit(C._main(sys.argv))"
        % (str(HOOKS_DIR), CJ.JOURNAL_ROOT)
    )
    base = [sys.executable, "-c", bootstrap, "query", "--repo-root", repo_a,
            "--head", sha5, "--task-id", "cli-task", "--session-id"]
    hit = subprocess.run(base + ["cli-sid"], capture_output=True, text=True)
    check("CLI exits 0 and prints the entry on a match",
          hit.returncode == 0 and json.loads(hit.stdout)["task_id"] == "cli-task")
    miss = subprocess.run(base + ["other-sid"], capture_output=True, text=True)
    check("CLI exits 1 and prints nothing on a miss",
          miss.returncode == 1 and miss.stdout.strip() == "")

    # Route coverage. The CLI is the route agents/changelog-analyst.md actually invokes to
    # decide reconciliation, so the linkage bind is demonstrated THROUGH it by execution
    # rather than inferred from the fact that it delegates. The passing match above is its
    # positive control: the same route still returns an unraced entry.
    raced_cli = subprocess.run(
        [sys.executable, "-c", bootstrap, "query", "--repo-root", repo_a,
         "--head", peer_sha, "--task-id", "T-RACE", "--session-id", "race-sid"],
        capture_output=True, text=True)
    check("CLI route refuses the race entry as well (exit 1, nothing printed)",
          raced_cli.returncode == 1 and raced_cli.stdout.strip() == "")

    print("\n%d/%d passed" % (len(CHECKS) - len(FAILURES), len(CHECKS)))
    return 1 if FAILURES else 0


def main():
    # TemporaryDirectory, not mkdtemp: this builds two git repositories per run, and the
    # bare mkdtemp form leaked both on every invocation. Module state is saved and
    # restored so the pytest entry point below can run in a shared interpreter.
    del CHECKS[:]
    del FAILURES[:]
    saved_root = CJ.JOURNAL_ROOT
    try:
        with tempfile.TemporaryDirectory(prefix="commit-journal-test-") as tmp:
            return _run(tmp)
    finally:
        CJ.JOURNAL_ROOT = saved_root


def test_commit_journal_adversarial():
    """Collected by the hooks/tests pytest run.

    Without this the module is importable but contributes no test items, so the
    adversarial checks would not execute as part of the suite at all.
    """
    assert main() == 0, "failed checks: %s" % (FAILURES,)


if __name__ == "__main__":
    sys.exit(main())
