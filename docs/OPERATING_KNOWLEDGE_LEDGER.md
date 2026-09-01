# OPERATING KNOWLEDGE LEDGER — where every memory-corpus rule lives

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-31

The operator's Claude Code memory directory (`docs/CONTINUITY.md` §4) is the one asset in
this system that lives on a single laptop. #2848's thesis is that a fresh session with **no**
personal memory must be able to operate the platform from repo artifacts alone — so every
durable **rule** in that directory needs a home in this repo, and the narrative that does
not need to be here needs to be *named* as not being here, rather than silently assumed.

This page is that registry. One row per file in the memory index: its type (from the file's
own prefix), its repo home (the page and section, or the file, that states the rule), and a
status. `docs/OPERATING_DISCIPLINE.md` Appendix A is the frozen 2026-08-27 audit of the
review-discipline half; this page supersedes it as the maintained answer and covers the
whole index.

**How it is kept true.** `tests/test_operating_knowledge_ledger_2848.py` holds this page
consistent with its own committed snapshot below: every snapshot file has exactly one row,
every `homed-here` / `already-homed` / `superseded` row cites a path git tracks, every
`narrative` / `off-repo` row states its reason, and the coverage counts match the rows. It
**cannot see the live memory directory** — that is outside git by design — so the live half
is a `/wrap` step (c) reflex: `python3 scripts/check_operating_knowledge_ledger.py --live`
lists any memory file with no row here. A row is added in the same wrap that writes the
memory file, or the guard has a hole exactly the width of the newest lesson.

**What a home is.** A repo page or file that states the rule in its own voice — never a
paste of the memory file, never the incident narrative in full, never personal detail. The
memory file keeps the narrative (the night it was learned, the numbers); the home keeps the
rule and the one measurement that makes it binding. Where a row cites a section ("§7") the
section heading is the anchor; where it cites a code file, the file's header docstring is.

## Status vocabulary

| status | meaning |
|---|---|
| `homed-here` | The rule had no repo home before the 2026-08-30 pass and was written into the cited home by it (#2848 PR 3) |
| `already-homed` | The rule was already stated in the cited home (by an earlier PR, a skill, or the code's own header) |
| `superseded` | The finding no longer holds — the machinery it describes was fixed or replaced; the cited file records the fix |
| `narrative` | Incident detail, a one-off measurement, or a session/program record — not a rule; stays in memory by design |
| `off-repo` | The subject deliberately lives outside this public repo (security-incident detail, an off-repo plan, tooling that is not in this tree) |
| `user` | Who the owner is — out of scope for this ledger, stays in memory |
| `index` | The memory index itself, or its annex |

## Coverage — 2026-09-01 (Session Q: +1 reference +1 project, snapshot + counters updated in the same edit as the rows). Prior: 2026-09-01 (Session P: +2 reference +1 project; regenerated from the rows after CI caught the snapshot/coverage drift). Prior: 2026-08-31 (Session O: +1 reference; reconcile: +1 reference +1 project the N/fin-diligence wraps added as rows but not here; Session M: +3 reference)

<!-- LEDGER-COVERAGE:START -->
**Files in the memory index snapshot: 389** — feedback 22 · reference 216 · security 1 · project 147 · user 1 · index 2

**Rule-class files (feedback + reference + security): 239** — homed-here 58 · already-homed 161 · superseded 7 · narrative 11 · off-repo 2

**Program/session files (project): 147** — already-homed 14 · superseded 1 · narrative 129 · off-repo 2 · index 1

**Out of scope: user 1 · index 2**
<!-- LEDGER-COVERAGE:END -->

Of Appendix A's 35 `residual` entries: 26 were placed by this pass, 8 were already stated somewhere the
08-27 audit's phrase probe did not reach (the `/prove-it`, `/incident` and `/new-machinery` skills
of #3245 — merged the day after the audit — ADR-146's own text, and that page's own §4.2), and 1
is superseded (the severity-free write shipped in #2981).

## Snapshot of the memory index — 2026-09-01 (Session P: +4 files — 2 reference, 2 project incl. Session O's own, which was added as a row but never to this block). Prior: 2026-08-31 (Session O: +1 reference; earlier reconcile +2)

The file list this ledger is checked against. Regenerate it by listing the memory
directory (`ls <memory-dir>/*.md`) and re-run the guard; a file added to memory and not to
this block is exactly what the `--live` check reports.

<!-- LEDGER-SNAPSHOT:START -->
```
INDEX_review_discipline.md
MEMORY.md
feedback_agent_rubrics_never_outrank_owner_labels.md
feedback_clarify_conversationally.md
feedback_concurrent_session_worktree.md
feedback_default_keep_going.md
feedback_deploy_s3.md
feedback_deploy_two_prefixes.md
feedback_garmin_rate_limit.md
feedback_hae_water_dedup.md
feedback_heartbeat_progress.md
feedback_ideation_include_offsite_channels.md
feedback_partial_acceptance_is_not_a_close.md
feedback_prod_deploy_authorization.md
feedback_rest_and_params_multifactor.md
feedback_review_ritual_model_identity.md
feedback_sensitive_content.md
feedback_site_pacific_time.md
feedback_squash_merge_drops_unpushed_commits.md
feedback_subagent_pr_bodies_no_record_identifiers.md
feedback_usage_headroom_before_fanout.md
feedback_verify_agent_findings.md
feedback_verify_sources_from_registry.md
feedback_watchers_exit_on_terminal_not_green.md
project_adr046_generated_prefix.md
project_agrade_d2_drain_2026_08_24.md
project_agrade_program_2026_08_23.md
project_alarm_board_2026_08_15.md
project_arch781_layer_retirement.md
project_backlog_blitz_2026_07_12.md
project_backlog_drain_2026_08_19.md
project_backlog_paydown_2026_07_08.md
project_backlog_pm_2026_07_27.md
project_backlog_sweep_2026_07_11b.md
project_bodyscan2_wave_2026_08_16.md
project_bug_bash_2026_07_06.md
project_bug_bash_2026_08_14.md
project_bugbash_queue_2026_08_14.md
project_build_fingerprint.md
project_cc_series.md
project_character_math_v2.md
project_character_sheet_2026_07.md
project_charter_paydown_cycle14_2026_08_17.md
project_chat_journey_2026_07_18.md
project_cloudfront_invalidation_path.md
project_coach_feedback_loops_2026_07_22.md
project_coach_opinion_engine.md
project_coach_portraits_program.md
project_coach_sim_harness_2026_08_10.md
project_coaching_brilliance_2026_08_10.md
project_coaching_redesign.md
project_coaching_team_v2_2026_08_10.md
project_coherence_program.md
project_complexity_paydown_2026_07_08.md
project_conformance_guard_2026_08_17.md
project_craft_review_2026_07_21.md
project_cycle5_reset_2026_07_10.md
project_cycle6_reset_2026_07_13.md
project_data_source_health_review.md
project_decision_sprint_2026_07_09.md
project_deep_context_2026_07_19.md
project_deploy_plane_cluster_2026_08_20.md
project_deploy_plane_unblock_2026_08_22.md
project_deploy_unblock_2026_08_18.md
project_design_pipeline_2026_07_18.md
project_doc_drift_guardrails_2026_07_13.md
project_elite_review_2026_08_16.md
project_elite_uplevel_2026_07.md
project_epic_1890_live_honesty.md
project_epic_closeout_2026_07_12.md
project_epic_tails_drain_2026_08_21.md
project_fable_graded_the_week_2026_08_16.md
project_fable_later_paydown.md
project_fable_next_batch.md
project_fable_paydown2_2026_07_11.md
project_fable_r21_batch.md
project_fable_triage_2026_08_20.md
project_fable_week_lane_a_2026_08_22.md
project_fable_week_session2_2026_08_23.md
project_financial_diligence_2026_08_31.md
project_frontier_review_2026_07_18.md
project_fullreview_panel.md
project_gate_audit_2026_08_13.md
project_gate_owner_unblock_2026_08_02.md
project_gates_paid_for_themselves_2026_08_09.md
project_genesis_night_close_2026_07_12.md
project_golden_brief_eval_742.md
project_green_main_prereg_repo_private_2026_07_13.md
project_home_overflow_followup.md
project_honesty_pair_adr104.md
project_instruments_were_the_defect_2026_08_15.md
project_intelligence_roadmap_2026_07.md
project_launch_dates.md
project_machinery_first_2026_08_22.md
project_max_opus_paydown_2026_08_22.md
project_mobile_pwa.md
project_mobile_uplevel_2026_07.md
project_monday_reset.md
project_next_paydown_2026_07_08.md
project_nonfable_drain_2026_08_11.md
project_nutrition_24h_lag.md
project_nutrition_privacy_flags.md
project_observability_slice_2026_08_18.md
project_opus_batch_2026_07_05.md
project_opus_batch_2026_07_06.md
project_overnight_burn_2026_08_09.md
project_overnight_honesty_arc_2026_08_16.md
project_p1_rate_limit_identity_2026_08_21.md
project_panel_reset_selection.md
project_panelcast_quality_bar.md
project_paydown_2026_07_07.md
project_personal_baselines_layer_outage.md
project_phase_taxonomy.md
project_phenoage_privacy.md
project_plan_then_execute_2026_08_22.md
project_platform_audit_2026.md
project_podcasts_google_tts.md
project_pr_render_gate_408.md
project_pre13_deferred.md
project_presence_quiet_stretch.md
project_privacy_guard_sweep_2026_08_08.md
project_qa_strategy_2026_07_18.md
project_queue_paydown_2026_08_10.md
project_r21_batch1_2_2026_07_06.md
project_r21_prediction_integrity.md
project_r22_build_paydown_2026_07_06.md
project_r22_consultancy_review.md
project_reader_engagement_loop.md
project_reading_mind_pillar.md
project_reconcile_and_branches_2026_07_05.md
project_repo_privacy_remediation.md
project_repo_visibility.md
project_reset_purges_site_config.md
project_review_backlog_program.md
project_review_remediation_2026_07_12.md
project_sdlc_review_2026_07_18.md
project_september_base_2026_08_18.md
project_serial_and_self_sustaining.md
project_session_a_2026_08_25.md
project_session_b_2026_08_25.md
project_session_c_2026_08_26.md
project_session_d_2026_08_26.md
project_session_e_2026_08_27.md
project_session_f_2026_08_27.md
project_session_g_2026_08_27.md
project_session_o_launch_2026_08_31.md
project_session_p_2026_09_01.md
project_session_q_2026_09_01.md
project_shipped_archive.md
project_silent_failure_drain_2026_08_15.md
project_social_membrane_2026_07_21.md
project_sonnet_batch_session17.md
project_stolen_laptop_resilience_2026_07_11.md
project_sweep_2026_07_11.md
project_system_model_2026_08_17.md
project_telegram_coach_chat_2026_08_09.md
project_throughput_session_2026_08_08.md
project_traffic_digest_measurement.md
project_training_truth_412.md
project_truth_audit.md
project_unblock_six_2026_07_10.md
project_uplevel_driver_and_board.md
project_uplevel_roadmap_2026_07.md
project_v5_coherence_redesign.md
project_visual_identity_system.md
project_visual_uplevel_2026_07.md
project_vlog_studio_2026_07_26.md
project_voice_studio_2026_07_19.md
project_whoop_reauth.md
project_wiki_program_2026_07_10.md
project_wrong_day_and_wrong_gauge_2026_08_18.md
reference_a_check_after_truncation_launders_the_defect.md
reference_a_check_that_measures_nothing_returns_clean.md
reference_a_ci_gate_that_cannot_fail.md
reference_a_citation_string_is_not_an_owner.md
reference_a_correct_rule_with_a_narrow_denominator.md
reference_a_dependency_missing_makes_a_gate_dark.md
reference_a_derived_artifact_needs_its_lane.md
reference_a_filed_issues_mechanism_is_a_hypothesis.md
reference_a_measurement_that_aborts_reports_zero.md
reference_a_mutation_must_actually_mutate.md
reference_a_pre_declared_red_is_not_a_read_lane.md
reference_a_client_cap_below_the_callee_p50.md
reference_a_proof_ledger_needs_its_own_freshness_guard.md
reference_a_rollback_whose_scope_cannot_reach_its_trigger.md
reference_a_sweep_one_import_away.md
reference_a_transform_can_be_correct_and_unreachable.md
reference_a_vacuous_negative_control.md
reference_a_verified_stamp_is_a_human_claim.md
reference_absence_read_as_success.md
reference_absent_check_invisible_to_fail_filter.md
reference_accuracy_gate_signed_metrics.md
reference_adr099_score_inverts_priority.md
reference_agent_commit_and_the_throughput_fix.md
reference_agent_commit_directory_arg_destroys.md
reference_agent_commit_directory_is_not_a_name.md
reference_ai_gate_blocking_deploys.md
reference_an_epic_can_pass_every_box_and_fail_its_outcome.md
reference_api_before_frontend_autodeploy_race.md
reference_api_schema_capture_wholesale.md
reference_arming_a_semantic_gate_needs_a_baseline.md
reference_asset_hasher_comment_paths.md
reference_asset_hashing_full_graph.md
reference_ast_walk_annassign_blindness.md
reference_audit_mislabels_loadbearing_dirs.md
reference_autoclose_keyword_ignores_negation.md
reference_averagejoematt_dns_and_mail.md
reference_backlog_drain_epic_tails.md
reference_baselining_needs_severity_free_write.md
reference_black_corrupts_json.md
reference_black_pin_path_skew.md
reference_budget_ceiling_fractional_bands.md
reference_budget_tier_band_availability.md
reference_cdk_apigwv2_stage_route_settings.md
reference_cdk_asset_staging_glitch.md
reference_cdk_deploy_classifier_and_approval.md
reference_cdk_refactor_stack_split.md
reference_cdk_synth_python_resolution.md
reference_cfn_secret_dynamic_ref.md
reference_character_config_generated_page.md
reference_check_existing_page_before_building.md
reference_check_the_restart_archive_before_regenerating.md
reference_ci_artifact_quota_rollback.md
reference_ci_deploy_race_manual_overwrite.md
reference_ci_extracted_script_needs_checkout.md
reference_ci_masking_and_creds.md
reference_cicd_red_and_archive_moves.md
reference_cloudfront_404_cache_smoke.md
reference_cloudfront_forwards_client_xff_unchanged.md
reference_cloudwatch_alarm_week_cap.md
reference_cloudwatch_query_form_errors_read_as_defects.md
reference_collect_only_lane_hides_infunction_imports.md
reference_concurrent_prs_union_breach_size_gate.md
reference_conflict_resolution_ate_a_return.md
reference_conflicting_pr_mints_no_checks.md
reference_content_policy_allowlist_follows_path.md
reference_correction_invisible_by_render_filter.md
reference_cost_tracker_sync_owned_rows.md
reference_coverage_tranche_x_privacy_gate_union_breach.md
reference_css_token_guard_vs_visual_qa.md
reference_dark_flag_waiver_reason_rots_when_reach_changes.md
reference_data_driven_dark_states.md
reference_delete_branch_closes_stacked_pr.md
reference_deploy_api_before_frontend.md
reference_deploy_coach_intelligence_excludes_the_worker.md
reference_deploy_from_main_not_worktree_branch.md
reference_deploy_gate_approval_and_recovery.md
reference_deploy_timestamp_is_not_the_commit.md
reference_discovery_bias_loose_but_gate_the_verb.md
reference_doc_index_strict_ci_only.md
reference_doc_sync_literal_treadmill.md
reference_docs_current_truth_only.md
reference_docs_only_commit_reds_every_pr_not_main.md
reference_docsync_apply_writes_inside_conflict_blocks.md
reference_docsync_literal_cross_pr_drift.md
reference_docsync_stamp_is_utc.md
reference_driver_commits_strip_hook_literals.md
reference_enumerate_all_leases_after_every_merge.md
reference_epic_checklists_stale_by_construction.md
reference_event_delay_vs_swallow_and_accumulated_deploys.md
reference_extract_the_right_real_source.md
reference_extraction_never_baseline_raise.md
reference_fail_closed_paths_need_a_live_proof.md
reference_fail_closed_scoped_to_artifact_not_lane.md
reference_ffmpeg_slim_brew_and_ass_units.md
reference_fixture_must_be_the_wire.md
reference_freshness_window_writer_cadence.md
reference_frozen_artifact_supersede_annotation.md
reference_future_genesis_breaks_rules_not_just_tests.md
reference_gate_prose_is_a_parsed_interface.md
reference_gate_registration_before_deploy.md
reference_gated_run_is_a_deploy_group_lease.md
reference_genesis_week_present_none.md
reference_gh_merge_takes_branch_not_integration_tree.md
reference_gh_merge_worktree_branch_switch.md
reference_gh_pr_checks_empty_is_not_green.md
reference_git_add_a_sweeps_concurrent_agent_edits.md
reference_git_checkout_path_destroys_your_own_edit.md
reference_git_stash_shared_across_worktrees.md
reference_github_env_protection_private_flip.md
reference_github_event_swallow_recovery.md
reference_github_token_push_never_dispatches.md
reference_gitleaks_push_only.md
reference_golden_tests_wallclock.md
reference_google_tts_per_sentence_limit.md
reference_grounder_evidence_excludes_current_turn.md
reference_guard_the_set_not_the_instance.md
reference_harness_must_track_its_call_site.md
reference_hazard_gate_before_model.md
reference_iam_parity_codified_broken_state.md
reference_import_time_frozen_globals_test_trap.md
reference_inrepo_worktree_pollutes_scanners.md
reference_io_threshold_tall_sections.md
reference_issue_closed_against_unmerged_pr.md
reference_job_timeout_renders_as_cancelled.md
reference_judge_flake_ground_truth.md
reference_judge_reproducing_false_positive_shapes.md
reference_lambda_perf_measure_at_origin.md
reference_lane_branch_must_not_carry_counter_file.md
reference_launchd_tcc_documents.md
reference_layer_shipped_deps_dependabot_blind.md
reference_lease_steward_must_outlive_the_tip.md
reference_llm_json_maxtokens_truncation.md
reference_local_axe_blind_to_color_mix_contrast.md
reference_local_black_vs_pinned_black.md
reference_local_render_qa.md
reference_magicmock_pagination_oom_runner_shutdown.md
reference_mcp_bridge_key_rotation_detach.md
reference_mcp_bundle_needs_reading.md
reference_measure_before_accepting_a_defect_rate.md
reference_measure_before_believing_the_premise.md
reference_merge_queue_no_blind_add.md
reference_merge_verdict_separate_command.md
reference_merged_is_not_deployed.md
reference_module_relative_config_paths_must_not_encode_depth.md
reference_negated_closing_keyword_still_closes.md
reference_never_diagnose_from_a_truncated_log_line.md
reference_new_site_page_registries.md
reference_no_tool_attribution_trailers.md
reference_node_check_lazy_parse.md
reference_og_card_fonts_tofu.md
reference_orphan_gate_inline_writer_literal.md
reference_package_import_breaks_sys_modules_stubs.md
reference_partition_scoped_sweep_rots_when_partition_gains_classes.md
reference_platform_facts_maintained_literal.md
reference_platform_logger_capture_and_dark_module_loggers.md
reference_pr_checks_lack_mypy_gate.md
reference_premerge_registration_moves_the_census.md
reference_prereg_dry_run_review.md
reference_prompt_structural_guarantees.md
reference_push_ci_silent_death.md
reference_pytest_pipe_exit_code.md
reference_qa_smoke_alarm_window_load_bearing.md
reference_r8st6_iam_review_gate.md
reference_rate_limit_must_charge_the_fanout.md
reference_read_for_a_later_adr_amendment.md
reference_read_the_deploy_critical_lane_by_name.md
reference_rebase_continue_phantom_wedge.md
reference_rebase_merge_queue_discipline.md
reference_reconcile_bot_handles_main_literals.md
reference_reconcile_job_cannot_derive_census.md
reference_reexport_is_not_a_patch_point.md
reference_regen_invoke_email_lambda_trap.md
reference_reject_a_gated_run_pinned_to_a_stale_sha.md
reference_removing_a_confound_reveals_the_second_defect.md
reference_reordering_sync_steps_changes_what_each_step_owns.md
reference_rerun_reuses_the_original_merge_commit.md
reference_reset_pipeline_owned_manifest_clobber.md
reference_rollback_partial_fires_mixed_fleet.md
reference_ruff_full_dir_set.md
reference_s3_first_config_invalidates_local_measurement.md
reference_saturated_alarm_hides_its_own_findings.md
reference_scratchpad_is_shared_across_concurrent_agents.md
reference_security_docs_never_via_hand_twin.md
reference_shallow_clone_git_gates.md
reference_shared_scratchpad_clobbers_pr_bodies.md
reference_ship_the_mechanism_print_the_residual.md
reference_single_file_deploy_strips_siblings.md
reference_site_api_layer_manual_attach.md
reference_site_deploy_superseded_skip.md
reference_site_js_test_and_build_pairs.md
reference_site_rollback_rerun_full_not_failed.md
reference_site_smoke_transient_timeout_rollback.md
reference_small_gap_reset_false_positive.md
reference_smoke_invalidation_race.md
reference_stack_census_prs_on_a_nonstrict_ruleset.md
reference_stale_behind_a_fresh_timestamp.md
reference_stale_data_row_reverts_code_deploy.md
reference_strptime_is_the_inverse_of_a_clock.md
reference_structural_set_is_not_a_ci_proxy.md
reference_suppressor_rules_must_be_structural.md
reference_svg_text_outline_and_theme_bake.md
reference_svg_type_floor_truth.md
reference_swallowed_push_no_runs_at_all.md
reference_task_notification_exit_codes_lie.md
reference_test_importing_aws_cdk_reds_ci.md
reference_test_layer_dep_import_collection_red.md
reference_the_rubric_can_be_the_finding_generator.md
reference_time_dependent_gate_outside_its_window.md
reference_token_overlap_misses_structural_cloning.md
reference_two_module_size_guards.md
reference_verify_bundle_boot_is_the_real_gate.md
reference_volatile_timestamp_in_asserted_blob.md
reference_withings_transient_refresh.md
reference_workflow_step_deps_and_first_apply.md
reference_worktree_agent_path_reuse.md
reference_worktree_case_insensitive_pollution.md
security_r22_mcp_token_exposure.md
user_who_is_matthew.md
```
<!-- LEDGER-SNAPSHOT:END -->

## Rule-class entries — `feedback_*`, `reference_*`, `security_*`

| memory file | type | home | status |
|---|---|---|---|
| `feedback_agent_rubrics_never_outrank_owner_labels.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §2.9 | already-homed |
| `feedback_clarify_conversationally.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §3a.2 | homed-here |
| `feedback_concurrent_session_worktree.md` | feedback | `.claude/agents/worktree-implementer.md` 0b/1 + `docs/CONVENTIONS.md` §7 + `docs/SITE_UPLEVEL_PLAYBOOK.md` § gotchas | already-homed |
| `feedback_default_keep_going.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §3a.3 + §5.2 | homed-here |
| `feedback_deploy_s3.md` | feedback | `CLAUDE.md` (Public Website: deploy) + `docs/SITE_UPLEVEL_PLAYBOOK.md` § deploy surface | already-homed |
| `feedback_deploy_two_prefixes.md` | feedback | superseded by the THREE-prefix rule — `docs/CONVENTIONS.md` §7 (#2019) | superseded |
| `feedback_garmin_rate_limit.md` | feedback | `docs/DECISIONS.md` ADR-074 + `docs/ACCOUNTS.md` | already-homed |
| `feedback_hae_water_dedup.md` | feedback | `docs/IDEMPOTENCY.md` + `docs/SCHEMA.md` (`_rd_water_intake_ml`) | already-homed |
| `feedback_heartbeat_progress.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §3a.1 | homed-here |
| `feedback_ideation_include_offsite_channels.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §3a.6 | homed-here |
| `feedback_partial_acceptance_is_not_a_close.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §2.1 + `.claude/skills/land/SKILL.md` §5 | already-homed |
| `feedback_prod_deploy_authorization.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §5 (placed by #3264) | already-homed |
| `feedback_rest_and_params_multifactor.md` | feedback | `docs/DECISIONS.md` (ADR-066/068: rest is a multi-factor coach judgment, never auto-set) | already-homed |
| `feedback_review_ritual_model_identity.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §3a.5 | homed-here |
| `feedback_sensitive_content.md` | feedback | the mechanism: `docs/DATA_GOVERNANCE.md` + the content filter in `deploy/sync_site_to_s3.sh`; the vocabulary itself is OFF-repo by design (#2503) | already-homed |
| `feedback_site_pacific_time.md` | feedback | `docs/CONVENTIONS.md` §7 (DATE# keys and reader-facing dates are Pacific) + `docs/IDEMPOTENCY.md` | homed-here |
| `feedback_squash_merge_drops_unpushed_commits.md` | feedback | `docs/CONVENTIONS.md` §3 | already-homed |
| `feedback_subagent_pr_bodies_no_record_identifiers.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §2.11 + `.claude/agents/issue-filer.md` | already-homed |
| `feedback_usage_headroom_before_fanout.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §3a.4 | homed-here |
| `feedback_verify_agent_findings.md` | feedback | `.claude/agents/finding-verifier.md` + `docs/OPERATING_DISCIPLINE.md` §1.1 | already-homed |
| `feedback_verify_sources_from_registry.md` | feedback | `CLAUDE.md` (read the registry facets) + `lambdas/ingestion/source_registry.py` | already-homed |
| `feedback_watchers_exit_on_terminal_not_green.md` | feedback | `docs/OPERATING_DISCIPLINE.md` §3.5 | already-homed |
| `reference_a_check_after_truncation_launders_the_defect.md` | reference | `.claude/skills/prove-it/SKILL.md` Q4 (the full text, not a transform that removed the evidence) | homed-here |
| `reference_a_check_that_measures_nothing_returns_clean.md` | reference | `.claude/skills/prove-it/SKILL.md` Q3 (print the denominator) + `.claude/agents/finding-verifier.md` 7 | already-homed |
| `reference_a_ci_gate_that_cannot_fail.md` | reference | `.claude/skills/prove-it/SKILL.md` § dark (a ⚠ and exit 0) + `.claude/skills/land/SKILL.md` §1 + `docs/OPERATING_DISCIPLINE.md` §3.4 | already-homed |
| `reference_a_citation_string_is_not_an_owner.md` | reference | `docs/CONVENTIONS.md` §9 (alarm-citation gate, `scripts/check_alarm_citations.py`) | already-homed |
| `reference_a_correct_rule_with_a_narrow_denominator.md` | reference | `.claude/skills/prove-it/SKILL.md` Q3 (is the denominator the live surface?) | homed-here |
| `reference_a_dependency_missing_makes_a_gate_dark.md` | reference | `.claude/skills/prove-it/SKILL.md` § what could make it dark; `scripts/skill_lint.py` header | already-homed |
| `reference_a_derived_artifact_needs_its_lane.md` | reference | `.claude/skills/new-machinery/SKILL.md` § traps | already-homed |
| `reference_a_measurement_that_aborts_reports_zero.md` | reference | `.claude/skills/prove-it/SKILL.md` Q3 + `.claude/agents/finding-verifier.md` 7 + `scripts/mypy_disable_cost.py` header | already-homed |
| `reference_a_mutation_must_actually_mutate.md` | reference | `.claude/skills/new-machinery/SKILL.md` Q2 (mutation-proven both directions) + `docs/CONVENTIONS.md` §9a | already-homed |
| `reference_a_pre_declared_red_is_not_a_read_lane.md` | reference | `docs/OPERATING_DISCIPLINE.md` §1.8 | already-homed |
| `reference_a_proof_ledger_needs_its_own_freshness_guard.md` | reference | `docs/CONVENTIONS.md` §9 + `tests/test_gate_census_2578.py` | already-homed |
| `reference_a_rollback_whose_scope_cannot_reach_its_trigger.md` | reference | `docs/CONVENTIONS.md` §4b (what the site auto-rollback can and cannot reach) + `docs/OPERATING_DISCIPLINE.md` §5.6 | homed-here |
| `reference_a_sweep_one_import_away.md` | reference | `docs/CONVENTIONS.md` §4a1 (#2924) + `tests/premerge_derivation.py` | already-homed |
| `reference_a_transform_can_be_correct_and_unreachable.md` | reference | `.claude/skills/new-machinery/SKILL.md` § traps (set equality both directions) + `.claude/skills/land/SKILL.md` §4 | homed-here |
| `reference_a_vacuous_negative_control.md` | reference | `.claude/skills/prove-it/SKILL.md` Q1 + `.claude/agents/finding-verifier.md` 7 | already-homed |
| `reference_a_client_cap_below_the_callee_p50.md` | reference | `lambdas/web/board_quality_gate.py` docstring (the measurement + derivation command) + `docs/DECISIONS.md` ADR-108 amendment 2026-09-01 | already-homed |
| `reference_a_verified_stamp_is_a_human_claim.md` | reference | `docs/OPERATING_DISCIPLINE.md` §4.2 + `.claude/agents/finding-verifier.md` (standing cautions) | already-homed |
| `reference_absence_read_as_success.md` | reference | `docs/CHARTER.md` (the derivation-guard primitive — derive, never trust a local copy) + the instance guards `tests/test_backup_agent_path_contract.py`, `scripts/check_main_green.py` HEAD-COVERAGE, #3378 | already-homed |
| `reference_absent_check_invisible_to_fail_filter.md` | reference | `docs/OPERATING_DISCIPLINE.md` §3.7 | already-homed |
| `reference_accuracy_gate_signed_metrics.md` | reference | `tests/accuracy_audit.py` (signed `progress_pct`) | already-homed |
| `reference_adr099_score_inverts_priority.md` | reference | `docs/OPERATING_DISCIPLINE.md` §2.7 | already-homed |
| `reference_agent_commit_and_the_throughput_fix.md` | reference | `.claude/agents/worktree-implementer.md` non-negotiables + `deploy/agent_commit.sh` header + `docs/CONVENTIONS.md` §12b | already-homed |
| `reference_agent_commit_directory_arg_destroys.md` | reference | fixed by #2897 — `docs/CONVENTIONS.md` §12b | superseded |
| `reference_agent_commit_directory_is_not_a_name.md` | reference | fixed by #2897 — `docs/CONVENTIONS.md` §12b (a directory now COVERS its files) | superseded |
| `reference_ai_gate_blocking_deploys.md` | reference | resolved by #1921 — `docs/DECISIONS.md` ADR-125 amendment (content findings no longer revert code) | superseded |
| `reference_an_epic_can_pass_every_box_and_fail_its_outcome.md` | reference | `docs/OPERATING_DISCIPLINE.md` §2.2 | already-homed |
| `reference_api_before_frontend_autodeploy_race.md` | reference | `docs/CONVENTIONS.md` §9 (`scripts/check_api_before_frontend.py`, #2831) | already-homed |
| `reference_api_schema_capture_wholesale.md` | reference | `docs/TESTING.md` § traps (API schema baselines are captured wholesale) | homed-here |
| `reference_arming_a_semantic_gate_needs_a_baseline.md` | reference | `.claude/skills/new-machinery/SKILL.md` § traps | already-homed |
| `reference_asset_hasher_comment_paths.md` | reference | `docs/SITE_UPLEVEL_PLAYBOOK.md` § gotchas (asset-hash bullet: comments count as edges) | homed-here |
| `reference_asset_hashing_full_graph.md` | reference | `docs/SITE_UPLEVEL_PLAYBOOK.md` § gotchas | already-homed |
| `reference_ast_walk_annassign_blindness.md` | reference | `tests/test_wallclock_fixture_bombs_2376.py`, `tests/test_site_api_namespace_guard_3002.py` (AnnAssign walked) | already-homed |
| `reference_audit_mislabels_loadbearing_dirs.md` | reference | — narrative: one audit's mislabelling; the rule it implies is CHARTER's registry primitive | narrative |
| `reference_autoclose_keyword_ignores_negation.md` | reference | `docs/OPERATING_DISCIPLINE.md` §2.5 | already-homed |
| `reference_averagejoematt_dns_and_mail.md` | reference | `docs/INFRASTRUCTURE.md` (registrar vs hosted zone) + `docs/ACCOUNTS.md` | already-homed |
| `reference_backlog_drain_epic_tails.md` | reference | `docs/OPERATING_DISCIPLINE.md` §2.8 | already-homed |
| `reference_baselining_needs_severity_free_write.md` | reference | fixed by #2981 — `tests/truth_baseline_audit.py` (the write path is severity-free; gating stays high-only at read time) | superseded |
| `reference_black_corrupts_json.md` | reference | `docs/CONVENTIONS.md` §7 | already-homed |
| `reference_black_pin_path_skew.md` | reference | `docs/CONVENTIONS.md` §9 (pre-commit: the format gate resolves the pin) + `scripts/install_hooks.sh` | already-homed |
| `reference_budget_ceiling_fractional_bands.md` | reference | `docs/COST_TRACKER.md` § budget guardrails + `docs/DECISIONS.md` ADR-133 | already-homed |
| `reference_budget_tier_band_availability.md` | reference | `docs/DECISIONS.md` ADR-125 amendment (tier ≥1 is the default state) + `docs/COST_TRACKER.md` § tier residence | already-homed |
| `reference_cdk_apigwv2_stage_route_settings.md` | reference | — narrative: a one-off CDK construct workaround, dated | narrative |
| `reference_cdk_asset_staging_glitch.md` | reference | `docs/CONVENTIONS.md` §5 | already-homed |
| `reference_cdk_deploy_classifier_and_approval.md` | reference | `docs/CONVENTIONS.md` §4d.2 + `deploy/cdk_deploy.sh` | already-homed |
| `reference_cdk_refactor_stack_split.md` | reference | `docs/CONVENTIONS.md` §6 (moving a function between stacks) | homed-here |
| `reference_cdk_synth_python_resolution.md` | reference | `deploy/cdk_deploy.sh` (pins its own venv for synth) | already-homed |
| `reference_cfn_secret_dynamic_ref.md` | reference | — narrative: a one-off CloudFormation detail (region-local secret refs) | narrative |
| `reference_character_config_generated_page.md` | reference | `docs/SITE_AUTHORING.md` §3 (generated pages) + `scripts/v4_build_evidence.py` | already-homed |
| `reference_check_existing_page_before_building.md` | reference | `.claude/skills/design-implement/SKILL.md` (check the URL first) + `tests/qa_manifest.py` | already-homed |
| `reference_check_the_restart_archive_before_regenerating.md` | reference | `docs/RUNBOOK.md` § Restart Pipeline (two reset reflexes: `archived_to`) | homed-here |
| `reference_ci_artifact_quota_rollback.md` | reference | — narrative: a dated GitHub artifact-quota incident; the rollback rule is CONVENTIONS §4b | narrative |
| `reference_ci_deploy_race_manual_overwrite.md` | reference | `docs/CONVENTIONS.md` §6 (live-code drift) | already-homed |
| `reference_ci_extracted_script_needs_checkout.md` | reference | `docs/CONVENTIONS.md` §4 (gate ordering) + `.github/workflows/ci-lint.yml` | already-homed |
| `reference_ci_masking_and_creds.md` | reference | `docs/SITE_UPLEVEL_PLAYBOOK.md` § verification checklist (creds-blanked) + `docs/CONVENTIONS.md` §4 (FAKE-creds parity run) | already-homed |
| `reference_cicd_red_and_archive_moves.md` | reference | `scripts/check_main_green.py` (the wrap green-main gate) | already-homed |
| `reference_cloudfront_404_cache_smoke.md` | reference | `deploy/smoke_test_site.sh` (cache-aware reads, #1526) + `docs/CONVENTIONS.md` §9 (#2831) | already-homed |
| `reference_cloudfront_forwards_client_xff_unchanged.md` | reference | `docs/CONVENTIONS.md` §9a + `tests/test_rate_limit_identity_1221.py` | already-homed |
| `reference_cloudwatch_alarm_week_cap.md` | reference | — narrative: an AWS limit noted once; encoded in the alarm definitions | narrative |
| `reference_cloudwatch_query_form_errors_read_as_defects.md` | reference | `docs/OPERATING_DISCIPLINE.md` §1.3 + `.claude/agents/finding-verifier.md` 6 | already-homed |
| `reference_collect_only_lane_hides_infunction_imports.md` | reference | `docs/CONVENTIONS.md` §4a (deploy-critical lane) + `tests/conftest.py` | already-homed |
| `reference_concurrent_prs_union_breach_size_gate.md` | reference | `docs/CONVENTIONS.md` §9 (lane-subset / union-breach class, #3025 full-suite pre-merge) | already-homed |
| `reference_conflict_resolution_ate_a_return.md` | reference | — narrative: a single merge-conflict slip; the class is the merge-train header's rule | narrative |
| `reference_conflicting_pr_mints_no_checks.md` | reference | `.claude/skills/reconcile-branch/SKILL.md` | already-homed |
| `reference_content_policy_allowlist_follows_path.md` | reference | `docs/DECISIONS.md` ADR-146 (path-keyed registries move in the same commit as the code) + `.claude/skills/journal-interview/SKILL.md` | already-homed |
| `reference_correction_invisible_by_render_filter.md` | reference | `docs/SITE_UPLEVEL_PLAYBOOK.md` § hard-won gotchas (check the renderer's filters) | homed-here |
| `reference_cost_tracker_sync_owned_rows.md` | reference | `docs/COST_TRACKER.md` header (sync-owned literals) | homed-here |
| `reference_coverage_tranche_x_privacy_gate_union_breach.md` | reference | `docs/CONVENTIONS.md` §9 (union-breach class) + `docs/ENGINEERING_STANDARDS.md` | already-homed |
| `reference_css_token_guard_vs_visual_qa.md` | reference | `docs/SITE_UPLEVEL_PLAYBOOK.md` § verification checklist (`tests/test_css_tokens.py` on any CSS diff) | homed-here |
| `reference_data_driven_dark_states.md` | reference | `docs/OPERATING_DISCIPLINE.md` §1.9 (a red on your PR is a hypothesis until it reds on pristine main) | homed-here |
| `reference_delete_branch_closes_stacked_pr.md` | reference | `docs/OPERATING_DISCIPLINE.md` §2.6 | already-homed |
| `reference_deploy_api_before_frontend.md` | reference | `docs/CONVENTIONS.md` §9 (#2831) + `deploy/smoke_test_site.sh` | already-homed |
| `reference_deploy_coach_intelligence_excludes_the_worker.md` | reference | `.claude/skills/deploy/SKILL.md` (special case: coach specs + worker, both halves) | homed-here |
| `reference_deploy_from_main_not_worktree_branch.md` | reference | `docs/CONVENTIONS.md` §2 | already-homed |
| `reference_deploy_gate_approval_and_recovery.md` | reference | `docs/CONVENTIONS.md` §4d + `deploy/approve_deployment.sh` | already-homed |
| `reference_deploy_timestamp_is_not_the_commit.md` | reference | `.claude/skills/land/SKILL.md` §4 + `deploy/verify_deployed_symbol.sh` | already-homed |
| `reference_discovery_bias_loose_but_gate_the_verb.md` | reference | `.claude/skills/new-machinery/SKILL.md` § traps (strict on the verb, wide on the object) | homed-here |
| `reference_doc_index_strict_ci_only.md` | reference | `scripts/check_doc_index.py` header (Local == CI, #1965) | already-homed |
| `reference_doc_sync_literal_treadmill.md` | reference | `docs/CONVENTIONS.md` §4a1 (#2982/#3101) | already-homed |
| `reference_docs_current_truth_only.md` | reference | `docs/OPERATING_DISCIPLINE.md` §4.4 (write current truth, never intended truth) | homed-here |
| `reference_docsync_apply_writes_inside_conflict_blocks.md` | reference | `.claude/skills/reconcile-branch/SKILL.md` | already-homed |
| `reference_docsync_literal_cross_pr_drift.md` | reference | `docs/CONVENTIONS.md` §4c | already-homed |
| `reference_docsync_stamp_is_utc.md` | reference | `deploy/sync_doc_metadata.py` + `docs/CONVENTIONS.md` §4c | already-homed |
| `reference_driver_commits_strip_hook_literals.md` | reference | `docs/CONVENTIONS.md` § facts that drift (on a branch, none of that applies) + `deploy/agent_commit.sh` | already-homed |
| `reference_enumerate_all_leases_after_every_merge.md` | reference | `.claude/skills/land/SKILL.md` §3 + `docs/INCIDENT_LOG.md` 2026-08-30 | already-homed |
| `reference_epic_checklists_stale_by_construction.md` | reference | `.claude/skills/wrap/SKILL.md` (e8)/(e9) + `docs/CONVENTIONS.md` §4a2 closure DoD (lands with #3341; interim: the rule's own body + this row) | homed-here |
| `reference_event_delay_vs_swallow_and_accumulated_deploys.md` | reference | `.claude/skills/land/SKILL.md` §2 (delay is not swallow) + §4 (a cancelled superseded Deploy) | homed-here |
| `reference_extract_the_right_real_source.md` | reference | `.claude/skills/prove-it/SKILL.md` Q4 (is this the code path the running system takes?) | homed-here |
| `reference_extraction_never_baseline_raise.md` | reference | `docs/OPERATING_DISCIPLINE.md` §4.3 | already-homed |
| `reference_dark_flag_waiver_reason_rots_when_reach_changes.md` | reference | `docs/CONVENTIONS.md` §4 | homed-here |
| `reference_docs_only_commit_reds_every_pr_not_main.md` | reference | `docs/CONVENTIONS.md` §3 | homed-here |
| `reference_lease_steward_must_outlive_the_tip.md` | reference | `docs/CONVENTIONS.md` §4 | homed-here |
| `reference_fail_closed_paths_need_a_live_proof.md` | reference | `.claude/skills/prove-it/SKILL.md` § dark: a fail-closed path | homed-here |
| `reference_fail_closed_scoped_to_artifact_not_lane.md` | reference | `deploy/sync_site_to_s3.sh` (content-filter hold: regen held, exit 0) | already-homed |
| `reference_ffmpeg_slim_brew_and_ass_units.md` | reference | — off-repo: the vlog studio's tooling lives outside this repo | off-repo |
| `reference_fixture_must_be_the_wire.md` | reference | `docs/CONVENTIONS.md` §9a + `.claude/skills/prove-it/SKILL.md` Q4 | already-homed |
| `reference_freshness_window_writer_cadence.md` | reference | `docs/CONVENTIONS.md` §7 (config mirror audit: the writer's own TTL) | already-homed |
| `reference_frozen_artifact_supersede_annotation.md` | reference | `docs/OPERATING_DISCIPLINE.md` §4.5 (a frozen artifact keeps its numbers and gains a note) + `lambdas/operational/weight_truth_qa.py` | homed-here |
| `reference_gate_prose_is_a_parsed_interface.md` | reference | `.claude/skills/new-machinery/SKILL.md` § traps (a gate's reason string is a parsed interface) + `scripts/harvest_eval_fixtures.py` | homed-here |
| `reference_gate_registration_before_deploy.md` | reference | `docs/CONVENTIONS.md` §9 (declare in `deploy/api_deploy_sequencing.json`, #2831) + `docs/INCIDENT_LOG.md` 2026-08-02 | already-homed |
| `reference_gated_run_is_a_deploy_group_lease.md` | reference | `docs/OPERATING_DISCIPLINE.md` §5.3–5.5 + `.claude/skills/land/SKILL.md` §3 | already-homed |
| `reference_genesis_week_present_none.md` | reference | `docs/RUNBOOK.md` § Restart Pipeline (the present-None gate) + `deploy/smoke_test_site.sh` | already-homed |
| `reference_gh_merge_takes_branch_not_integration_tree.md` | reference | `deploy/merge_train.sh` header + `.claude/skills/reconcile-branch/SKILL.md` | already-homed |
| `reference_gh_merge_worktree_branch_switch.md` | reference | `.claude/skills/reconcile-branch/SKILL.md` + `.claude/skills/worktree/SKILL.md` | already-homed |
| `reference_gh_pr_checks_empty_is_not_green.md` | reference | `docs/CONVENTIONS.md` §9 (pre-commit: `scripts/assert_pr_green.py`) + `docs/OPERATING_DISCIPLINE.md` §3.7 | already-homed |
| `reference_git_add_a_sweeps_concurrent_agent_edits.md` | reference | `docs/OPERATING_DISCIPLINE.md` §3.2 | already-homed |
| `reference_git_checkout_path_destroys_your_own_edit.md` | reference | `docs/OPERATING_DISCIPLINE.md` §3.3 | already-homed |
| `reference_git_stash_shared_across_worktrees.md` | reference | `docs/CONVENTIONS.md` §7 | already-homed |
| `reference_github_env_protection_private_flip.md` | reference | `docs/DECISIONS.md` (#1319 ADR: required-ness is an owner toggle) + `docs/MANAGED_WHERE_LEDGER.md` | already-homed |
| `reference_github_event_swallow_recovery.md` | reference | `.claude/skills/land/SKILL.md` §2 | already-homed |
| `reference_github_token_push_never_dispatches.md` | reference | `.claude/skills/land/SKILL.md` §2 + `docs/CONVENTIONS.md` §9 (`head_coverage`) | already-homed |
| `reference_gitleaks_push_only.md` | reference | `docs/CONVENTIONS.md` §4 + `.github/workflows/ci-lint.yml` | already-homed |
| `reference_golden_tests_wallclock.md` | reference | `docs/CONVENTIONS.md` §7 + `tests/test_wallclock_fixture_bombs_2376.py` | already-homed |
| `reference_google_tts_per_sentence_limit.md` | reference | `lambdas/ai/google_tts.py` header (#2148) | already-homed |
| `reference_grounder_evidence_excludes_current_turn.md` | reference | — narrative: fixed by #2518; the harness rule it produced is homed (call-site row above) | narrative |
| `reference_guard_the_set_not_the_instance.md` | reference | `.claude/skills/new-machinery/SKILL.md` Q2 + `docs/CHARTER.md` | already-homed |
| `reference_harness_must_track_its_call_site.md` | reference | `.claude/skills/prove-it/SKILL.md` Q4 (does the harness match the production call site?) + `scripts/coach_chat_sim.py` | homed-here |
| `reference_hazard_gate_before_model.md` | reference | `docs/PROPORTIONALITY.md` (clinical-lite hazard gate row) + `lambdas/ai/safety_contract.py` | already-homed |
| `reference_iam_parity_codified_broken_state.md` | reference | `docs/CONVENTIONS.md` §6 (parity is not capability) | homed-here |
| `reference_import_time_frozen_globals_test_trap.md` | reference | `docs/TESTING.md` § traps (import-time env globals are order-fragile) | homed-here |
| `reference_inrepo_worktree_pollutes_scanners.md` | reference | `.claude/agents/worktree-implementer.md` 0b + `scripts/lane_worktree.py` | already-homed |
| `reference_io_threshold_tall_sections.md` | reference | — narrative: a front-end detail already in DESIGN_SYSTEM_V5 (IntersectionObserver threshold 0) | narrative |
| `reference_issue_closed_against_unmerged_pr.md` | reference | `docs/OPERATING_DISCIPLINE.md` §2.4 | already-homed |
| `reference_job_timeout_renders_as_cancelled.md` | reference | `docs/OPERATING_DISCIPLINE.md` §4.6 | homed-here |
| `reference_judge_flake_ground_truth.md` | reference | `docs/OPERATING_DISCIPLINE.md` §1.5 | already-homed |
| `reference_judge_reproducing_false_positive_shapes.md` | reference | `docs/OPERATING_DISCIPLINE.md` §1.5 (a reproduced verdict is not thereby real) | homed-here |
| `reference_lambda_perf_measure_at_origin.md` | reference | `.claude/skills/land/SKILL.md` §5 (measure at origin, post-deploy) | homed-here |
| `reference_lane_branch_must_not_carry_counter_file.md` | reference | `.claude/skills/reconcile-branch/SKILL.md` §0 ("no branch may carry the counter file") + `docs/CONVENTIONS.md` §3 | already-homed |
| `reference_launchd_tcc_documents.md` | reference | `docs/NEW_MACHINE_BOOTSTRAP.md` §3c | already-homed |
| `reference_layer_shipped_deps_dependabot_blind.md` | reference | `docs/CONVENTIONS.md` §1 (the layer is retired; the class is gone with it) | already-homed |
| `reference_llm_json_maxtokens_truncation.md` | reference | `docs/CONVENTIONS.md` §7 (an LLM JSON call whose `max_tokens` truncates falls back silently) | homed-here |
| `reference_local_black_vs_pinned_black.md` | reference | `docs/CONVENTIONS.md` §9 (the format gate resolves the pin) + `scripts/install_hooks.sh` | already-homed |
| `reference_local_render_qa.md` | reference | `.claude/agents/render-qa.md` § harness rules | already-homed |
| `reference_magicmock_pagination_oom_runner_shutdown.md` | reference | — narrative: one runner OOM diagnosis; the fix is in the test that caused it | narrative |
| `reference_mcp_bridge_key_rotation_detach.md` | reference | `docs/RUNBOOK.md` § MCP Server Failure (two transports) + `docs/NEW_MACHINE_BOOTSTRAP.md` §3b + `docs/SECRETS_MAP.md` | already-homed |
| `reference_mcp_bundle_needs_reading.md` | reference | `.claude/skills/deploy/SKILL.md` (mcp special case) + `deploy/build_bundle.py` | already-homed |
| `reference_measure_before_accepting_a_defect_rate.md` | reference | `docs/OPERATING_DISCIPLINE.md` §1.7 | already-homed |
| `reference_measure_before_believing_the_premise.md` | reference | `docs/OPERATING_DISCIPLINE.md` §1.2 + `.claude/agents/finding-verifier.md` 5 | already-homed |
| `reference_merge_queue_no_blind_add.md` | reference | `docs/OPERATING_DISCIPLINE.md` §3.2 + `deploy/agent_commit.sh` | already-homed |
| `reference_merge_verdict_separate_command.md` | reference | `docs/OPERATING_DISCIPLINE.md` §3.7 + `.claude/skills/land/SKILL.md` §1 | already-homed |
| `reference_merged_is_not_deployed.md` | reference | `docs/OPERATING_DISCIPLINE.md` §2.3 + `.claude/skills/land/SKILL.md` §4 | already-homed |
| `reference_module_relative_config_paths_must_not_encode_depth.md` | reference | `CLAUDE.md` (ADR-146 paragraph: `common.repo_config`) | already-homed |
| `reference_negated_closing_keyword_still_closes.md` | reference | `docs/OPERATING_DISCIPLINE.md` §2.5 | already-homed |
| `reference_never_diagnose_from_a_truncated_log_line.md` | reference | `docs/OPERATING_DISCIPLINE.md` §1.4 + `.claude/agents/finding-verifier.md` 8 | already-homed |
| `reference_new_site_page_registries.md` | reference | `docs/SITE_AUTHORING.md` + `tests/qa_manifest.py` | already-homed |
| `reference_no_tool_attribution_trailers.md` | reference | `CLAUDE.md` § Authorship + `tests/test_no_tool_attribution_3005.py` | already-homed |
| `reference_node_check_lazy_parse.md` | reference | `docs/SITE_UPLEVEL_PLAYBOOK.md` § verification checklist (`scripts/import_site_js_graph.mjs`) | already-homed |
| `reference_og_card_fonts_tofu.md` | reference | `docs/SITE_UPLEVEL_PLAYBOOK.md` § gotchas (verify generated PNGs) | homed-here |
| `reference_orphan_gate_inline_writer_literal.md` | reference | `docs/TESTING.md` § traps (the orphan-partition gate resolves writers by AST; no `-x`) + `tests/test_site_partition_orphans.py` | homed-here |
| `reference_package_import_breaks_sys_modules_stubs.md` | reference | `docs/DECISIONS.md` ADR-146 + `tests/bundle_stubs.py`; pointer added in `docs/TESTING.md` § traps | already-homed |
| `reference_partition_scoped_sweep_rots_when_partition_gains_classes.md` | reference | `docs/PHASE_TAXONOMY.md` lesson 15 (scope a repair by classification, never by container) | homed-here |
| `reference_platform_facts_maintained_literal.md` | reference | `docs/CONVENTIONS.md` § facts that drift + `deploy/sync_doc_metadata.py` | already-homed |
| `reference_platform_logger_capture_and_dark_module_loggers.md` | reference | `docs/MONITORING.md` § structured logging | homed-here |
| `reference_pr_checks_lack_mypy_gate.md` | reference | fixed 2026-08-09 — the PR lane runs the mypy + size gates; `docs/CONVENTIONS.md` §4a0 | superseded |
| `reference_premerge_registration_moves_the_census.md` | reference | `docs/CONVENTIONS.md` §4a1 | already-homed |
| `reference_prereg_dry_run_review.md` | reference | `docs/RUNBOOK.md` § Restart Pipeline (the attended dry-run-review posture) + `docs/OPERATING_DISCIPLINE.md` §4.5 | already-homed |
| `reference_prompt_structural_guarantees.md` | reference | `docs/DECISIONS.md` ADR-104 (grounded-generation gate) + `lambdas/ai/behavior_logs.py` | already-homed |
| `reference_push_ci_silent_death.md` | reference | `docs/CONVENTIONS.md` §4d.1/4d.3 | already-homed |
| `reference_pytest_pipe_exit_code.md` | reference | `docs/OPERATING_DISCIPLINE.md` §3.4 | already-homed |
| `reference_qa_smoke_alarm_window_load_bearing.md` | reference | `docs/MONITORING.md` § active alarms (`qa-smoke-failures`) | homed-here |
| `reference_r8st6_iam_review_gate.md` | reference | `docs/CONVENTIONS.md` §4d.2 | already-homed |
| `reference_rate_limit_must_charge_the_fanout.md` | reference | `docs/CONVENTIONS.md` §7 (charge the fan-out, not the request) | homed-here |
| `reference_read_for_a_later_adr_amendment.md` | reference | `docs/OPERATING_DISCIPLINE.md` §4.1 | already-homed |
| `reference_read_the_deploy_critical_lane_by_name.md` | reference | `docs/CONVENTIONS.md` §4a + `.claude/skills/land/SKILL.md` §1 | already-homed |
| `reference_rebase_continue_phantom_wedge.md` | reference | `docs/CONVENTIONS.md` §4d.3 | already-homed |
| `reference_rebase_merge_queue_discipline.md` | reference | `deploy/merge_train.sh` + `.claude/skills/reconcile-branch/SKILL.md` | already-homed |
| `reference_reconcile_bot_handles_main_literals.md` | reference | `docs/CONVENTIONS.md` §4c | already-homed |
| `reference_reconcile_job_cannot_derive_census.md` | reference | `scripts/skill_lint.py` header + `.claude/skills/prove-it/SKILL.md` § dark: a missing dependency | already-homed |
| `reference_reexport_is_not_a_patch_point.md` | reference | `docs/TESTING.md` § traps (the old module is a re-export, not a patch point) | homed-here |
| `reference_regen_invoke_email_lambda_trap.md` | reference | `docs/RUNBOOK.md` § never a bare sync invoke (`dry_run`, async invoke); the no-gate half is superseded — the sender honours `dry_run` since #2111 | already-homed |
| `reference_reject_a_gated_run_pinned_to_a_stale_sha.md` | reference | `docs/OPERATING_DISCIPLINE.md` §5.3–5.5 + `.claude/skills/land/SKILL.md` §3 | already-homed |
| `reference_removing_a_confound_reveals_the_second_defect.md` | reference | `docs/OPERATING_DISCIPLINE.md` §2.12 | already-homed |
| `reference_reset_pipeline_owned_manifest_clobber.md` | reference | — narrative: a dated 2026-07-18 drill finding; the maintained procedure is RUNBOOK § Restart Pipeline | narrative |
| `reference_rollback_partial_fires_mixed_fleet.md` | reference | `docs/CONVENTIONS.md` §4d (`deploy_all=true` recovery) + `docs/RUNBOOK.md` § Rolling Back | already-homed |
| `reference_ruff_full_dir_set.md` | reference | `CLAUDE.md` (format gate paragraph) + `docs/CONVENTIONS.md` §4 | already-homed |
| `reference_s3_first_config_invalidates_local_measurement.md` | reference | `.claude/skills/prove-it/SKILL.md` Q4 (does the after actually contain the change?) + `scripts/coach_chat_sim.py` (`--local-specs`) | homed-here |
| `reference_saturated_alarm_hides_its_own_findings.md` | reference | `docs/CONVENTIONS.md` §9 (fired-and-cleared flap detector, #2912) + `docs/MONITORING.md` | already-homed |
| `reference_scratchpad_is_shared_across_concurrent_agents.md` | reference | `docs/OPERATING_DISCIPLINE.md` §3.1 + `.claude/agents/worktree-implementer.md` 0 | already-homed |
| `reference_security_docs_never_via_hand_twin.md` | reference | `docs/INCIDENT_LOG.md` 2026-08-30 row; structural home lands with #3336 (script applies `infra/iam/*.json` verbatim) | homed-here |
| `reference_shallow_clone_git_gates.md` | reference | `scripts/check_doc_index.py` header (shallow-clone caveat) | already-homed |
| `reference_shared_scratchpad_clobbers_pr_bodies.md` | reference | `docs/OPERATING_DISCIPLINE.md` §3.1 + `.claude/agents/worktree-implementer.md` 0 | already-homed |
| `reference_ship_the_mechanism_print_the_residual.md` | reference | `docs/OPERATING_DISCIPLINE.md` §2.10 | already-homed |
| `reference_single_file_deploy_strips_siblings.md` | reference | `CLAUDE.md` (Site API: full-tree bundle, never single-file) + `.claude/skills/deploy/SKILL.md` | already-homed |
| `reference_site_api_layer_manual_attach.md` | reference | `.claude/skills/deploy/SKILL.md` (site-api special case) + `docs/ARCHITECTURE.md` | already-homed |
| `reference_site_deploy_superseded_skip.md` | reference | `tests/test_site_deploy_supersede_guard.py` + `.github/workflows/site-deploy.yml` | already-homed |
| `reference_site_js_test_and_build_pairs.md` | reference | `docs/SITE_UPLEVEL_PLAYBOOK.md` § JS unit-test harness | already-homed |
| `reference_site_rollback_rerun_full_not_failed.md` | reference | `docs/CONVENTIONS.md` §4b (rerun the FULL workflow after an auto-rollback) | homed-here |
| `reference_site_smoke_transient_timeout_rollback.md` | reference | resolved by #1911 — `deploy/smoke_test_site.sh` header (exit 28 is named, never bare) | superseded |
| `reference_small_gap_reset_false_positive.md` | reference | `docs/RUNBOOK.md` § Restart Pipeline (two reset reflexes: the semantic gate is authoritative) | homed-here |
| `reference_smoke_invalidation_race.md` | reference | `deploy/smoke_test_site.sh` header + `deploy/README.md` (`deploy_convergence.py`, #2978) | already-homed |
| `reference_stale_behind_a_fresh_timestamp.md` | reference | `docs/OPERATING_DISCIPLINE.md` §4.2 (run the generator's own `--check`) | already-homed |
| `reference_stale_data_row_reverts_code_deploy.md` | reference | `docs/CONVENTIONS.md` §8b (#2051 in the class ledger) + `docs/INCIDENT_LOG.md` 2026-08-04 | already-homed |
| `reference_strptime_is_the_inverse_of_a_clock.md` | reference | `docs/CONVENTIONS.md` §7 (DATE# keys name a Pacific day; strptime is invisible to the clock matchers) | homed-here |
| `reference_structural_set_is_not_a_ci_proxy.md` | reference | `docs/CONVENTIONS.md` §4a1 | already-homed |
| `reference_suppressor_rules_must_be_structural.md` | reference | `.claude/skills/incident/SKILL.md` (structural, or it will fail too) + `deploy/wait_pr_green.sh` | already-homed |
| `reference_svg_text_outline_and_theme_bake.md` | reference | `scripts/build_brand_assets.py` header | already-homed |
| `reference_svg_type_floor_truth.md` | reference | `docs/SITE_UPLEVEL_PLAYBOOK.md` § hard-won gotchas (the fs-ok floor sanction) + `scripts/check_css_tokens.py` | homed-here |
| `reference_swallowed_push_no_runs_at_all.md` | reference | `.claude/skills/land/SKILL.md` §2 + `docs/CONVENTIONS.md` §9 (`head_coverage`) | already-homed |
| `reference_task_notification_exit_codes_lie.md` | reference | `docs/OPERATING_DISCIPLINE.md` §3.6 | already-homed |
| `reference_test_importing_aws_cdk_reds_ci.md` | reference | `docs/CONVENTIONS.md` §4a1 table + `CLAUDE.md` (CDK facts by AST) | already-homed |
| `reference_test_layer_dep_import_collection_red.md` | reference | `docs/CONVENTIONS.md` §1 (the layer is retired) + `tests/conftest.py` | already-homed |
| `reference_the_rubric_can_be_the_finding_generator.md` | reference | `docs/OPERATING_DISCIPLINE.md` §1.6 | already-homed |
| `reference_time_dependent_gate_outside_its_window.md` | reference | `.claude/skills/prove-it/SKILL.md` § dark: a window it never runs in; the fixture half in `docs/TESTING.md` § traps | homed-here |
| `reference_token_overlap_misses_structural_cloning.md` | reference | — narrative: a one-off measurement about a similarity metric | narrative |
| `reference_two_module_size_guards.md` | reference | `tests/conftest.py` (`_PREMERGE_EXTRA_FILES`: both size gates) + `docs/ENGINEERING_STANDARDS.md` | already-homed |
| `reference_verify_bundle_boot_is_the_real_gate.md` | reference | `.claude/skills/deploy/SKILL.md` (verify it BOOTS) + `docs/DECISIONS.md` ADR-146 | already-homed |
| `reference_volatile_timestamp_in_asserted_blob.md` | reference | `docs/TESTING.md` § traps (a substring asserted absent from `json.dumps`) | homed-here |
| `reference_withings_transient_refresh.md` | reference | `docs/REMEDIATION_TAXONOMY.md` + `deploy/MANIFEST.md` | already-homed |
| `reference_workflow_step_deps_and_first_apply.md` | reference | `.claude/skills/prove-it/SKILL.md` § dark: a missing dependency; the first-apply half in `docs/OPERATING_DISCIPLINE.md` §5.8 | already-homed |
| `reference_worktree_agent_path_reuse.md` | reference | `.claude/agents/worktree-implementer.md` 0b + `scripts/lane_worktree.py` | already-homed |
| `reference_worktree_case_insensitive_pollution.md` | reference | `docs/CONVENTIONS.md` §7 | already-homed |
| `reference_local_axe_blind_to_color_mix_contrast.md` | reference | `docs/CONVENTIONS.md` §7 (local axe blind to color-mix contrast — prove by arithmetic, read CI's report.json) | homed-here |
| `reference_rerun_reuses_the_original_merge_commit.md` | reference | `docs/CONVENTIONS.md` §6 CI-recovery table (rerun reuses the stale merge ref — update-branch, never rerun --failed) | already-homed |
| `reference_reordering_sync_steps_changes_what_each_step_owns.md` | reference | `docs/CONVENTIONS.md` §7 (reordering a sync changes ownership — assert include sets disjoint); INCIDENT_LOG 2026-08-31 P1 | homed-here |
| `reference_stack_census_prs_on_a_nonstrict_ruleset.md` | reference | `docs/CONVENTIONS.md` §7 (stack census-bumping PRs; re-rebase after each squash) | homed-here |
| `reference_a_filed_issues_mechanism_is_a_hypothesis.md` | reference | `docs/CONVENTIONS.md` §7 (a filed issue's stated mechanism is a hypothesis — reproduce before implementing; `describe-stack-events` is the decisive "did that deploy ship X") | homed-here |
| `reference_future_genesis_breaks_rules_not_just_tests.md` | reference | `docs/CONVENTIONS.md` §7 (a staged future genesis breaks genesis-anchored RUNTIME rules, not just tests — bound the floor by `today`, never skip pre-start) | homed-here |
| `security_r22_mcp_token_exposure.md` | security | — off-repo by design: security-incident detail stays out of the public repo (`docs/CONTINUITY.md` §4); the fixes are recorded on #779/#780/#893 and in `docs/DECISIONS.md` | off-repo |

## Program and session records — `project_*`

A `project_*` file is a body of work's narrative (what shipped, what is pending, the night's
forks). Its repo equivalent is the session handover, archived on the `session-archive`
branch (`docs/CONTINUITY.md` §1). The rows below name a home only where the file also
carries an operating rule.

| memory file | type | home | status |
|---|---|---|---|
| `project_adr046_generated_prefix.md` | project | `CLAUDE.md` (S3 prefix separation) + `docs/DECISIONS.md` ADR-046 | already-homed |
| `project_agrade_d2_drain_2026_08_24.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_session_o_launch_2026_08_31.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_session_p_2026_09_01.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_agrade_program_2026_08_23.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_alarm_board_2026_08_15.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_arch781_layer_retirement.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_backlog_blitz_2026_07_12.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_backlog_drain_2026_08_19.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_backlog_paydown_2026_07_08.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_backlog_pm_2026_07_27.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_backlog_sweep_2026_07_11b.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_bodyscan2_wave_2026_08_16.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_bug_bash_2026_07_06.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_bug_bash_2026_08_14.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_bugbash_queue_2026_08_14.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_build_fingerprint.md` | project | `docs/CONVENTIONS.md` § facts that drift (live site build: `/version.json`) | already-homed |
| `project_cc_series.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_character_math_v2.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_character_sheet_2026_07.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_charter_paydown_cycle14_2026_08_17.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_chat_journey_2026_07_18.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_cloudfront_invalidation_path.md` | project | `docs/SITE_UPLEVEL_PLAYBOOK.md` § gotchas (invalidate the VIEWER path) + `docs/RUNBOOK.md` § never a bare sync invoke | already-homed |
| `project_coach_feedback_loops_2026_07_22.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_coach_opinion_engine.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_coach_portraits_program.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_coach_sim_harness_2026_08_10.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_coaching_brilliance_2026_08_10.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_coaching_redesign.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_coaching_team_v2_2026_08_10.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_coherence_program.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_complexity_paydown_2026_07_08.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_conformance_guard_2026_08_17.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_craft_review_2026_07_21.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_cycle5_reset_2026_07_10.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_cycle6_reset_2026_07_13.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_data_source_health_review.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_decision_sprint_2026_07_09.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_deep_context_2026_07_19.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_deploy_plane_cluster_2026_08_20.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_deploy_plane_unblock_2026_08_22.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_deploy_unblock_2026_08_18.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_design_pipeline_2026_07_18.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_doc_drift_guardrails_2026_07_13.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_elite_review_2026_08_16.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_elite_uplevel_2026_07.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_epic_1890_live_honesty.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_epic_closeout_2026_07_12.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_epic_tails_drain_2026_08_21.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_fable_graded_the_week_2026_08_16.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_fable_later_paydown.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_fable_next_batch.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_fable_paydown2_2026_07_11.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_fable_r21_batch.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_fable_triage_2026_08_20.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_fable_week_lane_a_2026_08_22.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_fable_week_session2_2026_08_23.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_frontier_review_2026_07_18.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_financial_diligence_2026_08_31.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_fullreview_panel.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_gate_audit_2026_08_13.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_gate_owner_unblock_2026_08_02.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_gates_paid_for_themselves_2026_08_09.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_genesis_night_close_2026_07_12.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_golden_brief_eval_742.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_green_main_prereg_repo_private_2026_07_13.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_home_overflow_followup.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_honesty_pair_adr104.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_instruments_were_the_defect_2026_08_15.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_intelligence_roadmap_2026_07.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_launch_dates.md` | project | `CLAUDE.md` (EXPERIMENT_START_DATE is the anchor) + `lambdas/common/constants.py` | already-homed |
| `project_machinery_first_2026_08_22.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_max_opus_paydown_2026_08_22.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_mobile_pwa.md` | project | — narrative: a product decision recorded in DESIGN_SYSTEM_V5's responsive rules; no operating rule | narrative |
| `project_mobile_uplevel_2026_07.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_monday_reset.md` | project | `docs/RUNBOOK.md` § Restart Pipeline + `docs/PHASE_TAXONOMY.md` | already-homed |
| `project_next_paydown_2026_07_08.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_nonfable_drain_2026_08_11.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_nutrition_24h_lag.md` | project | `.claude/skills/qa/SKILL.md` (nutrition ~24h-lag semantics) | already-homed |
| `project_nutrition_privacy_flags.md` | project | `docs/DATA_GOVERNANCE.md` | already-homed |
| `project_observability_slice_2026_08_18.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_opus_batch_2026_07_05.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_opus_batch_2026_07_06.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_overnight_burn_2026_08_09.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_overnight_honesty_arc_2026_08_16.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_p1_rate_limit_identity_2026_08_21.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_panel_reset_selection.md` | project | — narrative: one panel-selection detail; the reset procedure is RUNBOOK § Restart Pipeline | narrative |
| `project_panelcast_quality_bar.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_paydown_2026_07_07.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_personal_baselines_layer_outage.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_phase_taxonomy.md` | project | `docs/PHASE_TAXONOMY.md` | already-homed |
| `project_phenoage_privacy.md` | project | `docs/DATA_GOVERNANCE.md` (chronological age is never published) | already-homed |
| `project_plan_then_execute_2026_08_22.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_platform_audit_2026.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_podcasts_google_tts.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_pr_render_gate_408.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_pre13_deferred.md` | project | `CLAUDE.md` § Privacy (per-variant publication = PRE-13, deferred) | already-homed |
| `project_presence_quiet_stretch.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_privacy_guard_sweep_2026_08_08.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_qa_strategy_2026_07_18.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_queue_paydown_2026_08_10.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_r21_batch1_2_2026_07_06.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_r21_prediction_integrity.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_r22_build_paydown_2026_07_06.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_r22_consultancy_review.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_reader_engagement_loop.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_reading_mind_pillar.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_reconcile_and_branches_2026_07_05.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_repo_privacy_remediation.md` | project | — off-repo by design: the remediation plan is kept outside the repo | off-repo |
| `project_repo_visibility.md` | project | stale — the repo has been PUBLIC since 2026-07-20; `.claude/agents/issue-filer.md` states it | superseded |
| `project_reset_purges_site_config.md` | project | `docs/CONVENTIONS.md` §7 (three prefixes; `config/` ↔ `site/config/` parity) | already-homed |
| `project_review_backlog_program.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_review_remediation_2026_07_12.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_sdlc_review_2026_07_18.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_september_base_2026_08_18.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_serial_and_self_sustaining.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_session_a_2026_08_25.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_session_b_2026_08_25.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_session_c_2026_08_26.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_session_d_2026_08_26.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_session_e_2026_08_27.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_session_f_2026_08_27.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_session_g_2026_08_27.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_shipped_archive.md` | project | index annex of MEMORY.md (terminal entries) | index |
| `project_silent_failure_drain_2026_08_15.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_social_membrane_2026_07_21.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_sonnet_batch_session17.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_stolen_laptop_resilience_2026_07_11.md` | project | `docs/DISASTER_RECOVERY.md` + `docs/NEW_MACHINE_BOOTSTRAP.md` | already-homed |
| `project_sweep_2026_07_11.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_system_model_2026_08_17.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_telegram_coach_chat_2026_08_09.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_throughput_session_2026_08_08.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_traffic_digest_measurement.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_training_truth_412.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_truth_audit.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_unblock_six_2026_07_10.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_uplevel_driver_and_board.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_uplevel_roadmap_2026_07.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_v5_coherence_redesign.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_visual_identity_system.md` | project | `docs/DESIGN_SYSTEM_V5.md` (never reintroduce emoji; reach for the shared modules) | already-homed |
| `project_visual_uplevel_2026_07.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_vlog_studio_2026_07_26.md` | project | — off-repo: the studio lives outside the repo | off-repo |
| `project_voice_studio_2026_07_19.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_whoop_reauth.md` | project | `docs/RUNBOOK.md` § Common Issues (`ingest-auth-unhealthy-24h`, the auth breaker) + `docs/ACCOUNTS.md` | already-homed |
| `project_wiki_program_2026_07_10.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_wrong_day_and_wrong_gauge_2026_08_18.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |
| `project_session_q_2026_09_01.md` | project | — narrative: a program/session record; the repo's equivalent is the `session-archive` branch of `handovers/` | narrative |

## Out of scope

| memory file | type | home | status |
|---|---|---|---|
| `INDEX_review_discipline.md` | index | — the memory index itself | index |
| `MEMORY.md` | index | — the memory index itself | index |
| `user_who_is_matthew.md` | user | — out of scope: who the owner is stays in memory | user |

---

**Verified:** 2026-08-30 (#2848 — snapshot taken from the live memory index by file name only;
every `homed-here` row was written into its cited home in the same PR; every cited path
checked against the tree by `tests/test_operating_knowledge_ledger_2848.py`)
