"""discover-folders.sh (P10 R14): /clean's folder pass (Step 4's rule-inspector writes a README and an
INDEX per discovered folder) leaves out the harness's own directories in a project: .claude (Claude
Code's and the harness's runtime files) and the JSON-only workflow directories docs/dev and docs/clean.
The /clean replay showed the READMEs written there left behind untracked, read by no one.
"""
import os
import subprocess

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "discover-folders.sh")


def test_the_harness_directories_are_left_out_and_the_rest_listed(tmp_path):
    for rel in (".claude/state", "docs/dev", "docs/clean", "docs/guides", "scripts", "sub/.claude", "sub/docs/clean"):
        (tmp_path / rel).mkdir(parents=True)
    out = subprocess.run(["bash", SCRIPT, str(tmp_path)], capture_output=True, text=True, check=True).stdout.split()
    assert out == ["docs", "docs/guides", "scripts", "sub", "sub/docs", "sub/docs/clean"]
