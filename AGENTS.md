# AGENTS.md

Instructions for Codex in this repository.

## Review guidelines

- This harness exists to run an unattended development pipeline. A finding counts only if a normal run reaches it: name the command or pipeline step, the ordinary input, and what goes wrong for the user.
- Do not report ways a deliberately adversarial agent could get past a guard: unusual option spellings, crafted expansions, preloaded libraries, races built on purpose. The hooks stop mistakes, not attacks.
- Report only P0 and P1: a command or pipeline step does not run, gives a wrong result, loses work, or puts a personal value into the public copy. No style, naming, wording or edge cases.
- One complete pass. On a re-review, only check whether the earlier findings are fixed; do not start a new search.
- Each finding gives: file and line, the normal path that reaches it, the result you traced or observed, and the smallest fix.
