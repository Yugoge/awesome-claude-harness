"""Prompt and hook lint: the P12 principles, checked by CI instead of by discipline.

Six checks, each over the tree it is given (`Tree`), each a list of `Finding`s:

  hook-strength      a prompt says a hook blocks while docs/ENFORCEMENT-LEDGER.md says
                     that by default it only warns or is off
  dead-reference     a prompt names a harness file that does not exist
  repeated-block     a block of 10 or more lines is repeated in two prompts
  emphasis           a prompt has more than 3 emphasis words
  unreachable-output a registered hook prints, but can only exit 0, so its output
                     never reaches the model
  two-writers        a state file has two writers (derived by the artifact check)

`python3 -m tests.lint [--tree DIR] [--check NAME ...]` prints the findings and exits 1
when there are any. tests/lint/test_lint_tree.py runs each check on this tree; it is
collected only when HARNESS_LINT=1, which the baseline workflow's lint step sets.
"""
