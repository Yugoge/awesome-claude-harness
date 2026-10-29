"""Unit tests of the artifact check's derivation rules (tests/artifact_graph/check.py).

Each test builds a small harness-shaped tree, derives the static half on it and
runs the check's derivation with no replay (the union then holds the static
relations alone, E1's fallback), so every rule is pinned without strace. The
replayed check over the real tree is tests/test_artifact_graph.py.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

from tests.artifact_graph import check as C
from tests.artifact_graph import derive

ROOT_LIBS = {
    "hooks/lib/harness_state_dir.py": '''
        import os
        _ENV = "CLAUDE_STATE_DIR"
        def harness_state_dir():
            v = os.environ.get(_ENV, "")
            return v if v.startswith("/") else "/tmp"
    ''',
    "agents/ba.md": "---\nname: ba\n---\n# BA\n",
    "agents/qa.md": "---\nname: qa\n---\n# QA\n",
}


def make_tree(tmp_path: Path, files: dict, settings: dict | None = None) -> Path:
    root = tmp_path / "tree"
    for rel, text in {**ROOT_LIBS, **files}.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    (root / "settings.json").write_text(json.dumps(settings or {"env": {}, "hooks": {}}), encoding="utf-8")
    return root


def check(root: Path) -> tuple:
    st = derive(root)
    m = C.derive(str(root), st, [])
    return m, C.violations(m, st.records)


def rules_on(vs, artifact: str) -> set:
    return {v.rule for v in vs if v.artifact == artifact}


STATE_HOOK = (
    "import os, sys\n"
    "sys.path.insert(0, os.path.dirname(__file__))\n"
    "from lib.harness_state_dir import harness_state_dir\n"
)


def hook(body: str) -> str:
    """A hook that resolves the state dir as the harness does, then `body`."""
    return STATE_HOOK + textwrap.dedent(body).lstrip("\n")


def test_second_writer_unread_and_unwritten(tmp_path):
    root = make_tree(tmp_path, {
        "hooks/a.py": hook('''
            open(harness_state_dir() + "/claude-shared.json", "w").write("{}")
        '''),
        "hooks/b.py": hook('''
            open(harness_state_dir() + "/claude-shared.json", "w").write("{}")
            open(harness_state_dir() + "/claude-nobody-reads.json", "w").write("{}")
        '''),
        "hooks/c.py": hook('''
            import json
            if not json.load(open(harness_state_dir() + "/claude-shared.json")):
                sys.exit(2)
            open(harness_state_dir() + "/claude-nobody-writes.json").read()
        '''),
    })
    m, vs = check(root)
    assert m.artifacts["<state>/claude-shared.json"].producers() == ["hooks/a.py", "hooks/b.py"]
    assert "1-producers" in rules_on(vs, "<state>/claude-shared.json")
    assert "2-unread" in rules_on(vs, "<state>/claude-nobody-reads.json")
    assert "2-unwritten" in rules_on(vs, "<state>/claude-nobody-writes.json")
    # one producer, one reader: no violation of goals 1-2 on a single-writer artifact
    m2, vs2 = check(make_tree(tmp_path / "ok", {
        "hooks/a.py": hook('open(harness_state_dir() + "/claude-one.json", "w").write("{}")\n'),
        "hooks/c.py": hook('open(harness_state_dir() + "/claude-one.json").read()\n'),
    }))
    assert not rules_on(vs2, "<state>/claude-one.json")


def test_reader_under_tmp_of_a_state_dir_file(tmp_path):
    root = make_tree(tmp_path, {
        "hooks/w.py": hook('open(harness_state_dir() + "/claude-split.json", "w").write("{}")\n'),
        "hooks/r.py": 'open("/tmp/claude-split.json").read()\n',
    })
    _m, vs = check(root)
    assert "8-state-dir" in rules_on(vs, "<state>/claude-split.json")
    assert "2-unwritten" in rules_on(vs, "/tmp/claude-split.json")


def test_hand_written_role_list_is_a_list_that_repeats_a_declaration(tmp_path):
    root = make_tree(tmp_path, {"hooks/roles.py": '''
        ROLES = ("ba", "qa")
        print(ROLES)
    '''})
    _m, vs = check(root)
    assert any(v.rule == "7-list" and v.artifact == "hooks/roles.py" for v in vs)


def test_two_deciders_with_rules_of_their_own_and_their_positions(tmp_path):
    settings = {"env": {}, "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/stop-x.py"}]}],
        "PreToolUse": [{"matcher": "Agent", "hooks": [{"type": "command",
                                                        "command": "python3 ~/.claude/hooks/g1.py"}]}],
    }}
    decide = hook('''
        import json
        if not os.path.exists(harness_state_dir() + "/claude-gate.json"):
            sys.exit(2)
    ''')
    root = make_tree(tmp_path, {
        "hooks/w.py": hook('open(harness_state_dir() + "/claude-gate.json", "w").write("{}")\n'),
        "hooks/g1.py": decide,
        "hooks/stop-x.py": decide,
        "scripts/also.py": decide,
    }, settings)
    m, vs = check(root)
    a = m.artifacts["<state>/claude-gate.json"]
    positions = {(d.who, d.position) for d in a.decisions}
    assert ("hooks/g1.py", "G1") in positions
    assert ("scripts/also.py", "elsewhere") in positions
    assert "4-one-rule" in rules_on(vs, "<state>/claude-gate.json")
    assert rules_on(vs, "<state>/claude-gate.json") & {"6-recheck", "6-move"}


def test_map_text_is_sorted_and_split_for_comments(tmp_path):
    root = make_tree(tmp_path, {
        "hooks/b.py": hook('open(harness_state_dir() + "/claude-b.json", "w").write("{}")\n'),
        "hooks/a.py": hook('open(harness_state_dir() + "/claude-a.json", "w").write("{}")\n'),
    })
    m, vs = check(root)
    text = C.map_text(m, vs)
    heads = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert heads == sorted(heads) and len(heads) == 2
    assert C.map_text(m, vs) == text
    big = "\n\n".join(f"## artifact {i:04d}\nproducers: x\nreaders: y" for i in range(400))
    parts = C.chunks(big, limit=4000)
    assert len(parts) > 1 and all(len(p.encode("utf-8")) <= 4000 for p in parts)
    assert "".join(parts).count("## artifact") == 400


def test_source_holds_no_name_lists():
    """Row 19: the check's source holds no list of artifact names, roles or hook names."""
    here = Path(__file__).resolve().parent
    tree = here.parents[1]
    roles = {p.stem for p in (tree / "agents").glob("*.md")
             if p.read_text(encoding="utf-8", errors="replace").startswith("---")}
    hooks = {p.name for p in (tree / "hooks").iterdir() if p.is_file()}
    for name in ("check.py", "runtime.py"):
        text = (here / name).read_text(encoding="utf-8")
        for role in roles:
            assert f'"{role}"' not in text and f"'{role}'" not in text, (name, role)
        for hook in hooks:
            assert hook not in text, (name, hook)
    for name in ("differential.py",):
        text = (tree / "tests" / "replay" / name).read_text(encoding="utf-8")
        for hook in hooks:
            assert hook not in text, (name, hook)
    assert os.path.basename(__file__) == "test_check.py"
