"""tests/grounding_wiring.py — the derived grounding-gate surface registry (#1967).

WHY THIS EXISTS
---------------
``grounded_generation.grounding_findings()`` takes every gate class as an OPTIONAL
keyword (deliberate, for backward compat — #1691/#1699). That made per-surface coverage
a matter of *convention*: each new gate class had to be hand-wired into each caller and
nothing failed when one was missed. The measured state at the time this landed was 4 of
15 grounding surfaces arming the #1691 cycle-freshness class and 1 of 15 arming the
#1699 behavioral class — and the "seven days of an experiment" Day-1 leak (#1897) was
the live consequence.

#2056 moved the behavioral class from 1 of 15 to 5 of 15 and, more to the point, retired
the blanket "no map at this layer" exemption that 12 surfaces cited — see the reason
block below. Every surface still exempt from the class now carries a reason specific to
IT, and the difference matters: a registry whose exemptions are all one sentence records
that nobody has looked, while a registry of distinct reasons records what was measured.

#2195 took it to 6 of 15 by paying the one measured cost #2056 had written down rather
than hidden — the stance writer's extra engagement_state read. The remaining 9
exemptions are all structural (the surface is not about Matthew, is third person, is a
post-hoc auditor, or has only a prior-day fact); none of them is discharged by wiring.

HOW IT'S GUARDED (guard the SET, not the instance)
--------------------------------------------------
The surface list is **derived**, never hand-maintained: ``scan_tree()`` AST-scans
``lambdas/`` for every call to a grounding chokepoint and keys it by
``"<module path>::<outermost enclosing function>"``. ``SURFACES`` below only supplies the
*policy* for each discovered surface — which gate classes it must arm, and a written
reason for each one it does not. The test asserts BOTH directions:

  * every discovered surface has a ``SURFACES`` entry  -> a NEW ungated AI surface fails
    the build until someone decides its gate classes (this is the #1967 outcome);
  * every ``SURFACES`` entry still resolves to a real discovered surface -> the registry
    cannot rot into a stale hand-list.

and, per entry, ``required | exempt == GATE_CLASSES`` — so adding a class to
``GATE_CLASSES`` forces a *decision* on every existing surface rather than silently
leaving them all uncovered.
"""

import ast
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)

# ── The gate classes, and how a caller ARMS each one ──────────────────────────
# kwargs: passing ALL of these to grounding_findings() arms the class.
# direct:  calling one of these grounded_generation helpers directly also arms it
#          (ai_calls' coach-v2 pipeline runs the two advisory gates as separate,
#          separately-logged steps rather than through the composite entrypoint).
GATE_CLASSES = {
    # ADR-104 allow-list number gate — the universal floor.
    "numbers": {"kwargs": ("allowed",), "direct": ()},
    # #1242 fabricated-date gate.
    "dates": {"kwargs": ("allowed_dates",), "direct": ()},
    # #1691 stale_baseline/stale_phase + #1897 experiment_span — the cycle anchors.
    "freshness": {
        "kwargs": ("generation_date_iso", "start_date_iso"),
        "direct": ("baseline_freshness_findings", "experiment_span_findings"),
    },
    # #1699 ungrounded-behavioral (same-day completed-action claim with no log).
    "behavioral": {"kwargs": ("available_logs",), "direct": ("ungrounded_behavioral_findings",)},
    # #1968 night-scope (a sleep/recovery/HRV figure with no night name, or one that
    # disagrees with that night's stored value after the wearable revised it).
    "night": {"kwargs": ("nightly_vitals",), "direct": ("night_scoped_vitals_findings",)},
}

# Wrappers that BAKE the gate kwargs inside their own body (the #2276/#1654 extraction
# shape): the wrapper's registered surface proves the composition once; a CALL to the
# wrapper then arms everything it bakes. Without this, a caller module that gates only
# through the wrapper (#3419: site_api_board_panel's worker) scans as gateless — the
# census sees the invoke seam but no decision, and a SURFACES entry for it reads stale.
WRAPPER_CHOKEPOINTS = {"board_grounding_findings": frozenset({"numbers", "dates", "freshness"})}

# The composite entrypoint whose kwargs are read, plus the standalone gate helpers,
# plus the baked wrappers.
CHOKEPOINTS = {"grounding_findings"} | {fn for spec in GATE_CLASSES.values() for fn in spec["direct"]} | set(WRAPPER_CHOKEPOINTS)

# Helpers that SUPPLY gate kwargs as a ``**spread``. AST sees only ``**call()``, so the
# provider has to declare what it arms. Renaming the provider without updating this map
# fails the wiring test instead of silently disarming every caller that spreads it.
PARAM_PROVIDERS = {"cycle_gate_params": frozenset({"freshness"})}
PARAM_PROVIDER_MODULE = "lambdas/ai/grounding_gate_params.py"

# ── Reusable exemption reasons (written once, cited per surface) ──────────────
#
# #2056 REPLACED THE BLANKET `_NO_LOG_MAP` EXEMPTION. It read "no per-generation-date
# log-availability map at this layer" and was cited by 12 of the 15 surfaces, which made
# it the registry's one un-actionable line: it named a missing input, not a reason, so it
# could never be discharged surface by surface. Two things closed it.
#
#   1. `ai.behavior_logs` now owns the honest DERIVATIONS of the map — from a render
#      payload, from the stored engagement signal's per-channel `last_log_date`, from a
#      domain snapshot's `days_since_last_*`. Four more surfaces had the input all along
#      and nobody had gone and got it.
#   2. `LogAvailability` lets a caller declare WHICH categories it can answer for. The
#      old bare-set contract read absence as "no log", so a surface that could see food
#      but not steps had to stay dark or flag every step claim falsely. Declared partial
#      coverage is what makes a partial-visibility surface armable *honestly*.
#
# #2195 then closed #2056's ONE recorded residual, the stance writer
# (`coach_history_summarizer::_apply_grounding_gate`). #2056 had correctly measured that
# nothing in that pipeline is day-scoped — it reads only the COACH# partition — so
# arming it needed a real read and #2056 deferred it as an explicit cost decision rather
# than guessing a map. #2195 measured the cost and paid it: ONE eventually-consistent
# GetItem on engagement_state STATE#current PER INVOCATION (hoisted above the 8-coach
# loop, so it does not scale with the loop), on a weekly cron plus a ≤2/day
# platform-wide event-refresh cap — ≤~780 reads a year, well under a cent, and no IAM
# or CDK change since the table grant is already table-level. It arms only where it can
# answer honestly: adaptive-mode writes that record 25 minutes before the weekly run, so
# the map really is same-day there; on the mid-week event path the record predates the
# stance's day and the derivation returns `LogAvailability.none()` rather than grading a
# same-day claim against yesterday's logs.
#
# What is left is not one excuse repeated; it is three distinct structural reasons, and
# each says what would have to become true for the class to arm.
_NOT_ABOUT_MATTHEW = (
    "the #1699 gate checks a SECOND-PERSON same-day claim, and on this surface `you` is "
    "not Matthew — it is the reader (the /api/explain system prompt says so in as many "
    "words: 'The reader is NOT Matthew'), the other coach in the dialogue, or the "
    "curator's own voice. Arming the class here would grade a claim about a stranger "
    "against Matthew's log partitions. No map would fix that; the scoping is the point."
)
_THIRD_PERSON_SURFACE = (
    "structurally out of scope: this surface is third person by construction — the "
    "prompt's own rule is 'You write in third person. Matthew is your subject' — and the "
    "#1699 gate only checks a second-person completed-action claim. Arming it would be a "
    "no-op dressed as coverage. Revisit only if the voice rule changes."
)
_PRIOR_DAY_SCOPED_LOGS = (
    "its one real availability fact is scoped to the WRONG DAY. The nudge shell probes "
    "`macrofactor DATE#{yesterday}` (`nutrition_logged_yesterday`) because the trigger is "
    "about yesterday's expected-complete nutrition day, while #1699 checks claims framed "
    "for TODAY. Passing a prior-day map would grade a same-day claim against the previous "
    "day's logs — a wrong answer, not a partial one. Arming this needs a same-day probe, "
    "which is new I/O this once-a-day pipeline does not otherwise perform."
)
_PRECEDENT_SCOPED_DATES = (
    "uses the framing-scoped precedent check (semantic_recall.precedent_citation_findings) "
    "instead of a blanket date allow-list — documented in-code at the call site: the "
    "coach-v2 allow-list deliberately excludes the few-shot voice block, so a blanket "
    "`allowed_dates` would false-flag ordinary data dates."
)
_AUDITOR = (
    "post-hoc freshness AUDITOR over already-published text, not a generation gate — it "
    "has no prompt/allow-list to ground numbers or dates against and no generation-day "
    "log map. Freshness is the only class that is meaningful (and it is armed)."
)
_NO_NIGHT_MAP = (
    "no night-keyed vitals map at this layer: `nightly_vitals` must be real stored "
    "readings keyed by NIGHT (ai_calls' `_nightly_vitals_for` derives it from the whoop "
    "rows the render already loaded). Passing a guessed or empty map would flag every "
    "sleep/recovery/HRV figure on the surface as unlabeled, which is how a gate gets "
    "switched off. Arming this class here waits on threading that map through — the "
    "same contract `available_logs` (#1699) has, and not a default."
)
_NOT_A_VITALS_SURFACE = (
    "this surface does not narrate night-scoped vitals — it has no sleep, recovery, HRV "
    "or resting-HR figure to scope to a night, so arming the class would be a no-op "
    "rather than coverage. Revisit if its subject matter widens."
)

_ALL = frozenset(GATE_CLASSES)


def _entry(required, exempt):
    return {"required": frozenset(required), "exempt": dict(exempt)}


# ── The registry: policy per DERIVED surface ─────────────────────────────────
SURFACES = {
    "lambdas/ai/ai_calls.py::_ground_legacy_output": _entry(
        ("numbers", "dates", "freshness", "behavioral"),
        {"night": _NO_NIGHT_MAP},
    ),
    "lambdas/ai/ai_calls.py::_run_coach_v2_pipeline": _entry(
        ("numbers", "freshness", "behavioral", "night"),
        {"dates": _PRECEDENT_SCOPED_DATES},
    ),
    # The ONLY surface with no exemption, and the reason is structural rather than
    # diligence. Every other entry here is a BROADCAST: the platform chooses the
    # subject, so a surface that never discusses sleep can honestly exempt `night`.
    # In a chat MATTHEW chooses the subject — he can ask the nutrition coach about
    # his HRV, which is #2343 exactly (a card whose fact block queried macrofactor
    # only, citing one night's real recovery and HRV as today's; the values existed,
    # the DAY was wrong). A surface that cannot predict its own topic cannot exempt
    # a class on the grounds that the topic will not come up.
    # #2564: declaring `behavioral` armed here was true of the ARMING and false of the
    # RUNTIME — the gate needs `available_logs` and the live chat call site passed none,
    # so the class could not fire. Now derived per turn from the engagement_state
    # presence record (coach_chat_grounding.chat_available_logs), and pinned end-to-end
    # through the production call path by tests/test_chat_behavioral_gate_2564.py.
    "lambdas/coach/coach_chat_grounding.py::build_grounder": _entry(
        ("numbers", "dates", "freshness", "behavioral", "night"),
        {},
    ),
    # #2419: the ensemble-digest writer, previously the census's tracked defect
    # (UNGATED_READER_KNOWN) — the LLM-written disagreement `topic` served verbatim
    # as /api/coach_analysis's cross_coach_reference with no chokepoint in the
    # module. Now gated on the digest's own inputs, regenerate-once-then-HOLD (the
    # deterministic fallback digest persists instead of gated-out text).
    # #2889: the module's THIRD surface — the ADR-126 reuse re-gate. It is the same
    # check as `_apply_grounding_gate` over the same prose blob and the same allow-list
    # derived from the same `user_message`, run at a DIFFERENT moment: before a stored
    # digest is republished on a later cycle. That is precisely why it exists — the
    # `dates` and `freshness` classes are functions of TODAY, so a digest that was
    # honest when generated can be a fabricated-date / stale-Day-N violation when it is
    # reused, and reusing the ORIGINAL verdict (which is what ADR-126's coach-brief path
    # does) would ship it. Check-only, no corrective regen: a surviving finding means the
    # caller regenerates from scratch, which runs `_apply_grounding_gate` in full.
    "lambdas/coach/coach_ensemble_digest.py::_still_grounded": _entry(
        ("numbers", "dates", "freshness"),
        {
            "behavioral": (
                "identical reasoning to `_apply_grounding_gate` below — this grades the "
                "same cross-coach synthesis prose, which cannot emit a second-person "
                "same-day completed-action claim, and the pipeline still reads only the "
                "COACH# partition, so arming would need a new read to grade a class this "
                "surface cannot emit."
            ),
            "night": _NO_NIGHT_MAP,
        },
    ),
    "lambdas/coach/coach_ensemble_digest.py::_apply_grounding_gate": _entry(
        ("numbers", "dates", "freshness"),
        {
            "behavioral": (
                "the digest is a cross-coach SYNTHESIS — its prose reports what the "
                "coaches' stored outputs SAID (topics, positions, concerns), never a "
                "second-person same-day completed-action claim to Matthew, which is the "
                "only shape #1699 checks. And the pipeline reads ONLY the COACH# "
                "partition (OUTPUT#/COMPRESSED#latest) — the same measured fact #2056 "
                "recorded for the stance pipeline: no behavior log is in hand, so arming "
                "would need a new read to grade a claim class this surface cannot emit. "
                "Revisit if the digest prompt ever asks for direct address of Matthew."
            ),
            "night": _NO_NIGHT_MAP,
        },
    ),
    # #2428: the module's SECOND surface — the COMPRESSED#latest compression writer,
    # previously the census's tracked defect (UNGATED_READER_KNOWN): the compressed
    # state replays into board-answer prompts (site_api_ai_lambda._coach_memory_bits),
    # an internal input laundered into a reader surface. Same arms as the stance
    # surface below; regenerate-once-then-HOLD (the prior COMPRESSED#latest is kept —
    # write skipped — or the deterministic structural fallback stands in).
    # #2418: the DERIVED READER PROSE of an OUTPUT# record — observatory_summary,
    # key_recommendation, elena_quote. Six serving paths publish these in preference to
    # the coach's own gated `content` (site_api_coach_narrative, site_api_coach_profile,
    # site_api_lambda's coaching-dashboard, coach_observatory_renderer, the Panel
    # podcast, the daily reflection), and until this entry they were the census's
    # tracked defect (UNGATED_READER_KNOWN): two deterministic guards, no registered
    # surface, so the numeric/date/night/freshness class never looked at the text a
    # reader actually gets. Allow-list = the source narrative itself. Regenerate once,
    # then HOLD the whole derived set (nulled) so every read site falls back to
    # `content` — the artifact that passed its own gate at generation time.
    "lambdas/coach/coach_state_updater.py::_gate_derived_prose": _entry(
        ("numbers", "dates", "freshness", "night"),
        {
            "behavioral": (
                "the source narrative ALREADY passed the #1699 gate with a real availability map "
                "(ai_calls arms it on both the legacy and coach-v2 paths), and this surface grades a "
                "CONDENSATION of that narrative against the narrative itself — a behavioral claim in "
                "the summary is either one the source gate already graded or a fabrication the "
                "numbers/dates classes catch as text the source never contained. Arming it here "
                "would need a map this layer does not hold: the state updater is invoked with "
                "`{coach_id, output_text, output_type, generation_date}` and reads no log partition "
                "at all, so a map would be new I/O bought to re-grade a class one gate up. Revisit "
                "if the extraction ever writes prose that is not a condensation of gated text."
            )
        },
    ),
    # #2573: the BLOCKING quality gate's deterministic number pre-pass. It is not a
    # generation surface — it re-runs the ADR-104 number class on a draft the coach-v2
    # pipeline has ALREADY gated, inside a separate Lambda, so that the blocking verdict
    # covers the fabricated-number class its LLM rubric was blind to (measured: 92/92/82).
    "lambdas/coach/coach_quality_gate.py::_number_grounding_report": _entry(
        ("numbers", "freshness"),
        {
            cls: (
                "the quality gate is a SEPARATE Lambda and its event carries only "
                "`{coach_id, output_text, generation_brief, generation_date}` "
                "(ai.quality_gate_contract.quality_gate_event). #2573 threads exactly ONE new input "
                "across that wire — the caller's already-computed numeric allow-list — because the "
                "allow-list is derived from the assembled generation prompt and cannot be "
                f"recomputed here. The {cls} class needs an input this layer does not have and the "
                "wire does not carry, and it is already armed one gate up, at generation time, on "
                "both coach paths (see the ai_calls entries above). Re-grading it here would mean "
                "shipping a second copy of the map to a post-hoc checker, not new coverage. Revisit "
                "only if the gate ever scores text the generation gate never saw."
            )
            for cls in ("dates", "behavioral", "night")
        },
    ),
    "lambdas/coach/coach_history_summarizer.py::_apply_compression_gate": _entry(
        ("numbers", "dates", "freshness", "behavioral"),
        {"night": _NO_NIGHT_MAP},
    ),
    "lambdas/coach/coach_history_summarizer.py::_apply_grounding_gate": _entry(
        ("numbers", "dates", "freshness", "behavioral"),
        {"night": _NO_NIGHT_MAP},
    ),
    "lambdas/coach/inter_coach_dialogue_lambda.py::generate_gated_turn": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NOT_ABOUT_MATTHEW, "night": _NO_NIGHT_MAP},
    ),
    # #2430: the once-a-day coach reflection published to generated/coach_daily.json and
    # rendered on the coach pages. It was never ungated — every line crossed ER-03 —
    # but ER-03 answers "correlative, hedged, no number outside the facts" and nothing
    # else, so a fabricated calendar date or a stale Day-N framing walked straight
    # through a check that looked like a gate. Both checks are fail-closed and both must
    # pass; a held reflection is dropped, and the coach is listed in `skipped`.
    "lambdas/compute/coach_daily_reflection_lambda.py::_grounding_findings": _entry(
        ("numbers", "dates", "freshness"),
        {
            "behavioral": (
                "the reflection re-voices ONE stored COACH#{id} OUTPUT# row — that row is the module's "
                "entire read, and it opens no log partition at all (the same measured fact #2056 recorded "
                "for the stance pipeline and #2419 for the digest). Its subject is the coach's own recent "
                "read of its own domain, not an account of what Matthew did today, which is the only shape "
                "#1699 checks. Arming it would buy a same-day availability probe purely to grade a claim "
                "class this re-voicing does not emit. Revisit if the prompt ever asks for direct address."
            ),
            "night": _NO_NIGHT_MAP,
        },
    ),
    # #2430: the quarterly in-voice memoir (generated/coach_memoirs.json). Its gate was
    # real but partial — fabricated_numbers + the cites_a_miss bar — and invisible here,
    # so the two classes a QUARTER-long retrospective most obviously carries were nobody's
    # decision: the dates of calls it claims to have made, and the span/Day-N framing it
    # sets them in. Allow-lists stay the pre-existing `facts`-wide scope, so this adds
    # classes and narrows nothing. Fail-closed, unchanged: one stricter retry, then drop.
    "lambdas/compute/coach_memoir_lambda.py::gate_check": _entry(
        ("numbers", "dates", "freshness"),
        {
            "behavioral": (
                "the memoir is FIRST-PERSON and retrospective — the prompt's own rule is 'This is YOU "
                "thinking about YOUR OWN calls' over a CLOSED quarter graded weeks earlier — while #1699 "
                "checks a second-person completed-action claim framed for TODAY. The module's only "
                "availability facts are that quarter's LEARNING# rows; passing them as available_logs "
                "would grade a same-day claim against a closed quarter's records, which is the field "
                "note's wrong-day shape a quarter wide — a wrong answer, not a partial one."
            ),
            "night": _NO_NIGHT_MAP,
        },
    ),
    # #2420: the hypothesis engine's TWO reader-bound prose paths (/api/hypotheses
    # serves the stored rows verbatim). The frozen test_spec already protects the
    # verdict (ADR-105); these surfaces protect the prose around it. Generation
    # holds an ungrounded candidate (dropping it — a batch re-call would re-roll
    # the grounded ones); resolution narration regenerates once then holds to the
    # deterministic evidence sentence.
    "lambdas/compute/hypothesis_engine_lambda.py::generate_hypotheses": _entry(
        ("numbers", "dates", "freshness"),
        {
            "behavioral": (
                "the #1699 gate grades a SECOND-PERSON same-day completed-action claim, and "
                "this surface has none by construction: the prompt asks the data-scientist "
                "voice for 'One clear sentence stating the relationship' over a 14-day "
                "window — analytic pattern claims about metrics, addressed to nobody, never "
                "an account of what Matthew did today. Grading it against a same-day log map "
                "would be a no-op dressed as coverage. Revisit if the prompt ever asks for "
                "day-of framing."
            ),
            "night": _NO_NIGHT_MAP,
        },
    ),
    "lambdas/compute/hypothesis_engine_lambda.py::narrate_resolution": _entry(
        ("numbers", "dates", "freshness"),
        {
            "behavioral": (
                "the resolution sentence restates a multi-week deterministic verdict for a "
                "general reader ('Write ONE plain-language sentence explaining what "
                "happened') — retrospective, about the monitoring window's arms and effect, "
                "never a second-person same-day completed-action claim, which is the only "
                "class the #1699 gate checks. Its numeric honesty is exactly what the "
                "required numbers/dates classes cover."
            ),
            "night": _NO_NIGHT_MAP,
        },
    ),
    "lambdas/compute/state_of_matthew_lambda.py::narration_gate": _entry(
        ("numbers", "dates", "freshness", "behavioral"),
        {"night": _NO_NIGHT_MAP},
    ),
    "lambdas/content/review_pack_ranker.py::baseline_mismatch_findings": _entry(
        ("freshness",),
        {"numbers": _AUDITOR, "dates": _AUDITOR, "behavioral": _AUDITOR, "night": _AUDITOR},
    ),
    "lambdas/emails/ai_review_pack_lambda.py::_freshness_findings_for": _entry(
        ("freshness",),
        {"numbers": _AUDITOR, "dates": _AUDITOR, "behavioral": _AUDITOR, "night": _AUDITOR},
    ),
    "lambdas/emails/chronicle_prompt.py::installment_grounding_findings": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _THIRD_PERSON_SURFACE, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/emails/coach_nudge_lambda.py::_gate": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _PRIOR_DAY_SCOPED_LOGS, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/emails/daily_debrief_lambda.py::narrate": _entry(
        ("numbers", "dates", "freshness", "behavioral"),
        {"night": _NO_NIGHT_MAP},
    ),
    # #2423: the ONLY AI sender addressed to a human who is not Matthew (the partner
    # address from SSM). Regenerate-once-then-HOLD; a held draft falls back to the
    # deterministic data-only email. Its second seam (the direct-bedrock fallback)
    # was retired in the same change — the #2390 census asserts one seam remains.
    "lambdas/emails/partner_email_lambda.py::_grounding_gate": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NOT_ABOUT_MATTHEW, "night": _NO_NIGHT_MAP},
    ),
    # #2430: the meal-photo calibration probe. The macro ESTIMATE is deliberately outside
    # every gate class — it is a guess whose whole purpose is to be graded, and grading it
    # is the exhibit (/method/eyeball/). The `note` is the module's ONE free-text field:
    # prose the model writes about the photo, stored on the estimate row beside the numbers
    # the reliability chart is built from. Same shape as reading_enrich's `themes` — the
    # deterministic parts (macros, the closed confidence set) are checked as data, and the
    # one string that can carry a CLAIM crosses the chokepoint. Fail-closed on the note
    # alone: a flagged note is dropped and the graded estimate stands.
    "lambdas/experiment/eyeball_calibration.py::_grounded_note": _entry(
        ("numbers", "dates", "freshness"),
        {
            "behavioral": (
                "the surface is a phrase describing FOOD IN A PHOTOGRAPH — 'one short phrase on what you "
                "saw', written by a probe the prompt tells in as many words is NOT a food logger. There is "
                "no second-person same-day completed-action claim to grade (#1699's only shape) and no "
                "behavior log could make one legitimate; what is load-bearing here is that the phrase "
                "invents no number the estimate itself does not assert, and cites no calendar date at all "
                "(allowed_dates=set() — for a description of a photo, every date is fabricated)."
            ),
            "night": _NOT_A_VITALS_SURFACE,
        },
    ),
    # #2421: the module's SINGLE chokepoint. It used to be `generate_and_cache` and only
    # that — the Mode-B correction rewrote the text AFTER this gate ran, and the weekly
    # priority, the experiment arc and the month rollup never entered a gate at all (the
    # #2390 census's PARTIAL_COVERAGE overlap). All six model calls now route through
    # `_gate_prose`, so the overlap retired and there is one surface to keep honest
    # instead of four idioms to keep in sync.
    "lambdas/intelligence/ai_expert_analyzer_lambda.py::_gate_prose": _entry(
        ("numbers", "freshness", "night", "behavioral"),
        {
            "dates": (
                "the analyzer's allow-list is assembled from prompt + shared system + "
                "canonical facts, but its narratives cite dates drawn from retrieved "
                "blocks that are summarized rather than quoted into those sources — a "
                "blanket date gate needs that source audit first. (#2056 took the first "
                "bite of the module's ADR-080 split — the DATE#-recency helpers moved to "
                "intelligence/item_recency.py to make room under the 2,000-line handler "
                "cap — but the date-source audit is still the blocker here, not space.)"
            ),
        },
    ),
    # #2426: the weekly field note (/api/field_notes) — was gated by the single-row
    # hard_canonical_contradictions count only, and invisible to this registry.
    # Allow-list = the generation prompt (the week's computed data + prior-note
    # excerpts); regenerate-once-then-hold in the caller.
    "lambdas/intelligence/field_notes_lambda.py::_note_grounding_findings": _entry(
        ("numbers", "dates", "freshness"),
        {
            "behavioral": (
                "the field note narrates the CLOSED prior week (generated after the week "
                "ends), while the #1699 gate checks a completed-action claim framed for "
                "TODAY. The module's only availability facts are that week's day rows — "
                "passing them as available_logs would grade a same-day claim against last "
                "week's records, a wrong answer rather than a partial one (the nudge "
                "shell's prior-day shape, a week wider). Arming this needs a "
                "generation-day probe this weekly pipeline does not otherwise perform."
            ),
            "night": _NO_NIGHT_MAP,
        },
    ),
    "lambdas/reading/horizons_retrospective.py::_grounding_gate": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NOT_ABOUT_MATTHEW, "night": _NOT_A_VITALS_SURFACE},
    ),
    # #2425: the constellation's idea extraction — labels/gists land on the IDEA
    # public allowlist (/api/constellation). The prompt's own grounding contract
    # ("grounded ONLY in the text you're given") is now code: the allow-list is
    # derived from the owner's takeaway/notes + the book title, and an idea whose
    # label or gist carries a number/date he never wrote is HELD (dropped — "no
    # invented ideas" is the module contract, and the fill machinery can re-run).
    "lambdas/reading/reading_constellation.py::_idea_grounding_findings": _entry(
        ("numbers", "dates", "freshness"),
        {
            "behavioral": (
                "the #1699 gate checks a SECOND-PERSON same-day completed-action claim, and an "
                "idea label/gist is a 2-5 word portable BOOK concept distilled from the owner's "
                "own written notes — never an address to Matthew about what he did today. The "
                "numbers/dates classes against his own quoted words are the load-bearing check. "
                "Revisit if the extraction prompt ever asks for behavioral narration."
            ),
            "night": _NO_NIGHT_MAP,
        },
    ),
    # #2425: the reading shelf's enrichment writer (/api/reading_shelf via the BOOK
    # public allowlist). The load-bearing gate is DETERMINISTIC where the field is a
    # closed set — domainTags/era ship only from the in-module vocab constants (the
    # prompt's tag list is generated from the same constants, so prompt and validator
    # cannot drift) and the difficulty subscores are clamped ints plus a page-derived
    # length — because for an enum a vocabulary check is exact where number-grounding
    # would be a no-op dressed as coverage. The ONE free-text field (themes) is what
    # crosses this chokepoint, against the assembled prompt — literally what the
    # model was given. Fail-closed both halves: a missing gate holds all themes.
    "lambdas/reading/reading_enrich.py::_grounded_themes": _entry(
        ("numbers", "dates", "freshness"),
        {
            "behavioral": (
                "the surface tags a BOOK — the system prompt's own rule is 'never opinions "
                "about the reader', and its output is tags and short theme phrases about the "
                "text, so there is no second-person same-day completed-action claim (#1699's "
                "only shape) to grade, and no behavior log could make one legitimate. Revisit "
                "if enrichment ever starts describing Matthew's reading behavior."
            ),
            "night": _NOT_A_VITALS_SURFACE,
        },
    ),
    # #2276/#1654: moved to web/site_api_ai_prompt.py when site_api_ai_lambda crossed the
    # god-module gate. Same function, same arms — only the module owning it changed.
    "lambdas/web/site_api_ai_prompt.py::board_grounding_findings": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NOT_ABOUT_MATTHEW, "night": _NO_NIGHT_MAP},
    ),
    # #3419: the board's per-persona generation (and its fail-closed ADR-104 gate,
    # one corrective rewrite max) moved to the extracted panel sibling's worker —
    # same gate core (board_grounding_findings, called through the host module),
    # same arms as the prompt-module entry above.
    "lambdas/web/site_api_board_panel.py::_generate": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NOT_ABOUT_MATTHEW, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/web/site_api_ai_lambda.py::_handle_ask": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NOT_ABOUT_MATTHEW, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/web/site_api_ai_lambda.py::_handle_explain": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NOT_ABOUT_MATTHEW, "night": _NO_NIGHT_MAP},
    ),
    # #3419: the follow-up leg was always gated through board_grounding_findings;
    # the wrapper-chokepoint scan now names it as its own surface — registered with
    # the same arms/exemptions as the opening board turn.
    "lambdas/web/site_api_ai_lambda.py::_handle_board_followup": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NOT_ABOUT_MATTHEW, "night": _NO_NIGHT_MAP},
    ),
}


# ── The derivation ───────────────────────────────────────────────────────────
def _classes_for_call(func_name, kwarg_names, spread_providers):
    """Gate classes a single call arms."""
    armed = set(WRAPPER_CHOKEPOINTS.get(func_name, frozenset()))
    for cls, spec in GATE_CLASSES.items():
        if func_name in spec["direct"] and (not spec["kwargs"] or all(k in kwarg_names for k in spec["kwargs"])):
            armed.add(cls)
        elif func_name == "grounding_findings" and spec["kwargs"] and all(k in kwarg_names for k in spec["kwargs"]):
            armed.add(cls)
    for provider in spread_providers:
        armed |= set(PARAM_PROVIDERS.get(provider, ()))
    return armed


def scan_source(rel_path, source):
    """{surface_key: set(gate classes armed)} for one module's source text.

    The surface key is ``"<rel_path>::<outermost enclosing function>"`` — outermost so a
    nested ``_findings_fn`` closure (the shared regen-once shape) is attributed to the
    real surface, and so the key survives a closure rename.
    """
    found = {}
    tree = ast.parse(source)

    def visit(node, outer):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, outer or child.name)
                continue
            if isinstance(child, ast.Call):
                fn = child.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
                if name in CHOKEPOINTS:
                    kwarg_names = {k.arg for k in child.keywords if k.arg}
                    spreads = set()
                    for k in child.keywords:
                        if k.arg is None and isinstance(k.value, ast.Call):
                            v = k.value.func
                            spreads.add(v.id if isinstance(v, ast.Name) else getattr(v, "attr", ""))
                    key = f"{rel_path}::{outer or '<module>'}"
                    found.setdefault(key, set())
                    found[key] |= _classes_for_call(name, kwarg_names, spreads)
            visit(child, outer)

    visit(tree, None)
    return found


def scan_tree(repo=REPO):
    """{surface_key: set(gate classes armed)} across all of ``lambdas/``.

    ``grounded_generation.py`` itself is skipped — it DEFINES the chokepoints and its
    internal dispatch is not a surface.
    """
    found = {}
    root = os.path.join(repo, "lambdas")
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(base, f)
            rel = os.path.relpath(path, repo)
            if rel == "lambdas/ai/grounded_generation.py":
                continue
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            if not any(cp in source for cp in CHOKEPOINTS):
                continue
            for key, classes in scan_source(rel, source).items():
                found.setdefault(key, set())
                found[key] |= classes
    return found


# ═════════════════════════════════════════════════════════════════════════════
# #3614 — the THIRD facet: audience + fail mode, per surface, AST-checked
# ═════════════════════════════════════════════════════════════════════════════
#
# WHY. Until this block the key union across all 32 entries was exactly
# {required, exempt}: which gate CLASSES a surface arms, and why not. The thing
# the aiq anchor actually asks for — "the audience-correct fail mode (fail-closed
# public, keep-best internal)" — was enforced by convention everywhere, and
# `lambdas/ai/grounded_generation.py` says so in as many words ("the caller's
# choice"). Convention is what #1967 replaced for the class list; this replaces it
# for the disposition.
#
# THE TWO FACETS.
#   audience   — PUBLIC iff the gated text, or a condensation/quotation of it, can
#                reach a reader who is not Matthew, INCLUDING by being quoted into a
#                prompt that generates reader text. That last clause is why the coach
#                COMPRESSED#latest writer is public: it is never served verbatim, and
#                it is replayed into board-answer prompts.
#   fail_mode  — FAIL_CLOSED iff the disposition site branches on the findings and
#                drops / falls back / holds. KEEP_BEST iff the text ships anyway and
#                the findings are at most logged or recorded as metadata.
#
# WHAT THE AST PROVES, AND WHAT IT DOES NOT. Each entry names its DISPOSITION —
# "<function>@<token>", or "<module>::<function>@<token>" when the decision is taken
# in another module — and `disposition_evidence()` reads that function: the token
# must be real there, and the function must (fail_closed) or must not (keep_best)
# ACT on it. "Act" is deliberately narrow and structural: an `if` on the token whose
# branch returns / continues / breaks / raises / rebinds, a `return X if token else Y`,
# or a predicate return (`return not findings`). A mention inside a log call, an
# f-string or a `len()` is NOT an act — that is precisely the keep-best shape.
# What this does NOT prove is data provenance: it does not follow the findings value
# across the wire into the disposition function (`coach_quality_gate` hands its report
# to a separate Lambda's caller, and the review-pack auditors have no draft at all).
# Provenance is what the written reason carries; the AST carries the disposition.
#
# THE CONTROL. Flipping one public surface from fail_closed to keep_best reds the
# facet test two ways — the AST still finds the hold branch, and the public keep-best
# residual set below gains a member it does not name. Both directions are exercised
# on a COPY of the registry in tests/test_grounding_sets_3614.py, so the control runs
# on every build rather than once in a session.

PUBLIC = "public"
INTERNAL = "internal"
AUDIENCES = frozenset({PUBLIC, INTERNAL})

FAIL_CLOSED = "fail_closed"
KEEP_BEST = "keep_best"
FAIL_MODES = frozenset({FAIL_CLOSED, KEEP_BEST})

FACET_KEYS = ("audience", "fail_mode", "disposition", "facet_reason")

# The one disposition that is not a call site: a post-hoc AUDITOR re-grades text that
# was published long ago, so there is no draft to hold and no generation to fall back
# to — the finding becomes an advisory flag beside an entry that ships either way. Only
# a surface whose gate-class exemptions already cite the measured `_AUDITOR` reason may
# use it (asserted, so this cannot become a way to dodge the AST check).
AUDITOR_NO_DRAFT = "auditor:no-draft-to-dispose"

# The measured residual, pinned by NAME (#3614). A public surface SHOULD be fail-closed;
# these three are not, and each is a recorded decision rather than an oversight. A fourth
# public keep-best surface reds `test_public_keep_best_residual_is_pinned` — which is the
# flip control's second edge.
PUBLIC_KEEP_BEST_RESIDUAL = frozenset(
    {
        "lambdas/ai/ai_calls.py::_run_coach_v2_pipeline",
        "lambdas/coach/inter_coach_dialogue_lambda.py::generate_gated_turn",
        "lambdas/emails/chronicle_prompt.py::installment_grounding_findings",
    }
)


def _facet(audience, fail_mode, disposition, reason):
    return {"audience": audience, "fail_mode": fail_mode, "disposition": disposition, "facet_reason": reason}


SURFACE_FACETS = {
    "lambdas/ai/ai_calls.py::_ground_legacy_output": _facet(
        INTERNAL,
        KEEP_BEST,
        "_ground_legacy_output@_left",
        "The four legacy daily-brief narratives go to ONE address — daily_brief_lambda's EMAIL_RECIPIENT, Matthew — and are "
        "never published; the archived copy feeds the Sunday review pack, itself internal. Keep-best by construction: "
        "`regen_once` returns the better of the two drafts and the residual `_left` is only printed, so a finding costs a log "
        "line rather than blanking his brief. Correct for an internal surface, and it is why the coach-brief archive carries "
        "the findings in meta for the review pack to flag later.",
    ),
    "lambdas/ai/ai_calls.py::_run_coach_v2_pipeline": _facet(
        PUBLIC,
        KEEP_BEST,
        "_run_coach_v2_pipeline@_left",
        "The coach narrative IS reader text — it is written to OUTPUT# and served by the coach pages and /api/coach_*. This "
        "step is nevertheless keep-best at its own call site: `regen_once` keeps the better draft and nothing branches on "
        "`_left`. The fail-closed half of this pipeline is one step later, in a SEPARATE registered surface — "
        "coach_quality_gate::_number_grounding_report, whose deterministic verdict sets passed=False and makes this function "
        "return CoachHold. Recorded rather than smoothed over: this is one of the three public keep-best surfaces, and the "
        "composite is fail-closed only because that other surface is.",
    ),
    "lambdas/coach/coach_chat_grounding.py::build_grounder": _facet(
        INTERNAL,
        FAIL_CLOSED,
        "lambdas/coach/coach_chat.py::run_turn@findings",
        "The chat is Matthew's own conversation with a coach (Telegram and his own clients); nothing under lambdas/web reads "
        "the CHAT# partition. It is held to the public bar anyway, for the reason this entry's gate-class block already "
        "gives — in a chat HE chooses the subject, so the surface cannot predict its own topic. `run_turn` returns the reply "
        "only when `findings` is empty, retries once with the offending claim named, then returns the held reply, which is "
        "stored so the deferral stays on the record.",
    ),
    "lambdas/coach/coach_ensemble_digest.py::_still_grounded": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_still_grounded@findings",
        "It re-grades a STORED digest against today's inputs before republication, and the digest is reader text "
        "(site_api_coach_stance reads ENSEMBLE#digest; the Friday Panel quotes it). Check-only and fail-closed: `return not "
        "findings` is the entire disposition — a surviving finding denies the reuse, and the caller regenerates from scratch "
        "through the full gate below.",
    ),
    "lambdas/coach/coach_ensemble_digest.py::_apply_grounding_gate": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "lambda_handler@adr104_findings",
        "The digest's prose is served (/api/coach_analysis's cross_coach_reference, the stance endpoint, the Panel). "
        "Fail-closed: on any finding surviving the one regen the handler replaces the model digest with the deterministic "
        "`_build_default_digest` and stamps `_grounding_hold`, so text that failed the gate is never persisted and never "
        "earns a reuse cache slot.",
    ),
    "lambdas/coach/coach_history_summarizer.py::_apply_compression_gate": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_compress_coach@findings",
        "COMPRESSED#latest is never served verbatim, but it is replayed into board-answer prompt assembly "
        "(site_api_ai_lambda._coach_memory_bits) — an internal record laundered into reader text, which is exactly the reach "
        "clause in this registry's audience rule. Fail-closed: `_compress_coach` returns the PRIOR COMPRESSED#latest (or the "
        "structural fallback when there is no prior) whenever findings survive the regen, so the write is skipped rather "
        "than made.",
    ),
    "lambdas/coach/coach_history_summarizer.py::_apply_grounding_gate": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_run_stance@adr104_findings",
        "The stance is reader text — site_api_coach_stance serves STANCE#latest. Fail-keep-priors, which is a fail-closed "
        "shape: the gate stamps `_adr104_findings` on the record and `_run_stance` pops it, and on any residual finding it "
        "returns `written: False` without calling `_write_stance`, so a stance that still cites an ungrounded number is "
        "never written over a good one.",
    ),
    "lambdas/coach/coach_quality_gate.py::_number_grounding_report": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_apply_number_grounding_verdict@findings",
        "Its own output is a verdict, not prose, but the TEXT it grades is the coach draft that ships to readers — so the "
        "audience is theirs. Fail-closed and structurally so: `_apply_number_grounding_verdict` sets passed=False on any "
        "measured finding, the LLM judge cannot overrule it, and ai_calls turns that `passed` into a CoachHold. Note the "
        "honest limit of the AST check here: the findings travel across a Lambda wire, so the token this entry names is "
        "bound from the report dict rather than from the gate call.",
    ),
    "lambdas/coach/coach_state_updater.py::_gate_derived_prose": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_write_output_record@_gate_findings",
        "The derived condensations (observatory_summary, key_recommendation, elena_quote) are what six serving paths publish "
        "in preference to the coach's own `content`. Fail-closed on the derived set only: `_write_output_record` calls "
        "`coach_derived_prose.hold(extraction)` on any residual finding, nulling the whole set so every read site falls back "
        "to the narrative that passed its own gate. The record itself still ships — that is the point of holding the "
        "condensation rather than the row.",
    ),
    "lambdas/coach/inter_coach_dialogue_lambda.py::generate_gated_turn": _facet(
        PUBLIC,
        KEEP_BEST,
        "_air_one@left1",
        "The exchange is published: the THREAD# rows under ENSEMBLE#dispute are read by site_api_coach_stance's dispute "
        "reader. Keep-best: `regen_once` returns the better turn and `_air_one` records `gate_findings_left` as a COUNT on "
        "the turn, branching only on an empty reply, never on the findings. So a residual finding is airing on a reader "
        "surface with a number beside it — the second of the three public keep-best surfaces, and the one whose residual is "
        "visible in the stored record.",
    ),
    "lambdas/compute/coach_daily_reflection_lambda.py::_grounding_findings": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "lambda_handler@ok",
        "The reflection is published to generated/coach_daily.json and rendered on the coach pages with no second gate "
        "downstream. Fail-closed through `_accepts`, which ANDs the ER-03 verdict with an empty finding list: the handler "
        "regenerates once stricter, and a coach that still fails is added to `skipped` — dropped, never shipped.",
    ),
    "lambdas/compute/coach_memoir_lambda.py::gate_check": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_generate_memoir@ok",
        "The quarterly memoir is published to generated/coach_memoirs.json. Fail-closed: `_generate_memoir` retries once "
        "with the reasons named and returns `(None, reasons2)` when the second draft still fails, so a memoir that fails "
        "the gate twice is dropped rather than shipped, and the flagged pair is retained as eval data.",
    ),
    "lambdas/compute/hypothesis_engine_lambda.py::generate_hypotheses": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "generate_hypotheses@findings",
        "Generated hypothesis prose is served verbatim by /api/hypotheses. Fail-closed per candidate: a hypothesis whose "
        "reader-bound prose carries a finding is HELD with a `continue` — it is simply not stored, and the grounded "
        "candidates from the same batch still land (a batch re-call would re-roll them, which is why the drop is per "
        "candidate rather than per batch).",
    ),
    "lambdas/compute/hypothesis_engine_lambda.py::narrate_resolution": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "narrate_resolution@findings",
        "The resolution sentence is appended to last_evidence, which /api/hypotheses serves. Fail-closed: one correction "
        'pass, then `return ""` on any surviving finding — which leaves the DETERMINISTIC evidence sentence as the only '
        "stored evidence, the fallback the regenerate-or-hold contract asks for.",
    ),
    "lambdas/compute/state_of_matthew_lambda.py::narration_gate": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "narrate@findings",
        "The weekly State of Matthew narration is reader text on the site. Fail-closed: `narrate` returns the deterministic "
        "fallback narrative with reason=grounding_gate on any finding or banned causal connective, and retains the flagged "
        "draft/final pair as labeled eval data.",
    ),
    "lambdas/content/review_pack_ranker.py::baseline_mismatch_findings": _facet(
        INTERNAL,
        KEEP_BEST,
        AUDITOR_NO_DRAFT,
        "A post-hoc auditor over ALREADY-PUBLISHED archived text, ranked into Matthew's own Sunday review pack — no reader, "
        "no draft, and nothing to hold: the finding becomes a score component and an advisory flag beside an entry that "
        "ships either way. There is therefore no disposition call site for the AST to read, which is what the "
        "auditor sentinel records; the fail-mode is keep-best in the only sense available to an auditor.",
    ),
    "lambdas/emails/ai_review_pack_lambda.py::_freshness_findings_for": _facet(
        INTERNAL,
        KEEP_BEST,
        AUDITOR_NO_DRAFT,
        "The same auditor shape one layer up: it re-runs the freshness class over an archived coach_brief and renders a "
        "warning banner into the review-pack email Matthew reads. The entry is rendered whether or not the banner appears, "
        "so there is no draft to drop and no generation to fall back to — advisory by construction, and fail-soft so a bad "
        "entry never breaks the pack.",
    ),
    "lambdas/emails/chronicle_prompt.py::installment_grounding_findings": _facet(
        PUBLIC,
        KEEP_BEST,
        "lambdas/emails/wednesday_chronicle_lambda.py::_handler_core@_residual",
        "The chronicle is the most public narrative the platform ships — emailed to subscribers and published on the site. "
        "It is nevertheless keep-best: `_handler_core` runs `regen_once`, logs 'chronicle keeps N residual grounding "
        "findings (best draft)' and carries on into Margaret's edit pass and the presence gate. The DELIBERATE reason is "
        "that a held chronicle is a missing weekly issue, and the two later gates (#914 presence-ack, the privacy filter) "
        "are the ones allowed to hold it — but the ADR-104 residual does ship. Third of the three public keep-best "
        "surfaces, and the one most worth revisiting.",
    ),
    "lambdas/emails/coach_nudge_lambda.py::_gate": _facet(
        INTERNAL,
        FAIL_CLOSED,
        "lambda_handler@findings",
        "The nudge is an email to Matthew alone. Fail-closed regardless, by the AC4 rule: a non-empty finding list means "
        "DROP SILENTLY — the handler writes the copy verbatim as a BLOCKED row for audit, never delivers it, never "
        "regenerates, and the day stays consumed so the anti-nag contract holds.",
    ),
    "lambdas/emails/daily_debrief_lambda.py::narrate": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "narrate@findings",
        "The debrief is published as a podcast episode under generated/podcast/debrief with its own RSS feed, so the "
        "audience is readers/listeners, not just Matthew. Fail-closed and single-shot: on any finding or causal hit it "
        "returns the deterministic template with narrated=False — it never regenerates, because the episode is one call "
        "per day.",
    ),
    "lambdas/emails/partner_email_lambda.py::_grounding_gate": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "build_commentary@findings",
        "The only AI sender addressed to a human who is not Matthew — a third party who cannot check the platform's "
        "numbers, which is the audience test this registry uses rather than 'is it on the website'. Fail-closed: "
        "`build_commentary` regenerates once and then returns None, and the caller sends the deterministic data-only email "
        "instead.",
    ),
    "lambdas/experiment/eyeball_calibration.py::_grounded_note": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_grounded_note@findings",
        "The note rides the estimate row the /method/eyeball/ exhibit renders. Fail-closed on the NOTE alone: "
        "`return None if findings else str(note)` drops the phrase and keeps the graded estimate, because holding the "
        "estimate would delete a measured data point over a descriptive sentence.",
    ),
    "lambdas/intelligence/ai_expert_analyzer_lambda.py::_gate_prose": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_gate_prose@_left",
        "All six of the analyzer's model calls are reader-bound (the observatory narratives, the weekly priority, the "
        'experiment arc, the month rollup). Fail-closed at the chokepoint itself: one corrective rewrite, then `return ""` '
        "on any residual finding, and the caller keeps the PRIOR cached record serving. Gate-infra failure holds too "
        "(#2763), which is the inverse of the fail-open shape the /explain endpoint had to fix in #2393.",
    ),
    "lambdas/intelligence/field_notes_lambda.py::_note_grounding_findings": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "generate_field_notes@findings",
        "The weekly field note is the public Third Wall (/api/field_notes). Fail-closed: one strict rewrite kept only if it "
        "strictly improves, and if the best draft still carries findings the note is HELD — nothing is written, so the "
        "endpoint serves the previous week rather than failed text. The gate itself also fails closed on its own "
        "unavailability, returning a synthetic gate_error finding.",
    ),
    "lambdas/reading/horizons_retrospective.py::_grounding_gate": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "generate@findings",
        "The retrospective is the reader hook on the public /data/horizons/ feed. Fail-closed: `generate` returns a HELD "
        "status carrying the finding details instead of the text, and a gate that is unavailable or raises returns a "
        "synthetic finding rather than the ungated draft.",
    ),
    "lambdas/reading/reading_constellation.py::_idea_grounding_findings": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "extract_ideas@findings",
        "Idea labels and gists land on the IDEA public allow-list (/api/constellation). Fail-closed per idea: "
        "`extract_ideas` skips the candidate with a `continue` on any finding — 'no invented ideas' is the module contract "
        "and the fill machinery can re-run — and a gate that raises holds the idea too.",
    ),
    "lambdas/reading/reading_enrich.py::_grounded_themes": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_grounded_themes@findings",
        "Themes are served on the BOOK public allow-list (/api/reading_shelf). Fail-closed per theme: a flagged phrase is "
        "dropped with a `continue`, and a missing or raising gate holds ALL themes rather than waving any through.",
    ),
    "lambdas/web/site_api_ai_prompt.py::board_grounding_findings": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "lambdas/web/site_api_board_panel.py::_generate@_gf",
        "The shared board gate core — it has no call site of its own; both consumers are registered surfaces in their own "
        "right and BOTH dispose identically: one corrective rewrite, then the in-voice refusal copy replaces the answer. "
        "The disposition named here is the opening board turn; the follow-up leg's is its own entry below.",
    ),
    "lambdas/web/site_api_board_panel.py::_generate": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_generate@_gf",
        "The board answer is served to any reader of /api/board_ask. Fail-closed: one bounded corrective rewrite inside the "
        "board rate limit, and if the retry is still ungrounded the persona's text becomes the honest in-voice refusal — "
        "never a fabricated figure — with the flagged draft retained as eval data.",
    ),
    "lambdas/web/site_api_ai_lambda.py::_handle_ask": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_handle_ask@_pre",
        "/api/ask answers an anonymous reader. Fail-closed: one corrective regen, and an answer that is still ungrounded is "
        "replaced by the refusal copy ('I couldn't ground part of that answer …') before the 200 is returned.",
    ),
    "lambdas/web/site_api_ai_lambda.py::_handle_explain": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_handle_explain@grounding_findings",
        "/api/explain hands a reader 3-4 sentences about a page they are looking at. Fail-closed with no regen at all: a "
        "finding replaces the explanation with _EXPLAIN_GROUNDING_REFUSAL, and since #2393 so does a PARTIAL bundle that "
        "cannot import the gate — the ImportError branch refuses rather than serving ungated Haiku output. The disposition "
        "token here is the gate CALL itself, because the finding list is never bound to a name.",
    ),
    "lambdas/web/site_api_ai_lambda.py::_handle_board_followup": _facet(
        PUBLIC,
        FAIL_CLOSED,
        "_handle_board_followup@_gf",
        "The follow-up turn is served to the same anonymous reader as the opening one and replays server-stored prior "
        "turns. Fail-closed identically: one corrective rewrite, else the refusal copy, with the flagged pair retained.",
    ),
}

# The entries themselves GAIN the facets (#3614) — `SURFACES[key]["audience"]` is the
# registry's own shape, not a second dict a reader has to join by hand. Both directions
# of the key match are asserted in tests/test_grounding_sets_3614.py rather than here:
# an import-time assertion would fail collection with a traceback instead of a verdict.
for _key, _facets in SURFACE_FACETS.items():
    if _key in SURFACES:
        SURFACES[_key].update(_facets)


# ── The disposition derivation (#3614) ───────────────────────────────────────
# Structural, deliberately narrow, and documented at the top of this block: these
# four helpers answer ONE question about a named function — does it ACT on a named
# token, or merely mention it?

_DISPOSAL_NODES = (ast.Return, ast.Continue, ast.Break, ast.Raise, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _walk_own_scope(node):
    """Yield every descendant of ``node`` that belongs to its OWN scope.

    Nested defs/lambdas are skipped: a closure's `return` is that closure's
    disposition, not the enclosing surface's. (The regen-once shape nests a
    `_findings_fn`, which would otherwise read as a hold on every surface.)
    """
    for child in ast.iter_child_nodes(node):
        yield child
        if isinstance(child, _NESTED_SCOPES):
            continue
        yield from _walk_own_scope(child)


def _mentions(node, token):
    """``token`` appears in ``node`` as a bare name, or as the function of a call."""
    for n in [node] + list(ast.walk(node)):
        if isinstance(n, ast.Name) and n.id == token:
            return True
        if isinstance(n, ast.Call):
            fn = n.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name == token:
                return True
    return False


def _contains_disposal(stmts):
    """A branch body that does something other than log: returns, continues, breaks,
    raises, or rebinds. A bare call (``logger.warning(...)``) is NOT a disposal — that
    distinction is the whole difference between fail-closed and keep-best."""
    for stmt in stmts:
        if isinstance(stmt, _DISPOSAL_NODES):
            return True
        for n in _walk_own_scope(stmt):
            if isinstance(n, _DISPOSAL_NODES):
                return True
    return False


def _is_predicate(value, token):
    """``return not findings`` / ``return ok and not findings`` — a VERDICT return,
    which is how a check-only surface disposes (the caller acts on the boolean)."""
    for n in [value] + list(ast.walk(value)):
        if isinstance(n, (ast.UnaryOp, ast.BoolOp, ast.Compare)) and _mentions(n, token):
            return True
    return False


def token_is_real(func_node, token):
    """The named token exists in the function: a parameter, something it binds, or a
    function it calls. A renamed variable reds here rather than silently reading as
    'no disposition found'."""
    args = func_node.args
    for a in list(args.args) + list(args.posonlyargs) + list(args.kwonlyargs) + [args.vararg, args.kwarg]:
        if a is not None and a.arg == token:
            return True
    for n in _walk_own_scope(func_node):
        if isinstance(n, ast.Name) and isinstance(getattr(n, "ctx", None), ast.Store) and n.id == token:
            return True
        if isinstance(n, (ast.ExceptHandler,)) and n.name == token:
            return True
        if isinstance(n, ast.Call):
            fn = n.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name == token:
                return True
    return False


def acts_on(func_node, token):
    """Does this function DROP / FALL BACK / HOLD on ``token``?"""
    for n in _walk_own_scope(func_node):
        if isinstance(n, ast.If) and _mentions(n.test, token) and (_contains_disposal(n.body) or _contains_disposal(n.orelse)):
            return True
        if isinstance(n, ast.Return) and n.value is not None:
            if isinstance(n.value, ast.IfExp) and _mentions(n.value.test, token):
                return True
            if _is_predicate(n.value, token):
                return True
    return False


def parse_disposition(key, disposition):
    """``"func@token"`` (the surface's own module) or ``"path.py::func@token"``.

    Returns ``(rel_path, function_name, token)``; raises ValueError on a malformed
    declaration so a typo cannot read as 'nothing to check'.
    """
    if "@" not in disposition:
        raise ValueError(f"{key}: disposition {disposition!r} names no token (expected '<function>@<token>')")
    where, token = disposition.rsplit("@", 1)
    if "::" in where:
        rel_path, func = where.split("::", 1)
    else:
        rel_path, func = key.split("::", 1)[0], where
    if not token or not func:
        raise ValueError(f"{key}: malformed disposition {disposition!r}")
    return rel_path, func, token


def disposition_evidence(key, disposition, repo=REPO):
    """What the tree says about one surface's disposition site.

    ``{"module", "function", "token", "module_exists", "function_found",
    "token_real", "acts"}`` — the caller compares ``acts`` with the declared
    fail mode. Never guesses: a missing module or function is reported as such.
    """
    rel_path, func, token = parse_disposition(key, disposition)
    out = {
        "module": rel_path,
        "function": func,
        "token": token,
        "module_exists": False,
        "function_found": False,
        "token_real": False,
        "acts": False,
    }
    path = os.path.join(repo, rel_path)
    if not os.path.exists(path):
        return out
    out["module_exists"] = True
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            out["function_found"] = True
            out["token_real"] = out["token_real"] or token_is_real(node, token)
            out["acts"] = out["acts"] or acts_on(node, token)
    return out


def facet_problems(surfaces=None, repo=REPO):
    """Every violation of the #3614 facet contract, as a list of strings.

    A pure function over a registry mapping so the flip-one-public-surface control
    can run it against a MUTATED COPY — the must-fail control is a test, not a
    session's memory of having tried it once.
    """
    surfaces = SURFACES if surfaces is None else surfaces
    problems = []
    for key, entry in sorted(surfaces.items()):
        missing = [k for k in FACET_KEYS if k not in entry]
        if missing:
            problems.append(f"{key}: no #3614 facet(s) {missing} — decide the audience and the fail mode")
            continue
        audience, fail_mode = entry["audience"], entry["fail_mode"]
        if audience not in AUDIENCES:
            problems.append(f"{key}: unknown audience {audience!r} (expected one of {sorted(AUDIENCES)})")
        if fail_mode not in FAIL_MODES:
            problems.append(f"{key}: unknown fail_mode {fail_mode!r} (expected one of {sorted(FAIL_MODES)})")
        reason = entry["facet_reason"]
        if not isinstance(reason, str) or len(reason.strip()) < 120:
            problems.append(f"{key}: the facet needs a written reason naming the reader AND what happens to a finding")
        # Half of the audience facet IS derivable: lambdas/web/site_api* is the public
        # serving path by construction (privacy_tier_wiring.family_of makes the same
        # call), so a surface there may not be declared internal.
        if key.startswith("lambdas/web/site_api") and audience != PUBLIC:
            problems.append(f"{key}: a lambdas/web/site_api* surface serves averagejoematt.com — audience cannot be {audience!r}")
        if audience == PUBLIC and fail_mode == KEEP_BEST and key not in PUBLIC_KEEP_BEST_RESIDUAL:
            problems.append(
                f"{key}: declared public + keep_best but is not in PUBLIC_KEEP_BEST_RESIDUAL — a public surface that "
                "ships its best draft with residual findings is a recorded decision, never a default"
            )
        if entry["disposition"] == AUDITOR_NO_DRAFT:
            if fail_mode != KEEP_BEST or _AUDITOR not in set(entry.get("exempt", {}).values()):
                problems.append(
                    f"{key}: the auditor sentinel is only for a post-hoc auditor — the surface must cite the measured "
                    "_AUDITOR exemption reason and keep-best, or it needs a real disposition site"
                )
            continue
        try:
            ev = disposition_evidence(key, entry["disposition"], repo=repo)
        except ValueError as e:
            problems.append(str(e))
            continue
        if not ev["module_exists"]:
            problems.append(f"{key}: disposition names module {ev['module']} — it does not exist")
            continue
        if not ev["function_found"]:
            problems.append(f"{key}: disposition names {ev['module']}::{ev['function']} — no such function (renamed? moved?)")
            continue
        if not ev["token_real"]:
            problems.append(f"{key}: disposition token {ev['token']!r} is not bound, taken or called in {ev['module']}::{ev['function']}")
            continue
        if fail_mode == FAIL_CLOSED and not ev["acts"]:
            problems.append(
                f"{key}: declared fail_closed, but {ev['module']}::{ev['function']} never drops, falls back or holds on "
                f"{ev['token']!r} — it only mentions it (logging a finding is not a fail mode)"
            )
        if fail_mode == KEEP_BEST and ev["acts"]:
            problems.append(
                f"{key}: declared keep_best, but {ev['module']}::{ev['function']} BRANCHES on {ev['token']!r} and "
                "drops/falls back — the declaration and the call site disagree"
            )
    return problems
