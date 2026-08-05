#!/usr/bin/env bash
# Description: Verify a PUBLISHED release artifact end-to-end, WITHOUT rebuilding it.
#   Downloads the archive, checksum, SBOM and attestation that a release actually
#   published, then proves: the archive bytes match the published checksum; the
#   attestation is bound to that same digest; the SBOM genuinely describes those
#   bytes; and the extracted contents equal the release-membership manifest with no
#   author-path or workspace-path residue. Rebuilding from source would verify the
#   wrong artifact — "it builds clean here" says nothing about what consumers get.
# Usage: bash scripts/verify-release-manifest.sh --tag <tag> [--repo <owner/name>]
#        bash scripts/verify-release-manifest.sh --local-archive <file> --sbom <f> --checksum <f>
# Exit codes: 0 = published artifact verified, 1 = verification failed, 2 = usage error.
#
# Style mirrors scripts/check-public-core.sh: `set -uo pipefail` (never -e), an
# explicit fail()/pass() accumulator so ALL problems surface in one run, and every
# value recomputed from the downloaded bytes rather than trusted.

set -uo pipefail

TAG=""
REPO=""
LOCAL_ARCHIVE=""
LOCAL_SBOM=""
LOCAL_CHECKSUM=""
WORKDIR=""
SKIP_ATTESTATION=0

while [ $# -gt 0 ]; do
  case "$1" in
    --tag)            TAG="${2:?--tag needs a value}"; shift 2 ;;
    --repo)           REPO="${2:?--repo needs a value}"; shift 2 ;;
    --local-archive)  LOCAL_ARCHIVE="${2:?--local-archive needs a file}"; shift 2 ;;
    --sbom)           LOCAL_SBOM="${2:?--sbom needs a file}"; shift 2 ;;
    --checksum)       LOCAL_CHECKSUM="${2:?--checksum needs a file}"; shift 2 ;;
    --workdir)        WORKDIR="${2:?--workdir needs a directory}"; shift 2 ;;
    --skip-attestation) SKIP_ATTESTATION=1; shift ;;
    -h|--help)        sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "verify-release-manifest: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

if [ -z "$TAG" ] && [ -z "$LOCAL_ARCHIVE" ]; then
  echo "verify-release-manifest: need --tag <tag> (published) or --local-archive <file>" >&2
  exit 2
fi

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
rc=0
fail() { echo "FAIL: $*"; rc=1; }
pass() { echo "PASS: $*"; }

[ -n "$WORKDIR" ] || WORKDIR="$(mktemp -d)"
mkdir -p "$WORKDIR"
DL="$WORKDIR/download"
EX="$WORKDIR/extract"
mkdir -p "$DL" "$EX"

# ---------------------------------------------------------------------------
# 1. Obtain the PUBLISHED assets. Downloaded, never rebuilt.
# ---------------------------------------------------------------------------
if [ -n "$TAG" ]; then
  command -v gh >/dev/null 2>&1 || { echo "FAIL: gh CLI is required to download the published release" >&2; exit 1; }
  GH_ARGS=(release download "$TAG" --dir "$DL")
  [ -n "$REPO" ] && GH_ARGS+=(--repo "$REPO")
  if ! gh "${GH_ARGS[@]}"; then
    echo "FAIL: could not download published assets for tag $TAG" >&2
    exit 1
  fi
  ARCHIVE="$(find "$DL" -maxdepth 1 -name '*.tar.gz' | head -1)"
  CHECKSUM="$(find "$DL" -maxdepth 1 -name '*.sha256' | head -1)"
  SBOM="$(find "$DL" -maxdepth 1 -name '*sbom*.json' | head -1)"
else
  ARCHIVE="$LOCAL_ARCHIVE"
  CHECKSUM="$LOCAL_CHECKSUM"
  SBOM="$LOCAL_SBOM"
  SKIP_ATTESTATION=1
fi

[ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ] || { echo "FAIL: no release archive found" >&2; exit 1; }
[ -n "$CHECKSUM" ] && [ -f "$CHECKSUM" ] || { echo "FAIL: no published checksum found" >&2; exit 1; }
[ -n "$SBOM" ] && [ -f "$SBOM" ] || { echo "FAIL: no published SBOM found" >&2; exit 1; }
echo "verifying PUBLISHED archive: $ARCHIVE"

# ---------------------------------------------------------------------------
# 2. Digest of the FINAL archive bytes must equal the published checksum.
# ---------------------------------------------------------------------------
ACTUAL_SHA="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
PUBLISHED_SHA="$(awk '{print $1}' "$CHECKSUM" | head -1)"
if [ "$ACTUAL_SHA" = "$PUBLISHED_SHA" ]; then
  pass "archive sha256 matches the published checksum ($ACTUAL_SHA)"
else
  fail "archive sha256 MISMATCH — downloaded $ACTUAL_SHA, published $PUBLISHED_SHA"
fi

# ---------------------------------------------------------------------------
# 3. Attestation must be bound to THAT digest (not merely present).
# ---------------------------------------------------------------------------
if [ "$SKIP_ATTESTATION" -eq 1 ]; then
  echo "INFO: attestation verification skipped (local-archive mode)"
elif command -v gh >/dev/null 2>&1; then
  ATT_ARGS=(attestation verify "$ARCHIVE")
  if [ -n "$REPO" ]; then ATT_ARGS+=(--repo "$REPO"); else ATT_ARGS+=(--owner "${GITHUB_REPOSITORY_OWNER:-}"); fi
  if gh "${ATT_ARGS[@]}"; then
    pass "build provenance attestation verifies against the downloaded archive bytes"
  else
    fail "attestation verification FAILED for the published archive"
  fi
else
  fail "gh CLI unavailable — cannot verify the attestation"
fi

# ---------------------------------------------------------------------------
# 4. Extract. From here on, every check runs against the EXTRACTED bytes.
# ---------------------------------------------------------------------------
if ! tar -xzf "$ARCHIVE" -C "$EX"; then
  fail "could not extract the published archive"
  echo "----------------------------------------------------------------------"
  echo "verify-release-manifest: FAILURES DETECTED"
  exit 1
fi
ROOTDIR="$EX"
if [ "$(find "$EX" -mindepth 1 -maxdepth 1 -type d | wc -l)" -eq 1 ] && \
   [ "$(find "$EX" -mindepth 1 -maxdepth 1 | wc -l)" -eq 1 ]; then
  ROOTDIR="$(find "$EX" -mindepth 1 -maxdepth 1 -type d)"
fi

MANIFEST="$ROOTDIR/release-membership.v1.json"
if [ ! -f "$MANIFEST" ]; then
  fail "release-membership manifest is missing from the archive ($MANIFEST)"
else
  pass "release-membership manifest travels inside the archive"
fi

# ---------------------------------------------------------------------------
# 5. SBOM must genuinely describe the archive, not merely parse.
# ---------------------------------------------------------------------------
python3 - "$SBOM" "$ROOTDIR" "$ACTUAL_SHA" <<'PY'
import hashlib, json, os, re, sys
sbom_path, root, archive_sha = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    bom = json.load(open(sbom_path, encoding="utf8"))
except Exception as exc:
    print(f"FAIL: SBOM is not valid JSON: {exc}"); sys.exit(1)
problems = 0

# --- CycloneDX validation AGAINST THE DECLARED specVersion -------------------
# Presence of a specVersion field says nothing: it was previously enough for the
# field to be non-empty, so a document declaring any version at all, in any shape,
# passed. The version is now matched against an explicitly declared supported set
# and the document is validated against the structure that version requires.
SUPPORTED_SPEC_VERSIONS = ("1.4", "1.5", "1.6")
CDX_COMPONENT_TYPES = {"application", "framework", "library", "container", "operating-system",
                       "device", "firmware", "file", "platform", "device-driver",
                       "machine-learning-model", "data"}
CDX_HASH_ALGS = {"MD5", "SHA-1", "SHA-256", "SHA-384", "SHA-512",
                 "SHA3-256", "SHA3-384", "SHA3-512", "BLAKE2b-256", "BLAKE2b-384",
                 "BLAKE2b-512", "BLAKE3"}
spec_version = bom.get("specVersion")
if bom.get("bomFormat") != "CycloneDX":
    print(f"FAIL: SBOM bomFormat is {bom.get('bomFormat')!r}, not 'CycloneDX'"); problems += 1
if spec_version not in SUPPORTED_SPEC_VERSIONS:
    print(f"FAIL: SBOM declares unsupported CycloneDX specVersion {spec_version!r} "
          f"(supported: {', '.join(SUPPORTED_SPEC_VERSIONS)})"); problems += 1
else:
    schema_problems = []
    ver = bom.get("version")
    if not isinstance(ver, int) or isinstance(ver, bool) or ver < 1:
        schema_problems.append(f"top-level 'version' must be an integer >= 1, got {ver!r}")
    if not isinstance(bom.get("components"), list):
        schema_problems.append("'components' must be an array")
    meta_component = (bom.get("metadata") or {}).get("component")
    if not isinstance(meta_component, dict):
        schema_problems.append("'metadata.component' is required and must be an object")
    elif meta_component.get("type") not in CDX_COMPONENT_TYPES:
        schema_problems.append(f"metadata.component.type {meta_component.get('type')!r} is not a "
                               f"CycloneDX {spec_version} component type")
    for i, c in enumerate(bom.get("components") or []):
        if not isinstance(c, dict):
            schema_problems.append(f"components[{i}] is not an object"); continue
        if c.get("type") not in CDX_COMPONENT_TYPES:
            schema_problems.append(f"components[{i}].type {c.get('type')!r} is not a "
                                   f"CycloneDX {spec_version} component type")
        if not c.get("name"):
            schema_problems.append(f"components[{i}] has no 'name'")
        for h in c.get("hashes") or []:
            if not isinstance(h, dict) or h.get("alg") not in CDX_HASH_ALGS:
                schema_problems.append(f"components[{i}] declares hash alg "
                                       f"{(h or {}).get('alg')!r}, not a CycloneDX algorithm")
    if schema_problems:
        print(f"FAIL: SBOM does not satisfy the CycloneDX {spec_version} schema it declares "
              f"({len(schema_problems)} problem(s)):")
        for p in schema_problems[:8]:
            print(f"    {p}")
        problems += 1
components = bom.get("components") or []
if not components:
    print("FAIL: SBOM has zero components (an empty SBOM describes nothing)"); problems += 1
declared = {c["name"]: c for c in components if c.get("type") == "file"}
actual = set()
for dirpath, dirnames, files in os.walk(root):
    dirnames[:] = [d for d in dirnames if d != ".git"]
    for f in files:
        actual.add(os.path.relpath(os.path.join(dirpath, f), root))
missing = actual - set(declared)
extra = set(declared) - actual
if missing:
    print(f"FAIL: SBOM omits {len(missing)} archive file(s), e.g. {sorted(missing)[:5]}"); problems += 1
if extra:
    print(f"FAIL: SBOM lists {len(extra)} file(s) not in the archive, e.g. {sorted(extra)[:5]}"); problems += 1
bad = 0
for name, comp in declared.items():
    if name not in actual:
        continue
    want = next((h["content"] for h in comp.get("hashes", []) if h.get("alg") == "SHA-256"), None)
    if not want:
        bad += 1; continue
    h = hashlib.sha256()
    with open(os.path.join(root, name), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != want:
        bad += 1
if bad:
    print(f"FAIL: {bad} SBOM file component(s) have a missing or mismatched sha256"); problems += 1
meta_hashes = [h.get("content") for h in (bom.get("metadata", {}).get("component", {}).get("hashes") or [])]
if meta_hashes and archive_sha not in meta_hashes:
    print("FAIL: SBOM metadata digest does not match the downloaded archive digest"); problems += 1
if not problems:
    print(f"  SBOM describes {len(declared)} archive file(s) + "
          f"{sum(1 for c in components if c.get('type') == 'library')} pinned librar(ies), all digests match")
sys.exit(1 if problems else 0)
PY
if [ $? -eq 0 ]; then
  pass "SBOM is well-formed AND its inventory matches the downloaded archive's contents"
else
  fail "SBOM does not faithfully describe the downloaded archive (see above)"
fi

# ---------------------------------------------------------------------------
# 6. Boundary rules over the EXTRACTED archive: path set == membership manifest,
#    and zero residue. Same engine CI uses, pointed at the published bytes.
# ---------------------------------------------------------------------------
if [ -f "$ROOTDIR/scripts/check-public-core.sh" ] && [ -f "$MANIFEST" ]; then
  if bash "$SELF_DIR/check-public-core.sh" --scan-root "$ROOTDIR" --release-manifest "$MANIFEST"; then
    pass "published archive: path set equals the membership manifest and carries no residue"
  else
    fail "published archive failed the boundary/residue gate (see above)"
  fi
else
  fail "cannot run the boundary gate against the archive (checker or manifest missing)"
fi

# ---------------------------------------------------------------------------
# 7. VERSION inside the archive must agree with the tag it was published under.
# ---------------------------------------------------------------------------
if [ -n "$TAG" ] && [ -f "$ROOTDIR/VERSION" ]; then
  ARCHIVE_VERSION="$(tr -d '[:space:]' < "$ROOTDIR/VERSION")"
  if [ "${TAG#v}" = "$ARCHIVE_VERSION" ]; then
    pass "archive VERSION ($ARCHIVE_VERSION) matches the published tag ($TAG)"
  else
    fail "archive VERSION ($ARCHIVE_VERSION) does not match the published tag ($TAG)"
  fi
fi

echo "----------------------------------------------------------------------"
if [ "$rc" -eq 0 ]; then
  echo "verify-release-manifest: PUBLISHED ARTIFACT VERIFIED (digest, attestation, SBOM, boundary rules)"
else
  echo "verify-release-manifest: FAILURES DETECTED — see FAIL lines above"
fi
exit "$rc"
