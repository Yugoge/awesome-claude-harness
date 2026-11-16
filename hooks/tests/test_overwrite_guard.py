#!/usr/bin/env python3
"""Tests of live code that the suite of the deleted overwrite guard also pinned.

The overwrite guard was never registered and was deleted with its route
corpus. What stays here has a live subject:

  * hooks/lib/allowlist.py's sentinel grants: a Write grant keeps its bare
    wildcard for the Write tool, and the registered PostToolUse consumer's
    bash-command matcher never matches a Write grant.
  * hooks/lib/bash_write_targets.py, the import shim over the shared parser
    (hooks/lib/shell_parse.py) that two registered hooks call: the path text
    `extract_bash_write_paths` and `extract_bash_touched_paths` return, and the
    parser's redirect and anchored-path readings behind them.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(REPO / "hooks"))
from lib import bash_write_targets as bwt  # noqa: E402
from lib.allowlist import (  # noqa: E402
    SENTINEL_GRANT_DIR,
    consume_sentinel_grant_on_terminal_result,
    match_sentinel_grant_for_bash_command,
    match_sentinel_grant_for_write,
)

NEW = "NEWCONTENT"


def original_bytes() -> str:
    """Fresh known bytes for this run; never a remembered constant."""
    return f"ORIGINAL-{uuid.uuid4().hex}"


def write_grant(task_id, session_id, operations) -> Path:
    Path(SENTINEL_GRANT_DIR).mkdir(parents=True, exist_ok=True)
    path = Path(SENTINEL_GRANT_DIR) / f"{task_id}.json"
    path.write_text(json.dumps({
        "task_id": task_id,
        "session_id": session_id,
        "allowed_operations": operations,
        "created_at": time.time(),
        "expires_at": time.time() + 300,
    }), encoding="utf-8")
    return path


def drop_grants(task_id):
    for path in Path(SENTINEL_GRANT_DIR).glob(f"{task_id}*.json"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def test_ac06_write_tool_wildcard_behaviour_is_unchanged():
    """A bare Write grant keeps its wildcard for the Write tool."""
    task_id = f"ovwtest-{uuid.uuid4().hex}"
    session_id = f"sid-{uuid.uuid4().hex}"
    try:
        write_grant(task_id, session_id, [{"op": "Write"}])
        matched = match_sentinel_grant_for_write(task_id, session_id, "/any/path/at/all")
        assert matched == {"op": "Write"}, "allowlist.py must be untouched"
    finally:
        drop_grants(task_id)


def test_ac09_the_registered_posttool_consumer_still_cannot_see_a_write_grant(tmp_path):
    """A Write grant is invisible to the registered PostToolUse consumer.

    hooks/posttool-allowlist-consume.py gates its unlink on
    match_sentinel_grant_for_bash_command, which reads the shell command's
    FIRST WORD as the op name. A {"op":"Write","target":...} grant names no
    shell command, so that matcher returns None for every replacement command
    and the consumer never spends it.
    """
    work = tmp_path / "posttool-blind"
    work.mkdir()
    target = work / "victim.txt"
    target.write_text(original_bytes(), encoding="utf-8")
    task_id = f"ovwtest-{uuid.uuid4().hex}"
    session_id = f"sid-{uuid.uuid4().hex}"
    try:
        write_grant(task_id, session_id, [{"op": "Write", "target": str(target)}])
        for command in (f"echo {NEW} > {target}", f"cp src {target}", f"tee {target}"):
            assert match_sentinel_grant_for_bash_command(task_id, command) is None, (
                "the PostToolUse consumer now matches a Write grant against a shell command")
        # And the helper it would have called is, and always was, fine.
        assert consume_sentinel_grant_on_terminal_result(task_id, "success") is True
    finally:
        drop_grants(task_id)


CONSUMERS = (
    "hooks/pretool-tool-policy.py",
)


@pytest.mark.parametrize("command, expected", [
    ("cat > /srv/foo.txt << EOF\nhello\nEOF", ["/srv/foo.txt"]),
    ("cat > /srv/a.txt << EOF\necho > /srv/b.txt\nEOF", ["/srv/a.txt"]),
    ("tee /srv/x.txt", ["/srv/x.txt"]),
    ("tee -a /srv/x.txt", ["/srv/x.txt"]),
    ("cp src dest", ["dest"]),
    ("mv src dest", ["dest"]),
    ("sed -i s/a/b/ /srv/file", ["/srv/file"]),
    ("install -m 755 src /usr/local/bin/x", ["/usr/local/bin/x"]),
    ("echo X", []),
    ('cmd <<<"hello world" > /srv/out', ["/srv/out"]),
    ("echo hello >> /var/log/app.log", ["/var/log/app.log"]),
    ("cat <<-'END'\n\techo > /tmp/inside\n\tEND", []),
    ("echo 'need >=10/3 items'", []),
    ("codex 'this is a Design gap >design fix this'", []),
    ("echo 'foo > bar'", []),
    ("(ss -ltnp 2>/dev/null || netstat -ltnp) | head", ["/dev/null"]),
    ("(cd /d && echo x > /tmp/a.txt)", ["/tmp/a.txt"]),
    ("\\cp src /tmp/a.txt", ["/tmp/a.txt"]),
    ("chmod -x /r/.git/k/rt && chmod 000 /r/a 2>/dev/null", ["/r/.git/k/rt", "/dev/null", "/r/a"]),
    ("chmod -R u+x,g-w a b; chmod --reference=r c; /bin/chmod +x d", ["a", "b", "c", "d"]),
    ("chown -h --from root:root me:me a; chown --reference r b", ["a", "b"]),
    ("chattr -R +i -a a; chattr -v 7 =e b", ["a", "b"]),
    ("setfacl -m u:x:rwx a; setfacl -Rbm g:y:r b; setfacl --set=u::r -- c", ["a", "b", "c"]),
    ("echo 'chmod -x a'; git log --grep chmod", []),
])
def test_ac10_the_shim_reads_the_parser_view(command, expected):
    assert bwt.extract_bash_write_paths(command) == expected


@pytest.mark.parametrize("command, expected", [
    ("echo x > /tmp/a", [("/tmp/a", "truncate")]),
    ("echo x >> /tmp/a", [("/tmp/a", "append")]),
    ("echo x >| /tmp/a", [("/tmp/a", "truncate")]),
    ("echo x | tee -a /tmp/a", [("/tmp/a", "append")]),
    ("truncate -s 0 /tmp/a", [("/tmp/a", "truncate")]),
    ("dd if=/tmp/s of=/tmp/a", [("/tmp/a", "truncate")]),
    ("curl -sS -o /tmp/a http://h/f", [("/tmp/a", "truncate")]),
    ("curl -sS -o/tmp/a http://h/f", [("/tmp/a", "truncate")]),
    ("wget -q -O /tmp/a http://h/f", [("/tmp/a", "truncate")]),
    ("mv /tmp/s /tmp/a", [("/tmp/a", "move-dest")]),
    ("sed -i s/a/b/ /tmp/a", [("/tmp/a", "in-place")]),
    ("cp -r /tmp/s /tmp/d", [("/tmp/d", "copy-dest")]),
    ("echo x &> /tmp/a", [("/tmp/a", "truncate")]),
    ("(cd /d && echo x > /tmp/a)", [("/tmp/a", "truncate")]),
    ("(cp /tmp/s /tmp/a)", [("/tmp/a", "copy-dest")]),
    ("\\cp /tmp/s /tmp/a", [("/tmp/a", "copy-dest")]),
    ("/bin/cp /tmp/s /tmp/a", [("/tmp/a", "copy-dest")]),
    ("/opt/x/my-cp /tmp/s /tmp/a", []),
    ("echo x > /tmp/cp", [("/tmp/cp", "truncate")]),
    ("echo x > >(cat)", []),
    ("echo 'foo > bar'", []),
    ("unlink /tmp/a", []),
])
def test_ac10_the_written_targets_carry_the_parser_mode(command, expected):
    assert [(t.path, t.mode) for t in bwt.extract_bash_write_targets_with_modes(command)] == expected


@pytest.mark.parametrize("command, expected", [
    ('rm -f /tmp/a "/tmp/b c" && mv /tmp/d /tmp/e',
     {("/tmp/a", True), ("/tmp/b c", True), ("/tmp/e", False), ("/tmp/e/d", True), ("/tmp/d", True)}),
    ("echo 'rm /tmp/a' >| /tmp/f; git rm --cached /tmp/b; /bin/rm /tmp/c", {("/tmp/f", False), ("/tmp/c", True)}),
    ("unlink /tmp/a", {("/tmp/a", True)}),
    ('mv "$X" /tmp/e', {("/tmp/e", True), ("$X", True)}),
    ("echo /tmp/y | xargs mv /tmp/a /tmp/e", {("/tmp/e", True), ("/tmp/a", True)}),
])
def test_ac10_touched_paths_mark_what_is_removed(command, expected):
    assert set(bwt.extract_bash_touched_paths(command)) == expected


def test_ac10_shim_signature_and_return_shape():
    signature = inspect.signature(bwt.extract_bash_write_paths)
    assert list(signature.parameters) == ["command"]
    assert signature.return_annotation in ("List[str]", list)
    result = bwt.extract_bash_write_paths("cat > /tmp/a.txt << EOF\nhello\nEOF")
    assert isinstance(result, list) and all(isinstance(x, str) for x in result)
    touched = bwt.extract_bash_touched_paths("rm /tmp/a; echo > /tmp/b")
    assert touched == [("/tmp/a", True), ("/tmp/b", False)]


@pytest.mark.parametrize("command, expected", [
    ("cat > /tmp/a.txt << EOF\nhello\nEOF", ["/tmp/a.txt"]),
    ("tee -a /tmp/x.txt", ["/tmp/x.txt"]),
    ("cp src dest", ["dest"]),
    ("mv src dest", ["dest"]),
    ("sed -i s/a/b/ /tmp/file", ["/tmp/file"]),
    ("install -m 755 src /usr/local/bin/x", ["/usr/local/bin/x"]),
    ("echo hello >> /var/log/app.log", ["/var/log/app.log"]),
    ("echo 'need >=10/3 items'", []),
    ("echo 'foo > bar'", []),
    ("echo X", []),
    # The shapes the consumers depend on: an absorbed ')' made
    # pretool-tool-policy.py refuse a read-only '(… 2>/dev/null) | head' by
    # inventing a write target named '/dev/null)'.
    ("ls /nope 2>&1", []),
    ("cmd --reason 'scope reduction' > /tmp/o", ["/tmp/o"]),
    ('cmd <<<"hello world" > /tmp/out', ["/tmp/out"]),
    ("cp x /tmp/my\\ file.txt", ["/tmp/my file.txt"]),
    ("diff <(sort a) <(sort b) > /tmp/d", ["/tmp/d"]),
    ("echo x > >(cat)", []),
    ("f() { echo x > /tmp/a.txt; }", ["/tmp/a.txt"]),
    ("case $x in a) echo hi;; esac", []),
    ("git status --porcelain | head -20", []),
])
def test_ac10_the_shim_names_the_paths_its_consumers_match(command, expected):
    assert bwt.extract_bash_write_paths(command) == expected


@pytest.mark.parametrize("command, expected", [
    ("(cd /d && echo x > /tmp/a.txt)", ["/tmp/a.txt"]),
    ("(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | head", ["/dev/null"]),
    ("(cp s /tmp/a.txt)", ["/tmp/a.txt"]),
    ("(sed -i s/a/b/ /tmp/file)", ["/tmp/file"]),
    ("\\cp src /tmp/a.txt", ["/tmp/a.txt"]),
    ("echo x | \\tee /tmp/a.txt", ["/tmp/a.txt"]),
    ("(diff <(sort a) <(sort b) > /tmp/d)", ["/tmp/d"]),
])
def test_ac10_grouped_and_escaped_forms_name_the_true_path(command, expected):
    """The consumers share this reader.

    A grouping or an escaped command word never hides the write nor glues a
    parenthesis to the path: each names the path the ungrouped form names.
    """
    assert bwt.extract_bash_write_paths(command) == expected


def test_ac10_quoted_paths_are_untouched_by_the_token_terminator():
    """The quoted branch of the token reader is deliberately not changed."""
    assert bwt.extract_bash_write_paths('echo x > "/tmp/report (1).txt"') == \
        ["/tmp/report (1).txt"]
    assert [t.path for t in bwt.extract_bash_write_targets_with_modes(
        "echo x > '/tmp/a (copy).txt'")] == ["/tmp/a (copy).txt"]


def py_compile_out_of_tree(path: Path, cache_root: Path):
    """`python -m py_compile` with the .pyc redirected under ``cache_root``.

    py_compile writes its .pyc even under PYTHONDONTWRITEBYTECODE; left to its
    default it lands in hooks/__pycache__/ of the checkout (and fails on a
    read-only one).
    """
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(cache_root))
    return subprocess.run([sys.executable, "-m", "py_compile", str(path)],
                          capture_output=True, text=True, env=env)


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_ac10_consumers_compile_and_import_the_shim(consumer, tmp_path):
    path = REPO / consumer
    text = path.read_text(encoding="utf-8")
    assert "extract_bash_write_paths" in text
    compiled = py_compile_out_of_tree(path, tmp_path)
    assert compiled.returncode == 0, compiled.stderr


@pytest.mark.parametrize("command", [
    "cat > /tmp/a << EOF\nhello\nEOF", "echo x >> ~/b.txt", "cp src $HOME/c", "tee -a /tmp/d < /dev/null",
    "sed -i s/a/b/ /tmp/e", "printf x | tee '/tmp/f g'", "rm /tmp/h", "mv /tmp/i /tmp/j",
])
def test_ac10_the_overnight_guard_reads_the_parser_as_the_shim_does(command, tmp_path):
    """The overnight guard reads write targets from lib/shell_parse.py directly; the paths it
    checks are the ones the shim's callers get."""
    path = REPO / "hooks" / "pretool-overnight-hook-guard.py"
    compiled = py_compile_out_of_tree(path, tmp_path)
    assert compiled.returncode == 0, compiled.stderr
    sys.path.insert(0, str(REPO / "hooks"))
    spec = importlib.util.spec_from_file_location("overnight_guard_ac10", path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    assert guard._bash_write_paths(command) == bwt.extract_bash_write_paths(command)


def test_ac10_the_cp_state_guard_imports_no_bash_reader(tmp_path):
    path = REPO / "hooks" / "pretool-cp-state-write-guard.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m and ("bash_write_targets" in m or "shell_parse" in m) for m in modules), modules
    compiled = py_compile_out_of_tree(path, tmp_path)
    assert compiled.returncode == 0, compiled.stderr


def test_ac10_the_wrapper_userintent_hook_reads_heredocs_with_the_parser(tmp_path):
    path = REPO / "hooks" / "pretool-wrapper-userintent.py"
    assert "from lib.shell_parse import without_heredoc_bodies" in path.read_text(encoding="utf-8")
    compiled = py_compile_out_of_tree(path, tmp_path)
    assert compiled.returncode == 0, compiled.stderr
    assert bwt.command_without_heredoc_bodies("cat > /tmp/a << EOF\nhello\nEOF") == \
        "cat > /tmp/a << EOF"
    assert bwt.command_without_heredoc_bodies("cat <<EOF\nkill 1\nEOF\nls") == "cat <<EOF\nls"
    assert bwt.command_without_heredoc_bodies("echo plain") == "echo plain"


@pytest.mark.parametrize("command, target", [
    ("echo NEWCONTENT > {DIR}/cp", "{DIR}/cp"),
    ("cp /bin/cp {DIR}/fresh-copy.txt", "{DIR}/fresh-copy.txt"),
])
def test_iter2_the_anchored_rule_still_names_the_whole_target(command, target, tmp_path):
    """The anchored absolute-path rule never truncates a target it must name."""
    command, target = (s.replace("{DIR}", str(tmp_path)) for s in (command, target))
    assert [t.path for t in bwt.extract_bash_write_targets_with_modes(command)] == [target]


def test_iter2_the_rejected_looser_anchor_really_would_cry_wolf():
    """A looser absolute-path anchor would cry wolf; the shipped anchored rule does not.

    A bare `[\\s;|&]` word boundary before `/…/cp` fires on ordinary read-only
    commands; the mode-aware reader's anchored rule names no target from them.
    """
    loose = re.compile(r"(?:^|[\s;|&])(?:/[\w.-]+)*/cp\b")
    cries_wolf = ["ls -la /usr/bin/cp /tmp/v", "diff /bin/cp /usr/bin/cp",
                  "cat /bin/cp > /tmp/copy", "test -x /bin/cp && echo ok"]
    for command in cries_wolf:
        assert loose.search(command), f"expected the loose anchor to match {command!r}"
        # The shipped anchored rule does not name a target from any of them.
        named = [t.path for t in bwt.extract_bash_write_targets_with_modes(command)]
        assert "/tmp/v" not in named
        assert not any(n.endswith("/cp") and "bin" in n for n in named)

    # A verb after an assignment prefix is read as the plain form is.
    assert bwt.extract_bash_write_paths("OVW=1 /bin/cp /tmp/s /tmp/v") == ["/tmp/v"]
    assert bwt.extract_bash_write_paths("OVW=1 cp /tmp/s /tmp/v") == ["/tmp/v"]


def test_iter2_redirect_operators_keep_their_operand():
    """`>|` and `>&` are redirect operators, not command separators.

    Their trailing `|`/`&` must not put the redirect TARGET at a command-word
    position; doing so truncated `echo x >| /tmp/a` to the bare name `a`.
    """
    assert [(t.path, t.mode) for t in
            bwt.extract_bash_write_targets_with_modes("echo x >| /tmp/a")] == \
        [("/tmp/a", "truncate")]
    assert [(t.path, t.mode) for t in
            bwt.extract_bash_write_targets_with_modes("echo x >|/tmp/a")] == \
        [("/tmp/a", "truncate")]
    assert [(t.path, t.mode) for t in
            bwt.extract_bash_write_targets_with_modes("echo x >& /tmp/a")] == \
        [("/tmp/a", "truncate")]
    assert bwt.extract_bash_write_targets_with_modes("echo x 2>&1") == []

