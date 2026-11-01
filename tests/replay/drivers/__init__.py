"""Scenario drivers. Each module defines PIPELINE (its summary-row name) and
run(rp: replay.Replay); it may define FAULTS, a list of (step-label pattern,
fn(rp, phase, step)) pairs that Replay.step() runs before and after the
matching steps. Pipeline drivers take every Bash block and dispatch template
they run from the tree under test through cmdtext (row 19 rule 9)."""
