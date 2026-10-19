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
#   2. git add -A into a TEMP index (GIT_INDEX_FILE); return 3 when the settings clean filter refuses
#   2b. hard-exclude known PII file classes from the temp index (independent of .gitignore)
#   2c. return 3, writing nothing, when the pre-commit hook's own checks refuse the temp index
#   3. git write-tree  -> TREE_SHA
#   4. if TREE_SHA == PARENT_TREE_SHA -> return 0 (idempotent)
#   5. git commit-tree TREE_SHA [-p PARENT_SHA] -m "<msg>"  -> NEW_SHA
#   6. git update-ref REF NEW_SHA OLD_SHA           (CAS; retries 5x on race)
#   7. opt-in background push, only when GIT_AUTO_PUSH=1 (rate-limited 1/30s per repo), WITHOUT -f, gated by a
#      fail-closed PII/credential content scan + a fail-open oversized-blob
#      size check on the local-minus-remote object set
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

CHECKPOINT_LOG_DIR="${CHECKPOINT_LOG_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs}"
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

# Known PII file classes hard-excluded from every checkpoint snapshot,
# independent of the CURRENT .gitignore content (defense-in-depth backstop;
# see docs/reference/checkpoint-mechanism.md). Space-separated.
# CHECKPOINT_PII_BASENAME_PREFIXES: matched as a basename PREFIX (glob
#   "$prefix*"), e.g. ".claude.json" also matches ".claude.json.bak".
# CHECKPOINT_PII_PATH_COMPONENTS: matched as an EXACT interior directory
#   segment, never a substring -- mirrors this repo's own path-component-
#   exact discipline against the root-anchored-vs-nested-copy bug class
#   (.gitignore:118-119).
CHECKPOINT_PII_BASENAME_PREFIXES="${CHECKPOINT_PII_BASENAME_PREFIXES:-.claude.json}"
CHECKPOINT_PII_PATH_COMPONENTS="${CHECKPOINT_PII_PATH_COMPONENTS:-backups sessions}"

# Fail-closed PII/credential content-signature pattern for the pre-push gate
# (distinct from the fail-open oversized-blob gate above). Email/UUID/GitHub-
# token/JWT are conventional shapes; sk-/AKIA copied verbatim from this
# repo's own CI secret scan (tier_2_verified reference:
# .github/workflows/baseline.yml:130).
CHECKPOINT_PII_SIGNATURE_PATTERN="${CHECKPOINT_PII_SIGNATURE_PATTERN:-[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|sk-[A-Za-z0-9]{20}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+}"

# Consecutive-failure alerting (2026-04-16): the 3rd back-to-back write_checkpoint failure prints
# one stderr alert; any success resets the counter, and a refusal (rc 3) leaves it alone.
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

# Internal: atomically (temp-file rename, safe against racing hooks) increment the consecutive-
# failure counter, and emit one stderr CHECKPOINT ALERT when the threshold is reached.
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

# Internal: fail-CLOSED pre-network gate for PII/credential content
# signatures (M2, 2026-09-18). Mirrors _checkpoint_push_gate_oversized_blob's
# local-minus-remote object-scoping but is fail-CLOSED by design: this is a
# security gate, not a bandwidth-optimization gate, so ANY inability to
# complete the scan (remote lookup failure/timeout, rev-list failure,
# content-read failure) also returns 0 (BLOCK) rather than 1 (ALLOW) -- the
# opposite default of the sibling gate above. Sets
# _checkpoint_push_gate_pii_name for the ALERT log line.
#   $1 work_dir   absolute repo working tree (may be empty for cwd)
#   $2 ref        refs/checkpoints/<branch>
#   $3 local_sha  exact local checkpoint tip resolved by the caller (no TOCTOU)
_checkpoint_push_gate_pii_name=""
_checkpoint_push_gate_pii_signature() {
    local work_dir="$1" ref="$2" local_sha="$3"
    _checkpoint_push_gate_pii_name=""
    local -a git_cmd
    if [ -n "$work_dir" ]; then git_cmd=(git -C "$work_dir"); else git_cmd=(git); fi

    if ! command -v timeout >/dev/null 2>&1; then
        # No timeout available: fail CLOSED (contrast the size gate, which
        # fails OPEN in this same situation -- see that function above).
        _checkpoint_push_gate_pii_name="scan unavailable: no 'timeout' binary"
        return 0
    fi

    local ls_out="" lookup_rc=0 remote_sha=""
    ls_out=$(GIT_TERMINAL_PROMPT=0 timeout "$CHECKPOINT_REMOTE_LOOKUP_TIMEOUT" \
        "${git_cmd[@]}" ls-remote --refs origin "$ref" 2>/dev/null)
    lookup_rc=$?

    if [ "$lookup_rc" -ne 0 ]; then
        # Fail CLOSED on lookup failure/timeout: cannot establish which
        # objects are new, so cannot safely allow the upload.
        _checkpoint_push_gate_pii_name="remote lookup failed/timed out"
        return 0
    fi

    remote_sha=$(printf '%s\n' "$ls_out" | awk -v r="$ref" '$2==r{print $1; exit}')

    local -a not_args=()
    if [ -n "$remote_sha" ]; then
        if "${git_cmd[@]}" cat-file -e "${remote_sha}^{commit}" 2>/dev/null; then
            not_args=(--not "$remote_sha")
        else
            _checkpoint_push_gate_pii_name="remote sha not local; cannot diff safely"
            return 0
        fi
    fi

    local rev_list_out="" rev_list_rc=0
    rev_list_out=$("${git_cmd[@]}" rev-list --objects "$local_sha" "${not_args[@]}" 2>/dev/null)
    rev_list_rc=$?
    if [ "$rev_list_rc" -ne 0 ]; then
        _checkpoint_push_gate_pii_name="rev-list failed"
        return 0
    fi

    local oid opath otype grep_rc
    while read -r oid opath; do
        [ -z "$oid" ] && continue
        otype=$("${git_cmd[@]}" cat-file -t "$oid" 2>/dev/null)
        if [ -z "$otype" ]; then
            _checkpoint_push_gate_pii_name="cat-file -t failed for ${oid}"
            return 0
        fi
        [ "$otype" = "blob" ] || continue
        "${git_cmd[@]}" cat-file -p "$oid" 2>/dev/null | grep -qEa "$CHECKPOINT_PII_SIGNATURE_PATTERN"
        grep_rc=$?
        if [ "$grep_rc" -eq 0 ]; then
            _checkpoint_push_gate_pii_name="${oid} (${opath:-<no-path>})"
            return 0
        elif [ "$grep_rc" -gt 1 ]; then
            # grep exit codes: 0=match, 1=no-match, >1=error. Fail CLOSED.
            _checkpoint_push_gate_pii_name="content scan error for ${oid}"
            return 0
        fi
    done <<< "$rev_list_out"

    return 1
}

# Internal: rate-limited background push of the checkpoint ref.
# Skips if another push was attempted within CHECKPOINT_PUSH_MIN_INTERVAL seconds
# for this repo. Uses repo-hash stamp file in /tmp/.
_checkpoint_rate_limited_push() {
    [ "${GIT_AUTO_PUSH:-}" = "1" ] || return 0
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
    local stamp_file
    stamp_file="$(
      . "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/harness_state_dir.sh" 2>/dev/null \
        && harness_state_dir || printf '%s' /tmp
    )/.checkpoint-push-${repo_hash}.ts"

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
    # M2 (waste gate) + PII gate (2026-09-18): both gates run INSIDE the
    #   detached worker (so their ls-remote / rev-list cost never re-enters
    #   the hook's path) and decide, BEFORE any network transfer, whether to
    #   skip a doomed oversized push or block a PII/credential-bearing one.
    #   The rate-limit above throttles how often this eligible-cycle path
    #   runs; when the window allows, the GATES — not the rate-limit --
    #   decide whether the push happens. _checkpoint_push_worker is factored
    #   out (same logic, same log-message conventions) purely so it can be
    #   called synchronously by tests without racing this detached subshell.
    # Background push WITHOUT -f; CAS chain guarantees fast-forward.
    (
        _checkpoint_push_worker "$work_dir" "$ref" "$local_sha"
    ) </dev/null >/dev/null 2>>"$CHECKPOINT_PUSH_LOG_FILE" &
    disown 2>/dev/null || true
}

# Internal: PII gate (fail-closed) then oversized-blob gate (fail-open) then
# the real push. Extracted from _checkpoint_rate_limited_push's background
# subshell so tests can invoke it synchronously (see comment above); the
# background+disown wrapping happens only in _checkpoint_rate_limited_push,
# never here. Same log-message wording/levels as before this extraction.
#   $1 work_dir   $2 ref   $3 local_sha
_checkpoint_push_worker() {
    local work_dir="$1" ref="$2" local_sha="$3"
    local -a git_cmd
    if [ -n "$work_dir" ]; then git_cmd=(git -C "$work_dir"); else git_cmd=(git); fi
    mkdir -p "$CHECKPOINT_LOG_DIR" 2>/dev/null
    if _checkpoint_push_gate_pii_signature "$work_dir" "$ref" "$local_sha"; then
        _checkpoint_push_log ALERT "BLOCK push ${ref}: local-minus-remote object set contains PII/credential-shaped content: ${_checkpoint_push_gate_pii_name:-?} (repo=${abs_git_dir:-${work_dir:-.}})"
    elif _checkpoint_push_gate_oversized_blob "$work_dir" "$ref" "$local_sha"; then
        _checkpoint_push_log WARN "SKIP push ${ref}: local-minus-remote object exceeds ceiling (${CHECKPOINT_REMOTE_MAX_FILE_BYTES} bytes): ${_checkpoint_push_gate_oversized_name:-?} (repo=${abs_git_dir:-${work_dir:-.}})"
    elif ! GIT_TERMINAL_PROMPT=0 "${git_cmd[@]}" push origin "${local_sha}:${ref}" >/dev/null 2>>"$CHECKPOINT_PUSH_LOG_FILE"; then
        _checkpoint_push_log ERROR "push ${ref} failed (repo=${abs_git_dir:-${work_dir:-.}})"
    fi
}

# Commit message of a checkpoint snapshot (both write paths below). A non-empty
# CLAUDE_CHECKPOINT_EXTRA_TRAILER is appended verbatim as one more trailer line
# after the Claude one (default empty = none).
#   $1 summary   $2 trigger   $3 ref   $4 file_count
_checkpoint_commit_body() {
    printf '%s' "${1}

Trigger: ${2}
Ref: ${3}
Files: ${4}

This commit is a snapshot written to refs/checkpoints/* by
~/.claude/hooks/lib/checkpoint-core.sh. It is NOT on any branch HEAD.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>${CLAUDE_CHECKPOINT_EXTRA_TRAILER:+
${CLAUDE_CHECKPOINT_EXTRA_TRAILER}}"
}

# Public API.
#
# write_checkpoint <work_dir> <trigger_reason> [<custom_message>]
#
#   work_dir        - the repo working tree (absolute; empty = cwd), used as `git -C <work_dir>`
#   trigger_reason  - what fired it (e.g. "posttool threshold", "stop hook: auto-commit.sh")
#   custom_message  - optional commit summary line (the rest of the body is appended)
#
# Return codes:
#   0  success OR idempotent no-op (tree unchanged)
#   1  build/CAS failure after retries
#   2  not a git repo
#   3  refused at step 2 or 2c: nothing written; checkpoint_refused_by names the rule(s), no value
write_checkpoint() {
    local work_dir="${1:-}"
    local trigger="${2:-unknown}"
    local custom_message="${3:-}"

    # rc=2 (not a repo) is a no-op skip, NOT a checkpoint failure: the counter is left alone.
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

    # Temp index (isolated from .git/index); PID + nanoseconds keep sibling runs apart.
    local ns
    ns=$(date +%s%N 2>/dev/null || date +%s)
    local TMP_INDEX="${abs_git_dir}/checkpoint-index.$$.${ns}"

    # The trap removes TMP_INDEX on any exit path, the enclosing shell's too; so does the end below.
    trap 'rm -f "$TMP_INDEX"' EXIT INT TERM HUP

    # -------------------------------------------------------------------------
    # PHASE 1: build the snapshot tree OUTSIDE the lock. It creates no commit object, only
    # content-addressed blobs and trees the winning writer would create anyway, so the costly
    # `git add -A` stays concurrent. The temp index is seeded from HEAD's tree (--empty in an empty
    # repo), never the checkpoint ref's, so files a past snapshot captured by mistake are not
    # inherited forever; the ref stays the COMMIT PARENT (linear history).
    # -------------------------------------------------------------------------
    local seed_parent_sha=""
    local seed_parent_tree=""
    seed_parent_sha=$($git_cmd rev-parse --verify -q HEAD 2>/dev/null || true)
    if [ -n "$seed_parent_sha" ]; then
        seed_parent_tree=$($git_cmd rev-parse "${seed_parent_sha}^{tree}" 2>/dev/null || true)
    fi

    rm -f "$TMP_INDEX"
    mkdir -p "$CHECKPOINT_LOG_DIR" 2>/dev/null  # the 2>> redirects below fail on a fresh home
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

    local h top common report
    checkpoint_refused_by=""
    h="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd -P)"
    { read -r top; read -r common; } < <($git_cmd rev-parse --show-toplevel --path-format=absolute --git-common-dir 2>/dev/null)
    if ! GIT_INDEX_FILE="$TMP_INDEX" $git_cmd add -A 2>>"$CHECKPOINT_LOG_FILE"; then
        rm -f "$TMP_INDEX"
        # Staging fails by design when this harness home's registered clean filter cannot clean
        # settings.json: a refusal if its engine, run here, refuses the file (rc 1; a missing one: 2).
        if [ "$top" = "$h" ] && [ -f "$h/settings.json" ] && $git_cmd config filter.claude-settings.clean >/dev/null \
            && { python3 "$h/scripts/install/render-settings" clean <"$h/settings.json" >/dev/null 2>&1; [ "$?" = 1 ]; }; then
            checkpoint_refused_by="the settings filter (render-settings clean)"
            _checkpoint_log ERROR "snapshot refused by ${checkpoint_refused_by}: nothing written (ref=${ref})"
            return 3
        fi
        _checkpoint_log ERROR "add -A failed (ref=${ref})"
        _checkpoint_record_failure
        return 1
    fi

    # -------------------------------------------------------------------------
    # Hard-exclude known PII file classes from the temp index whatever the CURRENT .gitignore says
    # (backstop; docs/reference/checkpoint-mechanism.md: .claude.json was captured in b432fc54, 13
    # days before its ignore rule existed). Path-component-exact, never substring: basename PREFIX
    # for the .claude.json family, exact interior directory segment for backups/sessions.
    # -------------------------------------------------------------------------
    local pii_path pii_removed=0
    while IFS= read -r pii_path; do
        [ -z "$pii_path" ] && continue
        if GIT_INDEX_FILE="$TMP_INDEX" $git_cmd update-index --force-remove -- "$pii_path" 2>>"$CHECKPOINT_LOG_FILE"; then
            pii_removed=$((pii_removed + 1))
        fi
    done < <(GIT_INDEX_FILE="$TMP_INDEX" $git_cmd ls-files 2>/dev/null | while IFS= read -r p; do
        base="${p##*/}"
        is_pii=0
        for prefix in $CHECKPOINT_PII_BASENAME_PREFIXES; do
            case "$base" in
                "$prefix"*) is_pii=1 ;;
            esac
        done
        if [ "$is_pii" -eq 0 ]; then
            dir="${p%/*}"
            if [ "$dir" != "$p" ]; then
                IFS='/' read -r -a segs <<< "$dir"
                for seg in "${segs[@]}"; do
                    for comp in $CHECKPOINT_PII_PATH_COMPONENTS; do
                        [ "$seg" = "$comp" ] && is_pii=1
                    done
                done
            fi
        fi
        [ "$is_pii" -eq 1 ] && printf '%s\n' "$p"
    done)
    if [ "$pii_removed" -gt 0 ]; then
        _checkpoint_log WARN "hard-excluded ${pii_removed} known-PII-class path(s) from snapshot (ref=${ref})"
    fi

    # Refuse what the pre-commit hook refuses, by its own engines on the temp index (they print no
    # literal or value): the private-literal rule when its list is not empty, and in this harness
    # home the settings check when settings.json differs from HEAD. Callers get only rule names.
    if [ -s "${common%/*}/private-literals.txt" ] && ! report="$(cd "$top" \
        && GIT_INDEX_FILE="$TMP_INDEX" bash "$h/scripts/check-public-core.sh" --private-literals 2>&1)"; then
        checkpoint_refused_by="the private-literal rule"
        _checkpoint_log ERROR "${checkpoint_refused_by}: ${report//$'\n'/ | }"
    fi
    if [ "$top" = "$h" ] \
        && ! GIT_INDEX_FILE="$TMP_INDEX" $git_cmd diff-index --cached --quiet HEAD -- settings.json 2>/dev/null \
        && ! GIT_INDEX_FILE="$TMP_INDEX" python3 "$h/scripts/install/render-settings" check --staged 2>>"$CHECKPOINT_LOG_FILE"; then
        checkpoint_refused_by+="${checkpoint_refused_by:+ and }the settings check (render-settings check --staged)"
    fi
    if [ -n "$checkpoint_refused_by" ]; then
        _checkpoint_log ERROR "snapshot refused by ${checkpoint_refused_by}: nothing written (ref=${ref})"
        rm -f "$TMP_INDEX"
        return 3
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
    # PHASE 2: commit-tree + update-ref under flock: one writer per repo at a
    # time, so commit-tree never produces an orphan object. FD 9 is local to
    # the subshell, whose exit releases the lock even on error.
    # -------------------------------------------------------------------------
    local lockfile="${abs_git_dir}/checkpoint-core.lock"
    touch "$lockfile" 2>/dev/null || true

    local result_file
    # mktemp honors $TMPDIR; so does its fallback (/tmp only when TMPDIR is unset).
    result_file=$(mktemp 2>/dev/null || printf '%s' "${TMPDIR:-/tmp}/checkpoint-result.$$.${ns}")

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
            commit_body=$(_checkpoint_commit_body "$summary" "$trigger" "$ref" "$file_count")

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
        commit_body=$(_checkpoint_commit_body "$summary" "$trigger" "$ref" "$file_count")

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
