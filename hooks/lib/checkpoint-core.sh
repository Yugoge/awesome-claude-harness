#!/bin/bash
# ============================================================================
# checkpoint-core.sh - Shared library for automated snapshot commits
# ----------------------------------------------------------------------------
# Purpose: write_checkpoint() writes a snapshot commit to
#   refs/checkpoints/<sanitized-branch>  (NEVER touches HEAD / branch refs)
#
# This file MUST be sourced, not executed directly:
#   source ~/.claude/hooks/lib/checkpoint-core.sh
#   write_checkpoint "$GIT_DIR" "trigger reason" ["custom message"]
#
# ----------------------------------------------------------------------------
# Ref layout
#   refs/checkpoints/<sanitized-branch>
#     - branch name sanitized via:  tr '/' '-'
#     - detached HEAD fallback:     refs/checkpoints/detached-<short-sha>
#     - empty repo:                 ref created as a root commit (no parent)
#
# Algorithm (git plumbing only — no `git commit`):
#   1. read-tree parent tree (or --empty for bootstrap)
#   2. git add -A  (staged into a TEMP index via GIT_INDEX_FILE)
#   3. git write-tree  -> TREE_SHA
#   4. if TREE_SHA == PARENT_TREE_SHA -> return 0 (idempotent)
#   5. git commit-tree TREE_SHA [-p PARENT_SHA] -m "<msg>"  -> NEW_SHA
#   6. git update-ref REF NEW_SHA OLD_SHA           (CAS; retries 5x on race)
#   7. background push (rate-limited to 1/30s per repo) WITHOUT -f
#
# Recovery commands (for humans):
#   git log refs/checkpoints/<branch>
#   git checkout refs/checkpoints/<branch> -- <path>
#   git show refs/checkpoints/<branch>:<path>
#
# Cross-machine recovery (documented in CLAUDE.md — not auto-applied):
#   [remote "origin"]
#     fetch = +refs/heads/*:refs/remotes/origin/*
#     fetch = +refs/checkpoints/*:refs/remotes/origin/checkpoints/*
#
# Log file locations:
#   ~/.claude/logs/checkpoint.log        CAS/build failures
#   ~/.claude/logs/checkpoint-push.log   background push failures
#
# Concurrency safety:
#   - flock advisory lock on .git/checkpoint-core.lock serializes the
#     critical section (parent-read + commit-tree + update-ref) so at most
#     one writer creates a commit object at a time; prevents dangling
#     commit objects from CAS losers.
#   - CAS update-ref retained as belt-and-suspenders; should never fail
#     under the lock.
#   - Tree build (read-tree + add -A + write-tree) runs outside the lock
#     because it does not create persistent git objects that would be
#     orphaned on a lost race (blobs/trees are content-addressed and
#     would be created anyway by the winning writer).
#   - Temp index isolation: GIT_INDEX_FILE=.git/checkpoint-index.$$.<ns>
#   - Stale temp-index sweep (>60 min) at entry
#   - trap EXIT INT TERM HUP removes temp index on any exit path
#   - If flock is unavailable, falls back to the old CAS-retry loop (and
#     logs a warning about potential orphan commits under concurrency).
# ============================================================================

CHECKPOINT_LOG_DIR="${CHECKPOINT_LOG_DIR:-$HOME/.claude/logs}"
CHECKPOINT_LOG_FILE="${CHECKPOINT_LOG_DIR}/checkpoint.log"
CHECKPOINT_PUSH_LOG_FILE="${CHECKPOINT_LOG_DIR}/checkpoint-push.log"
CHECKPOINT_PUSH_MIN_INTERVAL="${CHECKPOINT_PUSH_MIN_INTERVAL:-30}"  # seconds
CHECKPOINT_CAS_MAX_RETRIES="${CHECKPOINT_CAS_MAX_RETRIES:-5}"

# Per-file ceiling for the pre-network oversized-ref gate (WI-1 M2/S1).
# GitHub rejects any single blob over 100 MiB; transferring the whole pack only
# to be rejected wastes bandwidth every cycle. Overridable.
CHECKPOINT_REMOTE_MAX_FILE_BYTES="${CHECKPOINT_REMOTE_MAX_FILE_BYTES:-104857600}"  # 100 MiB
# Short timeout for the remote-ref lookup so the gate (which runs inside the
# fully-detached worker) cannot reintroduce the latency M1 removed.
CHECKPOINT_REMOTE_LOOKUP_TIMEOUT="${CHECKPOINT_REMOTE_LOOKUP_TIMEOUT:-10}"  # seconds

# Consecutive-failure alerting (2026-04-16 SaaS-grade ops gap fix).
# Counter file tracks back-to-back write_checkpoint failures; on the 3rd
# consecutive failure within one hook invocation we print a single stderr
# alert so users actually see the breakage. Any success resets the counter.
CHECKPOINT_FAIL_COUNT_FILE="${CHECKPOINT_FAIL_COUNT_FILE:-${CHECKPOINT_LOG_DIR}/.checkpoint-fail-count}"
CHECKPOINT_FAIL_ALERT_THRESHOLD="${CHECKPOINT_FAIL_ALERT_THRESHOLD:-3}"

# Internal: timestamped log line to checkpoint.log
_checkpoint_log() {
    local level="$1"
    shift
    mkdir -p "$CHECKPOINT_LOG_DIR" 2>/dev/null
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    printf '[%s] [%s] %s\n' "$ts" "$level" "$*" >> "$CHECKPOINT_LOG_FILE" 2>/dev/null || true
}

# Internal: timestamped log line to checkpoint-push.log
_checkpoint_push_log() {
    local level="$1"
    shift
    mkdir -p "$CHECKPOINT_LOG_DIR" 2>/dev/null
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    printf '[%s] [%s] %s\n' "$ts" "$level" "$*" >> "$CHECKPOINT_PUSH_LOG_FILE" 2>/dev/null || true
}

# Internal: atomically increment the consecutive-failure counter and emit a
# single stderr CHECKPOINT ALERT when the threshold is reached. Safe against
# racing hook invocations via atomic temp-file rename.
_checkpoint_record_failure() {
    mkdir -p "$CHECKPOINT_LOG_DIR" 2>/dev/null
    local current=0
    if [ -f "$CHECKPOINT_FAIL_COUNT_FILE" ]; then
        current=$(cat "$CHECKPOINT_FAIL_COUNT_FILE" 2>/dev/null | tr -dc '0-9')
        current=${current:-0}
    fi
    local next=$((current + 1))
    local tmp="${CHECKPOINT_FAIL_COUNT_FILE}.$$"
    printf '%s\n' "$next" > "$tmp" 2>/dev/null && mv -f "$tmp" "$CHECKPOINT_FAIL_COUNT_FILE" 2>/dev/null || rm -f "$tmp" 2>/dev/null
    if [ "$next" -ge "$CHECKPOINT_FAIL_ALERT_THRESHOLD" ]; then
        echo "[CHECKPOINT ALERT] ${next} consecutive write failures — check ${CHECKPOINT_LOG_FILE}" >&2
    fi
}

# Internal: reset the consecutive-failure counter on a successful write.
_checkpoint_record_success() {
    if [ -f "$CHECKPOINT_FAIL_COUNT_FILE" ]; then
        printf '0\n' > "$CHECKPOINT_FAIL_COUNT_FILE" 2>/dev/null || true
    fi
}

# Internal: compute git dir (.git) for the repo at <work_dir>
_checkpoint_git_dir() {
    local work_dir="$1"
    local git_cmd
    if [ -n "$work_dir" ]; then
        git_cmd="git -C $work_dir"
    else
        git_cmd="git"
    fi
    $git_cmd rev-parse --git-dir 2>/dev/null
}

# Internal: stale temp-index sweep (defensive; prevents SIGKILL residue buildup)
_checkpoint_sweep_stale_indexes() {
    local git_dir="$1"
    if [ -n "$git_dir" ] && [ -d "$git_dir" ]; then
        find "$git_dir" -maxdepth 1 -name 'checkpoint-index.*' -mmin +60 -delete 2>/dev/null || true
    fi
}

# Internal: pre-network gate. Decides, BEFORE any push, whether the LOCAL
# checkpoint tip carries an object absent from the REMOTE checkpoint ref AND
# exceeding the per-file ceiling. Returns 0 (BLOCK push) when such an object
# exists, 1 (ALLOW push) otherwise. Fails OPEN (return 1) on any remote-lookup
# failure/timeout so a momentary outage never permanently suppresses
# checkpoints. Sets _checkpoint_push_gate_oversized_name for the diagnostic line.
#   $1 work_dir   absolute repo working tree (may be empty for cwd)
#   $2 ref        refs/checkpoints/<branch>
#   $3 local_sha  exact local checkpoint tip resolved by the caller (no TOCTOU)
_checkpoint_push_gate_oversized_name=""
_checkpoint_push_gate_oversized_blob() {
    local work_dir="$1" ref="$2" local_sha="$3"
    _checkpoint_push_gate_oversized_name=""
    local -a git_cmd
    if [ -n "$work_dir" ]; then git_cmd=(git -C "$work_dir"); else git_cmd=(git); fi

    # GIT_TERMINAL_PROMPT=0 so a credential-needing remote can never hang the
    # worker on a prompt; timeout bounds the network call.
    local ls_out="" lookup_rc=0 remote_sha=""
    if command -v timeout >/dev/null 2>&1; then
        ls_out=$(GIT_TERMINAL_PROMPT=0 timeout "$CHECKPOINT_REMOTE_LOOKUP_TIMEOUT" \
            "${git_cmd[@]}" ls-remote --refs origin "$ref" 2>/dev/null)
        lookup_rc=$?
    else
        # No timeout available: fail OPEN rather than risk an unbounded hang.
        return 1
    fi

    # Fail OPEN on lookup failure / timeout: never suppress pushes permanently.
    if [ "$lookup_rc" -ne 0 ]; then
        return 1
    fi

    # Lookup succeeded. Select the line whose ref name EXACTLY matches.
    # Empty => remote ref ABSENT: compare local objects vs an EMPTY remote set.
    remote_sha=$(printf '%s\n' "$ls_out" | awk -v r="$ref" '$2==r{print $1; exit}')

    local -a not_args=()
    if [ -n "$remote_sha" ]; then
        # Verify the remote commit exists locally before rev-list --not.
        if "${git_cmd[@]}" cat-file -e "${remote_sha}^{commit}" 2>/dev/null; then
            not_args=(--not "$remote_sha")
        else
            return 1  # remote SHA not local -> cannot diff safely -> fail OPEN
        fi
    fi

    # batch-check reads object METADATA only (not the blob content).
    local largest=0
    largest=$("${git_cmd[@]}" rev-list --objects "$local_sha" "${not_args[@]}" 2>/dev/null \
        | awk '{print $1}' \
        | "${git_cmd[@]}" cat-file --batch-check='%(objecttype) %(objectsize) %(objectname)' 2>/dev/null \
        | awk '$1=="blob" && $2>max {max=$2} END{print max+0}')

    if [ "${largest:-0}" -gt "$CHECKPOINT_REMOTE_MAX_FILE_BYTES" ]; then
        local oid opath sz
        while read -r oid opath; do
            [ -z "$oid" ] && continue
            sz=$("${git_cmd[@]}" cat-file -s "$oid" 2>/dev/null || echo 0)
            if [ "${sz:-0}" -gt "$CHECKPOINT_REMOTE_MAX_FILE_BYTES" ]; then
                _checkpoint_push_gate_oversized_name="${oid} (${sz} bytes, ${opath:-<no-path>})"
                break
            fi
        done < <("${git_cmd[@]}" rev-list --objects "$local_sha" "${not_args[@]}" 2>/dev/null)
        return 0
    fi
    return 1
}

# Internal: rate-limited background push of the checkpoint ref.
# Skips if another push was attempted within CHECKPOINT_PUSH_MIN_INTERVAL seconds
# for this repo. Uses repo-hash stamp file in /tmp/.
_checkpoint_rate_limited_push() {
    local work_dir="$1"
    local ref="$2"
    local git_cmd
    if [ -n "$work_dir" ]; then
        git_cmd="git -C $work_dir"
    else
        git_cmd="git"
    fi

    # Skip silently if no 'origin' configured
    if ! $git_cmd remote get-url origin >/dev/null 2>&1; then
        return 0
    fi

    # Compute a stable stamp key for this repo (absolute git-dir path, hashed)
    local abs_git_dir
    abs_git_dir=$($git_cmd rev-parse --absolute-git-dir 2>/dev/null)
    if [ -z "$abs_git_dir" ]; then
        return 0
    fi
    local repo_hash
    repo_hash=$(printf '%s' "$abs_git_dir" | md5sum 2>/dev/null | awk '{print $1}')
    if [ -z "$repo_hash" ]; then
        repo_hash=$(printf '%s' "$abs_git_dir" | cksum | awk '{print $1}')
    fi
    local stamp_file="/tmp/.checkpoint-push-${repo_hash}.ts"

    # Rate limit: skip if last push attempt was within the interval
    if [ -f "$stamp_file" ]; then
        local now last diff
        now=$(date +%s)
        last=$(stat -c %Y "$stamp_file" 2>/dev/null || stat -f %m "$stamp_file" 2>/dev/null || echo 0)
        diff=$((now - last))
        if [ "$diff" -lt "$CHECKPOINT_PUSH_MIN_INTERVAL" ]; then
            return 0
        fi
    fi
    touch "$stamp_file" 2>/dev/null || true

    # Resolve the exact local checkpoint tip ONCE so the object scanned by the
    # gate is exactly the object pushed (no TOCTOU if the ref advances).
    local local_sha
    local_sha=$($git_cmd rev-parse --verify -q "${ref}^{commit}" 2>/dev/null)
    if [ -z "$local_sha" ]; then
        return 0
    fi

    # M1 (latency): the background command redirects its OWN fd0/fd1/fd2 so the
    #   Stop hook sees end-of-stream of the inherited descriptors immediately and
    #   returns <2 s; disown also detaches job control. (`setsid` alone would NOT
    #   close inherited stdout/stderr — fd redirection is the load-bearing part.)
    # M2 (waste gate): the gate runs INSIDE the detached worker (so its ls-remote
    #   / rev-list cost never re-enters the hook's path) and decides, BEFORE any
    #   network transfer, whether to skip a doomed oversized push. The rate-limit
    #   above throttles how often this eligible-cycle path runs; when the window
    #   allows, the GATE — not the rate-limit — decides whether the push happens.
    # Background push WITHOUT -f; CAS chain guarantees fast-forward.
    (
        mkdir -p "$CHECKPOINT_LOG_DIR" 2>/dev/null
        if _checkpoint_push_gate_oversized_blob "$work_dir" "$ref" "$local_sha"; then
            _checkpoint_push_log WARN "SKIP push ${ref}: local-minus-remote object exceeds ceiling (${CHECKPOINT_REMOTE_MAX_FILE_BYTES} bytes): ${_checkpoint_push_gate_oversized_name:-?} (repo=${abs_git_dir})"
        elif ! GIT_TERMINAL_PROMPT=0 $git_cmd push origin "${local_sha}:${ref}" >/dev/null 2>>"$CHECKPOINT_PUSH_LOG_FILE"; then
            _checkpoint_push_log ERROR "push ${ref} failed (repo=${abs_git_dir})"
        fi
    ) </dev/null >/dev/null 2>>"$CHECKPOINT_PUSH_LOG_FILE" &
    disown 2>/dev/null || true
}

# Public API.
#
# write_checkpoint <work_dir> <trigger_reason> [<custom_message>]
#
#   work_dir        - absolute path of the repo working tree, or empty string
#                     for cwd; passed via `git -C <work_dir>` when non-empty
#   trigger_reason  - short string describing what fired this checkpoint
#                     (e.g. "posttool threshold", "stop hook: auto-commit.sh")
#   custom_message  - optional; if provided, used as the commit summary line
#                     (rest of the commit body is appended automatically)
#
# Return codes:
#   0  success OR idempotent no-op (tree unchanged)
#   1  build/CAS failure after retries
#   2  not a git repo
write_checkpoint() {
    local work_dir="${1:-}"
    local trigger="${2:-unknown}"
    local custom_message="${3:-}"

    # Resolve git dir; bail gracefully if not a repo
    # Note: rc=2 (not-a-repo) is NOT a checkpoint failure — it's a no-op skip,
    # so we do NOT increment the failure counter here.
    local git_dir
    git_dir=$(_checkpoint_git_dir "$work_dir")
    if [ -z "$git_dir" ]; then
        _checkpoint_log WARN "not a git repo (work_dir='${work_dir}', trigger='${trigger}')"
        return 2
    fi

    # Resolve absolute git dir so temp-index path is unambiguous
    local git_cmd
    if [ -n "$work_dir" ]; then
        git_cmd="git -C $work_dir"
    else
        git_cmd="git"
    fi
    local abs_git_dir
    abs_git_dir=$($git_cmd rev-parse --absolute-git-dir 2>/dev/null)
    if [ -z "$abs_git_dir" ]; then
        _checkpoint_log ERROR "cannot resolve absolute git dir (work_dir='${work_dir}')"
        _checkpoint_record_failure
        return 1
    fi

    # Defensive sweep of orphaned temp indexes from previous SIGKILLed runs
    _checkpoint_sweep_stale_indexes "$abs_git_dir"

    # Determine branch name & ref
    local branch sanitized ref
    branch=$($git_cmd branch --show-current 2>/dev/null)
    if [ -z "$branch" ]; then
        # Detached HEAD fallback: refs/checkpoints/detached-<short-sha>
        local short_sha
        short_sha=$($git_cmd rev-parse --short HEAD 2>/dev/null)
        if [ -z "$short_sha" ]; then
            # Empty repo + detached (unusual); fall back to a literal label
            sanitized="detached-empty"
        else
            sanitized="detached-${short_sha}"
        fi
    else
        sanitized=$(printf '%s' "$branch" | tr '/' '-')
    fi
    ref="refs/checkpoints/${sanitized}"

    # Temp index path (isolated from real .git/index).
    # Use PID + nanosecond-ish suffix to avoid collisions among sibling runs.
    local ns
    ns=$(date +%s%N 2>/dev/null || date +%s)
    local TMP_INDEX="${abs_git_dir}/checkpoint-index.$$.${ns}"

    # Trap ensures TMP_INDEX is removed on any exit path from this function,
    # including the enclosing shell. Removing at end-of-function too (below).
    trap 'rm -f "$TMP_INDEX"' EXIT INT TERM HUP

    # -------------------------------------------------------------------------
    # PHASE 1: Build the working-tree snapshot OUTSIDE the lock.
    #
    # This phase does NOT create any commit objects — only blobs and a tree,
    # which are content-addressed and would be created by whichever writer
    # ultimately wins. Running this outside the lock preserves concurrency
    # for the expensive `git add -A` step and does not contribute to the
    # dangling-objects problem the flock fix targets.
    #
    # Seed temp index from the CURRENT working branch HEAD tree, never from
    # the checkpoint ref tree. This ensures ignored/runtime files that were
    # accidentally captured in historical refs/checkpoints/* do not get
    # resurrected forever by inheritance from the previous checkpoint tree.
    #
    # The checkpoint ref is still used later as the COMMIT PARENT so history
    # remains linear, but the snapshot content itself must reflect today's
    # working tree + ignore rules, not yesterday's polluted checkpoint tree.
    #
    # In an empty repo HEAD has no tree, so seed from --empty instead.
    # -------------------------------------------------------------------------
    local seed_parent_sha=""
    local seed_parent_tree=""
    seed_parent_sha=$($git_cmd rev-parse --verify -q HEAD 2>/dev/null || true)
    if [ -n "$seed_parent_sha" ]; then
        seed_parent_tree=$($git_cmd rev-parse "${seed_parent_sha}^{tree}" 2>/dev/null || true)
    fi

    rm -f "$TMP_INDEX"
    if [ -n "$seed_parent_tree" ]; then
        if ! GIT_INDEX_FILE="$TMP_INDEX" $git_cmd read-tree "$seed_parent_tree" 2>>"$CHECKPOINT_LOG_FILE"; then
            _checkpoint_log ERROR "read-tree failed (parent_tree=${seed_parent_tree}, ref=${ref})"
            rm -f "$TMP_INDEX"
            _checkpoint_record_failure
            return 1
        fi
    else
        if ! GIT_INDEX_FILE="$TMP_INDEX" $git_cmd read-tree --empty 2>>"$CHECKPOINT_LOG_FILE"; then
            _checkpoint_log ERROR "read-tree --empty failed (ref=${ref})"
            rm -f "$TMP_INDEX"
            _checkpoint_record_failure
            return 1
        fi
    fi

    if ! GIT_INDEX_FILE="$TMP_INDEX" $git_cmd add -A 2>>"$CHECKPOINT_LOG_FILE"; then
        _checkpoint_log ERROR "add -A failed (ref=${ref})"
        rm -f "$TMP_INDEX"
        _checkpoint_record_failure
        return 1
    fi

    local tree_sha
    tree_sha=$(GIT_INDEX_FILE="$TMP_INDEX" $git_cmd write-tree 2>>"$CHECKPOINT_LOG_FILE")
    if [ -z "$tree_sha" ]; then
        _checkpoint_log ERROR "write-tree produced empty sha (ref=${ref})"
        rm -f "$TMP_INDEX"
        _checkpoint_record_failure
        return 1
    fi

    # -------------------------------------------------------------------------
    # PHASE 2: Enter flock-protected critical section for the commit-tree +
    # update-ref pair. Only one writer per repo runs this section at a time,
    # so commit-tree never produces an orphan object.
    #
    # The flock FD (9) is local to the subshell; closing the subshell
    # releases the lock automatically even on error.
    # -------------------------------------------------------------------------
    local lockfile="${abs_git_dir}/checkpoint-core.lock"
    touch "$lockfile" 2>/dev/null || true

    local result_file
    result_file=$(mktemp 2>/dev/null || printf '%s' "/tmp/checkpoint-result.$$.${ns}")

    if command -v flock >/dev/null 2>&1; then
        # Run the critical section inside a flock-protected subshell.
        # Output the ref tip (or empty on idempotent no-op) to $result_file,
        # and use the subshell's exit code to signal status:
        #   0 = success (new commit written); result_file has the new sha
        #   2 = idempotent no-op (tree unchanged); result_file empty
        #   1 = hard failure; caller returns 1
        (
            flock -x 9

            # Re-read parent INSIDE the lock for correctness.
            local old_ref_sha_inner=""
            local parent_sha_inner=""
            local parent_tree_inner=""
            old_ref_sha_inner=$($git_cmd rev-parse --verify -q "$ref" 2>/dev/null || true)
            if [ -n "$old_ref_sha_inner" ]; then
                parent_sha_inner="$old_ref_sha_inner"
            else
                parent_sha_inner=$($git_cmd rev-parse --verify -q HEAD 2>/dev/null || true)
            fi
            if [ -n "$parent_sha_inner" ]; then
                parent_tree_inner=$($git_cmd rev-parse "${parent_sha_inner}^{tree}" 2>/dev/null || true)
            fi

            # Idempotency short-circuit: if the pre-built tree matches the
            # CURRENT parent tree (latest, under the lock), do not commit.
            if [ -n "$parent_tree_inner" ] && [ "$tree_sha" = "$parent_tree_inner" ]; then
                : > "$result_file"
                exit 2
            fi

            # Build commit message (inside the lock so timestamp/file-count
            # reflect the actual committed state).
            local summary=""
            local timestamp=""
            local file_count=""
            local commit_body=""
            timestamp=$(date '+%Y-%m-%d %H:%M:%S')
            if [ -n "$parent_tree_inner" ]; then
                file_count=$($git_cmd diff-tree -r --name-only "$parent_tree_inner" "$tree_sha" 2>/dev/null | wc -l | tr -d ' ')
            else
                file_count=$($git_cmd ls-tree -r --name-only "$tree_sha" 2>/dev/null | wc -l | tr -d ' ')
            fi
            if [ -n "$custom_message" ]; then
                summary="$custom_message"
            else
                summary="checkpoint: Auto-save at ${timestamp}"
            fi
            commit_body="${summary}

Trigger: ${trigger}
Ref: ${ref}
Files: ${file_count}

This commit is a snapshot written to refs/checkpoints/* by
~/.claude/hooks/lib/checkpoint-core.sh. It is NOT on any branch HEAD.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
via [Happy](https://happy.engineering)

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>"

            # commit-tree inside the lock: only one writer creates a commit
            # object at a time, so no dangling objects accumulate.
            local new_sha_inner=""
            if [ -n "$parent_sha_inner" ]; then
                new_sha_inner=$(printf '%s' "$commit_body" | $git_cmd commit-tree "$tree_sha" -p "$parent_sha_inner" 2>>"$CHECKPOINT_LOG_FILE")
            else
                new_sha_inner=$(printf '%s' "$commit_body" | $git_cmd commit-tree "$tree_sha" 2>>"$CHECKPOINT_LOG_FILE")
            fi
            if [ -z "$new_sha_inner" ]; then
                _checkpoint_log ERROR "commit-tree failed (ref=${ref}, tree=${tree_sha})"
                : > "$result_file"
                exit 1
            fi

            # CAS update-ref kept as safety net. Under the lock it must not
            # fail; if it does, something is badly wrong — log and abort.
            # Do NOT retry inside the lock (that reintroduces the orphan bug).
            if $git_cmd update-ref "$ref" "$new_sha_inner" "$old_ref_sha_inner" 2>>"$CHECKPOINT_LOG_FILE"; then
                printf '%s' "$new_sha_inner" > "$result_file"
                exit 0
            fi

            _checkpoint_log ERROR "update-ref failed INSIDE flock for ${ref} (old=${old_ref_sha_inner}, new=${new_sha_inner}); aborting without retry"
            printf '%s' "$new_sha_inner" > "$result_file"
            exit 1
        ) 9>"$lockfile"
        local rc=$?

        rm -f "$TMP_INDEX"
        trap - EXIT INT TERM HUP

        case "$rc" in
            0)
                rm -f "$result_file"
                _checkpoint_record_success
                _checkpoint_rate_limited_push "$work_dir" "$ref"
                return 0
                ;;
            2)
                rm -f "$result_file"
                _checkpoint_record_success
                return 0
                ;;
            *)
                rm -f "$result_file"
                _checkpoint_record_failure
                return 1
                ;;
        esac
    fi

    # -------------------------------------------------------------------------
    # PHASE 2 FALLBACK: flock unavailable. Warn and fall back to the old
    # CAS-retry loop. Under concurrency this may produce orphan commit
    # objects (GC-eligible) — the flock path above is preferred when
    # available.
    # -------------------------------------------------------------------------
    _checkpoint_log WARN "flock unavailable; falling back to CAS-retry loop (orphan commits possible under concurrency)"

    local retry=0
    local new_sha=""
    while [ "$retry" -lt "$CHECKPOINT_CAS_MAX_RETRIES" ]; do
        retry=$((retry + 1))

        local old_ref_sha=""
        local parent_sha=""
        local parent_tree=""
        old_ref_sha=$($git_cmd rev-parse --verify -q "$ref" 2>/dev/null || true)
        if [ -n "$old_ref_sha" ]; then
            parent_sha="$old_ref_sha"
        else
            parent_sha=$($git_cmd rev-parse --verify -q HEAD 2>/dev/null || true)
        fi
        if [ -n "$parent_sha" ]; then
            parent_tree=$($git_cmd rev-parse "${parent_sha}^{tree}" 2>/dev/null || true)
        fi

        # Idempotency short-circuit on pre-built tree.
        if [ -n "$parent_tree" ] && [ "$tree_sha" = "$parent_tree" ]; then
            rm -f "$result_file"
            _checkpoint_record_success
            return 0
        fi

        local summary=""
        local timestamp=""
        local file_count=""
        local commit_body=""
        timestamp=$(date '+%Y-%m-%d %H:%M:%S')
        if [ -n "$parent_tree" ]; then
            file_count=$($git_cmd diff-tree -r --name-only "$parent_tree" "$tree_sha" 2>/dev/null | wc -l | tr -d ' ')
        else
            file_count=$($git_cmd ls-tree -r --name-only "$tree_sha" 2>/dev/null | wc -l | tr -d ' ')
        fi
        if [ -n "$custom_message" ]; then
            summary="$custom_message"
        else
            summary="checkpoint: Auto-save at ${timestamp}"
        fi
        commit_body="${summary}

Trigger: ${trigger}
Ref: ${ref}
Files: ${file_count}

This commit is a snapshot written to refs/checkpoints/* by
~/.claude/hooks/lib/checkpoint-core.sh. It is NOT on any branch HEAD.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
via [Happy](https://happy.engineering)

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>"

        if [ -n "$parent_sha" ]; then
            new_sha=$(printf '%s' "$commit_body" | $git_cmd commit-tree "$tree_sha" -p "$parent_sha" 2>>"$CHECKPOINT_LOG_FILE")
        else
            new_sha=$(printf '%s' "$commit_body" | $git_cmd commit-tree "$tree_sha" 2>>"$CHECKPOINT_LOG_FILE")
        fi
        if [ -z "$new_sha" ]; then
            _checkpoint_log ERROR "commit-tree failed (ref=${ref}, tree=${tree_sha})"
            rm -f "$result_file"
            _checkpoint_record_failure
            return 1
        fi

        if $git_cmd update-ref "$ref" "$new_sha" "$old_ref_sha" 2>>"$CHECKPOINT_LOG_FILE"; then
            rm -f "$result_file"
            rm -f "$TMP_INDEX"
            trap - EXIT INT TERM HUP
            _checkpoint_record_success
            _checkpoint_rate_limited_push "$work_dir" "$ref"
            return 0
        fi

        _checkpoint_log WARN "CAS race on ${ref} (attempt ${retry}/${CHECKPOINT_CAS_MAX_RETRIES}), retrying"
        sleep "0.0$((50 + RANDOM % 150))" 2>/dev/null || sleep 1
    done

    _checkpoint_log ERROR "CAS exceeded ${CHECKPOINT_CAS_MAX_RETRIES} retries for ${ref}"
    rm -f "$result_file"
    rm -f "$TMP_INDEX"
    trap - EXIT INT TERM HUP
    _checkpoint_record_failure
    return 1
}

# End of library. Sourcing this file exposes write_checkpoint in the caller's shell.
