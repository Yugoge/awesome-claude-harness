from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))
from lib import contract_runtime, negative_evidence as ne, schema_registry  # noqa: E402


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        list(args), cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result.stdout.strip()


def _write_json(path: Path, value: dict, mode: int = 0o644) -> str:
    raw = ne.canonical_json_bytes(value, newline=True)
    path.write_bytes(raw)
    path.chmod(mode)
    return hashlib.sha256(raw).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nonfinite_value(token: str) -> float:
    return {
        "NaN": float("nan"),
        "Infinity": float("inf"),
        "-Infinity": float("-inf"),
    }[token]


def _write_nonfinite_json(
    path: Path, value: object, token: str, *, mode: int = 0o444
) -> str:
    raw = (
        json.dumps(
            value,
            allow_nan=True,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    assert token.encode("ascii") in raw
    if path.exists():
        path.chmod(0o644)
    path.write_bytes(raw)
    path.chmod(mode)
    return hashlib.sha256(raw).hexdigest()


def _cli_environment_that_records_find(tmp_path: Path) -> tuple[dict[str, str], Path]:
    marker = tmp_path / "find-was-invoked"
    bindir = tmp_path / "record-find-bin"
    bindir.mkdir()
    find = bindir / "find"
    find.write_text('#!/bin/sh\n: > "$FIND_MARKER"\nexit 97\n')
    find.chmod(0o755)
    env = {
        **os.environ,
        "FIND_MARKER": str(marker),
        "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
    }
    return env, marker


def _scan_cli(
    authority: "AuthorityFixture",
    tmp_path: Path,
    *,
    expected_context_sha256: str,
    expected_authority_sha256: str,
) -> tuple[subprocess.CompletedProcess[str], dict, Path]:
    env, marker = _cli_environment_that_records_find(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/negative-evidence.py"),
            "scan",
            "--contract-context",
            str(authority.context),
            "--expected-context-sha256",
            expected_context_sha256,
            "--authority-file",
            str(authority.admission),
            "--expected-authority-sha256",
            expected_authority_sha256,
            "--expected-authority-projection-sha256",
            authority.projection_sha,
            "--scan-root",
            str(authority.root),
            "--scope",
            "scope",
            "--target-kind",
            "exact-path",
            "--target",
            "scope/missing.txt",
            "--positive-control",
            "scope/control.txt",
            "--timeout-ms",
            "3000",
            "--max-output-bytes",
            "100000",
            "--max-files",
            "1000",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result, json.loads(result.stdout), marker


@dataclass
class AuthorityFixture:
    root: Path
    other: Path
    context: Path
    context_sha: str
    admission: Path
    admission_sha: str
    projection_sha: str

    def scan(self, **overrides):
        values = {
            "contract_context": str(self.context),
            "expected_context_sha256": self.context_sha,
            "authority_file": str(self.admission),
            "expected_authority_sha256": self.admission_sha,
            "expected_authority_projection_sha256": self.projection_sha,
            "scan_root": str(self.root),
            "scopes": ["scope"],
            "prunes": [],
            "target_kind": "exact-path",
            "target": "scope/missing.txt",
            "positive_control": "scope/control.txt",
            "timeout_ms": 3000,
            "max_output_bytes": 1_000_000,
            "max_files": 10_000,
        }
        values.update(overrides)
        return ne.scan_evidence(**values)

    def save(self, receipt: dict, destination: Path) -> str:
        ne.publish_receipt(str(destination), receipt)
        return _sha(destination)

    def verify(self, receipt_path: Path, receipt_sha: str, **overrides):
        values = {
            "receipt_path": str(receipt_path),
            "expected_receipt_sha256": receipt_sha,
            "contract_context": str(self.context),
            "expected_context_sha256": self.context_sha,
            "authority_file": str(self.admission),
            "expected_authority_sha256": self.admission_sha,
            "expected_authority_projection_sha256": self.projection_sha,
            "scan_root": str(self.root),
            "target_kind": "exact-path",
            "target": "scope/missing.txt",
            "expected_conclusion": "absent",
        }
        values.update(overrides)
        return ne.verify_receipt(**values)


def make_authority(
    tmp_path: Path,
    *,
    expected_repo_overrides: dict | None = None,
) -> AuthorityFixture:
    root = tmp_path / "authority"
    other = tmp_path / "other-worktree"
    root.mkdir(parents=True)
    _run("git", "init", "-b", "main", cwd=root)
    _run("git", "config", "user.email", "tests@example.invalid", cwd=root)
    _run("git", "config", "user.name", "L Guards Tests", cwd=root)
    _run(
        "git",
        "remote",
        "add",
        "origin",
        "https://example.invalid/lguards.git",
        cwd=root,
    )
    (root / "scope").mkdir()
    (root / "scope/control.txt").write_text("control\n")
    (root / "ticket.md").write_text("ticket\n")
    (root / "spec.md").write_text("spec\n")
    _write_json(root / "cycle.json", {"cycle": 1})
    _write_json(root / "ledger.json", {"owners": []})
    _run("git", "add", ".", cwd=root)
    _run("git", "commit", "-m", "fixture", cwd=root)
    head = _run("git", "rev-parse", "HEAD", cwd=root)
    _run("git", "worktree", "add", "-b", "other", str(other), head, cwd=root)

    common = str((root / ".git").resolve())
    repo_identity = {
        "git_common_dir_realpath": common,
        "object_format": "sha1",
        "remote_origin_url": "https://example.invalid/lguards.git",
    }
    if expected_repo_overrides:
        repo_identity.update(expected_repo_overrides)
    projection = {
        "schema": "lane-l-guards-root-authority.v1",
        "task_id": "test-l-guards",
        "spec_id": "spec-test",
        "session_id": "session-test",
        "cycle_id": 1,
        "registered_worktree": {
            "declared_absolute": str(root),
            "realpath": str(root.resolve()),
        },
        "repository": {
            "base_head": head,
            "identity": repo_identity,
            "identity_canonical_sha256": hashlib.sha256(
                ne.canonical_json_bytes(repo_identity)
            ).hexdigest(),
        },
        "spec": {"path": "spec.md", "sha256": _sha(root / "spec.md")},
        "cycle": {
            "contract_path": "cycle.json",
            "contract_sha256": _sha(root / "cycle.json"),
            "ownership_ledger_path": "ledger.json",
            "ownership_ledger_sha256": _sha(root / "ledger.json"),
        },
        "contract_context_path": "context.json",
        "admission_source": {
            "owner": "same_spec_parent",
            "path": "admission.json",
            "publication": "O_CREAT|O_EXCL|O_NOFOLLOW; mode 0444; fsync",
            "required_pre_state": "absent",
        },
    }
    projection_sha = hashlib.sha256(ne.canonical_json_bytes(projection)).hexdigest()
    context = {
        "$schema": "context.v1",
        "identity": {"task_id": "test-l-guards"},
        "ticket_binding": {
            "path": "ticket.md",
            "sha256": _sha(root / "ticket.md"),
        },
        "root_authority_contract": {
            "authority_projection": projection,
            "authority_projection_canonical_sha256": projection_sha,
        },
    }
    semantic_keys = ["identity", "ticket_binding", "root_authority_contract"]
    context["contract_projection"] = {
        "keys": semantic_keys,
        "canonical_compact_sha256": hashlib.sha256(
            ne.canonical_json_bytes({key: context[key] for key in semantic_keys})
        ).hexdigest(),
    }
    context_path = root / "context.json"
    context_sha = _write_json(context_path, context, 0o444)
    admission = {
        "schema_name": "lane-l-guards-dev-admission.v1",
        "schema_version": 1,
        "record_status": "PASS_ONE_FRESH_DEV_ACTOR_EXACT_12_IMPLEMENTATION_PATHS",
        "verdict": "PASS",
        "authorization": {"Dev_dispatch_allowed": True},
        "root_authority": {
            "authority_projection": projection,
            "authority_projection_canonical_sha256": projection_sha,
            "external_dispatch_inputs": {
                "contract_context_absolute": str(context_path),
                "expected_context_sha256": context_sha,
                "authority_file_absolute": str(root / "admission.json"),
                "expected_authority_projection_sha256": projection_sha,
            },
        },
        "authority_chain": {
            "base_HEAD": head,
            "context": {"path": "context.json", "sha256": context_sha},
            "context_semantic_projection_sha256": context["contract_projection"][
                "canonical_compact_sha256"
            ],
            "ticket": {
                "path": "ticket.md",
                "sha256": _sha(root / "ticket.md"),
            },
            "spec": {"path": "spec.md", "sha256": _sha(root / "spec.md")},
            "cycle_contract": {
                "path": "cycle.json",
                "sha256": _sha(root / "cycle.json"),
            },
            "ownership_ledger": {
                "path": "ledger.json",
                "sha256": _sha(root / "ledger.json"),
            },
            "registered_worktree_root": str(root),
            "registered_worktree_realpath": str(root.resolve()),
            "repository_identity": repo_identity,
            "repository_identity_canonical_sha256": projection["repository"][
                "identity_canonical_sha256"
            ],
            "root_authority_projection_sha256": projection_sha,
            "unique_worktree_registration": True,
        },
        "freshness_and_release": {"expires_at": "2099-01-01T00:00:00Z"},
    }
    admission_path = root / "admission.json"
    admission_sha = _write_json(admission_path, admission, 0o444)
    return AuthorityFixture(
        root=root,
        other=other,
        context=context_path,
        context_sha=context_sha,
        admission=admission_path,
        admission_sha=admission_sha,
        projection_sha=projection_sha,
    )


@pytest.fixture
def authority(tmp_path: Path) -> AuthorityFixture:
    return make_authority(tmp_path)


def assert_unknown(receipt: dict, needle: str | None = None) -> None:
    assert receipt["conclusion"] == "unknown"
    assert receipt["inconclusive_reasons"]
    if needle:
        assert any(needle in reason for reason in receipt["inconclusive_reasons"])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"0", 0),
        (b"-1.25", -1.25),
        (b"1e2", 100.0),
        (b'"finite"', "finite"),
        (b"null", None),
        (b"true", True),
        (b'{"nested":[1,false,null,"ok"]}', {"nested": [1, False, None, "ok"]}),
    ],
)
def test_strict_json_loads_accepts_standard_json(raw: bytes, expected: object):
    assert ne.strict_json_loads(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [b'{"duplicate":1,"duplicate":2}', b'{"value":1} trailing', b'"\xff"'],
)
def test_strict_json_loads_preserves_existing_rejections(raw: bytes):
    with pytest.raises(ne.EvidenceError, match="invalid strict JSON"):
        ne.strict_json_loads(raw)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("placement", ["top_level", "nested"])
def test_strict_json_loads_rejects_nonfinite_constants(token: str, placement: str):
    raw = token.encode("ascii")
    if placement == "nested":
        raw = b'{"outer":[{"value":' + raw + b"}]}"
    with pytest.raises(
        ne.EvidenceError,
        match=rf"invalid strict JSON: non-finite JSON constant: {token}",
    ):
        ne.strict_json_loads(raw)


def test_canonical_json_bytes_preserves_finite_encoding():
    value = {"z": 100.0, "a": [1, False, None, "有限"]}
    expected = b'{"a":[1,false,null,"\xe6\x9c\x89\xe9\x99\x90"],"z":100.0}'
    assert ne.canonical_json_bytes(value) == expected
    assert ne.canonical_json_bytes(value, newline=True) == expected + b"\n"


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("placement", ["top_level", "nested"])
def test_canonical_json_bytes_rejects_nonfinite_values(token: str, placement: str):
    value: object = _nonfinite_value(token)
    if placement == "nested":
        value = {"outer": [{"value": value}]}
    with pytest.raises(ValueError, match="Out of range float values"):
        ne.canonical_json_bytes(value)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_context_is_inconclusive_before_find(
    authority: AuthorityFixture, tmp_path: Path, token: str
):
    context = json.loads(authority.context.read_text())
    admission = json.loads(authority.admission.read_text())
    context["strict_json_nonfinite_probe"] = {"value": _nonfinite_value(token)}
    context_sha = _write_nonfinite_json(authority.context, context, token)
    admission["authority_chain"]["context"]["sha256"] = context_sha
    admission["root_authority"]["external_dispatch_inputs"][
        "expected_context_sha256"
    ] = context_sha
    admission_sha = _write_json(authority.admission, admission, 0o444)

    result, receipt, marker = _scan_cli(
        authority,
        tmp_path,
        expected_context_sha256=context_sha,
        expected_authority_sha256=admission_sha,
    )

    assert result.returncode == ne.INCONCLUSIVE_EXIT, result.stderr
    assert_unknown(receipt, f"non-finite JSON constant: {token}")
    assert receipt["execution"]["exit_code"] is None
    assert receipt["evidence"]["target_hits"] == []
    assert not marker.exists()
    assert not any(
        "raw SHA-256 mismatch" in reason for reason in receipt["inconclusive_reasons"]
    )


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_admission_is_inconclusive_before_find(
    authority: AuthorityFixture, tmp_path: Path, token: str
):
    admission = json.loads(authority.admission.read_text())
    admission["strict_json_nonfinite_probe"] = {"value": _nonfinite_value(token)}
    admission_sha = _write_nonfinite_json(authority.admission, admission, token)

    result, receipt, marker = _scan_cli(
        authority,
        tmp_path,
        expected_context_sha256=authority.context_sha,
        expected_authority_sha256=admission_sha,
    )

    assert result.returncode == ne.INCONCLUSIVE_EXIT, result.stderr
    assert_unknown(receipt, f"non-finite JSON constant: {token}")
    assert receipt["execution"]["exit_code"] is None
    assert receipt["evidence"]["target_hits"] == []
    assert not marker.exists()
    assert not any(
        "raw SHA-256 mismatch" in reason for reason in receipt["inconclusive_reasons"]
    )


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_receipt_fails_verify_before_rescan(
    authority: AuthorityFixture, tmp_path: Path, token: str
):
    receipt = authority.scan()
    receipt["request"]["timeout_ms"] = _nonfinite_value(token)
    receipt_path = tmp_path / f"nonfinite-receipt-{token}.json"
    receipt_sha = _write_nonfinite_json(receipt_path, receipt, token)
    env, marker = _cli_environment_that_records_find(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/negative-evidence.py"),
            "verify",
            "--receipt",
            str(receipt_path),
            "--expected-receipt-sha256",
            receipt_sha,
            "--contract-context",
            str(authority.context),
            "--expected-context-sha256",
            authority.context_sha,
            "--authority-file",
            str(authority.admission),
            "--expected-authority-sha256",
            authority.admission_sha,
            "--expected-authority-projection-sha256",
            authority.projection_sha,
            "--scan-root",
            str(authority.root),
            "--target-kind",
            "exact-path",
            "--target",
            "scope/missing.txt",
            "--expected-conclusion",
            "absent",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    verification = json.loads(result.stdout)

    assert result.returncode == ne.VERIFY_FAILURE_EXIT, result.stderr
    assert verification["ok"] is False
    assert verification["conclusion"] is None
    assert any(
        f"non-finite JSON constant: {token}" in error
        for error in verification["errors"]
    )
    assert "receipt raw SHA-256 mismatch" not in verification["errors"]
    assert not marker.exists()


# B01: external immutable root/repository authority.
def test_valid_authority_from_unrelated_cwd_cli(
    authority: AuthorityFixture, tmp_path: Path
):
    output = tmp_path / "receipt.json"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    cli = ROOT / "scripts/negative-evidence.py"
    args = [
        sys.executable,
        str(cli),
        "scan",
        "--contract-context",
        str(authority.context),
        "--expected-context-sha256",
        authority.context_sha,
        "--authority-file",
        str(authority.admission),
        "--expected-authority-sha256",
        authority.admission_sha,
        "--expected-authority-projection-sha256",
        authority.projection_sha,
        "--scan-root",
        str(authority.root),
        "--scope",
        "scope",
        "--target-kind",
        "exact-path",
        "--target",
        "scope/missing.txt",
        "--positive-control",
        "scope/control.txt",
        "--timeout-ms",
        "3000",
        "--max-output-bytes",
        "100000",
        "--max-files",
        "1000",
        "--output",
        str(output),
    ]
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(authority.other),
        "HOME": str(tmp_path / "fake-home"),
    }
    result = subprocess.run(
        args, cwd=unrelated, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert result.returncode == 0, result.stderr.decode()
    receipt = json.loads(output.read_text())
    assert receipt["conclusion"] == "absent"
    assert receipt["authority"]["errors"] == []
    assert stat.S_IMODE(output.stat().st_mode) == 0o444


def test_different_registered_equal_byte_worktree_is_unknown(
    authority: AuthorityFixture,
):
    receipt = authority.scan(scan_root=str(authority.other))
    assert_unknown(receipt, "scan_root_lexical_equality")
    assert receipt["execution"]["exit_code"] is None


def test_logical_alias_of_authoritative_root_is_unknown(
    authority: AuthorityFixture, tmp_path: Path
):
    alias = tmp_path / "authority-alias"
    alias.symlink_to(authority.root, target_is_directory=True)
    receipt = authority.scan(scan_root=str(alias))
    assert_unknown(receipt, "scan_root_lexical_equality")


@pytest.mark.parametrize("case", ["wrong_path", "missing", "wrong_digest"])
def test_context_binding_failures(
    authority: AuthorityFixture, tmp_path: Path, case: str
):
    values = {}
    if case == "wrong_path":
        copied = tmp_path / "context-copy.json"
        shutil.copyfile(authority.context, copied)
        values["contract_context"] = str(copied)
    elif case == "missing":
        values["contract_context"] = str(tmp_path / "missing-context.json")
    else:
        values["expected_context_sha256"] = "f" * 64
    assert_unknown(authority.scan(**values), "context")


@pytest.mark.parametrize(
    "case",
    ["wrong_path", "missing", "wrong_digest", "symlink", "mutable", "placeholder"],
)
def test_admission_binding_failures(
    authority: AuthorityFixture, tmp_path: Path, case: str
):
    values = {}
    if case == "wrong_path":
        copied = tmp_path / "admission-copy.json"
        shutil.copyfile(authority.admission, copied)
        copied.chmod(0o444)
        values["authority_file"] = str(copied)
    elif case == "missing":
        values["authority_file"] = str(tmp_path / "missing-admission.json")
    elif case == "wrong_digest":
        values["expected_authority_sha256"] = "f" * 64
    elif case == "symlink":
        link = tmp_path / "admission-link.json"
        link.symlink_to(authority.admission)
        values["authority_file"] = str(link)
    elif case == "mutable":
        authority.admission.chmod(0o644)
    else:
        values["expected_authority_sha256"] = "0" * 64
    assert_unknown(authority.scan(**values), "admission")


def test_authority_projection_expected_digest_mismatch(authority: AuthorityFixture):
    assert_unknown(
        authority.scan(expected_authority_projection_sha256="e" * 64),
        "authority_projection_digest",
    )


@pytest.mark.parametrize(
    "field", ["git_common_dir_realpath", "remote_origin_url", "object_format"]
)
def test_repository_identity_drift_is_unknown(tmp_path: Path, field: str):
    overrides = {
        "git_common_dir_realpath": "/not/the/common/dir",
        "remote_origin_url": "https://example.invalid/wrong.git",
        "object_format": "sha256",
    }
    fixture = make_authority(
        tmp_path, expected_repo_overrides={field: overrides[field]}
    )
    assert_unknown(fixture.scan(), "repository_")


@pytest.mark.parametrize("source", ["spec.md", "cycle.json", "ledger.json"])
def test_bound_source_drift_is_unknown(authority: AuthorityFixture, source: str):
    path = authority.root / source
    path.chmod(0o644)
    path.write_bytes(path.read_bytes() + b"drift\n")
    assert_unknown(authority.scan(), "digest")


def test_head_drift_is_unknown(authority: AuthorityFixture):
    (authority.root / "head-drift.txt").write_text("drift\n")
    _run("git", "add", "head-drift.txt", cwd=authority.root)
    _run("git", "commit", "-m", "head drift", cwd=authority.root)
    assert_unknown(authority.scan(), "repository_head")


@pytest.mark.parametrize("field", ["scopes", "prunes"])
def test_lexical_scope_or_prune_escape_is_usage_failure(
    authority: AuthorityFixture, field: str
):
    with pytest.raises(ne.UsageContractError):
        authority.scan(**{field: ["../outside"]})


def test_scope_symlink_outside_fails_before_find(
    authority: AuthorityFixture, tmp_path: Path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (authority.root / "outside-link").symlink_to(outside, target_is_directory=True)
    receipt = authority.scan(
        scopes=["outside-link"], positive_control="outside-link/control"
    )
    assert_unknown(receipt, "outside")
    assert receipt["execution"]["exit_code"] is None


# C2 existing matrix: real find -L behavior and fail-closed diagnostics.
def test_find_L_follows_scope_symlink_inside_root(authority: AuthorityFixture):
    (authority.root / "real").mkdir()
    (authority.root / "real/control.txt").write_text("control\n")
    (authority.root / "real/target.txt").write_text("target\n")
    (authority.root / "scope-link").symlink_to("real", target_is_directory=True)
    receipt = authority.scan(
        scopes=["scope-link"],
        target="scope-link/target.txt",
        positive_control="scope-link/control.txt",
    )
    assert receipt["conclusion"] == "present"


def test_find_L_follows_child_symlink_inside_root(authority: AuthorityFixture):
    (authority.root / "real").mkdir()
    (authority.root / "real/control.txt").write_text("control\n")
    (authority.root / "real/target.txt").write_text("target\n")
    (authority.root / "scope/link").symlink_to("../real", target_is_directory=True)
    receipt = authority.scan(
        target="scope/link/target.txt", positive_control="scope/link/control.txt"
    )
    assert receipt["conclusion"] == "present"


def test_unique_target_present(authority: AuthorityFixture):
    (authority.root / "scope/target.txt").write_text("target\n")
    assert authority.scan(target="scope/target.txt")["conclusion"] == "present"


def test_true_absent_with_unique_control(authority: AuthorityFixture):
    receipt = authority.scan()
    assert receipt["conclusion"] == "absent"
    assert receipt["evidence"]["target_hits"] == []
    assert receipt["evidence"]["control_hits"] == ["scope/control.txt"]


def test_duplicate_target_is_unknown(authority: AuthorityFixture):
    for name in ("a", "b"):
        (authority.root / f"scope/{name}").mkdir()
        (authority.root / f"scope/{name}/needle.txt").write_text(name)
    receipt = authority.scan(target_kind="basename", target="needle.txt")
    assert_unknown(receipt, "target matched more than once")


def test_duplicate_control_from_overlapping_scopes_is_unknown(
    authority: AuthorityFixture,
):
    (authority.root / "scope/sub").mkdir()
    (authority.root / "scope/sub/control.txt").write_text("control\n")
    receipt = authority.scan(
        scopes=["scope", "scope/sub"], positive_control="scope/sub/control.txt"
    )
    assert_unknown(receipt, "positive control matched 2 times")


def test_missing_control_is_unknown(authority: AuthorityFixture):
    assert_unknown(
        authority.scan(positive_control="scope/not-there.txt"),
        "positive control matched 0 times",
    )


def _fake_find(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: str) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "find"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])


def test_find_stderr_and_nonzero_is_unknown(
    authority: AuthorityFixture, monkeypatch, tmp_path
):
    _fake_find(monkeypatch, tmp_path, "echo forced-error >&2\nexit 7\n")
    receipt = authority.scan()
    assert_unknown(receipt, "find emitted stderr")
    assert receipt["execution"]["exit_code"] == 7


def test_find_timeout_is_unknown(authority: AuthorityFixture, monkeypatch, tmp_path):
    _fake_find(monkeypatch, tmp_path, "sleep 2\n")
    receipt = authority.scan(timeout_ms=30)
    assert_unknown(receipt, "timed out")
    assert receipt["execution"]["timed_out"] is True


def test_stdout_truncation_is_unknown(authority: AuthorityFixture):
    for index in range(30):
        (authority.root / f"scope/file-{index:02d}.txt").write_text("x")
    receipt = authority.scan(max_output_bytes=10)
    assert_unknown(receipt, "max_output_bytes")
    assert receipt["execution"]["stdout_truncated"] is True


def test_max_file_limit_is_unknown(authority: AuthorityFixture):
    (authority.root / "scope/another.txt").write_text("x")
    receipt = authority.scan(max_files=1)
    assert_unknown(receipt, "max_files")
    assert receipt["execution"]["max_files_exceeded"] is True


def test_excluded_exact_target_is_unknown(authority: AuthorityFixture):
    (authority.root / "scope/pruned").mkdir()
    receipt = authority.scan(prunes=["scope/pruned"], target="scope/pruned/missing.txt")
    assert_unknown(receipt, "hidden by a prune")


def test_basename_absence_with_any_prune_is_unknown(authority: AuthorityFixture):
    (authority.root / "scope/pruned").mkdir()
    receipt = authority.scan(
        prunes=["scope/pruned"], target_kind="basename", target="missing.txt"
    )
    assert_unknown(receipt, "hidden by a prune")


def test_equal_count_rename_breaks_verify(authority: AuthorityFixture, tmp_path: Path):
    old = authority.root / "scope/old.txt"
    old.write_text("same\n")
    receipt = authority.scan()
    path = tmp_path / "rename-receipt.json"
    digest = authority.save(receipt, path)
    old.rename(authority.root / "scope/new.txt")
    result = authority.verify(path, digest)
    assert result["ok"] is False
    assert any("semantic projection" in error for error in result["errors"])


def test_same_path_byte_drift_breaks_verify(
    authority: AuthorityFixture, tmp_path: Path
):
    data = authority.root / "scope/data.txt"
    data.write_text("before\n")
    receipt = authority.scan()
    path = tmp_path / "byte-receipt.json"
    digest = authority.save(receipt, path)
    data.write_text("after!\n")
    result = authority.verify(path, digest)
    assert result["ok"] is False


@pytest.mark.parametrize("field", ["receipt_digest", "argv", "scope"])
def test_receipt_digest_argv_and_scope_drift_fail_verify(
    authority: AuthorityFixture, tmp_path: Path, field: str
):
    receipt = authority.scan()
    path = tmp_path / f"{field}.json"
    if field == "receipt_digest":
        digest = authority.save(receipt, path)
        digest = "f" * 64
    else:
        tampered = copy.deepcopy(receipt)
        if field == "argv":
            tampered["execution"]["argv"].append("-false")
        else:
            tampered["request"]["scopes"] = ["."]
            tampered["request"]["scope_paths"] = [str(authority.root)]
            core = {
                key: value
                for key, value in tampered["request"].items()
                if key != "scan_config_sha256"
            }
            tampered["request"]["scan_config_sha256"] = hashlib.sha256(
                ne.canonical_json_bytes(core)
            ).hexdigest()
        path.write_bytes(ne.canonical_json_bytes(tampered, newline=True))
        path.chmod(0o444)
        digest = _sha(path)
    result = authority.verify(path, digest)
    assert result["ok"] is False
    assert result["errors"]


def test_receipt_from_wrong_authority_cannot_verify(tmp_path: Path):
    first = make_authority(tmp_path / "first")
    second = make_authority(tmp_path / "second")
    receipt = first.scan()
    path = tmp_path / "wrong-authority-receipt.json"
    digest = first.save(receipt, path)
    result = second.verify(path, digest)
    assert result["ok"] is False
    assert any("external receipt binding" in error for error in result["errors"])


# B02: actual registry/runtime integration and hard failures.
def test_fresh_process_real_registry_resolves_and_runtime_accepts(
    authority: AuthorityFixture, tmp_path: Path
):
    receipt_path = tmp_path / "fresh-process.json"
    receipt = authority.scan()
    receipt_path.write_bytes(ne.canonical_json_bytes(receipt, newline=True))
    code = """
import json, os, sys
from pathlib import Path
root=Path(os.environ['HARNESS_ROOT'])
sys.path.insert(0,str(root/'hooks'))
from lib import contract_runtime, schema_registry
record=json.loads(Path(os.environ['RECEIPT']).read_text())
schema=schema_registry.get_schema('negative-evidence.v1')
result=contract_runtime.validate(record,'negative-evidence.v1')
print(json.dumps({'id':schema.get('$id') if schema else None,'result':result},sort_keys=True))
raise SystemExit(0 if schema and result.get('ok') and result.get('severity')=='pass' else 1)
"""
    env = {**os.environ, "HARNESS_ROOT": str(ROOT), "RECEIPT": str(receipt_path)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["id"] == "negative-evidence.v1"


@pytest.mark.parametrize("mutation", ["extra", "wrong_schema", "wrong_version"])
def test_contract_runtime_rejects_closed_or_wrong_version_receipt(
    authority: AuthorityFixture, mutation: str
):
    receipt = authority.scan()
    if mutation == "extra":
        receipt["unexpected"] = True
    elif mutation == "wrong_schema":
        receipt["$schema"] = "other.v1"
    else:
        receipt["schema_version"] = 2
    result = contract_runtime.validate(receipt, ne.SCHEMA_NAME)
    assert result["ok"] is False
    assert result["severity"] == "fail"


def _with_temp_registry(tmp_path: Path, registry: dict, schema_mutator=None):
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    schema = json.loads((ROOT / "schemas/negative-evidence.v1.json").read_text())
    if schema_mutator:
        schema_mutator(schema)
    _write_json(schemas / "negative-evidence.v1.json", schema)
    _write_json(schemas / "other.json", schema)
    _write_json(schemas / "registry.json", registry)
    return schemas


@pytest.mark.parametrize("case", ["unregistered", "wrong_file", "schema_tamper"])
def test_registry_mapping_and_schema_tamper_are_hard_failures(
    authority: AuthorityFixture, tmp_path: Path, monkeypatch, case: str
):
    receipt = authority.scan()
    mapping = {}
    mutator = None
    if case == "wrong_file":
        mapping = {ne.SCHEMA_NAME: "other.json"}
    elif case == "schema_tamper":
        mapping = {ne.SCHEMA_NAME: "negative-evidence.v1.json"}

        def _tamper_schema(schema):
            schema.update({"title": "tampered"})

        mutator = _tamper_schema

    schemas = _with_temp_registry(tmp_path, {"schemas": mapping}, mutator)
    monkeypatch.setattr(schema_registry, "SCHEMAS_DIR", schemas)
    monkeypatch.setattr(schema_registry, "REGISTRY_PATH", schemas / "registry.json")
    schema_registry._CACHE.clear()
    schema_registry._REGISTRY_LOADED = False
    try:
        with pytest.raises(ne.SchemaContractError):
            ne.validate_receipt_schema(receipt)
        # An unknown/unregistered schema cannot be reclassified as an inconclusive receipt.
        if case == "unregistered":
            with pytest.raises(ne.SchemaContractError):
                authority.scan()
    finally:
        schema_registry._CACHE.clear()
        schema_registry._REGISTRY_LOADED = False


def test_receipt_parse_and_expected_digest_tamper_are_hard_failures(
    authority: AuthorityFixture, tmp_path: Path
):
    broken = tmp_path / "broken.json"
    broken.write_bytes(b'{"$schema":"negative-evidence.v1",')
    broken.chmod(0o444)
    result = authority.verify(broken, _sha(broken))
    assert result["ok"] is False
    assert any("invalid strict JSON" in error for error in result["errors"])
    valid = tmp_path / "valid.json"
    digest = authority.save(authority.scan(), valid)
    result = authority.verify(valid, "f" * 64)
    assert result["ok"] is False
    assert "receipt raw SHA-256 mismatch" in result["errors"]
    assert digest != "f" * 64
