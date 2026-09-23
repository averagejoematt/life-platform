"""tests/obligation_residue_3597.py — the #3597 obligation-carrier residue ledger.

THE dated, shrink-only record of every obligation block (`revisit …`, `fast-follow`,
`owner decides`, a deferral to later/step N) on a governed surface
(`scripts/obligation_carriers.OBLIGATION_SURFACES`) that carried NO home — no carrier
`#N`, no `not-work —` tag, no calendar-probed date — when the rule landed.

Each key is ``path::<sha256-12 of the cue sentence, digits masked>`` — content-keyed on
purpose (the conformance-residue precedent, #2844): EDITING a pinned obligation's words
re-keys it, surfaces as a NEW unhomed obligation, and the only green path is giving it a
home. Digits are masked so a doc-literal sync rewriting a count does not re-key a row.
Entries only ever come OUT — a key whose block gained a home (or was deleted) must be
removed, and `tests/test_obligation_carriers_3597.py` reds a stale key so the ledger
cannot silently over-state its debt.

Seeded 2026-09-23 by `python3 scripts/obligation_carriers.py --keys` — the sweep's own
output, no hand-typed key. 44 rows: 39 in docs/DECISIONS.md, 5 in docs/PROPORTIONALITY.md,
0 in docs/alarm_citations.json. The trailing comment on each row is the cue sentence at
seeding, for a reviewer — it is not read by anything.

Registered in `scripts/obligation_carriers.RESIDUE_LEDGERS` (carrier, condition, expiry).
"""

OBLIGATION_RESIDUE: dict[str, str] = {
    "docs/DECISIONS.md::66a2714d58f9": "2026-09-23",  # | ADR-029 | MCP Monolith: Retain Single Lambda, Revisit at 100+ Calls/Day | Active | 2026-03-15 |
    "docs/DECISIONS.md::5673a1f5d53c": "2026-09-23",  # Revisit if table grows beyond 10GB or new access patterns emerge.
    "docs/DECISIONS.md::a188255f557c": "2026-09-23",  # Revisit if usage pattern shifts to high-frequency interactive sessions.
    "docs/DECISIONS.md::55dbe6ea2e49": "2026-09-23",  # Revisit if platform ever becomes multi-tenant or processes clinical-grade regulated health data.
    "docs/DECISIONS.md::43247602c759": "2026-09-23",  # Revisit when either:
    "docs/DECISIONS.md::7c76c9675dcb": "2026-09-23",  # **Revisit conditions:**
    "docs/DECISIONS.md::265b9af0f955": "2026-09-23",  # **Revisit trigger defined.** If tool selection accuracy degrades measurably (Claude consistently pic
    "docs/DECISIONS.md::a631509ed3a8": "2026-09-23",  # Revisit only if a model's floor drops or a prompt grows on its own merits; the register's test fires
    "docs/DECISIONS.md::30a48131774c": "2026-09-23",  # Revisit per trigger conditions above.
    "docs/DECISIONS.md::e00332936068": "2026-09-23",  # Revisit only if a second major importer emerges.
    "docs/DECISIONS.md::1e440764aeff": "2026-09-23",  # Revisit only if a 6th+ data type is added.
    "docs/DECISIONS.md::8b5b206203ff": "2026-09-23",  # Revisit only if a new endpoint surfaces an actually-unbounded query.
    "docs/DECISIONS.md::5b2486e235bd": "2026-09-23",  # Revisit only when a second real user is on the horizon.
    "docs/DECISIONS.md::87eb32b6b994": "2026-09-23",  # the deferral posture itself (revisit only when a second real user is on the horizon)
    "docs/DECISIONS.md::5d01fc7c1bc3": "2026-09-23",  # **Revisit trigger:** the operator's `shadow` → `auto` flip.
    "docs/DECISIONS.md::f57c2c65511f": "2026-09-23",  # **Revisit trigger.** Two consecutive quarterly proportionality re-reads with zero `ALLOW-ADDITIVE` l
    "docs/DECISIONS.md::2ad27d8b5d56": "2026-09-23",  # **Revisit trigger.** A stack deploy blocked by a Deny in this document that is judged legitimate → w
    "docs/DECISIONS.md::2e05d0f10b71": "2026-09-23",  # Phase 1 prefers the simpler interpretation; Phase 2 can revisit if the drift turns out to matter.
    "docs/DECISIONS.md::b06ce287ef49": "2026-09-23",  # (Reversible: enabling both is a few CLI/CDK calls; revisit on the triggers below.)
    "docs/DECISIONS.md::7af3c20b944f": "2026-09-23",  # **Revisit triggers:** a second/paying user, an SLA commitment, or the platform becoming something wh
    "docs/DECISIONS.md::0d292c231ecb": "2026-09-23",  # Retained verbatim; see the amendment below.]** **Monitor trigger (revisit this ADR when):** Google s
    "docs/DECISIONS.md::0b8eb0c9f65c": "2026-09-23",  # **The ceiling stays $75 for now, chosen on purpose rather than inherited.** The number is re-affirme
    "docs/DECISIONS.md::1dca3dd01d95": "2026-09-23",  # At 100 board questions/day — far beyond current traffic — the month costs ~$50, which is the point o
    "docs/DECISIONS.md::ea62f60844ce": "2026-09-23",  # **Revisit trigger.** The trigger firing (either arm) re-opens monetization as a deliberate session w
    "docs/DECISIONS.md::438bd3e7485d": "2026-09-23",  # The choice was never recorded, and internal notes justified revisiting it with a premise the 2026-07
    "docs/DECISIONS.md::d24f566c61a2": "2026-09-23",  # **Revisit trigger (concrete, not "someday"):** introduce a READ-SIDE analytical layer (DuckDB/Athena
    "docs/DECISIONS.md::ac77930dcbab": "2026-09-23",  # field_notes keeps its own dict-shaped regen flow (already on the shared guard); the STANCE# writer g
    "docs/DECISIONS.md::c9804a7478e5": "2026-09-23",  # **Revisit only if** Garmin ingestion is restored to a healthy, non-rate-limited cadence — at which p
    "docs/DECISIONS.md::591f9f959d6c": "2026-09-23",  # Future "add an LLM council" proposals are answered by this ADR unless a proposer clears the revisit
    "docs/DECISIONS.md::31dc0266ed03": "2026-09-23",  # Revisit the threshold as the baseline traffic grows — it is one env var, not a code change.
    "docs/DECISIONS.md::9ae37b788b4d": "2026-09-23",  # **The revisit clause's carrier.** `tests/test_cost_governor.py::test_derived_threshold_exceeds_every
    "docs/DECISIONS.md::359e10311f1f": "2026-09-23",  # **Revisit trigger.** Reopen only when BOTH hold: the dose-response engine has armed (≥15 nonzero eve
    "docs/DECISIONS.md::42c130c63b33": "2026-09-23",  # **Revisit trigger (mirrors ADR-057).** Reopen when any of: real multi-user traffic (a second N=1 wit
    "docs/DECISIONS.md::6d49dc1549bd": "2026-09-23",  # **Revisit trigger.** Flip the lane to required (owner toggle + posture-file flip, same PR) when eith
    "docs/DECISIONS.md::03de035d6f9b": "2026-09-23",  # Revisit trigger: if conversation-sourced moves ever dominate a coach's confidence state (conversatio
    "docs/DECISIONS.md::cdfcf00ab73c": "2026-09-23",  # **Revisit when** any of these change: a second contributor (required reviews stop being absurd and s
    "docs/DECISIONS.md::651298774e7e": "2026-09-23",  # Keep brute-force cosine over a single `Query`.** Recorded with a concrete revisit trigger rather tha
    "docs/DECISIONS.md::bf4197e03458": "2026-09-23",  # **Revisit trigger (both conditions, not either).** Revisit when (a) the recall corpus exceeds **~5,0
    "docs/DECISIONS.md::5fecce78918f": "2026-09-23",  # The cost honestly carried: between DEXA scans the floor has no automated tripwire, and full-scan com
    "docs/PROPORTIONALITY.md::e6cd9c13ca46": "2026-09-23",  # | fresh-eyes weekly survey workflow | Portfolio | $ (small) | **This row's own revisit trigger FIRED
    "docs/PROPORTIONALITY.md::1f3a16390c3f": "2026-09-23",  # **Revisit:** measurable reader-audience growth · any accessibility complaint · commercialization |
    "docs/PROPORTIONALITY.md::51b488bd00b9": "2026-09-23",  # **Revisit triggers: a second subject · any external claim of generalization · a published methods ar
    "docs/PROPORTIONALITY.md::bedbff955964": "2026-09-23",  # **Revisit triggers:** a second user of any kind · any claim on the public surface that crosses from
    "docs/PROPORTIONALITY.md::fc23c29c6324": "2026-09-23",  # **The honest residual is recovery TIME, not recoverability.** **Revisit triggers:** a second operato
}


# ── the Load-bearing demote field (#3597 box 2) ──────────────────────────────────────────
# Every `docs/PROPORTIONALITY.md` row whose posture cell opens `Load-bearing` and carries
# neither `demote_by: YYYY-MM-DD` nor `demote_when: <condition>` when the rule landed —
# 81 of 81 on 2026-09-23 (most state a free-text **Demote trigger:**, which the calendar
# cannot read). Keyed on the digit-masked subsystem cell (`obligation_carriers.demote_row_key`).
# Seeded by `python3 scripts/obligation_carriers.py --demote-keys`. Shrink-only; drain = #4122.
DEMOTE_FIELD_RESIDUE: dict[str, str] = {
    "docs/PROPORTIONALITY.md::1bd2f64860a6": "2026-09-23",  # Review carry-forward cap + frozen anchors + calibration controls (#3603)
    "docs/PROPORTIONALITY.md::a966659ba7dc": "2026-09-23",  # a11y shrink-ledger dead-man + phase flag (#3546)
    "docs/PROPORTIONALITY.md::16e9df864d59": "2026-09-23",  # Pre-genesis prediction provenance contract (#3511)
    "docs/PROPORTIONALITY.md::2b05fbe4cde1": "2026-09-23",  # Chronicle status-row write-liveness dead-man (#3563)
    "docs/PROPORTIONALITY.md::f5da1afc0c6c": "2026-09-23",  # Ensemble-digest cycle-row liveness check (#3829)
    "docs/PROPORTIONALITY.md::097f4b94c188": "2026-09-23",  # Hevy folder full-page walk + truncation report (#3670)
    "docs/PROPORTIONALITY.md::6002913d044f": "2026-09-23",  # Daily recap card (#3741)
    "docs/PROPORTIONALITY.md::aeb146dcad39": "2026-09-23",  # Hevy template-index rebuild + dead-man (#3764)
    "docs/PROPORTIONALITY.md::02b3972805df": "2026-09-23",  # Progress-photo capture over Telegram (#3758)
    "docs/PROPORTIONALITY.md::dc91531a2ebb": "2026-09-23",  # Public-write prefix registry (#3741)
    "docs/PROPORTIONALITY.md::7379dab817f0": "2026-09-23",  # Owner-facing build readout (#3691: `scripts/build_platform_state.py` → `site/data/platform
    "docs/PROPORTIONALITY.md::fb3f5918b14c": "2026-09-23",  # MCP surface index + miss log (#3668/#3674: `mcp/surface_index.py` AST-derived from `site_a
    "docs/PROPORTIONALITY.md::1367ab6801d3": "2026-09-23",  # Cost-bearing-surface baseline ratchet (#3374 R1: the `cost_surface` plane in `model/platfo
    "docs/PROPORTIONALITY.md::c407e86338cb": "2026-09-23",  # Per-feature AI budget ledger (#3374 R3: `scripts/ai_budget_ledger.py` + `tests/test_ai_bud
    "docs/PROPORTIONALITY.md::ac86519cb3e5": "2026-09-23",  # MoM close delta clause (#3374 R2: `doc_facts_ops.monthly_close_driver_hits`, wired into `s
    "docs/PROPORTIONALITY.md::265c47b722ad": "2026-09-23",  # Per-door audience instrumentation (#3376: the bounded `Door` dimension on `LifePlatform/Tr
    "docs/PROPORTIONALITY.md::1e9cfc4a1c46": "2026-09-23",  # Reject-only production-gate lease steward (#3422, carried by the #3021 janitor: `scripts/c
    "docs/PROPORTIONALITY.md::d5c3a89291ff": "2026-09-23",  # Compute-pipeline liveness heartbeat (#3473: `compute-pipeline-stale-heartbeat` in the extr
    "docs/PROPORTIONALITY.md::284dd0a21eeb": "2026-09-23",  # Reset doc-gate sweep (#3477: `deploy/restart_verify_gates.py`, the final sub-script of `re
    "docs/PROPORTIONALITY.md::755b88a6b720": "2026-09-23",  # Co-owned computed_metrics write contract + ACWR dead-man (#3443: `compute/computed_metrics
    "docs/PROPORTIONALITY.md::c64e931a6e71": "2026-09-23",  # Coach-nudge write ordering + ledger dead-man (#3569: `floats_to_decimal` at `coach_nudge_l
    "docs/PROPORTIONALITY.md::6d562b6789c2": "2026-09-23",  # Additive-IAM CI gate (#2834: `deploy/iam_additive_gate.py` + the Plan/Deploy wiring in `ci
    "docs/PROPORTIONALITY.md::a340b91a23cf": "2026-09-23",  # CDK cfn-exec permissions boundary (#3340: `infra/iam/cdk-cfn-exec-boundary.boundary.json`,
    "docs/PROPORTIONALITY.md::800578a1670c": "2026-09-23",  # CloudWatch custom-metric estate (#2837: `deploy/emf_namespace_ledger.py` + `emf_series_cen
    "docs/PROPORTIONALITY.md::023bd9654c2b": "2026-09-23",  # Coherence sentinel + canonical-facts contracts
    "docs/PROPORTIONALITY.md::c8ac9622f08e": "2026-09-23",  # Permanence archive (nightly public snapshot + continuity switch, #2572)
    "docs/PROPORTIONALITY.md::049a84f5f929": "2026-09-23",  # Gate census + can-it-fail proofs (epic #2578)
    "docs/PROPORTIONALITY.md::ce2cc37a03cb": "2026-09-23",  # Proportionality-ledger wrap gate (`check_proportionality_ledger.py`, #2380/#2761)
    "docs/PROPORTIONALITY.md::ba1d1a7dcb21": "2026-09-23",  # Handover line assertion (`check_handover_lines.py`, #3006)
    "docs/PROPORTIONALITY.md::39324ffa3926": "2026-09-23",  # Batched wrap-gate runner (`wrap_gates.py`, #3007)
    "docs/PROPORTIONALITY.md::3d157ca93899": "2026-09-23",  # Operating calendar + ritual dead-man (#2832: `scripts/operating_calendar.py`, daily `opera
    "docs/PROPORTIONALITY.md::24a6f81eedc4": "2026-09-23",  # Prediction-gradeability contract (#3046: `prediction_emission.py` gradeable_by stamp, `Gra
    "docs/PROPORTIONALITY.md::c5a07e11ca4e": "2026-09-23",  # Kernel conformance guard (#2844)
    "docs/PROPORTIONALITY.md::6c3fb2ddec27": "2026-09-23",  # System model + drift gate (#2845)
    "docs/PROPORTIONALITY.md::6f326cd302ce": "2026-09-23",  # Pre-merge full unit suite + duration instruments (#3025, folding #2692: `full-suite` job,
    "docs/PROPORTIONALITY.md::83bc71b4aa43": "2026-09-23",  # Deploy-critical lane import guard (#2758)
    "docs/PROPORTIONALITY.md::c201a7a55901": "2026-09-23",  # 8-coach board + stance engine + orchestrator
    "docs/PROPORTIONALITY.md::117e8cfd2ed0": "2026-09-23",  # Coach feedback loop (nudges #1382, docket #1386, dossier #1387, review pack #1698, calibra
    "docs/PROPORTIONALITY.md::ef753be80cbb": "2026-09-23",  # Budget governor + budget_guard
    "docs/PROPORTIONALITY.md::5902c59a756c": "2026-09-23",  # Freshness / ingest-liveness / reconciliation detectors
    "docs/PROPORTIONALITY.md::9eaeb32c6e01": "2026-09-23",  # Character engine + sheet
    "docs/PROPORTIONALITY.md::8a86d8394e7d": "2026-09-23",  # Derived-artifact registry + lane guard (`tests/derived_artifact_registry.py`, epic #2986)
    "docs/PROPORTIONALITY.md::3734d7cb3199": "2026-09-23",  # Deploy guardrails (clobber guard, postflight, drift checks, one-bundle rule, **site-rollba
    "docs/PROPORTIONALITY.md::239f36741527": "2026-09-23",  # Weekly Panel podcast pipeline
    "docs/PROPORTIONALITY.md::7a2d90819343": "2026-09-23",  # Reading pillar (2 GSIs, tools, page)
    "docs/PROPORTIONALITY.md::bc85291cdf44": "2026-09-23",  # MCP server (76 tools post-#395 prune — re-derived 2026-08-27 from `sync_doc_metadata._auto
    "docs/PROPORTIONALITY.md::d3fa21a5f948": "2026-09-23",  # Conversation channel (chat-journey ADR-141/142, journal quotes, intake)
    "docs/PROPORTIONALITY.md::b5c92d5629ca": "2026-09-23",  # Paging channel (ADR-143, ≤5-alarm P1 set)
    "docs/PROPORTIONALITY.md::776bffcd45b6": "2026-09-23",  # Stats/forecast machinery (stats_core, hypothesis tester, calibration ledger)
    "docs/PROPORTIONALITY.md::19a6e80f3a83": "2026-09-23",  # personal-baselines monthly compute
    "docs/PROPORTIONALITY.md::cd83a79f7c8e": "2026-09-23",  # AI QA gates — vision (`visual_ai_qa`, Bedrock semantic screenshots) + prose (`reader_truth
    "docs/PROPORTIONALITY.md::a6b487da4be0": "2026-09-23",  # Required pre-merge lane (ADR-148 + the structural-gate extension, #1662/#2372-adjacent)
    "docs/PROPORTIONALITY.md::50d9e6b78f81": "2026-09-23",  # Module-size ratchets ×2 (1200-line hard ceiling + BASELINE no-grow, #1665)
    "docs/PROPORTIONALITY.md::8f8f1f3e90e9": "2026-09-23",  # Recall corpus writer + freshness watcher (semantic_recall, #1384/ADR-150)
    "docs/PROPORTIONALITY.md::6093299006a7": "2026-09-23",  # The review estate — one `/review <lens>` spine, seven lenses (full, accuracy, craft, sdlc,
    "docs/PROPORTIONALITY.md::f4440ded74fe": "2026-09-23",  # golden-brief-eval workflow
    "docs/PROPORTIONALITY.md::66b479815315": "2026-09-23",  # Privacy-tier field registry + consumer gate (`lambdas/privacy/field_tiers.py`, `tests/priv
    "docs/PROPORTIONALITY.md::e9e840de210d": "2026-09-23",  # Reader-truth debt ledger (`tests/truth_baseline.json`, #2956)
    "docs/PROPORTIONALITY.md::a3b9816c7206": "2026-09-23",  # Chronicle / Weekly-Signal delivery dead-men (#2820)
    "docs/PROPORTIONALITY.md::40c65ca28322": "2026-09-23",  # Alarm flap detector in the wrap citation gate (#2912)
    "docs/PROPORTIONALITY.md::a09d1fb22f89": "2026-09-23",  # Producer↔gate cron mirror check (#2818)
    "docs/PROPORTIONALITY.md::0b15797ec3c1": "2026-09-23",  # Nightly edge-429 observation (#3058: qa-smoke `ratelimit:edge_429`, `lambdas/operational/q
    "docs/PROPORTIONALITY.md::6cbc03da2ae4": "2026-09-23",  # Budget-integrity fail-closed channel (#3059: `FAIL_CLOSED_FEATURES` in budget_guard + `bud
    "docs/PROPORTIONALITY.md::86acefeccbad": "2026-09-23",  # Grant-enumeration drift sweep (#2824: `tests/grant_enumeration.py` + `tests/test_grant_enu
    "docs/PROPORTIONALITY.md::2e4528d09321": "2026-09-23",  # Public-claims registry (#3042 Phase D2: `tests/public_claims_registry.py`, `tests/test_pub
    "docs/PROPORTIONALITY.md::5295b568e33b": "2026-09-23",  # Architect operator leg (#2849 leg 1: cloud routine `architect-operator-2849`, `docs/OPERAT
    "docs/PROPORTIONALITY.md::4b7070c4836a": "2026-09-23",  # Idempotency census + send ledger (DIL-025: `docs/IDEMPOTENCY.md`, `lambdas/common/send_led
    "docs/PROPORTIONALITY.md::d6e758d70204": "2026-09-23",  # S3 lifecycle declared-vs-live drift assertion (DIL-026/#2799: `deploy/s3_lifecycle.json`,
    "docs/PROPORTIONALITY.md::d4d7887e7840": "2026-09-23",  # Isolated `raw/` backup — CRR to us-east-2 + its weekly assertion (#3042 DIL-027: `cdk/stac
    "docs/PROPORTIONALITY.md::3462e23e53ba": "2026-09-23",  # Compute source-completeness contract (#3049/DIL-024: `lambdas/common/input_manifest.py`, s
    "docs/PROPORTIONALITY.md::7f219514d27a": "2026-09-23",  # Merge train (`deploy/merge_train.sh`, #3104)
    "docs/PROPORTIONALITY.md::7a5d854bedc9": "2026-09-23",  # Clinical-lite hazard gate (`lambdas/ai/safety_contract.py` + `_req.hazard_gate`, #3050/DIL
    "docs/PROPORTIONALITY.md::b2c4f84770f3": "2026-09-23",  # Pair-seam conformance guard (`tests/pair_seam_guard_lib.py` + residue ledger, #2847 box 4
    "docs/PROPORTIONALITY.md::814ada4a5061": "2026-09-23",  # DynamoDB TTL declared-vs-live parity (`check_dynamodb_ttl` in `deploy/drift_sentinel.py`,
    "docs/PROPORTIONALITY.md::e6c4c1a74884": "2026-09-23",  # Security-tier log-retention declared-vs-live parity, every region (#3278: registry `cdk/st
    "docs/PROPORTIONALITY.md::14f1ddda2e18": "2026-09-23",  # Producer/consumer pair-contract framework (`tests/pair_contract*.py`, #2847)
    "docs/PROPORTIONALITY.md::db1d9a3473cf": "2026-09-23",  # Deploy-race convergence gate (`deploy/deploy_convergence.py`, #2978)
    "docs/PROPORTIONALITY.md::26962cedbcb4": "2026-09-23",  # Lambda enrollment kernel (`cdk/stacks/lambda_enrollment.py` + the outside-constructor ratc
    "docs/PROPORTIONALITY.md::215d1272f2fc": "2026-09-23",  # Reader-audience first-red alarm escalation (`scripts/platform_model_alarms.py::READER_AUDI
    "docs/PROPORTIONALITY.md::2422dbddf311": "2026-09-23",  # Security standing instruments (#3620): salted reader `ip_hash`, private-prefix deny assert
    "docs/PROPORTIONALITY.md::5e9e5f56f3d2": "2026-09-23",  # No-reset-world provenance stamping (#4040): the widened `data:coach_ensemble_phase_stamp_c
}
