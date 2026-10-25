#!/usr/bin/env bash
# Description: Self-verifying headline-claims gate. Runs ALL THREE hero-provenance audits in
#   --strict mode so any source-verification downgrade is a hard failure, the hero status and
#   capture-provenance checks, the adversarial-corpus check, and the enforcement-evidence gates
#   (docs/ENFORCEMENT-LEDGER.md against the tracked settings.json and the guard sources).
# Usage: bash scripts/verify-claims.sh
# Exit codes: 0 = all checks pass, 1 = one or more checks failed. Runs identically in CI and
#   locally.
# Root cause (git): the provenance audit was never run in CI and exited 0 even when source
#   verification was downgraded to warnings.
#
# Steps 1, 2 and 4 (the wired-entry, lifecycle-event and helper-script counts in README.md and
# ARCHITECTURE.md) are retired: the docs no longer carry hand-maintained counts, so there is
# nothing to recompute against. settings.json is read as staged in the index, its tracked form:
# the claude-settings filter leaves an initialised home's working file in the machine form,
# which enabled modules (paseo) extend with their own hooks.

set -uo pipefail   # deliberately NOT -e: an explicit accumulator runs every check so ALL drift
                   # is reported at once instead of aborting on the first failure.

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || { echo "ERROR: cannot cd to repo root" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required" >&2; exit 1; }
command -v node    >/dev/null 2>&1 || { echo "ERROR: node (>=18) is required for audit.mjs" >&2; exit 1; }

rc=0
fail() { echo "FAIL: $*"; rc=1; }
pass() { echo "PASS: $*"; }

# ---------------------------------------------------------------------------
# 3. Run ALL THREE hero-provenance audits in --strict mode (any downgrade hard-fails).
# ---------------------------------------------------------------------------
run_audit() {
  local manifest="$1" svg="$2"
  if [ ! -f "$manifest" ] || [ ! -f "$svg" ]; then
    fail "audit(strict): missing asset — ${manifest} or ${svg} not found"; return
  fi
  if node tools/demo/audit.mjs "$manifest" "$svg" --strict; then
    pass "audit(strict): ${manifest} <-> ${svg}"
  else
    fail "audit(strict): ${manifest} <-> ${svg}"
  fi
}
run_audit .github/assets/demo-trace.json .github/assets/pipeline-hero.svg
run_audit .github/assets/hook-trace.json .github/assets/hook-hero.svg
run_audit .github/assets/guard-hero.json .github/assets/guard-hero.svg

# ---------------------------------------------------------------------------
# 3b. Hero status-region ratchet + hero capture provenance.
#     These two gates protect the README's published claim rows and the hero capture chain.
#     Landed HERE because this file is the aggregate gate and the lane that authored those
#     gates may not edit it — an enforcement mechanism nobody invokes is advisory, whatever
#     its own tests say. Neither call is suffixed `|| true` and neither is redirected away
#     from the accumulator: a failure in either is a failure of this script.
#
#     verify-hero-provenance.py is deliberately invoked WITHOUT --skip-rerun, so the committed
#     manifest and SVG are re-derived from the committed capture on every run. That rerun
#     regenerates into a temporary directory and writes nothing into .github/assets/ (verified
#     this cycle by reading check_rerun); the README-mutating tamper table is reached only
#     under --tamper, which is not passed here.
# ---------------------------------------------------------------------------
if python3 scripts/generate-hero-status.py --check; then
  pass "hero-status: README claim rows match the generator's derivation (--check)"
else
  fail "hero-status: scripts/generate-hero-status.py --check reports the README status region has drifted"
fi

if python3 scripts/verify-hero-provenance.py; then
  pass "hero-provenance: capture -> manifest -> SVG chain re-derives (rerun included)"
else
  fail "hero-provenance: scripts/verify-hero-provenance.py reports a provenance violation"
fi

# ---------------------------------------------------------------------------
# 3c. The adversarial corpus is load-bearing, so its absence must be loud.
#     docs/ENFORCEMENT-LEDGER.md cites it as the machine-readable source of truth for the
#     payloads, and --ledger reads it to decide whether an `enforced` row has a linked corpus
#     case — but --ledger treats an unreadable corpus as simply "no linked cases", so deleting
#     the file used to leave this aggregate gate green. Missing and unparseable are reported as
#     DISTINCT diagnostics: they are different failures with different repairs.
#
#     Exercisable in isolation: set VERIFY_CLAIMS_CORPUS to a fixture path and read the
#     `corpus-validation:` line, which is attributable independently of the aggregate verdict.
# ---------------------------------------------------------------------------
CORPUS_PATH="${VERIFY_CLAIMS_CORPUS:-$ROOT/hooks/tests/fixtures/adversarial_corpus.json}"
corpus_diag="$(python3 - "$CORPUS_PATH" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.exists():
    print(f"MISSING: {path} does not exist"); sys.exit(1)
try:
    data = json.loads(path.read_text(encoding="utf8"))
except Exception as e:
    print(f"UNPARSEABLE: {path} is not valid JSON ({e})"); sys.exit(1)
if not isinstance(data, list) or not data:
    print(f"UNPARSEABLE: {path} parsed but is not a non-empty list of cases"); sys.exit(1)
print(f"OK: {len(data)} corpus case(s) parsed from {path}")
PY
)"
if [ $? -ne 0 ]; then
  fail "corpus-validation: ${corpus_diag}"
else
  pass "corpus-validation: ${corpus_diag}"
fi

# ---------------------------------------------------------------------------
# 6. Enforcement-evidence gates (docs/ENFORCEMENT-LEDGER.md <-> settings.json <-> the code).
#    (Step 5 retired: settings.json is the sole settings file, so no hook-set sync; number kept free.)
#    ADDITIVE: this step only ever appends to the existing accumulator, so it cannot change the
#    pass/fail semantics of the checks above for unrelated PRs. Outside a repository or with no
#    settings.json staged, git prints why and --claims fails.
#
#    DELEGATION, NOT DUPLICATION. Every closed set (behavior / exercise_status / proof_layer),
#    every recorded token set, and the gate-architecture census live in exactly ONE place --
#    DECLARED_SCHEMA and the RECORDED_* constants in scripts/check-enforcement-evidence.py.
#    This script restates none of them; it invokes that script. A prior revision of the spec
#    stated the behavior closed set five different ways across four documents, which would have
#    produced two guards encoding two different sets -- the identical two-hand-synced-copies
#    drift class that RISK-2 of docs/THREAT-MODEL.md exists to teach. Adding a second
#    enumerator here would have recreated it inside the mechanism meant to prevent it.
#
#      --ledger : evidence integrity  (enforced requires host-observed proof + a linked corpus
#                 case; closed-set labels; no passing compatibility row without a run link)
#      --claims : claim-versus-code   (both regex symbols present; arch-F7 block intact; every
#                 declared matrix witness reproduces its recorded outcome; wrapper/redirection
#                 token sets and gate-architecture census unchanged; ledger row set equals the
#                 index settings.json-derived set; every threat-model section-4 citation pinned)
# ---------------------------------------------------------------------------
EVIDENCE_GATE="$ROOT/scripts/check-enforcement-evidence.py"
if [ ! -f "$EVIDENCE_GATE" ]; then
  fail "enforcement-evidence: scripts/check-enforcement-evidence.py not found"
else
  for mode in ledger claims; do
    if python3 "$EVIDENCE_GATE" "--${mode}" --settings <(git cat-file blob :settings.json); then
      pass "enforcement-evidence --${mode}"
    else
      fail "enforcement-evidence --${mode}: see the FAIL lines above"
    fi
  done
fi

# ---------------------------------------------------------------------------
# Aggregated verdict.
# ---------------------------------------------------------------------------
echo "----------------------------------------------------------------------"
if [ "$rc" -eq 0 ]; then
  echo "verify-claims: ALL CHECKS PASSED"
else
  echo "verify-claims: FAILURES DETECTED — see FAIL lines above"
fi
exit "$rc"
