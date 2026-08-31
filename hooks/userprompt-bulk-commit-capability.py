#!/usr/bin/env python3
"""Trusted UserPromptSubmit capability minter.

The existing ``/commit --bulk`` behavior is preserved byte-for-byte in intent.
Lane F additionally recognizes only a later, top-level human ``/close --fix
--confirm`` prompt and mints a separately typed, preview-bound, single-use
``human_fix_confirmation.v1`` grant.  The two capability types are never
interchangeable and this hook remains non-blocking.
"""
import hashlib
import importlib.util
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
_WRITER_PATH = _SCRIPTS_DIR / "write-bulk-commit-sentinel.py"
_COMMIT_RE = re.compile(r"^\s*/commit(?:\s|$)")
_BULK_FLAG_RE = re.compile(r"(?:^|\s)--bulk(?:\s|$|\W)")
_TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_INVOCATION_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_WAIVER_RE = re.compile(r"^(F01|F02):(.+)$")
_GRANT_SCHEMA = "human_fix_confirmation.v1"
_AUDIT_SCHEMA = "fix-audit.v2"
_MAX_AUDIT_BYTES = 8 * 1024 * 1024
_OWNERSHIP_ADMISSION_DIGEST = "sha256:6a4b1bfbe7267b0683ccf4845731a3e893d3aa1fa44a69493476d6da551be71c"
_IDENTITY_FIELDS = {
    "schema_version", "canonical_project_root", "task_id", "entrypoint",
    "origin_session_id", "origin_invocation_id", "request_digest",
    "inventory_digest_before", "r1_result_digest", "run_id",
}
_PLAN_FIELDS = {
    "schema_version", "run_id", "entrypoint", "origin_invocation_id",
    "origin_session_id", "request_digest", "r1_result_digest", "inventory_digest",
    "actions", "waivers", "gate_required", "gate_kind", "allowed_mutations",
    "plan_digest",
}
_PREVIEW_RUN_FIELDS = {
    "run_id", "request_digest", "identity", "plan", "decision", "classified_events",
    "inventory_before", "inventory_digest_after", "state", "state_history",
    "confirmation_nonce", "gate_invocation_id", "identity_adoption_digest",
    "gate_preclaim_digest", "mutations", "waivers", "gate_handoff",
    "gate_attempt_count", "gate_receipt_digest", "ownership_admission_digest",
}
_HANDOFF_FIELDS = {
    "required", "state", "gate_kind", "gate_attempt_id", "gate_invocation_id",
    "identity_adoption_digest", "handoff_digest", "claim_token", "gate_preclaim_digest",
    "allowed_mutations_digest", "allowed_mutations", "pre_gate_state_digest",
    "receipt_digest", "outcome",
}


def _canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value, exclude=None):
    if exclude is not None:
        value = {k: v for k, v in value.items() if k != exclude}
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _confirmation_invocation_id(prompt_digest):
    """Derive the only apply UUID authorized by this trusted prompt event."""
    if not isinstance(prompt_digest, str) or not _DIGEST_RE.fullmatch(prompt_digest):
        raise ValueError("invalid confirmation prompt digest")
    raw = bytearray.fromhex(prompt_digest.removeprefix("sha256:"))[:16]
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def _strict_load(raw):
    duplicates = []
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                duplicates.append(key)
            out[key] = value
        return out
    text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
    value = json.loads(text, object_pairs_hook=pairs,
                       parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    if duplicates:
        raise ValueError("duplicate key")
    return value


def _is_bulk_commit(prompt: str) -> bool:
    if not prompt or not _COMMIT_RE.match(prompt):
        return False
    args = re.sub(r"^\s*/commit", "", prompt, count=1)
    return bool(_BULK_FLAG_RE.search(args))


def _mint(sid: str) -> None:
    """Mint the established bulk capability through its canonical writer."""
    spec = importlib.util.spec_from_file_location("_wbcs_writer", _WRITER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load writer at {_WRITER_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main(["--sid", sid, "--origin", "userpromptsubmit-hook"])


def _safe_rel(value):
    if not isinstance(value, str) or not value or os.path.isabs(value) or "\x00" in value:
        raise ValueError("unsafe waiver path")
    normalized = Path(value).as_posix()
    if normalized != value or value.startswith("./") or any(p in {"", ".", ".."} for p in value.split("/")):
        raise ValueError("unsafe waiver path")
    return value


def _parse_fix_confirmation(prompt):
    try:
        tokens = shlex.split(prompt, posix=True)
    except ValueError:
        return None
    if len(tokens) < 11 or tokens[0] != "/close" or not _TASK_RE.fullmatch(tokens[1]) \
            or tokens[2:4] != ["--fix", "--confirm"] or not _NONCE_RE.fullmatch(tokens[4]) \
            or tokens[5] != "--digest" or not _DIGEST_RE.fullmatch(tokens[6]):
        return None
    task_id, nonce, plan_digest = tokens[1], tokens[4], tokens[6]
    index = 7
    waivers = []
    while index + 1 < len(tokens) and tokens[index] == "--waive":
        match = _WAIVER_RE.fullmatch(tokens[index + 1])
        if not match:
            return None
        try:
            path = _safe_rel(match.group(2))
        except ValueError:
            return None
        waivers.append({"catalog_id": match.group(1), "path": path})
        index += 2
    if not waivers or index + 2 != len(tokens) or tokens[index] != "--reason" \
            or not tokens[index + 1].strip():
        return None
    if waivers != sorted(waivers, key=lambda x: (x["catalog_id"], x["path"])) \
            or len({(x["catalog_id"], x["path"]) for x in waivers}) != len(waivers):
        return None
    return {"task_id": task_id, "nonce": nonce, "plan_digest": plan_digest,
            "waivers": waivers, "reason": tokens[index + 1]}


def _canonical_project_root(data):
    supplied = [value for value in (data.get("cwd"), data.get("project_dir"))
                if value is not None and value != ""]
    if not supplied or any(not isinstance(value, str) or not os.path.isabs(value)
                           for value in supplied):
        return None
    roots = {os.path.realpath(value) for value in supplied}
    if len(roots) != 1:
        return None
    real = roots.pop()
    try:
        proc = subprocess.run(["git", "-C", real, "rev-parse", "--show-toplevel"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=5, check=False,
                              env={"PATH": os.environ.get("PATH", "")})
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    top = os.path.realpath(proc.stdout.decode("utf-8", errors="strict").strip())
    return top if top == real else None


def _load_preview(root, parsed, sid):
    audit_path = Path(root) / "docs/dev" / f"fix-audit-{parsed['task_id']}.json"
    if os.path.realpath(audit_path.parent) != str(audit_path.parent):
        raise ValueError("unsafe audit")
    dfd = os.open(audit_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fd = os.open(audit_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() \
                    or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1 \
                    or st.st_size <= 0 or st.st_size > _MAX_AUDIT_BYTES:
                raise ValueError("unsafe audit")
            chunks = []
            remaining = _MAX_AUDIT_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) != st.st_size or len(raw) > _MAX_AUDIT_BYTES:
                raise ValueError("unsafe audit")
        finally:
            os.close(fd)
    finally:
        os.close(dfd)
    audit = _strict_load(raw)
    exact = {"schema_version", "project_root", "task_id", "generation", "runs",
             "created_at", "updated_at", "audit_digest"}
    if not isinstance(audit, dict) or set(audit) != exact or audit["schema_version"] != _AUDIT_SCHEMA \
            or audit["project_root"] != root or audit["task_id"] != parsed["task_id"] \
            or not isinstance(audit["generation"], int) or audit["generation"] < 1 \
            or not isinstance(audit["runs"], list) \
            or audit["audit_digest"] != _digest(audit, "audit_digest"):
        raise ValueError("invalid audit")
    matches = []
    for run in audit["runs"]:
        if not isinstance(run, dict) or set(run) != _PREVIEW_RUN_FIELDS \
                or run.get("state") != "PREVIEWED":
            continue
        identity, plan = run.get("identity"), run.get("plan")
        if not isinstance(identity, dict) or set(identity) != _IDENTITY_FIELDS \
                or not isinstance(plan, dict) or set(plan) != _PLAN_FIELDS:
            continue
        if identity.get("schema_version") != "dev_fix_run_identity.v1" \
                or plan.get("schema_version") != "dev_fix_plan.v1" \
                or identity.get("run_id") != _digest(identity, "run_id") \
                or plan.get("plan_digest") != _digest(plan, "plan_digest") \
                or run.get("run_id") != identity.get("run_id") \
                or run.get("request_digest") != identity.get("request_digest") \
                or plan.get("run_id") != identity.get("run_id") \
                or plan.get("entrypoint") != identity.get("entrypoint") \
                or plan.get("origin_invocation_id") != identity.get("origin_invocation_id") \
                or plan.get("origin_session_id") != identity.get("origin_session_id") \
                or plan.get("request_digest") != identity.get("request_digest") \
                or plan.get("r1_result_digest") != identity.get("r1_result_digest") \
                or plan.get("inventory_digest") != identity.get("inventory_digest_before"):
            continue
        template = plan.get("allowed_mutations")
        template_fields = {"schema_version", "entrypoint", "gate_kind", "required_output_kinds",
                           "repository_ceiling_source", "template_digest"}
        handoff = run.get("gate_handoff")
        decision = run.get("decision")
        waiver_rows = run.get("waivers")
        history = run.get("state_history")
        expected_kinds = ["cleanliness_inspector_report", "close_report", "prompt_inspector_report",
                          "qa_checkpoint_if_applicable", "style_inspector_report"]
        identity_digests = (identity.get("request_digest"), identity.get("inventory_digest_before"),
                            identity.get("r1_result_digest"), identity.get("run_id"))
        if identity.get("canonical_project_root") != root or identity.get("task_id") != parsed["task_id"] \
                or identity.get("entrypoint") != "close" or identity.get("origin_session_id") != sid \
                or not _INVOCATION_RE.fullmatch(str(identity.get("origin_invocation_id", ""))) \
                or not all(_DIGEST_RE.fullmatch(str(item or "")) for item in identity_digests) \
                or not isinstance(run.get("inventory_before"), list) \
                or _digest(run["inventory_before"]) != identity.get("inventory_digest_before") \
                or run.get("inventory_digest_after") is not None \
                or run.get("confirmation_nonce") != parsed["nonce"] \
                or run.get("gate_invocation_id") is not None \
                or run.get("identity_adoption_digest") is not None \
                or run.get("gate_preclaim_digest") is not None \
                or run.get("mutations") != [] or run.get("gate_attempt_count") != 0 \
                or run.get("gate_receipt_digest") is not None \
                or run.get("ownership_admission_digest") != _OWNERSHIP_ADMISSION_DIGEST:
            continue
        if not isinstance(history, list) or len(history) != 1 or not isinstance(history[0], dict) \
                or set(history[0]) != {"state", "at"} or history[0].get("state") != "PREVIEWED" \
                or not isinstance(history[0].get("at"), str):
            continue
        if not isinstance(decision, dict) \
                or set(decision) != {"root_decision_ids", "secondary_evidence_codes", "disposition", "protected"} \
                or decision.get("disposition") != "waiver_candidate" or decision.get("protected") is not False \
                or not isinstance(decision.get("root_decision_ids"), list) \
                or not set(decision["root_decision_ids"]) <= {"F01", "F02", "NO_BLOCKER"} \
                or not {row["catalog_id"] for row in parsed["waivers"]} <= set(decision["root_decision_ids"]):
            continue
        if not isinstance(template, dict) or set(template) != template_fields \
                or template.get("schema_version") != "dev_fix_mutation_envelope_template.v1" \
                or template.get("entrypoint") != "close" \
                or template.get("gate_kind") != "close_artifact_chain_and_verdict" \
                or template.get("required_output_kinds") != expected_kinds \
                or template.get("repository_ceiling_source") is not None \
                or template.get("template_digest") != _digest(template, "template_digest"):
            continue
        if not isinstance(handoff, dict) or set(handoff) != _HANDOFF_FIELDS \
                or handoff != {"required": False, "state": "not_required", "gate_kind": None,
                               "gate_attempt_id": None, "gate_invocation_id": None,
                               "identity_adoption_digest": None, "handoff_digest": None,
                               "claim_token": None, "gate_preclaim_digest": None,
                               "allowed_mutations_digest": None, "allowed_mutations": None,
                               "pre_gate_state_digest": None, "receipt_digest": None, "outcome": None}:
            continue
        waiver_fields = {"catalog_id", "path", "reason_digest", "confirmation_grant_digest",
                         "projection_digest", "status"}
        if not isinstance(waiver_rows, list) or len(waiver_rows) != len(parsed["waivers"]) \
                or any(not isinstance(row, dict) or set(row) != waiver_fields \
                       or row.get("status") != "planned" or row.get("projection_digest") is not None \
                       or not _DIGEST_RE.fullmatch(str(row.get("reason_digest", ""))) \
                       or not _DIGEST_RE.fullmatch(str(row.get("confirmation_grant_digest", "")))
                       for row in waiver_rows) \
                or [{"catalog_id": row["catalog_id"], "path": row["path"]}
                    for row in waiver_rows] != parsed["waivers"]:
            continue
        if run.get("confirmation_nonce") == parsed["nonce"] \
                and plan.get("plan_digest") == parsed["plan_digest"] \
                and plan.get("waivers") == parsed["waivers"] \
                and plan.get("actions") == [] \
                and plan.get("entrypoint") == "close" \
                and plan.get("gate_required") is False \
                and plan.get("gate_kind") is None \
                and identity.get("origin_session_id") == sid \
                and identity.get("canonical_project_root") == root \
                and identity.get("task_id") == parsed["task_id"]:
            matches.append(run)
    if len(matches) != 1:
        raise ValueError("preview absent or ambiguous")
    return matches[0]


def _mint_fix_confirmation(data, prompt, sid):
    parsed = _parse_fix_confirmation(prompt)
    if parsed is None or not _SESSION_RE.fullmatch(sid) or data.get("prompt") != prompt \
            or data.get("session_id") != sid:
        return False
    root = _canonical_project_root(data)
    if root is None:
        return False
    destination = None
    destination_name = None
    dfd = None
    created = False
    try:
        run = _load_preview(root, parsed, sid)
        now = datetime.now(timezone.utc)
        prompt_event_id = data.get("prompt_id")
        if not isinstance(prompt_event_id, str) or not prompt_event_id:
            prompt_event_id = data.get("event_id")
        if not isinstance(prompt_event_id, str) or not prompt_event_id:
            raise ValueError("trusted prompt event identity is absent")
        prompt_event = {"prompt": prompt, "session_id": sid, "canonical_project_root": root,
                        "prompt_id": prompt_event_id}
        prompt_digest = _digest(prompt_event)
        prompt_id_or_hash = _confirmation_invocation_id(prompt_digest)
        grant = {
            "schema_version": _GRANT_SCHEMA,
            "origin": "userpromptsubmit-hook",
            "session_id": sid,
            "prompt_id_or_prompt_sha256": prompt_id_or_hash,
            "canonical_project_root": root,
            "task_id": parsed["task_id"],
            "command": "close",
            "nonce": parsed["nonce"],
            "preview_run_id": run["run_id"],
            "preview_request_digest": run["identity"]["request_digest"],
            "preview_plan_digest": run["plan"]["plan_digest"],
            "preview_invocation_id": run["identity"]["origin_invocation_id"],
            "preview_inventory_digest": run["identity"]["inventory_digest_before"],
            "confirmation_prompt_digest": prompt_digest,
            "waivers": parsed["waivers"],
            "reason": parsed["reason"],
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "confirmation_grant_digest": None,
        }
        grant["confirmation_grant_digest"] = _digest(grant, "confirmation_grant_digest")
        destination_name = f"claude-fix-confirmation-{sid}-{parsed['nonce']}.json"
        destination = Path("/tmp") / destination_name
        dfd = os.open("/tmp", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        fd = os.open(destination_name,
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=dfd)
        created = True
        raw = _canonical_bytes(grant) + b"\n"
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
            written = os.fstat(handle.fileno())
            if not stat.S_ISREG(written.st_mode) or written.st_uid != os.geteuid() \
                    or stat.S_IMODE(written.st_mode) != 0o600 or written.st_nlink != 1 \
                    or written.st_size != len(raw):
                raise ValueError("grant write attributes are invalid")
        os.fsync(dfd)
        verify_fd = os.open(destination_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=dfd)
        try:
            observed = os.fstat(verify_fd)
            chunks = []
            remaining = len(raw) + 1
            while remaining:
                chunk = os.read(verify_fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            os.close(verify_fd)
        if (observed.st_dev, observed.st_ino) != (written.st_dev, written.st_ino) \
                or not stat.S_ISREG(observed.st_mode) or observed.st_uid != os.geteuid() \
                or stat.S_IMODE(observed.st_mode) != 0o600 or observed.st_nlink != 1 \
                or b"".join(chunks) != raw:
            raise ValueError("grant post-write verification failed")
        return True
    except Exception as exc:  # non-blocking but never best-effort mint
        if created and destination_name is not None:
            try:
                if dfd is not None:
                    os.unlink(destination_name, dir_fd=dfd)
                    os.fsync(dfd)
                elif destination is not None:
                    destination.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        print(f"[fix-confirmation-capability] mint skipped: {exc}", file=sys.stderr)
        return False
    finally:
        if dfd is not None:
            os.close(dfd)


def main() -> int:
    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            return 0
        if not isinstance(data, dict):
            return 0
        prompt = data.get("prompt", "")
        if not isinstance(prompt, str):
            return 0
        sid_raw = data.get("session_id", "")
        sid = str(sid_raw) if sid_raw is not None else ""
        if _is_bulk_commit(prompt):
            if not sid:
                print("[bulk-commit-capability] /commit --bulk seen but no session_id; "
                      "deferring to /commit Step 5 fallback", file=sys.stderr)
                return 0
            try:
                _mint(sid)
            except SystemExit:
                pass
            except Exception as exc:
                print(f"[bulk-commit-capability] mint skipped: {exc}", file=sys.stderr)
                return 0
            print(f"[bulk-commit-capability] bulk-commit capability minted for session {sid}",
                  file=sys.stderr)
            return 0
        if _mint_fix_confirmation(data, prompt, sid):
            print(f"[fix-confirmation-capability] preview-bound capability minted for session {sid}",
                  file=sys.stderr)
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
