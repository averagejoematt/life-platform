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

# The composite entrypoint whose kwargs are read, plus the standalone gate helpers.
CHOKEPOINTS = {"grounding_findings"} | {fn for spec in GATE_CLASSES.values() for fn in spec["direct"]}

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
    "lambdas/web/site_api_ai_lambda.py::_handle_ask": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NOT_ABOUT_MATTHEW, "night": _NO_NIGHT_MAP},
    ),
    "lambdas/web/site_api_ai_lambda.py::_handle_explain": _entry(
        ("numbers", "dates", "freshness"),
        {"behavioral": _NOT_ABOUT_MATTHEW, "night": _NO_NIGHT_MAP},
    ),
}


# ── The derivation ───────────────────────────────────────────────────────────
def _classes_for_call(func_name, kwarg_names, spread_providers):
    """Gate classes a single call arms."""
    armed = set()
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
