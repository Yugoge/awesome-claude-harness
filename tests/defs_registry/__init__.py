"""The duplicate-definition check: no fact of hooks/ and scripts/ written out twice unless the
register (policies/definition-lookalikes.v1.json) says the look-alikes answer different questions.

`python3 -m tests.defs_registry [--tree DIR] [--count]` prints each uncovered group with file and
line and exits 1 when there is one; --count prints only the number of uncovered groups.
scan.py enumerates the definitions, check.py states the sameness rule and applies the register;
test_defs_registry.py holds the rule to synthetic trees and this tree to the register's ceiling.
"""
