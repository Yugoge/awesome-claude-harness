"""Unit tests of the derivation rules behind goal 2 (written-never-read, read-never-written).

Each test builds a small harness-shaped tree, derives the static half on it and runs the check's
derivation with no replay (test_check.py's harness), so each rule that keeps a false violation
out, or a real one in, is pinned on its own. The runtime half's rule (a temp-name generator's
random part) is pinned on a hand-written strace record.
"""

from __future__ import annotations

import json
import os

from tests.artifact_graph import check as C
from tests.artifact_graph import derive
from tests.artifact_graph.test_check import check, hook, make_tree, rules_on


def rel_paths(root, **match) -> set:
    st = derive(root)
    return {r["path"] for r in st.records if r["kind"] == "relation"
            and all(r.get(k) == v for k, v in match.items())}


def rule2(vs) -> set:
    return {(v.rule, v.artifact) for v in vs if v.rule.startswith("2-")}


SH_STATE = 'STATE="${CLAUDE_STATE_DIR:-/tmp}"\n'


# ------------------------------------------------------------------ engine (check.py)

def test_removing_a_file_reads_nothing(tmp_path):
    """An unlink is neither a read nor a write: a file only removed is no artifact, and a
    remover does not make a written file read."""
    m, vs = check(make_tree(tmp_path, {
        "hooks/w.py": hook('open(harness_state_dir() + "/claude-left.json", "w").write("{}")\n'),
        "hooks/rm.py": hook('''
            os.unlink(harness_state_dir() + "/claude-left.json")
            os.unlink(harness_state_dir() + "/claude-only-removed.json")
        '''),
    }))
    assert ("2-unread", "<state>/claude-left.json") in rule2(vs)
    assert "<state>/claude-only-removed.json" not in m.artifacts


def test_a_file_renamed_onto_another_is_its_temporary(tmp_path):
    m, vs = check(make_tree(tmp_path, {
        "hooks/w.py": hook('''
            dest = harness_state_dir() + "/claude-atomic.json"
            tmp = dest + ".tmp"
            open(tmp, "w").write("{}")
            os.replace(tmp, dest)
        '''),
        "hooks/r.py": hook('open(harness_state_dir() + "/claude-atomic.json").read()\n'),
    }))
    assert "<state>/claude-atomic.json.tmp" not in m.artifacts
    assert m.artifacts["<state>/claude-atomic.json"].producers() == ["hooks/w.py"]
    assert not rule2(vs)


def test_a_lock_file_folds_into_the_file_it_serves(tmp_path):
    m, vs = check(make_tree(tmp_path, {
        "hooks/w.sh": SH_STATE + 'exec 9>"$STATE/claude-log.jsonl.lock"\nflock -x 9\necho x >> "$STATE/claude-log.jsonl"\n',
        "hooks/r.sh": SH_STATE + 'cat "$STATE/claude-log.jsonl"\n',
    }))
    assert not [k for k in m.artifacts if k.endswith(".lock")]
    assert not rule2(vs)


def test_a_listing_reads_names_and_a_directory_test_names_no_file(tmp_path):
    """Rule (3): a scan reads the names it lists, not the files; `is_dir` names a directory,
    which is no file artifact."""
    m, vs = check(make_tree(tmp_path, {
        "hooks/w.py": hook('open(harness_state_dir() + "/claude-reports/a.json", "w").write("{}")\n'),
        "hooks/scan.py": hook('''
            import glob
            d = harness_state_dir() + "/claude-reports"
            if os.path.isdir(d):
                print(len(glob.glob(d + "/*.json")))
        '''),
    }))
    assert ("2-unread", "<state>/claude-reports/a.json") in rule2(vs)
    assert "<state>/claude-reports" not in m.artifacts
    assert not any(v.rule == "2-unwritten" for v in vs)


def test_a_file_one_component_writes_and_removes_is_its_private_scratch(tmp_path):
    """Rule (1): a file one component creates and removes, and nothing else touches, is its
    scratch; a reader that removes what another component wrote consumes it."""
    m, vs = check(make_tree(tmp_path, {
        "hooks/a.py": hook('''
            p = harness_state_dir() + "/claude-probe.json"
            open(p, "w").write("{}")
            os.unlink(p)
        '''),
        "hooks/b.py": hook('open(harness_state_dir() + "/claude-once.flag", "w").write("1")\n'),
        "hooks/c.py": hook('''
            p = harness_state_dir() + "/claude-once.flag"
            open(p).read()
            os.unlink(p)
        '''),
    }))
    assert "<state>/claude-probe.json" not in m.artifacts
    assert m.artifacts["<state>/claude-once.flag"].consumers() == ["hooks/c.py"]
    assert not rule2(vs)


def test_a_partial_writer_writes_every_member_of_its_named_family(tmp_path):
    m, vs = check(make_tree(tmp_path, {
        "hooks/w.py": hook('''
            import json
            cmd = json.load(sys.stdin)["command"]
            open(harness_state_dir() + "/claude-" + cmd + "-userintent.flag", "w").write("1")
        '''),
        "hooks/r1.py": hook('open(harness_state_dir() + "/claude-stop-userintent.flag").read()\n'),
        "hooks/r2.py": hook('open(harness_state_dir() + "/claude-commit-userintent.flag").read()\n'),
    }))
    for k in ("<state>/claude-stop-userintent.flag", "<state>/claude-commit-userintent.flag"):
        assert m.artifacts[k].producers() == ["hooks/w.py"], k
    assert not rule2(vs)


def test_a_static_id_token_stands_for_any_one_id_of_the_replay():
    """The static half names an id by its variable (`session_id` -> <sid>), the replay by its
    value (dev-<ts>); a temp name's <rand> sits inside the generator's prefix at run time."""
    assert C.matches("<proj>/.claude/r/<sid>/x.json", "<proj>/.claude/r/dev-<ts>/x.json")
    assert C.matches("<tmpdir>/<rand>/x", "<tmpdir>/tmp<rand>/x")
    assert not C.matches("<proj>/.claude/r/<sid>/x.json", "<proj>/.claude/r/a/b/x.json")


def test_a_declared_file_no_code_writes_is_the_declared_roles(tmp_path):
    """D21: the obligation that declares a file names its producer when no trace event or code
    site writes it (the role writes it with its own tool call)."""
    command = (
        "# /x\n\n"
        '<obligation v="1">\n'
        '{"task_id": "<TASK_ID>", "role": "ba", "pipeline": "x", "artifacts": '
        '[{"kind": "json", "path": "docs/dev/ba-note-<TASK_ID>.json"}]}\n'
        "</obligation>\n"
    )
    m, vs = check(make_tree(tmp_path, {
        "commands/x.md": command,
        "hooks/r.py": '''
            import json, os, sys
            t = json.load(sys.stdin)["task_id"]
            open(os.path.join(os.getcwd(), "docs/dev/ba-note-" + t + ".json")).read()
        ''',
    }))
    a = m.artifacts["<proj>/docs/dev/ba-note-<task>.json"]
    assert a.producers() == ["agent:ba"]
    assert not rule2(vs)


# ------------------------------------------------------------------ static half

def test_a_parameters_sibling_stays_in_the_parameters_directory(tmp_path):
    root = make_tree(tmp_path, {"hooks/w.py": hook('''
        from pathlib import Path
        def atomic_write(path, text):
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(text)
            os.replace(tmp, path)
        atomic_write(Path(harness_state_dir()) / "claude-w.json", "{}")
    ''')})
    assert "<state>/claude-w.json.tmp" in rel_paths(root, op="write")
    assert not [p for p in rel_paths(root) if p.startswith("<proj>/")]


def test_a_copy_into_a_directory_lands_under_its_own_name(tmp_path):
    root = make_tree(tmp_path, {"hooks/install.sh": (
        'SRC=/opt/kit/unit.service\n'
        'cp "$SRC" /etc/kit/\n'
        'cp /opt/kit/a.conf /opt/kit/b.conf /etc/kit-conf\n'
        'install -m 0644 -t /etc/kit-t /opt/kit/c.conf\n'
    )})
    writes = rel_paths(root, op="write")
    assert {"/etc/kit/unit.service", "/etc/kit-conf/a.conf", "/etc/kit-conf/b.conf",
            "/etc/kit-t/c.conf"} <= writes
    assert not writes & {"/etc/kit", "/etc/kit-conf", "/etc/kit-t"}


def test_option_words_are_no_operands(tmp_path):
    root = make_tree(tmp_path, {"hooks/s.sh": (
        'X="*.md"\n'
        'grep -r needle /opt/tree --exclude="$X"\n'
        'D=/opt/data\n'
        'stat -f -c %T "$D"\n'
        'stat -f %m "/opt/data/stamp"\n'
    )})
    paths = rel_paths(root)
    assert not [p for p in paths if "--exclude" in p or "%T" in p or "%m" in p]
    assert "/opt/data/stamp" in paths and "/opt/data" in paths


def test_a_cd_moves_the_paths_after_it_in_its_own_shell(tmp_path):
    """A cd inside a subshell group moves the relative paths after it in that group; a cd to a
    directory computed at run time leaves them under an unknown directory, not the project."""
    root = make_tree(tmp_path, {"scripts/t.sh": (
        'build() {\n'
        '  local dir="$1"\n'
        '  (\n'
        '    cd "$dir" || exit 1\n'
        '    echo x > f\n'
        '  )\n'
        '}\n'
        'build /opt/probe/repo\n'
        'cd "$(some_tool --where)" || exit 1\n'
        'echo y > g\n'
    )})
    writes = rel_paths(root, op="write")
    assert "/opt/probe/repo/f" in writes
    assert "<*>/g" in writes
    assert not {"<proj>/f", "<proj>/g"} & writes


def test_a_temp_name_generators_part_is_rand_and_its_files_are_scratch(tmp_path):
    root = make_tree(tmp_path, {
        "scripts/t.sh": 'd="$(mktemp -d)"\necho x > "$d/probe.txt"\ncat "$d/probe.txt"\n',
        "scripts/t.py": '''
            import tempfile, os
            d = tempfile.mkdtemp(prefix="kit-probe-")
            open(os.path.join(d, "out.json"), "w").write("{}")
        ''',
    })
    writes = rel_paths(root, op="write")
    assert "<tmpdir>/tmp.<rand>/probe.txt" in writes
    assert "<tmpdir>/kit-probe-<rand>/out.json" in writes
    m, vs = check(root)
    assert not [k for k in m.artifacts if "<rand>" in k]
    assert not rule2(vs)


def test_an_upper_case_brace_name_in_a_command_block_is_a_placeholder(tmp_path):
    root = make_tree(tmp_path, {"commands/c.md": (
        "# /c\n\n```bash\njq . docs/clean/context-{REQUEST_ID}.json > docs/clean/out-{REQUEST_ID}.json\n```\n"
    )})
    paths = rel_paths(root)
    assert "<proj>/docs/clean/context-<task>.json" in paths
    assert not [p for p in paths if "{" in p]


# ------------------------------------------------------------------ runtime half (trace.py)

def test_a_write_only_exclusive_create_keeps_its_name(tmp_path):
    """Only a temp-name generator's create (read-write, exclusive, 0600: mkstemp, mktemp) has a
    random part; code that claims a name of its own exclusively (O_WRONLY|O_EXCL) keeps it."""
    from tests.replay import trace
    proj = "/sbx/proj"
    out = tmp_path / "out"
    out.mkdir()
    lay = {"harness": "/sbx/hm/.claude", "project": proj, "origin": "/sbx/origin", "state": "/sbx/state",
           "home": "/sbx/hm", "sb": "/sbx", "markers": "/sbx/markers", "temp_dirs": ["/sbx/tmp"],
           "scratch": []}
    (out / "ids.json").write_text(json.dumps({"layout": lay, "ids": {}, "window": [0, None]}))
    (out / "markers.jsonl").write_text("")
    raw = tmp_path / "raw.txt"
    raw.write_text(
        f'100 openat(AT_FDCWD</>, "{proj}/.claude/reg/product-owner.json", O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC, 0600)'
        f' = 3<{proj}/.claude/reg/product-owner.json>\n'
        '100 openat(AT_FDCWD</>, "/sbx/tmp/tmpk3j9x2qa", O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC, 0600)'
        ' = 4</sbx/tmp/tmpk3j9x2qa>\n'
        '100 +++ exited with 0 +++\n')
    trace.parse(str(raw), str(out))
    rels = (out / "relations.tsv").read_text()
    assert "create\t<project>/.claude/reg/product-owner.json" in rels
    assert "create\t/sbx/tmp/<rand>" in rels and "tmpk3j9x2qa" not in rels
    assert "<rand>-owner" not in rels


def test_rule2_source_holds_no_name_lists():
    here = os.path.dirname(os.path.abspath(__file__))
    text = open(os.path.join(here, "check.py"), encoding="utf-8").read()
    # the lock and directory-test rules are patterns, never names of files
    assert "_LOCK = re.compile" in text and "_DIR_TEST = re.compile" in text


def test_a_scripts_argument_is_each_value_its_invocations_pass(tmp_path):
    """E1's argv class: a path a script takes as sys.argv[N] or $N is the path each invocation
    passes there (a hook's Popen, a command block's call)."""
    root = make_tree(tmp_path, {
        "scripts/watch.py": '''
            import sys
            open(sys.argv[2], "w").write("1")
        ''',
        "scripts/apply.sh": 'jq . "$1" > /dev/null\n',
        "hooks/start.py": hook('''
            import subprocess
            pid = harness_state_dir() + "/claude-watch.pid"
            subprocess.Popen(["python3", os.path.join(os.path.dirname(__file__), "..", "scripts", "watch.py"), "30", pid])
            open(pid).read()
        '''),
        "commands/c.md": "# /c\n\n```bash\nbash ~/.claude/scripts/apply.sh docs/dev/plan.json\n```\n",
    })
    st = derive(root)
    rel = {(r["component"], r["op"], r["path"]) for r in st.records if r["kind"] == "relation"}
    assert ("scripts/watch.py", "write", "<state>/claude-watch.pid") in rel
    assert ("scripts/apply.sh", "read", "<proj>/docs/dev/plan.json") in rel
    m, vs = check(root)
    assert m.artifacts["<state>/claude-watch.pid"].producers() == ["scripts/watch.py"]
    assert not rule2(vs) - {("2-unwritten", "<proj>/docs/dev/plan.json")}


def test_a_relative_path_an_output_shows_is_where_its_code_runs(tmp_path):
    """E12: `see logs/landing.log` in a notice the Stop hook relays names the log its own code
    writes in the directory it runs in (the harness home), not one under the project."""
    settings = {"env": {}, "hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "bash ~/.claude/hooks/relay.sh"}]}]}}
    m, vs = check(make_tree(tmp_path, {
        "scripts/install/land": (
            '#!/bin/bash\ncd -P "${BASH_SOURCE[0]%/*}/../.." || exit 0\nLOG=logs/landing.log\n'
            'echo "result=ok" >> "$LOG"\nprintf \'%s\\n\' "Landing failed (see logs/landing.log)"\n'),
        "hooks/relay.sh": (
            'NOTICE="$(bash "$(dirname "${BASH_SOURCE[0]}")/../scripts/install/land")"\n'
            'printf \'{"systemMessage": "%s"}\\n\' "$NOTICE"\n'),
    }, settings))
    a = m.artifacts["<harness>/logs/landing.log"]
    assert "owner" in a.consumers()
    assert not rule2(vs)


def test_inputs_tracked_project_files_local_layers_and_files_a_message_tells_the_user_to_write(tmp_path):
    root = make_tree(tmp_path, {
        "PUBLIC-CORE.md": "# tracked\n",
        "scripts/check.sh": 'top="$(git rev-parse --show-toplevel)"\ncat "$top/PUBLIC-CORE.md"\n',
        "hooks/layers.py": '''
            import os
            from pathlib import Path
            home = Path(os.path.expanduser("~/.claude"))
            for name in ("settings.json", "settings.local.json"):
                (home / name).read_text()
        ''',
        "scripts/drift.sh": (
            'top="$(git rev-parse --show-toplevel)"\nf="$top/.claude-cycle-baseline-sha"\n'
            'if [ -f "$f" ]; then B="$(cat "$f")"; else\n'
            '  echo "no baseline (use --baseline <sha> or write a SHA into .claude-cycle-baseline-sha)" >&2; fi\n'),
        # the harness writes into both directories, so neither is a directory nothing writes
        "hooks/state.py": '''
            import os
            for p in (os.path.join(os.getcwd(), "claude-own.json"), os.path.expanduser("~/.claude/claude-own.json")):
                open(p, "w").write("{}")
                open(p).read()
        ''',
    })
    m, vs = check(root)
    for k in ("<proj>/PUBLIC-CORE.md", "<harness>/settings.local.json", "<proj>/.claude-cycle-baseline-sha"):
        assert k not in m.artifacts, k
    assert not rule2(vs)


def test_a_project_resolvers_harness_home_tier_names_the_projects_file(tmp_path):
    """A resolver whose last tier is the harness home yields <proj>/x and <harness>/x at one
    site: one file, the project's."""
    m, vs = check(make_tree(tmp_path, {
        "hooks/w.py": '''
            import os
            from pathlib import Path
            def project_dir():
                env = os.environ.get("CLAUDE_PROJECT_DIR")
                if env:
                    return Path(env)
                return Path(os.path.expanduser("~/.claude"))
            (project_dir() / "docs" / "dev" / "note-x.md").write_text("x")
        ''',
        "hooks/r.py": '''
            import os
            from pathlib import Path
            (Path(os.environ["CLAUDE_PROJECT_DIR"]) / "docs" / "dev" / "note-x.md").read_text()
        ''',
    }))
    assert "<harness>/docs/dev/note-x.md" not in m.artifacts
    assert m.artifacts["<proj>/docs/dev/note-x.md"].producers() == ["hooks/w.py"]
    assert not rule2(vs)


def test_files_of_a_tree_a_component_creates_whole_are_its(tmp_path):
    m, vs = check(make_tree(tmp_path, {
        "scripts/boot.sh": 'for c in python3 python3.12; do PICK="$c"; done\n"$PICK" -m venv "$HOME/.claude/venv"\n',
        "scripts/use.sh": '. "$HOME/.claude/venv/bin/activate"\ncat "$HOME/.claude/venv/pyvenv.cfg"\n',
    }))
    assert m.artifacts["<harness>/venv/pyvenv.cfg"].producers() == ["scripts/boot.sh"]
    assert not rule2(vs)


def test_more_inputs_and_scratch_and_roots(tmp_path):
    """A sentinel the reader's docstring says the user creates by hand (on the lines after the
    one naming it) is an input; two components' temp files share a pattern but are two files,
    each its run's scratch; `git -C <the script's own dir> rev-parse --show-toplevel` is the
    harness's checkout, not the project."""
    root = make_tree(tmp_path, {
        "hooks/guard.py": '''
            """Blocks edits unless the sentinel `.claude/.edit-allow-sentinel` exists.

            The user creates this file by hand
            when they want to edit.
            """
            import os
            print(os.path.exists(os.path.join(os.getcwd(), ".claude", ".edit-allow-sentinel")))
        ''',
        "scripts/a.sh": 't="$(mktemp)"\necho a > "$t"\n',
        "scripts/b.sh": 't="$(mktemp)"\necho b > "$t"\n',
        "scripts/prune.sh": (
            'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
            'ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"\n'
            'for f in "$ROOT"/bookmark-*.json; do cat "$f"; done\n'),
    })
    reads = rel_paths(root, op="read")
    assert "<harness>/bookmark-<*>.json" in reads and "<proj>/bookmark-<*>.json" not in reads
    m, vs = check(root)
    assert "<proj>/.claude/.edit-allow-sentinel" not in m.artifacts
    assert not [k for k in m.artifacts if "<rand>" in k]
    assert not [v for v in vs if v.rule in ("1-producers", "2-unwritten")]


def test_a_declared_marker_is_a_whole_word(tmp_path):
    """CLOSE_REPORT_APPEND_ inside an environment variable's name or an error text another
    script prints is another word, not a reader of the response line that may carry it."""
    command = (
        "# /x\n\n"
        '<obligation v="1">\n'
        '{"task_id": "<TASK_ID>", "role": "qa", "pipeline": "x", "artifacts": '
        '[{"kind": "response_line", "terminal_line_regex": "^(DONE: YES|DONE_REPORT_APPEND_(ERROR|CRITICAL): .*)$"}]}\n'
        "</obligation>\n"
    )
    st = derive(make_tree(tmp_path, {
        "commands/x.md": command,
        "scripts/append.py": '''
            import os
            T = os.environ.get("DONE_REPORT_APPEND_LOCK_SECONDS")
            print(f"DONE_REPORT_APPEND_ERROR: append: {T}")
        ''',
        "hooks/verdict.py": '''
            import re
            RX = re.compile(r"^(DONE: YES|DONE_REPORT_APPEND_(ERROR|CRITICAL): )")
        ''',
    }))
    sites = {r["component"] for r in st.records if r["kind"] == "declared_literal"}
    assert "hooks/verdict.py" in sites and "scripts/append.py" not in sites


def test_an_argument_list_expansion_is_no_operand_and_a_git_entry_is_gits(tmp_path):
    root = make_tree(tmp_path, {"scripts/upd.sh": (
        'STATE="${CLAUDE_STATE_DIR:-/tmp}/claude-st.json"\nFILTER=".a = 1"\nARGS=(--arg k v)\n'
        'jq "${ARGS[@]}" "$FILTER" "$STATE" > "$STATE.tmp" && mv "$STATE.tmp" "$STATE"\n'
        'top="$(git rev-parse --show-toplevel)"\n[ -e "$top/.git" ] || exit 0\n'),
    })
    reads = rel_paths(root, op="read")
    assert "<state>/claude-st.json" in reads and not [p for p in reads if "= 1" in p]
    m, _vs = check(root)
    assert "<proj>/.git" not in m.artifacts


def test_a_payload_cwd_tier_beside_the_harness_home_tier_is_one_file(tmp_path):
    m, _vs = check(make_tree(tmp_path, {"hooks/r.py": '''
        import json, os, sys
        from pathlib import Path
        payload = json.load(sys.stdin)
        root = Path(payload.get("cwd") or os.path.expanduser("~/.claude"))
        (root / ".claude" / "claude-run-state.json").read_text()
    ''',
        # the harness writes into its home's .claude directory, so it is no directory nothing writes
        "hooks/own.py": '''
        import os
        p = os.path.expanduser("~/.claude/.claude/claude-own.json")
        open(p, "w").write("{}")
        open(p).read()
    '''}))
    assert not [k for k in m.artifacts if k.startswith("<harness>/") and "claude-run-state" in k]


def _run(events: list) -> C.Run:
    """A replay reduced to its relation events (comp, op, pattern, raw)."""
    r = C.Run("fake", "shipped", "")
    r.events = [{"comp": c, "origin": c, "actor": c if c.startswith("agent:") else "", "op": op,
                 "pattern": pat, "event": i + 1, "bulk": False, "raw": raw} for i, (c, op, pat, raw) in enumerate(events)]
    r.env = {"CLAUDE_STATE_DIR": "/sbx/state"}
    return r


def test_a_reader_of_an_id_keyed_file_reads_each_instance_and_ids_are_never_temp_names(tmp_path):
    """A code site reading docs/dev/context-<task>.json reads a /dev task's context-<ts>.json and
    a fan-out lane's context-dev-<ts>-<lane>.json alike; a write keyed by an id joins no more
    than one instance; neither an id token nor <*> stands for a temp-name generator's part."""
    root = make_tree(tmp_path, {"scripts/scan.py": '''
        import os, sys
        task_id = sys.argv[1]
        open(os.path.join(os.getcwd(), "docs", "dev", "context-" + task_id + ".json")).read()
        open(os.path.join(os.getcwd(), "out", task_id, ".gitignore"), "w").write("*")
        open(os.path.join(os.getcwd(), "docs", "dev", "note-" + task_id + ".json"), "w").write("{}")
    '''})
    st = derive(root)
    run = _run([
        ("agent:ba", "create", "<project>/docs/dev/context-<ts>.json", "/p/docs/dev/context-1.json"),
        ("agent:ba", "create", "<project>/docs/dev/context-dev-<ts>-<lane>.json", "/p/docs/dev/context-2.json"),
        ("agent:qa", "create", "<project>/out/cache-<rand>/.gitignore", "/p/out/cache-x/.gitignore"),
        ("scripts/scan.py", "create", "<project>/docs/dev/note-<ts>.json", "/p/docs/dev/note-1.json"),
        ("scripts/scan.py", "create", "<project>/docs/dev/note-dev-<ts>-<lane>.json", "/p/docs/dev/note-2.json"),
    ])
    m = C.derive(str(root), st, [run])
    vs = C.violations(m, st.records)
    for k in ("<proj>/docs/dev/context-<ts>.json", "<proj>/docs/dev/context-dev-<ts>-<lane>.json"):
        assert "scripts/scan.py" in m.artifacts[k].consumers(), k
    assert not [k for k, a in m.artifacts.items() if "<rand>" in k and "scripts/scan.py" in a.producers()]
    assert not [v for v in vs if v.rule == "2-unwritten" and "context" in v.artifact]
    # the id-keyed write the replays made two instances of names no static artifact of its own
    assert "<proj>/docs/dev/note-<task>.json" not in m.artifacts


def test_an_empty_default_is_no_value_and_a_bare_dotfile_in_an_unknown_directory_joins_nothing(tmp_path):
    """`${TOKEN:-}` says unset is empty, not what TOKEN holds: `$DIR/${TOKEN}.grant` is a file
    of an unknown name, not `.grant`; `<*>/.gitignore` (a directory the static half cannot root)
    does not join the harness's own .gitignore."""
    root = make_tree(tmp_path, {
        "hooks/k.sh": 'tok="${CLAUDE_X_TOKEN:-}"\ncat "${TMPDIR:-/tmp}/claude-x-grants/${tok}.grant"\n',
        "scripts/gi.sh": 'cd "$(some_tool --dir)" || exit 1\ngrep -q x .gitignore\n',
        "hooks/own.sh": 'echo x >> "$HOME/.claude/.gitignore"\ncat "$HOME/.claude/.gitignore"\n',
    })
    assert "<tmpdir>/claude-x-grants/.grant" not in rel_paths(root)
    m, _vs = check(root)
    assert "scripts/gi.sh" not in m.artifacts["<harness>/.gitignore"].consumers()


def test_a_branch_on_a_directory_test_reads_no_file_and_an_unknown_directory_joins_no_instance(tmp_path):
    root = make_tree(tmp_path, {
        "scripts/mig.sh": ('top="$(git rev-parse --show-toplevel)"\nif [[ ! -d "$top/legacy" ]]; then exit 1; fi\n'
                           'if [[ "$top/legacy" -nt "$top/new" ]]; then echo newer; fi\n'),
        "scripts/gi.sh": 'cd "$(some_tool --dir)" || exit 1\ngrep -q x .gitignore\n',
    })
    st = derive(root)
    run = _run([("hooks/a.sh", "write", "<project>/.gitignore", "/p/.gitignore"),
                ("hooks/b.sh", "write", "<harness>/.gitignore", "/h/.gitignore")])
    m = C.derive(str(root), st, [run])
    assert "<proj>/legacy" not in m.artifacts
    for k in ("<proj>/.gitignore", "<harness>/.gitignore"):
        assert k not in m.artifacts or "scripts/gi.sh" not in m.artifacts[k].consumers(), k


def test_a_declared_path_code_tests_as_a_directory_gets_no_producer_of_its_own(tmp_path):
    command = (
        "# /x\n\n"
        '<obligation v="1">\n'
        '{"task_id": "<TASK_ID>", "role": "spec", "pipeline": "x", "artifacts": '
        '[{"kind": "views", "path": "docs/dev/specs/<TASK_ID>/views"}]}\n'
        "</obligation>\n"
    )
    m, vs = check(make_tree(tmp_path, {
        "commands/x.md": command,
        "hooks/r.py": '''
            import json, os, sys
            t = json.load(sys.stdin)["task_id"]
            print(os.path.isdir(os.path.join(os.getcwd(), "docs/dev/specs", t, "views")))
        ''',
    }))
    assert not [v for v in vs if v.rule == "2-unread" and v.artifact.endswith("/views")]


def test_a_parameters_directory_or_dot_is_the_parameters_directory(tmp_path):
    """`os.path.dirname(path) or "."` for a parameter: the "." is the directory of a bare relative
    path, which the caller's value already gives; an absolute argument keeps its own directory."""
    root = make_tree(tmp_path, {"hooks/rm.py": hook('''
        def unlink_verified(path):
            fd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
            os.stat(os.path.basename(path), dir_fd=fd)
        unlink_verified(harness_state_dir() + "/claude-pointer.json")
    ''')})
    paths = rel_paths(root, op="read")
    assert "<state>/claude-pointer.json" in paths and "<proj>/claude-pointer.json" not in paths
