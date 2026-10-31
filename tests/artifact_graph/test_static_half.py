"""Unit tests of the static half (tests/artifact_graph).

Each test builds a small harness-shaped tree under tmp_path and checks the
records derive() returns; one test runs the static half twice on this
repository, in two processes with different hash seeds, and compares bytes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.artifact_graph import derive
from tests.artifact_graph import patterns as P
from tests.artifact_graph import shparse as S

REPO = Path(__file__).resolve().parents[2]

ROOT_LIBS = {
    "hooks/lib/harness_state_dir.py": '''
        import os
        _ENV = "CLAUDE_STATE_DIR"
        def harness_state_dir():
            v = os.environ.get(_ENV, "")
            return v if v.startswith("/") else "/tmp"
    ''',
    "hooks/lib/harness_state_dir.sh": '''
        harness_state_dir() { printf '%s\\n' "${CLAUDE_STATE_DIR:-/tmp}"; }
    ''',
    "hooks/lib/claude_home.py": '''
        from pathlib import Path
        def resolve():
            return Path(__file__).resolve().parents[2]
        def project_dir():
            return Path.cwd()
    ''',
    "settings.json": '{"env": {}, "hooks": {}}',
}


def make_tree(tmp_path: Path, files: dict) -> Path:
    root = tmp_path / "tree"
    for rel, text in {**ROOT_LIBS, **files}.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return root


def rels(result, **match):
    return [r for r in result.records if r["kind"] == "relation"
            and all(r.get(k) == v for k, v in match.items())]


def kinds(result, kind, **match):
    return [r for r in result.records if r["kind"] == kind and all(r.get(k) == v for k, v in match.items())]


# ----------------------------------------------------------------- python

def test_python_roots_joins_constants_and_helpers(tmp_path):
    root = make_tree(tmp_path, {"hooks/gate.py": '''
        import json, os, sys
        from pathlib import Path
        sys.path.insert(0, os.path.dirname(__file__))
        from lib.harness_state_dir import harness_state_dir

        LOG = os.path.expanduser("~/.claude/logs/gate.log")
        REG = ".claude/dev-registry"

        def streak_path(sid):
            return Path(harness_state_dir()) / f"claude-tool-streak-{sid}.json"

        def main():
            payload = json.load(sys.stdin)
            sid = payload.get("session_id", "")
            data = json.loads(streak_path(sid).read_text())
            with open(LOG, "a") as fh:
                fh.write("x")
            Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / REG
            os.replace("/tmp/x.tmp", os.path.join("/tmp", "x.json"))
            os.unlink(streak_path(sid))
        main()
    '''})
    r = derive(root)
    assert rels(r, op="read", path="<state>/claude-tool-streak-<sid>.json", site="hooks/gate.py:15")
    assert rels(r, op="write", path="<harness>/logs/gate.log", mode="append")
    ren = rels(r, op="rename", path="/tmp/x.json")
    assert ren and ren[0]["from"] == ["/tmp/x.tmp"]
    assert rels(r, op="unlink", path="<state>/claude-tool-streak-<sid>.json")


def test_parameter_effects_bind_at_each_call_site(tmp_path):
    root = make_tree(tmp_path, {
        "hooks/lib/store.py": '''
            import json, os
            def atomic_write(path, data):
                tmp = path + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump(data, fh)
                os.replace(tmp, path)
        ''',
        "hooks/a.py": '''
            from lib.store import atomic_write
            atomic_write("/tmp/claude-a.json", {})
        ''',
        "scripts/b.py": '''
            import sys
            sys.path.insert(0, "hooks")
            from lib.store import atomic_write
            atomic_write("docs/dev/b.json", {})
        ''',
    })
    r = derive(root)
    a = rels(r, op="rename", path="/tmp/claude-a.json")
    assert a and a[0]["component"] == "hooks/a.py" and a[0]["through"] == ["hooks/lib/store.py:6"]
    assert rels(r, op="write", path="/tmp/claude-a.json.tmp", component="hooks/a.py")
    assert rels(r, op="rename", path="<proj>/docs/dev/b.json", component="scripts/b.py")
    # bound at the callers, so nothing is left unresolved at the helper
    assert not kinds(r, "unresolved", component="hooks/lib/store.py")


def test_unresolved_reasons(tmp_path):
    root = make_tree(tmp_path, {"scripts/u.py": '''
        import json, sys
        def main():
            target = sys.argv[1]
            open(target).read()
            rec = json.load(sys.stdin)
            open(rec["path"]).read()
        main()
    '''})
    r = derive(root)
    reasons = {u["site"]: u["reason"] for u in kinds(r, "unresolved")}
    assert reasons["scripts/u.py:4"] == "data:argv"
    assert reasons["scripts/u.py:6"] == "data:payload"
    assert r.summary["unresolved_by_reason"]["data:argv"] == 1


# ------------------------------------------------------------------ shell

def test_shell_redirects_commands_functions_and_embedded_python(tmp_path):
    root = make_tree(tmp_path, {"hooks/s.sh": '''
        #!/usr/bin/env bash
        . "$(dirname "${BASH_SOURCE[0]}")/lib/harness_state_dir.sh"
        SID=$(cat | jq -r '.session_id // empty')
        FLAG="$(harness_state_dir)/claude-flag-${SID}.json"
        put() { printf '%s' "$2" > "$1"; }
        put "$FLAG" x
        [ -f "${CLAUDE_STATE_DIR:-/tmp}/claude-other.json" ] && rm -f "$FLAG"
        mv "$HOME/.claude/a.tmp" "$HOME/.claude/a.json"
        python3 - <<'PY'
        import os
        open(os.path.join(os.environ["CLAUDE_PROJECT_DIR"], "docs/dev/p.json")).read()
        PY
    '''})
    r = derive(root)
    assert rels(r, op="write", path="<state>/claude-flag-<sid>.json", component="hooks/s.sh", site="hooks/s.sh:6")
    assert rels(r, op="read", path="<state>/claude-other.json", mode="name")
    assert rels(r, op="unlink", path="<state>/claude-flag-<sid>.json")
    assert rels(r, op="rename", path="<harness>/a.json")
    assert rels(r, op="read", path="<harness>/hooks/lib/harness_state_dir.sh", mode="source")
    emb = rels(r, op="read", path="<proj>/docs/dev/p.json")
    assert emb and emb[0]["component"] == "hooks/s.sh" and emb[0]["site"] == "hooks/s.sh:11"


def test_shell_parser_constructs():
    src = textwrap.dedent('''
        f() { local x="$1"; case "$x" in a|b) echo one ;; *) echo "${x%/*}" ;; esac; }
        for i in 1 2; do [[ -n "$i" && $i -gt 0 ]] || continue; done
        while IFS= read -r line; do :; done < <(printf '%s\\n' a)
        cat <<EOF > out.txt
        $(date) ${HOME:-/srv}
        EOF
        X=(a b) Y=$((1+2)) z=`echo hi`
    ''')
    sc = S.parse(src)
    assert not sc.errors
    kinds_ = [type(n).__name__ for n in sc.body]
    assert kinds_ == ["FuncDef", "For", "Loop", "Simple", "Simple"]
    heredoc = sc.body[3].redirs[0].heredoc
    assert heredoc.delim == "EOF" and "date" in heredoc.body


# --------------------------------------------------------------- markdown

def test_command_blocks_obligations_and_placeholders(tmp_path):
    root = make_tree(tmp_path, {
        "agents/ba.md": "---\nname: ba\n---\nBA\n",
        "agents/qa.md": "---\nname: qa\n---\nQA\n",
        "agents/INDEX.md": "# index\n",
        "commands/dev.md": '''
            ---
            description: dev
            ---
            ```bash
            DEV_SESSION_ID="dev-$(date +%Y%m%d-%H%M%S)"
            mkdir -p .claude/dev-registry/$DEV_SESSION_ID
            echo '{}' > .claude/dev-registry/<DEV_SESSION_ID>/ba.json
            ```
            <obligation v="1">
            {"task_id": "<timestamp>", "role": "ba", "pipeline": "dev", "profile": "singular",
             "lane_set": [<lanes>],
             "artifacts": [{"kind": "json", "path": "docs/dev/context-<timestamp>.json", "schema": "context.v1"}]}
            </obligation>
            Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="qa", pipeline="dev", profile="final_verification"/"x", artifacts=[{"kind":"json","path":"docs/dev/qa-report-<timestamp>.json","schema":"qa-report.v2"}].

            **Announce completion**:

            ```
            Summary: docs/dev/summary-<date>.md
            ```
        ''',
    })
    r = derive(root)
    assert rels(r, op="write", path="<proj>/.claude/dev-registry/dev-<ts>/ba.json", origin="md-block",
                site="commands/dev.md:7")
    obs = kinds(r, "declaration", type="obligation")
    by_role = {o["role"]: o for o in obs}
    assert by_role["ba"]["artifacts"][0]["path"] == "<proj>/docs/dev/context-<ts>.json"
    assert by_role["ba"]["artifacts"][0]["schema"] == "context.v1"
    assert by_role["qa"]["profile"] == ["final_verification", "x"] and by_role["qa"]["form"] == "prose"
    assert sorted(x["name"] for x in kinds(r, "declaration", type="roster_entry")) == ["ba", "qa"]
    assert [x["name"] for x in kinds(r, "declaration", type="command")] == ["dev"]
    out = kinds(r, "owner_output", channel="command_text")
    assert out and out[0]["shown"] == "docs/dev/summary-<*>.md"


# ----------------------------------------------------------- declarations

def test_todo_steps_schemas_settings_and_switches(tmp_path):
    root = make_tree(tmp_path, {
        "scripts/todo/dev.py": '''
            _STEPS = [("1", "Parse", None), ("2", "Delegate", {"subagent_call": {"agent": "ba", "subagent_type": "ba"}})]
            _FORCED = [("1", "Forced", None)]
            def _forced():
                return False
            def _build(label, desc, meta):
                item = {"content": f"Step {label}: {desc}", "status": "pending"}
                if meta:
                    item.update(meta)
                return item
            def get_todos():
                steps = _FORCED if _forced() else _STEPS
                return [_build(l, d, m) for l, d, m in steps]
        ''',
        "scripts/todo/redev.py": "from dev import get_todos\n",
        "schemas/registry.json": '{"schemas": {"x.v1": "x.v1.json"}}',
        "schemas/x.v1.json": '{"$id": "x.v1", "properties": {"status": {"enum": ["pass", "fail"]}}}',
        "hooks/gate.py": '''
            import os, sys
            MODE = os.environ.get("CLAUDE_X_GATE", "advisory").strip().lower()
            if MODE == "block":
                sys.exit(2)
        ''',
        "settings.json": json.dumps({"env": {"CLAUDE_X_GATE": "block"}, "hooks": {"PreToolUse": [
            {"matcher": "Agent", "hooks": [{"type": "command",
                                            "command": "python3 \"${CLAUDE_HOME:-$HOME/.claude}/hooks/gate.py\""}]}]}},
                                indent=1),
    })
    r = derive(root)
    steps = kinds(r, "declaration", type="todo_step", command="dev")
    assert {(s["variant"], s["step"], s["subagent_call"]) for s in steps} == {
        (0, "Step 1: Forced", None), (1, "Step 1: Parse", None), (1, "Step 2: Delegate", "ba")}
    redev = kinds(r, "declaration", type="todo_step", command="redev")
    assert redev and all(s["site"].startswith("scripts/todo/dev.py:") for s in redev)
    assert kinds(r, "declaration", type="schema", id="x.v1")
    enum = kinds(r, "declaration", type="schema_enum", schema="x.v1")
    assert enum[0]["values"] == ["pass", "fail"] and enum[0]["pointer"] == "/properties/status/enum"
    reg = kinds(r, "declaration", type="hook_registration")
    assert reg[0]["event"] == "PreToolUse" and reg[0]["matcher"] == "Agent" and reg[0]["component"] == "hooks/gate.py"
    sw = kinds(r, "declaration", type="gate_switch", name="CLAUDE_X_GATE")
    assert sw[0]["settings_value"] == "block"
    assert sw[0]["readers"][0]["default"] == "advisory" and sw[0]["readers"][0]["compared"] == ["block"]


# ---------------------------------------------------------------- deciding

def test_deciding_candidates(tmp_path):
    root = make_tree(tmp_path, {"hooks/stop.py": '''
        import json, sys
        from pathlib import Path

        def load(p):
            return json.loads(Path(p).read_text())

        def main():
            rep = Path("docs/dev/report.json")
            if not rep.exists():
                print(json.dumps({"decision": "block", "reason": "missing"}))
                return 0
            try:
                data = load("docs/dev/other.json")
            except ValueError:
                sys.exit(2)
            if data.get("status") == "pass":
                return 0
            return 2

        sys.exit(main())
    '''})
    r = derive(root)
    d = kinds(r, "deciding", component="hooks/stop.py")
    got = {(x["path"], x["decision"], x["evidence"]) for x in d}
    assert ("<proj>/docs/dev/report.json", "block", "branch") in got
    assert ("<proj>/docs/dev/other.json", "exit2", "except") in got
    assert ("<proj>/docs/dev/other.json", "exit2", "branch") in got
    assert kinds(r, "raise_handler", site="hooks/stop.py:14")[0]["catches"] == ["ValueError"]


# ------------------------------------------------------------- chain calls

def test_chain_calls_and_their_use(tmp_path):
    root = make_tree(tmp_path, {
        "scripts/resolve-dev-artifact-chain.py": "print('{}')\n",
        "commands/close.md": '''
            ```bash
            CHAIN="$(python3 scripts/resolve-dev-artifact-chain.py --task-id "$TASK_ID")"
            MODE="$(jq -r .mode <<<"$CHAIN")"
            ```
            ```bash
            python3 scripts/resolve-dev-artifact-chain.py --task-id "$TASK_ID"
            ```
        ''',
        "hooks/h.py": '''
            import json, subprocess, sys
            from pathlib import Path
            SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
            def check():
                proc = subprocess.run([sys.executable, str(SCRIPTS / "resolve-dev-artifact-chain.py")],
                                      capture_output=True, text=True)
                return json.loads(proc.stdout)["status"] == "pass" and proc.returncode == 0
        ''',
    })
    r = derive(root)
    calls = {c["site"]: c for c in kinds(r, "chain_call")}
    assert calls["commands/close.md:2"]["uses"] == ["fields"] and calls["commands/close.md:2"]["fields"] == ["mode"]
    assert calls["commands/close.md:6"]["uses"] == ["verbatim"]
    h = calls["hooks/h.py:5"]
    assert "fields" in h["uses"] and "status" in h["uses"] and h["fields"] == ["status"]


# ------------------------------------------------------------ owner output

def test_system_message_relay_and_script_prints(tmp_path):
    root = make_tree(tmp_path, {
        "hooks/coord.py": '''
            import json, subprocess
            from pathlib import Path
            HOOKS = Path(__file__).resolve().parent
            def main():
                out = subprocess.run(["bash", str(HOOKS / "phase.sh")], capture_output=True).stdout
                notice = json.loads(out)["systemMessage"]
                print(json.dumps({"systemMessage": notice}))
        ''',
        "hooks/phase.sh": '''
            NOTICE="snapshot refused, see logs/checkpoint.log"
            printf '{"systemMessage": "%s"}\\n' "$NOTICE"
        ''',
        "scripts/report.py": 'print("wrote docs/dev/final-report.md")\n',
        "commands/end.md": '```bash\npython3 scripts/report.py\n```\n',
        "settings.json": json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "python3 \"$CLAUDE_HOME/hooks/coord.py\""}]}]}}),
    })
    r = derive(root)
    sm = kinds(r, "owner_output", channel="system_message", component="hooks/phase.sh")
    assert sm and sm[0]["shown"] == "logs/checkpoint.log" and sm[0]["reaches"] == "relayed:hooks/coord.py"
    sp = kinds(r, "owner_output", channel="script_print", component="scripts/report.py")
    assert sp and sp[0]["shown"] == "docs/dev/final-report.md" and sp[0]["reaches"] == "invoked_by:commands/end.md"


# ------------------------------------------------------------------ rule 7

def test_rule7_candidates(tmp_path):
    root = make_tree(tmp_path, {
        "agents/ba.md": "---\nname: ba\n---\n",
        "agents/dev.md": "---\nname: dev\n---\n",
        "agents/qa.md": "---\nname: qa\n---\n",
        "schemas/s.v1.json": '{"$id": "s.v1", "properties": {"status": {"enum": ["pass", "fail", "blocked"]}}}',
        "commands/dev.md": '<obligation v="1">{"role": "dev", "pipeline": "dev", "artifacts": '
                           '[{"kind": "json", "path": "docs/dev/dev-report-<timestamp>.json", "schema": "s.v1"}]}'
                           '</obligation>\n',
        "hooks/roles.py": '''
            PRODUCERS = frozenset({"ba", "dev", "qa"})
            ROLE_OF = {"dev-report": "dev"}
            TERMINAL = ("pass", "fail", "blocked")
            SCHEMA = "s.v1"
        ''',
        "scripts/role.sh": '''
            case "$base" in
              dev-report*) echo dev ;;
              *) echo orchestrator ;;
            esac
        ''',
        "policies/tool-policy.v1.json": '{"roles": {"dev": {"allowed_write_path_prefixes": '
                                        '["*/docs/dev/", "*/docs/dev/dev-report-"]}}}',
    })
    r = derive(root)
    classes = {(x["class"], x["site"]) for x in kinds(r, "rule7")}
    assert ("roster_list", "hooks/roles.py:1") in classes
    assert ("path_to_role", "hooks/roles.py:2") in classes
    assert ("enum_copy", "hooks/roles.py:3") in classes
    assert ("path_to_role", "scripts/role.sh:1") in classes
    pol = kinds(r, "rule7", **{"class": "policy_file_prefix"})
    assert [p["prefix"] for p in pol] == ["*/docs/dev/dev-report-"]
    assert kinds(r, "declared_literal", site="hooks/roles.py:4")


# ------------------------------------------- acceptance-3 shaped mutations

def test_state_dir_versus_fixed_tmp_differ(tmp_path):
    root = make_tree(tmp_path, {
        "hooks/w.py": '''
            from lib.harness_state_dir import harness_state_dir
            open(harness_state_dir() + "/claude-grant.json", "w").write("{}")
        ''',
        "hooks/r.py": 'open("/tmp/claude-grant.json").read()\n',
    })
    r = derive(root)
    assert rels(r, op="write", path="<state>/claude-grant.json")
    assert rels(r, op="read", path="/tmp/claude-grant.json")
    assert not rels(r, op="read", path="<state>/claude-grant.json")


def test_tests_directories_are_out_of_scope(tmp_path):
    root = make_tree(tmp_path, {
        "hooks/tests/test_x.py": 'open("/tmp/x").read()\n',
        "scripts/install/tests/t.sh": 'cat /tmp/y\n',
        "scripts/install/land": '#!/usr/bin/env bash\necho hi > "$HOME/.claude/logs/landing.log"\n',
    })
    r = derive(root)
    comps = {x["component"] for x in rels(r)}
    assert "scripts/install/land" in comps
    assert not any("tests/" in c for c in comps)


def test_shift_empty_alternatives_and_leading_unknowns(tmp_path):
    root = make_tree(tmp_path, {
        "scripts/sweep.sh": '''
            run_path() {
              local desc="$1"; shift
              local path="$1"; shift
              find "$path" "$@" -print
            }
            run_path "old outputs" /var/tmp/codex-outputs -mtime +7
            BASE=""
            [ -n "$BASE" ] || BASE="$(cd "$(dirname "$0")/.." && pwd)"
            cat "$BASE/settings.json"
            ( cd /var/tmp && touch sub.txt )
            cat relative-before.txt
            cd "$(dirname "$0")/.." || exit 0
            cat logs/after.log
        ''',
        "scripts/cp.py": '''
            import sys
            from pathlib import Path
            def cp_file(agent, n=None):
                suffix = f"-{n}" if n else ""
                return Path(".claude/specs") / f"cp-state-{agent}{suffix}.json"
            cp_file("qa").exists()
            Path(sys.argv[1]).parent.joinpath("x.json").read_text()
        ''',
    })
    r = derive(root)
    assert rels(r, op="read", mode="list", path="/var/tmp/codex-outputs/<*>")
    assert rels(r, op="read", path="<harness>/settings.json", component="scripts/sweep.sh")
    assert not rels(r, op="read", path="/settings.json")
    assert rels(r, op="read", path="<proj>/relative-before.txt")
    assert rels(r, op="read", path="<harness>/logs/after.log")
    probes = {x["path"] for x in rels(r, op="read", mode="name", component="scripts/cp.py")}
    assert probes == {"<proj>/.claude/specs/cp-state-qa.json", "<proj>/.claude/specs/cp-state-qa-<*>.json"}
    assert rels(r, op="read", path="<*>/x.json", component="scripts/cp.py")


# ------------------------------------------------------------- patterns

def test_patterns_normalize_and_join():
    t = P.tok("home") + "/.claude/logs/x-" + P.tok("sid") + ".log"
    assert P.to_pattern(t) == ("<harness>/logs/x-<sid>.log", (), "full")
    assert P.to_pattern("docs/dev/" + P.hole("data:record"))[2] == "partial"
    assert P.to_pattern(P.hole("data:argv"))[2] == "unresolved"
    assert P.matches("<proj>/docs/dev/close-report-<task>.md", "<proj>/docs/dev/close-report-dev-<ts>.md")
    assert P.matches("<state>/claude-push-grant-<sid>-<*>.json", "<state>/claude-push-grant-<sid>-ab12.json")
    assert not P.matches("<state>/claude-grant.json", "/tmp/claude-grant.json")
    assert P.to_pattern(P.hole("data:record") + "/" + P.tok("proj") + "/x.json")[0] == "<*>/<*>/x.json"
    assert P.classify_name("DEV_SESSION_ID") == "task" and P.classify_name("session_id") == "sid"
    assert P.classify_name("SESSION_TS") == "ts" and P.classify_name("lane_id") == "lane"


# ------------------------------------------------------------ command line

def test_cli_refuses_output_inside_the_tree(tmp_path):
    root = make_tree(tmp_path, {"hooks/a.py": "x = 1\n"})
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    bad = subprocess.run([sys.executable, "-m", "tests.artifact_graph", str(root), str(root / "out.jsonl")],
                         cwd=REPO, env=env, capture_output=True, text=True)
    assert bad.returncode == 2 and not (root / "out.jsonl").exists()
    good = subprocess.run([sys.executable, "-m", "tests.artifact_graph", str(root), str(tmp_path / "o.jsonl")],
                          cwd=REPO, env=env, capture_output=True, text=True)
    assert good.returncode == 0
    lines = (tmp_path / "o.jsonl").read_text().splitlines()
    assert lines == sorted(lines)


# ------------------------------------------------------------- determinism

def test_two_runs_on_this_repository_are_byte_identical(tmp_path):
    outs = []
    for seed in ("1", "4242"):
        out = tmp_path / f"run-{seed}.jsonl"
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run([sys.executable, "-m", "tests.artifact_graph", str(REPO), str(out)],
                              cwd=REPO, env=env, capture_output=True, text=True, timeout=900)
        assert proc.returncode == 0, proc.stderr[-2000:]
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]
    assert outs[0].count(b'"kind":"relation"') > 1000
