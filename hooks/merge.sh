#!/usr/bin/env bash
# merge.sh - wrapper for /merge slash command
#
# Why this exists: pretool-git-privilege-guard.py raw-greps for the literal
# string "git" + space + "merge" in command text and rejects it unless the
# env var CLAUDE_MERGE_COMMAND_ACTIVE=1 is set in the hook's process env.
# main-agent shell never has that env set, so the inline checkout+merge
# pattern in merge.md was unrunnable from agent context. This wrapper runs
# the merge in its OWN subprocess (which does not go through main-agent
# PreToolUse), exporting the env var locally so the privilege-guard inside
# the subprocess admits the inner command.
#
# Sentinel check mirrors commit.sh/push.sh (2026-04-28 SlashCommand-bypass plug).
#
# 2026-10-06 (merge-source generalization). The merge source is ANY resolvable
# commit-ish, not just a local branch head:
#   * local branch            master, worktree-overnight-...
#   * remote-tracking ref     origin/master, refs/remotes/origin/master
#   * tag                     v1.2.3 (annotated tags are peeled to their commit)
#   * bare commit hash        fa0aea69ccede...
# `git merge` itself always accepted all four; what rejected the last three was
# this wrapper's own `refs/heads/<name>` existence probe plus a cleanup section
# that assumed a deletable branch and a registered worktree always exist. Both
# are fixed here: validation is now "does it resolve to a commit object", and
# every lifecycle-cleanup step is conditional on the artifact actually being
# present. A ref shape with no branch and no worktree is the EXPECTED state for
# a remote ref / tag / hash, so each missing artifact is announced and skipped,
# never treated as a failure.
#
# Three behaviours are deliberately NOT relaxed by that generalization:
#   1. Self-merge (source and target resolve to the SAME commit) is refused
#      with a non-zero exit.
#   2. Every pre-existing safety check still runs on every ref shape: the
#      in_place clean-tree precondition, the untracked-overlap preflight, and
#      (upstream of this wrapper) merge-analyst's conflict-marker pre-check and
#      the merge-analyst grant that pretool-git-privilege-guard.py binds.
#   3. The post-merge invariant is still enforced before any cleanup runs.
set -euo pipefail

# Sentinel enforcement is handled by pretool-wrapper-userintent.py (PreToolUse hook)
# before this script runs. The wrapper itself stays pure git work.

# WS1: resolve the harness home from this script's own location (hooks/merge.sh
# -> harness home) via the shared resolver, so helper paths + the project-dir
# default work on a fresh non-root clone instead of the author literal /root.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/claude_home.sh"
# Degrade to $HOME/.claude on a resolver miss instead of hard-aborting under
# `set -e` (matches push.sh / apply-permissions.sh / resolve-close-report.sh).
CLAUDE_HOME="$(claude_home_resolve || echo "${HOME}/.claude")"

usage() {
  cat >&2 <<'EOF'
Usage: merge.sh [--no-commit] <ref>

  <ref>         Any resolvable commit-ish to merge into the default branch:
                a local branch, a remote-tracking ref (origin/master), a tag,
                or a bare commit hash.
  --no-commit   Apply the merge to the index and working tree but stop before
                creating the merge commit, so the rollback is the single step
                `git merge --abort`. Implies --no-ff (git cannot hold a
                fast-forward uncommitted). Lifecycle cleanup is skipped in this
                mode because no merge commit exists yet; re-run without
                --no-commit after committing to execute it.
EOF
}

# ─── Args ────────────────────────────────────────────────────────────────
NO_COMMIT=false
SOURCE_REF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-commit)
      NO_COMMIT=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "merge.sh: unknown option: $1" >&2
      usage
      exit 2
      ;;
    *)
      if [ -n "$SOURCE_REF" ]; then
        echo "merge.sh: unexpected extra argument: $1 (exactly one merge source is accepted)" >&2
        exit 2
      fi
      SOURCE_REF="$1"
      ;;
  esac
  shift
done

if [ -z "$SOURCE_REF" ]; then
  echo "merge.sh: merge source required" >&2
  usage
  exit 2
fi

# Resolve default branch via existing helper (under the resolved harness home)
DEFAULT_BRANCH="$("${CLAUDE_HOME}/scripts/derive-default-branch.sh")"
if [ -z "$DEFAULT_BRANCH" ]; then
  echo "merge.sh: could not resolve default branch" >&2
  exit 1
fi

# ─── Source resolution ───────────────────────────────────────────────────
# The requirement is "the source names a commit this repository has", so ask
# exactly that. `^{commit}` peels annotated tags down to their commit, and
# --verify makes an ambiguous or unknown name a hard failure rather than a
# silent empty string.
#
# Do NOT reintroduce a `refs/heads/` existence probe (e.g.
# `git show-ref --verify --quiet refs/heads/<name>`): it hard-codes "the
# source is a local branch head", so it rejects the remote-tracking ref, tag,
# and bare commit hash this wrapper accepts.
SOURCE_SHA="$(git rev-parse --verify --quiet "${SOURCE_REF}^{commit}" 2>/dev/null || true)"
if [ -z "$SOURCE_SHA" ]; then
  echo "merge.sh: '$SOURCE_REF' does not resolve to a commit object in this repository" >&2
  echo "  (accepted: local branch, remote-tracking ref, tag, or commit hash)" >&2
  exit 1
fi

# Full symbolic ref name, when the source IS a ref. Empty for a bare commit
# hash. This is what decides whether the lifecycle-cleanup section has anything
# to act on -- only a refs/heads/* source can have a branch to delete, a
# registered worktree, or a matching overnight-state file.
SOURCE_FULLREF="$(git rev-parse --symbolic-full-name "$SOURCE_REF" 2>/dev/null || true)"
SOURCE_LOCAL_BRANCH=""
case "$SOURCE_FULLREF" in
  refs/heads/*) SOURCE_LOCAL_BRANCH="${SOURCE_FULLREF#refs/heads/}" ;;
esac

DEFAULT_SHA="$(git rev-parse --verify --quiet "refs/heads/${DEFAULT_BRANCH}^{commit}" 2>/dev/null || true)"
if [ -z "$DEFAULT_SHA" ]; then
  echo "merge.sh: default branch '$DEFAULT_BRANCH' has no local ref (refs/heads/$DEFAULT_BRANCH)" >&2
  exit 1
fi

# ─── Self-merge refusal ──────────────────────────────────────────────────
# Refused when the resolved source and the resolved target are the SAME commit.
# The refusal message below is the single home for WHY.
#
# Scope note: this rejects ONLY an exact same-commit pair. A source that is a
# strict ancestor of the target is still allowed through to git's genuine
# "Already up to date" path, which is what makes re-running this wrapper after
# a completed merge idempotent (merge is a no-op, cleanup still runs).
if [ "$SOURCE_SHA" = "$DEFAULT_SHA" ]; then
  cat >&2 <<EOF
merge.sh: refusing self-merge — source and target are the same commit.
  source ref    : $SOURCE_REF -> $SOURCE_SHA
  target branch : $DEFAULT_BRANCH -> $DEFAULT_SHA
There is nothing to merge. git would report this as "Already up to date" and
exit 0, which is indistinguishable from a real merge to any caller inspecting
only the exit code, so it is rejected explicitly instead.
Pass a ref that actually differs from $DEFAULT_BRANCH.
EOF
  exit 2
fi

# In-place vs linked worktree detection (commands/dev-overnight.md's own
# isolation_kind vocabulary: "in_place" == worktree_path equals main_root).
# A linked (registered_worktree) worktree is always distinct from the main
# one (scripts/create-worktree.sh::validate_worktree enforces rp_wt != rp_main
# at creation time), so nothing else uses that directory while /merge runs.
# cwd being the main root carries no such exclusivity guarantee -- other
# sessions may hold uncommitted edits here right now -- so the checks below
# give that shape the equivalent safety the linked shape gets for free.
MAIN_WORKTREE_PATH="$(git worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2; exit}')"
CURRENT_TOPLEVEL="$(git rev-parse --show-toplevel)"
IS_IN_PLACE=false
if [ -n "$MAIN_WORKTREE_PATH" ] && [ "$(realpath "$MAIN_WORKTREE_PATH" 2>/dev/null)" = "$(realpath "$CURRENT_TOPLEVEL" 2>/dev/null)" ]; then
  IS_IN_PLACE=true
fi

# Clean-tree precondition (in_place only). It applies to EVERY source ref
# shape: it guards the DIRECTORY the merge lands in, not the ref being merged.
# Do NOT gate it on the shape of the source ref.
if [ "$IS_IN_PLACE" = true ]; then
  DIRTY="$(git status --porcelain)"
  if [ -n "$DIRTY" ]; then
    echo "merge.sh: refusing to merge in_place with uncommitted changes present (equivalent of the linked worktree's exclusivity guarantee -- this directory may be shared with other sessions):" >&2
    echo "$DIRTY" >&2
    exit 2
  fi
fi

# Untracked-overlap preflight (spec 5.2.1.3 R3b). The two diff endpoints are
# the RESOLVED shas, which is what makes one comparison serve every source
# shape. Do NOT reintroduce branch names as the endpoints: a bare commit hash
# has no branch name, and a remote-tracking ref or tag is not a branch head.
OVERLAP="$(git ls-files --others --exclude-standard | sort -u)"
if [ -n "$OVERLAP" ]; then
  TOUCHED="$(git diff --name-only "$DEFAULT_SHA" "$SOURCE_SHA" | sort -u)"
  CONFLICTS="$(comm -12 <(echo "$OVERLAP") <(echo "$TOUCHED") || true)"
  if [ -n "$CONFLICTS" ]; then
    echo "untracked overlap detected:" >&2
    echo "$CONFLICTS" >&2
    exit 2
  fi
fi

# Re-verify the source has not moved during the preflight above. The merge is
# issued by REF (so the merge commit message names the ref a human recognizes),
# but every post-merge assertion is made against the pinned SOURCE_SHA, so the
# two must still agree at the moment the merge runs.
RECHECK_SHA="$(git rev-parse --verify --quiet "${SOURCE_REF}^{commit}" 2>/dev/null || true)"
if [ "$RECHECK_SHA" != "$SOURCE_SHA" ]; then
  echo "merge.sh: '$SOURCE_REF' moved during preflight ($SOURCE_SHA -> ${RECHECK_SHA:-<unresolvable>}); aborting" >&2
  exit 2
fi

echo "merge.sh: merging $SOURCE_REF ($SOURCE_SHA) into $DEFAULT_BRANCH ($DEFAULT_SHA)"

# Export env so the inner subprocess command passes privilege-guard
export CLAUDE_MERGE_COMMAND_ACTIVE=1

# Checkout default branch + perform the merge.
# Disable set -e around the merge so we can capture the exit code and emit
# clear conflict-resolution instructions instead of dying silently.
git checkout "$DEFAULT_BRANCH"
set +e
if [ "$NO_COMMIT" = true ]; then
  # --no-ff is required, not cosmetic: git documents that a fast-forward update
  # creates no merge commit and therefore cannot be held back by --no-commit.
  # Without it, --no-commit would silently commit on the fast-forward path --
  # exactly the silent-success shape this wrapper exists to avoid.
  git merge --no-commit --no-ff "$SOURCE_REF"
else
  git merge "$SOURCE_REF" --no-edit
fi
MERGE_RC=$?
set -e

if [ $MERGE_RC -ne 0 ]; then
  cat >&2 <<EOF
merge.sh: git merge exited $MERGE_RC — likely conflicts. Cleanup SKIPPED.

Resolve manually, then re-invoke:
  1. git status                # inspect conflicting files
  2. <edit files to resolve conflicts>
  3. git add <files>
  4. git commit                # complete the merge commit
  5. /merge $SOURCE_REF        # re-run via slash command to finish cleanup
                               # (worktree remove, branch delete, state file removal)

The wrapper is idempotent: re-running after a clean merge skips re-merging
("Already up to date") and executes only the cleanup section.
EOF
  exit $MERGE_RC
fi

if [ "$NO_COMMIT" = true ]; then
  FF_NOTE=""
  if git merge-base --is-ancestor "$DEFAULT_SHA" "$SOURCE_SHA"; then
    FF_NOTE="
  note    : this merge was fast-forwardable; --no-commit forced --no-ff so it
            could be held uncommitted, so committing it will record a merge
            commit where a plain run would have fast-forwarded."
  fi
  cat <<EOF
merge.sh: --no-commit — merge applied to the index and working tree, NOT committed.
  source  : $SOURCE_REF ($SOURCE_SHA)
  target  : $DEFAULT_BRANCH ($DEFAULT_SHA)$FF_NOTE

  Finalize : git commit --no-edit
  Roll back: git merge --abort     (single step; restores the pre-merge tree exactly)

Lifecycle cleanup (worktree removal, branch deletion, overnight-state removal)
is intentionally NOT run in this mode: there is no merge commit yet, so the
post-merge containment invariant cannot hold. Re-run this wrapper without
--no-commit after committing to execute the cleanup section.
EOF
  exit 0
fi

# ─── Post-merge containment invariant ────────────────────────────────────
# Only execute cleanup when:
#   1. The merge returned 0 (checked above), AND
#   2. No unmerged index entries remain (no half-resolved conflict), AND
#   3. The default branch HEAD now CONTAINS the source commit.
#
# (3) is ancestry/containment, NOT tree-equality. Do NOT reintroduce a
# `git diff --quiet <ref>` proxy: a genuine three-way merge yields a tree that
# differs from BOTH parents, so it would fail on every correct divergent merge.
UNMERGED_PATHS="$(git ls-files --unmerged)"
if [ -n "$UNMERGED_PATHS" ]; then
  echo "merge.sh: merge reported success but unmerged index entries remain; cleanup SKIPPED — manually inspect" >&2
  echo "$UNMERGED_PATHS" >&2
  exit 1
fi

MERGE_COMMIT="$(git rev-parse HEAD)"
if ! git merge-base --is-ancestor "$SOURCE_SHA" "$MERGE_COMMIT"; then
  echo "merge.sh: post-merge containment check FAILED — $SOURCE_SHA is not an ancestor of $MERGE_COMMIT; cleanup SKIPPED — manually inspect" >&2
  exit 1
fi

echo "merge.sh: post-merge containment OK ($SOURCE_SHA is contained in $MERGE_COMMIT)"
echo "merge.sh: parents of $MERGE_COMMIT: $(git rev-list --parents -n 1 "$MERGE_COMMIT" | cut -d' ' -f2-)"

# ─── Cleanup after successful merge ──────────────────────────────────────
# Every step is conditional on the artifact existing. A remote-tracking ref, a
# tag, and a bare commit hash have no local branch, no registered worktree, and
# no overnight-state file keyed on them -- for those sources the absence is the
# expected state, not a failure, so each step is announced and skipped.
if [ -z "$SOURCE_LOCAL_BRANCH" ]; then
  echo "merge.sh: cleanup not applicable — '$SOURCE_REF' is not a local branch (resolved ref: ${SOURCE_FULLREF:-<bare commit, no ref name>})"
  echo "  ~ skipped worktree removal:  a non-branch source has no registered worktree"
  echo "  ~ skipped branch deletion:   a non-branch source has no branch to delete"
  echo "  ~ skipped overnight-state:   state files key on a branch name; none can match"
else
  echo "merge.sh: cleaning up worktree + branch + overnight state files for branch $SOURCE_LOCAL_BRANCH"

  # Locate worktree path (if branch was checked out as a worktree)
  WORKTREE_PATH=$(git worktree list --porcelain 2>/dev/null | awk -v b="refs/heads/$SOURCE_LOCAL_BRANCH" 'BEGIN{p=""} /^worktree /{p=$2} $1=="branch" && $2==b{print p; exit}')

  if [ -n "$WORKTREE_PATH" ] && [ -d "$WORKTREE_PATH" ]; then
    git worktree remove "$WORKTREE_PATH" --force 2>/dev/null && \
      echo "  ✓ removed worktree: $WORKTREE_PATH" || \
      echo "  ! could not remove worktree: $WORKTREE_PATH"
  else
    echo "  ~ skipped worktree removal: no registered worktree for $SOURCE_LOCAL_BRANCH"
  fi

  # Delete branch (worktree gone, so -d is safe; -d refuses unmerged but we just merged).
  # Skipped in_place: that branch is not a disposable linked-worktree branch,
  # so merging it does not imply deleting it too -- it stays on disk.
  if [ "$IS_IN_PLACE" = true ]; then
    echo "  ~ skipped branch deletion: $SOURCE_LOCAL_BRANCH (in_place merge keeps the source branch)"
  elif git branch -d "$SOURCE_LOCAL_BRANCH" 2>/dev/null; then
    echo "  ✓ deleted branch: $SOURCE_LOCAL_BRANCH"
  else
    echo "  ! branch $SOURCE_LOCAL_BRANCH not deleted (may be unmerged or detached)"
  fi

  # Cleanup overnight-state files referencing this branch
  # WS1: default to the resolved harness home, never the author literal /root.
  PROJ="${CLAUDE_PROJECT_DIR:-${CLAUDE_HOME}}"
  for sf in "$PROJ/.claude"/overnight-state-*.json; do
    [ -f "$sf" ] || continue
    STATE_BRANCH=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get('worktree_branch') or d.get('branch') or d.get('focus_branch') or '')
except Exception:
    pass
" "$sf" 2>/dev/null || echo "")
    if [ "$STATE_BRANCH" = "$SOURCE_LOCAL_BRANCH" ]; then
      rm -f "$sf"
      echo "  ✓ removed overnight-state: $sf"
    fi
  done
fi

echo "merge.sh: merge complete on $DEFAULT_BRANCH"
