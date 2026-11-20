"""The register of accepted deciding reads (tests/artifact_graph/register.py).

A rule (6) violation an entry names (artifact, reader, event and tool, mutation) is not reported and is
counted as covered; an entry needs a reason; an entry that covers no current violation fails the check
as stale; no other rule can be covered.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.artifact_graph import check as C
from tests.artifact_graph import register as R
from tests.artifact_graph.test_check import check, hook, make_tree, rules_on

FLAG = "<state>/claude-intent.flag"
SETTINGS = {"env": {}, "hooks": {"SessionStart": [{"matcher": "startup", "hooks": [
    {"type": "command", "command": 'python3 "$CLAUDE_HOME/hooks/ask-guard.py"'}]}]}}
DECIDER = hook('''
    if not os.path.exists(harness_state_dir() + "/claude-intent.flag"):
        sys.exit(2)
''')


def entry(**over) -> dict:
    e = {"artifact": FLAG, "reader": "hooks/ask-guard.py", "event": "SessionStart", "tool": "startup",
         "mutations": ["removed", "invalid", "any"], "reason": "the flag is the reference the ask is checked against"}
    return {**e, **over}


def tree(tmp_path, entries=None) -> Path:
    files = {"commands/x.md": '# /x\n\n```bash\nprintf true > "${CLAUDE_STATE_DIR}/claude-intent.flag"\n```\n',
             "hooks/ask-guard.py": DECIDER}
    if entries is not None:
        files[R.PATH] = json.dumps({"entries": entries})
    return make_tree(tmp_path, files, SETTINGS)


def test_without_an_entry_the_read_is_a_rule_six_violation(tmp_path):
    m, vs = check(tree(tmp_path))
    assert rules_on(vs, FLAG) & set(R.COVERABLE) and not m.covered


def test_an_entry_covers_its_read_and_the_check_counts_it(tmp_path):
    m, vs = check(tree(tmp_path, [entry()]))
    assert not rules_on(vs, FLAG) & set(R.COVERABLE)
    assert m.covered and all(v.reader == "hooks/ask-guard.py" for v, _e in m.covered)
    assert C.counts(m, vs)["register_covered"] == len(m.covered)
    assert f"{len(m.covered)} covered by the register" in C.map_text(m, vs)


@pytest.mark.parametrize("over", [{"reader": "hooks/other.py"}, {"tool": "resume"}, {"event": "Stop"},
                                  {"artifact": "<state>/claude-other.flag"}, {"mutations": ["unreadable"]}])
def test_an_entry_covers_only_what_it_names_and_is_then_stale(tmp_path, over):
    m, vs = check(tree(tmp_path, [entry(**over)]))
    assert rules_on(vs, FLAG) & set(R.COVERABLE) and not m.covered
    assert "register-stale" in rules_on(vs, R.PATH)


@pytest.mark.parametrize("reason", ["", "   "])
def test_an_entry_without_a_reason_is_refused(tmp_path, reason):
    m, vs = check(tree(tmp_path, [entry(reason=reason)]))
    assert "register-invalid" in rules_on(vs, R.PATH) and not m.covered
    assert rules_on(vs, FLAG) & set(R.COVERABLE)


def test_no_rule_but_six_can_be_covered():
    vs = [C.Violation(rule, FLAG, "x", reader="hooks/ask-guard.py", how="removed", at=(("SessionStart", "startup"),))
          for rule in ("1-producers", "2-unwritten", "4-one-rule", "5-chain-verbatim", "7-list", "8-state-dir")]
    six = C.Violation("6-move", FLAG, "x", reader="hooks/ask-guard.py", how="removed", at=(("SessionStart", "startup"),))
    assert R.apply([six], [dict(entry(), index=0)], [], C.Violation)[1]  # the same fields on rule (6): covered
    left, covered = R.apply(vs, [dict(entry(), index=0)], [], lambda r, a, msg: C.Violation(r, a, msg))
    assert not covered and {v.rule for v in left} >= {v.rule for v in vs} | {"register-stale"}
