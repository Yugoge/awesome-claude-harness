"""The privilege guard reads the message file the commit invocation names (Correction 5).

The `-F` operand is taken from the shell-tokenised commit invocation and unquoted,
so the subject line the bulk-commit check matches is the file the changelog-analyst
wrote, in every form its prose gives (CP-2's quoted literal path, the bulk loop's
`if ! ...; then` test, the recovery commit). An operand the guard cannot resolve
statically names no file it can read.
"""

import importlib.util
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent


def _guard():
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location("privilege_guard_f_operand",
                                                  HOOKS_DIR / "pretool-git-privilege-guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_prose_form_reads_the_written_message(tmp_path):
    guard = _guard()
    msg = tmp_path / "commit-msg-bulk-abc123.txt"
    msg.write_text("auto-bulk: chore(toy): sweep\n\nTask-id: bulk\n")
    forms = [
        f'git -C "/repo" commit -F "{msg}"',
        f'if ! git -C "/repo" commit -F "{msg}"; then\n  echo failed\nfi',
        f'git -C "/repo" commit --allow-empty -F "{msg}"',
        f"git commit --file={msg}",
        f"git commit -F{msg}",
    ]
    for command in forms:
        assert guard._extract_commit_message(command) == "auto-bulk: chore(toy): sweep", command


def test_an_unresolved_operand_names_no_file(tmp_path):
    guard = _guard()
    assert guard._extract_commit_message('git -C "/repo" commit -F "${MSGFILE}"') == ""
    assert guard._extract_commit_message(f'git commit -F "{tmp_path}/missing.txt"') == ""


def test_the_inline_message_still_wins():
    guard = _guard()
    assert guard._extract_commit_message("git commit -m 'auto-bulk: x'") == "auto-bulk: x"
