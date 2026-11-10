"""The execution-boundary analyzer (pretool-bash-safety.sh's removal policy) treats a shell's
script operand spelled through the quoted CLAUDE_HOME channel as the named script file it is,
as it treats a literal path (P2 R6).

STEP3_BLOCK is the block commands/test.md ran at its Step 3 before the step moved into
scripts/steps/test-prepare.py: it runs the harness migration script and, in an echo, names
`rm -rf test/`, which is removal evidence for the whole command. origin/master ran the script
as `~/.claude/scripts/migrate-test-to-tests.sh` (a literal path); R6 respelled it to
`bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/migrate-test-to-tests.sh"`. Both spellings get the
same decision from the analyzer and from the hook; a dynamic operand that is not exactly the
quoted channel with plain components, and a removal program behind the channel, stay refused.
The last test feeds every Bash call commands/test.md makes today to the hook.

ZERO EXECUTION: every command below is data handed to the analyzer or the hook as JSON stdin.
"""

from __future__ import annotations

import os
import re
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


STEP3_BLOCK = """\
if [[ -d "test" ]] && [[ ! -d "tests" || "test" -nt "tests" ]]; then
  echo "Found test/ folder - migrating to tests/ (Python standard naming)"

  bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/migrate-test-to-tests.sh" --project-root "$(pwd)"

  if [[ $? -eq 0 ]]; then
    echo "Migration complete - review tests/ folder"
    echo "   Remove test/ folder when ready: rm -rf test/"
  fi
elif [[ -d "test" ]] && [[ -d "tests" ]]; then
  echo "Both test/ and tests/ exist - manual review recommended"
  echo "   Run: bash <HARNESS_ROOT>/scripts/migrate-test-to-tests.sh --project-root $(pwd)"
fi"""


def _step3_block() -> str:
    assert "bash " + CHANNEL + SCRIPT + '" --project-root' in STEP3_BLOCK and "rm -rf test/" in STEP3_BLOCK
    return STEP3_BLOCK


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


def _test_md_calls() -> list[str]:
    """Every shell command commands/test.md tells the session to run: its bash fences, one per line,
    and its inline code spans that start a python3 program; the placeholders filled as the session fills them."""
    text = (REPO_ROOT / "commands" / "test.md").read_text(encoding="utf-8")
    calls = [line for block in re.findall(r"```bash\n(.*?)```", text, re.S) for line in block.splitlines() if line.strip()]
    calls += re.findall(r"`(python3 [^`]+)`", text)
    fill = {"<HARNESS_ROOT>": str(REPO_ROOT), "<request_id>": "test-20261109-120000", "<timestamp>": "2026-11-09T12:00:00Z"}
    return [re.sub("|".join(map(re.escape, fill)), lambda m: fill[m.group(0)], call) for call in calls]


def test_every_bash_call_in_test_md_is_allowed_by_the_analyzer_and_the_hook():
    calls = _test_md_calls()
    assert len(calls) >= 11 and any("--full" in call for call in calls), calls
    for command in calls:
        result = eb.analyze(command)
        assert result["allowed"] is True, (command, result["verdict"], result.get("reason"))
        code, _out, err = run_hook_command(command)
        assert code == 0, (command, err)
