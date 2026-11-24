"""Goal 2 on three spellings the check read as a file nobody reads (rule (1) folding, E12).

Each is a reading of code shape: a temp written beside its file and renamed onto it is that file's
write, whatever names the file (a script argument, an entry a listing gave); and the shell state
root's own text (a crc32 in bash arithmetic, a printf format) names HOME's state directory, so a
notice that shows a log under it names that log. A temp nothing renames stays unread (pinned).
"""

from __future__ import annotations

from tests.artifact_graph.test_check import check, hook, make_tree, rules_on

STATE_ROOT_SH = r'''
harness_state_root() {
  local home="${_HSD_LIB%/*/*}" h=~ crc=4294967295 i c n
  n="${home##*/}"
  for ((i = 0; i < ${#home}; i++)); do printf -v c '%d' "'${home:i:1}"; crc=$((crc ^ c)); done
  printf '%s/.local/state/claude-harness/%s-%08x\n' "$h" "$n" $((crc ^ 4294967295))
}
'''


def _unread(vs) -> set:
    return {v.artifact for v in vs if v.rule == "2-unread"}


def test_a_temp_beside_a_file_named_by_a_script_argument_folds_into_it(tmp_path):
    """The rename's source is bound to the invocation's argument as its destination is."""
    m, vs = check(make_tree(tmp_path, {
        "hooks/lib/ptr.py": '''
            import os, sys
            def write(root, text):
                path = os.path.join(root, ".ptr")
                with open(f"{path}.{os.getpid()}", "w") as fh:
                    fh.write(text)
                os.replace(f"{path}.{os.getpid()}", path)
            def read(root):
                return open(os.path.join(root, ".ptr")).read()
            if __name__ == "__main__":
                root = os.path.realpath(sys.argv[2])
                write(root, "x") if sys.argv[1] == "--start" else print(read(root))
        ''',
        "hooks/init.sh": 'python3 "$(dirname "${BASH_SOURCE[0]}")/lib/ptr.py" --start "$TMPDIR/s"\n',
    }, {"env": {}, "hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": "bash ~/.claude/hooks/init.sh"}]}]}}))
    assert not [a for a in _unread(vs) if ".ptr." in a], _unread(vs)


def test_a_temp_renamed_onto_a_listed_entry_folds_into_it(tmp_path):
    """A rename onto a name only the run knows (an entry of a listing) still folds its own temp."""
    m, vs = check(make_tree(tmp_path, {
        "hooks/carry.py": hook('''
            import shutil
            new = harness_state_dir()
            for name in os.listdir("/var/old"):
                tmp = f"{os.path.join(new, name)}.carry-{os.getpid()}"
                shutil.copy2(os.path.join("/var/old", name), tmp)
                os.replace(tmp, os.path.join(new, name))
        '''),
    }))
    assert not [a for a in _unread(vs) if ".carry-" in a], _unread(vs)


def test_a_temp_nothing_renames_stays_unread(tmp_path):
    """The positive control: the same temp name with no rename is a file nobody reads."""
    m, vs = check(make_tree(tmp_path, {
        "hooks/carry.py": hook('''
            new = harness_state_dir()
            for name in os.listdir("/var/old"):
                open(f"{os.path.join(new, name)}.carry-{os.getpid()}", "w").write("x")
        '''),
    }))
    assert [a for a in _unread(vs) if ".carry-" in a], _unread(vs)


def _log_tree(tmp_path, notice: str):
    return make_tree(tmp_path, {
        "hooks/lib/harness_state_dir.sh": STATE_ROOT_SH,
        "hooks/lib/core.sh": (
            '. "${BASH_SOURCE[0]%/*}/harness_state_dir.sh"\n'
            'LOG_FILE="$(harness_state_root)/logs/snap.log"\n'
            'snap() { echo "fail" >>"$LOG_FILE"; }\n'),
        "hooks/post.sh": (
            '. "$(dirname "${BASH_SOURCE[0]}")/lib/core.sh"\n'
            f'snap || printf \'{{"systemMessage": "%s"}}\\n\' "Snapshot failed; see {notice}"\n'),
    }, {"env": {}, "hooks": {"PostToolUse": [{"matcher": "Write", "hooks": [
        {"type": "command", "command": "bash ~/.claude/hooks/post.sh"}]}]}})


def test_a_notice_that_shows_the_state_roots_log_gives_it_the_owner(tmp_path):
    m, vs = check(_log_tree(tmp_path, "${LOG_FILE}"))
    key = "<home>/.local/state/claude-harness/<*>-<*>/logs/snap.log"
    assert key in m.artifacts, sorted(k for k in m.artifacts if "snap" in k)
    assert "owner" in m.artifacts[key].consumers()
    assert "2-unread" not in rules_on(vs, key)


def test_a_notice_that_shows_another_place_leaves_the_state_roots_log_unread(tmp_path):
    """The control: a notice naming the harness home's logs/ is no reader of the state root's log."""
    m, vs = check(_log_tree(tmp_path, "~/.claude/logs/snap.log"))
    assert "2-unread" in rules_on(vs, "<home>/.local/state/claude-harness/<*>-<*>/logs/snap.log")
