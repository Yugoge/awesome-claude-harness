#!/bin/bash
# sb-setup.sh <harness-dir>
# Build a disposable sandbox root at $SB for ns.sh / ns-alt.sh.
#   $SB/harness       copy of <harness-dir> (working tree incl. uncommitted changes) + venv;
#                     ns.sh binds it onto /root/.claude
#   $SB/harness-boot  same copy for the alternate-home layout (ns-alt.sh -> /home/alice/.claude)
#   $SB/roothome      becomes /root inside ns.sh: toyproj (product repo) + toyproj-origin.git
#   $SB/alt/home      becomes /home/alice inside ns-alt.sh: same toy repo pair
#   $SB/{tmp,vartmp,shm} and $SB/alt/{tmp,vartmp,shm}  private /tmp, /var/tmp, /dev/shm
# Nothing outside $SB is written. Re-run to rebuild from scratch.
set -euo pipefail
SB="${SB:?set SB to an empty scratch directory}"
SRC="$(cd "${1:?usage: sb-setup.sh <harness-dir>}" && pwd)"
PY="${SB_PYTHON:-$(command -v python3.12 || command -v python3)}"
mkdir -p "$SB"/{roothome,tmp,vartmp/claude-scratch,shm,logs,payloads} "$SB"/alt/{home,tmp,vartmp/claude-scratch,shm}

copy_harness() {  # <dest>
  rm -rf "$1"; mkdir -p "$1"
  (cd "$SRC" && tar --exclude=./venv --exclude='__pycache__' -cf - .) | tar -xf - -C "$1"
  # snapshot the working tree so reset.sh restores the state under test, not the last commit
  git -C "$1" -c core.hooksPath=/dev/null -c user.name=sandbox -c user.email=sandbox@example.invalid \
    commit -qa --allow-empty -m "sandbox snapshot" >/dev/null 2>&1 || true
  git -C "$1" add -A && git -C "$1" -c core.hooksPath=/dev/null -c user.name=sandbox \
    -c user.email=sandbox@example.invalid commit -q --allow-empty -m "sandbox snapshot (untracked)"
  "$PY" -m venv "$1/venv"
  local ver; ver=$("$PY" -c 'import sys;print(f"py{sys.version_info[0]}{sys.version_info[1]}")')
  if [ -f "$1/requirements/$ver.txt" ]; then
    "$1/venv/bin/pip" install -q --require-hashes -r "$1/requirements/$ver.txt"
  else
    "$1/venv/bin/pip" install -q -r "$1/requirements.txt"
  fi
}

make_toy() {  # <home-dir> <origin path as seen inside the namespace>
  local T="$1/toyproj" O="$1/toyproj-origin.git"
  rm -rf "$T" "$O"; mkdir -p "$T/toy" "$T/tests"
  printf '__pycache__/\n.pytest_cache/\n' > "$T/.gitignore"
  printf '# CLAUDE.md\n\n> Project-specific settings for toyproj\n' > "$T/CLAUDE.md"
  printf '# toy\n' > "$T/README.md"
  printf 'def add(a, b):\n    return a + b\n' > "$T/toy/__init__.py"
  printf 'def sub(a,b): return a-b\n' > "$T/toy/util.py"
  printf 'from toy import add\n\ndef test_add():\n    assert add(2, 3) == 5\n' > "$T/tests/test_add.py"
  git -C "$T" init -q -b master
  git -C "$T" config user.name sandbox; git -C "$T" config user.email sandbox@example.invalid
  git -C "$T" add -A; git -C "$T" commit -qm "init toy"; git -C "$T" tag sb-init
  git clone -q --bare "$T" "$O"
  git -C "$T" remote add origin "$2"   # resolved inside the namespace; reset.sh fetches
}

rm -rf "$SB/tools"; mkdir -p "$SB/tools"   # tools resolve each other at /mnt/sb/tools inside the namespace
cp "$(dirname "$0")"/*.py "$(dirname "$0")"/*.sh "$SB/tools/"
copy_harness "$SB/harness"
copy_harness "$SB/harness-boot"
make_toy "$SB/roothome" /root/toyproj-origin.git
make_toy "$SB/alt/home" /home/alice/toyproj-origin.git
echo "sandbox ready at $SB (harness from $SRC, python $("$PY" --version 2>&1))"
