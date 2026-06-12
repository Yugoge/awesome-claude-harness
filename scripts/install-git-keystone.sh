#!/usr/bin/env bash
# install-git-keystone.sh — wire the git-native reference-transaction keystone
# (M7) via core.hooksPath relocation WITHOUT clobbering existing hooks (AC6).
#
# Usage: install-git-keystone.sh --project-dir <repo> [--keystone-src <dir>]
#
# What it does (idempotent):
#   1. Inventory every NON-sample hook in the repo's CURRENT hooks dir.
#   2. Create a new keystone hooksPath dir: <git_common_dir>/keystone-hooks/.
#   3. Copy the keystone `reference-transaction` hook into it.
#   4. Re-home each inventoried hook into <keystone>/preserved/<name> and write
#      a thin dispatcher <keystone>/<name> that execs the preserved original
#      (so pre-commit / post-commit / etc. STILL FIRE after relocation — AC6).
#   5. Point core.hooksPath at the new dir.
#
# Rollback: `git config --unset core.hooksPath` (or set it back to the prior
# value printed by this script) and remove <keystone> dir. Non-destructive:
# the original hooks remain copied under preserved/.
#
# Exit: 0 = installed/already-installed; 1 = error.

set -euo pipefail

PROJECT_DIR=""
KEYSTONE_SRC="$(cd "$(dirname "$0")/.." && pwd)/hooks/git-keystone"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --keystone-src) KEYSTONE_SRC="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done
[[ -n "$PROJECT_DIR" ]] || PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

GIT_COMMON_DIR="$(git -C "$PROJECT_DIR" rev-parse --git-common-dir 2>/dev/null)"
[[ -n "$GIT_COMMON_DIR" ]] || { echo "Error: not a git repo: $PROJECT_DIR" >&2; exit 1; }
# Normalize to absolute
GIT_COMMON_DIR="$(cd "$PROJECT_DIR" && cd "$GIT_COMMON_DIR" && pwd -P)"

KEYSTONE_DIR="$GIT_COMMON_DIR/keystone-hooks"
PRESERVED_DIR="$KEYSTONE_DIR/preserved"

# Current hooks dir (explicit core.hooksPath if set, else default <common>/hooks)
CUR_HOOKS="$(git -C "$PROJECT_DIR" config --local --get core.hooksPath 2>/dev/null || true)"
[[ -n "$CUR_HOOKS" ]] || CUR_HOOKS="$GIT_COMMON_DIR/hooks"

# Idempotency: if core.hooksPath already points at our keystone dir, refresh the
# keystone hook only and exit.
if [[ "$CUR_HOOKS" == "$KEYSTONE_DIR" ]]; then
  install -m 0755 "$KEYSTONE_SRC/reference-transaction" "$KEYSTONE_DIR/reference-transaction"
  echo "KEYSTONE_DIR=$KEYSTONE_DIR (already installed; keystone refreshed)"
  exit 0
fi

mkdir -p "$KEYSTONE_DIR" "$PRESERVED_DIR"
install -m 0755 "$KEYSTONE_SRC/reference-transaction" "$KEYSTONE_DIR/reference-transaction"

# Inventory + re-home + chain every non-sample hook present NOW.
REHOMED=()
if [[ -d "$CUR_HOOKS" ]]; then
  for src in "$CUR_HOOKS"/*; do
    [[ -e "$src" ]] || continue
    name="$(basename "$src")"
    case "$name" in
      *.sample) continue ;;
      reference-transaction) continue ;;  # keystone owns this name
      keystone-hooks) continue ;;
    esac
    [[ -f "$src" ]] || continue
    cp -p "$src" "$PRESERVED_DIR/$name"
    chmod +x "$PRESERVED_DIR/$name" 2>/dev/null || true
    # Thin dispatcher that execs the preserved original with all args + stdin.
    cat > "$KEYSTONE_DIR/$name" <<DISP
#!/usr/bin/env bash
# Auto-generated dispatcher (install-git-keystone.sh): preserves the original
# $name hook after core.hooksPath relocation so it STILL FIRES (AC6).
set -u
PRESERVED="\$(dirname "\$0")/preserved/$name"
[ -x "\$PRESERVED" ] || exit 0
exec "\$PRESERVED" "\$@"
DISP
    chmod +x "$KEYSTONE_DIR/$name"
    REHOMED+=("$name")
  done
fi

# Record prior hooksPath for rollback visibility.
PRIOR="$(git -C "$PROJECT_DIR" config --local --get core.hooksPath 2>/dev/null || echo '<unset/default>')"
git -C "$PROJECT_DIR" config --local core.hooksPath "$KEYSTONE_DIR"

echo "KEYSTONE_DIR=$KEYSTONE_DIR"
echo "PRIOR_HOOKSPATH=$PRIOR"
echo "REHOMED_HOOKS=${REHOMED[*]:-none}"
