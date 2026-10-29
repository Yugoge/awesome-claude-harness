"""Work a compliant subagent does beyond its declared artifacts, as its agent text describes it.

Each helper returns an Act.work callable, work(sub, brief, player) -> content,
that performs the role's own tool calls (through the framework, so hooks see
them) and returns content for the artifacts the obligation declares (keyed by
artifact path or glob, "*" for every JSON artifact of the dispatch). The commands,
file names and templates come from agents/<role>.md of the tree
under test at run time; the driver supplies only the scenario (which file
changes, which acceptance criteria). A driver picks the helper that matches the
role it dispatches; nothing here enumerates roles.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex

from . import cmdtext
from .agents import peek, put


def ac_uid(ac: dict) -> str:
    """agents/ba.md Step 10: sha256(type+given+when+then+JSON.stringify(check))[:16]."""
    raw = ac["type"] + ac["given"] + ac["when"] + ac["then"] + json.dumps(ac["check"], separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def acceptance_criteria(items: list[dict]) -> list[dict]:
    return [dict(it, ac_uid=ac_uid(it)) for it in items]


def _prompt_value(prompt: str, key: str) -> str | None:
    m = re.search(r"^\s*%s:\s*(\S+)" % re.escape(key), prompt, re.M)
    return m.group(1) if m else None


def _codes(text: str, heading: str, *needles: str) -> str:
    """The inline code of a section of an agent file holding every needle."""
    sec = cmdtext.section(text, heading)
    for code in re.findall(r"`([^`\n]+)`", sec):
        if all(n in code for n in needles):
            return code
    raise cmdtext.TextNotFound(f"no inline code with {needles} under {heading!r}")


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------- test-writer

def test_writer(tier_key: str = "complexity_tier", risk_key: str = "risk_level"):
    """Skeletons per acceptance criterion from the agent file's skeleton template, the per-task
    manifest content, the global index the prompt names, and the report content."""

    def work(sub, brief, player):
        tree, project, tid, prompt = player.tree, brief.project, brief.task_id, brief.prompt
        ac_rel = _prompt_value(prompt, "acceptance_criteria_path")
        acs = json.loads(peek(sub.rp, sub.role, os.path.join(project, ac_rel))).get("acceptance_criteria") or []
        gen_dir = _prompt_value(prompt, "Generated tests go under").rstrip("/")
        index_rel = _prompt_value(prompt, "Global index")
        tier, risk = _prompt_value(prompt, tier_key), _prompt_value(prompt, risk_key)
        # The skeleton's file name as the agent file's heading spells it (`.../test_AC<NN>_<ac_uid>.py`).
        name = next((c for c in re.findall(r"^#{2,6} .*?`([^`]*<ac_uid>[^`]*\.py)`", player.tree.agent_text(player.role),
                                           re.M)), None)
        if name is None:
            raise cmdtext.TextNotFound(f"agents/{player.role}.md names no skeleton file pattern")
        tests, active = [], []
        for n, ac in enumerate(acs, 1):
            uid = ac["ac_uid"]
            norm = re.sub(r"\W", "_", ac["id"])
            rel = f"{gen_dir}/" + os.path.basename(name).replace("<NN>", f"{n:02d}").replace("<ac_uid>", uid)
            tpl = tree.template(player.role, rel)
            if tpl is None:
                raise cmdtext.TextNotFound(f"agents/{player.role}.md has no template for {rel}")
            text = tpl
            for key, val in (("<acceptance_criteria_path>", ac_rel), ("<id_normalized>", norm), ("<id>", ac["id"]),
                             ("<ac_uid>", uid), ("<ui|api|data|hook>", ac["type"]), ("<type>", ac["type"]),
                             ("<given>", ac["given"]), ("<when>", ac["when"]), ("<then>", ac["then"]),
                             ("<one-line summary>", ac["then"])):
                text = text.replace(key, val)
            put(sub, os.path.join(project, rel), text, f"{sub.role} Write {rel}")
            tests.append(rel)
            active.append({"task_id": tid, "ac_id": ac["id"], "ac_uid": uid, "type": ac["type"], "file": rel,
                           "status": "active", "hook_check": ac.get("check", {})})
        manifest_rel = _prompt_value(prompt, "Per-task active manifest") or f"{gen_dir}/manifest.json"
        report_rel = _prompt_value(prompt, "Write your report to")
        report = {"manifest_path": manifest_rel,
                  "trigger_gate": {"complexity_tier": tier, "risk_level": risk, "fired": True},
                  "tests_created": tests, "tests_archived": [], "tests_skipped_idempotent": [], "status": "completed"}
        if index_rel:  # the global index the prompt names ({kind: "index", tasks: [...]}), upserted
            index_path = os.path.join(project, index_rel)
            index = {"kind": "index", "tasks": []}
            if os.path.isfile(index_path):
                sub.read(index_path, label=f"{sub.role} Read {index_rel}")
                index = json.loads(peek(sub.rp, sub.role, index_path))
            index.setdefault("schema_version", "1.0")
            index["tasks"] = [t for t in index.get("tasks", []) if t.get("task_id") != tid] + [
                {"task_id": tid, "manifest_path": manifest_rel}]
            put(sub, index_path, json.dumps(index, indent=2) + "\n", f"{sub.role} Write {index_rel}")
            report.update(global_index_path=index_rel, global_index_kind=index["kind"])
        return {manifest_rel: {"schema_version": "1.1", "active_tests": active, "archived_tests": []},
                report_rel: report}
    return work


# ---------------------------------------------------------------- dev

def dev(edits: list, test_bodies: dict | None = None, report_extra: dict | None = None, creates: list | None = None,
        baseline_fallback: bool = False):
    """Apply `edits` [(rel, old, new)] (Read, then Edit), write each new file of `creates`
    [(rel, content)] (an existing one is Read, then edited in place), replace each generated test's
    TEST_INCOMPLETE sentinel line with `test_bodies[ac_uid]`, then derive dev.files_* with the
    git commands of the agent text (with `baseline_fallback`, its `git status --porcelain` fallback
    when the dispatch passed no baseline_head_sha) and record the owned-edits ledger and pre-edit
    snapshots."""

    def work(sub, brief, player):
        project, prompt = brief.project, brief.prompt
        text = player.tree.agent_text(player.role)
        owned, snapshots, touched = {}, {}, []

        def edit(rel, old, new):
            path = os.path.join(project, rel)
            sub.read(path, label=f"{sub.role} Read {rel}")
            before = peek(sub.rp, sub.role, path)
            snapshots.setdefault(rel, before)
            call = sub.edit(path, old, new, label=f"{sub.role} Edit {rel}")
            if call.ok:
                owned.setdefault(rel, []).append({"old": old, "new": new})
                touched.append(rel)

        for rel, old, new in edits:
            edit(rel, old, new)
        for rel, content in creates or []:
            path = os.path.join(project, rel)
            existed = os.path.exists(path)  # put() then Reads it and edits it in place
            call = put(sub, path, content, f"{sub.role} Write {rel}")
            if call is None or not call.ok:
                continue
            r = call.response
            snapshots.setdefault(rel, r.get("originalFile", "") if existed else "")  # a new file: empty
            owned.setdefault(rel, []).append({"old": r.get("oldString", "") if existed else "",
                                              "new": r.get("newString", "") if existed else content})
            touched.append(rel)
        gen = re.search(r"Generated tests \(when test-writer ran\):\s*(\S+?)/?\s", prompt)
        gen_dir = gen.group(1).rstrip("/") if gen else None
        if test_bodies and gen_dir and os.path.isdir(os.path.join(project, gen_dir)):
            for fn in sorted(os.listdir(os.path.join(project, gen_dir))):
                if not fn.endswith(".py"):
                    continue
                rel = f"{gen_dir}/{fn}"
                sub.read(os.path.join(project, rel), label=f"{sub.role} Read {rel}")
                src = peek(sub.rp, sub.role, os.path.join(project, rel))
                m = re.search(r"^([ \t]*)pytest\.fail\(f?\"TEST_INCOMPLETE:.*$", src, re.M)
                uid = re.search(r'^AC_UID = "([0-9a-f]+)"', src, re.M)
                body = test_bodies.get(uid.group(1) if uid else "", test_bodies.get("*"))
                if m and body:
                    new = "\n".join(m.group(1) + l if l else l for l in body.strip("\n").split("\n"))
                    edit(rel, m.group(0), new)
        # Git-diff derivation, as the agent text spells each command.
        base = re.search(r"^\s*baseline_head_sha:[ \t]*(\S*)", prompt, re.M)
        base = base.group(1) if base else ""
        diff_cmd = _codes(text, "Output Format", "git diff --name-only <baseline_head_sha>").replace(
            "<baseline_head_sha>", base)
        others_cmd = _codes(text, "Output Format", "git ls-files --others")
        cached_cmd = _codes(text, "Output Format", "git diff --cached")

        def names(cmd, what):
            c = sub.bash(cmd, f"List {what}", label=f"{sub.role} Bash {what}")
            return [l for l in c.response.get("stdout", "").split("\n") if l.strip()] if c.ok else []

        fallback = None
        if baseline_fallback and not base:  # "If `baseline_head_sha` is empty or absent ..., use `git status --porcelain`"
            sec = cmdtext.section(text, "Output Format")
            para = next((p for p in re.split(r"\n\s*\n", sec) if "baseline_head_sha` is empty or absent" in p), "")
            fallback = next((c for c in re.findall(r"`([^`\n]+)`", para) if c.startswith("git status")), None)
        if fallback:
            modified, untracked, staged_new = [], [], []
            for line in names(fallback, "changed files"):
                xy, path = line[:2], line[3:].strip()
                if xy != "??":
                    modified.append(path)
                    continue
                # a collapsed untracked directory lists the touched files under it
                untracked.extend([t for t in touched if t.startswith(path)] if path.endswith("/") else [path])
        else:
            modified = names(diff_cmd, "modified files")
            untracked = names(others_cmd, "untracked files")
            staged_new = names(cached_cmd, "staged new files")
        snap = re.search(r"^\s*baseline_dirty_snapshot:[ \t]*(.*)$", prompt, re.M)
        snap = snap.group(1).strip() if snap else ""
        if snap.startswith('"'):
            snap = json.loads(snap)
        dirty = [l[3:].strip() for l in snap.split("\n") if len(l) > 3]
        pre_dirty = lambda p: any(p == d or (d.endswith("/") and p.startswith(d)) for d in dirty)
        created = sorted({p for p in untracked + staged_new if not pre_dirty(p) and p in touched})
        provenance = {}
        for rel in touched:
            if rel in untracked and pre_dirty(rel):  # adoption cell: pre-existing untracked, modified here
                if rel not in modified:
                    modified.append(rel)
                provenance[rel] = {
                    "path": rel, "admission": "authenticated_preexisting_untracked_whole_file",
                    "pre_edit": {"sha256": hashlib.sha256(snapshots[rel].encode()).hexdigest(), "git_status": "??"},
                    "final": {"sha256": _sha256(os.path.join(project, rel)), "git_status": "??"}}
        dev_part = {"files_modified": sorted(set(modified)), "files_created": created}
        out = {"owned_edits": owned, "pre_edit_snapshots": snapshots, "dev": dev_part}
        if provenance:
            out["untracked_modified_provenance"] = provenance
        out.update(report_extra or {})
        return {"*": out}
    return work


# ---------------------------------------------------------------- qa

def qa(manifest_rel: str | None = None, e2e: dict | None = None, guard_respell=None, extra: dict | None = None):
    """QA final verification: Phase 5's per-task pytest and canonical manifest guard (manifest
    mode) as the agent text spells them when a per-task manifest is named, and the report content
    (e2e_enforcement, manifest_verification with the guard's verdict)."""

    def work(sub, brief, player):
        project, text = brief.project, player.tree.agent_text(player.role)
        content = {"qa": {}}
        if e2e:
            content["qa"]["e2e_enforcement"] = dict(e2e)
        man_rel = manifest_rel
        if man_rel is None:
            m = re.search(r"Per-task active test manifest:\s*(\S+)", brief.prompt)
            man_rel = m.group(1) if m else None
        if man_rel and os.path.isfile(os.path.join(project, man_rel)):
            active = json.loads(peek(sub.rp, sub.role, os.path.join(project, man_rel))).get("active_tests") or []
            gen_dir = os.path.dirname(man_rel)
            pytest_cmd = _codes(text, "Phase 5", "pytest tests/generated/<task_id>/").replace(
                "tests/generated/<task_id>/", gen_dir + "/")
            run = sub.bash(pytest_cmd, "Run the task's generated tests", label=f"{sub.role} Bash pytest generated")
            grep = sub.tool("Grep", {"pattern": "TEST_INCOMPLETE:", "path": os.path.join(project, gen_dir),
                                     "output_mode": "files_with_matches"}, label=f"{sub.role} Grep sentinel")
            sentinels = grep.response.get("filenames", []) if grep.ok else []
            mv = {"active_tests_count": len(active), "pytest_collected_ok": bool(active) and run.ok,
                  "pytest_failures": ([] if run.ok else [run.error[:400]]) + [f"TEST_INCOMPLETE in {s}" for s in sentinels]}
            guard = _codes(text, "Phase 5", "qa-manifest-guard.py", "( source").strip()
            cmd = f"printf '%s\\n' {shlex.quote(json.dumps(mv))} | {guard}"
            if guard_respell:
                cmd = guard_respell(cmd, "qa Phase 5 manifest guard")
            g = sub.bash(cmd, "Run the canonical manifest guard", label=f"{sub.role} Bash manifest guard")
            out = (g.response.get("stdout", "") if g.ok else g.error) or ""
            j = re.search(r"\{.*\}", out, re.S)
            try:
                gv = json.loads(j.group(0)) if j else {}
            except ValueError:
                gv = {}
            mv["guard_verdict"], mv["guard_reason"] = gv.get("verdict", "guard_unavailable"), gv.get("reason", out[-200:])
            content["qa"]["manifest_verification"] = mv
        if extra:
            from .schemagen import deep_merge
            content = deep_merge(content, extra)
        return {"*": content}
    return work
