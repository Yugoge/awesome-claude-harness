# The `Red-test:` trailer and the red-then-green job

> Last updated: 2026-11-16

A fix is shown by a test that fails before it and passes after it. `scripts/ci/red-green.py` runs that
check for a base and a head; this page says what it judges and how a change names its evidence.

## What the script does

    python3 scripts/ci/red-green.py --base origin/master --head HEAD [--body-file pr-body.md] [--summary out.md]

1. It finds the merge base of `--base` and `--head` and judges the diff merge-base..head.
2. **Exempt by path:** a diff that changes only tests (`test_*.py`, `conftest.py`) and docs (`docs/`, `*.md`,
   `*.rst`, `*.txt`) needs no red. Test helpers, fixtures, hooks, scripts, tools and `settings.json` are not
   exempt.
3. Otherwise it takes the head's changed `test_*.py` and `conftest.py` and every id a `Red-test: <nodeid>`
   trailer names, and runs each test file or id twice, each in a real checkout (a shared clone, so tests that
   read history see it):
   - **red:** the merge base with only the head's changed `test_*.py` and `conftest.py` laid over it. Test
     helpers and fixtures stay the base's;
   - **green:** the head.
4. It prints a markdown summary with one row per test id that does not pass on both sides, and the count of
   those that do. A test id that fails or errors on red and passes on green is **red then green**. A collection
   error on red counts as red, and is listed apart from a failing assertion so the reviewer can tell them apart.

Exit status: `0` when at least one id goes red then green, when the diff is exempt, or when a
`Red-test: none: <reason>` trailer is present; `1` otherwise.

## The trailer

The script reads `Red-test:` trailers from the commit messages of merge-base..head (git's trailer block, the
message's last paragraph, so a wrapped sentence that starts with `Red-test:` is not one) and `Red-test:` lines
from `--body-file` (the PR body). One line per id; any number of lines.

- `Red-test: <nodeid>` names a guard that already exists, for a change that adds or changes no test. The id is
  a pytest node id relative to the repository root, such as
  `tests/test_harness_switch.py::test_every_registered_hook_asks_the_switch_first` (without a parameter it
  selects every parameter). The script runs it red and green like a changed test.
- `Red-test: none: <reason>` says no deterministic red is possible (a timing fault, a CI-only change). The
  script prints the reason at the top of its summary, for the reviewer to judge, and exits 0.

## Example

On #43's merge (`036d1ed`), with its first parent as the base:

    python3 scripts/ci/red-green.py --base 036d1ed^1 --head 036d1ed

reports `hooks/tests/test_command_span.py::test_the_openers_context_is_read_in_the_cli_2_1_322_record_forms`
and `hooks/tests/test_stop_command_gate.py::test_a4_a_do_whose_minted_line_cli_2_1_322_records_as_hook_success_can_end`
as red then green. `6bf06147` changed no test; with
`Red-test: tests/test_harness_switch.py::test_every_registered_hook_asks_the_switch_first` its two
newly registered hooks' ids fail on `f0e4d9c` and pass on `6bf06147`.

Its own tests: `tests/test_ci_red_green.py`. Wiring the script into CI is the CI workflow's.
