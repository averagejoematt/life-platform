# OPERATING DISCIPLINE — the reflexes for running the work

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-27

The canonical home for the reflexes that govern **how work is adjudicated and how a
session is driven** — believing a finding, closing an issue, judging an epic, running
concurrent lanes, reading a record. Each one was learned from a real incident.

This page exists because those reflexes had no repo home. `docs/CONVENTIONS.md` is the
canonical home for the **deploy/CI/git** reflexes and `docs/CHARTER.md` for the
**architecture** primitives; both were already true. The third family — the one that
decides whether a finding is real, whether an issue is actually done, and how two agents
share a checkout — lived only in the operator's private Claude memory files, outside git,
on one laptop (`docs/CONTINUITY.md` §4). #2848 is the migration; this is where it landed.

**The one-place rule holds.** A rule stated here is not restated in `CONVENTIONS.md`,
`CHARTER.md`, `CLAUDE.md` or a subagent prompt, and vice versa — §6 below is the routing
table for what deliberately lives elsewhere. If you find a rule in two places, one copy
is stale: fix it to a one-line pointer.

**What this page is not:** it is not an incident log. Each rule carries only the measured
evidence that makes it binding. The full narrative of the night each was learned stays in
the memory corpus (Appendix A) and in `docs/INCIDENT_LOG.md`.

---

## 1. Before you act on a finding

1. **Verify the finding before implementing it.** Measured across review fan-outs on this
   codebase, roughly **half** of first-pass subagent findings are false positives — a
   guard already present, an intentional design, an AST-evaded pattern. The adversarial
   second pass is `.claude/agents/finding-verifier.md`; run it, and reproduce the
   evidence yourself before writing code against a finding.

2. **Re-measure the premise, not just the claim.** An issue's stated cause is a
   hypothesis someone wrote at filing time, not a finding. In one 8-lane session **three
   lanes falsified the premise of the issue they were sent to fix** — one of them after
   the module built against the wrong theory had already been written and reverted
   unshipped. Read live data before accepting the frame.

3. **Two methods agreeing is evidence; one method repeated is not.** A wrong query form
   returns "nothing" and reads exactly like a broken system — four times in one session
   (missing `--no-paginate`, a missing metric dimension, querying logs where the answer
   was in metrics, a bash library sourced under zsh). Re-measure a *different* way before
   filing or reporting.

4. **Never diagnose from a truncated log line.** A 300-character monitor summary produced
   a confident, wrong root cause that was reported to the owner and recorded on an issue.
   Pull the run's artifact, not the truncated line the notifier showed you.

5. **An LLM/judge verdict can flake HIGH on a claim that is true.** Ground-truth the
   claim against the data before acting on it — one such flake rolled back the very fix
   it was judging. The artifact is the evidence; the verdict line is not.

6. **When an LLM gate's findings recur as a class, read the gate's own prompt first.**
   The model may be *obeying* a wrong instruction rather than hallucinating: three
   consecutively blocked deploys traced to one bullet in a rubric.

7. **When an issue offers "fix it or accept it", measure the rate before choosing.** An
   acceptance that optimises the open-issue count and not the defect rate is dishonest.
   Measured, then declined: 1 false red per 1.6 days and not improving is not an
   acceptable rate.

8. **An agent's stated reason for its own red check is a hypothesis written before the
   lane finished.** It is not a read lane. See §3.7 for what to do instead.

> Instrument verification — proving a *gate/check/watcher* can fail, its fixture is the
> wire, and it is not dark — is a different question with a different home:
> `docs/CONVENTIONS.md` §9a and the gate registry in §9. Do not restate it here.

---

## 2. Adjudicating work — issues, PRs, epics

1. **Partial acceptance is not a close.** A merged PR that satisfies *part* of an issue's
   acceptance closes the PR, not the issue. Merge the work, reopen the issue, and name
   which boxes are unmet. (Three issues were wrongly closed this way in one day.) The
   full definition-of-done for a close — the verdict comment, every named residual
   disposed to exactly one home, nothing said after `closedAt`, epics after their
   children, the PR's closing set equal to the lane's declared target — is the registry
   `scripts/closure_contract.py` (#3318), rendered in `docs/CONVENTIONS.md` §4a2 and
   enforced (advisory) by its two detectors; it is not restated here.

2. **An epic is judged by its Outcome sentence, never by its child count.** An epic can
   have every child closed and every acceptance box verifiably true while its stated
   Outcome is days from failing. Child count is the weakest signal available. Corollary:
   an issue whose Outcome is measurably *unachievable* should be closed, not left open.

3. **Merged is not deployed.** A `Fixes #N` auto-closure proves the merge and nothing
   else. If the PR's pipeline died before the deploy stage, the issue reads closed while
   production runs the old value. Check the deployed artifact post-dates the merge before
   writing "realized" anywhere.

4. **An issue closed citing a PR is not evidence the code is on `main`.** Verify against
   `origin/main`, not against the closing comment.

5. **A closing keyword closes the issue regardless of negation or tense.** "This PR does
   NOT close #N" closes #N; so does "closed #N by accident" in a later commit. The parser
   sees neither the negation nor the past tense — and a `Fixes` in a **commit message**
   beats a corrected PR body, because the commit travels with the squash.

6. **`gh pr merge --delete-branch` closes every PR stacked on that branch**, and a closed
   PR cannot be retargeted. Recovery is restore-branch → reopen → retarget →
   `rebase --onto`.

7. **The ADR-099 score inverts priority when read alone.** Effort is the denominator, so
   a cheap P3 outranks a live P2, and `scripts/backlog_next.py` sorts by score. `prio:P0`
   is the sanctioned override for a live reader-facing defect — it is an escape hatch,
   not a fifth severity tier.

8. **Epic tails are the highest-yield drain.** An epic whose open-children count is 1 or 2
   closes when its last child does — roughly 1.5× the closures per unit of work versus
   cherry-picking the top-ranked issue. Derive the tails from the epics' own bodies, and
   verify the **epic's** acceptance before closing it (§2.2).

9. **An agent's rubric never outranks the owner's own label.** A classification rule
   written into a subagent brief is a heuristic for that agent, not a decision about the
   work — and be extra sceptical when an agent relabels work *out of its own reach*.

10. **Ship the mechanism, print the residual.** When an acceptance box needs human
    judgement over N specific items, land the derived mechanism and hand over a
    **counted, named** queue. Never invent N reasons in order to close it.

11. **No live record identifiers in a public PR body** — not even hashed. This repo is
    public and GitHub keeps the edit history of a body, so a later redaction is not an
    erasure.

12. **Removing a confound reveals the second defect.** "Much better" is not "fixed":
    after a real fix landed, two of eight downstream consumers were still wrong for a
    different reason. Re-measure the whole population after the confound is gone.

---

## 3. Session mechanics — concurrency, watchers, shells

1. **Scratch filenames carry the lane's issue number.** The session scratchpad is ONE
   directory shared by every concurrent agent. Two lanes wrote the same `pr_body.md`,
   clobbered each other in both directions, and a stray `Fixes` line falsely auto-closed
   an issue whose work was still unmerged.

2. **Never `git add -A` in a shared checkout.** It sweeps a concurrent agent's mid-work
   edits into your commit. Name paths explicitly — which is what `deploy/agent_commit.sh`
   requires anyway.

3. **`git checkout <path>` destroys your own unstaged edits to that path and exits 0.**
   This bites when reverting a deliberate mutation probe in a file you were also editing.
   Snapshot the file outside the tree first, and restore from the snapshot.

4. **`pytest … | tail` exits with `tail`'s status, which is 0.** Two full-suite runs were
   called green while carrying `FAILED` lines. The same trap applies to any piped gate
   step. Never read a pass/fail from the exit code of a pipeline whose last stage is a
   pager or a filter.

5. **A watcher exits on any TERMINAL state, plus a time cap — never on "green".** A
   green-only until-loop never completes on failure, so the session stalls at exactly the
   moment it needs to react.

6. **A background task's completion exit code is the wrapper's, not the payload's.** Read
   the output file's own verdict line before believing a lane succeeded.

7. **Before any merge, assert the expected check set BY NAME.** An empty or
   still-registering rollup passes a naive "no failures" filter: `gh pr checks` prints
   nothing both when everything is green and when nothing has attached yet. Two PRs were
   merged past a red full suite because the slow lane had not attached when it was
   sampled. `deploy/wait_pr_green.sh` is the only sanctioned watcher — it asserts the
   expected checks by name, treats "no checks reported" as a failure, and never merges.
   **Read its verdict, then run the merge as its own separate command** — a compound
   `wait && merge` is how the absent-check class keeps re-entering.

8. **Worktrees live outside the repo checkout, one per agent, never reused.** A worktree
   inside the repo is a second checkout that every tree-walking test sees; on macOS the
   case-variant twin path resolves to the same directory and leaks edits into the shared
   main tree. Mechanics and the incident record: `docs/CONVENTIONS.md` §7.

---

## 4. Reading the record

1. **Search for a LATER amendment before restoring anything an ADR describes.** ADRs are
   amended in place and an amendment can reverse an earlier one from the same month —
   "restoring" the state the ADR's body describes has already undone a deliberate
   decision once. Read to the end of the ADR, then check for a dated amendment after it.

2. **A `Verified:` stamp is a human claim, not a derivation.** The freshness gate compares
   *dates*, not content: one engine doc carried a fresh stamp while 18 of its 27 source
   citations were wrong. Re-derive the claim (by AST, by query) rather than trusting the
   stamp — and when a generator exists, run its own `--check`.

3. **Never raise a ratchet baseline to make your own change pass.** Pay for new lines by
   extraction, by folding into an existing structure, or by re-reading whether the change
   is needed. Six baseline collisions, zero raises. The standing rule is
   `docs/CHARTER.md` ("debt counts only ratchet down"); this is the implementer-facing
   form of it. A baseline that legitimately moves because the change *adds a real gate*
   moves in the same PR, with the reason stated.

---

## 5. Production authority — who may deploy, and what a waiting gate is

The `production` GitHub Environment gate is the real authority boundary in this system.
Everything below it — `deploy/deploy_lambda.sh`, `deploy/cdk_deploy.sh`, the site path — is
mechanics, and the mechanics are in `docs/CONVENTIONS.md`. **This section is the only place
that says who may pull the lever.** It exists because the rule previously lived nowhere in
the repo: a session could find *how* to deploy and not *whether it may* (#3264).

1. **The default is ask. Matthew approves production deploys.** Absent an explicit grant,
   a session that believes a deploy is needed **states the ask and stops** — one numbered
   request naming the function or stack, the sha, and why. It does not deploy, and it does
   not approve a waiting gate. "The change is obviously correct" is not an authorization.

2. **A standing grant supersedes the per-action ask, and only a standing grant does.** A
   session brief that says *autonomous with merge+deploy authority* IS the authorization —
   for the whole session, for every action inside it. **Do not re-ask per action**; a grant
   that has to be re-confirmed each time is not a grant, and the re-asking is itself the
   failure mode it was written to prevent. A grant covers the work in front of it, not a
   later session: authority does not carry across the session boundary.

3. **A gated run is a LEASE on a specific sha, not a queue ticket.** Approving it deploys
   *that tree*, not today's. This is the whole risk. A lease minted before later merges
   will ship a tree **older than what is already live** — Session F found one stranded 7.5h
   whose approval would have rolled back two fixes deployed the same session, and Session B
   found a 16.4h lease that would have regressed the fleet. Neither was a hypothetical.

4. **Decode every lease against what is ACTUALLY live before disposing of it.** Not against
   the PR title, not against the merge order, and not against the sha alone — compare by
   **content**: download the deployed bundle and grep for the change (`docs/CONVENTIONS.md`
   has the procedure). A sha comparison cannot see a manual deploy that already shipped the
   same code, which is the common case at the end of a working session.

5. **Dispose of it: approve or reject, never leave it waiting.** `deploy/approve_deployment.sh`
   and `deploy/reject_deployment.sh` are both first-class outcomes, and **rejection is the
   more common correct one** — a superseded lease should be rejected, not approved "to clear
   it". A lease left waiting is not neutral: it queues every later run behind it at zero jobs
   and reads as a wedge (`deploy/watch_deploy_gate.sh`, `scripts/check_deploy_wedge.py`).

6. **Rejecting is not reverting.** A rejected lease ships nothing; it does not undo a deploy
   that already happened. If production is wrong, that is a rollback (`docs/RUNBOOK.md`), a
   separate act with its own authority question — and note the site rollback's scope does not
   reach DynamoDB-sourced content or `/api/*`.

7. **Auto-merge never auto-deploys.** `remediation/automerge.py` merges a narrow allowlisted
   class without a human; CI's production approval gate stays intact behind it (ADR-065). A
   merged PR is not a deployed one, and "it merged" is never evidence that it shipped.

---

## 6. What deliberately lives elsewhere

| Family | Canonical home |
|---|---|
| Deploy, CI gates, git/merge mechanics, doc-sync literals, rollback — the **mechanics** | `docs/CONVENTIONS.md` |
| Who may deploy, standing grants, disposing a waiting gate — the **authority** | §5 above (deliberately NOT in `CONVENTIONS.md`) |
| Proving a gate can fail; fixture-is-the-wire; defect class → owning gate | `docs/CONVENTIONS.md` §9 and §9a |
| Filing discipline — file into the class, not the symptom | `docs/CONVENTIONS.md` §10 |
| The five architecture primitives and the paved roads | `docs/CHARTER.md` |
| Blast radius of a change; which modules feed which | `scripts/blast_radius.py`, `docs/DEPENDENCY_GRAPH.md` |
| Adversarial verification of a review finding | `.claude/agents/finding-verifier.md` |
| One issue → one worktree → one PR, end to end | `.claude/agents/worktree-implementer.md` |
| Backlog contract, labels, milestones, score line | `docs/DECISIONS.md` (ADR-099), `docs/CONTINUITY.md` §6 |
| State surfaces that are not in `docs/` | `docs/CONTINUITY.md` |

---

## 7. Residual — what a memoryless session still cannot determine from this repo

The cold-read exercise for #2848's fourth acceptance box: walk the repo with no session
memory and record what could not be answered. These are the gaps that remain **after**
this page. Each is a real hole, named rather than closed.

1. ~~**Deploy authorization.**~~ **CLOSED 2026-08-28 by #3264** — §5 above. It was the
   highest-value gap on this list: the only one where a successor acting reasonably on repo
   evidence alone could take a destructive production action, or strand the pipeline by
   refusing a safe one. Left visible rather than deleted, so the shape of what was missing
   stays legible.

2. **Which instrument-verification rules are binding.** The "an instrument that reports
   success without doing its job" family — negative controls, denominators, what makes a
   gate go dark — is roughly half the incident corpus and is currently split between
   `docs/CONVENTIONS.md` §9a and the operator's memory. A skill-shaped home for it is in
   flight; until it lands, a fresh session gets the rule only if it reads §9a.

3. **The concurrency posture of a session.** How many lanes run at once, how a driver
   fans out and collects them, and what a lane may assume about the primary checkout are
   nowhere in the repo. §3 above names the *hazards*; it does not describe the *pattern*.

4. **The per-entry incident narrative behind every rule.** By design — see Appendix A.
   The consequence is real and worth stating plainly: a successor can learn *what* the
   rules are from this repo and cannot learn *why* they were expensive.

5. **Thirty-five durable rules with no repo home yet.** Appendix A's `residual` class.
   They are real rules, not narrative; they were left out of §1–§4 because each belongs
   to a surface — render QA, module packaging, semantic-gate baselining, and the whole
   instrument-verification family in gap 2 above — that deserves its own owner rather
   than a bullet on this page. Naming them is the honest half of §2.10.

---

## Appendix A — the memory-corpus audit (2026-08-27, #2848)

**Corpus audited: 154 entries** — every review-discipline entry in the operator's private
Claude-memory index as of 2026-08-27. Each is classified exactly once.

This appendix is a **frozen, dated audit record**, not a maintained registry: the files it
names live outside git on one machine, so nothing in CI can re-derive it. It is kept
because it answers one question a successor will have — *which memory entries are now
redundant, and which are still the only copy.* The **rules** are maintained in their
homes; this table is not.

| Class | n | What it means |
|---|---|---|
| `homed` | 75 | Durable rule, already stated in a repo artifact before this PR. The memory entry is now narrative only. |
| `new` | 32 | Durable rule with **no** repo home until this PR. Stated in §1-§4 above. |
| `residual` | 35 | Durable rule, still no repo home. Named in §6.5; deliberately not migrated here. |
| `narrative` | 10 | Incident detail or a one-off measurement, not a rule. Stays in memory by design. |
| `superseded` | 2 | The finding no longer holds - the machinery it describes was fixed or replaced. |

Entry names below are the memory slugs with their `reference_` / `feedback_` prefix
stripped; each of the 154 appears exactly once.

**`homed` (75):** `a_citation_string_is_not_an_owner`, `a_dependency_missing_makes_a_gate_dark`, `a_derived_artifact_needs_its_lane`, `a_proof_ledger_needs_its_own_freshness_guard`, `a_sweep_one_import_away`, `accuracy_gate_signed_metrics`, `ast_walk_annassign_blindness`, `black_corrupts_json`, `black_pin_path_skew`, `cdk_asset_staging_glitch`, `character_config_generated_page`, `check_existing_page_before_building`, `ci_deploy_race_manual_overwrite`, `ci_extracted_script_needs_checkout`, `ci_masking_and_creds`, `cicd_red_and_archive_moves`, `cloudfront_forwards_client_xff_unchanged`, `collect_only_lane_hides_infunction_imports`, `concurrent_prs_union_breach_size_gate`, `coverage_tranche_x_privacy_gate_union_breach`, `deploy_from_main_not_worktree_branch`, `deploy_timestamp_is_not_the_commit`, `doc_index_strict_ci_only`, `doc_sync_literal_treadmill`, `docsync_apply_writes_inside_conflict_blocks`, `docsync_literal_cross_pr_drift`, `docsync_stamp_is_utc`, `driver_commits_strip_hook_literals`, `fail_closed_scoped_to_artifact_not_lane`, `fixture_must_be_the_wire`, `freshness_window_writer_cadence`, `gh_merge_takes_branch_not_integration_tree`, `gh_merge_worktree_branch_switch`, `gh_pr_checks_empty_is_not_green`, `git_stash_shared_across_worktrees`, `github_event_swallow_recovery`, `github_token_push_never_dispatches`, `gitleaks_push_only`, `golden_tests_wallclock`, `guard_the_set_not_the_instance`, `inrepo_worktree_pollutes_scanners`, `layer_shipped_deps_dependabot_blind`, `mcp_bundle_needs_reading`, `merge_queue_no_blind_add`, `module_relative_config_paths_must_not_encode_depth`, `new_site_page_registries`, `node_check_lazy_parse`, `platform_facts_maintained_literal`, `premerge_registration_moves_the_census`, `prompt_structural_guarantees`, `r8st6_iam_review_gate`, `read_the_deploy_critical_lane_by_name`, `rebase_continue_phantom_wedge`, `rebase_merge_queue_discipline`, `reconcile_bot_handles_main_literals`, `reconcile_job_cannot_derive_census`, `reject_a_gated_run_pinned_to_a_stale_sha`, `rollback_partial_fires_mixed_fleet`, `ruff_full_dir_set`, `saturated_alarm_hides_its_own_findings`, `shallow_clone_git_gates`, `single_file_deploy_strips_siblings`, `site_deploy_superseded_skip`, `site_js_test_and_build_pairs`, `squash_merge_drops_unpushed_commits`, `stale_behind_a_fresh_timestamp`, `stale_data_row_reverts_code_deploy`, `structural_set_is_not_a_ci_proxy`, `test_importing_aws_cdk_reds_ci`, `test_layer_dep_import_collection_red`, `verify_agent_findings`, `verify_bundle_boot_is_the_real_gate`, `verify_sources_from_registry`, `worktree_agent_path_reuse`, `worktree_case_insensitive_pollution`

**`new` (32):** `a_mutation_must_actually_mutate`, `a_pre_declared_red_is_not_a_read_lane`, `absent_check_invisible_to_fail_filter`, `adr099_score_inverts_priority`, `agent_rubrics_never_outrank_owner_labels`, `an_epic_can_pass_every_box_and_fail_its_outcome`, `autoclose_keyword_ignores_negation`, `backlog_drain_epic_tails`, `cloudwatch_query_form_errors_read_as_defects`, `delete_branch_closes_stacked_pr`, `extraction_never_baseline_raise`, `git_add_a_sweeps_concurrent_agent_edits`, `git_checkout_path_destroys_your_own_edit`, `issue_closed_against_unmerged_pr`, `judge_flake_ground_truth`, `measure_before_accepting_a_defect_rate`, `measure_before_believing_the_premise`, `merge_verdict_separate_command`, `merged_is_not_deployed`, `negated_closing_keyword_still_closes`, `never_diagnose_from_a_truncated_log_line`, `partial_acceptance_is_not_a_close`, `pytest_pipe_exit_code`, `read_for_a_later_adr_amendment`, `removing_a_confound_reveals_the_second_defect`, `scratchpad_is_shared_across_concurrent_agents`, `shared_scratchpad_clobbers_pr_bodies`, `ship_the_mechanism_print_the_residual`, `subagent_pr_bodies_no_record_identifiers`, `task_notification_exit_codes_lie`, `the_rubric_can_be_the_finding_generator`, `watchers_exit_on_terminal_not_green`

**`residual` (35):** `a_check_after_truncation_launders_the_defect`, `a_check_that_measures_nothing_returns_clean`, `a_correct_rule_with_a_narrow_denominator`, `a_measurement_that_aborts_reports_zero`, `a_rollback_whose_scope_cannot_reach_its_trigger`, `a_transform_can_be_correct_and_unreachable`, `a_vacuous_negative_control`, `a_verified_stamp_is_a_human_claim`, `api_schema_capture_wholesale`, `arming_a_semantic_gate_needs_a_baseline`, `baselining_needs_severity_free_write`, `content_policy_allowlist_follows_path`, `correction_invisible_by_render_filter`, `css_token_guard_vs_visual_qa`, `data_driven_dark_states`, `deploy_coach_intelligence_excludes_the_worker`, `discovery_bias_loose_but_gate_the_verb`, `docs_current_truth_only`, `extract_the_right_real_source`, `fail_closed_paths_need_a_live_proof`, `frozen_artifact_supersede_annotation`, `gate_prose_is_a_parsed_interface`, `harness_must_track_its_call_site`, `iam_parity_codified_broken_state`, `import_time_frozen_globals_test_trap`, `orphan_gate_inline_writer_literal`, `package_import_breaks_sys_modules_stubs`, `partition_scoped_sweep_rots_when_partition_gains_classes`, `reexport_is_not_a_patch_point`, `s3_first_config_invalidates_local_measurement`, `strptime_is_the_inverse_of_a_clock`, `suppressor_rules_must_be_structural`, `svg_type_floor_truth`, `time_dependent_gate_outside_its_window`, `volatile_timestamp_in_asserted_blob`

**`narrative` (10):** `audit_mislabels_loadbearing_dirs`, `cdk_apigwv2_stage_route_settings`, `cfn_secret_dynamic_ref`, `ci_artifact_quota_rollback`, `cloudwatch_alarm_week_cap`, `conflict_resolution_ate_a_return`, `grounder_evidence_excludes_current_turn`, `io_threshold_tall_sections`, `magicmock_pagination_oom_runner_shutdown`, `token_overlap_misses_structural_cloning`

**`superseded` (2):** `agent_commit_directory_is_not_a_name`, `pr_checks_lack_mypy_gate`

---

**Verified:** 2026-08-27 (#2848 - corpus audited at 154 entries; sections 1-4 are the
rules that had no repo home; section 6 is the measured residual, not a claim of
completeness)
