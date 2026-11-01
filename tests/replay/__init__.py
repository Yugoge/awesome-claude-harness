"""Sandboxed hook-replay framework (the "trace runner").

A replay models a Claude Code session against a copy of a harness tree: it
builds a sandbox (sandbox.py), fires the hooks settings.json registers for each
event the way the CLI does (hookrun.py), writes CLI-shaped transcripts and
performs the tool calls a scenario driver asks for (replay.py), takes the
command text a driver runs from the tree under test (cmdtext.py), and, under
strace, turns the file operations of every process into normalised relation
events (trace.py, norm.py). cli.py is the entry point; inner.py is what runs
inside the sandbox; drivers/ holds the scenario drivers.

Test code: nothing here is imported by the harness itself.
"""
