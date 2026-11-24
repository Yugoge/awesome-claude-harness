"""The shell half reads `$(python3 <tree program> <args>)` that shscan.PRINTED_DEFINITIONS names as the
static value of the Python function the program prints, so a shell writer that takes its root from the one
definition gets the keys its Python readers get (the session owner record: session-scratch-init.sh writes
under `scratch_owner.py --root`, locations.session_scratch_root's readers read there)."""
from __future__ import annotations

from tests.artifact_graph import derive
from tests.artifact_graph.test_static_half import make_tree, rels

LOCATIONS = '''
    import os
    SESSION_SCRATCH_ROOT = "/var/tmp/claude-scratch"
    def session_scratch_root():
        tmp = os.environ.get("TMPDIR") or ""
        root = (tmp if os.path.isabs(tmp) else None) or SESSION_SCRATCH_ROOT
        return os.path.dirname(root) if os.path.isfile(os.path.join(root, ".owner")) else root
'''
SCRATCH_OWNER = '''
    import os, sys
    def owner_record(d):
        with open(os.path.join(d, ".owner")) as fh:
            return fh.read()
    if __name__ == "__main__":
        if sys.argv[1:] == ["--root"]:
            import locations
            print(locations.session_scratch_root())
            sys.exit(0)
        sys.exit(0 if owner_record(sys.argv[1]) else 1)
'''
INIT = '''
    #!/usr/bin/env bash
    ROOT=$(python3 "$(dirname "${BASH_SOURCE[0]}")/lib/scratch_owner.py" --root 2>/dev/null) || ROOT=""
    OTHER=$(python3 "$(dirname "${BASH_SOURCE[0]}")/lib/scratch_owner.py" --other)
    SID="${CLAUDE_CODE_SESSION_ID:-}"
    printf '{}' > "$ROOT/$SID/.owner"
    printf '{}' > "$OTHER/x.json"
'''
READER = '''
    import json, os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
    import locations
    def main(sid):
        with open(os.path.join(locations.session_scratch_root(), sid, ".owner")) as fh:
            if not json.load(fh):
                sys.exit(2)
'''


def test_a_root_a_shell_script_takes_from_the_one_definition_is_that_definitions_key(tmp_path):
    root = make_tree(tmp_path, {"hooks/lib/locations.py": LOCATIONS, "hooks/lib/scratch_owner.py": SCRATCH_OWNER,
                                "hooks/init.sh": INIT, "hooks/reader.py": READER})
    r = derive(root)
    written = {x["path"] for x in rels(r, op="write", component="hooks/init.sh") if x["path"].endswith("/.owner")}
    read = {x["path"] for x in rels(r, op="read", component="hooks/reader.py") if x["path"].endswith("/.owner")}
    assert read and "<tmpdir>/../<sid>/.owner" in read, read
    assert read <= written, (read, written)
    # the same program with arguments the table does not name prints an unknown value, as before
    assert not any(x["path"].endswith("/x.json") and x["path"].startswith(("<tmpdir>", "/var/tmp"))
                   for x in rels(r, op="write", component="hooks/init.sh"))
