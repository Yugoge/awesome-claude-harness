#!/bin/bash
# start-fswatch-all.sh - Start fswatch monitoring for all important repositories
# Location: ~/.claude/hooks/start-fswatch-all.sh
# Usage: bash ~/.claude/hooks/start-fswatch-all.sh

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 FSWatch Batch Starter"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Automatically discover all git repositories
REPOS=()
while IFS= read -r git_dir; do
    repo_dir=$(dirname "$git_dir")
    REPOS+=("$repo_dir")
done < <(find ~ -maxdepth 3 -type d -name ".git" 2>/dev/null | sort)

if [ ${#REPOS[@]} -eq 0 ]; then
    echo "❌ No git repositories found"
    exit 1
fi

echo "📍 Found ${#REPOS[@]} repositories:"
for repo in "${REPOS[@]}"; do
    echo "   - $(basename "$repo")"
done
echo ""

started_count=0
skipped_count=0
failed_count=0

for repo in "${REPOS[@]}"; do
    repo_name=$(basename "$repo")

    # Check if git repo has remote
    if ! git -C "$repo" remote get-url origin >/dev/null 2>&1; then
        echo "⏭️  $repo_name: No remote, skipping"
        ((skipped_count++))
        continue
    fi

    # Check if already running
    if ps aux | grep -q "[g]it-fswatch.sh $repo"; then
        echo "⏭️  $repo_name: Already monitoring"
        ((skipped_count++))
        continue
    fi

    # Start fswatch
    log_file="$HOME/.claude/logs/fswatch-$repo_name.log"
    pid_file="$HOME/.claude/logs/fswatch-$repo_name.pid"

    # Create logs directory if not exists
    mkdir -p "$HOME/.claude/logs"

    # Remove old lock file if exists
    . "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/harness_state_dir.sh" 2>/dev/null \
      || harness_state_dir() { printf '%s\n' /tmp; }
    rm -f "$(harness_state_dir)/git-fswatch-${USER}.lock" 2>/dev/null

    nohup bash ~/.claude/hooks/git-fswatch.sh "$repo" \
        > "$log_file" 2>&1 &

    pid=$!

    # Wait a moment to check if process started successfully
    sleep 1

    if ps -p $pid > /dev/null 2>&1; then
        echo $pid > "$pid_file"
        echo "✅ $repo_name: Monitoring started (PID: $pid)"
        ((started_count++))
    else
        echo "❌ $repo_name: Failed to start (check $log_file)"
        ((failed_count++))
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ FSWatch startup complete!"
echo ""
echo "Summary:"
echo "  - Started:  $started_count"
echo "  - Skipped:  $skipped_count"
echo "  - Failed:   $failed_count"
echo ""
echo "Commands:"
echo "  Check status:   bash ~/.claude/hooks/protection-status.sh"
echo "  View logs:      tail -f ~/.claude/logs/fswatch-*.log"
echo "  Stop all:       pkill -f git-fswatch.sh"
echo "  Stop specific:  kill \$(cat ~/.claude/logs/fswatch-REPO_NAME.pid)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
