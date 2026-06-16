#!/bin/bash
# ============================================================================
# LEGACY / DO NOT USE — describes an obsolete auto-commit model.
# ============================================================================
# This installer reflects an OLD "auto-commit + auto-push after every response"
# design that the current harness does NOT use. Today git mutations are
# grant-gated (see README.md / ARCHITECTURE.md §6): /commit and /push each
# require a single-use, human-authorized grant; nothing commits or pushes
# automatically. This script is kept only for historical reference and is NOT
# part of the live setup — the canonical install is the root README Quickstart.
# It is a no-op guard below so a stale invocation does nothing.
# ============================================================================
echo "[LEGACY] hooks/install.sh describes the obsolete auto-commit model and is disabled." >&2
echo "[LEGACY] Use the root README Quickstart; git here is grant-gated, never automatic." >&2
exit 0

# ----------------------------------------------------------------------------
# Claude Code Auto-Commit One-Click Installer (legacy body, unreachable)
# Purpose: Quick installation and configuration of Claude Code auto-commit functionality
# Usage: bash install.sh
# ----------------------------------------------------------------------------

set -e

# Color definitions
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

# Print header
print_header() {
  echo -e "${BOLD}${BLUE}"
  echo "╔════════════════════════════════════════════════════════════════════════════╗"
  echo "║                                                                            ║"
  echo "║   Claude Code Auto-Commit Installer                                       ║"
  echo "║   Claude Code Auto-Commit Setup                                            ║"
  echo "║                                                                            ║"
  echo "╚════════════════════════════════════════════════════════════════════════════╝"
  echo -e "${NC}"
}

# Print step
print_step() {
  echo -e "${BOLD}${BLUE}➜ $1${NC}"
}

# Print success message
print_success() {
  echo -e "${GREEN}✅ $1${NC}"
}

# Print warning message
print_warning() {
  echo -e "${YELLOW}⚠️  $1${NC}"
}

# Print error message
print_error() {
  echo -e "${RED}❌ $1${NC}"
}

# Check if command exists
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Main installation flow
main() {
  print_header

  # Step 1: Create directories
  print_step "Creating hooks directory..."
  mkdir -p ~/.claude/hooks
  print_success "Directory creation complete"

  # Step 2: Check if files exist
  if [ -f ~/.claude/hooks/auto-commit.sh ]; then
    print_warning "Detected existing configuration files"
    read -p "Overwrite existing files? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      print_warning "Installation cancelled"
      exit 0
    fi
  fi

  # Step 3: Download or copy script files
  # Note: This installer assumes you are in the ~/.claude/hooks/ directory
  # If downloading from network, modify this section
  print_step "Checking script files..."

  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  if [ -f "$SCRIPT_DIR/auto-commit.sh" ]; then
    print_success "Script files exist"
  else
    print_error "Script files not found. Please ensure running in correct directory."
    exit 1
  fi

  # Step 4: Set execution permissions
  print_step "Setting script execution permissions..."
  chmod +x ~/.claude/hooks/auto-commit.sh
  chmod +x ~/.claude/hooks/ensure-git-repo.sh
  print_success "Permissions set complete"

  # Step 5: Backup existing settings.json
  if [ -f ~/.claude/settings.json ]; then
    print_step "Backing up existing configuration..."
    cp ~/.claude/settings.json ~/.claude/settings.json.backup.$(date +%Y%m%d_%H%M%S)
    print_success "Configuration backed up"
  fi

  # Step 6: Check dependencies
  print_step "Checking dependencies..."

  if ! command_exists git; then
    print_error "Git not installed. Please install Git first."
    exit 1
  fi
  print_success "Git installed"

  if ! command_exists gh; then
    print_warning "GitHub CLI not installed (optional)"
    echo -e "${YELLOW}  Installation method:${NC}"
    echo -e "${YELLOW}    macOS: brew install gh${NC}"
    echo -e "${YELLOW}    Linux: sudo apt install gh${NC}"
    echo -e "${YELLOW}    Other: https://cli.github.com/${NC}"
  else
    print_success "GitHub CLI installed"

    if ! gh auth status > /dev/null 2>&1; then
      print_warning "GitHub CLI not logged in"
      echo -e "${YELLOW}  Run: gh auth login${NC}"
    else
      print_success "GitHub CLI logged in"
    fi
  fi

  # Step 7: Configure environment variables (optional)
  print_step "Configuring environment variables (optional)..."

  read -p "Enable automatic GitHub repository creation? (y/N): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    SHELL_RC=""
    if [ -f ~/.bashrc ]; then
      SHELL_RC=~/.bashrc
    elif [ -f ~/.zshrc ]; then
      SHELL_RC=~/.zshrc
    fi

    if [ -n "$SHELL_RC" ]; then
      if ! grep -q "CLAUDE_AUTO_CREATE_REPO" "$SHELL_RC"; then
        echo "" >> "$SHELL_RC"
        echo "# Claude Code Auto-Commit Configuration" >> "$SHELL_RC"
        echo "export CLAUDE_AUTO_CREATE_REPO=true" >> "$SHELL_RC"
        print_success "Environment variable added to $SHELL_RC"
        print_warning "Please run: source $SHELL_RC"
      else
        print_warning "Environment variable already exists in $SHELL_RC"
      fi
    fi
  fi

  # Step 8: Complete
  echo ""
  echo -e "${BOLD}${GREEN}"
  echo "╔════════════════════════════════════════════════════════════════════════════╗"
  echo "║                                                                            ║"
  echo "║   ✅ Installation Complete!                                                ║"
  echo "║                                                                            ║"
  echo "╚════════════════════════════════════════════════════════════════════════════╝"
  echo -e "${NC}"

  echo -e "${BOLD}Next steps:${NC}"
  echo -e "  ${BLUE}1.${NC} Restart Claude Code"
  echo -e "  ${BLUE}2.${NC} View documentation: ${YELLOW}cat ~/.claude/hooks/README.md${NC}"
  echo -e "  ${BLUE}3.${NC} Quick start: ${YELLOW}cat ~/.claude/hooks/QUICKSTART.md${NC}"
  echo ""
  echo -e "${BOLD}Test installation:${NC}"
  echo -e "  ${YELLOW}bash ~/.claude/hooks/auto-commit.sh${NC}"
  echo ""
}

# Run installation
main

exit 0
