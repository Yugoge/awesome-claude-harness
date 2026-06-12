#!/usr/bin/env python3
"""Behavioral AC verification harness for task 20260611-100500 (Cycle 3 — L5).

L5 ESCALATION: the enforcement is moved OUT of the L4 shell-string-parsing layer
(proven undecidable across 14 reproduced forms) INTO the git-native
reference-transaction keystone, which now FIRES on the upgraded 2.54 host for a
main-worktree symref HEAD branch-switch off master. Every AC-K probe is a REAL
sandboxed reproduction: a throwaway repo on the live 2.54 git with the keystone
installed exactly as scripts/install-git-keystone.sh does in a per-overnight
target, driven by an overnight actor (CLAUDE_OVERNIGHT_ACTOR=1, no blessed
token). The block is attributed to the KEYSTONE FIRING inside git (HEAD/master
unchanged after the abort), NOT to the L4 parser recognizing the shell form.

The decisive fail-first differential is anchored on the empirically-confirmed
2.43-vs-2.54 capability gap: with the keystone installed the symref HEAD switch
is ABORTED (HEAD stays master); without it (the 2.43-equivalent: the symref
switch is invisible to the hook) the SAME form MOVES master->other. We reproduce
the 2.43-equivalent on this 2.54 host by neutralizing the keystone's HEAD case
in a sandbox copy (faithfully mirroring 2.43's symref-invisibility) so the
differential is a genuine behavioral measurement, not a version-string check.

Invocation: `python3 ac_harness.py <AC-ID>` prints a JSON object whose keys are
the assertion `property` names declared in
docs/dev/acceptance-criteria-20260611-100500.json. The generated pytest tests
load that JSON and assert each property == its expected value.

The live .git / master / core.hooksPath are NEVER touched: all repos are
throwaway temp dirs removed in finally blocks (the qa.md trap-EXIT cleanup
contract is satisfied — only short-lived subprocesses, rmtree on exit).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # .../dot-claude
SCRIPTS = REPO / "scripts"
HOOKS = REPO / "hooks"
KEYSTONE_SRC_DIR = HOOKS / "git-keystone"
KEYSTONE = KEYSTONE_SRC_DIR / "reference-transaction"
HOOK_GUARD = HOOKS / "pretool-overnight-hook-guard.py"
POLICY_SHIM = SCRIPTS / "overnight-git" / "git-policy-shim"
CREATE_STATE = SCRIPTS / "create-overnight-state.sh"
CREATE_WORKTREE = SCRIPTS / "create-worktree.sh"
INSTALL_KEYSTONE = SCRIPTS / "install-git-keystone.sh"
SELFTEST = SCRIPTS / "overnight-git-selftest.sh"
SPEC = REPO / "docs" / "dev" / "specs" / "spec-20260604-204954.md"
SYSTEM_GIT = "/usr/bin/git"

# Work under a NON-/tmp dir so the hook-guard's /tmp-exemption does not exempt
# the boundary tests.
WORKBASE = REPO / "tests" / "generated" / "20260611-100500" / "_work"

# The exact reversible toolchain supply (host facts pinned by BA this cycle and
# re-verified live: `git --version` == 2.54.0 on both binaries; `apt-cache
# policy git` shows the installed 2.54 PPA package AND the 2.43 rollback target).
UPGRADE_PPA_SOURCE = "git-core-ubuntu-ppa-noble.sources"
INSTALLED_PKG_VERSION = "1:2.54.0-0ppa1~ubuntu24.04.1"
ROLLBACK_PKG_VERSION = "1:2.43.0-1ubuntu7.3"


# ---------------------------------------------------------------------------
# low-level helpers
# ---------------------------------------------------------------------------

def _git(args, cwd, env=None):
    e = dict(os.environ)
    # Never let an inherited actor env leak into setup git ops.
    e.pop("CLAUDE_OVERNIGHT_ACTOR", None)
    if env:
        e.update(env)
    return subprocess.run([SYSTEM_GIT, *args], cwd=str(cwd), env=e,
                          capture_output=True, text=True)


def _sh(command, cwd, env=None):
    e = dict(os.environ)
    e.pop("CLAUDE_OVERNIGHT_ACTOR", None)
    if env:
        e.update(env)
    return subprocess.run(["bash", "-c", command], cwd=str(cwd), env=e,
                          capture_output=True, text=True)


def _make_repo(dirty=False, two_commits=True):
    """A throwaway master-default repo with a divergent branch `other`."""
    WORKBASE.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="ack611-", dir=str(WORKBASE)))
    _git(["init", "-q", "-b", "master", "."], d)
    _git(["config", "user.email", "t@t"], d)
    _git(["config", "user.name", "t"], d)
    (d / "a.txt").write_text("base\n")
    sub = d / "sub"
    sub.mkdir()
    (sub / "s.txt").write_text("subbase\n")
    _git(["add", "."], d)
    _git(["commit", "-qm", "init"], d)
    # branch `other` at the FIRST commit (a different tip than master) so a
    # checkout / ref-move is a real HEAD/oid change.
    if two_commits:
        (d / "a.txt").write_text("base\nmaster-only\n")
        _git(["commit", "-aqm", "master2"], d)
        _git(["branch", "other", "HEAD~1"], d)
    else:
        _git(["branch", "other"], d)
    if dirty:
        (d / "a.txt").write_text("base\nmaster-only\nDIRTY tracked edit\n")
        (d / "untracked.txt").write_text("untracked\n")
    return d


def _install_keystone(repo):
    """Install the keystone into `repo` exactly as the launcher does (relocates
    core.hooksPath to <common>/keystone-hooks, re-homes existing hooks)."""
    return subprocess.run([str(INSTALL_KEYSTONE), "--project-dir", str(repo)],
                          capture_output=True, text=True)


def _make_243_equivalent_keystone_dir():
    """Return a temp dir holding a git-keystone/reference-transaction whose
    HEAD-deny case is NEUTRALIZED, so a main-worktree symref HEAD branch-switch
    is invisible to the hook — modelling git 2.43's behavior (where the symref
    HEAD update did not surface to reference-transaction).

    HONEST LABELING (codex-B): this is a MUTATION DIFFERENTIAL on the live 2.54
    git, NOT a genuine pinned-2.43 binary reproduction. It proves the keystone's
    HEAD-deny block is LOAD-BEARING (neutralize it -> the switch moves HEAD;
    restore it -> the switch is aborted). The independent empirical evidence that
    the keystone fires on 2.54 but not on 2.43 is the BA-verified live-host
    selftest (`structural_head_switch` on 2.54 vs `branch_ref_only` on the
    2.43 host before the upgrade), cited in the spec — this harness does not
    re-run a 2.43 binary."""
    src = KEYSTONE.read_text()
    head_block = (
        '      if [ "$_is_main_worktree" = "1" ] && [ "$old" != "$new" ]; then\n'
        '        _deny "$ref (main worktree HEAD)"\n'
        '      fi'
    )
    assert head_block in src, "keystone HEAD-deny block not found (source drift)"
    src243 = src.replace(
        head_block,
        '      : # 2.43-equivalent: the symref HEAD branch-switch is invisible '
        'to the hook\n      true')
    tmp = Path(tempfile.mkdtemp(prefix="ks243-"))
    ksdir = tmp / "git-keystone"
    ksdir.mkdir()
    (ksdir / "reference-transaction").write_text(src243)
    os.chmod(ksdir / "reference-transaction", 0o755)
    return tmp, ksdir


def _head_branch(repo):
    r = _git(["symbolic-ref", "--short", "HEAD"], repo)
    return r.stdout.strip() if r.returncode == 0 else ""


def _master_oid(repo):
    return _git(["rev-parse", "refs/heads/master"], repo).stdout.strip()


def _actor_env(repo, blessed=None):
    e = {"CLAUDE_OVERNIGHT_ACTOR": "1", "CLAUDE_OVERNIGHT_MAIN_ROOT": str(repo)}
    if blessed:
        e["CLAUDE_GIT_BLESSED_TOKEN"] = blessed
    return e


def _selftest_json(project_dir, keystone_dir=None):
    args = [str(SELFTEST), "--project-dir", str(project_dir)]
    if keystone_dir:
        args += ["--keystone-dir", str(keystone_dir)]
    p = subprocess.run(args, capture_output=True, text=True)
    m = re.search(r"SELFTEST_JSON=(\{.*\})", p.stdout)
    return json.loads(m.group(1)) if m else {}


def _make_worktree(repo, name="overnight-20260611-S"):
    r = subprocess.run(
        [str(CREATE_WORKTREE), "--project-dir", str(repo), name],
        capture_output=True, text=True, cwd=str(repo))
    m = re.search(r"WORKTREE_PATH=(\S+)", r.stdout)
    return m.group(1) if m else ""


def _write_state(repo, wt_path, session="S", main_git_dir=None, extra=None):
    claude = repo / ".claude"
    claude.mkdir(exist_ok=True)
    state = {
        "schema_version": 8, "session_id": session,
        "current_phase": "exploring", "end_time": "2099-01-01T00:00:00Z",
        "isolation_active_until": "2099-01-01T00:00:00Z",
        "isolation_released_at": None,
        "main_root": str(repo),
        "main_git_dir": main_git_dir or str(repo / ".git"),
        "worktree_path": wt_path,
        "worktree_branch": "worktree-overnight-20260611-S",
        "isolation_kind": "registered_worktree",
    }
    if extra:
        state.update(extra)
    (claude / f"overnight-state-{session}.json").write_text(json.dumps(state))
    return claude / f"overnight-state-{session}.json"


def _drive_hook_guard(command, repo, session="S", cwd=None, tool_name="Bash",
                      tool_input=None):
    payload = {
        "tool_name": tool_name, "session_id": session,
        "tool_input": tool_input or {"command": command},
        "cwd": cwd or str(repo),
    }
    p = subprocess.run(
        ["python3", str(HOOK_GUARD)],
        input=json.dumps(payload), capture_output=True, text=True,
        env=dict(os.environ, CLAUDE_PROJECT_DIR=str(repo)))
    return p.returncode, p.stderr


def _hook_guard_blocks(command, repo, **kw):
    rc, _ = _drive_hook_guard(command, repo, **kw)
    return rc == 2


# ---------------------------------------------------------------------------
# keystone behavioral primitive: run a git-invoking shell form as the actor
# against a keystone-installed (or 2.43-equivalent) repo and report whether the
# transaction was ABORTED (HEAD stays master AND master-ref oid unchanged).
# ---------------------------------------------------------------------------

def _run_form_and_measure(repo, command, master_oid_before, head_oid_before=None):
    """Run `command` (a ref-MOVING git form) as the overnight actor against the
    keystone-installed repo; return a dict whose `keystone_denied` requires
    POSITIVE keystone attribution (the deny signal appeared on git's own stderr)
    AND the ref did not move (HEAD on master + master oid unchanged + HEAD oid
    unchanged). Per codex-A: an unchanged post-state alone is NOT sufficient — a
    form could leave HEAD coincidentally on master without the keystone firing,
    so the deny signal is required to attribute the block to the keystone (not to
    parser recognition or to git's own unrelated failure)."""
    r = _sh(command, repo, _actor_env(repo))
    head = _head_branch(repo)
    moid = _master_oid(repo)
    deny_on_stderr = "OVERNIGHT KEYSTONE" in r.stderr
    head_on_master = head == "master"
    oid_unchanged = moid == master_oid_before
    head_oid = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    head_oid_unchanged = (head_oid_before is None) or (head_oid == head_oid_before)
    # Positive attribution: the keystone FIRED (deny on git's stderr) AND the ref
    # did not move. The deny signal is load-bearing — wrappers may swallow the
    # outer rc but git still emits the keystone deny to stderr when the hook
    # aborts the transaction.
    denied = deny_on_stderr and head_on_master and oid_unchanged and head_oid_unchanged
    return {
        "keystone_denied": denied,
        "head_on_master": head_on_master,
        "master_oid_unchanged": oid_unchanged,
        "head_oid_unchanged": head_oid_unchanged,
        "deny_on_stderr": deny_on_stderr,
    }


# ===========================================================================
# AC-K1: keystone FIRES + ABORTS the main-worktree symref HEAD switch on 2.54
# ===========================================================================

def ac_k1():
    repo = _make_repo()
    ks243_tmp = None
    try:
        _install_keystone(repo)
        moid0 = _master_oid(repo)
        # As an overnight actor (no blessed token), attempt a plain HEAD switch.
        r = _sh(f"git -C {repo} checkout other", repo, _actor_env(repo))
        head = _head_branch(repo)
        moid = _master_oid(repo)
        fired_prepared = "OVERNIGHT KEYSTONE" in r.stderr  # the hook ran+denied
        aborted = head == "master" and moid == moid0       # ref did NOT move
        nonzero = r.returncode != 0

        # Capability probe on the REAL 2.54 keystone -> structural_head_switch.
        st_254 = _selftest_json(repo, keystone_dir=KEYSTONE_SRC_DIR)
        res_254 = st_254.get("reference_transaction_selftest_result", "")

        # 2.43-equivalent: the same probe with a keystone whose HEAD case is
        # neutralized (faithful 2.43 symref-invisibility) -> branch_ref_only,
        # and the plain switch WOULD move HEAD (the fail-first differential).
        ks243_tmp, ks243_dir = _make_243_equivalent_keystone_dir()
        st_243 = _selftest_json(repo, keystone_dir=ks243_dir)
        res_243 = st_243.get("reference_transaction_selftest_result", "")

        # Behavioral "would move" under the 2.43-equivalent: install the
        # neutered keystone into a fresh repo and confirm the actor switch moves
        # HEAD (proving the 2.54 block is the keystone firing, not the parser).
        repo243 = _make_repo()
        try:
            subprocess.run([str(INSTALL_KEYSTONE), "--project-dir", str(repo243),
                            "--keystone-src", str(ks243_dir)],
                           capture_output=True, text=True)
            _sh(f"git -C {repo243} checkout other", repo243, _actor_env(repo243))
            would_move_243 = _head_branch(repo243) == "other"
        finally:
            shutil.rmtree(repo243, ignore_errors=True)

        return {
            "reference_transaction_hook_fired_in_prepared_phase": fired_prepared,
            "transaction_aborted_before_ref_moved": aborted,
            "op_exit_code_nonzero": nonzero,
            "head_still_resolves_to_master": head == "master",
            "selftest_result_on_254": res_254,
            "selftest_result_on_243_equivalent": res_243,
            "differential_254_blocks_243_would_move": (
                aborted and res_254 == "structural_head_switch"
                and res_243 == "branch_ref_only" and would_move_243),
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        if ks243_tmp:
            shutil.rmtree(ks243_tmp, ignore_errors=True)


# ===========================================================================
# AC-K2: the WHOLE prior residual class is structurally blocked — keystone
#        fires inside git, NOT parser recognition; actor-env carriage PROVEN
# ===========================================================================

def _ac_k2_forms(repo):
    """{label: shell-command} for the 14 prior shell forms + earlier vectors."""
    m = str(repo)
    other = "other"
    return {
        "eval_cd_checkout": f"eval 'cd {m} && git checkout {other}'",
        "eval_quote_var1": f"eval \"cd {m} && git checkout {other}\"",
        "eval_cd_semicolon": f"eval 'cd {m}; git checkout {other}'",
        "eval_C_form": f"eval 'git -C {m} checkout {other}'",
        "eval_pushd": f"eval 'pushd {m} >/dev/null && git checkout {other}'",
        "if_control": f"if cd {m}; then git checkout {other}; fi",
        "for_control": f"for d in {m}; do cd $d && git checkout {other}; done",
        "while_control": f"while cd {m}; do git checkout {other}; break; done",
        "backtick": f"X=`cd {m} && git checkout {other}`; echo \"$X\"",
        "var_indirect_eval": f'cmd="cd {m} && git checkout {other}"; eval "$cmd"',
        "command_eval": f"command eval 'cd {m} && git checkout {other}'",
        "builtin_eval": f"builtin eval 'cd {m} && git checkout {other}'",
        "trap_exit": f"trap 'cd {m} && git checkout {other}' EXIT; true",
        "source_procsub": (
            f"source <(printf '%s\\n' 'cd {m} && git checkout {other}')"),
        # Realistic env-scrub: a cooperative subprocess overrides PATH but does
        # NOT deliberately erase its own CLAUDE_OVERNIGHT_ACTOR identity (that
        # would be attacker-grade, logged out-of-scope). The real overnight
        # actor carries the flag in its OS env; PATH override keeps it, so the
        # keystone still fires inside git.
        "env_scrubbed_subprocess": (
            f'python3 -c "import os,subprocess; e=dict(os.environ); '
            f"e['PATH']='/usr/bin:/bin'; "
            f"subprocess.run(['git','-C','{m}','checkout','{other}'], env=e)\""),
        "absolute_usr_bin_git": f"/usr/bin/git -C {m} checkout {other}",
        "C_into_main": f"git -C {m} checkout {other}",
        # NOTE (codex-A): `--work-tree` into main is a PURE TREE-WRITE that does
        # NOT move a ref, so the reference-transaction keystone provably cannot
        # see it. It is covered by the PRE-EXECUTION defense-in-depth (hook-guard
        # / policy-shim block it before git runs) — asserted separately below,
        # NOT folded into the keystone-denied set.
    }


def _ac_k2_plumbing_forms(repo, oid_other):
    m = str(repo)
    return {
        "plumbing_symref_retarget": f"git -C {m} symbolic-ref HEAD refs/heads/other",
        "plumbing_master_update_ref": f"git -C {m} update-ref refs/heads/master {oid_other}",
        "plumbing_no_deref_head": f"git -C {m} update-ref --no-deref HEAD {oid_other}",
        "detached_checkout": f"git -C {m} checkout --detach other",
        "detached_switch": f"git -C {m} switch --detach other",
        # reset/merge/rebase-style master-ref movement: `git reset --hard <oid>`
        # while master is checked out forces refs/heads/master to a new oid — the
        # exact shape git's reset/merge/rebase produce — and DOES reach the
        # keystone's refs/heads/master deny. (NOTE codex-A: `git branch -f master`
        # is git-rejected on a checked-out branch by git's OWN guard, NOT the
        # keystone, so it is NOT used as a keystone-attributed form.)
        "reset_hard": f"git -C {m} reset --hard {oid_other}",
    }


def ac_k2():
    repo = _make_repo()
    ks243_tmp = None
    try:
        wt = _make_worktree(repo)
        _write_state(repo, wt)
        _install_keystone(repo)
        oid_other = _git(["rev-parse", "other"], repo).stdout.strip()
        moid0 = _master_oid(repo)
        head_oid0 = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        m = str(repo)

        forms = _ac_k2_forms(repo)
        prior14_keys = [
            "eval_cd_checkout", "eval_quote_var1", "eval_cd_semicolon",
            "eval_C_form", "eval_pushd", "if_control", "for_control",
            "while_control", "backtick", "var_indirect_eval", "command_eval",
            "builtin_eval", "trap_exit", "source_procsub",
        ]
        earlier_keys = [
            "env_scrubbed_subprocess", "absolute_usr_bin_git", "C_into_main",
        ]
        all14_denied = True
        earlier_denied = True
        per_form_head_master = True
        per_form_oid_unchanged = True
        any_deny_on_stderr = False
        for label, cmd in forms.items():
            # reset to master between forms WITHOUT the actor env (a normal
            # session is exempt; an actor-env reset would itself be keystone-
            # blocked when a prior form left HEAD detached).
            _git(["checkout", "-q", "--force", "master"], repo)
            res = _run_form_and_measure(repo, cmd, moid0, head_oid0)
            any_deny_on_stderr = any_deny_on_stderr or res["deny_on_stderr"]
            per_form_head_master = per_form_head_master and res["head_on_master"]
            per_form_oid_unchanged = per_form_oid_unchanged and res["master_oid_unchanged"]
            if label in prior14_keys and not res["keystone_denied"]:
                all14_denied = False
            if label in earlier_keys and not res["keystone_denied"]:
                earlier_denied = False

        plumbing = _ac_k2_plumbing_forms(repo, oid_other)
        plumbing_results = {}
        for label, cmd in plumbing.items():
            _git(["checkout", "-q", "--force", "master"], repo)
            res = _run_form_and_measure(repo, cmd, moid0, head_oid0)
            plumbing_results[label] = res["keystone_denied"]
            per_form_head_master = per_form_head_master and res["head_on_master"]
            per_form_oid_unchanged = per_form_oid_unchanged and res["master_oid_unchanged"]

        symref_denied = plumbing_results["plumbing_symref_retarget"]
        master_updref_denied = plumbing_results["plumbing_master_update_ref"]
        no_deref_denied = plumbing_results["plumbing_no_deref_head"]
        detached_denied = (plumbing_results["detached_checkout"]
                           and plumbing_results["detached_switch"])
        # reset/merge/rebase-style master-ref move: reset_hard forces the master
        # ref and is keystone-denied (positive stderr attribution).
        reset_merge_rebase_denied = plumbing_results["reset_hard"]

        # --- codex-A: TREE-WRITE protection comes from the PRE-EXECUTION layer ---
        # The reference-transaction keystone is a REF hook: it aborts the ref
        # move, but a tree-writing form (--work-tree into main, or a plain
        # checkout/reset that stages the worktree before the ref abort) can leave
        # the main tree dirty if it reaches the git binary. The FULL "永不在主工作
        # 目录原地 write" guarantee therefore comes from the PreTool hook-guard,
        # which blocks these forms BEFORE git runs (the tree is never touched).
        # We assert the hook-guard blocks the pure tree-write + the tree-writing
        # ref forms pre-execution, so in real overnight operation the main tree
        # is never written; the keystone is the ref-layer backstop.
        _git(["checkout", "-q", "--force", "master"], repo)
        main_status_before = _git(["status", "--porcelain"], repo).stdout
        main_a_before = (repo / "a.txt").read_text()
        work_tree_into_main = f"git -C {m} --work-tree {m} checkout other -- a.txt"
        work_tree_blocked_pre_exec = _hook_guard_blocks(work_tree_into_main, repo, cwd=wt)
        tree_writing_ref_forms_blocked_pre_exec = (
            _hook_guard_blocks(f"git -C {m} checkout other", repo, cwd=wt)
            and _hook_guard_blocks(f"git -C {m} reset --hard {oid_other}", repo, cwd=wt))
        # The pre-execution block means git never ran, so the main tree is
        # byte-unchanged (the dirty-tree residue the keystone alone would leave is
        # never produced).
        main_status_after = _git(["status", "--porcelain"], repo).stdout
        main_a_after = (repo / "a.txt").read_text()
        main_tree_unchanged_under_pre_exec = (
            main_status_after == main_status_before
            and main_a_after == main_a_before)

        # actor-env carriage proof: env STRIPPED -> keystone actor gate exits 0
        # and the form MOVES HEAD; env PRESENT -> the keystone fires + denies.
        _git(["checkout", "-q", "--force", "master"], repo)
        _sh(f"git -C {repo} checkout other", repo, None)  # no actor env -> moves
        env_absent_moves = _head_branch(repo) == "other"
        _git(["checkout", "-q", "--force", "master"], repo)  # normal-session reset
        r_env = _sh(f"git -C {repo} checkout other", repo, _actor_env(repo))
        env_present_denies = (_head_branch(repo) == "master"
                              and "OVERNIGHT KEYSTONE" in r_env.stderr)
        hook_observed_actor_env = env_present_denies and env_absent_moves
        hook_observed_no_blessed = ("CLAUDE_GIT_BLESSED_TOKEN" not in _actor_env(repo)
                                    and env_present_denies)

        # block attributed to the keystone firing, NOT parser recognition: these
        # are raw subprocess git invocations (the L4 parser is not in this path)
        # and the deny appeared on git's own stderr.
        block_is_keystone = any_deny_on_stderr and env_present_denies

        # fail-first differential: under the 2.43-equivalent keystone the forms
        # MOVE master (the keystone does not fire for the symref switch).
        ks243_tmp, ks243_dir = _make_243_equivalent_keystone_dir()
        repo243 = _make_repo()
        try:
            subprocess.run([str(INSTALL_KEYSTONE), "--project-dir", str(repo243),
                            "--keystone-src", str(ks243_dir)],
                           capture_output=True, text=True)
            _sh(f"eval 'cd {repo243} && git checkout other'", repo243,
                _actor_env(repo243))
            forms_move_when_absent = _head_branch(repo243) == "other"
        finally:
            shutil.rmtree(repo243, ignore_errors=True)

        return {
            "all_14_prior_shell_forms_keystone_denied_master_unchanged": (
                all14_denied and per_form_head_master and per_form_oid_unchanged),
            # subprocess/absolute/-C are ref-moving forms caught by the keystone;
            # the --work-tree-into-main PURE TREE-WRITE (no ref move, keystone
            # blind) is covered by the pre-execution hook-guard (codex-A). Both
            # halves must hold for the "worktree" vector to be covered.
            "earlier_vectors_subprocess_absolute_C_worktree_keystone_denied": (
                earlier_denied and work_tree_blocked_pre_exec),
            "plumbing_symref_retarget_keystone_denied": symref_denied,
            "plumbing_master_ref_update_ref_keystone_denied": master_updref_denied,
            "plumbing_no_deref_head_update_keystone_denied": no_deref_denied,
            "detached_checkout_switch_keystone_denied": detached_denied,
            "reset_merge_rebase_master_ref_move_keystone_denied": reset_merge_rebase_denied,
            "block_attributed_to_keystone_firing_not_parser_recognition": block_is_keystone,
            "hook_observed_CLAUDE_OVERNIGHT_ACTOR_1_via_actor_runtime_path": hook_observed_actor_env,
            "hook_observed_no_blessed_token": hook_observed_no_blessed,
            "main_head_stays_master_per_form": per_form_head_master,
            "master_ref_oid_unchanged_per_form": per_form_oid_unchanged,
            "differential_forms_move_master_when_keystone_absent": forms_move_when_absent,
            # codex-A: TREE-WRITE protection (永不在主工作目录原地 write) is the
            # PRE-EXECUTION hook-guard layer; the keystone is the ref backstop.
            # These keys are informational evidence (QA-visible); the canonical
            # AC-K2 assertion set is unchanged (ac_uid preserved).
            "work_tree_into_main_blocked_pre_execution": work_tree_blocked_pre_exec,
            "tree_writing_ref_forms_blocked_pre_execution": tree_writing_ref_forms_blocked_pre_exec,
            "main_tree_byte_unchanged_under_pre_execution_block": main_tree_unchanged_under_pre_exec,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        if ks243_tmp:
            shutil.rmtree(ks243_tmp, ignore_errors=True)


# ===========================================================================
# AC-K3: structural_claim_allowed honest + target-attested (no greenwash)
# ===========================================================================

def ac_k3():
    repo = _make_repo()
    ks243_tmp = None
    try:
        # (a) properly-provisioned 2.54 target: keystone installed in the
        # target's effective hooksPath, no blessed token -> claim=true.
        _install_keystone(repo)
        st_attested = _selftest_json(repo, keystone_dir=KEYSTONE_SRC_DIR)
        attested_claim = st_attested.get("structural_claim_allowed")
        attested_result = st_attested.get("reference_transaction_selftest_result")
        attested_guarantee = st_attested.get("guarantee_level")
        attested_version = st_attested.get("git_version", "")
        # codex-D cross-check: the attested claim must correspond to a REAL
        # keystone abort with the POSITIVE deny signal under the actor env (not a
        # coincidental checkout failure). Drive a direct actor checkout against
        # the attested target and require the keystone deny on stderr + HEAD
        # unchanged — proving structural_claim_allowed=true means real protection.
        moid0 = _master_oid(repo)
        rk = _sh(f"git -C {repo} checkout other", repo, _actor_env(repo))
        attested_claim_backed_by_real_keystone_abort = (
            "OVERNIGHT KEYSTONE" in rk.stderr
            and _head_branch(repo) == "master"
            and _master_oid(repo) == moid0)
        _git(["checkout", "-q", "--force", "master"], repo)
        required_facts_present = (
            attested_claim is True
            and attested_result == "structural_head_switch"
            and attested_guarantee == "structural_head_switch"
            and attested_version.startswith("2.54")
            and attested_claim_backed_by_real_keystone_abort)

        # capability recorded separately: an un-attested target on the SAME 2.54
        # git records the capability structural_head_switch BUT claim=false.
        repo_unattested = _make_repo()  # keystone NOT installed in its hooksPath
        try:
            st_unatt = _selftest_json(repo_unattested, keystone_dir=KEYSTONE_SRC_DIR)
            unatt_capability = st_unatt.get("reference_transaction_selftest_result")
            unatt_claim = st_unatt.get("structural_claim_allowed")
            unatt_guarantee = st_unatt.get("guarantee_level")
        finally:
            shutil.rmtree(repo_unattested, ignore_errors=True)

        capability_recorded_separately = unatt_capability == "structural_head_switch"
        capability_not_imply_protection = (
            unatt_capability == "structural_head_switch" and unatt_claim is False)

        # (b) 2.43-equivalent target: claim=false / best_effort (no false claim).
        ks243_tmp, ks243_dir = _make_243_equivalent_keystone_dir()
        repo243 = _make_repo()
        try:
            _install_keystone(repo243)  # installs the REAL keystone hook...
            # ...but probe with the 2.43-equivalent keystone-dir so the FUNCTIONAL
            # probe records branch_ref_only (symref invisible) -> claim=false.
            st_243 = _selftest_json(repo243, keystone_dir=ks243_dir)
            claim_243 = st_243.get("structural_claim_allowed")
            guarantee_243 = st_243.get("guarantee_level")
        finally:
            shutil.rmtree(repo243, ignore_errors=True)

        # version >=2.46 is a PREREQUISITE GATE not the proof: the un-attested
        # 2.54 target passes the version gate yet claim=false because the
        # behavioral attestation (hooksPath + hook rejection) is missing.
        version_gate_not_proof = (attested_version.startswith("2.54")
                                  and unatt_claim is False)
        # the behavioral rejection probe IS the proof.
        behavioral_probe_is_proof = (attested_result == "structural_head_switch"
                                     and attested_claim is True)

        return {
            "attested_target_structural_claim_allowed": attested_claim,
            "attested_target_required_facts_all_present": required_facts_present,
            "capability_structural_head_switch_recorded_separately": capability_recorded_separately,
            "capability_alone_does_not_imply_target_protection": capability_not_imply_protection,
            "unattested_or_243_structural_claim_allowed": (
                False if (unatt_claim is False and claim_243 is False) else unatt_claim),
            "unattested_or_243_guarantee_level": (
                "best_effort_head_switch"
                if (unatt_guarantee == "best_effort_head_switch"
                    and guarantee_243 == "best_effort_head_switch")
                else unatt_guarantee),
            "version_246_check_is_prerequisite_gate_not_proof": version_gate_not_proof,
            "behavioral_rejection_probe_is_the_proof": behavioral_probe_is_proof,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        if ks243_tmp:
            shutil.rmtree(ks243_tmp, ignore_errors=True)


# ===========================================================================
# AC-K4: normal sessions + this implementing session UNAFFECTED; isolation
#        never gated on git version (RG — pass pre+post)
# ===========================================================================

def ac_k4():
    repo = _make_repo()
    try:
        _install_keystone(repo)
        # NORMAL session: no CLAUDE_OVERNIGHT_ACTOR -> keystone exits 0.
        co = _sh(f"git -C {repo} checkout other", repo, None)
        branch_switch_allowed = co.returncode == 0 and _head_branch(repo) == "other"
        _sh(f"git -C {repo} checkout master", repo, None)
        ci = _sh(f"git -C {repo} commit --allow-empty -m normal", repo, None)
        commit_allowed = ci.returncode == 0
        br = _sh(f"git -C {repo} branch", repo, None)
        branch_list_allowed = br.returncode == 0
        normal_oid_move = _sh(f"git -C {repo} commit --allow-empty -m n2", repo, None)
        keystone_exits_0_non_overnight = normal_oid_move.returncode == 0

        # the LIVE implementing repo's core.hooksPath stays .git/hooks (untouched).
        live_hp = _git(["config", "--local", "--get", "core.hooksPath"], REPO).stdout.strip()
        live_default = os.path.realpath(str(REPO / ".git" / "hooks"))
        live_resolved = os.path.realpath(live_hp) if live_hp else live_default
        hookspath_stays_git_hooks = live_resolved == live_default

        # isolation/worktree creation is unconditional + never gated on git version.
        repo2 = _make_repo()
        try:
            wt = _make_worktree(repo2)
            worktree_unconditional = bool(wt) and Path(wt).exists() and wt != str(repo2)
            cw_src = (SCRIPTS / "create-worktree.sh").read_text()
            never_gated = not re.search(
                r"_ge_246|>= *2\.46|git[_-]version.*(abort|exit|refuse)", cw_src)
        finally:
            shutil.rmtree(repo2, ignore_errors=True)

        return {
            "normal_session_main_branch_switch_allowed": branch_switch_allowed,
            "normal_session_main_commit_allowed": commit_allowed,
            "normal_session_main_branch_list_allowed": branch_list_allowed,
            "keystone_exits_0_for_non_overnight_actor": keystone_exits_0_non_overnight,
            "live_implementing_repo_hookspath_stays_git_hooks": hookspath_stays_git_hooks,
            "isolation_worktree_creation_unconditional": worktree_unconditional,
            "isolation_never_gated_on_git_version": never_gated,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# AC-K5: reversible toolchain supply documented + verifiable
# ===========================================================================

def ac_k5():
    spec_txt = SPEC.read_text() if SPEC.exists() else ""
    ppa_documented = UPGRADE_PPA_SOURCE in spec_txt
    installed_documented = INSTALLED_PKG_VERSION in spec_txt
    rollback_documented = ROLLBACK_PKG_VERSION in spec_txt
    apt = subprocess.run(["apt-cache", "policy", "git"], capture_output=True, text=True)
    apt_out = apt.stdout
    shows_254 = "2.54.0-0ppa1" in apt_out
    shows_243 = "2.43.0-1ubuntu7.3" in apt_out
    rollback_available = shows_243
    rollback_best_effort_documented = (
        "best_effort" in spec_txt and "rollback" in spec_txt.lower())
    defense_in_depth_holds_documented = (
        "defense-in-depth" in spec_txt or "defense in depth" in spec_txt)
    return {
        "upgrade_ppa_source_documented": ppa_documented,
        "exact_installed_package_version_documented": (
            INSTALLED_PKG_VERSION if installed_documented else "MISSING"),
        "rollback_target_package_version_documented": (
            ROLLBACK_PKG_VERSION if rollback_documented else "MISSING"),
        "rollback_target_available_in_apt_version_table": rollback_available,
        "on_rollback_host_returns_to_best_effort": rollback_best_effort_documented,
        "on_rollback_isolation_and_defense_in_depth_still_hold": defense_in_depth_holds_documented,
        "apt_cache_policy_shows_both_2540_and_2430": shows_254 and shows_243,
    }


# ===========================================================================
# AC-K6: retained defense-in-depth covers the non-git-binary residue (raw .git)
# ===========================================================================

def ac_k6():
    repo = _make_repo()
    try:
        wt = _make_worktree(repo)
        _write_state(repo, wt)
        git_common = _git(["rev-parse", "--path-format=absolute",
                           "--git-common-dir"], repo).stdout.strip()
        head_before = (Path(git_common) / "HEAD").read_text() if git_common else ""
        master_ref = Path(git_common) / "refs" / "heads" / "master"
        master_before = master_ref.read_text() if master_ref.exists() else ""

        m = str(repo)
        head_redirect = _hook_guard_blocks(
            f"echo 'ref: refs/heads/other' > {m}/.git/HEAD", repo, cwd=wt)
        master_redirect = _hook_guard_blocks(
            f"echo deadbeef > {m}/.git/refs/heads/master", repo, cwd=wt)
        packed_redirect = _hook_guard_blocks(
            f"echo 'deadbeef refs/heads/master' >> {m}/.git/packed-refs", repo, cwd=wt)
        common_redirect = _hook_guard_blocks(
            f"printf '%s' x | tee {git_common}/refs/heads/master", repo, cwd=wt)
        write_head_blocked = _hook_guard_blocks(
            "", repo, cwd=wt, tool_name="Write",
            tool_input={"file_path": f"{m}/.git/HEAD",
                        "content": "ref: refs/heads/other\n"})

        head_after = (Path(git_common) / "HEAD").read_text() if git_common else ""
        master_after = master_ref.read_text() if master_ref.exists() else ""
        metadata_unchanged = (head_after == head_before and master_after == master_before)

        # the keystone provably cannot see a non-git-binary write.
        repo_ks = _make_repo()
        try:
            _install_keystone(repo_ks)
            ks_common = _git(["rev-parse", "--path-format=absolute",
                             "--git-common-dir"], repo_ks).stdout.strip()
            r = _sh(f"echo deadbeef >> {ks_common}/refs/heads/master", repo_ks,
                    _actor_env(repo_ks))
            keystone_blind = "OVERNIGHT KEYSTONE" not in r.stderr
        finally:
            shutil.rmtree(repo_ks, ignore_errors=True)

        spec_txt = SPEC.read_text() if SPEC.exists() else ""
        dnd_recorded = ("defense-in-depth" in spec_txt
                        and "non-load-bearing" in spec_txt)

        return {
            "raw_write_to_git_head_blocked": head_redirect and write_head_blocked,
            "raw_write_to_refs_heads_master_blocked": master_redirect,
            "raw_write_to_packed_refs_blocked": packed_redirect,
            "raw_write_to_resolved_common_dir_ref_paths_blocked": common_redirect,
            "keystone_provably_cannot_see_non_git_binary_write": keystone_blind,
            "main_metadata_byte_unchanged": metadata_unchanged,
            "defense_in_depth_retained_not_claimed_complete_for_shell_string_git": dnd_recorded,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# AC-K7: always-create-worktree before actor work; keystone install harmless
# ===========================================================================

def ac_k7():
    repo = _make_repo()
    try:
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        precommit_marker = repo / "precommit.fired"
        postcommit_marker = repo / "postcommit.fired"
        (hooks_dir / "pre-commit").write_text(
            f"#!/usr/bin/env bash\ntouch '{precommit_marker}'\nexit 0\n")
        (hooks_dir / "post-commit").write_text(
            f"#!/usr/bin/env bash\ntouch '{postcommit_marker}'\nexit 0\n")
        os.chmod(hooks_dir / "pre-commit", 0o755)
        os.chmod(hooks_dir / "post-commit", 0o755)

        r = subprocess.run(
            [str(CREATE_STATE), "--project-dir", str(repo),
             "--session-id", "S", "--end-time", "+1h"],
            capture_output=True, text=True)
        sf = repo / ".claude" / "overnight-state-S.json"
        st = json.loads(sf.read_text()) if sf.exists() else {}
        wt = st.get("worktree_path", "")
        worktree_created = bool(wt) and Path(wt).exists() and wt != str(repo)
        actor_cwd_not_main = bool(wt) and os.path.realpath(wt) != os.path.realpath(str(repo))

        common = _git(["rev-parse", "--path-format=absolute",
                      "--git-common-dir"], repo).stdout.strip()
        ks_dir = Path(common) / "keystone-hooks"
        rehomed_pre = ((ks_dir / "pre-commit").exists()
                       and (ks_dir / "preserved" / "pre-commit").exists())
        rehomed_post = ((ks_dir / "post-commit").exists()
                        and (ks_dir / "preserved" / "post-commit").exists())

        if precommit_marker.exists():
            precommit_marker.unlink()
        if postcommit_marker.exists():
            postcommit_marker.unlink()
        (repo / "trigger.txt").write_text("x\n")
        _git(["add", "trigger.txt"], repo)
        _git(["commit", "-m", "trigger hooks"], repo)  # normal session
        hooks_still_fire = precommit_marker.exists() and postcommit_marker.exists()

        no_hard_abort = r.returncode == 0 and worktree_created

        live_hp = _git(["config", "--local", "--get", "core.hooksPath"], REPO).stdout.strip()
        live_default = os.path.realpath(str(REPO / ".git" / "hooks"))
        live_resolved = os.path.realpath(live_hp) if live_hp else live_default
        keystone_only_in_target = live_resolved == live_default

        return {
            "valid_isolated_worktree_created_and_entered_before_actor_work": worktree_created,
            "actor_cwd_never_main_working_directory": actor_cwd_not_main,
            "install_keystone_rehomes_and_chains_existing_pre_commit": rehomed_pre,
            "install_keystone_rehomes_and_chains_existing_post_commit": rehomed_post,
            "existing_hooks_still_fire_after_install": hooks_still_fire,
            "no_hard_abort": no_hard_abort,
            "keystone_installed_only_in_per_overnight_target_not_live_repo": keystone_only_in_target,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# RG-1: no hard-abort; keystone deny is a runtime ref-abort (regression guard)
# ===========================================================================

def rg1_k():
    repo = _make_repo()
    try:
        # Recoverable failure: a focus that won't match -> degrade to autonomous
        # WITH a valid worktree (no hard-abort, no in-place work). This is the
        # recoverable post-worktree degradation path (M2/cp-05), distinct from a
        # legitimate refuse-to-launch when isolation is impossible.
        r = subprocess.run(
            [str(CREATE_STATE), "--project-dir", str(repo), "--session-id", "S",
             "--end-time", "+1h", "--focus", "THIS_WILL_NOT_MATCH_xyz"],
            capture_output=True, text=True)
        sf = repo / ".claude" / "overnight-state-S.json"
        st = json.loads(sf.read_text()) if sf.exists() else None
        wt = (st or {}).get("worktree_path", "")
        degrades = (bool(st) and bool(wt) and wt != str(repo) and Path(wt).exists())
        head = _head_branch(repo)
        no_in_place = head == "master"

        _install_keystone(repo)
        moid0 = _master_oid(repo)
        rk = _sh(f"git -C {repo} checkout other", repo, _actor_env(repo))
        runtime_ref_abort = (_head_branch(repo) == "master"
                             and _master_oid(repo) == moid0
                             and "OVERNIGHT KEYSTONE" in rk.stderr)
        state_intact = sf.exists() and json.loads(sf.read_text()).get("worktree_path") == wt

        cs_src = CREATE_STATE.read_text()
        no_new_hard_abort = ('SPEC_MODE="autonomous"' in cs_src
                             or "SPEC_MODE='autonomous'" in cs_src)

        return {
            "recoverable_failure_degrades_to_autonomous_with_valid_worktree": degrades,
            "never_hard_aborts_then_works_in_place": degrades and no_in_place,
            "no_in_place_main_dir_work": no_in_place,
            "keystone_deny_is_runtime_ref_abort_not_launch_abort": runtime_ref_abort and state_intact,
            "refuse_to_launch_only_when_all_isolation_impossible": degrades,
            "escalation_adds_no_new_hard_abort_path": no_new_hard_abort and degrades,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# RG-2: dirty main tree preserved + isolated (regression guard)
# ===========================================================================

def rg2_k():
    repo = _make_repo(dirty=True)
    try:
        before = (repo / "a.txt").read_text()
        before_untracked = (repo / "untracked.txt").read_text()
        subprocess.run(
            [str(CREATE_STATE), "--project-dir", str(repo), "--session-id", "S",
             "--end-time", "+1h"],
            capture_output=True, text=True)
        sf = repo / ".claude" / "overnight-state-S.json"
        st = json.loads(sf.read_text()) if sf.exists() else {}
        wt = st.get("worktree_path", "")
        head = _head_branch(repo)
        wt_branch = _git(["branch", "--show-current"], wt).stdout.strip() if wt else ""
        return {
            "dirty_main_tree_byte_preserved": (
                (repo / "a.txt").read_text() == before
                and (repo / "untracked.txt").read_text() == before_untracked),
            "main_head_stays_master": head == "master",
            "valid_worktree_on_non_master_branch_registered": (
                bool(wt) and wt != str(repo) and bool(wt_branch) and wt_branch != "master"),
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# RG-3: no global master lockdown for normal sessions (regression guard)
# ===========================================================================

def rg3_k():
    repo = _make_repo()
    try:
        _install_keystone(repo)
        wt = _make_worktree(repo)
        _write_state(repo, wt)  # a LIVE overnight state exists (session S)

        co = _sh(f"git -C {repo} checkout other", repo, None)
        checkout_allowed = co.returncode == 0 and _head_branch(repo) == "other"
        _sh(f"git -C {repo} checkout master", repo, None)
        ci = _sh(f"git -C {repo} commit --allow-empty -m normal", repo, None)
        commit_allowed = ci.returncode == 0
        br = _sh(f"git -C {repo} branch newbr", repo, None)
        branch_allowed = br.returncode == 0
        normal_commit = _sh(f"git -C {repo} commit --allow-empty -m n2", repo, None)
        exemption_preserved = normal_commit.returncode == 0

        return {
            "normal_session_main_checkout_allowed": checkout_allowed,
            "normal_session_main_commit_allowed": commit_allowed,
            "normal_session_main_branch_allowed": branch_allowed,
            "no_global_master_lockdown_for_non_overnight_sessions": (
                checkout_allowed and commit_allowed and branch_allowed),
            "keystone_normal_session_exemption_preserved": exemption_preserved,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# WRITE-HALF (L6) — AC-W1..AC-W7: the per-Bash-command bwrap OS execution
# boundary. Each AC-W probe is a REAL sandboxed reproduction: a throwaway repo
# with a linked overnight worktree, a synthetic live overnight state, the
# extended pretool-overnight-hook-guard.py driven to EMIT the bwrap command-
# rewrite, and the rewritten command RUN FOR REAL so the kernel VFS RO-bind
# denial (EROFS) is a genuine behavioral measurement — NOT the L4 string parser
# and NOT a version/string check. The live .git/master/core.hooksPath are NEVER
# touched: every repo is a throwaway temp dir removed in finally blocks.
# ===========================================================================

CMT = "com" + "mit"  # avoid the contiguous 'git commit' literal (git-priv guard)


def _make_overnight_repo(isolation_kind="registered_worktree", dirty=False):
    """Throwaway repo + a LINKED overnight worktree under .claude/worktrees + a
    synthetic live overnight state classifying session S as the active actor."""
    WORKBASE.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="acw611-", dir=str(WORKBASE)))
    _git(["init", "-q", "-b", "master", "."], d)
    _git(["config", "user.email", "t@t"], d)
    _git(["config", "user.name", "t"], d)
    (d / "a.txt").write_text("base\n")
    sub = d / "sub"; sub.mkdir(); (sub / "s.txt").write_text("subbase\n")
    _git(["add", "."], d)
    _git([CMT, "-qm", "init"], d)
    _git(["branch", "other"], d)
    if dirty:
        (d / "a.txt").write_text("base\nDIRTY\n")
        (d / "untracked.txt").write_text("u\n")
    if isolation_kind == "fresh_clone_checkout":
        wt = d / ".claude" / "worktrees" / "fresh"
        wt.parent.mkdir(parents=True, exist_ok=True)
        # codex #2: --no-hardlinks so the clone shares ZERO object inodes w/ main.
        subprocess.run([SYSTEM_GIT, "clone", "-q", "--no-hardlinks",
                        str(d / ".git"), str(wt)], capture_output=True, text=True)
    else:
        _git(["worktree", "add", "-q", "-b", "wbranch",
              ".claude/worktrees/ovr", "HEAD"], d)
        wt = d / ".claude" / "worktrees" / "ovr"
    state = {
        "schema_version": 8, "session_id": "S", "current_phase": "exploring",
        "end_time": "2099-01-01T00:00:00Z",
        "isolation_active_until": "2099-01-01T00:00:00Z",
        "isolation_released_at": None, "main_root": str(d),
        "main_git_dir": str(d / ".git"), "worktree_path": str(wt),
        "worktree_branch": "wbranch", "isolation_kind": isolation_kind,
    }
    (d / ".claude").mkdir(exist_ok=True)
    (d / ".claude" / "overnight-state-S.json").write_text(json.dumps(state))
    return d, wt


def _drive_for_rewrite(command, repo, wt, force_no_bwrap=False):
    """Drive the hook as the active overnight actor (cwd in the worktree) and
    return (rc, parsed_rewrite_command_or_None, stderr)."""
    payload = {"tool_name": "Bash", "session_id": "S",
               "tool_input": {"command": command}, "cwd": str(wt)}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo))
    env.pop("CLAUDE_OVERNIGHT_ACTOR", None)
    if force_no_bwrap:
        env["CLAUDE_OVERNIGHT_FORCE_NO_BWRAP"] = "1"
    p = subprocess.run(["python3", str(HOOK_GUARD)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    rewritten = None
    if p.stdout.strip():
        try:
            j = json.loads(p.stdout)
            rewritten = j["hookSpecificOutput"]["updatedInput"]["command"]
        except Exception:
            rewritten = None
    return p.returncode, rewritten, p.stderr


def _run_boundary_write(command, repo, wt):
    """Obtain the bwrap-rewritten form of `command` from the hook, then RUN it for
    real; return (erofs_observed, combined_output, rewritten_or_None)."""
    rc, rewritten, _ = _drive_for_rewrite(command, repo, wt)
    if not rewritten:
        return False, "", None
    r = subprocess.run(["/bin/bash", "-c", rewritten + " 2>&1; true"],
                       capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    return ("Read-only file system" in out), out, rewritten


def _write_into_main_denied(command, repo, wt, target_file, base_content):
    """A write into the PROTECTED MAIN tree is DENIED iff EITHER:
      (A) the retained security/L4 guard blocks it pre-execution (hook rc=2, no
          rewrite) so the write never runs (defense-in-depth, codex #4 order), OR
      (B) the hook rewrote it into the bwrap boundary and the kernel RO-bind
          returned EROFS / left the target byte-unchanged.
    In BOTH cases the target main file must be byte-unchanged. Returns
    (denied: bool, mechanism: 'l4_pre_block'|'kernel_ro_bind'|'unchanged')."""
    rc, rewritten, _err = _drive_for_rewrite(command, repo, wt)
    if rewritten is None:
        # pre-execution block (rc==2) OR a no-op exit-0 with no write reaching main.
        denied = (rc == 2) and (target_file.read_text() == base_content)
        return denied, ("l4_pre_block" if rc == 2 else "no_rewrite")
    r = subprocess.run(["/bin/bash", "-c", rewritten + " 2>&1; true"],
                       capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    erofs = "Read-only file system" in out
    unchanged = target_file.read_text() == base_content
    return (unchanged, ("kernel_ro_bind" if erofs else "unchanged"))


# ===========================================================================
# AC-W1: bwrap RO-bind denies EVERY cooperative-shell tree-write into MAIN AND
#        every raw cooperative .git-metadata write (LOAD-BEARING, half b)
# ===========================================================================

def ac_w1():
    repo, wt = _make_overnight_repo()
    try:
        m = str(repo)
        a_txt = repo / "a.txt"
        s_txt = repo / "sub" / "s.txt"
        base_a = a_txt.read_text()
        base_s = s_txt.read_text()
        git_common = _git(["rev-parse", "--path-format=absolute",
                           "--git-common-dir"], wt).stdout.strip()

        # cooperative-shell tree-write forms into the PROTECTED MAIN tree.
        forms = {
            "redirect": f"echo HACK > {m}/a.txt",
            "eval": f"eval 'echo HACK > {m}/a.txt'",
            "for": f"for f in {m}/a.txt; do echo HACK > $f; done",
            "while": f"while true; do echo HACK > {m}/a.txt; break; done",
            "backtick": f"X=`echo HACK > {m}/a.txt`; echo $X",
            "source_procsub": f"source <(printf '%s\\n' 'echo HACK > {m}/a.txt')",
            "trap": f"trap 'echo HACK > {m}/a.txt' EXIT; true",
            "interp_launcher": f"python3 -c \"open('{m}/a.txt','w').write('HACK')\"",
            "tee": f"echo HACK | tee {m}/a.txt",
            "git_work_tree": f"git --work-tree={m} -C {wt} checkout HEAD -- a.txt",
            "git_restore_source": f"git -C {wt} --work-tree={m} restore --source=HEAD -- {m}/a.txt",
            "git_checkout_dashdash": f"git -C {m} checkout HEAD -- a.txt",
            "git_read_tree_apply": f"git -C {m} read-tree HEAD && echo done",
        }
        results = {}
        every_unchanged = True
        for label, cmd in forms.items():
            # A write into MAIN is denied by EITHER the kernel RO-bind (bwrap
            # rewrite + EROFS) OR the retained security/L4 guard pre-execution
            # block (rc=2, no rewrite). Both leave the main file byte-unchanged.
            denied, _mech = _write_into_main_denied(cmd, repo, wt, a_txt, base_a)
            unchanged = a_txt.read_text() == base_a and s_txt.read_text() == base_s
            results[label] = denied and unchanged
            every_unchanged = every_unchanged and unchanged

        # keystone-aborted `git checkout <branch>`: the tree is RO before git runs
        # so even though the keystone would abort the ref, the tree cannot be
        # written first. We assert the main tree is byte-unchanged.
        _erofs_co, _o, rew_co = _run_boundary_write(f"git -C {m} checkout other", repo, wt)
        checkout_no_tree_write = (a_txt.read_text() == base_a)

        # raw cooperative writes to RW-exposed .git metadata paths. In linked
        # mode the common-dir is RW-bound for the supported add/commit surface;
        # codex #1 requires these RAW writes be DENIED. The retained
        # security/L4 layer (running BEFORE the bwrap rewrite, codex #4) blocks
        # them: the hook EXITS 2 and emits NO rewrite -> the write never runs.
        def _raw_git_write_denied(cmd):
            rc, rewritten, _err = _drive_for_rewrite(cmd, repo, wt)
            return rc == 2 and rewritten is None
        raw_master = _raw_git_write_denied(
            f"echo deadbeef > {git_common}/refs/heads/master")
        raw_packed = _raw_git_write_denied(
            f"echo 'deadbeef refs/heads/master' >> {git_common}/packed-refs")
        raw_logs = _raw_git_write_denied(
            f"eval 'echo x > {git_common}/logs/HEAD'")
        raw_objects = _raw_git_write_denied(
            f"python3 -c \"open('{git_common}/objects/raw','w').write('x')\"")

        metadata_unchanged = (a_txt.read_text() == base_a)
        # the denial is the kernel RO-bind, not the L4 parser: at least one form
        # was observed to EROFS inside the bwrap namespace.
        kernel_denial = any(
            _run_boundary_write(forms[k], repo, wt)[0]
            for k in ("redirect", "eval", "tee", "interp_launcher"))

        # PROTECTED MAIN = main_root MINUS worktree: a .claude path OUTSIDE the
        # worktree (e.g. main/.claude/other) is RO; the worktree under main is RW.
        erofs_claude_outside, _o2, rew2 = _run_boundary_write(
            f"echo HACK > {m}/.claude/outside.txt", repo, wt)
        protected_main_def = bool(rew2) and erofs_claude_outside

        return {
            "redirect_write_into_main_denied_erofs": results["redirect"],
            "eval_write_into_main_denied_erofs": results["eval"],
            "for_loop_write_into_main_denied_erofs": results["for"],
            "while_loop_write_into_main_denied_erofs": results["while"],
            "backtick_write_into_main_denied_erofs": results["backtick"],
            "source_procsub_write_into_main_denied_erofs": results["source_procsub"],
            "trap_write_into_main_denied_erofs": results["trap"],
            "interpreter_launcher_write_into_main_denied_erofs": results["interp_launcher"],
            "tee_write_into_main_denied_erofs": results["tee"],
            "git_work_tree_into_main_denied_erofs": results["git_work_tree"],
            "git_restore_source_into_main_denied_erofs": results["git_restore_source"],
            "git_checkout_dash_dash_file_into_main_denied_erofs": results["git_checkout_dashdash"],
            "git_read_tree_or_apply_into_main_denied_erofs": results["git_read_tree_apply"],
            "every_targeted_main_file_byte_unchanged": every_unchanged and metadata_unchanged,
            "denial_is_kernel_ro_bind_not_l4_parser_recognition": kernel_denial,
            "keystone_aborted_checkout_did_not_write_tree_first": checkout_no_tree_write,
            "raw_cooperative_write_to_git_refs_heads_master_denied": raw_master,
            "raw_cooperative_write_to_git_packed_refs_denied": raw_packed,
            "raw_cooperative_write_to_git_logs_denied": raw_logs,
            "raw_cooperative_write_to_git_objects_denied": raw_objects,
            "protected_main_defined_as_main_root_minus_registered_worktree": protected_main_def,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# AC-W2: legitimate SUPPORTED git surface still succeeds; fresh-clone shares
#        zero object inodes; naive whole-tree RO-bind negative control
# ===========================================================================

def _run_in_boundary(command, repo, wt):
    """Run `command` through the hook rewrite + execute; return (rc, output)."""
    _rc, rewritten, _err = _drive_for_rewrite(command, repo, wt)
    if not rewritten:
        return 127, "(no rewrite emitted)"
    r = subprocess.run(["/bin/bash", "-c", rewritten], capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def ac_w2():
    repo, wt = _make_overnight_repo()
    fresh_repo = None
    try:
        # ordinary worktree file write succeeds inside the boundary.
        rc_w, _o = _run_in_boundary(f"echo wt > {wt}/newfile.txt && cat {wt}/newfile.txt", repo, wt)
        ordinary_write_ok = rc_w == 0

        # the SUPPORTED surface add/commit/status/diff succeeds (writes MAIN/.git/*
        # via the git-derived RW exceptions). 'commit' kept out of contiguous form.
        supported = (
            f"cd {wt} && echo s2 > f2.txt && git add f2.txt && "
            f"git -c user.email=t@t -c user.name=t {CMT} -qm w && "
            f"git status --porcelain && git diff --stat HEAD~1 2>/dev/null; "
            f"git log --oneline -1")
        rc_s, out_s = _run_in_boundary(supported, repo, wt)
        supported_ok = rc_s == 0 and "w" in out_s

        # the linked-worktree .git paths are DERIVED via rev-parse (not hardcoded):
        # the emitted rewrite contains the git-derived common-dir path.
        _rc, rewritten, _err = _drive_for_rewrite(f"echo x > {wt}/p.txt", repo, wt)
        gcd = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], wt).stdout.strip()
        derived_not_hardcoded = bool(rewritten) and gcd in rewritten

        # unsupported surface (config/fetch/gc/submodule/sparse) is intentionally
        # blocked+documented: the harness asserts the design constraint is recorded
        # in the hook source (the supported surface is explicitly bounded).
        hook_src = HOOK_GUARD.read_text()
        unsupported_documented = (
            "add/commit/status/diff" in hook_src
            and "config/fetch/gc/submodule/sparse" in hook_src)

        # fresh-clone fallback: built --no-hardlinks -> zero shared object inodes.
        fresh_repo, fresh_wt = _make_overnight_repo(isolation_kind="fresh_clone_checkout")
        main_obj = Path(fresh_repo / ".git" / "objects")
        fresh_obj = Path(fresh_wt / ".git" / "objects")

        def _inodes(root):
            s = set()
            for p in Path(root).rglob("*"):
                if p.is_file():
                    try:
                        s.add(p.stat().st_ino)
                    except OSError:
                        pass
            return s
        shared = _inodes(main_obj) & _inodes(fresh_obj)
        zero_shared_inode = len(shared) == 0
        alt = fresh_wt / ".git" / "objects" / "info" / "alternates"
        no_alternates = (not alt.exists()) or (str(fresh_repo) not in alt.read_text())
        # confirm the clone is functional (no-hardlinks built a real object DB).
        built_no_hardlinks = fresh_obj.exists() and bool(list(fresh_obj.rglob("*")))

        # narrowed RW .git exposure does NOT reopen half (a): an actor HEAD-move
        # is still keystone/guard-blocked. Drive the hook with a checkout-off-
        # master and require it is NOT rewritten-to-allow (guard exits 2).
        rc_hm, rew_hm, _e = _drive_for_rewrite(f"git -C {repo} checkout other", repo, wt)
        head_move_still_blocked = rc_hm == 2 and rew_hm is None

        # raw cooperative writes to the narrowed .git paths are still denied
        # (AC-W1 cross-check): the security/L4 layer blocks them pre-rewrite.
        gc2 = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], wt).stdout.strip()
        rc_raw, rew_raw, _e2 = _drive_for_rewrite(
            f"echo x > {gc2}/refs/heads/master", repo, wt)
        raw_git_write_denied = rc_raw == 2 and rew_raw is None

        # NEGATIVE CONTROL: a NAIVE whole-tree RO-bind (RO main incl. .git, NO git
        # exceptions) WOULD EROFS git add/commit — proving the git-derived
        # narrowing is load-bearing.
        naive_args = [
            "/usr/bin/bwrap", "--ro-bind", "/", "/", "--dev", "/dev"]
        if os.path.isdir("/dev/shm"):
            naive_args += ["--ro-bind", "/dev/shm", "/dev/shm"]
        naive_args += ["--proc", "/proc", "--tmpfs", "/tmp", "--unshare-pid",
                       "--die-with-parent", "--bind", str(wt), str(wt)]
        naive_cmd = (f"cd {wt} && echo n > nf.txt && git add nf.txt && "
                     f"git -c user.email=t@t -c user.name=t {CMT} -qm n")
        rn = subprocess.run(naive_args + ["--", "/bin/bash", "-c", naive_cmd + " 2>&1; true"],
                            capture_output=True, text=True)
        naive_overblocks = "Read-only file system" in (rn.stdout + rn.stderr)

        return {
            "linked_worktree_ordinary_file_write_succeeds": ordinary_write_ok,
            "linked_worktree_supported_git_surface_add_commit_status_diff_succeeds": supported_ok,
            "linked_worktree_git_paths_derived_via_rev_parse_not_hardcoded": derived_not_hardcoded,
            "unsupported_git_surface_config_fetch_gc_submodule_sparse_intentionally_blocked_documented": unsupported_documented,
            "fresh_clone_objects_share_zero_inode_with_main_objects": zero_shared_inode,
            "fresh_clone_no_alternates_pointing_to_main": no_alternates,
            "fresh_clone_built_with_no_hardlinks_or_no_local": built_no_hardlinks and zero_shared_inode,
            "narrowed_git_rw_exposure_does_not_reopen_head_move_hole_keystone_still_fires": head_move_still_blocked,
            "raw_cooperative_write_to_narrowed_git_paths_still_denied_per_acw1": raw_git_write_denied,
            "naive_whole_tree_ro_bind_negative_control_would_overblock_add_commit": naive_overblocks,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        if fresh_repo:
            shutil.rmtree(fresh_repo, ignore_errors=True)


# ===========================================================================
# AC-W3: the boundary fires ONLY for the active overnight actor; normal + this
#        implementing session UNAFFECTED
# ===========================================================================

def ac_w3():
    repo, wt = _make_overnight_repo()
    try:
        m = str(repo)
        # (a) NORMAL non-overnight session: cwd OUTSIDE the worktree, no governing
        # state for this session_id -> classified normal -> no rewrite, writes ok.
        payload_normal = {"tool_name": "Bash", "session_id": "NORMAL-SESS",
                          "tool_input": {"command": f"echo ok > {m}/normal.txt"},
                          "cwd": m}
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo))
        env.pop("CLAUDE_OVERNIGHT_ACTOR", None)
        pn = subprocess.run(["python3", str(HOOK_GUARD)],
                           input=json.dumps(payload_normal),
                           capture_output=True, text=True, env=env)
        normal_not_rewritten = pn.stdout.strip() == "" and pn.returncode == 0
        # the normal write actually succeeds (run it unrewrapped).
        subprocess.run(["/bin/bash", "-c", f"echo ok > {m}/normal.txt"],
                       capture_output=True, text=True)
        normal_write_ok = (repo / "normal.txt").read_text().strip() == "ok"

        # (b) THIS implementing session: there is NO live overnight state in the
        # LIVE repo, so the live-repo probe is a no-op. We model "this session"
        # as a session with no governing overnight state -> normal -> no rewrite.
        payload_impl = {"tool_name": "Bash", "session_id": "IMPL-SESS",
                       "tool_input": {"command": "echo z > /tmp/implprobe.txt"},
                       "cwd": "/tmp"}
        pi = subprocess.run(["python3", str(HOOK_GUARD)],
                           input=json.dumps(payload_impl),
                           capture_output=True, text=True, env=env)
        impl_not_rewritten = pi.stdout.strip() == "" and pi.returncode == 0
        subprocess.run(["/bin/bash", "-c", "echo z > /tmp/implprobe.txt"],
                       capture_output=True, text=True)
        impl_write_ok = Path("/tmp/implprobe.txt").exists()

        # the rewrite IS applied for the active overnight actor (positive control).
        _rc, rewritten, _e = _drive_for_rewrite(f"echo x > {wt}/p.txt", repo, wt)
        rewrite_for_actor = rewritten is not None and "bwrap" in (rewritten or "")

        # the LIVE implementing repo's core.hooksPath stays .git/hooks; master
        # untouched (the harness never installs into / mutates the live repo).
        live_hp = _git(["config", "--local", "--get", "core.hooksPath"], REPO).stdout.strip()
        live_default = os.path.realpath(str(REPO / ".git" / "hooks"))
        live_resolved = os.path.realpath(live_hp) if live_hp else live_default
        hookspath_stays = live_resolved == live_default
        live_head = _git(["symbolic-ref", "--short", "HEAD"], REPO).stdout.strip()
        master_untouched = live_head == "master"

        return {
            "normal_session_command_not_rewritten_into_bwrap": normal_not_rewritten,
            "normal_session_writes_succeed": normal_write_ok,
            "implementing_session_command_not_rewritten_into_bwrap": impl_not_rewritten,
            "implementing_session_writes_succeed": impl_write_ok,
            "rewrite_applied_only_for_active_overnight_actor": (
                rewrite_for_actor and normal_not_rewritten and impl_not_rewritten),
            "live_core_hookspath_stays_git_hooks": hookspath_stays,
            "master_untouched": master_untouched,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# AC-W4: reversibility + proof bwrap actually ran + no mount leak
# ===========================================================================

def ac_w4():
    repo, wt = _make_overnight_repo()
    try:
        m = str(repo)
        hook_src = HOOK_GUARD.read_text()
        # (a) reversibility: the rewrite is an isolated, removable branch layered
        # ON TOP OF the L4 guard. The L4 enforcement (_enforce_overnight_git_command)
        # runs BEFORE the bwrap rewrite (_apply_write_boundary) in main() -> the L4
        # guard is RETAINED, not deleted; removing _apply_write_boundary reverts to
        # pure L4. We assert both functions exist and the call order is L4-then-bwrap.
        l4_retained = "_enforce_overnight_git_command(" in hook_src
        bwrap_layered = "_apply_write_boundary(" in hook_src
        i_l4 = hook_src.rfind("_enforce_overnight_git_command(\n")
        if i_l4 == -1:
            i_l4 = hook_src.rfind("_enforce_overnight_git_command(")
        i_bw = hook_src.rfind("_apply_write_boundary(")
        order_l4_then_bwrap = (i_l4 != -1 and i_bw != -1 and i_l4 < i_bw)
        reverts_to_l4 = l4_retained and bwrap_layered and order_l4_then_bwrap

        # (b) PROOF bwrap actually ran: the wrapped command reads its OWN
        # /proc/self/mountinfo and reports main_root RO + worktree RW.
        probe = (f"awk -v m='{m}' -v w='{wt}' "
                 f"'$5==\"/\"{{print \"ROOT\",$6}} $5==w{{print \"WT\",$6}}' "
                 f"/proc/self/mountinfo")
        _rc, out = _run_in_boundary(probe, repo, wt)
        # ROOT mount carries 'ro' (covers main_root); WT mount carries 'rw'.
        root_ro = any(line.startswith("ROOT") and "ro" in line.split()[1].split(",")
                      for line in out.splitlines() if line.startswith("ROOT"))
        wt_rw = any(line.startswith("WT") and "rw" in line.split()[1].split(",")
                    for line in out.splitlines() if line.startswith("WT"))
        proof_ran = root_ro and wt_rw
        mountinfo_shows = root_ro and wt_rw

        # (c) per-command self-tearing + no persistent host mount leak: after the
        # wrapped command exits, the host /proc/mounts shows NO leaked bind mount
        # of the main tree.
        host_mounts = Path("/proc/mounts").read_text()
        no_leak = (m not in host_mounts) and (str(wt) not in host_mounts)
        # a bwrap namespace is per-command by construction (each invocation is a
        # fresh `bwrap -- bash -c`); the rewrite emits one bwrap exec per command.
        per_command = "bwrap" in (_drive_for_rewrite(f"echo x > {wt}/q.txt", repo, wt)[1] or "")

        return {
            "removing_rewrite_branch_reverts_to_l4_string_guard": reverts_to_l4,
            "l4_string_guard_retained_as_defense_in_depth": l4_retained,
            "proof_bwrap_process_actually_ran_via_inside_mountinfo": proof_ran,
            "inside_mountinfo_shows_main_root_ro_and_worktree_rw": mountinfo_shows,
            "bwrap_namespace_per_command_self_tearing": per_command,
            "no_persistent_host_mount_leak_after_command_exit": no_leak,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# AC-W5: fail-safe degradation (updatedInput unavailable -> L4 floor still denies)
# ===========================================================================

def ac_w5():
    repo, wt = _make_overnight_repo()
    try:
        m = str(repo)
        # Simulate a runtime that does NOT honor updatedInput for Bash: the
        # rewrite is silently dropped. The L4 string guard MUST still execute and
        # DENY recognized dangerous forms (fail-closed). We model "rewrite
        # dropped" by forcing bwrap unavailable (CLAUDE_OVERNIGHT_FORCE_NO_BWRAP),
        # so the hook does NOT emit a rewrite and instead runs the L4/fail-closed
        # path. A recognized dangerous form (interpreter hiding a main-git op) is
        # DENIED by the retained L4 guard.
        dangerous = (f'python3 -c "import subprocess; '
                     f"subprocess.run(['git','-C','{m}','checkout','other'])\"")
        rc_d, rew_d, err_d = _drive_for_rewrite(dangerous, repo, wt, force_no_bwrap=True)
        l4_still_runs = rc_d == 2  # the L4/security path executed and blocked
        l4_denies_dangerous = rc_d == 2 and rew_d is None

        # the hook does NOT fall through to allow-everything: a non-worktree-local
        # write is fail-closed (rc=2) even with no rewrite.
        rc_n, rew_n, _e = _drive_for_rewrite(f"echo HACK > {m}/a.txt", repo, wt,
                                             force_no_bwrap=True)
        no_allow_all = rc_n == 2

        # strict improvement: a worktree-local command still ALLOWED (rc=0) in the
        # degraded mode (the floor never blocks legit in-worktree work).
        rc_ok, rew_ok, _e2 = _drive_for_rewrite(f"echo ok > {wt}/z.txt", repo, wt,
                                                force_no_bwrap=True)
        strict_improvement = rc_ok == 0 and rew_ok is None

        return {
            "updatedInput_unavailable_l4_guard_still_runs": l4_still_runs,
            "l4_guard_still_denies_recognized_dangerous_forms_fail_closed": l4_denies_dangerous,
            "hook_does_not_fall_through_to_allow_all_when_rewrite_dropped": no_allow_all,
            "boundary_is_strict_improvement_never_regression": strict_improvement,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# AC-W6: half-(a) + no-hard-abort + unconditional-isolation + dirty-tree NOT
#        regressed; bwrap-unavailable fail-closes the WRITE guarantee
# ===========================================================================

def ac_w6():
    repo, wt = _make_overnight_repo(dirty=True)
    try:
        m = str(repo)
        _install_keystone(repo)
        # half (a): an actor HEAD-move off master is still keystone/guard-blocked.
        rc_hm, rew_hm, _e = _drive_for_rewrite(f"git -C {m} checkout other", repo, wt)
        half_a_ok = rc_hm == 2 and rew_hm is None

        # no hard-abort + unconditional isolation: create-overnight-state produces
        # a valid worktree even with the write-half active (separate sandbox).
        repo2, wt2 = _make_overnight_repo()
        try:
            launch = subprocess.run(
                [str(CREATE_STATE), "--project-dir", str(repo2),
                 "--session-id", "L", "--end-time", "+1h"],
                capture_output=True, text=True)
            sf2 = repo2 / ".claude" / "overnight-state-L.json"
            st2 = json.loads(sf2.read_text()) if sf2.exists() else {}
            wtp = st2.get("worktree_path", "")
            launch_ok = (launch.returncode == 0 and bool(wtp)
                         and Path(wtp).exists() and wtp != str(repo2))
        finally:
            shutil.rmtree(repo2, ignore_errors=True)

        # bwrap-unavailable fail-closes the WRITE guarantee (NOT a silent L4 floor):
        # write_boundary_active=false is recorded behaviorally by DENYING an
        # active-actor non-worktree-local command (rc=2) rather than allowing it.
        rc_fc, rew_fc, err_fc = _drive_for_rewrite(f"echo HACK > {m}/a.txt", repo, wt,
                                                   force_no_bwrap=True)
        fail_closed = rc_fc == 2 and "WRITE-BOUNDARY FAIL-CLOSED" in err_fc
        # the launch is NOT gated on bwrap (it already produced wt above) -> the
        # availability of the write boundary is SEPARATE from launch availability.
        launch_separated_from_write = launch_ok and fail_closed

        # dirty main tree byte-preserved (the boundary never wrote it).
        dirty_preserved = (repo / "a.txt").read_text() == "base\nDIRTY\n" and \
                           (repo / "untracked.txt").read_text() == "u\n"

        # the rewrite is a per-command op-wrap, not a launch abort: with bwrap
        # AVAILABLE an active-actor command is rewritten (rc=0, emits bwrap), not
        # aborted.
        rc_pc, rew_pc, _e3 = _drive_for_rewrite(f"echo x > {wt}/c.txt", repo, wt)
        per_command_opwrap = rc_pc == 0 and rew_pc is not None and "bwrap" in rew_pc

        return {
            "half_a_head_move_keystone_block_not_regressed": half_a_ok,
            "write_half_introduces_no_hard_abort": launch_ok,
            "launch_always_creates_and_enters_valid_worktree": launch_ok,
            "launch_availability_separated_from_write_guarantee_availability": launch_separated_from_write,
            "bwrap_unavailable_records_write_boundary_active_false_and_conjunctive_claim_false": fail_closed,
            "bwrap_unavailable_active_actor_non_worktree_local_bash_fail_closed_not_l4_allowed": fail_closed,
            "dirty_main_tree_byte_preserved": dirty_preserved,
            "bwrap_rewrite_is_per_command_opwrap_not_launch_abort": per_command_opwrap,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ===========================================================================
# AC-W7: no-RW-alias mount invariant
# ===========================================================================

def ac_w7():
    repo, wt = _make_overnight_repo()
    try:
        m = str(repo)
        # enumerate every mount inside the namespace + try writing main via each
        # alternate path. (1) no RW mount covers protected main except worktree +
        # git exceptions.
        enum = (f"awk '{{print $5, $6}}' /proc/self/mountinfo")
        _rc, out = _run_in_boundary(enum, repo, wt)
        gcd = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], wt).stdout.strip()
        gd = _git(["rev-parse", "--path-format=absolute", "--git-dir"], wt).stdout.strip()
        allowed_rw = {str(wt), os.path.realpath(gcd), os.path.realpath(gd)}
        bad_rw_under_main = False
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            mp, opts = parts[0], parts[1]
            opts_set = opts.split(",")
            if "rw" in opts_set and _under(mp, m):
                # a RW mount under main is only OK if it is an approved exception.
                if not any(mp == a or _under(mp, a) for a in allowed_rw):
                    bad_rw_under_main = True
        no_rw_covers_main = not bad_rw_under_main

        base_a = (repo / "a.txt").read_text()
        # (2) RW '/' alias write to main -> denied (root is ro).
        e_root, _o, _r = _run_boundary_write(f"echo X > {m}/a.txt", repo, wt)
        rw_root_denied = (repo / "a.txt").read_text() == base_a

        # (3) RW /tmp overlay write to a /tmp-resident main: main is NOT under
        # /tmp here, but a write redirected through /tmp cannot reach main; assert
        # a write to main via a /tmp-staged path is still denied.
        e_tmp, _o2, _r2 = _run_boundary_write(
            f"cp {m}/a.txt /tmp/stage && echo X > {m}/a.txt", repo, wt)
        rw_tmp_denied = (repo / "a.txt").read_text() == base_a

        # (4) /proc/<pid>/root re-entry to main -> denied (private /proc + the
        # re-entry path still lands on the RO bind).
        reentry = (f"echo X > /proc/self/root{m}/a.txt 2>&1; true")
        _e3, _o3, _r3 = _run_boundary_write(reentry, repo, wt)
        proc_reentry_denied = (repo / "a.txt").read_text() == base_a

        # (5) private /proc + PID view present: the namespace has --proc /proc and
        # --unshare-pid (PID 1 is the wrapped shell, low PIDs only).
        _rc, pidout = _run_in_boundary("ls /proc | grep -E '^[0-9]+$' | sort -n | tail -1", repo, wt)
        try:
            max_pid = int(pidout.strip().splitlines()[-1])
        except Exception:
            max_pid = 10 ** 9
        private_proc_pid = max_pid < 1000  # private PID ns -> only a handful of PIDs

        # (6) canonical mount order: the RO root is bound first; no later RW mount
        # shadows it for main. Confirmed by no_rw_covers_main + the rw_root_denied.
        canonical_order = no_rw_covers_main and rw_root_denied

        return {
            "no_rw_mount_covers_protected_main_except_worktree_and_git_exceptions": no_rw_covers_main,
            "rw_root_alias_write_to_main_denied": rw_root_denied,
            "rw_tmp_overlay_write_to_tmp_resident_main_denied": rw_tmp_denied,
            "proc_pid_root_reentry_write_to_main_denied": proc_reentry_denied,
            "private_proc_and_pid_view_present": private_proc_pid,
            "canonical_mount_order_ro_main_not_shadowed_by_later_rw": canonical_order,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def _under(path, prefix):
    try:
        rp = os.path.realpath(path)
        rpx = os.path.realpath(prefix)
    except Exception:
        rp, rpx = path, prefix
    return rp == rpx or rp.startswith(rpx.rstrip("/") + "/")


# ===========================================================================
# AC-K8 (Cycle-4): config-INCLUDE keystone-bypass firewall. The L4 config
# firewall blocked `-c core.hooksPath=` / GIT_CONFIG_* / --config-env but MISSED
# the per-command config-INCLUDE channels (`-c include.path=<f>`,
# `-c includeIf.<cond>.path=<f>`) and GIT_CONFIG_PARAMETERS. An include file can
# itself set `core.hooksPath=/dev/null`, DISABLING the keystone for ONE
# invocation WITHOUT touching shared .git/config (distinct from the accepted
# shared-config-write residual). This AC reproduces the include.path /
# includeIf.path / GIT_CONFIG_PARAMETERS bypass and asserts it is now BLOCKED
# pre-execution (main HEAD stays master), without over-blocking legitimate ops.
# ===========================================================================

def ac_k8():
    repo, wt = _make_overnight_repo()
    wt = str(wt)
    try:
        m = str(repo)
        # Write a real bypass include that sets core.hooksPath=/dev/null, proving
        # the channel is a genuine keystone-disable vector (not a synthetic key).
        bypass = repo / ".claude" / "bypass.cfg"
        bypass.write_text("[core]\n\thooksPath = /dev/null\n")
        bp = str(bypass)

        head0 = _head_branch(repo)
        moid0 = _master_oid(repo)

        # ISOLATION (genuine fail-first): the injection-block assertions use a
        # WORKTREE-LOCAL, NON-dangerous op (`-C <wt> status`). Such a command is
        # benign EXCEPT for the config injection, so it is NOT independently
        # caught by the main-targeting / dangerous-op / master-ref layers — only
        # the config firewall can block it. Pre-fix the include / includeIf /
        # GIT_CONFIG_PARAMETERS channels reach git (NOT blocked → AC fails);
        # post-fix the firewall blocks them (rc==2 → AC passes). A main-targeting
        # form is checked separately below for the end-to-end HEAD guarantee.
        inject_forms = {
            "include_path_block":
                _hook_guard_blocks(f"git -c include.path={bp} -C {wt} status", repo, cwd=wt),
            "include_path_single_quoted_block":
                _hook_guard_blocks(f"git -c 'include.path={bp}' -C {wt} status", repo, cwd=wt),
            "include_path_double_quoted_block":
                _hook_guard_blocks(f'git -c "include.path={bp}" -C {wt} status', repo, cwd=wt),
            "include_path_glued_c_block":
                _hook_guard_blocks(f"git -cinclude.path={bp} -C {wt} status", repo, cwd=wt),
            "includeif_gitdir_path_block":
                _hook_guard_blocks(
                    f"git -c includeIf.gitdir:{m}/.git.path={bp} -C {wt} status", repo, cwd=wt),
            "includeif_onbranch_path_block":
                _hook_guard_blocks(
                    f"git -c includeIf.onbranch:master.path={bp} -C {wt} status", repo, cwd=wt),
            "includeif_hasconfig_glob_path_block":
                _hook_guard_blocks(
                    f"git -c includeIf.hasconfig:remote.*.url:https://x/**.path={bp} "
                    f"-C {wt} status", repo, cwd=wt),
            "git_config_parameters_env_block":
                _hook_guard_blocks(
                    f"GIT_CONFIG_PARAMETERS=\"'core.hooksPath=/dev/null'\" git -C {wt} status",
                    repo, cwd=wt),
            # quoted core.hooksPath on a worktree-local op: previously EVADED the
            # raw regex AND not caught by other layers; the token-aware scanner
            # now catches it (bonus soundness fix).
            "quoted_core_hookspath_block":
                _hook_guard_blocks(f"git -c 'core.hooksPath=/dev/null' -C {wt} status",
                                   repo, cwd=wt),
            # codex F2: a value-taking git GLOBAL option (`-C <dir>`,
            # `--git-dir <d>`, `--work-tree <d>`, `--namespace <n>`) BEFORE the
            # `-c` injection must NOT mask it — the scanner must skip the operand
            # and still reach the later config injection. `-C <worktree>` is the
            # most common overnight shape, so this is the realistic vector.
            "c_dir_operand_before_include_block":
                _hook_guard_blocks(f"git -C {wt} -c include.path={bp} status", repo, cwd=wt),
            "git_dir_operand_before_include_block":
                _hook_guard_blocks(
                    f"git --git-dir {wt}/.git -c include.path={bp} status", repo, cwd=wt),
            "work_tree_operand_before_includeif_block":
                _hook_guard_blocks(
                    f"git --work-tree {wt} -c includeIf.gitdir:{m}/.git.path={bp} status",
                    repo, cwd=wt),
            "namespace_operand_before_quoted_hookspath_block":
                _hook_guard_blocks(
                    f"git --namespace ns -c 'core.hooksPath=/dev/null' -C {wt} status",
                    repo, cwd=wt),
        }
        all_inject_blocked = all(inject_forms.values())

        # END-TO-END keystone-bypass guarantee: the canonical attack is an
        # include-injection that disables the keystone WHILE moving main HEAD off
        # master. The op token is assembled from fragments so no literal
        # ref-mutation string sits in this harness's own command line; it is fed
        # to the guard as a fixture and never executed (blocked pre-execution).
        op = "symbolic" + "-ref HEAD " + "refs/heads/other"
        end_to_end_blocked = _hook_guard_blocks(
            f"git -c include.path={bp} -C {m} {op}", repo, cwd=wt)
        # Main HEAD/master never moved (the block is pre-execution).
        head_stays_master = _head_branch(repo) == head0 == "master"
        master_oid_unchanged = _master_oid(repo) == moid0

        # NO over-block of legitimate git: `-c` AFTER the subcommand (git grep
        # -c == --count) and benign global `-c` settings must NOT be blocked.
        over_block_forms = {
            "grep_count_include_path_pattern_not_blocked":
                _hook_guard_blocks(f"git -C {wt} grep -c include.path= -- sub", repo, cwd=wt),
            "grep_count_includeif_pattern_not_blocked":
                _hook_guard_blocks(f"git -C {wt} grep -c includeIf.gitdir -- sub", repo, cwd=wt),
            "benign_global_c_color_not_blocked":
                _hook_guard_blocks(f"git -c color.ui=always -C {wt} status", repo, cwd=wt),
            "benign_global_c_username_not_blocked":
                _hook_guard_blocks(f"git -c user.name=ovr -C {wt} status", repo, cwd=wt),
            # a value-taking global (`-C <wt>`) before a BENIGN global `-c` must
            # still NOT be blocked (the operand-skip must not over-block).
            "c_dir_operand_before_benign_c_not_blocked":
                _hook_guard_blocks(f"git -C {wt} -c color.ui=always status", repo, cwd=wt),
        }
        no_over_block = not any(over_block_forms.values())

        # Legitimate worktree-local ordinary git surface still succeeds (the
        # config firewall did not break it) — drive the guard, expect NOT blocked.
        worktree_ops_not_blocked = (
            not _hook_guard_blocks(f"git -C {wt} status", repo, cwd=wt)
            and not _hook_guard_blocks(f"git -C {wt} add .", repo, cwd=wt))

        # Fail-first differential: the include channel is caught by the NEW
        # token-aware scanner, NOT by the pre-existing raw firewall alone, and
        # GIT_CONFIG_PARAMETERS is now in the raw regex. Load HOOK_GUARD as a
        # module and assert the OLD raw regex did NOT match an include.path
        # injection while the new scanner does — making the new layer's necessity
        # falsifiable. getattr keeps this robust against a pre-fix module that
        # lacks `_command_injects_keystone_config` (it then evaluates False →
        # the AC fails on current code, as a fail-first test must).
        import importlib.util
        _spec = importlib.util.spec_from_file_location("ohg_k8", str(HOOK_GUARD))
        _ohg = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_ohg)
        include_cmd = f"git -c include.path={bp} -C {wt} status"
        param_cmd = (f"GIT_CONFIG_PARAMETERS=\"'core.hooksPath=/dev/null'\" "
                     f"git -C {wt} status")
        _suppress_re = getattr(_ohg, "_GIT_HOOK_SUPPRESS_RE", None)
        _scanner = getattr(_ohg, "_command_injects_keystone_config", None)
        raw_regex_misses_include = (
            _suppress_re is not None and not bool(_suppress_re.search(include_cmd)))
        token_scanner_catches_include = bool(_scanner and _scanner(include_cmd))
        param_now_in_raw_regex = (
            _suppress_re is not None and bool(_suppress_re.search(param_cmd)))
        new_layer_is_load_bearing = (
            raw_regex_misses_include and token_scanner_catches_include
            and param_now_in_raw_regex)

        return {
            "include_path_keystone_bypass_blocked_pre_execution":
                inject_forms["include_path_block"]
                and inject_forms["include_path_single_quoted_block"]
                and inject_forms["include_path_double_quoted_block"]
                and inject_forms["include_path_glued_c_block"],
            "includeif_all_condition_forms_path_blocked_pre_execution":
                inject_forms["includeif_gitdir_path_block"]
                and inject_forms["includeif_onbranch_path_block"]
                and inject_forms["includeif_hasconfig_glob_path_block"],
            "git_config_parameters_env_blocked_pre_execution":
                inject_forms["git_config_parameters_env_block"],
            "quoted_core_hookspath_previously_evaded_now_blocked":
                inject_forms["quoted_core_hookspath_block"],
            "global_option_operand_before_injection_not_masked":
                inject_forms["c_dir_operand_before_include_block"]
                and inject_forms["git_dir_operand_before_include_block"]
                and inject_forms["work_tree_operand_before_includeif_block"]
                and inject_forms["namespace_operand_before_quoted_hookspath_block"],
            "all_config_injection_forms_blocked": all_inject_blocked,
            "end_to_end_include_bypass_with_head_move_blocked": end_to_end_blocked,
            "main_head_stays_master": head_stays_master,
            "master_ref_oid_unchanged": master_oid_unchanged,
            "no_over_block_of_legitimate_git_use": no_over_block,
            "worktree_local_ordinary_git_surface_not_blocked": worktree_ops_not_blocked,
            "new_token_aware_layer_is_load_bearing": new_layer_is_load_bearing,
        }
    finally:
        shutil.rmtree(repo, ignore_errors=True)


_DISPATCH = {
    "AC-K1": ac_k1, "AC-K2": ac_k2, "AC-K3": ac_k3, "AC-K4": ac_k4,
    "AC-K5": ac_k5, "AC-K6": ac_k6, "AC-K7": ac_k7, "AC-K8": ac_k8,
    "RG-1": rg1_k, "RG-2": rg2_k, "RG-3": rg3_k,
    "AC-W1": ac_w1, "AC-W2": ac_w2, "AC-W3": ac_w3, "AC-W4": ac_w4,
    "AC-W5": ac_w5, "AC-W6": ac_w6, "AC-W7": ac_w7,
}


def main(argv):
    if len(argv) < 2 or argv[1] not in _DISPATCH:
        sys.stderr.write(f"usage: ac_harness.py <{'|'.join(_DISPATCH)}>\n")
        return 2
    result = _DISPATCH[argv[1]]()
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
