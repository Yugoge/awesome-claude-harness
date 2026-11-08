"""The execution-boundary analyzer (pretool-bash-safety.sh's removal policy) treats a shell's
script operand spelled through the quoted CLAUDE_HOME channel as the named script file it is,
as it treats a literal path (P2 R6).

commands/test.md's Step 3 block runs the harness migration script and, in an echo, names
`rm -rf test/`, which is removal evidence for the whole command. origin/master ran the script
as `~/.claude/scripts/migrate-test-to-tests.sh` (a literal path); R6 respelled it to
`bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/migrate-test-to-tests.sh"`. Both spellings get the
same decision from the analyzer and from the hook; a dynamic operand that is not exactly the
quoted channel with plain components, and a removal program behind the channel, stay refused.

ZERO EXECUTION: every command below is data handed to the analyzer or the hook as JSON stdin.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = Path(HERE).parents[1]
sys.path.insert(0, str(REPO_ROOT / "hooks" / "lib"))
sys.path.insert(0, HERE)

import bash_execution_boundary as eb  # noqa: E402
from pol_replay_harness import run_hook_command  # noqa: E402

CHANNEL = '"${CLAUDE_HOME:-$HOME/.claude}/'
SCRIPT = "scripts/migrate-test-to-tests.sh"


def _step3_block() -> str:
    text = (REPO_ROOT / "commands" / "test.md").read_text(encoding="utf-8")
    start = text.index("```bash\n", text.index("### Step 3")) + len("```bash\n")
    block = text[start:text.index("```", start)].strip()
    assert "bash " + CHANNEL + SCRIPT + '" --project-root' in block and "rm -rf test/" in block, block
    return block


def _old_spelling(block: str) -> str:
    old = block.replace("bash " + CHANNEL + SCRIPT + '"', "~/.claude/" + SCRIPT)
    return old.replace("bash ${CLAUDE_HOME:-$HOME/.claude}/" + SCRIPT, "~/.claude/" + SCRIPT)


def test_step3_block_gets_the_same_decision_in_both_spellings():
    new = _step3_block()
    old = _old_spelling(new)
    assert "CLAUDE_HOME" not in old and "  ~/.claude/" + SCRIPT + ' --project-root "$(pwd)"' in old
    for command in (new, old):
        result = eb.analyze(command)
        assert result["allowed"] is True, (command, result["verdict"], result.get("reason"))
    codes = [run_hook_command(command)[0] for command in (new, old)]
    assert codes == [0, 0], codes


def test_other_dynamic_or_removal_operands_stay_refused():
    evidence = '; echo "rm -rf test/"'
    for operand in (
        "${CLAUDE_HOME:-$HOME/.claude}/" + SCRIPT,       # unquoted
        CHANNEL + '../x.sh"',                             # leaves the harness home
        CHANNEL + '.hidden/x.sh"',                        # a dot component
        '"${CLAUDE_HOME:-$HOME/.claude}"',                # no file
        CHANNEL + SCRIPT + '$(id)"',                      # a further expansion
        '"$X/' + SCRIPT + '"',                            # another variable
    ):
        result = eb.analyze("bash " + operand + evidence)
        assert result["allowed"] is False and result["verdict"] == eb.UNRESOLVED, (operand, result)
    removal = eb.analyze("bash " + CHANNEL + 'bin/rm" -rf x')
    assert removal["allowed"] is False and "removal_reference" in removal["reason"], removal
    code, _out, _err = run_hook_command("bash " + CHANNEL + '../x.sh"' + evidence)
    assert code == 2
