"""Unit tests of the derivation rules behind rule (4) (one deciding rule per artifact and
mutation), rule (5) (the chain function's output used verbatim) and rule (6) (a deciding read
outside the allowed positions: a re-check, an E4 copy, a rule to move into a gate, or a use).

Each test builds a small harness-shaped tree (test_check.py's harness) and, where the rule needs
one, a replay reduced to its environment, derives the check on it, and pins one rule with its
counter-case beside it.
"""

from __future__ import annotations

import json

from tests.artifact_graph import check as C
from tests.artifact_graph import derive
from tests.artifact_graph.test_check import check, hook, make_tree, rules_on

FLAG = "<state>/claude-flag-<sid>.flag"
REC = "<state>/claude-rec-<sid>.json"


def _registered(*hooks: tuple) -> dict:
    """settings.json registering (event, matcher, hook file) entries."""
    out: dict = {"env": {}, "hooks": {}}
    for event, matcher, path in hooks:
        group = {"hooks": [{"type": "command", "command": f'python3 "$CLAUDE_HOME/{path}"'}]}
        if matcher:
            group["matcher"] = matcher
        out["hooks"].setdefault(event, []).append(group)
    return out


# ------------------------------------------------------------------ rule (4): one rule

def test_a_verdict_a_library_function_returns_is_one_rule_for_every_caller(tmp_path):
    """Hooks that call one library function reading the artifact and act on what it returns
    take its one verdict (the consent flag's `has_do_consent`); hooks that each test a part of
    what a loading function returned decide by rules of their own."""
    lib = '''
        import json
        from pathlib import Path
        from lib.harness_state_dir import harness_state_dir
        def has_flag(payload):
            sid = payload.get("session_id")
            return Path(harness_state_dir(), f"claude-flag-{sid}.flag").read_text().strip() == "true"
        def load(payload):
            sid = payload.get("session_id")
            return json.loads(Path(harness_state_dir(), f"claude-rec-{sid}.json").read_text())
    '''
    writer = hook('''
        import json
        d = json.load(sys.stdin)
        open(harness_state_dir() + "/claude-flag-" + d["session_id"] + ".flag", "w").write("true")
        open(harness_state_dir() + "/claude-rec-" + d["session_id"] + ".json", "w").write("{}")
    ''')
    caller = '''
        import json
        from lib.flags import has_flag, load
        d = json.load(sys.stdin)
        if {neg}has_flag(d):
            sys.exit(2)
        if load(d)["{field}"] == 1:
            sys.exit(2)
    '''
    settings = _registered(("PreToolUse", "Bash", "hooks/a.py"), ("PreToolUse", "Bash", "hooks/b.py"))
    root = make_tree(tmp_path, {
        "hooks/lib/flags.py": lib, "hooks/w.py": writer,
        "hooks/a.py": hook(caller.format(neg="", field="x")),
        "hooks/b.py": hook(caller.format(neg="not ", field="y")),
    }, settings)
    _m, vs = check(root)
    assert "4-one-rule" not in rules_on(vs, FLAG)
    assert "4-one-rule" in rules_on(vs, REC)


def test_a_deciding_reads_rule_is_the_library_site_it_ran_in_when_the_verdict_is_taken_whole(tmp_path):
    """The rule identity of a static deciding read (the shell form: `if write_checkpoint; then
    ... else exit 1`, the read inside the sourced library): the read's own site in the
    library function when the decision takes its verdict whole, the reader's own site when it
    tests a part of what came back, and the reader's own site for a read of its own code."""
    ctx = C._Ctx(C.Map(str(tmp_path)), [], [], [], [], set(), "scripts/x.py", [], str(tmp_path))

    def rec(read_through, whole, through=()):
        return {"component": "hooks/a.sh", "read_site": "hooks/a.sh:45", "read_through": list(read_through),
                "whole": whole, "through": list(through)}

    assert ctx._static_rule(rec(["hooks/lib/core.sh:131"], True)) == "hooks/lib/core.sh:131"
    assert ctx._static_rule(rec(["hooks/lib/core.sh:131"], False)) == "hooks/a.sh:45"
    assert ctx._static_rule(rec(["hooks/a.sh:12"], True)) == "hooks/a.sh:45"
    assert ctx._static_rule(rec([], True, ["hooks/a.sh:60"])) == "hooks/a.sh:60"
    assert C._rule_groups([C.Decision("hooks/a.sh", "elsewhere", "e", "static", rule="hooks/lib/core.sh:131"),
                           C.Decision("hooks/b.sh", "elsewhere", "e", "static", rule="hooks/lib/core.sh:131")]) \
        == ["hooks/a.sh+hooks/b.sh"]


def test_a_call_carrying_several_reads_pairs_its_verdict_with_each(tmp_path):
    """A call into a library function that reads two files and returns both carries both reads:
    the `except` around the call decides on each, not on the last one alone."""
    lib = '''
        import json
        from pathlib import Path
        from lib.harness_state_dir import harness_state_dir
        def load(sid):
            rec = json.loads(Path(harness_state_dir(), f"claude-rec-{sid}.json").read_text())
            flag = Path(harness_state_dir(), f"claude-flag-{sid}.flag").read_text()
            return rec, flag
    '''
    writer = hook('''
        import json
        d = json.load(sys.stdin)
        open(harness_state_dir() + "/claude-rec-" + d["session_id"] + ".json", "w").write("{}")
        open(harness_state_dir() + "/claude-flag-" + d["session_id"] + ".flag", "w").write("true")
    ''')
    reader = hook('''
        import json
        from lib.both import load
        d = json.load(sys.stdin)
        try:
            load(d["session_id"])
        except ValueError:
            sys.exit(2)
    ''')
    m, _vs = check(make_tree(tmp_path, {"hooks/lib/both.py": lib, "hooks/w.py": writer, "scripts/r.py": reader}))
    for key in (REC, FLAG):
        assert [d for d in m.artifacts[key].decisions if d.who == "scripts/r.py"], key


_STATE_LIB = '''
    import json
    from pathlib import Path
    from lib.harness_state_dir import harness_state_dir
    def read_state(sid):
        try:
            path = Path(harness_state_dir(), f"claude-rec-{sid}.json")
            if path.stat().st_size == 0:
                return None
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) else None
'''


def test_the_reads_one_library_function_makes_are_one_rule(tmp_path):
    """A record's one reading function stats it, then reads it: a hook taking its verdict whole
    and a reader the differential measured whose static reads run there both decide by that
    function, whichever of its two reads a mutation reaches."""
    use = hook('''
        import json
        from lib.st import read_state
        d = json.load(sys.stdin)
        if read_state(d["session_id"]) is None:
            sys.exit(2)
    ''')
    root = make_tree(tmp_path, {"hooks/lib/st.py": _STATE_LIB, "hooks/a.py": use, "hooks/b.py": use,
                                "hooks/w.py": hook('open(harness_state_dir() + "/claude-rec-x.json", "w")\n')})
    m, _vs = check(root)
    ctx = m.ctx
    statics = [d for d in m.artifacts[REC].decisions if d.who == "hooks/a.py"]
    assert {d.rule for d in statics} == {"hooks/lib/st.py:read_state"}
    measured = C.Decision("hooks/b.py", "own stop", "run#3", "differential", "removed", "shipped",
                          rule=ctx._rule_id("hooks/b.py", REC))
    assert measured.rule == "hooks/lib/st.py:read_state"
    assert C._rule_groups(statics + [measured]) == ["hooks/a.py+hooks/b.py"]


def test_a_measured_reader_through_several_library_functions_shares_each_ones_rule(tmp_path):
    """A gate the differential measured whose static deciding reads of the record run in two
    functions of other files (the record's one reading function, a schema check) takes the
    verdict of each: it shares a rule with a planner that takes the reading function's, where a
    single identity of its own would make it a rule apart (and the planner a rule to move)."""
    load = '''
        import json
        from pathlib import Path
        from lib.harness_state_dir import harness_state_dir
        def load(sid):
            return json.loads(Path(harness_state_dir(), f"claude-rec-{sid}.json").read_text())
    '''
    schema = '''
        import json
        from pathlib import Path
        from lib.harness_state_dir import harness_state_dir
        def valid(sid):
            try:
                return isinstance(json.loads(Path(harness_state_dir(), f"claude-rec-{sid}.json").read_text()), dict)
            except (OSError, ValueError):
                return False
    '''
    gate = hook('''
        import json
        from lib.r import load
        from lib.schema import valid
        d = json.load(sys.stdin)
        try:
            load(d["session_id"])
        except ValueError:
            sys.exit(2)
        if not valid(d["session_id"]):
            sys.exit(2)
    ''')
    plan = hook('''
        import json
        from lib.r import load
        d = json.load(sys.stdin)
        try:
            load(d["session_id"])
        except ValueError:
            sys.exit(2)
    ''')
    root = make_tree(tmp_path, {"hooks/lib/r.py": load, "hooks/lib/schema.py": schema, "hooks/gate.py": gate,
                                "scripts/plan.py": plan,
                                "hooks/w.py": hook('open(harness_state_dir() + "/claude-rec-x.json", "w")\n')})
    m, _vs = check(root)
    rule = m.ctx._rule_id("hooks/gate.py", REC)
    assert C._rules(C.Decision("hooks/gate.py", "", "", "", rule=rule)) == {"hooks/lib/r.py:load",
                                                                          "hooks/lib/schema.py:valid"}
    d1 = C.Decision("hooks/gate.py", "own stop", "e", "differential", "removed", "shipped", rule=rule)
    d2 = next(d for d in m.artifacts[REC].decisions if d.who == "scripts/plan.py")
    assert C._rule_groups([d1, d2]) == ["hooks/gate.py+scripts/plan.py"]
    a = C.Artifact(REC)
    a.writers.append(C.Rel("main", "write", "x", "runtime"))
    a.decisions = [d1, d2]
    assert not C._rechecks(a, a.key, [])


def test_a_field_the_library_function_sets_itself_is_its_verdict(tmp_path):
    """Two hooks test the `decision` field of what one evaluating function returns: the function
    builds that record and sets the field to literals of its own, so the field is its verdict and
    both take it whole (one rule). Where the function copies the field from what it read, or
    returns what it read on some path, the field is the artifact's content and each test is a
    rule of its own."""
    def tree(name: str, value: str, extra: str = "pass"):
        lib = f'''
            import json
            from pathlib import Path
            from lib.harness_state_dir import harness_state_dir
            def evaluate(sid):
                record = {{"decision": "REFUSE", "reason": None}}
                try:
                    state = json.loads(Path(harness_state_dir(), f"claude-rec-{{sid}}.json").read_text())
                except (OSError, ValueError) as e:
                    record["reason"] = str(e)
                    return record
                if state.get("raw"):
                    {extra}
                record["decision"] = {value}
                return record
        '''
        use = hook('''
            import json
            from lib.ev import evaluate
            d = json.load(sys.stdin)
            rec = evaluate(d["session_id"])
            if rec["decision"] != "PERMIT":
                sys.exit(2)
        ''')
        return make_tree(tmp_path / name, {
            "hooks/lib/ev.py": lib, "hooks/a.py": use, "scripts/b.py": use,
            "hooks/w.py": hook('open(harness_state_dir() + "/claude-rec-x.json", "w")\n')})
    _m, vs = check(tree("verdict", '"PERMIT" if state.get("ok") is True else "REFUSE"'))
    assert "4-one-rule" not in rules_on(vs, REC)
    _m2, vs2 = check(tree("content", 'state.get("decision")'))
    assert "4-one-rule" in rules_on(vs2, REC)
    _m3, vs3 = check(tree("passed-on", '"PERMIT"', extra="return dict(state)"))
    assert "4-one-rule" in rules_on(vs3, REC)


def test_a_library_run_as_a_process_decides_by_the_function_its_callers_call(tmp_path):
    """The one classifier of a report is run as a process by one consumer and called in-process
    by another: both decide by the function that reads the report (the process's own reading
    function, the caller's library function), one rule."""
    cv = '''
        import sys
        def classify(path):
            try:
                text = open(path).read()
            except FileNotFoundError:
                return "missing"
            return "yes" if text.strip().endswith("YES") else "no"
        if __name__ == "__main__":
            if classify(sys.argv[1]) != "yes":
                sys.exit(2)
    '''
    use = '''
        import sys
        from lib.cv import classify
        if classify(sys.argv[1]) == "missing":
            sys.exit(2)
    '''
    root = make_tree(tmp_path, {"hooks/lib/cv.py": cv, "hooks/u.py": use})
    m, _vs = check(root)
    key = "<*>"
    statics = [C.Decision("hooks/u.py", "elsewhere", "s", "static", "any", "static", rule=m.ctx._static_rule(d))
               for d in m.ctx.recs if d["kind"] == "deciding" and d["component"] == "hooks/u.py"]
    assert {d.rule for d in statics} == {"hooks/lib/cv.py:classify"}
    process = C.Decision("hooks/lib/cv.py", "elsewhere", "run#7", "differential", "removed", "shipped",
                         rule=m.ctx._rule_id("hooks/lib/cv.py", key))
    assert C._rule_groups(statics + [process]) == ["hooks/lib/cv.py+hooks/u.py"]


# ------------------------------------------------------------------ rule (5): the chain's output

CHAIN = '''
    import json, sys
    def resolve_chain(project_dir, task_id):
        return json.load(open(project_dir + "/docs/dev/dev-report-" + task_id + ".json"))
    def exit_status(result):
        return 0 if result["status"] in ("pass", "pass_with_exceptions") else 2
    if __name__ == "__main__":
        r = resolve_chain(sys.argv[1], sys.argv[2])
        print(json.dumps(r))
        sys.exit(exit_status(r))
'''

CONSUMER = '''
    import importlib.util, sys
    from pathlib import Path
    def _resolver():
        spec = importlib.util.spec_from_file_location(
            "r", str(Path(__file__).resolve().parent / "resolve-dev-artifact-chain.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    def row(project_dir, task_id):
        resolver = _resolver()
        result = resolver.resolve_chain(project_dir, task_id)
        out = {{"chain": result, "lanes": [lane["task_id"] for lane in result["lanes"]]}}
        {verdict}
        return out
'''


def _chain_violations(tmp_path, verdict: str, block: str = "") -> list:
    files = {"scripts/resolve-dev-artifact-chain.py": CHAIN,
             "scripts/consumer.py": CONSUMER.format(verdict=verdict)}
    if block:
        files["commands/x.md"] = "# /x\n\n```bash\n" + block + "\n```\n"
    _m, vs = check(make_tree(tmp_path, files))
    return [v for v in vs if v.rule == "5-chain-verbatim"]


def test_the_chain_functions_verdict_and_a_field_carried_on_are_its_output_used(tmp_path):
    """The chain call's exit status, a function of the chain's module applied to its result,
    and fields only carried on (a record's lanes) use the output verbatim; a test of a field
    of it (its status against a list of its own) decides on it."""
    assert not _chain_violations(tmp_path / "a", 'out["passed"] = resolver.exit_status(result) == 0',
                                 'CHAIN="$(python3 ~/.claude/scripts/resolve-dev-artifact-chain.py . t)" || exit 2')
    vs = _chain_violations(tmp_path / "b", 'out["passed"] = result["status"] in ("pass", "pass_with_exceptions")')
    assert [v for v in vs if "scripts/consumer.py" in v.message]


# ------------------------------------------------------------------ rule (6): a use, an E4 copy

def test_a_decision_elsewhere_on_what_only_code_writes_is_its_use(tmp_path):
    """A flag only a hook writes and no obligation declares, decided on by a script the main
    agent runs: no gate returns a fault to code, so the decision is the flag's use (rule (4)
    still counts its rules). The same decision on a file the main agent writes with its own
    tool is a rule to move into its gate."""
    decider = hook('''
        if not os.path.exists(harness_state_dir() + "/claude-intent.flag"):
            sys.exit(2)
    ''')
    by_code = make_tree(tmp_path / "code", {
        "hooks/w.py": hook('open(harness_state_dir() + "/claude-intent.flag", "w").write("true")\n'),
        "scripts/mint.py": decider,
    })
    _m, vs = check(by_code)
    assert "6-move" not in rules_on(vs, "<state>/claude-intent.flag")
    by_role = make_tree(tmp_path / "role", {
        "commands/x.md": '# /x\n\n```bash\nprintf true > "${CLAUDE_STATE_DIR}/claude-intent.flag"\n```\n',
        "scripts/mint.py": decider,
    })
    m2, vs2 = check(by_role)
    a = m2.artifacts.get("<state>/claude-intent.flag")
    assert a is not None and a.producers() == ["main"]
    assert "6-move" in rules_on(vs2, "<state>/claude-intent.flag")


def test_files_of_a_tree_a_platform_tool_creates_are_no_artifacts(tmp_path):
    """`python3 -m venv DIR` creates the interpreter's own environment: a script that tests it
    tests its environment, not an artifact; a file a script writes under its own directory is
    one."""
    root = make_tree(tmp_path, {
        "scripts/bootstrap": '#!/usr/bin/env bash\npython3 -m venv "$HOME/.claude/venv"\n'
                             'printf x > "$HOME/.claude/logs/boot.log"\n',
        "scripts/test": '#!/usr/bin/env bash\n[ -f "$HOME/.claude/venv/bin/activate" ] || exit 1\n'
                        '[ -f "$HOME/.claude/logs/boot.log" ] || exit 1\n',
    })
    m, _vs = check(root)
    assert not [k for k in m.artifacts if "/venv/" in k]
    assert "<harness>/logs/boot.log" in m.artifacts


def _gate_tree(tmp_path, path: str, schema: bool = True):
    art = {"kind": "json", "path": path}
    if schema:
        art["schema"] = "r.v1"
    ob = json.dumps({"task_id": "<TASK_ID>", "role": "qa", "pipeline": "x", "artifacts": [art]})
    settings = _registered(("SubagentStop", "", "hooks/g2.py"))
    return make_tree(tmp_path, {
        "commands/x.md": f'# /x\n\n<obligation v="1">\n{ob}\n</obligation>\n',
        "hooks/g2.py": 'import os\nMODE = os.environ.get("GATE_X_MODE", "advisory")\n',
        "scripts/use.py": '''
            import json, sys
            json.load(open("docs/dev/r-" + sys.argv[1] + ".json"))
            if not open("docs/dev/r-" + sys.argv[1] + ".json").read():
                sys.exit(2)
        ''',
    }, settings)


def _runs(shipped_mode: str, armed_mode: str) -> list:
    out = []
    for name, mode in (("shipped", shipped_mode), ("armed", armed_mode)):
        r = C.Run("x", name, "")
        r.env = {"CLAUDE_STATE_DIR": "/sbx/state", "GATE_X_MODE": mode}
        out.append(r)
    return out


def test_a_consumer_copy_of_what_the_stop_gate_checks_armed_is_an_e4_copy(tmp_path):
    """A report an obligation declares, decided on by a consumer script: the hook at
    SubagentStop whose gate switch the armed copy sets otherwise than the tree's settings.json
    checks the declared report at its role's stop when armed, so the consumer is that fault's
    only stop while the gate is advisory (listed, not a violation). With no switched stop gate
    it is a rule to move."""
    root = _gate_tree(tmp_path, "docs/dev/r-<TASK_ID>.json")
    st = derive(root)
    m = C.derive(str(root), st, _runs("advisory", "block"))
    vs = C.violations(m, st.records)
    key = next(k for k in m.artifacts if "/r-" in k)
    assert "6-move" not in rules_on(vs, key)
    assert [line for line in C.advisory_copies(m) if line.startswith(key)]
    m2 = C.derive(str(root), st, _runs("block", "block"))
    assert "6-move" in rules_on(C.violations(m2, st.records), key)


def test_a_lane_file_and_a_file_under_a_declared_folder_are_declared(tmp_path):
    """A fan-out lane's dispatch declares its template's path with its own id, the parent's
    with the lane; a dispatch that declares a folder declares the files in it."""
    assert C._lane_of("<proj>/docs/dev/qa-report-<ts>.json", "<proj>/docs/dev/qa-report-<ts>-<lane>.json")
    assert not C._lane_of("<proj>/docs/dev/qa-report-<ts>.json", "<proj>/docs/dev/dev-report-<ts>-<lane>.json")
    assert C._under("<proj>/docs/dev/specs/<*>/views", "<proj>/docs/dev/specs/<ts>/views/qa.md")
    assert not C._under("<proj>/docs/dev/specs/<*>/views.json", "<proj>/docs/dev/specs/<ts>/views.json/x")
    assert not C._under("<proj>/docs/dev/specs/<*>/views", "<proj>/docs/dev/specs/<ts>/other/qa.md")


def test_a_producers_library_reading_its_own_artifact_is_its_own_artifact(tmp_path):
    """A library that writes the state and reads it back decides on its own artifact, also
    where hooks load it; a library that only reads is judged at its callers' positions."""
    lib = '''
        import json
        from pathlib import Path
        from lib.harness_state_dir import harness_state_dir
        def path():
            return Path(harness_state_dir(), "claude-own.json")
        def write(rec):
            path().write_text(json.dumps(rec))
        def live():
            try:
                rec = json.loads(path().read_text())
            except ValueError:
                raise SystemExit(2)
            return rec
    '''
    root = make_tree(tmp_path, {
        "hooks/lib/own.py": lib,
        "hooks/w.py": hook("from lib.own import write\nwrite({})\n"),
        "hooks/r.py": hook("from lib.own import live\nlive()\n"),
    })
    m, _vs = check(root)
    a = m.artifacts["<state>/claude-own.json"]
    assert {d.position for d in a.decisions if d.who == "hooks/lib/own.py"} == {"own artifact"}


# ------------------------------------------------------------------ rule (2)'s readers

def _close_obligation() -> str:
    ob = json.dumps({"task_id": "<TASK_ID>", "role": "qa", "pipeline": "close", "artifacts": [
        {"kind": "response_line", "terminal_line_regex": "^(CLOSE: YES|CLOSE: NO)$"}]})
    return f'# /close\n\n<obligation v="1">\n{ob}\n</obligation>\n'


def test_a_marker_in_a_message_names_it_and_a_marker_a_test_holds_reads_it(tmp_path):
    """The marker inside an f-string that only forms a message is shown, not read; inside a
    comparison or a matching call it reads the response."""
    shown = '''
        import sys
        line = sys.argv[1]
        if not line:
            raise SystemExit(f"not a legal CLOSE: form: {line!r}")
    '''
    tested = '''
        import sys
        line = sys.argv[1]
        if line.startswith(f"CLOSE: "):
            raise SystemExit(2)
    '''
    m, _vs = check(make_tree(tmp_path / "a", {"commands/close.md": _close_obligation(), "scripts/s.py": shown}))
    a = m.artifacts["response:qa:CLOSE:"]
    assert "scripts/s.py" not in a.consumers()
    m2, _vs2 = check(make_tree(tmp_path / "b", {"commands/close.md": _close_obligation(), "scripts/s.py": tested}))
    assert "scripts/s.py" in m2.artifacts["response:qa:CLOSE:"].consumers()


def test_a_regex_shaped_to_the_id_decides_and_a_name_built_from_it_uses_it():
    """Of the code that holds a minted id's form, a regex that parses it is a rule on what the
    id is; a number-range regex the id's sample happens to match is about something else, and
    a template building a file name from the id uses it."""
    import re
    rx_id, rx_range = re.compile(r"\d{8}-\d{6}"), re.compile(r"([0-9]+)-([0-9]+)")
    sample = "20261030-081110"
    assert rx_id.fullmatch(sample) and not rx_id.fullmatch(re.sub(r"\d+", "1", sample))
    assert rx_range.fullmatch(sample) and rx_range.fullmatch(re.sub(r"\d+", "1", sample))


# ------------------------------------------------------------------ rules (1) and (3)'s reads

def test_a_hand_run_tools_project_file_is_its_own_checkouts(tmp_path):
    """A script a person runs and nothing in the harness runs names its project root
    (`git rev-parse --show-toplevel`): a file of the tree there is the tree's own file, an input;
    the same read by a script the commands run names the project's file."""
    tool = ('#!/usr/bin/env bash\n# Usage: bash scripts/verify.sh\nROOT="$(git rev-parse --show-toplevel)"\n'
            '[ -f "$ROOT/README.md" ] || exit 2\n')
    files = {"README.md": "# tree\n", "scripts/verify.sh": tool,
             "commands/x.md": '# /x\n\n```bash\nprintf x >> "$CLAUDE_PROJECT_DIR/README.md"\n```\n'}
    m, vs = check(make_tree(tmp_path / "hand", files))
    assert not any(v.artifact == "<proj>/README.md" and v.rule.startswith("6-") for v in vs)
    ran = dict(files, **{"commands/y.md": "# /y\n\n```bash\nbash ~/.claude/scripts/verify.sh\n```\n"})
    m2, _vs2 = check(make_tree(tmp_path / "ran", ran))
    assert any(d.who == "scripts/verify.sh" for d in m2.artifacts["<proj>/README.md"].decisions)


def test_a_file_fed_to_a_tree_scripts_stdin_is_read_by_that_script(tmp_path):
    """`python3 <harness>/scripts/check.py < FILE`: the script reads the content and decides;
    the shell that opens the file takes the script's exit status, which decides on no read of
    its own. A command that is not a tree script reading its stdin leaves the read the shell's."""
    lib = '''
        H="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
        if ! python3 "$H/scripts/check.py" < "$H/conf.json"; then
            exit 1
        fi
        if ! grep -q x < "$H/other.json"; then
            exit 1
        fi
    '''
    root = make_tree(tmp_path, {
        "scripts/check.py": "import json, sys\njson.load(sys.stdin)\n",
        "scripts/w.sh": 'H="$(cd "$(dirname "$0")/.." && pwd)"\nprintf "{}" > "$H/conf.json"\nprintf x > "$H/other.json"\n',
        "hooks/h.sh": lib,
    })
    m, _vs = check(root)
    assert not [d for d in m.artifacts["<harness>/conf.json"].decisions if d.who == "hooks/h.sh"]
    assert [d for d in m.artifacts["<harness>/other.json"].decisions if d.who == "hooks/h.sh"]


def test_a_byte_copy_of_a_source_found_present_decides_on_no_mutation(tmp_path):
    """`if [ -f "$X" ]; then cp "$X" "$X.bak" || exit 1; fi`: the copy's status is the same for
    every content and the guard leaves it no absent source; unguarded, a missing source fails
    it, a decision on the file's removal."""
    def tree(name: str, guarded: bool):
        body = ('if [ -f "$H/conf.json" ]; then\n    cp -p "$H/conf.json" "$H/conf.bak" || exit 1\nfi\n' if guarded
                else 'cp -p "$H/conf.json" "$H/conf.bak" || exit 1\n')
        return make_tree(tmp_path / name, {
            "scripts/w.sh": 'H="$(cd "$(dirname "$0")/.." && pwd)"\nprintf "{}" > "$H/conf.json"\n',
            "scripts/b.sh": 'H="$(cd "$(dirname "$0")/.." && pwd)"\n' + body,
        })
    m, _vs = check(tree("guarded", True))
    assert not [d for d in m.artifacts["<harness>/conf.json"].decisions if d.who == "scripts/b.sh"]
    m2, _vs2 = check(tree("bare", False))
    assert [d for d in m2.artifacts["<harness>/conf.json"].decisions if d.who == "scripts/b.sh"]


# ------------------------------------------------------------------ E1's differential, rule (6)

def _diff_run(units: list, env: dict | None = None) -> C.Run:
    r = C.Run("x", "shipped", "")
    r.env = env or {"CLAUDE_STATE_DIR": "/sbx/state"}
    r.events = []
    r.differential = {"units": units}
    return r


def test_a_chain_calls_change_is_the_chains_and_measures_no_other_reader():
    """One Bash call runs the chain function and, after it, a planner reading the same report:
    a mutation the chain decides on changes the call there, so the change is not the planner's
    rule; a mutation of a file the chain does not decide on stays the planner's."""
    ctx = C._Ctx(C.Map("/t"), [], [], [], [], set(), "scripts/chain.py", [], "/t")
    key, other = "<proj>/docs/dev/r-<ts>.json", "<proj>/docs/dev/p-<ts>.json"
    ctx.m.art(key).runtime = True
    ctx.m.art(other).runtime = True
    unit = {"seq": 5, "event": "PreToolUse", "label": "Step 5", "kind": "bash", "tool": "Bash"}
    ctx.runs = [_diff_run([
        dict(unit, origin="scripts/chain.py", runs=[
            {"pattern": key, "raw": "/p/r", "how": "removed", "changed": True, "readers": ["scripts/chain.py"]}]),
        dict(unit, origin="scripts/plan.py", runs=[
            {"pattern": key, "raw": "/p/r", "how": "removed", "changed": True, "readers": ["scripts/plan.py"]},
            {"pattern": other, "raw": "/p/p", "how": "removed", "changed": True, "readers": ["scripts/plan.py"]}]),
    ])]
    ctx.deciding()
    assert {d.who for d in ctx.m.artifacts[key].decisions} == {"scripts/chain.py"}
    assert {d.who for d in ctx.m.artifacts[other].decisions} == {"scripts/plan.py"}


def test_a_decision_elsewhere_that_takes_an_allowed_deciders_verdict_is_its_use():
    """Row 13's use: a reader outside the allowed positions that decides from the return of the
    one function a decider at an allowed position decides by uses that verdict; with a rule of
    its own it is a rule to move into the gate."""
    a = C.Artifact("<proj>/docs/dev/r.json")
    a.writers.append(C.Rel("main", "write", "x", "runtime"))
    a.decisions = [C.Decision("hooks/stop-x.py", "own stop", "e1", "differential", "removed", "shipped",
                              rule="hooks/lib/r.py:9"),
                   C.Decision("scripts/use.py", "elsewhere", "s1", "static", "any", "static", rule="hooks/lib/r.py:9")]
    assert not C._rechecks(a, a.key, [])
    a.decisions[1].rule = "scripts/use.py:4"
    assert [v.rule for v in C._rechecks(a, a.key, [])] == ["6-move"]


def _calls_run(calls: dict) -> C.Run:
    """A replay reduced to its invocations: seq -> a tool name (a tool call) or None (a prompt)."""
    r = C.Run("x", "shipped", "")
    r.invocations = {seq: ({"seq": seq, "event": "PreToolUse", "payload": {"tool_name": tool}} if tool
                           else {"seq": seq, "event": "UserPromptSubmit", "payload": {"prompt": "/x"}})
                     for seq, tool in calls.items()}
    return r


def _traced(who: str, op: str, run: C.Run, seq: int, actor: str) -> C.Rel:
    rel = C.Rel(who, op, f"{run.name}#{seq}", "runtime", via=who, actor=actor)
    rel.run, rel.seq, rel.raw = run, seq, "/p/f"     # type: ignore[attr-defined]
    return rel


def test_a_hook_on_a_tool_the_producer_did_not_write_with_is_not_at_its_tool_call():
    """The platform records a dispatch in the Agent call that makes it: a hook on Bash never runs
    in that call, so its decision on the record is not the producer's side, while a hook on Agent
    is the dispatch's (G1). A file the main agent writes through Bash is decided on at its tool
    call by a hook on Bash."""
    ctx = C._Ctx(C.Map("/t"), [], [], [], [], set(), "scripts/chain.py", [], "/t")
    run = _calls_run({5: "Agent"})
    record = C.Artifact("<harness>/projects/<slug>/<sid>/subagents/agent-<agent>.meta.json")
    record.writers.append(_traced("cli", "write", run, 5, "main"))
    assert ctx._position(record, "PreToolUse", None, None, "hooks/guard.py", "static", matcher="Bash") == "elsewhere"
    assert ctx._position(record, "PreToolUse", None, None, "hooks/g1.py", "static", matcher="Agent") == "G1"
    shell = C.Artifact("<state>/claude-own-<sid>.json")
    shell.writers.append(_traced("main", "write", _calls_run({5: "Bash"}), 5, "main"))
    assert ctx._position(shell, "PreToolUse", None, None, "hooks/guard.py", "static", matcher="Bash") \
        == "producer tool call"


def test_a_script_the_producer_runs_on_what_it_just_wrote_is_its_own_side():
    """The main agent writes a manifest and, in the next tool call of the same command, runs the
    script that refuses to go on without it: the refusal goes back to the producer that wrote it,
    in that run, so the script decides at the producer's side. The same script reading the file
    in a later command, or in another role's call, decides elsewhere."""
    ctx = C._Ctx(C.Map("/t"), [], [], [], [], set(), "scripts/chain.py", [], "/t")

    def manifest(calls: dict, read_seq: int, actor: str = "main") -> C.Artifact:
        run = _calls_run(calls)
        a = C.Artifact("<state>/claude-manifest-<sid>.json")
        a.writers.append(_traced("main", "write", run, 10, "main"))
        a.readers.append(_traced("scripts/mint.py", "read", run, read_seq, actor))
        return a

    same = manifest({9: None, 10: "Write", 12: "Bash"}, 12)
    assert ctx._position(same, "", None, None, "scripts/mint.py", "static") == "producer tool call"
    later = manifest({9: None, 10: "Write", 11: None, 12: "Bash"}, 12)
    assert ctx._position(later, "", None, None, "scripts/mint.py", "static") == "elsewhere"
    other = manifest({9: None, 10: "Write", 12: "Bash"}, 12, actor="agent:dev")
    assert ctx._position(other, "", None, None, "scripts/mint.py", "static") == "elsewhere"


def test_a_decision_on_what_nothing_writes_is_rule_twos():
    """A deciding read of a file no code, trace event or declaration writes has no producer
    side to weigh it against: the reading branch goes (2-unwritten), not a rule to move."""
    a = C.Artifact("<proj>/docs/x/ctx.json")
    a.readers.append(C.Rel("scripts/o.sh", "read", "scripts/o.sh:15", "static"))
    a.decisions = [C.Decision("scripts/o.sh", "elsewhere", "scripts/o.sh:15", "static", "any", "static",
                              rule="scripts/o.sh:15")]
    assert not C._rechecks(a, a.key, [])
    vs = [v.rule for v in C.violations(C.Map("/t", artifacts={a.key: a}))]
    assert vs == ["2-unwritten"]
    a.writers.append(C.Rel("main", "write", "x", "runtime"))
    assert [v.rule for v in C._rechecks(a, a.key, [])] == ["6-move"]
