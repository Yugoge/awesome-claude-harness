"""Structural + behavioural controls for the release pipeline and the published-artifact
verifier.

The blast-radius map reported `no_automated_test` for BOTH `.github/workflows/release.yml`
and `scripts/verify-release-manifest.sh`; this module is their first coverage. Each test
below is falsified by the pre-fix tree with a stated measurement:

  * the release was created PUBLIC and verified afterwards, so a failing verification
    could not un-publish it (`--draft` absent);
  * the attestation step declared no `id:` and none of its outputs was referenced, so
    three assets shipped where the requirement names four;
  * the archive-digest binding read `if meta_hashes and archive_sha not in meta_hashes:`,
    which short-circuits to PASS when the digest is ABSENT;
  * `baseline.yml` declared no `workflow_call`, and a tag push matches neither of its
    triggers, so no job-graph edge to the hygiene gates was expressible at all.

Workflow assertions read PARSED YAML node values (a step's `run:`/`uses:`/`needs:`/
`continue-on-error:`), never a whole-file text grep, so a comment mentioning `--draft`
cannot satisfy any of them.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parent.parent
RELEASE_WF = REPO / ".github" / "workflows" / "release.yml"
BASELINE_WF = REPO / ".github" / "workflows" / "baseline.yml"
VERIFIER = REPO / "scripts" / "verify-release-manifest.sh"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf8"))


def _on_block(doc: dict) -> dict:
    """PyYAML resolves the bare key `on:` to the boolean True (YAML 1.1)."""
    return doc.get("on") if "on" in doc else doc.get(True)


@pytest.fixture(scope="module")
def release_doc() -> dict:
    return _load(RELEASE_WF)


@pytest.fixture(scope="module")
def publish_steps(release_doc) -> list[dict]:
    return release_doc["jobs"]["release"]["steps"]


def _step_index(steps: list[dict], predicate) -> int:
    for i, s in enumerate(steps):
        if predicate(s):
            return i
    return -1


def _run_of(step: dict) -> str:
    return step.get("run") or ""


# ---------------------------------------------------------------------------
# AC-REL-5 — draft, then verify, then promote; plus a REAL dependency edge.
# ---------------------------------------------------------------------------

def test_release_is_created_as_a_draft(publish_steps):
    """Limb a: the release-creating run block carries --draft."""
    idx = _step_index(publish_steps, lambda s: "gh release create" in _run_of(s))
    assert idx >= 0, "no step invokes `gh release create`"
    assert "--draft" in _run_of(publish_steps[idx]), (
        "the release is created publicly; a failing verification cannot un-publish it")


def test_a_later_step_promotes_the_draft(publish_steps):
    """Limb b: promotion exists (anti-vacuity for limb c — never promoting would
    otherwise trivially satisfy 'verify precedes promote')."""
    create = _step_index(publish_steps, lambda s: "gh release create" in _run_of(s))
    promote = _step_index(publish_steps, lambda s: "--draft=false" in _run_of(s))
    assert promote >= 0, "nothing ever promotes the draft to a published release"
    assert promote > create, "promotion must come after creation"


def test_published_asset_verification_precedes_promotion(publish_steps):
    """Limb c: the artifact is verified BEFORE it becomes publicly consumable."""
    verify = _step_index(publish_steps,
                         lambda s: "verify-release-manifest.sh" in _run_of(s))
    promote = _step_index(publish_steps, lambda s: "--draft=false" in _run_of(s))
    assert verify >= 0, "no step verifies the published asset"
    assert promote >= 0, "no promotion step"
    assert verify < promote, "promotion happens before verification"


def test_verification_step_is_not_continue_on_error(publish_steps):
    """Limb d: a verification whose failure is ignored gates nothing."""
    verify = _step_index(publish_steps,
                         lambda s: "verify-release-manifest.sh" in _run_of(s))
    assert publish_steps[verify].get("continue-on-error") is not True, (
        "the published-asset verification is continue-on-error, so a failure would "
        "still be promoted")


def test_baseline_workflow_is_callable():
    """Limb e: without workflow_call the hygiene gates cannot be a dependency of
    anything — a tag push matches neither of baseline's other triggers."""
    on = _on_block(_load(BASELINE_WF))
    assert on is not None and "workflow_call" in on, (
        "baseline.yml declares no workflow_call, so no cross-workflow needs: edge exists")


def test_publishing_job_depends_on_the_hygiene_workflow(release_doc):
    """Limb f: the dependency edge is REAL — a job that `uses:` the baseline workflow,
    and a publishing job that `needs:` it."""
    jobs = release_doc["jobs"]
    callers = [jid for jid, j in jobs.items()
               if str(j.get("uses", "")).endswith(".github/workflows/baseline.yml")]
    assert callers, "no job calls the baseline hygiene workflow"
    needs = jobs["release"].get("needs")
    needs = [needs] if isinstance(needs, str) else list(needs or [])
    assert set(callers) & set(needs), (
        f"the publishing job needs {needs}, none of which runs the hygiene gates")


def test_publishing_job_retains_its_own_write_permissions(release_doc):
    """RISK-7: a called workflow does not inherit the caller's permissions. Moving the
    grant must not strip what the publishing job's own steps require."""
    perms = release_doc["jobs"]["release"].get("permissions") or {}
    for scope in ("contents", "id-token", "attestations"):
        assert perms.get(scope) == "write", (
            f"the publishing job lost `{scope}: write`, which its own steps require")


# ---------------------------------------------------------------------------
# AC-REL-6 — the attestation ships as a fourth asset.
# ---------------------------------------------------------------------------

def _attest_step(steps: list[dict]) -> dict:
    for s in steps:
        if str(s.get("uses", "")).startswith("actions/attest-build-provenance@"):
            return s
    pytest.fail("no attest-build-provenance step found")


def test_attest_step_declares_an_id(publish_steps):
    """Limb a: without an `id:` the bundle is unaddressable and cannot be shipped."""
    assert (_attest_step(publish_steps).get("id") or "").strip(), (
        "the attestation step declares no id, so its outputs cannot be referenced")


def _asset_operands(steps: list[dict]) -> list[str]:
    """Variable names passed as ASSET operands to `gh release create`.

    Read from the parsed step's `run:` node, and only from the segment AFTER the
    flags-array expansion, so option values are never miscounted as assets."""
    run = _run_of(steps[_step_index(steps, lambda s: "gh release create" in _run_of(s))])
    cmd = re.search(r"gh release create(.*?)(?:\n\s*\n|\Z)", run, re.S).group(1)
    cmd = cmd.replace("\\\n", " ")
    tail = cmd.split('"${flags[@]}"', 1)
    assert len(tail) == 2, "could not locate the flags-array expansion in the create command"
    return re.findall(r'"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?"', tail[1])


def test_four_assets_are_published(publish_steps):
    """Limb b: archive, checksum, SBOM, attestation."""
    operands = _asset_operands(publish_steps)
    assert len(operands) == 4, (
        f"expected 4 release assets, found {len(operands)}: {operands}")


def test_one_asset_resolves_from_the_attest_step_outputs(publish_steps):
    """Limb c: one operand traces to the attest step's outputs.

    The output NAME is deliberately not pinned — it cannot be confirmed offline for
    this pinned action version (OA-1), so pinning a literal would create a criterion
    that could be correct-but-failing."""
    attest_id = _attest_step(publish_steps)["id"]
    operands = set(_asset_operands(publish_steps))
    marker = f"steps.{attest_id}.outputs."
    for step in publish_steps:
        blob = json.dumps(step.get("env") or {}) + _run_of(step)
        if marker not in blob:
            continue
        exported = set(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=.*>>\s*"?\$GITHUB_ENV', _run_of(step)))
        if exported & operands:
            return
    pytest.fail(f"no published asset resolves from {marker}; operands were {sorted(operands)}")


# ---------------------------------------------------------------------------
# AC-REL-7 — the digest binding is mandatory and the SBOM is schema-checked.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def local_release(tmp_path_factory) -> dict:
    """Build an archive + a well-formed SBOM locally, then verify OFFLINE.

    local-archive mode sets SKIP_ATTESTATION, so no network client is needed."""
    base = tmp_path_factory.mktemp("rel")
    stage = base / "stage" / "claude-harness-test"
    stage.mkdir(parents=True)
    members = subprocess.run(
        ["python3", "scripts/lib/release_membership.py", "--from-git", "--root", ".",
         "--manifest", "release-membership.v1.json"],
        cwd=REPO, capture_output=True, text=True).stdout.split()
    assert members, "release-membership resolved an empty path set"
    for rel in members:
        src = REPO / rel
        if not src.is_file():
            continue
        (stage / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, stage / rel)

    archive = base / "claude-harness-test.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(stage, arcname=stage.name)
    sha = subprocess.run(["sha256sum", str(archive)],
                         capture_output=True, text=True).stdout.split()[0]
    checksum = base / "claude-harness-test.tar.gz.sha256"
    checksum.write_text(f"{sha}  {archive.name}\n", encoding="utf8")

    sbom = base / "sbom.json"
    r = subprocess.run(
        ["python3", "scripts/lib/make_sbom.py", "--root", str(stage), "--out", str(sbom),
         "--name", "claude-harness", "--version", "test", "--archive-sha256", sha],
        cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return {"base": base, "archive": archive, "checksum": checksum, "sbom": sbom}


def _verify(local_release: dict, sbom_path: Path, tag: str) -> subprocess.CompletedProcess:
    # An explicit --workdir keeps the harness off the shared temp filesystem, whose
    # exhaustion is a known source of spurious failures in this workspace.
    workdir = local_release["base"] / f"verify-{tag}"
    workdir.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["bash", str(VERIFIER), "--local-archive", str(local_release["archive"]),
         "--sbom", str(sbom_path), "--checksum", str(local_release["checksum"]),
         "--workdir", str(workdir)],
        cwd=REPO, capture_output=True, text=True)


def _mutate(local_release: dict, name: str, fn) -> Path:
    doc = json.loads(local_release["sbom"].read_text(encoding="utf8"))
    fn(doc)
    out = local_release["base"] / f"sbom-{name}.json"
    out.write_text(json.dumps(doc, indent=2), encoding="utf8")
    return out


def test_wellformed_sbom_verifies(local_release):
    """Limb a (anti-vacuity): without a passing positive case, every other limb here
    could be satisfied by making the verifier fail unconditionally."""
    r = _verify(local_release, local_release["sbom"], "clean")
    assert r.returncode == 0, r.stdout + r.stderr


def test_removed_archive_digest_fails(local_release):
    """Limb b: THE defect. Absence used to short-circuit the conjunction to PASS."""
    def drop(doc):
        doc["metadata"]["component"].pop("hashes", None)
    r = _verify(local_release, _mutate(local_release, "nodigest", drop), "nodigest")
    assert r.returncode != 0, "a digest-free SBOM verified clean"
    assert "archive-digest binding is mandatory" in r.stdout


def test_altered_archive_digest_fails(local_release):
    """Limb b corollary: mismatch must still fail (the old behaviour is preserved)."""
    def tamper(doc):
        doc["metadata"]["component"]["hashes"] = [{"alg": "SHA-256", "content": "0" * 64}]
    r = _verify(local_release, _mutate(local_release, "baddigest", tamper), "baddigest")
    assert r.returncode != 0
    assert "does not match the downloaded archive digest" in r.stdout


def test_removed_library_component_fails(local_release):
    """Limb c: only `file` components were ever compared against anything, so a
    dropped dependency was invisible."""
    def drop(doc):
        libs = [c for c in doc["components"] if c.get("type") == "library"]
        assert libs, "fixture has no library components to remove"
        doc["components"].remove(libs[0])
    r = _verify(local_release, _mutate(local_release, "nolib", drop), "nolib")
    assert r.returncode != 0, "a removed library component went undetected"
    assert "omits" in r.stdout and "librar" in r.stdout


def test_altered_library_version_fails(local_release):
    """Limb d: a version the archive's lockfiles do not pin must not verify."""
    def bump(doc):
        libs = [c for c in doc["components"] if c.get("type") == "library"]
        assert libs, "fixture has no library components to alter"
        libs[0]["version"] = "0.0.0-not-pinned"
    r = _verify(local_release, _mutate(local_release, "badver", bump), "badver")
    assert r.returncode != 0, "an altered library version went undetected"
    assert "lockfiles do not pin" in r.stdout


def test_unsupported_spec_version_fails(local_release):
    """Limb e: the declared specVersion is matched against an explicit supported set,
    not merely asserted non-empty."""
    def bogus(doc):
        doc["specVersion"] = "9.9"
    r = _verify(local_release, _mutate(local_release, "badspec", bogus), "badspec")
    assert r.returncode != 0, "an SBOM declaring an unsupported specVersion verified"
    assert "unsupported CycloneDX specVersion" in r.stdout


def test_document_is_validated_against_the_declared_spec_version(local_release):
    """Limb e, second half: the document must satisfy the STRUCTURE its declared
    version requires — a supported version label over a malformed body must fail."""
    def wreck(doc):
        doc["version"] = "not-an-integer"
        doc["components"][0]["type"] = "not-a-cyclonedx-type"
    r = _verify(local_release, _mutate(local_release, "badschema", wreck), "badschema")
    assert r.returncode != 0, "a structurally invalid CycloneDX document verified"
    assert "does not satisfy the CycloneDX" in r.stdout
