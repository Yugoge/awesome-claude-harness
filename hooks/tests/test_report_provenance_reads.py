"""The main agent's hand-run check (CD-6, hooks/pretool-tool-policy.py _check_hook_replay) against
the fifth verifier's findings, through the registered PreToolUse launcher in a throwaway project,
HOME and state dir:

1. inline code that only opens and reads a hook entry, the provenance module or the provenance
   ledger, and a `bash -n` / `sh -n` syntax check of a shell hook entry, pass;
2. inline code that imports or executes a hook entry or the provenance module, or writes the
   ledger, is still refused;
3. the cheap literal spellings that ran a hook entry past the check are refused at their
   PreToolUse: a glob, `?` or brace spelling of the entry, `find ... -exec <interpreter> {}`,
   inline python run with its directory in the hooks directory that imports a hooks module, and a
   shell's option operands (`-o posix`, `+x`, `-n ... +n`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_report_provenance_tamper as tt  # noqa: E402

H = str(tt.ROOT / "hooks")
MARK = "runs the harness's own hook code"
LEDGER = "/tmp/state/report-provenance/x.json"


@pytest.fixture()
def world(tmp_path):
    return tt.World(tmp_path)


READS = {
    "ast-parse-entry": f"python3 -c \"import ast; ast.parse(open('{H}/pretool-tool-policy.py').read())\"",
    "count-defs": f"python3 -c \"print(open('{H}/pretool-tool-policy.py').read().count('def '))\"",
    "heredoc-count-lines": (f"python3 - <<'EOF'\nimport re\nsrc=open('{H}/subagentstop-e2e-enforce.py').read()\n"
                            "print(len(src.splitlines()))\nEOF"),
    "node-read-length": (f"node -e \"console.log(require('fs').readFileSync('{H}/pretool-tool-policy.py',"
                         "'utf8').length)\""),
    "read-ledger-json": f"python3 -c \"import json; print(json.load(open('{LEDGER}')))\"",
    "read-provenance-module": f"python3 -c \"print(len(open('{H}/lib/report_provenance.py').read()))\"",
    "read-ledger-mode-r": f"python3 -c \"print(open('{LEDGER}', 'r').read())\"",
    "json-tool-ledger": f"python3 -m json.tool {LEDGER}",
    "bash-n-entry": f"bash -n {H}/pretool-bash-safety.sh",
    "sh-n-entry": f"sh -n {H}/pretool-bash-safety.sh",
    "bash-n-silent": f"bash -n {H}/pretool-bash-safety.sh 2>/dev/null; echo ok",
    "bash-nv-entry": f"bash -nv {H}/pretool-bash-safety.sh",
    "find-exec-grep": f"find {H} -maxdepth 1 -name 'pretool-*.py' -exec grep -l observe_call {{}} +",
    "cd-hooks-stdlib-import": f"cd {H} && python3 -c \"import json; print(json.dumps(1))\"",
    "cd-hooks-glob-read": f"cd {H} && ls pretool-tool-pol*.py",
}

REFUSED = {
    # imports or runs the hook entry / the provenance module, or writes the ledger
    "import-provenance": "python3 -c \"from lib import report_provenance\"",
    "import-provenance-after-read": f"python3 -c \"open('{H}/x').read(); import lib.report_provenance\"",
    "exec-open-entry": f"python3 -c \"exec(open('{H}/pretool-tool-policy.py').read())\"",
    "write-ledger": f"python3 -c \"open('{LEDGER}', 'w').write('x')\"",
    "dump-ledger": f"python3 - <<'EOF'\nimport json\njson.dump({{}}, open('{LEDGER}', 'a'))\nEOF",
    "node-write-ledger": f"node -e \"require('fs').writeFileSync('{LEDGER}', 'x')\"",
    "node-require-entry": f"node -e \"require('{H}/lib/x.js')\"",
    "call-observe-call": "python3 -c \"import x; x.observe_call({})\"",
    # spellings of the entry
    "glob-entry": f"python3 {H}/pretool-tool-pol*.py <<'EOF'\n{{}}\nEOF",
    "qmark-entry": f"python3 {H}/pretool-tool-policy.p? <<'EOF'\n{{}}\nEOF",
    "brace-entry": f"python3 {H}/pretool-tool-policy.{{py,}} <<'EOF'\n{{}}\nEOF",
    "glob-direct-exec": f"{H}/pretool-laun*.py < /tmp/p.json",
    "cd-glob-entry": f"cd {H} && python3 ./pretool-tool-pol[i]cy.py < /tmp/p.json",
    # find -exec
    "find-exec-python": f"find {H} -maxdepth 1 -name pretool-tool-policy.py -exec python3 {{}} \\; < /tmp/p.json",
    "find-exec-glob-name": f"find {H} -maxdepth 1 -name 'pretool-tool-pol*' -exec timeout 5 python3 {{}} \\;",
    "find-execdir-direct": f"find {H} -name 'pretool-launch.py' -execdir {{}} \\;",
    # inline python with its directory in the hooks dir importing hooks modules
    "cd-hooks-from-lib": (f"cd {H} && python3 - <<'PEOF'\nfrom lib import write_gate, rule_runner\n"
                          "r=[x for x in write_gate.RULES if x.name=='tool-policy'][0]\nPEOF"),
    "cd-hooks-import-lib-c": f"cd {H} && python3 -c \"import lib.rule_runner\"",
    "cd-hooks-syspath-lib": f"cd {H} && python3 -c \"import sys; sys.path.insert(0,'lib'); import shell_parse\"",
    "cd-hooks-lib-import": f"cd {H}/lib && python3 -c \"import rule_runner\"",
    "cd-hooks-m-lib": f"cd {H} && python3 -m lib.rule_runner",
    # shell option operands in front of the entry
    "bash-o-posix": f"bash -o posix {H}/pretool-bash-safety.sh < /tmp/p.json",
    "bash-plus-x": f"bash +x {H}/pretool-bash-safety.sh < /tmp/p.json",
    "bash-n-then-plus-n": f"bash -n +n {H}/pretool-bash-safety.sh < /tmp/p.json",
    "bash-o-noexec-off": f"bash -o noexec +o noexec {H}/pretool-bash-safety.sh < /tmp/p.json",
}


@pytest.mark.parametrize("name", list(READS))
def test_a_read_of_hook_code_or_the_ledger_passes(world, name):
    proc = world.launch("Bash", {"command": READS[name]})
    assert MARK not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", list(REFUSED))
def test_running_hook_code_or_writing_the_ledger_is_refused(world, name):
    proc = world.launch("Bash", {"command": REFUSED[name]})
    assert proc.returncode == 2, proc.stderr
    assert MARK in proc.stderr, proc.stderr


def test_a_subagents_inline_import_in_the_hooks_dir_is_not_refused_by_this_rule(world):
    qa = world.start_qa(tt.Q)
    proc = world.pre("Bash", {"command": REFUSED["cd-hooks-from-lib"]}, agent=qa)
    assert MARK not in proc.stderr, proc.stderr
