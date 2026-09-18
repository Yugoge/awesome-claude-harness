# `/restart` interruption detector: textual quota-proxy instead of structural liveness check

**Date**: 2026-09-15
**Component**: `hooks/lib/subagent_restart.py` → `discover_candidates()`, driven by
`scripts/restart-subagents.py prepare`
**Subject**: the `quota_or_usage_limit` evidence code does not measure whether the
candidate subagent's own process was interrupted. It measures whether a quota-shaped
*string* occurs anywhere in the parent's `Agent` tool_result body. Those are different
facts, and they come apart exactly when the fleet is doing quota-recovery work.
**Method**: full structural re-classification of all 217 candidate records emitted by a
`prepare` run against parent session `29b40616-c2b4-4132-83d8-978f2a98a0f6`, by reading
each candidate's own child JSONL transcript (not the parent's tool_result text) and
cross-checking against the parent-side tool_result. Raw candidate JSON at
`/var/lib/claude-accounts/yugetang/claude/projects/-dev-shm-dev-workspace-dot-claude/29b40616-c2b4-4132-83d8-978f2a98a0f6/tool-results/b60w39hr7.txt`;
classifier at `/tmp/restart_classify2.py`, per-candidate output at
`/tmp/restart_classification2.json`, genuinely-interrupted roster at
`/tmp/genuinely_interrupted_full.tsv`.

> **Correction to the premise this investigation started from.** The investigation was
> commissioned on the belief that `aef962fe7ed3ffccf` (style-inspector) and
> `a436a869f92470a38` (cleanliness-inspector) were false positives that had finished
> cleanly with a `STATUS: complete` line, and that most of the 213 pending candidates
> were stale. **Both beliefs are refuted by the transcripts.** Those two agents were
> genuinely killed mid-run, and the false-positive rate is 18.6%, not ~98%. The real
> false positives are a different, disjoint set of 39 agents. Details in §3 and §5.

---

## 0. The two examples that make the defect legible without any statistics

**The detector cannot tell a quota event from the report of a quota event having ended.**
Agent `af2c8a271aa70b4a1` (general-purpose, "Drive e1c60053 restart") delivered a clean
`end_turn` report whose own sentence was: *"its quota window **reset at** 15:50 UTC and
the session reconnected."* — i.e. the agent was reporting that the outage was **over**.
The detector's regex matched the substring `reset at 1` inside that sentence and flagged
the agent as **currently quota-interrupted**. It does not merely fail to distinguish
"interrupted" from "not interrupted" — it inverts the two on contact with the word
"reset", which is the one word in the outage vocabulary that means the opposite of what
the detector concluded from it.

**The detector cannot tell a quota event from an unrelated filename.** Agent
`ae822c167ffd478e7` (general-purpose, "Measure drift since 15:42Z gate") delivered a
clean `end_turn` report, 11,029 characters, verdict already reached. Its regex alternative
`(?:anthropic|claude)[^\n]{0,80}rate[-_ ]limit` spans up to 80 arbitrary characters, and in
this report it stretched from a **filename** to an unrelated parenthetical describing a
disk-space hook:

```
- **15:44:40.007Z** — `/tmp/claude-pressure-warn-ec2ae4f0-…` written, counter `3`
  (the hook's rate-limit maximum). This is `hooks/userprompt-tmpfs-pressure.sh`, a
  **tmpfs**-pressure warning about /tmp being full, n…
```

The matched span — `claude-pressure-warn-ec2ae4f0-…` written, counter `3` (the hook's
rate-limit` — runs through a temp-file path and a sentence whose entire point is *"this is
a disk warning, explicitly not a quota event."* The detector flagged it as one anyway.

Neither example required an edge case or a rare phrasing. Both are ordinary, correctly-
written reports doing exactly the job they were dispatched to do (recover from and report
on a quota outage). The detector penalizes doing that job well. Full roster and 3 more
examples in §5.

---

## 1. Measured shape of the candidate list

| Measure | Value |
|---|---|
| Candidate records emitted | **217** |
| `status: "pending"` | **213** |
| `status: "dispatched"` | 4 records = **2** distinct agents (`af293129f2aab2426`, `a50c142fa24093be5`) |
| Distinct `agent_id` values | **210** (7 agents appear twice, once per account root) |
| Distinct source parent sessions | **37** |
| Evidence codes present | `quota_or_usage_limit` ×190 records / 184 distinct agents; `missing_parent_tool_result` ×27 records / 26 distinct agents |
| Transcript roots spanned | `/root/.claude-cold` (145), `/var/lib/claude-accounts/orchestrade` (65), `/var/lib/claude-accounts/yugetang` (7) |
| Earliest candidate transcript | `a6faa47df39212489` — first record `2026-05-20T05:35:24.701Z` |
| Latest candidate transcript | `ab5881557f55a4053` — first record `2026-09-15T09:24:52.649Z` |
| Task-ids embedded in descriptions | `20260520-221059` … `20260604-204954` |

The list is not scoped to one session. `sibling_transcripts()` walks every account root
under `/var/lib/claude-accounts` plus `$HOME/.claude/projects` for the same project slug,
so a single `prepare` sweeps ~four months of fan-out history across 37 parent sessions.
The duplicate-`agent_id` rows (7) are the same child transcript reached through two
different account copies of the same session file; they are byte-identical.

## 2. The heuristic actually in use

`hooks/lib/subagent_restart.py:39-46` defines the sole quota test:

```python
QUOTA_RE = re.compile(
    r"you(?:'|’)?ve hit your session limit|session usage limit|"
    r"usage limit (?:has been )?(?:reached|exceeded)|"
    r"(?:anthropic|claude)[^\n]{0,80}rate[-_ ]limit|"
    r"(?:error|code)[\"' :=_-]{0,12}rate_limit|"
    r"resets?\s+(?:at|in)\s+\d",
    re.IGNORECASE,
)
```

and `discover_candidates()` applies it at `:365-368` to `result_text`, which is
`_textify(result_blocks)` — the **entire body of the parent's `Agent` tool_result**:

```python
result_blocks = results.get(tool_id, [])
result_text = _textify(result_blocks)
...
if (result_text and QUOTA_RE.search(result_text)) or (
    notification_after_call and notification.get("quota_interrupted")
):
    evidence.append("quota_or_usage_limit")
```

The parent's `Agent` tool_result body **is the child's own final report** whenever the
child completed. So the predicate being evaluated is "did this agent's report contain
quota-shaped prose", not "was this agent's process stopped". Nothing in
`discover_candidates()` ever opens the child transcript whose path it emits in
`agent_transcript_path` — the child's own liveness record is written into the candidate
record but never read.

The same substitution is repeated at `:274` for `<task-notification>` bodies
(`"quota_interrupted": bool(QUOTA_RE.search(tail))`) and again at `:670`, where a
resumed agent's response is graded `quota_interrupted` vs `response_observed` by running
`QUOTA_RE` over `last_message`.

By contrast, the neighbouring `interrupted_tool_result` test at `:382-386` *does* gate on
structure — `block.get("is_error") is True` **and** a word-bounded phrase match on the
same block — and carries a comment explaining exactly why an is_error-less fallback was
rejected. The quota branch has no such gate.

## 3. The structural signal the detector should have used

A child's JSONL transcript records liveness directly. Two record shapes are decisive,
and they are emitted by the harness, never by the model:

**Terminal report** — the agent chose to stop:

```
{"type":"assistant","message":{"role":"assistant","stop_reason":"end_turn",
 "content":[{"type":"text","text":"<the final report>"}]}}
```

**Harness abort** — the agent was stopped:

```
{"type":"assistant","isApiErrorMessage":true,"apiErrorStatus":429,
 "quotaLimits":{"status":"rejected","resetsAt":1789117800,"rateLimitType":"five_hour",...},
 "message":{"role":"assistant","stop_reason":"stop_sequence","model":"<synthetic>",
 "content":[{"type":"text","text":"You've hit your session limit · resets 9:10am (UTC)"}]}}
```

Note `"model":"<synthetic>"` and the `quotaLimits` object: this record is fabricated by
the client when the API refuses, and cannot be produced by an agent narrating someone
else's quota error. `stop_reason: "end_turn"` likewise cannot be forged by report text.

Census of the **last** record across all 210 distinct child transcripts:

| Last record shape | Count | Meaning |
|---|---|---|
| `isApiErrorMessage:true`, `stop_reason:"stop_sequence"` | 155 | harness abort |
| assistant `text` + `stop_reason:"end_turn"` | 25 | clean terminal report |
| `user` record (tool_result, or `[Request interrupted by user]`) | 17 | stream stopped mid-turn |
| assistant `tool_use` | 8 | stream stopped mid tool call |
| assistant `text`, `stop_reason:null` | 4 | stream stopped mid-narration |
| assistant `thinking` | 1 | stream stopped mid-thinking |

Because an agent can deliver a report and then be re-woken (by a coordinator
`restart-v1` SendMessage, or by Stop-hook feedback) and killed during *that* turn, the
final rule is not "is the last record an abort" but:

> **Does any assistant record in this child's transcript carry
> `stop_reason == "end_turn"`?** If yes, the agent reached a natural stopping point and
> emitted its own terminal report. If no, it never did.

The one exception found (1 of 210) is handled by a parent-side rescue clause: an agent
whose final assistant message was persisted without a `stop_reason` because the human
pressed ESC mid-stream, yet whose full 13 640-character report did land in the parent.

## 4. Corrected classification of all 217 candidates

Applied uniformly — to the 213 pending, the 4 dispatched, and all 26 distinct
`missing_parent_tool_result` agents alike, with no special-casing.

| Bucket | Distinct agents | Candidate rows | Action |
|---|---|---|---|
| **`never_reported`** — no `end_turn` anywhere: genuinely cut off, no terminal report | **171** | 177 | **resume** |
| `completed_clean` — `end_turn` is the last record | 25 | 26 | none |
| `completed_then_resume_interrupted` — reported, then a later coordinator/Stop-hook turn was cut off | 13 | 13 | none for the original issue |
| `report_delivered_without_end_turn` — full report reached the parent; ESC clipped the final `stop_reason` | 1 | 1 | none |
| **False positives (last three rows)** | **39** | **40** | **none** |

Breakdown of the 171 genuinely-interrupted:

| Why it has no terminal report | Count |
|---|---|
| harness abort record (`isApiErrorMessage:true`) is last | 142 |
| ends on a `user` record (tool_result, or `[Request interrupted by user]`) | 17 |
| ends mid-turn, `stop_reason: null` | 7 |
| ends mid-turn, `stop_reason: "tool_use"` | 5 |

By agent type: qa 43, dev 33, ba 25, style-inspector 18, general-purpose 15,
cleanliness-inspector 15, prompt-inspector 9, changelog-analyst 3, architect 3,
test-writer 2, push-analyst 2, Explore 1, claude 1, spec 1.

**False-positive rate by evidence code:**

| Evidence code | Distinct agents | False positives | Rate |
|---|---|---|---|
| `quota_or_usage_limit` | 184 | 39 | **21.2%** |
| `missing_parent_tool_result` | 26 | 0 | **0.0%** |
| All | 210 | 39 | 18.6% |

Every single false positive carries `quota_or_usage_limit`. The
`missing_parent_tool_result` code — which tests a structural fact ("the parent never
received a result for this tool_use_id") rather than a textual one — is perfectly precise
on this corpus.

## 5. Verbatim evidence

### 5a. The two agents believed to be false positives are genuine interruptions

`aef962fe7ed3ffccf` — style-inspector, "Style inspection for close attempt 4",
transcript `…/29b40616-…/subagents/agent-aef962fe7ed3ffccf.jsonl`, 233 lines:

```
$ grep -c "STATUS: complete"        agent-aef962fe7ed3ffccf.jsonl   → 0
$ grep -c '"stop_reason":"end_turn"' agent-aef962fe7ed3ffccf.jsonl  → 0
$ grep -c '"isApiErrorMessage":true' agent-aef962fe7ed3ffccf.jsonl  → 1
```

Its last three records are a `Bash` tool_use (L231), its tool_result (L232), and then:

```
L233  type=assistant  role=assistant  stop_reason=stop_sequence
      isApiErrorMessage=True  apiErrorStatus=429  timestamp=2026-09-11T08:47:16.283Z
      quotaLimits={"status":"rejected","resetsAt":1789117800,"rateLimitType":"five_hour",...}
      content=[{"type":"text","text":"You've hit your session limit · resets 9:10am (UTC)"}]
```

The parent's tool_result for its `tool_use_id` `toolu_01ToHPSuGWdfn8XsMtQQmmsB`
(parent line 5425) reads, in full:

```
Agent terminated early due to an API error: You've hit your session limit · resets 9:10am (UTC)
(error type rate_limit, HTTP 429, request id req_011CewMuqTvrEmUSrXtDhKSu, model sent to the API: claude-sonnet-5)

Everything below is PARTIAL output recovered from the agent before it was cut off. The agent did NOT finish its task — treat these results as incomplete.
Now let's run codex exec with the review prompt.
agentId: aef962fe7ed3ffccf (use SendMessage with to: 'aef962fe7ed3ffccf', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 467723
tool_uses: 88
duration_ms: 769045</usage>
```

`"Now let's run codex exec with the review prompt."` is the whole of its recovered
output — the agent was killed **at** the Codex step, 39 seconds before its sibling.
There is no `STATUS: complete` in this transcript, and no `end_turn` record.

`a436a869f92470a38` — cleanliness-inspector, "Cleanliness inspection for close attempt 4",
125 lines, identical shape:

```
$ grep -c "STATUS: complete"        agent-a436a869f92470a38.jsonl   → 0
$ grep -c '"stop_reason":"end_turn"' agent-a436a869f92470a38.jsonl  → 0
$ grep -c "usage limit"              agent-a436a869f92470a38.jsonl  → 0
```

```
L123  assistant  tool_use  [Write]
L124  user       tool_result
L125  assistant  stop_reason=stop_sequence  isApiErrorMessage=True  apiErrorStatus=429
      content=[{"type":"text","text":"You've hit your session limit · resets 9:10am (UTC)"}]
```

Parent tool_result (line 5430): `"…Everything below is PARTIAL output recovered…"` +
`"Now writing the final report."`. It was killed one record before writing its report.

Note what this means for the mechanism: for these two, `QUOTA_RE` matched the *harness's
own* abort banner, so the classification was right **by accident** — the same regex would
have fired identically on an agent that merely quoted that banner.

### 5b. Real false positives — the agent's own clean report trips the regex

`a01ac84de7d3b767e` — general-purpose, "Read and drive 378492fd". Last transcript record
is `stop_reason: "end_turn"`; parent received the full 6 009-character report. Its job was
to *diagnose another session's quota interruption*, so its report quotes the banner twice:

````
## Final turn: quota interruption, not a clean finish

The session's last transcript entry (2026-09-05T19:36:58.770Z, `isApiErrorMessage: true`) is verbatim:

```
You've hit your session limit · resets 9:20pm (UTC)
```

Immediately before it, the last tool_result records that its lane-d QA subagent was
itself killed by the same limit:

```
Agent terminated early due to an API error: You've hit your session limit · resets 9:20pm (UTC)
(error type rate_limit, HTTP 429, request id req_011Cekrbs9xcfHNs3dQ4p88G, …
```
````

Triggering substring: `You've hit your session limit` (×2), inside a fenced quotation of
*another* session's log. Report ends cleanly with an operational recommendation:
`"…so this is not close-ready. Whoever drives it next should expect a QA-iteration
decision, not a /close."`

`ae822c167ffd478e7` — general-purpose, "Measure drift since 15:42Z gate". Clean
`end_turn`; 11 029-character report delivered. The match is not even a quota sentence —
the `(?:anthropic|claude)[^\n]{0,80}rate[-_ ]limit` alternative spans 80 arbitrary
characters from a **filename** to an unrelated parenthetical about a hook's throttle:

```
- **15:44:40.007Z** — `/tmp/claude-pressure-warn-ec2ae4f0-…` written, counter `3`
  (the hook's rate-limit maximum). This is `hooks/userprompt-tmpfs-pressure.sh`, a
  **tmpfs**-pressure warning about /tmp being full, n…
```

Matched substring, verbatim:
`claude-pressure-warn-ec2ae4f0-…` written, counter `3` (the hook's rate-limit`

The sentence's own point is that this is a **disk**-pressure warning, explicitly *not* a
quota event. The regex flagged it as a quota interruption anyway.

`aae9f640dbbebc2da` — qa, "Final verification round 2 of R4". Clean `end_turn`, verdict
**PASS**, 3 238-character report delivered. Triggering substring
`Claude-usage-API HTTP 429 rate-limit`, from a sentence disclosing a flaky test:

```
…the 64th (`tests/test_paseo_usage_read.py::test_live_adapter_read_only_run_exits_zero_with_per_account_rows`)
is independently root-caused to a live external Claude-usage-API HTTP 429 rate-limit at
run time — unrelated to and untouched by this cycle's diff.
```

`af2c8a271aa70b4a1` — general-purpose, "Drive e1c60053 restart". Clean `end_turn`, three
separate matches, including `reset at 1` from the prose `"its quota window reset at 15:50
UTC and the session reconnected"` — i.e. the detector flagged an agent for reporting that
a quota window had **ended**.

All 25 `completed_clean` agents match this profile: 24 `general-purpose` + 1 `qa`, all
from 2026-09, all doing quota-recovery reconnaissance, all tripped by quoting the thing
they were sent to measure.

### 5c. The detector manufactures its own future false positives

13 agents (`completed_then_resume_interrupted`) delivered a clean `end_turn` report and
were then re-woken and killed during the follow-up turn. In **10** of the 13 the follow-up
turn was started by this very mechanism — `a956b0ba3760f2c3c` is representative:

```
L30  assistant  stop_reason=end_turn   "Three lines as asked: 1. **Message sent** — the bare literal `/restart` …"
L31  user       "The coordinator sent a message while you were working:
                 [awesome-claude-harness/restart-v1]
                 parent_session_id=0a0db999-3273-4172-82e1-9ef1c91a8fa2
                 agent_id=a956b0ba3760f2c3c
                 Resume this exact existing subagent from its persisted transcript …"
L33  assistant  tool_use
L36  assistant  stop_reason=stop_sequence  isApiErrorMessage=True
                "You've hit your session limit · resets 3:50pm (UTC)"
```

A prior `/restart` resumed an agent that had already finished; the redundant resume turn
burned quota and was itself killed; the kill wrote a fresh abort record, which makes the
agent a candidate again on the next `prepare`. The remaining 3 of 13 were re-woken by
`Stop hook feedback: [python3 "/root/.claude/hooks/subagentstop-codex-enforce.py"]:
CODEX_ENFORCE_BLOCKED…` rather than by the coordinator.

## 6. Step-3 hand verification (5 randomly sampled pending candidates)

Sampled with `random.sample(pending, 5)` over the 213 `status: "pending"` records,
unseeded. Each transcript was then read directly from disk with `wc`/`grep`/`tail` —
not by re-running the Step-2 classifier.

| # | agent_id | type | Hand-read finding | Script | Match |
|---|---|---|---|---|---|
| 1 | `aae9f640dbbebc2da` | qa | 273 lines, `end_turn`×1, apiErr×0. Last line is the terminal report: `"The report is valid and correctly structured… **Verdict: PASS** — verification report written to …/qa-report-20260910-091226.json"` | `completed_clean` | ✅ |
| 2 | `a39b7b1e65a350add` | dev | 92 lines, `end_turn`×0, apiErr×1. Last line `"model":"<synthetic>","stop_reason":"stop_sequence"` abort record, ts `2026-05-24T18:16:26.088Z`; previous line is a `tool_result` (`Output too large (150KB)…`). **No report.** | `never_reported` | ✅ |
| 3 | `a82e047c625e6124d` | qa | 59 lines, `end_turn`×1, apiErr×1. Reported cleanly, then the second-to-last record is a `user` string `"Stop hook feedback:\n[python3 \"/root/.claude/hooks/subagentstop-codex-enforce.py\"]: CODEX_ENFORCE_BLOCKED: agent a82e047c625e6124d (type=qa) has not called codex skill in session dev-20260915-0515…"`, and the forced continuation turn was killed. | `completed_then_resume_interrupted` | ✅ |
| 4 | `aa6871bd32997c8f6` | general-purpose | 14 lines, `end_turn`×0, apiErr×1. Ends on the synthetic abort record, ts `2026-09-03T17:57:27.243Z`; previous line a `tool_result`. **No report.** | `never_reported` | ✅ |
| 5 | `a82df5a8f6da22ad0` | spec | 51 lines, `end_turn`×0, apiErr×1. Ends on the synthetic abort record, ts `2026-06-04T21:44:41.603Z`; previous line a `tool_result` for a successful write to `docs/dev/specs/20260604-204954/views/dev.md`. **No report.** | `never_reported` | ✅ |

**5 of 5 agree with the script. 3 of the 5 are genuine interruptions with no terminal
report — flagging this loudly, as instructed.** The sample is consistent with the
population: 171/210 (81.4%) of candidates really were cut off. The "these are months old,
they must have finished" intuition is wrong in the specific way that matters — of the 149
candidates whose transcripts start in 2026-05/06/07, **zero** are false positives and 125
carry an explicit harness abort record. Old candidates are not stale successes; they are
old failures that were never recovered.

## 7. Why the false-positive rate rises with operational stress

A detector that does not check the structural fact it claims to detect — whether *this*
agent's own process was interrupted — but instead pattern-matches a cheap textual proxy
(the substring `usage limit` / `rate_limit` / `resets at N` appearing anywhere in a report
body) is unsound. It is unsound in a way that gets **worse exactly when the detector is
most needed**: when many subagents are genuinely reporting on quota exhaustion during a
widespread outage, nearly every one of them accumulates the same trigger text, so the
false-positive rate rises together with real operational stress rather than staying
constant.

This is not a hypothesis on this corpus; it is the measurement:

| Month of transcript | Candidates | False positives | FP rate |
|---|---|---|---|
| 2026-05 | 94 | 0 | **0.0%** |
| 2026-06 | 49 | 0 | **0.0%** |
| 2026-07 | 6 | 1 | 16.7% |
| 2026-08 | 1 | 1 | — |
| 2026-09 | 60 | 37 | **61.7%** |

May and June are ordinary fan-out months: agents were doing dev/qa/ba work and did not
talk about quota, so the proxy and the fact coincided and precision was perfect. September
is the quota-outage recovery campaign — the months when `general-purpose` scouts were
dispatched specifically to *read other sessions' quota banners and report them* — and
precision collapses to 38%. The detector's error is strongly, mechanically correlated with
the very condition it exists to handle. Worse, §5c shows the correlation is partly
self-generated: each redundant resume the false positive causes burns quota and produces a
fresh abort record, feeding the next sweep.

The consequences are not symmetric but they are both real:

- **False positives (39 agents)**: redundant `SendMessage` resumes of agents that already
  delivered their report. Each costs a full context reload plus a model turn, under quota
  pressure, for no work product — and manufactures a new abort record when it fails.
- **The reverse failure is not observed here** — `missing_parent_tool_result` is 0/26
  wrong — but note that a genuinely-cut-off agent whose partial output happens to contain
  no quota-shaped string and whose parent *did* receive a (partial) result would carry no
  evidence code at all and be silently dropped from recovery. The detector has no
  structural check that would catch it.

**The fix is a one-line change of subject, not a regex tune.** `discover_candidates()`
already computes `agent_transcript_path` for every candidate. Reading that file and asking
whether any record carries `stop_reason == "end_turn"` answers the actual question, costs
one file read per candidate, and is not defeatable by report prose. Tightening `QUOTA_RE`
cannot fix it: the trigger text in §5b is, in two of four cases, a *correct and desirable*
sentence in an agent's report.

## 8. Cross-reference — third instance of the same defect family

For whoever compiles this into the spec: this joins two findings already logged from the
same session as a third instance of one defect family — **a cheap proxy metric standing in
for the structural fact that was supposed to be checked.**

| Ref | Finding | The proxy | The structural fact it displaced |
|---|---|---|---|
| **D2** (logged earlier; recurred this session) | A latch field read as if it were live state | the latch's stored value | whether the condition is true *now* |
| **R39** (spec `docs/dev/specs/spec-20260906-harness-fixes-dev-ready.md`, family **F1** "匹配与锚定:无规范形式的文本匹配") | Artifact-glob resolution collapsing distinct task-ids via prefix matching | task-id as a string *prefix* | task-id identity |
| **this doc** | `/restart` interruption detection | quota-shaped substring anywhere in the report body | whether this agent's own process emitted a terminal report |

All three substitute an easily-computed textual/stored surrogate for the structural
predicate, and in all three the surrogate is available while the real predicate is also
available at comparable cost — R39's task-ids are exact-matchable, D2's condition is
re-readable, and here the child transcript is already named in the candidate record. This
one belongs under F1 alongside R39: both are unanchored text matching, and in both cases
the over-inclusion is silent.

---

## Appendix — reproduction

```
python3 /tmp/restart_classify2.py          # full classification, all 217 records
cat /tmp/restart_classification2.json      # per-candidate verdict + reason + tail
cat /tmp/genuinely_interrupted_full.tsv    # the 171: agent_id, parent_session_id, type, reason, description
```

The 171 genuinely-interrupted agents all carry the same `resume_message`, differing only
in two interpolated fields:

```
[awesome-claude-harness/restart-v1]
parent_session_id=<parent_session_id>
agent_id=<agent_id>

Resume this exact existing subagent from its persisted transcript after a quota or session-limit interruption.
First inspect the last tool call/result and current workspace side effects. Do not replay irreversible operations.
Continue only the original single assigned issue; do not broaden scope and do not spawn a replacement agent.
If the original work was already complete, make no duplicate edits and re-emit the terminal report after verification.
If quota blocks again, end with `RECOVERY_STATUS: quota_interrupted`; otherwise end with `RECOVERY_STATUS: completed`.
```

Verified programmatically: normalising `parent_session_id=` and `agent_id=` collapses all
217 `resume_message` values to exactly **1** distinct template.
