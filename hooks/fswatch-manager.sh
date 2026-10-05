#!/bin/bash
# fswatch-manager.sh - Manage git-fswatch instances
# Git file watcher management script
# Location: ~/.claude/hooks/fswatch-manager.sh
# Usage: bash ~/.claude/hooks/fswatch-manager.sh [command] [path]

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_PATH="$HOME/.claude/hooks/git-fswatch.sh"
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/harness_state_dir.sh" 2>/dev/null \
  || harness_state_dir() { printf '%s\n' /tmp; }
STATE_FILE="$(harness_state_dir)/git-fswatch-state-${USER}.txt"

# Show usage
usage() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${CYAN}Git File Watcher Manager${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Usage: bash $0 [command] [path]"
    echo ""
    echo "Commands:"
    echo "  start <path>    - Start watching a directory"
    echo "  stop [path]     - Stop watching (all or specific directory)"
    echo "  restart <path>  - Restart watcher for a directory"
    echo "  status          - Show all running watchers"
    echo "  logs [path]     - Show logs (tail -f)"
    echo "  test <path>     - Test configuration"
    echo "  install-service - Install systemd service (root required)"
    echo "  enable <path>   - Enable watcher on boot"
    echo "  disable <path>  - Disable watcher on boot"
    echo ""
    echo "Examples:"
    echo "  $0 start ~/my-project"
    echo "  $0 status"
    echo "  $0 stop"
    echo "  $0 logs ~/my-project"
    echo ""
}

# Check if path is a git repo
check_git_repo() {
    local path="$1"
    if [ ! -d "$path" ]; then
        echo -e "${RED}✗${NC} Directory does not exist: $path"
        return 1
    fi

    if ! git -C "$path" rev-parse --git-dir > /dev/null 2>&1; then
        echo -e "${RED}✗${NC} Not a git repository: $path"
        return 1
    fi

    return 0
}

# Start watcher
start_watcher() {
    local path="${1:-.}"
    path=$(cd "$path" && pwd)  # Absolute path

    echo -e "${BLUE}Starting watcher for: $path${NC}"

    if ! check_git_repo "$path"; then
        return 1
    fi

    # Check if already running
    if pgrep -f "git-fswatch.sh $path" > /dev/null; then
        echo -e "${YELLOW}⚠${NC} Watcher already running for: $path"
        echo "Stop it first with: $0 stop $path"
        return 1
    fi

    # Start in background
    nohup bash "$SCRIPT_PATH" "$path" > /dev/null 2>&1 &
    local pid=$!

    sleep 2

    if kill -0 $pid 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Watcher started (PID: $pid)"
        echo "View logs: $0 logs $path"
        return 0
    else
        echo -e "${RED}✗${NC} Failed to start watcher"
        return 1
    fi
}

# Stop watcher
stop_watcher() {
    local path="$1"

    if [ -z "$path" ]; then
        # Stop all
        echo -e "${BLUE}Stopping all watchers...${NC}"
        local pids=$(pgrep -f "git-fswatch.sh")

        if [ -z "$pids" ]; then
            echo -e "${YELLOW}⚠${NC} No watchers running"
            return 0
        fi

        echo "$pids" | while read pid; do
            kill "$pid" 2>/dev/null
            echo -e "${GREEN}✓${NC} Stopped watcher (PID: $pid)"
        done
    else
        path=$(cd "$path" && pwd)
        echo -e "${BLUE}Stopping watcher for: $path${NC}"

        local pid=$(pgrep -f "git-fswatch.sh $path")

        if [ -z "$pid" ]; then
            echo -e "${YELLOW}⚠${NC} No watcher running for: $path"
            return 0
        fi

        kill "$pid" 2>/dev/null
        echo -e "${GREEN}✓${NC} Stopped watcher (PID: $pid)"
    fi

    return 0
}

# Show status
show_status() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${CYAN}Git File Watcher Status${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    local pids=$(pgrep -f "git-fswatch.sh" | grep -v "$$")

    if [ -z "$pids" ]; then
        echo -e "${YELLOW}⚠${NC} No watchers running"
        return 0
    fi

    echo "Running watchers:"
    echo ""

    echo "$pids" | while read pid; do
        local cmdline=$(ps -p "$pid" -o cmd= | grep -o 'git-fswatch.sh.*')
        local watch_path=$(echo "$cmdline" | awk '{print $2}')
        local uptime=$(ps -p "$pid" -o etime= | tr -d ' ')

        echo -e "${GREEN}✓${NC} PID: $pid"
        echo "  Path: $watch_path"
        echo "  Uptime: $uptime"
        echo ""
    done

    # Check state file
    if [ -f "$STATE_FILE" ]; then
        echo "State file: $STATE_FILE"
        cat "$STATE_FILE"
        echo ""
    fi
}

# Show logs
show_logs() {
    local path="$1"
    local log_file="$HOME/.claude/logs/git-fswatch.log"

    if [ ! -f "$log_file" ]; then
        echo -e "${YELLOW}⚠${NC} No log file found: $log_file"
        return 1
    fi

    echo -e "${BLUE}Tailing log file (Ctrl+C to stop)${NC}"
    echo ""

    if [ -n "$path" ]; then
        tail -f "$log_file" | grep --line-buffered "$path"
    else
        tail -f "$log_file"
    fi
}

# Test configuration
test_config() {
    local path="${1:-.}"

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${CYAN}Testing Configuration${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Check fswatch
    echo -n "Checking fswatch... "
    if command -v fswatch &> /dev/null; then
        local version=$(fswatch --version | head -1)
        echo -e "${GREEN}✓${NC} $version"
    else
        echo -e "${RED}✗ Not installed${NC}"
        echo "Install: sudo apt-get install fswatch"
        return 1
    fi

    # Check git repo
    echo -n "Checking git repository... "
    if check_git_repo "$path"; then
        echo -e "${GREEN}✓${NC} Valid git repo"
    else
        return 1
    fi

    # Check git config
    echo -n "Checking git config... "
    cd "$path"
    local branch=$(git branch --show-current)
    local remote=$(git remote get-url origin 2>/dev/null || echo "")

    if [ -z "$branch" ]; then
        echo -e "${YELLOW}⚠${NC} Detached HEAD"
    elif [ -z "$remote" ]; then
        echo -e "${YELLOW}⚠${NC} No remote configured"
    else
        echo -e "${GREEN}✓${NC} Branch: $branch, Remote: $(basename $remote)"
    fi

    # Check permissions
    echo -n "Checking permissions... "
    if [ -w "$path" ]; then
        echo -e "${GREEN}✓${NC} Writable"
    else
        echo -e "${RED}✗${NC} Not writable"
        return 1
    fi

    # Check script
    echo -n "Checking script... "
    if [ -x "$SCRIPT_PATH" ]; then
        echo -e "${GREEN}✓${NC} Executable"
    else
        echo -e "${RED}✗${NC} Not executable"
        echo "Fix: chmod +x $SCRIPT_PATH"
        return 1
    fi

    echo ""
    echo -e "${GREEN}✓ All checks passed${NC}"
    return 0
}

# Install systemd service
install_service() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}✗${NC} Must run as root (use sudo)"
        return 1
    fi

    local service_file="$HOME/.claude/systemd/git-fswatch@.service"

    if [ ! -f "$service_file" ]; then
        echo -e "${RED}✗${NC} Service file not found: $service_file"
        return 1
    fi

    echo -e "${BLUE}Installing systemd service...${NC}"

    cp "$service_file" /etc/systemd/system/
    systemctl daemon-reload

    echo -e "${GREEN}✓${NC} Service installed"
    echo ""
    echo "Enable for a directory:"
    echo "  sudo systemctl enable git-fswatch@my-project"
    echo "  sudo systemctl start git-fswatch@my-project"
}

# Main
case "$1" in
    start)
        start_watcher "$2"
        ;;
    stop)
        stop_watcher "$2"
        ;;
    restart)
        stop_watcher "$2"
        sleep 1
        start_watcher "$2"
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs "$2"
        ;;
    test)
        test_config "$2"
        ;;
    install-service)
        install_service
        ;;
    *)
        usage
        exit 1
        ;;
esac
