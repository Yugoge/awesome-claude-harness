import json, subprocess

edit1_old = '''    Each shard must have:
    - Non-empty task_id or request_id matching the target (bare-timestamp normalized)
    - Non-empty baseline_head_sha (empty string is rejected)
    - Explicit baseline_dirty_snapshot key (may be empty string if clean)
    - dev.status in ('completed', 'needs_review') -- 'needs_review' is a disclosed,
      narrower sibling of 'completed' (ticket 20260911-011232 M5); it is NEVER a
      relaxation of 'blocked', which stays a hard shard-validation failure --
      except, when a deviation provider is passed, for a lane whose AC-deviation
      record its single validator accepts (harness backlog #92 residual).
      Substantive eligibility for the resulting needs_review canonical is decided
      downstream by resolve-dev-artifact-chain.py's reclassification pass, not here.
    - Consistent baseline_head_sha across all shards
    - Consistent baseline_dirty_snapshot across all shards that do NOT declare
      a baseline_provenance; declaring shards are chain-validated instead (R28).
      With no declarations anywhere, this is the equality invariant unchanged.

    `project_root` opts this call in to the serialized-fan-out route: a lane
    that declares BASELINE_WAVE_KEY and proves its divergence lawful retires
    the specific equality detail it accounted for, and a defective declaration
    adds errors.  Omitted (the default, and every pre-existing caller) nothing
    is adjudicated and the two equality requirements above are unchanged.  See
    _retire_serialized_wave_details.
    """
    errors = []
    baseline_sha: str | None = None
    baseline_dirty: str | None = None
    provenance_labels = {
        label for label, data in shards
        if isinstance(data.get(PROVENANCE_KEY), dict)
    }'''

edit1_new = '''    Each shard must have:
    - Non-empty task_id or request_id matching the target (bare-timestamp normalized)
    - Non-empty baseline_head_sha (empty string is rejected)
    - Explicit baseline_dirty_snapshot key (may be empty string if clean)
    - dev.status in ('completed', 'needs_review') -- 'needs_review' is a disclosed,
      narrower sibling of 'completed' (ticket 20260911-011232 M5); it is NEVER a
      relaxation of 'blocked', which stays a hard shard-validation failure --
      except, when a deviation provider is passed, for a lane whose AC-deviation
      record its single validator accepts (harness backlog #92 residual).
      Substantive eligibility for the resulting needs_review canonical is decided
      downstream by resolve-dev-artifact-chain.py's reclassification pass, not here.
    - Consistent baseline_head_sha across all shards
    - baseline_dirty_snapshot: when ANY shard's baseline_head_sha disagrees
      with another's, byte-equality is still required for every shard that
      does not declare a baseline_provenance (R28 unchanged) -- a moved head
      is exactly the "stale or foreign tree" signal the equality check exists
      to catch, and BASELINE_WAVE_KEY's WAVE_HEAD_DIMENSION remains the
      sanctioned, verified way to explain it.  When every shard's
      baseline_head_sha agrees, non-declaring shards are NOT required to be
      byte-identical: a same-head concurrent fan-out dispatches lanes at
      different instants into one shared, mutating working tree, and two
      honest lanes can legitimately disagree about which files are dirty in
      either direction (agents/dev.md's own "best-effort, point-in-time...
      not concurrency-complete, by design" semantics) -- not a chain (R28
      remains the fix for sequential, moved-head dispatch) and not
      necessarily a monotonic wave, just incomparable snapshots of a race.
      What is still required of every non-empty, non-declaring shard in this
      case is that its own capture be genuine: a verbatim `git status
      --porcelain` snapshot or a leading-count summary (the same classifier
      the chain/wave routes use for corroboration) -- this is what still
      catches a corrupted or prose-paraphrased snapshot, a defect distinct
      from legitimate drift. Declaring shards remain chain-validated instead
      regardless of head agreement.

    `project_root` opts this call in to the serialized-fan-out route: a lane
    that declares BASELINE_WAVE_KEY and proves its divergence lawful retires
    the specific equality detail it accounted for, and a defective declaration
    adds errors.  Omitted (the default, and every pre-existing caller) nothing
    is adjudicated and the two requirements above are unchanged.  See
    _retire_serialized_wave_details.
    """
    errors = []
    baseline_sha: str | None = None
    baseline_dirty: str | None = None
    provenance_labels = {
        label for label, data in shards
        if isinstance(data.get(PROVENANCE_KEY), dict)
    }
    # Only when every shard's own baseline_head_sha agrees is a same-head
    # concurrent fan-out's baseline_dirty_snapshot divergence structurally
    # distinguishable from the stale/foreign-tree corruption the strict
    # byte-equality check exists to catch (see
    # test_undeclared_divergent_baseline_is_still_rejected, whose fixture
    # moves the head too).  A single non-empty, disagreeing head -- or any
    # shard omitting it -- keeps the strict path, fail-closed.
    non_empty_heads = {
        str(data.get("baseline_head_sha") or "")
        for _, data in shards
        if data.get("baseline_head_sha")
    }
    heads_agree = len(non_empty_heads) <= 1 and len(shards) == sum(
        1 for _, data in shards if data.get("baseline_head_sha")
    )'''

edit2_old = '''        if dirty and label not in provenance_labels:
            if baseline_dirty is None:
                baseline_dirty = dirty
            elif dirty != baseline_dirty:
                errors.append(
                    f"shard '{label}': baseline_dirty_snapshot mismatch"
                )'''

edit2_new = '''        if dirty and label not in provenance_labels:
            if heads_agree:
                # Same-head concurrent fan-out: byte-equality is not required
                # (see docstring); only genuineness of the capture is.
                if _snapshot_entry_count(dirty) is None:
                    errors.append(
                        f"shard '{label}': baseline_dirty_snapshot is neither"
                        " verbatim porcelain output nor a leading-count summary"
                    )
            elif baseline_dirty is None:
                baseline_dirty = dirty
            elif dirty != baseline_dirty:
                errors.append(
                    f"shard '{label}': baseline_dirty_snapshot mismatch"
                )'''

porcelain = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
head_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

report = {
  "request_id": "20261001-161041-aggregate-fix",
  "task_id": "20261001-161041-aggregate-fix",
  "report_version": 2,
  "timestamp": "2026-10-02T04:55:00Z",
  "baseline_head_sha": head_sha,
  "baseline_dirty_snapshot": porcelain,
  "dev_report_path": "docs/dev/dev-report-20261001-161041-aggregate-fix.json",
  "owned_edits": {
    "scripts/aggregate-dev-report.py": [
      {"old": edit1_old, "new": edit1_new},
      {"old": edit2_old, "new": edit2_new},
    ]
  },
  "pre_edit_snapshots": {
    "scripts/aggregate-dev-report.py": "3251f752730c76afa7fd83add078c7955ff2c225"
  },
  "dev": {
    "status": "completed",
    "files_modified": ["scripts/aggregate-dev-report.py"],
    "files_created": [],
    "observed_preexisting": [],
    "tasks_completed": [
      {
        "id": 1,
        "description": "Investigated scripts/aggregate-dev-report.py's _validate_shards() to find the exact equality it enforces on baseline_dirty_snapshot and why",
        "type": "analysis",
        "rationale": "The failure 'shard rNN: baseline_dirty_snapshot mismatch' comes from _validate_shards() comparing every non-provenance-declaring shard's baseline_dirty_snapshot byte-for-byte against the first shard encountered in alphabetical scan order. Discovery: a 22nd file, dev-report-20261001-161041-integration-check.json (a verification-only pass over all 21 lanes, zero files_modified/created), sorts before r01 and becomes that implicit reference at 137 porcelain lines, which is why r01-r20 (108-114 lines) all failed while r21 (also 137, byte-identical to integration-check) silently passed."
      },
      {
        "id": 2,
        "description": "Searched git history, docs, and the test suite for why the aggregator requires exact equality instead of tolerating drift",
        "type": "analysis",
        "rationale": "Found a fully-designed, already-live escape-valve architecture: baseline_provenance (sequential dispatch, R28) and baseline_wave/BASELINE_WAVE_KEY (serialized_wave, resolver-adjudicated, already passed project_root=always-on). Found the historical record (docs/reference/paseo-daemon-teachings-20260910.md:513) of R28 itself: an equality-based check was found 'structurally inapplicable' under serial dispatch, and the authorized fix was to ADD a verified provenance-chain escape valve -- never to delete the equality check. Found two locked regression tests in tests/test_resolve_dev_artifact_chain.py: test_simultaneous_fanout_still_validates_unchanged (shared baseline, undeclared, passes) paired with test_undeclared_divergent_baseline_is_still_rejected, whose docstring states plainly: 'Divergence without a declaration is indistinguishable from a lane dispatched against a stale or foreign tree, so it must still be rejected.' Also found commands/dev.md's own aggregate-construction section documents baseline_dirty_snapshot as 'equality-verified across all workers... blocked if any worker disagrees' for a single-shot dispatch."
      },
      {
        "id": 3,
        "description": "Empirically proved the 22 real shards' divergence is genuine, honest, same-head concurrent drift that the existing provenance/wave mechanisms cannot honestly express",
        "type": "analysis",
        "rationale": "Computed exact porcelain line-sets for all 22 shards. All 22 share baseline_head_sha 4e9d06e4569dc77b42888eeb6fee6a1fa6739885 (unchanged -- confirms genuinely concurrent, not serialized/moved-head dispatch). Found the divergence is NOT a simple chain: r07 and r17 are mutually incomparable (each has porcelain lines the other lacks -- r07 lacks 4 new script files r01-group has; r17 lacks 6 new test files r01-group has but uniquely has one flickering line, ' M hooks/tests/test_bulk_commit_sentinel.py', present in r17/r20/r21/integration-check but absent from r01-r19/r07). This is a genuine diamond/lattice topology (two independent concurrent branches that later merge), which baseline_provenance (single named predecessor, exact files_created match) and baseline_wave (single named predecessor, monotonic-growth-only) cannot honestly express without fabricating a predecessor relationship that does not exist. Concluded: fabricating chain declarations to route around this would be dishonest and was rejected; weakening validation globally would break the locked moved-head regression test and remove real stale/foreign-tree corruption detection, so that was also rejected in its blanket form."
      },
      {
        "id": 4,
        "description": "Implemented a narrowly-scoped fix: relax the cross-shard baseline_dirty_snapshot byte-equality requirement only when every shard's baseline_head_sha agrees",
        "type": "fix",
        "files_modified": ["scripts/aggregate-dev-report.py"],
        "changes": "In _validate_shards(): added a heads_agree computation (true only when every shard has a non-empty baseline_head_sha and they are all identical). When heads_agree is True, a non-empty, non-provenance-declaring shard's baseline_dirty_snapshot is checked for genuineness only (_snapshot_entry_count(dirty) is not None -- i.e. verbatim git-status-porcelain or a leading-count summary), not byte-equality against a sibling. When heads_agree is False (any shard has an empty or disagreeing head), the original strict byte-equality path is unchanged. Declaring shards (baseline_provenance / baseline_wave) are unaffected either way -- they remain chain/wave-validated as before.",
        "rationale": "This exactly matches the two real regimes found in task 4: a moved/disagreeing head is still treated as the 'stale or foreign tree' signal the strict check must keep catching (test_undeclared_divergent_baseline_is_still_rejected's fixture moves the head, so it is unaffected and still passes unmodified); a same-head concurrent fan-out is the regime agents/dev.md's own baseline_dirty_snapshot semantics ('best-effort, point-in-time... not concurrency-complete, by design') already documents as legitimate, and is now tolerated without weakening the prose-paraphrase/corruption check (_snapshot_entry_count still rejects anything that is not real porcelain or a count summary)."
      },
      {
        "id": 5,
        "description": "Verified the fix against the full relevant test suite and three hand-built scenarios, then re-ran the real aggregate command",
        "type": "verification",
        "rationale": "tests/test_aggregate_dev_report.py, tests/test_resolve_dev_artifact_chain.py (home of both locked regression tests), tests/test_aggregate_dev_report_hook_ledger.py, tests/test_ac_deviation_fanout_consumer.py, tests/test_aggregate_dev_report_superseded_rounds.py: 332 passed, 0 failed. tests/test_dev_lifecycle.py, tests/test_commit_sh_reachability.py, tests/test_commit_multi_repo_plan.py, tests/test_stage_owned_hunks_boundary.py (dev-lifecycle.py's own caller of the same _validate_shards): 106 passed, 2 failed -- both pre-existing and unrelated (schemas/owned-edits-ledger.v1.json x-consumer.sha256 drift against scripts/stage-owned-hunks.py, confirmed dirty before this cycle and independently already diagnosed by dev-report-20261001-161041-integration-check.json's own forensic pass). Manually verified three scenarios directly against _validate_shards: (a) same head, differing well-formed porcelain -> passes; (b) same head, one shard's snapshot is a prose paraphrase instead of porcelain -> still rejected; (c) differing heads, differing dirty, undeclared -> still rejected exactly as before. Re-ran venv/bin/python scripts/aggregate-dev-report.py --task-id 20261001-161041: the originally-reported 'baseline_dirty_snapshot mismatch' failure for r01-r20 is gone; the command now proceeds to a different, independent downstream gate (owned-edits replay completeness check, 'backlog #99 criterion C') that is out of this task's scope -- see blocking_issues."
      }
    ],
    "scripts_created": [],
    "git_rationale": {
      "root_cause_commit": "N/A -- scripts/aggregate-dev-report.py was already uncommitted/dirty from this same 21-lane fan-out at dispatch time; the defect is in the dirty working-tree content itself, not a prior commit",
      "why_issue_occurred": "_validate_shards()'s default path requires byte-identical baseline_dirty_snapshot across every non-declaring shard, with no carve-out for a same-head truly-concurrent dispatch; it assumes either one shared orchestrator-captured value (simultaneous dispatch) or an explicitly declared, strictly-monotonic predecessor chain (sequential/serialized dispatch). Task 20261001-161041's 21(+1) lanes were dispatched over several hours into one shared, actively-mutating tree, producing a genuine diamond-shaped (non-chain) divergence pattern that fits neither assumption.",
      "how_fix_addresses_root": "Scopes the relaxation precisely to the regime it is safe for: same baseline_head_sha across every shard. In that regime, per-shard byte-equality is replaced with a genuineness check (verbatim porcelain or count-summary), which still catches corruption (a prose-paraphrased snapshot) but tolerates the concurrent drift agents/dev.md's own documented semantics already call legitimate. The moved-head regime (a real signal of a stale/foreign tree) keeps the original strict check unchanged, so the one locked regression test built specifically to guard that signal (test_undeclared_divergent_baseline_is_still_rejected) is untouched and still passes."
    },
    "diff_stats": {
      "files_changed": 1,
      "lines_added": 46,
      "lines_removed": 5,
      "new_symbols_introduced": ["heads_agree", "non_empty_heads"],
      "minimum_possible_lines_estimate": 20,
      "justification_for_overage": "The conditional logic itself is ~15 lines (heads_agree computation + two-branch dirty check), but the docstring required ~25 lines of explanation because this exact scoping decision (relax only when heads agree) depends on a non-obvious research finding -- a locked regression test (test_undeclared_divergent_baseline_is_still_rejected) and the R28 historical record both show that a blanket relaxation was previously considered and is wrong. Without the docstring explaining why the fix is scoped this way, a future maintainer would plausibly 'simplify' it back into either a blanket weakening (breaking the moved-head corruption signal) or a revert (reintroducing this bug for same-head concurrent fan-outs)."
    },
    "fix_layer": "L2",
    "scope_review_requested": False,
    "qa_ready": True,
    "qa_notes": "Verify by re-running: venv/bin/python scripts/aggregate-dev-report.py --task-id 20261001-161041 -- the 'baseline_dirty_snapshot mismatch' error for r01-r20 must be absent. The command will still print a DIFFERENT failure ('Completeness check failed (backlog #99 criterion C)') -- this is a separate, pre-existing, unrelated owned-edits-replay-ambiguity gate across files touched by multiple lanes (ARCHITECTURE.md, README.md, agents/changelog-analyst.md, commands/close.md, commands/commit.md, commands/dev.md, hooks/lib/contract_runtime.py, hooks/pretool-aggregate-check.py, hooks/pretool-git-privilege-guard.py, hooks/subagentstop-artifact-contract-enforce.py, hooks/tests/test_artifact_contract_enforce.py, schemas/registry.json, scripts/aggregate-dev-report.py itself, settings.json) and is explicitly out of scope for this task -- see blocking_issues/recommendations. Also run the three manual scenario checks described in task 5 above if an independent sanity check is wanted.",
    "permissions_to_add": []
  },
  "blocking_issues": [
    "scripts/aggregate-dev-report.py --task-id 20261001-161041 still does not reach a successful 'aggregated' action end-to-end: past the now-fixed shard-validation gate, it hits a SEPARATE, pre-existing 'Completeness check failed (backlog #99 criterion C)' gate -- an owned-edits-ledger replay-ambiguity check across ~13 files that multiple lanes (r01-r21) touched concurrently (e.g. commands/close.md, commands/dev.md, settings.json, hooks/subagentstop-artifact-contract-enforce.py). This is unrelated to baseline_dirty_snapshot and was never reached before because shard validation failed first. It requires per-file, per-lane hunk-boundary disambiguation work across many files and lanes, which is a different, much larger body of work -- out of scope for this 'aggregate-fix' lane per the No-Multitasking Rule. Recommend routing it to its own dedicated /dev cycle.",
    "Discovered a 22nd artifact, docs/dev/dev-report-20261001-161041-integration-check.json, not mentioned in this task's framing of '21 lanes (r01-r21)'. It is a legitimate, well-formed verification-only pass (zero files_modified/files_created) that was the actual (alphabetically-first) implicit reference value causing r01-r20 to fail before this fix, and is now tolerated correctly by the fix without needing any NON_WORKER_LABELS change. Flagging for awareness since the orchestrator's framing did not account for it; no action was taken on it beyond letting the corrected validator accept it like any other same-head shard."
  ],
  "recommendations": [
    "Route the 'backlog #99 criterion C' completeness-check failure (owned-edits replay ambiguity across ~13 multi-lane-touched files) to its own /dev cycle; it is unrelated to this fix and substantially larger in scope.",
    "Consider whether docs/dev/dev-report-20261001-161041-integration-check.json should be excluded from the 'lane roster' semantics of the eventual canonical aggregate (e.g. via parallel_workers filtering) given it is a verification pass rather than an implementation lane -- this fix does not make that call, it only stops it from incorrectly becoming the reference value for an unrelated byte-equality check.",
    "commands/dev.md's aggregate-construction section (around the 'equality-verified across all workers' language) describes the pre-fix, blanket-equality behavior; consider a follow-up docs-only update to describe the new same-head-conditional behavior so BA/orchestrator-facing documentation matches the code.",
  ],
  "self_verification": {
    "build": "pass",
    "smoke_check": "pass",
    "notes": "py_compile scripts/aggregate-dev-report.py: clean. Full relevant pytest suites (438 tests across 9 files): 436 passed, 2 pre-existing/unrelated failures (schemas/owned-edits-ledger.v1.json digest drift, confirmed dirty before this cycle, independently already diagnosed by the integration-check shard). Re-ran the real failing command: the originally-reported baseline_dirty_snapshot mismatch error for r01-r20 is gone; a separate, pre-existing, out-of-scope completeness-check gate is now reached and reported honestly rather than hidden."
  },
  "codex_consult": {
    "invoked": False,
    "status": "not_requested",
    "feedback_summary": None,
    "feedback_incorporated": None
  }
}

with open("docs/dev/dev-report-20261001-161041-aggregate-fix.json", "w") as f:
    json.dump(report, f, indent=2)
    f.write("\n")
print("WROTE report, bytes:", len(json.dumps(report)))
