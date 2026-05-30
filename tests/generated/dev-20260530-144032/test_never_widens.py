"""AC4 (ac_uid 4d0f6c2b3e5a7d94) — never widens the committed file set.

The helper operates on a SINGLE explicit repo-relative file passed by the caller.
It can only stage owned hunks WITHIN that file (or exclude it) — it can never reach
a different (foreign / non-whitelisted) file. This test proves the helper never
stages a file other than the one it was given, and that a foreign dirty file present
in the working tree is never staged by the helper.

Also asserts DO-NOT #1 at the helper boundary: the helper never runs `git add -A`
/ `git add .` (it stages exclusively via a single-file `git apply --cached` patch).
"""

import subprocess

from conftest import OK


def test_AC4_foreign_file_never_staged(repo):
    repo.write("owned.txt", "a\nb\nc\n")
    repo.write("foreign.txt", "1\n2\n3\n")
    repo.commit("base")
    snap = repo.write_snapshot("a\nb\nc\n")
    repo.write("owned.txt", "a\nb OWNED\nc\n")
    repo.write("foreign.txt", "1\n2 PEER\n3\n")  # foreign session dirty file
    ledger = repo.write_ledger([{"old": "b\n", "new": "b OWNED\n"}])

    rc, err = repo.run_helper("owned.txt", ledger, snap)
    assert rc == OK, err

    staged = repo.cached_names()
    # The staged set is a SUBSET of {owned.txt} — never a superset, never foreign.
    assert staged <= {"owned.txt"}, "helper widened the staged set: %s" % staged
    assert "foreign.txt" not in staged, "foreign dirty file must never be staged"
    # cardinality never increased beyond the single authorized file
    assert len(staged) <= 1


def test_AC4_helper_uses_no_add_all(repo):
    """Static guard: the helper source must NOT contain `git add -A` / `git add .`
    and must stage via `git apply --cached` only (DO-NOT #1 at the helper)."""
    from conftest import HELPER
    with open(HELPER, "r", encoding="utf-8") as fh:
        src = fh.read()
    assert "add -A" not in src and "add ." not in src and '"add"' not in src
    assert "apply" in src and "--cached" in src
