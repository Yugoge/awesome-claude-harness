# No phases, no deferral

Read this file when your agent file points here (ba, spec, dev and qa carry the rule in one line). It holds the
definition and what QA fails.

**The rule.** Every outcome the user requested is delivered in the same cycle, and the cycle ends only when all
of them are done. Parallel lanes inside one cycle are fine: one issue per agent, all running in this cycle.
Sequential phases, deferred parts and "later cycle" plans are never allowed, and nobody asks the owner to open
another /dev session.

**Forbidden in any spec, view, BA context, dev plan, dev report, QA verdict or close decision:**
- calling a part "phase 1", "phase 2", "stage 2", "MVP first", "first iteration" or "v1 now, v2 later";
- marking a requested outcome deferred, postponed, "for a later cycle", "a follow-up task" or "next /dev";
- sorting a requested outcome, one of its instances or the infrastructure it needs as Could have, Won't have or
  out of scope, unless the user narrowed the requirement themselves (in its text or in an answer to a question);
- a "cycle scope" narrower than the requirement.

**Not phasing:**
- the parallel lanes of one cycle, and the order of steps inside one lane (build before verify) when the cycle
  completes all of it;
- the phases of an agent's own procedure (spec's Phase 0 to 2, QA's Phases 1 to 6);
- defects outside the user's path: they go to `out_of_scope_observations`, because nobody requested them.

**What each role does.**
- BA and spec: plan every requested outcome into this cycle's lanes. The context, spec and views carry no
  deferral, no phase and no narrower scope.
- dev: deliver every requested outcome. An obstacle is solved, not reported as remaining work; the dev report has
  no "remaining" or "next phase" list.
- QA: the three checks below fail, and a fail goes back to the producer.

**What QA fails (one home, for every QA mode):**
- BA-QA (`scope_alignment`): a plan that phases or defers a requested outcome is a blocking objection.
- Spec-split QA: a spec or view split that phases or defers a requested outcome fails the split.
- Final and close QA: a cycle that leaves a requested outcome for later is `fail`, with the outcome named.
  "Partially addressed" is not a pass.
