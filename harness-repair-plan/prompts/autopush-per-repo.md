Owner steps: none.

# Auto push per repository (D1 as amended on 2026-11-07)

Effort: S, about half a day (D26). One PR to master, titled `Auto push per repository: ...`.

## Budget and stopping rules

- Build the change below, run its tests once, and record each command and its result in the PR.
- Run one self-check round over your own diff, fixing medium severity or higher only.
- Push after every commit.
- Ask the owner nothing. If something blocks you, say so in a PR comment.

## Why

The owner wants every repository on their machine to sync automatically by default, with off as the exception (DECISIONS.md, D1 as amended). Today automatic push has one global switch, GIT_AUTO_PUSH. Turning it on would also push the harness home's checkpoints to the public repository; that is how the 255 refs that P11 deletes got there.

## Goal

1. **A per-repository override.** A repository's local git config `harness.autoPush` (true or false) decides whether automatic pushes run for that repository. When the key is unset, the global GIT_AUTO_PUSH decides, exactly as today.
   - Read the key in one function. Every automatic push path calls that function:
     - the checkpoint push (`_checkpoint_rate_limited_push` in hooks/lib/checkpoint-core.sh);
     - git-fswatch's push (hooks/git-fswatch.sh);
     - session-git-init's initial push.
   - The privacy gate before a push stays unchanged.
2. **The harness home defaults to off.** `scripts/bootstrap` (init) and `scripts/install/land` set `git config --local harness.autoPush false` in the harness home when the key is absent. They never overwrite a value the owner set.
3. **Docs.** The README's install section says how to turn the switch on or off for one repository, in a few lines.
4. **Tests.** Unit tests cover, for each push path:
   - global on and repository false → no push;
   - global off and repository true → push;
   - key unset → the global switch decides.

   A test shows that init and land set false in a home that lacks the key and keep a value already set. Every test runs in a scratch HOME and scratch repositories, with no network: a local bare repository serves as the origin.

## Acceptance

- CI is green on 3.10, 3.11 and 3.12, and the artifact check is at zero.
- Once P1c is merged, P1c's replay suite is green too.
- The new tests fail on master and pass on your branch.

## DO NOT

- Do not change the tracked clean form's GIT_AUTO_PUSH "0", the privacy gate, or any phase's files beyond the push paths above.
- Do not add a new state file. The override lives in git's own config.
- Do not push to, or touch, a real remote or the real HOME.
- Do not force-push, rebase, or rewrite another branch.
