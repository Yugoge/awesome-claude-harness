#!/usr/bin/env bash
# repair-venv.sh — durably restore a Python venv when its bin/python3 symlink target is missing.
#
# Behavior (per BA spec docs/dev/ticket-20260529-081014.md M5):
#   1. Resolves venv path from script's own location ($BASH_SOURCE) — NOT cwd.
#      Override with --venv <path>.
#   2. Parses <venv>/pyvenv.cfg for `executable = <path>` (no hardcoded /usr/bin/python3.NN).
#   3. Verifies the parsed executable exists and is executable.
#   4. Creates <venv>/bin/python3 -> <executable> if missing or broken; never overwrites a
#      healthy file.
#   5. Verifies health: all three of <venv>/bin/{python,python3,python3.12} -m pytest --version
#      exit 0 with output matching ^pytest\s+\d+\.\d+; find <venv>/bin -maxdepth 1
#      -name 'python*' -type l -xtype l returns empty; <venv>/bin/python -c
#      'import sys; assert sys.prefix.endswith("venv")' exits 0.
#   6. Idempotent: if all checks pass on entry, prints "already healthy" and exits 0 without
#      touching anything. mtime of bin/python3 is preserved.
#   7. Does NOT mutate site-packages or recreate the venv.
#
# Usage:
#   bash scripts/repair-venv.sh [--venv <path>]
#
# Exit codes:
#   0  success (repaired and healthy, or already healthy)
#   1  repair failed (pyvenv.cfg missing/malformed, executable not found, verification failed
#      after repair attempt, etc.)

set -euo pipefail

# -------------------------------------------------------------------------
# Arg parsing
# -------------------------------------------------------------------------
VENV_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv)
      VENV_OVERRIDE="${2:?--venv requires a path}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,28p' "$0"
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# -------------------------------------------------------------------------
# Resolve venv path from script location (not cwd) per codex iter-1 finding #9.
# Script lives at <repo>/scripts/repair-venv.sh; venv at <repo>/venv.
# -------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${VENV_OVERRIDE}" ]]; then
  VENV="${VENV_OVERRIDE}"
else
  VENV="${REPO_ROOT}/venv"
fi

if [[ ! -d "${VENV}" ]]; then
  echo "Error: venv directory not found: ${VENV}" >&2
  exit 1
fi

PYVENV_CFG="${VENV}/pyvenv.cfg"
if [[ ! -f "${PYVENV_CFG}" ]]; then
  echo "Error: pyvenv.cfg not found at ${PYVENV_CFG}" >&2
  exit 1
fi

# -------------------------------------------------------------------------
# Parse executable= from pyvenv.cfg dynamically (no hardcoded interpreter).
# -------------------------------------------------------------------------
EXEC_LINE="$(awk -F'=' '/^[[:space:]]*executable[[:space:]]*=/ {
  sub(/^[[:space:]]+/, "", $2); sub(/[[:space:]]+$/, "", $2); print $2
}' "${PYVENV_CFG}" | head -n1)"

if [[ -z "${EXEC_LINE}" ]]; then
  echo "Error: pyvenv.cfg has no 'executable = <path>' line: ${PYVENV_CFG}" >&2
  exit 1
fi

INTERPRETER="${EXEC_LINE}"
if [[ ! -x "${INTERPRETER}" ]]; then
  echo "Error: pyvenv.cfg executable target is not an executable file: ${INTERPRETER}" >&2
  exit 1
fi

# -------------------------------------------------------------------------
# Health probe (all four checks must pass for idempotence).
# Returns 0 if venv is fully healthy, non-zero otherwise.
# -------------------------------------------------------------------------
health_probe() {
  local symlink
  for symlink in "${VENV}/bin/python" "${VENV}/bin/python3" "${VENV}/bin/python3.12"; do
    if [[ ! -e "${symlink}" ]]; then
      return 1
    fi
    local out
    out="$("${symlink}" -m pytest --version 2>/dev/null)" || return 1
    if ! grep -qE '^pytest[[:space:]]+[0-9]+\.[0-9]+' <<<"${out}"; then
      return 1
    fi
  done
  # Broken-symlink finder: empty output means no broken python* symlinks.
  local broken
  broken="$(find "${VENV}/bin" -maxdepth 1 -name 'python*' -type l -xtype l 2>/dev/null)"
  if [[ -n "${broken}" ]]; then
    return 1
  fi
  # sys.prefix-in-venv check (S2): confirms interpreter genuinely lives in the venv.
  "${VENV}/bin/python" -c 'import sys; assert sys.prefix.endswith("venv"), sys.prefix' >/dev/null 2>&1 || return 1
  return 0
}

# -------------------------------------------------------------------------
# Idempotence: if already healthy, exit 0 without touching anything.
# -------------------------------------------------------------------------
if health_probe; then
  echo "already healthy: ${VENV} (pytest --version OK on all three symlinks; no broken python* symlinks; sys.prefix in venv)"
  exit 0
fi

# -------------------------------------------------------------------------
# Repair: iterate over ALL THREE interpreter names so a venv with any of
# python / python3 / python3.12 missing or broken gets restored, not just
# python3 (codex finding #4 — verification breadth must match repair breadth).
# Each target is symlinked to ${INTERPRETER} when missing, broken, or
# non-executable; healthy entries are left untouched (idempotence).
# -------------------------------------------------------------------------
for name in python python3 python3.12; do
  TARGET="${VENV}/bin/${name}"
  needs_repair=0
  if [[ ! -e "${TARGET}" && ! -L "${TARGET}" ]]; then
    # Nothing at this path (not a file, not a dangling symlink).
    needs_repair=1
  elif [[ -L "${TARGET}" && ! -e "${TARGET}" ]]; then
    # Broken symlink (link present but target missing).
    needs_repair=1
  else
    # Path resolves to something — try to execute. If it fails, treat as needing repair.
    "${TARGET}" --version >/dev/null 2>&1 || needs_repair=1
  fi

  if [[ ${needs_repair} -eq 1 ]]; then
    # Safety guard (close 20260529-081014 codex BLOCKER #2):
    # repair-venv only manages symlinks. If TARGET exists as a real
    # (non-symlink) file or directory, refuse to delete it — silently
    # rm'ing a real Python binary or user file would be data loss outside
    # this script's mandate. Dangling symlinks are NOT caught by this
    # guard because -e returns false for them; they correctly fall through
    # to the rm+ln-s repair path.
    if [[ -e "${TARGET}" && ! -L "${TARGET}" ]]; then
      echo "Error: ${TARGET} exists as a real (non-symlink) file or directory." >&2
      echo "  repair-venv.sh only manages symlinks; refusing to delete a real path." >&2
      echo "  Remove or rename it manually if you intend to replace it with a symlink." >&2
      exit 1
    fi
    echo "Repairing: creating ${TARGET} -> ${INTERPRETER}"
    rm -f "${TARGET}"
    ln -s "${INTERPRETER}" "${TARGET}"
  fi
done

# -------------------------------------------------------------------------
# Re-verify after repair. If still unhealthy, emit clear diagnostic and exit 1.
# -------------------------------------------------------------------------
if ! health_probe; then
  echo "Error: repair completed but venv is still unhealthy." >&2
  echo "Diagnostic:" >&2
  for symlink in "${VENV}/bin/python" "${VENV}/bin/python3" "${VENV}/bin/python3.12"; do
    if [[ -e "${symlink}" ]]; then
      echo "  ${symlink}: $("${symlink}" -m pytest --version 2>&1 || echo '(pytest invocation failed)')" >&2
    else
      echo "  ${symlink}: missing" >&2
    fi
  done
  local_broken="$(find "${VENV}/bin" -maxdepth 1 -name 'python*' -type l -xtype l 2>/dev/null || true)"
  if [[ -n "${local_broken}" ]]; then
    echo "  broken symlinks remaining:" >&2
    echo "${local_broken}" | sed 's/^/    /' >&2
  fi
  exit 1
fi

echo "Repaired: ${VENV} now healthy (pytest --version OK on all three symlinks)"
exit 0
