"""Unit tests of the derivation rules behind rule (1) (one producer, the declared role writes a
declared artifact) and rule (7) (a list that repeats a declaration).

Each test builds a small harness-shaped tree and, where the rule needs one, a hand-written replay
reduced to relation events, and runs the check's derivation on them (test_check.py's harness), so
each rule that keeps a false violation out, or a real one in, is pinned on its own, with its
counter-case beside it.
"""

from __future__ import annotations

import json

from tests.artifact_graph import check as C
from tests.artifact_graph import derive
from tests.artifact_graph.test_check import check, make_tree, rules_on


def _run(events: list, manifest=(), name: str = "fake") -> C.Run:
    """A replay reduced to its relation events (comp, actor, op, pattern, raw[, origin, event])."""
    r = C.Run(name, "shipped", "")
    r.events = []
    for i, ev in enumerate(events):
        comp, actor, op, pat, raw = ev[:5]
        origin = ev[5] if len(ev) > 5 else comp
        r.events.append({"comp": comp, "origin": origin, "actor": actor, "op": op, "pattern": pat,
                         "event": ev[6] if len(ev) > 6 else i + 1, "bulk": False, "raw": raw})
    r.env = {"CLAUDE_STATE_DIR": "/sbx/state"}
    r.manifest = set(manifest)
    return r


def _derive(root, runs):
    st = derive(root)
    m = C.derive(str(root), st, runs)
    return m, C.violations(m, st.records)


def _template(role: str, path: str, schema: str = "") -> str:
    art = {"kind": "json", "path": path}
    if schema:
        art["schema"] = schema
    return ("# /x\n\n"
            '<obligation v="1">\n'
            + json.dumps({"task_id": "<TASK_ID>", "role": role, "pipeline": "x", "artifacts": [art]})
            + "\n</obligation>\n")


# ------------------------------------------------------------------ rule (1): the declared role

def test_a_placeholder_role_is_the_role_the_artifacts_name_holds(tmp_path):
    """One template dispatches every specialist (role="<specialist.type>", path
    .../<specialist.type>-report.json): each report it matches is declared for the role its own
    name holds, so the architect writing architect-report.json is its declared role."""
    assert C._bound_role("<specialist.type>", "docs/o/<session_id>/<specialist.type>-report.json",
                         "<proj>/docs/o/<sid>/architect-report.json") == "architect"
    # a key whose name holds no value for the placeholder, and a role no placeholder, stay as declared
    assert C._bound_role("<specialist.type>", "docs/o/<session_id>/<specialist.type>-report.json",
                         "<proj>/docs/o/<sid>/<*>-report.json") == "<specialist.type>"
    assert C._bound_role("dev", "docs/dev/dev-report-<x>.json", "<proj>/docs/dev/dev-report-<ts>.json") == "dev"
    root = make_tree(tmp_path, {
        "commands/x.md": _template("<specialist.type>", "docs/o/<session_id>/<specialist.type>-report.json"),
        "agents/architect.md": "---\nname: architect\n---\n",
    })
    run = _run([("agent:architect", "agent:architect", "create", "<project>/docs/o/<sid>/architect-report.json",
                 "/p/docs/o/s1/architect-report.json"),
                ("agent:user", "agent:user", "create", "<project>/docs/o/<sid>/user-report.json",
                 "/p/docs/o/s1/user-report.json")])
    m, vs = _derive(root, [run])
    a = m.artifacts["<proj>/docs/o/<sid>/architect-report.json"]
    assert {d["role"] for d in a.declared} == {"architect"}
    assert not [v for v in vs if v.rule.startswith("1-")]


def test_a_script_the_declared_roles_call_runs_is_that_roles_write_path(tmp_path):
    """The fan-out's aggregate (written by the hook the lane's dev report sets off) and a QA
    section appended by the helper QA runs: a script whose every write of a declared artifact ran
    inside the declared role's call is that role's write path, not a second producer; the same
    script writing it from the main agent's call is one."""
    root = make_tree(tmp_path, {"commands/x.md": _template("dev", "docs/dev/dev-report-<TASK_ID>.json"),
                                "agents/dev.md": "---\nname: dev\n---\n"})
    key = "<proj>/docs/dev/dev-report-<ts>.json"
    single = _run([("agent:dev", "agent:dev", "create", "<project>/docs/dev/dev-report-<ts>.json", "/p/1.json")],
                  name="single")
    fanout = _run([("scripts/agg.py", "agent:dev", "create", "<project>/docs/dev/dev-report-<ts>.json", "/p/2.json",
                    "hooks/watch.py")], name="fanout")
    m, vs = _derive(root, [single, fanout])
    assert sorted(m.artifacts[key].producers()) == ["agent:dev", "scripts/agg.py"]
    assert not rules_on(vs, key) & {"1-producers", "1-declared-role"}
    by_main = _run([("scripts/agg.py", "main", "create", "<project>/docs/dev/dev-report-<ts>.json", "/p/3.json",
                     "hooks/watch.py")], name="main")
    m, vs = _derive(root, [single, by_main])
    assert {"1-producers", "1-declared-role"} <= rules_on(vs, key)


def test_a_project_file_only_the_roles_edit_is_the_tasks_work(tmp_path):
    """A file of the user's project that was there at replay start and that only the roles' own
    tool calls write is the task's work product, whichever role the command gives the work (dev
    under /dev, the main agent under /do): one producer. A file the run created is not the user's,
    and two roles writing it are two producers."""
    root = make_tree(tmp_path, {})
    key = "<proj>/pkg/mod.py"
    by_dev = _run([("agent:dev", "agent:dev", "write", "<project>/pkg/mod.py", "/p/pkg/mod.py"),
                   ("hooks/post.py", "agent:dev", "read", "<project>/pkg/mod.py", "/p/pkg/mod.py")],
                  manifest=["/p/pkg/mod.py"], name="dev")
    by_main = _run([("main", "main", "write", "<project>/pkg/mod.py", "/p/pkg/mod.py"),
                    ("hooks/post.py", "main", "read", "<project>/pkg/mod.py", "/p/pkg/mod.py")],
                   manifest=["/p/pkg/mod.py"], name="do")
    m, vs = _derive(root, [by_dev, by_main])
    assert m.artifacts[key].producers() == ["agent:dev", "main"]
    assert "1-producers" not in rules_on(vs, key)
    made_dev = _run([("agent:dev", "agent:dev", "create", "<project>/pkg/mod.py", "/p/pkg/mod.py"),
                     ("hooks/post.py", "agent:dev", "read", "<project>/pkg/mod.py", "/p/pkg/mod.py")], name="dev")
    made_main = _run([("main", "main", "write", "<project>/pkg/mod.py", "/p/pkg/mod.py"),
                      ("hooks/post.py", "main", "read", "<project>/pkg/mod.py", "/p/pkg/mod.py")], name="do")
    m, vs = _derive(root, [made_dev, made_main])
    assert "1-producers" in rules_on(vs, key)


# ------------------------------------------------------------------ rule (1): who writes

def test_a_named_family_writer_writes_the_members_its_code_makes(tmp_path):
    """A writer of report-<id>.json whose id the static half cannot bind is each member of the
    family, unless the replays show it writing some: those are its (the fan-out's aggregate),
    and a lane's report beside them stays its lane's."""
    root = make_tree(tmp_path, {
        "scripts/agg.py": '''
            import os, sys
            def canonical_id(argv):
                return argv[1].rsplit("-", 1)[0]
            open(os.path.join(os.getcwd(), "docs", "dev", "dev-report-" + canonical_id(sys.argv) + ".json"),
                 "w").write("{}")
        ''',
        "commands/x.md": _template("dev", "docs/dev/dev-report-<TASK_ID>-<LANE>.json"),
        "agents/dev.md": "---\nname: dev\n---\n",
    })
    assert any(r["kind"] == "relation" and r["op"] == "write" and "<*>" in r["path"]
               for r in derive(root).records if r.get("component") == "scripts/agg.py")
    run = _run([("scripts/agg.py", "", "create", "<project>/docs/dev/dev-report-<ts>.json", "/p/a.json"),
                ("agent:dev", "agent:dev", "create", "<project>/docs/dev/dev-report-<ts>-<lane>.json", "/p/b.json")])
    m, vs = _derive(root, [run])
    assert m.artifacts["<proj>/docs/dev/dev-report-<ts>-<lane>.json"].producers() == ["agent:dev"]
    assert "scripts/agg.py" in m.artifacts["<proj>/docs/dev/dev-report-<ts>.json"].producers()


def test_a_writer_reached_through_a_library_or_a_load_by_path_is_one_producer(tmp_path):
    """A hook process that writes a file through code it loads (a library it imports, which loads
    the writer script by its file name; a shell library sourced through a variable holding its
    path) is that writer, not a producer of its own."""
    root = make_tree(tmp_path, {
        "scripts/sealer.py": '''
            import os
            def seal():
                open(os.path.join(os.environ.get("CLAUDE_HOME", os.path.expanduser("~/.claude")),
                                  "seals", "log.jsonl"), "a").write("{}")
            if __name__ == "__main__":
                seal()
        ''',
        "hooks/lib/journal.py": '''
            import importlib.util
            from pathlib import Path
            def trigger():
                path = Path(__file__).resolve().parent.parent.parent / "scripts" / "sealer.py"
                spec = importlib.util.spec_from_file_location("sealer", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.seal()
        ''',
        "hooks/post.py": "from lib.journal import trigger\ntrigger()\n",
        "hooks/lib/core.sh": '''
            core_log() { printf '%s\\n' "$1" >> "${CLAUDE_HOME:-$HOME/.claude}/logs/core.log"; }
        ''',
        "hooks/guard.sh": '''
            g() {
              local _lib="${_dir}/lib/core.sh"
              . "$_lib"
              core_log x
            }
            g
        ''',
        "hooks/other.sh": "echo nothing\n",
    })
    run = _run([("hooks/post.py", "main", "write", "<harness>/seals/log.jsonl", "/h/seals/log.jsonl"),
                ("hooks/guard.sh", "main", "write", "<harness>/logs/core.log", "/h/logs/core.log")])
    m, vs = _derive(root, [run])
    assert m.artifacts["<harness>/seals/log.jsonl"].producers() == ["scripts/sealer.py"]
    assert m.artifacts["<harness>/logs/core.log"].producers() == ["hooks/lib/core.sh"]
    assert not m.ctx._loads("hooks/other.sh", "hooks/lib/core.sh")


def test_a_temp_file_its_minting_run_alone_touched_is_its_scratch(tmp_path):
    """A name a temp-name generator minted is known only to the run that minted it: a file under
    such a name only that run touched is its private scratch, removed or not (a run stopped before
    its cleanup), so two runs that each leave one are no two producers of one artifact. A minted
    file another run reads is not scratch."""
    root = make_tree(tmp_path, {})
    run = _run([("hooks/a.sh", "agent:qa", "create", "/tmp/guard-<rand>", "/tmp/guard-k3j9x2", "hooks/a.sh", 1),
                ("scripts/c.sh", "", "create", "/tmp/guard-<rand>", "/tmp/guard-q8w7e6", "scripts/c.sh", 2)])
    m, vs = _derive(root, [run])
    assert "/tmp/guard-<rand>" not in m.artifacts
    shared = _run([("hooks/a.sh", "agent:qa", "create", "/tmp/guard-<rand>", "/tmp/guard-k3j9x2", "hooks/a.sh", 1),
                   ("hooks/b.py", "agent:qa", "read", "/tmp/guard-<rand>", "/tmp/guard-k3j9x2", "hooks/b.py", 2)])
    m, vs = _derive(root, [shared])
    assert "/tmp/guard-<rand>" in m.artifacts


def test_an_interpreter_reached_through_a_parent_segment_is_no_component(tmp_path):
    """`$DIR/../venv/bin/python3 -I $DIR/../hooks/lib/w.py` runs w.py: the component is the script
    the venv's interpreter runs, by its normalized path, never the interpreter."""
    from tests.replay import trace
    out = tmp_path / "out"
    out.mkdir()
    lay = {"harness": "/sbx/hm/.claude", "project": "/sbx/proj", "origin": "/sbx/origin", "state": "/sbx/state",
           "home": "/sbx/hm", "sb": "/sbx", "markers": "/sbx/markers", "temp_dirs": ["/sbx/tmp"], "scratch": []}
    (out / "ids.json").write_text(json.dumps({"layout": lay, "ids": {}, "window": [0, None]}))
    (out / "markers.jsonl").write_text("")
    h = "/sbx/hm/.claude"
    raw = tmp_path / "raw.txt"
    raw.write_text(
        f'100 execve("{h}/scripts/../venv/bin/python3", ["{h}/scripts/../venv/bin/python3", "-I", '
        f'"{h}/scripts/../hooks/lib/w.py", "write-state"], 0x7ffd /* 9 vars */) = 0\n'
        '100 openat(AT_FDCWD</>, "/sbx/proj/.claude/state-1.json", O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC, 0644)'
        ' = 3</sbx/proj/.claude/state-1.json>\n'
        '100 +++ exited with 0 +++\n')
    trace.parse(str(raw), str(out))
    rels = (out / "relations.tsv").read_text()
    assert "hooks/lib/w.py\tcreate\t<project>/.claude/state-1.json" in rels
    assert "venv" not in rels


# ------------------------------------------------------------------ rule (7)

def test_an_enum_copy_is_a_literal_in_code_that_handles_the_schemas_documents(tmp_path):
    """A literal holding a schema enum's values copies it where the code names the schema or the
    artifact family it declares (the schema id's stem); code that names neither has a vocabulary
    of its own that shares words with the enum (a status rank)."""
    schema = {"$id": "thing-report.v1.json", "type": "object",
              "properties": {"status": {"type": "string", "enum": ["completed", "blocked"]}}}
    root = make_tree(tmp_path, {
        "schemas/thing-report.v1.json": json.dumps(schema),
        "scripts/rank.py": 'RANK = {"completed": 0, "needs_review": 1, "blocked": 2}\n',
        "scripts/gate.py": ('import json, sys\n'
                            'doc = json.load(open("docs/dev/thing-report-x.json"))\n'
                            'if doc["status"] not in ("completed", "blocked"):\n'
                            '    sys.exit(2)\n'),
    })
    m, vs = check(root)
    copies = {v.artifact for v in vs if v.rule == "7-list"}
    assert "scripts/gate.py" in copies
    assert "scripts/rank.py" not in copies


def test_a_value_the_declared_schema_names_as_a_property_is_a_field_not_a_role(tmp_path):
    """`if name == f"x-report-{t}.json": section = "dev"` maps a declared path to the dev
    report's `dev` object when the declared schema names that property; it maps it to the role
    when the schema has no such property."""
    def tree(props: dict):
        schema = {"$id": "x-report.v1.json", "type": "object", "properties": props}
        return make_tree(tmp_path / ("a" if props else "b"), {
            "schemas/x-report.v1.json": json.dumps(schema),
            "commands/x.md": _template("dev", "docs/dev/x-report-<TASK_ID>.json", "x-report.v1"),
            "agents/dev.md": "---\nname: dev\n---\n",
            "scripts/r.py": ('import sys\n'
                             'def section(name, t):\n'
                             '    if name == f"x-report-{t}.json":\n'
                             '        section_name = "dev"\n'
                             '        return section_name\n'
                             '    return None\n'),
        })
    m, vs = check(tree({"dev": {"type": "object"}}))
    assert not [v for v in vs if v.rule == "7-list" and "maps" in v.message]
    m, vs = check(tree({"other": {"type": "object"}}))
    assert [v for v in vs if v.rule == "7-list" and "maps 'x-report-' to role 'dev'" in v.message]


def test_a_child_that_ran_before_its_fork_was_reported_keeps_its_parent_for_its_pids_next_lifetime(tmp_path):
    """A child can run, and exit, before its parent's fork is reported. That late fork report
    starts no lifetime of its own, so the pid's next lifetime keeps the fork that made it: the
    script a hook runs there is the hook's (its origin), never a process with no parent."""
    from tests.replay import trace
    out = tmp_path / "out"
    out.mkdir()
    lay = {"harness": "/sbx/hm/.claude", "project": "/sbx/proj", "origin": "/sbx/origin", "state": "/sbx/state",
           "home": "/sbx/hm", "sb": "/sbx", "markers": "/sbx/markers", "temp_dirs": ["/sbx/tmp"], "scratch": []}
    (out / "ids.json").write_text(json.dumps({"layout": lay, "ids": {}, "window": [0, None]}))
    (out / "markers.jsonl").write_text("")
    h = "/sbx/hm/.claude"
    raw = tmp_path / "raw.txt"
    raw.write_text(
        '1 clone(child_stack=NULL, flags=SIGCHLD) = 100\n'
        f'100 execve("/bin/bash", ["bash", "{h}/hooks/h.sh"], 0x7ffd /* 9 vars */) = 0\n'
        f'200 openat(AT_FDCWD</>, "{h}/logs/a.log", O_WRONLY|O_CREAT|O_APPEND, 0666) = 3<{h}/logs/a.log>\n'
        '200 +++ exited with 0 +++\n'
        '100 clone(child_stack=NULL, flags=SIGCHLD) = 200\n'
        '100 +++ exited with 0 +++\n'
        '1 clone(child_stack=NULL, flags=SIGCHLD) = 300\n'
        f'300 execve("/bin/bash", ["bash", "{h}/hooks/g.sh"], 0x7ffd /* 9 vars */) = 0\n'
        f'200 execve("{h}/venv/bin/python3", ["python3", "{h}/scripts/agg.py"], 0x7ffd /* 9 vars */) = 0\n'
        '300 vfork() = 200\n'
        '200 openat(AT_FDCWD</>, "/sbx/proj/docs/r.json", O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC, 0644)'
        ' = 3</sbx/proj/docs/r.json>\n'
        '200 +++ exited with 0 +++\n'
        '300 +++ exited with 0 +++\n')
    trace.parse(str(raw), str(out))
    events = [line.split("\t") for line in (out / "relation-events.tsv").read_text().splitlines()]
    by_path = {e[4]: e for e in events}
    assert by_path["<harness>/logs/a.log"][:2] == ["hooks/h.sh", "hooks/h.sh"]
    assert by_path["<project>/docs/r.json"][:2] == ["scripts/agg.py", "hooks/g.sh"]


def test_a_child_that_exited_with_no_traced_call_before_its_fork_was_reported_was_a_lifetime(tmp_path):
    """A child whose only line is its exit, reported before its parent's fork: that exit ends a
    lifetime of the pid, so the late fork report starts none, and the pid's next lifetime is the
    next fork's child, not a process of the first parent's hook run."""
    from tests.replay import trace
    out = tmp_path / "out"
    out.mkdir()
    lay = {"harness": "/sbx/hm/.claude", "project": "/sbx/proj", "origin": "/sbx/origin", "state": "/sbx/state",
           "home": "/sbx/hm", "sb": "/sbx", "markers": "/sbx/markers", "temp_dirs": ["/sbx/tmp"], "scratch": []}
    (out / "ids.json").write_text(json.dumps({"layout": lay, "ids": {}, "window": [0, None]}))
    (out / "markers.jsonl").write_text("")
    h = "/sbx/hm/.claude"
    raw = tmp_path / "raw.txt"
    raw.write_text(
        '1 clone(child_stack=NULL, flags=SIGCHLD) = 100\n'
        f'100 execve("/bin/bash", ["bash", "{h}/hooks/h.sh"], 0x7ffd /* 9 vars */) = 0\n'
        '200 +++ exited with 0 +++\n'
        '100 clone(child_stack=NULL, flags=SIGCHLD) = 200\n'
        '100 +++ exited with 0 +++\n'
        '1 clone(child_stack=NULL, flags=SIGCHLD) = 300\n'
        f'300 execve("/bin/bash", ["bash", "{h}/scripts/s.sh"], 0x7ffd /* 9 vars */) = 0\n'
        '300 clone(child_stack=NULL, flags=SIGCHLD) = 200\n'
        f'200 openat(AT_FDCWD</>, "{h}/logs/l.jsonl", O_WRONLY|O_CREAT|O_APPEND, 0666) = 3<{h}/logs/l.jsonl>\n'
        '200 +++ exited with 0 +++\n'
        '300 +++ exited with 0 +++\n')
    trace.parse(str(raw), str(out))
    events = [line.split("\t") for line in (out / "relation-events.tsv").read_text().splitlines()]
    assert [e[:2] for e in events if e[4] == "<harness>/logs/l.jsonl"] == [["scripts/s.sh", "scripts/s.sh"]]
