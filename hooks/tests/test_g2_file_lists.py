#!/usr/bin/env python3
"""P6 A3.a: G2 checks dev's declared file lists at dev's own stop against the
files Claude Code recorded the dev writing (hooks/subagentstop-artifact-
contract-enforce.py, _file_lists_errors).

W is P1b's write-set reader (command_span.write_set) on the stopping dev's
own transcript and on every earlier dev dispatch of its task id and lane (a
QA loop, a completion dispatch from another session); N is the paths its own
Bash commands name. D is dev.files_modified + dev.files_created. (a) each D
path is in W + N; (b) each W path git has a change for is in D.

A difference blocks dev's stop: exit 2 with the lines as a G2 finding. The
check only warned in the commit that introduced it, so each case also runs a
copy of the hook with FILE_LISTS_BLOCK set to False (that warning mode),
which prints the same lines after an `A3.a would block` stderr line and
changes no exit code; every clean case passes both. Transcripts are
synthetic, in the records Claude Code writes: the session's main transcript
holds each Agent dispatch, the subagent's own transcript its dispatch prompt
and tool calls, and its meta.json the dispatch's toolUseId.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import test_artifact_contract_enforce as base  # noqa: E402  (hooks/tests on sys.path)

TASK = "20261012-000000"
WARN = "A3.a would block"


@pytest.fixture(scope="module")
def warning(tmp_path_factory):
    """A copy of the hook tree whose A3.a decision constant is set to False
    (the warning mode)."""
    hook = base._l2_hook_tree(tmp_path_factory.mktemp("warning"))
    text = hook.read_text(encoding="utf-8")
    assert text.count("FILE_LISTS_BLOCK = True") == 1
    hook.write_text(text.replace("FILE_LISTS_BLOCK = True", "FILE_LISTS_BLOCK = False"), encoding="utf-8")
    return hook


def _git(project: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True, text=True).stdout


class Cycle:
    """A toy repository (gen.py, CLAUDE.md and src/app.py committed) and the
    transcript store of the sessions that dispatch devs into it."""

    def __init__(self, tmp_path: Path):
        self.project, self.home = tmp_path / "toyproj", tmp_path / "home"
        self.home.mkdir(parents=True)
        self.project.mkdir()
        _git(self.project, "init", "-q", "-b", "main")
        _git(self.project, "config", "user.email", "t@example.invalid")
        _git(self.project, "config", "user.name", "t")
        for rel, text in (("gen.py", "print('generated')\n"), ("CLAUDE.md", "# toy\n"), ("src/app.py", "x = 1\n")):
            base._write(self.project / rel, text)
        _git(self.project, "add", ".")
        _git(self.project, "commit", "-q", "-m", "seed")
        self.store = self.home / ".claude" / "projects" / base._project_slug(self.project)
        self.at = datetime.now(timezone.utc) - timedelta(minutes=30)

    def path(self, rel: str) -> str:
        return str(self.project / rel)

    def dispatch(self, session: str, agent_id: str, calls=(), task: str = TASK, lane=None, lane_set=None,
                 transcript: bool = True) -> dict:
        """One dev dispatch: the Agent call in the session's main transcript,
        the subagent's transcript (prompt, then its own tool calls) and meta."""
        self.at += timedelta(minutes=1)
        task_id = f"{task}-{lane}" if lane else task
        doc = {"task_id": task_id, "role": "dev", "pipeline": "dev",
               "profile": "fanout-lane" if lane else "singular", "dispatched_at": self.at.isoformat(),
               "artifacts": [{"kind": "json", "path": f"docs/dev/dev-report-{task_id}.json",
                              "schema": "dev-report.v2", "identity": {"task_id": task_id}}]}
        if lane:
            doc.update(lane=lane, lane_set=lane_set)
        prompt = f'You are the dev subagent.\n<obligation v="1">\n{json.dumps(doc, indent=2)}\n</obligation>'
        use_id = f"toolu_dispatch_{agent_id}"
        record = {"type": "assistant", "cwd": str(self.project), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": use_id, "name": "Agent",
             "input": {"subagent_type": "dev", "description": "dev", "prompt": prompt,
                       "run_in_background": False}}]}}
        self.store.mkdir(parents=True, exist_ok=True)
        with (self.store / f"{session}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        subagents = self.store / session / "subagents"
        subagents.mkdir(parents=True, exist_ok=True)
        (subagents / f"agent-{agent_id}.meta.json").write_text(
            json.dumps({"agentType": "dev", "toolUseId": use_id}), encoding="utf-8")
        own = subagents / f"agent-{agent_id}.jsonl"
        if transcript:
            records = [{"type": "user", "isSidechain": True, "cwd": str(self.project),
                        "message": {"role": "user", "content": prompt}}]
            records += base._tool_records(self.project, calls)
            own.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return {"session": session, "agent_id": agent_id, "task": task_id, "lane": lane, "lane_set": lane_set,
                "report": f"docs/dev/dev-report-{task_id}.json", "transcript": str(own)}

    def stop(self, d: dict, modified, created, hook=None) -> subprocess.CompletedProcess:
        """dev writes its schema-valid report with these lists and stops."""
        report = base._l2_dev_report(d["task"], lane=d["lane"], lane_set=d["lane_set"])
        report["owned_edits"], report["pre_edit_snapshots"] = {}, {}
        report["dev"].update(files_modified=list(modified), files_created=list(created))
        base._write(self.project / d["report"], report)
        return base._run_hook(self.project, self.home, d["agent_id"], session_id=d["session"],
                              stopgate_mode="block", hook_path=hook,
                              extra_payload={"agent_type": "dev", "agent_transcript_path": d["transcript"]})


def _lines(proc) -> dict:
    """The A3.a finding's lines by their label."""
    found = {}
    for line in proc.stderr.splitlines():
        m = re.match(r"\s+(declared but not written by this dev|written but not declared|"
                     r"set dev\.files_modified and dev\.files_created to exactly|unreadable[^:]*): (.*)$", line)
        if m:
            found[m.group(1).split(",")[0]] = m.group(2)
        m = re.match(r"\s+a file your own Bash produced counts once one of your Bash commands names it "
                     r"\(for example `ls -l <path>`\): (.*)$", line)
        if m:
            found["fix"] = m.group(1)
    return found


def _warned(proc, report: str, not_written: str, undeclared: str, expected: str) -> dict:
    """Warning mode: exit 0, one `A3.a would block` line naming the lists."""
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.count(WARN) == 1 and f"{WARN}: {report}: file_lists_differ" in proc.stderr, proc.stderr
    lines = _lines(proc)
    assert lines["declared but not written by this dev"] == not_written, proc.stderr
    assert lines["written but not declared"] == undeclared, proc.stderr
    assert lines["set dev.files_modified and dev.files_created to exactly"] == expected, proc.stderr
    assert "fail" not in proc.stderr.split(WARN, 1)[1].lower(), proc.stderr  # a repair step, never a failure
    return lines


def _blocked(proc, report: str, not_written: str, undeclared: str, expected: str) -> dict:
    """The hook: the same lines as a G2 finding of this stop, exit 2."""
    assert proc.returncode == 2, proc.stderr
    assert WARN not in proc.stderr and f"  - {report}: file_lists_differ" in proc.stderr, proc.stderr
    lines = _lines(proc)
    assert lines["declared but not written by this dev"] == not_written, proc.stderr
    assert lines["written but not declared"] == undeclared, proc.stderr
    assert lines["set dev.files_modified and dev.files_created to exactly"] == expected, proc.stderr
    return lines


def _clean(proc) -> None:
    assert proc.returncode == 0, proc.stderr
    assert WARN not in proc.stderr and "file_lists_differ" not in proc.stderr, proc.stderr


def _t6(c: Cycle, bash="python3 gen.py > generated.txt"):
    """A9's T6 dev: Reads its sentinel, Writes src/new.py, runs the generator
    (the driver writes its output); doc-sync and another session leave files."""
    sentinel = c.project / ".claude" / "dev-registry" / f"dev-{TASK}" / "dev.json"
    base._write(sentinel, {"agent_type": "dev"})
    base._write(c.project / "src" / "new.py", "def new():\n    return 1\n")
    base._write(c.project / "generated.txt", "generated\n")
    base._write(c.project / "CLAUDE.md", "# toy\n\n- src/new.py\n")      # doc-sync, a PostToolUse hook
    base._write(c.project / "src" / "INDEX.md", "# src\n")              # doc-sync
    base._write(c.project / "src" / "README.md", "# src\n")             # doc-sync
    base._write(c.project / "scratch.txt", "another session's\n")       # another session
    return [("Read", {"file_path": str(sentinel)}, True),
            ("Write", {"file_path": c.path("src/new.py"), "content": "def new():\n    return 1\n"}, True),
            ("Bash", {"command": bash, "description": "generate"}, True)]


def _git_derived(c: Cycle) -> tuple:
    """origin/master dev.md's derivation: git diff --name-only <baseline>, and
    git ls-files --others --exclude-standard plus staged additions."""
    head = _git(c.project, "rev-parse", "HEAD").strip()
    modified = _git(c.project, "diff", "--name-only", head).split()
    created = sorted(set(_git(c.project, "ls-files", "--others", "--exclude-standard").split())
                     | set(_git(c.project, "diff", "--cached", "--name-only", "--diff-filter=A").split()))
    return modified, created


# A9 / A10: the T6 replay ---------------------------------------------------


def test_a9_t6_git_derived_lists_warn_with_the_expected_lists(tmp_path, warning):
    c = Cycle(tmp_path)
    d = c.dispatch("session-t6", "agent-t6dev", _t6(c))
    modified, created = _git_derived(c)
    assert modified == ["CLAUDE.md"]
    assert created == [f".claude/dev-registry/dev-{TASK}/dev.json", "generated.txt", "scratch.txt",
                       "src/INDEX.md", "src/README.md", "src/new.py"]
    not_written = f".claude/dev-registry/dev-{TASK}/dev.json, CLAUDE.md, scratch.txt, src/INDEX.md, src/README.md"
    expected = "files_modified: []; files_created: generated.txt, src/new.py"
    _blocked(c.stop(d, modified, created), d["report"], not_written, "(none)", expected)
    _warned(c.stop(d, modified, created, warning), d["report"], not_written, "(none)", expected)
    for hook in (None, warning):
        _clean(c.stop(d, [], ["src/new.py", "generated.txt"], hook))
    assert not list((c.project / "docs" / "dev").glob("journal-view-*.json"))


def test_a10_generator_output_unnamed_until_dev_names_it(tmp_path, warning):
    c = Cycle(tmp_path)
    calls = _t6(c, bash="python3 gen.py")
    d = c.dispatch("session-gen", "agent-gendev", calls)
    args = (d["report"], "generated.txt", "(none)", "files_modified: []; files_created: src/new.py")
    blocked = _blocked(c.stop(d, [], ["src/new.py", "generated.txt"]), *args)
    warned = _warned(c.stop(d, [], ["src/new.py", "generated.txt"], warning), *args)
    for lines in (blocked, warned):
        assert lines["fix"] == "name it and keep it listed", lines
    named = c.dispatch("session-gen2", "agent-gendev2", calls + [("Bash", {"command": "ls -l generated.txt"}, True)])
    for hook in (None, warning):
        _clean(c.stop(named, [], ["src/new.py", "generated.txt"], hook))


def test_a10_written_file_omitted(tmp_path, warning):
    c = Cycle(tmp_path)
    d = c.dispatch("session-omit", "agent-omitdev", _t6(c))
    args = (d["report"], "(none)", "src/new.py", "files_modified: []; files_created: generated.txt, src/new.py")
    _blocked(c.stop(d, [], ["generated.txt"]), *args)
    _warned(c.stop(d, [], ["generated.txt"], warning), *args)


def test_a10_file_another_sessions_agent_wrote(tmp_path, warning):
    c = Cycle(tmp_path)
    base._write(c.project / "peer.py", "peer = 1\n")
    c.dispatch("session-peer", "agent-peerdev", [("Write", {"file_path": c.path("peer.py"), "content": "x"}, True)],
               task="20261012-111111")
    d = c.dispatch("session-own", "agent-owndev", _t6(c))
    args = (d["report"], "peer.py", "(none)", "files_modified: []; files_created: generated.txt, src/new.py")
    _blocked(c.stop(d, [], ["src/new.py", "generated.txt", "peer.py"]), *args)
    _warned(c.stop(d, [], ["src/new.py", "generated.txt", "peer.py"], warning), *args)


def test_a10_scratch_written_then_removed_and_refused_write(tmp_path, warning):
    """notes.tmp Written then removed by Bash (gone from disk and HEAD), and a
    Write a hook refused (is_error: nothing written): neither is declared."""
    c = Cycle(tmp_path)
    calls = _t6(c) + [("Write", {"file_path": c.path("notes.tmp"), "content": "n"}, True),
                      ("Bash", {"command": "rm notes.tmp"}, True),
                      ("Write", {"file_path": c.path("src/denied.py"), "content": "d"}, False)]
    base._write(c.project / "src" / "denied.py", "a peer's file\n")
    d = c.dispatch("session-tmp", "agent-tmpdev", calls)
    for hook in (None, warning):
        _clean(c.stop(d, [], ["src/new.py", "generated.txt"], hook))


@pytest.mark.parametrize("second_session", [False, True], ids=["qa_loop", "completion_dispatch"])
def test_a10_redispatch_inherits_the_cycles_writes(tmp_path, warning, second_session):
    """QA failed; a second dev dispatch of the task and lane (in the same
    session, or a /close span's completion dispatch in a new one) writes
    src/extra.py: the cycle's earlier writes are its own."""
    c = Cycle(tmp_path)
    c.dispatch("session-a", "agent-round1", _t6(c))
    base._write(c.project / "src" / "extra.py", "extra = 1\n")
    d = c.dispatch("session-b" if second_session else "session-a", "agent-round2",
                   [("Write", {"file_path": c.path("src/extra.py"), "content": "extra = 1\n"}, True)])
    for hook in (None, warning):
        _clean(c.stop(d, [], ["src/new.py", "generated.txt", "src/extra.py"], hook))
    args = (d["report"], "(none)", "src/new.py",
            "files_modified: []; files_created: generated.txt, src/extra.py, src/new.py")
    _blocked(c.stop(d, [], ["src/extra.py", "generated.txt"]), *args)
    _warned(c.stop(d, [], ["src/extra.py", "generated.txt"], warning), *args)


def test_a10_redev_mints_a_new_task_and_inherits_nothing(tmp_path, warning):
    c = Cycle(tmp_path)
    c.dispatch("session-a", "agent-old", _t6(c))
    d = c.dispatch("session-a", "agent-redev", [("Write", {"file_path": c.path("src/app.py"), "content": "x = 2\n"},
                                                 True)], task="20261012-020000")
    base._write(c.project / "src" / "app.py", "x = 2\n")
    for hook in (None, warning):
        _clean(c.stop(d, ["src/app.py"], [], hook))
    args = (d["report"], "src/new.py", "(none)", "files_modified: src/app.py; files_created: []")
    _blocked(c.stop(d, ["src/app.py"], ["src/new.py"]), *args)
    _warned(c.stop(d, ["src/app.py"], ["src/new.py"], warning), *args)


def test_a10_unreadable_predecessor_is_named_and_its_files_need_naming(tmp_path, warning):
    c = Cycle(tmp_path)
    _t6(c)
    c.dispatch("session-a", "agent-lost", transcript=False)
    d = c.dispatch("session-a", "agent-round2", [("Write", {"file_path": c.path("src/new.py"), "content": "y"}, True)])
    lines = _blocked(c.stop(d, [], ["src/new.py", "generated.txt"]), d["report"], "generated.txt", "(none)",
                     "files_modified: []; files_created: generated.txt, src/new.py")
    assert "toolu_dispatch_agent-lost in session session-a" in lines["unreadable"]
    _warned(c.stop(d, [], ["src/new.py", "generated.txt"], warning), d["report"], "generated.txt", "(none)",
            "files_modified: []; files_created: generated.txt, src/new.py")
    named = c.dispatch("session-a", "agent-round3", [("Bash", {"command": "ls -l generated.txt"}, True)])
    for hook in (None, warning):
        _clean(c.stop(named, [], ["src/new.py", "generated.txt"], hook))


def test_a10_fanout_lanes_each_against_their_own_writes(tmp_path, warning):
    c = Cycle(tmp_path)
    roster = ["l1", "l2"]
    base._write(c.project / "src" / "a.py", "a\n")
    base._write(c.project / "src" / "b.py", "b\n")
    la = c.dispatch("session-f", "agent-lane1", [("Write", {"file_path": c.path("src/a.py"), "content": "a\n"}, True)],
                    lane="l1", lane_set=roster)
    lb = c.dispatch("session-f", "agent-lane2", [("Write", {"file_path": c.path("src/b.py"), "content": "b\n"}, True)],
                    lane="l2", lane_set=roster)
    for hook in (None, warning):
        _clean(c.stop(la, [], ["src/a.py"], hook))
        _clean(c.stop(lb, [], ["src/b.py"], hook))
    args = (la["report"], "src/b.py", "(none)", "files_modified: []; files_created: src/a.py")
    _blocked(c.stop(la, [], ["src/a.py", "src/b.py"]), *args)
    _warned(c.stop(la, [], ["src/a.py", "src/b.py"], warning), *args)


# Path canonicalisation and the written-set edge cases ----------------------


def test_a10_absolute_in_repo_path_compares_as_the_relative_one(tmp_path, warning):
    c = Cycle(tmp_path)
    base._write(c.project / "src" / "app.py", "x = 3\n")
    d = c.dispatch("session-abs", "agent-absdev",
                   [("Edit", {"file_path": c.path("src/app.py"), "old_string": "1", "new_string": "3"}, True)])
    for hook in (None, warning):
        _clean(c.stop(d, [c.path("src/app.py")], [], hook))
        _clean(c.stop(d, ["./src/../src/app.py"], [], hook))


def test_written_then_deleted_tracked_file_is_declared(tmp_path, warning):
    """A tracked file dev Edited and then removed with `git rm` is a deletion
    that must land: declared (git rm names it) it passes; undeclared, the
    expected lists put it in files_modified."""
    c = Cycle(tmp_path)
    calls = [("Edit", {"file_path": c.path("src/app.py"), "old_string": "1", "new_string": "2"}, True),
             ("Bash", {"command": "git rm -q src/app.py"}, True)]
    d = c.dispatch("session-rm", "agent-rmdev", calls)
    _git(c.project, "rm", "-q", "src/app.py")
    for hook in (None, warning):
        _clean(c.stop(d, ["src/app.py"], [], hook))
    args = (d["report"], "(none)", "src/app.py", "files_modified: src/app.py; files_created: []")
    _blocked(c.stop(d, [], []), *args)
    _warned(c.stop(d, [], [], warning), *args)


def test_write_leaving_bytes_identical_needs_no_declaration(tmp_path, warning):
    """A Write whose bytes equal HEAD leaves git nothing to land: it need not
    be declared, and declaring it passes too (it was written)."""
    c = Cycle(tmp_path)
    d = c.dispatch("session-same", "agent-samedev",
                   [("Write", {"file_path": c.path("src/app.py"), "content": "x = 1\n"}, True)])
    for hook in (None, warning):
        _clean(c.stop(d, [], [], hook))
        _clean(c.stop(d, ["src/app.py"], [], hook))


def test_path_in_both_lists_is_one_declared_path(tmp_path, warning):
    c = Cycle(tmp_path)
    d = c.dispatch("session-both", "agent-bothdev", _t6(c))
    for hook in (None, warning):
        _clean(c.stop(d, ["src/new.py"], ["src/new.py", "generated.txt"], hook))


def test_excluded_trees_and_paths_outside_every_work_tree(tmp_path, warning):
    """docs/dev/**, .claude/dev-registry/** and .claude/scratch/** of the
    repository, and a file outside every git work tree, need no declaration;
    a write into another repository does, by its absolute path. Declared,
    A3.a is satisfied and /commit's trial plan has the say (this repository
    is not in its supported set); the write removed, nothing is left to
    declare."""
    c = Cycle(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    outside = tmp_path / "loose" / "note.txt"
    files = {c.path("docs/dev/notes.md"): "n", c.path(".claude/dev-registry/x.json"): "{}",
             c.path(".claude/scratch/s.txt"): "s", str(outside): "o", str(other / "lib.py"): "l"}
    for path, text in files.items():
        base._write(Path(path), text)
    d = c.dispatch("session-ex", "agent-exdev",
                   [("Write", {"file_path": path, "content": text}, True) for path, text in files.items()])
    lib = str((other / "lib.py").resolve())
    args = (d["report"], "(none)", lib, f"files_modified: []; files_created: {lib}")
    _blocked(c.stop(d, [], []), *args)
    _warned(c.stop(d, [], [], warning), *args)
    for hook in (None, warning):
        proc = c.stop(d, [], [str(other / "lib.py")], hook)
        assert "file_lists_differ" not in proc.stderr and WARN not in proc.stderr, proc.stderr
        assert "outside the supported repository set" in proc.stderr, proc.stderr
    (other / "lib.py").unlink()
    for hook in (None, warning):
        _clean(c.stop(d, [], [], hook))


def test_no_journal_view_write_is_left_in_g2():
    text = base.HOOK_PATH.read_text(encoding="utf-8")
    assert text.count("journal-view") == 0
    assert text.count("FILE_LISTS_BLOCK = True") == 1  # promoted; the warning-mode copy sets it to False


# R6 / R7: the prose G2's check replaces -------------------------------------

DEV_MD = base.REPO_ROOT / "agents" / "dev.md"
QA_MD = base.REPO_ROOT / "agents" / "qa.md"


def test_dev_md_lists_exactly_the_files_it_wrote():
    """agents/dev.md: one rule in place of the git derivation, its non-disjoint
    note, unborn-repo fallback and baseline_dirty_paths subtraction; the
    non-null rule, the adoption contract object, observed_preexisting, the
    baseline fields (QA no longer their reader) and the ledger stay."""
    text = DEV_MD.read_text(encoding="utf-8")
    assert len(re.findall(r"git ls-files --others|Git-diff derivation", text)) == 0
    for gone in ("baseline_dirty_paths", "not required to be disjoint", "skip git-diff derivation",
                 "`commit.sh` closure detection", "git diff --cached", "derive it from `git status --porcelain`",
                 "consumers (QA, changelog-analyst)", "QA and changelog-analyst read this field"):
        assert gone not in text, gone
    rule = re.search(r"^\*\*List exactly the files you wrote\*\* \(MANDATORY\): (.*)$", text, re.M)
    assert rule, "the file-list rule"
    for phrase in ("`dev.files_created` = the files you created that did not exist before the cycle",
                   "`dev.files_modified` = the existing files you changed or deleted",
                   "counts only if one of your Bash commands names it", "(for example `ls -l <path>`)",
                   "doc-sync's `CLAUDE.md`, `INDEX.md`, `README.md`", "`.claude/dev-registry/`",
                   "write scratch under `.claude/scratch/`",
                   "keeps the files earlier rounds of the cycle wrote that still exist",
                   "Your own SubagentStop checks these lists against what Claude Code recorded you writing"):
        assert phrase in rule.group(1), phrase
    assert "MUST be non-null lists" in text
    assert "`untracked_modified_provenance[<path>]` contract object" in text
    for kept in ("**`observed_preexisting[]`**", "**`baseline_head_sha`** MUST appear",
                 "**`baseline_dirty_snapshot`** MUST also appear", "## Owned-edits ledger + pre-edit snapshot"):
        assert kept in text, kept


def test_dev_md_bash_naming_step_is_already_allowed():
    """The one Bash command the new rule asks for is covered by the tracked
    settings.json allow list (no permission change)."""
    allow = json.loads((base.REPO_ROOT / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
    assert "Bash(ls:*)" in allow


def test_qa_md_step5_keeps_no_provenance_check():
    text = QA_MD.read_text(encoding="utf-8")
    assert len(re.findall(r"dev_provenance_violation|files_modified_underreport_violation|"
                          r"files_created_provenance_violation", text)) == 0
    step5 = text.split("### Step 5: Regression Testing", 1)[1].split("### Step 6:", 1)[0]
    for gone in ("Provenance check", "Adoption-cell carve-out", "Reverse (under-reporting) check",
                 "Also check `dev.files_created` for provenance", "baseline_dirty"):
        assert gone not in step5, gone
    assert step5.lstrip().startswith("**Check related functionality not broken**")
    assert "`tasks_completed[].files_modified`" in text and "`tasks_completed[].files_created`" in text
