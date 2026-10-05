#!/bin/bash
# git-fswatch.sh - Comprehensive Git file watcher using fswatch
# Comprehensive Git file monitor using fswatch
# Location: ~/.claude/hooks/git-fswatch.sh
# Usage: bash ~/.claude/hooks/git-fswatch.sh [path]

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Colors
readonly GREEN='\033[0;32m'
readonly RED='\033[0;31m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly CYAN='\033[0;36m'
readonly MAGENTA='\033[0;35m'
readonly NC='\033[0m' # No Color

# Configuration
WATCH_PATH="${1:-.}"
WATCH_PATH=$(cd "$WATCH_PATH" 2>/dev/null && pwd) || WATCH_PATH="."
REPO_NAME=$(basename "$WATCH_PATH")
DEBOUNCE_DELAY=${FSWATCH_DEBOUNCE:-12}       # Debounce delay (seconds, ensures <6 pushes/min GitHub limit)
AUTO_PULL_INTERVAL=${FSWATCH_PULL_INTERVAL:-300}  # Auto pull interval (seconds, default 5 minutes)
MAX_RETRIES=${FSWATCH_MAX_RETRIES:-3}        # Maximum retry attempts
LOG_FILE="${HOME}/.claude/logs/git-fswatch-${REPO_NAME}.log"
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/harness_state_dir.sh" 2>/dev/null \
  || harness_state_dir() { printf '%s\n' /tmp; }
LOCK_FILE="$(harness_state_dir)/git-fswatch-${USER}-${REPO_NAME}.lock"
STATE_FILE="$(harness_state_dir)/git-fswatch-state-${USER}-${REPO_NAME}.txt"

# Runtime state
COMMIT_TIMER_PID=""
LAST_PULL_TIME=$(date +%s)
CONSECUTIVE_FAILURES=0

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UTILITY FUNCTIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

log() {
    local level=$1
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

log_info() {
    echo -e "${BLUE}ℹ${NC} $*"
    log "INFO" "$*"
}

log_success() {
    echo -e "${GREEN}✓${NC} $*"
    log "SUCCESS" "$*"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $*"
    log "WARNING" "$*"
}

log_error() {
    echo -e "${RED}✗${NC} $*"
    log "ERROR" "$*"
}

log_critical() {
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}🚨 CRITICAL ERROR 🚨${NC}"
    echo -e "${RED}$*${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    log "CRITICAL" "$*"
}

# Cleanup on exit
cleanup() {
    log_info "Cleaning up..."

    # Kill pending commit timer
    if [ -n "$COMMIT_TIMER_PID" ]; then
        kill "$COMMIT_TIMER_PID" 2>/dev/null
    fi

    # Remove lock file
    rm -f "$LOCK_FILE"

    # Save state
    echo "stopped" > "$STATE_FILE"

    log_info "Git file watcher stopped"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# Check if another instance is running
check_lock() {
    if [ -f "$LOCK_FILE" ]; then
        local pid=$(cat "$LOCK_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            log_error "Another instance is already running (PID: $pid)"
            echo "To stop it: kill $pid"
            exit 1
        else
            log_warning "Stale lock file found, removing..."
            rm -f "$LOCK_FILE"
        fi
    fi

    echo $$ > "$LOCK_FILE"
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GIT OPERATIONS
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Check if directory is a git repository
check_git_repo() {
    if ! git -C "$WATCH_PATH" rev-parse --git-dir > /dev/null 2>&1; then
        log_critical "Not a git repository: $WATCH_PATH"
        echo "Initialize with: git init"
        exit 1
    fi
}

# Handle git lock files
handle_git_lock() {
    local lock_file="$WATCH_PATH/.git/index.lock"

    if [ ! -f "$lock_file" ]; then
        return 0
    fi

    log_warning "Git lock file detected: $lock_file"

    # Check for active git processes
    if pgrep -x git > /dev/null; then
        log_warning "Active git process found, waiting..."
        sleep 2
        return 1
    fi

    # Stale lock file
    log_warning "Stale lock file detected, removing..."
    rm -f "$lock_file"

    if [ $? -eq 0 ]; then
        log_success "Lock file removed"
        return 0
    else
        log_error "Failed to remove lock file"
        return 1
    fi
}

# Check for uncommitted changes
has_changes() {
    cd "$WATCH_PATH" || return 1

    # Check for modified, staged, or untracked files
    if ! git diff --quiet || \
       ! git diff --cached --quiet || \
       [ -n "$(git ls-files --others --exclude-standard)" ]; then
        return 0
    fi

    return 1
}

# Perform git pull with conflict detection
safe_pull() {
    cd "$WATCH_PATH" || return 1

    log_info "Checking for remote changes..."

    # Fetch first
    if ! git fetch origin 2>&1 | tee -a "$LOG_FILE"; then
        log_error "Failed to fetch from remote"
        return 1
    fi

    # Check if behind remote
    local branch=$(git branch --show-current)
    local behind=$(git rev-list --count HEAD..origin/"$branch" 2>/dev/null || echo "0")

    if [ "$behind" = "0" ]; then
        log_info "Already up to date"
        return 0
    fi

    log_info "Behind remote by $behind commit(s), pulling..."

    # Stash if there are changes
    local stashed=0
    if has_changes; then
        log_info "Stashing local changes..."
        if git stash push -m "fswatch auto-stash $(date +%s)" 2>&1 | tee -a "$LOG_FILE"; then
            stashed=1
            log_success "Changes stashed"
        else
            log_error "Failed to stash changes"
            return 1
        fi
    fi

    # Pull with rebase
    if git pull --rebase origin "$branch" 2>&1 | tee -a "$LOG_FILE"; then
        log_success "Pull successful"

        # Pop stash if we stashed
        if [ "$stashed" = "1" ]; then
            log_info "Restoring stashed changes..."
            if git stash pop 2>&1 | tee -a "$LOG_FILE"; then
                log_success "Stashed changes restored"
            else
                log_error "Failed to restore stash, conflicts may exist"
                log_critical "MANUAL INTERVENTION REQUIRED"
                echo ""
                echo "To resolve:"
                echo "  1. Fix conflicts in the files"
                echo "  2. git add <resolved-files>"
                echo "  3. git rebase --continue"
                echo "  4. git stash pop  # to restore your changes"
                echo ""
                echo "Or abort: git rebase --abort && git stash pop"
                return 1
            fi
        fi

        return 0
    else
        log_error "Pull failed, checking for conflicts..."

        # Check if it's a conflict
        if git status | grep -q "Unmerged paths\|both modified"; then
            log_critical "MERGE CONFLICT DETECTED"
            echo ""
            echo "Conflicted files:"
            git diff --name-only --diff-filter=U | sed 's/^/  - /'
            echo ""
            echo "To resolve:"
            echo "  1. Edit the conflicted files"
            echo "  2. git add <resolved-files>"
            echo "  3. git rebase --continue"
            if [ "$stashed" = "1" ]; then
                echo "  4. git stash pop  # to restore your stashed changes"
            fi
            echo ""
            echo "Or abort: git rebase --abort"
            if [ "$stashed" = "1" ]; then
                echo "         git stash pop"
            fi
            echo ""
            echo "File watcher will pause until conflicts are resolved."
            return 1
        fi

        return 1
    fi
}

# NOTE: safe_add() was removed on 2026-04-16 (SaaS-grade blame audit fix).
# It called `git add .` on the REAL index before every fswatch cycle, silently
# polluting the user's staged area. checkpoint-core.sh writes to an isolated
# temp index (GIT_INDEX_FILE) so pre-staging is redundant. sync_changes()
# now calls safe_commit() directly without a staging step.

# Source the shared checkpoint library once (idempotent)
if [ -z "${_CHECKPOINT_CORE_SOURCED:-}" ]; then
    # shellcheck source=lib/checkpoint-core.sh
    if [ -f "$HOME/.claude/hooks/lib/checkpoint-core.sh" ]; then
        . "$HOME/.claude/hooks/lib/checkpoint-core.sh"
        _CHECKPOINT_CORE_SOURCED=1
    fi
fi

# Write a snapshot to refs/checkpoints/<branch> via the shared library.
# The working branch HEAD is never moved. Replaces the former `git commit`
# path so fswatch no longer pollutes branch history.
#
# The checkpoint-core library uses an isolated temp index (GIT_INDEX_FILE),
# so the real .git/index is never touched by the snapshot operation.
safe_commit() {
    cd "$WATCH_PATH" || return 1

    # Short-circuit if there are no changes at all (tracked or untracked).
    local untracked
    untracked=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
    if git diff --quiet && git diff --cached --quiet && [ "$untracked" -eq 0 ]; then
        log_info "No changes to checkpoint"
        return 0
    fi

    # handle_git_lock() is retained because temp-index build still reads
    # metadata; but the lib itself uses an isolated index and does not
    # contend for .git/index.lock.
    if ! handle_git_lock; then
        return 1
    fi

    if [ -z "${_CHECKPOINT_CORE_SOURCED:-}" ]; then
        log_error "checkpoint-core.sh not available at ~/.claude/hooks/lib/"
        return 1
    fi

    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    log_info "Writing checkpoint to refs/checkpoints/<branch>..."

    if write_checkpoint "$WATCH_PATH" "fswatch daemon: $REPO_NAME"; then
        local branch sanitized ref tip
        branch=$(git branch --show-current 2>/dev/null)
        if [ -n "$branch" ]; then
            sanitized=$(printf '%s' "$branch" | tr '/' '-')
        else
            local short
            short=$(git rev-parse --short HEAD 2>/dev/null)
            sanitized="detached-${short:-empty}"
        fi
        ref="refs/checkpoints/${sanitized}"
        tip=$(git rev-parse --short "$ref" 2>/dev/null)
        log_success "Checkpoint created: ${tip:-?} on ${ref} (at ${timestamp})"
        return 0
    else
        log_error "Failed to create checkpoint (see ~/.claude/logs/checkpoint.log)"
        return 1
    fi
}

# Perform git push with retry logic
safe_push() {
    cd "$WATCH_PATH" || return 1

    local branch=$(git branch --show-current)

    if [ -z "$branch" ]; then
        log_error "Not on a branch (detached HEAD)"
        return 1
    fi

    # Check if there's anything to push
    local ahead=$(git rev-list --count origin/"$branch"..HEAD 2>/dev/null || echo "0")

    if [ "$ahead" = "0" ]; then
        log_info "Nothing to push"
        return 0
    fi

    log_info "Pushing $ahead commit(s) to origin/$branch..."

    local retry=0
    while [ $retry -lt $MAX_RETRIES ]; do
        if git push origin "$branch" 2>&1 | tee -a "$LOG_FILE"; then
            log_success "Push successful"
            CONSECUTIVE_FAILURES=0
            return 0
        else
            retry=$((retry + 1))
            log_warning "Push failed (attempt $retry/$MAX_RETRIES)"

            # Check if we need to pull first
            if git status 2>&1 | grep -q "have diverged\|behind"; then
                log_warning "Branch has diverged, pulling first..."
                if safe_pull; then
                    log_info "Retrying push after pull..."
                    continue
                else
                    log_error "Pull failed, cannot push"
                    return 1
                fi
            fi

            if [ $retry -lt $MAX_RETRIES ]; then
                log_info "Retrying in 5 seconds..."
                sleep 5
            fi
        fi
    done

    log_error "Push failed after $MAX_RETRIES attempts"
    CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))

    if [ $CONSECUTIVE_FAILURES -ge 3 ]; then
        log_critical "MULTIPLE PUSH FAILURES DETECTED"
        echo ""
        echo "Possible causes:"
        echo "  • Network connectivity issues"
        echo "  • Authentication failure"
        echo "  • Remote repository unavailable"
        echo "  • Insufficient permissions"
        echo ""
        echo "Suggestions:"
        echo "  1. Check network: ping github.com"
        echo "  2. Check remote: git remote -v"
        echo "  3. Test authentication: git push --dry-run"
        echo "  4. Check git credentials"
        echo ""
        echo "File watcher will continue but won't push until issue is resolved."
        CONSECUTIVE_FAILURES=0  # Reset to avoid spam
    fi

    return 1
}

# Complete sync operation
sync_changes() {
    log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log_info "Starting sync operation..."

    # Step 1: Check for changes
    if ! has_changes; then
        log_info "No changes detected, skipping sync"
        return 0
    fi

    # Step 2: Checkpoint (writes to refs/checkpoints/<branch> via temp index;
    # the real .git/index is never touched — no pre-staging needed).
    if ! safe_commit; then
        log_error "Sync failed at checkpoint stage"
        return 1
    fi

    # Step 3: Pull (periodic or before push)
    local current_time=$(date +%s)
    local time_since_pull=$((current_time - LAST_PULL_TIME))

    if [ $time_since_pull -gt $AUTO_PULL_INTERVAL ]; then
        log_info "Periodic pull check (last pull: ${time_since_pull}s ago)"
        if safe_pull; then
            LAST_PULL_TIME=$current_time
        else
            log_warning "Pull failed, will retry later"
            # Don't fail the whole sync, commit is already done
        fi
    fi

    # Step 4: Push
    if ! safe_push; then
        log_error "Sync failed at push stage (commit is safe locally)"
        return 1
    fi

    log_success "Sync completed successfully"
    log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return 0
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DEBOUNCE & EVENT HANDLING
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Debounced commit function
schedule_commit() {
    # Cancel previous timer
    if [ -n "$COMMIT_TIMER_PID" ] && kill -0 "$COMMIT_TIMER_PID" 2>/dev/null; then
        kill "$COMMIT_TIMER_PID" 2>/dev/null
        log_info "Debouncing... (previous timer cancelled)"
    fi

    # Schedule new commit
    (
        sleep "$DEBOUNCE_DELAY"
        sync_changes
    ) &

    COMMIT_TIMER_PID=$!
}

# Handle file system events
handle_event() {
    local event_file="$1"

    # Ignore events in .git directory
    if echo "$event_file" | grep -q "\.git/"; then
        return
    fi

    log_info "Change detected: $event_file"
    schedule_commit
}

#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

main() {
    # Ensure log directory exists
    mkdir -p "$(dirname "$LOG_FILE")"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${CYAN}🔍 Git File Watcher (fswatch)${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Validate watch path
    if [ ! -d "$WATCH_PATH" ]; then
        log_critical "Directory does not exist: $WATCH_PATH"
        exit 1
    fi

    # Check for git repository
    check_git_repo

    # Check for another instance
    check_lock

    # Check fswatch availability
    if ! command -v fswatch &> /dev/null; then
        log_critical "fswatch not found"
        echo "Install with: sudo apt-get install fswatch"
        exit 1
    fi

    # Display configuration
    echo "Configuration:"
    echo "  • Watch path: $WATCH_PATH"
    echo "  • Debounce delay: ${DEBOUNCE_DELAY}s"
    echo "  • Auto-pull interval: ${AUTO_PULL_INTERVAL}s"
    echo "  • Max retries: $MAX_RETRIES"
    echo "  • Log file: $LOG_FILE"
    echo ""

    # Get git info
    cd "$WATCH_PATH"
    local branch=$(git branch --show-current)
    local remote=$(git remote get-url origin 2>/dev/null || echo "No remote")

    echo "Repository:"
    echo "  • Branch: $branch"
    echo "  • Remote: $remote"
    echo ""

    log_info "Starting file watcher..."
    echo -e "${GREEN}✓${NC} Watching for changes (Press Ctrl+C to stop)"
    echo ""

    # Save state
    echo "running:$WATCH_PATH:$$" > "$STATE_FILE"

    # Initial sync
    log_info "Performing initial sync..."
    sync_changes

    # Start watching
    fswatch -r \
        --exclude='\.git/' \
        --exclude='node_modules/' \
        --exclude='__pycache__/' \
        --exclude='\.pyc$' \
        --exclude='\.swp$' \
        --exclude='\.tmp$' \
        --exclude='\.log$' \
        --event Created \
        --event Updated \
        --event Removed \
        --event Renamed \
        "$WATCH_PATH" | while read file; do
        handle_event "$file"
    done
}

# Run main
main "$@"
