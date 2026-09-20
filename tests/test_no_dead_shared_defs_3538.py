"""tests/test_no_dead_shared_defs_3538.py — #3538: nothing dead rides in every bundle.

THE COST. Under the one-bundle rule (#781, CONVENTIONS §1) ``deploy/build_bundle.py``'s
``stage_tree()`` copies the ENTIRE ``lambdas/`` tree into EVERY Lambda zip — ~104 of them
(ADR-146, #1653: "the bundle stages the tree at the zip root"). A public function nothing
calls is not merely clutter, it is carried ~104 times, appears in every reader's grep, and
reads as API — for ANY package under ``lambdas/``, not just ``common/`` and ``ai/``.
#1239 established the discipline and deleted eight such functions, but scoped its guard to
the word "intelligence" (a fixed list of 8 named symbols, not a general scan); #3538 added
a general AST scan but still hard-typed its package list to ``("lambdas/common",
"lambdas/ai")`` — 2 of the ~15 packages actually staged. #3609 box 2 (the forensic RCA's
principal ROW4, docs/reviews/FORENSIC_RCA_2026-09-05.md) closes that gap: the package list
below is DERIVED from ``build_bundle.stage_tree()``'s own output rather than hand-typed, so
a new package under ``lambdas/`` is covered the day it is created, with zero code change
here. Widening the scan from 2 packages to ~15 surfaced 101 previously-invisible
unreferenced defs (recorded below, dated 2026-09-19) — each is either a genuinely orphaned
function (0 references anywhere, not even a test) or a test-only helper with no production
caller yet. None are deleted in this PR: this is a STRUCTURAL fix (the scan's own reach),
and a bulk deletion campaign across a dozen packages — several owned by other concurrent
lanes the night this landed — is its own scoped follow-up, not a side effect of fixing the
package list. The registry entries below say so explicitly and name the evidence.

WHAT IS FLAGGED. A top-level, non-underscore ``def``/``async def`` in any package
``build_bundle.stage_tree()`` stages (i.e. any top-level ``lambdas/<pkg>``) with ZERO
references across the live surface:

    lambdas/  mcp/  deploy/  scripts/  cdk/  and the harnesses in tests/ that are
    not themselves tests (tests/visual_qa.py, tests/visual_ai_qa.py, …)

``tests/test_*.py`` is deliberately NOT live surface — a function whose only caller is
its own unit test is the thing this guard exists to find. The harnesses ARE live: they
run in CI as gates, and excluding them would have made this guard delete working code
(see ``attributed_to`` below).

HOW A REFERENCE IS COUNTED — both ways, because either alone is wrong:
  * AST (``Name`` load, attribute access, ``import``/``from`` alias). A mention inside a
    COMMENT is not a reference; a text scan counts it and calls dead code live.
    ``budget_guard.hard_stopped`` is the live specimen: its only non-test "reference" in
    the repo is a sentence in scripts/gate_census_enforcement.py's prose.
  * String literals. ``getattr(mod, "name")`` is invisible to AST, and this repo does it:
    ``tests/visual_ai_qa.py`` reaches ``bedrock_client.attributed_to`` by string. An
    AST-only scan calls that function dead, and deleting it breaks the visual-QA gate —
    the exact "string/getattr dispatch is invisible to the scan" caveat #3538 carries.

THE ALLOWLIST IS SHRINK-ONLY. An entry for a def the scan no longer flags fails, so it
can only get smaller. Prefer deletion; an entry has to say what would call the function
— or, for the #3609 widen's batch, honestly say that NOTHING does (see above).
"""

import ast
import os
import pathlib
import sys
import tempfile

_TESTS = pathlib.Path(__file__).resolve().parent
_REPO = _TESTS.parent

_DEPLOY_DIR = str(_REPO / "deploy")
if _DEPLOY_DIR not in sys.path:
    sys.path.insert(0, _DEPLOY_DIR)
import build_bundle  # noqa: E402


def _staged_package_names() -> tuple[str, ...]:
    """The scan's package list, read from ``build_bundle.stage_tree()``'s OWN output —
    not a hand-typed tuple (#3609 box 2). Actually invoking ``stage_tree()`` (into a
    scratch dir, same pattern as tests/test_deploy_bundle_paths.py) means a change to
    what the bundle excludes (``build_bundle.EXCLUDE_DIRS``) or a brand-new package
    dropped under ``lambdas/`` changes this list automatically, with no edit here.
    Non-Python staged directories (``config/``, ``fonts/``) fall out on their own: they
    carry no top-level ``def`` for ``_public_top_level_defs()`` to find."""
    with tempfile.TemporaryDirectory() as td:
        out = build_bundle.stage_tree(os.path.join(td, "stage"))
        names = sorted(p.name for p in pathlib.Path(out).iterdir() if p.is_dir())
    return tuple(f"lambdas/{name}" for name in names)


SCAN_PACKAGES = _staged_package_names()
LIVE_DIRS = ("lambdas", "mcp", "deploy", "scripts", "cdk")

# "package/module.py:name" -> what actually calls it. Deletion is the default; an entry
# here is a claim about a live caller the AST+string scan cannot see.
#
# Three shared defs whose only callers are deploy-time tools are NOT flagged and need no
# entry, because deploy/ and scripts/ are live surface here: token_alarm_window
# .window_for_genesis (deploy/restart_pipeline.py, deploy/restart_verify.py),
# record_text.coach_output_text (deploy/backfill_recall_embeddings.py) and
# request_validator.validate_source (deploy/dedup_source_records.py). That they ride in
# the bundle unused at RUNTIME is a packaging question (#781), not a dead-code one.
_BATCH_REASON = (
    "ADR-132 / #409: bedrock_batch ships the batch-inference MECHANISM deliberately "
    "unwired. Bedrock's hard floor is 100 records per job per model and measured volume "
    "is ~62 model calls/day across ALL producers mixed across models, so no producer can "
    "honestly submit a batch today — the module's own docstring is the decision and names "
    "batch_preflight() as the gate a future adopter calls first. This is a documented "
    "latent capability with full tests, not a leftover; deleting it is an ADR-132 reversal, "
    "not a dead-code cleanup. Revisit when a producer clears the 100-record floor."
)

ALLOWED_UNREFERENCED_SHARED_DEFS: dict[str, str] = {
    "lambdas/ai/bedrock_batch.py:build_jsonl_record": _BATCH_REASON,
    "lambdas/ai/bedrock_batch.py:submit_batch": _BATCH_REASON,
    "lambdas/ai/bedrock_batch.py:wait_for_batch": _BATCH_REASON,
    "lambdas/ai/bedrock_batch.py:retrieve_results": _BATCH_REASON,
    "lambdas/ai/bedrock_batch.py:run_or_fallback": _BATCH_REASON,
    "lambdas/ai/bedrock_batch.py:estimate_batch_savings": _BATCH_REASON,
    "lambdas/ai/ai_calls.py:call_training_coach_v2": (
        "one seat of a symmetric ADR-153 coach family (sleep / nutrition / training / mind, "
        "each a 3-line `_run_coach_v2_pipeline(<seat>, ...)` wrapper). The daily-brief tests "
        "patch it BY NAME as part of the brief's coach roster "
        "(tests/test_daily_brief_grounding_and_hold.py: 'ADR-153: call_training_coach_v2 "
        "stays mocked here even though the seat is...'), so removing one member breaks the "
        "roster and leaves an asymmetric family. Retiring a coach seat is a coaching-team "
        "decision, not a dead-code sweep."
    ),
    "lambdas/common/email_identity.py:is_verified_sender": (
        "the predicate half of #3568's sending-vocabulary registry, and the thing its gate "
        "asserts with. Runtime code consumes the registry's CONSTANTS (CHRONICLE_SENDER et al. "
        "are read by five senders and, at synth time, by email_stack/web_stack/role_policies_base); "
        "the FUNCTIONS exist so tests/test_email_sender_identity_3568.py can decide whether an "
        "arbitrary From address is on an SES-verified domain — which is the whole check. Deleting "
        "it does not shrink the surface, it moves the flag: with is_verified_sender gone, "
        "sender_domain becomes the unreferenced def (verified by removing it and re-running this "
        "test). Same shape as structured_output_config below — half of a live contract test, not "
        "a leftover."
    ),
    "lambdas/ai/bedrock_client.py:structured_output_config": (
        "half of a live CONTRACT test, not a leftover. #1385 AC4 "
        "(tests/test_whole_life_context_1385.py) uses it to build the body it then feeds "
        "through invoke() to prove the chokepoint FORWARDS `output_config` and STRIPS "
        "`model`. Delete the builder and the only proof that Bedrock Structured Outputs "
        "survive the chokepoint goes with it."
    ),
    # `guarded_send_raw_email` was allowlisted here as an unreferenced member of a SAFETY
    # SET — kept deliberately so the next raw-email sender would find a sanctioned gate
    # waiting rather than reach for boto3. It had no caller from the day it was written.
    # #3741's recap card is that sender: the card is a MIME message with a PNG attachment,
    # so it must go through send_raw_email, and it goes through the guard. The entry is
    # deleted rather than reworded because the scan no longer flags the def at all — the
    # allowlist is for definitions nothing references, and something references it now.
    "lambdas/common/input_manifest.py:reset_run_manifests": (
        "test-support for a LIVE contract class. tests/test_input_manifest_contract_3049.py"
        "::TestChokepoint calls it to clear the per-run manifest cache between cases; "
        "without it the whole class errors at setup and DIL-025's chokepoint contract goes "
        "dark. Same misplacement as prompt_cache's helpers — it belongs on the test side "
        "rather than in ~104 bundles, and moving it is its own change."
    ),
    "lambdas/common/quarter_utils.py:quarter_key": (
        "the INVERSE half of a round-trip contract: tests/test_quarter_utils.py"
        "::test_quarter_bounds_round_trip asserts quarter_key(quarter_bounds(q)[0]) == q and "
        "that the exclusive end lands in the NEXT quarter. quarter_bounds IS live "
        "(lambdas/compute/coach_memoir_lambda.py), so deleting its inverse would leave the "
        "live function's boundary math asserted only against hand-typed dates."
    ),
    "lambdas/ai/prompt_cache.py:clears_floor": (
        "the COMPUTATION of a live gate, not a leftover. "
        "tests/test_prompt_cache_decisions_3085.py asserts "
        "`clears_floor(the real prompt, the real model) == entry['engaged']` for every "
        "recorded caller — deleting it deletes the only thing that checks the "
        "CACHING_DECISIONS ledger against the models' actual minimum prefixes (#3085). It "
        "is misplaced (it belongs on the test side, where it would not ride ~104 bundles), "
        "not unused; moving it is a separate change with a real regression risk."
    ),
    "lambdas/common/subscriber_cadence.py:delivery_weekdays": (
        "the DERIVATION half of #3564's cadence contract, arriving with the merge of "
        "origin/main. tests/test_subscriber_cadence_promise_3564.py"
        "::test_promise_names_every_delivery_weekday_and_the_derived_count iterates it to "
        "assert the rendered promise names every day a subscriber can actually hear from "
        "the platform on — the exact disagreement #3564 was filed for. `promise_sentence` "
        "IS live (email_subscriber_lambda, subscriber_onboarding_lambda, "
        "qa_check_subscriber_promise); deleting the set the promise is checked AGAINST "
        "would leave the promise asserted only against itself."
    ),
    "lambdas/common/subscriber_cadence.py:chronicle_weekday": (
        "the second seat of a symmetric two-sender family — `signal_weekday()` (live: "
        "email_subscriber_lambda + subscriber_onboarding_lambda both render 'see you "
        "<day>' from it) and this, the chronicle's own cron day. Both are one line over "
        "`required_weekday(sender(<id>).cron)`; keeping only the seat that happens to have "
        "a caller today is the shrink-a-safety-set anti-pattern (#2610) that the "
        "send_guard entry above records. Retiring a subscriber sender is an email-cadence "
        "decision (#3564), not a dead-code sweep."
    ),
    "lambdas/ai/prompt_cache.py:cached_prefix_blocks": (
        "same class as clears_floor: the byte-stable prefix assembler the #2888 tests "
        "drive directly. Its production callers are the ones #2888/#3085 are still "
        "converting; the record of which callers have and have not engaged caching lives "
        "in CACHING_DECISIONS in this same module."
    ),
    # ── #3609 box 2: the widened-scan batch (101 entries, dated 2026-09-19). ────────
    #
    # SCAN_PACKAGES went from 2 hand-typed packages (common, ai) to ~15 derived from
    # build_bundle.stage_tree()'s own output (ADR-146: the bundle stages the WHOLE
    # lambdas/ tree, so every package ships in every one of the ~104 zips, not just
    # its own handler's). Every entry below was found by that widen and is registered
    # (not deleted) in this structural PR — each states the actual evidence a repo-wide
    # grep found (a specific test, a comment-only mention, or nothing at all). The
    # ~19 entries reading "zero references ANYWHERE" are the strongest deletion
    # candidates; deleting them is a separate, scoped follow-up (named in the #3609 PR
    # body) rather than bundled into the guard-mechanism fix itself.
    "lambdas/coach/board_loader.py:build_panel_prompt": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/coach/board_loader.py:get_matthew_context": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/coach/board_loader.py:get_member_color": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/coach/coach_checkin.py:recent_checkins_block": (
        "#3609 box 2 widen: exercised by tests/test_coach_checkin_tools.py; named only in a COMMENT in lambdas/ai/platform_memory.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/coach/coach_corrections.py:get_correction": (
        "#3609 box 2 widen: exercised only by tests/test_coach_corrections.py (also named in docs/SCHEMA.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/coach/coach_corrections.py:stale_cycle_corrections": (
        "#3609 box 2 widen: exercised only by tests/test_coach_corrections.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/coach/coach_register.py:compose_coach_prompt": (
        "#3609 box 2 widen: exercised by tests/test_coach_register_1390.py; named only in a COMMENT in scripts/v4_build_tone.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/coach/coach_register.py:extract_deterministic_slice": (
        "#3609 box 2 widen: exercised only by tests/test_coach_register_1390.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/coach/coach_register.py:is_register": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/coach/coach_sim_scoreboard.py:read_limitations": (
        "#3609 box 2 widen: exercised only by tests/test_coach_sim_scoreboard_2539.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/coach/critics.py:with_notes_block": (
        "#3609 box 2 widen: exercised only by tests/test_plan_critics_3752.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/coach/persona_registry.py:board_personas": (
        "#3609 box 2 widen: exercised only by tests/test_persona_registry.py (also named in docs/ADD_A_COACH.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/coach/persona_registry.py:by_coach_config_key": (
        "#3609 box 2 widen: exercised only by tests/test_persona_registry.py (also named in docs/ADD_A_COACH.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/coach/persona_registry.py:by_short_id": (
        "#3609 box 2 widen: exercised only by tests/test_persona_registry.py (also named in docs/ADD_A_COACH.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/coach/spiral_breaker.py:is_suppressed": (
        "#3609 box 2 widen: exercised only by tests/test_spiral_breaker.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/compute/adaptive_mode_lambda.py:fetch_recent_dates": (
        "#3609 box 2 widen: exercised only by tests/test_adaptive_mode_behavior.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/content/journal_quotes.py:is_markable": (
        "#3609 box 2 widen: exercised only by tests/test_journal_quotes_1568.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/content/recap_deliver.py:caption_for": (
        "#3609 box 2 widen: exercised only by tests/test_recap_deliver_3747.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/emails/panelcast_ident.py:render_ident": (
        "#3609 box 2 widen: exercised only by tests/test_panelcast_ident.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/emails/panelcast_ident.py:render_outro": (
        "#3609 box 2 widen: exercised only by tests/test_panelcast_ident.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/emails/partner_email_lambda.py:weight_sentence": (
        "#3609 box 2 widen: exercised only by tests/test_partner_email_lambda.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/calibration_core.py:classify_calibration_rows": (
        "#3609 box 2 widen: exercised only by tests/test_calibration_core_parity.py (also named in oss/calibration-core/src/calibration_core.py); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/canonical_facts.py:numeric_facts": (
        "#3609 box 2 widen: exercised only by tests/test_canonical_facts.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/config_anchor_registry.py:anchors_for_treatment": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/experiment/eyeball_calibration.py:build_estimate_item": (
        "#3609 box 2 widen: exercised only by tests/test_eyeball_isolation_1390.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/eyeball_calibration.py:build_grade_item": (
        "#3609 box 2 widen: exercised only by tests/test_eyeball_isolation_1390.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/eyeball_calibration.py:estimate_from_photo": (
        "#3609 box 2 widen: exercised only by tests/test_eyeball_isolation_1390.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/eyeball_calibration.py:estimated_monthly_cost": (
        "#3609 box 2 widen: exercised only by tests/test_eyeball_isolation_1390.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/eyeball_calibration.py:grade_against_truth": (
        "#3609 box 2 widen: exercised only by tests/test_eyeball_isolation_1390.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/eyeball_calibration.py:list_estimates": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/experiment/eyeball_calibration.py:write_estimate": (
        "#3609 box 2 widen: exercised only by tests/test_eyeball_isolation_1390.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/eyeball_calibration.py:write_grade": (
        "#3609 box 2 widen: exercised only by tests/test_eyeball_isolation_1390.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/methods_registry.py:get_registry": (
        "#3609 box 2 widen: exercised only by tests/test_methods_registry.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/methods_registry.py:get_stat": (
        "#3609 box 2 widen: exercised only by tests/test_conversation_enrichment_1577.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/methods_registry.py:verify_fingerprints": (
        "#3609 box 2 widen: exercised only by tests/test_methods_registry.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/experiment/phase_taxonomy.py:is_wipeable": (
        "#3609 box 2 widen: exercised by tests/test_phase_taxonomy.py; named only in a COMMENT in deploy/reconcile_provenance_2026_09.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/experiment/phase_taxonomy.py:never_touch": (
        "#3609 box 2 widen: exercised only by tests/test_mcp_tools_labs_behavior.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/health/adherence_calc.py:find_alias_candidates": (
        "#3609 box 2 widen: exercised by tests/test_adherence_calc.py; named only in a COMMENT in deploy/config_ownership_audit.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/health/sick_day_checker.py:delete_sick_day": (
        "#3609 box 2 widen: exercised only by tests/test_shared_modules.py (also named in docs/archive/CHANGELOG_v341.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/health/sick_day_checker.py:write_sick_day": (
        "#3609 box 2 widen: exercised by tests/test_shared_modules.py; named only in a COMMENT in mcp/layer_status.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/health/vocal_metrics.py:vocal_metrics_state": (
        "#3609 box 2 widen: exercised only by tests/test_vocal_metrics.py (also named in docs/SCHEMA.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/ingestion/ingestion_validator.py:list_supported_sources": (
        "#3609 box 2 widen: exercised only by tests/test_shared_modules.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/ingestion/ingestion_validator.py:validate_and_write": (
        "#3609 box 2 widen: exercised by tests/test_ddb_patterns.py; named only in a COMMENT in lambdas/compute/daily_metrics_compute_lambda.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/ingestion/source_registry.py:day_key_frame_consequence_for": (
        "#3609 box 2 widen: exercised only by tests/test_ingestion_day_key_derivation_3666.py (also named in docs/audits/TD-19_DATE_PARTITION_AUDIT.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/ingestion/source_registry.py:manual_hae_datatype_keys": (
        "#3609 box 2 widen: exercised only by tests/test_manual_source_reliability_746.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/ingestion/source_registry.py:manual_method_source_ids": (
        "#3609 box 2 widen: exercised by tests/test_source_registry_coverage_3669.py; named only in a COMMENT in lambdas/ingestion/source_registry_closed_social.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/ingestion/source_registry.py:oauth_digest_only_source_ids": (
        "#3609 box 2 widen: exercised by tests/test_oauth_alarm_coverage.py; named only in a COMMENT in cdk/stacks/monitoring_stack.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/ingestion/source_registry.py:provider_reconcile_source_ids": (
        "#3609 box 2 widen: named in docs/DECISIONS.md. No production caller found; registered pending owner triage."
    ),
    "lambdas/ingestion/source_registry.py:qa_required_oauth_source_ids": (
        "#3609 box 2 widen: exercised only by tests/test_oauth_alarm_coverage.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/ingestion/source_registry.py:raw_date_key_candidates": (
        "#3609 box 2 widen: exercised only by tests/test_dil028_raw_layout_replay.py (also named in docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/ingestion/source_registry.py:retired_source_ids": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/ingestion/source_registry.py:unregistered_source_partitions": (
        "#3609 box 2 widen: exercised only by tests/test_source_registry_coverage_3669.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/ingestion/source_registry.py:utc_day_key_source_ids": (
        "#3609 box 2 widen: exercised by tests/test_freshness_age_frame_3257.py; named only in a COMMENT in lambdas/ingestion/whoop_lambda.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/ingestion/strava_population.py:is_decided": (
        "#3609 box 2 widen: exercised only by tests/test_strava_population.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/intelligence/intelligence_common.py:complete_action": (
        "#3609 box 2 widen: exercised only by tests/test_intelligence_common_behavior.py (also named in docs/MCP_TOOL_AUDIT.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/intelligence/intelligence_common.py:compute_credibility": (
        "#3609 box 2 widen: exercised by tests/test_coach_intelligence.py; named only in a COMMENT in lambdas/experiment/calibration_core.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/intelligence/intelligence_common.py:get_action_history": (
        "#3609 box 2 widen: exercised only by tests/test_intelligence_common_behavior.py (also named in docs/archive/intelligence-layer/INTELLIGENCE_LAYER_V2_SPEC.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/intelligence/intelligence_common.py:get_open_actions": (
        "#3609 box 2 widen: exercised only by tests/test_intelligence_common_behavior.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/intelligence/intelligence_common.py:update_prediction_status": (
        "#3609 box 2 widen: exercised only by tests/test_intelligence_common_behavior.py (also named in docs/CHANGELOG.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/operational/continuity_watch.py:liveness_role": (
        "#3609 box 2 widen: exercised only by tests/test_continuity_watch_1400.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/operational/continuity_watch.py:watched_sources": (
        "#3609 box 2 widen: exercised only by tests/test_continuity_watch_1400.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/operational/reader_truth_qa.py:check_midword_truncation": (
        "#3609 box 2 widen: exercised only by tests/test_reader_truth_qa.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/operational/reader_truth_qa.py:check_vitals_freshness": (
        "#3609 box 2 widen: exercised only by tests/test_reader_truth_qa.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/broadcast_sensitivity_gate.py:cleared_filter_expression": (
        "#3609 box 2 widen: exercised by tests/test_broadcast_sensitivity_gate_1673.py; named only in a COMMENT in lambdas/web/site_api_social.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/privacy/broadcast_sensitivity_gate.py:filter_cleared": (
        "#3609 box 2 widen: exercised by tests/test_broadcast_sensitivity_gate_1673.py; named only in a COMMENT in lambdas/web/site_api_social.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/privacy/broadcast_sensitivity_gate.py:held_filter_expression": (
        "#3609 box 2 widen: exercised only by tests/test_broadcast_sensitivity_gate_1673.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/broadcast_sensitivity_gate.py:is_held": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/privacy/broadcast_sensitivity_gate.py:review_record": (
        "#3609 box 2 widen: exercised only by tests/test_broadcast_sensitivity_gate_1673.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/content_filter_channel.py:last_channel_errors": (
        "#3609 box 2 widen: exercised only by tests/test_content_filter_channel_errors_2655.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/content_filter_channel.py:reset_cache": (
        "#3609 box 2 widen: exercised by tests/test_between_chronicle_scrub_2654.py; named only in a COMMENT in lambdas/privacy/privacy_guard.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/privacy/diary_claims.py:is_gradable_record": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/privacy/diary_publish.py:engagement_by_entry": (
        "#3609 box 2 widen: exercised only by tests/test_diary_publish_1845.py (also named in docs/SCHEMA.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/diary_publish.py:format_publish_log_row": (
        "#3609 box 2 widen: exercised only by tests/test_diary_publish_1845.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/field_tiers.py:is_publishable": (
        "#3609 box 2 widen: exercised only by tests/test_privacy_tier_wiring_2803.py (also named in docs/DECISIONS.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/field_tiers.py:source_tier_of": (
        "#3609 box 2 widen: exercised only by tests/test_privacy_tier_wiring_2803.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/field_tiers.py:tier_of": (
        "#3609 box 2 widen: exercised only by tests/test_privacy_tier_wiring_2803.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/privacy_guard.py:reset_vocabulary_cache": (
        "#3609 box 2 widen: exercised only by tests/test_between_chronicle_scrub_2654.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/social_consent.py:is_reactable": (
        "#3609 box 2 widen: exercised only by tests/test_social_coach_reaction_1675.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/social_provenance.py:filter_human": (
        "#3609 box 2 widen: exercised only by tests/test_social_provenance_1670.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/privacy/social_provenance.py:human_origin_filter_expression": (
        "#3609 box 2 widen: exercised by tests/test_social_provenance_1670.py; named only in a COMMENT in lambdas/privacy/broadcast_sensitivity_gate.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/reading/horizons_calibration.py:is_publishable_reaction": (
        "#3609 box 2 widen: exercised by tests/test_horizons_calibration_1708.py; named only in a COMMENT in lambdas/web/site_api_reading.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/reading/reading_store.py:current_horizon_pick": (
        "#3609 box 2 widen: exercised only by tests/test_horizons.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/reading/reading_store.py:get_note": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/training/hevy_common.py:fetch_events_since": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/training/hevy_common.py:ingest_workout_by_id": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/training/hevy_common.py:load_cursor": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/training/hevy_common.py:save_cursor": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/training/hevy_write_client.py:get_workout_events": (
        "#3609 box 2 widen: exercised only by tests/test_hevy_write_client.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/training/routine_repo.py:get_version": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/training/routine_repo.py:lookup_hevy_id": (
        "#3609 box 2 widen: exercised only by tests/test_routine_repo.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/training/training_notes.py:compute_deviation": (
        "#3609 box 2 widen: exercised only by tests/test_training_notes.py (also named in docs/BACKLOG.md); no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/web/card_engine.py:draw_uncertainty": (
        "#3609 box 2 widen: exercised by tests/test_card_engine.py; named only in a COMMENT in scripts/doc_facts_og.py (not an actual call — the AST scan correctly ignores prose mentions, same caveat as hard_stopped above). No production caller found; registered pending owner triage."
    ),
    "lambdas/web/card_engine.py:registered_types": (
        "#3609 box 2 widen: exercised only by tests/test_card_engine.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/web/fingerprint.py:fingerprint_svg": (
        "#3609 box 2 widen: exercised only by tests/test_fingerprint.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/web/recap_canvas.py:render_card": (
        "#3609 box 2 widen: exercised only by tests/test_recap_render_3744.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/web/recap_charts.py:draw_dots": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/web/recap_charts.py:draw_kv_row": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/web/recap_charts.py:draw_rule": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
    "lambdas/web/recap_templates.py:all_strings": (
        "#3609 box 2 widen: exercised only by tests/test_recap_templates_3745.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/web/recap_templates.py:copy_for": (
        "#3609 box 2 widen: exercised only by tests/test_recap_render_3744.py; no production caller found on the live surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + live tests/ harnesses) as of 2026-09-19. Registered pending owner triage (wire it in or retire it with its test) rather than deleted in this structural PR."
    ),
    "lambdas/web/site_api_common.py:get_request_route": (
        "#3609 box 2 widen (SCAN_PACKAGES now derives from build_bundle.stage_tree()'s own output, not a common/ai-only literal): zero references ANYWHERE in the repo for this def — not a test, not a doc, not even a comment. The strongest deletion candidate this widen surfaced; registered rather than deleted so the package-list fix stays a structural change and a follow-up owns the delete decision by name."
    ),
}


def _py_files(rel_dir: str):
    for root, _dirs, files in os.walk(_REPO / rel_dir):
        if "node_modules" in root or "cdk.out" in root:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                yield pathlib.Path(root) / name


def _live_surface() -> list[pathlib.Path]:
    """Every file whose reference to a shared def counts as a live use. tests/test_*.py
    is excluded on purpose; the tests/ HARNESSES are included because CI runs them."""
    files: list[pathlib.Path] = []
    for rel in LIVE_DIRS:
        files += list(_py_files(rel))
    files += [p for p in _py_files("tests") if not p.name.startswith("test_")]
    return files


def _public_top_level_defs() -> dict[str, tuple[str, int, int]]:
    """ "<module rel path>:<name>" -> (rel, first line, last line)."""
    out: dict[str, tuple[str, int, int]] = {}
    for rel_dir in SCAN_PACKAGES:
        for path in _py_files(rel_dir):
            rel = str(path.relative_to(_REPO))
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                    out[f"{rel}:{node.name}"] = (rel, node.lineno, node.end_lineno or node.lineno)
    return out


def _referenced_names(path: pathlib.Path) -> set[str]:
    """Every name this file references — AST loads/attributes/imports, PLUS string
    literals (getattr dispatch).

    A `def` statement is NOT a reference (ast.FunctionDef carries its name as a plain
    string, not a Name node), so a function is never kept alive by its own definition.
    An intra-module CALL is: if `run_or_fallback` calls `submit_batch`, submit_batch is
    referenced. That under-reports a wholly-dead cluster and never over-reports, which
    is the right direction for a guard whose remedy is deletion.
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    refs: set[str] = set()
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return refs
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            refs.add(node.id)
        elif isinstance(node, ast.Attribute):
            refs.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            refs.add(node.value)  # getattr(mod, "name") / a dispatch table key
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                refs.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                refs.add(alias.name.split(".")[0])
    return refs


def scan_dead_shared_defs() -> dict[str, str]:
    """ "<module>:<name>" -> a human-readable size, for every unreferenced public def."""
    defs = _public_top_level_defs()
    wanted = {key.split(":", 1)[1] for key in defs}
    referenced: set[str] = set()
    for path in _live_surface():
        referenced |= _referenced_names(path) & wanted
    return {
        key: f"{end - start + 1} lines at {rel}:{start}"
        for key, (rel, start, end) in defs.items()
        if key.split(":", 1)[1] not in referenced
    }


def test_no_dead_public_def_ships_in_every_bundle():
    """A public def in lambdas/common or lambdas/ai that nothing outside its own unit
    test calls is dead weight in ~104 bundles — delete it, or register a caller."""
    dead = scan_dead_shared_defs()
    unregistered = {k: v for k, v in dead.items() if k not in ALLOWED_UNREFERENCED_SHARED_DEFS}
    assert not unregistered, (
        "Public def(s) in the every-bundle packages with no reference anywhere on the live\n"
        "surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + the tests/ harnesses). Under the\n"
        "one-bundle rule these ship in ~104 Lambda zips and read as API. Delete them (with\n"
        "their unit tests), or add an entry to ALLOWED_UNREFERENCED_SHARED_DEFS naming what\n"
        "calls them:\n" + "\n".join(f"  {k}  ({v})" for k, v in sorted(unregistered.items()))
    )


def test_the_allowlist_has_no_dead_entries():
    dead = scan_dead_shared_defs()
    stale = sorted(k for k in ALLOWED_UNREFERENCED_SHARED_DEFS if k not in dead)
    assert not stale, f"ALLOWED_UNREFERENCED_SHARED_DEFS lists entr(ies) the scan no longer flags; delete them: {stale}"


def test_the_scan_counts_a_string_dispatch_as_a_reference():
    """The caveat that makes this guard safe to act on. ``tests/visual_ai_qa.py`` reaches
    ``bedrock_client.attributed_to`` through ``getattr(bedrock, "attributed_to", None)``.
    An AST-only scan reports it dead; deleting it breaks the visual-QA gate. Pin the
    live specimen, not a synthetic one — a synthetic proves the code path, this proves
    the repo still contains the hazard the code path exists for."""
    harness = _REPO / "tests" / "visual_ai_qa.py"
    assert (
        'getattr(bedrock, "attributed_to"' in harness.read_text()
    ), "the live string-dispatch specimen moved; re-verify this guard's string-literal branch against its replacement"
    assert "lambdas/ai/bedrock_client.py:attributed_to" not in scan_dead_shared_defs()


def test_the_scan_ignores_a_mention_in_a_COMMENT():
    """The inverse caveat. A grep-based scan counts prose. ``hard_stopped`` was named
    only in a sentence in scripts/gate_census_enforcement.py, which is why a text scan
    called it live while it had no caller at all."""
    src = "# hard_stopped is mentioned here in prose only\nx = 1\n"
    tree_refs = _referenced_names_from_source(src)
    assert "hard_stopped" not in tree_refs


def _referenced_names_from_source(src: str) -> set[str]:
    refs: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name):
            refs.add(node.id)
        elif isinstance(node, ast.Attribute):
            refs.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            refs.add(node.value)
    return refs


# ─────────────────────────────────────────────────────────────────────────────
# The second half of #3538: no module may FORK a common.* symbol behind ImportError.
#
# Seven modules carried `try: from common.numeric import floats_to_decimal / except
# ImportError: def floats_to_decimal(obj): ...`. Under the one-bundle rule the import
# ALWAYS resolves, so the fallback is unreachable — and it had silently diverged from
# the canonical implementation, which since #1656 maps NaN/Inf to None. If the import
# path ever did break, six of the seven would have written NaN into DynamoDB instead of
# raising. A fork that cannot run is not a safety net; it is a second definition nobody
# tests and nobody updates.


def _import_error_redefinitions() -> dict[str, list[str]]:
    """ "<rel path>" -> the names re-defined inside an `except ImportError:` handler
    whose matching `try:` imported them from a `common.*` module."""
    found: dict[str, list[str]] = {}
    for rel_dir in ("lambdas", "mcp"):
        for path in _py_files(rel_dir):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                imported = {
                    alias.asname or alias.name
                    for stmt in node.body
                    if isinstance(stmt, ast.ImportFrom) and (stmt.module or "").split(".")[0] == "common"
                    for alias in stmt.names
                }
                if not imported:
                    continue
                for handler in node.handlers:
                    names = {n.id for n in ast.walk(handler.type) if isinstance(n, ast.Name)} if handler.type else set()
                    if "ImportError" not in names and "ModuleNotFoundError" not in names:
                        continue
                    for sub in ast.walk(handler):
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name in imported:
                            found.setdefault(str(path.relative_to(_REPO)), []).append(sub.name)
    return found


def test_no_module_forks_a_common_symbol_behind_an_import_error():
    """A `common.*` symbol has exactly one definition. See the block comment above."""
    forks = _import_error_redefinitions()
    assert not forks, (
        "Module(s) re-define a `common.*` symbol inside `except ImportError:`. The\n"
        "one-bundle rule (#781) means that import always resolves, so the fork is dead —\n"
        "and it drifts: the seven floats_to_decimal forks removed at #3538 had all lost\n"
        "the canonical NaN/Inf -> None branch, so if the import path ever DID break they\n"
        "would have written NaN to DynamoDB rather than failed. Import it, and let a\n"
        "broken import break loudly:\n" + "\n".join(f"  {rel}: {', '.join(names)}" for rel, names in sorted(forks.items()))
    )


def test_the_import_error_fork_scan_fires_on_the_shape_it_removed(tmp_path):
    """Mutation proof against a scanner that silently matches nothing — in the exact
    shape the seven removed forks had, TYPE_CHECKING guard and all."""
    import ast as _ast

    forked = (
        "from typing import TYPE_CHECKING\n"
        "try:\n"
        "    from common.numeric import floats_to_decimal  # noqa: F401\n"
        "except ImportError:\n"
        "    if not TYPE_CHECKING:\n"
        "\n"
        "        def floats_to_decimal(obj):\n"
        "            return obj\n"
    )
    tree = _ast.parse(forked)
    hits = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Try):
            imported = {
                a.name for s in node.body if isinstance(s, _ast.ImportFrom) and (s.module or "").split(".")[0] == "common" for a in s.names
            }
            for h in node.handlers:
                for sub in _ast.walk(h):
                    if isinstance(sub, _ast.FunctionDef) and sub.name in imported:
                        hits.append(sub.name)
    assert hits == ["floats_to_decimal"], "the detection shape itself must match the removed fork"

    # ...and the prescribed replacement — a bare import — must not be flagged.
    plain = _ast.parse("from common.numeric import floats_to_decimal\n")
    assert not [n for n in _ast.walk(plain) if isinstance(n, _ast.Try)]
