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

import fnmatch
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
    manifest content, the global index the prompt names, and the report content. Where the agent
    file's manifest template carries a `skeleton` per entry, each skeleton goes there and no test
    file is written (dev writes it); else each is written as its file. The manifest's
    schema_version is the one the template spells."""

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
        manifest_rel = _prompt_value(prompt, "Per-task active manifest") or f"{gen_dir}/manifest.json"
        mtpl = player.tree.template(player.role, manifest_rel) or ""
        embed = '"skeleton"' in mtpl
        version = re.search(r'"schema_version":\s*"([^"]+)"', mtpl)
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
            if not embed:
                put(sub, os.path.join(project, rel), text, f"{sub.role} Write {rel}")
            tests.append(rel)
            active.append({"task_id": tid, "ac_id": ac["id"], "ac_uid": uid, "type": ac["type"], "file": rel,
                           "status": "active", "hook_check": ac.get("check", {})})
            if embed:
                active[-1]["skeleton"] = text
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
        return {manifest_rel: {"schema_version": version.group(1) if version else "1.1", "active_tests": active,
                               "archived_tests": []},
                report_rel: report}
    return work


# ---------------------------------------------------------------- dev

def dev(edits: list, test_bodies: dict | None = None, report_extra: dict | None = None, creates: list | None = None,
        produced: list | None = None, tools: list | None = None):
    """Apply `edits` [(rel, old, new)] (Read, then Edit), write each new file of `creates`
    [(rel, content)] (an existing one is Read, then edited in place), run each Bash command of
    `produced` [(command, rel)] that makes the file rel, write each generated test the per-task
    manifest gives a skeleton for and the disk lacks, replace each generated test's
    TEST_INCOMPLETE sentinel line with `test_bodies[ac_uid]`, run each Bash command of `tools` (a
    formatter, an installer: a command that names no file it changes) between two `git status`
    calls, record the owned-edits ledger and pre-edit snapshots, then declare the files as the
    agent text's file-list rule says: exactly the files this dev wrote, dev.files_created those
    that did not exist before the cycle, dev.files_modified the existing ones it changed. A file a
    Bash command made that the command does not name is first named with the rule's own example
    command; a tool's files (those `git status` shows changed after it and not before, outside the
    pipeline's own trees) are declared unnamed; a re-dispatch keeps the files its earlier round's
    report lists that still exist."""

    def work(sub, brief, player):
        project, prompt = brief.project, brief.prompt
        # The rule's paragraph, located through the extractor: a renamed or removed rule fails here.
        name_cmd = next(c for c in cmdtext.inline_codes(player.tree.agent_text(player.role), "Output Format",
                                                        "List exactly the files you wrote") if "<path>" in c)
        owned, snapshots, touched = {}, {}, []
        fresh = set()   # generated tests this dispatch wrote from the manifest's skeletons
        new = set()     # files this dispatch wrote that did not exist before its write

        def edit(rel, old, new_text):
            path = os.path.join(project, rel)
            sub.read(path, label=f"{sub.role} Read {rel}")
            before = peek(sub.rp, sub.role, path)
            snapshots.setdefault(rel, before)
            call = sub.edit(path, old, new_text, label=f"{sub.role} Edit {rel}")
            if call.ok:
                owned.setdefault(rel, []).append({"old": old, "new": new_text})
                touched.append(rel)

        for rel, old, new_text in edits:
            edit(rel, old, new_text)
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
            if not existed:
                new.add(rel)
        for command, rel in produced or []:
            path = os.path.join(project, rel)
            existed = os.path.exists(path)
            if not sub.bash(command, f"Produce {rel}", label=f"{sub.role} Bash produce {rel}").ok \
                    or not os.path.exists(path):
                continue
            if rel not in command and path not in command:  # the producing command does not name it
                sub.bash(name_cmd.replace("<path>", shlex.quote(rel)), f"Name {rel}", label=f"{sub.role} Bash name {rel}")
            touched.append(rel)
            if not existed:
                new.add(rel)
        gen = re.search(r"Generated tests \(when test-writer ran\):\s*(\S+?)/?\s", prompt)
        gen_dir = gen.group(1).rstrip("/") if gen else None
        man = re.search(r"per-task active manifest at\s+(\S+?\.json)", prompt)
        if test_bodies and man and os.path.isfile(os.path.join(project, man.group(1))):
            mpath = os.path.join(project, man.group(1))
            sub.read(mpath, label=f"{sub.role} Read {man.group(1)}")
            for e in json.loads(peek(sub.rp, sub.role, mpath)).get("active_tests") or []:
                rel = e.get("file")
                if e.get("skeleton") and rel and not os.path.exists(os.path.join(project, rel)):
                    call = put(sub, os.path.join(project, rel), e["skeleton"], f"{sub.role} Write {rel}")
                    if call is not None and call.ok:
                        snapshots.setdefault(rel, "")
                        fresh.add(rel)
                        new.add(rel)
                        touched.append(rel)
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
                    body = "\n".join(m.group(1) + l if l else l for l in body.strip("\n").split("\n"))
                    edit(rel, m.group(0), body)
        for command in tools or []:
            def status(when):
                call = sub.bash("git status --porcelain -uall", f"Status {when} the tool",
                                label=f"{sub.role} Bash git status {when} {command.split()[0]}")
                return {line[3:]: line[:2] for line in (call.response or {}).get("stdout", "").splitlines()}
            before = status("before")
            if sub.bash(command, "Run the tool", label=f"{sub.role} Bash tool {command.split()[0]}").ok:
                for rel, code in sorted(status("after").items()):
                    if rel not in before and not rel.startswith(("docs/dev/", ".claude/")):
                        touched.append(rel)
                        new |= {rel} if code == "??" else set()
        for rel in fresh:  # a file this dispatch created: one Write of its final content in the ledger
            owned[rel] = [{"old": "", "new": peek(sub.rp, sub.role, os.path.join(project, rel))}]
        # A re-dispatch of the task and lane: the files its earlier round's report (the artifact
        # this dispatch declares, already on disk) lists that still exist, in the list it put them in.
        prior, prior_prov = {"files_created": set(), "files_modified": set()}, {}
        for art in (brief.obligation or {}).get("artifacts") or []:
            path = os.path.join(project, art.get("path") or "")
            if art.get("kind") != "json" or not os.path.isfile(path):
                continue
            sub.read(path, label=f"{sub.role} Read {art['path']} (earlier round)")
            try:
                doc = json.loads(peek(sub.rp, sub.role, path))
            except ValueError:
                continue
            for key in prior:
                prior[key] |= {p for p in ((doc.get("dev") or {}).get(key) or [])
                               if isinstance(p, str) and os.path.exists(os.path.join(project, p))}
            prior_prov.update(doc.get("untracked_modified_provenance") or {})
        created = prior["files_created"] | new
        modified = (prior["files_modified"] | set(touched)) - created
        # Adoption cell: an existing file untracked at baseline (the dispatch's baseline_dirty_snapshot,
        # copied verbatim) that this cycle changed carries its provenance object.
        snap = re.search(r"^\s*baseline_dirty_snapshot:[ \t]*(.*)$", prompt, re.M)
        snap = snap.group(1).strip() if snap else ""
        if snap.startswith('"'):
            snap = json.loads(snap)
        untracked = [l[3:].strip() for l in snap.split("\n") if l[:3] == "?? "]
        provenance = {}
        for rel in sorted(modified):
            if rel in snapshots and any(rel == d or (d.endswith("/") and rel.startswith(d)) for d in untracked):
                provenance[rel] = {
                    "path": rel, "admission": "authenticated_preexisting_untracked_whole_file",
                    "pre_edit": {"sha256": hashlib.sha256(snapshots[rel].encode()).hexdigest(), "git_status": "??"},
                    "final": {"sha256": _sha256(os.path.join(project, rel)), "git_status": "??"}}
            elif rel in prior_prov and rel not in touched:  # adopted in an earlier round, unchanged since
                provenance[rel] = prior_prov[rel]
        dev_part = {"files_modified": sorted(modified), "files_created": sorted(created)}
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
            # the files the text has the sentinel grep take (its `*.py` scope, where it names one)
            scope = {"glob": "*.py"} if "`*.py`" in cmdtext.section(text, "Phase 5") else {}
            grep = sub.tool("Grep", dict({"pattern": "TEST_INCOMPLETE:", "path": os.path.join(project, gen_dir),
                                          "output_mode": "files_with_matches"}, **scope), label=f"{sub.role} Grep sentinel")
            sentinels = [f for f in (grep.response.get("filenames", []) if grep.ok else [])
                         if fnmatch.fnmatch(os.path.basename(f), scope.get("glob", "*"))]
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
