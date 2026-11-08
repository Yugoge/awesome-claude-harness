You finish phase P11 of the owner's harness repair plan in this repository (Yugoge/awesome-claude-harness), on branch
repair/P11 (PR #19). The owner's ruling D30 (harness-repair-plan/DECISIONS.md on claude/vibrant-hopper-bazrn8) replaces
the history rewrite: this repository becomes private with its history, and a new public repository starts from one
commit of the clean tree. Keep the pre-push guard already on the branch.

Deliver, with tests:
1. A publish script. It builds one commit whose tree is a given commit's tree (default: master's head). The first
   publish has no parent; each later publish has the previous public commit as its only parent. Before pushing, it
   runs the privacy engine (check-public-core) and the pre-push guard's scan on that tree and refuses on any hit,
   naming the file and never the value. It pushes only that commit to the public remote's main branch.
2. End-to-end tests, only in scratch repositories you create, holding made-up stand-in values (a fake name, an
   example.invalid address), with local bare repositories as both remotes:
   - a clean tree publishes as one parentless commit;
   - a tree holding a stand-in private value is refused, and nothing is pushed;
   - a second publish adds exactly one commit;
   - no object of the private history exists in the public bare repository afterwards.
3. Keep GitHub Actions minutes on the private repository near zero: there, the workflows run only on manual dispatch;
   the full CI runs on the public repository for each publish.
4. On #19, the owner's confirmation runbook, with each step's effect: make this repository private; create the public
   repository (the owner names it then); the first publish; what the harness home does (nothing: its origin stays
   this repository). Mark #19 ready.

DO NOT:
- create a repository, change any repository's visibility, or push to any GitHub remote other than repair/P11;
- rewrite this repository's history, force-push, or delete a ref;
- read this repository's private overlay or the home's private-literal list to look for values;
- work around a safety check that stops a step: stop and report it on #19.

Push as soon as each step's tests pass. Ask the owner nothing; if something blocks you, say so in a PR comment.
